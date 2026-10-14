from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
from typing import Any, Literal, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from app.config.plans import get_plan_weight, resolve_plan_alias
from billing.config import Plan


PlanChangeKind = Literal["upgrade", "downgrade", "interval_change"]
BillingInterval = Literal["month", "year"]
_VALID_BILLING_INTERVALS = frozenset(("month", "year"))
_PENDING_PLAN_VALUES = frozenset((Plan.STARTER, Plan.STANDARD, Plan.SPECIALIST, Plan.EXECUTIVE))


@dataclass(frozen=True)
class PlanChangeDecision:
    kind: PlanChangeKind
    immediate: bool
    current_plan: str
    current_interval: str
    target_plan: Plan
    target_interval: str


@dataclass(frozen=True)
class StripeSubscriptionState:
    subscription_id: str
    customer_id: str
    status: str
    collection_method: str
    item_id: str
    price_id: str
    billing_interval: BillingInterval
    quantity: int
    current_period_start: int
    current_period_end: int
    schedule_id: str | None
    metadata: Mapping[str, str]


@dataclass(frozen=True)
class DowngradeScheduleSpec:
    subscription_id: str
    customer_id: str
    current_price_id: str
    current_interval: BillingInterval
    current_quantity: int
    current_period_start: int
    current_period_end: int
    target_price_id: str
    target_interval: BillingInterval
    metadata: Mapping[str, str]
    current_phase: Mapping[str, object] | None = None


@dataclass(frozen=True)
class ValidatedImmediatePlanChange:
    status: str
    billing_interval: BillingInterval
    current_period_end: int


