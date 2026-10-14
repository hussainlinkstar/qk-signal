"""Tests for RBAC enhancements — MANAGER role, project role_override, and
differentiated admin/manage/write permission gates.

AEX-40 Phase 1.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from services.workspace_rbac import (
    WORKSPACE_ADMIN_ROLES,
    WORKSPACE_MANAGE_ROLES,
    WORKSPACE_WRITE_ROLES,
    require_workspace_admin_access,
    require_workspace_manage_access,
    require_workspace_write_access,
    resolve_effective_project_role,
    resolve_project_access,
)


# ── helpers ──────────────────────────────────────────────────────────
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
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_user(db: Session, email: str, **kwargs) -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=10, **kwargs)
    db.add(user)
    db.flush()
    return user


def _seed_workspace(db: Session, owner: models.User) -> models.Workspace:
    ws = models.Workspace(name="Test Workspace", owner_id=owner.id)
    db.add(ws)
    db.flush()
    return ws


def _seed_membership(
    db: Session,
    workspace: models.Workspace,
    user: models.User,
    role: models.WorkspaceRole,
) -> models.WorkspaceUser:
    mem = models.WorkspaceUser(workspace_id=workspace.id, user_id=user.id, role=role)
    db.add(mem)
    db.flush()
    return mem


def _seed_project(
    db: Session, workspace: models.Workspace, name: str = "Project A"
) -> models.Project:
    proj = models.Project(
        workspace_id=workspace.id,
        name=name,
        icp_roles=[],
        competitors_json=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(proj)
    db.flush()
    return proj


def _seed_project_access(
    db: Session,
    membership: models.WorkspaceUser,
    project: models.Project,
    role_override: models.WorkspaceRole | None = None,
) -> models.WorkspaceUserProjectAccess:
    access = models.WorkspaceUserProjectAccess(
        workspace_user_id=membership.id,
        project_id=project.id,
        role_override=role_override,
    )
    db.add(access)
    db.flush()
    return access


# ── Role constant tests ─────────────────────────────────────────────


class TestRoleConstants:
    def test_admin_roles_contains_only_admin(self):
        assert WORKSPACE_ADMIN_ROLES == {"ADMIN"}

    def test_manage_roles_contains_admin_and_manager(self):
        assert WORKSPACE_MANAGE_ROLES == {"ADMIN", "MANAGER"}

    def test_write_roles_contains_admin_manager_editor(self):
        assert WORKSPACE_WRITE_ROLES == {"ADMIN", "MANAGER", "EDITOR"}

    def test_manager_in_workspace_role_enum(self):
        assert hasattr(models.WorkspaceRole, "MANAGER")
        assert models.WorkspaceRole.MANAGER.value == "MANAGER"


# ── Guard function tests ────────────────────────────────────────────


class TestRequireAdminAccess:
    def test_admin_passes(self):
        require_workspace_admin_access("ADMIN")

    def test_manager_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_admin_access("MANAGER")
        assert exc.value.status_code == 403

    def test_editor_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_admin_access("EDITOR")
        assert exc.value.status_code == 403

    def test_viewer_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_admin_access("VIEWER")
        assert exc.value.status_code == 403

    def test_client_readonly_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_admin_access("CLIENT_READONLY")
        assert exc.value.status_code == 403


class TestRequireManageAccess:
    def test_admin_passes(self):
        require_workspace_manage_access("ADMIN")

    def test_manager_passes(self):
        require_workspace_manage_access("MANAGER")

    def test_editor_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_manage_access("EDITOR")
        assert exc.value.status_code == 403

    def test_viewer_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_manage_access("VIEWER")
        assert exc.value.status_code == 403


class TestRequireWriteAccess:
    def test_admin_passes(self):
        require_workspace_write_access("ADMIN")

    def test_manager_passes(self):
        require_workspace_write_access("MANAGER")

    def test_editor_passes(self):
        require_workspace_write_access("EDITOR")

    def test_viewer_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_write_access("VIEWER")
        assert exc.value.status_code == 403

    def test_client_readonly_rejected(self):
        with pytest.raises(HTTPException) as exc:
            require_workspace_write_access("CLIENT_READONLY")
        assert exc.value.status_code == 403


# ── Effective project role resolution ────────────────────────────────


class TestResolveEffectiveProjectRole:
    def test_no_access_row_returns_workspace_role(self):
        assert resolve_effective_project_role("EDITOR", None) == "EDITOR"

    def test_access_without_override_returns_workspace_role(self):
        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            editor = _seed_user(db, "e@test.com")
            mem = _seed_membership(db, ws, editor, models.WorkspaceRole.EDITOR)
            proj = _seed_project(db, ws)
            access = _seed_project_access(db, mem, proj, role_override=None)
            db.commit()

            result = resolve_effective_project_role("EDITOR", access)
            assert result == "EDITOR"
        finally:
            _cleanup(db, engine)

    def test_access_with_override_returns_override(self):
        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            viewer = _seed_user(db, "v@test.com")
            mem = _seed_membership(db, ws, viewer, models.WorkspaceRole.VIEWER)
            proj = _seed_project(db, ws)
            access = _seed_project_access(db, mem, proj, role_override=models.WorkspaceRole.EDITOR)
            db.commit()

            result = resolve_effective_project_role("VIEWER", access)
            assert result == "EDITOR"
        finally:
            _cleanup(db, engine)


# ── Manager project scoping ─────────────────────────────────────────


class TestManagerProjectScoping:
    """MANAGER is a project-scoped role: they can only access projects
    they have been explicitly assigned to."""

    def test_manager_with_assignment_can_access_project(self):
        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            mem = _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            proj = _seed_project(db, ws)
            _seed_project_access(db, mem, proj)
            db.commit()

            access = resolve_project_access(db, user=manager, project_id=proj.id)
            assert access.project.id == proj.id
            assert access.role in {"MANAGER", "EDITOR", "ADMIN"}
        finally:
            _cleanup(db, engine)

    def test_manager_without_assignment_blocked(self):
        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            proj = _seed_project(db, ws)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                resolve_project_access(db, user=manager, project_id=proj.id)
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_manager_role_override_applied(self):
        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            mem = _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            proj = _seed_project(db, ws)
            _seed_project_access(db, mem, proj, role_override=models.WorkspaceRole.ADMIN)
            db.commit()

            access = resolve_project_access(db, user=manager, project_id=proj.id)
            assert access.role == "ADMIN"
        finally:
            _cleanup(db, engine)


# ── Router gate tests ────────────────────────────────────────────────


class TestWorkspaceRouterGates:
    """Verify that workspace-settings endpoints reject MANAGER/EDITOR,
    and that manage-level endpoints accept MANAGER but reject EDITOR."""

    def test_update_workspace_rejects_manager(self):
        from routers.workspace_router import update_current_workspace
        from routers.workspace_router import WorkspaceUpdateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                update_current_workspace(
                    payload=WorkspaceUpdateRequest(name="Renamed"),
                    user=manager,
                    db=db,
                )
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_update_workspace_passes_for_admin(self):
        from routers.workspace_router import update_current_workspace
        from routers.workspace_router import WorkspaceUpdateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            _seed_workspace(db, owner)
            db.commit()

            result = update_current_workspace(
                payload=WorkspaceUpdateRequest(name="Renamed"),
                user=owner,
                db=db,
            )
            assert result.name if hasattr(result, "name") else result["name"] == "Renamed"
        finally:
            _cleanup(db, engine)

    def test_member_upsert_rejects_manager_self_promotion(self):
        from routers.workspace_router import (
            WorkspaceMemberUpsertRequest,
            upsert_current_workspace_member,
        )

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            membership = _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                upsert_current_workspace_member(
                    payload=WorkspaceMemberUpsertRequest(
                        email=manager.email,
                        role="ADMIN",
                    ),
                    user=manager,
                    db=db,
                )

            assert exc.value.status_code == 403
            db.refresh(membership)
            assert membership.role == models.WorkspaceRole.MANAGER
        finally:
            _cleanup(db, engine)

    def test_update_member_role_rejects_editor(self):
        from routers.workspace_router import update_current_workspace_member_role
        from routers.workspace_router import WorkspaceMemberRoleUpdateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            editor = _seed_user(db, "e@test.com")
            _seed_membership(db, ws, editor, models.WorkspaceRole.EDITOR)
            target = _seed_user(db, "t@test.com")
            _seed_membership(db, ws, target, models.WorkspaceRole.VIEWER)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                update_current_workspace_member_role(
                    member_user_id=target.id,
                    payload=WorkspaceMemberRoleUpdateRequest(role="EDITOR"),
                    user=editor,
                    db=db,
                )
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_update_member_role_rejects_manager(self):
        from routers.workspace_router import update_current_workspace_member_role
        from routers.workspace_router import WorkspaceMemberRoleUpdateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            target = _seed_user(db, "t@test.com")
            _seed_membership(db, ws, target, models.WorkspaceRole.VIEWER)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                update_current_workspace_member_role(
                    member_user_id=target.id,
                    payload=WorkspaceMemberRoleUpdateRequest(role="EDITOR"),
                    user=manager,
                    db=db,
                )
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_remove_member_rejects_manager(self):
        from routers.workspace_router import remove_current_workspace_member

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            target = _seed_user(db, "t@test.com")
            _seed_membership(db, ws, target, models.WorkspaceRole.VIEWER)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                remove_current_workspace_member(
                    member_user_id=target.id,
                    user=manager,
                    db=db,
                )
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_create_project_passes_for_manager(self):
        from routers.workspace_router import create_project_in_current_workspace
        from routers.workspace_router import ProjectCreateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            db.commit()

            result = create_project_in_current_workspace(
                payload=ProjectCreateRequest(name="New Project", domain_url="https://example.com"),
                user=manager,
                db=db,
            )
            name = result.name if hasattr(result, "name") else result["name"]
            assert name == "New Project"
        finally:
            _cleanup(db, engine)

    def test_create_project_rejects_editor(self):
        from routers.workspace_router import create_project_in_current_workspace
        from routers.workspace_router import ProjectCreateRequest

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            editor = _seed_user(db, "e@test.com")
            _seed_membership(db, ws, editor, models.WorkspaceRole.EDITOR)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                create_project_in_current_workspace(
                    payload=ProjectCreateRequest(
                        name="New Project", domain_url="https://example.com"
                    ),
                    user=editor,
                    db=db,
                )
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_delete_project_rejects_manager(self):
        from routers.workspace_router import delete_project

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            manager = _seed_user(db, "m@test.com")
            mem = _seed_membership(db, ws, manager, models.WorkspaceRole.MANAGER)
            proj = _seed_project(db, ws)
            _seed_project_access(db, mem, proj)
            db.commit()

            with pytest.raises(HTTPException) as exc:
                delete_project(project_id=proj.id, user=manager, db=db)
            assert exc.value.status_code == 403
        finally:
            _cleanup(db, engine)

    def test_delete_project_passes_for_admin(self):
        from routers.workspace_router import delete_project

        db, engine = _build_db()
        try:
            owner = _seed_user(db, "o@test.com")
            ws = _seed_workspace(db, owner)
            proj = _seed_project(db, ws)
            db.commit()

            result = delete_project(project_id=proj.id, user=owner, db=db)
            assert result is None
        finally:
            _cleanup(db, engine)


# ── Service write-role inclusion tests ───────────────────────────────


class TestServiceWriteRoles:
    def test_annotation_write_roles_include_manager(self):
        from services.report_annotation_service import ANNOTATION_WRITE_ROLES

        assert "MANAGER" in ANNOTATION_WRITE_ROLES

    def test_annotation_read_roles_include_manager(self):
        from services.report_annotation_service import ANNOTATION_READ_ROLES

        assert "MANAGER" in ANNOTATION_READ_ROLES

    def test_claim_review_write_roles_include_manager(self):
        from services.claim_review_service import WRITE_ROLES

        assert "MANAGER" in WRITE_ROLES

    def test_task_write_roles_include_manager(self):
        from services.project_task_service import TASK_WRITE_ROLES

        assert "MANAGER" in TASK_WRITE_ROLES

    def test_task_write_allowed_for_manager(self):
        from services.project_task_service import task_write_allowed

        assert task_write_allowed("MANAGER") is True

    def test_annotation_write_allowed_for_manager(self):
        from services.report_annotation_service import annotation_write_allowed

        assert annotation_write_allowed("MANAGER") is True
