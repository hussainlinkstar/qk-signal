"""Tests for AEX-23: Periodic cron sweeper with health monitoring."""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# SIGNAL-1026: cron_sweeper._tier_last_run (and shutdown_requested) are bare
# module-level globals shared by the whole test process. Most classes below
# reset _tier_last_run in their own setup_method, but not all of them do (see
# TestSweepJobsCompat, TestSignalHandling), and per-class setup only resets
# state going into that class's own tests, not coming out of them. A test
# like test_only_fast_tier_when_others_not_due deliberately leaves real
# timestamps in _tier_last_run with no matching teardown. Reset unconditionally
# before and after every test in this file so no test can observe (or leave
# behind) another test's tier-timer state, regardless of which class's
# setup_method may or may not cover it.
@pytest.fixture(autouse=True)
def _reset_cron_sweeper_module_state():
    import cron_sweeper

    cron_sweeper._tier_last_run.clear()
    cron_sweeper.shutdown_requested = False
    yield
    cron_sweeper._tier_last_run.clear()
    cron_sweeper.shutdown_requested = False


# ── Helper to build a mock async Redis context manager ────────────────────────


def _make_redis_ctx(mock_redis):
    """Return a callable that produces an async context manager yielding *mock_redis*."""

    def factory(*args, **kwargs):
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_redis)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    return factory


# ── _should_run_tier tests ────────────────────────────────────────────────────


class TestShouldRunTier:
    """Unit tests for tier-based interval tracking."""

    def setup_method(self):
        import cron_sweeper

        cron_sweeper._tier_last_run.clear()

    def test_first_call_always_returns_true(self):
        import cron_sweeper

        assert cron_sweeper._should_run_tier("fast", 60) is True

    def test_immediate_second_call_returns_false(self):
        import cron_sweeper

        cron_sweeper._should_run_tier("fast", 60)
        assert cron_sweeper._should_run_tier("fast", 60) is False

    def test_returns_true_after_interval_elapsed(self):
        import cron_sweeper

        cron_sweeper._should_run_tier("fast", 60)
        # Fake the last run to be 61 seconds ago
        cron_sweeper._tier_last_run["fast"] = time.monotonic() - 61
        assert cron_sweeper._should_run_tier("fast", 60) is True

    def test_different_tiers_are_independent(self):
        import cron_sweeper

        cron_sweeper._should_run_tier("fast", 60)
        # "fast" was just run, but "standard" hasn't been run yet
        assert cron_sweeper._should_run_tier("fast", 60) is False
        assert cron_sweeper._should_run_tier("standard", 300) is True

    def test_zero_interval_always_runs(self):
        import cron_sweeper

        cron_sweeper._should_run_tier("always", 0)
        assert cron_sweeper._should_run_tier("always", 0) is True

    def test_never_run_tier_is_due_even_when_monotonic_clock_is_near_zero(self, monkeypatch):
        """SIGNAL-1026 regression.

        time.monotonic()'s reference point is undefined; on a freshly booted
        host (e.g. a CI runner) it can be a small value. A tier that has never
        run must still be considered due even if the current monotonic time
        is smaller than the tier's own interval, it must not depend on the
        clock's absolute value already exceeding the interval.
        """
        import cron_sweeper

        monkeypatch.setattr(cron_sweeper.time, "monotonic", lambda: 1.0)
        assert cron_sweeper._should_run_tier("daily", 86400) is True


# ── sweep_cycle tests ─────────────────────────────────────────────────────────


