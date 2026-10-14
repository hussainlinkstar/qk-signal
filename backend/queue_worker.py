import asyncio
import contextlib
import copy
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from uuid import uuid4

from dateutil.relativedelta import relativedelta

from core.env_bootstrap import bootstrap_environment
from core.redis_client import get_async_redis_client
from fastapi import HTTPException
import redis.asyncio as async_redis
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

bootstrap_environment()

import models
from auth.credits import (
    calculate_audit_credit_cost_for_policy_version,
    decrement_credits_atomic,
    increment_credits_atomic,
    is_billable_audit_outcome,
    is_retryable_integrity_error,
    should_decrement_credits,
)
from app.config.plans import can_use_feature
from app.services.advisor_plan_snapshot_service import (
    record_snapshot as record_advisor_plan_snapshot,
)
from app.services.advisor_view import attach_advisor_view
from audit_runner import canonical_score_breakdown, get_top_site_competitors, perform_audit
from cache_utils import build_audit_cache_key
from database import SessionLocal
from guest_audit_worker import guest_audit_worker_loop
from job_models import (
    JOB_STATUS_FAILED,
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_SUCCEEDED,
    AuditJobPayload,
    parse_job_payload,
)
from observability import (
    audit_db_retries_total,
    configure_logging,
    init_tracing,
    reset_request_id,
    set_request_id,
    tag_current_trace_with_request_id,
    worker_concurrent_jobs,
    worker_job_events_total,
    worker_job_wait_seconds,
    worker_queue_depth,
)
from services.queue_routing import (
    ALL_CONSUMER_QUEUES,
    QUEUE_FAST,
    resolve_queue_for_tier,
)
from operational_settings import (
    get_credit_engine_policy_version,
    is_ai_service_enabled,
    resolve_shadow_pricing_policy_version,
)
from services.ai_economics_ledger_service import record_ai_economics_ledger_entry
from services.ai_client import AIClient
from services.ai_engine import AIFactory
from services.audit_job_event_service import (
    append_stage_progress_event,
    build_audit_job_events_key,
)
from services.cost_forecast_service import (
    calculate_actual_audit_cost,
)
from services.network_analyzer import NetworkAnalysisService
from services.performance import PerformanceService
from services.performance_snapshots import PerformanceSnapshotService
from services.scraper import ScraperService
from services.hallucination_service import HallucinationService
from services.competitors.benchmark_service import CompetitorBenchmarkService
from services.competitors.provider_adapters import build_competitor_discovery_service
from services.predictive_intent_service import PredictiveIntentService
from services.query_taxonomy import normalize_intent_value, resolve_query_type
from services.site_entity_facts import SiteEntityFactService
from services.audit_credit_reconciliation_service import (
    resolve_audit_credit_resolution,
    resolve_shadow_audit_credit_cost,
)
from services.project_audit_scope import (
    AUDIT_PROJECT_SCOPE_COMPETITOR,
    declare_audit_project_scope,
    resolve_audit_project_scope,
)
from services.project_competitive_service import (
    MAX_PROJECT_COMPETITORS,
    build_project_competitor_request_id,
    ensure_project_competitor_snapshot_pending,
    mark_project_competitor_snapshot_failed,
    mark_project_competitor_snapshot_succeeded,
    maybe_queue_project_competitive_digest,
)
from services.project_task_service import sync_project_tasks
from services.audit_helpers import (
    competitor_lite_audit_is_denied as _competitor_lite_audit_is_denied,
    resolve_subscription_plan as _resolve_subscription_plan,
    resolve_plan_capabilities as _resolve_plan_capabilities,
    frontend_base_url as _frontend_base_url,
    build_audit_cost_forecast as _build_audit_cost_forecast,
    queue_notification as _queue_notification,
    queue_project_budget_notifications as _queue_project_budget_notifications,
    project_budget_settings_url as _project_budget_settings_url,
)
from services.signal_ingestion_service import SignalIngestionService
from services.debate_trace_service import debate_trace_service
from services.sitemap_crawler_service import SitemapCrawlerService
from services.ai_routing_policy import get_audit_tier_label
from services.pricing_policy_service import get_pricing_policy
from services.credit_hold_service import (
    acquire_credit_hold,
    release_credit_hold,
    settle_credit_hold,
)
from services.external_webhook_service import enqueue_external_webhook

logger = logging.getLogger(__name__)

QUEUE_NAME = os.getenv("AUDIT_QUEUE_NAME", "audit_jobs")
tracing_backend = init_tracing("audit-worker")

MAX_CONCURRENT_AUDITS = int(os.getenv("MAX_CONCURRENT_AUDITS", "4"))
JOB_TIMEOUT_FAST = int(os.getenv("AUDIT_JOB_TIMEOUT_FAST", "120"))
JOB_TIMEOUT_SMART = int(os.getenv("AUDIT_JOB_TIMEOUT_SMART", "600"))
JOB_TIMEOUT_DEEP = int(os.getenv("AUDIT_JOB_TIMEOUT_DEEP", "900"))

scraper_service = ScraperService()
ai_client = AIClient()
audit_consensus_ai_factory = AIFactory()
performance_service = PerformanceService()
performance_snapshot_service = PerformanceSnapshotService(performance_service)
network_service = NetworkAnalysisService()
hallucination_service = HallucinationService()
competitor_discovery_service = build_competitor_discovery_service()
competitor_benchmark_service = CompetitorBenchmarkService()
predictive_intent_service = PredictiveIntentService()
site_entity_fact_service = SiteEntityFactService()
signal_ingestion_service = SignalIngestionService()
sitemap_crawler_service = SitemapCrawlerService()

# Startup health: check scraper readiness
_firecrawl_ready = scraper_service.app is not None
logger.info(
    "Scraper health at startup: firecrawl=%s, fallback=available",
    "ready" if _firecrawl_ready else "unavailable (will use fallback)",
)

JOB_MAX_ATTEMPTS = int(os.getenv("AUDIT_JOB_MAX_ATTEMPTS", "3"))
JOB_RETRY_DELAY_SECONDS = float(os.getenv("AUDIT_JOB_RETRY_DELAY_SECONDS", "2"))
JOB_TIMEOUT_SECONDS = int(os.getenv("AUDIT_JOB_TIMEOUT_SECONDS", "900"))
METRICS_KEY = os.getenv("AUDIT_QUEUE_METRICS_KEY", "audit:metrics")
LITE_AUDIT_TOP_COMPETITORS = int(os.getenv("LITE_AUDIT_TOP_COMPETITORS", "3"))
LITE_AUDIT_COOLDOWN_SECONDS = int(os.getenv("LITE_AUDIT_COOLDOWN_SECONDS", "1800"))
LITE_AUDIT_REQUEST_PREFIX = "lite-refresh"
shutdown_requested = False
active_jobs = set()
HEARTBEAT_INTERVAL_SECONDS = 15
SCHEDULED_AUDIT_SWEEP_SECONDS = int(os.getenv("SCHEDULED_AUDIT_SWEEP_SECONDS", "60"))
SCHEDULED_AUDIT_BATCH_SIZE = int(os.getenv("SCHEDULED_AUDIT_BATCH_SIZE", "25"))
scheduled_audits_table_available: bool | None = None


def _resolve_job_timeout(tier: str | None) -> int:
    """Return the per-tier job timeout in seconds."""
    t = (tier or "").strip().lower()
    if t in ("deep", "deep_judgment"):
        return JOB_TIMEOUT_DEEP
    if t == "smart":
        return JOB_TIMEOUT_SMART
    return JOB_TIMEOUT_FAST


class InsufficientCreditsError(Exception):
    """Raised when the atomic credit decrement did not affect any row."""


class ProjectScanCapExceededError(Exception):
    """Raised when a project scan cap set after dispatch now blocks the job."""


DB_COMMIT_MAX_RETRIES = int(os.getenv("DB_COMMIT_MAX_RETRIES", "3"))


WORKER_AUDIT_CACHE_TTL_SECONDS = int(os.getenv("WORKER_AUDIT_CACHE_TTL_SECONDS", "21600"))


def _build_worker_audit_cache_key(job, resolved_job_url, resolved_target_type) -> str:
    """Cache key for a worker audit result. Mirrors the api_router cache so
    repeated audits of the same subject/provider/tier return an identical
    (consistent) report instead of recomputing the non-deterministic debate."""
    subject = (
        resolved_job_url or f"target:{resolved_target_type}:{getattr(job, 'target_name', '') or ''}"
    )
    requested_tier = str(getattr(job, "requested_tier", None) or job.tier or "")
    ctx_parts = [f"requested_tier:{requested_tier}"]
    if getattr(job, "project_id", None) is not None:
        ctx_parts.append(f"project:{job.project_id}")
    if getattr(job, "selected_models", None):
        ctx_parts.append(f"models:{','.join(job.selected_models)}")
    return build_audit_cache_key(subject, job.provider, job.tier, "|".join(ctx_parts))


async def _get_cached_audit_result(redis_client, cache_key):
    """Return (report, score_breakdown, measured_at) on cache hit, else None.

    ``measured_at`` is the ISO-8601 timestamp of when the cached content was
    actually computed (SIGV2-1235). It is ``None`` for cache entries written
    before this field existed; callers must treat that as "unknown", never as
    "now".
    """
    try:
        raw = await redis_client.get(cache_key)
        if not raw:
            return None
        entry = json.loads(raw)
        report = entry.get("report")
        scores = entry.get("scores")
        measured_at = entry.get("measured_at")
        measured_at = measured_at if isinstance(measured_at, str) and measured_at else None
        if isinstance(report, dict) and isinstance(scores, dict):
            return report, scores, measured_at
    except Exception as exc:
        logger.warning("Worker audit cache lookup failed: %s", exc)
    return None


def _resolve_cache_provenance_metadata(
    *, served_from_cache: bool, cached_measured_at: str | None, fresh_measured_at: datetime
) -> dict:
    """Build the honesty fields a cache hit must carry (SIGV2-1235): whether
    the response was served from cache, and WHEN the content was actually
    measured, distinct from when this particular response was served.

    A fresh (non-cache) run is measured right now, by definition. A cache hit
    is measured whenever the cached content was originally computed; if that
    is unknown (legacy cache entry written before this field existed), say so
    explicitly instead of defaulting to "now" and silently re-claiming
    freshness.
    """
    if served_from_cache:
        return {
            "served_from_cache": True,
            "measured_at": cached_measured_at,
            "measured_at_unknown": cached_measured_at is None,
        }
    return {
        "served_from_cache": False,
        "measured_at": fresh_measured_at.astimezone(timezone.utc).isoformat(),
        "measured_at_unknown": False,
    }


async def _store_cached_audit_result(
    redis_client, cache_key, full_report, score_breakdown, measured_at: datetime | None = None
) -> None:
    try:
        measured_at_iso = (
            (measured_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        )
        payload = json.dumps(
            {"report": full_report, "scores": score_breakdown, "measured_at": measured_at_iso}
        )
        await redis_client.set(cache_key, payload, ex=WORKER_AUDIT_CACHE_TTL_SECONDS)
    except Exception as exc:
        logger.warning("Worker audit cache store failed: %s", exc)


def _find_existing_audit_for_request(db: Session, user_id, request_id):
    """Return an existing audit for (user_id, request_id) or None.

    Used to make audit persistence idempotent: a retried job must not insert a
    second audit row for the same request_id.
    """
    if not request_id:
        return None
    return (
        db.query(models.Audit)
        .filter(
            models.Audit.user_id == user_id,
            models.Audit.request_id == request_id,
        )
        .first()
    )


def _normalize_intent_value(intent: str | None) -> str | None:
    return normalize_intent_value(intent)


@contextlib.contextmanager
def _worker_trace_context(job: AuditJobPayload):
    request_id = f"worker-{job.job_id}"
    token = set_request_id(request_id)
    tag_current_trace_with_request_id(request_id)
    try:
        yield
    finally:
        reset_request_id(token)


def _request_shutdown(signame: str) -> None:
    global shutdown_requested
    if shutdown_requested:
        logger.info("Shutdown already requested; ignoring %s", signame)
        return
    shutdown_requested = True
    logger.info("Received %s. Graceful shutdown requested.", signame)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _request_shutdown(s.name))
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame, s=sig: _request_shutdown(s.name))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scheduled_audits_table_exists(db: Session) -> bool:
    bind = db.get_bind()
    return inspect(bind).has_table("scheduled_audits")


