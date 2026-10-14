"""Compatibility layer for DB-backed settings resolution.

The canonical implementation now lives in `services.configuration_service`.
This module remains as a stable import surface for existing admin and service
code while using the single shared cache and registry.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from services.configuration_service import (
    ALL_MANAGED_SECTIONS,
    ENV_TO_DB_MAP,
    SECTION_AI_PROVIDER_KEYS,
    SECTION_CLOUDFLARE_CONFIG,
    SECTION_EMAIL_CONFIG,
    SECTION_OAUTH_CONFIG,
    SECTION_RUNTIME_CONFIG,
    SECTION_SEARCH_CONFIG,
    SECTION_SUPPORT_INFO,
    configuration_service,
    is_sensitive_field,
    mask_value,
)

__all__ = [
    "ALL_MANAGED_SECTIONS",
    "ENV_TO_DB_MAP",
    "SECTION_AI_PROVIDER_KEYS",
    "SECTION_CLOUDFLARE_CONFIG",
    "SECTION_EMAIL_CONFIG",
    "SECTION_OAUTH_CONFIG",
    "SECTION_RUNTIME_CONFIG",
    "SECTION_SEARCH_CONFIG",
    "SECTION_SUPPORT_INFO",
    "configuration_service",
    "get_all_sections_status",
    "get_section",
    "get_section_masked",
    "invalidate_db_settings_cache",
    "is_sensitive_field",
    "mask_value",
    "resolve_db_setting",
    "seed_from_env",
    "update_section",
]


def invalidate_db_settings_cache() -> None:
    configuration_service.invalidate_cache()


def resolve_db_setting(env_key: str, db: Session) -> Any:
    return configuration_service.resolve_value(env_key, db=db)


def get_section(section: str, db: Session) -> dict[str, Any]:
    return configuration_service.get_section(section, db)


def get_section_masked(section: str, db: Session) -> dict[str, Any]:
    return configuration_service.get_section_masked(section, db)


def update_section(section: str, updates: dict[str, Any], db: Session) -> None:
    configuration_service.update_section(section, updates, db)


def get_all_sections_status(db: Session) -> dict[str, dict[str, Any]]:
    return configuration_service.get_all_sections_status(db)


def seed_from_env(db: Session, *, dry_run: bool = False) -> dict[str, list[str]]:
    return configuration_service.seed_from_env(db, dry_run=dry_run)
