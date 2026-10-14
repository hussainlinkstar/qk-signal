"""SIGV2-1117: a competitor's scores must never be read as the project's own.

A competitor benchmark is stored with ``Audit.project_id`` set to the customer's
own project. The previous code told the two apart by subtracting the competitor
audit ids recorded on ``project_competitor_snapshots``, which fails open:

  * a ``lite-refresh`` benchmark never writes a snapshot at all, so nothing
    excluded it
  * deleting a competitor cascades its snapshots away, which moved that
    competitor's audit into the project's own history permanently

Every test below fails on the pre-fix code and passes with the positive
``Audit.project_scope`` predicate.
"""

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
from job_models import AuditJobPayload, parse_job_payload
from queue_worker import _enqueue_competitor_lite_refresh_jobs
from services.portal_service import get_audit_for_project, list_project_audits_paginated
from services.project_audit_scope import (
    AUDIT_PROJECT_SCOPE_COMPETITOR,
    AUDIT_PROJECT_SCOPE_OWN,
    declare_audit_project_scope,
    is_own_project_audit,
    resolve_audit_project_scope,
)
from services.project_competitive_service import (
    add_project_competitor,
    build_project_competitive_analysis,
    build_project_competitive_trends,
    delete_project_competitor,
    get_latest_project_competitive_source_audit,
    list_project_competitive_source_audits,
    mark_project_competitor_snapshot_succeeded,
)
from services.project_intelligence_service import select_project_module_audit
from services.project_progress_service import (
    build_project_period_comparison,
    build_project_trend_payload,
)
from services.workspace_intelligence_service import get_client_health

LITE_REFRESH_REQUEST_ID = "lite-refresh:1:2:job"


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


def _seed_project(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=500)
    db.add(owner)
    db.flush()
    db.add(
        models.Subscription(
            user_id=owner.id,
            stripe_customer_id="cus_scope",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name="Scope Ops", owner_id=owner.id)
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
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    url: str,
    geo: float,
    seo: float,
    aeo: float,
    created_at: datetime,
    project_scope: str,
    request_id: str | None = None,
    site_id: int | None = None,
    audit_type: models.AuditType = models.AuditType.FAST,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=project_scope,
        site_id=site_id,
        url=url,
        audit_type=audit_type,
        geo_score=geo,
        seo_score=seo,
        aeo_score=aeo,
        request_id=request_id,
        created_at=created_at,
        full_report={"metadata": {"audit_outcome": "completed"}},
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


# ---------------------------------------------------------------------------
# 1. A competitor lite-refresh audit, with no snapshot, is excluded everywhere
# ---------------------------------------------------------------------------


def test_competitor_lite_refresh_audit_without_snapshot_is_excluded_from_project_history() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project(db)
        now = datetime.now(timezone.utc)

        own_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://alpha.example",
            geo=70,
            seo=74,
            aeo=66,
            created_at=now - timedelta(days=2),
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            request_id="scheduled-audit:own",
        )
        # The contaminating row: a competitor benchmarked through the lite
        # refresh path. It is newer than the project's own audit and it has no
        # competitor snapshot, so nothing excluded it before this fix.
        competitor_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://comp-a.example",
            geo=0,
            seo=12,
            aeo=0,
            created_at=now - timedelta(hours=1),
            project_scope=AUDIT_PROJECT_SCOPE_COMPETITOR,
            request_id=LITE_REFRESH_REQUEST_ID,
        )
        assert (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(models.ProjectCompetitorSnapshot.competitor_audit_id == competitor_audit.id)
            .count()
            == 0
        )

        # Score history
        history = list_project_competitive_source_audits(db, project_id=project.id)
        assert [audit.id for audit in history] == [own_audit.id]

        rows, total = list_project_audits_paginated(db, project_id=project.id)
        assert total == 1
        assert [row.id for row in rows] == [own_audit.id]
        assert get_audit_for_project(db, project_id=project.id).id == own_audit.id
        assert (
            get_audit_for_project(db, project_id=project.id, audit_id=competitor_audit.id) is None
        )

        # Latest project audit, the row every "current score" panel reads
        latest = get_latest_project_competitive_source_audit(db, project_id=project.id)
        assert latest is not None
        assert latest.id == own_audit.id
        assert latest.seo_score == 74

        selection = select_project_module_audit(db, project_id=project.id, module="seo")
        assert selection.latest_audit is not None
        assert selection.latest_audit.id == own_audit.id

        health = get_client_health(db, workspace_id=workspace.id)
        assert len(health) == 1
        assert health[0]["latest_seo_score"] == 74
        assert health[0]["latest_geo_score"] == 70
        assert health[0]["latest_aeo_score"] == 66

        # Trend
        trend = build_project_trend_payload(
            db, project_id=project.id, period="30d", granularity="daily"
        )
        assert trend["summary"]["latest"]["seo"] == 74
        assert all(point["audit_count"] == 1 for point in trend["data_points"])

        competitive_trend = build_project_competitive_trends(
            db, project=project, period="all", metric="seo"
        )
        project_line = next(line for line in competitive_trend["lines"] if line["is_project"])
        assert [point["value"] for point in project_line["points"]] == [74]

        # 30-day change
        comparison = build_project_period_comparison(db, project_id=project.id, period="30d")
        assert comparison["current_period"]["seo"] == 74
        assert comparison["current_period"]["audit_count"] == 1

        # Rank
        analysis = build_project_competitive_analysis(db, project=project)
        assert analysis["project"]["scores"]["seo"] == 74
        assert analysis["project"]["scores"]["geo"] == 70
        assert analysis["rank"]["seo"] == 1
        assert analysis["rank"]["overall"] == 1
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# 2. Removing a competitor must not move its audit into the project's history
# ---------------------------------------------------------------------------


