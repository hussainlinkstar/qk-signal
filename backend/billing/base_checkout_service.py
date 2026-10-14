from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import models


BASE_CHECKOUT_ACTIVE_STATUSES = frozenset({"pending", "customer_created", "session_created"})
BASE_CHECKOUT_TERMINAL_STATUSES = frozenset({"completed", "expired", "failed", "canceled"})
BASE_CHECKOUT_ATTEMPT_TTL = timedelta(hours=24)
BASE_CHECKOUT_METADATA_KEYS = frozenset(
    {
        "type",
        "base_checkout_attempt_id",
        "user_id",
        "plan",
        "billing_interval",
    }
)


class BaseCheckoutError(RuntimeError):
    error_code = "base_checkout_error"


class BaseCheckoutConflictError(BaseCheckoutError):
    error_code = "base_checkout_attempt_conflict"


class BaseCheckoutValidationError(BaseCheckoutError):
    error_code = "base_checkout_validation_failed"


@dataclass(frozen=True)
class BaseCheckoutResolution:
    attempt: models.BaseCheckoutAttempt
    created: bool


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def stripe_customer_idempotency_key(*, user_id: int, stripe_mode: str) -> str:
    if stripe_mode not in {"test", "live"}:
        raise ValueError("Unsupported Stripe mode")
    return f"stripe-customer:{user_id}:{stripe_mode}"


def base_checkout_idempotency_key(attempt_id: str) -> str:
    return f"base-checkout:{attempt_id}"


def base_checkout_metadata(attempt: models.BaseCheckoutAttempt) -> dict[str, str]:
    return {
        "type": "base_subscription",
        "base_checkout_attempt_id": attempt.id,
        "user_id": str(attempt.user_id),
        "plan": attempt.target_plan,
        "billing_interval": attempt.billing_interval,
    }


