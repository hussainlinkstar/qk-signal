"""SIGV2-1025 Part 1: the shared Google refresh primitive.

One implementation refreshes Google OAuth connections for both the GA4
data-access path and the workspace catalog path. These tests pin the superset
behaviour: provider validation, rotated-token persistence including
``token_type`` and ``scope``, and reason-code-only errors.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from app.services.google_oauth_service import (
    GoogleOAuthRefreshError,
    derive_expires_at,
    refresh_google_oauth_connection,
)
from app.services.geo.ga4_oauth_service import GA4TokenRefreshError, ga4_access_token


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _google_connection(db: Session, *, expired: bool = True) -> models.OAuthConnection:
    user = models.User(email="ref@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name="ws", owner_id=user.id)
    db.add(ws)
    db.flush()
    conn = models.OAuthConnection(
        workspace_id=ws.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="expired-token",
        refresh_token="refresh-1",
        token_type="Bearer",
        scope="old-scope",
        expires_at=(
            datetime.now(timezone.utc) - timedelta(minutes=5)
            if expired
            else datetime.now(timezone.utc) + timedelta(hours=1)
        ),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


class _Resp:
    def __init__(self, status: int, payload: dict):
        self.status_code = status
        self._payload = payload
        self.content = b"x"
        self.text = str(payload)

    def json(self):
        return self._payload


def _stub_token_endpoint(monkeypatch, payload=None, status=200):
    import httpx
    from core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csecret")

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, json=None, headers=None, **kw):
            assert "oauth2.googleapis.com/token" in url
            return _Resp(
                status,
                payload
                or {
                    "access_token": "fresh-token",
                    "refresh_token": "rotated-refresh",
                    "token_type": "Bearer",
                    "scope": "new-scope",
                    "expires_in": 3600,
                },
            )

    monkeypatch.setattr(httpx, "Client", _Client)


def test_workspace_path_refreshes_and_persists_full_token_set(db: Session, monkeypatch) -> None:
    conn = _google_connection(db)
    _stub_token_endpoint(monkeypatch)
    result = refresh_google_oauth_connection(db, conn)
    assert result.access_token == "fresh-token"
    assert result.refresh_token == "rotated-refresh"
    assert result.token_type == "Bearer"
    assert result.scope == "new-scope"
    expires_at = result.expires_at
    if expires_at.tzinfo is None:  # sqlite readback drops tzinfo
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    assert expires_at > datetime.now(timezone.utc) + timedelta(minutes=55)


def test_ga4_path_also_persists_token_type_and_scope(db: Session, monkeypatch) -> None:
    conn = _google_connection(db)
    project = models.Project(workspace_id=conn.workspace_id, name="p", language="en")
    db.add(project)
    db.flush()
    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
        source_id="properties/123",
        is_active=True,
        oauth_connection_id=conn.id,
    )
    db.add(source)
    db.commit()

    _stub_token_endpoint(monkeypatch)
    token = ga4_access_token(db, source)
    assert token == "fresh-token"
    db.refresh(conn)
    assert conn.token_type == "Bearer"
    assert conn.scope == "new-scope"
    assert conn.refresh_token == "rotated-refresh"


def test_ga4_path_wraps_refresh_errors_as_ga4_type(db: Session, monkeypatch) -> None:
    conn = _google_connection(db)
    project = models.Project(workspace_id=conn.workspace_id, name="p", language="en")
    db.add(project)
    db.flush()
    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
        source_id="properties/123",
        is_active=True,
        oauth_connection_id=conn.id,
    )
    db.add(source)
    db.commit()

    _stub_token_endpoint(monkeypatch, status=400, payload={"error": "invalid_grant"})
    with pytest.raises(GA4TokenRefreshError):
        ga4_access_token(db, source)


def test_non_google_provider_rejected(db: Session) -> None:
    conn = _google_connection(db)
    conn.provider = models.OAuthProvider.BING
    db.commit()
    with pytest.raises(GoogleOAuthRefreshError, match="provider_not_google"):
        refresh_google_oauth_connection(db, conn)


def test_error_messages_carry_no_secret_material(db: Session, monkeypatch) -> None:
    conn = _google_connection(db)
    conn.refresh_token = "secret-refresh-value"
    db.commit()
    _stub_token_endpoint(monkeypatch, status=400, payload={"error": "x"})
    with pytest.raises(GoogleOAuthRefreshError) as err:
        refresh_google_oauth_connection(db, conn)
    for secret in ("secret-refresh-value", "csecret", "expired-token"):
        assert secret not in str(err.value)


def test_derive_expires_at_both_shapes() -> None:
    epoch = 1790000000
    assert derive_expires_at({"expires_at": epoch}) == datetime.fromtimestamp(
        epoch, tz=timezone.utc
    )
    approx = derive_expires_at({"expires_in": 3600})
    assert approx > datetime.now(timezone.utc) + timedelta(minutes=55)
    assert derive_expires_at({}) is None
