from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import redis
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature, resolve_plan_alias
from core.redis_client import get_sync_redis
from database import get_db

API_KEY_PREFIX = "stx_live_"
EXTERNAL_JOB_SOURCE = "external"
# The closed allow-list of API key scopes. Every scope here is enforced by at
# least one external route, and no route enforces a scope that is missing from
# it; backend/tests/test_api_key_scopes.py pins that agreement. Project tasks
# are covered by projects:read, so the retired tasks:read scope is absent.
API_KEY_SCOPES: tuple[str, ...] = (
    "audit:read",
    "audit:write",
    "projects:read",
    "reports:read",
    "reports:write",
    "schedules:read",
    "schedules:write",
    "competitors:read",
    "entities:read",
    "monitoring:read",
    "workflows:read",
    "workflows:write",
    "alerts:read",
    "alerts:write",
)
# What a key gets when the caller names no scopes: read access only. Starting a
# paid audit, writing a schedule or changing an alert has to be chosen, never
# handed out by omission.
DEFAULT_API_KEY_SCOPES: tuple[str, ...] = tuple(
    scope for scope in API_KEY_SCOPES if scope.endswith(":read")
)
DEFAULT_EXTERNAL_PROVIDER = (
    os.getenv("EXTERNAL_API_DEFAULT_PROVIDER") or "google"
).strip().lower() or "google"
EXTERNAL_RATE_LIMITS: dict[str, dict[str, int]] = {
    "plan_specialist": {"minute": 60, "day": 1000},
    "plan_executive": {"minute": 300, "day": 10000},
}


@dataclass(frozen=True)
class ExternalAPIPrincipal:
    user: models.User
    api_key: models.ApiKey
    plan: str


