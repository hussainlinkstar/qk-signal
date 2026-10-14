import sys
from decimal import Decimal
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.pricing_policy_service import (  # noqa: E402
    calculate_audit_credit_cost_for_policy,
    calculate_credits_from_real_cost,
    get_pricing_policy,
)


def test_pricing_policies_are_loadable() -> None:
    current = get_pricing_policy()
    v1 = get_pricing_policy("v1")
    v2 = get_pricing_policy("v2")
    v3 = get_pricing_policy("v3")

    assert current.version == "v3"
    assert v1.version == "v1"
    assert v2.version == "v2"
    assert v3.version == "v3"
    assert v1.credit_value_usd > 0
    assert v2.credit_value_usd > 0
    assert v3.credit_value_usd > 0


def test_v2_audit_pricing_increases_deep_tier_cost() -> None:
    v1_cost = calculate_audit_credit_cost_for_policy(
        policy_version="v1",
        provider="openai",
        tier="smart",
        entities_count=6,
        category="tech",
        market="ro",
    )
    v2_cost = calculate_audit_credit_cost_for_policy(
        policy_version="v2",
        provider="openai",
        tier="smart",
        entities_count=6,
        category="tech",
        market="ro",
    )

    assert v2_cost >= v1_cost


def test_credit_charge_enforces_policy_cap() -> None:
    credits, rule = calculate_credits_from_real_cost(
        real_cost_usd=Decimal("9999"),
        policy_version="v1",
        feature_key="generic.ai",
        tier_class="fast",
        billable=True,
    )

    assert credits == min(rule.cap_credits, get_pricing_policy("v1").max_credits_per_call)
