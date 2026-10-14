import contextlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from routers import api_router as api_module


@pytest.fixture(autouse=True)
def _honour_custom_routing(monkeypatch):
    """The API discards a client model selection on every plan (SIGV2-1139);
    these tests verify the routing engine itself, so let overrides through."""
    monkeypatch.setattr(
        api_module,
        "_strip_client_model_selection",
        lambda *, provider, selected_models: (provider, selected_models),
    )


from database import Base
from services.ai_routing_policy import provider_runtime_state_service
from middleware import maintenance as maintenance_module


class FakeRedisClient:
    def __init__(self, store: dict[str, object], calls: dict[str, list[object]]):
        self._store = store
        self._calls = calls

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, **_kwargs):
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str, **_kwargs):
        self._store[key] = value
        return True

    async def expire(self, key: str, ttl: int, **_kwargs):
        return True

    async def incr(self, key: str, amount: int = 1):
        current = int(self._store.get(key, 0)) + amount
        self._store[key] = current
        return current

    async def delete(self, *keys):
        for key in keys:
            self._store.pop(key, None)
        return len(keys)

    async def exists(self, *keys):
        return sum(1 for key in keys if key in self._store)

    async def hset(self, key: str, mapping: dict[str, str]):
        self._calls["hset"].append({"key": key, "mapping": dict(mapping)})
        self._store[key] = dict(mapping)

    async def rpush(self, key: str, value: str):
        self._calls["rpush"].append({"key": key, "value": value})
        self._store.setdefault(key, []).append(value)

    async def close(self):
        self._calls["close"].append(True)

    async def aclose(self):
        self._calls["close"].append(True)


def _fake_async_redis_ctx(client: FakeRedisClient):
    @contextlib.asynccontextmanager
    async def _ctx(**_kwargs):
        yield client

    return _ctx


@pytest.fixture
def routing_test_context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="routing@example.com",
        hashed_password="x",
        role="user",
        credits=50,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Routing Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Routing Project",
        domain_url="https://example.com",
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

    redis_store: dict[str, object] = {}
    redis_calls: dict[str, list[object]] = {"hset": [], "rpush": [], "close": []}
    fake_client = FakeRedisClient(redis_store, redis_calls)

    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    monkeypatch.setattr(api_module, "get_async_redis", _fake_async_redis_ctx(fake_client))
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
        "redis_store": redis_store,
        "redis_calls": redis_calls,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_estimate_audit_credit_usage_uses_server_side_routing(routing_test_context):
    response = routing_test_context["client"].post(
        "/api/v1/audit/estimate",
        json={
            "provider": "openai",
            "tier": "deep",
            "category": "finance",
            "market": "Romania",
            "entities": ["Acme"],
            "selected_models": ["openai", "anthropic"],
        },
    )

    assert response.status_code == 200
    payload = response.json()

    # CUTOVER stage 1: reasoning routes unconditionally to Bedrock. The user's
    # provider/model selection is still recorded (selected_models) but the
    # resolved provider collapses to bedrock.
    assert payload["provider"] == "bedrock"
    assert payload["tier"] == "smart"
    assert payload["tier_class"] == "deep"
    assert payload["execution_tier"] == "smart"
    assert payload["mode_label"] == "Smart"
    assert payload["confidence"] > 0
    # SIGV2-1024: internal cost forecast and provider-USD fields are redacted
    # from the customer-facing estimate.
    for key in ("estimated_credit_cost", "estimated_credits", "estimated_cost_usd", "breakdown"):
        assert key not in payload


