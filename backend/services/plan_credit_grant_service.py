"""Durable credit grants for paid base-plan Stripe invoices."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from app.config.plans import get_plan_capabilities
from auth.credits import increment_credits_atomic
from billing import BillingConfig, Plan


PAID_BASE_PLAN_TYPES = frozenset(
    {
        Plan.STANDARD.value,
        Plan.SPECIALIST.value,
        Plan.EXECUTIVE.value,
    }
)
SUPPORTED_BILLING_INTERVALS = frozenset({"month", "year"})


@dataclass(frozen=True)
class PlanCreditAllocation:
    plan_type: str
    credits: int
    interval: str
    period_start: int
    period_end: int
    stripe_subscription_id: str
    stripe_mode: str
    stripe_price_id: str


def _invoice_lines(invoice: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    lines = invoice.get("lines")
    if not isinstance(lines, Mapping):
        return []
    data = lines.get("data")
    if not isinstance(data, list):
        return []
    return [line for line in data if isinstance(line, Mapping)]


def _line_price_and_interval(line: Mapping[str, Any]) -> tuple[str | None, str | None]:
    price = line.get("price") or line.get("plan")
    if isinstance(price, Mapping):
        price_id = str(price.get("id") or "").strip() or None
        recurring = price.get("recurring")
        interval = recurring.get("interval") if isinstance(recurring, Mapping) else None
        if interval is None and line.get("plan") is price:
            interval = price.get("interval")
    else:
        price_id = str(price or "").strip() or None
        interval = None

    normalized_interval = str(interval or "").strip().lower() or None
    return price_id, normalized_interval


def resolve_paid_invoice_plan_allocation(
    db: Session,
    invoice: Mapping[str, Any],
    *,
    config: BillingConfig,
    stripe_mode: str,
) -> PlanCreditAllocation | None:
    """Resolve a fully paid invoice's canonical base-plan credit allocation.

    Monthly invoices grant one monthly allocation. Annual invoices grant all 12
    monthly allocations at annual payment time. Unknown prices, unsupported
    intervals, unpaid invoices, Starter, trials, and commitment prices do not
    resolve to an allocation.
    """
    if str(invoice.get("status") or "").strip().lower() != "paid":
        return None
    if invoice.get("paid") is not True:
        return None
    if invoice.get("billing_reason") not in {"subscription_create", "subscription_cycle"}:
        return None
    amount_paid = invoice.get("amount_paid")
    amount_due = invoice.get("amount_due")
    if (
        isinstance(amount_paid, bool)
        or isinstance(amount_due, bool)
        or not isinstance(amount_paid, int)
        or not isinstance(amount_due, int)
        or amount_paid <= 0
        or amount_paid != amount_due
    ):
        return None
    period_start = invoice.get("period_start")
    period_end = invoice.get("period_end")
    if (
        isinstance(period_start, bool)
        or isinstance(period_end, bool)
        or not isinstance(period_start, int)
        or not isinstance(period_end, int)
        or period_start <= 0
        or period_end <= period_start
    ):
        return None

    stripe_subscription_id = invoice.get("subscription")
    if not isinstance(stripe_subscription_id, str) or not stripe_subscription_id:
        return None
    resolved: set[tuple[str, str, str]] = set()
    for line in _invoice_lines(invoice):
        price_id, interval = _line_price_and_interval(line)
        if not price_id or interval not in SUPPORTED_BILLING_INTERVALS:
            continue
        plan = config.resolve_plan_price(stripe_mode, price_id, interval)
        if plan is None or plan.value not in PAID_BASE_PLAN_TYPES:
            continue
        resolved.add((plan.value, interval, price_id))

    # Multiple base plans or intervals on one invoice are ambiguous (for
    # example, a prorated plan change), so fail closed rather than over-grant.
    if len(resolved) != 1:
        return None

    plan_type, interval, stripe_price_id = resolved.pop()
    monthly_credits = get_plan_capabilities(plan_type).get("credits_per_month")
    if not isinstance(monthly_credits, int) or isinstance(monthly_credits, bool):
        return None
    if monthly_credits <= 0:
        return None

    multiplier = 12 if interval == "year" else 1
    return PlanCreditAllocation(
        plan_type=plan_type,
        credits=monthly_credits * multiplier,
        interval=interval,
        period_start=period_start,
        period_end=period_end,
        stripe_subscription_id=stripe_subscription_id,
        stripe_mode=stripe_mode,
        stripe_price_id=stripe_price_id,
    )


def grant_paid_invoice_plan_credits(
    db: Session,
    *,
    user_id: int,
    stripe_invoice_id: str,
    allocation: PlanCreditAllocation,
) -> bool:
    """Grant one paid invoice allocation exactly once in the current transaction.

    The user row lock serializes concurrent deliveries for the same wallet. The
    unique ``plan_credit_grants.stripe_invoice_id`` constraint provides the
    durable cross-event idempotency boundary.
    """
    normalized_invoice_id = str(stripe_invoice_id or "").strip()
    if not normalized_invoice_id:
        return False

    locked_user = db.execute(
        select(models.User).where(models.User.id == user_id).with_for_update()
    ).scalar_one_or_none()
    if locked_user is None:
        return False

    entitlement_key = (
        f"{allocation.stripe_subscription_id}:{allocation.plan_type}:{allocation.interval}:"
        f"{allocation.period_start}:"
        f"{allocation.period_end}"
    )
    existing_grant = db.execute(
        select(models.PlanCreditGrant.id).where(
            (models.PlanCreditGrant.stripe_invoice_id == normalized_invoice_id)
            | (models.PlanCreditGrant.entitlement_key == entitlement_key)
        )
    ).scalar_one_or_none()
    if existing_grant is not None:
        return False

    if not increment_credits_atomic(db, locked_user.id, allocation.credits):
        raise RuntimeError(f"Unable to grant plan credits to user {locked_user.id}")

    db.add(
        models.PlanCreditGrant(
            stripe_invoice_id=normalized_invoice_id,
            entitlement_key=entitlement_key,
            stripe_mode=allocation.stripe_mode,
            stripe_price_id=allocation.stripe_price_id,
            period_start=allocation.period_start,
            period_end=allocation.period_end,
            user_id=locked_user.id,
            plan_type=allocation.plan_type,
            credits=allocation.credits,
            interval=allocation.interval,
        )
    )
    db.add(
        models.UserCreditAdjustment(
            user_id=locked_user.id,
            admin_user_id=None,
            delta=allocation.credits,
            reason=json.dumps(
                {
                    "interval": allocation.interval,
                    "kind": "plan_invoice_credit_grant",
                    "plan_type": allocation.plan_type,
                    "stripe_invoice_id": normalized_invoice_id,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
        )
    )
    db.flush()
    return True
