from __future__ import annotations

import json
import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
import httpx
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature
from core.redis_client import get_async_redis
from auth.credits import should_decrement_credits
from database import get_db
from job_models import PDFJobPayload
from services.ai_routing_policy import resolve_audit_route
from services.external_api_service import (
    API_KEY_SCOPES,
    EXTERNAL_JOB_SOURCE,
    ExternalAPIPrincipal,
    audit_overall_score,
    enforce_external_rate_limit,
    external_error,
    require_api_key_scope,
    serialize_audit_scores,
)
from services.mcp_server_service import (
    MCP_ENDPOINT_PATH,
    MCP_PLAN_CAPABILITY,
    SUPPORTED_PROTOCOL_VERSIONS,
    TOOL_REGISTRY,
    mcp_availability_sentence,
    mcp_minimum_plan_id,
    tool_scopes,
)
from services.external_audit_launch_service import (
    ALLOWED_AUDIT_TIERS,
    ExternalAuditCreateRequest,
    estimate_credit_cost,
    job_request_id,
    launch_external_audit,
    load_audit_for_job,
    poll_url,
    report_url,
    resolve_external_request_project,
    serialize_job,
)
from services.export_service import (
    ExportFilters,
    iter_csv_lines,
    list_project_score_export_rows,
    max_export_rows_for_plan,
)
from app.services.learnings_service import dismissed_fingerprints
from services.audit_normalization_service import (
    build_normalized_audit_report,
    resolve_audit_normalization_current_plan,
)
from services.product_bucket_mapper import (
    BUCKET_LABELS,
    BUCKET_ORDER,
    aggregate_bucket_scores,
    bucket_for,
)
from services.url_validation import (
    async_request_with_validation,
    normalize_and_validate_url,
    validate_target_host,
)
from services.project_audit_scope import (
    own_project_audit_clause,
)
from services.workspace_rbac import accessible_workspace_ids, resolve_project_access

logger = logging.getLogger(__name__)

router = APIRouter(tags=["External API"])


class ExternalApiErrorEnvelope(BaseModel):
    code: str
    message: str
    status: int


class ExternalApiErrorResponse(BaseModel):
    error: ExternalApiErrorEnvelope


class ExternalScoreSummary(BaseModel):
    geo: float | None = None
    seo: float | None = None
    aeo: float | None = None
    # Single overall visibility score (engine-derived; report scores.overall when
    # present, else the mean of available pillar scores). Lets consumers (e.g.
    # Qiko Signal) read one number without recomputing it client-side.
    overall: float | None = None


class ExternalAuditCreateResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    estimated_completion_seconds: int
    poll_url: str
    idempotent_replay: bool = False
    webhook_secret: str | None = None


class ExternalAuditStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    url: str | None = None
    audit_target_type: str | None = None
    target_name: str | None = None
    provider: str | None = None
    tier: str | None = None
    project_id: int | None = None
    scores: ExternalScoreSummary | None = None
    error: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    report_url: str | None = None
    webhook_status: str | None = None


class ExternalAuditReportResponse(BaseModel):
    job_id: str
    audit_id: int
    status: Literal["completed"]
    url: str | None = None
    audit_target_type: str | None = None
    target_name: str | None = None
    scores: ExternalScoreSummary
    report: dict[str, Any]
    advisor: dict[str, Any] | None = None
    completed_at: str | None = None
    # Qiko Signal product bucket this audit's intent maps to (Brand/Category/
    # Problem/Feature/Comparison). Additive; derived deterministically.
    product_bucket: str | None = None


