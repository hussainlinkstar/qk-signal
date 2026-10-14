import sys
from decimal import Decimal
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.pricing_matrix import canonicalize_model_name, get_token_pricing_for_model  # noqa: E402
from services.billing_calculator import (  # noqa: E402
    BASE_CREDIT_VALUE_USD,
    MAX_CREDITS_PER_CALL,
    calculate_dynamic_billing,
)
from services.pricing_policy_service import get_pricing_policy  # noqa: E402


def test_dynamic_billing_is_plan_agnostic_for_same_usage() -> None:
    usage = {"prompt_tokens": 12000, "completion_tokens": 4000}

    plan_standard = calculate_dynamic_billing(
        model_name="gpt-5.4",
        usage=usage,
        plan_type="plan_standard",
    )
    singularity = calculate_dynamic_billing(
        model_name="gpt-5.4",
        usage=usage,
        plan_type="plan_executive",
    )

    assert plan_standard.credits_to_deduct == singularity.credits_to_deduct
    assert plan_standard.credit_value_usd == Decimal("0.100000")
    assert singularity.credit_value_usd == Decimal("0.100000")
    assert plan_standard.credit_value_usd == BASE_CREDIT_VALUE_USD.quantize(Decimal("0.000001"))


def test_dynamic_billing_caps_runaway_costs_per_call() -> None:
    billing = calculate_dynamic_billing(
        model_name="claude-opus-4-6",
        usage={"prompt_tokens": 2_000_000, "completion_tokens": 1_000_000},
        plan_type="plan_specialist",
    )

    policy = get_pricing_policy()
    generic_cap = policy.resolve_feature_rule("generic.ai", "fast").cap_credits
    assert billing.credits_to_deduct == min(MAX_CREDITS_PER_CALL, generic_cap)


def test_dynamic_billing_uses_premium_opus_rate() -> None:
    billing = calculate_dynamic_billing(
        model_name="claude-opus-4-6",
        usage={"prompt_tokens": 13_717, "completion_tokens": 4_088},
        plan_type="plan_specialist",
    )

    assert billing.token_cost_usd == Decimal("0.170785")


def test_pricing_matrix_normalizes_historical_claude_aliases() -> None:
    canonical_pricing = get_token_pricing_for_model("claude-opus-4-6")
    aliased_pricing = get_token_pricing_for_model("claude-4-6-opus")

    assert canonicalize_model_name("claude-4-6-opus") == "claude-opus-4-6"
    assert aliased_pricing == canonical_pricing


def test_dynamic_billing_returns_zero_when_usage_missing() -> None:
    billing = calculate_dynamic_billing(
        model_name="gemini-2.5-flash",
        usage=None,
        plan_type=None,
    )

    assert billing.base_cost_usd == Decimal("0.000000")
    assert billing.target_retail_price_usd == Decimal("0.000000")
    assert billing.credits_to_deduct == 0
