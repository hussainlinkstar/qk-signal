"""Worker audit result caching: identical re-runs return the cached report so
scores stay consistent between consecutive audits of the same subject.

SIGV2-1235: a cache hit must never be indistinguishable from a fresh
measurement. These tests pin that the cache stores and returns WHEN the
content was actually measured, and that the metadata built for a cache-hit
response is honest about it instead of claiming "now"."""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

import queue_worker


def _job(**overrides):
    base = dict(
        provider="google",
        tier="fast",
        requested_tier="smart",
        project_id=None,
        selected_models=None,
        target_name="",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str, int | None]] = []

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value
        self.set_calls.append((key, value, ex))


def test_cache_key_is_stable_and_tier_sensitive():
    k1 = queue_worker._build_worker_audit_cache_key(_job(), "https://qiko.ai", "website")
    k2 = queue_worker._build_worker_audit_cache_key(_job(), "https://qiko.ai", "website")
    k3 = queue_worker._build_worker_audit_cache_key(_job(tier="deep"), "https://qiko.ai", "website")
    assert k1 == k2  # deterministic
    assert k1 != k3  # tier participates in the key
    assert k1.startswith("audit:cache:")


@pytest.mark.asyncio
async def test_store_then_get_roundtrip():
    r = _FakeRedis()
    key = queue_worker._build_worker_audit_cache_key(_job(), "https://qiko.ai", "website")
    report = {"scores": {"seo": 54.0, "geo": 33.0, "aeo": 47.0}}
    scores = {"seo": 54.0, "geo": 33.0, "aeo": 47.0, "overall": 44.7}
    measured_at = datetime(2026, 10, 8, 15, 17, 0, tzinfo=timezone.utc)

    await queue_worker._store_cached_audit_result(r, key, report, scores, measured_at=measured_at)
    # Stored with a TTL
    assert r.set_calls and r.set_calls[0][2] == queue_worker.WORKER_AUDIT_CACHE_TTL_SECONDS

    cached = await queue_worker._get_cached_audit_result(r, key)
    assert cached is not None
    cached_report, cached_scores, cached_measured_at = cached
    assert cached_report == report
    assert cached_scores == scores
    # The real measurement time round-trips exactly, not "whenever this was
    # read back" (SIGV2-1235).
    assert cached_measured_at == measured_at.isoformat()


@pytest.mark.asyncio
async def test_store_defaults_measured_at_to_now_when_not_given():
    r = _FakeRedis()
    key = queue_worker._build_worker_audit_cache_key(_job(), "https://qiko.ai", "website")
    before = datetime.now(timezone.utc)

    await queue_worker._store_cached_audit_result(r, key, {"ok": True}, {"overall": 1.0})

    _, _, cached_measured_at = await queue_worker._get_cached_audit_result(r, key)
    after = datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(cached_measured_at)
    assert before <= parsed <= after


@pytest.mark.asyncio
async def test_get_returns_none_on_miss():
    r = _FakeRedis()
    assert await queue_worker._get_cached_audit_result(r, "audit:cache:missing") is None


@pytest.mark.asyncio
async def test_get_returns_none_on_malformed_entry():
    r = _FakeRedis()
    r.store["audit:cache:bad"] = json.dumps({"report": "not-a-dict", "scores": {}})
    assert await queue_worker._get_cached_audit_result(r, "audit:cache:bad") is None


@pytest.mark.asyncio
async def test_legacy_cache_entry_without_measured_at_reads_back_as_unknown_not_now():
    """A cache entry written before SIGV2-1235 has no ``measured_at`` key.
    Reading it back must surface ``None`` (unknown), never silently invent
    "now" as if the content had just been measured."""
    r = _FakeRedis()
    key = "audit:cache:legacy"
    r.store[key] = json.dumps({"report": {"ok": True}, "scores": {"overall": 1.0}})

    _, _, cached_measured_at = await queue_worker._get_cached_audit_result(r, key)
    assert cached_measured_at is None


def test_cache_hit_metadata_carries_true_measurement_time_not_now():
    """This is the ticket's core assertion: a cache-hit response's provenance
    metadata must carry the ORIGINAL measurement time, and must be marked as
    served from cache, so it cannot be mistaken for a fresh measurement even
    though it is produced "now"."""
    original_measured_at = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    fresh_now = datetime.now(timezone.utc)

    provenance = queue_worker._resolve_cache_provenance_metadata(
        served_from_cache=True,
        cached_measured_at=original_measured_at,
        fresh_measured_at=fresh_now,
    )

    assert provenance["served_from_cache"] is True
    assert provenance["measured_at"] == original_measured_at
    # The whole point of the bug: this must NOT equal "now".
    assert provenance["measured_at"] != fresh_now.isoformat()
    assert provenance["measured_at_unknown"] is False


def test_fresh_run_metadata_is_measured_now_and_not_served_from_cache():
    fresh_now = datetime.now(timezone.utc)

    provenance = queue_worker._resolve_cache_provenance_metadata(
        served_from_cache=False,
        cached_measured_at=None,
        fresh_measured_at=fresh_now,
    )

    assert provenance["served_from_cache"] is False
    assert provenance["measured_at"] == fresh_now.isoformat()
    assert provenance["measured_at_unknown"] is False


def test_cache_hit_with_unknown_measured_at_is_flagged_not_defaulted_to_now():
    fresh_now = datetime.now(timezone.utc)

    provenance = queue_worker._resolve_cache_provenance_metadata(
        served_from_cache=True,
        cached_measured_at=None,
        fresh_measured_at=fresh_now,
    )

    assert provenance["served_from_cache"] is True
    assert provenance["measured_at"] is None
    assert provenance["measured_at_unknown"] is True


def test_same_target_run_twice_second_response_is_distinguishable_from_fresh():
    """Simulates the ticket's reproduction: run A (real measurement), then run
    B minutes later which hits the cache. Run B's metadata must be impossible
    to mistake for a fresh measurement."""
    run_a_measured_at = datetime(2026, 10, 8, 15, 17, 0, tzinfo=timezone.utc)
    run_b_served_at = datetime(2026, 10, 8, 15, 20, 42, tzinfo=timezone.utc)

    run_a_metadata = queue_worker._resolve_cache_provenance_metadata(
        served_from_cache=False,
        cached_measured_at=None,
        fresh_measured_at=run_a_measured_at,
    )
    run_b_metadata = queue_worker._resolve_cache_provenance_metadata(
        served_from_cache=True,
        cached_measured_at=run_a_metadata["measured_at"],
        fresh_measured_at=run_b_served_at,
    )

    assert run_a_metadata["served_from_cache"] is False
    assert run_b_metadata["served_from_cache"] is True
    # Run B must report run A's real measurement time, not its own serve time.
    assert run_b_metadata["measured_at"] == run_a_metadata["measured_at"]
    assert run_b_metadata["measured_at"] != run_b_served_at.isoformat()
