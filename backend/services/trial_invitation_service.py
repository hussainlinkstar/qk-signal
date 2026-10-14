"""Admin-managed trial invitation lifecycle.

Handles creation, listing, redemption, revocation, and conversion tracking
for trial invitations sent to prospective agency users.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TypedDict

from fastapi import HTTPException
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

import models

DEFAULT_INVITATION_EXPIRY_DAYS = 30
logger = logging.getLogger(__name__)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class InvitationConversionStats(TypedDict):
    total_invited: int
    pending: int
    redeemed: int
    expired: int
    revoked: int
    converted_to_paid: int
    conversion_rate_pct: float


def create_invitation(
    db: Session,
    *,
    email: str,
    contact_name: str | None = None,
    invited_by_user_id: int | None = None,
    notes: str | None = None,
    expiry_days: int = DEFAULT_INVITATION_EXPIRY_DAYS,
) -> models.TrialInvitation:
    """Reject creation of retired trial invitations."""
    raise HTTPException(status_code=410, detail="Agency Trial invitations are no longer available.")


def list_invitations(
    db: Session,
    *,
    status_filter: str | None = None,
    skip: int = 0,
    limit: int = 50,
) -> tuple[list[models.TrialInvitation], int]:
    """List invitations with optional status filter. Returns (items, total)."""
    query = db.query(models.TrialInvitation)
    if status_filter:
        query = query.filter(models.TrialInvitation.status == status_filter)
    total = query.count()
    items = query.order_by(models.TrialInvitation.created_at.desc()).offset(skip).limit(limit).all()
    return items, total


def get_invitation_by_token(db: Session, token: str) -> models.TrialInvitation | None:
    return db.query(models.TrialInvitation).filter(models.TrialInvitation.token == token).first()


def get_invitation_by_email(db: Session, email: str) -> models.TrialInvitation | None:
    """Find a pending, non-expired invitation for the given email."""
    normalized = email.strip().lower()
    now = datetime.now(timezone.utc)
    return (
        db.query(models.TrialInvitation)
        .filter(
            models.TrialInvitation.email == normalized,
            models.TrialInvitation.status == "pending",
        )
        .filter(
            (models.TrialInvitation.expires_at.is_(None))
            | (models.TrialInvitation.expires_at > now)
        )
        .first()
    )


def resolve_pending_invitation(
    db: Session,
    *,
    email: str,
    invitation_token: str | None = None,
    strict_token_email_match: bool = False,
) -> models.TrialInvitation | None:
    """Resolve the invitation a registration flow should redeem.

    Token lookup takes precedence, but tokens may only be redeemed by the
    invited email address. Email fallback keeps the SSO path working when a
    provider returns the invited address but no explicit token is present.
    """
    normalized_email = email.strip().lower()
    invitation = None
    if invitation_token:
        invitation = get_invitation_by_token(db, invitation_token)
        if invitation and invitation.email != normalized_email:
            if strict_token_email_match:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"This invitation was issued for {invitation.email}. "
                        "Register with that email address to redeem the trial."
                    ),
                )
            logger.info(
                "Skipping trial invitation token redemption because email does not match "
                "(invitation_id=%s invitation_email=%s user_email=%s)",
                invitation.id,
                invitation.email,
                normalized_email,
            )
            invitation = None

    if invitation is None:
        invitation = get_invitation_by_email(db, normalized_email)

    if invitation and invitation.status == "pending":
        return invitation
    return None


def redeem_invitation(
    db: Session,
    *,
    invitation: models.TrialInvitation,
    user: models.User,
) -> models.TrialInvitation:
    """Mark an invitation as redeemed by the registering user.

    This should be called during user registration when a matching invitation exists.
    """
    if invitation.status != "pending":
        return invitation

    now = datetime.now(timezone.utc)
    expires_at = _coerce_utc(invitation.expires_at)
    if expires_at and now >= expires_at:
        invitation.status = "expired"
        invitation.updated_at = now
        db.add(invitation)
        db.flush()
        return invitation

    invitation.status = "redeemed"
    invitation.redeemed_by_user_id = user.id
    invitation.redeemed_at = now
    invitation.updated_at = now
    db.add(invitation)
    db.flush()
    return invitation


def apply_pending_invitation_for_user(
    db: Session,
    *,
    user: models.User,
    invitation_token: str | None = None,
) -> models.TrialInvitation | None:
    """Ignore retired invitations without changing historical records."""
    return None


def revoke_invitation(db: Session, invitation_id: int) -> models.TrialInvitation:
    """Revoke a pending invitation."""
    invitation = (
        db.query(models.TrialInvitation).filter(models.TrialInvitation.id == invitation_id).first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    if invitation.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot revoke invitation with status '{invitation.status}'.",
        )
    invitation.status = "revoked"
    invitation.updated_at = datetime.now(timezone.utc)
    db.add(invitation)
    db.flush()
    return invitation


def delete_invitation(db: Session, invitation_id: int) -> None:
    """Permanently delete an invitation record."""
    invitation = (
        db.query(models.TrialInvitation).filter(models.TrialInvitation.id == invitation_id).first()
    )
    if not invitation:
        raise HTTPException(status_code=404, detail="Invitation not found.")
    db.delete(invitation)
    db.flush()


def resend_invitation(db: Session, invitation_id: int) -> models.TrialInvitation:
    """Reject resending retired trial invitations."""
    raise HTTPException(status_code=410, detail="Agency Trial invitations are no longer available.")


def get_conversion_stats(db: Session) -> InvitationConversionStats:
    """Compute conversion funnel statistics across all invitations."""
    total = db.query(sa_func.count(models.TrialInvitation.id)).scalar() or 0
    pending = (
        db.query(sa_func.count(models.TrialInvitation.id))
        .filter(models.TrialInvitation.status == "pending")
        .scalar()
        or 0
    )
    redeemed = (
        db.query(sa_func.count(models.TrialInvitation.id))
        .filter(models.TrialInvitation.status == "redeemed")
        .scalar()
        or 0
    )
    expired = (
        db.query(sa_func.count(models.TrialInvitation.id))
        .filter(models.TrialInvitation.status == "expired")
        .scalar()
        or 0
    )
    revoked = (
        db.query(sa_func.count(models.TrialInvitation.id))
        .filter(models.TrialInvitation.status == "revoked")
        .scalar()
        or 0
    )

    # Count how many redeemed users went on to get a paid subscription
    converted_to_paid = 0
    if redeemed > 0:
        redeemed_user_ids = (
            db.query(models.TrialInvitation.redeemed_by_user_id)
            .filter(
                models.TrialInvitation.status == "redeemed",
                models.TrialInvitation.redeemed_by_user_id.isnot(None),
            )
            .subquery()
        )
        converted_to_paid = (
            db.query(sa_func.count(models.Subscription.id))
            .filter(
                models.Subscription.user_id.in_(db.query(redeemed_user_ids.c.redeemed_by_user_id)),
                models.Subscription.status == "active",
                models.Subscription.plan_type != "plan_agency_trial",
            )
            .scalar()
            or 0
        )

    conversion_rate = (converted_to_paid / redeemed * 100) if redeemed > 0 else 0.0

    return InvitationConversionStats(
        total_invited=total,
        pending=pending,
        redeemed=redeemed,
        expired=expired,
        revoked=revoked,
        converted_to_paid=converted_to_paid,
        conversion_rate_pct=round(conversion_rate, 1),
    )


def serialize_invitation(inv: models.TrialInvitation) -> dict:
    """Serialize an invitation to a JSON-safe dict."""
    # Resolve redeemed user's trial + subscription status
    redeemed_user_status = None
    if inv.redeemed_by:
        user = inv.redeemed_by
        trial_ends_at = _coerce_utc(user.trial_ends_at)
        has_paid = bool(
            user.subscription
            and user.subscription.status == "active"
            and user.subscription.plan_type != "plan_agency_trial"
        )
        redeemed_user_status = {
            "user_id": user.id,
            "email": user.email,
            "trial_active": bool(
                user.trial_plan and trial_ends_at and datetime.now(timezone.utc) < trial_ends_at
            ),
            "trial_expired": bool(
                user.trial_plan and trial_ends_at and datetime.now(timezone.utc) >= trial_ends_at
            ),
            "has_paid_subscription": has_paid,
            "plan_type": user.subscription.plan_type if user.subscription else None,
            "credits": user.credits or 0,
            "trial_audits_used": user.trial_audits_used or 0,
        }

    return {
        "id": inv.id,
        "email": inv.email,
        "contact_name": inv.contact_name,
        "token": inv.token,
        "status": inv.status,
        "invited_by_user_id": inv.invited_by_user_id,
        "redeemed_by_user_id": inv.redeemed_by_user_id,
        "redeemed_at": inv.redeemed_at.isoformat() if inv.redeemed_at else None,
        "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
        "notes": inv.notes,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "updated_at": inv.updated_at.isoformat() if inv.updated_at else None,
        "redeemed_user": redeemed_user_status,
    }
