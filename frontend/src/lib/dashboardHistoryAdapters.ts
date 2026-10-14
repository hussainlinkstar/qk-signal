import type { AeoRewriteSuggestion, AuditResult, GeoCitationSource } from "../types/auditResult";
import { isAuditResult } from "../types/auditResult";
import type {
  GeoTrendSeriesPoint,
  MetricTrendPoint,
  ScoreDistributionPoint,
} from "../types/dashboardCharts";
import type { GeoTrendPointResponse } from "../services/auditService";
import {
  hasAuditHistorySummaryScoreOverride,
  resolveAuditHistoryPlanFields,
  resolveAuditHistoryScores,
  resolveAuditHistoryTargetFields,
} from "./auditHistoryContract";
import {
  canonicalToDashboardAdapter,
  isCanonicalAuditReportPayload,
  normalizeAuditReport,
  type CanonicalAuditReport,
} from "./reportAdapters";

export type AuditHistoryPayload = {
  id: number;
  status?: string;
  url?: string | null;
  audit_target_type?: "website" | "brand" | null;
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown> | null;
  geo_score?: number | null;
  seo_score?: number | null;
  aeo_score?: number | null;
  full_report?: unknown;
};

const scoreableOutcomes = new Set(["completed", "succeeded", "ready"]);
const reportOutcomes = new Set(["completed", "degraded", "failed", "succeeded", "ready"]);
const acceptedIntentValues = new Set(["informational", "transactional", "navigational"]);
const acceptedQueryTypeValues = new Set(["informational", "decision_making"]);

const asNumber = (value: unknown, defaultValue = 0) => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return defaultValue;
};

const toObject = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {};

const normalizeEntityLabel = (value: unknown): string => {
  if (typeof value === "string") {
    return value.trim();
  }

  if (typeof value === "object" && value !== null) {
    const entry = value as Record<string, unknown>;
    const name = entry.name ?? entry.entity ?? entry.label ?? entry.value;
    return typeof name === "string" ? name.trim() : "";
  }

  return "";
};

const getLegacyAuditEntities = (
  report: Record<string, unknown>,
  analysis: Record<string, unknown>
) => {
  const reportEntities = toObject(report.entities);
  const analysisEntityData = toObject(analysis.entity_data);
  const analysisEntitySummary = toObject(analysis.entity_summary);

  const candidates = [
    report.entities,
    reportEntities.items,
    reportEntities.entities,
    analysis.entities_detected,
    analysisEntityData.entities_detected,
    analysisEntityData.entities,
    analysisEntitySummary.entities,
  ];

  const deduped = new Set<string>();

  for (const candidate of candidates) {
    if (!Array.isArray(candidate)) {
      continue;
    }

    for (const entity of candidate) {
      const normalized = normalizeEntityLabel(entity);
      if (normalized) {
        deduped.add(normalized);
      }
    }
  }

  return Array.from(deduped);
};

