"""SIGV2-1082: Bing Webmaster OAuth + metrics ingestion.

The Webmaster connection is a real OAuth provider distinct from the Entra
``bing`` client; unconfigured deployments report explicit unavailability; the
.NET date format parses to correct UTC; position is always unavailable with a
reason while the raw integers are retained; and Bing rows never merge with
Search Console rows. Every outbound call is mocked.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from app.services import bing_webmaster_service as bing
from app.services.bing_webmaster_service import (
    BING_TOKEN_URL,
    POSITION_UNAVAILABLE_REASON,
    BingWebmasterApiError,
    BingWebmasterConfigError,
    BingWebmasterService,
    bing_access_token,
    bing_webmaster_oauth_configured,
    exchange_code_for_tokens,
    normalize_stats_row,
    parse_bing_dotnet_date,
    position_payload,
    refresh_bing_oauth_connection,
    sync_bing_metrics,
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


def _project(db: Session, name: str = "BingProj") -> tuple[models.User, models.Project]:
    user = models.User(email=f"{name.lower()}@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name=f"{name} ws", owner_id=user.id)
    db.add(ws)
    db.flush()
    project = models.Project(workspace_id=ws.id, name=name, language="en")
    db.add(project)
    db.commit()
    db.refresh(user)
    db.refresh(project)
    return user, project


def _bing_connection(
    db: Session, ws_id: int, *, expires_at: datetime | None = None
) -> models.OAuthConnection:
    conn = models.OAuthConnection(
        workspace_id=ws_id,
        provider=models.OAuthProvider.BING,
        access_token="bing-access-token",
        refresh_token="bing-refresh-token",
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(hours=1)),
        scope="webmaster.manage",
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _bing_source(db: Session, project: models.Project, conn: models.OAuthConnection):
    source = models.ProjectDataSource(
        project_id=project.id,
        provider=models.OAuthProvider.BING,
        source_type=models.ProjectDataSourceType.BING_WEBMASTER,
        binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
        source_id="https://owned.example.com",
        oauth_connection_id=conn.id,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _settings_env(monkeypatch, client_id: str, client_secret: str) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_ID", client_id)
    monkeypatch.setattr(settings, "BING_WEBMASTER_CLIENT_SECRET", client_secret)


def test_unconfigured_credentials_report_unavailable(monkeypatch) -> None:
    _settings_env(monkeypatch, "", "")
    assert bing_webmaster_oauth_configured() is False
    with pytest.raises(BingWebmasterConfigError) as excinfo:
        exchange_code_for_tokens("code", "https://app.example/cb")
    assert str(excinfo.value) == bing.REASON_NOT_CONFIGURED

    _settings_env(monkeypatch, "id-only", "")
    assert bing_webmaster_oauth_configured() is False


def test_configured_credentials_allow_exchange(monkeypatch) -> None:
    _settings_env(monkeypatch, "client-id", "client-secret")
    assert bing_webmaster_oauth_configured() is True

    captured = {}

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            }

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data, headers):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr(bing.httpx, "Client", FakeClient)
    payload = exchange_code_for_tokens("auth-code", "https://app.example/cb")
    assert payload["access_token"] == "access-1"
    assert captured["url"] == BING_TOKEN_URL
    assert captured["data"]["grant_type"] == "authorization_code"
    assert captured["data"]["code"] == "auth-code"
    assert captured["data"]["client_id"] == "client-id"
    assert captured["data"]["client_secret"] == "client-secret"


def test_dotnet_date_parses_to_utc_date() -> None:
    # /Date(ms+/-offset)/: the day is taken in the declared offset.
    assert parse_bing_dotnet_date("/Date(1316156400000-0700)/") == date(2011, 9, 16)
    assert parse_bing_dotnet_date("/Date(1316156400000+0200)/") == date(2011, 9, 16)
    # Instant 2026-10-01T00:30Z; at -0700 the local day is still Sep 30.
    ms = int(datetime(2026, 10, 1, 0, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert parse_bing_dotnet_date(f"/Date({ms}-0700)/") == date(2026, 9, 30)
    assert parse_bing_dotnet_date(f"/Date({ms}+0000)/") == date(2026, 10, 1)
    assert parse_bing_dotnet_date("not-a-date") is None
    assert parse_bing_dotnet_date(None) is None


def test_refresh_rotates_and_persists_token_set(db, monkeypatch) -> None:
    _settings_env(monkeypatch, "client-id", "client-secret")
    user = models.User(email="refresh@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name="ws", owner_id=user.id)
    db.add(ws)
    db.commit()
    conn = models.OAuthConnection(
        workspace_id=ws.id,
        provider=models.OAuthProvider.BING,
        access_token="stale-token",
        refresh_token="refresh-0",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    db.add(conn)
    db.commit()

    calls = []

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {
                "access_token": "fresh-token",
                "refresh_token": "refresh-1",
                "token_type": "Bearer",
                "expires_in": 7200,
            }

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data, headers):
            calls.append(data)
            return FakeResponse()

    monkeypatch.setattr(bing.httpx, "Client", FakeClient)
    refreshed = refresh_bing_oauth_connection(db, conn)
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "refresh-0"
    assert refreshed.access_token == "fresh-token"
    assert refreshed.refresh_token == "refresh-1"
    expires = refreshed.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    assert expires > datetime.now(timezone.utc) + timedelta(minutes=90)


def test_expired_access_token_triggers_refresh(db, monkeypatch) -> None:
    _settings_env(monkeypatch, "client-id", "client-secret")
    user, project = _project(db, "ExpProj")
    ws = db.query(models.Workspace).filter_by(id=project.workspace_id).first()
    conn = _bing_connection(
        db,
        ws.id,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    source = _bing_source(db, project, conn)

    class FakeResponse:
        status_code = 200
        content = b"{}"

        def json(self):
            return {"access_token": "refreshed-token", "expires_in": 3600}

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data, headers):
            return FakeResponse()

    monkeypatch.setattr(bing.httpx, "Client", FakeClient)
    assert bing_access_token(db, source) == "refreshed-token"


def test_valid_access_token_does_not_refresh(db, monkeypatch) -> None:
    user, project = _project(db, "OkProj")
    ws = db.query(models.Workspace).filter_by(id=project.workspace_id).first()
    conn = _bing_connection(db, ws.id)
    source = _bing_source(db, project, conn)
    monkeypatch.setattr(
        bing.httpx,
        "Client",
        lambda *a, **k: pytest.fail("no refresh call expected"),
    )
    assert bing_access_token(db, source) == "bing-access-token"


def test_position_unavailable_but_raw_retained(db) -> None:
    user, project = _project(db, "PosProj")
    rows = [
        {
            "Date": "/Date(1761346800000+0000)/",
            "Clicks": 15,
            "Impressions": 100,
            "AvgClickPosition": 18,
            "AvgImpressionPosition": 17,
            "Query": "qiko",
        }
    ]
    written = sync_bing_metrics(
        db,
        project.id,
        "https://owned.example.com",
        rows,
        dimension_type="query",
        dimension_getter=lambda r: r.get("Query") or "",
    )
    assert written == 1
    stored = (
        db.query(models.ProjectBingMetric)
        .filter_by(project_id=project.id, dimension_type="query")
        .one()
    )
    assert stored.clicks == 15.0
    assert stored.impressions == 100.0
    assert stored.avg_click_position_raw == 18
    assert stored.avg_impression_position_raw == 17

    payload = position_payload(stored)
    assert payload["status"] == "unavailable"
    assert payload["reason"] == POSITION_UNAVAILABLE_REASON
    assert payload["raw_provider_value"] == 18
    assert "position" not in payload or payload.get("position") is None


def test_ingestion_writes_three_dimensions(db) -> None:
    user, project = _project(db, "DimProj")
    site_url = "https://owned.example.com"
    site_rows = [{"Date": "/Date(1761346800000+0000)/", "Clicks": 3, "Impressions": 40}]
    query_rows = [
        {
            "Date": "/Date(1761346800000+0000)/",
            "Clicks": 2,
            "Impressions": 30,
            "Query": "brand",
        }
    ]
    page_rows = [
        {
            "Date": "/Date(1761346800000+0000)/",
            "Clicks": 1,
            "Impressions": 10,
            "Url": "https://owned.example.com/a",
        }
    ]
    assert sync_bing_metrics(db, project.id, site_url, site_rows, dimension_type="site") == 1
    assert (
        sync_bing_metrics(
            db,
            project.id,
            site_url,
            query_rows,
            dimension_type="query",
            dimension_getter=lambda r: r.get("Query") or "",
        )
        == 1
    )
    assert (
        sync_bing_metrics(
            db,
            project.id,
            site_url,
            page_rows,
            dimension_type="page",
            dimension_getter=lambda r: r.get("Url") or "",
        )
        == 1
    )
    counts = {
        row.dimension_type
        for row in db.query(models.ProjectBingMetric).filter_by(project_id=project.id).all()
    }
    assert counts == {"site", "query", "page"}


def test_bing_and_gsc_rows_stay_distinct(db) -> None:
    user, project = _project(db, "DistinctProj")
    site_url = "https://owned.example.com"
    sync_bing_metrics(
        db,
        project.id,
        site_url,
        [{"Date": "/Date(1761346800000+0000)/", "Clicks": 9, "Impressions": 90}],
        dimension_type="site",
    )
    from app.services.gsc_reporting_service import sync_search_analytics

    sync_search_analytics(
        db,
        project.id,
        site_url,
        [{"page": "/a", "date": "2026-10-24", "clicks": 5, "impressions": 50, "position": 4.0}],
    )
    bing_rows = db.query(models.ProjectBingMetric).filter_by(project_id=project.id).all()
    gsc_rows = db.query(models.ProjectGSCPageMetric).filter_by(project_id=project.id).all()
    assert len(bing_rows) == 1 and bing_rows[0].clicks == 9.0
    assert len(gsc_rows) == 1 and gsc_rows[0].clicks == 5.0


def _bing_api_mock(monkeypatch, *, owned: list[str], stats: list[dict]) -> None:
    def fake_get(self, path, params):
        if path == "GetUserSites":
            return {"d": [{"Url": url} for url in owned]}
        if path in ("GetRankAndTrafficStats", "GetQueryStats", "GetPageStats"):
            return {"d": stats}
        raise AssertionError(path)

    monkeypatch.setattr(BingWebmasterService, "_get", fake_get)


def test_site_the_user_does_not_own_is_refused(db, monkeypatch) -> None:
    user, project = _project(db, "OwnProj")
    ws = db.query(models.Workspace).filter_by(id=project.workspace_id).first()
    conn = _bing_connection(db, ws.id)
    _bing_source(db, project, conn)
    _bing_api_mock(
        monkeypatch,
        owned=["https://someone-else.example.com"],
        stats=[],
    )
    client = _client(db, user)
    try:
        resp = client.get(f"/api/v1/projects/{project.id}/monitoring/bing-webmaster/metrics")
    finally:
        client.close()
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "site_not_owned"
    assert payload["availability"] == "unavailable"


def test_metrics_endpoint_ingests_and_reports(db, monkeypatch) -> None:
    user, project = _project(db, "MetricsProj")
    ws = db.query(models.Workspace).filter_by(id=project.workspace_id).first()
    conn = _bing_connection(db, ws.id)
    _bing_source(db, project, conn)
    ms = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1000)
    _bing_api_mock(
        monkeypatch,
        owned=["https://owned.example.com"],
        stats=[
            {
                "Date": f"/Date({ms}+0000)/",
                "Clicks": 12,
                "Impressions": 120,
                "AvgClickPosition": 18,
                "AvgImpressionPosition": 17,
                "Query": "qiko",
                "Url": "https://owned.example.com/a",
            }
        ],
    )
    client = _client(db, user)
    try:
        resp = client.get(f"/api/v1/projects/{project.id}/monitoring/bing-webmaster/metrics")
    finally:
        client.close()
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "ok"
    assert payload["provider"] == "bing_webmaster"
    assert payload["period"] == {"start": "2026-10-20", "end": "2026-10-20"}
    site_rows = payload["site"]
    assert site_rows[0]["clicks"] == 12.0
    assert site_rows[0]["impressions"] == 120.0
    assert site_rows[0]["position"]["status"] == "unavailable"
    assert site_rows[0]["position"]["reason"] == POSITION_UNAVAILABLE_REASON
    assert site_rows[0]["position"]["raw_provider_value"] == 18
    stored = db.query(models.ProjectBingMetric).filter_by(project_id=project.id).all()
    assert {row.dimension_type for row in stored} == {"site", "query", "page"}


def test_unconfigured_deployment_blocks_workspace_connect(monkeypatch, db) -> None:
    _settings_env(monkeypatch, "", "")
    user, project = _project(db, "CfgProj")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from auth.security import get_current_user_from_token as get_current_user
    from database import get_db
    from routers.workspace_router import router as workspace_router

    app = FastAPI()
    app.include_router(workspace_router, prefix="/api/v1")

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    client = TestClient(app, follow_redirects=False)
    try:
        resp = client.get("/api/v1/workspaces/current/oauth-connections/bing/start")
    finally:
        client.close()
    assert resp.status_code == 503
    assert "BING_WEBMASTER_CLIENT_ID" in resp.json()["detail"]


def test_api_error_maps_to_reason(monkeypatch) -> None:
    class FakeResponse:
        status_code = 429
        content = b"{}"

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params, headers):
            return FakeResponse()

    monkeypatch.setattr(bing.httpx, "Client", FakeClient)
    service = BingWebmasterService("token")
    with pytest.raises(BingWebmasterApiError) as excinfo:
        service.get_user_sites()
    assert str(excinfo.value) == "rate_limited"


def test_normalize_stats_row_shape() -> None:
    ms = int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp() * 1000)
    row = normalize_stats_row(
        {
            "Date": f"/Date({ms}+0000)/",
            "Clicks": 7,
            "Impressions": 70,
            "AvgClickPosition": 18,
        }
    )
    assert row is not None
    assert row["date"] == date(2026, 10, 25)
    assert row["clicks"] == 7.0
    assert row["avg_click_position_raw"] == 18
    assert "position" not in row
    assert normalize_stats_row({"Clicks": 1}) is None


def test_bing_granted_scope_manage_satisfies_webmaster_manage() -> None:
    """Bing's token endpoint returns the granted scope as ``manage``, not the
    ``webmaster.manage`` value we request, so the literal comparison reported
    insufficient_scope on a correctly authorized connection."""
    from routers.workspace_router import _resolve_scope_requirements

    required, granted, missing = _resolve_scope_requirements(
        models.ProjectDataSourceType.BING_WEBMASTER, "manage"
    )
    assert required == ["webmaster.manage"]
    assert granted == ["manage"]
    assert missing == []

    for value in ("webmaster.manage", "webmaster", "manage"):
        _, _, unmet = _resolve_scope_requirements(
            models.ProjectDataSourceType.BING_WEBMASTER, value
        )
        assert unmet == [], value

    _, _, unrelated = _resolve_scope_requirements(
        models.ProjectDataSourceType.BING_WEBMASTER, "openid profile email"
    )
    assert unrelated == ["webmaster.manage"]


def test_bing_getusersites_parses_the_real_response_shape(monkeypatch) -> None:
    """Bing returns ``{"d": [...]}`` with ``d`` as a list. The parser only
    handled ``d`` as a dict, so a successful call yielded zero sites."""
    import httpx

    from routers import workspace_router

    payload = {
        "d": [
            {
                "__type": "Site:#Microsoft.Bing.Webmaster.Api",
                "AuthenticationCode": "REDACTED",
                "DnsVerificationCode": "redacted.example.com",
                "IsVerified": True,
                "Url": "https://preprod.example.com/",
            },
            {
                "__type": "Site:#Microsoft.Bing.Webmaster.Api",
                "AuthenticationCode": "REDACTED",
                "DnsVerificationCode": "redacted2.example.com",
                "IsVerified": True,
                "Url": "https://example.com/",
            },
        ]
    }

    class _Client:
        def __init__(self, *a, **k): ...
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return httpx.Response(200, json=payload)

    monkeypatch.setattr(workspace_router.httpx, "Client", _Client)

    items = workspace_router._list_bing_webmaster_sites("token")
    assert [i.id for i in items] == [
        "https://preprod.example.com/",
        "https://example.com/",
    ]

    # The verification codes are credentials for proving site ownership and
    # must never reach the catalog response.
    blob = " ".join(f"{i.id} {i.label} {i.description or ''}" for i in items)
    assert "REDACTED" not in blob
    assert "redacted.example.com" not in blob
