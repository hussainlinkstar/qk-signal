"""SIGV2-1202: disconnecting a workspace grant must invalidate what depended on it.

Deleting the ``OAuthConnection`` row only nulls ``oauth_connection_id`` (the FK
is ON DELETE SET NULL). The property id, the label and ``is_active`` survive,
so the binding keeps claiming a live GA4 property and every read answers
"revoked" - the customer is told their access was revoked immediately after
they disconnected it themselves, and reconnecting cannot clear it.

The cleanup is deliberately narrow: this workspace, this provider,
workspace-bound sources only. Client magic-link bindings, project-level
grants, other workspaces, other providers and all historical data stay as
they are.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import os
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
from routers.workspace_router import delete_workspace_oauth_connection  # noqa: E402


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    user = models.User(email="owner@example.com", hashed_password="x", role="user", credits=5)
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
    return user, workspace, project


def _connection(
    db: Session,
    workspace_id: int,
    provider: models.OAuthProvider = models.OAuthProvider.GOOGLE,
) -> models.OAuthConnection:
    conn = models.OAuthConnection(
        workspace_id=workspace_id,
        provider=provider,
        access_token="account-a-token",
        refresh_token="account-a-refresh",
        token_type="Bearer",
        scope="analytics.readonly",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _source(
    db: Session,
    project_id: int,
    *,
    source_type: models.ProjectDataSourceType = (models.ProjectDataSourceType.GOOGLE_ANALYTICS_4),
    provider: models.OAuthProvider = models.OAuthProvider.GOOGLE,
    oauth_connection_id: int | None = None,
    project_oauth_connection_id: int | None = None,
    binding_mode: models.ProjectDataSourceBindingMode = (
        models.ProjectDataSourceBindingMode.WORKSPACE
    ),
    source_id: str | None = "properties/540236839",
    metadata_json: dict | None = None,
) -> models.ProjectDataSource:
    row = models.ProjectDataSource(
        project_id=project_id,
        provider=provider,
        source_type=source_type,
        binding_mode=binding_mode,
        source_id=source_id,
        source_label="Account A property",
        is_active=True,
        oauth_connection_id=oauth_connection_id,
        project_oauth_connection_id=project_oauth_connection_id,
        metadata_json=metadata_json if metadata_json is not None else {"ga4_time_zone": "UTC"},
        last_status="auth_error",
        last_error="ga4_access_denied_401",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_disconnect_clears_dependent_workspace_bindings() -> None:
    db = _build_db()
    user, workspace, project = _seed(db)
    conn = _connection(db, workspace.id)
    ga4 = _source(db, project.id, oauth_connection_id=conn.id)
    gsc = _source(
        db,
        project.id,
        source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
        oauth_connection_id=conn.id,
        source_id="https://client.example/",
    )

    delete_workspace_oauth_connection(provider="google", user=user, db=db)

    db.refresh(ga4)
    db.refresh(gsc)
    for row in (ga4, gsc):
        # No live property id, no label, no connection, switched off, and the
        # state says disconnected rather than revoked.
        assert row.source_id is None
        assert row.source_label is None
        assert row.oauth_connection_id is None
        assert row.is_active is False
        assert row.last_status == "disconnected"
        assert row.last_error is None
        assert "ga4_time_zone" not in (row.metadata_json or {})
    assert (
        db.query(models.OAuthConnection)
        .filter(models.OAuthConnection.workspace_id == workspace.id)
        .count()
        == 0
    )


def test_disconnect_preserves_history() -> None:
    db = _build_db()
    user, workspace, project = _seed(db)
    conn = _connection(db, workspace.id)
    _source(db, project.id, oauth_connection_id=conn.id)
    db.add(
        models.LLMTrafficSnapshot(
            project_id=project.id,
            source="chatgpt.com",
            snapshot_date=date(2026, 9, 1),
            sessions=12,
        )
    )
    db.commit()

    delete_workspace_oauth_connection(provider="google", user=user, db=db)

    assert (
        db.query(models.LLMTrafficSnapshot)
        .filter(models.LLMTrafficSnapshot.project_id == project.id)
        .count()
        == 1
    )
    assert db.query(models.Project).filter(models.Project.id == project.id).count() == 1


def test_disconnect_leaves_client_magic_link_bindings_alone() -> None:
    db = _build_db()
    user, workspace, project = _seed(db)
    conn = _connection(db, workspace.id)
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
    client_bound = _source(
        db,
        project.id,
        project_oauth_connection_id=project_conn.id,
        binding_mode=models.ProjectDataSourceBindingMode.CLIENT_MAGIC_LINK,
    )
    assert conn.id

    delete_workspace_oauth_connection(provider="google", user=user, db=db)

    db.refresh(client_bound)
    assert client_bound.source_id == "properties/540236839"
    assert client_bound.is_active is True
    assert client_bound.project_oauth_connection_id == project_conn.id


def test_disconnect_leaves_other_providers_and_workspaces_alone() -> None:
    db = _build_db()
    user, workspace, project = _seed(db)
    google = _connection(db, workspace.id)
    bing = _connection(db, workspace.id, provider=models.OAuthProvider.BING)
    bing_source = _source(
        db,
        project.id,
        source_type=models.ProjectDataSourceType.BING_WEBMASTER,
        provider=models.OAuthProvider.BING,
        oauth_connection_id=bing.id,
        source_id="https://client.example/",
        metadata_json={},
    )

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
    other_conn = _connection(db, other_workspace.id)
    other_source = _source(db, other_project.id, oauth_connection_id=other_conn.id)
    assert google.id

    delete_workspace_oauth_connection(provider="google", user=user, db=db)

    db.refresh(bing_source)
    db.refresh(other_source)
    assert bing_source.source_id == "https://client.example/"
    assert bing_source.is_active is True
    assert bing_source.oauth_connection_id == bing.id
    assert other_source.source_id == "properties/540236839"
    assert other_source.is_active is True


def test_disconnect_without_a_connection_still_404s() -> None:
    db = _build_db()
    user, _workspace, _project = _seed(db)
    with pytest.raises(HTTPException) as excinfo:
        delete_workspace_oauth_connection(provider="google", user=user, db=db)
    assert excinfo.value.status_code == 404