def _stripe_value(value: object, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def _stripe_id(value: object) -> str | None:
    if isinstance(value, str):
        return value if value else None
    identifier = _stripe_value(value, "id")
    return identifier if isinstance(identifier, str) and identifier else None


def stripe_subscription_item_id(stripe_subscription: object) -> str:
    items = _stripe_value(_stripe_value(stripe_subscription, "items"), "data")
    if not isinstance(items, (list, tuple)) or len(items) != 1:
        raise ValueError("invalid_subscription_items")
    item_id = _stripe_id(items[0])
    if item_id is None:
        raise ValueError("invalid_subscription_item")
    return item_id


def extract_stripe_subscription_state(
    stripe_subscription: object,
) -> StripeSubscriptionState:
    subscription_id = _stripe_id(stripe_subscription)
    customer_id = _stripe_id(_stripe_value(stripe_subscription, "customer"))
    status = _stripe_value(stripe_subscription, "status")
    collection_method = _stripe_value(stripe_subscription, "collection_method")
    items = _stripe_value(_stripe_value(stripe_subscription, "items"), "data")
    current_period_start = _stripe_value(stripe_subscription, "current_period_start")
    current_period_end = _stripe_value(stripe_subscription, "current_period_end")
    schedule = _stripe_value(stripe_subscription, "schedule")
    schedule_id = _stripe_id(schedule)
    metadata = _stripe_value(stripe_subscription, "metadata")
    if subscription_id is None:
        raise ValueError("invalid_subscription_id")
    if customer_id is None:
        raise ValueError("invalid_subscription_customer")
    if status not in {"active", "trialing"}:
        raise ValueError("invalid_subscription_status")
    if collection_method != "charge_automatically":
        raise ValueError("unsupported_collection_method")
    if not isinstance(items, (list, tuple)) or len(items) != 1:
        raise ValueError("invalid_subscription_items")
    item = items[0]
    item_id = _stripe_id(item)
    price = _stripe_value(item, "price")
    price_id = _stripe_id(price)
    interval = _stripe_value(_stripe_value(price, "recurring"), "interval")
    quantity = _stripe_value(item, "quantity")
    if item_id is None or price_id is None:
        raise ValueError("invalid_subscription_item")
    if interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_subscription_interval")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError("invalid_subscription_quantity")
    if (
        isinstance(current_period_start, bool)
        or not isinstance(current_period_start, int)
        or current_period_start <= 0
    ):
        raise ValueError("invalid_current_period_start")
    if (
        isinstance(current_period_end, bool)
        or not isinstance(current_period_end, int)
        or current_period_end <= current_period_start
    ):
        raise ValueError("invalid_current_period_end")
    if schedule is not None and schedule_id is None:
        raise ValueError("invalid_subscription_schedule")
    if not isinstance(metadata, Mapping):
        raise ValueError("invalid_subscription_metadata")
    return StripeSubscriptionState(
        subscription_id=subscription_id,
        customer_id=customer_id,
        status=status,
        collection_method=collection_method,
        item_id=item_id,
        price_id=price_id,
        billing_interval=interval,
        quantity=quantity,
        current_period_start=current_period_start,
        current_period_end=current_period_end,
        schedule_id=schedule_id,
        metadata=metadata,
    )


def validate_current_stripe_subscription(
    stripe_subscription: object,
    *,
    subscription_id: str,
    customer_id: str,
    status: str,
    price_id: str,
    billing_interval: str,
) -> StripeSubscriptionState:
    state = extract_stripe_subscription_state(stripe_subscription)
    if state.subscription_id != subscription_id:
        raise ValueError("subscription_id_mismatch")
    if state.customer_id != customer_id:
        raise ValueError("subscription_customer_mismatch")
    if state.status != status:
        raise ValueError("subscription_status_mismatch")
    if state.price_id != price_id:
        raise ValueError("subscription_price_mismatch")
    if state.billing_interval != billing_interval:
        raise ValueError("subscription_interval_mismatch")
    return state


def validate_immediate_plan_change(
    stripe_subscription: object,
    *,
    subscription_id: str,
    customer_id: str,
    target_price_id: str,
    target_interval: str,
    expected_quantity: int,
    metadata: Mapping[str, str],
) -> ValidatedImmediatePlanChange:
    state = extract_stripe_subscription_state(stripe_subscription)
    if state.subscription_id != subscription_id:
        raise ValueError("subscription_id_mismatch")
    if state.customer_id != customer_id:
        raise ValueError("subscription_customer_mismatch")
    if state.price_id != target_price_id:
        raise ValueError("subscription_price_mismatch")
    if state.billing_interval != target_interval:
        raise ValueError("subscription_interval_mismatch")
    if state.quantity != expected_quantity:
        raise ValueError("subscription_quantity_mismatch")
    if state.schedule_id is not None:
        raise ValueError("unexpected_attached_schedule")
    if any(state.metadata.get(key) != value for key, value in metadata.items()):
        raise ValueError("subscription_metadata_mismatch")
    return ValidatedImmediatePlanChange(
        status=state.status,
        billing_interval=state.billing_interval,
        current_period_end=state.current_period_end,
    )


def resolve_immediate_plan_change_state(
    stripe_subscription: object,
    *,
    subscription_id: str,
    customer_id: str,
    current_status: str,
    current_price_id: str,
    current_interval: str,
    target_price_id: str,
    target_interval: str,
    metadata: Mapping[str, str],
) -> tuple[StripeSubscriptionState, bool]:
    state = extract_stripe_subscription_state(stripe_subscription)
    if state.subscription_id != subscription_id:
        raise ValueError("subscription_id_mismatch")
    if state.customer_id != customer_id:
        raise ValueError("subscription_customer_mismatch")
    target_state_matches = (
        state.price_id == target_price_id and state.billing_interval == target_interval
    )
    metadata_matches = all(state.metadata.get(key) == value for key, value in metadata.items())
    if target_state_matches:
        if not metadata_matches:
            raise ValueError("subscription_metadata_mismatch")
        return state, True
    if metadata_matches:
        raise ValueError("subscription_target_state_mismatch")
    if state.status != current_status:
        raise ValueError("subscription_status_mismatch")
    if state.price_id != current_price_id:
        raise ValueError("subscription_price_mismatch")
    if state.billing_interval != current_interval:
        raise ValueError("subscription_interval_mismatch")
    return state, False


def immediate_plan_change_metadata(
    *,
    user_id: int,
    decision: PlanChangeDecision,
) -> dict[str, str]:
    return {
        "user_id": str(user_id),
        "plan": decision.target_plan.value,
        "billing_interval": decision.target_interval,
        "change_direction": decision.kind,
        "previous_plan": decision.current_plan,
        "previous_billing_interval": decision.current_interval,
    }


def immediate_plan_change_idempotency_key(
    *,
    subscription_id: int,
    stripe_mode: str,
    decision: PlanChangeDecision,
    operation_id: str,
) -> str:
    normalized_operation_id = operation_id.strip()
    if not normalized_operation_id:
        raise ValueError("invalid_operation_id")
    return (
        f"plan-change-immediate:{subscription_id}:{stripe_mode}:"
        f"{decision.current_plan}:{decision.current_interval}:"
        f"{decision.target_plan.value}:{decision.target_interval}:"
        f"{normalized_operation_id}"
    )


def downgrade_plan_change_metadata(
    *,
    user_id: int,
    subscription_record_id: int,
    decision: PlanChangeDecision,
) -> dict[str, str]:
    if decision.kind != "downgrade" or decision.immediate:
        raise ValueError("invalid_downgrade_decision")
    return {
        "user_id": str(user_id),
        "plan": decision.target_plan.value,
        "billing_interval": decision.target_interval,
        "change_direction": "downgrade",
        "previous_plan": decision.current_plan,
        "previous_billing_interval": decision.current_interval,
        "qiko_schedule_kind": "plan_change",
        "qiko_subscription_record_id": str(subscription_record_id),
    }


def downgrade_schedule_operation_id(
    *,
    subscription_id: int,
    stripe_mode: str,
    decision: PlanChangeDecision,
    current_period_end: int,
    previous_pending_plan: str | None,
    previous_pending_interval: str | None,
) -> str:
    canonical = ":".join(
        (
            str(subscription_id),
            stripe_mode,
            decision.current_plan,
            decision.current_interval,
            previous_pending_plan or "none",
            previous_pending_interval or "none",
            decision.target_plan.value,
            decision.target_interval,
            str(current_period_end),
        )
    )
    return f"pc_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def downgrade_schedule_idempotency_key(
    *,
    action: Literal["create", "modify"],
    subscription_id: int,
    stripe_mode: str,
    decision: PlanChangeDecision,
    operation_id: str,
) -> str:
    normalized_operation_id = operation_id.strip()
    if not normalized_operation_id:
        raise ValueError("invalid_operation_id")
    return (
        f"plan-change-schedule-{action}:{subscription_id}:{stripe_mode}:"
        f"{decision.current_plan}:{decision.current_interval}:"
        f"{decision.target_plan.value}:{decision.target_interval}:"
        f"{normalized_operation_id}"
    )


