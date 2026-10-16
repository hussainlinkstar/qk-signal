"use client";

import { asset } from "@/lib/basePath";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import type {
  AuditJobLiveDebateEvent,
  AuditHistoryItem,
  AuditJobStatusResponse,
  AuditRecordResponse,
} from "@/types/auditWorkspace";
import { isValidHttpUrl, withHttpScheme, type AuditFormValues } from "@/lib/auditFormSchema";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";
import { normalizeReport } from "@/lib/auditWorkspaceUtils";
import { computeAioScore } from "@/lib/aioScore";
import type { AuditStageState, AuditStageStatus, ScanRunPhase } from "@/lib/auditScanRun";
import {
  PROJECT_SETUP_FAILURE_I18N_KEYS,
  resolveProjectSetupFailureKey,
} from "@/lib/projectSetupFailure";
import { resolveProjectTargetCountry } from "@/lib/projectTargetCountry";
import { createAuditJob, estimateAuditCredits, AuditConflictError } from "@/services/auditService";

const STAGE_STATES: readonly AuditStageState[] = [
  "pending",
  "running",
  "completed",
  "failed",
  "skipped",
  "degraded",
  "unknown",
];

const asStageState = (raw: unknown): AuditStageState => {
  const value = String(raw ?? "").toLowerCase();
  return (STAGE_STATES as readonly string[]).includes(value)
    ? (value as AuditStageState)
    : "unknown";
};

/**
 * What the run view needs after the job query is gone.
 *
 * The terminal effect below clears `jobId` and removes the cached job, which
 * is what previously left the failed state with nothing to render. This
 * snapshot is written on every status response and kept afterwards, so the
 * succeeded and failed views still have the stages, the error and the
 * timestamps the approved design states.
 */
export type AuditRunSnapshot = {
  jobId: string;
  phase: Exclude<ScanRunPhase, "idle">;
  targetLabel: string;
  targetUrl: string;
  tier: string;
  stages: AuditStageStatus[];
  error: string | null;
  startedAt: string | null;
  completedAt: string | null;
  auditId: number | null;
};

type UseAuditRunnerParams = {
  getAuthHeaders: () => Promise<Record<string, string>>;
  isSignedIn: boolean;
  form: AuditFormValues;
  preScanResult?: AuditPreScanForecastSeed | null;
  validateForm: () => Promise<boolean>;
  verifyUrlPreflight: (url?: string) => Promise<boolean>;
  fetchAuditRecord: (id: number) => Promise<AuditRecordResponse>;
  invalidateHistory: () => Promise<void>;
  upsertHistoryEntry: (entry: AuditHistoryItem) => void;
  onAuditComplete: (entry: AuditHistoryItem, report: CanonicalAuditReport) => void;
  projectId?: number;
  /** Pass a job ID to re-attach to an already-running audit (e.g. after navigation). */
  reattachJobId?: string | null;
};

type AuditRunContext = {
  targetType: "website" | "brand";
  targetName: string;
  targetUrl: string;
  targetLabel: string;
  tier: string;
};

type AuditPreScanForecastSeed = {
  language: string;
  market_region: string;
  category: string;
  primary_entities?: string[] | null;
  source: string;
  snapshot_title?: string | null;
  snapshot_description?: string | null;
};

type AuditLiveDebateStepStatus = "pending" | "running" | "completed";
type AuditLiveDebateLayerStatus = "pending" | "running" | "completed";
type DebatePipelineType =
  | "fast_3step"
  | "smart_5step"
  | "delta_flow"
  | "legacy_3step"
  | "legacy_high_confidence";

type AuditLiveDebateStep = {
  key: string;
  label: string;
  role: string;
  semanticRole: string | null;
  layer: number | null;
  domain: string | null;
  status: AuditLiveDebateStepStatus;
  provider: string | null;
  model: string | null;
  summary: string | null;
  latencyMs: number | null;
  order: number;
  cascadeRetry: boolean;
  cascadeAttempt: number;
};

type AuditLiveDebateLayer = {
  key: string;
  layer: number;
  label: string;
  parallel: boolean;
  agentsInLayer: number;
  status: AuditLiveDebateLayerStatus;
  totalLatencyMs: number | null;
  agentsCompleted: number;
  agentsFailed: number;
};

export type AuditLiveDebateProgress = {
  mode: "live" | "polling_fallback";
  finished: boolean;
  profile: string | null;
  confidenceScore: number | null;
  fallbackReason: string | null;
  judgeAuthority: string | null;
  pipelineType: DebatePipelineType | null;
  totalAgents: number | null;
  parallelLayers: number | null;
  estimatedDurationS: number | null;
  totalLatencyMs: number | null;
  steps: AuditLiveDebateStep[];
  layers: AuditLiveDebateLayer[];
};

type DebateBlueprintStep = {
  key: string;
  label: string;
  role: string;
  semanticRole: string | null;
  layer: number;
  domain: string | null;
  order: number;
};

type DebateBlueprintLayer = {
  layer: number;
  label: string;
  parallel: boolean;
  steps: DebateBlueprintStep[];
};

type DebatePipelineBlueprint = {
  pipelineType: DebatePipelineType;
  totalAgents: number;
  parallelLayers: number;
  layers: DebateBlueprintLayer[];
};

