from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import sys
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from services.email_service import EmailService
from services.notification_router import NotificationRouter
from services.workflow_engine import WorkflowEngine
import services.workflow_engine as workflow_engine_module


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session(), engine


def _seed_project(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    user = models.User(
        email="owner@example.com", hashed_password="x", role="user", notifications_enabled=True
    )
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Signal Forge", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id, name="Alpha", domain_url="https://alpha.example", language="en"
    )
    db.add(project)
    db.flush()
    db.add(
        models.SlackConnection(
            workspace_id=workspace.id,
            access_token="xoxb-test",
            team_id="T123",
            default_channel_id="C123",
        )
    )
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    db.refresh(project)
    return user, workspace, project


def _mock_route(**overrides):
    route = {
        "provider": "google",
        "requested_tier": "fast",
        "execution_tier": "fast",
        "product_label": "Fast",
        "tier_class": "fast",
        "feature_key": "audit.main",
        "routing_mode": "default",
        "preferred_provider": "google",
        "route_reason": None,
    }
    route.update(overrides)
    return SimpleNamespace(**route)


def _mock_forecast(estimated_credits: int = 3):
    return SimpleNamespace(estimated_credits=estimated_credits)


def test_workflow_engine_matches_metric_threshold_and_runs_actions(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_project(db)
        queued_emails: list[dict[str, object]] = []
        slack_calls: list[dict[str, object]] = []

        monkeypatch.setattr(
            EmailService,
            "queue_template_email",
            lambda self, **kwargs: queued_emails.append(kwargs),
        )
        monkeypatch.setattr(
            NotificationRouter,
            "send_slack_message",
            lambda self, *, connection, event_key, context, channel_id=None: slack_calls.append(
                {
                    "workspace_id": connection.workspace_id,
                    "event_key": event_key,
                    "channel_id": channel_id,
                }
            ),
        )

        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Score Drop",
            trigger_config={
                "type": "metric_threshold",
                "metric": "geo_score",
                "condition": "below",
                "value": 70,
            },
            actions_config=[
                {
                    "type": "send_email",
                    "config": {"to": "pm@example.com", "template_key": "alert.triggered"},
                },
                {"type": "send_slack", "config": {"channel_id": "C123"}},
            ],
            cooldown_minutes=60,
            is_active=True,
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)

        runs = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="alert.triggered",
            context={"metric_name": "geo_score", "metric_value": 63, "project_name": project.name},
        )

        assert len(runs) == 1
        assert queued_emails[0]["to_email"] == "pm@example.com"
        assert slack_calls[0]["channel_id"] == "C123"
        assert runs[0].status == "completed"
        assert workflow.last_triggered_at is not None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_workflow_engine_respects_cooldown_and_isolates_failures(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_project(db)
        queued_emails: list[dict[str, object]] = []

        monkeypatch.setattr(
            EmailService,
            "queue_template_email",
            lambda self, **kwargs: queued_emails.append(kwargs),
        )

        def failing_slack(*_args, **_kwargs):
            raise RuntimeError("slack down")

        monkeypatch.setattr(NotificationRouter, "send_slack_message", failing_slack)

        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Alert Relay",
            trigger_config={"type": "platform_event", "event_key": "audit.completed"},
            actions_config=[
                {
                    "type": "send_email",
                    "config": {"to": "pm@example.com", "template_key": "audit.completed"},
                },
                {"type": "send_slack", "config": {"channel_id": "C123"}},
            ],
            cooldown_minutes=30,
            is_active=True,
        )
        db.add(workflow)
        db.commit()
        db.refresh(workflow)

        first_run = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="audit.completed",
            context={"project_name": project.name},
        )[0]

        assert first_run.status == "partial_failure"
        assert queued_emails[0]["template_key"] == "audit.completed"

        workflow.last_triggered_at = datetime.now(timezone.utc)
        db.commit()

        second_runs = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="audit.completed",
            context={"project_name": project.name},
        )
        assert second_runs == []
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_workflow_engine_run_audit_action_queues_audit_job(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_project(db)
        enqueued_payloads: list[dict[str, object]] = []

        monkeypatch.setattr(
            workflow_engine_module,
            "resolve_audit_route",
            lambda **_kwargs: _mock_route(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "forecast_audit_cost",
            lambda **_kwargs: _mock_forecast(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "serialize_cost_forecast",
            lambda _forecast: {"estimated_credits": _forecast.estimated_credits},
        )
        monkeypatch.setattr(
            WorkflowEngine,
            "_enqueue_audit_payload",
            lambda self, *, job_key, payload: enqueued_payloads.append(
                {"job_key": job_key, "payload": payload.to_dict()}
            ),
        )

        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Auto Re-Audit",
            trigger_config={"type": "platform_event", "event_key": "alert.triggered"},
            actions_config=[{"type": "run_audit", "config": {"tier": "fast"}}],
            cooldown_minutes=0,
            is_active=True,
        )
        db.add(workflow)
        db.commit()

        runs = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="alert.triggered",
            context={"target_url": "https://alpha.example"},
        )

        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].action_results[0]["status"] == "ok"
        assert enqueued_payloads

        queued_job_id = str(runs[0].action_results[0]["job_id"])
        queued_job = db.query(models.AuditJob).filter(models.AuditJob.id == queued_job_id).first()
        assert queued_job is not None
        assert queued_job.status == "queued"
        assert queued_job.project_id == project.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_workflow_engine_run_audit_action_fails_when_duplicate_job_exists(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_project(db)
        db.add(
            models.AuditJob(
                id="duplicate-job",
                user_id=user.id,
                project_id=project.id,
                status="running",
                url="https://alpha.example",
                request_id="duplicate-request",
            )
        )
        db.commit()

        monkeypatch.setattr(
            workflow_engine_module,
            "resolve_audit_route",
            lambda **_kwargs: _mock_route(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "forecast_audit_cost",
            lambda **_kwargs: _mock_forecast(),
        )
        monkeypatch.setattr(
            workflow_engine_module,
            "serialize_cost_forecast",
            lambda _forecast: {"estimated_credits": _forecast.estimated_credits},
        )
        monkeypatch.setattr(
            WorkflowEngine,
            "_enqueue_audit_payload",
            lambda self, *, job_key, payload: None,
        )

        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Auto Re-Audit",
            trigger_config={"type": "platform_event", "event_key": "alert.triggered"},
            actions_config=[{"type": "run_audit", "config": {"tier": "fast"}}],
            cooldown_minutes=0,
            is_active=True,
        )
        db.add(workflow)
        db.commit()

        runs = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="alert.triggered",
            context={"target_url": "https://alpha.example"},
        )

        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert "already running" in str(runs[0].action_results[0]["error"]).lower()
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_workflow_engine_create_jira_ticket_action_creates_export_row(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_project(db)
        db.add(
            models.JiraConnection(
                workspace_id=workspace.id,
                access_token="jira-access-token",
                cloud_id="cloud-123",
                default_jira_project_key="SYN",
                site_url="https://example.atlassian.net",
            )
        )
        db.commit()

        monkeypatch.setattr(
            workflow_engine_module,
            "_run_async_in_sync",
            lambda callable_factory: SimpleNamespace(
                issue_id="10001",
                issue_key="SYN-12",
                issue_url="https://example.atlassian.net/browse/SYN-12",
            ),
        )

        workflow = models.Workflow(
            workspace_id=workspace.id,
            project_id=project.id,
            created_by_user_id=user.id,
            name="Jira Ticketing",
            trigger_config={"type": "platform_event", "event_key": "audit.completed"},
            actions_config=[
                {
                    "type": "create_jira_ticket",
                    "config": {
                        "summary": "[{project_name}] {event_key}",
                        "description": "Audit URL: {target_url}",
                    },
                }
            ],
            cooldown_minutes=0,
            is_active=True,
        )
        db.add(workflow)
        db.commit()

        runs = WorkflowEngine(db).evaluate_event(
            workspace_id=workspace.id,
            project_id=project.id,
            event_key="audit.completed",
            context={"target_url": "https://alpha.example"},
        )

        assert len(runs) == 1
        assert runs[0].status == "completed"
        assert runs[0].action_results[0]["issue_key"] == "SYN-12"

        export = (
            db.query(models.ProjectJiraExport)
            .filter(models.ProjectJiraExport.project_id == project.id)
            .order_by(models.ProjectJiraExport.id.desc())
            .first()
        )
        assert export is not None
        assert export.issue_key == "SYN-12"
        assert export.jira_project_key == "SYN"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
