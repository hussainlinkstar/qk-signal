from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.schemas.jira_schema import JiraInitializeRequest, JiraProject
from app.schemas.scheduling import ScheduledAuditCreate, ScheduledAuditUpdate
from database import Base
from routers import jira_router, scheduling_router


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _user(db: Session, email: str) -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=25)
    db.add(user)
    db.flush()
    return user


def _workspace(db: Session, owner: models.User, name: str) -> models.Workspace:
    workspace = models.Workspace(name=name, owner_id=owner.id)
    db.add(workspace)
    db.flush()
    return workspace


def _project(db: Session, workspace: models.Workspace, name: str) -> models.Project:
    project = models.Project(
        workspace_id=workspace.id,
        name=name,
        domain_url=f"https://{name.lower().replace(' ', '-')}.example.com",
        icp_roles=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.flush()
    return project


def _membership(
    db: Session,
    workspace: models.Workspace,
    user: models.User,
    role: models.WorkspaceRole,
    *,
    project: models.Project | None = None,
) -> models.WorkspaceUser:
    membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    db.flush()
    if project is not None:
        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project.id,
            )
        )
        db.flush()
    return membership


def _schedule(
    db: Session,
    user: models.User,
    project: models.Project,
) -> models.ScheduledAudit:
    schedule = models.ScheduledAudit(
        user_id=user.id,
        project_id=project.id,
        url=project.domain_url,
        audit_type=models.AuditType.STANDARD,
        frequency=models.ScheduledAuditFrequency.WEEKLY,
        audit_params={"audit_target_type": "website"},
        is_active=True,
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


@pytest.fixture()
def db() -> Session:
    session, engine = _build_db()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture(autouse=True)
def allow_scheduling_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduling_router.plan_validator, "can_schedule_audits", lambda _user: True)


def _assert_forbidden(call) -> None:
    with pytest.raises(HTTPException) as exc_info:
        call()
    assert exc_info.value.status_code == 403


