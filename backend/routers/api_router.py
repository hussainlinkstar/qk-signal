import asyncio
import concurrent.futures
import hashlib
import json
import logging
import os
import re
import ssl
import threading
import uuid
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Any, Literal, Mapping, Sequence
from urllib.parse import quote, urlparse

import httpx
import stripe
import jwt
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from jwt import PyJWTError
from pydantic import BaseModel, EmailStr, Field, HttpUrl, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session
from core.password_hashing import hash_password, verify_password

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BACKEND_DIR / ".env")
load_dotenv(dotenv_path=BACKEND_DIR.parent / ".env", override=True)

import models
from database import SessionLocal, get_db
from audit_runner import canonical_score_breakdown, perform_audit
from cache_utils import build_audit_cache_key
from core.client_ip import resolve_client_ip
from core.config import settings
from core.redis_client import get_async_redis
from middleware.session_checker import deactivate_user_sessions, revoke_session_jtis
from schemas.auth import normalize_company_name
from score_utils import extract_score
from app.services.advisor_view import attach_advisor_view
from app.services.aio_view import attach_aio_view
from app.services.billing_retention import (
    RetainedInvoices,
    anonymize_billing_payments_for_user,
    effective_retention_until,
    record_account_deletion_receipt,
)
from app.services.learnings_service import dismissed_fingerprints
from app.services.search_types_view import attach_search_types
from services import advisor_chat_service, advisor_chat_history_service
from services import audit_share_token_service as audit_share_tokens
from services.project_visibility_service import compute_search_type_measurements
from services.scraper import ScraperService
from services.ai_client import AIClient
from services.ai_engine import AIFactory
from services.performance import PerformanceService
from services.performance_snapshots import PerformanceSnapshotService
from services.network_analyzer import NetworkAnalysisService
from services.geo_visibility_service import GeoVisibilityService, ProviderTimeoutError
from services.guest_audit_service import run_guest_audit
from services.aeo_answerability_service import AEOAnswerabilityService
from services.audit_normalization_service import (
    build_normalized_audit_report,
    normalize_audit_target_type,
    resolve_audit_normalization_current_plan,
    resolve_audit_effective_scores,
    resolve_audit_intent as resolve_audit_intent_contract,
    resolve_audit_query_category as resolve_audit_query_category_contract,
    resolve_audit_target_metadata as resolve_audit_target_metadata_contract,
    resolve_audit_target_name as resolve_audit_target_name_contract,
    resolve_audit_target_type as resolve_audit_target_type_contract,
    resolve_audit_target_url as resolve_audit_target_url_contract,
    resolve_legacy_audit_url as resolve_legacy_audit_url_contract,
)
from services.portal_service import resolve_workspace_owner_plan
from services.s3_storage_service import get_storage_service, resolve_report_retention_days
from services.entity_extraction import extract_entity_candidates_from_url
from services.entity_service import EntityService
from services.entity_graph_service import EntityGraphService
from services.hallucination_service import HallucinationService
from services.competitors.benchmark_service import CompetitorBenchmarkService
from services.competitors.provider_adapters import build_competitor_discovery_service
from services.predictive_intent_service import PredictiveIntentService
from services.query_taxonomy import (
    classify_query_category,
    normalize_intent_value,
    resolve_query_type,
)
from services.jira_service import jira_service
from services.pdf_report_renderer import (
    BrandingConfig,
    render_battle_report_pdf,
    render_white_label_pdf,
)
from services.pdf_reports import (
    normalize_branding_mode,
    normalize_competitor_mode,
    normalize_report_kind,
    resolve_export_manifest,
    resolve_report_kind,
)
from services.pdf_reports.battle_seed import build_canonical_competitor_battle_pair
from services.external_api_service import build_idempotency_fingerprint
from services.report_export_policy import first_unmet_report_export_requirement
from services.report_library import (
    resolve_report_kind_from_manifest,
    resolve_report_link_expiry,
    resolve_report_name,
    resolve_stored_report_name,
)
from services.report_export_variants import resolve_export_variant_entitlements
from services.pdf_reports.report_suite_service import (
    build_report_branding_config,
    build_report_summary_text as build_report_summary_text_service,
    render_report_pdf as render_report_pdf_service,
)
from services.report_i18n_service import (
    get_report_label,
    normalize_report_language,
)
from core.tier_labels import get_tier_display
from services.tier_duration_stats_service import (
    MIN_SAMPLE_SIZE as TIER_DURATION_MIN_SAMPLE_SIZE,
    STATISTIC_ID as TIER_DURATION_STATISTIC_ID,
    WINDOW_DAYS as TIER_DURATION_WINDOW_DAYS,
    describe_published_tier_durations,
    get_published_tier_durations,
)
from services.ai_routing_policy import (
    is_valid_audit_tier,
    normalize_audit_tier,
    resolve_audit_route,
    resolve_site_classify_route,
)
from services.pricing_policy_service import get_pricing_policy
from services.custom_domain_service import (
    resolve_workspace_branding,
    resolve_workspace_for_tenant_context,
)
from services.audit_credit_reconciliation_service import (
    resolve_audit_credit_resolution,
    resolve_shadow_audit_credit_cost,
)
from services.audit_job_event_service import (
    build_audit_job_events_key,
    encode_sse_event,
    project_audit_stage_states,
)
from services.credit_hold_service import (
    acquire_credit_hold,
    release_credit_hold,
    settle_credit_hold,
)
from services.cost_forecast_service import (
    calculate_actual_audit_cost,
)
from services.project_audit_scope import (
    declare_audit_project_scope,
    sanitize_client_request_id,
)
from services.project_competitive_service import list_project_competitors
from services.project_task_service import sync_project_tasks
from services.debate_trace_service import debate_trace_service
from services.ai_search_volatility_service import AISearchVolatilityService
from services.audit_helpers import (
    competitor_lite_audit_is_denied,
    resolve_subscription_plan,
    build_audit_cost_forecast as _build_audit_cost_forecast,
    queue_project_budget_notifications as _queue_project_budget_notifications,
)
from services.url_validation import (
    async_request_with_validation,
    normalize_and_validate_url,
    validate_target_host,
)
from services.semantic_cache_service import semantic_cache_service
from services.support_chat_service import generate_support_chat_reply
from services.strategic_insights_service import StrategicInsightsService
from job_models import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    AuditJobPayload,
    PDFJobPayload,
)
from job_models import JobStatus
from observability import audit_db_retries_total, render_metrics
from operational_settings import (
    get_credit_engine_policy_version,
    get_report_retention_days,
    is_ai_service_enabled,
    resolve_shadow_pricing_policy_version,
)
from services.ai_economics_ledger_service import record_ai_economics_ledger_entry
from billing import load_billing_config
from billing.stripe_event_service import (
    normalize_stripe_event_receipt,
    should_wake_event,
)
from auth.credits import (
    AUDIT_RECORD_STATUS_DEGRADED,
    AUDIT_RECORD_STATUS_FAILED,
    decrement_credits_atomic,
    has_active_subscription,
    increment_credits_atomic,
    is_billable_audit_outcome,
    is_retryable_integrity_error,
    should_decrement_credits,
)
from auth.mfa import (
    MFA_ISSUER,
    MFAVerificationResult,
    build_totp_uri,
    generate_totp_secret,
    mfa_throttle_retry_after,
    normalize_otp_code,
    verify_totp_code_for_user,
)
from auth.security import get_current_user_from_token as get_current_user
from services.reports.audit_result_adapter import to_canonical_audit_result
from services.site_entity_facts import SiteEntityFactService
from app.i18n import translate_backend_message
from app.config.plans import (
    PLAN_PRESENTATION,
    PUBLIC_PLAN_TYPES,
    can_use_feature,
    customer_facing_monthly_price_usd,
    get_plan_capabilities,
    is_custom_priced,
)
from app.services.compliance.plan_validator import PlanValidator
from app.services.geo.benchmark_service import GeoBenchmarkService
from app.schemas.jira_schema import JiraExportResponse
from services.workspace_rbac import (
    require_not_portal_only,
    require_workspace_write_access,
    resolve_project_access as resolve_project_access_service,
)
from app.schemas.competitor_schema import (
    CompetitorBenchmarkRequest,
    CompetitorBenchmarkResponse,
    CompetitorCompareResponse,
    CompetitorDiscoveryRequest,
    CompetitorDiscoveryResponse,
    CompetitorSemanticGapResponse,
)

logger = logging.getLogger(__name__)

INVALID_URL_FORMAT_KEY = "errors.invalid_url_format"
INVALID_URL_FORMAT_DETAIL = "Invalid URL format. URL must start with http:// or https://."

router = APIRouter()

STRIPE_WEBHOOK_QUEUE_NAME = os.getenv("STRIPE_WEBHOOK_QUEUE_NAME", "billing:webhook_events")
STRIPE_WEBHOOK_MAX_BODY_BYTES = 256 * 1024
STRIPE_WEBHOOK_WAKE_MARKER_TTL_SECONDS = 30
REPORT_EXPORT_DIR = Path(os.getenv("REPORT_EXPORT_DIR", BACKEND_DIR / "generated_reports"))
JWT_SECRET_KEY = settings.JWT_SECRET_KEY
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
MFA_SETUP_TOKEN_EXPIRE_SECONDS = int(os.getenv("MFA_SETUP_TOKEN_EXPIRE_SECONDS", "600"))


DB_COMMIT_MAX_RETRIES = int(os.getenv("DB_COMMIT_MAX_RETRIES", "3"))
AUDIT_RECORD_STATUS_COMPLETED = "completed"
# Result constants moved to auth.credits
AUDIT_RECORD_STATUSES = {
    AUDIT_RECORD_STATUS_COMPLETED,
    AUDIT_RECORD_STATUS_DEGRADED,
    AUDIT_RECORD_STATUS_FAILED,
}


def _normalize_intent_value(intent: str | None) -> str | None:
    return normalize_intent_value(intent)


def _resolve_audit_intent(audit: models.Audit) -> str | None:
    return resolve_audit_intent_contract(audit)


def _resolve_audit_query_category(audit: models.Audit) -> str:
    return resolve_audit_query_category_contract(audit)


async def _read_stripe_webhook_body(request: Request) -> bytes:
    content_length = request.headers.get("Content-Length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.") from exc
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length header.")
        if declared_length > STRIPE_WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Stripe webhook payload is too large.")

    payload = bytearray()
    async for chunk in request.stream():
        if not isinstance(chunk, bytes):
            raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload.")
        if len(payload) + len(chunk) > STRIPE_WEBHOOK_MAX_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Stripe webhook payload is too large.")
        payload.extend(chunk)
    return bytes(payload)


@router.post("/api/v1/webhooks/stripe")
async def stripe_webhook(request: Request):
    db = SessionLocal()
    try:
        config = load_billing_config(db=db)
    finally:
        db.close()
    mode_secrets = [
        (mode, mode_config.webhook_secret)
        for mode, mode_config in config.mode_configs.items()
        if mode in {"test", "live"} and mode_config.webhook_secret
    ]
    if not mode_secrets:
        logger.error("Stripe webhook secret is not configured.")
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.stripe_webhook_config_missing",
                "Stripe webhook configuration is missing.",
                request=request,
            ),
        )

    sig_header = request.headers.get("Stripe-Signature")
    if not sig_header:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.stripe_signature_header_missing",
                "Missing Stripe-Signature header.",
                request=request,
            ),
        )

    payload = await _read_stripe_webhook_body(request)
    verified_matches: list[tuple[str, object]] = []
    for candidate_mode, webhook_secret in mode_secrets:
        try:
            candidate_event = await asyncio.to_thread(
                stripe.Webhook.construct_event,
                payload,
                sig_header,
                webhook_secret,
            )
        except (ValueError, stripe.error.SignatureVerificationError):
            continue
        candidate_livemode = candidate_event.get("livemode")
        if candidate_livemode is (candidate_mode == "live"):
            verified_matches.append((candidate_mode, candidate_event))
    if len(verified_matches) != 1:
        logger.warning("Stripe webhook verification failed")
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.invalid_stripe_signature",
                "Invalid Stripe webhook signature.",
                request=request,
            ),
        )
    verified_mode, event = verified_matches[0]

    try:
        event_payload = normalize_stripe_event_receipt(
            event.to_dict(),
            stripe_mode=verified_mode,
        )
    except ValueError:
        logger.warning("Stripe webhook receipt validation failed")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook payload.")
    event_id = str(event_payload["id"])
    event_type = str(event_payload["type"])
    event_created = int(event_payload["created"])
    event_created_at = datetime.fromtimestamp(event_created, tz=timezone.utc)
    logger.info("Stripe webhook received: event_id=%s event_type=%s", event_id, event_type)

    should_enqueue = await asyncio.to_thread(
        _persist_stripe_webhook_event,
        event_id,
        event_type,
        event_created_at,
        event_payload,
    )

    if should_enqueue:
        await _enqueue_stripe_event_wakeup(event_id)

    return {"received": True}


async def _enqueue_stripe_event_wakeup(event_id: str) -> None:
    try:
        async with get_async_redis() as redis_client:
            marker_key = f"billing:webhook_wakeup:{event_id}"
            acquired = await redis_client.set(
                marker_key,
                "1",
                nx=True,
                ex=STRIPE_WEBHOOK_WAKE_MARKER_TTL_SECONDS,
            )
            if acquired:
                await redis_client.rpush(STRIPE_WEBHOOK_QUEUE_NAME, event_id)
    except Exception as exc:
        logger.warning(
            "Stripe event persisted but Redis wakeup failed: event_id=%s error_class=%s",
            event_id,
            type(exc).__name__,
        )


def _persist_stripe_webhook_event(
    event_id: str,
    event_type: str,
    event_created_at: datetime,
    event_payload: dict,
) -> bool:
    db = SessionLocal()
    try:
        existing = db.execute(
            select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
        ).scalar_one_or_none()
        if existing is not None:
            logger.info("Stripe webhook already logged: event_id=%s", event_id)
            return should_wake_event(existing)

        db.add(
            models.StripeEventLog(
                event_id=event_id,
                event_type=event_type,
                event_created_at=event_created_at,
                payload=event_payload,
                processing_status="pending",
            )
        )
        try:
            db.commit()
            return True
        except IntegrityError:
            db.rollback()
            logger.info("Stripe webhook insert skipped due to duplicate: event_id=%s", event_id)
            existing = db.execute(
                select(models.StripeEventLog).where(models.StripeEventLog.event_id == event_id)
            ).scalar_one_or_none()
            return existing is not None and should_wake_event(existing)
    finally:
        db.close()


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = render_metrics()
    return Response(content=payload, media_type=content_type)


class URLValidatedRequest(BaseModel):
    url: HttpUrl

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: str | HttpUrl) -> str:
        try:
            return normalize_and_validate_url(str(value))
        except ValueError as exc:
            raise ValueError(INVALID_URL_FORMAT_DETAIL) from exc


