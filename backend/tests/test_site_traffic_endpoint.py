"""SIGV2-1001: /monitoring/site-traffic endpoint tests.

Covers the contract rules that only exist at the HTTP boundary: tenant
authorization before retrieval, window rejection, availability statuses, and
the rule that no token or secret ever reaches a response body.
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


def _client(db: Session, user: models.User):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.security import get_current_user_from_token as get_current_user
    from database import get_db
    from routers.monitoring_router import router as monitoring_router

    app = FastAPI()
    app.include_router(monitoring_router)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def _project_with_source(
    db: Session,
    name: str,
    *,
    connection: bool = True,
    valid_token: bool = True,
) -> tuple[models.User, models.Project, models.ProjectDataSource]:
    user = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name=f"{name} ws", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name=name, language="en")
    db.add(project)
    db.flush()

    conn = None
    if connection:
        conn = models.OAuthConnection(
            workspace_id=workspace.id,
            provider=models.OAuthProvider.GOOGLE,
            access_token="secret-access-token" if valid_token else "",
            refresh_token="secret-refresh-token",
            scope="https://www.googleapis.com/auth/analytics.readonly",
            expires_at=(
                datetime.now(timezone.utc) + timedelta(hours=1)
                if valid_token
                else datetime.now(timezone.utc) - timedelta(hours=1)
            ),
        )
        db.add(conn)
        db.flush()

    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
        source_id="properties/123456789",
        source_label="Example property",
        is_active=True,
        oauth_connection_id=conn.id if conn else None,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return user, project, source


def test_disconnected_when_no_ga4_source(db: Session) -> None:
    user = models.User(email="nosrc@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="ws", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name="p", language="en")
    db.add(project)
    db.commit()

    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"


def test_unsupported_window_is_rejected_not_clamped(db: Session) -> None:
    user, project, _ = _project_with_source(db, "Win")
    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/site-traffic?window=30D"
    )
    assert response.status_code == 422


def test_foreign_tenant_property_refused(db: Session) -> None:
    _owner, project, _source = _project_with_source(db, "Owner")
    outsider = models.User(email="outsider@example.com", hashed_password="x")
    db.add(outsider)
    db.commit()

    response = _client(db, outsider).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 403


def _stub_fetch_ok(payload: dict):
    def _fetch(service, property_id, window_key, persisted_timezone=None):
        return payload, "Europe/Bucharest"

    return _fetch


def test_success_payload_and_timezone_persisted(db: Session, monkeypatch) -> None:
    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, source = _project_with_source(db, "Happy")
    payload = {
        "window": "7D",
        "availability": "available",
        "property_timezone": "Europe/Bucharest",
        "overview": {"sessions": 400.0, "total_users": 120.0},
    }
    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _stub_fetch_ok(payload))

    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["property_timezone"] == "Europe/Bucharest"
    db.refresh(source)
    assert source.metadata_json["ga4_time_zone"] == "Europe/Bucharest"
    assert source.last_status == "success"
    assert source.last_sync_at is not None


def test_no_secret_material_in_response(db: Session, monkeypatch) -> None:
    import json as _json

    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, _source = _project_with_source(db, "Secrets")
    payload = {
        "window": "7D",
        "availability": "available",
        "property_timezone": "UTC",
        "overview": {"sessions": 0.0},
    }
    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _stub_fetch_ok(payload))

    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    body_text = _json.dumps(response.json())
    for secret in ("secret-access-token", "secret-refresh-token"):
        assert secret not in body_text


def test_disconnected_when_connection_missing(db: Session) -> None:
    # SIGV2-1202 reversed this assertion. It used to require "revoked" for a
    # binding whose OAuth grant no longer exists, which is exactly the state
    # a disconnect leaves behind (the FK is ON DELETE SET NULL). The customer
    # was then told their access had been revoked and asked to reconnect
    # something they had just disconnected: the reconnect loop. No grant is a
    # disconnection and is now reported as one.
    user, project, source = _project_with_source(db, "NoConn", connection=False)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    db.refresh(source)
    assert source.last_status == "disconnected"
    assert "secret" not in (source.last_error or "")


def test_revoked_when_stored_token_cannot_be_refreshed(db: Session, monkeypatch) -> None:
    # An existing grant whose token is expired and unrefreshable is the real
    # "revoked" case, and it keeps that status.
    import app.services.geo.ga4_oauth_service as oauth_mod

    user, project, source = _project_with_source(db, "Stale", valid_token=False)

    def _raise(db_session, src):
        raise oauth_mod.GA4TokenRefreshError("invalid_grant")

    monkeypatch.setattr(oauth_mod, "ga4_access_token", _raise)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    db.refresh(source)
    assert source.last_status == "auth_error"


def test_permission_denied_when_ga4_403(db: Session, monkeypatch) -> None:
    # SIGV2-1202 reversed this assertion. It used to require "revoked" for a
    # 403, so a valid Google account that is simply not granted access to the
    # selected property was told its access had been revoked and sent to
    # reconnect - which changed nothing, because the authorization was fine.
    # A 403 is a permission denial and is now reported as one.
    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, source = _project_with_source(db, "Denied")

    def _denied(service, property_id, window_key, persisted_timezone=None):
        raise svc_mod.GA4PermissionError(
            "ga4_access_denied_403:property_denied",
            status_code=403,
            reason=svc_mod.GA4_REASON_PROPERTY_DENIED,
        )

    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _denied)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "permission_denied"
    assert body["reason"] == "property_denied"
    assert body["availability"] == "unavailable"
    db.refresh(source)
    assert source.last_status == "permission_denied"


def test_missing_scope_403_is_reported_as_insufficient_scope(db: Session, monkeypatch) -> None:
    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, source = _project_with_source(db, "NoScope")

    def _denied(service, property_id, window_key, persisted_timezone=None):
        raise svc_mod.GA4PermissionError(
            "ga4_access_denied_403:insufficient_scope",
            status_code=403,
            reason=svc_mod.GA4_REASON_INSUFFICIENT_SCOPE,
        )

    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _denied)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    body = response.json()
    assert body["status"] == "permission_denied"
    assert body["reason"] == "insufficient_scope"
    db.refresh(source)
    assert source.last_status == "permission_denied"


def test_revoked_when_ga4_401(db: Session, monkeypatch) -> None:
    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, source = _project_with_source(db, "Expired")

    def _denied(service, property_id, window_key, persisted_timezone=None):
        raise svc_mod.GA4PermissionError(
            "ga4_access_denied_401:invalid_credentials",
            status_code=401,
            reason=svc_mod.GA4_REASON_INVALID_CREDENTIALS,
        )

    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _denied)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.json()["status"] == "revoked"
    db.refresh(source)
    assert source.last_status == "auth_error"


def test_provider_error_when_ga4_429(db: Session, monkeypatch) -> None:
    import app.services.geo.ga4_reporting_service as svc_mod

    user, project, source = _project_with_source(db, "RateLtd")

    def _limited(service, property_id, window_key, persisted_timezone=None):
        raise svc_mod.GA4RateLimitError("ga4_rate_limited")

    monkeypatch.setattr(svc_mod, "fetch_site_traffic", _limited)
    response = _client(db, user).get(f"/api/v1/projects/{project.id}/monitoring/site-traffic")
    assert response.status_code == 200
    assert response.json()["status"] == "provider_error"
    db.refresh(source)
    assert source.last_status == "error"
    assert source.last_error == "rate_limited"
