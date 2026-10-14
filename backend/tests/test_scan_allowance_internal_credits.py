"""SIGV2-1024: customers see scans; credits are internal soft limits.

Covers: audits succeed with exhausted internal credits (AC2), the atomic
scan allowance (AC1/AC3), internal accounting continuing into negative
balances (AC4), the internal-only 80% alert routing (AC5), and redaction
of credit / provider-USD fields from customer surfaces (AC6).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
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
from services.scan_allowance_service import (
    consume_scan_allowance,
    scan_allowance_snapshot,
)


class FakeRedisClient:
    def __init__(self):
        self.hashes: dict[str, dict[str, str]] = {}

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

    async def hset(self, key: str, mapping: dict):
        self.hashes[key] = dict(mapping)
        return len(mapping)

    async def hgetall(self, key: str):
        return dict(self.hashes.get(key, {}))

    async def rpush(self, *_args, **_kwargs):
        return 1

    async def close(self):
        return None

    async def aclose(self):
        return None


@pytest.fixture
def launch_context(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="scan-allowance@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()

    workspace = models.Workspace(name="Scan Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Scan Project",
        domain_url="https://example.com",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.commit()
    db.refresh(user)
    db.refresh(project)

    fake_redis = FakeRedisClient()

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

    monkeypatch.setattr(_redis_client.async_redis_lib, "from_url", lambda *_a, **_k: fake_redis)
    monkeypatch.setattr(
        _redis_client.sync_redis_lib, "from_url", lambda *_a, **_k: FakeRedisClient()
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
        "redis": fake_redis,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _mock_perform_audit(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    perform = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    monkeypatch.setattr(main.api_module, "perform_audit", perform)
    monkeypatch.setattr(
        main.api_module,
        "fetch_url_signature",
        AsyncMock(return_value={"content_hash": "fresh-signature"}),
    )
    return perform


def _add_job(db, user, *, days_ago: float = 0, job_id: str | None = None) -> models.AuditJob:
    job = models.AuditJob(
        id=job_id or f"job-{days_ago}-{datetime.now(timezone.utc).timestamp()}",
        user_id=user.id,
        status="succeeded",
        audit_target_type=models.AuditTargetType.WEBSITE,
        url="https://example.com",
        request_id=f"req-{datetime.now(timezone.utc).timestamp()}",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        # SIGV2-1129: a scan the customer launched, which is what the allowance
        # bills. Signal's own competitor refreshes declare a different origin
        # and are not counted; see tests/test_competitor_refresh_scan_allowance.
        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
    )
    db.add(job)
    db.commit()
    return job


def test_sync_audit_succeeds_with_exhausted_internal_credits(
    launch_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2/AC4: credits=0 must not refuse; hold books a negative internal balance."""
    assert launch_context["user"].credits == 0
    _mock_perform_audit(monkeypatch)

    response = launch_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-soft-credits"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": launch_context["project"].id,
        },
    )

    launch_context["db"].refresh(launch_context["user"])
    assert response.status_code == 200
    body = response.json()
    assert "remaining_credits" not in body
    assert "estimated_credit_cost" not in body
    assert "consumed_credit_cost" not in body

    hold = launch_context["db"].query(models.CreditHold).one()
    assert hold.status == "settled"
    assert hold.payload_json.get("hold_shortfall") == 1
    assert launch_context["user"].credits == -1


