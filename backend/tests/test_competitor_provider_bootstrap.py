import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.competitors import provider_adapters


@pytest.mark.asyncio
async def test_bootstrap_wires_external_providers_when_api_keys_present(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", "serp-key")
    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", "places-key")

    async def _fake_places(site_url: str, category: str, market: str):
        assert site_url == "https://example.com"
        assert category == "dental clinic"
        assert market == "austin"
        return [{"name": "Atlas Dental"}]

    async def _fake_serp(site_url: str, category: str, market: str):
        assert site_url == "https://example.com"
        assert category == "dental clinic"
        assert market == "austin"
        return [{"name": "Peak Orthodontics"}]

    monkeypatch.setattr(provider_adapters, "google_places_provider", _fake_places)
    monkeypatch.setattr(provider_adapters, "serpapi_provider", _fake_serp)

    async def _fake_entity_provider(_site: str):
        return []

    monkeypatch.setattr(provider_adapters, "entity_audit_history_provider", _fake_entity_provider)

    service = provider_adapters.build_competitor_discovery_service()

    result = await service.discover_competitors(
        site_url="https://example.com",
        category="dental clinic",
        market="austin",
    )

    names = {item["name"] for item in result["competitors"]}
    assert "Atlas Dental" in names
    assert "Peak Orthodontics" in names
    assert result["provider_health"] == "ok"


@pytest.mark.asyncio
async def test_bootstrap_disables_external_providers_without_api_keys(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    service = provider_adapters.build_competitor_discovery_service()
    result = await service.discover_competitors(
        site_url="https://example.com",
        category="dental clinic",
        market="austin",
    )

    assert result["provider_status"]["places"] == "disabled"
    assert result["provider_status"]["serp"] == "disabled"
    assert result["provider_health"] == "disabled"


@pytest.mark.asyncio
async def test_bootstrap_uses_google_api_key_for_places_when_dedicated_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", "shared-google-key")
    monkeypatch.setattr(settings, "GOOGLE_PLACES_API_KEY", None)
    monkeypatch.setattr(settings, "GOOGLE_MAPS_API_KEY", None)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(settings, "SERPAPI_API_KEY", None)

    async def _fake_places(site_url: str, category: str, market: str):
        assert site_url == "https://example.com"
        assert category == "dental clinic"
        assert market == "austin"
        return [{"name": "City Dental"}]

    async def _fake_entity_provider(_site: str):
        return []

    monkeypatch.setattr(provider_adapters, "google_places_provider", _fake_places)
    monkeypatch.setattr(provider_adapters, "entity_audit_history_provider", _fake_entity_provider)

    service = provider_adapters.build_competitor_discovery_service()
    result = await service.discover_competitors(
        site_url="https://example.com",
        category="dental clinic",
        market="austin",
    )

    names = {item["name"] for item in result["competitors"]}
    assert "City Dental" in names
    assert result["provider_status"]["places"] == "ok"
