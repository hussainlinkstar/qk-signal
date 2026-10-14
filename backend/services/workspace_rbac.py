from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.orm import Session

import models

CLIENT_READONLY_PERMISSIONS = ["portal:read", "profile:read"]
WORKSPACE_ADMIN_ROLES = {models.WorkspaceRole.ADMIN.value}
WORKSPACE_MANAGE_ROLES = {models.WorkspaceRole.ADMIN.value, models.WorkspaceRole.MANAGER.value}
WORKSPACE_WRITE_ROLES = {
    models.WorkspaceRole.ADMIN.value,
    models.WorkspaceRole.MANAGER.value,
    models.WorkspaceRole.EDITOR.value,
}
_PROJECT_SCOPED_ROLES = {
    models.WorkspaceRole.CLIENT_READONLY.value,
    models.WorkspaceRole.MANAGER.value,
}


@dataclass(frozen=True)
class WorkspaceAccess:
    workspace: models.Workspace
    membership: models.WorkspaceUser | None
    role: str


@dataclass(frozen=True)
class ProjectAccess:
    project: models.Project
    workspace: models.Workspace
    membership: models.WorkspaceUser | None
    role: str


def role_value(value: models.WorkspaceRole | str | None) -> str:
    if isinstance(value, models.WorkspaceRole):
        return value.value
    return str(value or "")


def is_client_readonly_role(value: models.WorkspaceRole | str | None) -> bool:
    return role_value(value) == models.WorkspaceRole.CLIENT_READONLY.value


def resolve_portal_access_context(
    db: Session,
    *,
    user: models.User,
) -> tuple[bool, int | None]:
    owner_workspace_count = (
        db.query(models.Workspace.id).filter(models.Workspace.owner_id == user.id).count()
    )
    memberships = (
        db.query(models.WorkspaceUser)
        .filter(models.WorkspaceUser.user_id == user.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .all()
    )
    if owner_workspace_count > 0 or not memberships:
        return (False, None)

    roles = [role_value(membership.role) for membership in memberships]
    if any(role != models.WorkspaceRole.CLIENT_READONLY.value for role in roles):
        return (False, None)

    workspace_ids = sorted({int(membership.workspace_id) for membership in memberships})
    portal_workspace_id = workspace_ids[0] if len(workspace_ids) == 1 else None
    return (True, portal_workspace_id)


def attach_portal_access_context(db: Session, *, user: models.User) -> models.User:
    portal_only, portal_workspace_id = resolve_portal_access_context(db, user=user)
    setattr(user, "resolved_portal_only", portal_only)
    setattr(user, "resolved_portal_workspace_id", portal_workspace_id)
    return user


def require_not_portal_only(
    user: models.User,
    *,
    detail: str = "Client portal users cannot access this resource.",
) -> None:
    if bool(getattr(user, "resolved_portal_only", False)):
        raise HTTPException(status_code=403, detail=detail)


def require_workspace_internal_access(role: str) -> None:
    if is_client_readonly_role(role):
        raise HTTPException(
            status_code=403,
            detail="Client portal users cannot access agency workspace resources.",
        )


def require_workspace_write_access(role: str) -> None:
    if role not in WORKSPACE_WRITE_ROLES:
        raise HTTPException(status_code=403, detail="Workspace write access required.")


def require_workspace_admin_access(role: str) -> None:
    """Workspace settings, billing, member role changes, project create/delete."""
    if role not in WORKSPACE_ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Workspace admin access required.")


def require_workspace_manage_access(role: str) -> None:
    """Member invitation (project-scoped for MANAGER)."""
    if role not in WORKSPACE_MANAGE_ROLES:
        raise HTTPException(status_code=403, detail="Workspace manage access required.")


def resolve_workspace_access(
    db: Session,
    *,
    user: models.User,
    workspace_id: int,
    allow_client_readonly: bool = False,
) -> WorkspaceAccess:
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    if workspace.owner_id == user.id:
        return WorkspaceAccess(
            workspace=workspace,
            membership=None,
            role=models.WorkspaceRole.ADMIN.value,
        )

    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace.id,
            models.WorkspaceUser.user_id == user.id,
        )
        .first()
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Not authorized for this workspace.")

    role = role_value(membership.role)
    if is_client_readonly_role(role) and not allow_client_readonly:
        raise HTTPException(
            status_code=403,
            detail="Client portal users cannot access agency workspace resources.",
        )

    return WorkspaceAccess(workspace=workspace, membership=membership, role=role)


