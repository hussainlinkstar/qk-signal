"""Plan-entitlement policy for report PDF exports.

Pure decision logic shared by the HTTP enqueue paths, the queued PDF worker
and the download endpoint. This module must not import the router so the
worker can evaluate the same requirements without pulling in the API layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.services.compliance.plan_validator import PlanValidator

_plan_validator = PlanValidator()


@dataclass(frozen=True)
class ReportExportRequirement:
    feature_key: str
    detail: str


def resolve_report_export_requirements(
    export_manifest: Mapping[str, Any],
) -> tuple[ReportExportRequirement, ...]:
    """Return the capability requirements this manifest implies, in order.

    Mirrors the check order and early returns of the HTTP gate so denial
    precedence is identical at every enforcement point.
    """
    report_type = str(export_manifest.get("render_report_type") or "").strip().lower()
    report_kind = str(export_manifest.get("report_kind") or "").strip().lower()
    branding_mode = str(export_manifest.get("branding_mode") or "").strip().lower()

    requirements: list[ReportExportRequirement] = []

    is_white_label = branding_mode == "white_label" or report_type == "whitelabel"
    if is_white_label:
        requirements.append(
            ReportExportRequirement(
                feature_key="pdf_white_label",
                detail="White-label PDF reports are available on plans with PDF white-label access.",
            )
        )

    if report_type == "battle" or report_kind == "competitors":
        requirements.append(
            ReportExportRequirement(
                feature_key="has_competitor_analysis",
                detail="Battle PDF reports are available on plans with competitor analysis.",
            )
        )
        if report_type != "branded":
            return tuple(requirements)

    if report_type == "branded":
        requirements.append(
            ReportExportRequirement(
                feature_key="has_advanced_reporting",
                detail="Branded PDF reports are available on plans with advanced reporting.",
            )
        )
        return tuple(requirements)

    if is_white_label:
        return tuple(requirements)

    requirements.append(
        ReportExportRequirement(
            feature_key="has_pdf_audit_reports",
            detail="PDF audit reports are not available on your current plan.",
        )
    )
    return tuple(requirements)


def first_unmet_report_export_requirement(
    user: Any,
    export_manifest: Mapping[str, Any],
    *,
    validator: Any | None = None,
) -> ReportExportRequirement | None:
    """Return the first requirement the user's current plan does not meet, or None.

    ``validator`` defaults to this module's PlanValidator instance; the HTTP
    adapter passes the router's own instance so behavior (including any
    runtime substitution) matches the pre-existing gate exactly.
    """
    plan_validator = validator if validator is not None else _plan_validator
    for requirement in resolve_report_export_requirements(export_manifest):
        if not plan_validator.has_feature(user, requirement.feature_key):
            return requirement
    return None


__all__ = [
    "ReportExportRequirement",
    "first_unmet_report_export_requirement",
    "resolve_report_export_requirements",
]
