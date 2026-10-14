from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from routers.workspace_router import (
    _build_connections_return_url,
    _build_oauth_callback_uri,
    _get_or_create_current_workspace,
    _require_workspace_write_access,
    _resolve_workspace_access,
)
from services.notification_router import NotificationRouter
from services.oauth_service import oauth
from app.services.compliance.plan_validator import PlanValidator


router = APIRouter(prefix="/integrations/slack", tags=["Slack Integration"])
logger = logging.getLogger(__name__)
plan_validator = PlanValidator()
SLACK_OAUTH_SESSION_KEY = "slack_oauth_state"


class SlackChannelResponse(BaseModel):
    id: str
    name: str


class SlackStatusResponse(BaseModel):
    is_connected: bool
    is_plan_locked: bool = False
    detail: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    bot_user_id: str | None = None
    default_channel_id: str | None = None
    default_channel_name: str | None = None
    scope: str | None = None
    updated_at: str | None = None


class SlackDefaultChannelRequest(BaseModel):
    channel_id: str = Field(min_length=1, max_length=120)
    channel_name: str | None = Field(default=None, max_length=120)

    @field_validator("channel_id", "channel_name")
    @classmethod
    def _normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class SlackTestRequest(BaseModel):
    channel_id: str | None = Field(default=None, max_length=120)

    @field_validator("channel_id")
    @classmethod
    def _normalize_channel_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def check_slack_access(user: models.User = Depends(get_current_user)) -> models.User:
    if not plan_validator.has_feature(user, "can_use_slack_integration"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Slack integrations require Specialist or higher.",
        )
    return user


def _serialize_status(connection: models.SlackConnection | None) -> SlackStatusResponse:
    if connection is None:
        return SlackStatusResponse(is_connected=False)
    return SlackStatusResponse(
        is_connected=True,
        team_id=connection.team_id,
        team_name=connection.team_name,
        bot_user_id=connection.bot_user_id,
        default_channel_id=connection.default_channel_id,
        default_channel_name=connection.default_channel_name,
        scope=connection.scope,
        updated_at=connection.updated_at.isoformat() if connection.updated_at else None,
    )


@router.get("/authorize", dependencies=[Depends(check_slack_access)])
async def slack_authorize(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not os.getenv("SLACK_CLIENT_ID"):
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Slack OAuth is not configured on the server.",
        )

    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    callback_url = _build_oauth_callback_uri(request, route_name="slack_oauth_callback")
    request.session[SLACK_OAUTH_SESSION_KEY] = {
        "workspace_id": workspace.id,
        "user_id": user.id,
    }
    return await oauth.slack.authorize_redirect(request, callback_url)


@router.get("/callback", name="slack_oauth_callback")
async def slack_callback(
    request: Request,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    state_payload = request.session.pop(SLACK_OAUTH_SESSION_KEY, None)
    if not state_payload:
        return RedirectResponse(
            url=_build_connections_return_url(
                provider="slack",
                status="error",
                message="Slack OAuth session expired.",
            )
        )

    try:
        workspace_id = int(state_payload["workspace_id"])
        if int(state_payload.get("user_id") or 0) != user.id:
            raise HTTPException(status_code=403, detail="Slack OAuth session user mismatch.")
        check_slack_access(user)
        _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace_id)
        _require_workspace_write_access(role)
        token = await oauth.slack.authorize_access_token(request)
        team_payload = token.get("team") if isinstance(token.get("team"), dict) else {}
        webhook_payload = (
            token.get("incoming_webhook") if isinstance(token.get("incoming_webhook"), dict) else {}
        )

        connection = (
            db.query(models.SlackConnection)
            .filter(models.SlackConnection.workspace_id == workspace_id)
            .first()
        )
        if connection is None:
            connection = models.SlackConnection(
                workspace_id=workspace_id,
                access_token=str(token.get("access_token") or ""),
                team_id=str(team_payload.get("id") or token.get("team_id") or ""),
            )
            db.add(connection)

        access_token = str(token.get("access_token") or "").strip()
        team_id = str(team_payload.get("id") or token.get("team_id") or "").strip()
        if not access_token or not team_id:
            raise ValueError("Slack OAuth response did not include the expected workspace token.")

        connection.access_token = access_token
        connection.team_id = team_id
        connection.team_name = str(team_payload.get("name") or "").strip() or None
        connection.bot_user_id = str(token.get("bot_user_id") or "").strip() or None
        connection.scope = str(token.get("scope") or "").strip() or None
        connection.incoming_webhook_url = (
            str(webhook_payload.get("url") or "").strip() or connection.incoming_webhook_url
        )
        incoming_channel_id = str(webhook_payload.get("channel_id") or "").strip() or None
        incoming_channel_name = str(webhook_payload.get("channel") or "").strip() or None
        if incoming_channel_id:
            connection.default_channel_id = incoming_channel_id
        if incoming_channel_name:
            connection.default_channel_name = incoming_channel_name

        db.commit()
        return RedirectResponse(
            url=_build_connections_return_url(provider="slack", status="connected")
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Slack OAuth callback failed: user_id=%s error_class=%s",
            user.id,
            type(exc).__name__,
        )
        return RedirectResponse(
            url=_build_connections_return_url(
                provider="slack",
                status="error",
                message="Slack connection could not be completed. Please try again.",
            )
        )


