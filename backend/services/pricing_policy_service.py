from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal


DEFAULT_POLICY_VERSION = "v3"

AUDIT_TIER_ALIASES: dict[str, str] = {
    "standard": "fast",
    "deep": "smart",
}


@dataclass(frozen=True)
class FeatureTierRule:
    safety_multiplier: Decimal
    floor_credits: int
    cap_credits: int


@dataclass(frozen=True)
class PricingPolicy:
    version: str
    credit_value_usd: Decimal
    target_margin: Decimal
    provider_multipliers: dict[str, Decimal]
    tier_multipliers: dict[str, Decimal]
    feature_rules: dict[str, dict[str, FeatureTierRule]]
    max_credits_per_call: int
    synthesis_credit_cost: int
    prompt_recommendation_credit_cost: int
    infra_alloc_usd_by_feature: dict[str, Decimal]
    orchestration_usd_by_feature: dict[str, Decimal]
    retry_risk_rate: Decimal

    def resolve_feature_rule(self, feature_key: str, tier_class: str) -> FeatureTierRule:
        normalized_feature = str(feature_key or "").strip().lower() or "generic.ai"
        normalized_tier = normalize_feature_tier_class(tier_class)
        feature_config = (
            self.feature_rules.get(normalized_feature) or self.feature_rules["generic.ai"]
        )
        return (
            feature_config.get(normalized_tier)
            or feature_config.get("default")
            or self.feature_rules["generic.ai"]["default"]
        )

    def resolve_provider_multiplier(self, provider: str | None) -> Decimal:
        normalized_provider = str(provider or "").strip().lower()
        return self.provider_multipliers.get(normalized_provider, Decimal("1.0"))

    def resolve_tier_multiplier(self, tier: str | None) -> Decimal:
        normalized_tier = normalize_audit_tier(tier)
        return self.tier_multipliers.get(normalized_tier, Decimal("1.0"))

    def resolve_infra_alloc(self, feature_key: str) -> Decimal:
        normalized_feature = str(feature_key or "").strip().lower()
        return self.infra_alloc_usd_by_feature.get(
            normalized_feature,
            self.infra_alloc_usd_by_feature.get("default", Decimal("0")),
        )

    def resolve_orchestration_cost(self, feature_key: str) -> Decimal:
        normalized_feature = str(feature_key or "").strip().lower()
        return self.orchestration_usd_by_feature.get(
            normalized_feature,
            self.orchestration_usd_by_feature.get("default", Decimal("0")),
        )


def normalize_audit_tier(tier: str | None) -> str:
    cleaned = str(tier or "").strip().lower()
    if not cleaned:
        return "fast"
    return AUDIT_TIER_ALIASES.get(cleaned, cleaned)


def normalize_feature_tier_class(tier: str | None) -> str:
    normalized = normalize_audit_tier(tier)
    if normalized in {"smart", "deep_judgment"}:
        return "deep"
    return "fast"


def _as_decimal(value: str) -> Decimal:
    return Decimal(str(value).strip())


def _build_rule(*, safety_multiplier: str, floor_credits: int, cap_credits: int) -> FeatureTierRule:
    return FeatureTierRule(
        safety_multiplier=_as_decimal(safety_multiplier),
        floor_credits=max(0, int(floor_credits)),
        cap_credits=max(0, int(cap_credits)),
    )


