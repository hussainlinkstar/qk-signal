"""Monitoring API Router.

Provides endpoints for LLM traffic data, SERP tracking snapshots,
and target keyword management for the continuous monitoring platform.
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import models
from database import get_db
from auth.security import get_current_user_from_token as get_current_user
from services.project_bot_log_analyzer_service import (
    build_project_bot_log_summary,
    ingest_project_bot_log_upload,
    list_project_bot_log_sources,
    upsert_project_bot_log_source,
)
from services.base_prompt_service import build_coverage, ensure_base_prompts
from services.project_intelligence_service import require_project_capability_access
from services.ai_search_volatility_service import AISearchVolatilityService
from services.project_offpage_mentions_service import ProjectOffPageMentionsService
from services.project_visibility_service import ProjectVisibilityService
from services.target_keyword_limit_service import enforce_keyword_limit
from services.workspace_rbac import require_workspace_write_access, resolve_project_access

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/projects", tags=["Monitoring"])


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class LLMTrafficDataPoint(BaseModel):
    date: str
    source: str
    sessions: int
    users: Optional[int] = None
    page_views: Optional[int] = None
    avg_session_duration_seconds: Optional[float] = None
    bounce_rate: Optional[float] = None


class LLMTrafficResponse(BaseModel):
    project_id: int
    start_date: str
    end_date: str
    data: List[LLMTrafficDataPoint]
    total_sessions: int
    sources: List[str]


class SERPSnapshotItem(BaseModel):
    keyword: str
    keyword_id: int
    snapshot_date: str
    owns_featured_snippet: bool
    featured_snippet_url: Optional[str] = None
    paa_appearances: List[Dict[str, Any]] = []
    organic_position: Optional[int] = None
    serp_features_present: List[str] = []
    ai_overview_detected: bool = False
    ai_overview_cites_target: bool = False
    ai_overview_source_urls: Optional[List[str]] = None


class SERPTrackingSummary(BaseModel):
    project_id: int
    total_keywords: int
    snippets_owned: int
    snippets_gained: int
    snippets_lost: int
    paa_appearances_total: int
    ai_overview_count: int
    ai_overview_cited_count: int
    latest_snapshots: List[SERPSnapshotItem]


class TargetKeywordCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=500)
    search_engine: str = Field(default="google", max_length=20)
    language_code: str = Field(default="en", max_length=10)
    location_code: Optional[int] = None


class TargetKeywordResponse(BaseModel):
    id: int
    keyword: str
    search_engine: str
    language_code: str
    location_code: Optional[int]
    is_active: bool
    created_at: str


class VisibilityEngineStatusResponse(BaseModel):
    provider: str
    label: str
    live_measurement: str
    live_unavailable_reason: Optional[str] = None
    measurement_source: str
    # Null on a row this plan does not measure (SIGV2-1228). The run may exist;
    # its date beside an engine nothing is re-measuring would read as current.
    last_measured_at: Optional[str] = None
    # SIGV2-1216: whether this project's plan measures the engine, which is a
    # different fact from whether the product offers it and became visible the
    # first time a plan roster shrank. Defaulted to True so an older client
    # that ignores the field sees no behaviour change.
    measured_on_plan: bool = True
    # SIGV2-1228: every offered engine is still listed on every plan, so a row
    # the plan does not measure says why, and names the plan that does.
    plan_unavailable_reason: Optional[str] = None
    unlocks_on_plan: Optional[str] = None
    unlocks_on_plan_label: Optional[str] = None


class VisibilityEntitlementsResponse(BaseModel):
    plan: str
    # SIGV2-1142: a refusal has to state the cap, what is used, what remains,
    # and the plan that raises it. All four travel with the entitlement so no
    # client has to keep its own copy of the plan ladder.
    plan_label: Optional[str] = None
    upgrade_plan: Optional[str] = None
    upgrade_plan_label: Optional[str] = None
    upgrade_max_queries: Optional[int] = None
    max_queries: int
    used_queries: int = 0
    remaining_queries: int = 0
    allowed_providers: List[str] = Field(default_factory=list)
    # SIGV2-1188: the plan's scheduled-measurement cadence, so a surface can
    # say "re-measured daily" or "weekly" instead of implying one global value.
    sweep_interval_seconds: int = 0
    measurement_cadence: Optional[str] = None
    engines: List[VisibilityEngineStatusResponse] = Field(default_factory=list)
    is_locked: bool
    estimated_cost_per_check: Dict[str, int] = Field(default_factory=dict)
    measurement_note: str = (
        "API-model answers are not guaranteed identical to consumer chat apps "
        "with browsing or personalisation."
    )


class VisibilityQueryCreate(BaseModel):
    query_text: str = Field(min_length=1, max_length=500)
    query_type: str = Field(default="aeo", max_length=10)
    providers: List[str] = Field(default_factory=list)
    # SIGV2-1186: the prompt's customer-facing search type, stored on the row.
    # Omitted means "use the text-based suggestion", which is then written down
    # rather than re-derived on every read. An unrecognised value is a 422.
    search_type: Optional[str] = Field(default=None, max_length=20)


class VisibilityQueryUpdate(BaseModel):
    # SIGV2-1194: the wording of a tracked prompt is editable. Same bounds as
    # ``VisibilityQueryCreate.query_text``, so an edit cannot produce a row
    # creation would have refused. Omitted leaves the text untouched.
    query_text: Optional[str] = Field(default=None, min_length=1, max_length=500)
    query_type: Optional[str] = Field(default=None, max_length=10)
    providers: Optional[List[str]] = None
    is_active: Optional[bool] = None
    # SIGV2-1186: how the customer corrects a type we got wrong.
    search_type: Optional[str] = Field(default=None, max_length=20)


class VisibilityQueryResponse(BaseModel):
    id: int
    project_id: int
    query_text: str
    query_type: str
    # Canonical five-way search type (brand/category/problem/feature/
    # comparison). Serialised alongside query_type, which remains the internal
    # aeo/geo lane (SIGV2-1010, AC3).
    #
    # SIGV2-1186: the prompt's stored type when it has one, the text-based
    # inference when it does not. ``search_type_source`` is "stored" or
    # "inferred" so a surface never presents a guess as the customer's choice,
    # and ``search_type_suggested`` carries what the classifier would propose.
    search_type: Optional[str] = None
    search_type_source: Optional[str] = None
    search_type_suggested: Optional[str] = None
    # "customer" or "generated" (SIGV2-1186). Generated prompts are Signal's
    # base set and must be tellable from the customer's own.
    origin: Optional[str] = None
    is_generated: bool = False
    providers: List[str] = Field(default_factory=list)
    # Engines the prompt names that the current plan roster does not measure
    # (a prompt pinned to Gemini survives the Specialist roster change but is
    # never measured on it). The surface can name the dead engine instead of
    # showing a healthy-looking prompt that quietly never updates.
    unmeasured_providers: List[str] = Field(default_factory=list)
    is_active: bool
    # SIGV2-1188: active but past the plan's prompt cap (post-downgrade). The
    # sweep skips it, it keeps its history, and the UI marks it as unmeasured
    # on the current plan rather than silently dropping it.
    exceeds_plan_cap: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SearchTypeCoverageEntry(BaseModel):
    """One of the five search types, and whether any prompt covers it.

    SIGV2-1186: served before a scan runs, so a gap is something the customer
    can see and fill rather than an unexplained "unmeasured" card afterwards.
    ``suggested_prompt`` is the sentence the base-prompt generator would write
    for this type, and is ``None`` once the type is covered.
    """

    id: str
    label: str
    premium: bool = False
    prompt_count: int = 0
    covered: bool = False
    suggested_prompt: Optional[str] = None


class VisibilityQueryListResponse(BaseModel):
    project_id: int
    entitlements: VisibilityEntitlementsResponse
    queries: List[VisibilityQueryResponse] = Field(default_factory=list)
    # Always five entries, in canonical order, counting active prompts only.
    coverage: List[SearchTypeCoverageEntry] = Field(default_factory=list)


class GenerateBasePromptsResponse(BaseModel):
    project_id: int
    # Why nothing was created, when nothing was: "created", "already_covered",
    # "plan_locked", "cap_reached", "no_brand" or "failed". Stated rather than
    # returned as a silent empty list.
    reason: str
    created: List[VisibilityQueryResponse] = Field(default_factory=list)
    coverage: List[SearchTypeCoverageEntry] = Field(default_factory=list)
    entitlements: VisibilityEntitlementsResponse


class ScoreBreakdownResponse(BaseModel):
    citation_presence: float = 0.0
    citation_position: float = 0.0
    text_mention: float = 0.0
    topic_relevance: float = 0.0


class VisibilityPresenceResponse(BaseModel):
    # Named-engine presence derived only from successful matching evidence
    # (SIGV2-1010, AC4). `unmeasured` covers pending / failed / missing data
    # and is never a live-engine "no".
    state: str
    live_measured: bool = False
    reason: Optional[str] = None


class VisibilityRunEvidenceResponse(BaseModel):
    run_id: int
    prompt_template: str
    prompt: str
    status: str
    score: Optional[float] = None
    model: Optional[str] = None
    engine_source: Optional[str] = None
    served_from_cache: bool = False
    attempt: Optional[int] = None
    measured_at: Optional[str] = None
    # SIGV2-1313. One of live_measurement_disabled, plan_not_entitled,
    # engine_not_live_measurable, live_call_failed. Null when the run reached
    # the engine its provider slot names.
    fallback_reason: Optional[str] = None


class VisibilityEvidenceResponse(BaseModel):
    batch_id: int
    audit_job_id: Optional[str] = None
    schedule_key: Optional[str] = None
    # "scan" | "scheduled" | "queued" | "volatility" | "unknown"
    measurement_origin: str
    run_ids: List[int] = Field(default_factory=list)
    runs: List[VisibilityRunEvidenceResponse] = Field(default_factory=list)


class VisibilityProviderResultResponse(BaseModel):
    provider: str
    status: str
    batch_status: Optional[str] = None
    score: Optional[float] = None
    score_breakdown: Optional[ScoreBreakdownResponse] = None
    last_checked_at: Optional[str] = None
    citations_found: int = 0
    presence: Optional[VisibilityPresenceResponse] = None
    measurement_origin: Optional[str] = None
    audit_job_id: Optional[str] = None
    engine_source: Optional[str] = None
    model: Optional[str] = None
    evidence: Optional[VisibilityEvidenceResponse] = None


class VisibilityTopEngineResponse(BaseModel):
    provider: Optional[str] = None
    score: Optional[float] = None
    # Machine-readable reason when provider is null (e.g. tied_providers,
    # no_completed_measurements). Never an invented winner (AC5).
    reason: Optional[str] = None
    evidence: Optional[VisibilityEvidenceResponse] = None


class VisibilityPositionResponse(BaseModel):
    value: Optional[int] = None
    reason: Optional[str] = None


class VisibilityWhoWinsEntry(BaseModel):
    domain: str
    is_configured_competitor: bool = False
    citations: int = 0
    run_ids: List[int] = Field(default_factory=list)
    batch_ids: List[int] = Field(default_factory=list)


class VisibilityProviderBreakdownResponse(BaseModel):
    provider: str
    tracked_queries: int
    completed_checks: int
    cited_checks: int
    visibility_score: Optional[float] = None


class VisibilityQuerySummaryRowResponse(VisibilityQueryResponse):
    average_score: Optional[float] = None
    last_checked_at: Optional[str] = None
    results: List[VisibilityProviderResultResponse] = Field(default_factory=list)
    top_engine: Optional[VisibilityTopEngineResponse] = None
    position: Optional[VisibilityPositionResponse] = None
    who_wins: List[VisibilityWhoWinsEntry] = Field(default_factory=list)


class VisibilitySummaryResponse(BaseModel):
    project_id: int
    # The scan (audit job) this snapshot is scoped to, or null for the
    # default latest-measurement view (SIGV2-1010, AC2).
    audit_job_id: Optional[str] = None
    entitlements: VisibilityEntitlementsResponse
    queries_configured: int
    providers: List[str] = Field(default_factory=list)
    visibility_score: Optional[float] = None
    score_breakdown: Optional[ScoreBreakdownResponse] = None
    trend_delta: Optional[float] = None
    completed_checks: int
    pending_checks: int
    cited_checks: int
    total_checks: int
    last_updated_at: Optional[str] = None
    provider_breakdown: List[VisibilityProviderBreakdownResponse] = Field(default_factory=list)
    queries: List[VisibilityQuerySummaryRowResponse] = Field(default_factory=list)


class VisibilityTrendPointResponse(BaseModel):
    date: str
    visibility_score: Optional[float] = None
    completed_checks: int
    cited_checks: int
    providers: Dict[str, Optional[float]] = Field(default_factory=dict)


class VisibilityTrendResponse(BaseModel):
    project_id: int
    days: int
    providers: List[str] = Field(default_factory=list)
    points: List[VisibilityTrendPointResponse] = Field(default_factory=list)


class ComparativeProviderStatsResponse(BaseModel):
    visibility_score: float = 0.0
    cited_count: int = 0
    total_checks: int = 0


class ComparativeTrendPointResponse(BaseModel):
    date: str
    scores: Dict[str, float] = Field(default_factory=dict)


class ComparativeDomainResponse(BaseModel):
    is_primary: bool
    label: str
    providers: Dict[str, ComparativeProviderStatsResponse] = Field(default_factory=dict)
    trend: List[ComparativeTrendPointResponse] = Field(default_factory=list)
    share_of_voice: Optional[float] = None
    # SIGV2-1208: how old this domain's numbers are. ``None`` means never
    # measured, which a client must not render as a zero or as "now".
    last_measured_at: Optional[str] = None


class ComparativeVisibilityResponse(BaseModel):
    project_id: int
    domains: Dict[str, ComparativeDomainResponse] = Field(default_factory=dict)
    # SIGV2-1208: the freshest scheduled competitor measurement and the plan
    # cadence that paces it, so the surface can call a figure stale rather than
    # leaving the client to guess an expected refresh interval.
    competitors_last_measured_at: Optional[str] = None
    competitor_sweep_interval_seconds: Optional[int] = None
    # SIGV2-1216: the engines this project's plan measures. The chart's engine
    # filter is a fixed list client-side, so the roster has to travel with the
    # data or a tab outlives the measurement behind it.
    allowed_providers: List[str] = Field(default_factory=list)


class VolatilityDomainDeltaResponse(BaseModel):
    domain: str
    delta: int


class VolatilityIndustryRowResponse(BaseModel):
    industry: str
    volatility_score: Optional[float] = None
    compared_queries: int
    changed_ratio: Optional[float] = None


class VolatilitySummaryResponse(BaseModel):
    provider: str
    generated_at: str
    latest_snapshot_date: Optional[str] = None
    no_data: bool
    degraded: bool
    degraded_reasons: List[str] = Field(default_factory=list)
    weather_label: str
    volatility_score: Optional[float] = None
    compared_queries: int
    changed_ratio: Optional[float] = None
    avg_text_similarity: Optional[float] = None
    avg_citation_jaccard: Optional[float] = None
    citation_churn_rate: Optional[float] = None
    format_change_rate: Optional[float] = None
    top_winners: List[VolatilityDomainDeltaResponse] = Field(default_factory=list)
    top_losers: List[VolatilityDomainDeltaResponse] = Field(default_factory=list)
    industries: List[VolatilityIndustryRowResponse] = Field(default_factory=list)


class VolatilityTrendPointResponse(BaseModel):
    date: str
    volatility_score: Optional[float] = None
    compared_queries: int
    changed_ratio: Optional[float] = None


class VolatilityTrendResponse(BaseModel):
    provider: str
    days: int
    points: List[VolatilityTrendPointResponse] = Field(default_factory=list)


class BotLogIngestionSourceResponse(BaseModel):
    id: int
    source_type: str
    display_name: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool
    last_sync_at: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    updated_at: Optional[str] = None


class BotLogUploadDetailsResponse(BaseModel):
    id: int
    source_type: str
    filename: str
    status: str
    bytes_processed: int
    lines_processed: int
    bot_hits: int
    skipped_lines: int
    uploaded_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BotLogTotalsResponse(BaseModel):
    total_hits: int
    verified_hits: int
    spoofed_hits: int
    error_4xx_hits: int
    error_5xx_hits: int


class BotLogTimeSeriesPointResponse(BaseModel):
    date: str
    hits: int
    verified_hits: int
    spoofed_hits: int


class BotLogBreakdownRowResponse(BaseModel):
    bot_name: str
    hits: int
    verified_hits: int
    spoofed_hits: int
    error_4xx_hits: int
    error_5xx_hits: int


class BotLogSectionHeatmapRowResponse(BaseModel):
    section: str
    hits: int


class BotLogSpoofingRowResponse(BaseModel):
    bot_name: str
    spoofed_hits: int


class BotLogSummaryResponse(BaseModel):
    project_id: int
    generated_at: str
    window_days: int
    latest_snapshot_date: Optional[str] = None
    no_data: bool
    degraded: bool
    degraded_reasons: List[str] = Field(default_factory=list)
    totals: BotLogTotalsResponse
    time_series: List[BotLogTimeSeriesPointResponse] = Field(default_factory=list)
    bot_breakdown: List[BotLogBreakdownRowResponse] = Field(default_factory=list)
    section_heatmap: List[BotLogSectionHeatmapRowResponse] = Field(default_factory=list)
    spoofing_radar: List[BotLogSpoofingRowResponse] = Field(default_factory=list)
    ingestion_sources: List[BotLogIngestionSourceResponse] = Field(default_factory=list)
    latest_upload: Optional[BotLogUploadDetailsResponse] = None


class BotLogSourceListResponse(BaseModel):
    project_id: int
    items: List[BotLogIngestionSourceResponse] = Field(default_factory=list)


class BotLogSourceUpsertRequest(BaseModel):
    source_type: models.BotLogIngestionSourceType
    display_name: Optional[str] = Field(default=None, max_length=120)
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class BotLogUploadResponse(BaseModel):
    project_id: int
    upload_id: int
    status: str
    bytes_processed: int
    lines_processed: int
    bot_hits: int
    skipped_lines: int
    aggregate_rows: int
    summary_rows: int
    degraded: bool
    degraded_reasons: List[str] = Field(default_factory=list)


class OffPageMentionIngestItemRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    snippet: str = Field(min_length=1, max_length=8000)
    mention_url: Optional[str] = Field(default=None, max_length=2000)
    source_domain: Optional[str] = Field(default=None, max_length=255)
    external_id: Optional[str] = Field(default=None, max_length=255)
    published_at: Optional[str] = None
    sentiment_label: Optional[str] = Field(default=None, max_length=16)
    sentiment_score: Optional[float] = None
    linked_keywords: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    action_recommendation: Optional[str] = Field(default=None, max_length=1000)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class OffPageMentionsIngestRequest(BaseModel):
    source_type: str = Field(default="manual_import", max_length=80)
    mentions: List[OffPageMentionIngestItemRequest] = Field(min_length=1, max_length=100)
    run_analysis: bool = True
    skip_existing: bool = True


class OffPageMentionsIngestResponse(BaseModel):
    project_id: int
    ingested_mentions: int
    skipped_mentions: int
    analyzed_mentions: int
    degraded: bool
    degraded_reasons: List[str] = Field(default_factory=list)


class OffPageMentionFeedItemResponse(BaseModel):
    id: int
    project_id: int
    source_type: str
    source_domain: Optional[str] = None
    mention_url: Optional[str] = None
    external_id: Optional[str] = None
    title: Optional[str] = None
    snippet: str
    published_at: Optional[str] = None
    discovered_at: Optional[str] = None
    sentiment_label: str
    sentiment_score: Optional[float] = None
    linked_keywords: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    authority_score: float = 0.0
    action_recommendation: Optional[str] = None
    analysis_status: str
    link_state: str = "unknown"
    link_checked_at: Optional[str] = None
    link_evidence: Dict[str, Any] = Field(default_factory=dict)


class OffPageMentionsUnlinkedResponse(BaseModel):
    """Reclaimable-mention evidence list. `count` is derived from the same
    filtered, deduplicated set as `items`, so they reconcile. Only
    verified-unlinked publications appear; failed or unfetched pages stay
    `unknown` and are reported only in `states`."""

    project_id: int
    window_days: int
    count: int
    offset: int
    limit: int
    states: Dict[str, int] = Field(default_factory=dict)
    items: List[OffPageMentionFeedItemResponse] = Field(default_factory=list)


class OffPageMentionsLinkVerificationRequest(BaseModel):
    mention_ids: Optional[List[int]] = None
    limit: int = Field(default=50, ge=1, le=200)


class OffPageMentionsLinkVerificationResponse(BaseModel):
    project_id: int
    checked: int
    counts: Dict[str, int] = Field(default_factory=dict)
    items: List[OffPageMentionFeedItemResponse] = Field(default_factory=list)


class OffPageMentionsTotalsResponse(BaseModel):
    total_mentions: int
    positive_mentions: int
    neutral_mentions: int
    negative_mentions: int
    unique_domains: int


class OffPageMentionDomainSummaryResponse(BaseModel):
    domain: str
    mentions: int
    avg_authority_score: float
    avg_sentiment_score: float


class OffPageMentionAdviceResponse(BaseModel):
    title: str
    priority: str
    source_domain: str
    message: str
    mention_url: Optional[str] = None


class OffPageMentionsSummaryResponse(BaseModel):
    project_id: int
    generated_at: str
    window_days: int
    latest_snapshot_date: Optional[str] = None
    no_data: bool
    degraded: bool
    degraded_reasons: List[str] = Field(default_factory=list)
    off_page_aeo_score: float
    trend_delta: Optional[float] = None
    totals: OffPageMentionsTotalsResponse
    top_domains: List[OffPageMentionDomainSummaryResponse] = Field(default_factory=list)
    actionable_advice: List[OffPageMentionAdviceResponse] = Field(default_factory=list)
    latest_mentions: List[OffPageMentionFeedItemResponse] = Field(default_factory=list)


class OffPageMentionTrendPointResponse(BaseModel):
    date: str
    off_page_aeo_score: Optional[float] = None
    total_mentions: int = 0
    positive_mentions: int = 0
    negative_mentions: int = 0


class OffPageMentionTrendResponse(BaseModel):
    project_id: int
    days: int
    points: List[OffPageMentionTrendPointResponse] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Auth & access helpers
# ---------------------------------------------------------------------------


def _verify_project_access(project_id: int, user: models.User, db: Session) -> models.Project:
    """Verify the user has access to the project through workspace membership."""
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check workspace membership
    workspace = (
        db.query(models.Workspace).filter(models.Workspace.id == project.workspace_id).first()
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Owner always has access
    if workspace.owner_id == user.id:
        return project

    # Check workspace membership
    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == user.id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(status_code=403, detail="Access denied to this project")

    return project


# SIGV2-1221: the plan each of these states is derived from the capability it
# gates on, never typed in. These three all ride `api_access`, so if that
# capability ever moves plan the message moves with it instead of advertising a
# plan the backend stopped requiring.
def _require_bot_log_analyzer_access(user: models.User) -> None:
    require_project_capability_access(
        user,
        capability_key="api_access",
        subject="The LLM Bot Log Analyzer",
    )


def _require_off_page_mentions_access(user: models.User) -> None:
    require_project_capability_access(
        user,
        capability_key="api_access",
        subject="The Off-Page AEO Mentions Tracker",
    )


def _require_ai_search_volatility_access(user: models.User) -> None:
    require_project_capability_access(
        user,
        capability_key="api_access",
        subject="The AI Search Volatility Index",
    )


# ---------------------------------------------------------------------------
# LLM Traffic endpoints
# ---------------------------------------------------------------------------


@router.get("/{project_id}/monitoring/llm-traffic", response_model=LLMTrafficResponse)
def get_llm_traffic(
    project_id: int,
    months: int = Query(default=6, ge=1, le=24, description="Number of months to look back"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LLMTrafficResponse:
    """Get LLM referral traffic time series for a project."""
    _verify_project_access(project_id, user, db)

    end_date = date.today()
    ga4_source = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project_id,
            models.ProjectDataSource.source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            models.ProjectDataSource.is_active.is_(True),
        )
        .first()
    )
    if ga4_source is None:
        return LLMTrafficResponse(
            project_id=project_id,
            start_date=end_date.isoformat(),
            end_date=end_date.isoformat(),
            data=[],
            total_sessions=0,
            sources=[],
        )
    start_date = end_date - timedelta(days=months * 30)

    snapshots = (
        db.query(models.LLMTrafficSnapshot)
        .filter(
            models.LLMTrafficSnapshot.project_id == project_id,
            models.LLMTrafficSnapshot.snapshot_date >= start_date,
            models.LLMTrafficSnapshot.snapshot_date <= end_date,
        )
        .order_by(models.LLMTrafficSnapshot.snapshot_date.asc())
        .all()
    )

    data: list[LLMTrafficDataPoint] = []
    sources_set: set[str] = set()
    total_sessions = 0

    for snap in snapshots:
        sources_set.add(snap.source)
        total_sessions += snap.sessions
        data.append(
            LLMTrafficDataPoint(
                date=snap.snapshot_date.isoformat(),
                source=snap.source,
                sessions=snap.sessions,
                users=snap.users,
                page_views=snap.page_views,
                avg_session_duration_seconds=snap.avg_session_duration_seconds,
                bounce_rate=snap.bounce_rate,
            )
        )

    return LLMTrafficResponse(
        project_id=project_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        data=data,
        total_sessions=total_sessions,
        sources=sorted(sources_set),
    )


# ---------------------------------------------------------------------------
# Site traffic (GA4 reporting contract, docs/ga4-reporting-contract.md)
# ---------------------------------------------------------------------------


def _active_ga4_source(db: Session, project_id: int) -> Optional[models.ProjectDataSource]:
    return (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project_id,
            models.ProjectDataSource.source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            models.ProjectDataSource.is_active.is_(True),
        )
        .first()
    )


def _mark_source_status(
    db: Session,
    source: models.ProjectDataSource,
    *,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Record a retrieval outcome on the binding (contract section 6)."""
    source.last_status = status
    source.last_error = (error or "")[:500] or None
    if status in ("success", "fresh"):
        source.last_sync_at = datetime.now(timezone.utc)
    db.commit()