def build_downgrade_schedule_spec(
    state: StripeSubscriptionState,
    *,
    target_price_id: str,
    target_interval: str,
    metadata: Mapping[str, str],
) -> DowngradeScheduleSpec:
    if target_interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_target_interval")
    if not target_price_id or not target_price_id.strip():
        raise ValueError("invalid_target_price")
    if not isinstance(metadata, Mapping) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()
    ):
        raise ValueError("invalid_downgrade_metadata")
    return DowngradeScheduleSpec(
        subscription_id=state.subscription_id,
        customer_id=state.customer_id,
        current_price_id=state.price_id,
        current_interval=state.billing_interval,
        current_quantity=state.quantity,
        current_period_start=state.current_period_start,
        current_period_end=state.current_period_end,
        target_price_id=target_price_id,
        target_interval=target_interval,
        metadata=dict(metadata),
    )


_PRESERVED_PHASE_KEYS = frozenset(
    {
        "start_date",
        "end_date",
        "items",
        "coupon",
        "discounts",
        "default_tax_rates",
        "automatic_tax",
        "billing_cycle_anchor",
        "currency",
        "description",
        "proration_behavior",
        "collection_method",
        "invoice_settings",
        "billing_thresholds",
        "transfer_data",
        "application_fee_percent",
        "default_payment_method",
        "metadata",
        "trial_end",
        "add_invoice_items",
        "on_behalf_of",
    }
)
_PRESERVED_ITEM_KEYS = frozenset(
    {
        "price",
        "plan",
        "quantity",
        "metadata",
        "tax_rates",
        "billing_thresholds",
        "discounts",
    }
)