class AuditTargetValidatedRequest(BaseModel):
    audit_target_type: Literal["website", "brand"] = "website"
    url: HttpUrl | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=256)
    target_url: HttpUrl | None = None
    target_metadata: dict[str, Any] | None = None

    @field_validator("audit_target_type", mode="before")
    @classmethod
    def validate_target_type(cls, value: str) -> str:
        normalized = str(value or "website").strip().lower()
        if normalized not in {"website", "brand"}:
            raise ValueError("audit_target_type must be either 'website' or 'brand'.")
        return normalized

    @field_validator("url", "target_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: str | HttpUrl | None) -> str | None:
        if value is None:
            return None
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            return normalize_and_validate_url(raw_value)
        except ValueError as exc:
            raise ValueError(INVALID_URL_FORMAT_DETAIL) from exc

    @field_validator("target_name", mode="before")
    @classmethod
    def normalize_target_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target_contract(self) -> "AuditTargetValidatedRequest":
        if self.target_url is None and self.url is not None:
            self.target_url = self.url

        if self.audit_target_type == "website" and self.target_url is None:
            raise ValueError("Website audits require url or target_url.")

        if self.audit_target_type == "brand" and not self.target_name:
            raise ValueError("Brand audits require target_name.")

        return self

    def resolved_target_url(self) -> str | None:
        if self.target_url is not None:
            return str(self.target_url)
        if self.url is not None:
            return str(self.url)
        return None

    def resolved_target_name(self) -> str | None:
        if self.target_name:
            return str(self.target_name).strip() or None
        return None

    def resolved_target_metadata(self) -> dict[str, Any]:
        return dict(self.target_metadata) if isinstance(self.target_metadata, dict) else {}


class URLPreflightResponse(BaseModel):
    ok: bool
    url: HttpUrl
    status_code: int | None = None
    method: Literal["HEAD", "GET"] | None = None


def _is_ssl_verification_error(exc: httpx.RequestError) -> bool:
    details = str(exc).lower()
    if (
        "certificate verify failed" in details
        or "cert verify failed" in details
        or "self-signed certificate" in details
    ):
        return True

    cause: BaseException | None = exc
    while cause is not None:
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        cause = cause.__cause__
    return False


@router.get("/api/v1/audit/preflight", response_model=URLPreflightResponse, tags=["Audit"])
async def preflight_audit_url(
    url: str = Query(..., description="URL to preflight before submitting an audit."),
):
    try:
        normalized_url = normalize_and_validate_url(url)
        validate_target_host(normalized_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        try:
            head_response, resolved_url = await async_request_with_validation(
                client,
                method="HEAD",
                url=normalized_url,
            )
            if head_response.status_code < 500:
                return URLPreflightResponse(
                    ok=True,
                    url=resolved_url,
                    status_code=head_response.status_code,
                    method="HEAD",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.RequestError:
            # Some hosts reject HEAD probes at the transport layer; continue with GET reachability probe.
            pass

        try:
            get_response, resolved_url = await async_request_with_validation(
                client,
                method="GET",
                url=normalized_url,
                headers={"Range": "bytes=0-512"},
            )
            if get_response.status_code < 500:
                return URLPreflightResponse(
                    ok=True,
                    url=resolved_url,
                    status_code=get_response.status_code,
                    method="GET",
                )
            raise HTTPException(status_code=400, detail="Target URL returned an error response.")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail="Unable to reach the target URL.") from exc


class AIStrategicInsightsRequest(BaseModel):
    audit_id: int = Field(gt=0)
    project_id: int | None = Field(default=None, gt=0)


class AIStrategicInsightsResponse(BaseModel):
    content: str


class JiraProjectExportRequest(BaseModel):
    recommendation_title: str = Field(min_length=1, max_length=255)
    generated_guide_markdown: str = Field(min_length=1, max_length=30000)
    issue_type: str = Field(default="Task", max_length=50)
    project_key: str | None = Field(default=None, max_length=20)


class SupportChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class SupportChatRequest(BaseModel):
    messages: list[SupportChatMessage] = Field(min_length=1, max_length=20)
    locale: str = Field(default="en", max_length=8)

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str) -> str:
        normalized = (value or "en").strip().lower()
        return "ro" if normalized.startswith("ro") else "en"


class SupportChatResponse(BaseModel):
    agent_name: str
    reply: str
    # Must cover every provider the support-chat routing policy can select;
    # "bedrock" is the only reasoning provider under the current cutover.
    source: Literal["openai", "google", "bedrock", "fallback"]
    model: str | None = None
    suggestions: list[str] = Field(default_factory=list)


DEFAULT_AI_PROVIDER = "google"
DEFAULT_AI_TIER = "fast"
audit_consensus_ai_factory = AIFactory()


@router.post("/api/v1/ai/strategic-insights", response_model=AIStrategicInsightsResponse)
async def generate_strategic_insights(
    payload: AIStrategicInsightsRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    grounded_payload = StrategicInsightsService(db).generate_for_audit(
        user=user,
        audit_id=payload.audit_id,
        project_id=payload.project_id,
    )
    return AIStrategicInsightsResponse(content=json.dumps(grounded_payload))


@router.post("/api/v1/projects/{project_id}/export/jira", response_model=JiraExportResponse)
async def export_project_guide_to_jira(
    project_id: int,
    payload: JiraProjectExportRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    project = _resolve_project_for_audit(project_id=project_id, user=user, db=db)

    if not plan_validator.has_feature(user, "can_export_to_jira"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Upgrade to Specialist to export actionable tasks directly to your team's Jira.",
        )

    jira_connection = (
        db.query(models.JiraConnection)
        .filter(models.JiraConnection.workspace_id == project.workspace_id)
        .first()
    )
    if jira_connection is None or not jira_connection.access_token or not jira_connection.cloud_id:
        raise HTTPException(status_code=400, detail="Jira is not connected for this project.")

    browse_base_url = jira_service.normalize_browse_base_url(jira_connection.site_url)
    if browse_base_url is None:
        try:
            server_info = await jira_service.get_server_info(
                jira_connection.cloud_id,
                jira_connection.access_token,
            )
            resolved_site_url = server_info.get("baseUrl")
            normalized_resolved_site_url = jira_service.normalize_browse_base_url(resolved_site_url)
            if normalized_resolved_site_url:
                jira_connection.site_url = normalized_resolved_site_url
                db.commit()
                browse_base_url = normalized_resolved_site_url
        except Exception as exc:
            logger.warning(
                "Unable to refresh Jira browse base URL for workspace %s: %s",
                project.workspace_id,
                exc,
            )

    target_project_key = (
        payload.project_key or jira_connection.default_jira_project_key or ""
    ).strip()
    if not target_project_key:
        try:
            accessible_projects = await jira_service.get_projects(
                jira_connection.cloud_id,
                jira_connection.access_token,
            )
            if accessible_projects:
                target_project_key = accessible_projects[0].key.strip()
                jira_connection.default_jira_project_key = target_project_key
                db.commit()
        except Exception as exc:
            logger.warning(
                "Unable to resolve fallback Jira project for workspace %s: %s",
                project.workspace_id,
                exc,
            )

    if not target_project_key:
        raise HTTPException(
            status_code=400,
            detail="No target Jira project is configured. Connect Jira and initialize or select a Jira project first.",
        )

    try:
        export_result = JiraExportResponse.model_validate(
            await jira_service.create_issue(
                cloud_id=jira_connection.cloud_id,
                access_token=jira_connection.access_token,
                project_key=target_project_key,
                summary=payload.recommendation_title,
                description_md=payload.generated_guide_markdown,
                issue_type=payload.issue_type,
                site_url=browse_base_url,
            )
        )
        db.add(
            models.ProjectJiraExport(
                project_id=project.id,
                created_by_user_id=user.id,
                jira_project_key=target_project_key,
                issue_id=export_result.issue_id,
                issue_key=export_result.issue_key,
                issue_url=export_result.issue_url,
                title=payload.recommendation_title,
                issue_type=payload.issue_type,
                status_name="Exported",
            )
        )
        db.commit()
        return export_result
    except Exception as exc:
        logger.error(
            "Failed to export project %s recommendation to Jira for user %s: %s",
            project.id,
            user.id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to export guide to Jira.") from exc


def _support_quick_suggestions(locale: str) -> list[str]:
    del locale
    return [
        "How do I run my first Smart audit?",
        "What are the plan options and pricing?",
        "How do I enable MFA for my account?",
        "How can I change or cancel my plan?",
    ]


def _is_platform_support_question(user_message: str) -> bool:
    normalized = (user_message or "").strip().lower()
    if not normalized:
        return False

    platform_keywords = [
        "thothgraph",
        "platform",
        "audit",
        "guest",
        "fast",
        "smart",
        "high confidence",
        "geo",
        "aeo",
        "seo",
        "dashboard",
        "account",
        "settings",
        "mfa",
        "otp",
        "subscription",
        "plan",
        "pricing",
        "scans",
        "scan allowance",
        "invoice",
        "billing",
        "stripe",
        "cancel",
        "report",
        "pdf",
        "api",
        "webhook",
        "jira",
        "slack",
        "teams",
        "integration",
        "entity",
        "visibility",
        "portal",
        "project",
        "automation",
        "workflow",
        "schedule",
        "competitor",
        "brand",
        "custom domain",
        "password",
        "login",
        "sign in",
        "sign up",
        "register",
    ]
    return any(keyword in normalized for keyword in platform_keywords)


def _support_plan_summary() -> str:
    """Plan names, prices and scan allowances quoted from the plan catalogue.

    Iterates ``PUBLIC_PLAN_TYPES`` (canonical plans minus ``PRIVATE_PLAN_IDS``),
    so a private plan is structurally absent rather than filtered out by name.
    """
    entries: list[str] = []
    for plan_id in PUBLIC_PLAN_TYPES:
        capabilities = get_plan_capabilities(plan_id)
        name = str(PLAN_PRESENTATION.get(plan_id, {}).get("name") or plan_id)
        customer_price = customer_facing_monthly_price_usd(plan_id)
        scans = capabilities.get("max_audits")
        if not isinstance(scans, (int, float)):
            continue
        scans = int(scans)
        # -1 is the capability matrix's documented "unlimited" value, matching
        # how scan_allowance_service.resolve_scan_limit reads the same field.
        if scans < 0:
            scan_text = "unlimited scans"
        elif scans == 1:
            scan_text = "1 full scan/mo"
        else:
            scan_text = f"up to {scans:,} scans/mo"
        if is_custom_priced(plan_id) or customer_price is None:
            entries.append(f"{name} (custom pricing, {scan_text})")
        elif customer_price > 0:
            entries.append(f"{name} at USD {customer_price}/mo ({scan_text})")
        else:
            entries.append(f"{name} (free, {scan_text})")
    return "; ".join(entries)


#: The names the support surfaces already use for each depth. Deliberately not
#: taken from ``TIER_DISPLAY_LABELS``: the assistant calls ``deep_judgment``
#: "High Confidence", and SIGV2-1177 is not the ticket that renames a tier in
#: front of customers.
_SUPPORT_CHAT_TIER_LABELS: dict[str, str] = {
    "fast": "Fast",
    "smart": "Smart",
    "deep_judgment": "High Confidence",
}


def _resolve_support_chat_durations(db: Session) -> tuple[str | None, str | None]:
    """Render the measured per-depth durations for the two support surfaces.

    Returns ``(prompt_block, inline_fragment)``, either of which is ``None``
    when no depth has enough recorded runs to publish (SIGV2-1177). Best
    effort: a support answer about billing must not fail because an aggregate
    table could not be read, and the correct degraded behaviour is to state no
    duration, which is exactly what ``None`` produces downstream.
    """
    try:
        published = get_published_tier_durations(db)
    except Exception:
        logger.exception("Failed to read the measured tier durations for support chat")
        return None, None
    return (
        describe_published_tier_durations(published, labels=_SUPPORT_CHAT_TIER_LABELS),
        describe_published_tier_durations(published, labels=_SUPPORT_CHAT_TIER_LABELS, inline=True),
    )


def _build_support_chat_fallback_reply(
    user_message: str, locale: str, *, measured_durations: str | None = None
) -> str:
    lowered = user_message.lower()

    if not _is_platform_support_question(lowered):
        return (
            "I can only answer customer questions about Qiko Signal: audits, plans, billing, "
            "account settings, reports, integrations, projects, and MFA. "
            "Please rephrase your question in this product context and I will help."
        )

    if any(token in lowered for token in ["invoice", "billing", "stripe", "payment"]):
        return (
            "Hi, Qiko here. For billing, open Dashboard > Billing "
            "to view invoice records, subscription details, and your scan allowance. "
            "You can manage your plan from there. "
            "All billing is in USD. "
            "If an invoice is missing, share your account email and date range at billing@qiko.ai."
        )

    if any(token in lowered for token in ["mfa", "2fa", "otp", "authenticator"]):
        return (
            "You can enable MFA in Dashboard > Account Settings > Security. "
            "Flow: generate secret, scan QR in your authenticator app (Google Authenticator, Authy, or 1Password), "
            "then confirm the OTP code. "
            "If you lost device access, contact support@qiko.ai for manual recovery."
        )

    if any(token in lowered for token in ["scan", "allowance", "limit"]):
        return (
            "Each plan includes a scan allowance. One accepted scan run counts as one scan at "
            "every tier; a sitemap crawl is the exception and consumes one scan per crawled URL. "
            "Usage is counted over a rolling 30-day window rather than resetting on a billing "
            "date, and the current balance is shown on Dashboard > Billing. "
            "If you need more capacity, change your plan or ask about a commitment agreement."
        )

    if any(token in lowered for token in ["guest", "limit"]):
        guest_limit = os.getenv("GUEST_AUDIT_LIMIT", "1")
        return (
            f"Guest audits are free and rate-limited (default: {guest_limit} per session). "
            "They include a Core Web Vitals snapshot and basic AI recommendations. "
            "For deeper analysis with full AEO/GEO scoring and entity mapping, "
            "sign in and use Smart or High Confidence audits from the dashboard."
        )

    if any(
        token in lowered
        for token in ["plan", "subscription", "cancel", "upgrade", "downgrade", "pricing"]
    ):
        return (
            f"Qiko Signal plans (all USD): {_support_plan_summary()}. "
            "Manage your subscription from Dashboard > Billing. Upgrades take effect immediately. "
            "For cancellation help, contact billing@qiko.ai."
        )

    if any(token in lowered for token in ["api", "webhook", "developer"]):
        return (
            "API access is available on Specialist and above. "
            "Get your API key from Dashboard > Settings or Dashboard > Developer. "
            "Configure webhooks in Dashboard > Developer > Webhooks. "
            "Full API documentation is at Dashboard > Developer > Docs."
        )

    if any(token in lowered for token in ["jira", "slack", "teams", "integration"]):
        return (
            "Qiko Signal integrates with Jira (export recommendations as issues), "
            "Slack and Microsoft Teams (real-time notifications), "
            "Google Search Console, and Bing Webmaster Tools. "
            "Set up integrations from Dashboard > Connections. "
            "Jira, Slack, and Teams require Specialist or above."
        )

    if any(token in lowered for token in ["report", "pdf"]):
        return (
            "Generate PDF reports from any audit result by clicking Export PDF. "
            "Reports include the full SEO/AEO/GEO scorecard, recommendations, and Core Web Vitals. "
            "Multi-language report delivery is configurable per project."
        )

    if "audit" in lowered:
        # SIGV2-1177: the tier list carries no duration of its own. A measured
        # figure is appended only when `measured_durations` was passed in, which
        # happens only when a depth cleared its minimum sample size. With
        # nothing measured this reply names the tiers and claims no timing at
        # all, which is the intended behaviour, not a gap to fill in.
        reply = (
            "Qiko Signal offers four audit tiers: Guest (free), Fast, "
            "Smart (full multi-model analysis), "
            "and High Confidence (adversarial verification). "
            "Run audits from Dashboard > Audit. You can audit a website URL or a brand name (no URL needed)."
        )
        if measured_durations:
            reply += (
                " On recorded durations, " f"{measured_durations} " "A large site takes longer."
            )
        return reply

    return (
        "Hi, I'm Qiko. I can help with audits (Guest/Fast/Smart/High Confidence), plans, billing, "
        "reports, integrations, projects, API, account settings, and MFA. "
        "Tell me your exact issue and I will give you concrete next steps."
    )


_SUPPORT_CHAT_RATE_LIMIT_KEY_PREFIX = "support_chat"


async def enforce_support_chat_rate_limit(
    user: Annotated[models.User, Depends(get_current_user)],
) -> None:
    """Ceilings for the authenticated, LLM-backed support chat endpoint.

    Two limits are checked before the model call:

    * Per-identity, keyed on the authenticated user id. This used to be keyed
      on ``_resolve_client_ip``, an identifier only as trustworthy as ingress:
      if the proxy does not overwrite ``cf-connecting-ip`` / ``x-real-ip`` /
      ``x-forwarded-for``, a caller rotates them and resets their own counter.
      A user id comes out of a signed token instead, so no header can move it,
      and this dependency deliberately takes no ``Request`` at all.
    * A global ceiling keyed on a constant, unchanged, so total invocations per
      window are bounded regardless of how many identities call in. This is the
      limit that actually bounds spend.

    Unlike the shared ``enforce_rate_limit`` helper, which fails open so a
    Redis blip does not take unrelated endpoints down, this route is
    spend-bearing, so it fails closed: when the limiter cannot be evaluated
    the request is refused with 503. Only the operator-controlled
    ENVIRONMENT/APP_ENV gates exempt the limiter; no request header does.
    """
    if os.getenv("ENVIRONMENT", "").lower() in ("local", "development"):
        return

    if os.getenv("APP_ENV", "").lower() in ("local", "development"):
        return

    per_identity_limit, window_seconds = parse_rate_limit_config(
        os.getenv("RATE_LIMIT_SUPPORT_CHAT"),
        default_limit=20,
        default_window_seconds=60,
    )
    global_limit, global_window_seconds = parse_rate_limit_config(
        os.getenv("RATE_LIMIT_SUPPORT_CHAT_GLOBAL"),
        default_limit=200,
        default_window_seconds=60,
    )

    async def _count(key: str, ttl: int) -> int:
        async with get_async_redis() as redis_client:
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, ttl)
            return int(current)

    try:
        per_identity_count = await _count(
            f"ratelimit:{_SUPPORT_CHAT_RATE_LIMIT_KEY_PREFIX}:user:{user.id}",
            window_seconds,
        )
        global_count = await _count(
            f"ratelimit:{_SUPPORT_CHAT_RATE_LIMIT_KEY_PREFIX}:global",
            global_window_seconds,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Support chat rate limiter unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="Service Unavailable: rate limit cannot be evaluated."
        )

    if per_identity_count > per_identity_limit or global_count > global_limit:
        raise HTTPException(status_code=429, detail="Too Many Requests")


# Authenticated on purpose (SIGV2-1148). The reasoning, so it is not re-litigated:
#   * The topic list is customer support, not pre-sales: billing, reports,
#     integrations, projects, API keys, account settings and MFA are all things
#     only a signed-in customer has.
#   * There is no prospect surface behind this route. Its only caller is
#     ThothChatWidget, which no page or layout mounts and which is self-disabled;
#     the actual prospect surface (qiko-website-v2) never references it.
#   * OWASP LLM10, unbounded consumption: an anonymous LLM endpoint is a
#     denial-of-wallet surface whose per-request cost the caller influences, and
#     the control for that is per-identity limiting. Authentication supplies the
#     identity directly, and a user id cannot be rotated like a forwarded IP.
#   * If a prospect assistant is wanted later, build it deliberately on the
#     pattern in routers/guest_audit_public_router.py (explicit limiter, output
#     allowlist, documented contract) rather than inheriting an open legacy route.
# The rate limiter stays as defence in depth, and the prompt keeps its
# PUBLIC_PLAN_TYPES filtering: a customer should not be told about a plan they
# cannot buy either.
@router.post("/api/v1/ai/support-chat", response_model=SupportChatResponse, tags=["AI"])
async def support_chat(
    payload: SupportChatRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    _rate_limit: None = Depends(enforce_support_chat_rate_limit),
):
    trimmed_messages = payload.messages[-12:]
    last_user_message = next(
        (
            message.content.strip()
            for message in reversed(trimmed_messages)
            if message.role == "user" and message.content.strip()
        ),
        "",
    )
    if not last_user_message:
        raise HTTPException(status_code=400, detail="At least one user message is required.")

    suggestions = _support_quick_suggestions(payload.locale)
    if not _is_platform_support_question(last_user_message):
        out_of_scope_reply = _build_support_chat_fallback_reply(last_user_message, payload.locale)
        return SupportChatResponse(
            agent_name="Qiko",
            reply=out_of_scope_reply,
            source="fallback",
            model=None,
            suggestions=suggestions,
        )

    # SIGV2-1177: both the model prompt and the canned fallback get their
    # durations from the measured aggregate, or get none at all. Read once, for
    # both, so the two paths cannot state different figures.
    duration_block, duration_fragment = _resolve_support_chat_durations(db)

    try:
        generation = await generate_support_chat_reply(
            messages=trimmed_messages,
            locale=payload.locale,
            measured_durations=duration_block,
        )
        if generation and generation.reply:
            return SupportChatResponse(
                agent_name="Qiko",
                reply=generation.reply,
                source=generation.source,
                model=generation.model,
                suggestions=suggestions,
            )
    except Exception:
        logger.exception("Support chat generation failed; using fallback response.")

    fallback_reply = _build_support_chat_fallback_reply(
        last_user_message, payload.locale, measured_durations=duration_fragment
    )
    return SupportChatResponse(
        agent_name="Qiko",
        reply=fallback_reply,
        source="fallback",
        model=None,
        suggestions=suggestions,
    )


class AuditRequest(AuditTargetValidatedRequest):
    provider: str | None = None
    tier: str = "fast"
    cache_behavior: Literal["default", "bypass"] = "default"
    project_id: int
    brand_truth_payload: dict | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    entities: list[str] | None = None
    selected_models: list[str] | None = None
    audit_data: dict[str, Any] | None = None
    serp_preview: list[dict[str, Any]] | None = None

    @field_validator("tier", mode="before")
    @classmethod
    def validate_tier(cls, value: str | None) -> str:
        return _normalize_requested_audit_tier(value)

    @field_validator("cache_behavior", mode="before")
    @classmethod
    def validate_cache_behavior(cls, value: str | None) -> str:
        normalized = str(value or "default").strip().lower()
        if normalized not in {"default", "bypass"}:
            raise ValueError("cache_behavior must be either 'default' or 'bypass'.")
        return normalized


class AuditJobRequest(AuditTargetValidatedRequest):
    provider: str | None = None
    tier: str = "fast"
    project_id: int
    request_id: str | None = None
    brand_truth_payload: dict | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    entities: list[str] | None = None
    selected_models: list[str] | None = None
    audit_data: dict[str, Any] | None = None
    serp_preview: list[dict[str, Any]] | None = None

    @field_validator("tier", mode="before")
    @classmethod
    def validate_tier(cls, value: str | None) -> str:
        return _normalize_requested_audit_tier(value)


class AuditJobResponse(BaseModel):
    job_id: str
    status: JobStatus = Field(
        ...,
        description="Official job status values: queued, running, succeeded, failed.",
    )
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_url: str | None = None
    requested_tier: str | None = None
    tier_display: str | None = None
    mode_label: str | None = None
    request_id: str | None = None


class TierDurationFigure(BaseModel):
    """One depth's measured duration range, in whole minutes.

    ``low_minutes`` / ``high_minutes`` are the interquartile range of completed
    runs, rounded outward, so the only true statement about them is "half of
    the sampled runs finished between these two figures". Any copy built from
    them must say that. ``median_minutes`` is included for operators; no
    customer-facing surface states it, because no copy claims a single typical
    figure.
    """

    low_minutes: int = Field(..., description="floor(p25) of completed run durations, in minutes.")
    high_minutes: int = Field(..., description="ceil(p75) of completed run durations, in minutes.")
    median_minutes: int = Field(..., description="Median completed run duration, in minutes.")
    sample_size: int = Field(..., description="Completed runs the figures were derived from.")
    window_days: int = Field(..., description="Rolling window the sample was drawn from.")
    computed_at: datetime


class TierDurationsResponse(BaseModel):
    """Measured scan durations per depth (SIGV2-1177).

    ``tiers`` carries an entry **only** for a depth whose sample cleared the
    minimum size and whose aggregate is fresh. A depth with too little data is
    absent, not zero and not null-filled: a consumer that finds no entry must
    state no duration for that depth rather than substitute anything.
    """

    statistic: str = Field(
        ...,
        description=(
            "Identifies what the pair of figures is, so it cannot be mistaken "
            "for a mean, a min/max or a timeout."
        ),
    )
    min_sample_size: int
    window_days: int
    tiers: dict[str, TierDurationFigure]


class AuditEstimateRequest(BaseModel):
    audit_target_type: Literal["website", "brand"] = "website"
    url: HttpUrl | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=256)
    target_url: HttpUrl | None = None
    target_metadata: dict[str, Any] | None = None
    provider: str | None = None
    tier: str = "fast"
    category: str | None = None
    market: str | None = None
    entities: list[str] | None = None
    selected_models: list[str] | None = None
    audit_data: dict[str, Any] | None = None
    serp_preview: list[dict[str, Any]] | None = None

    @field_validator("audit_target_type", mode="before")
    @classmethod
    def validate_target_type(cls, value: str) -> str:
        normalized = str(value or "website").strip().lower()
        if normalized not in {"website", "brand"}:
            raise ValueError("audit_target_type must be either 'website' or 'brand'.")
        return normalized

    @field_validator("url", "target_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: str | HttpUrl | None) -> str | None:
        if value is None:
            return None
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            return normalize_and_validate_url(raw_value)
        except ValueError as exc:
            raise ValueError(INVALID_URL_FORMAT_DETAIL) from exc

    @field_validator("target_name", mode="before")
    @classmethod
    def normalize_target_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @field_validator("tier", mode="before")
    @classmethod
    def validate_tier(cls, value: str | None) -> str:
        return _normalize_requested_audit_tier(value)

    def resolved_target_url(self) -> str | None:
        if self.target_url is not None:
            return str(self.target_url)
        if self.url is not None:
            return str(self.url)
        return None

    def resolved_target_name(self) -> str | None:
        if self.target_name:
            return str(self.target_name).strip() or None
        return None

    def resolved_target_metadata(self) -> dict[str, Any]:
        return dict(self.target_metadata) if isinstance(self.target_metadata, dict) else {}


class AuditEstimateResponse(BaseModel):
    """Customer-facing launch preview. Scan-framed only: internal credit and
    provider-USD fields were removed under SIGV2-1024."""

    consumes_scan: bool
    has_active_subscription: bool
    scans_used: int
    scans_remaining: int | None = None
    reset_at: str | None = None
    confidence: float
    provider: str
    tier: str
    tier_display: str
    tier_class: str
    execution_tier: str
    mode_label: str


class AuditStageStatus(BaseModel):
    """Public resumable stage progress (SIGV2-1021).

    Statuses are the audited stage state machine: pending, running, completed,
    failed, skipped, degraded, unknown. ``unknown`` means durable stage
    evidence was unavailable (Redis expiry) - never fabricated completion.
    ``attempt`` distinguishes retry attempts; ``reason`` is a short
    machine-readable code. No percent-complete is manufactured.
    """

    id: str
    status: str = Field(
        ...,
        description="Stage states: pending, running, completed, failed, skipped, degraded, unknown.",
    )
    attempt: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    reason: str | None = None


class AuditJobStatusResponse(BaseModel):
    job_id: str
    status: JobStatus = Field(
        ...,
        description="Official job status values: queued, running, succeeded, failed.",
    )
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_url: str | None = None
    target_metadata: dict[str, Any] = Field(default_factory=dict)
    audit_id: int | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    request_id: str | None = None
    requested_tier: str | None = None
    tier_display: str | None = None
    stages: list[AuditStageStatus] | None = None


class CreateAuditResponse(BaseModel):
    audit_id: int
    report: dict
    request_id: str

    model_config = {
        "json_schema_extra": {
            "example": {
                "audit_id": 123,
                "request_id": "req-123",
                "report": {
                    "site": {"url": "https://example.com/", "market": "global", "language": "en"},
                    "competitors": [
                        {
                            "name": "Acme Co",
                            "score": 74.0,
                            "source": "Places",
                            "confidence_score": 0.84,
                            "geo_visibility": 76.0,
                            "aeo_score": 71.0,
                            "entity_strength": 75.0,
                            "rank": 2,
                        }
                    ],
                },
            }
        }
    }


class GuestAuditRequest(BaseModel):
    audit_target_type: Literal["website", "brand"] = "website"
    url: HttpUrl | None = None
    target_url: HttpUrl | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=256)
    entity: str | None = Field(default=None, min_length=1, max_length=256)
    target_metadata: dict[str, Any] | None = None
    email: EmailStr | None = None

    @field_validator("audit_target_type", mode="before")
    @classmethod
    def validate_target_type(cls, value: str) -> str:
        normalized = str(value or "website").strip().lower()
        if normalized not in {"website", "brand"}:
            raise ValueError("audit_target_type must be either 'website' or 'brand'.")
        return normalized

    @field_validator("url", "target_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: str | HttpUrl | None) -> str | None:
        if value is None:
            return None
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            return normalize_and_validate_url(raw_value)
        except ValueError as exc:
            raise ValueError(INVALID_URL_FORMAT_DETAIL) from exc

    @field_validator("target_name", "entity", mode="before")
    @classmethod
    def normalize_name_field(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target_contract(self) -> "GuestAuditRequest":
        if self.target_url is None and self.url is not None:
            self.target_url = self.url

        if self.audit_target_type == "website" and self.target_url is None:
            raise ValueError("Website audits require url or target_url.")

        if self.audit_target_type == "brand" and not self.resolved_target_name():
            raise ValueError("Brand audits require target_name or entity.")

        return self

    def resolved_target_url(self) -> str | None:
        if self.target_url is not None:
            return str(self.target_url)
        if self.url is not None:
            return str(self.url)
        return None

    def resolved_target_name(self) -> str | None:
        if self.target_name:
            return str(self.target_name).strip() or None
        if self.entity:
            return str(self.entity).strip() or None
        return None

    def resolved_target_metadata(self) -> dict[str, Any]:
        return dict(self.target_metadata) if isinstance(self.target_metadata, dict) else {}


class NotificationPreferencesRequest(BaseModel):
    notifications_enabled: bool
    notify_product_updates: bool | None = None
    notify_audit_alerts: bool | None = None
    notify_billing: bool | None = None


class NotificationPreferencesResponse(BaseModel):
    user_id: int
    notifications_enabled: bool
    notify_product_updates: bool
    notify_audit_alerts: bool
    notify_billing: bool


class AuditExport(BaseModel):
    id: int
    url: str
    geo_score: float = Field(..., description="GEO-specific score (not blended overall).")
    created_at: str
    full_report: dict


class SubscriptionExport(BaseModel):
    plan_type: str
    status: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    current_period_end: str | None
    cancel_at_period_end: bool


class BillingPaymentExport(BaseModel):
    id: int
    stripe_invoice_id: str
    stripe_customer_id: str
    stripe_subscription_id: str | None
    amount_paid: int | None
    amount_due: int | None
    currency: str | None
    status: str | None
    hosted_invoice_url: str | None
    invoice_pdf: str | None
    created_at: str
    # SIGV2-1144: the export states the statutory retention date of each
    # invoice, so the retention the account settings copy promises is visible
    # per record rather than only as a period in the UI.
    retention_until: str | None


class EmailOutboxExport(BaseModel):
    id: int
    to_email: str
    subject: str
    html_body: str | None
    text_body: str | None
    category: str | None
    correlation_id: str | None
    status: str
    provider: str | None
    attempts: int
    last_error: str | None
    created_at: str
    updated_at: str
    sent_at: str | None


class UserCreditAdjustmentExport(BaseModel):
    id: int
    user_id: int
    admin_user_id: int | None
    delta: int
    reason: str
    created_at: str


class AdminActionLogExport(BaseModel):
    id: int
    action: str
    target_type: str
    target_id: str | None
    metadata: dict
    created_at: str


class WorkspaceExportSummary(BaseModel):
    id: int
    name: str
    is_owner: bool
    role: str | None


class DataExportResponse(BaseModel):
    user_id: int
    email: str
    role: str
    credits: int
    notifications_enabled: bool
    company_profile: dict[str, str | bool | None]
    audits: list[AuditExport]
    subscription: SubscriptionExport | None
    billing_payments: list[BillingPaymentExport]
    email_outbox: list[EmailOutboxExport]
    user_credit_adjustments: list[UserCreditAdjustmentExport]
    admin_action_logs: list[AdminActionLogExport]
    workspaces: list[WorkspaceExportSummary]


class UserSubscriptionSummary(BaseModel):
    plan_type: str
    status: str
    current_period_end: str | None
    cancel_at_period_end: bool


class TrialStatusResponse(BaseModel):
    is_trial: bool = False
    trial_active: bool = False
    trial_expired: bool = False
    trial_plan: str | None = None
    trial_started_at: str | None = None
    trial_ends_at: str | None = None
    days_remaining: int = 0
    credits_remaining: int = 0
    credits_total: int = 0
    audits_used: int = 0
    audits_total: int = 0
    concierge_completed: bool = False
    limits_reached: bool = False
    limit_reason: str | None = None


class UserSummaryResponse(BaseModel):
    id: int
    email: str
    role: str
    credits: int = Field(..., description="Raw wallet credits available for per-audit deductions.")
    raw_credits: int = Field(..., description="Alias of credits for explicit API semantics.")
    included_audits_30d: int | None = Field(
        default=None,
        description="Plan audit allowance for the current rolling 30-day window, or null when unlimited.",
    )
    remaining_included_audits_30d: int | None = Field(
        default=None,
        description="Remaining plan audit allowance in the current rolling 30-day window, or null when unlimited.",
    )
    effective_credits: int = Field(
        ...,
        description="Legacy combined display value: raw wallet credits plus remaining included audits.",
    )
    credits_unlimited: bool
    audits_run_30d: int
    scans_used: int = Field(
        default=0, description="Scans consumed in the current rolling 30-day window."
    )
    scans_remaining: int | None = Field(
        default=None,
        description="Scans remaining in the current rolling 30-day window, or null when unlimited.",
    )
    reset_at: str | None = Field(
        default=None,
        description="When the oldest counted scan leaves the rolling window, or null when idle.",
    )
    subscription: UserSubscriptionSummary | None
    capabilities: dict[str, bool | int] = Field(default_factory=dict)
    trial: TrialStatusResponse | None = None


ONBOARDING_ALLOWED_STEPS = {
    "workspace_named",
    "first_project",
    "first_audit",
    "first_report",
    "invite_team_member",
    "connect_integration",
}


def _normalize_onboarding_steps(value: list[str] | None) -> list[str]:
    if not value:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_step in value:
        step = str(raw_step).strip().lower()
        if not step or step in seen or step not in ONBOARDING_ALLOWED_STEPS:
            continue
        seen.add(step)
        normalized.append(step)
    return normalized


def _normalize_onboarding_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return timestamp.isoformat()
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _normalize_onboarding_state(raw_state: Any) -> dict[str, Any]:
    payload = raw_state if isinstance(raw_state, dict) else {}
    return {
        "completed_steps": _normalize_onboarding_steps(
            payload.get("completed_steps")
            if isinstance(payload.get("completed_steps"), list)
            else []
        ),
        "started_at": _normalize_onboarding_timestamp(payload.get("started_at")),
        "dismissed_at": _normalize_onboarding_timestamp(payload.get("dismissed_at")),
        "updated_at": _normalize_onboarding_timestamp(payload.get("updated_at")),
    }


class UserOnboardingStateResponse(BaseModel):
    completed_steps: list[str] = Field(default_factory=list)
    started_at: str | None = None
    dismissed_at: str | None = None
    updated_at: str | None = None


class UserOnboardingStateUpdateRequest(BaseModel):
    completed_steps: list[str] | None = None
    add_completed_steps: list[str] | None = None
    started: bool | None = None
    dismissed: bool | None = None

    @field_validator("completed_steps", "add_completed_steps")
    @classmethod
    def validate_step_list(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return _normalize_onboarding_steps(value)


class UserProfileUpdateRequest(BaseModel):
    name: str | None = None
    company_legal_name: str | None = None
    company_registration_number: str | None = None
    company_vat_number: str | None = None
    billing_email: str | None = None
    billing_phone: str | None = None
    billing_address_line1: str | None = None
    billing_address_line2: str | None = None
    billing_city: str | None = None
    billing_state: str | None = None
    billing_postal_code: str | None = None
    billing_country: str | None = None
    billing_website_url: str | None = None
    billing_tax_exempt: bool | None = None

    @field_validator(
        "name",
        "company_legal_name",
        "company_registration_number",
        "company_vat_number",
        "billing_phone",
        "billing_address_line1",
        "billing_address_line2",
        "billing_city",
        "billing_state",
        "billing_postal_code",
        mode="before",
    )
    @classmethod
    def normalize_generic_text(cls, value: str | None, info) -> str | None:
        if info.field_name == "name":
            # ``name`` persists into User.company_name; the shared rule caps it.
            return normalize_company_name(value)
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        limits = {
            "company_legal_name": 160,
            "company_registration_number": 80,
            "company_vat_number": 80,
            "billing_phone": 40,
            "billing_address_line1": 180,
            "billing_address_line2": 180,
            "billing_city": 100,
            "billing_state": 100,
            "billing_postal_code": 40,
        }
        max_length = limits.get(str(info.field_name), 180)
        if len(normalized) > max_length:
            raise ValueError(f"{info.field_name} must be {max_length} characters or fewer.")
        return normalized

    @field_validator("billing_email", mode="before")
    @classmethod
    def normalize_billing_email(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().lower()
        if not normalized:
            return None
        if len(normalized) > 254:
            raise ValueError("billing_email must be 254 characters or fewer.")
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("billing_email must be a valid email address.")
        return normalized

    @field_validator("billing_country", mode="before")
    @classmethod
    def normalize_billing_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip().upper()
        if not normalized:
            return None
        if len(normalized) != 2 or not normalized.isalpha():
            raise ValueError("billing_country must be a 2-letter ISO country code.")
        return normalized

    @field_validator("billing_website_url", mode="before")
    @classmethod
    def normalize_billing_website_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            return None
        if len(normalized) > 255:
            raise ValueError("billing_website_url must be 255 characters or fewer.")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("billing_website_url must start with http:// or https://.")
        return normalized


class UserProfileResponse(BaseModel):
    user_id: int
    email: str
    name: str | None
    company_legal_name: str | None
    company_registration_number: str | None
    company_vat_number: str | None
    billing_email: str | None
    billing_phone: str | None
    billing_address_line1: str | None
    billing_address_line2: str | None
    billing_city: str | None
    billing_state: str | None
    billing_postal_code: str | None
    billing_country: str | None
    billing_website_url: str | None
    billing_tax_exempt: bool
    stripe_customer_id: str | None
    role: str
    notifications_enabled: bool
    mfa_enabled: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class ChangePasswordResponse(BaseModel):
    message: str


class MFAStatusResponse(BaseModel):
    enabled: bool


class MFASetupResponse(BaseModel):
    issuer: str
    account_name: str
    secret: str
    otpauth_uri: str
    qr_code_url: str
    setup_token: str


class MFAEnableRequest(BaseModel):
    # SIGV2-1241: enrollment binds only the server-minted secret carried by
    # setup_token. A client-supplied secret is never accepted.
    setup_token: str = Field(min_length=16, max_length=4096)
    otp_code: str = Field(min_length=6, max_length=12)

    @field_validator("setup_token")
    @classmethod
    def normalize_setup_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("setup_token is required.")
        return normalized

    @field_validator("otp_code")
    @classmethod
    def normalize_otp(cls, value: str) -> str:
        normalized = normalize_otp_code(value)
        if not normalized:
            raise ValueError("otp_code must contain exactly 6 digits.")
        return normalized


class MFADisableRequest(BaseModel):
    otp_code: str = Field(min_length=6, max_length=12)

    @field_validator("otp_code")
    @classmethod
    def normalize_otp(cls, value: str) -> str:
        normalized = normalize_otp_code(value)
        if not normalized:
            raise ValueError("otp_code must contain exactly 6 digits.")
        return normalized


class DataDeletionRequest(BaseModel):
    confirm: bool


class DataDeletionResponse(BaseModel):
    user_id: int
    deleted_audits: int
    deleted_subscription: bool
    # SIGV2-1144: invoices are no longer deleted. The field that used to
    # report how many were destroyed is gone rather than left reporting zero,
    # because a caller reading it was reading a compliance breach.
    retained_billing_payments: int
    billing_records_retained_until: str | None
    deletion_receipt_reference: str
    deleted_email_outbox_entries: int
    deleted_user_credit_adjustments: int
    anonymized_admin_action_logs: int
    anonymized_credit_adjustments_as_admin: int
    removed_workspace_memberships: int
    revoked_sessions: int
    # SIGV2-1251: revocation is best-effort (the account rows are already gone),
    # but a failure must not be reported as a clean revocation. These two make a
    # partial revocation visible to the caller instead of leaving
    # revoked_sessions to be read as "all of them".
    failed_session_revocations: int = 0
    session_revocation_complete: bool = True
    deleted_project_oauth_connections: int
    message: str


class AuditHistoryEntry(BaseModel):
    id: int
    url: str
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_url: str | None = None
    target_metadata: dict[str, Any] = Field(default_factory=dict)
    geo_score: float = Field(..., description="GEO-specific score (not blended overall).")
    seo_score: float | None = Field(None, description="SEO-specific score (not blended overall).")
    aeo_score: float | None = Field(None, description="AEO-specific score (not blended overall).")
    status: Literal["completed", "degraded", "failed", "archived", "purged"] = Field(
        ...,
        description="Official audit record status values.",
    )
    created_at: str
    intent: Literal["informational", "transactional", "navigational"] | None = None
    full_report: dict | None
    is_archived: bool = False
    is_pinned: bool = False


class GeoBenchmarkCompareResponse(BaseModel):
    site_a: dict
    site_b: dict
    citation_gap: dict
    source_overlap: dict
    keyword_dominance: list[dict]
    high_risk_discrepancies: dict
    window: dict


HEX_COLOR_PATTERN = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def _normalize_hex_color_input(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not HEX_COLOR_PATTERN.fullmatch(normalized):
        raise ValueError(f"{field_name} must be a valid hex color (e.g. #0EA5E9).")
    return normalized


def _resolve_branding_workspace(db: Session, user: models.User) -> models.Workspace | None:
    tenant_workspace = resolve_workspace_for_tenant_context(db, user=user)
    if tenant_workspace is not None:
        return tenant_workspace

    workspace = (
        db.query(models.Workspace)
        .filter(models.Workspace.owner_id == user.id)
        .order_by(models.Workspace.created_at.asc(), models.Workspace.id.asc())
        .first()
    )
    if workspace is not None:
        return workspace

    membership = (
        db.query(models.WorkspaceUser)
        .filter(models.WorkspaceUser.user_id == user.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .first()
    )
    if membership is None:
        return None

    return db.query(models.Workspace).filter(models.Workspace.id == membership.workspace_id).first()


def _resolve_user_branding_defaults(db: Session, user: models.User) -> dict[str, Any]:
    workspace = _resolve_branding_workspace(db, user)
    if workspace is not None:
        branding = resolve_workspace_branding(workspace)
        return {
            "custom_logo_url": branding["custom_logo_url"],
            "company_name": branding["company_name"],
            "primary_color": branding["primary_color"],
            "secondary_color": branding["secondary_color"],
            "hide_powered_by": bool(branding.get("hide_powered_by", False)),
        }
    return {
        "custom_logo_url": getattr(user, "custom_logo_url", None),
        "company_name": getattr(user, "company_name", None),
        "primary_color": _normalize_hex_color_input(
            getattr(user, "primary_color", None), field_name="primary_color"
        ),
        "secondary_color": _normalize_hex_color_input(
            getattr(user, "secondary_color", None), field_name="secondary_color"
        ),
        "hide_powered_by": False,
    }


def _serialize_user_profile(
    user: models.User,
    subscription: models.Subscription | None = None,
) -> dict[str, object]:
    resolved_subscription = subscription
    if resolved_subscription is None:
        resolved_subscription = getattr(user, "subscription", None)

    return {
        "user_id": user.id,
        "email": user.email,
        "name": user.company_name,
        "company_legal_name": getattr(user, "company_legal_name", None),
        "company_registration_number": getattr(user, "company_registration_number", None),
        "company_vat_number": getattr(user, "company_vat_number", None),
        "billing_email": getattr(user, "billing_email", None),
        "billing_phone": getattr(user, "billing_phone", None),
        "billing_address_line1": getattr(user, "billing_address_line1", None),
        "billing_address_line2": getattr(user, "billing_address_line2", None),
        "billing_city": getattr(user, "billing_city", None),
        "billing_state": getattr(user, "billing_state", None),
        "billing_postal_code": getattr(user, "billing_postal_code", None),
        "billing_country": getattr(user, "billing_country", None),
        "billing_website_url": getattr(user, "billing_website_url", None),
        "billing_tax_exempt": bool(getattr(user, "billing_tax_exempt", False)),
        "stripe_customer_id": (
            resolved_subscription.stripe_customer_id
            if resolved_subscription and resolved_subscription.stripe_customer_id
            else None
        ),
        "role": user.role,
        "notifications_enabled": bool(user.notifications_enabled),
        "mfa_enabled": bool(getattr(user, "mfa_secret", None)),
    }


def _sync_user_billing_profile_to_stripe_customer(
    *,
    user: models.User,
    subscription: models.Subscription | None,
    db: Session,
) -> None:
    if not subscription or not subscription.stripe_customer_id:
        return

    config = load_billing_config(db=db)
    mode_config = config.mode_configs.get(subscription.stripe_mode or "")
    api_key = mode_config.secret_key if mode_config is not None else None
    if not api_key:
        logger.warning("Billing profile Stripe sync skipped: code=missing_mode_credential")
        return

    name_value = user.company_legal_name or user.company_name or user.email
    customer_email = user.billing_email or user.email
    address_payload = {
        "line1": getattr(user, "billing_address_line1", None) or None,
        "line2": getattr(user, "billing_address_line2", None) or None,
        "city": getattr(user, "billing_city", None) or None,
        "state": getattr(user, "billing_state", None) or None,
        "postal_code": getattr(user, "billing_postal_code", None) or None,
        "country": getattr(user, "billing_country", None) or None,
    }
    address = {key: value for key, value in address_payload.items() if value}
    metadata_payload = {
        "platform_user_id": str(user.id),
        "company_display_name": user.company_name or "",
        "company_legal_name": getattr(user, "company_legal_name", None) or "",
        "company_registration_number": getattr(user, "company_registration_number", None) or "",
        "company_vat_number": getattr(user, "company_vat_number", None) or "",
        "company_website": getattr(user, "billing_website_url", None) or "",
        "billing_tax_exempt": "true"
        if bool(getattr(user, "billing_tax_exempt", False))
        else "false",
    }
    metadata = {key: value for key, value in metadata_payload.items() if value}

    modify_payload: dict[str, object] = {
        "name": name_value,
        "email": customer_email,
        "phone": getattr(user, "billing_phone", None),
        "tax_exempt": "exempt" if bool(getattr(user, "billing_tax_exempt", False)) else "none",
    }
    if address:
        modify_payload["address"] = address
    if metadata:
        modify_payload["metadata"] = metadata

    try:
        stripe.Customer.modify(subscription.stripe_customer_id, api_key=api_key, **modify_payload)
    except Exception as exc:  # pragma: no cover - network/provider dependent
        logger.warning(
            "Billing profile Stripe sync failed: error_class=%s code=customer_modify_failed",
            type(exc).__name__,
        )


def _build_mfa_qr_code_url(otpauth_uri: str) -> str:
    # External QR image endpoint consumed directly by the settings page.
    encoded = quote(otpauth_uri, safe="")
    return f"https://api.qrserver.com/v1/create-qr-code/?size=220x220&data={encoded}"


def _create_mfa_setup_token(*, user_id: int, secret: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=MFA_SETUP_TOKEN_EXPIRE_SECONDS)
    payload = {
        "sub": str(user_id),
        "purpose": "mfa_setup",
        "secret": secret,
        "exp": expires_at,
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def _decode_mfa_setup_token(*, token: str, user_id: int) -> str:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    except PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired MFA setup token.",
        ) from exc

    if payload.get("purpose") != "mfa_setup" or str(payload.get("sub")) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA setup token.",
        )

    secret = payload.get("secret")
    if not isinstance(secret, str) or not secret.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid MFA setup token payload.",
        )

    return secret.strip()


async def _verify_mfa_otp_or_raise(*, user_id: int, secret: str, otp_code: str | None) -> None:
    """SIGV2-1258: run the MFA management endpoints through the hardened path.

    Same single-use guarantee and per-user lockout the login path got in
    SIGV2-1244, and the same refusal to proceed when the replay guard cannot be
    reached. A replayed code is reported exactly like a wrong one so the caller
    learns nothing about which codes have already been spent.
    """
    result = await verify_totp_code_for_user(user_id=user_id, secret=secret, otp_code=otp_code)

    if result is MFAVerificationResult.THROTTLED:
        retry_after = await mfa_throttle_retry_after(user_id) or 60
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many MFA attempts. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    if result is MFAVerificationResult.UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MFA verification is temporarily unavailable. Try again shortly.",
        )

    if result is not MFAVerificationResult.OK:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid MFA code.")


class WhiteLabelBrandingUpdateRequest(BaseModel):
    custom_logo_url: str | None = None
    company_name: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_colors(cls, value: str | None, info):
        return _normalize_hex_color_input(value, field_name=info.field_name)


class WhiteLabelBrandingResponse(BaseModel):
    custom_logo_url: str | None = None
    company_name: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


ReportKindLiteral = Literal[
    "standard", "executive", "project", "competitors", "financial", "aio", "seo"
]
BrandingModeLiteral = Literal["platform", "white_label"]
CompetitorModeLiteral = Literal["latest", "trend"]


class WhiteLabelReportRequest(BaseModel):
    audit_id: int
    agency_name: str | None = None
    title: str | None = None
    logo_data_url: str | None = None
    report_date: str | None = None
    report_type: Literal["standard", "branded", "whitelabel"] | None = None
    report_kind: ReportKindLiteral | None = None
    branding_mode: BrandingModeLiteral | None = None
    competitor_mode: CompetitorModeLiteral | None = None
    hide_credit_cost: bool = True
    footer_text: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None
    language: str | None = None
    include_competitor_analysis: bool = False

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_colors(cls, value: str | None, info):
        return _normalize_hex_color_input(value, field_name=info.field_name)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        return normalize_report_language(value) if value else None

    @model_validator(mode="after")
    def validate_export_controls(self):
        if self.report_kind is not None:
            normalize_report_kind(self.report_kind)
        if self.branding_mode is not None:
            normalize_branding_mode(self.branding_mode)
        if self.competitor_mode is not None:
            normalize_competitor_mode(self.competitor_mode)
        resolved_report_kind = resolve_report_kind(
            explicit_report_kind=self.report_kind,
            explicit_report_type=self.report_type,
            template_type="Executive",
        )
        if self.competitor_mode is not None and resolved_report_kind != "competitors":
            raise ValueError("competitor_mode can only be used for competitor report exports.")
        return self


class WhiteLabelReportResponse(BaseModel):
    report_id: str
    generated_at: str
    agency_name: str
    primary_color: str
    include_competitor_analysis: bool
    audit: AuditHistoryEntry
    score_breakdown: dict
    highlights: list[str]


class ComplexReportOptions(BaseModel):
    mode: Literal["individual", "aggregated"] = "individual"
    sections: list[Literal["overview", "geo", "seo", "aeo", "cwv", "ai", "competitors"]] = Field(
        default_factory=lambda: ["overview", "geo", "seo", "aeo"]
    )
    report_type: Literal["standard", "battle", "branded", "whitelabel"] | None = None
    report_kind: ReportKindLiteral | None = None
    branding_mode: BrandingModeLiteral | None = None
    competitor_mode: CompetitorModeLiteral | None = None
    hide_credit_cost: bool = True
    footer_text: str | None = None
    competitors: list[int] = Field(default_factory=list)
    comparison_competitor_name: str | None = None
    comparison_competitor_rank: int | None = Field(default=None, gt=0)
    primary_color: str | None = None
    secondary_color: str | None = None
    language: str | None = None

    @field_validator("sections")
    @classmethod
    def validate_sections(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("At least one section must be selected.")
        deduped: list[str] = []
        for section in value:
            if section not in deduped:
                deduped.append(section)
        return deduped

    @field_validator("competitors")
    @classmethod
    def validate_competitors(cls, value: list[int]) -> list[int]:
        deduped = list(dict.fromkeys(value))
        if len(deduped) > 3:
            raise ValueError("A maximum of 3 competitor sites can be selected.")
        return deduped

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_colors(cls, value: str | None, info):
        return _normalize_hex_color_input(value, field_name=info.field_name)

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: str | None) -> str | None:
        return normalize_report_language(value) if value else None

    @field_validator("comparison_competitor_name")
    @classmethod
    def validate_comparison_competitor_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_export_controls(self):
        if self.report_kind is not None:
            normalize_report_kind(self.report_kind)
        if self.branding_mode is not None:
            normalize_branding_mode(self.branding_mode)
        if self.competitor_mode is not None:
            normalize_competitor_mode(self.competitor_mode)
        return self


class ComplexReportRequest(BaseModel):
    audit_ids: list[int] = Field(min_length=1, max_length=50)
    template_type: Literal["Technical", "Executive", "Comparative"]
    site_id: int | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    report_options: ComplexReportOptions = Field(default_factory=ComplexReportOptions)

    @model_validator(mode="after")
    def validate_date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must be earlier than or equal to date_to.")
        resolved_report_kind = resolve_report_kind(
            explicit_report_kind=self.report_options.report_kind,
            explicit_report_type=self.report_options.report_type,
            template_type=self.template_type,
        )
        if (
            self.report_options.competitor_mode is not None
            and resolved_report_kind != "competitors"
        ):
            raise ValueError("competitor_mode can only be used for competitor report exports.")
        return self


class ComplexReportResponse(BaseModel):
    report_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    template_type: str
    generated_at: str
    audit_count: int
    executive_summary: str | None = None
    aggregate: dict[str, object] | None = None
    download_url: str | None = None


class ReportLibraryItem(BaseModel):
    """One row of the report library, every column served from storage."""

    report_id: str
    name: str
    report_kind: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    created_at: datetime | None = None
    size_bytes: int | None = None
    status: str
    error: str | None = None
    expires_at: datetime | None = None
    link_expired: bool = False
    link_expiry_days_remaining: int | None = None
    retention_days: int
    download_url: str | None = None


class ReportLibraryResponse(BaseModel):
    items: list[ReportLibraryItem]
    total: int
    limit: int
    offset: int


class ReportLibraryDeleteRequest(BaseModel):
    report_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("report_ids")
    @classmethod
    def validate_report_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(report_id).strip() for report_id in value]
        deduped = list(dict.fromkeys(report_id for report_id in normalized if report_id))
        if not deduped:
            raise ValueError("At least one report id must be supplied.")
        return deduped


class ReportLibraryDeleteResponse(BaseModel):
    deleted: list[str]
    not_found: list[str]


class ExportVariantEntitlement(BaseModel):
    key: Literal["standard", "branded", "competitors", "whitelabel"]
    report_type: str
    report_kind: str | None = None
    template_type: str
    # True exactly when the plan fails this variant's capability requirement.
    # One field, so nothing can contradict it.
    locked: bool
    required_capability: str | None = None
    required_plan: str | None = None
    required_plan_label: str | None = None


class ExportVariantEntitlementsResponse(BaseModel):
    plan: str | None = None
    variants: list[ExportVariantEntitlement]


def _resolve_report_language_for_audits(
    audits: list[models.Audit],
    *,
    explicit_language: str | None = None,
) -> str:
    if explicit_language:
        return normalize_report_language(explicit_language)
    for audit in audits:
        project = getattr(audit, "project", None)
        project_language = getattr(project, "language", None)
        if isinstance(project_language, str) and project_language.strip():
            return normalize_report_language(project_language)
        report = audit.full_report if isinstance(audit.full_report, dict) else {}
        metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
        metadata_language = metadata.get("language")
        if isinstance(metadata_language, str) and metadata_language.strip():
            return normalize_report_language(metadata_language)
    return "en"


def _score_bundle_from_audit(audit: models.Audit) -> dict[str, float | None]:
    seo = float(audit.seo_score) if audit.seo_score is not None else None
    geo = float(audit.geo_score) if audit.geo_score is not None else None
    aeo = float(audit.aeo_score) if audit.aeo_score is not None else None
    available = [value for value in (seo, geo, aeo) if value is not None]
    overall = round(sum(available) / len(available), 2) if available else None
    return {
        "overall": overall,
        "seo": round(seo, 2) if seo is not None else None,
        "geo": round(geo, 2) if geo is not None else None,
        "aeo": round(aeo, 2) if aeo is not None else None,
    }


def _timeline_points_for_audits(audits: Sequence[models.Audit]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for audit in sorted(audits, key=lambda item: (item.created_at or datetime.min, item.id)):
        if audit.created_at is None:
            continue
        points.append(
            {
                "date": audit.created_at.astimezone(timezone.utc).isoformat()
                if audit.created_at.tzinfo is not None
                else audit.created_at.replace(tzinfo=timezone.utc).isoformat(),
                **_score_bundle_from_audit(audit),
            }
        )
    return points


def _series_delta(points: Sequence[Mapping[str, Any]], key: str) -> float | None:
    if len(points) < 2:
        return None
    first = points[0].get(key)
    last = points[-1].get(key)
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)):
        return None
    return round(float(last) - float(first), 2)


def _build_competitor_trend_payload(
    *,
    selected_audits: Sequence[models.Audit],
    primary_audit: models.Audit | None,
    competitor_audits: Sequence[models.Audit] | None,
) -> dict[str, Any] | None:
    if primary_audit is None or not competitor_audits or primary_audit.site_id is None:
        return None

    primary_points = _timeline_points_for_audits(
        [audit for audit in selected_audits if audit.site_id == primary_audit.site_id]
    )
    if not primary_points:
        return None

    coverage_dates = [
        point["date"] for point in primary_points if isinstance(point.get("date"), str)
    ]
    competitors_payload: list[dict[str, Any]] = []
    seen_site_ids: set[int] = set()
    for competitor_audit in competitor_audits:
        competitor_site_id = competitor_audit.site_id
        if competitor_site_id is None or competitor_site_id in seen_site_ids:
            continue
        seen_site_ids.add(int(competitor_site_id))
        competitor_points = _timeline_points_for_audits(
            [audit for audit in selected_audits if audit.site_id == competitor_site_id]
        )
        if not competitor_points:
            continue
        coverage_dates.extend(
            point["date"] for point in competitor_points if isinstance(point.get("date"), str)
        )
        competitors_payload.append(
            {
                "name": competitor_audit.url,
                "project_points": primary_points,
                "competitor_points": competitor_points,
                "project_latest": primary_points[-1],
                "competitor_latest": competitor_points[-1],
                "project_delta_overall": _series_delta(primary_points, "overall"),
                "competitor_delta_overall": _series_delta(competitor_points, "overall"),
            }
        )

    if not competitors_payload:
        return None

    sorted_coverage = sorted(coverage_dates)
    return {
        "enabled": True,
        "project_label": primary_audit.url,
        "coverage_start": sorted_coverage[0] if sorted_coverage else None,
        "coverage_end": sorted_coverage[-1] if sorted_coverage else None,
        "audit_count": len(selected_audits),
        "competitors": competitors_payload,
    }


def _build_complex_report_pdf(
    *,
    selected_audits: list[models.Audit],
    template_type: str,
    options: ComplexReportOptions,
    user: models.User,
    db: Session | None = None,
    branding_config: dict[str, Any] | None = None,
    export_manifest: dict[str, Any] | None = None,
    language: str | None = None,
    primary_audit: models.Audit | None = None,
    competitor_audits: list[models.Audit] | None = None,
) -> bytes:
    if db is not None:
        resolved_export_manifest = dict(
            export_manifest
            or _resolve_complex_report_manifest(
                template_type=template_type,
                options=options,
                branding_config=branding_config,
            )
        )
        report_language = _resolve_report_language_for_audits(
            selected_audits,
            explicit_language=language or options.language,
        )
        return render_report_pdf_service(
            db=db,
            selected_audits=selected_audits,
            template_type=template_type,
            options=options.model_dump(),
            branding_config=(
                branding_config
                or build_report_branding_config(
                    persisted_branding=None,
                    export_manifest=resolved_export_manifest,
                    template_type=template_type,
                    language=report_language,
                    overrides=options.model_dump(exclude_none=True),
                )
            ),
            export_manifest=resolved_export_manifest,
            language=report_language,
            primary_audit=primary_audit,
            competitor_audits=competitor_audits,
        )

    persisted_branding = branding_config or {}
    report_language = _resolve_report_language_for_audits(
        selected_audits,
        explicit_language=language or options.language,
    )
    resolved_export_manifest = dict(
        export_manifest
        or _resolve_complex_report_manifest(
            template_type=template_type,
            options=options,
            branding_config=persisted_branding,
        )
    )
    resolved_report_type = str(resolved_export_manifest.get("render_report_type") or "standard")
    primary_color = options.primary_color or persisted_branding.get("primary_color") or "#0EA5E9"
    secondary_color = (
        options.secondary_color or persisted_branding.get("secondary_color") or "#E2E8F0"
    )
    logo_data_url = persisted_branding.get("custom_logo_url")
    company_name = persisted_branding.get("company_name")
    hide_powered_by = bool(persisted_branding.get("hide_powered_by"))
    if resolved_report_type == "battle":
        default_title = get_report_label(
            report_language, "pdf.battle_report", default="Battle Report"
        )
    else:
        default_title = get_report_label(
            report_language,
            f"pdf.{template_type.lower()}_report",
            default=f"{template_type} Report",
        )
    default_title = str(persisted_branding.get("title") or default_title)

    branding = BrandingConfig(
        title=default_title,
        primary_color=primary_color,
        secondary_color=secondary_color,
        company_name=company_name,
        generated_date=(
            str(persisted_branding.get("generated_date") or "").strip()
            or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ),
        logo_data_url=logo_data_url,
        language=report_language,
        vendor_name="Qiko Signal",
        is_white_label=resolved_report_type == "whitelabel",
        show_powered_by=resolved_report_type == "branded" and not hide_powered_by,
        report_type=resolved_report_type,
        report_kind=str(resolved_export_manifest.get("report_kind") or ""),
        branding_mode=str(resolved_export_manifest.get("branding_mode") or ""),
        competitor_mode=(str(resolved_export_manifest.get("competitor_mode") or "") or None),
        hide_credit_cost=bool(resolved_export_manifest.get("hide_credit_cost", True)),
        footer_text=getattr(options, "footer_text", None) or persisted_branding.get("footer_text"),
        custom_footer_text=getattr(options, "footer_text", None)
        or persisted_branding.get("footer_text"),
        show_platform_branding=resolved_report_type != "whitelabel",
    )

    if resolved_report_type == "battle":
        if primary_audit and competitor_audits:
            trend_payload = (
                _build_competitor_trend_payload(
                    selected_audits=selected_audits,
                    primary_audit=primary_audit,
                    competitor_audits=competitor_audits,
                )
                if str(resolved_export_manifest.get("competitor_mode") or "").strip().lower()
                == "trend"
                else None
            )
            comparison_pairs = [
                {
                    "left_title": primary_audit.url,
                    "left_report": _apply_complex_report_sections(
                        primary_audit.full_report
                        if isinstance(primary_audit.full_report, dict)
                        else {},
                        options.sections,
                    ),
                    "right_title": competitor_audit.url,
                    "right_report": _apply_complex_report_sections(
                        competitor_audit.full_report
                        if isinstance(competitor_audit.full_report, dict)
                        else {},
                        options.sections,
                    ),
                    "left_full_report": primary_audit.full_report
                    if isinstance(primary_audit.full_report, dict)
                    else {},
                    "right_full_report": competitor_audit.full_report
                    if isinstance(competitor_audit.full_report, dict)
                    else {},
                    "left_audit_record": primary_audit,
                    "right_audit_record": competitor_audit,
                }
                for competitor_audit in competitor_audits
            ]
            first_pair = comparison_pairs[0]
            return render_battle_report_pdf(
                left_title=str(first_pair["left_title"]),
                right_title=str(first_pair["right_title"]),
                left_report=first_pair["left_report"],
                right_report=first_pair["right_report"],
                comparison_pairs=comparison_pairs,
                branding=branding,
                selected_sections=options.sections,
                left_full_report=first_pair["left_full_report"],
                right_full_report=first_pair["right_full_report"],
                left_audit_record=first_pair["left_audit_record"],
                right_audit_record=first_pair["right_audit_record"],
                trend_payload=trend_payload,
            )

        if len(selected_audits) == 1:
            comparison_pair = build_canonical_competitor_battle_pair(
                selected_audits[0],
                competitor_name=options.comparison_competitor_name,
                competitor_rank=options.comparison_competitor_rank,
            )
            return render_battle_report_pdf(
                left_title=str(comparison_pair["left_title"]),
                right_title=str(comparison_pair["right_title"]),
                left_report=comparison_pair["left_report"],
                right_report=comparison_pair["right_report"],
                comparison_pairs=[comparison_pair],
                branding=branding,
                selected_sections=options.sections,
                left_full_report=comparison_pair["left_full_report"],
                right_full_report=comparison_pair["right_full_report"],
                left_audit_record=comparison_pair["left_audit_record"],
                right_audit_record=comparison_pair["right_audit_record"],
                trend_payload=None,
            )

        left_report = _apply_complex_report_sections(
            selected_audits[0].full_report
            if isinstance(selected_audits[0].full_report, dict)
            else {},
            options.sections,
        )
        right_report = _apply_complex_report_sections(
            selected_audits[1].full_report
            if isinstance(selected_audits[1].full_report, dict)
            else {},
            options.sections,
        )
        return render_battle_report_pdf(
            left_title=selected_audits[0].url,
            right_title=selected_audits[1].url,
            left_report=left_report,
            right_report=right_report,
            branding=branding,
            selected_sections=options.sections,
            left_full_report=selected_audits[0].full_report
            if isinstance(selected_audits[0].full_report, dict)
            else {},
            right_full_report=selected_audits[1].full_report
            if isinstance(selected_audits[1].full_report, dict)
            else {},
            left_audit_record=selected_audits[0],
            right_audit_record=selected_audits[1],
            trend_payload=None,
        )

    primary_audit = selected_audits[0]
    full_report = primary_audit.full_report if isinstance(primary_audit.full_report, dict) else {}
    highlights = build_report_highlights(full_report)
    return render_white_label_pdf(
        audit_id=primary_audit.id,
        audit_url=primary_audit.url,
        geo_score=primary_audit.geo_score,
        highlights=highlights,
        full_report=full_report,
        branding=branding,
        include_competitor_analysis=(
            "competitors" in options.sections
            or bool(getattr(options, "include_competitor_analysis", False))
        ),
        audit_record=primary_audit,
        audit_history=selected_audits,
        selected_sections=options.sections,
    )


class GeoVisibilityRequest(BaseModel):
    target: str
    location: str
    seed_queries: list[str] | None = None
    brand: str | None = None


class GeoVisibilityQueryResult(BaseModel):
    query: str
    answer_excerpt: str
    provider_citations: list[str]
    brand_cited: bool
    status: Literal["ok", "timeout", "error"]
    error: str | None = None
    provider_status_code: int | None = None


class GeoVisibilityResponse(BaseModel):
    target: str
    location: str
    provider: str
    seed_queries: list[str]
    total_queries: int
    # Queries the provider actually answered. ``visibility_index`` is a share
    # of these, and is meaningless when ``visibility_measured`` is false.
    answered_queries: int = 0
    citations: int
    timed_out_queries: int
    failed_queries: int = 0
    # Queries the provider refused with a 4xx (bad parameter, rejected key,
    # exhausted quota). No search ran for those.
    provider_rejected_queries: int = 0
    provider_error: str | None = None
    visibility_measured: bool = True
    visibility_index: float
    partial_results: bool
    results: list[GeoVisibilityQueryResult]


class VisibilityTrendPoint(BaseModel):
    run_id: int
    created_at: str
    score: float
    status: str


class VisibilityTrendsResponse(BaseModel):
    topic: str
    provider: str | None = None
    points: list[VisibilityTrendPoint]


class VisibilityLatestRunResponse(BaseModel):
    batch_id: int
    topic: str
    provider: str
    schedule_key: str
    status: str
    score: float | None
    error: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    runs: list[dict[str, object]]


class VolatilityDomainChangePublicResponse(BaseModel):
    domain: str
    delta: int


class VolatilityIndustryPublicResponse(BaseModel):
    industry: str
    volatility_score: float | None = None
    compared_queries: int
    changed_ratio: float | None = None


class VolatilitySummaryPublicResponse(BaseModel):
    provider: str
    generated_at: str
    latest_snapshot_date: str | None = None
    no_data: bool
    degraded: bool
    degraded_reasons: list[str] = Field(default_factory=list)
    weather_label: str
    volatility_score: float | None = None
    compared_queries: int
    changed_ratio: float | None = None
    avg_text_similarity: float | None = None
    avg_citation_jaccard: float | None = None
    citation_churn_rate: float | None = None
    format_change_rate: float | None = None
    top_winners: list[VolatilityDomainChangePublicResponse] = Field(default_factory=list)
    top_losers: list[VolatilityDomainChangePublicResponse] = Field(default_factory=list)
    industries: list[VolatilityIndustryPublicResponse] = Field(default_factory=list)


class VolatilityTrendPublicPointResponse(BaseModel):
    date: str
    volatility_score: float | None = None
    compared_queries: int
    changed_ratio: float | None = None


class VolatilityTrendsPublicResponse(BaseModel):
    provider: str
    days: int
    points: list[VolatilityTrendPublicPointResponse] = Field(default_factory=list)


class VolatilityIndustryMatrixPointPublicResponse(BaseModel):
    date: str
    industry: str
    provider: str
    volatility_score: float | None = None
    compared_queries: int
    changed_ratio: float | None = None
    moving_queries: list[str] = Field(default_factory=list)


class VolatilityIndustryMatrixPublicResponse(BaseModel):
    provider: str
    days: int
    points: list[VolatilityIndustryMatrixPointPublicResponse] = Field(default_factory=list)


class VolatilityCitationLedgerRowPublicResponse(BaseModel):
    domain: str
    industry: str
    base_citations: int
    current_citations: int
    delta: int
    delta_pct: float
    provider: str
    volatility_score: float | None = None
    direction: str
    trend: list[int] = Field(default_factory=list)


class VolatilityCitationLedgerPublicResponse(BaseModel):
    provider: str
    generated_at: str
    latest_snapshot_date: str | None = None
    rows: list[VolatilityCitationLedgerRowPublicResponse] = Field(default_factory=list)


class VolatilityPublicDashboardResponse(BaseModel):
    available_providers: list[str] = Field(default_factory=list)
    summary: VolatilitySummaryPublicResponse
    trends: VolatilityTrendsPublicResponse
    industry_matrix: VolatilityIndustryMatrixPublicResponse
    citation_ledger: VolatilityCitationLedgerPublicResponse


class AEOAnswerabilityRequest(URLValidatedRequest):
    pass


class AEOAnswerabilityScore(BaseModel):
    value: int
    model: str
    raw_model_output: float


class AEOAnswerabilityFactor(BaseModel):
    feature: str
    label: str
    impact: float
    direction: Literal["positive", "negative"]
    raw_value: str
    explanation: str


class AEOAnswerabilityHistoryPoint(BaseModel):
    timestamp: str
    score: int


class AEOAnswerabilityResponse(BaseModel):
    url: str
    domain: str
    raw_features: dict[str, float | None]
    normalized_features: dict[str, float]
    score: AEOAnswerabilityScore
    answer_failure_reasons: list[str]
    primary_failure_reason: str | None = None
    readability_score: float
    readability_findings: list[str]
    rewrite_suggestions: list[dict[str, Any]]
    factor_explanations: list[AEOAnswerabilityFactor]
    history: list[AEOAnswerabilityHistoryPoint]


class EntityAnalysisResponse(BaseModel):
    url: str
    primary_entity: dict
    entities: list[dict] = Field(default_factory=list)
    same_as_urls: list[str] = Field(default_factory=list)
    mention_relations: list[dict] = Field(default_factory=list)
    expected_schema_type: str
    detected_schema_blocks: list[dict]
    comparison: dict
    missing_fields_by_schema_type: dict
    meta: dict


GraphEntityCategory = Literal["Person", "Organization", "Concept", "Product"]
GraphRelationType = Literal["MENTIONED_IN", "RELATED_TO"]


class EntityGraphNode(BaseModel):
    key: str
    name: str
    type: str
    category: GraphEntityCategory
    normalized_name: str
    sourceURLs: list[str] = Field(default_factory=list)


class EntityGraphEdge(BaseModel):
    from_: str = Field(validation_alias="from", serialization_alias="from")
    to: str
    relation: GraphRelationType
    source: str
    page_url: str


class EntityGraphPayload(BaseModel):
    nodes: list[EntityGraphNode] = Field(default_factory=list)
    edges: list[EntityGraphEdge] = Field(default_factory=list)
    categories: list[GraphEntityCategory] = Field(default_factory=list)
    url_mentions: list[str] = Field(default_factory=list)


class EntityGraphResponse(BaseModel):
    url: str
    uniqueness: dict
    nodes: list[EntityGraphNode] = Field(default_factory=list)
    edges: list[EntityGraphEdge] = Field(default_factory=list)
    categories: list[GraphEntityCategory] = Field(default_factory=list)
    url_mentions: list[str] = Field(default_factory=list)


class EntityExtractRequest(URLValidatedRequest):
    pass


class ExtractedEntity(BaseModel):
    name: str
    type: str
    confidence: float | None = None


class EntityExtractResponse(BaseModel):
    url: str
    entities: list[ExtractedEntity] = Field(default_factory=list)


class IntentCorpusEntryPayload(BaseModel):
    question: str
    context: str | None = None
    metadata: dict | None = None


class IntentIngestRequest(BaseModel):
    entries: list[IntentCorpusEntryPayload]
    reindex: bool = True


class IntentPredictRequest(BaseModel):
    query: str
    top_k: int = Field(default=5, ge=1, le=20)


class IntentPredictionItem(BaseModel):
    corpus_id: int
    question: str
    context: str | None = None
    similarity: float
    normalized_score: float


class IntentPredictResponse(BaseModel):
    query: str
    top_k: int
    predictions: list[IntentPredictionItem]


def build_report_highlights(full_report: dict) -> list[str]:
    highlights: list[str] = []
    analysis = full_report.get("analysis", {}) if isinstance(full_report, dict) else {}
    performance = full_report.get("performance", {}) if isinstance(full_report, dict) else {}
    network = full_report.get("network", {}) if isinstance(full_report, dict) else {}

    scores = full_report.get("scores", {}) if isinstance(full_report, dict) else {}
    if not isinstance(scores, dict):
        scores = {}

    def _resolve_pillar_score(canonical_key: str, legacy_key: str) -> float:
        """Prefer the canonical ``scores`` block, falling back to legacy analysis."""
        candidate = scores.get(canonical_key)
        if isinstance(candidate, (int, float)):
            return float(candidate)
        return extract_score(analysis, legacy_key)

    geo_score = _resolve_pillar_score("geo", "geo_score")
    seo_score = _resolve_pillar_score("seo", "seo_score")
    aeo_score = _resolve_pillar_score("aeo", "aeo_score")

    if geo_score:
        highlights.append(f"GEO score checked in at {geo_score:.0f}.")
    if seo_score:
        highlights.append(f"SEO score checked in at {seo_score:.0f}.")
    if aeo_score:
        highlights.append(f"AEO readiness scored {aeo_score:.0f}.")

    performance_score = performance.get("performance_score")
    if isinstance(performance_score, (int, float)):
        highlights.append(f"Performance score reported at {performance_score:.0f}.")

    if network.get("supports_http2"):
        highlights.append("HTTP/2 support detected for faster resource multiplexing.")
    if network.get("supports_http3_inferred"):
        highlights.append("HTTP/3 support advertised for modern transport resilience.")

    if not highlights:
        highlights.append("Audit data captured successfully. No additional highlights available.")

    return highlights


def _raise_client_error(
    status_code: int,
    key: str,
    fallback: str,
    *,
    request: Request | None = None,
    exc: Exception | None = None,
    log_context: str,
) -> None:
    if exc is not None:
        logger.warning("%s: %s", log_context, exc)
    detail = translate_backend_message(key, fallback, request=request)
    raise HTTPException(status_code=status_code, detail=detail)


def _normalize_audit_target_type_value(value: Any) -> str:
    return normalize_audit_target_type(value)


def _resolve_audit_target_type(audit: models.Audit) -> str:
    return resolve_audit_target_type_contract(audit)


def _resolve_audit_target_url(audit: models.Audit) -> str | None:
    return resolve_audit_target_url_contract(audit)


def _resolve_audit_target_name(audit: models.Audit) -> str | None:
    return resolve_audit_target_name_contract(audit)


def _resolve_audit_target_metadata(audit: models.Audit) -> dict[str, Any]:
    return resolve_audit_target_metadata_contract(audit)


def _resolve_legacy_audit_url(audit: models.Audit) -> str:
    return resolve_legacy_audit_url_contract(audit)


def normalize_persisted_full_report(audit: models.Audit, db: Session) -> dict:
    """Return a canonical report view without mutating stored legacy payloads on read."""

    # Read-only (side-effect free): when the audit is linked to a project, fetch
    # the dismissed Advisor action fingerprints so the Advisor view suppresses
    # them (learnings loop, Task 7.2). No write/mutation occurs.
    dismissed: set[str] | None = None
    search_type_measurements: dict[str, dict[str, Any]] | None = None
    project_id = getattr(audit, "project_id", None)
    if db is not None and project_id is not None:
        dismissed = dismissed_fingerprints(db, project_id)
        # Measured per-search-type visibility and answer ratio from this
        # project's ProjectVisibilityQuery runs. Read-only and defensive: no
        # rows -> all five unmeasured, which is what the cards then say.
        search_type_measurements = compute_search_type_measurements(db, project_id)
    return build_normalized_audit_report(
        audit,
        current_plan=resolve_audit_normalization_current_plan(audit.user),
        dismissed=dismissed,
        search_type_measurements=search_type_measurements,
    )


def _derive_audit_record_status(audit: models.Audit) -> str:
    # Check archive state first, archived audits have no full_report in DB
    if audit.full_report is None and audit.report_archive_uri:
        return "archived"
    if (
        audit.full_report is None
        and not audit.report_archive_uri
        and getattr(audit, "report_archived_at", None)
    ):
        return "purged"

    full_report = audit.full_report if isinstance(audit.full_report, dict) else {}
    metadata = full_report.get("metadata") if isinstance(full_report, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}

    audit_outcome = str(metadata.get("audit_outcome") or "").strip().lower()
    if audit_outcome in AUDIT_RECORD_STATUSES:
        if (
            audit_outcome == AUDIT_RECORD_STATUS_DEGRADED
            and metadata.get("scores_available") is False
        ):
            return AUDIT_RECORD_STATUS_FAILED
        return audit_outcome

    if metadata.get("scores_available") is False:
        return AUDIT_RECORD_STATUS_FAILED

    service_status = (
        metadata.get("service_status") if isinstance(metadata.get("service_status"), dict) else {}
    )
    ai_status = str(service_status.get("ai_service") or "").strip().lower()
    if ai_status in {"disabled", "degraded", "error", "failed", "timeout", "unavailable"}:
        return AUDIT_RECORD_STATUS_DEGRADED

    service_errors = (
        metadata.get("service_errors") if isinstance(metadata.get("service_errors"), dict) else {}
    )
    if service_errors.get("ai_service"):
        return AUDIT_RECORD_STATUS_DEGRADED

    return AUDIT_RECORD_STATUS_COMPLETED


def _is_billable_audit_outcome(full_report: dict | None) -> bool:
    return is_billable_audit_outcome(full_report)


def _coerce_score_breakdown(candidate: dict | None) -> dict[str, float] | None:
    if not isinstance(candidate, dict):
        return None
    if not {"seo", "geo", "aeo"}.issubset(candidate.keys()):
        return None
    score_breakdown = {
        "seo": float(candidate.get("seo") or 0.0),
        "geo": float(candidate.get("geo") or 0.0),
        "aeo": float(candidate.get("aeo") or 0.0),
    }
    score_breakdown["overall"] = float(
        candidate.get("overall")
        if candidate.get("overall") is not None
        else (score_breakdown["seo"] + score_breakdown["geo"] + score_breakdown["aeo"]) / 3
    )
    return score_breakdown


def _extract_score_breakdown_from_report(full_report: dict | None) -> dict[str, float]:
    if not isinstance(full_report, dict):
        return {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0}

    report_scores = _coerce_score_breakdown(full_report.get("scores"))
    if report_scores is not None:
        return report_scores

    analysis = full_report.get("analysis", {}) if isinstance(full_report, dict) else {}
    score_breakdown = {
        "seo": extract_score(analysis, "seo_score"),
        "geo": extract_score(analysis, "geo_score"),
        "aeo": extract_score(analysis, "aeo_score"),
    }
    score_breakdown["overall"] = (
        score_breakdown["seo"] + score_breakdown["geo"] + score_breakdown["aeo"]
    ) / 3
    return score_breakdown


def _ensure_report_provider_tier(
    full_report: dict[str, Any],
    *,
    requested_provider: str,
    requested_tier: str,
    execution_tier: str,
    mode_label: str,
) -> dict[str, Any]:
    metadata = full_report.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}

    provider = metadata.get("provider")
    model = metadata.get("model")
    metadata["provider"] = str(provider or model or requested_provider)
    metadata["tier"] = str(metadata.get("tier") or requested_tier)
    metadata["requested_tier"] = str(metadata.get("requested_tier") or requested_tier)
    metadata["execution_tier"] = str(metadata.get("execution_tier") or execution_tier)
    metadata["mode_label"] = str(metadata.get("mode_label") or mode_label)

    full_report["metadata"] = metadata
    return full_report


def parse_rate_limit_config(
    config_value: str | None, default_limit: int, default_window_seconds: int
) -> tuple[int, int]:
    if not config_value:
        return default_limit, default_window_seconds

    normalized = config_value.strip().lower()
    match = re.fullmatch(r"(\d+)\s*/\s*(\d+)?\s*([a-z]+)", normalized)
    if not match:
        logger.warning("Invalid rate limit config '%s'. Falling back to defaults.", config_value)
        return default_limit, default_window_seconds

    limit = int(match.group(1))
    amount = int(match.group(2) or "1")
    unit = match.group(3)
    unit_to_seconds = {
        "s": 1,
        "sec": 1,
        "secs": 1,
        "second": 1,
        "seconds": 1,
        "m": 60,
        "min": 60,
        "mins": 60,
        "minute": 60,
        "minutes": 60,
        "h": 3600,
        "hr": 3600,
        "hour": 3600,
        "hours": 3600,
        "d": 86400,
        "day": 86400,
        "days": 86400,
    }
    window_seconds = unit_to_seconds.get(unit)
    if not window_seconds:
        logger.warning(
            "Unsupported rate limit unit '%s' in '%s'. Falling back to defaults.",
            unit,
            config_value,
        )
        return default_limit, default_window_seconds
    return limit, amount * window_seconds


async def enforce_rate_limit(
    *,
    key_prefix: str,
    identifier: str,
    limit: int,
    window_seconds: int,
    too_many_requests_detail: str = "Too Many Requests",
) -> None:
    key = f"ratelimit:{key_prefix}:{identifier}"

    try:
        async with get_async_redis() as redis_client:
            current = await redis_client.incr(key)
            if current == 1:
                await redis_client.expire(key, window_seconds)
            if current > limit:
                raise HTTPException(status_code=429, detail=too_many_requests_detail)
    except HTTPException:
        raise
    except Exception as exc:
        # Fail open on Redis errors, but log at ERROR with a distinct code so
        # a limiter outage is alertable instead of silent.
        logger.error(
            "RATE_LIMIT_CHECK_UNAVAILABLE: rate limit check failed for %s: %s",
            key_prefix,
            exc,
        )


def _resolve_client_ip(request: Request) -> str:
    # Delegates to the shared trusted-proxy-aware resolver (SIGV2-1243):
    # identity headers are honored only when the immediate peer is in
    # settings.TRUSTED_PROXY_CIDRS.
    return resolve_client_ip(request)


async def enforce_guest_audit_limit(request: Request) -> None:
    if os.getenv("ENVIRONMENT", "").lower() in ("local", "development"):
        return

    if os.getenv("APP_ENV", "").lower() in ("local", "development"):
        return

    client_ip = _resolve_client_ip(request)
    if client_ip in ("127.0.0.1", "localhost", "::1") or client_ip.startswith(
        ("172.", "192.168.", "10.")
    ):
        return

    configured_limit, configured_window = parse_rate_limit_config(
        os.getenv("RATE_LIMIT_GUEST_AUDIT"),
        default_limit=int(os.getenv("GUEST_AUDIT_LIMIT", "1")),
        default_window_seconds=int(os.getenv("GUEST_AUDIT_WINDOW_SECONDS", "86400")),
    )
    client_ip = _resolve_client_ip(request)
    user_agent = request.headers.get("user-agent", "unknown")
    user_agent_hash = hashlib.sha256(user_agent.encode("utf-8")).hexdigest()
    await enforce_rate_limit(
        key_prefix="guest_audit",
        identifier=f"{client_ip}:{user_agent_hash}",
        limit=configured_limit,
        window_seconds=configured_window,
        too_many_requests_detail=translate_backend_message(
            "errors.too_many_requests_guest_audit",
            "Too Many Requests: guest audits are limited. Please try again later.",
            request=request,
        ),
    )


async def enforce_authenticated_audit_limit(user: models.User, request: Request) -> None:
    configured_limit, configured_window = parse_rate_limit_config(
        os.getenv("RATE_LIMIT_AUDIT", "10/min"),
        default_limit=10,
        default_window_seconds=60,
    )
    client_ip = _resolve_client_ip(request)
    identifier = f"user:{user.id}:{client_ip}"
    await enforce_rate_limit(
        key_prefix="audit",
        identifier=identifier,
        limit=configured_limit,
        window_seconds=configured_window,
        too_many_requests_detail=translate_backend_message(
            "errors.too_many_requests",
            "Too Many Requests",
            request=request,
        ),
    )


def get_user_or_404(db: Session, user_id: int) -> models.User:
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.user_not_found", "User not found"),
        )
    return user


# Initialize services
scraper_service = ScraperService()
ai_client = AIClient()
performance_service = PerformanceService()
performance_snapshot_service = PerformanceSnapshotService(performance_service)
network_service = NetworkAnalysisService()

geo_visibility_service = GeoVisibilityService()
aeo_answerability_service = AEOAnswerabilityService()
entity_service = EntityService()
entity_graph_service = EntityGraphService()
hallucination_service = HallucinationService()
competitor_discovery_service = build_competitor_discovery_service()
competitor_benchmark_service = CompetitorBenchmarkService()
predictive_intent_service = PredictiveIntentService()
geo_benchmark_service = GeoBenchmarkService()
site_entity_fact_service = SiteEntityFactService()
plan_validator = PlanValidator()

from services.queue_routing import resolve_queue_for_tier

CACHE_TTL_DEFAULT = int(os.getenv("AUDIT_CACHE_TTL_SECONDS", "86400"))
CACHE_TTL_BY_TIER = {
    "fast": int(os.getenv("AUDIT_CACHE_TTL_FAST_SECONDS", str(CACHE_TTL_DEFAULT))),
    "smart": int(os.getenv("AUDIT_CACHE_TTL_SMART_SECONDS", str(CACHE_TTL_DEFAULT))),
}
CACHE_TTL_BY_PLAN = {
    "plan_standard": int(os.getenv("AUDIT_CACHE_TTL_STARTER_SECONDS", str(CACHE_TTL_DEFAULT))),
    "plan_specialist": int(os.getenv("AUDIT_CACHE_TTL_PRO_SECONDS", str(CACHE_TTL_DEFAULT))),
    "plan_executive": int(os.getenv("AUDIT_CACHE_TTL_ENTERPRISE_SECONDS", str(CACHE_TTL_DEFAULT))),
}
PLAN_TO_TIER = {
    "plan_standard": "fast",
    "plan_specialist": "smart",
    "plan_executive": "smart",
}


def normalize_plan_type(plan: str | None) -> str | None:
    return plan_validator.normalize_plan_type(plan)


# resolve_subscription_plan and _resolve_plan_capabilities are imported from
# services.audit_helpers (Item 24 unification).


def _require_plan_feature(
    user: models.User | None,
    *,
    feature_key: str,
    detail: str,
    status_code: int = status.HTTP_402_PAYMENT_REQUIRED,
) -> None:
    if not plan_validator.has_feature(user, feature_key):
        raise HTTPException(status_code=status_code, detail=detail)


def _strip_client_model_selection(
    *,
    provider: str | None,
    selected_models: list[str] | None,
) -> tuple[None, None]:
    """Discard any client-submitted provider or model selection. Always.

    Choosing the models that run an audit is not a capability of any plan
    (SIGV2-1139). The capability key this function once checked,
    ``has_custom_ai_model_routing``, was ``False`` on all five entries of
    ``CAPABILITY_MATRIX`` and absent from ``MINIMUM_PLAN_BY_FEATURE``, and
    ``PlanValidator.has_feature`` reads only that matrix, so the check could
    never pass for any user. The Enterprise tier it was named after no longer
    exists either: ``CANONICAL_PLAN_TYPES`` tops out at ``plan_executive`` and
    the Global Enterprise plan was removed from the product (alembic
    ``20260731_010000_narrow_subscription_plan_type_constraint``). The
    capability branch was deleted rather than left as a decoy that implied an
    upgrade path to a tier nobody can buy, and SIGV2-1120 then removed the key
    itself from every matrix so no reader can mistake it for a live gate.

    The strip itself stays, because it is validation and not decoration. The
    start-scan form still posts its default ``provider`` and both fields remain
    part of the public request schema, so dropping them here is what keeps a
    caller from steering which paid provider executes their audit and from
    forcing the expensive ``multi_model_consensus`` path, which
    ``services/cost_forecast_service.py`` selects as soon as two or more models
    survive. ``resolve_audit_route`` owns routing instead.

    Returning ``None`` rather than raising is deliberate: the default
    ``provider`` field must not turn an otherwise valid request into a 4xx.
    """
    return None, None


def _normalize_requested_audit_tier(value: str | None) -> str:
    if not is_valid_audit_tier(value):
        raise ValueError("tier must be one of 'fast', 'smart', or 'deep_judgment'.")
    return normalize_audit_tier(value)


def _require_audit_mode_access(
    user: models.User | None,
    db: Session,
    *,
    requested_tier: str,
) -> None:
    if normalize_audit_tier(requested_tier) != "deep_judgment":
        return
    _require_plan_feature(
        user,
        feature_key="has_high_confidence_mode",
        detail=("High Confidence / Prescriptive Confidence mode requires " "Specialist or above."),
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _require_site_capacity(user: models.User, db: Session) -> None:
    max_sites = plan_validator.site_limit_for_user(user)
    if not isinstance(max_sites, int) or max_sites < 0:
        return

    sites_used = db.query(models.Site).filter(models.Site.user_id == user.id).count()
    if sites_used >= max_sites:
        raise HTTPException(
            status_code=403,
            detail=f"Site limit reached ({sites_used}/{max_sites}). Upgrade for more sites.",
        )


def _ensure_competitor_lite_audit_allowed(user: models.User, category: str | None) -> None:
    # SIGV2-1126: one rule, shared with the external API and the worker. Only
    # the shape of the refusal belongs to this surface.
    if competitor_lite_audit_is_denied(
        plan=resolve_subscription_plan(user),
        category=category,
    ):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Feature available in Specialist",
        )


def get_cache_ttl_seconds(tier: str, plan: str | None) -> int:
    plan_key = normalize_plan_type(plan)
    if plan_key and plan_key in CACHE_TTL_BY_PLAN:
        return CACHE_TTL_BY_PLAN[plan_key]
    derived_tier = PLAN_TO_TIER.get(plan_key) if plan_key else None
    effective_tier = (derived_tier or tier or "").lower()
    return CACHE_TTL_BY_TIER.get(effective_tier, CACHE_TTL_DEFAULT)


async def fetch_url_signature(url: str) -> dict[str, str]:
    from services.url_validation import safe_async_fetch

    response = await safe_async_fetch(url, timeout=10.0)
    content_hash = hashlib.sha256(response.content).hexdigest()
    headers = response.headers
    etag = headers.get("ETag") or headers.get("etag")
    last_modified = headers.get("Last-Modified") or headers.get("last-modified")
    signature = {"content_hash": content_hash}
    if etag:
        signature["etag"] = etag
    if last_modified:
        signature["last_modified"] = last_modified
    return signature


def _brand_truth_fingerprint(payload: dict | None) -> str | None:
    if not isinstance(payload, dict) or not payload:
        return None
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_audit_cache_subject(
    *,
    target_type: str,
    target_name: str | None,
    target_url: str | None,
    target_metadata: dict[str, Any] | None,
) -> str:
    if target_url:
        return target_url

    normalized_name = str(target_name or "brand-audit").strip().lower() or "brand-audit"
    metadata_fingerprint = _brand_truth_fingerprint(target_metadata)
    if metadata_fingerprint:
        return f"{target_type}:{normalized_name}:{metadata_fingerprint}"
    return f"{target_type}:{normalized_name}"


def is_cache_valid(signature: dict[str, str], metadata: dict) -> bool:
    if not signature or not metadata:
        return False
    if metadata.get("etag") and signature.get("etag"):
        return metadata["etag"] == signature["etag"]
    if metadata.get("content_hash") and signature.get("content_hash"):
        return metadata["content_hash"] == signature["content_hash"]
    if metadata.get("last_modified") and signature.get("last_modified"):
        return metadata["last_modified"] == signature["last_modified"]
    return False


def _extract_domain_from_url(url: str) -> str:
    parsed_url = urlparse(url)
    domain = (parsed_url.hostname or "").strip().lower()
    if not domain:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                INVALID_URL_FORMAT_KEY,
                INVALID_URL_FORMAT_DETAIL,
            ),
        )
    return domain