const PIPELINE_BLUEPRINTS: Record<DebatePipelineType, DebatePipelineBlueprint> = {
  fast_3step: {
    pipelineType: "fast_3step",
    totalAgents: 3,
    parallelLayers: 0,
    layers: [
      {
        layer: 1,
        label: "Proposal",
        parallel: false,
        steps: [
          {
            key: "fast_proposer",
            label: "Generator",
            role: "fast_proposer",
            semanticRole: "generator",
            layer: 1,
            domain: null,
            order: 1,
          },
        ],
      },
      {
        layer: 2,
        label: "Critique",
        parallel: false,
        steps: [
          {
            key: "fast_critic",
            label: "Critic",
            role: "fast_critic",
            semanticRole: "critic",
            layer: 2,
            domain: null,
            order: 2,
          },
        ],
      },
      {
        layer: 3,
        label: "Finalizing",
        parallel: false,
        steps: [
          {
            key: "fast_synthesizer",
            label: "Synthesizer",
            role: "fast_synthesizer",
            semanticRole: "judge",
            layer: 3,
            domain: null,
            order: 3,
          },
        ],
      },
    ],
  },
  smart_5step: {
    pipelineType: "smart_5step",
    totalAgents: 5,
    parallelLayers: 1,
    layers: [
      {
        layer: 1,
        label: "Specialized Generation",
        parallel: true,
        steps: [
          {
            key: "seo_generator",
            label: "SEO Generator",
            role: "seo_generator",
            semanticRole: "generator",
            layer: 1,
            domain: "seo",
            order: 1,
          },
          {
            key: "aeo_geo_generator",
            label: "AIO Generator",
            role: "aeo_geo_generator",
            semanticRole: "generator",
            layer: 1,
            domain: "aeo_geo",
            order: 2,
          },
        ],
      },
      {
        layer: 2,
        label: "Centralized Critique",
        parallel: false,
        steps: [
          {
            key: "centralized_critic",
            label: "Centralized Critic",
            role: "centralized_critic",
            semanticRole: "critic",
            layer: 2,
            domain: "cross_domain",
            order: 3,
          },
        ],
      },
      {
        layer: 3,
        label: "Finalizing",
        parallel: false,
        steps: [
          {
            key: "smart_synthesizer",
            label: "Synthesizer",
            role: "smart_synthesizer",
            semanticRole: "judge",
            layer: 3,
            domain: null,
            order: 4,
          },
        ],
      },
      {
        layer: 4,
        label: "Magistrate Review",
        parallel: false,
        steps: [
          {
            key: "magistrate",
            label: "Magistrate",
            role: "magistrate",
            semanticRole: "judge",
            layer: 4,
            domain: null,
            order: 5,
          },
        ],
      },
    ],
  },
  delta_flow: {
    pipelineType: "delta_flow",
    totalAgents: 8,
    parallelLayers: 2,
    layers: [
      {
        layer: 1,
        label: "Specialized Generation",
        parallel: true,
        steps: [
          {
            key: "seo_generator",
            label: "SEO Generator",
            role: "seo_generator",
            semanticRole: "generator",
            layer: 1,
            domain: "seo",
            order: 1,
          },
          {
            key: "geo_generator",
            label: "AI Visibility Generator",
            role: "geo_generator",
            semanticRole: "generator",
            layer: 1,
            domain: "geo",
            order: 2,
          },
          {
            key: "aeo_generator",
            label: "AI Answers Generator",
            role: "aeo_generator",
            semanticRole: "generator",
            layer: 1,
            domain: "aeo",
            order: 3,
          },
        ],
      },
      {
        layer: 2,
        label: "Domain Critique",
        parallel: true,
        steps: [
          {
            key: "seo_critic",
            label: "SEO Critic",
            role: "seo_critic",
            semanticRole: "critic",
            layer: 2,
            domain: "seo",
            order: 4,
          },
          {
            key: "geo_critic",
            label: "AI Visibility Critic",
            role: "geo_critic",
            semanticRole: "critic",
            layer: 2,
            domain: "geo",
            order: 5,
          },
          {
            key: "aeo_critic",
            label: "AI Answers Critic",
            role: "aeo_critic",
            semanticRole: "critic",
            layer: 2,
            domain: "aeo",
            order: 6,
          },
        ],
      },
      {
        layer: 3,
        label: "Consolidation",
        parallel: false,
        steps: [
          {
            key: "consolidator",
            label: "Consolidator",
            role: "consolidator",
            semanticRole: "consolidator",
            layer: 3,
            domain: null,
            order: 7,
          },
        ],
      },
      {
        layer: 4,
        label: "Global Magistrate",
        parallel: false,
        steps: [
          {
            key: "global_magistrate",
            label: "Global Magistrate",
            role: "global_magistrate",
            semanticRole: "judge",
            layer: 4,
            domain: null,
            order: 8,
          },
        ],
      },
    ],
  },
  legacy_3step: {
    pipelineType: "legacy_3step",
    totalAgents: 3,
    parallelLayers: 0,
    layers: [
      {
        layer: 1,
        label: "Proposal",
        parallel: false,
        steps: [
          {
            key: "proposer",
            label: "Proposer",
            role: "proposer",
            semanticRole: "generator",
            layer: 1,
            domain: null,
            order: 1,
          },
        ],
      },
      {
        layer: 2,
        label: "Challenge",
        parallel: false,
        steps: [
          {
            key: "challenger",
            label: "Challenger",
            role: "challenger",
            semanticRole: "critic",
            layer: 2,
            domain: null,
            order: 2,
          },
        ],
      },
      {
        layer: 3,
        label: "Finalizing",
        parallel: false,
        steps: [
          {
            key: "synthesizer",
            label: "Synthesizer",
            role: "synthesizer",
            semanticRole: "judge",
            layer: 3,
            domain: null,
            order: 3,
          },
        ],
      },
    ],
  },
  legacy_high_confidence: {
    pipelineType: "legacy_high_confidence",
    totalAgents: 3,
    parallelLayers: 0,
    layers: [
      {
        layer: 1,
        label: "Generation",
        parallel: false,
        steps: [
          {
            key: "proposer",
            label: "Generator",
            role: "proposer",
            semanticRole: "generator",
            layer: 1,
            domain: null,
            order: 1,
          },
        ],
      },
      {
        layer: 2,
        label: "Critique",
        parallel: false,
        steps: [
          {
            key: "challenger",
            label: "Critic",
            role: "challenger",
            semanticRole: "critic",
            layer: 2,
            domain: null,
            order: 2,
          },
        ],
      },
      {
        layer: 3,
        label: "Judgment",
        parallel: false,
        steps: [
          {
            key: "synthesizer",
            label: "Judge",
            role: "synthesizer",
            semanticRole: "judge",
            layer: 3,
            domain: null,
            order: 3,
          },
        ],
      },
    ],
  },
};

const FALLBACK_STEP_META: Record<
  string,
  {
    key: string;
    label: string;
    layer: number;
  }
> = {
  proposer: { key: "proposer", label: "Proposer", layer: 1 },
  generator: { key: "generator", label: "Generator", layer: 1 },
  fast_proposer: { key: "fast_proposer", label: "Generator", layer: 1 },
  challenger: { key: "challenger", label: "Challenger", layer: 2 },
  critic: { key: "critic", label: "Critic", layer: 2 },
  fast_critic: { key: "fast_critic", label: "Critic", layer: 2 },
  centralized_critic: { key: "centralized_critic", label: "Centralized Critic", layer: 2 },
  synthesizer: { key: "synthesizer", label: "Synthesizer", layer: 3 },
  judge: { key: "judge", label: "Judge", layer: 3 },
  fast_synthesizer: { key: "fast_synthesizer", label: "Synthesizer", layer: 3 },
  smart_synthesizer: { key: "smart_synthesizer", label: "Synthesizer", layer: 3 },
  magistrate: { key: "magistrate", label: "Magistrate", layer: 4 },
  global_magistrate: { key: "global_magistrate", label: "Global Magistrate", layer: 4 },
  consolidator: { key: "consolidator", label: "Consolidator", layer: 3 },
};

