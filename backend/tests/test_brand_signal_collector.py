"""Tests for BrandSignalCollectorService and brand signal scoring boost."""

from __future__ import annotations

import os

os.environ.setdefault("SSM_ENABLED", "false")

import asyncio
from unittest.mock import patch

import pytest

from services.brand_signal_collector_service import BrandSignalCollectorService
from score_utils import (
    ScoreBreakdown,
    _apply_brand_signal_boost,
    _BRAND_SIGNAL_WEIGHTS,
    calculate_deterministic_scores,
)


# ------------------------------------------------------------------ #
#  BrandSignalCollectorService unit tests
# ------------------------------------------------------------------ #


class TestBrandSignalCollectorService:
    """Tests for the BrandSignalCollectorService."""

    @pytest.fixture()
    def service(self):
        with patch("services.brand_signal_collector_service.settings") as mock_settings:
            mock_settings.SERPAPI_API_KEY = "test-key"
            svc = BrandSignalCollectorService()
            svc.serpapi_key = "test-key"
            return svc

    def test_empty_brand_returns_empty_result(self):
        with patch("services.brand_signal_collector_service.settings") as mock_settings:
            mock_settings.SERPAPI_API_KEY = ""
            svc = BrandSignalCollectorService()
            result = asyncio.run(svc.collect_brand_signals(brand_name=""))
            assert result["summary"]["signals_collected"] == 0
            assert result["summary"]["brand_presence_score"] == 0

    def test_whitespace_brand_returns_empty_result(self):
        with patch("services.brand_signal_collector_service.settings") as mock_settings:
            mock_settings.SERPAPI_API_KEY = ""
            svc = BrandSignalCollectorService()
            result = asyncio.run(svc.collect_brand_signals(brand_name="   "))
            assert result["summary"]["signals_collected"] == 0

    def test_extract_knowledge_graph_with_panel(self, service):
        serp_data = {
            "knowledge_panel": {
                "title": "Acme Corp",
                "type": "Company",
                "description": "A leading widget manufacturer.",
                "website": "https://acme.com",
                "thumbnail": "https://example.com/thumb.jpg",
                "founded": "1990",
            }
        }
        result = service._extract_knowledge_graph(serp_data)
        assert result["has_knowledge_panel"] is True
        assert result["title"] == "Acme Corp"
        assert result["type"] == "Company"
        assert result["description"] == "A leading widget manufacturer."
        assert result["website"] == "https://acme.com"
        assert result["attributes"]["founded"] == "1990"

    def test_extract_knowledge_graph_without_panel(self, service):
        result = service._extract_knowledge_graph({})
        assert result["has_knowledge_panel"] is False
        assert result["status"] == "not_found"

    def test_build_brand_summary_with_all_signals(self, service):
        signals = {
            "serp": {
                "status": "ok",
                "brand_domain_found": True,
                "brand_mention_rate": 80.0,
            },
            "knowledge_graph": {
                "has_knowledge_panel": True,
                "description": "A company",
                "website": "https://acme.com",
            },
            "wikidata": {
                "entity_exists": True,
                "has_wikipedia": True,
                "sitelinks_count": 10,
            },
            "ai_visibility": {
                "status": "ok",
                "visibility_index": 75,
            },
        }
        summary = service._build_brand_summary("Acme", signals)
        assert summary["signals_collected"] == 4
        assert summary["confidence"] == "high"
        assert summary["brand_presence_score"] > 0
        assert "serp_presence" in summary["score_components"]
        assert "knowledge_graph" in summary["score_components"]
        assert "wikidata_presence" in summary["score_components"]
        assert "ai_visibility" in summary["score_components"]

    def test_build_brand_summary_no_signals(self, service):
        signals = {
            "serp": {"status": "error"},
            "knowledge_graph": {"status": "error"},
            "wikidata": {"status": "error"},
            "ai_visibility": {"status": "error"},
        }
        summary = service._build_brand_summary("Unknown Brand", signals)
        assert summary["signals_collected"] == 0
        assert summary["confidence"] == "low"
        assert summary["brand_presence_score"] == 0

    def test_build_brand_summary_serp_only(self, service):
        signals = {
            "serp": {
                "status": "ok",
                "brand_domain_found": False,
                "brand_mention_rate": 50.0,
            },
            "knowledge_graph": {"status": "not_found", "has_knowledge_panel": False},
            "wikidata": {"status": "not_found", "entity_exists": False},
            "ai_visibility": {"status": "error"},
        }
        summary = service._build_brand_summary("SmallBrand", signals)
        assert summary["signals_collected"] == 1
        assert summary["confidence"] == "low"
        assert summary["score_components"]["serp_presence"] > 0
        assert summary["score_components"]["knowledge_graph"] == 0.0
        assert summary["score_components"]["wikidata_presence"] == 0.0

    def test_serp_score_capped_at_30(self, service):
        signals = {
            "serp": {
                "status": "ok",
                "brand_domain_found": True,
                "brand_mention_rate": 100.0,
            },
            "knowledge_graph": {"status": "not_found", "has_knowledge_panel": False},
            "wikidata": {"status": "not_found", "entity_exists": False},
            "ai_visibility": {"status": "error"},
        }
        summary = service._build_brand_summary("BigBrand", signals)
        assert summary["score_components"]["serp_presence"] <= 30.0

    def test_kg_score_capped_at_25(self, service):
        signals = {
            "serp": {"status": "error"},
            "knowledge_graph": {
                "has_knowledge_panel": True,
                "description": "Description",
                "website": "https://example.com",
            },
            "wikidata": {"status": "not_found", "entity_exists": False},
            "ai_visibility": {"status": "error"},
        }
        summary = service._build_brand_summary("Brand", signals)
        assert summary["score_components"]["knowledge_graph"] <= 25.0

    def test_wikidata_score_with_wikipedia(self, service):
        signals = {
            "serp": {"status": "error"},
            "knowledge_graph": {"status": "not_found", "has_knowledge_panel": False},
            "wikidata": {
                "entity_exists": True,
                "has_wikipedia": True,
                "sitelinks_count": 20,
            },
            "ai_visibility": {"status": "error"},
        }
        summary = service._build_brand_summary("WikiBrand", signals)
        # 10 (base) + 10 (wikipedia) + 5 (sitelinks capped)
        assert summary["score_components"]["wikidata_presence"] == 25.0


