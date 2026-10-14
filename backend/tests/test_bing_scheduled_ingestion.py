"""SIGV2-1265: Bing Webmaster ingestion must not depend on a UI request.

Before this, the only code path that wrote ``project_bing_metrics`` was the
``GET .../monitoring/bing-webmaster/metrics`` handler, and nothing in the
product called it, so a bound Bing site never ingested anything. Ingestion now
lives in one service call that the scheduled monitoring worker runs, and the
endpoint delegates to the same call. Every outbound call is mocked.
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
from app.services.bing_webmaster_service import (
    BingWebmasterService,
    sync_project_bing_source,
)


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


def _project(db: Session, name: str) -> models.Project:
    user = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name=f"{name} ws", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name=name, language="en")
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _bing_source(
    db: Session,
    project: models.Project,
    *,
    site_url: str = "https://owned.example.com",
    is_active: bool = True,
) -> models.ProjectDataSource:
    connection = models.OAuthConnection(
        workspace_id=project.workspace_id,
        provider=models.OAuthProvider.BING,
        access_token="bing-access-token",
        refresh_token="bing-refresh-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        scope="webmaster.manage",
    )
    db.add(connection)
    db.flush()
    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.BING,
        source_type=models.ProjectDataSourceType.BING_WEBMASTER,
        binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
        source_id=site_url,
        is_active=is_active,
        oauth_connection_id=connection.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _configured_deployment(monkeypatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_SECRET", "client-secret")


def _bing_api_mock(monkeypatch, *, owned: list[str], stats: list[dict]) -> None:
    def fake_get(self, path, params):
        if path == "GetUserSites":
            return {"d": [{"Url": url} for url in owned]}
        if path in ("GetRankAndTrafficStats", "GetQueryStats", "GetPageStats"):
            return {"d": stats}
        raise AssertionError(path)

    monkeypatch.setattr(BingWebmasterService, "_get", fake_get)


def _stats_row(day: datetime) -> dict:
    ms = int(day.timestamp() * 1000)
    return {
        "Date": f"/Date({ms}+0000)/",
        "Clicks": 12,
        "Impressions": 120,
        "AvgClickPosition": 18,
        "AvgImpressionPosition": 17,
        "Query": "qiko",
        "Url": "https://owned.example.com/a",
    }


def test_sync_runs_without_any_http_request_to_our_api(db, monkeypatch) -> None:
    project = _project(db, "SyncProj")
    source = _bing_source(db, project)
    _bing_api_mock(
        monkeypatch,
        owned=["https://owned.example.com"],
        stats=[_stats_row(datetime(2026, 10, 20, tzinfo=timezone.utc))],
    )

    result = sync_project_bing_source(db, source)

    assert result.status == "ok"
    assert result.site_url == "https://owned.example.com"
    assert result.rows_written > 0
    stored = db.query(models.ProjectBingMetric).filter_by(project_id=project.id).all()
    assert {row.dimension_type for row in stored} == {"site", "query", "page"}
    assert source.last_status == "fresh"
    assert source.last_sync_at is not None


def test_sync_refuses_a_site_the_connected_account_does_not_own(db, monkeypatch) -> None:
    project = _project(db, "UnownedProj")
    source = _bing_source(db, project)
    _bing_api_mock(monkeypatch, owned=["https://someone-else.example.com"], stats=[])

    result = sync_project_bing_source(db, source)

    assert result.status == "site_not_owned"
    assert result.rows_written == 0
    assert db.query(models.ProjectBingMetric).count() == 0
    assert source.last_status == "auth_error"


def test_sync_reports_a_binding_with_no_site_url(db, monkeypatch) -> None:
    project = _project(db, "NoSiteProj")
    source = _bing_source(db, project, site_url="   ")
    _bing_api_mock(monkeypatch, owned=[], stats=[])

    result = sync_project_bing_source(db, source)

    assert result.status == "provider_error"
    assert result.reason == "missing_site_url"
    assert source.last_status == "error"


def test_monitoring_worker_skips_a_deployment_without_bing_credentials(db, monkeypatch) -> None:
    import monitoring_worker
    from core.config import settings

    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_ID", "")
    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_SECRET", "")
    project = _project(db, "UnconfiguredProj")
    _bing_source(db, project)

    assert monitoring_worker._sync_bing_webmaster(db) == 0
    assert db.query(models.ProjectBingMetric).count() == 0


def test_monitoring_worker_ingests_every_active_bing_binding(db, monkeypatch) -> None:
    import monitoring_worker

    _configured_deployment(monkeypatch)
    active_project = _project(db, "ActiveProj")
    active_source = _bing_source(db, active_project)
    inactive_project = _project(db, "InactiveProj")
    _bing_source(db, inactive_project, is_active=False)
    _bing_api_mock(
        monkeypatch,
        owned=["https://owned.example.com"],
        stats=[_stats_row(datetime(2026, 10, 21, tzinfo=timezone.utc))],
    )

    synced = monitoring_worker._sync_bing_webmaster(db)

    assert synced == 1
    assert db.query(models.ProjectBingMetric).filter_by(project_id=active_project.id).count() > 0
    assert db.query(models.ProjectBingMetric).filter_by(project_id=inactive_project.id).count() == 0
    db.refresh(active_source)
    assert active_source.last_status == "fresh"


def test_monitoring_worker_keeps_going_when_one_binding_fails(db, monkeypatch) -> None:
    import monitoring_worker

    _configured_deployment(monkeypatch)
    broken_project = _project(db, "BrokenProj")
    broken_source = _bing_source(db, broken_project, site_url="https://broken.example.com")
    healthy_project = _project(db, "HealthyProj")
    _bing_source(db, healthy_project)
    _bing_api_mock(
        monkeypatch,
        owned=["https://owned.example.com"],
        stats=[_stats_row(datetime(2026, 10, 22, tzinfo=timezone.utc))],
    )

    synced = monitoring_worker._sync_bing_webmaster(db)

    assert synced == 1
    db.refresh(broken_source)
    assert broken_source.last_status == "auth_error"
    assert db.query(models.ProjectBingMetric).filter_by(project_id=healthy_project.id).count() > 0
