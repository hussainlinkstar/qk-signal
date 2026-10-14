from __future__ import annotations

import base64
import mimetypes
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from services.pdf_reports.assets import resolve_asset_data_uri
from services.pdf_reports.branding import build_branding_theme, normalize_hex_color
from services.pdf_reports.charts import (
    build_breakdown_bar_chart_svg,
    build_score_radar_svg,
    build_trend_line_svg,
)
from services.pdf_reports.labels import report_label as _l
from services.pdf_reports.logo_constants import QIKO_MARK_DATA_URI
from services.reports.audit_result_adapter import (
    to_canonical_audit_result,
    to_client_safe_audit,
    to_whitelabel_safe_audit,
)
from services.report_i18n_service import get_report_label, normalize_report_language


_REPORT_TYPES = {"standard", "battle", "branded", "whitelabel"}
_REPORT_KINDS = {"standard", "executive", "project", "competitors", "financial", "aio", "seo"}
_BRANDING_MODES = {"platform", "white_label"}
_COMPETITOR_MODES = {"latest", "trend"}
_REPORT_TYPE_ALIASES = {
    "comparative": "battle",
    "executive": "standard",
    "technical": "standard",
    "white-label": "whitelabel",
    "white_label": "whitelabel",
}
_REPORT_KIND_ALIASES = {
    "comparative": "competitors",
    "comparison": "competitors",
    "competitive": "competitors",
    "battle": "competitors",
    "standard": "standard",
    "executive": "executive",
    "project": "project",
    "progress": "project",
    "competitor": "competitors",
    "competitors": "competitors",
    "financial": "financial",
    "finance": "financial",
    "cost": "financial",
    "costs": "financial",
    "aio": "aio",
    "seo": "seo",
}
_BRANDING_MODE_ALIASES = {
    "platform": "platform",
    "default": "platform",
    "thothgraph": "platform",
    "white-label": "white_label",
    "white_label": "white_label",
    "whitelabel": "white_label",
}
_PLATFORM_BRAND_NAMES = {
    "",
    "thothgraph",
    "thothgraph intelligence",
    "thothgraph intelligence systems",
    "thoughtgraph",
    "thoughtgraph intelligence",
    "thoughtgraph intelligence systems",
    "qiko",
    "qiko signal",
}
_DEFAULT_PRIMARY_COLORS = {
    "standard": "#6366F1",
    "battle": "#6366F1",
    "branded": "#6366F1",
    "whitelabel": "#1E293B",
}
_DEFAULT_SECONDARY_COLORS = {
    "standard": "#1E293B",
    "battle": "#1E293B",
    "branded": "#1E293B",
    "whitelabel": "#E2E8F0",
}
_DEFAULT_REPORT_TITLES = {
    "standard": "AI Visibility Executive Diagnostic",
    "battle": "AI Visibility Battle Report",
    "branded": "Agency AI Readiness Diagnostic",
    "whitelabel": "AI Visibility Diagnostic",
}
_PILLAR_REPORT_TITLES = {
    "standard": "Visibility Report",
    "aio": "AIO Report",
    "seo": "SEO Report",
    "executive": "Executive Summary",
}
_DEFAULT_REPORT_SUBTITLES = {
    "standard": "Enterprise-grade GEO and AEO performance intelligence.",
    "battle": "Competitive answer-engine and generative visibility benchmark.",
    "branded": "Client-ready roadmap for answer-engine readiness and visibility growth.",
    "whitelabel": "Private-label AI visibility analysis for executive stakeholders.",
}
_WHITE_LABEL_BLOCKED_KEYS = {
    "ai_token_usage",
    "billable_cost",
    "billing_metadata",
    "cost_forecast",
    "debug",
    "estimated_llm_cost",
    "execution_metadata",
    "hallucination",
    "internal_metadata",
    "model_metadata",
    "provider_metadata",
    "warnings",
}
_COST_DISCLOSURE_BLOCKED_KEYS = {
    "actual_total_cogs_usd",
    "ai_token_usage",
    "billable_cost",
    "billable_credit_cost",
    "billing_metadata",
    "consumed_credit_cost",
    "cost_forecast",
    "credit_hold_id",
    "credit_hold_shortfall",
    "credit_hold_status",
    "credits_charged",
    "estimated_credit_cost",
    "estimated_llm_cost",
    "estimated_llm_cost_usd",
    "execution_metadata",
    "internal_metadata",
    "locked_credit_cost",
    "released_credit_cost",
    "remaining_credits",
    "token_cost_usd",
}


