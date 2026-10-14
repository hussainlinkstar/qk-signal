import logging
import os
import time
from typing import Any

import httpx

from .resilience import CircuitBreaker, ServiceUnavailableError, retry_with_backoff
from .screenshot_normalization import normalize_screenshot_base64

from .observability import (
    ERROR_CODE_HTTP_ERROR,
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_REQUEST_ERROR,
    ERROR_CODE_TIMEOUT,
    classify_error_code,
    duration_ms,
    is_retryable,
    log_external_service_event,
)

logger = logging.getLogger(__name__)


class AIServiceResponseError(RuntimeError):
    def __init__(
        self,
        *,
        status_code: int,
        detail: str,
        retryable: bool | None = None,
        error_code: str | None = None,
        error_type: str | None = None,
        error_subtype: str | None = None,
        request_id: str | None = None,
        payload_type: str | None = None,
        source: str | None = None,
        raw_type: str | None = None,
    ):
        super().__init__(detail)
        self.status_code = status_code
        self.retryable = retryable
        self.error_code = error_code
        self.error_type = error_type
        self.error_subtype = error_subtype
        self.request_id = request_id
        self.payload_type = payload_type
        self.source = source
        self.raw_type = raw_type


def _extract_error_payload(
    response: httpx.Response,
) -> tuple[
    bool | None,
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
]:
    detail_text = response.text
    retryable = None
    error_code = None
    error_type = None
    error_subtype = None
    request_id = None
    payload_type = None
    source = None
    raw_type = None
    try:
        payload = response.json()
    except ValueError:
        return (
            retryable,
            detail_text,
            error_code,
            error_type,
            error_subtype,
            request_id,
            payload_type,
            source,
            raw_type,
        )

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        detail_text = detail.get("error") or detail_text
        if isinstance(detail.get("detail"), str) and detail.get("detail").strip():
            detail_text = detail["detail"].strip()
        if isinstance(detail.get("retryable"), bool):
            retryable = detail["retryable"]
        if isinstance(detail.get("error_code"), str):
            error_code = detail["error_code"]
        if isinstance(detail.get("type"), str):
            error_type = detail["type"]
        if isinstance(detail.get("error_subtype"), str):
            error_subtype = detail["error_subtype"]
        if isinstance(detail.get("request_id"), str):
            request_id = detail["request_id"]
        if isinstance(detail.get("payload_type"), str):
            payload_type = detail["payload_type"]
        if isinstance(detail.get("source"), str):
            source = detail["source"]
        if isinstance(detail.get("raw_type"), str):
            raw_type = detail["raw_type"]

    if isinstance(payload, dict):
        if isinstance(payload.get("error_code"), str) and not error_code:
            error_code = payload["error_code"]
        if isinstance(payload.get("type"), str) and not error_type:
            error_type = payload["type"]
        if isinstance(payload.get("error_subtype"), str) and not error_subtype:
            error_subtype = payload["error_subtype"]
        if isinstance(payload.get("request_id"), str) and not request_id:
            request_id = payload["request_id"]
        if isinstance(payload.get("payload_type"), str) and not payload_type:
            payload_type = payload["payload_type"]
        if isinstance(payload.get("source"), str) and not source:
            source = payload["source"]
        if isinstance(payload.get("raw_type"), str) and not raw_type:
            raw_type = payload["raw_type"]

    return (
        retryable,
        detail_text,
        error_code,
        error_type,
        error_subtype,
        request_id,
        payload_type,
        source,
        raw_type,
    )


def _should_retry_httpx_error(exc: Exception) -> bool:
    if isinstance(exc, AIServiceResponseError):
        if isinstance(exc.retryable, bool):
            return exc.retryable
        return exc.status_code == 429 or 500 <= exc.status_code < 600
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code < 600
    return False


def _classify_exception_error_code(exc: Exception) -> str:
    if isinstance(exc, AIServiceResponseError):
        return classify_error_code(
            error_code=exc.error_code,
            message=str(exc),
            status_code=exc.status_code,
        )
    return classify_error_code(message=str(exc))


