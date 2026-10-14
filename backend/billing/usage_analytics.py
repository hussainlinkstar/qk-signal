"""Usage analytics: scan aggregation, burn-rate calculation, projection logic.

The customer-facing allowance is scans (SIGV2-1024). Daily scan history,
rolling burn rates, depletion projection and plan recommendation are all
denominated in scans. Credit-based aggregation remains for internal cost
monitoring.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from services.scan_allowance_service import ScanAllowanceSnapshot

from sqlalchemy import func, case
from sqlalchemy.orm import Session

import models
from app.config.plans import get_plan_capabilities, resolve_plan_alias

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Daily usage aggregation
# ---------------------------------------------------------------------------


def aggregate_daily_usage(
    db: Session,
    user_id: int,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return per-day credit usage (consumption only, not grants).

    Returns a list of ``{date, credits_used, credits_granted,
    deduction_count}`` dicts ordered chronologically.  Days with zero usage
    are included so callers have no gaps.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            func.date(models.UserCreditAdjustment.created_at).label("day"),
            func.sum(
                case(
                    (
                        models.UserCreditAdjustment.delta < 0,
                        func.abs(models.UserCreditAdjustment.delta),
                    ),
                    else_=0,
                )
            ).label("credits_used"),
            func.sum(
                case(
                    (models.UserCreditAdjustment.delta > 0, models.UserCreditAdjustment.delta),
                    else_=0,
                )
            ).label("credits_granted"),
            func.count(
                case(
                    (models.UserCreditAdjustment.delta < 0, 1),
                    else_=None,
                )
            ).label("deduction_count"),
        )
        .filter(
            models.UserCreditAdjustment.user_id == user_id,
            models.UserCreditAdjustment.created_at >= cutoff,
        )
        .group_by(func.date(models.UserCreditAdjustment.created_at))
        .order_by(func.date(models.UserCreditAdjustment.created_at))
        .all()
    )

    # Build a lookup for days with data
    usage_by_day: dict[str, dict] = {}
    for row in rows:
        day_str = str(row.day)
        usage_by_day[day_str] = {
            "date": day_str,
            "credits_used": int(row.credits_used or 0),
            "credits_granted": int(row.credits_granted or 0),
            "deduction_count": int(row.deduction_count or 0),
        }

    # Fill in empty days
    result = []
    current = cutoff.date()
    today = datetime.now(timezone.utc).date()
    while current <= today:
        day_str = current.isoformat()
        if day_str in usage_by_day:
            result.append(usage_by_day[day_str])
        else:
            result.append(
                {
                    "date": day_str,
                    "credits_used": 0,
                    "credits_granted": 0,
                    "deduction_count": 0,
                }
            )
        current += timedelta(days=1)

    return result


# ---------------------------------------------------------------------------
#  Burn-rate calculation
# ---------------------------------------------------------------------------


def calculate_burn_rate(
    daily_usage: list[dict],
    window_days: int = 7,
    *,
    key: str = "credits_used",
) -> float:
    """Calculate rolling-average daily burn rate for the given metric.

    Only considers days with actual usage in the window (to avoid dilution
    from weekends/holidays), but caps at ``window_days`` to prevent
    single-day spikes from inflating the rate.
    """
    if not daily_usage:
        return 0.0

    recent = daily_usage[-window_days:]
    total_used = sum(d[key] for d in recent)
    active_days = sum(1 for d in recent if d[key] > 0)

    if active_days == 0:
        return 0.0

    # Use the full window for averaging (more conservative) rather than
    # only active days.  This prevents artificially high projections when
    # someone only used credits on 1 of the last 7 days.
    return round(total_used / len(recent), 2)


def aggregate_daily_scans(
    db: Session,
    user_id: int,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return per-day scan counts (accepted audit jobs).

    Returns a list of ``{date, scans_used}`` dicts ordered chronologically.
    Days with zero scans are included so the chart has no gaps.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            func.date(models.AuditJob.created_at).label("day"),
            func.count(models.AuditJob.id).label("scans"),
        )
        .filter(
            models.AuditJob.user_id == user_id,
            models.AuditJob.created_at >= cutoff,
        )
        .group_by(func.date(models.AuditJob.created_at))
        .order_by(func.date(models.AuditJob.created_at))
        .all()
    )

    scans_by_day = {str(row.day): int(row.scans or 0) for row in rows}

    result = []
    current = cutoff.date()
    today = datetime.now(timezone.utc).date()
    while current <= today:
        day_str = current.isoformat()
        result.append({"date": day_str, "scans_used": scans_by_day.get(day_str, 0)})
        current += timedelta(days=1)

    return result


# ---------------------------------------------------------------------------
#  Usage breakdown by feature/provider
# ---------------------------------------------------------------------------


def get_usage_breakdown(
    db: Session,
    user_id: int,
    days: int = 30,
) -> dict[str, Any]:
    """Return credit usage sliced by feature_key and provider."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = (
        db.query(
            models.AIEconomicsLedgerEntry.feature_key,
            models.AIEconomicsLedgerEntry.provider,
            models.AIEconomicsLedgerEntry.tier_class,
            func.sum(models.AIEconomicsLedgerEntry.credits_charged).label("total_credits"),
            func.count(models.AIEconomicsLedgerEntry.id).label("request_count"),
        )
        .filter(
            models.AIEconomicsLedgerEntry.user_id == user_id,
            models.AIEconomicsLedgerEntry.created_at >= cutoff,
        )
        .group_by(
            models.AIEconomicsLedgerEntry.feature_key,
            models.AIEconomicsLedgerEntry.provider,
            models.AIEconomicsLedgerEntry.tier_class,
        )
        .all()
    )

    by_feature: dict[str, int] = defaultdict(int)
    by_provider: dict[str, int] = defaultdict(int)
    by_tier: dict[str, int] = defaultdict(int)

    for row in rows:
        credits = int(row.total_credits or 0)
        by_feature[row.feature_key or "unknown"] += credits
        by_provider[row.provider or "unknown"] += credits
        by_tier[row.tier_class or "unknown"] += credits

    return {
        "by_feature": dict(by_feature),
        "by_provider": dict(by_provider),
        "by_tier": dict(by_tier),
    }


