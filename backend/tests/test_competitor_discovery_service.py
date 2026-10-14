import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.competitors.discovery_service import CompetitorDiscoveryService


class StubCompetitorAIFactory:
    def __init__(self, competitors: list[dict[str, str]] | None = None) -> None:
        self._competitors = competitors or []
        self.calls = 0

    async def generate_competitors(
        self,
        *,
        provider: str = "google",
        tier: str = "fast",
        site_url: str,
        category: str,
        market: str,
        content: str | None = None,
    ) -> list[dict[str, str]]:
        self.calls += 1
        return [dict(item) for item in self._competitors]


@pytest.mark.asyncio
async def test_discover_competitors_returns_three_to_five_with_sources_and_scores():
    async def fake_places(_site: str, _category: str, _market: str):
        return ["Atlas Dental Group", {"name": "Bright Smile Clinic"}]

    async def fake_serp(_site: str, _category: str, _market: str):
        return ["Peak Orthodontics", {"title": "Citywide Dental Partners"}]

    service = CompetitorDiscoveryService(places_provider=fake_places, serp_provider=fake_serp)

    result = await service.discover_competitors(
        site_url="https://www.exampledental.com",
        category="dental clinic",
        market="austin",
    )

    competitors = result["competitors"]

    assert result["cached"] is False
    assert 3 <= len(competitors) <= 5
    assert {entry["source"] for entry in competitors}.issubset({"Places", "SERP"})
    assert all(0.55 <= entry["confidence_score"] <= 0.84 for entry in competitors)
    assert all(entry["shared_entities"] == [] for entry in competitors)
    assert all(entry["entity_overlap_score"] == 0.0 for entry in competitors)


@pytest.mark.asyncio
async def test_discover_competitors_filters_editorial_serp_titles_and_uses_llm_recovery():
    async def fake_serp(_site: str, _category: str, _market: str):
        return [
            {"title": "10 Biggest Ecommerce Platforms in the World (2026 ...)"},
            {"title": "Top 20 ecommerce marketplaces in the world in 2026"},
            {"title": "Most Visited Retail Websites in the World ..."},
        ]

    ai_factory = StubCompetitorAIFactory(
        competitors=[
            {"name": "Adidas", "source": "LLM Discovery"},
            {"name": "Puma", "source": "LLM Discovery"},
            {"name": "New Balance", "source": "LLM Discovery"},
        ]
    )
    service = CompetitorDiscoveryService(serp_provider=fake_serp, ai_factory=ai_factory)

    result = await service.discover_competitors(
        site_url="https://www.nike.com",
        category="e-commerce - online retail store",
        market="global",
    )

    names = [entry["name"] for entry in result["competitors"]]

    assert ai_factory.calls == 1
    assert names == ["Adidas", "Puma", "New Balance"]
    assert all("Platforms" not in name for name in names)
    assert all(entry["source"] == "LLM Discovery" for entry in result["competitors"])


@pytest.mark.asyncio
async def test_discover_competitors_ranks_by_shared_entities_and_citation_overlap():
    service = CompetitorDiscoveryService()
    full_report = {
        "entities": ["orthodontics", "invisalign", "austin"],
        "competitors": [
            {
                "name": "Elite Smile Studio",
                "entities": ["orthodontics", "invisalign", "austin"],
                "citations": [
                    {"entities": ["orthodontics"]},
                    {"entities": ["invisalign", "braces"]},
                ],
            },
            {
                "name": "Downtown Braces",
                "entities": ["orthodontics"],
                "citations": [{"entities": ["orthodontics"]}],
            },
        ],
    }

    result = await service.discover_competitors(
        site_url="https://exampledental.com",
        category="dental clinic",
        market="austin",
        full_report=full_report,
    )

    competitors = result["competitors"]

    assert [entry["name"] for entry in competitors[:2]] == ["Elite Smile Studio", "Downtown Braces"]
    assert competitors[0]["source"] == "EntityGraph"
    assert competitors[0]["shared_entities"] == ["austin", "invisalign", "orthodontics"]
    assert competitors[0]["entity_overlap_score"] > competitors[1]["entity_overlap_score"]
    assert competitors[0]["confidence_score"] > competitors[1]["confidence_score"]


