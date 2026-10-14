"""Reconnecting a workspace OAuth connection must repoint its data sources.

Deleting the old OAuthConnection row and reconnecting creates a new row id.
Workspace-bound ProjectDataSource rows keep a NULL or dangling
``oauth_connection_id`` unless they are repointed in the same transaction,
which makes ``ga4_access_token`` raise ``no_oauth_connection`` on a binding
that looks intact.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from routers.workspace_router import (
    BINDING_ACCESS_DENIED,
    BINDING_ACCESS_OK,
    BINDING_ACCESS_UNKNOWN,
    _probe_google_binding_access,
    _upsert_workspace_oauth_connection,
)
from app.services.geo.ga4_oauth_service import ga4_access_token


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory()


def _seed(db: Session) -> tuple[models.Workspace, models.Project]:
    user = models.User(email="owner@example.com", hashed_password="x", role="user", credits=5)
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Agency", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Client",
        domain_url="https://client.example",
        target_country="ro",
        language="ro",
    )
    db.add(project)
    db.commit()
    db.refresh(workspace)
    db.refresh(project)
    return workspace, project


def _connection(db: Session, workspace_id: int, token: str) -> models.OAuthConnection:
    conn = models.OAuthConnection(
        workspace_id=workspace_id,
        provider=models.OAuthProvider.GOOGLE,
        access_token=token,
        refresh_token="refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _ga4_source(
    db: Session,
    project_id: int,
    *,
    oauth_connection_id,
    project_oauth_connection_id=None,
    binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
    source_id="properties/540236839",
    source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
    metadata_json=None,
    last_status=None,
    last_error=None,
) -> models.ProjectDataSource:
    row = models.ProjectDataSource(
        project_id=project_id,
        provider=models.OAuthProvider.GOOGLE,
        source_type=source_type,
        binding_mode=binding_mode,
        source_id=source_id,
        source_label="Client GA4" if source_id else None,
        is_active=True,
        oauth_connection_id=oauth_connection_id,
        project_oauth_connection_id=project_oauth_connection_id,
        metadata_json={} if metadata_json is None else metadata_json,
        last_status=last_status,
        last_error=last_error,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_reconnect_repoints_workspace_bound_sources_to_new_connection() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "old-token")
    source = _ga4_source(db, project.id, oauth_connection_id=old.id)

    # Occupy the next row id so the replacement connection cannot reuse the
    # old id (SQLite would otherwise hand the same rowid back and mask the
    # orphaning).
    filler = models.OAuthConnection(
        workspace_id=workspace.id,
        provider=models.OAuthProvider.BING,
        access_token="bing-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(filler)
    db.commit()

    # The connection is replaced: the old row is deleted and the callback
    # creates a new one. Production (Postgres) fires the FK's SET NULL, so
    # mirror that state for a second source while the first keeps the
    # dangling id SQLite leaves behind.
    db.delete(old)
    db.commit()
    db.refresh(source)

    second_project = models.Project(
        workspace_id=workspace.id,
        name="Second client",
        domain_url="https://second.example",
        target_country="ro",
        language="ro",
    )
    db.add(second_project)
    db.commit()
    db.refresh(second_project)
    nulled = _ga4_source(db, second_project.id, oauth_connection_id=None)

    new = _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="new-token",
        refresh_token="new-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert new.id != old.id

    db.refresh(source)
    db.refresh(nulled)
    assert source.oauth_connection_id == new.id
    assert nulled.oauth_connection_id == new.id
    # The token still resolves: the binding survived the replacement.
    assert ga4_access_token(db, source) == "new-token"
    assert ga4_access_token(db, nulled) == "new-token"


def test_reconnect_does_not_touch_client_magic_link_bindings() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    project_conn = models.ProjectOAuthConnection(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="client-token",
        refresh_token="client-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(project_conn)
    db.commit()
    db.refresh(project_conn)
    source = _ga4_source(
        db,
        project.id,
        oauth_connection_id=None,
        project_oauth_connection_id=project_conn.id,
        binding_mode=models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK,
    )

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="new-token",
        refresh_token="new-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    db.refresh(source)
    assert source.oauth_connection_id is None
    assert source.project_oauth_connection_id == project_conn.id
    assert ga4_access_token(db, source) == "client-token"


def test_reconnect_leaves_other_workspace_sources_alone() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    other_owner = models.User(
        email="other@example.com", hashed_password="x", role="user", credits=5
    )
    db.add(other_owner)
    db.flush()
    other_workspace = models.Workspace(name="Other", owner_id=other_owner.id)
    db.add(other_workspace)
    db.flush()
    other_project = models.Project(
        workspace_id=other_workspace.id,
        name="Other client",
        domain_url="https://other.example",
        target_country="ro",
        language="ro",
    )
    db.add(other_project)
    db.commit()
    db.refresh(other_project)

    source = _ga4_source(db, other_project.id, oauth_connection_id=None)

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="new-token",
        refresh_token="new-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    db.refresh(source)
    assert source.oauth_connection_id is None


# ---------------------------------------------------------------------------
# SIGV2-1202: a new grant may not silently inherit the previous account's
# bindings. Before a saved property is reused it is validated with the new
# token. The decisive rule: only a CONFIRMED denial clears a binding. An
# uncertain signal (429, outage, network failure, a token problem, an
# unparseable id) keeps the binding and defers - destroying a working binding
# on an ambiguous signal is worse than showing one stale permission error.
# ---------------------------------------------------------------------------


def _probe(verdicts: dict[str, str], calls: list[tuple] | None = None):
    def _call(*, access_token: str, source_type, source_id: str) -> str:
        if calls is not None:
            calls.append((access_token, source_type, source_id))
        return verdicts[source_id]

    return _call


def test_switching_account_clears_a_property_the_new_account_cannot_read() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(
        db,
        project.id,
        oauth_connection_id=old.id,
        metadata_json={"ga4_time_zone": "Europe/Bucharest"},
        last_status="auth_error",
        last_error="ga4_access_denied_401",
    )

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({"properties/540236839": BINDING_ACCESS_DENIED}),
    )

    db.refresh(source)
    # A fresh selection is required: no property is claimed, and the row is
    # not left asserting live data it cannot read.
    assert source.source_id is None
    assert source.source_label is None
    assert source.is_active is False
    assert source.last_status == "needs_property_selection"
    assert "ga4_time_zone" not in (source.metadata_json or {})


def test_switching_account_keeps_a_property_the_new_account_can_read() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(
        db,
        project.id,
        oauth_connection_id=old.id,
        last_status="auth_error",
        last_error="ga4_access_denied_401",
    )
    db.delete(old)
    db.commit()

    new = _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({"properties/540236839": BINDING_ACCESS_OK}),
    )

    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.is_active is True
    assert source.oauth_connection_id == new.id
    # The stale authorization error is cleared, not left on a working binding.
    assert source.last_status is None
    assert source.last_error is None


def test_uncertain_validation_never_erases_a_binding() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(db, project.id, oauth_connection_id=old.id)
    db.delete(old)
    db.commit()

    new = _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="renewed-token",
        refresh_token="renewed-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({"properties/540236839": BINDING_ACCESS_UNKNOWN}),
    )

    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.is_active is True
    assert source.oauth_connection_id == new.id


def test_a_probe_that_raises_is_treated_as_uncertain() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(db, project.id, oauth_connection_id=old.id)

    def _explode(**_kwargs):
        raise RuntimeError("provider outage")

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="renewed-token",
        refresh_token="renewed-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_explode,
    )

    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.is_active is True


def test_no_probe_means_no_binding_is_erased() -> None:
    # The manual token-paste path cannot verify anything, so it must not be
    # allowed to clear a binding. Omitting the probe keeps the pre-SIGV2-1202
    # behaviour: repair the FK, change nothing else.
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(db, project.id, oauth_connection_id=old.id)
    db.delete(old)
    db.commit()

    new = _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="pasted-token",
        refresh_token="pasted-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )

    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.oauth_connection_id == new.id


def test_a_cleared_binding_stays_unbound() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(db, project.id, oauth_connection_id=old.id, source_id=None)
    calls: list[tuple] = []

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({}, calls),
    )

    db.refresh(source)
    assert source.source_id is None
    # Nothing was probed: there is no saved property to validate, and none is
    # invented for the new account.
    assert calls == []
    assert old.id


def test_search_console_bindings_are_validated_separately() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    old = _connection(db, workspace.id, "account-a-token")
    ga4 = _ga4_source(db, project.id, oauth_connection_id=old.id)
    gsc = _ga4_source(
        db,
        project.id,
        oauth_connection_id=old.id,
        source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
        source_id="https://client.example/",
    )
    calls: list[tuple] = []

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe(
            {
                "properties/540236839": BINDING_ACCESS_DENIED,
                "https://client.example/": BINDING_ACCESS_OK,
            },
            calls,
        ),
    )

    db.refresh(ga4)
    db.refresh(gsc)
    assert ga4.source_id is None
    assert gsc.source_id == "https://client.example/"
    assert {call[1] for call in calls} == {
        models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
        models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
    }


def test_validation_does_not_reach_other_tenants() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    other_owner = models.User(
        email="stranger@example.com", hashed_password="x", role="user", credits=5
    )
    db.add(other_owner)
    db.flush()
    other_workspace = models.Workspace(name="Stranger", owner_id=other_owner.id)
    db.add(other_workspace)
    db.flush()
    other_project = models.Project(
        workspace_id=other_workspace.id,
        name="Stranger client",
        domain_url="https://stranger.example",
        target_country="ro",
        language="ro",
    )
    db.add(other_project)
    db.commit()
    db.refresh(other_project)
    foreign = _ga4_source(db, other_project.id, oauth_connection_id=None)
    calls: list[tuple] = []

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({"properties/540236839": BINDING_ACCESS_DENIED}, calls),
    )

    db.refresh(foreign)
    assert foreign.source_id == "properties/540236839"
    assert foreign.is_active is True
    assert calls == []


def test_client_magic_link_bindings_are_never_validated_or_cleared() -> None:
    db = _build_db()
    workspace, project = _seed(db)
    project_conn = models.ProjectOAuthConnection(
        project_id=project.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="client-token",
        refresh_token="client-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(project_conn)
    db.commit()
    db.refresh(project_conn)
    source = _ga4_source(
        db,
        project.id,
        oauth_connection_id=None,
        project_oauth_connection_id=project_conn.id,
        binding_mode=models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK,
    )
    calls: list[tuple] = []

    _upsert_workspace_oauth_connection(
        db,
        workspace_id=workspace.id,
        provider=models.OAuthProvider.GOOGLE,
        access_token="account-b-token",
        refresh_token="account-b-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        access_probe=_probe({"properties/540236839": BINDING_ACCESS_DENIED}, calls),
    )

    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.is_active is True
    assert source.project_oauth_connection_id == project_conn.id
    assert calls == []


# ---------------------------------------------------------------------------
# The probe itself: status -> verdict. Only 403/404 are a confirmed denial.
# ---------------------------------------------------------------------------


def _probe_with_status(monkeypatch, status: int):
    import httpx

    seen: dict[str, str] = {}

    class _Resp:
        status_code = status
        text = ""

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, **kwargs):
            seen["url"] = url
            return _Resp()

    monkeypatch.setattr(httpx, "Client", _Client)
    return seen


def test_probe_maps_200_to_accessible(monkeypatch) -> None:
    seen = _probe_with_status(monkeypatch, 200)
    assert (
        _probe_google_binding_access(
            access_token="tok",
            source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            source_id="properties/540236839",
        )
        == BINDING_ACCESS_OK
    )
    assert seen["url"].endswith("/properties/540236839")


def test_probe_maps_403_and_404_to_denied(monkeypatch) -> None:
    for status in (403, 404):
        _probe_with_status(monkeypatch, status)
        assert (
            _probe_google_binding_access(
                access_token="tok",
                source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
                source_id="properties/540236839",
            )
            == BINDING_ACCESS_DENIED
        )


def test_probe_maps_rate_limits_and_outages_to_unknown(monkeypatch) -> None:
    for status in (401, 429, 500, 503):
        _probe_with_status(monkeypatch, status)
        assert (
            _probe_google_binding_access(
                access_token="tok",
                source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
                source_id="properties/540236839",
            )
            == BINDING_ACCESS_UNKNOWN
        )


def test_probe_maps_an_unusable_property_id_to_unknown(monkeypatch) -> None:
    # A value that cannot be turned into a GA4 property path proves nothing
    # about access, so it must not be read as a denial.
    _probe_with_status(monkeypatch, 200)
    assert (
        _probe_google_binding_access(
            access_token="tok",
            source_type=models.ProjectDataSourceType.GOOGLE_ANALYTICS_4,
            source_id="not-a-property",
        )
        == BINDING_ACCESS_UNKNOWN
    )


def test_probe_checks_the_search_console_site_itself(monkeypatch) -> None:
    seen = _probe_with_status(monkeypatch, 200)
    assert (
        _probe_google_binding_access(
            access_token="tok",
            source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
            source_id="https://client.example/",
        )
        == BINDING_ACCESS_OK
    )
    assert "webmasters/v3/sites/" in seen["url"]
    assert "https%3A%2F%2Fclient.example%2F" in seen["url"]


# ---------------------------------------------------------------------------
# The start flow must let the customer pick which Google account to use.
# Without select_account Google silently reuses the account already signed in
# to the browser, so "switch account" is unreachable from the product.
# ---------------------------------------------------------------------------


def test_google_start_flow_asks_which_account_and_keeps_the_workspace_id() -> None:
    import asyncio

    import routers.workspace_router as wr

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
                user=object(),
                db=object(),
            )
        )
    finally:
        wr._start_workspace_oauth_flow = original

    authorize_kwargs = captured["authorize_kwargs"]
    assert "select_account" in str(authorize_kwargs["prompt"])
    # consent must stay: dropping it loses the refresh token, and a connection
    # without a refresh token dies at the first token expiry.
    assert "consent" in str(authorize_kwargs["prompt"])
    assert authorize_kwargs["access_type"] == "offline"
    # SIGV2-1207's explicit workspace id still rides through the redirect.
    assert captured["workspace_id"] == 77


def test_cancelled_oauth_leaves_every_binding_intact() -> None:
    # The customer bailed out at Google's consent screen. Nothing was proven
    # about the existing grant or the saved property, so nothing may change.
    import asyncio

    import routers.workspace_router as wr

    db = _build_db()
    workspace, project = _seed(db)
    owner = db.query(models.User).filter(models.User.email == "owner@example.com").first()
    conn = _connection(db, workspace.id, "account-a-token")
    source = _ga4_source(db, project.id, oauth_connection_id=conn.id)

    class _Request:
        def __init__(self, session, query_params):
            self.session = session
            self.query_params = query_params

    request = _Request(
        {
            wr._workspace_oauth_session_key("google"): {
                "workspace_id": workspace.id,
                "user_id": owner.id,
            }
        },
        {"error": "access_denied"},
    )

    response = asyncio.run(
        wr._finish_workspace_oauth_flow(request=request, db=db, provider="google")
    )

    assert "status=error" in response.headers["location"]
    db.refresh(source)
    assert source.source_id == "properties/540236839"
    assert source.is_active is True
    assert source.oauth_connection_id == conn.id
    assert db.query(models.OAuthConnection).count() == 1
