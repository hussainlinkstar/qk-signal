from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
from services.project_competitive_service import (
    add_project_competitor,
    build_project_competitive_analysis,
    build_project_competitive_gaps,
    build_project_competitive_trends,
    list_project_competitors,
    mark_project_competitor_snapshot_succeeded,
)


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


def _seed_project(db: Session) -> tuple[models.User, models.Project]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=500)
    db.add(owner)
    db.flush()
    db.add(
        models.Subscription(
            user_id=owner.id,
            stripe_customer_id="cus_competitive",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name="Competitive Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Alpha Client",
        domain_url="https://alpha.example",
        target_country="US",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(owner)
    db.refresh(project)
    return owner, project


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    site_id: int | None = None,
    url: str,
    geo: float,
    seo: float,
    aeo: float,
    created_at: datetime,
    request_id: str | None = None,
    citation_share: float | None = None,
    performance: float | None = None,
    schema_coverage: float | None = None,
    # SIGV2-1117: a competitor benchmark carries the project's id too, so the
    # fixture has to declare which side of the benchmark it is building.
    project_scope: str = models.AUDIT_PROJECT_SCOPE_OWN,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=project_scope,
        site_id=site_id,
        url=url,
        geo_score=geo,
        seo_score=seo,
        aeo_score=aeo,
        request_id=request_id,
        created_at=created_at,
        full_report={
            "metadata": {
                "audit_outcome": "completed",
                "provider": "google",
                "category": "benchmark",
            },
            "geo": {"citation_share": citation_share or 0},
            "seo": {"performance": performance or 0},
            "aeo": {"schema_coverage": {"coverage_percent": schema_coverage or 0}},
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def test_competitive_analysis_gaps_and_trends_are_built_from_project_snapshots() -> None:
    db, engine = _build_db()
    try:
        owner, project = _seed_project(db)
        competitor_a = add_project_competitor(
            db, project=project, target_url="https://comp-a.example", display_name="Comp A"
        )
        competitor_b = add_project_competitor(
            db, project=project, target_url="https://comp-b.example", display_name="Comp B"
        )
        db.commit()

        previous_source = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url=project.domain_url or "https://alpha.example",
            geo=70,
            seo=74,
            aeo=55,
            citation_share=21,
            performance=61,
            schema_coverage=18,
            created_at=datetime.now(timezone.utc) - timedelta(days=14),
            request_id="scheduled-audit:prev",
        )
        current_source = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url=project.domain_url or "https://alpha.example",
            geo=78,
            seo=80,
            aeo=62,
            citation_share=34,
            performance=72,
            schema_coverage=22,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            request_id="scheduled-audit:current",
        )

        previous_comp_a = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_COMPETITOR,
            url="https://comp-a.example",
            geo=83,
            seo=76,
            aeo=79,
            citation_share=44,
            performance=66,
            schema_coverage=72,
            created_at=previous_source.created_at + timedelta(minutes=10),
        )
        current_comp_a = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_COMPETITOR,
            url="https://comp-a.example",
            geo=88,
            seo=75,
            aeo=82,
            citation_share=51,
            performance=65,
            schema_coverage=84,
            created_at=current_source.created_at + timedelta(minutes=10),
        )
        current_comp_b = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_COMPETITOR,
            url="https://comp-b.example",
            geo=70,
            seo=90,
            aeo=58,
            citation_share=26,
            performance=81,
            schema_coverage=25,
            created_at=current_source.created_at + timedelta(minutes=12),
        )

        mark_project_competitor_snapshot_succeeded(
            db,
            project_id=project.id,
            competitor_id=competitor_a.id,
            source_audit_id=previous_source.id,
            competitor_audit=previous_comp_a,
        )
        mark_project_competitor_snapshot_succeeded(
            db,
            project_id=project.id,
            competitor_id=competitor_a.id,
            source_audit_id=current_source.id,
            competitor_audit=current_comp_a,
        )
        mark_project_competitor_snapshot_succeeded(
            db,
            project_id=project.id,
            competitor_id=competitor_b.id,
            source_audit_id=current_source.id,
            competitor_audit=current_comp_b,
        )
        db.commit()

        analysis = build_project_competitive_analysis(db, project=project)
        assert analysis["rank"]["geo"] == 2
        assert analysis["rank"]["seo"] == 2
        assert analysis["rank"]["aeo"] == 2
        assert analysis["benchmark_status"]["configured_competitors"] == 2
        assert analysis["competitors"][0]["scores"]["overall"] is not None

        gaps = build_project_competitive_gaps(db, project=project)
        assert gaps["summary"]["gap_count"] == 3
        assert gaps["summary"]["largest_gap_metric"] == "aeo"
        assert any(
            gap["competitor_name"] == "Comp A" and gap["metric"] == "aeo" for gap in gaps["gaps"]
        )
        assert any(
            gap["competitor_name"] == "Comp B" and gap["metric"] == "seo" for gap in gaps["gaps"]
        )

        trends = build_project_competitive_trends(db, project=project, period="all", metric="geo")
        assert trends["metric"] == "geo"
        assert len(trends["lines"]) == 3
        assert len(trends["lines"][0]["points"]) == 2
    finally:
        _cleanup(db, engine)