def test_estimate_audit_credit_usage_preserves_brand_target_identity(
    routing_test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    def fake_build_audit_cost_forecast(**kwargs):
        captured.update(kwargs)
        return 3, {
            "estimated_total_cogs_usd": 0.33,
            "confidence": 0.77,
            "breakdown": {"resolved_provider": kwargs["provider"]},
        }

    monkeypatch.setattr(api_module, "_build_audit_cost_forecast", fake_build_audit_cost_forecast)

    response = routing_test_context["client"].post(
        "/api/v1/audit/estimate",
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Logistics",
            "target_metadata": {"aliases": ["Acme"]},
            "provider": "openai",
            "tier": "deep",
        },
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "bedrock"
    assert response.json()["tier"] == "smart"
    assert captured["provider"] == "bedrock"
    assert captured["target_url"] is None
    assert captured["target_name"] == "Acme Logistics"
    assert captured["target_metadata"] == {"aliases": ["Acme"]}


def test_create_audit_job_queues_resolved_route_and_selected_models(routing_test_context):
    project = routing_test_context["project"]
    response = routing_test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-routing-job"},
        json={
            "project_id": project.id,
            "url": "https://example.com",
            "provider": "openai",
            "tier": "deep",
            "selected_models": ["openai", "anthropic"],
            "language": "en",
            "market": "Romania",
            "category": "finance",
            "entities": ["Acme"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["requested_tier"] == "smart"
    assert payload["mode_label"] == "Smart"
    assert "estimated_credit_cost" not in payload

    queued_messages = routing_test_context["redis_store"].get(
        "audit_jobs:smart"
    ) or routing_test_context["redis_store"].get("audit_jobs", [])
    assert isinstance(queued_messages, list)
    queued_payload = json.loads(queued_messages[0])

    # CUTOVER stage 1: provider collapses to bedrock; the user's openai
    # selection could not be honoured so routing_mode reflects the fallback.
    assert queued_payload["provider"] == "bedrock"
    assert queued_payload["tier"] == "smart"
    assert queued_payload["requested_tier"] == "smart"
    assert queued_payload["tier_class"] == "deep"
    assert queued_payload["routing_feature_key"] == "audit.main"
    assert queued_payload["routing_mode"] == "user_selected_provider_runtime_fallback"
    assert queued_payload.get("selected_models") == ["openai", "anthropic"]
    assert queued_payload["cost_forecast"]["estimated_credits"] >= 1
    assert queued_payload["cost_forecast"]["breakdown"]["forecast_mode"] == "multi_model_consensus"


def test_estimate_audit_credit_usage_preserves_deep_judgment_mode_identity(routing_test_context):
    db = routing_test_context["db"]
    user = routing_test_context["user"]
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_high_confidence_estimate",
            plan_type="plan_executive",
            status="active",
        )
    )
    db.commit()
    db.refresh(user)

    response = routing_test_context["client"].post(
        "/api/v1/audit/estimate",
        json={
            "provider": "anthropic",
            "tier": "deep_judgment",
            "category": "finance",
            "market": "Romania",
            "entities": ["Acme"],
        },
    )

    assert response.status_code == 200
    payload = response.json()

    # CUTOVER stage 1: deep_judgment still uses the generator/critic/judge
    # debate roles, but every role collapses to the bedrock provider.
    assert payload["provider"] == "bedrock"
    assert payload["tier"] == "deep_judgment"
    assert payload["tier_class"] == "deep"
    assert payload["execution_tier"] == "smart"
    assert payload["mode_label"] == "High Confidence / Prescriptive Confidence mode"
    # SIGV2-1024: the internal forecast breakdown (roles, providers, cost) is
    # redacted from the customer-facing estimate response.
    assert "breakdown" not in payload


def test_deep_judgment_mode_is_plan_gated_server_side(
    routing_test_context,
):
    db = routing_test_context["db"]
    user = routing_test_context["user"]
    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id="cus_plan_gated_estimate",
        plan_type="plan_standard",
        status="active",
    )
    db.add(subscription)
    db.commit()
    db.refresh(user)

    response = routing_test_context["client"].post(
        "/api/v1/audit/estimate",
        json={
            "provider": "openai",
            "tier": "deep_judgment",
        },
    )

    assert response.status_code == 402
    assert "High Confidence / Prescriptive Confidence mode requires" in response.json()["detail"]


def test_estimate_audit_credit_usage_rejects_unknown_tier(routing_test_context):
    response = routing_test_context["client"].post(
        "/api/v1/audit/estimate",
        json={
            "tier": "ultra",
        },
    )

    assert response.status_code == 422
    assert "tier must be one of 'fast', 'smart', or 'deep_judgment'." in response.text


def test_create_audit_job_uses_authenticated_user_not_hardcoded(routing_test_context):
    """AEX-01: Verify create_audit_job uses the JWT-authenticated user, not user.id=1."""
    db = routing_test_context["db"]
    project = routing_test_context["project"]
    user = routing_test_context["user"]

    response = routing_test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-auth-check"},
        json={
            "project_id": project.id,
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "language": "en",
        },
    )

    assert response.status_code == 200
    job_id = response.json()["job_id"]

    db_job = db.query(models.AuditJob).filter(models.AuditJob.id == job_id).first()
    assert db_job is not None
    assert (
        db_job.user_id == user.id
    ), f"AuditJob should belong to authenticated user {user.id}, got {db_job.user_id}"


def test_create_audit_job_returns_401_without_auth(routing_test_context):
    """AEX-01: Unauthenticated requests to /audit/jobs must return 401."""
    project = routing_test_context["project"]

    main.app.dependency_overrides.pop(main.get_current_user, None)

    client = TestClient(main.app)
    response = client.post(
        "/api/v1/audit/jobs",
        json={
            "project_id": project.id,
            "url": "https://example.com",
            "tier": "fast",
            "language": "en",
        },
    )

    assert response.status_code == 401

    main.app.dependency_overrides[main.get_current_user] = lambda: routing_test_context["user"]