def _preserved_current_phase(
    phase: object,
    *,
    spec: DowngradeScheduleSpec,
) -> dict[str, object]:
    if not isinstance(phase, Mapping):
        raise ValueError("invalid_current_schedule_phase")
    unexpected_phase_keys = set(phase) - _PRESERVED_PHASE_KEYS
    if unexpected_phase_keys:
        raise ValueError("unsupported_current_schedule_phase")
    coupon = phase.get("coupon")
    discounts = phase.get("discounts")
    if coupon is not None and coupon != "" and discounts:
        raise ValueError("conflicting_schedule_discounts")
    if phase.get("start_date") != spec.current_period_start:
        raise ValueError("current_phase_start_mismatch")
    if phase.get("end_date") != spec.current_period_end:
        raise ValueError("current_phase_end_mismatch")
    items = phase.get("items")
    if not isinstance(items, (list, tuple)) or len(items) != 1:
        raise ValueError("invalid_schedule_phase_items")
    item = items[0]
    if not isinstance(item, Mapping):
        raise ValueError("invalid_schedule_phase_item")
    unexpected_item_keys = set(item) - _PRESERVED_ITEM_KEYS
    if unexpected_item_keys:
        raise ValueError("unsupported_schedule_phase_item")
    price = item.get("price")
    if _stripe_id(price) != spec.current_price_id:
        raise ValueError("schedule_phase_price_mismatch")
    plan = item.get("plan")
    if plan is not None and _stripe_id(plan) != spec.current_price_id:
        raise ValueError("schedule_phase_plan_mismatch")
    if _stripe_value(_stripe_value(price, "recurring"), "interval") != spec.current_interval:
        raise ValueError("schedule_phase_interval_mismatch")
    if item.get("quantity") != spec.current_quantity:
        raise ValueError("schedule_phase_quantity_mismatch")
    preserved = deepcopy(dict(phase))
    preserved_item = deepcopy(dict(item))
    preserved_item["price"] = spec.current_price_id
    preserved_item.pop("plan", None)
    if not preserved_item.get("discounts"):
        preserved_item.pop("discounts", None)
    preserved["items"] = [preserved_item]
    if coupon is None or coupon == "":
        preserved.pop("coupon", None)
    elif not isinstance(coupon, str):
        coupon_id = _stripe_id(coupon)
        if coupon_id is None:
            raise ValueError("invalid_schedule_coupon")
        preserved["coupon"] = coupon_id
    if not discounts:
        preserved.pop("discounts", None)
    tax_rates = preserved.get("default_tax_rates")
    if isinstance(tax_rates, list):
        normalized_tax_rates = []
        for tax_rate in tax_rates:
            tax_rate_id = _stripe_id(tax_rate)
            if tax_rate_id is None:
                raise ValueError("invalid_schedule_tax_rate")
            normalized_tax_rates.append(tax_rate_id)
        preserved["default_tax_rates"] = normalized_tax_rates
    for key in ("default_payment_method", "on_behalf_of"):
        value = preserved.get(key)
        if value is not None and not isinstance(value, str):
            value_id = _stripe_id(value)
            if value_id is None:
                raise ValueError(f"invalid_schedule_{key}")
            preserved[key] = value_id
    transfer_data = preserved.get("transfer_data")
    if isinstance(transfer_data, Mapping):
        normalized_transfer = deepcopy(dict(transfer_data))
        destination = normalized_transfer.get("destination")
        if destination is not None and not isinstance(destination, str):
            destination_id = _stripe_id(destination)
            if destination_id is None:
                raise ValueError("invalid_schedule_transfer_destination")
            normalized_transfer["destination"] = destination_id
        preserved["transfer_data"] = normalized_transfer
    return preserved


def attach_current_schedule_phase(
    spec: DowngradeScheduleSpec,
    schedule: object,
) -> DowngradeScheduleSpec:
    phases = _stripe_value(schedule, "phases")
    if not isinstance(phases, (list, tuple)) or not phases:
        raise ValueError("missing_current_schedule_phase")
    return replace(
        spec,
        current_phase=_preserved_current_phase(phases[0], spec=spec),
    )


