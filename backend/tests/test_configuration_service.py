from __future__ import annotations

import os

os.environ.setdefault("SSM_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from core.config import Settings
import models
from services.configuration_service import (
    CONFIG_DEFINITIONS,
    SECTION_EMAIL_CONFIG,
    SECTION_OAUTH_CONFIG,
    SECTION_RUNTIME_CONFIG,
    configuration_service,
)


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session()


def test_configuration_service_prefers_db_value_over_env(monkeypatch) -> None:
    db = _build_db()
    try:
        configuration_service.invalidate_cache()
        monkeypatch.setenv("MAIL_ENABLED", "false")

        db.add(
            models.OperationalSetting(
                fallback_model_enabled=True,
                pricing_v2_enabled=True,
                credit_engine_v2_enabled=True,
                pricing_v2_shadow_mode=False,
                pricing_v3_shadow_mode=False,
                report_retention_days=30,
                admin_settings_payload={
                    SECTION_EMAIL_CONFIG: {"enabled": True},
                },
            )
        )
        db.commit()

        assert configuration_service.resolve_value("MAIL_ENABLED", db=db) is True
    finally:
        db.close()
        configuration_service.invalidate_cache()


def test_configuration_service_seeds_empty_payload_from_env(monkeypatch) -> None:
    db = _build_db()
    try:
        configuration_service.invalidate_cache()
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
        monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
        monkeypatch.setenv("S3_BUCKET_NAME", "reports-bucket")

        payload = configuration_service.get_payload(db)

        assert payload[SECTION_OAUTH_CONFIG]["google_client_id"] == "google-client-id"
        assert payload[SECTION_RUNTIME_CONFIG]["CORS_ORIGINS"] == "https://app.example.com"
        assert payload[SECTION_RUNTIME_CONFIG]["S3_BUCKET_NAME"] == "reports-bucket"
    finally:
        db.close()
        configuration_service.invalidate_cache()


def test_configuration_service_force_refresh_bypasses_stale_payload_cache() -> None:
    db = _build_db()
    try:
        configuration_service.invalidate_cache()
        db.add(
            models.OperationalSetting(
                fallback_model_enabled=True,
                pricing_v2_enabled=True,
                credit_engine_v2_enabled=True,
                pricing_v2_shadow_mode=False,
                pricing_v3_shadow_mode=False,
                report_retention_days=30,
                admin_settings_payload={
                    SECTION_RUNTIME_CONFIG: {
                        "CORS_ORIGINS": "https://legacy.example.com",
                    },
                },
            )
        )
        db.commit()

        assert (
            configuration_service.resolve_value("CORS_ORIGINS", db=db)
            == "https://legacy.example.com"
        )

        settings_row = db.query(models.OperationalSetting).first()
        assert settings_row is not None
        settings_row.admin_settings_payload = {
            SECTION_RUNTIME_CONFIG: {
                "CORS_ORIGINS": "https://fresh.example.com",
            },
        }
        db.commit()

        assert (
            configuration_service.resolve_value("CORS_ORIGINS", db=db)
            == "https://legacy.example.com"
        )
        assert (
            configuration_service.resolve_value(
                "CORS_ORIGINS",
                db=db,
                force_refresh=True,
            )
            == "https://fresh.example.com"
        )
        assert (
            configuration_service.resolve_value("CORS_ORIGINS", db=db)
            == "https://fresh.example.com"
        )
    finally:
        db.close()
        configuration_service.invalidate_cache()


def test_configuration_service_registers_v3_debate_runtime_keys() -> None:
    for key in (
        "DEBATE_TOTAL_TIMEOUT_FAST_S",
        "DEBATE_STEP_TIMEOUT_FAST_S",
        "DEBATE_COST_CAP_FAST_USD",
        "DEBATE_TOTAL_TIMEOUT_SMART_S",
        "DEBATE_STEP_TIMEOUT_SMART_S",
        "DEBATE_COST_CAP_SMART_USD",
        "DEBATE_TOTAL_TIMEOUT_DEEP_S",
        "DEBATE_STEP_TIMEOUT_DEEP_S",
        "DEBATE_COST_CAP_DEEP_USD",
    ):
        assert key in CONFIG_DEFINITIONS
        assert CONFIG_DEFINITIONS[key].runtime_meta is not None


def test_settings_debate_v3_cost_caps_honor_legacy_cap_fallback(monkeypatch) -> None:
    monkeypatch.setenv("DEBATE_COST_CAP_USD", "7.5")
    monkeypatch.delenv("DEBATE_COST_CAP_FAST_USD", raising=False)
    monkeypatch.delenv("DEBATE_COST_CAP_SMART_USD", raising=False)
    monkeypatch.delenv("DEBATE_COST_CAP_DEEP_USD", raising=False)

    settings = Settings()

    assert settings.DEBATE_COST_CAP_FAST_USD == 7.5
    assert settings.DEBATE_COST_CAP_SMART_USD == 7.5
    assert settings.DEBATE_COST_CAP_DEEP_USD == 20.0
