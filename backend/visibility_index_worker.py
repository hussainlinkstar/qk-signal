from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func

from core.env_bootstrap import bootstrap_environment
from core.redis_client import get_async_redis_client

bootstrap_environment()

from database import SessionLocal
import models
from observability import configure_logging, init_tracing, visibility_worker_events_total
from services.ai_search_volatility_service import AISearchVolatilityService
from services.visibility_index_jobs import VisibilityIndexJobService, load_prompt_templates_from_env
from services.visibility_refresh_service import (
    REFRESH_JOB_KIND,
    REFRESH_SCHEDULE_KEY,
    reconcile_orphaned_refresh_leases,
    refresh_lease_key,
)

logger = logging.getLogger(__name__)

VISIBILITY_QUEUE_NAME = os.getenv("VISIBILITY_QUEUE_NAME", "visibility_index_jobs")
VISIBILITY_TOPICS = [
    v.strip() for v in os.getenv("VISIBILITY_TOPICS", "seo software").split(",") if v.strip()
]
VISIBILITY_PROVIDERS = [
    v.strip() for v in os.getenv("VISIBILITY_PROVIDERS", "openai").split(",") if v.strip()
]
VISIBILITY_SCHEDULE_SECONDS = int(os.getenv("VISIBILITY_SCHEDULE_SECONDS", "3600"))
VOLATILITY_INDEX_ENABLED = os.getenv("VOLATILITY_INDEX_ENABLED", "true").strip().lower() not in {
    "0",
    "false",
    "no",
}
VOLATILITY_PROVIDERS = [
    v.strip()
    for v in os.getenv("VOLATILITY_PROVIDERS", "google,bing,perplexity").split(",")
    if v.strip()
]
VOLATILITY_SCHEDULE_SECONDS = int(os.getenv("VOLATILITY_SCHEDULE_SECONDS", "86400"))
VOLATILITY_SEED_QUERY_LIMIT = int(os.getenv("VOLATILITY_SEED_QUERY_LIMIT", "500"))
shutdown_requested = False


def _normalize_target_domain(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    try:
        parsed = urlparse(normalized if "://" in normalized else f"https://{normalized}")
        hostname = (parsed.hostname or "").strip().lower().rstrip(".")
    except Exception:
        hostname = normalized.rstrip(".")
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname or None


def _request_shutdown(signame: str) -> None:
    global shutdown_requested
    shutdown_requested = True
    logger.info("Visibility worker received %s, shutting down.", signame)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _request_shutdown(s.name))
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame, s=sig: _request_shutdown(s.name))


async def _run_batch_for(
    topic: str,
    provider: str,
    schedule_key: str,
    project_id: int | None = None,
    target_domain: str | None = None,
    charge_user_id: int | None = None,
    charge_credits: bool = False,
    audit_job_id: str | None = None,
) -> None:
    db = SessionLocal()
    service = VisibilityIndexJobService()
    try:
        templates = load_prompt_templates_from_env()
        batch = await service.execute_batch(
            db=db,
            topic=topic,
            provider=provider,
            prompt_templates=templates,
            schedule_key=schedule_key,
            project_id=project_id,
            target_domain=target_domain,
            charge_user_id=charge_user_id,
            charge_credits=charge_credits,
            audit_job_id=audit_job_id,
        )
        logger.info(
            "Visibility batch completed id=%s project_id=%s topic=%s provider=%s target_domain=%s status=%s score=%s",
            batch.id,
            project_id,
            topic,
            provider,
            batch.target_domain,
            batch.status,
            batch.score,
        )
    except Exception as exc:
        visibility_worker_events_total.labels("batch_error").inc()
        logger.exception(
            "Visibility batch failed project_id=%s topic=%s provider=%s target_domain=%s schedule_key=%s error=%s",
            project_id,
            topic,
            provider,
            target_domain,
            schedule_key,
            exc,
        )
    finally:
        db.close()


