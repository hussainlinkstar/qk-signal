/**
 * The visibility provider keys, exactly as the backend sends them.
 *
 * The backend is the contract: `SUPPORTED_VISIBILITY_PROVIDERS` in
 * `backend/services/project_visibility_service.py` is the only place these are
 * defined, and they arrive here on `provider_breakdown` rows, on
 * `allowed_providers` in the visibility entitlements, on query `providers` and
 * on the trend series. Keep this union equal to that tuple, never the reverse.
 *
 * Meta used to be keyed `meta_ai` here, which the backend has never sent (it
 * was removed from the backend registry before `meta` was added, and only
 * survives in two backend test comments). A real `meta` row therefore missed
 * the label map, the chart colour and the logo map at once, so the AIO
 * by-engine tab would have rendered the raw string `meta` with no icon the
 * moment Meta visibility data landed.
 *
 * `VISIBILITY_PROVIDERS` is the runtime companion of this union - a type
 * cannot be enumerated at test time, and the key set is gated against the
 * committed backend vocabulary in `contracts/visibility_providers.json` by
 * `monitoring.providerContract.test.ts`.
 */
export const VISIBILITY_PROVIDERS = [
  "google",
  "openai",
  "anthropic",
  "bing",
  "perplexity",
  "xai",
  "deepseek",
  "meta",
] as const;

export type VisibilityProvider = (typeof VISIBILITY_PROVIDERS)[number];

/**
 * Engines withdrawn from the product (SIGV2-1215).
 *
 * `bing` is labelled "Copilot" and was the only engine with no live
 * measurement path: there is no public consumer API for Copilot answers, so it
 * could only run through a Bedrock proxy model that is not Copilot. Jake took
 * it out of the product on 2026-09-28.
 *
 * The key stays in `VISIBILITY_PROVIDERS` and in the label map on purpose: a
 * recorded measurement must still resolve to a name, and the backend keeps the
 * provider and its proxy path behind the matching
 * `WITHDRAWN_VISIBILITY_PROVIDERS` flag. What changes is that no surface may
 * render it. Mirrors `withdrawn` in `contracts/visibility_providers.json`,
 * which `monitoring.providerContract.test.ts` holds both sides to.
 */
export const WITHDRAWN_VISIBILITY_PROVIDERS = ["bing"] as const satisfies ReadonlyArray<
  (typeof VISIBILITY_PROVIDERS)[number]
>;

/** The engines the product offers, which is the only set a surface may render. */
export const OFFERED_VISIBILITY_PROVIDERS = VISIBILITY_PROVIDERS.filter(
  (provider) => !(WITHDRAWN_VISIBILITY_PROVIDERS as readonly string[]).includes(provider)
) as readonly VisibilityProvider[];

export type VisibilityQueryStatus = "pending" | "cited" | "not_cited" | "failed";

/**
 * One engine's measurement status for a project, as `entitlements.engines`
 * carries it.
 *
 * `measured_on_plan` is the field SIGV2-1216 added, and it is the one that
 * stops `last_measured_at` from lying. Offering an engine and measuring it for
 * this project are two different facts, and they only came apart once a plan
 * roster shrank.
 *
 * Every offered engine is listed on every plan, so a row rendered without
 * consulting this flag claims a measurement the plan never takes: Starter
 * lists seven engines and measures one. SIGV2-1228 made the rest of the row
 * match. A row with `measured_on_plan: false` carries no number and no
 * timestamp: `last_measured_at` is null even when the project holds real runs
 * for the engine, because a date beside an engine nothing is re-measuring
 * reads as a current measurement. Render such a row as unavailable on this
 * plan and name `unlocks_on_plan_label` as what unlocks it (SIGV2-1221's
 * pattern); never substitute a 0 or a dash for the missing value.
 */
export interface VisibilityEngineStatus {
  provider: VisibilityProvider;
  label: string;
  live_measurement: string;
  live_unavailable_reason?: string | null;
  measurement_source: string;
  last_measured_at?: string | null;
  measured_on_plan?: boolean;
  /** `"not_measured_on_plan"` when the plan's roster excludes the engine. */
  plan_unavailable_reason?: string | null;
  unlocks_on_plan?: string | null;
  unlocks_on_plan_label?: string | null;
}