def _build_policies() -> dict[str, PricingPolicy]:
    common_providers = {
        "google": _as_decimal("1.0"),
        "openai": _as_decimal("2.0"),
        "anthropic": _as_decimal("1.5"),
        "xai": _as_decimal("1.5"),
        "deepseek": _as_decimal("0.8"),
    }
    common_tiers = {
        "fast": _as_decimal("1.0"),
        "smart": _as_decimal("3.0"),
        "deep_judgment": _as_decimal("3.0"),
        "lite": _as_decimal("0.5"),
    }

    policies: dict[str, PricingPolicy] = {
        "v1": PricingPolicy(
            version="v1",
            credit_value_usd=_as_decimal("0.10"),
            target_margin=_as_decimal("0.70"),
            provider_multipliers=common_providers,
            tier_multipliers=common_tiers,
            feature_rules={
                "audit.main": {
                    "fast": _build_rule(safety_multiplier="1.0", floor_credits=1, cap_credits=200),
                    "deep": _build_rule(safety_multiplier="1.0", floor_credits=1, cap_credits=200),
                    "default": _build_rule(
                        safety_multiplier="1.0", floor_credits=1, cap_credits=200
                    ),
                },
                "content_brief.generate": {
                    "deep": _build_rule(
                        safety_multiplier="3.333333", floor_credits=1, cap_credits=200
                    ),
                    "default": _build_rule(
                        safety_multiplier="3.333333", floor_credits=1, cap_credits=200
                    ),
                },
                "aeo_mentions.analyze_batch": {
                    "fast": _build_rule(
                        safety_multiplier="3.333333", floor_credits=1, cap_credits=200
                    ),
                    "default": _build_rule(
                        safety_multiplier="3.333333", floor_credits=1, cap_credits=200
                    ),
                },
                "generic.ai": {
                    "default": _build_rule(
                        safety_multiplier="3.333333", floor_credits=1, cap_credits=200
                    ),
                },
            },
            max_credits_per_call=200,
            synthesis_credit_cost=1,
            prompt_recommendation_credit_cost=2,
            infra_alloc_usd_by_feature={"default": _as_decimal("0")},
            orchestration_usd_by_feature={"default": _as_decimal("0")},
            retry_risk_rate=_as_decimal("0"),
        ),
        "v2": PricingPolicy(
            version="v2",
            credit_value_usd=_as_decimal("0.10"),
            target_margin=_as_decimal("0.72"),
            provider_multipliers=common_providers,
            tier_multipliers=common_tiers,
            feature_rules={
                "audit.main": {
                    "fast": _build_rule(safety_multiplier="1.10", floor_credits=1, cap_credits=220),
                    "deep": _build_rule(safety_multiplier="1.35", floor_credits=2, cap_credits=240),
                    "default": _build_rule(
                        safety_multiplier="1.10", floor_credits=1, cap_credits=220
                    ),
                },
                "content_brief.generate": {
                    "deep": _build_rule(safety_multiplier="3.9", floor_credits=2, cap_credits=220),
                    "default": _build_rule(
                        safety_multiplier="3.9", floor_credits=1, cap_credits=220
                    ),
                },
                "aeo_mentions.analyze_batch": {
                    "fast": _build_rule(safety_multiplier="3.7", floor_credits=1, cap_credits=210),
                    "default": _build_rule(
                        safety_multiplier="3.7", floor_credits=1, cap_credits=210
                    ),
                },
                "generic.ai": {
                    "default": _build_rule(
                        safety_multiplier="3.8", floor_credits=1, cap_credits=220
                    ),
                },
            },
            max_credits_per_call=240,
            synthesis_credit_cost=1,
            prompt_recommendation_credit_cost=2,
            infra_alloc_usd_by_feature={
                "default": _as_decimal("0.0015"),
                "audit.main": _as_decimal("0.0025"),
                "content_brief.generate": _as_decimal("0.0010"),
                "aeo_mentions.analyze_batch": _as_decimal("0.0008"),
            },
            orchestration_usd_by_feature={
                "default": _as_decimal("0.0005"),
                "audit.main": _as_decimal("0.0015"),
                "content_brief.generate": _as_decimal("0.0020"),
            },
            retry_risk_rate=_as_decimal("0.06"),
        ),
        "v3": PricingPolicy(
            version="v3",
            credit_value_usd=_as_decimal("0.10"),
            target_margin=_as_decimal("0.675"),
            provider_multipliers=common_providers,
            tier_multipliers=common_tiers,
            feature_rules={
                "audit.main": {
                    "fast": _build_rule(safety_multiplier="2.50", floor_credits=2, cap_credits=250),
                    "deep": _build_rule(safety_multiplier="3.10", floor_credits=4, cap_credits=280),
                    "default": _build_rule(
                        safety_multiplier="2.50", floor_credits=2, cap_credits=250
                    ),
                },
                "content_brief.generate": {
                    "deep": _build_rule(safety_multiplier="4.00", floor_credits=3, cap_credits=250),
                    "default": _build_rule(
                        safety_multiplier="4.00", floor_credits=2, cap_credits=250
                    ),
                },
                "aeo_mentions.analyze_batch": {
                    "fast": _build_rule(safety_multiplier="3.80", floor_credits=2, cap_credits=230),
                    "default": _build_rule(
                        safety_multiplier="3.80", floor_credits=2, cap_credits=230
                    ),
                },
                "brand_audit.full_pipeline": {
                    "deep": _build_rule(safety_multiplier="3.20", floor_credits=5, cap_credits=300),
                    "default": _build_rule(
                        safety_multiplier="3.20", floor_credits=3, cap_credits=300
                    ),
                },
                "generic.ai": {
                    "default": _build_rule(
                        safety_multiplier="3.80", floor_credits=1, cap_credits=250
                    ),
                },
            },
            max_credits_per_call=300,
            synthesis_credit_cost=2,
            prompt_recommendation_credit_cost=3,
            infra_alloc_usd_by_feature={
                "default": _as_decimal("0.0020"),
                "audit.main": _as_decimal("0.0035"),
                "brand_audit.full_pipeline": _as_decimal("0.0050"),
                "content_brief.generate": _as_decimal("0.0015"),
                "aeo_mentions.analyze_batch": _as_decimal("0.0010"),
            },
            orchestration_usd_by_feature={
                "default": _as_decimal("0.0008"),
                "audit.main": _as_decimal("0.0020"),
                "brand_audit.full_pipeline": _as_decimal("0.0035"),
                "content_brief.generate": _as_decimal("0.0025"),
            },
            retry_risk_rate=_as_decimal("0.08"),
        ),
    }
    return policies


