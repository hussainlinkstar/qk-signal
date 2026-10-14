import type { ComponentType, SVGProps } from "react";
import type { LucideIcon } from "lucide-react";

export const AUDIT_TIERS = ["fast", "smart", "deep_judgment"] as const;

export type AuditTier = (typeof AUDIT_TIERS)[number];

type LocalSvgPath = `/icons/providers/${string}.svg`;
type SvgIconComponent = ComponentType<SVGProps<SVGSVGElement>>;

export type AuditProviderIcon = LucideIcon | SvgIconComponent | LocalSvgPath;

export type AuditProviderConfig = {
  label: string;
  icon: AuditProviderIcon;
  strengthsTooltip: string;
  models: Record<AuditTier, string>;
};

export const AUDIT_PROVIDER_CONFIG: Record<string, AuditProviderConfig> = {
  google: {
    label: "Google",
    icon: "/icons/providers/google-gemini.svg",
    strengthsTooltip: "AWS Bedrock reasoning.",
    models: {
      fast: "eu.amazon.nova-lite-v1:0",
      smart: "eu.amazon.nova-pro-v1:0",
      deep_judgment: "eu.amazon.nova-pro-v1:0",
    },
  },
  openai: {
    label: "OpenAI",
    icon: "/icons/providers/openai.svg",
    strengthsTooltip: "AWS Bedrock reasoning.",
    models: {
      fast: "eu.amazon.nova-lite-v1:0",
      smart: "eu.amazon.nova-pro-v1:0",
      deep_judgment: "eu.amazon.nova-pro-v1:0",
    },
  },
  anthropic: {
    label: "Anthropic",
    icon: "/icons/providers/anthropic.svg",
    strengthsTooltip: "AWS Bedrock reasoning.",
    models: {
      fast: "eu.amazon.nova-lite-v1:0",
      smart: "eu.amazon.nova-pro-v1:0",
      deep_judgment: "eu.amazon.nova-pro-v1:0",
    },
  },
  xai: {
    label: "xAI",
    icon: "/icons/providers/xai.svg",
    strengthsTooltip: "AWS Bedrock reasoning.",
    models: {
      fast: "eu.amazon.nova-lite-v1:0",
      smart: "eu.amazon.nova-pro-v1:0",
      deep_judgment: "eu.amazon.nova-pro-v1:0",
    },
  },
  deepseek: {
    label: "DeepSeek",
    icon: "/icons/providers/deepseek.svg",
    strengthsTooltip: "AWS Bedrock reasoning.",
    models: {
      fast: "eu.amazon.nova-lite-v1:0",
      smart: "eu.amazon.nova-pro-v1:0",
      deep_judgment: "eu.amazon.nova-pro-v1:0",
    },
  },
};

export const AUDIT_ROUTING_PROVIDER_BY_TIER: Record<AuditTier, keyof typeof AUDIT_PROVIDER_CONFIG> =
  {
    fast: "google",
    smart: "anthropic",
    deep_judgment: "anthropic",
  };

export const AUDIT_PROVIDER_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(AUDIT_PROVIDER_CONFIG).map(([provider, config]) => [provider, config.label])
);

export const AUDIT_MODEL_MAP: Record<string, Record<string, string>> = Object.fromEntries(
  Object.entries(AUDIT_PROVIDER_CONFIG).map(([provider, config]) => [provider, config.models])
);

export const resolveAuditProviderConfig = (provider: string): AuditProviderConfig | null =>
  AUDIT_PROVIDER_CONFIG[provider] ?? null;

/**
 * Customer-facing attribution shown wherever the resolved provider reaches the
 * report. Every provider routes to the same Bedrock models, so the honest name
 * is the panel, never a consumer product brand.
 */
export const REPORT_PANEL_LABEL = "Controlled model panel";

/**
 * Human-readable name for the reasoning capability behind each tier.
 *
 * Every provider label maps to the same Bedrock model per tier (the label is a
 * reporting attribution, not a different engine), so the raw model id carries no
 * user-facing meaning and reads as a contradiction next to a brand name
 * ("OpenAI · eu.amazon.nova-pro-v1:0"). Show the capability instead.
 */
export const AUDIT_MODEL_TIER_LABELS: Record<AuditTier, string> = {
  fast: "Bedrock · Fast reasoning",
  smart: "Bedrock · Smart reasoning",
  deep_judgment: "Bedrock · Deep reasoning",
};

export const normalizeAuditTier = (tier: string): AuditTier =>
  tier === "deep_judgment" ? "deep_judgment" : tier === "smart" ? "smart" : "fast";

