from datetime import datetime, timezone, timedelta

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import models
from app.schemas.scheduling import (
    ScheduledAuditCreate,
    merge_scheduled_audit_config,
    resolve_scheduled_audit_target_contract,
    ScheduledAuditResponse,
    ScheduledAuditUpdate,
)
from app.services.compliance.plan_validator import PlanValidator
from auth.security import get_current_user_from_token as get_current_user
from database import get_db
from services.workspace_rbac import require_workspace_write_access, resolve_project_access

router = APIRouter(prefix="/scheduled-audits", tags=["Scheduled Audits"])
plan_validator = PlanValidator()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _compute_next_run_at(*, frequency: str, anchor: datetime | None = None) -> datetime:
    now = anchor or _now_utc()
    normalized = (frequency or "weekly").strip().lower()
    if normalized == "monthly":
        return now + relativedelta(months=1)
    return now + timedelta(days=7)


def _resolve_project_for_schedule(
    *,
    db: Session,
    user: models.User,
    project_id: int,
    require_write: bool,
) -> models.Project:
    access = resolve_project_access(db, user=user, project_id=project_id)
    if require_write:
        require_workspace_write_access(access.role)
    return access.project


def _resolve_site_for_schedule(*, db: Session, user: models.User, site_id: int) -> models.Site:
    site = db.query(models.Site).filter(models.Site.id == site_id).first()
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found.")
    if site.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized for this site.")
    return site


def _ensure_can_schedule_audits(user: models.User) -> None:
    if plan_validator.can_schedule_audits(user):
        return

    detail = (
        "Automated scheduled audits are available only on Specialist and "
        "Executive. Please upgrade to continue."
    )
    if plan_validator.is_basic_plan(user):
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=detail)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def _ensure_unique_schedule(
    *,
    db: Session,
    user_id: int,
    project_id: int | None,
    site_id: int | None,
    exclude_schedule_id: int | None = None,
) -> None:
    query = db.query(models.ScheduledAudit).filter(models.ScheduledAudit.user_id == user_id)
    if exclude_schedule_id is not None:
        query = query.filter(models.ScheduledAudit.id != exclude_schedule_id)

    if project_id is not None:
        existing = query.filter(models.ScheduledAudit.project_id == project_id).first()
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="A scheduled audit already exists for this project."
            )

    if site_id is not None:
        existing = query.filter(models.ScheduledAudit.site_id == site_id).first()
        if existing is not None:
            raise HTTPException(
                status_code=409, detail="A scheduled audit already exists for this site."
            )


@router.post("", response_model=ScheduledAuditResponse, status_code=status.HTTP_201_CREATED)
def create_scheduled_audit(
    params: ScheduledAuditCreate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_can_schedule_audits(user)

    if params.project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=params.project_id,
            require_write=True,
        )
    if params.site_id is not None:
        _resolve_site_for_schedule(db=db, user=user, site_id=params.site_id)

    _ensure_unique_schedule(
        db=db,
        user_id=user.id,
        project_id=params.project_id,
        site_id=params.site_id,
    )
    resolved_contract = resolve_scheduled_audit_target_contract(
        url=params.url,
        project_id=params.project_id,
        site_id=params.site_id,
        audit_params=params.audit_params,
    )

    next_run_at = _compute_next_run_at(frequency=params.frequency)
    new_schedule = models.ScheduledAudit(
        user_id=user.id,
        project_id=resolved_contract["project_id"],
        site_id=resolved_contract["site_id"],
        url=resolved_contract["url"],
        audit_type=params.audit_type,
        frequency=params.frequency,
        audit_params=resolved_contract["audit_params"].model_dump(),
        is_active=params.is_active,
        next_run_at=next_run_at,
        paused_reason=None if params.is_active else models.ScheduledAuditPauseReason.MANUAL,
    )

    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    return new_schedule


