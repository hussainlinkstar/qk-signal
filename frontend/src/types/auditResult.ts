export type SiteInfo = {
  url: string | null;
  market: string;
  language: string;
};

export type AuditTargetType = "website" | "brand";

export type AuditTarget = {
  type: AuditTargetType;
  name: string | null;
  url: string | null;
  metadata: Record<string, unknown>;
};

export type SeoBreakdown = {
  onpage: number;
  performance: number;
  indexing: number;
  core_web_vitals?: number;
  technical_seo?: number;
  onpage_content?: number;
  eeat_trust?: number;
  security_accessibility?: number;
};

export type GeoBreakdown = {
  visibility_index: number;
  citation_share: number | null;
  brand_anchor: number | null;
};

export type GeoCitationSource = {
  domain: string;
  citation_count: number;
  trust_score: number;
  owner: "my_site" | "competitor" | "other";
};

export type GeoStrategicRecommendation = {
  insight: string;
  recommended_action: string;
};

export type GeoComparativePayload = {
  citation_sources: GeoCitationSource[];
  strategic_recommendations: GeoStrategicRecommendation[];
};

export type AeoRewriteSuggestion = {
  paragraph: string;
  score: number;
  suggestion: string;
};

export type AeoBreakdown = {
  answerability_score: number;
  extractable_pages: number | null;
  schema_health?: Record<string, unknown>;
  schema_coverage?: {
    coverage_percent: number;
    coverage_by_type: Record<string, number>;
    missing_high_impact_types: string[];
  };
  readability_score?: number | null;
  readability_findings?: string[];
  rewrite_suggestions?: AeoRewriteSuggestion[];
};

export type AnswerFailureReason = {
  reason: string;
  count: number;
  percentage: number;
};

export type SchemaHealth = {
  avg_score: number;
  healthy_audits: number;
  issue_count: number;
  coverage_percent: number;
  coverage_by_type: Record<string, number>;
  missing_high_impact_types: Array<{ type: string; count: number; percentage: number }>;
  high_impact_blockers: Array<{
    type: string;
    severity: "critical" | "high" | "medium" | "low";
    recommendation: string;
  }>;
};

export type QueryCategoryMetric = {
  query_type: string;
  count: number;
  percentage: number;
  avg_aeo_score?: number | null;
  median_aeo_score?: number | null;
  win_rate?: number | null;
};

export type CompetitorSnippetComparison = {
  query: string;
  winner: "site" | "competitor" | "tie" | "no_data";
  winner_reason?: "missing_site_data" | "missing_competitor_data" | "score_delta";
  result_state?: "won" | "lost" | "tie" | "no_data";
  site: {
    domain: string;
    answer_relevance: number | null;
    answer_excerpt: string | null;
    answer_relevance_source?: string | null;
    answer_relevance_fallback_used?: boolean;
    selected_audit_timestamp?: string | null;
  };
  competitor: {
    domain: string | null;
    answer_relevance: number | null;
    answer_excerpt: string | null;
    answer_relevance_source?: string | null;
    answer_relevance_fallback_used?: boolean;
    selected_audit_timestamp?: string | null;
  } | null;
  competitors?: Array<{
    site_id?: number;
    domain: string | null;
    display_name?: string | null;
    answer_relevance: number | null;
    answer_excerpt: string | null;
    answer_relevance_source?: string | null;
    answer_relevance_fallback_used?: boolean;
    selected_audit_timestamp?: string | null;
  }>;
};

export type TrustTrendPoint = {
  date: string;
  score: number | null;
  audit_count: number;
  signal_coverage?: number | null;
};

export type AeoSiteStats = {
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
  answer_failure_reasons: AnswerFailureReason[];
  schema_health: SchemaHealth;
  query_category_breakdown: QueryCategoryMetric[];
  trustworthiness_trend: TrustTrendPoint[];
  competitor_snippet_comparisons: CompetitorSnippetComparison[];
};

export type CompetitorScore = {
  name: string;
  score: number;
  source?: string;
  confidence_score?: number;
  geo_visibility?: number;
  aeo_score?: number;
  entity_strength?: number;
  rank?: number;
};

export type Suggestion = {
  priority: number;
  title: string;
  action: string;
  category?: "Technical" | "Content" | "Backlinks";
};

export type ScoreComponents = {
  score: number | null;
  components: Record<string, number>;
  penalties: Array<Record<string, unknown>>;
  bonuses: Array<Record<string, unknown>>;
};

export type GlobalScores = {
  seo: number;
  geo: number;
  aeo: number;
  overall?: number | null;
  seo_breakdown?: ScoreComponents | null;
  geo_breakdown?: ScoreComponents | null;
  aeo_breakdown?: ScoreComponents | null;
  scoring_version?: string;
};

