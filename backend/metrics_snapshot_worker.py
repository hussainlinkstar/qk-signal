import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from prometheus_client import REGISTRY

import models

logger = logging.getLogger(__name__)


def collect_metrics_snapshot(db: Session) -> None:
    """Read from Prometheus registry and save a snapshot to the database."""
    try:
        snapshot = models.MetricsSnapshot(snapshot_at=datetime.now(timezone.utc))

        requests_2xx = 0
        requests_4xx = 0
        requests_5xx = 0
        total_requests = 0

        total_duration = 0.0
        total_duration_count = 0
        duration_stats = {}
        completed = 0
        failed = 0

        for metric in REGISTRY.collect():
            if metric.name == "http_requests_total":
                for sample in metric.samples:
                    status_class = sample.labels.get("status_class", "")
                    val = int(sample.value)
                    total_requests += val
                    if status_class == "2xx":
                        requests_2xx += val
                    elif status_class == "4xx":
                        requests_4xx += val
                    elif status_class == "5xx":
                        requests_5xx += val

            elif metric.name == "http_request_duration_seconds":
                for sample in metric.samples:
                    path = sample.labels.get("path", "unknown")
                    method = sample.labels.get("method", "GET")
                    endpoint_key = f"{method} {path}"

                    if endpoint_key not in duration_stats:
                        duration_stats[endpoint_key] = {"sum": 0.0, "count": 0}

                    if sample.name == "http_request_duration_seconds_sum":
                        duration_stats[endpoint_key]["sum"] = sample.value
                        total_duration += sample.value
                    elif sample.name == "http_request_duration_seconds_count":
                        duration_stats[endpoint_key]["count"] = sample.value
                        total_duration_count += sample.value

            elif metric.name == "worker_job_events_total":
                for sample in metric.samples:
                    outcome = sample.labels.get("outcome", "")
                    if outcome == "success":
                        completed += int(sample.value)
                    elif outcome == "failure" or outcome == "error":
                        failed += int(sample.value)

        snapshot.requests_total = total_requests
        snapshot.requests_2xx = requests_2xx
        snapshot.requests_4xx = requests_4xx
        snapshot.requests_5xx = requests_5xx

        slow_endpoints = {}
        for ep, stats in duration_stats.items():
            if stats["count"] > 0:
                avg = stats["sum"] / stats["count"]
                if avg > 0.5:  # 500ms threshold
                    slow_endpoints[ep] = round(avg * 1000, 1)  # Store in ms

        if total_duration_count > 0:
            snapshot.latency_avg_ms = (total_duration / total_duration_count) * 1000

        snapshot.slow_endpoints = slow_endpoints
        snapshot.audit_jobs_completed = completed
        snapshot.audit_jobs_failed = failed

        db.add(snapshot)
        db.commit()

    except Exception as e:
        logger.error(f"Failed to collect metrics snapshot: {e}")
        db.rollback()