@router.get("", response_model=list[ScheduledAuditResponse])
def list_scheduled_audits(
    project_id: int | None = Query(default=None),
    site_id: int | None = Query(default=None),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=project_id,
            require_write=False,
        )

    query = db.query(models.ScheduledAudit).filter(models.ScheduledAudit.user_id == user.id)
    if project_id is not None:
        query = query.filter(models.ScheduledAudit.project_id == project_id)
    if site_id is not None:
        query = query.filter(models.ScheduledAudit.site_id == site_id)
    return query.order_by(
        models.ScheduledAudit.next_run_at.asc(), models.ScheduledAudit.id.asc()
    ).all()


@router.get("/{schedule_id}", response_model=ScheduledAuditResponse)
def get_scheduled_audit(
    schedule_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(models.ScheduledAudit)
        .filter(models.ScheduledAudit.id == schedule_id, models.ScheduledAudit.user_id == user.id)
        .first()
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled audit not found.")
    if schedule.project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=schedule.project_id,
            require_write=False,
        )
    return schedule


@router.patch("/{schedule_id}", response_model=ScheduledAuditResponse)
def update_scheduled_audit(
    schedule_id: int,
    params: ScheduledAuditUpdate,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    schedule = (
        db.query(models.ScheduledAudit)
        .filter(models.ScheduledAudit.id == schedule_id, models.ScheduledAudit.user_id == user.id)
        .first()
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled audit not found.")
    if schedule.project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=schedule.project_id,
            require_write=True,
        )

    update_data = params.model_dump(exclude_unset=True)
    enabling_schedule = update_data.get("is_active") is True
    if enabling_schedule or any(
        key in update_data
        for key in ("frequency", "audit_params", "project_id", "site_id", "url", "audit_type")
    ):
        _ensure_can_schedule_audits(user)

    new_project_id = update_data.get("project_id", schedule.project_id)
    new_site_id = update_data.get("site_id", schedule.site_id)
    new_frequency = update_data.get("frequency", schedule.frequency)
    merged_audit_params = merge_scheduled_audit_config(
        schedule.audit_params,
        update_data.get("audit_params"),
    )

    if new_project_id is None and new_site_id is None:
        raise HTTPException(
            status_code=400, detail="Either project_id or site_id must be provided."
        )

    if new_project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=new_project_id,
            require_write=True,
        )
    if new_site_id is not None:
        _resolve_site_for_schedule(db=db, user=user, site_id=new_site_id)

    if new_project_id != schedule.project_id or new_site_id != schedule.site_id:
        _ensure_unique_schedule(
            db=db,
            user_id=user.id,
            project_id=new_project_id,
            site_id=new_site_id,
            exclude_schedule_id=schedule.id,
        )

    try:
        resolved_contract = resolve_scheduled_audit_target_contract(
            url=update_data.get("url", schedule.url),
            project_id=new_project_id,
            site_id=new_site_id,
            audit_params=merged_audit_params,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    schedule.url = resolved_contract["url"]
    schedule.audit_params = resolved_contract["audit_params"].model_dump()
    if "project_id" in update_data:
        schedule.project_id = new_project_id
    if "site_id" in update_data:
        schedule.site_id = new_site_id
    if "audit_type" in update_data:
        schedule.audit_type = update_data["audit_type"]
    if "frequency" in update_data:
        schedule.frequency = new_frequency
    if "is_active" in update_data:
        schedule.is_active = bool(update_data["is_active"])
        if schedule.is_active:
            schedule.paused_reason = None
            schedule.next_run_at = _compute_next_run_at(frequency=new_frequency)
        else:
            schedule.paused_reason = models.ScheduledAuditPauseReason.MANUAL
    elif "frequency" in update_data and schedule.is_active:
        schedule.next_run_at = _compute_next_run_at(frequency=new_frequency)

    db.commit()
    db.refresh(schedule)
    return schedule


@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scheduled_audit(
    schedule_id: int,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    schedule = (
        db.query(models.ScheduledAudit)
        .filter(models.ScheduledAudit.id == schedule_id, models.ScheduledAudit.user_id == user.id)
        .first()
    )
    if schedule is None:
        raise HTTPException(status_code=404, detail="Scheduled audit not found.")
    if schedule.project_id is not None:
        _resolve_project_for_schedule(
            db=db,
            user=user,
            project_id=schedule.project_id,
            require_write=True,
        )

    db.delete(schedule)
    db.commit()
