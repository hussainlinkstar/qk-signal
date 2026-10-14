import asyncio
import logging
import os
import signal
import time
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_

from database import SessionLocal
import models
from observability import (
    configure_logging,
    cron_sweep_duration_seconds,
    cron_sweep_errors_total,
    cron_sweep_last_success_timestamp,
    cron_sweep_runs_total,
    init_tracing,
)
from operational_settings import get_report_retention_days
from services.credit_commitment_service import (
    collect_warning_candidates,
    report_pending_commitment_overages,
)
from services.credit_hold_service import expire_stale_holds
from services.credit_reconciliation_service import run_credit_reconciliation_sweep
from services.email_service import EmailService
from services.s3_storage_service import get_storage_service, resolve_report_retention_days
from services.project_competitive_service import (
    mark_project_competitor_snapshot_failed,
    maybe_queue_project_competitive_digest,
    parse_project_competitor_request_id,
)
from services.project_progress_service import generate_pending_project_progress_reports
from services.benchmark_engine import BenchmarkEngine
from services.signal_ingestion_service import SignalIngestionService
from services.project_bot_log_analyzer_service import refresh_recent_bot_log_daily_summaries
from services.project_offpage_mentions_service import (
    refresh_recent_off_page_mention_daily_summaries,
)
from services.ai_search_volatility_service import refresh_recent_global_volatility_snapshots
from services.trial_feedback_service import queue_feedback_requests_for_completed_trials
from services.trial_service import (
    transition_expired_trial_to_explorer,
    refresh_explorer_credits,
    STARTER_PLAN,
)
from services.model_lifecycle_monitor_service import run_model_lifecycle_check
from services.tier_duration_stats_service import recompute_tier_duration_stats
from services.workspace_rbac import user_can_access_project
from alert_evaluator import evaluate_admin_alerts
from services.alert_service import evaluate_due_project_alerts
from metrics_snapshot_worker import collect_metrics_snapshot
from core.config import settings
from core.redis_client import get_async_redis

logger = logging.getLogger("cron_sweeper")

# ── Sweep configuration ──────────────────────────────────────────────────────

SWEEP_INTERVAL_SECONDS = int(os.getenv("CRON_SWEEP_INTERVAL_SECONDS", "60"))
HEARTBEAT_KEY = "cron_sweeper:heartbeat"
LOCK_KEY = "cron_sweeper:lock"
WORKER_ID = f"sweeper-{uuid.uuid4().hex[:8]}"

# Per-tier intervals (seconds). Tasks are grouped into frequency tiers.
TIER_FAST = int(os.getenv("CRON_TIER_FAST_SECONDS", "60"))
TIER_STANDARD = int(os.getenv("CRON_TIER_STANDARD_SECONDS", "300"))
TIER_SLOW = int(os.getenv("CRON_TIER_SLOW_SECONDS", "3600"))
TIER_DAILY = int(os.getenv("CRON_TIER_DAILY_SECONDS", "86400"))

STALE_HEARTBEAT_THRESHOLD = timedelta(minutes=5)
STALE_QUEUED_THRESHOLD = timedelta(hours=1)

# ── Graceful shutdown ─────────────────────────────────────────────────────────

shutdown_requested = False


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


# ── Per-tier interval tracking ────────────────────────────────────────────────

_tier_last_run: dict[str, float] = {}


def _should_run_tier(tier: str, interval: int) -> bool:
    """Return True and mark as run if enough time has elapsed for this tier."""
    now = time.monotonic()
    # time.monotonic()'s reference point is undefined (CPython docs: "only the
    # difference between the results of two calls is valid"); on some hosts it
    # can start close to 0 (e.g. a freshly booted CI runner). Defaulting a
    # never-run tier to 0.0 relies on `now` already being >= `interval`, which
    # isn't guaranteed, so an unseen tier could wrongly appear "not due yet"
    # right after startup. -inf makes "never run" always due, independent of
    # the clock's absolute value.
    last = _tier_last_run.get(tier, float("-inf"))
    if now - last >= interval:
        _tier_last_run[tier] = now
        return True
    return False


# ── Helper functions ──────────────────────────────────────────────────────────


def _redis_owner_matches(owner: str | bytes | None, expected_owner: str) -> bool:
    if isinstance(owner, bytes):
        try:
            owner = owner.decode()
        except UnicodeDecodeError:
            return False
    return owner == expected_owner


