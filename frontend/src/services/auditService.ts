import { normalizeAuditHistoryPayload } from "@/lib/dashboardHistoryAdapters";
import {
  getAuditEvidenceNumber,
  normalizeAuditReportWithDiagnostics,
  type NormalizeAuditReportWithDiagnosticsResult,
} from "@/lib/auditNormalization";
import type { AuditHistoryPayload } from "@/components/dashboard/dashboardAuditSelection";
import type {
  AuditDataQuality,
  AiStrategicInsights,
  AiStrategistViewModel,
  AuditStatus,
  GroundedStrategicIdea,
  GroundingSource,
  IssueCategory,
  PriorityRoadmapItem,
  PriorityAction,
  RawAuditHistoryEntry,
  ScoreBreakdown,
} from "@/types/aiStrategist";
import type {
  AnswerFailureReason,
  AuditResult,
  CompetitorSnippetComparison,
  QueryCategoryMetric,
  SchemaHealth,
  TrustTrendPoint,
} from "@/types/auditResult";
import type { GeoTrendApiPoint } from "@/types/dashboardCharts";
import { computeScoreDelta, normalizeScoreBreakdown } from "@/utils/seoCalculations";
import {
  fetchProjectById,
  fetchProjectAudits,
  fetchProjectLatestAudit,
  fetchWorkspaceProjects,
  type ProjectAuditHistoryEntry,
  type WorkspaceProjectSummary,
} from "@/services/workspaceService";
import { requestJson, HttpRequestError, parseErrorDetail } from "@/services/http";

const AUDIT_JOBS_ENDPOINT = "/api/audit/jobs";
const AUDIT_ESTIMATE_ENDPOINT = "/api/v1/audit/estimate";
const AUDIT_PREFLIGHT_ENDPOINT = "/api/v1/audit/preflight";
const AUDIT_TIER_DURATIONS_ENDPOINT = "/api/v1/audit/tier-durations";
const GEO_COMPARE_ENDPOINT = "/api/v1/geo/compare";
const reportedAuditHistoryFingerprints = new Set<string>();

const ALLOWED_STATUS = new Set<AuditStatus>([
  "completed",
  "degraded",
  "failed",
  "succeeded",
  "ready",
  "archived",
  "purged",
]);

const asStatus = (value: unknown): AuditStatus => {
  const v = String(value ?? "completed").toLowerCase() as AuditStatus;
  return ALLOWED_STATUS.has(v) ? v : "completed";
};

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback;

const asArray = <T>(value: unknown, fallback: T[] = []): T[] =>
  Array.isArray(value) ? (value as T[]) : fallback;

const asObject = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};

const asNumber = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

const defaultInsights = (): AiStrategicInsights => ({
  executive_summary: "",
  critical_alerts: [],
  priority_roadmap: [],
  content_gap_theory: [],
  technical_debt_explanation: "",
  grounding_sources: [],
  aeo_query_ideas: [],
  geo_prompt_ideas: [],
});

const defaultDataQuality = (): AuditDataQuality => ({
  degraded: false,
  summary: null,
  issues: [],
});

const emitAuditHistorySchemaDrift = (
  entry: RawAuditHistoryEntry,
  fullReport: Record<string, unknown>,
  issues: string[]
) => {
  if (issues.length === 0) {
    return;
  }

  const fingerprint = JSON.stringify({
    auditId: entry.id,
    schemaVersion: fullReport.schema_version ?? null,
    issues,
  });

  if (reportedAuditHistoryFingerprints.has(fingerprint)) {
    return;
  }

  reportedAuditHistoryFingerprints.add(fingerprint);

  const payload = {
    auditId: entry.id,
    status: entry.status ?? null,
    schemaVersion: fullReport.schema_version ?? null,
    issues,
  };

  console.warn("[audit-history-schema-drift]", payload);
};

const normalizeIssueCategoryKey = (value: unknown): IssueCategory["key"] => {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");

  if (!normalized) return "other";

  const acceptedKeys: IssueCategory["key"][] = [
    "technical_seo",
    "content_quality",
    "indexability",
    "mobile_ux",
    "performance",
    "schema",
    "authority",
    "security",
    "other",
  ];

  if (acceptedKeys.includes(normalized as IssueCategory["key"])) {
    return normalized as IssueCategory["key"];
  }

  if (normalized.startsWith("technical")) return "technical_seo";
  if (normalized.startsWith("content")) return "content_quality";
  if (normalized.includes("backlink") || normalized.includes("authority")) return "authority";

  return "other";
};

const normalizeIssueSeverity = (item: Record<string, unknown>): IssueCategory["severity"] => {
  const rawSeverity = String(item.severity ?? item.impact ?? "")
    .trim()
    .toLowerCase();

  if (["low", "medium", "high", "critical"].includes(rawSeverity)) {
    return rawSeverity as IssueCategory["severity"];
  }

  const priority = Number(item.priority);
  if (priority === 1) return "critical";
  if (priority === 2) return "high";
  if (priority === 3) return "medium";
  if (priority > 0) return "low";

  return "medium";
};

const mapIssueCategories = (fullReport: Record<string, unknown>): IssueCategory[] => {
  const items = asArray<Record<string, unknown>>(fullReport.issue_categories, []);
  return items
    .map((item) => {
      const label = asString(item.label, "").trim();
      const count = asNumber(item.count);

      if (!label || count === null) {
        return null;
      }

      return {
        key: normalizeIssueCategoryKey(item.key),
        label,
        count,
        severity: normalizeIssueSeverity(item),
      };
    })
    .filter((item): item is IssueCategory => item !== null);
};

const mapPriorityActions = (fullReport: Record<string, unknown>): PriorityAction[] => {
  const src = asArray<Record<string, unknown>>(fullReport.priority_actions, []);
  if (src.length === 0) {
    return [];
  }

  const parsePriority = (value: unknown): PriorityAction["priority"] => {
    const numeric = Number(value);

    if (Number.isFinite(numeric)) {
      return Math.max(1, Math.min(5, Math.round(numeric))) as PriorityAction["priority"];
    }

    return 3;
  };

  const normalizeImpact = (value: unknown): PriorityAction["impact"] | null => {
    return value === "low" || value === "medium" || value === "high" ? value : null;
  };

  const normalizeEffort = (value: unknown): PriorityAction["effort"] | null => {
    return value === "low" || value === "medium" || value === "high" ? value : null;
  };

  return src
    .map<PriorityAction | null>((item, index) => {
      const impact = normalizeImpact(item.impact);
      const effort = normalizeEffort(item.effort);
      const title = asString(item.title, "");
      const description = asString(item.description, asString(item.action, ""));

      if (!title || !description || !impact || !effort) {
        return null;
      }

      return {
        id: asString(item.id, `action-${index + 1}`),
        title,
        description,
        category: normalizeIssueCategoryKey(item.category),
        priority: parsePriority(item.priority),
        impact,
        effort,
        eta_days: Number.isFinite(Number(item.eta_days)) ? Number(item.eta_days) : null,
        owner: asString(item.owner, "") || null,
      };
    })
    .filter((item): item is PriorityAction => item !== null);
};

