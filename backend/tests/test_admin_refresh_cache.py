import json
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import admin
import models
from admin import get_db
from auth.token_verifier import get_current_staff_user
from cache_utils import build_audit_cache_key
from database import Base
from main import app


class FakeRedisClient:
    def __init__(self, store: dict[str, str]):
        self._store = store

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            return 1
        return 0

    async def scan_iter(self, match: str | None = None):
        prefix = "audit:cache:"
        for key in list(self._store.keys()):
            if match == f"{prefix}*" and not key.startswith(prefix):
                continue
            yield key

    async def close(self):
        return None

    async def aclose(self):
        return None


def _build_client_with_db(admin_user: models.User):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_get_current_user

    return TestClient(app), db


def test_refresh_cache_deletes_targeted_cache_entry(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-cache@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    cache_key = build_audit_cache_key("https://target.example.com", "google", "fast")
    redis_store = {
        cache_key: json.dumps({"report": {"analysis": {}}, "metadata": {"content_hash": "abc"}}),
        "misc:key": "untouched",
    }

    @asynccontextmanager
    async def _fake_redis(**_kw):
        yield FakeRedisClient(redis_store)

    monkeypatch.setattr(admin, "get_async_redis", _fake_redis)

    response = client.post(
        "/api/v1/admin/refresh-cache",
        json={"url": "https://target.example.com", "provider": "google", "tier": "fast"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_keys"] == 1
    assert payload["mode"] == "targeted"
    assert cache_key not in redis_store
    assert redis_store["misc:key"] == "untouched"

    app.dependency_overrides.clear()
    db.close()


def test_refresh_cache_clear_all_deletes_only_audit_cache_entries(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-cache-all@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    cache_key_1 = build_audit_cache_key("https://a.example.com", "google", "fast")
    cache_key_2 = build_audit_cache_key("https://b.example.com", "google", "smart")
    redis_store = {
        cache_key_1: "value-1",
        cache_key_2: "value-2",
        "billing:job:1": "untouched",
    }

    @asynccontextmanager
    async def _fake_redis(**_kw):
        yield FakeRedisClient(redis_store)

    monkeypatch.setattr(admin, "get_async_redis", _fake_redis)

    response = client.post("/api/v1/admin/refresh-cache", json={"clear_all": True})

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_keys"] == 2
    assert payload["mode"] == "all"
    assert cache_key_1 not in redis_store
    assert cache_key_2 not in redis_store
    assert redis_store["billing:job:1"] == "untouched"

    app.dependency_overrides.clear()
    db.close()


def test_refresh_cache_requires_target_fields_when_not_clear_all(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-cache-invalid@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    @asynccontextmanager
    async def _fake_redis(**_kw):
        yield FakeRedisClient({})

    monkeypatch.setattr(admin, "get_async_redis", _fake_redis)

    response = client.post(
        "/api/v1/admin/refresh-cache", json={"url": "https://missing-fields.example.com"}
    )

    assert response.status_code == 400
    assert "Provide url, provider, and tier" in response.json()["detail"]

    app.dependency_overrides.clear()
    db.close()
