"""SIGV2-1244: TOTP codes are single-use and MFA attempts are throttled per user.

``verify_totp_code`` accepted any code inside the +/- 1 timestep window as many
times as it was presented, and nothing counted failed MFA attempts for a given
account, so an intercepted code stayed usable for ~90 seconds and brute force
was bounded only by a per-process IP limiter. These tests pin the two controls:
a burnt timestep is refused, and a locked-out user stays locked out no matter
which IP the next attempt arrives from.
"""

from __future__ import annotations

import contextlib

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
import pyotp
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.mfa as mfa_module
import models
from auth.mfa import MFAVerificationResult, verify_totp_code_for_user
from database import Base, get_db as auth_get_db
from main import app


class FakeRedis:
    """In-memory stand-in with the handful of commands the guard uses."""

    def __init__(self, fail_on: set[str] | None = None):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_on = fail_on or set()

    def _maybe_fail(self, command: str) -> None:
        if command in self.fail_on:
            raise ConnectionError(f"redis unavailable: {command}")

    async def get(self, key: str):
        self._maybe_fail("get")
        return self.store.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        self._maybe_fail("set")
        if nx and key in self.store:
            return None
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    async def incr(self, key: str) -> int:
        self._maybe_fail("incr")
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self._maybe_fail("expire")
        self.ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        self._maybe_fail("ttl")
        return self.ttls.get(key, -1)

    async def delete(self, key: str) -> int:
        self._maybe_fail("delete")
        self.store.pop(key, None)
        self.ttls.pop(key, None)
        return 1


def _patch_redis(monkeypatch, client: FakeRedis) -> FakeRedis:
    @contextlib.asynccontextmanager
    async def _fake_get_async_redis(*_args, **_kwargs):
        yield client

    monkeypatch.setattr(mfa_module, "get_async_redis", _fake_get_async_redis)
    return client