def _last_scheduled_measurement_at(
    db, project_id: int, *, target_domains: list[str] | None = None
) -> datetime | None:
    """The freshest batch the scheduled sweep produced for this project.

    Refresh batches (``schedule_key="queued"``), scan-linked batches
    (``audit_job_id`` set) and volatility seed batches are all excluded: none
    of them is the scheduled measurement a plan's cadence paces.

    ``target_domains`` narrows the clock to a set of domains, which is what
    makes the own-domain and competitor cadences independent (SIGV2-1208). A
    single project-wide clock would let last night's competitor run postpone
    this morning's own-domain run, and vice versa. ``None`` for the own-domain
    clock of a project with no domain recorded is matched explicitly, since
    those batches carry a NULL target.
    """
    query = db.query(func.max(models.VisibilityRunBatch.created_at)).filter(
        models.VisibilityRunBatch.project_id == project_id,
        models.VisibilityRunBatch.audit_job_id.is_(None),
        models.VisibilityRunBatch.schedule_key != "",
        models.VisibilityRunBatch.schedule_key != REFRESH_SCHEDULE_KEY,
        ~models.VisibilityRunBatch.schedule_key.like("volatility:%"),
    )
    if target_domains is not None:
        if target_domains:
            query = query.filter(models.VisibilityRunBatch.target_domain.in_(target_domains))
        else:
            query = query.filter(models.VisibilityRunBatch.target_domain.is_(None))
    return query.scalar()


def _interval_elapsed(last_run: datetime | None, interval: int, now: datetime) -> bool:
    """Whether ``interval`` seconds have passed since ``last_run``.

    Never measured means due: a project that has never been swept must not
    wait out an interval it has no start point for.
    """
    if last_run is None:
        return True
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=timezone.utc)
    return (now - last_run).total_seconds() >= interval


def _project_competitor_domains(project) -> list[str]:
    """The project's competitor domains, normalized and deduplicated."""
    domains: list[str] = []
    primary = _normalize_target_domain(project.domain_url)
    for competitor in list(project.competitors or []):
        domain = _normalize_target_domain(
            str(competitor.normalized_domain or competitor.target_url or "")
        )
        if domain and domain != primary and domain not in domains:
            domains.append(domain)
    return domains


