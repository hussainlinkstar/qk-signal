from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any, Mapping

from core.config import settings


BILLING_MODES = ("test", "live")
ANNUAL_DISCOUNT_PCT = 20  # 20% off vs monthly when billed annually

# The one currency this product bills in, for every plan, commitment tier,
# overage unit and top-up, in both test and live mode. It is deliberately a
# constant and not a setting: the currency of a Stripe Price is immutable once
# created, a Customer cannot hold subscriptions in two currencies, and the
# credit_top_up_orders table carries a CHECK constraint pinning 'usd'. Making
# this per-environment would let test and live disagree about what a number
# means, which is how the plan price ended up documented as EUR while Stripe
# charged USD (SIGV2-1133).
#
# Field and column names ending in _usd (monthly_price_usd, monthly_fee_usd,
# pending_monthly_fee_usd, proration_amount_usd) are therefore accurate, not
# legacy misnomers. Amounts in those fields are major units of this currency.
# Any surface that renders one of them must render it as this currency.
BILLING_CURRENCY = "usd"
BILLING_CURRENCY_DISPLAY = "USD"


class Plan(str, Enum):
    STARTER = "plan_starter"
    AGENCY_TRIAL = "plan_agency_trial"
    STANDARD = "plan_standard"
    SPECIALIST = "plan_specialist"
    EXECUTIVE = "plan_executive"


class CommitmentTier(str, Enum):
    GROWTH = "growth"
    SCALE = "scale"
    ENTERPRISE = "enterprise"


PLAN_ALIASES: dict[str, str] = {
    Plan.STARTER.value: Plan.STARTER.value,
    Plan.AGENCY_TRIAL.value: Plan.AGENCY_TRIAL.value,
    "trial": Plan.AGENCY_TRIAL.value,
    Plan.STANDARD.value: Plan.STANDARD.value,
    Plan.SPECIALIST.value: Plan.SPECIALIST.value,
    Plan.EXECUTIVE.value: Plan.EXECUTIVE.value,
}
COMMITMENT_TIER_ALIASES: dict[str, str] = {
    CommitmentTier.GROWTH.value: CommitmentTier.GROWTH.value,
    CommitmentTier.SCALE.value: CommitmentTier.SCALE.value,
    CommitmentTier.ENTERPRISE.value: CommitmentTier.ENTERPRISE.value,
}


MODE_SECRET_ENV_KEYS: dict[str, str] = {
    "test": "STRIPE_SECRET_KEY_TEST",
    "live": "STRIPE_SECRET_KEY_LIVE",
}
MODE_WEBHOOK_ENV_KEYS: dict[str, str] = {
    "test": "STRIPE_WEBHOOK_SECRET_TEST",
    "live": "STRIPE_WEBHOOK_SECRET_LIVE",
}
PRICE_ENV_KEYS: dict[Plan, str] = {
    Plan.STARTER: "STRIPE_PRICE_STARTER",
    Plan.STANDARD: "STRIPE_PRICE_STANDARD",
    Plan.SPECIALIST: "STRIPE_PRICE_SPECIALIST",
    Plan.EXECUTIVE: "STRIPE_PRICE_EXECUTIVE",
}
MODE_PRICE_ENV_KEYS: dict[str, dict[Plan, str]] = {
    "test": {
        Plan.STARTER: "STRIPE_PRICE_STARTER_TEST",
        Plan.STANDARD: "STRIPE_PRICE_STANDARD_TEST",
        Plan.SPECIALIST: "STRIPE_PRICE_SPECIALIST_TEST",
        Plan.EXECUTIVE: "STRIPE_PRICE_EXECUTIVE_TEST",
    },
    "live": {
        Plan.STARTER: "STRIPE_PRICE_STARTER_LIVE",
        Plan.STANDARD: "STRIPE_PRICE_STANDARD_LIVE",
        Plan.SPECIALIST: "STRIPE_PRICE_SPECIALIST_LIVE",
        Plan.EXECUTIVE: "STRIPE_PRICE_EXECUTIVE_LIVE",
    },
}
MODE_ANNUAL_PRICE_ENV_KEYS: dict[str, dict[Plan, str]] = {
    "test": {
        Plan.STANDARD: "STRIPE_PRICE_STANDARD_ANNUAL_TEST",
        Plan.SPECIALIST: "STRIPE_PRICE_SPECIALIST_ANNUAL_TEST",
        Plan.EXECUTIVE: "STRIPE_PRICE_EXECUTIVE_ANNUAL_TEST",
    },
    "live": {
        Plan.STANDARD: "STRIPE_PRICE_STANDARD_ANNUAL_LIVE",
        Plan.SPECIALIST: "STRIPE_PRICE_SPECIALIST_ANNUAL_LIVE",
        Plan.EXECUTIVE: "STRIPE_PRICE_EXECUTIVE_ANNUAL_LIVE",
    },
}
MODE_COMMITMENT_PRICE_ENV_KEYS: dict[str, dict[CommitmentTier, str]] = {
    "test": {
        CommitmentTier.GROWTH: "STRIPE_PRICE_COMMITMENT_GROWTH_TEST",
        CommitmentTier.SCALE: "STRIPE_PRICE_COMMITMENT_SCALE_TEST",
        CommitmentTier.ENTERPRISE: "STRIPE_PRICE_COMMITMENT_ENTERPRISE_TEST",
    },
    "live": {
        CommitmentTier.GROWTH: "STRIPE_PRICE_COMMITMENT_GROWTH_LIVE",
        CommitmentTier.SCALE: "STRIPE_PRICE_COMMITMENT_SCALE_LIVE",
        CommitmentTier.ENTERPRISE: "STRIPE_PRICE_COMMITMENT_ENTERPRISE_LIVE",
    },
}
MODE_COMMITMENT_OVERAGE_ENV_KEYS: dict[str, str] = {
    "test": "STRIPE_PRICE_COMMITMENT_OVERAGE_TEST",
    "live": "STRIPE_PRICE_COMMITMENT_OVERAGE_LIVE",
}


