import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import stripe
from fastapi import HTTPException

sys.path.append(str(Path(__file__).resolve().parents[1]))

from billing import Plan
from billing.router import (
    CheckoutSessionRequest,
    create_checkout_session,
    is_missing_customer_error,
)


class _FakeDb:
    def __init__(self) -> None:
        self.commits = 0
        self.refreshed = []

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:
        self.refreshed.append(obj)

    def add(self, _obj) -> None:
        return None

    def flush(self) -> None:
        return None


class _FakeConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}

    def price_id_for(self, _plan: Plan, interval: str = "month") -> str:
        return "price_123"


class _MissingPriceConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}

    def price_id_for(self, _plan: Plan, interval: str = "month") -> str:
        return ""


def _fake_attempt() -> SimpleNamespace:
    return SimpleNamespace(
        id="bca_test",
        user_id=42,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="month",
        status="pending",
        stripe_customer_id=None,
        stripe_session_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )


def _install_base_checkout_attempt_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass the DB-backed base checkout attempt tracking (SIGNAL-1024).

    create_checkout_session now wraps every checkout in a persisted
    BaseCheckoutAttempt for idempotency (resolve/link/reconcile, each backed
    by real db.execute() calls). These tests use a minimal _FakeDb that has
    no query/execute support by design, so they need to bypass that layer at
    the same billing.router boundary test_billing_checkout_guard.py already
    established, and only exercise the customer-retry logic they actually
    test.
    """
    attempt = _fake_attempt()

    monkeypatch.setattr(
        "billing.router.resolve_base_checkout_attempt",
        lambda *_args, **_kwargs: SimpleNamespace(attempt=attempt, created=True),
    )
    monkeypatch.setattr(
        "billing.router.link_base_checkout_customer",
        lambda *_args, **_kwargs: attempt,
    )
    monkeypatch.setattr(
        "billing.router._reconcile_base_checkout_session",
        lambda *_args, session, **_kwargs: (session.id, session.url),
    )
    monkeypatch.setattr(
        "billing.router.link_base_checkout_session",
        lambda *_args, **_kwargs: attempt,
    )


def test_checkout_retries_once_when_stripe_customer_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    subscription = SimpleNamespace(
        stripe_customer_id="cus_stale",
        plan_type="plan_standard",
        status="pending",
        stripe_mode="test",
    )
    user = SimpleNamespace(
        id=42, email="user@example.com", external_id="ext_123", subscription=subscription
    )

    _install_base_checkout_attempt_tracking(monkeypatch)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    customer_creates = []

    def _create_customer(**_kwargs):
        customer_creates.append(1)
        return SimpleNamespace(id="cus_fresh")

    monkeypatch.setattr("billing.router.stripe.Customer.create", _create_customer)

    checkout_calls = []

    def _create_checkout(**kwargs):
        checkout_calls.append(kwargs)
        if len(checkout_calls) == 1:
            raise stripe.error.InvalidRequestError(
                "No such customer",
                "customer",
                code="resource_missing",
            )
        return SimpleNamespace(
            id="cs_123", url="https://checkout.stripe.test/session", status="open"
        )

    monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_checkout)

    response = create_checkout_session(
        http_request=None,
        request=CheckoutSessionRequest(plan=Plan.STANDARD),
        user=user,
        db=db,
    )

    assert response == {"id": "cs_123", "url": "https://checkout.stripe.test/session"}
    assert len(checkout_calls) == 2
    assert len(customer_creates) == 1
    assert user.subscription.stripe_customer_id == "cus_fresh"


def test_checkout_does_not_swallow_other_invalid_request_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _FakeDb()
    subscription = SimpleNamespace(
        stripe_customer_id="cus_existing",
        plan_type="plan_standard",
        status="pending",
        stripe_mode="test",
    )
    user = SimpleNamespace(
        id=7, email="u@example.com", external_id="ext_7", subscription=subscription
    )

    _install_base_checkout_attempt_tracking(monkeypatch)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    def _raise_error(**_kwargs):
        raise stripe.error.InvalidRequestError(
            "Bad request",
            "line_items",
            code="parameter_invalid_integer",
        )

    monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _raise_error)

    with pytest.raises(stripe.error.InvalidRequestError):
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD),
            user=user,
            db=db,
        )


def test_is_missing_customer_error_checks_stripe_error_details() -> None:
    missing_customer_error = stripe.error.InvalidRequestError(
        "No such customer",
        "customer",
        code="resource_missing",
    )
    unrelated_error = stripe.error.InvalidRequestError(
        "Bad value",
        "line_items",
        code="parameter_invalid_integer",
    )

    assert is_missing_customer_error(missing_customer_error) is True
    assert is_missing_customer_error(unrelated_error) is False


def test_checkout_returns_400_when_selected_plan_has_no_configured_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A self-service plan with no Stripe price is a configuration error.

    The subject is Specialist rather than Executive since SIGV2-1211.
    Executive is now contact-only, so it is refused earlier for a different
    and better reason, which would have made this test silently stop covering
    the missing-price path. The Executive refusal is asserted separately
    below.
    """
    db = _FakeDb()
    subscription = SimpleNamespace(
        stripe_customer_id="cus_existing",
        plan_type="plan_standard",
        status="pending",
        stripe_mode="test",
    )
    user = SimpleNamespace(
        id=7, email="u@example.com", external_id="oauth_7", subscription=subscription
    )

    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _MissingPriceConfig()
    )

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.SPECIALIST),
            user=user,
            db=db,
        )

    error = exc_info.value
    assert getattr(error, "status_code", None) == 400
    assert getattr(error, "detail", "") == "Selected plan is not configured for checkout."


def test_checkout_refuses_a_contact_only_plan_before_it_reaches_stripe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Executive is "Contact Us", so self-service checkout is refused (SIGV2-1211).

    The card hides the Subscribe button, but a card is not a control: the
    refusal has to live on the endpoint, which is what this asserts. A
    configured Stripe price does not re-open the path, so the commercial
    decision cannot be undone by an environment variable.
    """
    db = _FakeDb()
    # Deliberately not an active subscription: an active one is refused
    # earlier still, by the base-subscription conflict guard, which would
    # test that guard instead of this one.
    subscription = SimpleNamespace(
        stripe_customer_id="cus_existing",
        plan_type="plan_standard",
        status="pending",
        stripe_mode="test",
    )
    user = SimpleNamespace(
        id=7, email="u@example.com", external_id="oauth_7", subscription=subscription
    )

    class _WorkingPriceConfig(_MissingPriceConfig):
        def price_id_for(self, plan: Plan, interval: str = "month") -> str:
            return f"price_{plan.value}_{interval}"

    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _WorkingPriceConfig()
    )

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.EXECUTIVE),
            user=user,
            db=db,
        )

    error = exc_info.value
    assert getattr(error, "status_code", None) == 409
    detail = getattr(error, "detail", {})
    assert detail["code"] == "self_service_checkout_unavailable"
    assert detail["route"] == "/contact"