# ------------------------------------------------------------------ #
#  Brand signal scoring boost tests
# ------------------------------------------------------------------ #


class TestBrandSignalBoost:
    """Tests for _apply_brand_signal_boost in score_utils."""

    def _make_breakdown(self, score: float = 5.0) -> ScoreBreakdown:
        return ScoreBreakdown(
            total_score=score,
            components={"base_metric": score},
            penalties=[],
            bonuses=[],
            metadata={},
        )

    def test_boost_applied_when_brand_score_higher(self):
        breakdown = self._make_breakdown(5.0)
        result = _apply_brand_signal_boost(
            breakdown,
            dimension="seo",
            serp_score=25.0,
            kg_score=20.0,
            wiki_score=15.0,
            ai_vis_score=10.0,
        )
        assert result.total_score > 5.0
        assert result.metadata.get("brand_signal_boosted") is True
        assert any(b["name"] == "brand_signal_boost" for b in result.bonuses)

    def test_no_boost_when_base_higher(self):
        breakdown = self._make_breakdown(95.0)
        result = _apply_brand_signal_boost(
            breakdown,
            dimension="seo",
            serp_score=5.0,
            kg_score=0.0,
            wiki_score=0.0,
            ai_vis_score=0.0,
        )
        # Should return original breakdown unchanged
        assert result.total_score == 95.0
        assert result.metadata.get("brand_signal_boosted") is None

    def test_boost_preserves_original_components(self):
        breakdown = self._make_breakdown(3.0)
        result = _apply_brand_signal_boost(
            breakdown,
            dimension="geo",
            serp_score=20.0,
            kg_score=25.0,
            wiki_score=20.0,
            ai_vis_score=15.0,
        )
        assert "base_metric" in result.components
        assert "brand_serp_presence" in result.components
        assert "brand_knowledge_graph" in result.components
        assert "brand_wikidata" in result.components
        assert "brand_ai_visibility" in result.components

    def test_seo_weights_favor_serp(self):
        seo_weights = _BRAND_SIGNAL_WEIGHTS["seo"]
        assert seo_weights["serp"] > seo_weights["kg"]
        assert seo_weights["serp"] > seo_weights["wiki"]
        assert seo_weights["serp"] > seo_weights["ai_vis"]

    def test_geo_weights_favor_kg_and_wiki(self):
        geo_weights = _BRAND_SIGNAL_WEIGHTS["geo"]
        assert geo_weights["kg"] >= geo_weights["serp"]
        assert geo_weights["wiki"] >= geo_weights["serp"]

    def test_aeo_weights_favor_ai_visibility(self):
        aeo_weights = _BRAND_SIGNAL_WEIGHTS["aeo"]
        assert aeo_weights["ai_vis"] > aeo_weights["serp"]
        assert aeo_weights["ai_vis"] > aeo_weights["kg"]
        assert aeo_weights["ai_vis"] > aeo_weights["wiki"]

    def test_zero_signals_no_boost(self):
        breakdown = self._make_breakdown(5.0)
        result = _apply_brand_signal_boost(
            breakdown,
            dimension="seo",
            serp_score=0.0,
            kg_score=0.0,
            wiki_score=0.0,
            ai_vis_score=0.0,
        )
        assert result.total_score == 5.0

    def test_score_capped_at_100(self):
        breakdown = self._make_breakdown(0.0)
        result = _apply_brand_signal_boost(
            breakdown,
            dimension="seo",
            serp_score=30.0,
            kg_score=25.0,
            wiki_score=25.0,
            ai_vis_score=20.0,
        )
        assert result.total_score <= 100.0