const parseJsonPayload = <T>(rawData: string): T | null => {
  try {
    return JSON.parse(rawData) as T;
  } catch {
    return null;
  }
};

const isTerminalJobStatus = (status: string | null | undefined): boolean =>
  status === "succeeded" || status === "failed";

const createProgressState = (
  mode: AuditLiveDebateProgress["mode"],
  blueprint?: DebatePipelineBlueprint | null
): AuditLiveDebateProgress => ({
  mode,
  finished: false,
  profile: null,
  confidenceScore: null,
  fallbackReason: null,
  judgeAuthority: null,
  pipelineType: blueprint?.pipelineType ?? null,
  totalAgents: blueprint?.totalAgents ?? null,
  parallelLayers: blueprint?.parallelLayers ?? null,
  estimatedDurationS: null,
  totalLatencyMs: null,
  layers:
    blueprint?.layers.map((layer) => ({
      key: `layer-${layer.layer}`,
      layer: layer.layer,
      label: layer.label,
      parallel: layer.parallel,
      agentsInLayer: layer.steps.length,
      status: "pending",
      totalLatencyMs: null,
      agentsCompleted: 0,
      agentsFailed: 0,
    })) ?? [],
  steps:
    blueprint?.layers.flatMap((layer) =>
      layer.steps.map((step) => ({
        key: step.key,
        label: step.label,
        role: step.role,
        semanticRole: step.semanticRole,
        layer: step.layer,
        domain: step.domain,
        status: "pending" as const,
        provider: null,
        model: null,
        summary: null,
        latencyMs: null,
        order: step.order,
        cascadeRetry: false,
        cascadeAttempt: 0,
      }))
    ) ?? [],
});

const cloneProgressState = (
  progress: AuditLiveDebateProgress,
  mode: AuditLiveDebateProgress["mode"]
): AuditLiveDebateProgress => ({
  ...progress,
  mode,
  layers: progress.layers.map((layer) => ({ ...layer })),
  steps: progress.steps.map((step) => ({ ...step })),
});

const normalizePipelineType = (value: string | null | undefined): DebatePipelineType | null => {
  const normalizedValue = String(value ?? "")
    .trim()
    .toLowerCase();
  if (normalizedValue in PIPELINE_BLUEPRINTS) {
    return normalizedValue as DebatePipelineType;
  }
  return null;
};

const resolvePipelineBlueprint = (
  pipelineType: string | null | undefined
): DebatePipelineBlueprint | null => {
  const normalizedPipelineType = normalizePipelineType(pipelineType);
  return normalizedPipelineType ? PIPELINE_BLUEPRINTS[normalizedPipelineType] : null;
};

const mergeProgressWithBlueprint = (
  previous: AuditLiveDebateProgress | null,
  blueprint: DebatePipelineBlueprint,
  mode: AuditLiveDebateProgress["mode"]
): AuditLiveDebateProgress => {
  const seeded = createProgressState(mode, blueprint);
  if (!previous) {
    return seeded;
  }

  const stepsByRole = new Map(previous.steps.map((step) => [step.role, step]));
  seeded.steps = seeded.steps.map((step) => {
    const previousStep = stepsByRole.get(step.role);
    return previousStep
      ? {
          ...step,
          ...previousStep,
          key: step.key,
          label: step.label,
          role: step.role,
          layer: step.layer,
          domain: step.domain,
          order: step.order,
        }
      : step;
  });
  seeded.layers = seeded.layers.map((layer) => {
    const previousLayer = previous.layers.find((entry) => entry.layer === layer.layer);
    return previousLayer
      ? {
          ...layer,
          ...previousLayer,
          key: layer.key,
          layer: layer.layer,
          label: layer.label,
          parallel: layer.parallel,
          agentsInLayer: Math.max(layer.agentsInLayer, previousLayer.agentsInLayer),
        }
      : layer;
  });
  return {
    ...seeded,
    finished: previous.finished,
    profile: previous.profile,
    confidenceScore: previous.confidenceScore,
    fallbackReason: previous.fallbackReason,
    judgeAuthority: previous.judgeAuthority,
    estimatedDurationS: previous.estimatedDurationS,
    totalLatencyMs: previous.totalLatencyMs,
  };
};

const getFallbackStepMeta = (
  role: string | null | undefined,
  semanticRole: string | null | undefined
): { key: string; label: string; layer: number } | null => {
  const semanticKey = String(semanticRole ?? "")
    .trim()
    .toLowerCase();
  if (semanticKey && FALLBACK_STEP_META[semanticKey]) {
    return FALLBACK_STEP_META[semanticKey];
  }

  const roleKey = String(role ?? "")
    .trim()
    .toLowerCase();
  if (roleKey && FALLBACK_STEP_META[roleKey]) {
    return FALLBACK_STEP_META[roleKey];
  }

  return null;
};

const resolvePipelineTypeForEvent = (
  previous: AuditLiveDebateProgress | null,
  event: AuditJobLiveDebateEvent
): DebatePipelineType | null => {
  const explicitPipelineType = normalizePipelineType(event.pipeline_type);
  if (explicitPipelineType) {
    return explicitPipelineType;
  }
  if (previous?.pipelineType) {
    return previous.pipelineType;
  }

  const roleKey = String(event.role ?? "")
    .trim()
    .toLowerCase();
  if (roleKey.startsWith("fast_")) {
    return "fast_3step";
  }
  if (
    roleKey === "aeo_geo_generator" ||
    roleKey === "centralized_critic" ||
    roleKey === "magistrate"
  ) {
    return "smart_5step";
  }
  if (
    roleKey === "geo_generator" ||
    roleKey === "aeo_generator" ||
    roleKey === "geo_critic" ||
    roleKey === "aeo_critic" ||
    roleKey === "consolidator" ||
    roleKey === "global_magistrate"
  ) {
    return "delta_flow";
  }
  return null;
};

