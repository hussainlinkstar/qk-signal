import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base
from middleware import maintenance as maintenance_module
from services.ai_routing_policy import provider_runtime_state_service


class FakeRedisClient:
    def __init__(self, store: dict[str, object]):
        self._store = store

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self._store[key] = value

    async def hset(self, key: str, mapping: dict[str, str]):
        self._store[key] = dict(mapping)

    async def rpush(self, key: str, value: str):
        self._store.setdefault(key, []).append(value)

    async def setex(self, key: str, ttl: int, value: str):
        del ttl
        self._store[key] = value

    async def expire(self, key: str, ttl: int):
        return True

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)
        return 0

    async def close(self):
        return None

    async def aclose(self):
        return None


def test_create_audit_preserves_deep_judgment_contract_metadata(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    redis_store: dict[str, object] = {}

    user = models.User(
        email="high-confidence@example.com",
        hashed_password="x",
        role="user",
        credits=50,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_high_confidence_contract",
            plan_type="plan_executive",
            status="active",
        )
    )
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="High Confidence Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="High Confidence Project",
        domain_url="https://example-high-confidence.com",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        db.refresh(user)
        return user

    async def noop_enforce_authenticated_audit_limit(*_args, **_kwargs):
        return None

    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(redis_store),
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(redis_store),
    )
    monkeypatch.setattr(
        main.api_module,
        "perform_audit",
        AsyncMock(
            return_value=(
                {
                    "analysis": {"seo_score": 72, "geo_score": 61, "aeo_score": 79},
                    "metadata": {"plan": "plan_executive", "model": "claude-opus-4-6"},
                },
                {"seo": 72.0, "geo": 61.0, "aeo": 79.0, "overall": 70.67},
            )
        ),
    )
    monkeypatch.setattr(
        main.api_module,
        "fetch_url_signature",
        AsyncMock(return_value={"content_hash": "deep-judgment-signature"}),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user
    client = TestClient(main.app)

    try:
        response = client.post(
            "/api/v1/audit",
            headers={"X-Request-ID": "req-deep-judgment-contract"},
            json={
                "project_id": project.id,
                "url": "https://example-high-confidence.com",
                "provider": "anthropic",
                "tier": "deep_judgment",
            },
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        persisted_audit = (
            db.query(models.Audit).filter(models.Audit.id == payload["audit_id"]).first()
        )

        assert persisted_audit is not None
        metadata = persisted_audit.full_report.get("metadata", {})
        assert metadata.get("tier") == "deep_judgment"
        assert metadata.get("requested_tier") == "deep_judgment"
        assert metadata.get("execution_tier") == "smart"
        assert metadata.get("mode_label") == "High Confidence / Prescriptive Confidence mode"

        cache_entries = [value for value in redis_store.values() if isinstance(value, str)]
        assert cache_entries
        cached_payload = json.loads(cache_entries[0])
        assert cached_payload["metadata"]["requested_tier"] == "deep_judgment"
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)
