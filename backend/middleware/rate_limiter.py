import asyncio
import hashlib
import logging
import time
from typing import Dict, Tuple

from fastapi import HTTPException, Request

from core.client_ip import resolve_client_ip
from core.redis_client import get_async_redis
from core.runtime_config import get_config_value
from database import SessionLocal

logger = logging.getLogger(__name__)

# Config value cache with TTL to avoid hitting DB on every request
_CONFIG_CACHE: Dict[str, Tuple[int, float]] = {}
_CONFIG_CACHE_TTL = 60.0  # seconds

LOGIN_RATE_LIMIT_DETAIL = "Too many login attempts. Please try again later."


def _get_cached_config(key: str) -> int:
    """Read a rate-limit config value, returning a cached result when fresh."""
    now = time.time()
    cached = _CONFIG_CACHE.get(key)
    if cached and now - cached[1] < _CONFIG_CACHE_TTL:
        return cached[0]

    db = SessionLocal()
    try:
        value = int(get_config_value(key, db))
    finally:
        db.close()
    _CONFIG_CACHE[key] = (value, now)
    return value


def _account_fingerprint(username: str) -> str:
    # Hash the normalized account identifier so raw emails never land in
    # Redis keys.
    return hashlib.sha256((username or "").strip().lower().encode("utf-8")).hexdigest()


def _account_key(client_ip: str, username: str) -> str:
    return f"ratelimit:login:acct:{client_ip}:{_account_fingerprint(username)}"


def _ip_key(client_ip: str) -> str:
    return f"ratelimit:login:ip:{client_ip}"


class RateLimiter:
    """Redis-backed failed-login limiter, shared across worker processes.

    Two counters are kept per resolved client IP:

    * ``ratelimit:login:acct:{ip}:{sha256(email)}`` bounds failures for one
      account behind one IP and is cleared on a successful login, so a
      forgotten password does not lock out everyone behind the same NAT.
    * ``ratelimit:login:ip:{ip}`` bounds total failures from one IP and is
      never cleared by a successful login, so credential spraying across
      many accounts cannot launder its own counter.

    Both increment only on a failed authentication, never per request, and
    both fail open (with an ERROR log) when Redis is unavailable, consistent
    with the shared ``enforce_rate_limit`` helper (SIGV2-1242).
    """

    async def ensure_login_allowed(self, request: Request, username: str) -> None:
        """Raise a uniform 429 when either counter is exhausted.

        Runs before authentication and returns the same response for known
        and unknown accounts, so it cannot be used to enumerate accounts.
        """
        client_ip = resolve_client_ip(request)
        account_limit = _get_cached_config("LOGIN_RATE_LIMIT")
        ip_limit = _get_cached_config("LOGIN_IP_RATE_LIMIT")
        try:
            async with get_async_redis() as client:
                account_fails, ip_fails = await asyncio.gather(
                    client.get(_account_key(client_ip, username)),
                    client.get(_ip_key(client_ip)),
                )
        except Exception as exc:
            logger.error("RATE_LIMIT_CHECK_UNAVAILABLE: %s", exc)
            return

        if (account_fails is not None and int(account_fails) >= account_limit) or (
            ip_fails is not None and int(ip_fails) >= ip_limit
        ):
            raise HTTPException(status_code=429, detail=LOGIN_RATE_LIMIT_DETAIL)

    async def record_login_failure(self, request: Request, username: str) -> None:
        client_ip = resolve_client_ip(request)
        account_window = _get_cached_config("LOGIN_RATE_WINDOW")
        ip_window = _get_cached_config("LOGIN_IP_RATE_WINDOW")
        try:
            async with get_async_redis() as client:
                for key, window in (
                    (_account_key(client_ip, username), account_window),
                    (_ip_key(client_ip), ip_window),
                ):
                    current = await client.incr(key)
                    if current == 1:
                        await client.expire(key, window)
        except Exception as exc:
            logger.error("RATE_LIMIT_CHECK_UNAVAILABLE: %s", exc)

    async def reset_login_failures(self, request: Request, username: str) -> None:
        """Clear the per-(IP, account) counter after a successful login.

        The per-IP counter is deliberately left alone so one valid account
        cannot reset the spray budget for the whole address.
        """
        client_ip = resolve_client_ip(request)
        try:
            async with get_async_redis() as client:
                await client.delete(_account_key(client_ip, username))
        except Exception as exc:
            logger.error("RATE_LIMIT_CHECK_UNAVAILABLE: %s", exc)


rate_limiter = RateLimiter()