const mapInsights = (fullReport: Record<string, unknown>): AiStrategicInsights => {
  const raw = fullReport.ai_strategic_insights ?? fullReport.ai_insights ?? fullReport.insights;
  if (!raw || typeof raw !== "object") return defaultInsights();
  const obj = raw as Record<string, unknown>;

  const criticalAlerts = asArray<string>(obj.critical_alerts, []).filter(
    (x) => typeof x === "string"
  );
  const contentGap = asArray<string>(obj.content_gap_theory, []).filter(
    (x) => typeof x === "string"
  );

  const roadmap = asArray<Record<string, unknown>>(
    obj.priority_roadmap,
    []
  ).map<PriorityRoadmapItem>((x) => ({
    task: asString(x.task, ""),
    category: asString(x.category, ""),
    impact: asString(x.impact, ""),
    effort_score: Number(x.effort_score ?? 0),
    reasoning: asString(x.reasoning, ""),
    confidence:
      x.confidence === "high" || x.confidence === "medium" || x.confidence === "low"
        ? x.confidence
        : undefined,
    label:
      x.label === "measured" || x.label === "inferred" || x.label === "hypothesis"
        ? x.label
        : undefined,
    source_basis: asArray<string>(x.source_basis, []).filter((item) => typeof item === "string"),
  }));

  const groundingSources = asArray<Record<string, unknown>>(obj.grounding_sources, [])
    .map<GroundingSource | null>((x) => {
      const label = asString(x.label, "");
      const sourceType = asString(x.source_type, "");
      const measured = typeof x.measured === "boolean" ? x.measured : null;

      if (!label || !sourceType || measured === null) {
        return null;
      }

      return {
        label,
        source_type: sourceType,
        measured,
        updated_at: asString(x.updated_at, ""),
      };
    })
    .filter((item): item is NonNullable<typeof item> => item !== null);

  const groundedIdeas = (value: unknown): GroundedStrategicIdea[] =>
    asArray<Record<string, unknown>>(value, [])
      .map<GroundedStrategicIdea | null>((x) => {
        const text = asString(x.text, "");
        const confidence =
          x.confidence === "high" || x.confidence === "medium" || x.confidence === "low"
            ? x.confidence
            : null;
        const label =
          x.label === "measured" || x.label === "inferred" || x.label === "hypothesis"
            ? x.label
            : null;

        if (!text || !confidence || !label) {
          return null;
        }

        return {
          text,
          confidence,
          label,
          source_basis: asArray<string>(x.source_basis, []).filter(
            (item) => typeof item === "string"
          ),
          status_note: asString(x.status_note, ""),
          last_verified_at: asString(x.last_verified_at, ""),
        };
      })
      .filter((item): item is NonNullable<typeof item> => item !== null);

  if (
    "summary" in obj ||
    "top_opportunities" in obj ||
    "key_risks" in obj ||
    "next_30_days_plan" in obj
  ) {
    const topOpp = asArray<Record<string, unknown>>(obj.top_opportunities, []);
    const keyRisks = asArray<Record<string, unknown>>(obj.key_risks, []);
    const plan = asArray<string>(obj.next_30_days_plan, []).filter((x) => typeof x === "string");

    return {
      executive_summary: asString(obj.summary, "No strategic insights available yet."),
      critical_alerts: keyRisks
        .map((risk) => asString(risk.title, "Risk"))
        .filter(Boolean)
        .slice(0, 2),
      priority_roadmap: topOpp.slice(0, 3).map<PriorityRoadmapItem>((op, index) => ({
        task: asString(op.title, `Task ${index + 1}`),
        category: "opportunity",
        impact: "medium",
        effort_score: 3,
        reasoning: asString(op.detail, ""),
      })),
      content_gap_theory: plan.slice(0, 3),
      technical_debt_explanation: asString(obj.technical_debt_explanation, ""),
      generated_at: asString(obj.generated_at, ""),
      grounding_sources: groundingSources,
      aeo_query_ideas: groundedIdeas(obj.aeo_query_ideas),
      geo_prompt_ideas: groundedIdeas(obj.geo_prompt_ideas),
    };
  }

  return {
    executive_summary: asString(obj.executive_summary, ""),
    critical_alerts: criticalAlerts,
    priority_roadmap: roadmap.filter(
      (row) => row.task && row.category && row.impact && row.reasoning
    ),
    content_gap_theory: contentGap,
    technical_debt_explanation: asString(obj.technical_debt_explanation, ""),
    generated_at: asString(obj.generated_at, ""),
    audit_id: Number.isFinite(Number(obj.audit_id)) ? Number(obj.audit_id) : undefined,
    project_id: Number.isFinite(Number(obj.project_id)) ? Number(obj.project_id) : null,
    grounding_sources: groundingSources,
    aeo_query_ideas: groundedIdeas(obj.aeo_query_ideas),
    geo_prompt_ideas: groundedIdeas(obj.geo_prompt_ideas),
  };
};

const extractScores = (
  entry: RawAuditHistoryEntry,
  normalization: NormalizeAuditReportWithDiagnosticsResult
): ScoreBreakdown => {
  const report = asObject(entry.full_report);
  const mobileObj = asObject(report.mobile);
  const fallbackSeoScore = asNumber(entry.seo_score);
  const fallbackMobileScore =
    asNumber(mobileObj.score) ??
    asNumber(asObject(report.seo).mobile) ??
    asNumber(asObject(report.scores).mobile);

  return normalizeScoreBreakdown({
    seo:
      getAuditEvidenceNumber(normalization.diagnostics.modules.seo, "overall") ??
      fallbackSeoScore ??
      0,
    speed: getAuditEvidenceNumber(normalization.diagnostics.modules.seo, "performance") ?? 0,
    indexing: getAuditEvidenceNumber(normalization.diagnostics.modules.seo, "indexing") ?? 0,
    mobile: fallbackMobileScore ?? 0,
  });
};