@pytest.mark.asyncio
async def test_discover_competitors_uses_persistent_audit_entities_and_ranks_by_confidence():
    async def audit_history_provider(_site: str):
        return [
            {
                "site": "exampledental.com",
                "is_target": True,
                "created_at": "2026-01-20T10:00:00Z",
                "full_report": {"entities": ["orthodontics", "invisalign", "austin", "braces"]},
            },
            {
                "site": "elitesmile.com",
                "domain": "Elite Smile Studio",
                "created_at": "2026-01-25T09:00:00Z",
                "full_report": {
                    "entities": ["orthodontics", "invisalign", "austin"],
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "best invisalign orthodontics in austin",
                                "brand_cited": True,
                                "provider_citations": [
                                    "https://source1.example",
                                    "https://source2.example",
                                ],
                            },
                            {
                                "query": "austin braces clinic",
                                "brand_cited": True,
                                "provider_citations": ["https://source3.example"],
                            },
                        ]
                    },
                },
            },
            {
                "site": "budgetsmiles.com",
                "domain": "Budget Smiles",
                "created_at": "2025-05-10T09:00:00Z",
                "full_report": {
                    "entities": ["orthodontics"],
                    "geo_visibility": {
                        "results": [
                            {
                                "query": "orthodontics tips",
                                "brand_cited": True,
                                "provider_citations": ["https://source4.example"],
                            }
                        ]
                    },
                },
            },
        ]

    service = CompetitorDiscoveryService(entity_audit_provider=audit_history_provider)

    result = await service.discover_competitors(
        site_url="https://exampledental.com",
        category="dental clinic",
        market="austin",
        full_report={"entities": ["dentist"]},
    )

    competitors = result["competitors"]

    assert competitors[0]["source"] == "EntityGraph"
    assert competitors[0]["name"] == "Elite Smile Studio"
    assert competitors[1]["name"] == "Budget Smiles"
    assert competitors[0]["shared_entities"] == ["austin", "invisalign", "orthodontics"]
    assert competitors[1]["shared_entities"] == ["orthodontics"]
    assert competitors[0]["entity_overlap_score"] > competitors[1]["entity_overlap_score"]
    assert competitors[0]["confidence_score"] > competitors[1]["confidence_score"]


@pytest.mark.asyncio
async def test_discover_competitors_falls_back_to_providers_when_entity_graph_insufficient():
    calls = {"places": 0, "serp": 0}

    async def fake_places(_site: str, _category: str, _market: str):
        calls["places"] += 1
        return ["Atlas Dental Group"]

    async def fake_serp(_site: str, _category: str, _market: str):
        calls["serp"] += 1
        return ["Peak Orthodontics"]

    service = CompetitorDiscoveryService(places_provider=fake_places, serp_provider=fake_serp)
    full_report = {
        "entities": ["orthodontics"],
        "competitors": [{"name": "Downtown Braces", "entities": ["orthodontics"]}],
    }

    result = await service.discover_competitors(
        site_url="https://exampledental.com",
        category="dental clinic",
        market="austin",
        full_report=full_report,
    )

    names = [entry["name"] for entry in result["competitors"]]

    assert result["cached"] is False
    assert names[0] == "Downtown Braces"
    assert "Atlas Dental Group" in names
    assert "Peak Orthodontics" in names
    assert calls == {"places": 1, "serp": 1}


@pytest.mark.asyncio
async def test_discover_competitors_caches_per_site():
    calls = {"places": 0, "serp": 0}

    async def fake_places(_site: str, _category: str, _market: str):
        calls["places"] += 1
        return ["Alpha HVAC"]

    async def fake_serp(_site: str, _category: str, _market: str):
        calls["serp"] += 1
        return ["Bravo Heating"]

    service = CompetitorDiscoveryService(places_provider=fake_places, serp_provider=fake_serp)

    first = await service.discover_competitors(
        site_url="https://www.coolair.io",
        category="hvac",
        market="phoenix",
    )
    second = await service.discover_competitors(
        site_url="https://coolair.io",
        category="hvac",
        market="phoenix",
    )

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["competitors"] == second["competitors"]
    assert calls == {"places": 1, "serp": 1}


@pytest.mark.asyncio
async def test_discover_competitors_validates_input():
    service = CompetitorDiscoveryService()

    with pytest.raises(ValueError, match="site_url is required"):
        await service.discover_competitors(site_url=" ", category="plumber", market="seattle")

    with pytest.raises(ValueError, match="category is required"):
        await service.discover_competitors(
            site_url="https://example.com", category=" ", market="seattle"
        )

    with pytest.raises(ValueError, match="market is required"):
        await service.discover_competitors(
            site_url="https://example.com", category="plumber", market=" "
        )


