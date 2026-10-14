from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import re
from datetime import date, datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Literal
from urllib.parse import urlencode
from urllib.parse import quote
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.params import Param
from fastapi.responses import RedirectResponse
from core.password_hashing import hash_password
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from sqlalchemy import and_, func
from sqlalchemy.orm import Session

import models
from auth.credits import (
    PROMPT_RECOMMENDATION_CREDIT_COST,
    calculate_audit_credit_cost,
    decrement_credits_atomic,
    increment_credits_atomic,
)
from auth.security import get_current_user_from_token as get_current_user
from app.config.plans import can_use_feature, resolve_entitled_subscription_plan, resolve_plan_alias
from app.services.advisor_plan_snapshot_service import (
    build_plan_progress,
    list_snapshots,
)
from app.services.brand_facts_service import (
    create_brand_fact,
    delete_brand_fact,
    list_brand_facts,
)
from app.services.learnings_service import (
    decision_key,
    dismissed_fingerprints,
    list_decisions,
    record_decision,
)
from core.iso_country_codes import is_valid_iso_country_code
from core.redis_client import get_async_redis
from database import get_db
from schemas.auth import normalize_company_name
from schemas.annotations import (
    AnnotationCreateRequest,
    AnnotationResponse,
    AnnotationThreadPageResponse,
    AnnotationUpdateRequest,
)
from schemas.claim_reviews import (
    ClaimReviewQueueResponse,
    ClaimReviewRequest,
    ClaimReviewDecisionResponse,
    ClaimReviewSummaryResponse,
)
from services.auth_service import AuthService
from services.ai_engine import AIFactory
from services.audit_helpers import resolve_subscription_plan as resolve_shared_subscription_plan
from services.audit_normalization_service import (
    build_normalized_audit_report,
    normalize_audit_target_type,
    resolve_audit_normalization_current_plan,
    resolve_audit_effective_scores,
    resolve_audit_target_metadata as resolve_audit_target_metadata_contract,
    resolve_audit_target_name as resolve_audit_target_name_contract,
    resolve_audit_target_url as resolve_audit_target_url_contract,
)
from services.ai_routing_policy import resolve_prompt_ai_route
from services.base_prompt_service import ensure_base_prompts
from services.cloudflare_custom_hostname_service import (
    delete_cloudflare_custom_hostname,
    is_cloudflare_custom_hostname_configured,
)
from services.custom_domain_service import (
    apply_workspace_branding,
    create_workspace_custom_domain,
    delete_workspace_custom_domain,
    is_tls_host_allowed,
    list_workspace_custom_domains,
    normalize_custom_domain,
    normalize_hex_color,
    normalize_optional_url,
    resolve_custom_domain_cname_target,
    resolve_workspace_branding,
    resolve_workspace_for_tenant_context,
    serialize_custom_domain,
    verify_workspace_custom_domain,
)
from services import smart_profile_service
from services.portal_service import resolve_workspace_owner_plan
from services.project_score_target_service import resolve_project_score_targets
from services.tenant_context import get_active_workspace_id
from services.email_service import EmailService
from services.oauth_service import oauth
from services.report_annotation_service import (
    annotation_write_allowed,
    build_annotation_response,
    create_annotation,
    delete_annotation,
    get_annotation_or_404,
    list_annotations,
    queue_annotation_notifications,
    update_annotation,
)
from services.claim_review_service import claim_review_service
from services.project_progress_service import (
    build_project_period_comparison,
    build_project_trend_payload,
    build_workspace_trends_overview,
    generate_project_progress_report,
)
from services.project_intelligence_service import (
    build_project_feature_access,
    select_project_module_audit,
)
from services.project_task_service import (
    build_project_task_impact_payload,
    build_project_task_summary,
    resolve_task_recommendation_key,
    sync_project_tasks,
    task_assignee_belongs_to_workspace,
)
from services.project_audit_scope import (
    AUDIT_PROJECT_SCOPE_COMPETITOR,
    own_project_audit_clause,
)
from services.project_visibility_service import compute_search_type_measurements
from services.project_competitive_service import (
    MAX_PROJECT_COMPETITORS,
    add_project_competitor,
    build_project_competitive_ai_prompt,
    build_project_competitive_analysis,
    build_project_competitive_gaps,
    build_project_competitive_trends,
    build_project_competitor_request_id,
    delete_project_competitor,
    ensure_project_competitor_snapshot_pending,
    get_latest_project_competitive_source_audit,
    list_project_competitors,
    mark_project_competitor_snapshot_failed,
    replace_project_competitors_from_urls,
)
from services.project_budget_service import (
    delete_project_budget,
    get_project_budget_snapshot,
    list_recent_project_budget_periods,
    normalize_cycle_anchor_day,
    upsert_project_budget,
)
from services.project_service import (
    archive_project,
    clone_project,
    unarchive_project,
)
from services.onboarding_service import (
    bulk_invite_clients,
    onboard_client,
)
from services.workspace_intelligence_service import (
    create_invitation,
    get_client_health,
    list_invitations,
    list_workspace_activity,
    log_workspace_activity,
    resend_invitation,
    revoke_invitation,
)
from services.reports.audit_result_adapter import (
    extract_canonical_entities,
    extract_normalized_recommendation_texts,
)
from services.workspace_rbac import (
    WORKSPACE_WRITE_ROLES,
    replace_client_project_assignments,
    require_workspace_admin_access as require_workspace_admin_access_service,
    require_workspace_manage_access as require_workspace_manage_access_service,
    require_workspace_write_access as require_workspace_write_access_service,
    resolve_project_access as resolve_project_access_service,
    resolve_workspace_access as resolve_workspace_access_service,
    role_value as workspace_role_value,
)
from services.url_validation import normalize_and_validate_url, sync_request_with_validation
from operational_settings import get_report_retention_days

router = APIRouter(tags=["Workspace"])
logger = logging.getLogger(__name__)
prompt_ai_factory = AIFactory()

from services.queue_routing import resolve_queue_for_tier


def _query_value(value: Any) -> Any:
    if isinstance(value, Param):
        return value.default
    return value


PROJECT_SOURCE_TYPE_TO_PROVIDER: dict[models.ProjectDataSourceType, models.OAuthProvider] = {
    models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE: models.OAuthProvider.GOOGLE,
    models.ProjectDataSourceType.GOOGLE_ANALYTICS_4: models.OAuthProvider.GOOGLE,
    models.ProjectDataSourceType.BING_WEBMASTER: models.OAuthProvider.BING,
}
REQUIRED_SCOPE_ALIASES_BY_SOURCE_TYPE: dict[
    models.ProjectDataSourceType,
    tuple[tuple[str, ...], ...],
] = {
    models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE: (
        (
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/webmasters",
            "webmasters.readonly",
            "webmasters",
            "gsc.read",
        ),
    ),
    models.ProjectDataSourceType.GOOGLE_ANALYTICS_4: (
        (
            "https://www.googleapis.com/auth/analytics.readonly",
            "https://www.googleapis.com/auth/analytics",
            "analytics.readonly",
            "analytics",
            "ga4.read",
        ),
    ),
    models.ProjectDataSourceType.BING_WEBMASTER: (
        (
            "webmaster.manage",
            "webmaster",
            "manage",
        ),
    ),
}
MAGIC_LINK_PROVIDER_SOURCE_TYPES: dict[
    models.OAuthProvider, tuple[models.ProjectDataSourceType, ...]
] = {
    models.OAuthProvider.GOOGLE: (
        models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
        models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
    ),
    models.OAuthProvider.BING: (models.ProjectDataSourceType.BING_WEBMASTER,),
}


def _resolve_smart_profile_ai_credit_cost() -> int:
    raw_value = os.getenv("SMART_PROFILE_AI_CREDIT_COST", "1")
    try:
        return max(1, int(raw_value or "1"))
    except ValueError:
        logger.warning(
            "Invalid SMART_PROFILE_AI_CREDIT_COST=%s; defaulting to 1",
            raw_value,
        )
        return 1


SMART_PROFILE_AI_CREDIT_COST = _resolve_smart_profile_ai_credit_cost()
SMART_PROFILE_AI_MODEL = smart_profile_service.resolve_smart_profile_model()
SMART_PROFILE_REQUIRED_FIELDS: tuple[tuple[str, str], ...] = (
    ("name", "Reference Name"),
    ("domain_url", "Primary Vector (URL)"),
    ("target_country", "Target Market (ISO)"),
    ("language", "Language Node"),
)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_domain_url(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if not normalized.startswith("http://") and not normalized.startswith("https://"):
        normalized = f"https://{normalized}"
    return normalize_and_validate_url(normalized.lower())


def _normalize_tracker_context_key(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return "workspace"

    try:
        parsed = urlparse(normalized)
    except Exception:
        parsed = None

    if parsed and parsed.netloc:
        host = parsed.netloc.strip().lower()
        if host.startswith("www."):
            host = host[4:]
        path = (parsed.path or "/").strip() or "/"
        if path != "/":
            path = path.rstrip("/")
        return f"{host}{path}"[:500] or "workspace"

    return normalized[:500] or "workspace"


def _serialize_aeo_query_tracker_entry(
    entry: models.AeoQueryTrackerEntry,
) -> dict[str, Any]:
    return {
        "query": str(entry.query or "").strip(),
        "tracked_at": _isoformat(_as_utc_datetime(entry.tracked_at)),
        "citation_hits": max(0, int(entry.citation_hits or 0)),
    }


def _serialize_geo_prompt_tracker_entry(
    entry: models.GeoPromptTrackerEntry,
) -> dict[str, Any]:
    return {
        "prompt": str(entry.prompt or "").strip(),
        "tracked_at": _isoformat(_as_utc_datetime(entry.tracked_at)),
        "citation_hits": max(0, int(entry.citation_hits or 0)),
    }


def _resolve_frontend_base_url() -> str:
    frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
    app_base_url = (os.getenv("APP_BASE_URL") or "").strip()
    return (frontend_url or app_base_url or "http://localhost:3000").rstrip("/")


# SIGV2-1220: the only places an OAuth return may land. Connecting GA4 from
# onboarding step 4 is a full browser navigation, so the callback decides where
# the customer comes back to, and every return used to be hard-coded to the
# Connections Hub - which dropped the customer out of the wizard mid-flow.
#
# This is a closed map of keys to internal paths, never a URL a caller supplies.
# The start request names a key, the key is validated there and again in the
# callback, and anything unrecognised resolves to the Hub. Nothing sent from
# outside can become the redirect target, so no open redirect is reachable
# through the return.
_OAUTH_RETURN_DESTINATIONS: dict[str, str] = {
    "connections": "/dashboard/connections",
    "onboarding": "/dashboard/overview",
}
_DEFAULT_OAUTH_RETURN = "connections"


def _resolve_oauth_return_path(return_to: object) -> str:
    if isinstance(return_to, str):
        path = _OAUTH_RETURN_DESTINATIONS.get(return_to)
        if path is not None:
            return path
    return _OAUTH_RETURN_DESTINATIONS[_DEFAULT_OAUTH_RETURN]


def _build_oauth_return_url(
    *,
    provider: str,
    status: str,
    message: str | None = None,
    return_to: object = _DEFAULT_OAUTH_RETURN,
) -> str:
    params = {"provider": provider, "status": status}
    if message:
        params["message"] = message
    path = _resolve_oauth_return_path(return_to)
    return f"{_resolve_frontend_base_url()}{path}?{urlencode(params)}"


def _build_connections_return_url(*, provider: str, status: str, message: str | None = None) -> str:
    return _build_oauth_return_url(provider=provider, status=status, message=message)


def _build_magic_link_return_url(
    *,
    token: str,
    provider: str | None = None,
    status: str | None = None,
    message: str | None = None,
) -> str:
    params: dict[str, str] = {}
    if provider:
        params["provider"] = provider
    if status:
        params["status"] = status
    if message:
        params["message"] = message
    encoded_token = quote(token, safe="")
    base_url = f"{_resolve_frontend_base_url()}/connect/{encoded_token}"
    if not params:
        return base_url
    return f"{base_url}?{urlencode(params)}"


def _build_oauth_callback_uri(
    request: Request,
    *,
    route_name: str,
    route_params: dict[str, str | int] | None = None,
) -> str:
    callback_uri = str(request.url_for(route_name, **(route_params or {})))
    public_backend_url = (os.getenv("BACKEND_PUBLIC_URL") or "").strip()
    if not public_backend_url:
        return callback_uri

    parsed_public = urlparse(public_backend_url)
    callback_target = urlparse(callback_uri)
    callback_path = callback_target.path + (
        f"?{callback_target.query}" if callback_target.query else ""
    )
    if parsed_public.scheme and parsed_public.netloc:
        base_path = parsed_public.path.rstrip("/")
        return f"{parsed_public.scheme}://{parsed_public.netloc}{base_path}{callback_path}"
    return callback_uri


def _workspace_oauth_session_key(provider: str) -> str:
    return f"workspace_{provider}_oauth"


def _magic_link_oauth_session_key(provider: str) -> str:
    return f"magic_link_{provider}_oauth"


def _role_value(value: models.WorkspaceRole | str) -> str:
    return workspace_role_value(value)


def _default_workspace_name(user: models.User) -> str:
    company_name = str(getattr(user, "company_name", "") or "").strip()
    if company_name:
        return f"{company_name} Workspace"
    local_part = (user.email or "workspace").split("@", maxsplit=1)[0].strip() or "workspace"
    return f"{local_part} Workspace"


def _ensure_workspace_owner_membership(workspace: models.Workspace, db: Session) -> None:
    existing_membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == workspace.owner_id,
        )
        .first()
    )
    if existing_membership:
        if _role_value(existing_membership.role) != models.WorkspaceRole.ADMIN.value:
            existing_membership.role = models.WorkspaceRole.ADMIN
            db.commit()
        return

    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=workspace.owner_id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    db.commit()