def _normalize_domain_for_project_matching(value: str | None) -> str | None:
    cleaned_value = (value or "").strip().lower()
    if not cleaned_value:
        return None

    candidate = cleaned_value if "://" in cleaned_value else f"https://{cleaned_value}"
    parsed_url = urlparse(candidate)
    normalized_domain = (parsed_url.hostname or "").strip().lower().rstrip(".")
    if not normalized_domain:
        return None
    if normalized_domain.startswith("www."):
        return normalized_domain[4:]
    return normalized_domain


# Removed _infer_project_id_for_audit_url because project_id is strictly required.


def _resolve_project_for_audit(
    *,
    project_id: int,
    user: models.User,
    db: Session,
) -> models.Project:
    access = resolve_project_access_service(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=False,
    )
    return access.project


# _frontend_base_url, _build_audit_cost_forecast are imported from
# services.audit_helpers (Item 24 unification).


def _resolve_audit_type_from_tier(tier: str | None) -> models.AuditType:
    normalized = normalize_audit_tier(tier)
    if normalized in {"smart", "deep_judgment"}:
        return models.AuditType.DEEP
    return models.AuditType.STANDARD


def _meter_synchronous_audit_scan(
    db: Session,
    *,
    user: models.User,
    project: models.Project,
    request_id: str,
    route,
    resolved_target_type: str,
    resolved_target_name: str | None,
    request_url: str | None,
    resolved_target_metadata: dict,
    estimated_credit_cost: int,
) -> str:
    """Consume one scan for a synchronous audit and record the counted row.

    SIGV2-1137: ``POST /api/v1/audit`` produces a real ``Audit`` and real
    provider cost, but it created no ``AuditJob``, and the customer-facing scan
    allowance counts ``AuditJob`` rows. A scan run through here was therefore
    invisible in the used count and nothing refused it at the limit, which is a
    billing bypass on the only limit customers are sold.

    The meter is not duplicated here. The scan is consumed through
    ``consume_scan_allowance`` and the run records the ``AuditJob`` row that
    allowance counts, declared as the customer's own scan, in the same
    transaction the allowance check locked the user row for. One accepted
    synchronous run is therefore exactly one consumed scan, and a refusal is
    raised before any provider work starts, so it costs nothing.

    ``scan_origin`` is keyed on who launched the scan, not on what it measures:
    the customer sent this request, including when they asked for a competitor
    lite audit through ``category``. That is the SIGV2-1129 asymmetry, where
    Signal's own benchmark refresh declares ``competitor_refresh`` instead and
    is never billed.
    """
    from services.scan_allowance_service import consume_scan_allowance

    consume_scan_allowance(db, user)

    job_id = str(uuid.uuid4())
    db.add(
        models.AuditJob(
            id=job_id,
            user_id=user.id,
            status=JOB_STATUS_RUNNING,
            audit_target_type=models.AuditTargetType(resolved_target_type),
            target_name=resolved_target_name,
            target_url=request_url or None,
            target_metadata=resolved_target_metadata,
            url=request_url or "",
            project_id=int(project.id) if project is not None else None,
            provider=route.provider,
            tier=route.execution_tier,
            estimated_credit_cost=estimated_credit_cost,
            request_id=request_id,
            # The run is already executing in this request, so the row starts at
            # "running" and _finalize_synchronous_audit_job closes it. No
            # heartbeat is written: the cron sweeper fails a running job whose
            # heartbeat went stale, and a long synchronous deep audit has no
            # worker to beat for it, so a heartbeat here would let the sweeper
            # fail (and email about) a run that is still in progress.
            scan_origin=models.SCAN_ORIGIN_CUSTOMER,
        )
    )
    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.error(
            "Failed to persist the metering record for synchronous audit %s: %s",
            request_id,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.save_audit_failed",
                "Failed to save audit to database.",
            ),
        )
    return job_id


