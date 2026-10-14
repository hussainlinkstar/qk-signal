from __future__ import annotations

import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

ERROR_CODE_TIMEOUT = "timeout"
ERROR_CODE_RATE_LIMITED = "rate_limited"
ERROR_CODE_QUOTA_EXHAUSTED = "quota_exhausted"
ERROR_CODE_RETRYABLE = "retryable_error"
ERROR_CODE_SERVICE_UNAVAILABLE = "service_unavailable"
ERROR_CODE_HTTP_ERROR = "http_error"
ERROR_CODE_REQUEST_ERROR = "request_error"
ERROR_CODE_UNKNOWN = "unknown_error"

RETRYABLE_ERROR_CODES = {
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_RETRYABLE,
    ERROR_CODE_SERVICE_UNAVAILABLE,
    ERROR_CODE_REQUEST_ERROR,
}


REDACTED_VALUE = "[REDACTED]"

# Query-string parameter names whose value is a credential. Upstream providers such as
# SerpAPI (``api_key``) and PageSpeed Insights (``key``) accept the secret as a query
# parameter, so the secret ends up inside ``httpx`` exception messages, which render the
# full request URL via ``str(exc)``.
_SENSITIVE_QUERY_PARAM_PATTERN = (
    r"api[-_]?key|access[-_]?token|refresh[-_]?token|id[-_]?token|auth[-_]?token"
    r"|client[-_]?secret|webhook[-_]?secret|private[-_]?key|secret[-_]?key"
    r"|apikey|key|token|secret|password|passwd|pwd|signature|sig|jwt|bearer|auth"
)
_SENSITIVE_QUERY_PARAM_RE = re.compile(
    rf"(?i)([?&](?:{_SENSITIVE_QUERY_PARAM_PATTERN})=)([^&\s\"'<>\\]*)"
)


def redact_secrets(value: Any) -> str:
    """Strip credential-bearing query parameter values out of arbitrary text.

    Use this on anything derived from an outbound request before it reaches a logger,
    a persisted payload or an API response: request URLs, query strings and exception
    messages (``httpx.HTTPStatusError.__str__`` embeds the full request URL).
    """
    text = "" if value is None else str(value)
    if not text:
        return text
    return _SENSITIVE_QUERY_PARAM_RE.sub(rf"\g<1>{REDACTED_VALUE}", text)


def http_target_for_log(url: Any) -> str:
    """Describe a request URL as ``host/path`` only, dropping the query string entirely.

    This is the preferred way to identify an upstream call in a log line, because it can
    never carry a credential even if a provider invents a new secret query parameter.
    """
    text = "" if url is None else str(url).strip()
    if not text:
        return "unknown-target"
    try:
        parts = urlsplit(text)
    except ValueError:
        return "unknown-target"
    host = (parts.hostname or "").strip()
    if not host:
        return "unknown-target"
    return f"{host}{parts.path or '/'}"


def describe_http_failure(url: Any, exc: BaseException) -> str:
    """Build a log-safe description of a failed outbound request.

    Keeps the diagnostically useful parts (exception type, upstream host and path, HTTP
    status code) and drops the credentialed query string that ``str(exc)`` would expose.
    """
    target = http_target_for_log(url)
    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code is not None:
        return f"{type(exc).__name__} for {target}: HTTP {status_code}"
    return f"{type(exc).__name__} for {target}: {redact_secrets(exc)}"


def duration_ms(start_time: float) -> int:
    return int((time.monotonic() - start_time) * 1000)


def classify_error_code(
    *,
    error_code: str | None = None,
    message: str | None = None,
    status_code: int | None = None,
    default: str = ERROR_CODE_RETRYABLE,
) -> str:
    normalized_error_code = (error_code or "").strip().lower()
    if normalized_error_code:
        if normalized_error_code in {
            ERROR_CODE_TIMEOUT,
            ERROR_CODE_RATE_LIMITED,
            ERROR_CODE_QUOTA_EXHAUSTED,
            ERROR_CODE_RETRYABLE,
            ERROR_CODE_SERVICE_UNAVAILABLE,
            ERROR_CODE_HTTP_ERROR,
            ERROR_CODE_REQUEST_ERROR,
            ERROR_CODE_UNKNOWN,
        }:
            return normalized_error_code
        if "quota" in normalized_error_code:
            return ERROR_CODE_QUOTA_EXHAUSTED
        if "rate" in normalized_error_code or "throttle" in normalized_error_code:
            return ERROR_CODE_RATE_LIMITED
        if "timeout" in normalized_error_code:
            return ERROR_CODE_TIMEOUT
        if "unavailable" in normalized_error_code:
            return ERROR_CODE_SERVICE_UNAVAILABLE

    text = (message or "").lower()
    quota_markers = (
        "insufficient_quota",
        "exceeded your current quota",
        "billing hard limit",
        "hard limit",
        "quota exceeded",
        "insufficient credits",
        "payment required",
    )

    if any(marker in text for marker in quota_markers):
        return ERROR_CODE_QUOTA_EXHAUSTED

    if status_code == 429 or "rate limit" in text or "rate limited" in text:
        return ERROR_CODE_RATE_LIMITED
    if "timeout" in text:
        return ERROR_CODE_TIMEOUT
    if status_code is not None:
        if status_code >= 500:
            return ERROR_CODE_RETRYABLE
        return ERROR_CODE_HTTP_ERROR
    return default


def is_retryable(error_code: str) -> bool:
    return error_code in RETRYABLE_ERROR_CODES


def log_external_service_event(
    logger: logging.Logger,
    *,
    service: str,
    operation: str,
    status: str,
    duration_ms_value: int,
    error_code: str | None = None,
    retryable: bool | None = None,
    http_status: int | None = None,
    attempt: int | None = None,
    delay_s: float | None = None,
    detail: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "service": service,
        "operation": operation,
        "status": status,
        "duration_ms": duration_ms_value,
    }
    if error_code:
        payload["error_code"] = error_code
    if retryable is not None:
        payload["retryable"] = retryable
    if http_status is not None:
        payload["http_status"] = http_status
    if attempt is not None:
        payload["attempt"] = attempt
    if delay_s is not None:
        payload["delay_s"] = delay_s
    if detail:
        # Defense in depth: callers routinely pass ``str(exc)`` here and httpx renders the
        # full request URL (secret query parameters included) in its exception messages.
        payload["detail"] = redact_secrets(detail)
    if extra_fields:
        payload.update(extra_fields)

    level = logging.INFO
    if status in {"error", "timeout", "rate_limited"}:
        level = logging.WARNING if retryable else logging.ERROR
    elif status == "retrying":
        level = logging.WARNING

    logger.log(level, "external_service_event: %s", payload)
