from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
import services.pdf_reports.report_suite_service as report_suite_service
from database import Base
from services.pdf_reports.report_suite_service import render_report_pdf


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: object) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_project(db: Session) -> tuple[models.User, models.Project, models.Site, models.Site]:
    owner = models.User(email="suite@example.com", hashed_password="x", role="user", credits=500)
    db.add(owner)
    db.flush()
    db.add(
        models.Subscription(
            user_id=owner.id,
            stripe_customer_id="cus_suite",
            plan_type="plan_specialist",
            status="active",
        )
    )
    workspace = models.Workspace(name="Suite Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Alpha Client",
        domain_url="https://alpha.example",
        target_country="US",
        language="en",
        icp_roles=["CMO", "SEO Lead"],
        usp="Evidence-led AI visibility reporting",
    )
    target_site = models.Site(
        user_id=owner.id,
        domain="alpha.example",
        display_name="Alpha",
    )
    competitor_site = models.Site(
        user_id=owner.id,
        domain="comp.example",
        display_name="Comp A",
    )
    db.add_all([project, target_site, competitor_site])
    db.commit()
    db.refresh(owner)
    db.refresh(project)
    db.refresh(target_site)
    db.refresh(competitor_site)
    return owner, project, target_site, competitor_site


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    site_id: int | None,
    url: str,
    geo: float,
    seo: float,
    aeo: float,
    created_at: datetime,
    request_id: str | None = None,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        site_id=site_id,
        url=url,
        target_url=url,
        target_name=url.replace("https://", ""),
        geo_score=geo,
        seo_score=seo,
        aeo_score=aeo,
        request_id=request_id,
        created_at=created_at,
        full_report={"metadata": {"title": url}},
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def _normalized_report(audit: models.Audit) -> dict[str, object]:
    overall = round(
        (float(audit.seo_score or 0) + float(audit.geo_score or 0) + float(audit.aeo_score or 0))
        / 3,
        2,
    )
    created_at = audit.created_at or datetime.now(timezone.utc)
    return {
        "target": {
            "type": "website",
            "name": audit.target_name or audit.url,
            "url": audit.target_url or audit.url,
            "metadata": {},
        },
        "site": {
            "url": audit.url,
            "market": "us",
            "language": "en",
        },
        "scores": {
            "seo": float(audit.seo_score or 0),
            "geo": float(audit.geo_score or 0),
            "aeo": float(audit.aeo_score or 0),
            "overall": overall,
        },
        "metadata": {
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "audit_target_type": "website",
            "target_name": audit.target_name or audit.url,
            "target_url": audit.target_url or audit.url,
            "target_metadata": {},
            "neural_executive_summary": "Executive summary.",
            "market_dominance_blueprint": "Blueprint summary.",
            "strategic_intelligence_grid": [],
        },
        "suggestions": [
            {
                "priority": 1,
                "title": "Improve schema coverage",
                "summary": "Expand answer schema on the primary landing pages.",
                "action": "Improve schema coverage",
                "category": "Technical",
                "owner": "Engineering",
                "estimated_effort": "medium",
            }
        ],
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": True,
            "grounding_profile": "dual_track_v1",
            "summary": {
                "total_claims": 4,
                "track_a_total": 3,
                "track_a_supported": 3,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 1,
                "track_b_supported": 1,
                "track_b_flagged": 0,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [],
            "degraded": False,
            "degraded_reason": None,
        },
    }


