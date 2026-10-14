"""SIGV2-1137: the synchronous audit path is metered like every other path.

``POST /api/v1/audit`` creates an ``Audit`` and runs real provider work, but it
created no ``AuditJob``, and the customer-facing scan allowance counts
``AuditJob`` rows. A scan run through this endpoint was therefore free: invisible
in the used count, and nothing refused it at the limit. Scans are the only
customer-facing limit, so that is a billing bypass.

Reachability, which decides whether an unmetered path is acceptable: the route
is registered on the app behind ``get_current_user`` (a normal customer session,
no admin role, no internal-service guard, no feature flag) and it is documented
for customers in ``docs/api.md``. It is customer-reachable, so it is metered.
``test_the_synchronous_path_is_customer_reachable`` pins that reachability, so a
change that re-scopes the endpoint is a visible decision rather than a silent
one.

The meter is not duplicated. The run consumes the allowance through
``consume_scan_allowance`` and records the ``AuditJob`` row that allowance
counts, declaring ``scan_origin='customer'`` because the customer launched it.
Every test here fails on the pre-fix code: the counting ones because nothing was
counted, the refusal one because nothing refused.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
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
from services.scan_allowance_service import scan_allowance_snapshot

COMPETITOR_LITE_CATEGORY = "Competitor Lite Audit"


class FakeRedisClient:
    """Enough of the async Redis surface for the synchronous audit path."""

    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def get(self, _key: str):
        return None

    async def set(self, key: str, value: str, ex: int | None = None):
        del ex
        self.store[key] = value

    async def setex(self, key: str, _ttl: int, value: str):
        self.store[key] = value

    async def expire(self, _key: str, _ttl: int):
        return True

    async def delete(self, *keys: str):
        for key in keys:
            self.store.pop(key, None)
        return len(keys)

    async def hset(self, key: str, mapping: dict):
        self.store[key] = dict(mapping)
        return len(mapping)

    async def hgetall(self, key: str):
        value = self.store.get(key)
        return dict(value) if isinstance(value, dict) else {}

    async def rpush(self, *_args, **_kwargs):
        return 1

    async def close(self):
        return None

    async def aclose(self):
        return None


@pytest.fixture
def sync_audit_context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = session_factory()
    user = models.User(
        email="sync-metering@example.com",
        hashed_password="x",
        role="user",
        credits=50,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Metering Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Metering Project",
        domain_url="https://example.com",
        target_country="US",
        language="en",
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
    monkeypatch.setattr(
        main.api_module,
        "enforce_authenticated_audit_limit",
        noop_enforce_authenticated_audit_limit,
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib, "from_url", lambda *_a, **_k: FakeRedisClient()
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *_a, **_k: FakeRedisClient()
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="available"),
    )

    perform_audit = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 80, "geo_score": 81, "aeo_score": 82},
                "metadata": {"plan": "plan_starter", "audit_outcome": "completed"},
            },
            {"seo": 80.0, "geo": 81.0, "aeo": 82.0, "overall": 81.0},
        )
    )
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit)
    monkeypatch.setattr(
        main.api_module,
        "fetch_url_signature",
        AsyncMock(return_value={"content_hash": "metering-signature"}),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    yield {
        "client": TestClient(main.app),
        "db": db,
        "user": user,
        "project": project,
        "perform_audit": perform_audit,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_subscription(db, user: models.User, plan: str) -> None:
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_sync_metering_{user.id}",
            plan_type=plan,
            status="active",
        )
    )
    db.commit()
    db.refresh(user)


def _launch(context, **overrides):
    body = {
        "url": "https://example.com",
        "provider": "google",
        "tier": "fast",
        "project_id": context["project"].id,
    }
    body.update(overrides)
    return context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-sync-metering"},
        json=body,
    )


def _add_consumed_scan(db, user: models.User, *, job_id: str, days_ago: float = 0) -> None:
    db.add(
        models.AuditJob(
            id=job_id,
            user_id=user.id,
            status="succeeded",
            audit_target_type=models.AuditTargetType.WEBSITE,
            url="https://already-scanned.example",
            request_id=f"audit-job:{job_id}",
            created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
            scan_origin=models.SCAN_ORIGIN_CUSTOMER,
        )
    )
    db.commit()


def test_the_synchronous_path_is_customer_reachable(sync_audit_context) -> None:
    """Why this path must be metered at all.

    If it were internal-only, leaving it unmetered could be a deliberate
    choice. It is not: the route is on the app behind the ordinary customer
    session dependency, with no admin or internal-service guard.
    """
    route = next(
        candidate
        for candidate in main.app.routes
        if getattr(candidate, "path", None) == "/api/v1/audit"
        and "POST" in getattr(candidate, "methods", set())
    )
    dependency_names = {
        dependency.call.__name__
        for dependency in route.dependant.dependencies
        if getattr(dependency, "call", None) is not None
    }
    assert "get_current_user" in dependency_names
    assert not any("admin" in name.lower() for name in dependency_names)


def test_synchronous_audit_consumes_exactly_one_scan(sync_audit_context) -> None:
    db, user = sync_audit_context["db"], sync_audit_context["user"]
    assert scan_allowance_snapshot(db, user).scans_used == 0

    response = _launch(sync_audit_context)

    assert response.status_code == 200, response.text
    assert sync_audit_context["perform_audit"].await_count == 1

    snapshot = scan_allowance_snapshot(db, user)
    assert snapshot.scans_used == 1
    assert snapshot.scans_remaining == 0

    jobs = db.query(models.AuditJob).all()
    assert len(jobs) == 1
    assert jobs[0].scan_origin == models.SCAN_ORIGIN_CUSTOMER
    assert jobs[0].status == "succeeded"
    assert jobs[0].completed_at is not None
    # Nothing to beat a heartbeat for a synchronous run, so none is written:
    # the cron sweeper only fails a running job whose heartbeat went stale.
    assert jobs[0].last_heartbeat is None
    assert jobs[0].project_id == sync_audit_context["project"].id

    audit = db.query(models.Audit).one()
    # The metering row and the audit it metered share the correlation id.
    assert jobs[0].request_id == audit.request_id


def test_synchronous_audit_is_refused_at_the_limit(sync_audit_context) -> None:
    """The refusal happens before the work, so it costs nothing."""
    db, user = sync_audit_context["db"], sync_audit_context["user"]
    _add_consumed_scan(db, user, job_id="already-consumed-1")
    assert scan_allowance_snapshot(db, user).scans_remaining == 0

    response = _launch(sync_audit_context, url="https://second-target.example")

    assert response.status_code == 402, response.text
    assert "Scan limit reached" in response.json()["detail"]
    assert sync_audit_context["perform_audit"].await_count == 0
    assert db.query(models.Audit).count() == 0
    assert db.query(models.AuditJob).count() == 1
    assert scan_allowance_snapshot(db, user).scans_used == 1


def test_scan_leaving_the_rolling_window_frees_the_synchronous_path(sync_audit_context) -> None:
    db, user = sync_audit_context["db"], sync_audit_context["user"]
    _add_consumed_scan(db, user, job_id="aged-out-1", days_ago=31)
    assert scan_allowance_snapshot(db, user).scans_used == 0

    response = _launch(sync_audit_context)

    assert response.status_code == 200, response.text
    assert scan_allowance_snapshot(db, user).scans_used == 1


def test_customer_requested_competitor_lite_audit_is_still_billed(sync_audit_context) -> None:
    """SIGV2-1129's asymmetry, applied to this path.

    The job is billed on who launched the scan, not on what it measures. The
    customer asked for this competitor lite audit, so it is one of their scans
    even though the audit row is classified as a competitor measurement. Keying
    billing on the measurement instead would let any entitled caller set
    ``category`` on every request and never consume a scan.
    """
    db, user = sync_audit_context["db"], sync_audit_context["user"]
    _seed_subscription(db, user, "plan_specialist")

    response = _launch(sync_audit_context, category=COMPETITOR_LITE_CATEGORY)

    assert response.status_code == 200, response.text
    job = db.query(models.AuditJob).one()
    assert job.scan_origin == models.SCAN_ORIGIN_CUSTOMER
    assert scan_allowance_snapshot(db, user).scans_used == 1
    audit = db.query(models.Audit).one()
    assert audit.project_scope == models.AUDIT_PROJECT_SCOPE_COMPETITOR


def test_failed_synchronous_run_still_consumes_the_scan(sync_audit_context) -> None:
    """A failure is not a free retry, which is the existing allowance contract."""
    db, user = sync_audit_context["db"], sync_audit_context["user"]
    sync_audit_context["perform_audit"].side_effect = RuntimeError("provider exploded")

    with pytest.raises(RuntimeError):
        _launch(sync_audit_context)

    job = db.query(models.AuditJob).one()
    assert job.status == "failed"
    assert job.scan_origin == models.SCAN_ORIGIN_CUSTOMER
    assert scan_allowance_snapshot(db, user).scans_used == 1