def _dashboard_base_url() -> str:
    return os.getenv("FRONTEND_URL", "https://qiko.ai/signal").rstrip("/")


def _queue_failure_email(
    db,
    *,
    user_id: int,
    to_email: str | None,
    template_key: str,
    context: dict[str, object],
    correlation_id: str,
) -> None:
    if not to_email:
        return
    try:
        EmailService(db).queue_template_email(
            to_email=to_email,
            template_key=template_key,
            context=context,
            user_id=user_id,
            correlation_id=correlation_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to queue %s notification for user %s", template_key, user_id, exc_info=exc
        )


def _mark_competitive_snapshot_failed_from_job(db, job: models.AuditJob, reason: str) -> None:
    request_context = parse_project_competitor_request_id(job.request_id)
    if request_context is None:
        return
    source_audit_id, competitor_id = request_context
    project = (
        db.query(models.Project)
        .join(models.Audit, models.Audit.project_id == models.Project.id)
        .filter(models.Audit.id == source_audit_id)
        .first()
    )
    if project is None:
        return
    # SIGV2-1136: both ids above are parsed out of the job's request id, so this
    # lookup is what decides which tenant's project receives a write and which
    # tenant's digest gets queued. Authorize the project against the job's user
    # before writing anything.
    #
    # The boundary is workspace or project membership, the same notion
    # resolve_project_access enforces on every router. It is deliberately not
    # `Audit.user_id == job.user_id`: a workspace member may benchmark against a
    # colleague's source audit, so the owning user is not expected to match the
    # user the job is attributed to, and an ownership filter would refuse that
    # legitimate case while still being the wrong rule.
    if not user_can_access_project(db, user_id=job.user_id, project_id=project.id):
        logger.warning(
            "Refusing a competitive snapshot write for AuditJob %s: user %s is outside the "
            "tenant boundary of project %s, which was resolved from the job's request id.",
            job.id,
            job.user_id,
            project.id,
        )
        return
    # The competitor id comes from the same parsed string, so it is trusted only
    # once it is proven to belong to the project being written. Without this the
    # snapshot row could link one project to another project's competitor.
    competitor_in_project = (
        db.query(models.ProjectCompetitor.id)
        .filter(
            models.ProjectCompetitor.id == competitor_id,
            models.ProjectCompetitor.project_id == project.id,
        )
        .first()
    )
    if competitor_in_project is None:
        logger.warning(
            "Refusing a competitive snapshot write for AuditJob %s: competitor %s does not "
            "belong to project %s.",
            job.id,
            competitor_id,
            project.id,
        )
        return
    mark_project_competitor_snapshot_failed(
        db,
        project_id=project.id,
        competitor_id=competitor_id,
        source_audit_id=source_audit_id,
        reason=reason,
    )
    maybe_queue_project_competitive_digest(
        db,
        project=project,
        source_audit_id=source_audit_id,
        frontend_base_url=_dashboard_base_url(),
    )


def _cleanup_expired_report_jobs(db, *, now: datetime) -> tuple[int, int]:
    try:
        retention_days = int(get_report_retention_days(db))
    except Exception:
        retention_days = resolve_report_retention_days()
    if retention_days <= 0:
        retention_days = resolve_report_retention_days()

    cutoff = now - timedelta(days=retention_days)
    stale_reports = (
        db.query(models.ComplexReportJob)
        .filter(
            models.ComplexReportJob.status == "succeeded",
            or_(
                models.ComplexReportJob.completed_at < cutoff,
                and_(
                    models.ComplexReportJob.completed_at.is_(None),
                    models.ComplexReportJob.created_at < cutoff,
                ),
            ),
        )
        .with_for_update(skip_locked=True)
        .all()
    )

    gcs_service = get_storage_service()
    expired_jobs = 0
    deleted_files = 0
    for job in stale_reports:
        if job.file_path and gcs_service.delete_file(storage_uri=job.file_path):
            deleted_files += 1
        job.status = "expired"
        expired_jobs += 1

    # Sweep orphaned report objects in case jobs were removed or file_path metadata drifted.
    deleted_files += gcs_service.cleanup_expired(
        prefix=str(settings.STORAGE_REPORTS_PREFIX or "reports/"),
        max_age_days=retention_days,
    )

    return expired_jobs, deleted_files