@dataclass(frozen=True)
class BillingModeConfig:
    secret_key: str | None
    webhook_secret: str | None
    price_ids: Mapping[Plan, str]
    annual_price_ids: Mapping[Plan, str]
    commitment_price_ids: Mapping[CommitmentTier, str]
    commitment_overage_price_id: str | None


@dataclass(frozen=True)
class BillingConfig:
    stripe_secret_key: str | None
    stripe_webhook_secret: str | None
    app_base_url: str
    price_ids: Mapping[Plan, str]
    annual_price_ids: Mapping[Plan, str]
    commitment_price_ids: Mapping[CommitmentTier, str]
    commitment_overage_price_id: str | None
    grace_period_days: int
    feature_flags: Mapping[str, bool]
    stripe_mode: str = "test"
    stripe_mode_source: str = "env"
    has_runtime_override: bool = False
    mode_configs: Mapping[str, BillingModeConfig] = field(default_factory=dict)

    def price_id_for(self, plan: Plan, interval: str = "month") -> str:
        if interval == "year":
            return self.annual_price_ids.get(plan, "")
        return self.price_ids.get(plan, "")

    def price_id_for_mode(self, mode: str, plan: Plan, interval: str = "month") -> str:
        mode_key = _normalize_mode(mode, default="test")
        mode_config = self.mode_configs.get(mode_key)
        if not mode_config:
            return ""
        if interval == "year":
            return mode_config.annual_price_ids.get(plan, "")
        return mode_config.price_ids.get(plan, "")

    def commitment_price_id_for(self, tier: CommitmentTier | str) -> str:
        resolved_tier = _resolve_commitment_tier_enum(tier)
        if resolved_tier is None:
            return ""
        return self.commitment_price_ids.get(resolved_tier, "")

    def commitment_price_id_for_mode(self, mode: str, tier: CommitmentTier | str) -> str:
        resolved_tier = _resolve_commitment_tier_enum(tier)
        if resolved_tier is None:
            return ""
        mode_key = _normalize_mode(mode, default="test")
        mode_config = self.mode_configs.get(mode_key)
        if not mode_config:
            return ""
        return mode_config.commitment_price_ids.get(resolved_tier, "")

    def commitment_overage_price_id_for_mode(self, mode: str) -> str:
        mode_key = _normalize_mode(mode, default="test")
        mode_config = self.mode_configs.get(mode_key)
        if not mode_config or not mode_config.commitment_overage_price_id:
            return ""
        return mode_config.commitment_overage_price_id

    def plan_for_price_id(self, price_id: str | None) -> Plan | None:
        if not price_id:
            return None
        for mode_config in self.mode_configs.values():
            for plan, configured_price_id in mode_config.price_ids.items():
                if configured_price_id and configured_price_id == price_id:
                    return plan
            for plan, configured_price_id in mode_config.annual_price_ids.items():
                if configured_price_id and configured_price_id == price_id:
                    return plan
        return None

    def resolve_plan_price(
        self,
        stripe_mode: str,
        price_id: str | None,
        interval: str,
    ) -> Plan | None:
        if not price_id or stripe_mode not in BILLING_MODES or interval not in {"month", "year"}:
            return None
        mode_config = self.mode_configs.get(stripe_mode)
        if mode_config is None:
            return None
        selected = mode_config.annual_price_ids if interval == "year" else mode_config.price_ids
        opposite = mode_config.price_ids if interval == "year" else mode_config.annual_price_ids
        matches = [plan for plan, configured in selected.items() if configured == price_id]
        if len(matches) != 1 or any(configured == price_id for configured in opposite.values()):
            return None
        return matches[0]

    def commitment_tier_for_price_id(self, price_id: str | None) -> CommitmentTier | None:
        if not price_id:
            return None
        for mode_config in self.mode_configs.values():
            for tier, configured_price_id in mode_config.commitment_price_ids.items():
                if configured_price_id and configured_price_id == price_id:
                    return tier
        return None

    def is_commitment_overage_price_id(self, price_id: str | None) -> bool:
        if not price_id:
            return False
        return any(
            mode_config.commitment_overage_price_id == price_id
            for mode_config in self.mode_configs.values()
            if mode_config.commitment_overage_price_id
        )

    @property
    def billing_enabled(self) -> bool:
        return self.feature_flags.get("billing_enabled", False)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_nullable_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return None


