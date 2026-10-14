from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
import re
from typing import Callable, Mapping
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import models
from observability import stripe_event_outcomes_total

STRIPE_EVENT_LEASE_DURATION = timedelta(minutes=5)
STRIPE_EVENT_MAX_ATTEMPTS = 5
STRIPE_EVENT_RETRY_BASE_DELAY = timedelta(seconds=30)
STRIPE_EVENT_RETRY_MAX_DELAY = timedelta(hours=1)
STRIPE_EVENT_DUE_BATCH_SIZE = 50
STRIPE_EVENT_DUE_BATCH_MAX = 100
_TERMINAL_STATUSES = frozenset({"processed", "dead_letter"})
_ERROR_CLASS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,127}$")
_SUPPORTED_EVENT_TYPES = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "invoice.paid",
        "invoice.payment_failed",
    }
)
logger = logging.getLogger(__name__)


class _ReceiptObject(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(min_length=1, max_length=255)
    object: str = Field(min_length=1, max_length=128)


class _ReceiptData(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    object: dict[str, object]


class _ReceiptEnvelope(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: str = Field(min_length=1, max_length=255, pattern=r"^evt_[A-Za-z0-9_]+$")
    type: str = Field(min_length=1, max_length=255)
    created: StrictInt = Field(gt=0, le=32503680000)
    livemode: StrictBool
    data: _ReceiptData


@dataclass(frozen=True)
class StripeEventClaim:
    event_id: str
    claim_token: str
    attempt_count: int


@dataclass(frozen=True)
class StripeEventFailureDisposition:
    status: str
    next_attempt_at: datetime | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_string(
    value: object,
    *,
    field_name: str,
    max_length: int = 255,
) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ValueError(f"invalid_{field_name}")
    return value


def _copy_string(source: dict[str, object], target: dict[str, object], key: str) -> None:
    if key not in source or source[key] is None:
        return
    target[key] = _required_string(source[key], field_name=key)


def _copy_integer(source: dict[str, object], target: dict[str, object], key: str) -> None:
    if key not in source or source[key] is None:
        return
    value = source[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid_{key}")
    target[key] = value


def _copy_boolean(source: dict[str, object], target: dict[str, object], key: str) -> None:
    if key not in source or source[key] is None:
        return
    value = source[key]
    if not isinstance(value, bool):
        raise ValueError(f"invalid_{key}")
    target[key] = value


def _mapping(value: object, *, field_name: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"invalid_{field_name}")
    return dict(value)


def _normalize_metadata(raw: object, *, event_type: str) -> dict[str, object]:
    if raw is None:
        return {}
    metadata = _mapping(raw, field_name="metadata")
    metadata_type = metadata.get("type")
    normalized: dict[str, object] = {}
    allowed = {"user_id", "plan", "billing_interval"}
    if event_type == "checkout.session.completed" and metadata_type == "base_subscription":
        normalized["type"] = "base_subscription"
        allowed = {
            "base_checkout_attempt_id",
            "user_id",
            "plan",
            "billing_interval",
        }
    elif event_type == "checkout.session.completed" and metadata_type == "credit_commitment":
        normalized["type"] = "credit_commitment"
        allowed = {"user_id", "tier"}
    for key in allowed:
        _copy_string(metadata, normalized, key)
    return normalized


def _normalize_price(raw: object) -> dict[str, object]:
    price = _mapping(raw, field_name="price")
    normalized: dict[str, object] = {}
    _copy_string(price, normalized, "id")
    _copy_string(price, normalized, "interval")
    recurring = price.get("recurring")
    if recurring is not None:
        recurring_mapping = _mapping(recurring, field_name="recurring")
        normalized_recurring: dict[str, object] = {}
        _copy_string(recurring_mapping, normalized_recurring, "interval")
        _copy_string(recurring_mapping, normalized_recurring, "usage_type")
        normalized["recurring"] = normalized_recurring
    return normalized


def _normalize_items(raw: object) -> dict[str, object]:
    items = _mapping(raw, field_name="items")
    data = items.get("data")
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError("invalid_items_data")
    normalized_items: list[dict[str, object]] = []
    for item in data:
        item_mapping = _mapping(item, field_name="item")
        normalized_item: dict[str, object] = {}
        _copy_string(item_mapping, normalized_item, "id")
        _copy_integer(item_mapping, normalized_item, "quantity")
        for key in ("price", "plan"):
            if item_mapping.get(key) is not None:
                normalized_item[key] = _normalize_price(item_mapping[key])
        normalized_items.append(normalized_item)
    return {"data": normalized_items}


def _normalize_lines(raw: object) -> dict[str, object]:
    lines = _mapping(raw, field_name="lines")
    data = lines.get("data")
    if not isinstance(data, list) or len(data) > 100:
        raise ValueError("invalid_lines_data")
    normalized_lines: list[dict[str, object]] = []
    for line in data:
        line_mapping = _mapping(line, field_name="line")
        normalized_line: dict[str, object] = {}
        _copy_integer(line_mapping, normalized_line, "quantity")
        _copy_integer(line_mapping, normalized_line, "amount")
        for key in ("price", "plan"):
            if line_mapping.get(key) is not None:
                normalized_line[key] = _normalize_price(line_mapping[key])
        period = line_mapping.get("period")
        if period is not None:
            period_mapping = _mapping(period, field_name="period")
            normalized_period: dict[str, object] = {}
            _copy_integer(period_mapping, normalized_period, "start")
            _copy_integer(period_mapping, normalized_period, "end")
            normalized_line["period"] = normalized_period
        normalized_lines.append(normalized_line)
    return {"data": normalized_lines}


def normalize_stripe_event_receipt(
    raw_event: object,
    *,
    stripe_mode: str,
) -> dict[str, object]:
    event = _mapping(raw_event, field_name="event")
    data = _mapping(event.get("data"), field_name="data")
    raw_object = _mapping(data.get("object"), field_name="data_object")
    object_identity = _ReceiptObject.model_validate(
        {
            "id": raw_object.get("id"),
            "object": raw_object.get("object"),
        }
    ).model_dump(exclude_none=True)
    envelope = _ReceiptEnvelope.model_validate(
        {
            "id": event.get("id"),
            "type": event.get("type"),
            "created": event.get("created"),
            "livemode": event.get("livemode"),
            "data": {"object": object_identity},
        }
    )
    expected_livemode = str(stripe_mode).strip().lower() == "live"
    if envelope.livemode is not expected_livemode:
        raise ValueError("stripe_mode_mismatch")
    event_type = envelope.type
    object_type = object_identity["object"]
    expected_object_type = {
        "checkout.session.completed": "checkout.session",
        "customer.subscription.created": "subscription",
        "customer.subscription.updated": "subscription",
        "customer.subscription.deleted": "subscription",
        "invoice.paid": "invoice",
        "invoice.payment_failed": "invoice",
    }.get(event_type)
    if expected_object_type is not None and object_type != expected_object_type:
        raise ValueError("stripe_event_object_mismatch")
    if event_type not in _SUPPORTED_EVENT_TYPES:
        return envelope.model_dump()

    normalized_object = dict(object_identity)
    if event_type.startswith("customer.subscription."):
        for key in ("customer", "status", "schedule"):
            _copy_string(raw_object, normalized_object, key)
        for key in ("current_period_start", "current_period_end"):
            _copy_integer(raw_object, normalized_object, key)
        _copy_boolean(raw_object, normalized_object, "cancel_at_period_end")
        normalized_object["metadata"] = _normalize_metadata(
            raw_object.get("metadata"),
            event_type=event_type,
        )
        if raw_object.get("items") is not None:
            normalized_object["items"] = _normalize_items(raw_object["items"])
    elif event_type == "checkout.session.completed":
        for key in (
            "customer",
            "client_reference_id",
            "subscription",
            "mode",
            "payment_status",
            "currency",
            "status",
        ):
            _copy_string(raw_object, normalized_object, key)
        _copy_integer(raw_object, normalized_object, "amount_total")
        normalized_object["metadata"] = _normalize_metadata(
            raw_object.get("metadata"),
            event_type=event_type,
        )
    else:
        for key in ("customer", "subscription", "currency", "status", "billing_reason"):
            _copy_string(raw_object, normalized_object, key)
        for key in (
            "created",
            "amount_paid",
            "amount_due",
            "period_start",
            "period_end",
        ):
            _copy_integer(raw_object, normalized_object, key)
        _copy_boolean(raw_object, normalized_object, "paid")
        normalized_object["metadata"] = _normalize_metadata(
            raw_object.get("metadata"),
            event_type=event_type,
        )
        if raw_object.get("lines") is not None:
            normalized_object["lines"] = _normalize_lines(raw_object["lines"])
    receipt = envelope.model_dump()
    receipt["data"] = {"object": normalized_object}
    return receipt


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _lease_is_stale(
    claimed_at: datetime | None,
    *,
    now: datetime,
    lease_duration: timedelta,
) -> bool:
    aware_claimed_at = _as_aware(claimed_at)
    return aware_claimed_at is None or aware_claimed_at <= now - lease_duration


def should_wake_event(
    event: models.StripeEventLog,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = STRIPE_EVENT_LEASE_DURATION,
) -> bool:
    current_time = now or utc_now()
    if event.processing_status == "pending":
        return True
    if event.processing_status == "failed":
        next_attempt_at = _as_aware(event.next_attempt_at)
        return next_attempt_at is not None and next_attempt_at <= current_time
    return False


def claim_event(
    db: Session,
    event_id: str,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = STRIPE_EVENT_LEASE_DURATION,
    token_factory: Callable[[], str] | None = None,
) -> StripeEventClaim | None:
    current_time = now or utc_now()
    event = db.execute(
        select(models.StripeEventLog)
        .where(models.StripeEventLog.event_id == event_id)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if event is None or event.processing_status in _TERMINAL_STATUSES:
        db.rollback()
        return None
    if event.processing_status == "processing" and not _lease_is_stale(
        event.claimed_at,
        now=current_time,
        lease_duration=lease_duration,
    ):
        db.rollback()
        return None
    if event.processing_status == "failed":
        next_attempt_at = _as_aware(event.next_attempt_at)
        if next_attempt_at is not None and next_attempt_at > current_time:
            db.rollback()
            return None
    if event.processing_status not in {"pending", "failed", "processing"}:
        db.rollback()
        return None

    claim_token = (token_factory or (lambda: uuid4().hex))()
    event.processing_status = "processing"
    event.claim_token = claim_token
    event.claimed_at = current_time
    event.next_attempt_at = None
    event.attempt_count = int(event.attempt_count or 0) + 1
    event.last_error = None
    claimed_event_id = event.event_id
    attempt_count = event.attempt_count
    db.commit()
    stripe_event_outcomes_total.labels(outcome="claimed").inc()
    return StripeEventClaim(
        event_id=claimed_event_id,
        claim_token=claim_token,
        attempt_count=attempt_count,
    )


def lock_claimed_event(
    db: Session,
    event_id: str,
    claim_token: str,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = STRIPE_EVENT_LEASE_DURATION,
) -> models.StripeEventLog | None:
    current_time = now or utc_now()
    event = db.execute(
        select(models.StripeEventLog)
        .where(
            models.StripeEventLog.event_id == event_id,
            models.StripeEventLog.processing_status == "processing",
            models.StripeEventLog.claim_token == claim_token,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if event is None or _lease_is_stale(
        event.claimed_at,
        now=current_time,
        lease_duration=lease_duration,
    ):
        db.rollback()
        return None
    return event


def complete_event(
    db: Session,
    event_id: str,
    claim_token: str,
    *,
    now: datetime | None = None,
) -> bool:
    result = db.execute(
        update(models.StripeEventLog)
        .where(
            models.StripeEventLog.event_id == event_id,
            models.StripeEventLog.processing_status == "processing",
            models.StripeEventLog.claim_token == claim_token,
        )
        .values(
            processing_status="processed",
            processed_at=now or utc_now(),
            last_error=None,
            claim_token=None,
            claimed_at=None,
            next_attempt_at=None,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        return False
    db.commit()
    stripe_event_outcomes_total.labels(outcome="processed").inc()
    return True


def _sanitized_error(error: BaseException) -> tuple[str, str]:
    error_class = type(error).__name__
    if not _ERROR_CLASS_PATTERN.fullmatch(error_class):
        error_class = "ProcessingError"
    if isinstance(error, SQLAlchemyError):
        code = "database_error"
        message = "Stripe event database operation failed."
    elif isinstance(error, (TypeError, ValueError)):
        code = "invalid_event"
        message = "Stripe event validation failed."
    else:
        code = "processing_error"
        message = "Stripe event processing failed."
    return (
        json.dumps(
            {"class": error_class, "code": code, "message": message},
            separators=(",", ":"),
            sort_keys=True,
        ),
        code,
    )


def fail_event(
    db: Session,
    event_id: str,
    claim_token: str,
    error: BaseException,
    *,
    now: datetime | None = None,
    max_attempts: int = STRIPE_EVENT_MAX_ATTEMPTS,
    retry_base_delay: timedelta = STRIPE_EVENT_RETRY_BASE_DELAY,
    retry_max_delay: timedelta = STRIPE_EVENT_RETRY_MAX_DELAY,
) -> StripeEventFailureDisposition | None:
    current_time = now or utc_now()
    event = db.execute(
        select(models.StripeEventLog)
        .where(
            models.StripeEventLog.event_id == event_id,
            models.StripeEventLog.processing_status == "processing",
            models.StripeEventLog.claim_token == claim_token,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if event is None:
        db.rollback()
        return None

    sanitized_error, error_code = _sanitized_error(error)
    event.last_error = sanitized_error
    event.claim_token = None
    event.claimed_at = None
    if event.attempt_count >= max_attempts:
        event.processing_status = "dead_letter"
        event.next_attempt_at = None
        event.dead_lettered_at = current_time
        disposition = StripeEventFailureDisposition("dead_letter", None)
        stripe_event_outcomes_total.labels(outcome="dead_letter").inc()
        logger.warning(
            "Stripe event dead-lettered: event_id=%s attempt_count=%s error_code=%s",
            event.event_id,
            event.attempt_count,
            error_code,
        )
    else:
        exponent = min(max(event.attempt_count - 1, 0), 20)
        delay_seconds = min(
            retry_base_delay.total_seconds() * (2**exponent),
            retry_max_delay.total_seconds(),
        )
        next_attempt_at = current_time + timedelta(seconds=delay_seconds)
        event.processing_status = "failed"
        event.next_attempt_at = next_attempt_at
        stripe_event_outcomes_total.labels(outcome="retry_scheduled").inc()
        disposition = StripeEventFailureDisposition("failed", next_attempt_at)
    db.commit()
    return disposition


def list_due_event_ids(
    db: Session,
    *,
    now: datetime | None = None,
    lease_duration: timedelta = STRIPE_EVENT_LEASE_DURATION,
    limit: int = STRIPE_EVENT_DUE_BATCH_SIZE,
) -> list[str]:
    current_time = now or utc_now()
    batch_size = max(1, min(limit, STRIPE_EVENT_DUE_BATCH_MAX))
    stale_before = current_time - lease_duration
    due = or_(
        models.StripeEventLog.processing_status == "pending",
        and_(
            models.StripeEventLog.processing_status == "failed",
            or_(
                models.StripeEventLog.next_attempt_at.is_(None),
                models.StripeEventLog.next_attempt_at <= current_time,
            ),
        ),
        and_(
            models.StripeEventLog.processing_status == "processing",
            or_(
                models.StripeEventLog.claimed_at.is_(None),
                models.StripeEventLog.claimed_at <= stale_before,
            ),
        ),
    )
    event_ids = list(
        db.execute(
            select(models.StripeEventLog.event_id)
            .where(due)
            .order_by(models.StripeEventLog.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    db.commit()
    return event_ids
