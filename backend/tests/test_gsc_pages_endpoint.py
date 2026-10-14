"""SIGV2-1025: /monitoring/search-console/pages endpoint tests.

Tenant isolation, availability states, and the rule that no token material
reaches a response.
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


def _project_with_gsc(
    db: Session, name: str, *, connection: bool = True
) -> tuple[models.User, models.Project, models.ProjectDataSource]:
    user = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name=f"{name} ws", owner_id=user.id)
    db.add(ws)
    db.flush()
    project = models.Project(workspace_id=ws.id, name=name, language="en")
    db.add(project)
    db.flush()

    conn = None
    if connection:
        conn = models.OAuthConnection(
            workspace_id=ws.id,
            provider=models.OAuthProvider.GOOGLE,
            access_token="secret-access-token",
            refresh_token="secret-refresh-token",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db.add(conn)
        db.flush()

    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
        source_id="sc-domain:example.com",
        is_active=True,
        oauth_connection_id=conn.id if conn else None,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return user, project, source


def test_disconnected_without_gsc_source(db: Session) -> None:
    user = models.User(email="x@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name="ws", owner_id=user.id)
    db.add(ws)
    db.flush()
    project = models.Project(workspace_id=ws.id, name="p", language="en")
    db.add(project)
    db.commit()

    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"


def test_unsupported_window_rejected(db: Session) -> None:
    user, project, _ = _project_with_gsc(db, "Win")
    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages?window=30D"
    )
    assert response.status_code == 422


def test_foreign_project_property_refused(db: Session) -> None:
    _owner, project, _ = _project_with_gsc(db, "Owner")
    outsider = models.User(email="out@example.com", hashed_password="x")
    db.add(outsider)
    db.commit()

    response = _client(db, outsider).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 403


def test_revoked_when_no_connection(db: Session) -> None:
    user, project, source = _project_with_gsc(db, "NoConn", connection=False)
    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    db.refresh(source)
    assert source.last_status == "auth_error"


def test_revoked_on_gsc_403(db: Session, monkeypatch) -> None:
    import app.services.gsc_reporting_service as gsc_mod

    user, project, source = _project_with_gsc(db, "Denied")
    service = gsc_mod.GSCReportingService(access_token="tok")

    def denied(*a, **k):
        raise gsc_mod.GSCPermissionError("gsc_access_denied_403")

    monkeypatch.setattr(
        gsc_mod.GSCReportingService, "query_search_analytics", lambda *a, **k: denied()
    )
    monkeypatch.setattr(gsc_mod, "GSCReportingService", lambda access_token: service, raising=True)
    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    db.refresh(source)
    assert source.last_status == "auth_error"


def test_provider_error_on_gsc_429_with_retry(db: Session, monkeypatch) -> None:
    import app.services.gsc_reporting_service as gsc_mod

    user, project, source = _project_with_gsc(db, "Limited")

    def limited(*a, **k):
        raise gsc_mod.GSCRateLimitError("gsc_rate_limited")

    monkeypatch.setattr(
        gsc_mod.GSCReportingService, "query_search_analytics", lambda *a, **k: limited()
    )
    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "provider_error"
    assert body["retry"] is True
    db.refresh(source)
    assert source.last_status == "error"
    assert source.last_error == "rate_limited"


def test_success_payload_and_no_secret_material(db: Session, monkeypatch) -> None:
    import json as _json

    import app.services.gsc_reporting_service as gsc_mod

    user, project, source = _project_with_gsc(db, "Happy")
    from zoneinfo import ZoneInfo

    # A day inside the computed PT window (end = yesterday PT).
    row_date = datetime.now(ZoneInfo("America/Los_Angeles")).date() - timedelta(days=1)
    rows = [
        {
            "page": "https://example.com/a",
            "date": row_date.isoformat(),
            "clicks": 5,
            "impressions": 100,
            "ctr": 0.05,
            "position": 8.0,
        }
    ]
    meta = {
        "completeness": "full",
        "first_incomplete_date": None,
        "response_aggregation_type": "auto",
    }
    monkeypatch.setattr(
        gsc_mod.GSCReportingService,
        "query_search_analytics",
        lambda self, site_url, **k: (rows, meta),
    )

    response = _client(db, user).get(
        f"/api/v1/projects/{project.id}/monitoring/search-console/pages"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["date_basis"] == "America/Los_Angeles"
    assert body["date_alignment"] == "approximate"  # no GA4 binding -> not exact
    assert body["pages"][0]["sessions"] is None
    assert body["pages"][0]["sessions_reason"] == "no_ga4_binding"
    db.refresh(source)
    assert source.last_status == "fresh"
    assert source.last_sync_at is not None

    text = _json.dumps(body)
    for secret in ("secret-access-token", "secret-refresh-token"):
        assert secret not in text