def downgrade_schedule_phases(
    spec: DowngradeScheduleSpec,
) -> list[dict[str, object]]:
    if spec.current_phase is None:
        raise ValueError("missing_current_schedule_phase")
    return [
        deepcopy(dict(spec.current_phase)),
        {
            "start_date": spec.current_period_end,
            "items": [
                {
                    "price": spec.target_price_id,
                    "quantity": spec.current_quantity,
                }
            ],
            "metadata": dict(spec.metadata),
        },
    ]


def stripe_schedule_id(schedule: object) -> str:
    schedule_id = _stripe_id(schedule)
    if schedule_id is None or not schedule_id.startswith("sub_sched_") or len(schedule_id) < 18:
        raise ValueError("invalid_schedule_id")
    return schedule_id


def validate_owned_active_schedule(
    schedule: object,
    *,
    subscription_id: str,
    customer_id: str,
    schedule_id: str | None = None,
) -> str:
    returned_schedule_id = _stripe_id(schedule)
    if (
        returned_schedule_id is None
        or not returned_schedule_id.startswith("sub_sched_")
        or len(returned_schedule_id) < 18
    ):
        raise ValueError("invalid_schedule_id")
    if schedule_id is not None and returned_schedule_id != schedule_id:
        raise ValueError("schedule_id_mismatch")
    if _stripe_id(_stripe_value(schedule, "customer")) != customer_id:
        raise ValueError("schedule_customer_mismatch")
    if _stripe_id(_stripe_value(schedule, "subscription")) != subscription_id:
        raise ValueError("schedule_subscription_mismatch")
    if _stripe_value(schedule, "status") != "active":
        raise ValueError("invalid_schedule_status")
    return returned_schedule_id


def validate_plan_change_schedule_owner(
    schedule: object,
    *,
    subscription_record_id: int,
    target_plan: Plan | None = None,
    target_interval: str | None = None,
) -> None:
    metadata = _stripe_value(schedule, "metadata")
    if not isinstance(metadata, Mapping):
        raise ValueError("missing_plan_change_schedule_metadata")
    if metadata.get("qiko_schedule_kind") != "plan_change":
        raise ValueError("schedule_kind_mismatch")
    if metadata.get("qiko_subscription_record_id") != str(subscription_record_id):
        raise ValueError("schedule_owner_mismatch")
    if target_plan is not None and metadata.get("plan") != target_plan.value:
        raise ValueError("schedule_target_plan_mismatch")
    if target_interval is not None and metadata.get("billing_interval") != target_interval:
        raise ValueError("schedule_target_interval_mismatch")


def _validate_schedule_phase_item(
    phase: object,
    *,
    price_id: str,
    interval: BillingInterval,
    quantity: int,
) -> None:
    items = _stripe_value(phase, "items")
    if not isinstance(items, (list, tuple)) or len(items) != 1:
        raise ValueError("invalid_schedule_phase_items")
    item = items[0]
    price = _stripe_value(item, "price")
    if _stripe_id(price) != price_id:
        raise ValueError("schedule_phase_price_mismatch")
    if _stripe_value(_stripe_value(price, "recurring"), "interval") != interval:
        raise ValueError("schedule_phase_interval_mismatch")
    if _stripe_value(item, "quantity") != quantity:
        raise ValueError("schedule_phase_quantity_mismatch")