def _load_project_visibility_jobs(
    db, project_id: int | None = None, *, scheduled: bool = False
) -> list[tuple[int, int | None, str, str, str | None]]:
    """Every (project, prompt, provider, target domain) cell worth measuring.

    ``project_id`` narrows the enumeration to one project, which is what a
    Signal-initiated refresh needs (SIGV2-1182). ``scheduled`` marks the
    periodic sweep, which SIGV2-1188 scopes further: a project is due only when
    its plan's cadence has elapsed since its last scheduled measurement, only
    the engines its plan includes are run regardless of what a stored prompt
    names, and only the prompts inside the plan cap are measured (a downgrade
    suspends the rest without deleting them).

    SIGV2-1208 gives competitor domains their own, slower cadence inside the
    same sweep. The two clocks are independent and each is read against its own
    domains, so the own domain can be due while the competitors are not and the
    other way round. A plan without competitor analysis has no competitor
    cadence at all: its competitor cells stay measurable on-demand only, which
    is where SIGV2-1188 left every plan.
    """
    from services.project_visibility_service import (
        ProjectVisibilityService,
        plan_competitor_sweep_interval_seconds,
        plan_sweep_interval_seconds,
    )

    jobs: list[tuple[int, int | None, str, str, str | None]] = []
    query_filters = [models.ProjectVisibilityQuery.is_active.is_(True)]
    if project_id is not None:
        query_filters.append(models.ProjectVisibilityQuery.project_id == int(project_id))
    queries = (
        db.query(models.ProjectVisibilityQuery)
        .filter(*query_filters)
        .order_by(
            models.ProjectVisibilityQuery.project_id.asc(), models.ProjectVisibilityQuery.id.asc()
        )
        .all()
    )
    if not queries:
        return jobs

    project_ids = sorted({int(query.project_id) for query in queries})
    projects = db.query(models.Project).filter(models.Project.id.in_(project_ids)).all()
    project_by_id = {project.id: project for project in projects}
    service = ProjectVisibilityService(db)
    entitlements_by_project: dict[int, dict] = {}
    measured_by_project: dict[int, set[int]] = {}
    due_by_project: dict[int, tuple[bool, bool]] = {}
    now = datetime.now(timezone.utc)
    seen: set[tuple[int, str, str, str | None]] = set()

    for query in queries:
        project = project_by_id.get(query.project_id)
        if project is None:
            continue

        entitlements = entitlements_by_project.get(project.id)
        if entitlements is None:
            entitlements = service.resolve_entitlements(project)
            entitlements_by_project[project.id] = entitlements
        plan_providers = set(entitlements["allowed_providers"])

        primary_domain = _normalize_target_domain(project.domain_url)
        competitor_domains = _project_competitor_domains(project)

        include_primary = True
        include_competitors = True
        if scheduled:
            if project.id not in due_by_project:
                own_interval = plan_sweep_interval_seconds(entitlements["plan"])
                own_due = _interval_elapsed(
                    _last_scheduled_measurement_at(
                        db,
                        project.id,
                        target_domains=[primary_domain] if primary_domain else [],
                    ),
                    own_interval,
                    now,
                )
                competitor_interval = plan_competitor_sweep_interval_seconds(entitlements["plan"])
                competitor_due = (
                    bool(competitor_domains)
                    and competitor_interval is not None
                    and _interval_elapsed(
                        _last_scheduled_measurement_at(
                            db, project.id, target_domains=competitor_domains
                        ),
                        competitor_interval,
                        now,
                    )
                )
                due_by_project[project.id] = (own_due, competitor_due)
            include_primary, include_competitors = due_by_project[project.id]
            if not include_primary and not include_competitors:
                continue

        # The cap applies to the cheapest-to-serve interpretation in both the
        # sweep and a refresh: the first N active prompts in creation order are
        # the measured set, and an over-cap prompt (post-downgrade) stays
        # unmeasured but undeleted.
        if project.id not in measured_by_project:
            measured_by_project[project.id] = service.measured_query_ids(project=project)
        if query.id not in measured_by_project[project.id]:
            continue

        providers = [
            str(value).strip().lower()
            for value in list(query.providers or [])
            if str(value).strip()
        ]
        # The plan's roster decides which engines run, not the row: a stored
        # prompt naming an engine the plan does not include is skipped here,
        # which also covers prompts written before the roster existed.
        providers = [provider for provider in providers if provider in plan_providers]
        if not providers:
            continue

        target_domains: list[str | None] = []
        if include_primary and primary_domain:
            target_domains.append(primary_domain)
        if include_competitors:
            for competitor_domain in competitor_domains:
                if competitor_domain not in target_domains:
                    target_domains.append(competitor_domain)

        if not target_domains:
            if not include_primary:
                # A competitor-only window on a project whose competitors have
                # all gone: nothing is due, and an untargeted batch would be a
                # measurement of nobody.
                continue
            target_domains = [None]

        charge_user_id = project.workspace.owner_id if project.workspace is not None else None
        for provider in providers:
            for target_domain in target_domains:
                dedupe_key = (query.project_id, query.query_text, provider, target_domain)
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                jobs.append(
                    (query.project_id, charge_user_id, query.query_text, provider, target_domain)
                )
    return jobs


