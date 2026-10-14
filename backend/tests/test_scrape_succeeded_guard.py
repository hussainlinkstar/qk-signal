"""Tests for the scrape_succeeded guard in deterministic scoring.

When scrape_succeeded=False, content-dependent sub-categories must be
zeroed (with zero-impact penalty) while schema/performance components
are still computed.  The top-level ``calculate_deterministic_scores``
auto-detects scrape_succeeded when the caller passes ``None``.
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from score_utils import DeterministicScoringEngine, calculate_deterministic_scores

Engine = DeterministicScoringEngine

# ── Fixtures ──────────────────────────────────────────────────────

_GOOD_PERF = {
    "lcp": 1.5,
    "fid": 50,
    "cls": 0.05,
    "ttfb": 200,
    "fcp": 1.0,
    "si": 2.0,
    "tbt": 100,
}

_GOOD_SCHEMA = {
    "detected_schema_types": ["LocalBusiness", "FAQPage"],
    "total_items": 5,
    "has_faq": True,
    "has_how_to": False,
    "has_local_business": True,
    "has_breadcrumb": True,
    "geo_types": ["LocalBusiness"],
    "coverage_percent": 50,
}

_GOOD_META = {
    "title": "Example Page",
    "description": "A well-optimised page.",
    "canonical": "https://example.com",
    "viewport": "width=device-width",
    "meta_description": "A well-optimised page.",
}


# ── SEO ───────────────────────────────────────────────────────────


class TestSEOScrapeGuard:
    def test_scrape_failed_zeroes_content_components(self):
        result = Engine.calculate_seo_score(
            performance_metrics=_GOOD_PERF,
            scrape_metadata=_GOOD_META,
            content="<html><body>Rich content</body></html>",
            scrape_succeeded=False,
        )
        for key in ("technical_seo", "onpage_content", "eeat_trust"):
            assert (
                result.components[key] == 0.0
            ), f"SEO component '{key}' should be 0.0 when scrape_succeeded=False"

    def test_scrape_failed_keeps_non_content_components(self):
        result = Engine.calculate_seo_score(
            performance_metrics=_GOOD_PERF,
            scrape_succeeded=False,
        )
        assert (
            result.components["core_web_vitals"] > 0
        ), "core_web_vitals should still be scored when scrape_succeeded=False"

    def test_scrape_failed_penalty_has_zero_impact(self):
        result = Engine.calculate_seo_score(scrape_succeeded=False)
        scrape_penalties = [
            p for p in result.penalties if "content-dependent SEO" in p.get("reason", "")
        ]
        assert len(scrape_penalties) == 1
        assert scrape_penalties[0]["impact"] == 0

    def test_scrape_succeeded_true_scores_content_components(self):
        result = Engine.calculate_seo_score(
            performance_metrics=_GOOD_PERF,
            scrape_metadata=_GOOD_META,
            content="<html><body>Rich well-optimised content with keywords</body></html>",
            scrape_succeeded=True,
        )
        scored = sum(
            1 for k in ("technical_seo", "onpage_content", "eeat_trust") if result.components[k] > 0
        )
        assert scored >= 1, (
            "At least one content-dependent SEO component should score > 0 "
            "when scrape_succeeded=True and content is present"
        )


# ── GEO ───────────────────────────────────────────────────────────


class TestGEOScrapeGuard:
    def test_scrape_failed_zeroes_content_components(self):
        result = Engine.calculate_geo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_metadata=_GOOD_META,
            content="<html><body>Local content</body></html>",
            brand_name="AcmeCorp",
            scrape_succeeded=False,
        )
        for key in ("content_citability", "source_authority", "brand_citation"):
            assert (
                result.components[key] == 0.0
            ), f"GEO component '{key}' should be 0.0 when scrape_succeeded=False"

    def test_scrape_failed_keeps_entity_clarity(self):
        result = Engine.calculate_geo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_succeeded=False,
        )
        assert (
            result.components["entity_clarity"] > 0
        ), "entity_clarity should still be scored when scrape_succeeded=False"

    def test_scrape_failed_penalty_has_zero_impact(self):
        result = Engine.calculate_geo_score(scrape_succeeded=False)
        scrape_penalties = [
            p for p in result.penalties if "content-dependent GEO" in p.get("reason", "")
        ]
        assert len(scrape_penalties) == 1
        assert scrape_penalties[0]["impact"] == 0

    def test_scrape_succeeded_true_scores_content_components(self):
        meta_with_lang = {
            **_GOOD_META,
            "title": "AcmeCorp - Local Business",
            "language": "en",
            "author": "John Doe",
        }
        result = Engine.calculate_geo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_metadata=meta_with_lang,
            content="<html><body><h1>AcmeCorp Guide</h1><h2>Overview</h2><p>AcmeCorp is defined as a local business in Springfield, IL. Written by John Doe. Published: 2024-01-15.</p></body></html>",
            brand_name="AcmeCorp",
            scrape_succeeded=True,
        )
        scored = sum(
            1
            for k in ("content_citability", "source_authority", "brand_citation")
            if result.components[k] > 0
        )
        assert scored >= 1, (
            "At least one content-dependent GEO component should score > 0 "
            "when scrape_succeeded=True"
        )


# ── AEO ───────────────────────────────────────────────────────────


class TestAEOScrapeGuard:
    def test_scrape_failed_zeroes_content_components(self):
        result = Engine.calculate_aeo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_metadata=_GOOD_META,
            content="<html><body>Structured FAQ content</body></html>",
            scrape_succeeded=False,
        )
        for key in ("semantic_entity_density", "information_gain", "snippet_formatting"):
            assert (
                result.components[key] == 0.0
            ), f"AEO component '{key}' should be 0.0 when scrape_succeeded=False"

    def test_scrape_failed_keeps_schema_component(self):
        result = Engine.calculate_aeo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_succeeded=False,
        )
        assert (
            result.components["llm_schema_readiness"] > 0
        ), "llm_schema_readiness should still be scored when scrape_succeeded=False"

    def test_scrape_failed_penalty_has_zero_impact(self):
        result = Engine.calculate_aeo_score(scrape_succeeded=False)
        scrape_penalties = [
            p for p in result.penalties if "content-dependent AEO" in p.get("reason", "")
        ]
        assert len(scrape_penalties) == 1
        assert scrape_penalties[0]["impact"] == 0

    def test_scrape_succeeded_true_scores_content_components(self):
        result = Engine.calculate_aeo_score(
            schema_analysis=_GOOD_SCHEMA,
            scrape_metadata=_GOOD_META,
            content="<html><body>Comprehensive FAQ answers and how-to guides</body></html>",
            scrape_succeeded=True,
        )
        scored = sum(
            1
            for k in ("semantic_entity_density", "information_gain", "snippet_formatting")
            if result.components[k] > 0
        )
        assert scored >= 1, (
            "At least one content-dependent AEO component should score > 0 "
            "when scrape_succeeded=True"
        )


# ── Auto-detection ────────────────────────────────────────────────


class TestScrapeSucceededAutoDetection:
    """Tests for the auto-detection in calculate_deterministic_scores
    when scrape_succeeded=None (default)."""

    def test_empty_content_no_meta_detects_false(self):
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is False

    def test_whitespace_only_content_no_meta_detects_false(self):
        result = calculate_deterministic_scores(
            content="   \n\t  ",
            scrape_metadata={},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is False

    def test_none_content_no_meta_detects_false(self):
        result = calculate_deterministic_scores(
            content=None,
            scrape_metadata=None,
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is False

    def test_non_empty_content_detects_true(self):
        result = calculate_deterministic_scores(
            content="<html><body>Some content</body></html>",
            scrape_metadata={},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is True

    def test_meta_title_triggers_true(self):
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={"title": "My Page"},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is True

    def test_meta_canonical_triggers_true(self):
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={"canonical": "https://example.com"},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is True

    def test_meta_viewport_triggers_true(self):
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={"viewport": "width=device-width"},
            scrape_succeeded=None,
        )
        assert result["scrape_succeeded"] is True

    def test_explicit_false_overrides_content(self):
        """Even with good content, explicit False forces scrape_succeeded=False."""
        result = calculate_deterministic_scores(
            content="<html><body>Rich page content</body></html>",
            scrape_metadata=_GOOD_META,
            scrape_succeeded=False,
        )
        assert result["scrape_succeeded"] is False

    def test_explicit_true_overrides_empty(self):
        """Even with empty content, explicit True forces scrape_succeeded=True."""
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={},
            scrape_succeeded=True,
        )
        assert result["scrape_succeeded"] is True