# ---------------------------------------------------------------------------
#  Projection helpers
# ---------------------------------------------------------------------------


def get_renewal_date(user: models.User) -> datetime | None:
    """Return the next subscription renewal date, or None."""
    sub = user.subscription
    if sub and sub.status in ("active", "trialing") and sub.current_period_end:
        return (
            sub.current_period_end.replace(tzinfo=timezone.utc)
            if sub.current_period_end.tzinfo is None
            else sub.current_period_end
        )
    return None


def get_monthly_allocation(user: models.User) -> int:
    """Return the monthly credit allocation for the user's current plan."""
    plan = resolve_current_plan(user)
    caps = get_plan_capabilities(plan)
    return int(caps.get("credits_per_month", 0))


def resolve_current_plan(user: models.User) -> str:
    """Resolve the user's effective plan name."""
    sub = user.subscription
    if sub and sub.status in ("active", "trialing") and sub.plan_type:
        return resolve_plan_alias(sub.plan_type)
    if (
        user.trial_plan
        and user.trial_ends_at
        and user.trial_ends_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
    ):
        return resolve_plan_alias(user.trial_plan)
    return "plan_starter"


# SIGV2-1306: a projection needs history before it is worth publishing.
#
# QA saw four figures on the billing page, no two of which agreed: one scan
# left out of two hundred, +367% against a thirty-day average on an account
# days old, about 1,421 days until depletion, and one of one sites at the plan
# limit while two projects existed.
#
# The arithmetic was right and the output was meaningless. One scan in seven
# days is a burn of 0.14 a day, and 199 remaining divided by that is 1,421
# days, which is where the number came from. A rate derived from a single data
# point is not a rate, and dividing by it produces a date four years out that
# the product then states as a fact.
#
# This is the same rule the rest of Signal already follows for an unmeasured
# score: below the evidence it needs, a surface says so rather than publishing
# a number. Seven days is the shortest window a 7-day burn rate can claim to
# describe.
#
# The measure is the span since the first real usage, NOT the number of rows.
# `aggregate_daily_scans` always returns one row per day across the whole
# window, padded with zeros for days before the account existed, so a
# three-day-old account arrives here with 31 rows. Counting rows let the
# reported 1,421-day projection straight through the first version of this
# guard, which is a good argument for testing against the shape production
# actually sends rather than a convenient one.
MIN_PROJECTION_HISTORY_DAYS = 7


