from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
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
from routers.workspace_router import (
    ProjectProgressReportRequest,
    create_project_progress_report,
    list_project_progress_reports,
)
from services.email_service import EmailService
from services.project_progress_service import (
    _extract_remaining_issues,
    build_project_period_comparison,
    build_project_trend_payload,
    build_workspace_trends_overview,
    generate_project_progress_report,
    generate_pending_project_progress_reports,
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


def _seed_project_with_history(
    db: Session,
) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(
        email="trends-owner@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        company_name="Signal Forge",
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Signal Forge", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="https://northwind.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()

    db.add_all(
        [
            models.Audit(
                user_id=owner.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project.domain_url,
                seo_score=40,
                geo_score=38,
                aeo_score=42,
                full_report={"metadata": {"audit_outcome": "completed"}},
                created_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
            ),
            models.Audit(
                user_id=owner.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project.domain_url,
                seo_score=48,
                geo_score=46,
                aeo_score=45,
                full_report={"metadata": {"audit_outcome": "completed"}},
                created_at=datetime(2026, 1, 24, 9, 0, tzinfo=timezone.utc),
            ),
            models.Audit(
                user_id=owner.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project.domain_url,
                seo_score=62,
                geo_score=58,
                aeo_score=60,
                full_report={
                    "metadata": {"audit_outcome": "completed"},
                    "analysis": {
                        "recommendations": ["Expand comparison pages with structured data."]
                    },
                },
                created_at=datetime(2026, 2, 7, 9, 0, tzinfo=timezone.utc),
            ),
            models.Audit(
                user_id=owner.id,
                project_id=project.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project.domain_url,
                seo_score=70,
                geo_score=65,
                aeo_score=68,
                full_report={
                    "metadata": {"audit_outcome": "completed"},
                    "prioritized_actions": [
                        {"title": "Expand comparison pages with structured data."},
                        {"title": "Increase FAQ coverage for top-intent pages."},
                    ],
                },
                created_at=datetime(2026, 2, 28, 9, 0, tzinfo=timezone.utc),
            ),
        ]
    )
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def _seed_project_with_single_current_month_audit(
    db: Session,
) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(
        email="preview-owner@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        company_name="Signal Forge",
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Signal Forge", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Preview Project",
        domain_url="https://preview.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()

    db.add(
        models.Audit(
            user_id=owner.id,
            project_id=project.id,
            project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
            url=project.domain_url,
            seo_score=61,
            geo_score=59,
            aeo_score=63,
            full_report={"metadata": {"audit_outcome": "completed"}},
            created_at=datetime(2026, 3, 2, 11, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def test_project_trends_and_workspace_overview_return_monthly_progress() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project_with_history(db)
        db.add_all(
            [
                models.GlobalVolatilitySnapshot(
                    snapshot_date=date(2026, 1, 1),
                    provider="all",
                    industry="all",
                    volatility_score=3.2,
                    compared_queries=50,
                    changed_query_count=10,
                    changed_ratio=0.2,
                    schema_version="1",
                ),
                models.GlobalVolatilitySnapshot(
                    snapshot_date=date(2026, 2, 1),
                    provider="all",
                    industry="all",
                    volatility_score=7.4,
                    compared_queries=55,
                    changed_query_count=22,
                    changed_ratio=0.4,
                    schema_version="1",
                ),
            ]
        )
        db.commit()

        # Pin "now" so the trailing-window queries are deterministic regardless of
        # the wall clock (the seeded audits are fixed at Jan/Feb 2026). The router
        # wrappers don't accept a clock override, so exercise the service layer.
        as_of = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
        trends = build_project_trend_payload(
            db,
            project_id=project.id,
            period="90d",
            granularity="monthly",
            now=as_of,
        )
        comparison = build_project_period_comparison(
            db,
            project_id=project.id,
            period="30d",
            now=as_of,
        )
        overview = build_workspace_trends_overview(
            db,
            workspace_id=workspace.id,
            period="90d",
            now=as_of,
        )

        assert len(trends["data_points"]) == 2
        assert trends["data_points"][0]["date"] == "2026-01-01"
        assert trends["data_points"][1]["date"] == "2026-02-01"
        assert trends["data_points"][0]["volatility_score"] == 3.2
        assert trends["data_points"][1]["volatility_score"] == 7.4
        assert trends["summary"]["delta"]["seo"] == pytest.approx(22.0)
        assert comparison["delta"]["overall"] == pytest.approx(20.66, abs=0.05)
        assert overview["workspace_id"] == workspace.id
        assert overview["projects"][0]["project_id"] == project.id
        assert len(overview["projects"][0]["sparkline"]) >= 2
    finally:
        _cleanup(db, engine)


def test_extract_remaining_issues_prefers_canonical_and_legacy_normalized_recommendation_rows() -> (
    None
):
    audit = models.Audit(
        user_id=1,
        project_id=1,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://northwind.example",
        full_report={
            "recommendations": {
                "items": [
                    {"title": "Canonical recommendation", "action": "Canonical recommendation"},
                ]
            },
            "prioritized_actions": [
                {"title": "Legacy prioritized action"},
            ],
            "analysis": {
                "recommendations": ["Legacy analysis recommendation"],
            },
        },
    )

    assert _extract_remaining_issues(audit) == [
        "Canonical recommendation",
        "Legacy prioritized action",
        "Legacy analysis recommendation",
    ]


def test_manual_progress_report_defaults_to_latest_audited_month_when_previous_month_is_empty() -> (
    None
):
    db, engine = _build_db()
    try:
        _owner, _workspace, project = _seed_project_with_single_current_month_audit(db)

        report = generate_project_progress_report(
            db,
            project_id=project.id,
            deliver_email=False,
            now=datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc),
        )

        assert report.report_month == date(2026, 3, 1)
        assert report.snapshot_json["report_month"] == "2026-03-01"
        assert report.snapshot_json["current_scores"]["audit_count"] == 1
        assert report.snapshot_json["previous_scores"]["audit_count"] == 0
    finally:
        _cleanup(db, engine)


def test_manual_progress_report_generation_persists_snapshot_and_queues_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    queued: list[tuple[str, str]] = []
    try:
        owner, workspace, project = _seed_project_with_history(db)
        client_user = models.User(
            email="client@example.com",
            hashed_password="x",
            role="user",
            credits=0,
        )
        db.add(client_user)
        db.flush()
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=client_user.id,
            role=models.WorkspaceRole.CLIENT_READONLY,
        )
        db.add(membership)
        db.flush()
        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project.id,
            )
        )
        db.commit()

        def _fake_queue_template_email(self, *, to_email: str, template_key: str, **kwargs):
            queued.append((to_email, template_key))
            return None

        monkeypatch.setattr(EmailService, "queue_template_email", _fake_queue_template_email)

        report = create_project_progress_report(
            project_id=project.id,
            payload=ProjectProgressReportRequest(
                report_month=date(2026, 2, 1),
                deliver_email=True,
            ),
            user=owner,
            db=db,
        )
        reports = list_project_progress_reports(project_id=project.id, user=owner, db=db)

        assert report["report_month"] == "2026-02-01"
        assert report["snapshot"]["current_scores"]["audit_count"] == 2
        assert report["snapshot"]["delta"]["seo"] == pytest.approx(22.0)
        assert report["snapshot"]["remaining_issues"]
        assert len(reports) == 1
        assert ("trends-owner@example.com", "project.progress_report") in queued
        assert ("client@example.com", "project.progress_report") in queued
    finally:
        _cleanup(db, engine)


def test_automation_generates_missing_monthly_reports_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    queued: list[str] = []
    try:
        owner, _workspace, project = _seed_project_with_history(db)
        db.add(
            models.ScheduledAudit(
                user_id=owner.id,
                project_id=project.id,
                url=project.domain_url,
                audit_type=models.AuditType.STANDARD,
                frequency=models.ScheduledAuditFrequency.MONTHLY,
                next_run_at=datetime(2026, 3, 7, 10, 0, tzinfo=timezone.utc),
                is_active=True,
            )
        )
        db.commit()

        def _fake_queue_template_email(self, *, to_email: str, template_key: str, **kwargs):
            queued.append(f"{to_email}:{template_key}")
            return None

        monkeypatch.setattr(EmailService, "queue_template_email", _fake_queue_template_email)

        generated = generate_pending_project_progress_reports(
            db,
            now=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
            frontend_base_url="http://localhost:3000",
        )
        repeated = generate_pending_project_progress_reports(
            db,
            now=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
            frontend_base_url="http://localhost:3000",
        )

        assert len(generated) == 1
        assert repeated == []
        assert queued == ["trends-owner@example.com:project.progress_report"]
    finally:
        _cleanup(db, engine)