def _validate_policy(policy: PricingPolicy) -> None:
    if policy.credit_value_usd <= 0:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: credit_value_usd must be > 0."
        )
    if policy.max_credits_per_call <= 0:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: max_credits_per_call must be > 0."
        )
    if policy.synthesis_credit_cost <= 0:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: synthesis_credit_cost must be > 0."
        )
    if policy.prompt_recommendation_credit_cost <= 0:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: prompt_recommendation_credit_cost must be > 0."
        )
    if not policy.provider_multipliers:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: provider multipliers missing."
        )
    if not policy.tier_multipliers:
        raise RuntimeError(f"Invalid pricing policy {policy.version}: tier multipliers missing.")
    if "generic.ai" not in policy.feature_rules:
        raise RuntimeError(
            f"Invalid pricing policy {policy.version}: generic.ai fallback rule missing."
        )
    for feature_key, feature_mapping in policy.feature_rules.items():
        if not feature_mapping:
            raise RuntimeError(
                f"Invalid pricing policy {policy.version}: feature rule map empty for {feature_key}."
            )
        for tier_key, tier_rule in feature_mapping.items():
            if tier_rule.safety_multiplier <= 0:
                raise RuntimeError(
                    f"Invalid pricing policy {policy.version}: safety multiplier must be > 0 for "
                    f"{feature_key}/{tier_key}."
                )
            if tier_rule.floor_credits < 0:
                raise RuntimeError(
                    f"Invalid pricing policy {policy.version}: floor cannot be negative for "
                    f"{feature_key}/{tier_key}."
                )
            if tier_rule.cap_credits < tier_rule.floor_credits:
                raise RuntimeError(
                    f"Invalid pricing policy {policy.version}: cap cannot be below floor for "
                    f"{feature_key}/{tier_key}."
                )


_PRICING_POLICIES = _build_policies()
if DEFAULT_POLICY_VERSION not in _PRICING_POLICIES:
    raise RuntimeError(f"Default pricing policy '{DEFAULT_POLICY_VERSION}' was not defined.")
for _policy in _PRICING_POLICIES.values():
    _validate_policy(_policy)


def get_pricing_policy(policy_version: str | None = None) -> PricingPolicy:
    normalized = str(policy_version or "").strip().lower()
    if not normalized:
        normalized = DEFAULT_POLICY_VERSION
    return _PRICING_POLICIES.get(normalized, _PRICING_POLICIES[DEFAULT_POLICY_VERSION])


def calculate_credits_from_real_cost(
    *,
    real_cost_usd: Decimal,
    policy_version: str | None,
    feature_key: str,
    tier_class: str,
    billable: bool,
) -> tuple[int, FeatureTierRule]:
    policy = get_pricing_policy(policy_version)
    rule = policy.resolve_feature_rule(feature_key, tier_class)
    if real_cost_usd <= 0:
        if not billable:
            return 0, rule
        floor = max(1, rule.floor_credits)
        cap = min(policy.max_credits_per_call, rule.cap_credits or policy.max_credits_per_call)
        return min(floor, cap), rule

    # Credits must recover the real COGS *plus* the target profit margin, so a
    # credit sold at ``credit_value_usd`` yields exactly ``target_margin``.
    #   credit_cost_basis = credit_value_usd * (1 - target_margin)
    #   credits           = real_cost / credit_cost_basis * safety_multiplier
    margin_fraction = (
        policy.target_margin
        if Decimal("0") <= policy.target_margin < Decimal("1")
        else Decimal("0")
    )
    credit_cost_basis = policy.credit_value_usd * (Decimal("1") - margin_fraction)
    if credit_cost_basis <= 0:
        credit_cost_basis = policy.credit_value_usd
    computed = ((real_cost_usd / credit_cost_basis) * rule.safety_multiplier).to_integral_value(
        rounding=ROUND_CEILING
    )
    credits = max(0, int(computed))

    if billable:
        credits = max(1, credits)
        credits = max(rule.floor_credits, credits)

    cap = min(policy.max_credits_per_call, rule.cap_credits or policy.max_credits_per_call)
    if cap > 0:
        credits = min(credits, cap)

    return credits, rule


def calculate_audit_credit_cost_for_policy(
    *,
    policy_version: str | None,
    provider: str,
    tier: str,
    entities_count: int = 0,
    category: str | None = None,
    market: str | None = None,
) -> int:
    policy = get_pricing_policy(policy_version)
    provider_multiplier = policy.resolve_provider_multiplier(provider)
    tier_multiplier = policy.resolve_tier_multiplier(tier)

    normalized_entities_count = max(0, int(entities_count))
    input_weight = _as_decimal("1.0") + (
        Decimal(min(normalized_entities_count, 8)) * _as_decimal("0.5")
    )
    if (category or "").strip():
        input_weight += _as_decimal("0.25")
    if (market or "").strip():
        input_weight += _as_decimal("0.25")

    raw_credits = (input_weight * tier_multiplier * provider_multiplier).to_integral_value(
        rounding=ROUND_CEILING
    )
    tier_class = normalize_feature_tier_class(tier)
    rule = policy.resolve_feature_rule("audit.main", tier_class)
    credits = max(1, int(raw_credits))
    credits = max(rule.floor_credits, credits)
    cap = min(policy.max_credits_per_call, rule.cap_credits or policy.max_credits_per_call)
    if cap > 0:
        credits = min(cap, credits)
    return max(1, credits)
