from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost:5432/testdb")
os.environ.setdefault("SSM_ENABLED", "0")

import billing_webhook_worker
import models
from app.config.plans import get_plan_capabilities
from database import Base


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db: Session, engine: object) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(db: Session, *, credits: int = 5) -> models.User:
    user = models.User(
        email="plan-credits@example.com",
        hashed_password="x",
        role="user",
        credits=credits,
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_plan_credits",
            stripe_subscription_id="sub_plan_credits",
            plan_type="plan_standard",
            status="active",
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _invoice_event(
    *,
    event_id: str,
    invoice_id: str,
    user_id: int,
    price_id: str,
    interval: str = "month",
    event_type: str = "invoice.paid",
    invoice_status: str = "paid",
    paid: bool = True,
    subscription_id: str = "sub_plan_credits",
) -> models.StripeEventLog:
    return models.StripeEventLog(
        event_id=event_id,
        event_type=event_type,
        event_created_at=datetime.now(timezone.utc),
        payload={
            "livemode": False,
            "data": {
                "object": {
                    "id": invoice_id,
                    "customer": "cus_plan_credits",
                    "subscription": subscription_id,
                    "status": invoice_status,
                    "paid": paid,
                    "billing_reason": "subscription_cycle",
                    "amount_due": 9900,
                    "amount_paid": 9900 if paid else 0,
                    "currency": "usd",
                    "period_start": 1_799_000_000,
                    "period_end": 1_800_000_000,
                    "metadata": {"user_id": str(user_id)},
                    "lines": {
                        "data": [
                            {
                                "price": {
                                    "id": price_id,
                                    "recurring": {"interval": interval},
                                }
                            }
                        ]
                    },
                }
            },
        },
        processing_status="pending",
    )


def _configure_prices(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_PRICE_STARTER_TEST", "price_starter_month")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_TEST", "price_standard_month")
    monkeypatch.setenv("STRIPE_PRICE_SPECIALIST_TEST", "price_specialist_month")
    monkeypatch.setenv("STRIPE_PRICE_EXECUTIVE_TEST", "price_executive_month")
    monkeypatch.setenv("STRIPE_PRICE_SPECIALIST_ANNUAL_TEST", "price_specialist_year")


@pytest.mark.parametrize(
    ("price_id", "plan_type"),
    [
        ("price_standard_month", "plan_standard"),
        ("price_specialist_month", "plan_specialist"),
        ("price_executive_month", "plan_executive"),
    ],
)
def test_paid_monthly_invoice_grants_canonical_plan_credits(
    monkeypatch: pytest.MonkeyPatch,
    price_id: str,
    plan_type: str,
) -> None:
    db, engine = _build_db()
    try:
        _configure_prices(monkeypatch)
        monkeypatch.setattr("billing_webhook_worker._enqueue_email", lambda *_args, **_kwargs: None)
        user = _seed_user(db)

        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _invoice_event(
                    event_id=f"evt_{plan_type}",
                    invoice_id=f"in_{plan_type}",
                    user_id=user.id,
                    price_id=price_id,
                ),
            )
        )

        allocation = int(get_plan_capabilities(plan_type)["credits_per_month"])
        db.refresh(user)
        grant = db.execute(select(models.PlanCreditGrant)).scalar_one()
        adjustment = db.execute(select(models.UserCreditAdjustment)).scalar_one()
        reason = json.loads(adjustment.reason)

        assert user.credits == 5 + allocation
        assert grant.stripe_invoice_id == f"in_{plan_type}"
        assert grant.plan_type == plan_type
        assert grant.credits == allocation
        assert grant.interval == "month"
        assert adjustment.delta == allocation
        assert reason == {
            "interval": "month",
            "kind": "plan_invoice_credit_grant",
            "plan_type": plan_type,
            "stripe_invoice_id": f"in_{plan_type}",
        }
    finally:
        _cleanup_db(db, engine)


def test_annual_invoice_grants_twelve_months_at_payment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        _configure_prices(monkeypatch)
        monkeypatch.setattr("billing_webhook_worker._enqueue_email", lambda *_args, **_kwargs: None)
        user = _seed_user(db, credits=100)

        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _invoice_event(
                    event_id="evt_annual_specialist",
                    invoice_id="in_annual_specialist",
                    user_id=user.id,
                    price_id="price_specialist_year",
                    interval="year",
                ),
            )
        )

        monthly = int(get_plan_capabilities("plan_specialist")["credits_per_month"])
        db.refresh(user)
        grant = db.execute(select(models.PlanCreditGrant)).scalar_one()
        assert user.credits == 100 + (monthly * 12)
        assert grant.credits == monthly * 12
        assert grant.interval == "year"
    finally:
        _cleanup_db(db, engine)


def test_same_invoice_with_distinct_stripe_events_grants_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        _configure_prices(monkeypatch)
        monkeypatch.setattr("billing_webhook_worker._enqueue_email", lambda *_args, **_kwargs: None)
        user = _seed_user(db)
        first = _invoice_event(
            event_id="evt_invoice_delivery_1",
            invoice_id="in_delivered_twice",
            user_id=user.id,
            price_id="price_standard_month",
        )
        second = _invoice_event(
            event_id="evt_invoice_delivery_2",
            invoice_id="in_delivered_twice",
            user_id=user.id,
            price_id="price_standard_month",
        )

        asyncio.run(billing_webhook_worker.handle_event(db, first))
        asyncio.run(billing_webhook_worker.handle_event(db, second))

        monthly = int(get_plan_capabilities("plan_standard")["credits_per_month"])
        db.refresh(user)
        assert user.credits == 5 + monthly
        assert len(db.execute(select(models.PlanCreditGrant)).scalars().all()) == 1
        assert len(db.execute(select(models.UserCreditAdjustment)).scalars().all()) == 1
        assert len(db.execute(select(models.BillingPayment)).scalars().all()) == 1
    finally:
        _cleanup_db(db, engine)


@pytest.mark.parametrize(
    ("event_type", "invoice_status", "paid", "price_id"),
    [
        ("invoice.payment_failed", "open", False, "price_standard_month"),
        ("invoice.paid", "open", False, "price_standard_month"),
        ("invoice.paid", "paid", True, "price_starter_month"),
        ("invoice.paid", "paid", True, "price_unknown"),
    ],
)
def test_non_paid_or_ineligible_plan_invoice_does_not_grant(
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    invoice_status: str,
    paid: bool,
    price_id: str,
) -> None:
    db, engine = _build_db()
    try:
        _configure_prices(monkeypatch)
        monkeypatch.setattr("billing_webhook_worker._enqueue_email", lambda *_args, **_kwargs: None)
        user = _seed_user(db)

        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _invoice_event(
                    event_id=f"evt_{event_type}_{price_id}",
                    invoice_id=f"in_{event_type}_{price_id}",
                    user_id=user.id,
                    price_id=price_id,
                    event_type=event_type,
                    invoice_status=invoice_status,
                    paid=paid,
                ),
            )
        )

        db.refresh(user)
        assert user.credits == 5
        assert db.execute(select(models.PlanCreditGrant)).first() is None
        assert db.execute(select(models.UserCreditAdjustment)).first() is None
    finally:
        _cleanup_db(db, engine)
