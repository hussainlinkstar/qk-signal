"""Client onboarding wizard & bulk invite, Phase 3 (AEX-40)."""

from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from core.password_hashing import hash_password
from sqlalchemy.orm import Session

import models
from models import WorkspaceRole
from schemas.auth import normalize_company_name
from services.email_service import EmailService

logger = logging.getLogger(__name__)

_MAX_BULK_INVITATIONS = 50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_frontend_base_url() -> str:
    frontend_url = (os.getenv("FRONTEND_URL") or "").strip()
    app_base_url = (os.getenv("APP_BASE_URL") or "").strip()
    return (frontend_url or app_base_url or "http://localhost:3000").rstrip("/")


def _find_or_create_user(
    db: Session,
    *,
    email: str,
    name: str | None = None,
) -> tuple[models.User, bool]:
    """Return ``(user, is_new)``."""
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is not None:
        return user, False

    hashed_password = hash_password(secrets.token_urlsafe(48))
    user = models.User(
        email=email,
        hashed_password=hashed_password,
        # Invitee names arrive from invitation flows; cap rather than reject so
        # an over-long name cannot break onboarding.
        company_name=normalize_company_name(name, on_overlong="truncate"),
        role="user",
    )
    db.add(user)
    db.flush()
    return user, True


def _ensure_workspace_membership(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
) -> tuple[models.WorkspaceUser, bool]:
    """Return ``(membership, already_existed)``."""
    membership = (
        db.query(models.WorkspaceUser)
        .filter(
            models.WorkspaceUser.workspace_id == workspace_id,
            models.WorkspaceUser.user_id == user_id,
        )
        .first()
    )
    if membership is not None:
        return membership, True

    membership = models.WorkspaceUser(
        workspace_id=workspace_id,
        user_id=user_id,
        role=WorkspaceRole.CLIENT_READONLY,
    )
    db.add(membership)
    db.flush()
    return membership, False


def _ensure_project_access(
    db: Session,
    *,
    workspace_user_id: int,
    project_id: int,
) -> models.WorkspaceUserProjectAccess:
    """Create a project-access row if one does not already exist."""
    existing = (
        db.query(models.WorkspaceUserProjectAccess)
        .filter(
            models.WorkspaceUserProjectAccess.workspace_user_id == workspace_user_id,
            models.WorkspaceUserProjectAccess.project_id == project_id,
        )
        .first()
    )
    if existing is not None:
        return existing

    access = models.WorkspaceUserProjectAccess(
        workspace_user_id=workspace_user_id,
        project_id=project_id,
    )
    db.add(access)
    db.flush()
    return access


async def _try_send_invitation_email(
    db: Session,
    *,
    workspace: models.Workspace,
    user: models.User,
    project_names: list[str],
) -> bool:
    """Best-effort invitation email.  Returns ``True`` on success."""
    try:
        from services.auth_service import AuthService

        auth_service = AuthService(db)
        email_service = EmailService(db)

        invitation_token = auth_service.create_password_reset_token(user.email)
        frontend_base_url = _resolve_frontend_base_url()
        invitation_url = f"{frontend_base_url}/reset-password?token={invitation_token}&flow=invite"
        portal_url = f"{frontend_base_url}/portal"

        owner = workspace.owner
        agency_name = (
            (
                (owner.company_name or "").strip()
                or (owner.email.split("@", 1)[0] if owner and owner.email else "")
                or workspace.name
            )
            if owner
            else workspace.name
        )

        await email_service.send_client_invitation_email(
            user.email,
            invitation_url=invitation_url,
            workspace_name=workspace.name,
            portal_url=portal_url,
            agency_name=agency_name,
            project_names=project_names,
            user_id=user.id,
            invitee_name=user.company_name,
        )
        return True
    except Exception:
        logger.exception(
            "Failed to send invitation email to %s (workspace %s)",
            user.email,
            workspace.id,
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def onboard_client(
    db: Session,
    *,
    workspace: models.Workspace,
    project_name: str,
    domain_url: str | None = None,
    client_email: str,
    client_name: str | None = None,
    invited_by_user_id: int,
) -> dict[str, Any]:
    """Single-transaction client onboarding: project → user → membership → invite email."""

    # 1. Create project -------------------------------------------------------
    project = models.Project(
        workspace_id=workspace.id,
        name=project_name,
        domain_url=domain_url,
    )
    db.add(project)
    db.flush()

    # 2. Find or create client user -------------------------------------------
    user, is_new_user = _find_or_create_user(
        db,
        email=client_email,
        name=client_name,
    )

    # 3. Workspace membership + project access --------------------------------
    membership, _already_member = _ensure_workspace_membership(
        db,
        workspace_id=workspace.id,
        user_id=user.id,
    )
    _ensure_project_access(
        db,
        workspace_user_id=membership.id,
        project_id=project.id,
    )

    # 4. Invitation email (best-effort) ---------------------------------------
    await _try_send_invitation_email(
        db,
        workspace=workspace,
        user=user,
        project_names=[project.name],
    )

    # Let the caller commit.
    return {
        "project": project,
        "user": user,
        "membership": membership,
        "is_new_user": is_new_user,
    }


async def bulk_invite_clients(
    db: Session,
    *,
    workspace: models.Workspace,
    invitations: list[dict[str, Any]],
    invited_by_user_id: int,
) -> list[dict[str, Any]]:
    """Invite up to 50 clients.  Returns per-item success/failure list."""

    if len(invitations) > _MAX_BULK_INVITATIONS:
        raise ValueError(
            f"Too many invitations ({len(invitations)}); maximum is {_MAX_BULK_INVITATIONS}"
        )

    # Pre-fetch workspace project IDs for validation.
    workspace_project_ids: set[int] = {
        pid
        for (pid,) in db.query(models.Project.id).filter(
            models.Project.workspace_id == workspace.id,
        )
    }

    results: list[dict[str, Any]] = []

    for item in invitations:
        email: str = item.get("email", "").strip().lower()
        name: str | None = item.get("name")
        project_ids: list[int] = item.get("project_ids") or []

        if not email:
            results.append(
                {"email": email, "success": False, "error": "Missing email", "user_id": None}
            )
            continue

        try:
            # Validate requested project IDs belong to workspace.
            invalid_ids = set(project_ids) - workspace_project_ids
            if invalid_ids:
                raise ValueError(
                    f"Project IDs {sorted(invalid_ids)} do not belong to workspace {workspace.id}"
                )

            # Find or create user.
            user, _is_new = _find_or_create_user(db, email=email, name=name)

            # Ensure CLIENT_READONLY membership.
            membership, _already_member = _ensure_workspace_membership(
                db,
                workspace_id=workspace.id,
                user_id=user.id,
            )

            # Assign to requested projects.
            assigned_project_names: list[str] = []
            for pid in project_ids:
                _ensure_project_access(
                    db,
                    workspace_user_id=membership.id,
                    project_id=pid,
                )
                project = db.query(models.Project).get(pid)
                if project is not None:
                    assigned_project_names.append(project.name)

            # Best-effort invitation email.
            await _try_send_invitation_email(
                db,
                workspace=workspace,
                user=user,
                project_names=assigned_project_names,
            )

            results.append({"email": email, "success": True, "error": None, "user_id": user.id})

        except Exception as exc:
            logger.exception("Bulk-invite failed for %s", email)
            results.append({"email": email, "success": False, "error": str(exc), "user_id": None})

    # Let the caller commit.
    return results
