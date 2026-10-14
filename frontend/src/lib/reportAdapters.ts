import type {
  TechnicalSignals,
  AuditResult,
  Suggestion,
  CompetitorScore,
  HallucinationResult,
  LockedAuditSection,
} from "@/types/auditResult";
import { getPenaltyFixGuidance, mapPenaltySection } from "@/lib/penaltyContext";

export type CanonicalAuditReport = {
  schema_version: string;
  url: string;
  target?: {
    type?: "website" | "brand";
    name?: string | null;
    url?: string | null;
    metadata?: Record<string, any>;
  };
  entity?: string;
  is_locked?: boolean;
  analysis: Record<string, any>;
  performance: Record<string, any>;
  network: Record<string, any>;
  warnings: string[];
  metadata: Record<string, any>;
  screenshot_base64?: string;
  screenshot_url?: string;
  site?: Record<string, any>;
  seo?: Record<string, any>;
  geo?: Record<string, any>;
  aeo?: Record<string, any>;
  entities?: unknown;
  competitors?: unknown;
  scores?: Record<string, any>;
  suggestions?:
    | string[]
    | Array<{
        title?: string;
        action?: string;
        priority?: number;
        category?: string;
        impact?: string;
      }>;
  /**
   * The canonical recommendation block (`_build_recommendations_block`).
   *
   * SIGV2-1193 carries this through normalization. It deliberately was not
   * carried before, which is what kept the Improve tabs' findings and the
   * Advisor's action plan disjoint, and therefore what let them report
   * different totals for the same audit. It is read only through
   * `getRecommendationItems`, as the ratings and grounding behind an Advisor
   * action, plus the all-or-nothing SIGV2-1096 fallback; it is never a row
   * source of its own, because that would reinstate the candidates the
   * Advisor's grounding gate dropped.
   */
  recommendations?: { items?: Array<Record<string, any>> };
  hallucination?: Record<string, any> | null;
  integrity_certificate?: {
    schema_version?: string;
    dual_track_grounding_enabled?: boolean;
    grounding_profile?: string | null;
    summary?: {
      total_claims?: number;
      track_a_total?: number;
      track_a_supported?: number;
      track_a_flagged?: number;
      track_a_omitted?: number;
      track_b_total?: number;
      track_b_supported?: number;
      track_b_flagged?: number;
      track_b_needs_manual_review?: number;
      track_b_omitted?: number;
    } | null;
    blocked_claim_buckets?: Array<{
      track?: string;
      category?: string;
      count?: number;
    }> | null;
    degraded?: boolean;
    degraded_reason?: string | null;
  } | null;
  entity_analysis?: Record<string, any>;
  aeo_signals?: Record<string, any>;
  geo_signals?: Record<string, any>;
  technical_signals?: TechnicalSignals;
  analysis_metadata?: {
    tools_used?: Array<{ name: string; task: string }>;
  };
  intelligence_summary?: string;
  detailed_seo_recommendations?: Array<{
    source: string;
    priority: "Critical" | "Warning" | "Optimization";
    title: string;
    description: string;
    implementation: string;
  }>;
  aeo_teaser?: string;
  executive_summary?: string;
  intelligence_dossier?: Array<{
    source_tool: "Qiko Signal Vision" | "Semantic Engine" | "Intent Classifier" | "Technical Core";
    priority_level: "Critical" | "Strategic" | "Optimization";
    finding_title: string;
    data_observation: string;
    generative_impact: string;
    implementation_logic: string;
    impact_on_overall_score: number;
  }>;
  aeo_citation_probability?: {
    score: number;
    primary_blockers: string[];
    citation_readiness: "Ready" | "Partial" | "Blocked";
  };
  geo_visibility_projection?: string;

  // Smart Tier (Neural Architect) specific fields
  // De-jargoned key (derives from ``strategic_roadmap``). ``neural_executive_summary``
  // is retained as an optional legacy alias so old persisted reports still read.
  strategic_summary?: string;
  /** @deprecated legacy persisted key — read-only fallback for old reports */
  neural_executive_summary?: string;
  debate_findings?: Array<{
    layer: "Neural Vision" | "Knowledge Graph" | "Generative Reasoning" | "Protocol Lab";
    severity: "Critical" | "Strategic" | "Evolutionary";
    neural_correlation: string;
    finding: string;
    llm_behavior_projection: string;
    architect_fix: string;
    priority_weight: number;
  }>;
  generative_authority_metrics?: {
    entity_clarity_score: number;
    contextual_trust_score: number;
    citable_nugget_density: "Low" | "Medium" | "High";
    primary_inference_blockers: string[];
  };
  competitive_positioning?: string;

  // Debate orchestration metadata (deep tier with debate enabled)
  debate?: {
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
    transcript?: Array<{
      role: string;
      semantic_role?: "generator" | "critic" | "judge" | "consolidator" | null;
      provider: string;
      model: string;
      output_summary: string;
      token_usage: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
      latency_ms: number;
      routing_mode?: string | null;
      route_reason?: string | null;
      requested_tier?: string | null;
      execution_tier?: string | null;
      layer?: number | null;
    }>;
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
  } | null;

  // Guest audit structured findings (populated by guest-audit endpoint)
  structured_findings?: {
    seo_findings?: Array<Record<string, any>>;
    geo_findings?: { preview?: Array<Record<string, any>>; total_count?: number; locked?: boolean };
    aeo_findings?: { preview?: Array<Record<string, any>>; total_count?: number; locked?: boolean };
    entity_summary?: { count?: number; top_names?: string[]; locked?: boolean };
  };
};

export type DetailedRecommendation = {
  title: string;
  description: string;
  category: string;
  impact: "Critical" | "Strategic" | "Optimization";
  engines: Array<"SEO" | "GEO" | "AEO">;
  /** Confidence level of the recommendation (high/medium/low). */
  confidence?: "high" | "medium" | "low";
  /** The audited page URL this finding relates to. */
  page?: string;
  /** Technical area / page section (e.g. "HTML Head · <title>"). */
  section?: string;
  /** Raw numeric penalty (negative) or bonus (positive) value. */
  impactValue?: number;
  /**
   * Deterministic problem code (see `problem_codes.py`), present when this
   * recommendation names a failing deterministic check. It is the entry's
   * stable identity across sources and audits; titles are LLM-written and
   * drift. `null`/`undefined` for entries no deterministic check produced.
   */
  problemCode?: string | null;
};

/**
 * Which of the audit's two fix channels a consolidated row came from
 * (SIGV2-1193). Both are shown: SIGV2-1175 settled that the customer should
 * be able to tell them apart, and folding two lists into one does not
 * withdraw that.
 *
 * - `"audit_finding"`: the audit's own findings, score-breakdown penalties,
 *   the intelligence dossier, debate findings, the detailed SEO roadmap.
 * - `"action_plan"`: the Advisor's ranked action plan
 *   (`metadata.advisor`, built from the canonical `recommendations.items[]`).
 *
 * A row raised by both carries both, in the order it was sourced.
 */
export type FixSource = "audit_finding" | "action_plan";

/**
 * One row of the single consolidated fix list (SIGV2-1193).
 *
 * It is a `DetailedRecommendation` plus the fields the action plan needs, so
 * every surface that used to read one of the two lists reads this one instead
 * and no two surfaces can disagree about how many fixes exist. The extra
 * fields are all resolved once, here, rather than re-derived per surface:
 *
 * - `impactLevel` / `effortLevel` are the SIGV2-1211 qualitative ladder, and
 *   unmeasured is a real state that must render as "not rated" rather than
 *   being defaulted to a band.
 * - `impact` (inherited) stays the pre-existing Critical/Strategic/
 *   Optimization severity used by the report rows and by the ordering. It is
 *   a classification that is always populated, not a claim that an impact was
 *   measured; `impactLevel` is the one that can say "nothing measured this".
 * - no numeric impact is exposed for rendering: `impactValue` is a measured
 *   score deduction, read to pick a band and to order, never printed
 *   (SIGV2-1218, SIGV2-1211).
 */
export type ConsolidatedFix = DetailedRecommendation & {
  /**
   * Stable per-row id. Advisor-sourced rows keep `advisor-action-<rank>` and
   * canonical-item rows keep `rec-<n>`, the ids the action plan already used,
   * so a row's identity in the DOM does not change under consolidation.
   */
  id: string;
  /** 1-based position in the one ordered list. */
  rank: number;
  /** Which channel(s) raised this fix. Never empty. */
  sources: FixSource[];
  /** Qualitative impact band, or explicitly unmeasured. */
  impactLevel: ResolvedLevel;
  /** Qualitative effort band, or explicitly unmeasured. */
  effortLevel: ResolvedLevel;
  /** Pillars a numeric expected-score delta claims this fix raises. */
  pillars: ScorePillar[];
  /** Grounding references (`grounded_by_findings` + `derived_from`). */
  groundedBy: string[];
  /**
   * The canonical action text the dismiss contract hashes server-side
   * (`learnings_service.compute_action_fingerprint`), when this row has one.
   * `null` for rows that exist only as an audit finding: those fall back to
   * the title, which is what the server would then store as the label.
   */
  actionText: string | null;
};

export type AuditScoreGroup = {
  label: string;
  score: number;
};

export type NormalizedEntity = {
  name: string;
  type: string;
  relevance: number | null;
};

type RecordValue = Record<string, any>;

const toObject = (value: unknown): Record<string, any> =>
  typeof value === "object" && value !== null ? (value as Record<string, any>) : {};

const isLegacySchemaVersion = (schemaVersion: string): boolean =>
  schemaVersion === "legacy" || schemaVersion === "1.0";

const isLegacyNormalizedReport = (report: CanonicalAuditReport): boolean =>
  isLegacySchemaVersion(report.schema_version);

const mergeObjectsWithFallback = (...values: unknown[]): RecordValue =>
  values.reduceRight<RecordValue>((acc, value) => ({ ...acc, ...toObject(value) }), {});

const compactObject = (value: RecordValue): RecordValue =>
  Object.fromEntries(
    Object.entries(value).filter(
      ([, entry]) => entry !== undefined && entry !== null && entry !== ""
    )
  );

const normalizeGridItem = (
  raw: Record<string, any>
): NonNullable<CanonicalAuditReport["debate_findings"]>[number] => {
  const pw = typeof raw.priority_weight === "number" ? raw.priority_weight : 0;
  const severity: "Critical" | "Strategic" | "Evolutionary" =
    typeof raw.severity === "string"
      ? (raw.severity as "Critical" | "Strategic" | "Evolutionary")
      : pw >= 0.8
        ? "Critical"
        : pw >= 0.5
          ? "Strategic"
          : "Evolutionary";

  const layer =
    typeof raw.layer === "string"
      ? (raw.layer as "Neural Vision" | "Knowledge Graph" | "Generative Reasoning" | "Protocol Lab")
      : typeof raw.agent_correlation === "string"
        ? inferLayerFromCorrelation(raw.agent_correlation)
        : "Neural Vision";

  return {
    finding: raw.finding ?? raw.discovery ?? "",
    neural_correlation: raw.neural_correlation ?? raw.neural_logic ?? "",
    llm_behavior_projection: raw.llm_behavior_projection ?? raw.agent_correlation ?? "",
    architect_fix: raw.architect_fix ?? "",
    priority_weight: pw,
    severity,
    layer,
  };
};

