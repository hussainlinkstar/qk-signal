"""Tests for trial_service — Explorer plan transition and credit refresh."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from services.trial_service import (
    STARTER_MONTHLY_CREDITS,
    STARTER_PLAN,
    activate_trial,
    enforce_trial_audit_limit,
    enforce_trial_feature,
    has_paid_subscription,
    increment_trial_audit_usage,
    is_explorer_user,
    is_trial_user,
    refresh_explorer_credits,
    resolve_trial_status,
    transition_expired_trial_to_explorer,
)


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session(), engine


def _seed_user(db: Session, **overrides) -> models.User:
    defaults = dict(email="test@example.com", hashed_password="x", role="user", credits=0)
    defaults.update(overrides)
    user = models.User(**defaults)
    db.add(user)
    db.flush()
    return user


def _make_expired_trial_user(db: Session, **overrides) -> models.User:
    """Seed a user whose agency trial expired 2 days ago."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        email="trial@example.com",
        hashed_password="x",
        role="user",
        credits=0,
        trial_plan="plan_agency_trial",
        trial_started_at=now - timedelta(days=16),
        trial_ends_at=now - timedelta(days=2),
        trial_audits_used=0,
    )
    defaults.update(overrides)
    return _seed_user(db, **defaults)


def _make_explorer_user(db: Session, **overrides) -> models.User:
    """Seed an Explorer user with credits refreshed 31 days ago."""
    now = datetime.now(timezone.utc)
    defaults = dict(
        email="plan_starter@example.com",
        hashed_password="x",
        role="user",
        credits=STARTER_MONTHLY_CREDITS,
        trial_plan=STARTER_PLAN,
        explorer_credits_refreshed_at=now - timedelta(days=31),
    )
    defaults.update(overrides)
    return _seed_user(db, **defaults)


# ── activate_trial ────────────────────────────────────────────────────


def test_activate_trial_rejects_new_grants() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        assert user.trial_plan is None
        with pytest.raises(Exception) as exc_info:
            activate_trial(db, user)
        assert exc_info.value.status_code == 410
        assert user.trial_plan is None
        assert user.credits == 0
        assert user.trial_ends_at is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_activate_trial_idempotent() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, trial_plan="plan_agency_trial", credits=50)
        result = activate_trial(db, user)
        assert result.credits == 50  # unchanged
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── is_trial_user / is_explorer_user ─────────────────────────────────


def test_is_trial_user() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, trial_plan="plan_agency_trial")
        assert is_trial_user(user) is True
        assert is_explorer_user(user) is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_is_explorer_user() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, trial_plan=STARTER_PLAN)
        assert is_explorer_user(user) is True
        assert is_trial_user(user) is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_is_neither_trial_nor_explorer() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        assert is_trial_user(user) is False
        assert is_explorer_user(user) is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── resolve_trial_status ─────────────────────────────────────────────


def test_resolve_trial_status_active() -> None:
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _seed_user(
            db,
            trial_plan="plan_agency_trial",
            trial_started_at=now - timedelta(days=3),
            trial_ends_at=now + timedelta(days=11),
            credits=80,
            trial_audits_used=1,
        )
        status = resolve_trial_status(user)
        assert status["is_trial"] is True
        assert status["trial_active"] is True
        assert status["trial_expired"] is False
        assert status["days_remaining"] >= 10
        assert status["credits_remaining"] == 80
        assert status["audits_used"] == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_resolve_trial_status_expired() -> None:
    db, engine = _build_db()
    try:
        user = _make_expired_trial_user(db)
        status = resolve_trial_status(user)
        assert status["is_trial"] is True
        assert status["trial_active"] is False
        assert status["trial_expired"] is True
        assert status["limit_reason"] == "trial_expired"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_resolve_trial_status_non_trial() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        status = resolve_trial_status(user)
        assert status["is_trial"] is False
        assert status["trial_active"] is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_resolve_trial_status_explorer_returns_empty() -> None:
    """Explorer users are NOT plan_agency_trial — resolve_trial_status returns empty."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        status = resolve_trial_status(user)
        assert status["is_trial"] is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── enforce_trial_audit_limit ────────────────────────────────────────


def test_enforce_trial_audit_limit_expired_raises_402() -> None:
    db, engine = _build_db()
    try:
        user = _make_expired_trial_user(db)
        with pytest.raises(Exception) as exc_info:
            enforce_trial_audit_limit(user)
        assert exc_info.value.status_code == 402
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_enforce_trial_audit_limit_audits_exhausted_raises_402() -> None:
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _seed_user(
            db,
            trial_plan="plan_agency_trial",
            trial_started_at=now - timedelta(days=3),
            trial_ends_at=now + timedelta(days=11),
            credits=50,
            trial_audits_used=5,
            trial_max_audits=5,
        )
        with pytest.raises(Exception) as exc_info:
            enforce_trial_audit_limit(user)
        assert exc_info.value.status_code == 402
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_enforce_trial_audit_limit_credits_exhausted_still_allows() -> None:
    # SIGV2-1024: exhausted internal credits must not refuse a trial audit.
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _seed_user(
            db,
            trial_plan="plan_agency_trial",
            trial_started_at=now - timedelta(days=3),
            trial_ends_at=now + timedelta(days=11),
            credits=0,
            trial_audits_used=1,
        )
        enforce_trial_audit_limit(user)
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_enforce_trial_audit_limit_explorer_skips() -> None:
    """Explorer users are NOT plan_agency_trial — limit enforcement skips them."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        enforce_trial_audit_limit(user)  # should NOT raise
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── enforce_trial_feature ────────────────────────────────────────────


