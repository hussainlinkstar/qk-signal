import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
import queue_worker
from database import Base
from job_models import AuditJobPayload


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _build_job(*, user_id: int) -> AuditJobPayload:
    return AuditJobPayload(
        job_id="job-reconcile-1",
        request_id="req-reconcile-1",
        user_id=user_id,
        url="https://northwind.example",
        provider="google",
        tier="fast",
        charge_credits=False,
        scheduled_audit_id=77,
        estimated_credit_cost=5,
    )


def test_precharged_credit_reconciliation_refund_is_idempotent(db_session):
    user = models.User(email="reconcile-refund@example.com", hashed_password="x", credits=15)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    job = _build_job(user_id=user.id)

    consumed_cost, applied = queue_worker._reconcile_precharged_audit_credits(
        db=db_session,
        job=job,
        user_id=user.id,
        estimated_credit_cost=5,
        billable_credit_cost=3,
        billed_provider="google",
        billed_tier="fast",
    )
    assert consumed_cost == 3
    assert applied is True
    db_session.commit()
    db_session.refresh(user)
    assert int(user.credits or 0) == 17

    consumed_cost_retry, applied_retry = queue_worker._reconcile_precharged_audit_credits(
        db=db_session,
        job=job,
        user_id=user.id,
        estimated_credit_cost=5,
        billable_credit_cost=3,
        billed_provider="google",
        billed_tier="fast",
    )
    assert consumed_cost_retry == 3
    assert applied_retry is False
    db_session.commit()
    db_session.refresh(user)
    assert int(user.credits or 0) == 17

    adjustment_rows = (
        db_session.query(models.UserCreditAdjustment)
        .filter(
            models.UserCreditAdjustment.user_id == user.id,
            models.UserCreditAdjustment.reason.contains("audit_credit_reconciliation"),
        )
        .all()
    )
    assert len(adjustment_rows) == 1
    assert adjustment_rows[0].delta == 2


def test_precharged_credit_reconciliation_charges_downward_delta(db_session):
    user = models.User(email="reconcile-charge@example.com", hashed_password="x", credits=6)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    job = _build_job(user_id=user.id)
    consumed_cost, applied = queue_worker._reconcile_precharged_audit_credits(
        db=db_session,
        job=job,
        user_id=user.id,
        estimated_credit_cost=2,
        billable_credit_cost=4,
        billed_provider="openai",
        billed_tier="smart",
    )
    assert consumed_cost == 4
    assert applied is True
    db_session.commit()
    db_session.refresh(user)
    assert int(user.credits or 0) == 4

    adjustment_row = (
        db_session.query(models.UserCreditAdjustment)
        .filter(
            models.UserCreditAdjustment.user_id == user.id,
            models.UserCreditAdjustment.reason.contains("audit_credit_reconciliation"),
        )
        .first()
    )
    assert adjustment_row is not None
    assert adjustment_row.delta == -2
