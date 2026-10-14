from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
from statistics import mean
from typing import Any

from sqlalchemy.orm import Session

import models
from services.project_audit_scope import own_project_audit_clause
from services.reports.audit_result_adapter import to_canonical_audit_result

TASK_WRITE_ROLES = {
    models.WorkspaceRole.ADMIN.value,
    models.WorkspaceRole.MANAGER.value,
    models.WorkspaceRole.EDITOR.value,
}


@dataclass(frozen=True)
class RecommendationCandidate:
    key: str
    title: str
    description: str
    category: str
    priority: str


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _task_status_value(value: models.ProjectTaskStatus | str | None) -> str:
    if isinstance(value, models.ProjectTaskStatus):
        return value.value
    return str(value or models.ProjectTaskStatus.TODO.value)


def _task_priority_value(value: models.ProjectTaskPriority | str | None) -> str:
    if isinstance(value, models.ProjectTaskPriority):
        return value.value
    return str(value or models.ProjectTaskPriority.MEDIUM.value)


def _resolution_source_value(
    value: models.ProjectTaskResolutionSource | str | None,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, models.ProjectTaskResolutionSource):
        return value.value
    normalized = str(value).strip()
    return normalized or None


def _normalize_title(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized[:255]


def _normalize_description(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:4000] or None


def _normalize_category(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized[:120] or "General"


def _normalize_key_fragment(value: str | None) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return normalized[:80]


def _key_digest_fragment(value: str | None) -> str:
    return " ".join(str(value or "").split()).casefold()


def _normalize_source_recommendation_key(
    *,
    title: str,
    category: str,
    description: str | None = None,
) -> str:
    title_key = _normalize_key_fragment(title)
    category_key = _normalize_key_fragment(category)
    # Digest the raw (casefolded, whitespace-normalised) input, NOT the stripped
    # slug: titles that collapse onto the same [a-z0-9] fragment (e.g. any two
    # non-latin titles, or "Fix A"/"fix  a") must still produce distinct keys.
    # The slug prefix stays human-readable; the digest carries uniqueness.
    digest = hashlib.sha256(
        f"{_key_digest_fragment(category)}|{_key_digest_fragment(title)}|{_key_digest_fragment(description)}".encode(
            "utf-8"
        )
    ).hexdigest()[:12]
    return f"{category_key or 'general'}:{title_key or 'recommendation'}:{digest}"


def _priority_rank(priority: str) -> int:
    return {
        models.ProjectTaskPriority.LOW.value: 1,
        models.ProjectTaskPriority.MEDIUM.value: 2,
        models.ProjectTaskPriority.HIGH.value: 3,
        models.ProjectTaskPriority.CRITICAL.value: 4,
    }.get(priority, 2)


def _normalize_priority(
    *,
    raw_priority: Any = None,
    raw_impact: Any = None,
    title: str = "",
    description: str = "",
    category: str = "",
) -> str:
    if isinstance(raw_priority, str):
        normalized = raw_priority.strip().lower()
        if normalized in {
            models.ProjectTaskPriority.LOW.value,
            models.ProjectTaskPriority.MEDIUM.value,
            models.ProjectTaskPriority.HIGH.value,
            models.ProjectTaskPriority.CRITICAL.value,
        }:
            return normalized

    try:
        numeric = int(raw_priority)
    except (TypeError, ValueError):
        numeric = None

    if numeric == 1:
        return models.ProjectTaskPriority.CRITICAL.value
    if numeric == 2:
        return models.ProjectTaskPriority.HIGH.value
    if numeric == 3:
        return models.ProjectTaskPriority.MEDIUM.value
    if numeric and numeric >= 4:
        return models.ProjectTaskPriority.LOW.value

    impact = str(raw_impact or "").strip().lower()
    if impact == "critical":
        return models.ProjectTaskPriority.CRITICAL.value
    if impact in {"strategic", "warning", "high"}:
        return models.ProjectTaskPriority.HIGH.value
    if impact in {"optimization", "medium"}:
        return models.ProjectTaskPriority.MEDIUM.value

    haystack = " ".join([title, description, category]).lower()
    critical_keywords = ("canonical", "crawl", "index", "schema", "redirect", "robots", "blocked")
    high_keywords = ("performance", "content gap", "faq", "citation", "entity", "trust")

    if any(keyword in haystack for keyword in critical_keywords):
        return models.ProjectTaskPriority.CRITICAL.value
    if any(keyword in haystack for keyword in high_keywords):
        return models.ProjectTaskPriority.HIGH.value
    return models.ProjectTaskPriority.MEDIUM.value


def _iter_recommendation_rows(audit: models.Audit) -> list[dict[str, Any]]:
    raw_report = audit.full_report if isinstance(audit.full_report, dict) else {}
    raw_metadata = (
        raw_report.get("metadata") if isinstance(raw_report.get("metadata"), dict) else {}
    )
    resolved_plan = str(raw_metadata.get("plan") or "plan_starter")
    target_type_raw = getattr(audit, "audit_target_type", "website")
    target_type = (
        str(getattr(target_type_raw, "value", target_type_raw) or "website").strip().lower()
    )
    if target_type not in {"website", "brand"}:
        target_type = "website"
    target_url = (
        str(getattr(audit, "target_url", "") or "").strip()
        or str(getattr(audit, "url", "") or "").strip()
        or None
    )
    target_name = str(getattr(audit, "target_name", "") or "").strip() or target_url
    target_metadata = (
        dict(getattr(audit, "target_metadata", {}))
        if isinstance(getattr(audit, "target_metadata", None), dict)
        else {}
    )
    canonical = to_canonical_audit_result(
        raw_report,
        audit_url=target_url,
        audit_target_type=target_type,
        target_name=target_name,
        target_url=target_url,
        target_metadata=target_metadata,
        created_at=audit.created_at,
        plan=resolved_plan,
    )

    rows: list[dict[str, Any]] = []

    def append_from(value: Any, *, fallback_category: str = "General") -> None:
        if not isinstance(value, list):
            return
        for index, entry in enumerate(value, start=1):
            if isinstance(entry, str):
                title = _normalize_title(entry)
                if not title:
                    continue
                rows.append(
                    {
                        "title": title,
                        "description": None,
                        "category": fallback_category,
                        "priority": index,
                        "impact": None,
                    }
                )
                continue
            if not isinstance(entry, dict):
                continue
            title = _normalize_title(entry.get("title") or entry.get("action"))
            description = _normalize_description(entry.get("description") or entry.get("action"))
            if not title:
                continue
            rows.append(
                {
                    "title": title,
                    "description": description,
                    "category": _normalize_category(entry.get("category") or fallback_category),
                    "priority": entry.get("priority", index),
                    "impact": entry.get("impact") or entry.get("severity"),
                }
            )

    # recommendations.items is the canonical node the Advisor plan is built
    # from (advisor_view._report_suggestions prefers it); read it first so the
    # board carries exactly one task per plan action, keyed identically.
    canonical_recommendations = canonical.get("recommendations")
    append_from(
        canonical_recommendations.get("items")
        if isinstance(canonical_recommendations, dict)
        else None,
        fallback_category="Technical",
    )
    append_from(canonical.get("suggestions"), fallback_category="Technical")
    raw_recommendations = raw_report.get("recommendations")
    append_from(
        raw_recommendations.get("items") if isinstance(raw_recommendations, dict) else None,
        fallback_category="Technical",
    )
    append_from(raw_report.get("prioritized_actions"), fallback_category="Technical")
    append_from(raw_report.get("priority_actions"), fallback_category="Technical")
    append_from(raw_report.get("suggestions"), fallback_category="Technical")

    analysis = raw_report.get("analysis") if isinstance(raw_report.get("analysis"), dict) else {}
    append_from(analysis.get("recommendations"), fallback_category="Technical")

    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        candidate_key = _normalize_source_recommendation_key(
            title=str(row.get("title") or ""),
            category=str(row.get("category") or "General"),
            description=str(row.get("description") or ""),
        )
        if candidate_key in seen_keys:
            continue
        seen_keys.add(candidate_key)
        deduped.append(row)
    return deduped


def extract_audit_recommendation_candidates(audit: models.Audit) -> list[RecommendationCandidate]:
    candidates: list[RecommendationCandidate] = []
    for row in _iter_recommendation_rows(audit):
        title = _normalize_title(str(row.get("title") or ""))
        description = _normalize_description(str(row.get("description") or ""))
        category = _normalize_category(str(row.get("category") or "General"))
        if not title:
            continue
        candidates.append(
            RecommendationCandidate(
                key=_normalize_source_recommendation_key(
                    title=title,
                    category=category,
                    description=description,
                ),
                title=title,
                description=description or "",
                category=category,
                priority=_normalize_priority(
                    raw_priority=row.get("priority"),
                    raw_impact=row.get("impact"),
                    title=title,
                    description=description or "",
                    category=category,
                ),
            )
        )
    return candidates


def resolve_task_recommendation_key(
    db: Session,
    *,
    project_id: int,
    source_audit_id: int | None,
    title: str,
    client_key: str | None = None,
) -> str | None:
    """Derive ``source_recommendation_key`` server-side.

    A task is an audit recommendation only when its source audit's own
    recommendation candidates prove it: a matching candidate key (client echo)
    or a matching title. A client-supplied key that verifies against no
    candidate is dropped, and so is a key with no source audit to check it
    against - the server, not the caller, asserts provenance.
    """
    if source_audit_id is None:
        return None
    audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.id == source_audit_id,
            models.Audit.project_id == project_id,
            own_project_audit_clause(),
        )
        .first()
    )
    if audit is None:
        return None
    candidates = extract_audit_recommendation_candidates(audit)
    if client_key:
        for candidate in candidates:
            if candidate.key == client_key:
                return candidate.key
    normalized_title = " ".join(str(title or "").split()).casefold()
    if normalized_title:
        for candidate in candidates:
            if " ".join(candidate.title.split()).casefold() == normalized_title:
                return candidate.key
    return None