def _set_scheduled_audits_table_availability(*, available: bool) -> None:
    global scheduled_audits_table_available

    if scheduled_audits_table_available is available:
        return

    scheduled_audits_table_available = available
    if available:
        logger.info("scheduled_audits table detected; resuming scheduled audit sweeps.")
    else:
        logger.warning(
            "Skipping scheduled audit sweep because scheduled_audits is unavailable; pending migrations may still be running."
        )


def _select_due_scheduled_audit_ids() -> list[int]:
    selection_db: Session | None = None
    try:
        selection_db = SessionLocal()
        if not _scheduled_audits_table_exists(selection_db):
            _set_scheduled_audits_table_availability(available=False)
            return []

        _set_scheduled_audits_table_availability(available=True)
        now = datetime.now(timezone.utc)
        return [
            int(schedule_id)
            for (schedule_id,) in (
                selection_db.query(models.ScheduledAudit.id)
                .filter(
                    models.ScheduledAudit.is_active,
                    models.ScheduledAudit.next_run_at <= now,
                )
                .order_by(models.ScheduledAudit.next_run_at.asc(), models.ScheduledAudit.id.asc())
                .limit(SCHEDULED_AUDIT_BATCH_SIZE)
                .all()
            )
        ]
    except Exception:
        logger.exception("Failed selecting due scheduled audits")
        return []
    finally:
        if selection_db is not None:
            selection_db.close()


# _queue_notification, _resolve_subscription_plan, _resolve_plan_capabilities
# are imported from services.audit_helpers (Item 24 unification).


def _ensure_site_capacity(user: models.User, db: Session) -> None:
    max_sites = _resolve_plan_capabilities(user).get("max_sites")
    if not isinstance(max_sites, int) or max_sites < 0:
        return

    sites_used = db.query(models.Site).filter(models.Site.user_id == user.id).count()
    if sites_used >= max_sites:
        raise HTTPException(
            status_code=403,
            detail=f"Site limit reached ({sites_used}/{max_sites}). Upgrade for more sites.",
        )


def _ensure_competitor_lite_allowed(user: models.User, category: str | None) -> None:
    # SIGV2-1126: the same rule the enqueue paths apply, re-checked here because
    # a job can sit in the queue across a downgrade. Only the refusal is local.
    if _competitor_lite_audit_is_denied(
        plan=_resolve_subscription_plan(user),
        category=category,
    ):
        raise HTTPException(status_code=403, detail="Feature available in Specialist")


def _is_non_retryable_http_status(status_code: int) -> bool:
    return 400 <= status_code < 500 and status_code not in {408, 425, 429}


def _build_site_url(site: models.Site) -> str:
    domain = (site.domain or "").strip().lower()
    return f"https://{domain}"


def _is_lite_job(job: AuditJobPayload) -> bool:
    return bool(job.request_id and job.request_id.startswith(f"{LITE_AUDIT_REQUEST_PREFIX}:"))


def _is_project_competitor_job(job: AuditJobPayload) -> bool:
    return job.project_competitor_id is not None and job.source_audit_id is not None


# _frontend_base_url, _build_audit_cost_forecast
# are imported from services.audit_helpers (Item 24 unification).


