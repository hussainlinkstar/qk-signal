"""Tests for credit balance reconciliation service."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

# We mock the ``models`` module so that importing the service under test
# does not trigger the full SQLAlchemy / config bootstrap chain.
_models_mock = MagicMock()
sys.modules.setdefault("models", _models_mock)

from sqlalchemy.orm import Session  # noqa: E402

from services.credit_reconciliation_service import (  # noqa: E402
    reconcile_all_credits,
    reconcile_user_credits,
    run_credit_reconciliation_sweep,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(user_id: int = 1, credits: int = 100, trial_plan: str | None = None) -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.credits = credits
    user.trial_plan = trial_plan
    return user


def _mock_db_for_single_user(user: MagicMock | None, ledger_sum: int | None) -> MagicMock:
    """Build a MagicMock(spec=Session) that handles the two queries in reconcile_user_credits.

    First call to db.query(models.User)...first() returns *user*.
    Second call to db.query(func.sum(...))...scalar() returns *ledger_sum*.
    """
    db = MagicMock(spec=Session)

    # Each db.query() call returns a fresh chain mock so the two queries
    # are independent.
    user_chain = MagicMock()
    user_chain.filter.return_value = user_chain
    user_chain.first.return_value = user

    sum_chain = MagicMock()
    sum_chain.filter.return_value = sum_chain
    sum_chain.scalar.return_value = ledger_sum

    db.query.side_effect = [user_chain, sum_chain]
    return db


# ---------------------------------------------------------------------------
# reconcile_user_credits
# ---------------------------------------------------------------------------


class TestReconcileUserCredits:
    def test_reconcile_user_credits_balanced(self) -> None:
        """No discrepancy when User.credits matches ledger sum."""
        user = _make_user(user_id=1, credits=100)
        db = _mock_db_for_single_user(user, ledger_sum=100)

        result = reconcile_user_credits(db, user_id=1)

        assert result is None

    def test_reconcile_user_credits_drift(self) -> None:
        """Discrepancy detected when credits diverge from ledger sum."""
        user = _make_user(user_id=42, credits=50)
        db = _mock_db_for_single_user(user, ledger_sum=100)

        result = reconcile_user_credits(db, user_id=42)

        assert result is not None
        assert result["user_id"] == 42
        assert result["expected"] == 100
        assert result["actual"] == 50
        assert result["drift"] == -50

    def test_reconcile_user_credits_no_adjustments(self) -> None:
        """User with no adjustments returns None (nothing to compare)."""
        user = _make_user(user_id=7, credits=5)
        db = _mock_db_for_single_user(user, ledger_sum=None)

        result = reconcile_user_credits(db, user_id=7)

        assert result is None

    def test_reconcile_user_credits_user_not_found(self) -> None:
        """Non-existent user returns None."""
        db = _mock_db_for_single_user(user=None, ledger_sum=None)

        result = reconcile_user_credits(db, user_id=999)

        assert result is None

    def test_reconcile_skips_trial_user(self) -> None:
        """Trial users (plan_agency_trial) are skipped to avoid false positives."""
        user = _make_user(user_id=10, credits=50, trial_plan="plan_agency_trial")
        # Only one query needed — user lookup; ledger query is never reached
        db = MagicMock(spec=Session)
        user_chain = MagicMock()
        user_chain.filter.return_value = user_chain
        user_chain.first.return_value = user
        db.query.side_effect = [user_chain]

        result = reconcile_user_credits(db, user_id=10)

        assert result is None

    def test_reconcile_skips_explorer_user(self) -> None:
        """Explorer users are skipped to avoid false positives."""
        user = _make_user(user_id=11, credits=20, trial_plan="plan_starter")
        db = MagicMock(spec=Session)
        user_chain = MagicMock()
        user_chain.filter.return_value = user_chain
        user_chain.first.return_value = user
        db.query.side_effect = [user_chain]

        result = reconcile_user_credits(db, user_id=11)

        assert result is None

    def test_reconcile_does_not_skip_paid_user(self) -> None:
        """Paid users (trial_plan=None) are still reconciled normally."""
        user = _make_user(user_id=12, credits=50, trial_plan=None)
        db = _mock_db_for_single_user(user, ledger_sum=100)

        result = reconcile_user_credits(db, user_id=12)

        assert result is not None
        assert result["drift"] == -50


# ---------------------------------------------------------------------------
# reconcile_all_credits
# ---------------------------------------------------------------------------


class TestReconcileAllCredits:
    def test_reconcile_all_credits_mixed(self) -> None:
        """Multiple users: only drifted ones are returned."""
        db = MagicMock(spec=Session)

        # Step 1: db.query(UserCreditAdjustment.user_id).distinct().limit().all()
        distinct_chain = MagicMock()
        distinct_chain.distinct.return_value = distinct_chain
        distinct_chain.limit.return_value = distinct_chain
        distinct_chain.all.return_value = [(1,), (2,), (3,)]

        # Step 2+: reconcile_user_credits calls db.query twice per user
        # User 1: balanced (credits=100, ledger=100)
        u1 = _make_user(user_id=1, credits=100)
        u1_chain = MagicMock()
        u1_chain.filter.return_value = u1_chain
        u1_chain.first.return_value = u1
        u1_sum_chain = MagicMock()
        u1_sum_chain.filter.return_value = u1_sum_chain
        u1_sum_chain.scalar.return_value = 100

        # User 2: drifted (credits=30, ledger=50)
        u2 = _make_user(user_id=2, credits=30)
        u2_chain = MagicMock()
        u2_chain.filter.return_value = u2_chain
        u2_chain.first.return_value = u2
        u2_sum_chain = MagicMock()
        u2_sum_chain.filter.return_value = u2_sum_chain
        u2_sum_chain.scalar.return_value = 50

        # User 3: drifted (credits=200, ledger=150)
        u3 = _make_user(user_id=3, credits=200)
        u3_chain = MagicMock()
        u3_chain.filter.return_value = u3_chain
        u3_chain.first.return_value = u3
        u3_sum_chain = MagicMock()
        u3_sum_chain.filter.return_value = u3_sum_chain
        u3_sum_chain.scalar.return_value = 150

        db.query.side_effect = [
            distinct_chain,  # initial user_ids query
            u1_chain,
            u1_sum_chain,  # user 1 reconciliation
            u2_chain,
            u2_sum_chain,  # user 2 reconciliation
            u3_chain,
            u3_sum_chain,  # user 3 reconciliation
        ]

        discrepancies, users_checked = reconcile_all_credits(db)

        assert users_checked == 3
        assert len(discrepancies) == 2
        ids = {d["user_id"] for d in discrepancies}
        assert ids == {2, 3}

        drift_2 = next(d for d in discrepancies if d["user_id"] == 2)
        assert drift_2["expected"] == 50
        assert drift_2["actual"] == 30
        assert drift_2["drift"] == -20

        drift_3 = next(d for d in discrepancies if d["user_id"] == 3)
        assert drift_3["expected"] == 150
        assert drift_3["actual"] == 200
        assert drift_3["drift"] == 50

    def test_reconcile_all_credits_all_balanced(self) -> None:
        """All users balanced returns empty list."""
        db = MagicMock(spec=Session)

        distinct_chain = MagicMock()
        distinct_chain.distinct.return_value = distinct_chain
        distinct_chain.limit.return_value = distinct_chain
        distinct_chain.all.return_value = [(1,)]

        u1 = _make_user(user_id=1, credits=50)
        u1_chain = MagicMock()
        u1_chain.filter.return_value = u1_chain
        u1_chain.first.return_value = u1
        u1_sum_chain = MagicMock()
        u1_sum_chain.filter.return_value = u1_sum_chain
        u1_sum_chain.scalar.return_value = 50

        db.query.side_effect = [distinct_chain, u1_chain, u1_sum_chain]

        discrepancies, users_checked = reconcile_all_credits(db)

        assert users_checked == 1
        assert discrepancies == []


# ---------------------------------------------------------------------------
# run_credit_reconciliation_sweep
# ---------------------------------------------------------------------------


class TestRunCreditReconciliationSweep:
    @patch("services.credit_reconciliation_service.reconcile_all_credits")
    def test_run_sweep_logs_summary(self, mock_reconcile) -> None:
        """Verify the sweep function returns proper summary dict."""
        mock_reconcile.return_value = (
            [{"user_id": 5, "expected": 100, "actual": 80, "drift": -20}],
            3,
        )

        db = MagicMock(spec=Session)

        summary = run_credit_reconciliation_sweep(db)

        assert summary["users_checked"] == 3
        assert len(summary["discrepancies"]) == 1
        assert summary["discrepancies"][0]["user_id"] == 5
        assert summary["discrepancies"][0]["drift"] == -20
        assert "checked_at" in summary

    @patch("services.credit_reconciliation_service.reconcile_all_credits")
    def test_run_sweep_no_discrepancies(self, mock_reconcile) -> None:
        """Clean sweep returns empty discrepancies list."""
        mock_reconcile.return_value = ([], 2)

        db = MagicMock(spec=Session)

        summary = run_credit_reconciliation_sweep(db)

        assert summary["users_checked"] == 2
        assert summary["discrepancies"] == []
        assert "checked_at" in summary