async def _run_project_refresh(
    *,
    project_id: int,
    schedule_key: str,
    lease_key: str | None,
    redis_client,
    audit_job_id: str | None = None,
) -> int:
    """Measure one project's prompts now, then release its refresh lease.

    The payload names only the project, so the prompt list is read here, when
    the refresh starts: a prompt the customer added while this job was still
    sitting on the queue is measured by this same run, which is what makes one
    coalesced refresh per project honest (SIGV2-1182).

    Signal started this run, so it is never charged: ``charge_credits`` stays
    ``False`` and no ``charge_user_id`` is passed, unlike the hourly sweep.
    Scan allowance is untouched either way, since no ``AuditJob`` exists here.

    The lease is released in a ``finally`` so the next prompt addition can queue
    a fresh run as soon as this one is done, rather than waiting out the TTL.
    Only this project's own lease key is deletable, so a malformed payload
    cannot name somebody else's key.
    """
    executed = 0
    try:
        db = SessionLocal()
        try:
            cells = _load_project_visibility_jobs(db, project_id=project_id)
        finally:
            db.close()

        if not cells:
            logger.info(
                "Visibility refresh for project_id=%s has no active prompts to measure",
                project_id,
            )
            return 0

        for _project_id, _charge_user_id, topic, provider, target_domain in cells:
            await _run_batch_for(
                topic=topic,
                provider=provider,
                schedule_key=schedule_key,
                project_id=project_id,
                target_domain=target_domain,
                charge_user_id=None,
                charge_credits=False,
                # Carries the scan that asked for this measurement, when one
                # did. Without it the batches exist but belong to no scan,
                # which is why every scan-scoped consumer returned nothing.
                audit_job_id=audit_job_id,
            )
            executed += 1
        return executed
    finally:
        if lease_key and lease_key == refresh_lease_key(project_id):
            try:
                await redis_client.delete(lease_key)
            except Exception:
                logger.warning(
                    "Could not release visibility refresh lease for project_id=%s",
                    project_id,
                    exc_info=True,
                )


def _load_volatility_seed_jobs(db) -> list[tuple[str, str]]:
    service = AISearchVolatilityService(db)
    rows = service.list_seed_queries(limit=VOLATILITY_SEED_QUERY_LIMIT, auto_seed=True)
    return [
        (str(row.query_text).strip(), str(row.industry or "general").strip().lower())
        for row in rows
        if str(row.query_text or "").strip()
    ]