@router.get("/{project_id}/monitoring/site-traffic")
def get_site_traffic(
    project_id: int,
    window: str = Query(default="7D", description="Reporting window: 7D, 15D, 90D or 12M"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Site traffic for a project's bound GA4 property.

    Implements docs/ga4-reporting-contract.md. Reads run under the customer's
    own OAuth token; the availability status is always stated, never implied.
    """

    from app.services.geo.ga4_oauth_service import (
        GA4ConnectionError,
        GA4TokenRefreshError,
        ga4_access_token,
    )
    from app.services.geo.ga4_reporting_service import (
        GA4_REASON_INVALID_CREDENTIALS,
        GA4_REASON_PERMISSION_DENIED,
        GA4PermissionError,
        GA4RateLimitError,
        GA4ReportError,
        GA4ReportingService,
        REPORT_WINDOWS,
        fetch_site_traffic,
        normalize_ga4_property_id,
    )
    from app.services.geo.ga4_traffic_service import GA4AuthError

    # Tenant authorization is checked before any retrieval (contract 1).
    _verify_project_access(project_id, user, db)

    window_key = window.upper()
    # Contract 3: unsupported windows are rejected, not silently clamped.
    if window_key not in REPORT_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported window '{window}'. Supported: {sorted(REPORT_WINDOWS)}.",
        )

    source = _active_ga4_source(db, project_id)
    if source is None:
        return {"status": "disconnected", "availability": "disconnected"}

    property_id = normalize_ga4_property_id(source.source_id)
    if property_id is None:
        _mark_source_status(db, source, status="error", error="invalid_property_id")
        return {"status": "provider_error", "availability": "unavailable"}

    try:
        token = ga4_access_token(db, source)
    except GA4ConnectionError as exc:
        # SIGV2-1202: no OAuth grant at all is a disconnection, not a
        # revocation. A disconnect nulls the binding's FK (ON DELETE SET NULL),
        # so reporting "revoked" here told a customer who had just
        # disconnected - or had just reconnected a different account - that
        # their access was revoked and they must reconnect. That is the loop.
        _mark_source_status(db, source, status="disconnected", error=str(exc)[:200])
        return {"status": "disconnected", "availability": "disconnected"}
    except (GA4TokenRefreshError, GA4AuthError) as exc:
        # A grant that exists but can no longer produce a usable token is the
        # real revoked case.
        _mark_source_status(db, source, status="auth_error", error=str(exc)[:200])
        return {"status": "revoked", "availability": "unavailable"}

    persisted_timezone = None
    metadata = source.metadata_json if isinstance(source.metadata_json, dict) else {}
    persisted_timezone = metadata.get("ga4_time_zone")

    service = GA4ReportingService(access_token=token)
    try:
        payload, seen_timezone = fetch_site_traffic(
            service,
            property_id,
            window_key,
            persisted_timezone=persisted_timezone,
        )
    except GA4PermissionError as exc:
        # SIGV2-1202: 401 and 403 are reported as different states. A 403
        # means this Google account is refused, not that the grant is broken,
        # so the customer is told to choose a property this account can read
        # (or grant the missing scope) instead of being sent round the
        # reconnect loop again. The reason comes from the service's fixed
        # vocabulary, so no provider text reaches the response.
        if getattr(exc, "status_code", None) == 401 or (
            getattr(exc, "reason", None) == GA4_REASON_INVALID_CREDENTIALS
        ):
            _mark_source_status(db, source, status="auth_error", error=str(exc)[:200])
            return {"status": "revoked", "availability": "unavailable"}
        _mark_source_status(db, source, status="permission_denied", error=str(exc)[:200])
        return {
            "status": "permission_denied",
            "availability": "unavailable",
            "reason": getattr(exc, "reason", None) or GA4_REASON_PERMISSION_DENIED,
        }
    except GA4RateLimitError:
        _mark_source_status(db, source, status="error", error="rate_limited")
        return {"status": "provider_error", "availability": "unavailable"}
    except GA4ReportError as exc:
        _mark_source_status(db, source, status="error", error=str(exc)[:200])
        return {"status": "provider_error", "availability": "unavailable"}

    if seen_timezone and seen_timezone != persisted_timezone:
        updated = dict(metadata)
        updated["ga4_time_zone"] = seen_timezone
        source.metadata_json = updated

    _mark_source_status(db, source, status="success")
    return {"status": "ok", **payload}


@router.get("/{project_id}/monitoring/search-console/pages")
def get_search_console_pages(
    project_id: int,
    window: str = Query(default="7D", description="Reporting window: 7D, 15D, 90D or 12M"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Search Console Pages table for the project's bound GSC property.

    Implements docs/search-console-reporting-contract.md. Sessions come from
    GA4, never from GSC clicks.
    """
    from core.config import settings
    from app.services.geo.ga4_oauth_service import (
        GA4ConnectionError,
        GA4TokenRefreshError,
        ga4_access_token,
    )
    from app.services.geo.ga4_reporting_service import (
        GA4ReportingService,
        normalize_ga4_property_id,
    )
    from app.services.geo.ga4_traffic_service import GA4AuthError
    from app.services.gsc_reporting_service import (
        GSC_WINDOWS,
        GSCPermissionError,
        GSCRateLimitError,
        GSCReportError,
        GSCReportingService,
        build_pages_payload,
        compute_gsc_period,
        sessions_by_page_key,
        sync_search_analytics,
        stored_page_rows,
    )

    _verify_project_access(project_id, user, db)

    window_key = window.upper()
    if window_key not in GSC_WINDOWS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported window '{window}'. Supported: {sorted(GSC_WINDOWS)}.",
        )

    source = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project_id,
            models.ProjectDataSource.source_type
            == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            models.ProjectDataSource.is_active.is_(True),
        )
        .first()
    )
    if source is None:
        return {"status": "disconnected", "availability": "disconnected"}

    site_url = str(source.source_id or "").strip()
    if not site_url:
        _mark_source_status(db, source, status="error", error="missing_site_url")
        return {"status": "provider_error", "availability": "unavailable"}

    try:
        token = ga4_access_token(db, source)
    except (GA4ConnectionError, GA4TokenRefreshError, GA4AuthError) as exc:
        _mark_source_status(db, source, status="auth_error", error=str(exc)[:200])
        return {"status": "revoked", "availability": "unavailable"}

    start, end = compute_gsc_period(window_key)
    service = GSCReportingService(access_token=token)
    try:
        rows, meta = service.query_search_analytics(
            site_url,
            start_date=start,
            end_date=end,
            dimensions=["page", "date"],
            data_state="all",
        )
    except GSCPermissionError as exc:
        _mark_source_status(db, source, status="auth_error", error=str(exc)[:200])
        return {"status": "revoked", "availability": "unavailable"}
    except GSCRateLimitError:
        _mark_source_status(db, source, status="error", error="rate_limited")
        return {
            "status": "provider_error",
            "availability": "unavailable",
            "retry": True,
        }
    except GSCReportError as exc:
        _mark_source_status(db, source, status="error", error=str(exc)[:200])
        return {"status": "provider_error", "availability": "unavailable"}

    sync_search_analytics(db, project_id, site_url, rows)
    page_rows = stored_page_rows(db, project_id, site_url, start, end)

    # Sessions come from GA4 (contract 6): never GSC clicks. No authorized GA4
    # binding, or a GA4-side failure, leaves Sessions unavailable with a reason.
    ga4_sessions: Optional[dict[str, float]] = None
    ga4_timezone: Optional[str] = None
    sessions_reason = "no_ga4_binding"
    ga4_source = _active_ga4_source(db, project_id)
    if ga4_source is not None:
        ga4_metadata = (
            ga4_source.metadata_json if isinstance(ga4_source.metadata_json, dict) else {}
        )
        ga4_timezone = ga4_metadata.get("ga4_time_zone")
        sessions_reason = "ga4_unavailable"
        try:
            ga4_token = ga4_access_token(db, ga4_source)
            ga4_property = normalize_ga4_property_id(ga4_source.source_id)
            if ga4_property:
                ga4_service = GA4ReportingService(access_token=ga4_token)
                seen_tz = ga4_service.get_property_timezone(ga4_property)
                if seen_tz:
                    ga4_timezone = seen_tz
                ga4_rows, _flags = ga4_service.run_report(
                    ga4_property,
                    dimensions=["pagePath"],
                    metrics=["sessions"],
                    date_ranges=[{"startDate": start.isoformat(), "endDate": end.isoformat()}],
                )
                ga4_sessions = sessions_by_page_key(ga4_rows)
        except Exception as exc:
            logger.warning(
                "GA4 sessions join failed for project=%s: %s",
                project_id,
                type(exc).__name__,
            )

    payload = build_pages_payload(
        site_url=site_url,
        window_key=window_key,
        start=start,
        end=end,
        page_rows=page_rows,
        ga4_sessions_by_key=ga4_sessions,
        ga4_property_timezone=ga4_timezone,
        min_impressions=settings.GSC_OPPORTUNITY_MIN_IMPRESSIONS,
        query_meta=meta,
        data_state="all",
        sessions_unavailable_reason=sessions_reason,
    )

    _mark_source_status(
        db,
        source,
        status="fresh" if rows else "connected_no_data",
    )
    return {"status": "ok", **payload}