@router.get("/status", response_model=SlackStatusResponse)
def get_slack_status(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not plan_validator.has_feature(user, "can_use_slack_integration"):
        return SlackStatusResponse(
            is_connected=False,
            is_plan_locked=True,
            detail="Slack integrations require Specialist or higher.",
        )
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    connection = (
        db.query(models.SlackConnection)
        .filter(models.SlackConnection.workspace_id == workspace.id)
        .first()
    )
    return _serialize_status(connection)


@router.get(
    "/channels",
    response_model=list[SlackChannelResponse],
    dependencies=[Depends(check_slack_access)],
)
async def list_slack_channels(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    connection = (
        db.query(models.SlackConnection)
        .filter(models.SlackConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack is not connected for this workspace.")

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            "https://slack.com/api/conversations.list",
            headers={"Authorization": f"Bearer {connection.access_token}"},
            params={
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": "200",
            },
        )
        response.raise_for_status()
        payload: dict[str, Any] = response.json()

    if payload.get("ok") is not True:
        raise HTTPException(
            status_code=502, detail=payload.get("error") or "Failed to list Slack channels."
        )

    channels = payload.get("channels") if isinstance(payload.get("channels"), list) else []
    return [
        SlackChannelResponse(
            id=str(channel.get("id") or ""),
            name=str(channel.get("name") or channel.get("id") or ""),
        )
        for channel in channels
        if channel.get("id")
    ]


@router.put(
    "/default-channel",
    response_model=SlackStatusResponse,
    dependencies=[Depends(check_slack_access)],
)
def update_default_slack_channel(
    payload: SlackDefaultChannelRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    connection = (
        db.query(models.SlackConnection)
        .filter(models.SlackConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack is not connected for this workspace.")

    connection.default_channel_id = payload.channel_id
    connection.default_channel_name = payload.channel_name
    db.commit()
    db.refresh(connection)
    return _serialize_status(connection)


@router.post("/test", dependencies=[Depends(check_slack_access)])
def send_slack_test_message(
    payload: SlackTestRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    connection = (
        db.query(models.SlackConnection)
        .filter(models.SlackConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack is not connected for this workspace.")

    NotificationRouter(db).send_slack_message(
        connection=connection,
        event_key="audit.completed",
        context={
            "workspace_name": workspace.name,
            "message": "Slack integration test from Qiko Signal.",
        },
        channel_id=payload.channel_id,
    )
    return {"ok": True}


@router.delete(
    "/disconnect",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(check_slack_access)],
)
def disconnect_slack(
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workspace = _get_or_create_current_workspace(db, user)
    _, role = _resolve_workspace_access(db, user=user, workspace_id=workspace.id)
    _require_workspace_write_access(role)

    connection = (
        db.query(models.SlackConnection)
        .filter(models.SlackConnection.workspace_id == workspace.id)
        .first()
    )
    if connection is None:
        raise HTTPException(status_code=404, detail="Slack is not connected for this workspace.")

    db.delete(connection)
    db.commit()
    return None
