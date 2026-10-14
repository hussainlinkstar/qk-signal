type AuditHistoryContractSource = {
  audit_target_type?: unknown;
  target_name?: unknown;
  target_url?: unknown;
  target_metadata?: unknown;
  url?: unknown;
  seo_score?: unknown;
  geo_score?: unknown;
  aeo_score?: unknown;
  full_report?: unknown;
};

type ResolvedDimensionScores = {
  seoScore: number | null;
  geoScore: number;
  aeoScore: number | null;
  overallScore: number | null;
};

type ResolvedPlanFields = {
  historicalPlan: string;
  currentPlan: string | null;
};

const SCORE_WEIGHTS = {
  seo: 0.4,
  aeo: 0.3,
  geo: 0.3,
} as const;

const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asOptionalNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

const asOptionalScoreValue = (value: unknown): number | null => {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return asOptionalNumber((value as Record<string, unknown>).score);
  }

  return asOptionalNumber(value);
};

const asOptionalString = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value.trim() : null;

const normalizePlanValue = (value: unknown): string | null => {
  const normalized = asOptionalString(value);
  return normalized ? normalized.toLowerCase() : null;
};

export const normalizeHistoryTargetType = (value: unknown): "website" | "brand" => {
  const normalized = typeof value === "string" ? value.trim().toLowerCase() : "";
  return normalized === "brand" ? "brand" : "website";
};

const calculateOverallScore = (scores: {
  seo?: number | null;
  geo?: number | null;
  aeo?: number | null;
}): number | null => {
  let totalWeight = 0;
  let weightedSum = 0;

  for (const [dimension, weight] of Object.entries(SCORE_WEIGHTS) as Array<
    [keyof typeof SCORE_WEIGHTS, number]
  >) {
    const value = scores[dimension];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      continue;
    }

    weightedSum += value * weight;
    totalWeight += weight;
  }

  if (totalWeight === 0) {
    return null;
  }

  return Math.max(0, Math.min(100, Math.round(weightedSum / totalWeight)));
};

export const resolveAuditHistoryTargetFields = (source: AuditHistoryContractSource) => {
  const report = asObject(source.full_report);
  const target = asObject(report.target);
  const metadata = asObject(report.metadata);

  const auditTargetType = normalizeHistoryTargetType(
    source.audit_target_type ??
      report.audit_target_type ??
      target.type ??
      metadata.audit_target_type
  );
  const targetUrl =
    asOptionalString(source.target_url) ??
    asOptionalString(target.url) ??
    asOptionalString(report.target_url) ??
    asOptionalString(metadata.target_url) ??
    asOptionalString(source.url) ??
    asOptionalString(report.url) ??
    null;
  const targetName =
    asOptionalString(source.target_name) ??
    asOptionalString(target.name) ??
    asOptionalString(report.target_name) ??
    asOptionalString(metadata.target_name) ??
    targetUrl ??
    (auditTargetType === "brand" ? "Brand audit" : null);
  const sourceTargetMetadata = asObject(source.target_metadata);
  const targetMetadata =
    Object.keys(sourceTargetMetadata).length > 0
      ? sourceTargetMetadata
      : Object.keys(asObject(target.metadata)).length > 0
        ? asObject(target.metadata)
        : Object.keys(asObject(report.target_metadata)).length > 0
          ? asObject(report.target_metadata)
          : asObject(metadata.target_metadata);

  return {
    auditTargetType,
    targetName,
    targetUrl,
    targetMetadata,
  };
};

export const resolveAuditHistoryScores = (
  source: AuditHistoryContractSource
): ResolvedDimensionScores => {
  const report = asObject(source.full_report);
  const scores = asObject(report.scores);
  const seo = asObject(report.seo);
  const geo = asObject(report.geo);
  const aeo = asObject(report.aeo);
  const analysis = asObject(report.analysis);

  const seoScore =
    asOptionalNumber(source.seo_score) ??
    asOptionalNumber(scores.seo) ??
    asOptionalNumber(seo.onpage) ??
    asOptionalScoreValue(analysis.seo_score);
  const geoScore =
    asOptionalNumber(source.geo_score) ??
    asOptionalNumber(scores.geo) ??
    asOptionalNumber(geo.visibility_index) ??
    asOptionalScoreValue(analysis.geo_score) ??
    0;
  const aeoScore =
    asOptionalNumber(source.aeo_score) ??
    asOptionalNumber(scores.aeo) ??
    asOptionalNumber(aeo.answerability_score) ??
    asOptionalScoreValue(analysis.aeo_score);
  const hasSummaryScoreOverride = hasAuditHistorySummaryScoreOverride(source);

  const overallScore = hasSummaryScoreOverride
    ? (calculateOverallScore({ seo: seoScore, geo: geoScore, aeo: aeoScore }) ??
      asOptionalNumber(scores.overall))
    : (asOptionalNumber(scores.overall) ??
      calculateOverallScore({ seo: seoScore, geo: geoScore, aeo: aeoScore }));

  return {
    seoScore,
    geoScore,
    aeoScore,
    overallScore,
  };
};

export const hasAuditHistorySummaryScoreOverride = (
  source: Pick<AuditHistoryContractSource, "seo_score" | "geo_score" | "aeo_score">
) =>
  asOptionalNumber(source.seo_score) !== null ||
  asOptionalNumber(source.geo_score) !== null ||
  asOptionalNumber(source.aeo_score) !== null;

export const resolveAuditHistoryPlanFields = (
  source: Pick<AuditHistoryContractSource, "full_report">
): ResolvedPlanFields => {
  const report = asObject(source.full_report);
  const metadata = asObject(report.metadata);

  return {
    historicalPlan: normalizePlanValue(metadata.plan) ?? "plan_starter",
    currentPlan: normalizePlanValue(metadata.current_plan),
  };
};