def resolve_effective_project_role(
    workspace_role: str,
    project_access: models.WorkspaceUserProjectAccess | None,
) -> str:
    """Returns role_override if set on the assignment, else the workspace-level role."""
    if project_access and project_access.role_override:
        return role_value(project_access.role_override)
    return workspace_role


def _ensure_project_assignment(
    db: Session,
    *,
    membership: models.WorkspaceUser | None,
    project_id: int,
) -> models.WorkspaceUserProjectAccess | None:
    """Check that the member has an explicit project assignment. Returns the assignment row."""
    if membership is None:
        raise HTTPException(status_code=403, detail="Not authorized for this project.")

    assignment = (
        db.query(models.WorkspaceUserProjectAccess)
        .filter(
            models.WorkspaceUserProjectAccess.workspace_user_id == membership.id,
            models.WorkspaceUserProjectAccess.project_id == project_id,
        )
        .first()
    )
    if assignment is None:
        raise HTTPException(status_code=403, detail="Not authorized for this project.")
    return assignment


def _has_any_project_assignments(
    db: Session,
    *,
    membership: models.WorkspaceUser,
) -> bool:
    """Check if a member has any project-level assignments."""
    return (
        db.query(models.WorkspaceUserProjectAccess.id)
        .filter(models.WorkspaceUserProjectAccess.workspace_user_id == membership.id)
        .first()
    ) is not None


def _ensure_client_project_assignment(
    db: Session,
    *,
    membership: models.WorkspaceUser | None,
    project_id: int,
) -> None:
    _ensure_project_assignment(db, membership=membership, project_id=project_id)


def resolve_project_access(
    db: Session,
    *,
    user: models.User,
    project_id: int,
    allow_client_readonly: bool = False,
) -> ProjectAccess:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    workspace_access = resolve_workspace_access(
        db,
        user=user,
        workspace_id=project.workspace_id,
        allow_client_readonly=allow_client_readonly,
    )
    role = workspace_access.role
    membership = workspace_access.membership

    if role in _PROJECT_SCOPED_ROLES:
        assignment = _ensure_project_assignment(db, membership=membership, project_id=project.id)
        role = resolve_effective_project_role(role, assignment)
    elif membership is not None and _has_any_project_assignments(db, membership=membership):
        assignment = _ensure_project_assignment(db, membership=membership, project_id=project.id)
        role = resolve_effective_project_role(role, assignment)

    return ProjectAccess(
        project=project,
        workspace=workspace_access.workspace,
        membership=membership,
        role=role,
    )


def user_can_access_project(
    db: Session,
    *,
    user_id: int | None,
    project_id: int | None,
    allow_client_readonly: bool = False,
) -> bool:
    """Report whether a user is inside the tenant boundary of a project.

    SIGV2-1136: background workers also resolve a project from an identifier and
    then write to it, so they need the boundary the routers enforce. This
    delegates to :func:`resolve_project_access` instead of restating the rule,
    so workspace ownership, membership and the project assignments that scope a
    MANAGER or a client membership all keep one definition. The refusal is
    returned as ``False`` rather than raised, because a worker has no response
    to raise an ``HTTPException`` into.

    The boundary is deliberately membership, not record ownership: a workspace
    member may benchmark against a colleague's source audit, so that audit's
    ``user_id`` is not expected to match the member acting on it.
    """
    if user_id is None or project_id is None:
        return False
    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None:
        return False
    try:
        resolve_project_access(
            db,
            user=user,
            project_id=int(project_id),
            allow_client_readonly=allow_client_readonly,
        )
    except HTTPException:
        return False
    return True


