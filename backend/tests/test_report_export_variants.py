"""SIGV2-1124: the Export report menu resolves against real entitlement.

SIGV2-1255: the menu offers the report kinds the product sells - Standard,
Executive, AIO and SEO, plus Competitors where the screen carries it - instead
of the branding-tier rows (branded, white-label). The menu's lock state must be
the same answer the enqueue endpoint gives, so these tests pin the variant set,
the capability each variant is gated on, and the plan label reported for a
locked variant. A frontend capability table that disagrees with
`CAPABILITY_MATRIX` is the defect this is built to prevent.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import MINIMUM_PLAN_BY_FEATURE, can_use_feature
from services.report_export_variants import (
    EXPORT_VARIANT_SPECS,
    resolve_export_variant_entitlements,
)

ALL_PLANS = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)


def _user_on_plan(plan_type: str | None) -> SimpleNamespace:
    subscription = SimpleNamespace(status="active", plan_type=plan_type) if plan_type else None
    return SimpleNamespace(subscription=subscription, trial_plan=None)


def _by_key(user) -> dict[str, dict]:
    return {row["key"]: row for row in resolve_export_variant_entitlements(user)}


def test_variant_set_is_the_report_kinds_the_product_sells():
    assert [spec.key for spec in EXPORT_VARIANT_SPECS] == [
        "standard",
        "executive",
        "aio",
        "seo",
        "competitors",
    ]
    for row in resolve_export_variant_entitlements(_user_on_plan("plan_starter")):
        assert row["key"] not in {"branded", "whitelabel"}


@pytest.mark.parametrize(
    "key,capability",
    [
        ("standard", "has_pdf_audit_reports"),
        ("executive", "has_pdf_audit_reports"),
        ("aio", "has_pdf_audit_reports"),
        ("seo", "has_pdf_audit_reports"),
        ("competitors", "has_competitor_analysis"),
    ],
)
def test_each_variant_reports_the_capability_the_enqueue_gate_enforces(key, capability):
    rows = _by_key(_user_on_plan("plan_starter"))
    assert rows[key]["required_capability"] == capability


@pytest.mark.parametrize(
    "key,plan_label",
    [
        ("standard", "Starter"),
        ("executive", "Starter"),
        ("aio", "Starter"),
        ("seo", "Starter"),
        ("competitors", "Specialist"),
    ],
)
def test_required_plan_label_comes_from_the_plan_catalogue(key, plan_label):
    rows = _by_key(_user_on_plan("plan_starter"))
    assert rows[key]["required_plan_label"] == plan_label
    assert rows[key]["required_plan"] == MINIMUM_PLAN_BY_FEATURE[rows[key]["required_capability"]]


def test_starter_unlocks_every_report_kind_but_not_competitors():
    """Every plan holds `has_pdf_audit_reports`, so the four report kinds are
    never locked. Competitors stays the one gated row (SIGV2-1018's no-new-
    entitlement call applied to the menu)."""
    rows = _by_key(_user_on_plan("plan_starter"))
    for key in ("standard", "executive", "aio", "seo"):
        assert rows[key]["locked"] is False, key
    assert rows["competitors"]["locked"] is True


def test_specialist_unlocks_the_competitors_report_too():
    rows = _by_key(_user_on_plan("plan_specialist"))
    for row in rows.values():
        assert row["locked"] is False, row["key"]


def test_no_subscription_resolves_to_the_free_plan_entitlement():
    rows = _by_key(_user_on_plan(None))
    assert rows["standard"]["locked"] is False
    assert rows["competitors"]["locked"] is True


def test_no_variant_carries_a_presentation_override():
    """There is one lock field, derived from entitlement, and no second channel."""
    for plan in ALL_PLANS:
        for row in resolve_export_variant_entitlements(_user_on_plan(plan)):
            assert "requires_sales" not in row
            assert "entitled" not in row


# ---------------------------------------------------------------------------
# The whole point: never disagree with the capability matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan", ALL_PLANS)
def test_lock_state_never_disagrees_with_the_capability_matrix(plan):
    for row in resolve_export_variant_entitlements(_user_on_plan(plan)):
        capability = row["required_capability"]
        assert row["locked"] is not can_use_feature(
            plan, capability
        ), f"{row['key']} on {plan} disagrees with CAPABILITY_MATRIX for {capability}"


@pytest.mark.parametrize("plan", ALL_PLANS)
def test_every_unlocked_variant_would_pass_the_enqueue_gate(plan):
    """An unlocked row must be one `generate-complex` actually accepts.

    This is the property the menu exists to preserve: the lock and the gate are
    the same decision, so the menu can neither offer a refusal nor hide a
    capability.
    """
    from services.pdf_reports.assembler import resolve_export_manifest
    from services.report_export_policy import first_unmet_report_export_requirement

    user = _user_on_plan(plan)
    for spec in EXPORT_VARIANT_SPECS:
        manifest = resolve_export_manifest(
            explicit_report_kind=spec.report_kind,
            explicit_report_type=spec.report_type,
            template_type=spec.template_type,
        )
        gate_refuses = first_unmet_report_export_requirement(user, manifest) is not None
        row = _by_key(user)[spec.key]
        assert (
            row["locked"] is gate_refuses
        ), f"{spec.key} on {plan}: menu locked={row['locked']} but gate refuses={gate_refuses}"
