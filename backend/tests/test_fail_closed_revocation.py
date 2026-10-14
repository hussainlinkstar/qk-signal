"""SIGV2-1242: Redis-backed auth/security controls must not silently fail open.

Decisions recorded per control:

* ``_is_token_denied`` (refresh deny list) fails CLOSED: when Redis cannot be
  consulted the refresh is rejected with 503, because this path mints new
  credentials and must not issue them on an unverifiable token.
* ``SessionRevocationMiddleware`` fails CLOSED: a Redis outage returns 503 for
  requests carrying a JWT JTI, while tokens that do not decode or carry no JTI
  keep their existing behaviour (downstream verifies them fully).
* ``_acquire_resend_verification_slot`` stays fail-OPEN (email verification is
  not blocked fleet-wide by Redis) but logs at ERROR with a distinct code.
* ``enforce_rate_limit`` stays fail-OPEN, same ERROR-level alerting.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import middleware.session_checker as session_checker
import routers.api_router as api_router
import routers.auth as auth_router


def _failing_redis(monkeypatch, module) -> None:
    @contextlib.asynccontextmanager
    async def _failing():
        raise ConnectionError("redis unavailable")
        yield  # pragma: no cover - unreachable

    monkeypatch.setattr(module, "get_async_redis", _failing)


@pytest.mark.asyncio
async def test_is_token_denied_fails_closed_on_redis_error(monkeypatch, caplog):
    _failing_redis(monkeypatch, auth_router)

    with caplog.at_level(logging.ERROR, logger="routers.auth"):
        with pytest.raises(HTTPException) as exc_info:
            await auth_router._is_token_denied("some-refresh-token")

    assert exc_info.value.status_code == 503
    assert "revocation" in exc_info.value.detail.lower()
    assert "AUTH_DENYLIST_UNAVAILABLE" in caplog.text


@pytest.mark.asyncio
async def test_is_token_denied_returns_true_when_denied(monkeypatch):
    class _FakeRedis:
        async def exists(self, _key):
            return 1

    @contextlib.asynccontextmanager
    async def _fake_cm():
        yield _FakeRedis()

    monkeypatch.setattr(auth_router, "get_async_redis", _fake_cm)

    assert await auth_router._is_token_denied("revoked-token") is True


def _middleware_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(session_checker.SessionRevocationMiddleware)

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


def test_session_checker_fails_closed_on_redis_error(monkeypatch, caplog):
    _failing_redis(monkeypatch, session_checker)
    token = jwt.encode({"sub": "u1", "jti": "jti-1"}, "irrelevant", algorithm="HS256")

    client = TestClient(_middleware_app())
    with caplog.at_level(logging.ERROR, logger="middleware.session_checker"):
        response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 503
    assert "SESSION_REVOCATION_UNAVAILABLE" in caplog.text


def test_session_checker_still_rejects_revoked_jti(monkeypatch):
    class _FakeRedis:
        async def exists(self, _key):
            return 1

    @contextlib.asynccontextmanager
    async def _fake_cm():
        yield _FakeRedis()

    monkeypatch.setattr(session_checker, "get_async_redis", _fake_cm)
    token = jwt.encode({"sub": "u1", "jti": "jti-1"}, "irrelevant", algorithm="HS256")

    client = TestClient(_middleware_app())
    response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_session_checker_passes_token_without_jti(monkeypatch):
    _failing_redis(monkeypatch, session_checker)
    token = jwt.encode({"sub": "u1"}, "irrelevant", algorithm="HS256")

    client = TestClient(_middleware_app())
    response = client.get("/ping", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_session_checker_passes_undecodable_token(monkeypatch):
    _failing_redis(monkeypatch, session_checker)

    client = TestClient(_middleware_app())
    response = client.get("/ping", headers={"Authorization": "Bearer not-a-jwt"})

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_resend_slot_fails_open_but_logs_error(monkeypatch, caplog):
    _failing_redis(monkeypatch, auth_router)

    with caplog.at_level(logging.ERROR, logger="routers.auth"):
        allowed = await auth_router._acquire_resend_verification_slot("user@example.com")

    assert allowed is True
    assert "RESEND_VERIFICATION_THROTTLE_UNAVAILABLE" in caplog.text


@pytest.mark.asyncio
async def test_enforce_rate_limit_fails_open_but_logs_error(monkeypatch, caplog):
    _failing_redis(monkeypatch, api_router)

    with caplog.at_level(logging.ERROR, logger="routers.api_router"):
        await api_router.enforce_rate_limit(
            key_prefix="guest_audit",
            identifier="198.51.100.7:ua",
            limit=1,
            window_seconds=60,
        )

    assert "RATE_LIMIT_CHECK_UNAVAILABLE" in caplog.text


@pytest.mark.asyncio
async def test_enforce_rate_limit_still_throttles(monkeypatch):
    class _FakeRedis:
        def __init__(self):
            self.counts: dict[str, int] = {}

        async def incr(self, key):
            self.counts[key] = self.counts.get(key, 0) + 1
            return self.counts[key]

        async def expire(self, _key, _ttl):
            return True

    fake = _FakeRedis()

    @contextlib.asynccontextmanager
    async def _fake_cm():
        yield fake

    monkeypatch.setattr(api_router, "get_async_redis", _fake_cm)

    await api_router.enforce_rate_limit(
        key_prefix="guest_audit", identifier="ip:ua", limit=1, window_seconds=60
    )
    with pytest.raises(HTTPException) as exc_info:
        await api_router.enforce_rate_limit(
            key_prefix="guest_audit", identifier="ip:ua", limit=1, window_seconds=60
        )
    assert exc_info.value.status_code == 429