export type TechnicalSignals = {
  performance?: {
    score?: number | null;
    lcp_ms?: number | null;
    cls?: number | null;
  };
  network?: {
    http_version?: string | null;
    supports_http2?: boolean | null;
    supports_http3?: boolean | null;
    supports_http3_inferred?: boolean | null;
  };
};

export type LockedAuditSection = {
  is_locked: boolean;
  capability_key?: string | null;
  required_plan?: string | null;
  required_plan_label?: string | null;
  detail?: string | null;
  lock_origin?: string | null;
};

export type AuditMetadata = {
  created_at: string;
  updated_at: string;
  plan: string;
  current_plan?: string | null;
  version: string;
  audit_target_type?: AuditTargetType;
  target_name?: string | null;
  target_url?: string | null;
  target_metadata?: Record<string, unknown>;
  service_status?: Record<string, string>;
  service_errors?: Record<string, string>;
  competitor_summary?: Record<string, unknown>;
  audit_outcome?: string;
  scores_available?: boolean;
  intent?: "informational" | "transactional" | "navigational" | null;
  query_type?: "informational" | "decision_making" | null;
  technical_signals?: TechnicalSignals;
  locked_sections?: Record<string, LockedAuditSection>;
};

export type ClaimVerification = {
  claim_id: string;
  claim_text: string;
  matched_truth_key: string;
  truth_value: string;
  similarity_score: number;
  hallucination: boolean;
  discrepancy_type?: string | null;
  severity: "none" | "low" | "medium" | "high" | "critical";
  field_path?: string | null;
  field_label?: string | null;
  certainty_score?: number | null;
  certainty_level?: "high" | "medium" | "low" | null;
  disposition?: "supported" | "flagged" | "omitted";
  evidence_refs?: EvidenceRef[];
};

export type EvidenceRef = {
  source_type: string;
  source_key: string;
  excerpt: string;
  retrieval_score: number;
};

export type FieldCertaintySummary = {
  field_path: string;
  label: string;
  total_claims: number;
  supported_claims: number;
  flagged_claims: number;
  omitted_claims: number;
  average_certainty: number;
  certainty_level: "high" | "medium" | "low";
};

export type HallucinationResult = {
  threshold: number;
  total_claims: number;
  flagged_claims: number;
  omitted_claims?: number;
  average_certainty?: number;
  claims: ClaimVerification[];
  high_risk_discrepancies: ClaimVerification[];
  field_summaries?: FieldCertaintySummary[];
};

export type AuditResult = {
  schema_version: string;
  target: AuditTarget;
  site: SiteInfo;
  seo: SeoBreakdown;
  geo: GeoBreakdown;
  aeo: AeoBreakdown;
  entities: string[];
  competitors: CompetitorScore[];
  suggestions: Suggestion[];
  scores: GlobalScores;
  metadata: AuditMetadata;
  hallucination?: HallucinationResult | null;
  geo_comparative?: GeoComparativePayload;
  aeo_site_stats?: AeoSiteStats;
};

const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isGeoCitationSource = (value: unknown): value is GeoCitationSource => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isString(payload.domain) &&
    isNumber(payload.citation_count) &&
    isNumber(payload.trust_score) &&
    (payload.owner === "my_site" || payload.owner === "competitor" || payload.owner === "other")
  );
};

const isGeoStrategicRecommendation = (value: unknown): value is GeoStrategicRecommendation => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return isString(payload.insight) && isString(payload.recommended_action);
};

const isGeoComparativePayload = (value: unknown): value is GeoComparativePayload => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    Array.isArray(payload.citation_sources) &&
    payload.citation_sources.every((item) => isGeoCitationSource(item)) &&
    Array.isArray(payload.strategic_recommendations) &&
    payload.strategic_recommendations.every((item) => isGeoStrategicRecommendation(item))
  );
};

const isStringRecord = (value: unknown): value is Record<string, string> => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  return Object.values(value as Record<string, unknown>).every((item) => isString(item));
};

const isUnknownRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

const isNullableNumber = (value: unknown): value is number | null =>
  value === null || isNumber(value);
const isNullableString = (value: unknown): value is string | null =>
  value === null || isString(value);

const isAuditTarget = (value: unknown): value is AuditTarget => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    (payload.type === "website" || payload.type === "brand") &&
    isNullableString(payload.name) &&
    isNullableString(payload.url) &&
    isUnknownRecord(payload.metadata)
  );
};

const isAnswerFailureReason = (value: unknown): value is AnswerFailureReason => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return isString(payload.reason) && isNumber(payload.count) && isNumber(payload.percentage);
};

