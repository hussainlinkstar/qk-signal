from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from admin import get_current_user, get_db
from database import Base
from main import app


def _build_client_with_db(admin_user: models.User):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    db.add(admin_user)
    db.commit()
    db.refresh(admin_user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app), db


def test_admin_billing_config_supports_runtime_mode_switch(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test_runtime_5678")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_TEST", "price_test_plan_standard")
    monkeypatch.setenv("STRIPE_PRICE_SPECIALIST_TEST", "price_test_plan_specialist")
    monkeypatch.setenv("STRIPE_PRICE_EXECUTIVE_TEST", "price_test_plan_executive")
    monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_GROWTH_TEST", "price_test_commitment_growth")
    monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_SCALE_TEST", "price_test_commitment_scale")
    monkeypatch.setenv(
        "STRIPE_PRICE_COMMITMENT_ENTERPRISE_TEST", "price_test_commitment_enterprise"
    )
    monkeypatch.setenv("STRIPE_PRICE_COMMITMENT_OVERAGE_TEST", "price_test_commitment_overage")

    response = client.get("/api/v1/admin/billing/config")
    assert response.status_code == 200
    payload = response.json()
    assert payload["stripe_mode"] == "test"
    assert payload["billing_enabled"] is True
    assert any(mode["mode"] == "test" and mode["secret_configured"] for mode in payload["modes"])
    assert any(
        item["tier"] == "growth" and item["configured"] for item in payload["commitment_price_ids"]
    )
    assert payload["commitment_overage_price_ids"]["configured"] is True

    patch_response = client.patch(
        "/api/v1/admin/billing/config",
        json={
            "stripe_mode": "live",
            "billing_enabled": True,
            "live_secret_key": "sk_live_override_1234",
            "live_webhook_secret": "whsec_live_override_5678",
            "live_price_ids": {
                "plan_standard": "price_live_starter",
                "plan_specialist": "price_live_pro",
                "plan_executive": "price_live_enterprise",
            },
            "live_commitment_price_ids": {
                "growth": "price_live_commitment_growth",
                "scale": "price_live_commitment_scale",
                "enterprise": "price_live_commitment_enterprise",
            },
            "live_commitment_overage_price_id": "price_live_commitment_overage",
        },
    )
    assert patch_response.status_code == 200
    patched_payload = patch_response.json()
    assert patched_payload["stripe_mode"] == "live"
    assert patched_payload["has_runtime_override"] is True
    assert any(
        mode["mode"] == "live" and mode["secret_configured"] and mode["webhook_configured"]
        for mode in patched_payload["modes"]
    )
    assert any(
        item["tier"] == "enterprise" and item["live_price_id"] == "price_live_commitment_enterprise"
        for item in patched_payload["commitment_price_ids"]
    )
    assert any(
        item["plan"] == "plan_executive" and item["live_price_id"] == "price_live_enterprise"
        for item in patched_payload["price_ids"]
    )
    assert (
        patched_payload["commitment_overage_price_ids"]["live_price_id"]
        == "price_live_commitment_overage"
    )

    settings = db.query(models.OperationalSetting).first()
    assert settings is not None
    assert isinstance(settings.admin_settings_payload, dict)
    assert "billing_runtime" in settings.admin_settings_payload

    app.dependency_overrides.clear()
    db.close()


def test_admin_billing_overview_reports_local_metrics(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-overview@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test_runtime_5678")
    monkeypatch.setattr("admin.stripe.Balance.retrieve", lambda: {"available": []})

    user = models.User(
        email="customer@example.com",
        hashed_password="x",
        role="user",
        credits=3,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            plan_type="plan_specialist",
            status="active",
            current_period_end=datetime.now(timezone.utc),
            cancel_at_period_end=False,
        )
    )
    db.add(
        models.BillingPayment(
            user_id=user.id,
            stripe_invoice_id="inv_123",
            stripe_customer_id="cus_123",
            stripe_subscription_id="sub_123",
            amount_paid=39900,
            amount_due=39900,
            currency="usd",
            status="paid",
            hosted_invoice_url="https://billing.example/inv_123",
            invoice_pdf="https://billing.example/inv_123.pdf",
            created_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    overview_response = client.get("/api/v1/admin/billing/overview")
    assert overview_response.status_code == 200
    payload = overview_response.json()
    assert payload["stripe_connected"] is True
    assert payload["total_subscriptions"] == 1
    assert payload["active_subscriptions"] == 1
    assert payload["total_invoices"] == 1
    assert payload["paid_invoices"] == 1
    # $99 since SIGV2-1211 (Specialist was $399). MRR is summed from the plan
    # catalogue's list price, which is exactly why Executive keeps its figure
    # in CAPABILITY_MATRIX even though no customer surface quotes it: the
    # assertion further down this file still expects 999.0 for an Executive
    # subscriber, and withholding the price from the matrix would have turned
    # it into 0 without saying so.
    assert payload["monthly_recurring_revenue_estimate"] == 99.0

    app.dependency_overrides.clear()
    db.close()


def test_admin_billing_overview_uses_canonical_plan_price_for_singularity(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-canonical@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET_TEST", "whsec_test_runtime_5678")
    monkeypatch.setattr("admin.stripe.Balance.retrieve", lambda: {"available": []})

    user = models.User(
        email="enterprise-customer@example.com",
        hashed_password="x",
        role="user",
        credits=3,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_ent_123",
            stripe_subscription_id="sub_ent_123",
            plan_type="plan_executive",
            status="active",
            current_period_end=datetime.now(timezone.utc),
            cancel_at_period_end=False,
        )
    )
    db.commit()

    overview_response = client.get("/api/v1/admin/billing/overview")
    assert overview_response.status_code == 200
    payload = overview_response.json()
    assert payload["monthly_recurring_revenue_estimate"] == 999.0

    app.dependency_overrides.clear()
    db.close()
