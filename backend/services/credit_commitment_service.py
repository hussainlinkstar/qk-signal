from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
import logging
from typing import Any, Mapping

from sqlalchemy.orm import Session

import models
from billing.config import BILLING_CURRENCY, BillingConfig, CommitmentTier, Plan
from billing.stripe_command_service import enqueue_usage_record_command


DEFAULT_OVERAGE_RATE = Decimal("0.1000")
WARNING_USAGE_RATIO = Decimal("0.80")
logger = logging.getLogger(__name__)
ELIGIBLE_PLAN_TYPES = {Plan.SPECIALIST.value, Plan.EXECUTIVE.value}


@dataclass(frozen=True)
class ValidatedCommitmentCheckout:
    tier: CommitmentTier
    fixed_item_id: str
    overage_item_id: str
    period_start: datetime
    period_end: datetime
    subscription_id: str


@dataclass(frozen=True)
class ValidatedCommitmentRenewal:
    period_start: datetime
    period_end: datetime
    fixed_price_id: str
    overage_price_id: str


@dataclass(frozen=True)
class CommitmentTierDefinition:
    tier: CommitmentTier
    label: str
    committed_credits: int
    rate_per_credit: Decimal
    discount_pct: int
    # Major units of BILLING_CURRENCY (USD). This value is what Stripe charges:
    # stripe_catalog_service turns it into minor units on a BILLING_CURRENCY
    # price, and validate_commitment_checkout_fulfillment refuses any checkout
    # whose amount_total or currency does not match it.
    monthly_fee_usd: Decimal
    overage_rate: Decimal = DEFAULT_OVERAGE_RATE


COMMITMENT_TIER_DEFINITIONS: dict[CommitmentTier, CommitmentTierDefinition] = {
    CommitmentTier.GROWTH: CommitmentTierDefinition(
        tier=CommitmentTier.GROWTH,
        label="Growth",
        committed_credits=2000,
        rate_per_credit=Decimal("0.09"),
        discount_pct=10,
        monthly_fee_usd=Decimal("180.00"),
    ),
    CommitmentTier.SCALE: CommitmentTierDefinition(
        tier=CommitmentTier.SCALE,
        label="Scale",
        committed_credits=5000,
        rate_per_credit=Decimal("0.08"),
        discount_pct=20,
        monthly_fee_usd=Decimal("400.00"),
    ),
    CommitmentTier.ENTERPRISE: CommitmentTierDefinition(
        tier=CommitmentTier.ENTERPRISE,
        label="Enterprise",
        committed_credits=8750,
        rate_per_credit=Decimal("0.07"),
        discount_pct=30,
        monthly_fee_usd=Decimal("612.50"),
    ),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        )
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return None


