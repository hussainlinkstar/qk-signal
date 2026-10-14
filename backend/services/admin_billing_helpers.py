"""Shared billing helper functions for admin endpoints.

Extracted from admin.py to reduce duplication and keep billing logic
in one importable module.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from app.config.plans import get_plan_monthly_price_usd
from billing import (
    BILLING_MODES,
    CommitmentTier,
    Plan,
    is_billing_runtime_payload_meaningful,
    normalize_billing_runtime_payload,
)


# ---------------------------------------------------------------------------
#  Stripe primitives
# ---------------------------------------------------------------------------


def stripe_object_to_dict(payload: object) -> dict[str, object]:
    """Convert a Stripe API object to a plain dict."""
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "to_dict_recursive"):
        try:
            value = payload.to_dict_recursive()
            if isinstance(value, dict):
                return value
        except Exception:
            return {}
    try:
        return dict(payload)  # type: ignore[arg-type]
    except Exception:
        return {}


def parse_stripe_timestamp(value: object) -> datetime | None:
    """Parse a Unix epoch seconds value into a UTC datetime."""
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


# ---------------------------------------------------------------------------
#  MRR calculation (used by /admin/metrics and /admin/billing/overview)
# ---------------------------------------------------------------------------


def calculate_subscription_mrr(db: Session) -> tuple[float, int, int]:
    """Return (mrr_usd, total_subscriptions, active_count).

    Queries Subscription rows once and computes the monthly recurring
    revenue from active subscriptions so callers don't duplicate this.
    """
    total_subscriptions = db.query(func.count(models.Subscription.id)).scalar() or 0
    active_subscriptions = (
        db.query(models.Subscription)
        .filter(models.Subscription.status.in_(["active", "trialing"]))
        .all()
    )
    mrr = sum(get_plan_monthly_price_usd(sub.plan_type) for sub in active_subscriptions)
    return float(mrr), int(total_subscriptions), len(active_subscriptions)


# ---------------------------------------------------------------------------
#  Workspace plan resolution  (3 call-sites collapsed into 1 helper)
# ---------------------------------------------------------------------------

_DEFAULT_PLAN = "plan_standard"


def resolve_workspace_plan(workspace: models.Workspace) -> str:
    """Resolve the plan name from the workspace owner's subscription."""
    owner = workspace.owner
    if not owner:
        return _DEFAULT_PLAN
    sub = getattr(owner, "subscription", None)
    return getattr(sub, "plan_type", None) or _DEFAULT_PLAN


def resolve_workspace_billing(workspace: models.Workspace) -> dict[str, Any]:
    """Resolve billing info from the workspace owner's subscription."""
    empty = {
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "plan_name": _DEFAULT_PLAN,
        "subscription_status": None,
    }
    owner = workspace.owner
    if not owner:
        return empty
    sub = getattr(owner, "subscription", None)
    if not sub:
        return empty
    return {
        "stripe_customer_id": sub.stripe_customer_id,
        "stripe_subscription_id": sub.stripe_subscription_id,
        "plan_name": getattr(sub, "plan_type", _DEFAULT_PLAN) or _DEFAULT_PLAN,
        "subscription_status": getattr(sub, "status", None),
    }


# ---------------------------------------------------------------------------
#  Commitment serialisation
# ---------------------------------------------------------------------------


def serialize_admin_commitment(
    commitment: models.CreditCommitment,
    user: models.User,
) -> dict[str, object]:
    active_cycle = next(
        (cycle for cycle in commitment.usage_cycles if cycle.status == "active"),
        None,
    )
    credits_used = int(active_cycle.credits_used or 0) if active_cycle else 0
    committed_credits = int(commitment.committed_credits or 0)
    overage_credits = int(active_cycle.overage_credits or 0) if active_cycle else 0
    usage_pct = round((credits_used / committed_credits) * 100, 2) if committed_credits > 0 else 0.0
    return {
        "id": commitment.id,
        "user_id": user.id,
        "user_email": user.email,
        "tier": commitment.tier,
        "committed_credits": committed_credits,
        "monthly_fee_usd": float(
            commitment.monthly_fee_usd or 0
        ),  # DB column is legacy-named _usd, stores EUR
        "rate_per_credit": float(commitment.rate_per_credit or 0),
        "status": commitment.status,
        "cancel_at_period_end": bool(commitment.cancel_at_period_end),
        "current_cycle_end": commitment.current_cycle_end,
        "credits_used": credits_used,
        "overage_credits": overage_credits,
        "usage_pct": usage_pct,
        "pending_tier": commitment.pending_tier,
    }