export interface VisibilityEntitlements {
  plan: string;
  // SIGV2-1142: the cap, the usage and the plan that raises the cap are served
  // by the API. Nothing client-side keeps its own copy of the plan ladder.
  plan_label?: string | null;
  upgrade_plan?: string | null;
  upgrade_plan_label?: string | null;
  upgrade_max_queries?: number | null;
  max_queries: number;
  used_queries: number;
  remaining_queries: number;
  allowed_providers: VisibilityProvider[];
  // SIGV2-1188: the plan's scheduled-measurement cadence. Optional so older
  // deployments that do not serve it still typecheck.
  //
  // SIGV2-1216: a plan may now sweep on an interval between daily and weekly
  // (Specialist runs every two days), and the backend names that interval
  // rather than rounding it down to "daily". The days are rounded up, so the
  // value never claims a measurement is fresher than it is.
  sweep_interval_seconds?: number;
  measurement_cadence?: "daily" | "weekly" | `every_${number}_days` | null;
  // SIGV2-1216: the per-engine roster, each row saying whether this plan
  // measures it. Optional so a payload from an older deployment typechecks.
  // SIGV2-1228: one row per OFFERED engine, on every plan, so the rows the
  // plan does not measure are marked rather than missing.
  engines?: VisibilityEngineStatus[];
  is_locked: boolean;
  estimated_cost_per_check: Record<string, number>;
}

/**
 * The five customer-facing search types, exactly as the backend defines them in
 * `CANONICAL_SEARCH_TYPES` (`backend/services/query_taxonomy.py`). Keep this
 * union equal to that list, never the reverse.
 */
export const SEARCH_TYPES = ["brand", "category", "problem", "feature", "comparison"] as const;

export type SearchTypeId = (typeof SEARCH_TYPES)[number];

/**
 * Where a prompt's search type came from (SIGV2-1186). `stored` means the
 * prompt carries the type as its own property, because the customer chose it or
 * it was written down at creation. `inferred` means the prompt predates the
 * stored column and the type shown is still the old text-based guess, which a
 * surface must not present as the customer's choice.
 */
export type SearchTypeSource = "stored" | "inferred";

/** Who wrote a prompt (SIGV2-1186). */
export type VisibilityQueryOrigin = "customer" | "generated";

export interface VisibilityQuery {
  id: number;
  project_id: number;
  query_text: string;
  query_type: "aeo" | "geo";
  // SIGV2-1186: the prompt's stored search type when it has one, the text-based
  // inference when it does not. `search_type_source` says which.
  search_type?: SearchTypeId | null;
  search_type_source?: SearchTypeSource | null;
  search_type_suggested?: SearchTypeId | null;
  origin?: VisibilityQueryOrigin | null;
  is_generated?: boolean;
  providers: VisibilityProvider[];
  // Engines the prompt names that the current plan roster does not measure.
  // A prompt left pinned to an engine the plan stopped measuring would
  // otherwise read as a live prompt that never updates.
  unmeasured_providers?: VisibilityProvider[];
  is_active: boolean;
  // SIGV2-1188: active but past the plan's prompt cap (post-downgrade). The
  // sweep skips it; it keeps its history and the UI marks it as unmeasured on
  // the current plan rather than silently dropping it.
  exceeds_plan_cap?: boolean;
  created_at: string | null;
  updated_at: string | null;
}

/**
 * One of the five search types and whether any active prompt covers it
 * (SIGV2-1186). Served with the prompt list, before a scan runs, so a gap is
 * something the customer can see and fill rather than an unexplained
 * "unmeasured" card afterwards. `suggested_prompt` is what the base-prompt
 * generator would write for an uncovered type, and null once it is covered.
 */
export interface SearchTypeCoverageEntry {
  id: SearchTypeId;
  label: string;
  premium: boolean;
  prompt_count: number;
  covered: boolean;
  suggested_prompt: string | null;
}

export interface ScoreBreakdown {
  citation_presence: number;
  citation_position: number;
  text_mention: number;
  topic_relevance: number;
}

export type VisibilityPresenceState =
  | "domain_citation"
  | "brand_mention"
  | "measured_absent"
  | "unmeasured";

export interface VisibilityPresence {
  state: VisibilityPresenceState;
  live_measured: boolean;
  reason: string | null;
}

