from dataclasses import asdict
import asyncio
from datetime import datetime, timedelta, timezone
import logging
import os
import secrets
from typing import Annotated, Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from core.password_hashing import hash_password
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, text
from sqlalchemy.orm import Session
import json
import redis as sync_redis
import stripe

import models
from app.config.plans import (
    CAPABILITY_DESCRIPTIONS,
    CAPABILITY_MATRIX,
    PLAN_PRESENTATION,
    PUBLIC_PLAN_TYPES,
)
from app.services.billing_retention import (
    UNNAMED_INVOICE_CUSTOMER,
    anonymize_billing_payments_for_user,
    effective_retention_until,
    record_account_deletion_receipt,
    retention_until_for_invoice,
    snapshot_invoice_customer_identity,
)
from app.services.compliance.plan_validator import (
    capability_override_policy,
    describe_override_enforcement,
)
from auth.security import get_current_admin_user as get_current_user
from auth.token_verifier import get_current_staff_user
from billing import (
    CommitmentTier,
    Plan,
    is_billing_runtime_payload_meaningful,
    load_billing_config,
    normalize_billing_runtime_payload,
)
from cache_utils import build_audit_cache_key
from database import SessionLocal
from operational_settings import (
    ALLOWED_REPORT_RETENTION_DAYS,
    build_maintenance_notice,
    get_or_create_operational_settings,
    normalize_report_retention_days,
)
from score_utils import extract_score
from schemas.auth import normalize_company_name
from schemas.admin_billing import (
    AdminBillingCatalogSyncRequest,
    AdminBillingCatalogSyncResponse,
    AdminBillingCatalogValidateRequest,
    AdminBillingCatalogValidateResponse,
    AdminBillingCommitmentsOverviewResponse,
    AdminBillingCommitmentsResponse,
    AdminBillingConfigResponse,
    AdminBillingConfigUpdateRequest,
    AdminBillingInvoicesResponse,
    AdminBillingOverviewResponse,
    AdminBillingSubscriptionsResponse,
    AdminBillingSyncResponse,
)
from services.auth_service import AuthService
from services.admin_billing_helpers import (
    apply_catalog_sync_to_runtime,
    build_admin_billing_config_payload,
    calculate_subscription_mrr,
    ensure_billing_runtime_modes,
    mask_secret_tail,
    parse_stripe_timestamp,
    persist_billing_runtime_settings,
    resolve_billing_commitment_tier_key,
    resolve_billing_plan_key,
    resolve_workspace_billing,
    resolve_workspace_plan,
    runtime_payload_has_key,
    serialize_admin_commitment,
    serialize_catalog_sync_result,
    stripe_object_to_dict,
)
from services.benchmark_engine import BenchmarkEngine
from services.custom_domain_service import normalize_optional_text, normalize_optional_url
from services.ai_routing_policy import normalize_audit_tier
from core.pricing_matrix import canonicalize_model_name, get_token_pricing_for_model
from core.redis_client import get_async_redis, get_sync_redis_client
from services.cost_forecast_service import calculate_actual_audit_cost
from services.stripe_catalog_service import (
    sync_catalog as sync_stripe_catalog,
    validate_catalog as validate_stripe_catalog,
)
from services.signal_ingestion_service import SignalIngestionService
from services.debate_trace_service import debate_trace_service
from services.email_service import EmailService
from services.email_templates import (
    DEFAULT_PREVIEW_CONTEXT,
    TEMPLATE_DEFINITIONS,
    render_template as render_email_template,
)
from app.i18n import translate_backend_message

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


DEFAULT_TOKENS_PER_TIER = {
    "fast": 1200,
    "smart": 2400,
}


def _get_redis() -> sync_redis.Redis | None:
    return get_sync_redis_client()


SENSITIVE_METADATA_KEYS = {
    "token",
    "tokens",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "cookie",
    "session",
    "jwt",
    "access_token",
    "refresh_token",
    "private_key",
    "client_secret",
    "webhook_secret",
    "bearer",
}


def _sanitize_log_metadata(value: object) -> object:
    if isinstance(value, dict):
        sanitized: dict[str, object] = {}
        for key, nested_value in value.items():
            key_text = str(key)
            normalized_key = key_text.lower()
            if any(sensitive_key in normalized_key for sensitive_key in SENSITIVE_METADATA_KEYS):
                sanitized[key_text] = "[REDACTED]"
            else:
                sanitized[key_text] = _sanitize_log_metadata(nested_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_log_metadata(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_log_metadata(item) for item in value]
    return value


def _log_admin_action(
    db: Session,
    admin_user: models.User,
    action: str,
    target_type: str,
    target_id: int | str | None,
    metadata: dict[str, object] | None = None,
) -> None:
    metadata_payload = metadata or {}
    db.add(
        models.AdminActionLog(
            admin_user_id=admin_user.id if admin_user else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            metadata_json=_sanitize_log_metadata(metadata_payload),
        )
    )


class AdminMetricsResponse(BaseModel):
    monthly_recurring_revenue: float
    total_api_costs: float
    ai_cost_consumed_30d: float
    ai_cost_consumed_total: float
    avg_ai_cost_per_audit_30d: float
    net_profit_margin: float
    total_users: int
    active_subscriptions: int
    audits_last_30_days: int
    total_audits: int
    ai_cost_currency: Literal["USD"] = "USD"


class TokenUsageEntry(BaseModel):
    model: str
    tokens: int
    cost: float
    audits: int


class TokenUsageResponse(BaseModel):
    window_days: int
    total_tokens: int
    total_cost: float
    entries: list[TokenUsageEntry]
    currency: Literal["USD"] = "USD"


# ── Time-series analytics ───────────────────────────────────────


class TimeSeriesPoint(BaseModel):
    date: str
    value: float


class PeriodSummary(BaseModel):
    current: float
    previous_period: float
    change_pct: float | None = None


class MetricsTimeSeriesResponse(BaseModel):
    period: str
    series: dict[str, list[TimeSeriesPoint]]
    summary: dict[str, PeriodSummary]


class AdminUserEntry(BaseModel):
    id: int
    email: str
    role: str
    credits: int
    notifications_enabled: bool
    plan: str
    subscription_status: str | None
    audit_count: int


class AdminUsersResponse(BaseModel):
    users: list[AdminUserEntry]
    page: int
    page_size: int
    total: int


class AdminUserAuditSummary(BaseModel):
    total: int
    last_audit_at: datetime | None
    last_audit_url: str | None


class AdminUserSubscriptionSummary(BaseModel):
    plan: str
    status: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool | None
    stripe_customer_id: str | None
    stripe_subscription_id: str | None


class AdminUserDetailResponse(BaseModel):
    user: AdminUserEntry
    audit_summary: AdminUserAuditSummary
    subscription_summary: AdminUserSubscriptionSummary


class AdminUserUpdateRequest(BaseModel):
    role: str | None = None
    credits: int | None = None
    notifications_enabled: bool | None = None
    plan: str | None = None
    plan_type: str | None = None


class AdminUserCreditsRequest(BaseModel):
    delta: int
    reason: str


class AdminUserMutationResponse(BaseModel):
    user: AdminUserEntry


class AdminInviteUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    # name persists into User.company_name; the shared rule caps it at 120.
    name: str | None = None
    role: str = Field(default="user")

    @field_validator("name", mode="before")
    @classmethod
    def normalize_invited_name(cls, value: str | None) -> str | None:
        return normalize_company_name(value)


class AdminInviteUserResponse(BaseModel):
    user_id: int
    email: str
    role: str
    invited: bool
    email_queued: bool
    invitation_url: str | None = None


class AdminIntegrationStatusEntry(BaseModel):
    key: str
    name: str
    status: str
    note: str
    admin_note: str = ""
    action_required: bool = False
    last_checked_at: str | None = None


class AdminApiKeyStatusEntry(BaseModel):
    key: str
    label: str
    env_var: str
    configured: bool
    required: bool
    status: str
    source: str
    last_four: str | None
    note: str = ""
    owner: str | None = None
    rotation_days: int | None = None
    usage: str | None = None
    recommended_action: str | None = None
    action_required: bool = False
    last_checked_at: str | None = None


class AdminSecurityCheckEntry(BaseModel):
    key: str
    label: str
    status: str
    details: str
    action_required: bool = False


class AdminSettingsSummary(BaseModel):
    total_integrations: int
    connected_integrations: int
    degraded_integrations: int
    missing_integrations: int
    disabled_integrations: int
    total_api_keys: int
    configured_api_keys: int
    missing_required_api_keys: int
    placeholder_api_keys: int
    open_security_issues: int
    generated_at: str


class AdminEmailFooterDefaults(BaseModel):
    social_facebook_url: str | None = None
    social_x_url: str | None = None
    social_instagram_url: str | None = None
    social_linkedin_url: str | None = None
    social_youtube_url: str | None = None
    social_tiktok_url: str | None = None
    company_address: str | None = None
    company_legal_name: str | None = None
    company_trademark_text: str | None = None
    footer_about_url: str | None = None
    footer_blog_url: str | None = None
    footer_support_url: str | None = None
    footer_legal_url: str | None = None
    footer_preferences_url: str | None = None
    footer_privacy_url: str | None = None
    brand_primary_color: str | None = None
    brand_secondary_color: str | None = None
    logo_light_url: str | None = None
    logo_dark_url: str | None = None


class AdminCurrencyPolicy(BaseModel):
    display_currency: Literal["USD"] = "USD"


class AdminCurrencyPolicyPatch(BaseModel):
    display_currency: Literal["USD"] = "USD"


class AdminSettingsResponse(BaseModel):
    integrations: list[AdminIntegrationStatusEntry]
    api_keys: list[AdminApiKeyStatusEntry]
    security_checks: list[AdminSecurityCheckEntry] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    email_footer_defaults: AdminEmailFooterDefaults
    currency_policy: AdminCurrencyPolicy
    summary: AdminSettingsSummary


class AdminIntegrationStatusPatch(BaseModel):
    key: str | None = None
    name: str | None = None
    note: str = ""


class AdminApiKeyStatusPatch(BaseModel):
    key: str | None = None
    label: str | None = None
    note: str = ""
    owner: str | None = None
    rotation_days: int | None = Field(default=None, ge=7, le=3650)


class AdminSettingsPatchRequest(BaseModel):
    integrations: list[AdminIntegrationStatusPatch] | None = None
    api_keys: list[AdminApiKeyStatusPatch] | None = None
    email_footer_defaults: AdminEmailFooterDefaults | None = None
    currency_policy: AdminCurrencyPolicyPatch | None = None


class OperationStatus(BaseModel):
    fallback_model_enabled: bool
    pricing_v2_enabled: bool
    credit_engine_v2_enabled: bool
    pricing_v2_shadow_mode: bool
    pricing_v3_shadow_mode: bool
    cache_refresh_requested_at: str | None
    report_retention_days: int


class FallbackToggleRequest(BaseModel):
    enabled: bool


class ReportRetentionUpdateRequest(BaseModel):
    days: int = Field(..., description="Retention in days. Allowed values: 30, 60, 90.")


class PricingV2FlagsUpdateRequest(BaseModel):
    pricing_v2_enabled: bool | None = None
    credit_engine_v2_enabled: bool | None = None
    pricing_v2_shadow_mode: bool | None = None
    pricing_v3_shadow_mode: bool | None = None


class CacheMetadataResponse(BaseModel):
    url: str
    provider: str
    tier: str
    cached_at: str | None
    content_hash: str | None
    etag: str | None
    last_modified: str | None
    audit_id: int | None = None


class CacheRefreshRequest(BaseModel):
    clear_all: bool = False
    url: str | None = None
    provider: str | None = None
    tier: str | None = None


class CacheRefreshResponse(BaseModel):
    deleted_keys: int
    mode: str


class DataRetentionCleanupResponse(BaseModel):
    audits_deleted: int
    screenshots_redacted: int
    retention_days: int | None
    strip_screenshots_after_days: int | None
    executed_at: str


class SignalWarehouseHealthResponse(BaseModel):
    total_signal_audit_snapshots: int
    total_signal_citation_events: int
    total_signal_entity_observations: int
    total_signal_remediation_outcomes: int
    total_benchmark_cohort_aggregates: int
    total_proprietary_scores: int
    historical_project_audits: int
    audits_with_signal_snapshots: int
    backfill_coverage_pct: float
    last_ingested_at: str | None


class SignalWarehouseBackfillRequest(BaseModel):
    dry_run: bool = False


class SignalWarehouseBackfillResponse(BaseModel):
    job_id: str
    status: str
    dry_run: bool
    audits_processed: int
    batches_processed: int
    rows_inserted: int
    cohort_rows_written: int
    errors: list[str] = Field(default_factory=list)


class AdminAuditEntry(BaseModel):
    id: int
    user_id: int
    user_email: str
    url: str
    audit_target_type: str | None = None
    target_name: str | None = None
    target_url: str | None = None
    geo_score: float
    seo_score: float
    aeo_score: float
    provider: str | None
    tier: str | None
    requested_tier: str | None = None
    grounding_profile: str | None = None
    dual_track_grounding_enabled: bool = False
    fallback_reason: str | None = None
    track_a_claim_count: int | None = None
    track_b_claim_count: int | None = None
    dual_track_rollout_mode: str | None = None
    dual_track_execution_mode: str | None = None
    created_at: str
    sanitized_at: str | None
    has_screenshot: bool


class AdminAuditListResponse(BaseModel):
    audits: list[AdminAuditEntry]
    page: int
    page_size: int
    total: int


class AdminAuditDetailResponse(BaseModel):
    id: int
    user_id: int
    user_email: str
    url: str
    audit_target_type: str | None = None
    target_name: str | None = None
    target_url: str | None = None
    geo_score: float
    seo_score: float
    aeo_score: float
    provider: str | None
    tier: str | None
    requested_tier: str | None = None
    grounding_profile: str | None = None
    dual_track_grounding_enabled: bool = False
    fallback_reason: str | None = None
    track_a_claim_count: int | None = None
    track_b_claim_count: int | None = None
    dual_track_rollout_mode: str | None = None
    dual_track_execution_mode: str | None = None
    subscription_type: str | None
    credits_used: int | None
    credits_remaining: int
    created_at: str
    sanitized_at: str | None
    full_report: dict | None
    has_screenshot: bool


class AdminAuditSanitizeResponse(BaseModel):
    id: int
    sanitized_at: str | None
    screenshot_removed: bool


class DebateTraceTimelineEntry(BaseModel):
    agent_role: str
    provider: str
    model: str
    status: str
    latency_ms: int
    cost_usd: float | None = None
    input_chars: int
    output_preview: str
    claim_count: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error_message: str | None = None


class DebateTraceLayerResponse(BaseModel):
    layer: int
    name: str
    parallel: bool
    traces: list[DebateTraceTimelineEntry]


class DebateTraceResponse(BaseModel):
    audit_id: int
    pipeline_type: str
    total_agents: int
    total_latency_ms: int
    total_cost_usd: float
    layers: list[DebateTraceLayerResponse]


class DebateTraceOutputResponse(BaseModel):
    audit_id: int
    agent_role: str
    agent_layer: int
    pipeline_type: str
    provider: str
    model: str
    status: str
    latency_ms: int
    cost_usd: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    input_payload_hash: str
    input_payload_chars: int
    input_summary: str | None = None
    input_payload: Any | None = None
    output_raw: Any | None = None
    output_claim_ledger: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: str | None = None


class DebateTraceJourneyStepResponse(BaseModel):
    layer: int
    agent: str
    provider: str
    model: str
    status: str
    action: str
    confidence: float | None = None
    new_confidence: float | None = None
    critique: str | None = None
    severity: str | None = None
    suggested_disposition: str | None = None
    disposition: str | None = None
    critique_reference: str | None = None
    recommended_action: str | None = None


class DebateTraceClaimJourneyResponse(BaseModel):
    audit_id: int
    claim_id: str
    claim_text: str | None = None
    claim_domain: str | None = None
    journey: list[DebateTraceJourneyStepResponse]


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_token_usage_from_audit(audit: models.Audit) -> tuple[str, int]:
    report = audit.full_report or {}
    metadata = report.get("metadata", {}) if isinstance(report, dict) else {}
    model_name = metadata.get("model") or metadata.get("provider") or "unknown"
    tokens = metadata.get("token_usage")
    if isinstance(tokens, dict):
        tokens_value = tokens.get("total") or tokens.get("tokens")
        if isinstance(tokens_value, (int, float)):
            return model_name, int(tokens_value)
    if isinstance(tokens, (int, float)):
        return model_name, int(tokens)
    estimated_tokens = metadata.get("estimated_tokens")
    if isinstance(estimated_tokens, (int, float)):
        return model_name, int(estimated_tokens)
    tier = metadata.get("tier")
    if isinstance(tier, str) and tier in DEFAULT_TOKENS_PER_TIER:
        return model_name, DEFAULT_TOKENS_PER_TIER[tier]
    return model_name, DEFAULT_TOKENS_PER_TIER["fast"]


def _estimate_cost(model: str, tokens: int) -> float:
    """Estimate provider token spend in USD for a given model and total token count.

    Uses the canonical pricing matrix from core.pricing_matrix.
    Assumes a 50/50 split between input and output tokens when only
    a total count is available. This is a legacy fallback used only
    when neither the AI economics ledger nor persisted audit usage
    metadata can provide a more precise breakdown.
    """
    pricing = get_token_pricing_for_model(model)
    avg_rate_per_million = (float(pricing["input"]) + float(pricing["output"])) / 2
    return round((tokens / 1_000_000) * avg_rate_per_million, 4)


def _coerce_admin_cost_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _coerce_admin_cost_float(value: object) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _normalize_admin_cost_step(
    step: dict[str, Any] | None,
    *,
    fallback_model: str | None = None,
    fx_snapshot: dict[str, Any] | None = None,
) -> dict[str, float | int | str] | None:
    if not isinstance(step, dict):
        return None

    usage = step.get("token_usage") if isinstance(step.get("token_usage"), dict) else {}
    prompt_tokens = _coerce_admin_cost_int(
        step.get("input_tokens")
        or step.get("prompt_tokens")
        or usage.get("prompt_tokens")
        or usage.get("input_tokens")
    )
    completion_tokens = _coerce_admin_cost_int(
        step.get("output_tokens")
        or step.get("completion_tokens")
        or usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("candidates_token_count")
    )
    total_tokens = _coerce_admin_cost_int(step.get("total_tokens") or usage.get("total_tokens"))
    if total_tokens <= 0:
        total_tokens = prompt_tokens + completion_tokens

    cost_usd = _coerce_admin_cost_float(
        step.get("actual_cost_usd") or step.get("estimated_cost_usd") or step.get("token_cost_usd")
    )
    if total_tokens <= 0 and cost_usd <= 0:
        return None

    model_name = canonicalize_model_name(step.get("model") or fallback_model) or "unknown"
    return {
        "model": model_name,
        "tokens": total_tokens,
        "cost_usd": round(cost_usd, 6),
    }


def _aggregate_admin_model_entries(
    entries: list[dict[str, float | int | str]] | None,
) -> list[dict[str, float | int | str]]:
    totals: dict[str, dict[str, float | int | str]] = {}
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        model_name = canonicalize_model_name(item.get("model")) or "unknown"
        entry = totals.setdefault(
            model_name,
            {
                "model": model_name,
                "tokens": 0,
                "cost_usd": 0.0,
            },
        )
        entry["tokens"] = int(entry["tokens"]) + _coerce_admin_cost_int(item.get("tokens"))
        entry["cost_usd"] = float(entry["cost_usd"]) + _coerce_admin_cost_float(
            item.get("cost_usd")
        )

    return [
        {
            "model": model_name,
            "tokens": int(data["tokens"]),
            "cost_usd": round(float(data["cost_usd"]), 6),
        }
        for model_name, data in sorted(
            totals.items(),
            key=lambda item: float(item[1]["cost_usd"]),
            reverse=True,
        )
    ]


def _build_admin_ledger_request_index(
    db: Session,
    *,
    request_ids: set[str],
    default_fx_snapshot: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if not request_ids:
        return {}

    rows = (
        db.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.request_id.in_(sorted(request_ids)))
        .all()
    )

    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        request_id = str(row.request_id or "").strip()
        if not request_id:
            continue

        entry = index.setdefault(
            request_id,
            {
                "total_tokens": 0,
                "token_cost_usd": 0.0,
                "real_cost_usd": 0.0,
                "model": None,
                "steps": [],
                "has_canonical_costs": False,
            },
        )
        entry["total_tokens"] += _coerce_admin_cost_int(row.total_tokens)
        entry["real_cost_usd"] += _coerce_admin_cost_float(row.real_cost_usd)

        row_model = canonicalize_model_name(row.model)
        if row_model and not entry["model"]:
            entry["model"] = row_model

        payload = row.payload_json if isinstance(row.payload_json, dict) else {}
        row_fx = {}
        row_token_cost_usd = _coerce_admin_cost_float(
            payload.get("token_cost_usd") or payload.get("actual_token_cost_usd")
        )
        if row_token_cost_usd > 0:
            entry["token_cost_usd"] += row_token_cost_usd
            entry["has_canonical_costs"] = True
        elif _coerce_admin_cost_float(row.token_cost_usd) > 0:
            entry["token_cost_usd"] += _coerce_admin_cost_float(row.token_cost_usd)
            entry["has_canonical_costs"] = True
        actual_steps = (
            payload.get("actual_steps") if isinstance(payload.get("actual_steps"), list) else []
        )
        for step in actual_steps:
            normalized_step = _normalize_admin_cost_step(
                step,
                fallback_model=row_model,
                fx_snapshot=row_fx,
            )
            if normalized_step is not None:
                entry["steps"].append(normalized_step)

    return index


def _build_admin_actual_cost_fallback(
    audit: models.Audit,
    *,
    default_fx_snapshot: dict[str, Any],
) -> dict[str, Any] | None:
    report = audit.full_report if isinstance(audit.full_report, dict) else None
    actual_cost = calculate_actual_audit_cost(
        report=report,
        policy_version=None,
        feature_key="audit.main",
    )
    total_tokens = _coerce_admin_cost_int(actual_cost.total_tokens)
    total_cost_usd = _coerce_admin_cost_float(actual_cost.total_cogs_usd)
    token_cost_usd = _coerce_admin_cost_float(actual_cost.token_cost_usd)

    steps_payload = actual_cost.breakdown if isinstance(actual_cost.breakdown, dict) else {}
    raw_steps = steps_payload.get("steps") if isinstance(steps_payload.get("steps"), list) else []
    step_entries = _aggregate_admin_model_entries(
        [
            normalized_step
            for normalized_step in (
                _normalize_admin_cost_step(
                    step,
                    fallback_model=actual_cost.model,
                    fx_snapshot=default_fx_snapshot,
                )
                for step in raw_steps
            )
            if normalized_step is not None
        ]
    )

    if total_tokens <= 0 and total_cost_usd <= 0 and token_cost_usd <= 0 and not step_entries:
        return None

    if not step_entries:
        model_name = canonicalize_model_name(actual_cost.model) or "unknown"
        step_entries = [
            {
                "model": model_name,
                "tokens": total_tokens,
                "cost_usd": round(token_cost_usd, 6),
            }
        ]

    return {
        "total_tokens": total_tokens,
        "token_cost_usd": round(token_cost_usd, 6),
        "real_cost_usd": round(total_cost_usd, 6),
        "model": str(actual_cost.model or "").strip() or None,
        "steps": step_entries,
        "has_canonical_costs": token_cost_usd > 0,
    }


def _resolve_admin_audit_economics(
    audit: models.Audit,
    *,
    ledger_entry: dict[str, Any] | None,
    default_fx_snapshot: dict[str, Any],
) -> dict[str, Any]:
    fallback_model, fallback_tokens = _get_token_usage_from_audit(audit)
    actual_fallback = _build_admin_actual_cost_fallback(
        audit,
        default_fx_snapshot=default_fx_snapshot,
    )

    ledger_total_tokens = _coerce_admin_cost_int((ledger_entry or {}).get("total_tokens"))
    ledger_token_cost_usd = _coerce_admin_cost_float((ledger_entry or {}).get("token_cost_usd"))
    ledger_real_cost = _coerce_admin_cost_float((ledger_entry or {}).get("real_cost_usd"))
    ledger_has_canonical_costs = bool((ledger_entry or {}).get("has_canonical_costs"))
    ledger_model_entries = _aggregate_admin_model_entries(
        (ledger_entry or {}).get("steps")
        if isinstance((ledger_entry or {}).get("steps"), list)
        else []
    )
    actual_total_tokens = _coerce_admin_cost_int((actual_fallback or {}).get("total_tokens"))
    actual_token_cost_usd = _coerce_admin_cost_float((actual_fallback or {}).get("token_cost_usd"))
    actual_real_cost_usd = _coerce_admin_cost_float((actual_fallback or {}).get("real_cost_usd"))
    actual_model_entries = (
        (actual_fallback or {}).get("steps")
        if isinstance((actual_fallback or {}).get("steps"), list)
        else []
    )

    total_tokens = actual_total_tokens or ledger_total_tokens or fallback_tokens
    total_cost_usd = actual_token_cost_usd or (
        ledger_token_cost_usd if ledger_has_canonical_costs else 0.0
    )
    if total_cost_usd <= 0:
        total_cost_usd = _estimate_cost(fallback_model, total_tokens or fallback_tokens)
    model_entries = actual_model_entries or (
        ledger_model_entries if ledger_has_canonical_costs else []
    )

    if not model_entries:
        model_name = (
            canonicalize_model_name((ledger_entry or {}).get("model"))
            or canonicalize_model_name((actual_fallback or {}).get("model"))
            or canonicalize_model_name(fallback_model)
        )
        fallback_cost_usd = (
            actual_token_cost_usd
            or (ledger_token_cost_usd if ledger_has_canonical_costs else 0.0)
            or _estimate_cost(model_name, total_tokens)
        )
        model_entries = [
            {
                "model": model_name,
                "tokens": total_tokens,
                "cost_usd": round(fallback_cost_usd, 6),
            }
        ]

    return {
        "audit_id": int(audit.id),
        "audit_key": str(audit.request_id or "").strip() or f"audit:{audit.id}",
        "request_id": str(audit.request_id or "").strip() or None,
        "created_at": audit.created_at,
        "project_id": audit.project_id,
        "user_id": audit.user_id,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost_usd, 6),
        "real_cost_usd": round(actual_real_cost_usd or ledger_real_cost, 6),
        "model_entries": [
            {
                "model": str(item.get("model") or "unknown"),
                "tokens": _coerce_admin_cost_int(item.get("tokens")),
                "cost_usd": round(_coerce_admin_cost_float(item.get("cost_usd")), 6),
            }
            for item in model_entries
            if isinstance(item, dict)
        ],
    }


def _load_admin_audit_economics(
    db: Session,
    audits: list[models.Audit],
) -> list[dict[str, Any]]:
    fx_snapshot = _get_admin_ai_cost_fx_snapshot(db)
    request_ids = {
        str(audit.request_id).strip()
        for audit in audits
        if isinstance(audit.request_id, str) and audit.request_id.strip()
    }
    ledger_index = _build_admin_ledger_request_index(
        db,
        request_ids=request_ids,
        default_fx_snapshot=fx_snapshot,
    )

    return [
        _resolve_admin_audit_economics(
            audit,
            ledger_entry=ledger_index.get(str(audit.request_id or "").strip()),
            default_fx_snapshot=fx_snapshot,
        )
        for audit in audits
    ]


def _get_retention_setting(env_key: str) -> int | None:
    raw_value = os.getenv(env_key)
    if raw_value is None or raw_value.strip() == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.invalid_env_value",
                "Invalid {env_key} value: {raw_value}",
                params={"env_key": env_key, "raw_value": raw_value},
            ),
        ) from exc
    if value <= 0:
        return None
    return value


def _get_operational_settings(db: Session) -> models.OperationalSetting:
    return get_or_create_operational_settings(db)


def _serialize_operation_status(
    settings: models.OperationalSetting,
) -> dict[str, object]:
    refresh_requested_at = (
        settings.cache_refresh_requested_at.isoformat()
        if settings.cache_refresh_requested_at
        else None
    )
    return {
        "fallback_model_enabled": settings.fallback_model_enabled,
        "pricing_v2_enabled": bool(getattr(settings, "pricing_v2_enabled", True)),
        "credit_engine_v2_enabled": bool(getattr(settings, "credit_engine_v2_enabled", True)),
        "pricing_v2_shadow_mode": bool(getattr(settings, "pricing_v2_shadow_mode", False)),
        "pricing_v3_shadow_mode": bool(getattr(settings, "pricing_v3_shadow_mode", False)),
        "cache_refresh_requested_at": refresh_requested_at,
        "report_retention_days": normalize_report_retention_days(
            getattr(settings, "report_retention_days", None)
        ),
    }


def _serialize_admin_user(
    user: models.User,
    subscription: models.Subscription | None,
    audit_count: int,
) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "credits": user.credits,
        "notifications_enabled": user.notifications_enabled,
        "plan": subscription.plan_type if subscription else (user.trial_plan or "plan_starter"),
        "subscription_status": subscription.status if subscription else None,
        "audit_count": audit_count,
    }


def _resolve_admin_plan_type(plan_value: str) -> str:
    normalized_plan = plan_value.strip().lower()
    if not normalized_plan:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.plan_must_be_non_empty", "plan must be a non-empty string."
            ),
        )

    if normalized_plan not in PUBLIC_PLAN_TYPES:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.plan_must_be_valid",
                "plan must be one of plan_starter/plan_standard/plan_specialist/plan_executive.",
            ),
        )
    return normalized_plan


def _get_audit_report_metadata(report: dict) -> tuple[str | None, str | None, bool]:
    metadata = report.get("metadata", {}) if isinstance(report, dict) else {}
    provider = metadata.get("provider") or metadata.get("model")
    tier = metadata.get("tier")
    has_screenshot = report.get("screenshot_base64") is not None
    return provider, tier, has_screenshot


def _resolve_audit_score(audit: models.Audit, report: dict, metric: str) -> float:
    scores = report.get("scores", {}) if isinstance(report, dict) else {}
    score_value = scores.get(metric) if isinstance(scores, dict) else None
    if isinstance(score_value, (int, float)):
        return float(score_value)

    analysis = report.get("analysis", {}) if isinstance(report, dict) else {}
    analysis_key = f"{metric}_score"
    if isinstance(analysis, dict):
        parsed = extract_score(analysis, analysis_key)
        if parsed > 0:
            return float(parsed)

    legacy_sections: dict[str, tuple[str, str]] = {
        "seo": ("seo", "onpage"),
        "geo": ("geo", "visibility_index"),
        "aeo": ("aeo", "answerability_score"),
    }
    section_name, section_score_key = legacy_sections[metric]
    section = report.get(section_name, {}) if isinstance(report, dict) else {}
    legacy_score = section.get(section_score_key) if isinstance(section, dict) else None
    if isinstance(legacy_score, (int, float)):
        return float(legacy_score)

    db_score = getattr(audit, f"{metric}_score", None)
    if isinstance(db_score, (int, float)):
        return float(db_score)

    return 0.0


def _extract_credits_used(report: dict) -> int | None:
    metadata = report.get("metadata", {}) if isinstance(report, dict) else {}
    candidate_keys = ("credits_used", "credit_used", "credits_consumed")
    for key in candidate_keys:
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _coerce_optional_text(value: object) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _coerce_optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.lstrip("-").isdigit():
            return int(stripped)
    return None


def _coerce_optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    normalized = str(value or "").strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    return None