def _parse_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _normalize_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _read_env_value(*env_keys: str) -> str | None:
    for env_key in env_keys:
        if not env_key:
            continue
        normalized = _normalize_text(os.getenv(env_key))
        if normalized:
            return normalized
    return None


def _normalize_mode(value: object, *, default: str) -> str:
    normalized = _normalize_text(value)
    if not normalized:
        return default
    lowered = normalized.lower()
    if lowered in BILLING_MODES:
        return lowered
    return default


def _resolve_plan_key(value: object) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return PLAN_ALIASES.get(normalized.lower())


def _resolve_commitment_tier_key(value: object) -> str | None:
    normalized = _normalize_text(value)
    if not normalized:
        return None
    return COMMITMENT_TIER_ALIASES.get(normalized.lower())


def _resolve_commitment_tier_enum(value: CommitmentTier | str | object) -> CommitmentTier | None:
    if isinstance(value, CommitmentTier):
        return value
    resolved = _resolve_commitment_tier_key(value)
    return CommitmentTier(resolved) if resolved else None


def _build_empty_mode_payload() -> dict[str, object]:
    return {
        "secret_key": None,
        "webhook_secret": None,
        "price_ids": {plan.value: None for plan in Plan},
        "annual_price_ids": {plan.value: None for plan in Plan},
        "commitment_price_ids": {tier.value: None for tier in CommitmentTier},
        "commitment_overage_price_id": None,
    }


def _normalize_runtime_price_map(raw_prices: object) -> dict[str, str | None]:
    normalized = {plan.value: None for plan in Plan}
    if not isinstance(raw_prices, Mapping):
        return normalized

    for key, value in raw_prices.items():
        resolved_plan = _resolve_plan_key(key)
        if not resolved_plan:
            continue
        normalized[resolved_plan] = _normalize_text(value)
    return normalized


def _normalize_runtime_commitment_price_map(raw_prices: object) -> dict[str, str | None]:
    normalized = {tier.value: None for tier in CommitmentTier}
    if not isinstance(raw_prices, Mapping):
        return normalized

    for key, value in raw_prices.items():
        resolved_tier = _resolve_commitment_tier_key(key)
        if not resolved_tier:
            continue
        normalized[resolved_tier] = _normalize_text(value)
    return normalized