def _get_or_create_current_workspace(db: Session, user: models.User) -> models.Workspace:
    # Custom-domain tenant context always wins.
    tenant_workspace = resolve_workspace_for_tenant_context(db, user=user)
    if tenant_workspace is not None:
        return tenant_workspace

    # Honour an explicit workspace selection sent via X-Workspace-Id header.
    requested_id = get_active_workspace_id()
    if requested_id is not None:
        workspace = db.query(models.Workspace).filter(models.Workspace.id == requested_id).first()
        if workspace is not None:
            has_access = workspace.owner_id == user.id or (
                db.query(models.WorkspaceUser.id)
                .filter(
                    models.WorkspaceUser.workspace_id == requested_id,
                    models.WorkspaceUser.user_id == user.id,
                )
                .first()
                is not None
            )
            if has_access:
                return workspace
        # If the requested workspace doesn't exist or the user has no access,
        # fall through to the default resolution below.

    workspace = (
        db.query(models.Workspace)
        .filter(models.Workspace.owner_id == user.id)
        .order_by(models.Workspace.created_at.asc(), models.Workspace.id.asc())
        .first()
    )
    if workspace:
        _ensure_workspace_owner_membership(workspace, db)
        return workspace

    membership = (
        db.query(models.WorkspaceUser)
        .filter(models.WorkspaceUser.user_id == user.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .first()
    )
    if membership:
        workspace = (
            db.query(models.Workspace)
            .filter(models.Workspace.id == membership.workspace_id)
            .first()
        )
        if workspace:
            return workspace

    workspace = models.Workspace(name=_default_workspace_name(user), owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    _ensure_workspace_owner_membership(workspace, db)
    return workspace


def _resolve_workspace_access(
    db: Session, *, user: models.User, workspace_id: int, allow_client_readonly: bool = False
) -> tuple[models.Workspace, str]:
    access = resolve_workspace_access_service(
        db,
        user=user,
        workspace_id=workspace_id,
        allow_client_readonly=allow_client_readonly,
    )
    return access.workspace, access.role


def _resolve_project_access(
    db: Session, *, user: models.User, project_id: int, allow_client_readonly: bool = False
) -> tuple[models.Project, models.Workspace, str]:
    access = resolve_project_access_service(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=allow_client_readonly,
    )
    return access.project, access.workspace, access.role


def _resolve_audit_access(
    db: Session,
    *,
    user: models.User,
    audit_id: int,
    allow_client_readonly: bool = False,
) -> tuple[models.Audit, models.Project, models.Workspace, str]:
    audit = db.query(models.Audit).filter(models.Audit.id == audit_id).first()
    if audit is None:
        raise HTTPException(status_code=404, detail="Audit not found.")
    if audit.project_id is None:
        raise HTTPException(status_code=400, detail="Audit is not linked to a workspace project.")

    project, workspace, role = _resolve_project_access(
        db,
        user=user,
        project_id=audit.project_id,
        allow_client_readonly=allow_client_readonly,
    )
    return audit, project, workspace, role


def _require_workspace_write_access(role: str) -> None:
    require_workspace_write_access_service(role)


def _require_workspace_admin_access(role: str) -> None:
    require_workspace_admin_access_service(role)


def _require_workspace_manage_access(role: str) -> None:
    require_workspace_manage_access_service(role)


def _resolve_subscription_plan(user: models.User | None) -> str:
    # SIGV2-1220: this used to be a second, divergent resolver that discarded
    # an entitled `plan_agency_trial` subscription. A trial whose entitlement
    # sits on the subscription row rather than the legacy `trial_plan` column
    # therefore resolved to Starter, and onboarding answered "Competitive
    # Intelligence is available on Specialist" to a trial the shared
    # capability matrix grants it. The shared resolver is the one source of
    # truth: a non-entitled status still yields no plan, so expired,
    # delinquent and cancelled trials stay restricted exactly as before.
    return resolve_shared_subscription_plan(user)


def _require_plan_feature(
    user: models.User | None,
    *,
    feature_key: str,
    detail: str,
    status_code: int = status.HTTP_402_PAYMENT_REQUIRED,
) -> None:
    if not can_use_feature(_resolve_subscription_plan(user), feature_key):
        raise HTTPException(status_code=status_code, detail=detail)


def _require_workspace_white_label_plan(db: Session, workspace: models.Workspace) -> None:
    owner_plan = resolve_workspace_owner_plan(db, workspace=workspace)
    if can_use_feature(owner_plan, "has_white_label"):
        return
    raise HTTPException(status_code=402, detail="White-label is available on the Executive plan")


def _resolve_subscription_plan_alias(user: models.User | None) -> str:
    resolved = resolve_plan_alias(resolve_entitled_subscription_plan(user))
    return resolved or "plan_starter"


def _require_competitive_settings_plan(
    user: models.User | None,
    updates: dict[str, Any],
) -> None:
    if not any(
        field_name in updates
        for field_name in (
            "competitors",
            "auto_competitor_audits_enabled",
            "competitive_digest_frequency",
        )
    ):
        return

    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )


def _serialize_workspace(
    workspace: models.Workspace,
    *,
    current_user_id: int,
    role: str,
    project_count: int,
    member_count: int,
    oauth_connection_count: int,
) -> dict[str, object]:
    return {
        "id": workspace.id,
        "name": workspace.name,
        "owner_id": workspace.owner_id,
        "created_at": _isoformat(workspace.created_at),
        "role": role,
        "is_owner": workspace.owner_id == current_user_id,
        "project_count": project_count,
        "member_count": member_count,
        "oauth_connection_count": oauth_connection_count,
        "role_mode": workspace.role_mode,
    }


def _serialize_white_label_settings(
    *,
    db: Session,
    workspace: models.Workspace,
) -> dict[str, object]:
    branding = resolve_workspace_branding(workspace)
    domains = [
        serialize_custom_domain(item)
        for item in list_workspace_custom_domains(db, workspace_id=workspace.id)
    ]
    return {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "company_name": branding["company_name"],
        "custom_logo_url": branding["custom_logo_url"],
        "primary_color": branding["primary_color"],
        "secondary_color": branding["secondary_color"],
        "custom_favicon_url": branding["custom_favicon_url"],
        "custom_page_title": branding["custom_page_title"],
        "custom_meta_description": branding["custom_meta_description"],
        "hide_powered_by": branding["hide_powered_by"],
        "email_sender_name": branding["email_sender_name"],
        "email_reply_to": branding["email_reply_to"],
        "social_facebook_url": branding["social_facebook_url"],
        "social_x_url": branding["social_x_url"],
        "social_instagram_url": branding["social_instagram_url"],
        "social_linkedin_url": branding["social_linkedin_url"],
        "social_youtube_url": branding["social_youtube_url"],
        "social_tiktok_url": branding["social_tiktok_url"],
        "company_address": branding["company_address"],
        "company_legal_name": branding["company_legal_name"],
        "company_trademark_text": branding["company_trademark_text"],
        "footer_about_url": branding["footer_about_url"],
        "footer_blog_url": branding["footer_blog_url"],
        "footer_support_url": branding["footer_support_url"],
        "footer_legal_url": branding["footer_legal_url"],
        "footer_preferences_url": branding["footer_preferences_url"],
        "footer_privacy_url": branding["footer_privacy_url"],
        "dns_target": resolve_custom_domain_cname_target(),
        "domains": domains,
    }


def _serialize_workspace_email_footer_settings(
    *,
    workspace: models.Workspace,
) -> dict[str, object]:
    branding = resolve_workspace_branding(workspace)
    return {
        "workspace_id": workspace.id,
        "workspace_name": workspace.name,
        "social_facebook_url": branding["social_facebook_url"],
        "social_x_url": branding["social_x_url"],
        "social_instagram_url": branding["social_instagram_url"],
        "social_linkedin_url": branding["social_linkedin_url"],
        "social_youtube_url": branding["social_youtube_url"],
        "social_tiktok_url": branding["social_tiktok_url"],
        "company_address": branding["company_address"],
        "company_legal_name": branding["company_legal_name"],
        "company_trademark_text": branding["company_trademark_text"],
        "footer_about_url": branding["footer_about_url"],
        "footer_blog_url": branding["footer_blog_url"],
        "footer_support_url": branding["footer_support_url"],
        "footer_legal_url": branding["footer_legal_url"],
        "footer_preferences_url": branding["footer_preferences_url"],
        "footer_privacy_url": branding["footer_privacy_url"],
    }


def _serialize_project(
    project: models.Project,
    *,
    user: models.User | None = None,
    audit_count: int = 0,
    last_audit_at: datetime | None = None,
    latest_seo_score: float | None = None,
    latest_geo_score: float | None = None,
    latest_aeo_score: float | None = None,
) -> dict[str, object]:
    project_status = getattr(project, "status", None)
    status_value = (
        project_status.value
        if isinstance(project_status, models.ProjectStatus)
        else str(project_status or "active")
    )
    return {
        "id": project.id,
        "workspace_id": project.workspace_id,
        "name": project.name,
        "domain_url": project.domain_url,
        "target_country": project.target_country,
        "language": project.language,
        "icp_roles": list(project.icp_roles or []),
        "pain_points": project.pain_points,
        "usp": project.usp,
        "competitors": list(project.competitors_json or []),
        "auto_competitor_audits_enabled": bool(project.auto_competitor_audits_enabled),
        "competitive_digest_frequency": (
            project.competitive_digest_frequency.value
            if isinstance(project.competitive_digest_frequency, models.CompetitiveDigestFrequency)
            else str(project.competitive_digest_frequency or "weekly")
        ),
        "priority_pulse_tags": list(project.priority_pulse_tags or []),
        "sme_profiles": list(project.sme_profiles or []),
        "tags": list(getattr(project, "tags", None) or []),
        "status": status_value,
        "cloned_from_id": getattr(project, "cloned_from_id", None),
        "archived_at": _isoformat(getattr(project, "archived_at", None)),
        "created_at": _isoformat(project.created_at),
        "audit_count": int(audit_count),
        "last_audit_at": _isoformat(last_audit_at),
        "latest_seo_score": latest_seo_score,
        "latest_geo_score": latest_geo_score,
        "latest_aeo_score": latest_aeo_score,
        "score_targets": resolve_project_score_targets(
            project,
            latest_seo_score=latest_seo_score,
            latest_geo_score=latest_geo_score,
            latest_aeo_score=latest_aeo_score,
            measured_at=_isoformat(last_audit_at),
        ),
        "feature_access": build_project_feature_access(user),
    }


def _serialize_project_budget_response(
    db: Session,
    *,
    project: models.Project,
    recent_periods: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    snapshot = get_project_budget_snapshot(db, project_id=project.id)
    return {
        "project_id": project.id,
        "workspace_id": project.workspace_id,
        "project_name": project.name,
        "domain_url": project.domain_url,
        "budget_configured": snapshot.monthly_limit_scans is not None,
        "monthly_limit_scans": snapshot.monthly_limit_scans,
        "cycle_anchor_day": snapshot.cycle_anchor_day,
        "current_period_start": snapshot.current_period_start.isoformat(),
        "current_period_end": snapshot.current_period_end.isoformat(),
        "consumed_scans": snapshot.consumed_scans,
        "remaining_scans": snapshot.remaining_scans,
        "percent_consumed": snapshot.percent_consumed,
        "status": snapshot.status,
        "warning_threshold_reached": snapshot.warning_threshold_reached,
        "limit_reached": snapshot.limit_reached,
        "recent_periods": recent_periods
        or list_recent_project_budget_periods(db, project_id=project.id),
    }


def _serialize_project_progress_report(
    report: models.ProjectProgressReport,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    snapshot = report.snapshot_json if isinstance(report.snapshot_json, dict) else {}
    project_snapshot = snapshot.get("project") if isinstance(snapshot.get("project"), dict) else {}
    created_at = _as_utc_datetime(report.created_at)
    reference_now = now or datetime.now(timezone.utc)
    expired = created_at is not None and created_at < (
        reference_now - timedelta(days=max(1, int(retention_days)))
    )
    return {
        "id": report.id,
        "project_id": report.project_id,
        "workspace_id": report.workspace_id,
        "report_month": report.report_month.isoformat(),
        "period_start": report.period_start.isoformat(),
        "period_end": report.period_end.isoformat(),
        "generated_by": report.generated_by,
        "recipient_count": int(report.recipient_count or 0),
        "email_sent_at": _isoformat(report.email_sent_at),
        "created_at": _isoformat(report.created_at),
        "language": (
            snapshot.get("report_language")
            if isinstance(snapshot.get("report_language"), str)
            else project_snapshot.get("language")
            if isinstance(project_snapshot.get("language"), str)
            else "en"
        ),
        "expired": expired,
        "retention_days": retention_days,
        "snapshot": snapshot,
    }


def _workspace_member_directory(
    db: Session,
    *,
    workspace: models.Workspace,
) -> dict[int, dict[str, Any]]:
    directory: dict[int, dict[str, Any]] = {}

    owner = db.query(models.User).filter(models.User.id == workspace.owner_id).first()
    if owner is not None:
        directory[owner.id] = {
            "user_id": owner.id,
            "email": owner.email,
            "role": models.WorkspaceRole.ADMIN.value,
            "is_owner": True,
        }

    memberships = (
        db.query(models.WorkspaceUser, models.User)
        .join(models.User, models.User.id == models.WorkspaceUser.user_id)
        .filter(models.WorkspaceUser.workspace_id == workspace.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .all()
    )
    for membership, member_user in memberships:
        role_value = (
            membership.role.value
            if isinstance(membership.role, models.WorkspaceRole)
            else str(membership.role)
        )
        existing = directory.get(member_user.id)
        if existing is not None and existing.get("is_owner"):
            continue
        directory[member_user.id] = {
            "user_id": member_user.id,
            "email": member_user.email,
            "role": role_value,
            "is_owner": workspace.owner_id == member_user.id,
        }

    return directory


def _serialize_project_task(
    task: models.ProjectTask,
    *,
    member_directory: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    assignee = (
        member_directory.get(task.assigned_to_user_id)
        if task.assigned_to_user_id is not None
        else None
    )
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": task.status.value
        if isinstance(task.status, models.ProjectTaskStatus)
        else str(task.status),
        "priority": task.priority.value
        if isinstance(task.priority, models.ProjectTaskPriority)
        else str(task.priority),
        "origin": task.origin.value
        if isinstance(task.origin, models.ProjectTaskOrigin)
        else str(task.origin),
        "category": task.category,
        "source_audit_id": task.source_audit_id,
        "source_recommendation_key": task.source_recommendation_key,
        "assigned_to_user_id": task.assigned_to_user_id,
        "assignee": assignee,
        "due_date": task.due_date.isoformat() if task.due_date is not None else None,
        "resolved_at": _isoformat(_as_utc_datetime(task.resolved_at)),
        "verified_at": _isoformat(_as_utc_datetime(task.verified_at)),
        "verification_audit_id": task.verification_audit_id,
        "resolution_source": task.resolution_source.value
        if isinstance(task.resolution_source, models.ProjectTaskResolutionSource)
        else str(task.resolution_source)
        if task.resolution_source
        else None,
        "sort_order": int(task.sort_order or 0),
        "created_at": _isoformat(_as_utc_datetime(task.created_at)),
        "updated_at": _isoformat(_as_utc_datetime(task.updated_at)),
    }


def _serialize_project_task_board(
    db: Session,
    *,
    project: models.Project,
    workspace: models.Workspace,
    role: str,
    tasks: list[models.ProjectTask],
) -> dict[str, Any]:
    member_directory = _workspace_member_directory(db, workspace=workspace)
    latest_audit = (
        db.query(models.Audit.id, models.Audit.created_at)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    assignees = sorted(
        member_directory.values(),
        key=lambda item: (
            not bool(item.get("is_owner")),
            str(item.get("role") or ""),
            str(item.get("email") or ""),
        ),
    )
    return {
        "project_id": project.id,
        "workspace_id": workspace.id,
        "can_edit": workspace_role_value(role) in WORKSPACE_WRITE_ROLES,
        "latest_audit_id": int(latest_audit.id) if latest_audit is not None else None,
        "latest_audit_at": _isoformat(_as_utc_datetime(latest_audit.created_at))
        if latest_audit is not None
        else None,
        "assignees": assignees,
        "summary": build_project_task_summary(tasks),
        "tasks": [
            _serialize_project_task(task, member_directory=member_directory)
            for task in sorted(
                tasks,
                key=lambda item: (
                    {
                        models.ProjectTaskStatus.TODO.value: 0,
                        models.ProjectTaskStatus.IN_PROGRESS.value: 1,
                        models.ProjectTaskStatus.DONE.value: 2,
                    }.get(
                        item.status.value
                        if isinstance(item.status, models.ProjectTaskStatus)
                        else str(item.status),
                        0,
                    ),
                    int(item.sort_order or 0),
                    item.id,
                ),
            )
        ],
    }


def _load_latest_project_scores(
    db: Session,
    *,
    project_id: int,
) -> tuple[float | None, float | None, float | None]:
    latest_audit = (
        db.query(
            models.Audit.seo_score,
            models.Audit.geo_score,
            models.Audit.aeo_score,
        )
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    if latest_audit is None:
        return (None, None, None)
    seo_score = float(latest_audit.seo_score) if latest_audit.seo_score is not None else None
    geo_score = float(latest_audit.geo_score) if latest_audit.geo_score is not None else None
    aeo_score = float(latest_audit.aeo_score) if latest_audit.aeo_score is not None else None
    return (seo_score, geo_score, aeo_score)


def _normalize_project_audit_target_type(value: Any) -> str:
    return normalize_audit_target_type(value)


def _resolve_project_audit_target_url(audit: models.Audit) -> str | None:
    return resolve_audit_target_url_contract(audit)


def _resolve_project_audit_target_name(audit: models.Audit) -> str | None:
    return resolve_audit_target_name_contract(audit)


def _resolve_project_audit_target_metadata(audit: models.Audit) -> dict[str, Any]:
    return resolve_audit_target_metadata_contract(audit)


def _normalize_project_audit_report(
    audit: models.Audit,
    db: Session,
    *,
    search_type_measurements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Normalize one project audit for a project-scoped response.

    ``search_type_measurements`` carries the project's own measured per-search-type
    visibility. It is not optional in practice: without it
    ``build_normalized_audit_report`` attaches five unmeasured search types, which
    is why the project overview's "Why AI recommends / ignores your website" cards
    read "No prompt data yet" even for a project whose prompts had been measured
    (SIGV2-1182). The callers compute it once per request, since every audit in a
    project-scoped response shares the one project.
    """
    return build_normalized_audit_report(
        audit,
        current_plan=resolve_audit_normalization_current_plan(audit.user),
        dismissed=dismissed_fingerprints(db, getattr(audit, "project_id", None)),
        search_type_measurements=search_type_measurements,
    )


def _derive_project_audit_status(
    audit: models.Audit,
) -> str:
    # Check archive state first
    if audit.full_report is None and getattr(audit, "report_archive_uri", None):
        return "archived"
    if (
        audit.full_report is None
        and not getattr(audit, "report_archive_uri", None)
        and getattr(audit, "report_archived_at", None)
    ):
        return "purged"

    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}

    outcome = str(metadata.get("audit_outcome") or "").strip().lower()
    if outcome == "succeeded":
        return "completed"
    if outcome in {"completed", "degraded", "failed"}:
        return outcome  # type: ignore[return-value]

    if metadata.get("scores_available") is False:
        return "degraded"
    if metadata.get("service_errors"):
        return "degraded"
    return "completed"


def _resolve_source_audit_metadata(audit: models.Audit) -> dict[str, Any]:
    if not isinstance(audit.full_report, dict):
        return {}
    metadata = audit.full_report.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _resolve_source_audit_refresh_context(audit: models.Audit) -> dict[str, Any]:
    metadata = _resolve_source_audit_metadata(audit)
    provider = str(metadata.get("provider") or "google").strip().lower() or "google"
    category = (
        str(metadata.get("category") or "competitive benchmark").strip() or "competitive benchmark"
    )
    market = metadata.get("market")
    language = metadata.get("language")
    return {
        "provider": provider,
        "category": category,
        "market": str(market).strip() if isinstance(market, str) and market.strip() else None,
        "language": str(language).strip()
        if isinstance(language, str) and language.strip()
        else None,
    }


async def _enqueue_project_competitor_refresh_jobs(
    *,
    db: Session,
    user: models.User,
    project: models.Project,
    source_audit: models.Audit,
) -> CompetitiveRefreshResponse:
    competitors = [
        competitor for competitor in project.competitors if competitor.auto_audit_enabled
    ]
    if not competitors:
        raise HTTPException(
            status_code=400, detail="Add at least one competitor before refreshing benchmarks."
        )

    # SIGV2-1129: a competitor benchmark is not one of the customer's scans, so
    # the refresh is bounded by what the product allows a project to track
    # rather than by the scan allowance. The cap is enforced when a competitor
    # is added; re-checking it here keeps the fan-out finite for rows that
    # arrived another way.
    skipped_competitors: list[str] = [
        competitor.target_url for competitor in competitors[MAX_PROJECT_COMPETITORS:]
    ]
    if skipped_competitors:
        logger.warning(
            "Project %s has %s auto-audit competitors, above the cap of %s; "
            "the benchmark refresh is bounded to the first %s.",
            project.id,
            len(competitors),
            MAX_PROJECT_COMPETITORS,
            MAX_PROJECT_COMPETITORS,
        )
    competitors = competitors[:MAX_PROJECT_COMPETITORS]

    refresh_context = _resolve_source_audit_refresh_context(source_audit)
    estimated_credit_cost = max(
        1,
        int(
            calculate_audit_credit_cost(
                provider=str(refresh_context["provider"]),
                tier="fast",
                entities_count=0,
                category=str(refresh_context["category"]),
                market=refresh_context["market"],
            )
        ),
    )
    payloads: list[dict[str, Any]] = []
    job_ids: list[str] = []

    for competitor in competitors:
        ensure_project_competitor_snapshot_pending(
            db,
            project_id=project.id,
            competitor_id=competitor.id,
            source_audit_id=source_audit.id,
            metadata={"source": "manual_refresh"},
        )
        job_id = secrets.token_hex(16)
        request_id = build_project_competitor_request_id(
            source_audit_id=source_audit.id,
            competitor_id=competitor.id,
            job_id=job_id,
        )
        db.add(
            models.AuditJob(
                id=job_id,
                user_id=user.id,
                status="queued",
                audit_target_type=models.AuditTargetType.WEBSITE,
                target_name=competitor.target_url,
                target_url=competitor.target_url,
                target_metadata={},
                url=competitor.target_url,
                request_id=request_id,
                # SIGV2-1129: a benchmark refresh measures a competitor to
                # populate the comparison the plan already includes, so it is
                # not billed as one of the customer's scans.
                scan_origin=models.SCAN_ORIGIN_COMPETITOR_REFRESH,
            )
        )
        payloads.append(
            {
                "job_id": job_id,
                "request_id": request_id,
                "user_id": user.id,
                "url": competitor.target_url,
                "audit_target_type": "website",
                "target_name": competitor.target_url,
                "target_url": competitor.target_url,
                "target_metadata": {},
                "provider": refresh_context["provider"],
                "tier": "fast",
                "project_id": project.id,
                "charge_credits": True,
                "estimated_credit_cost": estimated_credit_cost,
                "category": refresh_context["category"],
                "market": refresh_context["market"],
                "language": refresh_context["language"],
                "source_audit_id": source_audit.id,
                "project_competitor_id": competitor.id,
                "project_scope": AUDIT_PROJECT_SCOPE_COMPETITOR,
            }
        )
        job_ids.append(job_id)

    db.commit()

    async with get_async_redis() as redis_client:
        try:
            for payload in payloads:
                await redis_client.hset(
                    f"audit:job:{payload['job_id']}",
                    mapping={
                        "status": "queued",
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "url": str(payload["url"]),
                        "project_id": str(project.id),
                        "request_id": str(payload["request_id"]),
                        "source": "competitive_refresh",
                        "audit_target_type": "website",
                        "target_name": str(payload["target_name"]),
                        "target_url": str(payload["target_url"]),
                        "source_audit_id": str(source_audit.id),
                        "project_competitor_id": str(payload["project_competitor_id"]),
                        "estimated_credit_cost": str(estimated_credit_cost),
                    },
                )
                await redis_client.rpush(
                    resolve_queue_for_tier(str(payload.get("tier", "fast"))), json.dumps(payload)
                )
                from services.job_ttl_dlq_service import set_ttl_queued

                await set_ttl_queued(redis_client, payload["job_id"])
        except Exception as exc:
            db.rollback()
            for competitor in competitors:
                mark_project_competitor_snapshot_failed(
                    db,
                    project_id=project.id,
                    competitor_id=competitor.id,
                    source_audit_id=source_audit.id,
                    reason=f"Failed to enqueue benchmark refresh: {exc}",
                )
            (
                db.query(models.AuditJob)
                .filter(models.AuditJob.id.in_(job_ids))
                .update(
                    {
                        models.AuditJob.status: "failed",
                        models.AuditJob.error: "Failed to enqueue competitive benchmark job.",
                        models.AuditJob.completed_at: datetime.now(timezone.utc),
                    },
                    synchronize_session=False,
                )
            )
            db.commit()
            raise HTTPException(
                status_code=502, detail="Unable to enqueue competitor benchmark refresh."
            ) from exc

    return CompetitiveRefreshResponse(
        project_id=project.id,
        source_audit_id=source_audit.id,
        queued_jobs=len(payloads),
        skipped_competitors=skipped_competitors,
        message=f"Queued {len(payloads)} competitor benchmark job(s).",
    )


def _missing_smart_profile_required_fields(project: models.Project) -> list[str]:
    missing: list[str] = []
    for attribute, label in SMART_PROFILE_REQUIRED_FIELDS:
        value = getattr(project, attribute, None)
        if value is None:
            missing.append(label)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(label)
    return missing


def _extract_compact_text_from_html(html: str, *, max_chars: int = 1500) -> str:
    without_scripts = re.sub(
        r"<script\b[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL
    )
    without_styles = re.sub(
        r"<style\b[^>]*>.*?</style>", " ", without_scripts, flags=re.IGNORECASE | re.DOTALL
    )
    without_tags = re.sub(r"<[^>]+>", " ", without_styles)
    compact = re.sub(r"\s+", " ", without_tags).strip()
    return compact[:max_chars]


def _extract_first_regex_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip()
    return value or None


def _fetch_smart_profile_domain_snapshot(domain_url: str) -> dict[str, Any]:
    normalized = _normalize_domain_url(domain_url)
    if not normalized:
        return {}

    try:
        with httpx.Client(timeout=8.0, follow_redirects=False) as client:
            response, _ = sync_request_with_validation(
                client,
                method="GET",
                url=normalized,
                headers={
                    "User-Agent": "qiko-signal-profile-bot/1.0",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
    except ValueError:
        return {}
    except Exception:
        return {}

    if response.status_code >= 400:
        return {}

    content_type = str(response.headers.get("content-type") or "").lower()
    if "html" not in content_type and "text" not in content_type:
        return {}

    html = response.text[:300_000]
    title = _extract_first_regex_group(r"<title[^>]*>(.*?)</title>", html)
    meta_description = _extract_first_regex_group(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']',
        html,
    )
    if not meta_description:
        meta_description = _extract_first_regex_group(
            r'<meta[^>]+content=["\'](.*?)["\'][^>]+name=["\']description["\']',
            html,
        )

    heading_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, flags=re.IGNORECASE | re.DOTALL)
    headings = [
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", heading)).strip() for heading in heading_matches
    ]
    headings = [heading for heading in headings if heading][:3]
    body_excerpt = _extract_compact_text_from_html(html)

    snapshot = {
        "url": normalized,
        "title": title,
        "meta_description": meta_description,
        "headings": headings,
        "body_excerpt": body_excerpt,
    }
    if not any(
        snapshot.get(key) for key in ("title", "meta_description", "headings", "body_excerpt")
    ):
        return {}
    return snapshot


def _extract_latest_audit_evidence(db: Session, project_id: int) -> dict[str, Any]:
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    if latest_audit is None:
        return {}

    report = _normalize_project_audit_report(latest_audit, db)
    effective_scores = resolve_audit_effective_scores(latest_audit, canonical_report=report)

    # BUG-025b (extended): build_normalized_audit_report / to_canonical_audit_result
    # can relocate or drop summary, recommendations, and prioritized actions. Read
    # from the RAW full_report as well as the normalized report and merge, so evidence
    # extraction does not silently lose recommendations/prioritized actions.
    raw_report = latest_audit.full_report if isinstance(latest_audit.full_report, dict) else {}
    normalized_recommendations = extract_normalized_recommendation_texts(report, limit=8)
    raw_recommendations = extract_normalized_recommendation_texts(raw_report, limit=8)

    prioritized_actions: list[str] = []
    for source in (raw_report, report):
        prioritized_actions_raw = (
            source.get("prioritized_actions") if isinstance(source, dict) else None
        )
        if not isinstance(prioritized_actions_raw, list):
            continue
        for item in prioritized_actions_raw[:6]:
            if not isinstance(item, dict):
                continue
            candidate = item.get("title") or item.get("action") or item.get("name")
            if isinstance(candidate, str) and candidate.strip():
                normalized = re.sub(r"\s+", " ", candidate).strip()
                if normalized and normalized not in prioritized_actions:
                    prioritized_actions.append(normalized)
        if prioritized_actions:
            break

    raw_analysis = (
        raw_report.get("analysis") if isinstance(raw_report.get("analysis"), dict) else {}
    )
    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}

    summary = ""
    summary_candidates = [
        raw_analysis.get("summary"),
        analysis.get("summary") if isinstance(analysis, dict) else None,
        report.get("summary") if isinstance(report, dict) else None,
        report.get("executive_summary") if isinstance(report, dict) else None,
    ]
    for candidate in summary_candidates:
        if isinstance(candidate, str) and candidate.strip():
            summary = re.sub(r"\s+", " ", candidate).strip()[:600]
            break

    recommendations: list[str] = []
    for item in [*normalized_recommendations, *raw_recommendations, *prioritized_actions]:
        if not item:
            continue
        if item in recommendations:
            continue
        recommendations.append(item)
        if len(recommendations) >= 8:
            break

    # Same BUG-025b relocation issue as summary/recommendations above: entities
    # can live in the raw full_report (top-level "entities" or
    # analysis.entities_detected) and not survive normalization into `report`.
    entities = extract_canonical_entities(report, limit=10) or extract_canonical_entities(
        raw_report, limit=10
    )

    return {
        "audit_id": int(latest_audit.id),
        "audit_created_at": _isoformat(latest_audit.created_at),
        "scores": {
            "seo": effective_scores["seo"],
            "geo": effective_scores["geo"],
            "aeo": effective_scores["aeo"],
        },
        "summary": summary,
        "prioritized_actions": prioritized_actions,
        "recommendations": recommendations,
        "entities_detected": entities,
    }


def _build_grounded_smart_profile_sources(
    project: models.Project,
    db: Session,
) -> tuple[dict[str, Any], list[str]]:
    source_labels: list[str] = [
        "project_profile_fields",
    ]

    domain_snapshot = _fetch_smart_profile_domain_snapshot(project.domain_url or "")
    if domain_snapshot:
        source_labels.append("project_domain_snapshot")

    latest_audit = _extract_latest_audit_evidence(db, project.id)
    if latest_audit:
        source_labels.append("latest_project_audit")

    evidence = {
        "project": {
            "name": project.name,
            "domain_url": project.domain_url,
            "target_country": project.target_country,
            "language": project.language,
            "competitors": [
                str(item).strip() for item in (project.competitors_json or []) if str(item).strip()
            ],
        },
        "domain_snapshot": domain_snapshot,
        "latest_audit": latest_audit,
    }
    return evidence, source_labels


def _clean_generated_text_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = re.sub(r"\s+", " ", item).strip()
        if not normalized:
            continue
        cleaned.append(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


def _generate_smart_profile_via_ai_service(evidence: dict[str, Any]) -> dict[str, Any]:
    """Generate a grounded smart profile through the ai-service layer.

    AGENTS.md 4.4: routers never call an LLM API directly. The prompt, the
    model parameters and the Bedrock seam live in
    ``services.smart_profile_service``; this wrapper only maps its failures
    onto the HTTP responses this endpoint has always returned.
    """
    try:
        return smart_profile_service.generate_smart_profile(evidence)
    except smart_profile_service.SmartProfileUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except smart_profile_service.SmartProfileInvalidResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except smart_profile_service.SmartProfileGenerationError as exc:
        raise HTTPException(status_code=502, detail=f"AI generation failed: {exc}") from exc


def _normalize_generated_smart_profile(payload: dict[str, Any]) -> dict[str, Any]:
    pain_points_raw = payload.get("pain_points")
    usp_raw = payload.get("usp")
    pain_points = pain_points_raw.strip() if isinstance(pain_points_raw, str) else ""
    usp = usp_raw.strip() if isinstance(usp_raw, str) else ""

    return {
        "icp_roles": _clean_generated_text_list(payload.get("icp_roles"), limit=6),
        "pain_points": pain_points[:600] if pain_points else None,
        "usp": usp[:220] if usp else None,
        "priority_pulse_tags": _clean_generated_text_list(
            payload.get("priority_pulse_tags"),
            limit=8,
        ),
        "sme_profiles": _clean_generated_text_list(payload.get("sme_profiles"), limit=6),
        "unsupported_fields": _clean_generated_text_list(
            payload.get("unsupported_fields"), limit=10
        ),
    }


def _serialize_project_audit_entry(
    audit: models.Audit,
    *,
    db: Session,
    include_full_report: bool,
    search_type_measurements: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    audit_type_value = (
        audit.audit_type.value
        if isinstance(audit.audit_type, models.AuditType)
        else str(audit.audit_type or models.AuditType.FAST.value)
    )
    normalized_report = (
        _normalize_project_audit_report(
            audit, db, search_type_measurements=search_type_measurements
        )
        if include_full_report
        else None
    )
    effective_scores = resolve_audit_effective_scores(audit, canonical_report=normalized_report)
    return {
        "id": audit.id,
        "project_id": int(audit.project_id or 0),
        "site_id": int(audit.site_id) if audit.site_id is not None else None,
        "audit_type": audit_type_value,
        "url": _resolve_project_audit_target_url(audit) or "",
        "audit_target_type": _normalize_project_audit_target_type(
            getattr(audit, "audit_target_type", None)
        ),
        "target_name": _resolve_project_audit_target_name(audit),
        "target_url": _resolve_project_audit_target_url(audit),
        "target_metadata": _resolve_project_audit_target_metadata(audit),
        "geo_score": effective_scores["geo"],
        "seo_score": effective_scores["seo"],
        "aeo_score": effective_scores["aeo"],
        "status": _derive_project_audit_status(audit),
        "created_at": _isoformat(audit.created_at) or "",
        "full_report": normalized_report,
        "is_archived": bool(getattr(audit, "report_archived_at", None)),
        "is_pinned": bool(getattr(audit, "is_pinned", False)),
    }


def _serialize_project_data_source(
    source_type: models.ProjectDataSourceType,
    *,
    project_id: int,
    workspace_provider_connected: bool,
    row: models.ProjectDataSource | None = None,
) -> ProjectDataSourceResponse:
    provider = _resolve_provider_for_source_type(source_type)
    source_type_value = (
        source_type.value
        if isinstance(source_type, models.ProjectDataSourceType)
        else str(source_type)
    )
    provider_value = provider.value if isinstance(provider, models.OAuthProvider) else str(provider)

    if row is None:
        return ProjectDataSourceResponse(
            id=None,
            project_id=project_id,
            provider=provider_value,  # type: ignore[arg-type]
            source_type=source_type_value,  # type: ignore[arg-type]
            binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE.value,
            source_id=None,
            source_label=None,
            is_active=False,
            oauth_connection_id=None,
            project_oauth_connection_id=None,
            workspace_provider_connected=workspace_provider_connected,
            updated_at=None,
        )

    binding_mode_value = (
        row.binding_mode.value
        if isinstance(row.binding_mode, models.ProjectDataSourceBindingMode)
        else str(row.binding_mode)
    )

    return ProjectDataSourceResponse(
        id=row.id,
        project_id=row.project_id,
        provider=provider_value,  # type: ignore[arg-type]
        source_type=source_type_value,  # type: ignore[arg-type]
        binding_mode=binding_mode_value,  # type: ignore[arg-type]
        source_id=row.source_id,
        source_label=row.source_label,
        is_active=bool(row.is_active),
        oauth_connection_id=row.oauth_connection_id,
        project_oauth_connection_id=row.project_oauth_connection_id,
        workspace_provider_connected=workspace_provider_connected,
        updated_at=_isoformat(row.updated_at),
    )


def _token_preview(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _derive_expires_at(token_payload: dict[str, object]) -> datetime | None:
    """Delegate to the shared implementation in google_oauth_service."""
    from app.services.google_oauth_service import derive_expires_at

    return derive_expires_at(token_payload)


def _resolve_provider_for_source_type(
    source_type: models.ProjectDataSourceType,
) -> models.OAuthProvider:
    provider = PROJECT_SOURCE_TYPE_TO_PROVIDER.get(source_type)
    if provider is None:
        raise HTTPException(status_code=400, detail="Unsupported project data source type.")
    return provider


def _tokenize_scope_string(scope_value: str | None) -> set[str]:
    if not scope_value:
        return set()
    raw_tokens = [token.strip().lower() for token in scope_value.replace(",", " ").split()]
    return {token for token in raw_tokens if token}


def _normalize_granted_scope_aliases(scope_tokens: set[str]) -> set[str]:
    normalized = set(scope_tokens)
    for token in list(scope_tokens):
        if token.startswith("https://www.googleapis.com/auth/"):
            suffix = token.rsplit("/", maxsplit=1)[-1]
            if suffix:
                normalized.add(suffix)
        if token.endswith(".readonly"):
            normalized.add(token.removesuffix(".readonly"))
        if token == "gsc.read":
            normalized.add("webmasters.readonly")
            normalized.add("webmasters")
        if token == "ga4.read":
            normalized.add("analytics.readonly")
            normalized.add("analytics")
    return normalized


def _resolve_scope_requirements(
    source_type: models.ProjectDataSourceType, scope_value: str | None
) -> tuple[list[str], list[str], list[str]]:
    required_groups = REQUIRED_SCOPE_ALIASES_BY_SOURCE_TYPE.get(source_type, tuple())
    required_scopes = [group[0] for group in required_groups if group]
    granted_raw = _tokenize_scope_string(scope_value)
    granted_normalized = _normalize_granted_scope_aliases(granted_raw)

    missing_scopes: list[str] = []
    for group in required_groups:
        if not any(alias.strip().lower() in granted_normalized for alias in group):
            missing_scopes.append(group[0])

    granted_scopes = sorted(granted_raw)
    return required_scopes, granted_scopes, missing_scopes


def _build_scope_error_message(missing_scopes: list[str]) -> str:
    if not missing_scopes:
        return "insufficient_scope"
    return f"insufficient_scope: missing {', '.join(missing_scopes)}"


def _resolve_magic_link_with_project(
    db: Session, token: str
) -> tuple[models.MagicLink | None, models.Project | None, bool]:
    link = db.query(models.MagicLink).filter(models.MagicLink.unique_token == token).first()
    if link is None:
        return None, None, False

    project = db.query(models.Project).filter(models.Project.id == link.project_id).first()
    now = datetime.now(timezone.utc)
    link_expires_at = _as_utc_datetime(link.expires_at)
    is_expired = bool(link_expires_at is not None and link_expires_at <= now)
    return link, project, is_expired


def _coerce_metadata_dict(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _log_project_connection_event(
    db: Session,
    *,
    project_id: int,
    event_type: str,
    provider: models.OAuthProvider | None = None,
    magic_link_id: int | None = None,
    metadata: dict[str, object] | None = None,
) -> None:
    entry = models.ProjectConnectionAuditLog(
        project_id=project_id,
        magic_link_id=magic_link_id,
        provider=provider,
        event_type=event_type,
        metadata_json=metadata or {},
    )
    db.add(entry)


def _extract_id_token_claims(id_token: str | None) -> dict[str, str]:
    if not id_token or "." not in id_token:
        return {}
    parts = id_token.split(".")
    if len(parts) < 2:
        return {}
    payload_part = parts[1]
    padding = "=" * ((4 - len(payload_part) % 4) % 4)
    try:
        decoded_bytes = base64.urlsafe_b64decode(payload_part + padding)
        decoded_payload = decoded_bytes.decode("utf-8")
        parsed = json.loads(decoded_payload)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    claims: dict[str, str] = {}
    for key in ("email", "sub"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            claims[key] = value.strip()
    return claims


def _derive_token_identity(token_payload: dict[str, Any]) -> tuple[str | None, str | None]:
    userinfo_raw = token_payload.get("userinfo")
    if isinstance(userinfo_raw, dict):
        email = userinfo_raw.get("email")
        subject = userinfo_raw.get("sub")
        return (
            str(email).strip() if isinstance(email, str) and email.strip() else None,
            str(subject).strip() if isinstance(subject, str) and subject.strip() else None,
        )

    id_token = token_payload.get("id_token")
    claims = _extract_id_token_claims(str(id_token) if isinstance(id_token, str) else None)
    return claims.get("email"), claims.get("sub")


def _extract_domain_host(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _normalize_domain_url(value)
    if not normalized:
        return None
    parsed = urlparse(normalized)
    host = (parsed.netloc or "").strip().lower()
    if host.startswith("www."):
        return host[4:]
    return host or None


def _select_catalog_item_for_project(
    project: models.Project,
    items: list["ProjectDataSourceCatalogItemResponse"],
) -> "ProjectDataSourceCatalogItemResponse | None":
    if not items:
        return None
    project_host = _extract_domain_host(project.domain_url)
    if project_host:
        for item in items:
            candidate_host = _extract_domain_host(item.id) or _extract_domain_host(item.label)
            if candidate_host and candidate_host == project_host:
                return item
    return items[0]


def _upsert_project_oauth_connection(
    db: Session,
    *,
    project_id: int,
    provider: models.OAuthProvider,
    magic_link_id: int | None,
    access_token: str,
    refresh_token: str | None,
    token_type: str | None,
    scope: str | None,
    expires_at: datetime | None,
    connected_by_email: str | None,
    external_subject: str | None,
) -> models.ProjectOAuthConnection:
    row = (
        db.query(models.ProjectOAuthConnection)
        .filter(
            models.ProjectOAuthConnection.project_id == project_id,
            models.ProjectOAuthConnection.provider == provider,
        )
        .first()
    )
    if row is None:
        row = models.ProjectOAuthConnection(
            project_id=project_id,
            provider=provider,
            magic_link_id=magic_link_id,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            scope=scope,
            expires_at=expires_at,
            connected_by_email=connected_by_email,
            external_subject=external_subject,
        )
        db.add(row)
        db.flush()
        return row

    row.magic_link_id = magic_link_id
    row.access_token = access_token
    row.refresh_token = refresh_token
    row.token_type = token_type
    row.scope = scope
    row.expires_at = expires_at
    row.connected_by_email = connected_by_email
    row.external_subject = external_subject
    db.flush()
    return row


def _apply_magic_link_connection(
    *,
    db: Session,
    link: models.MagicLink,
    project: models.Project,
    provider: models.OAuthProvider,
    token_payload: dict[str, Any],
) -> None:
    now = datetime.now(timezone.utc)
    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise HTTPException(status_code=400, detail="oauth_access_token_missing")

    refresh_token_raw = token_payload.get("refresh_token")
    refresh_token = (
        str(refresh_token_raw).strip()
        if isinstance(refresh_token_raw, str) and refresh_token_raw.strip()
        else None
    )
    token_type_raw = token_payload.get("token_type")
    token_type = (
        str(token_type_raw).strip()
        if isinstance(token_type_raw, str) and token_type_raw.strip()
        else None
    )
    scope_raw = token_payload.get("scope")
    scope = str(scope_raw).strip() if isinstance(scope_raw, str) and scope_raw.strip() else None
    expires_at = _derive_expires_at(token_payload)
    connected_by_email, external_subject = _derive_token_identity(token_payload)

    connection = _upsert_project_oauth_connection(
        db,
        project_id=project.id,
        provider=provider,
        magic_link_id=link.id,
        access_token=access_token,
        refresh_token=refresh_token,
        token_type=token_type,
        scope=scope,
        expires_at=expires_at,
        connected_by_email=connected_by_email,
        external_subject=external_subject,
    )
    _log_project_connection_event(
        db,
        project_id=project.id,
        magic_link_id=link.id,
        provider=provider,
        event_type="magic_link_oauth_connected",
        metadata={
            "token_type": token_type or "",
            "has_refresh_token": bool(refresh_token),
            "scope": scope or "",
            "connected_by_email": connected_by_email or "",
        },
    )

    source_types = MAGIC_LINK_PROVIDER_SOURCE_TYPES.get(provider, tuple())
    for source_type in source_types:
        required_scopes, _granted_scopes, missing_scopes = _resolve_scope_requirements(
            source_type, scope
        )
        discovery_error: str | None = None
        selected_item: ProjectDataSourceCatalogItemResponse | None = None

        if missing_scopes:
            discovery_error = f"insufficient_scope: missing {', '.join(missing_scopes)}"
        else:
            try:
                catalog_items = _fetch_source_catalog_items(
                    source_type=source_type,
                    access_token=access_token,
                )
                selected_item = _select_catalog_item_for_project(project, catalog_items)
            except Exception as exc:
                discovery_error = str(exc)

        row = (
            db.query(models.ProjectDataSource)
            .filter(
                models.ProjectDataSource.project_id == project.id,
                models.ProjectDataSource.source_type == source_type,
            )
            .first()
        )
        metadata = {
            "connected_via_magic_link": True,
            "magic_link_id": link.id,
            "provider": provider.value,
            "project_oauth_connection_id": connection.id,
            "connected_at": now.isoformat(),
            "required_scopes": required_scopes,
            "source_discovery_error": discovery_error,
        }
        if row is None:
            row = models.ProjectDataSource(
                project_id=project.id,
                provider=provider,
                source_type=source_type,
                binding_mode=models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK,
                source_id=selected_item.id if selected_item else None,
                source_label=selected_item.label if selected_item else "Client OAuth connection",
                is_active=not bool(missing_scopes),
                oauth_connection_id=None,
                project_oauth_connection_id=connection.id,
                metadata_json=metadata,
            )
            db.add(row)
        else:
            current_metadata = _coerce_metadata_dict(row.metadata_json)
            current_metadata.update(metadata)
            row.provider = provider
            row.binding_mode = models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK
            row.source_id = selected_item.id if selected_item else row.source_id
            row.source_label = (
                selected_item.label
                if selected_item
                else (row.source_label or "Client OAuth connection")
            )
            row.is_active = not bool(missing_scopes)
            row.oauth_connection_id = None
            row.project_oauth_connection_id = connection.id
            row.metadata_json = current_metadata

    link.is_used = True
    link.used_at = now
    db.commit()


async def _start_magic_link_oauth_flow(
    *,
    request: Request,
    db: Session,
    token: str,
    provider: Literal["google", "bing"],
    callback_route_name: str,
    authorize_kwargs: dict[str, object],
    client_name: str | None = None,
) -> RedirectResponse:
    link, project, is_expired = _resolve_magic_link_with_project(db, token)
    if link is None or project is None:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_not_found"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    if is_expired:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_expired"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    if link.is_used:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_already_used"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    client = oauth.create_client(client_name or provider)
    if client is None:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="oauth_client_unavailable"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    request.session[_magic_link_oauth_session_key(provider)] = {
        "token": token,
        "magic_link_id": link.id,
        "project_id": project.id,
    }
    redirect_uri = _build_oauth_callback_uri(
        request,
        route_name=callback_route_name,
    )
    return await client.authorize_redirect(request, redirect_uri, **authorize_kwargs)


async def _finish_magic_link_oauth_flow(
    *,
    request: Request,
    db: Session,
    provider: Literal["google", "bing"],
    client_name: str | None = None,
) -> RedirectResponse:
    session_payload = request.session.pop(_magic_link_oauth_session_key(provider), None)
    if not isinstance(session_payload, dict):
        return RedirectResponse(
            url=_build_connections_return_url(
                provider=provider, status="error", message="oauth_session_missing"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    token = str(session_payload.get("token") or "").strip()
    if not token:
        return RedirectResponse(
            url=_build_connections_return_url(
                provider=provider, status="error", message="oauth_session_invalid"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    link, project, is_expired = _resolve_magic_link_with_project(db, token)
    if link is None or project is None:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_not_found"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    if is_expired:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_expired"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    if link.is_used:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="magic_link_already_used"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    error_value = request.query_params.get("error")
    if error_value:
        _log_project_connection_event(
            db,
            project_id=project.id,
            magic_link_id=link.id,
            provider=models.OAuthProvider(provider),
            event_type="magic_link_oauth_error",
            metadata={"error": error_value},
        )
        db.commit()
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message=error_value
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    client = oauth.create_client(client_name or provider)
    if client is None:
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="oauth_client_unavailable"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    try:
        token_payload = await client.authorize_access_token(request)
    except Exception:
        _log_project_connection_event(
            db,
            project_id=project.id,
            magic_link_id=link.id,
            provider=models.OAuthProvider(provider),
            event_type="magic_link_oauth_error",
            metadata={"error": "oauth_callback_failed"},
        )
        db.commit()
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message="oauth_callback_failed"
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    try:
        _apply_magic_link_connection(
            db=db,
            link=link,
            project=project,
            provider=models.OAuthProvider(provider),
            token_payload=token_payload,
        )
    except HTTPException as exc:
        _log_project_connection_event(
            db,
            project_id=project.id,
            magic_link_id=link.id,
            provider=models.OAuthProvider(provider),
            event_type="magic_link_oauth_error",
            metadata={"error": str(exc.detail)},
        )
        db.commit()
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token, provider=provider, status="error", message=str(exc.detail)
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    except Exception as exc:
        logger.exception(
            "Magic-link OAuth callback failed (provider=%s): %s",
            provider,
            exc,
        )
        _log_project_connection_event(
            db,
            project_id=project.id,
            magic_link_id=link.id,
            provider=models.OAuthProvider(provider),
            event_type="magic_link_oauth_error",
            metadata={"error": "magic_link_oauth_apply_failed"},
        )
        db.commit()
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token,
                provider=provider,
                status="error",
                message="magic_link_oauth_apply_failed",
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    return RedirectResponse(
        url=_build_magic_link_return_url(token=token, provider=provider, status="connected"),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


def _build_project_provider_statuses(
    db: Session,
    *,
    project_id: int,
    include_private_fields: bool,
) -> list[MagicLinkProviderConnectionResponse]:
    rows = (
        db.query(models.ProjectOAuthConnection)
        .filter(models.ProjectOAuthConnection.project_id == project_id)
        .all()
    )
    by_provider: dict[models.OAuthProvider, models.ProjectOAuthConnection] = {}
    for row in rows:
        provider_enum = (
            row.provider
            if isinstance(row.provider, models.OAuthProvider)
            else models.OAuthProvider(str(row.provider))
        )
        existing = by_provider.get(provider_enum)
        if existing is None:
            by_provider[provider_enum] = row
            continue
        existing_updated_at = _as_utc_datetime(existing.updated_at) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        current_updated_at = _as_utc_datetime(row.updated_at) or datetime.min.replace(
            tzinfo=timezone.utc
        )
        if current_updated_at >= existing_updated_at:
            by_provider[provider_enum] = row

    responses: list[MagicLinkProviderConnectionResponse] = []
    for provider in (models.OAuthProvider.GOOGLE, models.OAuthProvider.BING):
        row = by_provider.get(provider)
        responses.append(
            MagicLinkProviderConnectionResponse(
                provider=provider.value,  # type: ignore[arg-type]
                connected=row is not None,
                connected_at=_isoformat(_as_utc_datetime(row.updated_at)) if row else None,
                connected_by_email=(row.connected_by_email if include_private_fields else None)
                if row
                else None,
                has_refresh_token=bool(row.refresh_token)
                if row and include_private_fields
                else False,
                expires_at=_isoformat(_as_utc_datetime(row.expires_at))
                if row and include_private_fields
                else None,
                scope=(row.scope if include_private_fields else None) if row else None,
            )
        )
    return responses


def _resolve_magic_link_connection_state(
    *,
    link_exists: bool,
    project_exists: bool,
    is_expired: bool,
    is_used: bool,
    has_provider_connections: bool,
) -> str:
    if not link_exists or not project_exists:
        return "invalid"
    if has_provider_connections:
        return "connected"
    if is_used:
        return "used"
    if is_expired:
        return "expired"
    return "pending"


def _workspace_has_oauth_provider_connection(
    db: Session,
    *,
    workspace_id: int,
    provider: models.OAuthProvider,
) -> bool:
    row = (
        db.query(models.OAuthConnection.id)
        .filter(
            models.OAuthConnection.workspace_id == workspace_id,
            models.OAuthConnection.provider == provider,
        )
        .first()
    )
    return row is not None


def _get_latest_workspace_oauth_connection(
    db: Session,
    *,
    workspace_id: int,
    provider: models.OAuthProvider,
) -> models.OAuthConnection | None:
    return (
        db.query(models.OAuthConnection)
        .filter(
            models.OAuthConnection.workspace_id == workspace_id,
            models.OAuthConnection.provider == provider,
        )
        .order_by(models.OAuthConnection.id.desc())
        .first()
    )


def _user_holds_provider_connection_elsewhere(
    db: Session,
    *,
    user: models.User,
    provider: models.OAuthProvider,
    workspace_id: int,
) -> bool:
    """SIGV2-1207: does the user hold this provider's connection on another
    workspace they can access? Only workspaces the user owns or belongs to
    count - a foreign workspace's connection must not leak into the signal."""
    accessible_ids = [
        row.id
        for row in db.query(models.Workspace.id).filter(models.Workspace.owner_id == user.id).all()
    ]
    accessible_ids += [
        row.workspace_id
        for row in db.query(models.WorkspaceUser.workspace_id)
        .filter(models.WorkspaceUser.user_id == user.id)
        .all()
    ]
    other_ids = [wid for wid in set(accessible_ids) if wid != workspace_id]
    if not other_ids:
        return False
    return (
        db.query(models.OAuthConnection.id)
        .filter(
            models.OAuthConnection.provider == provider,
            models.OAuthConnection.workspace_id.in_(other_ids),
        )
        .first()
        is not None
    )


def _is_authentication_credential_error(error: Exception) -> bool:
    message = str(error or "").strip().lower()
    if not message:
        return False
    markers = (
        "invalid authentication credentials",
        "authentication credential",
        "unauthenticated",
        "invalid_grant",
        "token expired",
        "status=401",
        # Bing Webmaster answers expired/revoked tokens with HTTP 400 and a
        # JSON body like {"ErrorCode":18,"Message":"ERROR!!! InvalidToken"};
        # both spellings are matched so the retry path actually fires.
        "invalidtoken",
        "invalid_token",
    )
    return any(marker in message for marker in markers)


def _refresh_workspace_oauth_connection(
    db: Session,
    connection: models.OAuthConnection,
) -> models.OAuthConnection:
    """Refresh ``connection`` through the refresher for its own provider.

    Routing on ``connection.provider`` makes it structurally impossible to
    hand a Bing refresh token to the Google refresher or vice versa; each
    refresher also re-verifies the provider and raises ``provider_not_*`` on a
    mismatch.
    """
    provider = getattr(connection, "provider", None)
    provider_value = provider.value if isinstance(provider, models.OAuthProvider) else str(provider)
    if provider_value == models.OAuthProvider.GOOGLE.value:
        from app.services.google_oauth_service import refresh_google_oauth_connection

        return refresh_google_oauth_connection(db, connection)
    if provider_value == models.OAuthProvider.BING.value:
        from app.services.bing_webmaster_service import refresh_bing_oauth_connection

        return refresh_bing_oauth_connection(db, connection)
    raise RuntimeError(f"oauth_refresh_unsupported_provider:{provider_value}")


def _workspace_connection_access_token_expired(connection: models.OAuthConnection) -> bool:
    """True when the stored ``expires_at`` has passed (60s safety buffer)."""
    expires_at = getattr(connection, "expires_at", None)
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60)


def _extract_upstream_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        direct = payload.get("error_description") or payload.get("error")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        if isinstance(payload.get("error"), dict):
            nested = payload["error"]  # type: ignore[index]
            if isinstance(nested, dict):
                message = nested.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
    text_value = response.text.strip()
    if text_value:
        return text_value[:300]
    return f"status={response.status_code}"


def _list_google_search_console_sites(
    access_token: str,
) -> list[ProjectDataSourceCatalogItemResponse]:
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            "https://www.googleapis.com/webmasters/v3/sites",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        detail = _extract_upstream_error_message(response)
        raise RuntimeError(f"GSC catalog fetch failed: {detail}")

    payload = response.json()
    entries = payload.get("siteEntry", []) if isinstance(payload, dict) else []
    items: list[ProjectDataSourceCatalogItemResponse] = []
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            site_url = str(entry.get("siteUrl") or "").strip()
            if not site_url:
                continue
            permission = str(entry.get("permissionLevel") or "").strip() or None
            items.append(
                ProjectDataSourceCatalogItemResponse(
                    id=site_url,
                    label=site_url,
                    description=permission,
                )
            )
    return items


def _list_google_analytics_properties(
    access_token: str,
) -> list[ProjectDataSourceCatalogItemResponse]:
    def _list_from_account_summaries() -> list[ProjectDataSourceCatalogItemResponse]:
        entries: dict[str, ProjectDataSourceCatalogItemResponse] = {}
        page_token: str | None = None

        with httpx.Client(timeout=20.0) as client:
            for _ in range(10):
                params = {"pageSize": "200"}
                if page_token:
                    params["pageToken"] = page_token

                response = client.get(
                    "https://analyticsadmin.googleapis.com/v1beta/accountSummaries",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code >= 400:
                    detail = _extract_upstream_error_message(response)
                    raise RuntimeError(f"GA4 catalog fetch failed: {detail}")

                payload = response.json()
                account_summaries = (
                    payload.get("accountSummaries", []) if isinstance(payload, dict) else []
                )
                if isinstance(account_summaries, list):
                    for account_summary in account_summaries:
                        if not isinstance(account_summary, dict):
                            continue
                        property_summaries = account_summary.get("propertySummaries", [])
                        if not isinstance(property_summaries, list):
                            continue
                        for property_summary in property_summaries:
                            if not isinstance(property_summary, dict):
                                continue
                            property_name = str(property_summary.get("property") or "").strip()
                            if not property_name:
                                continue
                            property_id = (
                                property_name.split("/")[-1]
                                if "/" in property_name
                                else property_name
                            )
                            display_name = str(property_summary.get("displayName") or "").strip()
                            label = (
                                f"{display_name} ({property_id})"
                                if display_name and display_name != property_id
                                else property_id
                            )
                            entries[property_name] = ProjectDataSourceCatalogItemResponse(
                                id=property_name,
                                label=label,
                                description=None,
                            )

                page_token_value = (
                    payload.get("nextPageToken") if isinstance(payload, dict) else None
                )
                page_token = (
                    str(page_token_value).strip() if isinstance(page_token_value, str) else None
                )
                if not page_token:
                    break

        return list(entries.values())

    def _list_from_properties() -> list[ProjectDataSourceCatalogItemResponse]:
        items: list[ProjectDataSourceCatalogItemResponse] = []
        page_token: str | None = None

        with httpx.Client(timeout=20.0) as client:
            for _ in range(10):
                params = {"pageSize": "200", "showDeleted": "false"}
                if page_token:
                    params["pageToken"] = page_token
                response = client.get(
                    "https://analyticsadmin.googleapis.com/v1beta/properties",
                    params=params,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if response.status_code >= 400:
                    detail = _extract_upstream_error_message(response)
                    raise RuntimeError(f"GA4 catalog fetch failed: {detail}")

                payload = response.json()
                properties = payload.get("properties", []) if isinstance(payload, dict) else []
                if isinstance(properties, list):
                    for property_item in properties:
                        if not isinstance(property_item, dict):
                            continue
                        property_name = str(property_item.get("name") or "").strip()
                        display_name = str(property_item.get("displayName") or "").strip()
                        if not property_name:
                            continue
                        property_id = (
                            property_name.split("/")[-1] if "/" in property_name else property_name
                        )
                        label = (
                            f"{display_name} ({property_id})"
                            if display_name and display_name != property_id
                            else property_id
                        )
                        description_parts = [
                            str(property_item.get("timeZone") or "").strip(),
                            str(property_item.get("currencyCode") or "").strip(),
                        ]
                        description = " · ".join(part for part in description_parts if part) or None
                        items.append(
                            ProjectDataSourceCatalogItemResponse(
                                id=property_name,
                                label=label,
                                description=description,
                            )
                        )

                page_token_value = (
                    payload.get("nextPageToken") if isinstance(payload, dict) else None
                )
                page_token = (
                    str(page_token_value).strip() if isinstance(page_token_value, str) else None
                )
                if not page_token:
                    break

        return items

    try:
        return _list_from_account_summaries()
    except Exception as exc:
        if "filter" not in str(exc).lower():
            raise

    return _list_from_properties()


def _list_bing_webmaster_sites(access_token: str) -> list[ProjectDataSourceCatalogItemResponse]:
    with httpx.Client(timeout=15.0) as client:
        response = client.get(
            "https://ssl.bing.com/webmaster/api.svc/json/GetUserSites",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        detail = _extract_upstream_error_message(response)
        raise RuntimeError(f"Bing catalog fetch failed: {detail}")

    payload = response.json()
    candidates: list[dict] = []
    if isinstance(payload, dict):
        container = payload.get("d")
        if isinstance(container, list):
            candidates = [item for item in container if isinstance(item, dict)]
        if not candidates and isinstance(container, dict):
            for key in ("Results", "results", "Sites", "sites", "GetUserSites"):
                value = container.get(key)
                if isinstance(value, list):
                    candidates = [item for item in value if isinstance(item, dict)]
                    break
        if not candidates:
            for key in ("Results", "results", "Sites", "sites"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates = [item for item in value if isinstance(item, dict)]
                    break

    items: list[ProjectDataSourceCatalogItemResponse] = []
    for item in candidates:
        site_url = str(
            item.get("Url") or item.get("url") or item.get("SiteUrl") or item.get("siteUrl") or ""
        ).strip()
        if not site_url:
            continue
        permission = (
            str(
                item.get("PermissionLevel") or item.get("permissionLevel") or item.get("Role") or ""
            ).strip()
            or None
        )
        items.append(
            ProjectDataSourceCatalogItemResponse(
                id=site_url,
                label=site_url,
                description=permission,
            )
        )

    return items


def _fetch_source_catalog_items(
    *,
    source_type: models.ProjectDataSourceType,
    access_token: str,
) -> list[ProjectDataSourceCatalogItemResponse]:
    if source_type == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE:
        return _list_google_search_console_sites(access_token)
    if source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4:
        return _list_google_analytics_properties(access_token)
    if source_type == models.ProjectDataSourceType.BING_WEBMASTER:
        return _list_bing_webmaster_sites(access_token)
    raise HTTPException(status_code=400, detail="Unsupported project data source type.")


# SIGV2-1202: binding facts that are only true for the grant that produced
# them. They are cleared whenever the binding loses or changes its grant.
# Keys recording customer intent or history are deliberately not listed.
_LIVE_BINDING_METADATA_KEYS = ("ga4_time_zone",)

# Verdicts from validating one saved binding against a token. Only DENIED is a
# confirmed refusal; everything else that is not a clean success is UNKNOWN,
# and UNKNOWN never destroys a binding.
BINDING_ACCESS_OK = "accessible"
BINDING_ACCESS_DENIED = "denied"
BINDING_ACCESS_UNKNOWN = "unknown"


def _clear_live_binding_metadata(source: models.ProjectDataSource) -> None:
    metadata = source.metadata_json if isinstance(source.metadata_json, dict) else {}
    cleaned = {
        key: value for key, value in metadata.items() if key not in _LIVE_BINDING_METADATA_KEYS
    }
    if cleaned != metadata:
        source.metadata_json = cleaned


def _dependent_workspace_bindings(
    db: Session,
    *,
    workspace_id: int,
    provider: models.OAuthProvider,
) -> list[models.ProjectDataSource]:
    """Workspace-bound data sources that resolve through the workspace grant.

    Restricted to one workspace and one provider. Client-magic-link bindings
    and project-level grants are excluded: they resolve through
    ``project_oauth_connection_id`` and never used the workspace grant, so a
    workspace disconnect or reconnect must not touch them.
    """
    return (
        db.query(models.ProjectDataSource)
        .join(models.Project, models.Project.id == models.ProjectDataSource.project_id)
        .filter(
            models.Project.workspace_id == workspace_id,
            models.ProjectDataSource.provider == provider,
            models.ProjectDataSource.binding_mode == models.ProjectDataSourceBindingMode.WORKSPACE,
            models.ProjectDataSource.project_oauth_connection_id.is_(None),
        )
        .all()
    )


def _invalidate_workspace_provider_bindings(
    db: Session,
    *,
    workspace_id: int,
    provider: models.OAuthProvider,
) -> int:
    """Disconnect the data sources that depended on a grant being deleted.

    SIGV2-1202. Deleting the ``OAuthConnection`` row only nulls
    ``oauth_connection_id`` (the FK is ON DELETE SET NULL). The property id,
    the label and ``is_active`` survive, so the binding keeps claiming a live
    property and every read answers "revoked" - the customer is told their
    access was revoked right after they disconnected it themselves, and
    reconnecting cannot clear it.

    Only the binding is cleared. Historical traffic rows, audits, reports and
    audit logs are untouched, as are other workspaces, other providers and
    client-supplied grants. Flushed, not committed: the caller deletes the
    connection and commits both in one transaction.
    """
    rows = _dependent_workspace_bindings(db, workspace_id=workspace_id, provider=provider)
    for source in rows:
        source.source_id = None
        source.source_label = None
        source.oauth_connection_id = None
        source.is_active = False
        source.last_status = "disconnected"
        source.last_error = None
        _clear_live_binding_metadata(source)
    if rows:
        db.flush()
    return len(rows)


def _probe_google_binding_access(
    *,
    access_token: str,
    source_type: models.ProjectDataSourceType,
    source_id: str,
) -> str:
    """Can this token read this saved GA4 property / Search Console site?

    SIGV2-1202. Returns ``BINDING_ACCESS_DENIED`` only for an unambiguous
    refusal of the object itself (403 or 404). A 401, a 429, a 5xx, a network
    failure or an id that cannot be turned into a request proves nothing about
    access and returns ``BINDING_ACCESS_UNKNOWN``, because the caller treats
    DENIED as permission to clear a binding and an ambiguous signal must never
    destroy a working one.
    """
    value = (source_id or "").strip()
    if not value:
        return BINDING_ACCESS_UNKNOWN

    if source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4:
        from app.services.geo.ga4_reporting_service import normalize_ga4_property_id

        property_id = normalize_ga4_property_id(value)
        if property_id is None:
            return BINDING_ACCESS_UNKNOWN
        url = f"https://analyticsadmin.googleapis.com/v1beta/{property_id}"
    elif source_type == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE:
        # Search Console is validated separately and against its own object:
        # GA4 access says nothing about site ownership and vice versa.
        url = f"https://www.googleapis.com/webmasters/v3/sites/{quote(value, safe='')}"
    else:
        return BINDING_ACCESS_UNKNOWN

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, headers={"Authorization": f"Bearer {access_token}"})
    except Exception:
        return BINDING_ACCESS_UNKNOWN

    status_code = getattr(response, "status_code", 0)
    if status_code == 200:
        return BINDING_ACCESS_OK
    if status_code in (403, 404):
        return BINDING_ACCESS_DENIED
    return BINDING_ACCESS_UNKNOWN


def _upsert_workspace_oauth_connection(
    db: Session,
    *,
    workspace_id: int,
    provider: models.OAuthProvider,
    access_token: str,
    refresh_token: str | None,
    token_type: str | None,
    scope: str | None,
    expires_at: datetime | None,
    access_probe: Callable[..., str] | None = None,
) -> models.OAuthConnection:
    row = (
        db.query(models.OAuthConnection)
        .filter(
            models.OAuthConnection.workspace_id == workspace_id,
            models.OAuthConnection.provider == provider,
        )
        .first()
    )
    if row is None:
        row = models.OAuthConnection(
            workspace_id=workspace_id,
            provider=provider,
            access_token=access_token,
            refresh_token=refresh_token,
            token_type=token_type,
            scope=scope,
            expires_at=expires_at,
        )
        db.add(row)
    else:
        row.access_token = access_token
        row.refresh_token = refresh_token
        row.token_type = token_type
        row.scope = scope
        row.expires_at = expires_at

    db.flush()

    # A replaced connection leaves workspace-bound data sources orphaned: the
    # FK's SET NULL wipes oauth_connection_id (or leaves a dangling id), so
    # ga4_connection_for_source returns None and token resolution raises
    # no_oauth_connection. Repoint those rows to this connection in the same
    # transaction. Magic-link bindings are excluded: they resolve through
    # project_oauth_connection_id and never touch the workspace connection.
    #
    # SIGV2-1202: repointing alone was not enough. The new grant can belong to
    # a different Google account, and the saved property was only ever valid
    # for the old one, so a blind repoint restored an inaccessible property and
    # the customer was told again to reconnect. Each saved binding is therefore
    # validated against the new token first, when the caller supplies a probe.
    #
    # The probe is injected, not defaulted: a caller that cannot verify
    # anything (the manual token-paste endpoint) must not be able to clear a
    # binding, and no path may make a network call the caller did not ask for.
    probe_cache: dict[tuple[Any, str], str] = {}
    for source in _dependent_workspace_bindings(db, workspace_id=workspace_id, provider=provider):
        saved_id = str(source.source_id or "").strip()
        verdict = BINDING_ACCESS_UNKNOWN
        if saved_id and access_probe is not None:
            cache_key = (source.source_type, saved_id)
            if cache_key not in probe_cache:
                try:
                    probe_cache[cache_key] = access_probe(
                        access_token=access_token,
                        source_type=source.source_type,
                        source_id=saved_id,
                    )
                except Exception:
                    # A probe that fails tells us nothing. Keep the binding.
                    logger.warning(
                        "binding access probe failed for source_type=%s",
                        getattr(source.source_type, "value", source.source_type),
                    )
                    probe_cache[cache_key] = BINDING_ACCESS_UNKNOWN
            verdict = probe_cache[cache_key]

        if verdict == BINDING_ACCESS_DENIED:
            # Confirmed: the new grant cannot read this object. The binding is
            # cleared so the customer makes a fresh selection, rather than the
            # product quietly re-asserting a property it cannot read.
            source.source_id = None
            source.source_label = None
            source.is_active = False
            source.last_status = "needs_property_selection"
            source.last_error = "binding_not_accessible_for_new_grant"
            _clear_live_binding_metadata(source)
        elif verdict == BINDING_ACCESS_OK and source.last_status in (
            "auth_error",
            "permission_denied",
            "disconnected",
            "needs_property_selection",
        ):
            # Proven good: drop the stale failure so the UI stops reporting a
            # problem that no longer exists.
            source.last_status = None
            source.last_error = None

        # Unbound rows stay unbound: a property the customer cleared is never
        # re-invented for the new account. Only the FK is repaired.
        source.oauth_connection_id = row.id

    db.commit()
    db.refresh(row)
    return row


async def _start_workspace_oauth_flow(
    *,
    request: Request,
    db: Session,
    user: models.User,
    provider: Literal["google", "bing"],
    callback_route_name: str,
    authorize_kwargs: dict[str, object],
    client_name: str | None = None,
    workspace_id: int | None = None,
    return_to: str | None = None,
) -> RedirectResponse:
    # SIGV2-1220: the caller may name where the return should land, but only by
    # key, and an unrecognised key is refused here rather than quietly replaced
    # with the default. Same rule as the workspace id below: a request the
    # product cannot honour is an error, not something to substitute for.
    if return_to is not None and return_to not in _OAUTH_RETURN_DESTINATIONS:
        raise HTTPException(status_code=400, detail="Unsupported OAuth return destination.")

    # SIGV2-1207: the connect action is a full browser navigation, so no
    # X-Workspace-Id header can ride along and _get_or_create_current_workspace
    # falls back to the user's OLDEST owned workspace. A customer with two
    # workspaces could only ever connect the first one. The start request
    # therefore accepts an explicit workspace_id carrying the customer's active
    # workspace through the redirect. An id the user cannot access is refused
    # by _resolve_workspace_access rather than silently swapped for another
    # workspace - that silent substitution is the bug being fixed.
    if workspace_id is not None:
        workspace, role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
    else:
        workspace = _get_or_create_current_workspace(db, user)
        _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    client = oauth.create_client(client_name or provider)
    # create_client() never returns None here: oauth_service registers every
    # provider even with empty credentials. The real check is whether the
    # deployment holds the provider's id/secret at all; without it the redirect
    # would drop the user on the provider's own error page.
    if client is None or not _oauth_provider_configured(provider):
        raise HTTPException(
            status_code=503,
            detail=f"{provider.capitalize()} OAuth client is not configured.",
        )

    # SIGV2-1220: the destination travels inside the OAuth session entry the
    # callback already validates, not through the callback's query string, so
    # it cannot be rewritten between the two legs of the flow.
    request.session[_workspace_oauth_session_key(provider)] = {
        "workspace_id": workspace.id,
        "user_id": user.id,
        "return_to": return_to or _DEFAULT_OAUTH_RETURN,
    }
    redirect_uri = _build_oauth_callback_uri(request, route_name=callback_route_name)
    return await client.authorize_redirect(request, redirect_uri, **authorize_kwargs)


async def _finish_workspace_oauth_flow(
    *,
    request: Request,
    db: Session,
    provider: Literal["google", "bing"],
    client_name: str | None = None,
) -> RedirectResponse:
    session_payload = request.session.pop(_workspace_oauth_session_key(provider), None)
    if not isinstance(session_payload, dict):
        return RedirectResponse(
            url=_build_connections_return_url(
                provider=provider,
                status="error",
                message="oauth_session_missing",
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    # SIGV2-1220: resolved from the closed map, never used as a path. A stored
    # value that is not a known key lands on the Connections Hub.
    return_to = session_payload.get("return_to")

    workspace_id = int(session_payload.get("workspace_id") or 0)
    user_id = int(session_payload.get("user_id") or 0)
    if workspace_id <= 0 or user_id <= 0:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message="oauth_session_invalid",
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message="oauth_user_not_found",
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    workspace, role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
    _require_workspace_admin_access(role)

    error_value = request.query_params.get("error")
    if error_value:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message=error_value,
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    client = oauth.create_client(client_name or provider)
    if client is None:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message="oauth_client_unavailable",
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    try:
        token_payload = await client.authorize_access_token(request)
    except Exception:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message="oauth_callback_failed",
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        return RedirectResponse(
            url=_build_oauth_return_url(
                provider=provider,
                status="error",
                message="oauth_access_token_missing",
                return_to=return_to,
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )

    refresh_token_raw = token_payload.get("refresh_token")
    refresh_token = (
        str(refresh_token_raw).strip()
        if isinstance(refresh_token_raw, str) and refresh_token_raw
        else None
    )
    token_type_raw = token_payload.get("token_type")
    token_type = (
        str(token_type_raw).strip() if isinstance(token_type_raw, str) and token_type_raw else None
    )
    scope_raw = token_payload.get("scope")
    scope = str(scope_raw).strip() if isinstance(scope_raw, str) and scope_raw else None
    expires_at = _derive_expires_at(token_payload)

    # SIGV2-1202: the new token decides which saved bindings may be reused.
    # Only the Google flow carries a probe - GA4 properties and Search Console
    # sites are the objects that can be refused by a different account - and a
    # confirmed refusal is the only thing that clears a binding.
    access_probe = (
        _probe_google_binding_access if provider == models.OAuthProvider.GOOGLE.value else None
    )
    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider(provider),
        access_token=access_token,
        refresh_token=refresh_token,
        token_type=token_type,
        scope=scope,
        expires_at=expires_at,
        access_probe=access_probe,
    )

    return RedirectResponse(
        url=_build_oauth_return_url(
            provider=provider,
            status="connected",
            return_to=return_to,
        ),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )


def _serialize_workspace_member(
    membership: models.WorkspaceUser,
    *,
    workspace_owner_id: int,
) -> WorkspaceMemberResponse:
    user = membership.user
    if user is None:
        raise HTTPException(
            status_code=500, detail="Workspace member relationship is inconsistent."
        )

    role_value = _role_value(membership.role)
    if membership.user_id == workspace_owner_id:
        role_value = models.WorkspaceRole.ADMIN.value

    return WorkspaceMemberResponse(
        user_id=membership.user_id,
        email=user.email,
        role=role_value,  # type: ignore[arg-type]
        is_owner=membership.user_id == workspace_owner_id,
        created_at=_isoformat(membership.created_at),
    )


class RoleMode(str, Enum):
    marketer = "marketer"
    specialist = "specialist"
    agency = "agency"
    enterprise = "enterprise"
    explorer = "explorer"


class WorkspaceSummaryResponse(BaseModel):
    id: int
    name: str
    owner_id: int
    created_at: str | None
    role: str
    is_owner: bool
    project_count: int
    member_count: int
    oauth_connection_count: int
    role_mode: str | None = None


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    role_mode: RoleMode | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Workspace name is required.")
        return normalized


class WorkspaceWhiteLabelBrandingRequest(BaseModel):
    custom_logo_url: str | None = Field(default=None, max_length=2000)
    company_name: str | None = Field(default=None, max_length=255)
    primary_color: str | None = None
    secondary_color: str | None = None
    custom_favicon_url: str | None = Field(default=None, max_length=2000)
    custom_page_title: str | None = Field(default=None, max_length=255)
    custom_meta_description: str | None = Field(default=None, max_length=300)
    hide_powered_by: bool | None = None
    email_sender_name: str | None = Field(default=None, max_length=255)
    email_reply_to: str | None = Field(default=None, max_length=255)
    social_facebook_url: str | None = Field(default=None, max_length=512)
    social_x_url: str | None = Field(default=None, max_length=512)
    social_instagram_url: str | None = Field(default=None, max_length=512)
    social_linkedin_url: str | None = Field(default=None, max_length=512)
    social_youtube_url: str | None = Field(default=None, max_length=512)
    social_tiktok_url: str | None = Field(default=None, max_length=512)
    company_address: str | None = Field(default=None, max_length=1000)
    company_legal_name: str | None = Field(default=None, max_length=255)
    company_trademark_text: str | None = Field(default=None, max_length=512)
    footer_about_url: str | None = Field(default=None, max_length=512)
    footer_blog_url: str | None = Field(default=None, max_length=512)
    footer_support_url: str | None = Field(default=None, max_length=512)
    footer_legal_url: str | None = Field(default=None, max_length=512)
    footer_preferences_url: str | None = Field(default=None, max_length=512)
    footer_privacy_url: str | None = Field(default=None, max_length=512)

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_optional_colors(cls, value: str | None, info):
        return normalize_hex_color(value, field_name=info.field_name)

    @field_validator(
        "custom_logo_url",
        "company_name",
        "custom_favicon_url",
        "custom_page_title",
        "custom_meta_description",
        "email_sender_name",
        "email_reply_to",
        "social_facebook_url",
        "social_x_url",
        "social_instagram_url",
        "social_linkedin_url",
        "social_youtube_url",
        "social_tiktok_url",
        "company_address",
        "company_legal_name",
        "company_trademark_text",
        "footer_about_url",
        "footer_blog_url",
        "footer_support_url",
        "footer_legal_url",
        "footer_preferences_url",
        "footer_privacy_url",
    )
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator(
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
    @classmethod
    def validate_footer_urls(cls, value: str | None, info) -> str | None:
        return normalize_optional_url(value, max_length=512) if value is not None else None

    @field_validator("email_reply_to")
    @classmethod
    def validate_reply_to(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Valid reply-to email is required.")
        return value.lower()


class WorkspaceCustomDomainCreateRequest(BaseModel):
    domain: str = Field(min_length=4, max_length=253)

    @field_validator("domain")
    @classmethod
    def normalize_domain_value(cls, value: str) -> str:
        return normalize_custom_domain(value)


class WorkspaceCustomDomainResponse(BaseModel):
    id: int
    domain: str
    dns_target: str
    verified: bool
    ssl_status: Literal["pending_verification", "pending_ssl", "active", "error"]
    verification_error: str | None = None
    verification_checked_at: str | None = None
    activated_at: str | None = None
    created_at: str | None = None
    preview_url: str


class WorkspaceWhiteLabelSettingsResponse(BaseModel):
    workspace_id: int
    workspace_name: str
    company_name: str
    custom_logo_url: str | None = None
    primary_color: str
    secondary_color: str
    custom_favicon_url: str | None = None
    custom_page_title: str
    custom_meta_description: str | None = None
    hide_powered_by: bool = False
    email_sender_name: str | None = None
    email_reply_to: str | None = None
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
    dns_target: str | None = None
    domains: list[WorkspaceCustomDomainResponse] = Field(default_factory=list)


class WorkspaceEmailFooterUpdateRequest(BaseModel):
    social_facebook_url: str | None = Field(default=None, max_length=512)
    social_x_url: str | None = Field(default=None, max_length=512)
    social_instagram_url: str | None = Field(default=None, max_length=512)
    social_linkedin_url: str | None = Field(default=None, max_length=512)
    social_youtube_url: str | None = Field(default=None, max_length=512)
    social_tiktok_url: str | None = Field(default=None, max_length=512)
    company_address: str | None = Field(default=None, max_length=1000)
    company_legal_name: str | None = Field(default=None, max_length=255)
    company_trademark_text: str | None = Field(default=None, max_length=512)
    footer_about_url: str | None = Field(default=None, max_length=512)
    footer_blog_url: str | None = Field(default=None, max_length=512)
    footer_support_url: str | None = Field(default=None, max_length=512)
    footer_legal_url: str | None = Field(default=None, max_length=512)
    footer_preferences_url: str | None = Field(default=None, max_length=512)
    footer_privacy_url: str | None = Field(default=None, max_length=512)

    @field_validator(
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
    @classmethod
    def validate_footer_urls(cls, value: str | None) -> str | None:
        return normalize_optional_url(value, max_length=512) if value is not None else None

    @field_validator("company_address", "company_legal_name", "company_trademark_text")
    @classmethod
    def normalize_optional_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class WorkspaceEmailFooterSettingsResponse(BaseModel):
    workspace_id: int
    workspace_name: str
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


class TenantBrandingResponse(BaseModel):
    workspace_id: int
    workspace_name: str
    company_name: str
    custom_logo_url: str | None = None
    primary_color: str
    secondary_color: str
    custom_favicon_url: str | None = None
    custom_page_title: str
    custom_meta_description: str | None = None
    hide_powered_by: bool = False
    active_domain: str | None = None


class WorkspaceMemberResponse(BaseModel):
    user_id: int
    email: str
    role: Literal["ADMIN", "EDITOR", "VIEWER", "CLIENT_READONLY"]
    is_owner: bool
    created_at: str | None


class WorkspaceMemberUpsertRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    role: Literal["ADMIN", "EDITOR", "VIEWER", "CLIENT_READONLY"] = "EDITOR"

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Valid email is required.")
        return normalized


class WorkspaceMemberRoleUpdateRequest(BaseModel):
    role: Literal["ADMIN", "EDITOR", "VIEWER", "CLIENT_READONLY"]


class ClientInvitationRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    # name persists into User.company_name; the shared rule caps it at 120.
    name: str | None = Field(default=None, min_length=1)
    project_ids: list[int] = Field(default_factory=list, min_length=1, max_length=100)

    @field_validator("email")
    @classmethod
    def normalize_invitation_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
            raise ValueError("Valid email is required.")
        return normalized

    @field_validator("name", mode="before")
    @classmethod
    def normalize_invited_name(cls, value: str | None) -> str | None:
        return normalize_company_name(value)

    @field_validator("name")
    @classmethod
    def normalize_optional_invitee_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("project_ids")
    @classmethod
    def normalize_project_ids(cls, value: list[int]) -> list[int]:
        normalized = sorted({int(project_id) for project_id in value})
        if not normalized:
            raise ValueError("At least one project is required.")
        return normalized


class ClientInvitationResponse(BaseModel):
    user_id: int
    email: str
    role: Literal["CLIENT_READONLY"]
    project_ids: list[int] = Field(default_factory=list)
    invited: bool
    created_at: str | None = None
    email_queued: bool = False
    invitation_url: str | None = None


class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    domain_url: str | None = Field(default=None, max_length=500)
    target_country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default="en", min_length=2, max_length=10)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name is required.")
        return normalized

    @field_validator("domain_url")
    @classmethod
    def normalize_domain_url(cls, value: str | None) -> str | None:
        return _normalize_domain_url(value)

    @field_validator("target_country")
    @classmethod
    def normalize_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            return None
        if not is_valid_iso_country_code(normalized):
            raise ValueError(
                f"target_country must be a real ISO 3166-1 alpha-2 country code, got '{normalized}'. "
                "Leave it unset if there is no single target market."
            )
        return normalized

    @field_validator("language")
    @classmethod
    def normalize_language(cls, value: str | None) -> str:
        normalized = (value or "en").strip().lower()
        return normalized or "en"


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    domain_url: str | None = Field(default=None, max_length=500)
    target_country: str | None = Field(default=None, min_length=2, max_length=2)
    language: str | None = Field(default=None, min_length=2, max_length=10)
    icp_roles: list[str] | None = None
    pain_points: str | None = Field(default=None, max_length=5000)
    usp: str | None = Field(default=None, max_length=1000)
    competitors: list[str] | None = None
    auto_competitor_audits_enabled: bool | None = None
    competitive_digest_frequency: Literal["off", "weekly", "monthly"] | None = None
    priority_pulse_tags: list[str] | None = None
    sme_profiles: list[str] | None = None
    aio_score_target: StrictInt | None = Field(default=None, ge=0, le=100)
    seo_score_target: StrictInt | None = Field(default=None, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("domain_url")
    @classmethod
    def normalize_optional_domain(cls, value: str | None) -> str | None:
        return _normalize_domain_url(value)

    @field_validator("target_country")
    @classmethod
    def normalize_optional_country(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not normalized:
            return None
        if not is_valid_iso_country_code(normalized):
            raise ValueError(
                f"target_country must be a real ISO 3166-1 alpha-2 country code, got '{normalized}'. "
                "Leave it unset if there is no single target market."
            )
        return normalized

    @field_validator("language")
    @classmethod
    def normalize_optional_language(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None


class ProjectScoreTargetResponse(BaseModel):
    current: float | None = None
    target: int
    gap: float | None = None
    measured_at: str | None = None


class ProjectScoreTargetsResponse(BaseModel):
    aio: ProjectScoreTargetResponse
    seo: ProjectScoreTargetResponse


class ProjectFeatureAccessStateResponse(BaseModel):
    allowed: bool
    detail: str | None = None
    status_code: Literal[402, 403] | None = None
    required_plan: str | None = None


class ProjectFeatureAccessResponse(BaseModel):
    monitoring: ProjectFeatureAccessStateResponse
    automations: ProjectFeatureAccessStateResponse
    advisor_recommendations: ProjectFeatureAccessStateResponse
    entity_authority: ProjectFeatureAccessStateResponse
    benchmark_intelligence: ProjectFeatureAccessStateResponse
    scheduled_audits: ProjectFeatureAccessStateResponse
    jira_export: ProjectFeatureAccessStateResponse


class ProjectResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    domain_url: str | None
    target_country: str | None
    language: str
    icp_roles: list[str]
    pain_points: str | None
    usp: str | None
    competitors: list[str]
    auto_competitor_audits_enabled: bool
    competitive_digest_frequency: Literal["off", "weekly", "monthly"]
    priority_pulse_tags: list[str]
    sme_profiles: list[str]
    tags: list[str] = []
    status: str = "active"
    cloned_from_id: int | None = None
    archived_at: str | None = None
    created_at: str | None
    audit_count: int
    last_audit_at: str | None
    latest_seo_score: float | None = None
    latest_geo_score: float | None = None
    latest_aeo_score: float | None = None
    score_targets: ProjectScoreTargetsResponse | None = None
    feature_access: ProjectFeatureAccessResponse


class ProjectCloneRequest(BaseModel):
    new_name: str = Field(min_length=2, max_length=120)


class OnboardClientRequest(BaseModel):
    project_name: str = Field(min_length=2, max_length=120)
    domain_url: str | None = Field(default=None, max_length=500)
    client_email: str = Field(min_length=3, max_length=320)
    client_name: str | None = Field(default=None, max_length=200)


class OnboardClientResponse(BaseModel):
    project_id: int
    user_id: int
    is_new_user: bool
    workspace_membership_id: int


class BulkInviteItem(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = None
    project_ids: list[int] | None = None


class BulkInviteRequest(BaseModel):
    invitations: list[BulkInviteItem] = Field(max_length=50)


class BulkInviteResultItem(BaseModel):
    email: str
    success: bool
    error: str | None = None
    user_id: int | None = None


class BulkInviteResponse(BaseModel):
    results: list[BulkInviteResultItem]


# --- Phase 4: Workspace Intelligence schemas ---------------------------------


class ClientHealthItem(BaseModel):
    project_id: int
    name: str
    domain_url: str | None
    latest_seo_score: float | None = None
    latest_geo_score: float | None = None
    latest_aeo_score: float | None = None
    seo_delta: float | None = None
    geo_delta: float | None = None
    aeo_delta: float | None = None
    days_since_last_audit: int | None = None
    recommendation_count: int = 0
    open_approval_count: int = 0


class ClientHealthResponse(BaseModel):
    items: list[ClientHealthItem]


class InvitationCreateRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    name: str | None = Field(default=None, max_length=200)
    role: str = Field(default="viewer")
    project_ids: list[int] | None = None


class InvitationResponse(BaseModel):
    id: int
    workspace_id: int
    invited_email: str
    invited_name: str | None
    invited_by_user_id: int | None
    role: str
    project_ids: list[int]
    status: str
    token: str
    expires_at: str | None
    accepted_at: str | None
    created_at: str | None


class ActivityLogItem(BaseModel):
    id: int
    workspace_id: int
    actor_user_id: int | None
    action: str
    target_type: str | None
    target_id: int | None
    metadata_json: dict | None = None
    created_at: str | None


class ActivityLogResponse(BaseModel):
    items: list[ActivityLogItem]
    total: int
    page: int
    page_size: int


class ProjectBudgetPeriodResponse(BaseModel):
    period_start: str
    period_end: str
    cycle_anchor_day: int
    budget_limit_scans: int | None = None
    consumed_scans: int
    remaining_scans: int | None = None
    percent_consumed: float | None = None
    warning_threshold_reached: bool
    limit_reached: bool
    status: Literal["unlimited", "healthy", "warning", "exhausted"]


class ProjectBudgetUpsertRequest(BaseModel):
    monthly_limit_scans: int = Field(ge=0, le=1_000_000)
    cycle_anchor_day: int = Field(default=1, ge=1, le=28)

    @field_validator("cycle_anchor_day")
    @classmethod
    def normalize_anchor_day(cls, value: int) -> int:
        return normalize_cycle_anchor_day(value)


class ProjectBudgetResponse(BaseModel):
    project_id: int
    workspace_id: int
    project_name: str
    domain_url: str | None = None
    budget_configured: bool
    monthly_limit_scans: int | None = None
    cycle_anchor_day: int
    current_period_start: str
    current_period_end: str
    consumed_scans: int
    remaining_scans: int | None = None
    percent_consumed: float | None = None
    status: Literal["unlimited", "healthy", "warning", "exhausted"]
    warning_threshold_reached: bool
    limit_reached: bool
    recent_periods: list[ProjectBudgetPeriodResponse] = Field(default_factory=list)


class WorkspaceCostBreakdownResponse(BaseModel):
    workspace_id: int
    generated_at: str
    projects: list[ProjectBudgetResponse] = Field(default_factory=list)


class ProjectSmartProfileGenerateRequest(BaseModel):
    overwrite_existing: bool = True


class ProjectSmartProfileGenerateResponse(BaseModel):
    project: ProjectResponse
    model: str | None = None
    required_fields: list[str] = Field(default_factory=list)
    missing_required_fields: list[str] = Field(default_factory=list)
    generated_fields: list[str] = Field(default_factory=list)
    skipped_fields: list[str] = Field(default_factory=list)
    grounded_sources: list[str] = Field(default_factory=list)


class ProjectAuditHistoryEntryResponse(BaseModel):
    id: int
    project_id: int
    site_id: int | None = None
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP"]
    url: str
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_url: str | None = None
    target_metadata: dict[str, Any] = Field(default_factory=dict)
    geo_score: float
    seo_score: float | None = None
    aeo_score: float | None = None
    status: Literal["completed", "degraded", "failed", "archived", "purged"]
    created_at: str
    full_report: dict[str, Any] | None = None
    is_archived: bool = False
    is_pinned: bool = False


class ProjectLatestAuditSelectionResponse(BaseModel):
    module: Literal["seo", "aeo", "geo"]
    status: Literal["ready", "stale", "no_matching_audit", "no_audits"]
    message: str
    recommended_audit_type: Literal["STANDARD", "DEEP"]
    recommended_launch_tier: Literal["fast", "smart", "deep"]
    compatible_audit_types: list[Literal["FAST", "SMART", "STANDARD", "DEEP"]] = Field(
        default_factory=list
    )
    stale_after_days: int
    selected_audit_age_days: int | None = None
    selected_audit: ProjectAuditHistoryEntryResponse | None = None
    latest_audit: ProjectAuditHistoryEntryResponse | None = None


class ProjectTrendPointResponse(BaseModel):
    date: str
    seo: float | None = None
    geo: float | None = None
    aeo: float | None = None
    overall: float | None = None
    volatility_score: float | None = None
    audit_count: int
    latest_audit_at: str | None = None


class ProjectTrendSummaryPointResponse(BaseModel):
    date: str | None = None
    seo: float | None = None
    geo: float | None = None
    aeo: float | None = None
    overall: float | None = None
    audit_count: int | None = None
    latest_audit_at: str | None = None


class ProjectTrendDirectionResponse(BaseModel):
    seo: Literal["up", "down", "stable"]
    geo: Literal["up", "down", "stable"]
    aeo: Literal["up", "down", "stable"]
    overall: Literal["up", "down", "stable"]


class ProjectTrendSummaryResponse(BaseModel):
    first: ProjectTrendSummaryPointResponse | None = None
    latest: ProjectTrendSummaryPointResponse | None = None
    delta: dict[str, float | None]
    trend_direction: ProjectTrendDirectionResponse


class ProjectTrendResponse(BaseModel):
    project_id: int
    period: Literal["7d", "30d", "90d", "1y", "all"]
    granularity: Literal["daily", "weekly", "monthly"]
    data_points: list[ProjectTrendPointResponse] = Field(default_factory=list)
    summary: ProjectTrendSummaryResponse


class ProjectTrendComparisonPeriodResponse(BaseModel):
    start: str
    end: str
    seo: float | None = None
    geo: float | None = None
    aeo: float | None = None
    overall: float | None = None
    audit_count: int


class ProjectTrendComparisonResponse(BaseModel):
    project_id: int
    period: Literal["30d", "90d", "1y"]
    current_period: ProjectTrendComparisonPeriodResponse
    previous_period: ProjectTrendComparisonPeriodResponse
    delta: dict[str, float | None]
    trend_direction: ProjectTrendDirectionResponse


class WorkspaceTrendSparklinePointResponse(BaseModel):
    date: str
    seo: float | None = None
    aio: float | None = None
    overall: float | None = None


class WorkspaceTrendOverviewProjectResponse(BaseModel):
    project_id: int
    name: str
    domain_url: str | None = None
    last_audit_at: str | None = None
    latest_scores: dict[str, float | None]
    delta: dict[str, float | None]
    trend_direction: ProjectTrendDirectionResponse
    sparkline: list[WorkspaceTrendSparklinePointResponse] = Field(default_factory=list)


class WorkspaceTrendOverviewResponse(BaseModel):
    workspace_id: int
    period: Literal["7d", "30d", "90d", "1y", "all"]
    projects: list[WorkspaceTrendOverviewProjectResponse] = Field(default_factory=list)


class ProjectCompetitorScoresResponse(BaseModel):
    geo: float | None = None
    seo: float | None = None
    aeo: float | None = None
    overall: float | None = None


class ProjectCompetitorListItemResponse(BaseModel):
    id: int
    project_id: int
    target_url: str
    normalized_domain: str
    display_name: str
    auto_audit_enabled: bool
    created_at: str | None = None
    latest_status: Literal["not_started", "pending", "failed", "succeeded"]
    latest_failure_reason: str | None = None
    last_benchmarked_at: str | None = None
    latest_source_audit_id: int | None = None
    # BUG-026: Expose the canonical competitor site_id for PDF pipeline.
    competitor_site_id: int | None = None
    latest_scores: ProjectCompetitorScoresResponse


class ProjectCompetitorCreateRequest(BaseModel):
    target_url: str = Field(min_length=3, max_length=500)
    display_name: str | None = Field(default=None, max_length=120)


class ProjectBrandFactCreateRequest(BaseModel):
    kind: Literal["fact", "claim"] = "fact"
    statement: str = Field(min_length=1, max_length=2000)
    is_forbidden: bool = False

    @field_validator("statement")
    @classmethod
    def _statement_not_blank(cls, value: str) -> str:
        if not str(value or "").strip():
            raise ValueError("statement must not be empty")
        return value


class ProjectBrandFactResponse(BaseModel):
    id: int
    project_id: int
    kind: str
    statement: str
    is_forbidden: bool
    created_at: str | None = None


class AdvisorPlanSummaryResponse(BaseModel):
    total_actions: int = 0
    high_impact: int = 0
    medium_impact: int = 0
    low_impact: int = 0


class AdvisorPlanTrendPointResponse(BaseModel):
    created_at: str | None = None
    total_actions: int = 0
    high_impact: int = 0


class AdvisorPlanActionDeltaResponse(BaseModel):
    fingerprint: str
    action: str
    title: str | None = None
    impact: str | None = None
    effort: str | None = None
    rank: int | None = None


class AdvisorPlanDeltaResponse(BaseModel):
    actions_added: list[AdvisorPlanActionDeltaResponse] = Field(default_factory=list)
    actions_resolved: list[AdvisorPlanActionDeltaResponse] = Field(default_factory=list)
    actions_carried: list[AdvisorPlanActionDeltaResponse] = Field(default_factory=list)
    impact_delta: dict[str, int] = Field(default_factory=dict)
    summary_prev: AdvisorPlanSummaryResponse | None = None
    summary_curr: AdvisorPlanSummaryResponse | None = None


class AdvisorPlanProgressResponse(BaseModel):
    """Read-only Advisor-plan progress over time for an Executive project."""

    latest_summary: AdvisorPlanSummaryResponse | None = None
    first_summary: AdvisorPlanSummaryResponse | None = None
    trend: list[AdvisorPlanTrendPointResponse] = Field(default_factory=list)
    latest_delta: AdvisorPlanDeltaResponse | None = None


class RecommendationDecisionCreateRequest(BaseModel):
    """Record an accept/dismiss decision for an Advisor recommendation.

    Callers supply either a pre-computed ``action_fingerprint`` or the raw
    ``action_text`` (from which a key is derived). At least one of the two must
    be present.

    ``problem_code`` is the recommendation's deterministic code when it carries
    one (``metadata.advisor.actions[].problem_code``). Supplying it keys the
    decision on the failing check instead of on the LLM-written action text, so
    a dismissal still matches after the next audit rewords the fix. An unknown
    code is ignored rather than stored, which degrades to text identity.
    """

    action_fingerprint: str | None = Field(default=None, max_length=64)
    action_text: str | None = Field(default=None, max_length=2000)
    action_label: str | None = Field(default=None, max_length=2000)
    problem_code: str | None = Field(default=None, max_length=64)
    decision: Literal["accepted", "dismissed"]
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_fingerprint_or_text(self) -> "RecommendationDecisionCreateRequest":
        has_fingerprint = bool(str(self.action_fingerprint or "").strip())
        has_text = bool(str(self.action_text or "").strip())
        if not has_fingerprint and not has_text:
            raise ValueError("Either action_fingerprint or action_text is required.")
        return self


class RecommendationDecisionResponse(BaseModel):
    id: int
    project_id: int
    action_fingerprint: str
    action_label: str | None = None
    decision: str
    note: str | None = None
    decided_by: int | None = None
    created_at: str | None = None


class CompetitiveAnalysisProjectResponse(BaseModel):
    id: int
    name: str
    url: str | None = None
    scores: ProjectCompetitorScoresResponse
    last_audit_at: str | None = None


class CompetitiveAnalysisCompetitorResponse(BaseModel):
    id: int
    name: str
    url: str
    status: Literal["not_started", "pending", "failed", "succeeded"]
    last_benchmarked_at: str | None = None
    failure_reason: str | None = None
    scores: ProjectCompetitorScoresResponse
    delta: dict[str, float | None]


class CompetitiveBenchmarkStatusResponse(BaseModel):
    auto_competitor_audits_enabled: bool
    competitive_digest_frequency: Literal["off", "weekly", "monthly"]
    pending_competitors: int
    failed_competitors: int
    configured_competitors: int
    has_data: bool


class CompetitiveAnalysisResponse(BaseModel):
    project_id: int
    project: CompetitiveAnalysisProjectResponse
    competitors: list[CompetitiveAnalysisCompetitorResponse] = Field(default_factory=list)
    rank: dict[str, int | None]
    updated_at: str | None = None
    benchmark_status: CompetitiveBenchmarkStatusResponse


class CompetitiveTrendPointResponse(BaseModel):
    date: str | None = None
    value: float | None = None


class CompetitiveTrendLineResponse(BaseModel):
    key: str
    label: str
    is_project: bool
    points: list[CompetitiveTrendPointResponse] = Field(default_factory=list)


class CompetitiveTrendResponse(BaseModel):
    project_id: int
    metric: Literal["geo", "seo", "aeo", "overall"]
    period: Literal["30d", "90d", "1y", "all"]
    lines: list[CompetitiveTrendLineResponse] = Field(default_factory=list)


class CompetitiveGapItemResponse(BaseModel):
    competitor_id: int
    competitor_name: str
    metric: Literal["geo", "seo", "aeo"]
    project_score: float
    competitor_score: float
    delta: float
    severity: Literal["watch", "medium", "high"]
    reason: str
    recommendation: str
    evidence: list[str] = Field(default_factory=list)


class CompetitiveGapSummaryResponse(BaseModel):
    gap_count: int
    largest_gap_metric: Literal["geo", "seo", "aeo"] | None = None
    largest_gap_delta: float | None = None


class CompetitiveGapResponse(BaseModel):
    project_id: int
    generated_at: str | None = None
    summary: CompetitiveGapSummaryResponse
    gaps: list[CompetitiveGapItemResponse] = Field(default_factory=list)
    pending_competitors: list[str] = Field(default_factory=list)
    failed_competitors: list[dict[str, Any]] = Field(default_factory=list)


class CompetitiveRefreshResponse(BaseModel):
    project_id: int
    source_audit_id: int
    queued_jobs: int
    skipped_competitors: list[str] = Field(default_factory=list)
    message: str


class CompetitiveGapBriefResponse(BaseModel):
    competitor_id: int
    competitor_name: str
    content: str


class ProjectProgressReportRequest(BaseModel):
    report_month: date | None = None
    deliver_email: bool = False


class ProjectProgressReportListItemResponse(BaseModel):
    id: int
    project_id: int
    workspace_id: int
    report_month: str
    period_start: str
    period_end: str
    generated_by: str
    recipient_count: int
    email_sent_at: str | None = None
    created_at: str | None = None
    language: str = "en"
    expired: bool = False
    retention_days: int = 30
    snapshot: dict[str, Any]


class ProjectTaskAssigneeResponse(BaseModel):
    user_id: int
    email: str
    role: str
    is_owner: bool = False


class ProjectTaskResponse(BaseModel):
    id: int
    project_id: int
    title: str
    description: str | None = None
    status: Literal["todo", "in_progress", "done"]
    priority: Literal["low", "medium", "high", "critical"]
    origin: Literal["manual", "audit_recommendation"]
    category: str
    source_audit_id: int | None = None
    source_recommendation_key: str | None = None
    assigned_to_user_id: int | None = None
    assignee: ProjectTaskAssigneeResponse | None = None
    due_date: date | None = None
    resolved_at: str | None = None
    verified_at: str | None = None
    verification_audit_id: int | None = None
    resolution_source: Literal["manual", "audit_validated"] | None = None
    sort_order: int
    created_at: str | None = None
    updated_at: str | None = None


class ProjectTaskSummaryResponse(BaseModel):
    todo: int
    in_progress: int
    done: int
    unassigned: int
    audit_linked: int
    overdue: int
    validated: int


class ProjectTaskBoardResponse(BaseModel):
    project_id: int
    workspace_id: int
    can_edit: bool
    latest_audit_id: int | None = None
    latest_audit_at: str | None = None
    assignees: list[ProjectTaskAssigneeResponse] = Field(default_factory=list)
    summary: ProjectTaskSummaryResponse
    tasks: list[ProjectTaskResponse] = Field(default_factory=list)


class ProjectTaskCreateRequest(BaseModel):
    title: str
    description: str | None = None
    status: Literal["todo", "in_progress", "done"] = "todo"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    category: str = "General"
    assigned_to_user_id: int | None = None
    due_date: date | None = None
    source_audit_id: int | None = None
    source_recommendation_key: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Task title is required.")
        return normalized[:255]

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized[:4000] or None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str) -> str:
        normalized = value.strip()
        return normalized[:120] or "General"

    @field_validator("source_recommendation_key")
    @classmethod
    def _validate_source_key(cls, value: str | None) -> str | None:
        normalized = (value or "").strip()
        return normalized[:255] or None


class ProjectTaskUpdateRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: Literal["todo", "in_progress", "done"] | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    category: str | None = None
    assigned_to_user_id: int | None = None
    due_date: date | None = None
    source_audit_id: int | None = None
    source_recommendation_key: str | None = None

    @field_validator("title")
    @classmethod
    def _validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Task title cannot be empty.")
        return normalized[:255]

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:4000] or None

    @field_validator("category")
    @classmethod
    def _validate_category(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:120] or "General"

    @field_validator("source_recommendation_key")
    @classmethod
    def _validate_source_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized[:255] or None


class ProjectTaskReorderColumnRequest(BaseModel):
    status: Literal["todo", "in_progress", "done"]
    task_ids: list[int] = Field(default_factory=list)


class ProjectTaskReorderRequest(BaseModel):
    columns: list[ProjectTaskReorderColumnRequest] = Field(default_factory=list)


class ProjectTaskImpactDeltaResponse(BaseModel):
    seo: float | None = None
    geo: float | None = None
    aeo: float | None = None
    overall: float | None = None


class ProjectTaskImpactItemResponse(BaseModel):
    task_id: int
    title: str
    category: str
    priority: Literal["low", "medium", "high", "critical"]
    resolution_source: Literal["manual", "audit_validated"] | None = None
    source_audit_id: int | None = None
    source_audit_created_at: str | None = None
    verification_audit_id: int | None = None
    verified_at: str | None = None
    resolved_at: str | None = None
    verification_status: Literal["validated", "pending_validation"]
    delta: ProjectTaskImpactDeltaResponse
    narrative: str | None = None


class ProjectTaskImpactSummaryResponse(BaseModel):
    resolved_count: int
    validated_count: int
    pending_validation_count: int
    strongest_metric: Literal["seo", "geo", "aeo"] | None = None
    strongest_delta: float | None = None


class ProjectTaskImpactResponse(BaseModel):
    project_id: int
    summary: ProjectTaskImpactSummaryResponse
    items: list[ProjectTaskImpactItemResponse] = Field(default_factory=list)


class AeoQueryTrackerItemPayload(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    tracked_at: datetime | None = None
    citation_hits: int = Field(default=0, ge=0, le=100000)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("query is required")
        return normalized


class AeoQueryTrackerItemResponse(BaseModel):
    query: str
    tracked_at: str | None
    citation_hits: int


class AeoQueryTrackerUpsertRequest(BaseModel):
    context_url: str | None = Field(default=None, max_length=1000)
    items: list[AeoQueryTrackerItemPayload] = Field(default_factory=list, max_length=200)


class AeoQueryTrackerResponse(BaseModel):
    context_key: str
    items: list[AeoQueryTrackerItemResponse] = Field(default_factory=list)


class GeoPromptTrackerItemPayload(BaseModel):
    prompt: str = Field(min_length=1, max_length=5000)
    tracked_at: datetime | None = None
    citation_hits: int = Field(default=0, ge=0, le=100000)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt is required")
        return normalized


class GeoPromptTrackerItemResponse(BaseModel):
    prompt: str
    tracked_at: str | None
    citation_hits: int


class GeoPromptTrackerUpsertRequest(BaseModel):
    context_url: str | None = Field(default=None, max_length=1000)
    items: list[GeoPromptTrackerItemPayload] = Field(default_factory=list, max_length=200)


class GeoPromptTrackerResponse(BaseModel):
    context_key: str
    items: list[GeoPromptTrackerItemResponse] = Field(default_factory=list)


class OAuthConnectionUpsertRequest(BaseModel):
    access_token: str = Field(min_length=1, max_length=20000)
    refresh_token: str | None = Field(default=None, max_length=20000)
    token_type: str | None = Field(default=None, max_length=120)
    scope: str | None = Field(default=None, max_length=2000)
    expires_at: datetime | None = None

    @field_validator("access_token")
    @classmethod
    def normalize_access_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("access_token is required.")
        return normalized

    @field_validator("refresh_token", "token_type", "scope")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OAuthConnectionResponse(BaseModel):
    provider: Literal["google", "bing", "jira"]
    has_refresh_token: bool
    token_type: str | None
    scope: str | None
    expires_at: str | None
    updated_at: str | None
    access_token_preview: str | None
    site_name: str | None = None
    site_url: str | None = None
    connected: bool = False
    configured: bool = False


# The workspace OAuth flow for "bing" goes through the bing_webmaster client
# registration, so its credentials are the BING_WEBMASTER_* pair, not the
# Microsoft-SSO-flavoured BING_* pair.
_OAUTH_PROVIDER_CREDENTIAL_ENV = {
    "google": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "bing": ("BING_WEBMASTER_CLIENT_ID", "BING_WEBMASTER_CLIENT_SECRET"),
    "jira": ("JIRA_CLIENT_ID", "JIRA_CLIENT_SECRET"),
}


def _oauth_provider_configured(provider: str) -> bool:
    """Whether this deployment holds OAuth credentials for `provider`.

    services/oauth_service registers every provider even with empty env values
    so oauth.create_client() never returns None - the credential values are the
    real signal. Reading the same settings the registration read reports the
    deployment state and, unlike probing a failed request, cannot be confused
    with a transient network error.
    """
    env_names = _OAUTH_PROVIDER_CREDENTIAL_ENV.get(provider)
    if env_names is None:
        return True
    from core.config import settings

    return all(str(getattr(settings, name, None) or "").strip() for name in env_names)


class ProjectDataSourceUpsertRequest(BaseModel):
    binding_mode: Literal["workspace", "client_magic_link", "ai_estimate"] = "workspace"
    source_id: str | None = Field(default=None, max_length=500)
    source_label: str | None = Field(default=None, max_length=500)
    is_active: bool = True

    @field_validator("source_id", "source_label")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ProjectDataSourceResponse(BaseModel):
    id: int | None
    project_id: int
    provider: Literal["google", "bing"]
    source_type: Literal["google_search_console", "google_analytics_4", "bing_webmaster"]
    binding_mode: Literal["workspace", "client_magic_link", "ai_estimate"]
    source_id: str | None
    source_label: str | None
    is_active: bool
    oauth_connection_id: int | None
    project_oauth_connection_id: int | None
    workspace_provider_connected: bool
    updated_at: str | None


class ProjectDataSourceCatalogItemResponse(BaseModel):
    id: str
    label: str
    description: str | None = None


class ProjectDataSourceCatalogResponse(BaseModel):
    source_type: Literal["google_search_console", "google_analytics_4", "bing_webmaster"]
    provider: Literal["google", "bing"]
    workspace_provider_connected: bool
    # SIGV2-1207: true when the project's workspace holds no connection for the
    # provider but the user does hold one on another workspace they can access,
    # so the UI can say "connected elsewhere" instead of asking them to do the
    # connect they already did.
    connected_on_other_workspace: bool = False
    items: list[ProjectDataSourceCatalogItemResponse]
    required_scopes: list[str] = Field(default_factory=list)
    granted_scopes: list[str] = Field(default_factory=list)
    missing_scopes: list[str] = Field(default_factory=list)
    error: str | None = None
    fetched_at: str


class MagicLinkCreateRequest(BaseModel):
    expires_in_hours: int = Field(default=72, ge=1, le=24 * 30)


class MagicLinkResponse(BaseModel):
    project_id: int
    token: str
    link_url: str
    expires_at: str
    is_used: bool
    created_at: str | None


class MagicLinkProviderConnectionResponse(BaseModel):
    provider: Literal["google", "bing"]
    connected: bool
    connected_at: str | None = None
    connected_by_email: str | None = None
    has_refresh_token: bool = False
    expires_at: str | None = None
    scope: str | None = None


class MagicLinkPublicResponse(BaseModel):
    valid: bool
    token: str
    project_id: int | None
    workspace_id: int | None
    project_name: str | None
    domain_url: str | None
    expires_at: str | None
    is_used: bool
    connection_state: Literal["invalid", "pending", "expired", "used", "connected"]
    providers: list[MagicLinkProviderConnectionResponse] = Field(default_factory=list)


class MagicLinkConsumeResponse(BaseModel):
    token: str
    consumed: bool
    consumed_at: str | None


class ProjectMagicLinkStatusResponse(BaseModel):
    project_id: int
    status: Literal["not_requested", "pending", "expired", "connected"]
    latest_link_created_at: str | None
    latest_link_expires_at: str | None
    latest_link_is_used: bool
    open_magic_link_count: int
    providers: list[MagicLinkProviderConnectionResponse] = Field(default_factory=list)


@router.get("/workspaces", response_model=list[WorkspaceSummaryResponse])
def list_user_workspaces(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all workspaces the authenticated user owns or is a member of."""
    owned = (
        db.query(models.Workspace)
        .filter(models.Workspace.owner_id == user.id)
        .order_by(models.Workspace.created_at.asc(), models.Workspace.id.asc())
        .all()
    )
    owned_ids = {w.id for w in owned}

    member_workspaces = (
        db.query(models.Workspace)
        .join(models.WorkspaceUser, models.WorkspaceUser.workspace_id == models.Workspace.id)
        .filter(
            models.WorkspaceUser.user_id == user.id,
            models.Workspace.id.notin_(owned_ids),
        )
        .order_by(models.Workspace.created_at.asc(), models.Workspace.id.asc())
        .all()
    )

    all_workspaces = owned + member_workspaces
    if not all_workspaces:
        # Ensure at least one workspace exists for the user.
        ws = _get_or_create_current_workspace(db, user)
        all_workspaces = [ws]

    result = []
    workspace_ids = [w.id for w in all_workspaces]

    project_counts = dict(
        db.query(models.Project.workspace_id, func.count(models.Project.id))
        .filter(models.Project.workspace_id.in_(workspace_ids))
        .group_by(models.Project.workspace_id)
        .all()
    )
    member_counts = dict(
        db.query(models.WorkspaceUser.workspace_id, func.count(models.WorkspaceUser.id))
        .filter(models.WorkspaceUser.workspace_id.in_(workspace_ids))
        .group_by(models.WorkspaceUser.workspace_id)
        .all()
    )
    oauth_counts = dict(
        db.query(models.OAuthConnection.workspace_id, func.count(models.OAuthConnection.id))
        .filter(models.OAuthConnection.workspace_id.in_(workspace_ids))
        .group_by(models.OAuthConnection.workspace_id)
        .all()
    )

    memberships = {
        m.workspace_id: m.role.value
        for m in db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id.in_(workspace_ids),
            models.WorkspaceUser.user_id == user.id,
        )
        .all()
    }

    for workspace in all_workspaces:
        role = memberships.get(workspace.id, models.WorkspaceRole.ADMIN.value)
        result.append(
            _serialize_workspace(
                workspace,
                current_user_id=user.id,
                role=role,
                project_count=int(project_counts.get(workspace.id, 0)),
                member_count=int(member_counts.get(workspace.id, 0)),
                oauth_connection_count=int(oauth_counts.get(workspace.id, 0)),
            )
        )

    return result


@router.get("/workspaces/current", response_model=WorkspaceSummaryResponse)
def get_current_workspace(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)

    project_count = (
        db.query(func.count(models.Project.id))
        .filter(models.Project.workspace_id == workspace.id)
        .scalar()
        or 0
    )
    member_count = (
        db.query(func.count(models.WorkspaceUser.id))
        .filter(models.WorkspaceUser.workspace_id == workspace.id)
        .scalar()
        or 0
    )
    oauth_connection_count = (
        db.query(func.count(models.OAuthConnection.id))
        .filter(models.OAuthConnection.workspace_id == workspace.id)
        .scalar()
        or 0
    )

    return _serialize_workspace(
        workspace,
        current_user_id=user.id,
        role=role,
        project_count=int(project_count),
        member_count=int(member_count),
        oauth_connection_count=int(oauth_connection_count),
    )


class WorkspaceCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


@router.post(
    "/workspaces", response_model=WorkspaceSummaryResponse, status_code=status.HTTP_201_CREATED
)
def create_workspace(
    payload: WorkspaceCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new workspace. Requires the has_multi_workspace_federation capability."""
    _require_plan_feature(
        user,
        feature_key="has_multi_workspace_federation",
        detail="Multiple workspaces is available on the Executive plan.",
        status_code=status.HTTP_403_FORBIDDEN,
    )

    workspace = models.Workspace(name=payload.name.strip(), owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    _ensure_workspace_owner_membership(workspace, db)

    return _serialize_workspace(
        workspace,
        current_user_id=user.id,
        role=models.WorkspaceRole.ADMIN.value,
        project_count=0,
        member_count=1,
        oauth_connection_count=0,
    )


@router.delete("/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an owned workspace. The user must own it and must have at least one remaining workspace."""
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")
    if workspace.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Only the workspace owner can delete it.")

    # Ensure the user will still have at least one workspace after deletion.
    remaining_owned = (
        db.query(func.count(models.Workspace.id))
        .filter(models.Workspace.owner_id == user.id, models.Workspace.id != workspace_id)
        .scalar()
        or 0
    )
    if int(remaining_owned) == 0:
        raise HTTPException(
            status_code=400,
            detail="You cannot delete your last workspace. Create another workspace first.",
        )

    db.delete(workspace)
    db.commit()


@router.patch("/workspaces/current", response_model=WorkspaceSummaryResponse)
def update_current_workspace(
    payload: WorkspaceUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    if payload.name is not None:
        workspace.name = payload.name
    if payload.role_mode is not None:
        workspace.role_mode = payload.role_mode.value
    db.commit()
    db.refresh(workspace)

    project_count = (
        db.query(func.count(models.Project.id))
        .filter(models.Project.workspace_id == workspace.id)
        .scalar()
        or 0
    )
    member_count = (
        db.query(func.count(models.WorkspaceUser.id))
        .filter(models.WorkspaceUser.workspace_id == workspace.id)
        .scalar()
        or 0
    )
    oauth_connection_count = (
        db.query(func.count(models.OAuthConnection.id))
        .filter(models.OAuthConnection.workspace_id == workspace.id)
        .scalar()
        or 0
    )

    return _serialize_workspace(
        workspace,
        current_user_id=user.id,
        role=role,
        project_count=int(project_count),
        member_count=int(member_count),
        oauth_connection_count=int(oauth_connection_count),
    )


@router.get("/workspaces/current/white-label", response_model=WorkspaceWhiteLabelSettingsResponse)
def get_current_workspace_white_label_settings(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    return _serialize_white_label_settings(db=db, workspace=workspace)


@router.put("/workspaces/current/white-label", response_model=WorkspaceWhiteLabelSettingsResponse)
def update_current_workspace_white_label_settings(
    payload: WorkspaceWhiteLabelBrandingRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)
    _require_workspace_white_label_plan(db, workspace)

    apply_workspace_branding(workspace=workspace, payload=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(workspace)
    return _serialize_white_label_settings(db=db, workspace=workspace)


@router.get(
    "/workspaces/current/email-footer",
    response_model=WorkspaceEmailFooterSettingsResponse,
)
def get_current_workspace_email_footer_settings(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    return _serialize_workspace_email_footer_settings(workspace=workspace)


@router.patch(
    "/workspaces/current/email-footer",
    response_model=WorkspaceEmailFooterSettingsResponse,
)
def update_current_workspace_email_footer_settings(
    payload: WorkspaceEmailFooterUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)
    _require_workspace_white_label_plan(db, workspace)

    apply_workspace_branding(workspace=workspace, payload=payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(workspace)
    return _serialize_workspace_email_footer_settings(workspace=workspace)


@router.post(
    "/workspaces/current/white-label/domains",
    response_model=WorkspaceWhiteLabelSettingsResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_current_workspace_custom_domain(
    payload: WorkspaceCustomDomainCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)
    _require_workspace_white_label_plan(db, workspace)

    create_workspace_custom_domain(db, workspace_id=workspace.id, domain=payload.domain)
    db.commit()
    db.refresh(workspace)
    return _serialize_white_label_settings(db=db, workspace=workspace)


@router.post(
    "/workspaces/current/white-label/domains/{domain_id}/verify",
    response_model=WorkspaceWhiteLabelSettingsResponse,
)
def verify_current_workspace_custom_domain(
    domain_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)
    _require_workspace_white_label_plan(db, workspace)

    custom_domain = (
        db.query(models.CustomDomain)
        .filter(
            models.CustomDomain.id == domain_id,
            models.CustomDomain.workspace_id == workspace.id,
        )
        .first()
    )
    if custom_domain is None:
        raise HTTPException(status_code=404, detail="Custom domain not found.")

    verify_workspace_custom_domain(db, custom_domain=custom_domain)
    db.commit()
    db.refresh(custom_domain)
    db.refresh(workspace)

    owner = workspace.owner
    email_service = EmailService(db)
    context = {
        "workspace_name": workspace.name,
        "company_name": resolve_workspace_branding(workspace)["company_name"],
        "domain": custom_domain.domain,
        "dns_target": custom_domain.dns_target,
        "preview_url": f"https://{custom_domain.domain}",
        "settings_url": f"{_resolve_frontend_base_url()}/dashboard/settings",
        "error_message": custom_domain.verification_error,
    }
    if owner is not None:
        if custom_domain.verified and custom_domain.ssl_status != "error":
            email_service.queue_template_email(
                to_email=owner.email,
                template_key="workspace.domain_verified",
                context=context,
                user_id=owner.id,
                correlation_id=f"workspace.domain-verified:{workspace.id}:{custom_domain.id}",
            )
            if custom_domain.ssl_status == "active":
                email_service.queue_template_email(
                    to_email=owner.email,
                    template_key="workspace.ssl_provisioned",
                    context=context,
                    user_id=owner.id,
                    correlation_id=f"workspace.ssl-provisioned:{workspace.id}:{custom_domain.id}",
                )
        else:
            email_service.queue_template_email(
                to_email=owner.email,
                template_key="workspace.domain_error",
                context=context,
                user_id=owner.id,
                correlation_id=f"workspace.domain-error:{workspace.id}:{custom_domain.id}",
            )
        db.commit()

    return _serialize_white_label_settings(db=db, workspace=workspace)


@router.delete(
    "/workspaces/current/white-label/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_current_workspace_custom_domain(
    domain_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)
    _require_workspace_white_label_plan(db, workspace)

    custom_domain = (
        db.query(models.CustomDomain)
        .filter(
            models.CustomDomain.id == domain_id,
            models.CustomDomain.workspace_id == workspace.id,
        )
        .first()
    )
    if custom_domain is None:
        raise HTTPException(status_code=404, detail="Custom domain not found.")

    if is_cloudflare_custom_hostname_configured(db):
        try:
            delete_cloudflare_custom_hostname(custom_domain.domain, db=db)
        except Exception:
            logger.warning(
                "Cloudflare cleanup failed for domain %s (id=%s); proceeding with local deletion.",
                custom_domain.domain,
                custom_domain.id,
                exc_info=True,
            )

    deleted = delete_workspace_custom_domain(db, workspace_id=workspace.id, domain_id=domain_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Custom domain not found.")
    db.commit()
    return None


@router.get("/tenants/current-branding", response_model=TenantBrandingResponse)
def get_current_tenant_branding(
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_workspace_id = getattr(request.state, "tenant_workspace_id", None)
    tenant_domain = getattr(request.state, "tenant_domain", None)
    if tenant_workspace_id is None:
        raise HTTPException(status_code=404, detail="No active tenant branding for this host.")

    workspace = (
        db.query(models.Workspace).filter(models.Workspace.id == tenant_workspace_id).first()
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    branding = resolve_workspace_branding(workspace)
    return TenantBrandingResponse(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        company_name=branding["company_name"],
        custom_logo_url=branding["custom_logo_url"],
        primary_color=branding["primary_color"],
        secondary_color=branding["secondary_color"],
        custom_favicon_url=branding["custom_favicon_url"],
        custom_page_title=branding["custom_page_title"],
        custom_meta_description=branding["custom_meta_description"],
        hide_powered_by=branding["hide_powered_by"],
        active_domain=tenant_domain,
    )


@router.get("/tenants/domain-activation", include_in_schema=False)
def confirm_tenant_domain_activation(
    domain: str = Query(..., min_length=4, max_length=253),
    db: Session = Depends(get_db),
):
    if not is_tls_host_allowed(db, domain=domain):
        raise HTTPException(status_code=404, detail="Domain is not active.")
    return Response(status_code=status.HTTP_200_OK)


@router.get("/workspaces/current/members", response_model=list[WorkspaceMemberResponse])
def list_current_workspace_members(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)

    memberships = (
        db.query(models.WorkspaceUser)
        .join(models.User, models.User.id == models.WorkspaceUser.user_id)
        .filter(models.WorkspaceUser.workspace_id == workspace.id)
        .order_by(
            (models.WorkspaceUser.user_id == workspace.owner_id).desc(),
            models.WorkspaceUser.created_at.asc(),
            models.WorkspaceUser.id.asc(),
        )
        .all()
    )

    return [
        _serialize_workspace_member(membership, workspace_owner_id=workspace.owner_id)
        for membership in memberships
    ]


@router.post(
    "/workspaces/current/members",
    response_model=WorkspaceMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
def upsert_current_workspace_member(
    payload: WorkspaceMemberUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    target_user = (
        db.query(models.User).filter(func.lower(models.User.email) == payload.email.lower()).first()
    )
    if target_user is None:
        raise HTTPException(
            status_code=404,
            detail="User with this email does not exist yet.",
        )

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == target_user.id,
        )
        .first()
    )
    target_role = (
        models.WorkspaceRole.ADMIN.value if target_user.id == workspace.owner_id else payload.role
    )

    if membership is None:
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=target_user.id,
            role=models.WorkspaceRole(target_role),
        )
        db.add(membership)
    else:
        membership.role = models.WorkspaceRole(target_role)

    db.commit()
    db.refresh(membership)

    return _serialize_workspace_member(membership, workspace_owner_id=workspace.owner_id)


@router.post(
    "/workspaces/{workspace_id}/invite-client",
    response_model=ClientInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_workspace_client(
    workspace_id: int,
    payload: ClientInvitationRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace, role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
    _require_workspace_manage_access(role)

    if user.id == workspace.owner_id:
        db.refresh(user)

    project_rows = (
        db.query(models.Project)
        .filter(
            models.Project.workspace_id == workspace.id,
            models.Project.id.in_(payload.project_ids),
        )
        .order_by(models.Project.id.asc())
        .all()
    )
    if len(project_rows) != len(payload.project_ids):
        raise HTTPException(
            status_code=400, detail="All invited projects must belong to the target workspace."
        )

    if role == models.WorkspaceRole.MANAGER.value:
        caller_membership = (
            db.query(models.WorkspaceUser)
            .filter(
                models.WorkspaceUser.workspace_id == workspace.id,
                models.WorkspaceUser.user_id == user.id,
            )
            .first()
        )
        assigned_project_ids = {
            int(row.project_id)
            for row in db.query(models.WorkspaceUserProjectAccess)
            .filter(
                models.WorkspaceUserProjectAccess.workspace_user_id
                == (caller_membership.id if caller_membership else -1),
                models.WorkspaceUserProjectAccess.project_id.in_(payload.project_ids),
            )
            .all()
        }
        if assigned_project_ids != set(payload.project_ids):
            raise HTTPException(
                status_code=403,
                detail="Managers may invite clients only to assigned projects.",
            )

    target_user = (
        db.query(models.User).filter(func.lower(models.User.email) == payload.email.lower()).first()
    )
    invited = target_user is None
    if target_user is None:
        target_user = models.User(
            email=payload.email,
            hashed_password=hash_password(secrets.token_urlsafe(32)),
            role="user",
            company_name=payload.name,
        )
        db.add(target_user)
        db.commit()
        db.refresh(target_user)

    if target_user.id == workspace.owner_id:
        raise HTTPException(
            status_code=400, detail="Workspace owner cannot be converted into a client user."
        )

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == target_user.id,
        )
        .first()
    )
    if (
        membership is not None
        and _role_value(membership.role) != models.WorkspaceRole.CLIENT_READONLY.value
    ):
        raise HTTPException(
            status_code=409,
            detail="This user is already an internal workspace member and cannot be converted to client access.",
        )

    if payload.name and not (target_user.company_name or "").strip():
        target_user.company_name = payload.name

    if membership is None:
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=target_user.id,
            role=models.WorkspaceRole.CLIENT_READONLY,
        )
        db.add(membership)
    db.commit()
    db.refresh(target_user)
    db.refresh(membership)

    replace_client_project_assignments(
        db,
        membership=membership,
        project_ids=payload.project_ids,
    )
    db.commit()

    owner = workspace.owner
    workspace_branding = resolve_workspace_branding(workspace)
    agency_name = str(workspace_branding["company_name"] or "").strip() or (
        owner.email.split("@", 1)[0] if owner and owner.email else workspace.name
    )
    email_service = EmailService(db)
    frontend_base_url = _resolve_frontend_base_url()
    portal_url = f"{frontend_base_url}/portal"
    if invited:
        invitation_token = AuthService(db).create_password_reset_token(target_user.email)
        invitation_url = f"{frontend_base_url}/reset-password?token={invitation_token}&flow=invite"
    else:
        invitation_url = f"{frontend_base_url}/login?next=/portal"
    email_entry = await email_service.send_client_invitation_email(
        target_user.email,
        invitation_url=invitation_url,
        workspace_name=workspace.name,
        portal_url=portal_url,
        agency_name=agency_name,
        project_names=[project.name for project in project_rows],
        user_id=target_user.id,
        invitee_name=payload.name or target_user.company_name,
        correlation_id=f"workspace.client-invite:{workspace.id}:{target_user.id}",
    )

    return ClientInvitationResponse(
        user_id=target_user.id,
        email=target_user.email,
        role=models.WorkspaceRole.CLIENT_READONLY.value,
        project_ids=payload.project_ids,
        invited=invited,
        created_at=_isoformat(membership.created_at),
        email_queued=email_entry is not None,
        invitation_url=None,
    )


@router.patch(
    "/workspaces/current/members/{member_user_id}",
    response_model=WorkspaceMemberResponse,
)
def update_current_workspace_member_role(
    member_user_id: int,
    payload: WorkspaceMemberRoleUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == member_user_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")

    if member_user_id == workspace.owner_id and payload.role != models.WorkspaceRole.ADMIN.value:
        raise HTTPException(status_code=400, detail="Workspace owner role cannot be changed.")

    membership.role = models.WorkspaceRole(payload.role)
    db.commit()
    db.refresh(membership)
    return _serialize_workspace_member(membership, workspace_owner_id=workspace.owner_id)


@router.delete(
    "/workspaces/current/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_current_workspace_member(
    member_user_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    if member_user_id == workspace.owner_id:
        raise HTTPException(status_code=400, detail="Workspace owner cannot be removed.")

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == member_user_id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace member not found.")

    db.delete(membership)
    db.commit()
    return None


@router.get("/workspaces/current/projects", response_model=list[ProjectResponse])
def list_current_workspace_projects(
    include_archived: bool = Query(False),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)

    base_q = (
        db.query(
            models.Project,
            func.count(models.Audit.id).label("audit_count"),
            func.max(models.Audit.created_at).label("last_audit_at"),
        )
        # SIGV2-1117: the scope clause belongs in the join condition, not in a
        # WHERE, so a project with no audits of its own still appears with a
        # count of zero.
        .outerjoin(
            models.Audit,
            and_(
                models.Audit.project_id == models.Project.id,
                own_project_audit_clause(),
            ),
        )
        .filter(models.Project.workspace_id == workspace.id)
    )
    if not include_archived:
        base_q = base_q.filter(
            (models.Project.status == None)  # noqa: E711
            | (models.Project.status != models.ProjectStatus.ARCHIVED)
        )
    rows = (
        base_q.group_by(models.Project.id)
        .order_by(models.Project.created_at.desc(), models.Project.id.desc())
        .all()
    )

    projects: list[dict[str, object]] = []
    for row in rows:
        latest_seo_score, latest_geo_score, latest_aeo_score = _load_latest_project_scores(
            db,
            project_id=row.Project.id,
        )
        projects.append(
            _serialize_project(
                row.Project,
                user=user,
                audit_count=int(row.audit_count or 0),
                last_audit_at=row.last_audit_at,
                latest_seo_score=latest_seo_score,
                latest_geo_score=latest_geo_score,
                latest_aeo_score=latest_aeo_score,
            )
        )

    return projects


@router.get(
    "/workspaces/{workspace_id}/cost-breakdown",
    response_model=WorkspaceCostBreakdownResponse,
)
def get_workspace_cost_breakdown(
    workspace_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace, _role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
    project_rows = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace.id)
        .order_by(models.Project.name.asc(), models.Project.id.asc())
        .all()
    )
    return {
        "workspace_id": workspace.id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "projects": [
            _serialize_project_budget_response(db, project=project_row)
            for project_row in project_rows
        ],
    }


@router.post(
    "/workspaces/current/projects",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_in_current_workspace(
    payload: ProjectCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    project = models.Project(
        workspace_id=workspace.id,
        name=payload.name,
        domain_url=payload.domain_url,
        target_country=payload.target_country,
        language=payload.language or "en",
        icp_roles=[],
        competitors_json=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # SIGV2-1186: a new project starts with a base prompt covering each of the
    # five customer-facing search types, so the AIO drilldown has something
    # real to measure instead of reporting four or five types as unmeasured
    # with no way to say what is missing. Plan-bounded (a locked plan gets
    # none, a capped plan gets what fits), and every generated row is stored
    # with its explicit search type and origin="generated" so the customer can
    # retype or delete it. ensure_base_prompts never raises: a project is still
    # a project if its base prompts could not be written.
    ensure_base_prompts(db, project=project)

    return _serialize_project(project, user=user, audit_count=0, last_audit_at=None)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    audit_count = (
        db.query(func.count(models.Audit.id))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
        or 0
    )
    last_audit_at = (
        db.query(func.max(models.Audit.created_at))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
    )
    latest_seo_score, latest_geo_score, latest_aeo_score = _load_latest_project_scores(
        db,
        project_id=project.id,
    )
    return _serialize_project(
        project,
        user=user,
        audit_count=int(audit_count),
        last_audit_at=last_audit_at,
        latest_seo_score=latest_seo_score,
        latest_geo_score=latest_geo_score,
        latest_aeo_score=latest_aeo_score,
    )


def _get_project_task_or_404(
    db: Session,
    *,
    project_id: int,
    task_id: int,
) -> models.ProjectTask:
    task = (
        db.query(models.ProjectTask)
        .filter(
            models.ProjectTask.project_id == project_id,
            models.ProjectTask.id == task_id,
        )
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Project task not found.")
    return task


def _validate_project_task_source_audit(
    db: Session,
    *,
    project_id: int,
    source_audit_id: int | None,
) -> int | None:
    if source_audit_id is None:
        return None
    source_audit = (
        db.query(models.Audit.id)
        .filter(
            models.Audit.id == source_audit_id,
            models.Audit.project_id == project_id,
            own_project_audit_clause(),
        )
        .first()
    )
    if source_audit is None:
        raise HTTPException(status_code=400, detail="Source audit must belong to the same project.")
    return source_audit_id


def _validate_project_task_assignee(
    db: Session,
    *,
    workspace_id: int,
    assigned_to_user_id: int | None,
) -> int | None:
    if assigned_to_user_id is None:
        return None
    if not task_assignee_belongs_to_workspace(
        db,
        workspace_id=workspace_id,
        user_id=assigned_to_user_id,
    ):
        raise HTTPException(status_code=400, detail="Assignee must belong to the same workspace.")
    return assigned_to_user_id


@router.get(
    "/projects/{project_id}/tasks",
    response_model=ProjectTaskBoardResponse,
)
def list_project_tasks(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=True,
    )
    tasks = sync_project_tasks(db, project_id=project.id)
    return _serialize_project_task_board(
        db,
        project=project,
        workspace=workspace,
        role=role,
        tasks=tasks,
    )


@router.post(
    "/projects/{project_id}/tasks",
    response_model=ProjectTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_task(
    project_id: int,
    payload: ProjectTaskCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    existing_tasks = sync_project_tasks(db, project_id=project.id)
    source_audit_id = _validate_project_task_source_audit(
        db,
        project_id=project.id,
        source_audit_id=payload.source_audit_id,
    )
    assigned_to_user_id = _validate_project_task_assignee(
        db,
        workspace_id=workspace.id,
        assigned_to_user_id=payload.assigned_to_user_id,
    )

    status_enum = models.ProjectTaskStatus(payload.status)
    # Provenance is server-derived: the key is accepted only when the source
    # audit's own recommendation candidates verify it (client-supplied keys
    # alone cannot mark a task as audit_recommendation).
    source_recommendation_key = resolve_task_recommendation_key(
        db,
        project_id=project.id,
        source_audit_id=source_audit_id,
        title=payload.title,
        client_key=payload.source_recommendation_key,
    )
    task = models.ProjectTask(
        project_id=project.id,
        source_audit_id=source_audit_id,
        assigned_to_user_id=assigned_to_user_id,
        created_by_user_id=user.id,
        title=payload.title,
        description=payload.description,
        status=status_enum,
        priority=models.ProjectTaskPriority(payload.priority),
        origin=(
            models.ProjectTaskOrigin.AUDIT_RECOMMENDATION
            if source_recommendation_key
            else models.ProjectTaskOrigin.MANUAL
        ),
        category=payload.category,
        source_recommendation_key=source_recommendation_key,
        due_date=payload.due_date,
        sort_order=(
            max(
                [
                    int(existing.sort_order or 0)
                    for existing in existing_tasks
                    if (
                        existing.status.value
                        if isinstance(existing.status, models.ProjectTaskStatus)
                        else str(existing.status)
                    )
                    == payload.status
                ],
                default=0,
            )
            + 100
        ),
        schema_version="1",
        metadata_json={},
    )
    if status_enum == models.ProjectTaskStatus.DONE:
        now = datetime.now(timezone.utc)
        task.resolved_at = now
        task.resolution_source = models.ProjectTaskResolutionSource.MANUAL

    db.add(task)
    db.commit()
    db.refresh(task)

    member_directory = _workspace_member_directory(db, workspace=workspace)
    return _serialize_project_task(task, member_directory=member_directory)


@router.patch(
    "/projects/{project_id}/tasks/reorder",
    response_model=ProjectTaskBoardResponse,
)
def reorder_project_tasks(
    project_id: int,
    payload: ProjectTaskReorderRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    task_ids = [task_id for column in payload.columns for task_id in column.task_ids]
    if len(task_ids) != len(set(task_ids)):
        raise HTTPException(
            status_code=400, detail="Duplicate task ids are not allowed in reorder payload."
        )

    tasks_by_id = {
        task.id: task
        for task in db.query(models.ProjectTask)
        .filter(
            models.ProjectTask.project_id == project.id,
            models.ProjectTask.id.in_(task_ids or [-1]),
        )
        .all()
    }
    if task_ids and len(tasks_by_id) != len(task_ids):
        raise HTTPException(
            status_code=400, detail="Reorder payload contains unknown project tasks."
        )

    for column in payload.columns:
        status_enum = models.ProjectTaskStatus(column.status)
        for index, task_id in enumerate(column.task_ids, start=1):
            task = tasks_by_id[task_id]
            task.status = status_enum
            task.sort_order = index * 100
            if status_enum == models.ProjectTaskStatus.DONE:
                task.resolved_at = task.resolved_at or datetime.now(timezone.utc)
                task.resolution_source = (
                    task.resolution_source or models.ProjectTaskResolutionSource.MANUAL
                )
            else:
                task.resolved_at = None
                task.verified_at = None
                task.verification_audit_id = None
                task.resolution_source = None
            db.add(task)

    db.commit()
    tasks = sync_project_tasks(db, project_id=project.id)
    return _serialize_project_task_board(
        db,
        project=project,
        workspace=workspace,
        role=role,
        tasks=tasks,
    )


@router.get(
    "/projects/{project_id}/tasks/impact",
    response_model=ProjectTaskImpactResponse,
)
def get_project_task_impact(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=True,
    )
    return build_project_task_impact_payload(db, project_id=project.id)


@router.put(
    "/projects/{project_id}/tasks/{task_id}",
    response_model=ProjectTaskResponse,
)
def update_project_task(
    project_id: int,
    task_id: int,
    payload: ProjectTaskUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    task = _get_project_task_or_404(db, project_id=project.id, task_id=task_id)
    field_set = payload.model_fields_set

    if "source_audit_id" in field_set:
        task.source_audit_id = _validate_project_task_source_audit(
            db,
            project_id=project.id,
            source_audit_id=payload.source_audit_id,
        )
    if "assigned_to_user_id" in field_set:
        task.assigned_to_user_id = _validate_project_task_assignee(
            db,
            workspace_id=workspace.id,
            assigned_to_user_id=payload.assigned_to_user_id,
        )
    if "title" in field_set and payload.title is not None:
        task.title = payload.title
    if "description" in field_set:
        task.description = payload.description
    if "priority" in field_set and payload.priority is not None:
        task.priority = models.ProjectTaskPriority(payload.priority)
    if "category" in field_set and payload.category is not None:
        task.category = payload.category
    if "due_date" in field_set:
        task.due_date = payload.due_date
    if "source_recommendation_key" in field_set:
        task.source_recommendation_key = payload.source_recommendation_key
        task.origin = (
            models.ProjectTaskOrigin.AUDIT_RECOMMENDATION
            if payload.source_recommendation_key
            else models.ProjectTaskOrigin.MANUAL
        )

    previous_status = (
        task.status.value if isinstance(task.status, models.ProjectTaskStatus) else str(task.status)
    )
    if "status" in field_set and payload.status is not None:
        next_status = models.ProjectTaskStatus(payload.status)
        if next_status.value != previous_status:
            task.status = next_status
            sibling_max = (
                db.query(func.max(models.ProjectTask.sort_order))
                .filter(
                    models.ProjectTask.project_id == project.id,
                    models.ProjectTask.status == next_status,
                    models.ProjectTask.id != task.id,
                )
                .scalar()
            ) or 0
            task.sort_order = int(sibling_max) + 100

        if next_status == models.ProjectTaskStatus.DONE:
            if task.resolved_at is None:
                task.resolved_at = datetime.now(timezone.utc)
            if task.resolution_source is None:
                task.resolution_source = models.ProjectTaskResolutionSource.MANUAL
        else:
            task.resolved_at = None
            task.verified_at = None
            task.verification_audit_id = None
            task.resolution_source = None

    db.add(task)
    db.commit()
    db.refresh(task)

    member_directory = _workspace_member_directory(db, workspace=workspace)
    return _serialize_project_task(task, member_directory=member_directory)


@router.delete(
    "/projects/{project_id}/tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_task(
    project_id: int,
    task_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    task = _get_project_task_or_404(db, project_id=project.id, task_id=task_id)
    db.delete(task)
    db.commit()
    return None


@router.get(
    "/projects/{project_id}/competitors",
    response_model=list[ProjectCompetitorListItemResponse],
)
def get_project_competitors(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return list_project_competitors(db, project=project)


@router.post(
    "/projects/{project_id}/competitors",
    response_model=ProjectCompetitorListItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_competitor(
    project_id: int,
    payload: ProjectCompetitorCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    try:
        competitor = add_project_competitor(
            db,
            project=project,
            target_url=payload.target_url,
            display_name=payload.display_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    rows = list_project_competitors(db, project=project)
    return next(row for row in rows if int(row["id"]) == competitor.id)


@router.delete(
    "/projects/{project_id}/competitors/{competitor_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_competitor(
    project_id: int,
    competitor_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    try:
        delete_project_competitor(db, project=project, competitor_id=competitor_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return None


_BRAND_FACTS_PLAN_DETAIL = "Brand integrity guardrails are available on Executive."


@router.get(
    "/projects/{project_id}/brand-facts",
    response_model=list[ProjectBrandFactResponse],
)
def get_project_brand_facts(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_brand_integrity_guardrails",
        detail=_BRAND_FACTS_PLAN_DETAIL,
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return list_brand_facts(db, project_id=project.id)


_ADVISOR_PLAN_PROGRESS_PLAN_DETAIL = (
    "Advisor-plan progress (continuous management) is available on Executive."
)


@router.get(
    "/projects/{project_id}/advisor-plan-progress",
    response_model=AdvisorPlanProgressResponse,
)
def get_project_advisor_plan_progress(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Read-only Advisor-plan progress / delta over time for a project (Executive).

    Gated on ``has_done_for_you_execution`` (402 if absent), then tenant-scoped
    via ``_resolve_project_access`` (403/404). Purely derives progress from the
    persisted per-audit Advisor-plan snapshots — no recomputation, no
    auto-execution, no mutation of the canonical contract.
    """
    _require_plan_feature(
        user,
        feature_key="has_done_for_you_execution",
        detail=_ADVISOR_PLAN_PROGRESS_PLAN_DETAIL,
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    snapshots = list_snapshots(db, project.id)
    return build_plan_progress(snapshots)


@router.post(
    "/projects/{project_id}/brand-facts",
    response_model=ProjectBrandFactResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_brand_fact(
    project_id: int,
    payload: ProjectBrandFactCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_brand_integrity_guardrails",
        detail=_BRAND_FACTS_PLAN_DETAIL,
    )
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    try:
        fact = create_brand_fact(
            db,
            project_id=project.id,
            kind=payload.kind,
            statement=payload.statement,
            is_forbidden=payload.is_forbidden,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return fact


@router.delete(
    "/projects/{project_id}/brand-facts/{fact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_project_brand_fact(
    project_id: int,
    fact_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_brand_integrity_guardrails",
        detail=_BRAND_FACTS_PLAN_DETAIL,
    )
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    try:
        delete_brand_fact(db, project_id=project.id, fact_id=fact_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    db.commit()
    return None


@router.get(
    "/projects/{project_id}/recommendation-decisions",
    response_model=list[RecommendationDecisionResponse],
)
def get_project_recommendation_decisions(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return list_decisions(db, project_id=project.id)


@router.post(
    "/projects/{project_id}/recommendation-decisions",
    response_model=RecommendationDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_recommendation_decision(
    project_id: int,
    payload: RecommendationDecisionCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    # Key precedence: an explicit fingerprint wins (unchanged contract), then
    # the deterministic problem code, then the action-text digest. The code key
    # is what makes the dismissal outlive the next audit's rewording; the digest
    # remains the key for LLM-only advice, and reads match either form.
    fingerprint = str(payload.action_fingerprint or "").strip()
    if not fingerprint:
        fingerprint = decision_key(payload.action_text, payload.problem_code)

    # Readable label for the Learnings view: explicit override wins, otherwise
    # derive it from the raw action_text. The service RAW-sanitizes it (no
    # HTML-escaping — React escapes at render). Fingerprint logic is unchanged.
    label_source = payload.action_label if payload.action_label is not None else payload.action_text

    try:
        decision = record_decision(
            db,
            project_id=project.id,
            action_fingerprint=fingerprint,
            decision=payload.decision,
            decided_by=user.id,
            note=payload.note,
            action_label=label_source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return decision


@router.get(
    "/projects/{project_id}/competitive-analysis",
    response_model=CompetitiveAnalysisResponse,
)
def get_project_competitive_analysis(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return build_project_competitive_analysis(db, project=project)


@router.get(
    "/projects/{project_id}/competitive-analysis/trends",
    response_model=CompetitiveTrendResponse,
)
def get_project_competitive_trends(
    project_id: int,
    period: Literal["30d", "90d", "1y", "all"] = Query("90d"),
    metric: Literal["geo", "seo", "aeo", "overall"] = Query("overall"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return build_project_competitive_trends(db, project=project, period=period, metric=metric)


@router.get(
    "/projects/{project_id}/competitive-analysis/gaps",
    response_model=CompetitiveGapResponse,
)
def get_project_competitive_gaps(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    return build_project_competitive_gaps(db, project=project)


@router.post(
    "/projects/{project_id}/competitive-analysis/refresh",
    response_model=CompetitiveRefreshResponse,
)
async def refresh_project_competitive_analysis(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    latest_audit = get_latest_project_competitive_source_audit(db, project_id=project.id)
    if latest_audit is None:
        raise HTTPException(
            status_code=400, detail="Run a project audit first to benchmark competitors."
        )
    return await _enqueue_project_competitor_refresh_jobs(
        db=db,
        user=user,
        project=project,
        source_audit=latest_audit,
    )


@router.post(
    "/projects/{project_id}/competitive-analysis/gaps/{competitor_id}/ai-brief",
    response_model=CompetitiveGapBriefResponse,
)
async def generate_project_competitive_gap_brief(
    project_id: int,
    competitor_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_plan_feature(
        user,
        feature_key="has_competitor_analysis",
        detail="Competitive Intelligence is available on Specialist.",
    )
    _require_plan_feature(
        user, feature_key="has_semantic_gap", detail="AI gap briefs are available on Specialist."
    )
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)

    try:
        gap, recommendation_text = build_project_competitive_ai_prompt(
            db,
            project=project,
            competitor_id=competitor_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Internal cost accounting only: the charge always books and can go
    # negative, it never blocks the customer action.
    credits_required = PROMPT_RECOMMENDATION_CREDIT_COST
    decrement_credits_atomic(db, user.id, credits_required, allow_negative=True)
    db.commit()

    try:
        prompt_route = resolve_prompt_ai_route()
        content = await prompt_ai_factory.expand_recommendation(
            recommendation_text=recommendation_text,
            site_url=str(project.domain_url or gap["competitor_name"]),
            category="competitive gap",
            project_context={
                "project_name": project.name,
                "domain_url": project.domain_url,
                "competitor_name": gap["competitor_name"],
                "metric": gap["metric"],
                "delta": gap["delta"],
                "evidence": gap.get("evidence", []),
            },
            provider=prompt_route.provider,
            tier=prompt_route.execution_tier,
        )
    except Exception as exc:
        try:
            increment_credits_atomic(
                db,
                user.id,
                credits_required,
                reverse_commitment_usage=True,
            )
            db.commit()
        except Exception:
            db.rollback()
        raise HTTPException(status_code=502, detail=f"prompt.AI generation failed: {exc}") from exc

    return CompetitiveGapBriefResponse(
        competitor_id=competitor_id,
        competitor_name=str(gap["competitor_name"]),
        content=content,
    )


@router.get(
    "/projects/{project_id}/trends",
    response_model=ProjectTrendResponse,
)
def get_project_trends(
    project_id: int,
    period: Literal["7d", "30d", "90d", "1y", "all"] = Query("90d"),
    granularity: Literal["daily", "weekly", "monthly"] | None = Query(None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    try:
        return build_project_trend_payload(
            db,
            project_id=project.id,
            period=period,
            granularity=granularity or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/trends/comparison",
    response_model=ProjectTrendComparisonResponse,
)
def get_project_trend_comparison(
    project_id: int,
    period: Literal["30d", "90d", "1y"] = Query("30d"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    try:
        return build_project_period_comparison(
            db,
            project_id=project.id,
            period=period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/workspaces/{workspace_id}/trends/overview",
    response_model=WorkspaceTrendOverviewResponse,
)
def get_workspace_trends_overview(
    workspace_id: int,
    period: Literal["7d", "30d", "90d", "1y", "all"] = Query("90d"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace, _role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
    try:
        return build_workspace_trends_overview(
            db,
            workspace_id=workspace.id,
            period=period,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/reports",
    response_model=list[ProjectProgressReportListItemResponse],
)
def list_project_progress_reports(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    retention_days = get_report_retention_days(db)
    reports = (
        db.query(models.ProjectProgressReport)
        .filter(models.ProjectProgressReport.project_id == project.id)
        .order_by(
            models.ProjectProgressReport.report_month.desc(),
            models.ProjectProgressReport.id.desc(),
        )
        .all()
    )
    now = datetime.now(timezone.utc)
    return [
        _serialize_project_progress_report(report, retention_days=retention_days, now=now)
        for report in reports
    ]


@router.get(
    "/projects/{project_id}/reports/{report_id}",
    response_model=ProjectProgressReportListItemResponse,
)
def get_project_progress_report(
    project_id: int,
    report_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    retention_days = get_report_retention_days(db)
    report = (
        db.query(models.ProjectProgressReport)
        .filter(
            models.ProjectProgressReport.id == report_id,
            models.ProjectProgressReport.project_id == project.id,
        )
        .first()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="Project progress report not found.")
    return _serialize_project_progress_report(
        report,
        retention_days=retention_days,
        now=datetime.now(timezone.utc),
    )


@router.get(
    "/audits/{audit_id}/annotations",
    response_model=AnnotationThreadPageResponse,
)
def list_audit_annotations(
    audit_id: int,
    visibility: str | None = Query(default=None),
    section_path: str | None = Query(default=None, max_length=255),
    source_recommendation_key: str | None = Query(default=None, max_length=255),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, role = _resolve_audit_access(db, user=user, audit_id=audit_id)
    visibility = _query_value(visibility)
    section_path = _query_value(section_path)
    source_recommendation_key = _query_value(source_recommendation_key)
    page = _query_value(page)
    per_page = _query_value(per_page)
    visibility_enum = None
    if visibility is not None and str(visibility).strip():
        try:
            visibility_enum = models.AnnotationVisibility(str(visibility).strip())
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="Unsupported annotation visibility."
            ) from exc
    return list_annotations(
        db,
        audit_id=audit.id,
        user=user,
        role=role,
        visibility=visibility_enum,
        section_path=(str(section_path or "").strip() or None),
        source_recommendation_key=(str(source_recommendation_key or "").strip() or None),
        page=page,
        per_page=per_page,
    )


@router.post(
    "/audits/{audit_id}/annotations",
    response_model=AnnotationResponse,
)
def create_audit_annotation(
    audit_id: int,
    payload: AnnotationCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, project, _workspace, role = _resolve_audit_access(db, user=user, audit_id=audit_id)
    if not annotation_write_allowed(role):
        raise HTTPException(status_code=403, detail="Workspace write access required.")

    annotation = create_annotation(
        db,
        audit=audit,
        project=project,
        user=user,
        role=role,
        content=payload.content,
        visibility=payload.visibility,
        parent_id=payload.parent_id,
        section_path=payload.section_path,
        source_recommendation_key=payload.source_recommendation_key,
        portal_mode=False,
    )
    queue_annotation_notifications(db, project=project, audit=audit, annotation=annotation)
    db.commit()
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation.id)
    return build_annotation_response(annotation, user=user, role=role)


@router.put(
    "/audits/{audit_id}/annotations/{annotation_id}",
    response_model=AnnotationResponse,
)
def update_audit_annotation(
    audit_id: int,
    annotation_id: int,
    payload: AnnotationUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, role = _resolve_audit_access(db, user=user, audit_id=audit_id)
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation_id)
    annotation = update_annotation(
        db,
        annotation=annotation,
        user=user,
        role=role,
        content=payload.content,
        visibility=payload.visibility,
    )
    db.commit()
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation.id)
    return build_annotation_response(annotation, user=user, role=role)


@router.delete(
    "/audits/{audit_id}/annotations/{annotation_id}",
    response_model=AnnotationResponse,
)
def remove_audit_annotation(
    audit_id: int,
    annotation_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, role = _resolve_audit_access(db, user=user, audit_id=audit_id)
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation_id)
    annotation = delete_annotation(
        db,
        annotation=annotation,
        user=user,
        role=role,
    )
    db.commit()
    annotation = get_annotation_or_404(db, audit_id=audit.id, annotation_id=annotation.id)
    return build_annotation_response(annotation, user=user, role=role)


@router.get(
    "/audits/{audit_id}/review-queue",
    response_model=ClaimReviewQueueResponse,
)
def get_audit_claim_review_queue(
    audit_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, role = _resolve_audit_access(
        db,
        user=user,
        audit_id=audit_id,
        allow_client_readonly=True,
    )
    return claim_review_service.get_review_queue(
        db=db,
        audit=audit,
        can_review=role
        in {
            models.WorkspaceRole.ADMIN.value,
            models.WorkspaceRole.EDITOR.value,
        },
    )


@router.post(
    "/audits/{audit_id}/claims/{claim_id}/review",
    response_model=ClaimReviewDecisionResponse,
)
def submit_audit_claim_review(
    audit_id: int,
    claim_id: str,
    payload: ClaimReviewRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, role = _resolve_audit_access(
        db,
        user=user,
        audit_id=audit_id,
        allow_client_readonly=False,
    )
    _require_workspace_write_access(role)
    decision = claim_review_service.submit_review(
        db=db,
        audit=audit,
        claim_id=str(claim_id or "").strip(),
        disposition=payload.disposition,
        note=payload.note,
        reviewer=user,
    )
    db.commit()
    return decision


@router.get(
    "/audits/{audit_id}/review-summary",
    response_model=ClaimReviewSummaryResponse,
)
def get_audit_claim_review_summary(
    audit_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audit, _project, _workspace, _role = _resolve_audit_access(
        db,
        user=user,
        audit_id=audit_id,
        allow_client_readonly=True,
    )
    return claim_review_service.get_review_summary(db=db, audit=audit)


@router.post(
    "/projects/{project_id}/reports/generate",
    response_model=ProjectProgressReportListItemResponse,
)
def create_project_progress_report(
    project_id: int,
    payload: ProjectProgressReportRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    try:
        report = generate_project_progress_report(
            db,
            project_id=project.id,
            report_month=payload.report_month,
            generated_by="manual",
            deliver_email=payload.deliver_email,
            frontend_base_url=_resolve_frontend_base_url(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    db.commit()
    db.refresh(report)
    return _serialize_project_progress_report(
        report,
        retention_days=get_report_retention_days(db),
        now=datetime.now(timezone.utc),
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/budget",
    response_model=ProjectBudgetResponse,
)
def get_project_budget(
    workspace_id: int,
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    if workspace.id != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found in the target workspace.")
    return _serialize_project_budget_response(db, project=project)


@router.put(
    "/workspaces/{workspace_id}/projects/{project_id}/budget",
    response_model=ProjectBudgetResponse,
)
def put_project_budget(
    workspace_id: int,
    project_id: int,
    payload: ProjectBudgetUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    if workspace.id != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found in the target workspace.")
    _require_workspace_write_access(role)
    upsert_project_budget(
        db,
        project_id=project.id,
        monthly_limit_scans=payload.monthly_limit_scans,
        cycle_anchor_day=payload.cycle_anchor_day,
    )
    db.commit()
    return _serialize_project_budget_response(db, project=project)


@router.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/budget",
    response_model=ProjectBudgetResponse,
)
def remove_project_budget(
    workspace_id: int,
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    if workspace.id != workspace_id:
        raise HTTPException(status_code=404, detail="Project not found in the target workspace.")
    _require_workspace_write_access(role)
    delete_project_budget(db, project_id=project.id)
    db.commit()
    return _serialize_project_budget_response(db, project=project)


@router.get(
    "/projects/{project_id}/audits",
    response_model=list[ProjectAuditHistoryEntryResponse],
)
def list_project_audits(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(25, ge=1, le=100),
    include_full_report: bool = Query(False),
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP"] | None = Query(None),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    audits_query = db.query(models.Audit).filter(
        models.Audit.project_id == project.id, own_project_audit_clause()
    )
    if audit_type:
        audits_query = audits_query.filter(models.Audit.audit_type == models.AuditType(audit_type))

    audits = (
        audits_query.order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .limit(limit)
        .all()
    )

    # One measurement read for the whole response: every audit here belongs to
    # the same project, so the per-search-type figures are identical (SIGV2-1182).
    search_type_measurements = (
        compute_search_type_measurements(db, project.id) if include_full_report else None
    )
    return [
        _serialize_project_audit_entry(
            audit,
            db=db,
            include_full_report=include_full_report,
            search_type_measurements=search_type_measurements,
        )
        for audit in audits
    ]


@router.get(
    "/projects/{project_id}/audits/latest",
    response_model=ProjectAuditHistoryEntryResponse | None,
)
def get_project_latest_audit(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_full_report: bool = Query(True),
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP"] | None = Query(None),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    latest_audit_query = db.query(models.Audit).filter(
        models.Audit.project_id == project.id, own_project_audit_clause()
    )
    if audit_type:
        latest_audit_query = latest_audit_query.filter(
            models.Audit.audit_type == models.AuditType(audit_type)
        )

    latest_audit = latest_audit_query.order_by(
        models.Audit.created_at.desc(),
        models.Audit.id.desc(),
    ).first()
    if latest_audit is None:
        return None

    return _serialize_project_audit_entry(
        latest_audit,
        db=db,
        include_full_report=include_full_report,
        # The project overview's search-type cards are rendered from this
        # response; without the measurements they say "No prompt data yet"
        # whatever the project's prompts measured (SIGV2-1182).
        search_type_measurements=(
            compute_search_type_measurements(db, project.id) if include_full_report else None
        ),
    )


@router.get(
    "/projects/{project_id}/audits/latest-selection",
    response_model=ProjectLatestAuditSelectionResponse,
)
def get_project_latest_audit_selection(
    project_id: int,
    module: Literal["seo", "aeo", "geo"] = Query(...),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
    include_full_report: bool = Query(True),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    selection = select_project_module_audit(
        db,
        project_id=project.id,
        module=module,
    )
    # Same project for both serialized audits, so one read (SIGV2-1182).
    search_type_measurements = (
        compute_search_type_measurements(db, project.id) if include_full_report else None
    )
    return ProjectLatestAuditSelectionResponse(
        module=selection.module,
        status=selection.status,
        message=selection.message,
        recommended_audit_type=selection.recommended_audit_type,
        recommended_launch_tier=selection.recommended_launch_tier,
        compatible_audit_types=list(selection.compatible_audit_types),
        stale_after_days=selection.stale_after_days,
        selected_audit_age_days=selection.selected_audit_age_days,
        selected_audit=(
            ProjectAuditHistoryEntryResponse.model_validate(
                _serialize_project_audit_entry(
                    selection.selected_audit,
                    db=db,
                    include_full_report=include_full_report,
                    search_type_measurements=search_type_measurements,
                )
            )
            if selection.selected_audit is not None
            else None
        ),
        latest_audit=(
            ProjectAuditHistoryEntryResponse.model_validate(
                _serialize_project_audit_entry(
                    selection.latest_audit,
                    db=db,
                    include_full_report=False,
                )
            )
            if selection.latest_audit is not None
            else None
        ),
    )


@router.get(
    "/aeo/query-tracker",
    response_model=AeoQueryTrackerResponse,
)
def get_aeo_query_tracker(
    context_url: str | None = Query(None, max_length=1000),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context_key = _normalize_tracker_context_key(context_url)
    rows = (
        db.query(models.AeoQueryTrackerEntry)
        .filter(
            models.AeoQueryTrackerEntry.user_id == user.id,
            models.AeoQueryTrackerEntry.context_key == context_key,
        )
        .order_by(
            models.AeoQueryTrackerEntry.tracked_at.desc(), models.AeoQueryTrackerEntry.id.desc()
        )
        .all()
    )
    return {
        "context_key": context_key,
        "items": [_serialize_aeo_query_tracker_entry(row) for row in rows],
    }


@router.put(
    "/aeo/query-tracker",
    response_model=AeoQueryTrackerResponse,
)
def upsert_aeo_query_tracker(
    payload: AeoQueryTrackerUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context_key = _normalize_tracker_context_key(payload.context_url)

    deduped_items: list[AeoQueryTrackerItemPayload] = []
    seen: set[str] = set()
    for item in payload.items[:200]:
        normalized_query = item.query.strip()
        query_key = normalized_query.lower()
        if not normalized_query or query_key in seen:
            continue
        seen.add(query_key)
        deduped_items.append(
            AeoQueryTrackerItemPayload(
                query=normalized_query,
                tracked_at=item.tracked_at,
                citation_hits=max(0, int(item.citation_hits or 0)),
            )
        )

    (
        db.query(models.AeoQueryTrackerEntry)
        .filter(
            models.AeoQueryTrackerEntry.user_id == user.id,
            models.AeoQueryTrackerEntry.context_key == context_key,
        )
        .delete(synchronize_session=False)
    )

    for item in deduped_items:
        db.add(
            models.AeoQueryTrackerEntry(
                user_id=user.id,
                context_key=context_key,
                query=item.query,
                tracked_at=_as_utc_datetime(item.tracked_at) or datetime.now(timezone.utc),
                citation_hits=max(0, int(item.citation_hits or 0)),
            )
        )

    db.commit()

    rows = (
        db.query(models.AeoQueryTrackerEntry)
        .filter(
            models.AeoQueryTrackerEntry.user_id == user.id,
            models.AeoQueryTrackerEntry.context_key == context_key,
        )
        .order_by(
            models.AeoQueryTrackerEntry.tracked_at.desc(), models.AeoQueryTrackerEntry.id.desc()
        )
        .all()
    )
    return {
        "context_key": context_key,
        "items": [_serialize_aeo_query_tracker_entry(row) for row in rows],
    }


@router.get(
    "/geo/prompt-tracker",
    response_model=GeoPromptTrackerResponse,
)
def get_geo_prompt_tracker(
    context_url: str | None = Query(None, max_length=1000),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context_key = _normalize_tracker_context_key(context_url)
    rows = (
        db.query(models.GeoPromptTrackerEntry)
        .filter(
            models.GeoPromptTrackerEntry.user_id == user.id,
            models.GeoPromptTrackerEntry.context_key == context_key,
        )
        .order_by(
            models.GeoPromptTrackerEntry.tracked_at.desc(), models.GeoPromptTrackerEntry.id.desc()
        )
        .all()
    )
    return {
        "context_key": context_key,
        "items": [_serialize_geo_prompt_tracker_entry(row) for row in rows],
    }


@router.put(
    "/geo/prompt-tracker",
    response_model=GeoPromptTrackerResponse,
)
def upsert_geo_prompt_tracker(
    payload: GeoPromptTrackerUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    context_key = _normalize_tracker_context_key(payload.context_url)

    deduped_items: list[GeoPromptTrackerItemPayload] = []
    seen: set[str] = set()
    for item in payload.items[:200]:
        normalized_prompt = item.prompt.strip()
        prompt_key = normalized_prompt.lower()
        if not normalized_prompt or prompt_key in seen:
            continue
        seen.add(prompt_key)
        deduped_items.append(
            GeoPromptTrackerItemPayload(
                prompt=normalized_prompt,
                tracked_at=item.tracked_at,
                citation_hits=max(0, int(item.citation_hits or 0)),
            )
        )

    (
        db.query(models.GeoPromptTrackerEntry)
        .filter(
            models.GeoPromptTrackerEntry.user_id == user.id,
            models.GeoPromptTrackerEntry.context_key == context_key,
        )
        .delete(synchronize_session=False)
    )

    for item in deduped_items:
        db.add(
            models.GeoPromptTrackerEntry(
                user_id=user.id,
                context_key=context_key,
                prompt=item.prompt,
                tracked_at=_as_utc_datetime(item.tracked_at) or datetime.now(timezone.utc),
                citation_hits=max(0, int(item.citation_hits or 0)),
            )
        )

    db.commit()

    rows = (
        db.query(models.GeoPromptTrackerEntry)
        .filter(
            models.GeoPromptTrackerEntry.user_id == user.id,
            models.GeoPromptTrackerEntry.context_key == context_key,
        )
        .order_by(
            models.GeoPromptTrackerEntry.tracked_at.desc(), models.GeoPromptTrackerEntry.id.desc()
        )
        .all()
    )
    return {
        "context_key": context_key,
        "items": [_serialize_geo_prompt_tracker_entry(row) for row in rows],
    }


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    updates = payload.model_dump(exclude_unset=True)
    _require_competitive_settings_plan(user, updates)

    if "competitors" in updates:
        replace_project_competitors_from_urls(
            db,
            project=project,
            competitors=list(updates.pop("competitors") or []),
        )
    if (
        "competitive_digest_frequency" in updates
        and updates["competitive_digest_frequency"] is not None
    ):
        updates["competitive_digest_frequency"] = models.CompetitiveDigestFrequency(
            updates["competitive_digest_frequency"]
        )
    for field_name, value in updates.items():
        setattr(project, field_name, value)

    db.commit()
    db.refresh(project)

    audit_count = (
        db.query(func.count(models.Audit.id))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
        or 0
    )
    last_audit_at = (
        db.query(func.max(models.Audit.created_at))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
    )
    latest_seo_score, latest_geo_score, latest_aeo_score = _load_latest_project_scores(
        db,
        project_id=project.id,
    )
    return _serialize_project(
        project,
        user=user,
        audit_count=int(audit_count),
        last_audit_at=last_audit_at,
        latest_seo_score=latest_seo_score,
        latest_geo_score=latest_geo_score,
        latest_aeo_score=latest_aeo_score,
    )


@router.post(
    "/projects/{project_id}/generate-smart-profile",
    response_model=ProjectSmartProfileGenerateResponse,
)
def generate_project_smart_profile(
    project_id: int,
    payload: ProjectSmartProfileGenerateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    missing_required_fields = _missing_smart_profile_required_fields(project)
    required_fields = [label for _, label in SMART_PROFILE_REQUIRED_FIELDS]
    if missing_required_fields:
        raise HTTPException(
            status_code=400,
            detail=(
                "Missing required fields for grounded AI generation: "
                + ", ".join(missing_required_fields)
            ),
        )

    evidence, grounded_sources = _build_grounded_smart_profile_sources(project, db)
    generated_payload = _normalize_generated_smart_profile(
        _generate_smart_profile_via_ai_service(evidence)
    )

    generated_fields: list[str] = []
    skipped_fields: list[str] = []
    unsupported_fields = set(generated_payload.get("unsupported_fields") or [])

    def _apply_generated_value(*, field_name: str, generated_value: Any, has_value: bool) -> None:
        nonlocal generated_fields, skipped_fields
        if not has_value:
            skipped_fields.append(field_name)
            return

        if payload.overwrite_existing:
            setattr(project, field_name, generated_value)
            generated_fields.append(field_name)
            return

        current_value = getattr(project, field_name, None)
        if isinstance(current_value, str):
            is_empty = not current_value.strip()
        elif isinstance(current_value, list):
            is_empty = len(current_value) == 0
        else:
            is_empty = current_value in {None, ""}

        if is_empty:
            setattr(project, field_name, generated_value)
            generated_fields.append(field_name)
        else:
            skipped_fields.append(field_name)

    _apply_generated_value(
        field_name="icp_roles",
        generated_value=generated_payload["icp_roles"],
        has_value=bool(generated_payload["icp_roles"]),
    )
    _apply_generated_value(
        field_name="pain_points",
        generated_value=generated_payload["pain_points"],
        has_value=bool(generated_payload["pain_points"]),
    )
    _apply_generated_value(
        field_name="usp",
        generated_value=generated_payload["usp"],
        has_value=bool(generated_payload["usp"]),
    )
    _apply_generated_value(
        field_name="priority_pulse_tags",
        generated_value=generated_payload["priority_pulse_tags"],
        has_value=bool(generated_payload["priority_pulse_tags"]),
    )
    _apply_generated_value(
        field_name="sme_profiles",
        generated_value=generated_payload["sme_profiles"],
        has_value=bool(generated_payload["sme_profiles"]),
    )

    for unsupported in unsupported_fields:
        if unsupported not in skipped_fields:
            skipped_fields.append(unsupported)

    if not generated_fields:
        audit_count = (
            db.query(func.count(models.Audit.id))
            .filter(models.Audit.project_id == project.id, own_project_audit_clause())
            .scalar()
            or 0
        )
        last_audit_at = (
            db.query(func.max(models.Audit.created_at))
            .filter(models.Audit.project_id == project.id, own_project_audit_clause())
            .scalar()
        )
        latest_seo_score, latest_geo_score, latest_aeo_score = _load_latest_project_scores(
            db,
            project_id=project.id,
        )
        return ProjectSmartProfileGenerateResponse(
            project=ProjectResponse.model_validate(
                _serialize_project(
                    project,
                    user=user,
                    audit_count=int(audit_count),
                    last_audit_at=last_audit_at,
                    latest_seo_score=latest_seo_score,
                    latest_geo_score=latest_geo_score,
                    latest_aeo_score=latest_aeo_score,
                )
            ),
            model=SMART_PROFILE_AI_MODEL,
            required_fields=required_fields,
            missing_required_fields=missing_required_fields,
            generated_fields=generated_fields,
            skipped_fields=sorted(set(skipped_fields)),
            grounded_sources=grounded_sources,
        )

    # Internal soft-limit accounting only (SIGV2-1024): never blocks.
    decrement_credits_atomic(db, user.id, SMART_PROFILE_AI_CREDIT_COST, allow_negative=True)

    db.commit()
    db.refresh(project)
    db.refresh(user)

    audit_count = (
        db.query(func.count(models.Audit.id))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
        or 0
    )
    last_audit_at = (
        db.query(func.max(models.Audit.created_at))
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .scalar()
    )
    latest_seo_score, latest_geo_score, latest_aeo_score = _load_latest_project_scores(
        db,
        project_id=project.id,
    )

    return ProjectSmartProfileGenerateResponse(
        project=ProjectResponse.model_validate(
            _serialize_project(
                project,
                user=user,
                audit_count=int(audit_count),
                last_audit_at=last_audit_at,
                latest_seo_score=latest_seo_score,
                latest_geo_score=latest_geo_score,
                latest_aeo_score=latest_aeo_score,
            )
        ),
        model=SMART_PROFILE_AI_MODEL,
        required_fields=required_fields,
        missing_required_fields=missing_required_fields,
        generated_fields=generated_fields,
        skipped_fields=sorted(set(skipped_fields)),
        grounded_sources=grounded_sources,
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_admin_access(role)

    db.delete(project)
    db.commit()
    return None


@router.get("/workspaces/current/oauth-connections", response_model=list[OAuthConnectionResponse])
def list_workspace_oauth_connections(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)

    rows = (
        db.query(models.OAuthConnection)
        .filter(models.OAuthConnection.workspace_id == workspace.id)
        .order_by(models.OAuthConnection.provider.asc(), models.OAuthConnection.id.desc())
        .all()
    )

    # Also include Jira if connected
    jira_conn = (
        db.query(models.JiraConnection)
        .filter(models.JiraConnection.workspace_id == workspace.id)
        .first()
    )

    connections = [
        OAuthConnectionResponse(
            provider=str(
                row.provider.value
                if isinstance(row.provider, models.OAuthProvider)
                else row.provider
            ),  # type: ignore[arg-type]
            has_refresh_token=bool(row.refresh_token),
            token_type=row.token_type,
            scope=row.scope,
            expires_at=_isoformat(row.expires_at),
            updated_at=_isoformat(row.updated_at),
            access_token_preview=_token_preview(row.access_token),
            connected=True,
            configured=_oauth_provider_configured(
                str(
                    row.provider.value
                    if isinstance(row.provider, models.OAuthProvider)
                    else row.provider
                )
            ),
        )
        for row in rows
    ]

    if jira_conn:
        connections.append(
            OAuthConnectionResponse(
                provider="jira",
                has_refresh_token=bool(jira_conn.refresh_token),
                token_type="Bearer",
                scope="offline_access read:jira-user read:jira-work write:jira-work manage:jira-configuration",
                expires_at=_isoformat(jira_conn.expires_at),
                updated_at=_isoformat(jira_conn.updated_at),
                access_token_preview=_token_preview(jira_conn.access_token),
                site_name=jira_conn.site_name,
                site_url=jira_conn.site_url,
                connected=True,
                configured=_oauth_provider_configured("jira"),
            )
        )

    # Emit a row for every OAuth provider, connected or not, so the UI can tell
    # "not configured in this environment" apart from "not connected" instead
    # of offering a connect affordance that cannot work.
    present = {connection.provider for connection in connections}
    for provider in ("google", "bing", "jira"):
        if provider not in present:
            connections.append(
                OAuthConnectionResponse(
                    provider=provider,  # type: ignore[arg-type]
                    has_refresh_token=False,
                    token_type=None,
                    scope=None,
                    expires_at=None,
                    updated_at=None,
                    access_token_preview=None,
                    connected=False,
                    configured=_oauth_provider_configured(provider),
                )
            )

    return connections


@router.put(
    "/workspaces/current/oauth-connections/{provider}",
    response_model=OAuthConnectionResponse,
)
def upsert_workspace_oauth_connection(
    provider: Literal["google", "bing", "jira"],
    payload: OAuthConnectionUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    if provider == "jira":
        conn = (
            db.query(models.JiraConnection)
            .filter(models.JiraConnection.workspace_id == workspace.id)
            .first()
        )
        if not conn:
            conn = models.JiraConnection(
                workspace_id=workspace.id, access_token=payload.access_token
            )
            db.add(conn)
        else:
            conn.access_token = payload.access_token

        if payload.refresh_token:
            conn.refresh_token = payload.refresh_token
        if payload.expires_at:
            conn.expires_at = payload.expires_at

        db.commit()
        db.refresh(conn)

        return OAuthConnectionResponse(
            provider="jira",
            has_refresh_token=bool(conn.refresh_token),
            token_type="Bearer",
            scope=payload.scope
            or "offline_access read:jira-user read:jira-work write:jira-work manage:jira-configuration",
            expires_at=_isoformat(conn.expires_at),
            updated_at=_isoformat(conn.updated_at),
            access_token_preview=_token_preview(conn.access_token),
            site_name=conn.site_name,
            site_url=conn.site_url,
            connected=True,
            configured=_oauth_provider_configured("jira"),
        )

    provider_enum = models.OAuthProvider(provider)
    row = _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=provider_enum,
        access_token=payload.access_token,
        refresh_token=payload.refresh_token,
        token_type=payload.token_type,
        scope=payload.scope,
        expires_at=payload.expires_at,
    )

    return OAuthConnectionResponse(
        provider=provider,
        has_refresh_token=bool(row.refresh_token),
        token_type=row.token_type,
        scope=row.scope,
        expires_at=_isoformat(row.expires_at),
        updated_at=_isoformat(row.updated_at),
        access_token_preview=_token_preview(row.access_token),
        connected=True,
        configured=_oauth_provider_configured(provider),
    )


@router.get("/workspaces/current/oauth-connections/google/start")
async def start_google_workspace_oauth(
    request: Request,
    workspace_id: int | None = None,
    # SIGV2-1220: onboarding connects GA4 at step 4 and has to come back to the
    # wizard. Only a key from _OAUTH_RETURN_DESTINATIONS is accepted; absent
    # means the Connections Hub, which is every existing caller's behaviour.
    return_to: str | None = None,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    scope = " ".join(
        [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/analytics.readonly",
        ]
    )
    return await _start_workspace_oauth_flow(
        request=request,
        db=db,
        user=user,
        provider="google",
        callback_route_name="workspace_google_oauth_callback",
        authorize_kwargs={
            "scope": scope,
            "access_type": "offline",
            "include_granted_scopes": "true",
            # SIGV2-1202: select_account lets the customer choose which Google
            # account to grant. Without it Google silently reuses whichever
            # account the browser is signed in to, so a customer whose
            # properties live under a second account can never reach it and
            # keeps reconnecting the account that cannot see the property.
            # consent stays alongside it: dropping it loses the refresh token,
            # and a grant without one dies at the first token expiry.
            "prompt": "select_account consent",
        },
        workspace_id=workspace_id,
        return_to=return_to,
    )


@router.get(
    "/workspaces/current/oauth-connections/google/callback",
    name="workspace_google_oauth_callback",
)
async def finish_google_workspace_oauth(
    request: Request,
    db: Session = Depends(get_db),
):
    return await _finish_workspace_oauth_flow(
        request=request,
        db=db,
        provider="google",
    )


@router.get("/workspaces/current/oauth-connections/bing/start")
async def start_bing_workspace_oauth(
    request: Request,
    workspace_id: int | None = None,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.bing_webmaster_service import (
        BING_SCOPE,
        bing_webmaster_oauth_configured,
    )

    if not bing_webmaster_oauth_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Bing Webmaster connection is unavailable: BING_WEBMASTER_CLIENT_ID and "
                "BING_WEBMASTER_CLIENT_SECRET are not configured on this deployment."
            ),
        )
    return await _start_workspace_oauth_flow(
        request=request,
        db=db,
        user=user,
        provider="bing",
        callback_route_name="workspace_bing_oauth_callback",
        authorize_kwargs={"scope": BING_SCOPE},
        client_name="bing_webmaster",
        workspace_id=workspace_id,
    )


@router.get(
    "/workspaces/current/oauth-connections/bing/callback",
    name="workspace_bing_oauth_callback",
)
async def finish_bing_workspace_oauth(
    request: Request,
    db: Session = Depends(get_db),
):
    return await _finish_workspace_oauth_flow(
        request=request,
        db=db,
        provider="bing",
        client_name="bing_webmaster",
    )


@router.get(
    "/projects/{project_id}/data-sources",
    response_model=list[ProjectDataSourceResponse],
)
def list_project_data_sources(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    rows = (
        db.query(models.ProjectDataSource)
        .filter(models.ProjectDataSource.project_id == project.id)
        .order_by(models.ProjectDataSource.id.asc())
        .all()
    )

    rows_by_type: dict[models.ProjectDataSourceType, models.ProjectDataSource] = {}
    for row in rows:
        source_type_enum = (
            row.source_type
            if isinstance(row.source_type, models.ProjectDataSourceType)
            else models.ProjectDataSourceType(str(row.source_type))
        )
        rows_by_type[source_type_enum] = row

    response: list[ProjectDataSourceResponse] = []
    for source_type in models.ProjectDataSourceType:
        provider = _resolve_provider_for_source_type(source_type)
        workspace_provider_connected = _workspace_has_oauth_provider_connection(
            db,
            workspace_id=workspace.id,
            provider=provider,
        )
        response.append(
            _serialize_project_data_source(
                source_type,
                project_id=project.id,
                workspace_provider_connected=workspace_provider_connected,
                row=rows_by_type.get(source_type),
            )
        )
    return response


@router.get(
    "/projects/{project_id}/data-sources/{source_type}/catalog",
    response_model=ProjectDataSourceCatalogResponse,
)
def get_project_data_source_catalog(
    project_id: int,
    source_type: Literal["google_search_console", "google_analytics_4", "bing_webmaster"],
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    source_type_enum = models.ProjectDataSourceType(source_type)
    provider = _resolve_provider_for_source_type(source_type_enum)
    provider_value = provider.value if isinstance(provider, models.OAuthProvider) else str(provider)

    connection = _get_latest_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=provider,
    )
    fetched_at = datetime.now(timezone.utc).isoformat()
    if connection is None:
        return ProjectDataSourceCatalogResponse(
            source_type=source_type,  # type: ignore[arg-type]
            provider=provider_value,  # type: ignore[arg-type]
            workspace_provider_connected=False,
            connected_on_other_workspace=_user_holds_provider_connection_elsewhere(
                db,
                user=user,
                provider=provider,
                workspace_id=workspace.id,
            ),
            items=[],
            required_scopes=[],
            granted_scopes=[],
            missing_scopes=[],
            error="workspace_provider_not_connected",
            fetched_at=fetched_at,
        )

    required_scopes, granted_scopes, missing_scopes = _resolve_scope_requirements(
        source_type_enum,
        connection.scope,
    )
    if missing_scopes:
        return ProjectDataSourceCatalogResponse(
            source_type=source_type,  # type: ignore[arg-type]
            provider=provider_value,  # type: ignore[arg-type]
            workspace_provider_connected=True,
            items=[],
            required_scopes=required_scopes,
            granted_scopes=granted_scopes,
            missing_scopes=missing_scopes,
            error=_build_scope_error_message(missing_scopes),
            fetched_at=fetched_at,
        )

    def _reconnect_required_response() -> ProjectDataSourceCatalogResponse:
        return ProjectDataSourceCatalogResponse(
            source_type=source_type,  # type: ignore[arg-type]
            provider=provider_value,  # type: ignore[arg-type]
            workspace_provider_connected=False,
            items=[],
            required_scopes=required_scopes,
            granted_scopes=granted_scopes,
            missing_scopes=[],
            error="oauth_reconnect_required",
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    # Proactive refresh: when the stored access token has already expired,
    # renew it before the first call so the reactive retry below is a
    # fallback rather than the only mechanism.
    if _workspace_connection_access_token_expired(connection):
        if not str(connection.refresh_token or "").strip():
            logger.warning(
                "Workspace OAuth access token expired with no refresh token "
                "(project_id=%s, source_type=%s)",
                project.id,
                source_type,
            )
            return _reconnect_required_response()
        try:
            connection = _refresh_workspace_oauth_connection(db, connection)
        except Exception as refresh_exc:
            logger.warning(
                "Workspace OAuth token refresh failed (project_id=%s, source_type=%s): %s",
                project.id,
                source_type,
                refresh_exc,
            )
            return _reconnect_required_response()

    try:
        items = _fetch_source_catalog_items(
            source_type=source_type_enum,
            access_token=connection.access_token,
        )
    except Exception as exc:
        retried_with_refresh = False
        if _is_authentication_credential_error(exc):
            if not str(connection.refresh_token or "").strip():
                logger.warning(
                    "Project data source catalog auth failure with no refresh "
                    "token (project_id=%s, source_type=%s): %s",
                    project.id,
                    source_type,
                    exc,
                )
                return _reconnect_required_response()
            try:
                connection = _refresh_workspace_oauth_connection(db, connection)
                items = _fetch_source_catalog_items(
                    source_type=source_type_enum,
                    access_token=connection.access_token,
                )
                retried_with_refresh = True
            except Exception as refresh_exc:
                logger.warning(
                    "Project data source catalog refresh/retry failed "
                    "(project_id=%s, source_type=%s): %s",
                    project.id,
                    source_type,
                    refresh_exc,
                )
                return _reconnect_required_response()

        if retried_with_refresh:
            items = sorted(items, key=lambda item: item.label.lower())
            return ProjectDataSourceCatalogResponse(
                source_type=source_type,  # type: ignore[arg-type]
                provider=provider_value,  # type: ignore[arg-type]
                workspace_provider_connected=True,
                items=items,
                required_scopes=required_scopes,
                granted_scopes=granted_scopes,
                missing_scopes=[],
                error=None,
                fetched_at=datetime.now(timezone.utc).isoformat(),
            )

        logger.warning(
            "Project data source catalog fetch failed (project_id=%s, source_type=%s): %s",
            project.id,
            source_type,
            exc,
        )
        return ProjectDataSourceCatalogResponse(
            source_type=source_type,  # type: ignore[arg-type]
            provider=provider_value,  # type: ignore[arg-type]
            workspace_provider_connected=True,
            items=[],
            required_scopes=required_scopes,
            granted_scopes=granted_scopes,
            missing_scopes=[],
            error=str(exc),
            fetched_at=fetched_at,
        )

    items = sorted(items, key=lambda item: item.label.lower())
    return ProjectDataSourceCatalogResponse(
        source_type=source_type,  # type: ignore[arg-type]
        provider=provider_value,  # type: ignore[arg-type]
        workspace_provider_connected=True,
        items=items,
        required_scopes=required_scopes,
        granted_scopes=granted_scopes,
        missing_scopes=[],
        error=None,
        fetched_at=fetched_at,
    )


@router.put(
    "/projects/{project_id}/data-sources/{source_type}",
    response_model=ProjectDataSourceResponse,
)
def upsert_project_data_source(
    project_id: int,
    source_type: Literal["google_search_console", "google_analytics_4", "bing_webmaster"],
    payload: ProjectDataSourceUpsertRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    source_type_enum = models.ProjectDataSourceType(source_type)
    provider = _resolve_provider_for_source_type(source_type_enum)
    workspace_provider_connected = _workspace_has_oauth_provider_connection(
        db,
        workspace_id=workspace.id,
        provider=provider,
    )

    if (
        payload.binding_mode == models.ProjectDataSourceBindingMode.WORKSPACE.value
        and not workspace_provider_connected
    ):
        raise HTTPException(
            status_code=400,
            detail=f"Workspace connection for provider '{provider.value}' is required before mapping this source.",
        )

    oauth_connection_id: int | None = None
    workspace_connection: models.OAuthConnection | None = None
    if payload.binding_mode == models.ProjectDataSourceBindingMode.WORKSPACE.value:
        workspace_connection = _get_latest_workspace_oauth_connection(
            db,
            workspace_id=workspace.id,
            provider=provider,
        )
        oauth_connection_id = workspace_connection.id if workspace_connection else None
        if workspace_connection is None:
            raise HTTPException(
                status_code=400,
                detail=f"Workspace connection for provider '{provider.value}' is required before mapping this source.",
            )

        _required_scopes, _granted_scopes, missing_scopes = _resolve_scope_requirements(
            source_type_enum,
            workspace_connection.scope,
        )
        if missing_scopes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Workspace connection for provider '{provider.value}' is missing required scopes: "
                    f"{', '.join(missing_scopes)}. Reconnect provider with the required permissions."
                ),
            )

    row = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project.id,
            models.ProjectDataSource.source_type == source_type_enum,
        )
        .first()
    )

    binding_mode_enum = models.ProjectDataSourceBindingMode(payload.binding_mode)
    resolved_source_id = payload.source_id
    if binding_mode_enum == models.ProjectDataSourceBindingMode.AI_ESTIMATE:
        resolved_source_id = None

    if row is None:
        row = models.ProjectDataSource(
            project_id=project.id,
            provider=provider,
            source_type=source_type_enum,
            binding_mode=binding_mode_enum,
            source_id=resolved_source_id,
            source_label=payload.source_label,
            is_active=payload.is_active,
            oauth_connection_id=oauth_connection_id,
            project_oauth_connection_id=None,
            metadata_json={},
        )
        db.add(row)
    else:
        row.provider = provider
        row.binding_mode = binding_mode_enum
        row.source_id = resolved_source_id
        row.source_label = payload.source_label
        row.is_active = payload.is_active
        row.oauth_connection_id = oauth_connection_id
        if binding_mode_enum != models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK:
            row.project_oauth_connection_id = None

    db.commit()
    db.refresh(row)

    return _serialize_project_data_source(
        source_type_enum,
        project_id=project.id,
        workspace_provider_connected=workspace_provider_connected,
        row=row,
    )


@router.delete(
    "/projects/{project_id}/data-sources/{source_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_data_source(
    project_id: int,
    source_type: Literal["google_search_console", "google_analytics_4", "bing_webmaster"],
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    source_type_enum = models.ProjectDataSourceType(source_type)
    row = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project.id,
            models.ProjectDataSource.source_type == source_type_enum,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Project data source mapping not found.")

    db.delete(row)
    db.commit()
    return None


@router.delete(
    "/workspaces/current/oauth-connections/{provider}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_workspace_oauth_connection(
    provider: Literal["google", "bing", "jira"],
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_admin_access(role)

    if provider == "jira":
        conn = (
            db.query(models.JiraConnection)
            .filter(models.JiraConnection.workspace_id == workspace.id)
            .first()
        )
        if not conn:
            raise HTTPException(status_code=404, detail="Jira connection not found.")
        db.delete(conn)
        db.commit()
        return None

    provider_enum = models.OAuthProvider(provider)
    row = (
        db.query(models.OAuthConnection)
        .filter(
            models.OAuthConnection.workspace_id == workspace.id,
            models.OAuthConnection.provider == provider_enum,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="OAuth connection not found.")
    # SIGV2-1202: clear the bindings that depended on this grant in the same
    # transaction as the delete. Without it the FK's SET NULL leaves a binding
    # still naming a live property, and every read reports "revoked" - a
    # customer who has just disconnected is told their access was revoked.
    _invalidate_workspace_provider_bindings(
        db,
        workspace_id=workspace.id,
        provider=provider_enum,
    )
    db.delete(row)
    db.commit()
    return None


@router.post("/projects/{project_id}/magic-link", response_model=MagicLinkResponse)
def create_magic_link(
    project_id: int,
    payload: MagicLinkCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_in_hours)
    token = secrets.token_urlsafe(32)

    link = models.MagicLink(
        project_id=project.id,
        unique_token=token,
        expires_at=expires_at,
        is_used=False,
    )
    db.add(link)
    _log_project_connection_event(
        db,
        project_id=project.id,
        magic_link_id=None,
        provider=None,
        event_type="magic_link_created",
        metadata={"expires_in_hours": payload.expires_in_hours},
    )
    db.commit()
    db.refresh(link)

    frontend_base = _resolve_frontend_base_url()
    encoded_token = quote(token, safe="")
    link_url = f"{frontend_base}/connect/{encoded_token}"

    return MagicLinkResponse(
        project_id=project.id,
        token=token,
        link_url=link_url,
        expires_at=expires_at.isoformat(),
        is_used=bool(link.is_used),
        created_at=_isoformat(link.created_at),
    )


@router.get(
    "/projects/{project_id}/magic-link-status", response_model=ProjectMagicLinkStatusResponse
)
def get_project_magic_link_status(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    latest_link = (
        db.query(models.MagicLink)
        .filter(models.MagicLink.project_id == project.id)
        .order_by(models.MagicLink.created_at.desc(), models.MagicLink.id.desc())
        .first()
    )
    now = datetime.now(timezone.utc)
    open_magic_link_count = (
        db.query(func.count(models.MagicLink.id))
        .filter(
            models.MagicLink.project_id == project.id,
            models.MagicLink.is_used.is_(False),
            models.MagicLink.expires_at > now,
        )
        .scalar()
        or 0
    )
    provider_statuses = _build_project_provider_statuses(
        db,
        project_id=project.id,
        include_private_fields=True,
    )
    has_connected_provider = any(item.connected for item in provider_statuses)

    status: Literal["not_requested", "pending", "expired", "connected"] = "not_requested"
    latest_link_expires_at: datetime | None = None
    latest_link_created_at: datetime | None = None
    latest_link_is_used = False
    if latest_link is not None:
        latest_link_expires_at = _as_utc_datetime(latest_link.expires_at)
        latest_link_created_at = _as_utc_datetime(latest_link.created_at)
        latest_link_is_used = bool(latest_link.is_used)
        is_expired = bool(latest_link_expires_at is not None and latest_link_expires_at <= now)
        if has_connected_provider:
            status = "connected"
        elif latest_link.is_used:
            status = "expired"
        elif is_expired:
            status = "expired"
        else:
            status = "pending"
    elif has_connected_provider:
        status = "connected"

    return ProjectMagicLinkStatusResponse(
        project_id=project.id,
        status=status,
        latest_link_created_at=_isoformat(latest_link_created_at),
        latest_link_expires_at=_isoformat(latest_link_expires_at),
        latest_link_is_used=latest_link_is_used,
        open_magic_link_count=int(open_magic_link_count),
        providers=provider_statuses,
    )


@router.get("/magic-links/{token}/oauth/google/start")
async def start_magic_link_google_oauth(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    scope = " ".join(
        [
            "openid",
            "email",
            "profile",
            "https://www.googleapis.com/auth/webmasters.readonly",
            "https://www.googleapis.com/auth/analytics.readonly",
        ]
    )
    return await _start_magic_link_oauth_flow(
        request=request,
        db=db,
        token=token,
        provider="google",
        callback_route_name="magic_link_google_oauth_callback",
        authorize_kwargs={
            "scope": scope,
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
        },
    )


@router.get(
    "/magic-links/oauth/google/callback",
    name="magic_link_google_oauth_callback",
)
async def finish_magic_link_google_oauth(
    request: Request,
    db: Session = Depends(get_db),
):
    return await _finish_magic_link_oauth_flow(
        request=request,
        db=db,
        provider="google",
    )


@router.get("/magic-links/{token}/oauth/bing/start")
async def start_magic_link_bing_oauth(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
):
    from app.services.bing_webmaster_service import (
        BING_SCOPE,
        bing_webmaster_oauth_configured,
    )

    if not bing_webmaster_oauth_configured():
        return RedirectResponse(
            url=_build_magic_link_return_url(
                token=token,
                provider="bing",
                status="error",
                message="bing_webmaster_not_configured",
            ),
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    return await _start_magic_link_oauth_flow(
        request=request,
        db=db,
        token=token,
        provider="bing",
        callback_route_name="magic_link_bing_oauth_callback",
        authorize_kwargs={"scope": BING_SCOPE},
        client_name="bing_webmaster",
    )


@router.get(
    "/magic-links/oauth/bing/callback",
    name="magic_link_bing_oauth_callback",
)
async def finish_magic_link_bing_oauth(
    request: Request,
    db: Session = Depends(get_db),
):
    return await _finish_magic_link_oauth_flow(
        request=request,
        db=db,
        provider="bing",
        client_name="bing_webmaster",
    )


@router.get("/magic-links/{token}", response_model=MagicLinkPublicResponse)
def get_magic_link_status(token: str, db: Session = Depends(get_db)):
    link, project, is_expired = _resolve_magic_link_with_project(db, token)
    if link is None or project is None:
        return MagicLinkPublicResponse(
            valid=False,
            token=token,
            project_id=None,
            workspace_id=None,
            project_name=None,
            domain_url=None,
            expires_at=None,
            is_used=False,
            connection_state="invalid",
            providers=[],
        )

    provider_statuses = _build_project_provider_statuses(
        db,
        project_id=project.id,
        include_private_fields=False,
    )
    has_connected_provider = bool(
        db.query(models.ProjectOAuthConnection.id)
        .filter(models.ProjectOAuthConnection.magic_link_id == link.id)
        .first()
    )
    connection_state = _resolve_magic_link_connection_state(
        link_exists=True,
        project_exists=True,
        is_expired=is_expired,
        is_used=bool(link.is_used),
        has_provider_connections=has_connected_provider,
    )
    connection_state_literal: Literal["invalid", "pending", "expired", "used", "connected"] = (
        connection_state
        if connection_state in {"invalid", "pending", "expired", "used", "connected"}
        else "invalid"
    )
    valid = bool(connection_state == "pending")

    return MagicLinkPublicResponse(
        valid=valid,
        token=token,
        project_id=project.id,
        workspace_id=project.workspace_id,
        project_name=project.name,
        domain_url=project.domain_url,
        expires_at=_isoformat(_as_utc_datetime(link.expires_at)),
        is_used=bool(link.is_used),
        connection_state=connection_state_literal,
        providers=provider_statuses,
    )


@router.post("/magic-links/{token}/consume", response_model=MagicLinkConsumeResponse)
def consume_magic_link(token: str, db: Session = Depends(get_db)):
    link = db.query(models.MagicLink).filter(models.MagicLink.unique_token == token).first()
    if link is None:
        raise HTTPException(status_code=404, detail="Magic link not found.")

    now = datetime.now(timezone.utc)
    link_expires_at = _as_utc_datetime(link.expires_at)
    if link_expires_at and link_expires_at <= now:
        raise HTTPException(status_code=410, detail="Magic link expired.")

    if not link.is_used:
        link.is_used = True
        link.used_at = now
        _log_project_connection_event(
            db,
            project_id=link.project_id,
            magic_link_id=link.id,
            provider=None,
            event_type="magic_link_consumed_without_oauth",
            metadata={},
        )
        db.commit()
        db.refresh(link)

    return MagicLinkConsumeResponse(
        token=token,
        consumed=bool(link.is_used),
        consumed_at=_isoformat(link.used_at),
    )


# ---------------------------------------------------------------------------
# Project clone & archive
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/clone",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
def clone_project_endpoint(
    project_id: int,
    payload: ProjectCloneRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_manage_access(role)

    cloned = clone_project(
        db, source_project=project, new_name=payload.new_name, workspace_id=_workspace.id
    )
    db.commit()
    db.refresh(cloned)
    return _serialize_project(cloned, user=user, audit_count=0, last_audit_at=None)


@router.post(
    "/projects/{project_id}/archive",
    response_model=ProjectResponse,
)
def archive_project_endpoint(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_manage_access(role)

    archived = archive_project(db, project=project)
    db.commit()
    db.refresh(archived)
    return _serialize_project(archived, user=user, audit_count=0, last_audit_at=None)


@router.post(
    "/projects/{project_id}/unarchive",
    response_model=ProjectResponse,
)
def unarchive_project_endpoint(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_manage_access(role)

    restored = unarchive_project(db, project=project)
    db.commit()
    db.refresh(restored)
    return _serialize_project(restored, user=user, audit_count=0, last_audit_at=None)


# ---------------------------------------------------------------------------
# Client onboarding & bulk invite
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/current/onboard-client",
    response_model=OnboardClientResponse,
    status_code=status.HTTP_201_CREATED,
)
async def onboard_client_endpoint(
    payload: OnboardClientRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    try:
        result = await onboard_client(
            db,
            workspace=workspace,
            project_name=payload.project_name,
            domain_url=payload.domain_url,
            client_email=payload.client_email,
            client_name=payload.client_name,
            invited_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()

    return OnboardClientResponse(
        project_id=result["project"].id,
        user_id=result["user"].id,
        is_new_user=result["is_new_user"],
        workspace_membership_id=result["membership"].id,
    )


@router.post(
    "/workspaces/current/bulk-invite-clients",
    response_model=BulkInviteResponse,
)
async def bulk_invite_clients_endpoint(
    payload: BulkInviteRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    items = [inv.model_dump() for inv in payload.invitations]
    try:
        results = await bulk_invite_clients(
            db,
            workspace=workspace,
            invitations=items,
            invited_by_user_id=user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.commit()

    return BulkInviteResponse(
        results=[BulkInviteResultItem(**r) for r in results],
    )


# ---------------------------------------------------------------------------
# Phase 4: Workspace Intelligence endpoints
# ---------------------------------------------------------------------------


def _serialize_invitation(inv: models.WorkspaceInvitation) -> dict[str, Any]:
    inv_status = getattr(inv, "status", None)
    status_value = (
        inv_status.value
        if isinstance(inv_status, models.InvitationStatus)
        else str(inv_status or "pending")
    )
    inv_role = getattr(inv, "role", None)
    role_value = (
        inv_role.value if isinstance(inv_role, models.WorkspaceRole) else str(inv_role or "viewer")
    )
    return {
        "id": inv.id,
        "workspace_id": inv.workspace_id,
        "invited_email": inv.invited_email,
        "invited_name": inv.invited_name,
        "invited_by_user_id": inv.invited_by_user_id,
        "role": role_value,
        "project_ids": list(inv.project_ids or []),
        "status": status_value,
        "token": inv.token,
        "expires_at": _isoformat(inv.expires_at),
        "accepted_at": _isoformat(inv.accepted_at),
        "created_at": _isoformat(inv.created_at),
    }


@router.get(
    "/workspaces/current/client-health",
    response_model=ClientHealthResponse,
)
def get_client_health_endpoint(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    items = get_client_health(db, workspace_id=workspace.id)
    return ClientHealthResponse(items=[ClientHealthItem(**i) for i in items])


# --- Invitation tracking ---


@router.get(
    "/workspaces/current/invitations",
    response_model=list[InvitationResponse],
)
def list_workspace_invitations(
    status_filter: str | None = Query(None, alias="status"),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    invitations = list_invitations(db, workspace_id=workspace.id, status_filter=status_filter)
    return [_serialize_invitation(inv) for inv in invitations]


@router.post(
    "/workspaces/current/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_invitation(
    payload: InvitationCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    invitation = create_invitation(
        db,
        workspace_id=workspace.id,
        invited_email=payload.email,
        invited_name=payload.name,
        invited_by_user_id=user.id,
        role=payload.role,
        project_ids=payload.project_ids,
    )
    log_workspace_activity(
        db,
        workspace_id=workspace.id,
        actor_user_id=user.id,
        action="member.invited",
        target_type="member",
        metadata={"invited_email": payload.email, "role": payload.role},
    )
    db.commit()
    db.refresh(invitation)
    return _serialize_invitation(invitation)


@router.post(
    "/workspaces/current/invitations/{invitation_id}/resend",
    response_model=InvitationResponse,
)
def resend_workspace_invitation(
    invitation_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    invitation = (
        db.query(models.WorkspaceInvitation)
        .filter(
            models.WorkspaceInvitation.id == invitation_id,
            models.WorkspaceInvitation.workspace_id == workspace.id,
        )
        .first()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    updated = resend_invitation(db, invitation=invitation)
    db.commit()
    db.refresh(updated)
    return _serialize_invitation(updated)


@router.delete(
    "/workspaces/current/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_workspace_invitation(
    invitation_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    invitation = (
        db.query(models.WorkspaceInvitation)
        .filter(
            models.WorkspaceInvitation.id == invitation_id,
            models.WorkspaceInvitation.workspace_id == workspace.id,
        )
        .first()
    )
    if invitation is None:
        raise HTTPException(status_code=404, detail="Invitation not found.")

    revoke_invitation(db, invitation=invitation)
    db.commit()
    return None


# --- Activity log ---


@router.get(
    "/workspaces/current/activity-log",
    response_model=ActivityLogResponse,
)
def get_workspace_activity_log(
    action: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_manage_access(role)

    result = list_workspace_activity(
        db,
        workspace_id=workspace.id,
        action_filter=action,
        page=page,
        page_size=page_size,
    )
    return ActivityLogResponse(
        items=[
            ActivityLogItem(
                id=item.id,
                workspace_id=item.workspace_id,
                actor_user_id=item.actor_user_id,
                action=item.action,
                target_type=item.target_type,
                target_id=item.target_id,
                metadata_json=item.metadata_json,
                created_at=_isoformat(item.created_at),
            )
            for item in result["items"]
        ],
        total=result["total"],
        page=result["page"],
        page_size=result["page_size"],
    )