@router.get("/{project_id}/monitoring/bing-webmaster/metrics")
def get_bing_webmaster_metrics(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Bing Webmaster metrics for the project's bound site (SIGV2-1082).

    Implements docs/bing-webmaster-reporting-contract.md. Ingestion itself
    lives in ``sync_project_bing_source`` and also runs on the scheduled
    monitoring worker (SIGV2-1265), so this endpoint is a reader that happens
    to refresh rather than the only path that can ever fetch. Position is
    reported unavailable with a reason; the raw provider integers are
    persisted but never rendered as a position. Bing numbers stay a separate
    dataset from Search Console and are never merged.
    """
    from app.services.bing_webmaster_service import (
        covered_period,
        serialize_metric_row,
        stored_bing_rows,
        sync_project_bing_source,
    )

    _verify_project_access(project_id, user, db)

    source = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project_id,
            models.ProjectDataSource.source_type == models.ProjectDataSourceType.BING_WEBMASTER,
            models.ProjectDataSource.is_active.is_(True),
        )
        .first()
    )
    if source is None:
        return {"status": "disconnected", "availability": "disconnected"}

    result = sync_project_bing_source(db, source)
    if result.status != "ok":
        payload: Dict[str, Any] = {
            "status": result.status,
            "availability": result.availability,
        }
        if result.reason and result.status != "revoked":
            payload["reason"] = result.reason
        return payload

    site_url = str(result.site_url or "")
    stored = {
        dimension_type: [
            serialize_metric_row(row)
            for row in stored_bing_rows(db, project_id, site_url, dimension_type=dimension_type)
        ]
        for dimension_type in ("site", "query", "page")
    }

    return {
        "status": "ok",
        "provider": "bing_webmaster",
        "site_url": site_url,
        "period": covered_period(
            list(stored_bing_rows(db, project_id, site_url, dimension_type="site"))
        ),
        "position": {
            "status": "unavailable",
            "reason": "bing_position_scale_unverified",
        },
        "site": stored["site"],
        "queries": stored["query"],
        "pages": stored["page"],
    }


# ---------------------------------------------------------------------------
# SERP Tracking endpoints
# ---------------------------------------------------------------------------


@router.get("/{project_id}/monitoring/serp-tracking", response_model=SERPTrackingSummary)
def get_serp_tracking(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SERPTrackingSummary:
    """Get SERP tracking summary with snippet gained/lost analysis."""
    _verify_project_access(project_id, user, db)

    total_keywords = (
        db.query(models.TargetKeyword)
        .filter(
            models.TargetKeyword.project_id == project_id,
            models.TargetKeyword.is_active.is_(True),
        )
        .count()
    )

    # Get the latest snapshot per keyword
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    latest_snapshots_query = (
        db.query(models.SERPTrackingSnapshot)
        .join(models.TargetKeyword)
        .filter(
            models.SERPTrackingSnapshot.project_id == project_id,
            models.TargetKeyword.is_active.is_(True),
        )
        .order_by(models.SERPTrackingSnapshot.snapshot_date.desc())
        .all()
    )

    # Deduplicate to latest per keyword
    seen_keywords: set[int] = set()
    latest_snapshots: list[models.SERPTrackingSnapshot] = []
    for snap in latest_snapshots_query:
        if snap.keyword_id not in seen_keywords:
            seen_keywords.add(snap.keyword_id)
            latest_snapshots.append(snap)

    # Calculate snippet ownership
    snippets_owned = sum(1 for s in latest_snapshots if s.owns_featured_snippet)
    paa_total = sum(len(s.paa_appearances or []) for s in latest_snapshots)
    ai_overview_count = sum(
        1 for s in latest_snapshots if getattr(s, "ai_overview_detected", False)
    )
    ai_overview_cited_count = sum(
        1 for s in latest_snapshots if getattr(s, "ai_overview_cites_target", False)
    )

    # Gained/lost analysis: compare latest vs. previous month
    snippets_gained = 0
    snippets_lost = 0

    for snap in latest_snapshots:
        previous = (
            db.query(models.SERPTrackingSnapshot)
            .filter(
                models.SERPTrackingSnapshot.keyword_id == snap.keyword_id,
                models.SERPTrackingSnapshot.snapshot_date < snap.snapshot_date,
                models.SERPTrackingSnapshot.snapshot_date >= thirty_days_ago,
            )
            .order_by(models.SERPTrackingSnapshot.snapshot_date.desc())
            .first()
        )
        if previous:
            if snap.owns_featured_snippet and not previous.owns_featured_snippet:
                snippets_gained += 1
            elif not snap.owns_featured_snippet and previous.owns_featured_snippet:
                snippets_lost += 1

    # Build response items
    keyword_map: dict[int, str] = {}
    if latest_snapshots:
        keyword_ids = [s.keyword_id for s in latest_snapshots]
        keywords = (
            db.query(models.TargetKeyword).filter(models.TargetKeyword.id.in_(keyword_ids)).all()
        )
        keyword_map = {kw.id: kw.keyword for kw in keywords}

    items = [
        SERPSnapshotItem(
            keyword=keyword_map.get(s.keyword_id, ""),
            keyword_id=s.keyword_id,
            snapshot_date=s.snapshot_date.isoformat(),
            owns_featured_snippet=s.owns_featured_snippet,
            featured_snippet_url=s.featured_snippet_url,
            paa_appearances=s.paa_appearances or [],
            organic_position=s.organic_position,
            serp_features_present=s.serp_features_present or [],
            ai_overview_detected=getattr(s, "ai_overview_detected", False),
            ai_overview_cites_target=getattr(s, "ai_overview_cites_target", False),
            ai_overview_source_urls=getattr(s, "ai_overview_source_urls", None),
        )
        for s in latest_snapshots
    ]

    return SERPTrackingSummary(
        project_id=project_id,
        total_keywords=total_keywords,
        snippets_owned=snippets_owned,
        snippets_gained=snippets_gained,
        snippets_lost=snippets_lost,
        paa_appearances_total=paa_total,
        ai_overview_count=ai_overview_count,
        ai_overview_cited_count=ai_overview_cited_count,
        latest_snapshots=items,
    )


# ---------------------------------------------------------------------------
# Keyword management endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/{project_id}/monitoring/keywords",
    response_model=TargetKeywordResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_target_keyword(
    project_id: int,
    payload: TargetKeywordCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TargetKeywordResponse:
    """Add a target keyword for SERP tracking."""
    project = _verify_project_access(project_id, user, db)

    # Check for duplicate
    existing = (
        db.query(models.TargetKeyword)
        .filter(
            models.TargetKeyword.project_id == project_id,
            models.TargetKeyword.keyword == payload.keyword.strip(),
        )
        .first()
    )
    if existing:
        if not existing.is_active:
            # Reactivation puts the keyword back on the metered sync cycle, so
            # it is a new tracked keyword as far as the plan cap is concerned
            # (SIGV2-1150).
            enforce_keyword_limit(db, project)
            existing.is_active = True
            db.commit()
            db.refresh(existing)
            return _keyword_to_response(existing)
        raise HTTPException(status_code=409, detail="Keyword already exists for this project")

    enforce_keyword_limit(db, project)

    keyword = models.TargetKeyword(
        project_id=project_id,
        keyword=payload.keyword.strip(),
        search_engine=payload.search_engine,
        language_code=payload.language_code,
        location_code=payload.location_code,
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    return _keyword_to_response(keyword)


@router.get("/{project_id}/monitoring/keywords", response_model=list[TargetKeywordResponse])
def list_target_keywords(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TargetKeywordResponse]:
    """List all target keywords for a project."""
    _verify_project_access(project_id, user, db)

    keywords = (
        db.query(models.TargetKeyword)
        .filter(
            models.TargetKeyword.project_id == project_id,
            models.TargetKeyword.is_active.is_(True),
        )
        .order_by(models.TargetKeyword.created_at.asc())
        .all()
    )

    return [_keyword_to_response(kw) for kw in keywords]


@router.delete(
    "/{project_id}/monitoring/keywords/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_target_keyword(
    project_id: int,
    keyword_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Soft-delete a target keyword."""
    _verify_project_access(project_id, user, db)

    keyword = (
        db.query(models.TargetKeyword)
        .filter(
            models.TargetKeyword.id == keyword_id,
            models.TargetKeyword.project_id == project_id,
        )
        .first()
    )
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword not found")

    keyword.is_active = False
    db.commit()


@router.get(
    "/{project_id}/monitoring/visibility-queries",
    response_model=VisibilityQueryListResponse,
)
def list_visibility_queries(
    project_id: int,
    include_inactive: bool = Query(default=True),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisibilityQueryListResponse:
    """List configured visibility queries and plan entitlements for a project."""
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    entitlements = service.resolve_entitlements(project)
    active_queries = service.list_queries(project_id=project.id, include_inactive=False)
    entitlements["used_queries"] = len(active_queries)
    entitlements["remaining_queries"] = max(0, entitlements["max_queries"] - len(active_queries))

    queries = service.list_queries(project_id=project.id, include_inactive=include_inactive)
    # SIGV2-1188: a downgrade keeps every prompt and its history; the rows past
    # the cap are flagged so the surface can say they are not being measured
    # on the current plan instead of looking broken.
    measured_ids = service.measured_query_ids(project=project)
    return VisibilityQueryListResponse(
        project_id=project.id,
        entitlements=VisibilityEntitlementsResponse(**entitlements),
        queries=[
            VisibilityQueryResponse(
                **{
                    **service.serialize_query(query),
                    "exceeds_plan_cap": bool(query.is_active) and query.id not in measured_ids,
                }
            )
            for query in queries
        ],
        # SIGV2-1186: coverage of the five search types, served with the prompt
        # list so the surface that manages prompts can state the gaps before a
        # scan runs instead of after it.
        coverage=[
            SearchTypeCoverageEntry(**entry) for entry in build_coverage(db, project=project)
        ],
    )


@router.post(
    "/{project_id}/monitoring/visibility-queries/generate-base",
    response_model=GenerateBasePromptsResponse,
    status_code=status.HTTP_201_CREATED,
)
def generate_base_visibility_queries(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GenerateBasePromptsResponse:
    """Fill the project's uncovered search types with generated base prompts.

    SIGV2-1186. Idempotent and plan-bounded: a type that already has an active
    prompt is left alone, nothing is created past the plan's prompt cap, and
    every row written is stored with its explicit search type and
    ``origin="generated"`` so the customer can retype or delete it.

    This is the same operation project creation performs automatically; the
    endpoint exists for projects created before it, and for a customer filling
    a gap the coverage view has just shown them. 201 with ``reason`` explaining
    an empty ``created`` list, never a silent no-op.
    """
    project = _verify_project_access(project_id, user, db)
    result = ensure_base_prompts(db, project=project)

    service = ProjectVisibilityService(db)
    entitlements = service.resolve_entitlements(project)
    active_queries = service.list_queries(project_id=project.id, include_inactive=False)
    entitlements["used_queries"] = len(active_queries)
    entitlements["remaining_queries"] = max(0, entitlements["max_queries"] - len(active_queries))

    return GenerateBasePromptsResponse(
        project_id=project.id,
        reason=str(result.get("reason") or ""),
        created=[
            VisibilityQueryResponse(**service.serialize_query(query))
            for query in result.get("created") or []
        ],
        coverage=[SearchTypeCoverageEntry(**entry) for entry in result.get("coverage") or []],
        entitlements=VisibilityEntitlementsResponse(**entitlements),
    )


@router.post(
    "/{project_id}/monitoring/visibility-queries",
    response_model=VisibilityQueryResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_visibility_query(
    project_id: int,
    payload: VisibilityQueryCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisibilityQueryResponse:
    """Create a project-scoped AI visibility query."""
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    created = service.create_query(
        project=project,
        query_text=payload.query_text,
        query_type=payload.query_type,
        providers=payload.providers,
        search_type=payload.search_type,
    )
    return VisibilityQueryResponse(**service.serialize_query(created))


@router.patch(
    "/{project_id}/monitoring/visibility-queries/{query_id}",
    response_model=VisibilityQueryResponse,
)
def update_visibility_query(
    project_id: int,
    query_id: int,
    payload: VisibilityQueryUpdate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisibilityQueryResponse:
    """Update the wording, provider selection or activation state of a visibility query.

    SIGV2-1194: an edit to the wording applies to the whole project and to
    future scans only. Measurements already recorded against the old wording
    are left exactly as they are.
    """
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    updated = service.update_query(
        project=project,
        query_id=query_id,
        is_active=payload.is_active,
        providers=payload.providers,
        query_type=payload.query_type,
        search_type=payload.search_type,
        query_text=payload.query_text,
    )
    return VisibilityQueryResponse(**service.serialize_query(updated))


@router.delete(
    "/{project_id}/monitoring/visibility-queries/{query_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_visibility_query(
    project_id: int,
    query_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Delete a visibility query from the project."""
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    service.delete_query(project_id=project.id, query_id=query_id)


@router.get(
    "/{project_id}/monitoring/visibility-summary",
    response_model=VisibilitySummaryResponse,
)
def get_visibility_summary(
    project_id: int,
    audit_job_id: Optional[str] = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisibilitySummaryResponse:
    """Get aggregated AI visibility score, provider breakdown, and per-query statuses.

    With ``audit_job_id`` the per-query results are scoped to the batches that
    scan triggered; without it each cell is the latest measurement from any
    origin, explicitly identified per cell (SIGV2-1010, AC2).
    """
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    return VisibilitySummaryResponse(
        **service.build_summary(project=project, audit_job_id=audit_job_id)
    )


@router.get(
    "/{project_id}/monitoring/visibility-trends",
    response_model=VisibilityTrendResponse,
)
def get_visibility_trends(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VisibilityTrendResponse:
    """Get project-scoped AI visibility trend points."""
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    return VisibilityTrendResponse(**service.build_trends(project=project, days=days))


@router.get(
    "/{project_id}/monitoring/visibility-comparative",
    response_model=ComparativeVisibilityResponse,
)
def get_visibility_comparative(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ComparativeVisibilityResponse:
    """Brand vs competitor visibility comparison across AI engines."""
    require_project_capability_access(
        user,
        capability_key="has_competitor_analysis",
        subject="Competitor AI visibility comparison",
    )
    project = _verify_project_access(project_id, user, db)
    service = ProjectVisibilityService(db)
    summary = service.build_comparative_summary(project=project, days=days)
    trends = service.build_comparative_trends(project=project, days=days)

    # Merge summary + trends and compute share-of-voice
    merged_domains: dict[str, Any] = {}
    total_cited_all = 0
    domain_cited: dict[str, int] = {}

    for domain, s_data in summary.get("domains", {}).items():
        cited = sum(p.get("cited_count", 0) for p in s_data.get("providers", {}).values())
        domain_cited[domain] = cited
        total_cited_all += cited
        trend_data = trends.get("domains", {}).get(domain, {})
        merged_domains[domain] = {
            "is_primary": s_data["is_primary"],
            "label": s_data["label"],
            "providers": s_data.get("providers", {}),
            "trend": trend_data.get("trend", []),
            "share_of_voice": None,
            "last_measured_at": s_data.get("last_measured_at"),
        }

    # Include domains from trends that had no summary data
    for domain, t_data in trends.get("domains", {}).items():
        if domain not in merged_domains:
            merged_domains[domain] = {
                "is_primary": t_data.get("is_primary", False),
                "label": t_data.get("label", domain),
                "providers": {},
                "trend": t_data.get("trend", []),
                "share_of_voice": None,
                "last_measured_at": None,
            }

    # Compute share-of-voice
    if total_cited_all > 0:
        for domain in merged_domains:
            sov = round(domain_cited.get(domain, 0) / total_cited_all * 100, 1)
            merged_domains[domain]["share_of_voice"] = sov

    # SIGV2-1208: the competitor rows are the ones fed by the slower scheduled
    # cadence, so the headline freshness figure is theirs. The brand's own
    # fresher measurement must never stand in for it.
    competitor_measured = [
        data["last_measured_at"]
        for data in merged_domains.values()
        if not data["is_primary"] and data.get("last_measured_at")
    ]

    return ComparativeVisibilityResponse(
        project_id=project.id,
        domains=merged_domains,
        competitors_last_measured_at=max(competitor_measured) if competitor_measured else None,
        competitor_sweep_interval_seconds=summary.get("competitor_sweep_interval_seconds"),
        allowed_providers=list(summary.get("allowed_providers", [])),
    )


# ---------------------------------------------------------------------------
# AI search volatility index endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/monitoring/ai-search-volatility/summary",
    response_model=VolatilitySummaryResponse,
)
def get_ai_search_volatility_summary(
    project_id: int,
    provider: str = Query(default="all", max_length=50),
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VolatilitySummaryResponse:
    _require_ai_search_volatility_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    service = AISearchVolatilityService(db)
    service.ensure_default_seed_queries()
    payload = service.build_summary(days=days, provider=provider)
    return VolatilitySummaryResponse.model_validate(payload)


@router.get(
    "/{project_id}/monitoring/ai-search-volatility/trends",
    response_model=VolatilityTrendResponse,
)
def get_ai_search_volatility_trends(
    project_id: int,
    provider: str = Query(default="all", max_length=50),
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VolatilityTrendResponse:
    _require_ai_search_volatility_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    service = AISearchVolatilityService(db)
    service.ensure_default_seed_queries()
    payload = service.build_trends(days=days, provider=provider)
    return VolatilityTrendResponse.model_validate(payload)


# ---------------------------------------------------------------------------
# Off-page AEO mentions endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/monitoring/off-page-mentions/summary",
    response_model=OffPageMentionsSummaryResponse,
)
def get_off_page_mentions_summary(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OffPageMentionsSummaryResponse:
    _require_off_page_mentions_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    payload = ProjectOffPageMentionsService(db).build_summary(project=access.project, days=days)
    return OffPageMentionsSummaryResponse.model_validate(payload)


@router.get(
    "/{project_id}/monitoring/off-page-mentions/trends",
    response_model=OffPageMentionTrendResponse,
)
def get_off_page_mentions_trends(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OffPageMentionTrendResponse:
    _require_off_page_mentions_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    payload = ProjectOffPageMentionsService(db).build_trends(project_id=project_id, days=days)
    return OffPageMentionTrendResponse.model_validate(payload)


@router.get(
    "/{project_id}/monitoring/off-page-mentions/feed",
    response_model=List[OffPageMentionFeedItemResponse],
)
def list_off_page_mentions_feed(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    sentiment: Optional[str] = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> List[OffPageMentionFeedItemResponse]:
    _require_off_page_mentions_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    payload = ProjectOffPageMentionsService(db).list_feed(
        project_id=project_id,
        days=days,
        limit=limit,
        sentiment=sentiment,
    )
    return [OffPageMentionFeedItemResponse.model_validate(item) for item in payload]


@router.post(
    "/{project_id}/monitoring/off-page-mentions/ingest",
    response_model=OffPageMentionsIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_off_page_mentions(
    project_id: int,
    payload: OffPageMentionsIngestRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OffPageMentionsIngestResponse:
    _require_off_page_mentions_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    result = ProjectOffPageMentionsService(db).ingest_mentions(
        project=access.project,
        source_type=payload.source_type,
        mention_payloads=[item.model_dump() for item in payload.mentions],
        run_analysis=payload.run_analysis,
        skip_existing=payload.skip_existing,
    )
    return OffPageMentionsIngestResponse.model_validate(result)


@router.get(
    "/{project_id}/monitoring/off-page-mentions/unlinked",
    response_model=OffPageMentionsUnlinkedResponse,
)
def list_unlinked_off_page_mentions(
    project_id: int,
    days: int = Query(default=90, ge=7, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OffPageMentionsUnlinkedResponse:
    """Evidence-backed list of verified unlinked brand mentions (publications
    whose fetched page confirms the brand but carries no link to the target
    domain). Pages that failed or were never fetched stay `unknown` and are
    not counted as reclaimable."""
    _require_off_page_mentions_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    payload = ProjectOffPageMentionsService(db).list_unlinked_mentions(
        project_id=project_id,
        days=days,
        limit=limit,
        offset=offset,
    )
    return OffPageMentionsUnlinkedResponse.model_validate(payload)


@router.post(
    "/{project_id}/monitoring/off-page-mentions/verify-links",
    response_model=OffPageMentionsLinkVerificationResponse,
)
def verify_off_page_mention_links(
    project_id: int,
    payload: OffPageMentionsLinkVerificationRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OffPageMentionsLinkVerificationResponse:
    """Fetch mention source pages through the SSRF-safe outbound path and
    record a verified outbound-link-to-target state on each record. Unknown
    rows are checked first unless `mention_ids` is supplied."""
    _require_off_page_mentions_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    result = ProjectOffPageMentionsService(db).verify_project_mention_links(
        project=access.project,
        mention_ids=payload.mention_ids,
        limit=payload.limit,
    )
    return OffPageMentionsLinkVerificationResponse.model_validate(result)


# ---------------------------------------------------------------------------
# AI bot log analyzer endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{project_id}/monitoring/bot-logs/summary",
    response_model=BotLogSummaryResponse,
)
def get_bot_log_summary(
    project_id: int,
    days: int = Query(default=30, ge=7, le=365),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BotLogSummaryResponse:
    _require_bot_log_analyzer_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    payload = build_project_bot_log_summary(db, project_id=project_id, days=days)
    return BotLogSummaryResponse.model_validate(payload)


@router.get(
    "/{project_id}/monitoring/bot-logs/sources",
    response_model=BotLogSourceListResponse,
)
def list_bot_log_sources(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BotLogSourceListResponse:
    _require_bot_log_analyzer_access(user)
    resolve_project_access(db, user=user, project_id=project_id, allow_client_readonly=True)
    return BotLogSourceListResponse(
        project_id=project_id,
        items=[
            BotLogIngestionSourceResponse.model_validate(item)
            for item in list_project_bot_log_sources(db, project_id=project_id)
        ],
    )


@router.post(
    "/{project_id}/monitoring/bot-logs/sources",
    response_model=BotLogIngestionSourceResponse,
)
def upsert_bot_log_source(
    project_id: int,
    payload: BotLogSourceUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BotLogIngestionSourceResponse:
    _require_bot_log_analyzer_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)

    source = upsert_project_bot_log_source(
        db,
        project_id=project_id,
        source_type=payload.source_type,
        display_name=payload.display_name,
        config=payload.config,
        is_active=payload.is_active,
    )
    return BotLogIngestionSourceResponse.model_validate(source)


@router.post(
    "/{project_id}/monitoring/bot-logs/upload",
    response_model=BotLogUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_bot_log_file(
    project_id: int,
    file: UploadFile = File(...),
    source_type: models.BotLogIngestionSourceType = Query(
        default=models.BotLogIngestionSourceType.MANUAL_UPLOAD
    ),
    source_id: Optional[int] = Query(default=None, ge=1),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BotLogUploadResponse:
    _require_bot_log_analyzer_access(user)
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)

    normalized_source_type = source_type
    if source_id is not None:
        source_row = (
            db.query(models.ProjectBotLogSource)
            .filter(
                models.ProjectBotLogSource.id == source_id,
                models.ProjectBotLogSource.project_id == project_id,
            )
            .first()
        )
        if source_row is None:
            raise HTTPException(status_code=404, detail="Bot log ingestion source not found.")
        normalized_source_type = source_row.source_type

    if not str(file.filename or "").strip():
        raise HTTPException(status_code=400, detail="Uploaded file must include a filename.")

    result = ingest_project_bot_log_upload(
        db,
        project_id=project_id,
        upload_file=file,
        source_type=normalized_source_type,
        source_id=source_id,
    )
    return BotLogUploadResponse(
        project_id=project_id,
        upload_id=result.upload_id,
        status=result.status,
        bytes_processed=result.bytes_processed,
        lines_processed=result.lines_processed,
        bot_hits=result.bot_hits,
        skipped_lines=result.skipped_lines,
        aggregate_rows=result.aggregate_rows,
        summary_rows=result.summary_rows,
        degraded=result.degraded,
        degraded_reasons=result.degraded_reasons,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _keyword_to_response(kw: models.TargetKeyword) -> TargetKeywordResponse:
    created_at = kw.created_at
    if hasattr(created_at, "isoformat"):
        created_at_str = created_at.isoformat()
    else:
        created_at_str = str(created_at) if created_at else ""

    return TargetKeywordResponse(
        id=kw.id,
        keyword=kw.keyword,
        search_engine=kw.search_engine,
        language_code=kw.language_code,
        location_code=kw.location_code,
        is_active=kw.is_active,
        created_at=created_at_str,
    )
