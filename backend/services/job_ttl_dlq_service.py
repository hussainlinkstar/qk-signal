"""
AEX-22, Redis Job Hash TTL and Dead Letter Queue

Provides:
- TTL constants for audit:job:{id} hashes at each lifecycle stage
- DLQ push / list / retry / discard helpers
- Orphaned Redis key cleanup for cron sweeper
"""

from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
TTL_IN_PROGRESS = 1800  # 30 min, generous buffer over JOB_TIMEOUT_SECONDS (900)
TTL_SUCCEEDED = 86_400  # 24 h, enough for inspection / debugging
TTL_FAILED = 604_800  # 7 days, post-mortem window
TTL_QUEUED = 3600  # 1 h, safety net for stuck-in-queue jobs

# ---------------------------------------------------------------------------
# Key patterns
# ---------------------------------------------------------------------------
JOB_KEY_PREFIX = "audit:job:"
DLQ_LIST_KEY = "audit_jobs:dlq"

# Atomically pop the first DLQ entry whose decoded job_id matches ARGV[1].
# Returns the raw JSON string of the removed entry, or false if none matched.
# Running inside a single Lua script guarantees only one concurrent caller can
# remove (and therefore re-enqueue) a given entry.
_DLQ_POP_BY_JOB_ID_LUA = """
local key = KEYS[1]
local job_id = ARGV[1]
local items = redis.call('LRANGE', key, 0, -1)
for i = 1, #items do
    local raw = items[i]
    local ok, entry = pcall(cjson.decode, raw)
    if ok and entry['job_id'] == job_id then
        redis.call('LREM', key, 1, raw)
        return raw
    end
end
return false
"""
DLQ_MAX_RETRY_COUNT = 3
DLQ_ENTRY_TTL = 604_800  # 7 days, same as failed job hash


def _build_job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


# ---------------------------------------------------------------------------
# Async TTL helpers
# ---------------------------------------------------------------------------
async def set_ttl_queued(redis_client, job_id: str) -> None:
    """Set TTL on a newly queued job hash."""
    await redis_client.expire(_build_job_key(job_id), TTL_QUEUED)


async def set_ttl_in_progress(redis_client, job_id: str) -> None:
    """Refresh TTL while job is running (call on heartbeat)."""
    await redis_client.expire(_build_job_key(job_id), TTL_IN_PROGRESS)


async def set_ttl_succeeded(redis_client, job_id: str) -> None:
    """Set 24h TTL after job succeeds."""
    await redis_client.expire(_build_job_key(job_id), TTL_SUCCEEDED)


async def set_ttl_failed(redis_client, job_id: str) -> None:
    """Set 7-day TTL after job fails."""
    await redis_client.expire(_build_job_key(job_id), TTL_FAILED)


# ---------------------------------------------------------------------------
# Sync TTL helpers (for cron_sweeper)
# ---------------------------------------------------------------------------
def set_ttl_failed_sync(redis_client, job_id: str) -> None:
    """Sync version of set_ttl_failed for cron sweeper."""
    redis_client.expire(_build_job_key(job_id), TTL_FAILED)


# ---------------------------------------------------------------------------
# Dead Letter Queue, push
# ---------------------------------------------------------------------------
async def push_to_dlq(
    redis_client,
    *,
    job_id: str,
    original_payload: dict | None = None,
    error: str,
    error_traceback: str = "",
    retry_count: int = 0,
    worker_id: str = "",
) -> None:
    """Push a failed job entry to the dead letter queue."""
    entry = {
        "job_id": job_id,
        "original_payload": original_payload or {},
        "error": error[:2000],
        "traceback": error_traceback[:4000],
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "worker_id": worker_id,
        "retry_count": retry_count,
    }
    await redis_client.rpush(DLQ_LIST_KEY, json.dumps(entry))
    logger.warning("Job %s pushed to DLQ (retry_count=%s): %s", job_id, retry_count, error[:200])


