from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from routers import admin_trial
from routers.api_router import AdminActivateTrialRequest, admin_activate_trial
from services import auth_service, trial_invitation_service, trial_service


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def seed_user(db, **overrides):
    user = models.User(
        **{
            "email": "retirement@example.test",
            "hashed_password": "x",
            "role": "user",
            "credits": 40,
            **overrides,
        }
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def seed_invitation(db, **overrides):
    invitation = models.TrialInvitation(
        **{
            "email": "retirement@example.test",
            "token": "synthetic-retired-invitation",
            "status": "pending",
            "expires_at": datetime.now(timezone.utc) + timedelta(days=14),
            "schema_version": "1",
            **overrides,
        }
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation


def trial_snapshot(user):
    return (
        user.trial_plan,
        user.trial_started_at,
        user.trial_ends_at,
        user.trial_audits_used,
        user.trial_max_audits,
        user.trial_initial_credits,
        user.trial_concierge_completed,
        user.credits,
    )


def test_new_trial_activation_is_retired_without_granting_credits(db) -> None:
    user = seed_user(db)
    before = trial_snapshot(user)

    with pytest.raises(HTTPException) as exc_info:
        trial_service.activate_trial(db, user)

    assert exc_info.value.status_code == 410
    assert trial_snapshot(user) == before


@pytest.mark.parametrize("existing_trial", [False, True])
def test_admin_trial_activation_cannot_create_or_reset_a_trial(db, existing_trial) -> None:
    overrides = {}
    if existing_trial:
        now = datetime.now(timezone.utc)
        overrides = {
            "trial_plan": "plan_agency_trial",
            "trial_started_at": now - timedelta(days=3),
            "trial_ends_at": now + timedelta(days=11),
            "trial_audits_used": 2,
        }
    user = seed_user(db, **overrides)
    before = trial_snapshot(user)

    with pytest.raises(HTTPException) as exc_info:
        admin_activate_trial(
            request=AdminActivateTrialRequest(user_id=user.id),
            admin=SimpleNamespace(role="admin"),
            db=db,
        )

    assert exc_info.value.status_code == 410
    db.refresh(user)
    assert trial_snapshot(user) == before


@pytest.mark.parametrize("action", ["create", "resend", "admin-create", "admin-resend"])
def test_trial_invitation_creation_and_resend_are_retired(db, monkeypatch, action) -> None:
    invitation = seed_invitation(db, status="revoked")
    before = (invitation.status, invitation.token, invitation.expires_at)
    send_email = Mock()
    monkeypatch.setattr(admin_trial, "_send_trial_invitation_email", send_email)
    admin = SimpleNamespace(id=1, email="admin@example.test")

    with pytest.raises(HTTPException) as exc_info:
        if action == "create":
            trial_invitation_service.create_invitation(db, email="new@example.test")
        elif action == "resend":
            trial_invitation_service.resend_invitation(db, invitation.id)
        elif action == "admin-create":
            admin_trial.admin_create_invitation(
                request=admin_trial.CreateInvitationRequest(email="new@example.com"),
                admin=admin,
                db=db,
            )
        else:
            admin_trial.admin_resend_invitation(invitation_id=invitation.id, admin=admin, db=db)

    assert exc_info.value.status_code == 410
    assert db.query(models.TrialInvitation).count() == 1
    db.refresh(invitation)
    assert (invitation.status, invitation.token, invitation.expires_at) == before
    send_email.assert_not_called()


@pytest.mark.parametrize("use_token", [False, True])
def test_pending_legacy_invitation_no_longer_grants_a_trial(db, use_token) -> None:
    user = seed_user(db)
    invitation = seed_invitation(db)
    before = trial_snapshot(user)

    result = trial_invitation_service.apply_pending_invitation_for_user(
        db,
        user=user,
        invitation_token=invitation.token if use_token else None,
    )

    assert result is None
    assert trial_snapshot(user) == before
    assert invitation.status == "pending"
    assert invitation.redeemed_by_user_id is None


@pytest.mark.parametrize(
    "flow", ["password", "password-mismatched-token", "oauth-new", "oauth-link"]
)
def test_signup_and_oauth_succeed_without_redeeming_retired_invitations(
    db, monkeypatch, flow
) -> None:
    invitation = seed_invitation(
        db,
        email="other@example.test"
        if flow == "password-mismatched-token"
        else "retirement@example.test",
    )
    if flow == "oauth-link":
        seed_user(db)
    monkeypatch.setattr(auth_service, "hash_password", lambda _value: "synthetic-hash")
    monkeypatch.setattr(
        auth_service.AuthService, "_generate_oauth_password_hash", lambda _self: "x"
    )
    monkeypatch.setattr(
        auth_service.AuthService, "create_email_token", lambda _self, _email: "fixture-token"
    )
    monkeypatch.setattr(
        auth_service.AuthService, "send_verification_email_if_available", AsyncMock()
    )
    monkeypatch.setattr(auth_service.AuthService, "send_welcome_email_if_available", AsyncMock())
    service = auth_service.AuthService(db)

    if flow.startswith("password"):
        user = asyncio.run(
            service.create_user(
                SimpleNamespace(
                    email="retirement@example.test",
                    password="synthetic-password",
                    name="Fixture Agency",
                    trial_token=invitation.token,
                )
            )
        )
    else:
        user = asyncio.run(
            service.get_or_create_oauth_user(
                provider="google",
                subject="synthetic-retirement-subject",
                email="retirement@example.test",
                provider_email_verified=True,
                trial_token=invitation.token,
            )
        )

    assert user is not None
    assert user.id is not None
    assert user.trial_plan != "plan_agency_trial"
    assert user.trial_started_at is None
    db.refresh(invitation)
    assert invitation.status == "pending"
    assert invitation.redeemed_by_user_id is None


def test_existing_trial_activation_remains_idempotent_and_audit_limits_are_preserved(db) -> None:
    now = datetime.now(timezone.utc)
    user = seed_user(
        db,
        trial_plan="plan_agency_trial",
        trial_started_at=now - timedelta(days=3),
        trial_ends_at=now + timedelta(days=11),
        trial_audits_used=4,
        trial_max_audits=5,
        trial_initial_credits=100,
        trial_concierge_completed=True,
    )
    before = trial_snapshot(user)

    assert trial_service.activate_trial(db, user) is user
    assert trial_snapshot(user) == before
    assert trial_service.resolve_trial_status(user)["trial_active"] is True
    trial_service.enforce_trial_feature(user, feature_key="seo")
    trial_service.enforce_trial_audit_limit(user)
    trial_service.increment_trial_audit_usage(db, user)

    with pytest.raises(HTTPException) as exc_info:
        trial_service.enforce_trial_audit_limit(user)
    assert exc_info.value.status_code == 402
    assert trial_service.resolve_trial_status(user)["limit_reason"] == "audits_exhausted"


def test_existing_trial_expiry_still_transitions_without_losing_wallet_credits(db) -> None:
    now = datetime.now(timezone.utc)
    user = seed_user(
        db,
        credits=80,
        trial_plan="plan_agency_trial",
        trial_started_at=now - timedelta(days=16),
        trial_ends_at=now - timedelta(days=2),
    )

    with pytest.raises(HTTPException) as exc_info:
        trial_service.enforce_trial_audit_limit(user)
    assert exc_info.value.status_code == 402
    assert trial_service.resolve_trial_status(user)["trial_expired"] is True
    assert trial_service.transition_expired_trial_to_explorer(db, user) is True
    assert user.trial_plan == "plan_starter"
    assert user.credits == 80
    assert trial_service.transition_expired_trial_to_explorer(db, user) is False