def _serialize_audit_target_type(value: object) -> str | None:
    if hasattr(value, "name"):
        normalized = str(getattr(value, "name") or "").strip().lower()
        return normalized or None
    normalized = str(value or "").strip().lower()
    return normalized or None


def _extract_admin_audit_runtime_metadata(report: dict) -> dict[str, object]:
    metadata = report.get("metadata") if isinstance(report, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}
    dual_track_grounding = (
        metadata.get("dual_track_grounding")
        if isinstance(metadata.get("dual_track_grounding"), dict)
        else {}
    )
    integrity_summary = (
        metadata.get("integrity_certificate_summary")
        if isinstance(metadata.get("integrity_certificate_summary"), dict)
        else {}
    )

    track_a_claim_count = _coerce_optional_int(metadata.get("track_a_claim_count"))
    if track_a_claim_count is None:
        track_a_claim_count = _coerce_optional_int(integrity_summary.get("track_a_claim_count"))

    track_b_claim_count = _coerce_optional_int(metadata.get("track_b_claim_count"))
    if track_b_claim_count is None:
        track_b_claim_count = _coerce_optional_int(integrity_summary.get("track_b_claim_count"))

    return {
        "requested_tier": _coerce_optional_text(metadata.get("requested_tier"))
        or _coerce_optional_text(metadata.get("tier")),
        "grounding_profile": _coerce_optional_text(metadata.get("grounding_profile")),
        "dual_track_grounding_enabled": bool(
            _coerce_optional_bool(metadata.get("dual_track_grounding_enabled"))
        ),
        "fallback_reason": _coerce_optional_text(metadata.get("fallback_reason")),
        "track_a_claim_count": track_a_claim_count,
        "track_b_claim_count": track_b_claim_count,
        "dual_track_rollout_mode": _coerce_optional_text(dual_track_grounding.get("rollout_mode")),
        "dual_track_execution_mode": _coerce_optional_text(
            dual_track_grounding.get("effective_execution_mode")
        ),
    }


def _matches_admin_audit_runtime_filters(
    payload: dict[str, object],
    *,
    grounding_profile: str | None,
    dual_track_grounding_enabled: bool | None,
    fallback_reason: str | None,
) -> bool:
    normalized_grounding_profile = _coerce_optional_text(grounding_profile)
    normalized_fallback_reason = _coerce_optional_text(fallback_reason)

    if normalized_grounding_profile and (
        str(payload.get("grounding_profile") or "").strip().lower()
        != normalized_grounding_profile.lower()
    ):
        return False

    if (
        dual_track_grounding_enabled is not None
        and bool(payload.get("dual_track_grounding_enabled")) is not dual_track_grounding_enabled
    ):
        return False

    if (
        normalized_fallback_reason
        and normalized_fallback_reason.lower()
        not in str(payload.get("fallback_reason") or "").strip().lower()
    ):
        return False

    return True


def _serialize_audit_entry(
    audit: models.Audit,
    user_email: str,
    report: dict,
) -> dict[str, object]:
    provider, tier, has_screenshot = _get_audit_report_metadata(report)
    runtime_metadata = _extract_admin_audit_runtime_metadata(report)
    return {
        "id": audit.id,
        "user_id": audit.user_id,
        "user_email": user_email,
        "url": audit.url,
        "audit_target_type": _serialize_audit_target_type(audit.audit_target_type),
        "target_name": _coerce_optional_text(audit.target_name),
        "target_url": _coerce_optional_text(audit.target_url) or _coerce_optional_text(audit.url),
        "geo_score": _resolve_audit_score(audit, report, "geo"),
        "seo_score": _resolve_audit_score(audit, report, "seo"),
        "aeo_score": _resolve_audit_score(audit, report, "aeo"),
        "provider": provider,
        "tier": tier,
        **runtime_metadata,
        "created_at": audit.created_at.isoformat() if audit.created_at else "",
        "sanitized_at": audit.sanitized_at.isoformat() if audit.sanitized_at else None,
        "has_screenshot": has_screenshot,
    }


def _build_admin_audit_filters(
    user_id: int | None,
    user_email: str | None,
    url_contains: str | None,
    start_date: datetime | None,
    end_date: datetime | None,
    provider: str | None,
    tier: str | None,
) -> list[object]:
    provider_expr = models.Audit.full_report["metadata"]["provider"].as_string()
    tier_expr = models.Audit.full_report["metadata"]["tier"].as_string()
    normalized_provider = provider.strip().lower() if provider and provider.strip() else None
    normalized_tier = tier.strip().lower() if tier and tier.strip() else None

    filters: list[object] = []
    if user_id is not None:
        filters.append(models.Audit.user_id == user_id)
    if user_email and user_email.strip():
        filters.append(models.User.email.ilike(f"%{user_email.strip()}%"))
    if url_contains and url_contains.strip():
        filters.append(models.Audit.url.ilike(f"%{url_contains.strip()}%"))
    if start_date is not None:
        filters.append(models.Audit.created_at >= start_date)
    if end_date is not None:
        filters.append(models.Audit.created_at <= end_date)
    if normalized_provider:
        filters.append(func.lower(provider_expr) == normalized_provider)
    if normalized_tier:
        filters.append(func.lower(tier_expr) == normalized_tier)
    return filters


def _normalize_admin_cost_requested_tier(requested_tier: str | None) -> str | None:
    if not isinstance(requested_tier, str) or not requested_tier.strip():
        return None
    return normalize_audit_tier(requested_tier)


def _normalize_admin_cost_debate_profile(debate_profile: str | None) -> str | None:
    cleaned = str(debate_profile or "").strip().lower()
    return cleaned or None


def _apply_admin_cost_filters(
    query,
    *,
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    normalized_requested_tier = _normalize_admin_cost_requested_tier(requested_tier)
    normalized_debate_profile = _normalize_admin_cost_debate_profile(debate_profile)

    if normalized_requested_tier:
        requested_tier_expr = func.coalesce(
            models.Audit.full_report["metadata"]["requested_tier"].as_string(),
            models.Audit.full_report["metadata"]["tier"].as_string(),
        )
        query = query.filter(func.lower(requested_tier_expr) == normalized_requested_tier)

    if normalized_debate_profile:
        ai_generation_profile_expr = models.Audit.full_report["metadata"]["ai_generation"][
            "profile"
        ].as_string()
        debate_profile_expr = models.Audit.full_report["metadata"]["debate"]["profile"].as_string()
        resolved_profile_expr = func.coalesce(ai_generation_profile_expr, debate_profile_expr)
        query = query.filter(func.lower(resolved_profile_expr) == normalized_debate_profile)

    return query


def _get_admin_currency_policy_for_reporting(db: Session) -> dict[str, object]:
    return {"display_currency": "USD"}


def _serialize_admin_fx_reference(snapshot: dict[str, Any] | None = None) -> dict[str, object]:
    return {"currency": "USD"}


def _get_admin_ai_cost_fx_snapshot(db: Session) -> dict[str, Any]:
    return {}


VALID_PERIODS: dict[str, int] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "365d": 365,
}

VALID_METRICS: set[str] = {"audits", "emails", "cost"}


def _build_daily_series(
    rows: list[tuple],
    start_date,
    end_date,
) -> list[dict]:
    """Turn (date, value) query rows into a gapless daily list."""
    lookup: dict[str, float] = {}
    for row_date, row_value in rows:
        key = row_date.strftime("%Y-%m-%d") if hasattr(row_date, "strftime") else str(row_date)
        lookup[key] = float(row_value)

    result: list[dict] = []
    cursor = start_date
    while cursor <= end_date:
        key = cursor.strftime("%Y-%m-%d")
        result.append({"date": key, "value": lookup.get(key, 0.0)})
        cursor += timedelta(days=1)
    return result


def _compute_summary(current_val: float, previous_val: float) -> dict:
    change_pct = None
    if previous_val > 0:
        change_pct = round(((current_val - previous_val) / previous_val) * 100, 1)
    elif current_val > 0:
        change_pct = 100.0
    return {"current": current_val, "previous_period": previous_val, "change_pct": change_pct}


@router.get("/metrics/timeseries", response_model=MetricsTimeSeriesResponse)
def get_admin_metrics_timeseries(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    period: str = "30d",
    metrics: str = "audits,emails,cost",
):
    """Return daily time-series data for selected admin metrics."""
    if period not in VALID_PERIODS:
        raise HTTPException(
            status_code=400, detail=f"period must be one of {list(VALID_PERIODS.keys())}"
        )

    days = VALID_PERIODS[period]
    now = datetime.now(timezone.utc)
    period_end = now.date()
    period_start = (now - timedelta(days=days)).date()
    prev_start = (now - timedelta(days=days * 2)).date()

    requested = {m.strip() for m in metrics.split(",") if m.strip() in VALID_METRICS}
    if not requested:
        requested = VALID_METRICS

    series: dict[str, list] = {}
    summary: dict[str, dict] = {}

    date_col = func.date(models.Audit.created_at)
    email_date_col = func.date(models.EmailOutbox.created_at)

    if "audits" in requested:
        # Current period daily counts
        rows = (
            db.query(date_col.label("d"), func.count(models.Audit.id))
            .filter(
                models.Audit.created_at
                >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
            )
            .group_by("d")
            .order_by("d")
            .all()
        )
        series["audits"] = _build_daily_series(rows, period_start, period_end)

        current_total = sum(p["value"] for p in series["audits"])
        prev_total = (
            db.query(func.count(models.Audit.id))
            .filter(
                models.Audit.created_at
                >= datetime.combine(prev_start, datetime.min.time(), tzinfo=timezone.utc),
                models.Audit.created_at
                < datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            )
            .scalar()
            or 0
        )
        summary["audits"] = _compute_summary(current_total, float(prev_total))

    if "emails" in requested:
        rows = (
            db.query(email_date_col.label("d"), func.count(models.EmailOutbox.id))
            .filter(
                models.EmailOutbox.created_at
                >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
            )
            .group_by("d")
            .order_by("d")
            .all()
        )
        series["emails"] = _build_daily_series(rows, period_start, period_end)

        current_total = sum(p["value"] for p in series["emails"])
        prev_total = (
            db.query(func.count(models.EmailOutbox.id))
            .filter(
                models.EmailOutbox.created_at
                >= datetime.combine(prev_start, datetime.min.time(), tzinfo=timezone.utc),
                models.EmailOutbox.created_at
                < datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            )
            .scalar()
            or 0
        )
        summary["emails"] = _compute_summary(current_total, float(prev_total))

    if "cost" in requested:
        recent_audits = (
            db.query(models.Audit)
            .filter(
                models.Audit.created_at
                >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc)
            )
            .all()
        )
        recent_economics = _load_admin_audit_economics(db, recent_audits)
        daily_cost: dict[str, float] = {}
        for item in recent_economics:
            created_at = item.get("created_at")
            if not isinstance(created_at, datetime):
                continue
            day_key = created_at.strftime("%Y-%m-%d")
            daily_cost[day_key] = daily_cost.get(day_key, 0.0) + _coerce_admin_cost_float(
                item.get("total_cost_usd")
            )

        cost_rows = [
            (datetime.strptime(k, "%Y-%m-%d").date(), v)
            for k, v in daily_cost.items()
            if k != "unknown"
        ]
        series["cost"] = _build_daily_series(cost_rows, period_start, period_end)

        current_total = round(sum(p["value"] for p in series["cost"]), 2)

        prev_audits = (
            db.query(models.Audit)
            .filter(
                models.Audit.created_at
                >= datetime.combine(prev_start, datetime.min.time(), tzinfo=timezone.utc),
                models.Audit.created_at
                < datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            )
            .all()
        )
        prev_cost = round(
            sum(
                _coerce_admin_cost_float(item.get("total_cost_usd"))
                for item in _load_admin_audit_economics(db, prev_audits)
            ),
            2,
        )
        summary["cost"] = _compute_summary(current_total, round(prev_cost, 2))

    return {
        "period": period,
        "series": series,
        "summary": summary,
    }


@router.get("/metrics", response_model=AdminMetricsResponse)
def get_admin_metrics(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)

    monthly_recurring_revenue, _, active_subscription_count = calculate_subscription_mrr(db)

    total_users = db.query(func.count(models.User.id)).scalar() or 0
    total_audits = db.query(func.count(models.Audit.id)).scalar() or 0
    audits_last_30_days = (
        db.query(func.count(models.Audit.id))
        .filter(models.Audit.created_at >= thirty_days_ago)
        .scalar()
        or 0
    )
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))

    recent_audits = db.query(models.Audit).filter(models.Audit.created_at >= thirty_days_ago).all()
    recent_economics = _load_admin_audit_economics(db, recent_audits)
    token_costs_30d = round(
        sum(_coerce_admin_cost_float(item.get("total_cost_usd")) for item in recent_economics),
        2,
    )
    token_costs_30d_usd = round(
        sum(_coerce_admin_cost_float(item.get("total_cost_usd")) for item in recent_economics),
        2,
    )

    all_audits = db.query(models.Audit).all()
    token_costs_total = round(
        sum(
            _coerce_admin_cost_float(item.get("total_cost_usd"))
            for item in _load_admin_audit_economics(db, all_audits)
        ),
        2,
    )

    avg_ai_cost_per_audit_30d = (
        round(token_costs_30d / float(audits_last_30_days), 2) if audits_last_30_days else 0.0
    )

    net_profit_margin = 0.0
    if monthly_recurring_revenue:
        net_profit_margin = round(
            ((monthly_recurring_revenue - token_costs_30d_usd) / monthly_recurring_revenue) * 100,
            2,
        )

    return {
        "monthly_recurring_revenue": float(monthly_recurring_revenue),
        "total_api_costs": token_costs_30d,
        "ai_cost_consumed_30d": token_costs_30d,
        "ai_cost_consumed_total": token_costs_total,
        "avg_ai_cost_per_audit_30d": avg_ai_cost_per_audit_30d,
        "net_profit_margin": net_profit_margin,
        "total_users": int(total_users),
        "active_subscriptions": active_subscription_count,
        "audits_last_30_days": int(audits_last_30_days),
        "total_audits": int(total_audits),
        "ai_cost_currency": "USD",
        "fx_reference": fx_reference,
    }


@router.get("/token-usage", response_model=TokenUsageResponse)
def get_token_usage(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    window_days: int = 30,
):
    if window_days <= 0 or window_days > 365:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.window_days_out_of_range", "window_days must be between 1 and 365."
            ),
        )

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(days=window_days)
    audits = db.query(models.Audit).filter(models.Audit.created_at >= start_time).all()
    audit_economics = _load_admin_audit_economics(db, audits)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))

    totals: dict[str, dict[str, float | int]] = {}
    total_tokens = 0
    total_cost = 0.0
    for audit_entry in audit_economics:
        seen_models: set[str] = set()
        audit_tokens = _coerce_admin_cost_int(audit_entry.get("total_tokens"))
        total_tokens += audit_tokens
        total_cost += _coerce_admin_cost_float(audit_entry.get("total_cost_usd"))
        for model_entry in audit_entry.get("model_entries") or []:
            if not isinstance(model_entry, dict):
                continue
            model_name = str(model_entry.get("model") or "unknown").strip() or "unknown"
            entry = totals.setdefault(model_name, {"tokens": 0, "cost": 0.0, "audits": 0})
            entry["tokens"] = int(entry["tokens"]) + _coerce_admin_cost_int(
                model_entry.get("tokens")
            )
            entry["cost"] = float(entry["cost"]) + _coerce_admin_cost_float(
                model_entry.get("cost_usd")
            )
            if model_name not in seen_models:
                entry["audits"] = int(entry["audits"]) + 1
                seen_models.add(model_name)

    entries = [
        {
            "model": model,
            "tokens": int(data["tokens"]),
            "cost": round(float(data["cost"]), 2),
            "audits": int(data["audits"]),
        }
        for model, data in sorted(totals.items(), key=lambda item: item[1]["tokens"], reverse=True)
    ]

    return {
        "window_days": window_days,
        "total_tokens": total_tokens,
        "total_cost": round(total_cost, 2),
        "entries": entries,
        "currency": "USD",
        "fx_reference": fx_reference,
    }


@router.get("/users", response_model=AdminUsersResponse)
def list_admin_users(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 100:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range", "page_size must be between 1 and 100."
            ),
        )

    audit_counts_subquery = (
        db.query(
            models.Audit.user_id,
            func.count(models.Audit.id).label("audit_count"),
        )
        .group_by(models.Audit.user_id)
        .subquery()
    )

    user_query = (
        db.query(
            models.User,
            models.Subscription,
            audit_counts_subquery.c.audit_count,
        )
        .outerjoin(models.Subscription, models.Subscription.user_id == models.User.id)
        .outerjoin(audit_counts_subquery, audit_counts_subquery.c.user_id == models.User.id)
    )

    if query:
        trimmed = query.strip()
        if trimmed:
            like_value = f"%{trimmed}%"
            user_query = user_query.filter(
                or_(
                    models.User.email.ilike(like_value),
                    models.User.provider_subject.ilike(like_value),
                    models.User.role.ilike(like_value),
                )
            )

    total = user_query.count()
    users = (
        user_query.order_by(models.User.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "users": [
            _serialize_admin_user(
                user,
                subscription,
                int(audit_count or 0),
            )
            for user, subscription, audit_count in users
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/users/{user_id}", response_model=AdminUserDetailResponse)
def get_current_user_details(
    user_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    )
    audit_total = (
        db.query(func.count(models.Audit.id)).filter(models.Audit.user_id == user.id).scalar() or 0
    )
    last_audit = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user.id)
        .order_by(models.Audit.created_at.desc())
        .first()
    )

    return {
        "user": _serialize_admin_user(user, subscription, int(audit_total)),
        "audit_summary": {
            "total": int(audit_total),
            "last_audit_at": last_audit.created_at if last_audit else None,
            "last_audit_url": last_audit.url if last_audit else None,
        },
        "subscription_summary": {
            "plan": subscription.plan_type if subscription else (user.trial_plan or "plan_starter"),
            "status": subscription.status if subscription else None,
            "current_period_end": subscription.current_period_end if subscription else None,
            "cancel_at_period_end": subscription.cancel_at_period_end if subscription else None,
            "stripe_customer_id": subscription.stripe_customer_id if subscription else None,
            "stripe_subscription_id": subscription.stripe_subscription_id if subscription else None,
        },
    }


def _get_user_or_404(db: Session, user_id: int) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.user_not_found_admin", "User not found."),
        )
    return user


@router.patch("/users/{user_id}", response_model=AdminUserMutationResponse)
def update_admin_user(
    user_id: int,
    payload: AdminUserUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if (
        payload.plan is not None
        and payload.plan_type is not None
        and payload.plan != payload.plan_type
    ):
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.plan_plan_type_mismatch",
                "plan and plan_type must match when both are provided.",
            ),
        )
    requested_plan = payload.plan_type if payload.plan_type is not None else payload.plan
    validated_plan = (
        _resolve_admin_plan_type(requested_plan) if requested_plan is not None else None
    )
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    )
    previous_plan = subscription.plan_type if subscription else (user.trial_plan or "plan_starter")

    previous_values = {
        "role": user.role,
        "credits": user.credits,
        "notifications_enabled": user.notifications_enabled,
    }
    if payload.role is not None:
        if payload.role not in {"user", "admin", "moderator"}:
            raise HTTPException(
                status_code=400,
                detail=translate_backend_message(
                    "errors.role_invalid", "role must be 'user', 'moderator', or 'admin'."
                ),
            )
        user.role = payload.role
    if payload.credits is not None:
        if payload.credits < 0:
            raise HTTPException(
                status_code=400,
                detail=translate_backend_message(
                    "errors.credits_must_be_non_negative", "credits must be 0 or higher."
                ),
            )
        user.credits = payload.credits
    if payload.notifications_enabled is not None:
        user.notifications_enabled = payload.notifications_enabled

    if validated_plan is not None:
        if validated_plan == "plan_starter":
            user.trial_plan = "plan_starter"
            if subscription:
                db.delete(subscription)
                subscription = None
        elif subscription is None:
            subscription = models.Subscription(
                user_id=user.id,
                stripe_customer_id=f"admin_manual_{user.id}_{uuid4().hex}",
                plan_type=validated_plan,
                status="active",
            )
            db.add(subscription)
        else:
            subscription.plan_type = validated_plan
            # Admin plan assignments are treated as immediately active grants,
            # so users receive plan entitlements without waiting for a billing webhook.
            subscription.status = "active"
            subscription.cancel_at_period_end = False

    after_plan = subscription.plan_type if subscription else (user.trial_plan or "plan_starter")

    _log_admin_action(
        db,
        admin_user,
        action="user_update",
        target_type="user",
        target_id=user.id,
        metadata={
            "changes": {
                "role": {"before": previous_values["role"], "after": user.role},
                "credits": {"before": previous_values["credits"], "after": user.credits},
                "notifications_enabled": {
                    "before": previous_values["notifications_enabled"],
                    "after": user.notifications_enabled,
                },
                "plan": {
                    "before": previous_plan,
                    "after": after_plan,
                },
            }
        },
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    if subscription is not None:
        db.refresh(subscription)
    else:
        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
        )
    audit_count = (
        db.query(func.count(models.Audit.id)).filter(models.Audit.user_id == user.id).scalar() or 0
    )
    return {
        "user": _serialize_admin_user(user, subscription, int(audit_count)),
    }


@router.post("/users/{user_id}/credits", response_model=AdminUserMutationResponse)
def adjust_user_credits(
    user_id: int,
    payload: AdminUserCreditsRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    user = _get_user_or_404(db, user_id)
    if payload.delta == 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.delta_must_be_non_zero", "delta must be a non-zero value."
            ),
        )
    if not payload.reason.strip():
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message("errors.reason_required", "reason is required."),
        )
    new_credits = user.credits + payload.delta
    if new_credits < 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.credits_cannot_go_below_zero", "credits cannot go below zero."
            ),
        )

    user.credits = new_credits
    adjustment = models.UserCreditAdjustment(
        user_id=user.id,
        admin_user_id=admin_user.id,
        delta=payload.delta,
        reason=payload.reason.strip(),
        created_at=datetime.now(timezone.utc),
    )
    _log_admin_action(
        db,
        admin_user,
        action="user_credits_adjusted",
        target_type="user",
        target_id=user.id,
        metadata={
            "delta": payload.delta,
            "reason": payload.reason.strip(),
            "new_credits": user.credits,
        },
    )

    db.add(adjustment)
    db.add(user)
    db.commit()
    db.refresh(user)

    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    )
    audit_count = (
        db.query(func.count(models.Audit.id)).filter(models.Audit.user_id == user.id).scalar() or 0
    )
    return {
        "user": _serialize_admin_user(user, subscription, int(audit_count)),
    }


@router.delete("/users/{user_id}")
def delete_admin_user(
    user_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if admin_user.id == user_id:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.admin_self_delete_forbidden",
                "Admin users cannot delete their own account.",
            ),
        )

    user = _get_user_or_404(db, user_id)

    _log_admin_action(
        db,
        admin_user,
        action="user_delete",
        target_type="user",
        target_id=user.id,
        metadata={
            "email": user.email,
            "role": user.role,
        },
    )

    deleted_at = datetime.now(timezone.utc)
    deleted_audits = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user_id)
        .delete(synchronize_session=False)
    )
    deleted_subscriptions = (
        db.query(models.Subscription)
        .filter(models.Subscription.user_id == user_id)
        .delete(synchronize_session=False)
    )
    # Invoices are statutory tax records: the admin path anonymises them in
    # place exactly like the self-service path, it does not delete them
    # (SIGV2-1144).
    retained_invoices = anonymize_billing_payments_for_user(db, user=user, now=deleted_at)
    deleted_email_outbox_entries = (
        db.query(models.EmailOutbox)
        .filter(models.EmailOutbox.user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.query(models.UserCreditAdjustment).filter(
        models.UserCreditAdjustment.admin_user_id == user_id
    ).update({models.UserCreditAdjustment.admin_user_id: None}, synchronize_session=False)
    deleted_credit_adjustments = (
        db.query(models.UserCreditAdjustment)
        .filter(models.UserCreditAdjustment.user_id == user_id)
        .delete(synchronize_session=False)
    )

    receipt = record_account_deletion_receipt(
        db,
        user=user,
        now=deleted_at,
        initiated_by="admin",
        initiated_by_admin_user_id=admin_user.id,
        erased_record_counts={
            "audits": deleted_audits,
            "subscriptions": deleted_subscriptions,
            "email_outbox_entries": deleted_email_outbox_entries,
            "user_credit_adjustments": deleted_credit_adjustments,
        },
        retained_invoices=retained_invoices,
    )

    db.delete(user)
    db.commit()

    return {
        "deleted": True,
        "retained_billing_payments": retained_invoices.retained_count,
        "billing_records_retained_until": (
            retained_invoices.retained_until.isoformat()
            if retained_invoices.retained_until
            else None
        ),
        "deletion_receipt_reference": receipt.reference,
    }


@router.post(
    "/users/invite",
    response_model=AdminInviteUserResponse,
    status_code=201,
)
async def invite_admin_user(
    payload: AdminInviteUserRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if payload.role not in {"user", "admin", "moderator"}:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.role_invalid", "role must be 'user', 'moderator', or 'admin'."
            ),
        )

    normalized_email = payload.email.strip().lower()
    existing_user = (
        db.query(models.User).filter(func.lower(models.User.email) == normalized_email).first()
    )
    if existing_user is not None:
        raise HTTPException(
            status_code=409,
            detail=translate_backend_message(
                "errors.user_already_exists_admin",
                "A user with this email already exists.",
            ),
        )

    target_user = models.User(
        email=normalized_email,
        hashed_password=hash_password(secrets.token_urlsafe(32)),
        role=payload.role,
        company_name=payload.name,
    )
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    auth_service = AuthService(db)
    invitation_token = auth_service.create_password_reset_token(target_user.email)
    frontend_base_url = _resolve_platform_base_url()
    invitation_url = f"{frontend_base_url}/reset-password?token={invitation_token}&flow=invite"

    email_entry = None
    try:
        email_entry = await EmailService(db).send_password_reset_email(
            target_user.email,
            invitation_token,
            user_id=target_user.id,
        )
    except Exception:
        logger.warning("Failed to queue invite email for user %s", target_user.id, exc_info=True)

    _log_admin_action(
        db,
        admin_user,
        action="invite_user",
        target_type="user",
        target_id=target_user.id,
        metadata={"email": target_user.email, "role": payload.role},
    )
    db.commit()

    return AdminInviteUserResponse(
        user_id=target_user.id,
        email=target_user.email,
        role=target_user.role,
        invited=True,
        email_queued=email_entry is not None,
        invitation_url=None if email_entry is not None else invitation_url,
    )


@router.get("/billing/subscriptions", response_model=AdminBillingSubscriptionsResponse)
def list_admin_billing_subscriptions(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    subscriptions = (
        db.query(models.Subscription, models.User)
        .join(models.User, models.Subscription.user_id == models.User.id)
        .order_by(models.Subscription.id.asc())
        .all()
    )
    return {
        "subscriptions": [
            {
                "id": subscription.id,
                "user_id": user.id,
                "user_email": user.email,
                "stripe_customer_id": subscription.stripe_customer_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "plan_type": subscription.plan_type,
                "status": subscription.status,
            }
            for subscription, user in subscriptions
        ]
    }


@router.get("/billing/config", response_model=AdminBillingConfigResponse)
def get_admin_billing_config(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    config = load_billing_config(db=db)
    return build_admin_billing_config_payload(config)


@router.patch("/billing/config", response_model=AdminBillingConfigResponse)
def update_admin_billing_config(
    payload: AdminBillingConfigUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    settings = _get_operational_settings(db)
    normalized = _normalize_admin_settings_payload(settings.admin_settings_payload)
    raw_runtime = normalized.get("billing_runtime")
    runtime = normalize_billing_runtime_payload(raw_runtime)
    runtime_modes = ensure_billing_runtime_modes(runtime)
    preserve_billing_enabled = runtime_payload_has_key(raw_runtime, "billing_enabled")
    preserve_stripe_mode = runtime_payload_has_key(raw_runtime, "stripe_mode")

    if payload.billing_enabled is not None:
        runtime["billing_enabled"] = payload.billing_enabled
        preserve_billing_enabled = True
    if payload.stripe_mode is not None:
        runtime["stripe_mode"] = payload.stripe_mode
        preserve_stripe_mode = True

    if "test_secret_key" in payload.model_fields_set:
        runtime_modes["test"]["secret_key"] = _normalize_admin_text(
            payload.test_secret_key,
            max_length=512,
        )
    if "live_secret_key" in payload.model_fields_set:
        runtime_modes["live"]["secret_key"] = _normalize_admin_text(
            payload.live_secret_key,
            max_length=512,
        )
    if "test_webhook_secret" in payload.model_fields_set:
        runtime_modes["test"]["webhook_secret"] = _normalize_admin_text(
            payload.test_webhook_secret,
            max_length=512,
        )
    if "live_webhook_secret" in payload.model_fields_set:
        runtime_modes["live"]["webhook_secret"] = _normalize_admin_text(
            payload.live_webhook_secret,
            max_length=512,
        )

    for mode, plan_prices in (
        ("test", payload.test_price_ids),
        ("live", payload.live_price_ids),
    ):
        request_key = f"{mode}_price_ids"
        if request_key not in payload.model_fields_set:
            continue
        if not isinstance(plan_prices, dict):
            continue

        mode_price_ids = runtime_modes[mode].get("price_ids")
        if not isinstance(mode_price_ids, dict):
            mode_price_ids = {}
            runtime_modes[mode]["price_ids"] = mode_price_ids
        for plan_key, raw_price_id in plan_prices.items():
            resolved_plan = resolve_billing_plan_key(plan_key, _resolve_admin_plan_type)
            if not resolved_plan:
                continue
            mode_price_ids[resolved_plan] = _normalize_admin_text(raw_price_id, max_length=160)

    for mode, tier_prices in (
        ("test", payload.test_commitment_price_ids),
        ("live", payload.live_commitment_price_ids),
    ):
        request_key = f"{mode}_commitment_price_ids"
        if request_key not in payload.model_fields_set:
            continue
        if not isinstance(tier_prices, dict):
            continue

        mode_commitment_price_ids = runtime_modes[mode].get("commitment_price_ids")
        if not isinstance(mode_commitment_price_ids, dict):
            mode_commitment_price_ids = {}
            runtime_modes[mode]["commitment_price_ids"] = mode_commitment_price_ids
        for tier_key, raw_price_id in tier_prices.items():
            resolved_tier = resolve_billing_commitment_tier_key(tier_key)
            if not resolved_tier:
                continue
            mode_commitment_price_ids[resolved_tier] = _normalize_admin_text(
                raw_price_id,
                max_length=160,
            )

    if "test_commitment_overage_price_id" in payload.model_fields_set:
        runtime_modes["test"]["commitment_overage_price_id"] = _normalize_admin_text(
            payload.test_commitment_overage_price_id,
            max_length=160,
        )
    if "live_commitment_overage_price_id" in payload.model_fields_set:
        runtime_modes["live"]["commitment_overage_price_id"] = _normalize_admin_text(
            payload.live_commitment_overage_price_id,
            max_length=160,
        )

    persist_billing_runtime_settings(
        settings=settings,
        normalized_admin_payload=normalized,
        raw_runtime=raw_runtime,
        runtime=runtime,
        admin_user_id=admin_user.id,
        preserve_stripe_mode=preserve_stripe_mode,
        preserve_billing_enabled=preserve_billing_enabled,
        normalize_admin_settings_fn=_normalize_admin_settings_payload,
    )
    _log_admin_action(
        db,
        admin_user,
        action="admin_billing_config_updated",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={
            "stripe_mode": runtime.get("stripe_mode"),
            "billing_enabled": runtime.get("billing_enabled"),
            "has_runtime_override": is_billing_runtime_payload_meaningful(runtime),
        },
    )
    db.commit()
    db.refresh(settings)

    from services.configuration_service import configuration_service

    configuration_service.invalidate_cache()

    config = load_billing_config(db=db)
    return build_admin_billing_config_payload(config)


@router.post("/billing/catalog/sync", response_model=AdminBillingCatalogSyncResponse)
def sync_admin_billing_catalog(
    payload: AdminBillingCatalogSyncRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    config = load_billing_config(db=db)
    mode_config = config.mode_configs.get(payload.mode)
    stripe_secret_key = mode_config.secret_key if mode_config else None
    if not stripe_secret_key:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.stripe_secret_missing_catalog_sync",
                "Stripe secret key is missing for the requested billing mode.",
            ),
        )

    try:
        result = sync_stripe_catalog(
            stripe_secret_key=stripe_secret_key,
            mode=payload.mode,
            scope=payload.scope,
            dry_run=payload.dry_run,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.stripe_catalog_sync_failed",
                "Stripe catalog sync failed: {error}",
                params={"error": str(exc)},
            ),
        ) from exc

    config_payload = build_admin_billing_config_payload(load_billing_config(db=db))
    if not payload.dry_run:
        settings = _get_operational_settings(db)
        normalized = _normalize_admin_settings_payload(settings.admin_settings_payload)
        raw_runtime = normalized.get("billing_runtime")
        runtime = normalize_billing_runtime_payload(raw_runtime)
        runtime_modes = ensure_billing_runtime_modes(runtime)
        apply_catalog_sync_to_runtime(
            runtime_modes,
            mode=payload.mode,
            scope=payload.scope,
            plan_price_ids=result.plan_price_ids,
            annual_plan_price_ids=result.annual_plan_price_ids,
            commitment_price_ids=result.commitment_price_ids,
            commitment_overage_price_id=result.commitment_overage_price_id,
        )
        persist_billing_runtime_settings(
            settings=settings,
            normalized_admin_payload=normalized,
            raw_runtime=raw_runtime,
            runtime=runtime,
            admin_user_id=admin_user.id,
            preserve_stripe_mode=runtime_payload_has_key(raw_runtime, "stripe_mode"),
            preserve_billing_enabled=runtime_payload_has_key(raw_runtime, "billing_enabled"),
            normalize_admin_settings_fn=_normalize_admin_settings_payload,
        )
        db.commit()
        db.refresh(settings)
        from services.configuration_service import configuration_service

        configuration_service.invalidate_cache()
        config_payload = build_admin_billing_config_payload(load_billing_config(db=db))

    action_counts = {
        "created": sum(1 for item in result.items if item.action == "created"),
        "reused": sum(1 for item in result.items if item.action == "reused"),
        "warnings": sum(1 for item in result.items if item.action == "warning"),
        "errors": sum(1 for item in result.items if item.action == "error"),
    }
    _log_admin_action(
        db,
        admin_user,
        action="admin_billing_catalog_synced",
        target_type="operational_settings",
        target_id=None,
        metadata={
            "mode": payload.mode,
            "scope": payload.scope,
            "dry_run": payload.dry_run,
            "created_count": action_counts["created"],
            "reused_count": action_counts["reused"],
            "warning_item_count": action_counts["warnings"],
            "error_count": action_counts["errors"],
            "warning_count": len(result.warnings),
        },
    )
    db.commit()

    return {
        "mode": payload.mode,
        "scope": payload.scope,
        "dry_run": payload.dry_run,
        "result": serialize_catalog_sync_result(result),
        "config": config_payload,
    }


@router.post("/billing/catalog/validate", response_model=AdminBillingCatalogValidateResponse)
def validate_admin_billing_catalog(
    payload: AdminBillingCatalogValidateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    config = load_billing_config(db=db)
    mode_config = config.mode_configs.get(payload.mode)
    stripe_secret_key = mode_config.secret_key if mode_config else None
    if not stripe_secret_key:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.stripe_secret_missing_catalog_validate",
                "Stripe secret key is missing for the requested billing mode.",
            ),
        )

    try:
        results = validate_stripe_catalog(
            stripe_secret_key=stripe_secret_key,
            mode=payload.mode,
            configured_plan_price_ids={
                plan.value: mode_config.price_ids.get(plan) or None for plan in Plan
            },
            configured_annual_plan_price_ids={
                plan.value: mode_config.annual_price_ids.get(plan) or None for plan in Plan
            },
            configured_commitment_price_ids={
                tier.value: mode_config.commitment_price_ids.get(tier) or None
                for tier in CommitmentTier
            },
            configured_commitment_overage_price_id=mode_config.commitment_overage_price_id,
            scope=payload.scope,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.stripe_catalog_validate_failed",
                "Stripe catalog validation failed: {error}",
                params={"error": str(exc)},
            ),
        ) from exc

    status_counts = {
        "valid": sum(1 for item in results if item.status == "valid"),
        "unconfigured": sum(1 for item in results if item.status == "unconfigured"),
        "missing": sum(1 for item in results if item.status == "missing"),
        "mismatch": sum(1 for item in results if item.status == "mismatch"),
    }
    _log_admin_action(
        db,
        admin_user,
        action="admin_billing_catalog_validated",
        target_type="operational_settings",
        target_id=None,
        metadata={
            "mode": payload.mode,
            "scope": payload.scope,
            "valid_count": status_counts["valid"],
            "unconfigured_count": status_counts["unconfigured"],
            "missing_count": status_counts["missing"],
            "mismatch_count": status_counts["mismatch"],
        },
    )
    db.commit()

    return {
        "mode": payload.mode,
        "scope": payload.scope,
        "results": [asdict(item) for item in results],
        "config": build_admin_billing_config_payload(config),
    }


