"""Admin endpoints for trial invitation management, conversion tracking, and feedback."""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

import models
from auth.token_verifier import get_current_staff_user
from database import get_db
from services.trial_invitation_service import (
    create_invitation,
    delete_invitation,
    get_conversion_stats,
    list_invitations,
    resend_invitation,
    revoke_invitation,
    serialize_invitation,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/trial", tags=["admin-trial"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class CreateInvitationRequest(BaseModel):
    email: EmailStr
    contact_name: str | None = None
    notes: str | None = None
    expiry_days: int = 30


class InvitationResponse(BaseModel):
    model_config = {"extra": "allow"}


class InvitationListResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
    skip: int
    limit: int


class ConversionStatsResponse(BaseModel):
    total_invited: int
    pending: int
    redeemed: int
    expired: int
    revoked: int
    converted_to_paid: int
    conversion_rate_pct: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/invitations", status_code=201)
def admin_create_invitation(
    request: CreateInvitationRequest,
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Create a new trial invitation and send the invitation email."""
    invitation = create_invitation(
        db,
        email=request.email,
        contact_name=request.contact_name,
        invited_by_user_id=admin.id,
        notes=request.notes,
        expiry_days=request.expiry_days,
    )
    db.commit()
    db.refresh(invitation)

    # Send invitation email
    _send_trial_invitation_email(
        db=db,
        invitation=invitation,
        admin_name=getattr(admin, "company_name", None) or admin.email,
    )

    return serialize_invitation(invitation)


@router.get("/invitations")
def admin_list_invitations(
    status: str | None = Query(
        None, description="Filter by status: pending, redeemed, expired, revoked"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """List all trial invitations with optional status filter."""
    items, total = list_invitations(db, status_filter=status, skip=skip, limit=limit)
    return {
        "items": [serialize_invitation(inv) for inv in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.post("/invitations/{invitation_id}/revoke")
def admin_revoke_invitation(
    invitation_id: int,
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Revoke a pending invitation."""
    invitation = revoke_invitation(db, invitation_id)
    db.commit()
    db.refresh(invitation)
    return serialize_invitation(invitation)


@router.post("/invitations/{invitation_id}/resend")
def admin_resend_invitation(
    invitation_id: int,
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Resend a revoked or expired invitation with a fresh token and expiry."""
    invitation = resend_invitation(db, invitation_id)
    db.commit()
    db.refresh(invitation)

    # Re-send email
    _send_trial_invitation_email(
        db=db,
        invitation=invitation,
        admin_name=getattr(admin, "company_name", None) or admin.email,
    )

    return serialize_invitation(invitation)


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def admin_delete_invitation(
    invitation_id: int,
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Response:
    """Permanently delete an invitation."""
    delete_invitation(db, invitation_id)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/conversion-stats", response_model=ConversionStatsResponse)
def admin_get_conversion_stats(
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Get conversion funnel statistics for all trial invitations."""
    return get_conversion_stats(db)


# ---------------------------------------------------------------------------
# Feedback endpoints
# ---------------------------------------------------------------------------


def _serialize_feedback_request(fr: models.TrialFeedbackRequest) -> dict[str, Any]:
    user = fr.user
    requester = fr.requested_by
    return {
        "id": fr.id,
        "user_id": fr.user_id,
        "recipient_email": user.email if user else None,
        "recipient_name": (user.company_name or user.email) if user else None,
        "requested_by_name": (
            (requester.company_name or requester.email) if requester else "System"
        ),
        "token": fr.token,
        "status": fr.status,
        "trigger_reason": fr.trigger_reason,
        "overall_rating": fr.overall_rating,
        "would_recommend": fr.would_recommend,
        "what_worked_well": fr.what_worked_well,
        "what_was_missing": fr.what_was_missing,
        "improvement_suggestions": fr.improvement_suggestions,
        "trial_started_at": (
            fr.trial_started_at_snapshot.isoformat() if fr.trial_started_at_snapshot else None
        ),
        "trial_ended_at": (
            fr.trial_ended_at_snapshot.isoformat() if fr.trial_ended_at_snapshot else None
        ),
        "requested_at": fr.requested_at.isoformat() if fr.requested_at else None,
        "submitted_at": fr.submitted_at.isoformat() if fr.submitted_at else None,
        "expires_at": fr.expires_at.isoformat() if fr.expires_at else None,
    }


@router.get("/feedback")
def admin_list_feedback(
    status_filter: str | None = Query(
        None, alias="status", description="Filter: pending, submitted, expired"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """List all trial feedback requests with optional status filter."""
    query = (
        db.query(models.TrialFeedbackRequest)
        .options(
            joinedload(models.TrialFeedbackRequest.user),
            joinedload(models.TrialFeedbackRequest.requested_by),
        )
        .order_by(models.TrialFeedbackRequest.requested_at.desc())
    )
    if status_filter:
        query = query.filter(models.TrialFeedbackRequest.status == status_filter)

    total = query.count()
    items = query.offset(skip).limit(limit).all()

    return {
        "items": [_serialize_feedback_request(fr) for fr in items],
        "total": total,
        "skip": skip,
        "limit": limit,
    }


@router.get("/feedback/stats")
def admin_feedback_stats(
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Aggregate statistics for trial feedback responses."""
    total = db.query(func.count(models.TrialFeedbackRequest.id)).scalar() or 0
    pending = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(models.TrialFeedbackRequest.status == "pending")
        .scalar()
        or 0
    )
    submitted = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(models.TrialFeedbackRequest.status == "submitted")
        .scalar()
        or 0
    )
    expired = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(models.TrialFeedbackRequest.status == "expired")
        .scalar()
        or 0
    )
    avg_rating = (
        db.query(func.avg(models.TrialFeedbackRequest.overall_rating))
        .filter(
            models.TrialFeedbackRequest.status == "submitted",
            models.TrialFeedbackRequest.overall_rating.isnot(None),
        )
        .scalar()
    )
    recommend_yes = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(
            models.TrialFeedbackRequest.status == "submitted",
            models.TrialFeedbackRequest.would_recommend == "yes",
        )
        .scalar()
        or 0
    )
    recommend_maybe = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(
            models.TrialFeedbackRequest.status == "submitted",
            models.TrialFeedbackRequest.would_recommend == "maybe",
        )
        .scalar()
        or 0
    )
    recommend_no = (
        db.query(func.count(models.TrialFeedbackRequest.id))
        .filter(
            models.TrialFeedbackRequest.status == "submitted",
            models.TrialFeedbackRequest.would_recommend == "no",
        )
        .scalar()
        or 0
    )
    response_rate = round((submitted / total) * 100, 1) if total > 0 else 0.0

    return {
        "total": total,
        "pending": pending,
        "submitted": submitted,
        "expired": expired,
        "avg_rating": round(avg_rating, 2) if avg_rating is not None else None,
        "recommend_yes": recommend_yes,
        "recommend_maybe": recommend_maybe,
        "recommend_no": recommend_no,
        "response_rate_pct": response_rate,
    }


@router.get("/feedback/{feedback_id}")
def admin_get_feedback_detail(
    feedback_id: int,
    admin: models.User = Depends(get_current_staff_user),
    db: Session = Depends(get_db),
) -> Any:
    """Get a single feedback request with all fields."""
    fr = (
        db.query(models.TrialFeedbackRequest)
        .options(
            joinedload(models.TrialFeedbackRequest.user),
            joinedload(models.TrialFeedbackRequest.requested_by),
        )
        .filter(models.TrialFeedbackRequest.id == feedback_id)
        .first()
    )
    if fr is None:
        raise HTTPException(status_code=404, detail="Feedback request not found.")
    return _serialize_feedback_request(fr)


# ---------------------------------------------------------------------------
# Email helper
# ---------------------------------------------------------------------------


def _send_trial_invitation_email(
    *,
    db: Session,
    invitation: models.TrialInvitation,
    admin_name: str,
) -> None:
    """Queue a trial invitation email via the email outbox."""
    try:
        from services.email_service import EmailService

        app_base_url = (
            os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL") or "http://localhost:3000"
        ).rstrip("/")
        register_url = f"{app_base_url}/register?trial_token={invitation.token}"

        entry = EmailService(db).queue_template_email(
            to_email=invitation.email,
            template_key="trial.invitation",
            context={
                "email": invitation.email,
                "user_name": invitation.contact_name,
                "inviter_name": admin_name,
                "register_url": register_url,
                "trial_duration_days": 14,
                "trial_credits": 100,
                "trial_audit_limit": 5,
                "invitation_expires_at": (
                    invitation.expires_at.strftime("%B %d, %Y") if invitation.expires_at else None
                ),
            },
            correlation_id=f"trial.invitation:{invitation.id}",
            commit=True,
        )
        if entry is None:
            logger.error(
                "Trial invitation email was not queued for %s (invitation_id=%s); outbound mail disabled.",
                invitation.email,
                invitation.id,
            )
        else:
            logger.info(
                "Queued trial invitation email for %s (invitation_id=%s, outbox_id=%s)",
                invitation.email,
                invitation.id,
                entry.id,
            )
    except Exception:
        logger.exception(
            "Failed to queue trial invitation email for %s (invitation_id=%s)",
            invitation.email,
            invitation.id,
        )
