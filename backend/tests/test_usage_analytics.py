"""Tests for Phase 5 — Usage Intelligence UX.

Covers:
- billing/usage_analytics.py: aggregation, burn-rate, projections, plan recommendation
- billing/router.py: GET /billing/usage-analytics, GET /billing/plan-recommendation, GET /billing/scan-warning
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DISABLE_TRACING", "1")
os.environ.setdefault("DATABASE_URL", "postgresql://user:password@localhost:5432/testdb")
os.environ.setdefault("SSM_ENABLED", "0")


from billing.usage_analytics import (  # noqa: E402
    MIN_PROJECTION_HISTORY_DAYS,
    PROJECTION_REASON_NO_HISTORY,
    PROJECTION_REASON_NO_USAGE,
    PROJECTION_REASON_UNCAPPED,
    calculate_burn_rate,
    calculate_projections,
    get_monthly_allocation,
    get_renewal_date,
    observed_history_days,
    is_at_site_limit,
    resolve_current_plan,
    should_show_scan_warning,
)
from services.scan_allowance_service import ScanAllowanceSnapshot  # noqa: E402


def _scans(limit, remaining, used=0):
    return ScanAllowanceSnapshot(
        limit=limit, scans_used=used, scans_remaining=remaining, reset_at=None
    )


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------


def _make_user(
    *,
    credits=100,
    plan_type="plan_specialist",
    status="active",
    period_end=None,
    trial_plan=None,
    trial_ends_at=None,
):
    sub = None
    if plan_type and status:
        sub = SimpleNamespace(
            plan_type=plan_type,
            status=status,
            current_period_end=period_end or (datetime.now(timezone.utc) + timedelta(days=15)),
            billing_interval="month",
        )
    return SimpleNamespace(
        id=1,
        credits=credits,
        subscription=sub,
        trial_plan=trial_plan,
        trial_ends_at=trial_ends_at,
        credit_commitment=None,
    )


def _daily_usage(days, credits_per_day=10, start_offset=0):
    """Generate fake daily usage data."""
    result = []
    today = datetime.now(timezone.utc).date()
    for i in range(days):
        d = today - timedelta(days=days - 1 - i + start_offset)
        result.append(
            {
                "date": d.isoformat(),
                "credits_used": credits_per_day,
                "credits_granted": 0,
                "deduction_count": credits_per_day // 2 if credits_per_day > 0 else 0,
            }
        )
    return result


# ---------------------------------------------------------------------------
#  calculate_burn_rate
# ---------------------------------------------------------------------------


class TestCalculateBurnRate:
    def test_empty_data(self):
        assert calculate_burn_rate([]) == 0.0

    def test_constant_usage(self):
        usage = _daily_usage(7, credits_per_day=10)
        rate = calculate_burn_rate(usage, window_days=7)
        assert rate == 10.0

    def test_window_truncation(self):
        """Only uses last `window_days` entries."""
        usage = _daily_usage(30, credits_per_day=20)
        rate_7 = calculate_burn_rate(usage, window_days=7)
        assert rate_7 == 20.0

    def test_zero_usage(self):
        usage = _daily_usage(7, credits_per_day=0)
        assert calculate_burn_rate(usage, window_days=7) == 0.0

    def test_mixed_usage(self):
        """Average is over the full window, not just active days."""
        usage = [
            {"date": "2026-03-01", "credits_used": 70, "credits_granted": 0, "deduction_count": 5},
            {"date": "2026-03-02", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
            {"date": "2026-03-03", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
            {"date": "2026-03-04", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
            {"date": "2026-03-05", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
            {"date": "2026-03-06", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
            {"date": "2026-03-07", "credits_used": 0, "credits_granted": 0, "deduction_count": 0},
        ]
        rate = calculate_burn_rate(usage, window_days=7)
        assert rate == 10.0  # 70 / 7 days


# ---------------------------------------------------------------------------
#  calculate_projections
# ---------------------------------------------------------------------------


class TestCalculateProjections:
    def test_no_usage(self):
        usage = _daily_usage(7, credits_per_day=0)
        result = calculate_projections(usage, 100, None)
        assert result["days_until_depletion"] is None
        assert result["will_exhaust_before_renewal"] is False

    def test_basic_projection(self):
        usage = _daily_usage(7, credits_per_day=10)
        result = calculate_projections(
            usage,
            remaining=100,
            renewal_date=datetime.now(timezone.utc) + timedelta(days=30),
        )
        assert result["burn_rate_7d"] == 10.0
        assert result["days_until_depletion"] == 10.0
        assert result["will_exhaust_before_renewal"] is True
        assert result["projected_overage"] > 0

    def test_no_exhaustion_before_renewal(self):
        usage = _daily_usage(7, credits_per_day=1)
        result = calculate_projections(
            usage,
            remaining=100,
            renewal_date=datetime.now(timezone.utc) + timedelta(days=5),
        )
        assert result["will_exhaust_before_renewal"] is False
        assert result["projected_overage"] == 0


# ---------------------------------------------------------------------------
#  resolve_current_plan
# ---------------------------------------------------------------------------


class TestResolveCurrentPlan:
    def test_active_subscription(self):
        user = _make_user(plan_type="plan_specialist", status="active")
        assert resolve_current_plan(user) == "plan_specialist"

    def test_no_subscription_defaults_explorer(self):
        user = _make_user(plan_type=None, status=None)
        assert resolve_current_plan(user) == "plan_starter"

    def test_trial_plan(self):
        user = _make_user(
            plan_type=None,
            status=None,
            trial_plan="plan_specialist",
            trial_ends_at=datetime.now(timezone.utc) + timedelta(days=5),
        )
        assert resolve_current_plan(user) == "plan_specialist"


# ---------------------------------------------------------------------------
#  should_show_scan_warning
# ---------------------------------------------------------------------------


class TestShouldShowCreditWarning:
    def test_low_scans_triggers_warning(self):
        user = _make_user(credits=10, plan_type="plan_specialist")
        result = should_show_scan_warning(user, _scans(limit=800, remaining=10, used=790))
        assert result["show_warning"] is True
        assert result["unit"] == "scans"
        assert result["pct_remaining"] == 1.2  # 10/800, round half to even

    def test_sufficient_scans_no_warning(self):
        user = _make_user(credits=1000, plan_type="plan_specialist")
        result = should_show_scan_warning(user, _scans(limit=800, remaining=800))
        assert result["show_warning"] is False

    def test_upgrade_leaves_wallet_low_but_scans_full_no_warning(self):
        """SIGV2-1093: after a plan upgrade, ``user.credits`` stays at its
        pre-upgrade balance but the scan allowance reflects the new plan.
        The warning must read the scan allowance, not the legacy wallet."""
        user = _make_user(credits=5, plan_type="plan_standard")
        result = should_show_scan_warning(user, _scans(limit=200, remaining=199, used=1))
        assert result["show_warning"] is False
        assert result["unit"] == "scans"

    def test_no_scans_remaining_triggers_warning(self):
        user = _make_user(credits=0, plan_type=None, status=None)
        result = should_show_scan_warning(user, _scans(limit=1, remaining=0, used=1))
        assert result["show_warning"] is True
        assert result["pct_remaining"] == 0.0

    def test_uncapped_scans_never_warn(self):
        """Uncapped plans (snapshot limit is None) have no allowance to
        measure, so the warning never shows."""
        user = _make_user(credits=0, plan_type="plan_executive")
        result = should_show_scan_warning(user, _scans(limit=None, remaining=None))
        assert result["show_warning"] is False
        assert result["unit"] == "scans"
        assert result["pct_remaining"] is None

    def test_trial_uncapped_scans_never_warn(self):
        """Trial and unlimited-scan accounts never show a low-allowance
        warning from this check."""
        user = _make_user(credits=0, plan_type=None, status=None)
        result = should_show_scan_warning(user, _scans(limit=None, remaining=None))
        assert result["show_warning"] is False
        assert result["unit"] == "scans"


# ---------------------------------------------------------------------------
#  get_monthly_allocation / get_renewal_date
# ---------------------------------------------------------------------------


class TestPlanHelpers:
    def test_monthly_allocation_synapse(self):
        user = _make_user(plan_type="plan_specialist")
        assert get_monthly_allocation(user) == 3200

    def test_monthly_allocation_plan_standard(self):
        user = _make_user(plan_type="plan_standard")
        assert get_monthly_allocation(user) == 800

    def test_renewal_date_active(self):
        future = datetime.now(timezone.utc) + timedelta(days=15)
        user = _make_user(period_end=future)
        assert get_renewal_date(user) is not None
        assert abs((get_renewal_date(user) - future).total_seconds()) < 1

    def test_renewal_date_no_sub(self):
        user = _make_user(plan_type=None, status=None)
        assert get_renewal_date(user) is None


class TestIsAtSiteLimit:
    """SIGNAL-1001: unlimited-site plans (max_sites == -1) were permanently
    flagged as 'at the site limit' because `site_count >= max_sites` is always
    true once max_sites is negative."""

    def test_unlimited_plan_never_at_limit(self):
        assert is_at_site_limit(site_count=1, max_sites=-1) is False
        assert is_at_site_limit(site_count=1000, max_sites=-1) is False

    def test_finite_plan_under_limit(self):
        assert is_at_site_limit(site_count=2, max_sites=10) is False

    def test_finite_plan_at_limit(self):
        assert is_at_site_limit(site_count=10, max_sites=10) is True

    def test_finite_plan_over_limit(self):
        assert is_at_site_limit(site_count=11, max_sites=10) is True

    def test_zero_max_sites_treated_as_no_limit(self):
        # Defensive: an unexpected 0 should not report "at limit" for a
        # workspace with zero sites either.
        assert is_at_site_limit(site_count=0, max_sites=0) is False


# ---------------------------------------------------------------------------
# SIGV2-1306. QA saw four figures on the billing page, no two of which agreed:
# one scan left out of two hundred, +367% against a thirty-day average on an
# account days old, about 1,421 days until depletion, and one of one sites at
# the plan limit while two projects existed.
#
# The arithmetic was right and the output was meaningless. These tests pin the
# rule that replaces it: a projection needs history behind it, and below that
# the surface says so rather than publishing a number.
# ---------------------------------------------------------------------------


def _padded_window(*, scans_on_day=None, used=0, window=31):
    """The shape `aggregate_daily_scans` actually returns.

    One row per day across the whole window, padded with zeros for days before
    the account existed. `scans_on_day` counts back from the end, so
    `scans_on_day=3` means the usage was three days ago.

    The first version of this guard counted rows, and every account has a full
    window of them, so the reported projection went straight through it. The
    fixtures here are padded for exactly that reason: a convenient shape hid
    the defect the ticket is about.
    """
    rows = [{"credits_used": 0} for _ in range(window)]
    if scans_on_day is not None and used:
        rows[window - scans_on_day] = {"credits_used": used}
    return rows


def _days(count, used_on_first=0):
    """`count` days, with optional usage on day one only. Unpadded."""
    return [{"credits_used": used_on_first if index == 0 else 0} for index in range(count)]


def test_the_reported_1421_day_projection_is_withheld():
    # The exact shape QA hit, in the form production sends it: a full padded
    # window, one scan three days ago, 199 left. A burn of 1/7 is 0.14 a day
    # and 199 / 0.14 is 1,421 days, which is the figure on the screenshot.
    result = calculate_projections(
        _padded_window(scans_on_day=3, used=1), remaining=199, renewal_date=None
    )

    assert result["days_until_depletion"] is None
    assert result["depletion_date"] is None
    assert result["projection_reason"] == PROJECTION_REASON_NO_HISTORY
    # Three days of history, not the 31 rows it arrived as.
    assert result["observed_days"] == 3


def test_history_is_measured_from_the_first_real_usage_not_the_row_count():
    # The whole defect in one assertion.
    assert observed_history_days(_padded_window(scans_on_day=3, used=1)) == 3
    assert observed_history_days(_padded_window()) == 0
    assert observed_history_days([{"credits_used": 5}] * 10) == 10


def test_a_projection_is_published_once_there_is_a_week_behind_it():
    # A padded window whose usage starts far enough back to qualify.
    history = [{"credits_used": 0} for _ in range(31 - MIN_PROJECTION_HISTORY_DAYS)] + [
        {"credits_used": 10} for _ in range(MIN_PROJECTION_HISTORY_DAYS)
    ]

    result = calculate_projections(history, remaining=70, renewal_date=None)

    assert result["projection_reason"] is None
    # 70 remaining at 10 a day.
    assert result["days_until_depletion"] == 7.0
    assert result["depletion_date"] is not None


def test_usage_that_has_fallen_out_of_the_burn_window_reports_no_usage():
    # Reachable, and worth pinning: usage on the oldest day of a 31-row window
    # counts as history, because there has been something to observe, but the
    # 30-day burn rate only covers the last thirty rows, so the rate is zero.
    # History without a current rate is "no usage", not "no history".
    window = [{"credits_used": 5}] + [{"credits_used": 0} for _ in range(30)]

    result = calculate_projections(window, remaining=200, renewal_date=None)

    assert result["observed_days"] == 31
    assert result["burn_rate_30d"] == 0.0
    assert result["days_until_depletion"] is None
    assert result["projection_reason"] == PROJECTION_REASON_NO_USAGE


def test_a_window_with_no_usage_at_all_says_so():
    # No usage means no history, so this reports the absence rather than
    # claiming thirty days of observed nothing.
    result = calculate_projections(_padded_window(), remaining=200, renewal_date=None)

    assert result["days_until_depletion"] is None
    assert result["projection_reason"] == PROJECTION_REASON_NO_HISTORY
    assert result["observed_days"] == 0


def test_an_uncapped_allowance_has_nothing_to_depletes_and_says_which():
    history = [{"credits_used": 10} for _ in range(30)]

    result = calculate_projections(history, remaining=None, renewal_date=None)

    assert result["days_until_depletion"] is None
    assert result["projection_reason"] == PROJECTION_REASON_UNCAPPED


def test_the_burn_rates_are_still_reported_even_when_a_projection_is_not():
    # The rates are observations and stay useful; only the extrapolation from
    # them is withheld. A surface that wants to say "1 scan in 3 days" still
    # can.
    result = calculate_projections(
        _padded_window(scans_on_day=3, used=1), remaining=199, renewal_date=None
    )

    assert result["burn_rate_7d"] > 0
    assert result["projection_reason"] == PROJECTION_REASON_NO_HISTORY


def test_a_renewal_date_does_not_resurrect_a_withheld_projection():
    renewal = datetime.now(timezone.utc) + timedelta(days=20)

    result = calculate_projections(
        _padded_window(scans_on_day=2, used=1), remaining=199, renewal_date=renewal
    )

    assert result["will_exhaust_before_renewal"] is False
    assert result["projected_overage"] == 0
    assert result["projection_reason"] == PROJECTION_REASON_NO_HISTORY
