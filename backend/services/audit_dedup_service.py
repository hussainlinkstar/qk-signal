"""Audit submission deduplication service.

Prevents duplicate concurrent audits for the same target by maintaining
short-lived Redis keys.  Each key is scoped to a user, normalised target,
tier, and (optionally) project so that intentional re-audits on different
tiers or projects are not blocked.

Redis key pattern:
    audit:dedup:{user_id}:{normalised_subject}:{tier}[:{project_id}]
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# TTL should cover the longest possible audit duration with margin.
# JOB_TIMEOUT_SECONDS in queue_worker is 900 s; we add headroom for queue
# wait and retry loops.
DEDUP_TTL_SECONDS = 1200  # 20 min

DEDUP_KEY_PREFIX = "audit:dedup"


# ---------------------------------------------------------------------------
# URL normalisation (stricter than url_validation.normalize_and_validate_url)
# ---------------------------------------------------------------------------


def _normalise_url_for_dedup(raw_url: str) -> str:
    """Return a compact, case-insensitive key fragment for *raw_url*.

    Strips ``www.``, lowercases host+path, removes default ports and
    trailing slashes so that cosmetically-different URLs pointing at the
    same page resolve to the same dedup key.
    """
    parsed = urlparse(raw_url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    # Strip default ports
    port = parsed.port
    if port in (80, 443, None):
        port_suffix = ""
    else:
        port_suffix = f":{port}"
    path = (parsed.path or "/").rstrip("/") or "/"
    query = parsed.query or ""
    fragment = ""  # ignore fragments for dedup
    normalised = f"{host}{port_suffix}{path}"
    if query:
        normalised += f"?{query}"
    if fragment:
        normalised += f"#{fragment}"
    return normalised


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------


def build_dedup_key(
    *,
    user_id: int,
    target_url: str | None,
    target_name: str | None,
    tier: str,
    project_id: int | None = None,
) -> str:
    """Build a Redis dedup key for the given audit parameters."""
    if target_url and target_url.strip():
        subject = _normalise_url_for_dedup(target_url)
    elif target_name and target_name.strip():
        subject = target_name.strip().lower()
    else:
        # Fallback, should not happen in practice.
        subject = "unknown"

    # Hash the subject to avoid extremely long Redis keys.
    subject_hash = hashlib.sha256(subject.encode()).hexdigest()[:16]
    key = f"{DEDUP_KEY_PREFIX}:{user_id}:{subject_hash}:{tier}"
    if project_id is not None:
        key += f":{project_id}"
    return key


# ---------------------------------------------------------------------------
# Redis helpers (async)
# ---------------------------------------------------------------------------


async def check_dedup(redis_client, key: str) -> str | None:
    """Return the existing job_id if a dedup key is set, else ``None``."""
    existing = await redis_client.get(key)
    if existing:
        return existing.decode() if isinstance(existing, bytes) else str(existing)
    return None


async def set_dedup(redis_client, key: str, job_id: str, ttl: int = DEDUP_TTL_SECONDS) -> None:
    """Atomically set the dedup key if it does not already exist."""
    await redis_client.setex(key, ttl, job_id)


async def clear_dedup(redis_client, key: str) -> None:
    """Remove a dedup key (idempotent)."""
    try:
        await redis_client.delete(key)
    except Exception:
        logger.debug("Failed to clear dedup key %s", key, exc_info=True)


async def clear_dedup_for_job(redis_client, *, job) -> None:
    """Derive and clear the dedup key for a completed/failed job.

    *job* must be an ``AuditJobPayload`` (or any object exposing the same
    attributes).
    """
    try:
        key = build_dedup_key(
            user_id=job.user_id,
            target_url=job.url or job.target_url,
            target_name=job.target_name,
            tier=job.requested_tier or job.tier,
            project_id=job.project_id,
        )
        await clear_dedup(redis_client, key)
    except Exception:
        logger.debug(
            "Failed to clear dedup key for job %s",
            getattr(job, "job_id", "?"),
            exc_info=True,
        )
