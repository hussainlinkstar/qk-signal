"""SIGV2-1246: the OAuth one-time code exchange must be atomic.

The previous implementation issued GET and DELETE as two separate pipeline
operations, so two concurrent exchanges of the same code could both read the
value before either deleted it. These tests fake Redis with a client that only
exposes atomic GETDEL semantics; a GET-then-DELETE implementation fails them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json

import pytest

import routers.auth as auth_router


class _FakeRedisClient:
    """Minimal in-memory Redis stub with atomic getdel only."""

    def __init__(self, store: dict[str, str]):
        self._store = store
        self.getdel_calls = 0

    async def getdel(self, key: str):
        self.getdel_calls += 1
        # Pop is atomic: a concurrent caller that runs after this sees None.
        return self._store.pop(key, None)


def _patch_redis(monkeypatch, store: dict[str, str]) -> _FakeRedisClient:
    client = _FakeRedisClient(store)

    @contextlib.asynccontextmanager
    async def _fake_get_async_redis():
        yield client

    monkeypatch.setattr(auth_router, "get_async_redis", _fake_get_async_redis)
    return client


@pytest.mark.asyncio
async def test_exchange_oauth_code_returns_tokens_and_consumes_code(monkeypatch):
    store = {"oauth:code:abc": json.dumps({"access_token": "at", "refresh_token": "rt"})}
    client = _patch_redis(monkeypatch, store)

    tokens = await auth_router._exchange_oauth_code("abc")

    assert tokens == {"access_token": "at", "refresh_token": "rt"}
    assert client.getdel_calls == 1
    assert store == {}


@pytest.mark.asyncio
async def test_exchange_oauth_code_is_single_use(monkeypatch):
    store = {"oauth:code:abc": json.dumps({"access_token": "at", "refresh_token": "rt"})}
    _patch_redis(monkeypatch, store)

    first = await auth_router._exchange_oauth_code("abc")
    second = await auth_router._exchange_oauth_code("abc")

    assert first is not None
    assert second is None


@pytest.mark.asyncio
async def test_exchange_oauth_code_concurrent_callers_only_one_wins(monkeypatch):
    store = {"oauth:code:abc": json.dumps({"access_token": "at", "refresh_token": "rt"})}
    _patch_redis(monkeypatch, store)

    results = await asyncio.gather(*(auth_router._exchange_oauth_code("abc") for _ in range(5)))

    winners = [r for r in results if r is not None]
    assert len(winners) == 1
    assert winners[0]["access_token"] == "at"


@pytest.mark.asyncio
async def test_exchange_oauth_code_unknown_code_returns_none(monkeypatch):
    _patch_redis(monkeypatch, {})

    assert await auth_router._exchange_oauth_code("nope") is None
