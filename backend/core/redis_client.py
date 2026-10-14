"""Centralized Redis client factory, SEC-04.

Every backend service, worker, and middleware that needs Redis should import
from this module instead of calling ``redis.from_url()`` directly.

Usage::

    from core.redis_client import get_async_redis, get_sync_redis

    # async context
    async with get_async_redis() as r:
        await r.set("key", "value")

    # sync context (passkey, ROI simulator, admin helpers)
    with get_sync_redis() as r:
        r.set("key", "value")

    # long-lived worker clients (no context-manager, caller manages lifecycle)
    client = get_async_redis_client()
    ...
    await client.aclose()
"""

from __future__ import annotations

import contextlib
import logging
import os
from typing import AsyncIterator, Iterator
from urllib.parse import urlparse

import redis as sync_redis_lib
import redis.asyncio as async_redis_lib

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default connection parameters applied to every client
# ---------------------------------------------------------------------------
_DEFAULT_SOCKET_TIMEOUT: float = 30.0
_DEFAULT_SOCKET_CONNECT_TIMEOUT: float = 3.0
_DEFAULT_HEALTH_CHECK_INTERVAL: int = 30  # seconds


def _resolve_redis_url() -> str:
    """Return the ``REDIS_URL`` from env, with a dev-safe default."""
    return os.getenv("REDIS_URL", "redis://redis:6379")


def _is_tls_url(url: str) -> bool:
    return urlparse(url).scheme in ("rediss", "rediss+sentinel")


# ---------------------------------------------------------------------------
# Async helpers
# ---------------------------------------------------------------------------


def get_async_redis_client(
    *,
    url: str | None = None,
    decode_responses: bool = True,
    socket_timeout: float = _DEFAULT_SOCKET_TIMEOUT,
    socket_connect_timeout: float = _DEFAULT_SOCKET_CONNECT_TIMEOUT,
    health_check_interval: int = _DEFAULT_HEALTH_CHECK_INTERVAL,
) -> async_redis_lib.Redis:
    """Create an async Redis client.

    Callers that hold the client for the process lifetime (workers) should
    ``await client.aclose()`` on shutdown.  For short-lived usage prefer
    :func:`get_async_redis` which is an async context-manager.
    """
    resolved = url or _resolve_redis_url()
    return async_redis_lib.from_url(
        resolved,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        health_check_interval=health_check_interval,
    )


@contextlib.asynccontextmanager
async def get_async_redis(
    *,
    url: str | None = None,
    decode_responses: bool = True,
    socket_timeout: float = _DEFAULT_SOCKET_TIMEOUT,
    socket_connect_timeout: float = _DEFAULT_SOCKET_CONNECT_TIMEOUT,
) -> AsyncIterator[async_redis_lib.Redis]:
    """Async context-manager for short-lived Redis operations."""
    client = get_async_redis_client(
        url=url,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        health_check_interval=0,  # no keepalive for ephemeral use
    )
    try:
        yield client
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Sync helpers
# ---------------------------------------------------------------------------


def get_sync_redis_client(
    *,
    url: str | None = None,
    decode_responses: bool = True,
    socket_timeout: float = _DEFAULT_SOCKET_TIMEOUT,
    socket_connect_timeout: float = _DEFAULT_SOCKET_CONNECT_TIMEOUT,
) -> sync_redis_lib.Redis:
    """Create a synchronous Redis client."""
    resolved = url or _resolve_redis_url()
    return sync_redis_lib.from_url(
        resolved,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
    )


@contextlib.contextmanager
def get_sync_redis(
    *,
    url: str | None = None,
    decode_responses: bool = True,
    socket_timeout: float = _DEFAULT_SOCKET_TIMEOUT,
    socket_connect_timeout: float = _DEFAULT_SOCKET_CONNECT_TIMEOUT,
) -> Iterator[sync_redis_lib.Redis]:
    """Sync context-manager for short-lived Redis operations."""
    client = get_sync_redis_client(
        url=url,
        decode_responses=decode_responses,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
    )
    try:
        yield client
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Startup validation (called from Settings validator or manually)
# ---------------------------------------------------------------------------


def validate_redis_url_production(url: str) -> list[str]:
    """Return a list of warnings/errors for *url* under production rules.

    Returns an empty list when the URL passes all checks.
    """
    issues: list[str] = []
    parsed = urlparse(url)

    if not parsed.hostname:
        issues.append("REDIS_URL has no hostname")
        return issues

    # Require authentication (password embedded in URL)
    if not parsed.password:
        issues.append(
            "REDIS_URL has no password, production Redis must use "
            "redis://:PASSWORD@host:port or rediss://:PASSWORD@host:port"
        )

    # Warn (non-blocking) if TLS is not used
    if not _is_tls_url(url):
        logger.warning(
            "REDIS_URL does not use TLS (rediss://). Consider enabling TLS "
            "for encrypted transport in production."
        )

    # Reject the Docker Compose dev default
    if parsed.hostname in ("redis", "localhost", "127.0.0.1") and not parsed.password:
        issues.append(
            "REDIS_URL appears to use the unauthenticated dev default, "
            "set a strong password for production"
        )

    return issues
