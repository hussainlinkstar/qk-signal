from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

DEFAULT_CYCLE_ANCHOR_DAY = 1
MAX_CYCLE_ANCHOR_DAY = 28
DEFAULT_HISTORY_PERIODS = 6
WARNING_THRESHOLD_RATIO = 0.8


@dataclass(frozen=True)
class BudgetPeriodWindow:
    period_start: date
    period_end: date


@dataclass(frozen=True)
class ProjectBudgetSnapshot:
    project_id: int
    monthly_limit_scans: int | None
    cycle_anchor_day: int
    current_period_start: date
    current_period_end: date
    consumed_scans: int
    remaining_scans: int | None
    percent_consumed: float | None
    status: Literal["unlimited", "healthy", "warning", "exhausted"]
    warning_threshold_reached: bool
    limit_reached: bool


@dataclass(frozen=True)
class ProjectScanConsumptionResult:
    status: Literal["consumed", "budget_exceeded"]
    project_id: int
    scans: int
    monthly_limit_scans: int | None
    cycle_anchor_day: int
    period_start: date
    period_end: date
    consumed_scans: int
    remaining_scans: int | None
    percent_consumed: float | None
    threshold_events: tuple[Literal["warning_80", "limit_reached"], ...] = ()


def normalize_cycle_anchor_day(value: int | None) -> int:
    try:
        normalized = int(value or DEFAULT_CYCLE_ANCHOR_DAY)
    except (TypeError, ValueError):
        normalized = DEFAULT_CYCLE_ANCHOR_DAY
    return max(DEFAULT_CYCLE_ANCHOR_DAY, min(MAX_CYCLE_ANCHOR_DAY, normalized))


def _next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _previous_month_start(value: date) -> date:
    if value.month == 1:
        return date(value.year - 1, 12, 1)
    return date(value.year, value.month - 1, 1)


def resolve_budget_period_window(
    reference_at: datetime | None = None, cycle_anchor_day: int | None = None
) -> BudgetPeriodWindow:
    resolved_reference = (
        reference_at.astimezone(timezone.utc) if reference_at else datetime.now(timezone.utc)
    )
    resolved_anchor_day = normalize_cycle_anchor_day(cycle_anchor_day)
    reference_date = resolved_reference.date()
    month_start = date(reference_date.year, reference_date.month, 1)

    if reference_date.day >= resolved_anchor_day:
        period_start = month_start.replace(day=resolved_anchor_day)
    else:
        period_start = _previous_month_start(month_start).replace(day=resolved_anchor_day)

    period_end = _next_month_start(period_start.replace(day=1)).replace(day=resolved_anchor_day)
    return BudgetPeriodWindow(period_start=period_start, period_end=period_end)


def _calculate_remaining_scans(monthly_limit_scans: int | None, consumed_scans: int) -> int | None:
    if monthly_limit_scans is None:
        return None
    return max(0, int(monthly_limit_scans) - int(consumed_scans))


def _calculate_percent_consumed(
    monthly_limit_scans: int | None, consumed_scans: int
) -> float | None:
    if monthly_limit_scans is None or monthly_limit_scans <= 0:
        if monthly_limit_scans == 0:
            return 100.0 if consumed_scans >= 0 else 0.0
        return None
    return min(100.0, round((max(0, consumed_scans) / monthly_limit_scans) * 100, 2))


def _resolve_snapshot_status(
    monthly_limit_scans: int | None, consumed_scans: int
) -> Literal["unlimited", "healthy", "warning", "exhausted"]:
    if monthly_limit_scans is None:
        return "unlimited"
    if monthly_limit_scans == 0:
        return "exhausted"
    percent_consumed = _calculate_percent_consumed(monthly_limit_scans, consumed_scans) or 0.0
    if consumed_scans >= monthly_limit_scans:
        return "exhausted"
    if percent_consumed >= WARNING_THRESHOLD_RATIO * 100:
        return "warning"
    return "healthy"


def serialize_usage_period(row: models.ProjectBudgetUsagePeriod) -> dict[str, object]:
    remaining = _calculate_remaining_scans(row.budget_limit_scans, int(row.consumed_scans or 0))
    percent = _calculate_percent_consumed(row.budget_limit_scans, int(row.consumed_scans or 0))
    return {
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "cycle_anchor_day": int(row.cycle_anchor_day or DEFAULT_CYCLE_ANCHOR_DAY),
        "budget_limit_scans": int(row.budget_limit_scans)
        if row.budget_limit_scans is not None
        else None,
        "consumed_scans": int(row.consumed_scans or 0),
        "remaining_scans": remaining,
        "percent_consumed": percent,
        "warning_threshold_reached": bool(
            row.warning_threshold_sent_at
            or (
                row.budget_limit_scans is not None
                and row.budget_limit_scans > 0
                and int(row.consumed_scans or 0) >= row.budget_limit_scans * WARNING_THRESHOLD_RATIO
            )
        ),
        "limit_reached": bool(
            row.limit_reached_sent_at
            or (
                row.budget_limit_scans is not None
                and int(row.consumed_scans or 0) >= row.budget_limit_scans
            )
        ),
        "status": _resolve_snapshot_status(row.budget_limit_scans, int(row.consumed_scans or 0)),
    }