# ---------------------------------------------------------------------------
#  Billing config payload builder
# ---------------------------------------------------------------------------


def mask_secret_tail(value: str | None) -> str | None:
    """Return last 4 chars of a secret string for display, or None."""
    if not value:
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    if len(trimmed) <= 4:
        return trimmed
    return trimmed[-4:]


def build_admin_billing_config_payload(config: Any) -> dict[str, object]:
    """Build the admin billing config response dict from a billing config object."""
    modes: list[dict[str, object]] = []
    for mode in BILLING_MODES:
        mode_config = config.mode_configs.get(mode)
        modes.append(
            {
                "mode": mode,
                "secret_configured": bool(mode_config and mode_config.secret_key),
                "webhook_configured": bool(mode_config and mode_config.webhook_secret),
                "secret_hint": mask_secret_tail(mode_config.secret_key if mode_config else None),
                "webhook_hint": mask_secret_tail(
                    mode_config.webhook_secret if mode_config else None
                ),
            }
        )

    return {
        "billing_enabled": config.billing_enabled,
        "webhook_configured": bool(config.stripe_webhook_secret),
        "stripe_mode": config.stripe_mode,
        "stripe_mode_source": config.stripe_mode_source,
        "has_runtime_override": config.has_runtime_override,
        "modes": modes,
        "price_ids": [
            {
                "plan": plan.value,
                "configured": bool(config.price_id_for(plan)),
                "active_price_id": config.price_id_for(plan) or None,
                "test_price_id": config.price_id_for_mode("test", plan) or None,
                "live_price_id": config.price_id_for_mode("live", plan) or None,
            }
            for plan in Plan
        ],
        "commitment_price_ids": [
            {
                "tier": tier.value,
                "configured": bool(config.commitment_price_id_for(tier)),
                "active_price_id": config.commitment_price_id_for(tier) or None,
                "test_price_id": config.commitment_price_id_for_mode("test", tier) or None,
                "live_price_id": config.commitment_price_id_for_mode("live", tier) or None,
            }
            for tier in CommitmentTier
        ],
        "commitment_overage_price_ids": {
            "configured": bool(config.commitment_overage_price_id),
            "active_price_id": config.commitment_overage_price_id or None,
            "test_price_id": config.commitment_overage_price_id_for_mode("test") or None,
            "live_price_id": config.commitment_overage_price_id_for_mode("live") or None,
        },
    }


# ---------------------------------------------------------------------------
#  Catalog sync result serialisation
# ---------------------------------------------------------------------------


def serialize_catalog_sync_result(result: Any) -> dict[str, object]:
    payload = asdict(result)
    payload.pop("mode", None)
    payload.pop("dry_run", None)
    return payload


# ---------------------------------------------------------------------------
#  Billing runtime resolution helpers
# ---------------------------------------------------------------------------


def build_empty_billing_runtime_mode_payload() -> dict[str, object]:
    return {
        "secret_key": None,
        "webhook_secret": None,
        "price_ids": {plan.value: None for plan in Plan},
        "annual_price_ids": {plan.value: None for plan in Plan},
        "commitment_price_ids": {tier.value: None for tier in CommitmentTier},
        "commitment_overage_price_id": None,
    }


def ensure_billing_runtime_modes(runtime: dict[str, object]) -> dict[str, dict[str, object]]:
    """Ensure ``runtime["modes"]`` is a well-shaped dict for test+live."""
    runtime_modes = runtime.get("modes")
    if not isinstance(runtime_modes, dict):
        runtime_modes = {}
        runtime["modes"] = runtime_modes

    for mode in BILLING_MODES:
        mode_payload = runtime_modes.get(mode)
        if not isinstance(mode_payload, dict):
            mode_payload = build_empty_billing_runtime_mode_payload()
            runtime_modes[mode] = mode_payload
        if not isinstance(mode_payload.get("price_ids"), dict):
            mode_payload["price_ids"] = {plan.value: None for plan in Plan}
        if not isinstance(mode_payload.get("annual_price_ids"), dict):
            mode_payload["annual_price_ids"] = {plan.value: None for plan in Plan}
        if not isinstance(mode_payload.get("commitment_price_ids"), dict):
            mode_payload["commitment_price_ids"] = {tier.value: None for tier in CommitmentTier}
        if "commitment_overage_price_id" not in mode_payload:
            mode_payload["commitment_overage_price_id"] = None

    return runtime_modes