def accessible_workspace_ids(db: Session, user: models.User) -> list[int]:
    """Workspace IDs a user owns or is a non-client member of.

    The tenant boundary for a listing, where there is no single project id to
    resolve. A client-readonly membership is excluded deliberately: that role
    sees only the projects explicitly assigned to it through a portal, so it
    must not widen a workspace-level listing. SIGV2-1210 moved this out of the
    external API router so the MCP server scopes its project list by the same
    rule rather than a second copy of it.
    """
    owned = [
        row.id
        for row in db.query(models.Workspace.id).filter(models.Workspace.owner_id == user.id).all()
    ]
    membered = [
        row.workspace_id
        for row in db.query(models.WorkspaceUser.workspace_id)
        .filter(
            models.WorkspaceUser.user_id == user.id,
            models.WorkspaceUser.role != "client_readonly",
        )
        .all()
    ]
    return list({*owned, *membered})


def replace_project_assignments(
    db: Session,
    *,
    membership: models.WorkspaceUser,
    project_ids: list[int],
) -> None:
    """Replace project assignments for any role that supports project scoping."""
    normalized_project_ids = sorted({int(project_id) for project_id in project_ids})
    projects = (
        db.query(models.Project).filter(models.Project.id.in_(normalized_project_ids)).all()
        if normalized_project_ids
        else []
    )
    if len(projects) != len(normalized_project_ids):
        raise HTTPException(status_code=400, detail="One or more projects were not found.")
    if any(project.workspace_id != membership.workspace_id for project in projects):
        raise HTTPException(
            status_code=400, detail="All assigned projects must belong to the target workspace."
        )

    existing_rows = (
        db.query(models.WorkspaceUserProjectAccess)
        .filter(models.WorkspaceUserProjectAccess.workspace_user_id == membership.id)
        .all()
    )
    existing_by_project_id = {int(row.project_id): row for row in existing_rows}
    target_project_ids = set(normalized_project_ids)

    for project_id, row in existing_by_project_id.items():
        if project_id not in target_project_ids:
            db.delete(row)

    for project_id in normalized_project_ids:
        if project_id in existing_by_project_id:
            continue
        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project_id,
            )
        )


def replace_client_project_assignments(
    db: Session,
    *,
    membership: models.WorkspaceUser,
    project_ids: list[int],
) -> None:
    if not is_client_readonly_role(membership.role):
        raise HTTPException(
            status_code=400, detail="Project assignments are supported only for client memberships."
        )
    replace_project_assignments(db, membership=membership, project_ids=project_ids)


def resolve_portal_workspace_access(
    db: Session,
    *,
    user: models.User,
    workspace_id: int | None = None,
) -> WorkspaceAccess:
    memberships = (
        db.query(models.WorkspaceUser)
        .filter(models.WorkspaceUser.user_id == user.id)
        .order_by(models.WorkspaceUser.created_at.asc(), models.WorkspaceUser.id.asc())
        .all()
    )
    client_memberships = [
        membership for membership in memberships if is_client_readonly_role(membership.role)
    ]
    if not client_memberships:
        raise HTTPException(status_code=403, detail="Client portal access required.")

    selected_membership: models.WorkspaceUser | None = None
    if workspace_id is not None:
        selected_membership = next(
            (
                membership
                for membership in client_memberships
                if int(membership.workspace_id) == int(workspace_id)
            ),
            None,
        )
        if selected_membership is None:
            raise HTTPException(status_code=403, detail="Not authorized for this workspace.")
    else:
        selected_membership = client_memberships[0]

    workspace = (
        db.query(models.Workspace)
        .filter(models.Workspace.id == selected_membership.workspace_id)
        .first()
    )
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    return WorkspaceAccess(
        workspace=workspace,
        membership=selected_membership,
        role=models.WorkspaceRole.CLIENT_READONLY.value,
    )