def _usage_query(db: Session, *, project_id: int):
    query = db.query(models.ProjectBudgetUsagePeriod).filter(
        models.ProjectBudgetUsagePeriod.project_id == project_id,
    )
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()
    return query


def _get_budget_config(db: Session, *, project_id: int) -> models.ProjectBudget | None:
    query = db.query(models.ProjectBudget).filter(models.ProjectBudget.project_id == project_id)
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update()
    return query.first()


def _ensure_usage_row(
    db: Session,
    *,
    project_id: int,
    window: BudgetPeriodWindow,
    cycle_anchor_day: int,
    budget_limit_scans: int | None,
) -> models.ProjectBudgetUsagePeriod:
    table = models.ProjectBudgetUsagePeriod.__table__
    values = {
        "project_id": project_id,
        "period_start": window.period_start,
        "period_end": window.period_end,
        "cycle_anchor_day": cycle_anchor_day,
        "budget_limit_scans": budget_limit_scans,
        "consumed_scans": 0,
    }

    dialect_name = db.get_bind().dialect.name if db.get_bind() is not None else ""
    if dialect_name == "postgresql":
        db.execute(
            pg_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["project_id", "period_start"])
        )
    elif dialect_name == "sqlite":
        db.execute(
            sqlite_insert(table)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["project_id", "period_start"])
        )
    else:
        existing = (
            _usage_query(db, project_id=project_id)
            .filter(models.ProjectBudgetUsagePeriod.period_start == window.period_start)
            .first()
        )
        if existing is not None:
            return existing
        db.add(models.ProjectBudgetUsagePeriod(**values))

    db.flush()
    usage = (
        _usage_query(db, project_id=project_id)
        .filter(models.ProjectBudgetUsagePeriod.period_start == window.period_start)
        .first()
    )
    if usage is None:
        raise RuntimeError(f"Failed to resolve budget usage row for project {project_id}.")

    usage.period_end = window.period_end
    usage.cycle_anchor_day = cycle_anchor_day
    usage.budget_limit_scans = budget_limit_scans
    return usage


def _build_snapshot(
    *,
    project_id: int,
    monthly_limit_scans: int | None,
    cycle_anchor_day: int,
    consumed_scans: int,
    window: BudgetPeriodWindow,
) -> ProjectBudgetSnapshot:
    remaining = _calculate_remaining_scans(monthly_limit_scans, consumed_scans)
    percent_consumed = _calculate_percent_consumed(monthly_limit_scans, consumed_scans)
    warning_threshold_reached = bool(
        monthly_limit_scans is not None
        and monthly_limit_scans > 0
        and consumed_scans >= monthly_limit_scans * WARNING_THRESHOLD_RATIO
    )
    limit_reached = bool(monthly_limit_scans is not None and consumed_scans >= monthly_limit_scans)
    return ProjectBudgetSnapshot(
        project_id=project_id,
        monthly_limit_scans=monthly_limit_scans,
        cycle_anchor_day=cycle_anchor_day,
        current_period_start=window.period_start,
        current_period_end=window.period_end,
        consumed_scans=consumed_scans,
        remaining_scans=remaining,
        percent_consumed=percent_consumed,
        status=_resolve_snapshot_status(monthly_limit_scans, consumed_scans),
        warning_threshold_reached=warning_threshold_reached,
        limit_reached=limit_reached,
    )


def get_project_budget_snapshot(
    db: Session,
    *,
    project_id: int,
    reference_at: datetime | None = None,
) -> ProjectBudgetSnapshot:
    config = _get_budget_config(db, project_id=project_id)
    cycle_anchor_day = normalize_cycle_anchor_day(
        getattr(config, "cycle_anchor_day", DEFAULT_CYCLE_ANCHOR_DAY)
    )
    window = resolve_budget_period_window(
        reference_at=reference_at, cycle_anchor_day=cycle_anchor_day
    )
    usage = (
        db.query(models.ProjectBudgetUsagePeriod)
        .filter(
            models.ProjectBudgetUsagePeriod.project_id == project_id,
            models.ProjectBudgetUsagePeriod.period_start == window.period_start,
        )
        .first()
    )
    consumed_scans = int(usage.consumed_scans or 0) if usage is not None else 0
    monthly_limit_scans = (
        int(config.monthly_limit_scans)
        if config is not None and config.monthly_limit_scans is not None
        else None
    )
    return _build_snapshot(
        project_id=project_id,
        monthly_limit_scans=monthly_limit_scans,
        cycle_anchor_day=cycle_anchor_day,
        consumed_scans=consumed_scans,
        window=window,
    )


