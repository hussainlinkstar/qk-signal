"""SIGV2-1132: promotion codes must be redeemable on every checkout we create.

`allow_promotion_codes` appeared nowhere in our own code, only in the vendored
Stripe SDK, so the promotion-code field never rendered and any code we issued
was unredeemable. These tests pin the parameter onto the Stripe call for both
checkout paths, and keep the two paths consistent: a code that works on one
route and silently fails on another cannot be explained to a customer.

They also pin the constraint that makes consistency possible. Stripe rejects a
Checkout Session that carries both `allow_promotion_codes` and `discounts`
("You may only specify one of these parameters"), so no path may pre-apply a
coupon on the session itself.

SIGV2-1128 adds the copy half: no customer-facing billing message may be
denominated in credits.
"""

from __future__ import annotations

import ast
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost:5432/testdb")
os.environ.setdefault("SSM_ENABLED", "0")

import models
from billing import CommitmentTier, Plan
from billing.router import (
    CheckoutSessionRequest,
    CommitmentCheckoutRequest,
    create_checkout_session,
    create_commitment_checkout_session,
)
from database import Base

BACKEND_ROOT = Path(__file__).resolve().parents[1]
BILLING_ROUTER = BACKEND_ROOT / "billing" / "router.py"
COMMITMENT_SERVICE = BACKEND_ROOT / "services" / "credit_commitment_service.py"


class _FakeConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}
    commitment_overage_price_id = "price_commitment_overage"

    def price_id_for(self, plan: Plan, interval: str = "month") -> str:
        return f"price_{plan.value}_{interval}"

    @staticmethod
    def commitment_price_id_for(tier: CommitmentTier | str) -> str:
        value = tier.value if isinstance(tier, CommitmentTier) else str(tier)
        return f"price_commitment_{value}"


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _seed_user(db: Session, *, email: str, plan_type: str | None = None) -> models.User:
    user = models.User(
        email=email,
        hashed_password="x",
        role="user",
        credits=10,
    )
    db.add(user)
    db.flush()
    if plan_type:
        db.add(
            models.Subscription(
                user_id=user.id,
                stripe_customer_id=f"cus_{user.id}",
                stripe_subscription_id=f"sub_{user.id}",
                stripe_mode="test",
                plan_type=plan_type,
                status="active",
            )
        )
    db.commit()
    db.refresh(user)
    return user


def test_subscription_checkout_allows_promotion_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="promo-subscription@example.com")
        attempt = models.BaseCheckoutAttempt(
            id="bca_promo_subscription",
            user_id=user.id,
            stripe_mode="test",
            target_plan=Plan.STANDARD.value,
            billing_interval="month",
            status="customer_created",
            stripe_customer_id="cus_promo_subscription",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(attempt)
        db.commit()
        captured: list[dict[str, object]] = []

        def _create_checkout(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace(
                id="cs_promo_subscription",
                url="https://checkout.stripe.test/promo-subscription",
                status="open",
                mode="subscription",
                customer=kwargs["customer"],
                metadata=kwargs["metadata"],
                client_reference_id=kwargs["client_reference_id"],
                livemode=False,
            )

        monkeypatch.setattr(
            "billing.router.get_billing_config",
            lambda *_args, **_kwargs: _FakeConfig(),
        )
        monkeypatch.setattr(
            "billing.router.ensure_stripe_customer",
            lambda **_kwargs: "cus_promo_subscription",
        )
        monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_checkout)

        result = create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=db,
        )

        assert result["id"] == "cs_promo_subscription"
        assert len(captured) == 1
        assert captured[0]["allow_promotion_codes"] is True
        # Stripe refuses a session that carries both, and the idempotency key is
        # still the per-attempt key, so a retry replays the same parameters.
        assert "discounts" not in captured[0]
        assert captured[0]["idempotency_key"] == "base-checkout:bca_promo_subscription"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_commitment_checkout_allows_promotion_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        user = _seed_user(db, email="promo-commitment@example.com", plan_type="plan_specialist")
        captured: list[dict[str, object]] = []

        def _create_checkout(**kwargs):
            captured.append(kwargs)
            return SimpleNamespace(url="https://checkout.stripe.test/promo-commitment")

        monkeypatch.setattr(
            "billing.router.get_billing_config",
            lambda *_args, **_kwargs: _FakeConfig(),
        )
        monkeypatch.setattr(
            "billing.router.ensure_stripe_customer",
            lambda **_kwargs: "cus_promo_commitment",
        )
        monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_checkout)

        response = create_commitment_checkout_session(
            http_request=None,
            request=CommitmentCheckoutRequest(tier=CommitmentTier.GROWTH),
            user=user,
            db=db,
        )

        assert response["checkout_url"] == "https://checkout.stripe.test/promo-commitment"
        assert len(captured) == 1
        assert captured[0]["allow_promotion_codes"] is True
        assert "discounts" not in captured[0]
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _checkout_session_create_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ast.unparse(node.func)
        if target.endswith("checkout.Session.create"):
            calls.append(node)
    return calls