class TestSweepCycle:
    """Tests for the tier-aware sweep_cycle() function."""

    def setup_method(self):
        import cron_sweeper

        cron_sweeper._tier_last_run.clear()

    @patch("cron_sweeper.SessionLocal")
    @patch("cron_sweeper._dashboard_base_url", return_value="https://example.com")
    @patch("cron_sweeper.expire_stale_holds", return_value=[])
    @patch("cron_sweeper.generate_pending_project_progress_reports", return_value=[])
    @patch("cron_sweeper.evaluate_admin_alerts", new_callable=AsyncMock)
    @patch("cron_sweeper.collect_metrics_snapshot")
    @patch("cron_sweeper.refresh_recent_bot_log_daily_summaries", return_value={})
    @patch("cron_sweeper.refresh_recent_off_page_mention_daily_summaries", return_value={})
    @patch("cron_sweeper.refresh_recent_global_volatility_snapshots", return_value={})
    @patch("cron_sweeper.queue_feedback_requests_for_completed_trials", return_value={})
    @patch("cron_sweeper.report_pending_commitment_overages", return_value=[])
    @patch("cron_sweeper.collect_warning_candidates", return_value=[])
    @patch("cron_sweeper._cleanup_expired_report_jobs", return_value=(0, 0))
    @patch("cron_sweeper.run_model_lifecycle_check", return_value={})
    def test_force_all_runs_every_tier(
        self,
        _lifecycle,
        _cleanup,
        _warnings,
        _overages,
        _feedback,
        _volatility,
        _mentions,
        _botlog,
        _metrics,
        _alerts,
        _progress,
        _holds,
        _base,
        mock_session_cls,
    ):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = []
        mock_db.query.return_value.outerjoin.return_value.filter.return_value.first.return_value = (
            None
        )
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_session_cls.return_value = mock_db

        import cron_sweeper

        cron_sweeper.sweep_cycle(force_all=True)

        mock_db.commit.assert_called_once()
        mock_db.close.assert_called_once()
        # fast tier tasks
        _holds.assert_called_once()
        # standard tier tasks
        _alerts.assert_called_once()
        # slow tier tasks
        _overages.assert_called_once()
        # daily tier tasks
        _cleanup.assert_called_once()
        _lifecycle.assert_called_once()

    @patch("cron_sweeper.SessionLocal")
    @patch("cron_sweeper._dashboard_base_url", return_value="https://example.com")
    @patch("cron_sweeper.expire_stale_holds", return_value=[])
    def test_only_fast_tier_when_others_not_due(self, _holds, _base, mock_session_cls):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.with_for_update.return_value.all.return_value = []
        mock_session_cls.return_value = mock_db

        import cron_sweeper

        # Pre-mark standard/slow/daily as recently run
        now = time.monotonic()
        cron_sweeper._tier_last_run["standard"] = now
        cron_sweeper._tier_last_run["slow"] = now
        cron_sweeper._tier_last_run["daily"] = now

        cron_sweeper.sweep_cycle()

        # fast tier ran
        _holds.assert_called_once()

    def test_no_tiers_due_skips_entirely(self):
        import cron_sweeper

        now = time.monotonic()
        for tier in ("fast", "standard", "slow", "daily"):
            cron_sweeper._tier_last_run[tier] = now

        with patch("cron_sweeper.SessionLocal") as mock_session_cls:
            cron_sweeper.sweep_cycle()
            mock_session_cls.assert_not_called()

    @patch("cron_sweeper.SessionLocal")
    @patch("cron_sweeper._dashboard_base_url", return_value="https://example.com")
    def test_db_error_rolls_back_and_raises(self, _base, mock_session_cls):
        mock_db = MagicMock()
        mock_db.query.side_effect = RuntimeError("DB connection lost")
        mock_session_cls.return_value = mock_db

        import cron_sweeper

        with pytest.raises(RuntimeError, match="DB connection lost"):
            cron_sweeper.sweep_cycle(force_all=True)

        mock_db.rollback.assert_called_once()
        mock_db.close.assert_called_once()


# ── sweep_jobs backward compatibility ─────────────────────────────────────────


class TestSweepJobsCompat:
    def test_sweep_jobs_calls_sweep_cycle_with_force_all(self):
        import cron_sweeper

        with patch.object(cron_sweeper, "sweep_cycle") as mock_cycle:
            cron_sweeper.sweep_jobs()
            mock_cycle.assert_called_once_with(force_all=True)


# ── Signal handling tests ─────────────────────────────────────────────────────


