"""Alert Rules Evaluator Service.

Evaluates alert rules for a project against its latest data and queues alert emails.
"""

from datetime import datetime, timezone
import logging
import os

from sqlalchemy.orm import Session

import models
from routers.monitoring_router import get_serp_tracking
from services.notification_router import NotificationRouter
from services.project_offpage_mentions_service import ProjectOffPageMentionsService
from services.project_visibility_service import ProjectVisibilityService
from services.workflow_engine import evaluate_workflows_for_event

logger = logging.getLogger(__name__)


def _dashboard_url(project_id: int) -> str:
    base_url = os.getenv("FRONTEND_URL", "https://qiko.ai/signal").rstrip("/")
    return f"{base_url}/dashboard/projects/{project_id}"


def record_alert_trigger(
    db: Session,
    rule: models.AlertRule,
    metric_value: float,
    message: str,
    *,
    event_key: str = "alert.triggered",
    baseline_metric_value: float | None = None,
) -> None:
    """Record an alert log and queue routed notifications."""
    log = models.AlertLog(rule_id=rule.id, metric_value=metric_value, message=message)
    db.add(log)
    rule.last_triggered_at = datetime.now(timezone.utc)

    project = rule.project
    context = {
        "email": rule.email_to,
        "workspace_name": project.workspace.name if project.workspace else "Workspace",
        "project_name": project.name,
        "metric_name": rule.metric,
        "metric_value": metric_value,
        "condition": rule.condition,
        "threshold": rule.threshold,
        "message": message,
        "dashboard_url": _dashboard_url(project.id),
    }
    if baseline_metric_value is not None:
        context["baseline_metric_value"] = baseline_metric_value
    try:
        NotificationRouter(db).dispatch_event(
            workspace_id=project.workspace_id,
            event_key=event_key,
            context=context,
            user=project.workspace.owner if project.workspace else None,
            to_email=rule.email_to,
            correlation_id=f"alert:{rule.id}:{int(datetime.now(timezone.utc).timestamp())}",
        )
        evaluate_workflows_for_event(
            db,
            workspace_id=project.workspace_id,
            project_id=project.id,
            event_key=event_key,
            context=context,
        )
    except Exception as exc:
        logger.warning("Failed to queue alert notification for rule %s", rule.id, exc_info=exc)

    db.commit()


# SIGV2-1280: these three read `Audit`, not `AuditJob`.
#
# They used to query `AuditJob` filtered on a status nothing writes, so they
# matched nothing and returned. Fixing only the status moved the failure one
# line down, to `AttributeError: 'AuditJob' object has no attribute
# 'seo_score'`, swallowed by the caller's except and logged where nobody was
# reading. The scores live on `Audit` and always did.
#
# No status filter: `Audit` has no status column because the row is only
# written once an audit has succeeded (`queue_worker`). Its existence is the
# completion, and `created_at` orders it.
def evaluate_geo_score(db: Session, rule: models.AlertRule) -> None:
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == rule.project_id)
        .order_by(models.Audit.created_at.desc())
        .first()
    )
    if not latest_audit or latest_audit.geo_score is None:
        return
    if rule.condition == "below" and latest_audit.geo_score < rule.threshold:
        if (
            rule.last_triggered_at
            and (datetime.now(timezone.utc) - rule.last_triggered_at).total_seconds() < 86400
        ):
            return
        record_alert_trigger(
            db,
            rule,
            latest_audit.geo_score,
            f"AIO score dropped to {latest_audit.geo_score}% (below threshold of {rule.threshold}%)",
        )


def evaluate_seo_score(db: Session, rule: models.AlertRule) -> None:
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == rule.project_id)
        .order_by(models.Audit.created_at.desc())
        .first()
    )
    if not latest_audit or latest_audit.seo_score is None:
        return
    if rule.condition == "below" and latest_audit.seo_score < rule.threshold:
        if (
            rule.last_triggered_at
            and (datetime.now(timezone.utc) - rule.last_triggered_at).total_seconds() < 86400
        ):
            return
        record_alert_trigger(
            db,
            rule,
            latest_audit.seo_score,
            f"SEO score dropped to {latest_audit.seo_score}% (below threshold of {rule.threshold}%)",
        )


def evaluate_aeo_score(db: Session, rule: models.AlertRule) -> None:
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == rule.project_id)
        .order_by(models.Audit.created_at.desc())
        .first()
    )
    if not latest_audit or latest_audit.aeo_score is None:
        return
    if rule.condition == "below" and latest_audit.aeo_score < rule.threshold:
        if (
            rule.last_triggered_at
            and (datetime.now(timezone.utc) - rule.last_triggered_at).total_seconds() < 86400
        ):
            return
        record_alert_trigger(
            db,
            rule,
            latest_audit.aeo_score,
            f"AIO score dropped to {latest_audit.aeo_score}% (below threshold of {rule.threshold}%)",
        )


def evaluate_featured_snippets_lost(db: Session, rule: models.AlertRule) -> None:
    user = rule.project.workspace.owner
    try:
        summary = get_serp_tracking(project_id=rule.project_id, user=user, db=db)
        if rule.condition == "above" and summary.snippets_lost >= rule.threshold:
            if (
                rule.last_triggered_at
                and (datetime.now(timezone.utc) - rule.last_triggered_at).total_seconds()
                < 86400 * 7
            ):
                return
            record_alert_trigger(
                db,
                rule,
                summary.snippets_lost,
                f"Lost {summary.snippets_lost} Featured Snippets in the last 30 days (threshold: {rule.threshold}).",
            )
    except Exception as exc:
        logger.error(
            "Error evaluating snippets lost alert for project %s: %s", rule.project_id, exc
        )