async def _enqueue_project_competitor_jobs(
    *,
    redis_client: async_redis.Redis,
    db: Session,
    source_job: AuditJobPayload,
    source_audit: models.Audit,
    project: models.Project | None,
    user: models.User,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "skipped",
        "reason": "not_applicable",
        "queued_jobs": [],
        "competitors": [],
    }
    if project is None or source_job.scheduled_audit_id is None:
        result["reason"] = "missing_project_or_schedule"
        return result
    if not bool(project.auto_competitor_audits_enabled):
        result["reason"] = "project_disabled"
        return result
    if not can_use_feature(_resolve_subscription_plan(user), "has_competitor_analysis"):
        result["reason"] = "plan_restricted"
        return result

    competitors = [
        competitor for competitor in project.competitors if competitor.auto_audit_enabled
    ]
    if not competitors:
        result["reason"] = "no_competitors"
        return result

    # SIGV2-1129: the fan-out is bounded by what the product allows a project to
    # track, re-checked here rather than trusted. The cap is enforced when a
    # competitor is added, but this loop reads rows, and rows can arrive from a
    # bulk replace, a legacy import or a direct write; one schedule must never
    # be able to queue an unbounded number of audits. The allowance cannot be
    # the bound here, because these jobs are deliberately not the customer's
    # scans.
    bounded_competitors = competitors[:MAX_PROJECT_COMPETITORS]
    dropped_competitors = competitors[MAX_PROJECT_COMPETITORS:]
    if dropped_competitors:
        logger.warning(
            "Project %s has %s auto-audit competitors, above the cap of %s; "
            "the scheduled competitor refresh for audit %s is bounded to the first %s.",
            project.id,
            len(competitors),
            MAX_PROJECT_COMPETITORS,
            source_audit.id,
            MAX_PROJECT_COMPETITORS,
        )
    competitors = bounded_competitors
    result["competitor_cap"] = MAX_PROJECT_COMPETITORS
    result["dropped_competitors"] = [competitor.id for competitor in dropped_competitors]
    # The customer's scan allowance is deliberately not consulted: a competitor
    # benchmark is Signal's own work to populate a comparison the plan already
    # includes, so it is never billed as one of their scans (SIGV2-1129).
    result["billed_as_customer_scans"] = False

    policy_version = get_credit_engine_policy_version(db)
    estimated_credit_cost = max(
        1,
        int(
            calculate_audit_credit_cost_for_policy_version(
                policy_version=policy_version,
                provider=source_job.provider,
                tier="fast",
                entities_count=0,
                category=str(source_job.category or "competitive benchmark"),
                market=source_job.market,
            )
        ),
    )
    payloads: list[dict[str, object]] = []
    job_ids: list[str] = []
    for competitor in competitors:
        ensure_project_competitor_snapshot_pending(
            db,
            project_id=project.id,
            competitor_id=competitor.id,
            source_audit_id=source_audit.id,
            metadata={
                "source": "scheduled_audit",
                "scheduled_audit_id": source_job.scheduled_audit_id,
            },
        )
        job_id = str(uuid4())
        request_id = build_project_competitor_request_id(
            source_audit_id=source_audit.id,
            competitor_id=competitor.id,
            job_id=job_id,
        )
        db.add(
            models.AuditJob(
                id=job_id,
                user_id=user.id,
                status=JOB_STATUS_QUEUED,
                audit_target_type=models.AuditTargetType.WEBSITE,
                target_name=competitor.target_url,
                target_url=competitor.target_url,
                target_metadata={},
                url=competitor.target_url,
                request_id=request_id,
                created_at=datetime.now(timezone.utc),
                # SIGV2-1129: Signal launched this benchmark, the customer did
                # not. It is never counted against their scan allowance.
                scan_origin=models.SCAN_ORIGIN_COMPETITOR_REFRESH,
            )
        )
        payload = AuditJobPayload(
            job_id=job_id,
            request_id=request_id,
            user_id=user.id,
            url=competitor.target_url,
            audit_target_type="website",
            target_name=competitor.target_url,
            target_url=competitor.target_url,
            target_metadata={},
            provider=source_job.provider,
            tier="fast",
            project_id=project.id,
            charge_credits=True,
            estimated_credit_cost=estimated_credit_cost,
            category=source_job.category or "competitive benchmark",
            market=source_job.market,
            language=source_job.language,
            source_audit_id=source_audit.id,
            project_competitor_id=competitor.id,
            project_scope=AUDIT_PROJECT_SCOPE_COMPETITOR,
        ).to_dict()
        payloads.append(payload)
        job_ids.append(job_id)

    db.commit()

    try:
        for payload in payloads:
            await redis_client.hset(
                f"audit:job:{payload['job_id']}",
                mapping={
                    "status": "queued",
                    "created_at": _now_iso(),
                    "url": str(payload["url"]),
                    "project_id": str(project.id),
                    "request_id": str(payload["request_id"]),
                    "source": "scheduled_competitive_refresh",
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
        logger.exception("Failed to enqueue project competitor jobs for audit %s", source_audit.id)
        for competitor in competitors:
            mark_project_competitor_snapshot_failed(
                db,
                project_id=project.id,
                competitor_id=competitor.id,
                source_audit_id=source_audit.id,
                reason=f"Failed to enqueue competitor benchmark job: {exc}",
            )
        (
            db.query(models.AuditJob)
            .filter(models.AuditJob.id.in_(job_ids))
            .update(
                {
                    models.AuditJob.status: JOB_STATUS_FAILED,
                    models.AuditJob.error: "Failed to enqueue competitor benchmark job.",
                    models.AuditJob.completed_at: datetime.now(timezone.utc),
                },
                synchronize_session=False,
            )
        )
        db.commit()
        result["reason"] = "enqueue_failed"
        return result

    result["status"] = "queued"
    result["reason"] = "queued"
    result["queued_jobs"] = [
        {
            "job_id": payload["job_id"],
            "competitor_id": payload["project_competitor_id"],
            "url": payload["url"],
        }
        for payload in payloads
    ]
    result["competitors"] = [
        {"id": competitor.id, "name": competitor.display_name, "url": competitor.target_url}
        for competitor in competitors
    ]
    result["estimated_credit_cost"] = estimated_credit_cost
    return result


async def _enqueue_competitor_lite_refresh_jobs(
    *,
    redis_client: async_redis.Redis,
    db: Session,
    source_job: AuditJobPayload,
    source_audit: models.Audit,
) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "skipped",
        "reason": "not_applicable",
        "enqueued_jobs": [],
        "target_sites": [],
        "cooldown_seconds": LITE_AUDIT_COOLDOWN_SECONDS,
    }
    if source_audit.site_id is None:
        result["reason"] = "missing_site"
        logger.info("Skipping lite refresh for audit %s: site_id missing", source_audit.id)
        return result

    # SIGV2-1129: bounded by the top-N limit and the per-site cooldown below.
    # These jobs are queued straight to Redis and never create an ``AuditJob``
    # row, so they are outside the scan allowance by construction; the limit and
    # the cooldown are what keeps the work finite.
    competitors = get_top_site_competitors(
        db, site_id=source_audit.site_id, limit=LITE_AUDIT_TOP_COMPETITORS
    )
    if not competitors:
        result["reason"] = "no_competitors"
        logger.info("Skipping lite refresh for audit %s: no competitors found", source_audit.id)
        return result

    cooldown_cutoff = datetime.now(timezone.utc) - timedelta(seconds=LITE_AUDIT_COOLDOWN_SECONDS)
    enqueued_jobs: list[dict[str, object]] = []
    skipped_sites: list[dict[str, object]] = []

    for competitor_site in competitors:
        cooldown_audit = (
            db.query(models.Audit)
            .filter(
                models.Audit.site_id == competitor_site.id,
                models.Audit.request_id.like(f"{LITE_AUDIT_REQUEST_PREFIX}:%"),
                models.Audit.created_at >= cooldown_cutoff,
            )
            .order_by(models.Audit.created_at.desc())
            .first()
        )
        if cooldown_audit is not None:
            skipped_sites.append(
                {
                    "site_id": competitor_site.id,
                    "domain": competitor_site.domain,
                    "reason": "cooldown",
                    "latest_audit_id": cooldown_audit.id,
                }
            )
            continue

        lite_job_id = str(uuid4())
        lite_request_id = (
            f"{LITE_AUDIT_REQUEST_PREFIX}:{source_audit.id}:{competitor_site.id}:{lite_job_id}"
        )
        payload = AuditJobPayload(
            job_id=lite_job_id,
            request_id=lite_request_id,
            user_id=source_job.user_id,
            url=_build_site_url(competitor_site),
            audit_target_type="website",
            target_name=_build_site_url(competitor_site),
            target_url=_build_site_url(competitor_site),
            target_metadata={},
            provider=source_job.provider,
            tier="lite",
            project_id=source_job.project_id,
            category=source_job.category,
            market=source_job.market,
            language=source_job.language,
            # SIGV2-1117: this measures a competitor's site, not the project's
            # own. It keeps the project linkage for attribution and cost, and
            # must never be counted in the project's own score history.
            project_scope=AUDIT_PROJECT_SCOPE_COMPETITOR,
        )
        job_key = f"audit:job:{lite_job_id}"
        await redis_client.hset(
            job_key,
            mapping={
                "status": "queued",
                "created_at": _now_iso(),
                "request_id": lite_request_id,
                "job_type": "lite_competitor_refresh",
                "source_audit_id": str(source_audit.id),
                "source_site_id": str(source_audit.site_id),
                "target_site_id": str(competitor_site.id),
            },
        )
        await redis_client.rpush(QUEUE_FAST, json.dumps(payload.to_dict()))
        from services.job_ttl_dlq_service import set_ttl_queued as _set_ttl_q

        await _set_ttl_q(redis_client, lite_job_id)
        enqueued_jobs.append(
            {
                "job_id": lite_job_id,
                "target_site_id": competitor_site.id,
                "target_domain": competitor_site.domain,
            }
        )

    result["target_sites"] = [{"site_id": site.id, "domain": site.domain} for site in competitors]
    result["skipped_sites"] = skipped_sites
    result["enqueued_jobs"] = enqueued_jobs
    result["enqueued_count"] = len(enqueued_jobs)
    result["status"] = "queued" if enqueued_jobs else "skipped"
    result["reason"] = "cooldown" if not enqueued_jobs else "queued"
    logger.info(
        "Lite competitor refresh for audit %s: status=%s enqueued=%s skipped=%s",
        source_audit.id,
        result["status"],
        len(enqueued_jobs),
        len(skipped_sites),
    )
    return result


async def handle_job(
    redis_client: async_redis.Redis,
    job: AuditJobPayload,
    *,
    job_attempt: int = 1,
) -> None:
    job_key = f"audit:job:{job.job_id}"
    job_timeout = _resolve_job_timeout(job.tier)
    if job_attempt <= 1:
        # First attempt starts with a clean evidence list; retries keep it so
        # reconnected clients can reconstruct earlier attempts (SIGV2-1021).
        await redis_client.delete(build_audit_job_events_key(job.job_id))

    async def _stage_progress_sink(payload: dict) -> None:
        await append_stage_progress_event(
            redis_client,
            job_id=job.job_id,
            payload={"attempt": job_attempt, **payload},
        )

    request_token = set_request_id(job.request_id or f"job-{job.job_id}")
    tag_current_trace_with_request_id(job.request_id or f"job-{job.job_id}")
    logger.info("Starting audit job %s (request_id=%s)", job.job_id, job.request_id)
    await redis_client.hset(
        job_key,
        mapping={
            "status": JOB_STATUS_RUNNING,
            "started_at": _now_iso(),
            "request_id": job.request_id,
            "provider": job.provider,
            "tier": job.tier,
            "project_id": str(job.project_id) if job.project_id is not None else "",
            "estimated_credit_cost": str(
                max(1, int(getattr(job, "estimated_credit_cost", 1) or 1))
            ),
        },
    )

    # Sync with DB for reliability sweeper
    db_status: Session = SessionLocal()
    try:
        db_job = db_status.query(models.AuditJob).filter(models.AuditJob.id == job.job_id).first()
        if db_job:
            target_type_value = (
                str(getattr(job, "audit_target_type", "website") or "website").strip().lower()
            )
            if target_type_value not in {"website", "brand"}:
                target_type_value = "website"
            job_url_value = str(getattr(job, "url", "") or "").strip()
            job_target_url_value = (
                str(getattr(job, "target_url", "") or "").strip() or job_url_value or None
            )
            db_job.status = JOB_STATUS_RUNNING
            db_job.started_at = datetime.now(timezone.utc)
            db_job.last_heartbeat = datetime.now(timezone.utc)
            db_job.error = None
            db_job.audit_target_type = models.AuditTargetType(target_type_value)
            db_job.target_name = (
                str(getattr(job, "target_name", "")).strip()
                or job_target_url_value
                or job_url_value
            )
            db_job.target_url = job_target_url_value
            db_job.target_metadata = (
                dict(getattr(job, "target_metadata", {}))
                if isinstance(getattr(job, "target_metadata", None), dict)
                else {}
            )
            db_job.provider = job.provider
            db_job.tier = job.tier
            db_job.project_id = job.project_id
            db_job.estimated_credit_cost = max(
                1, int(getattr(job, "estimated_credit_cost", 1) or 1)
            )
            db_status.commit()
    except Exception:
        logger.exception("Failed to update AuditJob status in DB")
    finally:
        db_status.close()

    active_jobs.add(job.job_id)

    db: Session | None = None
    user: models.User | None = None
    credit_hold: models.CreditHold | None = None
    credit_hold_request_id: str | None = None
    credit_hold_finalized = False
    audit_executed = False
    try:
        db = SessionLocal()
        with _worker_trace_context(job):
            user = db.query(models.User).filter(models.User.id == job.user_id).first()
            if user is None:
                raise ValueError(f"User {job.user_id} not found")
            active_policy_version = get_credit_engine_policy_version(db)
            project = None
            if job.project_id is not None:
                project = (
                    db.query(models.Project).filter(models.Project.id == job.project_id).first()
                )
            resolved_target_type = (
                str(getattr(job, "audit_target_type", "website") or "website").strip().lower()
            )
            if resolved_target_type not in {"website", "brand"}:
                resolved_target_type = "website"
            resolved_job_url = str(job.url or "").strip()
            resolved_target_url = (
                str(getattr(job, "target_url", "") or "").strip() or resolved_job_url or None
            )
            resolved_target_name = (
                str(getattr(job, "target_name", "") or "").strip()
                or resolved_target_url
                or resolved_job_url
                or ("Brand audit" if resolved_target_type == "brand" else None)
            )
            resolved_target_metadata = (
                dict(getattr(job, "target_metadata", {}))
                if isinstance(getattr(job, "target_metadata", None), dict)
                else {}
            )
            estimated_credit_cost = max(1, int(getattr(job, "estimated_credit_cost", 0) or 0))
            forecast_payload = (
                dict(getattr(job, "cost_forecast", {}))
                if isinstance(getattr(job, "cost_forecast", None), dict)
                else {}
            )
            if estimated_credit_cost <= 0 or not forecast_payload:
                estimated_credit_cost, forecast_payload = _build_audit_cost_forecast(
                    db=db,
                    requested_tier=str(getattr(job, "requested_tier", None) or job.tier or "fast"),
                    policy_version=active_policy_version,
                    provider=job.provider,
                    target_url=resolved_target_url or None,
                    target_name=resolved_target_name,
                    target_metadata=resolved_target_metadata,
                    category=job.category,
                    market=job.market,
                    language=job.language,
                    entities=job.entities,
                    selected_models=job.selected_models,
                )
            subscription_plan = _resolve_subscription_plan(user)
            _ensure_competitor_lite_allowed(user, job.category)
            should_consume_credit = bool(
                job.charge_credits and should_decrement_credits(user, job.tier)
            )
            if should_consume_credit:
                # Project scan cap (SIGV2-1102): the scan was already counted at
                # dispatch; block only if a cap set or lowered since then now
                # exceeds the counted usage.
                from services.project_budget_service import (
                    check_project_scan_capacity,
                    project_scan_cap_exceeded_detail,
                )

                budget_snapshot = (
                    check_project_scan_capacity(db, project_id=project.id)
                    if project is not None
                    else None
                )
                if (
                    project is not None
                    and budget_snapshot is not None
                    and budget_snapshot.monthly_limit_scans is not None
                    and budget_snapshot.consumed_scans > budget_snapshot.monthly_limit_scans
                ):
                    raise ProjectScanCapExceededError(
                        project_scan_cap_exceeded_detail(
                            project_name=project.name,
                            monthly_limit_scans=int(budget_snapshot.monthly_limit_scans),
                            period_end=budget_snapshot.current_period_end,
                        )
                    )
                pending_credit_hold_request_id = f"audit-job:{job.job_id}"
                acquire_credit_hold(
                    db,
                    user_id=user.id,
                    hold_amount=estimated_credit_cost,
                    request_id=pending_credit_hold_request_id,
                    reason_code="audit.main",
                    feature_key="audit.main",
                    tier_class=str(getattr(job, "tier_class", None) or job.tier or "fast"),
                    policy_version=active_policy_version,
                    workspace_id=project.workspace_id if project is not None else None,
                    project_id=job.project_id,
                    ttl_seconds=job_timeout + 300,
                    payload={
                        "queue_job_id": job.job_id,
                        "request_id": job.request_id,
                        "estimated_credit_cost": estimated_credit_cost,
                        "cost_forecast": forecast_payload,
                    },
                )
                credit_hold_request_id = pending_credit_hold_request_id
                db.commit()
                db.refresh(user)
            ai_service_enabled = is_ai_service_enabled(db)

            # --- Result cache lookup (consistency: identical re-runs return
            # the cached report instead of recomputing the non-deterministic
            # multi-agent debate) ---
            _audit_cache_key = _build_worker_audit_cache_key(
                job, resolved_job_url, resolved_target_type
            )
            _cached_audit = await _get_cached_audit_result(redis_client, _audit_cache_key)
            full_report = None
            score_breakdown = None
            _cached_measured_at: str | None = None
            if _cached_audit is not None:
                full_report, score_breakdown, _cached_measured_at = _cached_audit
                logger.info(
                    "[CACHE] audit cache hit for job %s (measured_at=%s)",
                    job.job_id,
                    _cached_measured_at or "unknown",
                )

            # --- Multi-Model Concurrent Execution ---
            _selected = job.selected_models or []
            if full_report is not None:
                pass
            elif len(_selected) >= 2:
                logger.info(
                    "Multi-model consensus audit: running %d models concurrently for job %s",
                    len(_selected),
                    job.job_id,
                )

                async def _run_single_model(provider: str):
                    return await perform_audit(
                        url=resolved_job_url,
                        provider=provider,
                        tier=job.tier,
                        job_id=job.job_id,
                        requested_tier=getattr(job, "requested_tier", None),
                        audit_target_type=resolved_target_type,
                        target_name=resolved_target_name,
                        target_metadata=resolved_target_metadata,
                        category=job.category,
                        market=job.market,
                        language=job.language,
                        entities=job.entities,
                        project_id=job.project_id,
                        scraper_service=scraper_service,
                        performance_service=performance_service,
                        network_service=network_service,
                        ai_client=ai_client,
                        ai_service_enabled=ai_service_enabled,
                        hallucination_service=hallucination_service,
                        competitor_discovery_service=competitor_discovery_service,
                        competitor_benchmark_service=competitor_benchmark_service,
                        user_plan=subscription_plan,
                        brand_truth_payload=job.brand_truth_payload,
                        db=db,
                        performance_snapshot_service=performance_snapshot_service,
                        predictive_intent_service=predictive_intent_service,
                        site_structure_summary=getattr(job, "site_structure_summary", None),
                        event_sink=_stage_progress_sink,
                    )

                tasks = [_run_single_model(provider) for provider in _selected]
                results = await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=job_timeout,
                )

                # Collect successful results
                per_model_reports: list[dict] = []
                for provider, result in zip(_selected, results):
                    if isinstance(result, Exception):
                        logger.error(
                            "Model %s failed in multi-model audit for job %s: %s",
                            provider,
                            job.job_id,
                            result,
                        )
                    else:
                        report, _scores = result
                        per_model_reports.append(
                            {"provider": provider, "analysis": report, "scores": _scores}
                        )

                if not per_model_reports:
                    raise RuntimeError(
                        f"All {len(_selected)} models failed for multi-model audit job {job.job_id}"
                    )

                # Synthesize with Gemini Pro
                synthesized = await audit_consensus_ai_factory.synthesize_multi_model_results(
                    per_model_reports=per_model_reports,
                )

                # Use the synthesized analysis as the full_report, derive scores from it
                full_report = (
                    synthesized
                    if isinstance(synthesized, dict)
                    else per_model_reports[0].get("analysis", {})
                )
                score_breakdown = canonical_score_breakdown(full_report)

                # Inject consensus metadata into the full report
                if isinstance(full_report, dict):
                    full_report["_multi_model_audit"] = {
                        "models_used": [r["provider"] for r in per_model_reports],
                        "models_failed": [
                            p for p, r in zip(_selected, results) if isinstance(r, Exception)
                        ],
                        "total_models": len(_selected),
                        "successful_models": len(per_model_reports),
                    }
            else:
                # --- Single-Model Path (backward compatible) ---
                full_report, score_breakdown = await asyncio.wait_for(
                    perform_audit(
                        url=resolved_job_url,
                        provider=job.provider,
                        tier=job.tier,
                        job_id=job.job_id,
                        requested_tier=getattr(job, "requested_tier", None),
                        audit_target_type=resolved_target_type,
                        target_name=resolved_target_name,
                        target_metadata=resolved_target_metadata,
                        category=job.category,
                        market=job.market,
                        language=job.language,
                        entities=job.entities,
                        project_id=job.project_id,
                        scraper_service=scraper_service,
                        performance_service=performance_service,
                        network_service=network_service,
                        ai_client=ai_client,
                        ai_service_enabled=ai_service_enabled,
                        hallucination_service=hallucination_service,
                        competitor_discovery_service=competitor_discovery_service,
                        competitor_benchmark_service=competitor_benchmark_service,
                        user_plan=subscription_plan,
                        brand_truth_payload=job.brand_truth_payload,
                        db=db,
                        performance_snapshot_service=performance_snapshot_service,
                        predictive_intent_service=predictive_intent_service,
                        site_structure_summary=getattr(job, "site_structure_summary", None),
                        event_sink=_stage_progress_sink,
                    ),
                    timeout=job_timeout,
                )
            audit_executed = True
            _fresh_measured_at = datetime.now(timezone.utc)
            await _stage_progress_sink({"event": "stage_started", "stage": "report"})
            if _cached_audit is None and isinstance(full_report, dict):
                await _store_cached_audit_result(
                    redis_client,
                    _audit_cache_key,
                    full_report,
                    score_breakdown,
                    measured_at=_fresh_measured_at,
                )
            _cache_provenance = _resolve_cache_provenance_metadata(
                served_from_cache=_cached_audit is not None,
                cached_measured_at=_cached_measured_at,
                fresh_measured_at=_fresh_measured_at,
            )

            display_tier = str(getattr(job, "tier_class", None) or job.tier or "").strip().lower()
            if display_tier not in {"fast", "deep"}:
                requested_tier = (
                    str(getattr(job, "requested_tier", None) or job.tier or "").strip().lower()
                )
                display_tier = (
                    "deep" if requested_tier in {"smart", "deep", "deep_judgment"} else "fast"
                )
            if isinstance(full_report, dict):
                full_report["target"] = {
                    "type": resolved_target_type,
                    "name": resolved_target_name,
                    "url": resolved_target_url or None,
                    "metadata": resolved_target_metadata,
                }
                report_metadata = dict(full_report.get("metadata") or {})
                requested_tier = (
                    str(
                        getattr(job, "requested_tier", None)
                        or report_metadata.get("requested_tier")
                        or job.tier
                        or "fast"
                    )
                    .strip()
                    .lower()
                )
                report_metadata["audit_target_type"] = resolved_target_type
                report_metadata["target_name"] = resolved_target_name
                report_metadata["target_url"] = resolved_target_url or None
                report_metadata["target_metadata"] = resolved_target_metadata
                report_metadata["tier"] = requested_tier
                report_metadata["requested_tier"] = requested_tier
                report_metadata["execution_tier"] = str(job.tier or "").strip().lower() or "fast"
                report_metadata["mode_label"] = str(
                    getattr(job, "mode_label", None)
                    or report_metadata.get("mode_label")
                    or get_audit_tier_label(requested_tier)
                ).strip()
                report_metadata["tier_class"] = display_tier
                if job.selected_models:
                    report_metadata["selected_models"] = list(job.selected_models)
                if getattr(job, "routing_feature_key", None):
                    report_metadata["routing_feature_key"] = str(job.routing_feature_key)
                if getattr(job, "routing_mode", None):
                    report_metadata["routing_mode"] = str(job.routing_mode)
                # SIGV2-1235: a cache hit must carry when the content was
                # actually measured, distinct from when this row is served
                # (created_at), instead of being silently stamped as a fresh
                # measurement.
                report_metadata.update(_cache_provenance)
                full_report["generated_at"] = _cache_provenance["measured_at"]
                if getattr(job, "routing_preferred_provider", None):
                    report_metadata["routing_preferred_provider"] = str(
                        job.routing_preferred_provider
                    )
                if getattr(job, "routing_reason", None):
                    report_metadata["routing_reason"] = str(job.routing_reason)
                full_report["metadata"] = report_metadata

            credit_resolution = resolve_audit_credit_resolution(
                full_report=full_report if isinstance(full_report, dict) else None,
                estimated_credit_cost=estimated_credit_cost,
                default_provider=job.provider,
                default_tier=str(getattr(job, "requested_tier", None) or job.tier),
                policy_version=active_policy_version,
                entities_count=len(job.entities or []),
                category=job.category,
                market=job.market,
                selected_models=job.selected_models,
            )
            if isinstance(full_report, dict):
                report_metadata = dict(full_report.get("metadata") or {})
                report_metadata["billing_provider"] = credit_resolution.billed_provider
                report_metadata["billing_tier"] = credit_resolution.billed_tier
                report_metadata["estimated_credit_cost"] = credit_resolution.estimated_credit_cost
                report_metadata["billable_credit_cost"] = credit_resolution.billable_credit_cost
                if forecast_payload:
                    report_metadata["cost_forecast"] = forecast_payload
                if (
                    credit_resolution.provider_changed
                    or credit_resolution.tier_changed
                    or credit_resolution.cost_changed
                ):
                    report_metadata["credit_cost_reconciled"] = True
                    report_metadata["credit_reconciliation_reason"] = (
                        credit_resolution.resolution_reason
                        or "final_provider_tier_differs_from_enqueued_estimate"
                    )
                full_report["metadata"] = report_metadata

            billable_outcome = is_billable_audit_outcome(full_report)
            precharged_job = not bool(job.charge_credits)
            consumed_credit_cost = 0
            new_audit = None
            resolved_project_id = job.project_id
            is_project_competitor = _is_project_competitor_job(job)
            resolved_project_scope = resolve_audit_project_scope(
                request_id=job.request_id,
                category=job.category,
                project_competitor_id=job.project_competitor_id,
                source_audit_id=job.source_audit_id,
                declared_scope=job.project_scope,
            )
            if resolved_project_id is not None:
                project_exists = (
                    db.query(models.Project.id)
                    .filter(models.Project.id == resolved_project_id)
                    .first()
                )
                if project_exists is None:
                    logger.warning(
                        "Project %s not found for queued job %s; audit will be stored without project linkage.",
                        resolved_project_id,
                        job.job_id,
                    )
                    resolved_project_id = None
            is_brand_no_url = resolved_target_type == "brand" and not resolved_job_url
            if should_consume_credit and credit_hold_request_id is not None:
                if billable_outcome:
                    credit_hold = settle_credit_hold(
                        db,
                        request_id=credit_hold_request_id,
                        final_amount=credit_resolution.billable_credit_cost,
                        payload={
                            "billed_provider": credit_resolution.billed_provider,
                            "billed_tier": credit_resolution.billed_tier,
                        },
                    )
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
                if isinstance(full_report, dict):
                    report_metadata = dict(full_report.get("metadata") or {})
                    report_metadata["credit_hold_id"] = int(credit_hold.id)
                    report_metadata["credit_hold_status"] = str(credit_hold.status)
                    report_metadata["locked_credit_cost"] = int(credit_hold.hold_amount or 0)
                    report_metadata["consumed_credit_cost"] = int(credit_hold.final_amount or 0)
                    report_metadata["released_credit_cost"] = int(credit_hold.refunded_amount or 0)
                    hold_payload = dict(credit_hold.payload_json or {})
                    if hold_payload.get("extra_charge_shortfall"):
                        report_metadata["credit_hold_shortfall"] = int(
                            hold_payload["extra_charge_shortfall"]
                        )
                    full_report["metadata"] = report_metadata
            for attempt in range(1, DB_COMMIT_MAX_RETRIES + 1):
                try:
                    site = None
                    if not is_brand_no_url and resolved_job_url:
                        domain = (
                            resolved_job_url.split("//", 1)[-1].split("/", 1)[0].strip().lower()
                        )
                        site = (
                            db.query(models.Site)
                            .filter(
                                models.Site.user_id == job.user_id, models.Site.domain == domain
                            )
                            .first()
                        )
                        if site is None:
                            _ensure_site_capacity(user, db)
                            site = models.Site(
                                user_id=job.user_id, domain=domain, display_name=domain
                            )
                            db.add(site)
                            db.flush()

                    existing_audit = _find_existing_audit_for_request(
                        db, job.user_id, job.request_id
                    )
                    new_audit = models.Audit(
                        user_id=job.user_id,
                        site_id=site.id if site is not None else None,
                        project_id=resolved_project_id,
                        project_scope=resolved_project_scope,
                        audit_type=(
                            models.AuditType.DEEP
                            if display_tier == "deep"
                            else models.AuditType.FAST
                        ),
                        audit_target_type=models.AuditTargetType(resolved_target_type),
                        target_name=resolved_target_name,
                        target_url=resolved_target_url,
                        target_metadata=resolved_target_metadata,
                        url=resolved_job_url or None,
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
                        request_id=job.request_id,
                    )
                    if existing_audit is not None:
                        # Idempotency: a retried job must not create a second
                        # audit row for the same request_id. Reuse the existing
                        # audit instead of inserting a duplicate.
                        logger.warning(
                            "Duplicate audit creation skipped for request_id=%s (existing audit id=%s)",
                            job.request_id,
                            existing_audit.id,
                        )
                        new_audit = existing_audit
                        # SIGV2-1117: a row written before project_scope existed
                        # carries no classification. Stamp it from this job so the
                        # reused row is still identified positively.
                        if not existing_audit.project_scope:
                            existing_audit.project_scope = resolved_project_scope
                            db.add(existing_audit)
                    else:
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
                            "Debate trace persistence failed for audit %s (job=%s)",
                            new_audit.id,
                            job.job_id,
                        )
                        db.refresh(new_audit)
                    if precharged_job and billable_outcome:
                        consumed_credit_cost = credit_resolution.estimated_credit_cost
                    if resolved_project_id is not None and not is_project_competitor:
                        sync_project_tasks(db, project_id=resolved_project_id)
                    try:
                        signal_ingestion_service.ingest_audit(
                            db=db,
                            audit=new_audit,
                            provider=job.provider,
                            tier_class=display_tier,
                            routing_mode=getattr(job, "routing_mode", None),
                        )
                        db.commit()
                    except Exception:
                        db.rollback()
                        logger.exception(
                            "Signal ingestion failed for audit %s (job=%s)",
                            new_audit.id,
                            job.job_id,
                        )
                        db.refresh(new_audit)
                    # R12: persist one snapshot of the deterministic Advisor plan
                    # per audit (progress/trend foundation). The plan is computed
                    # at response-time on a deep copy so the persisted full_report
                    # / canonical contract is never mutated, and the persistence is
                    # additive + fully defensive: a snapshot failure can NEVER break
                    # audit completion (record_snapshot swallows errors; this block
                    # rolls back and logs on any commit failure). No auto-execution.
                    try:
                        advisor_view = attach_advisor_view(
                            copy.deepcopy(full_report) if isinstance(full_report, dict) else None
                        )
                        advisor_plan = (
                            (advisor_view.get("metadata") or {}).get("advisor")
                            if isinstance(advisor_view, dict)
                            else None
                        )
                        if (
                            record_advisor_plan_snapshot(
                                db,
                                new_audit.id,
                                resolved_project_id,
                                advisor_plan,
                            )
                            is not None
                        ):
                            db.commit()
                    except Exception:
                        db.rollback()
                        logger.warning(
                            "Advisor plan snapshot failed for audit %s (job=%s)",
                            new_audit.id,
                            job.job_id,
                            exc_info=True,
                        )
                        db.refresh(new_audit)
                    break
                except HTTPException as exc:
                    db.rollback()
                    if exc.status_code == 402:
                        raise InsufficientCreditsError("insufficient credits") from exc
                    raise
                except IntegrityError as exc:
                    db.rollback()
                    if attempt < DB_COMMIT_MAX_RETRIES and is_retryable_integrity_error(exc):
                        audit_db_retries_total.labels("worker").inc()
                        logger.warning(
                            "Retrying handle_job commit for user %s after retryable integrity error (attempt=%s): %s",
                            job.user_id,
                            attempt,
                            exc,
                        )
                        continue
                    raise

            if new_audit is not None and precharged_job and billable_outcome:
                reconciled_consumed_cost, reconciliation_updated = (
                    _reconcile_precharged_audit_credits(
                        db=db,
                        job=job,
                        user_id=job.user_id,
                        estimated_credit_cost=credit_resolution.estimated_credit_cost,
                        billable_credit_cost=credit_resolution.billable_credit_cost,
                        billed_provider=credit_resolution.billed_provider,
                        billed_tier=credit_resolution.billed_tier,
                    )
                )
                consumed_credit_cost = reconciled_consumed_cost
                if reconciliation_updated:
                    db.commit()
                    db.refresh(user)

            if new_audit is not None and billable_outcome and consumed_credit_cost > 0:
                actual_cost = calculate_actual_audit_cost(
                    report=full_report if isinstance(full_report, dict) else None,
                    policy_version=active_policy_version,
                    feature_key="audit.main",
                )
                shadow_policy_version = None
                shadow_credits_charged = None
                debate_profile = (
                    str(
                        (
                            ((full_report.get("metadata") or {}).get("ai_generation") or {}).get(
                                "profile"
                            )
                        )
                    )
                    .strip()
                    .lower()
                    if isinstance(full_report, dict)
                    and isinstance(full_report.get("metadata"), dict)
                    and isinstance((full_report.get("metadata") or {}).get("ai_generation"), dict)
                    and ((full_report.get("metadata") or {}).get("ai_generation") or {}).get(
                        "profile"
                    )
                    else None
                )
                shadow_policy_version = resolve_shadow_pricing_policy_version(
                    db,
                    active_policy_version=active_policy_version,
                )
                if shadow_policy_version is not None:
                    shadow_credits_charged = resolve_shadow_audit_credit_cost(
                        full_report=full_report if isinstance(full_report, dict) else None,
                        policy_version=shadow_policy_version,
                        billed_provider=credit_resolution.billed_provider,
                        billed_tier=credit_resolution.billed_tier,
                        entities_count=len(job.entities or []),
                        category=job.category,
                        market=job.market,
                        selected_models=list(job.selected_models or []),
                    )

                record_ai_economics_ledger_entry(
                    db,
                    policy_version=active_policy_version,
                    feature_key="audit.main",
                    tier_class=display_tier,
                    routing_profile=str(getattr(job, "routing_mode", "") or ""),
                    provider=actual_cost.provider or credit_resolution.billed_provider,
                    model=actual_cost.model
                    or (
                        str((full_report.get("metadata") or {}).get("model", ""))
                        if isinstance(full_report, dict)
                        else None
                    ),
                    fallback_level=1
                    if str(getattr(job, "routing_mode", "")).lower().endswith("fallback")
                    else 0,
                    input_tokens=actual_cost.input_tokens,
                    output_tokens=actual_cost.output_tokens,
                    token_cost_usd=actual_cost.token_cost_usd,
                    infra_alloc_usd=actual_cost.infra_cost_usd,
                    orchestration_usd=actual_cost.orchestration_cost_usd,
                    retry_risk_usd=actual_cost.retry_risk_usd,
                    credits_charged=max(0, int(consumed_credit_cost)),
                    credit_unit_value_usd=get_pricing_policy(
                        active_policy_version
                    ).credit_value_usd,
                    request_id=job.request_id,
                    workspace_id=project.workspace_id if project is not None else None,
                    project_id=resolved_project_id,
                    user_id=job.user_id,
                    shadow_policy_version=shadow_policy_version,
                    shadow_credits_charged=shadow_credits_charged,
                    payload={
                        "billable_outcome": True,
                        "estimated_credit_cost": credit_resolution.estimated_credit_cost,
                        "billable_credit_cost": credit_resolution.billable_credit_cost,
                        "provider_changed": credit_resolution.provider_changed,
                        "tier_changed": credit_resolution.tier_changed,
                        "cost_changed": credit_resolution.cost_changed,
                        "selected_models": list(job.selected_models or []),
                        "requested_tier": getattr(job, "requested_tier", None),
                        "debate_profile": debate_profile,
                        "pricing_currency": actual_cost.pricing_currency,
                        "estimated_llm_cost_usd": forecast_payload.get("estimated_llm_cost_usd"),
                        "estimated_total_cogs_usd": forecast_payload.get(
                            "estimated_total_cogs_usd"
                        ),
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
                        "actual_total_cogs_usd": float(actual_cost.total_cogs_usd),
                        "actual_token_cost_usd": float(actual_cost.token_cost_usd),
                        "actual_usage_mode": actual_cost.usage_mode,
                        "actual_step_count": actual_cost.step_count,
                        "actual_steps": actual_cost.breakdown.get("steps", []),
                        "queue_job_id": job.job_id,
                        "hold_id": getattr(credit_hold, "id", None)
                        if should_consume_credit
                        else None,
                        "hold_status": getattr(credit_hold, "status", None)
                        if should_consume_credit
                        else None,
                        "hold_delta": (
                            int(getattr(credit_hold, "hold_amount", 0) or 0)
                            - int(getattr(credit_hold, "final_amount", 0) or 0)
                        )
                        if should_consume_credit
                        else None,
                    },
                )

            if new_audit is not None and is_project_competitor:
                assert job.project_competitor_id is not None
                assert job.source_audit_id is not None
                mark_project_competitor_snapshot_succeeded(
                    db,
                    project_id=project.id if project is not None else int(resolved_project_id or 0),
                    competitor_id=job.project_competitor_id,
                    source_audit_id=job.source_audit_id,
                    competitor_audit=new_audit,
                )
                if project is not None:
                    maybe_queue_project_competitive_digest(
                        db,
                        project=project,
                        source_audit_id=job.source_audit_id,
                        frontend_base_url=_frontend_base_url(),
                    )
                db.commit()
                db.refresh(new_audit)
            elif new_audit is not None and not _is_lite_job(job):
                lite_refresh_metadata = await _enqueue_competitor_lite_refresh_jobs(
                    redis_client=redis_client,
                    db=db,
                    source_job=job,
                    source_audit=new_audit,
                )
                competitive_refresh_metadata = await _enqueue_project_competitor_jobs(
                    redis_client=redis_client,
                    db=db,
                    source_job=job,
                    source_audit=new_audit,
                    project=project,
                    user=user,
                )
                report_metadata = dict((new_audit.full_report or {}).get("metadata") or {})
                report_metadata["lite_refresh"] = lite_refresh_metadata
                report_metadata["competitive_refresh"] = competitive_refresh_metadata
                new_audit.full_report = {
                    **(new_audit.full_report or {}),
                    "metadata": report_metadata,
                }
                db.add(new_audit)

                # Check for multi-model consensus
                _selected = job.selected_models or []
                is_consensus = len(_selected) >= 2
                template_key = "audit.consensus_ready" if is_consensus else "audit.completed"

                dashboard_base = os.getenv("FRONTEND_URL", "https://qiko.ai/signal")
                report_url = (
                    f"{dashboard_base}/dashboard/projects/{resolved_project_id}/reports/{new_audit.id}"
                    if resolved_project_id
                    else f"{dashboard_base}/dashboard/reports/{new_audit.id}"
                )

                email_ctx = {
                    "email": user.email,
                    "workspace_name": project.workspace.name
                    if project and project.workspace
                    else None,
                    "project_name": project.name if project is not None else None,
                    "language": (
                        project.language
                        if project is not None and isinstance(project.language, str)
                        else None
                    ),
                    "target_url": resolved_target_url,
                    "report_url": report_url,
                    "audit_tier": job.tier,
                    "geo_score": score_breakdown.get("geo", 0),
                    "seo_score": score_breakdown.get("seo", 0),
                    "aeo_score": score_breakdown.get("aeo", 0),
                }
                if is_consensus:
                    email_ctx["model_names_csv"] = ", ".join(_selected)

                _queue_notification(
                    db,
                    user=user,
                    to_email=user.email,
                    template_key=template_key,
                    context=email_ctx,
                    correlation_id=job.job_id,
                    workspace_id=project.workspace_id if project is not None else None,
                    project_id=resolved_project_id,
                )

                db.commit()
                db.refresh(new_audit)

            await _stage_progress_sink({"event": "stage_completed", "stage": "report"})
            await redis_client.hset(
                job_key,
                mapping={
                    "status": JOB_STATUS_SUCCEEDED,
                    "completed_at": _now_iso(),
                    "audit_id": str(new_audit.id),
                    "request_id": job.request_id,
                    "estimated_credit_cost": str(estimated_credit_cost),
                    "consumed_credit_cost": str(consumed_credit_cost),
                    "remaining_credits": str(int(user.credits or 0)),
                },
            )
            from services.job_ttl_dlq_service import set_ttl_succeeded

            await set_ttl_succeeded(redis_client, job.job_id)
            # Clear audit dedup key on success
            from services.audit_dedup_service import clear_dedup_for_job

            await clear_dedup_for_job(redis_client, job=job)
            logger.info(
                "Completed audit job %s (request_id=%s, audit_id=%s, served_from_cache=%s, measured_at=%s)",
                job.job_id,
                job.request_id,
                new_audit.id,
                _cache_provenance["served_from_cache"],
                _cache_provenance["measured_at"] or "unknown",
            )
            # Update DB AuditJob
            db_status: Session = SessionLocal()
            try:
                db_job = (
                    db_status.query(models.AuditJob)
                    .filter(models.AuditJob.id == job.job_id)
                    .first()
                )
                if db_job:
                    db_job.status = JOB_STATUS_SUCCEEDED
                    db_job.completed_at = datetime.now(timezone.utc)
                    db_job.error = None
                    db_job.provider = job.provider
                    db_job.tier = job.tier
                    db_job.project_id = resolved_project_id
                    db_job.estimated_credit_cost = estimated_credit_cost
                    db_job.consumed_credit_cost = consumed_credit_cost
                if job.scheduled_audit_id is not None:
                    scheduled_audit = (
                        db_status.query(models.ScheduledAudit)
                        .filter(models.ScheduledAudit.id == job.scheduled_audit_id)
                        .first()
                    )
                    if scheduled_audit is not None:
                        scheduled_audit.last_run_status = models.ScheduledAuditRunStatus.SUCCEEDED
                        scheduled_audit.last_job_id = job.job_id
                db_status.commit()
            except Exception:
                logger.exception("Failed to update AuditJob success in DB")
            finally:
                db_status.close()

            if job.sitemap_crawl_job_id:
                db_sitemap: Session = SessionLocal()
                try:
                    await sitemap_crawler_service.record_page_outcome(
                        db=db_sitemap,
                        crawl_job_id=job.sitemap_crawl_job_id,
                        success=True,
                        consumed_credit_cost=max(
                            1, int(consumed_credit_cost or estimated_credit_cost or 1)
                        ),
                    )
                except Exception:
                    db_sitemap.rollback()
                    logger.exception(
                        "Failed to update sitemap crawl progress for successful job %s (crawl=%s)",
                        job.job_id,
                        job.sitemap_crawl_job_id,
                    )
                finally:
                    db_sitemap.close()
            await enqueue_external_webhook(job.job_id)
    except Exception as exc:
        if db is not None:
            db.rollback()
        if credit_hold_request_id and not credit_hold_finalized:
            if not audit_executed:
                try:
                    if db is not None:
                        release_credit_hold(
                            db,
                            request_id=credit_hold_request_id,
                            refund_reason=f"pre_execution_failure:{type(exc).__name__}",
                        )
                        db.commit()
                        if user is not None:
                            db.refresh(user)
                except Exception:
                    if db is not None:
                        db.rollback()
                    logger.exception(
                        "Failed to release queue credit hold %s after pre-execution failure.",
                        credit_hold_request_id,
                    )
            else:
                logger.warning(
                    "Audit job %s failed after execution with pending credit hold %s still open.",
                    job.job_id,
                    credit_hold_request_id,
                )
        # Update DB AuditJob as failed
        db_status: Session = SessionLocal()
        try:
            db_job = (
                db_status.query(models.AuditJob).filter(models.AuditJob.id == job.job_id).first()
            )
            if db_job:
                db_job.status = JOB_STATUS_FAILED
                db_job.completed_at = datetime.now(timezone.utc)
                db_job.error = str(exc)
                db_job.provider = job.provider
                db_job.tier = job.tier
                db_job.project_id = job.project_id
                db_job.estimated_credit_cost = max(
                    1, int(getattr(job, "estimated_credit_cost", 1) or 1)
                )
                db_job.consumed_credit_cost = int(db_job.consumed_credit_cost or 0)
            if job.scheduled_audit_id is not None:
                scheduled_audit = (
                    db_status.query(models.ScheduledAudit)
                    .filter(models.ScheduledAudit.id == job.scheduled_audit_id)
                    .first()
                )
                if scheduled_audit is not None:
                    scheduled_audit.last_run_status = models.ScheduledAuditRunStatus.FAILED
                    scheduled_audit.last_job_id = job.job_id
            if (
                job.project_id is not None
                and job.project_competitor_id is not None
                and job.source_audit_id is not None
            ):
                project_row = (
                    db_status.query(models.Project)
                    .filter(models.Project.id == job.project_id)
                    .first()
                )
                mark_project_competitor_snapshot_failed(
                    db_status,
                    project_id=job.project_id,
                    competitor_id=job.project_competitor_id,
                    source_audit_id=job.source_audit_id,
                    reason=str(exc),
                )
                if project_row is not None:
                    maybe_queue_project_competitive_digest(
                        db_status,
                        project=project_row,
                        source_audit_id=job.source_audit_id,
                        frontend_base_url=_frontend_base_url(),
                    )
            db_status.commit()
        except Exception:
            logger.exception("Failed to update AuditJob failure in DB")
        finally:
            db_status.close()

        if job.sitemap_crawl_job_id:
            db_sitemap: Session = SessionLocal()
            try:
                await sitemap_crawler_service.record_page_outcome(
                    db=db_sitemap,
                    crawl_job_id=job.sitemap_crawl_job_id,
                    success=False,
                    error_message=str(exc),
                )
            except Exception:
                db_sitemap.rollback()
                logger.exception(
                    "Failed to update sitemap crawl progress for failed job %s (crawl=%s)",
                    job.job_id,
                    job.sitemap_crawl_job_id,
                )
            finally:
                db_sitemap.close()
        await enqueue_external_webhook(job.job_id)
        raise
    finally:
        active_jobs.discard(job.job_id)
        # Clear dedup key on any terminal outcome (catch-all for failures)
        try:
            from services.audit_dedup_service import clear_dedup_for_job as _clear_dedup_for_job

            await _clear_dedup_for_job(redis_client, job=job)
        except Exception:
            logger.debug(
                "Failed to clear dedup key for job %s in finally", job.job_id, exc_info=True
            )
        if db is not None:
            db.close()
        reset_request_id(request_token)


