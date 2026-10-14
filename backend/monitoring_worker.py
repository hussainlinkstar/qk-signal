"""Monitoring Worker, Continuous Monitoring Background Runner.

Standalone script (invoked via cron) that refreshes GA4 LLM traffic and
DataForSEO SERP tracking data for all active projects.

Usage:
    python monitoring_worker.py                    # Run once (for cron)
    python monitoring_worker.py --loop --interval 3600  # Continuous loop
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import NamedTuple

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

from database import SessionLocal
from observability import configure_logging, init_tracing
import models

logger = logging.getLogger("monitoring_worker")

shutdown_requested = False


def _request_shutdown(signum: int, frame: object) -> None:
    global shutdown_requested
    shutdown_requested = True
    logger.info("Monitoring worker received signal %s, shutting down gracefully.", signum)


def _install_signal_handlers() -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, _request_shutdown)


# ---------------------------------------------------------------------------
# GA4 sync
# ---------------------------------------------------------------------------


class _GA4Target(NamedTuple):
    project_id: int
    ga4_property_id: str
    data_source: "models.ProjectDataSource | None" = None


def _normalize_ga4_property_id(raw: str | None) -> str | None:
    """Return ``properties/<digits>`` or ``None`` if the value is unusable.

    The id is interpolated into the GA4 Data API URL, so anything that is not
    digits after the prefix is dropped rather than passed through.
    """
    value = (raw or "").strip()
    if value.startswith("properties/"):
        value = value[len("properties/") :]
    if not value.isdigit():
        return None
    return f"properties/{value}"


def _resolve_ga4_targets(db: "Session") -> list[_GA4Target]:
    """Projects to sync, preferring the mapping the settings UI actually writes.

    Two tables held a GA4 property and only one of them was reachable. Project
    Settings writes ``project_data_sources`` (source_type ``google_analytics_4``),
    with provider catalog discovery, while this worker read
    ``project_ga4_configs``, which no endpoint ever populated. So a customer could
    select their property, see it saved, and never get a sync.

    ``project_data_sources`` wins because it is the one with a UI.
    ``project_ga4_configs`` is still honoured for any row set by hand before this,
    and is not used to override a project mapped through settings.
    """
    targets: dict[int, _GA4Target] = {}

    data_sources = (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.source_type == models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            models.ProjectDataSource.is_active.is_(True),
        )
        .all()
    )
    for source in data_sources:
        property_id = _normalize_ga4_property_id(getattr(source, "source_id", None))
        if property_id:
            targets[source.project_id] = _GA4Target(
                project_id=source.project_id,
                ga4_property_id=property_id,
                data_source=source,
            )
        else:
            logger.warning(
                "GA4 data source for project=%s has an unusable property id, skipping",
                source.project_id,
            )

    legacy_configs = (
        db.query(models.ProjectGA4Config).filter(models.ProjectGA4Config.is_active.is_(True)).all()
    )
    for config in legacy_configs:
        if config.project_id in targets:
            continue
        property_id = _normalize_ga4_property_id(config.ga4_property_id)
        if property_id:
            targets[config.project_id] = _GA4Target(
                project_id=config.project_id,
                ga4_property_id=property_id,
            )

    return list(targets.values())


def _mark_ga4_sync(
    db: "Session",
    source: "models.ProjectDataSource | None",
    *,
    status: str,
    error: str | None = None,
) -> None:
    if source is None:
        return
    source.last_status = status
    source.last_error = (error or "")[:500] or None
    if status == "success":
        source.last_sync_at = datetime.now(timezone.utc)
    db.commit()


def _safe_error_detail(exc: Exception) -> str:
    """Short sanitized reason for last_error; never includes token material."""
    detail = str(exc).strip()
    if not detail:
        return type(exc).__name__
    return detail[:500]


def _sync_ga4_traffic(db: "Session") -> int:
    """Sync GA4 LLM traffic for all projects with an active GA4 config.

    Projects bound through ``project_data_sources`` are synced with the
    customer's own OAuth token, resolved and refreshed by
    ``app.services.geo.ga4_oauth_service`` - the single token-handling path.
    Legacy ``project_ga4_configs`` rows with no data source fall back to the
    service account, which exists only for this AI-referral snapshot job.
    """
    from core.config import settings
    from app.services.geo.ga4_oauth_service import (
        GA4ConnectionError,
        GA4TokenRefreshError,
        ga4_access_token,
    )
    from app.services.geo.ga4_traffic_service import GA4TrafficService, GA4AuthError

    targets = _resolve_ga4_targets(db)

    if not targets:
        logger.info("No active GA4 configs found, skipping GA4 sync")
        return 0

    service_account_path = settings.GA4_SERVICE_ACCOUNT_JSON_PATH
    legacy_service = (
        GA4TrafficService(service_account_json_path=service_account_path)
        if service_account_path
        else None
    )

    synced = 0
    for target in targets:
        if shutdown_requested:
            logger.info("Shutdown requested, stopping GA4 sync")
            break
        source = target.data_source
        try:
            if source is not None:
                token = ga4_access_token(db, source)
                service = GA4TrafficService(access_token=token)
            else:
                if legacy_service is None:
                    logger.info(
                        "GA4_SERVICE_ACCOUNT_JSON_PATH not configured, "
                        "skipping legacy GA4 sync for project=%d",
                        target.project_id,
                    )
                    continue
                service = legacy_service
            service.sync_traffic(
                db=db,
                project_id=target.project_id,
                property_id=target.ga4_property_id,
                lookback_days=30,
            )
            _mark_ga4_sync(db, source, status="success")
            synced += 1
        except (GA4ConnectionError, GA4TokenRefreshError, GA4AuthError) as exc:
            _mark_ga4_sync(db, source, status="auth_error", error=_safe_error_detail(exc))
            logger.error(
                "GA4 auth error for project=%d: %s",
                target.project_id,
                type(exc).__name__,
            )
        except Exception as exc:
            _mark_ga4_sync(db, source, status="error", error=_safe_error_detail(exc))
            logger.exception(
                "GA4 sync failed for project=%d",
                target.project_id,
            )

    return synced


# ---------------------------------------------------------------------------
# Bing Webmaster sync
# ---------------------------------------------------------------------------


def _sync_bing_webmaster(db: "Session") -> int:
    """Ingest Bing Webmaster metrics for every active binding (SIGV2-1265).

    Ingestion used to happen only inside the monitoring endpoint, which no
    screen called, so a bound Bing site never collected a single row. One
    failing binding never stops the rest: the outcome is recorded on that
    binding and the loop carries on.
    """
    from app.services.bing_webmaster_service import (
        active_bing_bindings,
        bing_webmaster_oauth_configured,
        sync_project_bing_source,
    )

    if not bing_webmaster_oauth_configured():
        logger.info("Bing Webmaster OAuth not configured, skipping Bing sync")
        return 0

    bindings = active_bing_bindings(db)
    if not bindings:
        logger.info("No active Bing Webmaster bindings found, skipping Bing sync")
        return 0

    synced = 0
    for source in bindings:
        if shutdown_requested:
            logger.info("Shutdown requested, stopping Bing sync")
            break
        try:
            result = sync_project_bing_source(db, source)
        except Exception:
            logger.exception("Bing sync failed for project=%s", source.project_id)
            continue
        if result.status == "ok":
            synced += 1
        else:
            logger.warning(
                "Bing sync for project=%s reported %s (%s)",
                source.project_id,
                result.status,
                result.reason or "no reason given",
            )

    return synced


# ---------------------------------------------------------------------------
# DataForSEO sync
# ---------------------------------------------------------------------------


def _sync_serp_data(db: "Session") -> int:
    """Sync SERP data for all projects with active target keywords."""
    from core.config import settings

    if not settings.DATAFORSEO_LOGIN or not settings.DATAFORSEO_PASSWORD:
        logger.info("DataForSEO credentials not configured, skipping SERP sync")
        return 0

    from app.services.aeo.dataforseo_service import (
        DataForSEOService,
        DataForSEOAuthError,
        DataForSEORateLimitError,
    )

    service = DataForSEOService(
        login=settings.DATAFORSEO_LOGIN,
        password=settings.DATAFORSEO_PASSWORD,
    )

    # Find projects that have active keywords
    project_ids_with_keywords = (
        db.query(models.TargetKeyword.project_id)
        .filter(models.TargetKeyword.is_active.is_(True))
        .distinct()
        .all()
    )
    project_ids = [pid for (pid,) in project_ids_with_keywords]

    if not project_ids:
        logger.info("No projects with active keywords, skipping SERP sync")
        return 0

    projects = db.query(models.Project).filter(models.Project.id.in_(project_ids)).all()

    synced = 0
    for project in projects:
        if shutdown_requested:
            logger.info("Shutdown requested, stopping SERP sync")
            break

        domain = project.domain_url or ""
        if domain:
            # Strip protocol and trailing slash for domain matching
            domain = domain.replace("https://", "").replace("http://", "").rstrip("/")

        if not domain:
            logger.warning(
                "Project %d has no domain_url, skipping SERP sync",
                project.id,
            )
            continue

        try:
            service.sync_serp_data(
                db=db,
                project_id=project.id,
                target_domain=domain,
            )
            synced += 1
        except (DataForSEOAuthError, DataForSEORateLimitError):
            logger.error(
                "DataForSEO auth/rate-limit error for project=%d, aborting SERP sync",
                project.id,
            )
            break
        except Exception:
            logger.exception(
                "SERP sync failed for project=%d",
                project.id,
            )

    return synced


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def run_once() -> None:
    """Run a single monitoring sync cycle."""
    logger.info("=== Monitoring worker run started at %s ===", datetime.now(timezone.utc))
    db = SessionLocal()

    try:
        ga4_count = _sync_ga4_traffic(db)
        logger.info("GA4 sync complete: %d projects synced", ga4_count)

        bing_count = _sync_bing_webmaster(db)
        logger.info("Bing Webmaster sync complete: %d bindings synced", bing_count)

        serp_count = _sync_serp_data(db)
        logger.info("SERP sync complete: %d projects synced", serp_count)

    except Exception:
        logger.exception("Monitoring worker run failed")
    finally:
        db.close()

    logger.info("=== Monitoring worker run finished ===")


def main() -> None:
    parser = argparse.ArgumentParser(description="Continuous Monitoring Background Worker")
    parser.add_argument("--loop", action="store_true", help="Run in continuous loop mode")
    parser.add_argument(
        "--interval",
        type=int,
        default=3600 * 24 * 7,  # Weekly by default
        help="Interval between runs in seconds (default: 1 week)",
    )
    args = parser.parse_args()

    configure_logging()
    init_tracing("monitoring-worker")
    _install_signal_handlers()

    if args.loop:
        logger.info(
            "Monitoring worker starting in loop mode (interval=%ds)",
            args.interval,
        )
        while not shutdown_requested:
            run_once()
            if not shutdown_requested:
                logger.info("Sleeping for %d seconds until next run", args.interval)
                for _ in range(args.interval):
                    if shutdown_requested:
                        break
                    time.sleep(1)
    else:
        run_once()


if __name__ == "__main__":
    main()