def _finalize_synchronous_audit_job(
    db: Session, *, job_id: str, status: JobStatus, error: str | None = None
) -> None:
    """Close out the ``AuditJob`` row that metered a synchronous audit.

    Best effort on purpose: the scan is consumed and the report is already
    produced or already failed, so a bookkeeping write must not change the
    outcome the caller sees. Only the row's terminal status is at stake.
    """
    try:
        job = db.query(models.AuditJob).filter(models.AuditJob.id == job_id).first()
        if job is None:
            return
        job.status = status
        job.completed_at = datetime.now(timezone.utc)
        if error:
            job.error = error
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Failed to finalize the metering record for audit job %s", job_id)


@router.get("/api/v1/audit/tier-durations", response_model=TierDurationsResponse, tags=["Audit"])
def get_audit_tier_durations(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Measured scan duration per depth, derived from completed runs.

    SIGV2-1177. This is the only source of a per-depth duration in the product;
    neither side holds a constant any more. The read is a three-row table
    lookup, not an aggregation: the aggregate is computed by the hourly cron
    sweep, because it reads up to 90 days of ``audit_jobs`` rows per tier and
    does not move between two page loads.

    Authenticated: the figure is platform-wide operational data about throughput
    rather than anything tenant-specific, and the surface that states it is a
    signed-in dashboard page, so there is no reason to serve it anonymously.
    It is deliberately **not** tenant-scoped either, since a single workspace
    rarely has 20 runs at a depth and a per-tenant figure would publish far
    less often while telling the customer less.

    An empty ``tiers`` map is a valid, expected response: it means no depth has
    enough recorded runs yet, and the caller must then state no duration.
    """
    del user  # Authentication is the only thing the identity is used for.
    published = get_published_tier_durations(db)
    return TierDurationsResponse(
        statistic=TIER_DURATION_STATISTIC_ID,
        min_sample_size=TIER_DURATION_MIN_SAMPLE_SIZE,
        window_days=TIER_DURATION_WINDOW_DAYS,
        tiers={
            tier: TierDurationFigure(
                low_minutes=figure.low_minutes,
                high_minutes=figure.high_minutes,
                median_minutes=figure.median_minutes,
                sample_size=figure.sample_size,
                window_days=figure.window_days,
                computed_at=figure.computed_at,
            )
            for tier, figure in published.items()
        },
    )


@router.post("/api/v1/audit/estimate", response_model=AuditEstimateResponse, tags=["Audit"])
def estimate_audit_credit_usage(
    payload: AuditEstimateRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    _require_audit_mode_access(user, db, requested_tier=payload.tier)
    resolved_target_url = payload.resolved_target_url()
    resolved_target_name = payload.resolved_target_name() or resolved_target_url
    resolved_target_metadata = payload.resolved_target_metadata()
    gated_provider, gated_models = _strip_client_model_selection(
        provider=payload.provider,
        selected_models=payload.selected_models,
    )
    route = resolve_audit_route(
        tier=payload.tier,
        provider=gated_provider,
        selected_models=gated_models,
    )
    estimated_credit_cost, forecast_payload = _build_audit_cost_forecast(
        db=db,
        requested_tier=route.requested_tier,
        policy_version=get_credit_engine_policy_version(db),
        provider=route.provider,
        target_url=resolved_target_url,
        target_name=resolved_target_name,
        target_metadata=resolved_target_metadata,
        category=payload.category,
        market=payload.market,
        language=None,
        entities=payload.entities,
        selected_models=list(route.selected_models) or None,
        audit_data=payload.audit_data,
        serp_preview=payload.serp_preview,
    )
    consumes_credits = should_decrement_credits(user, route.requested_tier)
    from services.scan_allowance_service import scan_allowance_snapshot

    scan_snapshot = scan_allowance_snapshot(db, user)
    return {
        "consumes_scan": consumes_credits,
        "has_active_subscription": has_active_subscription(user),
        "scans_used": scan_snapshot.scans_used,
        "scans_remaining": scan_snapshot.scans_remaining,
        "reset_at": scan_snapshot.reset_at,
        "confidence": float(forecast_payload.get("confidence") or 0.0),
        "provider": route.provider,
        "tier": route.requested_tier,
        "tier_display": get_tier_display(route.requested_tier),
        "tier_class": route.tier_class,
        "execution_tier": route.execution_tier,
        "mode_label": route.product_label,
    }


@router.post("/api/v1/audit", response_model=CreateAuditResponse, tags=["Audit"])
async def create_audit(
    user: Annotated[models.User, Depends(get_current_user)],
    request: AuditRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    await enforce_authenticated_audit_limit(user, http_request)

    # Enforce trial limits before proceeding
    from services.trial_service import enforce_trial_audit_limit

    enforce_trial_audit_limit(user)

    cache_behavior = str(getattr(request, "cache_behavior", "default") or "default").strip().lower()
    if cache_behavior not in {"default", "bypass"}:
        cache_behavior = "default"
    cache_state = "bypass" if cache_behavior == "bypass" else "miss"
    http_request.state.audit_cache_state = cache_state
    resolved_target_type = request.audit_target_type
    request_url = request.resolved_target_url()
    resolved_target_name = request.resolved_target_name() or request_url
    resolved_target_metadata = request.resolved_target_metadata()
    cache_subject = _build_audit_cache_subject(
        target_type=resolved_target_type,
        target_name=resolved_target_name,
        target_url=request_url,
        target_metadata=resolved_target_metadata,
    )
    project = _resolve_project_for_audit(
        project_id=request.project_id,
        user=user,
        db=db,
    )
    resolved_project_id = int(project.id)
    # SIGV2-1126: X-Request-ID is client supplied, and the competitor prefixes
    # are internal markers, so a forged one is replaced with a server id.
    request_id = sanitize_client_request_id(
        http_request.state.request_id,
        fallback=f"audit:{uuid.uuid4()}",
    )
    subscription_plan = resolve_subscription_plan(user)
    _require_audit_mode_access(user, db, requested_tier=request.tier)
    gated_provider, gated_models = _strip_client_model_selection(
        provider=request.provider,
        selected_models=request.selected_models,
    )
    route = resolve_audit_route(
        tier=request.tier,
        provider=gated_provider,
        selected_models=gated_models,
    )
    active_policy_version = get_credit_engine_policy_version(db)
    estimated_credit_cost, forecast_payload = _build_audit_cost_forecast(
        db=db,
        requested_tier=route.requested_tier,
        policy_version=active_policy_version,
        provider=route.provider,
        target_url=request_url,
        target_name=resolved_target_name,
        target_metadata=resolved_target_metadata,
        category=request.category,
        market=request.market,
        language=request.language,
        entities=request.entities,
        selected_models=list(route.selected_models) or None,
        audit_data=request.audit_data,
        serp_preview=request.serp_preview,
    )
    _ensure_competitor_lite_audit_allowed(user, request.category)

    # --- Dedup check: prevent duplicate concurrent audits ---
    from services.audit_dedup_service import (
        build_dedup_key as _build_dedup_key,
        check_dedup as _check_dedup,
        set_dedup as _set_dedup,
        clear_dedup as _clear_dedup,
    )

    _dedup_key = _build_dedup_key(
        user_id=user.id,
        target_url=request_url,
        target_name=resolved_target_name,
        tier=route.requested_tier,
        project_id=resolved_project_id,
    )
    async with get_async_redis() as _dedup_rc:
        _existing_job_id = await _check_dedup(_dedup_rc, _dedup_key)
    if _existing_job_id:
        raise HTTPException(
            status_code=409,
            detail=translate_backend_message(
                "errors.audit_already_in_progress",
                "An audit for this target is already in progress.",
            ),
            headers={"X-Existing-Job-Id": _existing_job_id},
        )

    # SIGV2-1137: meter the scan here, after the dedup check so a duplicate
    # launch is rejected before it can consume one, and before any provider
    # work so a refusal at the limit costs nothing.
    sync_scan_job_id = _meter_synchronous_audit_scan(
        db,
        user=user,
        project=project,
        request_id=request_id,
        route=route,
        resolved_target_type=resolved_target_type,
        resolved_target_name=resolved_target_name,
        request_url=request_url,
        resolved_target_metadata=resolved_target_metadata,
        estimated_credit_cost=estimated_credit_cost,
    )
    user = db.merge(user)
    db.refresh(user)

    async with get_async_redis() as _dedup_rc2:
        await _set_dedup(_dedup_rc2, _dedup_key, request_id)

    # EPIC 11 / S11.1 quick-scan: the Pydantic validator and resolve_audit_route
    # normalise "lite"->"fast", so recover the raw tier from the request body and
    # thread it into perform_audit's requested_tier. perform_audit re-normalises
    # it internally for routing, so full-audit behaviour is unchanged. No-op when
    # the flag is OFF (production default).
    _perform_requested_tier = route.requested_tier
    if getattr(settings, "QUICK_SCAN_ENABLED", False):
        try:
            _raw_body = await http_request.json()
            _raw_tier_value = str((_raw_body or {}).get("tier") or "").strip().lower()
        except Exception:
            _raw_tier_value = ""
        if _raw_tier_value in {"lite", "quick"}:
            _perform_requested_tier = _raw_tier_value

    brand_truth_fingerprint = _brand_truth_fingerprint(request.brand_truth_payload)
    cache_context_parts: list[str] = []
    if brand_truth_fingerprint:
        cache_context_parts.append(f"brand_truth:{brand_truth_fingerprint}")
    if not request_url:
        cache_context_parts.append(f"target:{resolved_target_type}")
    if resolved_project_id is not None:
        cache_context_parts.append(f"project:{resolved_project_id}")
    cache_context_parts.append(f"requested_tier:{route.requested_tier}")
    if route.selected_models:
        cache_context_parts.append(f"models:{','.join(route.selected_models)}")
    cache_context_fingerprint = "|".join(cache_context_parts) if cache_context_parts else None
    cache_key = build_audit_cache_key(
        cache_subject,
        route.provider,
        route.execution_tier,
        cache_context_fingerprint,
    )
    cache_hit = False
    cached_report = None
    cached_score_breakdown: dict[str, float] | None = None
    cached_metadata: dict = {}
    url_signature: dict[str, str] | None = None
    credit_hold_request_id: str | None = None
    credit_hold_finalized = False
    audit_executed = False
    if cache_behavior != "bypass":
        async with get_async_redis() as redis_client:
            try:
                cached_payload = await redis_client.get(cache_key)
                if cached_payload:
                    cached_entry = json.loads(cached_payload)
                    cached_report = cached_entry.get("report")
                    cached_score_breakdown = _coerce_score_breakdown(cached_entry.get("scores"))
                    if cached_score_breakdown is None and cached_entry.get("avg_score") is not None:
                        fallback_avg = float(cached_entry.get("avg_score") or 0.0)
                        cached_score_breakdown = {
                            "seo": fallback_avg,
                            "geo": fallback_avg,
                            "aeo": fallback_avg,
                            "overall": fallback_avg,
                        }
                    cached_metadata = cached_entry.get("metadata", {}) or {}
                    if request_url:
                        try:
                            url_signature = await fetch_url_signature(request_url)
                        except Exception as exc:
                            logger.warning(
                                "Cache validation signature fetch failed for %s: %s",
                                request_url,
                                exc,
                            )
                        if url_signature and is_cache_valid(url_signature, cached_metadata):
                            cache_hit = True
                    else:
                        cache_hit = True
            except Exception as exc:
                logger.warning("Cache lookup failed for %s: %s", cache_subject, exc)

    try:
        if cache_hit and cached_report is not None:
            cache_state = "hit"
            http_request.state.audit_cache_state = cache_state
            full_report = cached_report
            score_breakdown = cached_score_breakdown or _extract_score_breakdown_from_report(
                full_report
            )
        else:
            if should_decrement_credits(user, route.requested_tier):
                # Project scan cap (SIGV2-1102): one scan per billable audit,
                # counted where the old per-project charge was taken so a
                # billable run always moves both counters or neither.
                from services.project_budget_service import enforce_project_scan_cap

                scan_result = enforce_project_scan_cap(db, project=project)
                if scan_result is not None and scan_result.threshold_events:
                    _queue_project_budget_notifications(
                        db=db,
                        project=project,
                        consumed_scans=scan_result.consumed_scans,
                        monthly_limit_scans=scan_result.monthly_limit_scans,
                        percent_consumed=scan_result.percent_consumed,
                        threshold_events=scan_result.threshold_events,
                    )
                pending_credit_hold_request_id = f"audit:{request_id}"
                acquire_credit_hold(
                    db,
                    user_id=user.id,
                    hold_amount=estimated_credit_cost,
                    request_id=pending_credit_hold_request_id,
                    reason_code="audit.main",
                    feature_key="audit.main",
                    tier_class=route.tier_class,
                    policy_version=active_policy_version,
                    workspace_id=project.workspace_id if project is not None else None,
                    project_id=resolved_project_id,
                    payload={
                        "estimated_credit_cost": estimated_credit_cost,
                        "cost_forecast": forecast_payload,
                        "http_request_id": request_id,
                        "target_url": request_url,
                    },
                )
                credit_hold_request_id = pending_credit_hold_request_id
                db.commit()
                user = db.merge(user)
                db.refresh(user)
            ai_service_enabled = is_ai_service_enabled(db)
            selected_model_routes = list(route.selected_models)
            if len(selected_model_routes) >= 2:

                async def _run_single_model(provider_name: str):
                    return await perform_audit(
                        url=request_url or "",
                        provider=provider_name,
                        tier=route.execution_tier,
                        requested_tier=_perform_requested_tier,
                        audit_target_type=resolved_target_type,
                        target_name=resolved_target_name,
                        target_metadata=resolved_target_metadata,
                        category=request.category,
                        market=request.market,
                        language=request.language,
                        entities=request.entities,
                        project_id=resolved_project_id,
                        scraper_service=scraper_service,
                        performance_service=performance_service,
                        network_service=network_service,
                        ai_client=ai_client,
                        ai_service_enabled=ai_service_enabled,
                        hallucination_service=hallucination_service,
                        competitor_discovery_service=competitor_discovery_service,
                        competitor_benchmark_service=competitor_benchmark_service,
                        user_plan=subscription_plan,
                        brand_truth_payload=request.brand_truth_payload,
                        db=db,
                        performance_snapshot_service=performance_snapshot_service,
                        predictive_intent_service=predictive_intent_service,
                    )

                results = await asyncio.gather(
                    *(_run_single_model(provider_name) for provider_name in selected_model_routes),
                    return_exceptions=True,
                )
                per_model_reports: list[dict[str, Any]] = []
                for provider_name, result in zip(selected_model_routes, results):
                    if isinstance(result, Exception):
                        logger.error(
                            "Model %s failed in multi-model sync audit for request %s: %s",
                            provider_name,
                            request_id,
                            result,
                        )
                    else:
                        report, scores = result
                        per_model_reports.append(
                            {"provider": provider_name, "analysis": report, "scores": scores}
                        )

                if not per_model_reports:
                    raise RuntimeError(
                        f"All {len(selected_model_routes)} models failed for audit request {request_id}"
                    )

                synthesized = await audit_consensus_ai_factory.synthesize_multi_model_results(
                    per_model_reports=per_model_reports,
                )
                full_report = (
                    synthesized
                    if isinstance(synthesized, dict)
                    else per_model_reports[0].get("analysis", {})
                )
                # Derive the persisted score breakdown from the synthesized
                # full_report (not the first model's raw scores) so the audit
                # table columns stay consistent with full_report["scores"].
                score_breakdown = canonical_score_breakdown(full_report)
                if isinstance(full_report, dict):
                    full_report["_multi_model_audit"] = {
                        "models_used": [report["provider"] for report in per_model_reports],
                        "models_failed": [
                            provider_name
                            for provider_name, result in zip(selected_model_routes, results)
                            if isinstance(result, Exception)
                        ],
                        "total_models": len(selected_model_routes),
                        "successful_models": len(per_model_reports),
                    }
            else:
                full_report, score_breakdown = await perform_audit(
                    url=request_url or "",
                    provider=route.provider,
                    tier=route.execution_tier,
                    requested_tier=_perform_requested_tier,
                    audit_target_type=resolved_target_type,
                    target_name=resolved_target_name,
                    target_metadata=resolved_target_metadata,
                    category=request.category,
                    market=request.market,
                    language=request.language,
                    entities=request.entities,
                    project_id=resolved_project_id,
                    scraper_service=scraper_service,
                    performance_service=performance_service,
                    network_service=network_service,
                    ai_client=ai_client,
                    ai_service_enabled=ai_service_enabled,
                    hallucination_service=hallucination_service,
                    competitor_discovery_service=competitor_discovery_service,
                    competitor_benchmark_service=competitor_benchmark_service,
                    user_plan=subscription_plan,
                    brand_truth_payload=request.brand_truth_payload,
                    db=db,
                    performance_snapshot_service=performance_snapshot_service,
                    predictive_intent_service=predictive_intent_service,
                )
            audit_executed = True
            try:
                if request_url and url_signature is None:
                    url_signature = await fetch_url_signature(request_url)
            except Exception as exc:
                logger.warning("Cache signature capture failed for %s: %s", request_url, exc)

            cache_metadata = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "url": request_url,
                "provider": route.provider,
                "tier": route.requested_tier,
                "requested_tier": route.requested_tier,
                "execution_tier": route.execution_tier,
                "content_hash": (url_signature or {}).get("content_hash"),
                "etag": (url_signature or {}).get("etag"),
                "last_modified": (url_signature or {}).get("last_modified"),
            }
            cache_entry = {
                "report": full_report,
                "scores": score_breakdown,
                "metadata": cache_metadata,
            }
            async with get_async_redis() as redis_client:
                try:
                    await redis_client.set(
                        cache_key,
                        json.dumps(cache_entry),
                        ex=get_cache_ttl_seconds(route.execution_tier, subscription_plan),
                    )
                except Exception as exc:
                    logger.warning("Failed to store cache entry for %s: %s", cache_subject, exc)

        full_report = to_canonical_audit_result(
            full_report if isinstance(full_report, dict) else {},
            audit_url=request_url or None,
            audit_target_type=resolved_target_type,
            target_name=resolved_target_name,
            target_url=request_url or None,
            target_metadata=resolved_target_metadata,
            created_at=datetime.now(timezone.utc),
            plan=subscription_plan,
        )
        full_report = _ensure_report_provider_tier(
            full_report,
            requested_provider=route.provider,
            requested_tier=route.requested_tier,
            execution_tier=route.execution_tier,
            mode_label=route.product_label,
        )

        metadata = (
            full_report.get("metadata") if isinstance(full_report.get("metadata"), dict) else {}
        )
        metadata["requested_tier"] = route.requested_tier
        metadata["mode_label"] = route.product_label
        metadata["tier_class"] = route.tier_class
        metadata["routing_feature_key"] = route.feature_key
        metadata["routing_mode"] = route.routing_mode
        if route.selected_models:
            metadata["selected_models"] = list(route.selected_models)
        if route.preferred_provider:
            metadata["routing_preferred_provider"] = route.preferred_provider
        if route.route_reason:
            metadata["routing_reason"] = route.route_reason
        if route.ignored_provider:
            metadata["legacy_provider_ignored"] = route.ignored_provider
        if route.ignored_selected_models:
            metadata["legacy_selected_models_ignored"] = list(route.ignored_selected_models)
        metadata["cache_behavior"] = cache_behavior
        metadata["cache_state"] = cache_state
        raw_query = (
            metadata.get("query")
            or metadata.get("prompt")
            or full_report.get("query")
            or request_url
            or resolved_target_name
        )
        resolved_query_category = classify_query_category(
            raw_query=raw_query,
            query_category=metadata.get("query_category") or metadata.get("queryCategory"),
        )
        metadata["query_category"] = resolved_query_category
        metadata["cost_forecast"] = forecast_payload
        full_report["metadata"] = metadata

        credit_resolution = resolve_audit_credit_resolution(
            full_report=full_report,
            estimated_credit_cost=estimated_credit_cost,
            default_provider=route.provider,
            default_tier=route.requested_tier,
            policy_version=active_policy_version,
            entities_count=len(request.entities or []),
            category=request.category,
            market=request.market,
            selected_models=route.selected_models,
        )
        metadata["billing_provider"] = credit_resolution.billed_provider
        metadata["billing_tier"] = credit_resolution.billed_tier
        metadata["estimated_credit_cost"] = credit_resolution.estimated_credit_cost
        metadata["billable_credit_cost"] = credit_resolution.billable_credit_cost
        if (
            credit_resolution.provider_changed
            or credit_resolution.tier_changed
            or credit_resolution.cost_changed
        ):
            metadata["credit_cost_reconciled"] = True
            metadata["credit_reconciliation_reason"] = (
                credit_resolution.resolution_reason
                or "final_provider_tier_differs_from_routed_estimate"
            )

        billable_outcome = _is_billable_audit_outcome(full_report)
        consumed_credit_cost = 0
        if credit_hold_request_id is not None:
            if billable_outcome:
                credit_hold = settle_credit_hold(
                    db,
                    request_id=credit_hold_request_id,
                    final_amount=credit_resolution.billable_credit_cost,
                    payload={
                        "billed_provider": credit_resolution.billed_provider,
                        "billed_tier": credit_resolution.billed_tier,
                        "requested_tier": route.requested_tier,
                    },
                )
                consumed_credit_cost = int(credit_hold.final_amount or 0)
                # Track trial audit usage
                from services.trial_service import increment_trial_audit_usage

                increment_trial_audit_usage(db, user)

                db.commit()
                db.refresh(user)
                credit_hold_finalized = True
            else:
                credit_hold = release_credit_hold(
                    db,
                    request_id=credit_hold_request_id,
                    refund_reason="non_billable_outcome",
                )
                db.commit()
                db.refresh(user)
                credit_hold_finalized = True

            metadata["credit_hold_id"] = int(credit_hold.id)
            metadata["credit_hold_status"] = str(credit_hold.status)
            metadata["locked_credit_cost"] = int(credit_hold.hold_amount or 0)
            metadata["consumed_credit_cost"] = int(credit_hold.final_amount or 0)
            metadata["released_credit_cost"] = int(credit_hold.refunded_amount or 0)
            hold_payload = dict(credit_hold.payload_json or {})
            if hold_payload.get("extra_charge_shortfall"):
                metadata["credit_hold_shortfall"] = int(hold_payload["extra_charge_shortfall"])
            full_report["metadata"] = metadata

        new_audit = None
        for attempt in range(1, DB_COMMIT_MAX_RETRIES + 1):
            try:
                site = None
                if request_url:
                    domain = _extract_domain_from_url(request_url)
                    site = (
                        db.query(models.Site)
                        .filter(models.Site.user_id == user.id, models.Site.domain == domain)
                        .first()
                    )
                    if site is None:
                        _require_site_capacity(user, db)
                        site = models.Site(user_id=user.id, domain=domain, display_name=domain)
                        db.add(site)
                        db.flush()

                new_audit = models.Audit(
                    user_id=user.id,
                    site_id=site.id if site is not None else None,
                    project_id=resolved_project_id,
                    # SIGV2-1121: this write path declares what it measures. An
                    # audit row that declares nothing is left unclassified and
                    # excluded from the project's own scores.
                    project_scope=declare_audit_project_scope(category=request.category),
                    audit_type=_resolve_audit_type_from_tier(route.tier_class),
                    audit_target_type=models.AuditTargetType(resolved_target_type),
                    target_name=resolved_target_name,
                    target_url=request_url or None,
                    target_metadata=resolved_target_metadata,
                    url=request_url or None,
                    geo_score=score_breakdown["geo"],
                    seo_score=score_breakdown["seo"],
                    aeo_score=score_breakdown["aeo"],
                    full_report=full_report,
                    intent=_normalize_intent_value(
                        (full_report.get("metadata") or {}).get("intent")
                        if isinstance(full_report, dict)
                        else None
                    ),
                    query_type=resolve_query_type(
                        query_type=(full_report.get("metadata") or {}).get("query_type")
                        if isinstance(full_report, dict)
                        else None,
                        intent=(full_report.get("metadata") or {}).get("intent")
                        if isinstance(full_report, dict)
                        else None,
                    ),
                    query_category=resolved_query_category,
                    request_id=request_id,
                )
                db.add(new_audit)
                db.flush()
                if site is not None:
                    site_entity_fact_service.replace_audit_facts(
                        db=db,
                        site_id=site.id,
                        audit_id=new_audit.id,
                        report=full_report if isinstance(full_report, dict) else {},
                        created_at=new_audit.created_at,
                    )
                db.commit()
                db.refresh(new_audit)
                db.refresh(user)
                try:
                    debate_trace_service.persist_trace_records(
                        db=db,
                        audit=new_audit,
                        trace_records=(
                            full_report.get("debate_trace_records")
                            if isinstance(full_report, dict)
                            else None
                        ),
                    )
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Debate trace persistence failed for audit %s (request_id=%s)",
                        new_audit.id,
                        request_id,
                    )
                    db.refresh(new_audit)
                if resolved_project_id is not None:
                    sync_project_tasks(db, project_id=resolved_project_id)
                break
            except HTTPException:
                db.rollback()
                raise
            except IntegrityError as exc:
                db.rollback()
                if attempt < DB_COMMIT_MAX_RETRIES and is_retryable_integrity_error(exc):
                    audit_db_retries_total.labels("api").inc()
                    logger.warning(
                        "Retrying create_audit commit for user %s after retryable integrity error (attempt=%s): %s",
                        user.id,
                        attempt,
                        exc,
                    )
                    continue
                logger.error("DB save failed for user %s due to integrity error: %s", user.id, exc)
                raise HTTPException(
                    status_code=500,
                    detail=translate_backend_message(
                        "errors.save_audit_failed",
                        "Failed to save audit to database.",
                    ),
                )
            except Exception as exc:
                db.rollback()
                logger.error("DB save failed for user %s: %s", user.id, exc)
                raise HTTPException(
                    status_code=500,
                    detail=translate_backend_message(
                        "errors.save_audit_failed",
                        "Failed to save audit to database.",
                    ),
                )
    except Exception as exc:
        if credit_hold_request_id and not credit_hold_finalized:
            if not audit_executed:
                try:
                    db.rollback()
                    release_credit_hold(
                        db,
                        request_id=credit_hold_request_id,
                        refund_reason=f"pre_execution_failure:{type(exc).__name__}",
                    )
                    db.commit()
                    db.refresh(user)
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Failed to release audit credit hold %s after execution failure.",
                        credit_hold_request_id,
                    )
            else:
                logger.warning(
                    "Audit %s failed after execution with pending credit hold %s still open.",
                    request_id,
                    credit_hold_request_id,
                )
        # SIGV2-1137: close the metering row. The scan stays consumed, matching
        # every other path: a failed outcome is not a free retry.
        try:
            db.rollback()
        except Exception:
            logger.debug("Rollback before finalizing the sync metering row failed", exc_info=True)
        _finalize_synchronous_audit_job(
            db,
            job_id=sync_scan_job_id,
            status=JOB_STATUS_FAILED,
            error=f"Synchronous audit failed: {type(exc).__name__}",
        )
        # Clear dedup key on failure too
        try:
            async with get_async_redis() as _dedup_rc_fail:
                await _clear_dedup(_dedup_rc_fail, _dedup_key)
        except Exception:
            logger.debug("Failed to clear dedup key after sync audit failure", exc_info=True)
        raise

    _finalize_synchronous_audit_job(db, job_id=sync_scan_job_id, status=JOB_STATUS_SUCCEEDED)

    # Clear dedup key, sync audit is complete
    try:
        async with get_async_redis() as _dedup_rc3:
            await _clear_dedup(_dedup_rc3, _dedup_key)
    except Exception:
        logger.debug("Failed to clear dedup key after sync audit", exc_info=True)

    if new_audit is None:
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.save_audit_failed",
                "Failed to save audit to database.",
            ),
        )

    if billable_outcome and consumed_credit_cost > 0:
        actual_cost = calculate_actual_audit_cost(
            report=full_report if isinstance(full_report, dict) else None,
            policy_version=active_policy_version,
            feature_key="audit.main",
        )
        shadow_policy_version = resolve_shadow_pricing_policy_version(
            db,
            active_policy_version=active_policy_version,
        )
        shadow_credits_charged = None
        debate_profile = (
            str((((full_report.get("metadata") or {}).get("ai_generation") or {}).get("profile")))
            .strip()
            .lower()
            if isinstance(full_report, dict)
            and isinstance(full_report.get("metadata"), dict)
            and isinstance((full_report.get("metadata") or {}).get("ai_generation"), dict)
            and ((full_report.get("metadata") or {}).get("ai_generation") or {}).get("profile")
            else None
        )
        if shadow_policy_version is not None:
            shadow_credits_charged = resolve_shadow_audit_credit_cost(
                full_report=full_report if isinstance(full_report, dict) else None,
                policy_version=shadow_policy_version,
                billed_provider=credit_resolution.billed_provider,
                billed_tier=credit_resolution.billed_tier,
                entities_count=len(request.entities or []),
                category=request.category,
                market=request.market,
                selected_models=list(route.selected_models),
            )

        try:
            record_ai_economics_ledger_entry(
                db,
                policy_version=active_policy_version,
                feature_key="audit.main",
                tier_class=route.tier_class,
                routing_profile=route.routing_mode,
                provider=actual_cost.provider or credit_resolution.billed_provider,
                model=actual_cost.model
                or str((full_report.get("metadata") or {}).get("model", "")),
                fallback_level=1
                if str(route.routing_mode or "").lower().endswith("fallback")
                else 0,
                input_tokens=actual_cost.input_tokens,
                output_tokens=actual_cost.output_tokens,
                token_cost_usd=actual_cost.token_cost_usd,
                infra_alloc_usd=actual_cost.infra_cost_usd,
                orchestration_usd=actual_cost.orchestration_cost_usd,
                retry_risk_usd=actual_cost.retry_risk_usd,
                credits_charged=max(0, int(consumed_credit_cost)),
                credit_unit_value_usd=get_pricing_policy(active_policy_version).credit_value_usd,
                request_id=request_id,
                workspace_id=project.workspace_id if project is not None else None,
                project_id=resolved_project_id,
                user_id=user.id,
                shadow_policy_version=shadow_policy_version,
                shadow_credits_charged=shadow_credits_charged,
                payload={
                    "billable_outcome": True,
                    "estimated_credit_cost": credit_resolution.estimated_credit_cost,
                    "billable_credit_cost": credit_resolution.billable_credit_cost,
                    "selected_models": list(route.selected_models),
                    "requested_tier": route.requested_tier,
                    "execution_tier": route.execution_tier,
                    "debate_profile": debate_profile,
                    "pricing_currency": actual_cost.pricing_currency,
                    "estimated_llm_cost_usd": forecast_payload.get("estimated_llm_cost_usd"),
                    "estimated_total_cogs_usd": forecast_payload.get("estimated_total_cogs_usd"),
                    "forecast_confidence": forecast_payload.get("confidence"),
                    "serp_density_score": (
                        forecast_payload.get("breakdown", {}).get("serp_density_score")
                        if isinstance(forecast_payload.get("breakdown"), dict)
                        else None
                    ),
                    "content_density_score": (
                        forecast_payload.get("breakdown", {}).get("content_density_score")
                        if isinstance(forecast_payload.get("breakdown"), dict)
                        else None
                    ),
                    "actual_token_cost_usd": float(actual_cost.token_cost_usd),
                    "actual_total_cogs_usd": float(actual_cost.total_cogs_usd),
                    "actual_usage_mode": actual_cost.usage_mode,
                    "actual_step_count": actual_cost.step_count,
                    "actual_steps": actual_cost.breakdown.get("steps", []),
                },
            )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception(
                "Failed to persist AI economics ledger entry for sync audit %s", request_id
            )

    return {
        "audit_id": new_audit.id,
        "report": full_report,
        "request_id": request_id,
    }


# ---------------------------------------------------------------------------
# Active audit jobs, allows frontend to discover running audits
# ---------------------------------------------------------------------------


class ActiveAuditJobSummary(BaseModel):
    job_id: str
    status: str
    audit_target_type: str = "website"
    target_name: str | None = None
    target_url: str | None = None
    tier: str | None = None
    tier_display: str | None = None
    started_at: str | None = None
    last_heartbeat: str | None = None
    stale: bool = False
    stale_reason: str | None = None
    project_id: int | None = None


class ActiveAuditJobsResponse(BaseModel):
    jobs: list[ActiveAuditJobSummary]


STALE_WARNING_SECONDS = 60
STALE_FAILURE_SECONDS = 300


@router.get("/api/v1/audit/jobs/active", response_model=ActiveAuditJobsResponse, tags=["Audit"])
async def list_active_audit_jobs(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the current user's non-terminal audit jobs (queued or running)."""

    rows = (
        db.query(models.AuditJob)
        .filter(
            models.AuditJob.user_id == user.id,
            models.AuditJob.status.in_(["queued", "running"]),
        )
        .order_by(models.AuditJob.created_at.desc())
        .limit(10)
        .all()
    )
    now = datetime.now(timezone.utc)
    jobs: list[ActiveAuditJobSummary] = []
    for row in rows:
        heartbeat = row.last_heartbeat or row.started_at
        # Normalize naive DB timestamps to UTC so the subtraction below doesn't
        # raise "can't subtract offset-naive and offset-aware datetimes".
        if heartbeat is not None and heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        stale = False
        stale_reason: str | None = None
        if heartbeat:
            elapsed = (now - heartbeat).total_seconds()
            if elapsed > STALE_FAILURE_SECONDS:
                stale = True
                stale_reason = "Audit appears to have failed, no heartbeat for 5 minutes"
            elif elapsed > STALE_WARNING_SECONDS:
                stale = True
                stale_reason = "Audit may be stalled, no heartbeat for 1 minute"
        jobs.append(
            ActiveAuditJobSummary(
                job_id=str(row.id),
                status=str(row.status or "queued"),
                audit_target_type=str(
                    getattr(row.audit_target_type, "value", row.audit_target_type) or "website"
                ),
                target_name=row.target_name,
                target_url=row.target_url or row.url,
                tier=row.tier,
                tier_display=get_tier_display(row.tier),
                started_at=row.started_at.isoformat() if row.started_at else None,
                last_heartbeat=heartbeat.isoformat() if heartbeat else None,
                stale=stale,
                stale_reason=stale_reason,
                project_id=row.project_id,
            )
        )
    return ActiveAuditJobsResponse(jobs=jobs)


@router.post("/api/v1/audit/jobs", response_model=AuditJobResponse, tags=["Audit"])
async def create_audit_job(
    user: Annotated[models.User, Depends(get_current_user)],
    request: AuditJobRequest,
    http_request: Request,
    db: Session = Depends(get_db),
):
    await enforce_authenticated_audit_limit(user, http_request)

    # Enforce trial limits before proceeding
    from services.trial_service import enforce_trial_audit_limit as _enforce_trial_limit

    _enforce_trial_limit(user)

    resolved_target_type = request.audit_target_type
    request_url = request.resolved_target_url()
    resolved_target_name = request.resolved_target_name() or request_url
    resolved_target_metadata = request.resolved_target_metadata()
    project = _resolve_project_for_audit(
        project_id=request.project_id,
        user=user,
        db=db,
    )
    resolved_project_id = int(project.id)
    _require_audit_mode_access(user, db, requested_tier=request.tier)
    gated_provider, gated_models = _strip_client_model_selection(
        provider=request.provider,
        selected_models=request.selected_models,
    )
    route = resolve_audit_route(
        tier=request.tier,
        provider=gated_provider,
        selected_models=gated_models,
    )
    active_policy_version = get_credit_engine_policy_version(db)
    estimated_credit_cost, forecast_payload = _build_audit_cost_forecast(
        db=db,
        requested_tier=route.requested_tier,
        policy_version=active_policy_version,
        provider=route.provider,
        target_url=request_url,
        target_name=resolved_target_name,
        target_metadata=resolved_target_metadata,
        category=request.category,
        market=request.market,
        language=request.language,
        entities=request.entities,
        selected_models=list(route.selected_models) or None,
        audit_data=request.audit_data,
        serp_preview=request.serp_preview,
    )
    _ensure_competitor_lite_audit_allowed(user, request.category)

    # --- Dedup check: prevent duplicate concurrent audits ---
    from services.audit_dedup_service import build_dedup_key, check_dedup, set_dedup

    dedup_key = build_dedup_key(
        user_id=user.id,
        target_url=request_url,
        target_name=resolved_target_name,
        tier=route.requested_tier,
        project_id=resolved_project_id,
    )
    async with get_async_redis() as dedup_rc:
        existing_job_id = await check_dedup(dedup_rc, dedup_key)
    if existing_job_id:
        raise HTTPException(
            status_code=409,
            detail=translate_backend_message(
                "errors.audit_already_in_progress",
                "An audit for this target is already in progress.",
            ),
            headers={"X-Existing-Job-Id": existing_job_id},
        )

    job_id = str(uuid.uuid4())
    # SIGV2-1126: both the body field and the X-Request-ID header are client
    # supplied, and the competitor prefixes are internal markers, so a forged
    # one is replaced with a server id.
    request_id = sanitize_client_request_id(
        request.request_id or http_request.state.request_id,
        fallback=f"audit-job:{job_id}",
    )

    # Consume one scan atomically with the job insert (SIGV2-1024). The user
    # row lock serialises concurrent launches for the final slot.
    from services.scan_allowance_service import consume_scan_allowance

    consume_scan_allowance(db, user)

    # Project scan cap (SIGV2-1102): manual runs block at the configured cap.
    from services.project_budget_service import enforce_project_scan_cap

    scan_result = enforce_project_scan_cap(db, project=project)
    if scan_result is not None and scan_result.threshold_events:
        _queue_project_budget_notifications(
            db=db,
            project=project,
            consumed_scans=scan_result.consumed_scans,
            monthly_limit_scans=scan_result.monthly_limit_scans,
            percent_consumed=scan_result.percent_consumed,
            threshold_events=scan_result.threshold_events,
        )

    # Persist job in DB for reliability sweeper
    db_job = models.AuditJob(
        id=job_id,
        user_id=user.id,
        status=JOB_STATUS_QUEUED,
        audit_target_type=models.AuditTargetType(resolved_target_type),
        target_name=resolved_target_name,
        target_url=request_url or None,
        target_metadata=resolved_target_metadata,
        url=request_url or "",
        project_id=resolved_project_id,
        provider=route.provider,
        tier=route.execution_tier,
        estimated_credit_cost=estimated_credit_cost,
        request_id=request_id,
        # SIGV2-1129: the customer launched this scan, so the job says so and
        # the allowance counts it positively. This holds even when they asked
        # for a competitor lite audit: they chose to spend a scan on it.
        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
    )
    db.add(db_job)
    log_context = {"job_id": job_id, "user.id": user.id, "request_id": request_id}
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        logger.error(
            "Failed to persist audit job due to integrity error",
            extra=log_context,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.save_audit_failed",
                "Failed to save audit to database.",
            ),
        )
    except ProgrammingError as exc:
        db.rollback()
        error_text = str(getattr(exc, "orig", exc)).lower()
        if "does not exist" in error_text or "undefined column" in error_text:
            logger.error(
                "Audit job persistence failed due to schema mismatch (missing relation/column)",
                extra=log_context,
                exc_info=exc,
            )
        else:
            logger.error(
                "Audit job persistence failed due to programming error",
                extra=log_context,
                exc_info=exc,
            )
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.save_audit_failed",
                "Failed to save audit to database.",
            ),
        )
    except Exception as exc:
        db.rollback()
        logger.error(
            "Failed to persist audit job",
            extra=log_context,
            exc_info=exc,
        )
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.save_audit_failed",
                "Failed to save audit to database.",
            ),
        )

    job_key = f"audit:job:{job_id}"
    payload = AuditJobPayload(
        job_id=job_id,
        request_id=request_id,
        user_id=user.id,
        url=request_url or "",
        audit_target_type=resolved_target_type,
        target_name=resolved_target_name,
        target_url=request_url or None,
        target_metadata=resolved_target_metadata,
        provider=route.provider,
        tier=route.execution_tier,
        requested_tier=route.requested_tier,
        mode_label=route.product_label,
        tier_class=route.tier_class,
        routing_feature_key=route.feature_key,
        routing_mode=route.routing_mode,
        routing_preferred_provider=route.preferred_provider,
        routing_reason=route.route_reason,
        project_id=resolved_project_id,
        estimated_credit_cost=estimated_credit_cost,
        cost_forecast=forecast_payload,
        brand_truth_payload=request.brand_truth_payload,
        category=request.category,
        market=request.market,
        language=request.language,
        entities=request.entities,
        selected_models=list(route.selected_models) or None,
        # SIGV2-1121: the enqueueing code declares the scope so the worker never
        # has to guess it.
        project_scope=declare_audit_project_scope(category=request.category),
    )
    async with get_async_redis() as redis_client:
        await redis_client.hset(
            job_key,
            mapping={
                "status": JOB_STATUS_QUEUED,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "user_id": str(user.id),
                "provider": route.provider,
                "tier": route.requested_tier,
                "tier_class": route.tier_class,
                "execution_tier": route.execution_tier,
                "mode_label": route.product_label,
                "routing_mode": route.routing_mode,
                "routing_preferred_provider": route.preferred_provider or "",
                "routing_reason": route.route_reason or "",
                "audit_target_type": resolved_target_type,
                "target_name": resolved_target_name or "",
                "target_url": request_url or "",
                "project_id": str(resolved_project_id) if resolved_project_id is not None else "",
                "estimated_cost_usd": str(forecast_payload.get("estimated_total_cogs_usd") or ""),
            },
        )
        await set_dedup(redis_client, dedup_key, job_id)
        await redis_client.rpush(
            resolve_queue_for_tier(route.execution_tier), json.dumps(payload.to_dict())
        )
        from services.job_ttl_dlq_service import set_ttl_queued

        await set_ttl_queued(redis_client, job_id)

    return {
        "job_id": job_id,
        "status": JOB_STATUS_QUEUED,
        "audit_target_type": resolved_target_type,
        "target_name": resolved_target_name,
        "target_url": request_url or None,
        "requested_tier": route.requested_tier,
        "tier_display": get_tier_display(route.requested_tier),
        "mode_label": route.product_label,
        "request_id": request_id,
    }