const isSchemaHealth = (value: unknown): value is SchemaHealth => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isNumber(payload.avg_score) &&
    isNumber(payload.healthy_audits) &&
    isNumber(payload.issue_count) &&
    isNumber(payload.coverage_percent) &&
    typeof payload.coverage_by_type === "object" &&
    payload.coverage_by_type !== null &&
    !Array.isArray(payload.coverage_by_type)
  );
};

const isQueryCategoryMetric = (value: unknown): value is QueryCategoryMetric => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return isString(payload.query_type) && isNumber(payload.count) && isNumber(payload.percentage);
};

const isCompetitorSnippetComparison = (value: unknown): value is CompetitorSnippetComparison => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  const site = payload.site as Record<string, unknown> | undefined;
  const competitor = payload.competitor as Record<string, unknown> | null | undefined;

  const isEntry = (entry: Record<string, unknown> | undefined, allowNullDomain: boolean) =>
    !!entry &&
    (allowNullDomain ? isNullableString(entry.domain) : isString(entry.domain)) &&
    isNullableNumber(entry.answer_relevance) &&
    isNullableString(entry.answer_excerpt);

  return (
    isString(payload.query) &&
    (payload.winner === "site" ||
      payload.winner === "competitor" ||
      payload.winner === "tie" ||
      payload.winner === "no_data") &&
    isEntry(site, false) &&
    (competitor === null || isEntry(competitor, true))
  );
};

const isTrustTrendPoint = (value: unknown): value is TrustTrendPoint => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  const signalCoverage = payload.signal_coverage;
  return (
    isString(payload.date) &&
    isNullableNumber(payload.score) &&
    isNumber(payload.audit_count) &&
    (signalCoverage === undefined || isNullableNumber(signalCoverage))
  );
};

const isAeoSiteStats = (value: unknown): value is AeoSiteStats => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  const answerDominance = payload.answer_dominance as Record<string, unknown> | undefined;

  return !!(
    isNumber(payload.site_id) &&
    isNumber(payload.audit_count) &&
    answerDominance &&
    isNumber(answerDominance.site_primary_count) &&
    isNumber(answerDominance.competitor_primary_count) &&
    isNumber(answerDominance.unknown_count) &&
    isNumber(answerDominance.site_primary_share) &&
    isNumber(answerDominance.competitor_primary_share) &&
    isNumber(answerDominance.site_primary_share_total) &&
    isNumber(answerDominance.competitor_primary_share_total) &&
    isNumber(answerDominance.unknown_share_total) &&
    Array.isArray(payload.answer_failure_reasons) &&
    payload.answer_failure_reasons.every((item) => isAnswerFailureReason(item)) &&
    isSchemaHealth(payload.schema_health) &&
    Array.isArray(payload.query_category_breakdown) &&
    payload.query_category_breakdown.every((item) => isQueryCategoryMetric(item)) &&
    Array.isArray(payload.trustworthiness_trend) &&
    payload.trustworthiness_trend.every((item) => isTrustTrendPoint(item)) &&
    Array.isArray(payload.competitor_snippet_comparisons) &&
    payload.competitor_snippet_comparisons.every((item) => isCompetitorSnippetComparison(item))
  );
};

const isClaimVerification = (value: unknown): value is ClaimVerification => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isString(payload.claim_id) &&
    isString(payload.claim_text) &&
    isString(payload.matched_truth_key) &&
    isString(payload.truth_value) &&
    isNumber(payload.similarity_score) &&
    typeof payload.hallucination === "boolean" &&
    (payload.discrepancy_type === undefined || isNullableString(payload.discrepancy_type)) &&
    (payload.field_path === undefined || isNullableString(payload.field_path)) &&
    (payload.field_label === undefined || isNullableString(payload.field_label)) &&
    (payload.certainty_score === undefined || isNullableNumber(payload.certainty_score)) &&
    (payload.certainty_level === undefined ||
      payload.certainty_level === null ||
      payload.certainty_level === "high" ||
      payload.certainty_level === "medium" ||
      payload.certainty_level === "low") &&
    (payload.disposition === undefined ||
      payload.disposition === "supported" ||
      payload.disposition === "flagged" ||
      payload.disposition === "omitted") &&
    (payload.evidence_refs === undefined ||
      (Array.isArray(payload.evidence_refs) &&
        payload.evidence_refs.every((item) => isEvidenceRef(item)))) &&
    (payload.severity === "none" ||
      payload.severity === "low" ||
      payload.severity === "medium" ||
      payload.severity === "high" ||
      payload.severity === "critical")
  );
};

const isEvidenceRef = (value: unknown): value is EvidenceRef => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isString(payload.source_type) &&
    isString(payload.source_key) &&
    isString(payload.excerpt) &&
    isNumber(payload.retrieval_score)
  );
};

