"""SIGV2-1136: a parsed request id must not choose which tenant gets a write.

``cron_sweeper._mark_competitive_snapshot_failed_from_job`` parses
``competitive-benchmark:<source_audit_id>:<competitor_id>`` out of a failed
job's request id, resolved the project from ``source_audit_id`` with no tenant
filter, then wrote a ``ProjectCompetitorSnapshot`` and queued a competitive
digest into whatever project owned that audit. A value derived from a request
id decided which tenant's project received a write.

The boundary applied is workspace or project membership, the same notion
``services.workspace_rbac.resolve_project_access`` enforces on every router. It
is deliberately not ``Audit.user_id == job.user_id``: a workspace member
benchmarking against a colleague's source audit is legitimate, and
``test_member_of_the_owning_workspace_still_writes_the_snapshot`` pins that so
the ownership shortcut cannot be reintroduced as a "fix".

The first, third and fourth tests fail on the pre-fix code, which wrote the
snapshot in every one of those cases.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import cron_sweeper
import models
from database import Base


@pytest.fixture
def tenant_context(monkeypatch: pytest.MonkeyPatch):
    engine, db = _build_db()

    owner = _add_user(db, "owner@tenant-a.example")
    outsider = _add_user(db, "outsider@tenant-b.example")
    colleague = _add_user(db, "colleague@tenant-a.example")

    workspace_a = models.Workspace(name="Tenant A", owner_id=owner.id)
    workspace_b = models.Workspace(name="Tenant B", owner_id=outsider.id)
    db.add_all([workspace_a, workspace_b])
    db.flush()

    db.add(
        models.WorkspaceUser(
            workspace_id=workspace_a.id,
            user_id=colleague.id,
            role=models.WorkspaceRole.EDITOR,
        )
    )

    project_a = models.Project(
        workspace_id=workspace_a.id,
        name="Tenant A Client",
        domain_url="https://tenant-a.example",
        target_country="US",
        language="en",
    )
    project_b = models.Project(
        workspace_id=workspace_b.id,
        name="Tenant B Client",
        domain_url="https://tenant-b.example",
        target_country="US",
        language="en",
    )
    db.add_all([project_a, project_b])
    db.flush()

    competitor_a = models.ProjectCompetitor(
        project_id=project_a.id,
        target_url="https://rival.example",
        normalized_domain="rival.example",
        display_name="Rival",
        auto_audit_enabled=True,
    )
    competitor_b = models.ProjectCompetitor(
        project_id=project_b.id,
        target_url="https://other-rival.example",
        normalized_domain="other-rival.example",
        display_name="Other Rival",
        auto_audit_enabled=True,
    )
    db.add_all([competitor_a, competitor_b])

    source_audit = models.Audit(
        user_id=owner.id,
        project_id=project_a.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://tenant-a.example",
        geo_score=70.0,
        seo_score=71.0,
        aeo_score=72.0,
        request_id="audit:tenant-a-source",
        created_at=datetime.now(timezone.utc),
    )
    db.add(source_audit)
    db.commit()

    queued_digests: list[int] = []

    def record_digest(_db, *, project, source_audit_id, frontend_base_url):
        del source_audit_id, frontend_base_url
        queued_digests.append(int(project.id))
        return False

    monkeypatch.setattr(cron_sweeper, "maybe_queue_project_competitive_digest", record_digest)

    yield {
        "db": db,
        "owner": owner,
        "outsider": outsider,
        "colleague": colleague,
        "project_a": project_a,
        "competitor_a": competitor_a,
        "competitor_b": competitor_b,
        "source_audit": source_audit,
        "queued_digests": queued_digests,
    }

    db.close()
    Base.metadata.drop_all(bind=engine)


def _build_db() -> tuple[Engine, Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return engine, session_factory()


def _add_user(db: Session, email: str) -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=10)
    db.add(user)
    db.flush()
    return user


def _failed_benchmark_job(
    db: Session,
    *,
    user: models.User,
    source_audit_id: int,
    competitor_id: int,
    job_id: str,
) -> models.AuditJob:
    job = models.AuditJob(
        id=job_id,
        user_id=user.id,
        status="failed",
        audit_target_type=models.AuditTargetType.WEBSITE,
        url="https://rival.example",
        request_id=f"competitive-benchmark:{source_audit_id}:{competitor_id}:{job_id}",
        scan_origin=models.SCAN_ORIGIN_COMPETITOR_REFRESH,
    )
    db.add(job)
    db.commit()
    return job


def _snapshots(db: Session) -> list[models.ProjectCompetitorSnapshot]:
    return db.query(models.ProjectCompetitorSnapshot).all()


def test_job_outside_the_tenant_boundary_writes_nothing(tenant_context) -> None:
    """The defect: a request id pointing at another tenant's audit caused a write."""
    db = tenant_context["db"]
    job = _failed_benchmark_job(
        db,
        user=tenant_context["outsider"],
        source_audit_id=tenant_context["source_audit"].id,
        competitor_id=tenant_context["competitor_a"].id,
        job_id="job-cross-tenant",
    )

    cron_sweeper._mark_competitive_snapshot_failed_from_job(db, job, "Job timed out")

    assert _snapshots(db) == []
    assert tenant_context["queued_digests"] == []