async def update_heartbeats():
    """Periodic task to update last_heartbeat for active jobs in DB and Redis."""
    while not shutdown_requested:
        if active_jobs:
            db: Session = SessionLocal()
            try:
                db.query(models.AuditJob).filter(models.AuditJob.id.in_(active_jobs)).update(
                    {"last_heartbeat": datetime.now(timezone.utc)}, synchronize_session=False
                )
                db.commit()
            except Exception:
                logger.exception("Failed to update audit heartbeats")
            finally:
                db.close()
            # Also update Redis hash heartbeat for each active job
            try:
                from core.redis_client import get_async_redis

                async with get_async_redis() as rc:
                    now_iso = _now_iso()
                    for jid in list(active_jobs):
                        await rc.hset(f"audit:job:{jid}", "last_heartbeat", now_iso)
                        from services.job_ttl_dlq_service import set_ttl_in_progress

                        await set_ttl_in_progress(rc, jid)
                    # Queue depth metrics
                    for q in ALL_CONSUMER_QUEUES:
                        depth = await rc.llen(q)
                        tier_label = q.rsplit(":", 1)[-1] if ":" in q else "legacy"
                        worker_queue_depth.labels(tier=tier_label).set(depth)
            except Exception:
                logger.debug("Failed to update Redis heartbeats", exc_info=True)
        await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)


