from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
import main
from middleware import maintenance as maintenance_module
from services.ai_routing_policy import provider_runtime_state_service


class FakeRedisClient:
    async def get(self, _key: str):
        return None

    async def set(self, _key: str, _value: str, ex: int | None = None):
        return None

    async def setex(self, _key: str, _ttl: int, _value: str):
        return None

    async def expire(self, _key: str, _ttl: int):
        return True

    async def delete(self, *_keys: str):
        return 0

    async def close(self):
        return None

    async def aclose(self):
        return None


@pytest.fixture
def hold_context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="credit-hold-integration@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()

    workspace = models.Workspace(name="Hold Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Hold Project",
        domain_url="https://example.com",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.commit()
    db.refresh(user)
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
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *_args, **_kwargs: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *_args, **_kwargs: FakeRedisClient()
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="available"),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    client = TestClient(main.app)

    yield {
        "client": client,
        "db": db,
        "user": user,
        "project": project,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_create_audit_settles_credit_hold_before_persisting_audit(
    hold_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(
        main.api_module,
        "fetch_url_signature",
        AsyncMock(return_value={"content_hash": "fresh-signature"}),
    )

    response = hold_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-hold-success"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": hold_context["project"].id,
        },
    )

    hold_context["db"].refresh(hold_context["user"])
    credit_hold = hold_context["db"].query(models.CreditHold).one()
    persisted_audit = hold_context["db"].query(models.Audit).one()

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1
    assert hold_context["user"].credits == 4
    assert credit_hold.request_id == "audit:req-hold-success"
    assert credit_hold.status == "settled"
    assert credit_hold.hold_amount == 1
    assert credit_hold.final_amount == 1
    assert persisted_audit.full_report["metadata"]["credit_hold_id"] == credit_hold.id
    assert persisted_audit.full_report["metadata"]["credit_hold_status"] == "settled"
    assert persisted_audit.full_report["metadata"]["cost_forecast"]["estimated_credits"] == 1


def test_create_audit_refunds_credit_hold_when_execution_fails(
    hold_context,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main.api_module,
        "perform_audit",
        AsyncMock(
            side_effect=main.HTTPException(
                status_code=503,
                detail="AI analysis is currently unavailable; please retry shortly.",
            )
        ),
    )
    monkeypatch.setattr(
        main.api_module,
        "fetch_url_signature",
        AsyncMock(return_value={"content_hash": "fresh-signature"}),
    )

    response = hold_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-hold-failure"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": hold_context["project"].id,
        },
    )

    hold_context["db"].refresh(hold_context["user"])
    credit_hold = hold_context["db"].query(models.CreditHold).one()

    assert response.status_code == 503
    assert (
        response.json()["detail"] == "AI analysis is currently unavailable; please retry shortly."
    )
    assert hold_context["user"].credits == 5
    assert credit_hold.request_id == "audit:req-hold-failure"
    assert credit_hold.status == "refunded"
    assert credit_hold.refunded_amount == 1