def _task_source_datetime(task: models.ProjectTask) -> datetime:
    return (
        _as_utc_datetime(task.source_audit.created_at)
        if task.source_audit is not None and task.source_audit.created_at is not None
        else _as_utc_datetime(task.created_at) or datetime.now(timezone.utc)
    )


def _task_is_active_at(task: models.ProjectTask, instant: datetime) -> bool:
    source_at = _task_source_datetime(task)
    if source_at > instant:
        return False
    resolved_at = _as_utc_datetime(task.resolved_at)
    if resolved_at is None:
        return True
    return resolved_at > instant


def _next_sort_order(tasks: list[models.ProjectTask], status_value: str) -> int:
    current = [
        int(task.sort_order or 0)
        for task in tasks
        if _task_status_value(task.status) == status_value
    ]
    return (max(current) if current else 0) + 100


def _find_active_task(
    tasks: list[models.ProjectTask],
    *,
    key: str,
    at: datetime,
) -> models.ProjectTask | None:
    for task in tasks:
        if task.source_recommendation_key != key:
            continue
        if _task_is_active_at(task, at):
            return task
    return None


def _refresh_recommendation_task(
    task: models.ProjectTask,
    candidate: RecommendationCandidate,
) -> bool:
    changed = False
    if task.origin != models.ProjectTaskOrigin.AUDIT_RECOMMENDATION:
        return changed
    if task.title != candidate.title:
        task.title = candidate.title
        changed = True
    normalized_description = candidate.description or None
    if (task.description or None) != normalized_description:
        task.description = normalized_description
        changed = True
    if task.category != candidate.category:
        task.category = candidate.category
        changed = True
    if _task_priority_value(task.priority) != candidate.priority:
        task.priority = models.ProjectTaskPriority(candidate.priority)
        changed = True
    return changed