def _cycle_label(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


def resolve_commitment_tier_definition(
    tier: CommitmentTier | str | None,
) -> CommitmentTierDefinition | None:
    if isinstance(tier, CommitmentTier):
        return COMMITMENT_TIER_DEFINITIONS.get(tier)
    if isinstance(tier, str):
        normalized = tier.strip().lower()
        if not normalized:
            return None
        try:
            return COMMITMENT_TIER_DEFINITIONS[CommitmentTier(normalized)]
        except ValueError:
            return None
    return None


def serialize_tier_definition(definition: CommitmentTierDefinition) -> dict[str, object]:
    return {
        "tier": definition.tier.value,
        "label": definition.label,
        "committed_credits": definition.committed_credits,
        "rate_per_credit": definition.rate_per_credit,
        "discount_pct": definition.discount_pct,
        "monthly_fee_usd": definition.monthly_fee_usd,
        "overage_rate": definition.overage_rate,
    }


def list_commitment_tiers() -> list[dict[str, object]]:
    return [
        serialize_tier_definition(COMMITMENT_TIER_DEFINITIONS[tier])
        for tier in (
            CommitmentTier.GROWTH,
            CommitmentTier.SCALE,
            CommitmentTier.ENTERPRISE,
        )
    ]


def resolve_current_plan_type(user: models.User) -> str | None:
    sub = user.subscription
    if sub is None or not sub.plan_type:
        return None
    if sub.status not in ("active", "trialing"):
        return None
    return str(sub.plan_type).strip().lower() or None


def resolve_commitment_lock_reason(user: models.User) -> str | None:
    if user.subscription is None or user.subscription.status not in {"active", "trialing"}:
        return "An active Specialist or Executive subscription is required."
    current_plan = resolve_current_plan_type(user)
    if current_plan not in ELIGIBLE_PLAN_TYPES:
        return "Audit commitments are available on Specialist and Executive."
    return None


def is_commitment_eligible(user: models.User) -> bool:
    return resolve_commitment_lock_reason(user) is None


def get_user_commitment(
    db: Session,
    *,
    user_id: int,
    include_inactive: bool = False,
) -> models.CreditCommitment | None:
    query = db.query(models.CreditCommitment).filter(models.CreditCommitment.user_id == user_id)
    if not include_inactive:
        query = query.filter(
            models.CreditCommitment.status.in_(["active", "past_due"]),
        )
    return query.order_by(models.CreditCommitment.id.desc()).first()


def get_commitment_by_subscription_id(
    db: Session,
    *,
    stripe_subscription_id: str | None,
) -> models.CreditCommitment | None:
    if not stripe_subscription_id:
        return None
    return (
        db.query(models.CreditCommitment)
        .filter(models.CreditCommitment.stripe_subscription_id == stripe_subscription_id)
        .first()
    )


def get_active_commitment_cycle(
    db: Session,
    *,
    commitment_id: int,
    for_update: bool = False,
) -> models.CommitmentUsageCycle | None:
    query = db.query(models.CommitmentUsageCycle).filter(
        models.CommitmentUsageCycle.commitment_id == commitment_id,
        models.CommitmentUsageCycle.status == "active",
    )
    if for_update:
        query = query.with_for_update()
    return query.order_by(models.CommitmentUsageCycle.cycle_start.desc()).first()


def serialize_commitment_status(
    commitment: models.CreditCommitment | None,
    *,
    cycle: models.CommitmentUsageCycle | None = None,
) -> dict[str, object] | None:
    if commitment is None:
        return None
    active_cycle = cycle
    if active_cycle is None:
        active_cycle = next(
            (item for item in commitment.usage_cycles if item.status == "active"),
            None,
        )
    credits_used = int(active_cycle.credits_used or 0) if active_cycle else 0
    committed_credits = (
        int(active_cycle.committed_credits or 0)
        if active_cycle
        else int(commitment.committed_credits or 0)
    )
    overage_credits = int(active_cycle.overage_credits or 0) if active_cycle else 0
    credits_remaining = max(committed_credits - credits_used, 0)
    usage_pct = round((credits_used / committed_credits) * 100, 2) if committed_credits > 0 else 0.0
    nearing_limit = (
        committed_credits > 0
        and Decimal(credits_used) / Decimal(committed_credits) >= WARNING_USAGE_RATIO
    )
    return {
        "id": commitment.id,
        "tier": commitment.tier,
        "committed_credits": int(commitment.committed_credits or 0),
        "rate_per_credit": commitment.rate_per_credit,
        "monthly_fee_usd": commitment.monthly_fee_usd,
        "overage_rate": commitment.overage_rate,
        "status": commitment.status,
        "cancel_at_period_end": bool(commitment.cancel_at_period_end),
        "cycle_start": active_cycle.cycle_start if active_cycle else commitment.current_cycle_start,
        "cycle_end": active_cycle.cycle_end if active_cycle else commitment.current_cycle_end,
        "credits_used": credits_used,
        "credits_remaining": credits_remaining,
        "overage_credits": overage_credits,
        "usage_pct": usage_pct,
        "nearing_limit": nearing_limit,
        # SIGV2-1128: the customer surface states the cycle qualitatively, so it
        # needs the overage state as a flag. Reading overage_credits in the UI
        # would put an internal credit quantity back on the Billing page.
        "in_overage": overage_credits > 0,
        "pending_tier": commitment.pending_tier,
        "pending_change_effective_at": commitment.pending_change_effective_at,
    }


def record_commitment_usage(db: Session, *, user_id: int, amount: int) -> None:
    normalized_amount = max(0, int(amount))
    if normalized_amount <= 0:
        return
    cycle = (
        db.query(models.CommitmentUsageCycle)
        .join(
            models.CreditCommitment,
            models.CreditCommitment.id == models.CommitmentUsageCycle.commitment_id,
        )
        .filter(
            models.CreditCommitment.user_id == user_id,
            models.CreditCommitment.status.in_(["active", "past_due"]),
            models.CommitmentUsageCycle.status == "active",
        )
        .with_for_update()
        .order_by(models.CommitmentUsageCycle.cycle_start.desc())
        .first()
    )
    if cycle is None:
        return
    cycle.credits_used = int(cycle.credits_used or 0) + normalized_amount
    cycle.overage_credits = max(0, int(cycle.credits_used or 0) - int(cycle.committed_credits or 0))


def refund_commitment_usage(db: Session, *, user_id: int, amount: int) -> None:
    normalized_amount = max(0, int(amount))
    if normalized_amount <= 0:
        return
    cycle = (
        db.query(models.CommitmentUsageCycle)
        .join(
            models.CreditCommitment,
            models.CreditCommitment.id == models.CommitmentUsageCycle.commitment_id,
        )
        .filter(
            models.CreditCommitment.user_id == user_id,
            models.CreditCommitment.status.in_(["active", "past_due"]),
            models.CommitmentUsageCycle.status == "active",
        )
        .with_for_update()
        .order_by(models.CommitmentUsageCycle.cycle_start.desc())
        .first()
    )
    if cycle is None:
        return
    cycle.credits_used = max(0, int(cycle.credits_used or 0) - normalized_amount)
    cycle.overage_credits = max(0, int(cycle.credits_used or 0) - int(cycle.committed_credits or 0))


def extract_commitment_subscription_items(
    subscription_payload: Mapping[str, Any],
    *,
    db: Session,
    config: BillingConfig,
) -> tuple[str | None, str | None]:
    items = (subscription_payload.get("items") or {}).get("data") or []
    commitment_item_id: str | None = None
    overage_item_id: str | None = None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        price = item.get("price") or item.get("plan") or {}
        price_id = price.get("id") if isinstance(price, Mapping) else None
        if config.commitment_tier_for_price_id(price_id):
            commitment_item_id = str(item.get("id") or "")
        if config.is_commitment_overage_price_id(price_id):
            overage_item_id = str(item.get("id") or "")
    return commitment_item_id or None, overage_item_id or None


def resolve_subscription_commitment_tier(
    subscription_payload: Mapping[str, Any],
    *,
    db: Session,
    config: BillingConfig,
) -> CommitmentTierDefinition | None:
    items = (subscription_payload.get("items") or {}).get("data") or []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        price = item.get("price") or item.get("plan") or {}
        price_id = price.get("id") if isinstance(price, Mapping) else None
        resolved_tier = config.commitment_tier_for_price_id(price_id)
        if resolved_tier:
            return COMMITMENT_TIER_DEFINITIONS.get(resolved_tier)
    return None


def resolve_invoice_period(
    invoice_payload: Mapping[str, Any],
) -> tuple[datetime | None, datetime | None]:
    period_start = _parse_timestamp(invoice_payload.get("period_start"))
    period_end = _parse_timestamp(invoice_payload.get("period_end"))
    lines = (invoice_payload.get("lines") or {}).get("data") or []
    for line in lines:
        if not isinstance(line, Mapping):
            continue
        period = line.get("period")
        if isinstance(period, Mapping):
            period_start = period_start or _parse_timestamp(period.get("start"))
            period_end = period_end or _parse_timestamp(period.get("end"))
        if period_start and period_end:
            break
    return period_start, period_end


def grant_commitment_cycle_credits(
    db: Session,
    *,
    commitment: models.CreditCommitment,
    cycle: models.CommitmentUsageCycle,
    reason_kind: str,
    stripe_reference: str | None,
) -> models.UserCreditAdjustment:
    from auth.credits import increment_credits_atomic

    granted_credits = int(cycle.committed_credits or commitment.committed_credits or 0)
    if not increment_credits_atomic(db, commitment.user_id, granted_credits):
        raise RuntimeError(f"Failed to grant commitment credits for user {commitment.user_id}.")

    adjustment = models.UserCreditAdjustment(
        user_id=commitment.user_id,
        delta=granted_credits,
        reason=json.dumps(
            {
                "kind": reason_kind,
                "commitment_id": commitment.id,
                "tier": commitment.tier,
                "cycle_start": _cycle_label(cycle.cycle_start),
                "cycle_end": _cycle_label(cycle.cycle_end),
                "stripe_reference": stripe_reference,
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    )
    db.add(adjustment)
    return adjustment


def validate_commitment_checkout_fulfillment(
    *,
    session: Mapping[str, Any],
    subscription_payload: Mapping[str, Any],
    stripe_mode: str,
    config: BillingConfig,
    user: models.User,
    local_subscription: models.Subscription,
) -> ValidatedCommitmentCheckout:
    if not is_commitment_eligible(user):
        raise ValueError("commitment_ineligible")
    if (
        session.get("object") not in (None, "checkout.session")
        or session.get("mode") != "subscription"
        or session.get("status") != "complete"
    ):
        raise ValueError("invalid_checkout_state")
    if session.get("payment_status") not in {"paid", "no_payment_required"}:
        raise ValueError("invalid_checkout_payment")
    if session.get("currency") != BILLING_CURRENCY:
        raise ValueError("invalid_checkout_currency")
    if session.get("customer") != local_subscription.stripe_customer_id:
        raise ValueError("checkout_customer_mismatch")
    subscription_id = str(session.get("subscription") or "")
    if not subscription_id or subscription_payload.get("id") != subscription_id:
        raise ValueError("checkout_subscription_mismatch")
    if subscription_payload.get(
        "customer"
    ) != local_subscription.stripe_customer_id or subscription_payload.get("status") not in {
        "active",
        "trialing",
    }:
        raise ValueError("invalid_subscription_state")
    start = _parse_timestamp(subscription_payload.get("current_period_start"))
    end = _parse_timestamp(subscription_payload.get("current_period_end"))
    if start is None or end is None or end <= start:
        raise ValueError("invalid_subscription_period")
    items = (subscription_payload.get("items") or {}).get("data") or []
    fixed: list[tuple[CommitmentTier, str]] = []
    overage: list[str] = []
    mode_config = config.mode_configs.get(stripe_mode)
    if mode_config is None:
        raise ValueError("invalid_stripe_mode")
    for item in items:
        if not isinstance(item, Mapping) or not str(item.get("id") or ""):
            raise ValueError("invalid_subscription_item")
        price = item.get("price") or {}
        price_id = price.get("id") if isinstance(price, Mapping) else None
        tiers = [
            tier
            for tier, configured in mode_config.commitment_price_ids.items()
            if configured == price_id
        ]
        if len(tiers) == 1:
            fixed.append((tiers[0], str(item["id"])))
        elif price_id == mode_config.commitment_overage_price_id:
            overage.append(str(item["id"]))
        else:
            raise ValueError("unknown_commitment_item")
    if len(fixed) != 1 or len(overage) != 1:
        raise ValueError("invalid_commitment_composition")
    fixed_item = next(
        item for item in items if isinstance(item, Mapping) and item.get("id") == fixed[0][1]
    )
    overage_item = next(
        item for item in items if isinstance(item, Mapping) and item.get("id") == overage[0]
    )
    if fixed_item.get("quantity") != 1:
        raise ValueError("invalid_fixed_quantity")
    overage_price = overage_item.get("price") or {}
    recurring = overage_price.get("recurring") if isinstance(overage_price, Mapping) else {}
    if (
        overage_item.get("quantity") not in (None, 0)
        or not isinstance(recurring, Mapping)
        or recurring.get("usage_type") != "metered"
    ):
        raise ValueError("invalid_overage_shape")
    tier_definition = COMMITMENT_TIER_DEFINITIONS.get(fixed[0][0])
    expected_amount = (
        int((tier_definition.monthly_fee_usd * 100).to_integral_exact()) if tier_definition else -1
    )
    amount_total = session.get("amount_total")
    if isinstance(amount_total, bool) or amount_total != expected_amount:
        raise ValueError("invalid_checkout_amount")
    metadata = session.get("metadata") or {}
    if not isinstance(metadata, Mapping) or metadata.get("tier") != fixed[0][0].value:
        raise ValueError("commitment_tier_mismatch")
    return ValidatedCommitmentCheckout(
        fixed[0][0], fixed[0][1], overage[0], start, end, subscription_id
    )


def validate_commitment_renewal_invoice(
    *,
    invoice: Mapping[str, Any],
    stripe_mode: str,
    config: BillingConfig,
    commitment: models.CreditCommitment,
    local_subscription: models.Subscription,
) -> ValidatedCommitmentRenewal:
    if (
        commitment.stripe_mode not in (None, stripe_mode)
        or invoice.get("status") != "paid"
        or invoice.get("paid") is not True
        or invoice.get("billing_reason") != "subscription_cycle"
    ):
        raise ValueError("invalid_renewal_state")
    if (
        invoice.get("customer") != local_subscription.stripe_customer_id
        or invoice.get("subscription") != commitment.stripe_subscription_id
    ):
        raise ValueError("renewal_identity_mismatch")
    if invoice.get("currency") != BILLING_CURRENCY:
        raise ValueError("invalid_renewal_currency")
    paid, due = invoice.get("amount_paid"), invoice.get("amount_due")
    if isinstance(paid, bool) or not isinstance(paid, int) or paid <= 0 or paid != due:
        raise ValueError("invalid_renewal_amount")
    start, end = resolve_invoice_period(invoice)
    if start is None or end is None or end <= start:
        raise ValueError("invalid_renewal_period")
    mode_config = config.mode_configs.get(stripe_mode)
    expected_tier = commitment.tier
    if (
        commitment.pending_tier
        and commitment.pending_change_effective_at
        and commitment.pending_change_effective_at <= start
    ):
        expected_tier = commitment.pending_tier
    tier = CommitmentTier(expected_tier)
    expected_fixed = mode_config.commitment_price_ids.get(tier) if mode_config else None
    expected_overage = mode_config.commitment_overage_price_id if mode_config else None
    prices = [
        (line.get("price") or {}).get("id")
        for line in ((invoice.get("lines") or {}).get("data") or [])
        if isinstance(line, Mapping) and isinstance(line.get("price"), Mapping)
    ]
    lines = [
        line
        for line in ((invoice.get("lines") or {}).get("data") or [])
        if isinstance(line, Mapping)
    ]
    fixed_lines = [
        line
        for line in lines
        if isinstance(line.get("price"), Mapping) and line["price"].get("id") == expected_fixed
    ]
    if len(fixed_lines) != 1 or fixed_lines[0].get("quantity") != 1:
        raise ValueError("invalid_renewal_fixed_quantity")
    if prices.count(expected_fixed) != 1 or prices.count(expected_overage) != 1 or len(prices) != 2:
        raise ValueError("invalid_renewal_composition")
    tier_definition = COMMITMENT_TIER_DEFINITIONS.get(tier)
    expected_fixed_amount = (
        int((tier_definition.monthly_fee_usd * 100).to_integral_exact()) if tier_definition else -1
    )
    fixed_amount = fixed_lines[0].get("amount")
    if isinstance(fixed_amount, bool) or fixed_amount != expected_fixed_amount:
        raise ValueError("invalid_renewal_fixed_amount")
    overage_line = next(
        line
        for line in lines
        if isinstance(line.get("price"), Mapping) and line["price"].get("id") == expected_overage
    )
    overage_amount = overage_line.get("amount")
    overage_quantity = overage_line.get("quantity")
    recurring = overage_line["price"].get("recurring") or {}
    if (
        isinstance(overage_amount, bool)
        or not isinstance(overage_amount, int)
        or overage_amount < 0
        or isinstance(overage_quantity, bool)
        or (
            overage_quantity is not None
            and (not isinstance(overage_quantity, int) or overage_quantity < 0)
        )
        or not isinstance(recurring, Mapping)
        or recurring.get("usage_type") != "metered"
    ):
        raise ValueError("invalid_renewal_overage_line")
    # Discounts, tax adjustments, and credits are unsupported: totals must equal normalized lines.
    if paid != fixed_amount + overage_amount:
        raise ValueError("renewal_total_line_mismatch")
    return ValidatedCommitmentRenewal(start, end, str(expected_fixed), str(expected_overage))


def activate_commitment_from_checkout(
    db: Session,
    *,
    user: models.User,
    session_payload: Mapping[str, Any],
    subscription_payload: Mapping[str, Any],
    config: BillingConfig,
    stripe_mode: str,
) -> tuple[models.CreditCommitment, models.CommitmentUsageCycle, bool]:
    existing = get_commitment_by_subscription_id(
        db,
        stripe_subscription_id=str(subscription_payload.get("id") or ""),
    )
    if existing is not None:
        existing.stripe_mode = stripe_mode
        cycle = get_active_commitment_cycle(db, commitment_id=existing.id) or (
            db.query(models.CommitmentUsageCycle)
            .filter(models.CommitmentUsageCycle.commitment_id == existing.id)
            .order_by(models.CommitmentUsageCycle.cycle_start.desc())
            .first()
        )
        if cycle is None:
            raise RuntimeError("Existing commitment found without a usage cycle.")
        return existing, cycle, False

    tier_definition = resolve_commitment_tier_definition(
        (session_payload.get("metadata") or {}).get("tier")
    )
    if tier_definition is None:
        tier_definition = resolve_subscription_commitment_tier(
            subscription_payload,
            db=db,
            config=config,
        )
    if tier_definition is None:
        raise RuntimeError("Unable to resolve commitment tier from checkout session.")

    commitment_item_id, overage_item_id = extract_commitment_subscription_items(
        subscription_payload,
        db=db,
        config=config,
    )
    cycle_start = _parse_timestamp(subscription_payload.get("current_period_start")) or _utc_now()
    cycle_end = _parse_timestamp(subscription_payload.get("current_period_end")) or cycle_start
    commitment = models.CreditCommitment(
        user_id=user.id,
        tier=tier_definition.tier.value,
        committed_credits=tier_definition.committed_credits,
        rate_per_credit=tier_definition.rate_per_credit,
        monthly_fee_usd=tier_definition.monthly_fee_usd,
        overage_rate=tier_definition.overage_rate,
        stripe_subscription_id=str(subscription_payload.get("id") or ""),
        stripe_mode=stripe_mode,
        stripe_commitment_subscription_item_id=commitment_item_id,
        stripe_overage_subscription_item_id=overage_item_id,
        status=str(subscription_payload.get("status") or "active"),
        cancel_at_period_end=bool(subscription_payload.get("cancel_at_period_end")),
        current_cycle_start=cycle_start,
        current_cycle_end=cycle_end,
    )
    db.add(commitment)
    db.flush()

    cycle = models.CommitmentUsageCycle(
        commitment_id=commitment.id,
        user_id=user.id,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        committed_credits=tier_definition.committed_credits,
        credits_used=0,
        overage_credits=0,
        status="active",
    )
    db.add(cycle)
    db.flush()
    return commitment, cycle, True


def report_commitment_overage(
    db: Session,
    *,
    commitment: models.CreditCommitment,
    cycle: models.CommitmentUsageCycle,
    stripe_mode: str,
) -> bool:
    overage_credits = int(cycle.overage_credits or 0)
    if overage_credits <= 0:
        cycle.overage_reported = True
        return False
    if cycle.overage_reported:
        return False
    if not commitment.stripe_overage_subscription_item_id:
        raise RuntimeError("Commitment overage item id is missing.")

    enqueue_usage_record_command(
        db,
        commitment_id=commitment.id,
        cycle_id=cycle.id,
        subscription_item_id=commitment.stripe_overage_subscription_item_id,
        stripe_mode=stripe_mode,
        quantity=overage_credits,
        timestamp=int((cycle.cycle_end or _utc_now()).timestamp()),
    )
    cycle.overage_reported = True
    return True


def _apply_pending_change_if_due(
    commitment: models.CreditCommitment,
    *,
    cycle_start: datetime | None,
) -> None:
    if (
        not commitment.pending_tier
        or not commitment.pending_change_effective_at
        or cycle_start is None
    ):
        return
    if commitment.pending_change_effective_at > cycle_start:
        return

    commitment.tier = commitment.pending_tier
    if commitment.pending_committed_credits is not None:
        commitment.committed_credits = int(commitment.pending_committed_credits)
    if commitment.pending_rate_per_credit is not None:
        commitment.rate_per_credit = commitment.pending_rate_per_credit
    if commitment.pending_monthly_fee_usd is not None:
        commitment.monthly_fee_usd = commitment.pending_monthly_fee_usd

    commitment.pending_tier = None
    commitment.pending_committed_credits = None
    commitment.pending_rate_per_credit = None
    commitment.pending_monthly_fee_usd = None
    commitment.pending_change_effective_at = None


def renew_commitment_for_invoice(
    db: Session,
    *,
    commitment: models.CreditCommitment,
    invoice_payload: Mapping[str, Any],
    config: BillingConfig,
    stripe_mode: str,
) -> tuple[models.CommitmentUsageCycle | None, bool]:
    cycle_start, cycle_end = resolve_invoice_period(invoice_payload)
    if cycle_start is None or cycle_end is None:
        return None, False

    existing_cycle = (
        db.query(models.CommitmentUsageCycle)
        .filter(
            models.CommitmentUsageCycle.commitment_id == commitment.id,
            models.CommitmentUsageCycle.cycle_start == cycle_start,
        )
        .first()
    )
    commitment.status = "active"
    commitment.current_cycle_start = cycle_start
    commitment.current_cycle_end = cycle_end
    commitment.cancel_at_period_end = bool(commitment.cancel_at_period_end)
    if existing_cycle is not None:
        return existing_cycle, False

    active_cycle = get_active_commitment_cycle(db, commitment_id=commitment.id, for_update=True)
    if active_cycle is not None:
        report_commitment_overage(
            db,
            commitment=commitment,
            cycle=active_cycle,
            stripe_mode=stripe_mode,
        )
        active_cycle.status = "closed"

    _apply_pending_change_if_due(commitment, cycle_start=cycle_start)
    cycle = models.CommitmentUsageCycle(
        commitment_id=commitment.id,
        user_id=commitment.user_id,
        cycle_start=cycle_start,
        cycle_end=cycle_end,
        committed_credits=int(commitment.committed_credits or 0),
        credits_used=0,
        overage_credits=0,
        status="active",
    )
    db.add(cycle)
    db.flush()
    return cycle, True


def sync_commitment_subscription_state(
    db: Session,
    *,
    subscription_payload: Mapping[str, Any],
    config: BillingConfig,
    stripe_mode: str,
) -> models.CreditCommitment | None:
    commitment = get_commitment_by_subscription_id(
        db,
        stripe_subscription_id=str(subscription_payload.get("id") or ""),
    )
    if commitment is None:
        return None
    commitment.stripe_mode = stripe_mode
    commitment.status = str(subscription_payload.get("status") or commitment.status or "active")
    commitment.cancel_at_period_end = bool(subscription_payload.get("cancel_at_period_end"))
    commitment.current_cycle_start = _parse_timestamp(
        subscription_payload.get("current_period_start")
    )
    commitment.current_cycle_end = _parse_timestamp(subscription_payload.get("current_period_end"))
    commitment.canceled_at = (
        _utc_now() if commitment.status == "canceled" else commitment.canceled_at
    )
    commitment_item_id, overage_item_id = extract_commitment_subscription_items(
        subscription_payload,
        db=db,
        config=config,
    )
    if commitment_item_id:
        commitment.stripe_commitment_subscription_item_id = commitment_item_id
    if overage_item_id:
        commitment.stripe_overage_subscription_item_id = overage_item_id
    if commitment.status == "canceled":
        active_cycle = get_active_commitment_cycle(db, commitment_id=commitment.id, for_update=True)
        if active_cycle is not None:
            report_commitment_overage(
                db,
                commitment=commitment,
                cycle=active_cycle,
                stripe_mode=stripe_mode,
            )
            active_cycle.status = "closed"
    return commitment


def report_pending_commitment_overages(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[int]:
    reference_now = now or _utc_now()
    cycles = (
        db.query(models.CommitmentUsageCycle, models.CreditCommitment)
        .join(
            models.CreditCommitment,
            models.CreditCommitment.id == models.CommitmentUsageCycle.commitment_id,
        )
        .filter(
            models.CommitmentUsageCycle.status == "active",
            models.CommitmentUsageCycle.overage_credits > 0,
            models.CommitmentUsageCycle.overage_reported.is_(False),
            models.CommitmentUsageCycle.cycle_end <= reference_now,
        )
        .all()
    )
    reported_ids: list[int] = []
    for cycle, commitment in cycles:
        if commitment.stripe_mode not in {"test", "live"}:
            logger.warning(
                "Skipping legacy commitment overage without Stripe mode: commitment_id=%s cycle_id=%s",
                commitment.id,
                cycle.id,
            )
            continue
        if report_commitment_overage(
            db,
            commitment=commitment,
            cycle=cycle,
            stripe_mode=commitment.stripe_mode,
        ):
            reported_ids.append(cycle.id)
    return reported_ids


def collect_warning_candidates(
    db: Session,
) -> list[tuple[models.CreditCommitment, models.CommitmentUsageCycle]]:
    cycles = (
        db.query(models.CommitmentUsageCycle, models.CreditCommitment)
        .join(
            models.CreditCommitment,
            models.CreditCommitment.id == models.CommitmentUsageCycle.commitment_id,
        )
        .filter(
            models.CommitmentUsageCycle.status == "active",
            models.CommitmentUsageCycle.warning_sent_at.is_(None),
            models.CreditCommitment.status.in_(["active", "past_due"]),
        )
        .all()
    )
    warning_candidates: list[tuple[models.CreditCommitment, models.CommitmentUsageCycle]] = []
    for cycle, commitment in cycles:
        committed = int(cycle.committed_credits or 0)
        used = int(cycle.credits_used or 0)
        if committed <= 0:
            continue
        if Decimal(used) / Decimal(committed) >= WARNING_USAGE_RATIO:
            warning_candidates.append((commitment, cycle))
    return warning_candidates
