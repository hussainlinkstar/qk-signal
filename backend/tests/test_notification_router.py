from __future__ import annotations

from pathlib import Path
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from services.email_service import EmailService
from services.notification_router import NotificationRouter


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session(), engine


def _seed_workspace(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
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
            team_name="Ops HQ",
            default_channel_id="C123",
            default_channel_name="seo-alerts",
        )
    )
    db.add(
        models.TeamsConnection(
            workspace_id=workspace.id,
            webhook_url="https://teams.example/webhook",
            channel_name="Delivery Ops",
        )
    )
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    db.refresh(project)
    return user, workspace, project


def test_notification_router_dispatches_email_slack_and_teams(monkeypatch) -> None:
    db, engine = _build_db()
    try:
        user, workspace, project = _seed_workspace(db)
        queued_emails: list[dict[str, object]] = []
        posts: list[tuple[str, dict[str, object]]] = []

        def fake_queue_template_email(self, **kwargs):
            queued_emails.append(kwargs)
            return None

        def fake_post_json(self, url, payload, *, headers):
            posts.append((url, dict(payload)))
            return {"ok": True}

        monkeypatch.setattr(EmailService, "queue_template_email", fake_queue_template_email)
        monkeypatch.setattr(NotificationRouter, "_post_json", fake_post_json)

        NotificationRouter(db).dispatch_event(
            workspace_id=workspace.id,
            event_key="audit.completed",
            context={
                "project_name": project.name,
                "workspace_name": workspace.name,
                "target_url": project.domain_url,
            },
            user=user,
            to_email=user.email,
            correlation_id="audit-123",
        )

        assert queued_emails[0]["template_key"] == "audit.completed"
        assert queued_emails[0]["to_email"] == "owner@example.com"
        assert posts[0][0] == "https://slack.com/api/chat.postMessage"
        assert posts[0][1]["channel"] == "C123"
        assert posts[1][0] == "https://teams.example/webhook"
        assert posts[1][1]["attachments"][0]["content"]["body"][0]["text"] == "Audit completed"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
