import logging
import os
import re
import time
import json
from contextlib import asynccontextmanager
from uuid import uuid4

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()

# Backport FastAPI OpenAPI bug fix (fastapi 0.121.1 → 0.123.1)
from core.fastapi_patches import patch_openapi_ref_handling

patch_openapi_ref_handling()

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler as fastapi_http_exception_handler,
    request_validation_exception_handler as fastapi_request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException as FastAPIHTTPException
from starlette.middleware.sessions import SessionMiddleware
from fastapi.responses import JSONResponse

from observability import (
    audit_endpoint_events_total,
    configure_logging,
    http_request_duration_seconds,
    http_requests_total,
    init_tracing,
    reset_request_id,
    set_request_id,
    status_class_from_code,
    tag_current_trace_with_request_id,
)
from system_checks import router as system_router
from admin import router as admin_router
from billing.router import router as billing_router
from core.runtime_migrations import (
    apply_pending_migrations_if_needed,
    runtime_migrations_enabled,
)
from routers.api_router import router as api_router
from routers.contact_router import router as contact_router
from routers.workspace_router import router as workspace_router
from routers.portal_router import router as portal_router
from routers.auth import router as auth_router_instance
from routers.monitoring_router import router as monitoring_router
from routers.entity_authority_router import router as entity_authority_router
from routers.benchmark_router import router as benchmark_router
from routers.cms_router import router as cms_router
from routers.embed_router import router as embed_router
from routers.guest_audit_public_router import router as guest_audit_public_router
from routers.alert_rules_router import router as alert_rules_router
from routers.jira_router import router as jira_router
from routers.scheduling_router import router as scheduling_router
from routers.slack_router import router as slack_router
from routers.teams_router import router as teams_router
from routers.workflow_router import router as workflow_router
from routers.api_keys_router import router as api_keys_router
from routers.external_api_router import router as external_api_router
from routers.internal_signal_router import router as internal_signal_router
from routers.mcp_router import router as mcp_router
from services.mcp_server_service import MCP_ENDPOINT_PATH
from routers.passkeys_router import router as passkeys_router
from routers.upload_router import router as upload_router
from routers.search_router import router as search_router
from routers import admin_alerts
from routers import admin_model_lifecycle
from routers import admin_security
from routers import admin_observability
from routers.admin_trial import router as admin_trial_router
from routers.trial_feedback_router import router as trial_feedback_router
from routers import api_router as api_module
from middleware.tenant_resolver import tenant_resolver_middleware
from middleware.runtime_cors import RuntimeCORSMiddleware
from core.config import get_env_setting_value, settings
from services.configuration_service import configuration_service

from auth.security import get_current_user_from_token as get_current_user
from app.i18n import translate_backend_message

configure_logging()
logger = logging.getLogger(__name__)

app_env = os.getenv("APP_ENV", "development").lower()
logger.info(
    "Runtime migration sync is %s for %s (RUN_MIGRATIONS=%s).",
    "enabled" if runtime_migrations_enabled() else "disabled",
    app_env,
    os.getenv("RUN_MIGRATIONS", "1"),
)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    apply_pending_migrations_if_needed()
    try:
        from database import SessionLocal
        from system_checks import warn_if_email_transport_unconfigured

        db = SessionLocal()
        try:
            warn_if_email_transport_unconfigured(db)
        finally:
            db.close()
    except Exception:
        pass
    yield
    # Graceful shutdown: close persistent HTTP clients
    try:
        from routers.api_router import ai_client as _router_ai_client

        await _router_ai_client.aclose()
    except Exception:
        pass


app = FastAPI(title="Qiko Signal Audit API", lifespan=_app_lifespan)
tracing_backend = init_tracing("audit-api")
logger.info("Tracing backend initialized: %s", tracing_backend)

