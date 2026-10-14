"""Launching an audit on behalf of an API key holder (SIGV2-1210).

This module is the one path by which an external caller starts a paid audit.
It was lifted wholesale out of ``routers.external_api_router`` when the MCP
server gained an audit-triggering tool, because the alternative was a second
implementation of the same rules and this codebase has already shipped two
duplicated limiters that disagreed with their originals.

Everything that makes starting an audit safe lives here, in this order, and
the order is the contract:

1. **Entitlement.** A competitor lite audit the plan does not include is
   refused before any row is written (SIGV2-1126).
2. **Idempotency.** A caller-supplied key is resolved against Redis first, so
   a retry returns the original job instead of starting a second paid audit.
   The stored record carries a fingerprint of the request, so the same key
   used for a different target is a 409 rather than a silently wrong replay.
3. **Dedup.** An audit already in progress for the same target is a 409, which
   catches the retry that arrives without an idempotency key at all.
4. **Scan allowance.** ``consume_scan_allowance`` counts customer-origin jobs
   in the rolling 30-day window and raises 402 at the plan's ``max_audits``.
   It locks the user row, and the caller commits the new job in the same
   transaction, so two concurrent launches for the final slot serialise.
5. **Project scan cap.** The per-project budget, separate from the plan's.

Only then is the job row written and queued.

Both callers reach this through ``launch_external_audit``. Neither may
reimplement any step of it, and neither may reorder them: counting the
allowance before resolving idempotency would charge a scan for a replay.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncContextManager, Callable, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

import models
from auth.credits import calculate_audit_credit_cost
from job_models import JOB_STATUS_QUEUED, AuditJobPayload
from services.ai_routing_policy import resolve_audit_route
from services.audit_helpers import competitor_lite_audit_is_denied
from services.external_api_service import (
    EXTERNAL_JOB_SOURCE,
    ExternalAPIPrincipal,
    build_idempotency_fingerprint,
    external_error,
    hash_idempotency_key,
    map_external_job_status,
    serialize_audit_scores,
)
from services.project_audit_scope import (
    declare_audit_project_scope,
    sanitize_client_request_id,
)
from services.queue_routing import resolve_queue_for_tier
from services.url_validation import normalize_and_validate_url, validate_target_host
from services.workspace_rbac import resolve_project_access

logger = logging.getLogger(__name__)

# The Redis context factory is passed in rather than imported, so the caller
# decides which client the launch path talks to. Each caller resolves it from
# its own module namespace at call time, which is also what lets a test
# substitute a fake for one surface without reaching into this module.
RedisContextFactory = Callable[[], AsyncContextManager[Any]]

ALLOWED_AUDIT_TIERS = {"fast", "smart", "standard", "deep", "deep_judgment"}
DEFAULT_ESTIMATED_COMPLETION_SECONDS = 45


class ExternalAuditCreateRequest(BaseModel):
    url: str | None = None
    audit_target_type: Literal["website", "brand"] = "website"
    target_name: str | None = None
    target_metadata: dict[str, Any] | None = None
    brand_truth_payload: dict[str, Any] | None = None
    tier: str = "fast"
    entity: str | None = None
    entities: list[str] | None = None
    category: str | None = None
    market: str | None = None
    language: str | None = None
    project_id: int | None = Field(default=None, gt=0)
    webhook_url: str | None = None
    webhook_secret: str | None = Field(default=None, min_length=8, max_length=255)
    idempotency_key: str | None = Field(default=None, min_length=4, max_length=255)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_and_validate_url(value)

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_and_validate_url(value)
        validate_target_host(normalized)
        return normalized

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in ALLOWED_AUDIT_TIERS:
            raise ValueError("tier must be one of: fast, smart, deep_judgment, standard, deep.")
        return normalized

    @model_validator(mode="after")
    def normalize_entity_fields(self) -> "ExternalAuditCreateRequest":
        merged_entities = [str(item).strip() for item in (self.entities or []) if str(item).strip()]
        if self.entity and self.entity.strip():
            merged_entities = [self.entity.strip(), *merged_entities]
        deduped: list[str] = []
        for entity in merged_entities:
            if entity not in deduped:
                deduped.append(entity)
        self.entities = deduped or None
        return self

    @model_validator(mode="after")
    def validate_target_type_fields(self) -> "ExternalAuditCreateRequest":
        if self.audit_target_type == "brand":
            if not self.target_name or not self.target_name.strip():
                raise ValueError("target_name is required when audit_target_type is 'brand'.")
        else:
            if not self.url:
                raise ValueError("url is required when audit_target_type is 'website'.")
        return self


def resolve_external_request_project(
    *,
    project_id: int | None,
    principal: ExternalAPIPrincipal,
    db: Session,
) -> models.Project | None:
    """Resolve an optional project id inside the key's tenant boundary."""
    if project_id is None:
        return None
    access = resolve_project_access(
        db,
        user=principal.user,
        project_id=project_id,
        allow_client_readonly=False,
    )
    return access.project


