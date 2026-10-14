"""SIGV2-1126: the competitor lite audit gate, and who gets to classify an audit.

Two properties are pinned here.

1. The competitor lite entitlement rule is one rule. The app path refused a
   competitor lite audit from a plan without ``has_competitor_analysis``; the
   external API accepted it, created the job row, consumed a scan and only let
   the worker refuse it afterwards. Both boundaries now consult the same rule
   and refuse with 402, and an entitled caller is still served.

2. A client cannot choose how its audit is classified. The project scope used
   to be derived from the request id, which is client supplied on every
   external write path (the ``request_id`` body field of
   ``POST /api/v1/audit/jobs``, and the ``X-Request-ID`` header everywhere),
   so forging a ``lite-refresh:`` prefix moved the audit out of the project's
   own history. Classification now comes from the category alone.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base
from job_models import parse_job_payload
from middleware import maintenance as maintenance_module
from models import AUDIT_PROJECT_SCOPE_COMPETITOR, AUDIT_PROJECT_SCOPE_OWN
from routers import external_api_router
from services.ai_routing_policy import provider_runtime_state_service
from services.external_api_service import ExternalAPIPrincipal, hash_api_key

COMPETITOR_LITE_CATEGORY = "Competitor Lite Audit"
FORGED_REQUEST_ID = "lite-refresh:1:2:forged"
# Deliberately low entropy and assembled at runtime: the external API only
# requires the prefix, and a realistic-looking literal would be a secret-scan
# finding in a file that holds no secret.
TEST_API_KEY_PREFIX = "stx_live_"


class _FakeRedis:
    """Minimal async Redis double that keeps every enqueued payload."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.values: dict[str, str] = {}
        self.lists: dict[str, list[str]] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self.values[key] = value
        return True

    async def setex(self, key: str, _ttl, value: str):
        self.values[key] = value
        return True

    async def expire(self, _key: str, _ttl: int):
        return True

    async def delete(self, *keys: str):
        for key in keys:
            self.values.pop(key, None)
        return len(keys)

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, 0)) + 1
        self.values[key] = str(value)
        return value

    async def hset(self, key: str, mapping: dict):
        self.hashes.setdefault(key, {}).update({str(k): str(v) for k, v in mapping.items()})
        return len(mapping)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def close(self):
        return None

    async def aclose(self):
        return None

    def enqueued_payloads(self) -> list[dict]:
        return [
            json.loads(raw)
            for key, values in self.lists.items()
            if key.startswith("audit_jobs")
            for raw in values
        ]


class _FakeSyncRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    def incr(self, key: str) -> int:
        value = int(self.counters.get(key, 0)) + 1
        self.counters[key] = value
        return value

    def expire(self, _key: str, _seconds: int) -> bool:
        return True

    def ttl(self, _key: str) -> int:
        return 60

    def close(self) -> None:
        return None


@contextlib.contextmanager
def _fake_sync_redis_ctx(**_kwargs):
    yield _FakeSyncRedis()


def _seed_subscription(db, user: models.User, plan_type: str) -> None:
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()
    db.refresh(user)


