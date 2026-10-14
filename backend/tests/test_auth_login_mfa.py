from __future__ import annotations

import contextlib

from fastapi.testclient import TestClient
from core.password_hashing import hash_password
import pyotp
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth.mfa as mfa_module
import models
from database import Base, get_db as auth_get_db
from main import app


class _FakeRedis:
    """SIGV2-1244: the login MFA path needs Redis for its replay guard."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def incr(self, key: str) -> int:
        value = int(self.store.get(key, 0)) + 1
        self.store[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return 900

    async def delete(self, key: str) -> int:
        self.store.pop(key, None)
        return 1


def _patch_redis(monkeypatch) -> None:
    client = _FakeRedis()

    @contextlib.asynccontextmanager
    async def _fake_get_async_redis(*_args, **_kwargs):
        yield client

    monkeypatch.setattr(mfa_module, "get_async_redis", _fake_get_async_redis)


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
        external_id="mfa-user",
        auth_provider="local",
        provider_subject="mfa-user",
        email="mfa@example.com",
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


def test_login_requires_mfa_code_when_enabled(monkeypatch):
    _patch_redis(monkeypatch)
    client, db, mfa_secret = _build_client()

    missing_mfa_response = client.post(
        "/api/v1/auth/login",
        data={"username": "mfa@example.com", "password": "Password123"},
    )
    assert missing_mfa_response.status_code == 401
    assert missing_mfa_response.json() == {
        "detail": {"detail": "MFA code required", "mfa_required": True},
    }

    invalid_mfa_response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "mfa@example.com",
            "password": "Password123",
            "mfa_code": "111111",
        },
    )
    assert invalid_mfa_response.status_code == 401
    assert invalid_mfa_response.json() == {
        "detail": {"detail": "Invalid MFA code", "mfa_required": True},
    }

    valid_code = pyotp.TOTP(mfa_secret).now()
    success_response = client.post(
        "/api/v1/auth/login",
        data={
            "username": "mfa@example.com",
            "password": "Password123",
            "mfa_code": valid_code,
        },
    )
    assert success_response.status_code == 200
    payload = success_response.json()
    assert "access_token" in payload
    assert "refresh_token" in payload
    assert payload["token_type"] == "bearer"

    app.dependency_overrides.clear()
    db.close()
