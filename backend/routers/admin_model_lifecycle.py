from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Annotated, Optional
from datetime import datetime, timezone
from pydantic import BaseModel

import models
from database import get_db
from auth.security import get_current_admin_user

router = APIRouter(
    prefix="/admin/model-lifecycle",
    tags=["admin-model-lifecycle"],
    dependencies=[Depends(get_current_admin_user)],
)

# ── Pydantic Models ────────────────────────────────────────────────────────


class AckBody(BaseModel):
    notes: Optional[str] = None


# ── Aggregate Stats ────────────────────────────────────────────────────────


@router.get("/stats")
def lifecycle_stats(db: Session = Depends(get_db)):
    """Aggregate counts for the KPI bar, not page-scoped."""
    MLA = models.ModelLifecycleAlert
    total = db.query(func.count(MLA.id)).scalar() or 0
    active = db.query(func.count(MLA.id)).filter(MLA.status == "active").scalar() or 0
    critical_unresolved = (
        db.query(func.count(MLA.id))
        .filter(MLA.severity == "critical", MLA.status != "resolved")
        .scalar()
        or 0
    )
    acknowledged = db.query(func.count(MLA.id)).filter(MLA.status == "acknowledged").scalar() or 0
    resolved = db.query(func.count(MLA.id)).filter(MLA.status == "resolved").scalar() or 0

    by_provider = dict(
        db.query(MLA.provider, func.count(MLA.id))
        .filter(MLA.status != "resolved")
        .group_by(MLA.provider)
        .all()
    )
    by_severity = dict(
        db.query(MLA.severity, func.count(MLA.id))
        .filter(MLA.status != "resolved")
        .group_by(MLA.severity)
        .all()
    )

    # Latest check timestamp from most recent snapshot
    MLS = models.ModelLifecycleSnapshot
    last_check = db.query(func.max(MLS.fetched_at)).scalar()

    return {
        "total": total,
        "active": active,
        "critical_unresolved": critical_unresolved,
        "acknowledged": acknowledged,
        "resolved": resolved,
        "by_provider": by_provider,
        "by_severity": by_severity,
        "last_check_at": last_check.isoformat() if last_check else None,
    }


# ── Lifecycle Alerts ───────────────────────────────────────────────────────


@router.get("/alerts")
def list_lifecycle_alerts(
    status: Optional[str] = Query(None, description="'active', 'acknowledged', 'resolved'"),
    provider: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(models.ModelLifecycleAlert).order_by(
        models.ModelLifecycleAlert.created_at.desc()
    )
    if status:
        query = query.filter(models.ModelLifecycleAlert.status == status)
    if provider:
        query = query.filter(models.ModelLifecycleAlert.provider == provider)
    if severity:
        query = query.filter(models.ModelLifecycleAlert.severity == severity)

    total = query.count()
    alerts = query.offset((page - 1) * page_size).limit(page_size).all()
    result = []
    for a in alerts:
        a_dict = {
            "id": a.id,
            "provider": a.provider,
            "alert_type": a.alert_type,
            "severity": a.severity,
            "title": a.title,
            "description": a.description,
            "affected_models": a.affected_models,
            "details": a.details,
            "source_url": a.source_url,
            "status": a.status,
            "acknowledged_by_id": a.acknowledged_by_id,
            "acknowledged_by_email": a.acknowledged_by.email if a.acknowledged_by else None,
            "acknowledged_at": a.acknowledged_at.isoformat() if a.acknowledged_at else None,
            "resolved_at": a.resolved_at.isoformat() if a.resolved_at else None,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "schema_version": a.schema_version,
        }
        result.append(a_dict)
    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.patch("/alerts/{alert_id}/ack")
def acknowledge_lifecycle_alert(
    alert_id: int,
    admin_user: Annotated[models.User, Depends(get_current_admin_user)],
    db: Session = Depends(get_db),
    body: AckBody = Body(default=AckBody()),
):
    alert = (
        db.query(models.ModelLifecycleAlert)
        .filter(models.ModelLifecycleAlert.id == alert_id)
        .first()
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status != "active":
        raise HTTPException(status_code=400, detail="Only active alerts can be acknowledged")

    alert.status = "acknowledged"
    alert.acknowledged_at = datetime.now(timezone.utc)
    alert.acknowledged_by_id = admin_user.id
    if body.notes:
        existing = alert.details if isinstance(alert.details, dict) else {}
        alert.details = {**existing, "ack_notes": body.notes}

    db.commit()
    return {"status": "acknowledged"}


@router.patch("/alerts/{alert_id}/resolve")
def resolve_lifecycle_alert(
    alert_id: int,
    db: Session = Depends(get_db),
):
    alert = (
        db.query(models.ModelLifecycleAlert)
        .filter(models.ModelLifecycleAlert.id == alert_id)
        .first()
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status not in ("active", "acknowledged"):
        raise HTTPException(
            status_code=400, detail="Only active or acknowledged alerts can be resolved"
        )

    alert.status = "resolved"
    alert.resolved_at = datetime.now(timezone.utc)

    db.commit()
    return {"status": "resolved"}


# ── Lifecycle Snapshots ────────────────────────────────────────────────────


@router.get("/snapshots")
def list_lifecycle_snapshots(
    provider: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(models.ModelLifecycleSnapshot).order_by(
        models.ModelLifecycleSnapshot.fetched_at.desc()
    )
    if provider:
        query = query.filter(models.ModelLifecycleSnapshot.provider == provider)

    total = query.count()
    snapshots = query.offset((page - 1) * page_size).limit(page_size).all()
    result = []
    for s in snapshots:
        s_dict = {
            "id": s.id,
            "provider": s.provider,
            "source_url": s.source_url,
            "page_type": s.page_type,
            "content_hash": s.content_hash,
            "extracted_models": s.extracted_models,
            "raw_text_excerpt": s.raw_text_excerpt,
            "fetched_at": s.fetched_at.isoformat() if s.fetched_at else None,
            "schema_version": s.schema_version,
        }
        result.append(s_dict)
    return {"items": result, "total": total, "page": page, "page_size": page_size}


# ── Sources & Manual Check ─────────────────────────────────────────────────


@router.get("/sources")
def list_monitored_sources():
    from services.model_lifecycle_monitor_service import MONITOR_SOURCES

    return MONITOR_SOURCES


@router.post("/check")
def trigger_lifecycle_check(db: Session = Depends(get_db)):
    from services.model_lifecycle_monitor_service import run_model_lifecycle_check

    summary = run_model_lifecycle_check(db)
    return summary