const isFieldCertaintySummary = (value: unknown): value is FieldCertaintySummary => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isString(payload.field_path) &&
    isString(payload.label) &&
    isNumber(payload.total_claims) &&
    isNumber(payload.supported_claims) &&
    isNumber(payload.flagged_claims) &&
    isNumber(payload.omitted_claims) &&
    isNumber(payload.average_certainty) &&
    (payload.certainty_level === "high" ||
      payload.certainty_level === "medium" ||
      payload.certainty_level === "low")
  );
};

const isHallucinationResult = (value: unknown): value is HallucinationResult => {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    isNumber(payload.threshold) &&
    isNumber(payload.total_claims) &&
    isNumber(payload.flagged_claims) &&
    (payload.omitted_claims === undefined || isNumber(payload.omitted_claims)) &&
    (payload.average_certainty === undefined || isNumber(payload.average_certainty)) &&
    Array.isArray(payload.claims) &&
    payload.claims.every((item) => isClaimVerification(item)) &&
    Array.isArray(payload.high_risk_discrepancies) &&
    payload.high_risk_discrepancies.every((item) => isClaimVerification(item)) &&
    (payload.field_summaries === undefined ||
      (Array.isArray(payload.field_summaries) &&
        payload.field_summaries.every((item) => isFieldCertaintySummary(item))))
  );
};

export const isAuditResult = (value: unknown): value is AuditResult => {
  if (!value || typeof value !== "object") {
    return false;
  }

  const payload = value as Record<string, unknown>;
  const target = payload.target as Record<string, unknown> | undefined;
  const site = payload.site as Record<string, unknown> | undefined;
  const seo = payload.seo as Record<string, unknown> | undefined;
  const geo = payload.geo as Record<string, unknown> | undefined;
  const aeo = payload.aeo as Record<string, unknown> | undefined;
  const scores = payload.scores as Record<string, unknown> | undefined;
  const metadata = payload.metadata as Record<string, unknown> | undefined;

  return !!(
    isString(payload.schema_version) &&
    target &&
    site &&
    seo &&
    geo &&
    aeo &&
    scores &&
    metadata &&
    isNullableString(site.url) &&
    isString(site.market) &&
    isString(site.language) &&
    isAuditTarget(target) &&
    isNumber(seo.onpage) &&
    isNullableNumber(seo.performance) &&
    isNumber(seo.indexing) &&
    isNullableNumber(geo.visibility_index) &&
    isNullableNumber(geo.citation_share) &&
    isNullableNumber(geo.brand_anchor) &&
    isNullableNumber(aeo.answerability_score) &&
    isNullableNumber(aeo.extractable_pages) &&
    Array.isArray(payload.entities) &&
    Array.isArray(payload.competitors) &&
    Array.isArray(payload.suggestions) &&
    isNumber(scores.seo) &&
    isNumber(scores.geo) &&
    isNumber(scores.aeo) &&
    (scores.overall === undefined || isNullableNumber(scores.overall)) &&
    isString(metadata.created_at) &&
    isString(metadata.updated_at) &&
    isString(metadata.plan) &&
    (metadata.current_plan === undefined || isNullableString(metadata.current_plan)) &&
    isString(metadata.version) &&
    (payload.geo_comparative === undefined || isGeoComparativePayload(payload.geo_comparative)) &&
    (payload.aeo_site_stats === undefined || isAeoSiteStats(payload.aeo_site_stats)) &&
    (payload.hallucination === undefined ||
      payload.hallucination === null ||
      isHallucinationResult(payload.hallucination)) &&
    (metadata.service_status === undefined || isStringRecord(metadata.service_status)) &&
    (metadata.service_errors === undefined || isStringRecord(metadata.service_errors)) &&
    (metadata.competitor_summary === undefined || isUnknownRecord(metadata.competitor_summary)) &&
    (metadata.audit_outcome === undefined || isString(metadata.audit_outcome)) &&
    (metadata.scores_available === undefined || typeof metadata.scores_available === "boolean") &&
    (metadata.intent === undefined ||
      metadata.intent === null ||
      metadata.intent === "informational" ||
      metadata.intent === "transactional" ||
      metadata.intent === "navigational") &&
    (metadata.query_type === undefined ||
      metadata.query_type === null ||
      metadata.query_type === "informational" ||
      metadata.query_type === "decision_making") &&
    (metadata.audit_target_type === undefined ||
      metadata.audit_target_type === "website" ||
      metadata.audit_target_type === "brand") &&
    (metadata.target_name === undefined || isNullableString(metadata.target_name)) &&
    (metadata.target_url === undefined || isNullableString(metadata.target_url)) &&
    (metadata.target_metadata === undefined || isUnknownRecord(metadata.target_metadata)) &&
    (metadata.technical_signals === undefined || isUnknownRecord(metadata.technical_signals))
  );
};
