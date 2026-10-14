"""Contract test: benchmark_intelligence project feature gate must track
`has_competitor_analysis`, the same capability key enforced by the real
Competitive Intelligence API endpoints in workspace_router.py.

Regression coverage for a latent contract mismatch where the
`benchmark_intelligence` UI gate was keyed on `entity_authority` (a
different, unrelated capability backing entity_authority_router.py)
instead of `has_competitor_analysis`.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.config.plans import MINIMUM_PLAN_BY_FEATURE, PLAN_PRESENTATION, can_use_feature
from services.project_intelligence_service import (
    _FEATURE_RULES,
    build_project_feature_access,
    resolve_project_capability_access,
)


def _make_user(
    plan_type: str,
    *,
    status: str = "active",
    trial_plan: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        subscription=SimpleNamespace(plan_type=plan_type, status=status),
        trial_plan=trial_plan,
    )


def test_benchmark_intelligence_rule_uses_has_competitor_analysis_capability() -> None:
    """Lock in the capability key so the UI gate and the API gate never drift again."""
    assert _FEATURE_RULES["benchmark_intelligence"].capability_key == "has_competitor_analysis"


def test_benchmark_intelligence_access_denied_when_plan_lacks_competitor_analysis() -> None:
    # plan_standard does not include has_competitor_analysis (nor entity_authority).
    user = _make_user("plan_standard")

    access = build_project_feature_access(user)["benchmark_intelligence"]

    assert can_use_feature("plan_standard", "has_competitor_analysis") is False
    assert access["allowed"] is False
    assert access["allowed"] == can_use_feature("plan_standard", "has_competitor_analysis")


def test_benchmark_intelligence_access_allowed_when_plan_has_competitor_analysis() -> None:
    # plan_specialist includes has_competitor_analysis (and entity_authority).
    user = _make_user("plan_specialist")

    access = build_project_feature_access(user)["benchmark_intelligence"]

    assert can_use_feature("plan_specialist", "has_competitor_analysis") is True
    assert access["allowed"] is True
    assert access["allowed"] == can_use_feature("plan_specialist", "has_competitor_analysis")


def test_pending_specialist_does_not_unlock_benchmark_intelligence() -> None:
    user = _make_user("plan_specialist", status="pending")

    access = build_project_feature_access(user)["benchmark_intelligence"]

    assert access["allowed"] is False


def test_advisor_recommendations_rule_uses_has_advisor_recommendations_capability() -> None:
    """SIGV2-1134: the Advisor action plan and every preview of it, one key.

    The project dashboard's top-three preview card used to gate on
    ``automations`` (``can_use_workflow_automations``, Specialist and up) while
    the action plan page it previews was included from Standard up, so a
    Standard customer could open the full plan and was told on the dashboard to
    upgrade to Specialist to preview it. Both surfaces now read this key.
    """
    assert _FEATURE_RULES["advisor_recommendations"].capability_key == "has_advisor_recommendations"
    assert _FEATURE_RULES["advisor_recommendations"].required_plan == "Standard"
    # The two are genuinely different features, so the keys must stay distinct.
    assert (
        _FEATURE_RULES["automations"].capability_key
        != _FEATURE_RULES["advisor_recommendations"].capability_key
    )


def test_standard_plan_owns_the_advisor_plan_but_not_workflow_automations() -> None:
    user = _make_user("plan_standard")

    access = build_project_feature_access(user)

    assert can_use_feature("plan_standard", "has_advisor_recommendations") is True
    assert access["advisor_recommendations"]["allowed"] is True
    assert access["advisor_recommendations"]["required_plan"] is None
    # The capability that used to gate the preview, for contrast.
    assert access["automations"]["allowed"] is False


def test_starter_plan_is_told_the_plan_it_needs_for_the_advisor_plan() -> None:
    user = _make_user("plan_starter")

    access = build_project_feature_access(user)["advisor_recommendations"]

    assert can_use_feature("plan_starter", "has_advisor_recommendations") is False
    assert access["allowed"] is False
    assert access["required_plan"] == "Standard"
    assert "Standard" in str(access["detail"])


def test_pending_paid_plan_falls_back_to_trial_capabilities() -> None:
    user = _make_user(
        "plan_executive",
        status="pending",
        trial_plan="plan_agency_trial",
    )

    access = build_project_feature_access(user)["benchmark_intelligence"]

    assert access["allowed"] is True


# SIGV2-1221. Every project feature rule used to carry a hand-written plan name
# and a hand-written sentence containing it, and nothing checked either against
# the capability the rule gates on. "Project monitoring requires Standard or
# higher" was the result: `MINIMUM_PLAN_BY_FEATURE` puts `has_performance_sync`
# on `plan_starter`, so every plan grants it, the rule can never deny anyone,
# and the plan it named would have sold an upgrade that changed nothing. A
# wrong plan name is a passing test until something computes the right one.
def test_every_feature_rule_names_the_plan_its_capability_requires() -> None:
    for feature_key, rule in _FEATURE_RULES.items():
        expected_plan = MINIMUM_PLAN_BY_FEATURE.get(rule.capability_key)
        assert expected_plan is not None, (feature_key, rule.capability_key)

        if expected_plan == "plan_starter":
            # Nothing to upgrade to, so the rule may not name a plan at all.
            assert rule.required_plan is None, feature_key
            continue

        expected_label = PLAN_PRESENTATION[expected_plan]["name"]
        assert rule.required_plan == expected_label, feature_key
        assert expected_label in rule.detail, feature_key


def test_the_plan_a_rule_names_actually_grants_the_capability() -> None:
    for feature_key, rule in _FEATURE_RULES.items():
        required_plan = MINIMUM_PLAN_BY_FEATURE[rule.capability_key]
        assert can_use_feature(required_plan, rule.capability_key) is True, feature_key


def test_monitoring_is_granted_on_every_plan_so_it_names_none() -> None:
    rule = _FEATURE_RULES["monitoring"]

    assert MINIMUM_PLAN_BY_FEATURE[rule.capability_key] == "plan_starter"
    assert rule.required_plan is None
    assert "Standard" not in rule.detail
    # And the gate itself can never deny anyone, on any plan.
    for plan in ("plan_starter", "plan_standard", "plan_specialist", "plan_executive"):
        assert build_project_feature_access(_make_user(plan))["monitoring"]["allowed"] is True


def test_capability_access_derives_the_plan_rather_than_taking_one() -> None:
    # The helper the routers call takes a subject, never a plan: a router
    # cannot state a plan that does not hold the capability it is gating on.
    access = resolve_project_capability_access(
        _make_user("plan_standard"),
        capability_key="api_access",
        subject="The AI Search Volatility Index",
    )

    assert access["allowed"] is False
    assert access["required_plan"] == PLAN_PRESENTATION["plan_specialist"]["name"]
    assert access["detail"] == "The AI Search Volatility Index requires Specialist or higher."
