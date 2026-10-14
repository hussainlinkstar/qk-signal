"""SIGNAL-1061: GA4 sync uses the customer's own OAuth token and reports status.

Data pulled with the granted token, not the shared service account.
Status fields on project_data_sources must tell the truth:
success / error (with reason) / auth_error (reconnect needed).
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
from app.services.geo.ga4_traffic_service import GA4TrafficService
from monitoring_worker import _resolve_ga4_targets, _sync_ga4_traffic


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


def _project_with_ga4_source(
    db: Session, name: str, *, connection: bool = True
) -> tuple[models.Project, models.ProjectDataSource, models.OAuthConnection | None]:
    owner = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(owner)
    db.flush()
    workspace = models.Workspace(name=f"{name} ws", owner_id=owner.id)
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
            access_token="expired-token",
            refresh_token="refresh-1",
            scope="https://www.googleapis.com/auth/analytics.readonly",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
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
    return project, source, conn


def test_bearer_token_mode_needs_no_service_account() -> None:
    service = GA4TrafficService(access_token="user-token-abc")
    assert service._get_access_token() == "user-token-abc"


def test_resolve_targets_carries_the_data_source_row(db: Session) -> None:
    project, source, _ = _project_with_ga4_source(db, "Targeted")
    targets = _resolve_ga4_targets(db)
    assert len(targets) == 1
    assert targets[0].project_id == project.id
    assert targets[0].data_source is source or targets[0].data_source.id == source.id


def _stub_ga4_api(monkeypatch, calls: list[str], fail: bool = False) -> None:
    """Stub token refresh + GA4 runReport; record bearer tokens used."""
    import httpx
    import app.services.geo.ga4_traffic_service as svc_mod
    from core.config import settings

    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "csecret")

    class _Resp:
        def __init__(self, status: int, payload: dict):
            self.status_code = status
            self._payload = payload
            self.content = b"x"
            self.text = str(payload)

        def json(self):
            return self._payload

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, json=None, headers=None, **kw):
            auth = (headers or {}).get("Authorization", "")
            calls.append(auth)
            if "oauth2.googleapis.com/token" in url:
                return _Resp(200, {"access_token": "fresh-token", "expires_in": 3600})
            if fail:
                return _Resp(403, {"error": {"message": "forbidden"}})
            return _Resp(200, {"rows": []})

    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(svc_mod.httpx, "Client", _Client)


def test_sync_uses_refreshed_user_token_and_marks_success(db: Session, monkeypatch) -> None:
    _project_with_ga4_source(db, "Synced")
    calls: list[str] = []
    _stub_ga4_api(monkeypatch, calls)

    synced = _sync_ga4_traffic(db)

    assert synced == 1
    assert "Bearer fresh-token" in calls
    assert "Bearer expired-token" not in calls

    source = db.query(models.ProjectDataSource).first()
    assert source.last_status == "success"
    assert source.last_sync_at is not None
    assert source.last_error is None


def test_sync_failure_records_reason(db: Session, monkeypatch) -> None:
    _project_with_ga4_source(db, "Failing")
    calls: list[str] = []
    _stub_ga4_api(monkeypatch, calls, fail=True)

    synced = _sync_ga4_traffic(db)

    assert synced == 0
    source = db.query(models.ProjectDataSource).first()
    assert source.last_status == "error"
    assert source.last_error
    assert "fresh-token" not in source.last_error


def test_missing_connection_marks_auth_error(db: Session, monkeypatch) -> None:
    _project_with_ga4_source(db, "NoConn", connection=False)
    calls: list[str] = []
    _stub_ga4_api(monkeypatch, calls)

    synced = _sync_ga4_traffic(db)

    assert synced == 0
    source = db.query(models.ProjectDataSource).first()
    assert source.last_status == "auth_error"


def test_refresh_failure_marks_auth_error(db: Session, monkeypatch) -> None:
    _project_with_ga4_source(db, "BadRefresh")
    import httpx

    class _Client:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, json=None, headers=None, **kw):
            class R:
                status_code = 400
                content = b"x"
                text = "invalid_grant"

                def json(self):
                    return {"error": "invalid_grant"}

            return R()

    monkeypatch.setattr(httpx, "Client", _Client)

    synced = _sync_ga4_traffic(db)

    assert synced == 0
    source = db.query(models.ProjectDataSource).first()
    assert source.last_status == "auth_error"


# ---------------------------------------------------------------------------
# llm-traffic endpoint gating: the band disappears when the source is removed
# ---------------------------------------------------------------------------


def _llm_traffic_client(db: Session, user: models.User):
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


def _project_owner(db: Session, name: str) -> tuple[models.User, models.Project]:
    user = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name=f"{name} ws", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name=name, language="en")
    db.add(project)
    db.commit()
    return user, project


def test_llm_traffic_empty_without_ga4_source(db: Session) -> None:
    from datetime import date as _date

    user, project = _project_owner(db, "NoSource")
    db.add(
        models.LLMTrafficSnapshot(
            project_id=project.id,
            source="chatgpt.com",
            snapshot_date=_date.today(),
            sessions=10,
            users=8,
            page_views=12,
        )
    )
    db.commit()

    client = _llm_traffic_client(db, user)
    response = client.get(f"/api/v1/projects/{project.id}/monitoring/llm-traffic")

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_llm_traffic_returns_data_with_active_source(db: Session) -> None:
    from datetime import date as _date

    user, project = _project_owner(db, "WithSource")
    db.add(
        models.ProjectDataSource(
            project_id=project.id,
            provider=models.OAuthProvider.GOOGLE,
            source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            source_id="properties/123456789",
            is_active=True,
        )
    )
    db.add(
        models.LLMTrafficSnapshot(
            project_id=project.id,
            source="chatgpt.com",
            snapshot_date=_date.today(),
            sessions=10,
            users=8,
            page_views=12,
        )
    )
    db.commit()

    client = _llm_traffic_client(db, user)
    response = client.get(f"/api/v1/projects/{project.id}/monitoring/llm-traffic")

    assert response.status_code == 200
    assert response.json()["total_sessions"] == 10
