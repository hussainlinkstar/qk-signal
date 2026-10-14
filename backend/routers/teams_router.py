from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from routers.workspace_router import (
    _get_or_create_current_workspace,
    _require_workspace_write_access,
    _resolve_workspace_access,
)
from services.notification_router import NotificationRouter
from app.services.compliance.plan_validator import PlanValidator


router = APIRouter(prefix="/integrations/teams", tags=["Teams Integration"])
plan_validator = PlanValidator()


class TeamsConnectionRequest(BaseModel):
    webhook_url: str = Field(min_length=1, max_length=4000)
    channel_name: str | None = Field(default=None, max_length=120)

    @field_validator("webhook_url", "channel_name")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TeamsStatusResponse(BaseModel):
    is_connected: bool
    is_plan_locked: bool = False
    detail: str | None = None
    channel_name: str | None = None
    webhook_preview: str | None = None
    updated_at: str | None = None


def _mask_webhook(value: str | None) -> str | None:
    normalized = (value or "").strip()
    if len(normalized) <= 12:
        return normalized or None
    return f"{normalized[:8]}...{normalized[-4:]}"


def check_teams_access(user: models.User = Depends(get_current_user)) -> models.User:
    if not plan_validator.has_feature(user, "can_use_teams_integration"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Microsoft Teams integrations require Specialist or higher.",
        )
    return user


def _serialize_status(connection: models.TeamsConnection | None) -> TeamsStatusResponse:
    if connection is None:
        return TeamsStatusResponse(is_connected=False)
    return TeamsStatusResponse(
        is_connected=True,
        channel_name=connection.channel_name,
        webhook_preview=_mask_webhook(connection.webhook_url),
        updated_at=connection.updated_at.isoformat() if connection.updated_at else None,
    )


@router.post(
    "/connect", response_model=TeamsStatusResponse, dependencies=[Depends(check_teams_access)]
)
def connect_teams(
    payload: TeamsConnectionRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    connection = (
        db.query(models.TeamsConnection)
        .filter(models.TeamsConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        connection = models.TeamsConnection(
            workspace_id=workspace.id,
            webhook_url=payload.webhook_url,
        )
        db.add(connection)

    connection.webhook_url = payload.webhook_url
    connection.channel_name = payload.channel_name
    db.commit()
    db.refresh(connection)
    return _serialize_status(connection)


@router.get("/status", response_model=TeamsStatusResponse)
def get_teams_status(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not plan_validator.has_feature(user, "can_use_teams_integration"):
        return TeamsStatusResponse(
            is_connected=False,
            is_plan_locked=True,
            detail="Microsoft Teams integrations require Specialist or higher.",
        )
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    connection = (
        db.query(models.TeamsConnection)
        .filter(models.TeamsConnection.workspace_id == workspace.id)
        .first()
    )
    return _serialize_status(connection)


@router.post("/test", dependencies=[Depends(check_teams_access)])
def send_teams_test_message(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)
    connection = (
        db.query(models.TeamsConnection)
        .filter(models.TeamsConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Teams is not connected for this workspace.")

    NotificationRouter(db).send_teams_message(
        connection=connection,
        event_key="audit.completed",
        context={
            "workspace_name": workspace.name,
            "message": "Microsoft Teams integration test from Qiko Signal.",
        },
    )
    return {"ok": True}


@router.delete(
    "/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(check_teams_access)],
)
def disconnect_teams(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    connection = (
        db.query(models.TeamsConnection)
        .filter(models.TeamsConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Teams is not connected for this workspace.")

    db.delete(connection)
    db.commit()
    return None
