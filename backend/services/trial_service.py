"""Agency trial lifecycle management.

Handles activation, status resolution, limit enforcement, and expiry
for the 14-day agency trial (100 credits, 5 audits max).
Also manages the trial → Explorer auto-transition.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import TypedDict

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    TRIAL_CREDITS,
    TRIAL_MAX_AUDITS,
    get_plan_capabilities,
)

logger = logging.getLogger(__name__)

STARTER_PLAN = "plan_starter"
STARTER_MONTHLY_CREDITS = int(get_plan_capabilities(STARTER_PLAN)["credits_per_month"])
STARTER_CREDIT_REFRESH_INTERVAL_DAYS = 30


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class TrialStatus(TypedDict):
    is_trial: bool
    trial_active: bool
    trial_expired: bool
    trial_plan: str | None
    trial_started_at: str | None
    trial_ends_at: str | None
    days_remaining: int
    credits_remaining: int
    credits_total: int
    audits_used: int
    audits_total: int
    concierge_completed: bool
    limits_reached: bool
    limit_reason: str | None


def activate_trial(db: Session, user: models.User) -> models.User:
    """Preserve existing trial records and reject new trial activation."""
    if user.trial_plan:
        return user

    raise HTTPException(status_code=410, detail="Agency Trial is no longer available.")


def resolve_trial_status(user: models.User) -> TrialStatus:
    """Compute the current trial status for a user."""
    if user.trial_plan != "plan_agency_trial":
        return _empty_trial_status()

    now = datetime.now(timezone.utc)
    trial_ends_at = _coerce_utc(user.trial_ends_at)
    is_expired = trial_ends_at is not None and now >= trial_ends_at

    days_remaining = 0
    if trial_ends_at and not is_expired:
        delta = trial_ends_at - now
        days_remaining = max(0, delta.days)

    credits_remaining = max(0, int(user.credits or 0))
    audits_used = int(user.trial_audits_used or 0)
    audits_total = int(user.trial_max_audits or TRIAL_MAX_AUDITS)
    credits_total = int(user.trial_initial_credits or TRIAL_CREDITS)

    limit_reason = _resolve_limit_reason(
        is_expired=is_expired,
        credits_remaining=credits_remaining,
        audits_used=audits_used,
        audits_total=audits_total,
    )

    return TrialStatus(
        is_trial=True,
        trial_active=not is_expired and limit_reason is None,
        trial_expired=is_expired,
        trial_plan=user.trial_plan,
        trial_started_at=user.trial_started_at.isoformat() if user.trial_started_at else None,
        trial_ends_at=trial_ends_at.isoformat() if trial_ends_at else None,
        days_remaining=days_remaining,
        credits_remaining=credits_remaining,
        credits_total=credits_total,
        audits_used=audits_used,
        audits_total=audits_total,
        concierge_completed=bool(user.trial_concierge_completed),
        limits_reached=limit_reason is not None,
        limit_reason=limit_reason,
    )


def is_trial_user(user: models.User) -> bool:
    """Return True if user is on an agency trial (active or expired). Explorer is not a trial."""
    return user.trial_plan == "plan_agency_trial"


def is_explorer_user(user: models.User) -> bool:
    """Return True if user has been transitioned to the Explorer free tier."""
    return user.trial_plan == STARTER_PLAN


def is_trial_active(user: models.User) -> bool:
    """Return True only if the user's trial is active and within limits."""
    if user.trial_plan != "plan_agency_trial":
        return False
    status = resolve_trial_status(user)
    return status["trial_active"]


def has_paid_subscription(user: models.User) -> bool:
    """Return True if user has upgraded to a paid plan."""
    return bool(
        user.subscription
        and user.subscription.status == "active"
        and user.subscription.plan_type not in ("plan_agency_trial", STARTER_PLAN)
    )


def get_trial_plan_name(user: models.User) -> str | None:
    """Return the effective plan name for trial/plan_starter resolution."""
    if has_paid_subscription(user):
        return None  # paid plan takes precedence
    if user.trial_plan:
        return user.trial_plan
    return None


def enforce_trial_audit_limit(user: models.User) -> None:
    """Raise 402 if the trial user has exhausted their audit allowance.

    Should be called before starting an audit for trial users.
    Explorer users are not subject to trial limits (they use CAPABILITY_MATRIX limits).
    """
    if user.trial_plan != "plan_agency_trial" or has_paid_subscription(user):
        return

    status = resolve_trial_status(user)
    if status["trial_expired"]:
        raise HTTPException(
            status_code=402,
            detail="Your 14-day agency trial has expired. Please upgrade to a paid plan to continue.",
        )
    if status["audits_used"] >= status["audits_total"]:
        raise HTTPException(
            status_code=402,
            detail=(
                f"You have used all {status['audits_total']} scans included in your trial. "
                "Please upgrade to a paid plan for more scans."
            ),
        )


