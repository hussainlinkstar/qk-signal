import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

import billing_webhook_worker
import models
from services.credit_commitment_service import report_pending_commitment_overages
from admin import get_current_user as get_current_admin_user
from admin import get_db as get_admin_db
from billing import CommitmentTier
from billing.router import (
    CommitmentCheckoutRequest,
    create_commitment_checkout_session,
)
from database import Base
from main import app
from auth.credits import decrement_credits_atomic


class _FakeCommitmentConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}
    commitment_overage_price_id = "price_commitment_overage"

    @staticmethod
    def commitment_price_id_for(tier: CommitmentTier | str) -> str:
        value = tier.value if isinstance(tier, CommitmentTier) else str(tier)
        return {
            "growth": "price_commitment_growth",
            "scale": "price_commitment_scale",
            "enterprise": "price_commitment_enterprise",
        }[value]


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
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user_with_subscription(
    db: Session,
    *,
    email: str = "agency@example.com",
    credits: int = 5,
    plan_type: str = "plan_specialist",
    status: str = "active",
) -> models.User:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=credits,
        company_name="Signal Forge",
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            stripe_subscription_id=f"sub_plan_{user.id}",
            plan_type=plan_type,
            status=status,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def _commitment_checkout_event(
    *, user_id: int, session_id: str, subscription_id: str
) -> models.StripeEventLog:
    return models.StripeEventLog(
        event_id=f"evt_{session_id}",
        event_type="checkout.session.completed",
        event_created_at=datetime.now(timezone.utc),
        payload={
            "livemode": False,
            "data": {
                "object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "mode": "subscription",
                    "status": "complete",
                    "payment_status": "paid",
                    "currency": "usd",
                    "amount_total": 18000,
                    "customer": f"cus_{user_id}",
                    "subscription": subscription_id,
                    "metadata": {
                        "type": "credit_commitment",
                        "user_id": str(user_id),
                        "tier": "growth",
                        "committed_credits": "2000",
                    },
                }
            },
        },
        processing_status="pending",
    )


def _commitment_invoice_event(
    *,
    user_id: int,
    subscription_id: str,
    invoice_id: str,
    period_start: datetime,
    period_end: datetime,
    event_type: str = "invoice.paid",
) -> models.StripeEventLog:
    return models.StripeEventLog(
        event_id=f"evt_{invoice_id}",
        event_type=event_type,
        event_created_at=datetime.now(timezone.utc),
        payload={
            "livemode": False,
            "data": {
                "object": {
                    "id": invoice_id,
                    "customer": f"cus_{user_id}",
                    "subscription": subscription_id,
                    "status": "paid",
                    "paid": True,
                    "billing_reason": "subscription_cycle",
                    "amount_due": 18000,
                    "amount_paid": 18000,
                    "currency": "usd",
                    "period_start": int(period_start.timestamp()),
                    "period_end": int(period_end.timestamp()),
                    "lines": {
                        "data": [
                            {
                                "price": {"id": "price_commitment_growth"},
                                "quantity": 1,
                                "amount": 18000,
                                "period": {
                                    "start": int(period_start.timestamp()),
                                    "end": int(period_end.timestamp()),
                                },
                            },
                            {
                                "price": {
                                    "id": "price_commitment_overage",
                                    "recurring": {"usage_type": "metered"},
                                },
                                "amount": 0,
                            },
                        ]
                    },
                }
            },
        },
        processing_status="pending",
    )


def _subscription_payload(*, start: datetime, end: datetime) -> dict[str, object]:
    return {
        "id": "sub_commitment_growth",
        "customer": "cus_1",
        "status": "active",
        "cancel_at_period_end": False,
        "current_period_start": int(start.timestamp()),
        "current_period_end": int(end.timestamp()),
        "items": {
            "data": [
                {
                    "id": "si_commitment_growth",
                    "quantity": 1,
                    "price": {"id": "price_commitment_growth"},
                },
                {
                    "id": "si_commitment_overage",
                    "price": {
                        "id": "price_commitment_overage",
                        "recurring": {"usage_type": "metered"},
                    },
                },
            ]
        },
    }


def _build_admin_client(db: Session, admin_user: models.User) -> TestClient:
    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_admin_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = override_get_current_user
    return TestClient(app)