class TestSignalHandling:
    def setup_method(self):
        import cron_sweeper

        cron_sweeper.shutdown_requested = False

    def test_request_shutdown_sets_flag(self):
        import cron_sweeper

        cron_sweeper._request_shutdown("SIGTERM")
        assert cron_sweeper.shutdown_requested is True

    def test_duplicate_shutdown_is_idempotent(self):
        import cron_sweeper

        cron_sweeper._request_shutdown("SIGTERM")
        cron_sweeper._request_shutdown("SIGTERM")  # should not raise
        assert cron_sweeper.shutdown_requested is True


# ── run_periodic async loop tests ─────────────────────────────────────────────


class TestRunPeriodic:
    """Tests for the async periodic loop."""

    def setup_method(self):
        import cron_sweeper

        cron_sweeper.shutdown_requested = False
        cron_sweeper._tier_last_run.clear()

    @pytest.mark.asyncio
    async def test_heartbeat_updated_on_success(self):
        """After a successful sweep, Redis heartbeat key should be set."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=b"sweeper-test1234")
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        call_count = 0

        async def shutdown_after_one_cycle(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle"),
            patch("cron_sweeper._interruptible_sleep", side_effect=shutdown_after_one_cycle),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        # Verify heartbeat was set
        set_calls = [
            c for c in mock_redis.set.call_args_list if c[0][0] == cron_sweeper.HEARTBEAT_KEY
        ]
        assert len(set_calls) >= 1

    @pytest.mark.asyncio
    async def test_distributed_lock_prevents_concurrent_execution(self):
        """When lock is held by another instance, sweep should be skipped."""
        import cron_sweeper

        mock_redis = AsyncMock()
        # SET NX returns False (lock held by someone else)
        mock_redis.set = AsyncMock(return_value=False)
        # GET returns a different worker_id
        mock_redis.get = AsyncMock(return_value=b"sweeper-other999")

        call_count = 0

        async def shutdown_after_skip(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 1:
                cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle") as mock_sweep,
            patch("cron_sweeper._interruptible_sleep", side_effect=shutdown_after_skip),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        # sweep_cycle should NOT have been called
        mock_sweep.assert_not_called()

    @pytest.mark.asyncio
    async def test_sweep_error_does_not_crash_loop(self):
        """A sweep failure should be caught and the loop should continue."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID.encode())
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        call_count = 0

        async def shutdown_after_two(seconds):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle", side_effect=RuntimeError("boom")),
            patch("cron_sweeper._interruptible_sleep", side_effect=shutdown_after_two),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            # Should NOT raise — the loop catches the error
            await cron_sweeper.run_periodic()

        # Loop ran twice before shutdown
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_graceful_shutdown_releases_lock(self):
        """On shutdown, the sweeper should release its Redis lock."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID.encode())
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle"),
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        # Lock should be deleted on shutdown
        mock_redis.delete.assert_called_with(cron_sweeper.LOCK_KEY)

    @pytest.mark.asyncio
    async def test_graceful_shutdown_releases_lock_with_str_owner(self):
        """On shutdown, decoded Redis owner values should release the lock."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle"),
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        mock_redis.delete.assert_called_with(cron_sweeper.LOCK_KEY)

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_success(self):
        """Prometheus metrics should be incremented on successful sweep."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID.encode())
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle"),
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
            patch("cron_sweeper.cron_sweep_runs_total") as mock_runs,
            patch("cron_sweeper.cron_sweep_duration_seconds") as mock_duration,
            patch("cron_sweeper.cron_sweep_last_success_timestamp") as mock_ts,
        ):
            await cron_sweeper.run_periodic()

        mock_runs.labels.assert_called_with(status="success")
        mock_runs.labels.return_value.inc.assert_called()
        mock_duration.observe.assert_called()
        mock_ts.set.assert_called()

    @pytest.mark.asyncio
    async def test_metrics_recorded_on_error(self):
        """Error metrics should be incremented when sweep fails."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID.encode())
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle", side_effect=RuntimeError("fail")),
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
            patch("cron_sweeper.cron_sweep_runs_total") as mock_runs,
            patch("cron_sweeper.cron_sweep_errors_total") as mock_errors,
            patch("cron_sweeper.cron_sweep_duration_seconds"),
        ):
            await cron_sweeper.run_periodic()

        mock_runs.labels.assert_called_with(status="error")
        mock_errors.inc.assert_called()

    @pytest.mark.asyncio
    async def test_reentrant_lock_succeeds_for_same_worker(self):
        """If SET NX fails but the lock is owned by us, we should proceed."""
        import cron_sweeper

        mock_redis = AsyncMock()
        # SET NX returns False (lock already exists)
        mock_redis.set = AsyncMock(return_value=False)
        # GET returns our own worker ID
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID.encode())
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle") as mock_sweep,
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        # sweep should have been called (re-entrant lock)
        mock_sweep.assert_called_once()

    @pytest.mark.asyncio
    async def test_reentrant_lock_succeeds_with_str_owner(self):
        """A decoded Redis owner value should support re-entrant acquisition."""
        import cron_sweeper

        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=False)
        mock_redis.get = AsyncMock(return_value=cron_sweeper.WORKER_ID)
        mock_redis.expire = AsyncMock(return_value=True)
        mock_redis.delete = AsyncMock()

        async def immediate_shutdown(seconds):
            cron_sweeper.shutdown_requested = True

        with (
            patch("cron_sweeper.get_async_redis", side_effect=_make_redis_ctx(mock_redis)),
            patch("cron_sweeper.sweep_cycle") as mock_sweep,
            patch("cron_sweeper._interruptible_sleep", side_effect=immediate_shutdown),
            patch("cron_sweeper._install_signal_handlers"),
        ):
            await cron_sweeper.run_periodic()

        mock_sweep.assert_called_once()