def job_request_id(correlation_id: str | None, job_id: str) -> str:
    """Build a job's request id from a client-influenced correlation id.

    SIGV2-1126: the inbound correlation id is client supplied and ends up as
    the prefix of the job's request id, which is parsed elsewhere as an
    internal marker, so it is sanitized rather than trusted.
    """
    sanitized = sanitize_client_request_id(correlation_id, fallback=f"external:{job_id}")
    return f"{sanitized}:{job_id}"


def poll_url(job_id: str) -> str:
    return f"/api/v1/external/audit/{job_id}"


def report_url(job_id: str) -> str:
    return f"/api/v1/external/audit/{job_id}/report"


def estimate_credit_cost(tier: str, provider: str, entities: list[str] | None) -> int:
    return calculate_audit_credit_cost(
        provider=provider,
        tier=tier,
        entities_count=len(entities or []),
    )


def load_audit_for_job(db: Session, db_job: models.AuditJob) -> models.Audit | None:
    if not db_job.request_id:
        return None
    return (
        db.query(models.Audit)
        .filter(
            models.Audit.user_id == db_job.user_id,
            models.Audit.request_id == db_job.request_id,
        )
        .order_by(models.Audit.created_at.desc())
        .first()
    )


def serialize_job(
    *,
    db: Session,
    db_job: models.AuditJob,
) -> dict[str, Any]:
    audit = load_audit_for_job(db, db_job)
    target_type = None
    if db_job.audit_target_type is not None:
        target_type = (
            db_job.audit_target_type.value
            if hasattr(db_job.audit_target_type, "value")
            else str(db_job.audit_target_type)
        )
    return {
        "job_id": db_job.id,
        "status": map_external_job_status(db_job.status),
        "url": db_job.url or None,
        "audit_target_type": target_type,
        "target_name": db_job.target_name,
        "provider": db_job.provider,
        "tier": db_job.tier,
        "project_id": db_job.project_id,
        "scores": serialize_audit_scores(audit),
        "error": db_job.error,
        "created_at": db_job.created_at.isoformat() if db_job.created_at else None,
        "started_at": db_job.started_at.isoformat() if db_job.started_at else None,
        "completed_at": db_job.completed_at.isoformat() if db_job.completed_at else None,
        "report_url": report_url(db_job.id) if audit is not None else None,
        "webhook_status": db_job.webhook_status,
    }


async def resolve_idempotent_job(
    *,
    principal: ExternalAPIPrincipal,
    payload: ExternalAuditCreateRequest,
    redis_ctx: RedisContextFactory,
) -> str | None:
    if not payload.idempotency_key:
        return None

    async with redis_ctx() as redis_client:
        cache_key = f"idempotency:{principal.user.id}:{payload.idempotency_key}"
        cached_value = await redis_client.get(cache_key)
        if not cached_value:
            return None

        parsed = json.loads(cached_value)
        expected_fingerprint = build_idempotency_fingerprint(payload.model_dump(mode="json"))
        if parsed.get("fingerprint") != expected_fingerprint:
            raise external_error(
                code="VALIDATION_ERROR",
                message="This idempotency key was already used with a different request payload.",
                status_code=409,
            )
        return str(parsed.get("job_id"))