const asDomain = (value: unknown): string => {
  if (typeof value !== "string") {
    return "";
  }

  return value
    .replace(/^https?:\/\//i, "")
    .split("/")[0]
    .trim()
    .toLowerCase();
};

const mapCitationSources = (value: unknown): AuditResult["geo_comparative"] => {
  const source = Array.isArray(value) ? value : [];

  const citationSources = source
    .map((item) => {
      if (typeof item === "string") {
        const domain = asDomain(item);
        if (!domain) {
          return null;
        }
        return {
          domain,
          citation_count: 1,
          trust_score: 50,
          owner: "other" as const,
        };
      }

      if (!item || typeof item !== "object" || Array.isArray(item)) {
        return null;
      }

      const payload = item as Record<string, unknown>;
      const domain = asDomain(payload.domain ?? payload.url);
      if (!domain) {
        return null;
      }

      const rawOwner = String(payload.owner ?? "other").toLowerCase();
      const owner: GeoCitationSource["owner"] =
        rawOwner === "my_site" || rawOwner === "competitor" ? rawOwner : "other";

      return {
        domain,
        citation_count: asNumber(payload.citation_count ?? payload.count, 1),
        trust_score: asNumber(payload.trust_score ?? payload.trust, 50),
        owner,
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  return {
    citation_sources: citationSources,
    strategic_recommendations: [],
  };
};

const applyResolvedAuditHistoryContract = (
  audit: AuditResult,
  payload: AuditHistoryPayload
): AuditResult => {
  const targetFields = resolveAuditHistoryTargetFields(payload);
  const scoreFields = resolveAuditHistoryScores(payload);
  const planFields = resolveAuditHistoryPlanFields(payload);
  const hasSummaryScoreOverride = hasAuditHistorySummaryScoreOverride(payload);

  return {
    ...audit,
    target: {
      ...audit.target,
      type: targetFields.auditTargetType,
      name: targetFields.targetName,
      url: targetFields.targetUrl,
      metadata: targetFields.targetMetadata,
    },
    site: {
      ...audit.site,
      url: targetFields.targetUrl ?? audit.site.url,
    },
    geo: {
      ...audit.geo,
      visibility_index: hasSummaryScoreOverride ? scoreFields.geoScore : audit.geo.visibility_index,
    },
    seo: {
      ...audit.seo,
      onpage: hasSummaryScoreOverride
        ? (scoreFields.seoScore ?? audit.seo.onpage)
        : audit.seo.onpage,
      indexing: hasSummaryScoreOverride
        ? (scoreFields.seoScore ?? audit.seo.indexing)
        : audit.seo.indexing,
    },
    aeo: {
      ...audit.aeo,
      answerability_score: hasSummaryScoreOverride
        ? (scoreFields.aeoScore ?? audit.aeo.answerability_score)
        : audit.aeo.answerability_score,
    },
    scores: {
      ...audit.scores,
      seo: scoreFields.seoScore ?? audit.scores.seo,
      geo: scoreFields.geoScore,
      aeo: scoreFields.aeoScore ?? audit.scores.aeo,
      overall: scoreFields.overallScore ?? audit.scores.overall ?? null,
    },
    metadata: {
      ...audit.metadata,
      plan: planFields.historicalPlan,
      current_plan: planFields.currentPlan,
      audit_target_type: targetFields.auditTargetType,
      target_name: targetFields.targetName,
      target_url: targetFields.targetUrl,
      target_metadata: targetFields.targetMetadata,
    },
  };
};

const coerceLegacyAuditResult = (payload: AuditHistoryPayload): AuditResult | null => {
  const value = payload.full_report;
  if (!value || typeof value !== "object") {
    return null;
  }
  const report = value as Record<string, unknown>;
  const analysis = toObject(report.analysis);
  const metadata = toObject(report.metadata);
  const targetFields = resolveAuditHistoryTargetFields(payload);
  const scoreFields = resolveAuditHistoryScores(payload);
  const planFields = resolveAuditHistoryPlanFields(payload);
  const nowIso = new Date().toISOString();

  const extractScore = (scoreValue: unknown) =>
    asNumber(
      typeof scoreValue === "object" &&
        scoreValue &&
        "score" in (scoreValue as Record<string, unknown>)
        ? (scoreValue as Record<string, unknown>).score
        : scoreValue
    );

  const recommendations = Array.isArray(analysis.recommendations)
    ? analysis.recommendations.filter((item: unknown): item is string => typeof item === "string")
    : [];

  return {
    schema_version: String(report.schema_version ?? "legacy"),
    target: {
      type: targetFields.auditTargetType,
      name: targetFields.targetName,
      url: targetFields.targetUrl,
      metadata: targetFields.targetMetadata,
    },
    site: {
      url: targetFields.targetUrl ?? String(report.url ?? analysis.url ?? ""),
      market: String(metadata.market ?? "global"),
      language: String(metadata.language ?? "en"),
    },
    seo: {
      onpage: extractScore(analysis.seo_score),
      performance: asNumber(
        toObject(report.performance).performance_score,
        extractScore(analysis.seo_score)
      ),
      indexing: extractScore(analysis.seo_score),
    },
    geo: {
      visibility_index: extractScore(analysis.geo_score),
      citation_share: 0,
      brand_anchor: 0,
    },
    aeo: {
      answerability_score: extractScore(analysis.aeo_score),
      extractable_pages: asNumber(
        toObject(report.aeo).extractable_pages ?? analysis.extractable_pages,
        0
      ),
      schema_health:
        toObject(report.aeo).schema_health !== undefined
          ? (toObject(report.aeo).schema_health as Record<string, unknown>)
          : undefined,
      schema_coverage:
        toObject(report.aeo).schema_coverage !== undefined
          ? (toObject(report.aeo).schema_coverage as {
              coverage_percent: number;
              coverage_by_type: Record<string, number>;
              missing_high_impact_types: string[];
            })
          : undefined,
      readability_score:
        typeof toObject(report.aeo).readability_score === "number"
          ? (toObject(report.aeo).readability_score as number)
          : null,
      readability_findings: Array.isArray(toObject(report.aeo).readability_findings)
        ? (toObject(report.aeo).readability_findings as string[])
        : undefined,
      rewrite_suggestions: Array.isArray(toObject(report.aeo).rewrite_suggestions)
        ? (toObject(report.aeo).rewrite_suggestions as AeoRewriteSuggestion[])
        : undefined,
    },
    entities: getLegacyAuditEntities(report, analysis),
    competitors: [],
    suggestions: recommendations.map((action, index) => ({
      priority: index + 1,
      title: `Recommendation ${index + 1}`,
      action,
    })),
    scores: {
      seo: scoreFields.seoScore ?? extractScore(analysis.seo_score),
      geo: scoreFields.geoScore,
      aeo: scoreFields.aeoScore ?? extractScore(analysis.aeo_score),
      overall:
        scoreFields.overallScore ??
        asNumber(
          analysis.overall_score,
          ((scoreFields.seoScore ?? extractScore(analysis.seo_score)) +
            scoreFields.geoScore +
            (scoreFields.aeoScore ?? extractScore(analysis.aeo_score))) /
            3
        ),
    },
    metadata: {
      created_at: String(metadata.created_at ?? nowIso),
      updated_at: String(metadata.updated_at ?? nowIso),
      plan: planFields.historicalPlan,
      current_plan: planFields.currentPlan,
      version: String(metadata.version ?? report.schema_version ?? "legacy"),
      service_status:
        metadata.service_status && typeof metadata.service_status === "object"
          ? (metadata.service_status as Record<string, string>)
          : undefined,
      service_errors:
        metadata.service_errors && typeof metadata.service_errors === "object"
          ? (metadata.service_errors as Record<string, string>)
          : undefined,
      scores_available:
        typeof metadata.scores_available === "boolean" ? metadata.scores_available : undefined,
      audit_outcome: String(metadata.audit_outcome ?? payload.status ?? "completed").toLowerCase(),
      intent: acceptedIntentValues.has(String(metadata.intent).toLowerCase())
        ? (String(metadata.intent).toLowerCase() as
            | "informational"
            | "transactional"
            | "navigational")
        : null,
      query_type: acceptedQueryTypeValues.has(String(metadata.query_type).toLowerCase())
        ? (String(metadata.query_type).toLowerCase() as "informational" | "decision_making")
        : null,
      audit_target_type: targetFields.auditTargetType,
      target_name: targetFields.targetName,
      target_url: targetFields.targetUrl,
      target_metadata: targetFields.targetMetadata,
    },
    geo_comparative: mapCitationSources(toObject(report.geo).citation_sources),
  };
};

const normalizeAuditItem = (payload: AuditHistoryPayload): AuditResult | null => {
  const normalizedStatus = payload.status?.toLowerCase();
  if (normalizedStatus && !reportOutcomes.has(normalizedStatus)) {
    return null;
  }

  if (payload.full_report && typeof payload.full_report === "object") {
    const fullReport = payload.full_report as Record<string, any>;
    const normalizedReport = normalizeAuditReport(fullReport);

    if (isCanonicalAuditReportPayload(normalizedReport)) {
      return applyResolvedAuditHistoryContract(
        canonicalToDashboardAdapter(normalizedReport as CanonicalAuditReport),
        payload
      );
    }
  }

  // If the payload already matches AuditResult shape, use it directly
  if (isAuditResult(payload.full_report)) {
    return applyResolvedAuditHistoryContract(payload.full_report, payload);
  }

  // Legacy fallback for old payloads
  const legacy = coerceLegacyAuditResult(payload);
  if (legacy && isAuditResult(legacy)) {
    return applyResolvedAuditHistoryContract(legacy, payload);
  }

  return null;
};

const toTimestamp = (dateIso: string): number => {
  const timestamp = Date.parse(dateIso);
  return Number.isFinite(timestamp) ? timestamp : 0;
};

/**
 * @deprecated SEO now uses the AI Strategist pipeline (`useAuditHistory` + `auditService.mapAuditHistoryToViewModel`).
 * Keep this adapter for GEO/AEO modules until their migration is complete.
 */
export const normalizeAuditHistoryPayload = (payload: AuditHistoryPayload[]): AuditResult[] => {
  return payload
    .map((item) => normalizeAuditItem(item))
    .filter((audit): audit is AuditResult => audit !== null)
    .sort((a, b) => toTimestamp(a.metadata.created_at) - toTimestamp(b.metadata.created_at));
};

export const isScoreableAuditResult = (audit: AuditResult): boolean => {
  const outcome = audit.metadata.audit_outcome?.toLowerCase();
  if (outcome && !scoreableOutcomes.has(outcome)) {
    return false;
  }

  if (audit.metadata.scores_available === false) {
    return false;
  }

  return true;
};

export const filterScoreableAuditHistory = (history: AuditResult[]): AuditResult[] =>
  history.filter((audit) => isScoreableAuditResult(audit));

export const buildMetricTrendData = (
  history: AuditResult[],
  metricSelector: (audit: AuditResult) => number
): MetricTrendPoint[] => {
  const scoreableHistory = filterScoreableAuditHistory(history);

  return scoreableHistory.map((audit) => ({
    date: audit.metadata.created_at,
    value: asNumber(metricSelector(audit), asNumber(audit.scores.overall, 0)),
  }));
};

export const mapGeoWeeklyTrendData = (trends: GeoTrendPointResponse[]): GeoTrendSeriesPoint[] => {
  return [...trends]
    .sort((a, b) => toTimestamp(a.date) - toTimestamp(b.date))
    .map((trend) => ({
      date: trend.date,
      score: asNumber(trend.score),
      citations: asNumber(trend.citations),
    }));
};

export const buildScoreDistributionData = (
  history: AuditResult[],
  metricSelector: (audit: AuditResult) => number,
  bucketSize = 20
): ScoreDistributionPoint[] => {
  const safeBucketSize = bucketSize > 0 ? bucketSize : 20;
  const bucketCount = Math.ceil(100 / safeBucketSize);

  const buckets = Array.from({ length: bucketCount }, (_, index) => {
    const min = index * safeBucketSize;
    const max = Math.min(100, min + safeBucketSize - 1);
    return {
      bucket: `${min}-${max}`,
      index,
      count: 0,
    };
  });

  const scoreableHistory = filterScoreableAuditHistory(history);

  scoreableHistory.forEach((audit) => {
    const score = Math.max(
      0,
      Math.min(100, asNumber(metricSelector(audit), asNumber(audit.scores.overall, 0)))
    );
    const bucketIndex = Math.min(Math.floor(score / safeBucketSize), buckets.length - 1);
    buckets[bucketIndex].count += 1;
  });

  return buckets;
};