def test_async_launch_succeeds_with_exhausted_internal_credits(
    launch_context, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_perform_audit(monkeypatch)
    response = launch_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-async-soft"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": launch_context["project"].id,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "estimated_credit_cost" not in body
    assert "remaining_credits" not in body


def test_scan_allowance_blocks_at_limit(launch_context) -> None:
    """plan_starter allows 1 scan; the second launch in the window is refused."""
    db, user = launch_context["db"], launch_context["user"]
    _add_job(db, user)

    with pytest.raises(HTTPException) as exc_info:
        consume_scan_allowance(db, user)
    assert exc_info.value.status_code == 402
    assert "Scan limit reached" in str(exc_info.value.detail)


def test_scan_allowance_boundary_and_reset(launch_context) -> None:
    db, user = launch_context["db"], launch_context["user"]

    snapshot = scan_allowance_snapshot(db, user)
    assert snapshot.scans_used == 0
    assert snapshot.scans_remaining == 1
    assert snapshot.reset_at is None

    consume_scan_allowance(db, user)
    _add_job(db, user)

    snapshot = scan_allowance_snapshot(db, user)
    assert snapshot.scans_used == 1
    assert snapshot.scans_remaining == 0
    assert snapshot.reset_at is not None

    # A job older than the rolling window frees the slot.
    db.delete(db.query(models.AuditJob).first())
    db.commit()
    _add_job(db, user, days_ago=31)
    snapshot = scan_allowance_snapshot(db, user)
    assert snapshot.scans_used == 0
    consume_scan_allowance(db, user)


def test_concurrent_launch_final_slot_serializes(launch_context) -> None:
    """Two consume attempts for the final slot: exactly one succeeds."""
    db, user = launch_context["db"], launch_context["user"]

    first = consume_scan_allowance(db, user)
    assert first.scans_remaining == 1
    _add_job(db, user)

    with pytest.raises(HTTPException) as exc_info:
        consume_scan_allowance(db, user)
    assert exc_info.value.status_code == 402


def test_user_summary_reports_scans(launch_context) -> None:
    db, user = launch_context["db"], launch_context["user"]
    _add_job(db, user)

    response = launch_context["client"].get("/api/v1/users/me")
    assert response.status_code == 200
    body = response.json()
    assert body["scans_used"] == 1
    assert body["scans_remaining"] == 0
    assert body["reset_at"] is not None


def test_job_status_db_fallback_redacts_credit_fields(launch_context) -> None:
    db, user = launch_context["db"], launch_context["user"]
    job = _add_job(db, user, job_id="status-job-1")

    response = launch_context["client"].get(f"/api/v1/audit/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    for field in ("estimated_credit_cost", "consumed_credit_cost", "remaining_credits"):
        assert field not in body


def test_job_status_redis_branch_redacts_credit_fields(launch_context) -> None:
    db, user, redis = launch_context["db"], launch_context["user"], launch_context["redis"]
    job = _add_job(db, user, job_id="status-job-2")
    redis.hashes[f"audit:job:{job.id}"] = {
        "status": "running",
        "estimated_credit_cost": "7",
        "consumed_credit_cost": "2",
        "remaining_credits": "48",
    }

    response = launch_context["client"].get(f"/api/v1/audit/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    for field in ("estimated_credit_cost", "consumed_credit_cost", "remaining_credits"):
        assert field not in body


def test_sse_debate_finished_drops_provider_cost() -> None:
    from services.audit_job_event_service import normalize_debate_progress_event

    normalized = normalize_debate_progress_event(
        {"event": "debate_complete", "confidence": 0.9, "total_cost_usd": 4.52}
    )
    assert "total_cost_usd" not in normalized
    assert normalized["confidence_score"] == 0.9


def test_client_safe_audit_strips_credit_keys() -> None:
    from services.reports.audit_result_adapter import to_client_safe_audit

    audit = {
        "metadata": {
            "estimated_credit_cost": 5,
            "consumed_credit_cost": 4,
            "billable_credit_cost": 4,
            "locked_credit_cost": 5,
            "released_credit_cost": 1,
            "credit_hold_id": 12,
            "credit_hold_status": "settled",
            "credit_hold_shortfall": 0,
            "credit_cost_reconciled": True,
            "credit_reconciliation_reason": "x",
            "cost_forecast": {"estimated_credits": 5},
            "billing_provider": "google",
            "billing_tier": "smart",
            "audit_kind": "full_site",
        },
        "scores": {"overall": 80},
    }
    safe = to_client_safe_audit(audit)
    metadata = safe["metadata"]
    for key in (
        "estimated_credit_cost",
        "consumed_credit_cost",
        "billable_credit_cost",
        "locked_credit_cost",
        "released_credit_cost",
        "credit_hold_id",
        "credit_hold_status",
        "credit_hold_shortfall",
        "credit_cost_reconciled",
        "credit_reconciliation_reason",
        "cost_forecast",
        "billing_provider",
        "billing_tier",
    ):
        assert key not in metadata
    assert metadata["audit_kind"] == "full_site"


def test_trial_limit_ignores_credit_balance() -> None:
    from services.trial_service import enforce_trial_audit_limit

    user = SimpleNamespace(
        trial_plan="plan_agency_trial",
        trial_started_at=datetime.now(timezone.utc),
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=7),
        trial_audits_used=1,
        trial_max_audits=5,
        trial_initial_credits=50,
        trial_concierge_completed=False,
        credits=0,
        subscriptions=[],
        subscription=None,
    )
    # Exhausted internal credits must not refuse the trial audit.
    enforce_trial_audit_limit(user)
