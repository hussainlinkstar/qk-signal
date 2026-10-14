"""Customer-facing scan allowance (SIGV2-1024).

Customers see scans, not credits. Credits remain as internal soft limits for
cost accounting; this module is the single source of truth for the scan
allowance that customers are entitled to launch.

Contract
--------
- **Owner:** the individual ``User`` account launching the audit.
- **Counting unit:** one accepted audit job (``AuditJob`` row) that is
  positively declared as a scan the customer launched
  (``AuditJob.scan_origin == 'customer'``) equals one consumed scan.
- **Reset window:** rolling 30 days. ``reset_at`` is when the oldest counted
  scan leaves the window; it is ``None`` when nothing is consumed.
- **Billable events:** a scan is consumed at job *acceptance*. Successful,
  degraded and failed outcomes all count; a failure is not a free retry.
  Pre-scans do not consume scans (they carry their own internal cost).
  Sitemap-crawl child jobs consume one scan each, matching the previous
  per-URL internal credit charge; the dispatcher stops queuing when the
  allowance is exhausted. Scheduled and workflow-triggered audits count
  identically to manual launches because they create the same accepted
  ``AuditJob``. SIGV2-1137: the synchronous ``POST /api/v1/audit`` path counts
  identically for the same reason. It runs the audit inside the request instead
  of queuing it, but it is customer-reachable and produces a real audit, so it
  consumes the allowance and records the ``AuditJob`` row counted here rather
  than being metered some other way.
- **Retry dedupe:** duplicate launches for the same target are rejected
  upstream by ``audit_dedup_service`` before a job is accepted, so a retry
  never double-consumes.
- **Not billable (SIGV2-1129):** Signal's competitor benchmark refresh. It is
  work Signal chooses to do to populate a comparison the plan already includes,
  so it is never one of the customer's scans, whether a scheduled audit fanned
  it out or the workspace refresh endpoint triggered it. It is bounded by the
  tracked-competitor cap (``MAX_PROJECT_COMPETITORS``), not by the allowance.
  A competitor *lite audit the customer asks for* through ``POST /api/v1/audit``
  or the external API is a different thing: the customer launched it, so it is
  one of their scans and it is billed. Without that distinction, any caller
  entitled to competitor lite audits could set ``category`` on every request
  and never consume a scan.
- **Trial:** agency-trial users are governed by
  ``trial_service.enforce_trial_audit_limit`` (one-time grant), not by this
  rolling-window allowance.
- **Unlimited:** ``max_audits == -1`` plan capability means no cap.

Classification
--------------
The count is positive, never a subtraction (SIGV2-1121's shape, applied to
billing). A job is billed only when its write path declared it as the
customer's own scan. A job that declares nothing stays ``NULL`` and is not
billed, so an undeclared write path under-counts instead of charging a
customer for automation. That direction is chosen deliberately: the allowance
is the customer-facing contract, so giving a scan away is recoverable while
billing one that was never requested is not. It is not silent either, because
every unclassified job in the window is logged by
``_warn_about_unclassified_jobs``.

Atomicity
---------
``consume_scan_allowance`` takes a ``FOR UPDATE`` lock on the user row and
counts existing jobs inside the same transaction that inserts the new
``AuditJob``. Two concurrent launches for the final slot therefore
serialise on the user row and exactly one wins.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from models import SCAN_ORIGIN_CUSTOMER
from services.trial_service import has_paid_subscription

logger = logging.getLogger(__name__)

SCAN_ALLOWANCE_WINDOW_DAYS = 30


@dataclass(frozen=True)
class ScanAllowanceSnapshot:
    limit: int | None  # None means unlimited
    scans_used: int
    scans_remaining: int | None
    reset_at: str | None


def resolve_scan_limit(user: models.User | None) -> int | None:
    """Return the plan's scan cap, or ``None`` for unlimited.

    Agency-trial users return ``None`` here: their allowance is the one-time
    grant enforced by ``trial_service.enforce_trial_audit_limit``.
    """
    if user is None:
        return None
    if user.trial_plan and not has_paid_subscription(user):
        return None
    from services.audit_helpers import resolve_plan_capabilities

    capabilities = resolve_plan_capabilities(user)
    max_audits = capabilities.get("max_audits")
    if not isinstance(max_audits, int) or isinstance(max_audits, bool):
        return None
    if max_audits < 0:
        return None
    return max_audits


def _window_start(now: datetime) -> datetime:
    return now - timedelta(days=SCAN_ALLOWANCE_WINDOW_DAYS)


def _window_job_filter(user_id: int, window_start: datetime):
    return (
        models.AuditJob.user_id == user_id,
        models.AuditJob.created_at >= window_start,
    )


def customer_scan_clause():
    """Require positive proof that a job is a scan the customer launched."""
    return models.AuditJob.scan_origin == SCAN_ORIGIN_CUSTOMER


def unclassified_scan_clause():
    """Match a job whose write path declared no origin at all."""
    return models.AuditJob.scan_origin.is_(None)


def _billable_job_filter(user_id: int, window_start: datetime):
    """Jobs in the window that are positively the customer's own scan.

    SIGV2-1129: the third clause is the fix. Without it the filter billed every
    job attributed to the user, including the competitor benchmarks a scheduled
    audit fans out on the customer's behalf, so a single schedule with five
    tracked competitors took six scans out of a rolling allowance the customer
    never spent.
    """
    return (
        *_window_job_filter(user_id, window_start),
        customer_scan_clause(),
    )


def _warn_about_unclassified_jobs(db: Session, user_id: int, window_start: datetime) -> int:
    """Log, and return, the jobs in the window that declared no origin.

    They are not billed. An undeclared job means a write path that creates
    ``AuditJob`` rows without stating whose scan it is, which is a defect to
    fix at that write path, not something to resolve by guessing here.
    """
    unclassified = (
        db.query(func.count(models.AuditJob.id))
        .filter(*_window_job_filter(user_id, window_start), unclassified_scan_clause())
        .scalar()
        or 0
    )
    unclassified = int(unclassified)
    if unclassified:
        logger.warning(
            "Scan allowance for user %s met %s audit job(s) in the window with no declared "
            "scan origin; they are not billed as the customer's scans. Declare the origin at "
            "the write path that created them.",
            user_id,
            unclassified,
        )
    return unclassified


def scan_allowance_snapshot(
    db: Session,
    user: models.User,
    *,
    now: datetime | None = None,
) -> ScanAllowanceSnapshot:
    now = now or datetime.now(timezone.utc)
    limit = resolve_scan_limit(user)
    scans_used = (
        db.query(func.count(models.AuditJob.id))
        .filter(*_billable_job_filter(user.id, _window_start(now)))
        .scalar()
        or 0
    )
    scans_used = int(scans_used)
    _warn_about_unclassified_jobs(db, user.id, _window_start(now))

    reset_at: str | None = None
    if scans_used > 0:
        oldest = (
            db.query(func.min(models.AuditJob.created_at))
            .filter(*_billable_job_filter(user.id, _window_start(now)))
            .scalar()
        )
        if oldest is not None:
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            reset_at = (oldest + timedelta(days=SCAN_ALLOWANCE_WINDOW_DAYS)).isoformat()

    remaining = None if limit is None else max(0, limit - scans_used)
    return ScanAllowanceSnapshot(
        limit=limit,
        scans_used=scans_used,
        scans_remaining=remaining,
        reset_at=reset_at,
    )


def consume_scan_allowance(
    db: Session,
    user: models.User,
    *,
    now: datetime | None = None,
) -> ScanAllowanceSnapshot:
    """Enforce the scan allowance atomically.

    Locks the user row FOR UPDATE, counts billable scans in the rolling
    window, and raises 402 when the allowance is exhausted. The caller must
    insert the new ``AuditJob`` in the same transaction so the count and the
    insert commit together.
    """
    now = now or datetime.now(timezone.utc)
    limit = resolve_scan_limit(user)
    if limit is None:
        return scan_allowance_snapshot(db, user, now=now)

    locked_user = db.query(models.User).filter(models.User.id == user.id).with_for_update().first()
    if locked_user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    snapshot = scan_allowance_snapshot(db, locked_user, now=now)
    if snapshot.scans_used >= limit:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Scan limit reached ({snapshot.scans_used}/{limit} scans in the "
                "current 30-day window). Please upgrade your plan for more scans."
            ),
        )
    return snapshot
