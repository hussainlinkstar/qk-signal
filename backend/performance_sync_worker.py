from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

from database import SessionLocal
import models
from observability import configure_logging, init_tracing
from services.performance import PerformanceService
from services.performance_snapshots import PerformanceSnapshotService, PerformanceSyncWorker

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = int(os.getenv("PERFORMANCE_SYNC_INTERVAL_SECONDS", "86400"))
PERFORMANCE_SYNC_URL_LIMIT = int(os.getenv("PERFORMANCE_SYNC_URL_LIMIT", "500"))
shutdown_requested = False


def _request_shutdown(signame: str) -> None:
    global shutdown_requested
    shutdown_requested = True
    logger.info("Performance sync worker received %s, shutting down.", signame)


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: _request_shutdown(s.name))
        except NotImplementedError:
            signal.signal(sig, lambda _signum, _frame, s=sig: _request_shutdown(s.name))


def _load_target_urls(db) -> list[str]:
    rows = (
        db.query(models.Audit.url)
        .distinct()
        .order_by(models.Audit.created_at.desc())
        .limit(PERFORMANCE_SYNC_URL_LIMIT)
        .all()
    )
    return [str(row[0]) for row in rows if row and row[0]]


async def run_worker() -> None:
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    performance_service = PerformanceService()
    snapshot_service = PerformanceSnapshotService(performance_service)
    sync_worker = PerformanceSyncWorker(snapshot_service)

    logger.info("Performance sync worker started interval=%ss", SYNC_INTERVAL_SECONDS)
    last_run = 0.0
    while not shutdown_requested:
        now = time.monotonic()
        if now - last_run < SYNC_INTERVAL_SECONDS:
            await asyncio.sleep(1)
            continue

        db = SessionLocal()
        try:
            urls = _load_target_urls(db)
            counters = await sync_worker.run_once(db, urls=urls)
            logger.info("Performance sync run completed counters=%s", counters)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Performance sync run failed: %s", exc)
        finally:
            db.close()
        last_run = now


if __name__ == "__main__":
    configure_logging()
    init_tracing("performance-sync-worker")
    asyncio.run(run_worker())
