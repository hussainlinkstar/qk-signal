from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from core.redis_client import get_async_redis
import os
import logging
from datetime import datetime, timezone
from typing import Any, Annotated

from database import SessionLocal
from core.config import settings, effective_gemini_api_key_from_env  # noqa: F401 - patched via system_checks.effective_gemini_api_key_from_env in tests
from auth.security import (
    get_current_admin_user,
    get_current_user,
)
from operational_settings import get_maintenance_notice
from services.serpapi_health import (
    PROBE_INVALID_KEY,
    PROBE_OPERATIONAL,
    PROBE_RATE_LIMITED,
    probe_serpapi,
)
from services.service_health import get_service_health
import models

logger = logging.getLogger(__name__)
router = APIRouter()
METRICS_KEY = os.getenv("AUDIT_QUEUE_METRICS_KEY", "audit:metrics")
# The OpenRouter LLM gateway (and its OpenAI fallback) were retired — the engine
# now runs reasoning/measurement entirely on AWS Bedrock, which is checked
# elsewhere. No external LLM-gateway provider keys are tracked here anymore.
TRACKING_PROVIDER_KEYS: tuple[tuple[str, str], ...] = ()


def get_db():
    """Dependency to get the DB session for status checks."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/health", tags=["System"])
@router.get("/system-status", tags=["System"])
async def get_system_status_public(db: Session = Depends(get_db)):
    """Public status endpoint with redacted service details."""
    payload = await _build_system_status_payload(db)
    return {
        "services": _to_public_services(payload["services"]),
        "available_models": payload.get("available_models", []),
    }


@router.get("/system-status/admin", tags=["System"])
async def get_system_status_admin(
    _: Annotated[models.User, Depends(get_current_admin_user)],
    db: Session = Depends(get_db),
):
    """Admin status endpoint with full diagnostics and metrics."""
    return await _build_system_status_payload(db)


@router.get("/maintenance-notice", tags=["System"])
def get_maintenance_notice_for_user(
    _: Annotated[models.User, Depends(get_current_user)],
    db: Session = Depends(get_db),
):
    """Scheduled-maintenance notice for the in-app banner.

    Any authenticated user may read this: the whole point of the banner is to
    warn ordinary users before a maintenance window starts. It exposes only the
    two fields the banner renders (``scheduled_start`` and ``message``), reusing
    the same operational-settings row the admin maintenance view reads, so no
    admin-only state (maintenance toggle, bypass allowlist, feature switches,
    scheduled end) can leak through it.
    """
    return {"maintenance": get_maintenance_notice(db)}


@router.get("/health/cron-sweeper", tags=["System"])
async def get_cron_sweeper_health():
    """Check cron sweeper health via Redis heartbeat.

    Returns healthy if the heartbeat key is fresh (within 3x the
    configured sweep interval), unhealthy otherwise.
    """
    try:
        async with get_async_redis(socket_timeout=2.0, socket_connect_timeout=2.0) as redis_client:
            heartbeat_raw = await redis_client.get("cron_sweeper:heartbeat")
    except Exception as e:
        return {"status": "unknown", "error": str(e)}

    if not heartbeat_raw:
        return {"status": "unhealthy", "reason": "No heartbeat found"}

    try:
        value = heartbeat_raw.decode() if isinstance(heartbeat_raw, bytes) else heartbeat_raw
        last_beat = datetime.fromisoformat(value)
        age_seconds = (datetime.now(timezone.utc) - last_beat).total_seconds()
        sweep_interval = int(os.getenv("CRON_SWEEP_INTERVAL_SECONDS", "60"))
        threshold = sweep_interval * 3

        if age_seconds > threshold:
            return {
                "status": "unhealthy",
                "reason": "Heartbeat is stale",
                "last_heartbeat": last_beat.isoformat(),
                "age_seconds": round(age_seconds, 1),
                "threshold_seconds": threshold,
            }

        return {
            "status": "healthy",
            "last_heartbeat": last_beat.isoformat(),
            "age_seconds": round(age_seconds, 1),
        }
    except Exception as e:
        return {"status": "unknown", "error": f"Invalid heartbeat value: {e}"}


def _email_transport_status(db: Session | None) -> tuple[str, str]:
    """Resolution-only SMTP check: reuse email_sender's DB-then-env lookup."""
    from services.email_sender import missing_smtp_settings

    missing = missing_smtp_settings(db)
    if not missing:
        return "Operational", ""
    return "Not Configured", (
        "SMTP transport is not fully configured; missing: " + ", ".join(missing) + "."
    )


