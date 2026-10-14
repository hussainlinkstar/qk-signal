"""Server-driven trial feedback request lifecycle."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from services.email_service import EmailService
from services.trial_service import resolve_trial_status

logger = logging.getLogger(__name__)

TRIAL_FEEDBACK_REQUEST_EXPIRY_DAYS = 45


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _frontend_base_url() -> str:
    for env_key in ("FRONTEND_URL", "APP_BASE_URL"):
        value = (os.getenv(env_key) or "").strip()
        if value:
            return value.rstrip("/")
    return "http://localhost:3000"


def _sender_name(user: models.User | None) -> str:
    if user is None:
        return "Qiko Signal Team"
    return str(getattr(user, "company_name", None) or user.email).strip()


def _expire_request_if_needed(
    db: Session,
    feedback_request: models.TrialFeedbackRequest,
    *,
    now: datetime | None = None,
) -> str:
    reference_time = now or _now()
    expires_at = _coerce_utc(feedback_request.expires_at)
    if (
        feedback_request.status == "pending"
        and expires_at is not None
        and reference_time >= expires_at
    ):
        feedback_request.status = "expired"
        feedback_request.updated_at = reference_time
        db.add(feedback_request)
        db.flush()
    return str(feedback_request.status)


def _resolve_trial_invitation_for_user(
    db: Session,
    user: models.User,
) -> models.TrialInvitation | None:
    invitation = (
        db.query(models.TrialInvitation)
        .filter(models.TrialInvitation.redeemed_by_user_id == user.id)
        .order_by(
            models.TrialInvitation.redeemed_at.desc(),
            models.TrialInvitation.created_at.desc(),
        )
        .first()
    )
    if invitation is not None:
        return invitation
    return (
        db.query(models.TrialInvitation)
        .filter(models.TrialInvitation.email == user.email)
        .order_by(models.TrialInvitation.created_at.desc())
        .first()
    )


def _resolve_request_sender(
    db: Session,
    *,
    invitation: models.TrialInvitation | None,
) -> models.User | None:
    if invitation is not None and invitation.invited_by is not None:
        return invitation.invited_by
    return (
        db.query(models.User)
        .filter(models.User.role == "admin")
        .order_by(models.User.id.asc())
        .first()
    )


def build_feedback_url(feedback_request: models.TrialFeedbackRequest) -> str:
    return f"{_frontend_base_url()}/trial-feedback/{feedback_request.token}"


def get_feedback_request_by_token(
    db: Session,
    token: str,
) -> models.TrialFeedbackRequest | None:
    feedback_request = (
        db.query(models.TrialFeedbackRequest)
        .filter(models.TrialFeedbackRequest.token == token)
        .first()
    )
    if feedback_request is None:
        return None
    _expire_request_if_needed(db, feedback_request)
    return feedback_request


def create_feedback_request_for_user(
    db: Session,
    *,
    user: models.User,
    now: datetime | None = None,
) -> tuple[models.TrialFeedbackRequest, bool]:
    reference_time = now or _now()
    if not user.trial_plan or user.trial_started_at is None:
        raise HTTPException(status_code=409, detail="User does not have a completed trial.")

    existing = (
        db.query(models.TrialFeedbackRequest)
        .filter(
            models.TrialFeedbackRequest.user_id == user.id,
            models.TrialFeedbackRequest.trial_started_at_snapshot == user.trial_started_at,
        )
        .first()
    )
    if existing is not None:
        _expire_request_if_needed(db, existing, now=reference_time)
        return existing, False

    trial_status = resolve_trial_status(user)
    invitation = _resolve_trial_invitation_for_user(db, user)
    sender = _resolve_request_sender(db, invitation=invitation)
    feedback_request = models.TrialFeedbackRequest(
        user_id=user.id,
        trial_invitation_id=invitation.id if invitation is not None else None,
        requested_by_user_id=sender.id if sender is not None else None,
        token=str(uuid.uuid4()),
        status="pending",
        trigger_reason=trial_status.get("limit_reason") or "trial_completed",
        trial_started_at_snapshot=user.trial_started_at,
        trial_ended_at_snapshot=user.trial_ends_at,
        requested_at=reference_time,
        expires_at=reference_time + timedelta(days=TRIAL_FEEDBACK_REQUEST_EXPIRY_DAYS),
        updated_at=reference_time,
        schema_version="1",
    )
    db.add(feedback_request)
    db.flush()
    return feedback_request, True


def maybe_queue_feedback_request_email(
    db: Session,
    *,
    feedback_request: models.TrialFeedbackRequest,
) -> bool:
    status_value = _expire_request_if_needed(db, feedback_request)
    if status_value != "pending":
        return False

    correlation_id = f"trial.feedback_request:{feedback_request.id}"
    existing_outbox = (
        db.query(models.EmailOutbox)
        .filter(models.EmailOutbox.correlation_id == correlation_id)
        .first()
    )
    if existing_outbox is not None:
        return False

    sender = feedback_request.requested_by
    entry = EmailService(db).queue_trial_feedback_request_email(
        feedback_request.user.email,
        user_id=feedback_request.user_id,
        user_name=feedback_request.user.company_name,
        admin_name=_sender_name(sender),
        feedback_url=build_feedback_url(feedback_request),
        trial_ended_at=(
            feedback_request.trial_ended_at_snapshot.strftime("%B %d, %Y")
            if feedback_request.trigger_reason == "trial_expired"
            and feedback_request.trial_ended_at_snapshot
            else None
        ),
        correlation_id=correlation_id,
        commit=False,
    )
    if entry is None:
        logger.warning(
            "Trial feedback request email was not queued for user_id=%s request_id=%s",
            feedback_request.user_id,
            feedback_request.id,
        )
        return False
    return True


def queue_feedback_requests_for_completed_trials(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    reference_time = now or _now()
    candidates = (
        db.query(models.User)
        .filter(
            models.User.trial_plan.isnot(None),
            models.User.trial_started_at.isnot(None),
        )
        .all()
    )

    created_requests = 0
    queued_emails = 0
    eligible_users = 0
    for user in candidates:
        trial_status = resolve_trial_status(user)
        if trial_status["trial_active"]:
            continue

        eligible_users += 1
        feedback_request, created = create_feedback_request_for_user(
            db,
            user=user,
            now=reference_time,
        )
        if created:
            created_requests += 1
        if maybe_queue_feedback_request_email(db, feedback_request=feedback_request):
            queued_emails += 1

    return {
        "eligible_users": eligible_users,
        "created_requests": created_requests,
        "queued_emails": queued_emails,
    }


def serialize_public_feedback_request(
    db: Session,
    feedback_request: models.TrialFeedbackRequest,
) -> dict[str, Any]:
    status_value = _expire_request_if_needed(db, feedback_request)
    return {
        "token": feedback_request.token,
        "status": status_value,
        "recipient_email": feedback_request.user.email,
        "recipient_name": feedback_request.user.company_name or feedback_request.user.email,
        "requested_by_name": _sender_name(feedback_request.requested_by),
        "trigger_reason": feedback_request.trigger_reason,
        "trial_started_at": (
            feedback_request.trial_started_at_snapshot.isoformat()
            if feedback_request.trial_started_at_snapshot
            else None
        ),
        "trial_ended_at": (
            feedback_request.trial_ended_at_snapshot.isoformat()
            if feedback_request.trial_ended_at_snapshot
            else None
        ),
        "expires_at": (
            feedback_request.expires_at.isoformat() if feedback_request.expires_at else None
        ),
        "submitted_at": (
            feedback_request.submitted_at.isoformat() if feedback_request.submitted_at else None
        ),
    }


def submit_feedback(
    db: Session,
    *,
    token: str,
    overall_rating: int,
    would_recommend: str,
    what_worked_well: str | None,
    what_was_missing: str | None,
    improvement_suggestions: str | None,
) -> models.TrialFeedbackRequest:
    feedback_request = get_feedback_request_by_token(db, token)
    if feedback_request is None:
        raise HTTPException(status_code=404, detail="Feedback request not found.")

    status_value = _expire_request_if_needed(db, feedback_request)
    if status_value == "submitted":
        raise HTTPException(status_code=409, detail="Feedback has already been submitted.")
    if status_value == "expired":
        raise HTTPException(status_code=410, detail="This feedback link has expired.")

    reference_time = _now()
    feedback_request.status = "submitted"
    feedback_request.overall_rating = overall_rating
    feedback_request.would_recommend = would_recommend
    feedback_request.what_worked_well = what_worked_well
    feedback_request.what_was_missing = what_was_missing
    feedback_request.improvement_suggestions = improvement_suggestions
    feedback_request.submitted_at = reference_time
    feedback_request.updated_at = reference_time
    db.add(feedback_request)
    db.flush()
    return feedback_request