def test_list_project_competitors_exposes_competitor_site_id_from_latest_snapshot() -> None:
    db, engine = _build_db()
    try:
        owner, project = _seed_project(db)
        source_site = models.Site(user_id=owner.id, domain="alpha.example", display_name="Alpha")
        competitor_site = models.Site(
            user_id=owner.id, domain="comp-a.example", display_name="Comp A"
        )
        db.add_all([source_site, competitor_site])
        db.commit()
        db.refresh(source_site)
        db.refresh(competitor_site)

        competitor = add_project_competitor(
            db,
            project=project,
            target_url="https://comp-a.example",
            display_name="Comp A",
        )
        db.commit()

        source_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=source_site.id,
            url=project.domain_url or "https://alpha.example",
            geo=78,
            seo=80,
            aeo=62,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        competitor_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=competitor_site.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_COMPETITOR,
            url="https://comp-a.example",
            geo=83,
            seo=76,
            aeo=79,
            created_at=datetime.now(timezone.utc),
        )
        mark_project_competitor_snapshot_succeeded(
            db,
            project_id=project.id,
            competitor_id=competitor.id,
            source_audit_id=source_audit.id,
            competitor_audit=competitor_audit,
        )
        db.commit()

        rows = list_project_competitors(db, project=project)
        assert len(rows) == 1
        assert rows[0]["competitor_site_id"] == competitor_site.id
    finally:
        _cleanup(db, engine)


def test_scheduled_competitor_jobs_create_pending_snapshots_and_queue_payloads() -> None:
    db, engine = _build_db()
    try:
        owner, project = _seed_project(db)
        competitor_a = add_project_competitor(
            db, project=project, target_url="https://comp-a.example"
        )
        competitor_b = add_project_competitor(
            db, project=project, target_url="https://comp-b.example"
        )
        db.commit()

        source_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url=project.domain_url or "https://alpha.example",
            geo=78,
            seo=80,
            aeo=62,
            created_at=datetime.now(timezone.utc),
            request_id="scheduled-audit:test",
        )

        job = AuditJobPayload(
            job_id="source-job",
            request_id="scheduled-audit:test:job",
            user_id=owner.id,
            url=project.domain_url or "https://alpha.example",
            provider="google",
            tier="fast",
            project_id=project.id,
            scheduled_audit_id=77,
            charge_credits=False,
            category="benchmark",
        )

        class _FakeRedis:
            def __init__(self) -> None:
                self.hashes: list[tuple[str, dict[str, str]]] = []
                self.payloads: list[str] = []
                self.expirations: list[tuple[str, int]] = []

            async def hset(self, key: str, mapping: dict[str, str]) -> None:
                self.hashes.append((key, mapping))

            async def rpush(self, _queue: str, payload: str) -> None:
                self.payloads.append(payload)

            async def expire(self, _key: str, _ttl: int) -> None:
                # Enqueue path calls set_ttl_queued() -> redis.expire() on each job hash.
                self.expirations.append((_key, _ttl))

        fake_redis = _FakeRedis()
        result = asyncio.run(
            _enqueue_project_competitor_jobs(
                redis_client=fake_redis,  # type: ignore[arg-type]
                db=db,
                source_job=job,
                source_audit=source_audit,
                project=project,
                user=owner,
            )
        )

        pending = (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(models.ProjectCompetitorSnapshot.source_audit_id == source_audit.id)
            .all()
        )
        queued_jobs = (
            db.query(models.AuditJob)
            .filter(models.AuditJob.request_id.like("competitive-benchmark:%"))
            .all()
        )

        assert result["status"] == "queued"
        assert len(result["queued_jobs"]) == 2
        assert len(pending) == 2
        assert {row.status for row in pending} == {"pending"}
        assert len(queued_jobs) == 2
        assert len(fake_redis.payloads) == 2
        assert {row.competitor_id for row in pending} == {competitor_a.id, competitor_b.id}
    finally:
        _cleanup(db, engine)