async def run_worker() -> None:
    redis_client = get_async_redis_client()
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    # SIGV2-1234: a lease this worker (or a predecessor killed by the same
    # deploy) took but never released leaves the project unable to scan for
    # up to REFRESH_LEASE_SECONDS. A restart is exactly when that orphan can
    # exist, so reconcile once before the main loop starts.
    db = SessionLocal()
    try:
        released = reconcile_orphaned_refresh_leases(db)
    finally:
        db.close()
    if released:
        logger.warning(
            "Startup reconciliation released %s orphaned visibility refresh lease(s): %s",
            len(released),
            released,
        )

    logger.info(
        "Visibility worker started queue=%s schedule=%ss",
        VISIBILITY_QUEUE_NAME,
        VISIBILITY_SCHEDULE_SECONDS,
    )
    last_scheduled_run = 0.0
    last_volatility_run = 0.0
    try:
        while not shutdown_requested:
            result = await redis_client.blpop(VISIBILITY_QUEUE_NAME, timeout=3)
            if result:
                _, payload_raw = result
                try:
                    payload = json.loads(payload_raw)
                    if str(payload.get("kind") or "").strip() == REFRESH_JOB_KIND:
                        # Signal-initiated project refresh (SIGV2-1182): the
                        # prompts are enumerated at execution time, not at
                        # enqueue time.
                        visibility_worker_events_total.labels("job_received").inc()
                        refresh_audit_job_id = payload.get("audit_job_id")
                        await _run_project_refresh(
                            project_id=int(payload["project_id"]),
                            schedule_key=str(payload.get("schedule_key") or REFRESH_SCHEDULE_KEY),
                            lease_key=(
                                str(payload["lease_key"])
                                if payload.get("lease_key") is not None
                                else None
                            ),
                            redis_client=redis_client,
                            audit_job_id=(
                                str(refresh_audit_job_id)
                                if refresh_audit_job_id is not None
                                else None
                            ),
                        )
                    else:
                        topic = str(payload["topic"]).strip()
                        provider = str(payload["provider"]).strip().lower()
                        schedule_key = str(payload.get("schedule_key") or "queued")
                        project_id = payload.get("project_id")
                        target_domain = _normalize_target_domain(payload.get("target_domain"))
                        charge_user_id = payload.get("charge_user_id")
                        charge_credits = bool(payload.get("charge_credits", False))
                        audit_job_id = payload.get("audit_job_id")
                        visibility_worker_events_total.labels("job_received").inc()
                        await _run_batch_for(
                            topic=topic,
                            provider=provider,
                            schedule_key=schedule_key,
                            project_id=int(project_id) if project_id is not None else None,
                            target_domain=target_domain,
                            charge_user_id=(
                                int(charge_user_id) if charge_user_id is not None else None
                            ),
                            charge_credits=charge_credits,
                            audit_job_id=(str(audit_job_id) if audit_job_id is not None else None),
                        )
                except Exception as exc:
                    visibility_worker_events_total.labels("job_invalid").inc()
                    logger.warning("Invalid visibility job payload '%s': %s", payload_raw, exc)

            now = time.monotonic()
            if now - last_scheduled_run >= VISIBILITY_SCHEDULE_SECONDS:
                schedule_key = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
                for topic in VISIBILITY_TOPICS:
                    for provider in VISIBILITY_PROVIDERS:
                        await _run_batch_for(
                            topic=topic, provider=provider, schedule_key=schedule_key
                        )
                db = SessionLocal()
                try:
                    # SIGV2-1188: the tick stays hourly, but each project is
                    # due only on its own plan's cadence and measures on its
                    # plan's engine roster. SIGV2-1208: competitor domains ride
                    # the same sweep on their own slower cadence, so a tick can
                    # return the own domain, the competitors, both or neither.
                    for (
                        project_id,
                        charge_user_id,
                        topic,
                        provider,
                        target_domain,
                    ) in _load_project_visibility_jobs(db, scheduled=True):
                        await _run_batch_for(
                            topic=topic,
                            provider=provider,
                            schedule_key=schedule_key,
                            project_id=project_id,
                            target_domain=target_domain,
                            charge_user_id=charge_user_id,
                            charge_credits=charge_user_id is not None,
                        )
                finally:
                    db.close()
                last_scheduled_run = now

            if (
                VOLATILITY_INDEX_ENABLED
                and now - last_volatility_run >= VOLATILITY_SCHEDULE_SECONDS
            ):
                schedule_key = f"volatility:{datetime.now(timezone.utc).strftime('%Y%m%d')}"
                db = SessionLocal()
                try:
                    seed_jobs = _load_volatility_seed_jobs(db)
                finally:
                    db.close()

                if seed_jobs:
                    logger.info(
                        "Starting global volatility sampling jobs seeds=%s providers=%s schedule_key=%s",
                        len(seed_jobs),
                        len(VOLATILITY_PROVIDERS),
                        schedule_key,
                    )
                for topic, _industry in seed_jobs:
                    for provider in VOLATILITY_PROVIDERS:
                        await _run_batch_for(
                            topic=topic,
                            provider=provider,
                            schedule_key=schedule_key,
                        )

                db = SessionLocal()
                try:
                    written_rows = AISearchVolatilityService(db).rebuild_snapshots_for_date(
                        run_date=datetime.now(timezone.utc).date()
                    )
                    db.commit()
                    logger.info(
                        "Volatility snapshot refresh completed schedule_key=%s rows_written=%s",
                        schedule_key,
                        written_rows,
                    )
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Volatility snapshot refresh failed for schedule_key=%s", schedule_key
                    )
                finally:
                    db.close()
                last_volatility_run = now
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    configure_logging()
    init_tracing("visibility-worker")
    asyncio.run(run_worker())