def _build_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    mfa_secret = pyotp.random_base32()
    user = models.User(
        external_id="mfa-replay-user",
        auth_provider="local",
        provider_subject="mfa-replay-user",
        email="mfa-replay@example.com",
        hashed_password=hash_password("Password123"),
        role="user",
        mfa_secret=mfa_secret,
        email_verified=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[auth_get_db] = override_get_db
    return TestClient(app), db, mfa_secret


def _login(client: TestClient, code: str | None, *, ip: str = "203.0.113.10"):
    data = {"username": "mfa-replay@example.com", "password": "Password123"}
    if code is not None:
        data["mfa_code"] = code
    return client.post("/api/v1/auth/login", data=data, headers={"X-Forwarded-For": ip})


# --------------------------------------------------------------------------
# Unit level
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_valid_code_is_accepted_once_and_refused_on_replay(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()

    first = await verify_totp_code_for_user(user_id=7, secret=secret, otp_code=code)
    second = await verify_totp_code_for_user(user_id=7, secret=secret, otp_code=code)

    assert first is MFAVerificationResult.OK
    assert second is MFAVerificationResult.REPLAYED


@pytest.mark.asyncio
async def test_replay_guard_is_scoped_per_user(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    code = pyotp.TOTP(secret).now()

    assert await verify_totp_code_for_user(user_id=1, secret=secret, otp_code=code) is (
        MFAVerificationResult.OK
    )
    assert await verify_totp_code_for_user(user_id=2, secret=secret, otp_code=code) is (
        MFAVerificationResult.OK
    )


@pytest.mark.asyncio
async def test_redis_failure_on_the_replay_path_rejects_the_code(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis(fail_on={"set"}))
    secret = pyotp.random_base32()

    result = await verify_totp_code_for_user(
        user_id=7, secret=secret, otp_code=pyotp.TOTP(secret).now()
    )

    assert result is MFAVerificationResult.UNAVAILABLE
    assert result is not MFAVerificationResult.OK


@pytest.mark.asyncio
async def test_throttle_lookup_failure_is_fail_open(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis(fail_on={"get"}))
    secret = pyotp.random_base32()

    result = await verify_totp_code_for_user(
        user_id=7, secret=secret, otp_code=pyotp.TOTP(secret).now()
    )

    assert result is MFAVerificationResult.OK


@pytest.mark.asyncio
async def test_failed_attempts_lock_the_user_out(monkeypatch):
    fake = _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()

    for _ in range(mfa_module.MAX_FAILED_ATTEMPTS):
        assert await verify_totp_code_for_user(user_id=7, secret=secret, otp_code="000000") is (
            MFAVerificationResult.INVALID
        )

    # Even a genuinely valid code is refused while the lockout holds.
    result = await verify_totp_code_for_user(
        user_id=7, secret=secret, otp_code=pyotp.TOTP(secret).now()
    )

    assert result is MFAVerificationResult.THROTTLED
    assert fake.ttls[f"{mfa_module.FAILED_ATTEMPT_KEY_PREFIX}7"] == (
        mfa_module.FAILED_ATTEMPT_WINDOW_SECONDS
    )


@pytest.mark.asyncio
async def test_successful_verification_clears_the_failure_counter(monkeypatch):
    fake = _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()

    for _ in range(mfa_module.MAX_FAILED_ATTEMPTS - 1):
        await verify_totp_code_for_user(user_id=7, secret=secret, otp_code="000000")

    assert await verify_totp_code_for_user(
        user_id=7, secret=secret, otp_code=pyotp.TOTP(secret).now()
    ) is (MFAVerificationResult.OK)
    assert f"{mfa_module.FAILED_ATTEMPT_KEY_PREFIX}7" not in fake.store


# --------------------------------------------------------------------------
# Login endpoint
# --------------------------------------------------------------------------


def test_login_rejects_a_replayed_totp_code(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    client, db, mfa_secret = _build_client()
    try:
        code = pyotp.TOTP(mfa_secret).now()

        first = _login(client, code)
        assert first.status_code == 200
        assert "access_token" in first.json()

        replay = _login(client, code)
        assert replay.status_code == 401
        assert replay.json() == {"detail": {"detail": "Invalid MFA code", "mfa_required": True}}
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_login_throttles_a_user_independently_of_the_source_ip(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    # Keep the per-IP login limiter out of the way: TestClient's peer is not a
    # routable IP, so its X-Forwarded-For is (correctly) not trusted and every
    # attempt would share one bucket below MAX_FAILED_ATTEMPTS.
    monkeypatch.setattr(
        "middleware.rate_limiter._get_cached_config",
        lambda key: {
            "LOGIN_RATE_LIMIT": 100,
            "LOGIN_RATE_WINDOW": 60,
            "LOGIN_IP_RATE_LIMIT": 1000,
            "LOGIN_IP_RATE_WINDOW": 60,
        }[key],
    )
    client, db, mfa_secret = _build_client()
    try:
        for index in range(mfa_module.MAX_FAILED_ATTEMPTS):
            response = _login(client, "000000", ip=f"198.51.100.{index + 1}")
            assert response.status_code == 401

        # New IP, correct code, still locked out: the counter is keyed by user.
        blocked = _login(client, pyotp.TOTP(mfa_secret).now(), ip="192.0.2.77")
        assert blocked.status_code == 429
        assert blocked.json()["detail"]["mfa_required"] is True
        assert int(blocked.headers["Retry-After"]) > 0
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_login_rejects_when_the_replay_guard_cannot_reach_redis(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis(fail_on={"set"}))
    client, db, mfa_secret = _build_client()
    try:
        response = _login(client, pyotp.TOTP(mfa_secret).now())

        assert response.status_code == 503
        assert "access_token" not in response.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_login_still_succeeds_with_a_fresh_code(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    client, db, mfa_secret = _build_client()
    try:
        missing = _login(client, None)
        assert missing.status_code == 401
        assert missing.json() == {"detail": {"detail": "MFA code required", "mfa_required": True}}

        ok = _login(client, pyotp.TOTP(mfa_secret).now())
        assert ok.status_code == 200
        payload = ok.json()
        assert payload["token_type"] == "bearer"
        assert "refresh_token" in payload
    finally:
        app.dependency_overrides.clear()
        db.close()
