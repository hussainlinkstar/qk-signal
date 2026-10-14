"""The Export report menu, resolved against real plan entitlement.

The menu offers the report kinds the product sells (SIGV2-1255): Standard,
Executive, AIO and SEO, plus the Competitors report on the screens that carry
it. The branding-tier rows (branded, white-label) are gone from the menu; a
white-label executive export still exists through its own endpoint and the
branding settings surface, it is simply not a row here.

The lock state must never be decided by a client-side capability table: a
frontend table that disagreed with `CAPABILITY_MATRIX` is the defect SIGV2-1108
had to fix on live engine tracking. So this module derives each variant's
entitlement from the same objects the enqueue, worker and download paths use:
`resolve_export_manifest` builds the manifest, `resolve_report_export_requirements`
turns it into capability requirements, and the plan validator answers them.

Every variant is gated on exactly the capability its own manifest requires and
on nothing else. There is deliberately no second channel for presentation to
diverge from entitlement:

  standard / executive / aio / seo   has_pdf_audit_reports (every plan)
  competitors                        has_competitor_analysis

The four kind-based rows carry no extra entitlement of their own - the same
call SIGV2-1018 recorded for the aio and seo kinds - so a plan that can export
a PDF can export each report kind.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.config.plans import MINIMUM_PLAN_BY_FEATURE, PLAN_PRESENTATION
from services.pdf_reports.assembler import resolve_export_manifest
from services.report_export_policy import (
    first_unmet_report_export_requirement,
    resolve_report_export_requirements,
)


@dataclass(frozen=True)
class ExportVariantSpec:
    """One row of the approved Export report menu."""

    key: str
    report_type: str
    report_kind: str | None
    template_type: str


# Which variants exist, and what each one is, is this list; the per-page
# ordering is a layout concern and stays in the UI (`EXPORT_MENU_PAGES`).
EXPORT_VARIANT_SPECS: tuple[ExportVariantSpec, ...] = (
    ExportVariantSpec(
        key="standard",
        report_type="standard",
        report_kind="standard",
        template_type="Executive",
    ),
    ExportVariantSpec(
        key="executive",
        report_type="standard",
        report_kind="executive",
        template_type="Executive",
    ),
    ExportVariantSpec(
        key="aio",
        report_type="standard",
        report_kind="aio",
        template_type="Executive",
    ),
    ExportVariantSpec(
        key="seo",
        report_type="standard",
        report_kind="seo",
        template_type="Executive",
    ),
    ExportVariantSpec(
        key="competitors",
        report_type="standard",
        report_kind="competitors",
        template_type="Executive",
    ),
)


def _manifest_for(spec: ExportVariantSpec) -> dict[str, Any]:
    return resolve_export_manifest(
        explicit_report_kind=spec.report_kind,
        explicit_report_type=spec.report_type,
        template_type=spec.template_type,
    )


def _plan_label(plan: str | None) -> str | None:
    if not plan:
        return None
    presentation = PLAN_PRESENTATION.get(plan)
    if presentation:
        name = presentation.get("name")
        if isinstance(name, str) and name:
            return name
    return plan.removeprefix("plan_").replace("_", " ").title()


def resolve_export_variant_entitlements(
    user: Any,
    *,
    validator: Any | None = None,
) -> list[dict[str, Any]]:
    """Describe every approved export variant for this user's real plan.

    `locked` is the answer the enqueue endpoint would give, and nothing else:
    True exactly when the plan fails a capability requirement this variant's
    manifest implies. It is the single field the menu gates on, so there is no
    second one for a presentation rule to contradict it with.

    `required_capability` and `required_plan_label` name the requirement, so the
    menu can say which plan unlocks a locked variant without owning a plan table
    of its own.
    """

    rows: list[dict[str, Any]] = []
    for spec in EXPORT_VARIANT_SPECS:
        manifest: Mapping[str, Any] = _manifest_for(spec)
        requirements = resolve_report_export_requirements(manifest)
        unmet = first_unmet_report_export_requirement(user, manifest, validator=validator)

        # The requirement the plan has to clear to reach this variant at all is
        # the last one in the chain; the earlier ones are prerequisites that a
        # higher plan already satisfies. Report whichever one is actually unmet,
        # and otherwise the gating requirement itself.
        gating = requirements[-1] if requirements else None
        reported = unmet or gating
        required_capability = reported.feature_key if reported else None
        required_plan = (
            MINIMUM_PLAN_BY_FEATURE.get(required_capability) if required_capability else None
        )

        rows.append(
            {
                "key": spec.key,
                "report_type": spec.report_type,
                "report_kind": spec.report_kind,
                "template_type": spec.template_type,
                "locked": unmet is not None,
                "required_capability": required_capability,
                "required_plan": required_plan,
                "required_plan_label": _plan_label(required_plan),
            }
        )
    return rows


__all__ = [
    "EXPORT_VARIANT_SPECS",
    "ExportVariantSpec",
    "resolve_export_variant_entitlements",
]