@router.get("/api/v1/audit/jobs/{job_id}", response_model=AuditJobStatusResponse, tags=["Audit"])
async def get_audit_job_status(
    job_id: str,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_job = (
        db.query(models.AuditJob)
        .filter(models.AuditJob.id == job_id, models.AuditJob.user_id == user.id)
        .first()
    )
    if db_job is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.job_not_found", "Job not found"),
        )

    job_key = f"audit:job:{job_id}"
    async with get_async_redis() as redis_client:
        job_data = await redis_client.hgetall(job_key)
        raw_stage_events: list[Any] = []
        lrange = getattr(redis_client, "lrange", None)
        if callable(lrange):
            try:
                raw_stage_events = await lrange(build_audit_job_events_key(job_id), 0, -1)
            except Exception:
                # No stage evidence available: stages report truthful
                # pending/unknown rather than fabricated completion (AC3).
                raw_stage_events = []

    stage_events: list[dict[str, Any]] = []
    for raw_event in raw_stage_events:
        try:
            parsed = json.loads(raw_event)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            stage_events.append(parsed)

    def _stages_for(status_value: Any) -> list[dict[str, Any]]:
        return project_audit_stage_states(stage_events, job_status=str(status_value or ""))

    def _coerce_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    if job_data:
        request_id = job_data.get("request_id") or db_job.request_id
        audit_id = _coerce_int(job_data.get("audit_id"))
        if audit_id is None and request_id:
            audit_row = (
                db.query(models.Audit.id)
                .filter(models.Audit.user_id == user.id, models.Audit.request_id == request_id)
                .order_by(models.Audit.created_at.desc())
                .first()
            )
            audit_id = int(audit_row.id) if audit_row else None

        resolved_target_type = _normalize_audit_target_type_value(
            job_data.get("audit_target_type") or db_job.audit_target_type
        )
        resolved_target_url = (
            str(job_data.get("target_url") or "").strip()
            or str(getattr(db_job, "target_url", "") or "").strip()
            or str(db_job.url or "").strip()
            or None
        )
        resolved_target_name = (
            str(job_data.get("target_name") or "").strip()
            or str(getattr(db_job, "target_name", "") or "").strip()
            or resolved_target_url
        )
        resolved_target_metadata = (
            dict(getattr(db_job, "target_metadata", {}))
            if isinstance(getattr(db_job, "target_metadata", None), dict)
            else {}
        )

        resolved_status = job_data.get("status", db_job.status or "queued")
        return {
            "job_id": job_id,
            "status": resolved_status,
            "stages": _stages_for(resolved_status),
            "audit_target_type": resolved_target_type,
            "target_name": resolved_target_name,
            "target_url": resolved_target_url,
            "target_metadata": resolved_target_metadata,
            "audit_id": audit_id,
            "error": job_data.get("error") or job_data.get("last_error") or db_job.error,
            "created_at": job_data.get("created_at")
            or (db_job.created_at.isoformat() if db_job.created_at else None),
            "started_at": job_data.get("started_at")
            or (db_job.started_at.isoformat() if db_job.started_at else None),
            "completed_at": job_data.get("completed_at")
            or (db_job.completed_at.isoformat() if db_job.completed_at else None),
            "request_id": request_id,
            "requested_tier": job_data.get("requested_tier"),
            "tier_display": get_tier_display(
                job_data.get("requested_tier") or job_data.get("tier")
            ),
        }

    request_id = db_job.request_id
    resolved_audit_id: int | None = None
    if request_id:
        audit_row = (
            db.query(models.Audit.id)
            .filter(models.Audit.user_id == user.id, models.Audit.request_id == request_id)
            .order_by(models.Audit.created_at.desc())
            .first()
        )
        resolved_audit_id = int(audit_row.id) if audit_row else None

    fallback_target_url = (
        str(getattr(db_job, "target_url", "") or "").strip()
        or str(db_job.url or "").strip()
        or None
    )
    fallback_target_name = (
        str(getattr(db_job, "target_name", "") or "").strip() or fallback_target_url
    )
    fallback_target_metadata = (
        dict(getattr(db_job, "target_metadata", {}))
        if isinstance(getattr(db_job, "target_metadata", None), dict)
        else {}
    )

    fallback_status = db_job.status or "queued"
    return {
        "job_id": job_id,
        "status": fallback_status,
        "stages": _stages_for(fallback_status),
        "audit_target_type": _normalize_audit_target_type_value(db_job.audit_target_type),
        "target_name": fallback_target_name,
        "target_url": fallback_target_url,
        "target_metadata": fallback_target_metadata,
        "audit_id": resolved_audit_id,
        "error": db_job.error,
        "created_at": db_job.created_at.isoformat() if db_job.created_at else None,
        "started_at": db_job.started_at.isoformat() if db_job.started_at else None,
        "completed_at": db_job.completed_at.isoformat() if db_job.completed_at else None,
        "request_id": request_id,
        "requested_tier": db_job.tier if hasattr(db_job, "tier") else None,
        "tier_display": get_tier_display(db_job.tier)
        if hasattr(db_job, "tier") and db_job.tier
        else None,
    }


@router.get("/api/v1/audit/jobs/{job_id}/events", tags=["Audit"])
async def stream_audit_job_events(
    job_id: str,
    request: Request,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_job = (
        db.query(models.AuditJob)
        .filter(models.AuditJob.id == job_id, models.AuditJob.user_id == user.id)
        .first()
    )
    if db_job is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.job_not_found", "Job not found"),
        )

    async def _event_stream():
        async with get_async_redis() as redis_client:
            events_key = build_audit_job_events_key(job_id)
            emitted_status_payload: str | None = None
            emitted_event_count = 0
            last_keep_alive = time.monotonic()

            while True:
                if await request.is_disconnected():
                    break

                status_payload = await get_audit_job_status(job_id=job_id, user=user, db=db)
                serialized_status = json.dumps(status_payload, sort_keys=True, default=str)
                if serialized_status != emitted_status_payload:
                    yield encode_sse_event("job_status", status_payload)
                    emitted_status_payload = serialized_status

                try:
                    raw_events = await redis_client.lrange(events_key, emitted_event_count, -1)
                except Exception:
                    # Events list expired or unavailable: status + stages still
                    # stream truthfully; nothing is fabricated (AC3).
                    raw_events = []
                for raw_event in raw_events:
                    try:
                        event_payload = json.loads(raw_event)
                    except json.JSONDecodeError:
                        continue
                    event_name = str(event_payload.get("type") or "message").strip() or "message"
                    yield encode_sse_event(event_name, event_payload)
                emitted_event_count += len(raw_events)

                if status_payload.get("status") in {"succeeded", "failed"}:
                    break

                now_monotonic = time.monotonic()
                if now_monotonic - last_keep_alive >= 15:
                    yield ": ping\n\n"
                    last_keep_alive = now_monotonic

                await asyncio.sleep(0.75)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _is_monitored_competitor_site(site: models.Site, user_id: int, db: Session) -> bool:
    return (
        db.query(models.site_competitors)
        .join(models.Site, models.Site.id == models.site_competitors.c.site_id)
        .filter(
            models.Site.user_id == user_id,
            models.site_competitors.c.competitor_site_id == site.id,
        )
        .first()
        is not None
    )


def _validate_geo_compare_site_access(
    site: models.Site | None, user: models.User, db: Session
) -> None:
    if not site:
        raise HTTPException(status_code=404, detail="Site not found.")

    if site.user_id == user.id:
        return

    if _is_monitored_competitor_site(site, user.id, db):
        return

    raise HTTPException(
        status_code=403,
        detail="You do not have access to this site. It must belong to your account or be a monitored competitor.",
    )