def _normalize_scheduled_frequency(frequency: object | None) -> str:
    frequency_value = getattr(frequency, "value", frequency)
    normalized = str(frequency_value or "weekly").strip().lower()
    return normalized or "weekly"


def _compute_next_scheduled_run(
    *, frequency: object | None, anchor: datetime | None = None
) -> datetime:
    now = anchor or datetime.now(timezone.utc)
    if _normalize_scheduled_frequency(frequency) == "monthly":
        return now + relativedelta(months=1)
    return now + timedelta(days=7)


def _build_scheduled_request_id(schedule_id: int, job_id: str) -> str:
    return f"scheduled-audit:{schedule_id}:{job_id}"


def _scheduled_credit_adjustment_reason(
    *,
    scheduled_audit_id: int,
    job_id: str | None,
    delta: int,
    event: str,
) -> str:
    return json.dumps(
        {
            "kind": "scheduled_audit_credit_adjustment",
            "scheduled_audit_id": scheduled_audit_id,
            "job_id": job_id,
            "delta": delta,
            "event": event,
        },
        sort_keys=True,
    )


def _audit_credit_reconciliation_reason(
    *,
    job_id: str,
    request_id: str | None,
    scheduled_audit_id: int | None,
    estimated_credit_cost: int,
    billable_credit_cost: int,
    billed_provider: str,
    billed_tier: str,
    delta: int,
) -> str:
    return json.dumps(
        {
            "kind": "audit_credit_reconciliation",
            "job_id": job_id,
            "request_id": request_id,
            "scheduled_audit_id": scheduled_audit_id,
            "estimated_credit_cost": estimated_credit_cost,
            "billable_credit_cost": billable_credit_cost,
            "billed_provider": billed_provider,
            "billed_tier": billed_tier,
            "delta": delta,
        },
        sort_keys=True,
    )


