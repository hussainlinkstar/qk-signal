"use client";

import React, { useState } from "react";
import { ChevronDown, ChevronUp, Swords } from "lucide-react";
import DebateStepRow, { type DebateStep } from "./DebateStepRow";

export type DebateMetadata = {
  enabled: boolean;
  profile?: string | null;
  pipeline_type?: string | null;
  parallel_layers?: number | null;
  agent_count?: number | null;
  debate_confidence_score?: number | null;
  synthesis_reasoning?: string | null;
  fallback_reason?: string | null;
  judge_authority?: string | null;
  judge_summary?: {
    accepted_claims: number;
    downgraded_claims: number;
    rejected_claims: number;
    unresolved_disputes: number;
  } | null;
  transcript?: DebateStep[];
  per_agent_costs?: Array<{
    role: string;
    provider: string;
    model: string;
    semantic_role?: "generator" | "critic" | "judge" | "consolidator" | null;
    latency_ms?: number | null;
    cost_usd?: number | null;
    tokens?: { prompt?: number; completion?: number; total?: number } | null;
    execution_tier?: string | null;
    routing_mode?: string | null;
    layer?: number | null;
  }> | null;
  total_token_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  } | null;
  total_latency_ms?: number | null;
  total_estimated_cost_usd?: number | null;
};

const PROFILE_LABELS: Record<string, string> = {
  fast_3step: "FAST 3-step",
  smart_5step: "SMART 5-step",
  delta_flow: "Delta Flow",
  high_confidence: "High Confidence review",
  specialist_synthesis: "Specialist synthesis",
  standard: "Legacy Smart",
};

const ROLE_LABELS: Record<string, string> = {
  fast_proposer: "FAST Proposer",
  fast_critic: "FAST Critic",
  fast_synthesizer: "FAST Synthesizer",
  seo_generator: "SEO Generator",
  aeo_geo_generator: "AIO Generator",
  geo_generator: "AI Visibility Generator",
  aeo_generator: "AI Answers Generator",
  centralized_critic: "Central Critic",
  seo_critic: "SEO Critic",
  geo_critic: "AI Visibility Critic",
  aeo_critic: "AI Answers Critic",
  smart_synthesizer: "SMART Synthesizer",
  magistrate: "Magistrate",
  consolidator: "Consolidator",
  global_magistrate: "Global Magistrate",
};

