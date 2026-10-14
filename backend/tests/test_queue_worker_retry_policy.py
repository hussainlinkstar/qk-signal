import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import asyncio

import pytest
from fastapi import HTTPException

import queue_worker
from job_models import parse_job_payload


class _FakeCounter:
    def labels(self, *_args, **_kwargs):
        return self

    def inc(self):
        return None


class _FakeRedis:
    """Minimal async Redis fake covering the methods _process_job_with_retries
    (and the DLQ helpers it calls) exercise."""

    def __init__(self):
        self.hset_calls: list[tuple[str, dict]] = []
        self.hincrby_calls: list[tuple[str, str, int]] = []
        self.rpush_calls: list[tuple[str, tuple]] = []
        self._lists: dict[str, list] = {}

    async def hset(self, key: str, mapping: dict):
        self.hset_calls.append((key, mapping))

    async def hincrby(self, key: str, field: str, amount: int = 1):
        self.hincrby_calls.append((key, field, amount))

    async def hincrbyfloat(self, _key: str, _field: str, _amount: float):
        return None

    async def hget(self, _key: str, _field: str):
        return None

    async def rpush(self, key: str, *values):
        self.rpush_calls.append((key, values))
        self._lists.setdefault(key, []).extend(values)
        return len(self._lists[key])

    async def expire(self, _key: str, _ttl: int):
        return None

    async def close(self):
        return None

    async def aclose(self):
        return None


def _make_job(tier: str = "starter"):
    payload = {
        "job_id": "job-1",
        "request_id": "req-1",
        "user_id": 1,
        "url": "https://example.com",
        "provider": "google",
        "tier": tier,
    }
    return payload, parse_job_payload(payload)


@pytest.mark.asyncio
async def test_does_not_retry_non_retryable_http_exception(monkeypatch):
    """A 422 (non-retryable) must fail immediately: handle_job called once,
    no backoff sleep, job marked failed."""
    fake_redis = _FakeRedis()
    payload, job = _make_job()
    attempts = {"count": 0}

    async def _fake_handle_job(_redis_client, _job, **_kwargs):
        attempts["count"] += 1
        raise HTTPException(status_code=422, detail="invalid job input")

    async def _fake_sleep(_seconds: float):
        raise AssertionError("sleep should not be called for non-retryable HTTP errors")

    monkeypatch.setattr(queue_worker, "handle_job", _fake_handle_job)
    monkeypatch.setattr(queue_worker, "worker_job_events_total", _FakeCounter())
    monkeypatch.setattr(queue_worker.asyncio, "sleep", _fake_sleep)

    queue_worker.shutdown_requested = False
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    try:
        await queue_worker._process_job_with_retries(fake_redis, semaphore, payload, job)
    finally:
        queue_worker.shutdown_requested = False

    assert attempts["count"] == 1
    failed_writes = [m for _k, m in fake_redis.hset_calls if m.get("status") == "failed"]
    assert failed_writes
    assert failed_writes[-1]["error"] == "invalid job input"


@pytest.mark.asyncio
async def test_retries_retryable_http_exception_until_success(monkeypatch):
    """A retryable 503 then success: handle_job retried, job not left failed."""
    fake_redis = _FakeRedis()
    payload, job = _make_job()
    calls = {"count": 0}

    async def _fake_handle_job(_redis_client, _job, **_kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise HTTPException(status_code=503, detail="temporary outage")
        return None

    async def _fast_sleep(_seconds: float):
        return None

    monkeypatch.setattr(queue_worker, "handle_job", _fake_handle_job)
    monkeypatch.setattr(queue_worker, "worker_job_events_total", _FakeCounter())
    monkeypatch.setattr(queue_worker.asyncio, "sleep", _fast_sleep)

    queue_worker.shutdown_requested = False
    semaphore = asyncio.Semaphore(1)
    await semaphore.acquire()
    await queue_worker._process_job_with_retries(fake_redis, semaphore, payload, job)

    assert calls["count"] == 2
    failed_writes = [m for _k, m in fake_redis.hset_calls if m.get("status") == "failed"]
    assert not failed_writes