def _reconcile_precharged_audit_credits(
    *,
    db: Session,
    job: AuditJobPayload,
    user_id: int,
    estimated_credit_cost: int,
    billable_credit_cost: int,
    billed_provider: str,
    billed_tier: str,
) -> tuple[int, bool]:
    estimated = max(1, int(estimated_credit_cost or 1))
    billable = max(1, int(billable_credit_cost or 1))
    delta = estimated - billable
    if delta == 0:
        return billable, False

    reason = _audit_credit_reconciliation_reason(
        job_id=job.job_id,
        request_id=job.request_id,
        scheduled_audit_id=job.scheduled_audit_id,
        estimated_credit_cost=estimated,
        billable_credit_cost=billable,
        billed_provider=billed_provider,
        billed_tier=billed_tier,
        delta=delta,
    )
    existing = (
        db.query(models.UserCreditAdjustment.id)
        .filter(
            models.UserCreditAdjustment.user_id == user_id,
            models.UserCreditAdjustment.reason == reason,
        )
        .first()
    )
    if existing is not None:
        return billable, False

    adjustment_applied = False
    if delta > 0:
        increment_credits_atomic(
            db,
            user_id,
            delta,
            reverse_commitment_usage=True,
        )
        adjustment_applied = True
    else:
        charge_amount = abs(delta)
        adjustment_applied = decrement_credits_atomic(
            db, user_id, charge_amount, allow_negative=True
        )
        if not adjustment_applied:
            logger.warning(
                "Could not apply downward credit reconciliation for job %s.",
                job.job_id,
            )

    if not adjustment_applied:
        return estimated, False

    db.add(
        models.UserCreditAdjustment(
            user_id=user_id,
            delta=delta,
            reason=reason,
        )
    )
    return billable, True


