"""SIGV2-1220: the GA4 OAuth return has to be able to land back in onboarding.

Connecting GA4 at onboarding step 4 is a full browser navigation, so the
callback decides where the customer comes back to. Every return used to be
hard-coded to ``/dashboard/connections``, which dropped the customer out of the
wizard: the project was already created, so the wizard would not reopen at all
and the remaining steps were unreachable.

The start request may therefore name a return destination, but only by key.
The key resolves against a closed map in the router, so nothing a caller sends
can become the redirect target, and the choice travels inside the OAuth session
state the flow already validates rather than through the callback's query
string.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models  # noqa: E402
from database import Base  # noqa: E402
import routers.workspace_router as wr  # noqa: E402


def _build_db() -> tuple[Session, models.User, models.Workspace]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = session_factory()
    user = models.User(email="owner@example.com", hashed_password="x", role="user")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Agency", owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=user.id,
            role=models.WorkspaceRole.ADMIN,
        )
    )
    db.commit()
    db.refresh(user)
    db.refresh(workspace)
    return db, user, workspace


class _FakeStartRequest:
    def __init__(self) -> None:
        self.session: dict[str, dict[str, object]] = {}
        self.query_params: dict[str, str] = {}

    def url_for(self, name: str, **_params) -> str:
        return f"https://backend.test/{name}"


class _FakeAuthorizeClient:
    async def authorize_redirect(self, request, redirect_uri, **_kwargs):
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="https://provider.test/authorize", status_code=307)


class _FakeCallbackRequest:
    def __init__(self, session: dict[str, object], query_params: dict[str, str]) -> None:
        self.session = session
        self.query_params = query_params


class _FakeTokenClient:
    async def authorize_access_token(self, _request):
        return {
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "token_type": "Bearer",
            "scope": "analytics.readonly",
            "expires_at": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        }


def _start(
    monkeypatch,
    db: Session,
    user: models.User,
    workspace_id: int,
    **kwargs,
) -> _FakeStartRequest:
    request = _FakeStartRequest()
    monkeypatch.setattr(wr.oauth, "create_client", lambda _name: _FakeAuthorizeClient())
    monkeypatch.setattr(wr, "_oauth_provider_configured", lambda _provider: True)
    asyncio.run(
        wr._start_workspace_oauth_flow(
            request=request,  # type: ignore[arg-type]
            db=db,
            user=user,
            provider="google",
            callback_route_name="workspace_google_oauth_callback",
            authorize_kwargs={"scope": "openid"},
            workspace_id=workspace_id,
            **kwargs,
        )
    )
    return request


def _finish(monkeypatch, db: Session, session_payload: dict[str, object], **query):
    monkeypatch.setattr(wr.oauth, "create_client", lambda _name: _FakeTokenClient())
    request = _FakeCallbackRequest(
        {wr._workspace_oauth_session_key("google"): session_payload},
        dict(query),
    )
    return asyncio.run(
        wr._finish_workspace_oauth_flow(
            request=request,  # type: ignore[arg-type]
            db=db,
            provider="google",
        )
    )


def test_start_records_the_onboarding_return_in_the_oauth_session(monkeypatch) -> None:
    db, user, workspace = _build_db()

    request = _start(monkeypatch, db, user, workspace.id, return_to="onboarding")

    payload = request.session["workspace_google_oauth"]
    # SIGV2-1207's workspace binding is untouched; the destination rides
    # alongside it inside the same validated session entry.
    assert payload["workspace_id"] == workspace.id
    assert payload["user_id"] == user.id
    assert payload["return_to"] == "onboarding"


def test_start_defaults_to_the_connections_hub(monkeypatch) -> None:
    db, user, workspace = _build_db()

    request = _start(monkeypatch, db, user, workspace.id)

    payload = request.session["workspace_google_oauth"]
    assert payload["return_to"] == "connections"


def test_start_refuses_an_unknown_return_destination(monkeypatch) -> None:
    """Only keys in the closed map are accepted. An arbitrary destination is
    refused rather than quietly replaced, the same rule SIGV2-1207 applied to
    an inaccessible workspace id."""
    db, user, workspace = _build_db()

    for rejected in ("https://evil.example/steal", "//evil.example", "/dashboard/billing", ""):
        with pytest.raises(HTTPException) as excinfo:
            _start(monkeypatch, db, user, workspace.id, return_to=rejected)
        assert excinfo.value.status_code == 400


def test_successful_onboarding_return_lands_back_on_the_wizard(monkeypatch) -> None:
    db, user, workspace = _build_db()

    response = _finish(
        monkeypatch,
        db,
        {"workspace_id": workspace.id, "user_id": user.id, "return_to": "onboarding"},
    )

    location = response.headers["location"]
    assert "/dashboard/overview?" in location
    assert "provider=google" in location
    assert "status=connected" in location
    # The connection itself still had to be stored; the destination is the only
    # thing this ticket changes.
    assert db.query(models.OAuthConnection).count() == 1


def test_cancelled_onboarding_connect_returns_to_the_wizard_too(monkeypatch) -> None:
    """Cancellation must keep the customer in the flow they were in, with the
    reason, so Retry and Skip are both still reachable."""
    db, user, workspace = _build_db()

    response = _finish(
        monkeypatch,
        db,
        {"workspace_id": workspace.id, "user_id": user.id, "return_to": "onboarding"},
        error="access_denied",
    )

    location = response.headers["location"]
    assert "/dashboard/overview?" in location
    assert "status=error" in location
    assert "message=access_denied" in location
    # SIGV2-1202: a cancelled OAuth proves nothing, so no connection is written.
    assert db.query(models.OAuthConnection).count() == 0


def test_connections_hub_return_is_unchanged(monkeypatch) -> None:
    db, user, workspace = _build_db()

    response = _finish(
        monkeypatch,
        db,
        {"workspace_id": workspace.id, "user_id": user.id, "return_to": "connections"},
    )

    assert "/dashboard/connections?" in response.headers["location"]


def test_a_session_without_a_destination_still_returns_to_connections(monkeypatch) -> None:
    """Sessions written before this change carry no return_to at all."""
    db, user, workspace = _build_db()

    response = _finish(
        monkeypatch,
        db,
        {"workspace_id": workspace.id, "user_id": user.id},
    )

    assert "/dashboard/connections?" in response.headers["location"]


def test_a_tampered_session_destination_falls_back_to_connections(monkeypatch) -> None:
    """Defence in depth: the callback re-resolves the key against the same
    closed map instead of trusting the stored value as a path."""
    db, user, workspace = _build_db()

    response = _finish(
        monkeypatch,
        db,
        {
            "workspace_id": workspace.id,
            "user_id": user.id,
            "return_to": "https://evil.example/steal",
        },
    )

    location = response.headers["location"]
    assert "/dashboard/connections?" in location
    assert "evil.example" not in location


def test_a_missing_oauth_session_returns_to_connections(monkeypatch) -> None:
    db, _user, _workspace = _build_db()
    monkeypatch.setattr(wr.oauth, "create_client", lambda _name: _FakeTokenClient())
    request = _FakeCallbackRequest({}, {})

    response = asyncio.run(
        wr._finish_workspace_oauth_flow(
            request=request,  # type: ignore[arg-type]
            db=db,
            provider="google",
        )
    )

    assert "/dashboard/connections?" in response.headers["location"]
    assert "message=oauth_session_missing" in response.headers["location"]


def test_google_start_endpoint_passes_the_return_destination_through() -> None:
    captured: dict[str, object] = {}

    async def _fake_start(**kwargs):
        captured.update(kwargs)
        return "redirect"

    original = wr._start_workspace_oauth_flow
    wr._start_workspace_oauth_flow = _fake_start
    try:
        asyncio.run(
            wr.start_google_workspace_oauth(
                request=object(),
                workspace_id=77,
                return_to="onboarding",
                user=object(),
                db=object(),
            )
        )
    finally:
        wr._start_workspace_oauth_flow = original

    assert captured["workspace_id"] == 77
    assert captured["return_to"] == "onboarding"
    # SIGV2-1202's account picker and refresh-token consent still ride along.
    assert "select_account" in str(captured["authorize_kwargs"]["prompt"])  # type: ignore[index]
    assert "consent" in str(captured["authorize_kwargs"]["prompt"])  # type: ignore[index]