class ExternalAuditListItem(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    url: str | None = None
    audit_target_type: str | None = None
    target_name: str | None = None
    provider: str | None = None
    tier: str | None = None
    project_id: int | None = None
    created_at: str | None = None
    completed_at: str | None = None
    scores: ExternalScoreSummary | None = None


class ExternalAuditListResponse(BaseModel):
    items: list[ExternalAuditListItem]
    page: int
    page_size: int
    total: int


class ExternalAuditBulkRequest(BaseModel):
    items: list[ExternalAuditCreateRequest] = Field(..., min_length=1, max_length=50)


class ExternalAuditBulkItemResponse(BaseModel):
    url: str | None = None
    audit_target_type: str | None = None
    target_name: str | None = None
    job_id: str | None = None
    status: Literal["queued", "running", "completed", "failed"] | None = None
    poll_url: str | None = None
    idempotent_replay: bool = False
    error: str | None = None


class ExternalAuditBulkResponse(BaseModel):
    items: list[ExternalAuditBulkItemResponse]


# ---------------------------------------------------------------------------
# Project read models
# ---------------------------------------------------------------------------


class ExternalProjectSummary(BaseModel):
    id: int
    name: str
    domain_url: str | None = None
    target_country: str | None = None
    language: str = "en"
    created_at: str | None = None


class ExternalProjectListResponse(BaseModel):
    items: list[ExternalProjectSummary]
    page: int
    page_size: int
    total: int


class ExternalProjectDetailResponse(BaseModel):
    id: int
    name: str
    domain_url: str | None = None
    target_country: str | None = None
    language: str = "en"
    icp_roles: list[str] = []
    pain_points: str | None = None
    usp: str | None = None
    created_at: str | None = None
    total_audits: int = 0
    latest_audit_at: str | None = None


class ExternalProjectAuditItem(BaseModel):
    audit_id: int
    url: str | None = None
    audit_target_type: str | None = None
    target_name: str | None = None
    audit_type: str | None = None
    geo_score: float | None = None
    seo_score: float | None = None
    aeo_score: float | None = None
    created_at: str | None = None
    has_report: bool = True


class ExternalProjectAuditListResponse(BaseModel):
    items: list[ExternalProjectAuditItem]
    page: int
    page_size: int
    total: int


class ProjectBucketScore(BaseModel):
    bucket: str
    label: str
    score: float | None
    sample_size: int


class ExternalProjectBucketsResponse(BaseModel):
    project_id: int
    buckets: list[ProjectBucketScore]
    audits_analyzed: int
    generated_at: str


# ---------------------------------------------------------------------------
# Preflight & estimate models
# ---------------------------------------------------------------------------


class ExternalPreflightResponse(BaseModel):
    ok: bool
    url: str
    status_code: int | None = None
    method: str | None = None


class ExternalAuditEstimateRequest(BaseModel):
    url: str | None = None
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    tier: str = "fast"
    entities: list[str] | None = None
    category: str | None = None
    market: str | None = None

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in ALLOWED_AUDIT_TIERS:
            raise ValueError("tier must be one of: fast, smart, deep_judgment, standard, deep.")
        return normalized


class ExternalAuditEstimateResponse(BaseModel):
    """Scan-framed launch preview; internal credit fields removed (SIGV2-1024)."""

    consumes_scan: bool
    tier: str
    entities_count: int = 0
    scans_used: int
    scans_remaining: int | None = None
    reset_at: str | None = None


# SIGV2-1210: the audit launch path and its helpers moved to
# services.external_audit_launch_service so the MCP server's audit tool runs
# the same entitlement, idempotency, dedup, scan-allowance and project-cap
# sequence rather than a second copy of it. These names stay bound here because
# this module's routes and its tests already use them.
_resolve_project_for_external_request = resolve_external_request_project
_poll_url = poll_url
_report_url = report_url
_estimate_credit_cost = estimate_credit_cost
_load_audit_for_job = load_audit_for_job
_audit_overall_score = audit_overall_score
_serialize_scores = serialize_audit_scores


def _job_request_id(http_request: Request, job_id: str) -> str:
    return job_request_id(getattr(http_request.state, "request_id", None), job_id)


def _serialize_job(*, db: Session, db_job: models.AuditJob) -> dict[str, Any]:
    return serialize_job(db=db, db_job=db_job)


def _build_export_filters(
    *,
    principal: ExternalAPIPrincipal,
    project_ids: list[int] | None,
    start_date: date | None,
    end_date: date | None,
    limit: int | None,
) -> ExportFilters:
    if start_date and end_date and end_date < start_date:
        raise external_error(
            code="VALIDATION_ERROR",
            message="end_date must be on or after start_date.",
            status_code=400,
        )

    max_rows = max_export_rows_for_plan(principal.plan)
    if limit is not None and limit > max_rows:
        raise external_error(
            code="VALIDATION_ERROR",
            message=f"limit exceeds the maximum export size for your plan ({max_rows} rows).",
            status_code=400,
        )

    normalized_project_ids = sorted(
        {int(project_id) for project_id in (project_ids or []) if int(project_id) > 0}
    )
    return ExportFilters(
        project_ids=tuple(normalized_project_ids),
        start_date=start_date,
        end_date=end_date,
        row_limit=int(limit or max_rows),
    )


def _csv_filename(*, prefix: str, project_id: int | None = None) -> str:
    suffix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if project_id is not None:
        return f"{prefix}-project-{project_id}-{suffix}.csv"
    return f"{prefix}-{suffix}.csv"


async def _enqueue_external_audit_job(
    *,
    payload: ExternalAuditCreateRequest,
    principal: ExternalAPIPrincipal,
    http_request: Request,
    db: Session,
) -> dict[str, Any]:
    """Start one audit through the shared launch path (SIGV2-1210).

    ``get_async_redis`` is resolved from this module's namespace on every call
    and handed to the launch service, so this surface keeps deciding which
    Redis client its own requests talk to.
    """
    return await launch_external_audit(
        payload=payload,
        principal=principal,
        correlation_id=getattr(http_request.state, "request_id", None),
        db=db,
        redis_ctx=get_async_redis,
    )


@router.post(
    "/external/audit",
    response_model=ExternalAuditCreateResponse,
    status_code=202,
    responses={
        401: {"model": ExternalApiErrorResponse},
        402: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        409: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def create_external_audit(
    payload: ExternalAuditCreateRequest,
    response: Response,
    http_request: Request,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    try:
        return await _enqueue_external_audit_job(
            payload=payload,
            principal=principal,
            http_request=http_request,
            db=db,
        )
    except HTTPException as exc:
        if exc.status_code == 402:
            if isinstance(exc.detail, dict) and exc.detail.get("code"):
                # Already an external_error (e.g. PLAN_NOT_ELIGIBLE); pass it
                # through unchanged.
                raise
            detail = exc.detail
            message = detail if isinstance(detail, str) else str(detail)
            raise external_error(
                code="SCAN_LIMIT_EXCEEDED",
                message=message,
                status_code=402,
            ) from exc
        raise
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise external_error(
                code="INVALID_URL",
                message=str(exc),
                status_code=400,
            ) from exc
        raise


@router.get(
    "/external/audit/{job_id}",
    response_model=ExternalAuditStatusResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def get_external_audit_status(
    job_id: str,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    db_job = (
        db.query(models.AuditJob)
        .filter(
            models.AuditJob.id == job_id,
            models.AuditJob.user_id == principal.user.id,
            models.AuditJob.source == EXTERNAL_JOB_SOURCE,
        )
        .first()
    )
    if db_job is None:
        raise external_error(
            code="JOB_NOT_FOUND",
            message="Audit job not found.",
            status_code=404,
        )
    return _serialize_job(db=db, db_job=db_job)


@router.get(
    "/external/audit/{job_id}/report",
    response_model=ExternalAuditReportResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        409: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def get_external_audit_report(
    job_id: str,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    db_job = (
        db.query(models.AuditJob)
        .filter(
            models.AuditJob.id == job_id,
            models.AuditJob.user_id == principal.user.id,
            models.AuditJob.source == EXTERNAL_JOB_SOURCE,
        )
        .first()
    )
    if db_job is None:
        raise external_error(
            code="JOB_NOT_FOUND",
            message="Audit job not found.",
            status_code=404,
        )
    audit = _load_audit_for_job(db, db_job)
    if audit is None:
        raise external_error(
            code="VALIDATION_ERROR",
            message="Audit report is not available yet.",
            status_code=409,
        )
    normalized_report = build_normalized_audit_report(
        audit,
        current_plan=resolve_audit_normalization_current_plan(principal.user),
        dismissed=dismissed_fingerprints(db, getattr(audit, "project_id", None)),
    )
    target_type = None
    if db_job.audit_target_type is not None:
        target_type = (
            db_job.audit_target_type.value
            if hasattr(db_job.audit_target_type, "value")
            else str(db_job.audit_target_type)
        )
    # Serve the Advisor plan from the normalized report's dismissal-filtered
    # attach (single accessor), never from the persisted plan directly.
    normalized_metadata = (
        normalized_report.get("metadata")
        if isinstance(normalized_report.get("metadata"), dict)
        else {}
    )
    advisor_plan = (
        normalized_metadata.get("advisor")
        if isinstance(normalized_metadata.get("advisor"), dict)
        else None
    )
    return {
        "job_id": db_job.id,
        "audit_id": int(audit.id),
        "status": "completed",
        "url": audit.url or None,
        "audit_target_type": target_type,
        "target_name": db_job.target_name,
        "scores": _serialize_scores(audit),
        "report": normalized_report,
        "advisor": advisor_plan,
        "completed_at": audit.created_at.isoformat() if audit.created_at else None,
        "product_bucket": bucket_for(audit.intent, audit.query_category).value,
    }


@router.get(
    "/external/projects/{project_id}/scores/csv",
    responses={
        400: {"model": ExternalApiErrorResponse},
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def export_project_scores_csv(
    project_id: int,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
):
    rate_limit_response = Response()
    await enforce_external_rate_limit(response=rate_limit_response, principal=principal)
    project = _resolve_project_for_external_request(
        project_id=project_id,
        principal=principal,
        db=db,
    )
    if project is None:
        raise external_error(
            code="PROJECT_NOT_FOUND",
            message="Project not found.",
            status_code=404,
        )

    filters = _build_export_filters(
        principal=principal,
        project_ids=[project.id],
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    rows = list_project_score_export_rows(
        db,
        user=principal.user,
        filters=filters,
    )
    streaming_response = StreamingResponse(
        iter_csv_lines(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{_csv_filename(prefix="project-scores", project_id=project.id)}"',
        },
    )
    for header_name, header_value in rate_limit_response.headers.items():
        streaming_response.headers[header_name] = header_value
    return streaming_response


@router.get(
    "/external/projects/{project_id}/buckets",
    response_model=ExternalProjectBucketsResponse,
    responses={
        400: {"model": ExternalApiErrorResponse},
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def get_project_bucket_scores(
    project_id: int,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    response: Response,
    db: Session = Depends(get_db),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
):
    """Project-level Qiko Signal product-bucket scores (S11.x).

    Classifies each of the project's audits into one of the five product buckets
    (Brand/Category/Problem/Feature/Comparison) by its intent/query-category and
    returns the mean overall score per bucket, in canonical order.
    """
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_for_external_request(
        project_id=project_id,
        principal=principal,
        db=db,
    )
    if project is None:
        raise external_error(
            code="PROJECT_NOT_FOUND",
            message="Project not found.",
            status_code=404,
        )

    query = db.query(models.Audit).filter(
        models.Audit.project_id == project.id, own_project_audit_clause()
    )
    if start_date is not None:
        query = query.filter(
            models.Audit.created_at
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        )
    if end_date is not None:
        query = query.filter(
            models.Audit.created_at
            < datetime.combine(end_date, datetime.min.time(), tzinfo=timezone.utc)
            + timedelta(days=1)
        )
    audits = query.all()

    counts: dict = {bucket: 0 for bucket in BUCKET_ORDER}
    items: list[tuple] = []
    for audit in audits:
        bucket = bucket_for(audit.intent, audit.query_category)
        counts[bucket] += 1
        items.append((bucket, _audit_overall_score(audit)))

    bucket_scores = aggregate_bucket_scores(items)
    buckets = [
        ProjectBucketScore(
            bucket=bucket.value,
            label=BUCKET_LABELS[bucket],
            score=bucket_scores[bucket],
            sample_size=counts[bucket],
        )
        for bucket in BUCKET_ORDER
    ]
    return ExternalProjectBucketsResponse(
        project_id=project.id,
        buckets=buckets,
        audits_analyzed=len(audits),
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get(
    "/external/export",
    responses={
        400: {"model": ExternalApiErrorResponse},
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def export_scores_csv(
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
    project_id: list[int] | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1),
):
    rate_limit_response = Response()
    await enforce_external_rate_limit(response=rate_limit_response, principal=principal)
    normalized_project_ids = sorted({int(item) for item in (project_id or []) if int(item) > 0})
    for requested_project_id in normalized_project_ids:
        _resolve_project_for_external_request(
            project_id=requested_project_id,
            principal=principal,
            db=db,
        )

    filters = _build_export_filters(
        principal=principal,
        project_ids=normalized_project_ids,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    rows = list_project_score_export_rows(
        db,
        user=principal.user,
        filters=filters,
    )
    streaming_response = StreamingResponse(
        iter_csv_lines(rows),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{_csv_filename(prefix="scores-export")}"',
        },
    )
    for header_name, header_value in rate_limit_response.headers.items():
        streaming_response.headers[header_name] = header_value
    return streaming_response


@router.get("/external/audits", response_model=ExternalAuditListResponse)
async def list_external_audits(
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = Query(
        default=None, description="Filter by status: queued, running, completed, failed"
    ),
    audit_target_type: str | None = Query(
        default=None, description="Filter by target type: website, brand"
    ),
    project_id: int | None = Query(default=None, gt=0, description="Filter by project ID"),
    start_date: date | None = Query(
        default=None, description="Filter audits created on or after this date"
    ),
    end_date: date | None = Query(
        default=None, description="Filter audits created on or before this date"
    ),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    base_query = db.query(models.AuditJob).filter(
        models.AuditJob.user_id == principal.user.id,
        models.AuditJob.source == EXTERNAL_JOB_SOURCE,
    )

    if status:
        internal_status = status.strip().lower()
        if internal_status == "completed":
            internal_status = "succeeded"
        base_query = base_query.filter(models.AuditJob.status == internal_status)
    if audit_target_type:
        base_query = base_query.filter(
            models.AuditJob.audit_target_type == audit_target_type.strip().lower()
        )
    if project_id is not None:
        base_query = base_query.filter(models.AuditJob.project_id == project_id)
    if start_date:
        base_query = base_query.filter(
            models.AuditJob.created_at
            >= datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
        )
    if end_date:
        base_query = base_query.filter(
            models.AuditJob.created_at
            <= datetime.combine(end_date, datetime.max.time(), tzinfo=timezone.utc)
        )

    base_query = base_query.order_by(models.AuditJob.created_at.desc(), models.AuditJob.id.desc())
    total = base_query.count()
    rows = base_query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_serialize_job(db=db, db_job=row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/external/audit/bulk", response_model=ExternalAuditBulkResponse, status_code=202)
async def create_external_audit_bulk(
    payload: ExternalAuditBulkRequest,
    response: Response,
    http_request: Request,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    results: list[dict[str, Any]] = []
    for item in payload.items:
        try:
            queued = await _enqueue_external_audit_job(
                payload=item,
                principal=principal,
                http_request=http_request,
                db=db,
            )
            results.append(
                {
                    "url": item.url,
                    "audit_target_type": item.audit_target_type,
                    "target_name": item.target_name,
                    "job_id": queued["job_id"],
                    "status": queued["status"],
                    "poll_url": queued["poll_url"],
                    "idempotent_replay": bool(queued.get("idempotent_replay")),
                    "error": None,
                }
            )
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, dict):
                message = str(detail.get("message") or "Unable to queue audit.")
            else:
                message = str(detail or "Unable to queue audit.")
            results.append(
                {
                    "url": item.url,
                    "audit_target_type": item.audit_target_type,
                    "target_name": item.target_name,
                    "job_id": None,
                    "status": None,
                    "poll_url": None,
                    "idempotent_replay": False,
                    "error": message,
                }
            )
            db.rollback()
        except Exception as exc:
            message = "Unable to queue audit."
            if str(exc):
                message = str(exc)
            results.append(
                {
                    "url": item.url,
                    "audit_target_type": item.audit_target_type,
                    "target_name": item.target_name,
                    "job_id": None,
                    "status": None,
                    "poll_url": None,
                    "idempotent_replay": False,
                    "error": message,
                }
            )
            db.rollback()
    return {"items": results}


# ---------------------------------------------------------------------------
# Project read endpoints
# ---------------------------------------------------------------------------


# SIGV2-1210: moved to services.workspace_rbac so the MCP server scopes its
# project listing by the same tenant rule. Alias kept for this module's callers.
_accessible_workspace_ids = accessible_workspace_ids


def _serialize_project_summary(project: models.Project) -> dict[str, Any]:
    return {
        "id": project.id,
        "name": project.name,
        "domain_url": project.domain_url,
        "target_country": project.target_country,
        "language": project.language or "en",
        "created_at": project.created_at.isoformat() if project.created_at else None,
    }


@router.get(
    "/external/projects",
    response_model=ExternalProjectListResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def list_external_projects(
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    ws_ids = _accessible_workspace_ids(db, principal.user)
    if not ws_ids:
        return {"items": [], "page": page, "page_size": page_size, "total": 0}

    base_query = (
        db.query(models.Project)
        .filter(models.Project.workspace_id.in_(ws_ids))
        .order_by(models.Project.created_at.desc(), models.Project.id.desc())
    )
    total = base_query.count()
    rows = base_query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [_serialize_project_summary(p) for p in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get(
    "/external/projects/{project_id}",
    response_model=ExternalProjectDetailResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def get_external_project(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    try:
        access = resolve_project_access(
            db,
            user=principal.user,
            project_id=project_id,
            allow_client_readonly=False,
        )
    except HTTPException as exc:
        status = exc.status_code
        if status == 404:
            raise external_error(
                code="PROJECT_NOT_FOUND", message="Project not found.", status_code=404
            ) from exc
        raise external_error(
            code="FORBIDDEN", message="You do not have access to this project.", status_code=403
        ) from exc

    project = access.project

    total_audits = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .count()
    )
    latest_audit = (
        db.query(models.Audit.created_at)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc())
        .first()
    )

    return {
        "id": project.id,
        "name": project.name,
        "domain_url": project.domain_url,
        "target_country": project.target_country,
        "language": project.language or "en",
        "icp_roles": project.icp_roles or [],
        "pain_points": project.pain_points,
        "usp": project.usp,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "total_audits": total_audits,
        "latest_audit_at": latest_audit[0].isoformat()
        if latest_audit and latest_audit[0]
        else None,
    }


@router.get(
    "/external/projects/{project_id}/audits",
    response_model=ExternalProjectAuditListResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        404: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def list_external_project_audits(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    try:
        access = resolve_project_access(
            db,
            user=principal.user,
            project_id=project_id,
            allow_client_readonly=False,
        )
    except HTTPException as exc:
        status = exc.status_code
        if status == 404:
            raise external_error(
                code="PROJECT_NOT_FOUND", message="Project not found.", status_code=404
            ) from exc
        raise external_error(
            code="FORBIDDEN", message="You do not have access to this project.", status_code=403
        ) from exc

    base_query = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == access.project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
    )
    total = base_query.count()
    rows = base_query.offset((page - 1) * page_size).limit(page_size).all()
    items = []
    for audit in rows:
        target_type = None
        if audit.audit_target_type is not None:
            target_type = (
                audit.audit_target_type.value
                if hasattr(audit.audit_target_type, "value")
                else str(audit.audit_target_type)
            )
        audit_type = None
        if audit.audit_type is not None:
            audit_type = (
                audit.audit_type.value
                if hasattr(audit.audit_type, "value")
                else str(audit.audit_type)
            )
        items.append(
            {
                "audit_id": audit.id,
                "url": audit.url or None,
                "audit_target_type": target_type,
                "target_name": audit.target_name,
                "audit_type": audit_type,
                "geo_score": audit.geo_score,
                "seo_score": audit.seo_score,
                "aeo_score": audit.aeo_score,
                "created_at": audit.created_at.isoformat() if audit.created_at else None,
                "has_report": audit.full_report is not None,
            }
        )
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# ---------------------------------------------------------------------------
# Preflight & estimate endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/external/audit/preflight",
    response_model=ExternalPreflightResponse,
    responses={
        400: {"model": ExternalApiErrorResponse},
        401: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
        502: {"model": ExternalApiErrorResponse},
    },
)
async def external_audit_preflight(
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    url: str = Query(..., description="URL to validate before submitting an audit."),
):
    await enforce_external_rate_limit(response=response, principal=principal)

    try:
        normalized_url = normalize_and_validate_url(url)
        validate_target_host(normalized_url)
    except ValueError as exc:
        raise external_error(code="INVALID_URL", message=str(exc), status_code=400) from exc

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=False) as client:
        try:
            head_response, resolved_url = await async_request_with_validation(
                client,
                method="HEAD",
                url=normalized_url,
            )
            if head_response.status_code < 500:
                return {
                    "ok": True,
                    "url": str(resolved_url),
                    "status_code": head_response.status_code,
                    "method": "HEAD",
                }
        except ValueError as exc:
            raise external_error(code="INVALID_URL", message=str(exc), status_code=400) from exc
        except httpx.RequestError:
            pass

        try:
            get_response, resolved_url = await async_request_with_validation(
                client,
                method="GET",
                url=normalized_url,
                headers={"Range": "bytes=0-512"},
            )
            if get_response.status_code < 500:
                return {
                    "ok": True,
                    "url": str(resolved_url),
                    "status_code": get_response.status_code,
                    "method": "GET",
                }
            raise external_error(
                code="URL_UNREACHABLE",
                message="Target URL returned a server error.",
                status_code=400,
            )
        except ValueError as exc:
            raise external_error(code="INVALID_URL", message=str(exc), status_code=400) from exc
        except httpx.RequestError as exc:
            raise external_error(
                code="URL_UNREACHABLE",
                message="Unable to reach the target URL.",
                status_code=502,
            ) from exc


@router.post(
    "/external/audit/estimate",
    response_model=ExternalAuditEstimateResponse,
    responses={
        401: {"model": ExternalApiErrorResponse},
        403: {"model": ExternalApiErrorResponse},
        429: {"model": ExternalApiErrorResponse},
    },
)
async def external_audit_estimate(
    payload: ExternalAuditEstimateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    route = resolve_audit_route(tier=payload.tier)
    entities_count = len(payload.entities or [])
    from services.scan_allowance_service import scan_allowance_snapshot

    scan_snapshot = scan_allowance_snapshot(db, principal.user)
    return {
        "consumes_scan": should_decrement_credits(principal.user, payload.tier),
        "tier": route.execution_tier,
        "entities_count": entities_count,
        "scans_used": scan_snapshot.scans_used,
        "scans_remaining": scan_snapshot.scans_remaining,
        "reset_at": scan_snapshot.reset_at,
    }


# ===========================================================================
# Shared helpers for project-scoped external endpoints
# ===========================================================================


def _resolve_project_external(
    db: Session,
    principal: ExternalAPIPrincipal,
    project_id: int,
) -> models.Project:
    """Resolve and validate project access, wrapping errors for external API."""
    try:
        access = resolve_project_access(
            db,
            user=principal.user,
            project_id=project_id,
            allow_client_readonly=False,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise external_error(
                code="PROJECT_NOT_FOUND", message="Project not found.", status_code=404
            ) from exc
        raise external_error(
            code="FORBIDDEN", message="You do not have access to this project.", status_code=403
        ) from exc
    return access.project


def _require_plan_feature(principal: ExternalAPIPrincipal, feature: str, label: str) -> None:
    """Raise 402 if the plan lacks a required feature."""
    if not can_use_feature(principal.plan, feature):
        raise external_error(
            code="PLAN_NOT_ELIGIBLE",
            message=f"Your plan does not include {label}. Please upgrade.",
            status_code=402,
        )


_EXTERNAL_ERROR_RESPONSES = {
    401: {"model": ExternalApiErrorResponse},
    403: {"model": ExternalApiErrorResponse},
    404: {"model": ExternalApiErrorResponse},
    429: {"model": ExternalApiErrorResponse},
}

_EXTERNAL_ERROR_RESPONSES_402 = {
    **_EXTERNAL_ERROR_RESPONSES,
    402: {"model": ExternalApiErrorResponse},
}


# ===========================================================================
# TASK-95  Intelligence & Reporting
# ===========================================================================

# ---------------------------------------------------------------------------
# PDF Reports  (reports:read / reports:write)
# ---------------------------------------------------------------------------


class ExternalReportGenerateRequest(BaseModel):
    audit_ids: list[int] = Field(..., min_length=1, max_length=50)
    template_type: Literal["Technical", "Executive", "Comparative"] = "Technical"


class ExternalReportGenerateResponse(BaseModel):
    report_id: str
    status: str
    poll_url: str


class ExternalReportStatusResponse(BaseModel):
    report_id: str
    status: str
    created_at: str | None = None
    started_at: str | None = None
    completed_at: str | None = None
    download_url: str | None = None
    error: str | None = None


@router.post(
    "/external/reports/generate",
    response_model=ExternalReportGenerateResponse,
    status_code=202,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_generate_report(
    payload: ExternalReportGenerateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("reports:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    ws_ids = _accessible_workspace_ids(db, principal.user)
    if not ws_ids:
        raise external_error(code="FORBIDDEN", message="No accessible workspaces.", status_code=403)
    audits = db.query(models.Audit).filter(models.Audit.id.in_(payload.audit_ids)).all()
    found_ids: set[int] = set()
    for audit in audits:
        if audit.user_id == principal.user.id:
            found_ids.add(audit.id)
        elif audit.project_id:
            proj = db.query(models.Project).filter(models.Project.id == audit.project_id).first()
            if proj and proj.workspace_id in ws_ids:
                found_ids.add(audit.id)
    missing = set(payload.audit_ids) - found_ids
    if missing:
        raise external_error(
            code="AUDIT_NOT_FOUND",
            message=f"Audit(s) not found or not accessible: {sorted(missing)}",
            status_code=404,
        )
    report_id = str(uuid.uuid4())
    job = models.ComplexReportJob(id=report_id, user_id=principal.user.id, status="queued")
    db.add(job)
    db.commit()
    pdf_payload = {
        **PDFJobPayload(
            job_id=report_id,
            user_id=principal.user.id,
            audit_ids=payload.audit_ids,
            template_type=payload.template_type,
            options={},
            branding_config={},
        ).to_dict(),
        "source": "external_api",
    }
    async with get_async_redis() as rc:
        await rc.rpush("pdf_jobs", json.dumps(pdf_payload))
    return {
        "report_id": report_id,
        "status": "queued",
        "poll_url": f"/api/v1/external/reports/{report_id}/status",
    }


@router.get(
    "/external/reports/{report_id}/status",
    response_model=ExternalReportStatusResponse,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_report_status(
    report_id: str,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("reports:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    job = (
        db.query(models.ComplexReportJob)
        .filter(
            models.ComplexReportJob.id == report_id,
            models.ComplexReportJob.user_id == principal.user.id,
        )
        .first()
    )
    if not job:
        raise external_error(
            code="REPORT_NOT_FOUND", message="Report job not found.", status_code=404
        )
    download_url = None
    if job.status == "succeeded" and job.file_path:
        download_url = f"/api/v1/external/reports/{report_id}/download"
    return {
        "report_id": job.id,
        "status": "completed" if job.status == "succeeded" else job.status,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "download_url": download_url,
        "error": job.error,
    }


@router.get(
    "/external/reports/{report_id}/download",
    responses={
        **_EXTERNAL_ERROR_RESPONSES,
        409: {"model": ExternalApiErrorResponse},
        410: {"model": ExternalApiErrorResponse},
    },
)
async def external_report_download(
    report_id: str,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("reports:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    job = (
        db.query(models.ComplexReportJob)
        .filter(
            models.ComplexReportJob.id == report_id,
            models.ComplexReportJob.user_id == principal.user.id,
        )
        .first()
    )
    if not job:
        raise external_error(
            code="REPORT_NOT_FOUND", message="Report job not found.", status_code=404
        )
    if job.status != "succeeded" or not job.file_path:
        raise external_error(
            code="REPORT_NOT_READY",
            message=f"Report is not ready for download (status: {job.status}).",
            status_code=409,
        )
    from pathlib import Path

    file_path = Path(job.file_path)
    if not file_path.exists():
        raise external_error(
            code="REPORT_EXPIRED",
            message="Report file has expired or been removed.",
            status_code=410,
        )
    return StreamingResponse(
        open(file_path, "rb"),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="report-{report_id}.pdf"'},
    )


# ---------------------------------------------------------------------------
# Scheduled Audits  (schedules:read / schedules:write)
# ---------------------------------------------------------------------------


class ExternalScheduledAuditCreateRequest(BaseModel):
    url: str | None = None
    project_id: int | None = Field(default=None, gt=0)
    frequency: Literal["weekly", "monthly"] = "weekly"
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP", "DEEP_JUDGMENT"] = "STANDARD"
    audit_params: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ExternalScheduledAuditUpdateRequest(BaseModel):
    url: str | None = None
    frequency: Literal["weekly", "monthly"] | None = None
    audit_type: Literal["FAST", "SMART", "STANDARD", "DEEP", "DEEP_JUDGMENT"] | None = None
    audit_params: dict[str, Any] | None = None
    is_active: bool | None = None


class ExternalScheduledAuditItem(BaseModel):
    id: int
    project_id: int | None = None
    url: str | None = None
    frequency: str
    audit_type: str
    audit_params: dict[str, Any] = {}
    is_active: bool
    paused_reason: str | None = None
    last_run_status: str | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExternalScheduledAuditListResponse(BaseModel):
    items: list[ExternalScheduledAuditItem]
    total: int


def _serialize_scheduled_audit(sa: models.ScheduledAudit) -> dict[str, Any]:
    freq = (
        sa.frequency.value
        if hasattr(sa.frequency, "value")
        else str(sa.frequency)
        if sa.frequency
        else "weekly"
    )
    a_type = (
        sa.audit_type.value
        if hasattr(sa.audit_type, "value")
        else str(sa.audit_type)
        if sa.audit_type
        else "STANDARD"
    )
    pr = (
        sa.paused_reason.value
        if hasattr(sa.paused_reason, "value")
        else str(sa.paused_reason)
        if sa.paused_reason
        else None
    )
    lrs = (
        sa.last_run_status.value
        if hasattr(sa.last_run_status, "value")
        else str(sa.last_run_status)
        if sa.last_run_status
        else None
    )
    return {
        "id": sa.id,
        "project_id": sa.project_id,
        "url": sa.url,
        "frequency": freq,
        "audit_type": a_type,
        "audit_params": sa.audit_params or {},
        "is_active": sa.is_active,
        "paused_reason": pr,
        "last_run_status": lrs,
        "next_run_at": sa.next_run_at.isoformat() if sa.next_run_at else None,
        "last_run_at": sa.last_run_at.isoformat() if sa.last_run_at else None,
        "created_at": sa.created_at.isoformat() if sa.created_at else None,
        "updated_at": sa.updated_at.isoformat() if sa.updated_at else None,
    }


@router.get(
    "/external/scheduled-audits",
    response_model=ExternalScheduledAuditListResponse,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_list_scheduled_audits(
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("schedules:read"))],
    db: Session = Depends(get_db),
    project_id: int | None = Query(default=None, gt=0),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_schedule_audits", "scheduled audits")
    q = db.query(models.ScheduledAudit).filter(models.ScheduledAudit.user_id == principal.user.id)
    if project_id is not None:
        q = q.filter(models.ScheduledAudit.project_id == project_id)
    q = q.order_by(models.ScheduledAudit.next_run_at.asc(), models.ScheduledAudit.id.asc())
    rows = q.all()
    return {"items": [_serialize_scheduled_audit(r) for r in rows], "total": len(rows)}


@router.get(
    "/external/scheduled-audits/{schedule_id}",
    response_model=ExternalScheduledAuditItem,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_get_scheduled_audit(
    schedule_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("schedules:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_schedule_audits", "scheduled audits")
    sa = (
        db.query(models.ScheduledAudit)
        .filter(
            models.ScheduledAudit.id == schedule_id,
            models.ScheduledAudit.user_id == principal.user.id,
        )
        .first()
    )
    if not sa:
        raise external_error(
            code="SCHEDULE_NOT_FOUND", message="Scheduled audit not found.", status_code=404
        )
    return _serialize_scheduled_audit(sa)


@router.post(
    "/external/scheduled-audits",
    response_model=ExternalScheduledAuditItem,
    status_code=201,
    responses={**_EXTERNAL_ERROR_RESPONSES_402, 409: {"model": ExternalApiErrorResponse}},
)
async def external_create_scheduled_audit(
    payload: ExternalScheduledAuditCreateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("schedules:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_schedule_audits", "scheduled audits")
    project = None
    if payload.project_id:
        project = _resolve_project_external(db, principal, payload.project_id)
    if not payload.project_id:
        raise external_error(
            code="VALIDATION_ERROR",
            message="project_id is required for scheduled audits via the external API.",
            status_code=400,
        )
    # Check duplicate
    dup_q = db.query(models.ScheduledAudit).filter(
        models.ScheduledAudit.user_id == principal.user.id
    )
    if payload.project_id:
        dup_q = dup_q.filter(models.ScheduledAudit.project_id == payload.project_id)
    existing = dup_q.first()
    if existing and payload.project_id:
        raise external_error(
            code="DUPLICATE_SCHEDULE",
            message="A schedule already exists for this project.",
            status_code=409,
        )
    now = datetime.now(timezone.utc)
    delta = timedelta(days=30) if payload.frequency == "monthly" else timedelta(days=7)
    sa = models.ScheduledAudit(
        user_id=principal.user.id,
        project_id=payload.project_id,
        site_id=None,
        url=payload.url or (project.domain_url if project else None),
        audit_type=payload.audit_type,
        frequency=payload.frequency,
        audit_params=payload.audit_params,
        is_active=payload.is_active,
        next_run_at=now + delta,
        paused_reason="MANUAL" if not payload.is_active else None,
    )
    db.add(sa)
    db.commit()
    db.refresh(sa)
    return _serialize_scheduled_audit(sa)


@router.patch(
    "/external/scheduled-audits/{schedule_id}",
    response_model=ExternalScheduledAuditItem,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_update_scheduled_audit(
    schedule_id: int,
    payload: ExternalScheduledAuditUpdateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("schedules:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_schedule_audits", "scheduled audits")
    sa = (
        db.query(models.ScheduledAudit)
        .filter(
            models.ScheduledAudit.id == schedule_id,
            models.ScheduledAudit.user_id == principal.user.id,
        )
        .first()
    )
    if not sa:
        raise external_error(
            code="SCHEDULE_NOT_FOUND", message="Scheduled audit not found.", status_code=404
        )
    if payload.url is not None:
        sa.url = payload.url
    if payload.frequency is not None:
        sa.frequency = payload.frequency
        delta = timedelta(days=30) if payload.frequency == "monthly" else timedelta(days=7)
        sa.next_run_at = datetime.now(timezone.utc) + delta
    if payload.audit_type is not None:
        sa.audit_type = payload.audit_type
    if payload.audit_params is not None:
        merged = dict(sa.audit_params or {})
        merged.update(payload.audit_params)
        sa.audit_params = merged
    if payload.is_active is not None:
        sa.is_active = payload.is_active
        if not payload.is_active:
            sa.paused_reason = "MANUAL"
        else:
            sa.paused_reason = None
            if sa.next_run_at and sa.next_run_at < datetime.now(timezone.utc):
                delta = (
                    timedelta(days=30)
                    if (sa.frequency and str(sa.frequency).lower() == "monthly")
                    else timedelta(days=7)
                )
                sa.next_run_at = datetime.now(timezone.utc) + delta
    db.commit()
    db.refresh(sa)
    return _serialize_scheduled_audit(sa)


@router.delete(
    "/external/scheduled-audits/{schedule_id}",
    status_code=204,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_delete_scheduled_audit(
    schedule_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("schedules:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_schedule_audits", "scheduled audits")
    sa = (
        db.query(models.ScheduledAudit)
        .filter(
            models.ScheduledAudit.id == schedule_id,
            models.ScheduledAudit.user_id == principal.user.id,
        )
        .first()
    )
    if not sa:
        raise external_error(
            code="SCHEDULE_NOT_FOUND", message="Scheduled audit not found.", status_code=404
        )
    db.delete(sa)
    db.commit()


# ---------------------------------------------------------------------------
# Competitors  (competitors:read)
# ---------------------------------------------------------------------------


class ExternalCompetitorItem(BaseModel):
    id: int
    target_url: str
    display_name: str
    normalized_domain: str
    auto_audit_enabled: bool = True
    created_at: str | None = None


@router.get(
    "/external/projects/{project_id}/competitors",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_list_competitors(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("competitors:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "has_competitor_analysis", "competitor analysis")
    project = _resolve_project_external(db, principal, project_id)
    rows = (
        db.query(models.ProjectCompetitor)
        .filter(models.ProjectCompetitor.project_id == project.id)
        .order_by(models.ProjectCompetitor.created_at.desc())
        .all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "target_url": c.target_url,
                "display_name": c.display_name,
                "normalized_domain": c.normalized_domain,
                "auto_audit_enabled": c.auto_audit_enabled,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in rows
        ],
        "total": len(rows),
    }


@router.get(
    "/external/projects/{project_id}/competitive-analysis",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_competitive_analysis(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("competitors:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "has_competitor_analysis", "competitor analysis")
    project = _resolve_project_external(db, principal, project_id)
    competitors = (
        db.query(models.ProjectCompetitor)
        .filter(models.ProjectCompetitor.project_id == project.id)
        .all()
    )
    items = []
    for comp in competitors:
        latest = (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(
                models.ProjectCompetitorSnapshot.competitor_id == comp.id,
                models.ProjectCompetitorSnapshot.status == "completed",
            )
            .order_by(models.ProjectCompetitorSnapshot.captured_at.desc())
            .first()
        )
        items.append(
            {
                "competitor_id": comp.id,
                "display_name": comp.display_name,
                "normalized_domain": comp.normalized_domain,
                "latest_snapshot": {
                    "geo_score": latest.geo_score,
                    "seo_score": latest.seo_score,
                    "aeo_score": latest.aeo_score,
                    "captured_at": latest.captured_at.isoformat() if latest.captured_at else None,
                }
                if latest
                else None,
            }
        )
    return {"project_id": project.id, "competitors": items}


@router.get(
    "/external/projects/{project_id}/competitive-analysis/trends",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_competitive_trends(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("competitors:read"))],
    db: Session = Depends(get_db),
    period: str = Query("90d", description="Time period: 30d, 90d, 1y, all"),
    metric: str = Query("overall", description="Metric: geo, seo, aeo, overall"),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "has_competitor_analysis", "competitor analysis")
    project = _resolve_project_external(db, principal, project_id)
    days_map = {"30d": 30, "90d": 90, "1y": 365, "all": 3650}
    days = days_map.get(period, 90)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    competitors = (
        db.query(models.ProjectCompetitor)
        .filter(models.ProjectCompetitor.project_id == project.id)
        .all()
    )
    result = []
    for comp in competitors:
        snapshots = (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(
                models.ProjectCompetitorSnapshot.competitor_id == comp.id,
                models.ProjectCompetitorSnapshot.status == "completed",
                models.ProjectCompetitorSnapshot.captured_at >= cutoff,
            )
            .order_by(models.ProjectCompetitorSnapshot.captured_at.asc())
            .all()
        )
        data_points = []
        for s in snapshots:
            point = {"captured_at": s.captured_at.isoformat() if s.captured_at else None}
            if metric in ("geo", "overall"):
                point["geo_score"] = s.geo_score
            if metric in ("seo", "overall"):
                point["seo_score"] = s.seo_score
            if metric in ("aeo", "overall"):
                point["aeo_score"] = s.aeo_score
            data_points.append(point)
        result.append(
            {
                "competitor_id": comp.id,
                "display_name": comp.display_name,
                "data_points": data_points,
            }
        )
    return {"project_id": project.id, "period": period, "metric": metric, "competitors": result}


# ---------------------------------------------------------------------------
# Entity Authority  (entities:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/entity-authority",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_entity_authority(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("entities:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "entity_authority", "entity authority")
    project = _resolve_project_external(db, principal, project_id)
    from services.entity_authority_service import EntityAuthorityService

    svc = EntityAuthorityService()
    result = svc.get_latest_snapshot(db=db, project_id=project.id)
    if result is None:
        result = svc.compute_score(db=db, project_id=project.id)
    return result.as_dict()


@router.get(
    "/external/projects/{project_id}/entity-authority/gaps",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_entity_authority_gaps(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("entities:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "entity_authority", "entity authority")
    project = _resolve_project_external(db, principal, project_id)
    from services.entity_authority_service import EntityAuthorityService

    svc = EntityAuthorityService()
    gaps = svc.compute_gaps(db=db, project_id=project.id)
    return {"project_id": project.id, "gaps": [g.as_dict() for g in gaps]}


@router.get(
    "/external/projects/{project_id}/entity-authority/trend",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_entity_authority_trend(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("entities:read"))],
    db: Session = Depends(get_db),
    limit: int = Query(12, ge=1, le=52),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "entity_authority", "entity authority")
    project = _resolve_project_external(db, principal, project_id)
    from services.entity_authority_service import EntityAuthorityService

    svc = EntityAuthorityService()
    snapshots = svc.compute_trend(db=db, project_id=project.id, limit=limit)
    return {"project_id": project.id, "snapshots": [s.as_dict() for s in snapshots]}


# ---------------------------------------------------------------------------
# AI Strategic Insights  (projects:read)
# ---------------------------------------------------------------------------


class ExternalInsightsRequest(BaseModel):
    audit_id: int = Field(..., gt=0)


@router.post(
    "/external/projects/{project_id}/insights",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_generate_insights(
    project_id: int,
    payload: ExternalInsightsRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.strategic_insights_service import StrategicInsightsService

    svc = StrategicInsightsService(db)
    result = svc.generate_for_audit(
        user=principal.user, audit_id=payload.audit_id, project_id=project.id
    )
    return result


# ===========================================================================
# TASK-96  Monitoring & Analytics
# ===========================================================================

# ---------------------------------------------------------------------------
# Visibility  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/visibility/summary",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_visibility_summary(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.project_visibility_service import ProjectVisibilityService

    svc = ProjectVisibilityService(db)
    return svc.build_summary(project=project)


@router.get(
    "/external/projects/{project_id}/visibility/trends",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_visibility_trends(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.project_visibility_service import ProjectVisibilityService

    svc = ProjectVisibilityService(db)
    return svc.build_trends(project=project, days=days)


# ---------------------------------------------------------------------------
# SERP Tracking  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/serp-tracking",
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_serp_tracking(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    snapshots = (
        db.query(models.SERPTrackingSnapshot)
        .filter(models.SERPTrackingSnapshot.project_id == project.id)
        .order_by(models.SERPTrackingSnapshot.snapshot_date.desc())
        .limit(100)
        .all()
    )
    return {
        "project_id": project.id,
        "snapshots": [
            {
                "id": s.id,
                "keyword_id": s.keyword_id,
                "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
                "owns_featured_snippet": s.owns_featured_snippet,
                "organic_position": s.organic_position,
                "paa_appearances": s.paa_appearances or [],
                "serp_features_present": s.serp_features_present or [],
                "ai_overview_detected": getattr(s, "ai_overview_detected", False),
                "ai_overview_cites_target": getattr(s, "ai_overview_cites_target", False),
                "ai_overview_source_urls": getattr(s, "ai_overview_source_urls", None),
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ],
    }


# ---------------------------------------------------------------------------
# LLM Traffic  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/llm-traffic",
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_llm_traffic(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    months: int = Query(6, ge=1, le=24),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    cutoff = datetime.now(timezone.utc) - timedelta(days=months * 30)
    snapshots = (
        db.query(models.LLMTrafficSnapshot)
        .filter(
            models.LLMTrafficSnapshot.project_id == project.id,
            models.LLMTrafficSnapshot.snapshot_date >= cutoff.date(),
        )
        .order_by(models.LLMTrafficSnapshot.snapshot_date.asc())
        .all()
    )
    return {
        "project_id": project.id,
        "months": months,
        "snapshots": [
            {
                "id": s.id,
                "source": s.source,
                "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
                "sessions": s.sessions,
                "users": s.users,
                "page_views": s.page_views,
                "avg_session_duration_seconds": s.avg_session_duration_seconds,
                "bounce_rate": s.bounce_rate,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in snapshots
        ],
    }


# ---------------------------------------------------------------------------
# AI Search Volatility  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/ai-search-volatility",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_ai_search_volatility(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    provider: str = Query("all"),
    days: int = Query(30, ge=7, le=365),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.ai_search_volatility_service import AISearchVolatilityService

    svc = AISearchVolatilityService(db)
    svc.ensure_default_seed_queries()
    summary = svc.build_summary(days=days, provider=provider)
    trends = svc.build_trends(days=days, provider=provider)
    return {"project_id": project.id, "summary": summary, "trends": trends}


# ---------------------------------------------------------------------------
# Off-Page Mentions  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/off-page-mentions/summary",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_off_page_mentions_summary(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.project_offpage_mentions_service import ProjectOffPageMentionsService

    svc = ProjectOffPageMentionsService(db)
    return svc.build_summary(project=project, days=days)


@router.get(
    "/external/projects/{project_id}/off-page-mentions/feed",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_off_page_mentions_feed(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
    limit: int = Query(50, ge=1, le=200),
    sentiment: str | None = Query(default=None),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.project_offpage_mentions_service import ProjectOffPageMentionsService

    svc = ProjectOffPageMentionsService(db)
    return svc.list_feed(project_id=project.id, days=days, limit=limit, sentiment=sentiment)


# ===========================================================================
# TASK-97  Advanced Features & DX
# ===========================================================================

# ---------------------------------------------------------------------------
# Project Tasks  (projects:read)
# ---------------------------------------------------------------------------


class ExternalTaskItem(BaseModel):
    id: int
    project_id: int
    title: str
    description: str | None = None
    status: str
    priority: str
    category: str = "General"
    origin: str | None = None
    assigned_to_user_id: int | None = None
    due_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExternalTaskListResponse(BaseModel):
    items: list[ExternalTaskItem]
    total: int
    summary: dict[str, int] = {}


def _serialize_task_external(t: models.ProjectTask) -> dict[str, Any]:
    status_val = (
        t.status.value if hasattr(t.status, "value") else str(t.status) if t.status else "TODO"
    )
    priority_val = (
        t.priority.value
        if hasattr(t.priority, "value")
        else str(t.priority)
        if t.priority
        else "MEDIUM"
    )
    origin_val = (
        t.origin.value if hasattr(t.origin, "value") else str(t.origin) if t.origin else None
    )
    return {
        "id": t.id,
        "project_id": t.project_id,
        "title": t.title,
        "description": t.description,
        "status": status_val,
        "priority": priority_val,
        "category": t.category or "General",
        "origin": origin_val,
        "assigned_to_user_id": t.assigned_to_user_id,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get(
    "/external/projects/{project_id}/tasks",
    summary="List remediation actions with status summary",
    description=(
        "Returns remediation actions from Fixes and their current status summary. "
        "The Tasks board remains Coming Soon."
    ),
    response_model=ExternalTaskListResponse,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_list_tasks(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
    status: str | None = Query(
        default=None, description="Filter by status: TODO, IN_PROGRESS, DONE"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    q = db.query(models.ProjectTask).filter(models.ProjectTask.project_id == project.id)
    if status:
        q = q.filter(models.ProjectTask.status == status.upper())
    q = q.order_by(models.ProjectTask.sort_order.asc(), models.ProjectTask.created_at.desc())
    total = q.count()
    rows = q.offset((page - 1) * page_size).limit(page_size).all()
    from services.project_task_service import build_project_task_summary

    all_tasks = (
        db.query(models.ProjectTask).filter(models.ProjectTask.project_id == project.id).all()
    )
    summary = build_project_task_summary(all_tasks)
    return {
        "items": [_serialize_task_external(t) for t in rows],
        "total": total,
        "summary": summary,
    }


@router.get(
    "/external/projects/{project_id}/tasks/{task_id}",
    summary="Get a remediation action",
    description=("Returns a remediation action from Fixes. The Tasks board remains Coming Soon."),
    response_model=ExternalTaskItem,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_get_task(
    project_id: int,
    task_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("projects:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    task = (
        db.query(models.ProjectTask)
        .filter(models.ProjectTask.id == task_id, models.ProjectTask.project_id == project.id)
        .first()
    )
    if not task:
        raise external_error(code="TASK_NOT_FOUND", message="Task not found.", status_code=404)
    return _serialize_task_external(task)


# ---------------------------------------------------------------------------
# Bot Logs  (monitoring:read)
# ---------------------------------------------------------------------------


@router.get(
    "/external/projects/{project_id}/bot-logs/summary",
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_bot_log_summary(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("monitoring:read"))],
    db: Session = Depends(get_db),
    days: int = Query(30, ge=7, le=365),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    from services.project_bot_log_analyzer_service import build_project_bot_log_summary

    return build_project_bot_log_summary(db, project_id=project.id, days=days)


# ---------------------------------------------------------------------------
# Workflows  (workflows:read / workflows:write)
# ---------------------------------------------------------------------------


class ExternalWorkflowItem(BaseModel):
    id: int
    name: str
    description: str | None = None
    trigger_config: dict[str, Any] = {}
    actions_config: list[Any] = []
    cooldown_minutes: int = 1440
    is_active: bool = True
    last_triggered_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ExternalWorkflowListResponse(BaseModel):
    items: list[ExternalWorkflowItem]
    total: int


@router.get(
    "/external/projects/{project_id}/workflows",
    response_model=ExternalWorkflowListResponse,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_list_workflows(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("workflows:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_use_workflow_automations", "workflow automations")
    project = _resolve_project_external(db, principal, project_id)
    from services.workflow_engine import serialize_workflow

    rows = (
        db.query(models.Workflow)
        .filter(models.Workflow.project_id == project.id)
        .order_by(models.Workflow.created_at.desc())
        .all()
    )
    return {"items": [serialize_workflow(w) for w in rows], "total": len(rows)}


@router.get(
    "/external/projects/{project_id}/workflows/{workflow_id}",
    response_model=ExternalWorkflowItem,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_get_workflow(
    project_id: int,
    workflow_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("workflows:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_use_workflow_automations", "workflow automations")
    project = _resolve_project_external(db, principal, project_id)
    from services.workflow_engine import serialize_workflow

    wf = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if not wf:
        raise external_error(
            code="WORKFLOW_NOT_FOUND", message="Workflow not found.", status_code=404
        )
    return serialize_workflow(wf)


@router.patch(
    "/external/projects/{project_id}/workflows/{workflow_id}/toggle",
    response_model=ExternalWorkflowItem,
    responses=_EXTERNAL_ERROR_RESPONSES_402,
)
async def external_toggle_workflow(
    project_id: int,
    workflow_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("workflows:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    _require_plan_feature(principal, "can_use_workflow_automations", "workflow automations")
    project = _resolve_project_external(db, principal, project_id)
    from services.workflow_engine import serialize_workflow

    wf = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if not wf:
        raise external_error(
            code="WORKFLOW_NOT_FOUND", message="Workflow not found.", status_code=404
        )
    wf.is_active = not wf.is_active
    db.commit()
    db.refresh(wf)
    return serialize_workflow(wf)


# ---------------------------------------------------------------------------
# Alert Rules  (alerts:read / alerts:write)
# ---------------------------------------------------------------------------


class ExternalAlertRuleItem(BaseModel):
    id: int
    project_id: int
    metric: str
    condition: str
    threshold: float
    email_to: str
    is_active: bool = True
    last_triggered_at: str | None = None
    created_at: str | None = None


class ExternalAlertRuleListResponse(BaseModel):
    items: list[ExternalAlertRuleItem]
    total: int


class ExternalAlertRuleCreateRequest(BaseModel):
    metric: str = Field(..., description="Metric to monitor: geo_score, seo_score, aeo_score")
    condition: str = Field(..., description="Condition: below, drops_by")
    threshold: float = Field(..., ge=0, le=100)
    email_to: str
    is_active: bool = True


class ExternalAlertRuleUpdateRequest(BaseModel):
    metric: str | None = None
    condition: str | None = None
    threshold: float | None = Field(default=None, ge=0, le=100)
    email_to: str | None = None
    is_active: bool | None = None


def _serialize_alert_rule_external(rule: models.AlertRule) -> dict[str, Any]:
    return {
        "id": rule.id,
        "project_id": rule.project_id,
        "metric": rule.metric,
        "condition": rule.condition,
        "threshold": rule.threshold,
        "email_to": rule.email_to,
        "is_active": rule.is_active,
        "last_triggered_at": rule.last_triggered_at.isoformat() if rule.last_triggered_at else None,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
    }


@router.get(
    "/external/projects/{project_id}/alerts",
    response_model=ExternalAlertRuleListResponse,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_list_alert_rules(
    project_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("alerts:read"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    rows = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.project_id == project.id)
        .order_by(models.AlertRule.created_at.desc())
        .all()
    )
    return {"items": [_serialize_alert_rule_external(r) for r in rows], "total": len(rows)}


@router.post(
    "/external/projects/{project_id}/alerts",
    response_model=ExternalAlertRuleItem,
    status_code=201,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_create_alert_rule(
    project_id: int,
    payload: ExternalAlertRuleCreateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("alerts:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    allowed_metrics = {"geo_score", "seo_score", "aeo_score"}
    if payload.metric not in allowed_metrics:
        raise external_error(
            code="VALIDATION_ERROR",
            message=f"metric must be one of: {', '.join(sorted(allowed_metrics))}",
            status_code=400,
        )
    allowed_conditions = {"below", "drops_by"}
    if payload.condition not in allowed_conditions:
        raise external_error(
            code="VALIDATION_ERROR",
            message=f"condition must be one of: {', '.join(sorted(allowed_conditions))}",
            status_code=400,
        )
    rule = models.AlertRule(
        project_id=project.id,
        metric=payload.metric,
        condition=payload.condition,
        threshold=payload.threshold,
        email_to=payload.email_to,
        is_active=payload.is_active,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _serialize_alert_rule_external(rule)


@router.put(
    "/external/projects/{project_id}/alerts/{rule_id}",
    response_model=ExternalAlertRuleItem,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_update_alert_rule(
    project_id: int,
    rule_id: int,
    payload: ExternalAlertRuleUpdateRequest,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("alerts:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    rule = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.id == rule_id, models.AlertRule.project_id == project.id)
        .first()
    )
    if not rule:
        raise external_error(
            code="ALERT_RULE_NOT_FOUND", message="Alert rule not found.", status_code=404
        )
    if payload.metric is not None:
        rule.metric = payload.metric
    if payload.condition is not None:
        rule.condition = payload.condition
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.email_to is not None:
        rule.email_to = payload.email_to
    if payload.is_active is not None:
        rule.is_active = payload.is_active
    db.commit()
    db.refresh(rule)
    return _serialize_alert_rule_external(rule)


@router.delete(
    "/external/projects/{project_id}/alerts/{rule_id}",
    status_code=204,
    responses=_EXTERNAL_ERROR_RESPONSES,
)
async def external_delete_alert_rule(
    project_id: int,
    rule_id: int,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("alerts:write"))],
    db: Session = Depends(get_db),
):
    await enforce_external_rate_limit(response=response, principal=principal)
    project = _resolve_project_external(db, principal, project_id)
    rule = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.id == rule_id, models.AlertRule.project_id == project.id)
        .first()
    )
    if not rule:
        raise external_error(
            code="ALERT_RULE_NOT_FOUND", message="Alert rule not found.", status_code=404
        )
    db.delete(rule)
    db.commit()


# ---------------------------------------------------------------------------
# OpenAPI Spec Export & SDK Metadata  (no scope needed beyond auth)
# ---------------------------------------------------------------------------


@router.get("/external/openapi.json", responses=_EXTERNAL_ERROR_RESPONSES)
async def external_openapi_spec(
    request: Request,
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
):
    await enforce_external_rate_limit(response=response, principal=principal)
    app = request.app
    full_spec = app.openapi()
    external_paths = {}
    for path, methods in (full_spec.get("paths") or {}).items():
        if path.startswith("/external/") or "/external/" in path:
            external_paths[path] = methods
    filtered_spec = {
        "openapi": full_spec.get("openapi", "3.1.0"),
        "info": {
            "title": "Qiko Signal External API",
            "version": full_spec.get("info", {}).get("version", "1.0.0"),
            "description": "Public API for Qiko Signal GEO/AEO audit platform.",
        },
        "paths": external_paths,
        "components": full_spec.get("components", {}),
    }
    return filtered_spec


def _mcp_metadata(principal: ExternalAPIPrincipal) -> dict[str, Any]:
    """What this key may do with the MCP server, stated honestly either way.

    A key on an ineligible plan is told the server exists, which plan it needs
    and that this key cannot use it, rather than being shown an endpoint that
    would refuse it. Every field is derived from the entitlement config, so it
    cannot advertise a grant the gate does not give (SIGV2-1210).
    """
    enabled = can_use_feature(principal.plan, MCP_PLAN_CAPABILITY)
    metadata: dict[str, Any] = {
        "enabled": enabled,
        "availability": mcp_availability_sentence(),
        "required_plan": mcp_minimum_plan_id(),
        "transport": "streamable-http",
        "protocol_versions": list(SUPPORTED_PROTOCOL_VERSIONS),
        "authentication": "api_key_bearer",
        "tools": [tool.name for tool in TOOL_REGISTRY],
        # Derived, never asserted: the one tool that spends is named here
        # rather than described as a property of the server, so this cannot
        # keep claiming the server is read-only once a write tool exists.
        "scopes": list(tool_scopes()),
        "tools_that_consume_a_scan": [tool.name for tool in TOOL_REGISTRY if tool.consumes_scan],
    }
    # The usable endpoint is published only to a key that may actually connect.
    metadata["endpoint"] = MCP_ENDPOINT_PATH if enabled else None
    return metadata


@router.get("/external/sdk-metadata", responses=_EXTERNAL_ERROR_RESPONSES)
async def external_sdk_metadata(
    response: Response,
    principal: Annotated[ExternalAPIPrincipal, Depends(require_api_key_scope("audit:read"))],
):
    await enforce_external_rate_limit(response=response, principal=principal)
    return {
        "api_version": "v1",
        "base_path": "/api/v1/external",
        "available_scopes": list(API_KEY_SCOPES),
        "supported_tiers": ["fast", "smart", "deep_judgment", "standard", "deep"],
        "rate_limits": {
            "plan_specialist": {"per_minute": 60, "per_day": 1000},
            "plan_executive": {"per_minute": 300, "per_day": 10000},
        },
        "mcp": _mcp_metadata(principal),
    }
