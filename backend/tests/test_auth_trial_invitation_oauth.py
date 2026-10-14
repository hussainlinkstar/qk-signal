from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["SSM_ENABLED"] = "0"

from database import Base  # noqa: E402
import models  # noqa: E402
from services.auth_service import AuthService  # noqa: E402


def _build_session_factory() -> sessionmaker:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session


def test_oauth_sign_in_truncates_an_overlong_provider_name_and_still_succeeds() -> None:
    """A provider display name longer than the company-name cap must be capped,
    never rejected: a sign-in cannot fail over a cosmetic field."""
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        user = asyncio.run(
            AuthService(db).get_or_create_oauth_user(
                provider="google",
                subject="google-subject-overlong",
                email="overlong-oauth@example.com",
                name="X" * 300,
                provider_email_verified=True,
            )
        )

        assert user.id is not None
        assert user.company_name == "X" * 120
    finally:
        db.close()


def test_oauth_sign_in_stores_none_for_a_blank_provider_name() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        user = asyncio.run(
            AuthService(db).get_or_create_oauth_user(
                provider="google",
                subject="google-subject-blank",
                email="blank-oauth@example.com",
                name="   ",
                provider_email_verified=True,
            )
        )

        assert user.id is not None
        assert user.company_name is None
    finally:
        db.close()


def test_oauth_sign_in_never_overwrites_an_existing_company_name() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        existing = models.User(
            email="named-oauth@example.com",
            hashed_password="unused",
            auth_provider="google",
            provider_subject="google-subject-named",
            external_id="google-subject-named",
            company_name="User Set Name",
            email_verified=True,
        )
        db.add(existing)
        db.commit()

        user = asyncio.run(
            AuthService(db).get_or_create_oauth_user(
                provider="google",
                subject="google-subject-named",
                email="named-oauth@example.com",
                name="Provider Supplied Name",
                provider_email_verified=True,
            )
        )

        assert user.id == existing.id
        assert user.company_name == "User Set Name"
    finally:
        db.close()


def test_oauth_user_ignores_matching_retired_trial_invitation() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        invitation = models.TrialInvitation(
            email="invitee@example.com",
            token="trial-token",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            schema_version="1",
        )
        db.add(invitation)
        db.commit()

        user = asyncio.run(
            AuthService(db).get_or_create_oauth_user(
                provider="google",
                subject="google-subject-1",
                email="invitee@example.com",
                name="Invited Agency",
                provider_email_verified=True,
                trial_token="trial-token",
            )
        )
        db.refresh(user)
        db.refresh(invitation)

        assert user.auth_provider == "google"
        assert user.trial_plan is None
        assert user.trial_started_at is None
        assert invitation.status == "pending"
        assert invitation.redeemed_by_user_id is None
    finally:
        db.close()


def test_oauth_linking_existing_user_ignores_pending_trial_invitation_by_email() -> None:
    session_factory = _build_session_factory()
    db = session_factory()
    try:
        user = models.User(
            email="existing@example.com",
            hashed_password="hashed",
            unsubscribe_token="unsubscribe-token",
        )
        db.add(user)
        db.flush()

        invitation = models.TrialInvitation(
            email="existing@example.com",
            token="existing-trial-token",
            status="pending",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
            schema_version="1",
        )
        db.add(invitation)
        db.commit()

        linked_user = asyncio.run(
            AuthService(db).get_or_create_oauth_user(
                provider="microsoft",
                subject="microsoft-subject-1",
                email="existing@example.com",
                name="Existing Account",
                provider_email_verified=True,
            )
        )
        db.refresh(linked_user)
        db.refresh(invitation)

        assert linked_user.id == user.id
        assert linked_user.auth_provider == "microsoft"
        assert linked_user.provider_subject == "microsoft-subject-1"
        assert linked_user.trial_plan is None
        assert invitation.status == "pending"
        assert invitation.redeemed_by_user_id is None
    finally:
        db.close()
