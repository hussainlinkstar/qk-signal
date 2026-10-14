import base64
import asyncio
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from core.env_bootstrap import bootstrap_environment
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError

bootstrap_environment()

from observability import (
    configure_logging,
    init_tracing,
    reset_request_id,
    set_request_id,
    tag_current_trace_with_request_id,
)
from core.redis_client import get_async_redis_client
from report_schema import CanonicalAuditAnalysisContract, TrackBJudgeContract
from services.audit_job_event_service import append_debate_progress_event
from services.ai_engine import AIFactory
from services.screenshot_normalization import normalize_screenshot_base64

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    configure_logging()
    tracing_backend = init_tracing("ai-service")
    logger.info("Tracing backend initialized: %s", tracing_backend)
    yield


app = FastAPI(title="Qiko Signal Service", lifespan=_app_lifespan)

ai_factory = AIFactory()


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    token = set_request_id(request_id)
    tag_current_trace_with_request_id(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        reset_request_id(token)


def _normalize_env_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _parse_int_env(var_name: str, default: int) -> int:
    raw_value = os.getenv(var_name)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        logger.warning("Invalid integer for %s=%s; using default=%s", var_name, raw_value, default)
        return default


def _resolve_limit(prefix: str, value: str, default_var: str, default: int) -> int:
    normalized = _normalize_env_key(value)
    specific_var = f"{prefix}_{normalized}"
    return _parse_int_env(specific_var, _parse_int_env(default_var, default))


def _resolve_window(prefix: str, value: str, default_var: str, default: int) -> int:
    normalized = _normalize_env_key(value)
    specific_var = f"{prefix}_{normalized}_WINDOW_SECONDS"
    return _parse_int_env(specific_var, _parse_int_env(default_var, default))


@dataclass
class _WindowCounter:
    count: int
    window_start: float


class _RateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._entries: dict[str, _WindowCounter] = {}

    async def check(self, key: str, limit: int, window_seconds: int, detail: str) -> None:
        if limit <= 0 or window_seconds <= 0:
            return
        now = time.monotonic()
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or (now - entry.window_start) >= window_seconds:
                self._entries[key] = _WindowCounter(count=1, window_start=now)
                return
            entry.count += 1
            if entry.count > limit:
                raise HTTPException(status_code=429, detail=detail)


rate_limiter = _RateLimiter()


class AIAuditRequest(BaseModel):
    provider: str = "google"
    tier: str = "fast"
    requested_tier: str | None = None
    job_id: str | None = None
    content: str
    screenshot_base64: str | None = None
    network_data: dict
    category: str | None = None
    market: str | None = None
    query_type: str | None = None
    context_payload: dict | None = None


class AIAuditResponse(BaseModel):
    analysis: CanonicalAuditAnalysisContract
    provider: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)
    debate: dict[str, Any] | None = None
    debate_trace_records: list[dict[str, Any]] = Field(default_factory=list)


class AISuggestionDetailRequest(BaseModel):
    provider: str = "google"
    tier: str = "fast"
    suggestion: str
    market: str = "global"
    language: str = "en"
    page_type: str | None = None
    page_type_label: str | None = None


class AISuggestionDetailResponse(BaseModel):
    short_title: str
    comprehensive_action: str
    # Absent/unclassifiable category is a real state (the model legitimately
    # returns null when a suggestion doesn't fit Technical/Content/Backlinks),
    # not a contract violation. Same explicit-null convention as the
    # unmeasured-engine fields (SIGV2-1215/SIGV2-1216): render honestly rather
    # than fabricate a bucket.
    category: str | None = None
    provider: str | None = None
    model: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = None


class AITrackBClaimRequest(BaseModel):
    provider: str = "google"
    tier: str = "smart"
    claim: dict[str, Any]
    judge_context: dict[str, Any] | None = None


class AITrackBClaimResponse(BaseModel):
    judgment: TrackBJudgeContract
    provider: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)


def _map_ai_error_to_http(ai_error: dict) -> tuple[int, dict]:
    error_message = ai_error.get("error", "AI provider request failed.")
    error_code = ai_error.get("error_code", "provider_request_error")
    retryable = bool(ai_error.get("retryable", False))

    status_code = ai_error.get("http_status")
    if not isinstance(status_code, int):
        if error_code == "provider_auth_error":
            status_code = 401
        elif error_code == "provider_config_error":
            status_code = 424
        elif retryable:
            status_code = 503
        else:
            status_code = 502

    detail = {
        "error": error_message,
        "error_code": error_code,
        "retryable": retryable,
    }
    return status_code, detail


