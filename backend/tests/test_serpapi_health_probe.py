"""The SerpAPI status row must reflect a real probe, not key presence.

Production ran with a SerpAPI key that the provider rejects with HTTP 401
while the public status page advertised "Operational", because the check only
asked whether the key string was non-empty.
"""

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

import services.serpapi_health as serpapi_health

API_KEY = "serpapi-test-key-value"


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClientFactory:
    """Stands in for httpx.AsyncClient and records every outbound attempt."""

    def __init__(self, *, status_code: int | None = None, error: Exception | None = None) -> None:
        self.status_code = status_code
        self.error = error
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, *_args, **_kwargs):
        factory = self

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_exc_info):
                return False

            async def get(self, url, params=None):
                factory.calls.append((url, dict(params or {})))
                if factory.error is not None:
                    raise factory.error
                return _FakeResponse(factory.status_code or 200)

        return _FakeAsyncClient()


@pytest.fixture(autouse=True)
def _isolated_caches(monkeypatch):
    """No cross-test cache bleed and never a real Redis connection."""
    serpapi_health._local_cache.clear()

    class _FakeRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}

        async def get(self, key):
            return self.store.get(key)

        async def set(self, key, value, ex=None):
            self.store[key] = value

    shared = _FakeRedis()

    @asynccontextmanager
    async def fake_get_async_redis(**_kwargs):
        yield shared

    monkeypatch.setattr(serpapi_health, "get_async_redis", fake_get_async_redis)
    yield shared
    serpapi_health._local_cache.clear()


def test_rejected_api_key_is_reported_as_invalid_not_operational(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=401)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert result["state"] == serpapi_health.PROBE_INVALID_KEY
    assert "HTTP 401" in result["detail"]
    assert len(client_factory.calls) == 1
    assert client_factory.calls[0][0].endswith("/account.json")


def test_accepted_api_key_is_reported_as_operational(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=200)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert result["state"] == serpapi_health.PROBE_OPERATIONAL


def test_rate_limited_provider_is_reported_as_rate_limited(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=429)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert result["state"] == serpapi_health.PROBE_RATE_LIMITED


def test_network_failure_fails_closed_to_unknown(monkeypatch) -> None:
    client_factory = _FakeClientFactory(error=httpx.ConnectTimeout("timed out"))
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert result["state"] == serpapi_health.PROBE_UNKNOWN
    assert result["state"] != serpapi_health.PROBE_OPERATIONAL


def test_unexpected_status_code_fails_closed_to_unknown(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=500)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert result["state"] == serpapi_health.PROBE_UNKNOWN
    assert "HTTP 500" in result["detail"]


def test_probe_result_is_cached_so_the_public_page_cannot_amplify_requests(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=401)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    first = asyncio.run(serpapi_health.probe_serpapi(API_KEY))
    second = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert first == second
    assert len(client_factory.calls) == 1


def test_cached_verdict_is_shared_across_processes_via_redis(monkeypatch, _isolated_caches) -> None:
    client_factory = _FakeClientFactory(status_code=401)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    asyncio.run(serpapi_health.probe_serpapi(API_KEY))
    # Simulate a second worker process: same shared cache, empty local cache.
    serpapi_health._local_cache.clear()
    second = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert second["state"] == serpapi_health.PROBE_INVALID_KEY
    assert len(client_factory.calls) == 1


def test_probe_still_throttles_when_redis_is_unavailable(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=401)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    @asynccontextmanager
    async def broken_get_async_redis(**_kwargs):
        raise RuntimeError("redis is down")
        yield  # pragma: no cover

    monkeypatch.setattr(serpapi_health, "get_async_redis", broken_get_async_redis)

    asyncio.run(serpapi_health.probe_serpapi(API_KEY))
    asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert len(client_factory.calls) == 1


def test_api_key_never_appears_in_the_cache_key_or_the_detail(
    monkeypatch, _isolated_caches
) -> None:
    error = httpx.ConnectError(
        f"failed connecting to https://serpapi.com/account.json?api_key={API_KEY}"
    )
    client_factory = _FakeClientFactory(error=error)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi(API_KEY))

    assert API_KEY not in result["detail"]
    assert all(API_KEY not in key for key in _isolated_caches.store)
    assert all(API_KEY not in value for value in _isolated_caches.store.values())
    assert all(API_KEY not in fingerprint for fingerprint in serpapi_health._local_cache)


def test_empty_key_is_never_probed(monkeypatch) -> None:
    client_factory = _FakeClientFactory(status_code=200)
    monkeypatch.setattr(serpapi_health.httpx, "AsyncClient", client_factory)

    result = asyncio.run(serpapi_health.probe_serpapi("   "))

    assert result["state"] == serpapi_health.PROBE_UNKNOWN
    assert client_factory.calls == []
