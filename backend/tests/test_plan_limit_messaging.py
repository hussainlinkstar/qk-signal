"""Shared wording for per-plan caps on tracked resources (SIGV2-1142, SIGV2-1150).

Tracked prompts and tracked keywords are capped per plan and refuse with the
same sentence, built in one place. These tests pin the two properties that
sentence must have for every plan and every resource:

* it names a plan the customer can actually buy, never a private plan, and
* when nothing purchasable raises the cap it says to remove one instead, rather
  than promising an upgrade that does not exist.

The named upgrade target used to be derived by plan weight alone, which made
``Agency Trial`` the answer for a Starter customer: a free 14-day evaluation
grant, not a purchase. The filter that fixed it lives in the shared module, so
both resources inherit it, and these tests cover both.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    PLAN_PRESENTATION,
    PRIVATE_PLAN_IDS,
)
from services.plan_limit_messaging import (
    next_plan_with_higher_allowance,
    plan_display_name,
    tracked_limit_detail,
)
from services.project_visibility_service import visibility_query_allowances
from services.target_keyword_limit_service import keyword_allowances

PROMPTS = ("prompt", "prompts")
KEYWORDS = ("keyword", "keywords")

RESOURCES = (
    ("prompts", visibility_query_allowances, PROMPTS),
    ("keywords", keyword_allowances, KEYWORDS),
)

PRIVATE_PLAN_LABELS = tuple(
    str(PLAN_PRESENTATION[plan]["name"]) for plan in sorted(PRIVATE_PLAN_IDS)
)


def _detail(plan: str, allowances: dict[str, int], nouns: tuple[str, str]) -> str:
    """The refusal a customer on ``plan`` sees when sitting exactly at the cap."""
    maximum = allowances[plan]
    singular, plural = nouns
    return tracked_limit_detail(
        plan=plan,
        used=maximum,
        maximum=maximum,
        allowances=allowances,
        noun_singular=singular,
        noun_plural=plural,
    )


# ---------------------------------------------------------------------------
# No refusal may name a private plan
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("resource,allowances_fn,nouns", RESOURCES)
@pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
def test_no_refusal_names_a_private_plan(resource, allowances_fn, nouns, plan) -> None:
    detail = _detail(plan, allowances_fn(), nouns)
    for label in PRIVATE_PLAN_LABELS:
        # The plan's own name is allowed: it is who the customer already is.
        if label == plan_display_name(plan):
            continue
        assert label not in detail, (
            f"the {resource} refusal for '{plan}' names the private plan "
            f"'{label}', which a customer cannot buy: {detail}"
        )


@pytest.mark.parametrize("resource,allowances_fn,nouns", RESOURCES)
@pytest.mark.parametrize("plan", CANONICAL_PLAN_TYPES)
def test_named_upgrade_target_is_never_private(resource, allowances_fn, nouns, plan) -> None:
    upgrade = next_plan_with_higher_allowance(plan, allowances_fn())
    if upgrade is None:
        return
    assert upgrade[0] not in PRIVATE_PLAN_IDS
    assert upgrade[0] != plan


# ---------------------------------------------------------------------------
# What each plan is now pointed at
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("resource,allowances_fn,nouns", RESOURCES)
def test_starter_is_pointed_at_a_purchasable_plan(resource, allowances_fn, nouns) -> None:
    """Was Agency Trial, which is a grant rather than a purchase."""
    upgrade = next_plan_with_higher_allowance("plan_starter", allowances_fn())
    assert upgrade is not None
    assert upgrade[0] == "plan_standard"
    assert "upgrade to Standard" in _detail("plan_starter", allowances_fn(), nouns)


@pytest.mark.parametrize("resource,allowances_fn,nouns", RESOURCES)
def test_agency_trial_keeps_a_sensible_target(resource, allowances_fn, nouns) -> None:
    """Excluding private plans must not leave the trial pointing at nothing.

    Standard does not raise the trial's allowance, so the answer is the next
    plan that does, exactly as it was before the filter existed.
    """
    upgrade = next_plan_with_higher_allowance("plan_agency_trial", allowances_fn())
    assert upgrade is not None
    assert upgrade[0] == "plan_specialist"

    detail = _detail("plan_agency_trial", allowances_fn(), nouns)
    assert "your Agency Trial plan tracks" in detail
    assert "upgrade to Specialist" in detail


@pytest.mark.parametrize("resource,allowances_fn,nouns", RESOURCES)
def test_top_plan_promises_no_upgrade(resource, allowances_fn, nouns) -> None:
    singular, _plural = nouns
    assert next_plan_with_higher_allowance("plan_executive", allowances_fn()) is None
    detail = _detail("plan_executive", allowances_fn(), nouns)
    assert "upgrade" not in detail.lower()
    assert f"Remove a {singular} you no longer track to add this one." in detail


# ---------------------------------------------------------------------------
# Wording is unchanged for every plan whose target was already public
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "plan,expected_target",
    [
        ("plan_agency_trial", "Specialist"),
        ("plan_standard", "Specialist"),
        ("plan_specialist", "Executive"),
    ],
)
def test_prompt_refusal_wording_is_unchanged_for_public_targets(plan, expected_target) -> None:
    """Excluding private plans must only move the Starter message.

    The numbers come from the live ladder (the Starter and trial prompt caps are
    env-overridable), the wording and the named plan are pinned.
    """
    allowances = visibility_query_allowances()
    maximum = allowances[plan]
    target_max = allowances[
        {"Specialist": "plan_specialist", "Executive": "plan_executive"}[expected_target]
    ]
    expected = (
        f"Prompt limit reached: your {plan_display_name(plan)} plan tracks "
        f"{maximum} prompts, {maximum} are in use and 0 remain. "
        f"Remove a prompt, or upgrade to {expected_target} to track {target_max}."
    )
    assert _detail(plan, allowances, PROMPTS) == expected


def test_executive_prompt_refusal_wording_is_unchanged() -> None:
    allowances = visibility_query_allowances()
    maximum = allowances["plan_executive"]
    expected = (
        f"Prompt limit reached: your Executive plan tracks {maximum} prompts, "
        f"{maximum} are in use and 0 remain. "
        "Remove a prompt you no longer track to add this one."
    )
    assert _detail("plan_executive", allowances, PROMPTS) == expected


def test_starter_prompt_refusal_names_standard_not_the_trial() -> None:
    """The one message this change moves, stated in full."""
    allowances = visibility_query_allowances()
    maximum = allowances["plan_starter"]
    standard_max = allowances["plan_standard"]
    expected = (
        f"Prompt limit reached: your Starter plan tracks {maximum} prompts, "
        f"{maximum} are in use and 0 remain. "
        f"Remove a prompt, or upgrade to Standard to track {standard_max}."
    )
    assert _detail("plan_starter", allowances, PROMPTS) == expected
    assert "Agency Trial" not in expected


# ---------------------------------------------------------------------------
# Mechanics
# ---------------------------------------------------------------------------


def test_an_unlimited_allowance_ranks_above_every_finite_cap() -> None:
    allowances = {"plan_standard": 10, "plan_specialist": 50, "plan_executive": -1}
    assert next_plan_with_higher_allowance("plan_specialist", allowances) == ("plan_executive", -1)
    detail = tracked_limit_detail(
        plan="plan_specialist",
        used=50,
        maximum=50,
        allowances=allowances,
        noun_singular="keyword",
        noun_plural="keywords",
    )
    assert "upgrade to Executive to track unlimited keywords." in detail


def test_a_plan_whose_only_higher_allowance_is_private_promises_no_upgrade() -> None:
    """The fallback wording, not an empty or self-referential sentence."""
    allowances = {"plan_starter": 5, "plan_agency_trial": 10}
    assert next_plan_with_higher_allowance("plan_starter", allowances) is None
    detail = tracked_limit_detail(
        plan="plan_starter",
        used=5,
        maximum=5,
        allowances=allowances,
        noun_singular="keyword",
        noun_plural="keywords",
    )
    assert detail.endswith("Remove a keyword you no longer track to add this one.")
    assert "Agency Trial" not in detail


def test_no_refusal_contains_an_em_dash() -> None:
    for _resource, allowances_fn, nouns in RESOURCES:
        for plan in CANONICAL_PLAN_TYPES:
            assert "\u2014" not in _detail(plan, allowances_fn(), nouns)