@pytest.mark.asyncio
async def test_discover_competitors_fallback_uses_passed_category_for_names(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENABLE_TEXTUAL_COMPETITOR_FALLBACK", "true")
    ai_factory = StubCompetitorAIFactory(
        competitors=[
            {"name": "Mile High Hvac Pros", "source": "LLM Discovery"},
            {"name": "Denver Hvac Experts", "source": "LLM Discovery"},
            {"name": "Front Range Hvac Co", "source": "LLM Discovery"},
        ]
    )
    service = CompetitorDiscoveryService(ai_factory=ai_factory)

    result = await service.discover_competitors(
        site_url="https://metrocoolingpros.com",
        category="hvac",
        market="denver",
    )

    names = [entry["name"] for entry in result["competitors"]]

    assert len(names) >= 3
    assert ai_factory.calls == 1
    assert all("General" not in name for name in names)
    assert any("Hvac" in name for name in names)


@pytest.mark.asyncio
async def test_discover_competitors_fallback_supports_niche_categories_for_sample_domain(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENABLE_TEXTUAL_COMPETITOR_FALLBACK", "true")
    ai_factory = StubCompetitorAIFactory(
        competitors=[
            {"name": "Summit Law Group", "source": "LLM Discovery"},
            {"name": "Chicago Injury Law Partners", "source": "LLM Discovery"},
            {"name": "Lakefront Law Office", "source": "LLM Discovery"},
        ]
    )
    service = CompetitorDiscoveryService(ai_factory=ai_factory)

    result = await service.discover_competitors(
        site_url="https://summitinjurylaw.com",
        category="law firm",
        market="chicago",
    )

    names = [entry["name"] for entry in result["competitors"]]

    assert len(names) >= 3
    assert ai_factory.calls == 1
    assert any("Law" in name for name in names)
    assert all("General" not in name for name in names)


# ---------------------------------------------------------------------------
# SIGV2-1285. Edward was shown these two strings as competitor brands, each
# with a confidence score beside it:
#
#   "List Greatest General From Different Countries"
#   "The Top 10 Generals in World History"
#
# Two defects let them through. The screen was applied only where `source` was
# "Places" or "SERP", exempting the entity extractor and the textual fallback,
# which is where these came from. And the screen did not recognise them anyway:
# its superlative pattern was anchored to the start of the string, so "The Top
# 10 ..." passed on the strength of a leading article.
# ---------------------------------------------------------------------------

EDWARDS_HEADLINES = (
    "List Greatest General From Different Countries",
    "The Top 10 Generals in World History",
)

OTHER_EDITORIAL_TITLES = (
    "Best Dental Clinics in Dubai",
    "15 Leading Agencies 2026",
    "A Guide to Dental Clinics",
    "Top 10 CRMs | TechRadar",
    "Best SEO Tools",
    "Something truncated here...",
)

REAL_BRANDS = (
    "Tessiant",
    "Accenture",
    "McKinsey & Company",
    "Best Buy",
    "The Walt Disney Company",
    "Oladoc",
    "Topshop",
    "Deloitte Digital",
    "Boston Consulting Group",
    "Mayo Clinic",
)


def test_the_two_headlines_edward_was_shown_are_recognised_as_prose():
    for headline in EDWARDS_HEADLINES:
        assert CompetitorDiscoveryService._looks_like_editorial_title(headline), headline


def test_other_article_shapes_are_recognised_too():
    # Fixing only the two that were reported would leave the class open.
    for title in OTHER_EDITORIAL_TITLES:
        assert CompetitorDiscoveryService._looks_like_editorial_title(title), title


def test_a_real_brand_survives_the_screen():
    # The screen has to be sharper than "contains a superlative": Best Buy is
    # a shop, "Best Dental Clinics" is an article, and a product that drops
    # real competitors is no better than one that invents them.
    for brand in REAL_BRANDS:
        assert not CompetitorDiscoveryService._looks_like_editorial_title(brand), brand


def test_the_screen_is_not_limited_to_one_source():
    # The defect was the condition `source in {"Places", "SERP"}`. A name that
    # is prose is prose whichever code path found it, and every candidate
    # reaching the customer carries a confidence score.
    import inspect

    source = inspect.getsource(CompetitorDiscoveryService.discover_competitors)
    assert 'source in {"Places", "SERP"}' not in source
    # And the screen runs over the combined list, not just the provider one.
    assert "_looks_like_editorial_title(self._extract_name(candidate))" in source
