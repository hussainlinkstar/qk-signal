from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Annotated, Any, Literal
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy.orm import Session

import models
from auth.credits import calculate_audit_credit_cost
from auth.security import get_current_user_from_token as get_current_user
from core.redis_client import get_async_redis
from database import get_db
from job_models import JOB_STATUS_QUEUED, AuditJobPayload
from services.email_service import EmailService
from services.project_audit_scope import declare_audit_project_scope
from services.embed_service import (
    authenticate_embed_key,
    build_embed_cors_headers,
    enforce_embed_daily_limit,
    generate_embed_api_key_material,
    normalize_allowed_origins,
    origin_allowed,
    resolve_embed_plan,
    serialize_embed_key,
)
from services.sitemap_crawler_service import SitemapCrawlerService
from services.url_validation import normalize_and_validate_url
from services.workspace_rbac import (
    require_not_portal_only,
    require_workspace_write_access,
    resolve_project_access as resolve_project_access_service,
    resolve_workspace_access as resolve_workspace_access_service,
)

router = APIRouter(prefix="/api/v1", tags=["Embed & Sitemap"])

from services.queue_routing import resolve_queue_for_tier

EMBED_AUDIT_PROVIDER = (
    os.getenv("EXTERNAL_API_DEFAULT_PROVIDER") or "google"
).strip().lower() or "google"
EMBED_AUDIT_TIER = "fast"
EMBED_CAPTCHA_SECRET_KEY = (os.getenv("EMBED_CAPTCHA_SECRET_KEY") or "").strip()
EMBED_CAPTCHA_VERIFY_URL = (
    os.getenv("EMBED_CAPTCHA_VERIFY_URL")
    or "https://challenges.cloudflare.com/turnstile/v0/siteverify"
).strip()
EMBED_CAPTCHA_REQUIRED = (os.getenv("EMBED_CAPTCHA_REQUIRED") or "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

sitemap_crawler_service = SitemapCrawlerService()


def _map_job_status(status_value: str | None) -> str:
    normalized = (status_value or "queued").strip().lower()
    if normalized == "succeeded":
        return "completed"
    return normalized


def _serialize_lead(lead: models.Lead) -> dict[str, Any]:
    scores = lead.scores_json if isinstance(lead.scores_json, dict) else {}
    return {
        "id": int(lead.id),
        "workspace_id": int(lead.workspace_id),
        "embed_key_id": int(lead.embed_key_id) if lead.embed_key_id is not None else None,
        "email": lead.email,
        "url": lead.url,
        "entity": lead.entity,
        "audit_job_id": lead.audit_job_id,
        "scores": {
            "geo": scores.get("geo"),
            "seo": scores.get("seo"),
            "aeo": scores.get("aeo"),
        }
        if scores
        else None,
        "source": lead.source,
        "status": lead.status,
        "ip_address": lead.ip_address,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "schema_version": str(lead.schema_version or "1"),
    }


def _workspace_access(
    db: Session,
    *,
    user: models.User,
    workspace_id: int,
    allow_client_readonly: bool = False,
) -> tuple[models.Workspace, str]:
    access = resolve_workspace_access_service(
        db,
        user=user,
        workspace_id=workspace_id,
        allow_client_readonly=allow_client_readonly,
    )
    return access.workspace, access.role


def _project_access(
    db: Session,
    *,
    user: models.User,
    project_id: int,
    allow_client_readonly: bool = False,
) -> tuple[models.Project, models.Workspace, str]:
    access = resolve_project_access_service(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=allow_client_readonly,
    )
    return access.project, access.workspace, access.role


def _enforce_lead_widget_plan_for_workspace(workspace: models.Workspace) -> str:
    owner = workspace.owner
    if owner is None:
        raise HTTPException(status_code=404, detail="Workspace owner not found.")
    return resolve_embed_plan(owner)


def _enforce_lead_widget_plan_for_user(user: models.User) -> str:
    return resolve_embed_plan(user)


def _captcha_is_enforced() -> bool:
    return EMBED_CAPTCHA_REQUIRED or bool(EMBED_CAPTCHA_SECRET_KEY)


async def _verify_embed_captcha(
    *,
    token: str | None,
    remote_ip: str | None,
) -> None:
    if not _captcha_is_enforced():
        return

    if not token:
        raise HTTPException(status_code=400, detail="Captcha verification is required.")

    if not EMBED_CAPTCHA_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Captcha verification is not configured. Please contact support.",
        )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            verify_response = await client.post(
                EMBED_CAPTCHA_VERIFY_URL,
                data={
                    "secret": EMBED_CAPTCHA_SECRET_KEY,
                    "response": token,
                    "remoteip": remote_ip or "",
                },
            )
    except Exception as exc:  # pragma: no cover - defensive network guard
        raise HTTPException(
            status_code=502,
            detail="Captcha verification is temporarily unavailable. Please retry.",
        ) from exc

    if verify_response.status_code >= 500:
        raise HTTPException(
            status_code=502,
            detail="Captcha verification is temporarily unavailable. Please retry.",
        )

    try:
        payload = verify_response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Captcha verification returned an invalid response.",
        ) from exc

    if not bool(payload.get("success")):
        raise HTTPException(status_code=400, detail="Captcha verification failed. Please retry.")


