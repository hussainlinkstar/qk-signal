from __future__ import annotations

from core.config import settings
from services.report_i18n_service import (
    DEFAULT_REPORT_LANGUAGE,
    get_report_label,
    normalize_report_language,
)


def resolve_audit_output_language(
    candidate: str | None = None,
    *,
    allow_override: bool = False,
) -> str:
    configured_default = normalize_report_language(
        getattr(settings, "AUDIT_OUTPUT_LANGUAGE", DEFAULT_REPORT_LANGUAGE)
    )
    if allow_override and candidate:
        return normalize_report_language(candidate)
    return configured_default


def get_audit_output_language_name(
    candidate: str | None = None,
    *,
    allow_override: bool = False,
) -> str:
    resolved_language = resolve_audit_output_language(
        candidate,
        allow_override=allow_override,
    )
    return get_report_label(
        DEFAULT_REPORT_LANGUAGE,
        f"meta.language_name_map.{resolved_language}",
        default=resolved_language.upper(),
    )


def build_audit_output_language_instruction(
    candidate: str | None = None,
    *,
    allow_override: bool = False,
) -> str:
    language_name = get_audit_output_language_name(
        candidate,
        allow_override=allow_override,
    )
    return (
        f"Always communicate in {language_name}. "
        "Do not switch languages based on the site's market, locale, detected content language, "
        "or provided metadata."
    )
