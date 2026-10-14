from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from services.pdf_reports import (
    BrandingConfig,
    build_battle_context,
    build_white_label_context,
    render_pdf_from_template,
)


def render_white_label_pdf(
    *,
    audit_id: int,
    audit_url: str,
    geo_score: float,
    highlights: list[str],
    full_report: dict,
    branding: BrandingConfig,
    include_competitor_analysis: bool,
    audit_record: Any | None = None,
    audit_history: Sequence[Any] | None = None,
    selected_sections: Sequence[str] | None = None,
) -> bytes:
    context = build_white_label_context(
        audit_id=audit_id,
        audit_url=audit_url,
        geo_score=geo_score,
        highlights=highlights,
        full_report=full_report,
        branding=branding,
        include_competitor_analysis=include_competitor_analysis,
        audit_record=audit_record,
        audit_history=audit_history,
        selected_sections=selected_sections,
    )
    return render_pdf_from_template(template_name="white_label.html", context=context)


def render_battle_report_pdf(
    *,
    left_title: str,
    right_title: str,
    left_report: dict,
    right_report: dict,
    branding: BrandingConfig,
    comparison_pairs: list[dict[str, str | dict]] | None = None,
    selected_sections: Sequence[str] | None = None,
    left_full_report: Mapping[str, Any] | None = None,
    right_full_report: Mapping[str, Any] | None = None,
    left_audit_record: Any | None = None,
    right_audit_record: Any | None = None,
    trend_payload: Mapping[str, Any] | None = None,
    benchmark_payload: Mapping[str, Any] | None = None,
) -> bytes:
    context = build_battle_context(
        left_title=left_title,
        right_title=right_title,
        left_report=left_report,
        right_report=right_report,
        branding=branding,
        comparison_pairs=comparison_pairs,
        selected_sections=selected_sections,
        left_full_report=left_full_report,
        right_full_report=right_full_report,
        left_audit_record=left_audit_record,
        right_audit_record=right_audit_record,
        trend_payload=trend_payload,
        benchmark_payload=benchmark_payload,
    )
    return render_pdf_from_template(template_name="battle.html", context=context)


__all__ = [
    "BrandingConfig",
    "render_battle_report_pdf",
    "render_pdf_from_template",
    "render_white_label_pdf",
]