def test_commitment_checkout_rejects_plan_standard_users(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user_with_subscription(db, plan_type="plan_standard")
        monkeypatch.setattr(
            "billing.router.get_billing_config", lambda *_args, **_kwargs: _FakeCommitmentConfig()
        )

        with pytest.raises(HTTPException) as exc_info:
            create_commitment_checkout_session(
                http_request=None,
                request=CommitmentCheckoutRequest(tier=CommitmentTier.GROWTH),
                user=user,
                db=db,
            )

        assert exc_info.value.status_code == 403
        assert "Specialist" in str(exc_info.value.detail)
    finally:
        _cleanup_db(db, engine)


def test_commitment_checkout_creates_fixed_and_metered_line_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user_with_subscription(db, credits=25, plan_type="plan_specialist")
        captured: dict[str, object] = {}

        def _create_session(**kwargs):
            captured.update(kwargs)
            return SimpleNamespace(url="https://checkout.stripe.test/commitment")

        monkeypatch.setattr(
            "billing.router.get_billing_config", lambda *_args, **_kwargs: _FakeCommitmentConfig()
        )
        monkeypatch.setattr(
            "billing.router.ensure_stripe_customer", lambda **_kwargs: "cus_commitment"
        )
        monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_session)

        response = create_commitment_checkout_session(
            http_request=None,
            request=CommitmentCheckoutRequest(tier=CommitmentTier.GROWTH),
            user=user,
            db=db,
        )

        assert response["checkout_url"] == "https://checkout.stripe.test/commitment"
        assert captured["mode"] == "subscription"
        assert captured["line_items"] == [
            {"price": "price_commitment_growth", "quantity": 1},
            {"price": "price_commitment_overage"},
        ]
        assert captured["metadata"]["type"] == "credit_commitment"
    finally:
        _cleanup_db(db, engine)


def test_commitment_checkout_webhook_creates_commitment_and_grants_credits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        monkeypatch.setenv("STRIPE_MODE", "test")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_GROWTH_TEST", "price_commitment_growth")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_SCALE_TEST", "price_commitment_scale")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_ENTERPRISE_TEST", "price_commitment_enterprise")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_OVERAGE_TEST", "price_commitment_overage")
        user = _seed_user_with_subscription(db, credits=15)
        captured_email: dict[str, object] = {}
        cycle_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        cycle_end = cycle_start + timedelta(days=31)

        monkeypatch.setattr(
            billing_webhook_worker.stripe.Subscription,
            "retrieve",
            lambda _subscription_id: _subscription_payload(start=cycle_start, end=cycle_end),
        )
        monkeypatch.setattr(
            "billing_webhook_worker._enqueue_email",
            lambda _db, **kwargs: captured_email.update(kwargs),
        )

        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _commitment_checkout_event(
                    user_id=user.id,
                    session_id="cs_commitment_growth",
                    subscription_id="sub_commitment_growth",
                ),
                prepared_subscription_payload=_subscription_payload(
                    start=cycle_start,
                    end=cycle_end,
                ),
            )
        )

        db.refresh(user)
        commitment = db.query(models.CreditCommitment).one()
        cycle = db.query(models.CommitmentUsageCycle).one()
        adjustment = db.query(models.UserCreditAdjustment).one()
        reason_payload = json.loads(adjustment.reason)

        assert user.credits == 2015
        assert commitment.tier == "growth"
        assert commitment.stripe_mode == "test"
        assert cycle.committed_credits == 2000
        assert reason_payload["kind"] == "commitment_grant"
        assert captured_email["template_key"] == "commitment.activated"
    finally:
        _cleanup_db(db, engine)