def test_jira_initialize_rejects_cross_tenant_project_before_jira_calls(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attacker = _user(db, "attacker@example.com")
    attacker_workspace = _workspace(db, attacker, "Attacker")
    victim = _user(db, "victim@example.com")
    victim_workspace = _workspace(db, victim, "Victim")
    victim_project = _project(db, victim_workspace, "Victim Project")
    db.add(
        models.JiraConnection(
            workspace_id=attacker_workspace.id,
            access_token="attacker-token",
            cloud_id="attacker-cloud",
        )
    )
    db.commit()

    jira_called = False

    async def _unexpected_call(*_args, **_kwargs):
        nonlocal jira_called
        jira_called = True
        raise AssertionError("Jira must not be called for an unauthorized project")

    monkeypatch.setattr(jira_router.jira_service, "get_myself", _unexpected_call)
    monkeypatch.setattr(jira_router.jira_service, "create_project", _unexpected_call)

    _assert_forbidden(
        lambda: asyncio.run(
            jira_router.initialize_jira_project(
                JiraInitializeRequest(project_id=victim_project.id),
                user=attacker,
                db=db,
            )
        )
    )
    assert jira_called is False


def test_jira_initialize_allows_assigned_editor_and_uses_project_workspace_connection(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _user(db, "owner@example.com")
    workspace = _workspace(db, owner, "Agency")
    project = _project(db, workspace, "Authorized Project")
    editor = _user(db, "editor@example.com")
    _membership(db, workspace, editor, models.WorkspaceRole.EDITOR, project=project)
    db.add(
        models.JiraConnection(
            workspace_id=workspace.id,
            access_token="workspace-token",
            cloud_id="workspace-cloud",
        )
    )
    db.commit()

    captured: dict[str, str] = {}

    async def _get_myself(cloud_id: str, access_token: str):
        captured.update(cloud_id=cloud_id, access_token=access_token)
        return {"accountId": "account-1"}

    async def _create_project(**kwargs):
        captured.update(name=kwargs["name"], key=kwargs["key"])
        return JiraProject(id="100", key=kwargs["key"], name=kwargs["name"])

    monkeypatch.setattr(jira_router.jira_service, "get_myself", _get_myself)
    monkeypatch.setattr(jira_router.jira_service, "create_project", _create_project)

    result = asyncio.run(
        jira_router.initialize_jira_project(
            JiraInitializeRequest(project_id=project.id),
            user=editor,
            db=db,
        )
    )

    assert result.name == "Qiko Signal - Authorized Project"
    assert captured["cloud_id"] == "workspace-cloud"
    assert captured["access_token"] == "workspace-token"


@pytest.mark.parametrize(
    ("role", "assigned"),
    [
        (models.WorkspaceRole.VIEWER, True),
        (models.WorkspaceRole.CLIENT_READONLY, True),
        (models.WorkspaceRole.MANAGER, False),
    ],
)
def test_schedule_create_rejects_non_writers(
    db: Session,
    role: models.WorkspaceRole,
    assigned: bool,
) -> None:
    owner = _user(db, f"owner-{role.value}@example.com")
    workspace = _workspace(db, owner, f"Workspace {role.value}")
    project = _project(db, workspace, f"Project {role.value}")
    member = _user(db, f"member-{role.value}@example.com")
    _membership(db, workspace, member, role, project=project if assigned else None)
    db.commit()

    _assert_forbidden(
        lambda: scheduling_router.create_scheduled_audit(
            ScheduledAuditCreate(project_id=project.id, url=project.domain_url),
            user=member,
            db=db,
        )
    )


@pytest.mark.parametrize(
    "role",
    [models.WorkspaceRole.VIEWER, models.WorkspaceRole.CLIENT_READONLY],
)
def test_schedule_update_and_delete_reject_readonly_roles(
    db: Session,
    role: models.WorkspaceRole,
) -> None:
    owner = _user(db, f"owner-write-{role.value}@example.com")
    workspace = _workspace(db, owner, f"Write Workspace {role.value}")
    project = _project(db, workspace, f"Write Project {role.value}")
    member = _user(db, f"writer-{role.value}@example.com")
    _membership(db, workspace, member, role, project=project)
    schedule = _schedule(db, member, project)

    _assert_forbidden(
        lambda: scheduling_router.update_scheduled_audit(
            schedule.id,
            ScheduledAuditUpdate(is_active=False),
            user=member,
            db=db,
        )
    )
    _assert_forbidden(
        lambda: scheduling_router.delete_scheduled_audit(
            schedule.id,
            user=member,
            db=db,
        )
    )
    assert db.get(models.ScheduledAudit, schedule.id) is not None


def test_unassigned_manager_cannot_update_or_delete_schedule(db: Session) -> None:
    owner = _user(db, "manager-owner@example.com")
    workspace = _workspace(db, owner, "Manager Workspace")
    project = _project(db, workspace, "Manager Project")
    manager = _user(db, "unassigned-manager@example.com")
    _membership(db, workspace, manager, models.WorkspaceRole.MANAGER)
    schedule = _schedule(db, manager, project)

    _assert_forbidden(
        lambda: scheduling_router.update_scheduled_audit(
            schedule.id,
            ScheduledAuditUpdate(frequency="monthly"),
            user=manager,
            db=db,
        )
    )
    _assert_forbidden(
        lambda: scheduling_router.delete_scheduled_audit(
            schedule.id,
            user=manager,
            db=db,
        )
    )


@pytest.mark.parametrize(
    "role",
    [models.WorkspaceRole.MANAGER, models.WorkspaceRole.EDITOR],
)
def test_assigned_manager_and_editor_can_create_update_and_delete_schedule(
    db: Session,
    role: models.WorkspaceRole,
) -> None:
    owner = _user(db, f"success-owner-{role.value}@example.com")
    workspace = _workspace(db, owner, f"Success Workspace {role.value}")
    project = _project(db, workspace, f"Success Project {role.value}")
    member = _user(db, f"success-member-{role.value}@example.com")
    _membership(db, workspace, member, role, project=project)
    db.commit()

    schedule = scheduling_router.create_scheduled_audit(
        ScheduledAuditCreate(project_id=project.id, url=project.domain_url),
        user=member,
        db=db,
    )
    updated = scheduling_router.update_scheduled_audit(
        schedule.id,
        ScheduledAuditUpdate(frequency="monthly"),
        user=member,
        db=db,
    )
    assert updated.frequency == models.ScheduledAuditFrequency.MONTHLY

    scheduling_router.delete_scheduled_audit(schedule.id, user=member, db=db)
    assert db.get(models.ScheduledAudit, schedule.id) is None


def test_admin_owner_schedule_crud_still_succeeds(db: Session) -> None:
    admin = _user(db, "admin@example.com")
    workspace = _workspace(db, admin, "Admin Workspace")
    project = _project(db, workspace, "Admin Project")
    db.commit()

    schedule = scheduling_router.create_scheduled_audit(
        ScheduledAuditCreate(project_id=project.id, url=project.domain_url),
        user=admin,
        db=db,
    )
    assert scheduling_router.get_scheduled_audit(schedule.id, user=admin, db=db).id == schedule.id
    assert [
        item.id
        for item in scheduling_router.list_scheduled_audits(
            project_id=None,
            site_id=None,
            user=admin,
            db=db,
        )
    ] == [schedule.id]

    scheduling_router.delete_scheduled_audit(schedule.id, user=admin, db=db)
    assert db.get(models.ScheduledAudit, schedule.id) is None


def test_assigned_viewer_can_read_schedule(db: Session) -> None:
    owner = _user(db, "viewer-owner@example.com")
    workspace = _workspace(db, owner, "Viewer Workspace")
    project = _project(db, workspace, "Viewer Project")
    viewer = _user(db, "assigned-viewer@example.com")
    _membership(db, workspace, viewer, models.WorkspaceRole.VIEWER, project=project)
    schedule = _schedule(db, viewer, project)

    assert scheduling_router.get_scheduled_audit(schedule.id, user=viewer, db=db).id == schedule.id
    listed = scheduling_router.list_scheduled_audits(
        project_id=project.id,
        site_id=None,
        user=viewer,
        db=db,
    )
    assert [item.id for item in listed] == [schedule.id]


def test_schedule_move_reauthorizes_target_project(db: Session) -> None:
    user = _user(db, "move-admin@example.com")
    source_workspace = _workspace(db, user, "Source Workspace")
    source_project = _project(db, source_workspace, "Source Project")
    target_owner = _user(db, "target-owner@example.com")
    target_workspace = _workspace(db, target_owner, "Target Workspace")
    target_project = _project(db, target_workspace, "Target Project")
    _membership(db, target_workspace, user, models.WorkspaceRole.VIEWER, project=target_project)
    schedule = _schedule(db, user, source_project)

    _assert_forbidden(
        lambda: scheduling_router.update_scheduled_audit(
            schedule.id,
            ScheduledAuditUpdate(project_id=target_project.id),
            user=user,
            db=db,
        )
    )
    db.refresh(schedule)
    assert schedule.project_id == source_project.id