def _stripe_billing_status(db: Session | None) -> tuple[str, str]:
    """Resolution-only Stripe check: reuse billing.config's own resolution.

    SIGV2-1270: the failure that shipped was STRIPE_MODE=test reaching
    production through an SSM override while .env said live, invisible
    because the health surface only reported the key's presence. The mode is
    resolved through load_billing_config (env + DB runtime overrides), and a
    test-mode resolution in a production environment is reported Degraded.
    No Stripe client is constructed and no API call is made.
    """
    from billing.config import load_billing_config

    config = load_billing_config(db)
    mode = str(config.stripe_mode or "test")
    source = str(getattr(config, "stripe_mode_source", "env") or "env")
    mode_details = f"Effective Stripe mode: {mode} (source: {source})."

    if settings.is_production and mode == "test":
        return "Degraded", (
            "Running in Stripe test mode in a production environment, so no "
            f"payment will be captured. {mode_details}"
        )

    _stripe_key = (
        settings.STRIPE_SECRET_KEY_LIVE if mode == "live" else settings.STRIPE_SECRET_KEY_TEST
    )
    if not str(_stripe_key or "").strip():
        return "Not Configured", (
            f"Stripe secret key is not configured for the active mode ({mode}). {mode_details}"
        )

    return "Operational", mode_details


def warn_if_email_transport_unconfigured(db: Session | None) -> None:
    """SIGV2-1272: say once, at startup, when no email can be sent. A rebuilt
    database wipes the DB-held SMTP section, so this must be loud, not
    discoverable only when a user requests a password reset."""
    status, details = _email_transport_status(db)
    if status == "Operational":
        return
    logger.warning(
        "email_transport_not_configured",
        extra={"code": "EMAIL_TRANSPORT_NOT_CONFIGURED", "details": details},
    )


