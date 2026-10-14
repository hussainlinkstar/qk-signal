"""
Tests for AEX-22: Redis Job Hash TTL and Dead Letter Queue

Covers:
- TTL constants and key helpers
- Async TTL set functions
- DLQ push / list / retry / discard
- Auto-retry sweep (sync)
- Orphaned key cleanup (sync)
- build_dlq_payload_from_exception helper
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone

from services.job_ttl_dlq_service import (
    TTL_IN_PROGRESS,
    TTL_SUCCEEDED,
    TTL_FAILED,
    TTL_QUEUED,
    DLQ_LIST_KEY,
    DLQ_MAX_RETRY_COUNT,
    _build_job_key,
    set_ttl_queued,
    set_ttl_in_progress,
    set_ttl_succeeded,
    set_ttl_failed,
    set_ttl_failed_sync,
    push_to_dlq,
    list_dlq,
    dlq_length,
    retry_dlq_entry,
    discard_dlq_entry,
    auto_retry_dlq_sync,
    cleanup_orphaned_job_keys_sync,
    build_dlq_payload_from_exception,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAsyncRedis:
    """Minimal async Redis fake for testing DLQ operations."""

    def __init__(self):
        self._data: dict[str, list[str]] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._ttls: dict[str, int] = {}

    async def expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl

    async def rpush(self, key: str, *values: str) -> int:
        self._data.setdefault(key, [])
        for v in values:
            self._data[key].append(v)
        return len(self._data[key])

    async def llen(self, key: str) -> int:
        return len(self._data.get(key, []))

    async def lrange(self, key: str, start: int, end: int) -> list[str]:
        lst = self._data.get(key, [])
        return lst[start : end + 1]

    async def lindex(self, key: str, idx: int) -> str | None:
        lst = self._data.get(key, [])
        if 0 <= idx < len(lst):
            return lst[idx]
        return None

    async def lset(self, key: str, idx: int, value: str) -> None:
        lst = self._data.get(key, [])
        if 0 <= idx < len(lst):
            lst[idx] = value

    async def lrem(self, key: str, count: int, value: str) -> int:
        lst = self._data.get(key, [])
        removed = 0
        while value in lst and (count == 0 or removed < count):
            lst.remove(value)
            removed += 1
        return removed

    async def hset(self, key: str, mapping: dict | None = None, **kwargs) -> None:
        self._hashes.setdefault(key, {})
        if mapping:
            self._hashes[key].update({k: str(v) for k, v in mapping.items()})
        for k, v in kwargs.items():
            self._hashes[key][k] = str(v)

    async def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        self._hashes.setdefault(key, {})
        current = int(self._hashes[key].get(field, 0))
        self._hashes[key][field] = str(current + amount)
        return current + amount

    async def hincrbyfloat(self, key: str, field: str, amount: float) -> float:
        self._hashes.setdefault(key, {})
        current = float(self._hashes[key].get(field, 0))
        self._hashes[key][field] = str(current + amount)
        return current + amount

    async def eval(self, script, numkeys, *keys_and_args):
        # Emulate the atomic DLQ pop-by-job-id Lua script.
        key = keys_and_args[0]
        job_id = keys_and_args[1]
        lst = self._data.get(key, [])
        for raw in list(lst):
            try:
                entry = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if entry.get("job_id") == job_id:
                lst.remove(raw)
                return raw
        return None


class FakeSyncRedis:
    """Minimal sync Redis fake for testing sync operations."""

    def __init__(self):
        self._data: dict[str, list[str]] = {}
        self._hashes: dict[str, dict[str, str]] = {}
        self._ttls: dict[str, int] = {}

    def expire(self, key: str, ttl: int) -> None:
        self._ttls[key] = ttl

    def rpush(self, key: str, *values: str) -> int:
        self._data.setdefault(key, [])
        for v in values:
            self._data[key].append(v)
        return len(self._data[key])

    def llen(self, key: str) -> int:
        return len(self._data.get(key, []))

    def lindex(self, key: str, idx: int) -> str | None:
        lst = self._data.get(key, [])
        if 0 <= idx < len(lst):
            return lst[idx]
        return None

    def lset(self, key: str, idx: int, value: str) -> None:
        lst = self._data.get(key, [])
        if 0 <= idx < len(lst):
            lst[idx] = value

    def lrem(self, key: str, count: int, value: str) -> int:
        lst = self._data.get(key, [])
        removed = 0
        while value in lst and (count == 0 or removed < count):
            lst.remove(value)
            removed += 1
        return removed

    def hset(self, key: str, mapping: dict | None = None, **kwargs) -> None:
        self._hashes.setdefault(key, {})
        if mapping:
            self._hashes[key].update({k: str(v) for k, v in mapping.items()})
        for k, v in kwargs.items():
            self._hashes[key][k] = str(v)

    def hget(self, key: str, field: str) -> str | None:
        return self._hashes.get(key, {}).get(field)

    def ttl(self, key: str) -> int:
        return self._ttls.get(key, -1)

    def scan(self, cursor: str = "0", match: str = "*", count: int = 100):
        # Simple implementation: return all matching keys in one shot
        import fnmatch

        all_keys = list(self._hashes.keys())
        matched = [k for k in all_keys if fnmatch.fnmatch(k, match)]
        return ("0", matched)


# ---------------------------------------------------------------------------
# TTL constant tests
# ---------------------------------------------------------------------------


class TestTTLConstants:
    def test_ttl_values(self):
        assert TTL_QUEUED == 3600
        assert TTL_IN_PROGRESS == 1800
        assert TTL_SUCCEEDED == 86_400
        assert TTL_FAILED == 604_800

    def test_dlq_max_retry(self):
        assert DLQ_MAX_RETRY_COUNT == 3

    def test_dlq_list_key(self):
        assert DLQ_LIST_KEY == "audit_jobs:dlq"


# ---------------------------------------------------------------------------
# Key builder
# ---------------------------------------------------------------------------


class TestBuildJobKey:
    def test_builds_correct_key(self):
        assert _build_job_key("abc-123") == "audit:job:abc-123"

    def test_empty_job_id(self):
        assert _build_job_key("") == "audit:job:"


# ---------------------------------------------------------------------------
# Async TTL setters
# ---------------------------------------------------------------------------


class TestAsyncTTLSetters:
    @pytest.mark.asyncio
    async def test_set_ttl_queued(self):
        r = FakeAsyncRedis()
        await set_ttl_queued(r, "job-1")
        assert r._ttls["audit:job:job-1"] == TTL_QUEUED

    @pytest.mark.asyncio
    async def test_set_ttl_in_progress(self):
        r = FakeAsyncRedis()
        await set_ttl_in_progress(r, "job-2")
        assert r._ttls["audit:job:job-2"] == TTL_IN_PROGRESS

    @pytest.mark.asyncio
    async def test_set_ttl_succeeded(self):
        r = FakeAsyncRedis()
        await set_ttl_succeeded(r, "job-3")
        assert r._ttls["audit:job:job-3"] == TTL_SUCCEEDED

    @pytest.mark.asyncio
    async def test_set_ttl_failed(self):
        r = FakeAsyncRedis()
        await set_ttl_failed(r, "job-4")
        assert r._ttls["audit:job:job-4"] == TTL_FAILED


# ---------------------------------------------------------------------------
# Sync TTL setter
# ---------------------------------------------------------------------------


class TestSyncTTLSetter:
    def test_set_ttl_failed_sync(self):
        r = FakeSyncRedis()
        set_ttl_failed_sync(r, "job-5")
        assert r._ttls["audit:job:job-5"] == TTL_FAILED


# ---------------------------------------------------------------------------
# DLQ push
# ---------------------------------------------------------------------------


class TestDLQPush:
    @pytest.mark.asyncio
    async def test_push_to_dlq_basic(self):
        r = FakeAsyncRedis()
        await push_to_dlq(
            r,
            job_id="job-fail-1",
            original_payload={"url": "https://example.com"},
            error="Something went wrong",
        )
        assert len(r._data[DLQ_LIST_KEY]) == 1
        entry = json.loads(r._data[DLQ_LIST_KEY][0])
        assert entry["job_id"] == "job-fail-1"
        assert entry["error"] == "Something went wrong"
        assert entry["original_payload"]["url"] == "https://example.com"
        assert entry["retry_count"] == 0
        assert "failed_at" in entry

    @pytest.mark.asyncio
    async def test_push_to_dlq_truncates_long_error(self):
        r = FakeAsyncRedis()
        long_error = "x" * 5000
        await push_to_dlq(r, job_id="job-long", error=long_error)
        entry = json.loads(r._data[DLQ_LIST_KEY][0])
        assert len(entry["error"]) == 2000

    @pytest.mark.asyncio
    async def test_push_to_dlq_with_retry_count(self):
        r = FakeAsyncRedis()
        await push_to_dlq(r, job_id="job-r2", error="fail", retry_count=2)
        entry = json.loads(r._data[DLQ_LIST_KEY][0])
        assert entry["retry_count"] == 2


# ---------------------------------------------------------------------------
# DLQ list
# ---------------------------------------------------------------------------


class TestDLQList:
    @pytest.mark.asyncio
    async def test_list_empty(self):
        r = FakeAsyncRedis()
        result = await list_dlq(r)
        assert result == []

    @pytest.mark.asyncio
    async def test_list_returns_newest_first(self):
        r = FakeAsyncRedis()
        for i in range(3):
            await push_to_dlq(r, job_id=f"job-{i}", error=f"err-{i}")
        entries = await list_dlq(r)
        assert len(entries) == 3
        assert entries[0]["job_id"] == "job-2"
        assert entries[2]["job_id"] == "job-0"

    @pytest.mark.asyncio
    async def test_list_pagination(self):
        r = FakeAsyncRedis()
        for i in range(5):
            await push_to_dlq(r, job_id=f"job-{i}", error=f"err-{i}")
        page1 = await list_dlq(r, offset=0, limit=2)
        assert len(page1) == 2
        assert page1[0]["job_id"] == "job-4"

    @pytest.mark.asyncio
    async def test_dlq_length(self):
        r = FakeAsyncRedis()
        assert await dlq_length(r) == 0
        await push_to_dlq(r, job_id="j1", error="e1")
        await push_to_dlq(r, job_id="j2", error="e2")
        assert await dlq_length(r) == 2


# ---------------------------------------------------------------------------
# DLQ retry
# ---------------------------------------------------------------------------


class TestDLQRetry:
    @pytest.mark.asyncio
    async def test_retry_found(self):
        r = FakeAsyncRedis()
        await push_to_dlq(
            r,
            job_id="job-retry-1",
            original_payload={"url": "https://test.com", "job_id": "job-retry-1"},
            error="timeout",
        )
        entry = await retry_dlq_entry(r, "job-retry-1")
        assert entry is not None
        assert entry["job_id"] == "job-retry-1"
        # DLQ should be empty now
        assert await dlq_length(r) == 0
        # Job should be re-enqueued to tier-specific queue (defaults to fast)
        assert len(r._data.get("audit_jobs:fast", [])) == 1
        re_enqueued = json.loads(r._data["audit_jobs:fast"][0])
        assert re_enqueued["dlq_retry_count"] == 1
        # Job hash should be reset
        assert r._hashes["audit:job:job-retry-1"]["status"] == "queued"
        assert r._ttls["audit:job:job-retry-1"] == TTL_QUEUED

    @pytest.mark.asyncio
    async def test_concurrent_retry_enqueues_only_once(self):
        # Two workers racing to retry the same DLQ entry must result in exactly
        # one re-enqueue (atomic Lua removal). The loser gets None.
        r = FakeAsyncRedis()
        await push_to_dlq(
            r,
            job_id="job-race",
            original_payload={"url": "https://x.com", "job_id": "job-race", "tier": "fast"},
            error="boom",
        )
        results = await asyncio.gather(
            retry_dlq_entry(r, "job-race"),
            retry_dlq_entry(r, "job-race"),
        )
        non_none = [x for x in results if x is not None]
        assert len(non_none) == 1
        assert await dlq_length(r) == 0
        # Exactly one re-enqueue
        assert len(r._data.get("audit_jobs:fast", [])) == 1

    @pytest.mark.asyncio
    async def test_retry_not_found(self):
        r = FakeAsyncRedis()
        entry = await retry_dlq_entry(r, "nonexistent")
        assert entry is None

    @pytest.mark.asyncio
    async def test_retry_no_payload(self):
        r = FakeAsyncRedis()
        await push_to_dlq(r, job_id="no-payload", error="fail")
        result = await retry_dlq_entry(r, "no-payload")
        assert result is None  # Cannot retry without original_payload


# ---------------------------------------------------------------------------
# DLQ discard
# ---------------------------------------------------------------------------


class TestDLQDiscard:
    @pytest.mark.asyncio
    async def test_discard_found(self):
        r = FakeAsyncRedis()
        await push_to_dlq(r, job_id="job-disc-1", error="fail")
        assert await discard_dlq_entry(r, "job-disc-1") is True
        assert await dlq_length(r) == 0

    @pytest.mark.asyncio
    async def test_discard_not_found(self):
        r = FakeAsyncRedis()
        assert await discard_dlq_entry(r, "nonexistent") is False


# ---------------------------------------------------------------------------
# Auto-retry sweep (sync)
# ---------------------------------------------------------------------------


class TestAutoRetrySweep:
    def test_retries_eligible_entries(self):
        r = FakeSyncRedis()
        # Add 2 retryable entries (retry_count < 3) and 1 exhausted (retry_count = 3)
        for i, rc in enumerate([0, 1, DLQ_MAX_RETRY_COUNT]):
            entry = json.dumps(
                {
                    "job_id": f"j-{i}",
                    "original_payload": {"url": f"https://test{i}.com", "job_id": f"j-{i}"},
                    "error": "fail",
                    "retry_count": rc,
                    "failed_at": datetime.now(timezone.utc).isoformat(),
                    "worker_id": "",
                }
            )
            r.rpush(DLQ_LIST_KEY, entry)
        result = auto_retry_dlq_sync(r)
        assert result["retried"] == 2
        assert result["skipped"] == 1
        assert result["errors"] == 0
        # Queue should have 2 re-enqueued (to tier-specific fast queue, since payloads have no tier)
        assert r.llen("audit_jobs:fast") == 2
        # DLQ should have 1 remaining (the exhausted one)
        assert result["total_remaining"] == 1

    def test_no_retry_without_payload(self):
        r = FakeSyncRedis()
        entry = json.dumps(
            {
                "job_id": "j-nopayload",
                "original_payload": {},
                "error": "fail",
                "retry_count": 0,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "worker_id": "",
            }
        )
        r.rpush(DLQ_LIST_KEY, entry)
        result = auto_retry_dlq_sync(r)
        assert result["retried"] == 0
        assert result["skipped"] == 1

    def test_empty_dlq(self):
        r = FakeSyncRedis()
        result = auto_retry_dlq_sync(r)
        assert result["retried"] == 0
        assert result["skipped"] == 0
        assert result["total_remaining"] == 0


# ---------------------------------------------------------------------------
# Orphaned key cleanup (sync)
# ---------------------------------------------------------------------------


class TestOrphanedKeyCleanup:
    def test_fixes_keys_without_ttl(self):
        r = FakeSyncRedis()
        # Create keys with different statuses but no TTL
        r.hset("audit:job:s1", mapping={"status": "succeeded"})
        r.hset("audit:job:f1", mapping={"status": "failed"})
        r.hset("audit:job:r1", mapping={"status": "running"})
        r.hset("audit:job:q1", mapping={"status": "queued"})
        r.hset("audit:job:u1", mapping={"status": ""})
        result = cleanup_orphaned_job_keys_sync(r)
        assert result["scanned"] == 5
        assert result["fixed"] == 5
        assert r._ttls["audit:job:s1"] == TTL_SUCCEEDED
        assert r._ttls["audit:job:f1"] == TTL_FAILED
        assert r._ttls["audit:job:r1"] == TTL_IN_PROGRESS
        assert r._ttls["audit:job:q1"] == TTL_QUEUED
        assert r._ttls["audit:job:u1"] == TTL_SUCCEEDED  # Unknown defaults to succeeded TTL

    def test_skips_keys_with_ttl(self):
        r = FakeSyncRedis()
        r.hset("audit:job:s1", mapping={"status": "succeeded"})
        r._ttls["audit:job:s1"] = 3600  # Already has TTL
        result = cleanup_orphaned_job_keys_sync(r)
        assert result["scanned"] == 1
        assert result["fixed"] == 0

    def test_skips_events_subkeys(self):
        r = FakeSyncRedis()
        r.hset("audit:job:e1:events", mapping={"type": "step"})
        result = cleanup_orphaned_job_keys_sync(r)
        assert result["scanned"] == 0  # Events subkeys skipped

    def test_empty_redis(self):
        r = FakeSyncRedis()
        result = cleanup_orphaned_job_keys_sync(r)
        assert result["scanned"] == 0
        assert result["fixed"] == 0


# ---------------------------------------------------------------------------
# build_dlq_payload_from_exception
# ---------------------------------------------------------------------------


class TestBuildDLQPayload:
    def test_builds_payload(self):
        try:
            raise ValueError("test error")
        except ValueError as exc:
            result = build_dlq_payload_from_exception(
                job_id="j-exc",
                original_payload={"url": "https://test.com"},
                exc=exc,
                retry_count=2,
                worker_id="w-1",
            )
        assert result["job_id"] == "j-exc"
        assert result["error"] == "test error"
        assert result["retry_count"] == 2
        assert result["worker_id"] == "w-1"
        assert "ValueError" in result["error_traceback"]
        assert result["original_payload"]["url"] == "https://test.com"

    def test_builds_payload_none_payload(self):
        result = build_dlq_payload_from_exception(
            job_id="j-none",
            original_payload=None,
            exc=RuntimeError("boom"),
        )
        assert result["original_payload"] is None
        assert result["error"] == "boom"
