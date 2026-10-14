from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from auth.credits import (
    PROVIDER_MULTIPLIER,
    calculate_audit_credit_cost_for_policy_version,
    calculate_multi_model_credit_cost_for_policy_version,
    normalize_audit_tier,
)
from services.cost_forecast_service import calculate_actual_audit_cost
from services.pricing_policy_service import (
    calculate_credits_from_real_cost,
    normalize_feature_tier_class,
)


@dataclass(frozen=True)
class AuditCreditResolution:
    estimated_credit_cost: int
    billable_credit_cost: int
    billed_provider: str
    billed_tier: str
    provider_changed: bool
    tier_changed: bool
    cost_changed: bool
    resolution_reason: str | None = None


def _normalize_provider(provider: str | None, *, fallback_provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    if normalized in PROVIDER_MULTIPLIER:
        return normalized
    fallback = str(fallback_provider or "").strip().lower()
    return fallback if fallback in PROVIDER_MULTIPLIER else "google"


def _resolve_debate_actual_credit_cost(
    *,
    full_report: dict[str, Any] | None,
    policy_version: str | None,
    billed_tier: str,
) -> int | None:
    metadata = full_report.get("metadata") if isinstance(full_report, dict) else None
    report_metadata = metadata if isinstance(metadata, dict) else {}
    ai_generation = (
        report_metadata.get("ai_generation")
        if isinstance(report_metadata.get("ai_generation"), dict)
        else {}
    )
    transcript = (
        ai_generation.get("transcript") if isinstance(ai_generation.get("transcript"), list) else []
    )
    usage_mode = str(ai_generation.get("mode") or "").strip().lower()
    if usage_mode != "debate" and not transcript:
        return None

    actual_cost = calculate_actual_audit_cost(
        report=full_report,
        policy_version=policy_version,
        feature_key="audit.main",
    )
    if actual_cost.step_count <= 0:
        return None

    actual_credit_cost, _ = calculate_credits_from_real_cost(
        real_cost_usd=actual_cost.total_cogs_usd,
        policy_version=policy_version,
        feature_key="audit.main",
        tier_class=normalize_feature_tier_class(billed_tier),
        billable=True,
    )
    return max(1, int(actual_credit_cost or 1))


def resolve_shadow_audit_credit_cost(
    *,
    full_report: dict[str, Any] | None,
    policy_version: str | None,
    billed_provider: str,
    billed_tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
    selected_models: list[str] | tuple[str, ...] | None = None,
) -> int:
    actual_cost = calculate_actual_audit_cost(
        report=full_report,
        policy_version=policy_version,
        feature_key="audit.main",
    )
    if actual_cost.step_count > 0:
        actual_credit_cost, _ = calculate_credits_from_real_cost(
            real_cost_usd=actual_cost.total_cogs_usd,
            policy_version=policy_version,
            feature_key="audit.main",
            tier_class=normalize_feature_tier_class(billed_tier),
            billable=True,
        )
        return max(1, int(actual_credit_cost or 1))

    resolved_selected_models = [
        str(model).strip().lower()
        for model in (selected_models or [])
        if str(model).strip().lower() in PROVIDER_MULTIPLIER
    ]
    if len(resolved_selected_models) >= 2:
        return max(
            1,
            int(
                calculate_multi_model_credit_cost_for_policy_version(
                    policy_version=policy_version,
                    selected_models=resolved_selected_models,
                    tier=billed_tier,
                    entities_count=entities_count,
                    category=category,
                    market=market,
                )
            ),
        )

    return max(
        1,
        int(
            calculate_audit_credit_cost_for_policy_version(
                policy_version=policy_version,
                provider=billed_provider,
                tier=billed_tier,
                entities_count=entities_count,
                category=category,
                market=market,
            )
        ),
    )


def resolve_audit_credit_resolution(
    *,
    full_report: dict[str, Any] | None,
    estimated_credit_cost: int,
    default_provider: str,
    default_tier: str,
    policy_version: str | None = None,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
    selected_models: list[str] | tuple[str, ...] | None = None,
) -> AuditCreditResolution:
    metadata = full_report.get("metadata") if isinstance(full_report, dict) else None
    report_metadata = metadata if isinstance(metadata, dict) else {}
    resolved_selected_models = [
        str(model).strip().lower()
        for model in (
            selected_models
            if selected_models is not None
            else report_metadata.get("selected_models", [])
        )
        if str(model).strip().lower() in PROVIDER_MULTIPLIER
    ]

    billed_provider = _normalize_provider(
        report_metadata.get("provider")
        if isinstance(report_metadata.get("provider"), str)
        else None,
        fallback_provider=default_provider,
    )
    billed_tier = normalize_audit_tier(
        report_metadata.get("tier")
        if isinstance(report_metadata.get("tier"), str)
        else default_tier
    )
    default_provider_normalized = _normalize_provider(default_provider, fallback_provider="google")
    default_tier_normalized = normalize_audit_tier(default_tier)
    billable_credit_cost = _resolve_debate_actual_credit_cost(
        full_report=full_report,
        policy_version=policy_version,
        billed_tier=billed_tier,
    )
    resolution_reason = None
    if billable_credit_cost is None:
        if len(resolved_selected_models) >= 2:
            billable_credit_cost = max(
                1,
                int(
                    calculate_multi_model_credit_cost_for_policy_version(
                        policy_version=policy_version,
                        selected_models=resolved_selected_models,
                        tier=billed_tier,
                        entities_count=entities_count,
                        category=category,
                        market=market,
                    )
                ),
            )
            resolution_reason = "multi_model_selected_models"
        else:
            billable_credit_cost = max(
                1,
                int(
                    calculate_audit_credit_cost_for_policy_version(
                        policy_version=policy_version,
                        provider=billed_provider,
                        tier=billed_tier,
                        entities_count=entities_count,
                        category=category,
                        market=market,
                    )
                ),
            )
    else:
        resolution_reason = "debate_actual_usage_cost"
    estimated_normalized = max(1, int(estimated_credit_cost or 1))
    provider_changed = billed_provider != default_provider_normalized
    tier_changed = billed_tier != default_tier_normalized
    cost_changed = billable_credit_cost != estimated_normalized
    if resolution_reason is None and (provider_changed or tier_changed or cost_changed):
        resolution_reason = "final_provider_tier_differs_from_routed_estimate"
    return AuditCreditResolution(
        estimated_credit_cost=estimated_normalized,
        billable_credit_cost=billable_credit_cost,
        billed_provider=billed_provider,
        billed_tier=billed_tier,
        provider_changed=provider_changed,
        tier_changed=tier_changed,
        cost_changed=cost_changed,
        resolution_reason=resolution_reason,
    )