async def process_scheduled_audits(redis_client: async_redis.Redis) -> None:
    """Periodic task to sweep for due ScheduledAudit entries and queue them."""
    while not shutdown_requested:
        due_ids = _select_due_scheduled_audit_ids()

        for scheduled_id in due_ids:
            if shutdown_requested:
                break

            dispatch_db: Session | None = None
            payload: dict[str, object] | None = None
            job_key: str | None = None
            job_id: str | None = None
            estimated_cost = 0

            try:
                dispatch_db = SessionLocal()
                now = datetime.now(timezone.utc)
                scheduled_query = dispatch_db.query(models.ScheduledAudit).filter(
                    models.ScheduledAudit.id == scheduled_id
                )
                if dispatch_db.bind is not None and dispatch_db.bind.dialect.name != "sqlite":
                    scheduled_query = scheduled_query.with_for_update(skip_locked=True)
                scheduled = scheduled_query.first()
                if scheduled is None or not scheduled.is_active or scheduled.next_run_at > now:
                    continue

                user = (
                    dispatch_db.query(models.User)
                    .filter(models.User.id == scheduled.user_id)
                    .first()
                )
                if user is None:
                    continue

                capabilities = _resolve_plan_capabilities(user)
                dashboard_base = os.getenv("FRONTEND_URL", "https://qiko.ai/signal")
                billing_url = f"{dashboard_base}/dashboard/billing"

                if not bool(capabilities.get("can_schedule_audits", False)):
                    logger.info(
                        "Pausing scheduled audit %s: user %s plan lost capability.",
                        scheduled.id,
                        user.id,
                    )
                    scheduled.is_active = False
                    scheduled.paused_reason = models.ScheduledAuditPauseReason.PLAN_RESTRICTED
                    scheduled.last_run_status = models.ScheduledAuditRunStatus.PAUSED
                    _queue_notification(
                        dispatch_db,
                        user=user,
                        to_email=user.email,
                        template_key="audit.schedule_paused",
                        context={
                            "email": user.email,
                            "target_url": scheduled.url,
                            "current_plan": _resolve_subscription_plan(user),
                            "billing_url": billing_url,
                        },
                        correlation_id=f"sched-plan-{scheduled.id}-{int(now.timestamp())}",
                        workspace_id=None,
                        project_id=scheduled.project_id,
                    )
                    dispatch_db.commit()
                    continue

                from app.schemas.scheduling import resolve_scheduled_audit_target_contract

                audit_params = dict(scheduled.audit_params or {})
                try:
                    resolved_schedule = resolve_scheduled_audit_target_contract(
                        url=scheduled.url,
                        project_id=scheduled.project_id,
                        site_id=scheduled.site_id,
                        audit_params=audit_params,
                    )
                except ValueError as exc:
                    logger.warning(
                        "Pausing scheduled audit %s due to invalid target contract: %s",
                        scheduled.id,
                        exc,
                    )
                    scheduled.is_active = False
                    scheduled.paused_reason = models.ScheduledAuditPauseReason.MANUAL
                    scheduled.last_run_status = models.ScheduledAuditRunStatus.PAUSED
                    dispatch_db.commit()
                    continue

                sched_config = resolved_schedule["audit_params"]
                normalized_audit_params = sched_config.model_dump()
                if scheduled.url != resolved_schedule["url"]:
                    scheduled.url = resolved_schedule["url"]
                if scheduled.audit_params != normalized_audit_params:
                    scheduled.audit_params = normalized_audit_params
                sched_target_type = sched_config.audit_target_type
                sched_target_name = sched_config.target_name
                sched_target_metadata = sched_config.target_metadata or {}
                sched_url = str(resolved_schedule["url"] or "").strip()
                provider = str(sched_config.provider or "google").strip().lower() or "google"
                tier = str(sched_config.tier or "fast").strip().lower() or "fast"
                category = str(sched_config.category or "").strip() or None
                market = str(sched_config.market or "").strip() or None
                language = str(sched_config.language or "").strip() or None
                entities = [
                    str(entity).strip() for entity in sched_config.entities if str(entity).strip()
                ]
                selected_models = [
                    str(model).strip().lower()
                    for model in sched_config.selected_models
                    if str(model).strip()
                ]
                brand_truth_payload = sched_config.brand_truth_payload

                active_policy_version = get_credit_engine_policy_version(dispatch_db)
                estimated_cost, forecast_payload = _build_audit_cost_forecast(
                    db=dispatch_db,
                    requested_tier=tier,
                    policy_version=active_policy_version,
                    provider=provider,
                    target_url=sched_url or None,
                    target_name=sched_target_name or sched_url or None,
                    target_metadata=sched_target_metadata,
                    category=category,
                    market=market,
                    language=language,
                    entities=entities,
                    selected_models=selected_models,
                )

                scheduled_project = None
                if scheduled.project_id is not None:
                    scheduled_project = (
                        dispatch_db.query(models.Project)
                        .filter(models.Project.id == scheduled.project_id)
                        .first()
                    )

                if scheduled_project is not None:
                    from services.project_budget_service import consume_project_scan

                    scan_result = consume_project_scan(dispatch_db, project_id=scheduled_project.id)
                    if scan_result.status == "budget_exceeded":
                        logger.warning(
                            "Scan cap reached for scheduled audit %s (project=%s). Pausing.",
                            scheduled.id,
                            scheduled.project_id,
                        )
                        scheduled.is_active = False
                        scheduled.paused_reason = models.ScheduledAuditPauseReason.BUDGET_EXCEEDED
                        scheduled.last_run_status = models.ScheduledAuditRunStatus.PAUSED
                        _queue_notification(
                            dispatch_db,
                            user=user,
                            to_email=user.email,
                            template_key="budget.exceeded",
                            context={
                                "email": user.email,
                                "project_name": scheduled_project.name,
                                "workspace_name": scheduled_project.workspace.name
                                if scheduled_project.workspace is not None
                                else "Workspace",
                                "consumed_scans": scan_result.consumed_scans,
                                "monthly_limit_scans": scan_result.monthly_limit_scans or 0,
                                "settings_url": _project_budget_settings_url(scheduled_project.id),
                            },
                            correlation_id=f"sched-budget-{scheduled.id}-{int(now.timestamp())}",
                            workspace_id=scheduled_project.workspace_id,
                            project_id=scheduled.project_id,
                        )
                        dispatch_db.commit()
                        continue
                    _queue_project_budget_notifications(
                        dispatch_db,
                        project=scheduled_project,
                        consumed_scans=scan_result.consumed_scans,
                        monthly_limit_scans=scan_result.monthly_limit_scans,
                        percent_consumed=scan_result.percent_consumed,
                        threshold_events=scan_result.threshold_events,
                    )

                # SIGV2-1024/SIGV2-1102: internal accounting only; a shortfall
                # books a negative balance instead of pausing the scheduled audit.
                decrement_credits_atomic(dispatch_db, user.id, estimated_cost, allow_negative=True)

                dispatch_db.refresh(user)
                job_id = str(uuid4())
                request_id = _build_scheduled_request_id(scheduled.id, job_id)
                dispatch_db.add(
                    models.UserCreditAdjustment(
                        user_id=user.id,
                        delta=-estimated_cost,
                        reason=_scheduled_credit_adjustment_reason(
                            scheduled_audit_id=scheduled.id,
                            job_id=job_id,
                            delta=-estimated_cost,
                            event="scheduled_dispatch",
                        ),
                    )
                )
                sched_display_name = sched_target_name or sched_url or "Brand audit"
                dispatch_db.add(
                    models.AuditJob(
                        id=job_id,
                        user_id=user.id,
                        status=JOB_STATUS_QUEUED,
                        audit_target_type=models.AuditTargetType(sched_target_type),
                        target_name=sched_display_name,
                        target_url=sched_url or None,
                        target_metadata=sched_target_metadata,
                        url=sched_url,
                        request_id=request_id,
                        created_at=now,
                        # SIGV2-1129: the customer configured this schedule for
                        # their own target, so the run is their scan and counts
                        # exactly as a manual launch does.
                        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
                    )
                )

                scheduled.last_run_at = now
                scheduled.last_run_status = models.ScheduledAuditRunStatus.QUEUED
                scheduled.last_job_id = job_id
                scheduled.next_run_at = _compute_next_scheduled_run(
                    frequency=scheduled.frequency,
                    anchor=now,
                )
                scheduled.paused_reason = None

                payload = AuditJobPayload(
                    job_id=job_id,
                    request_id=request_id,
                    user_id=user.id,
                    url=sched_url,
                    audit_target_type=sched_target_type,
                    target_name=sched_display_name,
                    target_url=sched_url or None,
                    target_metadata=sched_target_metadata,
                    provider=provider,
                    tier=tier,
                    project_id=scheduled.project_id,
                    scheduled_audit_id=scheduled.id,
                    charge_credits=False,
                    estimated_credit_cost=estimated_cost,
                    cost_forecast=forecast_payload,
                    brand_truth_payload=brand_truth_payload,
                    category=category,
                    market=market,
                    language=language,
                    entities=entities or None,
                    selected_models=selected_models or None,
                    # SIGV2-1121: a scheduled audit measures the project's own
                    # target unless the schedule itself asks for a competitor
                    # lite audit. The dispatcher declares it either way.
                    project_scope=declare_audit_project_scope(category=category),
                ).to_dict()
                job_key = f"audit:job:{job_id}"
                dispatch_db.commit()
            except Exception:
                if dispatch_db is not None:
                    dispatch_db.rollback()
                logger.exception("Failed preparing scheduled audit %s", scheduled_id)
                continue
            finally:
                if dispatch_db is not None:
                    dispatch_db.close()

            if payload is None or job_key is None or job_id is None:
                continue

            try:
                await redis_client.hset(
                    job_key,
                    mapping={
                        "status": "queued",
                        "created_at": _now_iso(),
                        "url": str(payload.get("url") or ""),
                        "project_id": str(payload.get("project_id") or ""),
                        "request_id": str(payload.get("request_id") or ""),
                        "source": "scheduled_audit",
                        "scheduled_audit_id": str(scheduled_id),
                        "estimated_credit_cost": str(estimated_cost),
                        "estimated_cost_usd": str(
                            forecast_payload.get("estimated_total_cogs_usd") or ""
                        ),
                    },
                )
                await redis_client.rpush(
                    resolve_queue_for_tier(str(payload.get("tier", "fast"))), json.dumps(payload)
                )
                from services.job_ttl_dlq_service import set_ttl_queued as _stq

                await _stq(redis_client, job_id)
            except Exception:
                logger.exception("Failed to enqueue scheduled audit %s", scheduled_id)
                refund_db: Session | None = None
                try:
                    refund_db = SessionLocal()
                    refund_now = datetime.now(timezone.utc)
                    increment_credits_atomic(
                        refund_db,
                        int(payload["user_id"]),
                        estimated_cost,
                        reverse_commitment_usage=True,
                    )
                    refund_db.add(
                        models.UserCreditAdjustment(
                            user_id=int(payload["user_id"]),
                            delta=estimated_cost,
                            reason=_scheduled_credit_adjustment_reason(
                                scheduled_audit_id=scheduled_id,
                                job_id=job_id,
                                delta=estimated_cost,
                                event="enqueue_refund",
                            ),
                        )
                    )
                    db_job = (
                        refund_db.query(models.AuditJob)
                        .filter(models.AuditJob.id == job_id)
                        .first()
                    )
                    if db_job is not None:
                        db_job.status = JOB_STATUS_FAILED
                        db_job.completed_at = refund_now
                        db_job.error = "Failed to enqueue scheduled audit job."
                    scheduled = (
                        refund_db.query(models.ScheduledAudit)
                        .filter(models.ScheduledAudit.id == scheduled_id)
                        .first()
                    )
                    if scheduled is not None:
                        scheduled.last_run_status = models.ScheduledAuditRunStatus.FAILED
                        scheduled.next_run_at = refund_now + timedelta(minutes=5)
                    refund_db.commit()
                except Exception:
                    if refund_db is not None:
                        refund_db.rollback()
                    logger.exception(
                        "Failed to refund scheduled audit %s after enqueue failure",
                        scheduled_id,
                    )
                finally:
                    if refund_db is not None:
                        refund_db.close()

        await asyncio.sleep(SCHEDULED_AUDIT_SWEEP_SECONDS)


