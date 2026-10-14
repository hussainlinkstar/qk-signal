from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from core.pricing_matrix import get_token_pricing_for_model
from services.pricing_policy_service import (
    calculate_credits_from_real_cost,
    get_pricing_policy,
    normalize_feature_tier_class,
)


_DEFAULT_BASE_POLICY = get_pricing_policy()
DEFAULT_TARGET_MARGIN = _DEFAULT_BASE_POLICY.target_margin
BASE_CREDIT_VALUE_USD = _DEFAULT_BASE_POLICY.credit_value_usd
TARGET_RETAIL_SHARE = Decimal("0.30")
MAX_CREDITS_PER_CALL = _DEFAULT_BASE_POLICY.max_credits_per_call


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class NormalizedAIUsage:
    prompt_tokens: int
    completion_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class BillingComputation:
    policy_version: str
    feature_key: str
    tier_class: str
    model_name: str
    pricing_currency: str
    fallback_level: int
    retry_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    input_cost_per_million_usd: Decimal
    output_cost_per_million_usd: Decimal
    token_cost_usd: Decimal
    base_cost_usd: Decimal
    infra_alloc_usd: Decimal
    orchestration_usd: Decimal
    retry_risk_usd: Decimal
    real_cost_usd: Decimal
    safety_multiplier: Decimal
    floor_credits: int
    cap_credits: int
    target_margin: Decimal
    target_retail_price_usd: Decimal
    implied_revenue_usd: Decimal
    margin_usd: Decimal
    margin_pct: Decimal | None
    effective_credit_value_usd: Decimal
    credit_value_usd: Decimal
    credits_to_deduct: int
    plan_type: str | None


def normalize_usage_payload(usage: dict[str, Any] | None) -> NormalizedAIUsage:
    payload = usage if isinstance(usage, dict) else {}
    prompt_tokens = int(
        payload.get("prompt_tokens")
        or payload.get("input_tokens")
        or payload.get("prompt_token_count")
        or 0
    )
    completion_tokens = int(
        payload.get("completion_tokens")
        or payload.get("output_tokens")
        or payload.get("candidates_token_count")
        or payload.get("completion_token_count")
        or 0
    )
    return NormalizedAIUsage(
        prompt_tokens=max(0, prompt_tokens),
        completion_tokens=max(0, completion_tokens),
    )


def calculate_dynamic_billing(
    *,
    model_name: str,
    usage: dict[str, Any] | None,
    plan_type: str | None,
    feature_key: str = "generic.ai",
    tier_class: str = "fast",
    policy_version: str | None = None,
    fallback_level: int = 0,
    retry_count: int = 0,
    orchestration_hops: int = 0,
) -> BillingComputation:
    normalized_usage = normalize_usage_payload(usage)
    normalized_feature_key = str(feature_key or "generic.ai").strip().lower() or "generic.ai"
    normalized_tier_class = normalize_feature_tier_class(tier_class)
    policy = get_pricing_policy(policy_version)
    pricing = get_token_pricing_for_model(model_name)

    token_cost_usd = (Decimal(normalized_usage.prompt_tokens) / Decimal("1000000")) * pricing[
        "input"
    ] + (Decimal(normalized_usage.completion_tokens) / Decimal("1000000")) * pricing["output"]
    infra_alloc_usd = (
        policy.resolve_infra_alloc(normalized_feature_key)
        if normalized_usage.total_tokens > 0
        else Decimal("0")
    )
    orchestration_usd = (
        policy.resolve_orchestration_cost(normalized_feature_key)
        * Decimal(max(0, int(orchestration_hops)))
        if normalized_usage.total_tokens > 0
        else Decimal("0")
    )
    retry_risk_usd = (
        (token_cost_usd + orchestration_usd)
        * policy.retry_risk_rate
        * Decimal(max(0, int(retry_count)))
        if normalized_usage.total_tokens > 0
        else Decimal("0")
    )
    real_cost_usd = token_cost_usd + infra_alloc_usd + orchestration_usd + retry_risk_usd

    credits_to_deduct, tier_rule = calculate_credits_from_real_cost(
        real_cost_usd=real_cost_usd,
        policy_version=policy.version,
        feature_key=normalized_feature_key,
        tier_class=normalized_tier_class,
        billable=normalized_usage.total_tokens > 0,
    )

    target_retail_price_usd = policy.credit_value_usd * Decimal(credits_to_deduct)
    implied_revenue_usd = target_retail_price_usd
    margin_usd = implied_revenue_usd - real_cost_usd
    margin_pct = (margin_usd / implied_revenue_usd) if implied_revenue_usd > 0 else None

    return BillingComputation(
        policy_version=policy.version,
        feature_key=normalized_feature_key,
        tier_class=normalized_tier_class,
        model_name=model_name,
        pricing_currency="USD",
        fallback_level=max(0, int(fallback_level)),
        retry_count=max(0, int(retry_count)),
        prompt_tokens=normalized_usage.prompt_tokens,
        completion_tokens=normalized_usage.completion_tokens,
        total_tokens=normalized_usage.total_tokens,
        input_cost_per_million_usd=_quantize(pricing["input"]),
        output_cost_per_million_usd=_quantize(pricing["output"]),
        token_cost_usd=_quantize(token_cost_usd),
        base_cost_usd=_quantize(token_cost_usd),
        infra_alloc_usd=_quantize(infra_alloc_usd),
        orchestration_usd=_quantize(orchestration_usd),
        retry_risk_usd=_quantize(retry_risk_usd),
        real_cost_usd=_quantize(real_cost_usd),
        safety_multiplier=_quantize(tier_rule.safety_multiplier),
        floor_credits=max(0, int(tier_rule.floor_credits)),
        cap_credits=max(0, int(tier_rule.cap_credits)),
        target_margin=_quantize(policy.target_margin),
        target_retail_price_usd=_quantize(target_retail_price_usd),
        implied_revenue_usd=_quantize(implied_revenue_usd),
        margin_usd=_quantize(margin_usd),
        margin_pct=_quantize(margin_pct) if isinstance(margin_pct, Decimal) else None,
        effective_credit_value_usd=_quantize(policy.credit_value_usd),
        credit_value_usd=_quantize(policy.credit_value_usd),
        credits_to_deduct=max(0, int(credits_to_deduct)),
        plan_type=str(plan_type or "").strip().lower() or None,
    )
