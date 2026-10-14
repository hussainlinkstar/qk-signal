"""Report library contracts (SIGV2-1130).

Three things this suite exists to pin, because each one was absent before:

* The library can be listed at all, newest first, with every approved column
  served from storage rather than recomputed per row.
* Link expiry is real. A succeeded report whose retention has run out reads as
  expired, and reads that way before anyone clicks the link.
* Delete is scoped to the caller. A report belonging to another account is not
  listed, not deletable, and its id is not confirmed back to the caller.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("SSM_ENABLED", "false")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base
from middleware import maintenance as maintenance_module
from routers import api_router as api_router_module
from services.report_library import resolve_report_link_expiry, resolve_report_name

RETENTION_DAYS = 30


class _RecordingStorageService:
    """Stands in for S3/local storage and records what was deleted."""

    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete_file(self, *, storage_uri: str) -> bool:
        self.deleted.append(storage_uri)
        return True


def _make_job(
    *,
    job_id: str,
    user_id: int,
    status: str,
    created_at: datetime,
    completed_at: datetime | None = None,
    name: str | None = None,
    report_kind: str | None = "standard",
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    file_path: str | None = None,
    file_size_bytes: int | None = None,
) -> models.ComplexReportJob:
    return models.ComplexReportJob(
        id=job_id,
        user_id=user_id,
        status=status,
        created_at=created_at,
        updated_at=created_at,
        completed_at=completed_at,
        name=name,
        period_start=period_start,
        period_end=period_end,
        file_path=file_path,
        file_size_bytes=file_size_bytes,
        export_manifest={"report_kind": report_kind} if report_kind else None,
    )


@pytest.fixture
def library_client(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    owner = models.User(
        email="library-owner@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    other = models.User(
        email="library-other@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add_all([owner, other])
    db.commit()
    db.refresh(owner)
    db.refresh(other)

    now = datetime.now(timezone.utc)
    jobs = [
        _make_job(
            job_id="report-succeeded-fresh",
            user_id=owner.id,
            status="succeeded",
            created_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=2),
            name="Standard report - 1 Apr 2026 to 30 Jun 2026",
            period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
            file_path="local://reports/fresh.pdf",
            file_size_bytes=2_516_582,
        ),
        _make_job(
            job_id="report-succeeded-stale",
            user_id=owner.id,
            status="succeeded",
            created_at=now - timedelta(days=RETENTION_DAYS + 5),
            completed_at=now - timedelta(days=RETENTION_DAYS + 5),
            name="Executive report - all time, 1 Sep 2026",
            file_path="local://reports/stale.pdf",
            file_size_bytes=1_024,
            report_kind="executive",
        ),
        _make_job(
            job_id="report-running",
            user_id=owner.id,
            status="running",
            created_at=now - timedelta(minutes=5),
            name="Standard report - all time, 5 Oct 2026",
        ),
        _make_job(
            job_id="report-failed",
            user_id=owner.id,
            status="failed",
            created_at=now - timedelta(days=1),
            completed_at=now - timedelta(days=1),
            name="Competitors report - all time, 4 Oct 2026",
            report_kind="competitors",
        ),
        _make_job(
            job_id="report-foreign",
            user_id=other.id,
            status="succeeded",
            created_at=now,
            completed_at=now,
            name="Standard report - all time, 5 Oct 2026",
            file_path="local://reports/foreign.pdf",
            file_size_bytes=4_096,
        ),
    ]
    db.add_all(jobs)
    db.commit()

    storage = _RecordingStorageService()
    monkeypatch.setattr(api_router_module, "get_storage_service", lambda: storage)
    monkeypatch.setattr(api_router_module, "get_report_retention_days", lambda _db: RETENTION_DAYS)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )

    def override_get_db():
        yield db

    def override_get_current_user():
        return owner

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    client = TestClient(main.app)
    try:
        yield client, db, storage, owner, other
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_library_lists_only_the_callers_reports_newest_first(library_client):
    client, _db, _storage, _owner, _other = library_client

    response = client.get("/api/v1/reports/complex")

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert [item["report_id"] for item in payload["items"]] == [
        "report-running",
        "report-succeeded-fresh",
        "report-failed",
        "report-succeeded-stale",
    ]
    assert "report-foreign" not in {item["report_id"] for item in payload["items"]}


def test_library_row_serves_every_approved_column_from_storage(library_client):
    client, _db, _storage, _owner, _other = library_client

    items = client.get("/api/v1/reports/complex").json()["items"]
    fresh = next(item for item in items if item["report_id"] == "report-succeeded-fresh")

    assert fresh["name"] == "Standard report - 1 Apr 2026 to 30 Jun 2026"
    assert fresh["report_kind"] == "standard"
    assert fresh["period_start"].startswith("2026-04-01")
    assert fresh["period_end"].startswith("2026-06-30")
    assert fresh["size_bytes"] == 2_516_582
    assert fresh["status"] == "succeeded"
    assert fresh["retention_days"] == RETENTION_DAYS
    assert fresh["link_expired"] is False
    assert fresh["link_expiry_days_remaining"] == RETENTION_DAYS - 1
    assert fresh["download_url"] == "/api/v1/reports/complex/report-succeeded-fresh/download"


def test_a_report_past_retention_reads_as_expired_before_anyone_clicks_it(library_client):
    client, _db, _storage, _owner, _other = library_client

    items = client.get("/api/v1/reports/complex").json()["items"]
    stale = next(item for item in items if item["report_id"] == "report-succeeded-stale")

    assert stale["link_expired"] is True
    assert stale["link_expiry_days_remaining"] == 0
    # No download link is offered for a link that is already dead. The whole
    # promise of the approved subtitle is that the customer learns this here
    # and not from a failed click.
    assert stale["download_url"] is None


def test_an_unfinished_report_offers_no_download_and_no_expiry(library_client):
    client, _db, _storage, _owner, _other = library_client

    items = client.get("/api/v1/reports/complex").json()["items"]
    running = next(item for item in items if item["report_id"] == "report-running")
    failed = next(item for item in items if item["report_id"] == "report-failed")

    for item in (running, failed):
        assert item["download_url"] is None
        assert item["expires_at"] is None
        assert item["link_expiry_days_remaining"] is None
        assert item["link_expired"] is False


def test_library_pagination_reports_the_full_total(library_client):
    client, _db, _storage, _owner, _other = library_client

    page = client.get("/api/v1/reports/complex", params={"limit": 2, "offset": 2}).json()

    assert page["total"] == 4
    assert page["limit"] == 2
    assert page["offset"] == 2
    assert [item["report_id"] for item in page["items"]] == [
        "report-failed",
        "report-succeeded-stale",
    ]


def test_delete_removes_the_row_and_the_stored_artifact(library_client):
    client, db, storage, _owner, _other = library_client

    response = client.delete("/api/v1/reports/complex/report-succeeded-fresh")

    assert response.status_code == 200
    assert response.json() == {"deleted": ["report-succeeded-fresh"], "not_found": []}
    assert storage.deleted == ["local://reports/fresh.pdf"]
    assert (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "report-succeeded-fresh")
        .first()
        is None
    )


def test_delete_refuses_another_accounts_report_and_leaves_it_intact(library_client):
    client, db, storage, _owner, _other = library_client

    response = client.delete("/api/v1/reports/complex/report-foreign")

    assert response.status_code == 404
    assert storage.deleted == []
    assert (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "report-foreign")
        .first()
        is not None
    )


def test_bulk_delete_removes_owned_rows_and_names_the_rest_as_not_found(library_client):
    client, db, storage, _owner, _other = library_client

    response = client.post(
        "/api/v1/reports/complex/delete",
        json={
            "report_ids": [
                "report-succeeded-fresh",
                "report-foreign",
                "report-does-not-exist",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted"] == ["report-succeeded-fresh"]
    assert payload["not_found"] == ["report-foreign", "report-does-not-exist"]
    assert storage.deleted == ["local://reports/fresh.pdf"]
    assert (
        db.query(models.ComplexReportJob)
        .filter(models.ComplexReportJob.id == "report-foreign")
        .first()
        is not None
    )


def test_bulk_delete_requires_at_least_one_id(library_client):
    client, _db, _storage, _owner, _other = library_client

    assert client.post("/api/v1/reports/complex/delete", json={"report_ids": []}).status_code == 422


def test_expired_download_is_still_refused_after_the_library_showed_it_as_expired(library_client):
    client, _db, _storage, _owner, _other = library_client

    response = client.get("/api/v1/reports/complex/report-succeeded-stale/download")

    assert response.status_code == 410


# ---------------------------------------------------------------------------
# Naming and period: resolved once at generation, never re-derived on read
# ---------------------------------------------------------------------------


def test_report_name_is_derived_from_kind_and_period():
    assert (
        resolve_report_name(
            report_kind="standard",
            period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
        )
        == "Standard report - 1 Apr 2026 to 30 Jun 2026"
    )
    assert (
        resolve_report_name(
            report_kind="executive",
            period_start=datetime(2026, 6, 1, tzinfo=timezone.utc),
            period_end=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        == "Executive report - 1 Jun 2026"
    )


def test_a_report_without_a_period_is_named_from_its_generation_date():
    # Deliberately not named from the minimum and maximum of the selected
    # audits: that would label an all-time report with an interval the customer
    # never asked for.
    assert (
        resolve_report_name(
            report_kind="competitors",
            generated_at=datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc),
        )
        == "Competitors report - all time, 5 Oct 2026"
    )


def test_an_unknown_kind_is_named_without_inventing_one():
    assert resolve_report_name(
        report_kind=None,
        generated_at=datetime(2026, 10, 5, tzinfo=timezone.utc),
    ).startswith("Report report - ")


def test_generate_persists_the_name_and_period_and_leaves_them_frozen(library_client):
    client, db, _storage, owner, _other = library_client

    created_at = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    job = _make_job(
        job_id="report-frozen",
        user_id=owner.id,
        status="succeeded",
        created_at=created_at,
        completed_at=created_at,
        name="Standard report - 1 Apr 2026 to 30 Jun 2026",
        period_start=datetime(2026, 4, 1, tzinfo=timezone.utc),
        period_end=datetime(2026, 6, 30, tzinfo=timezone.utc),
    )
    db.add(job)
    db.commit()

    items = client.get("/api/v1/reports/complex").json()["items"]
    frozen = next(item for item in items if item["report_id"] == "report-frozen")

    # Served verbatim from the row, not rebuilt from kind plus period on read.
    assert frozen["name"] == "Standard report - 1 Apr 2026 to 30 Jun 2026"


def test_a_row_predating_the_name_column_still_renders_a_name(library_client):
    client, db, _storage, owner, _other = library_client

    created_at = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)
    db.add(
        _make_job(
            job_id="report-legacy",
            user_id=owner.id,
            status="succeeded",
            created_at=created_at,
            completed_at=created_at,
            name=None,
            report_kind="financial",
        )
    )
    db.commit()

    items = client.get("/api/v1/reports/complex").json()["items"]
    legacy = next(item for item in items if item["report_id"] == "report-legacy")

    assert legacy["name"] == "Financial report - all time, 20 Aug 2026"


# ---------------------------------------------------------------------------
# Expiry arithmetic, independent of the HTTP layer
# ---------------------------------------------------------------------------


def test_expiry_counts_from_completion_not_from_request_time():
    now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
    job = _make_job(
        job_id="x",
        user_id=1,
        status="succeeded",
        created_at=now - timedelta(days=20),
        completed_at=now - timedelta(days=4),
    )

    expiry = resolve_report_link_expiry(job, retention_days=7, now=now)

    assert expiry.expired is False
    assert expiry.days_remaining == 3
    assert expiry.expires_at == job.completed_at + timedelta(days=7)


def test_an_already_expired_job_needs_no_arithmetic():
    job = _make_job(
        job_id="x",
        user_id=1,
        status="expired",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    expiry = resolve_report_link_expiry(job, retention_days=30)

    assert expiry.expired is True
    assert expiry.days_remaining == 0
    assert expiry.expires_at is None