async def store_idempotency_record(
    *,
    principal: ExternalAPIPrincipal,
    payload: ExternalAuditCreateRequest,
    job_id: str,
    redis_ctx: RedisContextFactory,
) -> None:
    if not payload.idempotency_key:
        return
    async with redis_ctx() as redis_client:
        await redis_client.setex(
            f"idempotency:{principal.user.id}:{payload.idempotency_key}",
            timedelta(hours=24),
            json.dumps(
                {
                    "job_id": job_id,
                    "fingerprint": build_idempotency_fingerprint(payload.model_dump(mode="json")),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )


async def launch_external_audit(
    *,
    payload: ExternalAuditCreateRequest,
    principal: ExternalAPIPrincipal,
    correlation_id: str | None,
    db: Session,
    redis_ctx: RedisContextFactory,
) -> dict[str, Any]:
    """Start one audit for an API key holder, or refuse it.

    ``correlation_id`` is the inbound request correlation id, used only to
    build the job's request id; it is sanitized rather than trusted.
    """
    # SIGV2-1126: the same entitlement rule the app path applies, enforced here
    # at the boundary, before any job row, quota consumption or queue write.
    if competitor_lite_audit_is_denied(plan=principal.plan, category=payload.category):
        raise external_error(
            code="PLAN_NOT_ELIGIBLE",
            message="Your plan does not include competitor analysis. Please upgrade.",
            status_code=402,
        )

    existing_job_id = await resolve_idempotent_job(
        principal=principal, payload=payload, redis_ctx=redis_ctx
    )
    if existing_job_id:
        existing_job = (
            db.query(models.AuditJob)
            .filter(
                models.AuditJob.id == existing_job_id,
                models.AuditJob.user_id == principal.user.id,
                models.AuditJob.source == EXTERNAL_JOB_SOURCE,
            )
            .first()
        )
        if existing_job is None:
            raise external_error(
                code="JOB_NOT_FOUND",
                message="The original job for this idempotency key could not be found.",
                status_code=404,
            )
        return {
            **serialize_job(db=db, db_job=existing_job),
            "estimated_completion_seconds": DEFAULT_ESTIMATED_COMPLETION_SECONDS,
            "poll_url": poll_url(existing_job.id),
            "idempotent_replay": True,
            "webhook_secret": None,
        }

    route = resolve_audit_route(tier=payload.tier)
    estimated_credit_cost = estimate_credit_cost(
        tier=route.execution_tier,
        provider=route.provider,
        entities=payload.entities,
    )
    project = resolve_external_request_project(
        project_id=payload.project_id,
        principal=principal,
        db=db,
    )
    # SIGV2-1024: credits are internal soft limits and never block an audit.

    # --- Dedup check: prevent duplicate concurrent external audits ---
    from services.audit_dedup_service import build_dedup_key, check_dedup, set_dedup

    _ext_dedup_key = build_dedup_key(
        user_id=principal.user.id,
        target_url=payload.url,
        target_name=payload.target_name,
        tier=route.requested_tier,
        project_id=project.id if project is not None else None,
    )
    async with redis_ctx() as dedup_rc:
        _ext_existing = await check_dedup(dedup_rc, _ext_dedup_key)
    if _ext_existing:
        raise external_error(
            code="AUDIT_ALREADY_IN_PROGRESS",
            message="An audit for this target is already in progress.",
            status_code=409,
        )

    job_id = str(uuid.uuid4())
    request_id = job_request_id(correlation_id, job_id)
    webhook_secret = payload.webhook_secret
    if payload.webhook_url and not webhook_secret:
        webhook_secret = secrets.token_urlsafe(24)

    # Consume one scan atomically with the job insert (SIGV2-1024).
    from services.scan_allowance_service import consume_scan_allowance

    try:
        consume_scan_allowance(db, principal.user)
    except HTTPException as exc:
        if exc.status_code == 402:
            raise external_error(
                code="SCAN_LIMIT_EXCEEDED",
                message=str(exc.detail),
                status_code=402,
            ) from exc
        raise

    # Project scan cap (SIGV2-1102): audits block at the configured cap.
    from services.project_budget_service import enforce_project_scan_cap

    try:
        scan_result = enforce_project_scan_cap(db, project=project)
    except HTTPException as exc:
        if exc.status_code == 402:
            raise external_error(
                code="PROJECT_SCAN_CAP_EXCEEDED",
                message=str(exc.detail),
                status_code=402,
            ) from exc
        raise

    if scan_result is not None and scan_result.threshold_events:
        from services.audit_helpers import queue_project_budget_notifications

        queue_project_budget_notifications(
            db,
            project=project,
            consumed_scans=scan_result.consumed_scans,
            monthly_limit_scans=scan_result.monthly_limit_scans,
            percent_consumed=scan_result.percent_consumed,
            threshold_events=scan_result.threshold_events,
        )

    db_job = models.AuditJob(
        id=job_id,
        user_id=principal.user.id,
        api_key_id=principal.api_key.id,
        project_id=project.id if project is not None else None,
        status=JOB_STATUS_QUEUED,
        source=EXTERNAL_JOB_SOURCE,
        audit_target_type=(
            models.AuditTargetType.BRAND
            if payload.audit_target_type == "brand"
            else models.AuditTargetType.WEBSITE
        ),
        target_name=payload.target_name or payload.url,
        target_url=payload.url,
        target_metadata=payload.target_metadata or {},
        url=payload.url or "",
        provider=route.provider,
        tier=route.execution_tier,
        estimated_credit_cost=estimated_credit_cost,
        idempotency_key_hash=hash_idempotency_key(payload.idempotency_key)
        if payload.idempotency_key
        else None,
        webhook_url=payload.webhook_url,
        webhook_secret=webhook_secret,
        webhook_status="pending" if payload.webhook_url else None,
        request_id=request_id,
        # SIGV2-1129: an API caller launching an audit is the customer's own
        # scan, including a competitor lite audit they explicitly requested.
        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
    )
    db.add(db_job)
    db.commit()
    db.refresh(db_job)

    payload_job = AuditJobPayload(
        job_id=job_id,
        request_id=request_id,
        user_id=principal.user.id,
        url=payload.url or "",
        audit_target_type=payload.audit_target_type,
        target_name=payload.target_name or payload.url,
        target_url=payload.url,
        target_metadata=payload.target_metadata or {},
        brand_truth_payload=payload.brand_truth_payload,
        provider=route.provider,
        tier=route.execution_tier,
        requested_tier=route.requested_tier,
        mode_label=route.product_label,
        tier_class=route.tier_class,
        routing_feature_key=route.feature_key,
        routing_mode=route.routing_mode,
        routing_preferred_provider=route.preferred_provider,
        routing_reason=route.route_reason,
        project_id=project.id if project is not None else None,
        estimated_credit_cost=estimated_credit_cost,
        category=payload.category,
        market=payload.market,
        language=payload.language,
        entities=payload.entities,
        # SIGV2-1121: the external API declares the scope of the audit it asks
        # for, so the worker never has to guess whose target it measured.
        project_scope=declare_audit_project_scope(category=payload.category),
    )
    async with redis_ctx() as redis_client:
        await redis_client.hset(
            f"audit:job:{job_id}",
            mapping={
                "status": JOB_STATUS_QUEUED,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "request_id": request_id,
                "user_id": str(principal.user.id),
                "provider": route.provider,
                "tier": route.execution_tier,
                "project_id": str(project.id) if project is not None else "",
                "estimated_credit_cost": str(estimated_credit_cost),
                "source": EXTERNAL_JOB_SOURCE,
            },
        )
        await set_dedup(redis_client, _ext_dedup_key, job_id)
        await redis_client.rpush(
            resolve_queue_for_tier(route.execution_tier), json.dumps(payload_job.to_dict())
        )
        from services.job_ttl_dlq_service import set_ttl_queued

        await set_ttl_queued(redis_client, job_id)

    await store_idempotency_record(
        principal=principal,
        payload=payload,
        job_id=job_id,
        redis_ctx=redis_ctx,
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "estimated_completion_seconds": DEFAULT_ESTIMATED_COMPLETION_SECONDS,
        "poll_url": poll_url(job_id),
        "idempotent_replay": False,
        "webhook_secret": webhook_secret if payload.webhook_url else None,
    }