const inferLayerFromCorrelation = (
  correlation: string
): "Neural Vision" | "Knowledge Graph" | "Generative Reasoning" | "Protocol Lab" => {
  const lower = correlation.toLowerCase();
  if (lower.includes("knowledge") || lower.includes("semantic")) return "Knowledge Graph";
  if (lower.includes("intent") || lower.includes("predictive") || lower.includes("generative"))
    return "Generative Reasoning";
  if (lower.includes("technical") || lower.includes("protocol") || lower.includes("lab"))
    return "Protocol Lab";
  return "Neural Vision";
};

const normalizeGrid = (grid: unknown): CanonicalAuditReport["debate_findings"] => {
  if (!Array.isArray(grid) || grid.length === 0) return undefined;
  return grid.filter((item) => typeof item === "object" && item !== null).map(normalizeGridItem);
};

const hasOwnKey = (value: unknown, key: string): boolean =>
  typeof value === "object" && value !== null && Object.prototype.hasOwnProperty.call(value, key);

const coerceMetricScore = (
  value: unknown,
  { ratio = false }: { ratio?: boolean } = {}
): number | undefined => {
  const candidate =
    typeof value === "number"
      ? value
      : typeof value === "string" && value.trim()
        ? Number(value)
        : NaN;

  if (!Number.isFinite(candidate)) {
    return undefined;
  }

  const normalized = ratio ? candidate * 100 : candidate;
  return Math.max(0, Math.min(100, normalized));
};

const firstDefined = <T>(...values: T[]): T | undefined => {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }

  return undefined;
};

const toStringArray = (value: unknown): string[] =>
  Array.isArray(value)
    ? value.map((entry) => (typeof entry === "string" ? entry.trim() : "")).filter(Boolean)
    : [];

const toDetailedRecommendationArray = (value: unknown): any[] =>
  Array.isArray(value)
    ? value
        .map((entry) => {
          if (typeof entry === "string") return { title: entry.trim(), action: "" };
          if (typeof entry === "object" && entry !== null) {
            const rec = entry as any;
            return {
              title: (rec.title || rec.action || "").trim(),
              action: (rec.action || rec.description || "").trim(),
              priority: rec.priority,
              impact: rec.impact,
              category: rec.category,
              problem_code: rec.problem_code,
            };
          }
          return null;
        })
        .filter(Boolean)
    : [];