async def _build_system_status_payload(db: Session) -> dict[str, Any]:
    """Performs live checks on critical internal and external services."""
    services = {
        "database": {"name": "PostgreSQL Database", "status": "Operational", "details": ""},
        "project_data_sources": {
            "name": "Project Data Sources",
            "status": "Operational",
            "details": "",
        },
        "cache": {"name": "Redis Cache", "status": "Operational", "details": ""},
        "scraper": {"name": "Firecrawl API", "status": "Operational", "details": ""},
        "stripe": {"name": "Stripe Billing", "status": "Operational", "details": ""},
        "dataforseo": {"name": "DataForSEO API", "status": "Operational", "details": ""},
        "serpapi": {"name": "SerpAPI / Search", "status": "Operational", "details": ""},
        "pagespeed": {"name": "PageSpeed Insights", "status": "Operational", "details": ""},
        "email": {"name": "Email / SMTP", "status": "Operational", "details": ""},
    }

    # Check Database
    try:
        import asyncio

        # Enforce a strict 2-second timeout to prevent blocking the worker
        await asyncio.wait_for(asyncio.to_thread(db.execute, text("SELECT 1")), timeout=2.0)
    except Exception as e:
        services["database"]["status"] = "Major Outage"
        services["database"]["details"] = "Database connection timed out or is unreachable."
        logger.error(f"System Status Check: Database connection failed. {e}")

    # Check project data source dependency
    try:
        db.execute(text("SELECT count(1) FROM project_data_sources"))
    except Exception as e:
        services["project_data_sources"]["status"] = "Major Outage"
        services["project_data_sources"]["details"] = str(e)
        logger.error("System Status Check: project_data_sources dependency check failed. %s", e)

    # Check Redis
    redis_auth = False
    redis_tls = False
    try:
        _redis_url = os.getenv("REDIS_URL", "redis://redis:6379")
        from urllib.parse import urlparse as _urlparse

        _parsed = _urlparse(_redis_url)
        redis_auth = bool(_parsed.password)
        redis_tls = _parsed.scheme in ("rediss", "rediss+sentinel")

        async with get_async_redis(socket_timeout=2.0, socket_connect_timeout=2.0) as redis_client:
            await redis_client.ping()
    except Exception as e:
        services["cache"]["status"] = "Major Outage"
        services["cache"]["details"] = "Redis connection timed out or is unreachable."
        logger.warning(f"System Status Check: Redis connection failed. {e}")

    # Check External API Keys from environment
    if not settings.FIRECRAWL_API_KEY:
        services["scraper"]["status"] = "Degraded"
        services["scraper"]["details"] = (
            "FIRECRAWL_API_KEY not configured, using httpx fallback scraper (no JS rendering, no screenshots)."
        )
    else:
        # A key being present doesn't mean the account can actually be
        # called right now (e.g. it has run out of credits). Layer the
        # real-time outcome of the last scrape/search attempt on top of the
        # static key-presence check so a billing outage shows up here
        # instead of reading as falsely Operational.
        firecrawl_health = await get_service_health("firecrawl")
        if isinstance(firecrawl_health, dict) and firecrawl_health.get("ok") is False:
            services["scraper"]["status"] = "Degraded"
            detail = str(firecrawl_health.get("detail") or "").strip()
            services["scraper"]["details"] = (
                f"Recent Firecrawl calls are failing ({detail}). Falling back to a "
                "lower-quality scraper; GEO competitor discovery may return no results."
            )

    # LLM reasoning/measurement runs on AWS Bedrock; there is no external
    # OpenRouter/OpenAI gateway key to check here anymore.

    # Stripe billing (SIGV2-1270): reports the effective billing mode
    # resolved by billing.config - a test mode in production is Degraded.
    stripe_status, stripe_details = _stripe_billing_status(db)
    services["stripe"]["status"] = stripe_status
    services["stripe"]["details"] = stripe_details

    # DataForSEO
    if not (
        str(settings.DATAFORSEO_LOGIN or "").strip()
        and str(settings.DATAFORSEO_PASSWORD or "").strip()
    ):
        services["dataforseo"]["status"] = "Not Configured"
        services["dataforseo"]["details"] = (
            "DATAFORSEO_LOGIN / DATAFORSEO_PASSWORD is not configured."
        )

    # Email transport (SIGV2-1272): resolution-only through email_sender's own
    # DB-section-then-env lookup, so health reports what sending would
    # actually get. No SMTP connection is opened here.
    email_status, email_details = _email_transport_status(db)
    services["email"]["status"] = email_status
    services["email"]["details"] = email_details

    # SerpAPI / Search
    #
    # A present key is not a working key: the public status page used to
    # publish "Operational" for a revoked SerpAPI key while every GEO
    # visibility query was failing with HTTP 401. The verdict now comes from a
    # cached probe of SerpAPI itself, and anything inconclusive reports
    # "Unknown" instead of claiming health.
    serpapi_key = str(settings.SERPAPI_API_KEY or "").strip()
    generic_search_key = str(settings.SEARCH_API_KEY or "").strip()
    if not (serpapi_key or generic_search_key):
        services["serpapi"]["status"] = "Not Configured"
        services["serpapi"]["details"] = "SERPAPI_API_KEY (or SEARCH_API_KEY) is not configured."
    elif serpapi_key:
        probe = await probe_serpapi(serpapi_key)
        probe_state = probe.get("state")
        if probe_state == PROBE_OPERATIONAL:
            services["serpapi"]["details"] = "SerpAPI accepted the configured API key."
        elif probe_state == PROBE_INVALID_KEY:
            services["serpapi"]["status"] = "Major Outage"
            services["serpapi"]["details"] = probe.get("detail", "")
        elif probe_state == PROBE_RATE_LIMITED:
            services["serpapi"]["status"] = "Degraded"
            services["serpapi"]["details"] = probe.get("detail", "")
        else:
            services["serpapi"]["status"] = "Unknown"
            services["serpapi"]["details"] = probe.get("detail", "")
    else:
        # A generic SEARCH_API provider is configured. There is no probe for
        # it yet, and an unprobed provider must not be advertised as healthy.
        services["serpapi"]["status"] = "Unknown"
        services["serpapi"]["details"] = (
            "A generic search provider (SEARCH_API_KEY) is configured. No health probe "
            "exists for it yet, so its state is unverified."
        )

    # PageSpeed Insights
    if not str(settings.PAGESPEED_API_KEY or "").strip():
        services["pagespeed"]["status"] = "Not Configured"
        services["pagespeed"]["details"] = "PAGESPEED_API_KEY is not configured."

    metrics: dict[str, Any] = {
        "jobs_started": 0,
        "jobs_succeeded": 0,
        "jobs_failed": 0,
        "job_attempts_total": 0,
        "job_retries": 0,
        "job_duration_seconds_total": 0.0,
    }
    try:
        async with get_async_redis(socket_timeout=2.0, socket_connect_timeout=2.0) as redis_client:
            metrics_raw = await redis_client.hgetall(METRICS_KEY)
        if metrics_raw:
            metrics = {
                "jobs_started": int(metrics_raw.get("jobs_started", 0)),
                "jobs_succeeded": int(metrics_raw.get("jobs_succeeded", 0)),
                "jobs_failed": int(metrics_raw.get("jobs_failed", 0)),
                "job_attempts_total": int(metrics_raw.get("job_attempts_total", 0)),
                "job_retries": int(metrics_raw.get("job_retries", 0)),
                "job_duration_seconds_total": float(
                    metrics_raw.get("job_duration_seconds_total", 0.0)
                ),
            }
    except Exception as e:
        logger.warning("System Status Check: Failed to load audit metrics. %s", e)

    available_models = [
        provider
        for service_id, provider in TRACKING_PROVIDER_KEYS
        if services.get(service_id, {}).get("status") == "Operational"
    ]

    return {
        "services": services,
        "audit_metrics": metrics,
        "available_models": available_models,
        "security_posture": {
            "redis_auth": redis_auth,
            "redis_tls": redis_tls,
        },
    }


