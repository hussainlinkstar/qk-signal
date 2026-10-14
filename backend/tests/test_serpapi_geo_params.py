"""SerpAPI geographic parameter regression tests.

Production sent the project country as ``location=us`` and SerpAPI answered
``HTTP 400 {"error": "Unsupported \\`us\\` location - location parameter."}`` for
every single query, so the whole GEO visibility feature returned nothing. The
key itself was valid throughout. These tests pin the two properties that were
missing: the country travels in ``gl``, and a provider 4xx is never reported as
a clean zero-visibility result.

Every provider call here is mocked. Nothing in this file may reach the live
SerpAPI account.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.brand_signal_collector_service import BrandSignalCollectorService
from services.competitors import provider_adapters
from services.geo_visibility_service import GeoVisibilityService
from services.serpapi_params import build_serpapi_geo_params, resolve_country_code


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)


def _use_serpapi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "generic")
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.setattr(settings, "SEARCH_API_KEY", None)
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", "serp-key")


# --------------------------------------------------------------------- #
#  Parameter mapping
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("market", "expected"),
    [
        ("us", "us"),
        ("US", "us"),
        ("  de  ", "de"),
        ("en-us", "us"),
        ("en_US", "us"),
        ("co-uk", "uk"),
        ("global", None),
        ("", None),
        (None, None),
        ("Bucharest", None),
        ("new york", None),
    ],
)
def test_resolve_country_code(market, expected):
    assert resolve_country_code(market) == expected


def test_country_market_never_becomes_a_location():
    params = build_serpapi_geo_params("us", allow_location=True)
    assert params == {"gl": "us"}
    assert "location" not in params


def test_place_name_stays_a_location_when_the_caller_allows_it():
    assert build_serpapi_geo_params("Bucharest", allow_location=True) == {"location": "Bucharest"}
    # A market identifier is not a location, so it is dropped rather than
    # guessed at.
    assert build_serpapi_geo_params("Bucharest") == {}


def test_global_market_sends_no_geography():
    assert build_serpapi_geo_params("global", allow_location=True) == {}


def test_language_maps_to_hl():
    assert build_serpapi_geo_params("us", language="en-GB") == {"gl": "us", "hl": "en"}


# --------------------------------------------------------------------- #
#  The built request
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_geo_visibility_request_sends_country_in_gl_not_location(monkeypatch):
    """The exact production request shape that used to return HTTP 400."""
    captured: dict[str, httpx.URL] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        return httpx.Response(200, json={"organic_results": []})

    _use_serpapi(monkeypatch)
    _install_mock_transport(monkeypatch, handler)

    await GeoVisibilityService().execute_query("best alternatives to qiko.ai in us", "us")

    params = captured["url"].params
    assert params["gl"] == "us"
    assert "location" not in params
    assert params["engine"] == "google"


@pytest.mark.asyncio
async def test_geo_visibility_request_keeps_a_real_place_name_in_location(monkeypatch):
    captured: dict[str, httpx.URL] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        return httpx.Response(200, json={"organic_results": []})

    _use_serpapi(monkeypatch)
    _install_mock_transport(monkeypatch, handler)

    await GeoVisibilityService().execute_query("best clinic", "Bucharest")

    params = captured["url"].params
    assert params["location"] == "Bucharest"
    assert "gl" not in params


@pytest.mark.asyncio
async def test_competitor_serp_provider_sends_country_in_gl_not_location(monkeypatch):
    captured: dict[str, httpx.URL] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = request.url
        return httpx.Response(200, json={"organic_results": [{"title": "Acme"}]})

    monkeypatch.setattr(settings, "SERPAPI_API_KEY", "serp-key")
    _install_mock_transport(monkeypatch, handler)

    results = await provider_adapters.serpapi_provider("https://qiko.ai", "dental clinic", "us")

    assert results == [{"name": "Acme"}]
    params = captured["url"].params
    assert params["gl"] == "us"
    assert "location" not in params


@pytest.mark.asyncio
async def test_brand_serp_signals_send_country_in_gl_and_no_junk_code(monkeypatch):
    """``market[:2]`` used to turn "bucharest" into the country code "bu"."""
    captured: list[dict[str, str]] = []

    async def fake_fetch(url: str, *, method="GET", timeout=15.0, params=None, **kwargs):
        captured.append(dict(params or {}))
        return httpx.Response(200, json={"organic_results": []})

    monkeypatch.setattr("services.url_validation.safe_async_fetch", fake_fetch)
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", "serp-key")

    service = BrandSignalCollectorService()
    service.serpapi_key = "serp-key"

    await service._collect_serp_signals("Qiko", category="", market="us", domain="qiko.ai")
    assert captured[0]["gl"] == "us"
    assert "location" not in captured[0]

    captured.clear()
    await service._collect_serp_signals("Qiko", category="", market="bucharest", domain="qiko.ai")
    assert "gl" not in captured[0]
    assert "location" not in captured[0]


# --------------------------------------------------------------------- #
#  A provider 4xx is not a zero-visibility result
# --------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_provider_4xx_is_not_reported_as_clean_zero_visibility(monkeypatch, caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": "Unsupported `us` location - location parameter."}
        )

    _use_serpapi(monkeypatch)
    _install_mock_transport(monkeypatch, handler)

    with caplog.at_level(logging.WARNING):
        result = await GeoVisibilityService().run_visibility_audit(
            target="qiko.ai",
            location="us",
            seed_queries=["best alternatives to qiko.ai", "top providers like qiko.ai"],
        )

    assert result["visibility_index"] == 0.0
    # ... but the payload says loudly that the zero was never measured.
    assert result["visibility_measured"] is False
    assert result["answered_queries"] == 0
    assert result["failed_queries"] == 2
    assert result["provider_rejected_queries"] == 2
    assert result["partial_results"] is True
    assert "HTTP 400" in result["provider_error"]
    assert all(item["provider_status_code"] == 400 for item in result["results"])
    assert "serp-key" not in caplog.text


@pytest.mark.asyncio
async def test_measured_zero_visibility_stays_a_clean_zero(monkeypatch):
    """The contrast case: the provider answered, the brand was simply absent."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {"title": "Someone else", "link": "https://example.com", "snippet": "no match"}
                ]
            },
        )

    _use_serpapi(monkeypatch)
    _install_mock_transport(monkeypatch, handler)

    result = await GeoVisibilityService().run_visibility_audit(
        target="qiko.ai",
        location="us",
        seed_queries=["best alternatives to qiko.ai"],
    )

    assert result["visibility_index"] == 0.0
    assert result["visibility_measured"] is True
    assert result["answered_queries"] == 1
    assert result["provider_rejected_queries"] == 0
    assert result["provider_error"] is None
    assert result["partial_results"] is False