class AIClient:
    TIER_TIMEOUTS: dict[str, float] = {
        "fast": 120.0,
        "lite": 120.0,
        "smart": 300.0,
        "deep_judgment": 660.0,
    }
    TIER_RETRIES: dict[str, int] = {
        "fast": 3,
        "lite": 3,
        "smart": 1,
        "deep_judgment": 0,
    }

    def __init__(self, base_url: str | None = None, timeout_seconds: float = 120.0):
        self.base_url = (base_url or os.getenv("AI_SERVICE_URL", "http://ai-service:8001")).rstrip(
            "/"
        )
        self.timeout = timeout_seconds
        self.breaker = CircuitBreaker()
        self.retry_config = {
            "retries": self._get_int_env("AI_RETRY_COUNT", 3),
            "base_delay": self._get_float_env("AI_RETRY_BASE_DELAY", 0.5),
            "max_delay": self._get_float_env("AI_RETRY_MAX_DELAY", 4.0),
        }
        max_connections = self._get_int_env("AI_HTTP_MAX_CONNECTIONS", 20)
        max_keepalive_connections = self._get_int_env("AI_HTTP_MAX_KEEPALIVE", 10)
        self.http_limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        # Persistent client, reuses TCP connections across calls
        self._client = httpx.AsyncClient(
            timeout=self.timeout,
            limits=self.http_limits,
        )

    async def aclose(self) -> None:
        """Gracefully close the underlying HTTP connection pool."""
        await self._client.aclose()

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return default

    @staticmethod
    def _get_float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            return default

    async def generate_audit(
        self,
        *,
        provider: str,
        tier: str,
        content: str,
        screenshot_base64: str | None,
        network_data: dict,
        category: str | None = None,
        market: str | None = None,
        query_type: str | None = None,
        context_payload: dict | None = None,
        requested_tier: str | None = None,
        job_id: str | None = None,
    ) -> dict:
        start_time = time.monotonic()
        normalized_screenshot_base64 = None

        if screenshot_base64 is not None:
            try:
                normalized_screenshot_base64 = normalize_screenshot_base64(screenshot_base64)
            except ValueError as exc:
                return {
                    "error": {
                        "type": "validation_error",
                        "error_code": "invalid_screenshot_payload",
                        "error_subtype": "screenshot_payload_shape",
                        "http_status": 400,
                        "retryable": False,
                        "raw_type": type(screenshot_base64).__name__,
                        "payload_type": type(screenshot_base64).__name__,
                        "source": "firecrawl",
                        "detail": str(exc),
                    }
                }

        payload = {
            "provider": provider,
            "tier": tier,
            "content": content,
            "screenshot_base64": normalized_screenshot_base64,
            "network_data": network_data,
            "category": category,
            "market": market,
            "query_type": query_type,
            "context_payload": context_payload,
        }
        if isinstance(requested_tier, str) and requested_tier.strip():
            payload["requested_tier"] = requested_tier.strip().lower()
        if isinstance(job_id, str) and job_id.strip():
            payload["job_id"] = job_id.strip()
        effective_timeout = self.TIER_TIMEOUTS.get(tier, self.timeout)
        effective_retries = self.TIER_RETRIES.get(tier, self.retry_config["retries"])
        client = self._client
        try:

            async def _call_ai_service():
                response = await client.post(
                    f"{self.base_url}/ai/audit", json=payload, timeout=effective_timeout
                )
                if response.is_error:
                    (
                        retryable,
                        detail,
                        error_code,
                        error_type,
                        error_subtype,
                        request_id,
                        payload_type,
                        source,
                        raw_type,
                    ) = _extract_error_payload(response)
                    raise AIServiceResponseError(
                        status_code=response.status_code,
                        detail=detail,
                        retryable=retryable,
                        error_code=error_code,
                        error_type=error_type,
                        error_subtype=error_subtype,
                        request_id=request_id,
                        payload_type=payload_type,
                        source=source,
                        raw_type=raw_type,
                    )
                return response

            response = await retry_with_backoff(
                _call_ai_service,
                breaker=self.breaker,
                service_name="AI",
                retries=effective_retries,
                base_delay=self.retry_config["base_delay"],
                max_delay=self.retry_config["max_delay"],
                should_retry=_should_retry_httpx_error,
                on_retry=lambda exc, attempt, delay: log_external_service_event(
                    logger,
                    service="ai_service",
                    operation="generate_audit",
                    status="retrying",
                    duration_ms_value=duration_ms(start_time),
                    error_code=_classify_exception_error_code(exc),
                    retryable=True,
                    attempt=attempt,
                    delay_s=delay,
                    detail=str(exc),
                ),
            )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_audit",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
        except httpx.RequestError as exc:
            error_code = (
                ERROR_CODE_TIMEOUT
                if isinstance(exc, httpx.TimeoutException)
                else ERROR_CODE_REQUEST_ERROR
            )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_audit",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(exc),
            )
            logger.error("AI service connection error: %s", exc)
            return {"error": f"AI service connection failed: {exc}"}
        except AIServiceResponseError as exc:
            error_code = classify_error_code(
                error_code=exc.error_code,
                message=str(exc),
                status_code=exc.status_code,
            )
            if exc.status_code == 429:
                error_code = ERROR_CODE_RATE_LIMITED
            retryable = (
                exc.retryable if isinstance(exc.retryable, bool) else is_retryable(error_code)
            )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_audit",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=retryable,
                http_status=exc.status_code,
                detail=str(exc),
            )
            logger.error("AI service error: %s", exc)
            return {
                "error": {
                    "type": exc.error_type or "ai_service_response_error",
                    "error_code": exc.error_code or error_code,
                    "error_subtype": exc.error_subtype,
                    "http_status": exc.status_code,
                    "retryable": retryable,
                    "request_id": exc.request_id,
                    "payload_type": exc.payload_type,
                    "source": exc.source,
                    "raw_type": exc.raw_type,
                    "detail": str(exc),
                }
            }
        except ServiceUnavailableError as exc:
            error_code = _classify_exception_error_code(exc)
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_audit",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(exc),
            )
            logger.error("AI service temporarily unavailable: %s", exc)
            return {"error": f"AI service temporarily unavailable: {exc}"}
        except httpx.HTTPError as exc:
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_audit",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=ERROR_CODE_HTTP_ERROR,
                retryable=False,
                detail=str(exc),
            )
            logger.error("AI service error: %s", exc)
            return {"error": f"AI service request failed: {exc}"}

        return response.json()

    async def generate_suggestion_detail(
        self,
        *,
        provider: str,
        tier: str,
        suggestion: str,
        market: str,
        language: str,
        page_type: str | None = None,
        page_type_label: str | None = None,
    ) -> dict:
        start_time = time.monotonic()
        payload = {
            "provider": provider,
            "tier": tier,
            "suggestion": suggestion,
            "market": market,
            "language": language,
            "page_type": page_type,
            "page_type_label": page_type_label,
        }
        client = self._client
        try:

            async def _call_ai_service():
                response = await client.post(f"{self.base_url}/ai/suggestion-detail", json=payload)
                if response.is_error:
                    (
                        retryable,
                        detail,
                        error_code,
                        error_type,
                        error_subtype,
                        request_id,
                        payload_type,
                        source,
                        raw_type,
                    ) = _extract_error_payload(response)
                    raise AIServiceResponseError(
                        status_code=response.status_code,
                        detail=detail,
                        retryable=retryable,
                        error_code=error_code,
                        error_type=error_type,
                        error_subtype=error_subtype,
                        request_id=request_id,
                        payload_type=payload_type,
                        source=source,
                        raw_type=raw_type,
                    )
                return response

            response = await retry_with_backoff(
                _call_ai_service,
                breaker=self.breaker,
                service_name="AI",
                retries=self.retry_config["retries"],
                base_delay=self.retry_config["base_delay"],
                max_delay=self.retry_config["max_delay"],
                should_retry=_should_retry_httpx_error,
                on_retry=lambda exc, attempt, delay: log_external_service_event(
                    logger,
                    service="ai_service",
                    operation="generate_suggestion_detail",
                    status="retrying",
                    duration_ms_value=duration_ms(start_time),
                    error_code=_classify_exception_error_code(exc),
                    retryable=True,
                    attempt=attempt,
                    delay_s=delay,
                    detail=str(exc),
                ),
            )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_suggestion_detail",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
            return response.json()
        except Exception as exc:
            error_code = _classify_exception_error_code(exc)
            log_external_service_event(
                logger,
                service="ai_service",
                operation="generate_suggestion_detail",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(exc),
            )
            logger.warning("Suggestion detail enrichment failed: %s", exc)
            return {}

    async def evaluate_track_b_claim(
        self,
        *,
        provider: str,
        tier: str,
        claim: dict[str, Any],
        judge_context: dict[str, Any] | None,
    ) -> dict:
        start_time = time.monotonic()
        payload = {
            "provider": provider,
            "tier": tier,
            "claim": claim,
            "judge_context": judge_context or {},
        }
        client = self._client
        try:

            async def _call_ai_service():
                response = await client.post(f"{self.base_url}/ai/track-b-claim", json=payload)
                if response.is_error:
                    (
                        retryable,
                        detail,
                        error_code,
                        error_type,
                        error_subtype,
                        request_id,
                        payload_type,
                        source,
                        raw_type,
                    ) = _extract_error_payload(response)
                    raise AIServiceResponseError(
                        status_code=response.status_code,
                        detail=detail,
                        retryable=retryable,
                        error_code=error_code,
                        error_type=error_type,
                        error_subtype=error_subtype,
                        request_id=request_id,
                        payload_type=payload_type,
                        source=source,
                        raw_type=raw_type,
                    )
                return response

            response = await retry_with_backoff(
                _call_ai_service,
                breaker=self.breaker,
                service_name="AI",
                retries=self.retry_config["retries"],
                base_delay=self.retry_config["base_delay"],
                max_delay=self.retry_config["max_delay"],
                should_retry=_should_retry_httpx_error,
                on_retry=lambda exc, attempt, delay: log_external_service_event(
                    logger,
                    service="ai_service",
                    operation="evaluate_track_b_claim",
                    status="retrying",
                    duration_ms_value=duration_ms(start_time),
                    error_code=_classify_exception_error_code(exc),
                    retryable=True,
                    attempt=attempt,
                    delay_s=delay,
                    detail=str(exc),
                ),
            )
            result = response.json()
            if not isinstance(result, dict) or not isinstance(result.get("judgment"), dict):
                raise AIServiceResponseError(
                    status_code=502,
                    detail="AI service returned an invalid Track B judge payload.",
                    retryable=False,
                    error_code="invalid_track_b_judge_contract",
                )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="evaluate_track_b_claim",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
            return result
        except Exception as exc:
            error_code = _classify_exception_error_code(exc)
            log_external_service_event(
                logger,
                service="ai_service",
                operation="evaluate_track_b_claim",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(exc),
            )
            logger.warning("Track B judge evaluation failed: %s", exc)
            raise

    async def classify_site_category(
        self,
        *,
        content: str,
        provider: str = "google",
        tier: str = "fast",
    ) -> dict:
        """Classify a website into an industry category via the AI microservice."""
        start_time = time.monotonic()
        payload = {"content": content, "provider": provider, "tier": tier}
        client = self._client
        try:

            async def _call_ai_service():
                response = await client.post(f"{self.base_url}/ai/classify-site", json=payload)
                if response.is_error:
                    (
                        retryable,
                        detail,
                        error_code,
                        error_type,
                        error_subtype,
                        request_id,
                        payload_type,
                        source,
                        raw_type,
                    ) = _extract_error_payload(response)
                    raise AIServiceResponseError(
                        status_code=response.status_code,
                        detail=detail,
                        retryable=retryable,
                        error_code=error_code,
                        error_type=error_type,
                        error_subtype=error_subtype,
                        request_id=request_id,
                        payload_type=payload_type,
                        source=source,
                        raw_type=raw_type,
                    )
                return response

            response = await retry_with_backoff(
                _call_ai_service,
                breaker=self.breaker,
                service_name="AI",
                retries=self.retry_config["retries"],
                base_delay=self.retry_config["base_delay"],
                max_delay=self.retry_config["max_delay"],
                should_retry=_should_retry_httpx_error,
                on_retry=lambda exc, attempt, delay: log_external_service_event(
                    logger,
                    service="ai_service",
                    operation="classify_site_category",
                    status="retrying",
                    duration_ms_value=duration_ms(start_time),
                    error_code=_classify_exception_error_code(exc),
                    retryable=True,
                    attempt=attempt,
                    delay_s=delay,
                    detail=str(exc),
                ),
            )
            log_external_service_event(
                logger,
                service="ai_service",
                operation="classify_site_category",
                status="success",
                duration_ms_value=duration_ms(start_time),
            )
            return response.json()
        except Exception as exc:
            error_code = _classify_exception_error_code(exc)
            log_external_service_event(
                logger,
                service="ai_service",
                operation="classify_site_category",
                status="error",
                duration_ms_value=duration_ms(start_time),
                error_code=error_code,
                retryable=is_retryable(error_code),
                detail=str(exc),
            )
            logger.warning("Site category classification failed: %s", exc)
            return {"category": "General", "confidence": 0.0}
