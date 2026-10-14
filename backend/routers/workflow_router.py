from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

import models
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from routers.workspace_router import _require_workspace_write_access, _resolve_project_access
from schemas.workflows import (
    WorkflowCreateRequest,
    WorkflowResponse,
    WorkflowRunResponse,
    WorkflowTestRequest,
    WorkflowTestResponse,
    WorkflowUpdateRequest,
)
from services.workflow_engine import WorkflowEngine, serialize_workflow, serialize_workflow_run
from app.config.plans import get_plan_capabilities
from services.project_intelligence_service import (
    require_project_feature_access,
    resolve_user_plan_alias,
)


router = APIRouter(tags=["Workflow Automations"])


def _require_workflow_access(user: models.User) -> dict[str, bool | int]:
    require_project_feature_access(user, "automations")
    plan_type = resolve_user_plan_alias(user)
    capabilities = get_plan_capabilities(plan_type)
    return capabilities


def _sample_event_key(trigger_config: dict[str, Any]) -> str:
    trigger_type = str(trigger_config.get("type") or "").strip().lower()
    if trigger_type == "platform_event":
        event_key = str(trigger_config.get("event_key") or "").strip()
        if event_key:
            return event_key
        event_keys = trigger_config.get("event_keys")
        if isinstance(event_keys, list):
            for item in event_keys:
                normalized = str(item).strip()
                if normalized:
                    return normalized
    if trigger_type == "audit_completed":
        return "audit.completed"
    return "alert.triggered"


def _sample_context(project: models.Project, payload_context: dict[str, Any]) -> dict[str, Any]:
    context = {
        "workspace_name": project.workspace.name if project.workspace else "Workspace",
        "project_name": project.name,
        "target_url": project.domain_url,
        "dashboard_url": f"/dashboard/projects/{project.id}",
        "metric_name": "geo_score",
        "metric_value": 64,
        "threshold": 70,
        "message": "Workflow test execution from the project automations panel.",
        "audit_tier": "smart",
    }
    context.update(payload_context)
    return context


@router.get("/projects/{project_id}/workflows", response_model=list[WorkflowResponse])
def list_workflows(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workflow_access(user)
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)
    workflows = (
        db.query(models.Workflow)
        .filter(models.Workflow.project_id == project.id)
        .order_by(models.Workflow.created_at.asc(), models.Workflow.id.asc())
        .all()
    )
    return [WorkflowResponse.model_validate(serialize_workflow(workflow)) for workflow in workflows]


@router.post("/projects/{project_id}/workflows", response_model=WorkflowResponse)
def create_workflow(
    project_id: int,
    payload: WorkflowCreateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    capabilities = _require_workflow_access(user)
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    max_workflows = capabilities.get("max_workflows_per_project")
    existing_count = (
        db.query(models.Workflow).filter(models.Workflow.project_id == project.id).count()
    )
    if isinstance(max_workflows, int) and max_workflows >= 0 and existing_count >= max_workflows:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Your plan allows up to {max_workflows} workflows per project.",
        )

    workflow = models.Workflow(
        workspace_id=project.workspace_id,
        project_id=project.id,
        created_by_user_id=user.id,
        name=payload.name,
        description=payload.description,
        trigger_config=payload.trigger_config.model_dump(exclude_none=True),
        actions_config=[action.model_dump(exclude_none=True) for action in payload.actions_config],
        cooldown_minutes=payload.cooldown_minutes,
        is_active=payload.is_active,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return WorkflowResponse.model_validate(serialize_workflow(workflow))


@router.put("/projects/{project_id}/workflows/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    project_id: int,
    workflow_id: int,
    payload: WorkflowUpdateRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workflow_access(user)
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    if payload.name is not None:
        workflow.name = payload.name
    if payload.description is not None or "description" in payload.model_fields_set:
        workflow.description = payload.description
    if payload.trigger_config is not None:
        workflow.trigger_config = payload.trigger_config.model_dump(exclude_none=True)
    if payload.actions_config is not None:
        workflow.actions_config = [
            action.model_dump(exclude_none=True) for action in payload.actions_config
        ]
    if payload.cooldown_minutes is not None:
        workflow.cooldown_minutes = payload.cooldown_minutes
    if payload.is_active is not None:
        workflow.is_active = payload.is_active

    db.commit()
    db.refresh(workflow)
    return WorkflowResponse.model_validate(serialize_workflow(workflow))


@router.delete(
    "/projects/{project_id}/workflows/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workflow(
    project_id: int,
    workflow_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workflow_access(user)
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    db.delete(workflow)
    db.commit()
    return None


@router.post(
    "/projects/{project_id}/workflows/{workflow_id}/test", response_model=WorkflowTestResponse
)
def test_workflow(
    project_id: int,
    workflow_id: int,
    payload: WorkflowTestRequest,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workflow_access(user)
    project, _workspace, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)

    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    engine = WorkflowEngine(db)
    run = engine.execute_workflow(
        workflow=workflow,
        event_key=_sample_event_key(dict(workflow.trigger_config or {})),
        context=_sample_context(project, payload.context),
    )
    return WorkflowTestResponse(run=WorkflowRunResponse.model_validate(serialize_workflow_run(run)))


@router.get(
    "/projects/{project_id}/workflows/{workflow_id}/runs", response_model=list[WorkflowRunResponse]
)
def list_workflow_runs(
    project_id: int,
    workflow_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_workflow_access(user)
    project, _workspace, _role = _resolve_project_access(db, user=user, project_id=project_id)

    workflow = (
        db.query(models.Workflow)
        .filter(models.Workflow.id == workflow_id, models.Workflow.project_id == project.id)
        .first()
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")

    runs = (
        db.query(models.WorkflowRun)
        .filter(models.WorkflowRun.workflow_id == workflow.id)
        .order_by(models.WorkflowRun.triggered_at.desc(), models.WorkflowRun.id.desc())
        .limit(20)
        .all()
    )
    return [WorkflowRunResponse.model_validate(serialize_workflow_run(run)) for run in runs]
