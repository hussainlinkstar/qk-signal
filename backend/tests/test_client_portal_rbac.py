from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import main
import models
from billing.router import list_plans
from database import Base
from routers import api_router
from routers.api_router import JiraProjectExportRequest, _resolve_project_for_audit
from routers.portal_router import (
    get_portal_branding,
    get_portal_project_dashboard,
    list_portal_project_tasks,
    list_portal_projects,
)
from routers.workspace_router import (
    ClientInvitationRequest,
    invite_workspace_client,
    list_current_workspace_members,
    list_current_workspace_projects,
)
from services.email_service import EmailService
from services.workspace_rbac import attach_portal_access_context


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: Engine) -> None:
    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_workspace(
    db: Session,
) -> tuple[models.User, models.Workspace, models.Project, models.Project]:
    owner = models.User(
        email="agency-owner@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        company_name="Signal Forge",
        custom_logo_url="https://cdn.example.com/logo.svg",
        primary_color="#0ea5e9",
        secondary_color="#f97316",
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Signal Forge Clients", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project_alpha = models.Project(
        workspace_id=workspace.id,
        name="Alpha Motors",
        domain_url="https://alpha.example",
        language="en",
        target_country="US",
    )
    project_beta = models.Project(
        workspace_id=workspace.id,
        name="Beta Legal",
        domain_url="https://beta.example",
        language="en",
        target_country="US",
    )
    db.add_all([project_alpha, project_beta])
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project_alpha)
    db.refresh(project_beta)
    return owner, workspace, project_alpha, project_beta


def test_invite_workspace_client_creates_membership_assignments_and_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project_alpha, project_beta = _seed_workspace(db)
        captured_email: dict[str, object] = {}

        async def _fake_send_client_invitation_email(self, recipient_email: str, **kwargs):
            captured_email["recipient_email"] = recipient_email
            captured_email.update(kwargs)
            return SimpleNamespace(id=1)

        monkeypatch.setattr(
            EmailService,
            "send_client_invitation_email",
            _fake_send_client_invitation_email,
        )

        response = asyncio.run(
            invite_workspace_client(
                workspace_id=workspace.id,
                payload=ClientInvitationRequest(
                    email="client@example.com",
                    name="Acme Client",
                    project_ids=[project_alpha.id, project_beta.id],
                ),
                user=owner,
                db=db,
            )
        )

        invited_user = (
            db.query(models.User).filter(models.User.email == "client@example.com").first()
        )
        membership = (
            db.query(models.WorkspaceUser)
            .filter(
                models.WorkspaceUser.workspace_id == workspace.id,
                models.WorkspaceUser.user_id == invited_user.id,
            )
            .first()
        )
        assignments = (
            db.query(models.WorkspaceUserProjectAccess)
            .filter(models.WorkspaceUserProjectAccess.workspace_user_id == membership.id)
            .order_by(models.WorkspaceUserProjectAccess.project_id.asc())
            .all()
        )

        assert response.role == models.WorkspaceRole.CLIENT_READONLY.value
        assert response.invited is True
        assert response.email_queued is True
        assert response.invitation_url is None
        assert membership is not None
        assert membership.role == models.WorkspaceRole.CLIENT_READONLY
        assert [row.project_id for row in assignments] == [project_alpha.id, project_beta.id]
        assert captured_email["recipient_email"] == "client@example.com"
        assert captured_email["workspace_name"] == workspace.name
        assert captured_email["agency_name"] == "Signal Forge"
        assert captured_email["project_names"] == [project_alpha.name, project_beta.name]
        assert str(captured_email["portal_url"]).endswith("/portal")
    finally:
        _cleanup(db, engine)


def test_invite_workspace_client_never_returns_reset_credential_when_email_queue_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project_alpha, _ = _seed_workspace(db)

        async def _fake_send_client_invitation_email(self, recipient_email: str, **kwargs):
            return None

        monkeypatch.setattr(
            EmailService,
            "send_client_invitation_email",
            _fake_send_client_invitation_email,
        )

        response = asyncio.run(
            invite_workspace_client(
                workspace_id=workspace.id,
                payload=ClientInvitationRequest(
                    email="manual-link@example.com",
                    name="Manual Link Client",
                    project_ids=[project_alpha.id],
                ),
                user=owner,
                db=db,
            )
        )

        assert response.email_queued is False
        assert response.invitation_url is None
    finally:
        _cleanup(db, engine)


def test_invite_existing_user_uses_login_link_without_password_reset_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.auth_service import AuthService

    db, engine = _build_db()
    try:
        owner, workspace, project_alpha, _ = _seed_workspace(db)
        existing_user = models.User(
            email="existing-client@example.com",
            hashed_password="existing-hash",
            role="user",
            credits=0,
        )
        db.add(existing_user)
        db.commit()
        captured: dict[str, object] = {}

        def _unexpected_reset_token(self, email: str) -> str:
            raise AssertionError(f"reset token must not be generated for existing user {email}")

        async def _capture_email(self, recipient_email: str, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(id=1)

        monkeypatch.setattr(AuthService, "create_password_reset_token", _unexpected_reset_token)
        monkeypatch.setattr(EmailService, "send_client_invitation_email", _capture_email)

        response = asyncio.run(
            invite_workspace_client(
                workspace_id=workspace.id,
                payload=ClientInvitationRequest(
                    email=existing_user.email,
                    project_ids=[project_alpha.id],
                ),
                user=owner,
                db=db,
            )
        )

        assert response.invited is False
        assert response.invitation_url is None
        assert str(captured["invitation_url"]).endswith("/login?next=/portal")
    finally:
        _cleanup(db, engine)


def test_invite_existing_internal_member_does_not_demote_role() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project_alpha, _ = _seed_workspace(db)
        editor = models.User(
            email="internal-editor@example.com",
            hashed_password="x",
            role="user",
            credits=0,
        )
        db.add(editor)
        db.flush()
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=editor.id,
            role=models.WorkspaceRole.EDITOR,
        )
        db.add(membership)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                invite_workspace_client(
                    workspace_id=workspace.id,
                    payload=ClientInvitationRequest(
                        email=editor.email,
                        project_ids=[project_alpha.id],
                    ),
                    user=owner,
                    db=db,
                )
            )

        assert exc.value.status_code == 409
        db.refresh(membership)
        assert membership.role == models.WorkspaceRole.EDITOR
    finally:
        _cleanup(db, engine)