const buildDataQuality = (
  entry: RawAuditHistoryEntry,
  fullReport: Record<string, unknown>,
  normalization: NormalizeAuditReportWithDiagnosticsResult,
  issueCategories: IssueCategory[],
  priorityActions: PriorityAction[]
): AuditDataQuality => {
  const issues = [...normalization.diagnostics.issues];
  const hasSuggestions = asArray(fullReport.suggestions, []).length > 0;
  const hasStructuredIssueCategories = asArray(fullReport.issue_categories, []).length > 0;
  const hasStructuredPriorityActions = asArray(fullReport.priority_actions, []).length > 0;

  if (hasSuggestions && !hasStructuredIssueCategories) {
    issues.push(
      "Issue distribution is unavailable because the audit payload did not include structured issue_categories. The dashboard did not infer categories from generic suggestions."
    );
  }

  if (hasSuggestions && !hasStructuredPriorityActions) {
    issues.push(
      "Priority actions are unavailable because the audit payload did not include structured priority_actions. The dashboard did not infer impact or effort from suggestion text."
    );
  }

  if (hasStructuredIssueCategories && issueCategories.length === 0) {
    issues.push(
      "Issue categories were present but invalid, so the issue distribution is unavailable."
    );
  }

  if (hasStructuredPriorityActions && priorityActions.length === 0) {
    issues.push("Priority actions were present but invalid, so the action table is unavailable.");
  }

  const dedupedIssues = Array.from(new Set(issues));

  if (dedupedIssues.length === 0) {
    return defaultDataQuality();
  }

  emitAuditHistorySchemaDrift(entry, fullReport, dedupedIssues);

  return {
    degraded: true,
    summary: dedupedIssues[0] ?? normalization.diagnostics.summary,
    issues: dedupedIssues,
  };
};

export const mapAuditHistoryToViewModel = (
  history: RawAuditHistoryEntry[]
): AiStrategistViewModel[] => {
  const sorted = [...history].sort(
    (a, b) => Date.parse(a.created_at ?? "") - Date.parse(b.created_at ?? "")
  );

  return sorted.map((entry, index) => {
    const report = asObject(entry.full_report);
    const site = asObject(report.site);
    const normalization = normalizeAuditReportWithDiagnostics(report);
    const issueCategories = mapIssueCategories(report);
    const priorityActions = mapPriorityActions(report);
    const dataQuality = buildDataQuality(
      entry,
      report,
      normalization,
      issueCategories,
      priorityActions
    );
    const currentScores = extractScores(entry, normalization);
    const prev =
      index > 0
        ? extractScores(
            sorted[index - 1] as RawAuditHistoryEntry,
            normalizeAuditReportWithDiagnostics(asObject(sorted[index - 1]?.full_report))
          )
        : undefined;

    return {
      auditId: entry.id,
      siteUrl: asString(
        site.url,
        asString(entry.target_url, asString(entry.url, asString(entry.target_name, "")))
      ),
      createdAt: asString(entry.created_at, new Date(0).toISOString()),
      projectId: entry.project_id,
      status: asStatus(entry.status),
      scores: currentScores,
      scoreDeltaVsPrevious: computeScoreDelta(currentScores, prev),
      issueCategories,
      priorityActions,
      aiInsights: mapInsights(report),
      dataQuality,
    };
  });
};

export type UserProjectSummary = {
  project_id: number;
  domain: string;
  display_name: string;
  audit_count: number;
  latest_seo_score: number | null;
  latest_geo_score: number | null;
  latest_aeo_score: number | null;
  latest_audit_at: string | null;
  category?: string | null;
  type?: string | null;
  is_competitor?: boolean;
};

export type UserSiteSummary = UserProjectSummary & {
  site_id: number;
};

export type GeoSiteSummary = {
  site_id: number;
  audit_count: number;
  avg_geo_score: number;
  avg_visibility_index: number;
  avg_citation_share: number;
  avg_brand_anchor: number;
  intent: "informational" | "transactional" | "navigational" | null;
};

export type GeoTrendPointResponse = GeoTrendApiPoint;

export type GeoCompareResponse = {
  site_a: {
    id: number;
    domain: string;
    audit_count: number;
  };
  site_b: {
    id: number;
    domain: string;
    audit_count: number;
  };
  citation_gap: {
    site_a_citations: number;
    site_b_citations: number;
    delta: number;
    fallback_sources_site_a: string[];
    fallback_sources_site_b: string[];
  };
  source_overlap: {
    count: number;
    domains: string[];
  };
  keyword_dominance: Array<{
    category: string;
    site_a_mentions: number;
    site_b_mentions: number;
    dominant_site: string;
    total_mentions: number;
  }>;
  high_risk_discrepancies: {
    site_a_total: number;
    site_b_total: number;
    items: Array<{
      discrepancy_type: string;
      severity: string;
      site_a_url: string;
      site_b_url: string;
      prompt: string;
    }>;
  };
  window: {
    start_at: string;
    end_at: string;
  };
};

export type AuthorityIndex = {
  value: number;
  components: {
    trustworthiness: number;
    answer_dominance: number;
    schema_health: number;
    readability: number;
  };
  confidence: number;
};

export type AuthorityIndexTrendPoint = {
  date: string;
  value: number;
  audit_count: number;
  confidence: number;
};

export type AeoSiteStatsResponse = {
  site_id: number;
  audit_count: number;
  answer_dominance: {
    site_primary_count: number;
    competitor_primary_count: number;
    unknown_count: number;
    site_primary_share: number;
    competitor_primary_share: number;
    site_primary_share_total: number;
    competitor_primary_share_total: number;
    unknown_share_total: number;
  };
  top_performing_queries: Array<{
    query: string;
    aeo_score: number;
    created_at: string | null;
    intent: string | null;
    query_type: string | null;
  }>;
  answer_failure_reasons: AnswerFailureReason[];
  schema_health: SchemaHealth;
  readability_insights: {
    avg_readability_score: number | null;
    low_readability_audits: number;
    findings: Array<{
      finding: string;
      count: number;
      percentage: number;
    }>;
    top_rewrite_suggestions: Array<{
      paragraph: string;
      suggestion: string;
      score: number;
    }>;
  };
  competitor_benchmark: {
    site_avg_aeo_score: number;
    competitor_avg_aeo_score: number | null;
    score_gap: number | null;
    competitor_count: number;
  };
  query_category_breakdown: QueryCategoryMetric[];
  trustworthiness_trend: TrustTrendPoint[];
  trustworthiness_signal_coverage: number | null;
  authority_index: AuthorityIndex;
  authority_index_trend: AuthorityIndexTrendPoint[];
  query_benchmark: {
    site_id: number;
    site_domain: string;
    competitor_count: number;
    queries: Array<
      CompetitorSnippetComparison & {
        battle_for_snippet: CompetitorSnippetComparison;
      }
    >;
  };
};

type GeoIntent = "informational" | "transactional" | "navigational";

const toNumber = (value: unknown, fallback = 0): number => {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }

  return fallback;
};

const toStringOrNull = (value: unknown): string | null =>
  typeof value === "string" ? value : null;

const toNullableNumber = (value: unknown): number | null => {
  if (value === null || value === undefined) {
    return null;
  }

  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }

  if (typeof value === "string") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }

  return null;
};

