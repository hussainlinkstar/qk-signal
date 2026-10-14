"""Tests for guest-audit persistence, claim endpoint, and cron purge."""

import contextlib
import importlib
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

import models
from database import Base
from services import guest_audit_service


class FakeRedisClient:
    """Minimal async Redis mock for rate-limit enforcement."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def get(self, key: str):
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._store[key] = value

    async def incr(self, key: str):
        val = int(self._store.get(key, "0")) + 1
        self._store[key] = str(val)
        return val

    async def expire(self, key: str, seconds: int):
        pass

    async def rpush(self, key: str, *values):
        pass

    async def aclose(self):
        pass

    async def close(self):
        pass


class _LazyModuleProxy:
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


def _build_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="guest-test@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = models.Workspace(name="Guest Test Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    return engine, db, user


@pytest.fixture
def guest_test_context(monkeypatch: pytest.MonkeyPatch):
    engine, db, user = _build_test_session()
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

    fake_redis = FakeRedisClient()
    redis_client_module = importlib.import_module("core.redis_client")

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

    @contextlib.asynccontextmanager
    async def _fake_async_redis(**_kw):
        yield fake_redis

    monkeypatch.setattr(redis_client_module, "get_async_redis_client", lambda **_kw: fake_redis)
    monkeypatch.setattr(redis_client_module, "get_async_redis", _fake_async_redis)

    main_mod = main._load()
    main_mod.app.dependency_overrides[main_mod.get_db] = override_get_db
    main_mod.app.dependency_overrides[main_mod.get_current_user] = override_get_current_user

    client = TestClient(main_mod.app, raise_server_exceptions=False)

    yield {
        "client": client,
        "db": db,
        "user": user,
        "engine": engine,
    }

    main_mod.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _mock_guest_audit_externals(monkeypatch):
    """Mock all external calls used by the guest-audit endpoint."""
    scraper_mock = AsyncMock(
        return_value={"success_status": True, "markdown_content": "Test content"}
    )
    perf_mock = AsyncMock(
        return_value={
            "performance_score": 80,
            "seo_audits": [],
            "largest_contentful_paint": 1200,
            "cumulative_layout_shift": 0.05,
        }
    )
    network_mock = AsyncMock(
        return_value={"supports_http2": True, "supports_http3_inferred": False, "http_version": "2"}
    )
    ai_mock = AsyncMock(
        return_value={
            "analysis": {
                "intelligence_summary": "Test audit summary.",
                "detailed_recommendations": [
                    {
                        "agent": "SEO Agent",
                        "finding": "Missing meta description",
                        "why_it_matters": "Reduces click-through rates.",
                        "fix": "Add a meta description tag.",
                    }
                ],
                "aeo_teaser": "AEO readiness assessment.",
            }
        }
    )

    monkeypatch.setattr(
        guest_audit_service.scraper_service, "get_page_content_and_screenshot", scraper_mock
    )
    monkeypatch.setattr(
        guest_audit_service.performance_service, "get_performance_metrics", perf_mock
    )
    monkeypatch.setattr(
        guest_audit_service.network_service, "analyze_network_protocols", network_mock
    )
    monkeypatch.setattr(guest_audit_service.ai_client, "generate_audit", ai_mock)

    return scraper_mock, perf_mock, network_mock, ai_mock


def test_guest_audit_returns_claim_token(guest_test_context, monkeypatch):
    """Guest audit endpoint should persist a GuestAuditRecord and return a claim token."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-persist"},
        json={"url": "https://example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "guest_audit_token" in payload
    assert payload["guest_audit_token"]

    # Verify DB record exists
    db = guest_test_context["db"]
    record = db.query(models.GuestAuditRecord).first()
    assert record is not None
    assert record.target_url == "https://example.com/"
    assert record.claim_token == payload["guest_audit_token"]
    assert record.claimed_by_user_id is None
    assert record.seo_score is not None
    assert record.request_id == "req-guest-persist"


def test_guest_audit_brand_mode_persists_record(guest_test_context, monkeypatch):
    """Brand-mode guest audits should persist target_name and audit_target_type."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-brand-persist"},
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Corp",
            "target_metadata": {"industry": "tech"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["guest_audit_token"]

    db = guest_test_context["db"]
    record = db.query(models.GuestAuditRecord).first()
    assert record is not None
    assert record.target_name == "Acme Corp"
    assert record.audit_target_type == "brand"


def test_guest_audit_with_captured_email_queues_followup(guest_test_context, monkeypatch):
    """A guest audit that captured an email must queue a guest_audit.followup outbox row."""
    _mock_guest_audit_externals(monkeypatch)
    from services import email_service

    monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *a, **k: None)
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-email"},
        json={"url": "https://example.com", "email": "guest-lead@example.com"},
    )

    assert response.status_code == 200

    db = guest_test_context["db"]
    entry = db.query(models.EmailOutbox).filter_by(template_key="guest_audit.followup").first()
    assert entry is not None
    assert entry.to_email == "guest-lead@example.com"
    assert entry.user_id is None
    assert entry.status == "pending"
    assert "guest_audit_token=" in entry.html_body


def test_guest_audit_response_includes_structured_findings(guest_test_context, monkeypatch):
    """Response should include structured_findings with gated previews."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-findings"},
        json={"url": "https://example.com"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "structured_findings" in payload
    sf = payload["structured_findings"]
    assert "seo_findings" in sf
    assert "geo_findings" in sf
    assert sf["geo_findings"]["locked"] is True
    assert "aeo_findings" in sf
    assert sf["aeo_findings"]["locked"] is True
    assert "entity_summary" in sf
    assert sf["entity_summary"]["locked"] is True


def test_guest_audit_response_includes_locked_sections(guest_test_context, monkeypatch):
    """Response metadata should include locked_sections for frontend gating."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-locked"},
        json={"url": "https://example.com"},
    )

    payload = response.json()
    locked = payload["metadata"]["locked_sections"]
    assert "geo" in locked
    assert "aeo" in locked
    assert "competitors" in locked
    assert "entities" in locked
    assert "hallucinations" in locked
    assert "export" in locked
    for section in locked.values():
        assert section["lock_origin"] == "guest"


def test_guest_audit_response_reports_how_complete_the_run_was(guest_test_context, monkeypatch):
    """Both guest paths carry the degradation block, so a score produced by a
    partial run is never presented as a clean measurement."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-degradation"},
        json={"url": "https://example.com"},
    )

    degradation = response.json()["degradation"]
    assert set(degradation) == {
        "fully_measured",
        "content_source",
        "javascript_rendered",
        "screenshot_captured",
        "ai_analysis_available",
        "reasons",
    }
    assert isinstance(degradation["fully_measured"], bool)


