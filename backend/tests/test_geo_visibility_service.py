import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import services.geo_visibility_service as geo_visibility_module
from core.config import settings
from services.geo_visibility_service import GeoVisibilityService, ProviderResponseError


@pytest.mark.asyncio
async def test_generic_search_uses_serpapi_defaults_when_key_is_set(monkeypatch):
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "organic_results": [
                    {
                        "title": "Acme Dental",
                        "link": "https://example.com/acme",
                        "snippet": "Top rated clinic",
                    }
                ]
            },
        )

    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "generic")
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.setattr(settings, "SEARCH_API_KEY", None)
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", "serp-key")

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    service = GeoVisibilityService()
    result = await service.execute_query("best clinic", "Bucharest")

    assert result.citations == ["https://example.com/acme"]
    requested_url = captured["url"]
    assert "serpapi.com/search.json" in requested_url
    assert "api_key=serp-key" in requested_url
    assert "engine=google" in requested_url
    # Query params via httpx.URL rather than a raw substring match on "q=best%20clinic":
    # httpx encodes spaces as "+" (not "%20") in query strings as of 0.28, both are
    # valid, equivalent encodings, so assert on the decoded value instead of the wire form.
    assert httpx.URL(requested_url).params["q"] == "best clinic"
    assert "location=Bucharest" in requested_url


@pytest.mark.asyncio
async def test_generic_search_requires_search_url_or_serpapi_key(monkeypatch):
    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "generic")
    monkeypatch.delenv("SEARCH_API_URL", raising=False)
    monkeypatch.delenv("SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    service = GeoVisibilityService()

    with pytest.raises(ProviderResponseError, match="SEARCH_API_URL or SERPAPI_API_KEY"):
        await service.execute_query("best clinic", "Bucharest")


@pytest.mark.asyncio
async def test_firecrawl_search_success_records_healthy_service_outcome(monkeypatch):
    recorded: list[dict] = []

    async def fake_record(service, *, ok, detail=""):
        recorded.append({"service": service, "ok": ok, "detail": detail})

    monkeypatch.setattr(geo_visibility_module, "record_service_outcome", fake_record)
    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "firecrawl")

    service = GeoVisibilityService()
    service.firecrawl_app = SimpleNamespace(
        search=AsyncMock(return_value={"data": [{"url": "https://example.com", "title": "Acme"}]})
    )

    result = await service.execute_query("best clinic", "Bucharest")

    assert result.citations == ["https://example.com"]
    assert recorded == [{"service": "firecrawl", "ok": True, "detail": ""}]


@pytest.mark.asyncio
async def test_firecrawl_search_reads_v2_search_data_grouped_results(monkeypatch):
    """firecrawl-py 4.x returns SearchData (``web``/``news``/``images`` groups),
    not a flat ``data``/``results`` list. Reading the old shape silently yields
    zero citations, which measured every brand as invisible (geo score 0)."""
    monkeypatch.setattr(geo_visibility_module, "record_service_outcome", AsyncMock())
    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "firecrawl")

    search_data_dump = {
        "web": [
            {
                "url": "https://qiko.ai/platform",
                "title": "Qiko AI platform",
                "description": "SEO and AI visibility audits",
                "category": None,
            },
            {
                "url": "https://competitor.example",
                "title": "Competitor",
                "description": "Alternative audit tool",
                "category": None,
            },
        ],
        "news": [],
        "images": [],
    }
    # The real SDK returns a pydantic model; non-dict payloads go through
    # ``model_dump()`` in the service, so the fake mirrors exactly that.
    fake_payload = SimpleNamespace(model_dump=lambda: search_data_dump)

    service = GeoVisibilityService()
    service.firecrawl_app = SimpleNamespace(search=AsyncMock(return_value=fake_payload))

    result = await service.execute_query("best audit tools", "global")

    assert result.citations == ["https://qiko.ai/platform", "https://competitor.example"]
    assert "Qiko AI platform" in result.answer


@pytest.mark.asyncio
async def test_firecrawl_search_failure_records_unhealthy_service_outcome_and_still_raises(
    monkeypatch,
):
    """A quota/billing failure on GEO competitor search shares the same
    "firecrawl" health signal as the page scraper (same account/credits)."""
    recorded: list[dict] = []

    async def fake_record(service, *, ok, detail=""):
        recorded.append({"service": service, "ok": ok, "detail": detail})

    monkeypatch.setattr(geo_visibility_module, "record_service_outcome", fake_record)
    monkeypatch.setenv("GEO_VISIBILITY_PROVIDER", "firecrawl")

    service = GeoVisibilityService()
    service.firecrawl_app = SimpleNamespace(
        search=AsyncMock(
            side_effect=RuntimeError(
                "Payment Required: Failed to search. Insufficient credits to perform this request."
            )
        )
    )

    with pytest.raises(ProviderResponseError):
        await service.execute_query("best clinic", "Bucharest")

    assert len(recorded) == 1
    assert recorded[0] == {
        "service": "firecrawl",
        "ok": False,
        "detail": "Payment Required: Failed to search. Insufficient credits to perform this request.",
    }


@pytest.mark.asyncio
async def test_empty_provider_response_is_not_measured_as_zero_visibility(monkeypatch):
    """A search that returns nothing measured nothing.

    An empty provider response carries no answer text and no citations, so
    scoring it as "the brand was not cited" turns a provider-side failure
    into a published zero. That is the shape of the degraded-scan reports:
    the same site measured minutes apart swings between a real score and 0
    purely on whether the search backend answered. Empty probes are counted
    as rejections, exactly like a 4xx, so they stay out of the denominator
    and ``visibility_measured`` tells the truth when every probe came back
    blank.
    """
    service = GeoVisibilityService()
    answers = {
        "q-empty": geo_visibility_module.SearchProviderResult(
            query="q-empty", answer="   ", citations=[]
        ),
        "q-live": geo_visibility_module.SearchProviderResult(
            query="q-live",
            answer="Qiko AI platform - audit tooling",
            citations=["https://qiko.ai/platform"],
        ),
    }

    async def fake_execute(*, query: str, location: str):
        return answers[query]

    monkeypatch.setattr(service, "execute_query", fake_execute)

    payload = await service.run_visibility_audit(
        target="https://qiko.ai",
        location="global",
        seed_queries=["q-empty", "q-live"],
        brand="Qiko",
    )

    # One probe answered, and the brand was cited in it: the empty probe
    # neither counts as an answer nor dilutes the score to 50.
    assert payload["answered_queries"] == 1
    assert payload["citations"] == 1
    assert payload["visibility_index"] == 100.0
    assert payload["visibility_measured"] is True
    assert payload["provider_rejected_queries"] == 1
    statuses = [row["status"] for row in payload["results"]]
    assert statuses == ["empty", "ok"]
    assert payload["partial_results"] is True


@pytest.mark.asyncio
async def test_all_probes_empty_reports_nothing_measured(monkeypatch):
    """Every probe blank is an outage, not a brand with zero visibility."""
    service = GeoVisibilityService()

    async def fake_execute(*, query: str, location: str):
        return geo_visibility_module.SearchProviderResult(query=query, answer="", citations=[])

    monkeypatch.setattr(service, "execute_query", fake_execute)

    payload = await service.run_visibility_audit(
        target="https://qiko.ai",
        location="global",
        seed_queries=["a", "b"],
        brand="Qiko",
    )

    assert payload["answered_queries"] == 0
    assert payload["visibility_measured"] is False
    assert payload["provider_rejected_queries"] == 2
