"""SIGV2-1129: an automated competitor refresh is not the customer's scan.

A scheduled audit fans out one ``AuditJob`` per tracked competitor. Those jobs
were attributed to the customer and the billable filter looked only at
``user_id`` and ``created_at``, so a single schedule with five tracked
competitors took six scans out of a rolling 30-day allowance the customer never
spent. Scans are the only customer-facing limit, so that is a billing defect.

The fix counts positively: the allowance bills a job only when its write path
declared the job to be a scan the customer launched
(``AuditJob.scan_origin == 'customer'``). A competitor benchmark declares
``competitor_refresh`` and is never billed, and a job that declares nothing is
not billed either, which under-counts rather than charging a customer for
automation. That direction is asserted below so it cannot be flipped silently.

Every test here fails on the pre-fix code: the first three because the
competitor jobs were counted, the last two because ``scan_origin`` did not
exist at all.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from job_models import AuditJobPayload
from queue_worker import _enqueue_project_competitor_jobs
from services.project_competitive_service import MAX_PROJECT_COMPETITORS
from services.scan_allowance_service import (
    consume_scan_allowance,
    scan_allowance_snapshot,
)


class FakeRedis:
    """Only the four calls the competitor fan-out makes."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.queued: list[str] = []

    async def hset(self, key: str, mapping: dict) -> int:
        self.hashes[key] = {str(name): str(value) for name, value in mapping.items()}
        return len(mapping)

    async def rpush(self, _queue: str, payload: str) -> int:
        self.queued.append(payload)
        return len(self.queued)

    async def expire(self, _key: str, _ttl: int) -> bool:
        return True


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed(
    db: Session, *, competitor_count: int
) -> tuple[models.User, models.Project, models.Audit]:
    user = models.User(
        email="competitor-refresh@example.com",
        hashed_password="x",
        role="user",
        credits=500,
    )
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id="cus_sigv2_1129",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name="Benchmark Ops", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Alpha Client",
        domain_url="https://alpha.example",
        target_country="US",
        language="en",
        auto_competitor_audits_enabled=True,
    )
    db.add(project)
    db.flush()
    for index in range(competitor_count):
        db.add(
            models.ProjectCompetitor(
                project_id=project.id,
                target_url=f"https://rival{index}.example",
                normalized_domain=f"rival{index}.example",
                display_name=f"Rival {index}",
                auto_audit_enabled=True,
            )
        )
    source_audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://alpha.example",
        geo_score=70.0,
        seo_score=71.0,
        aeo_score=72.0,
        created_at=datetime.now(timezone.utc),
    )
    db.add(source_audit)
    db.commit()
    db.refresh(user)
    db.refresh(project)
    db.refresh(source_audit)
    return user, project, source_audit


def _customer_scan(
    db: Session,
    user: models.User,
    *,
    suffix: str,
    days_ago: float = 0.0,
) -> models.AuditJob:
    job = models.AuditJob(
        id=f"customer-scan-{suffix}",
        user_id=user.id,
        status="succeeded",
        audit_target_type=models.AuditTargetType.WEBSITE,
        url="https://alpha.example",
        request_id=f"audit-job:{suffix}",
        created_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        scan_origin=models.SCAN_ORIGIN_CUSTOMER,
    )
    db.add(job)
    db.commit()
    return job


def _run_scheduled_fan_out(
    db: Session,
    *,
    user: models.User,
    project: models.Project,
    source_audit: models.Audit,
    redis_client: FakeRedis,
) -> dict[str, object]:
    source_job = AuditJobPayload(
        job_id="scheduled-parent-job",
        request_id="scheduled-audit:1:scheduled-parent-job",
        user_id=user.id,
        url="https://alpha.example",
        provider="google",
        tier="fast",
        project_id=project.id,
        scheduled_audit_id=1,
        category="competitive benchmark",
    )
    return asyncio.run(
        _enqueue_project_competitor_jobs(
            redis_client=redis_client,
            db=db,
            source_job=source_job,
            source_audit=source_audit,
            project=project,
            user=user,
        )
    )


def _competitor_jobs(db: Session) -> list[models.AuditJob]:
    return (
        db.query(models.AuditJob)
        .filter(models.AuditJob.scan_origin == models.SCAN_ORIGIN_COMPETITOR_REFRESH)
        .all()
    )


def test_scheduled_refresh_bills_the_customer_scan_and_not_the_competitors() -> None:
    """One scheduled audit with five competitors costs one scan, not six."""
    db, engine = _build_db()
    try:
        user, project, source_audit = _seed(db, competitor_count=5)
        _customer_scan(db, user, suffix="scheduled-run")
        assert scan_allowance_snapshot(db, user).scans_used == 1

        redis_client = FakeRedis()
        result = _run_scheduled_fan_out(
            db,
            user=user,
            project=project,
            source_audit=source_audit,
            redis_client=redis_client,
        )

        assert result["status"] == "queued"
        assert len(result["queued_jobs"]) == 5
        assert len(redis_client.queued) == 5
        assert len(_competitor_jobs(db)) == 5
        assert db.query(models.AuditJob).count() == 6

        assert scan_allowance_snapshot(db, user).scans_used == 1
    finally:
        _cleanup(db, engine)