def test_enforce_trial_feature_explorer_seo_allowed() -> None:
    """Explorer has seo=True in CAPABILITY_MATRIX, so no 403."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        enforce_trial_feature(user, feature_key="seo")  # should not raise
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_enforce_trial_feature_explorer_gated_raises_403() -> None:
    """Explorer does NOT have has_white_label, so expect 403."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        with pytest.raises(Exception) as exc_info:
            enforce_trial_feature(user, feature_key="has_white_label")
        assert exc_info.value.status_code == 403
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── transition_expired_trial_to_explorer ─────────────────────────────


@pytest.mark.parametrize(
    ("current_credits", "expected_credits"),
    [(0, 12), (5, 12), (12, 12), (500, 500)],
)
def test_transition_expired_trial_preserves_wallet_floor(
    current_credits: int,
    expected_credits: int,
) -> None:
    db, engine = _build_db()
    try:
        user = _make_expired_trial_user(db, credits=current_credits)
        result = transition_expired_trial_to_explorer(db, user)
        assert result is True
        assert user.trial_plan == STARTER_PLAN
        assert user.credits == expected_credits
        assert user.explorer_credits_refreshed_at is not None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_transition_skips_active_trial() -> None:
    """Do not transition if the trial hasn't expired yet."""
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _seed_user(
            db,
            trial_plan="plan_agency_trial",
            trial_started_at=now - timedelta(days=3),
            trial_ends_at=now + timedelta(days=11),
            credits=80,
        )
        result = transition_expired_trial_to_explorer(db, user)
        assert result is False
        assert user.trial_plan == "plan_agency_trial"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_transition_skips_already_explorer() -> None:
    """Idempotent — already-transitioned users are skipped."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db, credits=5)
        result = transition_expired_trial_to_explorer(db, user)
        assert result is False
        assert user.credits == 5  # unchanged
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_transition_skips_paid_subscriber() -> None:
    """Users with an active paid subscription should not be transitioned."""
    db, engine = _build_db()
    try:
        user = _make_expired_trial_user(db)
        sub = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_test",
            plan_type="plan_specialist",
            status="active",
            billing_interval="monthly",
        )
        db.add(sub)
        db.flush()
        result = transition_expired_trial_to_explorer(db, user)
        assert result is False
        assert user.trial_plan == "plan_agency_trial"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_transition_skips_no_trial_ends_at() -> None:
    """Edge case: trial_ends_at is None — skip."""
    db, engine = _build_db()
    try:
        user = _seed_user(db, trial_plan="plan_agency_trial", trial_ends_at=None)
        result = transition_expired_trial_to_explorer(db, user)
        assert result is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── refresh_explorer_credits ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("current_credits", "expected_credits"),
    [(0, 12), (5, 12), (12, 12), (500, 500)],
)
def test_refresh_explorer_credits_preserves_wallet_floor(
    current_credits: int,
    expected_credits: int,
) -> None:
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db, credits=current_credits)
        result = refresh_explorer_credits(db, user)
        assert result is True
        assert user.credits == expected_credits
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_refresh_explorer_credits_too_soon() -> None:
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _make_explorer_user(
            db,
            credits=5,
            explorer_credits_refreshed_at=now - timedelta(days=10),
        )
        result = refresh_explorer_credits(db, user)
        assert result is False
        assert user.credits == 5  # unchanged
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_refresh_explorer_credits_null_refreshed_at() -> None:
    """First refresh — null explorer_credits_refreshed_at sets baseline."""
    db, engine = _build_db()
    try:
        user = _seed_user(
            db,
            trial_plan=STARTER_PLAN,
            credits=3,
            explorer_credits_refreshed_at=None,
        )
        result = refresh_explorer_credits(db, user)
        assert result is True
        assert user.credits == STARTER_MONTHLY_CREDITS
        assert user.explorer_credits_refreshed_at is not None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_refresh_skips_non_explorer() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, trial_plan="plan_agency_trial", credits=50)
        result = refresh_explorer_credits(db, user)
        assert result is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_refresh_skips_paid_subscriber() -> None:
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        sub = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_test",
            plan_type="plan_specialist",
            status="active",
            billing_interval="monthly",
        )
        db.add(sub)
        db.flush()
        result = refresh_explorer_credits(db, user)
        assert result is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── has_paid_subscription ────────────────────────────────────────────


def test_has_paid_subscription_with_active_plan() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        sub = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_test",
            plan_type="plan_specialist",
            status="active",
            billing_interval="monthly",
        )
        db.add(sub)
        db.flush()
        assert has_paid_subscription(user) is True
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_has_paid_subscription_explorer_is_not_paid() -> None:
    """Explorer subscription entry (if one existed) is not considered paid."""
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        sub = models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_test",
            plan_type=STARTER_PLAN,
            status="active",
            billing_interval="monthly",
        )
        db.add(sub)
        db.flush()
        assert has_paid_subscription(user) is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_has_paid_subscription_no_subscription() -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        assert has_paid_subscription(user) is False
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ── increment_trial_audit_usage ──────────────────────────────────────


def test_increment_trial_audit_usage() -> None:
    db, engine = _build_db()
    try:
        now = datetime.now(timezone.utc)
        user = _seed_user(
            db,
            trial_plan="plan_agency_trial",
            trial_started_at=now,
            trial_ends_at=now + timedelta(days=14),
            trial_audits_used=2,
        )
        increment_trial_audit_usage(db, user)
        assert user.trial_audits_used == 3
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_increment_trial_audit_usage_skips_explorer() -> None:
    """Explorer users should not have trial audit usage incremented."""
    db, engine = _build_db()
    try:
        user = _make_explorer_user(db)
        user.trial_audits_used = 0
        increment_trial_audit_usage(db, user)
        assert user.trial_audits_used == 0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
