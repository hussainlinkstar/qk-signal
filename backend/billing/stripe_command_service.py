from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Mapping
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

import models
from observability import stripe_command_events_total

logger = logging.getLogger(__name__)

STRIPE_COMMAND_LEASE_DURATION = timedelta(minutes=5)
STRIPE_COMMAND_MAX_ATTEMPTS = 5
STRIPE_COMMAND_BATCH_SIZE = 20
STRIPE_COMMAND_RETRY_BASE_SECONDS = 30
STRIPE_COMMAND_RETRY_MAX_SECONDS = 3600


@dataclass(frozen=True)
class StripeCommandClaim:
    command_id: int
    claim_token: str
    idempotency_key: str
    command_type: str
    stripe_mode: str
    payload: Mapping[str, object]
    attempt_count: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def enqueue_usage_record_command(
    db: Session,
    *,
    commitment_id: int,
    cycle_id: int,
    subscription_item_id: str,
    stripe_mode: str,
    quantity: int,
    timestamp: int,
) -> models.StripeCommandOutbox:
    if stripe_mode not in {"test", "live"}:
        raise ValueError("Invalid Stripe command mode")
    idempotency_key = f"commitment-overage:{commitment_id}:{cycle_id}"
    existing = db.execute(
        select(models.StripeCommandOutbox).where(
            models.StripeCommandOutbox.idempotency_key == idempotency_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    command = models.StripeCommandOutbox(
        idempotency_key=idempotency_key,
        command_type="subscription_item_usage_record",
        stripe_mode=stripe_mode,
        payload={
            "subscription_item_id": subscription_item_id,
            "quantity": quantity,
            "timestamp": timestamp,
            "action": "set",
        },
        status="pending",
    )
    db.add(command)
    db.flush()
    return command


def list_due_command_ids(
    db: Session,
    *,
    now: datetime | None = None,
    limit: int = STRIPE_COMMAND_BATCH_SIZE,
) -> list[int]:
    current_time = now or utc_now()
    stale_before = current_time - STRIPE_COMMAND_LEASE_DURATION
    due = or_(
        models.StripeCommandOutbox.status == "pending",
        and_(
            models.StripeCommandOutbox.status == "failed",
            models.StripeCommandOutbox.next_attempt_at <= current_time,
        ),
        and_(
            models.StripeCommandOutbox.status == "processing",
            models.StripeCommandOutbox.claimed_at <= stale_before,
        ),
    )
    command_ids = list(
        db.execute(
            select(models.StripeCommandOutbox.id)
            .where(due)
            .order_by(models.StripeCommandOutbox.id)
            .limit(max(1, min(limit, 100)))
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )
    db.commit()
    return command_ids


def claim_command(
    db: Session,
    command_id: int,
    *,
    now: datetime | None = None,
) -> StripeCommandClaim | None:
    current_time = now or utc_now()
    stale_before = current_time - STRIPE_COMMAND_LEASE_DURATION
    command = db.execute(
        select(models.StripeCommandOutbox)
        .where(models.StripeCommandOutbox.id == command_id)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if command is None or command.status in {"succeeded", "dead_letter"}:
        db.rollback()
        return None
    claimed_at = _aware(command.claimed_at)
    if command.status == "processing" and (claimed_at is None or claimed_at > stale_before):
        db.rollback()
        return None
    next_attempt_at = _aware(command.next_attempt_at)
    if command.status == "failed" and (next_attempt_at is None or next_attempt_at > current_time):
        db.rollback()
        return None
    claim_token = uuid4().hex
    command.status = "processing"
    command.claim_token = claim_token
    command.claimed_at = current_time
    command.next_attempt_at = None
    command.processed_at = None
    command.dead_lettered_at = None
    command.attempt_count = int(command.attempt_count or 0) + 1
    command.last_error = None
    payload = dict(command.payload or {})
    claim = StripeCommandClaim(
        command_id=command.id,
        claim_token=claim_token,
        idempotency_key=command.idempotency_key,
        command_type=command.command_type,
        stripe_mode=command.stripe_mode,
        payload=payload,
        attempt_count=command.attempt_count,
    )
    db.commit()
    stripe_command_events_total.labels(
        event="claimed",
        command_type=claim.command_type,
        stripe_mode=claim.stripe_mode,
        error_code="none",
    ).inc()
    return claim


def complete_command(
    db: Session,
    claim: StripeCommandClaim,
    *,
    now: datetime | None = None,
) -> bool:
    result = db.execute(
        update(models.StripeCommandOutbox)
        .where(
            models.StripeCommandOutbox.id == claim.command_id,
            models.StripeCommandOutbox.status == "processing",
            models.StripeCommandOutbox.claim_token == claim.claim_token,
        )
        .values(
            status="succeeded",
            processed_at=now or utc_now(),
            claim_token=None,
            claimed_at=None,
            next_attempt_at=None,
            last_error=None,
            dead_lettered_at=None,
        )
    )
    if result.rowcount != 1:
        db.rollback()
        stripe_command_events_total.labels(
            event="stale_rejected",
            command_type=claim.command_type,
            stripe_mode=claim.stripe_mode,
            error_code="stale_claim",
        ).inc()
        return False
    db.commit()
    stripe_command_events_total.labels(
        event="succeeded",
        command_type=claim.command_type,
        stripe_mode=claim.stripe_mode,
        error_code="none",
    ).inc()
    return True


def fail_command(
    db: Session,
    claim: StripeCommandClaim,
    error: BaseException,
    *,
    now: datetime | None = None,
    max_attempts: int = STRIPE_COMMAND_MAX_ATTEMPTS,
) -> bool:
    current_time = now or utc_now()
    command = db.execute(
        select(models.StripeCommandOutbox)
        .where(
            models.StripeCommandOutbox.id == claim.command_id,
            models.StripeCommandOutbox.status == "processing",
            models.StripeCommandOutbox.claim_token == claim.claim_token,
        )
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    if command is None:
        db.rollback()
        return False
    command.last_error = json.dumps(
        {
            "class": type(error).__name__,
            "code": "stripe_command_failed",
            "message": "Stripe command execution failed.",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    command.claim_token = None
    command.claimed_at = None
    if command.attempt_count >= max_attempts:
        command.status = "dead_letter"
        command.next_attempt_at = None
        command.dead_lettered_at = current_time
        stripe_command_events_total.labels(
            event="dead_letter",
            command_type=command.command_type,
            stripe_mode=command.stripe_mode,
            error_code="stripe_command_failed",
        ).inc()
        logger.warning(
            "Stripe command dead-lettered: command_id=%s command_type=%s stripe_mode=%s "
            "attempt_count=%s error_code=%s",
            command.id,
            command.command_type,
            command.stripe_mode,
            command.attempt_count,
            "stripe_command_failed",
        )
    else:
        delay = min(
            STRIPE_COMMAND_RETRY_BASE_SECONDS * (2 ** max(command.attempt_count - 1, 0)),
            STRIPE_COMMAND_RETRY_MAX_SECONDS,
        )
        command.status = "failed"
        command.next_attempt_at = current_time + timedelta(seconds=delay)
        stripe_command_events_total.labels(
            event="retry_scheduled",
            command_type=command.command_type,
            stripe_mode=command.stripe_mode,
            error_code="stripe_command_failed",
        ).inc()
    db.commit()
    return True
