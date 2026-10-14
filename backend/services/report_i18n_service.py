from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping


logger = logging.getLogger(__name__)

DEFAULT_REPORT_LANGUAGE = "en"
SUPPORTED_REPORT_LANGUAGES = (
    "en",
    "es",
    "fr",
    "de",
    "it",
    "ro",
    "nl",
    "pt",
    "pl",
    "sv",
    "ja",
    "zh",
    "ar",
)
CJK_REPORT_LANGUAGES = frozenset({"ja", "zh"})
RTL_REPORT_LANGUAGES = frozenset({"ar"})

_I18N_DIR = Path(__file__).resolve().parent.parent / "i18n"

_EMAIL_TEMPLATE_KEY_MAP = {
    "audit.completed": "audit_completed",
    "audit.consensus_ready": "consensus_ready",
    "project.progress_report": "progress_report",
    "competitive.digest": "competitive_digest",
    "guest_audit.followup": "guest_audit_followup",
}


def normalize_report_language(candidate: str | None) -> str:
    if not candidate:
        return DEFAULT_REPORT_LANGUAGE
    normalized = str(candidate).strip().lower()
    if normalized in SUPPORTED_REPORT_LANGUAGES:
        return normalized
    base = normalized.split("-", 1)[0]
    if base in SUPPORTED_REPORT_LANGUAGES:
        return base
    return DEFAULT_REPORT_LANGUAGE


def is_cjk_report_language(language: str | None) -> bool:
    return normalize_report_language(language) in CJK_REPORT_LANGUAGES


def is_rtl_report_language(language: str | None) -> bool:
    return normalize_report_language(language) in RTL_REPORT_LANGUAGES


@lru_cache(maxsize=32)
def load_report_translations(language: str) -> dict[str, Any]:
    resolved_language = normalize_report_language(language)
    path = _I18N_DIR / f"{resolved_language}.json"
    if not path.exists():
        path = _I18N_DIR / f"{DEFAULT_REPORT_LANGUAGE}.json"

    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to load report translations for language=%s", resolved_language)
        if resolved_language == DEFAULT_REPORT_LANGUAGE:
            return {}
        return load_report_translations(DEFAULT_REPORT_LANGUAGE)


def _lookup(payload: Mapping[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _format_value(value: Any, params: Mapping[str, Any] | None) -> Any:
    if params is None:
        return value
    if isinstance(value, str):
        try:
            return value.format(**params)
        except Exception:
            return value
    if isinstance(value, dict):
        return {key: _format_value(item, params) for key, item in value.items()}
    if isinstance(value, list):
        return [_format_value(item, params) for item in value]
    return value


def get_report_label(
    language: str | None,
    key: str,
    *,
    default: str | None = None,
    params: Mapping[str, Any] | None = None,
) -> str:
    resolved_language = normalize_report_language(language)
    localized = _lookup(load_report_translations(resolved_language), key)
    fallback = _lookup(load_report_translations(DEFAULT_REPORT_LANGUAGE), key)
    value = localized if isinstance(localized, str) else fallback
    if not isinstance(value, str):
        value = default or key
    return str(_format_value(value, params))


def get_report_language_name(language: str | None) -> str:
    return get_report_label(language, "meta.language_name", default="English")


def get_report_language_display_label(language: str | None) -> str:
    code = normalize_report_language(language)
    english_name = get_report_label(
        DEFAULT_REPORT_LANGUAGE,
        "meta.language_name_map." + code,
        default=code.upper(),
    )
    native_name = get_report_label(code, "meta.language_name", default=english_name)
    if native_name == english_name:
        return f"{english_name} ({code.upper()})"
    return f"{english_name} / {native_name} ({code.upper()})"


def get_email_copy(
    language: str | None,
    template_key: str,
    *,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved_language = normalize_report_language(language)
    bundle = load_report_translations(resolved_language)
    fallback_bundle = load_report_translations(DEFAULT_REPORT_LANGUAGE)
    email_key = _EMAIL_TEMPLATE_KEY_MAP.get(template_key)
    params = dict(context or {})

    common_value = _lookup(bundle, "email.common")
    fallback_common = _lookup(fallback_bundle, "email.common")
    template_value = _lookup(bundle, f"email.{email_key}") if email_key else None
    fallback_template = _lookup(fallback_bundle, f"email.{email_key}") if email_key else None

    merged: dict[str, Any] = {}
    if isinstance(fallback_common, dict):
        merged.update(fallback_common)
    if isinstance(common_value, dict):
        merged.update(common_value)
    if isinstance(fallback_template, dict):
        merged.update(fallback_template)
    if isinstance(template_value, dict):
        merged.update(template_value)
    return _format_value(merged, params)