export const toScoreValue = (value: unknown): number => {
  if (typeof value === "number" && !Number.isNaN(value)) return value;
  if (typeof value === "string") {
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  return 0;
};

const normalizeLegacyReport = (report: Record<string, any>): CanonicalAuditReport => ({
  schema_version: "legacy",
  url: report.url ?? report.analysis?.url ?? "",
  is_locked: Boolean(report.is_locked),
  analysis: report.analysis ?? report.ai_analysis ?? {},
  performance: report.performance ?? report.performance_metrics ?? {},
  network: report.network ?? report.network_analysis ?? {},
  warnings: report.warnings ?? report.metadata?.warnings ?? [],
  metadata: report.metadata ?? {},
  screenshot_base64: report.screenshot_base64,
  screenshot_url: report.screenshot_url,
  hallucination: toObject(report.hallucination),
  integrity_certificate: toObject(report.integrity_certificate),
});

const normalizeCanonicalReport = (report: Record<string, any>): CanonicalAuditReport => {
  const site = toObject(report.site);
  const seo = toObject(report.seo);
  const geo = toObject(report.geo);
  const aeo = toObject(report.aeo);
  const scores = toObject(report.scores);
  const metadata = toObject(report.metadata);
  const analysis = toObject(report.analysis ?? report.ai_analysis);

  const canonicalSuggestions = toDetailedRecommendationArray(report.suggestions);
  const scopedSuggestions = [
    ...toDetailedRecommendationArray(seo.suggestions ?? seo.recommendations),
    ...toDetailedRecommendationArray(geo.suggestions ?? geo.recommendations),
    ...toDetailedRecommendationArray(aeo.suggestions ?? aeo.recommendations),
  ];

  return {
    schema_version: String(report.schema_version),
    url: site.url ?? report.target?.url ?? report.url ?? report.analysis?.url ?? "",
    target: report.target ?? {
      type:
        metadata.audit_target_type === "brand" || metadata.audit_target_type === "website"
          ? metadata.audit_target_type
          : "website",
      name:
        typeof metadata.target_name === "string"
          ? metadata.target_name
          : (site.url ?? report.url ?? null),
      url:
        typeof metadata.target_url === "string"
          ? metadata.target_url
          : (site.url ?? report.url ?? null),
      metadata:
        typeof metadata.target_metadata === "object" && metadata.target_metadata !== null
          ? metadata.target_metadata
          : {},
    },
    entity: report.entity ?? report.analysis?.entity,
    is_locked: typeof report.is_locked === "boolean" ? report.is_locked : undefined,
    analysis,
    performance: toObject(report.performance ?? report.performance_metrics ?? site.performance),
    network: toObject(report.network ?? report.network_analysis ?? site.network),
    warnings: toStringArray(report.warnings ?? metadata.warnings),
    metadata,
    screenshot_base64: report.screenshot_base64,
    screenshot_url: report.screenshot_url,
    site,
    seo,
    geo,
    aeo,
    entities: report.entities,
    competitors: report.competitors,
    scores,
    suggestions: canonicalSuggestions.length > 0 ? canonicalSuggestions : scopedSuggestions,
    // SIGV2-1193: carried on purpose. See the field's note on
    // `CanonicalAuditReport` - without it the normalized surfaces could see
    // the Advisor's actions but not the ratings and grounding behind them, so
    // one fix read "rated" on the action plan and "not rated" on the Improve
    // tab. `narrative.recommendations` is the legacy location the raw path
    // also reads.
    recommendations:
      report.recommendations ?? (report as Record<string, any>).narrative?.recommendations,
    hallucination: Array.isArray(toObject(report.hallucination).claims)
      ? toObject(report.hallucination)
      : (report.hallucination?.unsupported_sentences?.length ?? 0) > 0
        ? toObject(report.hallucination)
        : toObject(report.metadata?.hallucination ?? report.hallucination),
    integrity_certificate: toObject(report.integrity_certificate),
    structured_findings: report.structured_findings,
    entity_analysis:
      report.entity_analysis ?? metadata.entity_analysis ?? report.analysis?.entity_analysis,
    aeo_signals: report.aeo_signals ?? metadata.aeo_signals ?? report.analysis?.aeo_signals,
    geo_signals: report.geo_signals ?? metadata.geo_signals ?? report.analysis?.geo_signals,
    technical_signals:
      report.technical_signals ?? metadata.technical_signals ?? report.analysis?.technical_signals,
    analysis_metadata: report.analysis_metadata,
    intelligence_summary: report.intelligence_summary,
    detailed_seo_recommendations: report.detailed_seo_recommendations,
    aeo_teaser: report.aeo_teaser,
    executive_summary:
      report.analysis?.executive_dossier ??
      report.analysis?.executive_summary ??
      metadata.executive_summary ??
      report.executive_summary,
    intelligence_dossier:
      report.analysis?.findings ??
      report.analysis?.intelligence_dossier ??
      metadata.intelligence_dossier ??
      report.intelligence_dossier,
    aeo_citation_probability:
      report.analysis?.aeo_citation_probability ??
      metadata.aeo_citation_probability ??
      report.aeo_citation_probability,
    geo_visibility_projection:
      report.analysis?.geo_visibility_projection ?? report.geo_visibility_projection,
    strategic_summary:
      report.analysis?.strategic_roadmap ??
      report.analysis?.strategic_summary ??
      report.analysis?.neural_executive_summary ??
      metadata.strategic_summary ??
      metadata.neural_executive_summary ??
      report.strategic_summary ??
      report.neural_executive_summary,
    debate_findings: normalizeGrid(
      report.analysis?.debate_findings ??
        report.analysis?.neural_intelligence_grid ??
        report.analysis?.strategic_intelligence_grid ??
        metadata.debate_findings ??
        metadata.strategic_intelligence_grid ??
        report.debate_findings ??
        report.strategic_intelligence_grid ??
        (report as Record<string, any>).narrative?.debate_findings ??
        (report as Record<string, any>).narrative?.strategic_intelligence_grid
    ),
    generative_authority_metrics:
      report.analysis?.generative_authority_metrics ?? report.generative_authority_metrics,
    competitive_positioning:
      report.analysis?.competitive_positioning ??
      report.analysis?.market_dominance_blueprint ??
      metadata.competitive_positioning ??
      metadata.market_dominance_blueprint ??
      report.competitive_positioning ??
      report.market_dominance_blueprint,
    debate: report.debate ?? report.analysis?._debate ?? report.analysis?.debate ?? null,
  };
};

const normalizeV1Report = (report: Record<string, any>): CanonicalAuditReport => ({
  schema_version: report.schema_version ?? "1.0",
  url: report.url ?? "",
  is_locked: Boolean(report.is_locked),
  analysis: report.analysis ?? {},
  performance: report.performance ?? {},
  network: report.network ?? {},
  warnings: report.warnings ?? report.metadata?.warnings ?? [],
  metadata: report.metadata ?? {},
  screenshot_base64: report.screenshot_base64,
  screenshot_url: report.screenshot_url,
  hallucination: toObject(report.hallucination),
  integrity_certificate: toObject(report.integrity_certificate),
});

export const hasCanonicalFields = (report: Record<string, any>): boolean =>
  ["site", "seo", "geo", "aeo", "entities", "competitors", "scores"].some((key) => key in report);

export const isCanonicalAuditReportPayload = (report: Record<string, any>): boolean =>
  hasCanonicalFields(report) &&
  typeof report.schema_version === "string" &&
  report.schema_version !== "legacy" &&
  report.schema_version !== "1.0";

export const normalizeAuditReport = (report: Record<string, any>): CanonicalAuditReport => {
  if (hasCanonicalFields(report)) {
    if (!isCanonicalAuditReportPayload(report)) {
      throw new Error("Canonical audit payload is missing a versioned schema_version.");
    }
    return normalizeCanonicalReport(report);
  }

  const schemaVersion =
    typeof report.schema_version === "string" ? report.schema_version : undefined;

  if (!schemaVersion) {
    return normalizeLegacyReport(report);
  }

  switch (schemaVersion) {
    case "1.0":
      return normalizeV1Report(report);
    default:
      return normalizeLegacyReport(report);
  }
};

export const getAuditScoreGroups = (report: CanonicalAuditReport): AuditScoreGroup[] => {
  const scores = toObject(report.scores);
  const analysis = report.analysis ?? {};
  const isLegacy = isLegacyNormalizedReport(report);

  if (
    scores.citability !== undefined ||
    scores.entity_matching !== undefined ||
    scores.trust_signals !== undefined ||
    scores.technical_seo !== undefined
  ) {
    return [
      { label: "Citability", score: toScoreValue(scores.citability) },
      { label: "Entity Match", score: toScoreValue(scores.entity_matching) },
      { label: "Trust Signals", score: toScoreValue(scores.trust_signals) },
      { label: "Technical SEO", score: toScoreValue(scores.technical_seo) },
    ];
  }

  if (
    isLegacy &&
    (analysis?.citability_score !== undefined ||
      analysis?.entity_matching_score !== undefined ||
      analysis?.trust_signals_score !== undefined ||
      analysis?.technical_seo_score !== undefined)
  ) {
    return [
      { label: "Citability", score: toScoreValue(analysis?.citability_score) },
      { label: "Entity Match", score: toScoreValue(analysis?.entity_matching_score) },
      { label: "Trust Signals", score: toScoreValue(analysis?.trust_signals_score) },
      { label: "Technical SEO", score: toScoreValue(analysis?.technical_seo_score) },
    ];
  }

  if (
    scores.seo !== undefined ||
    scores.geo !== undefined ||
    scores.aeo !== undefined ||
    (isLegacy && (analysis?.seo_score || analysis?.geo_score || analysis?.aeo_score))
  ) {
    return [
      {
        label: "SEO Score",
        score: toScoreValue(
          scores.seo ?? (isLegacy ? (analysis?.seo_score?.score ?? analysis?.seo_score) : undefined)
        ),
      },
      {
        label: "AI Visibility Score",
        score: toScoreValue(
          scores.geo ?? (isLegacy ? (analysis?.geo_score?.score ?? analysis?.geo_score) : undefined)
        ),
      },
      {
        label: "AI Answers Index",
        score: toScoreValue(
          scores.aeo ?? (isLegacy ? (analysis?.aeo_score?.score ?? analysis?.aeo_score) : undefined)
        ),
      },
    ];
  }

  return [];
};

export const getSeoTabData = (report: CanonicalAuditReport) => {
  const metadata = toObject(report.metadata);
  const seo = toObject(report.seo);
  const isLegacy = isLegacyNormalizedReport(report);

  if (!isLegacy) {
    const seoAuditsCandidate = seo.audits ?? seo.seo_audits;
    const seoAudits: any[] = Array.isArray(seoAuditsCandidate) ? seoAuditsCandidate : [];

    return {
      seo,
      metadata,
      performance: compactObject({
        performance_score: firstDefined(
          seo.performance,
          report.technical_signals?.performance?.score
        ),
      }),
      seoAudits,
      structuredDataDetected:
        typeof seo.structured_data_detected === "boolean"
          ? seo.structured_data_detected
          : undefined,
      seoStatus: typeof seo.status === "string" ? seo.status : undefined,
      largestContentfulPaint: firstDefined(
        seo.core_web_vitals?.largest_contentful_paint,
        report.technical_signals?.performance?.lcp_ms
      ),
      cumulativeLayoutShift: firstDefined(
        seo.core_web_vitals?.cumulative_layout_shift,
        report.technical_signals?.performance?.cls
      ),
    };
  }

  const legacyPerformance = mergeObjectsWithFallback(
    report.performance,
    report.site?.performance,
    report.metadata?.performance,
    report.analysis?.performance,
    report.analysis?.performance_metrics
  );

  const seoAuditsCandidate =
    seo.audits ?? seo.seo_audits ?? legacyPerformance.seo_audits ?? report.analysis?.seo_audits;

  const seoAudits: any[] = Array.isArray(seoAuditsCandidate) ? seoAuditsCandidate : [];

  return {
    seo,
    metadata,
    performance: {
      ...legacyPerformance,
      performance_score: firstDefined(
        seo.performance,
        legacyPerformance.performance_score,
        report.scores?.seo_breakdown?.components?.core_web_vitals
      ),
      status: firstDefined(legacyPerformance.status),
    },
    seoAudits,
    structuredDataDetected: firstDefined(
      seo.structured_data_detected,
      legacyPerformance.structured_data_detected,
      report.analysis?.structured_data_detected,
      metadata.structured_data_detected
    ) as boolean | undefined,
    seoStatus: firstDefined(
      seo.status,
      legacyPerformance.seo_status,
      report.analysis?.seo_status,
      metadata.seo_status
    ) as string | undefined,
    largestContentfulPaint: firstDefined(
      seo.core_web_vitals?.largest_contentful_paint,
      report.technical_signals?.performance?.lcp_ms,
      legacyPerformance.largest_contentful_paint,
      report.analysis?.largest_contentful_paint
    ),
    cumulativeLayoutShift: firstDefined(
      seo.core_web_vitals?.cumulative_layout_shift,
      report.technical_signals?.performance?.cls,
      legacyPerformance.cumulative_layout_shift,
      report.analysis?.cumulative_layout_shift
    ),
  };
};

export const getAeoTabData = (report: CanonicalAuditReport) => {
  const metadata = toObject(report.metadata);
  const aeo = toObject(report.aeo);
  const analysis = toObject(report.analysis);
  const isLegacy = isLegacyNormalizedReport(report);

  if (!isLegacy) {
    return {
      aeo,
      metadata,
      summary: typeof aeo.summary === "string" && aeo.summary.trim() ? aeo.summary : undefined,
      entityClarity: firstDefined(
        report.entity_analysis?.entity_clarity_score,
        aeo.semantic_entity_density,
        aeo.entity_clarity
      ),
      scoreDetails: compactObject(
        mergeObjectsWithFallback(report.aeo_signals, {
          answerability_score: coerceMetricScore(aeo.answerability_score),
          voice_readiness_score: coerceMetricScore(aeo.snippet_formatting),
          schema_completeness: coerceMetricScore(
            firstDefined(
              aeo.schema_coverage?.coverage_percent,
              aeo.schema_health?.coverage_percent,
              aeo.schema_health?.score
            )
          ),
          content_freshness_score: coerceMetricScore(aeo.information_gain),
        })
      ),
    };
  }

  const legacyAeoScore = toObject(analysis.aeo_score);
  const schemaHealth = toObject(aeo.schema_health);
  const schemaCoverage = toObject(aeo.schema_coverage);

  const aeoSignals = compactObject(
    mergeObjectsWithFallback(
      report.aeo_signals,
      metadata.aeo_signals,
      analysis.aeo_signals,
      aeo.signals,
      aeo.details,
      legacyAeoScore,
      {
        answerability_score: coerceMetricScore(
          firstDefined(
            aeo.answerability_score,
            aeo.answer_relevance_score,
            legacyAeoScore.answerability_score,
            legacyAeoScore.score
          )
        ),
        voice_readiness_score: coerceMetricScore(
          firstDefined(aeo.voice_readiness_score, aeo.snippet_formatting)
        ),
        schema_completeness: coerceMetricScore(
          firstDefined(
            aeo.schema_completeness,
            aeo.llm_schema_readiness,
            schemaHealth.score,
            schemaCoverage.coverage_percent
          )
        ),
        content_freshness_score: coerceMetricScore(
          firstDefined(aeo.content_freshness_score, aeo.information_gain)
        ),
      }
    )
  );

  return {
    aeo,
    metadata,
    summary: firstDefined(
      aeo.summary,
      metadata.aeo_summary,
      legacyAeoScore.summary,
      analysis.aeo_summary
    ) as string | undefined,
    entityClarity: firstDefined(
      aeo.semantic_entity_density,
      report.entity_analysis?.entity_clarity_score,
      analysis.entity_analysis?.entity_clarity_score,
      aeo.entity_clarity,
      metadata.entity_clarity,
      legacyAeoScore.entity_clarity,
      analysis.entity_clarity
    ),
    scoreDetails: aeoSignals,
  };
};

export const getGeoTabData = (report: CanonicalAuditReport) => {
  const metadata = toObject(report.metadata);
  const geo = toObject(report.geo);
  const analysis = toObject(report.analysis);
  const isLegacy = isLegacyNormalizedReport(report);

  if (!isLegacy) {
    return {
      geo,
      metadata,
      summary: typeof geo.summary === "string" && geo.summary.trim() ? geo.summary : undefined,
      citabilityScore: firstDefined(
        geo.citation_share,
        geo.citability_score,
        report.geo_signals?.citation_consistency_score
      ),
      entityMatchingScore: firstDefined(geo.brand_anchor, geo.entity_matching_score),
      trustSignalsScore: firstDefined(
        geo.brand_citation,
        geo.trust_signals_score,
        report.entity_analysis?.brand_trust_score,
        report.geo_signals?.local_authority_score
      ),
      technicalSeoScore: firstDefined(
        geo.advanced_local_schema,
        geo.spatial_content,
        geo.technical_seo_score
      ),
      scoreDetails: compactObject(
        mergeObjectsWithFallback(report.geo_signals, {
          citation_consistency_score: coerceMetricScore(
            firstDefined(
              geo.citation_consistency_score,
              geo.citation_share,
              geo.napw_completeness,
              geo.citability_score
            )
          ),
          local_authority_score: coerceMetricScore(
            firstDefined(
              geo.local_authority_score,
              geo.brand_citation,
              geo.brand_anchor,
              report.entity_analysis?.brand_trust_score
            )
          ),
          relevance_score: coerceMetricScore(
            firstDefined(geo.relevance_score, geo.spatial_content, geo.entity_matching_score)
          ),
        })
      ),
    };
  }

  const entityAnalysis = toObject(
    report.entity_analysis ?? metadata.entity_analysis ?? analysis.entity_analysis
  );
  const geoSignals = compactObject(
    mergeObjectsWithFallback(
      report.geo_signals,
      metadata.geo_signals,
      analysis.geo_signals,
      geo.signals,
      geo.details,
      {
        citation_consistency_score: coerceMetricScore(
          firstDefined(
            geo.citation_consistency_score,
            geo.citation_share,
            geo.napw_completeness,
            geo.citability_score
          )
        ),
        local_authority_score: coerceMetricScore(
          firstDefined(
            geo.local_authority_score,
            geo.brand_citation,
            geo.brand_anchor,
            entityAnalysis.brand_trust_score
          )
        ),
        relevance_score: coerceMetricScore(
          firstDefined(
            geo.relevance_score,
            geo.spatial_content,
            geo.brand_anchor,
            geo.entity_matching_score
          )
        ),
      }
    )
  );

  return {
    geo,
    metadata,
    summary: firstDefined(
      geo.summary,
      metadata.geo_summary,
      analysis.geo_score?.summary,
      analysis.geo_summary
    ) as string | undefined,
    citabilityScore: firstDefined(
      geo.citation_share,
      geo.napw_completeness,
      report.geo_signals?.citation_consistency_score,
      analysis.geo_signals?.citation_consistency_score,
      geo.citability_score,
      analysis.citability_score
    ),
    entityMatchingScore: firstDefined(
      geo.brand_anchor,
      geo.entity_matching_score,
      analysis.entity_matching_score
    ),
    trustSignalsScore: firstDefined(
      geo.brand_citation,
      report.entity_analysis?.brand_trust_score,
      analysis.entity_analysis?.brand_trust_score,
      geo.trust_signals_score,
      analysis.trust_signals_score
    ),
    technicalSeoScore: firstDefined(
      geo.advanced_local_schema,
      geo.spatial_content,
      geo.technical_seo_score,
      analysis.technical_seo_score
    ),
    scoreDetails: geoSignals,
  };
};

export const getTechnicalTabData = (report: CanonicalAuditReport) => {
  const metadata = toObject(report.metadata);
  const analysis = toObject(report.analysis);
  const seo = toObject(report.seo);
  const seoComponents = toObject(toObject(report.scores?.seo_breakdown).components);
  const perfSignal = toObject(report.technical_signals?.performance);
  const netSignal = toObject(report.technical_signals?.network);
  const isLegacy = isLegacyNormalizedReport(report);

  if (!isLegacy) {
    return {
      performance: compactObject({
        performance_score: firstDefined(perfSignal.score, seo.performance),
        lcp_ms: firstDefined(perfSignal.lcp_ms, seo.core_web_vitals?.largest_contentful_paint),
        cls: firstDefined(perfSignal.cls, seo.core_web_vitals?.cumulative_layout_shift),
      }),
      network: compactObject({
        http_version: netSignal.http_version,
        supports_http2: netSignal.supports_http2,
        supports_http3: netSignal.supports_http3,
        supports_http3_inferred: netSignal.supports_http3_inferred,
      }),
      technicalSignals: report.technical_signals,
      metadata,
    };
  }

  const basePerformance = mergeObjectsWithFallback(
    report.performance,
    report.site?.performance,
    metadata.performance,
    analysis.performance,
    analysis.performance_metrics
  );

  const baseNetwork = mergeObjectsWithFallback(
    report.network,
    report.site?.network,
    metadata.network,
    analysis.network,
    analysis.network_analysis
  );

  return {
    performance: {
      ...basePerformance,
      performance_score: firstDefined(
        perfSignal.score,
        seo.performance,
        basePerformance.performance_score,
        basePerformance.score
      ),
      lcp_ms: firstDefined(
        perfSignal.lcp_ms,
        seo.core_web_vitals,
        seoComponents.core_web_vitals,
        basePerformance.lcp_ms,
        basePerformance.largest_contentful_paint
      ),
      cls: firstDefined(
        perfSignal.cls,
        basePerformance.cls,
        basePerformance.cumulative_layout_shift
      ),
    },
    network: {
      ...baseNetwork,
      http_version: firstDefined(netSignal.http_version, baseNetwork.http_version),
      supports_http2: firstDefined(netSignal.supports_http2, baseNetwork.supports_http2),
      supports_http3: firstDefined(netSignal.supports_http3, baseNetwork.supports_http3),
      supports_http3_inferred: firstDefined(
        netSignal.supports_http3_inferred,
        baseNetwork.supports_http3_inferred
      ),
    },
    technicalSignals: report.technical_signals,
    metadata,
  };
};

export const getAuditPrimaryScore = (
  report: CanonicalAuditReport,
  key: "seo" | "geo" | "aeo"
): number => {
  const scores = toObject(report.scores);
  const analysis = report.analysis ?? {};
  const section = toObject((report as Record<string, any>)[key]);
  const isLegacy = isLegacyNormalizedReport(report);

  const sectionScoreKey =
    key === "seo" ? "onpage" : key === "geo" ? "visibility_index" : "answerability_score";
  const val =
    scores[key] ??
    section.score ??
    section[sectionScoreKey] ??
    (isLegacy ? (analysis?.[`${key}_score`]?.score ?? analysis?.[`${key}_score`]) : undefined);
  if (val !== undefined && val !== null) return toScoreValue(val);

  if (!isLegacy) {
    return 0;
  }

  const metadata = toObject(report.metadata);
  const competitorSummary = toObject(metadata.competitor_summary);
  const benchmark = toObject(competitorSummary.benchmark);
  const rows = Array.isArray(benchmark.rows) ? benchmark.rows : [];

  const targetRow = rows.find((r: any) => r.is_target === true);
  if (targetRow) {
    if (key === "geo" && targetRow.geo_visibility !== undefined)
      return toScoreValue(targetRow.geo_visibility);
    if (key === "aeo" && targetRow.aeo_score !== undefined)
      return toScoreValue(targetRow.aeo_score);
    if (key === "seo" && targetRow.overall_score !== undefined)
      return toScoreValue(targetRow.overall_score); // Fallback for SEO
  }

  return 0;
};

export const getAuditOverallScore = (report: CanonicalAuditReport): number | null => {
  const scores = toObject(report.scores);
  if (scores.overall !== undefined && scores.overall !== null) {
    return toScoreValue(scores.overall);
  }
  return null;
};

/**
 * Customer-facing AIO ("AI Optimization") roll-up view. AIO is a derived,
 * additive presentation of the existing AEO + GEO outputs — the internal
 * engine (SEO/AEO/GEO) is unchanged. See signal plan Phase 2.
 */
export type AioView = {
  aio_score: number | null;
  components: { aeo: number | null; geo: number | null };
  summary?: string | null;
  scope: string;
};

/** A headline pillar shown on the customer-facing overview (SEO + AIO). */
export type Pillar = {
  key: "seo" | "aio";
  label: string;
  score: number | null;
  scopeLabel: string;
  color: string;
  target?: number | null;
};

const AIO_DEFAULT_SCOPE = "website_and_brand";

/** Brand palette hex values (mirrors the `brand.*` design tokens). */
const PILLAR_COLORS = {
  seo: "#60A5FA", // brand.seo
  aio: "#2DD4BF", // AIO accent (teal, brand.aeo token reused)
} as const;

const toNullableScore = (value: unknown): number | null => {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
};

/** Reads an engine score (seo/geo/aeo) as a nullable number, mirroring
 * `getAuditPrimaryScore` resolution order but returning null when absent. */
const readNullablePrimaryScore = (
  report: CanonicalAuditReport,
  key: "seo" | "geo" | "aeo"
): number | null => {
  const scores = toObject(report.scores);
  const analysis = report.analysis ?? {};
  const section = toObject((report as Record<string, unknown>)[key]);
  const isLegacy = isLegacyNormalizedReport(report);
  const sectionScoreKey =
    key === "seo" ? "onpage" : key === "geo" ? "visibility_index" : "answerability_score";
  const raw =
    scores[key] ??
    section.score ??
    section[sectionScoreKey] ??
    (isLegacy ? (analysis?.[`${key}_score`]?.score ?? analysis?.[`${key}_score`]) : undefined);
  return toNullableScore(raw);
};

/**
 * Returns the AIO roll-up view. Prefers the backend-augmented
 * `report.metadata.aio` (Task 2.2); falls back to deriving from the report's
 * AEO/GEO scores so it still works on audits created before 2.2.
 * AIO score = round(mean of present {aeo, geo}); null if both are missing.
 */
export const getAioView = (report: CanonicalAuditReport): AioView | null => {
  const aioMeta = toObject(report.metadata).aio;
  if (aioMeta && typeof aioMeta === "object") {
    const meta = aioMeta as Record<string, unknown>;
    const components = toObject(meta.components);
    return {
      aio_score: toNullableScore(meta.aio_score),
      components: {
        aeo: toNullableScore(components.aeo),
        geo: toNullableScore(components.geo),
      },
      summary: typeof meta.summary === "string" ? meta.summary : null,
      scope: typeof meta.scope === "string" ? meta.scope : AIO_DEFAULT_SCOPE,
    };
  }

  const aeo = readNullablePrimaryScore(report, "aeo");
  const geo = readNullablePrimaryScore(report, "geo");
  if (aeo === null && geo === null) {
    return null;
  }

  const present = [aeo, geo].filter((value): value is number => value !== null);
  const aioScore = Math.round(present.reduce((sum, value) => sum + value, 0) / present.length);

  return {
    aio_score: aioScore,
    components: { aeo, geo },
    summary: null,
    scope: AIO_DEFAULT_SCOPE,
  };
};

/**
 * A single customer-facing search type under the AIO drilldown. Mirrors the
 * backend `report.metadata.search_types[]` entries produced by
 * `aggregate_search_types` (signal plan Phase 4): Brand, Category, Problem,
 * Feature and Comparison. `comparison` is the premium (Specialist+) type.
 */
/**
 * How many of the AI answers checked for a search type showed the brand.
 * `measured` is the number of completed query+provider checks, `present` the
 * subset the brand appeared in. The backend never emits `0 of 0`: a type with
 * nothing checked has no ratio at all.
 */
export type SearchTypeAnswerRatio = {
  present: number;
  measured: number;
};

export type SearchType = {
  /** Canonical id (brand | category | problem | feature | comparison). */
  id: string;
  /** Human-facing label (e.g. "Comparison"). */
  label: string;
  /** Per-type visibility score (0–100) or `null` when no signal exists. */
  score: number | null;
  /**
   * The answers checked for this type and how many showed the brand, or `null`
   * when no check has completed (SIGV2-1105).
   */
  answerRatio: SearchTypeAnswerRatio | null;
  /** Period-over-period trend, or `null` when no historical comparison. */
  trend: number | null;
  /** One-line, plain-language insight for the card. */
  insight: string;
  /** Whether the type is gated to Specialist+ (only `comparison` today). */
  premium: boolean;
  /**
   * Provenance of the score. `"measured"` = real per-query visibility observed
   * on this project's own AI-engine runs (VisibilityRunBatch). `"pending"` =
   * no measurement yet, but a run that will produce one is queued or in flight
   * for a prompt of this type (SIGV2-1182). Anything else, including the
   * retired `"derived"` heuristic estimate still present in reports served
   * before SIGV2-1105, is not a measurement and its score must not be
   * rendered.
   */
  source: "measured" | "pending" | "unmeasured" | string | null;
};

/** `true` only for a score this project's own visibility runs produced. */
export const isMeasuredSearchType = (searchType: SearchType): boolean =>
  searchType.source === "measured" &&
  typeof searchType.score === "number" &&
  Number.isFinite(searchType.score);

/**
 * `true` when a measurement for this type is queued or running (SIGV2-1182).
 * Never true alongside `isMeasuredSearchType`: the backend only pends a type
 * with no completed check of its own, and a pending type carries no score.
 */
export const isPendingSearchType = (searchType: SearchType): boolean =>
  searchType.source === "pending" && !isMeasuredSearchType(searchType);

/**
 * Returns the 5 customer-facing search types attached by the backend at
 * `report.metadata.search_types` (`aggregate_search_types`). Maps each entry to
 * the UI shape, preserving the backend order. Returns `[]` when absent.
 */
const toAnswerRatio = (value: unknown): SearchTypeAnswerRatio | null => {
  if (typeof value !== "object" || value === null) return null;
  const { present, measured } = value as Record<string, unknown>;
  if (typeof present !== "number" || typeof measured !== "number") return null;
  if (!Number.isInteger(present) || !Number.isInteger(measured)) return null;
  // `0 of 0` is not a ratio, and `6 of 4` is not one either: a shape the
  // payload cannot support reads as no measurement rather than as a figure.
  if (measured <= 0 || present < 0 || present > measured) return null;
  return { present, measured };
};

export const getSearchTypes = (report: CanonicalAuditReport): SearchType[] => {
  const raw = toObject(report.metadata).search_types;
  if (!Array.isArray(raw)) {
    return [];
  }

  const searchTypes: SearchType[] = [];
  raw.forEach((entry) => {
    if (typeof entry !== "object" || entry === null) return;
    const item = entry as Record<string, unknown>;
    const id = typeof item.id === "string" ? item.id : "";
    if (!id) return;

    searchTypes.push({
      id,
      label: typeof item.label === "string" ? item.label : id,
      score: toNullableScore(item.score),
      answerRatio: toAnswerRatio(item.answer_ratio),
      trend: toNullableScore(item.trend),
      insight: typeof item.insight === "string" ? item.insight : "",
      premium: item.premium === true,
      source: typeof item.source === "string" ? item.source : null,
    });
  });

  return searchTypes;
};

/** Impact / effort levels emitted by the deterministic Advisor. */
export type AdvisorLevel = "low" | "medium" | "high";

/**
 * A single ROI-ranked Advisor action, mapped from the backend's
 * `metadata.advisor.actions[]` shape (`build_advisor_plan`). The backend emits
 * `action`, optional `title`, `impact`, `effort`, `roi_score`,
 * `grounded_by_findings`, `derived_from` and `rank` — it does NOT emit a separate
 * "why" or "lift", so we surface only the real fields (`impact` drives the
 * expected-lift chip; the action text is the headline).
 */
export type AdvisorAction = {
  /** Stable id derived from the action's deterministic rank. */
  id: string;
  /** 1-based priority rank (1 = highest ROI). */
  rank: number;
  /** Headline action text (backend `title` if present, else `action`). */
  title: string;
  /** Fuller action text, present only when a distinct short `title` exists. */
  detail: string | null;
  /**
   * The backend's impact label. This is NOT evidence that anything was
   * measured: `advisor_view._impact_label` returns `"medium"` as a silent
   * fallback when the source item carries neither an explicit `impact` nor a
   * numeric `expected_score_impact`, so the label is always populated and a
   * defaulted value is indistinguishable from a real one at this level. Use
   * `resolveActionImpact` for anything customer-facing.
   */
  impact: AdvisorLevel;
  /**
   * The backend's effort label, with the same caveat: `toAdvisorLevel`
   * collapses a missing value to `"medium"`. Use `resolveActionEffort`.
   */
  effort: AdvisorLevel;
  /**
   * Where `impact` came from. `"advisor"` means it was read from
   * `metadata.advisor`; `"derived"` means a caller reconstructed it from the
   * canonical item because the advisor plan dropped the action.
   */
  impactSource: "advisor" | "derived";
  /** Grounding references (`grounded_by_findings` + `derived_from`). */
  groundedBy: string[];
  /**
   * Deterministic problem code (`problem_code`), present only when a
   * deterministic check raised this action. It is the action's durable
   * identity: unlike the title and detail text, which an LLM rewrites on every
   * audit, this value does not drift, so a dismissal keyed on it survives the
   * next audit (SIGV2-1118). `null` for LLM-authored advice.
   */
  problemCode: string | null;
};

/** The deterministic Advisor plan, mapped from `report.metadata.advisor`. */
export type AdvisorPlan = {
  schemaVersion: string;
  actions: AdvisorAction[];
  /** Optional LLM narrative — `null` for the default deterministic plan. */
  strategicSummary: string | null;
};

// Read-only passthrough: the server owns the vocabulary and validates it on
// write, so the client only checks the shape it will send back.
const toProblemCode = (value: unknown): string | null => {
  if (typeof value !== "string") return null;
  const code = value.trim().toLowerCase();
  return code && code.length <= 64 ? code : null;
};

const toAdvisorLevel = (value: unknown): AdvisorLevel => {
  const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
  return raw === "low" || raw === "high" ? raw : "medium";
};

/**
 * Returns the deterministic Advisor plan ("what to fix, in order") attached by
 * the backend at `report.metadata.advisor` (Task 3.1, `attach_advisor_view`).
 * Maps the backend keys to a clean UI shape and preserves the ROI ordering.
 * Returns `null` when the advisor plan is absent.
 */
export const getAdvisorPlan = (report: CanonicalAuditReport): AdvisorPlan | null => {
  const advisor: unknown = toObject(report.metadata).advisor;
  if (typeof advisor !== "object" || advisor === null) {
    return null;
  }

  const advisorObj = advisor as Record<string, unknown>;
  const rawActions = Array.isArray(advisorObj.actions) ? advisorObj.actions : [];

  const actions: AdvisorAction[] = [];
  rawActions.forEach((entry, index) => {
    if (typeof entry !== "object" || entry === null) return;
    const item = entry as Record<string, unknown>;

    const action = typeof item.action === "string" ? item.action.trim() : "";
    const titleField = typeof item.title === "string" ? item.title.trim() : "";
    const title = titleField || action;
    if (!title) return;

    const detail = titleField && action && action !== titleField ? action : null;
    const rank =
      typeof item.rank === "number" && Number.isFinite(item.rank) ? item.rank : index + 1;

    actions.push({
      id: `advisor-action-${rank}`,
      rank,
      title,
      detail,
      impact: toAdvisorLevel(item.impact),
      effort: toAdvisorLevel(item.effort),
      impactSource: "advisor",
      groundedBy: [
        ...toStringArray(item.grounded_by_findings),
        ...toStringArray(item.derived_from),
      ],
      problemCode: toProblemCode(item.problem_code),
    });
  });

  return {
    schemaVersion: typeof advisorObj.schema_version === "string" ? advisorObj.schema_version : "",
    actions,
    strategicSummary:
      typeof advisorObj.strategic_summary === "string" ? advisorObj.strategic_summary : null,
  };
};

// ---------------------------------------------------------------------------
// Canonical recommendation items (SIGV2-1037). `recommendations.items[]` is
// built by `_to_canonical_suggestions` and carries the fields the Advisor
// plan view flattens away: `estimated_effort`, `expected_score_impact`,
// `category`, `rationale` and the grounding refs. The Advisor emits impact and
// effort labels that fall back to "medium" when the source fields are absent,
// so the plan page joins back to these items to tell a measured rating from a
// defaulted one.
// ---------------------------------------------------------------------------

/** Per-dimension expected score deltas; every value may be explicitly null. */
export type ExpectedScoreImpact = {
  seo: number | null;
  geo: number | null;
  aeo: number | null;
  overall: number | null;
};

export type RecommendationItem = {
  /** Canonical long action text — the join key to `metadata.advisor` actions. */
  action: string;
  /** Short title; equals `action` when no distinct title exists. */
  title: string;
  /** Backend-normalised class: "Technical" | "Content" | "Backlinks" (or other). */
  category: string | null;
  rationale: string | null;
  /** Explicit effort rating; `null` when the item carries no valid value. */
  estimatedEffort: AdvisorLevel | null;
  /** Expected score deltas per dimension; `null` when the dict is absent. */
  expectedScoreImpact: ExpectedScoreImpact | null;
  /** Grounding references (`grounded_by_findings` + `derived_from`). */
  groundedBy: string[];
  /** Deterministic problem code; see `AdvisorAction.problemCode`. */
  problemCode: string | null;
};

const toNullableNumber = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

const toExpectedScoreImpact = (value: unknown): ExpectedScoreImpact | null => {
  if (typeof value !== "object" || value === null) return null;
  const raw = value as Record<string, unknown>;
  return {
    seo: toNullableNumber(raw.seo),
    geo: toNullableNumber(raw.geo),
    aeo: toNullableNumber(raw.aeo),
    overall: toNullableNumber(raw.overall),
  };
};

const toExplicitAdvisorLevel = (value: unknown): AdvisorLevel | null => {
  const raw = typeof value === "string" ? value.trim().toLowerCase() : "";
  return raw === "low" || raw === "medium" || raw === "high" ? (raw as AdvisorLevel) : null;
};

/**
 * Returns the canonical `recommendations.items[]` entries (with the
 * `narrative.recommendations.items` fallback the legacy path also reads).
 */
export const getRecommendationItems = (report: CanonicalAuditReport): RecommendationItem[] => {
  const rawReport = report as Record<string, any>;
  const items = rawReport.recommendations?.items ?? rawReport.narrative?.recommendations?.items;
  if (!Array.isArray(items)) return [];

  const out: RecommendationItem[] = [];
  for (const entry of items) {
    if (typeof entry !== "object" || entry === null) continue;
    const item = entry as Record<string, unknown>;
    const action = typeof item.action === "string" ? item.action.trim() : "";
    const titleField = typeof item.title === "string" ? item.title.trim() : "";
    const title = titleField || action;
    if (!title && !action) continue;
    out.push({
      action: action || title,
      title,
      category:
        typeof item.category === "string" && item.category.trim() ? item.category.trim() : null,
      rationale:
        typeof item.rationale === "string" && item.rationale.trim() ? item.rationale.trim() : null,
      estimatedEffort: toExplicitAdvisorLevel(item.estimated_effort),
      expectedScoreImpact: toExpectedScoreImpact(item.expected_score_impact),
      groundedBy: [
        ...toStringArray(item.grounded_by_findings),
        ...toStringArray(item.derived_from),
      ],
      problemCode: toProblemCode(item.problem_code),
    });
  }
  return out;
};

const normalizeJoinText = (value: string | null | undefined): string =>
  String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");

/**
 * Joins an Advisor plan action to its canonical `recommendations.items[]`
 * entry. The Advisor preserves `action` verbatim (`build_advisor_plan`), so
 * matching on the action text is exact; the title is a secondary key.
 */
export const matchRecommendationItem = (
  action: AdvisorAction,
  items: RecommendationItem[]
): RecommendationItem | null => {
  const keys = new Set([normalizeJoinText(action.title), normalizeJoinText(action.detail)]);
  keys.delete("");
  for (const item of items) {
    if (keys.has(normalizeJoinText(item.action)) || keys.has(normalizeJoinText(item.title))) {
      return item;
    }
  }
  return null;
};

/** True when at least one expected-score dimension carries a numeric delta. */
export const hasNumericScoreImpact = (impact: ExpectedScoreImpact | null): boolean =>
  impact !== null &&
  [impact.seo, impact.geo, impact.aeo, impact.overall].some((v) => typeof v === "number");

/**
 * Maps numeric score deltas to the categorical impact band, using the same
 * thresholds as the backend's `advisor_view._impact_label` so a reconstructed
 * label never disagrees with the one the Advisor would have produced.
 * Returns `null` when no dimension carries a number.
 */
export const deriveImpactLevel = (impact: ExpectedScoreImpact | null): AdvisorLevel | null => {
  if (!impact) return null;
  const deltas = [impact.seo, impact.geo, impact.aeo, impact.overall]
    .filter((v): v is number => typeof v === "number")
    .map(Math.abs);
  if (deltas.length === 0) return null;
  const top = Math.max(...deltas);
  if (top >= 10) return "high";
  if (top >= 4) return "medium";
  return "low";
};

/**
 * A rating that knows whether anything actually measured it. `measured: false`
 * carries no level at all, so a caller cannot accidentally render a default.
 */
export type ResolvedLevel =
  | { measured: true; level: AdvisorLevel }
  | { measured: false; level: null };

const UNMEASURED: ResolvedLevel = { measured: false, level: null };

/**
 * The single authority on whether a fix's impact may be shown as a category.
 *
 * Impact has exactly one real source: the numeric `expected_score_impact`
 * deltas on the canonical `recommendations.items[]` entry. Neither
 * `RecommendationItem` nor the legacy top-level `Suggestion` model carries an
 * `impact` field (both are `extra="forbid"`), so when those deltas are absent
 * the backend's label is its silent `"medium"` default and means nothing.
 *
 * This deliberately gates one field on the presence of another, which is only
 * sound because of that backend detail, so it lives here, named and tested,
 * instead of being re-derived at each call site.
 */
export const resolveActionImpact = (
  action: AdvisorAction,
  item: RecommendationItem | null
): ResolvedLevel => {
  const deltas = item?.expectedScoreImpact ?? null;
  if (!hasNumericScoreImpact(deltas)) return UNMEASURED;
  if (action.impactSource === "advisor") {
    return { measured: true, level: action.impact };
  }
  const derived = deriveImpactLevel(deltas);
  return derived ? { measured: true, level: derived } : UNMEASURED;
};

/**
 * Effort's only trustworthy source is the canonical item's explicitly
 * nullable `estimated_effort`. `action.effort` is never consulted: the
 * Advisor collapses a missing effort to `"medium"`, so trusting it would
 * present a default as a rating.
 */
export const resolveActionEffort = (
  _action: AdvisorAction,
  item: RecommendationItem | null
): ResolvedLevel =>
  item?.estimatedEffort ? { measured: true, level: item.estimatedEffort } : UNMEASURED;

/**
 * The same authority as `resolveActionImpact`, for the surfaces that read a
 * `DetailedRecommendation` instead of the Advisor plan: the SEO and AIO
 * Improve lists and the audit report's fix rows.
 *
 * Impact is categorical by product rule (SIGV2-1211), so `impactValue` is
 * read only to decide the band and is never printed. It is a score deduction
 * the audit measured, not a prediction of what a fix would recover, and
 * presenting it as "+N points you will gain" claims an estimate is a
 * measurement. The bands are `deriveImpactLevel`'s, so a rating here can
 * never disagree with the one the action plan shows for the same problem.
 *
 * No numeric source means no rating. Zero is "this costs nothing", which is
 * not a rating either, so both resolve to unmeasured and the caller renders
 * the unrated state rather than a defaulted "medium".
 */
export const resolveRecommendationImpact = (
  fix: Pick<DetailedRecommendation, "impactValue">
): ResolvedLevel => {
  const raw = fix.impactValue;
  if (typeof raw !== "number" || !Number.isFinite(raw) || raw === 0) return UNMEASURED;
  const level = deriveImpactLevel({ seo: null, geo: null, aeo: null, overall: Math.abs(raw) });
  return level ? { measured: true, level } : UNMEASURED;
};

/** Which product pillars an expected-score impact claims to move. */
export type ScorePillar = "seo" | "aio";

/**
 * Maps `expected_score_impact` dimensions to the product's two pillars, the
 * way `getPillars` does: `seo` -> SEO, `aeo`+`geo` -> AIO. Only positive
 * deltas count — the claim is "raises", so null, zero and negative values
 * all produce no claim. Never read `cross_score_leverage` for this, it is
 * silently defaulted to ["seo"] upstream.
 */
export const impactedPillars = (impact: ExpectedScoreImpact | null): ScorePillar[] => {
  if (!impact) return [];
  const out: ScorePillar[] = [];
  if (typeof impact.seo === "number" && impact.seo > 0) out.push("seo");
  if (
    (typeof impact.aeo === "number" && impact.aeo > 0) ||
    (typeof impact.geo === "number" && impact.geo > 0)
  )
    out.push("aio");
  return out;
};

/**
 * Returns the two customer-facing headline pillars: SEO (website only) and
 * AIO (website & brand — the AEO+GEO roll-up).
 */
export const getPillars = (report: CanonicalAuditReport): Pillar[] => {
  const seoScore = getAuditPrimaryScore(report, "seo");
  const aioScore = getAioView(report)?.aio_score ?? null;

  return [
    {
      key: "seo",
      label: "SEO",
      score: seoScore,
      scopeLabel: "Website only",
      color: PILLAR_COLORS.seo,
    },
    {
      key: "aio",
      label: "AIO",
      score: aioScore,
      scopeLabel: "Website & Brand",
      color: PILLAR_COLORS.aio,
    },
  ];
};

export const getAuditLockedSection = (
  report: CanonicalAuditReport | null | undefined,
  sectionKey: string
): LockedAuditSection | null => {
  const metadata = toObject(report?.metadata);
  const lockedSections = toObject(metadata.locked_sections);
  const section = lockedSections[sectionKey];
  if (typeof section !== "object" || section === null || section.is_locked !== true) {
    return null;
  }
  return section as LockedAuditSection;
};

export const getAuditRecommendations = (report: CanonicalAuditReport): string[] => {
  const analysis = report.analysis ?? {};
  const isLegacy = isLegacyNormalizedReport(report);
  const deduped = new Set<string>();

  [
    report.suggestions,
    report.seo?.suggestions,
    report.geo?.suggestions,
    report.aeo?.suggestions,
    report.seo?.recommendations,
    report.geo?.recommendations,
    report.aeo?.recommendations,
    ...(isLegacy
      ? [
          analysis?.recommendations,
          analysis?.seo_score?.recommendations,
          analysis?.geo_score?.recommendations,
          analysis?.aeo_score?.recommendations,
          analysis?.aeo_recommendations,
          analysis?.geo_recommendations,
        ]
      : []),
  ]
    .flatMap((entry) => toDetailedRecommendationArray(entry).map((rec) => rec.title))
    .forEach((rec) => deduped.add(rec));

  return Array.from(deduped);
};

// Impact severity ladder for merging two entries that name one problem.
const IMPACT_SEVERITY: Record<DetailedRecommendation["impact"], number> = {
  Optimization: 0,
  Strategic: 1,
  Critical: 2,
};

/**
 * Rating order for the SIGV2-1211 ladder. Unmeasured is last, never "low":
 * a rating that is absent is also treated as unmeasured, because "no ladder
 * at all" cannot be a band either.
 */
const LEVEL_RANK: Record<AdvisorLevel, number> = { high: 0, medium: 1, low: 2 };
const UNRATED_RANK = 3;
const impactRank = (level: ResolvedLevel | undefined): number =>
  level?.measured ? LEVEL_RANK[level.level] : UNRATED_RANK;
/** Cheapest first, with unmeasured last for the same reason. */
const EFFORT_RANK: Record<AdvisorLevel, number> = { low: 0, medium: 1, high: 2 };
const effortRank = (level: ResolvedLevel | undefined): number =>
  level?.measured ? EFFORT_RANK[level.level] : UNRATED_RANK;

/**
 * The one ordering of the consolidated list (SIGV2-1193).
 *
 * Severity first, because that is the ladder the report rows and the project
 * overview's top three already sort on; then the measured impact band, then
 * the measured effort band (ROI: biggest and easiest first, the Advisor's own
 * rule), then the title so the order is stable for a given audit.
 *
 * Unrated sorts last at every level it participates in. It is never treated
 * as "low": "nothing measured this" and "this measured low" are different
 * statements, and collapsing them would quietly promote or demote a row on
 * the strength of a default.
 */
type FixOrderKey = Pick<ConsolidatedFix, "impact" | "impactLevel" | "effortLevel" | "title">;

export const compareConsolidatedFixes = (a: FixOrderKey, b: FixOrderKey): number =>
  IMPACT_SEVERITY[b.impact] - IMPACT_SEVERITY[a.impact] ||
  impactRank(a.impactLevel) - impactRank(b.impactLevel) ||
  effortRank(a.effortLevel) - effortRank(b.effortLevel) ||
  a.title.localeCompare(b.title);

/** The severity band a resolved impact level maps onto. */
const severityForLevel = (level: ResolvedLevel): DetailedRecommendation["impact"] => {
  if (!level.measured) return "Optimization";
  return level.level === "high"
    ? "Critical"
    : level.level === "medium"
      ? "Strategic"
      : "Optimization";
};

/**
 * `{dimension}.penalty.{code}` is the only reference shape the pipeline emits
 * for a deterministic problem (`problem_code_suggestions.grounding_ref`).
 * Keyword grounding can only ever produce `{dimension}.finding.{n}`, which
 * this deliberately does not match.
 */
const PENALTY_REF_RE = /^(seo|geo|aeo)\.penalty\.([a-z][a-z0-9_]{2,47})$/;

/**
 * Secondary join key (SIGV2-1193, step 2): the problem code named by a
 * grounding reference, for an item that carries no `problem_code` of its own.
 *
 * Exact and closed-world, like the primary key: the reference shape above is
 * produced by exactly one function, and only for a code that was already in
 * the `problem_codes` registry when the penalty was raised, so reading the
 * code back out of it is transport decoding, not inference. No fuzzy match,
 * no text similarity, no model-assigned code. `problem_codes.py` forbids all
 * three and that rule stands.
 *
 * Measured against the pipeline as it stands, this can never fire: the
 * deterministic channel attaches the code and the reference in the same
 * breath (`build_problem_code_suggestions`), and an LLM-authored item never
 * receives a penalty reference at all - `test_llm_items_never_receive_a_penalty_reference`
 * pins that. It is implemented anyway, and tested, so that if a future
 * grounding change does start producing a coded reference on an uncoded item
 * the row folds instead of duplicating.
 */
export const problemCodeFromGroundingRefs = (refs: readonly string[]): string | null => {
  for (const ref of refs) {
    const match = PENALTY_REF_RE.exec(
      String(ref ?? "")
        .trim()
        .toLowerCase()
    );
    if (match) return match[2];
  }
  return null;
};

type FixDraft = Omit<ConsolidatedFix, "id" | "rank"> & { id?: string };

/**
 * The single consolidated list of things to fix (SIGV2-1193).
 *
 * Until this existed the product showed two: the audit's own findings (the
 * Improve tabs) and the Advisor's action plan (the fixes page). They had
 * different totals, a stakeholder read the difference as a contradiction
 * ("22 versus 10"), and SIGV2-1175 answered it by labelling each list with
 * its source and its own count. This is the backlog item that created, so the
 * two are merged here, once, and every surface reads the result.
 *
 * The join, exactly:
 *
 * 1. **Primary key: `problem_code`.** The closed registry in
 *    `problem_codes.py`. It is attached at the deterministic source before any
 *    model sees the text and travels unchanged through enrichment, so two
 *    entries sharing a code are one problem however differently they are
 *    worded. One row, and it keeps the richer guidance.
 * 2. **Secondary key: a coded grounding reference**, for an entry with no
 *    `problem_code` (see `problemCodeFromGroundingRefs`).
 * 3. **Nothing else.** No fuzzy matching, no text similarity, no
 *    model-assigned code, ever.
 * 4. **An uncoded entry is never merged.** It appears exactly once, on its own
 *    row, labelled with the channel that raised it. Identity must fail toward
 *    showing the fix: a wrongly merged row silently deletes advice the
 *    customer pays for, and nobody can see it happened.
 * 5. **Eligibility is the Advisor's, unchanged.** The plan drops candidates it
 *    cannot ground to a finding (`require_grounding=True`), and this list does
 *    not put them back: the recommendation channel is read from the plan when
 *    the plan has actions. Only when the plan is empty does it fall back to the
 *    canonical items (SIGV2-1096: a degraded run can ground nothing, and
 *    claiming no check ran would be worse), and only when there are no
 *    canonical items either does it fall back to `report.suggestions`.
 *    Exactly one of the three is read, which is what stops the same fix being
 *    counted twice: `recommendations.items[]` is built from `suggestions`
 *    (`_build_recommendations_block`) and the plan is built from the items
 *    (`advisor_view._report_suggestions`), so all three are the same content
 *    at different stages of processing.
 */
export const getConsolidatedFixes = (report: CanonicalAuditReport): ConsolidatedFix[] => {
  const drafts: FixDraft[] = [];
  const seenTitles = new Set<string>();
  const byProblemCode = new Map<string, FixDraft>();

  const mergeInto = (existing: FixDraft, incoming: FixDraft) => {
    if (existing.impactValue === undefined && incoming.impactValue !== undefined) {
      existing.impactValue = incoming.impactValue;
    }
    if (!existing.section && incoming.section) existing.section = incoming.section;
    if (!existing.page && incoming.page) existing.page = incoming.page;
    if (!existing.confidence && incoming.confidence) existing.confidence = incoming.confidence;
    if (!existing.description && incoming.description) {
      existing.description = incoming.description;
    }
    for (const engine of incoming.engines) {
      if (!existing.engines.includes(engine)) existing.engines.push(engine);
    }
    if (IMPACT_SEVERITY[incoming.impact] > IMPACT_SEVERITY[existing.impact]) {
      existing.impact = incoming.impact;
    }
    // A rating only arrives by being measured, so an unmeasured side never
    // overwrites a measured one, and two measured sides keep the first
    // (the action plan's own rating, when the plan raised this row).
    if (!existing.impactLevel.measured && incoming.impactLevel.measured) {
      existing.impactLevel = incoming.impactLevel;
    }
    if (!existing.effortLevel.measured && incoming.effortLevel.measured) {
      existing.effortLevel = incoming.effortLevel;
    }
    if (existing.pillars.length === 0) existing.pillars = incoming.pillars;
    if (existing.actionText === null) existing.actionText = incoming.actionText;
    for (const ref of incoming.groundedBy) {
      if (!existing.groundedBy.includes(ref)) existing.groundedBy.push(ref);
    }
    for (const source of incoming.sources) {
      if (!existing.sources.includes(source)) existing.sources.push(source);
    }
    // The code can arrive on the second side (a penalty folding into an item
    // joined through its grounding reference, and the reverse).
    if (!existing.problemCode && incoming.problemCode) {
      existing.problemCode = incoming.problemCode;
    }
  };

  const commit = (draft: FixDraft): void => {
    const code = draft.problemCode || problemCodeFromGroundingRefs(draft.groundedBy);
    if (code) {
      draft.problemCode = code;
      const existing = byProblemCode.get(code);
      if (existing) {
        mergeInto(existing, draft);
        return;
      }
      byProblemCode.set(code, draft);
    }
    drafts.push(draft);
  };

  /** An audit-finding row: everything the audit itself raised. */
  const finding = (rec: DetailedRecommendation): FixDraft => ({
    ...rec,
    sources: ["audit_finding"],
    // The finding's own band comes from the deduction the audit measured.
    // Nothing measures a finding's effort, so effort stays explicitly unrated.
    impactLevel: resolveRecommendationImpact(rec),
    effortLevel: UNMEASURED,
    pillars: [],
    groundedBy: [],
    actionText: null,
  });

  // 1. From Intelligence Dossier (Deep Scan / Neural)
  if (Array.isArray(report.intelligence_dossier)) {
    report.intelligence_dossier.forEach((item) => {
      if (!item.finding_title || seenTitles.has(item.finding_title)) return;

      let category = item.source_tool || "General";
      if (category.includes("Technical")) category = "Technical";
      else if (category.includes("Semantic")) category = "Semantic";
      else if (category.includes("Intent")) category = "Intent";

      commit(
        finding({
          title: item.finding_title,
          description: item.data_observation || item.implementation_logic || "",
          category,
          impact:
            item.priority_level === "Critical"
              ? "Critical"
              : item.priority_level === "Strategic"
                ? "Strategic"
                : "Optimization",
          engines: ["SEO", "GEO", "AEO"], // Dossier is usually cross-engine
          problemCode: toProblemCode((item as Record<string, unknown>).problem_code),
        })
      );
      seenTitles.add(item.finding_title);
    });
  }

  // 2. From Debate Findings (handles both typed and narrative formats)
  if (Array.isArray(report.debate_findings)) {
    report.debate_findings.forEach((item: any) => {
      const title = item.finding || item.discovery;
      if (!title || seenTitles.has(title)) return;

      const pw = typeof item.priority_weight === "number" ? item.priority_weight : 0;
      let impact: "Critical" | "Strategic" | "Optimization" = "Optimization";
      if (item.severity === "Critical" || pw >= 0.9) impact = "Critical";
      else if (item.severity === "Strategic" || pw >= 0.7) impact = "Strategic";

      commit(
        finding({
          title,
          description:
            item.architect_fix || item.llm_behavior_projection || item.neural_logic || "",
          category: item.layer || item.agent_correlation || "Neural",
          impact,
          engines: ["GEO", "AEO"],
          problemCode: toProblemCode(item.problem_code),
        })
      );
      seenTitles.add(title);
    });
  }

  // 3. From Detailed SEO Optimization Roadmap
  if (Array.isArray(report.detailed_seo_recommendations)) {
    report.detailed_seo_recommendations.forEach((item) => {
      if (!item.title || seenTitles.has(item.title)) return;

      commit(
        finding({
          title: item.title,
          description: item.description || item.implementation || "",
          category: item.source || "SEO",
          impact:
            item.priority === "Critical"
              ? "Critical"
              : item.priority === "Warning"
                ? "Strategic"
                : "Optimization",
          engines: ["SEO"],
          problemCode: toProblemCode((item as Record<string, unknown>).problem_code),
        })
      );
      seenTitles.add(item.title);
    });
  }

  // 4. The recommendation channel: exactly one of the Advisor plan, the
  //    canonical items, or the legacy `suggestions` array (see rule 5 above).
  const rawReport = report as Record<string, any>;
  const plan = getAdvisorPlan(report);
  const items = getRecommendationItems(report);

  const commitAction = (action: AdvisorAction, item: RecommendationItem | null) => {
    const title = action.title;
    if (!title || seenTitles.has(title)) return;
    const impactLevel = resolveActionImpact(action, item);
    commit({
      id: action.id,
      title,
      description: action.detail ?? item?.rationale ?? "",
      category: item?.category ?? "General",
      // Severity is the ladder the report rows and the ordering speak; it is
      // read off the resolved band so one problem cannot be Critical on one
      // surface and Optimization on another.
      impact: severityForLevel(impactLevel),
      engines: ["SEO", "GEO", "AEO"],
      problemCode: action.problemCode,
      sources: ["action_plan"],
      impactLevel,
      effortLevel: resolveActionEffort(action, item),
      pillars: impactedPillars(item?.expectedScoreImpact ?? null),
      groundedBy: item?.groundedBy?.length ? [...item.groundedBy] : [...action.groundedBy],
      // The dismiss contract hashes the canonical action text, so the item's
      // `action` is preferred: on the fallback path `action.detail` holds the
      // rationale, not the action.
      actionText: item?.action ?? action.detail ?? title,
    });
    seenTitles.add(title);
  };

  if (plan && plan.actions.length > 0) {
    plan.actions.forEach((action) => commitAction(action, matchRecommendationItem(action, items)));
  } else if (items.length > 0) {
    // SIGV2-1096: the Advisor drops candidates it cannot ground to a finding,
    // and a degraded run can emit recommendations while emitting no findings
    // at all, so the plan comes back empty. Listing the candidates unrated is
    // the honest answer; claiming no check ran is not. This is all-or-nothing
    // on purpose - it never reinstates a subset the Advisor rejected while
    // keeping the rest of its plan.
    items.forEach((item, index) =>
      commitAction(
        {
          id: `rec-${index + 1}`,
          rank: index + 1,
          title: item.title || item.action,
          detail: item.action !== item.title ? item.action : (item.rationale ?? null),
          // Reconstructed from the item's own deltas, never guessed, and
          // `impactSource: "derived"` stops `resolveActionImpact` trusting a
          // label the Advisor never produced for this action.
          impact: deriveImpactLevel(item.expectedScoreImpact) ?? "medium",
          effort: item.estimatedEffort ?? "medium",
          impactSource: "derived",
          groundedBy: item.groundedBy,
          problemCode: item.problemCode,
        },
        item
      )
    );
  } else {
    // Legacy and guest reports: no advisor plan and no canonical items, only
    // the flat `suggestions` array the older schema carried.
    const suggestions = Array.isArray(report.suggestions) ? report.suggestions : [];
    suggestions.forEach((entry: any) => {
      let title = "";
      let desc = "";
      let cat = "General";
      let imp: "Critical" | "Strategic" | "Optimization" = "Strategic";
      const eng: Array<"SEO" | "GEO" | "AEO"> = ["SEO", "GEO", "AEO"];
      let conf: "high" | "medium" | "low" | undefined;

      if (typeof entry === "string") {
        title = entry;
      } else {
        title =
          typeof entry.title === "string"
            ? entry.title
            : typeof entry.action === "string"
              ? entry.action
              : "";
        desc = entry.action || entry.description || "";
        cat = entry.category || "General";

        const rawImpact = entry.impact || entry.priority_level || entry.severity;
        const rawPriority = entry.priority;

        if (rawImpact === "Critical" || rawPriority === 1 || rawPriority === "1") imp = "Critical";
        else if (
          rawImpact === "Strategic" ||
          rawImpact === "Warning" ||
          rawPriority === 2 ||
          rawPriority === "2"
        )
          imp = "Strategic";
        else imp = "Optimization";

        if (
          entry.confidence === "high" ||
          entry.confidence === "medium" ||
          entry.confidence === "low"
        ) {
          conf = entry.confidence;
        }
      }

      if (!title || seenTitles.has(title)) {
        return;
      }

      commit({
        ...finding({
          title,
          description: desc,
          category: cat,
          impact: imp,
          engines: eng,
          confidence: conf,
          problemCode: typeof entry === "object" ? toProblemCode(entry.problem_code) : null,
        }),
        actionText: desc || title,
      });
      seenTitles.add(title);
    });
  }

  // 5. From score breakdown penalties (SEO, AEO, GEO), enriched with page, section, impact
  const scores = rawReport.scores ?? {};
  const auditedPageUrl = report.target?.url || report.site?.url || report.url || "";
  const missingSchemaTypes: string[] = report.aeo?.schema_health?.missing_required_types ?? [];
  const penaltyEngineMap: Array<{ key: string; engine: "SEO" | "GEO" | "AEO" }> = [
    { key: "seo_breakdown", engine: "SEO" },
    { key: "aeo_breakdown", engine: "AEO" },
    { key: "geo_breakdown", engine: "GEO" },
  ];
  for (const { key, engine } of penaltyEngineMap) {
    const penalties = scores[key]?.penalties;
    if (!Array.isArray(penalties)) continue;
    penalties.forEach((pen: any) => {
      const reason = typeof pen === "string" ? pen : pen?.reason;
      if (!reason || seenTitles.has(reason)) return;

      const rawImpactVal = typeof pen?.impact === "number" ? pen.impact : 0;
      const isAiFinding = typeof pen === "object" && pen?.source === "ai_finding";

      let impact: "Critical" | "Strategic" | "Optimization";
      if (isAiFinding && pen.severity === "critical") impact = "Critical";
      else if (isAiFinding && pen.severity === "warning") impact = "Strategic";
      else {
        const impactAbs = Math.abs(rawImpactVal);
        impact = impactAbs >= 15 ? "Critical" : impactAbs >= 10 ? "Strategic" : "Optimization";
      }

      const section = mapPenaltySection(reason);

      let description: string;
      let category = engine as string;
      let confidence: "high" | "medium" | "low" | undefined;
      if (isAiFinding) {
        // Real, model-generated finding, use its own description/rationale
        // instead of restating the reason in a generic template.
        const findingDescription =
          typeof pen.description === "string" ? pen.description.trim() : "";
        const rationale = typeof pen.rationale === "string" ? pen.rationale.trim() : "";
        description = [findingDescription || reason, rationale].filter(Boolean).join(" ");
        if (typeof pen.category === "string" && pen.category.trim()) {
          // AI findings return free-form snake_case categories (e.g.
          // "structured_data"); humanize for display instead of leaking the
          // raw identifier into the card badge.
          category = pen.category
            .trim()
            .replace(/[_-]+/g, " ")
            .replace(/\b\w/g, (c: string) => c.toUpperCase());
        }
        if (typeof pen.confidence === "number") {
          confidence = pen.confidence >= 0.8 ? "high" : pen.confidence >= 0.5 ? "medium" : "low";
        }
      } else {
        description =
          getPenaltyFixGuidance(reason) ??
          `Fix: ${reason.toLowerCase()} to improve ${engine} score.`;
        if (section.startsWith("Structured Data") && missingSchemaTypes.length > 0) {
          description += ` Missing types: ${missingSchemaTypes.join(", ")}.`;
        }
      }

      commit(
        finding({
          title: reason,
          description,
          category,
          impact,
          engines: [engine],
          confidence,
          page: auditedPageUrl || undefined,
          section,
          impactValue: rawImpactVal || undefined,
          // The deterministic check's stable code (`pen.code`): this is the key
          // the enriched recommendations.items entry for the same problem also
          // carries, so commit() folds them into one row.
          problemCode: typeof pen === "object" && pen !== null ? toProblemCode(pen.code) : null,
        })
      );
      seenTitles.add(reason);
    });
  }

  // One ordering, assigned once, so every surface counts and ranks the same
  // list. `rank` is the row's position in it: the action plan prints it, and
  // the overview's top three is literally this list's first three.
  return drafts.sort(compareConsolidatedFixes).map((draft, index) => ({
    ...draft,
    id: draft.id ?? `fix-${index + 1}`,
    rank: index + 1,
  }));
};

/**
 * @deprecated Use `getConsolidatedFixes`. Retained as the name the Improve
 * tabs, the report rows and the project surfaces already import; it returns
 * the same single consolidated list (SIGV2-1193).
 */
export const getDetailedAuditRecommendations = getConsolidatedFixes;

// ---------------------------------------------------------------------------
// Brand-only audit recommendation filter
// ---------------------------------------------------------------------------
// Strips website-specific technical recommendations that are irrelevant when
// no URL was provided (brand entity audits).
const _BRAND_IRRELEVANT_PATTERNS = [
  /\bmeta\s*(tag|description|title)\b/i,
  /\b(page\s*speed|page\s*load|loading\s*speed)\b/i,
  /\b(core\s*web\s*vitals|cwv|cls|lcp|fid|inp|ttfb)\b/i,
  /\bcanonical\s*(url|tag)\b/i,
  /\balt\s*text\b/i,
  /\binternal\s*link/i,
  /\bhttp\/?\d\b/i,
  /\brobots\.txt\b/i,
  /\bsitemap(\.xml)?\b/i,
  /\b(ssl|https)\b/i,
  /\bredirect\s*(chain|loop)\b/i,
  /\b(minif|compress|gzip|brotli)\b/i,
  /\b(lazy\s*load|image\s*optim)/i,
  /\bviewport\b/i,
  /\bmobile\s*(friendly|responsive)\b/i,
  /\b(heading|h[1-6])\s*(hierarchy|structure|tag)\b/i,
  /\b(crawl|index|noindex|nofollow)\b/i,
  /\bhreflang\b/i,
  /\bopen\s*graph\b/i,
];

export const filterBrandOnlyRecommendations = <T extends DetailedRecommendation>(
  recommendations: T[]
): T[] => {
  return recommendations.filter((rec) => {
    const text = `${rec.title} ${rec.description}`;
    // Keep if purely Technical category with no other signals
    if (
      rec.category.toLowerCase() === "technical" &&
      rec.engines.length === 1 &&
      rec.engines[0] === "SEO"
    ) {
      return false;
    }
    return !_BRAND_IRRELEVANT_PATTERNS.some((pat) => pat.test(text));
  });
};

export const getAuditScopedRecommendations = (
  report: CanonicalAuditReport,
  key: "seo" | "geo" | "aeo"
): string[] => {
  const analysis = report.analysis ?? {};
  const section = toObject((report as Record<string, unknown>)[key]);
  const isLegacy = isLegacyNormalizedReport(report);
  const deduped = new Set<string>();

  [
    section.suggestions,
    section.recommendations,
    ...(isLegacy
      ? [analysis?.[`${key}_score`]?.recommendations, analysis?.[`${key}_recommendations`]]
      : []),
  ]
    .flatMap((entry) => toDetailedRecommendationArray(entry).map((rec) => rec.title))
    .forEach((rec) => deduped.add(rec));

  return Array.from(deduped);
};

const normalizeEntity = (entity: unknown): NormalizedEntity | null => {
  if (typeof entity === "string") {
    return { name: entity, type: "Entity", relevance: null };
  }

  if (typeof entity === "object" && entity) {
    const entry = entity as Record<string, any>;
    return {
      name: entry.name ?? entry.entity ?? entry.label ?? "Unnamed Entity",
      type: entry.type ?? entry.category ?? "Entity",
      relevance:
        entry.relevance === undefined && entry.score === undefined
          ? null
          : toScoreValue(entry.relevance ?? entry.score),
    };
  }

  return null;
};

export const getAuditEntities = (report: CanonicalAuditReport): NormalizedEntity[] => {
  const analysis = report.analysis ?? {};
  const canonicalEntityObject = toObject(report.entities);
  const isLegacy = isLegacyNormalizedReport(report);
  const candidates = [
    report.entities,
    canonicalEntityObject.items,
    canonicalEntityObject.entities,
    ...(isLegacy
      ? [
          analysis?.entities_detected,
          analysis?.entity_data?.entities_detected,
          analysis?.entity_data?.entities,
          analysis?.entity_summary?.entities,
        ]
      : []),
  ];
  const rawEntities = candidates.find((entry) => Array.isArray(entry)) ?? [];

  return rawEntities.map(normalizeEntity).filter(Boolean) as NormalizedEntity[];
};

export const getAuditEntityCategories = (report: CanonicalAuditReport): string[] => {
  const canonicalEntityObject = toObject(report.entities);
  const analysis = report.analysis ?? {};

  const canonicalCategories = toStringArray(canonicalEntityObject.categories);
  if (canonicalCategories.length > 0) return canonicalCategories;

  if (!isLegacyNormalizedReport(report)) {
    return [];
  }

  return toStringArray(analysis?.entity_data?.categories);
};

export const getAuditEntityDetails = (report: CanonicalAuditReport): Record<string, any> | null => {
  const canonicalEntityObject = toObject(report.entities);
  const analysis = report.analysis ?? {};

  if (Object.keys(canonicalEntityObject).length > 0) {
    return canonicalEntityObject;
  }

  if (!isLegacyNormalizedReport(report)) {
    return null;
  }

  return analysis?.entity_data ?? analysis?.entity_summary ?? null;
};

export const canonicalToDashboardAdapter = (report: CanonicalAuditReport): AuditResult => {
  const seoScore = report.scores?.seo ?? report.seo?.onpage ?? 0;
  const geoScore = report.scores?.geo ?? report.geo?.visibility_index ?? 0;
  const aeoScore = report.scores?.aeo ?? report.aeo?.answerability_score ?? 0;
  const overallScore = report.scores?.overall ?? null;

  const siteUrl = report.url || report.site?.url || "";
  const market = report.site?.market || report.metadata?.market || "global";
  const language = report.site?.language || report.metadata?.language || "en";

  const suggestions: Suggestion[] = Array.isArray(report.suggestions)
    ? toDetailedRecommendationArray(report.suggestions).map((item, i) => ({
        priority: Number.isFinite(Number(item.priority)) ? Number(item.priority) : i + 1,
        title: item.title,
        action: item.action || item.title,
        category:
          item.category === "Technical" ||
          item.category === "Content" ||
          item.category === "Backlinks"
            ? item.category
            : undefined,
      }))
    : [];

  const competitors: CompetitorScore[] = Array.isArray(report.competitors)
    ? (report.competitors as CompetitorScore[])
    : [];

  const entities = getAuditEntities(report).map((e) => e.name);
  const targetType =
    report.target?.type === "brand" || report.metadata?.audit_target_type === "brand"
      ? "brand"
      : "website";
  const targetUrl =
    report.target?.url ??
    (typeof report.metadata?.target_url === "string" ? report.metadata.target_url : null) ??
    (siteUrl || null);
  const targetName =
    report.target?.name ??
    (typeof report.metadata?.target_name === "string" ? report.metadata.target_name : null) ??
    targetUrl;
  const targetMetadata =
    (report.target?.metadata && typeof report.target.metadata === "object"
      ? report.target.metadata
      : null) ??
    (report.metadata?.target_metadata && typeof report.metadata.target_metadata === "object"
      ? report.metadata.target_metadata
      : null) ??
    {};

  return {
    schema_version: report.schema_version,
    target: {
      type: targetType,
      name: targetName,
      url: targetUrl,
      metadata: targetMetadata as Record<string, unknown>,
    },
    site: { url: siteUrl, market, language },
    seo: {
      onpage: report.seo?.onpage ?? seoScore,
      performance: hasOwnKey(report.seo, "performance")
        ? (report.seo?.performance ?? null)
        : (report.technical_signals?.performance?.score ?? 0),
      indexing: report.seo?.indexing ?? seoScore,
    },
    geo: {
      visibility_index: hasOwnKey(report.geo, "visibility_index")
        ? (report.geo?.visibility_index ?? null)
        : geoScore,
      citation_share: report.geo?.citation_share ?? null,
      brand_anchor: report.geo?.brand_anchor ?? null,
    },
    aeo: {
      answerability_score: hasOwnKey(report.aeo, "answerability_score")
        ? (report.aeo?.answerability_score ?? null)
        : aeoScore,
      extractable_pages: report.aeo?.extractable_pages ?? null,
      schema_health: report.aeo?.schema_health as any,
      schema_coverage: report.aeo?.schema_coverage as any,
      readability_score: report.aeo?.readability_score as any,
      readability_findings: report.aeo?.readability_findings as any,
      rewrite_suggestions: report.aeo?.rewrite_suggestions as any,
    },
    entities,
    competitors,
    suggestions,
    scores: {
      seo: seoScore,
      geo: geoScore,
      aeo: aeoScore,
      overall: overallScore,
    },
    metadata: {
      created_at: report.metadata?.created_at || new Date().toISOString(),
      updated_at: report.metadata?.updated_at || new Date().toISOString(),
      plan: report.metadata?.plan || "plan_starter",
      current_plan:
        typeof report.metadata?.current_plan === "string" ? report.metadata.current_plan : null,
      version: report.metadata?.version || report.schema_version || "1.0",
      audit_outcome:
        typeof report.metadata?.audit_outcome === "string"
          ? report.metadata.audit_outcome
          : undefined,
      scores_available:
        typeof report.metadata?.scores_available === "boolean"
          ? report.metadata.scores_available
          : undefined,
      audit_target_type: targetType,
      target_name: targetName,
      target_url: targetUrl,
      target_metadata: targetMetadata as Record<string, unknown>,
      technical_signals: report.technical_signals,
      intent: report.metadata?.intent || null,
      query_type: report.metadata?.query_type || null,
    },
    hallucination: report.hallucination as HallucinationResult | null | undefined,
  };
};