export interface VisibilityProviderResult {
  provider: VisibilityProvider;
  status: VisibilityQueryStatus;
  batch_status: string | null;
  score: number | null;
  score_breakdown: ScoreBreakdown | null;
  last_checked_at: string | null;
  citations_found: number;
  presence?: VisibilityPresence | null;
  /**
   * Which panel produced the answer: `openrouter_live` is the named engine
   * itself, anything else is the stand-in Bedrock panel, and `mixed` is the
   * backend's marker for a cell whose runs disagree. Read through
   * `lib/visibilityProvenance`, never compared inline (SIGV2-1299).
   */
  engine_source?: string | null;
  /** Resolved model id behind the cell. Internal, never shown to a customer. */
  model?: string | null;
}

export interface VisibilityProviderBreakdown {
  provider: VisibilityProvider;
  tracked_queries: number;
  completed_checks: number;
  cited_checks: number;
  visibility_score: number | null;
}

export interface VisibilityQuerySummaryRow extends VisibilityQuery {
  average_score: number | null;
  last_checked_at: string | null;
  results: VisibilityProviderResult[];
}

export interface VisibilityQueryListResponse {
  project_id: number;
  entitlements: VisibilityEntitlements;
  queries: VisibilityQuery[];
  // SIGV2-1186: always five entries in canonical order, counting active
  // prompts only. Older deployments may omit it, hence optional.
  coverage?: SearchTypeCoverageEntry[];
}

/**
 * Result of asking Signal to fill the project's uncovered search types
 * (SIGV2-1186). `reason` is stated rather than implied by an empty `created`:
 * "created", "already_covered", "plan_locked", "cap_reached", "no_brand" or
 * "failed".
 */
export interface GenerateBasePromptsResponse {
  project_id: number;
  reason: string;
  created: VisibilityQuery[];
  coverage: SearchTypeCoverageEntry[];
  entitlements: VisibilityEntitlements;
}

export interface VisibilitySummaryResponse {
  project_id: number;
  entitlements: VisibilityEntitlements;
  queries_configured: number;
  providers: VisibilityProvider[];
  visibility_score: number | null;
  score_breakdown: ScoreBreakdown | null;
  trend_delta: number | null;
  completed_checks: number;
  pending_checks: number;
  cited_checks: number;
  total_checks: number;
  last_updated_at: string | null;
  provider_breakdown: VisibilityProviderBreakdown[];
  queries: VisibilityQuerySummaryRow[];
}

export interface VisibilityTrendPoint {
  date: string;
  visibility_score: number | null;
  completed_checks: number;
  cited_checks: number;
  providers: Record<string, number | null>;
}

export interface VisibilityTrendResponse {
  project_id: number;
  days: number;
  providers: VisibilityProvider[];
  points: VisibilityTrendPoint[];
}

export interface CreateVisibilityQueryPayload {
  query_text: string;
  query_type: "aeo" | "geo";
  providers: VisibilityProvider[];
  // SIGV2-1186: omit to accept the backend's text-based suggestion, which is
  // then stored on the row. An unrecognised value is a 422.
  search_type?: SearchTypeId;
}

export interface UpdateVisibilityQueryPayload {
  // SIGV2-1194: rewording the question is how a prompt the backend typed
  // wrong is corrected, and an edit marks the row as the customer's own.
  query_text?: string;
  query_type?: "aeo" | "geo";
  providers?: VisibilityProvider[];
  is_active?: boolean;
  // SIGV2-1186: how the customer corrects a type we got wrong.
  search_type?: SearchTypeId;
}

export interface VolatilityDomainDelta {
  domain: string;
  delta: number;
}

export interface VolatilityIndustryRow {
  industry: string;
  volatility_score: number | null;
  compared_queries: number;
  changed_ratio: number | null;
}

export interface VolatilitySummaryResponse {
  provider: string;
  generated_at: string;
  latest_snapshot_date: string | null;
  no_data: boolean;
  degraded: boolean;
  degraded_reasons: string[];
  weather_label: string;
  volatility_score: number | null;
  compared_queries: number;
  changed_ratio: number | null;
  avg_text_similarity: number | null;
  avg_citation_jaccard: number | null;
  citation_churn_rate: number | null;
  format_change_rate: number | null;
  top_winners: VolatilityDomainDelta[];
  top_losers: VolatilityDomainDelta[];
  industries: VolatilityIndustryRow[];
}

export interface VolatilityTrendPoint {
  date: string;
  volatility_score: number | null;
  compared_queries: number;
  changed_ratio: number | null;
}

