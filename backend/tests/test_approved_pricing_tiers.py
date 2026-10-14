"""SIGV2-1211 block C3: the approved pricing tiers and the Executive up-sell.

Edward approved the four-tier table Jake supplied, so this module pins it as a
specification rather than leaving it implied by whichever surface happens to
render a number.

Three things are pinned here, and each exists because the approved table
disagrees with something already shipped.

**Price.** Starter stays free, Standard drops to $49, Specialist drops to $99
and Executive stops quoting a figure to a customer at all. Executive keeps its
internal list price: ``admin_billing_helpers`` sums ``monthly_price_usd`` into
MRR and ``stripe_catalog_service`` turns it into a Stripe ``unit_amount``, so
zeroing or nulling the matrix entry would silently drop Executive revenue from
the admin figure and would ask Stripe to create a $0 recurring price. The
figure is withheld from customer surfaces instead, which is the same shape
``UNPUBLISHED_CAPABILITY_KEYS`` already uses for a live value that may not be
stated.

**The allowance ladder is unchanged.** Every numeric and boolean row in the
approved table already matches ``CAPABILITY_MATRIX``, so the table is the
shipped entitlement ladder with new prices on it. Pinning that here means a
later edit to a cap has to argue with the approved table, and it records that
this branch reduced nothing: no customer loses a site, a scan, a keyword or a
capability.

**The Executive up-sell is copy, not entitlement.** Jake's own wording is that
the extra Enterprise entries are "an up-sell to customers that we would custom
build, not necessarily things that are in Executive right now". Workflow
automation, white-label delivery and multi-workspace federation therefore
appear as bespoke consultancy text and must never be derived from
``can_use_workflow_automations``, ``max_workflows_per_project``,
``has_white_label``, ``pdf_white_label`` or
``has_multi_workspace_federation``. Deriving them would re-publish in one move
what SIGV2-1206 unpublished and what SIGV2-1167 withdrew, so the independence
is asserted directly: the copy survives those keys being flipped off.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

from app.config.plans import (  # noqa: E402
    CAPABILITY_MATRIX,
    CUSTOM_PRICED_PLAN_IDS,
    UNPUBLISHED_CAPABILITY_KEYS,
    bespoke_plan_highlights,
    bespoke_plan_inclusions,
    build_plan_feature_list,
    get_plan_catalog_entry,
    get_plan_monthly_price_usd,
    is_custom_priced,
)


# ---------------------------------------------------------------------------
# The approved table, transcribed once
# ---------------------------------------------------------------------------

APPROVED_MONTHLY_PRICE_USD = {
    "plan_starter": 0,
    "plan_standard": 49,
    "plan_specialist": 99,
    # Executive is "Contact Us" on the approved table. The figure below is the
    # internal list price it keeps for MRR and Stripe, never quoted to a
    # customer; `test_executive_quotes_no_price_to_a_customer` is the half of
    # this pair that pins the withholding.
    "plan_executive": 999,
}

APPROVED_ALLOWANCES = {
    "max_sites": {
        "plan_starter": 1,
        "plan_standard": 1,
        "plan_specialist": 10,
        "plan_executive": -1,
    },
    "max_audits": {
        "plan_starter": 1,
        "plan_standard": 200,
        "plan_specialist": 800,
        "plan_executive": 2000,
    },
    "max_tracked_keywords": {
        "plan_starter": 5,
        "plan_standard": 10,
        "plan_specialist": 50,
        "plan_executive": 200,
    },
    "max_parallel_audits": {
        "plan_starter": 1,
        "plan_standard": 1,
        "plan_specialist": 5,
        "plan_executive": 10,
    },
    "max_workflows_per_project": {
        "plan_starter": 0,
        "plan_standard": 0,
        "plan_specialist": 5,
        "plan_executive": -1,
    },
}

# Every boolean row on the approved table, as Starter/Standard/Specialist/Executive.
APPROVED_CAPABILITIES = {
    "has_advisor_recommendations": (False, True, True, True),
    "has_competitor_analysis": (False, False, True, True),
    "has_semantic_gap": (False, False, True, True),
    "has_advanced_reporting": (False, False, True, True),
    # The approved table names this row "API & MCP access". Only the API half
    # is asserted, and only the API half is published: ``mcp_access`` does not
    # exist on this branch's base at all (it arrives with SIGV2-1210, which
    # requires server and client evidence to be recorded before pricing may
    # advertise MCP). Renaming the published row to mention MCP here would
    # promise a connection no customer can make yet.
    "api_access": (False, False, True, True),
    "has_high_confidence_mode": (False, False, True, True),
    "has_priority_pulse": (False, False, True, True),
    "has_predictive_intent_engine": (False, False, True, True),
    "has_semantic_graph_mapping": (False, False, True, True),
    "has_white_label": (False, False, False, True),
    "pdf_white_label": (False, False, False, True),
    "has_multi_workspace_federation": (False, False, False, True),
    "has_custom_pricing": (False, False, False, True),
}

PRICED_LADDER = ("plan_starter", "plan_standard", "plan_specialist", "plan_executive")

# Jake's exact copy for the Executive card. Capitalisation and punctuation are
# the acceptance criterion, so they are asserted literally.
EXECUTIVE_HIGHLIGHTS = (
    "Agent development",
    "Custom workflows",
    "Paid ads / marketing insights",
)
EXECUTIVE_INCLUSIONS = (
    "Agent deployment and hosting",
    "Workflow automation to fit your processes",
    "AI consultancy and development",
)

# The keys the bespoke copy must never be derived from. The first two are
# unpublished by SIGV2-1206 (Automations is Coming Soon) and the last three
# are the white-label and federation offers Jake reclassified as custom build
# work rather than shipped Executive capability.
FORBIDDEN_SOURCE_KEYS = (
    "can_use_workflow_automations",
    "max_workflows_per_project",
    "has_white_label",
    "pdf_white_label",
    "has_multi_workspace_federation",
)


# ---------------------------------------------------------------------------
# Price
# ---------------------------------------------------------------------------


def test_the_matrix_carries_the_approved_monthly_prices() -> None:
    for plan, price in APPROVED_MONTHLY_PRICE_USD.items():
        assert CAPABILITY_MATRIX[plan]["monthly_price_usd"] == price, plan


def test_mrr_and_stripe_still_read_a_real_executive_figure() -> None:
    """The withholding is a presentation decision, not a deleted price.

    ``admin_billing_helpers.compute_mrr`` and
    ``stripe_catalog_service._catalog_definitions`` both go through this
    function, so it has to keep returning the list price.
    """
    assert get_plan_monthly_price_usd("plan_standard") == 49
    assert get_plan_monthly_price_usd("plan_specialist") == 99
    assert get_plan_monthly_price_usd("plan_executive") == 999


def test_exactly_one_plan_is_custom_priced() -> None:
    assert CUSTOM_PRICED_PLAN_IDS == frozenset({"plan_executive"})
    assert is_custom_priced("plan_executive") is True
    for plan in ("plan_starter", "plan_standard", "plan_specialist", "plan_agency_trial"):
        assert is_custom_priced(plan) is False, plan
    assert is_custom_priced(None) is False
    assert is_custom_priced("plan_does_not_exist") is False


def test_executive_quotes_no_price_to_a_customer() -> None:
    """The customer-facing catalogue entry carries no Executive figure.

    ``None`` rather than ``0``: the billing card and the comparison header
    both render 0 as "Free", and the marketing site treats a zero amount as
    free too, so a zeroed price would advertise the most expensive plan as the
    cheapest.
    """
    entry = get_plan_catalog_entry("plan_executive")
    capabilities = entry["capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["monthly_price_usd"] is None
    assert entry["annual_price_usd"] is None
    assert entry["custom_priced"] is True
    assert entry["cta"] == "contact"


def test_a_listed_plan_still_quotes_its_price_and_annual_total() -> None:
    standard = get_plan_catalog_entry("plan_standard")
    capabilities = standard["capabilities"]
    assert isinstance(capabilities, dict)
    assert capabilities["monthly_price_usd"] == 49
    # 20% off twelve months at the approved price.
    assert standard["annual_price_usd"] == 470.4
    assert standard["custom_priced"] is False
    assert standard["cta"] == "self_serve"

    specialist = get_plan_catalog_entry("plan_specialist")
    specialist_capabilities = specialist["capabilities"]
    assert isinstance(specialist_capabilities, dict)
    assert specialist_capabilities["monthly_price_usd"] == 99
    assert specialist["annual_price_usd"] == 950.4


# ---------------------------------------------------------------------------
# The allowance ladder the approved table did not change
# ---------------------------------------------------------------------------


def test_every_approved_allowance_already_matches_the_shipped_ladder() -> None:
    for key, expected in APPROVED_ALLOWANCES.items():
        for plan, value in expected.items():
            assert CAPABILITY_MATRIX[plan][key] == value, f"{plan}.{key}"


def test_every_approved_capability_already_matches_the_shipped_ladder() -> None:
    for key, expected in APPROVED_CAPABILITIES.items():
        actual = tuple(bool(CAPABILITY_MATRIX[plan][key]) for plan in PRICED_LADDER)
        assert actual == expected, key


def test_no_tracked_allowance_was_reduced_for_an_existing_customer() -> None:
    """Nothing in this branch takes an allowance away.

    The approved table's "Max Tracked Keywords" column is the keyword cap,
    which already read 5/10/50/200, not the separate tracked-prompt cap
    SIGV2-1188 settled at 10/25/50/200. Had the two been conflated, Starter
    would have halved and Standard would have dropped by 60%, so this asserts
    the prompt ladder is untouched by a pricing change.
    """
    from services.project_visibility_service import visibility_query_allowances

    assert visibility_query_allowances() == {
        "plan_starter": 10,
        "plan_agency_trial": 25,
        "plan_standard": 25,
        "plan_specialist": 50,
        "plan_executive": 200,
    }


# ---------------------------------------------------------------------------
# The Executive up-sell is copy, never a capability key
# ---------------------------------------------------------------------------


def test_the_executive_card_states_jakes_exact_highlights() -> None:
    assert bespoke_plan_highlights("plan_executive") == EXECUTIVE_HIGHLIGHTS
    assert get_plan_catalog_entry("plan_executive")["bespoke_highlights"] == list(
        EXECUTIVE_HIGHLIGHTS
    )


def test_the_executive_card_states_jakes_exact_inclusions() -> None:
    assert bespoke_plan_inclusions("plan_executive") == EXECUTIVE_INCLUSIONS


def test_no_other_plan_carries_bespoke_consultancy_copy() -> None:
    for plan in ("plan_starter", "plan_standard", "plan_specialist", "plan_agency_trial"):
        assert bespoke_plan_highlights(plan) == (), plan
        assert bespoke_plan_inclusions(plan) == (), plan
        assert get_plan_catalog_entry(plan)["bespoke_highlights"] == [], plan


def test_the_executive_feature_list_is_one_real_allowance_then_bespoke_copy() -> None:
    """Jake's card: the first tick stays the scan allowance, the last three change."""
    assert build_plan_feature_list("plan_executive") == [
        "2000 audits/mo",
        *EXECUTIVE_INCLUSIONS,
    ]