def validate_configured_downgrade_schedule(
    schedule: object,
    *,
    schedule_id: str,
    spec: DowngradeScheduleSpec,
) -> None:
    validate_owned_active_schedule(
        schedule,
        schedule_id=schedule_id,
        subscription_id=spec.subscription_id,
        customer_id=spec.customer_id,
    )
    if _stripe_value(schedule, "end_behavior") != "release":
        raise ValueError("invalid_schedule_end_behavior")
    schedule_metadata = _stripe_value(schedule, "metadata")
    if not isinstance(schedule_metadata, Mapping) or dict(schedule_metadata) != dict(spec.metadata):
        raise ValueError("schedule_metadata_mismatch")

    phases = _stripe_value(schedule, "phases")
    if not isinstance(phases, (list, tuple)) or len(phases) != 2:
        raise ValueError("invalid_schedule_phases")
    current_phase, future_phase = phases
    if _stripe_value(current_phase, "start_date") != spec.current_period_start:
        raise ValueError("current_phase_start_mismatch")
    if _stripe_value(current_phase, "end_date") != spec.current_period_end:
        raise ValueError("current_phase_end_mismatch")
    _validate_schedule_phase_item(
        current_phase,
        price_id=spec.current_price_id,
        interval=spec.current_interval,
        quantity=spec.current_quantity,
    )
    if spec.current_phase is None or _preserved_current_phase(
        current_phase,
        spec=spec,
    ) != dict(spec.current_phase):
        raise ValueError("current_phase_configuration_mismatch")
    if _stripe_value(future_phase, "start_date") != spec.current_period_end:
        raise ValueError("future_phase_start_mismatch")
    _validate_schedule_phase_item(
        future_phase,
        price_id=spec.target_price_id,
        interval=spec.target_interval,
        quantity=spec.current_quantity,
    )
    future_metadata = _stripe_value(future_phase, "metadata")
    if not isinstance(future_metadata, Mapping) or dict(future_metadata) != dict(spec.metadata):
        raise ValueError("future_phase_metadata_mismatch")


def is_configured_downgrade_schedule(
    schedule: object,
    *,
    schedule_id: str,
    spec: DowngradeScheduleSpec,
) -> bool:
    try:
        validate_configured_downgrade_schedule(
            schedule,
            schedule_id=schedule_id,
            spec=spec,
        )
    except ValueError:
        return False
    return True


def schedule_release_idempotency_key(schedule_id: str) -> str:
    return f"plan-change-schedule-release:{schedule_id}"


def validate_pending_schedule(
    schedule: object,
    *,
    schedule_id: str,
    subscription_id: str,
    customer_id: str,
) -> Literal["active", "released"]:
    if _stripe_id(schedule) != schedule_id:
        raise ValueError("schedule_id_mismatch")
    if _stripe_id(_stripe_value(schedule, "customer")) != customer_id:
        raise ValueError("schedule_customer_mismatch")
    status = _stripe_value(schedule, "status")
    if status == "active":
        linked_subscription_id = _stripe_id(_stripe_value(schedule, "subscription"))
    elif status == "released":
        linked_subscription_id = _stripe_id(_stripe_value(schedule, "released_subscription"))
    else:
        raise ValueError("invalid_schedule_status")
    if linked_subscription_id != subscription_id:
        raise ValueError("schedule_subscription_mismatch")
    return status


def validate_released_schedule(
    schedule: object,
    *,
    schedule_id: str,
    subscription_id: str,
    customer_id: str,
) -> None:
    status = validate_pending_schedule(
        schedule,
        schedule_id=schedule_id,
        subscription_id=subscription_id,
        customer_id=customer_id,
    )
    if status != "released":
        raise ValueError("schedule_not_released")


