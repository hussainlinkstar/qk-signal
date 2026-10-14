from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException
from starlette.requests import Request

import main


class FakeRedisClient:
    counters: dict[str, int] = {}
    expirations: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        current = self.counters.get(key, 0) + 1
        self.counters[key] = current
        return current

    async def expire(self, key: str, seconds: int) -> None:
        self.expirations[key] = seconds

    async def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio
async def test_enforce_authenticated_audit_limit_returns_429_after_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    FakeRedisClient.counters.clear()
    FakeRedisClient.expirations.clear()
    monkeypatch.setenv("RATE_LIMIT_AUDIT", "2/min")
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *args, **kwargs: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *args, **kwargs: FakeRedisClient()
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/audit",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )
    user = SimpleNamespace(id=42)

    await main.enforce_authenticated_audit_limit(user, request)
    await main.enforce_authenticated_audit_limit(user, request)

    with pytest.raises(HTTPException) as exc_info:
        await main.enforce_authenticated_audit_limit(user, request)

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Too Many Requests"


@pytest.mark.asyncio
async def test_enforce_guest_audit_limit_cannot_be_bypassed_with_a_localhost_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: Origin is caller-supplied, so it must not exempt the
    guest-audit limiter. Before the fix, `Origin: http://localhost` skipped it."""
    FakeRedisClient.counters.clear()
    FakeRedisClient.expirations.clear()
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("RATE_LIMIT_GUEST_AUDIT", "1/min")
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *args, **kwargs: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *args, **kwargs: FakeRedisClient()
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/audit",
            "headers": [(b"origin", b"http://localhost")],
            "client": ("203.0.113.9", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )

    await main.enforce_guest_audit_limit(request)

    with pytest.raises(HTTPException) as exc_info:
        await main.enforce_guest_audit_limit(request)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_parse_rate_limit_config_supports_short_minute_format() -> None:
    limit, window_seconds = main.parse_rate_limit_config(
        "10/min", default_limit=1, default_window_seconds=5
    )

    assert limit == 10
    assert window_seconds == 60


@pytest.mark.asyncio
async def test_parse_rate_limit_config_falls_back_to_default_for_invalid_value() -> None:
    limit, window_seconds = main.parse_rate_limit_config(
        "nonsense", default_limit=7, default_window_seconds=90
    )

    assert limit == 7
    assert window_seconds == 90
