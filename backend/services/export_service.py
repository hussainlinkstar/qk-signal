from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO
from typing import Any, Iterable, Iterator

from sqlalchemy.orm import Session

import models
from report_schema import AuditAnalysis
from services.project_audit_scope import own_project_audit_clause
from services.reports.audit_result_adapter import (
    extract_canonical_entities,
    extract_normalized_recommendation_items,
)
from services.workspace_rbac import is_client_readonly_role

EXPORT_CSV_COLUMNS = (
    "project_id",
    "audit_date",
    "geo_score",
    "seo_score",
    "aeo_score",
    "url",
    "entity_count",
    "recommendation_count",
)

EXPORT_ROW_LIMITS = {
    "plan_specialist": 2000,
    "plan_executive": 10000,
}


@dataclass(frozen=True)
class ExportFilters:
    project_ids: tuple[int, ...] = ()
    start_date: date | None = None
    end_date: date | None = None
    row_limit: int = 2000


def max_export_rows_for_plan(plan: str) -> int:
    return int(EXPORT_ROW_LIMITS.get(str(plan or "").strip().lower(), 2000))


def list_accessible_project_ids(
    db: Session,
    *,
    user: models.User,
) -> list[int]:
    project_ids: set[int] = set()

    owned_project_rows = (
        db.query(models.Project.id)
        .join(models.Workspace, models.Project.workspace_id == models.Workspace.id)
        .filter(models.Workspace.owner_id == user.id)
        .all()
    )
    project_ids.update(int(project_id) for (project_id,) in owned_project_rows)

    memberships = (
        db.query(models.WorkspaceUser).filter(models.WorkspaceUser.user_id == user.id).all()
    )

    internal_workspace_ids = [
        int(membership.workspace_id)
        for membership in memberships
        if not is_client_readonly_role(membership.role)
    ]
    if internal_workspace_ids:
        internal_project_rows = (
            db.query(models.Project.id)
            .filter(models.Project.workspace_id.in_(internal_workspace_ids))
            .all()
        )
        project_ids.update(int(project_id) for (project_id,) in internal_project_rows)

    client_membership_ids = [
        int(membership.id) for membership in memberships if is_client_readonly_role(membership.role)
    ]
    if client_membership_ids:
        client_project_rows = (
            db.query(models.WorkspaceUserProjectAccess.project_id)
            .filter(models.WorkspaceUserProjectAccess.workspace_user_id.in_(client_membership_ids))
            .all()
        )
        project_ids.update(int(project_id) for (project_id,) in client_project_rows)

    return sorted(project_ids)


def list_project_score_export_rows(
    db: Session,
    *,
    user: models.User,
    filters: ExportFilters,
) -> list[dict[str, Any]]:
    project_ids = sorted(
        {int(project_id) for project_id in filters.project_ids if int(project_id) > 0}
    )
    if not project_ids:
        project_ids = list_accessible_project_ids(db, user=user)
    if not project_ids:
        return []

    query = db.query(models.Audit).filter(
        models.Audit.project_id.in_(project_ids), own_project_audit_clause()
    )
    if filters.start_date is not None:
        query = query.filter(models.Audit.created_at >= _date_start(filters.start_date))
    if filters.end_date is not None:
        query = query.filter(models.Audit.created_at < _date_end_exclusive(filters.end_date))

    audits = (
        query.order_by(models.Audit.created_at.asc(), models.Audit.id.asc())
        .limit(int(filters.row_limit))
        .all()
    )
    return [_serialize_export_row(audit) for audit in audits]


def iter_csv_lines(rows: Iterable[dict[str, Any]]) -> Iterator[str]:
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(EXPORT_CSV_COLUMNS))

    writer.writeheader()
    yield buffer.getvalue()
    buffer.seek(0)
    buffer.truncate(0)

    for row in rows:
        writer.writerow(row)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)


def _serialize_export_row(audit: models.Audit) -> dict[str, Any]:
    entity_count, recommendation_count = _derive_report_counts(audit.full_report)
    return {
        "project_id": int(audit.project_id) if audit.project_id is not None else "",
        "audit_date": _serialize_datetime(audit.created_at),
        "geo_score": _serialize_score(audit.geo_score),
        "seo_score": _serialize_score(audit.seo_score),
        "aeo_score": _serialize_score(audit.aeo_score),
        "url": audit.url,
        "entity_count": entity_count,
        "recommendation_count": recommendation_count,
    }


def _serialize_score(value: float | None) -> str:
    if value is None:
        return ""
    return f"{float(value):g}"


def _serialize_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def _derive_report_counts(full_report: Any) -> tuple[int, int]:
    if not isinstance(full_report, dict):
        return (0, 0)

    canonical_entities = extract_canonical_entities(full_report)
    normalized_recommendations = extract_normalized_recommendation_items(full_report)
    if canonical_entities or normalized_recommendations:
        return (len(canonical_entities), len(normalized_recommendations))

    analysis_payload = full_report.get("analysis")
    if isinstance(analysis_payload, dict):
        try:
            parsed = AuditAnalysis.model_validate(analysis_payload)
            entities = [
                item
                for item in (parsed.entities_detected or [])
                if isinstance(item, str) and item.strip()
            ]
            recommendations = [
                item
                for item in (parsed.recommendations or [])
                if isinstance(item, str) and item.strip()
            ]
            if entities or recommendations:
                return (len(entities), len(recommendations))
        except Exception:
            pass

    entities = _normalize_string_list(
        full_report.get("entities_detected")
        or full_report.get("entities")
        or (
            analysis_payload.get("entities_detected")
            if isinstance(analysis_payload, dict)
            else None
        )
        or (analysis_payload.get("entities") if isinstance(analysis_payload, dict) else None)
    )
    recommendations = _normalize_string_list(
        full_report.get("recommendations")
        or (analysis_payload.get("recommendations") if isinstance(analysis_payload, dict) else None)
    )
    return (len(entities), len(recommendations))


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            continue
        normalized = item.strip()
        if not normalized:
            continue
        items.append(normalized)
    return items


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _date_end_exclusive(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)