def test_deleting_a_competitor_does_not_move_its_audit_into_project_history() -> None:
    db, engine = _build_db()
    try:
        owner, _workspace, project = _seed_project(db)
        now = datetime.now(timezone.utc)

        competitor = add_project_competitor(
            db, project=project, target_url="https://comp-a.example", display_name="Comp A"
        )
        db.commit()

        own_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://alpha.example",
            geo=70,
            seo=74,
            aeo=66,
            created_at=now - timedelta(days=2),
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            request_id="scheduled-audit:own",
        )
        competitor_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://comp-a.example",
            geo=0,
            seo=12,
            aeo=0,
            created_at=now - timedelta(hours=1),
            project_scope=AUDIT_PROJECT_SCOPE_COMPETITOR,
            request_id="competitive-benchmark:1:1:job",
        )
        mark_project_competitor_snapshot_succeeded(
            db,
            project_id=project.id,
            competitor_id=competitor.id,
            source_audit_id=own_audit.id,
            competitor_audit=competitor_audit,
        )
        db.commit()

        assert [
            audit.id for audit in list_project_competitive_source_audits(db, project_id=project.id)
        ] == [own_audit.id]

        # Removing the competitor cascades the snapshot away, which is what used
        # to leave its audit inside the project's own history for good.
        delete_project_competitor(db, project=project, competitor_id=competitor.id)
        db.commit()
        assert (
            db.query(models.ProjectCompetitorSnapshot)
            .filter(models.ProjectCompetitorSnapshot.project_id == project.id)
            .count()
            == 0
        )
        assert db.query(models.Audit).filter(models.Audit.id == competitor_audit.id).count() == 1

        history = list_project_competitive_source_audits(db, project_id=project.id)
        assert [audit.id for audit in history] == [own_audit.id]

        latest = get_latest_project_competitive_source_audit(db, project_id=project.id)
        assert latest is not None
        assert latest.id == own_audit.id

        comparison = build_project_period_comparison(db, project_id=project.id, period="30d")
        assert comparison["current_period"]["seo"] == 74
        assert comparison["current_period"]["audit_count"] == 1

        analysis = build_project_competitive_analysis(db, project=project)
        assert analysis["project"]["scores"]["seo"] == 74
        assert analysis["rank"]["seo"] == 1
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# 3. The positive predicate must not under-count the project's own audits
# ---------------------------------------------------------------------------