def _normalize_report_type(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    normalized = _REPORT_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in _REPORT_TYPES:
        raise ValueError(f"Unsupported PDF report type: {value!r}")
    return normalized


def normalize_report_kind(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    normalized = _REPORT_KIND_ALIASES.get(normalized, normalized)
    if normalized not in _REPORT_KINDS:
        raise ValueError(f"Unsupported PDF report kind: {value!r}")
    return normalized


def normalize_branding_mode(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    normalized = _BRANDING_MODE_ALIASES.get(normalized, normalized)
    if normalized not in _BRANDING_MODES:
        raise ValueError(f"Unsupported PDF branding mode: {value!r}")
    return normalized


def normalize_competitor_mode(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return None
    if normalized not in _COMPETITOR_MODES:
        raise ValueError(f"Unsupported PDF competitor mode: {value!r}")
    return normalized


def resolve_report_kind(
    *,
    explicit_report_kind: str | None = None,
    explicit_report_type: str | None = None,
    template_type: str | None = None,
) -> str:
    normalized_kind = normalize_report_kind(explicit_report_kind)
    if normalized_kind:
        return normalized_kind

    normalized_type = None
    if explicit_report_type:
        normalized_type = _normalize_report_type(explicit_report_type)
    if normalized_type == "battle":
        return "competitors"
    if normalized_type in {"branded", "whitelabel"}:
        return "executive"
    if normalized_type == "standard":
        return "standard"

    template_value = str(template_type or "").strip().lower()
    if template_value == "comparative":
        return "competitors"
    if template_value == "executive":
        return "executive"
    return "standard"


def resolve_branding_mode(
    *,
    explicit_branding_mode: str | None = None,
    explicit_report_type: str | None = None,
    agency_branding_data: Mapping[str, Any] | None = None,
) -> str:
    normalized_mode = normalize_branding_mode(explicit_branding_mode)
    if normalized_mode:
        return normalized_mode

    normalized_type = None
    if explicit_report_type:
        normalized_type = _normalize_report_type(explicit_report_type)
    if normalized_type == "whitelabel":
        return "white_label"

    branding = dict(agency_branding_data or {})
    if bool(branding.get("is_white_label")):
        return "white_label"
    return "platform"


def resolve_report_type(
    *,
    explicit_report_type: str | None = None,
    explicit_report_kind: str | None = None,
    explicit_branding_mode: str | None = None,
    template_type: str | None = None,
    agency_branding_data: Mapping[str, Any] | None = None,
) -> str:
    """Resolve the normalized report type while preserving current endpoint defaults."""

    if explicit_report_type:
        return _normalize_report_type(explicit_report_type)

    resolved_report_kind = resolve_report_kind(
        explicit_report_kind=explicit_report_kind,
        explicit_report_type=explicit_report_type,
        template_type=template_type,
    )
    if resolved_report_kind == "competitors":
        return "battle"

    resolved_branding_mode = resolve_branding_mode(
        explicit_branding_mode=explicit_branding_mode,
        explicit_report_type=explicit_report_type,
        agency_branding_data=agency_branding_data,
    )
    if resolved_branding_mode == "white_label":
        return "whitelabel"

    if str(template_type or "").strip().lower() == "comparative":
        return "battle"

    branding = dict(agency_branding_data or {})
    if bool(branding.get("is_white_label")):
        return "whitelabel"

    company_name = _text(
        branding.get("agency_name") or branding.get("company_name") or branding.get("brand_name")
    )
    logo_source = _text(
        branding.get("logo_data_url") or branding.get("custom_logo_url") or branding.get("logo_url")
    )
    has_agency_branding = bool(logo_source) or bool(
        company_name and not _is_platform_brand(company_name)
    )
    if has_agency_branding:
        return "branded"
    return "standard"


def resolve_export_manifest(
    *,
    explicit_report_kind: str | None = None,
    explicit_branding_mode: str | None = None,
    explicit_competitor_mode: str | None = None,
    explicit_report_type: str | None = None,
    template_type: str | None = None,
    hide_credit_cost: bool | None = None,
    agency_branding_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    report_kind = resolve_report_kind(
        explicit_report_kind=explicit_report_kind,
        explicit_report_type=explicit_report_type,
        template_type=template_type,
    )
    branding_mode = resolve_branding_mode(
        explicit_branding_mode=explicit_branding_mode,
        explicit_report_type=explicit_report_type,
        agency_branding_data=agency_branding_data,
    )
    competitor_mode = normalize_competitor_mode(explicit_competitor_mode)
    if competitor_mode is None and report_kind == "competitors":
        competitor_mode = "latest"
    render_report_type = resolve_report_type(
        explicit_report_type=explicit_report_type,
        explicit_report_kind=report_kind,
        explicit_branding_mode=branding_mode,
        template_type=template_type,
        agency_branding_data=agency_branding_data,
    )
    return {
        "report_kind": report_kind,
        "branding_mode": branding_mode,
        "competitor_mode": competitor_mode,
        "hide_credit_cost": True if hide_credit_cost is None else bool(hide_credit_cost),
        "legacy_report_type": (
            _normalize_report_type(explicit_report_type) if explicit_report_type else None
        ),
        "render_report_type": render_report_type,
        "template_type": _text(template_type) or None,
    }


def resolve_effective_export_manifest(
    *,
    export_manifest: Mapping[str, Any] | None,
    options: Mapping[str, Any] | None,
    template_type: str,
    branding_config: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Resolve the manifest both the export policy and the renderer must share.

    A truthy stored manifest wins; otherwise the manifest is derived from the
    job options exactly as ``render_report_pdf`` does, so a policy check can
    never evaluate a different manifest than the one that is rendered.
    """
    options_payload = dict(options or {})
    if export_manifest:
        return dict(export_manifest)
    return resolve_export_manifest(
        explicit_report_kind=_text(options_payload.get("report_kind")) or None,
        explicit_branding_mode=_text(options_payload.get("branding_mode")) or None,
        explicit_competitor_mode=_text(options_payload.get("competitor_mode")) or None,
        explicit_report_type=_text(options_payload.get("report_type")) or None,
        template_type=template_type,
        hide_credit_cost=(
            options_payload.get("hide_credit_cost")
            if "hide_credit_cost" in options_payload
            else True
        ),
        agency_branding_data=branding_config,
    )


def _text(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or default
    if isinstance(value, (int, float)):
        return str(value)
    return default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    items: list[str] = []
    for item in value:
        normalized = _text(item)
        if normalized:
            items.append(normalized)
    return items


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_get(payload: Any, *path: str, default: Any = None) -> Any:
    current = payload
    for key in path:
        if not isinstance(current, Mapping):
            return default
        current = current.get(key)
    return current if current is not None else default


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        # A naive string has no timezone: stored timestamps are UTC and a
        # date-only value is a calendar date, so interpret it as UTC rather
        # than shifting it through the host timezone (SIGV2-1205).
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _format_display_date(value: Any) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        candidate = _text(value)
        return candidate or datetime.now(timezone.utc).strftime("%B %d, %Y")
    return parsed.strftime("%B %d, %Y")


def _format_coverage_date(value: Any, language: str = "en") -> str:
    parsed = value if isinstance(value, datetime) else None
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    return parsed.strftime("%B %d, %Y") if parsed else _l(language, "Unknown date")


def _format_signed_delta(value: float | None, *, suffix: str = "") -> str:
    if value is None:
        return "-"
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return f"{rounded:+.0f}{suffix}"
    return f"{rounded:+.1f}{suffix}"


def _score_display(value: float | None) -> str:
    if value is None:
        return "-"
    rounded = round(float(value), 1)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.1f}"


def _display_domain(url: str | None) -> str | None:
    """Bare host for cover display: 'https://northwindhotels.com/' -> 'northwindhotels.com'."""
    if not url:
        return None
    parsed = urlparse(str(url))
    host = parsed.netloc or parsed.path.split("/", 1)[0]
    return host or str(url)


def _score_tone(value: float | None) -> str:
    if value is None:
        return "muted"
    if value >= 80:
        return "strong"
    if value >= 65:
        return "solid"
    if value >= 45:
        return "watch"
    return "critical"


def _priority_value(value: Any) -> int:
    parsed = _int(value)
    return parsed if parsed is not None else 999


def _title_case(value: str) -> str:
    normalized = _text(value)
    return normalized.replace("_", " ").title() if normalized else ""


def _is_platform_brand(value: str | None) -> bool:
    return _text(value).lower() in _PLATFORM_BRAND_NAMES


def _encode_inline_svg(svg_markup: str) -> str:
    encoded = base64.b64encode(svg_markup.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


_REPO_ROOT = Path(__file__).resolve().parents[3]
_FRONTEND_PUBLIC_DIR = _REPO_ROOT / "frontend" / "public"


@lru_cache(maxsize=8)
def _bundled_image_data_uri(asset_name: str) -> str | None:
    asset_path = _FRONTEND_PUBLIC_DIR / asset_name
    try:
        payload = asset_path.read_bytes()
    except OSError:
        return None

    mime_type = mimetypes.guess_type(asset_path.name)[0] or ""
    if asset_path.suffix.lower() == ".svg":
        mime_type = "image/svg+xml"
    if mime_type != "image/svg+xml" and not mime_type.startswith("image/"):
        return None

    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _inline_platform_logo_data_uri(
    *,
    wordmark_fill: str,
    subtitle_fill: str,
) -> str:
    svg = """
<svg xmlns="http://www.w3.org/2000/svg" width="264" height="48" viewBox="0 0 264 48" fill="none">
  <rect x="0.5" y="0.5" width="47" height="47" rx="12" fill="#0D1726" stroke="#6366F1"/>
  <path d="M16 14h16v4H24v16h-4V18h-4z" fill="#6366F1"/>
  <path d="M30 30H18v-4h8V14h4z" fill="#22D3EE"/>
  <text x="62" y="21" fill="{wordmark_fill}" font-size="11" font-family="Manrope, Inter, DejaVu Sans, Arial, sans-serif" font-weight="700" letter-spacing="1.8">QIKO SIGNAL</text>
  <text x="62" y="35" fill="{subtitle_fill}" font-size="10" font-family="Manrope, Inter, DejaVu Sans, Arial, sans-serif">AI VISIBILITY REPORTS</text>
</svg>
""".strip().format(wordmark_fill=wordmark_fill, subtitle_fill=subtitle_fill)
    return _encode_inline_svg(svg)


def _default_platform_header_logo_data_uri() -> str:
    """Qiko mark for the running header bar. The retired stacked wordmark
    was removed (SIGV2-1275); the header carries the approved mark alone
    since Satoshi is only available as .woff2 and unusable in reportlab."""
    return QIKO_MARK_DATA_URI or _inline_platform_logo_data_uri(
        wordmark_fill="#FFFFFF",
        subtitle_fill="#94A3B8",
    )


def _default_platform_cover_logo_data_uri() -> str:
    """Qiko mark for the cover lockup; the "Signal" word is set in Satoshi
    beside it in the template, matching the approved in-app lockup."""
    return QIKO_MARK_DATA_URI or _inline_platform_logo_data_uri(
        wordmark_fill="#FFFFFF",
        subtitle_fill="#D6E6F8",
    )


def _branding_payload(branding: Any) -> dict[str, Any]:
    if isinstance(branding, Mapping):
        payload = dict(branding)
    else:
        payload = {
            "title": getattr(branding, "title", None),
            "agency_name": getattr(branding, "agency_name", None),
            "company_name": getattr(branding, "company_name", None),
            "logo_data_url": getattr(branding, "logo_data_url", None),
            "custom_logo_url": getattr(branding, "custom_logo_url", None),
            "logo_url": getattr(branding, "logo_url", None),
            "primary_color": getattr(branding, "primary_color", None),
            "secondary_color": getattr(branding, "secondary_color", None),
            "generated_date": getattr(branding, "generated_date", None),
            "language": getattr(branding, "language", None),
            "report_type": getattr(branding, "report_type", None),
            "report_kind": getattr(branding, "report_kind", None),
            "branding_mode": getattr(branding, "branding_mode", None),
            "competitor_mode": getattr(branding, "competitor_mode", None),
            "hide_credit_cost": getattr(branding, "hide_credit_cost", None),
            "footer_text": getattr(branding, "footer_text", None),
            "custom_footer_text": getattr(branding, "custom_footer_text", None),
            "is_white_label": getattr(branding, "is_white_label", None),
        }
    payload["agency_name"] = _text(payload.get("agency_name") or payload.get("company_name"))
    payload["logo_data_url"] = _text(
        payload.get("logo_data_url") or payload.get("custom_logo_url") or payload.get("logo_url")
    )
    return payload


def _build_branding_context(
    *,
    report_type: str,
    report_kind: str,
    agency_branding_data: Mapping[str, Any] | None,
    generated_at: Any,
    language: str,
) -> dict[str, Any]:
    payload = dict(agency_branding_data or {})
    agency_name = _text(payload.get("agency_name") or payload.get("company_name"))
    agency_logo = resolve_asset_data_uri(
        _text(
            payload.get("logo_data_url")
            or payload.get("custom_logo_url")
            or payload.get("logo_url")
        )
    )
    footer_text = _text(
        payload.get("footer_text")
        or payload.get("custom_footer_text")
        or payload.get("agency_footer_text")
    )
    primary_color = normalize_hex_color(
        payload.get("primary_color"), _DEFAULT_PRIMARY_COLORS[report_type]
    )
    secondary_color = normalize_hex_color(
        payload.get("secondary_color"), _DEFAULT_SECONDARY_COLORS[report_type]
    )
    generated_date = _text(payload.get("generated_date")) or _text(generated_at)
    report_title = _text(payload.get("title")) or _l(
        language, _PILLAR_REPORT_TITLES.get(report_kind, _DEFAULT_REPORT_TITLES[report_type])
    )
    report_subtitle = _l(language, _DEFAULT_REPORT_SUBTITLES[report_type])

    if report_type in {"standard", "battle"}:
        header_mode = "platform_logo"
        header_logo_data_uri = _default_platform_header_logo_data_uri()
        cover_logo_data_uri = _default_platform_cover_logo_data_uri()
        logo_data_uri = header_logo_data_uri
        display_name = "Qiko Signal"
        footer_mode = "text"
        footer_text = _l(language, "Generated by Qiko Signal - Intelligence Analyzer")
        show_platform_branding = True
    elif report_type == "branded":
        header_mode = "agency_logo" if agency_logo else "agency_text"
        header_logo_data_uri = agency_logo
        cover_logo_data_uri = agency_logo
        logo_data_uri = header_logo_data_uri
        display_name = agency_name or "Agency"
        footer_mode = "text"
        footer_text = _l(language, "Powered by Qiko Signal")
        show_platform_branding = True
    else:
        header_mode = "agency_logo" if agency_logo else "agency_text"
        header_logo_data_uri = agency_logo
        cover_logo_data_uri = agency_logo
        logo_data_uri = header_logo_data_uri
        display_name = agency_name
        footer_mode = "text" if footer_text else "blank"
        footer_text = footer_text or ""
        show_platform_branding = False

    theme = build_branding_theme(
        SimpleNamespace(
            title=report_title,
            company_name=display_name,
            primary_color=primary_color,
            secondary_color=secondary_color,
            generated_date=generated_date,
            language=language,
            vendor_name="Qiko Signal",
            is_white_label=report_type == "whitelabel",
            show_powered_by=report_type == "branded",
        )
    )
    return {
        **theme,
        "agency_name": display_name,
        "logo_data_uri": logo_data_uri,
        "header_logo_data_uri": header_logo_data_uri,
        "cover_logo_data_uri": cover_logo_data_uri,
        "header_mode": header_mode,
        "footer_mode": footer_mode,
        "footer_text": footer_text,
        "show_platform_branding": show_platform_branding,
        "report_title": report_title,
        "report_subtitle": report_subtitle,
        "generated_date": generated_date,
        "generated_date_long": _format_display_date(generated_date),
    }


def _canonicalize_audit(audit: Mapping[str, Any] | None) -> dict[str, Any]:
    payload = deepcopy(dict(audit)) if isinstance(audit, Mapping) else {}
    target = _mapping(payload.get("target"))
    metadata = _mapping(payload.get("metadata"))
    audit_url = _text(target.get("url") or _safe_get(payload, "site", "url") or payload.get("url"))
    return to_canonical_audit_result(
        payload,
        audit_url=audit_url or None,
        audit_target_type=_text(
            target.get("type") or metadata.get("audit_target_type") or "website"
        )
        or "website",
        target_name=_text(target.get("name") or metadata.get("target_name")) or None,
        target_url=_text(target.get("url") or metadata.get("target_url") or audit_url) or None,
        target_metadata=_mapping(target.get("metadata") or metadata.get("target_metadata")),
        created_at=_parse_datetime(metadata.get("created_at")),
        plan=_text(metadata.get("plan"), default="plan_starter") or "plan_starter",
        version=_text(metadata.get("version"), default="2.0") or "2.0",
    )


def _seed_audit_payload(
    *,
    audit_payload: Mapping[str, Any] | None,
    audit_record: Any | None,
    audit_url: str | None = None,
) -> dict[str, Any]:
    seeded = deepcopy(dict(audit_payload)) if isinstance(audit_payload, Mapping) else {}
    metadata = _mapping(seeded.get("metadata"))
    target = _mapping(seeded.get("target"))
    site = _mapping(seeded.get("site"))

    resolved_url = _text(
        target.get("url")
        or getattr(audit_record, "target_url", None)
        or getattr(audit_record, "url", None)
        or audit_url
        or site.get("url")
    )
    resolved_target_name = _text(
        target.get("name")
        or getattr(audit_record, "target_name", None)
        or metadata.get("target_name")
        or resolved_url
    )
    resolved_target_type = (
        _text(
            target.get("type")
            or metadata.get("audit_target_type")
            or getattr(
                getattr(audit_record, "audit_target_type", None),
                "value",
                getattr(audit_record, "audit_target_type", None),
            )
            or "website"
        )
        or "website"
    )
    resolved_target_metadata = {
        **_mapping(target.get("metadata")),
        **_mapping(metadata.get("target_metadata")),
        **_mapping(getattr(audit_record, "target_metadata", None)),
    }

    if audit_record is not None:
        created_at = getattr(audit_record, "created_at", None)
        if created_at is not None and not metadata.get("created_at"):
            metadata["created_at"] = (
                created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)
            )
        project = getattr(audit_record, "project", None)
        project_language = getattr(project, "language", None)
        if project_language and not metadata.get("language"):
            metadata["language"] = project_language

    metadata["target_name"] = resolved_target_name or metadata.get("target_name")
    metadata["target_url"] = resolved_url or metadata.get("target_url")
    metadata["audit_target_type"] = resolved_target_type
    metadata["target_metadata"] = resolved_target_metadata
    seeded["metadata"] = metadata
    seeded["target"] = {
        "type": resolved_target_type,
        "name": resolved_target_name or None,
        "url": resolved_url or None,
        "metadata": resolved_target_metadata,
    }
    if resolved_url:
        site["url"] = resolved_url
    seeded["site"] = site
    return seeded


def _entity_strength_score(canonical_audit: Mapping[str, Any]) -> float | None:
    entity_analysis = _mapping(_safe_get(canonical_audit, "metadata", "entity_analysis"))
    values = [
        value
        for value in (
            _float(entity_analysis.get("entity_clarity_score")),
            _float(entity_analysis.get("brand_trust_score")),
        )
        if value is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def _build_ai_engines(canonical_audit: Mapping[str, Any], language: str = "en") -> dict[str, Any]:
    """Per-engine rows attached to this audit snapshot (SIGV2-1205).

    ``metadata.engines`` is written at render time from the visibility
    measurements attached to the audit's own job, never from live state, so an
    old report keeps last month's engine picture. Each row carries a status:
    ``measured`` (a real score), ``pending`` (measurement still in flight) or
    ``withheld`` (a measurement exists but its result was withheld, e.g. a
    failed or plan-gated engine). When nothing is attached, ``available`` is
    False and the template says so honestly instead of pretending a row.
    """
    raw_engines = _safe_get(canonical_audit, "metadata", "engines")
    items: list[dict[str, Any]] = []
    if isinstance(raw_engines, Sequence) and not isinstance(raw_engines, (str, bytes, bytearray)):
        for entry in raw_engines:
            if not isinstance(entry, Mapping):
                continue
            # Rows are keyed "engine" because the client-safe projection
            # strips nested "provider" keys; accept both for stored payloads.
            provider = _text(entry.get("engine") or entry.get("provider"))
            status = _text(entry.get("status")).lower() or "withheld"
            if status not in {"measured", "pending", "withheld"}:
                status = "withheld"
            score = _float(entry.get("score"))
            if score is None:
                status = "pending" if status == "measured" else status
            status_label = {
                "measured": _l(language, "Measured"),
                "pending": _l(language, "Pending"),
                "withheld": _l(language, "Withheld"),
            }[status]
            items.append(
                {
                    # "provider" is safe here: the blocklist that strips it
                    # runs on the audit payload before sections are built,
                    # not on the assembled context.
                    "provider": provider,
                    "engine": provider,
                    "label": _text(entry.get("label"))
                    or _title_case(provider)
                    or _l(language, "Engine"),
                    "status": status,
                    "status_label": status_label,
                    "score": score if status == "measured" else None,
                    "score_display": _score_display(score) if status == "measured" else None,
                    "measured_at": _text(entry.get("measured_at")),
                }
            )
    return {"items": items, "available": bool(items)}


def _build_score_cards(
    canonical_audit: Mapping[str, Any], report_kind: str, language: str = "en"
) -> list[dict[str, Any]]:
    scores = _mapping(canonical_audit.get("scores"))
    aio_score = _float(_safe_get(canonical_audit, "metadata", "aio", "aio_score"))
    if report_kind in {"standard", "aio", "seo", "executive"}:
        metrics = (("AI visibility", aio_score), ("Search visibility", _float(scores.get("seo"))))
    else:
        metrics = tuple(
            (label, _float(scores.get(key)))
            for label, key in (
                ("Overall", "overall"),
                ("SEO", "seo"),
                ("GEO", "geo"),
                ("AEO", "aeo"),
            )
        )
    cards: list[dict[str, Any]] = []
    for label, value in metrics:
        cards.append(
            {
                "label": _l(language, label),
                "value": value,
                "display_value": _score_display(value),
                "tone": _score_tone(value),
                "delta_display": None,
            }
        )
    return cards


def _format_dimension_labels(dimensions: Sequence[str] | None, language: str = "en") -> list[str]:
    if not dimensions:
        return []
    labels: list[str] = []
    for value in dimensions:
        normalized = _text(value).lower()
        if normalized == "seo":
            labels.append(_l(language, "SEO"))
        elif normalized == "geo":
            labels.append(_l(language, "GEO"))
        elif normalized == "aeo":
            labels.append(_l(language, "AEO"))
        elif normalized == "overall":
            labels.append(_l(language, "Overall"))
    return labels


def _build_action_items(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> list[dict[str, Any]]:
    recommendations = _mapping(canonical_audit.get("recommendations"))
    raw_suggestions = recommendations.get("items")
    if not isinstance(raw_suggestions, Sequence):
        raw_suggestions = canonical_audit.get("suggestions")
    if not isinstance(raw_suggestions, Sequence):
        return []
    items: list[dict[str, Any]] = []
    for suggestion in raw_suggestions:
        if not isinstance(suggestion, Mapping):
            continue
        action = _text(suggestion.get("action"))
        title = _text(suggestion.get("title")) or action
        if not action and not title:
            continue
        priority = _int(suggestion.get("priority"))
        category = _text(suggestion.get("category"), default="technical") or "technical"
        affected_scores = _format_dimension_labels(
            _string_list(
                suggestion.get("cross_score_leverage") or suggestion.get("affected_scores")
            ),
            language=language,
        )
        # SIGV2-1211: `expected_score_impact` is deliberately not read here.
        # It used to be formatted into an "Expected impact: SEO +6 pts" string
        # that no template ever rendered, and every action section already says
        # in so many words that no predicted point gain is attached to an item,
        # so publishing it would contradict the page it sits on. Penalties and
        # blockers keep their numeric `impact_display`: those are measured
        # deductions, not predictions. Measured aggregation is SIGV2-1007.
        items.append(
            {
                "title": title,
                "action": action or title,
                "summary": _text(suggestion.get("summary")),
                "rationale": _text(suggestion.get("rationale")),
                "category": _title_case(category.replace("_", " ")),
                "priority": priority,
                "priority_display": str(priority) if priority is not None else "N/A",
                "owner": _title_case(_text(suggestion.get("owner"), default="engineering")),
                "effort": _title_case(_text(suggestion.get("estimated_effort"), default="medium")),
                "confidence": _title_case(_text(suggestion.get("confidence"), default="medium")),
                "affected_scores": affected_scores,
                "dependencies": _string_list(suggestion.get("dependencies")),
                "grounded_by_findings": _string_list(
                    suggestion.get("grounded_by_findings") or suggestion.get("derived_from")
                ),
            }
        )
    items.sort(key=lambda item: (_priority_value(item.get("priority")), item["title"].lower()))
    return items


def _group_action_items(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    order: list[str] = []
    for item in items:
        category = _text(item.get("category"), default="Technical") or "Technical"
        if category not in grouped:
            order.append(category)
        grouped[category].append(dict(item))

    groups: list[dict[str, Any]] = []
    for category in order:
        entries = grouped[category]
        entries.sort(
            key=lambda item: (_priority_value(item.get("priority")), item["title"].lower())
        )
        groups.append({"category": category, "items": entries})
    return groups


def _normalize_penalties(category: str, penalties: Any) -> list[dict[str, Any]]:
    if not isinstance(penalties, Sequence) or isinstance(penalties, (str, bytes, bytearray)):
        return []

    rows: list[dict[str, Any]] = []
    for penalty in penalties:
        if not isinstance(penalty, Mapping):
            continue
        reason = _text(penalty.get("reason") or penalty.get("title") or penalty.get("description"))
        if not reason:
            continue
        impact = _float(penalty.get("impact"))
        severity = "moderate"
        if impact is not None and abs(impact) >= 20:
            severity = "critical"
        elif impact is not None and abs(impact) >= 10:
            severity = "high"
        rows.append(
            {
                "category": category.upper(),
                "reason": reason,
                "impact": impact,
                "impact_display": _format_signed_delta(impact, suffix=" pts"),
                "severity": severity,
            }
        )

    rows.sort(key=lambda item: abs(item["impact"] or 0), reverse=True)
    return rows


def _collect_penalties(
    canonical_audit: Mapping[str, Any], sections: Sequence[str]
) -> list[dict[str, Any]]:
    scores = _mapping(canonical_audit.get("scores"))
    penalties: list[dict[str, Any]] = []
    for section in sections:
        breakdown = _mapping(scores.get(f"{section}_breakdown"))
        penalties.extend(_normalize_penalties(section, breakdown.get("penalties")))
    penalties.sort(key=lambda item: abs(item["impact"] or 0), reverse=True)
    return penalties


def _normalize_intelligence_grid(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        agent_correlation = _text(item.get("agent_correlation"))
        neural_logic = _text(item.get("neural_logic"))
        architect_fix = _text(item.get("architect_fix"))
        if not any((agent_correlation, neural_logic, architect_fix)):
            continue
        rows.append(
            {
                "agent_correlation": agent_correlation,
                "neural_logic": neural_logic,
                "architect_fix": architect_fix,
                "discovery": _text(item.get("discovery")),
                "priority_weight": _text(item.get("priority_weight")),
            }
        )
    return rows


def _narrative_block_context(value: Any, fallback_text: str = "") -> dict[str, Any]:
    payload = _mapping(value)
    text = _text(payload.get("text")) or fallback_text
    confidence = _text(payload.get("confidence"), default="low") or "low"
    return {
        "text": text,
        "confidence": confidence,
        "confidence_label": _title_case(confidence),
        "requires_review": bool(payload.get("requires_review")),
        "supported_sentence_ratio": _float(payload.get("supported_sentence_ratio")),
    }


def _narrative_context(canonical_audit: Mapping[str, Any]) -> dict[str, Any]:
    narrative = _mapping(canonical_audit.get("narrative"))
    metadata = _mapping(canonical_audit.get("metadata"))
    executive_summary = _narrative_block_context(
        narrative.get("executive_summary"),
        fallback_text=_text(
            # Read NEW key first, then the legacy persisted key.
            metadata.get("strategic_summary")
            or metadata.get("neural_executive_summary")
            or metadata.get("executive_summary")
        ),
    )
    # Read the renamed (de-jargoned) keys first, then fall back to the legacy
    # persisted keys so historical ``full_report`` JSON still renders in PDFs.
    market_blueprint = _narrative_block_context(
        narrative.get("competitive_positioning") or narrative.get("market_dominance_blueprint"),
        fallback_text=_text(
            metadata.get("competitive_positioning") or metadata.get("market_dominance_blueprint")
        ),
    )
    return {
        "executive_summary": executive_summary,
        "strategic_summary": executive_summary["text"],
        "strategic_intelligence_grid": _normalize_intelligence_grid(
            narrative.get("debate_findings")
            or narrative.get("strategic_intelligence_grid")
            or metadata.get("debate_findings")
            or metadata.get("strategic_intelligence_grid")
        ),
        "market_dominance_blueprint_block": market_blueprint,
        "market_dominance_blueprint": market_blueprint["text"],
    }


def _build_integrity_trust_context(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, Any]:
    certificate = _mapping(canonical_audit.get("integrity_certificate"))
    summary = _mapping(certificate.get("summary"))
    if not certificate or not summary:
        return {
            "items": [],
            "blocked_buckets": [],
            "degraded_note": "",
        }

    track_a_total = _int(summary.get("track_a_total")) or 0
    track_a_supported = _int(summary.get("track_a_supported")) or 0
    track_a_flagged = _int(summary.get("track_a_flagged")) or 0
    track_a_omitted = _int(summary.get("track_a_omitted")) or 0
    track_b_total = _int(summary.get("track_b_total")) or 0
    track_b_supported = _int(summary.get("track_b_supported")) or 0
    track_b_flagged = _int(summary.get("track_b_flagged")) or 0
    track_b_needs_manual_review = _int(summary.get("track_b_needs_manual_review")) or 0
    track_b_omitted = _int(summary.get("track_b_omitted")) or 0
    review_claims = (
        track_a_flagged
        + track_a_omitted
        + track_b_flagged
        + track_b_needs_manual_review
        + track_b_omitted
    )
    degraded = bool(certificate.get("degraded"))
    degraded_reason = _text(certificate.get("degraded_reason"))

    items = [
        {
            "label": _l(language, "Grounding profile"),
            "value": _title_case(
                _text(certificate.get("grounding_profile"), default="single_track_v1")
            ),
        },
        {
            "label": _l(language, "Track A review"),
            "value": f"{track_a_supported}/{track_a_total} supported",
        },
        {
            "label": _l(language, "Track B review"),
            "value": f"{track_b_supported}/{track_b_total} passed"
            if track_b_total > 0
            else _l(language, "Not engaged"),
        },
        {
            "label": _l(language, "Review state"),
            "value": (
                f"Degraded ({_title_case(degraded_reason) or 'Safe fallback'})"
                if degraded
                else (
                    f"{review_claims} blocked"
                    if review_claims > 0
                    else _l(language, "No blocked claims")
                )
            ),
        },
    ]

    blocked_buckets: list[dict[str, Any]] = []
    raw_buckets = certificate.get("blocked_claim_buckets")
    if isinstance(raw_buckets, list):
        for item in raw_buckets:
            bucket = _mapping(item)
            count = _int(bucket.get("count")) or 0
            if count <= 0:
                continue
            blocked_buckets.append(
                {
                    "track_label": _title_case(_text(bucket.get("track"))),
                    "category_label": _title_case(_text(bucket.get("category"))),
                    "count": count,
                }
            )
    blocked_buckets.sort(key=lambda item: int(item.get("count") or 0), reverse=True)

    degraded_note = ""
    if degraded:
        degraded_note = f"Integrity review partially degraded: {_title_case(degraded_reason) or 'Safe fallback'}."

    return {
        "items": items,
        "blocked_buckets": blocked_buckets[:4],
        "degraded_note": degraded_note,
    }


def _build_trust_banner(canonical_audit: Mapping[str, Any], language: str = "en") -> dict[str, Any]:
    confidence = _mapping(canonical_audit.get("confidence"))
    score_contract = _mapping(canonical_audit.get("score_contract"))
    integrity = _build_integrity_trust_context(canonical_audit, language=language)
    coverage = _float(confidence.get("external_data_coverage")) or 0.0
    warnings = _string_list(confidence.get("warnings"))
    items = [
        {
            "label": _l(language, "Audit mode"),
            "value": _title_case(_text(confidence.get("audit_mode"), default="website")),
        },
        {
            "label": _l(language, "Deterministic score engine"),
            "value": _title_case(
                _text(
                    score_contract.get("public_score_source"), default="deterministic_matrix"
                ).replace("_", " ")
            ),
        },
        {
            "label": _l(language, "Score version"),
            "value": _text(score_contract.get("public_score_version"), default="3.0"),
        },
        {
            "label": _l(language, "External data coverage"),
            "value": f"{round(coverage * 100):.0f}%",
        },
        {
            "label": _l(language, "Competitive confidence"),
            "value": _title_case(_text(confidence.get("competitive_confidence"), default="low")),
        },
        {
            "label": _l(language, "Narrative confidence"),
            "value": _title_case(_text(confidence.get("narrative_confidence"), default="low")),
        },
    ]
    return {
        "items": items,
        "warnings": warnings,
        "integrity_items": integrity["items"],
        "blocked_buckets": integrity["blocked_buckets"],
        "degraded_note": integrity["degraded_note"],
    }


def _humanize_component_key(value: str) -> str:
    return _title_case(value.replace("_", " "))


def _business_implication_for_score(label: str, value: float | None, language: str = "en") -> str:
    if label == "SEO":
        if value is None or value < 45:
            return _l(
                language,
                "Discovery, crawl, and page relevance signals are likely constraining baseline visibility.",
            )
        if value < 70:
            return _l(
                language,
                "Core SEO foundations are present, but technical gaps are still limiting consistent visibility.",
            )
        return _l(
            language,
            "SEO readiness is stable enough to support broader GEO and AEO gains.",
        )
    if label == "GEO":
        if value is None or value < 45:
            return _l(
                language,
                "Local and geographic machine-readability is likely suppressing visibility in place-aware discovery.",
            )
        if value < 70:
            return _l(
                language,
                "Geographic relevance signals exist, but location authority is not yet defensible.",
            )
        return _l(
            language,
            "Geographic authority signals are strong enough to support competitive local discovery.",
        )
    if value is None or value < 45:
        return _l(
            language,
            "Answer-engine readiness is weak, making extraction and citation less reliable.",
        )
    if value < 70:
        return _l(
            language,
            "Answer-engine signals are emerging, but extractability is still inconsistent.",
        )
    return _l(
        language,
        "Machine-readable answer coverage is supporting stronger generative visibility.",
    )


def _build_why_this_score_panels(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> list[dict[str, Any]]:
    scores = _mapping(canonical_audit.get("scores"))
    aeo = _mapping(canonical_audit.get("aeo"))
    schema_health = _mapping(aeo.get("schema_health"))
    panels: list[dict[str, Any]] = []

    for label, key in (("SEO", "seo"), ("GEO", "geo"), ("AEO", "aeo")):
        score_value = _float(scores.get(key))
        breakdown = _mapping(scores.get(f"{key}_breakdown"))
        components = _mapping(breakdown.get("components"))
        strengths = [
            _humanize_component_key(component_key)
            for component_key, component_value in sorted(
                components.items(),
                key=lambda item: _float(item[1]) or 0.0,
                reverse=True,
            )
            if _float(component_value) is not None
        ][:2]
        blockers = [
            _text(penalty.get("reason") or penalty.get("title"))
            for penalty in breakdown.get("penalties", [])
            if isinstance(penalty, Mapping) and _text(penalty.get("reason") or penalty.get("title"))
        ][:3]
        missing_signals = [
            blocker
            for blocker in blockers
            if any(keyword in blocker.lower() for keyword in ("missing", "no ", "lack", "weak"))
        ][:2]
        if label == "AEO":
            missing_signals.extend(_string_list(schema_health.get("missing_high_impact_types"))[:2])
        panels.append(
            {
                "label": label,
                "score": score_value,
                "score_display": _score_display(score_value),
                "tone": _score_tone(score_value),
                "strongest_signals": strengths
                or [
                    _l(
                        language,
                        "No positive structural signal was strong enough to lead this score.",
                    )
                ],
                "top_blockers": blockers
                or [_l(language, "No blockers were captured for this score.")],
                "missing_signals": missing_signals
                or [_l(language, "No high-impact missing signal was identified.")],
                "business_implication": _business_implication_for_score(
                    label, score_value, language
                ),
            }
        )
    return panels


_MVP_REPORT_KINDS = ("standard", "aio", "seo", "executive")
# AEO and GEO are internal components of AIO; the four MVP report kinds never
# name them in customer-facing text.
_AIO_INTERNAL_TOKEN_RE = re.compile(r"\b(?:AEO|GEO)\b")
_AIO_RUN_RE = re.compile(r"\bAIO\b(?:[\s,&]*\band\b[\s,&]*|[\s,&]+)+\bAIO\b")
_AIO_PANEL_SENTINELS = (
    "No positive structural signal was strong enough to lead this score.",
    "No blockers were captured for this score.",
    "No high-impact missing signal was identified.",
)


def _collapse_aio_runs(text: str) -> str:
    # "GEO and AEO" becomes "AIO and AIO"; collapse repeated AIO joined by
    # commas, "and", "&" or whitespace into a single AIO, then tidy any
    # separator the collapse left dangling.
    result = text
    previous = None
    while result != previous:
        previous = result
        result = _AIO_RUN_RE.sub("AIO", result)
        result = re.sub(r",\s*and\b", " and", result)
        result = re.sub(r"\band\s+and\b", "and", result)
        result = re.sub(r",\s*$", "", result)
    return result


def _publicize_aio_terms(value: Any) -> Any:
    if isinstance(value, str):
        return _collapse_aio_runs(_AIO_INTERNAL_TOKEN_RE.sub("AIO", value))
    if isinstance(value, Mapping):
        return {key: _publicize_aio_terms(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_publicize_aio_terms(item) for item in value]
    return value


def _dedupe_strings(values: Sequence[Any]) -> list[Any]:
    seen: set[Any] = set()
    result: list[Any] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _merge_panel_strings(values: Sequence[Any], sentinels: set[str]) -> list[Any]:
    deduped = _dedupe_strings(values)
    real = [value for value in deduped if value not in sentinels]
    return real or deduped[:1]


def _apply_aio_public_naming(
    sections: Mapping[str, Any], canonical_audit: Mapping[str, Any], language: str = "en"
) -> Mapping[str, Any]:
    public = _publicize_aio_terms(sections)
    aio_score = _float(_safe_get(canonical_audit, "metadata", "aio", "aio_score"))
    sentinels = {_l(language, text) for text in _AIO_PANEL_SENTINELS}

    why = public.get("why_this_score")
    if isinstance(why, dict):
        panels = why.get("items")
        if isinstance(panels, list):
            aio_index = next(
                (
                    index
                    for index, panel in enumerate(panels)
                    if isinstance(panel, dict) and panel.get("label") == "AIO"
                ),
                None,
            )
            if aio_index is not None:
                merged = [
                    panel
                    for panel in panels
                    if isinstance(panel, dict) and panel.get("label") == "AIO"
                ]
                implications = _dedupe_strings(
                    [
                        _text(panel.get("business_implication"))
                        for panel in merged
                        if _text(panel.get("business_implication"))
                    ]
                )
                items = list(panels[:aio_index])
                items.append(
                    {
                        "label": "AIO",
                        "score": aio_score,
                        "score_display": _score_display(aio_score)
                        if aio_score is not None
                        else None,
                        "tone": _score_tone(aio_score),
                        "strongest_signals": _merge_panel_strings(
                            [
                                signal
                                for panel in merged
                                for signal in _string_list(panel.get("strongest_signals"))
                            ],
                            sentinels,
                        ),
                        "top_blockers": _merge_panel_strings(
                            [
                                blocker
                                for panel in merged
                                for blocker in _string_list(panel.get("top_blockers"))
                            ],
                            sentinels,
                        ),
                        "missing_signals": _merge_panel_strings(
                            [
                                signal
                                for panel in merged
                                for signal in _string_list(panel.get("missing_signals"))
                            ],
                            sentinels,
                        ),
                        "business_implication": " ".join(implications),
                    }
                )
                items.extend(
                    panel
                    for panel in panels[aio_index:]
                    if not (isinstance(panel, dict) and panel.get("label") == "AIO")
                )
                why["items"] = items

    actions = public.get("top_action_items")
    if isinstance(actions, dict):
        for item in actions.get("items") or []:
            if isinstance(item, dict) and isinstance(item.get("affected_scores"), list):
                item["affected_scores"] = _dedupe_strings(item["affected_scores"])

    return public


def _build_structural_readiness(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, Any]:
    competitive = _mapping(canonical_audit.get("competitive"))
    summary = _mapping(competitive.get("summary"))
    insights = _mapping(competitive.get("insights"))
    scores = _mapping(canonical_audit.get("scores"))
    overall = _float(scores.get("overall"))
    target_rank = _int(summary.get("target_rank"))

    if target_rank == 1 and (overall is None or overall < 70):
        headline = _l(language, "Leading today but structurally fragile")
    elif target_rank is not None and target_rank > 1 and overall is not None and overall >= 70:
        headline = _l(language, "Structural readiness is ahead of current competitive position")
    elif overall is not None and overall < 60:
        headline = _l(
            language,
            "Competitive visibility is constrained by weak structural readiness",
        )
    else:
        headline = _l(
            language,
            "Competitive position and structural readiness are broadly aligned",
        )

    evidence = (
        _string_list(insights.get("target_risks"))
        or _string_list(insights.get("largest_gaps"))
        or [
            item["reason"]
            for item in _collect_penalties(canonical_audit, ("seo", "geo", "aeo"))[:3]
        ]
    )
    return {
        "headline": headline,
        "body": _l(
            language,
            "The competitive view should be interpreted alongside the deterministic readiness score. "
            "When rank and readiness diverge, the current lead is less defensible.",
        ),
        "evidence": evidence[:3],
    }


def _build_aeo_readiness_dashboard(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, Any]:
    aeo = _mapping(canonical_audit.get("aeo"))
    schema_health = _mapping(aeo.get("schema_health"))
    schema_coverage = _mapping(aeo.get("schema_coverage"))
    metrics = []
    for label, key, source in (
        ("LLM Schema Readiness", "llm_schema_readiness", aeo),
        ("Semantic Entity Density", "semantic_entity_density", aeo),
        ("Information Gain", "information_gain", aeo),
        ("Schema Health", "score", schema_health),
    ):
        value = _float(source.get(key))
        metrics.append(
            {
                "label": label,
                "value": value,
                "display_value": _score_display(value),
                "tone": _score_tone(value),
            }
        )
    return {
        "metrics": metrics,
        "detected_schema_types": _string_list(schema_health.get("detected_schema_types")),
        "missing_high_impact_types": _string_list(
            schema_health.get("missing_high_impact_types")
            or schema_coverage.get("missing_high_impact_types")
        ),
    }


def _build_metric_snapshot(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> list[dict[str, Any]]:
    geo = _mapping(canonical_audit.get("geo"))
    aeo = _mapping(canonical_audit.get("aeo"))
    metrics: list[dict[str, Any]] = []
    for label, value in (
        (
            _l(language, "Content Citability"),
            _float(geo.get("content_citability")) or _float(geo.get("napw_completeness")),
        ),
        (
            _l(language, "Source Authority"),
            _float(geo.get("source_authority")) or _float(geo.get("spatial_content")),
        ),
        (
            _l(language, "Entity Clarity"),
            _float(geo.get("entity_clarity")) or _float(geo.get("advanced_local_schema")),
        ),
        (_l(language, "Brand Citation"), _float(geo.get("brand_citation"))),
        (_l(language, "LLM Schema Readiness"), _float(aeo.get("llm_schema_readiness"))),
        (_l(language, "Semantic Entity Density"), _float(aeo.get("semantic_entity_density"))),
        (_l(language, "Information Gain"), _float(aeo.get("information_gain"))),
        (_l(language, "Snippet Formatting"), _float(aeo.get("snippet_formatting"))),
    ):
        metrics.append(
            {
                "label": label,
                "value": value,
                "display_value": _score_display(value),
                "tone": _score_tone(value),
            }
        )
    return metrics


def _build_charts_context(
    canonical_audit: Mapping[str, Any],
    *,
    branding_primary: str = "#6366F1",
    branding_secondary: str = "#1E293B",
    include_radar: bool = True,
    include_breakdown: bool = True,
    include_trend: bool = False,
    trend_points: Sequence[Mapping[str, Any]] | None = None,
    comparison_metrics: Mapping[str, object] | None = None,
    comparison_color: str | None = None,
    language: str = "en",
) -> dict[str, str]:
    charts: dict[str, str] = {}
    scores = _mapping(canonical_audit.get("scores"))
    geo = _mapping(canonical_audit.get("geo"))
    aeo = _mapping(canonical_audit.get("aeo"))

    if include_radar:
        radar_metrics = {
            _l(language, "SEO"): _float(scores.get("seo")) or 0,
            _l(language, "GEO"): _float(scores.get("geo")) or 0,
            _l(language, "AEO"): _float(scores.get("aeo")) or 0,
            _l(language, "Citability"): _float(geo.get("content_citability"))
            or _float(geo.get("napw_completeness"))
            or 0,
            _l(language, "Schema"): _float(aeo.get("llm_schema_readiness")) or 0,
            _l(language, "Info Gain"): _float(aeo.get("information_gain")) or 0,
        }
        svg = build_score_radar_svg(
            metrics=radar_metrics,
            primary_color=branding_primary,
            secondary_color=branding_secondary,
            comparison_metrics=comparison_metrics,
            comparison_color=comparison_color,
            language=language,
        )
        if svg:
            charts["radar_svg"] = _encode_inline_svg(svg)

    if include_breakdown:
        breakdown_metrics: list[tuple[str, object]] = []
        for label, key, fallback_key, source in (
            (_l(language, "Content Citability"), "content_citability", "napw_completeness", geo),
            (_l(language, "Source Authority"), "source_authority", "spatial_content", geo),
            (_l(language, "Entity Clarity"), "entity_clarity", "advanced_local_schema", geo),
            (_l(language, "LLM Schema"), "llm_schema_readiness", None, aeo),
            (_l(language, "Entity Density"), "semantic_entity_density", None, aeo),
            (_l(language, "Info Gain"), "information_gain", None, aeo),
            (_l(language, "Snippet Format"), "snippet_formatting", None, aeo),
        ):
            value = _float(source.get(key)) or (
                _float(source.get(fallback_key)) if fallback_key else None
            )
            if value is not None:
                breakdown_metrics.append((label, value))
        if breakdown_metrics:
            svg = build_breakdown_bar_chart_svg(
                metrics=breakdown_metrics,
                primary_color=branding_primary,
                secondary_color=branding_secondary,
                language=language,
            )
            if svg:
                charts["breakdown_bar_svg"] = _encode_inline_svg(svg)

    if include_trend and trend_points and len(trend_points) >= 2:
        formatted_points: list[dict[str, object]] = []
        for point in trend_points:
            if not isinstance(point, Mapping):
                continue
            formatted_points.append(
                {
                    "label": _text(
                        point.get("date_label") or _format_display_date(point.get("date"))
                    ),
                    "geo": _float(point.get("geo")) or 0,
                    "seo": _float(point.get("seo")) or 0,
                    "aeo": _float(point.get("aeo")) or 0,
                }
            )
        if len(formatted_points) >= 2:
            svg = build_trend_line_svg(
                points=formatted_points,
                primary_color=branding_primary,
                secondary_color=branding_secondary,
                tertiary_color="#F97316",
                language=language,
            )
            if svg:
                charts["trend_line_svg"] = _encode_inline_svg(svg)

    return charts


def _normalize_benchmark_columns(columns: Any, language: str = "en") -> list[dict[str, Any]]:
    if not isinstance(columns, Sequence) or isinstance(columns, (str, bytes, bytearray)):
        return [
            {"key": "rank", "label": _l(language, "Rank"), "type": "number"},
            {"key": "name", "label": _l(language, "Brand"), "type": "text"},
            {"key": "geo_visibility", "label": _l(language, "GEO Visibility"), "type": "number"},
            {"key": "aeo_score", "label": _l(language, "AEO Score"), "type": "number"},
            {"key": "entity_strength", "label": _l(language, "Entity Strength"), "type": "number"},
            {"key": "overall_score", "label": _l(language, "Overall Score"), "type": "number"},
        ]

    normalized: list[dict[str, Any]] = []
    for column in columns:
        if not isinstance(column, Mapping):
            continue
        key = _text(column.get("key"))
        if not key:
            continue
        normalized.append(
            {
                "key": key,
                "label": _text(column.get("label")) or _title_case(key),
                "type": _text(column.get("type"), default="text") or "text",
            }
        )
    return normalized or _normalize_benchmark_columns(None, language=language)


def _normalize_benchmark_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        return []

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        deltas = _mapping(row.get("deltas_vs_target"))
        name = _text(row.get("name"))
        if not name:
            continue
        normalized.append(
            {
                "rank": _int(row.get("rank")),
                "name": name,
                "is_target": bool(row.get("is_target")),
                "geo_visibility": _float(row.get("geo_visibility")),
                "aeo_score": _float(row.get("aeo_score")),
                "entity_strength": _float(row.get("entity_strength")),
                "overall_score": _float(row.get("overall_score")),
                "deltas_vs_target": {
                    "geo_visibility": _float(deltas.get("geo_visibility")),
                    "aeo_score": _float(deltas.get("aeo_score")),
                    "entity_strength": _float(deltas.get("entity_strength")),
                },
            }
        )
    return normalized


_BENCHMARK_METRIC_KEYS: tuple[str, ...] = (
    "geo_visibility",
    "aeo_score",
    "entity_strength",
)


def _benchmark_metric_value(value: Any) -> float | None:
    parsed = _float(value)
    if parsed is None:
        return None
    return round(max(0.0, min(100.0, parsed)), 2)


def _build_tolerant_benchmark_table(
    *,
    target_name: str,
    target_metrics: Mapping[str, float | None],
    competitors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Benchmark table that keeps an absent metric absent (SIGV2-1205).

    ``CompetitorBenchmarkService`` requires every metric to be numeric, so
    callers used to feed it ``0.0`` for a missing measurement and the PDF
    printed fabricated zeros, ranks and deltas. Here a metric that was never
    measured stays ``None``: the row is not ranked, gets no overall and no
    delta for inputs either side does not have. A genuinely measured ``0.0``
    still renders as zero.
    """
    metric_keys = _BENCHMARK_METRIC_KEYS

    def normalize_metrics(payload: Mapping[str, Any]) -> dict[str, float | None]:
        return {key: _benchmark_metric_value(payload.get(key)) for key in metric_keys}

    def normalize_name(name: Any) -> str:
        return " ".join(str(name or "").split())

    normalized_target_name = normalize_name(target_name)
    target_values = normalize_metrics(target_metrics)

    entries: list[dict[str, Any]] = [
        {"name": normalized_target_name, "is_target": True, "metrics": target_values}
    ]
    for competitor in competitors:
        competitor_name = normalize_name(competitor.get("name"))
        if not competitor_name or competitor_name.lower() == normalized_target_name.lower():
            continue
        entries.append(
            {
                "name": competitor_name,
                "is_target": False,
                "metrics": normalize_metrics(competitor),
            }
        )

    def is_measured(metrics: Mapping[str, float | None]) -> bool:
        return all(metrics.get(key) is not None for key in metric_keys)

    rows: list[dict[str, Any]] = []
    for entry in entries:
        metrics = entry["metrics"]
        measured = is_measured(metrics)
        overall = (
            round(sum(metrics[key] for key in metric_keys) / len(metric_keys), 2)
            if measured
            else None
        )
        deltas = {
            key: (
                round(metrics[key] - target_values[key], 2)
                if metrics[key] is not None and target_values[key] is not None
                else None
            )
            for key in metric_keys
        }
        rows.append(
            {
                "rank": None,
                "name": entry["name"],
                "is_target": entry["is_target"],
                **metrics,
                "overall_score": overall,
                "deltas_vs_target": deltas,
            }
        )

    measured_rows = sorted(
        (row for row in rows if row["overall_score"] is not None),
        key=lambda row: row["overall_score"],
        reverse=True,
    )
    unmeasured_rows = [row for row in rows if row["overall_score"] is None]
    for rank, row in enumerate(measured_rows, start=1):
        row["rank"] = rank
    ordered_rows = measured_rows + unmeasured_rows

    return {
        "columns": [
            {"key": "rank", "label": "Rank", "type": "number"},
            {"key": "name", "label": "Brand", "type": "text"},
            {"key": "geo_visibility", "label": "GEO Visibility", "type": "score"},
            {"key": "aeo_score", "label": "AEO Score", "type": "score"},
            {"key": "entity_strength", "label": "Entity Strength", "type": "score"},
            {"key": "overall_score", "label": "Overall", "type": "score"},
        ],
        "rows": ordered_rows,
        "summary": {
            "target": normalized_target_name,
            "competitor_count": max(0, len(ordered_rows) - 1),
            "target_rank": next(
                (row["rank"] for row in ordered_rows if row["is_target"]),
                None,
            ),
        },
    }


def _derive_benchmark_from_competitors(canonical_audit: Mapping[str, Any]) -> dict[str, Any] | None:
    target = _mapping(canonical_audit.get("target"))
    scores = _mapping(canonical_audit.get("scores"))
    competitors = canonical_audit.get("competitors")
    target_name = _text(target.get("name"))
    if not target_name or not isinstance(competitors, Sequence):
        return None

    return _build_tolerant_benchmark_table(
        target_name=target_name,
        target_metrics={
            "geo_visibility": _float(scores.get("geo")),
            "aeo_score": _float(scores.get("aeo")),
            "entity_strength": _entity_strength_score(canonical_audit),
        },
        competitors=[
            {
                "name": _text(item.get("name")),
                "geo_visibility": _float(item.get("geo_visibility")),
                "aeo_score": _float(item.get("aeo_score")),
                "entity_strength": _float(item.get("entity_strength")),
            }
            for item in competitors
            if isinstance(item, Mapping) and _text(item.get("name"))
        ],
    )


def _build_battle_leaderboard(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, Any]:
    benchmark = _mapping(_safe_get(canonical_audit, "metadata", "competitor_summary", "benchmark"))
    derived = benchmark or (_derive_benchmark_from_competitors(canonical_audit) or {})
    columns = _normalize_benchmark_columns(derived.get("columns"), language=language)
    rows = _normalize_benchmark_rows(derived.get("rows"))
    target_name = _text(_safe_get(canonical_audit, "target", "name"))
    return {
        "columns": columns,
        "rows": rows,
        "target_name": target_name,
    }


def _resolve_top_level_deltas(
    canonical_audit: Mapping[str, Any],
    leaderboard_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float | None]:
    raw_deltas = _mapping(canonical_audit.get("deltas_vs_target"))
    resolved = {
        "geo_visibility": _float(raw_deltas.get("geo_visibility")),
        "aeo_score": _float(raw_deltas.get("aeo_score")),
        "entity_strength": _float(raw_deltas.get("entity_strength")),
    }
    if any(value is not None for value in resolved.values()):
        return resolved

    competitor_rows = [row for row in leaderboard_rows if not bool(row.get("is_target"))]
    competitor_rows.sort(
        key=lambda item: (_priority_value(item.get("rank")), item.get("name", "").lower())
    )
    if not competitor_rows:
        return resolved
    first_row = competitor_rows[0]
    deltas = _mapping(first_row.get("deltas_vs_target"))
    return {
        "geo_visibility": _float(deltas.get("geo_visibility")),
        "aeo_score": _float(deltas.get("aeo_score")),
        "entity_strength": _float(deltas.get("entity_strength")),
    }


def _build_delta_analysis(
    canonical_audit: Mapping[str, Any],
    leaderboard_rows: Sequence[Mapping[str, Any]],
    language: str = "en",
) -> list[dict[str, Any]]:
    deltas = _resolve_top_level_deltas(canonical_audit, leaderboard_rows)
    items: list[dict[str, Any]] = []
    for label, key in (
        (_l(language, "GEO Visibility"), "geo_visibility"),
        (_l(language, "AEO Score"), "aeo_score"),
    ):
        value = deltas.get(key)
        if value is None:
            continue
        if value > 0:
            stance = _l(language, "Competitor lead")
        elif value < 0:
            stance = _l(language, "Target lead")
        else:
            stance = _l(language, "Parity")
        items.append(
            {
                "label": label,
                "value": value,
                "display_value": _format_signed_delta(value, suffix=" pts"),
                "stance": stance,
                "tone": "critical" if value > 0 else "strong" if value < 0 else "muted",
            }
        )
    return items


def _build_entity_share_of_voice(canonical_audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    entities = _string_list(canonical_audit.get("entities"))
    rows: list[dict[str, Any]] = []
    for index, entity in enumerate(entities[:12]):
        rows.append(
            {
                "name": entity,
                "weight": max(36, 96 - (index * 6)),
            }
        )
    return rows


def _build_battle_comparison_metrics(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, object] | None:
    """Build comparison metrics for the first competitor in the leaderboard."""
    benchmark = _mapping(_safe_get(canonical_audit, "metadata", "competitor_summary", "benchmark"))
    rows = _normalize_benchmark_rows(benchmark.get("rows"))
    competitor_rows = [row for row in rows if not bool(row.get("is_target"))]
    if not competitor_rows:
        competitors = canonical_audit.get("competitors")
        if isinstance(competitors, Sequence):
            for item in competitors:
                if isinstance(item, Mapping) and _text(item.get("name")):
                    return _measured_comparison_metrics(item, language=language)
        return None
    return _measured_comparison_metrics(competitor_rows[0], language=language)


def _measured_comparison_metrics(
    row: Mapping[str, Any], *, language: str
) -> dict[str, object] | None:
    """Comparison radar values built only from measured inputs (SIGV2-1205).

    The previous version padded SEO/NAPW/Schema/Info Gain with literal zeros,
    so the PDF plotted axes the audit never measured. Absent metrics are
    omitted rather than fabricated.
    """
    metrics: dict[str, object] = {}
    for label, key in (
        (_l(language, "SEO"), "seo_score"),
        (_l(language, "GEO"), "geo_visibility"),
        (_l(language, "AEO"), "aeo_score"),
    ):
        value = _float(row.get(key))
        if value is not None:
            metrics[label] = value
    return metrics or None


def _build_competitive_trend_timeline(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> dict[str, Any]:
    raw_timeline = _mapping(
        _safe_get(canonical_audit, "metadata", "competitor_summary", "trend_timeline")
    )
    competitors_raw = raw_timeline.get("competitors")
    if not isinstance(competitors_raw, Sequence):
        return {"enabled": False, "competitors": []}

    project_label = _text(raw_timeline.get("project_label"), default=_l(language, "Target"))
    coverage_start = _text(raw_timeline.get("coverage_start"))
    coverage_end = _text(raw_timeline.get("coverage_end"))
    competitors: list[dict[str, Any]] = []
    for entry in competitors_raw:
        if not isinstance(entry, Mapping):
            continue

        def _normalize_points(value: Any) -> list[dict[str, Any]]:
            normalized: list[dict[str, Any]] = []
            if not isinstance(value, Sequence):
                return normalized
            for item in value:
                if not isinstance(item, Mapping):
                    continue
                date_label = _format_display_date(item.get("date"))
                normalized.append(
                    {
                        "date_label": date_label or _l(language, "Unknown date"),
                        "overall_display": _score_display(_float(item.get("overall"))),
                        "seo_display": _score_display(_float(item.get("seo"))),
                        "geo_display": _score_display(_float(item.get("geo"))),
                        "aeo_display": _score_display(_float(item.get("aeo"))),
                    }
                )
            return normalized[-6:]

        project_points = _normalize_points(entry.get("project_points"))
        competitor_points = _normalize_points(entry.get("competitor_points"))
        if not project_points and not competitor_points:
            continue

        project_latest = _mapping(entry.get("project_latest"))
        competitor_latest = _mapping(entry.get("competitor_latest"))
        competitors.append(
            {
                "name": _text(entry.get("name"), default=_l(language, "Competitor")),
                "project_label": project_label,
                "project_points": project_points,
                "competitor_points": competitor_points,
                "project_latest_overall": _score_display(_float(project_latest.get("overall"))),
                "competitor_latest_overall": _score_display(
                    _float(competitor_latest.get("overall"))
                ),
                "project_delta_overall": _format_signed_delta(
                    _float(entry.get("project_delta_overall")), suffix=" pts"
                ),
                "competitor_delta_overall": _format_signed_delta(
                    _float(entry.get("competitor_delta_overall")), suffix=" pts"
                ),
            }
        )

    return {
        "enabled": bool(competitors),
        "project_label": project_label,
        "coverage_start": _format_display_date(coverage_start) if coverage_start else None,
        "coverage_end": _format_display_date(coverage_end) if coverage_end else None,
        "audit_count": _int(raw_timeline.get("audit_count")),
        "competitors": competitors,
    }


def _build_geo_metrics(
    canonical_audit: Mapping[str, Any], language: str = "en"
) -> list[dict[str, Any]]:
    geo = _mapping(canonical_audit.get("geo"))
    items: list[dict[str, Any]] = []
    for label, key, fallback_key in (
        (_l(language, "Content Citability"), "content_citability", "napw_completeness"),
        (_l(language, "Source Authority"), "source_authority", "spatial_content"),
        (_l(language, "Entity Clarity"), "entity_clarity", "advanced_local_schema"),
        (_l(language, "Brand Citation"), "brand_citation", None),
        (_l(language, "GBP Completeness"), "gbp_completeness", None),
        (_l(language, "Local Link Authority"), "local_link_authority", None),
        (_l(language, "Review Signal Strength"), "review_signal_strength", None),
    ):
        value = _float(geo.get(key)) or (_float(geo.get(fallback_key)) if fallback_key else None)
        if value is not None:
            items.append(
                {
                    "label": label,
                    "value": value,
                    "display_value": _score_display(value),
                    "tone": _score_tone(value),
                }
            )
    return items


def _build_score_breakdown(canonical_audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    scores = _mapping(canonical_audit.get("scores"))
    groups: list[dict[str, Any]] = []
    for domain, key in (("SEO", "seo"), ("GEO", "geo"), ("AEO", "aeo")):
        breakdown = _mapping(scores.get(f"{key}_breakdown"))
        components_raw = _mapping(breakdown.get("components"))
        if not components_raw:
            continue
        components = [
            {
                "label": _humanize_component_key(component_key),
                "value": value,
                "display_value": _score_display(value),
                "tone": _score_tone(value),
            }
            for component_key, raw_value in sorted(
                components_raw.items(),
                key=lambda item: _float(item[1]) or 0.0,
                reverse=True,
            )
            if (value := _float(raw_value)) is not None
        ]
        penalties = _normalize_penalties(domain, breakdown.get("penalties"))[:3]
        groups.append(
            {
                "domain": domain,
                "components": components,
                "penalties": penalties,
            }
        )
    return groups


def _build_standard_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    is_brand_without_url: bool = False,
    language: str = "en",
) -> dict[str, Any]:
    scores = _mapping(canonical_audit.get("scores"))
    cards = [
        {
            "label": label,
            "value": _float(scores.get(key)),
            "display_value": _score_display(_float(scores.get(key))),
            "tone": _score_tone(_float(scores.get(key))),
        }
        for label, key in (("SEO", "seo"), ("GEO", "geo"), ("AEO", "aeo"))
    ]
    return {
        "is_brand_without_url": is_brand_without_url,
        "trust_banner": _build_trust_banner(canonical_audit, language=language),
        "executive_dashboard": {
            "overall": {
                "label": "Overall",
                "value": _float(scores.get("overall")),
                "display_value": _score_display(_float(scores.get("overall"))),
                "tone": _score_tone(_float(scores.get("overall"))),
            },
            "cards": cards,
        },
        "why_this_score": {
            "items": _build_why_this_score_panels(canonical_audit, language=language),
        },
        "score_breakdown": {
            "items": _build_score_breakdown(canonical_audit),
        },
        "geo_metrics": {
            "items": _build_geo_metrics(canonical_audit, language=language),
        },
        "aeo_readiness_dashboard": _build_aeo_readiness_dashboard(
            canonical_audit, language=language
        ),
        "strategic_interpretation": {
            "body": _text(_mapping(narrative.get("executive_summary")).get("text"))
            or _text(_mapping(narrative.get("market_dominance_blueprint_block")).get("text"))
            or _l(
                language,
                "AI visibility signals were captured, but a strategic interpretation was not available.",
            ),
            "confidence_label": _text(
                _mapping(narrative.get("executive_summary")).get("confidence_label"),
                default=_l(language, "Low"),
            ),
            "requires_review": bool(
                _mapping(narrative.get("executive_summary")).get("requires_review")
            ),
        },
        "critical_blockers": {
            "items": _collect_penalties(
                canonical_audit, ("geo", "aeo") if is_brand_without_url else ("seo", "geo", "aeo")
            )[:10],
        },
        "top_action_items": {
            "items": _build_action_items(canonical_audit, language=language)[:8],
        },
    }


def _action_items_for_dimensions(
    canonical_audit: Mapping[str, Any],
    dimensions: Sequence[str],
    language: str = "en",
) -> list[dict[str, Any]]:
    wanted = {str(dimension).strip().lower() for dimension in dimensions}
    items: list[dict[str, Any]] = []
    for item in _build_action_items(canonical_audit, language=language):
        affected = item.get("affected_scores")
        if isinstance(affected, str):
            tokens = affected.split(",")
        elif isinstance(affected, Sequence):
            tokens = [str(value) for value in affected]
        else:
            tokens = []
        if wanted & {token.strip().lower() for token in tokens if token.strip()}:
            items.append(item)
    return items


def _strategic_interpretation(narrative: Mapping[str, Any], language: str = "en") -> dict[str, Any]:
    return {
        "body": _text(_mapping(narrative.get("executive_summary")).get("text"))
        or _text(_mapping(narrative.get("market_dominance_blueprint_block")).get("text"))
        or _l(
            language,
            "AI visibility signals were captured, but a strategic interpretation was not available.",
        ),
        "confidence_label": _text(
            _mapping(narrative.get("executive_summary")).get("confidence_label"),
            default=_l(language, "Low"),
        ),
        "requires_review": bool(
            _mapping(narrative.get("executive_summary")).get("requires_review")
        ),
    }


def _build_aio_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    is_brand_without_url: bool = False,
    language: str = "en",
) -> dict[str, Any]:
    aio = _mapping(_safe_get(canonical_audit, "metadata", "aio"))
    components = _mapping(aio.get("components"))
    aio_score = _float(aio.get("aio_score"))
    component_cards = [
        {
            "label": label,
            "value": _float(components.get(key)),
            "display_value": _score_display(_float(components.get(key))),
            "tone": _score_tone(_float(components.get(key))),
        }
        for label, key in (("AEO", "aeo"), ("GEO", "geo"))
    ]
    return {
        "is_brand_without_url": is_brand_without_url,
        "aio_result": {
            "title": _l(language, "AIO Score"),
            "label": "AIO",
            "value": aio_score,
            "display_value": _score_display(aio_score),
            "tone": _score_tone(aio_score),
            "scope": _text(aio.get("scope")),
            # ``scope`` carries a machine identifier today (``website_and_brand``);
            # map it to a sentence and pass through any human-readable value,
            # dropping the line when we cannot describe it safely.
            "scope_label": {
                "website_and_brand": _l(language, "This score covers your website and brand.")
            }.get(
                _text(aio.get("scope")),
                None if "_" in _text(aio.get("scope") or "") else _text(aio.get("scope")),
            ),
            "summary": _text(aio.get("summary")),
            "components": component_cards,
        },
        "why_this_score": {
            "items": [
                panel
                for panel in _build_why_this_score_panels(canonical_audit, language=language)
                if panel.get("label") in {"AEO", "GEO"}
            ],
        },
        "score_breakdown": {
            "items": [
                group
                for group in _build_score_breakdown(canonical_audit)
                if group.get("domain") in {"AEO", "GEO"}
            ],
        },
        "geo_metrics": {
            "items": _build_geo_metrics(canonical_audit, language=language),
        },
        "aeo_readiness_dashboard": _build_aeo_readiness_dashboard(
            canonical_audit, language=language
        ),
        "critical_blockers": {
            "items": _collect_penalties(canonical_audit, ("aeo", "geo"))[:10],
        },
        "top_action_items": {
            "items": _action_items_for_dimensions(
                canonical_audit, ("aeo", "geo"), language=language
            )[:8],
        },
        "trust_banner": _build_trust_banner(canonical_audit, language=language),
        "strategic_interpretation": _strategic_interpretation(narrative, language=language),
    }


_SEO_FOCUS_GROUPS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Technical", "pdf.seo_focus_technical", ("technical_seo", "security_accessibility")),
    ("On-Page", "pdf.seo_focus_on_page", ("onpage_content", "eeat_trust")),
    ("Performance", "pdf.seo_focus_performance", ("core_web_vitals",)),
)


def _build_seo_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    is_brand_without_url: bool = False,
    language: str = "en",
) -> dict[str, Any]:
    scores = _mapping(canonical_audit.get("scores"))
    seo_score = _float(scores.get("seo"))
    components = _mapping(_mapping(scores.get("seo_breakdown")).get("components"))

    def _component_card(component_key: str, label: str) -> dict[str, Any]:
        value = _float(components.get(component_key))
        return {
            "label": label,
            "value": value,
            "display_value": _score_display(value),
            "tone": _score_tone(value),
        }

    focus_groups: list[dict[str, Any]] = []
    grouped_keys: set[str] = set()
    for label_default, label_key, component_keys in _SEO_FOCUS_GROUPS:
        items = [
            _component_card(component_key, _humanize_component_key(component_key))
            for component_key in component_keys
            if _float(components.get(component_key)) is not None
        ]
        grouped_keys.update(component_keys)
        if items:
            focus_groups.append(
                {
                    "label": get_report_label(language, label_key, default=label_default),
                    "items": items,
                }
            )
    other_items = [
        _component_card(component_key, _humanize_component_key(component_key))
        for component_key in components
        if component_key not in grouped_keys and _float(components.get(component_key)) is not None
    ]
    if other_items:
        focus_groups.append(
            {
                "label": get_report_label(
                    language, "pdf.seo_focus_other", default=_l(language, "Additional Signals")
                ),
                "items": other_items,
            }
        )

    return {
        "is_brand_without_url": is_brand_without_url,
        "seo_overview": {
            "title": get_report_label(
                language, "pdf.seo_overview_title", default=_l(language, "SEO Score")
            ),
            "score": {
                "label": "SEO",
                "value": seo_score,
                "display_value": _score_display(seo_score),
                "tone": _score_tone(seo_score),
            },
        },
        "seo_focus": {"groups": focus_groups},
        "why_this_score": {
            "items": [
                panel
                for panel in _build_why_this_score_panels(canonical_audit, language=language)
                if panel.get("label") == "SEO"
            ],
        },
        "score_breakdown": {
            "items": [
                group
                for group in _build_score_breakdown(canonical_audit)
                if group.get("domain") == "SEO"
            ],
        },
        "critical_blockers": {
            "items": _collect_penalties(canonical_audit, ("seo",))[:10],
        },
        "top_action_items": {
            "items": _action_items_for_dimensions(canonical_audit, ("seo",), language=language)[:8],
        },
        "trust_banner": _build_trust_banner(canonical_audit, language=language),
        "strategic_interpretation": _strategic_interpretation(narrative, language=language),
    }


def _build_battle_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    leaderboard = _build_battle_leaderboard(canonical_audit, language=language)
    return {
        "trust_banner": _build_trust_banner(canonical_audit),
        "battlefield_leaderboard": leaderboard,
        "competitive_trend_timeline": _build_competitive_trend_timeline(
            canonical_audit, language=language
        ),
        "delta_analysis": {
            "items": _build_delta_analysis(canonical_audit, leaderboard["rows"], language=language),
        },
        "competitive_position": _build_structural_readiness(canonical_audit, language=language),
        "entity_share_of_voice": {
            "items": _build_entity_share_of_voice(canonical_audit),
        },
        "strategic_conclusion": {
            "body": _text(_mapping(narrative.get("market_dominance_blueprint_block")).get("text"))
            or _text(_mapping(narrative.get("executive_summary")).get("text"))
            or _l(
                language,
                "Competitive positioning signals are available, but no strategic conclusion was generated.",
            ),
            "confidence_label": _text(
                _mapping(narrative.get("market_dominance_blueprint_block")).get("confidence_label"),
                default=_l(language, "Low"),
            ),
        },
    }


def _build_branded_sections(
    canonical_audit: Mapping[str, Any],
    branding: Mapping[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    action_items = _build_action_items(canonical_audit, language=language)
    return {
        "trust_banner": _build_trust_banner(canonical_audit),
        "agency_cover": {
            "agency_name": _text(branding.get("agency_name")),
            "client_name": _text(_safe_get(canonical_audit, "target", "name")),
            "target_url": _text(_safe_get(canonical_audit, "target", "url")),
        },
        "aeo_readiness_dashboard": _build_aeo_readiness_dashboard(
            canonical_audit, language=language
        ),
        "high_impact_ai_blockers": {
            "title": _l(language, "High-Impact AI Blockers"),
            "items": _collect_penalties(canonical_audit, ("aeo", "geo", "seo"))[:8],
        },
        "roadmap": {
            "groups": _group_action_items(action_items),
        },
        "strategic_interpretation": {
            "body": _text(
                _mapping(_mapping(canonical_audit.get("narrative")).get("executive_summary")).get(
                    "text"
                )
            )
            or _l(language, "Strategic interpretation was not available for this report."),
        },
    }


def _build_whitelabel_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    return {
        "trust_banner": _build_trust_banner(canonical_audit, language=language),
        "strategic_intelligence_grid": {
            "items": list(narrative.get("strategic_intelligence_grid") or []),
        },
        "deep_technical_breakdown": {
            "items": _collect_penalties(canonical_audit, ("seo", "geo", "aeo"))[:12],
        },
        "metrics": {
            "items": _build_metric_snapshot(canonical_audit, language=language),
        },
    }


_WITHHELD_SECTION_LABELS: dict[str, tuple[str, str]] = {
    # section id -> (report-i18n key, English default)
    "competitors": ("pdf.withheld_section.competitors", "Competitors"),
    "entities": ("pdf.withheld_section.entities", "Entities"),
    "predictive_intent": ("pdf.withheld_section.predictive_intent", "Predictive Intent"),
    "semantic_graph": ("pdf.withheld_section.semantic_graph", "Semantic Graph"),
    "advanced_reporting": ("pdf.withheld_section.advanced_reporting", "Advanced Reporting"),
    "brand_integrity": ("pdf.withheld_section.brand_integrity", "Brand Integrity"),
    "eeat_trust": ("pdf.withheld_section.eeat_trust", "E-E-A-T Trust"),
}


def _build_withheld_sections(
    canonical_audit: Mapping[str, Any],
    language: str,
    *,
    white_label: bool = False,
) -> list[dict[str, Any]]:
    """Project locked_sections into public-safe withheld placeholders.

    Exposes only the section id (as a label), the withheld state, the
    customer-facing detail and the required plan label. Capability keys, raw
    plan ids, lock origins and counts are deliberately not projected.

    ``white_label=True`` (SIGV2-1276) strips all plan/upsell wording for a
    report handed to the agency's client: the upgrade hint is dropped and the
    detail falls back to the neutral "not included in this report" string -
    payload-authored details may name plans and are not trusted here.
    """
    locked_sections = _mapping(_safe_get(canonical_audit, "metadata", "locked_sections"))
    default_detail = get_report_label(
        language,
        "pdf.withheld_section_default_detail_white_label",
        default="This section is not included in this report.",
    )
    if not white_label:
        default_detail = get_report_label(
            language,
            "pdf.withheld_section_default_detail",
            default="This section is not included on the current plan.",
        )
    withheld: list[dict[str, Any]] = []
    for section_key in sorted(locked_sections):
        entry = _mapping(locked_sections.get(section_key))
        if not bool(entry.get("is_locked")):
            continue
        section_id = _text(section_key)
        label_key, label_default = _WITHHELD_SECTION_LABELS.get(
            section_id,
            ("pdf.withheld_section.unknown", section_id.replace("_", " ").title() or "Section"),
        )
        required_plan_label = _text(entry.get("required_plan_label")) or None
        withheld.append(
            {
                "section": section_id,
                "section_label": get_report_label(language, label_key, default=label_default),
                "withheld": True,
                "detail": default_detail
                if white_label
                else (_text(entry.get("detail")) or default_detail),
                "required_plan_label": required_plan_label if not white_label else None,
                "upgrade_hint": get_report_label(
                    language,
                    "pdf.withheld_section_upgrade_hint",
                    default="Available on the {plan} plan",
                    params={"plan": required_plan_label},
                )
                if required_plan_label and not white_label
                else None,
            }
        )
    return withheld


def _build_report_labels(language: str) -> dict[str, str]:
    return {
        "generated_on": get_report_label(language, "pdf.generated_on", default="Generated"),
        "target": get_report_label(language, "pdf.target_label", default="Target"),
        "score": get_report_label(language, "pdf.score_label", default="Score"),
        "priority": _l(language, "Priority"),
        "category": _l(language, "Category"),
        "impact": _l(language, "Impact"),
        "client": _l(language, "Client"),
        "report": _l(language, "Report"),
        "page_label": get_report_label(language, "pdf.page_label", default="Page"),
        "withheld_sections_title": get_report_label(
            language,
            "pdf.withheld_sections_title",
            default="Sections not included in this report",
        ),
    }


def _report_suite_payload(canonical_audit: Mapping[str, Any], key: str) -> dict[str, Any]:
    return _mapping(_safe_get(canonical_audit, "metadata", "report_suite", key))


def _build_context_page(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    *,
    report_kind: str,
    language: str = "en",
    suppress_financial_context: bool = False,
) -> dict[str, Any]:
    target = _mapping(canonical_audit.get("target"))
    site = _mapping(canonical_audit.get("site"))
    scores = _mapping(canonical_audit.get("scores"))
    title = _l(language, "Audit Context")
    subtitle = (
        _text(_mapping(narrative.get("executive_summary")).get("text"))
        or _text(_mapping(narrative.get("market_dominance_blueprint_block")).get("text"))
        or _l(language, "Report context was assembled from persisted audit evidence.")
    )
    cards = [
        {
            "label": _l(language, "Target"),
            "value": _text(
                target.get("name") or target.get("url"), default=_l(language, "Audit target")
            ),
        },
        {
            "label": _l(language, "Target URL"),
            "value": _text(target.get("url"), default=_l(language, "Not provided")),
        },
        {
            "label": _l(language, "Market"),
            "value": _text(site.get("market"), default=_l(language, "Global")),
        },
        {
            "label": _l(language, "Overall score"),
            "value": _score_display(_float(scores.get("overall"))),
        },
    ]
    lists: list[dict[str, Any]] = []
    highlights: list[str] = []

    if report_kind == "executive":
        blueprint = _report_suite_payload(canonical_audit, "executive_blueprint")
        title = _l(language, "Diagnostic Blueprint")
        subtitle = _l(
            language,
            "Persisted project context, connected data sources, and target metadata "
            "anchor the executive interpretation in server-side evidence.",
        )
        cards = [
            {
                "label": _l(language, "Target"),
                "value": _text(blueprint.get("target_name"), default=_l(language, "Audit target")),
            },
            {
                "label": _l(language, "Target URL"),
                "value": _text(blueprint.get("target_url"), default=_l(language, "Not provided")),
            },
            {
                "label": _l(language, "Target type"),
                "value": _title_case(_text(blueprint.get("target_type"), default="website")),
            },
            {
                "label": _l(language, "Project"),
                "value": _text(
                    blueprint.get("project_name"), default=_l(language, "Standalone audit")
                ),
            },
        ]
        active_sources = [
            f"{_text(item.get('label'))} ({_text(item.get('mode'))})"
            for item in blueprint.get("active_sources", [])
            if isinstance(item, Mapping) and _text(item.get("label"))
        ]
        icp_roles = _string_list(blueprint.get("icp_roles"))
        supporting_references = [
            f"{_text(item.get('label'))}: {_text(item.get('value'))}"
            for item in blueprint.get("supporting_references", [])
            if isinstance(item, Mapping) and _text(item.get("value"))
        ]
        if active_sources:
            lists.append({"label": _l(language, "Connected sources"), "items": active_sources})
        if icp_roles:
            lists.append({"label": _l(language, "ICP roles"), "items": icp_roles})
        if _text(blueprint.get("usp")):
            lists.append(
                {
                    "label": _l(language, "Unique selling proposition"),
                    "items": [_text(blueprint.get("usp"))],
                }
            )
        if supporting_references:
            lists.append(
                {"label": _l(language, "Supporting references"), "items": supporting_references[:6]}
            )
        highlights = _string_list(blueprint.get("source_warnings"))
    elif report_kind == "project":
        project_report = _report_suite_payload(canonical_audit, "project_report")
        title = _l(language, "Project Context")
        subtitle = _l(
            language,
            "Score movement and remediation state are derived from persisted project audits and actions.",
        )
        cards = [
            {
                "label": _l(language, "Coverage start"),
                "value": _format_coverage_date(project_report.get("coverage_start"), language),
            },
            {
                "label": _l(language, "Coverage end"),
                "value": _format_coverage_date(project_report.get("coverage_end"), language),
            },
            {
                "label": _l(language, "Audits included"),
                "value": str(_int(project_report.get("audit_count")) or 0),
            },
            {
                "label": _l(language, "Overall delta"),
                "value": _format_signed_delta(
                    _float(_mapping(project_report.get("delta")).get("overall")), suffix=" pts"
                ),
            },
        ]
        movement = _mapping(project_report.get("task_movement"))
        lists = [
            {
                "label": _l(language, "Action progress"),
                "items": [
                    f"{_l(language, 'New audit-linked actions')}: {_int(movement.get('new')) or 0}",
                    f"{_l(language, 'Resolved actions')}: {_int(movement.get('resolved')) or 0}",
                    f"{_l(language, 'Validated actions')}: {_int(movement.get('validated')) or 0}",
                ],
            }
        ]
        highlights = _string_list(project_report.get("remaining_issues"))
    elif report_kind == "financial" and not suppress_financial_context:
        financial_report = _report_suite_payload(canonical_audit, "financial_report")
        title = _l(language, "Financial Context")
        subtitle = _text(financial_report.get("redaction_reason")) or _l(
            language,
            "Project credit consumption is summarized from persisted audit jobs and budget windows.",
        )
        cards = [
            {
                "label": _l(language, "Ledger rows"),
                "value": str(_int(financial_report.get("run_count")) or 0),
            },
            {
                "label": _l(language, "Disclosure"),
                "value": _l(language, "Hidden")
                if bool(financial_report.get("redacted"))
                else _l(language, "Visible"),
            },
        ]
        if bool(financial_report.get("redacted")):
            highlights = [_text(financial_report.get("redaction_reason"))]
    elif report_kind == "competitors":
        trend_timeline = _build_competitive_trend_timeline(canonical_audit, language=language)
        title = _l(language, "Competitive Context")
        subtitle = _l(
            language,
            "Benchmark and historical movement are assembled from persisted project competitor snapshots.",
        )
        cards = [
            {
                "label": _l(language, "Target"),
                "value": _text(
                    target.get("name") or target.get("url"), default=_l(language, "Target")
                ),
            },
            {
                "label": _l(language, "Tracked competitors"),
                "value": str(len(trend_timeline.get("competitors", []))),
            },
            {
                "label": _l(language, "Coverage start"),
                "value": _text(
                    trend_timeline.get("coverage_start"), default=_l(language, "Latest snapshot")
                ),
            },
            {
                "label": _l(language, "Coverage end"),
                "value": _text(
                    trend_timeline.get("coverage_end"), default=_l(language, "Latest snapshot")
                ),
            },
        ]
        highlights = [
            f"{item.get('name')} latest overall {item.get('competitor_latest_overall')}"
            for item in trend_timeline.get("competitors", [])[:3]
            if isinstance(item, Mapping)
        ]

    return {
        "title": title,
        "subtitle": subtitle,
        "cards": cards,
        "lists": lists,
        "highlights": highlights,
    }


def _build_integrity_page(
    canonical_audit: Mapping[str, Any],
    *,
    report_kind: str,
    hide_credit_cost: bool,
    language: str = "en",
    white_label: bool = False,
) -> dict[str, Any]:
    trust_banner = _build_trust_banner(canonical_audit, language=language)
    review_notes = list(trust_banner.get("warnings", []))
    degraded_note = _text(trust_banner.get("degraded_note"))
    if degraded_note:
        review_notes.append(degraded_note)

    disclosure_items: list[dict[str, Any]] = []
    if not hide_credit_cost:
        if report_kind == "financial":
            financial_report = _report_suite_payload(canonical_audit, "financial_report")
            if not bool(financial_report.get("redacted")):
                disclosure_items = [
                    {
                        "label": _l(language, "Total consumed"),
                        "value": f"{_int(financial_report.get('total_consumed_credits')) or 0} credits",
                    },
                    {
                        "label": _l(language, "Runs recorded"),
                        "value": str(_int(financial_report.get("run_count")) or 0),
                    },
                ]
        else:
            metadata = _mapping(canonical_audit.get("metadata"))
            disclosure_items = [
                {
                    "label": _l(language, "Estimated credits"),
                    "value": str(_int(metadata.get("estimated_credit_cost")) or 0),
                },
                {
                    "label": _l(language, "Consumed credits"),
                    "value": str(_int(metadata.get("consumed_credit_cost")) or 0),
                },
            ]
            disclosure_items = [item for item in disclosure_items if item["value"] not in {"0", ""}]

    return {
        "title": _l(language, "Integrity & Confidence Certificate"),
        # SIGV2-1276: white-label output must not use the word "disclosure" -
        # it implies withheld commercial data exists inside the document.
        "summary": (
            _l(
                language,
                "This page summarizes grounding coverage and blocked-claim outcomes.",
            )
            if white_label
            else _l(
                language,
                "This page summarizes grounding coverage, blocked-claim outcomes, and the final disclosure state.",
            )
        ),
        "certificate_items": trust_banner.get("integrity_items", []),
        "blocked_buckets": trust_banner.get("blocked_buckets", []),
        "review_notes": review_notes,
        "financial_disclosure": {
            "enabled": bool(disclosure_items),
            "items": disclosure_items,
        },
    }


def _build_executive_sections(
    canonical_audit: Mapping[str, Any],
    narrative: Mapping[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    scores = _mapping(canonical_audit.get("scores"))
    action_items = _build_action_items(canonical_audit)
    return {
        "executive_dashboard": {
            "overall": {
                "label": "Overall",
                "value": _float(scores.get("overall")),
                "display_value": _score_display(_float(scores.get("overall"))),
                "tone": _score_tone(_float(scores.get("overall"))),
            },
            "cards": _build_score_cards(
                canonical_audit, report_kind="executive", language=language
            ),
        },
        "strategic_intelligence_grid": {
            "items": list(narrative.get("strategic_intelligence_grid") or []),
        },
        "score_breakdown": {
            "items": _build_score_breakdown(canonical_audit),
        },
        "aeo_readiness_dashboard": _build_aeo_readiness_dashboard(
            canonical_audit, language=language
        ),
        "high_impact_ai_blockers": {
            "items": _collect_penalties(canonical_audit, ("seo", "geo", "aeo"))[:10],
        },
        "top_action_items": {
            "items": action_items[:8],
        },
        "strategic_interpretation": {
            "body": _text(_mapping(narrative.get("executive_summary")).get("text"))
            or _text(_mapping(narrative.get("market_dominance_blueprint_block")).get("text"))
            or _l(language, "Strategic interpretation was not available for this report."),
            "confidence_label": _text(
                _mapping(narrative.get("executive_summary")).get("confidence_label"),
                default=_l(language, "Low"),
            ),
        },
    }


def _build_project_sections(
    canonical_audit: Mapping[str, Any],
    language: str = "en",
) -> dict[str, Any]:
    project_report = _report_suite_payload(canonical_audit, "project_report")
    delta = _mapping(project_report.get("delta"))
    trend_points = []
    for entry in project_report.get("trend_points", []):
        if not isinstance(entry, Mapping):
            continue
        trend_points.append(
            {
                "date_label": _format_display_date(entry.get("date"))
                or _l(language, "Unknown date"),
                "overall_display": _score_display(_float(entry.get("overall"))),
                "seo_display": _score_display(_float(entry.get("seo"))),
                "geo_display": _score_display(_float(entry.get("geo"))),
                "aeo_display": _score_display(_float(entry.get("aeo"))),
            }
        )
    task_summary = _mapping(project_report.get("task_status_summary"))
    task_movement = _mapping(project_report.get("task_movement"))
    validated_impact = []
    for item in project_report.get("validated_impact", []):
        if not isinstance(item, Mapping):
            continue
        is_validated = item.get("verification_status") == "validated"
        validated_impact.append(
            {
                "title": _text(item.get("title")),
                "category": _text(item.get("category")),
                "verification_label": _l(language, "No longer reported")
                if is_validated
                else _l(language, "Awaiting audit"),
                "narrative": _l(language, "No longer reported in a later audit.")
                if is_validated
                else _l(language, "Awaiting a later audit."),
            }
        )
    return {
        "project_score_delta": {
            "items": [
                {
                    "label": _l(language, "SEO delta"),
                    "display_value": _format_signed_delta(_float(delta.get("seo")), suffix=" pts"),
                    "tone": "strong"
                    if (_float(delta.get("seo")) or 0) > 0
                    else "critical"
                    if (_float(delta.get("seo")) or 0) < 0
                    else "muted",
                },
                {
                    "label": _l(language, "GEO delta"),
                    "display_value": _format_signed_delta(_float(delta.get("geo")), suffix=" pts"),
                    "tone": "strong"
                    if (_float(delta.get("geo")) or 0) > 0
                    else "critical"
                    if (_float(delta.get("geo")) or 0) < 0
                    else "muted",
                },
                {
                    "label": _l(language, "AEO delta"),
                    "display_value": _format_signed_delta(_float(delta.get("aeo")), suffix=" pts"),
                    "tone": "strong"
                    if (_float(delta.get("aeo")) or 0) > 0
                    else "critical"
                    if (_float(delta.get("aeo")) or 0) < 0
                    else "muted",
                },
                {
                    "label": _l(language, "Overall delta"),
                    "display_value": _format_signed_delta(
                        _float(delta.get("overall")), suffix=" pts"
                    ),
                    "tone": "strong"
                    if (_float(delta.get("overall")) or 0) > 0
                    else "critical"
                    if (_float(delta.get("overall")) or 0) < 0
                    else "muted",
                },
            ],
        },
        "project_trend_timeline": {
            "items": trend_points,
        },
        "task_movement": {
            "caption": (
                f"{_l(language, 'Audit coverage')}: "
                f"{_format_coverage_date(project_report.get('coverage_start'), language)}"
                " – "
                f"{_format_coverage_date(project_report.get('coverage_end'), language)}."
            ),
            "items": [
                {
                    "label": _l(language, "New actions"),
                    "value": str(_int(task_movement.get("new")) or 0),
                    "details": _string_list(task_movement.get("new_titles"))[:4],
                },
                {
                    "label": _l(language, "Resolved actions"),
                    "value": str(_int(task_movement.get("resolved")) or 0),
                    "details": _string_list(task_movement.get("resolved_titles"))[:4],
                },
                {
                    "label": _l(language, "Validated actions"),
                    "value": str(_int(task_movement.get("validated")) or 0),
                    "details": [],
                },
            ],
        },
        "task_status_summary": {
            "caption": _l(language, "Current project status."),
            "items": [
                {"label": _l(language, "To do"), "value": str(_int(task_summary.get("todo")) or 0)},
                {
                    "label": _l(language, "In progress"),
                    "value": str(_int(task_summary.get("in_progress")) or 0),
                },
                {"label": _l(language, "Done"), "value": str(_int(task_summary.get("done")) or 0)},
                {
                    "label": _l(language, "Validated"),
                    "value": str(_int(task_summary.get("validated")) or 0),
                },
            ],
        },
        "score_breakdown": {
            "items": _build_score_breakdown(canonical_audit),
        },
        "validated_impact": {
            "caption": _l(language, "Current verification of completed actions."),
            "items": validated_impact[:5],
        },
        "remaining_issues": {
            "items": _string_list(project_report.get("remaining_issues"))[:5],
        },
    }


def _build_financial_sections(
    canonical_audit: Mapping[str, Any],
    language: str = "en",
    *,
    withhold_credit_cost: bool = False,
) -> dict[str, Any]:
    financial_report = _report_suite_payload(canonical_audit, "financial_report")
    # SIGV2-1276: a white-label report must not even acknowledge that credit
    # metering exists, so withholding there means no section at all - the
    # notice below still names "credit cost disclosure". An explicit
    # ``redacted: false`` is the opt-in that shows the figures again.
    if withhold_credit_cost and financial_report.get("redacted") is not False:
        return {}
    if bool(financial_report.get("redacted")):
        return {
            "redaction_notice": {
                "title": _l(language, "Credit cost disclosure withheld"),
                "body": _text(
                    financial_report.get("redaction_reason"),
                    default=_l(
                        language,
                        "Financial details were intentionally withheld for client presentation.",
                    ),
                ),
            }
        }

    summary_items = [
        {
            "label": _l(language, "Total consumed"),
            "value": f"{_int(financial_report.get('total_consumed_credits')) or 0} credits",
        },
        {
            "label": _l(language, "Runs recorded"),
            "value": str(_int(financial_report.get("run_count")) or 0),
        },
    ]
    return {
        "financial_summary": {
            "items": summary_items,
        },
        "ledger_rows": {
            "items": [
                item
                for item in financial_report.get("ledger_rows", [])
                if isinstance(item, Mapping)
            ][:24],
        },
    }


def _strip_blocked_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _text(key).lower()
            if normalized_key in _WHITE_LABEL_BLOCKED_KEYS:
                continue
            cleaned[key] = _strip_blocked_keys(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_blocked_keys(item) for item in value]
    return value


def _sanitize_whitelabel_context(context: dict[str, Any]) -> dict[str, Any]:
    sanitized = _strip_blocked_keys(context)
    branding = _mapping(sanitized.get("branding"))
    branding["show_platform_branding"] = False
    branding["footer_text"] = _text(branding.get("footer_text"))
    branding["footer_mode"] = "text" if branding["footer_text"] else "blank"
    branding["vendor_name"] = ""
    sanitized["branding"] = branding
    return sanitized


def _strip_disclosure_keys(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = _text(key).lower()
            if normalized_key in _COST_DISCLOSURE_BLOCKED_KEYS:
                continue
            cleaned[key] = _strip_disclosure_keys(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_disclosure_keys(item) for item in value]
    return value


def _sanitize_cost_disclosure_context(context: dict[str, Any]) -> dict[str, Any]:
    sanitized = _strip_disclosure_keys(context)
    export_manifest = _mapping(sanitized.get("export_manifest"))
    export_manifest["hide_credit_cost"] = True
    sanitized["export_manifest"] = export_manifest
    return sanitized


_TOC_SPEC: dict[str, list[tuple[str, str | None]]] = {
    "standard": [
        ("Executive Dashboard", None),
        ("Why This Score?", None),
        ("Score Component Breakdown", "score_breakdown"),
        ("GEO Visibility Metrics", "geo_metrics"),
        ("AEO Readiness Dashboard", "aeo_readiness_dashboard"),
        ("Critical Blockers", None),
        ("Prescribed Actions", None),
        ("Trust & Confidence", "trust_banner"),
        ("Strategic Interpretation", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "executive": [
        ("Executive Analysis", None),
        ("Strategic Intelligence Grid", None),
        ("Score Component Breakdown", "score_breakdown"),
        ("AEO Readiness Dashboard", "aeo_readiness_dashboard"),
        ("High-Impact AI Blockers", None),
        ("Prescribed Actions", None),
        ("Strategic Interpretation", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "competitors": [
        ("Battlefield Leaderboard", None),
        ("Score Delta Analysis", None),
        ("All-Time Trend", "competitive_trend_timeline"),
        ("Competitive Position vs Structural Readiness", None),
        ("Entity Share of Voice", None),
        ("Strategic Conclusion", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "project": [
        ("Project Score Delta", None),
        ("Trend Timeline", None),
        ("Score Component Breakdown", "score_breakdown"),
        ("Action progress", None),
        ("Action status", None),
        ("Action verification", None),
        ("Remaining Issues", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "financial": [
        ("Financial Summary", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "aio": [
        ("AI Optimization Score", "aio_result"),
        ("Why This Score?", "why_this_score"),
        ("Score Component Breakdown", "score_breakdown"),
        ("GEO Visibility Metrics", "geo_metrics"),
        ("AEO Readiness Dashboard", "aeo_readiness_dashboard"),
        ("Critical Blockers", None),
        ("Prescribed Actions", None),
        ("Trust & Confidence", "trust_banner"),
        ("Strategic Interpretation", None),
        ("Integrity & Confidence Certificate", None),
    ],
    "seo": [
        ("SEO Score", "seo_overview"),
        ("Technical, On-Page & Performance", "seo_focus"),
        ("Why This Score?", "why_this_score"),
        ("Score Component Breakdown", "score_breakdown"),
        ("Critical Blockers", None),
        ("Prescribed Actions", None),
        ("Trust & Confidence", "trust_banner"),
        ("Strategic Interpretation", None),
        ("Integrity & Confidence Certificate", None),
    ],
}


def _build_toc_entries(
    report_kind: str,
    sections: Mapping[str, Any],
    language: str = "en",
) -> list[dict[str, Any]]:
    spec = _TOC_SPEC.get(report_kind, _TOC_SPEC.get("standard", []))
    entries: list[dict[str, Any]] = []
    for label, section_key in spec:
        if section_key is not None:
            section_value = sections.get(section_key)
            if not section_value:
                continue
            if isinstance(section_value, Mapping) and "items" in section_value:
                if not section_value["items"]:
                    continue
            if isinstance(section_value, Mapping) and "enabled" in section_value:
                if not section_value["enabled"]:
                    continue
        entries.append({"label": _l(language, label), "level": 1})
    return entries


def build_report_context(
    audit: dict[str, Any],
    report_type: str,
    agency_branding_data: dict[str, Any] | None = None,
    export_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable, template-safe context from a canonical or raw audit payload."""

    normalized_report_type = _normalize_report_type(report_type)
    branding_payload = dict(agency_branding_data or {})
    resolved_manifest = resolve_export_manifest(
        explicit_report_kind=_text(
            (export_manifest or {}).get("report_kind") or branding_payload.get("report_kind")
        )
        or None,
        explicit_branding_mode=_text(
            (export_manifest or {}).get("branding_mode") or branding_payload.get("branding_mode")
        )
        or None,
        explicit_competitor_mode=_text(
            (export_manifest or {}).get("competitor_mode")
            or branding_payload.get("competitor_mode")
        )
        or None,
        explicit_report_type=normalized_report_type,
        template_type=_text(
            (export_manifest or {}).get("template_type") or branding_payload.get("template_type")
        )
        or None,
        hide_credit_cost=(
            (export_manifest or {}).get("hide_credit_cost")
            if "hide_credit_cost" in _mapping(export_manifest)
            else branding_payload.get("hide_credit_cost")
        ),
        agency_branding_data=branding_payload,
    )
    report_kind = _text(resolved_manifest.get("report_kind"), default="standard") or "standard"
    is_white_label_mode = _text(resolved_manifest.get("branding_mode")) == "white_label"
    canonical_audit = _canonicalize_audit(audit)
    if normalized_report_type == "whitelabel":
        canonical_audit = to_whitelabel_safe_audit(canonical_audit)
    else:
        canonical_audit = to_client_safe_audit(canonical_audit)
    metadata = _mapping(canonical_audit.get("metadata"))
    language = normalize_report_language(
        _text(
            branding_payload.get("language")
            or metadata.get("language")
            or _safe_get(canonical_audit, "site", "language")
        )
        or "en"
    )
    generated_at = _text(branding_payload.get("generated_date")) or _text(
        metadata.get("updated_at") or metadata.get("created_at")
    )
    branding = _build_branding_context(
        report_type=normalized_report_type,
        report_kind=report_kind,
        agency_branding_data=branding_payload,
        generated_at=generated_at,
        language=language,
    )
    target = _mapping(canonical_audit.get("target"))
    site = _mapping(canonical_audit.get("site"))
    scores = _mapping(canonical_audit.get("scores"))
    narrative = _narrative_context(canonical_audit)

    _resolved_target_type = _text(target.get("type"), default="website") or "website"
    _resolved_target_url = _text(target.get("url") or site.get("url"))
    _is_brand_without_url = _resolved_target_type == "brand" and not _resolved_target_url

    common_context = {
        "report_type": normalized_report_type,
        "report_kind": report_kind,
        "generated_at": _text(generated_at or datetime.now(timezone.utc).isoformat()),
        "language": language,
        "is_cjk": bool(branding.get("is_cjk")),
        "is_rtl": bool(branding.get("is_rtl")),
        "branding": branding,
        "export_manifest": resolved_manifest,
        "labels": _build_report_labels(language),
        "is_brand_without_url": _is_brand_without_url,
        "target": {
            "name": _text(target.get("name"))
            or _text(site.get("url"))
            or _l(language, "Audit target"),
            "url": _resolved_target_url,
            "domain": _display_domain(_resolved_target_url),
            "type": _resolved_target_type,
            "market": _text(site.get("market"), default="global") or "global",
            "language": _text(site.get("language"), default=language) or language,
        },
        "scores": {
            "overall": _float(scores.get("overall")),
            "aio": _float(_safe_get(canonical_audit, "metadata", "aio", "aio_score")),
            "seo": _float(scores.get("seo")),
            "geo": _float(scores.get("geo")),
            "aeo": _float(scores.get("aeo")),
            "cards": _build_score_cards(
                canonical_audit, report_kind=report_kind, language=language
            ),
        },
        "narrative": narrative,
        "context_page": _build_context_page(
            canonical_audit,
            narrative,
            report_kind=report_kind,
            language=language,
            suppress_financial_context=is_white_label_mode,
        ),
        "integrity_page": _build_integrity_page(
            canonical_audit,
            report_kind=report_kind,
            hide_credit_cost=bool(resolved_manifest.get("hide_credit_cost")) or is_white_label_mode,
            language=language,
            white_label=is_white_label_mode,
        ),
        "sections": {},
        "charts": {},
        "withheld_sections": _build_withheld_sections(
            canonical_audit,
            language,
            white_label=is_white_label_mode,
        ),
    }

    branding_colors = _mapping(branding.get("colors"))
    _chart_primary = _text(branding_colors.get("primary"), default="#6366F1") or "#6366F1"
    _chart_secondary = _text(branding_colors.get("secondary"), default="#1E293B") or "#1E293B"

    if report_kind == "standard":
        common_context["sections"] = _build_standard_sections(
            canonical_audit,
            narrative,
            is_brand_without_url=_is_brand_without_url,
            language=language,
        )
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=True,
            language=language,
        )
    elif report_kind == "competitors":
        common_context["sections"] = _build_battle_sections(
            canonical_audit, narrative, language=language
        )
        _comp_metrics = _build_battle_comparison_metrics(canonical_audit, language=language)
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=False,
            comparison_metrics=_comp_metrics,
            comparison_color="#F97316",
            language=language,
        )
    elif report_kind == "executive":
        common_context["sections"] = _build_executive_sections(
            canonical_audit, narrative, language=language
        )
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=True,
            language=language,
        )
    elif report_kind == "project":
        common_context["sections"] = _build_project_sections(canonical_audit, language=language)
        project_report = _report_suite_payload(canonical_audit, "project_report")
        raw_trend = project_report.get("trend_points", [])
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=False,
            include_trend=True,
            trend_points=raw_trend,
        )
    elif report_kind == "financial":
        common_context["sections"] = _build_financial_sections(
            canonical_audit,
            language=language,
            withhold_credit_cost=is_white_label_mode,
        )
    elif report_kind == "aio":
        common_context["sections"] = _build_aio_sections(
            canonical_audit,
            narrative,
            is_brand_without_url=_is_brand_without_url,
            language=language,
        )
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=True,
            language=language,
        )
    elif report_kind == "seo":
        common_context["sections"] = _build_seo_sections(
            canonical_audit,
            narrative,
            is_brand_without_url=_is_brand_without_url,
            language=language,
        )
        common_context["charts"] = _build_charts_context(
            canonical_audit,
            branding_primary=_chart_primary,
            branding_secondary=_chart_secondary,
            include_radar=True,
            include_breakdown=True,
            language=language,
        )
    else:
        common_context["sections"] = _build_whitelabel_sections(
            canonical_audit, narrative, language=language
        )

    if isinstance(common_context.get("sections"), dict):
        common_context["sections"]["ai_engines"] = _build_ai_engines(
            canonical_audit, language=language
        )

    if report_kind in _MVP_REPORT_KINDS:
        common_context["sections"] = _apply_aio_public_naming(
            common_context["sections"], canonical_audit, language=language
        )

    common_context["toc_entries"] = _build_toc_entries(
        report_kind, common_context.get("sections") or {}, language=language
    )

    if normalized_report_type == "whitelabel":
        common_context = _sanitize_whitelabel_context(common_context)

    if bool(resolved_manifest.get("hide_credit_cost")):
        common_context = _sanitize_cost_disclosure_context(common_context)

    return common_context


def _build_synthetic_battle_audit(
    *,
    language: str = "en",
    left_title: str,
    right_title: str,
    left_report: Mapping[str, Any],
    right_report: Mapping[str, Any],
    comparison_pairs: Sequence[Mapping[str, Any]] | None = None,
    left_audit_record: Any | None = None,
    trend_payload: Mapping[str, Any] | None = None,
    benchmark_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    pairs = list(comparison_pairs or [])
    if not pairs:
        pairs = [
            {
                "left_title": left_title,
                "right_title": right_title,
                "left_report": left_report,
                "right_report": right_report,
            }
        ]

    first_pair = pairs[0]
    left_canonical = _canonicalize_audit(
        first_pair.get("left_full_report")
        if isinstance(first_pair.get("left_full_report"), Mapping)
        else first_pair.get("left_report")
    )
    competitor_rows: list[dict[str, Any]] = []
    for pair in pairs:
        right_canonical = _canonicalize_audit(
            pair.get("right_full_report")
            if isinstance(pair.get("right_full_report"), Mapping)
            else pair.get("right_report")
        )
        right_target = _mapping(right_canonical.get("target"))
        right_scores = _mapping(right_canonical.get("scores"))
        competitor_rows.append(
            {
                "name": _text(pair.get("right_title"))
                or _text(right_target.get("name"))
                or _l(language, "Competitor"),
                "geo_visibility": _float(right_scores.get("geo")),
                "aeo_score": _float(right_scores.get("aeo")),
                "entity_strength": _entity_strength_score(right_canonical),
            }
        )

    if isinstance(benchmark_payload, Mapping) and benchmark_payload:
        benchmark = deepcopy(dict(benchmark_payload))
    else:
        target_scores = _mapping(left_canonical.get("scores"))
        benchmark = _build_tolerant_benchmark_table(
            target_name=_text(first_pair.get("left_title"))
            or _text(_safe_get(left_canonical, "target", "name"))
            or _l(language, "Target"),
            target_metrics={
                "geo_visibility": _float(target_scores.get("geo")),
                "aeo_score": _float(target_scores.get("aeo")),
                "entity_strength": _entity_strength_score(left_canonical),
            },
            competitors=competitor_rows,
        )

    rows = _normalize_benchmark_rows(benchmark.get("rows"))
    competitor_deltas = _resolve_top_level_deltas(left_canonical, rows)
    metadata = _mapping(left_canonical.get("metadata"))
    competitor_summary = _mapping(metadata.get("competitor_summary"))
    competitor_summary["benchmark"] = benchmark
    if isinstance(trend_payload, Mapping) and trend_payload:
        competitor_summary["trend_timeline"] = deepcopy(dict(trend_payload))
    metadata["competitor_summary"] = competitor_summary
    if not _text(
        metadata.get("competitive_positioning") or metadata.get("market_dominance_blueprint")
    ):
        metadata["competitive_positioning"] = _text(
            metadata.get("strategic_summary")
            or metadata.get("neural_executive_summary")
            or metadata.get("executive_summary")
            or _l(
                language,
                "Comparative visibility signals highlight where the target is leading and where competitive pressure is increasing.",
            )
        )

    synthetic = deepcopy(left_canonical)
    synthetic["metadata"] = metadata
    synthetic["deltas_vs_target"] = competitor_deltas
    return _seed_audit_payload(
        audit_payload=synthetic,
        audit_record=left_audit_record,
        audit_url=_text(_safe_get(left_canonical, "target", "url")),
    )


def build_white_label_context(
    *,
    audit_id: int,
    audit_url: str,
    geo_score: float,
    highlights: Sequence[str],
    full_report: Mapping[str, Any],
    branding: Any,
    include_competitor_analysis: bool,
    audit_record: Any | None = None,
    audit_history: Sequence[Any] | None = None,
    selected_sections: Sequence[str] | None = None,
) -> dict[str, Any]:
    del (
        audit_id,
        geo_score,
        highlights,
        include_competitor_analysis,
        audit_history,
        selected_sections,
    )

    branding_payload = _branding_payload(branding)
    report_type = resolve_report_type(
        explicit_report_type=_text(branding_payload.get("report_type")),
        explicit_report_kind=_text(branding_payload.get("report_kind")) or None,
        explicit_branding_mode=_text(branding_payload.get("branding_mode")) or None,
        agency_branding_data=branding_payload,
    )
    export_manifest = resolve_export_manifest(
        explicit_report_kind=_text(branding_payload.get("report_kind")) or None,
        explicit_branding_mode=_text(branding_payload.get("branding_mode")) or None,
        explicit_competitor_mode=_text(branding_payload.get("competitor_mode")) or None,
        explicit_report_type=_text(branding_payload.get("report_type")) or None,
        hide_credit_cost=branding_payload.get("hide_credit_cost"),
        agency_branding_data=branding_payload,
    )
    seeded_payload = _seed_audit_payload(
        audit_payload=full_report,
        audit_record=audit_record,
        audit_url=audit_url,
    )
    return build_report_context(
        seeded_payload,
        report_type=report_type,
        agency_branding_data=branding_payload,
        export_manifest=export_manifest,
    )


def build_battle_context(
    *,
    left_title: str,
    right_title: str,
    left_report: Mapping[str, Any],
    right_report: Mapping[str, Any],
    branding: Any,
    comparison_pairs: Sequence[Mapping[str, Any]] | None = None,
    selected_sections: Sequence[str] | None = None,
    left_full_report: Mapping[str, Any] | None = None,
    right_full_report: Mapping[str, Any] | None = None,
    left_audit_record: Any | None = None,
    right_audit_record: Any | None = None,
    trend_payload: Mapping[str, Any] | None = None,
    benchmark_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    del selected_sections, right_full_report, right_audit_record

    branding_payload = _branding_payload(branding)
    synthetic_battle_audit = _build_synthetic_battle_audit(
        language=_text(branding_payload.get("language")) or "en",
        left_title=left_title,
        right_title=right_title,
        left_report=left_full_report if isinstance(left_full_report, Mapping) else left_report,
        right_report=right_report,
        comparison_pairs=comparison_pairs,
        left_audit_record=left_audit_record,
        trend_payload=trend_payload,
        benchmark_payload=benchmark_payload,
    )
    branding_payload["report_type"] = "battle"
    export_manifest = resolve_export_manifest(
        explicit_report_kind=_text(branding_payload.get("report_kind")) or "competitors",
        explicit_branding_mode=_text(branding_payload.get("branding_mode")) or None,
        explicit_competitor_mode=_text(branding_payload.get("competitor_mode")) or None,
        explicit_report_type="battle",
        hide_credit_cost=branding_payload.get("hide_credit_cost"),
        agency_branding_data=branding_payload,
    )
    return build_report_context(
        synthetic_battle_audit,
        report_type="battle",
        agency_branding_data=branding_payload,
        export_manifest=export_manifest,
    )


__all__ = [
    "build_battle_context",
    "build_report_context",
    "build_white_label_context",
    "normalize_branding_mode",
    "normalize_competitor_mode",
    "normalize_report_kind",
    "resolve_branding_mode",
    "resolve_export_manifest",
    "resolve_report_kind",
    "resolve_report_type",
]
