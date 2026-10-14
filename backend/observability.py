import logging
import os
from contextvars import ContextVar, Token
from typing import Any, Literal

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

RequestStatusClass = Literal["2xx", "3xx", "4xx", "5xx"]

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

http_requests_total = Counter(
    "http_requests_total",
    "Total HTTP requests processed by the API.",
    ["method", "path", "status_class"],
)
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path", "status_class"],
)

audit_endpoint_events_total = Counter(
    "audit_endpoint_events_total",
    "Outcome and cache behavior for /api/v1/audit.",
    ["outcome", "cache"],
)

audit_db_retries_total = Counter(
    "audit_db_retries_total",
    "DB retry attempts for persisting audit records.",
    ["source"],
)

stripe_event_outcomes_total = Counter(
    "stripe_event_outcomes_total",
    "Bounded outcomes for durable Stripe event processing.",
    ["outcome"],
)


stripe_command_events_total = Counter(
    "stripe_command_events_total",
    "Outcome counters for durable Stripe commands.",
    ["event", "command_type", "stripe_mode", "error_code"],
)


worker_job_events_total = Counter(
    "worker_job_events_total",
    "Outcome counters for async audit jobs.",
    ["outcome"],
)

visibility_worker_events_total = Counter(
    "visibility_worker_events_total",
    "Outcome counters for visibility index worker runs.",
    ["outcome"],
)

audit_dual_track_claims_total = Counter(
    "audit_dual_track_claims_total",
    "Per-track shadow claim dispositions observed during dual-track grounding.",
    ["track", "disposition"],
)

audit_dual_track_reason_codes_total = Counter(
    "audit_dual_track_reason_codes_total",
    "Reason-code counters observed during dual-track shadow evaluation.",
    ["track", "reason_code"],
)

audit_dual_track_fallback_total = Counter(
    "audit_dual_track_fallback_total",
    "Fail-safe fallback reasons encountered by dual-track grounding.",
    ["fallback_reason"],
)

# ── Cron sweeper metrics ─────────────────────────────────────────────────────

cron_sweep_runs_total = Counter(
    "cron_sweep_runs_total",
    "Total cron sweep cycle executions.",
    ["status"],
)

cron_sweep_duration_seconds = Histogram(
    "cron_sweep_duration_seconds",
    "Duration of each cron sweep cycle in seconds.",
)

cron_sweep_errors_total = Counter(
    "cron_sweep_errors_total",
    "Total errors encountered during cron sweep cycles.",
)

cron_sweep_last_success_timestamp = Gauge(
    "cron_sweep_last_success_timestamp",
    "Unix timestamp of the last successful cron sweep.",
)

# ── Worker concurrency & queue depth ─────────────────────────────────────────

worker_concurrent_jobs = Gauge(
    "worker_concurrent_jobs",
    "Number of audit jobs currently being processed concurrently by the worker.",
)

worker_queue_depth = Gauge(
    "worker_queue_depth",
    "Number of jobs waiting in a Redis audit queue.",
    ["tier"],
)

worker_job_wait_seconds = Histogram(
    "worker_job_wait_seconds",
    "Time a job spent waiting in the queue before being picked up (seconds).",
    buckets=[0.5, 1, 2, 5, 10, 30, 60, 120, 300, 600],
)


class RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def configure_logging() -> None:
    if getattr(configure_logging, "_configured", False):
        return

    root_logger = logging.getLogger()
    log_level_name = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    log_level = logging.getLevelNamesMapping().get(log_level_name, logging.INFO)
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] [request_id=%(request_id)s] %(message)s"
        )
    )
    handler.addFilter(RequestIdLogFilter())
    root_logger.addHandler(handler)

    setattr(configure_logging, "_configured", True)


def set_request_id(request_id: str) -> Token:
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token) -> None:
    _request_id_ctx.reset(token)


def get_request_id() -> str:
    return _request_id_ctx.get()


def status_class_from_code(status_code: int) -> RequestStatusClass:
    if 200 <= status_code < 300:
        return "2xx"
    if 300 <= status_code < 400:
        return "3xx"
    if 400 <= status_code < 500:
        return "4xx"
    return "5xx"


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


def _resolve_sentry_dsn_for_service(service_name: str) -> str:
    normalized_service_name = service_name.upper().replace("-", "_").strip("_")
    candidate_keys = [f"SENTRY_DSN_{normalized_service_name}", "SENTRY_DSN"]
    for key in candidate_keys:
        value = os.getenv(key, "").strip()
        if value:
            return value
    return ""


def init_tracing(service_name: str) -> str:
    disable_tracing = os.getenv("DISABLE_TRACING", "").strip().lower() in {"1", "true", "yes"}
    if disable_tracing:
        return "none"

    backend = os.getenv("TRACING_BACKEND", "none").strip().lower()
    dsn = _resolve_sentry_dsn_for_service(service_name)
    if backend != "sentry":
        if dsn:
            logging.getLogger(__name__).info(
                "Sentry DSN is configured for %s but TRACING_BACKEND=%s; tracing is disabled.",
                service_name,
                backend,
            )
        return "none"

    if not dsn:
        return "disabled"

    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    traces_sample_rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.2"))

    def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
        request_id = get_request_id()
        if request_id and request_id != "-":
            tags = event.setdefault("tags", {})
            tags.setdefault("request_id", request_id)
        return event

    integrations: list[Any] = [LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)]
    if service_name in {"audit-api", "ai-service"}:
        integrations.append(FastApiIntegration())

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        traces_sample_rate=traces_sample_rate,
        environment=os.getenv("SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development")),
        release=os.getenv("SENTRY_RELEASE"),
        before_send=_before_send,
    )
    sentry_sdk.set_tag("service", service_name)
    return "sentry"


def tag_current_trace_with_request_id(request_id: str) -> None:
    backend = os.getenv("TRACING_BACKEND", "none").strip().lower()
    if backend != "sentry":
        return
    try:
        import sentry_sdk

        sentry_sdk.set_tag("request_id", request_id)
    except Exception:
        return