const ensureLayerState = (
  progress: AuditLiveDebateProgress,
  layerNumber: number,
  overrides?: Partial<AuditLiveDebateLayer>
): AuditLiveDebateLayer => {
  const existingLayer = progress.layers.find((layer) => layer.layer === layerNumber);
  if (existingLayer) {
    if (overrides) {
      for (const [key, value] of Object.entries(overrides)) {
        if (value !== undefined) {
          Object.assign(existingLayer, { [key]: value });
        }
      }
    }
    return existingLayer;
  }

  const newLayer: AuditLiveDebateLayer = {
    key: `layer-${layerNumber}`,
    layer: layerNumber,
    label: overrides?.label ?? `Layer ${layerNumber}`,
    parallel: overrides?.parallel ?? false,
    agentsInLayer: overrides?.agentsInLayer ?? 0,
    status: overrides?.status ?? "pending",
    totalLatencyMs: overrides?.totalLatencyMs ?? null,
    agentsCompleted: overrides?.agentsCompleted ?? 0,
    agentsFailed: overrides?.agentsFailed ?? 0,
  };
  progress.layers.push(newLayer);
  progress.layers.sort((left, right) => left.layer - right.layer);
  return newLayer;
};

const syncLayerState = (
  progress: AuditLiveDebateProgress,
  layerNumber: number
): AuditLiveDebateProgress => {
  const layer = progress.layers.find((entry) => entry.layer === layerNumber);
  if (!layer) {
    return progress;
  }

  const layerSteps = progress.steps.filter((step) => step.layer === layerNumber);
  if (layerSteps.length > 0) {
    layer.agentsInLayer = Math.max(layer.agentsInLayer, layerSteps.length);
    layer.agentsCompleted = Math.max(
      layer.agentsCompleted,
      layerSteps.filter((step) => step.status === "completed").length
    );
    const hasRunningSteps = layerSteps.some((step) => step.status === "running");
    if (
      layer.totalLatencyMs != null ||
      layer.agentsCompleted + layer.agentsFailed >= layer.agentsInLayer
    ) {
      layer.status = "completed";
    } else if (hasRunningSteps || layer.agentsCompleted > 0) {
      layer.status = "running";
    } else {
      layer.status = "pending";
    }
  }

  return progress;
};

const applyLiveDebateEvent = (
  previous: AuditLiveDebateProgress | null,
  event: AuditJobLiveDebateEvent,
  mode: AuditLiveDebateProgress["mode"]
): AuditLiveDebateProgress | null => {
  const pipelineType = resolvePipelineTypeForEvent(previous, event);
  const blueprint = resolvePipelineBlueprint(pipelineType);
  const nextState =
    blueprint && (!previous || previous.pipelineType !== blueprint.pipelineType)
      ? mergeProgressWithBlueprint(previous, blueprint, mode)
      : previous
        ? cloneProgressState(previous, mode)
        : createProgressState(mode, blueprint);

  nextState.pipelineType = pipelineType ?? nextState.pipelineType;
  nextState.totalAgents =
    typeof event.total_agents === "number"
      ? event.total_agents
      : (nextState.totalAgents ?? blueprint?.totalAgents ?? null);
  nextState.parallelLayers =
    typeof event.parallel_layers === "number"
      ? event.parallel_layers
      : (nextState.parallelLayers ?? blueprint?.parallelLayers ?? null);
  nextState.estimatedDurationS =
    typeof event.estimated_duration_s === "number"
      ? event.estimated_duration_s
      : nextState.estimatedDurationS;
  nextState.profile = event.profile ?? nextState.profile;
  nextState.judgeAuthority = event.judge_authority ?? nextState.judgeAuthority;

  if (event.type === "pipeline_started") {
    return nextState;
  }

  if (event.type === "layer_started" || event.type === "layer_completed") {
    if (typeof event.layer === "number") {
      const layer = ensureLayerState(nextState, event.layer, {
        label: event.layer_name ?? undefined,
        parallel: event.parallel ?? undefined,
        agentsInLayer:
          typeof event.agents_in_layer === "number" ? event.agents_in_layer : undefined,
        status: event.type === "layer_started" ? "running" : "completed",
        totalLatencyMs:
          typeof event.total_latency_ms === "number" ? event.total_latency_ms : undefined,
        agentsCompleted:
          typeof event.agents_completed === "number" ? event.agents_completed : undefined,
        agentsFailed: typeof event.agents_failed === "number" ? event.agents_failed : undefined,
      });
      if (event.type === "layer_started") {
        layer.status = "running";
      }
      syncLayerState(nextState, event.layer);
    }
    return nextState;
  }

  if (event.type === "debate_finished") {
    nextState.finished = true;
    nextState.confidenceScore =
      typeof event.confidence_score === "number"
        ? event.confidence_score
        : nextState.confidenceScore;
    nextState.fallbackReason = event.fallback_reason ?? nextState.fallbackReason;
    nextState.totalLatencyMs =
      typeof event.total_latency_ms === "number"
        ? event.total_latency_ms
        : nextState.totalLatencyMs;
    return nextState;
  }

  const fallbackMeta = getFallbackStepMeta(event.role, event.semantic_role);
  const eventRole = String(event.role ?? fallbackMeta?.key ?? "").trim();
  if (!eventRole) {
    return nextState;
  }

  const existingStepIndex = nextState.steps.findIndex((step) => step.role === eventRole);
  const currentStep =
    existingStepIndex >= 0
      ? nextState.steps[existingStepIndex]
      : {
          key: fallbackMeta?.key ?? eventRole,
          label: fallbackMeta?.label ?? eventRole.replace(/_/g, " "),
          role: eventRole,
          semanticRole: event.semantic_role ?? null,
          layer: typeof event.layer === "number" ? event.layer : (fallbackMeta?.layer ?? null),
          domain: event.domain ?? null,
          status: "pending" as const,
          provider: null,
          model: null,
          summary: null,
          latencyMs: null,
          order: nextState.steps.length + 1,
          cascadeRetry: false,
          cascadeAttempt: 0,
        };

  const isCascadeRetry = event.cascade_retry === true;
  const updatedStep: AuditLiveDebateStep = {
    ...currentStep,
    semanticRole: event.semantic_role ?? currentStep.semanticRole,
    layer: typeof event.layer === "number" ? event.layer : currentStep.layer,
    domain: event.domain ?? currentStep.domain,
    provider: event.provider ?? currentStep.provider,
    model: event.model ?? currentStep.model,
    status: event.type === "step_completed" ? "completed" : "running",
    summary: event.summary ?? currentStep.summary,
    latencyMs: typeof event.latency_ms === "number" ? event.latency_ms : currentStep.latencyMs,
    cascadeRetry: isCascadeRetry || currentStep.cascadeRetry,
    cascadeAttempt:
      typeof event.cascade_attempt === "number"
        ? event.cascade_attempt
        : currentStep.cascadeAttempt,
  };

  if (existingStepIndex >= 0) {
    nextState.steps[existingStepIndex] = updatedStep;
  } else {
    nextState.steps.push(updatedStep);
  }

  if (updatedStep.layer != null) {
    ensureLayerState(nextState, updatedStep.layer, {
      agentsInLayer: Math.max(
        nextState.steps.filter((step) => step.layer === updatedStep.layer).length,
        1
      ),
      status: "running",
    });
    syncLayerState(nextState, updatedStep.layer);
  }

  nextState.steps.sort((left, right) => {
    const leftLayer = left.layer ?? Number.MAX_SAFE_INTEGER;
    const rightLayer = right.layer ?? Number.MAX_SAFE_INTEGER;
    if (leftLayer !== rightLayer) {
      return leftLayer - rightLayer;
    }
    return left.order - right.order;
  });

  return nextState;
};

