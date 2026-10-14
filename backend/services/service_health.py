"""Lightweight, best-effort tracking of real-time external service health.

`system_checks.py` mostly answers "is an API key configured?", which says
nothing about whether that provider is actually working right now (e.g. a
paid account that has run out of credits still has a perfectly valid key).
This module lets a service record the outcome of its real calls so the
System Status page can reflect what is actually happening instead of just
key presence.

Failures to read or write this signal are swallowed: this is an
observability aid, never a dependency request handling can fail on.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from core.redis_client import get_async_redis

logger = logging.getLogger(__name__)

_KEY_PREFIX = "service_health:"
# A stale failure record should not haunt the status page forever once the
# provider recovers and stops being called with fresh outcomes.
_TTL_SECONDS = 30 * 60
_MAX_DETAIL_LENGTH = 500


async def record_service_outcome(service: str, *, ok: bool, detail: str = "") -> None:
    """Best-effort record of the outcome of a real call to *service*."""
    payload = {
        "ok": ok,
        "detail": str(detail or "").strip()[:_MAX_DETAIL_LENGTH],
        "at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with get_async_redis(socket_timeout=1.0, socket_connect_timeout=1.0) as redis_client:
            await redis_client.set(f"{_KEY_PREFIX}{service}", json.dumps(payload), ex=_TTL_SECONDS)
    except Exception:
        logger.debug(
            "record_service_outcome: failed to record health for %s", service, exc_info=True
        )


async def get_service_health(service: str) -> dict[str, Any] | None:
    """Return the last recorded outcome for *service*, or None if unknown."""
    try:
        async with get_async_redis(socket_timeout=1.0, socket_connect_timeout=1.0) as redis_client:
            raw = await redis_client.get(f"{_KEY_PREFIX}{service}")
    except Exception:
        logger.debug("get_service_health: failed to read health for %s", service, exc_info=True)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None