def normalize_billing_runtime_payload(payload: object) -> dict[str, object]:
    source = payload if isinstance(payload, Mapping) else {}
    modes_source = source.get("modes")
    modes_mapping = modes_source if isinstance(modes_source, Mapping) else {}

    stripe_mode = _normalize_mode(source.get("stripe_mode"), default="test")
    billing_enabled = _parse_nullable_bool(source.get("billing_enabled"))
    updated_at = _normalize_text(source.get("updated_at"))

    updated_by_user_id: int | None = None
    raw_updated_by_user_id = source.get("updated_by_user_id")
    if isinstance(raw_updated_by_user_id, int):
        updated_by_user_id = raw_updated_by_user_id
    elif isinstance(raw_updated_by_user_id, str):
        stripped = raw_updated_by_user_id.strip()
        if stripped and stripped.isdigit():
            updated_by_user_id = int(stripped)

    modes: dict[str, dict[str, object]] = {}
    for mode in BILLING_MODES:
        mode_payload = _build_empty_mode_payload()
        mode_source = modes_mapping.get(mode)
        mode_source_mapping = mode_source if isinstance(mode_source, Mapping) else {}

        secret_key = _normalize_text(mode_source_mapping.get("secret_key"))
        webhook_secret = _normalize_text(mode_source_mapping.get("webhook_secret"))
        price_ids = _normalize_runtime_price_map(mode_source_mapping.get("price_ids"))
        annual_price_ids = _normalize_runtime_price_map(mode_source_mapping.get("annual_price_ids"))
        commitment_price_ids = _normalize_runtime_commitment_price_map(
            mode_source_mapping.get("commitment_price_ids")
        )
        commitment_overage_price_id = _normalize_text(
            mode_source_mapping.get("commitment_overage_price_id")
        )

        fallback_secret = _normalize_text(source.get(f"{mode}_secret_key"))
        fallback_webhook = _normalize_text(source.get(f"{mode}_webhook_secret"))
        fallback_prices = _normalize_runtime_price_map(source.get(f"{mode}_price_ids"))
        fallback_annual_prices = _normalize_runtime_price_map(
            source.get(f"{mode}_annual_price_ids")
        )
        fallback_commitment_prices = _normalize_runtime_commitment_price_map(
            source.get(f"{mode}_commitment_price_ids")
        )
        fallback_commitment_overage_price_id = _normalize_text(
            source.get(f"{mode}_commitment_overage_price_id")
        )

        mode_payload["secret_key"] = secret_key or fallback_secret
        mode_payload["webhook_secret"] = webhook_secret or fallback_webhook
        mode_payload["price_ids"] = {
            plan.value: price_ids.get(plan.value) or fallback_prices.get(plan.value)
            for plan in Plan
        }
        mode_payload["annual_price_ids"] = {
            plan.value: annual_price_ids.get(plan.value) or fallback_annual_prices.get(plan.value)
            for plan in Plan
        }
        mode_payload["commitment_price_ids"] = {
            tier.value: commitment_price_ids.get(tier.value)
            or fallback_commitment_prices.get(tier.value)
            for tier in CommitmentTier
        }
        mode_payload["commitment_overage_price_id"] = (
            commitment_overage_price_id or fallback_commitment_overage_price_id
        )
        modes[mode] = mode_payload

    return {
        "stripe_mode": stripe_mode,
        "billing_enabled": billing_enabled,
        "updated_at": updated_at,
        "updated_by_user_id": updated_by_user_id,
        "modes": modes,
    }


def is_billing_runtime_payload_meaningful(payload: object) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if "stripe_mode" in payload or "billing_enabled" in payload:
        return True

    modes_source = payload.get("modes")
    modes_mapping = modes_source if isinstance(modes_source, Mapping) else {}
    for mode in BILLING_MODES:
        mode_source = modes_mapping.get(mode)
        mode_source_mapping = mode_source if isinstance(mode_source, Mapping) else {}
        if _normalize_text(mode_source_mapping.get("secret_key")):
            return True
        if _normalize_text(mode_source_mapping.get("webhook_secret")):
            return True
        prices_source = mode_source_mapping.get("price_ids")
        if isinstance(prices_source, Mapping):
            for value in prices_source.values():
                if _normalize_text(value):
                    return True
        annual_prices_source = mode_source_mapping.get("annual_price_ids")
        if isinstance(annual_prices_source, Mapping):
            for value in annual_prices_source.values():
                if _normalize_text(value):
                    return True
        commitment_prices_source = mode_source_mapping.get("commitment_price_ids")
        if isinstance(commitment_prices_source, Mapping):
            for value in commitment_prices_source.values():
                if _normalize_text(value):
                    return True
        if _normalize_text(mode_source_mapping.get("commitment_overage_price_id")):
            return True

        if _normalize_text(payload.get(f"{mode}_secret_key")):
            return True
        if _normalize_text(payload.get(f"{mode}_webhook_secret")):
            return True
        fallback_prices = payload.get(f"{mode}_price_ids")
        if isinstance(fallback_prices, Mapping):
            for value in fallback_prices.values():
                if _normalize_text(value):
                    return True
        fallback_commitment_prices = payload.get(f"{mode}_commitment_price_ids")
        if isinstance(fallback_commitment_prices, Mapping):
            for value in fallback_commitment_prices.values():
                if _normalize_text(value):
                    return True
        if _normalize_text(payload.get(f"{mode}_commitment_overage_price_id")):
            return True

    return False


