"""SIGV2-1086: Bing token refresh in the project data-source catalog.

The catalog fetch used to hand every auth failure to the Google refresher and
could not even recognize Bing's ``InvalidToken`` payload, so an expired Bing
token silently produced an empty site list with ``connected: true``. These
tests pin provider-routed refresh, the classifier's Bing vocabulary, proactive
refresh on a stored expiry, and the reconnect-required surface on real
failure. All outbound calls are mocked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from routers.workspace_router import (
    OAuthConnectionUpsertRequest,
    ProjectCreateRequest,
    _is_authentication_credential_error,
    _refresh_workspace_oauth_connection,
    create_project_in_current_workspace,
    get_project_data_source_catalog,
    upsert_workspace_oauth_connection,
)


def _build_db() -> tuple[Session, sessionmaker, Engine, models.User]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()
    user = models.User(email="bing-refresh@example.com", hashed_password="x")
    db.add(user)
    db.commit()
    db.refresh(user)
    return db, testing_session_local, engine, user


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _project_and_connection(
    db: Session,
    user: models.User,
    *,
    provider: str,
    scope: str,
    expires_at: datetime,
    name: str,
) -> int:
    created = create_project_in_current_workspace(
        payload=ProjectCreateRequest(name=name, domain_url=f"{name.lower()}.example"),
        user=user,
        db=db,
    )
    upsert_workspace_oauth_connection(
        provider=provider,
        payload=OAuthConnectionUpsertRequest(
            access_token=f"{provider}-access-token",
            refresh_token=f"{provider}-refresh-token",
            scope=scope,
            token_type="Bearer",
            expires_at=expires_at,
        ),
        user=user,
        db=db,
    )
    return int(created["id"])


class _FetchStub:
    """Mockable _fetch_source_catalog_items replacement recording tokens."""

    def __init__(self, *failures: Exception):
        self.failures = list(failures)
        self.calls: list[str] = []

    def __call__(self, source_type, access_token):
        from routers.workspace_router import ProjectDataSourceCatalogItemResponse

        self.calls.append(access_token)
        if self.failures:
            raise self.failures.pop(0)
        return [
            ProjectDataSourceCatalogItemResponse(
                id="https://site.example/",
                label="https://site.example/",
            )
        ]


def _catalog_kwargs():
    import routers.workspace_router as workspace_router_module

    return workspace_router_module


def test_expired_bing_token_triggers_bing_refresh_before_fetch() -> None:
    db, _sf, engine, user = _build_db()
    try:
        project_id = _project_and_connection(
            db,
            user,
            provider="bing",
            scope="webmaster.manage",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            name="BingExpired",
        )
        module = _catalog_kwargs()
        fetch = _FetchStub()
        original_fetch = module._fetch_source_catalog_items

        import app.services.bing_webmaster_service as bing_service

        refreshed = []

        def _fake_bing_refresh(db_session, connection):
            provider = connection.provider
            provider_value = (
                provider.value if isinstance(provider, models.OAuthProvider) else provider
            )
            assert provider_value == "bing"
            connection.access_token = "bing-fresh-token"
            refreshed.append(True)
            return connection

        original_bing = bing_service.refresh_bing_oauth_connection
        bing_service.refresh_bing_oauth_connection = _fake_bing_refresh
        module._fetch_source_catalog_items = fetch
        try:
            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="bing_webmaster",
                user=user,
                db=db,
            )
        finally:
            module._fetch_source_catalog_items = original_fetch
            bing_service.refresh_bing_oauth_connection = original_bing

        assert refreshed == [True]
        # The fetch only ever saw the refreshed token, never the stale one.
        assert fetch.calls == ["bing-fresh-token"]
        assert catalog.error is None
        assert len(catalog.items) == 1
    finally:
        _cleanup(db, engine)


def test_bing_invalidtoken_payload_is_classified_as_auth_error() -> None:
    bing_error = RuntimeError(
        'Bing catalog fetch failed: {"ErrorCode":18,"Message":"ERROR!!! InvalidToken"}'
    )
    assert _is_authentication_credential_error(bing_error) is True
    # And an unrelated failure stays unrelated.
    assert _is_authentication_credential_error(RuntimeError("catalog provider timeout")) is False


def test_bing_invalidtoken_retries_through_bing_refresher() -> None:
    db, _sf, engine, user = _build_db()
    try:
        project_id = _project_and_connection(
            db,
            user,
            provider="bing",
            scope="webmaster.manage",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            name="BingRetry",
        )
        module = _catalog_kwargs()
        fetch = _FetchStub(
            RuntimeError(
                'Bing catalog fetch failed: {"ErrorCode":18,"Message":"ERROR!!! InvalidToken"}'
            )
        )
        original_fetch = module._fetch_source_catalog_items

        import app.services.bing_webmaster_service as bing_service
        import app.services.google_oauth_service as google_service

        def _fake_bing_refresh(db_session, connection):
            connection.access_token = "bing-fresh-token"
            return connection

        def _forbidden_google_refresh(db_session, connection):
            raise AssertionError("google refresher must not see a bing connection")

        original_bing = bing_service.refresh_bing_oauth_connection
        original_google = google_service.refresh_google_oauth_connection
        bing_service.refresh_bing_oauth_connection = _fake_bing_refresh
        google_service.refresh_google_oauth_connection = _forbidden_google_refresh
        module._fetch_source_catalog_items = fetch
        try:
            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="bing_webmaster",
                user=user,
                db=db,
            )
        finally:
            module._fetch_source_catalog_items = original_fetch
            bing_service.refresh_bing_oauth_connection = original_bing
            google_service.refresh_google_oauth_connection = original_google

        assert fetch.calls == ["bing-access-token", "bing-fresh-token"]
        assert catalog.error is None
        assert catalog.workspace_provider_connected is True
    finally:
        _cleanup(db, engine)


def test_google_connection_still_uses_google_refresher() -> None:
    db, _sf, engine, user = _build_db()
    try:
        project_id = _project_and_connection(
            db,
            user,
            provider="google",
            scope="https://www.googleapis.com/auth/webmasters.readonly",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            name="GoogleRetry",
        )
        module = _catalog_kwargs()
        fetch = _FetchStub(RuntimeError("Request had invalid authentication credentials"))
        original_fetch = module._fetch_source_catalog_items

        import app.services.bing_webmaster_service as bing_service
        import app.services.google_oauth_service as google_service

        def _fake_google_refresh(db_session, connection):
            connection.access_token = "google-fresh-token"
            return connection

        def _forbidden_bing_refresh(db_session, connection):
            raise AssertionError("bing refresher must not see a google connection")

        original_google = google_service.refresh_google_oauth_connection
        original_bing = bing_service.refresh_bing_oauth_connection
        google_service.refresh_google_oauth_connection = _fake_google_refresh
        bing_service.refresh_bing_oauth_connection = _forbidden_bing_refresh
        module._fetch_source_catalog_items = fetch
        try:
            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="google_search_console",
                user=user,
                db=db,
            )
        finally:
            module._fetch_source_catalog_items = original_fetch
            google_service.refresh_google_oauth_connection = original_google
            bing_service.refresh_bing_oauth_connection = original_bing

        assert fetch.calls == ["google-access-token", "google-fresh-token"]
        assert catalog.error is None
    finally:
        _cleanup(db, engine)


def test_dispatcher_refuses_an_unknown_provider() -> None:
    connection = models.OAuthConnection(
        workspace_id=1,
        provider="jira",
        access_token="x",
        refresh_token="y",
    )
    with pytest.raises(RuntimeError, match="oauth_refresh_unsupported_provider:jira"):
        _refresh_workspace_oauth_connection(None, connection)


def test_failed_bing_refresh_surfaces_reconnect_required() -> None:
    db, _sf, engine, user = _build_db()
    try:
        project_id = _project_and_connection(
            db,
            user,
            provider="bing",
            scope="webmaster.manage",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            name="BingFail",
        )
        module = _catalog_kwargs()
        fetch = _FetchStub()
        original_fetch = module._fetch_source_catalog_items

        import app.services.bing_webmaster_service as bing_service

        def _failing_bing_refresh(db_session, connection):
            raise RuntimeError("refresh_failed_http_400")

        original_bing = bing_service.refresh_bing_oauth_connection
        bing_service.refresh_bing_oauth_connection = _failing_bing_refresh
        module._fetch_source_catalog_items = fetch
        try:
            catalog = get_project_data_source_catalog(
                project_id=project_id,
                source_type="bing_webmaster",
                user=user,
                db=db,
            )
        finally:
            module._fetch_source_catalog_items = original_fetch
            bing_service.refresh_bing_oauth_connection = original_bing

        # The provider call was never attempted; the response is an explicit
        # reconnect-required state, not an empty list that looks connected.
        assert fetch.calls == []
        assert catalog.workspace_provider_connected is False
        assert catalog.items == []
        assert catalog.error == "oauth_reconnect_required"
    finally:
        _cleanup(db, engine)


def test_auth_failure_without_refresh_token_surfaces_reconnect() -> None:
    db, _sf, engine, user = _build_db()
    try:
        created = create_project_in_current_workspace(
            payload=ProjectCreateRequest(name="BingNoRT", domain_url="bingnort.example"),
            user=user,
            db=db,
        )
        upsert_workspace_oauth_connection(
            provider="bing",
            payload=OAuthConnectionUpsertRequest(
                access_token="bing-access-token",
                refresh_token=None,
                scope="webmaster.manage",
                token_type="Bearer",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            ),
            user=user,
            db=db,
        )
        module = _catalog_kwargs()
        fetch = _FetchStub(RuntimeError('{"ErrorCode":18,"Message":"ERROR!!! InvalidToken"}'))
        original_fetch = module._fetch_source_catalog_items
        module._fetch_source_catalog_items = fetch
        try:
            catalog = get_project_data_source_catalog(
                project_id=int(created["id"]),
                source_type="bing_webmaster",
                user=user,
                db=db,
            )
        finally:
            module._fetch_source_catalog_items = original_fetch

        assert catalog.workspace_provider_connected is False
        assert catalog.error == "oauth_reconnect_required"
    finally:
        _cleanup(db, engine)
