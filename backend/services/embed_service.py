from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature, resolve_plan_alias
from core.redis_client import get_async_redis

EMBED_API_KEY_PREFIX = "stx_embed_"


@dataclass(frozen=True)
class EmbedPrincipal:
    user: models.User
    api_key: models.EmbedApiKey


def hash_embed_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_embed_api_key_material() -> tuple[str, str, str, str]:
    token = secrets.token_hex(16)
    raw_key = f"{EMBED_API_KEY_PREFIX}{token}"
    return raw_key, hash_embed_api_key(raw_key), EMBED_API_KEY_PREFIX, token[-4:]


def normalize_origin(value: str) -> str:
    normalized = str(value or "").strip().lower().rstrip("/")
    if not normalized:
        raise ValueError("Origin cannot be empty.")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Origins must include http(s) scheme and host.")
    return f"{parsed.scheme}://{parsed.netloc}"


def normalize_allowed_origins(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for candidate in values:
        origin = normalize_origin(candidate)
        if origin not in normalized:
            normalized.append(origin)
    if not normalized:
        raise ValueError("At least one allowed origin is required.")
    return normalized


def origin_allowed(origin: str | None, allowed_origins: list[str] | None) -> bool:
    if not origin:
        return True
    try:
        normalized_origin = normalize_origin(origin)
    except ValueError:
        return False
    allowed = {
        str(item).strip().lower().rstrip("/")
        for item in (allowed_origins or [])
        if str(item).strip()
    }
    return normalized_origin in allowed


def _extract_embed_key(request: Request) -> str | None:
    authorization = (request.headers.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if candidate:
            return candidate

    x_embed_key = (request.headers.get("x-embed-key") or "").strip()
    if x_embed_key:
        return x_embed_key

    return None


def resolve_embed_plan(user: models.User) -> str:
    resolved_plan = resolve_plan_alias(
        user.subscription.plan_type if user.subscription and user.subscription.plan_type else None
    )
    subscription_status = (
        (user.subscription.status or "").strip().lower()
        if user.subscription and user.subscription.status
        else ""
    )
    if not resolved_plan or not can_use_feature(resolved_plan, "lead_widget"):
        raise HTTPException(
            status_code=402,
            detail="Lead widgets are available on Specialist and Executive plans.",
        )
    if subscription_status not in {"active", "trialing"}:
        raise HTTPException(
            status_code=402,
            detail="Your subscription must be active before using lead widgets.",
        )
    return resolved_plan


def validate_embed_origin(*, request: Request, api_key: models.EmbedApiKey) -> str | None:
    request_origin = (request.headers.get("origin") or "").strip() or None
    if not origin_allowed(
        request_origin, api_key.allowed_origins if isinstance(api_key.allowed_origins, list) else []
    ):
        raise HTTPException(status_code=403, detail="Origin is not allowed for this embed key.")
    return request_origin


def build_embed_cors_headers(origin: str | None) -> dict[str, str]:
    if not origin:
        return {}
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "Authorization,Content-Type,X-Embed-Key,X-Request-ID",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Vary": "Origin",
    }


def serialize_embed_key(api_key: models.EmbedApiKey) -> dict[str, object]:
    return {
        "id": int(api_key.id),
        "workspace_id": int(api_key.workspace_id),
        "user_id": int(api_key.user_id),
        "label": api_key.label,
        "allowed_origins": [str(item) for item in (api_key.allowed_origins or [])],
        "daily_limit": int(api_key.daily_limit or 100),
        "is_active": bool(api_key.is_active),
        "key_prefix": api_key.key_prefix or EMBED_API_KEY_PREFIX,
        "key_last_four": api_key.key_last_four,
        "last_used_at": api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        "created_at": api_key.created_at.isoformat() if api_key.created_at else None,
        "schema_version": str(api_key.schema_version or "1"),
    }


async def authenticate_embed_key(
    *,
    request: Request,
    db: Session,
    enforce_origin: bool = True,
) -> tuple[EmbedPrincipal, str | None]:
    raw_key = _extract_embed_key(request)
    if not raw_key or not raw_key.startswith(EMBED_API_KEY_PREFIX):
        raise HTTPException(status_code=401, detail="A valid embed API key is required.")

    api_key = (
        db.query(models.EmbedApiKey)
        .filter(models.EmbedApiKey.key_hash == hash_embed_api_key(raw_key))
        .first()
    )
    if api_key is None or api_key.user is None or not bool(api_key.is_active):
        raise HTTPException(
            status_code=401, detail="The supplied embed API key is invalid or revoked."
        )

    request_origin = None
    if enforce_origin:
        request_origin = validate_embed_origin(request=request, api_key=api_key)

    resolve_embed_plan(api_key.user)

    api_key.last_used_at = datetime.now(timezone.utc)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return EmbedPrincipal(user=api_key.user, api_key=api_key), request_origin


async def enforce_embed_daily_limit(
    *,
    response: Response,
    api_key: models.EmbedApiKey,
) -> None:
    date_key = datetime.now(timezone.utc).strftime("%Y%m%d")
    redis_key = f"embed_rate:{api_key.id}:{date_key}"
    daily_limit = max(1, int(api_key.daily_limit or 100))
    async with get_async_redis() as redis_client:
        current = int(await redis_client.incr(redis_key))
        if current == 1:
            await redis_client.expire(redis_key, 86400)
        ttl = int(await redis_client.ttl(redis_key))

    ttl = ttl if ttl > 0 else 86400
    response.headers["X-RateLimit-Day-Limit"] = str(daily_limit)
    response.headers["X-RateLimit-Day-Remaining"] = str(max(0, daily_limit - current))
    response.headers["X-RateLimit-Day-Reset"] = str(
        int(datetime.now(timezone.utc).timestamp()) + ttl
    )

    if current > daily_limit:
        response.headers["Retry-After"] = str(ttl)
        raise HTTPException(status_code=429, detail="Embed API key daily limit exceeded.")
