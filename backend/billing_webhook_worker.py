import asyncio
import logging
from dataclasses import dataclass
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from core.env_bootstrap import bootstrap_environment
from core.redis_client import get_async_redis_client
from sqlalchemy import select
from sqlalchemy.orm import Session
import stripe

bootstrap_environment()

import models
from app.services.billing_retention import retention_until_for_invoice
from billing import BILLING_CURRENCY_DISPLAY, BillingConfig, load_billing_config
from billing.base_checkout_service import (
    complete_base_checkout_attempt,
    normalize_base_checkout_metadata,
)
from billing.plan_change_service import (
    pending_plan_change_identity,
    reconcile_pending_plan_change,
)
from billing.stripe_command_service import (
    STRIPE_COMMAND_BATCH_SIZE,
    claim_command,
    complete_command,
    fail_command,
    list_due_command_ids,
)
from billing.stripe_event_service import (
    STRIPE_EVENT_DUE_BATCH_SIZE,
    STRIPE_EVENT_MAX_ATTEMPTS,
    claim_event,
    complete_event,
    fail_event,
    list_due_event_ids,
    lock_claimed_event,
)
from database import SessionLocal
from observability import configure_logging, init_tracing
from services.credit_commitment_service import (
    activate_commitment_from_checkout,
    get_commitment_by_subscription_id,
    grant_commitment_cycle_credits,
    renew_commitment_for_invoice,
    resolve_subscription_commitment_tier,
    sync_commitment_subscription_state,
    validate_commitment_checkout_fulfillment,
    validate_commitment_renewal_invoice,
)
from services.email_service import EmailService
from services.plan_credit_grant_service import (
    grant_paid_invoice_plan_credits,
    resolve_paid_invoice_plan_allocation,
)

logger = logging.getLogger(__name__)