def test_the_executive_feature_list_no_longer_advertises_the_withdrawn_offers() -> None:
    features = " | ".join(build_plan_feature_list("plan_executive")).lower()
    for claim in ("multiple workspaces", "white-label", "white label"):
        assert claim not in features, claim


def test_the_bespoke_copy_does_not_come_from_any_capability_key(monkeypatch) -> None:
    """Flip every forbidden source off; the copy must not move.

    This is the assertion that stops the up-sell quietly becoming an
    entitlement claim. If someone replaces the literal copy with a derivation
    from one of these keys, the published Executive card starts contradicting
    SIGV2-1206 and SIGV2-1167, and this test is what notices.
    """
    for key in FORBIDDEN_SOURCE_KEYS:
        monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], key, False)
    monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], "max_workflows_per_project", 0)

    assert bespoke_plan_highlights("plan_executive") == EXECUTIVE_HIGHLIGHTS
    assert bespoke_plan_inclusions("plan_executive") == EXECUTIVE_INCLUSIONS
    assert build_plan_feature_list("plan_executive") == [
        "2000 audits/mo",
        *EXECUTIVE_INCLUSIONS,
    ]
    assert get_plan_catalog_entry("plan_executive")["bespoke_highlights"] == list(
        EXECUTIVE_HIGHLIGHTS
    )


def test_the_workflow_automation_keys_stay_unpublished() -> None:
    """SIGV2-1206 is not undone by publishing an Executive up-sell."""
    assert "can_use_workflow_automations" in UNPUBLISHED_CAPABILITY_KEYS
    assert "max_workflows_per_project" in UNPUBLISHED_CAPABILITY_KEYS


def test_the_bespoke_copy_carries_no_em_dash() -> None:
    for plan in CAPABILITY_MATRIX:
        for line in (*bespoke_plan_highlights(plan), *bespoke_plan_inclusions(plan)):
            assert "\u2014" not in line, line