def test_every_legitimate_project_audit_kind_and_depth_is_still_found() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project(db)
        now = datetime.now(timezone.utc)

        expected_ids: list[int] = []
        for index, audit_type in enumerate(
            (
                models.AuditType.FAST,
                models.AuditType.SMART,
                models.AuditType.STANDARD,
                models.AuditType.DEEP,
            )
        ):
            audit = _create_audit(
                db,
                user_id=owner.id,
                project_id=project.id,
                url="https://alpha.example",
                geo=60 + index,
                seo=60 + index,
                aeo=60 + index,
                created_at=now - timedelta(days=10 - index),
                project_scope=AUDIT_PROJECT_SCOPE_OWN,
                request_id=f"scheduled-audit:{audit_type.value}",
                audit_type=audit_type,
            )
            expected_ids.append(audit.id)

        # A brand audit of the project itself, with no URL at all.
        brand_audit = models.Audit(
            user_id=owner.id,
            project_id=project.id,
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            audit_target_type=models.AuditTargetType.BRAND,
            target_name="Alpha Client",
            url=None,
            audit_type=models.AuditType.SMART,
            geo_score=64,
            seo_score=64,
            aeo_score=64,
            request_id="brand:own",
            created_at=now - timedelta(days=5),
            full_report={"metadata": {"audit_outcome": "completed"}},
        )
        db.add(brand_audit)
        db.commit()
        db.refresh(brand_audit)
        expected_ids.append(brand_audit.id)

        # An ad-hoc manual audit with no request-id prefix of any kind.
        manual_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://alpha.example/pricing",
            geo=65,
            seo=65,
            aeo=65,
            created_at=now - timedelta(days=1),
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            request_id=None,
        )
        expected_ids.append(manual_audit.id)

        history = list_project_competitive_source_audits(db, project_id=project.id)
        assert sorted(audit.id for audit in history) == sorted(expected_ids)

        _rows, total = list_project_audits_paginated(db, project_id=project.id, page_size=50)
        assert total == len(expected_ids)

        for audit_type in (
            models.AuditType.FAST,
            models.AuditType.SMART,
            models.AuditType.STANDARD,
            models.AuditType.DEEP,
        ):
            assert (
                db.query(models.Audit)
                .filter(
                    models.Audit.project_id == project.id,
                    models.Audit.project_scope == AUDIT_PROJECT_SCOPE_OWN,
                    models.Audit.audit_type == audit_type,
                )
                .count()
                >= 1
            )

        trend = build_project_trend_payload(
            db, project_id=project.id, period="30d", granularity="daily"
        )
        assert sum(point["audit_count"] for point in trend["data_points"]) == len(expected_ids)

        # The most recent own audit is the ad-hoc one, so nothing was dropped at
        # the top of the history either.
        health = get_client_health(db, workspace_id=workspace.id)
        assert health[0]["latest_seo_score"] == 65
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Write-side classification
# ---------------------------------------------------------------------------


