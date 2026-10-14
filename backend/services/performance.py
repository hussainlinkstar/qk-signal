import os
from pathlib import Path
import time
import httpx
from dotenv import load_dotenv
import logging

from app.services.seo.performance_service import normalize_core_web_vitals
from .resilience import CircuitBreaker, ServiceUnavailableError, retry_with_backoff
from .observability import (
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_SERVICE_UNAVAILABLE,
    ERROR_CODE_TIMEOUT,
    classify_error_code,
    duration_ms,
    http_target_for_log,
    is_retryable,
    log_external_service_event,
    redact_secrets,
)

load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")

logger = logging.getLogger(__name__)


def _should_retry_httpx_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code < 600
    return False


class PerformanceService:
    def __init__(self):
        self.api_key = os.getenv("PAGESPEED_API_KEY")
        if not self.api_key:
            logger.warning("PAGESPEED_API_KEY not found. Performance metrics will be skipped.")
        self.include_seo_default = self._parse_bool_env(os.getenv("PAGESPEED_INCLUDE_SEO"))
        self.api_endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
        self.breaker = CircuitBreaker()
        self.retry_config = {
            "retries": self._get_int_env("PAGESPEED_RETRY_COUNT", 3),
            "base_delay": self._get_float_env("PAGESPEED_RETRY_BASE_DELAY", 0.5),
            "max_delay": self._get_float_env("PAGESPEED_RETRY_MAX_DELAY", 4.0),
        }

    @staticmethod
    def _parse_bool_env(value: str | None) -> bool | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        logger.warning(
            "Invalid PAGESPEED_INCLUDE_SEO value '%s'. Expected true/false. Falling back to request value.",
            value,
        )
        return None

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning("Invalid %s value '%s'. Falling back to %s.", name, value, default)
            return default

    @staticmethod
    def _get_float_env(name: str, default: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            logger.warning("Invalid %s value '%s'. Falling back to %s.", name, value, default)
            return default

    def _resolve_include_seo(self, include_seo: bool) -> bool:
        return include_seo if self.include_seo_default is None else self.include_seo_default

    def _get_default_metrics(self, error_message: str):
        """Returns a default structure for metrics on failure."""
        return {
            "status": "error",
            "message": error_message,
            "performance_score": 0,
            "first_contentful_paint": "N/A",
            "largest_contentful_paint": "N/A",
            "speed_index": "N/A",
            "total_blocking_time": "N/A",
            "interaction_to_next_paint": "N/A",
            "cumulative_layout_shift": "N/A",
        }

    @staticmethod
    def _extract_vitals(audits: dict) -> dict:
        return {
            "first_contentful_paint": audits.get("first-contentful-paint", {}).get(
                "displayValue", "N/A"
            ),
            "largest_contentful_paint": audits.get("largest-contentful-paint", {}).get(
                "displayValue", "N/A"
            ),
            "speed_index": audits.get("speed-index", {}).get("displayValue", "N/A"),
            "total_blocking_time": audits.get("total-blocking-time", {}).get("displayValue", "N/A"),
            "interaction_to_next_paint": audits.get("interaction-to-next-paint", {}).get(
                "displayValue", "N/A"
            ),
            "cumulative_layout_shift": audits.get("cumulative-layout-shift", {}).get(
                "displayValue", "N/A"
            ),
        }

    async def get_performance_metrics(
        self,
        url: str,
        strategy: str = "DESKTOP",
        include_seo: bool = False,
    ):
        """
        Analyzes a URL using Google PageSpeed Insights asynchronously.
        Returns default values on failure to avoid blocking the main audit process.
        """
        if not self.api_key:
            return self._get_default_metrics("API key for PageSpeed Insights is not configured.")

        effective_include_seo = self._resolve_include_seo(include_seo)

        def build_params(include_seo_categories: bool):
            params = [
                ("url", url),
                ("key", self.api_key),
                ("strategy", strategy),
                ("category", "PERFORMANCE"),
            ]
            if include_seo_categories:
                params.append(("category", "SEO"))
            return params

        async with httpx.AsyncClient() as client:
            start_time = time.monotonic()
            try:

                async def _fetch(params):
                    response = await client.get(self.api_endpoint, params=params, timeout=30.0)
                    response.raise_for_status()
                    return response.json()

                params = build_params(effective_include_seo)
                result = await retry_with_backoff(
                    lambda: _fetch(params),
                    breaker=self.breaker,
                    service_name="PageSpeed",
                    retries=self.retry_config["retries"],
                    base_delay=self.retry_config["base_delay"],
                    max_delay=self.retry_config["max_delay"],
                    should_retry=_should_retry_httpx_error,
                    on_retry=lambda exc, attempt, delay: log_external_service_event(
                        logger,
                        service="pagespeed",
                        operation="run_pagespeed",
                        status="retrying",
                        duration_ms_value=duration_ms(start_time),
                        error_code=classify_error_code(message=str(exc)),
                        retryable=True,
                        attempt=attempt,
                        delay_s=delay,
                        detail=str(exc),
                    ),
                )

                lighthouse_result = result.get("lighthouseResult", {})
                performance_score = (
                    lighthouse_result.get("categories", {}).get("performance", {}).get("score", 0)
                    * 100
                )
                audits = lighthouse_result.get("audits", {})
                vitals = self._extract_vitals(audits)

                seo_audits: list[dict] = []
                structured_data_detected = None
                seo_status = "disabled" if not effective_include_seo else "available"
                seo_error = None
                if effective_include_seo:
                    seo_category = lighthouse_result.get("categories", {}).get("seo", {})
                    audit_refs = seo_category.get("auditRefs", [])
                    if not seo_category or not audit_refs:
                        seo_status = "missing"
                        seo_error = "SEO data was not included in the PageSpeed response."
                    for ref in audit_refs:
                        audit_id = ref.get("id")
                        if not audit_id:
                            continue
                        audit = audits.get(audit_id, {})
                        score = audit.get("score")
                        if score is None:
                            continue
                        if score < 1:
                            seo_audits.append(
                                {
                                    "id": audit_id,
                                    "title": audit.get("title", "SEO improvement"),
                                    "description": audit.get("description", ""),
                                    "score": score,
                                }
                            )
                        if audit_id == "structured-data":
                            structured_data_detected = score == 1

                if effective_include_seo and structured_data_detected is None:
                    structured_data_detected = False

                normalized_cwv = normalize_core_web_vitals(result)
                lcp_ms = normalized_cwv.get("lcp", {}).get("value")
                cls = normalized_cwv.get("cls", {}).get("value")

                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="success",
                    duration_ms_value=duration_ms(start_time),
                )
                return {
                    "status": "success",
                    "performance_score": round(performance_score),
                    **vitals,
                    "lcp_ms": lcp_ms,
                    "cls": cls,
                    "seo_audits": seo_audits,
                    "structured_data_detected": structured_data_detected,
                    "seo_status": seo_status,
                    "seo_error": seo_error,
                }

            except httpx.TimeoutException as e:
                if effective_include_seo:
                    logger.warning(
                        "PageSpeed SEO request timed out for %s; retrying performance-only metrics.",
                        url,
                    )
                    try:
                        params = build_params(False)
                        result = await retry_with_backoff(
                            lambda: _fetch(params),
                            breaker=self.breaker,
                            service_name="PageSpeed",
                            retries=self.retry_config["retries"],
                            base_delay=self.retry_config["base_delay"],
                            max_delay=self.retry_config["max_delay"],
                            should_retry=_should_retry_httpx_error,
                            on_retry=lambda exc, attempt, delay: log_external_service_event(
                                logger,
                                service="pagespeed",
                                operation="run_pagespeed_fallback",
                                status="retrying",
                                duration_ms_value=duration_ms(start_time),
                                error_code=classify_error_code(message=str(exc)),
                                retryable=True,
                                attempt=attempt,
                                delay_s=delay,
                                detail=str(exc),
                            ),
                        )
                        lighthouse_result = result.get("lighthouseResult", {})
                        performance_score = (
                            lighthouse_result.get("categories", {})
                            .get("performance", {})
                            .get("score", 0)
                            * 100
                        )
                        audits = lighthouse_result.get("audits", {})
                        vitals = self._extract_vitals(audits)

                        normalized_cwv = normalize_core_web_vitals(result)
                        lcp_ms = normalized_cwv.get("lcp", {}).get("value")
                        cls = normalized_cwv.get("cls", {}).get("value")

                        return {
                            "status": "success",
                            "performance_score": round(performance_score),
                            **vitals,
                            "lcp_ms": lcp_ms,
                            "cls": cls,
                            "seo_audits": [],
                            "structured_data_detected": None,
                            "seo_status": "timeout",
                            "seo_error": "SEO data timed out; returning performance-only metrics.",
                        }
                    except Exception as fallback_error:
                        logger.error(
                            "Performance-only fallback failed for %s after SEO timeout: %s",
                            url,
                            redact_secrets(fallback_error),
                        )
                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="error",
                    duration_ms_value=duration_ms(start_time),
                    error_code=ERROR_CODE_TIMEOUT,
                    retryable=True,
                    detail=str(e),
                )
                safe_error = redact_secrets(e)
                logger.error(
                    "PageSpeed API request timed out for %s (endpoint=%s): %s",
                    url,
                    http_target_for_log(self.api_endpoint),
                    safe_error,
                )
                return self._get_default_metrics(
                    f"PageSpeed Insights request timed out: {safe_error}"
                )
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                response_text = redact_secrets(e.response.text)
                if status_code == 403:
                    message = (
                        "Invalid or restricted PAGESPEED_API_KEY. Check your API key permissions "
                        "and billing status."
                    )
                else:
                    message = (
                        f"PageSpeed Insights API returned status {status_code}: {response_text}"
                    )
                error_code = classify_error_code(message=message, status_code=status_code)
                if status_code == 429:
                    error_code = ERROR_CODE_RATE_LIMITED
                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="error",
                    duration_ms_value=duration_ms(start_time),
                    error_code=error_code,
                    retryable=is_retryable(error_code),
                    http_status=status_code,
                    detail=message,
                )
                logger.error(
                    "PageSpeed API error for %s (endpoint=%s status=%s): %s",
                    url,
                    http_target_for_log(self.api_endpoint),
                    status_code,
                    message,
                )
                return self._get_default_metrics(message)
            except ServiceUnavailableError as e:
                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="error",
                    duration_ms_value=duration_ms(start_time),
                    error_code=ERROR_CODE_SERVICE_UNAVAILABLE,
                    retryable=True,
                    detail=str(e),
                )
                logger.error(f"PageSpeed API temporarily unavailable for {url}: {e}")
                return self._get_default_metrics(str(e))
            except httpx.RequestError as e:
                error_code = (
                    ERROR_CODE_TIMEOUT
                    if isinstance(e, httpx.TimeoutException)
                    else classify_error_code(message=str(e))
                )
                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="error",
                    duration_ms_value=duration_ms(start_time),
                    error_code=error_code,
                    retryable=is_retryable(error_code),
                    detail=str(e),
                )
                safe_error = redact_secrets(e)
                logger.error(
                    "PageSpeed API request failed for %s (endpoint=%s): %s",
                    url,
                    http_target_for_log(self.api_endpoint),
                    safe_error,
                )
                return self._get_default_metrics(
                    f"Failed to connect to PageSpeed Insights API: {safe_error}"
                )
            except Exception as e:
                log_external_service_event(
                    logger,
                    service="pagespeed",
                    operation="run_pagespeed",
                    status="error",
                    duration_ms_value=duration_ms(start_time),
                    error_code=classify_error_code(message=str(e), default="unknown_error"),
                    retryable=False,
                    detail=str(e),
                )
                safe_error = redact_secrets(e)
                logger.error(
                    "An unexpected error occurred during PageSpeed analysis for %s: %s",
                    url,
                    safe_error,
                )
                return self._get_default_metrics(f"An unexpected error occurred: {safe_error}")
