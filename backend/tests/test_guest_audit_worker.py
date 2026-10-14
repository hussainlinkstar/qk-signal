"""Tests for the queued guest audit runner and the degraded-run report."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import guest_audit_worker  # noqa: E402
from services.guest_audit_service import build_degradation_report  # noqa: E402
from services.url_validation import SSRFBlockedError  # noqa: E402


class _RecordingStore:
    def __init__(self) -> None:
        self.running: list[str] = []
        self.completed: list[tuple[str, dict]] = []
        self.failed: list[tuple[str, str]] = []

    async def mark_running(self, job_id):
        self.running.append(job_id)

    async def mark_completed(self, job_id, result):
        self.completed.append((job_id, result))

    async def mark_failed(self, job_id, error_code):
        self.failed.append((job_id, error_code))


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _RecordingStore:
    recorder = _RecordingStore()
    monkeypatch.setattr(guest_audit_worker, "mark_running", recorder.mark_running)
    monkeypatch.setattr(guest_audit_worker, "mark_completed", recorder.mark_completed)
    monkeypatch.setattr(guest_audit_worker, "mark_failed", recorder.mark_failed)
    monkeypatch.setattr(guest_audit_worker, "SessionLocal", lambda: _FakeSession())
    return recorder


class _FakeSession:
    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass


def _job_payload(**overrides) -> dict:
    payload = {
        "job_id": "job-1",
        "audit_target_type": "website",
        "target_url": "https://example.com",
        "target_name": "",
        "target_metadata": "{}",
        "email": "",
        "ip_hash": "hash",
        "user_agent_hash": "",
        "referrer": "",
        "request_id": "req-1",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_a_successful_run_stores_the_projected_result(store, monkeypatch):
    async def fake_run(db, **kwargs):
        _ = db, kwargs
        return {
            "intelligence_summary": "Looks fine.",
            "scores": {"overall": 60, "seo": 60, "geo": 60, "aeo": 60},
            "guest_audit_token": "tok",
            "request_id": "req-internal",
            "performance": {"internal": True},
            "metadata": {"created_at": "2026-09-09T00:00:00+00:00"},
        }

    monkeypatch.setattr(guest_audit_worker, "run_guest_audit", fake_run)

    await guest_audit_worker.process_guest_audit_job(_job_payload())

    assert store.running == ["job-1"]
    assert store.failed == []
    job_id, result = store.completed[0]
    assert job_id == "job-1"
    # Stored through the allowlist, so the internal sections never reach Redis.
    assert "performance" not in result
    assert "request_id" not in result
    assert result["scores"]["overall"] == 60


@pytest.mark.asyncio
async def test_a_target_blocked_at_run_time_is_reported_as_such(store, monkeypatch):
    """DNS can change between submission and execution, so the pipeline can
    still refuse a target that validated cleanly at submit time."""

    async def fake_run(db, **kwargs):
        _ = db, kwargs
        raise SSRFBlockedError("Private or reserved network targets are not allowed.")

    monkeypatch.setattr(guest_audit_worker, "run_guest_audit", fake_run)

    await guest_audit_worker.process_guest_audit_job(_job_payload())

    assert store.failed == [("job-1", "target_blocked")]
    assert store.completed == []


@pytest.mark.asyncio
async def test_an_unexpected_failure_is_reported_without_leaking_the_exception(store, monkeypatch):
    async def fake_run(db, **kwargs):
        _ = db, kwargs
        raise RuntimeError("postgres connection string is postgres://user:pw@db/signal")

    monkeypatch.setattr(guest_audit_worker, "run_guest_audit", fake_run)

    await guest_audit_worker.process_guest_audit_job(_job_payload())

    assert store.failed == [("job-1", "internal_error")]


@pytest.mark.asyncio
async def test_a_run_that_exceeds_the_budget_is_reported_as_a_timeout(store, monkeypatch):
    async def fake_run(db, **kwargs):
        _ = db, kwargs
        await asyncio.sleep(5)

    monkeypatch.setattr(guest_audit_worker, "run_guest_audit", fake_run)
    monkeypatch.setattr(guest_audit_worker, "resolve_job_timeout_seconds", lambda: 0.01)

    await guest_audit_worker.process_guest_audit_job(_job_payload())

    assert store.failed == [("job-1", "timeout")]


@pytest.mark.asyncio
async def test_a_payload_without_a_job_id_is_dropped(store, monkeypatch):
    async def fake_run(db, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("the audit must not run for an unidentifiable job")

    monkeypatch.setattr(guest_audit_worker, "run_guest_audit", fake_run)

    await guest_audit_worker.process_guest_audit_job(_job_payload(job_id=""))

    assert store.running == []
    assert store.completed == []
    assert store.failed == []


# ---------------------------------------------------------------------------
# Degraded runs
# ---------------------------------------------------------------------------


def test_a_firecrawl_run_is_reported_as_fully_measured():
    report = build_degradation_report(
        target_url="https://example.com",
        scrape_method="firecrawl",
        scrape_succeeded=True,
        screenshot_captured=True,
        performance_metrics={"status": "ok", "performance_score": 80},
        ai_analysis_available=True,
    )

    assert report["fully_measured"] is True
    assert report["javascript_rendered"] is True
    assert report["reasons"] == []


def test_the_fallback_fetch_is_reported_as_a_degraded_run():
    """Firecrawl credits are exhausted, so this is the common case today: the
    score is understated and the response has to say so."""
    report = build_degradation_report(
        target_url="https://example.com",
        scrape_method="fallback",
        scrape_succeeded=True,
        screenshot_captured=False,
        performance_metrics={"status": "ok", "performance_score": 80},
        ai_analysis_available=True,
    )

    assert report["fully_measured"] is False
    assert report["javascript_rendered"] is False
    assert [reason["code"] for reason in report["reasons"]] == ["javascript_not_rendered"]


def test_a_failed_scrape_is_reported_rather_than_scored_silently():
    report = build_degradation_report(
        target_url="https://example.com",
        scrape_method=None,
        scrape_succeeded=False,
        screenshot_captured=False,
        performance_metrics={"status": "error"},
        ai_analysis_available=False,
    )

    codes = [reason["code"] for reason in report["reasons"]]
    assert codes == [
        "content_unavailable",
        "performance_unavailable",
        "ai_analysis_unavailable",
    ]
    assert report["fully_measured"] is False


def test_a_brand_audit_without_a_url_is_not_penalised_for_missing_page_signals():
    report = build_degradation_report(
        target_url=None,
        scrape_method=None,
        scrape_succeeded=False,
        screenshot_captured=False,
        performance_metrics={"status": "skipped"},
        ai_analysis_available=True,
    )

    assert report["fully_measured"] is True
    assert report["content_source"] == "not_applicable"