def test_lite_refresh_enqueue_declares_competitor_scope() -> None:
    db, engine = _build_db()
    try:
        owner, _workspace, project = _seed_project(db)

        project_site = models.Site(user_id=owner.id, domain="alpha.example", display_name="Alpha")
        competitor_site = models.Site(
            user_id=owner.id, domain="comp-a.example", display_name="Comp A"
        )
        db.add_all([project_site, competitor_site])
        db.commit()
        db.refresh(project_site)
        db.refresh(competitor_site)
        project_site.competitors.append(competitor_site)
        db.commit()

        source_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=project_site.id,
            url="https://alpha.example",
            geo=70,
            seo=74,
            aeo=66,
            created_at=datetime.now(timezone.utc),
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            request_id="scheduled-audit:own",
        )

        source_job = AuditJobPayload(
            job_id="source-job",
            request_id="scheduled-audit:own",
            user_id=owner.id,
            url="https://alpha.example",
            provider="google",
            tier="fast",
            project_id=project.id,
        )

        class _FakeRedis:
            def __init__(self) -> None:
                self.payloads: list[str] = []

            async def hset(self, _key: str, mapping: dict[str, str]) -> None:
                return None

            async def rpush(self, _queue: str, payload: str) -> None:
                self.payloads.append(payload)

            async def expire(self, _key: str, _ttl: int) -> None:
                return None

        fake_redis = _FakeRedis()
        result = asyncio.run(
            _enqueue_competitor_lite_refresh_jobs(
                redis_client=fake_redis,  # type: ignore[arg-type]
                db=db,
                source_job=source_job,
                source_audit=source_audit,
            )
        )

        assert result["enqueued_count"] == 1
        import json

        payload = parse_job_payload(json.loads(fake_redis.payloads[0]))
        assert payload.project_id == project.id
        assert payload.project_scope == AUDIT_PROJECT_SCOPE_COMPETITOR
        assert (
            resolve_audit_project_scope(
                request_id=payload.request_id,
                category=payload.category,
                declared_scope=payload.project_scope,
            )
            == AUDIT_PROJECT_SCOPE_COMPETITOR
        )
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# SIGV2-1121: an undeclared, unmarked audit must never count as the project's own
# ---------------------------------------------------------------------------


def test_write_path_that_declares_no_scope_is_excluded_from_project_own_scores() -> None:
    """A future write path that forgets to declare must fail closed.

    The classifier used to end in ``return AUDIT_PROJECT_SCOPE_OWN``, so an audit
    that declared nothing and carried no competitor marker was stamped as the
    project's own. That is the SIGV2-1117 defect again, and silently: a
    plausible wrong number on history, trend, change, rank, digests and PDFs.
    """
    import json

    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project(db)
        now = datetime.now(timezone.utc)

        own_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            url="https://alpha.example",
            geo=70,
            seo=74,
            aeo=66,
            created_at=now - timedelta(days=2),
            project_scope=AUDIT_PROJECT_SCOPE_OWN,
            request_id="scheduled-audit:own",
        )

        # A write path added after SIGV2-1117 that forgets to declare a scope:
        # it enqueues a job with no project_scope and no competitor marker of
        # any kind, through the same Redis round-trip as every real enqueue.
        undeclared_job = parse_job_payload(
            json.loads(
                json.dumps(
                    AuditJobPayload(
                        job_id="future-job",
                        request_id="future-write-path:1",
                        user_id=owner.id,
                        url="https://alpha.example/new-surface",
                        provider="google",
                        tier="fast",
                        project_id=project.id,
                        category="brand new surface",
                    ).to_dict()
                )
            )
        )
        assert undeclared_job.project_scope is None

        # The worker classifies that job exactly as it classifies every job.
        resolved_scope = resolve_audit_project_scope(
            request_id=undeclared_job.request_id,
            category=undeclared_job.category,
            project_competitor_id=undeclared_job.project_competitor_id,
            source_audit_id=undeclared_job.source_audit_id,
            declared_scope=undeclared_job.project_scope,
        )
        assert resolved_scope is None

        undeclared_audit = models.Audit(
            user_id=owner.id,
            project_id=project.id,
            project_scope=resolved_scope,
            url=undeclared_job.url,
            audit_type=models.AuditType.FAST,
            geo_score=11,
            seo_score=12,
            aeo_score=13,
            request_id=undeclared_job.request_id,
            # Newer than the project's own audit, so every "latest score" read
            # would pick it up if it counted as the project's.
            created_at=now,
            full_report={"metadata": {"audit_outcome": "completed"}},
        )
        db.add(undeclared_audit)
        db.commit()
        db.refresh(undeclared_audit)

        assert undeclared_audit.project_scope is None
        assert is_own_project_audit(undeclared_audit) is False

        history = list_project_competitive_source_audits(db, project_id=project.id)
        assert [audit.id for audit in history] == [own_audit.id]

        rows, total = list_project_audits_paginated(db, project_id=project.id)
        assert total == 1
        assert [row.id for row in rows] == [own_audit.id]
        assert get_audit_for_project(db, project_id=project.id).id == own_audit.id
        assert (
            get_audit_for_project(db, project_id=project.id, audit_id=undeclared_audit.id) is None
        )

        latest = get_latest_project_competitive_source_audit(db, project_id=project.id)
        assert latest is not None
        assert latest.id == own_audit.id
        assert latest.seo_score == 74

        selection = select_project_module_audit(db, project_id=project.id, module="seo")
        assert selection.latest_audit is not None
        assert selection.latest_audit.id == own_audit.id

        health = get_client_health(db, workspace_id=workspace.id)
        assert health[0]["latest_seo_score"] == 74

        trend = build_project_trend_payload(
            db, project_id=project.id, period="30d", granularity="daily"
        )
        assert trend["summary"]["latest"]["seo"] == 74
        assert sum(point["audit_count"] for point in trend["data_points"]) == 1

        comparison = build_project_period_comparison(db, project_id=project.id, period="30d")
        assert comparison["current_period"]["seo"] == 74
        assert comparison["current_period"]["audit_count"] == 1
    finally:
        _cleanup(db, engine)