def test_render_report_pdf_builds_project_interval_payload_from_persisted_tasks(
    monkeypatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, project, target_site, _competitor_site = _seed_project(db)
        older_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=target_site.id,
            url="https://alpha.example/audit-1",
            geo=60,
            seo=62,
            aeo=58,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        latest_audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=target_site.id,
            url="https://alpha.example/audit-2",
            geo=78,
            seo=80,
            aeo=76,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        db.add_all(
            [
                models.ProjectTask(
                    project_id=project.id,
                    source_audit_id=latest_audit.id,
                    title="New answer formatting issue",
                    status=models.ProjectTaskStatus.TODO,
                    priority=models.ProjectTaskPriority.MEDIUM,
                    origin=models.ProjectTaskOrigin.AUDIT_RECOMMENDATION,
                    category="Content",
                ),
                models.ProjectTask(
                    project_id=project.id,
                    source_audit_id=None,
                    title="Resolved schema gap",
                    status=models.ProjectTaskStatus.DONE,
                    priority=models.ProjectTaskPriority.HIGH,
                    origin=models.ProjectTaskOrigin.AUDIT_RECOMMENDATION,
                    category="Technical",
                    resolved_at=latest_audit.created_at,
                ),
                models.ProjectTask(
                    project_id=project.id,
                    source_audit_id=None,
                    title="Validated citation fix",
                    status=models.ProjectTaskStatus.DONE,
                    priority=models.ProjectTaskPriority.HIGH,
                    origin=models.ProjectTaskOrigin.AUDIT_RECOMMENDATION,
                    category="Authority",
                    resolved_at=latest_audit.created_at,
                    verified_at=latest_audit.created_at,
                ),
            ]
        )
        db.commit()

        captured: dict[str, object] = {}

        monkeypatch.setattr(
            report_suite_service,
            "resolve_audit_normalization_current_plan",
            lambda _user: "current",
        )
        monkeypatch.setattr(
            report_suite_service,
            "build_normalized_audit_report",
            lambda audit, current_plan=None: _normalized_report(audit),
        )
        monkeypatch.setattr(
            report_suite_service,
            "extract_normalized_recommendation_texts",
            lambda _report, limit=4: ["Expand FAQ schema", "Strengthen citations"][:limit],
        )
        monkeypatch.setattr(
            report_suite_service,
            "sync_project_tasks",
            lambda db_session, project_id: (
                db_session.query(models.ProjectTask)
                .filter(models.ProjectTask.project_id == project_id)
                .order_by(models.ProjectTask.id.asc())
                .all()
            ),
        )
        monkeypatch.setattr(
            report_suite_service,
            "build_project_task_summary",
            lambda tasks: {"todo": 1, "in_progress": 0, "done": 2, "validated": 1},
        )
        monkeypatch.setattr(
            report_suite_service,
            "build_project_task_impact_payload",
            lambda _db, project_id: {
                "items": [{"title": "Validated citation fix", "project_id": project_id}],
                "summary": {"validated_count": 1},
            },
        )
        monkeypatch.setattr(
            report_suite_service,
            "render_white_label_pdf",
            lambda **kwargs: captured.update(kwargs) or b"%PDF-project",
        )

        pdf_bytes = render_report_pdf(
            db=db,
            selected_audits=[older_audit, latest_audit],
            template_type="Executive",
            options={
                "report_kind": "project",
                "branding_mode": "platform",
                "hide_credit_cost": True,
            },
            branding_config={"generated_date": "2026-03-12"},
        )

        assert pdf_bytes == b"%PDF-project"
        suite = captured["full_report"]["metadata"]["report_suite"]["project_report"]
        assert suite["audit_count"] == 2
        assert suite["task_movement"]["new"] == 1
        assert suite["task_movement"]["resolved"] == 2
        assert suite["task_movement"]["validated"] == 1
        assert suite["delta"]["overall"] == 18.0
        assert suite["validated_impact"][0]["title"] == "Validated citation fix"
        assert suite["remaining_issues"] == ["Expand FAQ schema", "Strengthen citations"]
    finally:
        _cleanup(db, engine)


def test_render_report_pdf_builds_competitor_trend_payload_from_tracked_history(
    monkeypatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, project, target_site, competitor_site = _seed_project(db)
        older_source = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=target_site.id,
            url="https://alpha.example/audit-1",
            geo=68,
            seo=70,
            aeo=67,
            created_at=datetime.now(timezone.utc) - timedelta(days=20),
        )
        current_source = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=target_site.id,
            url="https://alpha.example/audit-2",
            geo=76,
            seo=78,
            aeo=74,
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        older_competitor = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=competitor_site.id,
            url="https://comp.example/audit-1",
            geo=72,
            seo=73,
            aeo=71,
            created_at=older_source.created_at + timedelta(minutes=5),
        )
        current_competitor = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=competitor_site.id,
            url="https://comp.example/audit-2",
            geo=81,
            seo=82,
            aeo=79,
            created_at=current_source.created_at + timedelta(minutes=5),
        )

        tracked_competitor = models.ProjectCompetitor(
            project_id=project.id,
            target_url="https://comp.example",
            normalized_domain="comp.example",
            display_name="Comp A",
        )
        db.add(tracked_competitor)
        db.commit()
        db.refresh(tracked_competitor)

        db.add_all(
            [
                models.ProjectCompetitorSnapshot(
                    project_id=project.id,
                    competitor_id=tracked_competitor.id,
                    source_audit_id=older_source.id,
                    competitor_audit_id=older_competitor.id,
                    status="succeeded",
                    geo_score=older_competitor.geo_score,
                    seo_score=older_competitor.seo_score,
                    aeo_score=older_competitor.aeo_score,
                    captured_at=older_source.created_at,
                ),
                models.ProjectCompetitorSnapshot(
                    project_id=project.id,
                    competitor_id=tracked_competitor.id,
                    source_audit_id=current_source.id,
                    competitor_audit_id=current_competitor.id,
                    status="succeeded",
                    geo_score=current_competitor.geo_score,
                    seo_score=current_competitor.seo_score,
                    aeo_score=current_competitor.aeo_score,
                    captured_at=current_source.created_at,
                ),
            ]
        )
        db.commit()

        captured: dict[str, object] = {}

        monkeypatch.setattr(
            report_suite_service,
            "resolve_audit_normalization_current_plan",
            lambda _user: "plan_specialist",
        )
        monkeypatch.setattr(
            report_suite_service,
            "build_normalized_audit_report",
            lambda audit, current_plan=None: _normalized_report(audit),
        )
        monkeypatch.setattr(
            report_suite_service,
            "render_battle_report_pdf",
            lambda **kwargs: captured.update(kwargs) or b"%PDF-battle",
        )

        pdf_bytes = render_report_pdf(
            db=db,
            selected_audits=[
                older_source,
                current_source,
                older_competitor,
                current_competitor,
            ],
            template_type="Comparative",
            options={
                "report_kind": "competitors",
                "branding_mode": "platform",
                "competitor_mode": "trend",
                "sections": ["overview", "geo", "seo", "aeo"],
            },
            branding_config={"generated_date": "2026-03-12"},
            export_manifest={
                "report_kind": "competitors",
                "branding_mode": "platform",
                "competitor_mode": "trend",
                "render_report_type": "battle",
                "hide_credit_cost": True,
            },
            primary_audit=current_source,
            competitor_audits=[current_competitor],
        )

        assert pdf_bytes == b"%PDF-battle"
        assert captured["trend_payload"]["enabled"] is True
        assert captured["trend_payload"]["competitors"][0]["name"] == "Comp A"
        benchmark_rows = captured["benchmark_payload"]["rows"]
        assert any(row.get("is_target") is True for row in benchmark_rows)
        assert any(row["name"] == "Comp A" for row in benchmark_rows)
        trend_timeline = captured["left_full_report"]["metadata"]["competitor_summary"][
            "trend_timeline"
        ]
        assert trend_timeline["competitors"][0]["name"] == "Comp A"
    finally:
        _cleanup(db, engine)