def test_every_checkout_creation_path_opts_into_promotion_codes() -> None:
    calls = _checkout_session_create_calls(BILLING_ROUTER)
    # Two paths exist today: the subscription checkout and the commitment
    # checkout. A third one must make the same decision deliberately.
    assert len(calls) == 2
    for call in calls:
        keywords = {keyword.arg for keyword in call.keywords}
        assert "allow_promotion_codes" in keywords
        assert "discounts" not in keywords
        allow = next(
            keyword.value for keyword in call.keywords if keyword.arg == "allow_promotion_codes"
        )
        assert isinstance(allow, ast.Constant) and allow.value is True


def _customer_facing_messages(path: Path) -> list[str]:
    """Strings a customer can be shown: `detail=` values and `"message"` values."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    messages: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg in {"detail", "message"} and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str):
                        messages.append(keyword.value.value)
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "message"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)
                ):
                    messages.append(value.value)
        if (
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            messages.append(node.value.value)
    return messages


@pytest.mark.parametrize("path", [BILLING_ROUTER, COMMITMENT_SERVICE])
def test_customer_facing_billing_messages_never_mention_credits(path: Path) -> None:
    messages = _customer_facing_messages(path)
    assert messages, f"{path.name} exposed no customer-facing message to check"
    leaks = [message for message in messages if "credit" in message.lower()]
    assert leaks == [], f"{path.name} leaked credit language: {leaks}"


def test_commitment_status_states_the_cycle_without_a_credit_quantity() -> None:
    """The customer surface reads flags; the credit figures stay internal."""
    from services.credit_commitment_service import serialize_commitment_status

    commitment = SimpleNamespace(
        id=3,
        tier="scale",
        committed_credits=5000,
        rate_per_credit=0.08,
        monthly_fee_usd=400,
        overage_rate=0.1,
        status="active",
        cancel_at_period_end=False,
        current_cycle_start=datetime(2026, 3, 1, tzinfo=timezone.utc),
        current_cycle_end=datetime(2026, 4, 1, tzinfo=timezone.utc),
        pending_tier=None,
        pending_change_effective_at=None,
        usage_cycles=[],
    )
    cycle = SimpleNamespace(
        status="active",
        credits_used=6200,
        committed_credits=5000,
        overage_credits=1200,
        cycle_start=commitment.current_cycle_start,
        cycle_end=commitment.current_cycle_end,
    )

    payload = serialize_commitment_status(commitment, cycle=cycle)

    assert payload is not None
    assert payload["in_overage"] is True
    assert payload["nearing_limit"] is True

    within_commitment = SimpleNamespace(
        status="active",
        credits_used=400,
        committed_credits=5000,
        overage_credits=0,
        cycle_start=commitment.current_cycle_start,
        cycle_end=commitment.current_cycle_end,
    )
    quiet = serialize_commitment_status(commitment, cycle=within_commitment)
    assert quiet is not None
    assert quiet["in_overage"] is False
    assert quiet["nearing_limit"] is False
