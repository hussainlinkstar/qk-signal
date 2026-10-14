from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from services.cms_fix_delivery_service import (
    CMS_CONFIRMATION_TOKEN_TTL_SECONDS,
    create_or_update_connection,
    delete_connection,
    get_project_connection_or_404,
    get_task_deployment_log_or_404,
    list_project_connections,
    list_project_deployment_logs,
    normalize_site_url,
    preview_task_change,
    push_task_change,
    redact_credentials,
    require_cms_push_plan,
    rollback_task_change,
    verify_connection,
)
from services.workspace_rbac import require_workspace_write_access, resolve_project_access


router = APIRouter(prefix="/api/v1", tags=["CMS Fix Delivery"])


class CMSConnectRequest(BaseModel):
    cms_type: str = Field(min_length=2, max_length=32)
    site_url: str = Field(min_length=8, max_length=500)
    credentials: dict[str, str] = Field(default_factory=dict)

    @field_validator("cms_type")
    @classmethod
    def validate_cms_type(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"wordpress", "shopify"}:
            raise ValueError("CMS type must be wordpress or shopify.")
        return normalized

    @field_validator("site_url")
    @classmethod
    def validate_site_url(cls, value: str) -> str:
        return normalize_site_url(value)


class CMSConnectionResponse(BaseModel):
    id: int
    project_id: int
    workspace_id: int
    cms_type: str
    site_url: str
    status: str
    last_verified_at: str | None = None
    schema_version: str
    created_at: str | None = None
    updated_at: str | None = None
    credentials_preview: dict[str, str] = Field(default_factory=dict)


class CMSPreviewResponse(BaseModel):
    task_id: int
    project_id: int
    connection_id: int
    page_url: str
    field: str
    current_value: str | None
    proposed_value: str
    diff_html: str
    confirmation_token: str
    confirmation_expires_in_seconds: int


class CMSPushRequest(BaseModel):
    connection_id: int
    page_url: str = Field(min_length=8, max_length=2000)
    field: str = Field(min_length=2, max_length=64)
    confirmation_token: str = Field(min_length=10, max_length=2000)
    new_value: str | None = Field(default=None, max_length=20000)


class CMSRollbackRequest(BaseModel):
    connection_id: int
    deployment_log_id: int | None = None


class CMSDeploymentLogResponse(BaseModel):
    id: int
    project_task_id: int | None
    cms_connection_id: int | None
    initiated_by: int | None
    page_url: str
    field_changed: str
    value_before: str | None
    value_after: str
    cms_revision_id: str | None
    status: str
    pushed_at: str | None
    rolled_back_at: str | None
    error_message: str | None
    schema_version: str
    created_at: str | None


class CMSPushResponse(BaseModel):
    success: bool
    task_id: int
    project_id: int
    connection_id: int
    deployment_log: CMSDeploymentLogResponse
    revision_id: str | None
    error_message: str | None


def _isoformat(value) -> str | None:
    return value.isoformat() if value else None


def _serialize_connection(connection: models.CMSConnection) -> CMSConnectionResponse:
    return CMSConnectionResponse(
        id=connection.id,
        project_id=connection.project_id,
        workspace_id=connection.workspace_id,
        cms_type=connection.cms_type,
        site_url=connection.site_url,
        status=connection.status,
        last_verified_at=_isoformat(connection.last_verified_at),
        schema_version=connection.schema_version,
        created_at=_isoformat(connection.created_at),
        updated_at=_isoformat(connection.updated_at),
        credentials_preview=redact_credentials(connection.credentials_json),
    )


def _serialize_log(log: models.CMSDeploymentLog) -> CMSDeploymentLogResponse:
    return CMSDeploymentLogResponse(
        id=log.id,
        project_task_id=log.project_task_id,
        cms_connection_id=log.cms_connection_id,
        initiated_by=log.initiated_by,
        page_url=log.page_url,
        field_changed=log.field_changed,
        value_before=log.value_before,
        value_after=log.value_after,
        cms_revision_id=log.cms_revision_id,
        status=log.status,
        pushed_at=_isoformat(log.pushed_at),
        rolled_back_at=_isoformat(log.rolled_back_at),
        error_message=log.error_message,
        schema_version=log.schema_version,
        created_at=_isoformat(log.created_at),
    )


def _get_task_or_404(db: Session, *, task_id: int) -> models.ProjectTask:
    task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Project task not found.")
    return task


