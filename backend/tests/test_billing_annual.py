"""Tests for Phase 3 — Annual Billing.

Covers:
- billing/config.py: price_id_for(interval="year"), plan_for_price_id() for annual IDs
- billing/router.py: list_plans annual fields, checkout with billing_interval
- billing_webhook_worker.py: _extract_billing_interval(), _upsert_subscription(billing_interval=...)
- app/config/plans.py: get_plan_catalog_entry() returning annual_price_usd
"""

import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DISABLE_TRACING", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost:5432/testdb")
os.environ.setdefault("SSM_ENABLED", "0")

from app.config.plans import get_plan_catalog_entry  # noqa: E402
from billing.config import ANNUAL_DISCOUNT_PCT, Plan, load_billing_config  # noqa: E402
from billing.router import (  # noqa: E402
    CheckoutSessionRequest,
    create_checkout_session,
    list_plans,
    normalized_billing_interval,
)
import billing_webhook_worker  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeConfig:
    app_base_url = "https://app.example.com"
    stripe_mode = "test"
    mode_configs = {"test": SimpleNamespace(secret_key="test-explicit-key")}

    def price_id_for(self, plan, interval: str = "month") -> str:
        if interval == "year":
            return f"price_{plan.value}_annual"
        return f"price_{plan.value}"


class _NoAnnualConfig:
    """Config with no annual price IDs configured."""

    app_base_url = "https://app.example.com"

    def price_id_for(self, plan, interval: str = "month") -> str:
        if interval == "year":
            return ""
        return f"price_{plan.value}"


class _FakeDb:
    def __init__(self):
        self.commits = 0
        self.refreshed = []

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def add(self, _obj):
        return None


# ---------------------------------------------------------------------------
# get_plan_catalog_entry: annual_price_usd
# ---------------------------------------------------------------------------


def test_catalog_entry_returns_annual_price_usd_for_numeric_plans():
    entry = get_plan_catalog_entry("plan_standard")
    monthly = entry["capabilities"]["monthly_price_usd"]
    expected = round(monthly * 12 * (1 - ANNUAL_DISCOUNT_PCT / 100), 2)
    assert entry["annual_price_usd"] == expected
    assert entry["annual_price_usd"] > 0


def test_catalog_entry_annual_price_usd_none_for_custom_price_plans():
    entry = get_plan_catalog_entry("unknown_plan_id")
    assert entry["annual_price_usd"] is None


def test_catalog_entry_annual_price_usd_for_all_canonical_plans():
    for plan_id in ("plan_standard", "plan_specialist", "plan_executive"):
        entry = get_plan_catalog_entry(plan_id)
        monthly = entry["capabilities"].get("monthly_price_usd", 0)
        if isinstance(monthly, (int, float)) and monthly > 0:
            expected = round(monthly * 12 * (1 - ANNUAL_DISCOUNT_PCT / 100), 2)
            assert entry["annual_price_usd"] == expected, f"{plan_id} annual mismatch"
        else:
            assert entry["annual_price_usd"] is None, f"{plan_id} should be None"


# ---------------------------------------------------------------------------
# billing/config.py: price_id_for with interval, plan_for_price_id annual
# ---------------------------------------------------------------------------


def test_price_id_for_defaults_to_monthly():
    config = load_billing_config(runtime_overrides={})
    # Without env vars, all prices are empty, but the method should not crash
    assert isinstance(config.price_id_for(Plan.STANDARD), str)
    assert isinstance(config.price_id_for(Plan.STANDARD, "month"), str)


def test_price_id_for_returns_annual_when_configured(monkeypatch):
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_ANNUAL_TEST", "price_annual_nc_test")
    config = load_billing_config(runtime_overrides={})
    assert config.price_id_for(Plan.STANDARD, "year") == "price_annual_nc_test"


def test_price_id_for_annual_returns_empty_when_not_configured():
    config = load_billing_config(runtime_overrides={})
    assert config.price_id_for(Plan.STANDARD, "year") == ""


def test_plan_for_price_id_resolves_annual_price_ids(monkeypatch):
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_PRICE_SPECIALIST_ANNUAL_TEST", "price_annual_sp")
    config = load_billing_config(runtime_overrides={})
    assert config.plan_for_price_id("price_annual_sp") == Plan.SPECIALIST


def test_plan_for_price_id_returns_none_for_unknown():
    config = load_billing_config(runtime_overrides={})
    assert config.plan_for_price_id("price_nonexistent") is None


# ---------------------------------------------------------------------------
# billing/router.py: list_plans — annual fields
# ---------------------------------------------------------------------------


def test_list_plans_returns_annual_price_fields(monkeypatch):
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            plan_type="plan_specialist",
            status="active",
            stripe_customer_id="cus_123",
            billing_interval="month",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    plans_by_id = {plan["id"]: plan for plan in payload["plans"]}

    nc = plans_by_id["plan_standard"]
    assert "annual_price_usd" in nc
    assert "annual_price_id" in nc
    assert "annual_checkout_available" in nc
    assert nc["annual_price_id"] == "price_plan_standard_annual"
    assert nc["annual_checkout_available"] is True


