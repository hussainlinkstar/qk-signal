from __future__ import annotations

from pathlib import Path
import os
import sys

from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db
from routers import slack_router, teams_router


def _build_client() -> tuple[TestClient, Session, object, models.User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        email="owner@example.com", hashed_password="x", role="user", notifications_enabled=True
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user() -> models.User:
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    return TestClient(app), db, engine, user


def test_slack_oauth_callback_persists_workspace_connection(monkeypatch) -> None:
    client, db, engine, _user = _build_client()
    monkeypatch.setenv("SLACK_CLIENT_ID", "slack-client-id")
    monkeypatch.setattr(slack_router.plan_validator, "has_feature", lambda *_args, **_kwargs: True)

    async def fake_authorize_redirect(_request, callback_url):
        assert callback_url.endswith("/api/v1/integrations/slack/callback")
        return RedirectResponse("https://slack.example/authorize")

    async def fake_authorize_access_token(_request):
        return {
            "access_token": "xoxb-test",
            "scope": "chat:write channels:read incoming-webhook",
            "team": {"id": "T123", "name": "Ops HQ"},
            "bot_user_id": "B123",
            "incoming_webhook": {
                "url": "https://hooks.slack.example/123",
                "channel": "seo-alerts",
                "channel_id": "C123",
            },
        }

    monkeypatch.setattr(slack_router.oauth.slack, "authorize_redirect", fake_authorize_redirect)
    monkeypatch.setattr(
        slack_router.oauth.slack, "authorize_access_token", fake_authorize_access_token
    )

    authorize_response = client.get("/api/v1/integrations/slack/authorize", follow_redirects=False)
    assert authorize_response.status_code in {302, 307}

    callback_response = client.get("/api/v1/integrations/slack/callback", follow_redirects=False)
    assert callback_response.status_code in {302, 307}
    assert "provider=slack" in callback_response.headers["location"]
    assert "status=connected" in callback_response.headers["location"]

    connection = db.query(models.SlackConnection).first()
    assert connection is not None
    assert connection.team_name == "Ops HQ"
    assert connection.default_channel_id == "C123"
    assert connection.default_channel_name == "seo-alerts"

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_slack_callback_rechecks_plan_before_persisting(monkeypatch) -> None:
    client, db, engine, _user = _build_client()
    monkeypatch.setenv("SLACK_CLIENT_ID", "slack-client-id")
    access_allowed = True
    monkeypatch.setattr(
        slack_router.plan_validator,
        "has_feature",
        lambda *_args, **_kwargs: access_allowed,
    )

    async def fake_authorize_redirect(_request, _callback_url):
        return RedirectResponse("https://slack.example/authorize")

    token_exchange = False

    async def fake_authorize_access_token(_request):
        nonlocal token_exchange
        token_exchange = True
        return {"access_token": "xoxb-test", "team": {"id": "T123"}}

    monkeypatch.setattr(slack_router.oauth.slack, "authorize_redirect", fake_authorize_redirect)
    monkeypatch.setattr(
        slack_router.oauth.slack, "authorize_access_token", fake_authorize_access_token
    )

    assert client.get(
        "/api/v1/integrations/slack/authorize", follow_redirects=False
    ).status_code in {302, 307}
    access_allowed = False
    callback_response = client.get("/api/v1/integrations/slack/callback", follow_redirects=False)

    assert callback_response.status_code in {302, 307}
    assert "status=error" in callback_response.headers["location"]
    assert token_exchange is False
    assert db.query(models.SlackConnection).count() == 0

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_locked_slack_and_teams_status_reads_are_descriptive_but_mutations_remain_gated(
    monkeypatch,
) -> None:
    client, db, engine, _user = _build_client()
    monkeypatch.setattr(slack_router.plan_validator, "has_feature", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(teams_router.plan_validator, "has_feature", lambda *_args, **_kwargs: False)

    slack_status = client.get("/api/v1/integrations/slack/status")
    teams_status = client.get("/api/v1/integrations/teams/status")

    assert slack_status.status_code == 200
    assert slack_status.json() == {
        "is_connected": False,
        "is_plan_locked": True,
        "detail": "Slack integrations require Specialist or higher.",
        "team_id": None,
        "team_name": None,
        "bot_user_id": None,
        "default_channel_id": None,
        "default_channel_name": None,
        "scope": None,
        "updated_at": None,
    }
    assert teams_status.status_code == 200
    assert teams_status.json() == {
        "is_connected": False,
        "is_plan_locked": True,
        "detail": "Microsoft Teams integrations require Specialist or higher.",
        "channel_name": None,
        "webhook_preview": None,
        "updated_at": None,
    }
    assert client.post("/api/v1/integrations/teams/test").status_code == 402
    assert client.post("/api/v1/integrations/slack/test", json={}).status_code == 402

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_slack_channels_endpoint_lists_available_channels(monkeypatch) -> None:
    client, db, engine, user = _build_client()
    monkeypatch.setattr(slack_router.plan_validator, "has_feature", lambda *_args, **_kwargs: True)
    workspace = models.Workspace(name="Signal Forge", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(
        models.SlackConnection(
            workspace_id=workspace.id,
            access_token="xoxb-test",
            team_id="T123",
            team_name="Ops HQ",
            default_channel_id="C123",
        )
    )
    db.commit()

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"ok": True, "channels": [{"id": "C123", "name": "seo-alerts"}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(slack_router.httpx, "AsyncClient", FakeAsyncClient)

    response = client.get("/api/v1/integrations/slack/channels")
    assert response.status_code == 200
    assert response.json() == [{"id": "C123", "name": "seo-alerts"}]

    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
