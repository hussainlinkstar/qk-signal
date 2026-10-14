"""Consumer for queued public guest audits.

Runs inside the existing audit worker container as a task started by
``queue_worker.worker_loop``, so no new container and no compose change. It is
a separate loop rather than another branch of the audit queue because a guest
audit is not an ``AuditJob``: it has no user, spends no credits, and produces
the freemium guest payload instead of a full report.

Worker Law 3, bounded concurrency and timeout: concurrency is capped by
``GUEST_AUDIT_WORKER_CONCURRENCY`` and every run is wrapped in
``GUEST_AUDIT_JOB_TIMEOUT_SECONDS``. There is no retry: a guest audit spends
model money on every attempt, so a failed run is reported to the visitor
rather than silently paid for again.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from core.config import settings
from database import SessionLocal
from services.guest_audit_public import (
    ERROR_INTERNAL,
    ERROR_TARGET_BLOCKED,
    ERROR_TIMEOUT,
    mark_completed,
    mark_failed,
    mark_running,
    project_public_result,
    resolve_job_timeout_seconds,
    resolve_queue_name,
)
from services.guest_audit_service import run_guest_audit
from services.url_validation import SSRFBlockedError

logger = logging.getLogger(__name__)


def resolve_concurrency() -> int:
    return max(1, int(getattr(settings, "GUEST_AUDIT_WORKER_CONCURRENCY", 2) or 2))


def _classify_error(exc: BaseException) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return ERROR_TIMEOUT
    if isinstance(exc, SSRFBlockedError):
        return ERROR_TARGET_BLOCKED
    if isinstance(exc, ValueError):
        # ``normalize_and_validate_url`` rejects a target that only became
        # resolvable-to-private after submission (DNS changed in between).
        return ERROR_TARGET_BLOCKED
    return ERROR_INTERNAL


async def process_guest_audit_job(payload: dict[str, Any]) -> None:
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        logger.warning("Guest audit job payload has no job_id, dropping it")
        return

    try:
        await mark_running(job_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Guest audit job %s could not be marked running: %s", job_id, exc)

    try:
        raw_metadata = payload.get("target_metadata") or "{}"
        target_metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else {}
    except (TypeError, ValueError):
        target_metadata = {}

    db = SessionLocal()
    try:
        result = await asyncio.wait_for(
            run_guest_audit(
                db,
                audit_target_type=str(payload.get("audit_target_type") or "website"),
                target_url=str(payload.get("target_url") or "") or None,
                target_name=str(payload.get("target_name") or "") or None,
                target_metadata=target_metadata if isinstance(target_metadata, dict) else {},
                email=str(payload.get("email") or "") or None,
                request_id=str(payload.get("request_id") or "") or None,
                ip_hash=str(payload.get("ip_hash") or ""),
                user_agent_hash=str(payload.get("user_agent_hash") or "") or None,
                referrer=str(payload.get("referrer") or "") or None,
            ),
            timeout=resolve_job_timeout_seconds(),
        )
    except Exception as exc:
        db.rollback()
        error_code = _classify_error(exc)
        logger.warning("Guest audit job %s failed (%s): %s", job_id, error_code, exc)
        with contextlib.suppress(Exception):
            await mark_failed(job_id, error_code)
        return
    finally:
        db.close()

    try:
        await mark_completed(job_id, project_public_result(result))
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Guest audit job %s could not be stored: %s", job_id, exc)
        with contextlib.suppress(Exception):
            await mark_failed(job_id, ERROR_INTERNAL)


async def guest_audit_worker_loop(redis_client, *, should_stop=None) -> None:
    """Consume the guest audit queue until *should_stop* returns True."""
    queue_name = resolve_queue_name()
    semaphore = asyncio.Semaphore(resolve_concurrency())
    pending: set[asyncio.Task] = set()

    logger.info(
        "Guest audit consumer listening on %s (max_concurrent=%d)",
        queue_name,
        resolve_concurrency(),
    )

    def _stop() -> bool:
        return bool(should_stop()) if callable(should_stop) else False

    try:
        while not _stop():
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if _stop():
                semaphore.release()
                break

            try:
                item = await redis_client.blpop([queue_name], timeout=2)
            except asyncio.CancelledError:
                semaphore.release()
                raise
            except Exception as exc:
                semaphore.release()
                logger.warning("Guest audit queue read failed: %s", exc)
                await asyncio.sleep(1.0)
                continue

            if not item:
                semaphore.release()
                continue

            _queue, raw_payload = item
            try:
                payload = json.loads(
                    raw_payload.decode() if isinstance(raw_payload, bytes) else raw_payload
                )
            except (AttributeError, TypeError, ValueError):
                semaphore.release()
                logger.warning("Guest audit queue produced an unreadable payload, dropping it")
                continue

            async def _run(job_payload: dict[str, Any]) -> None:
                try:
                    await process_guest_audit_job(job_payload)
                finally:
                    semaphore.release()

            task = asyncio.create_task(_run(payload))
            pending.add(task)
            task.add_done_callback(pending.discard)
    finally:
        if pending:
            logger.info("Guest audit consumer draining %d job(s)", len(pending))
            await asyncio.gather(*pending, return_exceptions=True)
