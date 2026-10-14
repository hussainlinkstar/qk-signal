"""SIGV2-1258: the MFA management endpoints must reuse the hardened TOTP path.

SIGV2-1244 made TOTP codes single-use and added a per-user attempt lockout, but
only ``/api/v1/auth/login`` was wired to it. ``/api/v1/users/me/mfa/disable``
and ``/api/v1/users/me/mfa/enable`` still called the plain ``verify_totp_code``,
so a code already spent stayed usable for the rest of its window and neither
endpoint counted failed attempts. These tests pin the same three guarantees the
login path has: a burnt code is refused, repeated wrong codes lock the user out,
and an unreachable replay guard rejects the attempt instead of allowing it.
"""

from __future__ import annotations

import contextlib
import time

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
import pyotp
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.mfa as mfa_module
import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base, get_db
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


def _build_client(*, mfa_secret: str | None = None):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        external_id="mfa-endpoint-user",
        auth_provider="local",
        provider_subject="mfa-endpoint-user",
        email="mfa-endpoint@example.com",
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

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), db, user


def _disable(client: TestClient, code: str):
    return client.post("/api/v1/users/me/mfa/disable", json={"otp_code": code})


def _restore_secret(db, user, secret: str) -> None:
    """Put MFA back on the account so the next attempt reaches the TOTP check."""
    user.mfa_secret = secret
    db.commit()
    db.refresh(user)


# --------------------------------------------------------------------------
# Disable endpoint
# --------------------------------------------------------------------------


def test_disable_accepts_a_fresh_code(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    client, db, user = _build_client(mfa_secret=secret)
    try:
        response = _disable(client, pyotp.TOTP(secret).now())

        assert response.status_code == 200
        assert response.json()["enabled"] is False

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_disable_rejects_a_replayed_totp_code(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    client, db, user = _build_client(mfa_secret=secret)
    try:
        code = pyotp.TOTP(secret).now()

        assert _disable(client, code).status_code == 200

        _restore_secret(db, user, secret)
        replay = _disable(client, code)

        assert replay.status_code == 400
        assert replay.json() == {"detail": "Invalid MFA code."}

        db.refresh(user)
        assert user.mfa_secret == secret
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_disable_rejects_a_code_already_spent_on_login(monkeypatch):
    """The burn is per user, so a code intercepted at login cannot strip MFA."""
    fake = _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    client, db, user = _build_client(mfa_secret=secret)
    try:
        code = pyotp.TOTP(secret).now()
        timestep = mfa_module.matching_totp_timestep(secret, code)
        fake.store[f"{mfa_module.USED_TIMESTEP_KEY_PREFIX}{user.id}:{timestep}"] = "1"

        response = _disable(client, code)

        assert response.status_code == 400

        db.refresh(user)
        assert user.mfa_secret == secret
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_disable_throttles_repeated_invalid_codes(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    secret = pyotp.random_base32()
    client, db, user = _build_client(mfa_secret=secret)
    try:
        for _ in range(mfa_module.MAX_FAILED_ATTEMPTS):
            assert _disable(client, "000000").status_code == 400

        # Even a genuinely valid code is refused while the lockout holds.
        blocked = _disable(client, pyotp.TOTP(secret).now())

        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0

        db.refresh(user)
        assert user.mfa_secret == secret
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_disable_rejects_when_the_replay_guard_cannot_reach_redis(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis(fail_on={"set"}))
    secret = pyotp.random_base32()
    client, db, user = _build_client(mfa_secret=secret)
    try:
        response = _disable(client, pyotp.TOTP(secret).now())

        assert response.status_code == 503

        db.refresh(user)
        assert user.mfa_secret == secret
    finally:
        app.dependency_overrides.clear()
        db.close()


# --------------------------------------------------------------------------
# Enable endpoint
# --------------------------------------------------------------------------


def test_enable_rejects_a_replayed_enrollment_request(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    client, db, user = _build_client()
    try:
        setup = client.post("/api/v1/users/me/mfa/setup")
        assert setup.status_code == 200
        payload = setup.json()
        body = {
            "setup_token": payload["setup_token"],
            "otp_code": pyotp.TOTP(payload["secret"]).now(),
        }

        first = client.post("/api/v1/users/me/mfa/enable", json=body)
        assert first.status_code == 200

        replay = client.post("/api/v1/users/me/mfa/enable", json=body)
        assert replay.status_code == 400
        assert replay.json() == {"detail": "Invalid MFA code."}
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_throttles_repeated_invalid_codes(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis())
    client, db, user = _build_client()
    try:
        setup = client.post("/api/v1/users/me/mfa/setup")
        payload = setup.json()

        for _ in range(mfa_module.MAX_FAILED_ATTEMPTS):
            response = client.post(
                "/api/v1/users/me/mfa/enable",
                json={"setup_token": payload["setup_token"], "otp_code": "000000"},
            )
            assert response.status_code == 400

        blocked = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "setup_token": payload["setup_token"],
                "otp_code": pyotp.TOTP(payload["secret"]).now(),
            },
        )

        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) > 0

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_rejects_when_the_replay_guard_cannot_reach_redis(monkeypatch):
    _patch_redis(monkeypatch, FakeRedis(fail_on={"set"}))
    client, db, user = _build_client()
    try:
        setup = client.post("/api/v1/users/me/mfa/setup")
        payload = setup.json()

        response = client.post(
            "/api/v1/users/me/mfa/enable",
            json={
                "setup_token": payload["setup_token"],
                "otp_code": pyotp.TOTP(payload["secret"]).now(),
            },
        )

        assert response.status_code == 503

        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_enable_then_disable_needs_two_distinct_codes(monkeypatch):
    """The enrollment code is spent, so disabling needs the next one."""
    _patch_redis(monkeypatch, FakeRedis())
    client, db, user = _build_client()
    try:
        payload = client.post("/api/v1/users/me/mfa/setup").json()
        secret = payload["secret"]

        enable = client.post(
            "/api/v1/users/me/mfa/enable",
            json={"setup_token": payload["setup_token"], "otp_code": pyotp.TOTP(secret).now()},
        )
        assert enable.status_code == 200

        next_code = pyotp.TOTP(secret).at(int(time.time()) + mfa_module.TOTP_INTERVAL_SECONDS)
        disable = _disable(client, next_code)

        assert disable.status_code == 200
        db.refresh(user)
        assert user.mfa_secret is None
    finally:
        app.dependency_overrides.clear()
        db.close()