@router.get("/billing/overview", response_model=AdminBillingOverviewResponse)
def get_admin_billing_overview(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    config = load_billing_config(db=db)

    stripe_connected = False
    stripe_error: str | None = None
    if config.stripe_secret_key:
        try:
            stripe.api_key = config.stripe_secret_key
            stripe.Balance.retrieve()
            stripe_connected = True
        except Exception as exc:  # pragma: no cover - network/provider dependent
            stripe_error = str(exc)

    mrr_usd, total_subscriptions, active_subscriptions = calculate_subscription_mrr(db)
    total_invoices = db.query(func.count(models.BillingPayment.id)).scalar() or 0
    paid_invoices = (
        db.query(func.count(models.BillingPayment.id))
        .filter(models.BillingPayment.status == "paid")
        .scalar()
        or 0
    )
    open_invoices = (
        db.query(func.count(models.BillingPayment.id))
        .filter(models.BillingPayment.status.in_(["open", "draft", "uncollectible", "failed"]))
        .scalar()
        or 0
    )
    latest_invoice = (
        db.query(models.BillingPayment).order_by(models.BillingPayment.created_at.desc()).first()
    )

    return {
        "stripe_mode": config.stripe_mode,
        "billing_enabled": config.billing_enabled,
        "stripe_connected": stripe_connected,
        "stripe_error": stripe_error,
        "total_subscriptions": total_subscriptions,
        "active_subscriptions": active_subscriptions,
        "total_invoices": int(total_invoices),
        "paid_invoices": int(paid_invoices),
        "open_invoices": int(open_invoices),
        "monthly_recurring_revenue_estimate": mrr_usd,
        "latest_invoice_at": latest_invoice.created_at.isoformat() if latest_invoice else None,
    }


@router.post("/billing/sync", response_model=AdminBillingSyncResponse)
def sync_admin_billing_data(
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    config = load_billing_config(db=db)
    if not config.stripe_secret_key:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.stripe_secret_missing_sync",
                "Stripe secret key is missing for the active billing mode.",
            ),
        )

    stripe.api_key = config.stripe_secret_key
    try:
        stripe_subscriptions = stripe.Subscription.list(limit=100, status="all")
        stripe_invoices = stripe.Invoice.list(limit=100)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=translate_backend_message(
                "errors.stripe_sync_failed",
                "Stripe sync failed: {error}",
                params={"error": str(exc)},
            ),
        ) from exc

    subscriptions_processed = 0
    invoices_processed = 0
    records_skipped = 0
    errors: list[str] = []

    for raw_subscription in stripe_subscriptions.data:
        subscription_payload = stripe_object_to_dict(raw_subscription)
        stripe_customer_id = str(subscription_payload.get("customer") or "").strip()
        if not stripe_customer_id:
            records_skipped += 1
            continue

        local_subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.stripe_customer_id == stripe_customer_id)
            .first()
        )
        if not local_subscription:
            metadata = subscription_payload.get("metadata")
            metadata_mapping = metadata if isinstance(metadata, dict) else {}
            metadata_user_id = metadata_mapping.get("user_id")
            resolved_user_id = None
            try:
                resolved_user_id = int(str(metadata_user_id))
            except (TypeError, ValueError):
                resolved_user_id = None

            if resolved_user_id is None:
                records_skipped += 1
                continue
            local_subscription = (
                db.query(models.Subscription)
                .filter(models.Subscription.user_id == resolved_user_id)
                .first()
            )
            if local_subscription is None:
                local_subscription = models.Subscription(
                    user_id=resolved_user_id,
                    stripe_customer_id=stripe_customer_id,
                    plan_type=Plan.STANDARD.value,
                    status="pending",
                )
                db.add(local_subscription)

        items = subscription_payload.get("items")
        item_data = items.get("data") if isinstance(items, dict) else []
        first_item = item_data[0] if isinstance(item_data, list) and item_data else {}
        price_data = first_item.get("price") if isinstance(first_item, dict) else {}
        plan_data = first_item.get("plan") if isinstance(first_item, dict) else {}
        price_id = None
        if isinstance(price_data, dict):
            price_id = str(price_data.get("id") or "").strip() or None
        if not price_id and isinstance(plan_data, dict):
            price_id = str(plan_data.get("id") or "").strip() or None

        resolved_plan = config.plan_for_price_id(price_id)
        current_period_end = parse_stripe_timestamp(subscription_payload.get("current_period_end"))

        local_subscription.stripe_customer_id = stripe_customer_id
        local_subscription.stripe_subscription_id = (
            str(subscription_payload.get("id") or "").strip() or None
        )
        local_subscription.status = str(subscription_payload.get("status") or "pending")
        local_subscription.cancel_at_period_end = bool(
            subscription_payload.get("cancel_at_period_end")
        )
        local_subscription.current_period_end = current_period_end
        if resolved_plan:
            local_subscription.plan_type = resolved_plan.value
        subscriptions_processed += 1

    for raw_invoice in stripe_invoices.data:
        invoice_payload = stripe_object_to_dict(raw_invoice)
        stripe_invoice_id = str(invoice_payload.get("id") or "").strip()
        stripe_customer_id = str(invoice_payload.get("customer") or "").strip()
        if not stripe_invoice_id or not stripe_customer_id:
            records_skipped += 1
            continue

        subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.stripe_customer_id == stripe_customer_id)
            .first()
        )
        if subscription is None:
            records_skipped += 1
            continue

        payment = (
            db.query(models.BillingPayment)
            .filter(models.BillingPayment.stripe_invoice_id == stripe_invoice_id)
            .first()
        )
        created_at = parse_stripe_timestamp(invoice_payload.get("created")) or datetime.now(
            timezone.utc
        )
        if payment is None:
            payment = models.BillingPayment(
                user_id=subscription.user_id,
                stripe_invoice_id=stripe_invoice_id,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id=str(invoice_payload.get("subscription") or "").strip()
                or None,
                amount_paid=invoice_payload.get("amount_paid"),
                amount_due=invoice_payload.get("amount_due"),
                currency=invoice_payload.get("currency"),
                status=invoice_payload.get("status"),
                hosted_invoice_url=invoice_payload.get("hosted_invoice_url"),
                invoice_pdf=invoice_payload.get("invoice_pdf"),
                created_at=created_at,
                retention_until=retention_until_for_invoice(created_at),
            )
            db.add(payment)
        else:
            # A retained invoice from a deleted account keeps its severed
            # customer link: the sync refreshes the invoice facts only
            # (SIGV2-1144).
            if payment.anonymized_at is None:
                payment.user_id = subscription.user_id
                payment.stripe_customer_id = stripe_customer_id
            payment.stripe_subscription_id = (
                str(invoice_payload.get("subscription") or "").strip() or None
            )
            payment.amount_paid = invoice_payload.get("amount_paid")
            payment.amount_due = invoice_payload.get("amount_due")
            payment.currency = invoice_payload.get("currency")
            payment.status = invoice_payload.get("status")
            payment.hosted_invoice_url = invoice_payload.get("hosted_invoice_url")
            payment.invoice_pdf = invoice_payload.get("invoice_pdf")
            payment.created_at = created_at
            payment.retention_until = retention_until_for_invoice(created_at)

        invoices_processed += 1

    try:
        _log_admin_action(
            db,
            admin_user,
            action="admin_billing_sync",
            target_type="billing",
            target_id=config.stripe_mode,
            metadata={
                "stripe_mode": config.stripe_mode,
                "subscriptions_processed": subscriptions_processed,
                "invoices_processed": invoices_processed,
                "records_skipped": records_skipped,
                "errors": errors,
            },
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.billing_sync_commit_failed",
                "Billing sync failed to persist updates: {error}",
                params={"error": str(exc)},
            ),
        ) from exc

    return {
        "stripe_mode": config.stripe_mode,
        "subscriptions_processed": subscriptions_processed,
        "invoices_processed": invoices_processed,
        "records_skipped": records_skipped,
        "errors": errors,
    }