def sync_project_tasks(
    db: Session,
    *,
    project_id: int,
    commit: bool = True,
) -> list[models.ProjectTask]:
    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        return []

    audits = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project.id, own_project_audit_clause())
        .order_by(models.Audit.created_at.asc(), models.Audit.id.asc())
        .all()
    )
    tasks = (
        db.query(models.ProjectTask)
        .filter(models.ProjectTask.project_id == project.id)
        .order_by(models.ProjectTask.created_at.asc(), models.ProjectTask.id.asc())
        .all()
    )

    changed = False

    for audit in audits:
        audit_at = _as_utc_datetime(audit.created_at) or datetime.now(timezone.utc)
        candidates = extract_audit_recommendation_candidates(audit)
        candidate_by_key = {candidate.key: candidate for candidate in candidates}

        for candidate in candidates:
            active_task = _find_active_task(tasks, key=candidate.key, at=audit_at)
            if active_task is not None:
                if _refresh_recommendation_task(active_task, candidate):
                    changed = True
                continue

            historical_task = next(
                (
                    task
                    for task in tasks
                    if task.source_recommendation_key == candidate.key
                    and _task_source_datetime(task) <= audit_at
                    and _task_is_active_at(task, audit_at)
                ),
                None,
            )
            if historical_task is not None:
                if _refresh_recommendation_task(historical_task, candidate):
                    changed = True
                continue

            task = models.ProjectTask(
                project_id=project.id,
                source_audit_id=audit.id,
                title=candidate.title,
                description=candidate.description or None,
                status=models.ProjectTaskStatus.TODO,
                priority=models.ProjectTaskPriority(candidate.priority),
                origin=models.ProjectTaskOrigin.AUDIT_RECOMMENDATION,
                category=candidate.category,
                source_recommendation_key=candidate.key,
                sort_order=_next_sort_order(tasks, models.ProjectTaskStatus.TODO.value),
                schema_version="1",
                metadata_json={"auto_created_from_audit": audit.id},
            )
            db.add(task)
            db.flush()
            tasks.append(task)
            changed = True

        candidate_keys = set(candidate_by_key.keys())
        for task in tasks:
            key = str(task.source_recommendation_key or "").strip()
            if not key:
                continue

            task_status = _task_status_value(task.status)
            if task_status != models.ProjectTaskStatus.DONE.value:
                if not _task_is_active_at(task, audit_at):
                    continue
                if _task_source_datetime(task) >= audit_at:
                    continue
                if key in candidate_keys:
                    continue

                task.status = models.ProjectTaskStatus.DONE
                task.resolved_at = audit_at
                task.verified_at = audit_at
                task.verification_audit_id = audit.id
                task.resolution_source = models.ProjectTaskResolutionSource.AUDIT_VALIDATED
                task.sort_order = _next_sort_order(tasks, models.ProjectTaskStatus.DONE.value)
                changed = True
                continue

            if task.verification_audit_id is not None:
                continue

            resolved_at = _as_utc_datetime(task.resolved_at)
            if resolved_at is None or audit_at <= resolved_at:
                continue
            if key in candidate_keys:
                continue

            task.verification_audit_id = audit.id
            task.verified_at = audit_at
            if task.resolution_source is None:
                task.resolution_source = models.ProjectTaskResolutionSource.MANUAL
            changed = True

    if changed and commit:
        db.commit()
        for task in tasks:
            db.refresh(task)
    elif changed:
        db.flush()

    return (
        db.query(models.ProjectTask)
        .filter(models.ProjectTask.project_id == project.id)
        .order_by(models.ProjectTask.sort_order.asc(), models.ProjectTask.id.asc())
        .all()
    )