app.include_router(system_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(billing_router, prefix="/api/v1")
app.include_router(contact_router, prefix="/api/v1")
app.include_router(workspace_router, prefix="/api/v1")
app.include_router(portal_router, prefix="/api/v1")
app.include_router(admin_alerts.router, prefix="/api/v1")
app.include_router(admin_model_lifecycle.router, prefix="/api/v1")
app.include_router(admin_security.router, prefix="/api/v1")
app.include_router(admin_observability.router, prefix="/api/v1")
app.include_router(admin_trial_router, prefix="/api/v1")
app.include_router(trial_feedback_router, prefix="/api/v1")
app.include_router(auth_router_instance, prefix="/api/v1")
app.include_router(monitoring_router)
app.include_router(entity_authority_router)
app.include_router(benchmark_router)
app.include_router(cms_router)
app.include_router(embed_router)
# Already prefixed with /api/v1/public, so it is registered without a prefix.
app.include_router(guest_audit_public_router)
app.include_router(alert_rules_router, prefix="/api/v1", tags=["Alert Rules"])
app.include_router(jira_router, prefix="/api/v1")
app.include_router(scheduling_router, prefix="/api/v1")
app.include_router(slack_router, prefix="/api/v1")
app.include_router(teams_router, prefix="/api/v1")
app.include_router(workflow_router, prefix="/api/v1")
app.include_router(api_keys_router, prefix="/api/v1")
app.include_router(external_api_router, prefix="/api/v1")
app.include_router(internal_signal_router, prefix="/api/v1")
# The MCP server's Streamable HTTP endpoint: POST /api/v1/mcp (SIGV2-1210).
app.include_router(mcp_router, prefix="/api/v1")
app.include_router(passkeys_router, prefix="/api/v1")
app.include_router(upload_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(api_router)


def _parse_cors_origins(raw_value: str) -> list[str]:
    value = (raw_value or "").strip()
    if not value:
        return []

    if value.startswith("["):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip().rstrip("/") for item in parsed if str(item).strip()]

    return [segment.strip().rstrip("/") for segment in value.split(",") if segment.strip()]


def _resolve_cors_origins() -> list[str]:
    origins: list[str] = []
    dynamic_cors_origins = _parse_cors_origins(
        str(
            configuration_service.resolve_value(
                "CORS_ORIGINS",
                default=get_env_setting_value("CORS_ORIGINS", default=""),
                force_refresh=True,
            )
            or ""
        )
    )
    origins.extend(dynamic_cors_origins)

    domain = str(getattr(settings, "DOMAIN", "") or "").strip()
    if domain:
        normalized_domain = domain.replace("https://", "").replace("http://", "").strip("/")
        if normalized_domain:
            origins.append(f"https://{normalized_domain}")
            origins.append(f"https://www.{normalized_domain}")

    for env_key in ("FRONTEND_URL", "APP_BASE_URL", "NEXT_PUBLIC_APP_URL"):
        env_value = str(getattr(settings, env_key, "") or "").strip()
        if env_value:
            origins.append(env_value.rstrip("/"))

    if app_env != "production":
        origins.append("http://localhost:3000")
        origins.append("http://127.0.0.1:3000")
        origins.append("http://localhost:3001")
        origins.append("http://127.0.0.1:3001")

    unique_origins = list(dict.fromkeys(origin for origin in origins if origin))
    if not unique_origins:
        logger.warning(
            "No CORS origins configured; defaulting to localhost only. Set CORS_ORIGINS/FRONTEND_URL/APP_BASE_URL for production."
        )
        return [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]

    return unique_origins


initial_cors_origins = _resolve_cors_origins()
logger.info("Initial CORS origins configured: %s", ", ".join(initial_cors_origins))

app.add_middleware(
    RuntimeCORSMiddleware,
    allow_origins_resolver=_resolve_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Request-ID", "Accept-Language"],
)
from middleware.maintenance import MaintenanceMiddleware
from middleware.session_checker import SessionRevocationMiddleware
from middleware.security_headers import SecurityHeadersMiddleware
from middleware.public_site_cors import PublicSiteCorsMiddleware

app.add_middleware(MaintenanceMiddleware)
app.add_middleware(SessionRevocationMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.resolved_session_secret,
    same_site="lax",
    https_only=settings.session_cookie_secure,
    max_age=14 * 24 * 60 * 60,
)

app.add_middleware(SecurityHeadersMiddleware)

# Registered last, so it is the outermost middleware and sees the preflight
# before the global credentialed CORS middleware rejects the marketing-site
# origin. Scoped to /api/v1/public/ and to PUBLIC_SITE_ORIGINS only.
app.add_middleware(PublicSiteCorsMiddleware)


@app.middleware("http")
async def resolve_tenant_context(request: Request, call_next):
    return await tenant_resolver_middleware(request, call_next)


_MAGIC_LINK_PATH_RE = re.compile(r"(/magic-links/)[^/]+")


def _safe_request_path(request: Request) -> str:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str) and route_path:
        return route_path
    return _MAGIC_LINK_PATH_RE.sub(r"\1{token}", request.url.path)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    token = set_request_id(request_id)
    request.state.request_id = request_id
    tag_current_trace_with_request_id(request_id)
    started_at = time.monotonic()
    logger.info(
        "Request started: %s %s (request_id=%s)",
        request.method,
        _safe_request_path(request),
        request_id,
    )
    response = None
    status_code = 500
    request.state.audit_cache_state = "na"
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    except RuntimeError as rt_err:
        # Starlette BaseHTTPMiddleware raises "No response returned" when the
        # client disconnects mid-request or a downstream middleware fails to
        # produce a response.  Return a synthetic 503 instead of letting the
        # exception propagate as unhandled log noise.
        if "No response returned" in str(rt_err):
            logger.warning(
                "Client disconnected or middleware returned no response: %s %s (request_id=%s)",
                request.method,
                _safe_request_path(request),
                request_id,
            )
            status_code = 503
            from starlette.responses import Response as RawResponse

            return RawResponse(status_code=503)
        raise
    except Exception as exc:
        logger.exception(
            "Unhandled exception during request: %s %s (request_id=%s): %s",
            request.method,
            _safe_request_path(request),
            request_id,
            exc,
        )
        raise
    finally:
        status_class = status_class_from_code(int(status_code))
        duration_seconds = time.monotonic() - started_at
        path_label = _safe_request_path(request)
        http_requests_total.labels(request.method, path_label, status_class).inc()
        http_request_duration_seconds.labels(request.method, path_label, status_class).observe(
            duration_seconds
        )
        if request.url.path == "/api/v1/audit":
            outcome = "success" if status_code < 400 else "failure"
            cache_state = getattr(request.state, "audit_cache_state", "na")
            audit_endpoint_events_total.labels(outcome, cache_state).inc()
        logger.info(
            "Request completed: %s %s (request_id=%s, status=%s, duration_s=%.4f)",
            request.method,
            _safe_request_path(request),
            request_id,
            status_code,
            duration_seconds,
        )
        reset_request_id(token)