def test_list_plans_returns_billing_interval(monkeypatch):
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            plan_type="plan_standard",
            status="active",
            stripe_customer_id="cus_a",
            billing_interval="year",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    assert payload["billing_interval"] == "year"


def test_list_plans_billing_interval_defaults_to_month(monkeypatch):
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    assert payload["billing_interval"] == "month"


def test_list_plans_keeps_supported_monthly_interval(monkeypatch, caplog):
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            id=4242,
            plan_type="plan_standard",
            status="active",
            stripe_customer_id="cus_month",
            billing_interval="month",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    with caplog.at_level(logging.WARNING, logger="billing.router"):
        payload = list_plans(http_request=None, user=user, db=None)

    assert payload["billing_interval"] == "month"
    assert "billing_interval_normalized" not in caplog.text


def test_list_plans_keeps_supported_annual_interval(monkeypatch, caplog):
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            id=4243,
            plan_type="plan_standard",
            status="active",
            stripe_customer_id="cus_year",
            billing_interval="year",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    with caplog.at_level(logging.WARNING, logger="billing.router"):
        payload = list_plans(http_request=None, user=user, db=None)

    assert payload["billing_interval"] == "year"
    assert "billing_interval_normalized" not in caplog.text


def test_list_plans_normalizes_unsupported_interval_and_warns(monkeypatch, caplog):
    """A row with an interval outside month/year must not break the plan change flow.

    The column has no CHECK constraint, so a seeded or legacy row can hold
    anything. The payload has to stay inside the set the plan change request
    schema accepts, otherwise the UI posts the stored value back and the
    request is rejected with HTTP 422 (SIGV2-1198).
    """
    user = SimpleNamespace(
        subscription=SimpleNamespace(
            id=4244,
            plan_type="plan_standard",
            status="active",
            stripe_customer_id="cus_weekly",
            billing_interval="weekly",
        )
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    with caplog.at_level(logging.WARNING, logger="billing.router"):
        payload = list_plans(http_request=None, user=user, db=None)

    assert payload["billing_interval"] == "month"
    warnings = [
        record for record in caplog.records if "billing_interval_normalized" in record.getMessage()
    ]
    assert len(warnings) == 1
    assert "subscription_id=4244" in warnings[0].getMessage()
    assert "'weekly'" in warnings[0].getMessage()


def test_list_plans_unsupported_interval_leaves_other_fields_intact(monkeypatch):
    def _build_user(interval: str):
        return SimpleNamespace(
            subscription=SimpleNamespace(
                id=4245,
                plan_type="plan_standard",
                status="active",
                stripe_customer_id="cus_fields",
                billing_interval=interval,
            )
        )

    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    healthy = list_plans(http_request=None, user=_build_user("month"), db=None)
    degraded = list_plans(http_request=None, user=_build_user("weekly"), db=None)

    assert degraded == healthy
    assert degraded["current_plan"] == "plan_standard"
    assert degraded["status"] == "active"
    assert degraded["portal_available"] is True
    assert degraded["pending_plan_change"] is None


def test_normalized_billing_interval_handles_missing_subscription_and_attribute(caplog):
    with caplog.at_level(logging.WARNING, logger="billing.router"):
        assert normalized_billing_interval(None) == "month"

    assert "billing_interval_normalized" not in caplog.text

    with caplog.at_level(logging.WARNING, logger="billing.router"):
        assert normalized_billing_interval(SimpleNamespace(id=7)) == "month"

    assert "billing_interval_normalized" in caplog.text


def test_list_plans_annual_checkout_unavailable_when_no_annual_price(monkeypatch):
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _NoAnnualConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    plans_by_id = {plan["id"]: plan for plan in payload["plans"]}

    for plan_id in ("plan_standard", "plan_specialist", "plan_executive"):
        assert plans_by_id[plan_id]["annual_checkout_available"] is False
        assert plans_by_id[plan_id]["annual_price_id"] == ""


# ---------------------------------------------------------------------------
# billing/router.py: checkout with billing_interval
# ---------------------------------------------------------------------------


def test_checkout_passes_annual_interval_to_stripe(monkeypatch):
    db = _FakeDb()
    subscription = SimpleNamespace(
        stripe_customer_id="cus_x",
        stripe_subscription_id=None,
        plan_type="plan_standard",
        status="pending",
    )
    user = SimpleNamespace(id=1, email="u@e.com", external_id="eid", subscription=subscription)
    monkeypatch.setattr(
        "billing.router._lock_checkout_billing_state",
        lambda _db, *, user_id, authenticated_user: (user, subscription),
    )
    attempt = SimpleNamespace(
        id="bca_annual",
        user_id=user.id,
        stripe_mode="test",
        target_plan=Plan.STANDARD.value,
        billing_interval="year",
        status="pending",
        stripe_customer_id=None,
        stripe_session_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )
    monkeypatch.setattr(
        "billing.router.resolve_base_checkout_attempt",
        lambda *_args, **_kwargs: SimpleNamespace(attempt=attempt, created=True),
    )
    customer_calls = []

    def _ensure_customer(**kwargs):
        customer_calls.append(kwargs)
        return "cus_x"

    monkeypatch.setattr("billing.router.ensure_stripe_customer", _ensure_customer)

    def _link_customer(*_args, **_kwargs):
        attempt.stripe_customer_id = "cus_x"
        attempt.status = "customer_created"
        return attempt

    monkeypatch.setattr("billing.router.link_base_checkout_customer", _link_customer)
    monkeypatch.setattr(
        "billing.router.link_base_checkout_session", lambda *_args, **_kwargs: attempt
    )

    captured = []

    def _create_checkout(**kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            id="cs_1",
            url="https://checkout.stripe.test/s",
            status="open",
            mode="subscription",
            customer=kwargs["customer"],
            metadata=kwargs["metadata"],
            client_reference_id=kwargs["client_reference_id"],
            livemode=False,
        )

    monkeypatch.setattr("billing.router.stripe.checkout.Session.create", _create_checkout)

    req = CheckoutSessionRequest(plan=Plan.STANDARD, billing_interval="year")
    result = create_checkout_session(http_request=None, request=req, user=user, db=db)

    assert result == {"id": "cs_1", "url": "https://checkout.stripe.test/s"}
    assert len(captured) == 1
    assert customer_calls[0]["idempotency_key"] == "stripe-customer:1:test"
    assert captured[0]["idempotency_key"] == "base-checkout:bca_annual"
    assert captured[0]["line_items"][0]["price"] == "price_plan_standard_annual"
    assert captured[0]["metadata"]["billing_interval"] == "year"


def test_checkout_annual_fails_when_annual_price_not_configured(monkeypatch):
    from fastapi import HTTPException

    db = _FakeDb()
    subscription = SimpleNamespace(
        stripe_customer_id="cus_x",
        stripe_subscription_id=None,
        plan_type="plan_standard",
        status="pending",
    )
    user = SimpleNamespace(id=1, email="u@e.com", external_id="eid", subscription=subscription)
    monkeypatch.setattr(
        "billing.router._lock_checkout_billing_state",
        lambda _db, *, user_id, authenticated_user: (user, subscription),
    )
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _NoAnnualConfig()
    )

    with pytest.raises(HTTPException) as exc_info:
        create_checkout_session(
            http_request=None,
            request=CheckoutSessionRequest(plan=Plan.STANDARD, billing_interval="year"),
            user=user,
            db=db,
        )

    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# billing_webhook_worker.py: _extract_billing_interval