class TestCalculateDeterministicScoresWithBrandSignals:
    """Tests for calculate_deterministic_scores with brand_signals parameter."""

    def test_none_brand_signals_works_normally(self):
        result = calculate_deterministic_scores(brand_signals=None)
        assert "seo_score" in result
        assert "geo_score" in result
        assert "aeo_score" in result
        assert "overall_score" in result

    def test_empty_brand_signals_works_normally(self):
        result = calculate_deterministic_scores(brand_signals={})
        assert "seo_score" in result
        assert "overall_score" in result

    def test_brand_signals_with_data_boosts_scores(self):
        brand_signals = {
            "summary": {
                "signals_collected": 3,
                "brand_presence_score": 60.0,
                "score_components": {
                    "serp_presence": 25.0,
                    "knowledge_graph": 20.0,
                    "wikidata_presence": 15.0,
                    "ai_visibility": 12.0,
                },
            },
        }
        result = calculate_deterministic_scores(brand_signals=brand_signals)
        # At least one dimension should be boosted above the default near-zero
        assert result["seo_score"] > 0 or result["geo_score"] > 0 or result["aeo_score"] > 0

    def test_brand_signals_zero_collected_no_boost(self):
        brand_signals = {
            "summary": {
                "signals_collected": 0,
                "brand_presence_score": 0,
                "score_components": {},
            },
        }
        # Should behave same as no brand signals
        with_signals = calculate_deterministic_scores(brand_signals=brand_signals)
        without_signals = calculate_deterministic_scores(brand_signals=None)
        assert with_signals["seo_score"] == without_signals["seo_score"]
        assert with_signals["geo_score"] == without_signals["geo_score"]
        assert with_signals["aeo_score"] == without_signals["aeo_score"]
