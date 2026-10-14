from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy.orm import Session

import models
from services.billing_calculator import BillingComputation
from services.pricing_policy_service import get_pricing_policy, normalize_feature_tier_class


def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return Decimal("0")
        return Decimal(cleaned)
    return Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


def record_ai_economics_ledger_entry(
    db: Session,
    *,
    policy_version: str,
    feature_key: str,
    tier_class: str,
    routing_profile: str | None,
    provider: str | None,
    model: str | None,
    fallback_level: int = 0,
    input_tokens: int = 0,
    output_tokens: int = 0,
    token_cost_usd: Decimal | int | float | str | None = None,
    infra_alloc_usd: Decimal | int | float | str | None = None,
    orchestration_usd: Decimal | int | float | str | None = None,
    retry_risk_usd: Decimal | int | float | str | None = None,
    credits_charged: int = 0,
    credit_unit_value_usd: Decimal | int | float | str | None = None,
    request_id: str | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
    user_id: int | None = None,
    shadow_policy_version: str | None = None,
    shadow_credits_charged: int | None = None,
    payload: dict[str, Any] | None = None,
) -> models.AIEconomicsLedgerEntry:
    normalized_policy = get_pricing_policy(policy_version).version
    normalized_feature = str(feature_key or "generic.ai").strip().lower() or "generic.ai"
    normalized_tier_class = normalize_feature_tier_class(tier_class)
    normalized_input_tokens = max(0, int(input_tokens or 0))
    normalized_output_tokens = max(0, int(output_tokens or 0))
    total_tokens = normalized_input_tokens + normalized_output_tokens

    token_component = _to_decimal(token_cost_usd)
    infra_component = _to_decimal(infra_alloc_usd)
    orchestration_component = _to_decimal(orchestration_usd)
    retry_component = _to_decimal(retry_risk_usd)
    unit_value = _to_decimal(credit_unit_value_usd)
    if unit_value <= 0:
        unit_value = get_pricing_policy(normalized_policy).credit_value_usd

    normalized_credits = max(0, int(credits_charged or 0))
    real_cost = token_component + infra_component + orchestration_component + retry_component
    implied_revenue = unit_value * Decimal(normalized_credits)
    margin_usd = implied_revenue - real_cost
    margin_pct = (margin_usd / implied_revenue) if implied_revenue > 0 else None
    payload_json = dict(payload or {})

    entry = models.AIEconomicsLedgerEntry(
        policy_version=normalized_policy,
        feature_key=normalized_feature,
        tier_class=normalized_tier_class,
        routing_profile=str(routing_profile).strip() if isinstance(routing_profile, str) else None,
        provider=str(provider).strip().lower() if isinstance(provider, str) and provider else None,
        model=str(model).strip() if isinstance(model, str) and model else None,
        fallback_level=max(0, int(fallback_level or 0)),
        input_tokens=normalized_input_tokens,
        output_tokens=normalized_output_tokens,
        total_tokens=total_tokens,
        token_cost_usd=_quantize(token_component),
        infra_alloc_usd=_quantize(infra_component),
        orchestration_usd=_quantize(orchestration_component),
        retry_risk_usd=_quantize(retry_component),
        real_cost_usd=_quantize(real_cost),
        credits_charged=normalized_credits,
        credit_unit_value_usd=_quantize(unit_value),
        implied_revenue_usd=_quantize(implied_revenue),
        margin_usd=_quantize(margin_usd),
        margin_pct=_quantize(margin_pct) if isinstance(margin_pct, Decimal) else None,
        request_id=str(request_id).strip() if isinstance(request_id, str) and request_id else None,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        shadow_policy_version=(
            str(shadow_policy_version).strip().lower()
            if isinstance(shadow_policy_version, str) and shadow_policy_version
            else None
        ),
        shadow_credits_charged=(
            max(0, int(shadow_credits_charged)) if shadow_credits_charged is not None else None
        ),
        payload_json=payload_json,
        schema_version="2",
    )
    db.add(entry)
    return entry


def record_billing_event_to_ledger(
    db: Session,
    *,
    billing: BillingComputation,
    provider: str | None,
    feature_key: str,
    request_id: str | None = None,
    workspace_id: int | None = None,
    project_id: int | None = None,
    user_id: int | None = None,
    routing_profile: str | None = None,
    shadow_policy_version: str | None = None,
    shadow_credits_charged: int | None = None,
    payload: dict[str, Any] | None = None,
) -> models.AIEconomicsLedgerEntry:
    return record_ai_economics_ledger_entry(
        db,
        policy_version=billing.policy_version,
        feature_key=feature_key,
        tier_class=billing.tier_class,
        routing_profile=routing_profile,
        provider=provider,
        model=billing.model_name,
        fallback_level=billing.fallback_level,
        input_tokens=billing.prompt_tokens,
        output_tokens=billing.completion_tokens,
        token_cost_usd=billing.token_cost_usd,
        infra_alloc_usd=billing.infra_alloc_usd,
        orchestration_usd=billing.orchestration_usd,
        retry_risk_usd=billing.retry_risk_usd,
        credits_charged=billing.credits_to_deduct,
        credit_unit_value_usd=billing.effective_credit_value_usd,
        request_id=request_id,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        shadow_policy_version=shadow_policy_version,
        shadow_credits_charged=shadow_credits_charged,
        payload=payload,
    )
