"""Tests for moderator role access control across admin endpoints."""

from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import admin
import models
from database import Base
from auth.token_verifier import get_current_user as base_get_current_user
from admin import get_db

from main import app


class _FakeRedisClient:
    """Minimal stand-in for the async redis client used by admin job endpoints.

    Only the methods admin.py's job-queue/status routes actually call.
    """

    async def llen(self, _key):
        return 0

    async def get(self, _key):
        return None

    async def hgetall(self, _key):
        return {}


def _patch_async_redis(monkeypatch) -> None:
    @asynccontextmanager
    async def fake_get_async_redis(**_kwargs):
        yield _FakeRedisClient()

    monkeypatch.setattr(admin, "get_async_redis", fake_get_async_redis)


def _build_user(*, role: str) -> models.User:
    user = models.User(
        email=f"{role}@example.com",
        hashed_password="hashed",
        role=role,
        credits=100,
        notifications_enabled=True,
        unsubscribe_token=f"{role}-unsub-token",
    )
    return user


def _setup(role: str):
    """Create a TestClient with admin.py routes backed by an in-memory DB.

    Overrides the *base* ``get_current_user`` dependency so that the
    role-gate dependencies (``get_current_admin_user`` /
    ``get_current_staff_user``) exercise their real logic.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    user = _build_user(role=role)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Attach resolved_role so the gate dependencies behave as in production
    setattr(user, "resolved_role", role)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_base_get_current_user() -> models.User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[base_get_current_user] = override_base_get_current_user

    return TestClient(app), db, user, engine


def _teardown(client, db, engine):
    client.close()
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


# ── Staff-accessible endpoints (moderator should get 200) ──────────

STAFF_ENDPOINTS = [
    ("GET", "/api/v1/admin/metrics"),
    ("GET", "/api/v1/admin/metrics/timeseries"),
    ("GET", "/api/v1/admin/token-usage"),
    ("GET", "/api/v1/admin/audits"),
    ("GET", "/api/v1/admin/operations"),
    ("GET", "/api/v1/admin/action-logs"),
    ("GET", "/api/v1/admin/email-outbox"),
    ("GET", "/api/v1/admin/email-outbox/stats"),
    ("GET", "/api/v1/admin/jobs/queues"),
    ("GET", "/api/v1/admin/jobs/recent"),
    ("GET", "/api/v1/admin/jobs/stats"),
    ("GET", "/api/v1/admin/costs/summary"),
    ("GET", "/api/v1/admin/plans"),
    ("GET", "/api/v1/admin/email-templates"),
]

# ── Admin-only endpoints (moderator should get 403) ────────────────

ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/v1/admin/users"),
    ("GET", "/api/v1/admin/billing/subscriptions"),
    ("GET", "/api/v1/admin/billing/config"),
    ("GET", "/api/v1/admin/billing/overview"),
    ("GET", "/api/v1/admin/billing/invoices"),
    ("GET", "/api/v1/admin/billing/commitments"),
    ("GET", "/api/v1/admin/settings"),
    ("GET", "/api/v1/admin/settings/ai-providers"),
    ("GET", "/api/v1/admin/settings/dynamic"),
    ("GET", "/api/v1/admin/config"),
    ("GET", "/api/v1/admin/config/editable"),
    ("GET", "/api/v1/admin/gdpr/data-map"),
    ("GET", "/api/v1/admin/workspaces"),
    ("GET", "/api/v1/admin/feature-flags"),
    ("GET", "/api/v1/admin/maintenance"),
]


class TestModeratorStaffAccess:
    """Moderator should be able to reach staff-accessible endpoints."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, monkeypatch):
        _patch_async_redis(monkeypatch)
        self.client, self.db, self.user, self.engine = _setup("moderator")
        yield
        _teardown(self.client, self.db, self.engine)

    @pytest.mark.parametrize("method,path", STAFF_ENDPOINTS)
    def test_moderator_can_access_staff_endpoints(self, method, path):
        response = self.client.request(method, path)
        assert response.status_code != 403, f"Moderator should access {method} {path} but got 403"


class TestModeratorAdminBlocked:
    """Moderator should be blocked from admin-only endpoints."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.client, self.db, self.user, self.engine = _setup("moderator")
        yield
        _teardown(self.client, self.db, self.engine)

    @pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
    def test_moderator_blocked_from_admin_endpoints(self, method, path):
        response = self.client.request(method, path)
        assert (
            response.status_code == 403
        ), f"Moderator should be blocked from {method} {path} but got {response.status_code}"


class TestAdminFullAccess:
    """Admin should be able to access all endpoints."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self, monkeypatch):
        _patch_async_redis(monkeypatch)
        self.client, self.db, self.user, self.engine = _setup("admin")
        yield
        _teardown(self.client, self.db, self.engine)

    @pytest.mark.parametrize("method,path", STAFF_ENDPOINTS + ADMIN_ONLY_ENDPOINTS)
    def test_admin_can_access_all_endpoints(self, method, path):
        response = self.client.request(method, path)
        assert response.status_code != 403, f"Admin should access {method} {path} but got 403"


class TestRegularUserBlocked:
    """Regular user should be blocked from all admin endpoints."""

    @pytest.fixture(autouse=True)
    def setup_and_teardown(self):
        self.client, self.db, self.user, self.engine = _setup("user")
        yield
        _teardown(self.client, self.db, self.engine)

    @pytest.mark.parametrize("method,path", STAFF_ENDPOINTS[:3] + ADMIN_ONLY_ENDPOINTS[:3])
    def test_regular_user_blocked(self, method, path):
        response = self.client.request(method, path)
        assert (
            response.status_code == 403
        ), f"Regular user should be blocked from {method} {path} but got {response.status_code}"