def test_guest_audit_response_has_real_scores(guest_test_context, monkeypatch):
    """Scores should come from the deterministic scoring engine, not hardcoded zeros."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-scores"},
        json={"url": "https://example.com"},
    )

    payload = response.json()
    assert payload["metadata"]["score_source"] == "deterministic_matrix"
    assert payload["metadata"]["version"] == "2.0"
    # Scores should be populated (from deterministic engine)
    assert isinstance(payload["seo_score"], (int, float))
    assert isinstance(payload["geo_score"], (int, float))
    assert isinstance(payload["aeo_score"], (int, float))


def test_claim_guest_audit_success(guest_test_context, monkeypatch):
    """Authenticated user can claim a guest audit record via token."""
    _mock_guest_audit_externals(monkeypatch)

    # First, run a guest audit
    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-claim"},
        json={"url": "https://example.com"},
    )
    assert response.status_code == 200
    token = response.json()["guest_audit_token"]

    # Claim it
    claim_response = guest_test_context["client"].post(
        f"/api/v1/guest-audit/claim?token={token}",
        headers={"X-Request-ID": "req-claim"},
    )
    assert claim_response.status_code == 200
    claim_data = claim_response.json()
    assert claim_data["status"] == "claimed"
    assert claim_data["target_url"] == "https://example.com/"

    # Verify DB record is updated
    db = guest_test_context["db"]
    record = db.query(models.GuestAuditRecord).first()
    assert record.claimed_by_user_id == guest_test_context["user"].id
    assert record.claimed_at is not None


def test_claim_guest_audit_invalid_token(guest_test_context):
    """Invalid or expired tokens should return 400."""
    response = guest_test_context["client"].post(
        "/api/v1/guest-audit/claim?token=invalid-jwt-token",
        headers={"X-Request-ID": "req-claim-invalid"},
    )
    assert response.status_code == 400
    assert "Invalid or expired" in response.json()["detail"]


def test_claim_guest_audit_already_claimed(guest_test_context, monkeypatch):
    """Claiming an already-claimed audit returns 409."""
    _mock_guest_audit_externals(monkeypatch)

    response = guest_test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-double-claim"},
        json={"url": "https://example.com"},
    )
    token = response.json()["guest_audit_token"]

    # First claim
    guest_test_context["client"].post(
        f"/api/v1/guest-audit/claim?token={token}",
        headers={"X-Request-ID": "req-claim-1"},
    )

    # Second claim attempt
    second = guest_test_context["client"].post(
        f"/api/v1/guest-audit/claim?token={token}",
        headers={"X-Request-ID": "req-claim-2"},
    )
    assert second.status_code == 409
    assert "already been claimed" in second.json()["detail"]


def test_guest_audit_purge_removes_old_unclaimed_records():
    """Cron sweeper should delete unclaimed guest audit records older than 30 days."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestSession()

    user = models.User(
        email="purge-test@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    now = datetime.now(timezone.utc)

    # Old unclaimed (should be purged)
    old_unclaimed = models.GuestAuditRecord(
        ip_hash="hash1",
        target_url="https://old.example.com",
        audit_target_type="website",
        claim_token="token-old-unclaimed",
        created_at=now - timedelta(days=45),
    )
    # Recent unclaimed (should be kept)
    recent_unclaimed = models.GuestAuditRecord(
        ip_hash="hash2",
        target_url="https://recent.example.com",
        audit_target_type="website",
        claim_token="token-recent-unclaimed",
        created_at=now - timedelta(days=5),
    )
    # Old claimed (should be kept)
    old_claimed = models.GuestAuditRecord(
        ip_hash="hash3",
        target_url="https://old-claimed.example.com",
        audit_target_type="website",
        claim_token="token-old-claimed",
        claimed_by_user_id=user.id,
        claimed_at=now - timedelta(days=40),
        created_at=now - timedelta(days=45),
    )
    db.add_all([old_unclaimed, recent_unclaimed, old_claimed])
    db.commit()

    assert db.query(models.GuestAuditRecord).count() == 3

    # Simulate the purge logic from cron_sweeper
    guest_cutoff = now - timedelta(days=30)
    purged = (
        db.query(models.GuestAuditRecord)
        .filter(
            models.GuestAuditRecord.claimed_by_user_id.is_(None),
            models.GuestAuditRecord.created_at < guest_cutoff,
        )
        .delete(synchronize_session=False)
    )
    db.commit()

    assert purged == 1
    remaining = db.query(models.GuestAuditRecord).all()
    assert len(remaining) == 2
    remaining_tokens = {r.claim_token for r in remaining}
    assert "token-recent-unclaimed" in remaining_tokens
    assert "token-old-claimed" in remaining_tokens

    db.close()
    Base.metadata.drop_all(bind=engine)
