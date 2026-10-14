from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from admin import get_current_user, get_db
from database import Base
from main import app
from services.stripe_catalog_service import (
    StripeCatalogItemResult,
    StripeCatalogSyncResult,
    StripeCatalogValidationResult,
)


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


def test_admin_catalog_sync_persists_requested_mode_without_flipping_active_mode(
    monkeypatch,
) -> None:
    admin_user = models.User(
        email="admin-billing-catalog@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", "sk_live_runtime_5678")
    captured: dict[str, object] = {}

    def _fake_sync_catalog(**kwargs):
        captured.update(kwargs)
        return StripeCatalogSyncResult(
            mode="live",
            dry_run=False,
            items=[
                StripeCatalogItemResult(
                    kind="plan",
                    key="plan_standard",
                    product_id="prod_live_plan_standard",
                    price_id="price_live_plan_standard",
                    action="created",
                    message="Created managed product and price.",
                ),
                StripeCatalogItemResult(
                    kind="plan",
                    key="plan_executive",
                    product_id="prod_live_plan_executive",
                    price_id="price_live_plan_executive",
                    action="created",
                    message="Created managed product and price.",
                ),
                StripeCatalogItemResult(
                    kind="commitment_fixed",
                    key="growth",
                    product_id="prod_live_growth",
                    price_id="price_live_growth",
                    action="created",
                    message="Created managed product and price.",
                ),
                StripeCatalogItemResult(
                    kind="commitment_overage",
                    key="shared",
                    product_id="prod_live_overage",
                    price_id="price_live_overage",
                    action="created",
                    message="Created managed product and price.",
                ),
            ],
            plan_price_ids={
                "plan_standard": "price_live_plan_standard",
                "plan_executive": "price_live_plan_executive",
            },
            commitment_price_ids={
                "growth": "price_live_growth",
            },
            commitment_overage_price_id="price_live_overage",
        )

    monkeypatch.setattr("admin.sync_stripe_catalog", _fake_sync_catalog)

    response = client.post(
        "/api/v1/admin/billing/catalog/sync",
        json={"mode": "live", "scope": "all", "dry_run": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured["stripe_secret_key"] == "sk_live_runtime_5678"
    assert payload["config"]["stripe_mode"] == "test"
    assert payload["config"]["has_runtime_override"] is True

    settings = db.query(models.OperationalSetting).first()
    assert settings is not None
    runtime = settings.admin_settings_payload["billing_runtime"]
    assert "stripe_mode" not in runtime
    assert runtime["modes"]["live"]["price_ids"]["plan_standard"] == "price_live_plan_standard"
    assert runtime["modes"]["live"]["price_ids"]["plan_executive"] == "price_live_plan_executive"
    assert runtime["modes"]["live"]["commitment_price_ids"]["growth"] == "price_live_growth"
    assert runtime["modes"]["live"]["commitment_overage_price_id"] == "price_live_overage"
    assert runtime["modes"]["test"]["price_ids"]["plan_standard"] is None

    app.dependency_overrides.clear()
    db.close()


def test_admin_catalog_sync_dry_run_does_not_persist_runtime_changes(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-catalog-dry-run@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")

    monkeypatch.setattr(
        "admin.sync_stripe_catalog",
        lambda **kwargs: StripeCatalogSyncResult(
            mode=kwargs["mode"],
            dry_run=kwargs["dry_run"],
            items=[
                StripeCatalogItemResult(
                    kind="plan",
                    key="plan_standard",
                    product_id=None,
                    price_id=None,
                    action="warning",
                    message="Dry run: managed product and price would be created.",
                )
            ],
        ),
    )

    response = client.post(
        "/api/v1/admin/billing/catalog/sync",
        json={"mode": "test", "scope": "plans", "dry_run": True},
    )

    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert db.query(models.OperationalSetting).first() is None

    app.dependency_overrides.clear()
    db.close()


def test_admin_catalog_validate_uses_requested_mode_config(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-catalog-validate@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_SECRET_KEY_LIVE", "sk_live_runtime_5678")
    monkeypatch.setenv("STRIPE_PRICE_EXECUTIVE_LIVE", "price_live_plan_executive")
    captured: dict[str, object] = {}

    def _fake_validate_catalog(**kwargs):
        captured.update(kwargs)
        return [
            StripeCatalogValidationResult(
                kind="plan",
                key="plan_executive",
                configured_price_id="price_live_plan_executive",
                status="valid",
                message="Configured Stripe price matches the canonical catalog definition.",
            )
        ]

    monkeypatch.setattr("admin.validate_stripe_catalog", _fake_validate_catalog)

    response = client.post(
        "/api/v1/admin/billing/catalog/validate",
        json={"mode": "live", "scope": "plans"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert captured["stripe_secret_key"] == "sk_live_runtime_5678"
    assert captured["configured_plan_price_ids"]["plan_executive"] == "price_live_plan_executive"
    assert payload["results"][0]["status"] == "valid"

    app.dependency_overrides.clear()
    db.close()


def test_admin_catalog_sync_persists_annual_plan_price_ids(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-catalog-annual@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")

    monkeypatch.setattr(
        "admin.sync_stripe_catalog",
        lambda **kwargs: StripeCatalogSyncResult(
            mode="test",
            dry_run=False,
            items=[
                StripeCatalogItemResult(
                    kind="plan",
                    key="plan_standard",
                    product_id="prod_test_plan_standard",
                    price_id="price_test_plan_standard",
                    action="created",
                    message="Created managed product and price.",
                ),
                StripeCatalogItemResult(
                    kind="plan_annual",
                    key="plan_standard",
                    product_id="prod_test_plan_standard",
                    price_id="price_test_plan_standard_annual",
                    action="created",
                    message="Created a new canonical price.",
                ),
            ],
            plan_price_ids={"plan_standard": "price_test_plan_standard"},
            annual_plan_price_ids={"plan_standard": "price_test_plan_standard_annual"},
        ),
    )

    response = client.post(
        "/api/v1/admin/billing/catalog/sync",
        json={"mode": "test", "scope": "plans", "dry_run": False},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["annual_plan_price_ids"] == {
        "plan_standard": "price_test_plan_standard_annual"
    }

    settings = db.query(models.OperationalSetting).first()
    assert settings is not None
    runtime = settings.admin_settings_payload["billing_runtime"]
    assert runtime["modes"]["test"]["price_ids"]["plan_standard"] == "price_test_plan_standard"
    assert (
        runtime["modes"]["test"]["annual_price_ids"]["plan_standard"]
        == "price_test_plan_standard_annual"
    )

    app.dependency_overrides.clear()
    db.close()


def test_admin_catalog_validate_passes_configured_annual_price_ids(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-billing-catalog-validate-annual@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY_TEST", "sk_test_runtime_1234")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_TEST", "price_test_plan_standard")
    monkeypatch.setenv("STRIPE_PRICE_STANDARD_ANNUAL_TEST", "price_test_plan_standard_annual")
    captured: dict[str, object] = {}

    def _fake_validate_catalog(**kwargs):
        captured.update(kwargs)
        return [
            StripeCatalogValidationResult(
                kind="plan_annual",
                key="plan_standard",
                configured_price_id="price_test_plan_standard_annual",
                status="mismatch",
                message="Configured Stripe price does not match the canonical catalog definition.",
            )
        ]

    monkeypatch.setattr("admin.validate_stripe_catalog", _fake_validate_catalog)

    response = client.post(
        "/api/v1/admin/billing/catalog/validate",
        json={"mode": "test", "scope": "plans"},
    )

    assert response.status_code == 200
    assert (
        captured["configured_annual_plan_price_ids"]["plan_standard"]
        == "price_test_plan_standard_annual"
    )
    payload = response.json()
    assert payload["results"][0]["kind"] == "plan_annual"
    assert payload["results"][0]["status"] == "mismatch"

    app.dependency_overrides.clear()
    db.close()
