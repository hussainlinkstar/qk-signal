"""Tests for services.queue_routing — tier-to-queue resolution and constants."""

import pytest

from services.queue_routing import (
    ALL_CONSUMER_QUEUES,
    LEGACY_QUEUE_NAME,
    QUEUE_DEEP,
    QUEUE_FAST,
    QUEUE_SMART,
    resolve_queue_for_tier,
)


class TestResolveQueueForTier:
    """Verify tier → queue mapping."""

    @pytest.mark.parametrize(
        "tier, expected_queue",
        [
            ("fast", QUEUE_FAST),
            ("lite", QUEUE_FAST),
            ("smart", QUEUE_SMART),
            ("deep", QUEUE_DEEP),
            ("deep_judgment", QUEUE_DEEP),
        ],
    )
    def test_known_tiers(self, tier: str, expected_queue: str) -> None:
        assert resolve_queue_for_tier(tier) == expected_queue

    def test_unknown_tier_defaults_to_fast(self) -> None:
        assert resolve_queue_for_tier("nonexistent") == QUEUE_FAST

    def test_none_defaults_to_fast(self) -> None:
        assert resolve_queue_for_tier(None) == QUEUE_FAST

    def test_empty_string_defaults_to_fast(self) -> None:
        assert resolve_queue_for_tier("") == QUEUE_FAST

    def test_case_insensitive(self) -> None:
        assert resolve_queue_for_tier("SMART") == QUEUE_SMART
        assert resolve_queue_for_tier("Fast") == QUEUE_FAST
        assert resolve_queue_for_tier("DEEP_JUDGMENT") == QUEUE_DEEP

    def test_whitespace_stripped(self) -> None:
        assert resolve_queue_for_tier("  smart  ") == QUEUE_SMART


class TestQueueConstants:
    """Verify queue name structure and priority order."""

    def test_queue_names_are_namespaced(self) -> None:
        assert QUEUE_FAST.endswith(":fast")
        assert QUEUE_SMART.endswith(":smart")
        assert QUEUE_DEEP.endswith(":deep")

    def test_all_consumer_queues_priority_order(self) -> None:
        assert ALL_CONSUMER_QUEUES == [QUEUE_FAST, QUEUE_SMART, QUEUE_DEEP, LEGACY_QUEUE_NAME]

    def test_legacy_queue_is_last(self) -> None:
        assert ALL_CONSUMER_QUEUES[-1] == LEGACY_QUEUE_NAME

    def test_fast_is_first_priority(self) -> None:
        assert ALL_CONSUMER_QUEUES[0] == QUEUE_FAST

    def test_no_duplicate_queues(self) -> None:
        assert len(ALL_CONSUMER_QUEUES) == len(set(ALL_CONSUMER_QUEUES))


class TestWorkerConcurrencyConstants:
    """Verify worker concurrency and timeout constants from queue_worker."""

    def test_max_concurrent_audits_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_CONCURRENT_AUDITS", "8")
        # Re-import to pick up the env var change
        import importlib
        import queue_worker

        importlib.reload(queue_worker)
        assert queue_worker.MAX_CONCURRENT_AUDITS == 8
        # Clean up: reload back to default
        monkeypatch.delenv("MAX_CONCURRENT_AUDITS", raising=False)
        importlib.reload(queue_worker)

    def test_job_timeout_resolution(self) -> None:
        from queue_worker import (
            _resolve_job_timeout,
            JOB_TIMEOUT_FAST,
            JOB_TIMEOUT_SMART,
            JOB_TIMEOUT_DEEP,
        )

        assert _resolve_job_timeout("fast") == JOB_TIMEOUT_FAST
        assert _resolve_job_timeout("lite") == JOB_TIMEOUT_FAST
        assert _resolve_job_timeout("smart") == JOB_TIMEOUT_SMART
        assert _resolve_job_timeout("deep") == JOB_TIMEOUT_DEEP
        assert _resolve_job_timeout("deep_judgment") == JOB_TIMEOUT_DEEP
        # Unknown tier falls back to fast timeout
        assert _resolve_job_timeout("unknown") == JOB_TIMEOUT_FAST