def increment_trial_audit_usage(db: Session, user: models.User) -> None:
    """Increment the trial audit counter after a successful audit."""
    if user.trial_plan != "plan_agency_trial" or has_paid_subscription(user):
        return
    user.trial_audits_used = (user.trial_audits_used or 0) + 1
    db.add(user)
    db.flush()


def mark_concierge_completed(db: Session, user: models.User) -> None:
    """Mark the concierge onboarding as completed for a trial user."""
    user.trial_concierge_completed = True
    db.add(user)
    db.flush()


def enforce_trial_feature(user: models.User, *, feature_key: str) -> None:
    """Block trial users from accessing gated features (e.g. CNAME).

    Raises 403 if the feature is not available on the trial plan.
    Explorer users are checked against Explorer capabilities, not trial capabilities.
    """
    if has_paid_subscription(user):
        return

    plan_key = user.trial_plan
    if not plan_key:
        return

    if plan_key == STARTER_PLAN:
        capabilities = get_plan_capabilities(STARTER_PLAN)
    elif plan_key == "plan_agency_trial":
        capabilities = get_plan_capabilities("plan_agency_trial")
    else:
        return

    if not capabilities.get(feature_key, False):
        raise HTTPException(
            status_code=403,
            detail=(
                "This feature is not available on your current plan. "
                "Please upgrade to unlock it."
            ),
        )


# ── Explorer transition ──────────────────────────────────────────────


def transition_expired_trial_to_explorer(db: Session, user: models.User) -> bool:
    """Transition an expired trial user to the Explorer free tier.

    Returns True if the transition was performed, False if skipped.
    Idempotent, already-transitioned users are skipped.
    """
    if user.trial_plan != "plan_agency_trial":
        return False
    if has_paid_subscription(user):
        return False

    trial_ends_at = _coerce_utc(user.trial_ends_at)
    if trial_ends_at is None:
        return False

    now = datetime.now(timezone.utc)
    if now < trial_ends_at:
        return False  # trial still active

    user.trial_plan = STARTER_PLAN
    user.credits = max(int(user.credits or 0), STARTER_MONTHLY_CREDITS)
    user.explorer_credits_refreshed_at = now
    db.add(user)
    db.flush()
    logger.info("Transitioned user %s from trial to Explorer plan", user.id)
    return True


def refresh_explorer_credits(db: Session, user: models.User) -> bool:
    """Refresh monthly credits for an Explorer user.

    Once 30 days have elapsed, ensure the wallet has at least the canonical
    Starter allocation. Larger balances are preserved until wallet buckets
    are available. Returns True when the refresh timestamp is advanced.
    """
    if user.trial_plan != STARTER_PLAN:
        return False
    if has_paid_subscription(user):
        return False

    now = datetime.now(timezone.utc)
    last_refresh = _coerce_utc(user.explorer_credits_refreshed_at)
    if last_refresh is None:
        # First refresh, set a non-destructive baseline.
        user.credits = max(int(user.credits or 0), STARTER_MONTHLY_CREDITS)
        user.explorer_credits_refreshed_at = now
        db.add(user)
        db.flush()
        return True

    next_refresh = last_refresh + timedelta(days=STARTER_CREDIT_REFRESH_INTERVAL_DAYS)
    if now < next_refresh:
        return False

    user.credits = max(int(user.credits or 0), STARTER_MONTHLY_CREDITS)
    user.explorer_credits_refreshed_at = now
    db.add(user)
    db.flush()
    logger.info("Refreshed Explorer credits for user %s", user.id)
    return True


def _resolve_limit_reason(
    *,
    is_expired: bool,
    credits_remaining: int,
    audits_used: int,
    audits_total: int,
) -> str | None:
    if is_expired:
        return "trial_expired"
    # Credits are internal soft limits (SIGV2-1024); an exhausted internal
    # balance no longer ends the trial or blocks audits.
    if audits_used >= audits_total:
        return "audits_exhausted"
    return None


def _empty_trial_status() -> TrialStatus:
    return TrialStatus(
        is_trial=False,
        trial_active=False,
        trial_expired=False,
        trial_plan=None,
        trial_started_at=None,
        trial_ends_at=None,
        days_remaining=0,
        credits_remaining=0,
        credits_total=0,
        audits_used=0,
        audits_total=0,
        concierge_completed=False,
        limits_reached=False,
        limit_reason=None,
    )