def external_error(
    *,
    code: str,
    message: str,
    status_code: int,
    headers: Mapping[str, str] | None = None,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "status": status_code,
        },
        headers=dict(headers or {}),
    )


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def hash_idempotency_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def build_idempotency_fingerprint(payload: Mapping[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_api_key_material() -> tuple[str, str, str, str]:
    token = secrets.token_hex(16)
    raw_key = f"{API_KEY_PREFIX}{token}"
    return raw_key, hash_api_key(raw_key), API_KEY_PREFIX, token[-4:]


def resolve_external_plan(user: models.User) -> str:
    resolved_plan = resolve_plan_alias(
        user.subscription.plan_type if user.subscription and user.subscription.plan_type else None
    )
    subscription_status = (
        (user.subscription.status or "").strip().lower()
        if user.subscription and user.subscription.status
        else ""
    )
    if not resolved_plan or not can_use_feature(resolved_plan, "api_access"):
        raise external_error(
            code="PLAN_NOT_ELIGIBLE",
            message="External API access is available on Specialist and Executive plans.",
            status_code=403,
        )
    if subscription_status not in {"active", "trialing"}:
        raise external_error(
            code="PLAN_NOT_ELIGIBLE",
            message="Your subscription must be active before using the external API.",
            status_code=403,
        )
    return resolved_plan


def _extract_raw_api_key(request: Request) -> str | None:
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate:
            return candidate

    x_api_key = (request.headers.get("x-api-key") or "").strip()
    if x_api_key:
        return x_api_key
    return None


def _normalize_scopes(value: Any) -> list[str]:
    """Return the scopes a stored key actually grants.

    Only stored scopes still on the allow-list count. A key minted before a
    scope was retired keeps whatever is left, and never falls back to the
    default grant, because that would widen the key instead of narrowing it.
    """
    if isinstance(value, list):
        scopes = [str(scope).strip().lower() for scope in value if str(scope).strip()]
    else:
        scopes = []
    if not scopes:
        return list(DEFAULT_API_KEY_SCOPES)
    recognized: list[str] = []
    for scope in scopes:
        if scope in API_KEY_SCOPES and scope not in recognized:
            recognized.append(scope)
    return recognized


def validate_api_key_scopes(value: Any) -> list[str]:
    """Normalize requested scopes, refusing anything outside the allow-list."""
    if value is None:
        return list(DEFAULT_API_KEY_SCOPES)
    if not isinstance(value, list):
        raise ValueError("Scopes must be a list of scope names.")
    requested = [str(scope).strip().lower() for scope in value if str(scope).strip()]
    if not requested:
        return list(DEFAULT_API_KEY_SCOPES)
    unknown = sorted({scope for scope in requested if scope not in API_KEY_SCOPES})
    if unknown:
        raise ValueError(
            "Unsupported scope: "
            + ", ".join(unknown)
            + ". Supported scopes: "
            + ", ".join(API_KEY_SCOPES)
            + "."
        )
    ordered: list[str] = []
    for scope in API_KEY_SCOPES:
        if scope in requested:
            ordered.append(scope)
    return ordered


async def get_api_key_principal(
    request: Request,
    db: Session = Depends(get_db),
) -> ExternalAPIPrincipal:
    raw_key = _extract_raw_api_key(request)
    if not raw_key or not raw_key.startswith(API_KEY_PREFIX):
        raise external_error(
            code="INVALID_API_KEY",
            message="A valid API key is required.",
            status_code=401,
        )

    api_key = (
        db.query(models.ApiKey).filter(models.ApiKey.key_hash == hash_api_key(raw_key)).first()
    )
    if (
        api_key is None
        or api_key.user is None
        or not bool(api_key.is_active)
        or api_key.revoked_at is not None
    ):
        raise external_error(
            code="INVALID_API_KEY",
            message="The supplied API key is invalid or revoked.",
            status_code=401,
        )

    plan = resolve_external_plan(api_key.user)
    api_key.last_used_at = datetime.now(timezone.utc)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return ExternalAPIPrincipal(user=api_key.user, api_key=api_key, plan=plan)


def assert_known_api_key_scope(scope: str) -> str:
    """Return ``scope``, or raise at import time if it is not on the allow-list.

    Every surface that guards something with a scope goes through here, so a
    scope the code does not know cannot be enforced anywhere: not on a route,
    not on an MCP tool. The failure is deliberately at import time rather than
    on the first request, because a guard nobody can satisfy and a guard that
    silently does nothing look identical to a caller.
    """
    if scope not in API_KEY_SCOPES:
        raise ValueError(
            f"{scope} is not an API key scope. Add it to API_KEY_SCOPES before guarding a route "
            "with it, so the advertised list and the enforcement cannot drift apart."
        )
    return scope


def principal_grants_scope(principal: ExternalAPIPrincipal, scope: str) -> bool:
    """Whether the authenticated key really grants ``scope`` right now."""
    return scope in _normalize_scopes(principal.api_key.scopes)


def require_principal_scope(principal: ExternalAPIPrincipal, scope: str) -> None:
    """Enforce one scope against an already-authenticated principal.

    The scope check for callers that are not a single FastAPI route, which is
    the MCP server: one endpoint dispatching several tools, each with its own
    scope. It reads the same stored scopes through the same normalizer as
    ``require_api_key_scope``, so there is one scope vocabulary and one place
    that decides what a stored scope list grants.
    """
    if not principal_grants_scope(principal, scope):
        raise external_error(
            code="INVALID_API_KEY",
            message=f"This API key does not include the required scope: {scope}.",
            status_code=403,
        )


def require_api_key_scope(scope: str) -> Callable[..., ExternalAPIPrincipal]:
    assert_known_api_key_scope(scope)

    async def _dependency(
        principal: ExternalAPIPrincipal = Depends(get_api_key_principal),
    ) -> ExternalAPIPrincipal:
        require_principal_scope(principal, scope)
        return principal

    _dependency.api_key_scope = scope
    return _dependency


def _increment_with_expiry(
    redis_client: redis.Redis,
    *,
    key: str,
    window_seconds: int,
) -> tuple[int, int]:
    current = int(redis_client.incr(key))
    if current == 1:
        redis_client.expire(key, window_seconds)
    ttl = int(redis_client.ttl(key))
    if ttl < 0:
        ttl = window_seconds
    return current, ttl


async def enforce_external_rate_limit(
    *,
    response: Response,
    principal: ExternalAPIPrincipal,
) -> None:
    plan_limits = EXTERNAL_RATE_LIMITS.get(principal.plan)
    if not plan_limits:
        raise external_error(
            code="RATE_LIMIT_CONFIGURATION_MISSING",
            message="External API access is temporarily unavailable for this plan.",
            status_code=503,
        )

    minute_limit = int(plan_limits["minute"])
    day_limit = int(plan_limits["day"])
    minute_key = f"ratelimit:external:{principal.api_key.id}:minute"
    day_key = f"ratelimit:external:{principal.api_key.id}:day"

    with get_sync_redis() as redis_client:
        minute_current, minute_ttl = _increment_with_expiry(
            redis_client,
            key=minute_key,
            window_seconds=60,
        )
        day_current, day_ttl = _increment_with_expiry(
            redis_client,
            key=day_key,
            window_seconds=86400,
        )

    minute_remaining = max(0, minute_limit - minute_current)
    day_remaining = max(0, day_limit - day_current)
    now = int(time.time())
    headers = {
        "X-RateLimit-Limit": str(minute_limit),
        "X-RateLimit-Remaining": str(minute_remaining),
        "X-RateLimit-Reset": str(now + max(0, minute_ttl)),
        "X-RateLimit-Day-Limit": str(day_limit),
        "X-RateLimit-Day-Remaining": str(day_remaining),
        "X-RateLimit-Day-Reset": str(now + max(0, day_ttl)),
    }

    for header_name, header_value in headers.items():
        response.headers[header_name] = header_value

    if minute_current > minute_limit or day_current > day_limit:
        retry_after = max(1, minute_ttl if minute_current > minute_limit else day_ttl)
        headers["Retry-After"] = str(retry_after)
        raise external_error(
            code="RATE_LIMIT_EXCEEDED",
            message="Rate limit exceeded for this API key.",
            status_code=429,
            headers=headers,
        )


def serialize_api_key(api_key: models.ApiKey) -> dict[str, Any]:
    return {
        "id": int(api_key.id),
        "name": api_key.name,
        "key_prefix": api_key.key_prefix or API_KEY_PREFIX,
        "key_last_four": api_key.key_last_four,
        "scopes": _normalize_scopes(api_key.scopes),
        "is_active": bool(api_key.is_active) and api_key.revoked_at is None,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "revoked_at": api_key.revoked_at.isoformat() if api_key.revoked_at else None,
    }


def map_external_job_status(status: str | None) -> str:
    normalized = (status or "queued").strip().lower()
    if normalized == "succeeded":
        return "completed"
    return normalized


def audit_overall_score(audit: models.Audit) -> float | None:
    """One overall visibility score for an audit.

    Prefers the report's own ``scores.overall`` and falls back to the mean of
    the available pillar scores, so a consumer reads one number without
    recomputing it. Lives here rather than in a router because the external
    API and the MCP server both answer with it and must answer the same.
    """
    report = audit.full_report if isinstance(audit.full_report, dict) else {}
    scores = report.get("scores") if isinstance(report.get("scores"), dict) else {}
    overall = scores.get("overall")
    if isinstance(overall, (int, float)):
        return float(overall)
    pillars = [
        value
        for value in (audit.seo_score, audit.geo_score, audit.aeo_score)
        if isinstance(value, (int, float))
    ]
    if not pillars:
        return None
    return round(sum(pillars) / len(pillars), 1)


def serialize_audit_scores(audit: models.Audit | None) -> dict[str, float | None] | None:
    return (
        None
        if audit is None
        else {
            "geo": audit.geo_score,
            "seo": audit.seo_score,
            "aeo": audit.aeo_score,
            "overall": audit_overall_score(audit),
        }
    )
