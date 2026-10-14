from __future__ import annotations

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
from services.audit_data_sources import resolve_project_audit_data_sources


def _build_db() -> tuple[Session, sessionmaker]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), session_factory


def _seed_workspace_project(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    user = models.User(email="resolver@example.com", hashed_password="x", role="user", credits=5)
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
    db.refresh(user)
    db.refresh(workspace)
    db.refresh(project)
    return user, workspace, project


def _cleanup(db: Session) -> None:
    engine = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_resolve_project_audit_data_sources_defaults_to_ai_estimate_only() -> None:
    db, _session_factory = _build_db()
    try:
        _user, _workspace, project = _seed_workspace_project(db)
        context, warnings = resolve_project_audit_data_sources(db, project_id=project.id)

        assert context["project_id"] == project.id
        assert context["workspace_id"] == project.workspace_id
        assert context["mode"] == "ai_estimate_only"
        assert context["has_external_data"] is False
        assert len(context["sources"]) == 3
        assert any("AI Estimates Only" in warning for warning in warnings)
    finally:
        _cleanup(db)


def test_resolve_project_audit_data_sources_prefers_client_magic_link_over_workspace() -> None:
    db, _session_factory = _build_db()
    try:
        _user, workspace, project = _seed_workspace_project(db)
        db.add(
            models.OAuthConnection(
                workspace_id=workspace.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="workspace-google-token",
            )
        )
        db.add(
            models.ProjectOAuthConnection(
                project_id=project.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="project-google-token",
            )
        )
        db.add(
            models.ProjectDataSource(
                project_id=project.id,
                provider=models.OAuthProvider.GOOGLE,
                source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
                binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
                source_id="sc-domain:client.example",
                source_label="Client GSC",
                is_active=True,
            )
        )
        db.commit()

        context, warnings = resolve_project_audit_data_sources(db, project_id=project.id)
        gsc_entry = next(
            source
            for source in context["sources"]
            if source["source_type"] == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE.value
        )

        assert context["has_external_data"] is True
        assert context["fallback_applied"] is True
        assert gsc_entry["requested_binding_mode"] == "workspace"
        assert gsc_entry["resolved_binding_mode"] == "client_magic_link"
        assert any("resolved client_magic_link" in warning for warning in warnings)
    finally:
        _cleanup(db)


def test_resolve_project_audit_data_sources_treats_inactive_sources_as_ai_estimate_only() -> None:
    db, _session_factory = _build_db()
    try:
        _user, workspace, project = _seed_workspace_project(db)
        db.add(
            models.OAuthConnection(
                workspace_id=workspace.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="workspace-google-token",
            )
        )
        db.add(
            models.ProjectDataSource(
                project_id=project.id,
                provider=models.OAuthProvider.GOOGLE,
                source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
                binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
                source_id="sc-domain:client.example",
                source_label="Client GSC",
                is_active=False,
            )
        )
        db.commit()

        context, warnings = resolve_project_audit_data_sources(db, project_id=project.id)
        gsc_entry = next(
            source
            for source in context["sources"]
            if source["source_type"] == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE.value
        )

        assert context["has_external_data"] is False
        assert context["mode"] == "ai_estimate_only"
        assert gsc_entry["resolved_binding_mode"] == "workspace"
        assert gsc_entry["effective_binding_mode"] == "ai_estimate"
        assert gsc_entry["has_external_data"] is False
        assert gsc_entry["source_id"] is None
        assert any("AI Estimates Only" in warning for warning in warnings)
    finally:
        _cleanup(db)


def test_resolve_project_audit_data_sources_requires_mapped_source_selection() -> None:
    db, _session_factory = _build_db()
    try:
        _user, workspace, project = _seed_workspace_project(db)
        db.add(
            models.OAuthConnection(
                workspace_id=workspace.id,
                provider=models.OAuthProvider.GOOGLE,
                access_token="workspace-google-token",
            )
        )
        db.add(
            models.ProjectDataSource(
                project_id=project.id,
                provider=models.OAuthProvider.GOOGLE,
                source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
                binding_mode=models.ProjectDataSourceBindingMode.WORKSPACE,
                source_id=None,
                source_label=None,
                is_active=True,
            )
        )
        db.commit()

        context, warnings = resolve_project_audit_data_sources(db, project_id=project.id)
        gsc_entry = next(
            source
            for source in context["sources"]
            if source["source_type"] == models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE.value
        )

        assert context["has_external_data"] is False
        assert context["mode"] == "ai_estimate_only"
        assert gsc_entry["resolved_binding_mode"] == "workspace"
        assert gsc_entry["effective_binding_mode"] == "ai_estimate"
        assert gsc_entry["has_external_data"] is False
        assert gsc_entry["source_label"] is None
        assert any("AI Estimates Only" in warning for warning in warnings)
    finally:
        _cleanup(db)