def _load_runtime_overrides_from_db(db: object) -> object:
    try:
        from services.configuration_service import configuration_service

        payload = configuration_service.get_payload(db if hasattr(db, "query") else None)
        return payload.get("billing_runtime")
    except Exception:
        return None


def load_billing_config(
    db: object | None = None,
    runtime_overrides: Mapping[str, Any] | None = None,
) -> BillingConfig:
    env_mode = _normalize_mode(os.getenv("STRIPE_MODE"), default="test")

    base_price_ids = {
        plan: _read_env_value(PRICE_ENV_KEYS.get(plan, "")) or "" for plan in PRICE_ENV_KEYS
    }

    mode_secret_keys = {
        mode: _normalize_text(os.getenv(MODE_SECRET_ENV_KEYS[mode])) for mode in BILLING_MODES
    }
    mode_webhook_secrets = {
        mode: _normalize_text(os.getenv(MODE_WEBHOOK_ENV_KEYS[mode])) for mode in BILLING_MODES
    }
    mode_price_ids: dict[str, dict[Plan, str]] = {}
    for mode in BILLING_MODES:
        mode_price_ids[mode] = {}
        mode_price_env_keys = MODE_PRICE_ENV_KEYS.get(mode, {})
        for plan in Plan:
            env_key = mode_price_env_keys.get(plan)
            mode_price_ids[mode][plan] = _read_env_value(env_key or "") or ""
    mode_commitment_price_ids: dict[str, dict[CommitmentTier, str]] = {
        mode: {
            tier: _normalize_text(os.getenv(MODE_COMMITMENT_PRICE_ENV_KEYS[mode][tier])) or ""
            for tier in CommitmentTier
        }
        for mode in BILLING_MODES
    }
    mode_annual_price_ids: dict[str, dict[Plan, str]] = {}
    for mode in BILLING_MODES:
        mode_annual_price_ids[mode] = {}
        annual_env_keys = MODE_ANNUAL_PRICE_ENV_KEYS.get(mode, {})
        for plan in Plan:
            env_key = annual_env_keys.get(plan)
            mode_annual_price_ids[mode][plan] = _read_env_value(env_key or "") or ""
    mode_commitment_overage_price_ids = {
        mode: _normalize_text(os.getenv(MODE_COMMITMENT_OVERAGE_ENV_KEYS[mode])) or ""
        for mode in BILLING_MODES
    }

    for plan in Plan:
        base_price_id = base_price_ids.get(plan, "")
        if base_price_id and not mode_price_ids[env_mode].get(plan):
            mode_price_ids[env_mode][plan] = base_price_id

    raw_runtime_overrides = runtime_overrides
    if raw_runtime_overrides is None:
        raw_runtime_overrides = _load_runtime_overrides_from_db(db) if db is not None else None

    has_runtime_override = is_billing_runtime_payload_meaningful(raw_runtime_overrides)
    normalized_runtime = normalize_billing_runtime_payload(raw_runtime_overrides)
    runtime_modes = normalized_runtime["modes"] if isinstance(normalized_runtime, Mapping) else {}

    stripe_mode = env_mode
    stripe_mode_source = "env"
    if isinstance(raw_runtime_overrides, Mapping) and "stripe_mode" in raw_runtime_overrides:
        stripe_mode = _normalize_mode(
            normalized_runtime.get("stripe_mode"),
            default=env_mode,
        )
        stripe_mode_source = "runtime"

    for mode in BILLING_MODES:
        runtime_mode_payload = runtime_modes.get(mode, {})
        if not isinstance(runtime_mode_payload, Mapping):
            runtime_mode_payload = {}

        runtime_secret_key = _normalize_text(runtime_mode_payload.get("secret_key"))
        runtime_webhook_secret = _normalize_text(runtime_mode_payload.get("webhook_secret"))
        runtime_price_ids = runtime_mode_payload.get("price_ids")
        runtime_price_mapping = runtime_price_ids if isinstance(runtime_price_ids, Mapping) else {}
        runtime_commitment_price_ids = runtime_mode_payload.get("commitment_price_ids")
        runtime_commitment_price_mapping = (
            runtime_commitment_price_ids
            if isinstance(runtime_commitment_price_ids, Mapping)
            else {}
        )
        runtime_commitment_overage_price_id = _normalize_text(
            runtime_mode_payload.get("commitment_overage_price_id")
        )
        runtime_annual_price_ids = runtime_mode_payload.get("annual_price_ids")
        runtime_annual_price_mapping = (
            runtime_annual_price_ids if isinstance(runtime_annual_price_ids, Mapping) else {}
        )

        if runtime_secret_key:
            mode_secret_keys[mode] = runtime_secret_key
        if runtime_webhook_secret:
            mode_webhook_secrets[mode] = runtime_webhook_secret

        for plan in Plan:
            runtime_price_id = _normalize_text(runtime_price_mapping.get(plan.value))
            if runtime_price_id:
                mode_price_ids[mode][plan] = runtime_price_id
            runtime_annual_price_id = _normalize_text(runtime_annual_price_mapping.get(plan.value))
            if runtime_annual_price_id:
                mode_annual_price_ids[mode][plan] = runtime_annual_price_id
        for tier in CommitmentTier:
            runtime_commitment_price_id = _normalize_text(
                runtime_commitment_price_mapping.get(tier.value)
            )
            if runtime_commitment_price_id:
                mode_commitment_price_ids[mode][tier] = runtime_commitment_price_id
        if runtime_commitment_overage_price_id:
            mode_commitment_overage_price_ids[mode] = runtime_commitment_overage_price_id

    app_base_url = str(
        getattr(settings, "APP_BASE_URL", "http://localhost:3000") or "http://localhost:3000"
    )
    grace_period_days = _parse_int(
        str(getattr(settings, "BILLING_GRACE_PERIOD_DAYS", 7) or 7), default=7
    )

    active_secret_key = mode_secret_keys.get(stripe_mode)
    billing_enabled_default = bool(active_secret_key)
    env_billing_enabled = _parse_bool(
        str(getattr(settings, "FEATURE_BILLING_ENABLED", billing_enabled_default)),
        default=billing_enabled_default,
    )
    runtime_billing_enabled = _parse_nullable_bool(normalized_runtime.get("billing_enabled"))
    billing_enabled = (
        env_billing_enabled if runtime_billing_enabled is None else runtime_billing_enabled
    )

    feature_flags = {
        "billing_enabled": billing_enabled,
        "billing_grace_period": _parse_bool(
            str(getattr(settings, "FEATURE_BILLING_GRACE_PERIOD", True)),
            default=True,
        ),
    }

    mode_configs: dict[str, BillingModeConfig] = {}
    for mode in BILLING_MODES:
        mode_configs[mode] = BillingModeConfig(
            secret_key=mode_secret_keys.get(mode),
            webhook_secret=mode_webhook_secrets.get(mode),
            price_ids={plan: mode_price_ids[mode].get(plan, "") for plan in Plan},
            annual_price_ids={plan: mode_annual_price_ids[mode].get(plan, "") for plan in Plan},
            commitment_price_ids={
                tier: mode_commitment_price_ids[mode].get(tier, "") for tier in CommitmentTier
            },
            commitment_overage_price_id=mode_commitment_overage_price_ids.get(mode),
        )

    active_mode_config = mode_configs.get(stripe_mode, mode_configs["test"])
    return BillingConfig(
        stripe_secret_key=active_mode_config.secret_key,
        stripe_webhook_secret=active_mode_config.webhook_secret,
        app_base_url=app_base_url,
        price_ids=active_mode_config.price_ids,
        annual_price_ids=active_mode_config.annual_price_ids,
        commitment_price_ids=active_mode_config.commitment_price_ids,
        commitment_overage_price_id=active_mode_config.commitment_overage_price_id,
        grace_period_days=grace_period_days,
        feature_flags=feature_flags,
        stripe_mode=stripe_mode,
        stripe_mode_source=stripe_mode_source,
        has_runtime_override=has_runtime_override,
        mode_configs=mode_configs,
    )