STRIPE_WEBHOOK_QUEUE_NAME = os.getenv("STRIPE_WEBHOOK_QUEUE_NAME", "billing:webhook_events")
_TERMINAL_BASE_SUBSCRIPTION_STATUSES = {"canceled", "incomplete_expired"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_timestamp(timestamp: Any) -> datetime | None:
    if isinstance(timestamp, (int, float)):
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return None


def _get_nested(mapping: Mapping[str, Any], *keys: Any) -> Optional[Any]:
    current: Any = mapping
    for key in keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            if key >= len(current):
                return None
            current = current[key]
        else:
            return None
    return current


def _resolve_user_id(
    db: Session,
    *,
    obj: Mapping[str, Any],
    stripe_customer_id: str | None,
) -> int | None:
    metadata = obj.get("metadata") or {}
    user_id_value = metadata.get("user_id") or obj.get("client_reference_id")
    if user_id_value:
        try:
            return int(str(user_id_value))
        except (TypeError, ValueError):
            pass
    if stripe_customer_id:
        return db.execute(
            select(models.Subscription.user_id).where(
                models.Subscription.stripe_customer_id == stripe_customer_id
            )
        ).scalar_one_or_none()
    return None


def _lock_user_subscription(
    db: Session,
    *,
    user_id: int,
) -> tuple[models.User, models.Subscription | None]:
    user = db.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one()
    subscription = db.execute(
        select(models.Subscription)
        .where(models.Subscription.user_id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one_or_none()
    return user, subscription


def _resolve_user(
    db: Session,
    *,
    obj: Mapping[str, Any],
    stripe_customer_id: str | None,
) -> models.User | None:
    metadata = obj.get("metadata") or {}
    user_id_value = metadata.get("user_id") or obj.get("client_reference_id")
    if user_id_value:
        try:
            user_id = int(str(user_id_value))
        except (TypeError, ValueError):
            user_id = None
        if user_id is not None:
            user = db.query(models.User).filter(models.User.id == user_id).first()
            if user:
                return user

    if stripe_customer_id:
        subscription = (
            db.query(models.Subscription)
            .filter(models.Subscription.stripe_customer_id == stripe_customer_id)
            .first()
        )
        if subscription:
            return db.query(models.User).filter(models.User.id == subscription.user_id).first()
    return None


def _stripe_object_to_dict(payload: object) -> dict[str, object]:
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


def _plan_type_from_price_id(
    price_id: str | None,
    config: BillingConfig,
    *,
    stripe_mode: str,
    interval: str | None,
) -> str | None:
    if not price_id or interval not in {"month", "year"}:
        return None
    resolved_plan = config.resolve_plan_price(stripe_mode, price_id, interval)
    return resolved_plan.value if resolved_plan else None


def _extract_billing_interval(obj: Mapping[str, Any]) -> str | None:
    """Extract billing interval (month/year) from Stripe subscription or invoice object."""
    interval = _get_nested(obj, "items", "data", 0, "price", "recurring", "interval")
    if interval in ("month", "year"):
        return interval
    interval = _get_nested(obj, "lines", "data", 0, "price", "recurring", "interval")
    if interval in ("month", "year"):
        return interval
    return None


def _extract_price_id(obj: Mapping[str, Any]) -> str | None:
    return (
        _get_nested(obj, "items", "data", 0, "price", "id")
        or _get_nested(obj, "items", "data", 0, "plan", "id")
        or _get_nested(obj, "lines", "data", 0, "price", "id")
        or _get_nested(obj, "lines", "data", 0, "plan", "id")
    )


def _resolve_base_subscription_item_pair(
    obj: Mapping[str, Any],
    *,
    config: BillingConfig,
    stripe_mode: str,
) -> tuple[str, str] | None:
    items = _get_nested(obj, "items", "data")
    if not isinstance(items, list) or len(items) != 1:
        return None
    item = items[0]
    if not isinstance(item, Mapping):
        return None
    price = item.get("price") or item.get("plan")
    if not isinstance(price, Mapping):
        return None
    price_id = price.get("id")
    interval = _get_nested(price, "recurring", "interval")
    if not isinstance(price_id, str) or interval not in {"month", "year"}:
        return None
    plan = _plan_type_from_price_id(
        price_id,
        config,
        stripe_mode=stripe_mode,
        interval=interval,
    )
    if plan is None:
        return None
    return plan, interval


def _upsert_subscription(
    db: Session,
    *,
    user: models.User | None,
    stripe_customer_id: str | None,
    stripe_subscription_id: str | None,
    status: str | None,
    plan_type: str | None,
    current_period_end: datetime | None,
    cancel_at_period_end: bool | None,
    billing_interval: str | None = None,
    stripe_mode: str | None = None,
    locked_subscription: models.Subscription | None = None,
    subscription_fenced: bool = False,
    allow_terminal_rollover: bool = False,
) -> models.Subscription | None:
    owner_id = user.id if user is not None else None
    if owner_id is None and stripe_customer_id:
        owner_id = db.execute(
            select(models.Subscription.user_id).where(
                models.Subscription.stripe_customer_id == stripe_customer_id
            )
        ).scalar_one_or_none()
    if owner_id is not None and not subscription_fenced:
        user, locked_subscription = _lock_user_subscription(db, user_id=owner_id)

    subscription = locked_subscription
    if subscription and user and subscription.user_id != user.id:
        raise ValueError("subscription_customer_user_mismatch")

    if not subscription:
        if not user or not stripe_customer_id:
            logger.warning("Unable to create subscription without user or customer id.")
            return None
        subscription = models.Subscription(
            user_id=user.id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            plan_type=plan_type or "plan_standard",
            status=status or "pending",
            stripe_mode=stripe_mode,
        )
        db.add(subscription)
    else:
        if stripe_customer_id and subscription.stripe_customer_id not in {
            "",
            stripe_customer_id,
        }:
            raise ValueError("subscription_customer_reassignment_rejected")
        if stripe_customer_id:
            subscription.stripe_customer_id = stripe_customer_id
        subscription_id_rollover = bool(
            stripe_subscription_id
            and subscription.stripe_subscription_id
            not in {
                None,
                "",
                stripe_subscription_id,
            }
        )
        if subscription_id_rollover and (
            not allow_terminal_rollover
            or subscription.status not in _TERMINAL_BASE_SUBSCRIPTION_STATUSES
        ):
            raise ValueError("subscription_id_reassignment_rejected")
        if stripe_mode and subscription.stripe_mode not in {None, "", stripe_mode}:
            raise ValueError("subscription_mode_reassignment_rejected")
        if subscription_id_rollover:
            subscription.stripe_schedule_id = None
            subscription.managed_plan_change_schedule_id = None
            subscription.pending_plan_type = None
            subscription.pending_billing_interval = None
            subscription.pending_change_effective_at = None
        if stripe_subscription_id:
            subscription.stripe_subscription_id = stripe_subscription_id
        if status:
            subscription.status = status
        if plan_type:
            subscription.plan_type = plan_type
        if stripe_mode:
            subscription.stripe_mode = stripe_mode

    if current_period_end:
        subscription.current_period_end = current_period_end
    if cancel_at_period_end is not None:
        subscription.cancel_at_period_end = cancel_at_period_end
    if billing_interval:
        subscription.billing_interval = billing_interval

    return subscription


def _upsert_payment(
    db: Session,
    *,
    user: models.User,
    invoice: Mapping[str, Any],
    status: str,
) -> None:
    stripe_invoice_id = invoice.get("id")
    if not stripe_invoice_id:
        logger.warning("Stripe invoice id missing for payment update.")
        return

    stripe_customer_id = invoice.get("customer")
    created_at = _parse_timestamp(invoice.get("created")) or _utc_now()

    payment = (
        db.query(models.BillingPayment)
        .filter(models.BillingPayment.stripe_invoice_id == stripe_invoice_id)
        .first()
    )
    if not payment:
        payment = models.BillingPayment(
            user_id=user.id,
            stripe_invoice_id=stripe_invoice_id,
            stripe_customer_id=stripe_customer_id or "",
            stripe_subscription_id=invoice.get("subscription"),
            amount_paid=invoice.get("amount_paid"),
            amount_due=invoice.get("amount_due"),
            currency=invoice.get("currency"),
            status=status,
            created_at=created_at,
            # The statutory clock is stored when the record is created, from
            # the invoice date, not from any later event (SIGV2-1144).
            retention_until=retention_until_for_invoice(created_at),
        )
        db.add(payment)
    elif payment.anonymized_at is not None:
        # The invoice belongs to a deleted account and is retained under a
        # legal obligation. A later Stripe event must not re-attach it to a
        # living customer identity, so only the invoice facts are refreshed.
        payment.stripe_subscription_id = invoice.get("subscription")
        payment.amount_paid = invoice.get("amount_paid")
        payment.amount_due = invoice.get("amount_due")
        payment.currency = invoice.get("currency")
        payment.status = status
        payment.created_at = created_at
        payment.retention_until = retention_until_for_invoice(created_at)
    else:
        payment.user_id = user.id
        if stripe_customer_id:
            payment.stripe_customer_id = stripe_customer_id
        payment.stripe_subscription_id = invoice.get("subscription")
        payment.amount_paid = invoice.get("amount_paid")
        payment.amount_due = invoice.get("amount_due")
        payment.currency = invoice.get("currency")
        payment.status = status
        payment.created_at = created_at
        payment.retention_until = retention_until_for_invoice(created_at)


def _billing_url(config: BillingConfig) -> str:
    return f"{config.app_base_url.rstrip('/')}/dashboard/billing"


@dataclass(frozen=True)
class PreparedStripeEvent:
    config: BillingConfig
    stripe_mode: str
    subscription_payload: Mapping[str, Any] | None = None


def _stripe_api_key_for_mode(config: BillingConfig, stripe_mode: str) -> str:
    mode_config = config.mode_configs.get(stripe_mode)
    secret = mode_config.secret_key if mode_config is not None else None
    if not secret:
        raise RuntimeError(f"Stripe {stripe_mode} credential is not configured")
    return secret


def _load_billing_config_snapshot(*, bind: object | None = None) -> BillingConfig:
    read_db: Session = Session(bind=bind) if bind is not None else SessionLocal()
    try:
        config = load_billing_config(db=read_db)
        read_db.rollback()
        return config
    finally:
        read_db.close()


def _build_email_outbox(
    *,
    bind: object | None = None,
    user_id: int | None,
    to_email: str,
    template_key: str,
    context: Mapping[str, Any],
    correlation_id: str | None,
) -> models.EmailOutbox | None:
    read_db: Session = Session(bind=bind) if bind is not None else SessionLocal()
    try:
        entry = EmailService(read_db).queue_template_email(
            to_email=to_email,
            template_key=template_key,
            context=context,
            user_id=user_id,
            correlation_id=correlation_id,
        )
        if entry is not None:
            read_db.expunge(entry)
        read_db.rollback()
        return entry
    except Exception:
        read_db.rollback()
        raise
    finally:
        read_db.close()


def _enqueue_email(
    db: Session,
    *,
    user: models.User | None,
    to_email: str,
    template_key: str,
    context: Mapping[str, Any],
    correlation_id: str | None,
) -> None:
    entry = _build_email_outbox(
        bind=db.get_bind(),
        user_id=user.id if user else None,
        to_email=to_email,
        template_key=template_key,
        context=context,
        correlation_id=correlation_id,
    )
    if entry is not None:
        db.add(entry)


async def handle_event(
    db: Session,
    event_log: models.StripeEventLog,
    *,
    config: BillingConfig | None = None,
    stripe_mode: str | None = None,
    prepared_subscription_payload: Mapping[str, Any] | None = None,
) -> None:
    config = config or _load_billing_config_snapshot(bind=db.get_bind())
    payload = event_log.payload
    receipt_livemode = payload.get("livemode") if isinstance(payload, Mapping) else None
    receipt_mode = (
        "live" if receipt_livemode is True else "test" if receipt_livemode is False else None
    )
    stripe_mode = stripe_mode or receipt_mode
    if stripe_mode not in {"test", "live"} or receipt_mode != stripe_mode:
        raise ValueError("Stripe receipt mode provenance is invalid")
    logger.info("Processing Stripe event %s (%s)", event_log.event_id, event_log.event_type)
    payload = event_log.payload
    event_type = event_log.event_type
    if not isinstance(payload, Mapping):
        raise ValueError("Stripe event payload must be an object")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("Stripe event data must be an object")
    data_object = data.get("object")
    if not isinstance(data_object, Mapping):
        raise ValueError("Stripe event data.object must be an object")

    if event_type in {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }:
        if (
            get_commitment_by_subscription_id(
                db,
                stripe_subscription_id=str(data_object.get("id") or ""),
            )
            is not None
            or resolve_subscription_commitment_tier(
                data_object,
                db=db,
                config=config,
            )
            is not None
        ):
            commitment = sync_commitment_subscription_state(
                db,
                subscription_payload=data_object,
                config=config,
                stripe_mode=stripe_mode,
            )
            if commitment and event_type == "customer.subscription.deleted":
                user = db.query(models.User).filter(models.User.id == commitment.user_id).first()
                if user:
                    _enqueue_email(
                        db,
                        user=user,
                        to_email=user.email,
                        template_key="commitment.canceled",
                        context={
                            "email": user.email,
                            "user_name": user.company_name or user.email,
                            "tier": commitment.tier,
                            "manage_billing_url": _billing_url(config),
                        },
                        correlation_id=event_log.event_id,
                    )
            if commitment:
                db.flush()
            return

        stripe_customer_id = data_object.get("customer")
        user_id = _resolve_user_id(db, obj=data_object, stripe_customer_id=stripe_customer_id)
        if user_id is None:
            logger.warning("Subscription event missing user and Stripe customer id.")
            return
        user, existing_subscription = _lock_user_subscription(db, user_id=user_id)
        if existing_subscription is not None:
            incoming_subscription_id = str(data_object.get("id") or "")
            incoming_customer_id = str(stripe_customer_id or "")
            if incoming_subscription_id != existing_subscription.stripe_subscription_id:
                raise ValueError("subscription_id_reassignment_rejected")
            if incoming_customer_id != existing_subscription.stripe_customer_id:
                raise ValueError("subscription_customer_reassignment_rejected")
            if existing_subscription.stripe_mode not in {None, "", stripe_mode}:
                raise ValueError("subscription_mode_reassignment_rejected")
            if existing_subscription.stripe_mode in {None, ""}:
                existing_subscription.stripe_mode = stripe_mode
        previous_plan = existing_subscription.plan_type if existing_subscription else None
        resolved_pair = _resolve_base_subscription_item_pair(
            data_object,
            config=config,
            stripe_mode=stripe_mode,
        )
        plan_type = resolved_pair[0] if resolved_pair is not None else None
        billing_interval = resolved_pair[1] if resolved_pair is not None else None
        current_period_start = _parse_timestamp(data_object.get("current_period_start"))
        current_period_end = _parse_timestamp(data_object.get("current_period_end"))
        cancel_at_period_end = data_object.get("cancel_at_period_end")
        status = data_object.get("status") or (
            "canceled" if event_type.endswith("deleted") else None
        )
        pending_activated = False
        source_event_created_at = _as_utc(event_log.event_created_at)
        existing_pending_identity = (
            pending_plan_change_identity(existing_subscription)
            if existing_subscription is not None
            else None
        )
        existing_fence = (
            _as_utc(existing_subscription.plan_state_event_created_at)
            if existing_subscription is not None
            and existing_subscription.plan_state_event_created_at is not None
            else None
        )
        terminal_event = event_type == "customer.subscription.deleted"
        same_second_terminal_override = bool(
            terminal_event
            and existing_fence is not None
            and source_event_created_at.replace(microsecond=0)
            == existing_fence.replace(microsecond=0)
        )
        stale_event = bool(
            existing_fence is not None
            and source_event_created_at <= existing_fence
            and not same_second_terminal_override
        )
        incoming_pair_is_complete = plan_type is not None and billing_interval is not None
        plan_for_upsert = plan_type if incoming_pair_is_complete else None
        interval_for_upsert = billing_interval if incoming_pair_is_complete else None
        status_for_upsert = status
        period_end_for_upsert = current_period_end
        cancel_for_upsert = cancel_at_period_end
        if stale_event:
            plan_for_upsert = None
            interval_for_upsert = None
            status_for_upsert = None
            period_end_for_upsert = None
            cancel_for_upsert = None
        else:
            if terminal_event:
                plan_for_upsert = None
                interval_for_upsert = None
                period_end_for_upsert = None
                cancel_for_upsert = None
            if (
                not terminal_event
                and existing_subscription is not None
                and incoming_pair_is_complete
                and existing_pending_identity is not None
                and current_period_start is not None
            ):
                pending_activated = reconcile_pending_plan_change(
                    existing_subscription,
                    source_event_created_at=source_event_created_at,
                    current_period_start=current_period_start,
                    subscription_id=str(data_object.get("id") or ""),
                    customer_id=str(stripe_customer_id or ""),
                    stripe_mode=stripe_mode,
                    resolved_plan_type=plan_type,
                    billing_interval=billing_interval,
                    schedule_id=str(data_object.get("schedule") or "") or None,
                )
                if pending_activated:
                    plan_for_upsert = existing_subscription.plan_type
                    interval_for_upsert = existing_subscription.billing_interval
            incoming_schedule_id = str(data_object.get("schedule") or "") or None
            pending_schedule_conflict = bool(
                existing_pending_identity is not None
                and incoming_schedule_id != existing_pending_identity[0]
            )
            pending_pair_conflict = bool(
                existing_subscription is not None
                and incoming_pair_is_complete
                and (
                    plan_for_upsert != existing_subscription.plan_type
                    or interval_for_upsert != existing_subscription.billing_interval
                )
            )
            pending_transition_due = bool(
                existing_subscription is not None
                and current_period_start is not None
                and existing_subscription.pending_change_effective_at is not None
                and _as_utc(current_period_start)
                >= _as_utc(existing_subscription.pending_change_effective_at)
            )
            if (
                not terminal_event
                and existing_subscription is not None
                and existing_pending_identity is not None
                and not pending_activated
                and (pending_schedule_conflict or pending_pair_conflict or pending_transition_due)
            ):
                plan_for_upsert = None
                interval_for_upsert = None
                status_for_upsert = "quarantined"
                logger.error(
                    "Stripe pending subscription state could not be reconciled: user_id=%s subscription_id=%s code=pending_subscription_quarantined",
                    user_id,
                    data_object.get("id"),
                )
            if not incoming_pair_is_complete and status in {"active", "trialing"}:
                status_for_upsert = "quarantined"
                logger.error(
                    "Stripe subscription price could not be resolved: user_id=%s subscription_id=%s code=subscription_price_quarantined",
                    user_id,
                    data_object.get("id"),
                )

        subscription = _upsert_subscription(
            db,
            user=user,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=data_object.get("id"),
            status=status_for_upsert,
            plan_type=plan_for_upsert,
            current_period_end=period_end_for_upsert,
            cancel_at_period_end=cancel_for_upsert,
            billing_interval=interval_for_upsert,
            stripe_mode=stripe_mode,
            locked_subscription=existing_subscription,
            subscription_fenced=True,
        )
        authoritative_state_mutated = bool(
            plan_for_upsert is not None
            or interval_for_upsert is not None
            or status_for_upsert is not None
            or period_end_for_upsert is not None
            or cancel_for_upsert is not None
        )
        if subscription is not None and not stale_event and authoritative_state_mutated:
            subscription.plan_state_event_created_at = max(
                source_event_created_at,
                existing_fence or source_event_created_at,
            )
        if user:
            if event_type == "customer.subscription.deleted":
                _enqueue_email(
                    db,
                    user=user,
                    to_email=user.email,
                    template_key="subscription.deleted",
                    context={"email": user.email, "manage_billing_url": _billing_url(config)},
                    correlation_id=event_log.event_id,
                )
            elif (
                event_type == "customer.subscription.updated"
                and (pending_activated or existing_pending_identity is None)
                and previous_plan
                and subscription is not None
                and previous_plan != subscription.plan_type
            ):
                _enqueue_email(
                    db,
                    user=user,
                    to_email=user.email,
                    template_key="plan.changed",
                    context={
                        "email": user.email,
                        "plan_name": subscription.plan_type,
                        "previous_plan": previous_plan,
                        "manage_billing_url": _billing_url(config),
                    },
                    correlation_id=event_log.event_id,
                )
        if subscription:
            db.flush()
        return

    if event_type == "checkout.session.completed":
        session = data_object
        raw_metadata = session.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, Mapping) else {}
        metadata_type = metadata.get("type")
        if metadata_type == "base_subscription":
            if prepared_subscription_payload is None:
                raise RuntimeError("Prepared base subscription payload is missing")
            subscription_payload = prepared_subscription_payload
            normalized_metadata = normalize_base_checkout_metadata(metadata)
            attempt_id = normalized_metadata.get("base_checkout_attempt_id")
            if not attempt_id:
                raise ValueError("base_checkout_attempt_id_missing")
            attempt_owner_id = db.execute(
                select(models.BaseCheckoutAttempt.user_id).where(
                    models.BaseCheckoutAttempt.id == attempt_id
                )
            ).scalar_one_or_none()
            if attempt_owner_id is None:
                raise ValueError("base_checkout_attempt_not_found")
            user, locked_subscription = _lock_user_subscription(
                db,
                user_id=attempt_owner_id,
            )

            billing_interval = _extract_billing_interval(subscription_payload)
            price_id = _extract_price_id(subscription_payload)
            plan_type = _plan_type_from_price_id(
                price_id,
                config,
                stripe_mode=stripe_mode,
                interval=billing_interval,
            )
            if plan_type is None or billing_interval is None:
                raise ValueError("base_checkout_price_unrecognized")

            attempt, completed = complete_base_checkout_attempt(
                db,
                session=session,
                subscription_payload=subscription_payload,
                stripe_mode=stripe_mode,
                expected_plan=plan_type,
                expected_interval=billing_interval,
            )
            subscription = _upsert_subscription(
                db,
                user=user,
                stripe_customer_id=str(session.get("customer") or ""),
                stripe_subscription_id=str(session.get("subscription") or ""),
                status=str(subscription_payload.get("status") or ""),
                plan_type=attempt.target_plan,
                current_period_end=_parse_timestamp(subscription_payload.get("current_period_end")),
                cancel_at_period_end=subscription_payload.get("cancel_at_period_end"),
                billing_interval=attempt.billing_interval,
                stripe_mode=attempt.stripe_mode,
                locked_subscription=locked_subscription,
                subscription_fenced=True,
                allow_terminal_rollover=True,
            )
            if subscription is None:
                raise RuntimeError("Base checkout subscription could not be persisted")
            subscription.plan_state_event_created_at = _as_utc(event_log.event_created_at)
            db.flush()
            if not completed:
                logger.info(
                    "Base checkout attempt %s was already completed; skipping duplicate fulfillment",
                    attempt.id,
                )
            return

        if metadata_type == "credit_commitment":
            stripe_subscription_id = str(session.get("subscription") or "").strip()
            if not stripe_subscription_id:
                logger.warning(
                    "Commitment checkout completed without a subscription id: %s",
                    event_log.event_id,
                )
                return

            user = _resolve_user(
                db,
                obj=session,
                stripe_customer_id=session.get("customer"),
            )
            if user is None:
                logger.warning(
                    "Unable to resolve user for commitment checkout session %s", event_log.event_id
                )
                return

            if get_commitment_by_subscription_id(db, stripe_subscription_id=stripe_subscription_id):
                logger.info(
                    "Commitment already fulfilled for subscription %s, skipping",
                    stripe_subscription_id,
                )
                return

            if prepared_subscription_payload is None:
                raise RuntimeError("Prepared commitment subscription payload is missing")
            subscription_payload = prepared_subscription_payload
            user = db.execute(
                select(models.User).where(models.User.id == user.id).with_for_update()
            ).scalar_one()
            local_subscription = db.execute(
                select(models.Subscription)
                .where(models.Subscription.user_id == user.id)
                .with_for_update()
            ).scalar_one()
            validated = validate_commitment_checkout_fulfillment(
                session=session,
                subscription_payload=subscription_payload,
                stripe_mode=stripe_mode,
                config=config,
                user=user,
                local_subscription=local_subscription,
            )
            session = dict(session)
            session["metadata"] = {**dict(metadata), "tier": validated.tier.value}
            commitment, cycle, created = activate_commitment_from_checkout(
                db,
                user=user,
                session_payload=session,
                subscription_payload=subscription_payload,
                config=config,
                stripe_mode=stripe_mode,
            )
            if not created:
                logger.info(
                    "Commitment already active for subscription %s, skipping duplicate checkout fulfillment",
                    stripe_subscription_id,
                )
                return

            grant_commitment_cycle_credits(
                db,
                commitment=commitment,
                cycle=cycle,
                reason_kind="commitment_grant",
                stripe_reference=str(session.get("id") or ""),
            )

            _enqueue_email(
                db,
                user=user,
                to_email=user.email,
                template_key="commitment.activated",
                context={
                    "email": user.email,
                    "user_name": user.company_name or user.email,
                    "tier": commitment.tier,
                    "monthly_fee_usd": str(commitment.monthly_fee_usd),
                    "monthly_fee_currency": BILLING_CURRENCY_DISPLAY,
                    "cycle_end": commitment.current_cycle_end.isoformat()
                    if commitment.current_cycle_end
                    else None,
                    "manage_billing_url": _billing_url(config),
                },
                correlation_id=f"commitment-{stripe_subscription_id}",
            )
            db.flush()
            return

        if metadata_type is None:
            logger.info(
                "Skipping legacy checkout session without billing fulfillment metadata: %s",
                event_log.event_id,
            )
            return
        logger.info(
            "Skipping checkout session with unrelated fulfillment metadata: %s",
            event_log.event_id,
        )
        return

    if event_type not in {"invoice.paid", "invoice.payment_failed"}:
        raise ValueError(f"Unsupported Stripe event type: {event_type}")

    invoice = data_object
    stripe_customer_id = invoice.get("customer")
    user_id = _resolve_user_id(db, obj=invoice, stripe_customer_id=stripe_customer_id)
    if user_id is None:
        logger.warning("Unable to resolve user for invoice event %s", event_log.event_id)
        return

    # Serialize invoice fulfillment for this wallet before any invoice-keyed
    # payment or credit rows are checked or inserted. This closes the race
    # between distinct Stripe event deliveries for the same invoice.
    user, local_subscription = _lock_user_subscription(db, user_id=user_id)

    payment_status = "paid" if event_type == "invoice.paid" else "failed"
    _upsert_payment(db, user=user, invoice=invoice, status=payment_status)

    stripe_subscription_id = invoice.get("subscription")
    commitment = get_commitment_by_subscription_id(
        db,
        stripe_subscription_id=str(stripe_subscription_id or ""),
    )
    if commitment is not None:
        if commitment.stripe_mode not in (None, stripe_mode):
            raise ValueError("commitment_mode_mismatch")
        if event_type == "invoice.paid":
            if local_subscription is None:
                raise ValueError("commitment_subscription_missing")
            validate_commitment_renewal_invoice(
                invoice=invoice,
                stripe_mode=stripe_mode,
                config=config,
                commitment=commitment,
                local_subscription=local_subscription,
            )
            commitment.stripe_mode = stripe_mode
            cycle, created = renew_commitment_for_invoice(
                db,
                commitment=commitment,
                invoice_payload=invoice,
                config=config,
                stripe_mode=stripe_mode,
            )
            if created and cycle is not None:
                grant_commitment_cycle_credits(
                    db,
                    commitment=commitment,
                    cycle=cycle,
                    reason_kind="commitment_renewal",
                    stripe_reference=str(invoice.get("id") or ""),
                )
                _enqueue_email(
                    db,
                    user=user,
                    to_email=user.email,
                    template_key="commitment.renewed",
                    context={
                        "email": user.email,
                        "user_name": user.company_name or user.email,
                        "tier": commitment.tier,
                        "cycle_end": cycle.cycle_end.isoformat() if cycle.cycle_end else None,
                        "manage_billing_url": _billing_url(config),
                    },
                    correlation_id=event_log.event_id,
                )
        else:
            commitment.status = "past_due"

        _enqueue_email(
            db,
            user=user,
            to_email=user.email,
            template_key=event_type,
            context={
                "email": user.email,
                "amount_due": invoice.get("amount_due") or invoice.get("amount_paid"),
                "currency": invoice.get("currency"),
                "manage_billing_url": _billing_url(config),
                "plan_name": commitment.tier,
            },
            correlation_id=event_log.event_id,
        )
        db.flush()
        return

    allocation = None
    invoice_matches_subscription = bool(
        local_subscription
        and local_subscription.stripe_customer_id == stripe_customer_id
        and local_subscription.stripe_subscription_id == stripe_subscription_id
    )
    mode_matches = bool(
        local_subscription and local_subscription.stripe_mode in (None, stripe_mode)
    )
    if event_type == "invoice.paid" and invoice_matches_subscription and mode_matches:
        allocation = resolve_paid_invoice_plan_allocation(
            db,
            invoice,
            config=config,
            stripe_mode=stripe_mode,
        )
        stripe_invoice_id = str(invoice.get("id") or "").strip()
        if allocation is not None and stripe_invoice_id:
            granted = grant_paid_invoice_plan_credits(
                db,
                user_id=user.id,
                stripe_invoice_id=stripe_invoice_id,
                allocation=allocation,
            )
            if not granted:
                logger.info(
                    "Plan credits already granted for invoice %s, skipping duplicate grant",
                    stripe_invoice_id,
                )

    plan_type = (
        allocation.plan_type
        if allocation is not None
        else _plan_type_from_price_id(
            _extract_price_id(invoice),
            config,
            stripe_mode=stripe_mode,
            interval=_extract_billing_interval(invoice),
        )
    )
    _enqueue_email(
        db,
        user=user,
        to_email=user.email,
        template_key=event_type,
        context={
            "email": user.email,
            "amount_due": invoice.get("amount_due") or invoice.get("amount_paid"),
            "currency": invoice.get("currency"),
            "manage_billing_url": _billing_url(config),
            "plan_name": plan_type,
        },
        correlation_id=event_log.event_id,
    )

    db.flush()


def _prepare_event(event_id: str, claim_token: str) -> PreparedStripeEvent | None:
    read_db: Session = SessionLocal()
    try:
        config = _load_billing_config_snapshot(bind=read_db.get_bind())
        event = read_db.execute(
            select(models.StripeEventLog).where(
                models.StripeEventLog.event_id == event_id,
                models.StripeEventLog.processing_status == "processing",
                models.StripeEventLog.claim_token == claim_token,
            )
        ).scalar_one_or_none()
        if event is None:
            read_db.rollback()
            return None
        payload = event.payload if isinstance(event.payload, Mapping) else {}
        livemode = payload.get("livemode") if isinstance(payload, Mapping) else None
        if not isinstance(livemode, bool):
            raise ValueError("Stripe receipt mode is missing")
        stripe_mode = "live" if livemode else "test"
        api_key = _stripe_api_key_for_mode(config, stripe_mode)
        data = payload.get("data") if isinstance(payload, Mapping) else None
        data_object = data.get("object") if isinstance(data, Mapping) else None
        subscription_id = None
        if event.event_type == "checkout.session.completed" and isinstance(data_object, Mapping):
            metadata = data_object.get("metadata")
            if isinstance(metadata, Mapping) and metadata.get("type") in {
                "base_subscription",
                "credit_commitment",
            }:
                subscription_id = str(data_object.get("subscription") or "").strip() or None
        read_db.rollback()
    finally:
        read_db.close()
    subscription_payload = None
    if subscription_id is not None:
        subscription_payload = _stripe_object_to_dict(
            stripe.Subscription.retrieve(subscription_id, api_key=api_key)
        )
    return PreparedStripeEvent(
        config=config,
        stripe_mode=stripe_mode,
        subscription_payload=subscription_payload,
    )


async def process_event(
    event_id: str,
    *,
    now: datetime | None = None,
    max_attempts: int = STRIPE_EVENT_MAX_ATTEMPTS,
) -> None:
    claim_db: Session = SessionLocal()
    try:
        claim = claim_event(claim_db, event_id, now=now)
    except Exception as exc:
        claim_db.rollback()
        logger.error(
            "Failed to claim Stripe event: event_id=%s error_class=%s",
            event_id,
            type(exc).__name__,
        )
        return
    finally:
        claim_db.close()
    if claim is None:
        return
    try:
        prepared = _prepare_event(event_id, claim.claim_token)
    except Exception as exc:
        failure_db: Session = SessionLocal()
        try:
            fail_event(
                failure_db,
                event_id,
                claim.claim_token,
                exc,
                now=now,
                max_attempts=max_attempts,
            )
        finally:
            failure_db.close()
        return
    if prepared is None:
        return

    db: Session = SessionLocal()
    try:
        # The durable claim token is rechecked before handler execution and terminal updates.
        # Top-up financial idempotency remains enforced by the order row and unique constraints.
        event_log = lock_claimed_event(
            db,
            event_id,
            claim.claim_token,
            now=now,
        )
        if event_log is None:
            db.rollback()
            return
        await handle_event(
            db,
            event_log,
            config=prepared.config,
            stripe_mode=prepared.stripe_mode,
            prepared_subscription_payload=prepared.subscription_payload,
        )
        if not complete_event(db, event_id, claim.claim_token, now=now):
            logger.info("Stripe event completion ignored for stale claim: %s", event_id)
            return
    except Exception as exc:
        logger.warning(
            "Stripe event processing failed: event_id=%s error_class=%s",
            event_id,
            type(exc).__name__,
        )
        db.rollback()
        db.close()
        failure_db: Session = SessionLocal()
        try:
            disposition = fail_event(
                failure_db,
                event_id,
                claim.claim_token,
                exc,
                now=now,
                max_attempts=max_attempts,
            )
            if disposition is None:
                logger.info("Stripe event failure ignored for stale claim: %s", event_id)
        except Exception as failure_exc:
            failure_db.rollback()
            logger.error(
                "Failed to persist Stripe event failure state: event_id=%s error_class=%s",
                event_id,
                type(failure_exc).__name__,
            )
        finally:
            failure_db.close()
        return
    finally:
        if db.is_active:
            db.close()


async def process_due_events(
    *,
    batch_size: int = STRIPE_EVENT_DUE_BATCH_SIZE,
) -> int:
    db: Session = SessionLocal()
    try:
        event_ids = list_due_event_ids(db, limit=batch_size)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to poll due Stripe events: error_class=%s", type(exc).__name__)
        return 0
    finally:
        db.close()

    for event_id in event_ids:
        try:
            await process_event(event_id)
        except Exception as exc:
            logger.error(
                "Unexpected Stripe event worker failure: event_id=%s error_class=%s",
                event_id,
                type(exc).__name__,
            )
    return len(event_ids)


async def process_stripe_command(command_id: int) -> None:
    claim_db: Session = SessionLocal()
    try:
        claim = claim_command(claim_db, command_id)
    finally:
        claim_db.close()
    if claim is None:
        return
    try:
        config = _load_billing_config_snapshot()
        api_key = _stripe_api_key_for_mode(config, claim.stripe_mode)
        if claim.command_type != "subscription_item_usage_record":
            raise ValueError("Unsupported Stripe command type")
        subscription_item_id = claim.payload.get("subscription_item_id")
        quantity = claim.payload.get("quantity")
        timestamp = claim.payload.get("timestamp")
        action = claim.payload.get("action")
        if not isinstance(subscription_item_id, str) or not subscription_item_id:
            raise ValueError("Invalid Stripe subscription item id")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
            raise ValueError("Invalid Stripe usage quantity")
        if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp <= 0:
            raise ValueError("Invalid Stripe usage timestamp")
        if action != "set":
            raise ValueError("Invalid Stripe usage action")
        await asyncio.to_thread(
            stripe.SubscriptionItem.create_usage_record,
            subscription_item_id,
            quantity=quantity,
            timestamp=timestamp,
            action=action,
            idempotency_key=claim.idempotency_key,
            api_key=api_key,
        )
        complete_db: Session = SessionLocal()
        try:
            complete_command(complete_db, claim)
        finally:
            complete_db.close()
    except Exception as exc:
        failure_db: Session = SessionLocal()
        try:
            fail_command(failure_db, claim, exc)
        finally:
            failure_db.close()


async def process_due_stripe_commands(
    *,
    batch_size: int = STRIPE_COMMAND_BATCH_SIZE,
) -> int:
    db: Session = SessionLocal()
    try:
        command_ids = list_due_command_ids(db, limit=batch_size)
    except Exception as exc:
        db.rollback()
        logger.error("Failed to poll Stripe commands: error_class=%s", type(exc).__name__)
        return 0
    finally:
        db.close()
    for command_id in command_ids:
        try:
            await process_stripe_command(command_id)
        except Exception as exc:
            logger.error(
                "Unexpected Stripe command failure: command_id=%s error_class=%s",
                command_id,
                type(exc).__name__,
            )
    return len(command_ids)


def _decode_event_id(value: object) -> str | None:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return None
    if isinstance(value, str):
        return value
    return None


async def worker_loop() -> None:
    redis_client = get_async_redis_client()
    logger.info("Stripe webhook worker listening on queue %s", STRIPE_WEBHOOK_QUEUE_NAME)
    try:
        await process_due_events()
        await process_due_stripe_commands()
        while True:
            try:
                result = await redis_client.blpop(STRIPE_WEBHOOK_QUEUE_NAME, timeout=5)
            except Exception as exc:
                logger.error(
                    "Stripe webhook Redis wakeup failed: error_class=%s",
                    type(exc).__name__,
                )
                await asyncio.sleep(1)
                await process_due_events()
                await process_due_stripe_commands()
                continue
            if result:
                event_id = _decode_event_id(result[1])
                if event_id:
                    await redis_client.delete(f"billing:webhook_wakeup:{event_id}")
                    await process_event(event_id)
            await process_due_events()
            await process_due_stripe_commands()
    finally:
        await redis_client.aclose()


if __name__ == "__main__":
    configure_logging()
    init_tracing("billing-worker")
    asyncio.run(worker_loop())
