from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["SSM_ENABLED"] = "0"

from database import Base, get_db as database_get_db  # noqa: E402
import middleware.maintenance as maintenance  # noqa: E402
import models  # noqa: E402
from main import app, get_db as api_get_db  # noqa: E402
from services import email_service  # noqa: E402
from services.trial_feedback_service import (  # noqa: E402
    create_feedback_request_for_user,
    queue_feedback_requests_for_completed_trials,
)
from auth.token_verifier import get_current_staff_user  # noqa: E402


def _build_client() -> tuple[TestClient, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database_get_db] = override_get_db
    app.dependency_overrides[api_get_db] = override_get_db
    maintenance._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }
    return TestClient(app), testing_session


def _cleanup_overrides() -> None:
    app.dependency_overrides.clear()


def test_queue_feedback_requests_for_completed_trials_creates_request_and_email(
    monkeypatch,
) -> None:
    client, session_factory = _build_client()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    # EmailService.__init__ resolves MAIL_ENABLED via
    # core.db_settings_resolver.resolve_db_setting first, which (through
    # configuration_service's env-default fallback) can read a cached/raw
    # env-derived settings snapshot instead of the settings monkeypatch
    # above when no DB override row exists yet. Force "no DB override" so
    # the fallback to `settings.MAIL_ENABLED` actually applies.
    monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *_a, **_kw: None)
    db = session_factory()
    try:
        admin_user = models.User(
            email="admin@example.com",
            hashed_password="hashed",
            unsubscribe_token="admin-unsub",
            role="admin",
        )
        expired_user = models.User(
            email="trial-user@example.com",
            hashed_password="hashed",
            unsubscribe_token="trial-unsub",
            company_name="Trial User",
            trial_plan="plan_agency_trial",
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=20),
            trial_ends_at=datetime.now(timezone.utc) - timedelta(days=2),
            trial_audits_used=2,
            trial_max_audits=5,
            trial_initial_credits=100,
            credits=75,
        )
        db.add(admin_user)
        db.add(expired_user)
        db.flush()

        invitation = models.TrialInvitation(
            email=expired_user.email,
            token="redeemed-trial-token",
            status="redeemed",
            invited_by_user_id=admin_user.id,
            redeemed_by_user_id=expired_user.id,
            redeemed_at=datetime.now(timezone.utc) - timedelta(days=19),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
            schema_version="1",
        )
        db.add(invitation)
        db.commit()

        summary = queue_feedback_requests_for_completed_trials(
            db,
            now=datetime.now(timezone.utc),
        )
        db.commit()

        feedback_request = db.query(models.TrialFeedbackRequest).one()
        outbox = (
            db.query(models.EmailOutbox)
            .filter(
                models.EmailOutbox.correlation_id == f"trial.feedback_request:{feedback_request.id}"
            )
            .one()
        )

        assert summary["eligible_users"] == 1
        assert summary["created_requests"] == 1
        assert summary["queued_emails"] == 1
        assert feedback_request.requested_by_user_id == admin_user.id
        assert outbox.template_key == "trial.feedback_request"
        assert "Share Feedback" in outbox.html_body
    finally:
        db.close()
        client.close()
        _cleanup_overrides()


def test_trial_feedback_public_endpoints_allow_submit(monkeypatch) -> None:
    client, session_factory = _build_client()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    db = session_factory()
    try:
        user = models.User(
            email="feedback@example.com",
            hashed_password="hashed",
            unsubscribe_token="feedback-unsub",
            company_name="Feedback Team",
            trial_plan="plan_agency_trial",
            trial_started_at=datetime.now(timezone.utc) - timedelta(days=16),
            trial_ends_at=datetime.now(timezone.utc) - timedelta(days=1),
            trial_audits_used=5,
            trial_max_audits=5,
            trial_initial_credits=100,
            credits=0,
        )
        db.add(user)
        db.commit()

        feedback_request, _created = create_feedback_request_for_user(
            db,
            user=user,
            now=datetime.now(timezone.utc),
        )
        db.commit()

        get_response = client.get(
            f"/api/v1/trial-feedback/{feedback_request.token}",
            headers={"X-Request-ID": "req-feedback-get"},
        )
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "pending"
        assert get_response.json()["recipient_email"] == "feedback@example.com"

        submit_response = client.post(
            f"/api/v1/trial-feedback/{feedback_request.token}/submit",
            headers={"X-Request-ID": "req-feedback-submit"},
            json={
                "overall_rating": 4,
                "would_recommend": "yes",
                "what_worked_well": "The audit output was useful.",
                "what_was_missing": "Need more workflow automation.",
                "improvement_suggestions": "Make the setup flow faster.",
            },
        )
        assert submit_response.status_code == 200
        assert submit_response.json()["status"] == "submitted"

        second_submit_response = client.post(
            f"/api/v1/trial-feedback/{feedback_request.token}/submit",
            headers={"X-Request-ID": "req-feedback-submit-again"},
            json={
                "overall_rating": 4,
                "would_recommend": "yes",
            },
        )
        assert second_submit_response.status_code == 409

        db.refresh(feedback_request)
        assert feedback_request.status == "submitted"
        assert feedback_request.overall_rating == 4
        assert feedback_request.would_recommend == "yes"
    finally:
        db.close()
        client.close()
        _cleanup_overrides()