async def _process_job_with_retries(
    redis_client: async_redis.Redis,
    semaphore: asyncio.Semaphore,
    payload: dict,
    job: AuditJobPayload,
) -> None:
    """Process a single audit job with retry logic. Runs as a concurrent task."""
    try:
        attempts = 0
        while attempts < JOB_MAX_ATTEMPTS:
            if shutdown_requested:
                logger.info(
                    "Shutdown requested. Stopping retries for job %s after %s attempt(s).",
                    job.job_id,
                    attempts,
                )
                break
            attempts += 1
            attempt_started_at = time.monotonic()
            if attempts == 1:
                await redis_client.hincrby(METRICS_KEY, "jobs_started", 1)
                worker_job_events_total.labels("started").inc()
                worker_job_events_total.labels("cache_miss").inc()
            await redis_client.hincrby(METRICS_KEY, "job_attempts_total", 1)
            if attempts > 1:
                await redis_client.hincrby(METRICS_KEY, "job_retries", 1)
                worker_job_events_total.labels("retry").inc()
            await redis_client.hset(
                f"audit:job:{job.job_id}",
                mapping={
                    "attempts": str(attempts),
                    "last_attempt_at": _now_iso(),
                },
            )
            try:
                await handle_job(redis_client, job, job_attempt=attempts)
                await redis_client.hincrby(METRICS_KEY, "jobs_succeeded", 1)
                worker_job_events_total.labels("success").inc()
                await redis_client.hincrbyfloat(
                    METRICS_KEY,
                    "job_duration_seconds_total",
                    time.monotonic() - attempt_started_at,
                )
                break
            except (InsufficientCreditsError, ProjectScanCapExceededError) as exc:
                logger.info("Job %s stopped due to business failure: %s", job.job_id, exc)
                await redis_client.hincrbyfloat(
                    METRICS_KEY,
                    "job_duration_seconds_total",
                    time.monotonic() - attempt_started_at,
                )
                await redis_client.hincrby(METRICS_KEY, "jobs_failed", 1)
                worker_job_events_total.labels("failure").inc()
                await redis_client.hset(
                    f"audit:job:{job.job_id}",
                    mapping={
                        "status": JOB_STATUS_FAILED,
                        "completed_at": _now_iso(),
                        "error": str(exc),
                    },
                )
                from services.job_ttl_dlq_service import (
                    set_ttl_failed as _stf_biz,
                    push_to_dlq as _pdlq_biz,
                )

                await _stf_biz(redis_client, job.job_id)
                await _pdlq_biz(
                    redis_client,
                    job_id=job.job_id,
                    original_payload=payload,
                    error=str(exc),
                    retry_count=attempts,
                )
                break
            except asyncio.TimeoutError:
                tier_timeout = _resolve_job_timeout(job.tier)
                logger.warning(
                    "Job %s timed out on attempt %s (tier=%s, timeout=%ds)",
                    job.job_id,
                    attempts,
                    job.tier,
                    tier_timeout,
                )
                await redis_client.hincrbyfloat(
                    METRICS_KEY,
                    "job_duration_seconds_total",
                    time.monotonic() - attempt_started_at,
                )
                if attempts >= JOB_MAX_ATTEMPTS:
                    await redis_client.hincrby(METRICS_KEY, "jobs_failed", 1)
                    worker_job_events_total.labels("failure").inc()
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "status": JOB_STATUS_FAILED,
                            "completed_at": _now_iso(),
                            "error": f"Timeout after {tier_timeout}s (tier={job.tier})",
                        },
                    )
                    from services.job_ttl_dlq_service import (
                        set_ttl_failed as _stf_to,
                        push_to_dlq as _pdlq_to,
                    )

                    await _stf_to(redis_client, job.job_id)
                    await _pdlq_to(
                        redis_client,
                        job_id=job.job_id,
                        original_payload=payload,
                        error=f"Timeout after {tier_timeout}s (tier={job.tier})",
                        retry_count=attempts,
                    )
                else:
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "last_error": f"Timeout after {tier_timeout}s",
                        },
                    )
                    if shutdown_requested:
                        logger.info(
                            "Shutdown requested. Skipping timeout retry delay for job %s.",
                            job.job_id,
                        )
                        break
                    await asyncio.sleep(JOB_RETRY_DELAY_SECONDS)
            except HTTPException as exc:
                logger.warning(
                    "Job %s returned HTTPException on attempt %s: status=%s detail=%s",
                    job.job_id,
                    attempts,
                    exc.status_code,
                    exc.detail,
                )
                await redis_client.hincrbyfloat(
                    METRICS_KEY,
                    "job_duration_seconds_total",
                    time.monotonic() - attempt_started_at,
                )
                if _is_non_retryable_http_status(exc.status_code):
                    await redis_client.hincrby(METRICS_KEY, "jobs_failed", 1)
                    worker_job_events_total.labels("failure").inc()
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "status": JOB_STATUS_FAILED,
                            "completed_at": _now_iso(),
                            "error": str(exc.detail),
                        },
                    )
                    from services.job_ttl_dlq_service import (
                        set_ttl_failed as _stf_h1,
                        push_to_dlq as _pdlq_h1,
                    )

                    await _stf_h1(redis_client, job.job_id)
                    await _pdlq_h1(
                        redis_client,
                        job_id=job.job_id,
                        original_payload=payload,
                        error=str(exc.detail),
                        retry_count=attempts,
                    )
                    break
                if attempts >= JOB_MAX_ATTEMPTS:
                    await redis_client.hincrby(METRICS_KEY, "jobs_failed", 1)
                    worker_job_events_total.labels("failure").inc()
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "status": JOB_STATUS_FAILED,
                            "completed_at": _now_iso(),
                            "error": str(exc.detail),
                        },
                    )
                    from services.job_ttl_dlq_service import (
                        set_ttl_failed as _stf_h2,
                        push_to_dlq as _pdlq_h2,
                    )

                    await _stf_h2(redis_client, job.job_id)
                    await _pdlq_h2(
                        redis_client,
                        job_id=job.job_id,
                        original_payload=payload,
                        error=str(exc.detail),
                        retry_count=attempts,
                    )
                else:
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "last_error": str(exc.detail),
                        },
                    )
                    if shutdown_requested:
                        logger.info(
                            "Shutdown requested. Skipping retry delay for job %s.",
                            job.job_id,
                        )
                        break
                    await asyncio.sleep(JOB_RETRY_DELAY_SECONDS)
            except Exception as exc:
                logger.exception("Job %s failed attempt %s: %s", job.job_id, attempts, exc)
                await redis_client.hincrbyfloat(
                    METRICS_KEY,
                    "job_duration_seconds_total",
                    time.monotonic() - attempt_started_at,
                )
                if attempts >= JOB_MAX_ATTEMPTS:
                    await redis_client.hincrby(METRICS_KEY, "jobs_failed", 1)
                    worker_job_events_total.labels("failure").inc()
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "status": JOB_STATUS_FAILED,
                            "completed_at": _now_iso(),
                            "error": str(exc),
                        },
                    )
                    from services.job_ttl_dlq_service import (
                        set_ttl_failed as _stf_g,
                        push_to_dlq as _pdlq_g,
                        build_dlq_payload_from_exception,
                    )

                    await _stf_g(redis_client, job.job_id)
                    dlq_kw = build_dlq_payload_from_exception(
                        job_id=job.job_id, original_payload=payload, exc=exc, retry_count=attempts
                    )
                    await _pdlq_g(redis_client, **dlq_kw)
                else:
                    await redis_client.hset(
                        f"audit:job:{job.job_id}",
                        mapping={
                            "last_error": str(exc),
                        },
                    )
                    if shutdown_requested:
                        logger.info(
                            "Shutdown requested. Skipping retry delay for job %s.",
                            job.job_id,
                        )
                        break
                    await asyncio.sleep(JOB_RETRY_DELAY_SECONDS)
    finally:
        semaphore.release()
        worker_concurrent_jobs.dec()


async def worker_loop() -> None:
    redis_client = get_async_redis_client()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    logger.info(
        "Audit worker listening on queues %s (max_concurrent=%d)",
        ALL_CONSUMER_QUEUES,
        MAX_CONCURRENT_AUDITS,
    )
    logger.info("Tracing backend initialized: %s", tracing_backend)

    # BUG-024: Log source-code fingerprint at startup so operators can detect stale runtimes.
    try:
        _runner_path = Path(__file__).resolve().parent / "audit_runner.py"
        _runner_mtime = datetime.fromtimestamp(
            _runner_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
        logger.info("audit_runner.py mtime: %s  (worker PID %s)", _runner_mtime, os.getpid())
    except Exception:
        logger.warning("Could not read audit_runner.py mtime for freshness check.")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_AUDITS)
    pending_tasks: set[asyncio.Task] = set()

    # Start heartbeat and cron tasks
    heartbeat_task = asyncio.create_task(update_heartbeats())
    cron_task = asyncio.create_task(process_scheduled_audits(redis_client))
    # Public guest audits run here too, on their own queue and their own
    # concurrency budget: they are not AuditJobs (no user, no credits, a
    # freemium payload instead of a full report) so they get a separate
    # consumer rather than another branch of the audit queue.
    guest_audit_redis = get_async_redis_client()
    guest_audit_task = asyncio.create_task(
        guest_audit_worker_loop(
            guest_audit_redis,
            should_stop=lambda: shutdown_requested,
        )
    )

    try:
        while not shutdown_requested:
            # Backpressure: wait for capacity before consuming from the queue.
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if shutdown_requested:
                semaphore.release()
                break

            result = await redis_client.blpop(ALL_CONSUMER_QUEUES, timeout=2)
            if not result:
                semaphore.release()
                continue

            source_queue_raw, payload_raw = result
            source_queue = (
                source_queue_raw.decode()
                if isinstance(source_queue_raw, bytes)
                else str(source_queue_raw)
            )

            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                semaphore.release()
                logger.warning("Invalid payload from %s: %s", source_queue, payload_raw)
                from services.job_ttl_dlq_service import push_to_dlq

                await push_to_dlq(
                    redis_client,
                    job_id="unknown-parse-error",
                    original_payload={"raw": str(payload_raw)[:2000]},
                    error="JSONDecodeError: invalid job payload",
                )
                continue

            try:
                job = parse_job_payload(payload)
            except ValueError as exc:
                semaphore.release()
                logger.warning("Invalid payload from %s: %s", source_queue, exc)
                from services.job_ttl_dlq_service import push_to_dlq as _push_dlq

                await _push_dlq(
                    redis_client,
                    job_id=payload.get("job_id", "unknown-validation-error"),
                    original_payload=payload,
                    error=f"Payload validation error: {exc}",
                )
                continue

            # Track job wait time (time from enqueue to pop)
            try:
                created_at_str = await redis_client.hget(f"audit:job:{job.job_id}", "created_at")
                if created_at_str:
                    _ca = (
                        created_at_str.decode()
                        if isinstance(created_at_str, bytes)
                        else str(created_at_str)
                    )
                    wait_secs = (
                        datetime.now(timezone.utc) - datetime.fromisoformat(_ca)
                    ).total_seconds()
                    worker_job_wait_seconds.observe(max(0, wait_secs))
            except Exception:
                pass

            worker_concurrent_jobs.inc()
            task = asyncio.create_task(
                _process_job_with_retries(redis_client, semaphore, payload, job),
                name=f"audit-job-{job.job_id}",
            )
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

        # Graceful shutdown: wait for in-progress jobs to complete
        if pending_tasks:
            logger.info(
                "Graceful shutdown: waiting for %d in-progress job(s)...", len(pending_tasks)
            )
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            logger.info("All in-progress jobs completed.")
        logger.info("Worker loop exited after graceful shutdown request.")
    finally:
        heartbeat_task.cancel()
        cron_task.cancel()
        # The guest consumer is not cancelled: it observes shutdown_requested
        # and drains its in-flight audits first, because that work has
        # already been paid for.
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task
            await cron_task
        with contextlib.suppress(Exception):
            await guest_audit_task
        with contextlib.suppress(Exception):
            await guest_audit_redis.aclose()
        await redis_client.aclose()
        logger.info("Redis connection closed. Worker shutdown complete.")


if __name__ == "__main__":
    configure_logging()
    asyncio.run(worker_loop())