def test_declare_audit_project_scope_is_explicit_for_every_write_path() -> None:
    # The project's own target: the normal case, stated rather than guessed.
    assert declare_audit_project_scope() == AUDIT_PROJECT_SCOPE_OWN
    assert declare_audit_project_scope(category="sitemap crawl") == AUDIT_PROJECT_SCOPE_OWN

    # A caller of POST /api/v1/audit or the external API can ask for a
    # competitor lite audit, so the declaration honours that request. The
    # competitor lite entitlement gate authorizes that category before any of
    # this runs (SIGV2-1126).
    assert (
        declare_audit_project_scope(category="Competitor Lite Audit")
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )


def test_resolve_audit_project_scope_classification() -> None:
    # A declared scope wins.
    assert (
        resolve_audit_project_scope(declared_scope="competitor") == AUDIT_PROJECT_SCOPE_COMPETITOR
    )
    assert resolve_audit_project_scope(declared_scope="project") == AUDIT_PROJECT_SCOPE_OWN

    # Markers cover payloads enqueued before project_scope existed.
    assert (
        resolve_audit_project_scope(request_id="lite-refresh:1:2:job")
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )
    assert (
        resolve_audit_project_scope(request_id="competitive-benchmark:1:2:job")
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )
    assert (
        resolve_audit_project_scope(project_competitor_id=4, source_audit_id=9)
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )
    assert (
        resolve_audit_project_scope(category="Competitor Lite Audit")
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )

    # SIGV2-1121: anything neither declared nor marked stays unclassified. The
    # classifier must not invent the project's own scope, because a NULL row is
    # excluded from the project's scores while a wrong "project" row is counted.
    assert resolve_audit_project_scope(request_id="scheduled-audit:7") is None
    assert resolve_audit_project_scope(request_id=None, category=None) is None
    assert resolve_audit_project_scope(request_id="req-1", category="sitemap crawl") is None
    # An unparseable declared value must not be trusted as a scope.
    assert (
        resolve_audit_project_scope(request_id="lite-refresh:1", declared_scope="nonsense")
        == AUDIT_PROJECT_SCOPE_COMPETITOR
    )
