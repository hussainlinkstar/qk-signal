"""Alert Evaluation Worker (Task 14)

Polls system metrics every 60 seconds and evaluates active `AdminAlertRule` instances.
If a threshold is breached, records an `AdminAlertEvent` and sends notifications.
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session
from prometheus_client import REGISTRY

from database import SessionLocal
from models import AdminAlertRule, AdminAlertEvent, AdminNotificationChannel, EmailOutbox
from services.email_service import EmailService
from admin import _get_redis_metrics, _get_db_pool_metrics, _get_request_stats

logger = logging.getLogger(__name__)

# List of default rules injected on first run
DEFAULT_ADMIN_ALERTS = [
    {
        "name": "High Error Rate",
        "metric_key": "error_rate_5xx",
        "condition": "above",
        "threshold_value": 5.0,
        "severity": "critical",
    },
    {
        "name": "Audit Queue Backlog",
        "metric_key": "queue_depth_audit",
        "condition": "above",
        "threshold_value": 100,
        "severity": "warning",
    },
    {
        "name": "Worker Down",
        "metric_key": "worker_dead_count",
        "condition": "above",
        "threshold_value": 0,
        "severity": "critical",
    },
    {
        "name": "Email Delivery Failures",
        "metric_key": "email_failure_rate",
        "condition": "above",
        "threshold_value": 10.0,
        "severity": "warning",
    },
    {
        "name": "Quality Gate Failure Rate",
        "metric_key": "quality_gate_failure_rate",
        "condition": "above",
        "threshold_value": 30.0,
        "severity": "warning",
    },
]


async def collect_metric(db: Session, key: str) -> float:
    """Collect the current value for a given metric key."""
    if key in ("error_rate_5xx", "error_rate_4xx"):
        stats = _get_request_stats()
        # the _get_request_stats dict has error_rate_percent (which is 5xx + 4xx),
        # let's be more precise by reading prometheus again or using stats.
        if key == "error_rate_5xx":
            try:
                requests: dict[str, float] = {}
                for metric in REGISTRY.collect():
                    if metric.name == "http_requests_total":
                        for sample in metric.samples:
                            if sample.name == "http_requests_total_total":
                                status_class = sample.labels.get("status_class", "unknown")
                                requests[status_class] = (
                                    requests.get(status_class, 0) + sample.value
                                )
                total = sum(requests.values())
                errors = requests.get("5xx", 0)
                return round((errors / max(total, 1)) * 100, 2)
            except Exception:
                return 0.0
        elif key == "error_rate_4xx":
            stats = _get_request_stats()
            return stats.get("error_rate_percent", 0.0)  # Approx

    if key.startswith("queue_depth_"):
        q_name = key.replace("queue_depth_", "")
        if q_name == "audit":
            # Sum across all tier-specific audit queues
            from services.queue_routing import ALL_CONSUMER_QUEUES

            redis_metrics = await _get_redis_metrics()
            depths = redis_metrics.get("queue_depths", {})
            return float(sum(depths.get(q, 0) for q in ALL_CONSUMER_QUEUES))
        elif q_name == "pdf":
            q_name = "pdf_jobs"
        elif q_name == "billing":
            q_name = "billing:webhook_events"
        elif q_name == "email":
            # Count DB
            return db.query(EmailOutbox).filter(EmailOutbox.status == "pending").count()

        redis_metrics = await _get_redis_metrics()
        return float(redis_metrics.get("queue_depths", {}).get(q_name, 0))

    if key == "worker_dead_count":
        redis_metrics = await _get_redis_metrics()
        workers = redis_metrics.get("workers", [])
        return float(sum(1 for w in workers if w.get("status") == "dead"))

    if key == "email_failure_rate":
        # Rough proxy: failed vs sent over last hour
        now = datetime.now(timezone.utc)
        hour_ago = now - timedelta(hours=1)
        failed = (
            db.query(EmailOutbox)
            .filter(EmailOutbox.status == "failed", EmailOutbox.created_at >= hour_ago)
            .count()
        )
        sent = (
            db.query(EmailOutbox)
            .filter(EmailOutbox.status == "sent", EmailOutbox.created_at >= hour_ago)
            .count()
        )
        total = failed + sent
        return round((failed / max(total, 1)) * 100, 2)

    if key == "db_pool_exhaustion":
        db_metrics = _get_db_pool_metrics(db)
        pool_size = db_metrics.get("pool_size", 1) + db_metrics.get("max_overflow", 0)
        checked_out = db_metrics.get("checked_out", 0)
        return round((checked_out / max(pool_size, 1)) * 100, 2)

    if key == "redis_memory_mb":
        redis_metrics = await _get_redis_metrics()
        return float(redis_metrics.get("used_memory_mb", 0.0))

    if key == "quality_gate_failure_rate":
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)
        from routers.admin_observability import _collect_prompt_quality_gate_metrics

        metrics = _collect_prompt_quality_gate_metrics(
            db=db,
            cutoff_date=cutoff,
            window_days=1,
        )
        return round(metrics.get("failure_rate", 0.0) * 100, 2)

    return 0.0


def evaluate_condition(current: float, condition: str, threshold: float) -> bool:
    if condition == "above":
        return current > threshold
    elif condition == "below":
        return current < threshold
    elif condition == "equals":
        return current == threshold
    return False


def in_cooldown(db: Session, rule: AdminAlertRule) -> bool:
    """Check if the rule has fired within its cooldown period."""
    last_event = (
        db.query(AdminAlertEvent)
        .filter(AdminAlertEvent.rule_id == rule.id)
        .order_by(AdminAlertEvent.created_at.desc())
        .first()
    )

    if not last_event:
        return False

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.cooldown_minutes)
    return last_event.created_at >= cutoff


async def send_slack_notification(event: AdminAlertEvent, db: Session) -> bool:
    """Send webhook POST to active Slack channels."""
    from services.url_validation import SSRFBlockedError, safe_async_fetch

    channels = (
        db.query(AdminNotificationChannel)
        .filter(
            AdminNotificationChannel.channel_type == "slack", AdminNotificationChannel.is_active
        )
        .all()
    )

    if not channels:
        return False

    success = False
    message = f"*[{event.severity.upper()}] {event.message}*"

    for channel in channels:
        webhook_url = (channel.config_json or {}).get("webhook_url")
        if webhook_url:
            try:
                await safe_async_fetch(
                    webhook_url,
                    method="POST",
                    json={"text": message},
                    timeout=5.0,
                )
                success = True
            except SSRFBlockedError as e:
                logger.warning("Slack webhook blocked by SSRF policy: %s", e)
            except Exception as e:
                logger.error(f"Failed to post to Slack: {e}")

    return success


async def seed_default_rules(db: Session):
    for default_rule in DEFAULT_ADMIN_ALERTS:
        exists = db.query(AdminAlertRule).filter_by(metric_key=default_rule["metric_key"]).first()
        if not exists:
            rule = AdminAlertRule(**default_rule)
            db.add(rule)
    db.commit()


async def evaluate_admin_alerts():
    """Main evaluation loop, designed to be called every 60s."""
    db = SessionLocal()
    try:
        # Idempotently seed defaults
        await seed_default_rules(db)

        rules = db.query(AdminAlertRule).filter(AdminAlertRule.is_active).all()
        for rule in rules:
            try:
                current_value = await collect_metric(db, rule.metric_key)
                triggered = evaluate_condition(current_value, rule.condition, rule.threshold_value)

                if triggered and not in_cooldown(db, rule):
                    message = f"{rule.name}: {rule.metric_key} is {current_value} ({rule.condition} {rule.threshold_value})"
                    logger.warning(f"Admin Alert Triggered: {message}")

                    event = AdminAlertEvent(
                        rule_id=rule.id,
                        metric_key=rule.metric_key,
                        current_value=current_value,
                        threshold_value=rule.threshold_value,
                        severity=rule.severity,
                        message=message,
                    )
                    db.add(event)
                    db.commit()
                    db.refresh(event)

                    notifications = {}
                    if rule.notify_email:
                        # Send to ADMIN_EMAILS
                        from core.config import settings

                        admin_emails_raw = str(getattr(settings, "ADMIN_EMAILS", "") or "")
                        admin_emails = [e.strip() for e in admin_emails_raw.split(",") if e.strip()]

                        if admin_emails:
                            # Queue email
                            email_service = EmailService(db)
                            email_service.queue_template_email(
                                to_email=admin_emails[
                                    0
                                ],  # Just send to first admin for now, or could generate multiple
                                template_name="admin_system_alert",
                                subject=f"[{event.severity.upper()}] System Alert: {rule.name}",
                                context={
                                    "rule_name": rule.name,
                                    "severity": event.severity,
                                    "message": message,
                                    "current_value": current_value,
                                    "threshold_value": rule.threshold_value,
                                    "metric_key": rule.metric_key,
                                    "timestamp": datetime.now(timezone.utc).strftime(
                                        "%Y-%m-%d %H:%M:%S UTC"
                                    ),
                                },
                            )
                            notifications["email"] = True

                    if rule.notify_slack:
                        notifications["slack"] = await send_slack_notification(event, db)

                    event.notifications_sent = notifications
                    db.commit()
            except Exception as e:
                logger.error(f"Error evaluating rule {rule.id}: {e}")

    finally:
        db.close()


if __name__ == "__main__":
    from core.env_bootstrap import bootstrap_environment

    bootstrap_environment()
    asyncio.run(evaluate_admin_alerts())