def list_recent_project_budget_periods(
    db: Session,
    *,
    project_id: int,
    limit: int = DEFAULT_HISTORY_PERIODS,
) -> list[dict[str, object]]:
    rows = (
        db.query(models.ProjectBudgetUsagePeriod)
        .filter(models.ProjectBudgetUsagePeriod.project_id == project_id)
        .order_by(
            models.ProjectBudgetUsagePeriod.period_start.desc(),
            models.ProjectBudgetUsagePeriod.id.desc(),
        )
        .limit(max(1, int(limit)))
        .all()
    )
    return [serialize_usage_period(row) for row in rows]


def upsert_project_budget(
    db: Session,
    *,
    project_id: int,
    monthly_limit_scans: int,
    cycle_anchor_day: int,
    reference_at: datetime | None = None,
) -> models.ProjectBudget:
    resolved_limit = max(0, int(monthly_limit_scans))
    resolved_anchor_day = normalize_cycle_anchor_day(cycle_anchor_day)
    config = _get_budget_config(db, project_id=project_id)

    if config is None:
        config = models.ProjectBudget(
            project_id=project_id,
            monthly_limit_scans=resolved_limit,
            cycle_anchor_day=resolved_anchor_day,
        )
        db.add(config)
    else:
        config.monthly_limit_scans = resolved_limit
        config.cycle_anchor_day = resolved_anchor_day

    window = resolve_budget_period_window(
        reference_at=reference_at, cycle_anchor_day=resolved_anchor_day
    )
    _ensure_usage_row(
        db,
        project_id=project_id,
        window=window,
        cycle_anchor_day=resolved_anchor_day,
        budget_limit_scans=resolved_limit,
    )
    db.flush()
    return config


def delete_project_budget(
    db: Session,
    *,
    project_id: int,
    reference_at: datetime | None = None,
) -> None:
    config = _get_budget_config(db, project_id=project_id)
    if config is None:
        return

    cycle_anchor_day = normalize_cycle_anchor_day(config.cycle_anchor_day)
    window = resolve_budget_period_window(
        reference_at=reference_at, cycle_anchor_day=cycle_anchor_day
    )
    usage = (
        _usage_query(db, project_id=project_id)
        .filter(models.ProjectBudgetUsagePeriod.period_start == window.period_start)
        .first()
    )
    if usage is not None:
        usage.budget_limit_scans = None
        usage.cycle_anchor_day = DEFAULT_CYCLE_ANCHOR_DAY

    db.delete(config)
    db.flush()