@router.get(
    "/api/v1/geo/compare",
    response_model=GeoBenchmarkCompareResponse,
    tags=["Audit"],
)
def compare_geo_sites(
    site_a_id: int,
    site_b_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    start_at: datetime | None = Query(default=None),
    end_at: datetime | None = Query(default=None),
):
    _require_plan_feature(
        user, feature_key="has_competitor_analysis", detail="Feature available in Specialist"
    )
    resolved_end = end_at or datetime.now(timezone.utc)
    resolved_start = start_at or (resolved_end - timedelta(days=30))
    if resolved_start >= resolved_end:
        raise HTTPException(status_code=400, detail="start_at must be earlier than end_at.")

    site_a = db.query(models.Site).filter(models.Site.id == site_a_id).first()
    site_b = db.query(models.Site).filter(models.Site.id == site_b_id).first()

    _validate_geo_compare_site_access(site_a, user, db)
    _validate_geo_compare_site_access(site_b, user, db)

    try:
        return geo_benchmark_service.compare_sites(
            db=db,
            site_a_id=site_a_id,
            site_b_id=site_b_id,
            user_id=user.id,
            start_at=resolved_start,
            end_at=resolved_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/v1/audits/{audit_id}", response_model=AuditHistoryEntry, tags=["Audit"])
def get_audit_record(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == audit_id, models.Audit.user_id == user.id)
        .first()
    )
    if not audit:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    status = _derive_audit_record_status(audit)
    is_archived = status in ("archived", "purged")

    # For archived audits, attempt lazy retrieval from object storage
    normalized_report = None
    if is_archived and audit.report_archive_uri:
        from services.audit_archive_service import restore_archived_report

        normalized_report = restore_archived_report(db, audit)
    elif audit.full_report is not None:
        normalized_report = normalize_persisted_full_report(audit, db)

    # Response-time additive metadata views for the archived raw-report branch;
    # the normalized branch already gets them via build_normalized_audit_report.
    # Idempotent and not persisted; canonical contract untouched. Each attach is
    # isolated: a failure in one view is logged and the response continues with the
    # remaining views applied (one view can't 500 the whole audit).
    #   - aio: AIO roll-up (AEO+GEO).
    #   - advisor: deterministic Advisor plan.
    #   - search_types: the 5 canonical search types, measured per-type visibility
    #     and answer ratio only, unmeasured where there is no measurement.
    # The advisor attach runs on BOTH branches (normalized + archived); route it
    # through the same dismissed-fingerprint filter as
    # normalize_persisted_full_report so a dismissed action cannot resurface.
    _dismissed_fingerprints = dismissed_fingerprints(db, getattr(audit, "project_id", None))
    _attaches: list[tuple[str, Any]] = [
        ("aio", lambda r: attach_aio_view(r)),
        ("advisor", lambda r: attach_advisor_view(r, dismissed=_dismissed_fingerprints)),
    ]
    # search_types requires a DB read (compute_search_type_measurements). The
    # non-archived branch already computed AND attached it via
    # normalize_persisted_full_report -> build_normalized_audit_report; reuse that
    # result instead of recomputing. Only the archived branch (restore_archived_report
    # omits these additive views) needs the compute here -> one DB read per request,
    # identical figures either way.
    _has_search_types = (
        isinstance(normalized_report, dict)
        and isinstance(normalized_report.get("metadata"), dict)
        and "search_types" in normalized_report["metadata"]
    )
    if not _has_search_types:
        _archived_search_type_measurements = compute_search_type_measurements(
            db, getattr(audit, "project_id", None)
        )
        _attaches.append(
            (
                "search_types",
                lambda r: attach_search_types(r, measurements=_archived_search_type_measurements),
            )
        )
    for _label, _attach in _attaches:
        try:
            normalized_report = _attach(normalized_report)
        except Exception:
            logger.exception("metadata attach failed: %s", _label)

    effective_scores = resolve_audit_effective_scores(audit, canonical_report=normalized_report)

    return {
        "id": audit.id,
        "url": _resolve_legacy_audit_url(audit),
        "audit_target_type": _resolve_audit_target_type(audit),
        "target_name": _resolve_audit_target_name(audit),
        "target_url": _resolve_audit_target_url(audit),
        "target_metadata": _resolve_audit_target_metadata(audit),
        "geo_score": effective_scores["geo"],
        "seo_score": effective_scores["seo"],
        "aeo_score": effective_scores["aeo"],
        "created_at": audit.created_at.isoformat() if audit.created_at else "",
        "status": status,
        "intent": (
            normalized_report.get("metadata", {}).get("intent")
            if isinstance(normalized_report, dict)
            and isinstance(normalized_report.get("metadata"), dict)
            else None
        ),
        "full_report": normalized_report,
        "is_archived": is_archived,
        "is_pinned": bool(getattr(audit, "is_pinned", False)),
    }


class AdvisorChatMessage(BaseModel):
    role: Literal["user", "advisor", "assistant"] = "user"
    content: str = Field(min_length=1, max_length=4000)


class AdvisorChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[AdvisorChatMessage] | None = Field(default=None, max_length=20)


# Hard timeout guard for the chat endpoint (AGENTS §8.7 Chat API = 5s).
_ADVISOR_CHAT_TIMEOUT_SECONDS = 5.0

# How many recent persisted turns to replay as prior-turn context. Bounded so
# the model prompt stays within the token budget (the service further trims).
_ADVISOR_CHAT_HISTORY_TURNS = 10

_ADVISOR_CHAT_FALLBACK_REPLY = "I couldn't analyse that right now. Please try again in a moment."

# SIGV2-1251: the advisor LLM call is synchronous (boto3 ``converse``), so it
# runs on a worker thread. It used to get a fresh
# ``ThreadPoolExecutor(max_workers=1)`` per request, used as a context manager,
# and ``__exit__`` calls ``shutdown(wait=True)``, so the request blocked until
# the call finished no matter what ``future.result(timeout=...)`` said. The 5s
# guard was therefore decorative and repeated timeouts piled up threads.
#
# Now: one shared, bounded executor for the whole process, plus a non-blocking
# capacity gate. A thread cannot be force-killed, so the honest guarantee here
# is that in-flight advisor calls are bounded, never unbounded: at most
# ``_ADVISOR_CHAT_MAX_CONCURRENCY`` run at once and excess requests are refused
# outright instead of queueing behind stuck ones. What actually ends an
# abandoned call is the socket read timeout ``advisor_chat_service`` sets on the
# Bedrock invocation.
_ADVISOR_CHAT_MAX_CONCURRENCY = max(1, int(os.getenv("ADVISOR_CHAT_MAX_CONCURRENCY") or 8))

_advisor_chat_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=_ADVISOR_CHAT_MAX_CONCURRENCY,
    thread_name_prefix="advisor-chat",
)

# Released by the worker thread itself, so a timed-out call keeps holding its
# slot until the underlying invocation really ends. That is what stops threads
# accumulating across repeated timeouts.
_advisor_chat_slots = threading.BoundedSemaphore(_ADVISOR_CHAT_MAX_CONCURRENCY)


class AdvisorChatCapacityError(RuntimeError):
    """Every advisor-chat slot is occupied by an in-flight call."""


def _run_advisor_chat_with_timeout(
    report: dict,
    message: str,
    history: list,
) -> dict:
    """Run the sync advisor call under a wall-clock guard, bounded and queue-free.

    Raises ``TimeoutError`` when the guard expires and
    ``AdvisorChatCapacityError`` when no slot is free. Never blocks on executor
    shutdown.
    """
    if not _advisor_chat_slots.acquire(blocking=False):
        raise AdvisorChatCapacityError(
            f"all {_ADVISOR_CHAT_MAX_CONCURRENCY} advisor-chat slots are busy"
        )

    def _task() -> dict:
        try:
            return advisor_chat_service.answer(report, message, history)
        finally:
            _advisor_chat_slots.release()

    try:
        future = _advisor_chat_executor.submit(_task)
    except Exception:
        # The task never ran, so nothing will release the slot for us.
        _advisor_chat_slots.release()
        raise

    # On timeout the future is abandoned deliberately: cancel() cannot stop a
    # call that is already running, and we must not wait for it.
    return future.result(timeout=_ADVISOR_CHAT_TIMEOUT_SECONDS)


def _advisor_chat_result_or_fallback(
    report: dict,
    message: str,
    history: list,
    audit_id: int,
) -> dict:
    """Advisor reply, degrading to a safe fallback on timeout/capacity/error."""
    result: dict | None = None
    try:
        result = _run_advisor_chat_with_timeout(report, message, history)
    except AdvisorChatCapacityError:
        logger.warning(
            "Advisor chat refused for audit %s: all %s slots busy",
            audit_id,
            _ADVISOR_CHAT_MAX_CONCURRENCY,
        )
    except TimeoutError:
        logger.warning("Advisor chat timed out for audit %s", audit_id)
    except Exception:
        logger.exception("Advisor chat failed for audit %s", audit_id)

    if not isinstance(result, dict):
        return {"reply": _ADVISOR_CHAT_FALLBACK_REPLY, "citations": []}
    return result


@router.post("/api/v1/audits/{audit_id}/advisor-chat", tags=["Audit"])
def advisor_chat(
    audit_id: int,
    payload: AdvisorChatRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Audit-grounded conversational advisor (Phase 8).

    Answers a question strictly from THIS audit's evidence and abstains when the
    evidence does not support an answer. Tier-gated (Standard+); enforces audit
    ownership; the LLM call happens only inside ``advisor_chat_service`` (never
    here). A 5s hard timeout guard degrades to a safe fallback reply.
    """
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )
    # Ownership / tenant isolation: only the audit owner may chat about it.
    if audit.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this audit.")

    # Tier gate: the grounded Advisor chat is a Standard+ capability.
    _require_plan_feature(
        user,
        feature_key="has_advisor_recommendations",
        detail="Upgrade to Standard or above to chat with the audit Advisor.",
    )

    # Serve the Advisor plan through the same dismissal-filtered accessor as
    # every other consumer (attach_advisor_view recomputes the plan; a shallow
    # copy keeps the persisted payload untouched).
    report = dict(audit.full_report) if isinstance(audit.full_report, dict) else {}
    report = attach_advisor_view(
        report,
        dismissed=dismissed_fingerprints(db, getattr(audit, "project_id", None)),
    )

    # PRIOR-TURN CONTEXT: load the persisted history for THIS (audit, user) and
    # replay it (bounded to the most recent turns, within token budget). The
    # client-supplied ``payload.history`` is ignored here — the server is the
    # source of truth, so a client can't smuggle a forged transcript. History is
    # passed as role-tagged data; advisor_chat_service treats each turn as data,
    # never as instructions (prompt-injection defence preserved).
    history = advisor_chat_history_service.list_messages(
        db, audit_id, user.id, limit=_ADVISOR_CHAT_HISTORY_TURNS
    )

    # Run the (sync) ai-service call under a hard timeout guard on the shared
    # bounded executor. On timeout/capacity/error we return a safe fallback
    # rather than hanging the request or piling up threads (SIGV2-1251).
    result = _advisor_chat_result_or_fallback(report, payload.message, history, audit_id)

    reply = str(result.get("reply") or _ADVISOR_CHAT_FALLBACK_REPLY)
    citations = list(result.get("citations") or [])

    # Persist BOTH turns so follow-ups stay consistent. We reach here only after
    # ownership + plan gating passed, so persistence never happens on
    # auth/gating failures. Even on a model error/abstention/timeout we persist
    # the user turn + the (fallback) reply so the stored thread matches the UI.
    try:
        advisor_chat_history_service.append_message(db, audit_id, user.id, "user", payload.message)
        advisor_chat_history_service.append_message(
            db, audit_id, user.id, "assistant", reply, citations=citations
        )
    except Exception:
        logger.exception("Failed to persist advisor chat history for audit %s", audit_id)

    return {"reply": reply, "citations": citations}


@router.get("/api/v1/audits/{audit_id}/advisor-chat/history", tags=["Audit"])
def advisor_chat_history(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the persisted Advisor-chat turns for THIS (audit, user).

    Same gating as the chat endpoint: audit ownership (403) + the
    ``has_advisor_recommendations`` plan capability (402). Lets the UI hydrate
    the transcript on mount so multi-turn context survives a reload.
    """
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )
    if audit.user_id != user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this audit.")

    _require_plan_feature(
        user,
        feature_key="has_advisor_recommendations",
        detail="Upgrade to Standard or above to chat with the audit Advisor.",
    )

    messages = advisor_chat_history_service.list_messages(
        db, audit_id, user.id, limit=_ADVISOR_CHAT_HISTORY_TURNS * 2
    )
    return {"messages": messages}


@router.get("/api/v1/audits/{audit_id}/shared", tags=["Audit"])
def get_shared_audit_record(
    audit_id: int,
    token: str = Query(..., description="Share token required for access"),
    db: Session = Depends(get_db),
):
    """Public read-only access to an audit for share links. Requires valid share token."""
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found.")

    # SIGV2-1250: constant-time comparison plus the token's own deadline, both
    # owned by services.audit_share_token_service. A token minted before that
    # change has no recorded deadline and stays valid until it is rotated.
    if not audit_share_tokens.share_token_matches(audit, token):
        raise HTTPException(status_code=403, detail="Invalid or expired share link.")

    if audit.full_report is None:
        raise HTTPException(status_code=404, detail="Audit report not available.")

    normalized_report = normalize_persisted_full_report(audit, db)
    effective_scores = resolve_audit_effective_scores(audit, canonical_report=normalized_report)

    return {
        "id": audit.id,
        "url": _resolve_legacy_audit_url(audit),
        "audit_target_type": _resolve_audit_target_type(audit),
        "target_name": _resolve_audit_target_name(audit),
        "target_url": _resolve_audit_target_url(audit),
        "target_metadata": _resolve_audit_target_metadata(audit),
        "geo_score": effective_scores["geo"],
        "seo_score": effective_scores["seo"],
        "aeo_score": effective_scores["aeo"],
        "created_at": audit.created_at.isoformat() if audit.created_at else "",
        "full_report": normalized_report,
    }


@router.post("/api/v1/audits/{audit_id}/share", tags=["Audit"])
def create_audit_share_link(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Generate a share token for an audit owned by the current user.

    Asking twice while the link is still valid returns the same token. An
    absent or expired token is replaced (SIGV2-1250), so an expired link is
    re-issued here rather than resurrected.
    """
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == audit_id, models.Audit.user_id == user.id)
        .first()
    )
    if not audit:
        raise HTTPException(status_code=404, detail="Audit not found.")

    previous_token = audit.share_token
    token = audit_share_tokens.issue_share_token(audit)
    if token != previous_token:
        db.commit()
        db.refresh(audit)

    expires_at = audit.share_token_expires_at
    return {
        "share_token": audit.share_token,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.post("/api/v1/audits/{audit_id}/pin", tags=["Audit"])
def pin_audit_record(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Pin an audit to exempt it from data retention archival."""
    from services.audit_archive_service import pin_audit

    if not pin_audit(db, audit_id, user.id):
        raise HTTPException(status_code=404, detail="Audit not found.")
    db.commit()
    return {"status": "pinned", "audit_id": audit_id}


@router.delete("/api/v1/audits/{audit_id}/pin", tags=["Audit"])
def unpin_audit_record(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Unpin an audit, allowing normal archival."""
    from services.audit_archive_service import unpin_audit

    if not unpin_audit(db, audit_id, user.id):
        raise HTTPException(status_code=404, detail="Audit not found.")
    db.commit()
    return {"status": "unpinned", "audit_id": audit_id}


@router.get("/api/v1/audit/{audit_id}/comparison", tags=["Audit"])
def get_audit_comparison(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return score delta comparison data for an audit vs its predecessor."""
    from services.audit_comparison_service import get_audit_comparison as _get_comparison

    result = _get_comparison(db, audit_id, user.id)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )
    return result


# ── Claim Feedback Endpoints (AEX-26) ──────────────────────────────


def _authorize_claim_feedback_audit(
    db: Session,
    *,
    audit_id: int,
    user: models.User,
    require_write: bool,
) -> models.Audit:
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")

    if audit.project_id is None:
        if audit.user_id != user.id:
            raise HTTPException(status_code=404, detail="Audit not found.")
        return audit

    try:
        access = resolve_project_access_service(
            db,
            user=user,
            project_id=audit.project_id,
            allow_client_readonly=not require_write,
        )
        if require_write:
            require_workspace_write_access(access.role)
    except HTTPException as exc:
        if exc.status_code in {403, 404}:
            raise HTTPException(status_code=404, detail="Audit not found.") from exc
        raise
    return audit


class ClaimFeedbackRequest(BaseModel):
    claim_key: str = Field(..., min_length=1, max_length=300)
    claim_text: str = Field(..., min_length=1, max_length=2000)
    claim_category: str | None = Field(None, max_length=120)
    feedback_type: Literal["agree", "disagree", "fixed"]
    feedback_text: str | None = Field(None, max_length=1000)


@router.post("/api/v1/audits/{audit_id}/feedback", tags=["Claim Feedback"])
def submit_claim_feedback(
    audit_id: int,
    body: ClaimFeedbackRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Submit or update feedback for a specific finding in an audit report."""
    from services.claim_feedback_service import upsert_feedback

    _authorize_claim_feedback_audit(
        db,
        audit_id=audit_id,
        user=user,
        require_write=True,
    )

    fb = upsert_feedback(
        db,
        audit_id=audit_id,
        user_id=user.id,
        claim_key=body.claim_key,
        claim_text=body.claim_text,
        claim_category=body.claim_category,
        feedback_type=body.feedback_type,
        feedback_text=body.feedback_text,
    )
    db.commit()
    db.refresh(fb)
    return {
        "id": fb.id,
        "audit_id": fb.audit_id,
        "claim_key": fb.claim_key,
        "feedback_type": fb.feedback_type.value,
        "feedback_text": fb.feedback_text,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }


@router.get("/api/v1/audits/{audit_id}/feedback", tags=["Claim Feedback"])
def list_claim_feedback(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    mine_only: bool = Query(False),
):
    """List feedback for an audit. Use mine_only=true to see only your own."""
    from services.claim_feedback_service import get_feedback_for_audit

    _authorize_claim_feedback_audit(
        db,
        audit_id=audit_id,
        user=user,
        require_write=False,
    )

    items = get_feedback_for_audit(
        db,
        audit_id=audit_id,
        user_id=user.id if mine_only else None,
    )
    return [
        {
            "id": fb.id,
            "audit_id": fb.audit_id,
            "user_id": fb.user_id,
            "claim_key": fb.claim_key,
            "claim_text": fb.claim_text,
            "claim_category": fb.claim_category,
            "feedback_type": fb.feedback_type.value,
            "feedback_text": fb.feedback_text,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        }
        for fb in items
    ]


@router.get("/api/v1/audits/{audit_id}/feedback/summary", tags=["Claim Feedback"])
def get_claim_feedback_summary(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get aggregated feedback counts per claim for an audit."""
    from services.claim_feedback_service import get_feedback_summary_for_audit

    _authorize_claim_feedback_audit(
        db,
        audit_id=audit_id,
        user=user,
        require_write=False,
    )
    return get_feedback_summary_for_audit(db, audit_id=audit_id)


@router.delete("/api/v1/audits/{audit_id}/feedback/{feedback_id}", tags=["Claim Feedback"])
def delete_claim_feedback(
    audit_id: int,
    feedback_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Delete your own feedback entry."""
    from services.claim_feedback_service import delete_feedback

    _authorize_claim_feedback_audit(
        db,
        audit_id=audit_id,
        user=user,
        require_write=False,
    )
    feedback = (
        db.query(models.ClaimFeedback)
        .filter(
            models.ClaimFeedback.id == feedback_id,
            models.ClaimFeedback.audit_id == audit_id,
            models.ClaimFeedback.user_id == user.id,
        )
        .first()
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found or access denied.")

    if not delete_feedback(db, feedback_id=feedback_id, user_id=user.id):
        raise HTTPException(status_code=404, detail="Feedback not found or access denied.")
    db.commit()
    return {"status": "deleted"}


@router.get("/api/v1/audits/{audit_id}/feedback/previous", tags=["Claim Feedback"])
def get_previous_audit_feedback(
    audit_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Get feedback from previous audits of the same URL, for re-audit context."""
    from services.claim_feedback_service import get_previous_feedback_for_url

    audit = _authorize_claim_feedback_audit(
        db,
        audit_id=audit_id,
        user=user,
        require_write=False,
    )

    return get_previous_feedback_for_url(
        db,
        url=audit.url,
        current_audit_id=audit_id,
        project_id=audit.project_id,
    )


async def _build_executive_summary_text(
    *,
    template_type: str,
    audits: list[models.Audit],
    language: str = "en",
) -> str:
    return await build_report_summary_text_service(
        template_type=template_type,
        audits=audits,
        language=language,
    )


def _apply_complex_report_sections(
    full_report: dict[str, Any], sections: list[str]
) -> dict[str, Any]:
    if not isinstance(full_report, dict):
        return {}

    section_key_map = {
        "overview": ["metadata", "summary", "analysis", "scores"],
        "geo": ["geo", "geo_analysis"],
        "seo": ["seo", "seo_analysis"],
        "aeo": ["aeo", "answerability"],
        "cwv": ["performance", "core_web_vitals"],
        "ai": ["ai_strategic_insights", "ai", "analysis"],
        "competitors": ["competitors", "competitive_analysis", "benchmark"],
    }

    filtered: dict[str, Any] = {}
    for section in sections:
        for report_key in section_key_map.get(section, []):
            if report_key in full_report:
                filtered[report_key] = full_report[report_key]

    return filtered


def _normalize_comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _filter_audits_by_interval(
    audits: list[models.Audit],
    *,
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[models.Audit]:
    if date_from is None and date_to is None:
        return audits

    normalized_from = _normalize_comparable_datetime(date_from) if date_from is not None else None
    normalized_to = _normalize_comparable_datetime(date_to) if date_to is not None else None

    filtered: list[models.Audit] = []
    for audit in audits:
        created_at = audit.created_at
        if created_at is None:
            continue
        normalized_created = _normalize_comparable_datetime(created_at)
        if normalized_from is not None and normalized_created < normalized_from:
            continue
        if normalized_to is not None and normalized_created > normalized_to:
            continue
        filtered.append(audit)
    return filtered


def _select_latest_audit_for_site(
    audits: list[models.Audit],
    *,
    site_id: int,
    date_from: datetime | None,
    date_to: datetime | None,
) -> models.Audit | None:
    site_audits = [audit for audit in audits if audit.site_id == site_id]
    in_interval = _filter_audits_by_interval(site_audits, date_from=date_from, date_to=date_to)
    if not in_interval:
        return None
    return max(in_interval, key=lambda audit: audit.created_at or datetime.min)


def _load_audits_for_sites(
    db: Session,
    *,
    user_id: int,
    site_ids: Sequence[int],
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[models.Audit]:
    normalized_site_ids = [int(site_id) for site_id in dict.fromkeys(site_ids) if int(site_id) > 0]
    if not normalized_site_ids:
        return []

    audits = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user_id, models.Audit.site_id.in_(normalized_site_ids))
        .order_by(models.Audit.created_at.asc(), models.Audit.id.asc())
        .all()
    )
    return _filter_audits_by_interval(audits, date_from=date_from, date_to=date_to)


def _resolve_complex_report_manifest(
    *,
    template_type: str,
    options: ComplexReportOptions,
    branding_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_export_manifest(
        explicit_report_kind=getattr(options, "report_kind", None),
        explicit_branding_mode=getattr(options, "branding_mode", None),
        explicit_competitor_mode=getattr(options, "competitor_mode", None),
        explicit_report_type=getattr(options, "report_type", None),
        template_type=template_type,
        hide_credit_cost=getattr(options, "hide_credit_cost", True),
        agency_branding_data=branding_config,
    )


def _resolve_white_label_report_manifest(
    request: WhiteLabelReportRequest,
    *,
    branding_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return resolve_export_manifest(
        explicit_report_kind=request.report_kind,
        explicit_branding_mode=request.branding_mode,
        explicit_competitor_mode=request.competitor_mode,
        explicit_report_type=request.report_type,
        template_type="Executive",
        hide_credit_cost=request.hide_credit_cost,
        agency_branding_data=branding_config,
    )


def _require_report_export_access(
    user: models.User | None,
    *,
    export_manifest: Mapping[str, Any],
) -> None:
    unmet = first_unmet_report_export_requirement(user, export_manifest, validator=plan_validator)
    if unmet is not None:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=unmet.detail)


@router.post(
    "/api/v1/reports/generate-complex", response_model=ComplexReportResponse, tags=["Reports"]
)
async def generate_complex_report(
    payload: ComplexReportRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    resolved_export_manifest = _resolve_complex_report_manifest(
        template_type=payload.template_type,
        options=payload.report_options,
    )
    report_kind = str(resolved_export_manifest.get("report_kind") or "standard").strip().lower()
    competitor_mode = str(resolved_export_manifest.get("competitor_mode") or "").strip().lower()
    _require_report_export_access(user, export_manifest=resolved_export_manifest)

    manual_audits = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user.id, models.Audit.id.in_(payload.audit_ids))
        .order_by(models.Audit.created_at.asc())
        .all()
    )
    if not manual_audits:
        raise HTTPException(status_code=404, detail="No matching audits found for this user.")

    options = payload.report_options
    reference_audit = manual_audits[-1]
    persisted_branding = _resolve_user_branding_defaults(db, user)

    if report_kind == "project":
        if reference_audit.project_id is None or reference_audit.site_id is None:
            raise HTTPException(
                status_code=400,
                detail="Project report exports require a project-backed, site-linked audit.",
            )
    if report_kind == "financial" and reference_audit.project_id is None:
        raise HTTPException(
            status_code=400,
            detail="Financial report exports require a project-backed audit.",
        )

    site_interval_audits: list[models.Audit] = []
    effective_site_id = payload.site_id
    if effective_site_id is None and (
        report_kind == "project" or (report_kind == "competitors" and competitor_mode == "trend")
    ):
        effective_site_id = reference_audit.site_id

    if options.mode == "aggregated" or effective_site_id is not None or report_kind == "project":
        if effective_site_id is None:
            raise HTTPException(status_code=400, detail="site_id is required for aggregated mode.")
        site_interval_audits = (
            db.query(models.Audit)
            .filter(models.Audit.user_id == user.id, models.Audit.site_id == effective_site_id)
            .order_by(models.Audit.created_at.asc())
            .all()
        )
        site_interval_audits = _filter_audits_by_interval(
            site_interval_audits,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )

    selected_audits = manual_audits
    if options.mode == "aggregated":
        selected_audits = site_interval_audits
        if not selected_audits:
            raise HTTPException(
                status_code=400, detail="No audits match the selected site for aggregated mode."
            )
    elif report_kind == "project":
        selected_audits = site_interval_audits
        if not selected_audits:
            raise HTTPException(
                status_code=400,
                detail="No site history is available for the selected project report range.",
            )

    competitor_ids = list(dict.fromkeys(options.competitors))
    comparison_audits = selected_audits

    if report_kind == "competitors" and competitor_mode == "trend":
        if reference_audit.project_id is None or effective_site_id is None:
            raise HTTPException(
                status_code=400,
                detail="Competitive trend exports require a project-backed, site-linked audit.",
            )
        if not competitor_ids:
            raise HTTPException(
                status_code=400,
                detail="Competitive trend exports require at least one tracked competitor selection.",
            )
        project = getattr(reference_audit, "project", None)
        if project is None:
            project = (
                db.query(models.Project)
                .filter(models.Project.id == reference_audit.project_id)
                .first()
            )
        if project is None:
            raise HTTPException(
                status_code=400,
                detail="Competitive trend exports require an accessible project context.",
            )
        tracked_competitor_site_ids = {
            int(row["competitor_site_id"])
            for row in list_project_competitors(db, project=project)
            if row.get("competitor_site_id") is not None
        }
        if not tracked_competitor_site_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Competitive trend exports require tracked competitor benchmark history "
                    "for this project."
                ),
            )
        missing_tracked_ids = [
            site_id for site_id in competitor_ids if site_id not in tracked_competitor_site_ids
        ]
        if missing_tracked_ids:
            missing_ids = ", ".join(str(site_id) for site_id in missing_tracked_ids)
            raise HTTPException(
                status_code=400,
                detail=(
                    "Competitive trend exports require tracked competitor selection. "
                    f"Unsupported competitor site_id(s): {missing_ids}."
                ),
            )

    primary_audit: models.Audit | None = None
    selected_competitor_audits: list[models.Audit] = []
    if payload.template_type == "Comparative" and competitor_ids:
        primary_site_id = effective_site_id or selected_audits[0].site_id
        if primary_site_id is None:
            raise HTTPException(
                status_code=400,
                detail="Comparative report requires a site_id for the primary company.",
            )

        comparison_audits = _load_audits_for_sites(
            db,
            user_id=user.id,
            site_ids=[primary_site_id, *competitor_ids],
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
        if not comparison_audits:
            raise HTTPException(
                status_code=400,
                detail="No audits match the selected primary/competitor sites in the selected interval.",
            )

        primary_audit = _select_latest_audit_for_site(
            comparison_audits,
            site_id=primary_site_id,
            date_from=payload.date_from,
            date_to=payload.date_to,
        )
        if primary_audit is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"No primary site audit found in selected interval for site_id={primary_site_id}."
                ),
            )

        missing_competitor_site_ids: list[int] = []
        for competitor_site_id in competitor_ids:
            competitor_audit = _select_latest_audit_for_site(
                comparison_audits,
                site_id=competitor_site_id,
                date_from=payload.date_from,
                date_to=payload.date_to,
            )
            if competitor_audit is None:
                missing_competitor_site_ids.append(competitor_site_id)
                continue
            selected_competitor_audits.append(competitor_audit)

        if missing_competitor_site_ids:
            missing_ids = ", ".join(str(site_id) for site_id in missing_competitor_site_ids)
            raise HTTPException(
                status_code=400,
                detail=(
                    "Missing competitor audit in selected interval for site_id(s): "
                    f"{missing_ids}."
                ),
            )
        selected_audits = comparison_audits

    if payload.template_type == "Comparative" and len(selected_audits) < 2:
        try:
            build_canonical_competitor_battle_pair(
                selected_audits[0],
                competitor_name=options.comparison_competitor_name,
                competitor_rank=options.comparison_competitor_rank,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    report_language = _resolve_report_language_for_audits(
        selected_audits,
        explicit_language=options.language,
    )

    # Short-window dedupe: identical requests inside the window replay the
    # existing job instead of enqueueing a second full PDF render. The
    # fingerprint covers audit ids, not audit content, so the window stays
    # short on purpose (see COMPLEX_REPORT_IDEMPOTENCY_WINDOW_SECONDS): a
    # deliberate regenerate after data changed must get a new report. Fail
    # open when Redis is unavailable; this is a cost optimisation, not a
    # security control.
    idempotency_fingerprint = build_idempotency_fingerprint(
        {
            "user_id": user.id,
            "export_manifest": resolved_export_manifest,
            "audit_ids": sorted(audit.id for audit in selected_audits),
            "sections": sorted(options.sections or []),
            "language": report_language,
        }
    )
    idempotency_cache_key = f"complex_report_idem:{user.id}:{idempotency_fingerprint}"
    try:
        async with get_async_redis() as redis_client:
            cached_report_id = await redis_client.get(idempotency_cache_key)
    except Exception:
        cached_report_id = None
        logger.warning("Could not read complex report idempotency key; proceeding without dedupe.")
    if isinstance(cached_report_id, bytes):
        cached_report_id = cached_report_id.decode("utf-8", errors="replace")
    if cached_report_id:
        existing_job = (
            db.query(models.ComplexReportJob)
            .filter(
                models.ComplexReportJob.id == cached_report_id,
                models.ComplexReportJob.user_id == user.id,
            )
            .first()
        )
        if existing_job is not None and existing_job.status in {
            "queued",
            "running",
            "succeeded",
        }:
            return ComplexReportResponse(
                report_id=existing_job.id,
                status=existing_job.status,
                template_type=payload.template_type,
                generated_at=datetime.now(timezone.utc).isoformat(),
                audit_count=len(selected_audits),
                executive_summary=None,
                aggregate=None,
                download_url=None,
            )
        # Terminal or missing job (failed/expired/deleted): the cached id is
        # dead weight. Drop it so later requests skip the dead lookup, then
        # enqueue fresh. A failed job in particular must never replay: the
        # user may have just upgraded to fix a 1019 entitlement denial.
        try:
            async with get_async_redis() as redis_client:
                await redis_client.delete(idempotency_cache_key)
        except Exception:
            logger.warning("Could not clear stale complex report idempotency key.")

    report_id = str(uuid.uuid4())
    # Persist job with queued status and the resolved manifest so the worker
    # and download re-checks evaluate exactly what was authorized at enqueue.
    # The library name is resolved here, once, and frozen: the requested period
    # is stored alongside it so the row never has to re-derive either.
    report_job = models.ComplexReportJob(
        id=report_id,
        user_id=user.id,
        status="queued",
        export_manifest=resolved_export_manifest,
        name=resolve_report_name(
            report_kind=report_kind,
            period_start=payload.date_from,
            period_end=payload.date_to,
            generated_at=datetime.now(timezone.utc),
        ),
        period_start=payload.date_from,
        period_end=payload.date_to,
    )
    db.add(report_job)
    db.commit()

    # Capture branding for worker
    persisted_branding = _resolve_user_branding_defaults(db, user)
    branding_config = build_report_branding_config(
        persisted_branding=persisted_branding,
        export_manifest=resolved_export_manifest,
        template_type=payload.template_type,
        language=report_language,
        overrides=payload.report_options.model_dump(exclude_none=True),
    )

    # Enqueue work for PDF worker
    job_payload = PDFJobPayload(
        job_id=report_id,
        user_id=user.id,
        template_type=payload.template_type,
        audit_ids=[audit.id for audit in selected_audits],
        options=payload.report_options.model_dump(),
        branding_config=branding_config,
        export_manifest=resolved_export_manifest,
        language=report_language,
        primary_audit_id=primary_audit.id if primary_audit else None,
        competitor_audit_ids=[a.id for a in selected_competitor_audits],
    )

    async with get_async_redis() as redis_client:
        await redis_client.rpush("pdf_jobs", json.dumps(job_payload.to_dict()))
        try:
            await redis_client.setex(
                idempotency_cache_key,
                timedelta(seconds=settings.COMPLEX_REPORT_IDEMPOTENCY_WINDOW_SECONDS),
                report_id,
            )
        except Exception:
            logger.warning("Could not store complex report idempotency key; continuing without it.")

    return ComplexReportResponse(
        report_id=report_id,
        status="queued",
        template_type=payload.template_type,
        generated_at=datetime.now(timezone.utc).isoformat(),
        audit_count=len(selected_audits),
        executive_summary=None,
        aggregate=None,
        download_url=None,
    )


def _resolve_effective_report_retention_days(db: Session) -> int:
    try:
        retention_days = int(get_report_retention_days(db))
    except Exception:
        retention_days = resolve_report_retention_days()
    if retention_days <= 0:
        retention_days = resolve_report_retention_days()
    return retention_days


def _resolve_report_job_expired(
    db: Session,
    job: models.ComplexReportJob,
    *,
    now: datetime | None = None,
) -> bool:
    if job.status == "expired":
        return True
    if job.status != "succeeded":
        return False

    completed_at = job.completed_at or job.updated_at or job.created_at
    if completed_at is None:
        return False
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)

    retention_days = _resolve_effective_report_retention_days(db)

    reference_time = now or datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(days=retention_days)
    return completed_at < cutoff