def test_workspace_owner_writes_the_snapshot(tenant_context) -> None:
    db = tenant_context["db"]
    job = _failed_benchmark_job(
        db,
        user=tenant_context["owner"],
        source_audit_id=tenant_context["source_audit"].id,
        competitor_id=tenant_context["competitor_a"].id,
        job_id="job-owner",
    )

    cron_sweeper._mark_competitive_snapshot_failed_from_job(db, job, "Job timed out")

    snapshots = _snapshots(db)
    assert len(snapshots) == 1
    assert snapshots[0].project_id == tenant_context["project_a"].id
    assert snapshots[0].competitor_id == tenant_context["competitor_a"].id
    assert snapshots[0].status == "failed"
    assert tenant_context["queued_digests"] == [tenant_context["project_a"].id]


def test_member_of_the_owning_workspace_still_writes_the_snapshot(tenant_context) -> None:
    """The legitimate case the obvious fix would have broken.

    The source audit belongs to the workspace owner, the job is attributed to a
    different member of that same workspace. ``Audit.user_id == job.user_id``
    would refuse this; membership allows it.
    """
    db = tenant_context["db"]
    assert tenant_context["source_audit"].user_id != tenant_context["colleague"].id
    job = _failed_benchmark_job(
        db,
        user=tenant_context["colleague"],
        source_audit_id=tenant_context["source_audit"].id,
        competitor_id=tenant_context["competitor_a"].id,
        job_id="job-colleague",
    )

    cron_sweeper._mark_competitive_snapshot_failed_from_job(db, job, "Job timed out")

    snapshots = _snapshots(db)
    assert len(snapshots) == 1
    assert snapshots[0].project_id == tenant_context["project_a"].id
    assert snapshots[0].status == "failed"
    assert tenant_context["queued_digests"] == [tenant_context["project_a"].id]


def test_project_scoped_member_without_an_assignment_writes_nothing(tenant_context) -> None:
    """Membership alone is not the whole boundary for a project-scoped role.

    A MANAGER is scoped to the projects they are assigned, which is exactly what
    ``resolve_project_access`` enforces, so the sweeper inherits it instead of
    restating it.
    """
    db = tenant_context["db"]
    manager = _add_user(db, "manager@tenant-a.example")
    db.add(
        models.WorkspaceUser(
            workspace_id=tenant_context["project_a"].workspace_id,
            user_id=manager.id,
            role=models.WorkspaceRole.MANAGER,
        )
    )
    db.commit()

    job = _failed_benchmark_job(
        db,
        user=manager,
        source_audit_id=tenant_context["source_audit"].id,
        competitor_id=tenant_context["competitor_a"].id,
        job_id="job-unassigned-manager",
    )

    cron_sweeper._mark_competitive_snapshot_failed_from_job(db, job, "Job timed out")

    assert _snapshots(db) == []
    assert tenant_context["queued_digests"] == []


def test_competitor_from_another_project_writes_nothing(tenant_context) -> None:
    """The competitor id is parsed from the same string, so it is proven too.

    Without this the snapshot row would link one tenant's project to another
    tenant's competitor row.
    """
    db = tenant_context["db"]
    job = _failed_benchmark_job(
        db,
        user=tenant_context["owner"],
        source_audit_id=tenant_context["source_audit"].id,
        competitor_id=tenant_context["competitor_b"].id,
        job_id="job-foreign-competitor",
    )

    cron_sweeper._mark_competitive_snapshot_failed_from_job(db, job, "Job timed out")

    assert _snapshots(db) == []
    assert tenant_context["queued_digests"] == []