# ── Main sweep function ──────────────────────────────────────────────────────


def sweep_cycle(*, force_all: bool = False):
    """Execute all due sweep tasks based on tier intervals.

    When *force_all* is True every tier runs unconditionally (used for
    single-shot / ``--once`` mode).
    """
    run_fast = force_all or _should_run_tier("fast", TIER_FAST)
    run_standard = force_all or _should_run_tier("standard", TIER_STANDARD)
    run_slow = force_all or _should_run_tier("slow", TIER_SLOW)
    run_daily = force_all or _should_run_tier("daily", TIER_DAILY)

    if not any([run_fast, run_standard, run_slow, run_daily]):
        logger.debug("No sweep tiers due this cycle, skipping")
        return

    db = SessionLocal()
    now = datetime.now(timezone.utc)
    dashboard_base = _dashboard_base_url()

    logger.info(
        "Starting sweep cycle (fast=%s standard=%s slow=%s daily=%s)",
        run_fast,
        run_standard,
        run_slow,
        run_daily,
    )

    try:
        # ── Fast tier: stale job detection, credit holds, DLQ retry ───
        if run_fast:
            stale_running_audits = (
                db.query(models.AuditJob)
                .filter(
                    models.AuditJob.status == "running",
                    models.AuditJob.last_heartbeat < (now - STALE_HEARTBEAT_THRESHOLD),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in stale_running_audits:
                logger.warning(
                    "Failing stale running AuditJob: %s (Last heartbeat: %s)",
                    job.id,
                    job.last_heartbeat,
                )
                job.status = "failed"
                job.error = "Job timed out (no heartbeat detected)"
                job.completed_at = now
                _mark_competitive_snapshot_failed_from_job(db, job, job.error)
                user = db.query(models.User).filter(models.User.id == job.user_id).first()
                if user:
                    _queue_failure_email(
                        db,
                        user_id=user.id,
                        to_email=user.email,
                        template_key="audit.failed",
                        context={
                            "email": user.email,
                            "target_url": job.target_url or job.url or job.target_name or "",
                            "error_message": job.error,
                            "dashboard_url": f"{dashboard_base}/dashboard/reports",
                        },
                        correlation_id=f"audit.failed:{job.id}",
                    )

            stale_queued_audits = (
                db.query(models.AuditJob)
                .filter(
                    models.AuditJob.status == "queued",
                    models.AuditJob.created_at < (now - STALE_QUEUED_THRESHOLD),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in stale_queued_audits:
                logger.warning(
                    "Failing stale queued AuditJob: %s (Created at: %s)", job.id, job.created_at
                )
                job.status = "failed"
                job.error = "Job timed out (stuck in queue for too long)"
                job.completed_at = now
                _mark_competitive_snapshot_failed_from_job(db, job, job.error)
                user = db.query(models.User).filter(models.User.id == job.user_id).first()
                if user:
                    _queue_failure_email(
                        db,
                        user_id=user.id,
                        to_email=user.email,
                        template_key="audit.failed",
                        context={
                            "email": user.email,
                            "target_url": job.target_url or job.url or job.target_name or "",
                            "error_message": job.error,
                            "dashboard_url": f"{dashboard_base}/dashboard/reports",
                        },
                        correlation_id=f"audit.failed:{job.id}",
                    )

            expired_hold_ids = expire_stale_holds(db, reference_time=now)
            if expired_hold_ids:
                logger.warning(
                    "Expired %d stale credit holds: %s", len(expired_hold_ids), expired_hold_ids
                )

            stale_running_reports = (
                db.query(models.ComplexReportJob)
                .filter(
                    models.ComplexReportJob.status == "running",
                    models.ComplexReportJob.last_heartbeat < (now - STALE_HEARTBEAT_THRESHOLD),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in stale_running_reports:
                logger.warning(
                    "Failing stale running ComplexReportJob: %s (Last heartbeat: %s)",
                    job.id,
                    job.last_heartbeat,
                )
                job.status = "failed"
                job.error = "Report generation timed out (no heartbeat detected)"
                job.completed_at = now
                user = db.query(models.User).filter(models.User.id == job.user_id).first()
                if user:
                    _queue_failure_email(
                        db,
                        user_id=user.id,
                        to_email=user.email,
                        template_key="report.failed",
                        context={
                            "email": user.email,
                            "report_name": "Complex report",
                            "job_id": job.id,
                            "error_message": job.error,
                            "dashboard_url": f"{dashboard_base}/dashboard/reports",
                        },
                        correlation_id=f"report.failed:{job.id}",
                    )

            stale_queued_reports = (
                db.query(models.ComplexReportJob)
                .filter(
                    models.ComplexReportJob.status == "queued",
                    models.ComplexReportJob.created_at < (now - STALE_QUEUED_THRESHOLD),
                )
                .with_for_update(skip_locked=True)
                .all()
            )
            for job in stale_queued_reports:
                logger.warning(
                    "Failing stale queued ComplexReportJob: %s (Created at: %s)",
                    job.id,
                    job.created_at,
                )
                job.status = "failed"
                job.error = "Report generation timed out (stuck in queue for too long)"
                job.completed_at = now
                user = db.query(models.User).filter(models.User.id == job.user_id).first()
                if user:
                    _queue_failure_email(
                        db,
                        user_id=user.id,
                        to_email=user.email,
                        template_key="report.failed",
                        context={
                            "email": user.email,
                            "report_name": "Complex report",
                            "job_id": job.id,
                            "error_message": job.error,
                            "dashboard_url": f"{dashboard_base}/dashboard/reports",
                        },
                        correlation_id=f"report.failed:{job.id}",
                    )

            # DLQ auto-retry
            try:
                from core.redis_client import get_sync_redis
                from services.job_ttl_dlq_service import auto_retry_dlq_sync

                with get_sync_redis() as redis_client:
                    dlq_result = auto_retry_dlq_sync(redis_client)
                    logger.info(
                        "DLQ auto-retry: retried=%s skipped=%s errors=%s remaining=%s",
                        dlq_result["retried"],
                        dlq_result["skipped"],
                        dlq_result["errors"],
                        dlq_result["total_remaining"],
                    )
            except Exception:
                logger.exception("Failed DLQ auto-retry sweep")

        # ── Standard tier: general maintenance tasks ──────────────────
        if run_standard:
            generated_reports = generate_pending_project_progress_reports(
                db,
                now=now,
                frontend_base_url=dashboard_base,
            )
            if generated_reports:
                logger.info("Queued %s automated project progress reports", len(generated_reports))

            try:
                logger.info("Evaluating Admin Alerts...")
                asyncio.run(evaluate_admin_alerts())
            except Exception:
                logger.exception("Failed to run Admin Alerts Evaluator")

            # SIGV2-1280: the customer-facing alert rules. Until now nothing
            # evaluated them. Rules were created through the dashboard and
            # through the public API, stored, listed and edited, and never
            # looked at, so no alert a customer configured could ever fire.
            # It failed silently, because the only symptom is a notification
            # that does not arrive.
            #
            # Here rather than in the audit worker because only three of the
            # six metrics come from an audit; the others read visibility and
            # mention tables that change on their own schedule. One sweep
            # covers every metric and every source of change, and a failure
            # cannot take an audit down with it.
            try:
                evaluated = evaluate_due_project_alerts(db)
                if evaluated:
                    logger.info("Evaluated alert rules for %s project(s)", evaluated)
            except Exception:
                logger.exception("Failed to evaluate project alert rules")

            try:
                logger.info("Capturing metrics snapshot...")
                collect_metrics_snapshot(db)
            except Exception:
                logger.exception("Failed to capture metrics snapshot")

            try:
                bot_log_summary = refresh_recent_bot_log_daily_summaries(db, lookback_days=30)
                logger.info(
                    "Bot log summary refresh: considered=%s refreshed=%s failed=%s",
                    int(bot_log_summary.get("projects_considered", 0)),
                    int(bot_log_summary.get("projects_refreshed", 0)),
                    int(bot_log_summary.get("projects_failed", 0)),
                )
            except Exception:
                logger.exception("Failed bot log summary refresh sweep")

            try:
                mention_summary = refresh_recent_off_page_mention_daily_summaries(
                    db, lookback_days=30
                )
                logger.info(
                    "Off-page mentions summary refresh: considered=%s refreshed=%s failed=%s",
                    int(mention_summary.get("projects_considered", 0)),
                    int(mention_summary.get("projects_refreshed", 0)),
                    int(mention_summary.get("projects_failed", 0)),
                )
            except Exception:
                logger.exception("Failed off-page mentions summary refresh sweep")

            try:
                volatility_summary = refresh_recent_global_volatility_snapshots(
                    db, lookback_days=30
                )
                logger.info(
                    "Global volatility refresh: dates_considered=%s dates_refreshed=%s rows_written=%s",
                    int(volatility_summary.get("dates_considered", 0)),
                    int(volatility_summary.get("dates_refreshed", 0)),
                    int(volatility_summary.get("rows_written", 0)),
                )
            except Exception:
                logger.exception("Failed global volatility refresh sweep")

            try:
                feedback_summary = queue_feedback_requests_for_completed_trials(db, now=now)
                logger.info(
                    "Trial feedback sweep: eligible_users=%s created_requests=%s queued_emails=%s",
                    int(feedback_summary.get("eligible_users", 0)),
                    int(feedback_summary.get("created_requests", 0)),
                    int(feedback_summary.get("queued_emails", 0)),
                )
            except Exception:
                logger.exception("Failed trial feedback request sweep")

            # ── Trial → Explorer auto-transition + Explorer credit refresh ──
            try:
                expired_trial_users = (
                    db.query(models.User)
                    .filter(
                        models.User.trial_plan == "plan_agency_trial",
                        models.User.trial_ends_at < now,
                    )
                    .all()
                )
                transitioned = 0
                for u in expired_trial_users:
                    if transition_expired_trial_to_explorer(db, u):
                        transitioned += 1
                        try:
                            email_service = EmailService(db)
                            email_service.queue_template_email(
                                to_email=u.email,
                                template_key="trial.explorer_transition",
                                context={
                                    "email": u.email,
                                    "user_name": u.company_name or u.email,
                                    "upgrade_url": f"{dashboard_base}/dashboard/billing",
                                },
                            )
                        except Exception:
                            logger.warning(
                                "Failed to queue Explorer transition email for user %s", u.id
                            )
                if transitioned:
                    db.commit()
                    logger.info("Trial→Explorer transition sweep: transitioned=%s", transitioned)
            except Exception:
                logger.exception("Failed trial→Explorer transition sweep")

            try:
                explorer_users = (
                    db.query(models.User).filter(models.User.trial_plan == STARTER_PLAN).all()
                )
                refreshed = 0
                for u in explorer_users:
                    if refresh_explorer_credits(db, u):
                        refreshed += 1
                if refreshed:
                    db.commit()
                    logger.info("Explorer credit refresh sweep: refreshed=%s", refreshed)
            except Exception:
                logger.exception("Failed Explorer credit refresh sweep")

        # ── Slow tier: credit commitments, signal warehouse ───────────
        if run_slow:
            reported_overages = report_pending_commitment_overages(db, now=now)
            if reported_overages:
                logger.info("Reported %s pending commitment overage cycles", len(reported_overages))

            warning_candidates = collect_warning_candidates(db)
            for commitment, cycle in warning_candidates:
                user = db.query(models.User).filter(models.User.id == commitment.user_id).first()
                if user is None:
                    continue
                usage_pct = round(
                    (int(cycle.credits_used or 0) / max(int(cycle.committed_credits or 1), 1))
                    * 100,
                    2,
                )
                _queue_failure_email(
                    db,
                    user_id=user.id,
                    to_email=user.email,
                    template_key="commitment.overage_warning",
                    context={
                        "email": user.email,
                        "user_name": user.company_name or user.email,
                        "tier": commitment.tier,
                        "usage_pct": usage_pct,
                        "manage_billing_url": f"{dashboard_base}/dashboard/billing",
                    },
                    correlation_id=f"commitment.warning:{commitment.id}:{cycle.id}",
                )
                cycle.warning_sent_at = now

            try:
                has_missing_signal_rows = (
                    db.query(models.Audit.id)
                    .outerjoin(
                        models.SignalAuditSnapshot,
                        models.SignalAuditSnapshot.audit_id == models.Audit.id,
                    )
                    .filter(
                        models.Audit.project_id.isnot(None),
                        models.SignalAuditSnapshot.id.is_(None),
                    )
                    .first()
                    is not None
                )
                if has_missing_signal_rows:
                    summary = SignalIngestionService().backfill_all(db=db, dry_run=False)
                    logger.info(
                        "Signal warehouse backfill in cron sweep processed audits=%s batches=%s rows=%s errors=%s",
                        summary.get("audits_processed", 0),
                        summary.get("batches_processed", 0),
                        summary.get("rows_inserted", 0),
                        len(summary.get("errors", [])),
                    )

                today = now.date()
                existing_cohort_rows = (
                    db.query(models.BenchmarkCohortAggregate.id)
                    .filter(models.BenchmarkCohortAggregate.period_date == today)
                    .first()
                )
                if existing_cohort_rows is None:
                    written_rows = BenchmarkEngine().compute_cohort_aggregates(
                        db=db, period_date=today
                    )
                    logger.info(
                        "Signal benchmark aggregates computed for %s: rows=%s",
                        today.isoformat(),
                        written_rows,
                    )
            except Exception:
                logger.exception("Failed signal warehouse sweep")

            # SIGV2-1177: the per-tier scan duration aggregate the start-scan
            # screen states. Recomputed on the hourly tier rather than per
            # request: it reads up to 90 days of completed audit_jobs rows per
            # tier, and a figure derived from months of runs does not move
            # between two page loads. Hourly also keeps it well inside the
            # service's own staleness ceiling, so a surface stops stating a
            # figure if this sweep ever stops running.
            try:
                duration_stats = recompute_tier_duration_stats(db, now=now)
                logger.info(
                    "Tier duration aggregate: %s",
                    " ".join(
                        f"{tier}(n={summary['sample_size']},published={summary['published']})"
                        for tier, summary in duration_stats.items()
                    ),
                )
            except Exception:
                logger.exception("Failed tier duration aggregate sweep")

        # ── Daily tier: retention cleanup, model lifecycle, orphan keys ─
        if run_daily:
            expired_jobs, deleted_report_files = _cleanup_expired_report_jobs(db, now=now)
            if expired_jobs or deleted_report_files:
                logger.info(
                    "Report retention sweep completed: expired_jobs=%s deleted_files=%s",
                    expired_jobs,
                    deleted_report_files,
                )

            try:
                from services.audit_archive_service import run_retention_sweep

                retention_result = run_retention_sweep(db, now=now)
                if any(retention_result.values()):
                    logger.info(
                        "Audit data retention sweep: screenshots_redacted=%s reports_archived=%s reports_purged=%s",
                        retention_result["screenshots_redacted"],
                        retention_result["reports_archived"],
                        retention_result["reports_purged"],
                    )
            except Exception:
                logger.exception("Failed audit data retention sweep")

            try:
                lifecycle_summary = run_model_lifecycle_check(db)
                logger.info(
                    "Model lifecycle check: sources=%s failed=%s changed=%s alerts=%s emails=%s",
                    int(lifecycle_summary.get("sources_checked", 0)),
                    int(lifecycle_summary.get("sources_failed", 0)),
                    int(lifecycle_summary.get("pages_changed", 0)),
                    int(lifecycle_summary.get("alerts_created", 0)),
                    int(lifecycle_summary.get("emails_sent", 0)),
                )
            except Exception:
                logger.exception("Failed model lifecycle check sweep")

            try:
                from core.redis_client import get_sync_redis
                from services.job_ttl_dlq_service import cleanup_orphaned_job_keys_sync

                with get_sync_redis() as redis_client:
                    orphan_result = cleanup_orphaned_job_keys_sync(redis_client)
                    logger.info(
                        "Redis job key cleanup: scanned=%s fixed=%s",
                        orphan_result["scanned"],
                        orphan_result["fixed"],
                    )
            except Exception:
                logger.exception("Failed orphan cleanup sweep")

            # Purge unclaimed guest audit records older than 30 days
            try:
                guest_cutoff = now - timedelta(days=30)
                purged_guests = (
                    db.query(models.GuestAuditRecord)
                    .filter(
                        models.GuestAuditRecord.claimed_by_user_id.is_(None),
                        models.GuestAuditRecord.created_at < guest_cutoff,
                    )
                    .delete(synchronize_session=False)
                )
                if purged_guests:
                    logger.info(
                        "Purged %s unclaimed guest audit records older than 30 days", purged_guests
                    )
            except Exception:
                logger.exception("Failed guest audit record purge")

            try:
                recon_summary = run_credit_reconciliation_sweep(db)
                logger.info(
                    "Credit reconciliation sweep: users_checked=%s discrepancies=%s",
                    recon_summary["users_checked"],
                    len(recon_summary["discrepancies"]),
                )
            except Exception:
                logger.exception("Failed credit reconciliation sweep")

        db.commit()
        logger.info("Sweep cycle completed successfully")
    except Exception:
        logger.exception("Error during sweep cycle")
        db.rollback()
        raise
    finally:
        db.close()


# ── Legacy single-shot entry point ───────────────────────────────────────────


def sweep_jobs():
    """Backward-compatible single-shot sweep (runs all tiers once)."""
    sweep_cycle(force_all=True)


# ── Async periodic loop ──────────────────────────────────────────────────────


async def _interruptible_sleep(seconds: float) -> None:
    """Sleep for the given duration, checking for shutdown every second."""
    remaining = seconds
    while remaining > 0 and not shutdown_requested:
        await asyncio.sleep(min(remaining, 1.0))
        remaining -= 1.0


async def run_periodic():
    """Main periodic loop with heartbeat, distributed lock, and metrics."""
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    logger.info(
        "Cron sweeper started (worker_id=%s, interval=%ds, tiers: fast=%ds standard=%ds slow=%ds daily=%ds)",
        WORKER_ID,
        SWEEP_INTERVAL_SECONDS,
        TIER_FAST,
        TIER_STANDARD,
        TIER_SLOW,
        TIER_DAILY,
    )

    while not shutdown_requested:
        # Acquire distributed lock
        lock_acquired = False
        try:
            async with get_async_redis() as redis_client:
                lock_acquired = bool(
                    await redis_client.set(
                        LOCK_KEY,
                        WORKER_ID,
                        nx=True,
                        ex=SWEEP_INTERVAL_SECONDS * 3,
                    )
                )
                if not lock_acquired:
                    # Check if we already own the lock (re-entrant)
                    current_owner = await redis_client.get(LOCK_KEY)
                    if _redis_owner_matches(current_owner, WORKER_ID):
                        lock_acquired = True
                        await redis_client.expire(LOCK_KEY, SWEEP_INTERVAL_SECONDS * 3)
        except Exception:
            logger.exception("Failed to acquire sweep lock from Redis")

        if not lock_acquired:
            logger.debug("Another sweeper instance holds the lock, skipping this cycle")
            await _interruptible_sleep(SWEEP_INTERVAL_SECONDS)
            continue

        start = time.monotonic()
        try:
            # Run sweep in thread to avoid blocking the event loop
            await asyncio.to_thread(sweep_cycle)

            # Update heartbeat
            try:
                async with get_async_redis() as redis_client:
                    await redis_client.set(
                        HEARTBEAT_KEY,
                        datetime.now(timezone.utc).isoformat(),
                        ex=SWEEP_INTERVAL_SECONDS * 3,
                    )
                    # Refresh lock TTL
                    await redis_client.expire(LOCK_KEY, SWEEP_INTERVAL_SECONDS * 3)
            except Exception:
                logger.warning("Failed to update heartbeat/lock in Redis", exc_info=True)

            cron_sweep_runs_total.labels(status="success").inc()
            cron_sweep_last_success_timestamp.set(time.time())

        except Exception:
            cron_sweep_runs_total.labels(status="error").inc()
            cron_sweep_errors_total.inc()
            logger.critical("Sweep cycle failed", exc_info=True)

        finally:
            duration = time.monotonic() - start
            cron_sweep_duration_seconds.observe(duration)

        await _interruptible_sleep(SWEEP_INTERVAL_SECONDS)

    # Graceful shutdown: release lock
    logger.info("Cron sweeper shutting down gracefully (worker_id=%s)", WORKER_ID)
    try:
        async with get_async_redis() as redis_client:
            current_owner = await redis_client.get(LOCK_KEY)
            if _redis_owner_matches(current_owner, WORKER_ID):
                await redis_client.delete(LOCK_KEY)
    except Exception:
        pass


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    configure_logging()
    init_tracing("cron-sweeper")

    if "--once" in sys.argv:
        sweep_jobs()
    else:
        asyncio.run(run_periodic())