class EmbedAuditCreateRequest(BaseModel):
    audit_target_type: Literal["website", "brand"] = "website"
    url: str | None = None
    email: EmailStr
    entity: str | None = Field(default=None, max_length=255)
    target_name: str | None = Field(default=None, max_length=255)
    captcha_token: str | None = Field(default=None, max_length=2048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        return normalize_and_validate_url(normalized)

    @field_validator("entity", "target_name", "captcha_token")
    @classmethod
    def validate_entity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_target_requirements(self) -> "EmbedAuditCreateRequest":
        if self.audit_target_type == "website" and not self.url:
            raise ValueError("Website audits require a valid URL.")
        if self.audit_target_type == "brand" and not self.resolved_target_name():
            raise ValueError("Brand audits require a target name or entity.")
        return self

    def resolved_target_name(self) -> str | None:
        return (self.target_name or self.entity or "").strip() or None


class EmbedAuditCreateResponse(BaseModel):
    lead_id: int
    job_id: str
    poll_url: str
    estimated_seconds: int


class EmbedAuditStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    scores: dict[str, float | None] | None = None
    error: str | None = None


class EmbedKeyCreateRequest(BaseModel):
    label: str = Field(..., min_length=2, max_length=120)
    allowed_origins: list[str] = Field(..., min_length=1, max_length=25)
    daily_limit: int = Field(default=100, ge=1, le=50000)


class EmbedKeyCreateResponse(BaseModel):
    api_key: str
    item: dict[str, Any]


class EmbedKeyDeleteResponse(BaseModel):
    revoked: bool
    item: dict[str, Any]


class WorkspaceLeadsListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    skip: int
    limit: int


class SitemapCrawlRequest(BaseModel):
    sitemap_url: str

    @field_validator("sitemap_url")
    @classmethod
    def validate_sitemap_url(cls, value: str) -> str:
        return normalize_and_validate_url(value)


class SitemapCrawlEstimateResponse(BaseModel):
    url_count: int


class SmartCrawlPlanBreakdown(BaseModel):
    page_type: str
    label: str
    total_urls: int
    sampled_urls: int
    sample_urls: list[str]
    skipped: bool
    coverage_ratio: float


class SmartCrawlEstimateResponse(BaseModel):
    total_site_urls: int
    total_page_types: int
    sampled_urls_count: int
    plan: list[SmartCrawlPlanBreakdown]


class SitemapCrawlStartResponse(BaseModel):
    job_id: str
    status: str
    total_urls: int | None


class SitemapCrawlStatusResponse(BaseModel):
    id: str
    project_id: int
    user_id: int
    sitemap_url: str
    status: str
    total_urls: int | None
    completed_urls: int
    failed_urls: int
    error: str | None
    created_at: str | None
    completed_at: str | None


class SitemapCrawlReportResponse(BaseModel):
    id: str
    project_id: int
    status: str
    report: dict[str, Any]


@router.options("/embed/audit", status_code=status.HTTP_204_NO_CONTENT)
async def embed_audit_options(request: Request, response: Response):
    origin = (request.headers.get("origin") or "").strip() or None
    for key, value in build_embed_cors_headers(origin).items():
        response.headers[key] = value
    return None


@router.options("/embed/audit/{job_id}/status", status_code=status.HTTP_204_NO_CONTENT)
async def embed_audit_status_options(job_id: str, request: Request, response: Response):
    _ = job_id
    origin = (request.headers.get("origin") or "").strip() or None
    for key, value in build_embed_cors_headers(origin).items():
        response.headers[key] = value
    return None


@router.post(
    "/embed/audit",
    response_model=EmbedAuditCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_embed_audit(
    payload: EmbedAuditCreateRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    principal, origin = await authenticate_embed_key(request=request, db=db, enforce_origin=True)
    await enforce_embed_daily_limit(response=response, api_key=principal.api_key)
    await _verify_embed_captcha(
        token=payload.captcha_token,
        remote_ip=request.client.host if request.client else None,
    )

    resolved_target_type = (
        payload.audit_target_type
        if payload.audit_target_type in {"website", "brand"}
        else "website"
    )
    resolved_target_name = payload.resolved_target_name()
    resolved_url = (payload.url or "").strip() or None
    job_url = resolved_url or ""
    target_name_for_job = resolved_target_name or resolved_url or "Brand audit"

    estimated_credit_cost = calculate_audit_credit_cost(
        provider=EMBED_AUDIT_PROVIDER,
        tier=EMBED_AUDIT_TIER,
        entities_count=1 if resolved_target_name else 0,
    )
    # SIGV2-1024: credits are internal soft limits and never block an audit.
    # Embed audits consume one scan atomically with the job insert.
    from services.scan_allowance_service import consume_scan_allowance

    consume_scan_allowance(db, principal.user)

    job_id = str(uuid4())
    request_id = f"embed:{principal.api_key.id}:{job_id}"
    db_job = models.AuditJob(
        id=job_id,
        user_id=principal.user.id,
        embed_api_key_id=principal.api_key.id,
        status=JOB_STATUS_QUEUED,
        source="embed",
        audit_target_type=(
            models.AuditTargetType.BRAND
            if resolved_target_type == "brand"
            else models.AuditTargetType.WEBSITE
        ),
        target_name=target_name_for_job,
        target_url=resolved_url,
        target_metadata={},
        url=job_url,
        provider=EMBED_AUDIT_PROVIDER,
        tier=EMBED_AUDIT_TIER,
        estimated_credit_cost=estimated_credit_cost,
        request_id=request_id,
        # SIGV2-1129: a widget lead audit runs against the customer's own
        # target on their embed key, so it is one of their scans.
        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
    )
    db.add(db_job)

    lead = models.Lead(
        workspace_id=principal.api_key.workspace_id,
        embed_key_id=principal.api_key.id,
        email=str(payload.email).lower(),
        url=resolved_url or "",
        entity=resolved_target_name,
        audit_job_id=job_id,
        scores_json=None,
        source="widget",
        status="pending",
        ip_address=request.client.host if request.client else None,
        schema_version="1",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    payload_job = AuditJobPayload(
        job_id=job_id,
        request_id=request_id,
        user_id=principal.user.id,
        url=job_url,
        audit_target_type=resolved_target_type,
        target_name=target_name_for_job,
        target_url=resolved_url,
        target_metadata={},
        provider=EMBED_AUDIT_PROVIDER,
        tier=EMBED_AUDIT_TIER,
        project_id=None,
        estimated_credit_cost=estimated_credit_cost,
        entities=[resolved_target_name] if resolved_target_name else None,
        category="lead widget",
        # SIGV2-1121: a widget lead audit measures the requested target for the
        # workspace itself, and this write path declares that explicitly.
        project_scope=declare_audit_project_scope(category="lead widget"),
    )
    async with get_async_redis() as redis_client:
        await redis_client.hset(
            f"audit:job:{job_id}",
            mapping={
                "status": JOB_STATUS_QUEUED,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "user_id": str(principal.user.id),
                "provider": EMBED_AUDIT_PROVIDER,
                "tier": EMBED_AUDIT_TIER,
                "project_id": "",
                "estimated_credit_cost": str(estimated_credit_cost),
                "source": "embed",
                "embed_key_id": str(principal.api_key.id),
            },
        )
        await redis_client.rpush(
            resolve_queue_for_tier(EMBED_AUDIT_TIER), json.dumps(payload_job.to_dict())
        )
        from services.job_ttl_dlq_service import set_ttl_queued

        await set_ttl_queued(redis_client, job_id)

    if principal.user.email:
        await EmailService(db).send_lead_captured_email(
            email=principal.user.email,
            workspace_name=principal.api_key.workspace.name
            if principal.api_key.workspace
            else None,
            lead_email=lead.email,
            lead_url=lead.url or "Not provided (brand audit)",
            lead_entity=lead.entity,
            lead_id=int(lead.id),
            dashboard_url="/dashboard/leads",
            user_id=principal.user.id,
            workspace_id=principal.api_key.workspace_id,
            correlation_id=f"lead:{lead.id}",
        )

    for key, value in build_embed_cors_headers(origin).items():
        response.headers[key] = value

    return {
        "lead_id": int(lead.id),
        "job_id": job_id,
        "poll_url": f"/api/v1/embed/audit/{job_id}/status",
        "estimated_seconds": 30,
    }


@router.get("/embed/audit/{job_id}/status", response_model=EmbedAuditStatusResponse)
async def get_embed_audit_status(
    job_id: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    lead = db.query(models.Lead).filter(models.Lead.audit_job_id == job_id).first()
    if lead is None:
        raise HTTPException(status_code=404, detail="Embed audit job not found.")

    request_origin = (request.headers.get("origin") or "").strip() or None
    if request_origin and lead.embed_key is not None:
        if not origin_allowed(request_origin, lead.embed_key.allowed_origins):
            raise HTTPException(status_code=403, detail="Origin is not allowed for this embed job.")

    db_job = (
        db.query(models.AuditJob)
        .filter(
            models.AuditJob.id == job_id,
            models.AuditJob.source == "embed",
        )
        .first()
    )
    if db_job is None:
        raise HTTPException(status_code=404, detail="Embed audit job not found.")

    status_value = _map_job_status(db_job.status)
    scores_payload: dict[str, float | None] | None = None

    if status_value == "completed" and db_job.request_id:
        audit = (
            db.query(models.Audit)
            .filter(
                models.Audit.user_id == db_job.user_id,
                models.Audit.request_id == db_job.request_id,
            )
            .order_by(models.Audit.created_at.desc())
            .first()
        )
        if audit is not None:
            scores_payload = {
                "geo": float(audit.geo_score)
                if isinstance(audit.geo_score, (int, float))
                else None,
                "seo": float(audit.seo_score)
                if isinstance(audit.seo_score, (int, float))
                else None,
                "aeo": float(audit.aeo_score)
                if isinstance(audit.aeo_score, (int, float))
                else None,
            }
            if lead.status != "audit_complete":
                lead.scores_json = scores_payload
                lead.status = "audit_complete"
                db.add(lead)
                db.commit()

    if request_origin:
        for key, value in build_embed_cors_headers(request_origin).items():
            response.headers[key] = value

    return {
        "job_id": db_job.id,
        "status": status_value,
        "scores": scores_payload,
        "error": db_job.error,
    }


@router.get("/workspaces/{workspace_id}/leads", response_model=WorkspaceLeadsListResponse)
def list_workspace_leads(
    workspace_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    status_filter: str | None = Query(default=None, alias="status"),
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    require_not_portal_only(user)
    workspace, _role = _workspace_access(
        db, user=user, workspace_id=workspace_id, allow_client_readonly=False
    )
    _enforce_lead_widget_plan_for_workspace(workspace)

    query = db.query(models.Lead).filter(models.Lead.workspace_id == workspace.id)
    if status_filter:
        query = query.filter(models.Lead.status == status_filter)

    total = query.count()
    items = (
        query.order_by(models.Lead.created_at.desc(), models.Lead.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {
        "items": [_serialize_lead(item) for item in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/workspaces/{workspace_id}/embed-keys")
def list_workspace_embed_keys(
    workspace_id: int,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    require_not_portal_only(user)
    workspace, _role = _workspace_access(
        db, user=user, workspace_id=workspace_id, allow_client_readonly=False
    )
    _enforce_lead_widget_plan_for_workspace(workspace)

    keys = (
        db.query(models.EmbedApiKey)
        .filter(models.EmbedApiKey.workspace_id == workspace.id)
        .order_by(models.EmbedApiKey.created_at.desc(), models.EmbedApiKey.id.desc())
        .all()
    )
    return [serialize_embed_key(item) for item in keys]


@router.post(
    "/workspaces/{workspace_id}/embed-keys",
    response_model=EmbedKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_embed_key(
    workspace_id: int,
    payload: EmbedKeyCreateRequest,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    require_not_portal_only(user)
    workspace, role = _workspace_access(
        db, user=user, workspace_id=workspace_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)
    _enforce_lead_widget_plan_for_workspace(workspace)

    raw_key, key_hash, key_prefix, key_last_four = generate_embed_api_key_material()
    try:
        normalized_origins = normalize_allowed_origins(payload.allowed_origins)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    owner_user_id = int(workspace.owner_id)
    embed_key = models.EmbedApiKey(
        workspace_id=workspace.id,
        user_id=owner_user_id,
        label=payload.label.strip(),
        key_hash=key_hash,
        key_prefix=key_prefix,
        key_last_four=key_last_four,
        allowed_origins=normalized_origins,
        daily_limit=max(1, int(payload.daily_limit)),
        is_active=True,
        schema_version="1",
    )
    db.add(embed_key)
    db.commit()
    db.refresh(embed_key)

    return {
        "api_key": raw_key,
        "item": serialize_embed_key(embed_key),
    }


@router.delete(
    "/workspaces/{workspace_id}/embed-keys/{embed_key_id}", response_model=EmbedKeyDeleteResponse
)
def revoke_workspace_embed_key(
    workspace_id: int,
    embed_key_id: int,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    require_not_portal_only(user)
    workspace, role = _workspace_access(
        db, user=user, workspace_id=workspace_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)
    _enforce_lead_widget_plan_for_workspace(workspace)

    embed_key = (
        db.query(models.EmbedApiKey)
        .filter(
            models.EmbedApiKey.id == embed_key_id,
            models.EmbedApiKey.workspace_id == workspace.id,
        )
        .first()
    )
    if embed_key is None:
        raise HTTPException(status_code=404, detail="Embed API key not found.")

    embed_key.is_active = False
    db.add(embed_key)
    db.commit()
    db.refresh(embed_key)

    return {"revoked": True, "item": serialize_embed_key(embed_key)}


@router.post(
    "/projects/{project_id}/sitemap-crawl/estimate",
    response_model=SitemapCrawlEstimateResponse,
)
async def estimate_sitemap_crawl(
    project_id: int,
    payload: SitemapCrawlRequest,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    project, _workspace, role = _project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)

    try:
        urls = await sitemap_crawler_service.parse_sitemap(payload.sitemap_url, max_urls=500)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    estimate = sitemap_crawler_service.estimate_crawl(url_count=len(urls))
    return {"url_count": estimate["url_count"]}


@router.post("/projects/{project_id}/sitemap-crawl", response_model=SitemapCrawlStartResponse)
async def start_sitemap_crawl(
    project_id: int,
    payload: SitemapCrawlRequest,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    project, _workspace, role = _project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)
    _enforce_lead_widget_plan_for_user(user)

    try:
        crawl_job = await sitemap_crawler_service.start_crawl(
            db=db,
            user=user,
            project=project,
            sitemap_url=payload.sitemap_url,
            max_urls=500,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "job_id": crawl_job.id,
        "status": crawl_job.status,
        "total_urls": crawl_job.total_urls,
    }


@router.get(
    "/projects/{project_id}/sitemap-crawl/latest", response_model=SitemapCrawlStatusResponse
)
def get_latest_sitemap_crawl(
    project_id: int,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    _project, _workspace, _role = _project_access(
        db,
        user=user,
        project_id=project_id,
        allow_client_readonly=True,
    )

    crawl_job = (
        db.query(models.SitemapCrawlJob)
        .filter(models.SitemapCrawlJob.project_id == project_id)
        .order_by(models.SitemapCrawlJob.created_at.desc())
        .first()
    )
    if crawl_job is None:
        raise HTTPException(status_code=404, detail="No sitemap crawl found for this project.")

    return {
        "id": crawl_job.id,
        "project_id": int(crawl_job.project_id),
        "user_id": int(crawl_job.user_id),
        "sitemap_url": crawl_job.sitemap_url,
        "status": crawl_job.status,
        "total_urls": crawl_job.total_urls,
        "completed_urls": int(crawl_job.completed_urls or 0),
        "failed_urls": int(crawl_job.failed_urls or 0),
        "error": crawl_job.error,
        "created_at": crawl_job.created_at.isoformat() if crawl_job.created_at else None,
        "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
    }


@router.get("/sitemap-crawl/{crawl_job_id}", response_model=SitemapCrawlStatusResponse)
def get_sitemap_crawl_status(
    crawl_job_id: str,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    crawl_job = (
        db.query(models.SitemapCrawlJob).filter(models.SitemapCrawlJob.id == crawl_job_id).first()
    )
    if crawl_job is None:
        raise HTTPException(status_code=404, detail="Sitemap crawl job not found.")

    _project, _workspace, _role = _project_access(
        db,
        user=user,
        project_id=crawl_job.project_id,
        allow_client_readonly=True,
    )

    return {
        "id": crawl_job.id,
        "project_id": int(crawl_job.project_id),
        "user_id": int(crawl_job.user_id),
        "sitemap_url": crawl_job.sitemap_url,
        "status": crawl_job.status,
        "total_urls": crawl_job.total_urls,
        "completed_urls": int(crawl_job.completed_urls or 0),
        "failed_urls": int(crawl_job.failed_urls or 0),
        "error": crawl_job.error,
        "created_at": crawl_job.created_at.isoformat() if crawl_job.created_at else None,
        "completed_at": crawl_job.completed_at.isoformat() if crawl_job.completed_at else None,
    }


@router.get("/sitemap-crawl/{crawl_job_id}/report", response_model=SitemapCrawlReportResponse)
def get_sitemap_crawl_report(
    crawl_job_id: str,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    crawl_job = (
        db.query(models.SitemapCrawlJob).filter(models.SitemapCrawlJob.id == crawl_job_id).first()
    )
    if crawl_job is None:
        raise HTTPException(status_code=404, detail="Sitemap crawl job not found.")

    _project, _workspace, _role = _project_access(
        db,
        user=user,
        project_id=crawl_job.project_id,
        allow_client_readonly=True,
    )

    if crawl_job.status != "completed":
        raise HTTPException(status_code=409, detail="Sitemap crawl report is not available yet.")

    report_payload = (
        crawl_job.aggregated_scores_json
        if isinstance(crawl_job.aggregated_scores_json, dict)
        else {}
    )
    return {
        "id": crawl_job.id,
        "project_id": int(crawl_job.project_id),
        "status": crawl_job.status,
        "report": report_payload,
    }


# ------------------------------------------------------------------ #
#  Smart Sample Crawl endpoints
# ------------------------------------------------------------------ #


@router.post(
    "/projects/{project_id}/smart-crawl/estimate",
    response_model=SmartCrawlEstimateResponse,
)
async def estimate_smart_crawl(
    project_id: int,
    payload: SitemapCrawlRequest,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """Estimate a smart sample crawl, returns page-type breakdown and credit cost."""
    project, _workspace, role = _project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)

    try:
        plan = await sitemap_crawler_service.estimate_smart_crawl(
            sitemap_url=payload.sitemap_url,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Internal credit fields are stripped from the customer-facing estimate.
    for credit_key in ("per_url_credit_cost", "estimated_credit_cost"):
        plan.pop(credit_key, None)
    return plan


@router.post(
    "/projects/{project_id}/smart-crawl",
    response_model=SitemapCrawlStartResponse,
)
async def start_smart_crawl(
    project_id: int,
    payload: SitemapCrawlRequest,
    user: Annotated[models.User, Depends(get_current_user)] = None,
    db: Session = Depends(get_db),
):
    """Start a smart sample crawl that audits representative pages per page type."""
    project, _workspace, role = _project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(role)
    _enforce_lead_widget_plan_for_user(user)

    try:
        crawl_job = await sitemap_crawler_service.start_smart_crawl(
            db=db,
            user=user,
            project=project,
            sitemap_url=payload.sitemap_url,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "job_id": crawl_job.id,
        "status": crawl_job.status,
        "total_urls": crawl_job.total_urls,
    }
