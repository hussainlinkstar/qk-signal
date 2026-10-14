"""Credit balance reconciliation service.

Compares the running credit counter on User.credits with the
computed sum of UserCreditAdjustment.delta for each user.
Discrepancies are logged and returned.

Note: Trial and plan_starter users receive credits via direct mutation
(``trial_service.py``) without creating ``UserCreditAdjustment``
records.  These users are excluded from reconciliation to avoid
false-positive drift reports.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

# trial_plan values that grant credits outside the adjustment ledger.
_UNTRACKED_TRIAL_PLANS = {"plan_agency_trial", "plan_starter"}


def _user_has_untracked_credits(user) -> bool:
    """Return True if the user has credits granted outside the ledger."""
    return bool(getattr(user, "trial_plan", None) in _UNTRACKED_TRIAL_PLANS)


def reconcile_user_credits(db: Session, user_id: int) -> dict | None:
    """Compare the ledger sum to User.credits for a single user.

    Returns ``None`` when the balances match (or no adjustments exist).
    Returns a discrepancy dict when they diverge.
    Skips users whose credits are partially managed outside the ledger
    (trial / plan_starter plans).
    """
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if user is None:
        return None

    # Skip users with non-ledgered credit grants to avoid false positives.
    if _user_has_untracked_credits(user):
        return None

    row = (
        db.query(func.sum(models.UserCreditAdjustment.delta))
        .filter(models.UserCreditAdjustment.user_id == user_id)
        .scalar()
    )

    # No adjustment records at all -- nothing to reconcile against.
    if row is None:
        return None

    expected = int(row)
    actual = int(user.credits)

    if actual == expected:
        return None

    return {
        "user_id": user_id,
        "expected": expected,
        "actual": actual,
        "drift": actual - expected,
    }


def reconcile_all_credits(db: Session, *, limit: int = 500) -> tuple[list[dict], int]:
    """Check all users who have at least one credit adjustment.

    Returns ``(discrepancies, users_checked)``, discrepancies is a list
    of dicts (empty means all good), and *users_checked* is the actual
    number of users that were reconciled (after filtering).
    The *limit* parameter caps how many users to examine per run.
    """
    user_ids = db.query(models.UserCreditAdjustment.user_id).distinct().limit(limit).all()

    discrepancies: list[dict] = []
    checked = 0
    for (uid,) in user_ids:
        result = reconcile_user_credits(db, uid)
        # result is None for balanced, not-found, or skipped (trial/plan_starter)
        checked += 1
        if result is not None:
            discrepancies.append(result)

    return discrepancies, checked


def run_credit_reconciliation_sweep(db: Session) -> dict:
    """Run a full reconciliation sweep, log results, and return a summary."""
    discrepancies, users_checked = reconcile_all_credits(db)

    checked_at = datetime.now(timezone.utc).isoformat()

    if discrepancies:
        logger.warning(
            "Credit reconciliation found %d discrepancies out of %d users checked",
            len(discrepancies),
            users_checked,
        )
        for d in discrepancies:
            logger.warning(
                "Credit drift: user_id=%s expected=%s actual=%s drift=%s",
                d["user_id"],
                d["expected"],
                d["actual"],
                d["drift"],
            )
    else:
        logger.info(
            "Credit reconciliation completed: %d users checked, no discrepancies",
            users_checked,
        )

    return {
        "users_checked": users_checked,
        "discrepancies": discrepancies,
        "checked_at": checked_at,
    }