const mapProjectToUserProjectSummary = (project: WorkspaceProjectSummary): UserProjectSummary => {
  const domainSource = project.domain_url ?? project.name;
  let domain = domainSource;
  try {
    if (project.domain_url) {
      domain = new URL(project.domain_url).hostname || domainSource;
    }
  } catch {
    domain = domainSource.replace(/^https?:\/\//i, "");
  }

  return {
    project_id: toNumber(project.id, 0),
    domain,
    display_name: asString(project.name, domain),
    audit_count: toNumber(project.audit_count, 0),
    latest_seo_score: toNullableNumber(project.latest_seo_score),
    latest_geo_score: toNullableNumber(project.latest_geo_score),
    latest_aeo_score: toNullableNumber(project.latest_aeo_score),
    latest_audit_at: toStringOrNull(project.last_audit_at),
    category: null,
    type: null,
    is_competitor: false,
  };
};

const mapUserProjectSummaryToLegacySiteSummary = (
  project: UserProjectSummary
): UserSiteSummary => ({
  ...project,
  site_id: project.project_id,
});

const mapProjectAuditToRawHistoryEntry = (
  audit: ProjectAuditHistoryEntry
): RawAuditHistoryEntry => ({
  id: toNumber(audit.id, 0),
  project_id: toNumber(audit.project_id, 0),
  url: asString(audit.url, ""),
  audit_target_type:
    audit.audit_target_type === "brand" || audit.audit_target_type === "website"
      ? audit.audit_target_type
      : undefined,
  target_name: typeof audit.target_name === "string" ? audit.target_name : null,
  target_url: typeof audit.target_url === "string" ? audit.target_url : null,
  target_metadata:
    audit.target_metadata && typeof audit.target_metadata === "object"
      ? audit.target_metadata
      : null,
  created_at: asString(audit.created_at, new Date(0).toISOString()),
  status: asString(audit.status, "completed"),
  audit_type: asString(audit.audit_type, "STANDARD"),
  seo_score: toNullableNumber(audit.seo_score),
  geo_score: toNullableNumber(audit.geo_score),
  aeo_score: toNullableNumber(audit.aeo_score),
  full_report: audit.full_report ?? null,
});

const sortHistoryAscending = <T extends { created_at?: string | null }>(entries: T[]): T[] =>
  [...entries].sort((a, b) => Date.parse(a.created_at ?? "") - Date.parse(b.created_at ?? ""));

const toWinner = (value: unknown): "site" | "competitor" | "tie" | "no_data" => {
  if (value === "site" || value === "competitor" || value === "tie" || value === "no_data") {
    return value;
  }
  return "no_data";
};

const toResultState = (
  winner: "site" | "competitor" | "tie" | "no_data"
): "won" | "lost" | "tie" | "no_data" => {
  if (winner === "site") return "won";
  if (winner === "competitor") return "lost";
  if (winner === "tie") return "tie";
  return "no_data";
};

const asSeverity = (value: unknown): "critical" | "high" | "medium" | "low" => {
  if (value === "critical" || value === "high" || value === "medium" || value === "low") {
    return value;
  }
  return "high";
};

const toSchemaType = (value: unknown): string => {
  if (typeof value !== "string") return "";
  const normalized = value.trim();
  return normalized.replace(/^https?:\/\/schema\.org\//i, "").replace(/^@?type\s*:\s*/i, "");
};

const buildJsonLdRecommendation = (schemaType: string): string => {
  const normalized = schemaType || "Thing";
  return `Add a JSON-LD block for ${normalized} with @context, @type, name, description, and canonical URL fields.`;
};

const normalizeSnippetComparison = (
  value: unknown,
  siteDomain = ""
): CompetitorSnippetComparison => {
  const payload = asObject(value);
  const site = asObject(payload.site);
  const competitor = payload.competitor === null ? null : asObject(payload.competitor);
  const winner = toWinner(payload.winner);

  return {
    query: asString(payload.query),
    winner,
    winner_reason:
      payload.winner_reason === "missing_site_data" ||
      payload.winner_reason === "missing_competitor_data" ||
      payload.winner_reason === "score_delta"
        ? payload.winner_reason
        : undefined,
    result_state: toResultState(winner),
    site: {
      domain: asString(site.domain, siteDomain),
      answer_relevance: toNullableNumber(site.answer_relevance),
      answer_excerpt: toStringOrNull(site.answer_excerpt),
      answer_relevance_source: toStringOrNull(site.answer_relevance_source),
      answer_relevance_fallback_used: Boolean(site.answer_relevance_fallback_used),
      selected_audit_timestamp: toStringOrNull(site.selected_audit_timestamp ?? site.created_at),
    },
    competitor: competitor
      ? {
          domain: toStringOrNull(competitor.domain),
          answer_relevance: toNullableNumber(competitor.answer_relevance),
          answer_excerpt: toStringOrNull(competitor.answer_excerpt),
          answer_relevance_source: toStringOrNull(competitor.answer_relevance_source),
          answer_relevance_fallback_used: Boolean(competitor.answer_relevance_fallback_used),
          selected_audit_timestamp: toStringOrNull(
            competitor.selected_audit_timestamp ?? competitor.created_at
          ),
        }
      : null,
    competitors: asArray<unknown>(payload.competitors, []).map((entry) => {
      const item = asObject(entry);
      return {
        site_id: toNumber(item.site_id, 0),
        domain: toStringOrNull(item.domain),
        display_name: toStringOrNull(item.display_name),
        answer_relevance: toNullableNumber(item.answer_relevance),
        answer_excerpt: toStringOrNull(item.answer_excerpt),
        answer_relevance_source: toStringOrNull(item.answer_relevance_source),
        answer_relevance_fallback_used: Boolean(item.answer_relevance_fallback_used),
        selected_audit_timestamp: toStringOrNull(item.selected_audit_timestamp ?? item.created_at),
      };
    }),
  };
};

export const normalizeAeoSiteStatsPayload = (
  payload: unknown,
  siteIdFallback = 0
): AeoSiteStatsResponse => {
  const source = asObject(payload);
  const answerDominance = asObject(source.answer_dominance);
  const schemaHealth = asObject(source.schema_health);
  const queryBenchmark = asObject(source.query_benchmark);
  const competitorBenchmark = asObject(source.competitor_benchmark);
  const readabilityInsights = asObject(source.readability_insights);
  const siteDomain = asString(queryBenchmark.site_domain);

  const normalizedMissingHighImpactTypes = asArray<unknown>(
    schemaHealth.missing_high_impact_types,
    []
  ).map((entry) => {
    if (typeof entry === "string") {
      const type = toSchemaType(entry);
      return {
        type,
        count: 0,
        percentage: 0,
      };
    }

    const item = asObject(entry);
    const type = toSchemaType(item.type ?? item.schema_type ?? item.name);
    return {
      type,
      count: toNumber(item.count, 0),
      percentage: toNumber(item.percentage, 0),
    };
  });

  const normalizedHighImpactBlockers = asArray<unknown>(schemaHealth.high_impact_blockers, []).map(
    (entry) => {
      if (typeof entry === "string") {
        const inferredType =
          normalizedMissingHighImpactTypes.find((item) =>
            entry.toLowerCase().includes(item.type.toLowerCase())
          )?.type ?? "Schema";

        return {
          type: inferredType,
          severity: "high" as const,
          recommendation: entry.trim() || buildJsonLdRecommendation(inferredType),
        };
      }

      const item = asObject(entry);
      const type = toSchemaType(item.type ?? item.schema_type ?? item.name);
      const recommendation = asString(
        item.recommendation,
        asString(item.message, buildJsonLdRecommendation(type || "Schema"))
      );

      return {
        type: type || "Schema",
        severity: asSeverity(item.severity),
        recommendation,
      };
    }
  );

  const queries = asArray<unknown>(queryBenchmark.queries, []).map((query) => {
    const normalized = normalizeSnippetComparison(query, siteDomain);
    const raw = asObject(query);
    const battle =
      raw.battle_for_snippet === undefined
        ? normalized
        : normalizeSnippetComparison(raw.battle_for_snippet, siteDomain);

    return {
      ...normalized,
      battle_for_snippet: battle,
    };
  });

  return {
    site_id: toNumber(source.site_id, siteIdFallback),
    audit_count: toNumber(source.audit_count, 0),
    answer_dominance: {
      site_primary_count: toNumber(answerDominance.site_primary_count, 0),
      competitor_primary_count: toNumber(answerDominance.competitor_primary_count, 0),
      unknown_count: toNumber(answerDominance.unknown_count, 0),
      site_primary_share: toNumber(answerDominance.site_primary_share, 0),
      competitor_primary_share: toNumber(answerDominance.competitor_primary_share, 0),
      site_primary_share_total: toNumber(answerDominance.site_primary_share_total, 0),
      competitor_primary_share_total: toNumber(answerDominance.competitor_primary_share_total, 0),
      unknown_share_total: toNumber(answerDominance.unknown_share_total, 0),
    },
    top_performing_queries: asArray<unknown>(source.top_performing_queries, []).map((entry) => {
      const item = asObject(entry);
      return {
        query: asString(item.query),
        aeo_score: toNumber(item.aeo_score, 0),
        created_at: toStringOrNull(item.created_at),
        intent: toStringOrNull(item.intent),
        query_type: toStringOrNull(item.query_type),
      };
    }),
    answer_failure_reasons: asArray<unknown>(source.answer_failure_reasons, []).map((entry) => {
      const item = asObject(entry);
      return {
        reason: asString(item.reason, "unknown"),
        count: toNumber(item.count, 0),
        percentage: toNumber(item.percentage, 0),
      };
    }),
    schema_health: {
      avg_score: toNumber(schemaHealth.avg_score, 0),
      healthy_audits: toNumber(schemaHealth.healthy_audits, 0),
      issue_count: toNumber(schemaHealth.issue_count, 0),
      coverage_percent: toNumber(schemaHealth.coverage_percent, 0),
      coverage_by_type: Object.fromEntries(
        Object.entries(asObject(schemaHealth.coverage_by_type)).map(([type, value]) => [
          type,
          toNumber(value, 0),
        ])
      ),
      missing_high_impact_types: normalizedMissingHighImpactTypes,
      high_impact_blockers: normalizedHighImpactBlockers,
    },
    readability_insights: {
      avg_readability_score: toNullableNumber(readabilityInsights.avg_readability_score),
      low_readability_audits: toNumber(readabilityInsights.low_readability_audits, 0),
      findings: asArray<unknown>(readabilityInsights.findings, []).map((entry) => {
        const item = asObject(entry);
        return {
          finding: asString(item.finding),
          count: toNumber(item.count, 0),
          percentage: toNumber(item.percentage, 0),
        };
      }),
      top_rewrite_suggestions: asArray<unknown>(
        readabilityInsights.top_rewrite_suggestions,
        []
      ).map((entry) => {
        const item = asObject(entry);
        return {
          paragraph: asString(item.paragraph),
          suggestion: asString(item.suggestion),
          score: toNumber(item.score, 1),
        };
      }),
    },
    competitor_benchmark: {
      site_avg_aeo_score: toNumber(competitorBenchmark.site_avg_aeo_score, 0),
      competitor_avg_aeo_score: toNullableNumber(competitorBenchmark.competitor_avg_aeo_score),
      score_gap: toNullableNumber(competitorBenchmark.score_gap),
      competitor_count: toNumber(competitorBenchmark.competitor_count, 0),
    },
    query_category_breakdown: asArray<unknown>(source.query_category_breakdown, []).map((entry) => {
      const item = asObject(entry);
      return {
        query_type: asString(item.query_type, "unknown"),
        count: toNumber(item.count, 0),
        percentage: toNumber(item.percentage, 0),
        avg_aeo_score: toNullableNumber(item.avg_aeo_score),
        median_aeo_score: toNullableNumber(item.median_aeo_score),
        win_rate: toNullableNumber(item.win_rate),
      };
    }),
    trustworthiness_trend: asArray<unknown>(source.trustworthiness_trend, []).map((entry) => {
      const item = asObject(entry);
      return {
        date: asString(item.date),
        score: toNullableNumber(item.score),
        audit_count: toNumber(item.audit_count, 0),
        signal_coverage: toNullableNumber(item.signal_coverage),
      };
    }),
    trustworthiness_signal_coverage: toNullableNumber(source.trustworthiness_signal_coverage),
    authority_index: {
      value: toNumber(asObject(source.authority_index).value, 0),
      components: {
        trustworthiness: toNumber(
          asObject(asObject(source.authority_index).components).trustworthiness,
          0
        ),
        answer_dominance: toNumber(
          asObject(asObject(source.authority_index).components).answer_dominance,
          0
        ),
        schema_health: toNumber(
          asObject(asObject(source.authority_index).components).schema_health,
          0
        ),
        readability: toNumber(asObject(asObject(source.authority_index).components).readability, 0),
      },
      confidence: toNumber(asObject(source.authority_index).confidence, 0),
    },
    authority_index_trend: asArray<unknown>(source.authority_index_trend, []).map((entry) => {
      const item = asObject(entry);
      return {
        date: asString(item.date),
        value: toNumber(item.value, 0),
        audit_count: toNumber(item.audit_count, 0),
        confidence: toNumber(item.confidence, 0),
      };
    }),
    query_benchmark: {
      site_id: toNumber(queryBenchmark.site_id, siteIdFallback),
      site_domain: siteDomain,
      competitor_count: toNumber(queryBenchmark.competitor_count, 0),
      queries,
    },
  };
};

const asGeoIntent = (value: unknown): GeoIntent | null => {
  if (value === "informational" || value === "transactional" || value === "navigational") {
    return value;
  }
  return null;
};

const average = (values: number[]): number =>
  values.length > 0 ? values.reduce((sum, value) => sum + value, 0) / values.length : 0;

const toDateOnly = (isoDate: string | null | undefined): string =>
  typeof isoDate === "string" && isoDate.length >= 10
    ? isoDate.slice(0, 10)
    : new Date(0).toISOString().slice(0, 10);

const parseProjectDomain = (projectDomainUrl: string | null | undefined, fallback = ""): string => {
  const raw = asString(projectDomainUrl, "").trim();
  if (!raw) return fallback;
  try {
    return new URL(raw).hostname || raw;
  } catch {
    return raw.replace(/^https?:\/\//i, "");
  }
};

const extractGeoMetricsFromAudit = (audit: ProjectAuditHistoryEntry) => {
  const report = asObject(audit.full_report);
  const geo = asObject(report.geo);
  const metadata = asObject(report.metadata);

  return {
    geoScore: toNumber(audit.geo_score, toNumber(geo.visibility_index, 0)),
    visibilityIndex: toNumber(geo.visibility_index, toNumber(audit.geo_score, 0)),
    citationShare: toNullableNumber(geo.citation_share),
    brandAnchor: toNullableNumber(geo.brand_anchor),
    intent: asGeoIntent(metadata.intent ?? report.intent),
  };
};

const buildProjectScopedGeoSummary = (
  projectId: number,
  audits: ProjectAuditHistoryEntry[]
): GeoSiteSummary => {
  const metrics = audits.map(extractGeoMetricsFromAudit);
  const intents = metrics
    .map((item) => item.intent)
    .filter((item): item is GeoIntent => Boolean(item));

  return {
    site_id: projectId,
    audit_count: audits.length,
    avg_geo_score: average(metrics.map((item) => item.geoScore)),
    avg_visibility_index: average(metrics.map((item) => item.visibilityIndex)),
    avg_citation_share: average(
      metrics
        .map((item) => item.citationShare)
        .filter((value): value is number => typeof value === "number")
    ),
    avg_brand_anchor: average(
      metrics
        .map((item) => item.brandAnchor)
        .filter((value): value is number => typeof value === "number")
    ),
    intent: intents.at(-1) ?? null,
  };
};

const buildProjectScopedGeoTrend = (audits: ProjectAuditHistoryEntry[]): GeoTrendPointResponse[] =>
  [...audits]
    .sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
    .map((audit) => {
      const metrics = extractGeoMetricsFromAudit(audit);
      return {
        date: toDateOnly(audit.created_at),
        score: metrics.geoScore,
        citations: metrics.citationShare ?? 0,
        intent: metrics.intent,
      } satisfies GeoTrendPointResponse;
    });

const buildProjectScopedAeoStatsPayload = async (
  headers: HeadersInit,
  projectId: number
): Promise<AeoSiteStatsResponse> => {
  const [project, latestAudit, audits] = await Promise.all([
    fetchProjectById(projectId, headers),
    fetchProjectLatestAudit(projectId, headers, { includeFullReport: true }),
    fetchProjectAudits(projectId, headers, { includeFullReport: true, limit: 100 }),
  ]);

  const report = asObject(latestAudit?.full_report);
  const aeoReport = asObject(report.aeo);
  const metadata = asObject(report.metadata);
  const competitors = asArray<Record<string, unknown>>(report.competitors);
  const competitorScores = competitors
    .map((entry) => toNullableNumber(entry.aeo_score ?? entry.score))
    .filter((value): value is number => value !== null);

  const siteDomain = parseProjectDomain(project.domain_url, project.name);
  const siteAeoScore = toNumber(latestAudit?.aeo_score, toNumber(aeoReport.answerability_score, 0));
  const trustworthinessTrend = [...audits].reverse().map((audit) => {
    const auditReport = asObject(audit.full_report);
    const auditAeo = asObject(auditReport.aeo);
    const auditMetadata = asObject(auditReport.metadata);
    return {
      date: toDateOnly(audit.created_at),
      score: toNullableNumber(
        auditAeo.trustworthiness_score ?? auditMetadata.trustworthiness_score
      ),
      audit_count: 1,
      signal_coverage: toNullableNumber(
        auditAeo.trustworthiness_signal_coverage ?? auditMetadata.trustworthiness_signal_coverage
      ),
    };
  });

  const authorityTrend = [...audits].reverse().map((audit) => {
    const auditReport = asObject(audit.full_report);
    const authorityIndex = asObject(auditReport.authority_index);
    return {
      date: toDateOnly(audit.created_at),
      value: toNumber(authorityIndex.value, toNumber(audit.aeo_score, 0)),
      audit_count: 1,
      confidence: toNumber(authorityIndex.confidence, 0),
    };
  });

  const derivedPayload = {
    ...report,
    site_id: projectId,
    audit_count: audits.length,
    answer_dominance: report.answer_dominance ?? aeoReport.answer_dominance ?? undefined,
    top_performing_queries: report.top_performing_queries ?? aeoReport.top_performing_queries ?? [],
    answer_failure_reasons: report.answer_failure_reasons ?? aeoReport.answer_failure_reasons ?? [],
    schema_health: report.schema_health ?? aeoReport.schema_health ?? {},
    readability_insights: report.readability_insights ?? aeoReport.readability_insights ?? {},
    competitor_benchmark: report.competitor_benchmark ?? {
      site_avg_aeo_score: siteAeoScore,
      competitor_avg_aeo_score: competitorScores.length > 0 ? average(competitorScores) : null,
      score_gap: competitorScores.length > 0 ? siteAeoScore - average(competitorScores) : null,
      competitor_count: competitorScores.length,
    },
    query_category_breakdown: report.query_category_breakdown ?? [],
    trustworthiness_trend: report.trustworthiness_trend ?? trustworthinessTrend,
    trustworthiness_signal_coverage:
      report.trustworthiness_signal_coverage ??
      toNullableNumber(
        aeoReport.trustworthiness_signal_coverage ?? metadata.trustworthiness_signal_coverage
      ),
    authority_index: report.authority_index ?? {
      value: siteAeoScore,
      components: {
        trustworthiness: siteAeoScore,
        answer_dominance: siteAeoScore,
        schema_health: toNumber(asObject(report.schema_health).avg_score, 0),
        readability: toNumber(asObject(report.readability_insights).avg_readability_score, 0),
      },
      confidence: Math.min(100, audits.length * 10),
    },
    authority_index_trend: report.authority_index_trend ?? authorityTrend,
    query_benchmark: report.query_benchmark ?? {
      site_id: projectId,
      site_domain: siteDomain,
      competitor_count: competitors.length,
      queries: report.competitor_snippet_comparisons ?? [],
    },
  };

  return normalizeAeoSiteStatsPayload(derivedPayload, projectId);
};

export const geoSiteSummaryClient = {
  async get(headers: HeadersInit, siteId: number, intent?: GeoIntent): Promise<GeoSiteSummary> {
    const audits = await fetchProjectAudits(siteId, headers, {
      includeFullReport: true,
      limit: 100,
    });
    const filteredAudits = intent
      ? audits.filter((audit) => extractGeoMetricsFromAudit(audit).intent === intent)
      : audits;
    return buildProjectScopedGeoSummary(siteId, filteredAudits);
  },
};

export const geoTrendsClient = {
  async get(
    headers: HeadersInit,
    siteId: number,
    intent?: GeoIntent
  ): Promise<GeoTrendPointResponse[]> {
    const audits = await fetchProjectAudits(siteId, headers, {
      includeFullReport: true,
      limit: 100,
    });
    const trend = buildProjectScopedGeoTrend(audits);
    return intent ? trend.filter((point) => point.intent === intent) : trend;
  },
};

export const geoCompareClient = {
  async get(
    headers: HeadersInit,
    siteAId: number,
    siteBId: number,
    startAt?: string,
    endAt?: string
  ): Promise<GeoCompareResponse> {
    const query = new URLSearchParams({
      site_a_id: String(siteAId),
      site_b_id: String(siteBId),
    });
    if (startAt) query.set("start_at", startAt);
    if (endAt) query.set("end_at", endAt);

    return requestJson<GeoCompareResponse>({
      endpoint: `${GEO_COMPARE_ENDPOINT}?${query.toString()}`,
      method: "GET",
      headers,
      errorMessage: "Unable to load AI visibility comparison.",
    });
  },
};

export const aeoSiteStatsClient = {
  async get(headers: HeadersInit, siteId: number): Promise<AeoSiteStatsResponse> {
    return buildProjectScopedAeoStatsPayload(headers, siteId);
  },
};

export const fetchUserProjects = async (
  headers: HeadersInit = {}
): Promise<UserProjectSummary[]> => {
  const projects = await fetchWorkspaceProjects(headers);
  return projects.map(mapProjectToUserProjectSummary);
};

export const fetchUserSites = async (headers: HeadersInit = {}): Promise<UserSiteSummary[]> => {
  const projects = await fetchUserProjects(headers);
  return projects.map(mapUserProjectSummaryToLegacySiteSummary);
};

export const fetchAuditHistory = async (
  headers: HeadersInit = {},
  projectId?: number
): Promise<RawAuditHistoryEntry[]> => {
  if (typeof projectId === "number") {
    const projectHistory = await fetchProjectAudits(projectId, headers, {
      includeFullReport: true,
      limit: 100,
    });
    return sortHistoryAscending(projectHistory.map(mapProjectAuditToRawHistoryEntry));
  }

  const projects = await fetchWorkspaceProjects(headers);
  if (projects.length === 0) {
    return [];
  }

  const settled = await Promise.allSettled(
    projects.map((project) =>
      fetchProjectAudits(project.id, headers, {
        includeFullReport: true,
        limit: 25,
      })
    )
  );

  const mergedProject = settled
    .filter(
      (result): result is PromiseFulfilledResult<ProjectAuditHistoryEntry[]> =>
        result.status === "fulfilled"
    )
    .flatMap((result) => result.value)
    .map(mapProjectAuditToRawHistoryEntry);

  const deduped = Array.from(new Map(mergedProject.map((item) => [item.id, item])).values());
  return sortHistoryAscending(deduped);
};

export const fetchGeoSiteSummary = async (
  headers: HeadersInit,
  siteId: number,
  intent?: GeoIntent
): Promise<GeoSiteSummary> => geoSiteSummaryClient.get(headers, siteId, intent);

export const fetchGeoTrends = async (
  headers: HeadersInit,
  siteId: number,
  intent?: GeoIntent
): Promise<GeoTrendPointResponse[]> => geoTrendsClient.get(headers, siteId, intent);

export const fetchGeoCompare = async (
  headers: HeadersInit,
  siteAId: number,
  siteBId: number,
  startAt?: string,
  endAt?: string
): Promise<GeoCompareResponse> => geoCompareClient.get(headers, siteAId, siteBId, startAt, endAt);

export const fetchAeoSiteStats = async (
  headers: HeadersInit,
  siteId: number
): Promise<AeoSiteStatsResponse> => aeoSiteStatsClient.get(headers, siteId);

export type CreateAuditJobInput = {
  projectId: number;
  url?: string;
  auditTargetType?: "website" | "brand";
  targetName?: string;
  targetUrl?: string;
  targetMetadata?: Record<string, unknown>;
  auditData?: Record<string, unknown>;
  serpPreview?: Record<string, unknown>[];
  provider?: string;
  tier: string;
  requestId: string;
  language?: string;
  market?: string;
  category?: string;
  entities?: string | string[];
  selectedModels?: string[];
};

export type CreateAuditJobPayload = {
  project_id: number;
  url?: string;
  audit_target_type?: "website" | "brand";
  target_name?: string;
  target_url?: string;
  target_metadata?: Record<string, unknown>;
  audit_data?: Record<string, unknown>;
  serp_preview?: Record<string, unknown>[];
  provider?: string;
  tier: string;
  request_id: string;
  language?: string;
  market?: string;
  category?: string;
  entities?: string[];
  selected_models?: string[];
};

export type CreateAuditJobResponse = {
  job_id: string;
  status: string;
  audit_target_type?: "website" | "brand";
  target_name?: string | null;
  target_url?: string | null;
  requested_tier?: string | null;
  mode_label?: string | null;
  request_id?: string | null;
};

export type AuditCreditEstimateInput = {
  auditTargetType?: "website" | "brand";
  targetName?: string;
  targetMetadata?: Record<string, unknown>;
  provider?: string;
  tier: string;
  category?: string;
  market?: string;
  entities?: string | string[];
  selectedModels?: string[];
  selected_models?: string[];
  targetUrl?: string;
  auditData?: Record<string, unknown>;
  serpPreview?: Record<string, unknown>[];
};

export type AuditCreditEstimateResponse = {
  consumes_scan: boolean;
  has_active_subscription: boolean;
  scans_used: number;
  scans_remaining?: number | null;
  reset_at?: string | null;
  confidence: number;
  provider: string;
  tier: string;
  tier_class: string;
  execution_tier: string;
  mode_label: string;
};

export type AuditPreflightResponse = {
  ok: boolean;
  url: string;
  status_code?: number | null;
  method?: "HEAD" | "GET";
};

const normalizeEntities = (entities?: string | string[]): string[] | undefined => {
  if (!entities) return undefined;

  const rawItems = Array.isArray(entities) ? entities : entities.split(",");
  const normalized = rawItems.map((item) => item.trim()).filter(Boolean);

  return normalized.length > 0 ? normalized : undefined;
};

export const buildCreateAuditJobPayload = (input: CreateAuditJobInput): CreateAuditJobPayload => {
  const legacyUrl = input.url?.trim() ?? "";
  const resolvedTargetUrl = input.targetUrl?.trim() || legacyUrl || undefined;
  const resolvedTargetType = input.auditTargetType ?? "website";
  const resolvedTargetName = input.targetName?.trim();
  const payload: CreateAuditJobPayload = {
    project_id: input.projectId,
    tier: input.tier,
    request_id: input.requestId,
    audit_target_type: resolvedTargetType,
  };

  if (legacyUrl) payload.url = legacyUrl;
  if (resolvedTargetUrl) payload.target_url = resolvedTargetUrl;
  if (resolvedTargetName) payload.target_name = resolvedTargetName;
  if (input.targetMetadata && Object.keys(input.targetMetadata).length > 0) {
    payload.target_metadata = input.targetMetadata;
  }
  if (input.auditData && Object.keys(input.auditData).length > 0) {
    payload.audit_data = input.auditData;
  }
  if (input.serpPreview && input.serpPreview.length > 0) {
    payload.serp_preview = input.serpPreview;
  }

  if (input.provider?.trim()) payload.provider = input.provider.trim();
  if (input.language?.trim()) payload.language = input.language.trim();
  if (input.market?.trim()) payload.market = input.market.trim();
  if (input.category?.trim()) payload.category = input.category.trim();

  const entities = normalizeEntities(input.entities);
  if (entities) {
    payload.entities = entities;
  }

  if (input.selectedModels && input.selectedModels.length >= 2) {
    payload.selected_models = input.selectedModels;
  }

  return payload;
};

export class AuditConflictError extends Error {
  existingJobId: string | null;
  constructor(message: string, existingJobId: string | null) {
    super(message);
    this.name = "AuditConflictError";
    this.existingJobId = existingJobId;
  }
}

export const createAuditJob = async (
  input: CreateAuditJobInput,
  headers: HeadersInit = {}
): Promise<CreateAuditJobResponse> => {
  const body = buildCreateAuditJobPayload(input);
  const normalizedHeaders: Record<string, string> = { "Content-Type": "application/json" };
  if (headers instanceof Headers) {
    headers.forEach((v, k) => {
      normalizedHeaders[k] = v;
    });
  } else if (Array.isArray(headers)) {
    headers.forEach(([k, v]) => {
      normalizedHeaders[k] = v;
    });
  } else {
    Object.entries(headers).forEach(([k, v]) => {
      if (v !== undefined) normalizedHeaders[k] = String(v);
    });
  }
  const response = await fetch(AUDIT_JOBS_ENDPOINT, {
    method: "POST",
    headers: normalizedHeaders,
    body: JSON.stringify(body),
  });
  if (response.status === 409) {
    const payload = (await response.json().catch(() => null)) as {
      detail?: string;
      existing_job_id?: string;
    } | null;
    const existingJobId =
      response.headers.get("X-Existing-Job-Id") ?? payload?.existing_job_id ?? null;
    throw new AuditConflictError(
      payload?.detail ?? "An audit for this target is already in progress.",
      existingJobId
    );
  }
  if (!response.ok) {
    throw new HttpRequestError(
      response.status,
      await parseErrorDetail(response, "Unable to run the audit.")
    );
  }
  return (await response.json()) as CreateAuditJobResponse;
};

export const estimateAuditCredits = async (
  input: AuditCreditEstimateInput,
  headers: HeadersInit = {}
): Promise<AuditCreditEstimateResponse> => {
  const selectedModels = input.selectedModels ?? input.selected_models;
  const payload: {
    audit_target_type?: "website" | "brand";
    target_name?: string;
    target_metadata?: Record<string, unknown>;
    provider?: string;
    tier: string;
    category: string | null;
    market: string | null;
    entities: string[];
    selected_models?: string[];
    target_url?: string;
    audit_data?: Record<string, unknown>;
    serp_preview?: Record<string, unknown>[];
  } = {
    tier: input.tier,
    category: input.category?.trim() || null,
    market: input.market?.trim() || null,
    entities: normalizeEntities(input.entities) ?? [],
    ...(selectedModels && selectedModels.length >= 2 ? { selected_models: selectedModels } : {}),
  };
  if (input.provider?.trim()) {
    payload.provider = input.provider.trim();
  }
  if (input.auditTargetType) {
    payload.audit_target_type = input.auditTargetType;
  }
  if (input.targetName?.trim()) {
    payload.target_name = input.targetName.trim();
  }
  if (input.targetUrl?.trim()) {
    payload.target_url = input.targetUrl.trim();
  }
  if (input.targetMetadata && Object.keys(input.targetMetadata).length > 0) {
    payload.target_metadata = input.targetMetadata;
  }
  if (input.auditData && Object.keys(input.auditData).length > 0) {
    payload.audit_data = input.auditData;
  }
  if (input.serpPreview && input.serpPreview.length > 0) {
    payload.serp_preview = input.serpPreview;
  }

  return requestJson<AuditCreditEstimateResponse>({
    endpoint: AUDIT_ESTIMATE_ENDPOINT,
    method: "POST",
    headers,
    body: payload,
    errorMessage: "Unable to estimate the scan cost.",
  });
};

export const preflightAuditUrl = async (
  url: string,
  headers: HeadersInit = {}
): Promise<AuditPreflightResponse> => {
  return requestJson<AuditPreflightResponse>({
    endpoint: `${AUDIT_PREFLIGHT_ENDPOINT}?url=${encodeURIComponent(url)}`,
    method: "GET",
    headers,
    errorMessage: "URL preflight failed.",
  });
};

export const fetchAuditById = async (
  auditId: number,
  headers: HeadersInit = {}
): Promise<RawAuditHistoryEntry> => {
  return requestJson<RawAuditHistoryEntry>({
    endpoint: `/api/v1/audits/${auditId}`,
    method: "GET",
    headers,
    errorMessage: "Unable to load the completed audit.",
  });
};

/**
 * One tier's measured scan duration as the backend publishes it (SIGV2-1177).
 *
 * The numbers are the p25..p75 range of completed runs in whole minutes,
 * rounded outward, plus the sample the quartiles rest on. `computed_at` is an
 * ISO timestamp; a figure absent from `tiers` means the tier has no
 * publishable measurement and the surface must state none.
 */
export type TierDurationFigure = {
  low_minutes: number;
  high_minutes: number;
  median_minutes: number;
  sample_size: number;
  window_days: number;
  computed_at: string;
};

export type TierDurationsResponse = {
  statistic: string;
  min_sample_size: number;
  window_days: number;
  tiers: Record<string, TierDurationFigure>;
};

export const getTierDurations = async (
  headers: HeadersInit = {}
): Promise<TierDurationsResponse> => {
  return requestJson<TierDurationsResponse>({
    endpoint: AUDIT_TIER_DURATIONS_ENDPOINT,
    method: "GET",
    headers,
    errorMessage: "Unable to load measured scan durations.",
  });
};

export async function fetchLegacyAuditHistory(
  headers: Record<string, string>,
  projectId?: number
): Promise<AuditResult[]> {
  const payload = (await fetchAuditHistory(headers, projectId)) as AuditHistoryPayload[];
  const normalized = normalizeAuditHistoryPayload(payload);

  if (payload.length > 0 && normalized.length === 0) {
    throw new Error("Audit history response missing full_report data.");
  }

  return normalized;
}
