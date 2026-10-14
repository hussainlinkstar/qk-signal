from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.credit_hold_service import (
    CREDIT_HOLD_STATUS_EXPIRED,
    CREDIT_HOLD_STATUS_PENDING,
    CREDIT_HOLD_STATUS_REFUNDED,
    CREDIT_HOLD_STATUS_SETTLED,
    acquire_credit_hold,
    expire_stale_holds,
    release_credit_hold,
    settle_credit_hold,
)


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory()


def _cleanup(db: Session) -> None:
    engine = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(db: Session, *, credits: int = 20) -> models.User:
    user = models.User(
        email=f"hold-{credits}@example.com",
        hashed_password="x",
        role="user",
        credits=credits,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_acquire_and_settle_credit_hold_refunds_unused_credits() -> None:
    db = _build_db()
    try:
        user = _seed_user(db, credits=20)

        hold = acquire_credit_hold(
            db,
            user_id=user.id,
            hold_amount=7,
            request_id="audit:req-hold-settle",
            reason_code="audit.main",
            feature_key="audit.main",
            tier_class="fast",
            policy_version="v2",
        )
        db.commit()
        db.refresh(user)

        assert hold.status == CREDIT_HOLD_STATUS_PENDING
        assert user.credits == 13

        settled = settle_credit_hold(
            db,
            request_id="audit:req-hold-settle",
            final_amount=4,
        )
        db.commit()
        db.refresh(user)

        assert settled.status == CREDIT_HOLD_STATUS_SETTLED
        assert settled.final_amount == 4
        assert settled.refunded_amount == 3
        assert user.credits == 16
    finally:
        _cleanup(db)


def test_release_credit_hold_restores_locked_wallet_balance() -> None:
    db = _build_db()
    try:
        user = _seed_user(db, credits=9)

        acquire_credit_hold(
            db,
            user_id=user.id,
            hold_amount=3,
            request_id="audit:req-hold-release",
            reason_code="audit.main",
            feature_key="audit.main",
            tier_class="fast",
            policy_version="v2",
        )
        db.commit()
        db.refresh(user)
        assert user.credits == 6

        released = release_credit_hold(
            db,
            request_id="audit:req-hold-release",
            refund_reason="provider_failure",
        )
        db.commit()
        db.refresh(user)

        assert released.status == CREDIT_HOLD_STATUS_REFUNDED
        assert released.final_amount == 0
        assert released.refunded_amount == 3
        assert user.credits == 9
    finally:
        _cleanup(db)


def test_expire_stale_holds_marks_rows_expired_and_refunds_wallet() -> None:
    db = _build_db()
    try:
        user = _seed_user(db, credits=12)

        hold = acquire_credit_hold(
            db,
            user_id=user.id,
            hold_amount=5,
            request_id="audit:req-hold-expire",
            reason_code="audit.main",
            feature_key="audit.main",
            tier_class="deep",
            policy_version="v2",
        )
        hold.expires_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        db.commit()
        db.refresh(user)
        assert user.credits == 7

        expired_ids = expire_stale_holds(db, reference_time=datetime.now(timezone.utc))
        db.commit()
        db.refresh(user)

        assert expired_ids == [hold.id]
        expired_hold = db.query(models.CreditHold).filter(models.CreditHold.id == hold.id).one()
        assert expired_hold.status == CREDIT_HOLD_STATUS_EXPIRED
        assert expired_hold.refunded_amount == 5
        assert user.credits == 12
    finally:
        _cleanup(db)


def test_settle_credit_hold_collects_full_delta_into_negative_balance() -> None:
    # SIGV2-1024: credits are internal soft limits; the settle applies the full
    # extra charge even when it pushes the internal balance below zero.
    db = _build_db()
    try:
        user = _seed_user(db, credits=5)

        acquire_credit_hold(
            db,
            user_id=user.id,
            hold_amount=4,
            request_id="audit:req-hold-shortfall",
            reason_code="audit.main",
            feature_key="audit.main",
            tier_class="deep",
            policy_version="v2",
        )
        db.commit()
        db.refresh(user)
        assert user.credits == 1

        settled = settle_credit_hold(
            db,
            request_id="audit:req-hold-shortfall",
            final_amount=6,
        )
        db.commit()
        db.refresh(user)

        assert settled.status == CREDIT_HOLD_STATUS_SETTLED
        assert settled.final_amount == 6
        assert settled.refunded_amount == 0
        assert user.credits == -1
    finally:
        _cleanup(db)