def consume_project_scan(
    db: Session,
    *,
    project_id: int,
    scans: int = 1,
    reference_at: datetime | None = None,
) -> ProjectScanConsumptionResult:
    """Consume scans from the project's monthly cap.

    Counts at audit acceptance, in the same transaction as the ``AuditJob``
    insert, so the project counter can never disagree with the user-level
    ``consume_scan_allowance``. Returns ``budget_exceeded`` without
    incrementing when the cap is already reached; ``None`` caps never block.
    """
    normalized_scans = max(1, int(scans))
    config = _get_budget_config(db, project_id=project_id)
    cycle_anchor_day = normalize_cycle_anchor_day(
        getattr(config, "cycle_anchor_day", DEFAULT_CYCLE_ANCHOR_DAY)
    )
    window = resolve_budget_period_window(
        reference_at=reference_at, cycle_anchor_day=cycle_anchor_day
    )
    monthly_limit_scans = (
        int(config.monthly_limit_scans)
        if config is not None and config.monthly_limit_scans is not None
        else None
    )
    usage = _ensure_usage_row(
        db,
        project_id=project_id,
        window=window,
        cycle_anchor_day=cycle_anchor_day,
        budget_limit_scans=monthly_limit_scans,
    )

    previous_consumed = int(usage.consumed_scans or 0)
    if (
        monthly_limit_scans is not None
        and previous_consumed + normalized_scans > monthly_limit_scans
    ):
        return ProjectScanConsumptionResult(
            status="budget_exceeded",
            project_id=project_id,
            scans=normalized_scans,
            monthly_limit_scans=monthly_limit_scans,
            cycle_anchor_day=cycle_anchor_day,
            period_start=window.period_start,
            period_end=window.period_end,
            consumed_scans=previous_consumed,
            remaining_scans=_calculate_remaining_scans(monthly_limit_scans, previous_consumed),
            percent_consumed=_calculate_percent_consumed(monthly_limit_scans, previous_consumed),
        )

    usage.consumed_scans = previous_consumed + normalized_scans
    usage.last_consumed_at = (reference_at or datetime.now(timezone.utc)).astimezone(timezone.utc)

    threshold_events: list[Literal["warning_80", "limit_reached"]] = []
    if monthly_limit_scans is not None and monthly_limit_scans > 0:
        warning_threshold_scans = monthly_limit_scans * WARNING_THRESHOLD_RATIO
        if previous_consumed < warning_threshold_scans <= usage.consumed_scans:
            usage.warning_threshold_sent_at = usage.warning_threshold_sent_at or datetime.now(
                timezone.utc
            )
            threshold_events.append("warning_80")
    if monthly_limit_scans is not None and usage.consumed_scans >= monthly_limit_scans:
        usage.limit_reached_sent_at = usage.limit_reached_sent_at or datetime.now(timezone.utc)
        threshold_events.append("limit_reached")

    db.flush()
    return ProjectScanConsumptionResult(
        status="consumed",
        project_id=project_id,
        scans=normalized_scans,
        monthly_limit_scans=monthly_limit_scans,
        cycle_anchor_day=cycle_anchor_day,
        period_start=window.period_start,
        period_end=window.period_end,
        consumed_scans=int(usage.consumed_scans or 0),
        remaining_scans=_calculate_remaining_scans(
            monthly_limit_scans, int(usage.consumed_scans or 0)
        ),
        percent_consumed=_calculate_percent_consumed(
            monthly_limit_scans, int(usage.consumed_scans or 0)
        ),
        threshold_events=tuple(threshold_events),
    )


def check_project_scan_capacity(
    db: Session,
    *,
    project_id: int,
    estimated_scans: int = 1,
    reference_at: datetime | None = None,
) -> ProjectBudgetSnapshot:
    """Snapshot a project's scan cap usage for an upcoming run.

    The usage row is locked FOR UPDATE so concurrent launches serialise;
    scans already consumed at job acceptance include in-flight audits, so no
    separate pending-hold adjustment is needed.
    """
    config = _get_budget_config(db, project_id=project_id)
    cycle_anchor_day = normalize_cycle_anchor_day(
        getattr(config, "cycle_anchor_day", DEFAULT_CYCLE_ANCHOR_DAY)
    )
    monthly_limit_scans = (
        int(config.monthly_limit_scans)
        if config is not None and config.monthly_limit_scans is not None
        else None
    )

    if monthly_limit_scans is None:
        return get_project_budget_snapshot(db, project_id=project_id, reference_at=reference_at)

    window = resolve_budget_period_window(
        reference_at=reference_at, cycle_anchor_day=cycle_anchor_day
    )
    usage = _ensure_usage_row(
        db,
        project_id=project_id,
        window=window,
        cycle_anchor_day=cycle_anchor_day,
        budget_limit_scans=monthly_limit_scans,
    )

    return _build_snapshot(
        project_id=project_id,
        monthly_limit_scans=monthly_limit_scans,
        cycle_anchor_day=cycle_anchor_day,
        consumed_scans=int(usage.consumed_scans or 0),
        window=window,
    )


def project_scan_cap_exceeded_detail(
    *,
    project_name: str,
    monthly_limit_scans: int,
    period_end: date,
) -> str:
    return (
        f"Project scan cap reached for {project_name} "
        f"({monthly_limit_scans} scans per cycle). The next cycle starts "
        f"{period_end.strftime('%b %d, %Y')}. Adjust the cap in project settings."
    )


def enforce_project_scan_cap(
    db: Session,
    *,
    project: models.Project | None,
    scans: int = 1,
    reference_at: datetime | None = None,
) -> ProjectScanConsumptionResult | None:
    """Consume a project scan for a customer-initiated run, blocking at the cap.

    Returns ``None`` when there is no project to attribute. Raises 402 when
    the project's monthly scan cap is reached; the message names scans and
    the cycle reset date and never mentions internal cost accounting.
    """
    if project is None:
        return None
    result = consume_project_scan(
        db,
        project_id=project.id,
        scans=scans,
        reference_at=reference_at,
    )
    if result.status == "budget_exceeded":
        raise HTTPException(
            status_code=402,
            detail=project_scan_cap_exceeded_detail(
                project_name=project.name,
                monthly_limit_scans=int(result.monthly_limit_scans or 0),
                period_end=result.period_end,
            ),
        )
    return result