def test_render_report_pdf_builds_financial_payload_and_redacts_when_requested(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        owner, project, target_site, _competitor_site = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            site_id=target_site.id,
            url="https://alpha.example/audit-1",
            geo=76,
            seo=79,
            aeo=74,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
            request_id="req-financial-1",
        )
        db.add(
            models.AuditJob(
                id="job-financial-1",
                user_id=owner.id,
                project_id=project.id,
                status="completed",
                url=audit.url,
                request_id="req-financial-1",
                estimated_credit_cost=9,
                consumed_credit_cost=0,
                completed_at=audit.created_at,
            )
        )
        db.add(
            models.CreditHold(
                user_id=owner.id,
                request_id="req-financial-1",
                hold_amount=9,
                final_amount=7,
                status="settled",
                reason_code="audit",
                feature_key="audit",
                project_id=project.id,
                expires_at=datetime.now(timezone.utc) + timedelta(days=1),
            )
        )
        db.commit()

        monkeypatch.setattr(
            report_suite_service,
            "resolve_audit_normalization_current_plan",
            lambda _user: "current",
        )
        monkeypatch.setattr(
            report_suite_service,
            "build_normalized_audit_report",
            lambda current_audit, current_plan=None: _normalized_report(current_audit),
        )
        visible_capture: dict[str, object] = {}
        redacted_capture: dict[str, object] = {}
        monkeypatch.setattr(
            report_suite_service,
            "render_white_label_pdf",
            lambda **kwargs: visible_capture.update(kwargs) or b"%PDF-financial-visible",
        )

        visible_pdf = render_report_pdf(
            db=db,
            selected_audits=[audit],
            template_type="Executive",
            options={
                "report_kind": "financial",
                "branding_mode": "platform",
                "hide_credit_cost": False,
            },
            branding_config={"generated_date": "2026-03-12"},
        )

        assert visible_pdf == b"%PDF-financial-visible"
        visible_suite = visible_capture["full_report"]["metadata"]["report_suite"][
            "financial_report"
        ]
        assert visible_suite["redacted"] is False
        assert visible_suite["ledger_rows"][0]["credits_consumed"] == 7
        assert visible_suite["total_consumed_credits"] == 7

        monkeypatch.setattr(
            report_suite_service,
            "render_white_label_pdf",
            lambda **kwargs: redacted_capture.update(kwargs) or b"%PDF-financial-redacted",
        )

        redacted_pdf = render_report_pdf(
            db=db,
            selected_audits=[audit],
            template_type="Executive",
            options={
                "report_kind": "financial",
                "branding_mode": "platform",
                "hide_credit_cost": True,
            },
            branding_config={"generated_date": "2026-03-12"},
        )

        assert redacted_pdf == b"%PDF-financial-redacted"
        redacted_suite = redacted_capture["full_report"]["metadata"]["report_suite"][
            "financial_report"
        ]
        assert redacted_suite["redacted"] is True
        assert redacted_suite["redaction_reason"] == (
            "Cost disclosure was withheld for client presentation."
        )
        assert "ledger_rows" not in redacted_suite
    finally:
        _cleanup(db, engine)
