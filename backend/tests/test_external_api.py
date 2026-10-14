import contextlib
import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import main
import models
import database
from database import Base
from job_models import parse_pdf_job_payload
from middleware import maintenance as maintenance_module
from services.external_api_service import (
    API_KEY_SCOPES,
    EXTERNAL_RATE_LIMITS,
    ExternalAPIPrincipal,
    enforce_external_rate_limit,
    hash_api_key,
)
from services.external_webhook_service import (
    build_webhook_signature,
    deliver_external_webhook_for_job,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        value = int(self.counters.get(key, 0)) + 1
        self.counters[key] = value
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = int(seconds)
        return True

    async def ttl(self, key: str) -> int:
        return int(self.ttls.get(key, -1))

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def setex(self, key: str, ttl: int | object, value: str) -> bool:
        seconds = (
            int(getattr(ttl, "total_seconds", lambda: ttl)())
            if hasattr(ttl, "total_seconds")
            else int(ttl)
        )
        self.ttls[key] = seconds
        self.values[key] = value
        return True

    async def hset(self, key: str, mapping: dict[str, str]) -> int:
        self.hashes.setdefault(key, {}).update({str(k): str(v) for k, v in mapping.items()})
        return len(mapping)

    async def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    async def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    async def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _fake_redis_ctx(fake_redis: FakeRedis):
    """Return an async context-manager factory that yields *fake_redis*."""

    @asynccontextmanager
    async def _ctx(**_kw):
        yield fake_redis

    return _ctx


class FakeSyncRedis:
    """Sync mirror of FakeRedis for get_sync_redis consumers."""

    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, key: str) -> int:
        value = int(self.counters.get(key, 0)) + 1
        self.counters[key] = value
        return value

    def expire(self, key: str, seconds: int) -> bool:
        self.ttls[key] = int(seconds)
        return True

    def ttl(self, key: str) -> int:
        return int(self.ttls.get(key, -1))

    def close(self) -> None:
        return None


@contextlib.contextmanager
def _fake_sync_redis_ctx(**_kw):
    yield FakeSyncRedis()


def _persistent_sync_redis_ctx(shared: FakeSyncRedis):
    """Return a sync context-manager factory that always yields *shared*."""

    @contextlib.contextmanager
    def _ctx(**_kw):
        yield shared

    return _ctx


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(
    db: Session,
    *,
    email: str,
    credits: int = 25,
    plan_type: str = "plan_specialist",
    subscription_status: str = "active",
) -> models.User:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=credits,
        company_name="Signal Forge",
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type=plan_type,
            status=subscription_status,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _seed_api_key(
    db: Session,
    *,
    user: models.User,
    raw_key: str = "stx_live_0123456789abcdef0123456789abcd",
    scopes: list[str] | None = None,
) -> models.ApiKey:
    if scopes is None:
        scopes = ["audit:read", "audit:write", "projects:read"]
    api_key = models.ApiKey(
        user_id=user.id,
        name="Primary API key",
        key_hash=hash_api_key(raw_key),
        key_prefix="stx_live_",
        key_last_four=raw_key[-4:],
        scopes=scopes,
        is_active=True,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def _build_client(
    db: Session,
    *,
    auth_user: models.User,
    monkeypatch: pytest.MonkeyPatch | None = None,
) -> TestClient:
    def override_get_db():
        yield db

    def override_current_user():
        return db.query(models.User).filter(models.User.id == auth_user.id).first()

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_current_user
    if monkeypatch is not None:
        monkeypatch.setattr(
            maintenance_module,
            "_get_maintenance_state",
            lambda: {"active": False, "message": "", "allowed_ips": []},
        )
    return TestClient(main.app)


def test_api_key_management_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="owner@example.com")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        create_response = client.post(
            "/api/v1/settings/api-keys",
            json={"name": "Warehouse Export"},
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        assert created_payload["api_key"].startswith("stx_live_")
        assert created_payload["item"]["name"] == "Warehouse Export"
        assert created_payload["item"]["key_last_four"] == created_payload["api_key"][-4:]

        list_response = client.get("/api/v1/settings/api-keys")
        assert list_response.status_code == 200
        listed_payload = list_response.json()
        assert listed_payload["api_access_enabled"] is True
        assert len(listed_payload["items"]) == 1

        revoke_response = client.delete(
            f"/api/v1/settings/api-keys/{created_payload['item']['id']}"
        )
        assert revoke_response.status_code == 200
        assert revoke_response.json()["revoked"] is True

        refreshed_key = (
            db.query(models.ApiKey).filter(models.ApiKey.id == created_payload["item"]["id"]).one()
        )
        assert refreshed_key.is_active is False
        assert refreshed_key.revoked_at is not None
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_audit_idempotency_returns_original_job(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="api@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        payload = {
            "url": "https://example.com",
            "tier": "fast",
            "idempotency_key": "same-request-123",
        }

        first = client.post("/api/v1/external/audit", headers=headers, json=payload)
        assert first.status_code == 202
        first_payload = first.json()
        assert first_payload["idempotent_replay"] is False

        second = client.post("/api/v1/external/audit", headers=headers, json=payload)
        assert second.status_code == 202
        second_payload = second.json()
        assert second_payload["job_id"] == first_payload["job_id"]
        assert second_payload["idempotent_replay"] is True

        assert db.query(models.AuditJob).filter(models.AuditJob.source == "external").count() == 1
        all_audit_lists = sum(
            (v for k, v in fake_redis.lists.items() if k.startswith("audit_jobs")), []
        )
        assert len(all_audit_lists) == 1
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_api_rejects_ineligible_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="starter@example.com", plan_type="plan_standard")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)

        response = client.get(
            "/api/v1/external/audits",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
        )
        assert response.status_code == 403
        payload = response.json()
        assert payload["error"]["code"] == "PLAN_NOT_ELIGIBLE"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