def normalize_base_checkout_metadata(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        return MappingProxyType({})
    normalized = {
        key: str(raw_value).strip()
        for key, raw_value in value.items()
        if key in BASE_CHECKOUT_METADATA_KEYS and isinstance(raw_value, (str, int))
    }
    return MappingProxyType(normalized)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active_attempt_query(*, user_id: int, stripe_mode: str):
    return (
        select(models.BaseCheckoutAttempt)
        .where(
            models.BaseCheckoutAttempt.user_id == user_id,
            models.BaseCheckoutAttempt.stripe_mode == stripe_mode,
            models.BaseCheckoutAttempt.status.in_(BASE_CHECKOUT_ACTIVE_STATUSES),
        )
        .execution_options(populate_existing=True)
        .with_for_update()
    )


def _payload_matches(
    attempt: models.BaseCheckoutAttempt,
    *,
    target_plan: str,
    billing_interval: str,
) -> bool:
    return attempt.target_plan == target_plan and attempt.billing_interval == billing_interval


def resolve_base_checkout_attempt(
    db: Session,
    *,
    user_id: int,
    stripe_mode: str,
    target_plan: str,
    billing_interval: str,
    now: datetime | None = None,
) -> BaseCheckoutResolution:
    current_time = now or utc_now()
    db.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one()
    db.execute(
        select(models.Subscription)
        .where(models.Subscription.user_id == user_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one_or_none()
    existing = db.execute(
        _active_attempt_query(user_id=user_id, stripe_mode=stripe_mode)
    ).scalar_one_or_none()

    if existing is not None:
        if not _payload_matches(
            existing,
            target_plan=target_plan,
            billing_interval=billing_interval,
        ):
            raise BaseCheckoutConflictError("Another subscription checkout is already in progress.")
        return BaseCheckoutResolution(attempt=existing, created=False)

    attempt = models.BaseCheckoutAttempt(
        id=f"bca_{uuid4().hex}",
        user_id=user_id,
        stripe_mode=stripe_mode,
        target_plan=target_plan,
        billing_interval=billing_interval,
        status="pending",
        expires_at=current_time + BASE_CHECKOUT_ATTEMPT_TTL,
        updated_at=current_time,
    )
    db.add(attempt)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(attempt)
    return BaseCheckoutResolution(attempt=attempt, created=True)


def lock_base_checkout_attempt(
    db: Session,
    *,
    attempt_id: str,
) -> models.BaseCheckoutAttempt:
    return db.execute(
        select(models.BaseCheckoutAttempt)
        .where(models.BaseCheckoutAttempt.id == attempt_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one()


def cancel_untouched_base_checkout_attempt(
    db: Session,
    *,
    attempt_id: str,
) -> bool:
    attempt = lock_base_checkout_attempt(db, attempt_id=attempt_id)
    if (
        attempt.status != "pending"
        or attempt.stripe_customer_id is not None
        or attempt.stripe_session_id is not None
    ):
        return False
    attempt.status = "canceled"
    attempt.updated_at = utc_now()
    db.commit()
    db.refresh(attempt)
    return True


def link_base_checkout_customer(
    db: Session,
    *,
    attempt_id: str,
    stripe_customer_id: str,
    allow_replacement: bool = False,
    commit: bool = True,
) -> models.BaseCheckoutAttempt:
    attempt = lock_base_checkout_attempt(db, attempt_id=attempt_id)
    if attempt.status not in BASE_CHECKOUT_ACTIVE_STATUSES:
        raise BaseCheckoutConflictError("Subscription checkout is no longer active.")
    if attempt.stripe_customer_id not in {None, stripe_customer_id}:
        if not allow_replacement or attempt.status != "customer_created":
            raise BaseCheckoutValidationError("Stripe customer does not match checkout attempt.")
        attempt.stripe_customer_id = stripe_customer_id
    if attempt.status == "pending":
        attempt.stripe_customer_id = stripe_customer_id
        attempt.status = "customer_created"
    if db.is_modified(attempt):
        attempt.updated_at = utc_now()
        if commit:
            db.commit()
            db.refresh(attempt)
        else:
            db.flush()
    return attempt


def link_base_checkout_session(
    db: Session,
    *,
    attempt_id: str,
    stripe_customer_id: str,
    stripe_session_id: str,
    commit: bool = True,
) -> models.BaseCheckoutAttempt:
    attempt = lock_base_checkout_attempt(db, attempt_id=attempt_id)
    if attempt.status not in BASE_CHECKOUT_ACTIVE_STATUSES:
        raise BaseCheckoutConflictError("Subscription checkout is no longer active.")
    if attempt.stripe_customer_id != stripe_customer_id:
        raise BaseCheckoutValidationError("Stripe customer does not match checkout attempt.")
    if attempt.stripe_session_id not in {None, stripe_session_id}:
        raise BaseCheckoutValidationError("Stripe session does not match checkout attempt.")
    if attempt.status in {"pending", "customer_created"}:
        attempt.stripe_session_id = stripe_session_id
        attempt.status = "session_created"
        attempt.updated_at = utc_now()
        if commit:
            db.commit()
            db.refresh(attempt)
        else:
            db.flush()
    return attempt


def expire_base_checkout_attempt(
    db: Session,
    *,
    attempt_id: str,
    stripe_session_id: str,
) -> models.BaseCheckoutAttempt:
    attempt = lock_base_checkout_attempt(db, attempt_id=attempt_id)
    if attempt.status not in BASE_CHECKOUT_ACTIVE_STATUSES:
        raise BaseCheckoutConflictError("Subscription checkout is no longer active.")
    if attempt.stripe_session_id not in {None, stripe_session_id}:
        raise BaseCheckoutValidationError("Stripe session does not match checkout attempt.")
    attempt.stripe_session_id = stripe_session_id
    attempt.status = "expired"
    attempt.updated_at = utc_now()
    db.commit()
    db.refresh(attempt)
    return attempt


def stripe_object_value(value: object, key: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(key)
    return getattr(value, key, None)


def validate_base_checkout_session(
    session: object,
    *,
    attempt: models.BaseCheckoutAttempt,
    require_open: bool,
) -> tuple[str, str | None, str]:
    session_id = stripe_object_value(session, "id")
    customer_id = stripe_object_value(session, "customer")
    raw_metadata = stripe_object_value(session, "metadata")
    metadata = normalize_base_checkout_metadata(raw_metadata)
    expected_metadata = base_checkout_metadata(attempt)
    livemode = stripe_object_value(session, "livemode")
    status = stripe_object_value(session, "status")
    checkout_url = stripe_object_value(session, "url")

    if not isinstance(session_id, str) or not session_id.startswith("cs_"):
        raise BaseCheckoutValidationError("Stripe checkout session id is invalid.")
    if attempt.stripe_session_id and session_id != attempt.stripe_session_id:
        raise BaseCheckoutValidationError("Stripe checkout session id does not match.")
    if stripe_object_value(session, "mode") != "subscription":
        raise BaseCheckoutValidationError("Stripe checkout mode does not match.")
    if customer_id != attempt.stripe_customer_id:
        raise BaseCheckoutValidationError("Stripe checkout customer does not match.")
    if not isinstance(raw_metadata, Mapping) or set(raw_metadata) != BASE_CHECKOUT_METADATA_KEYS:
        raise BaseCheckoutValidationError("Stripe checkout metadata fields do not match.")
    if metadata != expected_metadata:
        raise BaseCheckoutValidationError("Stripe checkout metadata does not match.")
    if stripe_object_value(session, "client_reference_id") != str(attempt.user_id):
        raise BaseCheckoutValidationError("Stripe checkout user reference does not match.")
    if not isinstance(livemode, bool) or livemode != (attempt.stripe_mode == "live"):
        raise BaseCheckoutValidationError("Stripe checkout mode environment does not match.")
    if status not in {"open", "complete", "expired"}:
        raise BaseCheckoutValidationError("Stripe checkout session status is invalid.")
    if status == "open":
        if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
            raise BaseCheckoutValidationError("Stripe checkout URL is invalid.")
    else:
        checkout_url = None
    return session_id, checkout_url, status


def complete_base_checkout_attempt(
    db: Session,
    *,
    session: Mapping[str, Any],
    subscription_payload: Mapping[str, Any],
    stripe_mode: str,
    expected_plan: str,
    expected_interval: str,
) -> tuple[models.BaseCheckoutAttempt, bool]:
    metadata = normalize_base_checkout_metadata(session.get("metadata"))
    attempt_id = metadata.get("base_checkout_attempt_id")
    if metadata.get("type") != "base_subscription" or not attempt_id:
        raise BaseCheckoutValidationError("Base checkout attempt metadata is missing.")

    attempt = db.execute(
        select(models.BaseCheckoutAttempt)
        .where(models.BaseCheckoutAttempt.id == attempt_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    ).scalar_one_or_none()
    if attempt is None:
        raise BaseCheckoutValidationError("Base checkout attempt was not found.")

    session_id = str(session.get("id") or "").strip()
    customer_id = str(session.get("customer") or "").strip()
    subscription_id = str(session.get("subscription") or "").strip()
    retrieved_subscription_id = str(subscription_payload.get("id") or "").strip()
    subscription_customer = str(subscription_payload.get("customer") or "").strip()
    subscription_status = str(subscription_payload.get("status") or "").strip().lower()
    expected_metadata = base_checkout_metadata(attempt)

    if metadata != expected_metadata:
        raise BaseCheckoutValidationError("Base checkout metadata does not match its attempt.")
    if stripe_mode != attempt.stripe_mode:
        raise BaseCheckoutValidationError("Base checkout Stripe mode does not match.")
    if expected_plan != attempt.target_plan or expected_interval != attempt.billing_interval:
        raise BaseCheckoutValidationError("Base checkout price does not match its attempt.")
    if str(metadata.get("user_id")) != str(attempt.user_id):
        raise BaseCheckoutValidationError("Base checkout user does not match its attempt.")
    if session.get("mode") != "subscription" or session.get("status") != "complete":
        raise BaseCheckoutValidationError("Base checkout session state does not match.")
    if str(session.get("client_reference_id") or "") != str(attempt.user_id):
        raise BaseCheckoutValidationError("Base checkout session user does not match.")
    if (
        not session_id.startswith("cs_")
        or not customer_id
        or not subscription_id.startswith("sub_")
    ):
        raise BaseCheckoutValidationError("Base checkout Stripe references are invalid.")
    if retrieved_subscription_id != subscription_id:
        raise BaseCheckoutValidationError("Base checkout subscription does not match.")
    if subscription_customer != customer_id:
        raise BaseCheckoutValidationError("Base checkout subscription customer does not match.")
    if subscription_status not in {"active", "trialing"}:
        raise BaseCheckoutValidationError("Base checkout subscription is not entitled.")
    if attempt.stripe_session_id not in {None, session_id}:
        raise BaseCheckoutValidationError("Base checkout session does not match its attempt.")
    if attempt.stripe_customer_id is None:
        if (
            attempt.status != "pending"
            or attempt.stripe_session_id is not None
            or attempt.completed_at is not None
        ):
            raise BaseCheckoutValidationError("Base checkout customer does not match its attempt.")
    elif attempt.stripe_customer_id != customer_id:
        raise BaseCheckoutValidationError("Base checkout customer does not match its attempt.")

    if attempt.status == "completed":
        return attempt, False
    if attempt.status not in BASE_CHECKOUT_ACTIVE_STATUSES:
        raise BaseCheckoutConflictError("Base checkout attempt is no longer active.")

    attempt.stripe_customer_id = customer_id
    attempt.stripe_session_id = session_id
    attempt.status = "completed"
    attempt.completed_at = utc_now()
    attempt.updated_at = attempt.completed_at
    return attempt, True