from services.canonical_payload_coercion import coerce_payload_for_contract


def _validate_canonical_analysis_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "AI service returned an invalid audit payload.",
                "error_code": "invalid_ai_audit_contract",
                "retryable": False,
                "detail": "Expected 'analysis' to be a JSON object.",
            },
        )

    sanitized = {
        key: value
        for key, value in payload.items()
        if not (isinstance(key, str) and key.startswith("_"))
    }

    coerced = coerce_payload_for_contract(sanitized)

    try:
        validated = CanonicalAuditAnalysisContract.model_validate(coerced)
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "AI service returned an invalid audit payload.",
                "error_code": "invalid_ai_audit_contract",
                "retryable": False,
                "detail": str(exc),
                "validation_errors": exc.errors(),
            },
        ) from exc

    return validated.model_dump()


def _validate_track_b_judgment_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=502,
            detail={
                "error": "AI service returned an invalid Track B judge payload.",
                "error_code": "invalid_track_b_judge_contract",
                "retryable": False,
                "detail": "Expected Track B judgment to be a JSON object.",
            },
        )

    sanitized = {
        key: value
        for key, value in payload.items()
        if not (isinstance(key, str) and key.startswith("_"))
    }

    try:
        validated = TrackBJudgeContract.model_validate(sanitized)
    except ValidationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "error": "AI service returned an invalid Track B judge payload.",
                "error_code": "invalid_track_b_judge_contract",
                "retryable": False,
                "detail": str(exc),
                "validation_errors": exc.errors(),
            },
        ) from exc

    return validated.model_dump()


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}


@app.post("/ai/audit", response_model=AIAuditResponse)
async def generate_audit(request: AIAuditRequest):
    provider = request.provider.strip() if request.provider else "unknown"
    tier = request.tier.strip() if request.tier else "unknown"
    provider_limit = _resolve_limit(
        "AI_RATE_LIMIT_PROVIDER", provider, "AI_RATE_LIMIT_PROVIDER_DEFAULT", 60
    )
    tier_limit = _resolve_limit("AI_RATE_LIMIT_TIER", tier, "AI_RATE_LIMIT_TIER_DEFAULT", 120)
    provider_window = _resolve_window(
        "AI_RATE_LIMIT_PROVIDER", provider, "AI_RATE_LIMIT_PROVIDER_WINDOW_SECONDS", 60
    )
    tier_window = _resolve_window(
        "AI_RATE_LIMIT_TIER", tier, "AI_RATE_LIMIT_TIER_WINDOW_SECONDS", 60
    )
    await rate_limiter.check(
        key=f"provider:{provider.lower()}",
        limit=provider_limit,
        window_seconds=provider_window,
        detail=f"Rate limit exceeded for provider '{provider}'.",
    )
    await rate_limiter.check(
        key=f"tier:{tier.lower()}",
        limit=tier_limit,
        window_seconds=tier_window,
        detail=f"Rate limit exceeded for tier '{tier}'.",
    )

    screenshot_bytes = b""
    if request.screenshot_base64 is not None:
        try:
            normalized_screenshot = normalize_screenshot_base64(request.screenshot_base64)
            screenshot_bytes = base64.b64decode(normalized_screenshot, validate=True)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid screenshot payload")

        if not screenshot_bytes:
            raise HTTPException(status_code=400, detail="Invalid screenshot payload")

    redis_client = None
    on_event = None
    normalized_job_id = str(request.job_id or "").strip()
    if normalized_job_id:
        redis_client = get_async_redis_client()

        async def _on_event(event_payload: dict[str, Any]) -> None:
            if redis_client is None:
                return
            await append_debate_progress_event(
                redis_client,
                job_id=normalized_job_id,
                payload=event_payload,
            )

        on_event = _on_event

    try:
        ai_response = await ai_factory.generate_audit(
            provider=provider,
            tier=tier,
            requested_tier=request.requested_tier,
            content=request.content,
            screenshot_data=screenshot_bytes,
            network_data=request.network_data,
            category=request.category,
            market=request.market,
            query_type=request.query_type,
            context_payload=request.context_payload,
            on_event=on_event,
        )
    finally:
        if redis_client is not None:
            await redis_client.aclose()

    if "error" in ai_response:
        logger.error("AI provider error: %s", ai_response["error"])
        status_code, detail = _map_ai_error_to_http(ai_response)
        raise HTTPException(status_code=status_code, detail=detail)

    return {
        "analysis": _validate_canonical_analysis_payload(ai_response.get("analysis")),
        "provider": str(ai_response.get("provider") or provider),
        "model": str(ai_response.get("model") or ""),
        "usage": ai_response.get("usage") if isinstance(ai_response.get("usage"), dict) else {},
        "debate": ai_response.get("debate")
        if isinstance(ai_response.get("debate"), dict)
        else None,
        "debate_trace_records": (
            ai_response.get("debate_trace_records")
            if isinstance(ai_response.get("debate_trace_records"), list)
            else []
        ),
    }


