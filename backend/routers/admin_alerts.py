from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Annotated, Optional
from datetime import datetime
from pydantic import BaseModel, Field

import models
from database import get_db
from auth.security import get_current_admin_user

router = APIRouter(
    prefix="/admin/alerts", tags=["admin-alerts"], dependencies=[Depends(get_current_admin_user)]
)

# ── Pydantic Models ────────────────────────────────────────────────────────


class AlertRuleCreate(BaseModel):
    name: str
    description: Optional[str] = None
    metric_key: str
    condition: str
    threshold_value: float
    time_window_minutes: int = 5
    cooldown_minutes: int = 60
    severity: str = "warning"
    is_active: bool = True
    notification_channel_ids: List[int] = Field(default_factory=list)


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    metric_key: Optional[str] = None
    condition: Optional[str] = None
    threshold_value: Optional[float] = None
    time_window_minutes: Optional[int] = None
    cooldown_minutes: Optional[int] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None
    notification_channel_ids: Optional[List[int]] = None


class NotificationChannelCreate(BaseModel):
    name: str
    channel_type: str
    config_json: dict
    is_active: bool = True


class AlertEventAck(BaseModel):
    notes: Optional[str] = None


# ── Alert Rules ────────────────────────────────────────────────────────────


@router.get("/rules")
def list_alert_rules(db: Session = Depends(get_db)):
    rules = db.query(models.AdminAlertRule).all()
    # Serialize rules and their connected channels
    result = []
    for r in rules:
        r_dict = {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "metric_key": r.metric_key,
            "condition": r.condition,
            "threshold_value": r.threshold_value,
            "time_window_minutes": r.time_window_minutes,
            "cooldown_minutes": r.cooldown_minutes,
            "severity": r.severity,
            "is_active": r.is_active,
            "channels": [{"id": c.id, "name": c.name, "type": c.channel_type} for c in r.channels],
        }
        result.append(r_dict)
    return result


@router.post("/rules")
def create_alert_rule(rule: AlertRuleCreate, db: Session = Depends(get_db)):
    db_rule = models.AdminAlertRule(
        name=rule.name,
        description=rule.description,
        metric_key=rule.metric_key,
        condition=rule.condition,
        threshold_value=rule.threshold_value,
        time_window_minutes=rule.time_window_minutes,
        cooldown_minutes=rule.cooldown_minutes,
        severity=rule.severity,
        is_active=rule.is_active,
    )
    if rule.notification_channel_ids:
        channels = (
            db.query(models.AdminNotificationChannel)
            .filter(models.AdminNotificationChannel.id.in_(rule.notification_channel_ids))
            .all()
        )
        db_rule.channels = channels

    db.add(db_rule)
    db.commit()
    db.refresh(db_rule)
    return {"id": db_rule.id, "status": "created"}


@router.put("/rules/{rule_id}")
def update_alert_rule(rule_id: int, updates: AlertRuleUpdate, db: Session = Depends(get_db)):
    db_rule = db.query(models.AdminAlertRule).filter(models.AdminAlertRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")

    update_data = updates.model_dump(exclude_unset=True)
    channel_ids = update_data.pop("notification_channel_ids", None)

    for key, value in update_data.items():
        setattr(db_rule, key, value)

    if channel_ids is not None:
        channels = (
            db.query(models.AdminNotificationChannel)
            .filter(models.AdminNotificationChannel.id.in_(channel_ids))
            .all()
        )
        db_rule.channels = channels

    db.commit()
    return {"id": db_rule.id, "status": "updated"}


@router.delete("/rules/{rule_id}")
def delete_alert_rule(rule_id: int, db: Session = Depends(get_db)):
    db_rule = db.query(models.AdminAlertRule).filter(models.AdminAlertRule.id == rule_id).first()
    if not db_rule:
        raise HTTPException(status_code=404, detail="Alert rule not found")
    db.delete(db_rule)
    db.commit()
    return {"status": "deleted"}


# ── Alert Events ───────────────────────────────────────────────────────────


@router.get("/events")
def list_alert_events(
    status: Optional[str] = Query(None, description="'active', 'resolved', 'acknowledged'"),
    limit: int = 50,
    db: Session = Depends(get_db),
):
    query = db.query(models.AdminAlertEvent).order_by(models.AdminAlertEvent.triggered_at.desc())
    if status:
        query = query.filter(models.AdminAlertEvent.status == status)

    events = query.limit(limit).all()
    result = []
    for e in events:
        e_dict = {
            "id": e.id,
            "rule_id": e.rule_id,
            "rule_name": e.rule.name if e.rule else "Unknown Rule",
            "metric_key": e.metric_key,
            "current_value": e.current_value,
            "context_info": e.context_info,
            "triggered_at": e.triggered_at.isoformat() if e.triggered_at else None,
            "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
            "status": e.status,
            "acknowledged_at": e.acknowledged_at.isoformat() if e.acknowledged_at else None,
            "acknowledged_by": e.acknowledged_by,
            "notes": e.notes,
        }
        result.append(e_dict)
    return result


@router.patch("/events/{event_id}/ack")
def acknowledge_alert_event(
    event_id: int,
    body: AlertEventAck,
    admin_user: Annotated[models.User, Depends(get_current_admin_user)],
    db: Session = Depends(get_db),
):
    event = db.query(models.AdminAlertEvent).filter(models.AdminAlertEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    if event.status != "active":
        raise HTTPException(status_code=400, detail="Only active events can be acknowledged")

    event.status = "acknowledged"
    from datetime import timezone

    event.acknowledged_at = datetime.now(timezone.utc)
    event.acknowledged_by = admin_user.email
    if body.notes:
        event.notes = body.notes

    db.commit()
    return {"status": "acknowledged"}


# ── Notification Channels ──────────────────────────────────────────────────


@router.get("/channels")
def list_channels(db: Session = Depends(get_db)):
    channels = db.query(models.AdminNotificationChannel).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "channel_type": c.channel_type,
            "config": c.config_json,
            "is_active": c.is_active,
        }
        for c in channels
    ]


@router.post("/channels")
def create_channel(channel: NotificationChannelCreate, db: Session = Depends(get_db)):
    if channel.channel_type not in ["email", "slack"]:
        raise HTTPException(status_code=400, detail="Invalid channel type")

    db_channel = models.AdminNotificationChannel(
        name=channel.name,
        channel_type=channel.channel_type,
        config_json=channel.config_json,
        is_active=channel.is_active,
    )
    db.add(db_channel)
    db.commit()
    db.refresh(db_channel)
    return {"id": db_channel.id, "status": "created"}


@router.delete("/channels/{channel_id}")
def delete_channel(channel_id: int, db: Session = Depends(get_db)):
    db_channel = (
        db.query(models.AdminNotificationChannel)
        .filter(models.AdminNotificationChannel.id == channel_id)
        .first()
    )
    if not db_channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    db.delete(db_channel)
    db.commit()
    return {"status": "deleted"}