@pytest.mark.asyncio
async def test_partial_provider_failure_does_not_dilute_the_index(monkeypatch):
    """One answered query citing the brand is 100 percent, not 50 percent."""
    responses = [
        httpx.Response(
            200,
            json={
                "organic_results": [
                    {"title": "Qiko", "link": "https://qiko.ai", "snippet": "the brand"}
                ]
            },
        ),
        httpx.Response(400, json={"error": "Unsupported `us` location - location parameter."}),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return responses.pop(0)

    _use_serpapi(monkeypatch)
    _install_mock_transport(monkeypatch, handler)

    result = await GeoVisibilityService().run_visibility_audit(
        target="qiko.ai",
        location="us",
        seed_queries=["query one", "query two"],
    )

    assert result["answered_queries"] == 1
    assert result["citations"] == 1
    assert result["visibility_index"] == 100.0
    assert result["visibility_measured"] is True
    assert result["partial_results"] is True
    assert result["provider_rejected_queries"] == 1


@pytest.mark.asyncio
async def test_brand_ai_visibility_signal_reports_provider_failure(monkeypatch):
    """A refused provider must not score as a collected zero-visibility signal."""

    class _FailedVisibilityService:
        async def run_visibility_audit(self, **_kwargs):
            return {
                "visibility_index": 0.0,
                "visibility_measured": False,
                "total_queries": 3,
                "answered_queries": 0,
                "citations": 0,
                "partial_results": True,
                "provider_rejected_queries": 3,
                "provider_error": "HTTPStatusError for serpapi.com/search.json: HTTP 400",
                "results": [],
            }

    monkeypatch.setattr(
        "services.geo_visibility_service.GeoVisibilityService",
        _FailedVisibilityService,
    )

    service = BrandSignalCollectorService()
    signal = await service._collect_ai_visibility_signals("Qiko", category="", market="us")

    assert signal["status"] == "provider_error"
    assert signal["visibility_measured"] is False
    assert signal["provider_rejected_queries"] == 3
    assert "HTTP 400" in signal["provider_error"]

    # An unmeasured signal must not be counted or scored as if it were data.
    summary = service._build_brand_summary("Qiko", {"ai_visibility": signal})
    assert "ai_visibility" not in summary["score_components"]
    assert summary["signals_collected"] == 0
