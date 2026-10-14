import {
  AUDIT_PROVIDER_CONFIG,
  resolveAuditRoutingConfig,
  type AuditTier,
} from "@/constants/auditModelMap";
import type { CanonicalAuditReport } from "@/lib/reportAdapters";

type AuditProviderKey = keyof typeof AUDIT_PROVIDER_CONFIG;

type CompletedAuditRouteInput = {
  billingProvider?: unknown;
  routingPreferredProvider?: unknown;
  provider?: unknown;
  model?: unknown;
  requestedTier?: unknown;
  tier?: unknown;
  executionTier?: unknown;
  modeLabel?: unknown;
  auditType?: unknown;
};

const asString = (value: unknown): string => (typeof value === "string" ? value.trim() : "");

const asStringList = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((entry) => (typeof entry === "string" ? entry.trim() : "")).filter(Boolean)
    : [];

const normalizeTierToken = (value: unknown): string => {
  const normalized = asString(value)
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
  return normalized;
};

export const normalizeAuditRequestedTier = (value: unknown): AuditTier | null => {
  const normalized = normalizeTierToken(value);
  if (!normalized) return null;
  if (normalized === "deep_judgment" || normalized === "high_confidence") {
    return "deep_judgment";
  }
  if (normalized === "smart" || normalized === "deep") {
    return "smart";
  }
  if (normalized === "fast" || normalized === "standard" || normalized === "lite") {
    return "fast";
  }
  return null;
};

export const normalizeAuditProviderKey = (value: unknown): AuditProviderKey | null => {
  const normalized = asString(value).toLowerCase();
  if (!normalized) return null;
  if (normalized in AUDIT_PROVIDER_CONFIG) {
    return normalized as AuditProviderKey;
  }
  if (normalized.includes("gemini") || normalized.includes("google")) {
    return "google";
  }
  if (normalized.includes("claude") || normalized.includes("anthropic")) {
    return "anthropic";
  }
  if (
    normalized.includes("gpt") ||
    normalized.includes("openai") ||
    normalized.startsWith("o1") ||
    normalized.startsWith("o3") ||
    normalized.startsWith("o4")
  ) {
    return "openai";
  }
  return null;
};

export const resolveCompletedAuditRoute = ({
  billingProvider,
  routingPreferredProvider,
  provider,
  model,
  requestedTier,
  tier,
  executionTier,
  modeLabel,
  auditType,
}: CompletedAuditRouteInput): { provider: AuditProviderKey; tier: AuditTier } => {
  const resolvedTier =
    normalizeAuditRequestedTier(requestedTier) ??
    normalizeAuditRequestedTier(tier) ??
    normalizeAuditRequestedTier(executionTier) ??
    (() => {
      const normalizedModeLabel = asString(modeLabel).toLowerCase();
      if (normalizedModeLabel.includes("high confidence")) {
        return "deep_judgment";
      }
      if (normalizedModeLabel.includes("smart")) {
        return "smart";
      }
      return null;
    })() ??
    (() => {
      const normalizedAuditType = asString(auditType).toLowerCase();
      if (normalizedAuditType === "deep" || normalizedAuditType === "smart") {
        return "smart";
      }
      return normalizedAuditType === "fast" || normalizedAuditType === "standard" ? "fast" : null;
    })() ??
    "fast";

  const resolvedProvider =
    normalizeAuditProviderKey(billingProvider) ??
    normalizeAuditProviderKey(routingPreferredProvider) ??
    normalizeAuditProviderKey(provider) ??
    normalizeAuditProviderKey(model) ??
    resolveAuditRoutingConfig(resolvedTier).providerKey;

  return {
    provider: resolvedProvider,
    tier: resolvedTier,
  };
};

export const buildCompletedAuditScheduleParams = (
  report: CanonicalAuditReport | null | undefined,
  auditType?: string | null
): {
  provider: AuditProviderKey;
  tier: AuditTier;
  category?: string;
  market?: string;
  language?: string;
  entities: string[];
  selected_models: string[];
} => {
  const reportRecord =
    report && typeof report === "object" ? (report as Record<string, unknown>) : {};
  const metadata =
    reportRecord.metadata && typeof reportRecord.metadata === "object"
      ? (reportRecord.metadata as Record<string, unknown>)
      : {};
  const multiModelAudit =
    reportRecord._multi_model_audit && typeof reportRecord._multi_model_audit === "object"
      ? (reportRecord._multi_model_audit as Record<string, unknown>)
      : {};

  const route = resolveCompletedAuditRoute({
    billingProvider: metadata.billing_provider,
    routingPreferredProvider: metadata.routing_preferred_provider,
    provider: metadata.provider,
    model: metadata.model,
    requestedTier: metadata.requested_tier,
    tier: metadata.tier,
    executionTier: metadata.execution_tier,
    modeLabel: metadata.mode_label,
    auditType,
  });

  const selectedModels =
    asStringList(multiModelAudit.models_used).length > 0
      ? asStringList(multiModelAudit.models_used)
      : asStringList(metadata.selected_models);

  const category = asString(metadata.category);
  const market = asString(metadata.market);
  const language = asString(metadata.language);

  return {
    provider: route.provider,
    tier: route.tier,
    category: category || undefined,
    market: market || undefined,
    language: language || undefined,
    entities: asStringList(metadata.entities),
    selected_models: selectedModels,
  };
};
