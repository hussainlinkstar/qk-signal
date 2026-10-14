import os

import models
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


def _find_entry(entries: list[dict], key: str) -> dict:
    for entry in entries:
        if entry.get("key") == key:
            return entry
    raise AssertionError(f"Missing entry for key={key}")


def test_admin_settings_reports_runtime_statuses(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-settings@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-openai-secret-1234")
    monkeypatch.setenv("OPENROUTER_API_KEY", "changeme")
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "secure-access-secret")
    monkeypatch.setenv("JWT_REFRESH_SECRET_KEY", "secure-refresh-secret")
    monkeypatch.setenv("ADMIN_EMAILS", "admin@example.com")
    monkeypatch.setenv("FRONTEND_URL", "https://thothgraph.com")

    def _env_only_pick(env_vars, _db):
        """Bypass DB/cache path — resolve purely from os.getenv."""
        for var in env_vars:
            raw = os.getenv(var)
            if raw and raw.strip():
                return raw.strip(), var, "env"
        return None, None, "unset"

    monkeypatch.setattr("admin._pick_env_or_db_value", _env_only_pick)
    monkeypatch.setattr("admin._resolve_redis_health", lambda: (True, "Redis ping successful."))
    monkeypatch.setattr(
        "admin._get_admin_ai_cost_fx_snapshot",
        lambda _db: {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "pricing_currency": "USD",
            "billing_currency": "EUR",
            "usd_per_usd": "1.11",
            "eur_per_usd": "0.90090090",
            "effective_date": "2026-03-12",
            "source": "ecb_reference",
            "status": "ok",
            "fetched_at": "2026-03-12T09:00:00+00:00",
        },
    )

    response = client.get("/api/v1/admin/settings")

    assert response.status_code == 200
    payload = response.json()
    assert "summary" in payload
    assert "security_checks" in payload
    assert "recommendations" in payload
    assert "email_footer_defaults" in payload
    assert "currency_policy" in payload
    assert "high_confidence_rollout" not in payload
    assert "dual_track_grounding_rollout" not in payload
    assert payload["email_footer_defaults"]["footer_about_url"] == "https://thothgraph.com/about"
    assert payload["email_footer_defaults"]["social_linkedin_url"] is None
    assert payload["currency_policy"]["display_currency"] == "USD"
    # A configured required provider key reports status "configured".
    openai = _find_entry(payload["api_keys"], "openai_provider")
    assert openai["configured"] is True
    assert openai["status"] == "configured"
    assert openai["required"] is True

    # A placeholder secret reports status "placeholder".
    openrouter = _find_entry(payload["api_keys"], "openrouter_provider")
    assert openrouter["configured"] is False
    assert openrouter["status"] == "placeholder"

    firecrawl = _find_entry(payload["api_keys"], "firecrawl")
    assert firecrawl["configured"] is False
    assert firecrawl["required"] is True
    assert firecrawl["status"] == "missing"

    assert payload["summary"]["missing_required_api_keys"] >= 1
    assert payload["summary"]["placeholder_api_keys"] >= 1
    assert any(
        "FIRECRAWL_API_KEY" in recommendation for recommendation in payload["recommendations"]
    )

    app.dependency_overrides.clear()
    db.close()