@app.post("/ai/suggestion-detail", response_model=AISuggestionDetailResponse)
async def generate_suggestion_detail(request: AISuggestionDetailRequest):
    detail = await ai_factory.generate_suggestion_detail(
        provider=request.provider.strip() if request.provider else "google",
        tier=request.tier.strip() if request.tier else "fast",
        suggestion=request.suggestion,
        market=request.market,
        language=request.language,
        page_type=request.page_type,
        page_type_label=request.page_type_label,
    )
    return detail


@app.post("/ai/track-b-claim", response_model=AITrackBClaimResponse)
async def evaluate_track_b_claim(request: AITrackBClaimRequest):
    provider = request.provider.strip() if request.provider else "unknown"
    tier = request.tier.strip() if request.tier else "unknown"
    provider_limit = _resolve_limit(
        "AI_RATE_LIMIT_PROVIDER", provider, "AI_RATE_LIMIT_PROVIDER_DEFAULT", 60
    )
    tier_limit = _resolve_limit("AI_RATE_LIMIT_TIER", tier, "AI_RATE_LIMIT_TIER_DEFAULT", 120)
    provider_window = _resolve_window(
        "AI_RATE_LIMIT_PROVIDER", provider, "AI_RATE_LIMIT_PROVIDER_WINDOW_SECONDS", 60
    )
    tier_window = _resolve_window(
        "AI_RATE_LIMIT_TIER", tier, "AI_RATE_LIMIT_TIER_WINDOW_SECONDS", 60
    )
    await rate_limiter.check(
        key=f"provider:{provider.lower()}",
        limit=provider_limit,
        window_seconds=provider_window,
        detail=f"Rate limit exceeded for provider '{provider}'.",
    )
    await rate_limiter.check(
        key=f"tier:{tier.lower()}",
        limit=tier_limit,
        window_seconds=tier_window,
        detail=f"Rate limit exceeded for tier '{tier}'.",
    )

    ai_response = await ai_factory.evaluate_track_b_claim(
        provider=provider,
        tier=tier,
        claim=dict(request.claim or {}),
        judge_context=dict(request.judge_context or {}),
    )

    if "error" in ai_response:
        logger.error("AI Track B judge error: %s", ai_response["error"])
        status_code, detail = _map_ai_error_to_http(ai_response)
        raise HTTPException(status_code=status_code, detail=detail)

    return {
        "judgment": _validate_track_b_judgment_payload(ai_response.get("judgment")),
        "provider": str(ai_response.get("provider") or provider),
        "model": str(ai_response.get("model") or ""),
        "usage": ai_response.get("usage") if isinstance(ai_response.get("usage"), dict) else {},
    }


class SiteClassifyRequest(BaseModel):
    content: str
    provider: str = "google"
    tier: str = "fast"


class SiteClassifyResponse(BaseModel):
    category: str
    confidence: float


@app.post("/ai/classify-site", response_model=SiteClassifyResponse)
async def classify_site(request: SiteClassifyRequest):
    result = await ai_factory.classify_site_category(
        provider=request.provider.strip() if request.provider else "google",
        tier=request.tier.strip() if request.tier else "fast",
        content=request.content,
    )
    return SiteClassifyResponse(
        category=result.get("category", "General"),
        confidence=result.get("confidence", 0.5),
    )