@pytest.fixture
def app_context(monkeypatch: pytest.MonkeyPatch):
    """An authenticated app client with one workspace project."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_factory()

    user = models.User(
        email="competitor-lite@example.com",
        hashed_password="x",
        role="user",
        credits=100,
    )
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Scope Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Scope Project",
        domain_url="https://example.com",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.commit()
    db.refresh(user)
    db.refresh(project)

    fake_redis = _FakeRedis()

    def override_get_db():
        yield db

    def override_get_current_user():
        db.refresh(user)
        return user

    async def noop_audit_limit(*_args, **_kwargs):
        return None

    async def passthrough_tenant_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(main, "enforce_authenticated_audit_limit", noop_audit_limit)
    monkeypatch.setattr(main, "tenant_resolver_middleware", passthrough_tenant_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as redis_client_module

    monkeypatch.setattr(
        redis_client_module.async_redis_lib, "from_url", lambda *_a, **_k: fake_redis
    )
    monkeypatch.setattr(
        redis_client_module.sync_redis_lib, "from_url", lambda *_a, **_k: _FakeSyncRedis()
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="available"),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    yield {
        "client": TestClient(main.app),
        "db": db,
        "user": user,
        "project": project,
        "redis": fake_redis,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def external_context(monkeypatch: pytest.MonkeyPatch):
    """An external API caller holding a live API key."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_factory()

    user = models.User(
        email="external-competitor-lite@example.com",
        hashed_password="x",
        role="user",
        credits=100,
    )
    db.add(user)
    db.flush()
    db.commit()
    db.refresh(user)

    raw_key = TEST_API_KEY_PREFIX + "fixture" * 4
    api_key = models.ApiKey(
        user_id=user.id,
        name="Primary API key",
        key_hash=hash_api_key(raw_key),
        key_prefix=TEST_API_KEY_PREFIX,
        key_last_four=raw_key[-4:],
        scopes=["audit:read", "audit:write", "projects:read"],
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    fake_redis = _FakeRedis()

    def override_get_db():
        yield db

    import database

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)

    @contextlib.asynccontextmanager
    async def fake_async_redis(**_kwargs):
        yield fake_redis

    monkeypatch.setattr(external_api_router, "get_async_redis", fake_async_redis)

    yield {
        "client": TestClient(main.app),
        "db": db,
        "user": user,
        "api_key": api_key,
        "raw_key": raw_key,
        "redis": fake_redis,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _launch_job(context, *, headers=None, **overrides):
    body = {
        "url": "https://example.com",
        "provider": "google",
        "tier": "fast",
        "project_id": context["project"].id,
    }
    body.update(overrides)
    return context["client"].post("/api/v1/audit/jobs", headers=headers or {}, json=body)


def _only_enqueued_scope(context) -> str | None:
    payloads = context["redis"].enqueued_payloads()
    assert len(payloads) == 1, payloads
    return parse_job_payload(payloads[0]).project_scope


# ---------------------------------------------------------------------------
# 1. The entitlement rule is one rule, applied at every boundary
# ---------------------------------------------------------------------------


def test_app_path_refuses_competitor_lite_audit_without_the_entitlement(app_context) -> None:
    _seed_subscription(app_context["db"], app_context["user"], "plan_standard")

    response = _launch_job(app_context, category=COMPETITOR_LITE_CATEGORY)

    assert response.status_code == 402, response.text
    assert app_context["db"].query(models.AuditJob).count() == 0
    assert app_context["redis"].enqueued_payloads() == []


def test_external_path_refuses_competitor_lite_audit_without_the_entitlement(
    external_context,
) -> None:
    """The external boundary must refuse exactly what the app boundary refuses.

    A plan without ``api_access`` cannot hold a usable API key today, so this
    drives the enqueue function with a principal carrying an unentitled plan.
    The point of the gate is that the boundary does not depend on the current
    shape of the plan catalog for its authorization.
    """
    db = external_context["db"]
    principal = ExternalAPIPrincipal(
        user=external_context["user"],
        api_key=external_context["api_key"],
        plan="plan_standard",
    )
    http_request = SimpleNamespace(state=SimpleNamespace(request_id="req-external"))

    with pytest.raises(HTTPException) as refusal:
        asyncio.run(
            external_api_router._enqueue_external_audit_job(
                payload=external_api_router.ExternalAuditCreateRequest(
                    url="https://example.com",
                    tier="fast",
                    category=COMPETITOR_LITE_CATEGORY,
                ),
                principal=principal,
                http_request=http_request,
                db=db,
            )
        )

    assert refusal.value.status_code == 402
    assert refusal.value.detail["code"] == "PLAN_NOT_ELIGIBLE"
    # Nothing was created and no quota was spent before the refusal.
    assert db.query(models.AuditJob).count() == 0
    assert external_context["redis"].enqueued_payloads() == []


def test_external_path_allows_competitor_lite_audit_with_the_entitlement(
    external_context,
) -> None:
    _seed_subscription(external_context["db"], external_context["user"], "plan_specialist")

    response = external_context["client"].post(
        "/api/v1/external/audit",
        headers={"X-API-Key": external_context["raw_key"]},
        json={
            "url": "https://example.com",
            "tier": "fast",
            "category": COMPETITOR_LITE_CATEGORY,
        },
    )

    assert response.status_code == 202, response.text
    assert _only_enqueued_scope(external_context) == AUDIT_PROJECT_SCOPE_COMPETITOR


def test_app_path_allows_competitor_lite_audit_with_the_entitlement(app_context) -> None:
    _seed_subscription(app_context["db"], app_context["user"], "plan_specialist")

    response = _launch_job(app_context, category=COMPETITOR_LITE_CATEGORY)

    assert response.status_code == 200, response.text
    assert _only_enqueued_scope(app_context) == AUDIT_PROJECT_SCOPE_COMPETITOR


def test_the_entitlement_rule_itself_is_shared() -> None:
    from services.audit_helpers import competitor_lite_audit_is_denied

    assert competitor_lite_audit_is_denied(plan="plan_standard", category=COMPETITOR_LITE_CATEGORY)
    assert not competitor_lite_audit_is_denied(
        plan="plan_specialist", category=COMPETITOR_LITE_CATEGORY
    )
    # An unknown or absent plan fails closed.
    assert competitor_lite_audit_is_denied(plan=None, category=COMPETITOR_LITE_CATEGORY)
    # Any other audit is untouched by the gate.
    assert not competitor_lite_audit_is_denied(plan="plan_starter", category="sitemap crawl")


# ---------------------------------------------------------------------------
# 2. The client does not get to classify its own audit
# ---------------------------------------------------------------------------


def test_forged_request_id_body_field_cannot_change_the_project_scope(app_context) -> None:
    _seed_subscription(app_context["db"], app_context["user"], "plan_specialist")

    response = _launch_job(app_context, request_id=FORGED_REQUEST_ID)

    assert response.status_code == 200, response.text
    assert _only_enqueued_scope(app_context) == AUDIT_PROJECT_SCOPE_OWN
    # The forged id is discarded outright, so nothing downstream reads it back
    # as an internal competitor marker either.
    payload = parse_job_payload(app_context["redis"].enqueued_payloads()[0])
    assert not payload.request_id.startswith("lite-refresh:")


def test_forged_request_id_header_cannot_change_the_project_scope(app_context) -> None:
    _seed_subscription(app_context["db"], app_context["user"], "plan_specialist")

    response = _launch_job(app_context, headers={"X-Request-ID": FORGED_REQUEST_ID})

    assert response.status_code == 200, response.text
    assert _only_enqueued_scope(app_context) == AUDIT_PROJECT_SCOPE_OWN


def test_forged_request_id_header_cannot_change_the_external_project_scope(
    external_context,
) -> None:
    _seed_subscription(external_context["db"], external_context["user"], "plan_specialist")

    response = external_context["client"].post(
        "/api/v1/external/audit",
        headers={
            "X-API-Key": external_context["raw_key"],
            "X-Request-ID": "lite-refresh:1",
        },
        json={"url": "https://example.com", "tier": "fast"},
    )

    assert response.status_code == 202, response.text
    assert _only_enqueued_scope(external_context) == AUDIT_PROJECT_SCOPE_OWN
    payload = parse_job_payload(external_context["redis"].enqueued_payloads()[0])
    assert not payload.request_id.startswith("lite-refresh:")


def test_a_forged_prefix_cannot_reach_the_classifier_through_the_declaration() -> None:
    from services.project_audit_scope import (
        declare_audit_project_scope,
        is_reserved_internal_request_id,
        sanitize_client_request_id,
    )

    # The declaration no longer accepts a request id at all.
    assert declare_audit_project_scope(category=None) == AUDIT_PROJECT_SCOPE_OWN
    with pytest.raises(TypeError):
        declare_audit_project_scope(request_id=FORGED_REQUEST_ID)  # type: ignore[call-arg]

    assert is_reserved_internal_request_id(FORGED_REQUEST_ID)
    assert is_reserved_internal_request_id("competitive-benchmark:1:2:job")
    assert not is_reserved_internal_request_id("req-abc")
    assert sanitize_client_request_id(FORGED_REQUEST_ID, fallback="server-id") == "server-id"
    assert sanitize_client_request_id("   ", fallback="server-id") == "server-id"
    assert sanitize_client_request_id("req-abc", fallback="server-id") == "req-abc"