def test_client_portal_role_is_scoped_and_blocked_from_internal_surfaces() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project_alpha, project_beta = _seed_workspace(db)
        client_user = models.User(
            email="portal-user@example.com",
            hashed_password="x",
            role="user",
            credits=0,
            company_name="Portal User",
        )
        db.add(client_user)
        db.flush()

        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=client_user.id,
            role=models.WorkspaceRole.CLIENT_READONLY,
        )
        db.add(membership)
        db.flush()

        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project_alpha.id,
            )
        )
        db.add(
            models.Audit(
                user_id=owner.id,
                project_id=project_alpha.id,
                project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
                url=project_alpha.domain_url,
                geo_score=67.0,
                seo_score=74.0,
                aeo_score=71.0,
                full_report={
                    "analysis": {
                        "summary": "Technical SEO is stable, but entity coverage needs more depth.",
                        "recommendations": ["Expand entity-backed FAQs on high-value pages."],
                    },
                    "metadata": {"audit_outcome": "completed"},
                },
            )
        )
        db.add(
            models.ProjectJiraExport(
                project_id=project_alpha.id,
                issue_id="10042",
                issue_key="SYN-42",
                issue_url="https://example.atlassian.net/browse/SYN-42",
                title="Expand entity-backed FAQs",
                issue_type="Task",
                status_name="To Do",
            )
        )
        db.commit()

        portal_user = attach_portal_access_context(db, user=client_user)

        branding = get_portal_branding(user=portal_user, db=db, workspace_id=workspace.id)
        projects = list_portal_projects(user=portal_user, db=db, workspace_id=workspace.id)
        dashboard = get_portal_project_dashboard(
            project_id=project_alpha.id, user=portal_user, db=db
        )
        tasks = list_portal_project_tasks(project_id=project_alpha.id, user=portal_user, db=db)

        assert branding.workspace_id == workspace.id
        assert branding.agency_name == "Signal Forge"
        assert branding.primary_color == "#0ea5e9"
        assert [project.id for project in projects] == [project_alpha.id]
        assert dashboard.project.id == project_alpha.id
        assert dashboard.latest_audit is not None
        assert dashboard.latest_audit.summary is not None
        assert "entity coverage" in dashboard.latest_audit.summary
        assert len(tasks) == 1
        assert tasks[0].issue_key == "SYN-42"

        with pytest.raises(HTTPException) as project_exc:
            get_portal_project_dashboard(project_id=project_beta.id, user=portal_user, db=db)
        assert project_exc.value.status_code == 403

        with pytest.raises(HTTPException) as workspace_projects_exc:
            list_current_workspace_projects(user=portal_user, db=db)
        assert workspace_projects_exc.value.status_code == 403

        with pytest.raises(HTTPException) as workspace_members_exc:
            list_current_workspace_members(user=portal_user, db=db)
        assert workspace_members_exc.value.status_code == 403

        with pytest.raises(HTTPException) as audit_exc:
            _resolve_project_for_audit(project_id=project_alpha.id, user=portal_user, db=db)
        assert audit_exc.value.status_code == 403

        with pytest.raises(HTTPException) as billing_exc:
            list_plans(http_request=None, user=portal_user, db=db)
        assert billing_exc.value.status_code == 403
    finally:
        _cleanup(db, engine)


def test_jira_export_endpoint_persists_project_jira_export_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        owner, _workspace, project_alpha, _project_beta = _seed_workspace(db)
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id="cus_123",
                plan_type="plan_specialist",
                status="active",
            )
        )
        db.add(
            models.JiraConnection(
                workspace_id=project_alpha.workspace_id,
                access_token="jira-access-token",
                cloud_id="cloud-123",
                site_url="https://example.atlassian.net",
                default_jira_project_key="SYN",
            )
        )
        db.commit()

        async def _fake_create_issue(**kwargs):
            assert kwargs["project_key"] == "SYN"
            return SimpleNamespace(
                issue_id="1001",
                issue_key="SYN-99",
                issue_url="https://example.atlassian.net/browse/SYN-99",
            )

        monkeypatch.setattr(api_router.jira_service, "create_issue", _fake_create_issue)

        response = asyncio.run(
            api_router.export_project_guide_to_jira(
                project_id=project_alpha.id,
                payload=JiraProjectExportRequest(
                    recommendation_title="Ship stronger FAQ schema",
                    generated_guide_markdown="## Steps\n- Expand entity coverage",
                ),
                user=owner,
                db=db,
            )
        )

        export_rows = (
            db.query(models.ProjectJiraExport)
            .filter(models.ProjectJiraExport.project_id == project_alpha.id)
            .all()
        )

        assert response.issue_key == "SYN-99"
        assert len(export_rows) == 1
        assert export_rows[0].issue_key == "SYN-99"
        assert export_rows[0].issue_url.endswith("/browse/SYN-99")
        assert export_rows[0].title == "Ship stronger FAQ schema"
        assert export_rows[0].issue_type == "Task"
        assert export_rows[0].status_name == "Exported"
    finally:
        _cleanup(db, engine)