def observed_history_days(daily_usage: list[dict], *, key: str = "credits_used") -> int:
    """How long there has been something to observe, in days.

    The span from the first day carrying usage to the end of the window. Zero
    when nothing has been used, because a run of empty days is not history of
    anything: it is the absence of it.
    """
    for index, day in enumerate(daily_usage):
        if day.get(key, 0) > 0:
            return len(daily_usage) - index
    return 0


PROJECTION_REASON_NO_HISTORY = "insufficient_history"
PROJECTION_REASON_NO_USAGE = "no_usage_yet"
PROJECTION_REASON_UNCAPPED = "allowance_uncapped"


def calculate_projections(
    daily_usage: list[dict],
    remaining: int | None,
    renewal_date: datetime | None,
    *,
    key: str = "credits_used",
) -> dict[str, Any]:
    """Project depletion date and overage risk for the given metric.

    ``remaining`` is ``None`` when the allowance is uncapped, in which case
    no depletion is projected.

    A projection is withheld, with ``projection_reason`` saying why, when
    there is not enough history behind it to mean anything (SIGV2-1306).
    """
    burn_7d = calculate_burn_rate(daily_usage, window_days=7, key=key)
    burn_30d = calculate_burn_rate(daily_usage, window_days=30, key=key)

    # Use 7-day burn rate for projections (more recent = more relevant)
    active_burn = burn_7d if burn_7d > 0 else burn_30d

    days_until_depletion: float | None = None
    depletion_date: str | None = None
    will_exhaust_before_renewal = False
    projected_overage = 0

    observed_days = observed_history_days(daily_usage, key=key)
    projection_reason: str | None = None
    if remaining is None:
        projection_reason = PROJECTION_REASON_UNCAPPED
    elif observed_days < MIN_PROJECTION_HISTORY_DAYS:
        projection_reason = PROJECTION_REASON_NO_HISTORY
    elif active_burn <= 0:
        projection_reason = PROJECTION_REASON_NO_USAGE

    if projection_reason is None and active_burn > 0 and remaining is not None:
        days_until_depletion = round(remaining / active_burn, 1)
        depletion_dt = datetime.now(timezone.utc) + timedelta(days=days_until_depletion)
        depletion_date = depletion_dt.date().isoformat()

        if renewal_date:
            days_to_renewal = (renewal_date - datetime.now(timezone.utc)).total_seconds() / 86400
            will_exhaust_before_renewal = days_until_depletion < days_to_renewal
            if will_exhaust_before_renewal:
                projected_overage = int((days_to_renewal - days_until_depletion) * active_burn)

    return {
        "burn_rate_7d": burn_7d,
        "burn_rate_30d": burn_30d,
        "days_until_depletion": days_until_depletion,
        "depletion_date": depletion_date,
        "will_exhaust_before_renewal": will_exhaust_before_renewal,
        "projected_overage": projected_overage,
        # None when a projection was published; otherwise why it was not, so
        # the surface can say that instead of printing a figure it cannot
        # stand behind (SIGV2-1306).
        "projection_reason": projection_reason,
        "observed_days": observed_days,
    }


# ---------------------------------------------------------------------------
#  Low-credit warning
# ---------------------------------------------------------------------------

WARNING_THRESHOLD_PCT = 0.20


def should_show_scan_warning(
    user: models.User,
    scans: "ScanAllowanceSnapshot",
) -> dict[str, Any]:
    """Check if the user should see a low-allowance warning.

    The customer-facing allowance is scans (SIGV2-1024); the comparison is
    ``scans_remaining / limit``. Uncapped plans (``limit`` is ``None`` or
    ``<= 0``) never warn.

    Returns a dict with ``show_warning``, ``remaining``, ``allowance``,
    ``pct_remaining`` and ``unit`` (always ``"scans"``).
    """
    if scans.limit is not None and scans.limit > 0:
        remaining = scans.scans_remaining or 0
        allowance = scans.limit
        pct = remaining / allowance
        return {
            "show_warning": pct < WARNING_THRESHOLD_PCT,
            "remaining": remaining,
            "allowance": allowance,
            "pct_remaining": round(pct * 100, 1),
            "unit": "scans",
        }

    return {
        "show_warning": False,
        "remaining": scans.scans_remaining,
        "allowance": scans.limit,
        "pct_remaining": None,
        "unit": "scans",
    }


