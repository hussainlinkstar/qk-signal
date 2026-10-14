"""Tests for GET /api/v1/audit/jobs/active endpoint."""

import importlib
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base


class _LazyModuleProxy:
    """Deferred import so env-vars are settled before the app module loads."""

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


main = _LazyModuleProxy("main")


# ---------------------------------------------------------------------------
# Fake Redis (minimal, identical to the pattern in test_audit_endpoint)
# ---------------------------------------------------------------------------


class FakeRedisClient:
    def __init__(self):
        self._store: dict = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    async def hset(self, key: str, mapping: dict):
        self._store[key] = dict(mapping)

    async def hgetall(self, key: str):
        value = self._store.get(key)
        return dict(value) if isinstance(value, dict) else {}

    async def rpush(self, key: str, value: str):
        existing = self._store.get(key)
        if isinstance(existing, list):
            existing.append(value)
        elif existing is None:
            self._store[key] = [value]
        else:
            self._store[key] = [existing, value]

    async def lrange(self, key: str, start: int, end: int):
        value = self._store.get(key)
        items = list(value) if isinstance(value, list) else []
        normalized_end = None if end == -1 else end + 1
        return items[start:normalized_end]

    async def delete(self, *keys: str):
        for key in keys:
            self._store.pop(key, None)

    async def aclose(self):
        pass

    async def close(self):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_session():
    """Create an in-memory SQLite database with a single user & project."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="active-jobs-test@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Test Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Test Project",
        domain_url="https://example.com",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return engine, db, user, project


def _make_audit_job(
    db,
    *,
    user_id,
    status="running",
    started_minutes_ago=5,
    heartbeat_minutes_ago=1,
    project_id=None,
    target_name="example.com",
    target_url="https://example.com",
    tier="fast",
):
    """Insert an AuditJob row and return the generated id."""
    now = datetime.now(timezone.utc)
    job_id = str(uuid.uuid4())
    job = models.AuditJob(
        id=job_id,
        user_id=user_id,
        status=status,
        url="https://example.com",
        audit_target_type=models.AuditTargetType.WEBSITE,
        target_name=target_name,
        target_url=target_url,
        tier=tier,
        started_at=now - timedelta(minutes=started_minutes_ago),
        last_heartbeat=(
            now - timedelta(minutes=heartbeat_minutes_ago)
            if heartbeat_minutes_ago is not None
            else None
        ),
        project_id=project_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job_id


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_context(monkeypatch: pytest.MonkeyPatch):
    """
    Provide a TestClient with dependency overrides for get_db,
    get_current_user, and patched middleware / redis.
    """
    engine, db, user, project = _build_test_session()
    maintenance_module = importlib.import_module("middleware.maintenance")
    from services.ai_routing_policy import provider_runtime_state_service

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
        main,
        "enforce_authenticated_audit_limit",
        noop_enforce_authenticated_audit_limit,
    )
    monkeypatch.setattr(
        main.api_module,
        "enforce_authenticated_audit_limit",
        noop_enforce_authenticated_audit_limit,
    )
    monkeypatch.setattr(
        main,
        "tenant_resolver_middleware",
        noop_tenant_resolver_middleware,
    )
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
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


ENDPOINT = "/api/v1/audit/jobs/active"


# ---------------------------------------------------------------------------
# 1. Unauthenticated requests are rejected
# ---------------------------------------------------------------------------


def test_unauthenticated_returns_401_or_403(monkeypatch: pytest.MonkeyPatch):
    """Without auth override the endpoint must reject the request."""
    engine, db, _user, _project = _build_test_session()
    maintenance_module = importlib.import_module("middleware.maintenance")

    def override_get_db():
        try:
            yield db
        finally:
            pass

    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    monkeypatch.setattr(
        main,
        "tenant_resolver_middleware",
        noop_tenant_resolver_middleware,
    )
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *a, **kw: FakeRedisClient()
    )

    # Only override get_db — do NOT override get_current_user
    main.app.dependency_overrides[main.get_db] = override_get_db

    try:
        client = TestClient(main.app, raise_server_exceptions=False)
        response = client.get(ENDPOINT)
        assert response.status_code in (401, 403)
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# 2. No active jobs → empty list
# ---------------------------------------------------------------------------


def test_no_active_jobs_returns_empty_list(test_context):
    """When the user has no queued/running jobs the response is an empty list."""
    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    assert body["jobs"] == []


# ---------------------------------------------------------------------------
# 3. Returns only the current user's active jobs (not other users')
# ---------------------------------------------------------------------------


def test_returns_only_current_users_active_jobs(test_context):
    """Jobs belonging to a different user must not appear in the response."""
    db = test_context["db"]
    user = test_context["user"]
    project = test_context["project"]

    # Create a second user
    other_user = models.User(
        email="other@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(other_user)
    db.commit()
    db.refresh(other_user)

    # Job for the authenticated user (should appear)
    own_job_id = _make_audit_job(
        db,
        user_id=user.id,
        status="running",
        project_id=project.id,
        target_name="my-site.com",
    )

    # Job for the other user (should NOT appear)
    _make_audit_job(
        db,
        user_id=other_user.id,
        status="running",
        target_name="other-site.com",
    )

    # A queued job for the authenticated user (should also appear)
    queued_job_id = _make_audit_job(
        db,
        user_id=user.id,
        status="queued",
        target_name="queued-site.com",
    )

    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    returned_ids = {j["job_id"] for j in body["jobs"]}

    assert own_job_id in returned_ids
    assert queued_job_id in returned_ids
    assert len(returned_ids) == 2

    # Verify basic summary fields on the running job
    own_job = next(j for j in body["jobs"] if j["job_id"] == own_job_id)
    assert own_job["status"] == "running"
    assert own_job["target_name"] == "my-site.com"
    assert own_job["target_url"] == "https://example.com"
    assert own_job["tier"] == "fast"
    assert own_job["project_id"] == project.id
    assert own_job["audit_target_type"] == "website"


# ---------------------------------------------------------------------------
# 4. Stale detection
# ---------------------------------------------------------------------------


def test_stale_warning_when_heartbeat_over_60s(test_context):
    """A job with last_heartbeat > 60s ago should be flagged stale (warning)."""
    db = test_context["db"]
    user = test_context["user"]

    job_id = _make_audit_job(
        db,
        user_id=user.id,
        status="running",
        heartbeat_minutes_ago=2,  # 120 seconds — over 60s threshold
    )

    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    job = next(j for j in body["jobs"] if j["job_id"] == job_id)
    assert job["stale"] is True
    assert job["stale_reason"] is not None
    assert "1 minute" in job["stale_reason"]


def test_stale_failure_when_heartbeat_over_300s(test_context):
    """A job with last_heartbeat > 300s ago should be flagged stale with 5-min message."""
    db = test_context["db"]
    user = test_context["user"]

    job_id = _make_audit_job(
        db,
        user_id=user.id,
        status="running",
        heartbeat_minutes_ago=6,  # 360 seconds — over 300s threshold
    )

    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    job = next(j for j in body["jobs"] if j["job_id"] == job_id)
    assert job["stale"] is True
    assert job["stale_reason"] is not None
    assert "5 minutes" in job["stale_reason"]


def test_not_stale_when_heartbeat_recent(test_context):
    """A job with last_heartbeat < 60s ago should NOT be stale."""
    db = test_context["db"]
    user = test_context["user"]

    job_id = _make_audit_job(
        db,
        user_id=user.id,
        status="running",
        heartbeat_minutes_ago=0,  # just now
    )

    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    job = next(j for j in body["jobs"] if j["job_id"] == job_id)
    assert job["stale"] is False
    assert job["stale_reason"] is None


# ---------------------------------------------------------------------------
# 5. Terminal jobs excluded — completed/failed should not appear
# ---------------------------------------------------------------------------


def test_terminal_jobs_excluded(test_context):
    """Jobs with status completed or failed must NOT appear in the response."""
    db = test_context["db"]
    user = test_context["user"]

    # Create terminal jobs
    _make_audit_job(db, user_id=user.id, status="completed")
    _make_audit_job(db, user_id=user.id, status="failed")

    # Create one active job so we can verify filtering
    active_id = _make_audit_job(db, user_id=user.id, status="running")

    response = test_context["client"].get(ENDPOINT)
    assert response.status_code == 200

    body = response.json()
    returned_ids = {j["job_id"] for j in body["jobs"]}
    returned_statuses = {j["status"] for j in body["jobs"]}

    assert active_id in returned_ids
    assert len(returned_ids) == 1
    assert "completed" not in returned_statuses
    assert "failed" not in returned_statuses