const DebateProcessCard = ({ debate }: { debate: DebateMetadata }) => {
  const [expanded, setExpanded] = useState(false);

  if (!debate?.enabled) return null;

  const transcript = debate.transcript ?? [];
  const totalTokens = debate.total_token_usage?.total_tokens ?? 0;
  const totalLatency = debate.total_latency_ms ? (debate.total_latency_ms / 1000).toFixed(1) : "-";
  const confidence =
    debate.debate_confidence_score != null
      ? `${Math.round(debate.debate_confidence_score * 100)}%`
      : null;
  const judgeSummary = debate.judge_summary;
  const profileLabel =
    (debate.pipeline_type && PROFILE_LABELS[debate.pipeline_type]) ||
    (debate.profile ? (PROFILE_LABELS[debate.profile] ?? debate.profile) : null);
  const judgeAuthorityLabel =
    debate.judge_authority === "primary"
      ? "Primary judge"
      : debate.judge_authority === "fallback"
        ? "Fallback judge"
        : null;
  const perAgentCosts = debate.per_agent_costs ?? [];
  const agentCountLabel =
    debate.agent_count != null && debate.agent_count > 0 ? `${debate.agent_count} agents` : null;
  const layerCountLabel =
    debate.parallel_layers != null && debate.parallel_layers > 0
      ? `${debate.parallel_layers} parallel layer${debate.parallel_layers === 1 ? "" : "s"}`
      : null;

  return (
    <section className="mb-8 rounded-xl border border-(--line) bg-(--line-2)">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between gap-3 p-4 sm:p-6 text-left"
      >
        <div className="flex items-center gap-2">
          <Swords className="h-5 w-5 text-thoth-brass" />
          <h3 className="text-lg font-semibold text-(--t-1)">Debate Process</h3>
          {profileLabel ? (
            <span className="rounded-full border border-[color-mix(in_srgb,var(--purple)_30%,transparent)] bg-[color-mix(in_srgb,var(--purple)_10%,transparent)] px-2 py-0.5 text-xs font-medium text-(--purple)">
              {profileLabel}
            </span>
          ) : null}
          {agentCountLabel ? (
            <span className="rounded-full border border-(--line) bg-(--line-2) px-2 py-0.5 text-xs font-medium text-(--t-2)">
              {agentCountLabel}
            </span>
          ) : null}
          {layerCountLabel ? (
            <span className="rounded-full border border-(--line) bg-(--line-2) px-2 py-0.5 text-xs font-medium text-(--t-2)">
              {layerCountLabel}
            </span>
          ) : null}
          {judgeAuthorityLabel ? (
            <span
              className={
                debate.judge_authority === "fallback"
                  ? "rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-0.5 text-xs font-medium text-amber-100"
                  : "rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-100"
              }
            >
              {judgeAuthorityLabel}
            </span>
          ) : null}
          {confidence && (
            <span className="ml-2 rounded-full border border-thoth-brass/40 bg-thoth-brass/10 px-2 py-0.5 text-xs font-medium text-thoth-brass">
              {confidence} confidence
            </span>
          )}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-(--t-2)" />
        ) : (
          <ChevronDown className="h-4 w-4 text-(--t-2)" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-(--line) px-4 pb-5 pt-3 sm:px-6 space-y-4">
          <div className="space-y-2">
            {transcript.map((step, idx) => (
              <DebateStepRow key={`${step.role}-${idx}`} step={step} />
            ))}
          </div>

          {debate.synthesis_reasoning && (
            <div className="rounded-md border border-(--line) bg-(--line-2) p-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-(--t-2)">
                Consensus Reasoning
              </p>
              <p className="text-sm leading-relaxed text-(--t-2)">{debate.synthesis_reasoning}</p>
            </div>
          )}

          {judgeSummary ? (
            <div className="rounded-md border border-(--line) bg-(--line-2) p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--t-2)">
                Judge Summary
              </p>
              <div className="grid grid-cols-2 gap-2 text-xs text-(--t-2) sm:grid-cols-4">
                <span>Accepted: {judgeSummary.accepted_claims}</span>
                <span>Downgraded: {judgeSummary.downgraded_claims}</span>
                <span>Rejected: {judgeSummary.rejected_claims}</span>
                <span>Unresolved: {judgeSummary.unresolved_disputes}</span>
              </div>
            </div>
          ) : null}

          {perAgentCosts.length ? (
            <div className="rounded-md border border-(--line) bg-(--line-2) p-4">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-(--t-2)">
                Agent Performance Breakdown
              </p>
              <div className="space-y-2">
                {perAgentCosts.map((entry, index) => {
                  const label = ROLE_LABELS[entry.role] ?? entry.role;
                  const tokens = entry.tokens?.total ?? 0;
                  return (
                    <div
                      key={`${entry.role}-${entry.provider}-${index}`}
                      className="flex flex-col gap-1 rounded-md border border-(--line) bg-(--line-2) px-3 py-2 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="space-y-1">
                        <p className="text-sm font-medium text-(--t-1)">{label}</p>
                        <p className="text-xs text-(--t-2)">
                          {entry.provider} / {entry.model}
                        </p>
                      </div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-(--t-2)">
                        {entry.layer != null ? <span>Layer {entry.layer}</span> : null}
                        {entry.execution_tier ? <span>{entry.execution_tier}</span> : null}
                        {entry.latency_ms != null ? (
                          <span>{(entry.latency_ms / 1000).toFixed(1)}s</span>
                        ) : null}
                        <span>{tokens > 0 ? `${(tokens / 1000).toFixed(1)}k tok` : ",  tok"}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ) : null}

          {debate.fallback_reason ? (
            <div className="rounded-md border border-amber-400/20 bg-amber-400/5 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-amber-200">
                Fallback
              </p>
              <p className="mt-1 text-sm text-amber-100">{debate.fallback_reason}</p>
            </div>
          ) : null}

          <div className="flex items-center gap-4 text-xs text-(--t-3) pt-1">
            <span>Total: {totalLatency}s</span>
            <span>
              {totalTokens > 0 ? `${(totalTokens / 1000).toFixed(1)}k tokens` : ",  tokens"}
            </span>
          </div>
        </div>
      )}
    </section>
  );
};

export default DebateProcessCard;
