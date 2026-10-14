"""Phase 5.1 — value-ladder capability mapping (Qiko Signal).

Asserts the capability matrix encodes the approved value ladder so Phase 5.2
can gate the UI consistently:

  * AI recommendations (Advisor)            -> Standard+
  * Competitor view + Comparison search     -> Specialist+ (has_competitor_analysis)
  * API read                                -> Specialist+ (api_access)
  * White-label / custom domain / execution -> Executive+
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config.plans import CANONICAL_PLAN_TYPES, get_plan_capabilities, get_plan_weight


def test_standard_unlocks_advisor_not_competitor() -> None:
    std = get_plan_capabilities("plan_standard")
    assert std["has_advisor_recommendations"] is True  # Standard+
    assert std["has_competitor_analysis"] is False  # Specialist+
    assert std["has_done_for_you_execution"] is False  # Executive+
    assert std["has_white_label"] is False
    assert std["api_access"] is False


def test_specialist_unlocks_competitor_and_api() -> None:
    spec = get_plan_capabilities("plan_specialist")
    assert spec["has_advisor_recommendations"] is True
    assert spec["has_competitor_analysis"] is True
    assert spec["api_access"] is True
    assert spec["has_done_for_you_execution"] is False  # Executive+
    assert spec["has_white_label"] is False


def test_executive_unlocks_execution() -> None:
    exe = get_plan_capabilities("plan_executive")
    assert exe["has_done_for_you_execution"] is True
    assert exe["can_use_workflow_automations"] is True


def test_white_label_is_executive_only() -> None:
    # White-label, custom domain and multiple workspaces are Executive
    # entitlements. Asserted across every plan so re-enabling them anywhere
    # else has to be a deliberate change to this expectation.
    for plan in CANONICAL_PLAN_TYPES:
        caps = get_plan_capabilities(plan)
        expected = plan == "plan_executive"
        assert caps["has_white_label"] is expected, plan
        assert caps["pdf_white_label"] is expected, plan
        assert caps["has_custom_domain"] is expected, plan
        assert caps["has_multi_workspace_federation"] is expected, plan


def test_starter_locks_advisor() -> None:
    starter = get_plan_capabilities("plan_starter")
    assert starter["has_advisor_recommendations"] is False
    assert starter["has_competitor_analysis"] is False
    assert starter["has_done_for_you_execution"] is False


def test_executive_is_the_top_tier() -> None:
    # Executive is the highest tier in the catalog, so nothing may outrank it.
    executive_weight = get_plan_weight("plan_executive")
    for plan in CANONICAL_PLAN_TYPES:
        assert get_plan_weight(plan) <= executive_weight, plan
