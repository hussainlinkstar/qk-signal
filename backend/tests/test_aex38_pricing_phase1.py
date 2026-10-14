"""Tests for AEX-38 Phase 1: Pricing & Plan Evolution — Bug Fixes & Quick Wins."""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import (
    PLAN_WEIGHTS,
    can_use_feature,
    plan_meets_requirement,
)
from billing.router import list_plans
from services.public_plan_catalog import build_public_plan_catalog


class _FakeConfig:
    def price_id_for(self, plan, interval: str = "month") -> str:
        return f"price_{plan.value}"


# ---------------------------------------------------------------------------
# P1: PLAN_WEIGHTS fix — plan_agency_trial must be below plan_specialist
# ---------------------------------------------------------------------------


def test_plan_agency_trial_weight_is_below_plan_specialist():
    """plan_agency_trial (5) < plan_standard (10) < plan_specialist (20)."""
    assert PLAN_WEIGHTS["plan_agency_trial"] < PLAN_WEIGHTS["plan_standard"]
    assert PLAN_WEIGHTS["plan_agency_trial"] < PLAN_WEIGHTS["plan_specialist"]


def test_plan_agency_trial_does_not_meet_plan_specialist_requirement():
    """plan_meets_requirement must return False for plan_agency_trial vs plan_specialist."""
    assert plan_meets_requirement("plan_agency_trial", "plan_specialist") is False
    assert plan_meets_requirement("plan_agency_trial", "plan_standard") is False


def test_plan_agency_trial_can_use_feature_via_direct_capability():
    """plan_agency_trial still accesses features that are True in its CAPABILITY_MATRIX entry."""
    assert can_use_feature("plan_agency_trial", "has_competitor_analysis") is True
    assert can_use_feature("plan_agency_trial", "api_access") is True


def test_plan_agency_trial_cannot_use_feature_via_weight_fallback():
    """Features only gated by MINIMUM_PLAN_BY_FEATURE at plan_specialist should
    NOT be granted to plan_agency_trial via weight comparison anymore."""
    assert can_use_feature("plan_agency_trial", "has_white_label") is False
    assert can_use_feature("plan_agency_trial", "has_sla_guarantee") is False


# ---------------------------------------------------------------------------
# P2: /billing/plans/public — unauthenticated, no plan_agency_trial
# ---------------------------------------------------------------------------


def test_list_plans_public_excludes_plan_agency_trial():
    payload = build_public_plan_catalog()
    plan_ids = [p["id"] for p in payload["plans"]]

    assert "plan_agency_trial" not in plan_ids
    assert plan_ids == [
        "plan_starter",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    ]


def test_only_a_custom_priced_plan_may_hide_its_price():
    """A plan hides its price only by being declared custom priced.

    This test used to assert that *no* public plan hides a price, because at
    the time all four were self-service. SIGV2-1211 made Executive "Contact
    Us", so the assertion is inverted rather than dropped: a missing figure is
    now allowed, but only where ``has_custom_pricing`` says so and only with a
    contact CTA. That keeps the original guard's force, which was to stop a
    plan silently publishing no price.
    """
    payload = build_public_plan_catalog()

    hidden = set()
    for plan in payload["plans"]:
        if plan["monthly_price_usd"] is None:
            assert plan["has_custom_pricing"] is True, plan["id"]
            assert plan["cta"] == "contact", plan["id"]
            hidden.add(plan["id"])
        else:
            assert isinstance(plan["monthly_price_usd"], int), plan["id"]
            assert plan["has_custom_pricing"] is False, plan["id"]
            assert plan["cta"] == "self_serve", plan["id"]

    assert hidden == {"plan_executive"}


def test_list_plans_public_shows_prices_for_standard_plans():
    payload = build_public_plan_catalog()
    plans_by_id = {p["id"]: p for p in payload["plans"]}

    # The tiers Edward approved on 8 Oct (SIGV2-1211).
    assert plans_by_id["plan_starter"]["monthly_price_usd"] == 0
    assert plans_by_id["plan_standard"]["monthly_price_usd"] == 49
    assert plans_by_id["plan_specialist"]["monthly_price_usd"] == 99
    # Executive is negotiated, so the public payload quotes nothing.
    assert plans_by_id["plan_executive"]["monthly_price_usd"] is None


def test_list_plans_public_excludes_credit_pricing():
    payload = build_public_plan_catalog()
    assert "credit_price_usd" not in payload


# ---------------------------------------------------------------------------
# P3/P5: /billing/plans no longer exposes top-up metadata
# ---------------------------------------------------------------------------


def test_list_plans_excludes_credit_metadata(monkeypatch):
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    assert "credit_price_usd" not in payload
    assert "top_up_max_credits" not in payload


def test_list_plans_capabilities_carry_no_internal_credit_keys(monkeypatch):
    """Credits are the internal cost unit (SIGV2-1102). /billing/plans is
    authenticated but customer-facing, so the embedded capability matrix must
    not serve internal-only keys such as credits_per_month. The staff plans
    screen reads the full matrix through admin.py instead."""
    user = SimpleNamespace(subscription=None)
    monkeypatch.setattr(
        "billing.router.get_billing_config", lambda _request, _db=None: _FakeConfig()
    )

    payload = list_plans(http_request=None, user=user, db=None)
    for plan in payload["plans"]:
        capabilities = plan.get("capabilities") or {}
        credit_keys = [key for key in capabilities if "credit" in key.lower()]
        assert credit_keys == [], f"{plan.get('id')} serves credit fields: {credit_keys}"
        # A genuine capability still comes through, so the filter is selective.
        assert "max_audits" in capabilities