export const resolveAuditModelConfig = (
  provider: string,
  tier: string
): {
  providerLabel: string;
  modelId: string;
  modelTierLabel: string;
  displayLabel: string;
  strengthsTooltip: string;
  icon: AuditProviderIcon | null;
} => {
  const providerConfig = resolveAuditProviderConfig(provider);
  if (!providerConfig) {
    return {
      providerLabel: provider,
      modelId: "Not available",
      modelTierLabel: "Not available",
      displayLabel: "Not available",
      strengthsTooltip: "",
      icon: null,
    };
  }

  const resolvedTier: AuditTier = normalizeAuditTier(tier);

  return {
    providerLabel: REPORT_PANEL_LABEL,
    modelId: providerConfig.models[resolvedTier] ?? "Not available",
    modelTierLabel: AUDIT_MODEL_TIER_LABELS[resolvedTier],
    displayLabel: REPORT_PANEL_LABEL,
    strengthsTooltip: providerConfig.strengthsTooltip,
    icon: providerConfig.icon,
  };
};

export const resolveAuditModelName = (provider: string, tier: string): string =>
  resolveAuditModelConfig(provider, tier).displayLabel;

export const resolveAuditRoutingConfig = (tier: string) => {
  const resolvedTier: AuditTier =
    tier === "deep_judgment" ? "deep_judgment" : tier === "smart" ? "smart" : "fast";
  const provider = AUDIT_ROUTING_PROVIDER_BY_TIER[resolvedTier];
  return {
    providerKey: provider,
    tier: resolvedTier,
    ...resolveAuditModelConfig(provider, resolvedTier),
  };
};

/* ── V3 Pipeline Profiles ───────────────────────────────────── */

export type PipelineStep = {
  role: string;
  provider: string;
  /** Which model tier this agent uses (e.g. synthesizer uses "fast" even in the smart pipeline). */
  executionTier: AuditTier;
  /** Steps sharing a layer number run in parallel. */
  layer: number;
};

export type PipelineProfile = {
  name: string;
  agentCount: number;
  parallelLayers: number;
  steps: PipelineStep[];
};

/**
 * Default V3 debate pipeline profiles per audit tier.
 * Provider assignments reflect the backend routing policy with provider
 * diversity enforcement (ai_routing_policy.py + debate_orchestrator.py).
 */
export const PIPELINE_PROFILES: Record<AuditTier, PipelineProfile> = {
  fast: {
    name: "Fast 3-Step",
    agentCount: 3,
    parallelLayers: 0,
    steps: [
      { role: "Proposer", provider: "google", executionTier: "fast", layer: 1 },
      { role: "Critic", provider: "anthropic", executionTier: "fast", layer: 2 },
      { role: "Synthesizer", provider: "google", executionTier: "fast", layer: 3 },
    ],
  },
  smart: {
    name: "Smart 5-Step Debate",
    agentCount: 5,
    parallelLayers: 1,
    steps: [
      { role: "SEO Generator", provider: "google", executionTier: "smart", layer: 1 },
      { role: "AIO Generator", provider: "anthropic", executionTier: "smart", layer: 1 },
      { role: "Centralized Critic", provider: "anthropic", executionTier: "smart", layer: 2 },
      { role: "Synthesizer", provider: "google", executionTier: "fast", layer: 3 },
      { role: "Magistrate", provider: "openai", executionTier: "smart", layer: 4 },
    ],
  },
  deep_judgment: {
    name: "Delta Flow 8-Agent",
    agentCount: 8,
    parallelLayers: 2,
    steps: [
      { role: "SEO Generator", provider: "google", executionTier: "smart", layer: 1 },
      { role: "AI Visibility Generator", provider: "anthropic", executionTier: "smart", layer: 1 },
      { role: "AI Answers Generator", provider: "openai", executionTier: "smart", layer: 1 },
      { role: "SEO Critic", provider: "anthropic", executionTier: "smart", layer: 2 },
      { role: "AI Visibility Critic", provider: "openai", executionTier: "smart", layer: 2 },
      { role: "AI Answers Critic", provider: "google", executionTier: "smart", layer: 2 },
      { role: "Consolidator", provider: "openai", executionTier: "smart", layer: 3 },
      { role: "Global Magistrate", provider: "openai", executionTier: "smart", layer: 4 },
    ],
  },
};

export type ResolvedPipelineStep = PipelineStep & {
  providerLabel: string;
  modelId: string;
  modelTierLabel: string;
  icon: AuditProviderIcon | null;
};

/** Resolve the full pipeline for a tier, mapping each step to its model name and provider label. */
export function resolvePipelineSteps(tier: AuditTier): {
  profile: PipelineProfile;
  steps: ResolvedPipelineStep[];
  uniqueProviders: string[];
} {
  const profile = PIPELINE_PROFILES[tier];
  const seen = new Set<string>();
  const steps: ResolvedPipelineStep[] = profile.steps.map((step) => {
    const cfg = AUDIT_PROVIDER_CONFIG[step.provider];
    seen.add(step.provider);
    return {
      ...step,
      providerLabel: cfg ? REPORT_PANEL_LABEL : step.provider,
      modelId: cfg?.models[step.executionTier] ?? "unknown",
      modelTierLabel: AUDIT_MODEL_TIER_LABELS[step.executionTier],
      icon: cfg?.icon ?? null,
    };
  });
  return { profile, steps, uniqueProviders: [...seen] };
}