def pending_plan_change_identity(
    subscription: models.Subscription,
) -> tuple[str, Plan, str] | None:
    values = (
        subscription.stripe_schedule_id,
        subscription.pending_plan_type,
        subscription.pending_billing_interval,
        subscription.pending_change_effective_at,
    )
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("invalid_pending_plan_change")
    schedule_id, plan_value, interval, _effective_at = values
    try:
        plan = Plan(plan_value)
    except ValueError as error:
        raise ValueError("invalid_pending_plan_change") from error
    if plan not in _PENDING_PLAN_VALUES or interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_pending_plan_change")
    return schedule_id, plan, interval


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def reconcile_pending_plan_change(
    subscription: models.Subscription,
    *,
    source_event_created_at: datetime,
    current_period_start: datetime,
    subscription_id: str,
    customer_id: str,
    stripe_mode: str,
    resolved_plan_type: str,
    billing_interval: str,
    schedule_id: str | None,
) -> bool:
    if source_event_created_at.tzinfo is None or source_event_created_at.utcoffset() is None:
        raise ValueError("invalid_source_event_created_at")
    if current_period_start.tzinfo is None or current_period_start.utcoffset() is None:
        raise ValueError("invalid_current_period_start")
    pending_identity = pending_plan_change_identity(subscription)
    if pending_identity is None:
        return False
    expected_schedule_id, expected_plan, expected_interval = pending_identity
    if (
        subscription.stripe_subscription_id != subscription_id
        or subscription.stripe_customer_id != customer_id
        or subscription.stripe_mode != stripe_mode
        or resolved_plan_type != expected_plan.value
        or billing_interval != expected_interval
        or schedule_id != expected_schedule_id
    ):
        return False
    effective_at = subscription.pending_change_effective_at
    if not isinstance(effective_at, datetime):
        raise ValueError("invalid_pending_change_effective_at")
    if current_period_start.astimezone(timezone.utc) != _as_utc(effective_at):
        return False
    subscription.plan_type = expected_plan.value
    subscription.billing_interval = expected_interval
    subscription.managed_plan_change_schedule_id = expected_schedule_id
    return clear_pending_plan_change(
        subscription,
        expected_schedule_id=expected_schedule_id,
        expected_plan=expected_plan,
        expected_interval=expected_interval,
    )


def classify_plan_change(
    current_plan: str,
    current_interval: str,
    target_plan: Plan,
    target_interval: str,
) -> PlanChangeDecision:
    if current_interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_current_interval")
    if target_interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_target_interval")

    resolved_current_plan = resolve_plan_alias(current_plan) or current_plan
    if resolved_current_plan == target_plan.value:
        if current_interval == target_interval:
            raise ValueError("same_plan")
        return PlanChangeDecision(
            kind="interval_change",
            immediate=True,
            current_plan=current_plan,
            current_interval=current_interval,
            target_plan=target_plan,
            target_interval=target_interval,
        )

    current_weight = get_plan_weight(resolved_current_plan)
    target_weight = get_plan_weight(target_plan.value)
    if target_weight > current_weight:
        kind: PlanChangeKind = "upgrade"
        immediate = True
    else:
        kind = "downgrade"
        immediate = False

    return PlanChangeDecision(
        kind=kind,
        immediate=immediate,
        current_plan=current_plan,
        current_interval=current_interval,
        target_plan=target_plan,
        target_interval=target_interval,
    )


def lock_subscription_for_plan_change(
    db: Session,
    subscription_id: int,
) -> models.Subscription:
    statement = (
        select(models.Subscription)
        .where(models.Subscription.id == subscription_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    subscription = db.execute(statement).scalar_one_or_none()
    if subscription is None:
        raise ValueError("subscription_not_found")
    return subscription


def set_pending_plan_change(
    subscription: models.Subscription,
    stripe_schedule_id: str,
    target_plan: Plan,
    target_interval: str,
    effective_at: datetime,
) -> None:
    if not stripe_schedule_id or not stripe_schedule_id.strip():
        raise ValueError("invalid_stripe_schedule_id")
    if target_plan not in _PENDING_PLAN_VALUES:
        raise ValueError("invalid_target_plan")
    if target_interval not in _VALID_BILLING_INTERVALS:
        raise ValueError("invalid_target_interval")
    if effective_at.tzinfo is None or effective_at.utcoffset() is None:
        raise ValueError("invalid_effective_at")

    subscription.stripe_schedule_id = stripe_schedule_id
    subscription.pending_plan_type = target_plan.value
    subscription.pending_billing_interval = target_interval
    subscription.pending_change_effective_at = effective_at


def clear_pending_plan_change(
    subscription: models.Subscription,
    expected_schedule_id: str,
    expected_plan: Plan,
    expected_interval: str,
) -> bool:
    if (
        subscription.stripe_schedule_id != expected_schedule_id
        or subscription.pending_plan_type != expected_plan.value
        or subscription.pending_billing_interval != expected_interval
    ):
        return False

    subscription.stripe_schedule_id = None
    subscription.pending_plan_type = None
    subscription.pending_billing_interval = None
    subscription.pending_change_effective_at = None
    return True