# ---------------------------------------------------------------------------
# Dead Letter Queue, list
# ---------------------------------------------------------------------------
async def list_dlq(redis_client, *, offset: int = 0, limit: int = 50) -> list[dict]:
    """Return paginated DLQ entries (newest-first)."""
    total = await redis_client.llen(DLQ_LIST_KEY)
    if total == 0:
        return []
    # DLQ is oldest-first (rpush). Reverse for newest-first display.
    start = max(0, total - offset - limit)
    end = total - offset - 1
    if end < 0:
        return []
    raw_items = await redis_client.lrange(DLQ_LIST_KEY, start, end)
    entries = []
    for raw in reversed(raw_items):
        try:
            entries.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            entries.append({"raw": str(raw), "parse_error": True})
    return entries


async def dlq_length(redis_client) -> int:
    """Return the total number of entries in the DLQ."""
    return await redis_client.llen(DLQ_LIST_KEY)


# ---------------------------------------------------------------------------
# Dead Letter Queue, retry
# ---------------------------------------------------------------------------
async def retry_dlq_entry(redis_client, job_id: str, queue_name: str = "audit_jobs") -> dict | None:
    """Find a DLQ entry by job_id, re-enqueue it, and remove from DLQ.

    Returns the re-enqueued entry dict or None if not found.
    """
    from services.queue_routing import resolve_queue_for_tier

    # Atomically locate and remove the matching DLQ entry. Running the search +
    # LREM inside a single Lua script eliminates the race where two workers
    # both find the same entry and re-enqueue it twice. Only the worker whose
    # LREM actually removed the element receives the raw payload back.
    removed_raw = await redis_client.eval(_DLQ_POP_BY_JOB_ID_LUA, 1, DLQ_LIST_KEY, job_id)
    if not removed_raw:
        return None
    if isinstance(removed_raw, bytes):
        removed_raw = removed_raw.decode("utf-8")
    try:
        entry = json.loads(removed_raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning("DLQ entry %s could not be decoded after removal", job_id)
        return None
    # Re-enqueue the original payload
    original_payload = entry.get("original_payload", {})
    if not original_payload:
        logger.warning("DLQ entry %s has no original_payload, cannot retry", job_id)
        return None
    # Increment retry count in the payload
    original_payload["dlq_retry_count"] = entry.get("retry_count", 0) + 1
    target_queue = resolve_queue_for_tier(str(original_payload.get("tier", "fast")))
    await redis_client.rpush(target_queue, json.dumps(original_payload))
    # Reset the job hash status to queued
    job_key = _build_job_key(job_id)
    await redis_client.hset(
        job_key,
        mapping={
            "status": "queued",
            "dlq_retried_at": datetime.now(timezone.utc).isoformat(),
            "dlq_retry_count": str(original_payload["dlq_retry_count"]),
        },
    )
    await redis_client.expire(job_key, TTL_QUEUED)
    logger.info(
        "DLQ entry %s re-enqueued to %s (retry_count=%s)",
        job_id,
        target_queue,
        original_payload["dlq_retry_count"],
    )
    return entry


# ---------------------------------------------------------------------------
# Dead Letter Queue, discard
# ---------------------------------------------------------------------------
async def discard_dlq_entry(redis_client, job_id: str) -> bool:
    """Remove a DLQ entry by job_id without re-enqueuing. Returns True if found."""
    total = await redis_client.llen(DLQ_LIST_KEY)
    for idx in range(total):
        raw = await redis_client.lindex(DLQ_LIST_KEY, idx)
        if raw is None:
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if entry.get("job_id") != job_id:
            continue
        sentinel = f"__dlq_discard_{job_id}_{datetime.now(timezone.utc).timestamp()}"
        await redis_client.lset(DLQ_LIST_KEY, idx, sentinel)
        await redis_client.lrem(DLQ_LIST_KEY, 1, sentinel)
        logger.info("DLQ entry %s discarded", job_id)
        return True
    return False


# ---------------------------------------------------------------------------
# Auto-retry sweep (called from cron_sweeper)
# ---------------------------------------------------------------------------
def auto_retry_dlq_sync(redis_client, queue_name: str = "audit_jobs") -> dict:
    """Scan the DLQ and re-enqueue entries with retry_count < DLQ_MAX_RETRY_COUNT.

    Synchronous, designed for cron_sweeper.
    Returns summary dict with counts.
    """
    from services.queue_routing import resolve_queue_for_tier

    total = redis_client.llen(DLQ_LIST_KEY)
    retried = 0
    skipped = 0
    errors = 0
    idx = 0
    while idx < total:
        raw = redis_client.lindex(DLQ_LIST_KEY, idx)
        if raw is None:
            idx += 1
            continue
        try:
            entry = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            idx += 1
            continue
        retry_count = entry.get("retry_count", 0)
        if retry_count >= DLQ_MAX_RETRY_COUNT:
            skipped += 1
            idx += 1
            continue
        job_id = entry.get("job_id", "unknown")
        original_payload = entry.get("original_payload", {})
        if not original_payload:
            skipped += 1
            idx += 1
            continue
        try:
            # Remove from DLQ
            sentinel = f"__dlq_autoretry_{job_id}"
            redis_client.lset(DLQ_LIST_KEY, idx, sentinel)
            redis_client.lrem(DLQ_LIST_KEY, 1, sentinel)
            total -= 1  # List shrank, don't increment idx
            # Re-enqueue to tier-specific queue
            original_payload["dlq_retry_count"] = retry_count + 1
            target_queue = resolve_queue_for_tier(str(original_payload.get("tier", "fast")))
            redis_client.rpush(target_queue, json.dumps(original_payload))
            # Reset job hash
            job_key = _build_job_key(job_id)
            redis_client.hset(
                job_key,
                mapping={
                    "status": "queued",
                    "dlq_retried_at": datetime.now(timezone.utc).isoformat(),
                    "dlq_retry_count": str(retry_count + 1),
                },
            )
            redis_client.expire(job_key, TTL_QUEUED)
            retried += 1
            logger.info(
                "DLQ auto-retry: job %s re-enqueued to %s (retry %s)",
                job_id,
                target_queue,
                retry_count + 1,
            )
        except Exception:
            logger.exception("DLQ auto-retry failed for job %s", job_id)
            errors += 1
            idx += 1
    return {
        "retried": retried,
        "skipped": skipped,
        "errors": errors,
        "total_remaining": redis_client.llen(DLQ_LIST_KEY),
    }


# ---------------------------------------------------------------------------
# Orphaned Redis key cleanup (called from cron_sweeper)
# ---------------------------------------------------------------------------
def cleanup_orphaned_job_keys_sync(redis_client, *, batch_size: int = 200) -> dict:
    """Scan for audit:job:* keys with no TTL and set appropriate TTL.

    Synchronous, designed for cron_sweeper.
    """
    cursor = "0"
    fixed = 0
    scanned = 0
    while True:
        cursor, keys = redis_client.scan(cursor=cursor, match="audit:job:*", count=batch_size)
        for key in keys:
            # Skip event sub-keys (audit:job:{id}:events)
            key_str = key if isinstance(key, str) else key.decode("utf-8", errors="replace")
            if ":events" in key_str:
                continue
            scanned += 1
            ttl = redis_client.ttl(key_str)
            if ttl == -1:  # No TTL set
                # Check status to decide TTL
                status = redis_client.hget(key_str, "status")
                if isinstance(status, bytes):
                    status = status.decode("utf-8", errors="replace")
                if status == "succeeded":
                    redis_client.expire(key_str, TTL_SUCCEEDED)
                elif status == "failed":
                    redis_client.expire(key_str, TTL_FAILED)
                elif status == "running":
                    redis_client.expire(key_str, TTL_IN_PROGRESS)
                elif status == "queued":
                    redis_client.expire(key_str, TTL_QUEUED)
                else:
                    # Unknown status, expire in 24h as safety
                    redis_client.expire(key_str, TTL_SUCCEEDED)
                fixed += 1
        if cursor == 0 or cursor == "0" or cursor == b"0":
            break
    return {"scanned": scanned, "fixed": fixed}


# ---------------------------------------------------------------------------
# Helper, build DLQ entry from worker context
# ---------------------------------------------------------------------------
def build_dlq_payload_from_exception(
    *,
    job_id: str,
    original_payload: dict | None,
    exc: BaseException,
    retry_count: int = 0,
    worker_id: str = "",
) -> dict:
    """Build kwargs for push_to_dlq from an exception context."""
    return {
        "job_id": job_id,
        "original_payload": original_payload,
        "error": str(exc),
        "error_traceback": traceback.format_exc(),
        "retry_count": retry_count,
        "worker_id": worker_id,
    }