# ---------------------------------------------------------------------------
#  Plan recommendation
# ---------------------------------------------------------------------------

PLAN_ORDER = [
    "plan_starter",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
]


def get_next_plan_up(current_plan: str) -> str | None:
    """Return the next plan tier above the current one."""
    try:
        idx = PLAN_ORDER.index(current_plan)
    except ValueError:
        return None
    if idx + 1 < len(PLAN_ORDER):
        return PLAN_ORDER[idx + 1]
    return None


def is_at_site_limit(site_count: int, max_sites: int) -> bool:
    """Whether a workspace has used up its plan's site allowance.

    `max_sites == -1` is the "unlimited" sentinel (see
    ``app/config/plans.py``: "Maximum tracked sites (-1 = unlimited)"). Without
    this guard, `site_count >= max_sites` is always true once `site_count >= 0`,
    so every unlimited-site plan (Executive) was permanently
    flagged as "at the site limit" (SIGNAL-1001).
    """
    return max_sites > 0 and site_count >= max_sites


def build_plan_recommendation(
    db: Session,
    user: models.User,
    daily_scans: list[dict],
) -> dict[str, Any] | None:
    """Suggest an optimal plan based on actual scan usage patterns.

    Returns None if no recommendation is warranted.
    """
    current_plan = resolve_current_plan(user)
    current_caps = get_plan_capabilities(current_plan)
    scan_limit = int(current_caps.get("max_audits", 0))

    burn_30d = calculate_burn_rate(daily_scans, window_days=30, key="scans_used")
    projected_monthly = burn_30d * 30

    # Count user sites
    site_count = (
        db.query(func.count(models.Site.id))
        .filter(
            models.Site.user_id == user.id,
        )
        .scalar()
        or 0
    )

    max_sites = int(current_caps.get("max_sites", 1))

    hitting_scan_limit = scan_limit > 0 and projected_monthly > scan_limit * 0.85
    hitting_site_limit = is_at_site_limit(site_count, max_sites)

    if not hitting_scan_limit and not hitting_site_limit:
        return None

    next_plan = get_next_plan_up(current_plan)
    if not next_plan:
        return None

    reasons = []
    if hitting_scan_limit:
        reasons.append(
            f"You're on pace for ~{int(projected_monthly)} scans/month ({int(projected_monthly / scan_limit * 100)}% of your {scan_limit} scan allowance)"
        )
    if hitting_site_limit:
        reasons.append(f"You have {site_count}/{max_sites} sites, at your plan limit")

    from app.config.plans import PLAN_PRESENTATION

    next_label = PLAN_PRESENTATION.get(next_plan, {}).get(
        "label", next_plan.replace("_", " ").title()
    )

    return {
        "recommended_plan": next_plan,
        "recommended_plan_label": next_label,
        "reasons": reasons,
        "message": f"Based on your usage, {next_label} would give you more room to grow.",
    }


# ---------------------------------------------------------------------------
#  Full analytics response builder
# ---------------------------------------------------------------------------


def build_usage_analytics(
    db: Session,
    user: models.User,
    days: int = 30,
) -> dict[str, Any]:
    """Compose the customer-facing usage analytics response, in scans."""
    from services.scan_allowance_service import scan_allowance_snapshot

    daily_scans = aggregate_daily_scans(db, user.id, days=days)
    scan_snapshot = scan_allowance_snapshot(db, user)
    renewal_date = get_renewal_date(user)

    projections = calculate_projections(
        daily_scans,
        scan_snapshot.scans_remaining,
        renewal_date,
        key="scans_used",
    )

    warning = should_show_scan_warning(user, scan_snapshot)
    recommendation = build_plan_recommendation(db, user, daily_scans)

    return {
        "daily_usage": daily_scans,
        "scans_used": scan_snapshot.scans_used,
        "scans_remaining": scan_snapshot.scans_remaining,
        "scan_allowance": scan_snapshot.limit,
        "reset_at": scan_snapshot.reset_at,
        "renewal_date": renewal_date.isoformat() if renewal_date else None,
        "current_plan": resolve_current_plan(user),
        **projections,
        "warning": warning,
        "recommendation": recommendation,
    }