def evaluate_ai_visibility_score(db: Session, rule: models.AlertRule) -> None:
    try:
        summary = ProjectVisibilityService(db).build_summary(project=rule.project)
        score = summary.get("visibility_score")
        if score is None:
            return

        now = datetime.now(timezone.utc)
        if rule.last_triggered_at and (now - rule.last_triggered_at).total_seconds() < 86400:
            return

        if rule.condition == "below" and score < rule.threshold:
            record_alert_trigger(
                db,
                rule,
                score,
                f"AIO Score dropped to {score}% (below threshold of {rule.threshold}%).",
                event_key="alert.visibility_score_drop",
            )
            return

        if rule.condition == "drops_by":
            trend_points = summary.get("trend_delta")
            if (
                isinstance(trend_points, (int, float))
                and abs(float(trend_points)) >= rule.threshold
                and float(trend_points) < 0
            ):
                baseline_metric_value = round(score - float(trend_points), 2)
                record_alert_trigger(
                    db,
                    rule,
                    score,
                    f"AIO Score dropped by {abs(float(trend_points))}% to {score}%.",
                    event_key="alert.visibility_score_drop",
                    baseline_metric_value=baseline_metric_value,
                )
    except Exception as exc:
        logger.error("Error evaluating AIO alert for project %s: %s", rule.project_id, exc)


def evaluate_aeo_mention_drop(db: Session, rule: models.AlertRule) -> None:
    try:
        summary = ProjectOffPageMentionsService(db).build_summary(project=rule.project, days=30)
        if bool(summary.get("no_data")):
            return
        score = summary.get("off_page_aeo_score")
        if not isinstance(score, (int, float)):
            return

        now = datetime.now(timezone.utc)
        if rule.last_triggered_at and (now - rule.last_triggered_at).total_seconds() < 86400:
            return

        if rule.condition == "below" and float(score) < rule.threshold:
            record_alert_trigger(
                db,
                rule,
                float(score),
                f"Off-page visibility score dropped to {float(score):.2f}% (below threshold of {rule.threshold}%).",
                event_key="alert.aeo_mention_drop",
            )
            return

        if rule.condition == "drops_by":
            delta = summary.get("trend_delta")
            if (
                isinstance(delta, (int, float))
                and float(delta) < 0
                and abs(float(delta)) >= rule.threshold
            ):
                baseline = round(float(score) - float(delta), 2)
                record_alert_trigger(
                    db,
                    rule,
                    float(score),
                    f"Off-page visibility score dropped by {abs(float(delta)):.2f}% to {float(score):.2f}%.",
                    event_key="alert.aeo_mention_drop",
                    baseline_metric_value=baseline,
                )
    except Exception as exc:
        logger.error(
            "Error evaluating off-page mention alert for project %s: %s", rule.project_id, exc
        )


def evaluate_alerts_for_project(db: Session, project_id: int) -> None:
    rules = (
        db.query(models.AlertRule)
        .filter(
            models.AlertRule.project_id == project_id,
            models.AlertRule.is_active.is_(True),
        )
        .all()
    )
    for rule in rules:
        try:
            if rule.metric == "geo_score":
                evaluate_geo_score(db, rule)
            elif rule.metric == "seo_score":
                evaluate_seo_score(db, rule)
            elif rule.metric == "aeo_score":
                evaluate_aeo_score(db, rule)
            elif rule.metric == "featured_snippets_lost":
                evaluate_featured_snippets_lost(db, rule)
            elif rule.metric == "ai_visibility_score":
                evaluate_ai_visibility_score(db, rule)
            elif rule.metric == "aeo_mention_drop":
                evaluate_aeo_mention_drop(db, rule)
        except Exception as exc:
            logger.error("Failed to evaluate alert rule %s: %s", rule.id, exc)


def evaluate_due_project_alerts(db: Session) -> int:
    """Evaluate every project that has at least one active alert rule.

    The entry point the scheduler calls (SIGV2-1280). Before this existed,
    ``evaluate_alerts_for_project`` was reachable only from its own test file:
    customers created rules through the dashboard and through the public API,
    the rules were stored and listed back to them, and nothing ever looked at
    them. No alert could fire, and the only symptom was a notification that
    never arrived.

    One project failing does not stop the rest. A sweep that aborts halfway
    would silently starve every project after the first bad one, which is the
    same class of silence this function exists to end.

    Returns the number of projects evaluated, so the scheduler can log that
    the sweep did something.
    """
    project_ids = [
        row[0]
        for row in db.query(models.AlertRule.project_id)
        .filter(models.AlertRule.is_active.is_(True))
        .distinct()
        .all()
        if row[0] is not None
    ]
    evaluated = 0
    for project_id in project_ids:
        try:
            evaluate_alerts_for_project(db, project_id)
            evaluated += 1
        except Exception:
            logger.exception("Failed to evaluate alert rules for project %s", project_id)
    return evaluated