const resolveAuditTargetType = (value: string | null | undefined): "website" | "brand" =>
  String(value ?? "")
    .trim()
    .toLowerCase() === "brand"
    ? "brand"
    : "website";

// Users paste bare hosts ("example.com", "www.example.com") as often as full
// URLs. Anything without a scheme becomes https, which is what the crawler
// expects.
const resolveAuditTargetUrl = (form: Pick<AuditFormValues, "url" | "targetUrl">): string =>
  withHttpScheme(form.targetUrl) || withHttpScheme(form.url);

const resolveAuditTargetName = (
  form: Pick<AuditFormValues, "auditTargetType" | "targetName" | "url" | "targetUrl">
): string => {
  const explicitName = form.targetName.trim();
  if (explicitName) return explicitName;
  return resolveAuditTargetUrl(form);
};

const normalizeDomain = (value: string): string => {
  const trimmed = value.trim();
  if (!trimmed) return "";
  try {
    return new URL(trimmed).hostname.replace(/^www\./i, "");
  } catch {
    return trimmed
      .replace(/^https?:\/\//i, "")
      .replace(/^www\./i, "")
      .split("/")[0]
      .trim();
  }
};

const buildForecastAuditData = (
  targetUrl: string,
  preScanResult?: AuditPreScanForecastSeed | null
): Record<string, unknown> | undefined => {
  if (!targetUrl && !preScanResult) {
    return undefined;
  }

  const payload: Record<string, unknown> = {};
  if (targetUrl) {
    payload.target_url = targetUrl;
    payload.url = targetUrl;
  }
  if (preScanResult?.snapshot_title) {
    payload.title = preScanResult.snapshot_title;
  }
  if (preScanResult?.snapshot_description) {
    payload.meta_description = preScanResult.snapshot_description;
    payload.summary = preScanResult.snapshot_description;
  }
  if (preScanResult?.language) {
    payload.language = preScanResult.language;
  }
  if (preScanResult?.market_region) {
    payload.market = preScanResult.market_region;
  }
  if (preScanResult?.category) {
    payload.category = preScanResult.category;
  }
  if (preScanResult?.primary_entities?.length) {
    payload.entities_detected = preScanResult.primary_entities;
  }
  return Object.keys(payload).length > 0 ? payload : undefined;
};

// ---------------------------------------------------------------------------
// Job status polling queryFn
// ---------------------------------------------------------------------------

async function fetchJobStatus(
  jobId: string,
  getAuthHeaders: () => Promise<Record<string, string>>,
  signal?: AbortSignal
): Promise<AuditJobStatusResponse> {
  const authHeaders = await getAuthHeaders();
  const response = await fetch(`/api/audit/jobs/${jobId}`, { headers: authHeaders, signal });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? "Unable to check audit status.");
  }
  return (await response.json()) as AuditJobStatusResponse;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuditRunner({
  getAuthHeaders,
  isSignedIn,
  form,
  preScanResult,
  validateForm,
  verifyUrlPreflight,
  fetchAuditRecord,
  invalidateHistory,
  upsertHistoryEntry,
  onAuditComplete,
  projectId,
  reattachJobId,
}: UseAuditRunnerParams) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(reattachJobId ?? null);
  const didReattach = useRef(false);
  const [activeRunContext, setActiveRunContext] = useState<AuditRunContext | null>(null);
  const [completionBanner, setCompletionBanner] = useState<{
    title: string;
    subtitle: string;
  } | null>(null);
  const [completedAuditMeta, setCompletedAuditMeta] = useState<{
    auditId: number;
    target: string;
    overallScore: number | null;
    seoScore: number | null;
    aeoScore: number | null;
    geoScore: number | null;
    aioScore: number | null;
  } | null>(null);
  const [runSnapshot, setRunSnapshot] = useState<AuditRunSnapshot | null>(null);
  const [isEventStreamConnected, setIsEventStreamConnected] = useState(false);
  const [isEventStreamFallback, setIsEventStreamFallback] = useState(false);
  const [liveDebateProgress, setLiveDebateProgress] = useState<AuditLiveDebateProgress | null>(
    null
  );
  const [duplicateAuditJobId, setDuplicateAuditJobId] = useState<string | null>(null);
  const resolvedTargetType = resolveAuditTargetType(form.auditTargetType);
  const resolvedTargetUrl = resolveAuditTargetUrl(form);
  const resolvedTargetName = resolveAuditTargetName(form);
  const resolvedTargetLabel = resolvedTargetName || resolvedTargetUrl;
  const preScanPrimaryEntities = preScanResult?.primary_entities ?? [];
  const forecastAuditData = useMemo(
    () => buildForecastAuditData(resolvedTargetUrl, preScanResult),
    [preScanResult, resolvedTargetUrl]
  );
  const isEstimateTargetReady = useMemo(() => {
    if (resolvedTargetType === "website") {
      return isValidHttpUrl(resolvedTargetUrl);
    }
    if (!resolvedTargetUrl) {
      return true;
    }
    return isValidHttpUrl(resolvedTargetUrl);
  }, [resolvedTargetType, resolvedTargetUrl]);

  const estimatedCreditsQuery = useQuery({
    queryKey: [
      "audit-credit-estimate",
      form.tier,
      resolvedTargetType,
      resolvedTargetUrl,
      resolvedTargetName,
      form.language?.trim() || "",
      form.category?.trim() || "",
      form.market?.trim() || "",
      form.entities.join("|"),
      form.selectedModels.join("|"),
      preScanResult?.snapshot_title ?? "",
      preScanResult?.snapshot_description ?? "",
      preScanPrimaryEntities.join("|"),
      isSignedIn,
    ],
    queryFn: async () => {
      const authHeaders = await getAuthHeaders();
      return estimateAuditCredits(
        {
          auditTargetType: resolvedTargetType,
          targetName: resolvedTargetType === "brand" ? resolvedTargetName || undefined : undefined,
          tier: form.tier,
          category: form.category,
          market: form.market,
          entities: form.entities,
          selectedModels: form.selectedModels,
          targetUrl: resolvedTargetUrl || undefined,
          auditData: forecastAuditData,
        },
        authHeaders
      );
    },
    enabled: isSignedIn && isEstimateTargetReady,
    staleTime: 30_000,
    retry: 1,
  });

  const jobQuery = useQuery({
    queryKey: ["audit-job", jobId],
    queryFn: ({ signal }) => fetchJobStatus(jobId!, getAuthHeaders, signal),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (isTerminalJobStatus(status)) return false;
      return isEventStreamFallback ? 5000 : false;
    },
    staleTime: 0,
    retry: 1,
  });

  const jobData = jobQuery.data;
  const isPolling = !!jobId && !isTerminalJobStatus(jobData?.status);
  const pollError = isEventStreamFallback ? (jobQuery.error?.message ?? "") : "";

  // Re-attach: when reattachJobId changes externally, adopt it
  useEffect(() => {
    if (!reattachJobId || didReattach.current) return;
    didReattach.current = true;
    setJobId(reattachJobId);
  }, [reattachJobId]);

  // Re-attach: populate activeRunContext from the first job status response
  useEffect(() => {
    if (!reattachJobId || !jobData || activeRunContext) return;
    if (jobId !== reattachJobId) return;
    const targetName = jobData.target_name ?? jobData.target_url ?? "";
    const targetUrl = jobData.target_url ?? "";
    setActiveRunContext({
      targetType: jobData.audit_target_type === "brand" ? "brand" : "website",
      targetName,
      targetUrl,
      targetLabel: targetName || targetUrl,
      tier: jobData.requested_tier ?? form.tier,
    });
  }, [reattachJobId, jobData, jobId, activeRunContext, form.tier]);

  // Declared before the terminal-status effect on purpose: effects run in
  // declaration order, so the snapshot is written from the final status
  // response before that effect clears `jobId` and drops the cached job.
  useEffect(() => {
    if (!jobData || !jobId) return;
    const status = String(jobData.status ?? "").toLowerCase();
    const phase: Exclude<ScanRunPhase, "idle"> =
      status === "succeeded" ? "succeeded" : status === "failed" ? "failed" : "running";
    const targetUrl = jobData.target_url ?? activeRunContext?.targetUrl ?? resolvedTargetUrl;
    const targetName = jobData.target_name ?? activeRunContext?.targetName ?? resolvedTargetName;
    setRunSnapshot({
      jobId,
      phase,
      targetLabel: targetName || targetUrl,
      targetUrl,
      tier: jobData.requested_tier ?? activeRunContext?.tier ?? form.tier,
      stages: (jobData.stages ?? []).map((stage) => ({
        id: String(stage.id),
        status: asStageState(stage.status),
        attempt: typeof stage.attempt === "number" ? stage.attempt : 0,
        startedAt: stage.started_at ?? null,
        completedAt: stage.completed_at ?? null,
        reason: stage.reason ?? null,
      })),
      error: jobData.error ?? null,
      startedAt: jobData.started_at ?? null,
      completedAt: jobData.completed_at ?? null,
      auditId: typeof jobData.audit_id === "number" ? jobData.audit_id : null,
    });
  }, [
    jobData,
    jobId,
    activeRunContext?.tier,
    activeRunContext?.targetName,
    activeRunContext?.targetUrl,
    form.tier,
    resolvedTargetName,
    resolvedTargetUrl,
  ]);

  useEffect(() => {
    if (!jobId) {
      setIsEventStreamConnected(false);
      setIsEventStreamFallback(false);
      setLiveDebateProgress(null);
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId) {
      return;
    }

    if (typeof window === "undefined" || typeof window.EventSource === "undefined") {
      setIsEventStreamConnected(false);
      setIsEventStreamFallback(true);
      return;
    }

    const streamJobId = jobId;
    const stream = new EventSource(`/api/audit/jobs/${streamJobId}/events`);
    let isClosed = false;

    const syncJobStatus = (payload: AuditJobStatusResponse) => {
      queryClient.setQueryData(["audit-job", streamJobId], payload);
    };

    const handleJobStatus = (event: MessageEvent) => {
      const payload = parseJsonPayload<AuditJobStatusResponse>(event.data);
      if (!payload) {
        return;
      }
      syncJobStatus(payload);
    };

    const handleDebateEvent = (event: MessageEvent) => {
      const payload = parseJsonPayload<AuditJobLiveDebateEvent>(event.data);
      if (!payload) {
        return;
      }
      setLiveDebateProgress((current) => applyLiveDebateEvent(current, payload, "live"));
    };

    stream.onopen = () => {
      if (isClosed) {
        return;
      }
      setIsEventStreamConnected(true);
      setIsEventStreamFallback(false);
      setLiveDebateProgress((current) => (current ? { ...current, mode: "live" } : current));
    };

    stream.addEventListener("job_status", handleJobStatus as EventListener);
    stream.addEventListener("pipeline_started", handleDebateEvent as EventListener);
    stream.addEventListener("layer_started", handleDebateEvent as EventListener);
    stream.addEventListener("layer_completed", handleDebateEvent as EventListener);
    stream.addEventListener("step_started", handleDebateEvent as EventListener);
    stream.addEventListener("step_completed", handleDebateEvent as EventListener);
    stream.addEventListener("debate_finished", handleDebateEvent as EventListener);

    stream.onerror = () => {
      if (isClosed) {
        return;
      }

      const currentStatus = queryClient.getQueryData<AuditJobStatusResponse>([
        "audit-job",
        streamJobId,
      ])?.status;
      stream.close();
      setIsEventStreamConnected(false);

      if (isTerminalJobStatus(currentStatus)) {
        return;
      }

      setIsEventStreamFallback(true);
      setLiveDebateProgress((current) =>
        current ? { ...current, mode: "polling_fallback" } : current
      );
    };

    return () => {
      isClosed = true;
      stream.removeEventListener("job_status", handleJobStatus as EventListener);
      stream.removeEventListener("pipeline_started", handleDebateEvent as EventListener);
      stream.removeEventListener("layer_started", handleDebateEvent as EventListener);
      stream.removeEventListener("layer_completed", handleDebateEvent as EventListener);
      stream.removeEventListener("step_started", handleDebateEvent as EventListener);
      stream.removeEventListener("step_completed", handleDebateEvent as EventListener);
      stream.removeEventListener("debate_finished", handleDebateEvent as EventListener);
      stream.close();
    };
  }, [jobId, queryClient]);

  useEffect(() => {
    if (!jobData || !jobId) return;

    if (jobData.status === "succeeded" && jobData.audit_id) {
      const completedJobId = jobId;
      const auditId = jobData.audit_id;
      const completedAuditType = String(
        activeRunContext?.tier ?? form.tier ?? "fast"
      ).toUpperCase();
      const completedTarget = (activeRunContext?.targetLabel ?? resolvedTargetLabel).trim();
      setJobId(null);
      setActiveRunContext(null);
      queryClient.removeQueries({ queryKey: ["audit-job", completedJobId] });
      setCompletionBanner({
        title: "Assessment is finished ✨",
        subtitle: completedTarget
          ? `Sequence complete for ${completedTarget}. Added to history.`
          : "Sequence complete. Added to history.",
      });

      void (async () => {
        try {
          await invalidateHistory();
          const auditRecord = await fetchAuditRecord(auditId);
          const normalizedReportData = normalizeReport(auditRecord, auditRecord.url);
          const overallScore =
            typeof normalizedReportData.scores?.overall === "number"
              ? Math.round(normalizedReportData.scores.overall)
              : null;
          const seoScore = typeof auditRecord.seo_score === "number" ? auditRecord.seo_score : null;
          const aeoScore = typeof auditRecord.aeo_score === "number" ? auditRecord.aeo_score : null;
          const geoScore = typeof auditRecord.geo_score === "number" ? auditRecord.geo_score : null;
          setCompletedAuditMeta({
            auditId,
            target: completedTarget,
            overallScore,
            seoScore,
            aeoScore,
            geoScore,
            // Same headline every surface shows for this audit (SIGNAL-1000),
            // so the run view's "New scores" agrees with the report page.
            aioScore: computeAioScore(normalizedReportData, { aeo: aeoScore, geo: geoScore }),
          });
          // The allowance shown next to the result is the one after this run,
          // so the pre-launch estimate has to be refetched rather than reused.
          void queryClient.invalidateQueries({ queryKey: ["audit-credit-estimate"] });
          toast.success(`Audit finished · ${completedAuditType}`, {
            id: `audit-finished-${auditId}`,
            description: completedTarget ? `Target: ${completedTarget}` : "Your report is ready.",
            action: {
              label: "View Report",
              onClick: () => {
                window.location.href = asset(`/dashboard/audit/${auditId}`);
              },
            },
          });
          const newEntry: AuditHistoryItem = {
            id: auditRecord.id,
            url: auditRecord.url,
            auditTargetType:
              auditRecord.audit_target_type === "brand" ||
              auditRecord.audit_target_type === "website"
                ? auditRecord.audit_target_type
                : resolvedTargetType,
            targetName: auditRecord.target_name ?? null,
            targetUrl: auditRecord.target_url ?? null,
            targetMetadata:
              auditRecord.target_metadata && typeof auditRecord.target_metadata === "object"
                ? auditRecord.target_metadata
                : {},
            geoScore: auditRecord.geo_score,
            seoScore: typeof auditRecord.seo_score === "number" ? auditRecord.seo_score : null,
            aeoScore: typeof auditRecord.aeo_score === "number" ? auditRecord.aeo_score : null,
            status: String(auditRecord.status ?? "completed"),
            auditType: String(auditRecord.audit_type ?? form.tier ?? "STANDARD").toUpperCase(),
            createdAt: auditRecord.created_at,
            // The served project of the finished audit. The history query has
            // always carried this; the completion path omitted it, so the
            // finished-scan view had no project to point its Dashboard crumb
            // and action at and fell back to the workspace overview
            // (SIGV2-1163 / SIGV2-1164). Carrying it also means the entry
            // written here matches the one the history query returns.
            projectId: auditRecord.project_id,
            fullReport: auditRecord.full_report ?? null,
          };
          upsertHistoryEntry(newEntry);
          onAuditComplete(newEntry, normalizedReportData);
        } catch {
          // Error will surface through the history query
        }
      })();
      return;
    }

    if (jobData.status === "failed") {
      const failedJobId = jobId;
      setJobId(null);
      setActiveRunContext(null);
      queryClient.removeQueries({ queryKey: ["audit-job", failedJobId] });
      toast.error(jobData.error ?? "Assessment failed. Please try again.", {
        id: `audit-failed-${jobId}`,
      });
    }
  }, [
    fetchAuditRecord,
    invalidateHistory,
    upsertHistoryEntry,
    jobData,
    jobId,
    activeRunContext?.tier,
    activeRunContext?.targetLabel,
    onAuditComplete,
    form.tier,
    resolvedTargetLabel,
    resolvedTargetType,
    queryClient,
  ]);

  // --- Submit mutation ---
  const submitMutation = useMutation({
    mutationFn: async () => {
      const isValid = await validateForm();
      if (!isValid) throw new Error("Please fix the form errors before submitting.");
      if (!isSignedIn) throw new Error("Sign in to run a full assessment.");

      const requiresTargetUrl = resolvedTargetType === "website";

      if (requiresTargetUrl && !resolvedTargetUrl) {
        throw new Error("A target URL is required to execute this assessment.");
      }

      if (resolvedTargetUrl) {
        const isPreflightOk = await verifyUrlPreflight(resolvedTargetUrl);
        if (!isPreflightOk) {
          throw new Error("URL validation preflight failed. Please check the URL and try again.");
        }
      }

      setCompletionBanner(null);
      setActiveRunContext({
        targetType: resolvedTargetType,
        targetName: resolvedTargetName,
        targetUrl: resolvedTargetUrl,
        targetLabel: resolvedTargetLabel,
        tier: form.tier,
      });

      const requestId = crypto.randomUUID();
      const authHeaders = await getAuthHeaders();

      let targetProjectId = projectId;

      if (!targetProjectId) {
        const { fetchWorkspaceProjects, createWorkspaceProject } =
          await import("@/services/workspaceService");

        try {
          const projects = await fetchWorkspaceProjects(authHeaders);
          const normalizedTargetDomain = normalizeDomain(resolvedTargetUrl);
          const fallbackProjectName =
            resolvedTargetName || normalizedTargetDomain || "Brand Assessment";

          const existingProject = projects.find((p) => {
            if (!p.domain_url || !normalizedTargetDomain) return false;
            const pDomain = normalizeDomain(p.domain_url);
            return pDomain === normalizedTargetDomain;
          });

          if (existingProject) {
            targetProjectId = existingProject.id;
          } else {
            // "Main market" is free text ("Romania", "London, UK", or empty),
            // while target_country only accepts an ISO 3166-1 alpha-2 code.
            // Sending the raw value made every creation fail (SIGV2-1110), so
            // a market that cannot be resolved to a code is left unset.
            const targetCountry = resolveProjectTargetCountry(form.market);
            const trimmedLanguage = form.language.trim();
            const newProject = await createWorkspaceProject(
              {
                name: fallbackProjectName,
                domain_url: resolvedTargetUrl || null,
                language: trimmedLanguage.length >= 2 ? trimmedLanguage : "en",
                target_country: targetCountry,
              },
              authHeaders
            );
            const newId =
              typeof newProject?.id === "number" && Number.isFinite(newProject.id)
                ? newProject.id
                : typeof (newProject as { project_id?: unknown })?.project_id === "number"
                  ? (newProject as { project_id: number }).project_id
                  : null;
            if (newId == null) {
              throw new Error(t(PROJECT_SETUP_FAILURE_I18N_KEYS.generic));
            }
            targetProjectId = newId;
          }
        } catch (projectSetupError) {
          throw new Error(t(resolveProjectSetupFailureKey(projectSetupError)));
        }
      }

      if (!targetProjectId) {
        throw new Error(t(PROJECT_SETUP_FAILURE_I18N_KEYS.generic));
      }

      return createAuditJob(
        {
          projectId: targetProjectId,
          url: resolvedTargetUrl,
          auditTargetType: resolvedTargetType,
          targetName: resolvedTargetType === "brand" ? resolvedTargetName || undefined : undefined,
          targetUrl: resolvedTargetUrl,
          tier: form.tier,
          requestId,
          language: form.language,
          market: form.market,
          category: form.category,
          entities: form.entities,
          selectedModels: form.selectedModels,
          auditData: forecastAuditData,
        },
        {
          ...authHeaders,
          "X-Request-ID": requestId,
        }
      );
    },
    onSuccess: (payload) => {
      setJobId(payload.job_id);
      const payloadTargetType =
        payload.audit_target_type === "brand" || payload.audit_target_type === "website"
          ? payload.audit_target_type
          : resolvedTargetType;
      const payloadTargetUrl = payload.target_url?.trim() || resolvedTargetUrl;
      const payloadTargetName =
        payload.target_name?.trim() || resolvedTargetName || payloadTargetUrl;
      setActiveRunContext(
        (current) =>
          current ?? {
            targetType: payloadTargetType,
            targetUrl: payloadTargetUrl,
            targetName: payloadTargetName,
            targetLabel: payloadTargetName,
            tier: form.tier,
          }
      );
      void invalidateHistory();
    },
    onError: (err) => {
      if (err instanceof AuditConflictError) {
        setDuplicateAuditJobId(err.existingJobId);
        if (err.existingJobId) {
          setJobId(err.existingJobId);
        }
        toast.warning("An audit for this target is already in progress.");
      }
    },
  });

  const handleSubmit = useCallback(
    async (event?: React.FormEvent) => {
      if (event) event.preventDefault();
      setCompletionBanner(null);
      setCompletedAuditMeta(null);
      setLiveDebateProgress(null);
      setDuplicateAuditJobId(null);
      setIsEventStreamConnected(false);
      setIsEventStreamFallback(false);
      setRunSnapshot(null);
      submitMutation.mutate();
    },
    [submitMutation]
  );

  /** Leave the run view and go back to the start-scan form. */
  const dismissRun = useCallback(() => {
    setRunSnapshot(null);
    setCompletionBanner(null);
    setCompletedAuditMeta(null);
    setLiveDebateProgress(null);
  }, []);

  const error =
    submitMutation.error?.message ??
    (jobData?.status === "failed" ? (jobData.error ?? "Assessment job failed.") : "");

  const statusLabel = useMemo(() => {
    const status = jobData?.status;
    if (status === "queued") return "Queued";
    if (status === "running") return "Running";
    if (status === "succeeded") return "Completed";
    if (status === "failed") return "Failed";
    return null;
  }, [jobData?.status]);

  const isDuplicateAudit = useMemo(
    () => duplicateAuditJobId !== null || submitMutation.error instanceof AuditConflictError,
    [duplicateAuditJobId, submitMutation.error]
  );

  const dismissCompletion = useCallback(() => {
    setCompletedAuditMeta(null);
    setCompletionBanner(null);
  }, []);

  // A launch that has not produced a job id yet is already a run as far as the
  // page is concerned: the approved design swaps the form for the run view at
  // that point, with every stage still queued.
  const pendingLaunchSnapshot: AuditRunSnapshot | null = submitMutation.isPending
    ? {
        jobId: "",
        phase: "running",
        targetLabel: resolvedTargetLabel,
        targetUrl: resolvedTargetUrl,
        tier: form.tier,
        stages: [],
        error: null,
        startedAt: null,
        completedAt: null,
        auditId: null,
      }
    : null;
  const effectiveRunSnapshot = runSnapshot ?? pendingLaunchSnapshot;
  const runPhase: ScanRunPhase = effectiveRunSnapshot?.phase ?? "idle";

  return {
    isLoading: submitMutation.isPending,
    error,
    pollError,
    isPolling,
    runSnapshot: effectiveRunSnapshot,
    runPhase,
    dismissRun,
    isEstimatingCredits: estimatedCreditsQuery.isFetching,
    consumesScan: estimatedCreditsQuery.data?.consumes_scan ?? null,
    scansUsed: estimatedCreditsQuery.data?.scans_used ?? null,
    scansRemaining: estimatedCreditsQuery.data?.scans_remaining ?? null,
    scansResetAt: estimatedCreditsQuery.data?.reset_at ?? null,
    serverEstimateConfidence: estimatedCreditsQuery.data?.confidence ?? null,
    jobStatus: jobData?.status ?? null,
    jobStatusLabel: statusLabel,
    liveDebateProgress,
    isEventStreamConnected,
    isEventStreamFallback,
    completionBanner,
    completedAuditMeta,
    dismissCompletion,
    handleSubmit,
    isDuplicateAudit,
    isReattaching: !!reattachJobId && jobId === reattachJobId && isPolling,
  };
}
