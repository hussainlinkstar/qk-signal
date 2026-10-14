from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import models
from core.config import settings as app_settings
from database import get_db

DEFAULT_FALLBACK_MODEL_ENABLED = True
DEFAULT_PRICING_V2_ENABLED = True
DEFAULT_CREDIT_ENGINE_V2_ENABLED = True
DEFAULT_PRICING_V2_SHADOW_MODE = False
DEFAULT_PRICING_V3_SHADOW_MODE = False
ALLOWED_REPORT_RETENTION_DAYS = (30, 60, 90)


def _resolve_default_report_retention_days() -> int:
    try:
        configured = int(app_settings.STORAGE_REPORT_RETENTION_DAYS)
    except (TypeError, ValueError):
        configured = 30
    return configured if configured in ALLOWED_REPORT_RETENTION_DAYS else 30


DEFAULT_REPORT_RETENTION_DAYS = _resolve_default_report_retention_days()


def get_or_create_operational_settings(db: Session) -> models.OperationalSetting:
    settings = db.query(models.OperationalSetting).first()
    if settings is None:
        settings = models.OperationalSetting(
            fallback_model_enabled=DEFAULT_FALLBACK_MODEL_ENABLED,
            pricing_v2_enabled=DEFAULT_PRICING_V2_ENABLED,
            credit_engine_v2_enabled=DEFAULT_CREDIT_ENGINE_V2_ENABLED,
            pricing_v2_shadow_mode=DEFAULT_PRICING_V2_SHADOW_MODE,
            pricing_v3_shadow_mode=DEFAULT_PRICING_V3_SHADOW_MODE,
            report_retention_days=DEFAULT_REPORT_RETENTION_DAYS,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def normalize_report_retention_days(
    value: int | None,
    *,
    default: int = DEFAULT_REPORT_RETENTION_DAYS,
) -> int:
    try:
        normalized = int(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return normalized if normalized in ALLOWED_REPORT_RETENTION_DAYS else default


def get_report_retention_days(db: Session) -> int:
    settings = get_or_create_operational_settings(db)
    return normalize_report_retention_days(settings.report_retention_days)


def set_report_retention_days(db: Session, value: int) -> models.OperationalSetting:
    settings = get_or_create_operational_settings(db)
    settings.report_retention_days = normalize_report_retention_days(value)
    db.commit()
    db.refresh(settings)
    return settings


def is_ai_service_enabled(db: Session) -> bool:
    settings = db.query(models.OperationalSetting).first()
    if settings is None:
        return DEFAULT_FALLBACK_MODEL_ENABLED
    return bool(settings.fallback_model_enabled)


def is_pricing_v2_enabled(db: Session) -> bool:
    settings = get_or_create_operational_settings(db)
    return bool(getattr(settings, "pricing_v2_enabled", DEFAULT_PRICING_V2_ENABLED))


def is_credit_engine_v2_enabled(db: Session) -> bool:
    settings = get_or_create_operational_settings(db)
    return bool(getattr(settings, "credit_engine_v2_enabled", DEFAULT_CREDIT_ENGINE_V2_ENABLED))


def is_pricing_v2_shadow_mode(db: Session) -> bool:
    settings = get_or_create_operational_settings(db)
    return bool(getattr(settings, "pricing_v2_shadow_mode", DEFAULT_PRICING_V2_SHADOW_MODE))


def is_pricing_v3_shadow_mode(db: Session) -> bool:
    settings = get_or_create_operational_settings(db)
    return bool(getattr(settings, "pricing_v3_shadow_mode", DEFAULT_PRICING_V3_SHADOW_MODE))


def resolve_shadow_pricing_policy_version(
    db: Session,
    *,
    active_policy_version: str | None,
) -> str | None:
    normalized_policy = str(active_policy_version or "").strip().lower()
    if is_pricing_v3_shadow_mode(db) and normalized_policy != "v3":
        return "v3"
    if is_pricing_v2_shadow_mode(db) and normalized_policy != "v2":
        return "v2"
    return None


def get_credit_engine_policy_version(db: Session) -> str:
    return "v2" if is_credit_engine_v2_enabled(db) else "v1"


def is_feature_enabled(db: Session, feature_key: str, default: bool = True) -> bool:
    """Check if a feature kill switch is enabled. Defaults to True (enabled)."""
    settings = db.query(models.OperationalSetting).first()
    if settings is None:
        return default
    payload = (
        settings.admin_settings_payload if isinstance(settings.admin_settings_payload, dict) else {}
    )
    switches = payload.get("feature_switches", {})
    return bool(switches.get(feature_key, default))


def require_feature(feature_key: str, status_code: int = 404):
    """FastAPI dependency to require a feature kill switch to be enabled."""

    def dependency(db: Session = Depends(get_db)):
        if not is_feature_enabled(db, feature_key):
            raise HTTPException(status_code=status_code, detail="Feature disabled or not found")
        return True

    return dependency


def build_maintenance_notice(settings: models.OperationalSetting) -> dict[str, str | None]:
    """The scheduled-maintenance fields that are safe to show any authenticated user.

    Deliberately limited to what the in-app banner renders. Everything else on
    the operational settings row (the maintenance toggle itself, the bypass
    allowlist, the scheduled end) stays admin-only.
    """
    return {
        "scheduled_start": settings.maintenance_scheduled_start.isoformat()
        if settings.maintenance_scheduled_start
        else None,
        "message": settings.maintenance_message or "",
    }


def get_maintenance_notice(db: Session) -> dict[str, str | None]:
    """Read the shared maintenance source of truth and return the banner fields."""
    return build_maintenance_notice(get_or_create_operational_settings(db))


def is_maintenance_active(db: Session) -> bool:
    """Check if maintenance mode is currently active."""
    from datetime import datetime, timezone

    settings = db.query(models.OperationalSetting).first()
    if settings is None:
        return False

    if settings.maintenance_mode:
        return True

    now = datetime.now(timezone.utc)
    if settings.maintenance_scheduled_start and settings.maintenance_scheduled_end:
        if settings.maintenance_scheduled_start <= now <= settings.maintenance_scheduled_end:
            return True

    return False
