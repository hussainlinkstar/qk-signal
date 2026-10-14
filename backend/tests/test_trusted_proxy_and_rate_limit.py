"""SIGV2-1243: client IP must honor a trusted-proxy list, and the login rate
limit must live on shared Redis state instead of a per-process dict.

Topology check (docker-compose.vps.yml + deploy/Caddyfile): traffic reaches
the backend as Traefik -> Caddy -> Next.js BFF proxy -> backend:8000, all on
Docker private networks, so the immediate peer is always a private/loopback
address. The default trusted-proxy CIDRs therefore cover loopback plus
RFC1918; anything else must not be able to spoof identity headers.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException, Request
from starlette.datastructures import Address, Headers, URL

import middleware.rate_limiter as rate_limiter_module
import routers.api_router as api_router
from core.password_hashing import hash_password
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import models
from database import Base
from main import app, get_db


def _request(
    client_host: str, headers: dict[str, str] | None = None, path: str = "/api/v1/auth/login"
) -> MagicMock:
    request = MagicMock(spec=Request)
    request.client = Address(host=client_host, port=443)
    request.headers = Headers(headers or {})
    request.url = URL(f"http://testserver{path}")
    return request


def test_spoofed_xff_from_untrusted_peer_is_ignored():
    request = _request("203.0.113.10", {"x-forwarded-for": "6.6.6.6"})
    assert api_router._resolve_client_ip(request) == "203.0.113.10"


def test_all_spoofable_headers_ignored_from_untrusted_peer():
    request = _request(
        "203.0.113.10",
        {
            "cf-connecting-ip": "6.6.6.6",
            "x-real-ip": "7.7.7.7",
            "x-forwarded-for": "8.8.8.8",
        },
    )
    assert api_router._resolve_client_ip(request) == "203.0.113.10"


def test_trusted_private_peer_forwards_header_ip():
    request = _request("172.18.0.2", {"x-forwarded-for": "6.6.6.6"})
    assert api_router._resolve_client_ip(request) == "6.6.6.6"


def test_cf_and_real_ip_headers_are_never_honored():
    """Verified on preprod: forged cf-connecting-ip / x-real-ip survive the
    Traefik -> Caddy -> BFF chain, so they are attacker-controlled even when
    the peer is trusted and must not be consulted."""
    request = _request(
        "127.0.0.1",
        {"cf-connecting-ip": "6.6.6.6", "x-real-ip": "7.7.7.7"},
    )
    assert api_router._resolve_client_ip(request) == "127.0.0.1"


def test_client_injected_xff_entry_is_skipped():
    """An appending edge produces 'spoofed, real_client, <trusted hops>'; the
    resolver must return the rightmost untrusted entry, not the leftmost."""
    request = _request(
        "172.18.0.2",
        {"x-forwarded-for": "9.9.9.9, 82.76.117.27, 10.0.0.5"},
    )
    assert api_router._resolve_client_ip(request) == "82.76.117.27"


def test_xff_rightmost_untrusted_wins_over_trusted_hops():
    request = _request(
        "10.1.2.3",
        {"x-forwarded-for": "203.0.113.55, 172.16.4.4"},
    )
    assert api_router._resolve_client_ip(request) == "203.0.113.55"


def test_xff_all_trusted_falls_back_to_peer():
    request = _request("172.18.0.2", {"x-forwarded-for": "10.0.0.5, 192.168.1.1"})
    assert api_router._resolve_client_ip(request) == "172.18.0.2"


def _patch_login_limits(monkeypatch, account_limit=5, ip_limit=30):
    monkeypatch.setattr(
        rate_limiter_module,
        "_get_cached_config",
        lambda key: {
            "LOGIN_RATE_LIMIT": account_limit,
            "LOGIN_RATE_WINDOW": 900,
            "LOGIN_IP_RATE_LIMIT": ip_limit,
            "LOGIN_IP_RATE_WINDOW": 300,
        }[key],
    )


@pytest.mark.asyncio
async def test_account_locks_out_after_limit_failures(monkeypatch):
    _patch_login_limits(monkeypatch)
    limiter = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    for _ in range(5):
        await limiter.ensure_login_allowed(request, "user@example.com")
        await limiter.record_login_failure(request, "user@example.com")

    with pytest.raises(HTTPException) as exc_info:
        await limiter.ensure_login_allowed(request, "user@example.com")
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_second_account_on_same_ip_still_allowed(monkeypatch):
    """Locking out one account must not lock out the whole NATed office."""
    _patch_login_limits(monkeypatch)
    limiter = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    for _ in range(5):
        await limiter.record_login_failure(request, "user-a@example.com")

    with pytest.raises(HTTPException):
        await limiter.ensure_login_allowed(request, "user-a@example.com")
    await limiter.ensure_login_allowed(request, "user-b@example.com")


@pytest.mark.asyncio
async def test_successful_login_resets_account_counter(monkeypatch):
    _patch_login_limits(monkeypatch)
    limiter = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    for _ in range(5):
        await limiter.record_login_failure(request, "user@example.com")
    await limiter.reset_login_failures(request, "user@example.com")

    await limiter.ensure_login_allowed(request, "user@example.com")


@pytest.mark.asyncio
async def test_ip_spray_ceiling_blocks_every_account(monkeypatch):
    """30 failures across different accounts exhaust the per-IP budget, even
    for an account that never failed, and a successful login must not clear
    the spray counter."""
    _patch_login_limits(monkeypatch)
    limiter = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    for index in range(30):
        await limiter.record_login_failure(request, f"acct-{index}@example.com")

    await limiter.reset_login_failures(request, "legit@example.com")
    with pytest.raises(HTTPException) as exc_info:
        await limiter.ensure_login_allowed(request, "never-failed@example.com")
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_counters_are_shared_across_limiter_instances(monkeypatch):
    """Two RateLimiter objects (as in separate worker processes) must share
    counters, which is only true if the state lives in Redis."""
    _patch_login_limits(monkeypatch)
    limiter_a = rate_limiter_module.RateLimiter()
    limiter_b = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    for _ in range(5):
        await limiter_a.record_login_failure(request, "user@example.com")

    with pytest.raises(HTTPException):
        await limiter_b.ensure_login_allowed(request, "user@example.com")


@pytest.mark.asyncio
async def test_login_rate_limit_fails_open_on_redis_error(monkeypatch, caplog):
    _patch_login_limits(monkeypatch)

    @contextlib.asynccontextmanager
    async def _failing():
        raise ConnectionError("redis unavailable")
        yield  # pragma: no cover - unreachable

    monkeypatch.setattr(rate_limiter_module, "get_async_redis", _failing)
    limiter = rate_limiter_module.RateLimiter()
    request = _request("203.0.113.10")

    with caplog.at_level(logging.ERROR, logger="middleware.rate_limiter"):
        await limiter.ensure_login_allowed(request, "user@example.com")
        await limiter.record_login_failure(request, "user@example.com")
        await limiter.reset_login_failures(request, "user@example.com")

    assert caplog.text.count("RATE_LIMIT_CHECK_UNAVAILABLE") == 3


@pytest.mark.asyncio
async def test_distinct_ips_get_distinct_buckets(monkeypatch):
    _patch_login_limits(monkeypatch)
    limiter = rate_limiter_module.RateLimiter()
    for _ in range(30):
        await limiter.record_login_failure(_request("203.0.113.10"), "user@example.com")
    # A different client IP is not throttled by the first client's failures.
    await limiter.ensure_login_allowed(_request("203.0.113.11"), "user@example.com")
    with pytest.raises(HTTPException):
        await limiter.ensure_login_allowed(_request("203.0.113.10"), "user@example.com")


def _build_login_client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    db.add(
        models.User(
            external_id="rl-user",
            auth_provider="local",
            provider_subject="rl-user",
            email="rl@example.com",
            hashed_password=hash_password("Password123!"),
            role="user",
            email_verified=True,
        )
    )
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def _login(client: TestClient, username: str, password: str) -> int:
    return client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}
    ).status_code


def test_login_endpoint_is_rate_limited_after_failures():
    """The login route counts failed attempts per account: five bad passwords
    get 401, the sixth attempt is a 429 before credentials are checked."""
    client = _build_login_client()
    try:
        for _ in range(5):
            assert _login(client, "rl@example.com", "wrong-password") == 401
        assert _login(client, "rl@example.com", "wrong-password") == 429
        # A different account on the same peer is not locked out with it.
        assert _login(client, "other@example.com", "wrong-password") == 401
    finally:
        app.dependency_overrides.clear()


def test_login_success_resets_the_account_counter():
    client = _build_login_client()
    try:
        for _ in range(4):
            assert _login(client, "rl@example.com", "wrong-password") == 401
        assert _login(client, "rl@example.com", "Password123!") == 200
        # After the reset a fresh 4 failures must still not lock out.
        for _ in range(4):
            assert _login(client, "rl@example.com", "wrong-password") == 401
        assert _login(client, "rl@example.com", "Password123!") == 200
    finally:
        app.dependency_overrides.clear()


def test_ip_spray_ceiling_gives_identical_429_for_known_and_unknown_accounts():
    """Once the per-IP budget is gone the response must be byte-identical for
    registered and unregistered emails, so the limiter is not an account
    enumeration oracle."""
    client = _build_login_client()
    try:
        for index in range(30):
            assert _login(client, f"spray-{index}@example.com", "nope") == 401

        known = client.post(
            "/api/v1/auth/login",
            data={"username": "rl@example.com", "password": "wrong-password"},
        )
        unknown = client.post(
            "/api/v1/auth/login",
            data={"username": "ghost@example.com", "password": "wrong-password"},
        )
        assert known.status_code == 429
        assert unknown.status_code == 429
        assert known.json() == unknown.json()
    finally:
        app.dependency_overrides.clear()