# ---------------------------------------------------------------------------
# Admin feedback endpoints
# ---------------------------------------------------------------------------


def _build_admin_client() -> tuple[TestClient, sessionmaker, models.User]:
    """Build test client with admin auth override."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    admin_user = models.User(
        email="admin@example.com",
        hashed_password="hashed",
        unsubscribe_token="admin-unsub-token",
        role="admin",
        credits=100,
    )
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)
    db.close()

    def override_get_db():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    def override_admin():
        session = testing_session()
        return session.query(models.User).filter(models.User.email == "admin@example.com").first()

    app.dependency_overrides[database_get_db] = override_get_db
    app.dependency_overrides[api_get_db] = override_get_db
    app.dependency_overrides[get_current_staff_user] = override_admin
    maintenance._get_maintenance_state = lambda: {
        "active": False,
        "message": "",
        "allowed_ips": [],
    }
    return TestClient(app), testing_session, admin_user


def _seed_feedback_data(session_factory: sessionmaker) -> list[int]:
    """Seed trial users and feedback requests, return list of feedback_request ids."""
    db = session_factory()
    now = datetime.now(timezone.utc)
    ids = []
    for i, (status, rating, recommend) in enumerate(
        [
            ("submitted", 5, "yes"),
            ("submitted", 3, "maybe"),
            ("pending", None, None),
            ("expired", None, None),
        ]
    ):
        user = models.User(
            email=f"trial-fb-{i}@example.com",
            hashed_password="hashed",
            unsubscribe_token=f"unsub-fb-{i}",
            company_name=f"Feedback User {i}",
            trial_plan="plan_agency_trial",
            trial_started_at=now - timedelta(days=30),
            trial_ends_at=now - timedelta(days=5),
            trial_audits_used=2,
            trial_max_audits=5,
            trial_initial_credits=100,
            credits=50,
        )
        db.add(user)
        db.flush()

        fr = models.TrialFeedbackRequest(
            user_id=user.id,
            token=f"fb-token-{i}",
            status=status,
            trigger_reason="trial_expired",
            trial_started_at_snapshot=now - timedelta(days=30),
            trial_ended_at_snapshot=now - timedelta(days=5),
            requested_at=now - timedelta(days=4),
            expires_at=now + timedelta(days=41),
            updated_at=now,
            schema_version="1",
        )
        if rating is not None:
            fr.overall_rating = rating
            fr.would_recommend = recommend
            fr.what_worked_well = f"Good stuff {i}"
            fr.what_was_missing = f"Missing stuff {i}"
            fr.improvement_suggestions = f"Suggestion {i}"
            fr.submitted_at = now - timedelta(days=2)
        db.add(fr)
        db.flush()
        ids.append(fr.id)

    db.commit()
    db.close()
    return ids


def test_admin_list_feedback_returns_all(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    client, session_factory, _ = _build_admin_client()
    try:
        _seed_feedback_data(session_factory)
        res = client.get("/api/v1/admin/trial/feedback")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 4
        assert len(data["items"]) == 4
        assert all("recipient_email" in item for item in data["items"])
    finally:
        client.close()
        _cleanup_overrides()


def test_admin_list_feedback_filters_by_status(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    client, session_factory, _ = _build_admin_client()
    try:
        _seed_feedback_data(session_factory)
        res = client.get("/api/v1/admin/trial/feedback?status=submitted")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        assert all(item["status"] == "submitted" for item in data["items"])
    finally:
        client.close()
        _cleanup_overrides()


def test_admin_feedback_stats(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    client, session_factory, _ = _build_admin_client()
    try:
        _seed_feedback_data(session_factory)
        res = client.get("/api/v1/admin/trial/feedback/stats")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 4
        assert data["submitted"] == 2
        assert data["pending"] == 1
        assert data["expired"] == 1
        assert data["avg_rating"] == 4.0  # (5+3)/2
        assert data["recommend_yes"] == 1
        assert data["recommend_maybe"] == 1
        assert data["recommend_no"] == 0
        assert data["response_rate_pct"] == 50.0
    finally:
        client.close()
        _cleanup_overrides()


def test_admin_feedback_detail(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    client, session_factory, _ = _build_admin_client()
    try:
        ids = _seed_feedback_data(session_factory)
        res = client.get(f"/api/v1/admin/trial/feedback/{ids[0]}")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "submitted"
        assert data["overall_rating"] == 5
        assert data["would_recommend"] == "yes"
        assert data["what_worked_well"] == "Good stuff 0"
    finally:
        client.close()
        _cleanup_overrides()


def test_admin_feedback_detail_not_found(monkeypatch) -> None:
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    client, _, _ = _build_admin_client()
    try:
        res = client.get("/api/v1/admin/trial/feedback/99999")
        assert res.status_code == 404
    finally:
        client.close()
        _cleanup_overrides()