def _mark_report_job_expired(db: Session, job: models.ComplexReportJob) -> None:
    if job.status == "expired":
        return
    job.status = "expired"
    db.commit()
    db.refresh(job)


def _serialize_report_library_item(
    job: models.ComplexReportJob,
    *,
    retention_days: int,
    now: datetime,
) -> ReportLibraryItem:
    expiry = resolve_report_link_expiry(job, retention_days=retention_days, now=now)
    # A link the retention policy has already run out on is a dead link. It is
    # reported as expired here, before the customer clicks it, which is the
    # whole promise of the Link expiry column; the download route refuses it
    # with 410 either way.
    downloadable = job.status == "succeeded" and not expiry.expired
    return ReportLibraryItem(
        report_id=job.id,
        name=resolve_stored_report_name(job),
        report_kind=resolve_report_kind_from_manifest(job.export_manifest),
        period_start=job.period_start,
        period_end=job.period_end,
        created_at=job.created_at,
        size_bytes=job.file_size_bytes,
        status=job.status,
        error=job.error,
        expires_at=expiry.expires_at,
        link_expired=expiry.expired,
        link_expiry_days_remaining=expiry.days_remaining,
        retention_days=retention_days,
        download_url=f"/api/v1/reports/complex/{job.id}/download" if downloadable else None,
    )


@router.get("/api/v1/reports/complex", response_model=ReportLibraryResponse, tags=["Reports"])
def list_complex_reports(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """The report library: one call populates every approved column.

    Scoped the same way the existing single-report routes are, on
    ``ComplexReportJob.user_id``, so a report belonging to anyone else is not
    merely hidden from the list, it is unreachable. Newest first, matching the
    approved subtitle.
    """
    scoped_reports = db.query(models.ComplexReportJob).filter(
        models.ComplexReportJob.user_id == user.id
    )
    total = scoped_reports.count()
    jobs = (
        scoped_reports.order_by(
            models.ComplexReportJob.created_at.desc(),
            models.ComplexReportJob.id.desc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    retention_days = _resolve_effective_report_retention_days(db)
    now = datetime.now(timezone.utc)
    return ReportLibraryResponse(
        items=[
            _serialize_report_library_item(job, retention_days=retention_days, now=now)
            for job in jobs
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _delete_report_artifact(job: models.ComplexReportJob) -> None:
    """Remove the stored PDF so a deleted report leaves nothing downloadable."""
    if not job.file_path:
        return
    try:
        get_storage_service().delete_file(storage_uri=job.file_path)
    except Exception:
        # The row still goes. An orphaned object is swept by the retention
        # cron; a row the customer deleted that comes back is worse.
        logger.warning("Could not delete stored artifact for report job %s", job.id)


@router.delete(
    "/api/v1/reports/complex/{report_id}",
    response_model=ReportLibraryDeleteResponse,
    tags=["Reports"],
)
def delete_complex_report(
    report_id: str,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    report_job = (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == report_id, models.ComplexReportJob.user_id == user.id)
        .first()
    )
    if not report_job:
        # Same answer for "does not exist" and "is not yours", so the route
        # cannot be used to discover another tenant's report ids.
        raise HTTPException(status_code=404, detail="Complex report not found.")

    _delete_report_artifact(report_job)
    db.delete(report_job)
    db.commit()
    return ReportLibraryDeleteResponse(deleted=[report_id], not_found=[])


@router.post(
    "/api/v1/reports/complex/delete",
    response_model=ReportLibraryDeleteResponse,
    tags=["Reports"],
)
def delete_complex_reports(
    payload: ReportLibraryDeleteRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Bulk delete behind the approved "Delete selected" action.

    Ownership is re-resolved per id from the caller's own scope, so a selection
    carrying a foreign id deletes nothing of that tenant's and reports the id
    back as not found.
    """
    scoped_jobs = (
        db.query(models.ComplexReportJob)
        .filter(
            models.ComplexReportJob.user_id == user.id,
            models.ComplexReportJob.id.in_(payload.report_ids),
        )
        .all()
    )
    owned_ids = {job.id for job in scoped_jobs}
    for job in scoped_jobs:
        _delete_report_artifact(job)
        db.delete(job)
    db.commit()
    return ReportLibraryDeleteResponse(
        deleted=[report_id for report_id in payload.report_ids if report_id in owned_ids],
        not_found=[report_id for report_id in payload.report_ids if report_id not in owned_ids],
    )


@router.get("/api/v1/reports/complex/{report_id}/download", tags=["Reports"])
def download_complex_report(
    report_id: str,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    report_job = (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == report_id, models.ComplexReportJob.user_id == user.id)
        .first()
    )
    if not report_job:
        raise HTTPException(status_code=404, detail="Complex report not found.")
    if _resolve_report_job_expired(db, report_job):
        _mark_report_job_expired(db, report_job)
    if report_job.status == "expired":
        raise HTTPException(
            status_code=410, detail="Complex report expired and is no longer available."
        )
    if report_job.status != "succeeded":
        raise HTTPException(
            status_code=409, detail=f"Report not ready. Current status: {report_job.status}"
        )
    # Re-check the export entitlement against the manifest stored at enqueue:
    # a plan downgraded after rendering must not serve the gated artifact.
    # Residual: rows predating the export_manifest column have no stored
    # manifest, so only the base has_pdf_audit_reports requirement applies to
    # them. That is unavoidable without a stored manifest and is limited to
    # artifacts rendered under a then-valid entitlement.
    unmet_export_requirement = first_unmet_report_export_requirement(
        user, export_manifest=report_job.export_manifest or {}, validator=plan_validator
    )
    if unmet_export_requirement is not None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=unmet_export_requirement.detail,
        )
    if not report_job.file_path:
        raise HTTPException(status_code=404, detail="Report file path is missing.")

    gcs_service = get_storage_service()
    file_payload = gcs_service.download_file(storage_uri=report_job.file_path)
    if file_payload is not None:
        filename = gcs_service.filename_from_uri(report_job.file_path)
        return Response(
            content=file_payload,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "private, no-store",
            },
        )

    _mark_report_job_expired(db, report_job)
    raise HTTPException(
        status_code=410, detail="Complex report expired and is no longer available."
    )


@router.get("/api/v1/users/me/branding", response_model=WhiteLabelBrandingResponse, tags=["Users"])
def get_user_white_label_branding(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access branding settings.")
    db_user = db.query(models.User).filter(models.User.id == user.id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    return _resolve_user_branding_defaults(db, db_user)


@router.put("/api/v1/users/me/branding", response_model=WhiteLabelBrandingResponse, tags=["Users"])
def update_user_white_label_branding(
    payload: WhiteLabelBrandingUpdateRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access branding settings.")
    # `user` comes from the auth dependency and may be bound to a different SQLAlchemy session.
    # Re-fetch in this request's DB session to avoid cross-session attach errors.
    db_user = db.query(models.User).filter(models.User.id == user.id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    workspace = _resolve_branding_workspace(db, db_user)

    current_branding = _resolve_user_branding_defaults(db, db_user)

    if (
        "custom_logo_url" in payload.model_fields_set
        and payload.custom_logo_url != current_branding["custom_logo_url"]
    ):
        if workspace is not None:
            if not can_use_feature(
                resolve_workspace_owner_plan(db, workspace=workspace), "has_white_label"
            ):
                raise HTTPException(
                    status_code=402, detail="White-label is available on the Executive plan"
                )
        else:
            _require_plan_feature(
                user,
                feature_key="has_white_label",
                detail="White-label is available on the Executive plan",
            )

    if workspace is None:
        if "custom_logo_url" in payload.model_fields_set:
            db_user.custom_logo_url = payload.custom_logo_url
        if "company_name" in payload.model_fields_set:
            # This payload field also feeds Workspace.company_name (which has
            # its own 255 limit), so the user-column cap is enforced here, on
            # the write, not on the shared schema field. This is a form a
            # person fills in, so over-length input is rejected with a 422.
            try:
                db_user.company_name = normalize_company_name(payload.company_name)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
                ) from exc
        if "primary_color" in payload.model_fields_set:
            db_user.primary_color = payload.primary_color
        if "secondary_color" in payload.model_fields_set:
            db_user.secondary_color = payload.secondary_color
        db.commit()
        db.refresh(db_user)
        return _resolve_user_branding_defaults(db, db_user)

    if "custom_logo_url" in payload.model_fields_set:
        workspace.custom_logo_url = payload.custom_logo_url
    if "company_name" in payload.model_fields_set:
        workspace.company_name = payload.company_name
    if "primary_color" in payload.model_fields_set:
        workspace.primary_color = payload.primary_color
    if "secondary_color" in payload.model_fields_set:
        workspace.secondary_color = payload.secondary_color
    db.commit()
    db.refresh(workspace)
    return _resolve_user_branding_defaults(db, db_user)


@router.post(
    "/api/v1/reports/white-label", response_model=WhiteLabelReportResponse, tags=["Reports"]
)
def create_white_label_report(
    user: Annotated[models.User, Depends(get_current_user)],
    request: WhiteLabelReportRequest,
    db: Session = Depends(get_db),
):
    audit = (
        db.query(models.Audit)
        .filter(models.Audit.id == request.audit_id, models.Audit.user_id == user.id)
        .first()
    )
    if not audit:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    full_report = normalize_persisted_full_report(audit, db)
    effective_scores = resolve_audit_effective_scores(audit, canonical_report=full_report)
    score_breakdown = {
        "geo_score": effective_scores["geo"],
        "seo_score": effective_scores["seo"],
        "aeo_score": effective_scores["aeo"],
    }
    highlights = build_report_highlights(full_report)

    persisted_branding = _resolve_user_branding_defaults(db, user)
    effective_agency_name = (
        request.agency_name or persisted_branding["company_name"] or "White-Label Report"
    )
    effective_primary_color = (
        request.primary_color or persisted_branding["primary_color"] or "#00F2FF"
    )

    return {
        "report_id": str(uuid.uuid4()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "agency_name": effective_agency_name,
        "primary_color": effective_primary_color,
        "include_competitor_analysis": request.include_competitor_analysis,
        "audit": {
            "id": audit.id,
            "url": audit.url,
            "geo_score": audit.geo_score,
            "seo_score": audit.seo_score,
            "aeo_score": audit.aeo_score,
            "created_at": audit.created_at.isoformat() if audit.created_at else "",
            "status": _derive_audit_record_status(audit),
            "intent": full_report.get("metadata", {}).get("intent")
            if isinstance(full_report.get("metadata"), dict)
            else None,
            "full_report": full_report,
        },
        "score_breakdown": score_breakdown,
        "highlights": highlights,
    }


@router.get("/api/v1/reports/complex/{report_id}/status", tags=["Reports"])
def get_complex_report_status(
    report_id: str,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    job = (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == report_id, models.ComplexReportJob.user_id == user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found.")
    if _resolve_report_job_expired(db, job):
        _mark_report_job_expired(db, job)

    try:
        retention_days = int(get_report_retention_days(db))
    except Exception:
        retention_days = resolve_report_retention_days()
    return {
        "report_id": report_id,
        "status": job.status,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "download_url": f"/api/v1/reports/complex/{report_id}/download"
        if job.status == "succeeded"
        else None,
        "expired": job.status == "expired",
        "retention_days": retention_days,
    }


@router.get(
    "/api/v1/reports/export-variants",
    response_model=ExportVariantEntitlementsResponse,
    tags=["Reports"],
)
def list_report_export_variants(
    user: Annotated[models.User, Depends(get_current_user)],
):
    """Entitlement for the approved Export report menu, for this user's plan.

    The menu's lock state is a plan decision, so it is answered here rather than
    by a client-side capability table: this reuses the same manifest and policy
    objects the enqueue endpoint enforces, so the menu and the gate can never
    disagree about what the plan allows.
    """
    require_not_portal_only(user, detail="Client portal users cannot export reports.")
    return {
        "plan": resolve_subscription_plan(user),
        "variants": resolve_export_variant_entitlements(user, validator=plan_validator),
    }


@router.post("/api/v1/reports/white-label/pdf", tags=["Reports"])
async def create_white_label_report_pdf(
    user: Annotated[models.User, Depends(get_current_user)],
    request: WhiteLabelReportRequest,
    db: Session = Depends(get_db),
):
    audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.id == request.audit_id,
            models.Audit.user_id == user.id,
        )
        .first()
    )
    if not audit:
        raise HTTPException(
            status_code=404,
            detail=translate_backend_message("errors.audit_not_found", "Audit not found."),
        )

    persisted_branding = _resolve_user_branding_defaults(db, user)
    report_language = normalize_report_language(
        request.language or getattr(getattr(audit, "project", None), "language", None)
    )
    resolved_export_manifest = _resolve_white_label_report_manifest(
        request,
        branding_config=persisted_branding,
    )
    report_kind = str(resolved_export_manifest.get("report_kind") or "executive").strip().lower()
    report_type = str(
        resolved_export_manifest.get("render_report_type") or request.report_type or "whitelabel"
    )
    # Entitlement check must precede the job insert so a denied request does
    # not leave a permanently queued phantom row on the status endpoint.
    _require_report_export_access(user, export_manifest=resolved_export_manifest)
    # Request-shape rejections likewise precede the insert: every raise below
    # depends only on the request/audit/manifest, not on the job row.
    if report_kind == "project":
        raise HTTPException(
            status_code=400,
            detail="Project reports must be generated from the project export flow.",
        )
    if report_kind == "financial" and audit.project_id is None:
        raise HTTPException(
            status_code=400,
            detail="Financial report exports require a project-backed audit.",
        )
    if (
        report_kind == "competitors"
        and str(resolved_export_manifest.get("competitor_mode") or "").strip().lower() == "trend"
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Competitor trend exports must be generated from the project export flow "
                "with a tracked competitor selection."
            ),
        )

    report_id = str(uuid.uuid4())
    # Re-use ComplexReportJob for white-label reports too. This path takes a
    # single audit and no interval, so the row carries no period and is named
    # from its generation date, which is the "all time" case by definition.
    report_job = models.ComplexReportJob(
        id=report_id,
        user_id=user.id,
        status="queued",
        export_manifest=resolved_export_manifest,
        name=resolve_report_name(
            report_kind=report_kind,
            generated_at=datetime.now(timezone.utc),
        ),
    )
    db.add(report_job)
    db.commit()

    # Enqueue for PDF worker
    branding_config = build_report_branding_config(
        persisted_branding=persisted_branding,
        export_manifest=resolved_export_manifest,
        template_type="Executive",
        language=report_language,
        overrides=request.model_dump(exclude_none=True, exclude={"audit_id"}),
    )
    job_payload = PDFJobPayload(
        job_id=report_id,
        user_id=user.id,
        template_type="Executive",  # White label defaults to executive style
        audit_ids=[audit.id],
        options={
            "include_competitor_analysis": request.include_competitor_analysis,
            "report_type": report_type,
            "footer_text": request.footer_text,
            "agency_name": request.agency_name,
            "title": request.title,
            "report_date": request.report_date,
            "primary_color": request.primary_color,
            "secondary_color": request.secondary_color,
            "logo_data_url": request.logo_data_url,
            "language": report_language,
            "report_kind": resolved_export_manifest["report_kind"],
            "branding_mode": resolved_export_manifest["branding_mode"],
            "competitor_mode": resolved_export_manifest["competitor_mode"],
            "hide_credit_cost": resolved_export_manifest["hide_credit_cost"],
        },
        branding_config=branding_config,
        export_manifest=resolved_export_manifest,
        language=report_language,
    )

    async with get_async_redis() as redis_client:
        await redis_client.rpush("pdf_jobs", json.dumps(job_payload.to_dict()))

    return {
        "report_id": report_id,
        "status": "queued",
        "poll_url": f"/api/v1/reports/complex/{report_id}/status",
    }


@router.get(
    "/api/v1/competitors/compare",
    response_model=CompetitorCompareResponse,
    tags=["Competitors"],
)
def compare_competitor_sites(
    base_site_id: int,
    comp_site_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user, feature_key="has_competitor_analysis", detail="Feature available in Specialist"
    )
    base_site = db.query(models.Site).filter(models.Site.id == base_site_id).first()
    comp_site = db.query(models.Site).filter(models.Site.id == comp_site_id).first()

    _validate_geo_compare_site_access(base_site, user, db)
    _validate_geo_compare_site_access(comp_site, user, db)

    is_linked_competitor = (
        db.query(models.site_competitors)
        .filter(
            models.site_competitors.c.site_id == base_site_id,
            models.site_competitors.c.competitor_site_id == comp_site_id,
        )
        .first()
        is not None
    )
    if not is_linked_competitor:
        raise HTTPException(status_code=403, detail="Competitor is not linked to this project")

    try:
        result = competitor_benchmark_service.compare_latest_site_audits(
            db=db,
            base_site_id=base_site_id,
            comp_site_id=comp_site_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result["base_site"] = base_site.domain if base_site else None
    result["comp_site"] = comp_site.domain if comp_site else None
    return CompetitorCompareResponse(**result)


@router.get(
    "/api/v1/competitors/semantic-gap",
    response_model=CompetitorSemanticGapResponse,
    tags=["Competitors"],
)
def get_competitor_semantic_gap(
    base_site_id: int,
    comp_site_id: int,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user, feature_key="has_competitor_analysis", detail="Feature available in Specialist"
    )
    _require_plan_feature(
        user, feature_key="has_semantic_gap", detail="Feature available in Specialist"
    )
    base_site = db.query(models.Site).filter(models.Site.id == base_site_id).first()
    comp_site = db.query(models.Site).filter(models.Site.id == comp_site_id).first()

    _validate_geo_compare_site_access(base_site, user, db)
    _validate_geo_compare_site_access(comp_site, user, db)

    is_linked_competitor = (
        db.query(models.site_competitors)
        .filter(
            models.site_competitors.c.site_id == base_site_id,
            models.site_competitors.c.competitor_site_id == comp_site_id,
        )
        .first()
        is not None
    )
    if not is_linked_competitor:
        raise HTTPException(status_code=403, detail="Competitor is not linked to this project")

    try:
        return competitor_benchmark_service.compare_semantic_footprint(
            site_id_1=base_site_id,
            site_id_2=comp_site_id,
            db=db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/api/v1/competitors/discovery",
    response_model=CompetitorDiscoveryResponse,
    tags=["Competitors"],
)
async def discover_competitors(
    request: CompetitorDiscoveryRequest,
    user: Annotated[models.User, Depends(get_current_user)],
):
    _require_plan_feature(
        user, feature_key="has_competitor_analysis", detail="Feature available in Specialist"
    )
    del user
    try:
        result = await competitor_discovery_service.discover_competitors(
            site_url=request.site_url,
            category=request.category,
            market=request.market,
        )
    except ValueError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.competitor_discovery_invalid",
            fallback="Invalid competitor discovery request.",
            request=None,
            exc=exc,
            log_context="Competitor discovery validation failed",
        )

    return CompetitorDiscoveryResponse(**result)


@router.post(
    "/api/v1/competitors/benchmark",
    response_model=CompetitorBenchmarkResponse,
    tags=["Competitors"],
)
def generate_competitor_benchmark(
    request: CompetitorBenchmarkRequest,
    user: Annotated[models.User, Depends(get_current_user)],
):
    _require_plan_feature(
        user, feature_key="has_competitor_analysis", detail="Feature available in Specialist"
    )
    del user
    try:
        result = competitor_benchmark_service.build_benchmark_table(
            target=request.target.model_dump(),
            competitors=[item.model_dump() for item in request.competitors],
        )
    except ValueError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.competitor_benchmark_invalid",
            fallback="Invalid competitor benchmark request.",
            request=None,
            exc=exc,
            log_context="Competitor benchmark validation failed",
        )

    return CompetitorBenchmarkResponse(**result)


@router.get(
    "/api/v1/geo-visibility",
    response_model=GeoVisibilityResponse,
    tags=["Audit"],
    include_in_schema=False,
)
async def get_geo_visibility(
    user: Annotated[models.User, Depends(get_current_user)],
    target: str = Query(..., description="Target URL or domain to track visibility for."),
    location: str = Query(..., description="Target location context for query generation."),
    seed_queries: list[str] | None = Query(
        default=None, description="Optional explicit seed queries."
    ),
    brand: str | None = Query(
        default=None, description="Optional brand/entity name to detect alongside domain."
    ),
):
    del user
    request = GeoVisibilityRequest(
        target=target,
        location=location,
        seed_queries=seed_queries,
        brand=brand,
    )
    return await _run_geo_visibility_audit(request)


async def _run_geo_visibility_audit(request: GeoVisibilityRequest) -> GeoVisibilityResponse:
    try:
        validate_target_host(request.target)
        return await geo_visibility_service.run_visibility_audit(
            target=request.target,
            location=request.location,
            seed_queries=request.seed_queries,
            brand=request.brand,
        )
    except ValueError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.geo_visibility_invalid",
            fallback="Invalid geo visibility request.",
            request=None,
            exc=exc,
            log_context="Geo visibility validation failed",
        )
    except ProviderTimeoutError as exc:
        _raise_client_error(
            status_code=504,
            key="errors.geo_visibility_timeout",
            fallback="Geo visibility provider timed out.",
            request=None,
            exc=exc,
            log_context="Geo visibility provider timeout",
        )


@router.post("/api/v1/geo-visibility", response_model=GeoVisibilityResponse, tags=["Audit"])
async def post_geo_visibility(
    user: Annotated[models.User, Depends(get_current_user)],
    request: GeoVisibilityRequest,
):
    del user
    return await _run_geo_visibility_audit(request)


@router.get(
    "/api/v1/visibility-index/trends",
    response_model=VisibilityTrendsResponse,
    tags=["Audit"],
)
def get_visibility_index_trends(
    user: Annotated[models.User, Depends(get_current_user)],
    topic: str = Query(..., description="Topic tracked by recurring visibility jobs."),
    provider: str | None = Query(default=None, description="Optional provider filter."),
    days: int = Query(default=30, ge=1, le=365, description="Time window in days."),
    db: Session = Depends(get_db),
):
    del user
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    query = db.query(models.VisibilityRunBatch).filter(models.VisibilityRunBatch.topic == topic)
    if provider:
        query = query.filter(models.VisibilityRunBatch.provider == provider)
    batches = (
        query.filter(models.VisibilityRunBatch.created_at >= cutoff)
        .order_by(models.VisibilityRunBatch.created_at.asc())
        .all()
    )
    points = [
        {
            "run_id": batch.id,
            "created_at": batch.created_at.isoformat() if batch.created_at else "",
            "score": float(batch.score or 0.0),
            "status": batch.status,
        }
        for batch in batches
    ]
    return {"topic": topic, "provider": provider, "points": points}


@router.get(
    "/api/v1/visibility-index/latest",
    response_model=VisibilityLatestRunResponse,
    tags=["Audit"],
)
def get_visibility_index_latest_run(
    user: Annotated[models.User, Depends(get_current_user)],
    topic: str = Query(..., description="Topic tracked by recurring visibility jobs."),
    provider: str = Query(..., description="Provider used for the run."),
    db: Session = Depends(get_db),
):
    del user
    latest = (
        db.query(models.VisibilityRunBatch)
        .filter(models.VisibilityRunBatch.topic == topic)
        .filter(models.VisibilityRunBatch.provider == provider)
        .order_by(models.VisibilityRunBatch.created_at.desc())
        .first()
    )
    if latest is None:
        raise HTTPException(
            status_code=404, detail="No visibility runs found for the requested filters"
        )

    runs = (
        db.query(models.VisibilityRun)
        .filter(models.VisibilityRun.batch_id == latest.id)
        .order_by(models.VisibilityRun.created_at.asc())
        .all()
    )
    return {
        "batch_id": latest.id,
        "topic": latest.topic,
        "provider": latest.provider,
        "schedule_key": latest.schedule_key,
        "status": latest.status,
        "score": latest.score,
        "error": latest.error,
        "started_at": latest.started_at.isoformat() if latest.started_at else None,
        "completed_at": latest.completed_at.isoformat() if latest.completed_at else None,
        "runs": [
            {
                "id": run.id,
                "prompt_template": run.prompt_template,
                "prompt": run.prompt,
                "raw_response": run.raw_response,
                "parsed_citations": run.parsed_citations,
                "valid_citations": run.valid_citations,
                "score": run.score,
                "status": run.status,
                "error": run.error,
                "created_at": run.created_at.isoformat() if run.created_at else None,
            }
            for run in runs
        ],
    }


@router.get(
    "/api/v1/volatility/public",
    response_model=VolatilityPublicDashboardResponse,
    tags=["Audit"],
)
def get_public_ai_search_volatility_dashboard(
    provider: str = Query(default="all", max_length=50),
    days: int = Query(default=30, ge=7, le=365),
    db: Session = Depends(get_db),
):
    service = AISearchVolatilityService(db)
    service.ensure_default_seed_queries()
    return service.build_public_dashboard(days=days, provider=provider)


@router.post(
    "/api/v1/aeo/answerability",
    response_model=AEOAnswerabilityResponse,
    tags=["Audit"],
)
async def score_aeo_answerability(
    user: Annotated[models.User, Depends(get_current_user)],
    request: AEOAnswerabilityRequest,
    db: Session = Depends(get_db),
):
    try:
        return await aeo_answerability_service.score_url(
            str(request.url),
            prevalidated=True,
            db=db,
            user_id=user.id,
        )
    except httpx.HTTPError as exc:
        _raise_client_error(
            status_code=502,
            key="errors.target_url_fetch_unavailable",
            fallback="Unable to fetch the target URL.",
            request=None,
            exc=exc,
            log_context="AEO answerability target fetch failed",
        )


@router.post(
    "/api/v1/intent/ingest",
    tags=["Audit"],
)
def ingest_intent_corpus(
    request: IntentIngestRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    del user
    inserted = predictive_intent_service.ingest_corpus(
        db=db,
        entries=[entry.model_dump() for entry in request.entries],
        reindex=request.reindex,
    )
    return {"inserted": inserted, "reindexed": request.reindex and inserted > 0}


@router.post(
    "/api/v1/intent/reindex",
    tags=["Audit"],
)
def reindex_intent_corpus(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    del user
    indexed = predictive_intent_service.rebuild_index(db)
    return {"indexed": indexed}


@router.post(
    "/api/v1/intent/predict",
    response_model=IntentPredictResponse,
    tags=["Audit"],
)
def predict_intent(
    request: IntentPredictRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    del user
    start = time.perf_counter()
    results = predictive_intent_service.predict(db=db, query=request.query, top_k=request.top_k)
    latency_ms = (time.perf_counter() - start) * 1000
    predictive_intent_service.persist_query_telemetry(
        db=db,
        query=request.query,
        top_k=request.top_k,
        provider=os.getenv("INTENT_INDEX_PROVIDER", "local"),
        latency_ms=latency_ms,
        results=results,
    )
    return IntentPredictResponse(query=request.query, top_k=request.top_k, predictions=results)


@router.get(
    "/api/v1/entities",
    response_model=EntityAnalysisResponse,
    tags=["Audit"],
)
async def get_entities(
    user: Annotated[models.User, Depends(get_current_user)],
    url: str = Query(..., description="URL to analyze for entities and schema markup."),
):
    del user
    try:
        normalized_url = normalize_and_validate_url(url)
        result = await entity_service.analyze(normalized_url)
    except httpx.HTTPStatusError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.target_url_fetch_failed",
            fallback="Failed to fetch the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity analysis URL fetch failed with HTTP status error",
        )
    except httpx.RequestError as exc:
        _raise_client_error(
            status_code=502,
            key="errors.target_url_retrieve_failed",
            fallback="Unable to retrieve the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity analysis URL retrieval failed",
        )

    return EntityAnalysisResponse(**result)


@router.get(
    "/api/v1/entities/graph",
    response_model=EntityGraphResponse,
    tags=["Audit"],
)
async def get_entities_graph(
    user: Annotated[models.User, Depends(get_current_user)],
    url: str = Query(..., description="URL to analyze and transform into graph data."),
):
    del user
    try:
        normalized_url = normalize_and_validate_url(url)
        result = await entity_service.analyze(normalized_url)
        graph = entity_graph_service.build_graph(result)
    except httpx.HTTPStatusError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.target_url_fetch_failed",
            fallback="Failed to fetch the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity graph URL fetch failed with HTTP status error",
        )
    except httpx.RequestError as exc:
        _raise_client_error(
            status_code=502,
            key="errors.target_url_retrieve_failed",
            fallback="Unable to retrieve the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity graph URL retrieval failed",
        )

    return EntityGraphResponse(**graph)


@router.post(
    "/api/v1/entities/extract",
    response_model=EntityExtractResponse,
    tags=["Audit"],
)
async def extract_entities_from_url(
    request: EntityExtractRequest,
    user: Annotated[models.User, Depends(get_current_user)],
):
    del user
    try:
        entities = await extract_entity_candidates_from_url(
            str(request.url),
            entity_service=entity_service,
        )
    except httpx.HTTPStatusError as exc:
        _raise_client_error(
            status_code=400,
            key="errors.target_url_fetch_failed",
            fallback="Failed to fetch the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity extraction URL fetch failed with HTTP status error",
        )
    except httpx.RequestError as exc:
        _raise_client_error(
            status_code=502,
            key="errors.target_url_retrieve_failed",
            fallback="Unable to retrieve the requested URL.",
            request=None,
            exc=exc,
            log_context="Entity extraction URL retrieval failed",
        )

    return EntityExtractResponse(url=str(request.url), entities=entities)


class SiteClassifyRequest(URLValidatedRequest):
    pass


class SiteClassifyResponse(BaseModel):
    url: str
    category: str
    confidence: float


@router.post(
    "/api/v1/site/classify",
    response_model=SiteClassifyResponse,
    tags=["Audit"],
)
async def classify_site_category(
    request: SiteClassifyRequest,
    user: Annotated[models.User, Depends(get_current_user)],
):
    del user
    target_url = str(request.url)
    try:
        scrape_result = await scraper_service.get_page_content_and_screenshot(target_url)
        # ScraperService returns the page text under "markdown_content"; there is no
        # "content" key, so reading it always yielded "" and short-circuited the
        # classification to General/0.0 after paying for a full Firecrawl scrape.
        page_content = (
            str(scrape_result.get("markdown_content") or "")
            if isinstance(scrape_result, dict)
            else ""
        )
    except Exception:
        page_content = ""

    if not page_content:
        return SiteClassifyResponse(url=target_url, category="General", confidence=0.0)

    route = resolve_site_classify_route()
    content_excerpt = re.sub(r"\s+", " ", page_content).strip()[:2000]
    cache_context = {"url": target_url, "content": content_excerpt}
    cached_entry = await asyncio.to_thread(
        semantic_cache_service.get_json,
        feature_key=route.feature_key,
        route_provider=route.provider,
        route_tier=route.execution_tier,
        semantic_payload=cache_context,
    )
    if isinstance(cached_entry, dict):
        cached_response = cached_entry.get("response")
        if isinstance(cached_response, dict):
            return SiteClassifyResponse(
                url=target_url,
                category=str(cached_response.get("category") or "General"),
                confidence=float(cached_response.get("confidence") or 0.0),
            )

    try:
        result = await ai_client.classify_site_category(
            content=content_excerpt,
            provider=route.provider,
            tier=route.execution_tier,
        )
    except Exception:
        result = {"category": "General", "confidence": 0.0}

    await asyncio.to_thread(
        semantic_cache_service.set_json,
        feature_key=route.feature_key,
        route_provider=route.provider,
        route_tier=route.execution_tier,
        semantic_payload=cache_context,
        value={
            "category": result.get("category", "General"),
            "confidence": float(result.get("confidence", 0.0) or 0.0),
        },
    )

    return SiteClassifyResponse(
        url=target_url,
        category=result.get("category", "General"),
        confidence=result.get("confidence", 0.0),
    )


# ── AI Pre-Audit URL Scanning ──────────────────────────────────────────────

PRE_SCAN_CREDIT_COST = int(os.getenv("PRE_SCAN_CREDIT_COST", "1"))


class PreScanRequest(BaseModel):
    audit_target_type: Literal["website", "brand"] = "website"
    url: HttpUrl | None = None
    target_name: str | None = Field(default=None, min_length=1, max_length=256)

    @field_validator("url", mode="before")
    @classmethod
    def validate_url(cls, value: str | HttpUrl | None) -> str | None:
        if value is None:
            return None
        raw_value = str(value).strip()
        if not raw_value:
            return None
        try:
            return normalize_and_validate_url(raw_value)
        except ValueError as exc:
            raise ValueError(INVALID_URL_FORMAT_DETAIL) from exc

    @model_validator(mode="after")
    def validate_target_contract(self) -> "PreScanRequest":
        if self.audit_target_type == "website" and not self.url:
            raise ValueError("Website pre-scans require a url.")
        if self.audit_target_type == "brand" and not self.target_name and not self.url:
            raise ValueError("Brand pre-scans require a target_name or url.")
        return self


class PreScanResponse(BaseModel):
    url: str | None = None
    target_name: str | None = None
    language: str
    market_region: str
    category: str
    primary_entities: list[str]
    source: str
    snapshot_title: str | None = None
    snapshot_description: str | None = None


@router.post(
    "/api/v1/audit/pre-scan",
    response_model=PreScanResponse,
    tags=["Audit"],
)
async def pre_scan_url(
    payload: PreScanRequest,
    user: Annotated[models.User, Depends(get_current_user)],
):
    """Perform an AI-powered pre-scan of the given URL.

    Extracts language, market region, category, primary entities, and direct competitors
    using Gemini AI. Costs 1 credit for non-subscription users.
    """
    from services.pre_scan_service import analyze_target

    target_url = str(payload.url) if payload.url else None
    target_name = payload.target_name
    audit_target_type = payload.audit_target_type

    # Internal soft-limit accounting only (SIGV2-1024): the pre-scan books
    # its small internal cost, allowed to go negative, and never blocks.
    credits_deducted = 0
    if should_decrement_credits(user, "fast"):
        db = SessionLocal()
        try:
            success = decrement_credits_atomic(
                db, user.id, PRE_SCAN_CREDIT_COST, allow_negative=True
            )
            if not success:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to record internal accounting.",
                )
            db.commit()
            credits_deducted = PRE_SCAN_CREDIT_COST
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    try:
        result = await asyncio.to_thread(analyze_target, audit_target_type, target_url, target_name)
    except Exception as exc:
        if credits_deducted > 0:
            db = SessionLocal()
            try:
                increment_credits_atomic(db, user.id, credits_deducted)
                db.commit()
            except Exception as refund_exc:
                logger.error(
                    "Failed to refund pre-scan credits for user %s: %s", user.id, refund_exc
                )
            finally:
                db.close()

        if isinstance(exc, ValueError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if isinstance(exc, RuntimeError):
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        raise

    return PreScanResponse(
        url=target_url,
        target_name=target_name,
        language=result.get("language", "en"),
        market_region=result.get("market_region", "Global"),
        category=result.get("category", "General"),
        primary_entities=result.get("primary_entities", []),
        source=result.get("source", "gemini_pre_scan"),
        snapshot_title=result.get("snapshot_title"),
        snapshot_description=result.get("snapshot_description"),
    )


@router.post("/api/v1/guest-audit", tags=["Audit"])
async def create_guest_audit(
    request: GuestAuditRequest, http_request: Request, db: Session = Depends(get_db)
):
    """Run a guest audit synchronously and return the full guest payload.

    This is the legacy path used by Signal's own marketing page, kept as is.
    It blocks for as long as the audit takes, which is why the marketing site
    uses the queued public path instead (``POST /api/v1/public/guest-audit``).
    """
    await enforce_guest_audit_limit(http_request)
    client_ip = _resolve_client_ip(http_request)
    ua_raw = http_request.headers.get("user-agent", "")
    return await run_guest_audit(
        db,
        audit_target_type=request.audit_target_type,
        target_url=request.resolved_target_url(),
        target_name=request.resolved_target_name(),
        target_metadata=request.resolved_target_metadata(),
        email=request.email,
        request_id=http_request.state.request_id,
        ip_hash=hashlib.sha256(client_ip.encode("utf-8")).hexdigest(),
        user_agent_hash=(hashlib.sha256(ua_raw.encode("utf-8")).hexdigest() if ua_raw else None),
        referrer=http_request.headers.get("referer", None),
    )


@router.post("/api/v1/guest-audit/claim", tags=["Audit"])
def claim_guest_audit(
    token: str = Query(
        ..., description="The guest_audit_token returned by the guest-audit endpoint."
    ),
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """Claim a guest audit record and link it to the authenticated user."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
    except PyJWTError:
        raise HTTPException(status_code=400, detail="Invalid or expired guest audit token.")

    if payload.get("type") != "guest_audit_claim":
        raise HTTPException(status_code=400, detail="Invalid token type.")

    record = (
        db.query(models.GuestAuditRecord)
        .filter(models.GuestAuditRecord.id == payload.get("guest_audit_id"))
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Guest audit record not found.")

    if record.claimed_by_user_id is not None:
        raise HTTPException(status_code=409, detail="This guest audit has already been claimed.")

    record.claimed_by_user_id = user.id
    record.claimed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "claimed",
        "guest_audit_id": record.id,
        "target_url": record.target_url,
        "target_name": record.target_name,
        "seo_score": record.seo_score,
        "geo_score": record.geo_score,
        "aeo_score": record.aeo_score,
        "overall_score": record.overall_score,
    }


@router.get("/api/v1/users/me", response_model=UserSummaryResponse, tags=["Users"])
def get_user_summary(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(
        user, detail="Client portal users cannot access billing or credit summaries."
    )
    user = get_user_or_404(db, user.id)
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    )

    # Resolve plan and capabilities (trial plan takes effect when no paid sub)
    from services.trial_service import resolve_trial_status

    plan_type = resolve_subscription_plan(user)
    capabilities = get_plan_capabilities(plan_type)

    trial_status_data = resolve_trial_status(user)

    max_audits_capability = capabilities.get("max_audits", 5)
    max_audits = (
        int(max_audits_capability)
        if isinstance(max_audits_capability, int) and not isinstance(max_audits_capability, bool)
        else 5
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    audits_run_30d = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user.id)
        .filter(models.Audit.created_at >= cutoff)
        .count()
    )

    credits_unlimited = max_audits == -1
    raw_credits = max(0, int(user.credits or 0))
    included_audits_30d = None if credits_unlimited else max(0, max_audits)
    remaining_included_audits_30d = (
        None if credits_unlimited else max(0, max_audits - audits_run_30d)
    )
    effective_credits = raw_credits + (remaining_included_audits_30d or 0)

    from services.scan_allowance_service import scan_allowance_snapshot

    scan_snapshot = scan_allowance_snapshot(db, user)

    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "credits": raw_credits,
        "raw_credits": raw_credits,
        "included_audits_30d": included_audits_30d,
        "remaining_included_audits_30d": remaining_included_audits_30d,
        "effective_credits": effective_credits,
        "credits_unlimited": credits_unlimited,
        "audits_run_30d": audits_run_30d,
        "scans_used": scan_snapshot.scans_used,
        "scans_remaining": scan_snapshot.scans_remaining,
        "reset_at": scan_snapshot.reset_at,
        "subscription": (
            {
                "plan_type": subscription.plan_type,
                "status": subscription.status,
                "current_period_end": (
                    subscription.current_period_end.isoformat()
                    if subscription.current_period_end
                    else None
                ),
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
            if subscription
            else None
        ),
        "capabilities": capabilities,
        "trial": trial_status_data if trial_status_data["is_trial"] else None,
    }


@router.get("/api/v1/users/me/profile", response_model=UserProfileResponse, tags=["Users"])
def get_user_profile(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access account settings.")
    db_user = get_user_or_404(db, user.id)
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == db_user.id).first()
    )
    return _serialize_user_profile(db_user, subscription)


@router.get(
    "/api/v1/users/me/onboarding", response_model=UserOnboardingStateResponse, tags=["Users"]
)
def get_user_onboarding_state(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access onboarding state.")
    db_user = get_user_or_404(db, user.id)
    return _normalize_onboarding_state(getattr(db_user, "onboarding_state", None))


@router.patch(
    "/api/v1/users/me/onboarding", response_model=UserOnboardingStateResponse, tags=["Users"]
)
def update_user_onboarding_state(
    request: UserOnboardingStateUpdateRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access onboarding state.")
    db_user = get_user_or_404(db, user.id)
    state = _normalize_onboarding_state(getattr(db_user, "onboarding_state", None))
    now_iso = datetime.now(timezone.utc).isoformat()

    if request.started is True and not state["started_at"]:
        state["started_at"] = now_iso
    elif request.started is False:
        state["started_at"] = None

    if request.completed_steps is not None:
        state["completed_steps"] = request.completed_steps

    if request.add_completed_steps:
        merged_steps = _normalize_onboarding_steps(
            [*state["completed_steps"], *request.add_completed_steps]
        )
        state["completed_steps"] = merged_steps

    if request.dismissed is True:
        state["dismissed_at"] = now_iso
    elif request.dismissed is False:
        state["dismissed_at"] = None

    state["updated_at"] = now_iso
    db_user.onboarding_state = state

    try:
        db.commit()
        db.refresh(db_user)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update onboarding state for user %s: %s", db_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update onboarding state.",
        )

    return _normalize_onboarding_state(getattr(db_user, "onboarding_state", None))


@router.get("/api/v1/users/me/trial", response_model=TrialStatusResponse, tags=["Users"])
def get_user_trial_status(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Return the current trial status for the authenticated user."""
    from services.trial_service import resolve_trial_status as _resolve_trial

    db_user = get_user_or_404(db, user.id)
    return _resolve_trial(db_user)


@router.post("/api/v1/users/me/trial/concierge-complete", tags=["Users"])
def mark_trial_concierge_complete(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Mark the concierge onboarding as completed for the trial user."""
    from services.trial_service import mark_concierge_completed

    db_user = get_user_or_404(db, user.id)
    mark_concierge_completed(db, db_user)
    db.commit()
    return {"status": "ok"}


@router.patch("/api/v1/users/me", response_model=UserProfileResponse, tags=["Users"])
def update_user_profile(
    request: UserProfileUpdateRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    require_not_portal_only(user, detail="Client portal users cannot access account settings.")
    db_user = get_user_or_404(db, user.id)
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == db_user.id).first()
    )

    field_to_column = {
        "name": "company_name",
        "company_legal_name": "company_legal_name",
        "company_registration_number": "company_registration_number",
        "company_vat_number": "company_vat_number",
        "billing_email": "billing_email",
        "billing_phone": "billing_phone",
        "billing_address_line1": "billing_address_line1",
        "billing_address_line2": "billing_address_line2",
        "billing_city": "billing_city",
        "billing_state": "billing_state",
        "billing_postal_code": "billing_postal_code",
        "billing_country": "billing_country",
        "billing_website_url": "billing_website_url",
        "billing_tax_exempt": "billing_tax_exempt",
    }

    for field_name, column_name in field_to_column.items():
        if field_name not in request.model_fields_set:
            continue
        value = getattr(request, field_name)
        if field_name == "billing_tax_exempt" and value is None:
            value = False
        setattr(db_user, column_name, value)

    try:
        db.commit()
        db.refresh(db_user)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to update profile for user %s: %s", db_user.id, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update profile.",
        )

    _sync_user_billing_profile_to_stripe_customer(
        user=db_user,
        subscription=subscription,
        db=db,
    )

    return _serialize_user_profile(db_user, subscription)


@router.post("/api/v1/users/me/password", response_model=ChangePasswordResponse, tags=["Users"])
def change_user_password(
    request: ChangePasswordRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_user = get_user_or_404(db, user.id)

    if db_user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password changes are only supported for email/password accounts.",
        )

    # verify_password returns False on a malformed hash instead of raising.
    password_matches = verify_password(request.current_password, db_user.hashed_password)

    if not password_matches:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
        )

    if request.current_password == request.new_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be different from current password.",
        )

    db_user.hashed_password = hash_password(request.new_password)
    db.commit()

    # Invalidate every session/refresh token issued before the change,
    # including the caller's own session.
    session_jtis = deactivate_user_sessions(db, db_user.id)
    if session_jtis:
        asyncio.run(revoke_session_jtis(session_jtis))
    return {"message": "Password updated successfully."}


@router.get("/api/v1/users/me/mfa/status", response_model=MFAStatusResponse, tags=["Users"])
def get_mfa_status(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_user = get_user_or_404(db, user.id)
    return {"enabled": bool(getattr(db_user, "mfa_secret", None))}


@router.post("/api/v1/users/me/mfa/setup", response_model=MFASetupResponse, tags=["Users"])
def create_mfa_setup(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_user = get_user_or_404(db, user.id)
    if db_user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup is currently available for email/password accounts only.",
        )

    secret = generate_totp_secret()
    otpauth_uri = build_totp_uri(secret, account_name=db_user.email, issuer=MFA_ISSUER)
    setup_token = _create_mfa_setup_token(user_id=db_user.id, secret=secret)

    return {
        "issuer": MFA_ISSUER,
        "account_name": db_user.email,
        "secret": secret,
        "otpauth_uri": otpauth_uri,
        "qr_code_url": _build_mfa_qr_code_url(otpauth_uri),
        "setup_token": setup_token,
    }


@router.post("/api/v1/users/me/mfa/enable", response_model=MFAStatusResponse, tags=["Users"])
async def enable_mfa(
    request: MFAEnableRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_user = get_user_or_404(db, user.id)
    if db_user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup is currently available for email/password accounts only.",
        )

    # SIGV2-1241: the only accepted source for the enrolled secret is the
    # server-minted, user-bound setup token issued by the setup endpoint.
    secret = _decode_mfa_setup_token(token=request.setup_token, user_id=db_user.id)

    await _verify_mfa_otp_or_raise(user_id=db_user.id, secret=secret, otp_code=request.otp_code)

    db_user.mfa_secret = secret
    db.commit()
    return {"enabled": True}


@router.post("/api/v1/users/me/mfa/disable", response_model=MFAStatusResponse, tags=["Users"])
async def disable_mfa(
    request: MFADisableRequest,
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    db_user = get_user_or_404(db, user.id)
    if db_user.auth_provider != "local":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup is currently available for email/password accounts only.",
        )

    if not db_user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled.")

    await _verify_mfa_otp_or_raise(
        user_id=db_user.id, secret=db_user.mfa_secret, otp_code=request.otp_code
    )

    db_user.mfa_secret = None
    db.commit()
    return {"enabled": False}


@router.get(
    "/api/v1/users/me/notification-preferences",
    response_model=NotificationPreferencesResponse,
    tags=["Users"],
)
def get_notification_preferences(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    user = get_user_or_404(db, user.id)
    return {
        "user_id": user.id,
        "notifications_enabled": user.notifications_enabled,
        "notify_product_updates": user.notify_product_updates,
        "notify_audit_alerts": user.notify_audit_alerts,
        "notify_billing": user.notify_billing,
    }


@router.put(
    "/api/v1/users/me/notification-preferences",
    response_model=NotificationPreferencesResponse,
    tags=["Users"],
)
def update_notification_preferences(
    user: Annotated[models.User, Depends(get_current_user)],
    request: NotificationPreferencesRequest,
    db: Session = Depends(get_db),
):
    user = get_user_or_404(db, user.id)
    user.notifications_enabled = request.notifications_enabled
    if request.notify_product_updates is not None:
        user.notify_product_updates = request.notify_product_updates
    if request.notify_audit_alerts is not None:
        user.notify_audit_alerts = request.notify_audit_alerts
    if request.notify_billing is not None:
        user.notify_billing = request.notify_billing
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to update notification preferences for user {user.id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.notification_preferences_update_failed",
                "Failed to update notification preferences.",
            ),
        )

    return {
        "user_id": user.id,
        "notifications_enabled": user.notifications_enabled,
        "notify_product_updates": user.notify_product_updates,
        "notify_audit_alerts": user.notify_audit_alerts,
        "notify_billing": user.notify_billing,
    }


@router.get("/api/v1/users/me/data-export", response_model=DataExportResponse, tags=["Users"])
def export_user_data(
    user: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    user = get_user_or_404(db, user.id)
    audits = (
        db.query(models.Audit)
        .filter(models.Audit.user_id == user.id)
        .order_by(models.Audit.created_at.desc())
        .all()
    )
    subscription = (
        db.query(models.Subscription).filter(models.Subscription.user_id == user.id).first()
    )
    billing_payments = (
        db.query(models.BillingPayment)
        .filter(models.BillingPayment.user_id == user.id)
        .order_by(models.BillingPayment.created_at.desc())
        .all()
    )
    email_outbox_entries = (
        db.query(models.EmailOutbox)
        .filter(models.EmailOutbox.user_id == user.id)
        .order_by(models.EmailOutbox.created_at.desc())
        .all()
    )
    credit_adjustments = (
        db.query(models.UserCreditAdjustment)
        .filter(models.UserCreditAdjustment.user_id == user.id)
        .order_by(models.UserCreditAdjustment.created_at.desc())
        .all()
    )
    admin_action_logs = (
        db.query(models.AdminActionLog)
        .filter(models.AdminActionLog.admin_user_id == user.id)
        .order_by(models.AdminActionLog.created_at.desc())
        .all()
    )
    workspace_memberships = (
        db.query(models.WorkspaceUser, models.Workspace)
        .join(models.Workspace, models.Workspace.id == models.WorkspaceUser.workspace_id)
        .filter(models.WorkspaceUser.user_id == user.id)
        .all()
    )
    owned_workspace_ids = {
        row.id
        for row in db.query(models.Workspace.id).filter(models.Workspace.owner_id == user.id).all()
    }
    workspaces_summary = [
        {
            "id": workspace.id,
            "name": workspace.name,
            "is_owner": workspace.owner_id == user.id or workspace.id in owned_workspace_ids,
            "role": membership.role.value if membership.role else None,
        }
        for membership, workspace in workspace_memberships
    ]
    # Workspaces the user owns without a membership row still appear.
    missing_owned = owned_workspace_ids - {entry["id"] for entry in workspaces_summary}
    if missing_owned:
        for workspace in (
            db.query(models.Workspace).filter(models.Workspace.id.in_(missing_owned)).all()
        ):
            workspaces_summary.append(
                {
                    "id": workspace.id,
                    "name": workspace.name,
                    "is_owner": True,
                    "role": None,
                }
            )

    logger.info("User data export requested for user_id=%s", user.id)

    return {
        "user_id": user.id,
        "email": user.email,
        "role": user.role,
        "credits": user.credits,
        "notifications_enabled": user.notifications_enabled,
        "company_profile": {
            "company_name": user.company_name,
            "company_legal_name": getattr(user, "company_legal_name", None),
            "company_registration_number": getattr(user, "company_registration_number", None),
            "company_vat_number": getattr(user, "company_vat_number", None),
            "billing_email": getattr(user, "billing_email", None),
            "billing_phone": getattr(user, "billing_phone", None),
            "billing_address_line1": getattr(user, "billing_address_line1", None),
            "billing_address_line2": getattr(user, "billing_address_line2", None),
            "billing_city": getattr(user, "billing_city", None),
            "billing_state": getattr(user, "billing_state", None),
            "billing_postal_code": getattr(user, "billing_postal_code", None),
            "billing_country": getattr(user, "billing_country", None),
            "billing_website_url": getattr(user, "billing_website_url", None),
            "billing_tax_exempt": bool(getattr(user, "billing_tax_exempt", False)),
        },
        "audits": [
            {
                "id": audit.id,
                "url": audit.url,
                "geo_score": audit.geo_score,
                "created_at": audit.created_at.isoformat() if audit.created_at else "",
                "full_report": normalize_persisted_full_report(audit, db),
            }
            for audit in audits
        ],
        "subscription": (
            {
                "plan_type": subscription.plan_type,
                "status": subscription.status,
                "stripe_customer_id": subscription.stripe_customer_id,
                "stripe_subscription_id": subscription.stripe_subscription_id,
                "current_period_end": (
                    subscription.current_period_end.isoformat()
                    if subscription.current_period_end
                    else None
                ),
                "cancel_at_period_end": subscription.cancel_at_period_end,
            }
            if subscription
            else None
        ),
        "billing_payments": [
            {
                "id": payment.id,
                "stripe_invoice_id": payment.stripe_invoice_id,
                "stripe_customer_id": payment.stripe_customer_id,
                "stripe_subscription_id": payment.stripe_subscription_id,
                "amount_paid": payment.amount_paid,
                "amount_due": payment.amount_due,
                "currency": payment.currency,
                "status": payment.status,
                "hosted_invoice_url": payment.hosted_invoice_url,
                "invoice_pdf": payment.invoice_pdf,
                "created_at": payment.created_at.isoformat() if payment.created_at else "",
                "retention_until": effective_retention_until(payment).isoformat(),
            }
            for payment in billing_payments
        ],
        "email_outbox": [
            {
                "id": outbox.id,
                "to_email": outbox.to_email,
                "subject": outbox.subject,
                "html_body": outbox.html_body,
                "text_body": outbox.text_body,
                "category": outbox.category,
                "correlation_id": outbox.correlation_id,
                "status": outbox.status,
                "provider": outbox.provider,
                "attempts": outbox.attempts,
                "last_error": outbox.last_error,
                "created_at": outbox.created_at.isoformat() if outbox.created_at else "",
                "updated_at": outbox.updated_at.isoformat() if outbox.updated_at else "",
                "sent_at": outbox.sent_at.isoformat() if outbox.sent_at else None,
            }
            for outbox in email_outbox_entries
        ],
        "user_credit_adjustments": [
            {
                "id": adjustment.id,
                "user_id": adjustment.user_id,
                "admin_user_id": adjustment.admin_user_id,
                "delta": adjustment.delta,
                "reason": adjustment.reason,
                "created_at": adjustment.created_at.isoformat() if adjustment.created_at else "",
            }
            for adjustment in credit_adjustments
        ],
        "admin_action_logs": [
            {
                "id": log.id,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "metadata": log.metadata_json,
                "created_at": log.created_at.isoformat() if log.created_at else "",
            }
            for log in admin_action_logs
        ],
        "workspaces": workspaces_summary,
    }


@router.delete("/api/v1/users/me", response_model=DataDeletionResponse, tags=["Users"])
def delete_user_data(
    user: Annotated[models.User, Depends(get_current_user)],
    request: DataDeletionRequest,
    db: Session = Depends(get_db),
):
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail=translate_backend_message(
                "errors.confirmation_required_for_delete",
                "Confirmation required to delete data.",
            ),
        )

    user = get_user_or_404(db, user.id)
    user_id = user.id

    # Refuse account deletion while the user owns a workspace with other
    # members: deleting the owner CASCADE-deletes the whole workspace and
    # every other member's projects, audits and connections with it.
    owned_workspaces = db.query(models.Workspace).filter(models.Workspace.owner_id == user_id).all()
    shared_owned_workspaces = []
    for owned_workspace in owned_workspaces:
        other_member_count = (
            db.query(models.WorkspaceUser)
            .filter(
                models.WorkspaceUser.workspace_id == owned_workspace.id,
                models.WorkspaceUser.user_id != user_id,
            )
            .count()
        )
        if other_member_count:
            shared_owned_workspaces.append(
                {
                    "id": owned_workspace.id,
                    "name": owned_workspace.name,
                    "other_members": other_member_count,
                }
            )
    if shared_owned_workspaces:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "workspace_ownership_transfer_required",
                "message": translate_backend_message(
                    "errors.workspace_ownership_transfer_required",
                    "You own a shared workspace. Transfer its ownership to another "
                    "member or remove all members before deleting your account.",
                ),
                "workspaces": shared_owned_workspaces,
            },
        )

    # An active paying subscription must not be silently abandoned: cancel it
    # first so the customer is not charged for an account they believe is gone.
    blocking_subscription = (
        db.query(models.Subscription)
        .filter(
            models.Subscription.user_id == user_id,
            models.Subscription.status.in_(("active", "trialing", "past_due", "unpaid")),
            models.Subscription.cancel_at_period_end.is_(False),
        )
        .first()
    )
    if blocking_subscription:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "active_subscription_cancellation_required",
                "message": translate_backend_message(
                    "errors.active_subscription_cancellation_required",
                    "Cancel your active subscription before deleting your account.",
                ),
            },
        )

    owned_workspace_ids = [workspace.id for workspace in owned_workspaces]
    member_workspace_ids = [
        row.workspace_id
        for row in db.query(models.WorkspaceUser)
        .filter(models.WorkspaceUser.user_id == user_id)
        .all()
        if row.workspace_id not in owned_workspace_ids
    ]
    session_jtis = [
        row.token_jti
        for row in db.query(models.UserSession).filter(models.UserSession.user_id == user_id).all()
        if row.token_jti
    ]

    deletion_completed_at = datetime.now(timezone.utc)
    deleted_audits = 0
    deleted_subscription = 0
    retained_invoices = RetainedInvoices(retained_count=0, retained_until=None)
    deletion_receipt_reference = ""
    deleted_email_outbox_entries = 0
    deleted_user_credit_adjustments = 0
    anonymized_admin_action_logs = 0
    anonymized_credit_adjustments_as_admin = 0
    removed_workspace_memberships = 0
    deleted_project_oauth_connections = 0

    try:
        # Member (not owner) of other workspaces: remove only their membership;
        # another member's data must never be touched. Workspace-level
        # OAuthConnection rows are deliberately left alone: they are one shared
        # row per provider with no attribution to the person who authorised
        # them, so deleting them would destroy other members' integrations.
        if member_workspace_ids:
            removed_workspace_memberships = (
                db.query(models.WorkspaceUser)
                .filter(
                    models.WorkspaceUser.user_id == user_id,
                    models.WorkspaceUser.workspace_id.in_(member_workspace_ids),
                )
                .delete(synchronize_session=False)
            )
        deleted_project_oauth_connections = (
            db.query(models.ProjectOAuthConnection)
            .filter(models.ProjectOAuthConnection.connected_by_email == user.email)
            .delete(synchronize_session=False)
        )
        deleted_audits = (
            db.query(models.Audit)
            .filter(models.Audit.user_id == user_id)
            .delete(synchronize_session=False)
        )
        deleted_subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.user_id == user_id)
            .delete(synchronize_session=False)
        )
        # Invoices are statutory tax records, not account data: they are
        # anonymised in place and kept, never deleted (SIGV2-1144).
        retained_invoices = anonymize_billing_payments_for_user(
            db, user=user, now=deletion_completed_at
        )
        deleted_email_outbox_entries = (
            db.query(models.EmailOutbox)
            .filter(models.EmailOutbox.user_id == user_id)
            .delete(synchronize_session=False)
        )
        deleted_user_credit_adjustments = (
            db.query(models.UserCreditAdjustment)
            .filter(models.UserCreditAdjustment.user_id == user_id)
            .delete(synchronize_session=False)
        )
        anonymized_credit_adjustments_as_admin = (
            db.query(models.UserCreditAdjustment)
            .filter(models.UserCreditAdjustment.admin_user_id == user_id)
            .update({models.UserCreditAdjustment.admin_user_id: None}, synchronize_session=False)
        )
        anonymized_admin_action_logs = (
            db.query(models.AdminActionLog)
            .filter(models.AdminActionLog.admin_user_id == user_id)
            .update(
                {
                    models.AdminActionLog.admin_user_id: None,
                    models.AdminActionLog.metadata_json: {"admin_user_deleted": True},
                },
                synchronize_session=False,
            )
        )
        # The receipt is written before the user row goes, inside the same
        # transaction, so there is no state where the account is gone and
        # nothing evidences the request (SIGV2-1144).
        deletion_receipt = record_account_deletion_receipt(
            db,
            user=user,
            now=deletion_completed_at,
            initiated_by="self_service",
            erased_record_counts={
                "audits": deleted_audits,
                "subscriptions": deleted_subscription,
                "email_outbox_entries": deleted_email_outbox_entries,
                "user_credit_adjustments": deleted_user_credit_adjustments,
                "workspace_memberships": removed_workspace_memberships,
                "project_oauth_connections": deleted_project_oauth_connections,
            },
            retained_invoices=retained_invoices,
        )
        deletion_receipt_reference = deletion_receipt.reference
        db.query(models.User).filter(models.User.id == user_id).delete(synchronize_session=False)
        db.commit()

    except Exception as e:
        db.rollback()
        logger.error("Failed to delete data for user %s: %s", user_id, e)
        raise HTTPException(
            status_code=500,
            detail=translate_backend_message(
                "errors.delete_user_data_failed", "Failed to delete user data."
            ),
        )

    # Revoke every session JTI so in-flight access tokens stop working
    # immediately, not only at token expiry. Best-effort: the user rows are
    # already gone, so a Redis outage must not fail the deletion response - but
    # it must not be reported as a clean revocation either (SIGV2-1251). One
    # event loop for every JTI, and a partial outcome is logged at ERROR and
    # surfaced on the response instead of hiding behind a bare count.
    revoked_sessions = 0
    if session_jtis:
        try:
            revoked_sessions = asyncio.run(revoke_session_jtis(session_jtis))
        except Exception:
            logger.exception(
                "Session revocation failed entirely for deleted user %s (%s sessions)",
                user_id,
                len(session_jtis),
            )
    failed_session_revocations = len(session_jtis) - revoked_sessions
    if failed_session_revocations:
        logger.error(
            "Partial session revocation for deleted user %s: %s of %s sessions could not be "
            "revoked. In-flight access tokens for those sessions stay valid until expiry.",
            user_id,
            failed_session_revocations,
            len(session_jtis),
        )

    logger.info(
        "User data deleted for user_id=%s receipt=%s retained_invoices=%s",
        user_id,
        deletion_receipt_reference,
        retained_invoices.retained_count,
    )

    return {
        "user_id": user_id,
        "deleted_audits": deleted_audits,
        "deleted_subscription": deleted_subscription > 0,
        "retained_billing_payments": retained_invoices.retained_count,
        "billing_records_retained_until": (
            retained_invoices.retained_until.isoformat()
            if retained_invoices.retained_until
            else None
        ),
        "deletion_receipt_reference": deletion_receipt_reference,
        "deleted_email_outbox_entries": deleted_email_outbox_entries,
        "deleted_user_credit_adjustments": deleted_user_credit_adjustments,
        "anonymized_admin_action_logs": anonymized_admin_action_logs,
        "anonymized_credit_adjustments_as_admin": anonymized_credit_adjustments_as_admin,
        "removed_workspace_memberships": removed_workspace_memberships,
        "revoked_sessions": revoked_sessions,
        "failed_session_revocations": failed_session_revocations,
        "session_revocation_complete": not failed_session_revocations,
        "deleted_project_oauth_connections": deleted_project_oauth_connections,
        "message": "Account data deleted successfully.",
    }


