"""Real SerpAPI reachability probe for the System Status page.

A configured ``SERPAPI_API_KEY`` says nothing about whether SerpAPI will
accept it: a revoked or expired key is still a non-empty string, so a
presence-only check publishes "Operational" while every GEO visibility query
fails with HTTP 401. This module asks SerpAPI itself.

Design constraints, because the public status page is unauthenticated:

* Cheap: it calls the account endpoint, which consumes no search credits.
* Cached: one probe per TTL is shared across processes through Redis, with an
  in-process fallback so a Redis outage cannot turn the status page into a
  request amplifier against SerpAPI.
* Bounded: a short timeout, so the status page is never held up by SerpAPI.
* Fail closed: anything that is not a definitive answer resolves to "unknown",
  never to "operational".
* Leak free: the key is never logged, cached, or echoed in a detail string.
  Cache keys use a truncated digest so key rotation invalidates the cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from core.config import settings
from core.redis_client import get_async_redis
from services.observability import describe_http_failure

logger = logging.getLogger(__name__)

PROBE_OPERATIONAL = "operational"
PROBE_INVALID_KEY = "invalid_key"
PROBE_RATE_LIMITED = "rate_limited"
PROBE_UNKNOWN = "unknown"

_DEFAULT_ACCOUNT_URL = "https://serpapi.com/account.json"
_PROBE_TIMEOUT_SECONDS = 2.5
# A definitive verdict is cached long enough that the public page cannot
# hammer SerpAPI; an inconclusive one expires quickly so a transient network
# blip does not pin the row to "unknown" for the rest of the window.
_CACHE_TTL_SECONDS = 600
_UNKNOWN_CACHE_TTL_SECONDS = 60
_CACHE_KEY_PREFIX = "service_probe:serpapi:"

_local_cache: dict[str, tuple[float, dict[str, str]]] = {}


def _account_url() -> str:
    """Account endpoint derived from the configured SerpAPI search URL."""
    configured = str(getattr(settings, "SERPAPI_URL", "") or "").strip()
    if not configured:
        return _DEFAULT_ACCOUNT_URL
    try:
        parts = urlsplit(configured)
    except ValueError:
        return _DEFAULT_ACCOUNT_URL
    if not parts.scheme or not parts.netloc:
        return _DEFAULT_ACCOUNT_URL
    return f"{parts.scheme}://{parts.netloc}/account.json"


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]


def _ttl_for(result: dict[str, str]) -> int:
    return _UNKNOWN_CACHE_TTL_SECONDS if result["state"] == PROBE_UNKNOWN else _CACHE_TTL_SECONDS


def _read_local_cache(fingerprint: str) -> dict[str, str] | None:
    entry = _local_cache.get(fingerprint)
    if not entry:
        return None
    expires_at, result = entry
    if expires_at <= time.monotonic():
        _local_cache.pop(fingerprint, None)
        return None
    return result


def _write_local_cache(fingerprint: str, result: dict[str, str]) -> None:
    # Only the current key is ever of interest, so the cache is reset instead
    # of accumulating an entry per rotated key.
    _local_cache.clear()
    _local_cache[fingerprint] = (time.monotonic() + _ttl_for(result), result)


async def _read_shared_cache(fingerprint: str) -> dict[str, str] | None:
    try:
        async with get_async_redis(socket_timeout=1.0, socket_connect_timeout=1.0) as redis_client:
            raw = await redis_client.get(f"{_CACHE_KEY_PREFIX}{fingerprint}")
    except Exception:
        logger.debug("serpapi probe: shared cache read failed", exc_info=True)
        return None
    if not raw:
        return None
    try:
        cached: Any = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(cached, dict) and isinstance(cached.get("state"), str):
        return {"state": cached["state"], "detail": str(cached.get("detail") or "")}
    return None


async def _write_shared_cache(fingerprint: str, result: dict[str, str]) -> None:
    try:
        async with get_async_redis(socket_timeout=1.0, socket_connect_timeout=1.0) as redis_client:
            await redis_client.set(
                f"{_CACHE_KEY_PREFIX}{fingerprint}",
                json.dumps(result),
                ex=_ttl_for(result),
            )
    except Exception:
        logger.debug("serpapi probe: shared cache write failed", exc_info=True)


async def _run_probe(api_key: str) -> dict[str, str]:
    url = _account_url()
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT_SECONDS) as client:
            response = await client.get(url, params={"api_key": api_key})
    except Exception as exc:
        # Fail closed: an unreachable provider is unverified, not healthy.
        return {
            "state": PROBE_UNKNOWN,
            "detail": f"SerpAPI health probe did not complete ({describe_http_failure(url, exc)}).",
        }

    status_code = response.status_code
    if status_code == 200:
        return {"state": PROBE_OPERATIONAL, "detail": ""}
    if status_code in (401, 403):
        return {
            "state": PROBE_INVALID_KEY,
            "detail": (
                f"SerpAPI rejected the configured API key (HTTP {status_code}). "
                "Search-backed GEO visibility queries will fail until it is replaced."
            ),
        }
    if status_code == 429:
        return {
            "state": PROBE_RATE_LIMITED,
            "detail": "SerpAPI is rate limiting or the plan quota is exhausted (HTTP 429).",
        }
    return {
        "state": PROBE_UNKNOWN,
        "detail": f"SerpAPI health probe returned an unexpected response (HTTP {status_code}).",
    }


async def probe_serpapi(api_key: str) -> dict[str, str]:
    """Return the cached or freshly probed SerpAPI verdict for *api_key*.

    Never raises: any failure resolves to ``{"state": "unknown"}``.
    """
    key = str(api_key or "").strip()
    if not key:
        return {"state": PROBE_UNKNOWN, "detail": "No SerpAPI API key to probe."}

    fingerprint = _fingerprint(key)
    cached = _read_local_cache(fingerprint)
    if cached is not None:
        return cached

    cached = await _read_shared_cache(fingerprint)
    if cached is not None:
        _write_local_cache(fingerprint, cached)
        return cached

    result = await _run_probe(key)
    _write_local_cache(fingerprint, result)
    await _write_shared_cache(fingerprint, result)
    return result
