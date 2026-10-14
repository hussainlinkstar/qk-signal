from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.performance_snapshots import PerformanceSnapshotService, PerformanceSyncWorker


class _FakePerformanceService:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def get_performance_metrics(self, _url: str, include_seo: bool = False):
        self.calls += 1
        if self.responses:
            response = self.responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        return {"status": "success", "performance_score": 88, "include_seo": include_seo}


@pytest.fixture
def sqlite_session(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    SessionTesting = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionTesting()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_snapshot_updates_existing_row(sqlite_session):
    service = PerformanceSnapshotService(_FakePerformanceService([]))
    normalized = service.normalize_url("https://Example.com/")

    first = service.upsert_snapshot(
        sqlite_session,
        normalized_url=normalized,
        snapshot_date=date.today(),
        metrics_payload={"status": "success", "performance_score": 50},
        source_status="success",
    )
    second = service.upsert_snapshot(
        sqlite_session,
        normalized_url=normalized,
        snapshot_date=date.today(),
        metrics_payload={"status": "success", "performance_score": 87},
        source_status="success",
    )

    rows = sqlite_session.query(models.PerformanceSnapshot).all()
    assert len(rows) == 1
    assert first.id == second.id
    assert rows[0].metrics_payload["performance_score"] == 87


@pytest.mark.asyncio
async def test_dedupes_same_day_fetch(sqlite_session):
    perf = _FakePerformanceService([{"status": "success", "performance_score": 91}])
    service = PerformanceSnapshotService(perf)

    first = await service.get_or_fetch_snapshot(sqlite_session, url="https://example.com")
    second = await service.get_or_fetch_snapshot(sqlite_session, url="https://example.com")

    assert first.metrics["performance_score"] == 91
    assert second.metrics["performance_score"] == 91
    assert perf.calls == 1


@pytest.mark.asyncio
async def test_sync_worker_handles_quota_limited_response_without_retry(
    sqlite_session, monkeypatch
):
    perf = _FakePerformanceService(
        [
            {
                "status": "error",
                "message": "Quota exceeded for this API",
                "performance_score": 0,
            }
        ]
    )
    snapshot_service = PerformanceSnapshotService(perf)
    worker = PerformanceSyncWorker(snapshot_service, max_retries=3, min_interval_seconds=0.0)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float):
        sleeps.append(seconds)

    monkeypatch.setattr("services.performance_snapshots.asyncio.sleep", _fake_sleep)

    synced = await worker.sync_url(sqlite_session, url="https://example.com")

    assert synced is False
    assert perf.calls == 1
    assert sleeps == []