@router.post(
    "/projects/{project_id}/cms/connect",
    response_model=CMSConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def connect_project_cms(
    project_id: int,
    payload: CMSConnectRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)

    try:
        connection = create_or_update_connection(
            db,
            project=access.project,
            cms_type=payload.cms_type,
            site_url=payload.site_url,
            credentials=payload.credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _serialize_connection(connection)


@router.get(
    "/projects/{project_id}/cms/connections",
    response_model=list[CMSConnectionResponse],
)
def list_connections(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    rows = list_project_connections(db, project_id=access.project.id)
    return [_serialize_connection(row) for row in rows]


@router.post(
    "/projects/{project_id}/cms/connections/{connection_id}/verify",
    response_model=CMSConnectionResponse,
)
async def verify_project_connection(
    project_id: int,
    connection_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    connection = get_project_connection_or_404(
        db, project_id=access.project.id, connection_id=connection_id
    )
    connection = await verify_connection(db, connection=connection)
    return _serialize_connection(connection)


@router.delete(
    "/projects/{project_id}/cms/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_project_connection(
    project_id: int,
    connection_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    connection = get_project_connection_or_404(
        db, project_id=access.project.id, connection_id=connection_id
    )
    delete_connection(db, connection=connection)
    return None


@router.get(
    "/tasks/{task_id}/cms/preview",
    response_model=CMSPreviewResponse,
)
async def preview_task_cms_change(
    task_id: int,
    connection_id: int = Query(..., ge=1),
    page_url: str = Query(..., min_length=8, max_length=2000),
    field: str = Query(..., min_length=2, max_length=64),
    new_value: str | None = Query(default=None, max_length=20000),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_cms_push_plan(user)
    task = _get_task_or_404(db, task_id=task_id)
    access = resolve_project_access(
        db, user=user, project_id=task.project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    connection = get_project_connection_or_404(
        db, project_id=access.project.id, connection_id=connection_id
    )

    try:
        preview_result = await preview_task_change(
            db,
            task=task,
            connection=connection,
            page_url=page_url,
            field=field,
            explicit_value=new_value,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CMSPreviewResponse(
        task_id=task.id,
        project_id=task.project_id,
        connection_id=connection.id,
        page_url=preview_result.preview.page_url,
        field=preview_result.preview.field,
        current_value=preview_result.preview.current_value,
        proposed_value=preview_result.preview.proposed_value,
        diff_html=preview_result.preview.diff_html,
        confirmation_token=preview_result.confirmation_token,
        confirmation_expires_in_seconds=CMS_CONFIRMATION_TOKEN_TTL_SECONDS,
    )


@router.post(
    "/tasks/{task_id}/cms/push",
    response_model=CMSPushResponse,
)
async def push_task_cms_change(
    task_id: int,
    payload: CMSPushRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_cms_push_plan(user)
    task = _get_task_or_404(db, task_id=task_id)
    access = resolve_project_access(
        db, user=user, project_id=task.project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    connection = get_project_connection_or_404(
        db,
        project_id=access.project.id,
        connection_id=payload.connection_id,
    )

    try:
        deployment_log, push_result = await push_task_change(
            db,
            task=task,
            connection=connection,
            initiated_by_user_id=user.id,
            page_url=payload.page_url,
            field=payload.field,
            explicit_value=payload.new_value,
            confirmation_token=payload.confirmation_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CMSPushResponse(
        success=push_result.success,
        task_id=task.id,
        project_id=task.project_id,
        connection_id=connection.id,
        deployment_log=_serialize_log(deployment_log),
        revision_id=push_result.revision_id,
        error_message=push_result.error_message,
    )


@router.post(
    "/tasks/{task_id}/cms/rollback",
    response_model=CMSPushResponse,
)
async def rollback_task_cms_change(
    task_id: int,
    payload: CMSRollbackRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    require_cms_push_plan(user)
    task = _get_task_or_404(db, task_id=task_id)
    access = resolve_project_access(
        db, user=user, project_id=task.project_id, allow_client_readonly=False
    )
    require_workspace_write_access(access.role)
    connection = get_project_connection_or_404(
        db,
        project_id=access.project.id,
        connection_id=payload.connection_id,
    )
    source_log = get_task_deployment_log_or_404(
        db,
        task_id=task.id,
        connection_id=connection.id,
        deployment_log_id=payload.deployment_log_id,
    )

    deployment_log, push_result = await rollback_task_change(
        db,
        task=task,
        connection=connection,
        initiated_by_user_id=user.id,
        source_log=source_log,
    )

    return CMSPushResponse(
        success=push_result.success,
        task_id=task.id,
        project_id=task.project_id,
        connection_id=connection.id,
        deployment_log=_serialize_log(deployment_log),
        revision_id=push_result.revision_id,
        error_message=push_result.error_message,
    )


@router.get(
    "/projects/{project_id}/cms/deployment-log",
    response_model=list[CMSDeploymentLogResponse],
)
def list_project_cms_deployment_log(
    project_id: int,
    task_id: int | None = Query(default=None, ge=1),
    connection_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    access = resolve_project_access(
        db, user=user, project_id=project_id, allow_client_readonly=True
    )
    rows = list_project_deployment_logs(
        db,
        project_id=access.project.id,
        task_id=task_id,
        connection_id=connection_id,
        limit=limit,
    )
    return [_serialize_log(row) for row in rows]
