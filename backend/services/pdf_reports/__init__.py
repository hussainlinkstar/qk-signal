from .assembler import (
    build_battle_context,
    build_report_context,
    build_white_label_context,
    normalize_branding_mode,
    normalize_competitor_mode,
    normalize_report_kind,
    resolve_branding_mode,
    resolve_effective_export_manifest,
    resolve_export_manifest,
    resolve_report_kind,
    resolve_report_type,
)
from .contracts import BrandingConfig
from .renderer import render_pdf_from_template

__all__ = [
    "BrandingConfig",
    "build_battle_context",
    "build_report_context",
    "build_white_label_context",
    "normalize_branding_mode",
    "normalize_competitor_mode",
    "normalize_report_kind",
    "render_pdf_from_template",
    "resolve_branding_mode",
    "resolve_effective_export_manifest",
    "resolve_export_manifest",
    "resolve_report_kind",
    "resolve_report_type",
]