# Re-export commonly referenced symbols for tests and downstream imports.
get_db = api_module.get_db
resolve_subscription_plan = api_module.resolve_subscription_plan
parse_rate_limit_config = api_module.parse_rate_limit_config
enforce_authenticated_audit_limit = api_module.enforce_authenticated_audit_limit
enforce_guest_audit_limit = api_module.enforce_guest_audit_limit
get_current_user = get_current_user
aeo_answerability_service = api_module.aeo_answerability_service
competitor_discovery_service = api_module.competitor_discovery_service
competitor_benchmark_service = api_module.competitor_benchmark_service
HTTPException = api_module.HTTPException
build_audit_cache_key = api_module.build_audit_cache_key
perform_audit = api_module.perform_audit
fetch_url_signature = api_module.fetch_url_signature


URL_VALIDATION_ERROR_PATHS = {
    "/api/v1/audit",
    "/api/v1/audit/jobs",
    "/api/v1/guest-audit",
    "/api/v1/public/guest-audit",
    "/api/v1/aeo/answerability",
}

# SIGV2-1172 made every plan-change failure name its own cause and carry a
# reference code, but it could only reach failures raised as HTTPException.
# FastAPI's own validation failure returns `detail` as a list of field errors,
# which carries neither a message nor a code, so the modal fell back to the
# bare "HTTP 422" and the operator was left with nothing to act on. These
# routes therefore answer a rejected body in the same shape as every other
# plan-change failure: `detail.code` and `detail.message`.
PLAN_CHANGE_VALIDATION_PATHS = {
    "/api/v1/billing/upgrade-preview",
    "/api/v1/billing/upgrade",
}

