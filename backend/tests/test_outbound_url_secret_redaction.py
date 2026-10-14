"""Regression tests for the SerpAPI key leak observed in production logs.

Every failed GEO visibility query used to log ``str(exc)`` of an ``httpx`` error, and
``httpx`` renders the full request URL in its exception messages. SerpAPI takes its
credential as the ``api_key`` query parameter, so the live key was written to the
container logs in plaintext on every failure.
"""

import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.geo_visibility_service import GeoVisibilityService
from services.observability import (
    REDACTED_VALUE,
    describe_http_failure,
    http_target_for_log,
    log_external_service_event,
    redact_secrets,
)

LIVE_KEY = "0123456789abcdef0123456789abcdef"
LEAKED_URL = (
    "https://serpapi.com/search.json?q=best+alternatives+to+qiko.ai+in+us"
    f"&location=us&api_key={LIVE_KEY}&engine=google"
)
PRODUCTION_LOG_MESSAGE = f"Client error '400 Bad Request' for url '{LEAKED_URL}'"


def test_redact_secrets_strips_api_key_but_keeps_diagnostics() -> None:
    sanitized = redact_secrets(PRODUCTION_LOG_MESSAGE)

    assert LIVE_KEY not in sanitized
    assert f"api_key={REDACTED_VALUE}" in sanitized
    # The genuinely useful diagnostic parts survive.
    assert "400 Bad Request" in sanitized
    assert "serpapi.com/search.json" in sanitized
    assert "q=best+alternatives+to+qiko.ai+in+us" in sanitized
    assert "engine=google" in sanitized


@pytest.mark.parametrize(
    "raw",
    [
        "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=x&key=" + LIVE_KEY,
        "https://maps.googleapis.com/maps/api/place/textsearch/json?query=x&key=" + LIVE_KEY,
        f"https://example.com/v1?access_token={LIVE_KEY}",
        f"https://example.com/v1?token={LIVE_KEY}&password={LIVE_KEY}",
        f"https://example.com/v1?client_secret={LIVE_KEY}",
    ],
)
def test_redact_secrets_covers_other_credential_query_parameters(raw: str) -> None:
    assert LIVE_KEY not in redact_secrets(raw)


def test_redact_secrets_leaves_harmless_parameters_intact() -> None:
    raw = "https://serpapi.com/search.json?q=keyword+research&num=5&engine=google"

    assert redact_secrets(raw) == raw


def test_http_target_for_log_drops_the_whole_query_string() -> None:
    assert http_target_for_log(LEAKED_URL) == "serpapi.com/search.json"


def test_describe_http_failure_keeps_host_path_and_status_code() -> None:
    request = httpx.Request("GET", LEAKED_URL)
    response = httpx.Response(400, request=request)
    exc = httpx.HTTPStatusError(PRODUCTION_LOG_MESSAGE, request=request, response=response)

    detail = describe_http_failure(LEAKED_URL, exc)

    assert LIVE_KEY not in detail
    assert "serpapi.com/search.json" in detail
    assert "HTTP 400" in detail
    assert "HTTPStatusError" in detail


def test_log_external_service_event_redacts_the_detail_field(caplog) -> None:
    logger = logging.getLogger("test_outbound_url_secret_redaction")

    with caplog.at_level(logging.ERROR, logger=logger.name):
        log_external_service_event(
            logger,
            service="serpapi",
            operation="geo_visibility_query",
            status="error",
            duration_ms_value=12,
            http_status=400,
            detail=PRODUCTION_LOG_MESSAGE,
        )

    emitted = caplog.text
    assert LIVE_KEY not in emitted
    assert f"api_key={REDACTED_VALUE}" in emitted
    assert "'http_status': 400" in emitted


@pytest.mark.asyncio
async def test_failed_geo_query_never_logs_the_serpapi_key(monkeypatch, caplog) -> None:
    """End-to-end guard on the exact production failure: SerpAPI answers 400/401 and the
    key must not reach the logger, the returned payload, or the persisted error field."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["api_key"] == LIVE_KEY
        return httpx.Response(400, text="Bad Request")

    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "generic")
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.setattr(settings, "SEARCH_API_KEY", None)
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", LIVE_KEY)

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    service = GeoVisibilityService()

    with caplog.at_level(logging.WARNING):
        result = await service.run_visibility_audit(
            target="qiko.ai",
            location="us",
            seed_queries=["best alternatives to qiko.ai in us"],
        )

    assert LIVE_KEY not in caplog.text
    assert "GEO visibility query failed" in caplog.text
    # Host, path and status code still identify the failing upstream call.
    assert "serpapi.com/search.json" in caplog.text
    assert "HTTP 400" in caplog.text

    query_result = result["results"][0]
    assert query_result["status"] == "error"
    assert LIVE_KEY not in query_result["error"]
    assert "HTTP 400" in query_result["error"]
