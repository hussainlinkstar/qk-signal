from __future__ import annotations

import re
from typing import Any

from services.report_i18n_service import (
    is_cjk_report_language,
    is_rtl_report_language,
    normalize_report_language,
)


_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def normalize_hex_color(value: str | None, fallback: str) -> str:
    candidate = str(value or "").strip()
    if not _HEX_COLOR_RE.match(candidate):
        return fallback
    return candidate if candidate.startswith("#") else f"#{candidate}"


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = normalize_hex_color(value, "#000000").lstrip("#")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )


def _clamp_channel(value: float) -> int:
    return max(0, min(255, int(round(value))))


def mix_hex_colors(base: str, other: str, ratio: float) -> str:
    ratio = max(0.0, min(1.0, ratio))
    base_rgb = _hex_to_rgb(base)
    other_rgb = _hex_to_rgb(other)
    mixed = tuple(
        _clamp_channel((base_channel * (1 - ratio)) + (other_channel * ratio))
        for base_channel, other_channel in zip(base_rgb, other_rgb)
    )
    return "#{:02X}{:02X}{:02X}".format(*mixed)


def pick_text_color(background: str) -> str:
    red, green, blue = _hex_to_rgb(background)
    luminance = ((0.299 * red) + (0.587 * green) + (0.114 * blue)) / 255
    return "#00040e" if luminance > 0.62 else "#F8FAFC"


def build_branding_theme(branding: Any) -> dict[str, Any]:
    primary = normalize_hex_color(getattr(branding, "primary_color", None), "#2563EB")
    secondary = normalize_hex_color(getattr(branding, "secondary_color", None), "#9333EA")
    primary_text = pick_text_color(primary)
    secondary_text = pick_text_color(secondary)
    language = normalize_report_language(getattr(branding, "language", None))
    vendor_name = str(getattr(branding, "vendor_name", "") or "Qiko Signal")
    is_white_label = bool(getattr(branding, "is_white_label", False))
    show_powered_by = bool(getattr(branding, "show_powered_by", False))
    company_name = str(getattr(branding, "company_name", "") or "").strip()
    if not company_name and not is_white_label:
        company_name = vendor_name

    cover_from = "#FFFFFF"
    cover_to = "#F6F7F9"
    cover_accent = f"linear-gradient(90deg, {primary}, {secondary})"

    return {
        "title": str(getattr(branding, "title", "") or "Audit Report"),
        "company_name": company_name,
        "generated_date": str(getattr(branding, "generated_date", "") or ""),
        "language": language,
        "is_cjk": is_cjk_report_language(language),
        "is_rtl": is_rtl_report_language(language),
        "vendor_name": vendor_name,
        "is_white_label": is_white_label,
        "show_powered_by": show_powered_by,
        "show_platform_branding": bool(
            getattr(branding, "show_platform_branding", not is_white_label)
        ),
        "logo_data_url": getattr(branding, "logo_data_url", None),
        "colors": {
            "primary": primary,
            "secondary": secondary,
            "primary_text": primary_text,
            "secondary_text": secondary_text,
            "background": "#FFFFFF",
            "card": "#FFFFFF",
            "card_alt": mix_hex_colors(primary, "#F8FAFC", 0.94),
            "border": "#E8EAEE",
            "muted": "#565E6E",
            "text": "#0C0F16",
            "success": "#12A150",
            "warning": "#D9930B",
            "danger": "#E5484D",
            "header_bg": "#FFFFFF",
            "header_text": "#565E6E",
            "cover_from": cover_from,
            "cover_to": cover_to,
            "cover_accent": cover_accent,
            "surface_tint": mix_hex_colors(primary, "#FFFFFF", 0.94),
            "shadow": "rgba(15, 23, 42, 0.06)",
        },
    }