def runtime_payload_has_key(raw_runtime: object, key: str) -> bool:
    return isinstance(raw_runtime, dict) and key in raw_runtime


def persist_billing_runtime_settings(
    *,
    settings: models.OperationalSetting,
    normalized_admin_payload: dict[str, object],
    raw_runtime: object,
    runtime: dict[str, object],
    admin_user_id: int,
    preserve_stripe_mode: bool,
    preserve_billing_enabled: bool,
    normalize_admin_settings_fn: Any,
) -> None:
    """Write billing runtime back to OperationalSetting.

    ``normalize_admin_settings_fn`` is the admin-level normalizer, passed
    in to avoid a circular import (it lives in admin.py).
    """
    normalized_runtime = normalize_billing_runtime_payload(runtime)
    if not preserve_stripe_mode:
        normalized_runtime.pop("stripe_mode", None)
    if not preserve_billing_enabled:
        normalized_runtime.pop("billing_enabled", None)
    normalized_runtime["updated_at"] = datetime.now(timezone.utc).isoformat()
    normalized_runtime["updated_by_user_id"] = admin_user_id

    if is_billing_runtime_payload_meaningful(normalized_runtime):
        normalized_admin_payload["billing_runtime"] = normalized_runtime
    else:
        normalized_admin_payload.pop("billing_runtime", None)

    settings.admin_settings_payload = normalize_admin_settings_fn(normalized_admin_payload)


def apply_catalog_sync_to_runtime(
    runtime_modes: dict[str, dict[str, object]],
    *,
    mode: str,
    scope: Literal["plans", "commitments", "all"],
    plan_price_ids: dict[str, str],
    commitment_price_ids: dict[str, str],
    commitment_overage_price_id: str | None,
    annual_plan_price_ids: dict[str, str] | None = None,
) -> None:
    mode_payload = runtime_modes[mode]
    mode_price_ids = mode_payload.get("price_ids")
    if not isinstance(mode_price_ids, dict):
        mode_price_ids = {plan.value: None for plan in Plan}
        mode_payload["price_ids"] = mode_price_ids
    mode_annual_price_ids = mode_payload.get("annual_price_ids")
    if not isinstance(mode_annual_price_ids, dict):
        mode_annual_price_ids = {plan.value: None for plan in Plan}
        mode_payload["annual_price_ids"] = mode_annual_price_ids
    mode_commitment_price_ids = mode_payload.get("commitment_price_ids")
    if not isinstance(mode_commitment_price_ids, dict):
        mode_commitment_price_ids = {tier.value: None for tier in CommitmentTier}
        mode_payload["commitment_price_ids"] = mode_commitment_price_ids

    if scope in {"plans", "all"}:
        for plan_key, price_id in plan_price_ids.items():
            if plan_key in mode_price_ids:
                mode_price_ids[plan_key] = price_id
        for plan_key, price_id in (annual_plan_price_ids or {}).items():
            if plan_key in mode_annual_price_ids:
                mode_annual_price_ids[plan_key] = price_id

    if scope in {"commitments", "all"}:
        for tier_key, price_id in commitment_price_ids.items():
            if tier_key in mode_commitment_price_ids:
                mode_commitment_price_ids[tier_key] = price_id
        if commitment_overage_price_id:
            mode_payload["commitment_overage_price_id"] = commitment_overage_price_id


# ---------------------------------------------------------------------------
#  Billing plan / tier key resolution
# ---------------------------------------------------------------------------


def resolve_billing_plan_key(plan_key: str, resolve_fn: Any) -> str | None:
    """Normalise a plan key string, returning None for unrecognised values.

    ``resolve_fn`` is ``_resolve_admin_plan_type`` from admin.py (passed in
    to avoid circular imports).
    """
    normalized = (plan_key or "").strip().lower()
    if not normalized:
        return None
    try:
        return resolve_fn(normalized)
    except Exception:
        return None


def resolve_billing_commitment_tier_key(tier_key: str) -> str | None:
    normalized = (tier_key or "").strip().lower()
    if not normalized:
        return None
    try:
        return CommitmentTier(normalized).value
    except ValueError:
        return None