@router.get("/billing/invoices", response_model=AdminBillingInvoicesResponse)
def list_admin_billing_invoices(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    status: str | None = None,
    plan: str | None = None,
    user_email: str | None = None,
    stripe_invoice_id: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 100:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range", "page_size must be between 1 and 100."
            ),
        )

    # SIGV2-1144: outer join, not inner. An invoice whose customer has deleted
    # their account keeps NULL in user_id, and an inner join silently dropped
    # it, so reported revenue shrank retroactively every time someone exercised
    # their right to erasure. The invoice row is the record of the revenue; the
    # customer row is not needed to report it.
    query = (
        db.query(models.BillingPayment, models.User, models.Subscription)
        .outerjoin(models.User, models.BillingPayment.user_id == models.User.id)
        .outerjoin(models.Subscription, models.Subscription.user_id == models.User.id)
    )

    if start_date is not None:
        query = query.filter(models.BillingPayment.created_at >= start_date)
    if end_date is not None:
        query = query.filter(models.BillingPayment.created_at <= end_date)
    if status:
        query = query.filter(models.BillingPayment.status == status)
    if plan:
        normalized_plan = plan.strip().lower()
        if normalized_plan:
            query = query.filter(models.Subscription.plan_type == normalized_plan)
    if user_email:
        # An anonymised invoice keeps the recipient identity the invoice itself
        # carries, so searching by address still finds it.
        query = query.filter(
            or_(
                models.User.email.ilike(f"%{user_email}%"),
                models.BillingPayment.invoice_customer_email.ilike(f"%{user_email}%"),
            )
        )
    if stripe_invoice_id:
        query = query.filter(models.BillingPayment.stripe_invoice_id == stripe_invoice_id)
    if stripe_customer_id:
        query = query.filter(models.BillingPayment.stripe_customer_id == stripe_customer_id)
    if stripe_subscription_id:
        query = query.filter(models.BillingPayment.stripe_subscription_id == stripe_subscription_id)

    total = query.count()
    invoices = (
        query.order_by(models.BillingPayment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "invoices": [
            {
                "id": payment.id,
                "user_id": user.id if user else None,
                "user_email": (
                    user.email
                    if user
                    else (
                        payment.invoice_customer_email
                        or payment.invoice_customer_name
                        or UNNAMED_INVOICE_CUSTOMER
                    )
                ),
                "account_deleted": user is None,
                "retention_until": (
                    effective_retention_until(payment) if payment.created_at else None
                ),
                "stripe_invoice_id": payment.stripe_invoice_id,
                "stripe_customer_id": payment.stripe_customer_id,
                "stripe_subscription_id": payment.stripe_subscription_id,
                "amount_paid": payment.amount_paid,
                "amount_due": payment.amount_due,
                "currency": payment.currency,
                "status": payment.status,
                "hosted_invoice_url": payment.hosted_invoice_url,
                "invoice_pdf": payment.invoice_pdf,
                "created_at": payment.created_at,
                "plan_type": subscription.plan_type if subscription else None,
            }
            for payment, user, subscription in invoices
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/billing/commitments", response_model=AdminBillingCommitmentsResponse)
def list_admin_billing_commitments(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    tier: str | None = None,
    user_email: str | None = None,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 100:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range", "page_size must be between 1 and 100."
            ),
        )

    query = db.query(models.CreditCommitment, models.User).join(
        models.User, models.CreditCommitment.user_id == models.User.id
    )
    if status:
        query = query.filter(models.CreditCommitment.status == status)
    if tier:
        query = query.filter(models.CreditCommitment.tier == tier.strip().lower())
    if user_email:
        query = query.filter(models.User.email.ilike(f"%{user_email.strip()}%"))

    total = query.count()
    rows = (
        query.order_by(models.CreditCommitment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "commitments": [serialize_admin_commitment(commitment, user) for commitment, user in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/billing/commitments/overview", response_model=AdminBillingCommitmentsOverviewResponse)
def get_admin_billing_commitments_overview(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    commitments = db.query(models.CreditCommitment).all()
    active_commitments = [item for item in commitments if item.status in {"active", "past_due"}]
    pending_cancellations = sum(1 for item in active_commitments if item.cancel_at_period_end)
    commitment_mrr = sum(
        float(item.monthly_fee_usd or 0) for item in active_commitments
    )  # column stores EUR
    usage_pct_values: list[float] = []
    total_overage_credits = 0
    for commitment in active_commitments:
        active_cycle = next(
            (cycle for cycle in commitment.usage_cycles if cycle.status == "active"), None
        )
        if active_cycle is None:
            continue
        committed_credits = int(active_cycle.committed_credits or 0)
        used_credits = int(active_cycle.credits_used or 0)
        total_overage_credits += int(active_cycle.overage_credits or 0)
        if committed_credits > 0:
            usage_pct_values.append(round((used_credits / committed_credits) * 100, 2))

    average_usage_pct = (
        round(sum(usage_pct_values) / len(usage_pct_values), 2) if usage_pct_values else 0.0
    )
    return {
        "total_commitments": len(commitments),
        "active_commitments": len(active_commitments),
        "pending_cancellations": int(pending_cancellations),
        "commitment_mrr_usd": round(commitment_mrr, 2),
        "average_usage_pct": average_usage_pct,
        "total_overage_credits": int(total_overage_credits),
    }


@router.get("/audits", response_model=AdminAuditListResponse)
def list_admin_audits(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    user_id: int | None = None,
    user_email: str | None = None,
    url_contains: str | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    provider: str | None = None,
    tier: str | None = None,
    grounding_profile: str | None = None,
    dual_track_grounding_enabled: bool | None = None,
    fallback_reason: str | None = None,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 100:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range", "page_size must be between 1 and 100."
            ),
        )

    filters = _build_admin_audit_filters(
        user_id=user_id,
        user_email=user_email,
        url_contains=url_contains,
        start_date=start_date,
        end_date=end_date,
        provider=provider,
        tier=tier,
    )

    query = (
        db.query(models.Audit, models.User)
        .join(models.User, models.Audit.user_id == models.User.id)
        .filter(*filters)
    )

    runtime_filters_active = (
        any(
            value is not None and str(value).strip() != ""
            for value in (grounding_profile, fallback_reason)
        )
        or dual_track_grounding_enabled is not None
    )

    if runtime_filters_active:
        serialized_audits = [
            _serialize_audit_entry(
                audit,
                user.email,
                audit.full_report if isinstance(audit.full_report, dict) else {},
            )
            for audit, user in query.order_by(models.Audit.created_at.desc()).all()
        ]
        filtered_audits = [
            audit_payload
            for audit_payload in serialized_audits
            if _matches_admin_audit_runtime_filters(
                audit_payload,
                grounding_profile=grounding_profile,
                dual_track_grounding_enabled=dual_track_grounding_enabled,
                fallback_reason=fallback_reason,
            )
        ]
        total = len(filtered_audits)
        audits_payload = filtered_audits[(page - 1) * page_size : page * page_size]
    else:
        total = (
            db.query(func.count(models.Audit.id))
            .join(models.User, models.Audit.user_id == models.User.id)
            .filter(*filters)
            .scalar()
            or 0
        )

        audits_payload = [
            _serialize_audit_entry(
                audit,
                user.email,
                audit.full_report if isinstance(audit.full_report, dict) else {},
            )
            for audit, user in (
                query.order_by(models.Audit.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
        ]

    return {
        "audits": audits_payload,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/audits/{audit_id}", response_model=AdminAuditDetailResponse)
def get_admin_audit(
    audit_id: int,
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    include_screenshot: bool = False,
):
    result = (
        db.query(models.Audit, models.User)
        .join(models.User, models.Audit.user_id == models.User.id)
        .filter(models.Audit.id == audit_id)
        .first()
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    audit, user = result
    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    provider, tier, has_screenshot = _get_audit_report_metadata(report)
    runtime_metadata = _extract_admin_audit_runtime_metadata(report)
    if not include_screenshot and report.get("screenshot_base64") is not None:
        report = dict(report)
        report["screenshot_base64"] = None
    subscription_type = (
        user.subscription.plan_type
        if user.subscription is not None
        else report.get("metadata", {}).get("plan")
        if isinstance(report.get("metadata"), dict)
        else None
    )

    return {
        "id": audit.id,
        "user_id": audit.user_id,
        "user_email": user.email,
        "url": audit.url,
        "audit_target_type": _serialize_audit_target_type(audit.audit_target_type),
        "target_name": _coerce_optional_text(audit.target_name),
        "target_url": _coerce_optional_text(audit.target_url) or _coerce_optional_text(audit.url),
        "geo_score": _resolve_audit_score(audit, report, "geo"),
        "seo_score": _resolve_audit_score(audit, report, "seo"),
        "aeo_score": _resolve_audit_score(audit, report, "aeo"),
        "provider": provider,
        "tier": tier,
        **runtime_metadata,
        "subscription_type": subscription_type,
        "credits_used": _extract_credits_used(report),
        "credits_remaining": user.credits,
        "created_at": audit.created_at.isoformat() if audit.created_at else "",
        "sanitized_at": audit.sanitized_at.isoformat() if audit.sanitized_at else None,
        "full_report": report,
        "has_screenshot": has_screenshot,
    }


@router.get("/audits/{audit_id}/debate-trace", response_model=DebateTraceResponse)
def get_admin_debate_trace(
    audit_id: int,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    payload = debate_trace_service.get_timeline(db=db, audit=audit)
    _log_admin_action(
        db,
        admin_user,
        action="audit_debate_trace_viewed",
        target_type="audit",
        target_id=audit_id,
        metadata={"trace_count": payload.get("total_agents", 0)},
    )
    db.commit()
    return payload


@router.get(
    "/audits/{audit_id}/debate-trace/claim/{claim_id}/journey",
    response_model=DebateTraceClaimJourneyResponse,
)
def get_admin_debate_claim_journey(
    audit_id: int,
    claim_id: str,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    payload = debate_trace_service.get_claim_journey(db=db, audit=audit, claim_id=claim_id)
    _log_admin_action(
        db,
        admin_user,
        action="audit_debate_claim_journey_viewed",
        target_type="audit",
        target_id=audit_id,
        metadata={"claim_id": claim_id, "journey_steps": len(payload.get("journey") or [])},
    )
    db.commit()
    return payload


@router.get(
    "/audits/{audit_id}/debate-trace/{role}/output",
    response_model=DebateTraceOutputResponse,
)
def get_admin_debate_trace_output(
    audit_id: int,
    role: str,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    payload = debate_trace_service.get_agent_output(db=db, audit_id=audit_id, role=role)
    if payload is None:
        raise HTTPException(status_code=404, detail="Debate trace output not found.")

    _log_admin_action(
        db,
        admin_user,
        action="audit_debate_trace_output_viewed",
        target_type="audit",
        target_id=audit_id,
        metadata={"agent_role": role},
    )
    db.commit()
    return payload


@router.post("/audits/{audit_id}/sanitize", response_model=AdminAuditSanitizeResponse)
def sanitize_admin_audit(
    audit_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    screenshot_removed = False
    if report.get("screenshot_base64") is not None:
        report = dict(report)
        report["screenshot_base64"] = None
        audit.full_report = report
        screenshot_removed = True

    audit.sanitized_at = datetime.now(timezone.utc)
    _log_admin_action(
        db,
        admin_user,
        action="audit_sanitized",
        target_type="audit",
        target_id=audit.id,
        metadata={
            "screenshot_removed": screenshot_removed,
            "sanitized_at": audit.sanitized_at.isoformat() if audit.sanitized_at else None,
        },
    )
    db.commit()

    return {
        "id": audit.id,
        "sanitized_at": audit.sanitized_at.isoformat() if audit.sanitized_at else None,
        "screenshot_removed": screenshot_removed,
    }


@router.delete("/audits/{audit_id}")
def delete_admin_audit(
    audit_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    deleted = (
        db.query(models.Audit).filter(models.Audit.id == audit_id).delete(synchronize_session=False)
    )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )
    _log_admin_action(
        db,
        admin_user,
        action="audit_deleted",
        target_type="audit",
        target_id=audit_id,
    )
    db.commit()
    return {"deleted": True}


@router.get("/cache-metadata", response_model=CacheMetadataResponse)
async def get_cache_metadata(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    audit_id: int | None = None,
    url: str | None = None,
    provider: str | None = None,
    tier: str | None = None,
):
    resolved_audit_id = audit_id
    if audit_id is not None:
        audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
        if audit is None:
            raise HTTPException(
                status_code=404,
                detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
            )
        url = audit.url
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        report_metadata = report.get("metadata", {}) if isinstance(report, dict) else {}
        provider = report_metadata.get("provider")
        tier = report_metadata.get("tier")
    else:
        if not url or not provider or not tier:
            raise HTTPException(
                status_code=400,
                detail=translate_backend_message(
                    "errors.cache_lookup_params_required",
                    "Provide url, provider, and tier (or an audit_id).",
                ),
            )

    if not provider or not tier or not url:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.cache_lookup_provider_tier_unresolved",
                "Unable to resolve provider/tier for cache lookup.",
            ),
        )

    cache_key = build_audit_cache_key(url, provider, tier)
    async with get_async_redis() as redis_client:
        cached_payload = await redis_client.get(cache_key)

    if not cached_payload:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message(
                "errors.cache_entry_not_found", "Cache entry not found."
            ),
        )

    try:
        cached_entry = json.loads(cached_payload)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.cache_entry_parse_failed", "Cache entry could not be parsed."
            ),
        ) from exc

    cached_metadata = cached_entry.get("metadata", {}) or {}
    return {
        "url": url,
        "provider": provider,
        "tier": tier,
        "cached_at": cached_metadata.get("cached_at"),
        "content_hash": cached_metadata.get("content_hash"),
        "etag": cached_metadata.get("etag"),
        "last_modified": cached_metadata.get("last_modified"),
        "audit_id": resolved_audit_id,
    }


@router.post("/refresh-cache", response_model=CacheRefreshResponse)
async def refresh_cache(
    request: CacheRefreshRequest,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    deleted_keys = 0
    mode = "targeted"

    async with get_async_redis() as redis_client:
        if request.clear_all:
            mode = "all"
            async for cache_key in redis_client.scan_iter(match="audit:cache:*"):
                deleted_keys += await redis_client.delete(cache_key)
        else:
            if not request.url or not request.provider or not request.tier:
                raise HTTPException(
                    status_code=400,
                    detail=translate_backend_message(
                        "errors.cache_refresh_params_required",
                        "Provide url, provider, and tier for targeted cache refresh or set clear_all=true.",
                    ),
                )
            cache_key = build_audit_cache_key(request.url, request.provider, request.tier)
            deleted_keys = await redis_client.delete(cache_key)

    _log_admin_action(
        db,
        admin_user,
        action="cache_refreshed",
        target_type="cache",
        target_id=mode,
        metadata={
            "mode": mode,
            "deleted_keys": deleted_keys,
            "url": request.url,
            "provider": request.provider,
            "tier": request.tier,
        },
    )
    db.commit()
    return {"deleted_keys": deleted_keys, "mode": mode}


DEFAULT_ADMIN_SETTINGS = {
    "integrations": [],
    "api_keys": [],
    "billing_runtime": None,
}

DEFAULT_ROTATION_DAYS = 90
PLACEHOLDER_SECRET_MARKERS = (
    "changeme",
    "change-me",
    "replace-me",
    "replace_me",
    "your_api_key",
    "your-api-key",
    "placeholder",
    "example",
)
INSECURE_SECRET_VALUES = {
    "",
    "dev-secret",
    "change-me",
    "changeme",
    "secret",
    "password",
    "session_secret_fallback",
}

API_KEY_CATALOG = [
    {
        "key": "openai_provider",
        "label": "OpenAI",
        "env_vars": ["OPENAI_API_KEY"],
        "required": True,
        "usage": "Image generation, text generation, and the single fallback when OpenRouter is unavailable.",
    },
    {
        "key": "openrouter_provider",
        "label": "OpenRouter Gateway",
        "env_vars": ["OPENROUTER_API_KEY"],
        "required": False,
        "usage": "Unified LLM gateway (primary) for all text generation. OpenAI is the single fallback when OpenRouter is unavailable.",
    },
    {
        "key": "firecrawl",
        "label": "Firecrawl",
        "env_vars": ["FIRECRAWL_API_KEY"],
        "required": True,
        "usage": "Crawling and source extraction for audits.",
    },
    {
        "key": "serpapi",
        "label": "SerpAPI",
        "env_vars": ["SERPAPI_API_KEY"],
        "required": False,
        "usage": "External competitor SERP intelligence.",
    },
    {
        "key": "google_places",
        "label": "Google Places",
        "env_vars": [
            "GOOGLE_PLACES_API_KEY",
            "GOOGLE_MAPS_API_KEY",
            "GOOGLE_API_KEY",
            "GEMINI_API_KEY",
        ],
        "required": False,
        "usage": "Local competitor discovery enrichment.",
    },
    {
        "key": "stripe_secret",
        "label": "Stripe Secret",
        "env_vars": ["STRIPE_SECRET_KEY_TEST", "STRIPE_SECRET_KEY_LIVE"],
        "required_when": "billing_enabled",
        "usage": "Billing checkout and subscription lifecycle.",
    },
    {
        "key": "stripe_webhook",
        "label": "Stripe Webhook Secret",
        "env_vars": ["STRIPE_WEBHOOK_SECRET_TEST", "STRIPE_WEBHOOK_SECRET_LIVE"],
        "required_when": "billing_enabled",
        "usage": "Validates Stripe webhook payload signatures.",
    },
    {
        "key": "sentry",
        "label": "Sentry DSN",
        "env_vars": [
            "SENTRY_DSN",
            "SENTRY_DSN_AUDIT_API",
            "SENTRY_DSN_AUDIT_WORKER",
            "SENTRY_DSN_AI_SERVICE",
        ],
        "required": False,
        "usage": "Centralized runtime monitoring and error tracing.",
    },
    {
        "key": "pagespeed",
        "label": "PageSpeed API",
        "env_vars": ["PAGESPEED_API_KEY"],
        "required": False,
        "usage": "Expanded performance diagnostics for audits.",
    },
    {
        "key": "search_api",
        "label": "Search API",
        "env_vars": ["SEARCH_API_KEY"],
        "required": False,
        "usage": "Optional GEO visibility provider integration.",
    },
]

INTEGRATION_LABELS = {
    "infrastructure": "Core Infrastructure",
    "ai_runtime": "AI Runtime",
    "cms_generation": "CMS AI Generation",
    "billing": "Billing (Stripe)",
    "oauth": "OAuth Providers",
    "email_delivery": "Email Delivery",
    "competitor_data": "Competitor Data Sources",
    "observability": "Observability",
}

API_KEY_LABEL_TO_KEY = {entry["label"].lower(): entry["key"] for entry in API_KEY_CATALOG}
API_KEY_LABEL_TO_KEY.update(
    {
        "core audit service": "openai_provider",
        "entity graph": "google_places",
        "geo telemetry": "search_api",
    }
)
INTEGRATION_NAME_TO_KEY = {label.lower(): key for key, label in INTEGRATION_LABELS.items()}
EMAIL_FOOTER_URL_FIELDS = (
    "social_facebook_url",
    "social_x_url",
    "social_instagram_url",
    "social_linkedin_url",
    "social_youtube_url",
    "social_tiktok_url",
    "footer_about_url",
    "footer_blog_url",
    "footer_support_url",
    "footer_legal_url",
    "footer_preferences_url",
    "footer_privacy_url",
)
EMAIL_FOOTER_TEXT_FIELDS = (
    "company_address",
    "company_legal_name",
    "company_trademark_text",
)
EMAIL_FOOTER_COLOR_FIELDS = (
    "brand_primary_color",
    "brand_secondary_color",
)
EMAIL_FOOTER_LOGO_FIELDS = (
    "logo_light_url",
    "logo_dark_url",
)
EMAIL_FOOTER_FIELDS = (
    EMAIL_FOOTER_URL_FIELDS
    + EMAIL_FOOTER_TEXT_FIELDS
    + EMAIL_FOOTER_COLOR_FIELDS
    + EMAIL_FOOTER_LOGO_FIELDS
)
VALID_ADMIN_DISPLAY_CURRENCIES: tuple[str, ...] = ("EUR", "USD")


def _resolve_platform_base_url() -> str:
    base_url = os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL") or "https://qiko.ai/signal"
    return str(base_url).strip().rstrip("/")


def _default_admin_email_footer_defaults() -> dict[str, str | None]:
    base_url = _resolve_platform_base_url()
    return {
        "social_facebook_url": None,
        "social_x_url": None,
        "social_instagram_url": None,
        "social_linkedin_url": None,
        "social_youtube_url": None,
        "social_tiktok_url": None,
        "company_address": None,
        "company_legal_name": "Qiko AI Labs FZCO",
        "company_trademark_text": "Qiko Signal is a trademark of Qiko AI Labs FZCO.",
        "footer_about_url": f"{base_url}/about",
        "footer_blog_url": f"{base_url}/blog",
        "footer_support_url": f"{base_url}/contact",
        "footer_legal_url": f"{base_url}/terms",
        "footer_preferences_url": f"{base_url}/preferences",
        "footer_privacy_url": f"{base_url}/privacy",
        "brand_primary_color": None,
        "brand_secondary_color": None,
        "logo_light_url": None,
        "logo_dark_url": None,
    }


def _default_admin_currency_policy() -> dict[str, object]:
    return {"display_currency": "USD"}


def _normalize_admin_currency_code(
    value: object,
    *,
    default: str = "EUR",
) -> str:
    normalized = str(value or default).strip().upper()
    return normalized if normalized in VALID_ADMIN_DISPLAY_CURRENCIES else default


def _normalize_admin_exchange_rate(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return round(parsed, 6)


def _normalize_admin_currency_policy(value: object, *, strict: bool = False) -> dict[str, object]:
    return {"display_currency": "USD"}


def _resolve_admin_currency_policy(
    payload: dict[str, object], *, fx_snapshot: dict[str, Any] | None = None
) -> dict[str, object]:
    return {"display_currency": "USD"}


def _normalize_admin_email_footer_defaults(
    value: object,
    *,
    strict: bool = False,
) -> dict[str, str | None]:
    source = value if isinstance(value, dict) else {}
    normalized: dict[str, str | None] = {}

    for field_name in EMAIL_FOOTER_URL_FIELDS:
        try:
            normalized[field_name] = normalize_optional_url(
                source.get(field_name),
                max_length=512,
            )
        except ValueError as exc:
            if strict:
                raise HTTPException(status_code=422, detail=f"{field_name}: {exc}") from exc
            normalized[field_name] = None

    normalized["company_address"] = normalize_optional_text(
        source.get("company_address"),
        max_length=1000,
    )
    normalized["company_legal_name"] = normalize_optional_text(
        source.get("company_legal_name"),
        max_length=255,
    )
    normalized["company_trademark_text"] = normalize_optional_text(
        source.get("company_trademark_text"),
        max_length=512,
    )

    for color_field in EMAIL_FOOTER_COLOR_FIELDS:
        raw = str(source.get(color_field) or "").strip()
        if (
            raw
            and len(raw) in (4, 7)
            and raw.startswith("#")
            and all(c in "0123456789abcdefABCDEF" for c in raw[1:])
        ):
            normalized[color_field] = raw
        else:
            normalized[color_field] = None

    for logo_field in EMAIL_FOOTER_LOGO_FIELDS:
        try:
            normalized[logo_field] = normalize_optional_url(
                source.get(logo_field),
                max_length=1024,
            )
        except ValueError as exc:
            if strict:
                raise HTTPException(status_code=422, detail=f"{logo_field}: {exc}") from exc
            normalized[logo_field] = None

    return normalized


def _resolve_admin_email_footer_defaults(payload: dict[str, object]) -> dict[str, str | None]:
    defaults = _default_admin_email_footer_defaults()
    raw_footer = payload.get("email_footer_defaults")
    if not isinstance(raw_footer, dict):
        return defaults

    normalized_footer = _normalize_admin_email_footer_defaults(raw_footer)
    for field_name in EMAIL_FOOTER_FIELDS:
        if field_name in raw_footer:
            defaults[field_name] = normalized_footer[field_name]
    return defaults


def _normalize_admin_text(value: object, *, max_length: int = 260) -> str:
    text_value = str(value or "").strip()
    if len(text_value) > max_length:
        return text_value[:max_length].strip()
    return text_value


def _normalize_rotation_days(value: object) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    if parsed < 7 or parsed > 3650:
        return None
    return parsed


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_placeholder_secret(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered in PLACEHOLDER_SECRET_MARKERS:
        return True
    return any(marker in lowered for marker in PLACEHOLDER_SECRET_MARKERS)


def _pick_env_value(env_vars: list[str]) -> tuple[str | None, str | None]:
    for env_var in env_vars:
        raw_value = os.getenv(env_var)
        if raw_value is None:
            continue
        trimmed = raw_value.strip()
        if trimmed:
            return trimmed, env_var
    return None, None


def _pick_env_or_db_value(env_vars: list[str], db: Session) -> tuple[str | None, str | None, str]:
    """Resolve env_vars with DB-override priority.

    Resolution chain: DB section first (across all vars), then os.getenv.
    Returns (value, env_var_name, source) where source is 'db' | 'env' | 'unset'.
    Only values explicitly stored in a DB section are labelled 'db'.
    """
    from core.db_settings_resolver import ENV_TO_DB_MAP, get_section

    # Pass 1, DB sections only (no env fallback)
    for env_var in env_vars:
        mapping = ENV_TO_DB_MAP.get(env_var)
        if not mapping:
            continue
        section, field = mapping
        section_data = get_section(section, db)
        val = section_data.get(field)
        if val is not None and str(val).strip():
            return str(val).strip(), env_var, "db"

    # Pass 2, raw env vars
    for env_var in env_vars:
        raw = os.getenv(env_var)
        if raw and raw.strip():
            return raw.strip(), env_var, "env"

    return None, None, "unset"


def _append_admin_note(runtime_note: str, override_note: str) -> str:
    if not override_note:
        return runtime_note
    if runtime_note:
        return f"{runtime_note} Admin note: {override_note}"
    return f"Admin note: {override_note}"


async def _check_redis_connection() -> tuple[bool, str]:
    async with get_async_redis(socket_timeout=1, socket_connect_timeout=1) as client:
        try:
            await client.ping()
            return True, "Redis ping successful."
        except Exception as exc:  # pragma: no cover - depends on runtime network
            return False, f"Redis check failed: {exc}"


def _resolve_redis_health() -> tuple[bool, str]:
    try:
        return asyncio.run(_check_redis_connection())
    except RuntimeError:
        return True, "Redis URL configured. Live ping skipped in current runtime."
    except Exception as exc:  # pragma: no cover - defensive fallback
        return False, f"Redis check failed: {exc}"


def _normalize_admin_settings_payload(payload: dict | None) -> dict[str, object]:
    source = payload if isinstance(payload, dict) else {}
    integrations = source.get("integrations")
    api_keys = source.get("api_keys")
    billing_runtime_raw = source.get("billing_runtime")
    email_footer_defaults_raw = source.get("email_footer_defaults")
    currency_policy_raw = source.get("currency_policy")

    normalized_integrations: list[dict[str, object]] = []
    integration_index: dict[str, int] = {}
    if isinstance(integrations, list):
        for item in integrations:
            if not isinstance(item, dict):
                continue
            raw_key = _normalize_admin_text(item.get("key"), max_length=80).lower()
            raw_name = _normalize_admin_text(item.get("name"), max_length=120).lower()
            resolved_key = raw_key or INTEGRATION_NAME_TO_KEY.get(raw_name)
            if not resolved_key:
                continue
            normalized_entry = {
                "key": resolved_key,
                "note": _normalize_admin_text(item.get("note"), max_length=320),
            }
            if resolved_key in integration_index:
                normalized_integrations[integration_index[resolved_key]] = normalized_entry
            else:
                integration_index[resolved_key] = len(normalized_integrations)
                normalized_integrations.append(normalized_entry)
    normalized_integrations.sort(key=lambda item: str(item.get("key") or ""))

    normalized_api_keys: list[dict[str, object]] = []
    api_key_index: dict[str, int] = {}
    if isinstance(api_keys, list):
        for item in api_keys:
            if not isinstance(item, dict):
                continue
            raw_key = _normalize_admin_text(item.get("key"), max_length=80).lower()
            raw_label = _normalize_admin_text(item.get("label"), max_length=160).lower()
            resolved_key = raw_key or API_KEY_LABEL_TO_KEY.get(raw_label)
            if not resolved_key:
                continue
            normalized_entry = {
                "key": resolved_key,
                "note": _normalize_admin_text(item.get("note"), max_length=320),
                "owner": _normalize_admin_text(item.get("owner"), max_length=120) or None,
                "rotation_days": _normalize_rotation_days(item.get("rotation_days")),
            }
            if resolved_key in api_key_index:
                normalized_api_keys[api_key_index[resolved_key]] = normalized_entry
            else:
                api_key_index[resolved_key] = len(normalized_api_keys)
                normalized_api_keys.append(normalized_entry)
    normalized_api_keys.sort(key=lambda item: str(item.get("key") or ""))

    normalized_payload: dict[str, object] = {
        "integrations": normalized_integrations,
        "api_keys": normalized_api_keys,
    }

    if is_billing_runtime_payload_meaningful(billing_runtime_raw):
        normalized_runtime = normalize_billing_runtime_payload(billing_runtime_raw)
        if not isinstance(billing_runtime_raw, dict) or "stripe_mode" not in billing_runtime_raw:
            normalized_runtime.pop("stripe_mode", None)
        if (
            not isinstance(billing_runtime_raw, dict)
            or "billing_enabled" not in billing_runtime_raw
        ):
            normalized_runtime.pop("billing_enabled", None)
        normalized_payload["billing_runtime"] = normalized_runtime

    if "email_footer_defaults" in source:
        normalized_payload["email_footer_defaults"] = _normalize_admin_email_footer_defaults(
            email_footer_defaults_raw
        )

    if "currency_policy" in source:
        normalized_payload["currency_policy"] = _normalize_admin_currency_policy(
            currency_policy_raw
        )

    if "ai_cost_fx" in source:
        normalized_payload["ai_cost_fx"] = {}

    # Pass through sections managed by db_settings_resolver and other
    # dynamic sections that are written independently of this normalizer.
    for _passthrough_key in (
        "runtime_config",
        "feature_switches",
        "maintenance",
        "ai_provider_keys",
        "search_config",
        "email_config",
        "oauth_config",
        "cloudflare_config",
        "support_info",
    ):
        if _passthrough_key in source:
            raw = source[_passthrough_key]
            if isinstance(raw, dict) and raw:
                normalized_payload[_passthrough_key] = raw

    return normalized_payload


def _resolve_api_key_required(
    spec: dict[str, object], *, billing_enabled: bool, email_provider: str
) -> bool:
    required_when = str(spec.get("required_when") or "").strip()
    if required_when == "billing_enabled":
        return billing_enabled
    return bool(spec.get("required", False))


def _build_runtime_api_key_entries(
    api_key_overrides: dict[str, dict[str, object]],
    *,
    db: Session,
    billing_enabled: bool,
    email_provider: str,
    billing_config,
    checked_at: str,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for spec in API_KEY_CATALOG:
        key = str(spec["key"])
        env_vars = list(spec.get("env_vars", []))
        if key == "stripe_secret":
            raw_secret = billing_config.stripe_secret_key
            source_env = f"STRIPE_SECRET_KEY_{billing_config.stripe_mode.upper()}"
            db_source = "runtime" if billing_config.has_runtime_override else "env"
        elif key == "stripe_webhook":
            raw_secret = billing_config.stripe_webhook_secret
            source_env = f"STRIPE_WEBHOOK_SECRET_{billing_config.stripe_mode.upper()}"
            db_source = "runtime" if billing_config.has_runtime_override else "env"
        else:
            raw_secret, source_env, db_source = _pick_env_or_db_value(env_vars, db)

        placeholder = bool(raw_secret and _looks_like_placeholder_secret(raw_secret))
        configured = bool(raw_secret) and not placeholder
        required = _resolve_api_key_required(
            spec,
            billing_enabled=billing_enabled,
            email_provider=email_provider,
        )

        if configured:
            status = "configured"
            recommended_action = "Configured."
        elif placeholder:
            status = "placeholder"
            recommended_action = (
                f"Replace placeholder value in {source_env or env_vars[0]} with a valid secret."
            )
        elif required:
            status = "missing"
            recommended_action = f"Set {', '.join(env_vars)} and redeploy backend services."
        else:
            status = "missing"
            recommended_action = f"Optional: set {', '.join(env_vars)} to enable this integration."

        override = api_key_overrides.get(key, {})
        rotation_days = (
            _normalize_rotation_days(override.get("rotation_days")) or DEFAULT_ROTATION_DAYS
        )
        action_required = status in {"placeholder"} or (required and status != "configured")

        entries.append(
            {
                "key": key,
                "label": str(spec["label"]),
                "env_var": source_env or env_vars[0],
                "configured": configured,
                "required": required,
                "status": status,
                "source": db_source,
                "last_four": mask_secret_tail(raw_secret),
                "note": _normalize_admin_text(override.get("note"), max_length=320),
                "owner": _normalize_admin_text(override.get("owner"), max_length=120) or None,
                "rotation_days": rotation_days,
                "usage": str(spec.get("usage") or ""),
                "recommended_action": recommended_action,
                "action_required": action_required,
                "last_checked_at": checked_at,
            }
        )
    return entries


def _find_api_key_entry(
    api_keys: list[dict[str, object]],
    key: str,
) -> dict[str, object]:
    for entry in api_keys:
        if str(entry.get("key")) == key:
            return entry
    return {}


def _build_runtime_integrations(
    db: Session,
    integration_overrides: dict[str, dict[str, object]],
    api_keys: list[dict[str, object]],
    *,
    billing_enabled: bool,
    billing_config,
    checked_at: str,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []

    def api_configured(api_key: str) -> bool:
        return bool(_find_api_key_entry(api_keys, api_key).get("configured"))

    def override_note(key: str) -> str:
        return _normalize_admin_text(
            integration_overrides.get(key, {}).get("note"),
            max_length=320,
        )

    database_ok = True
    database_note = "Database connection healthy."
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        database_ok = False
        database_note = f"Database check failed: {exc}"

    redis_ok, redis_note = _resolve_redis_health()
    if database_ok and redis_ok:
        infra_status = "Connected"
    elif database_ok or redis_ok:
        infra_status = "Degraded"
    else:
        infra_status = "Missing"
    entries.append(
        {
            "key": "infrastructure",
            "name": INTEGRATION_LABELS["infrastructure"],
            "status": infra_status,
            "note": _append_admin_note(
                f"{database_note} {redis_note}", override_note("infrastructure")
            ),
            "admin_note": override_note("infrastructure"),
            "action_required": infra_status in {"Degraded", "Missing"},
            "last_checked_at": checked_at,
        }
    )

    openrouter_ready = api_configured("openrouter_provider")
    openai_ready = api_configured("openai_provider")
    if openrouter_ready and openai_ready:
        ai_status = "Connected"
        ai_note = "OpenRouter gateway (primary) configured with OpenAI fallback."
    elif openrouter_ready:
        ai_status = "Connected"
        ai_note = "OpenRouter gateway configured (no OpenAI fallback key set)."
    elif openai_ready:
        ai_status = "Connected"
        ai_note = "OpenAI configured (image, text and fallback). OpenRouter gateway not set."
    else:
        ai_status = "Missing"
        ai_note = "No AI provider is configured (set OPENROUTER_API_KEY and/or OPENAI_API_KEY)."
    entries.append(
        {
            "key": "ai_runtime",
            "name": INTEGRATION_LABELS["ai_runtime"],
            "status": ai_status,
            "note": _append_admin_note(ai_note, override_note("ai_runtime")),
            "admin_note": override_note("ai_runtime"),
            "action_required": ai_status in {"Degraded", "Missing"},
            "last_checked_at": checked_at,
        }
    )

    from core.config import settings as app_settings

    cms_text_model = str(getattr(app_settings, "OPENAI_SMART_MODEL", "") or "gpt-4.1")
    cms_image_model = str(
        os.getenv("OPENAI_IMAGE_MODEL")
        or getattr(app_settings, "OPENAI_IMAGE_MODEL", "")
        or "gpt-image-1"
    )
    cms_status = "Connected" if openai_ready else "Missing"
    cms_note = (
        f"Text model: {cms_text_model}. Image model: {cms_image_model} (OpenAI)."
        if openai_ready
        else "OpenAI key missing; CMS falls back to local draft templates."
    )
    entries.append(
        {
            "key": "cms_generation",
            "name": INTEGRATION_LABELS["cms_generation"],
            "status": cms_status,
            "note": _append_admin_note(cms_note, override_note("cms_generation")),
            "admin_note": override_note("cms_generation"),
            "action_required": cms_status == "Missing",
            "last_checked_at": checked_at,
        }
    )

    if not billing_enabled:
        billing_status = "Disabled"
        billing_note = "Billing feature flag is disabled."
    else:
        missing_parts: list[str] = []
        if not billing_config.stripe_secret_key:
            missing_parts.append(f"missing Stripe secret key for {billing_config.stripe_mode} mode")
        if not billing_config.stripe_webhook_secret:
            missing_parts.append(f"missing webhook secret for {billing_config.stripe_mode} mode")
        missing_prices = [
            plan for plan in PUBLIC_PLAN_TYPES if not billing_config.price_id_for(Plan(plan))
        ]
        if missing_prices:
            missing_parts.append(
                f"missing Stripe prices for plans in {billing_config.stripe_mode} mode: {', '.join(missing_prices)}"
            )
        if not missing_parts:
            billing_status = "Connected"
            billing_note = f"Stripe ready in {billing_config.stripe_mode} mode" + (
                " (runtime override)." if billing_config.has_runtime_override else "."
            )
        elif billing_config.stripe_secret_key:
            billing_status = "Degraded"
            billing_note = "Billing partially configured: " + "; ".join(missing_parts)
        else:
            billing_status = "Missing"
            billing_note = "Billing not ready: " + "; ".join(missing_parts)
    entries.append(
        {
            "key": "billing",
            "name": INTEGRATION_LABELS["billing"],
            "status": billing_status,
            "note": _append_admin_note(billing_note, override_note("billing")),
            "admin_note": override_note("billing"),
            "action_required": billing_enabled and billing_status in {"Degraded", "Missing"},
            "last_checked_at": checked_at,
        }
    )

    def _resolve_oauth(key: str) -> str:
        val, _, _ = _pick_env_or_db_value([key], db)
        return val or ""

    oauth_provider_statuses = {
        "Google": bool(
            _resolve_oauth("GOOGLE_CLIENT_ID") and _resolve_oauth("GOOGLE_CLIENT_SECRET")
        ),
        "GitHub": bool(
            _resolve_oauth("GITHUB_CLIENT_ID") and _resolve_oauth("GITHUB_CLIENT_SECRET")
        ),
        "Microsoft/Azure": bool(
            (_resolve_oauth("MICROSOFT_SSO_CLIENT_ID") or _resolve_oauth("BING_CLIENT_ID"))
            and (
                _resolve_oauth("MICROSOFT_SSO_CLIENT_SECRET")
                or _resolve_oauth("BING_CLIENT_SECRET")
            )
        ),
        "LinkedIn": bool(
            _resolve_oauth("LINKEDIN_CLIENT_ID") and _resolve_oauth("LINKEDIN_CLIENT_SECRET")
        ),
    }
    configured_oauth_providers = [
        provider_name for provider_name, is_ready in oauth_provider_statuses.items() if is_ready
    ]
    if len(configured_oauth_providers) == len(oauth_provider_statuses):
        oauth_status = "Connected"
        oauth_note = "Google, GitHub, Microsoft/Azure, and LinkedIn OAuth are configured."
    elif configured_oauth_providers:
        oauth_status = "Degraded"
        oauth_note = (
            "OAuth providers are partially configured ("
            + ", ".join(
                f"{provider_name}: {'yes' if is_ready else 'no'}"
                for provider_name, is_ready in oauth_provider_statuses.items()
            )
            + ")."
        )
    else:
        oauth_status = "Missing"
        oauth_note = "No OAuth provider is configured."
    entries.append(
        {
            "key": "oauth",
            "name": INTEGRATION_LABELS["oauth"],
            "status": oauth_status,
            "note": _append_admin_note(oauth_note, override_note("oauth")),
            "admin_note": override_note("oauth"),
            "action_required": oauth_status in {"Degraded", "Missing"},
            "last_checked_at": checked_at,
        }
    )

    from core.config import settings as app_settings

    email_provider = str(app_settings.EMAIL_PROVIDER or "smtp").strip().lower()
    if email_provider == "smtp":
        missing_smtp = [
            env_var
            for env_var in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD")
            if not str(getattr(app_settings, env_var, "") or "").strip()
        ]
        if missing_smtp:
            email_status = "Missing"
            email_note = f"SMTP provider selected. Missing: {', '.join(missing_smtp)}."
        else:
            email_status = "Connected"
            email_note = "SMTP provider is configured."
    else:
        email_status = "Missing"
        email_note = f"Unsupported EMAIL_PROVIDER '{email_provider}'."
    entries.append(
        {
            "key": "email_delivery",
            "name": INTEGRATION_LABELS["email_delivery"],
            "status": email_status,
            "note": _append_admin_note(email_note, override_note("email_delivery")),
            "admin_note": override_note("email_delivery"),
            "action_required": email_status == "Missing",
            "last_checked_at": checked_at,
        }
    )

    serpapi_ready = api_configured("serpapi")
    places_ready = api_configured("google_places")
    if serpapi_ready and places_ready:
        competitor_status = "Connected"
        competitor_note = "SerpAPI and Google Places are configured."
    elif serpapi_ready or places_ready:
        competitor_status = "Degraded"
        competitor_note = (
            "Only one competitor data source is configured "
            f"(SerpAPI: {'yes' if serpapi_ready else 'no'}, "
            f"Google Places: {'yes' if places_ready else 'no'})."
        )
    else:
        competitor_status = "Missing"
        competitor_note = "No external competitor data source key is configured."
    entries.append(
        {
            "key": "competitor_data",
            "name": INTEGRATION_LABELS["competitor_data"],
            "status": competitor_status,
            "note": _append_admin_note(competitor_note, override_note("competitor_data")),
            "admin_note": override_note("competitor_data"),
            "action_required": competitor_status == "Missing",
            "last_checked_at": checked_at,
        }
    )

    tracing_backend = (os.getenv("TRACING_BACKEND", "none") or "none").strip().lower()
    sentry_ready = api_configured("sentry")
    if tracing_backend == "sentry" and not sentry_ready:
        observability_status = "Missing"
        observability_note = (
            "TRACING_BACKEND=sentry but no Sentry DSN is configured "
            "(SENTRY_DSN or service-specific SENTRY_DSN_*)."
        )
    elif tracing_backend == "none" and not sentry_ready:
        observability_status = "Degraded"
        observability_note = "No external observability backend configured."
    else:
        observability_status = "Connected"
        observability_note = f"Tracing backend: {tracing_backend}."
    entries.append(
        {
            "key": "observability",
            "name": INTEGRATION_LABELS["observability"],
            "status": observability_status,
            "note": _append_admin_note(observability_note, override_note("observability")),
            "admin_note": override_note("observability"),
            "action_required": observability_status == "Missing",
            "last_checked_at": checked_at,
        }
    )

    return entries


def _build_security_checks() -> list[dict[str, object]]:
    from core.config import settings

    checks: list[dict[str, object]] = []

    access_secret = (settings.JWT_SECRET_KEY or "").strip()
    if access_secret.lower() in INSECURE_SECRET_VALUES:
        checks.append(
            {
                "key": "jwt_access_secret",
                "label": "JWT access secret",
                "status": "fail",
                "details": "JWT_SECRET_KEY is missing or using a known insecure default.",
                "action_required": True,
            }
        )
    else:
        checks.append(
            {
                "key": "jwt_access_secret",
                "label": "JWT access secret",
                "status": "pass",
                "details": "JWT access token secret looks configured.",
                "action_required": False,
            }
        )

    refresh_secret = (settings.JWT_REFRESH_SECRET_KEY or access_secret).strip()
    if refresh_secret.lower() in INSECURE_SECRET_VALUES:
        checks.append(
            {
                "key": "jwt_refresh_secret",
                "label": "JWT refresh secret",
                "status": "fail",
                "details": "JWT_REFRESH_SECRET_KEY is missing or insecure.",
                "action_required": True,
            }
        )
    elif refresh_secret == access_secret:
        checks.append(
            {
                "key": "jwt_refresh_secret",
                "label": "JWT refresh secret",
                "status": "warn",
                "details": "Refresh secret matches access secret. Use a dedicated secret.",
                "action_required": True,
            }
        )
    else:
        checks.append(
            {
                "key": "jwt_refresh_secret",
                "label": "JWT refresh secret",
                "status": "pass",
                "details": "Refresh secret is configured separately.",
                "action_required": False,
            }
        )

    from core.config import settings as app_settings

    admin_allowlist = str(app_settings.ADMIN_EMAILS or "").strip()
    if not admin_allowlist:
        checks.append(
            {
                "key": "admin_allowlist",
                "label": "Admin allowlist",
                "status": "warn",
                "details": "ADMIN_EMAILS is empty. Admin role promotion allowlist is not configured.",
                "action_required": True,
            }
        )
    else:
        checks.append(
            {
                "key": "admin_allowlist",
                "label": "Admin allowlist",
                "status": "pass",
                "details": "ADMIN_EMAILS allowlist is configured.",
                "action_required": False,
            }
        )

    mfa_issuer = str(app_settings.MFA_ISSUER or "Qiko Signal").strip()
    checks.append(
        {
            "key": "mfa_issuer",
            "label": "MFA issuer",
            "status": "warn" if mfa_issuer.lower() == "Qiko Signal" else "pass",
            "details": (
                "Using default MFA issuer. Set MFA_ISSUER for your deployment brand."
                if mfa_issuer.lower() == "Qiko Signal"
                else f"MFA issuer configured as '{mfa_issuer}'."
            ),
            "action_required": mfa_issuer.lower() == "Qiko Signal",
        }
    )

    raw_ttl = (os.getenv("MFA_SETUP_TOKEN_EXPIRE_SECONDS") or "600").strip()
    try:
        ttl_seconds = int(raw_ttl)
    except ValueError:
        ttl_seconds = 600
        status = "warn"
        details = f"Invalid MFA_SETUP_TOKEN_EXPIRE_SECONDS '{raw_ttl}'. Using default 600."
        action_required = True
    else:
        if ttl_seconds < 300 or ttl_seconds > 1800:
            status = "warn"
            details = (
                f"MFA setup token TTL is {ttl_seconds}s. Recommended range is 300-1800 seconds."
            )
            action_required = True
        else:
            status = "pass"
            details = f"MFA setup token TTL is {ttl_seconds}s."
            action_required = False
    checks.append(
        {
            "key": "mfa_setup_ttl",
            "label": "MFA setup token TTL",
            "status": status,
            "details": details,
            "action_required": action_required,
        }
    )

    # -------------------------------------------------------------------
    # SEC-01: Session secret strength
    # -------------------------------------------------------------------
    session_secret = (settings.SESSION_SECRET_KEY or "").strip()
    jwt_secret = (settings.JWT_SECRET_KEY or "").strip()
    if not session_secret or session_secret.lower() in INSECURE_SECRET_VALUES:
        checks.append(
            {
                "key": "session_secret",
                "label": "Session secret (SEC-01)",
                "status": "fail",
                "details": "SESSION_SECRET_KEY is missing or uses a known insecure default.",
                "action_required": True,
            }
        )
    elif len(session_secret) < 32:
        checks.append(
            {
                "key": "session_secret",
                "label": "Session secret (SEC-01)",
                "status": "warn",
                "details": f"SESSION_SECRET_KEY is only {len(session_secret)} chars. Minimum 32 recommended.",
                "action_required": True,
            }
        )
    elif session_secret == jwt_secret:
        checks.append(
            {
                "key": "session_secret",
                "label": "Session secret (SEC-01)",
                "status": "warn",
                "details": "SESSION_SECRET_KEY matches JWT_SECRET_KEY. Use a dedicated secret.",
                "action_required": True,
            }
        )
    else:
        checks.append(
            {
                "key": "session_secret",
                "label": "Session secret (SEC-01)",
                "status": "pass",
                "details": "Session secret is configured and distinct from JWT secret.",
                "action_required": False,
            }
        )

    # -------------------------------------------------------------------
    # SEC-02 / SEC-11: CSP mode
    # -------------------------------------------------------------------
    # The frontend middleware sets Content-Security-Policy (enforcing) or
    # Content-Security-Policy-Report-Only.  We expose the *intended* mode
    # based on the codebase default after SEC-11 promotion.
    checks.append(
        {
            "key": "csp_mode",
            "label": "CSP mode (SEC-02/11)",
            "status": "pass",
            "details": "Content-Security-Policy is in enforcing mode with report-uri.",
            "action_required": False,
        }
    )

    # -------------------------------------------------------------------
    # SEC-04: Redis auth & TLS status
    # -------------------------------------------------------------------
    redis_url = (os.getenv("REDIS_URL") or "redis://redis:6379").strip()
    from urllib.parse import urlparse as _urlparse

    _parsed_redis = _urlparse(redis_url)
    redis_has_auth = bool(_parsed_redis.password)
    redis_has_tls = _parsed_redis.scheme in ("rediss", "rediss+sentinel")
    if not redis_has_auth:
        checks.append(
            {
                "key": "redis_auth",
                "label": "Redis auth (SEC-04)",
                "status": "warn",
                "details": "REDIS_URL has no password. Production Redis should require authentication.",
                "action_required": app_settings.ENVIRONMENT != "development",
            }
        )
    else:
        checks.append(
            {
                "key": "redis_auth",
                "label": "Redis auth (SEC-04)",
                "status": "pass",
                "details": "Redis URL includes authentication credentials.",
                "action_required": False,
            }
        )

    checks.append(
        {
            "key": "redis_tls",
            "label": "Redis TLS (SEC-04)",
            "status": "pass" if redis_has_tls else "warn",
            "details": (
                "Redis connection uses TLS (rediss://)."
                if redis_has_tls
                else "Redis connection does not use TLS. Consider enabling TLS for production."
            ),
            "action_required": False,
        }
    )

    # -------------------------------------------------------------------
    # SEC-09: SSRF protection
    # -------------------------------------------------------------------
    try:
        from services.url_validation import safe_async_fetch  # noqa: F401

        ssrf_status = "pass"
        ssrf_details = "SSRF protection (safe_async_fetch) is available."
    except ImportError:
        ssrf_status = "fail"
        ssrf_details = "SSRF guard module not found. Internal network is unprotected."
    checks.append(
        {
            "key": "ssrf_protection",
            "label": "SSRF protection (SEC-09)",
            "status": ssrf_status,
            "details": ssrf_details,
            "action_required": ssrf_status != "pass",
        }
    )

    # -------------------------------------------------------------------
    # SEC-02: Security headers middleware
    # -------------------------------------------------------------------
    try:
        from middleware.security_headers import SecurityHeadersMiddleware  # noqa: F401

        sec_headers_status = "pass"
        sec_headers_details = "SecurityHeadersMiddleware is importable and registered."
    except ImportError:
        sec_headers_status = "fail"
        sec_headers_details = (
            "SecurityHeadersMiddleware not found. Security headers may be missing."
        )
    checks.append(
        {
            "key": "security_headers_middleware",
            "label": "Security headers (SEC-02)",
            "status": sec_headers_status,
            "details": sec_headers_details,
            "action_required": sec_headers_status != "pass",
        }
    )

    return checks


def _build_admin_settings_summary(
    integrations: list[dict[str, object]],
    api_keys: list[dict[str, object]],
    security_checks: list[dict[str, object]],
    *,
    generated_at: str,
) -> dict[str, object]:
    connected_integrations = sum(1 for item in integrations if item.get("status") == "Connected")
    degraded_integrations = sum(1 for item in integrations if item.get("status") == "Degraded")
    missing_integrations = sum(1 for item in integrations if item.get("status") == "Missing")
    disabled_integrations = sum(1 for item in integrations if item.get("status") == "Disabled")
    configured_api_keys = sum(1 for item in api_keys if bool(item.get("configured")))
    missing_required_api_keys = sum(
        1 for item in api_keys if bool(item.get("required")) and not bool(item.get("configured"))
    )
    placeholder_api_keys = sum(1 for item in api_keys if item.get("status") == "placeholder")
    open_security_issues = sum(1 for item in security_checks if bool(item.get("action_required")))

    return {
        "total_integrations": len(integrations),
        "connected_integrations": connected_integrations,
        "degraded_integrations": degraded_integrations,
        "missing_integrations": missing_integrations,
        "disabled_integrations": disabled_integrations,
        "total_api_keys": len(api_keys),
        "configured_api_keys": configured_api_keys,
        "missing_required_api_keys": missing_required_api_keys,
        "placeholder_api_keys": placeholder_api_keys,
        "open_security_issues": open_security_issues,
        "generated_at": generated_at,
    }


def _build_admin_settings_recommendations(
    integrations: list[dict[str, object]],
    api_keys: list[dict[str, object]],
    security_checks: list[dict[str, object]],
) -> list[str]:
    recommendations: list[str] = []
    seen: set[str] = set()

    def add_recommendation(message: str) -> None:
        normalized = message.strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        recommendations.append(normalized)

    required_missing = [
        str(item.get("env_var"))
        for item in api_keys
        if bool(item.get("required")) and not bool(item.get("configured"))
    ]
    if required_missing:
        add_recommendation(f"Configure required secrets: {', '.join(required_missing)}.")

    placeholder_vars = [
        str(item.get("env_var")) for item in api_keys if item.get("status") == "placeholder"
    ]
    if placeholder_vars:
        add_recommendation(f"Replace placeholder secret values: {', '.join(placeholder_vars)}.")

    failing_integrations = [
        str(item.get("name"))
        for item in integrations
        if bool(item.get("action_required")) and item.get("status") in {"Degraded", "Missing"}
    ]
    if failing_integrations:
        add_recommendation(
            "Resolve degraded integrations: " + ", ".join(failing_integrations) + "."
        )

    security_items = [
        str(item.get("label")) for item in security_checks if bool(item.get("action_required"))
    ]
    if security_items:
        add_recommendation("Address security checks: " + ", ".join(security_items) + ".")

    if not recommendations:
        add_recommendation("All critical configuration checks are healthy.")

    return recommendations


def _get_admin_settings(db: Session) -> dict[str, object]:
    from core.config import settings as app_settings

    settings = _get_operational_settings(db)
    normalized_payload = _normalize_admin_settings_payload(settings.admin_settings_payload)
    if settings.admin_settings_payload != normalized_payload:
        settings.admin_settings_payload = normalized_payload
        db.commit()
        db.refresh(settings)

    checked_at = datetime.now(timezone.utc).isoformat()
    billing_config = load_billing_config(db=db)
    billing_enabled = billing_config.billing_enabled
    email_provider = str(app_settings.EMAIL_PROVIDER or "smtp").strip().lower()
    integration_overrides = {
        str(item.get("key")): item
        for item in normalized_payload.get("integrations", [])
        if str(item.get("key") or "").strip()
    }
    api_key_overrides = {
        str(item.get("key")): item
        for item in normalized_payload.get("api_keys", [])
        if str(item.get("key") or "").strip()
    }

    api_key_entries = _build_runtime_api_key_entries(
        api_key_overrides,
        db=db,
        billing_enabled=billing_enabled,
        email_provider=email_provider,
        billing_config=billing_config,
        checked_at=checked_at,
    )
    integration_entries = _build_runtime_integrations(
        db,
        integration_overrides,
        api_key_entries,
        billing_enabled=billing_enabled,
        billing_config=billing_config,
        checked_at=checked_at,
    )
    security_checks = _build_security_checks()
    email_footer_defaults = _resolve_admin_email_footer_defaults(normalized_payload)
    fx_snapshot = _get_admin_ai_cost_fx_snapshot(db)
    currency_policy = _resolve_admin_currency_policy(normalized_payload, fx_snapshot=fx_snapshot)
    summary = _build_admin_settings_summary(
        integration_entries,
        api_key_entries,
        security_checks,
        generated_at=checked_at,
    )
    recommendations = _build_admin_settings_recommendations(
        integration_entries,
        api_key_entries,
        security_checks,
    )
    return {
        "integrations": integration_entries,
        "api_keys": api_key_entries,
        "security_checks": security_checks,
        "recommendations": recommendations,
        "email_footer_defaults": email_footer_defaults,
        "currency_policy": currency_policy,
        "ai_cost_fx": _serialize_admin_fx_reference(fx_snapshot),
        "summary": summary,
    }


@router.get("/settings", response_model=AdminSettingsResponse)
def get_admin_settings(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    return _get_admin_settings(db)


@router.patch("/settings", response_model=AdminSettingsResponse)
def update_admin_settings(
    payload: AdminSettingsPatchRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    settings = _get_operational_settings(db)
    current = _normalize_admin_settings_payload(settings.admin_settings_payload)

    if payload.integrations is not None:
        integration_overrides = {
            str(item.get("key")): item
            for item in current.get("integrations", [])
            if str(item.get("key") or "").strip()
        }
        for item in payload.integrations:
            key = _normalize_admin_text(item.key, max_length=80).lower()
            if not key:
                key = (
                    INTEGRATION_NAME_TO_KEY.get(
                        _normalize_admin_text(item.name, max_length=120).lower()
                    )
                    or ""
                )
            if not key:
                continue
            integration_overrides[key] = {
                "key": key,
                "note": _normalize_admin_text(item.note, max_length=320),
            }
        current["integrations"] = sorted(
            integration_overrides.values(),
            key=lambda entry: str(entry.get("key") or ""),
        )

    if payload.api_keys is not None:
        api_key_overrides = {
            str(item.get("key")): item
            for item in current.get("api_keys", [])
            if str(item.get("key") or "").strip()
        }
        for item in payload.api_keys:
            key = _normalize_admin_text(item.key, max_length=80).lower()
            if not key:
                key = (
                    API_KEY_LABEL_TO_KEY.get(
                        _normalize_admin_text(item.label, max_length=160).lower()
                    )
                    or ""
                )
            if not key:
                continue
            api_key_overrides[key] = {
                "key": key,
                "note": _normalize_admin_text(item.note, max_length=320),
                "owner": _normalize_admin_text(item.owner, max_length=120) or None,
                "rotation_days": _normalize_rotation_days(item.rotation_days),
            }
        current["api_keys"] = sorted(
            api_key_overrides.values(),
            key=lambda entry: str(entry.get("key") or ""),
        )

    if payload.email_footer_defaults is not None:
        current["email_footer_defaults"] = _normalize_admin_email_footer_defaults(
            payload.email_footer_defaults.model_dump(),
            strict=True,
        )

    settings.admin_settings_payload = _normalize_admin_settings_payload(current)
    footer_defaults_payload = (
        settings.admin_settings_payload.get("email_footer_defaults")
        if isinstance(settings.admin_settings_payload, dict)
        else {}
    )
    configured_footer_fields = sum(
        1
        for field_name in EMAIL_FOOTER_FIELDS
        if isinstance(footer_defaults_payload, dict)
        and str(footer_defaults_payload.get(field_name) or "").strip()
    )
    _log_admin_action(
        db,
        admin_user,
        action="admin_settings_updated",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={
            "integration_overrides": len(settings.admin_settings_payload.get("integrations", [])),
            "api_key_overrides": len(settings.admin_settings_payload.get("api_keys", [])),
            "email_footer_defaults_configured_fields": configured_footer_fields,
            "ai_cost_currency": "USD",
            "currency_policy_override_ignored": payload.currency_policy is not None,
        },
    )
    db.commit()
    db.refresh(settings)
    return _get_admin_settings(db)


# ── DB Settings Resolver helpers ─────────────────────────────────────────────


def _db_resolver_section(section: str, db: Session) -> dict[str, object]:
    from core.db_settings_resolver import get_section_masked

    return get_section_masked(section, db)


def _db_resolver_update(
    section: str, updates: dict[str, Any], admin_user: models.User, db: Session, action: str
) -> None:
    from core.db_settings_resolver import update_section, invalidate_db_settings_cache

    # Strip None values so callers can send partial patches
    clean = {k: v for k, v in updates.items() if v is not None}
    update_section(section, clean, db)
    invalidate_db_settings_cache()
    _log_admin_action(
        db,
        admin_user,
        action=action,
        target_type="operational_settings",
        target_id=None,
        metadata={"updated_fields": [k for k in clean]},
    )


# ── AI Provider Keys & Model Routing ─────────────────────────────────────────


# Keys still surfaced on the AI-models admin page. The retired Google/Gemini/
# Anthropic LLM reasoning keys are intentionally excluded (the engine runs on
# Bedrock now). OpenRouter + OpenAI were also removed: AI/auto image generation
# is gone (featured images are uploaded manually) and CMS text generation runs
# on Bedrock, so nothing consumes those keys anymore. Only data-provider keys
# remain editable here.
EDITABLE_AI_PROVIDER_KEY_FIELDS: tuple[str, ...] = (
    "firecrawl_api_key",
    "pagespeed_api_key",
    "search_api_key",
    "serpapi_api_key",
    "google_places_api_key",
    "google_maps_api_key",
    "dataforseo_login",
    "dataforseo_password",
)


class AiProviderKeysPatch(BaseModel):
    firecrawl_api_key: str | None = None
    pagespeed_api_key: str | None = None
    search_api_key: str | None = None
    serpapi_api_key: str | None = None
    google_places_api_key: str | None = None
    google_maps_api_key: str | None = None
    dataforseo_login: str | None = None
    dataforseo_password: str | None = None


class SearchConfigPatch(BaseModel):
    serpapi_engine: str | None = None
    google_places_api_mode: str | None = None
    google_places_fallback_to_legacy: bool | None = None


class AiProvidersResponse(BaseModel):
    model_config = {"protected_namespaces": ()}
    ai_provider_keys: dict[str, object]
    search_config: dict[str, object]
    # Effective Bedrock model names sourced from runtime_config or env defaults
    model_routing: dict[str, object]
    # Read-only Bedrock credential status (boolean only — never the token value)
    bedrock_status: dict[str, object]
    # Read-only per-provider Bedrock measurement model map (display-only)
    measurement_model_map: dict[str, object]
    # Read-only effective Bedrock configuration inventory (non-secret):
    # region, resolved text + embedding models, per-engine measurement
    # availability in the configured region, and inference routing type.
    bedrock_inventory: dict[str, object] = {}


def _get_effective_model_routing(db: Session) -> dict[str, object]:
    """Editable Bedrock model routing (runtime_config → env defaults).

    The engine runs reasoning/measurement/embeddings/support-chat/pre-scan/
    case-study entirely on Bedrock, so only the Bedrock tier models are exposed
    as editable here. The retired GOOGLE_*/OPENAI_*/ANTHROPIC_*/CMS_GEMINI_*
    routing keys are no longer surfaced.
    """
    from core.runtime_config import get_config_value

    return {
        "BEDROCK_SMART_MODEL": get_config_value("BEDROCK_SMART_MODEL", db),
        "BEDROCK_FAST_MODEL": get_config_value("BEDROCK_FAST_MODEL", db),
        "BEDROCK_LITE_MODEL": get_config_value("BEDROCK_LITE_MODEL", db),
        "BEDROCK_EMBEDDING_MODEL": get_config_value("BEDROCK_EMBEDDING_MODEL", db),
    }


def _get_bedrock_status() -> dict[str, object]:
    """Read-only Bedrock credential status. Returns a boolean only — the value of
    AWS_BEARER_TOKEN_BEDROCK is NEVER returned."""
    from core.config import settings as app_settings

    return {
        "configured": bool(os.environ.get("AWS_BEARER_TOKEN_BEDROCK")),
        "region": getattr(app_settings, "BEDROCK_REGION", None),
        "enabled": bool(getattr(app_settings, "BEDROCK_ENABLED", False)),
    }


def _get_measurement_model_map() -> dict[str, object]:
    """Read-only per-provider Bedrock measurement model map (display-only)."""
    from core.config import settings as app_settings

    raw = getattr(app_settings, "BEDROCK_MEASUREMENT_MODEL_MAP", {}) or {}
    return {str(k): str(v) for k, v in dict(raw).items()}


def _get_bedrock_inventory() -> dict[str, object]:
    """Effective non-secret Bedrock configuration, per service surface.

    Region, resolved reasoning-tier text models, embedding model and
    dimensionality, per-engine measurement availability in the configured
    region, and inference-profile routing metadata (routing type and
    destination scope — an ``eu.`` profile is cross-region EU and is not a
    statement that processing stays in any single country).
    """
    from core.bedrock_runtime import (
        BEDROCK_EMBEDDING_DIMENSIONS,
        configured_bedrock_region,
        inference_profile_routing,
        measurement_map_inventory,
    )
    from core.config import settings as app_settings

    text_models = {
        "lite": getattr(app_settings, "BEDROCK_LITE_MODEL", None),
        "fast": getattr(app_settings, "BEDROCK_FAST_MODEL", None),
        "smart": getattr(app_settings, "BEDROCK_SMART_MODEL", None),
    }
    return {
        "region": configured_bedrock_region(),
        "enabled": bool(getattr(app_settings, "BEDROCK_ENABLED", False)),
        "text_models": {
            tier: {
                "model": model_id,
                "routing": inference_profile_routing(model_id),
            }
            for tier, model_id in text_models.items()
        },
        "embedding_model": getattr(app_settings, "BEDROCK_EMBEDDING_MODEL", None),
        "embedding_dimensions": BEDROCK_EMBEDDING_DIMENSIONS,
        "measurement_map": measurement_map_inventory(),
    }


def _filter_editable_keys(section: dict[str, object]) -> dict[str, object]:
    """Restrict the ai_provider_keys section to fields still surfaced on the
    AI-models admin page (retired LLM reasoning keys are hidden, not deleted)."""
    return {k: v for k, v in section.items() if k in EDITABLE_AI_PROVIDER_KEY_FIELDS}


def _build_ai_providers_payload(db: Session) -> dict[str, object]:
    return {
        "ai_provider_keys": _filter_editable_keys(_db_resolver_section("ai_provider_keys", db)),
        "search_config": _db_resolver_section("search_config", db),
        "model_routing": _get_effective_model_routing(db),
        "bedrock_status": _get_bedrock_status(),
        "measurement_model_map": _get_measurement_model_map(),
        "bedrock_inventory": _get_bedrock_inventory(),
    }


@router.get("/settings/ai-providers", response_model=AiProvidersResponse)
def get_ai_providers(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    return _build_ai_providers_payload(db)


@router.patch("/settings/ai-providers", response_model=AiProvidersResponse)
def update_ai_providers(
    keys_patch: AiProviderKeysPatch | None = None,
    search_patch: SearchConfigPatch | None = None,
    admin_user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    if keys_patch is not None:
        _db_resolver_update(
            "ai_provider_keys",
            keys_patch.model_dump(exclude_none=True),
            admin_user,
            db,
            "ai_provider_keys_updated",
        )
    if search_patch is not None:
        _db_resolver_update(
            "search_config",
            search_patch.model_dump(exclude_none=True),
            admin_user,
            db,
            "search_config_updated",
        )
    return _build_ai_providers_payload(db)


class AiProvidersPatchRequest(BaseModel):
    keys: AiProviderKeysPatch | None = None
    search: SearchConfigPatch | None = None


@router.patch("/settings/ai-providers/bulk", response_model=AiProvidersResponse)
def bulk_update_ai_providers(
    payload: AiProvidersPatchRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    if payload.keys is not None:
        _db_resolver_update(
            "ai_provider_keys",
            payload.keys.model_dump(exclude_none=True),
            admin_user,
            db,
            "ai_provider_keys_updated",
        )
    if payload.search is not None:
        _db_resolver_update(
            "search_config",
            payload.search.model_dump(exclude_none=True),
            admin_user,
            db,
            "search_config_updated",
        )
    return _build_ai_providers_payload(db)


# ── OAuth Client Credentials ──────────────────────────────────────────────────


class OAuthConfigPatch(BaseModel):
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None
    linkedin_client_id: str | None = None
    linkedin_client_secret: str | None = None
    jira_client_id: str | None = None
    jira_client_secret: str | None = None
    bing_client_id: str | None = None
    bing_client_secret: str | None = None


@router.get("/settings/oauth")
def get_oauth_config(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _db_resolver_section("oauth_config", db)


@router.patch("/settings/oauth")
def update_oauth_config(
    payload: OAuthConfigPatch,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _db_resolver_update(
        "oauth_config",
        payload.model_dump(exclude_none=True),
        admin_user,
        db,
        "oauth_config_updated",
    )
    return _db_resolver_section("oauth_config", db)


# ── Cloudflare Configuration ──────────────────────────────────────────────────


class CloudflareConfigPatch(BaseModel):
    api_token: str | None = None
    zone_id: str | None = None
    custom_origin_server: str | None = None
    auto_activate_on_verify: bool | None = None


@router.get("/settings/cloudflare")
def get_cloudflare_config(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _db_resolver_section("cloudflare_config", db)


@router.patch("/settings/cloudflare")
def update_cloudflare_config(
    payload: CloudflareConfigPatch,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _db_resolver_update(
        "cloudflare_config",
        payload.model_dump(exclude_none=True),
        admin_user,
        db,
        "cloudflare_config_updated",
    )
    return _db_resolver_section("cloudflare_config", db)


# ── Email Configuration ────────────────────────────────────────────────────────


class EmailConfigPatch(BaseModel):
    enabled: bool | None = None
    provider: str | None = None  # smtp
    from_address: str | None = None
    from_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: str | None = None
    outbox_max_attempts: int | None = Field(default=None, ge=1, le=20)
    outbox_batch_size: int | None = Field(default=None, ge=1, le=500)


@router.get("/settings/email-config")
def get_email_config(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _db_resolver_section("email_config", db)


@router.patch("/settings/email-config")
def update_email_config(
    payload: EmailConfigPatch,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    updates = payload.model_dump(exclude_none=True)
    if "provider" in updates:
        prov = str(updates["provider"]).strip().lower()
        if prov not in {"smtp"}:
            raise HTTPException(status_code=422, detail="provider must be 'smtp'")
        updates["provider"] = prov
    _db_resolver_update("email_config", updates, admin_user, db, "email_config_updated")
    return _db_resolver_section("email_config", db)


# ── Support / Branding Contact Info ───────────────────────────────────────────


class SupportInfoPatch(BaseModel):
    support_email: str | None = None
    billing_email: str | None = None
    privacy_email: str | None = None
    contact_inbox_address: str | None = None
    contact_ticket_prefix: str | None = None


@router.get("/settings/support-info")
def get_support_info(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return _db_resolver_section("support_info", db)


@router.patch("/settings/support-info")
def update_support_info(
    payload: SupportInfoPatch,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
) -> dict[str, object]:
    _db_resolver_update(
        "support_info",
        payload.model_dump(exclude_none=True),
        admin_user,
        db,
        "support_info_updated",
    )
    return _db_resolver_section("support_info", db)


# ── Aggregated dynamic settings overview ──────────────────────────────────────


class DynamicSettingsOverview(BaseModel):
    model_config = {"protected_namespaces": ()}
    ai_provider_keys: dict[str, object]
    search_config: dict[str, object]
    email_config: dict[str, object]
    oauth_config: dict[str, object]
    cloudflare_config: dict[str, object]
    support_info: dict[str, object]
    model_routing: dict[str, object]


@router.get("/settings/dynamic", response_model=DynamicSettingsOverview)
def get_dynamic_settings_overview(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return all DB-managed dynamic settings in one call (all sensitive values masked)."""
    return {
        "ai_provider_keys": _db_resolver_section("ai_provider_keys", db),
        "search_config": _db_resolver_section("search_config", db),
        "email_config": _db_resolver_section("email_config", db),
        "oauth_config": _db_resolver_section("oauth_config", db),
        "cloudflare_config": _db_resolver_section("cloudflare_config", db),
        "support_info": _db_resolver_section("support_info", db),
        "model_routing": _get_effective_model_routing(db),
    }


# ── Operations ────────────────────────────────────────────────────────────────


@router.get("/operations", response_model=OperationStatus)
def get_operations_status(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    settings = _get_operational_settings(db)
    return _serialize_operation_status(settings)


@router.post("/operations/cache-refresh", response_model=OperationStatus)
def request_cache_refresh(
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    settings = _get_operational_settings(db)
    settings.cache_refresh_requested_at = datetime.now(timezone.utc)
    _log_admin_action(
        db,
        admin_user,
        action="cache_refresh_requested",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={"cache_refresh_requested_at": settings.cache_refresh_requested_at.isoformat()},
    )
    db.commit()
    db.refresh(settings)
    return _serialize_operation_status(settings)


@router.post("/operations/fallback-model", response_model=OperationStatus)
def toggle_fallback_model(
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    request: FallbackToggleRequest,
    db: Session = Depends(get_db),
):
    settings = _get_operational_settings(db)
    previous_value = settings.fallback_model_enabled
    settings.fallback_model_enabled = request.enabled
    _log_admin_action(
        db,
        admin_user,
        action="fallback_model_toggled",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={"before": previous_value, "after": request.enabled},
    )
    db.commit()
    db.refresh(settings)
    return _serialize_operation_status(settings)


@router.post("/operations/pricing-v2", response_model=OperationStatus)
def update_pricing_v2_flags(
    request: PricingV2FlagsUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    if (
        request.pricing_v2_enabled is None
        and request.credit_engine_v2_enabled is None
        and request.pricing_v2_shadow_mode is None
        and request.pricing_v3_shadow_mode is None
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "At least one pricing flag must be provided: "
                "pricing_v2_enabled, credit_engine_v2_enabled, pricing_v2_shadow_mode, "
                "pricing_v3_shadow_mode."
            ),
        )

    settings = _get_operational_settings(db)
    before = {
        "pricing_v2_enabled": bool(getattr(settings, "pricing_v2_enabled", True)),
        "credit_engine_v2_enabled": bool(getattr(settings, "credit_engine_v2_enabled", True)),
        "pricing_v2_shadow_mode": bool(getattr(settings, "pricing_v2_shadow_mode", False)),
        "pricing_v3_shadow_mode": bool(getattr(settings, "pricing_v3_shadow_mode", False)),
    }
    if request.pricing_v2_enabled is not None:
        settings.pricing_v2_enabled = bool(request.pricing_v2_enabled)
    if request.credit_engine_v2_enabled is not None:
        settings.credit_engine_v2_enabled = bool(request.credit_engine_v2_enabled)
    if request.pricing_v2_shadow_mode is not None:
        settings.pricing_v2_shadow_mode = bool(request.pricing_v2_shadow_mode)
    if request.pricing_v3_shadow_mode is not None:
        settings.pricing_v3_shadow_mode = bool(request.pricing_v3_shadow_mode)

    _log_admin_action(
        db,
        admin_user,
        action="pricing_v2_flags_updated",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={"before": before, "after": _serialize_operation_status(settings)},
    )
    db.commit()
    db.refresh(settings)
    return _serialize_operation_status(settings)


@router.post("/operations/report-retention", response_model=OperationStatus)
def update_report_retention_days(
    request: ReportRetentionUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    if request.days not in ALLOWED_REPORT_RETENTION_DAYS:
        allowed = ", ".join(str(value) for value in ALLOWED_REPORT_RETENTION_DAYS)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid retention value. Allowed values: {allowed}.",
        )

    settings = _get_operational_settings(db)
    previous = normalize_report_retention_days(getattr(settings, "report_retention_days", None))
    settings.report_retention_days = request.days
    _log_admin_action(
        db,
        admin_user,
        action="report_retention_updated",
        target_type="operational_settings",
        target_id=settings.id,
        metadata={"before": previous, "after": request.days},
    )
    db.commit()
    db.refresh(settings)
    return _serialize_operation_status(settings)


@router.get("/signal-warehouse/health", response_model=SignalWarehouseHealthResponse)
def get_signal_warehouse_health(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    total_signal_audit_snapshots = (
        db.query(models.SignalAuditSnapshot).count()
        if hasattr(models, "SignalAuditSnapshot")
        else 0
    )
    total_signal_citation_events = (
        db.query(models.SignalCitationEvent).count()
        if hasattr(models, "SignalCitationEvent")
        else 0
    )
    total_signal_entity_observations = (
        db.query(models.SignalEntityObservation).count()
        if hasattr(models, "SignalEntityObservation")
        else 0
    )
    total_signal_remediation_outcomes = (
        db.query(models.SignalRemediationOutcome).count()
        if hasattr(models, "SignalRemediationOutcome")
        else 0
    )
    total_benchmark_cohort_aggregates = (
        db.query(models.BenchmarkCohortAggregate).count()
        if hasattr(models, "BenchmarkCohortAggregate")
        else 0
    )
    total_proprietary_scores = (
        db.query(models.ProprietaryScore).count() if hasattr(models, "ProprietaryScore") else 0
    )

    historical_project_audits = (
        db.query(models.Audit.id).filter(models.Audit.project_id.isnot(None)).count()
    )
    audits_with_signal_snapshots = int(
        (
            db.query(func.count(func.distinct(models.SignalAuditSnapshot.audit_id))).scalar()
            if hasattr(models, "SignalAuditSnapshot")
            else 0
        )
        or 0
    )
    backfill_coverage_pct = (
        round(
            (audits_with_signal_snapshots / historical_project_audits) * 100.0,
            2,
        )
        if historical_project_audits > 0
        else 0.0
    )

    latest_candidates = [
        db.query(func.max(models.SignalAuditSnapshot.ingested_at)).scalar()
        if hasattr(models, "SignalAuditSnapshot")
        else None,
        db.query(func.max(models.BenchmarkCohortAggregate.computed_at)).scalar()
        if hasattr(models, "BenchmarkCohortAggregate")
        else None,
        db.query(func.max(models.ProprietaryScore.computed_at)).scalar()
        if hasattr(models, "ProprietaryScore")
        else None,
    ]
    latest_candidates = [item for item in latest_candidates if isinstance(item, datetime)]
    last_ingested_at = max(latest_candidates).isoformat() if latest_candidates else None

    return SignalWarehouseHealthResponse(
        total_signal_audit_snapshots=total_signal_audit_snapshots,
        total_signal_citation_events=total_signal_citation_events,
        total_signal_entity_observations=total_signal_entity_observations,
        total_signal_remediation_outcomes=total_signal_remediation_outcomes,
        total_benchmark_cohort_aggregates=total_benchmark_cohort_aggregates,
        total_proprietary_scores=total_proprietary_scores,
        historical_project_audits=historical_project_audits,
        audits_with_signal_snapshots=audits_with_signal_snapshots,
        backfill_coverage_pct=backfill_coverage_pct,
        last_ingested_at=last_ingested_at,
    )


@router.post(
    "/signal-warehouse/backfill", response_model=SignalWarehouseBackfillResponse, status_code=202
)
def trigger_signal_warehouse_backfill(
    payload: SignalWarehouseBackfillRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    job_id = str(uuid4())
    ingestion_service = SignalIngestionService()
    benchmark_engine = BenchmarkEngine()
    now = datetime.now(timezone.utc)

    summary = ingestion_service.backfill_all(db=db, dry_run=payload.dry_run)
    cohort_rows_written = 0
    status_value = "dry_run_completed" if payload.dry_run else "completed"
    if not payload.dry_run:
        cohort_rows_written = benchmark_engine.compute_cohort_aggregates(
            db=db,
            period_date=now.date(),
        )

    _log_admin_action(
        db,
        admin_user,
        action="signal_warehouse_backfill_triggered",
        target_type="signal_warehouse",
        target_id=job_id,
        metadata={
            "dry_run": payload.dry_run,
            "audits_processed": summary.get("audits_processed", 0),
            "batches_processed": summary.get("batches_processed", 0),
            "rows_inserted": summary.get("rows_inserted", 0),
            "cohort_rows_written": cohort_rows_written,
            "errors": len(summary.get("errors", [])),
        },
    )
    db.commit()

    return SignalWarehouseBackfillResponse(
        job_id=job_id,
        status=status_value,
        dry_run=payload.dry_run,
        audits_processed=int(summary.get("audits_processed", 0)),
        batches_processed=int(summary.get("batches_processed", 0)),
        rows_inserted=int(summary.get("rows_inserted", 0)),
        cohort_rows_written=int(cohort_rows_written),
        errors=[str(item) for item in summary.get("errors", [])],
    )


@router.post("/data-retention/cleanup", response_model=DataRetentionCleanupResponse)
def cleanup_data_retention(
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    retention_days = _get_retention_setting("AUDIT_RETENTION_DAYS")
    strip_days = _get_retention_setting("AUDIT_STRIP_SCREENSHOTS_AFTER_DAYS")
    now = datetime.now(timezone.utc)
    delete_before = now - timedelta(days=retention_days) if retention_days is not None else None

    audits_deleted = 0
    screenshots_redacted = 0

    if strip_days is not None:
        strip_before = now - timedelta(days=strip_days)
        strip_query = (
            db.query(models.Audit)
            .filter(models.Audit.created_at < strip_before)
            .filter(models.Audit.sanitized_at.is_(None))
        )
        if delete_before is not None:
            strip_query = strip_query.filter(models.Audit.created_at >= delete_before)
        audits_to_strip = strip_query.all()
        for audit in audits_to_strip:
            report = audit.full_report if isinstance(audit.full_report, dict) else {}
            if report.get("screenshot_base64") is not None:
                audit.full_report = {**report, "screenshot_base64": None}
                screenshots_redacted += 1
            audit.sanitized_at = now

    if retention_days is not None:
        audits_deleted = (
            db.query(models.Audit)
            .filter(models.Audit.created_at < delete_before)
            .delete(synchronize_session=False)
        )

    if strip_days is not None or retention_days is not None:
        _log_admin_action(
            db,
            admin_user,
            action="data_retention_cleanup",
            target_type="audit",
            target_id=None,
            metadata={
                "audits_deleted": int(audits_deleted),
                "screenshots_redacted": int(screenshots_redacted),
                "retention_days": retention_days,
                "strip_screenshots_after_days": strip_days,
                "executed_at": now.isoformat(),
            },
        )
        db.commit()

    return {
        "audits_deleted": int(audits_deleted),
        "screenshots_redacted": int(screenshots_redacted),
        "retention_days": retention_days,
        "strip_screenshots_after_days": strip_days,
        "executed_at": now.isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin Action Log / Audit Trail
# ---------------------------------------------------------------------------


class ActionLogEntry(BaseModel):
    id: int
    admin_user_id: int | None
    admin_email: str | None
    action: str
    target_type: str | None
    target_id: str | None
    metadata: dict | None
    created_at: str


class ActionLogPage(BaseModel):
    items: list[ActionLogEntry]
    total: int
    page: int
    page_size: int


class ActionLogSummaryEntry(BaseModel):
    label: str
    count: int


class ActionLogSummary(BaseModel):
    total_actions: int
    actions_last_24h: int
    actions_last_7d: int
    top_actions: list[ActionLogSummaryEntry]
    top_actors: list[ActionLogSummaryEntry]
    top_target_types: list[ActionLogSummaryEntry]


@router.get("/action-logs", response_model=ActionLogPage)
def list_action_logs(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    action: str | None = None,
    target_type: str | None = None,
    admin_user_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 200:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range",
                "page_size must be between 1 and 200.",
            ),
        )

    query = db.query(models.AdminActionLog, models.User.email).outerjoin(
        models.User, models.AdminActionLog.admin_user_id == models.User.id
    )

    if action and action.strip():
        query = query.filter(models.AdminActionLog.action.ilike(f"%{action.strip()}%"))
    if target_type and target_type.strip():
        query = query.filter(models.AdminActionLog.target_type == target_type.strip())
    if admin_user_id is not None:
        query = query.filter(models.AdminActionLog.admin_user_id == admin_user_id)
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(models.AdminActionLog.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(models.AdminActionLog.created_at <= dt_to)
        except ValueError:
            pass
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                models.AdminActionLog.action.ilike(term),
                models.AdminActionLog.target_id.ilike(term),
                models.AdminActionLog.target_type.ilike(term),
            )
        )

    total = query.count()
    rows = (
        query.order_by(models.AdminActionLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        ActionLogEntry(
            id=log.id,
            admin_user_id=log.admin_user_id,
            admin_email=email,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            metadata=log.metadata_json if isinstance(log.metadata_json, dict) else None,
            created_at=log.created_at.isoformat() if log.created_at else "",
        )
        for log, email in rows
    ]

    return ActionLogPage(items=items, total=total, page=page, page_size=page_size)


@router.get("/action-logs/summary", response_model=ActionLogSummary)
def get_action_logs_summary(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    total_actions = db.query(func.count(models.AdminActionLog.id)).scalar() or 0

    now = datetime.now(timezone.utc)
    actions_24h = (
        db.query(func.count(models.AdminActionLog.id))
        .filter(models.AdminActionLog.created_at >= now - timedelta(hours=24))
        .scalar()
        or 0
    )
    actions_7d = (
        db.query(func.count(models.AdminActionLog.id))
        .filter(models.AdminActionLog.created_at >= now - timedelta(days=7))
        .scalar()
        or 0
    )

    top_actions_rows = (
        db.query(models.AdminActionLog.action, func.count(models.AdminActionLog.id).label("cnt"))
        .group_by(models.AdminActionLog.action)
        .order_by(text("cnt DESC"))
        .limit(10)
        .all()
    )
    top_actions = [ActionLogSummaryEntry(label=a, count=c) for a, c in top_actions_rows]

    top_actors_rows = (
        db.query(models.User.email, func.count(models.AdminActionLog.id).label("cnt"))
        .join(models.User, models.AdminActionLog.admin_user_id == models.User.id)
        .group_by(models.User.email)
        .order_by(text("cnt DESC"))
        .limit(10)
        .all()
    )
    top_actors = [ActionLogSummaryEntry(label=e, count=c) for e, c in top_actors_rows]

    top_target_types_rows = (
        db.query(
            models.AdminActionLog.target_type,
            func.count(models.AdminActionLog.id).label("cnt"),
        )
        .filter(models.AdminActionLog.target_type.isnot(None))
        .group_by(models.AdminActionLog.target_type)
        .order_by(text("cnt DESC"))
        .limit(10)
        .all()
    )
    top_target_types = [ActionLogSummaryEntry(label=t, count=c) for t, c in top_target_types_rows]

    return ActionLogSummary(
        total_actions=total_actions,
        actions_last_24h=actions_24h,
        actions_last_7d=actions_7d,
        top_actions=top_actions,
        top_actors=top_actors,
        top_target_types=top_target_types,
    )


# ---------------------------------------------------------------------------
# Email Outbox Dashboard
# ---------------------------------------------------------------------------


class EmailOutboxEntry(BaseModel):
    id: int
    user_id: int | None
    to_email: str
    subject: str
    category: str | None
    template_key: str | None
    correlation_id: str | None
    status: str
    provider: str | None
    attempts: int
    last_error: str | None
    created_at: str
    sent_at: str | None


class EmailOutboxPage(BaseModel):
    items: list[EmailOutboxEntry]
    total: int
    page: int
    page_size: int


class EmailOutboxDetail(BaseModel):
    id: int
    user_id: int | None
    user_email: str | None
    to_email: str
    subject: str
    html_body: str | None
    text_body: str | None
    category: str | None
    template_key: str | None
    correlation_id: str | None
    status: str
    provider: str | None
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str | None
    sent_at: str | None


class EmailOutboxStatsEntry(BaseModel):
    label: str
    count: int


class EmailOutboxTemplateStats(BaseModel):
    template_key: str
    sent: int
    failed: int
    pending: int


class EmailOutboxStats(BaseModel):
    total: int
    pending: int
    sent: int
    failed: int
    retry: int
    delivery_rate: float
    avg_attempts: float
    top_errors: list[EmailOutboxStatsEntry]
    by_template: list[EmailOutboxTemplateStats]


def _serialize_outbox_entry(entry: models.EmailOutbox) -> dict:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "to_email": entry.to_email,
        "subject": entry.subject,
        "category": entry.category,
        "template_key": getattr(entry, "template_key", None),
        "correlation_id": entry.correlation_id,
        "status": entry.status,
        "provider": entry.provider,
        "attempts": entry.attempts,
        "last_error": entry.last_error,
        "created_at": entry.created_at.isoformat() if entry.created_at else "",
        "sent_at": entry.sent_at.isoformat() if entry.sent_at else None,
    }


@router.get("/email-outbox", response_model=EmailOutboxPage)
def list_email_outbox(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 50,
    status: str | None = None,
    template_key: str | None = None,
    category: str | None = None,
    to_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_error: bool | None = None,
    search: str | None = None,
):
    if page <= 0:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_must_be_positive", "page must be greater than 0."
            ),
        )
    if page_size <= 0 or page_size > 200:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.page_size_out_of_range",
                "page_size must be between 1 and 200.",
            ),
        )

    query = db.query(models.EmailOutbox)

    if status and status.strip():
        query = query.filter(models.EmailOutbox.status == status.strip())
    if template_key and template_key.strip():
        query = query.filter(models.EmailOutbox.template_key == template_key.strip())
    if category and category.strip():
        query = query.filter(models.EmailOutbox.category == category.strip())
    if to_email and to_email.strip():
        query = query.filter(models.EmailOutbox.to_email.ilike(f"%{to_email.strip()}%"))
    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            query = query.filter(models.EmailOutbox.created_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            query = query.filter(models.EmailOutbox.created_at <= dt_to)
        except ValueError:
            pass
    if has_error is True:
        query = query.filter(
            models.EmailOutbox.last_error.isnot(None),
            models.EmailOutbox.last_error != "",
        )
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                models.EmailOutbox.to_email.ilike(term),
                models.EmailOutbox.subject.ilike(term),
                models.EmailOutbox.correlation_id.ilike(term),
            )
        )

    total = query.count()
    rows = (
        query.order_by(models.EmailOutbox.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return EmailOutboxPage(
        items=[_serialize_outbox_entry(e) for e in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/email-outbox/stats", response_model=EmailOutboxStats)
def get_email_outbox_stats(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    total = db.query(func.count(models.EmailOutbox.id)).scalar() or 0
    pending = (
        db.query(func.count(models.EmailOutbox.id))
        .filter(models.EmailOutbox.status == "pending")
        .scalar()
        or 0
    )
    sent = (
        db.query(func.count(models.EmailOutbox.id))
        .filter(models.EmailOutbox.status == "sent")
        .scalar()
        or 0
    )
    failed = (
        db.query(func.count(models.EmailOutbox.id))
        .filter(models.EmailOutbox.status == "failed")
        .scalar()
        or 0
    )
    retry = (
        db.query(func.count(models.EmailOutbox.id))
        .filter(models.EmailOutbox.status == "retry")
        .scalar()
        or 0
    )

    denominator = sent + failed
    delivery_rate = round((sent / denominator * 100) if denominator > 0 else 0.0, 2)

    avg_attempts_val = db.query(func.avg(models.EmailOutbox.attempts)).scalar()
    avg_attempts = round(float(avg_attempts_val), 2) if avg_attempts_val else 0.0

    top_errors_rows = (
        db.query(models.EmailOutbox.last_error, func.count(models.EmailOutbox.id).label("cnt"))
        .filter(
            models.EmailOutbox.last_error.isnot(None),
            models.EmailOutbox.last_error != "",
        )
        .group_by(models.EmailOutbox.last_error)
        .order_by(text("cnt DESC"))
        .limit(10)
        .all()
    )
    top_errors = [
        EmailOutboxStatsEntry(label=err[:200] if err else "Unknown", count=c)
        for err, c in top_errors_rows
    ]

    by_template_rows = (
        db.query(
            models.EmailOutbox.template_key,
            models.EmailOutbox.status,
            func.count(models.EmailOutbox.id).label("cnt"),
        )
        .filter(models.EmailOutbox.template_key.isnot(None))
        .group_by(models.EmailOutbox.template_key, models.EmailOutbox.status)
        .all()
    )
    template_map: dict[str, dict[str, int]] = {}
    for tpl, st, cnt in by_template_rows:
        if tpl not in template_map:
            template_map[tpl] = {"sent": 0, "failed": 0, "pending": 0}
        if st == "sent":
            template_map[tpl]["sent"] += cnt
        elif st == "failed":
            template_map[tpl]["failed"] += cnt
        else:
            template_map[tpl]["pending"] += cnt

    by_template = [
        EmailOutboxTemplateStats(
            template_key=tpl,
            sent=counts["sent"],
            failed=counts["failed"],
            pending=counts["pending"],
        )
        for tpl, counts in sorted(template_map.items())
    ]

    return EmailOutboxStats(
        total=total,
        pending=pending,
        sent=sent,
        failed=failed,
        retry=retry,
        delivery_rate=delivery_rate,
        avg_attempts=avg_attempts,
        top_errors=top_errors,
        by_template=by_template,
    )


@router.get("/email-outbox/{email_id}", response_model=EmailOutboxDetail)
def get_email_outbox_detail(
    email_id: int,
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    entry = db.query(models.EmailOutbox).filter(models.EmailOutbox.id == email_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Email not found.")

    user_email = None
    if entry.user_id:
        user = db.query(models.User.email).filter(models.User.id == entry.user_id).first()
        if user:
            user_email = user.email

    return EmailOutboxDetail(
        id=entry.id,
        user_id=entry.user_id,
        user_email=user_email,
        to_email=entry.to_email,
        subject=entry.subject,
        html_body=entry.html_body,
        text_body=entry.text_body,
        category=entry.category,
        template_key=getattr(entry, "template_key", None),
        correlation_id=entry.correlation_id,
        status=entry.status,
        provider=entry.provider,
        attempts=entry.attempts,
        last_error=entry.last_error,
        created_at=entry.created_at.isoformat() if entry.created_at else "",
        updated_at=entry.updated_at.isoformat() if entry.updated_at else None,
        sent_at=entry.sent_at.isoformat() if entry.sent_at else None,
    )


@router.post("/email-outbox/{email_id}/resend")
def resend_email(
    email_id: int,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    entry = db.query(models.EmailOutbox).filter(models.EmailOutbox.id == email_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Email not found.")

    if entry.status == "sent":
        raise HTTPException(status_code=400, detail="Email already sent successfully.")

    entry.status = "pending"
    entry.last_error = None
    entry.attempts = 0

    _log_admin_action(
        db,
        admin_user,
        action="email_resend",
        target_type="email_outbox",
        target_id=entry.id,
        metadata={
            "to_email": entry.to_email,
            "subject": entry.subject,
            "previous_status": entry.status,
            "previous_attempts": entry.attempts,
        },
    )
    db.commit()

    return {"success": True, "message": f"Email #{email_id} queued for resend."}


# ---------------------------------------------------------------------------
# Plan & Feature-Flag Management (TASK_ADMIN-06)
# ---------------------------------------------------------------------------


class PlanInfo(BaseModel):
    display_name: str
    monthly_price_usd: int
    capabilities: dict[str, object]


class PlansResponse(BaseModel):
    plans: dict[str, PlanInfo]
    capability_keys: list[str]
    capability_descriptions: dict[str, str]
    # SIGV2-1147: the subset of capability_keys for which a workspace override
    # is actually enforced at runtime, plus the refusal reason for every other
    # key. The admin UI offers only the former and explains the latter.
    overridable_capability_keys: list[str] = Field(default_factory=list)
    override_refusal_reasons: dict[str, str] = Field(default_factory=dict)


class OverrideOut(BaseModel):
    id: int
    workspace_id: int
    workspace_name: str | None = None
    capability_key: str
    override_value: object
    reason: str | None = None
    created_by_email: str | None = None
    expires_at: str | None = None
    created_at: str
    is_enforced: bool = False
    enforcement_reason: str = ""


class OverrideCreate(BaseModel):
    workspace_id: int
    capability_key: str
    override_value: object
    reason: str | None = None
    expires_at: str | None = None


class EffectiveCapability(BaseModel):
    key: str
    base_value: object
    effective_value: object
    is_overridden: bool
    override_id: int | None = None
    # SIGV2-1147: an override row may exist and still not be enforced, so
    # is_overridden alone never implies effective_value moved.
    is_enforced: bool = False
    enforcement_reason: str = ""


class FeatureFlagOut(BaseModel):
    id: int
    key: str
    description: str | None = None
    is_enabled: bool
    rollout_percentage: int | None = None
    created_at: str
    updated_at: str


class FeatureFlagCreate(BaseModel):
    key: str
    description: str | None = None
    is_enabled: bool = False
    rollout_percentage: int | None = None


class FeatureFlagUpdate(BaseModel):
    description: str | None = None
    is_enabled: bool | None = None
    rollout_percentage: int | None = None


def _override_to_dict(ov: models.WorkspaceCapabilityOverride) -> dict:
    ws = ov.workspace
    creator = ov.created_by_user
    # SIGV2-1147: rows written before the override policy existed may target a
    # capability no gate consults. Report that on the row rather than letting
    # the list imply every row is in force.
    enforcement = describe_override_enforcement(ov.capability_key)
    return {
        "id": ov.id,
        "workspace_id": ov.workspace_id,
        "workspace_name": ws.name if ws else None,
        "capability_key": ov.capability_key,
        "override_value": ov.override_value,
        "reason": ov.reason,
        "created_by_email": creator.email if creator else None,
        "expires_at": ov.expires_at.isoformat() if ov.expires_at else None,
        "created_at": ov.created_at.isoformat() if ov.created_at else "",
        "is_enforced": enforcement.is_enforced,
        "enforcement_reason": enforcement.reason,
    }


def _flag_to_dict(flag: models.FeatureFlag) -> dict:
    return {
        "id": flag.id,
        "key": flag.key,
        "description": flag.description,
        "is_enabled": flag.is_enabled,
        "rollout_percentage": flag.rollout_percentage,
        "created_at": flag.created_at.isoformat() if flag.created_at else "",
        "updated_at": flag.updated_at.isoformat() if flag.updated_at else "",
    }


# ---- 1. Plan comparison ----


@router.get("/plans", response_model=PlansResponse)
def admin_get_plans(
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Return all plans with capabilities for side-by-side comparison."""
    plans_out: dict[str, PlanInfo] = {}
    all_keys: list[str] = []

    for plan_key in PUBLIC_PLAN_TYPES:
        caps = CAPABILITY_MATRIX[plan_key]
        presentation = PLAN_PRESENTATION.get(plan_key, {})
        price = int(caps.get("monthly_price_usd", 0))
        plans_out[plan_key] = PlanInfo(
            display_name=presentation.get("name", plan_key.replace("_", " ").title()),
            monthly_price_usd=price,
            capabilities=dict(caps),
        )
        if not all_keys:
            all_keys = list(caps.keys())

    policy = capability_override_policy()
    return PlansResponse(
        plans=plans_out,
        capability_keys=all_keys,
        capability_descriptions=CAPABILITY_DESCRIPTIONS,
        overridable_capability_keys=sorted(
            key for key, verdict in policy.items() if verdict.is_enforced
        ),
        override_refusal_reasons={
            key: verdict.reason for key, verdict in policy.items() if not verdict.is_enforced
        },
    )


# ---- 2. Workspace capability overrides ----


@router.get("/plans/overrides")
def admin_list_overrides(
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """List all active capability overrides across workspaces."""
    now = datetime.now(timezone.utc)
    overrides = (
        db.query(models.WorkspaceCapabilityOverride)
        .filter(
            or_(
                models.WorkspaceCapabilityOverride.expires_at.is_(None),
                models.WorkspaceCapabilityOverride.expires_at > now,
            )
        )
        .order_by(models.WorkspaceCapabilityOverride.created_at.desc())
        .all()
    )
    return {"overrides": [_override_to_dict(o) for o in overrides]}


@router.post("/plans/overrides", status_code=201)
def admin_create_override(
    body: OverrideCreate,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Create a per-workspace capability override (additive only)."""
    # Validate workspace exists
    workspace = db.query(models.Workspace).filter(models.Workspace.id == body.workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Validate capability key exists
    sample_plan = next(iter(CAPABILITY_MATRIX.values()), {})
    if body.capability_key not in sample_plan:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown capability key: {body.capability_key}",
        )

    # SIGV2-1147: refuse a row no gate would ever read. Accepting one told the
    # administrator a customer had been granted something the product then
    # kept refusing, with nothing anywhere to say the row was inert.
    enforcement = describe_override_enforcement(body.capability_key)
    if not enforcement.is_enforced:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{body.capability_key}' cannot be granted per workspace and the "
                f"override would have no effect. {enforcement.reason}"
            ),
        )

    # Every overridable capability is boolean, and an override exists only to
    # grant. Anything other than True would be stored and never honoured.
    if body.override_value is not True:
        raise HTTPException(
            status_code=400,
            detail=(
                f"'{body.capability_key}' is a boolean capability and an override can "
                "only grant it. Pass true, or delete the override to revoke."
            ),
        )

    # The additive-only numeric guardrail that used to sit here is gone with
    # the numeric keys it guarded: it compared the submitted value against
    # whichever plan happened to be first in CAPABILITY_MATRIX rather than the
    # workspace owner's plan, so it would have waved through a restriction on
    # any higher plan. Every remaining overridable capability is boolean and
    # the check above admits True only, which is additive by construction.

    # Upsert: replace existing override for same workspace+key
    existing = (
        db.query(models.WorkspaceCapabilityOverride)
        .filter(
            models.WorkspaceCapabilityOverride.workspace_id == body.workspace_id,
            models.WorkspaceCapabilityOverride.capability_key == body.capability_key,
        )
        .first()
    )
    if existing:
        existing.override_value = body.override_value
        existing.reason = body.reason
        existing.expires_at = datetime.fromisoformat(body.expires_at) if body.expires_at else None
        existing.created_by_user_id = admin_user.id
        db.flush()
        ov = existing
    else:
        ov = models.WorkspaceCapabilityOverride(
            workspace_id=body.workspace_id,
            capability_key=body.capability_key,
            override_value=body.override_value,
            reason=body.reason,
            created_by_user_id=admin_user.id,
            expires_at=(datetime.fromisoformat(body.expires_at) if body.expires_at else None),
        )
        db.add(ov)
        db.flush()

    _log_admin_action(
        db,
        admin_user,
        action="capability_override_upsert",
        target_type="workspace_capability_override",
        target_id=ov.id,
        metadata={
            "workspace_id": body.workspace_id,
            "capability_key": body.capability_key,
            "override_value": body.override_value,
            "reason": body.reason,
        },
    )
    db.commit()
    db.refresh(ov)
    return _override_to_dict(ov)


@router.delete("/plans/overrides/{override_id}")
def admin_delete_override(
    override_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Remove a capability override."""
    ov = (
        db.query(models.WorkspaceCapabilityOverride)
        .filter(models.WorkspaceCapabilityOverride.id == override_id)
        .first()
    )
    if not ov:
        raise HTTPException(status_code=404, detail="Override not found.")

    _log_admin_action(
        db,
        admin_user,
        action="capability_override_delete",
        target_type="workspace_capability_override",
        target_id=ov.id,
        metadata={
            "workspace_id": ov.workspace_id,
            "capability_key": ov.capability_key,
        },
    )
    db.delete(ov)
    db.commit()
    return {"success": True}


@router.get("/plans/workspace/{workspace_id}")
def admin_effective_capabilities(
    workspace_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return effective (base + overrides) capabilities for a workspace."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Determine the workspace owner's plan
    owner = workspace.owner
    sub = getattr(owner, "subscription", None)
    plan_type = getattr(sub, "plan_type", None) or "plan_standard"
    base_caps = dict(CAPABILITY_MATRIX.get(plan_type, {}))

    # Load active overrides for this workspace
    now = datetime.now(timezone.utc)
    overrides = (
        db.query(models.WorkspaceCapabilityOverride)
        .filter(
            models.WorkspaceCapabilityOverride.workspace_id == workspace_id,
            or_(
                models.WorkspaceCapabilityOverride.expires_at.is_(None),
                models.WorkspaceCapabilityOverride.expires_at > now,
            ),
        )
        .all()
    )
    override_map = {o.capability_key: o for o in overrides}

    # SIGV2-1147: effective_value must mean "what the gates will decide", so an
    # override moves it only when the policy enforces that capability. A stored
    # but unenforced row is still reported, with the reason it does nothing.
    effective: list[dict] = []
    for key, base_val in base_caps.items():
        ov = override_map.get(key)
        enforcement = describe_override_enforcement(key)
        applies = ov is not None and enforcement.is_enforced
        effective.append(
            {
                "key": key,
                "base_value": base_val,
                "effective_value": ov.override_value if applies else base_val,
                "is_overridden": ov is not None,
                "override_id": ov.id if ov else None,
                "is_enforced": enforcement.is_enforced,
                "enforcement_reason": enforcement.reason,
            }
        )

    return {
        "workspace_id": workspace_id,
        "workspace_name": workspace.name,
        "plan_type": plan_type,
        "capabilities": effective,
    }


# ---- 3. Feature flags ----


@router.get("/feature-flags")
def admin_list_feature_flags(
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """List all feature flags."""
    flags = db.query(models.FeatureFlag).order_by(models.FeatureFlag.key).all()
    return {"flags": [_flag_to_dict(f) for f in flags]}


@router.post("/feature-flags", status_code=201)
def admin_create_feature_flag(
    body: FeatureFlagCreate,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Create a new feature flag."""
    existing = db.query(models.FeatureFlag).filter(models.FeatureFlag.key == body.key).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Feature flag '{body.key}' already exists.")

    if body.rollout_percentage is not None and not (0 <= body.rollout_percentage <= 100):
        raise HTTPException(status_code=400, detail="Rollout percentage must be 0-100.")

    flag = models.FeatureFlag(
        key=body.key,
        description=body.description,
        is_enabled=body.is_enabled,
        rollout_percentage=body.rollout_percentage,
    )
    db.add(flag)

    _log_admin_action(
        db,
        admin_user,
        action="feature_flag_create",
        target_type="feature_flag",
        target_id=body.key,
        metadata={"is_enabled": body.is_enabled, "rollout_percentage": body.rollout_percentage},
    )
    db.commit()
    db.refresh(flag)
    return _flag_to_dict(flag)


@router.patch("/feature-flags/{flag_id}")
def admin_update_feature_flag(
    flag_id: int,
    body: FeatureFlagUpdate,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Update a feature flag (toggle, rollout %, description)."""
    flag = db.query(models.FeatureFlag).filter(models.FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found.")

    changes: dict[str, object] = {}
    if body.is_enabled is not None:
        changes["is_enabled"] = {"from": flag.is_enabled, "to": body.is_enabled}
        flag.is_enabled = body.is_enabled
    if body.rollout_percentage is not None:
        if not (0 <= body.rollout_percentage <= 100):
            raise HTTPException(status_code=400, detail="Rollout percentage must be 0-100.")
        changes["rollout_percentage"] = {
            "from": flag.rollout_percentage,
            "to": body.rollout_percentage,
        }
        flag.rollout_percentage = body.rollout_percentage
    if body.description is not None:
        flag.description = body.description

    _log_admin_action(
        db,
        admin_user,
        action="feature_flag_update",
        target_type="feature_flag",
        target_id=flag.id,
        metadata={"key": flag.key, "changes": changes},
    )
    db.commit()
    db.refresh(flag)
    return _flag_to_dict(flag)


@router.delete("/feature-flags/{flag_id}")
def admin_delete_feature_flag(
    flag_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Delete a feature flag."""
    flag = db.query(models.FeatureFlag).filter(models.FeatureFlag.id == flag_id).first()
    if not flag:
        raise HTTPException(status_code=404, detail="Feature flag not found.")

    _log_admin_action(
        db,
        admin_user,
        action="feature_flag_delete",
        target_type="feature_flag",
        target_id=flag.id,
        metadata={"key": flag.key},
    )
    db.delete(flag)
    db.commit()
    return {"success": True}


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-03, Queue & Job Monitoring Endpoints
# ──────────────────────────────────────────────────────────────────────

QUEUE_MAP = {
    "audit_jobs": {"key": "audit_jobs", "worker_name": "audit_worker"},
    "audit_jobs:fast": {"key": "audit_jobs:fast", "worker_name": "audit_worker"},
    "audit_jobs:smart": {"key": "audit_jobs:smart", "worker_name": "audit_worker"},
    "audit_jobs:deep": {"key": "audit_jobs:deep", "worker_name": "audit_worker"},
    "pdf_jobs": {"key": "pdf_jobs", "worker_name": "pdf_worker"},
}


@router.get("/jobs/queues")
async def admin_get_job_queues(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Return queue depths, worker heartbeats, email outbox pending count, and audit metrics."""
    async with get_async_redis() as redis_client:
        queues = []
        for queue_name, meta in QUEUE_MAP.items():
            depth = await redis_client.llen(queue_name)
            heartbeat_raw = await redis_client.get(f"worker:heartbeat:{meta['worker_name']}")
            heartbeat = json.loads(heartbeat_raw) if heartbeat_raw else None
            queues.append(
                {
                    "name": queue_name.replace("_", " ").title(),
                    "key": meta["key"],
                    "depth": depth,
                    "worker_name": meta["worker_name"],
                    "worker_alive": heartbeat is not None,
                    "worker_last_seen": heartbeat.get("timestamp") if heartbeat else None,
                    "worker_pid": heartbeat.get("pid") if heartbeat else None,
                    "jobs_processed": heartbeat.get("jobs_processed", 0) if heartbeat else 0,
                }
            )

        # Email outbox pending count
        email_pending = (
            db.query(func.count(models.EmailOutbox.id))
            .filter(models.EmailOutbox.status.in_(["pending", "retry"]))
            .scalar()
            or 0
        )

        # Audit queue metrics from Redis hash
        audit_metrics = None
        raw = await redis_client.hgetall("audit:metrics")
        if raw:
            audit_metrics = {
                "jobs_started": int(raw.get("jobs_started", 0)),
                "jobs_succeeded": int(raw.get("jobs_succeeded", 0)),
                "jobs_failed": int(raw.get("jobs_failed", 0)),
                "job_retries": int(raw.get("job_retries", 0)),
                "job_duration_seconds_total": float(raw.get("job_duration_seconds_total", 0)),
            }

        return {
            "queues": queues,
            "email_outbox_pending": email_pending,
            "audit_metrics": audit_metrics,
        }


@router.get("/jobs/recent")
def admin_get_recent_jobs(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 25,
    queue: str | None = None,
    status: str | None = None,
):
    """Return recent jobs across audit and PDF queues, paginated."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 25

    items = []

    # Fetch audit jobs
    if not queue or queue == "audit_jobs":
        aq = db.query(
            models.AuditJob.id,
            models.AuditJob.user_id,
            models.User.email.label("user_email"),
            models.AuditJob.status,
            models.AuditJob.url,
            models.AuditJob.error,
            models.AuditJob.created_at,
            models.AuditJob.started_at,
            models.AuditJob.completed_at,
            models.AuditJob.last_heartbeat,
        ).outerjoin(models.User, models.AuditJob.user_id == models.User.id)
        if status:
            aq = aq.filter(models.AuditJob.status == status)
        for row in aq.order_by(models.AuditJob.created_at.desc()).limit(500).all():
            items.append(
                {
                    "id": row.id,
                    "queue": "audit_jobs",
                    "user_id": row.user_id,
                    "user_email": row.user_email,
                    "status": row.status,
                    "url": row.url,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "last_heartbeat": row.last_heartbeat.isoformat()
                    if row.last_heartbeat
                    else None,
                }
            )

    # Fetch PDF jobs
    if not queue or queue == "pdf_jobs":
        pq = db.query(
            models.ComplexReportJob.id,
            models.ComplexReportJob.user_id,
            models.User.email.label("user_email"),
            models.ComplexReportJob.status,
            models.ComplexReportJob.error,
            models.ComplexReportJob.created_at,
            models.ComplexReportJob.started_at,
            models.ComplexReportJob.completed_at,
            models.ComplexReportJob.last_heartbeat,
        ).outerjoin(models.User, models.ComplexReportJob.user_id == models.User.id)
        if status:
            pq = pq.filter(models.ComplexReportJob.status == status)
        for row in pq.order_by(models.ComplexReportJob.created_at.desc()).limit(500).all():
            items.append(
                {
                    "id": row.id,
                    "queue": "pdf_jobs",
                    "user_id": row.user_id,
                    "user_email": row.user_email,
                    "status": row.status,
                    "url": None,
                    "error": row.error,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "started_at": row.started_at.isoformat() if row.started_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "last_heartbeat": row.last_heartbeat.isoformat()
                    if row.last_heartbeat
                    else None,
                }
            )

    # Sort combined list by created_at descending
    items.sort(key=lambda x: x["created_at"] or "", reverse=True)

    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]

    return {
        "items": page_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/jobs/stats")
def admin_get_job_stats(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Return aggregate job statistics."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    # Audit job counts
    audit_24h = (
        db.query(func.count(models.AuditJob.id))
        .filter(models.AuditJob.created_at >= day_ago)
        .scalar()
        or 0
    )
    audit_7d = (
        db.query(func.count(models.AuditJob.id))
        .filter(models.AuditJob.created_at >= week_ago)
        .scalar()
        or 0
    )

    # PDF job counts
    pdf_24h = (
        db.query(func.count(models.ComplexReportJob.id))
        .filter(models.ComplexReportJob.created_at >= day_ago)
        .scalar()
        or 0
    )
    pdf_7d = (
        db.query(func.count(models.ComplexReportJob.id))
        .filter(models.ComplexReportJob.created_at >= week_ago)
        .scalar()
        or 0
    )

    # Status breakdown for audit jobs (last 7d)
    status_rows = (
        db.query(models.AuditJob.status, func.count(models.AuditJob.id))
        .filter(models.AuditJob.created_at >= week_ago)
        .group_by(models.AuditJob.status)
        .all()
    )
    jobs_by_status = {s: c for s, c in status_rows}

    # Average duration for completed audit jobs (last 7d)
    avg_dur = (
        db.query(
            func.avg(
                func.extract("epoch", models.AuditJob.completed_at)
                - func.extract("epoch", models.AuditJob.started_at)
            )
        )
        .filter(
            models.AuditJob.status == "succeeded",
            models.AuditJob.completed_at.isnot(None),
            models.AuditJob.started_at.isnot(None),
            models.AuditJob.created_at >= week_ago,
        )
        .scalar()
    )

    # Failure rate
    total_completed = sum(v for k, v in jobs_by_status.items() if k in ("succeeded", "failed"))
    failed_count = jobs_by_status.get("failed", 0)
    failure_rate = round((failed_count / total_completed * 100), 1) if total_completed > 0 else 0.0

    return {
        "jobs_by_status": jobs_by_status,
        "audit_jobs_24h": audit_24h,
        "audit_jobs_7d": audit_7d,
        "pdf_jobs_24h": pdf_24h,
        "pdf_jobs_7d": pdf_7d,
        "avg_duration_seconds": round(avg_dur, 2) if avg_dur else None,
        "failure_rate_pct": failure_rate,
    }


@router.post("/jobs/{queue_key}/purge")
async def admin_purge_queue(
    queue_key: str,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Purge all pending items from a Redis queue."""
    if queue_key not in QUEUE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown queue: {queue_key}")

    async with get_async_redis() as redis_client:
        depth_before = await redis_client.llen(queue_key)
        await redis_client.delete(queue_key)

    _log_admin_action(
        db,
        admin_user,
        action="queue.purge",
        target_type="queue",
        target_id=queue_key,
        metadata={"depth_before": depth_before},
    )

    return {"success": True, "deleted": depth_before}


# ──────────────────────────────────────────────────────────────────────
#  AEX-22, Dead Letter Queue Admin Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/jobs/dlq")
async def admin_list_dlq(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    offset: int = 0,
    limit: int = 50,
):
    """List entries in the audit dead letter queue (newest-first)."""
    from services.job_ttl_dlq_service import list_dlq, dlq_length

    async with get_async_redis() as redis_client:
        entries = await list_dlq(redis_client, offset=offset, limit=limit)
        total = await dlq_length(redis_client)
    return {"entries": entries, "total": total, "offset": offset, "limit": limit}


@router.post("/jobs/dlq/{job_id}/retry")
async def admin_retry_dlq(
    job_id: str,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Re-enqueue a DLQ entry by job_id."""
    from services.job_ttl_dlq_service import retry_dlq_entry

    async with get_async_redis() as redis_client:
        entry = await retry_dlq_entry(redis_client, job_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"DLQ entry not found: {job_id}")
    _log_admin_action(
        db,
        admin_user,
        action="dlq.retry",
        target_type="job",
        target_id=job_id,
        metadata={"retry_count": entry.get("retry_count", 0)},
    )
    return {"success": True, "job_id": job_id, "retried": True}


@router.delete("/jobs/dlq/{job_id}")
async def admin_discard_dlq(
    job_id: str,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Discard a DLQ entry without re-enqueuing."""
    from services.job_ttl_dlq_service import discard_dlq_entry

    async with get_async_redis() as redis_client:
        found = await discard_dlq_entry(redis_client, job_id)
    if not found:
        raise HTTPException(status_code=404, detail=f"DLQ entry not found: {job_id}")
    _log_admin_action(
        db,
        admin_user,
        action="dlq.discard",
        target_type="job",
        target_id=job_id,
    )
    return {"success": True, "job_id": job_id, "discarded": True}


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-04, GDPR Compliance Toolkit Endpoints
# ──────────────────────────────────────────────────────────────────────

import hashlib


@router.get("/gdpr/user/search")
def admin_gdpr_user_search(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
):
    """Search users for GDPR operations, returns user list with audit counts."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 20

    query = (
        db.query(
            models.User.id.label("user_id"),
            models.User.email,
            models.User.role,
            models.User.company_name,
            models.User.anonymized_at,
            func.count(models.Audit.id).label("audit_count"),
        )
        .outerjoin(models.Audit, models.Audit.user_id == models.User.id)
        .group_by(models.User.id)
    )

    if q:
        search_filter = or_(
            models.User.email.ilike(f"%{q}%"),
            models.User.company_name.ilike(f"%{q}%"),
        )
        query = query.filter(search_filter)

    total = query.count()
    offset = (page - 1) * page_size
    rows = query.order_by(models.User.id.desc()).offset(offset).limit(page_size).all()

    items = []
    for row in rows:
        items.append(
            {
                "user_id": row.user_id,
                "email": row.email,
                "role": row.role or "user",
                "company_name": row.company_name,
                "audit_count": row.audit_count or 0,
                "anonymized_at": row.anonymized_at.isoformat() if row.anonymized_at else None,
            }
        )

    return {"items": items, "total": total}


@router.get("/gdpr/data-map")
def admin_gdpr_data_map(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the data processing register, categories, PII fields, retention, legal basis."""
    total_users = db.query(func.count(models.User.id)).scalar() or 0
    anonymized_users = (
        db.query(func.count(models.User.id)).filter(models.User.anonymized_at.isnot(None)).scalar()
        or 0
    )

    entries = [
        {
            "category": "User Profile",
            "table": "users",
            "pii_fields": [
                "email",
                "company_name",
                "billing_email",
                "billing_phone",
                "billing_address_line1",
                "billing_address_line2",
                "billing_city",
                "billing_state",
                "billing_postal_code",
                "billing_country",
            ],
            "retention_policy": "Until account deletion or anonymization",
            "legal_basis": "Contract performance (Art. 6(1)(b))",
            "record_count": total_users,
        },
        {
            "category": "Audit Data",
            "table": "audits",
            "pii_fields": ["url (may contain PII in query params)"],
            "retention_policy": "90 days unless flagged; screenshots stripped after 30 days",
            "legal_basis": "Contract performance (Art. 6(1)(b))",
            "record_count": db.query(func.count(models.Audit.id)).scalar() or 0,
        },
        {
            "category": "Billing & Payments",
            "table": "billing_payments",
            "pii_fields": ["stripe_customer_id", "stripe_invoice_id", "receipt_url"],
            # SIGV2-1144: the real UAE period, not an invented one. Five years
            # following the Tax Period the invoice relates to, extended by four
            # years for an audit, a notified audit or a dispute (or until final
            # settlement, whichever is later) and by one year from a Voluntary
            # Disclosure. Survives account deletion, anonymised.
            "retention_policy": (
                "5 years after the Tax Period the invoice relates to "
                "(UAE Cabinet Decision 74/2023 Art. 3); +4 years for an audit, "
                "notified audit or dispute, +1 year from a Voluntary Disclosure"
            ),
            "legal_basis": "Legal obligation (Art. 6(1)(c); GDPR Art. 17(3)(b))",
            "record_count": db.query(func.count(models.BillingPayment.id)).scalar() or 0,
        },
        {
            "category": "Email Communications",
            "table": "email_outbox",
            "pii_fields": ["to_email", "subject", "html_body"],
            "retention_policy": "90 days",
            "legal_basis": "Contract performance (Art. 6(1)(b))",
            "record_count": db.query(func.count(models.EmailOutbox.id)).scalar() or 0,
        },
        {
            "category": "Credit Adjustments",
            "table": "user_credit_adjustments",
            "pii_fields": ["reason (may reference user)"],
            "retention_policy": "Until account deletion",
            "legal_basis": "Contract performance (Art. 6(1)(b))",
            "record_count": db.query(func.count(models.UserCreditAdjustment.id)).scalar() or 0,
        },
        {
            "category": "Subscriptions",
            "table": "subscriptions",
            "pii_fields": ["stripe_customer_id", "stripe_subscription_id"],
            "retention_policy": "Until account deletion",
            "legal_basis": "Contract performance (Art. 6(1)(b))",
            "record_count": db.query(func.count(models.Subscription.id)).scalar() or 0,
        },
        {
            "category": "Admin Action Logs",
            "table": "admin_action_logs",
            "pii_fields": ["admin_user_id", "target_id (may reference user)"],
            "retention_policy": "Indefinite (accountability)",
            "legal_basis": "Legitimate interest (Art. 6(1)(f))",
            "record_count": db.query(func.count(models.AdminActionLog.id)).scalar() or 0,
        },
    ]

    return {"entries": entries, "total_users": total_users, "anonymized_users": anonymized_users}


@router.get("/gdpr/user/{user_id}")
def admin_gdpr_user_detail(
    user_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return GDPR summary for a specific user."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    audit_count = (
        db.query(func.count(models.Audit.id)).filter(models.Audit.user_id == user_id).scalar() or 0
    )
    email_count = (
        db.query(func.count(models.EmailOutbox.id))
        .filter(models.EmailOutbox.user_id == user_id)
        .scalar()
        or 0
    )
    payment_count = (
        db.query(func.count(models.BillingPayment.id))
        .filter(models.BillingPayment.user_id == user_id)
        .scalar()
        or 0
    )
    has_subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user_id).first()
        is not None
    )

    created_at = getattr(user, "created_at", None)

    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role or "user",
        "company_name": user.company_name,
        "created_at": created_at.isoformat() if hasattr(created_at, "isoformat") else created_at,
        "anonymized_at": user.anonymized_at.isoformat() if user.anonymized_at else None,
        "audit_count": audit_count,
        "email_count": email_count,
        "payment_count": payment_count,
        "has_subscription": has_subscription,
    }


@router.post("/gdpr/export/{user_id}")
def admin_gdpr_export(
    user_id: int,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Generate a SAR (Subject Access Request) data export for a user."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    # Profile data
    profile = {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "company_name": user.company_name,
        "company_legal_name": user.company_legal_name,
        "billing_email": user.billing_email,
        "billing_phone": user.billing_phone,
        "billing_address": {
            "line1": user.billing_address_line1,
            "line2": user.billing_address_line2,
            "city": user.billing_city,
            "state": user.billing_state,
            "postal_code": user.billing_postal_code,
            "country": user.billing_country,
        },
        "notifications_enabled": user.notifications_enabled,
        "auth_provider": user.auth_provider,
        "anonymized_at": user.anonymized_at.isoformat() if user.anonymized_at else None,
    }

    # Audits
    audits_raw = db.query(models.Audit).filter(models.Audit.user_id == user_id).all()
    audits = []
    for a in audits_raw:
        audits.append(
            {
                "id": a.id,
                "url": a.url,
                "audit_type": getattr(a, "audit_type", None),
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
        )

    # Emails
    emails_raw = db.query(models.EmailOutbox).filter(models.EmailOutbox.user_id == user_id).all()
    emails = []
    for e in emails_raw:
        emails.append(
            {
                "id": e.id,
                "to_email": e.to_email,
                "subject": e.subject,
                "template_key": e.template_key,
                "status": e.status,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "sent_at": e.sent_at.isoformat() if e.sent_at else None,
            }
        )

    # Payments
    payments_raw = (
        db.query(models.BillingPayment).filter(models.BillingPayment.user_id == user_id).all()
    )
    payments = []
    for p in payments_raw:
        payments.append(
            {
                "id": p.id,
                "amount": getattr(p, "amount", None),
                "currency": getattr(p, "currency", None),
                "status": getattr(p, "status", None),
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
        )

    # Credit adjustments
    adjustments_raw = (
        db.query(models.UserCreditAdjustment)
        .filter(models.UserCreditAdjustment.user_id == user_id)
        .all()
    )
    adjustments = []
    for adj in adjustments_raw:
        adjustments.append(
            {
                "id": adj.id,
                "amount": adj.amount,
                "reason": getattr(adj, "reason", None),
                "created_at": adj.created_at.isoformat() if adj.created_at else None,
            }
        )

    # Subscription
    sub = db.query(models.Subscription).filter(models.Subscription.user_id == user_id).first()
    subscription = None
    if sub:
        subscription = {
            "id": sub.id,
            "plan_type": sub.plan_type,
            "status": getattr(sub, "status", None),
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
        }

    export_data = {
        "profile": profile,
        "audits": audits,
        "emails_sent": emails,
        "payments": payments,
        "credit_adjustments": adjustments,
        "subscription": subscription,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "export_type": "GDPR Subject Access Request (Article 15)",
    }

    _log_admin_action(
        db,
        admin_user,
        action="gdpr.export",
        target_type="user",
        target_id=user_id,
        metadata={"categories": list(export_data.keys())},
    )
    db.commit()

    return export_data


class AnonymizeRequest(BaseModel):
    confirm_email: str


@router.post("/gdpr/anonymize/{user_id}")
def admin_gdpr_anonymize(
    user_id: int,
    body: AnonymizeRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Anonymize a user's PII, replace with hashed values, keep structural data."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    if user.anonymized_at:
        raise HTTPException(status_code=400, detail="User is already anonymized.")

    if body.confirm_email != user.email:
        raise HTTPException(status_code=400, detail="Confirmation email does not match user email.")

    if user.id == admin_user.id:
        raise HTTPException(status_code=400, detail="Cannot anonymize your own account.")

    # Hash PII fields
    hash_prefix = hashlib.sha256(f"anon:{user.id}:{user.email}".encode()).hexdigest()[:12]
    anon_email = f"anon_{hash_prefix}@redacted.invalid"

    # The retained invoices must still say who they were issued to after the
    # account's own fields are overwritten (SIGV2-1144).
    snapshot_invoice_customer_identity(db, user=user)

    original_email = user.email
    user.email = anon_email
    user.company_name = None
    user.company_legal_name = None
    user.company_registration_number = None
    user.company_vat_number = None
    user.billing_email = None
    user.billing_phone = None
    user.billing_address_line1 = None
    user.billing_address_line2 = None
    user.billing_city = None
    user.billing_state = None
    user.billing_postal_code = None
    user.billing_country = None
    user.billing_website_url = None
    user.custom_logo_url = None
    user.hashed_password = "ANONYMIZED"
    user.mfa_secret = None
    user.unsubscribe_token = None
    user.anonymized_at = datetime.now(timezone.utc)

    # Anonymize email outbox entries
    db.query(models.EmailOutbox).filter(models.EmailOutbox.user_id == user_id).update(
        {"to_email": anon_email, "html_body": "REDACTED", "text_body": "REDACTED"}
    )

    _log_admin_action(
        db,
        admin_user,
        action="gdpr.anonymize",
        target_type="user",
        target_id=user_id,
        metadata={"original_email_hash": hashlib.sha256(original_email.encode()).hexdigest()[:16]},
    )
    db.commit()

    return {"message": f"User {user_id} has been anonymized successfully."}


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-08, Workspace & Project Admin Browser
# ──────────────────────────────────────────────────────────────────────


class AdminWorkspaceEntry(BaseModel):
    id: int
    name: str
    owner_id: int
    owner_email: str
    plan_name: str
    member_count: int
    project_count: int
    created_at: datetime


class AdminWorkspacesResponse(BaseModel):
    items: list[AdminWorkspaceEntry]
    total: int
    page: int
    per_page: int


class AdminWorkspaceMemberEntry(BaseModel):
    user_id: int
    email: str
    name: str | None = None
    role: str
    joined_at: datetime


class AdminWorkspaceProjectEntry(BaseModel):
    id: int
    name: str
    domain_url: str | None = None
    created_at: datetime


class AdminWorkspaceAuditEntry(BaseModel):
    id: int
    url: str
    audit_type: str | None = None
    geo_score: float | None = None
    seo_score: float | None = None
    aeo_score: float | None = None
    project_name: str | None = None
    created_at: datetime | None = None


class AdminWorkspaceUsageSummary(BaseModel):
    total_audits: int
    audits_this_month: int
    projects_count: int
    member_count: int


class AdminWorkspaceBilling(BaseModel):
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    plan_name: str
    subscription_status: str | None = None


class AdminWorkspaceDetailResponse(BaseModel):
    id: int
    name: str
    owner_id: int
    owner_email: str
    plan_name: str
    created_at: datetime
    members: list[AdminWorkspaceMemberEntry]
    projects: list[AdminWorkspaceProjectEntry]
    usage_summary: AdminWorkspaceUsageSummary
    billing: AdminWorkspaceBilling


class AdminWorkspaceUpdateRequest(BaseModel):
    name: str | None = None


@router.get("/workspaces", response_model=AdminWorkspacesResponse)
def admin_list_workspaces(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    per_page: int = 25,
    search: str | None = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
):
    """Paginated workspace list with aggregate counts."""
    if page < 1:
        page = 1
    if per_page < 1 or per_page > 200:
        per_page = 25

    # Subqueries for aggregate counts
    member_count_sq = (
        db.query(
            models.WorkspaceUser.workspace_id,
            func.count(models.WorkspaceUser.id).label("member_count"),
        )
        .group_by(models.WorkspaceUser.workspace_id)
        .subquery()
    )

    project_count_sq = (
        db.query(
            models.Project.workspace_id,
            func.count(models.Project.id).label("project_count"),
        )
        .group_by(models.Project.workspace_id)
        .subquery()
    )

    query = (
        db.query(
            models.Workspace.id,
            models.Workspace.name,
            models.Workspace.owner_id,
            models.User.email.label("owner_email"),
            models.Workspace.created_at,
            func.coalesce(member_count_sq.c.member_count, 0).label("member_count"),
            func.coalesce(project_count_sq.c.project_count, 0).label("project_count"),
        )
        .join(models.User, models.Workspace.owner_id == models.User.id)
        .outerjoin(member_count_sq, models.Workspace.id == member_count_sq.c.workspace_id)
        .outerjoin(project_count_sq, models.Workspace.id == project_count_sq.c.workspace_id)
    )

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                models.Workspace.name.ilike(term),
                models.User.email.ilike(term),
            )
        )

    # Get total before pagination
    total = query.count()

    # Sorting
    allowed_sort_cols = {
        "created_at": models.Workspace.created_at,
        "name": models.Workspace.name,
    }
    sort_col = allowed_sort_cols.get(sort_by, models.Workspace.created_at)
    if sort_order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    offset = (page - 1) * per_page
    rows = query.offset(offset).limit(per_page).all()

    # We need to resolve plan names, fetch workspace owners in bulk
    workspace_ids = [r.id for r in rows]
    workspace_objs = (
        (db.query(models.Workspace).filter(models.Workspace.id.in_(workspace_ids)).all())
        if workspace_ids
        else []
    )
    plan_map = {w.id: resolve_workspace_plan(w) for w in workspace_objs}

    items = []
    for row in rows:
        items.append(
            AdminWorkspaceEntry(
                id=row.id,
                name=row.name,
                owner_id=row.owner_id,
                owner_email=row.owner_email,
                plan_name=plan_map.get(row.id, "plan_standard"),
                member_count=row.member_count,
                project_count=row.project_count,
                created_at=row.created_at,
            )
        )

    return AdminWorkspacesResponse(items=items, total=total, page=page, per_page=per_page)


@router.get("/workspaces/{workspace_id}", response_model=AdminWorkspaceDetailResponse)
def admin_workspace_detail(
    workspace_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Workspace detail with members, projects, usage summary, and billing."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    owner = workspace.owner
    owner_email = owner.email if owner else "unknown"
    plan_name = resolve_workspace_plan(workspace)
    billing_info = resolve_workspace_billing(workspace)

    # Members
    member_rows = (
        db.query(
            models.WorkspaceUser.user_id,
            models.User.email,
            models.User.company_name.label("name"),
            models.WorkspaceUser.role,
            models.WorkspaceUser.created_at.label("joined_at"),
        )
        .join(models.User, models.WorkspaceUser.user_id == models.User.id)
        .filter(models.WorkspaceUser.workspace_id == workspace_id)
        .order_by(models.WorkspaceUser.created_at.asc())
        .all()
    )
    members = [
        AdminWorkspaceMemberEntry(
            user_id=m.user_id,
            email=m.email,
            name=m.name,
            role=str(m.role.value) if hasattr(m.role, "value") else str(m.role),
            joined_at=m.joined_at,
        )
        for m in member_rows
    ]

    # Projects
    project_rows = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace_id)
        .order_by(models.Project.created_at.desc())
        .all()
    )
    projects = [
        AdminWorkspaceProjectEntry(
            id=p.id,
            name=p.name,
            domain_url=p.domain_url,
            created_at=p.created_at,
        )
        for p in project_rows
    ]

    # Usage summary
    project_ids = [p.id for p in project_rows]
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    total_audits = 0
    audits_this_month = 0
    if project_ids:
        total_audits = (
            db.query(func.count(models.Audit.id))
            .filter(models.Audit.project_id.in_(project_ids))
            .scalar()
        ) or 0
        audits_this_month = (
            db.query(func.count(models.Audit.id))
            .filter(
                models.Audit.project_id.in_(project_ids),
                models.Audit.created_at >= month_start,
            )
            .scalar()
        ) or 0

    usage_summary = AdminWorkspaceUsageSummary(
        total_audits=total_audits,
        audits_this_month=audits_this_month,
        projects_count=len(project_rows),
        member_count=len(member_rows),
    )

    return AdminWorkspaceDetailResponse(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        owner_email=owner_email,
        plan_name=plan_name,
        created_at=workspace.created_at,
        members=members,
        projects=projects,
        usage_summary=usage_summary,
        billing=AdminWorkspaceBilling(**billing_info),
    )


@router.patch("/workspaces/{workspace_id}")
def admin_update_workspace(
    workspace_id: int,
    body: AdminWorkspaceUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Update workspace properties. Only name is mutable from admin."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    changes: dict[str, object] = {}
    if body.name is not None and body.name.strip():
        changes["name"] = {"from": workspace.name, "to": body.name.strip()}
        workspace.name = body.name.strip()

    if not changes:
        raise HTTPException(status_code=400, detail="No changes provided.")

    _log_admin_action(
        db,
        admin_user,
        action="workspace.update",
        target_type="workspace",
        target_id=workspace_id,
        metadata=changes,
    )
    db.commit()
    db.refresh(workspace)

    return {
        "success": True,
        "workspace": {
            "id": workspace.id,
            "name": workspace.name,
        },
    }


@router.get("/workspaces/{workspace_id}/members")
def admin_workspace_members(
    workspace_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Membership roster for a workspace."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    rows = (
        db.query(
            models.WorkspaceUser.user_id,
            models.User.email,
            models.User.company_name.label("name"),
            models.WorkspaceUser.role,
            models.WorkspaceUser.created_at.label("joined_at"),
        )
        .join(models.User, models.WorkspaceUser.user_id == models.User.id)
        .filter(models.WorkspaceUser.workspace_id == workspace_id)
        .order_by(models.WorkspaceUser.created_at.asc())
        .all()
    )

    members = [
        {
            "user_id": r.user_id,
            "email": r.email,
            "name": r.name,
            "role": str(r.role.value) if hasattr(r.role, "value") else str(r.role),
            "joined_at": r.joined_at.isoformat() if r.joined_at else None,
        }
        for r in rows
    ]

    return {"members": members, "total": len(members)}


@router.get("/workspaces/{workspace_id}/projects")
def admin_workspace_projects(
    workspace_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Projects belonging to a workspace."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    rows = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace_id)
        .order_by(models.Project.created_at.desc())
        .all()
    )

    projects = [
        {
            "id": p.id,
            "name": p.name,
            "domain_url": p.domain_url,
            "language": p.language,
            "target_country": p.target_country,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in rows
    ]

    return {"projects": projects, "total": len(projects)}


@router.get("/workspaces/{workspace_id}/audit-history")
def admin_workspace_audit_history(
    workspace_id: int,
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    page: int = 1,
    page_size: int = 25,
):
    """Paginated audit history for all projects in a workspace."""
    if page < 1:
        page = 1
    if page_size < 1 or page_size > 200:
        page_size = 25

    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Get project IDs for this workspace
    project_ids = [
        pid
        for (pid,) in db.query(models.Project.id)
        .filter(models.Project.workspace_id == workspace_id)
        .all()
    ]

    if not project_ids:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    query = (
        db.query(
            models.Audit.id,
            models.Audit.url,
            models.Audit.audit_type,
            models.Audit.geo_score,
            models.Audit.seo_score,
            models.Audit.aeo_score,
            models.Audit.created_at,
            models.Project.name.label("project_name"),
        )
        .outerjoin(models.Project, models.Audit.project_id == models.Project.id)
        .filter(models.Audit.project_id.in_(project_ids))
    )

    total = query.count()
    offset = (page - 1) * page_size
    rows = query.order_by(models.Audit.created_at.desc()).offset(offset).limit(page_size).all()

    items = [
        {
            "id": r.id,
            "url": r.url,
            "audit_type": str(r.audit_type.value)
            if hasattr(r.audit_type, "value")
            else str(r.audit_type)
            if r.audit_type
            else None,
            "geo_score": r.geo_score,
            "seo_score": r.seo_score,
            "aeo_score": r.aeo_score,
            "project_name": r.project_name,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}


class WorkspaceAdminDeletePayload(BaseModel):
    project_action: Literal["delete", "move"] = "delete"
    target_workspace_id: int | None = None


@router.post("/workspaces/{workspace_id}/delete")
def admin_delete_workspace(
    workspace_id: int,
    payload: WorkspaceAdminDeletePayload,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """
    Delete a workspace as an admin.
    If the workspace has projects, they can be either deleted or moved to another workspace.
    """
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    if payload.project_action == "move":
        if not payload.target_workspace_id:
            raise HTTPException(
                status_code=400, detail="target_workspace_id is required when moving projects."
            )
        if payload.target_workspace_id == workspace_id:
            raise HTTPException(
                status_code=400, detail="Cannot move projects to the same workspace."
            )

        target_ws = (
            db.query(models.Workspace)
            .filter(models.Workspace.id == payload.target_workspace_id)
            .first()
        )
        if not target_ws:
            raise HTTPException(status_code=404, detail="Target workspace not found.")

        # Move projects
        db.query(models.Project).filter(models.Project.workspace_id == workspace_id).update(
            {"workspace_id": target_ws.id}, synchronize_session=False
        )

    # Proceed to delete the workspace. SQLAlchemy relationships with cascade="all, delete-orphan" will handle the rest.
    db.delete(workspace)

    # Log the action
    _log_admin_action(
        db,
        admin_user,
        "delete_workspace",
        "workspace",
        str(workspace_id),
        {
            "project_action": payload.project_action,
            "target_workspace_id": payload.target_workspace_id,
        },
    )

    db.commit()

    return {"status": "success", "message": f"Workspace {workspace_id} deleted."}


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-11, AI Cost Monitoring & Budget Dashboard
# ──────────────────────────────────────────────────────────────────────


@router.get("/costs/summary")
def admin_costs_summary(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    """KPI bar: current month spend, projected month-end, avg cost/audit."""
    currency_policy = _get_admin_currency_policy_for_reporting(db)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    day_of_month = now.day
    days_in_month = 30  # approximate

    # Current month audits
    month_audits = _apply_admin_cost_filters(
        db.query(models.Audit).filter(models.Audit.created_at >= month_start),
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    )
    month_audits = month_audits.all()
    month_economics = _load_admin_audit_economics(db, month_audits)

    total_cost_month = 0.0
    total_tokens_month = 0
    model_costs: dict[str, float] = {}

    for audit_entry in month_economics:
        total_cost_month += _coerce_admin_cost_float(audit_entry.get("total_cost_usd"))
        total_tokens_month += _coerce_admin_cost_int(audit_entry.get("total_tokens"))
        for model_entry in audit_entry.get("model_entries") or []:
            if not isinstance(model_entry, dict):
                continue
            model_name = str(model_entry.get("model") or "unknown").strip() or "unknown"
            model_costs[model_name] = model_costs.get(model_name, 0.0) + _coerce_admin_cost_float(
                model_entry.get("cost_usd")
            )

    audit_count = len(month_audits)
    avg_cost = round(total_cost_month / max(audit_count, 1), 2)

    # Linear projection
    if day_of_month > 0:
        daily_rate = total_cost_month / day_of_month
        projected_month_end = round(daily_rate * days_in_month, 2)
    else:
        projected_month_end = 0.0

    # Previous month for comparison
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    prev_count_query = _apply_admin_cost_filters(
        db.query(func.count(models.Audit.id)).filter(
            models.Audit.created_at >= prev_month_start,
            models.Audit.created_at < month_start,
        ),
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    )
    prev_count = prev_count_query.scalar() or 0

    return {
        "currency": "USD",
        "currency_policy": currency_policy,
        "fx_reference": fx_reference,
        "current_month_cost": round(total_cost_month, 2),
        "projected_month_end": round(projected_month_end, 2),
        "avg_cost_per_audit": avg_cost,
        "total_tokens_month": total_tokens_month,
        "audit_count_month": audit_count,
        "prev_month_audit_count": prev_count,
        "top_model": max(model_costs, key=model_costs.get, default="unknown")
        if model_costs
        else "N/A",
        "top_model_cost": round(max(model_costs.values(), default=0), 2),
    }


@router.get("/costs/daily")
def admin_costs_daily(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    days: int = 30,
    workspace_id: int | None = None,
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    """Daily cost time-series for the last N days."""
    currency_policy = _get_admin_currency_policy_for_reporting(db)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))
    if days < 1 or days > 180:
        days = 30

    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    query = db.query(models.Audit).filter(models.Audit.created_at >= start_date)
    query = _apply_admin_cost_filters(
        query,
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    )

    if workspace_id is not None:
        project_ids = [
            pid
            for (pid,) in db.query(models.Project.id)
            .filter(models.Project.workspace_id == workspace_id)
            .all()
        ]
        if not project_ids:
            return {
                "currency": "USD",
                "currency_policy": currency_policy,
                "fx_reference": fx_reference,
                "days": days,
                "series": [],
                "summary": {"total_cost": 0, "avg_daily": 0},
            }
        query = query.filter(models.Audit.project_id.in_(project_ids))

    audits = query.all()
    audit_economics = _load_admin_audit_economics(db, audits)

    # Group by date
    daily_data: dict[str, dict] = {}
    for audit_entry in audit_economics:
        created_at = audit_entry.get("created_at")
        if not isinstance(created_at, datetime):
            continue
        date_key = created_at.strftime("%Y-%m-%d")
        tokens = _coerce_admin_cost_int(audit_entry.get("total_tokens"))
        cost = _coerce_admin_cost_float(audit_entry.get("total_cost_usd"))

        if date_key not in daily_data:
            daily_data[date_key] = {
                "total_cost": 0.0,
                "total_tokens": 0,
                "audit_count": 0,
                "by_model": {},
            }
        daily_data[date_key]["total_cost"] += cost
        daily_data[date_key]["total_tokens"] += tokens
        daily_data[date_key]["audit_count"] += 1
        for model_entry in audit_entry.get("model_entries") or []:
            if not isinstance(model_entry, dict):
                continue
            model_name = str(model_entry.get("model") or "unknown").strip() or "unknown"
            model_cost = _coerce_admin_cost_float(model_entry.get("cost_usd"))
            daily_data[date_key]["by_model"][model_name] = (
                daily_data[date_key]["by_model"].get(model_name, 0.0) + model_cost
            )

    # Fill missing dates and sort
    series = []
    current = start_date.date()
    end = now.date()
    while current <= end:
        dk = current.isoformat()
        entry = daily_data.get(
            dk, {"total_cost": 0.0, "total_tokens": 0, "audit_count": 0, "by_model": {}}
        )
        series.append(
            {
                "date": dk,
                "total_cost": round(entry["total_cost"], 2),
                "total_tokens": entry["total_tokens"],
                "audit_count": entry["audit_count"],
                "by_model": {k: round(v, 2) for k, v in entry["by_model"].items()},
            }
        )
        current += timedelta(days=1)

    total_cost = sum(s["total_cost"] for s in series)
    avg_daily = round(total_cost / max(len(series), 1), 2)

    return {
        "currency": "USD",
        "currency_policy": currency_policy,
        "fx_reference": fx_reference,
        "days": days,
        "series": series,
        "summary": {
            "total_cost": round(total_cost, 2),
            "avg_daily": avg_daily,
        },
    }


@router.get("/costs/by-model")
def admin_costs_by_model(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    window_days: int = 30,
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    """Cost breakdown by AI model over the given window."""
    currency_policy = _get_admin_currency_policy_for_reporting(db)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))
    if window_days < 1 or window_days > 365:
        window_days = 30

    start_date = datetime.now(timezone.utc) - timedelta(days=window_days)
    audits = _apply_admin_cost_filters(
        db.query(models.Audit).filter(models.Audit.created_at >= start_date),
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    ).all()
    audit_economics = _load_admin_audit_economics(db, audits)

    model_breakdown: dict[str, dict] = {}
    for audit_entry in audit_economics:
        seen_models: set[str] = set()
        for model_entry in audit_entry.get("model_entries") or []:
            if not isinstance(model_entry, dict):
                continue
            model_name = str(model_entry.get("model") or "unknown").strip() or "unknown"
            if model_name not in model_breakdown:
                model_breakdown[model_name] = {"tokens": 0, "cost": 0.0, "audits": 0}
            model_breakdown[model_name]["tokens"] += _coerce_admin_cost_int(
                model_entry.get("tokens")
            )
            model_breakdown[model_name]["cost"] += _coerce_admin_cost_float(
                model_entry.get("cost_usd")
            )
            if model_name not in seen_models:
                model_breakdown[model_name]["audits"] += 1
                seen_models.add(model_name)

    items = sorted(
        [
            {
                "model": k,
                "tokens": v["tokens"],
                "cost": round(v["cost"], 2),
                "audits": v["audits"],
                "cost_per_1m_usd": {
                    "input": float(get_token_pricing_for_model(k)["input"]),
                    "output": float(get_token_pricing_for_model(k)["output"]),
                },
            }
            for k, v in model_breakdown.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )

    return {
        "currency": "USD",
        "currency_policy": currency_policy,
        "fx_reference": fx_reference,
        "window_days": window_days,
        "models": items,
        "total_cost": round(sum(i["cost"] for i in items), 2),
    }


@router.get("/costs/by-workspace")
def admin_costs_by_workspace(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    window_days: int = 30,
    limit: int = 10,
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    """Top workspaces by AI cost over the given window."""
    currency_policy = _get_admin_currency_policy_for_reporting(db)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))
    if window_days < 1 or window_days > 365:
        window_days = 30
    if limit < 1 or limit > 50:
        limit = 10

    start_date = datetime.now(timezone.utc) - timedelta(days=window_days)

    # Fetch audits with project_id set
    audits = _apply_admin_cost_filters(
        db.query(models.Audit).filter(
            models.Audit.created_at >= start_date,
            models.Audit.project_id.isnot(None),
        ),
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    )
    audits = audits.all()
    audit_economics = {
        int(item.get("audit_id")): item
        for item in _load_admin_audit_economics(db, audits)
        if item.get("audit_id") is not None
    }

    # Build project_id -> workspace_id map
    project_ids = list({a.project_id for a in audits if a.project_id})
    project_ws_map: dict[int, int] = {}
    if project_ids:
        rows = (
            db.query(models.Project.id, models.Project.workspace_id)
            .filter(models.Project.id.in_(project_ids))
            .all()
        )
        project_ws_map = {r.id: r.workspace_id for r in rows}

    # Aggregate cost by workspace
    ws_costs: dict[int, dict] = {}
    for audit in audits:
        ws_id = project_ws_map.get(audit.project_id)
        if ws_id is None:
            continue
        audit_entry = audit_economics.get(int(audit.id))
        tokens = _coerce_admin_cost_int((audit_entry or {}).get("total_tokens"))
        cost = _coerce_admin_cost_float((audit_entry or {}).get("total_cost_usd"))
        if ws_id not in ws_costs:
            ws_costs[ws_id] = {"cost": 0.0, "audits": 0, "tokens": 0}
        ws_costs[ws_id]["cost"] += cost
        ws_costs[ws_id]["audits"] += 1
        ws_costs[ws_id]["tokens"] += tokens

    # Resolve workspace names
    ws_ids = list(ws_costs.keys())
    ws_names: dict[int, str] = {}
    if ws_ids:
        rows = (
            db.query(models.Workspace.id, models.Workspace.name)
            .filter(models.Workspace.id.in_(ws_ids))
            .all()
        )
        ws_names = {r.id: r.name for r in rows}

    items = sorted(
        [
            {
                "workspace_id": wid,
                "workspace_name": ws_names.get(wid, f"Workspace #{wid}"),
                "cost": round(data["cost"], 2),
                "audits": data["audits"],
                "tokens": data["tokens"],
            }
            for wid, data in ws_costs.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )[:limit]

    return {
        "currency": "USD",
        "currency_policy": currency_policy,
        "fx_reference": fx_reference,
        "window_days": window_days,
        "workspaces": items,
    }


@router.get("/costs/by-user")
def admin_costs_by_user(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
    window_days: int = 30,
    limit: int = 10,
    requested_tier: str | None = None,
    debate_profile: str | None = None,
):
    """Top users by AI cost over the given window."""
    currency_policy = _get_admin_currency_policy_for_reporting(db)
    fx_reference = _serialize_admin_fx_reference(_get_admin_ai_cost_fx_snapshot(db))
    if window_days < 1 or window_days > 365:
        window_days = 30
    if limit < 1 or limit > 50:
        limit = 10

    start_date = datetime.now(timezone.utc) - timedelta(days=window_days)
    audits = _apply_admin_cost_filters(
        db.query(models.Audit).filter(
            models.Audit.created_at >= start_date,
            models.Audit.user_id.isnot(None),
        ),
        requested_tier=requested_tier,
        debate_profile=debate_profile,
    )
    audits = audits.all()
    audit_economics = {
        int(item.get("audit_id")): item
        for item in _load_admin_audit_economics(db, audits)
        if item.get("audit_id") is not None
    }

    user_costs: dict[int, dict] = {}
    for audit in audits:
        uid = audit.user_id
        audit_entry = audit_economics.get(int(audit.id))
        tokens = _coerce_admin_cost_int((audit_entry or {}).get("total_tokens"))
        cost = _coerce_admin_cost_float((audit_entry or {}).get("total_cost_usd"))
        if uid not in user_costs:
            user_costs[uid] = {"cost": 0.0, "audits": 0, "tokens": 0}
        user_costs[uid]["cost"] += cost
        user_costs[uid]["audits"] += 1
        user_costs[uid]["tokens"] += tokens

    # Resolve user emails
    user_ids = list(user_costs.keys())
    user_emails: dict[int, str] = {}
    if user_ids:
        rows = (
            db.query(models.User.id, models.User.email).filter(models.User.id.in_(user_ids)).all()
        )
        user_emails = {r.id: r.email for r in rows}

    items = sorted(
        [
            {
                "user_id": uid,
                "email": user_emails.get(uid, f"User #{uid}"),
                "cost": round(data["cost"], 2),
                "audits": data["audits"],
                "tokens": data["tokens"],
            }
            for uid, data in user_costs.items()
        ],
        key=lambda x: x["cost"],
        reverse=True,
    )[:limit]

    return {
        "currency": "USD",
        "currency_policy": currency_policy,
        "fx_reference": fx_reference,
        "window_days": window_days,
        "users": items,
    }


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-12, Server Load & Infrastructure Monitoring
# ──────────────────────────────────────────────────────────────────────


def _get_process_metrics() -> dict:
    """Read process metrics from /proc/self/ (Linux only, no psutil needed)."""
    result: dict = {
        "memory_rss_mb": None,
        "memory_vms_mb": None,
        "uptime_seconds": None,
        "threads": None,
    }
    try:
        with open("/proc/self/status", "r") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    result["memory_rss_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("VmSize:"):
                    result["memory_vms_mb"] = round(int(line.split()[1]) / 1024, 1)
                elif line.startswith("Threads:"):
                    result["threads"] = int(line.split()[1])
    except Exception:
        pass
    try:
        with open("/proc/uptime", "r") as f:
            result["uptime_seconds"] = round(float(f.read().split()[0]), 0)
    except Exception:
        pass
    try:
        with open("/proc/loadavg", "r") as f:
            parts = f.read().split()
            result["load_avg_1m"] = float(parts[0])
            result["load_avg_5m"] = float(parts[1])
            result["load_avg_15m"] = float(parts[2])
    except Exception:
        pass
    return result


def _get_db_pool_metrics(db: Session) -> dict:
    """Get SQLAlchemy connection pool stats and basic PG stats."""
    result: dict = {}
    try:
        pool = db.get_bind().pool
        result["pool_size"] = pool.size()
        result["checked_in"] = pool.checkedin()
        result["checked_out"] = pool.checkedout()
        result["overflow"] = pool.overflow()
        result["max_overflow"] = pool._max_overflow
    except Exception:
        pass
    try:
        result["db_size_mb"] = round(
            db.execute(
                text("SELECT pg_database_size(current_database()) / 1024.0 / 1024.0")
            ).scalar()
            or 0,
            1,
        )
    except Exception:
        result["db_size_mb"] = None
    try:
        result["active_connections"] = db.execute(
            text("SELECT count(*) FROM pg_stat_activity WHERE state = 'active'")
        ).scalar()
        result["total_connections"] = db.execute(
            text("SELECT count(*) FROM pg_stat_activity")
        ).scalar()
    except Exception:
        pass
    try:
        rows = db.execute(
            text("""
            SELECT relname AS table_name,
                   n_live_tup AS row_count,
                   pg_total_relation_size(relid) / 1024.0 / 1024.0 AS size_mb
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(relid) DESC
            LIMIT 15
        """)
        ).fetchall()
        result["top_tables"] = [
            {"table": r.table_name, "rows": r.row_count, "size_mb": round(r.size_mb, 1)}
            for r in rows
        ]
    except Exception:
        result["top_tables"] = []
    return result


async def _get_redis_metrics() -> dict:
    """Get Redis memory, client count, key count, and queue depths."""
    result: dict = {}
    try:
        async with get_async_redis(socket_timeout=2.0) as r:
            try:
                info = await r.info("memory")
                result["used_memory_mb"] = round(info.get("used_memory", 0) / 1024 / 1024, 1)
                result["used_memory_peak_mb"] = round(
                    info.get("used_memory_peak", 0) / 1024 / 1024, 1
                )
            except Exception:
                pass
            try:
                clients = await r.info("clients")
                result["connected_clients"] = clients.get("connected_clients", 0)
            except Exception:
                pass
            try:
                result["total_keys"] = await r.dbsize()
            except Exception:
                pass

            # Queue depths
            queue_depths = {}
            for queue_name in [
                "audit_jobs:fast",
                "audit_jobs:smart",
                "audit_jobs:deep",
                "audit_jobs",
                "pdf_jobs",
                "billing:webhook_events",
                "visibility_index_jobs",
            ]:
                try:
                    queue_depths[queue_name] = await r.llen(queue_name)
                except Exception:
                    queue_depths[queue_name] = 0
            result["queue_depths"] = queue_depths

            # Worker heartbeats
            workers = []
            try:
                heartbeats = await r.hgetall("worker:heartbeats")
                for name, data_str in heartbeats.items():
                    try:
                        info = json.loads(data_str)
                        last_seen = datetime.fromisoformat(info.get("last_seen", ""))
                        age_seconds = (
                            datetime.now(timezone.utc) - last_seen.replace(tzinfo=timezone.utc)
                        ).total_seconds()
                        workers.append(
                            {
                                "name": name,
                                "status": "alive" if age_seconds < 120 else "dead",
                                "last_seen": info.get("last_seen"),
                                "pid": info.get("pid"),
                                "jobs_processed": info.get("jobs_processed", 0),
                                "last_error": info.get("last_error"),
                                "age_seconds": round(age_seconds, 0),
                            }
                        )
                    except Exception:
                        workers.append({"name": name, "status": "unknown", "last_seen": None})
            except Exception:
                pass
            result["workers"] = workers
    except Exception:
        pass
    return result


def _get_request_stats() -> dict:
    """Parse live Prometheus counter values for request stats."""
    result: dict = {"total_requests": 0, "by_status": {}, "error_rate_percent": 0.0}
    try:
        from prometheus_client import REGISTRY

        requests: dict[str, float] = {}
        for metric in REGISTRY.collect():
            if metric.name == "http_requests_total":
                for sample in metric.samples:
                    if sample.name == "http_requests_total_total":
                        status_class = sample.labels.get("status_class", "unknown")
                        requests[status_class] = requests.get(status_class, 0) + sample.value
        total = sum(requests.values())
        error_count = requests.get("5xx", 0) + requests.get("4xx", 0)
        result["total_requests"] = int(total)
        result["by_status"] = {k: int(v) for k, v in requests.items()}
        result["error_rate_percent"] = round((error_count / max(total, 1)) * 100, 2)
    except Exception:
        pass
    return result


@router.get("/infrastructure/metrics")
async def admin_infrastructure_metrics(
    _: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Comprehensive infrastructure health snapshot."""
    process_metrics = _get_process_metrics()
    db_metrics = _get_db_pool_metrics(db)
    redis_metrics = await _get_redis_metrics()
    request_stats = _get_request_stats()

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "process": process_metrics,
        "database": db_metrics,
        "redis": redis_metrics,
        "request_stats": request_stats,
    }


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-15, Runtime Configuration Console
# ──────────────────────────────────────────────────────────────────────


@router.get("/config")
def admin_config_list(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Full config view, all settings with current value, source, editable flag."""
    from core.config import settings as app_settings
    from core.runtime_config import (
        RUNTIME_CONFIGURABLE_KEYS,
        get_runtime_overrides,
        is_sensitive_key,
        mask_value,
    )

    overrides = get_runtime_overrides(db)
    all_fields = app_settings.model_fields

    items = []
    categories: set[str] = set()

    for key, field_info in sorted(all_fields.items()):
        meta = RUNTIME_CONFIGURABLE_KEYS.get(key)
        editable = meta is not None
        default_value = field_info.default
        env_value = os.getenv(key)
        runtime_value = overrides.get(key)
        sensitive = is_sensitive_key(key)

        # Determine source
        if runtime_value is not None:
            current_value = runtime_value
            source = "runtime"
        elif env_value is not None:
            current_value = env_value
            source = "env"
        else:
            current_value = default_value
            source = "default"

        category = meta["category"] if meta else _infer_category(key)
        categories.add(category)

        entry: dict = {
            "key": key,
            "current_value": mask_value(current_value) if sensitive else current_value,
            "source": source,
            "editable": editable,
            "category": category,
            "is_secret": sensitive,
        }

        if editable and meta:
            entry["type"] = meta.get("type", "str")
            entry["description"] = meta.get("description", "")
            if "min" in meta:
                entry["min"] = meta["min"]
            if "max" in meta:
                entry["max"] = meta["max"]
            if "options" in meta:
                entry["options"] = meta["options"]
            entry["default_value"] = default_value
            entry["env_value"] = mask_value(env_value) if sensitive else env_value
            entry["runtime_value"] = runtime_value

        items.append(entry)

    return {
        "settings": items,
        "categories": sorted(categories),
        "total_settings": len(items),
        "runtime_overrides": len(overrides),
    }


def _infer_category(key: str) -> str:
    """Infer a category from the key name for non-editable settings."""
    upper = key.upper()
    if any(p in upper for p in ("STRIPE", "BILLING", "PRICE")):
        return "Billing"
    if any(p in upper for p in ("MAIL", "EMAIL", "SMTP")):
        return "Email"
    if any(
        p in upper
        for p in ("GEMINI", "GOOGLE_FAST", "GOOGLE_SMART", "OPENAI", "ANTHROPIC", "CMS_GEMINI")
    ):
        return "AI Models"
    if any(
        p in upper
        for p in ("JWT", "TOKEN", "SESSION", "AUTH", "MFA", "OAUTH", "PASSWORD", "LOGIN", "RATE")
    ):
        return "Auth"
    if any(p in upper for p in ("DATABASE", "REDIS", "DB_")):
        return "Infrastructure"
    if any(p in upper for p in ("SENTRY", "TRACING", "LOG_")):
        return "Observability"
    if any(p in upper for p in ("AUDIT", "QUEUE", "WORKER", "JOB", "GUEST")):
        return "Workers"
    if any(p in upper for p in ("GOOGLE_CLIENT", "GITHUB", "LINKEDIN", "JIRA", "BING")):
        return "OAuth Providers"
    if any(
        p in upper
        for p in ("FIRECRAWL", "PAGESPEED", "SEARCH", "SERPAPI", "DATAFORSEO", "PLACES", "MAPS")
    ):
        return "External APIs"
    if any(p in upper for p in ("DOMAIN", "URL", "CORS", "HOST", "WEBAUTHN", "CLOUDFLARE")):
        return "Infrastructure"
    return "General"


@router.get("/config/editable")
def admin_config_editable(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Only runtime-configurable settings with their metadata."""
    from core.config import settings as app_settings
    from core.runtime_config import RUNTIME_CONFIGURABLE_KEYS, get_runtime_overrides

    overrides = get_runtime_overrides(db)
    items = []

    for key, meta in sorted(RUNTIME_CONFIGURABLE_KEYS.items()):
        default_value = getattr(app_settings, key, None)
        env_value = os.getenv(key)
        runtime_value = overrides.get(key)

        if runtime_value is not None:
            current_value = runtime_value
            source = "runtime"
        elif env_value is not None:
            current_value = env_value
            source = "env"
        else:
            current_value = default_value
            source = "default"

        items.append(
            {
                "key": key,
                "current_value": current_value,
                "source": source,
                "default_value": default_value,
                "env_value": env_value,
                "runtime_value": runtime_value,
                "type": meta.get("type", "str"),
                "category": meta.get("category", "General"),
                "description": meta.get("description", ""),
                "min": meta.get("min"),
                "max": meta.get("max"),
                "options": meta.get("options"),
            }
        )

    return {"settings": items, "total": len(items), "overrides": len(overrides)}


class ConfigUpdateRequest(BaseModel):
    updates: dict[str, object] = Field(
        ..., description="Key-value pairs to set as runtime overrides"
    )


@router.patch("/config")
def admin_config_update(
    body: ConfigUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Update one or more runtime config overrides."""
    from core.runtime_config import (
        RUNTIME_CONFIGURABLE_KEYS,
        coerce_value,
        invalidate_cache,
        validate_config_value,
    )

    errors = []
    applied = {}

    for key, value in body.updates.items():
        if key not in RUNTIME_CONFIGURABLE_KEYS:
            errors.append(f"'{key}' is not runtime-configurable.")
            continue
        ok, msg = validate_config_value(key, value)
        if not ok:
            errors.append(msg)
            continue
        applied[key] = coerce_value(key, value)

    if errors:
        raise HTTPException(status_code=422, detail="; ".join(errors))

    settings = get_or_create_operational_settings(db)
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )
    runtime = payload.get("runtime_config", {})
    old_values = {k: runtime.get(k) for k in applied}
    runtime.update(applied)
    payload["runtime_config"] = runtime
    settings.admin_settings_payload = payload
    db.commit()
    invalidate_cache()

    _log_admin_action(
        db,
        admin_user,
        "config_update",
        "config",
        None,
        {"updated": {k: {"old": old_values.get(k), "new": v} for k, v in applied.items()}},
    )

    return {"applied": applied, "total_overrides": len(runtime)}


@router.delete("/config/{key}")
def admin_config_reset(
    key: str,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Remove a runtime override, revert to env/default."""
    from core.runtime_config import RUNTIME_CONFIGURABLE_KEYS, invalidate_cache

    if key not in RUNTIME_CONFIGURABLE_KEYS:
        raise HTTPException(status_code=404, detail=f"'{key}' is not runtime-configurable.")

    settings = get_or_create_operational_settings(db)
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )
    runtime = payload.get("runtime_config", {})
    old_value = runtime.pop(key, None)
    payload["runtime_config"] = runtime
    settings.admin_settings_payload = payload
    db.commit()
    invalidate_cache()

    if old_value is not None:
        _log_admin_action(
            db,
            admin_user,
            "config_reset",
            "config",
            None,
            {"key": key, "old_value": old_value},
        )

    return {"key": key, "removed": old_value is not None, "total_overrides": len(runtime)}


# ──────────────────────────────────────────────────────────────────────
#  TASK_ADMIN-13, Maintenance Mode & Feature Kill Switches
# ──────────────────────────────────────────────────────────────────────


DEFAULT_FEATURE_SWITCHES = {
    "audits_enabled": True,
    "pdf_generation_enabled": True,
    "email_sending_enabled": True,
    "billing_enabled": True,
    "cms_generation_enabled": True,
    "signups_enabled": True,
    "oauth_enabled": True,
    "scheduled_audits_enabled": True,
    "competitor_analysis_enabled": True,
}


@router.get("/maintenance")
def admin_maintenance_status(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Current maintenance mode + feature switch state."""
    settings = get_or_create_operational_settings(db)
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )

    feature_switches_raw = payload.get("feature_switches", {})

    # Merge defaults with stored values
    merged_switches = {**DEFAULT_FEATURE_SWITCHES, **feature_switches_raw}

    # The banner-facing subset is built by the shared helper so the admin view
    # and the authenticated notice endpoint can never drift apart.
    notice = build_maintenance_notice(settings)

    return {
        "maintenance": {
            "enabled": bool(settings.maintenance_mode),
            "message": notice["message"],
            "allowed_emails": settings.maintenance_allowed_ips or [],
            "scheduled_start": notice["scheduled_start"],
            "scheduled_end": settings.maintenance_scheduled_end.isoformat()
            if settings.maintenance_scheduled_end
            else None,
        },
        "feature_switches": merged_switches,
    }


class MaintenanceToggleRequest(BaseModel):
    enabled: bool
    message: str = ""
    allowed_emails: list[str] = Field(default_factory=list)


@router.post("/maintenance/toggle")
def admin_maintenance_toggle(
    body: MaintenanceToggleRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Toggle maintenance mode on/off with optional message and IP allowlist."""
    from middleware.maintenance import MAINTENANCE_CACHE_KEY

    settings = get_or_create_operational_settings(db)

    old_state = settings.maintenance_mode

    settings.maintenance_mode = body.enabled
    settings.maintenance_message = body.message.strip()
    # Store allowed_emails in the maintenance_allowed_ips column
    settings.maintenance_allowed_ips = [e.strip().lower() for e in body.allowed_emails if e.strip()]

    # Also update the legacy JSON payload for backwards compatibility in case other tools use it
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )
    payload["maintenance"] = {
        "enabled": body.enabled,
        "message": body.message.strip(),
        "allowed_emails": settings.maintenance_allowed_ips,
    }
    settings.admin_settings_payload = payload

    # Invalidate Redis cache
    redis_client = _get_redis()
    if redis_client:
        try:
            redis_client.delete(MAINTENANCE_CACHE_KEY)
        except Exception:
            pass

    db.commit()

    _log_admin_action(
        db,
        admin_user,
        "maintenance_toggle",
        "maintenance",
        None,
        {"old_enabled": old_state, "new_enabled": body.enabled, "message": body.message.strip()},
    )

    return {"enabled": body.enabled, "message": body.message.strip()}


from typing import Optional
from datetime import datetime


class MaintenanceScheduleRequest(BaseModel):
    scheduled_start: Optional[datetime]
    scheduled_end: Optional[datetime]
    message: str = ""
    allowed_ips: list[str] = Field(default_factory=list)


@router.post("/maintenance/schedule")
def admin_maintenance_schedule(
    body: MaintenanceScheduleRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Schedule future maintenance windows."""
    from middleware.maintenance import MAINTENANCE_CACHE_KEY

    settings = get_or_create_operational_settings(db)

    settings.maintenance_scheduled_start = body.scheduled_start
    settings.maintenance_scheduled_end = body.scheduled_end
    if body.message:
        settings.maintenance_message = body.message.strip()
    if body.allowed_ips:
        settings.maintenance_allowed_ips = [ip.strip() for ip in body.allowed_ips if ip.strip()]

    db.commit()

    # Invalidate Redis cache
    redis_client = _get_redis()
    if redis_client:
        try:
            redis_client.delete(MAINTENANCE_CACHE_KEY)
        except Exception:
            pass

    _log_admin_action(
        db,
        admin_user,
        "maintenance_schedule",
        "maintenance",
        None,
        {"scheduled_start": str(body.scheduled_start), "scheduled_end": str(body.scheduled_end)},
    )
    return {"status": "Scheduled successfully"}


class FeatureSwitchUpdateRequest(BaseModel):
    switches: dict[str, bool] = Field(..., description="Feature key → enabled/disabled")


@router.patch("/feature-switches")
def admin_feature_switch_update(
    body: FeatureSwitchUpdateRequest,
    admin_user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Toggle one or more feature kill switches."""
    # Validate keys
    invalid_keys = [k for k in body.switches if k not in DEFAULT_FEATURE_SWITCHES]
    if invalid_keys:
        raise HTTPException(
            status_code=422, detail=f"Unknown feature switches: {', '.join(invalid_keys)}"
        )

    settings = get_or_create_operational_settings(db)
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )

    current_switches = payload.get("feature_switches", {})
    old_values = {
        k: current_switches.get(k, DEFAULT_FEATURE_SWITCHES.get(k, True)) for k in body.switches
    }

    current_switches.update(body.switches)
    payload["feature_switches"] = current_switches
    settings.admin_settings_payload = payload
    db.commit()

    _log_admin_action(
        db,
        admin_user,
        "feature_switch_update",
        "feature_switches",
        None,
        {"changes": {k: {"old": old_values[k], "new": v} for k, v in body.switches.items()}},
    )

    merged = {**DEFAULT_FEATURE_SWITCHES, **current_switches}
    return {"feature_switches": merged}


# ---------------------------------------------------------------------------
# Email Template Preview & Test Send  (TASK_ADMIN-10)
# ---------------------------------------------------------------------------


@router.get("/email-templates")
def admin_list_email_templates(
    _: Annotated[models.User, Depends(get_current_staff_user)],
):
    """List all registered email template definitions."""
    templates = []
    for key, defn in TEMPLATE_DEFINITIONS.items():
        subject_display = defn.subject if isinstance(defn.subject, str) else "(dynamic)"
        templates.append(
            {
                "key": key,
                "subject": subject_display,
                "html_template": defn.html_template,
                "category": defn.category,
            }
        )
    categories = sorted({d.category for d in TEMPLATE_DEFINITIONS.values()})
    return {"templates": templates, "categories": categories, "total": len(templates)}


@router.get("/email-templates/default-context")
def admin_email_template_default_context(
    _: Annotated[models.User, Depends(get_current_staff_user)],
):
    """Return the default preview context dictionary."""
    return {"context": DEFAULT_PREVIEW_CONTEXT}


class EmailTemplatePreviewRequest(BaseModel):
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/email-templates/{template_key:path}/preview")
def admin_preview_email_template(
    template_key: str,
    body: EmailTemplatePreviewRequest,
    _: Annotated[models.User, Depends(get_current_staff_user)],
):
    """Render an email template with the provided (or default) context."""
    if template_key not in TEMPLATE_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown template key: {template_key}")

    merged_context = {**DEFAULT_PREVIEW_CONTEXT, **body.context}
    try:
        rendered = render_email_template(template_key, merged_context)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Template render error: {exc}")

    defn = TEMPLATE_DEFINITIONS[template_key]
    return {
        "key": template_key,
        "subject": rendered.subject,
        "html": rendered.html,
        "text": rendered.text,
        "category": rendered.category,
        "html_template": defn.html_template,
    }


class EmailTemplateTestSendRequest(BaseModel):
    to_email: str = Field(..., description="Recipient email address")
    context: dict[str, Any] = Field(default_factory=dict)


@router.post("/email-templates/{template_key:path}/test-send")
def admin_test_send_email_template(
    template_key: str,
    body: EmailTemplateTestSendRequest,
    admin_user: Annotated[models.User, Depends(get_current_staff_user)],
    db: Session = Depends(get_db),
):
    """Render a template and queue a test send via the EmailOutbox."""
    if template_key not in TEMPLATE_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown template key: {template_key}")

    to_email = body.to_email.strip().lower()
    if not to_email or "@" not in to_email:
        raise HTTPException(status_code=422, detail="Invalid email address")

    merged_context = {**DEFAULT_PREVIEW_CONTEXT, **body.context}
    try:
        rendered = render_email_template(template_key, merged_context)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Template render error: {exc}")

    test_subject = f"[TEST] {rendered.subject}"

    outbox_entry = models.EmailOutbox(
        user_id=admin_user.id,
        to_email=to_email,
        subject=test_subject,
        html_body=rendered.html,
        text_body=rendered.text,
        category=rendered.category,
        template_key=template_key,
        correlation_id=f"admin-test-{uuid4().hex[:12]}",
        status="pending",
    )
    db.add(outbox_entry)
    db.commit()
    db.refresh(outbox_entry)

    _log_admin_action(
        db,
        admin_user,
        "email_test_send",
        "email_template",
        template_key,
        {"to_email": to_email, "outbox_id": outbox_entry.id},
    )
    db.commit()

    return {
        "status": "queued",
        "outbox_id": outbox_entry.id,
        "to_email": to_email,
        "subject": test_subject,
    }


# ── Claim Feedback Analytics (AEX-26) ──────────────────────────────


@router.get("/claim-feedback/analytics")
def admin_claim_feedback_analytics(
    days: int = 30,
    admin_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return aggregated claim feedback analytics for admin dashboard."""
    from services.claim_feedback_service import get_feedback_analytics

    return get_feedback_analytics(db, days=days)