# ---------------------------------------------------------------------------


def test_extract_billing_interval_from_subscription_items():
    obj = {"items": {"data": [{"price": {"recurring": {"interval": "year"}}}]}}
    assert billing_webhook_worker._extract_billing_interval(obj) == "year"


def test_extract_billing_interval_from_invoice_lines():
    obj = {"lines": {"data": [{"price": {"recurring": {"interval": "month"}}}]}}
    assert billing_webhook_worker._extract_billing_interval(obj) == "month"


def test_extract_billing_interval_returns_none_for_empty():
    assert billing_webhook_worker._extract_billing_interval({}) is None


def test_extract_billing_interval_ignores_unexpected_values():
    obj = {"items": {"data": [{"price": {"recurring": {"interval": "week"}}}]}}
    assert billing_webhook_worker._extract_billing_interval(obj) is None


# ---------------------------------------------------------------------------
# billing_webhook_worker.py: _upsert_subscription with billing_interval
# (uses real in-memory SQLite)
# ---------------------------------------------------------------------------

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
import models  # noqa: E402
from database import Base  # noqa: E402


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db, engine):
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(db):
    user = models.User(
        email="annual@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        company_name="Annual Test",
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_annual",
            plan_type="plan_standard",
            status="active",
            billing_interval="month",
        )
    )
    db.commit()
    db.refresh(user)
    return user


def test_upsert_subscription_sets_billing_interval():
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        sub = billing_webhook_worker._upsert_subscription(
            db,
            user=user,
            stripe_customer_id="cus_annual",
            stripe_subscription_id="sub_annual_1",
            status="active",
            plan_type="plan_specialist",
            current_period_end=datetime(2027, 1, 1, tzinfo=timezone.utc),
            cancel_at_period_end=False,
            billing_interval="year",
        )
        db.commit()
        assert sub is not None
        assert sub.billing_interval == "year"
    finally:
        _cleanup_db(db, engine)


def test_upsert_subscription_preserves_interval_when_not_provided():
    db, engine = _build_db()
    try:
        user = _seed_user(db)
        sub = billing_webhook_worker._upsert_subscription(
            db,
            user=user,
            stripe_customer_id="cus_annual",
            stripe_subscription_id="sub_2",
            status="active",
            plan_type="plan_specialist",
            current_period_end=None,
            cancel_at_period_end=None,
        )
        db.commit()
        assert sub is not None
        assert sub.billing_interval == "month"
    finally:
        _cleanup_db(db, engine)
