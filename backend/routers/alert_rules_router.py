"""Alert Rules API Router.

Provides endpoints for creating, reading, updating, and deleting Alert Rules
for continuous monitoring.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

import models
from database import get_db
from auth.security import get_current_user_from_token as get_current_user
from routers.workspace_router import _resolve_project_access, _require_workspace_write_access

router = APIRouter(prefix="/projects", tags=["Alert Rules"])

# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class AlertRuleCreate(BaseModel):
    metric: str = Field(
        ...,
        description=(
            "E.g., geo_score, seo_score, aeo_score, ai_visibility_score, "
            "aeo_mention_drop, featured_snippets_lost"
        ),
    )
    condition: str = Field(..., description="E.g., below, above, drops_by")
    threshold: float
    email_to: EmailStr
    is_active: bool = True


class AlertRuleUpdate(BaseModel):
    metric: Optional[str] = None
    condition: Optional[str] = None
    threshold: Optional[float] = None
    email_to: Optional[EmailStr] = None
    is_active: Optional[bool] = None


class AlertLogResponse(BaseModel):
    id: int
    rule_id: int
    triggered_at: datetime
    metric_value: float
    message: str


class AlertRuleResponse(BaseModel):
    id: int
    project_id: int
    metric: str
    condition: str
    threshold: float
    email_to: str
    is_active: bool
    last_triggered_at: Optional[datetime]
    created_at: datetime
    # We optionally return the latest logs
    recent_logs: List[AlertLogResponse] = []


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _verify_project_access_for_alerts(
    project_id: int, user: models.User, db: Session
) -> models.Project:
    project, _, _ = _resolve_project_access(db, user=user, project_id=project_id)
    return project


def _verify_project_edit_access(project_id: int, user: models.User, db: Session) -> models.Project:
    project, _, role = _resolve_project_access(db, user=user, project_id=project_id)
    _require_workspace_write_access(role)
    return project


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{project_id}/alerts", response_model=List[AlertRuleResponse])
def list_alert_rules(
    project_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all alert rules for a project."""
    _verify_project_access_for_alerts(project_id, user, db)

    rules = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.project_id == project_id)
        .order_by(models.AlertRule.created_at.desc())
        .all()
    )

    response_items = []
    for rule in rules:
        resp = AlertRuleResponse(
            id=rule.id,
            project_id=rule.project_id,
            metric=rule.metric,
            condition=rule.condition,
            threshold=rule.threshold,
            email_to=rule.email_to,
            is_active=rule.is_active,
            last_triggered_at=rule.last_triggered_at,
            created_at=rule.created_at,
            recent_logs=[
                AlertLogResponse(
                    id=log.id,
                    rule_id=log.rule_id,
                    triggered_at=log.triggered_at,
                    metric_value=log.metric_value,
                    message=log.message,
                )
                for log in rule.logs[
                    :5
                ]  # returns latest 5 logs if lazy loaded, though we should probably order them
            ],
        )
        response_items.append(resp)

    return response_items


@router.post("/{project_id}/alerts", response_model=AlertRuleResponse)
def create_alert_rule(
    project_id: int,
    payload: AlertRuleCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a new alert rule for a project."""
    _verify_project_edit_access(project_id, user, db)

    new_rule = models.AlertRule(
        project_id=project_id,
        metric=payload.metric,
        condition=payload.condition,
        threshold=payload.threshold,
        email_to=payload.email_to,
        is_active=payload.is_active,
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)

    return AlertRuleResponse(
        id=new_rule.id,
        project_id=new_rule.project_id,
        metric=new_rule.metric,
        condition=new_rule.condition,
        threshold=new_rule.threshold,
        email_to=new_rule.email_to,
        is_active=new_rule.is_active,
        last_triggered_at=new_rule.last_triggered_at,
        created_at=new_rule.created_at,
    )


@router.put("/{project_id}/alerts/{rule_id}", response_model=AlertRuleResponse)
def update_alert_rule(
    project_id: int,
    rule_id: int,
    payload: AlertRuleUpdate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update an existing alert rule."""
    _verify_project_edit_access(project_id, user, db)

    rule = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.id == rule_id, models.AlertRule.project_id == project_id)
        .first()
    )

    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    if payload.metric is not None:
        rule.metric = payload.metric
    if payload.condition is not None:
        rule.condition = payload.condition
    if payload.threshold is not None:
        rule.threshold = payload.threshold
    if payload.email_to is not None:
        rule.email_to = payload.email_to
    if payload.is_active is not None:
        rule.is_active = payload.is_active

    db.commit()
    db.refresh(rule)

    return AlertRuleResponse(
        id=rule.id,
        project_id=rule.project_id,
        metric=rule.metric,
        condition=rule.condition,
        threshold=rule.threshold,
        email_to=rule.email_to,
        is_active=rule.is_active,
        last_triggered_at=rule.last_triggered_at,
        created_at=rule.created_at,
    )


@router.delete("/{project_id}/alerts/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert_rule(
    project_id: int,
    rule_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete an alert rule."""
    _verify_project_edit_access(project_id, user, db)

    rule = (
        db.query(models.AlertRule)
        .filter(models.AlertRule.id == rule_id, models.AlertRule.project_id == project_id)
        .first()
    )

    if not rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    db.delete(rule)
    db.commit()
    return