@pytest.mark.asyncio
async def test_external_api_rate_limits_include_executive_and_fail_closed() -> None:
    assert EXTERNAL_RATE_LIMITS["plan_executive"] == {"minute": 300, "day": 10000}
    principal = ExternalAPIPrincipal(
        user=SimpleNamespace(),
        api_key=SimpleNamespace(id=1),
        plan="plan_unknown",
    )

    with pytest.raises(HTTPException) as exc_info:
        await enforce_external_rate_limit(response=Response(), principal=principal)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == "RATE_LIMIT_CONFIGURATION_MISSING"


def test_external_api_rate_limit_returns_429(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    shared_sync_redis = FakeSyncRedis()
    try:
        user = _seed_user(db, email="limit@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr(
            "services.external_api_service.get_sync_redis",
            _persistent_sync_redis_ctx(shared_sync_redis),
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        last_response = None
        for _ in range(61):
            last_response = client.get("/api/v1/external/audits", headers=headers)
        assert last_response is not None
        assert last_response.status_code == 429
        assert last_response.json()["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert last_response.headers["Retry-After"] == "60"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_api_accepts_quota_tier_without_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SIGV2-1024: exhausted internal credits must not refuse the audit;
    # only the scan allowance may still gate the launch.
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        monkeypatch.setenv("AUDIT_QUOTA_TIERS", "smart")
        user = _seed_user(db, email="credits@example.com", credits=1)
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        response = client.post(
            "/api/v1/external/audit",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
            json={"url": "https://example.com", "tier": "smart"},
        )
        assert response.status_code == 202
    finally:
        main.app.dependency_overrides.clear()
        monkeypatch.delenv("AUDIT_QUOTA_TIERS", raising=False)
        _cleanup_db(db, engine)


def test_external_webhook_delivery_signs_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="webhook@example.com")
        api_key = _seed_api_key(db, user=user)

        job = models.AuditJob(
            id="job-webhook-1",
            user_id=user.id,
            api_key_id=api_key.id,
            status="succeeded",
            source="external",
            url="https://example.com",
            provider="google",
            tier="fast",
            estimated_credit_cost=1,
            consumed_credit_cost=1,
            request_id="req-webhook-1",
            webhook_url="https://agency.example/hooks/audit",
            webhook_secret="super-secret-key",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.add(
            models.Audit(
                user_id=user.id,
                url="https://example.com",
                geo_score=91.0,
                seo_score=84.0,
                aeo_score=79.0,
                full_report={"summary": "done"},
                request_id="req-webhook-1",
            )
        )
        db.commit()

        captured: dict[str, object] = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def post(self, url: str, content: bytes, headers: dict[str, str]):
                captured["url"] = url
                captured["content"] = content
                captured["headers"] = headers
                return httpx.Response(200, request=httpx.Request("POST", url))

        monkeypatch.setattr("services.external_webhook_service.httpx.AsyncClient", FakeAsyncClient)

        import asyncio

        assert asyncio.run(deliver_external_webhook_for_job(db, job_id="job-webhook-1")) is True
        db.refresh(job)

        body = captured["content"]
        assert captured["url"] == "https://agency.example/hooks/audit"
        assert isinstance(body, bytes)
        expected_signature = build_webhook_signature("super-secret-key", body)
        assert captured["headers"]["X-Qiko-Signal-Signature"] == expected_signature
        assert job.webhook_status == "delivered"
        assert job.webhook_delivered_at is not None
    finally:
        _cleanup_db(db, engine)


def test_external_brand_audit_creates_job_without_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brand audits should succeed with target_name and no url."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="brand@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        payload = {
            "audit_target_type": "brand",
            "target_name": "Acme Corp",
            "target_metadata": {"industry": "technology"},
            "tier": "fast",
        }

        response = client.post("/api/v1/external/audit", headers=headers, json=payload)
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["job_id"]
        assert body["idempotent_replay"] is False

        db_job = db.query(models.AuditJob).filter(models.AuditJob.id == body["job_id"]).first()
        assert db_job is not None
        assert db_job.audit_target_type.value == "brand"
        assert db_job.target_name == "Acme Corp"
        assert db_job.target_metadata == {"industry": "technology"}
        assert db_job.url == ""

        status_response = client.get(
            f"/api/v1/external/audit/{body['job_id']}",
            headers=headers,
        )
        assert status_response.status_code == 200
        status_body = status_response.json()
        assert status_body["audit_target_type"] == "brand"
        assert status_body["target_name"] == "Acme Corp"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_brand_audit_rejects_missing_target_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Brand audits without target_name should be rejected with 422."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="brand-err@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        payload = {
            "audit_target_type": "brand",
            "tier": "fast",
        }

        response = client.post("/api/v1/external/audit", headers=headers, json=payload)
        assert response.status_code == 422
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_website_audit_rejects_missing_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """Website audits without url should be rejected with 422."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="web-err@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        payload = {
            "audit_target_type": "website",
            "tier": "fast",
        }

        response = client.post("/api/v1/external/audit", headers=headers, json=payload)
        assert response.status_code == 422
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# Project read endpoint tests
# ---------------------------------------------------------------------------


def _seed_workspace_and_project(
    db: Session,
    *,
    user: models.User,
    project_name: str = "Test Project",
    domain_url: str = "https://example.com",
) -> tuple[models.Workspace, models.Project]:
    workspace = db.query(models.Workspace).filter(models.Workspace.owner_id == user.id).first()
    if workspace is None:
        workspace = models.Workspace(name="Test WS", owner_id=user.id)
        db.add(workspace)
        db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name=project_name,
        domain_url=domain_url,
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return workspace, project


def test_external_list_projects_returns_owned_projects(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/projects should list projects the API key owner can access."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="proj-list@example.com")
        _seed_api_key(db, user=user)
        _seed_workspace_and_project(db, user=user, project_name="Alpha")
        _seed_workspace_and_project(db, user=user, project_name="Beta")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        response = client.get("/api/v1/external/projects", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2
        names = {item["name"] for item in body["items"]}
        assert "Alpha" in names
        assert "Beta" in names
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_get_project_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/projects/{id} should return project detail with audit counts."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="proj-detail@example.com")
        _seed_api_key(db, user=user)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Detail Project")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        response = client.get(f"/api/v1/external/projects/{project.id}", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["id"] == project.id
        assert body["name"] == "Detail Project"
        assert body["total_audits"] == 0
        assert body["domain_url"] == "https://example.com"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_get_project_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/projects/{id} for non-existent project should return 404."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="proj-404@example.com")
        _seed_api_key(db, user=user)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        response = client.get("/api/v1/external/projects/99999", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


# ---------------------------------------------------------------------------
# TASK-95/96/97 — New External API Endpoint Tests
# ---------------------------------------------------------------------------

ALL_SCOPES = list(API_KEY_SCOPES)


def test_external_generate_report_publishes_worker_payload_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="report-contract@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _workspace, project = _seed_workspace_and_project(
            db,
            user=user,
            project_name="Report Contract",
        )
        audits = [
            models.Audit(
                user_id=user.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=f"https://example.com/{suffix}",
                geo_score=80.0,
                seo_score=81.0,
                aeo_score=82.0,
                full_report={"status": "complete"},
            )
            for suffix in ("primary", "comparison")
        ]
        db.add_all(audits)
        db.commit()
        for audit in audits:
            db.refresh(audit)

        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)
        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        audit_ids = [audit.id for audit in audits]
        response = client.post(
            "/api/v1/external/reports/generate",
            headers={"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"},
            json={"audit_ids": audit_ids, "template_type": "Comparative"},
        )

        assert response.status_code == 202, response.text
        queued_json = fake_redis.lists["pdf_jobs"][0]
        raw_payload = json.loads(queued_json)
        worker_payload = parse_pdf_job_payload(raw_payload)
        assert "report_id" not in raw_payload
        assert worker_payload.job_id == response.json()["report_id"]
        assert worker_payload.user_id == user.id
        assert worker_payload.template_type == "Comparative"
        assert worker_payload.audit_ids == audit_ids
        assert raw_payload["source"] == "external_api"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_scheduled_audit_crud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full CRUD flow for scheduled audits via the external API."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="sched@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Sched Project")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}

        # Create
        create_resp = client.post(
            "/api/v1/external/scheduled-audits",
            headers=headers,
            json={
                "project_id": project.id,
                "audit_type": "FAST",
                "frequency": "weekly",
                "is_active": True,
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert created["project_id"] == project.id
        assert created["frequency"] == "weekly"
        assert created["is_active"] is True
        schedule_id = created["id"]

        # List
        list_resp = client.get("/api/v1/external/scheduled-audits", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1

        # Get
        get_resp = client.get(f"/api/v1/external/scheduled-audits/{schedule_id}", headers=headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == schedule_id

        # Update
        patch_resp = client.patch(
            f"/api/v1/external/scheduled-audits/{schedule_id}",
            headers=headers,
            json={"frequency": "monthly", "is_active": False},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["frequency"] == "monthly"
        assert patch_resp.json()["is_active"] is False

        # Delete
        delete_resp = client.delete(
            f"/api/v1/external/scheduled-audits/{schedule_id}", headers=headers
        )
        assert delete_resp.status_code == 204

        # Verify deleted
        get_after = client.get(f"/api/v1/external/scheduled-audits/{schedule_id}", headers=headers)
        assert get_after.status_code == 404
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_scheduled_audit_requires_project_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating a scheduled audit without project_id returns 400."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="sched-err@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.post(
            "/api/v1/external/scheduled-audits",
            headers=headers,
            json={"audit_type": "FAST", "frequency": "weekly"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_scheduled_audit_duplicate_returns_409(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating a duplicate schedule for the same project returns 409."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="sched-dup@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Dup Project")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        first = client.post(
            "/api/v1/external/scheduled-audits",
            headers=headers,
            json={"project_id": project.id, "audit_type": "FAST", "frequency": "weekly"},
        )
        assert first.status_code == 201

        second = client.post(
            "/api/v1/external/scheduled-audits",
            headers=headers,
            json={"project_id": project.id, "audit_type": "FAST", "frequency": "monthly"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "DUPLICATE_SCHEDULE"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_alert_rule_crud(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full CRUD flow for alert rules via the external API."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="alert@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Alert Project")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}

        # Create
        create_resp = client.post(
            f"/api/v1/external/projects/{project.id}/alerts",
            headers=headers,
            json={
                "metric": "geo_score",
                "condition": "below",
                "threshold": 70.0,
                "email_to": "alerts@example.com",
            },
        )
        assert create_resp.status_code == 201, create_resp.text
        created = create_resp.json()
        assert created["metric"] == "geo_score"
        assert created["condition"] == "below"
        assert created["threshold"] == 70.0
        rule_id = created["id"]

        # List
        list_resp = client.get(f"/api/v1/external/projects/{project.id}/alerts", headers=headers)
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1

        # Update
        update_resp = client.put(
            f"/api/v1/external/projects/{project.id}/alerts/{rule_id}",
            headers=headers,
            json={"threshold": 60.0, "is_active": False},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["threshold"] == 60.0
        assert update_resp.json()["is_active"] is False

        # Delete
        delete_resp = client.delete(
            f"/api/v1/external/projects/{project.id}/alerts/{rule_id}",
            headers=headers,
        )
        assert delete_resp.status_code == 204

        # Verify deleted
        list_after = client.get(f"/api/v1/external/projects/{project.id}/alerts", headers=headers)
        assert list_after.json()["total"] == 0
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_alert_rule_validates_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    """Creating an alert with invalid metric returns 400."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="alert-bad@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Alert Bad")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.post(
            f"/api/v1/external/projects/{project.id}/alerts",
            headers=headers,
            json={
                "metric": "invalid_metric",
                "condition": "below",
                "threshold": 50.0,
                "email_to": "x@x.com",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_alert_rule_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """Updating a non-existent alert returns 404."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="alert-nf@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Alert NF")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.put(
            f"/api/v1/external/projects/{project.id}/alerts/99999",
            headers=headers,
            json={"threshold": 50.0},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "ALERT_RULE_NOT_FOUND"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_openapi_spec_returns_external_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/openapi.json returns filtered external API paths."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="openapi@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.get("/api/v1/external/openapi.json", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["openapi"]
        assert body["info"]["title"] == "Qiko Signal External API"
        for path_key in body.get("paths", {}):
            assert "external" in path_key.lower()
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_sdk_metadata_returns_expected_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/sdk-metadata returns API metadata with new scopes."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="sdk@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.get("/api/v1/external/sdk-metadata", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["api_version"] == "v1"
        assert body["base_path"] == "/api/v1/external"
        assert "audit:read" in body["available_scopes"]
        assert "monitoring:read" in body["available_scopes"]
        assert "workflows:read" in body["available_scopes"]
        assert "alerts:write" in body["available_scopes"]
        assert "supported_providers" not in body
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_scope_gating_rejects_wrong_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Endpoints reject requests when the API key lacks the required scope."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="scope-gate@example.com")
        _seed_api_key(db, user=user, scopes=["audit:read"])
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Scope Test")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}

        # schedules:read required
        resp = client.get("/api/v1/external/scheduled-audits", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "INVALID_API_KEY"
        assert "schedules:read" in resp.json()["error"]["message"]

        # alerts:read required
        resp = client.get(f"/api/v1/external/projects/{project.id}/alerts", headers=headers)
        assert resp.status_code == 403
        assert "alerts:read" in resp.json()["error"]["message"]

        # workflows:read required
        resp = client.get(f"/api/v1/external/projects/{project.id}/workflows", headers=headers)
        assert resp.status_code == 403
        assert "workflows:read" in resp.json()["error"]["message"]

        # monitoring:read required
        resp = client.get(
            f"/api/v1/external/projects/{project.id}/visibility/summary", headers=headers
        )
        assert resp.status_code == 403
        assert "monitoring:read" in resp.json()["error"]["message"]
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_project_not_found_for_new_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    """New project-scoped endpoints return 404 for non-existent projects."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="new-404@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        endpoints = [
            "/api/v1/external/projects/99999/alerts",
            "/api/v1/external/projects/99999/tasks",
            "/api/v1/external/projects/99999/competitors",
        ]
        for url in endpoints:
            resp = client.get(url, headers=headers)
            assert resp.status_code == 404, f"{url} expected 404, got {resp.status_code}"
            assert resp.json()["error"]["code"] == "PROJECT_NOT_FOUND"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_task_list_returns_empty_for_new_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/projects/{id}/tasks returns empty list for a project with no tasks."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="task-list@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Tasks Project")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.get(f"/api/v1/external/projects/{project.id}/tasks", headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert "summary" in body
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)


def test_external_task_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /external/projects/{id}/tasks/{task_id} returns 404 for non-existent task."""
    db, engine = _build_db()
    fake_redis = FakeRedis()
    try:
        user = _seed_user(db, email="task-nf@example.com")
        _seed_api_key(db, user=user, scopes=ALL_SCOPES)
        _ws, project = _seed_workspace_and_project(db, user=user, project_name="Task NF")
        client = _build_client(db, auth_user=user, monkeypatch=monkeypatch)

        monkeypatch.setattr("services.external_api_service.get_sync_redis", _fake_sync_redis_ctx)
        monkeypatch.setattr(
            "routers.external_api_router.get_async_redis", _fake_redis_ctx(fake_redis)
        )

        headers = {"X-API-Key": "stx_live_0123456789abcdef0123456789abcd"}
        resp = client.get(f"/api/v1/external/projects/{project.id}/tasks/99999", headers=headers)
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "TASK_NOT_FOUND"
    finally:
        main.app.dependency_overrides.clear()
        _cleanup_db(db, engine)