def test_commitment_renewal_reports_overage_and_grants_new_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        monkeypatch.setenv("STRIPE_MODE", "test")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_GROWTH_TEST", "price_commitment_growth")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_SCALE_TEST", "price_commitment_scale")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_ENTERPRISE_TEST", "price_commitment_enterprise")
        monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_OVERAGE_TEST", "price_commitment_overage")
        user = _seed_user_with_subscription(db, credits=3000)
        cycle_start = datetime(2026, 3, 1, tzinfo=timezone.utc)
        cycle_end = cycle_start + timedelta(days=31)
        monkeypatch.setattr(
            billing_webhook_worker.stripe.Subscription,
            "retrieve",
            lambda _subscription_id: _subscription_payload(start=cycle_start, end=cycle_end),
        )
        monkeypatch.setattr("billing_webhook_worker._enqueue_email", lambda *_args, **_kwargs: None)
        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _commitment_checkout_event(
                    user_id=user.id,
                    session_id="cs_commitment_growth",
                    subscription_id="sub_commitment_growth",
                ),
                prepared_subscription_payload=_subscription_payload(
                    start=cycle_start,
                    end=cycle_end,
                ),
            )
        )

        assert decrement_credits_atomic(db, user.id, 2500) is True
        db.commit()
        db.refresh(user)

        renewal_start = cycle_end
        renewal_end = renewal_start + timedelta(days=30)
        asyncio.run(
            billing_webhook_worker.handle_event(
                db,
                _commitment_invoice_event(
                    user_id=user.id,
                    subscription_id="sub_commitment_growth",
                    invoice_id="inv_commitment_renewal",
                    period_start=renewal_start,
                    period_end=renewal_end,
                ),
            )
        )

        db.refresh(user)
        cycles = (
            db.query(models.CommitmentUsageCycle)
            .order_by(models.CommitmentUsageCycle.cycle_start.asc())
            .all()
        )
        assert len(cycles) == 2
        assert cycles[0].status == "closed"
        assert cycles[0].overage_credits == 500
        assert cycles[1].status == "active"
        assert cycles[1].committed_credits == 2000
        assert user.credits == 4500
        assert db.query(models.PlanCreditGrant).count() == 0
        command = db.query(models.StripeCommandOutbox).one()
        assert (
            command.idempotency_key
            == f"commitment-overage:{cycles[0].commitment_id}:{cycles[0].id}"
        )
        assert command.payload["subscription_item_id"] == "si_commitment_overage"
        assert command.payload["quantity"] == 500
        assert command.status == "pending"
    finally:
        _cleanup_db(db, engine)


def test_cron_overage_uses_persisted_mode_and_skips_legacy_null(caplog) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user_with_subscription(db, credits=100)
        now = datetime.now(timezone.utc)
        for suffix, stripe_mode in [("live", "live"), ("legacy", None)]:
            commitment = models.CreditCommitment(
                user_id=user.id,
                tier="growth",
                committed_credits=100,
                rate_per_credit=0.1,
                monthly_fee_usd=10,
                overage_rate=0.1,
                stripe_subscription_id=f"sub_{suffix}",
                stripe_mode=stripe_mode,
                stripe_overage_subscription_item_id=f"si_{suffix}",
                status="active",
            )
            db.add(commitment)
            db.flush()
            cycle = models.CommitmentUsageCycle(
                commitment_id=commitment.id,
                user_id=user.id,
                cycle_start=now - timedelta(days=31),
                cycle_end=now - timedelta(days=1),
                committed_credits=100,
                credits_used=120,
                overage_credits=20,
                status="active",
            )
            db.add(cycle)
        db.commit()

        reported = report_pending_commitment_overages(db, now=now)
        db.commit()

        assert len(reported) == 1
        command = db.query(models.StripeCommandOutbox).one()
        assert command.stripe_mode == "live"
        assert command.payload["subscription_item_id"] == "si_live"
        assert "Skipping legacy commitment overage without Stripe mode" in caplog.text
    finally:
        _cleanup_db(db, engine)


def test_admin_commitment_overview_reports_commitment_mrr_and_overage() -> None:
    db, engine = _build_db()
    try:
        admin_user = models.User(
            email="admin@example.com",
            hashed_password="x",
            role="admin",
            credits=10,
            notifications_enabled=True,
        )
        db.add(admin_user)
        db.commit()
        db.refresh(admin_user)

        user = _seed_user_with_subscription(db, email="billing@example.com", credits=100)
        commitment = models.CreditCommitment(
            user_id=user.id,
            tier="scale",
            committed_credits=5000,
            rate_per_credit=0.08,
            monthly_fee_usd=400,
            overage_rate=0.10,
            stripe_subscription_id="sub_commitment_scale",
            stripe_commitment_subscription_item_id="si_scale",
            stripe_overage_subscription_item_id="si_scale_overage",
            status="active",
            current_cycle_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
            current_cycle_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        )
        db.add(commitment)
        db.flush()
        db.add(
            models.CommitmentUsageCycle(
                commitment_id=commitment.id,
                user_id=user.id,
                cycle_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
                cycle_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
                committed_credits=5000,
                credits_used=5200,
                overage_credits=200,
                status="active",
            )
        )
        db.commit()

        client = _build_admin_client(db, admin_user)
        response = client.get("/api/v1/admin/billing/commitments/overview")
        assert response.status_code == 200
        payload = response.json()
        assert payload["active_commitments"] == 1
        assert payload["commitment_mrr_usd"] == 400.0
        assert payload["total_overage_credits"] == 200
    finally:
        _cleanup_db(db, engine)
