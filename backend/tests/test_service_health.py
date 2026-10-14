"""Tests for the best-effort, Redis-backed external service health tracker.

This complements the static "is the API key configured?" checks in
system_checks.py with what actually happened on the last real call, so a
provider that has run out of credits (still has a valid key configured)
shows up as degraded instead of Operational.
"""

import asyncio
from contextlib import asynccontextmanager

import services.service_health as service_health


def _patch_redis_store(monkeypatch, store: dict[str, str]) -> None:
    class FakeRedisClient:
        async def set(self, key, value, ex=None):
            store[key] = value

        async def get(self, key):
            return store.get(key)

    @asynccontextmanager
    async def fake_get_async_redis(**_kwargs):
        yield FakeRedisClient()

    monkeypatch.setattr(service_health, "get_async_redis", fake_get_async_redis)


def test_record_and_get_service_outcome_roundtrip(monkeypatch) -> None:
    store: dict[str, str] = {}
    _patch_redis_store(monkeypatch, store)

    asyncio.run(
        service_health.record_service_outcome(
            "firecrawl", ok=False, detail="Payment Required: Insufficient credits"
        )
    )
    result = asyncio.run(service_health.get_service_health("firecrawl"))

    assert result is not None
    assert result["ok"] is False
    assert result["detail"] == "Payment Required: Insufficient credits"
    assert "at" in result


def test_record_service_outcome_sets_an_expiry_so_stale_failures_self_clear(monkeypatch) -> None:
    recorded_ex: dict[str, int | None] = {}

    class FakeRedisClient:
        async def set(self, key, value, ex=None):
            recorded_ex["ex"] = ex

        async def get(self, key):
            return None

    @asynccontextmanager
    async def fake_get_async_redis(**_kwargs):
        yield FakeRedisClient()

    monkeypatch.setattr(service_health, "get_async_redis", fake_get_async_redis)

    asyncio.run(service_health.record_service_outcome("firecrawl", ok=True))

    assert recorded_ex["ex"] is not None and recorded_ex["ex"] > 0


def test_get_service_health_returns_none_when_nothing_recorded(monkeypatch) -> None:
    _patch_redis_store(monkeypatch, {})

    assert asyncio.run(service_health.get_service_health("firecrawl")) is None


def test_record_service_outcome_never_raises_when_redis_is_unavailable(monkeypatch) -> None:
    @asynccontextmanager
    async def broken_get_async_redis(**_kwargs):
        raise ConnectionError("redis down")
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(service_health, "get_async_redis", broken_get_async_redis)

    # Must not raise: this is an observability aid, not a hard dependency.
    asyncio.run(service_health.record_service_outcome("firecrawl", ok=True))


def test_get_service_health_returns_none_when_redis_is_unavailable(monkeypatch) -> None:
    @asynccontextmanager
    async def broken_get_async_redis(**_kwargs):
        raise ConnectionError("redis down")
        yield  # pragma: no cover - never reached

    monkeypatch.setattr(service_health, "get_async_redis", broken_get_async_redis)

    assert asyncio.run(service_health.get_service_health("firecrawl")) is None
