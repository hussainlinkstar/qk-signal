from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from auth.credits import decrement_credits_atomic, increment_credits_atomic
from services.credit_commitment_service import record_commitment_usage

CREDIT_HOLD_STATUS_PENDING = "pending"
CREDIT_HOLD_STATUS_SETTLED = "settled"
CREDIT_HOLD_STATUS_REFUNDED = "refunded"
CREDIT_HOLD_STATUS_EXPIRED = "expired"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _copy_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    return dict(payload)


def _merge_payload(
    current_payload: dict[str, Any] | None,
    updates: dict[str, Any] | None,
) -> dict[str, Any]:
    merged = _copy_payload(current_payload)
    if isinstance(updates, dict):
        merged.update(updates)
    return merged


def _get_credit_hold_for_update(db: Session, *, request_id: str) -> models.CreditHold | None:
    return (
        db.query(models.CreditHold)
        .filter(models.CreditHold.request_id == str(request_id))
        .with_for_update()
        .first()
    )


def acquire_credit_hold(
    db: Session,
    *,
    user_id: int,
    hold_amount: int,
    request_id: str,
    reason_code: str,
    feature_key: str,
    tier_class: str,
    policy_version: str,
    ttl_seconds: int = 1800,
    workspace_id: int | None = None,
    project_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> models.CreditHold:
    normalized_hold_amount = max(1, int(hold_amount))
    normalized_request_id = str(request_id).strip()
    if not normalized_request_id:
        raise ValueError("request_id is required for credit holds")

    existing_hold = _get_credit_hold_for_update(db, request_id=normalized_request_id)
    if existing_hold is not None:
        return existing_hold

    user = db.query(models.User).filter(models.User.id == int(user_id)).with_for_update().first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    available_credits = int(user.credits or 0)
    # SIGV2-1024: credits are internal soft limits. A shortfall never blocks
    # the audit; the hold is still recorded and the internal balance is
    # allowed to go negative so accounting stays honest.
    hold_shortfall = max(0, normalized_hold_amount - available_credits)

    updated = decrement_credits_atomic(
        db,
        user.id,
        normalized_hold_amount,
        record_commitment=False,
        allow_negative=True,
    )
    if not updated:
        raise HTTPException(
            status_code=500,
            detail="Failed to reserve internal audit accounting.",
        )

    hold = models.CreditHold(
        user_id=user.id,
        request_id=normalized_request_id,
        hold_amount=normalized_hold_amount,
        refunded_amount=0,
        status=CREDIT_HOLD_STATUS_PENDING,
        reason_code=str(reason_code),
        feature_key=str(feature_key),
        tier_class=str(tier_class or "fast"),
        policy_version=str(policy_version or "v1"),
        workspace_id=workspace_id,
        project_id=project_id,
        expires_at=_utcnow() + timedelta(seconds=max(60, int(ttl_seconds))),
        payload_json=_merge_payload(
            payload,
            {
                "state": "locked",
                "hold_amount": normalized_hold_amount,
                "available_credits_at_lock": available_credits,
                "hold_shortfall": hold_shortfall,
            },
        ),
    )
    db.add(hold)
    db.flush()
    return hold


def settle_credit_hold(
    db: Session,
    *,
    request_id: str,
    final_amount: int,
    billing: Any | None = None,
    payload: dict[str, Any] | None = None,
) -> models.CreditHold:
    hold = _get_credit_hold_for_update(db, request_id=str(request_id))
    if hold is None:
        raise ValueError(f"CreditHold not found for request_id={request_id}")
    if hold.status != CREDIT_HOLD_STATUS_PENDING:
        return hold

    requested_final_amount = max(0, int(final_amount))
    locked_amount = max(0, int(hold.hold_amount or 0))
    refund_amount = max(0, locked_amount - requested_final_amount)
    extra_charge_requested = max(0, requested_final_amount - locked_amount)
    extra_charge_applied = 0

    if refund_amount > 0:
        increment_credits_atomic(db, hold.user_id, refund_amount)
    elif extra_charge_requested > 0:
        # Internal accounting stays honest: apply the full extra charge even
        # when it pushes the internal balance negative.
        if decrement_credits_atomic(
            db,
            hold.user_id,
            extra_charge_requested,
            record_commitment=False,
            allow_negative=True,
        ):
            extra_charge_applied = extra_charge_requested

    actual_final_amount = max(0, locked_amount - refund_amount + extra_charge_applied)
    if actual_final_amount > 0:
        record_commitment_usage(db, user_id=hold.user_id, amount=actual_final_amount)

    hold.final_amount = actual_final_amount
    hold.refunded_amount = refund_amount
    hold.status = CREDIT_HOLD_STATUS_SETTLED
    hold.settled_at = _utcnow()
    hold.payload_json = _merge_payload(
        hold.payload_json,
        {
            "state": "settled",
            "requested_final_amount": requested_final_amount,
            "actual_final_amount": actual_final_amount,
            "hold_delta": locked_amount - actual_final_amount,
            "extra_charge_requested": extra_charge_requested,
            "extra_charge_applied": extra_charge_applied,
            "extra_charge_shortfall": max(0, extra_charge_requested - extra_charge_applied),
            "billing_summary": {
                "feature_key": getattr(billing, "feature_key", None),
                "tier_class": getattr(billing, "tier_class", None),
                "policy_version": getattr(billing, "policy_version", None),
            }
            if billing is not None
            else None,
            **_copy_payload(payload),
        },
    )
    db.add(hold)
    db.flush()
    return hold


def release_credit_hold(
    db: Session,
    *,
    request_id: str,
    refund_reason: str = "provider_failure",
    expired: bool = False,
    payload: dict[str, Any] | None = None,
) -> models.CreditHold:
    hold = _get_credit_hold_for_update(db, request_id=str(request_id))
    if hold is None:
        raise ValueError(f"CreditHold not found for request_id={request_id}")
    if hold.status != CREDIT_HOLD_STATUS_PENDING:
        return hold

    refund_amount = max(0, int(hold.hold_amount or 0))
    if refund_amount > 0:
        increment_credits_atomic(db, hold.user_id, refund_amount)

    hold.final_amount = 0
    hold.refunded_amount = refund_amount
    hold.status = CREDIT_HOLD_STATUS_EXPIRED if expired else CREDIT_HOLD_STATUS_REFUNDED
    hold.settled_at = _utcnow()
    hold.payload_json = _merge_payload(
        hold.payload_json,
        {
            "state": "released",
            "refund_reason": str(refund_reason),
            "hold_delta": refund_amount,
            **_copy_payload(payload),
        },
    )
    db.add(hold)
    db.flush()
    return hold


def expire_stale_holds(db: Session, *, reference_time: datetime | None = None) -> list[int]:
    now = reference_time.astimezone(timezone.utc) if reference_time else _utcnow()
    stale_holds = (
        db.query(models.CreditHold)
        .filter(
            models.CreditHold.status == CREDIT_HOLD_STATUS_PENDING,
            models.CreditHold.expires_at < now,
        )
        .with_for_update(skip_locked=True)
        .all()
    )
    expired_ids: list[int] = []
    for hold in stale_holds:
        expired_ids.append(int(hold.id))
        release_credit_hold(
            db,
            request_id=hold.request_id,
            refund_reason="expired",
            expired=True,
            payload={"expired_at": now.isoformat()},
        )
    return expired_ids