_PUBLIC_NAME_OVERRIDES: dict[str, str] = {
    "database": "Database",
    "cache": "Cache Service",
    "scraper": "Content Scraper",
    "project_data_sources": "Data Sources",
}


def _to_public_services(services: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Redact diagnostics and anonymize infrastructure names from public status payload."""
    return {
        service_id: {
            "name": _PUBLIC_NAME_OVERRIDES.get(service_id, service["name"]),
            "status": service["status"],
        }
        for service_id, service in services.items()
    }


# ── Platform social links (public, cached) ────────────────────────────────────

_SOCIAL_LINK_FIELDS = (
    ("x", "social_x_url", "X"),
    ("linkedin", "social_linkedin_url", "LinkedIn"),
)
_SOCIAL_DEFAULTS: dict[str, str | None] = {
    "social_x_url": None,
    "social_linkedin_url": None,
}


@router.get("/platform/social-links", tags=["System"])
def get_platform_social_links(db: Session = Depends(get_db)):
    """Public endpoint returning platform social links configured by the admin.

    Used by the website footer to display dynamic social icons without
    hardcoding URLs.  Returns only non-empty links.
    """
    footer_values: dict[str, str | None] = dict(_SOCIAL_DEFAULTS)
    try:
        op_settings = db.query(models.OperationalSetting).first()
        if op_settings and isinstance(op_settings.admin_settings_payload, dict):
            raw_footer = op_settings.admin_settings_payload.get("email_footer_defaults")
            if isinstance(raw_footer, dict):
                for _, field_name, _ in _SOCIAL_LINK_FIELDS:
                    val = str(raw_footer.get(field_name) or "").strip()
                    if val and (val.startswith("http://") or val.startswith("https://")):
                        footer_values[field_name] = val
                    elif field_name in raw_footer and not val:
                        footer_values[field_name] = None
    except Exception:
        logger.warning("Failed to load platform social links from DB", exc_info=True)

    links = []
    for platform, field_name, label in _SOCIAL_LINK_FIELDS:
        url = footer_values.get(field_name)
        if url:
            links.append({"platform": platform, "label": label, "url": url})
    return {"links": links}


# In-memory ring buffer for CSP violation summaries (last N reports).
# A proper deployment would forward these to an observability backend, but
# this lightweight approach gives admins actionable data without adding a
# database table or external dependency.
_CSP_REPORT_BUFFER: list[dict[str, Any]] = []
_CSP_REPORT_BUFFER_MAX = 200
_csp_violation_count: int = 0


@router.post("/csp-report", tags=["System"], status_code=204)
async def receive_csp_report(request: Request):
    """Ingest a CSP violation report sent by the browser.

    Browsers POST a JSON payload with a ``csp-report`` key (CSP Level 2)
    or a top-level ``type`` key (Reporting API v1).  We normalise both
    formats, log the violation, and keep recent reports in memory for the
    admin posture dashboard.
    """
    global _csp_violation_count
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=204)

    # Normalise CSP Level 2 vs Reporting API v1 format
    if isinstance(body, list):
        # Reporting API v1 sends an array of reports
        for item in body:
            _ingest_single_csp_report(item.get("body", item))
        return Response(status_code=204)

    report = body.get("csp-report") or body
    _ingest_single_csp_report(report)
    return Response(status_code=204)


def _ingest_single_csp_report(report: dict[str, Any]) -> None:
    global _csp_violation_count
    _csp_violation_count += 1
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "blocked_uri": str(report.get("blocked-uri") or report.get("blockedURL", ""))[:200],
        "violated_directive": str(
            report.get("violated-directive") or report.get("effectiveDirective", "")
        )[:100],
        "document_uri": str(report.get("document-uri") or report.get("documentURL", ""))[:200],
        "source_file": str(report.get("source-file") or report.get("sourceFile", ""))[:200],
    }
    logger.info("CSP violation #%d: %s", _csp_violation_count, summary)
    _CSP_REPORT_BUFFER.append(summary)
    if len(_CSP_REPORT_BUFFER) > _CSP_REPORT_BUFFER_MAX:
        del _CSP_REPORT_BUFFER[: len(_CSP_REPORT_BUFFER) - _CSP_REPORT_BUFFER_MAX]


@router.get("/csp-report/summary", tags=["System"])
async def get_csp_report_summary(
    _: Annotated[models.User, Depends(get_current_admin_user)],
):
    """Return recent CSP violation reports and cumulative count (admin only)."""
    return {
        "total_violations": _csp_violation_count,
        "recent_reports": list(reversed(_CSP_REPORT_BUFFER[-50:])),
    }