export interface VolatilityTrendResponse {
  provider: string;
  days: number;
  points: VolatilityTrendPoint[];
}

export interface PublicVolatilityDashboardResponse {
  available_providers: string[];
  summary: VolatilitySummaryResponse;
  trends: VolatilityTrendResponse;
  industry_matrix: PublicVolatilityIndustryMatrixResponse;
  citation_ledger: PublicVolatilityCitationLedgerResponse;
}

export interface PublicVolatilityIndustryMatrixPoint {
  date: string;
  industry: string;
  provider: string;
  volatility_score: number | null;
  compared_queries: number;
  changed_ratio: number | null;
  moving_queries: string[];
}

export interface PublicVolatilityIndustryMatrixResponse {
  provider: string;
  days: number;
  points: PublicVolatilityIndustryMatrixPoint[];
}

export interface PublicVolatilityCitationLedgerRow {
  domain: string;
  industry: string;
  base_citations: number;
  current_citations: number;
  delta: number;
  delta_pct: number;
  provider: string;
  volatility_score: number | null;
  direction: "winner" | "loser";
  trend: number[];
}

export interface PublicVolatilityCitationLedgerResponse {
  provider: string;
  generated_at: string;
  latest_snapshot_date: string | null;
  rows: PublicVolatilityCitationLedgerRow[];
}

export interface OffPageMentionFeedItem {
  id: number;
  project_id: number;
  source_type: string;
  source_domain: string | null;
  mention_url: string | null;
  external_id: string | null;
  title: string | null;
  snippet: string;
  published_at: string | null;
  discovered_at: string | null;
  sentiment_label: "positive" | "neutral" | "negative" | "unknown";
  sentiment_score: number | null;
  linked_keywords: string[];
  entities: string[];
  authority_score: number;
  action_recommendation: string | null;
  analysis_status: string;
}

export interface OffPageMentionsTotals {
  total_mentions: number;
  positive_mentions: number;
  neutral_mentions: number;
  negative_mentions: number;
  unique_domains: number;
}

export interface OffPageMentionDomainSummary {
  domain: string;
  mentions: number;
  avg_authority_score: number;
  avg_sentiment_score: number;
}

export interface OffPageMentionAdvice {
  title: string;
  priority: string;
  source_domain: string;
  message: string;
  mention_url: string | null;
}

export interface OffPageMentionsSummaryResponse {
  project_id: number;
  generated_at: string;
  window_days: number;
  latest_snapshot_date: string | null;
  no_data: boolean;
  degraded: boolean;
  degraded_reasons: string[];
  off_page_aeo_score: number;
  trend_delta: number | null;
  totals: OffPageMentionsTotals;
  top_domains: OffPageMentionDomainSummary[];
  actionable_advice: OffPageMentionAdvice[];
  latest_mentions: OffPageMentionFeedItem[];
}

export interface OffPageMentionTrendPoint {
  date: string;
  off_page_aeo_score: number | null;
  total_mentions: number;
  positive_mentions: number;
  negative_mentions: number;
}

export interface OffPageMentionTrendResponse {
  project_id: number;
  days: number;
  points: OffPageMentionTrendPoint[];
}

// ---------------------------------------------------------------------------
// SERP tracking (target keywords) — GET monitoring/serp-tracking returns the
// latest dated snapshot per keyword only; there is no history endpoint, so a
// per-keyword position trend cannot be computed from this payload.
// ---------------------------------------------------------------------------

export interface SerpSnapshotItem {
  keyword: string;
  keyword_id: number;
  snapshot_date: string;
  owns_featured_snippet: boolean;
  featured_snippet_url: string | null;
  paa_appearances: Record<string, unknown>[];
  organic_position: number | null;
  serp_features_present: string[];
  ai_overview_detected: boolean;
  ai_overview_cites_target: boolean;
  ai_overview_source_urls?: string[] | null;
}

export interface SerpTrackingSummary {
  project_id: number;
  total_keywords: number;
  snippets_owned: number;
  snippets_gained: number;
  snippets_lost: number;
  paa_appearances_total: number;
  ai_overview_count: number;
  ai_overview_cited_count: number;
  latest_snapshots: SerpSnapshotItem[];
}