def task_write_allowed(role: str) -> bool:
    return str(role or "").strip().upper() in TASK_WRITE_ROLES


def task_assignee_belongs_to_workspace(
    db: Session,
    *,
    workspace_id: int,
    user_id: int,
) -> bool:
    workspace = db.query(models.Workspace).filter(models.Workspace.id == workspace_id).first()
    if workspace is None:
        return False
    if workspace.owner_id == user_id:
        return True
    membership = (
        db.query(models.WorkspaceUser.id)
        .filter(
            models.WorkspaceUser.workspace_id == workspace_id,
            models.WorkspaceUser.user_id == user_id,
        )
        .first()
    )
    return membership is not None


def build_project_task_impact_payload(
    db: Session,
    *,
    project_id: int,
) -> dict[str, Any]:
    tasks = sync_project_tasks(db, project_id=project_id)
    impact_items: list[dict[str, Any]] = []
    strongest_metric: str | None = None
    strongest_delta: float | None = None

    for task in tasks:
        if _task_status_value(task.status) != models.ProjectTaskStatus.DONE.value:
            continue

        source_audit = task.source_audit
        verification_audit = task.verification_audit

        delta_payload = {"seo": None, "geo": None, "aeo": None, "overall": None}
        verification_status = "pending_validation"
        narrative: str | None = None

        if source_audit is not None and verification_audit is not None:
            seo_delta = (
                round(float(verification_audit.seo_score) - float(source_audit.seo_score), 2)
                if source_audit.seo_score is not None and verification_audit.seo_score is not None
                else None
            )
            geo_delta = (
                round(float(verification_audit.geo_score) - float(source_audit.geo_score), 2)
                if source_audit.geo_score is not None and verification_audit.geo_score is not None
                else None
            )
            aeo_delta = (
                round(float(verification_audit.aeo_score) - float(source_audit.aeo_score), 2)
                if source_audit.aeo_score is not None and verification_audit.aeo_score is not None
                else None
            )
            deltas = [value for value in (seo_delta, geo_delta, aeo_delta) if value is not None]
            overall_delta = round(mean(deltas), 2) if deltas else None
            delta_payload = {
                "seo": seo_delta,
                "geo": geo_delta,
                "aeo": aeo_delta,
                "overall": overall_delta,
            }
            verification_status = "validated"

            top_metric = None
            top_value = None
            for metric_key in ("seo", "geo", "aeo"):
                value = delta_payload[metric_key]
                if value is None:
                    continue
                if top_value is None or value > top_value:
                    top_metric = metric_key
                    top_value = value

            if top_metric is not None and top_value is not None and top_value > 0:
                narrative = f"Fixing '{task.title}' improved {top_metric.upper()} by +{top_value}."
                if strongest_delta is None or top_value > strongest_delta:
                    strongest_delta = top_value
                    strongest_metric = top_metric
            else:
                narrative = f"'{task.title}' was cleared in a later audit without a measurable score lift yet."

        impact_items.append(
            {
                "task_id": task.id,
                "title": task.title,
                "category": task.category,
                "priority": _task_priority_value(task.priority),
                "resolution_source": _resolution_source_value(task.resolution_source),
                "source_audit_id": task.source_audit_id,
                "source_audit_created_at": _as_utc_datetime(source_audit.created_at).isoformat()
                if source_audit is not None and source_audit.created_at is not None
                else None,
                "verification_audit_id": task.verification_audit_id,
                "verified_at": _as_utc_datetime(task.verified_at).isoformat()
                if task.verified_at is not None
                else None,
                "resolved_at": _as_utc_datetime(task.resolved_at).isoformat()
                if task.resolved_at is not None
                else None,
                "verification_status": verification_status,
                "delta": delta_payload,
                "narrative": narrative,
            }
        )

    impact_items.sort(
        key=lambda item: (
            item["verification_status"] != "validated",
            item["resolved_at"] or "",
            item["task_id"],
        ),
        reverse=True,
    )

    validated_count = sum(1 for item in impact_items if item["verification_status"] == "validated")
    pending_validation_count = len(impact_items) - validated_count

    return {
        "project_id": project_id,
        "summary": {
            "resolved_count": len(impact_items),
            "validated_count": validated_count,
            "pending_validation_count": pending_validation_count,
            "strongest_metric": strongest_metric,
            "strongest_delta": strongest_delta,
        },
        "items": impact_items,
    }


def build_project_task_summary(tasks: list[models.ProjectTask]) -> dict[str, int]:
    summary = defaultdict(int)
    now = datetime.now(timezone.utc).date()

    for task in tasks:
        status_value = _task_status_value(task.status)
        summary[status_value] += 1
        if task.assigned_to_user_id is None:
            summary["unassigned"] += 1
        if task.source_audit_id is not None:
            summary["audit_linked"] += 1
        if (
            task.due_date is not None
            and status_value != models.ProjectTaskStatus.DONE.value
            and task.due_date < now
        ):
            summary["overdue"] += 1
        if task.verification_audit_id is not None:
            summary["validated"] += 1

    return {
        "todo": int(summary[models.ProjectTaskStatus.TODO.value]),
        "in_progress": int(summary[models.ProjectTaskStatus.IN_PROGRESS.value]),
        "done": int(summary[models.ProjectTaskStatus.DONE.value]),
        "unassigned": int(summary["unassigned"]),
        "audit_linked": int(summary["audit_linked"]),
        "overdue": int(summary["overdue"]),
        "validated": int(summary["validated"]),
    }
