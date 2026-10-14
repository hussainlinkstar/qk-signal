from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from statistics import mean
from typing import Any, Iterable, Sequence

from sqlalchemy.orm import Session

import models
from services.ai_search_volatility_service import AISearchVolatilityService
from services.email_service import EmailService
from services.notification_router import NotificationRouter
from services.project_audit_scope import own_project_audit_clause
from services.reports.audit_result_adapter import extract_normalized_recommendation_texts
from services.workflow_engine import evaluate_workflows_for_event

SUPPORTED_TREND_PERIODS = {"7d", "30d", "90d", "1y", "all"}
SUPPORTED_COMPARISON_PERIODS = {"30d", "90d", "1y"}
SUPPORTED_GRANULARITIES = {"daily", "weekly", "monthly"}


@dataclass(frozen=True)
class MetricSummary:
    seo: float | None
    geo: float | None
    aeo: float | None
    overall: float | None
    audit_count: int

    def as_dict(self) -> dict[str, float | int | None]:
        return {
            "seo": self.seo,
            "geo": self.geo,
            "aeo": self.aeo,
            "overall": self.overall,
            "audit_count": self.audit_count,
        }


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _round_metric(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def _mean_or_none(values: Iterable[float | None]) -> float | None:
    normalized = [float(value) for value in values if value is not None]
    if not normalized:
        return None
    return round(mean(normalized), 2)


def _overall_score(*, seo: float | None, geo: float | None, aeo: float | None) -> float | None:
    return _mean_or_none([seo, geo, aeo])


def _derive_aio_for_point(point: dict[str, Any]) -> float | None:
    # Canonical AIO weighting (AIO_AEO_WEIGHT / AIO_GEO_WEIGHT) so the sparkline
    # agrees with the score ring; imported lazily to avoid a module cycle.
    from app.services.aio_view import derive_aio

    return derive_aio({"aeo_score": point["aeo"], "geo_score": point["geo"]}).get("aio_score")


def _metric_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None:
        return None
    return round(current - previous, 2)


def _metric_direction(delta: float | None) -> str:
    if delta is None:
        return "stable"
    if delta > 1:
        return "up"
    if delta < -1:
        return "down"
    return "stable"


def normalize_trend_period(period: str) -> str:
    normalized = (period or "90d").strip().lower()
    if normalized not in SUPPORTED_TREND_PERIODS:
        raise ValueError("Unsupported trend period.")
    return normalized


def normalize_comparison_period(period: str) -> str:
    normalized = (period or "30d").strip().lower()
    if normalized not in SUPPORTED_COMPARISON_PERIODS:
        raise ValueError("Unsupported comparison period.")
    return normalized


def normalize_granularity(granularity: str, *, period: str) -> str:
    normalized = (granularity or "").strip().lower()
    if not normalized:
        if period in {"7d", "30d"}:
            normalized = "daily"
        elif period == "90d":
            normalized = "weekly"
        else:
            normalized = "monthly"
    if normalized not in SUPPORTED_GRANULARITIES:
        raise ValueError("Unsupported trend granularity.")
    return normalized


def _period_delta(period: str) -> timedelta | None:
    if period == "7d":
        return timedelta(days=7)
    if period == "30d":
        return timedelta(days=30)
    if period == "90d":
        return timedelta(days=90)
    if period == "1y":
        return timedelta(days=365)
    return None


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _next_month_start(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _month_bounds(value: date) -> tuple[datetime, datetime]:
    month_start = _month_start(value)
    next_month_start = _next_month_start(month_start)
    return (
        datetime.combine(month_start, datetime.min.time(), tzinfo=timezone.utc),
        datetime.combine(next_month_start, datetime.min.time(), tzinfo=timezone.utc),
    )


def _bucket_start(created_at: datetime, granularity: str) -> date:
    created_date = created_at.date()
    if granularity == "daily":
        return created_date
    if granularity == "weekly":
        return created_date - timedelta(days=created_date.weekday())
    return _month_start(created_date)


def _bucket_bounds_for_granularity(bucket_date: date, granularity: str) -> tuple[date, date]:
    if granularity == "daily":
        return bucket_date, bucket_date
    if granularity == "weekly":
        return bucket_date, bucket_date + timedelta(days=6)
    next_month_start = _next_month_start(bucket_date)
    return bucket_date, next_month_start - timedelta(days=1)


def _load_project_audits(
    db: Session,
    *,
    project_id: int,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> list[models.Audit]:
    # SIGV2-1117: trend, period comparison and the monthly report all read this
    # list, so it must contain the project's own audits and nothing else.
    query = db.query(models.Audit).filter(
        models.Audit.project_id == project_id, own_project_audit_clause()
    )
    if start_at is not None:
        query = query.filter(models.Audit.created_at >= start_at)
    if end_at is not None:
        query = query.filter(models.Audit.created_at < end_at)
    return query.order_by(models.Audit.created_at.asc(), models.Audit.id.asc()).all()


def _summarize_audits(audits: Sequence[models.Audit]) -> MetricSummary:
    seo = _mean_or_none(audit.seo_score for audit in audits)
    geo = _mean_or_none(audit.geo_score for audit in audits)
    aeo = _mean_or_none(audit.aeo_score for audit in audits)
    return MetricSummary(
        seo=seo,
        geo=geo,
        aeo=aeo,
        overall=_overall_score(seo=seo, geo=geo, aeo=aeo),
        audit_count=len(audits),
    )


def build_project_trend_payload(
    db: Session,
    *,
    project_id: int,
    period: str,
    granularity: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_period = normalize_trend_period(period)
    normalized_granularity = normalize_granularity(granularity, period=normalized_period)
    current_time = _as_utc_datetime(now) or datetime.now(timezone.utc)
    delta = _period_delta(normalized_period)
    start_at = current_time - delta if delta is not None else None

    audits = _load_project_audits(db, project_id=project_id, start_at=start_at)
    buckets: dict[date, list[models.Audit]] = {}
    for audit in audits:
        created_at = _as_utc_datetime(audit.created_at)
        if created_at is None:
            continue
        key = _bucket_start(created_at, normalized_granularity)
        buckets.setdefault(key, []).append(audit)

    volatility_by_date: dict[str, float] = {}
    if buckets:
        ordered_bucket_dates = sorted(buckets.keys())
        first_bucket = ordered_bucket_dates[0]
        last_bucket = ordered_bucket_dates[-1]
        _last_start, last_end = _bucket_bounds_for_granularity(last_bucket, normalized_granularity)
        volatility_by_date = AISearchVolatilityService(db).build_overlay_map(
            start_date=first_bucket,
            end_date=last_end,
            provider="all",
        )

    data_points: list[dict[str, Any]] = []
    for bucket_date in sorted(buckets):
        bucket_audits = buckets[bucket_date]
        latest_audit = bucket_audits[-1]
        seo = _mean_or_none(audit.seo_score for audit in bucket_audits)
        geo = _mean_or_none(audit.geo_score for audit in bucket_audits)
        aeo = _mean_or_none(audit.aeo_score for audit in bucket_audits)
        overall = _overall_score(seo=seo, geo=geo, aeo=aeo)
        bucket_start_date, bucket_end_date = _bucket_bounds_for_granularity(
            bucket_date, normalized_granularity
        )
        volatility_values: list[float] = []
        cursor = bucket_start_date
        while cursor <= bucket_end_date:
            candidate = volatility_by_date.get(cursor.isoformat())
            if candidate is not None:
                volatility_values.append(float(candidate))
            cursor += timedelta(days=1)
        data_points.append(
            {
                "date": bucket_date.isoformat(),
                "seo": seo,
                "geo": geo,
                "aeo": aeo,
                "overall": overall,
                "volatility_score": round(sum(volatility_values) / len(volatility_values), 2)
                if volatility_values
                else None,
                "audit_count": len(bucket_audits),
                "latest_audit_at": _as_utc_datetime(latest_audit.created_at).isoformat()
                if latest_audit.created_at
                else None,
            }
        )

    first_point = data_points[0] if data_points else None
    latest_point = data_points[-1] if data_points else None
    delta_payload = {
        "seo": _metric_delta(latest_point["seo"], first_point["seo"])
        if first_point and latest_point
        else None,
        "geo": _metric_delta(latest_point["geo"], first_point["geo"])
        if first_point and latest_point
        else None,
        "aeo": _metric_delta(latest_point["aeo"], first_point["aeo"])
        if first_point and latest_point
        else None,
        "overall": _metric_delta(latest_point["overall"], first_point["overall"])
        if first_point and latest_point
        else None,
    }

    return {
        "project_id": project_id,
        "period": normalized_period,
        "granularity": normalized_granularity,
        "data_points": data_points,
        "summary": {
            "first": first_point,
            "latest": latest_point,
            "delta": delta_payload,
            "trend_direction": {
                "seo": _metric_direction(delta_payload["seo"]),
                "geo": _metric_direction(delta_payload["geo"]),
                "aeo": _metric_direction(delta_payload["aeo"]),
                "overall": _metric_direction(delta_payload["overall"]),
            },
        },
    }


def build_project_period_comparison(
    db: Session,
    *,
    project_id: int,
    period: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    normalized_period = normalize_comparison_period(period)
    current_time = _as_utc_datetime(now) or datetime.now(timezone.utc)
    delta = _period_delta(normalized_period)
    if delta is None:
        raise ValueError("Comparison period requires a bounded window.")

    current_start = current_time - delta
    previous_start = current_start - delta

    previous_audits = _load_project_audits(
        db,
        project_id=project_id,
        start_at=previous_start,
        end_at=current_start,
    )
    current_audits = _load_project_audits(
        db,
        project_id=project_id,
        start_at=current_start,
        end_at=current_time,
    )

    previous_summary = _summarize_audits(previous_audits)
    current_summary = _summarize_audits(current_audits)
    delta_payload = {
        "seo": _metric_delta(current_summary.seo, previous_summary.seo),
        "geo": _metric_delta(current_summary.geo, previous_summary.geo),
        "aeo": _metric_delta(current_summary.aeo, previous_summary.aeo),
        "overall": _metric_delta(current_summary.overall, previous_summary.overall),
    }

    return {
        "project_id": project_id,
        "period": normalized_period,
        "current_period": {
            "start": current_start.isoformat(),
            "end": current_time.isoformat(),
            **current_summary.as_dict(),
        },
        "previous_period": {
            "start": previous_start.isoformat(),
            "end": current_start.isoformat(),
            **previous_summary.as_dict(),
        },
        "delta": delta_payload,
        "trend_direction": {
            "seo": _metric_direction(delta_payload["seo"]),
            "geo": _metric_direction(delta_payload["geo"]),
            "aeo": _metric_direction(delta_payload["aeo"]),
            "overall": _metric_direction(delta_payload["overall"]),
        },
    }


def build_workspace_trends_overview(
    db: Session,
    *,
    workspace_id: int,
    period: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    projects = (
        db.query(models.Project)
        .filter(models.Project.workspace_id == workspace_id)
        .order_by(models.Project.name.asc(), models.Project.id.asc())
        .all()
    )

    items: list[dict[str, Any]] = []
    for project in projects:
        trend_payload = build_project_trend_payload(
            db,
            project_id=project.id,
            period=period,
            granularity="weekly",
            now=now,
        )
        latest_audit = (
            db.query(models.Audit)
            .filter(models.Audit.project_id == project.id, own_project_audit_clause())
            .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
            .first()
        )
        items.append(
            {
                "project_id": project.id,
                "name": project.name,
                "domain_url": project.domain_url,
                "last_audit_at": _as_utc_datetime(latest_audit.created_at).isoformat()
                if latest_audit and latest_audit.created_at
                else None,
                "latest_scores": {
                    "seo": _round_metric(latest_audit.seo_score) if latest_audit else None,
                    "geo": _round_metric(latest_audit.geo_score) if latest_audit else None,
                    "aeo": _round_metric(latest_audit.aeo_score) if latest_audit else None,
                    "overall": _overall_score(
                        seo=_round_metric(latest_audit.seo_score) if latest_audit else None,
                        geo=_round_metric(latest_audit.geo_score) if latest_audit else None,
                        aeo=_round_metric(latest_audit.aeo_score) if latest_audit else None,
                    ),
                },
                "delta": trend_payload["summary"]["delta"],
                "trend_direction": trend_payload["summary"]["trend_direction"],
                "sparkline": [
                    {
                        "date": point["date"],
                        "seo": point["seo"],
                        "aio": _derive_aio_for_point(point),
                        "overall": point["overall"],
                    }
                    for point in trend_payload["data_points"][-8:]
                ],
            }
        )

    return {
        "workspace_id": workspace_id,
        "period": normalize_trend_period(period),
        "projects": items,
    }


def _extract_remaining_issues(audit: models.Audit | None) -> list[str]:
    if audit is None or not isinstance(audit.full_report, dict):
        return []

    report = audit.full_report
    canonical_recommendations = extract_normalized_recommendation_texts(report, limit=3)
    if canonical_recommendations:
        return canonical_recommendations

    prioritized = report.get("prioritized_actions")
    if isinstance(prioritized, list):
        items: list[str] = []
        for raw_item in prioritized[:3]:
            if isinstance(raw_item, dict):
                title = raw_item.get("title") or raw_item.get("action") or raw_item.get("name")
                if isinstance(title, str) and title.strip():
                    items.append(title.strip())
        if items:
            return items

    analysis = report.get("analysis") if isinstance(report.get("analysis"), dict) else {}
    recommendations = analysis.get("recommendations") if isinstance(analysis, dict) else None
    if isinstance(recommendations, list):
        return [str(item).strip() for item in recommendations[:3] if str(item).strip()]
    return []


def _build_highlights(
    current: MetricSummary,
    previous: MetricSummary,
) -> list[str]:
    rows = [
        ("SEO", _metric_delta(current.seo, previous.seo)),
        ("GEO", _metric_delta(current.geo, previous.geo)),
        ("AEO", _metric_delta(current.aeo, previous.aeo)),
    ]
    improvements = [
        f"{label} {'improved' if delta and delta > 0 else 'changed'} by {abs(delta):.1f} points"
        for label, delta in rows
        if delta is not None and abs(delta) >= 1
    ]
    if improvements:
        return improvements[:3]
    return [
        "Historical benchmarks are still building. Run recurring audits to unlock stronger month-over-month insights."
    ]


def _resolve_progress_report_recipients(
    db: Session,
    *,
    project: models.Project,
) -> list[tuple[str, int | None]]:
    recipients: list[tuple[str, int | None]] = []
    owner = project.workspace.owner if project.workspace else None
    if owner and owner.email:
        recipients.append((owner.email, owner.id))

    rows = (
        db.query(models.User)
        .join(models.WorkspaceUser, models.WorkspaceUser.user_id == models.User.id)
        .join(
            models.WorkspaceUserProjectAccess,
            models.WorkspaceUserProjectAccess.workspace_user_id == models.WorkspaceUser.id,
        )
        .filter(
            models.WorkspaceUser.workspace_id == project.workspace_id,
            models.WorkspaceUser.role == models.WorkspaceRole.CLIENT_READONLY,
            models.WorkspaceUserProjectAccess.project_id == project.id,
        )
        .all()
    )
    for user in rows:
        if user.email:
            recipients.append((user.email, user.id))

    deduped: list[tuple[str, int | None]] = []
    seen: set[str] = set()
    for email, user_id in recipients:
        key = email.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((email, user_id))
    return deduped


def _resolve_default_report_month(now: datetime) -> date:
    current_month_start = date(now.year, now.month, 1)
    previous_month_end = current_month_start - timedelta(days=1)
    return date(previous_month_end.year, previous_month_end.month, 1)


def _resolve_latest_audit_month(
    db: Session,
    *,
    project_id: int,
) -> date | None:
    latest_audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.project_id == project_id,
            own_project_audit_clause(),
            models.Audit.created_at.isnot(None),
        )
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    if latest_audit is None or latest_audit.created_at is None:
        return None
    created_at = _as_utc_datetime(latest_audit.created_at)
    if created_at is None:
        return None
    return _month_start(created_at.date())


def _resolve_report_month(
    db: Session,
    *,
    project_id: int,
    report_month: date | None,
    now: datetime,
) -> date:
    if report_month is not None:
        return _month_start(report_month)

    preferred_month = _resolve_default_report_month(now)
    preferred_start_dt, preferred_end_dt = _month_bounds(preferred_month)
    if _load_project_audits(
        db,
        project_id=project_id,
        start_at=preferred_start_dt,
        end_at=preferred_end_dt,
    ):
        return preferred_month

    latest_audit_month = _resolve_latest_audit_month(db, project_id=project_id)
    return latest_audit_month or preferred_month


def generate_project_progress_report(
    db: Session,
    *,
    project_id: int,
    report_month: date | None = None,
    generated_by: str = "manual",
    deliver_email: bool = False,
    now: datetime | None = None,
    frontend_base_url: str | None = None,
) -> models.ProjectProgressReport:
    current_time = _as_utc_datetime(now) or datetime.now(timezone.utc)
    normalized_report_month = _resolve_report_month(
        db,
        project_id=project_id,
        report_month=report_month,
        now=current_time,
    )
    next_report_month = _next_month_start(normalized_report_month)
    previous_report_month = normalized_report_month - timedelta(days=1)
    previous_month_start = date(previous_report_month.year, previous_report_month.month, 1)

    current_start_dt, current_end_dt = _month_bounds(normalized_report_month)
    previous_start_dt, _ = _month_bounds(previous_month_start)
    previous_end_dt = current_start_dt

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        raise ValueError("Project not found.")

    current_audits = _load_project_audits(
        db,
        project_id=project.id,
        start_at=current_start_dt,
        end_at=current_end_dt,
    )
    if not current_audits:
        raise ValueError("No audits found for the selected report month.")

    previous_audits = _load_project_audits(
        db,
        project_id=project.id,
        start_at=previous_start_dt,
        end_at=previous_end_dt,
    )

    current_summary = _summarize_audits(current_audits)
    previous_summary = _summarize_audits(previous_audits)
    trend_payload = build_project_trend_payload(
        db,
        project_id=project.id,
        period="90d",
        granularity="monthly",
        now=current_end_dt,
    )
    latest_audit = current_audits[-1]
    recipients = _resolve_progress_report_recipients(db, project=project)

    snapshot = {
        "generated_at": current_time.isoformat(),
        "report_month": normalized_report_month.isoformat(),
        "project": {
            "id": project.id,
            "workspace_id": project.workspace_id,
            "name": project.name,
            "domain_url": project.domain_url,
            "language": project.language or "en",
        },
        "report_language": project.language or "en",
        "period": {
            "start": normalized_report_month.isoformat(),
            "end": next_report_month.isoformat(),
        },
        "previous_period": {
            "start": previous_month_start.isoformat(),
            "end": normalized_report_month.isoformat(),
        },
        "current_scores": current_summary.as_dict(),
        "previous_scores": previous_summary.as_dict(),
        "delta": {
            "seo": _metric_delta(current_summary.seo, previous_summary.seo),
            "geo": _metric_delta(current_summary.geo, previous_summary.geo),
            "aeo": _metric_delta(current_summary.aeo, previous_summary.aeo),
            "overall": _metric_delta(current_summary.overall, previous_summary.overall),
        },
        "trend_direction": {
            "seo": _metric_direction(_metric_delta(current_summary.seo, previous_summary.seo)),
            "geo": _metric_direction(_metric_delta(current_summary.geo, previous_summary.geo)),
            "aeo": _metric_direction(_metric_delta(current_summary.aeo, previous_summary.aeo)),
            "overall": _metric_direction(
                _metric_delta(current_summary.overall, previous_summary.overall)
            ),
        },
        "trend_points": trend_payload["data_points"][-6:],
        "highlights": _build_highlights(current_summary, previous_summary),
        "remaining_issues": _extract_remaining_issues(latest_audit),
        "latest_audit_at": _as_utc_datetime(latest_audit.created_at).isoformat()
        if latest_audit.created_at
        else None,
        "recipients": [email for email, _user_id in recipients],
    }

    report = (
        db.query(models.ProjectProgressReport)
        .filter(
            models.ProjectProgressReport.project_id == project.id,
            models.ProjectProgressReport.report_month == normalized_report_month,
        )
        .first()
    )
    if report is None:
        report = models.ProjectProgressReport(
            project_id=project.id,
            workspace_id=project.workspace_id,
            report_month=normalized_report_month,
            period_start=normalized_report_month,
            period_end=next_report_month,
            generated_by=generated_by,
            snapshot_json=snapshot,
            recipient_count=len(recipients),
        )
        db.add(report)
    else:
        report.generated_by = generated_by
        report.snapshot_json = snapshot
        report.recipient_count = len(recipients)
        report.period_start = normalized_report_month
        report.period_end = next_report_month

    db.flush()

    if deliver_email and recipients:
        report_url = f"{(frontend_base_url or 'http://localhost:3000').rstrip('/')}/dashboard/projects/{project.id}/reports"
        email_service = EmailService(db)
        notification_context = {
            "workspace_name": project.workspace.name if project.workspace else "Workspace",
            "project_name": project.name,
            "language": project.language or "en",
            "report_language": project.language or "en",
            "report_month_label": normalized_report_month.strftime("%B %Y"),
            "report_url": report_url,
            "domain_url": project.domain_url,
            "current_scores": snapshot["current_scores"],
            "previous_scores": snapshot["previous_scores"],
            "delta": snapshot["delta"],
            "highlights": snapshot["highlights"],
            "remaining_issues": snapshot["remaining_issues"],
            "trend_points": snapshot["trend_points"],
        }
        for email, user_id in recipients:
            email_service.queue_template_email(
                to_email=email,
                template_key="project.progress_report",
                context=notification_context,
                user_id=user_id,
                correlation_id=f"project.progress-report:{project.id}:{normalized_report_month.isoformat()}:{email.lower()}",
            )
        if project.workspace and project.workspace.owner:
            NotificationRouter(db).dispatch_event(
                workspace_id=project.workspace_id,
                event_key="project.progress_report",
                context=notification_context,
                user=project.workspace.owner,
                to_email=None,
                correlation_id=f"project.progress-report:{project.id}:{normalized_report_month.isoformat()}:channels",
            )
        evaluate_workflows_for_event(
            db,
            workspace_id=project.workspace_id,
            project_id=project.id,
            event_key="project.progress_report",
            context=notification_context,
        )
        report.email_sent_at = current_time

    return report


def generate_pending_project_progress_reports(
    db: Session,
    *,
    now: datetime | None = None,
    frontend_base_url: str | None = None,
) -> list[models.ProjectProgressReport]:
    current_time = _as_utc_datetime(now) or datetime.now(timezone.utc)
    if current_time.day != 1:
        return []

    report_month = _resolve_default_report_month(current_time)
    projects = (
        db.query(models.Project)
        .join(models.ScheduledAudit, models.ScheduledAudit.project_id == models.Project.id)
        .filter(models.ScheduledAudit.is_active.is_(True))
        .distinct()
        .all()
    )

    generated: list[models.ProjectProgressReport] = []
    for project in projects:
        existing = (
            db.query(models.ProjectProgressReport.id)
            .filter(
                models.ProjectProgressReport.project_id == project.id,
                models.ProjectProgressReport.report_month == report_month,
            )
            .first()
        )
        if existing is not None:
            continue
        try:
            generated.append(
                generate_project_progress_report(
                    db,
                    project_id=project.id,
                    report_month=report_month,
                    generated_by="automation",
                    deliver_email=True,
                    now=current_time,
                    frontend_base_url=frontend_base_url,
                )
            )
        except ValueError:
            continue
    return generated
