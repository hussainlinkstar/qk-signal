from datetime import datetime, timedelta, timezone

import models
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from admin import get_db
from auth.token_verifier import get_current_staff_user
from database import Base
from main import app


def _build_client_with_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    admin_user = models.User(
        email="admin-costs@example.com",
        hashed_password="x",
        role="admin",
        credits=100,
        notifications_enabled=True,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_get_current_user
    return TestClient(app), db, engine


def _cleanup(client: TestClient, db, engine) -> None:
    client.close()
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def _stub_fx_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(
        "admin._get_admin_ai_cost_fx_snapshot",
        lambda _db: {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "pricing_currency": "USD",
            "billing_currency": "EUR",
            "usd_per_usd": "1.10",
            "eur_per_usd": "0.90909091",
            "effective_date": "2026-03-12",
            "source": "ecb_reference",
            "status": "ok",
            "fetched_at": "2026-03-12T09:00:00+00:00",
        },
    )


def _seed_cost_audits(db) -> dict[str, str]:
    deep_user = models.User(
        email="deep-judge@example.com",
        hashed_password="x",
        role="user",
        credits=20,
        notifications_enabled=True,
    )
    smart_user = models.User(
        email="smart-legacy@example.com",
        hashed_password="x",
        role="user",
        credits=20,
        notifications_enabled=True,
    )
    fast_user = models.User(
        email="fast-user@example.com",
        hashed_password="x",
        role="user",
        credits=20,
        notifications_enabled=True,
    )
    db.add_all([deep_user, smart_user, fast_user])
    db.commit()
    for user in (deep_user, smart_user, fast_user):
        db.refresh(user)

    deep_workspace = models.Workspace(name="High Confidence Workspace", owner_id=deep_user.id)
    smart_workspace = models.Workspace(name="Smart Legacy Workspace", owner_id=smart_user.id)
    fast_workspace = models.Workspace(name="Fast Workspace", owner_id=fast_user.id)
    db.add_all([deep_workspace, smart_workspace, fast_workspace])
    db.commit()
    for workspace in (deep_workspace, smart_workspace, fast_workspace):
        db.refresh(workspace)

    deep_project = models.Project(
        name="High Confidence Project",
        domain_url="https://deep.example.com",
        workspace_id=deep_workspace.id,
    )
    smart_project = models.Project(
        name="Smart Legacy Project",
        domain_url="https://smart.example.com",
        workspace_id=smart_workspace.id,
    )
    fast_project = models.Project(
        name="Fast Project",
        domain_url="https://fast.example.com",
        workspace_id=fast_workspace.id,
    )
    db.add_all([deep_project, smart_project, fast_project])
    db.commit()
    for project in (deep_project, smart_project, fast_project):
        db.refresh(project)

    # Seeds must satisfy two windows at once: audit.created_at >= month_start
    # (the summary's current-month filter) and created_at >= now - 30 days (the
    # daily/by-model/by-user window endpoints). now minus day-sized offsets
    # lands in the previous month on the 1st-3rd; month_start itself lands
    # outside the 30-day window on a month's last day. max() of the two bounds
    # stays inside both on every date, including one minute past midnight on
    # the 1st (offsets are seconds).
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    def _this_month(seconds_ago: int = 0) -> datetime:
        return max(month_start, now - timedelta(seconds=seconds_ago))

    db.add_all(
        [
            models.Audit(
                user_id=deep_user.id,
                project_id=deep_project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                request_id="req-deep-1",
                url="https://deep.example.com",
                geo_score=84,
                seo_score=82,
                aeo_score=88,
                created_at=_this_month(2),
                full_report={
                    "metadata": {
                        "model": "gpt-4.1",
                        "token_usage": {"total": 3000},
                        "tier": "deep_judgment",
                        "requested_tier": "deep_judgment",
                        "ai_generation": {"profile": "high_confidence"},
                    }
                },
            ),
            models.Audit(
                user_id=smart_user.id,
                project_id=smart_project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                request_id="req-smart-1",
                url="https://smart.example.com",
                geo_score=73,
                seo_score=75,
                aeo_score=71,
                created_at=_this_month(1),
                full_report={
                    "metadata": {
                        "model": "gemini-2.5-pro",
                        "estimated_tokens": 2000,
                        "tier": "smart",
                    }
                },
            ),
            models.Audit(
                user_id=fast_user.id,
                project_id=fast_project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                request_id="req-fast-1",
                url="https://fast.example.com",
                geo_score=61,
                seo_score=64,
                aeo_score=62,
                created_at=_this_month(0),
                full_report={
                    "metadata": {
                        "model": "gpt-4.1-mini",
                        "estimated_tokens": 1000,
                        "tier": "fast",
                        "requested_tier": "fast",
                    }
                },
            ),
        ]
    )
    db.commit()

    return {
        "deep_email": deep_user.email,
        "smart_email": smart_user.email,
        "deep_workspace": deep_workspace.name,
        "deep_request_id": "req-deep-1",
    }


def test_admin_cost_endpoints_filter_high_confidence_requested_tier(monkeypatch) -> None:
    client, db, engine = _build_client_with_db()
    try:
        _stub_fx_snapshot(monkeypatch)
        seeded = _seed_cost_audits(db)

        params = {"requested_tier": "deep_judgment", "debate_profile": "high_confidence"}

        summary = client.get("/api/v1/admin/costs/summary", params=params)
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["audit_count_month"] == 1
        assert summary_payload["top_model"] == "gpt-4.1"

        daily = client.get("/api/v1/admin/costs/daily", params={"days": 30, **params})
        assert daily.status_code == 200
        daily_payload = daily.json()
        assert sum(entry["audit_count"] for entry in daily_payload["series"]) == 1
        assert daily_payload["summary"]["total_cost"] > 0

        by_model = client.get("/api/v1/admin/costs/by-model", params={"window_days": 30, **params})
        assert by_model.status_code == 200
        by_model_payload = by_model.json()
        assert len(by_model_payload["models"]) == 1
        assert by_model_payload["models"][0]["model"] == "gpt-4.1"
        assert by_model_payload["models"][0]["audits"] == 1

        by_workspace = client.get(
            "/api/v1/admin/costs/by-workspace", params={"window_days": 30, **params}
        )
        assert by_workspace.status_code == 200
        by_workspace_payload = by_workspace.json()
        assert len(by_workspace_payload["workspaces"]) == 1
        assert by_workspace_payload["workspaces"][0]["workspace_name"] == seeded["deep_workspace"]
        assert by_workspace_payload["workspaces"][0]["audits"] == 1

        by_user = client.get("/api/v1/admin/costs/by-user", params={"window_days": 30, **params})
        assert by_user.status_code == 200
        by_user_payload = by_user.json()
        assert len(by_user_payload["users"]) == 1
        assert by_user_payload["users"][0]["email"] == seeded["deep_email"]
        assert by_user_payload["users"][0]["audits"] == 1
    finally:
        _cleanup(client, db, engine)


def test_admin_cost_requested_tier_filter_falls_back_to_legacy_tier_metadata(monkeypatch) -> None:
    client, db, engine = _build_client_with_db()
    try:
        _stub_fx_snapshot(monkeypatch)
        seeded = _seed_cost_audits(db)

        summary = client.get("/api/v1/admin/costs/summary", params={"requested_tier": "smart"})
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["audit_count_month"] == 1
        assert summary_payload["top_model"] == "gemini-2.5-pro"

        by_model = client.get(
            "/api/v1/admin/costs/by-model", params={"window_days": 30, "requested_tier": "deep"}
        )
        assert by_model.status_code == 200
        by_model_payload = by_model.json()
        assert len(by_model_payload["models"]) == 1
        assert by_model_payload["models"][0]["model"] == "gemini-2.5-pro"

        by_user = client.get(
            "/api/v1/admin/costs/by-user", params={"window_days": 30, "requested_tier": "smart"}
        )
        assert by_user.status_code == 200
        by_user_payload = by_user.json()
        assert len(by_user_payload["users"]) == 1
        assert by_user_payload["users"][0]["email"] == seeded["smart_email"]
    finally:
        _cleanup(client, db, engine)


def test_admin_cost_endpoints_use_canonical_usd_and_fx_reference(monkeypatch) -> None:
    client, db, engine = _build_client_with_db()
    try:
        _stub_fx_snapshot(monkeypatch)
        _seed_cost_audits(db)

        summary = client.get(
            "/api/v1/admin/costs/summary", params={"requested_tier": "deep_judgment"}
        )
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["currency"] == "USD"
        assert summary_payload["currency_policy"]["display_currency"] == "USD"
        assert summary_payload["current_month_cost"] > 0
        assert summary_payload["top_model_cost"] > 0

        daily = client.get(
            "/api/v1/admin/costs/daily", params={"days": 30, "requested_tier": "deep_judgment"}
        )
        assert daily.status_code == 200
        daily_payload = daily.json()
        matching_entries = [entry for entry in daily_payload["series"] if entry["audit_count"] == 1]
        assert len(matching_entries) == 1
        assert matching_entries[0]["total_cost"] > 0
    finally:
        _cleanup(client, db, engine)


def test_admin_cost_endpoints_prefer_ledger_usd_over_legacy_token_estimate(monkeypatch) -> None:
    client, db, engine = _build_client_with_db()
    try:
        _stub_fx_snapshot(monkeypatch)
        seeded = _seed_cost_audits(db)
        db.add(
            models.AIEconomicsLedgerEntry(
                policy_version="v2",
                feature_key="audit.main",
                tier_class="deep",
                provider="anthropic",
                model="claude-opus-4.6",
                total_tokens=7200,
                input_tokens=3600,
                output_tokens=3600,
                token_cost_usd=1.545455,
                infra_alloc_usd=0,
                orchestration_usd=0,
                retry_risk_usd=0,
                real_cost_usd=1.545455,
                credits_charged=4,
                credit_unit_value_usd=0.1,
                implied_revenue_usd=0.4,
                margin_usd=-1.145455,
                request_id=seeded["deep_request_id"],
                payload_json={
                    "token_cost_usd": 1.7,
                    "ai_cost_fx": {
                        "usd_per_usd": 1.10,
                        "eur_per_usd": 0.90909091,
                        "effective_date": "2026-03-12",
                        "source": "ecb_reference",
                        "status": "ok",
                        "fetched_at": "2026-03-12T09:00:00+00:00",
                    },
                    "actual_steps": [
                        {
                            "model": "claude-opus-4.6",
                            "input_tokens": 3600,
                            "output_tokens": 3600,
                            "actual_cost_usd": 1.7,
                        }
                    ],
                },
            )
        )
        db.commit()

        summary = client.get(
            "/api/v1/admin/costs/summary", params={"requested_tier": "deep_judgment"}
        )
        assert summary.status_code == 200
        summary_payload = summary.json()
        assert summary_payload["current_month_cost"] == 1.7
        assert summary_payload["top_model"] == "claude-opus-4.6"
        assert summary_payload["top_model_cost"] == 1.7

        by_model = client.get(
            "/api/v1/admin/costs/by-model",
            params={"window_days": 30, "requested_tier": "deep_judgment"},
        )
        assert by_model.status_code == 200
        by_model_payload = by_model.json()
        assert by_model_payload["models"][0]["model"] == "claude-opus-4.6"
        assert by_model_payload["models"][0]["cost"] == 1.7

        token_usage = client.get("/api/v1/admin/token-usage", params={"window_days": 30})
        assert token_usage.status_code == 200
        token_usage_payload = token_usage.json()
        claude_entry = next(
            entry for entry in token_usage_payload["entries"] if entry["model"] == "claude-opus-4.6"
        )
        assert claude_entry["cost"] == 1.7
    finally:
        _cleanup(client, db, engine)