# ── _interruptible_sleep tests ────────────────────────────────────────────────


class TestInterruptibleSleep:
    def setup_method(self):
        import cron_sweeper

        cron_sweeper.shutdown_requested = False

    @pytest.mark.asyncio
    async def test_sleep_completes_normally(self):
        import cron_sweeper

        start = time.monotonic()
        await cron_sweeper._interruptible_sleep(0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05

    @pytest.mark.asyncio
    async def test_sleep_interrupted_by_shutdown(self):
        import cron_sweeper

        async def set_shutdown():
            await asyncio.sleep(0.05)
            cron_sweeper.shutdown_requested = True

        task = asyncio.create_task(set_shutdown())
        start = time.monotonic()
        await cron_sweeper._interruptible_sleep(10.0)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0  # Should exit way before 10 seconds
        await task


# ── Health endpoint tests ─────────────────────────────────────────────────────


class TestCronSweeperHealthEndpoint:
    """Tests for GET /health/cron-sweeper in system_checks.py."""

    @pytest.mark.asyncio
    async def test_healthy_when_heartbeat_is_fresh(self):
        from system_checks import get_cron_sweeper_health

        fresh_ts = datetime.now(timezone.utc).isoformat()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=fresh_ts.encode())

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_redis)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("system_checks.get_async_redis", return_value=ctx):
            result = await get_cron_sweeper_health()

        assert result["status"] == "healthy"
        assert "age_seconds" in result

    @pytest.mark.asyncio
    async def test_unhealthy_when_heartbeat_is_stale(self):
        from system_checks import get_cron_sweeper_health

        stale_ts = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stale_ts.encode())

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_redis)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("system_checks.get_async_redis", return_value=ctx),
            patch.dict("os.environ", {"CRON_SWEEP_INTERVAL_SECONDS": "60"}),
        ):
            result = await get_cron_sweeper_health()

        assert result["status"] == "unhealthy"
        assert result["reason"] == "Heartbeat is stale"

    @pytest.mark.asyncio
    async def test_unhealthy_when_no_heartbeat(self):
        from system_checks import get_cron_sweeper_health

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(return_value=mock_redis)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("system_checks.get_async_redis", return_value=ctx):
            result = await get_cron_sweeper_health()

        assert result["status"] == "unhealthy"
        assert result["reason"] == "No heartbeat found"

    @pytest.mark.asyncio
    async def test_unknown_when_redis_fails(self):
        from system_checks import get_cron_sweeper_health

        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch("system_checks.get_async_redis", return_value=ctx):
            result = await get_cron_sweeper_health()

        assert result["status"] == "unknown"
        assert "error" in result