def test_snapshot_agrees_with_what_is_billed_across_a_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A customer told they have one scan left must still be able to spend it."""
    import services.audit_helpers as audit_helpers

    monkeypatch.setattr(
        audit_helpers,
        "resolve_plan_capabilities",
        lambda _user: {"max_audits": 6, "has_competitor_analysis": True},
    )

    db, engine = _build_db()
    try:
        user, project, source_audit = _seed(db, competitor_count=5)
        for index in range(5):
            _customer_scan(db, user, suffix=f"own-{index}")

        before = scan_allowance_snapshot(db, user)
        assert (before.scans_used, before.scans_remaining) == (5, 1)

        _run_scheduled_fan_out(
            db,
            user=user,
            project=project,
            source_audit=source_audit,
            redis_client=FakeRedis(),
        )

        after = scan_allowance_snapshot(db, user)
        assert (after.scans_used, after.scans_remaining) == (5, 1)
        # The promised last scan is actually spendable: before the fix the five
        # competitor jobs had already taken it and this raised 402.
        assert consume_scan_allowance(db, user).scans_remaining == 1

        _customer_scan(db, user, suffix="own-5")
        with pytest.raises(Exception) as exc_info:
            consume_scan_allowance(db, user)
        assert getattr(exc_info.value, "status_code", None) == 402
    finally:
        _cleanup(db, engine)


def test_fan_out_is_bounded_by_the_tracked_competitor_cap() -> None:
    """More competitor rows than the product allows must not queue more jobs."""
    db, engine = _build_db()
    try:
        over_cap = MAX_PROJECT_COMPETITORS + 4
        user, project, source_audit = _seed(db, competitor_count=over_cap)
        assert len(project.competitors) == over_cap

        redis_client = FakeRedis()
        result = _run_scheduled_fan_out(
            db,
            user=user,
            project=project,
            source_audit=source_audit,
            redis_client=redis_client,
        )

        assert result["competitor_cap"] == MAX_PROJECT_COMPETITORS
        assert len(result["queued_jobs"]) == MAX_PROJECT_COMPETITORS
        assert len(result["dropped_competitors"]) == over_cap - MAX_PROJECT_COMPETITORS
        assert len(redis_client.queued) == MAX_PROJECT_COMPETITORS
        assert len(_competitor_jobs(db)) == MAX_PROJECT_COMPETITORS
    finally:
        _cleanup(db, engine)


def test_an_undeclared_job_is_not_billed_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The chosen direction for an ambiguous row: under-count, and say so.

    A write path that creates an ``AuditJob`` without declaring an origin is a
    defect, and this asserts how it fails. Under-counting hands back a scan,
    which is visible and recoverable. Over-counting bills a customer for work
    they never requested, which is the defect this ticket exists to fix. Do not
    flip this to bill unclassified rows; declare the origin at the write path
    instead.
    """
    db, engine = _build_db()
    try:
        user, _project, _source_audit = _seed(db, competitor_count=1)
        db.add(
            models.AuditJob(
                id="undeclared-job",
                user_id=user.id,
                status="queued",
                audit_target_type=models.AuditTargetType.WEBSITE,
                url="https://alpha.example",
                request_id="audit-job:undeclared",
                created_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        with caplog.at_level(logging.WARNING, logger="services.scan_allowance_service"):
            snapshot = scan_allowance_snapshot(db, user)

        assert snapshot.scans_used == 0
        assert snapshot.reset_at is None
        assert "no declared scan origin" in caplog.text
    finally:
        _cleanup(db, engine)


def test_competitor_refresh_jobs_never_reach_the_billable_window() -> None:
    """Belt and braces on the counting rule itself, independent of the fan-out."""
    db, engine = _build_db()
    try:
        user, _project, _source_audit = _seed(db, competitor_count=1)
        for index in range(4):
            db.add(
                models.AuditJob(
                    id=f"benchmark-{index}",
                    user_id=user.id,
                    status="queued",
                    audit_target_type=models.AuditTargetType.WEBSITE,
                    url=f"https://rival{index}.example",
                    request_id=f"competitive-benchmark:1:{index}:job",
                    created_at=datetime.now(timezone.utc),
                    scan_origin=models.SCAN_ORIGIN_COMPETITOR_REFRESH,
                )
            )
        db.commit()
        assert scan_allowance_snapshot(db, user).scans_used == 0

        _customer_scan(db, user, suffix="single")
        snapshot = scan_allowance_snapshot(db, user)
        assert snapshot.scans_used == 1
        assert snapshot.reset_at is not None
    finally:
        _cleanup(db, engine)