def test_admin_settings_patch_persists_metadata_overrides(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-settings-patch@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-live-secret-9876")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-secret-0001")
    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "secure-access-secret")
    monkeypatch.setenv("JWT_REFRESH_SECRET_KEY", "secure-refresh-secret")
    monkeypatch.setattr("admin._resolve_redis_health", lambda: (True, "Redis ping successful."))
    monkeypatch.setattr(
        "admin._get_admin_ai_cost_fx_snapshot",
        lambda _db: {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "pricing_currency": "USD",
            "billing_currency": "EUR",
            "usd_per_usd": "1.11",
            "eur_per_usd": "0.90090090",
            "effective_date": "2026-03-12",
            "source": "ecb_reference",
            "status": "ok",
            "fetched_at": "2026-03-12T09:00:00+00:00",
        },
    )

    patch_response = client.patch(
        "/api/v1/admin/settings",
        json={
            "integrations": [
                {"key": "ai_runtime", "note": "Monitor provider failover weekly."},
            ],
            "api_keys": [
                {
                    "key": "openai_provider",
                    "note": "Owned by platform team.",
                    "owner": "platform",
                    "rotation_days": 60,
                }
            ],
            "email_footer_defaults": {
                "social_linkedin_url": "https://linkedin.com/company/acme-platform",
                "social_x_url": "https://x.com/acme_platform",
                "company_legal_name": "Acme Platform SRL",
                "company_address": "42 Orbit Avenue\nBucharest",
                "company_trademark_text": "Acme Platform is a trademark.",
                "footer_about_url": "https://acme.example/about",
                "footer_blog_url": "https://acme.example/blog",
                "footer_support_url": "https://acme.example/support",
                "footer_legal_url": "https://acme.example/legal",
                "footer_preferences_url": "https://acme.example/preferences",
                "footer_privacy_url": "https://acme.example/privacy",
            },
        },
    )
    assert patch_response.status_code == 200

    get_response = client.get("/api/v1/admin/settings")
    assert get_response.status_code == 200
    payload = get_response.json()

    ai_runtime = _find_entry(payload["integrations"], "ai_runtime")
    assert ai_runtime["admin_note"] == "Monitor provider failover weekly."
    assert "Admin note: Monitor provider failover weekly." in ai_runtime["note"]

    openai = _find_entry(payload["api_keys"], "openai_provider")
    assert openai["note"] == "Owned by platform team."
    assert openai["owner"] == "platform"
    assert openai["rotation_days"] == 60
    assert (
        payload["email_footer_defaults"]["social_linkedin_url"]
        == "https://linkedin.com/company/acme-platform"
    )
    assert payload["email_footer_defaults"]["footer_privacy_url"] == "https://acme.example/privacy"
    assert payload["email_footer_defaults"]["company_legal_name"] == "Acme Platform SRL"
    assert payload["currency_policy"]["display_currency"] == "USD"

    app.dependency_overrides.clear()
    db.close()


def test_admin_settings_patch_rejects_invalid_email_footer_url(monkeypatch) -> None:
    admin_user = models.User(
        email="admin-settings-footer-invalid@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-live-secret-9876")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "firecrawl-secret-0001")
    monkeypatch.setenv("FEATURE_BILLING_ENABLED", "false")
    monkeypatch.setenv("JWT_SECRET_KEY", "secure-access-secret")
    monkeypatch.setenv("JWT_REFRESH_SECRET_KEY", "secure-refresh-secret")
    monkeypatch.setattr("admin._resolve_redis_health", lambda: (True, "Redis ping successful."))
    monkeypatch.setattr(
        "admin._get_admin_ai_cost_fx_snapshot",
        lambda _db: {
            "base_currency": "EUR",
            "quote_currency": "USD",
            "pricing_currency": "USD",
            "billing_currency": "EUR",
            "usd_per_usd": "1.11",
            "eur_per_usd": "0.90090090",
            "effective_date": "2026-03-12",
            "source": "ecb_reference",
            "status": "ok",
            "fetched_at": "2026-03-12T09:00:00+00:00",
        },
    )

    patch_response = client.patch(
        "/api/v1/admin/settings",
        json={
            "email_footer_defaults": {
                "footer_about_url": "acme.example/about",
            },
        },
    )
    assert patch_response.status_code == 422
    assert "footer_about_url" in patch_response.json()["detail"]

    app.dependency_overrides.clear()
    db.close()


def test_admin_settings_patch_requires_admin_access() -> None:
    admin_user = models.User(
        email="admin-settings-forbidden@example.com",
        hashed_password="x",
        role="admin",
        credits=10,
        notifications_enabled=True,
    )
    client, db = _build_client_with_db(admin_user)

    def override_get_current_user():
        raise HTTPException(status_code=403, detail="Admin access required.")

    app.dependency_overrides[get_current_user] = override_get_current_user

    response = client.patch(
        "/api/v1/admin/settings",
        json={},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."

    app.dependency_overrides.clear()
    db.close()