# ---------------------------------------------------------------------------
# Admin: Trial Management
# ---------------------------------------------------------------------------


class AdminActivateTrialRequest(BaseModel):
    user_id: int
    duration_days: int = 14
    credits: int = 100
    max_audits: int = 5


class AdminTrialResponse(BaseModel):
    user_id: int
    trial_plan: str | None
    trial_started_at: str | None
    trial_ends_at: str | None
    trial_audits_used: int
    trial_max_audits: int
    trial_initial_credits: int
    credits: int


@router.post("/api/v1/admin/trial/activate", response_model=AdminTrialResponse, tags=["Admin"])
def admin_activate_trial(
    request: AdminActivateTrialRequest,
    admin: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Reject new and repeated trial grants."""
    if str(getattr(admin, "role", "")).strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    raise HTTPException(status_code=410, detail="Agency Trial is no longer available.")


@router.post("/api/v1/admin/trial/revoke", tags=["Admin"])
def admin_revoke_trial(
    request: AdminActivateTrialRequest,
    admin: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Admin endpoint to revoke a trial for any user."""
    if str(getattr(admin, "role", "")).strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    target_user = db.query(models.User).filter(models.User.id == request.user_id).first()
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found.")

    target_user.trial_plan = None
    target_user.trial_started_at = None
    target_user.trial_ends_at = None
    target_user.trial_audits_used = 0
    target_user.trial_max_audits = 5
    target_user.trial_initial_credits = 100
    target_user.trial_concierge_completed = False
    db.commit()

    return {"status": "ok", "user_id": target_user.id, "message": "Trial revoked."}


# ---------------------------------------------------------------------------
# Developer, Internal OpenAPI Spec (JWT-protected, for dashboard Swagger UI)
# ---------------------------------------------------------------------------


@router.get("/api/v1/developer/openapi-spec", tags=["Developer"])
def developer_openapi_spec(
    request: Request,
    user: models.User = Depends(get_current_user),
):
    """Return the filtered external-API OpenAPI spec for the dashboard API reference viewer."""
    app = request.app
    full_spec = app.openapi()
    external_paths = {}
    for path, methods in (full_spec.get("paths") or {}).items():
        if path.startswith("/external/") or "/external/" in path:
            external_paths[path] = methods
    return {
        "openapi": full_spec.get("openapi", "3.1.0"),
        "info": {
            "title": "Qiko Signal External API",
            "version": full_spec.get("info", {}).get("version", "1.0.0"),
            "description": "Headless API for programmatic audit execution, project data retrieval, scheduled audits, and webhook delivery.",
        },
        "servers": [{"url": "/api/v1", "description": "Default"}],
        "paths": external_paths,
        "components": full_spec.get("components", {}),
    }