# The field a rejected plan-change body is most likely to fail on, mapped to a
# code the reference line can show. `billing_interval` is the one worth naming
# on its own: the client sends back the interval the billing payload reported
# for the current subscription, and that column carries no CHECK constraint,
# unlike `pending_billing_interval`. So a stored value outside month/year is
# echoed into a field that only accepts those two.
PLAN_CHANGE_FIELD_CODES = {
    "billing_interval": "INVALID_BILLING_INTERVAL",
    "target_plan": "INVALID_TARGET_PLAN",
}


@app.exception_handler(RequestValidationError)
async def handle_request_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith("/api/v1/external/"):
        has_url_field_error = any(
            error.get("loc") and tuple(error["loc"])[-1] in {"url", "webhook_url"}
            for error in exc.errors()
        )
        first_message = next(
            (str(error.get("msg")) for error in exc.errors() if error.get("msg")),
            "Invalid request payload.",
        )
        code = "INVALID_URL" if has_url_field_error else "VALIDATION_ERROR"
        status_code = 400 if has_url_field_error else 422
        field_errors = []
        for error in exc.errors():
            loc = error.get("loc", ())
            field = ".".join(str(part) for part in loc if part != "body")
            field_errors.append({"field": field, "message": str(error.get("msg", ""))})
        return JSONResponse(
            status_code=status_code,
            content={
                "error": {
                    "code": code,
                    "message": first_message,
                    "status": status_code,
                    "details": field_errors,
                }
            },
        )
    if request.url.path in PLAN_CHANGE_VALIDATION_PATHS:
        fields = [str(tuple(error["loc"])[-1]) for error in exc.errors() if error.get("loc")]
        # A named code is only reported when the failure is attributable to a
        # single field: a body missing both fields, or failing on both, gets
        # the generic code rather than blaming one of them.
        distinct_fields = set(fields)
        named = next((field for field in fields if field in PLAN_CHANGE_FIELD_CODES), None)
        code = (
            PLAN_CHANGE_FIELD_CODES[named]
            if named and len(distinct_fields) == 1
            else "INVALID_PLAN_CHANGE_REQUEST"
        )
        # The rejected value is deliberately not echoed back: it comes from the
        # billing payload rather than from anything the customer typed, so the
        # field name is what identifies the fault. The value is logged instead.
        logger.warning(
            "plan_change_validation_rejected",
            extra={"path": request.url.path, "fields": fields, "code": code},
        )
        return JSONResponse(
            status_code=422,
            content={
                "detail": {
                    "code": code,
                    "message": (
                        "This plan change could not be prepared because the request "
                        "was rejected before it reached billing. Your plan has not "
                        "changed. Please contact support with this reference."
                    ),
                }
            },
        )
    has_url_field_error = any(
        error.get("loc") and tuple(error["loc"])[-1] == "url" for error in exc.errors()
    )
    if request.url.path in URL_VALIDATION_ERROR_PATHS and has_url_field_error:
        return JSONResponse(
            status_code=400,
            content={
                "detail": translate_backend_message(
                    api_module.INVALID_URL_FORMAT_KEY,
                    api_module.INVALID_URL_FORMAT_DETAIL,
                    request=request,
                )
            },
        )
    return await fastapi_request_validation_exception_handler(request, exc)


def _uses_external_error_envelope(path: str) -> bool:
    """Whether a path answers failures with the API key surface's error shape.

    The external REST API and the MCP endpoint are the same surface to a
    customer: one API key, one set of error codes. SIGV2-1210 added the MCP
    endpoint here so a client does not have to parse two different error
    envelopes depending on which half of the surface refused it.
    """
    return path.startswith("/api/v1/external/") or path == MCP_ENDPOINT_PATH


@app.exception_handler(FastAPIHTTPException)
async def handle_http_exception(request: Request, exc: FastAPIHTTPException):
    if _uses_external_error_envelope(request.url.path):
        detail = exc.detail
        if isinstance(detail, dict) and {"code", "message", "status"}.issubset(detail.keys()):
            payload = {"error": detail}
        else:
            payload = {
                "error": {
                    "code": "VALIDATION_ERROR" if exc.status_code < 500 else "INTERNAL_ERROR",
                    "message": str(detail),
                    "status": exc.status_code,
                }
            }
        return JSONResponse(
            status_code=exc.status_code,
            content=payload,
            headers=getattr(exc, "headers", None) or None,
        )
    return await fastapi_http_exception_handler(request, exc)