export interface TargetKeyword {
  id: number;
  keyword: string;
  search_engine: string;
  language_code: string;
  location_code: number | null;
  is_active: boolean;
  created_at: string;
}

// POST /projects/{id}/monitoring/keywords (TargetKeywordCreate). Everything
// except `keyword` has a server-side default, and the approved Keywords tab
// asks for the keyword only, so the dialog sends the keyword only.
export interface CreateTargetKeywordPayload {
  keyword: string;
  search_engine?: string;
  language_code?: string;
  location_code?: number | null;
}

// ---------------------------------------------------------------------------
// Search Console pages — docs/search-console-reporting-contract.md (SIGV2-1025).
// Sessions come from GA4, never from GSC clicks; `sessions_reason` names why a
// row has no sessions value. `opportunity` is the backend classification with
// its evidence attached — render it, never recompute it.
// ---------------------------------------------------------------------------

export type SearchConsoleOpportunityValue =
  | "striking_distance"
  | "low_ctr"
  | "insufficient_data"
  | "none";

export interface SearchConsoleOpportunity {
  value: SearchConsoleOpportunityValue;
  evidence: {
    weighted_position: number | null;
    impressions: number;
    ctr: number | null;
    band_median_ctr: number | null;
    min_impressions: number;
    incomplete: boolean;
  };
}

export interface SearchConsolePageRow {
  page_key: string;
  pages: string[];
  collapsed_count: number;
  clicks: number;
  impressions: number;
  ctr: number | null;
  avg_position: number | null;
  sessions: number | null;
  sessions_reason: "no_ga4_binding" | "ga4_unavailable" | "no_ga4_match" | null;
  incomplete: boolean;
  opportunity: SearchConsoleOpportunity;
}

export interface SearchConsolePagesPayload {
  property: string;
  window: string;
  start_date: string;
  end_date: string;
  date_basis: string;
  ga4_property_timezone: string | null;
  date_alignment: "exact" | "approximate";
  data_state: string;
  first_incomplete_date: string | null;
  response_aggregation_type: string | null;
  completeness: string;
  partial_reason: string | null;
  url_normalization: string;
  totals: {
    clicks: number;
    impressions: number;
    ctr: number | null;
    position: number | null;
  };
  pages: SearchConsolePageRow[];
  series: Record<string, unknown>[];
  fetched_at: string;
}

// The endpoint answers a stub {status, availability} when the project's GSC
// binding is disconnected, revoked or the provider errored.
export interface SearchConsolePagesStub {
  status: "disconnected" | "revoked" | "provider_error";
  availability: string;
  retry?: boolean;
}

export type SearchConsolePagesResponse = SearchConsolePagesPayload | SearchConsolePagesStub;

export const isSearchConsolePagesPayload = (
  r: SearchConsolePagesResponse | null
): r is SearchConsolePagesPayload =>
  r !== null && Array.isArray((r as SearchConsolePagesPayload).pages);

// ---------------------------------------------------------------------------
// Comparative (brand vs competitor) visibility
// ---------------------------------------------------------------------------

export interface ComparativeProviderStats {
  visibility_score: number;
  cited_count: number;
  total_checks: number;
}

export interface ComparativeTrendPoint {
  date: string;
  scores: Record<string, number>;
}

export interface ComparativeDomain {
  is_primary: boolean;
  label: string;
  providers: Partial<Record<VisibilityProvider, ComparativeProviderStats>>;
  trend: ComparativeTrendPoint[];
  share_of_voice: number | null;
  /**
   * When this domain's numbers were last measured. `null` means never, which
   * is not a zero and not "now" (SIGV2-1208).
   */
  last_measured_at: string | null;
}

export interface ComparativeVisibilityResponse {
  project_id: number;
  domains: Record<string, ComparativeDomain>;
  /** Freshest measurement across the non-primary domains only. */
  competitors_last_measured_at: string | null;
  /**
   * The plan's scheduled competitor cadence in seconds, or `null` where
   * competitor cells are measured on demand only. This is the yardstick a
   * reading is called overdue against.
   */
  competitor_sweep_interval_seconds: number | null;
  /**
   * The engines this project's plan measures (SIGV2-1216). The engine filter
   * on the chart is a fixed list client-side, so the roster has to travel with
   * the data or a tab outlives the measurement behind it. Optional so a
   * payload from an older deployment typechecks.
   */
  allowed_providers?: VisibilityProvider[];
}
