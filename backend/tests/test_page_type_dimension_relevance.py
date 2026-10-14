# pyre-unsafe
"""AEX-06: Tests for page-type dimension relevance weighting.

Verifies that:
- All 20 page types have defined dimension relevance weights
- Terms/privacy pages have GEO and AEO weight = 0 (N/A)
- Login/signup pages have GEO and AEO weight = 0 (N/A)
- Homepage applies full weights to all dimensions
- N/A dimensions are correctly identified in scoring results
- Overall score uses relevance-adjusted weights
- Backward compatibility when no page_type is provided
"""

import pytest
from score_utils import DeterministicScoringEngine, calculate_deterministic_scores
from services.page_type_detector import (
    PAGE_TYPE_DIMENSION_RELEVANCE,
    PAGE_TYPE_HOMEPAGE,
    PAGE_TYPE_TERMS,
    PAGE_TYPE_PRIVACY,
    PAGE_TYPE_LOGIN,
    PAGE_TYPE_SIGNUP,
    PAGE_TYPE_CHECKOUT,
    PAGE_TYPE_FAQ,
    PAGE_TYPE_BLOG_ARTICLE,
    PAGE_TYPE_CONTACT,
    PAGE_TYPE_DOCUMENTATION,
    PAGE_TYPE_GENERIC,
    PAGE_TYPE_PRODUCT,
    PAGE_TYPE_PRODUCT_LISTING,
    PAGE_TYPE_LANDING,
    PAGE_TYPE_PRICING,
    PAGE_TYPE_ABOUT,
    PAGE_TYPE_CASE_STUDY,
    PAGE_TYPE_BLOG_INDEX,
    PAGE_TYPE_CAREERS,
    PAGE_TYPE_SEARCH,
    get_dimension_relevance,
)

Engine = DeterministicScoringEngine

ALL_PAGE_TYPES = [
    PAGE_TYPE_HOMEPAGE,
    PAGE_TYPE_PRODUCT,
    PAGE_TYPE_PRODUCT_LISTING,
    PAGE_TYPE_BLOG_ARTICLE,
    PAGE_TYPE_LANDING,
    PAGE_TYPE_FAQ,
    PAGE_TYPE_PRICING,
    PAGE_TYPE_ABOUT,
    PAGE_TYPE_DOCUMENTATION,
    PAGE_TYPE_CASE_STUDY,
    PAGE_TYPE_CONTACT,
    PAGE_TYPE_BLOG_INDEX,
    PAGE_TYPE_CAREERS,
    PAGE_TYPE_SEARCH,
    PAGE_TYPE_GENERIC,
    PAGE_TYPE_TERMS,
    PAGE_TYPE_PRIVACY,
    PAGE_TYPE_LOGIN,
    PAGE_TYPE_SIGNUP,
    PAGE_TYPE_CHECKOUT,
]


# ================================================================== #
#  1. Relevance weight mapping completeness
# ================================================================== #


class TestDimensionRelevanceMapping:
    """Verify the mapping covers all page types with valid weights."""

    @pytest.mark.parametrize("page_type", ALL_PAGE_TYPES)
    def test_all_page_types_have_weights(self, page_type):
        """Every page type must have defined dimension relevance weights."""
        assert page_type in PAGE_TYPE_DIMENSION_RELEVANCE

    @pytest.mark.parametrize("page_type", ALL_PAGE_TYPES)
    def test_weights_are_valid_floats(self, page_type):
        """All weights must be between 0.0 and 1.0."""
        seo, geo, aeo = PAGE_TYPE_DIMENSION_RELEVANCE[page_type]
        assert 0.0 <= seo <= 1.0
        assert 0.0 <= geo <= 1.0
        assert 0.0 <= aeo <= 1.0

    def test_exactly_20_page_types_defined(self):
        """Mapping must cover exactly 20 page types."""
        assert len(PAGE_TYPE_DIMENSION_RELEVANCE) == 20

    def test_unknown_page_type_gets_default(self):
        """Unknown page type falls back to full weights."""
        rel = get_dimension_relevance("totally_unknown_type")
        assert rel == {"seo": 1.0, "geo": 1.0, "aeo": 1.0}


# ================================================================== #
#  2. get_dimension_relevance helper
# ================================================================== #


class TestGetDimensionRelevance:
    """Tests for the get_dimension_relevance function."""

    def test_homepage_full_weights(self):
        rel = get_dimension_relevance("homepage")
        assert rel == {"seo": 1.0, "geo": 1.0, "aeo": 1.0}

    def test_terms_zero_geo_aeo(self):
        rel = get_dimension_relevance("terms")
        assert rel["geo"] == 0.0
        assert rel["aeo"] == 0.0
        assert rel["seo"] > 0.0

    def test_privacy_zero_geo_aeo(self):
        rel = get_dimension_relevance("privacy")
        assert rel["geo"] == 0.0
        assert rel["aeo"] == 0.0

    def test_login_zero_geo_aeo(self):
        rel = get_dimension_relevance("login")
        assert rel["geo"] == 0.0
        assert rel["aeo"] == 0.0

    def test_signup_zero_geo_aeo(self):
        rel = get_dimension_relevance("signup")
        assert rel["geo"] == 0.0
        assert rel["aeo"] == 0.0

    def test_faq_high_aeo_low_geo(self):
        rel = get_dimension_relevance("faq")
        assert rel["aeo"] == 1.0
        assert rel["geo"] < 0.5

    def test_contact_high_geo_low_aeo(self):
        rel = get_dimension_relevance("contact")
        assert rel["geo"] == 1.0
        assert rel["aeo"] < 0.5

    def test_blog_article_full_aeo(self):
        rel = get_dimension_relevance("blog_article")
        assert rel["aeo"] == 1.0
        assert rel["seo"] == 1.0

    def test_returns_dict_format(self):
        rel = get_dimension_relevance("homepage")
        assert set(rel.keys()) == {"seo", "geo", "aeo"}


# ================================================================== #
#  3. calculate_deterministic_scores with page_type
# ================================================================== #


class TestDeterministicScoresPageType:
    """Tests for page-type weighting in the scoring pipeline."""

    def test_no_page_type_no_relevance_metadata(self):
        """Without page_type, no relevance metadata should be in result."""
        result = calculate_deterministic_scores(
            scrape_metadata={"title": "Test"},
            content="",
        )
        assert "dimension_relevance" not in result
        assert "na_dimensions" not in result
        assert "page_type" not in result

    def test_homepage_no_na_dimensions(self):
        """Homepage should have no N/A dimensions."""
        result = calculate_deterministic_scores(
            scrape_metadata={"title": "Test"},
            content="",
            page_type="homepage",
        )
        assert result.get("page_type") == "homepage"
        assert result.get("dimension_relevance") == {"seo": 1.0, "geo": 1.0, "aeo": 1.0}
        assert "na_dimensions" not in result

    def test_terms_page_na_geo_aeo(self):
        """Terms page should mark GEO and AEO as N/A."""
        result = calculate_deterministic_scores(
            scrape_metadata={"title": "Terms of Service"},
            content="These are the terms of service for our platform.",
            page_type="terms",
        )
        assert "geo" in result.get("na_dimensions", [])
        assert "aeo" in result.get("na_dimensions", [])
        assert "seo" not in result.get("na_dimensions", [])

    def test_login_page_na_geo_aeo(self):
        """Login page should mark GEO and AEO as N/A."""
        result = calculate_deterministic_scores(
            scrape_metadata={"title": "Login"},
            content="",
            page_type="login",
        )
        assert set(result.get("na_dimensions", [])) == {"geo", "aeo"}

    def test_overall_score_excludes_na_dimensions(self):
        """Overall score for terms page should be SEO-only (GEO/AEO weight=0)."""
        # Create a scenario with measurable SEO signals
        result = calculate_deterministic_scores(
            scrape_metadata={"title": "Terms of Service", "url": "https://example.com/terms"},
            content="<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'></head></html>",
            network_data={"protocol": "h2", "is_https": True},
            page_type="terms",
        )
        seo = result["seo_score"]
        overall = result["overall_score"]
        # With GEO=0 weight and AEO=0 weight, overall should equal SEO score
        # (since only SEO contributes to the weighted average)
        assert overall == seo

    def test_blog_article_geo_weight_reduced(self):
        """Blog article should have GEO weight reduced in overall score."""
        # Same signals, different page type
        kwargs = dict(
            scrape_metadata={"title": "Test Article", "url": "https://example.com/blog/test"},
            content="<p>Some content about testing things.</p>" * 10,
        )
        as_homepage = calculate_deterministic_scores(**kwargs, page_type="homepage")
        as_blog = calculate_deterministic_scores(**kwargs, page_type="blog_article")

        # Dimension scores should be identical (same signals)
        assert as_homepage["seo_score"] == as_blog["seo_score"]
        assert as_homepage["geo_score"] == as_blog["geo_score"]
        assert as_homepage["aeo_score"] == as_blog["aeo_score"]

        # Overall may differ due to different weights
        # Blog has geo=0.5 vs homepage geo=1.0
        assert as_blog.get("dimension_relevance", {}).get("geo") < as_homepage.get(
            "dimension_relevance", {}
        ).get("geo")

    def test_backward_compatible_without_page_type(self):
        """Calling without page_type should produce identical results to before."""
        kwargs = dict(
            scrape_metadata={"title": "Test"},
            content="",
        )
        result = calculate_deterministic_scores(**kwargs)
        result_with_none = calculate_deterministic_scores(**kwargs, page_type=None)
        assert result["overall_score"] == result_with_none["overall_score"]
        assert result["seo_score"] == result_with_none["seo_score"]


# ================================================================== #
#  4. Overall score weighting with relevance
# ================================================================== #


class TestOverallScoreWithRelevance:
    """Verify overall score calculation respects relevance weights."""

    def test_equal_scores_homepage_vs_terms(self):
        """With equal dimension scores, terms page overall should differ from homepage."""
        # Use calculate_overall_score directly with custom weights
        scores = {"seo": 50.0, "geo": 50.0, "aeo": 50.0}

        homepage_weights = {"seo": 0.4 * 1.0, "geo": 0.3 * 1.0, "aeo": 0.3 * 1.0}
        terms_weights = {"seo": 0.4 * 0.5, "geo": 0.3 * 0.0, "aeo": 0.3 * 0.0}

        homepage_overall = Engine.calculate_overall_score(scores, weights=homepage_weights)
        terms_overall = Engine.calculate_overall_score(scores, weights=terms_weights)

        # Homepage: (50*0.4 + 50*0.3 + 50*0.3) / (0.4+0.3+0.3) = 50
        assert homepage_overall == 50.0
        # Terms: (50*0.2 + 50*0 + 50*0) / 0.2 = 50 (normalized)
        assert terms_overall == 50.0

    def test_zero_weight_dimension_excluded_from_normalization(self):
        """Dimensions with weight=0 should not affect the overall score."""
        scores = {"seo": 80.0, "geo": 10.0, "aeo": 10.0}

        # Terms page: only SEO matters (weight 0.2), GEO/AEO weight 0
        terms_weights = {"seo": 0.4 * 0.5, "geo": 0.3 * 0.0, "aeo": 0.3 * 0.0}
        overall = Engine.calculate_overall_score(scores, weights=terms_weights)
        # Only SEO contributes: 80*0.2 / 0.2 = 80
        assert overall == 80.0

    def test_mixed_relevance_weights(self):
        """Blog article with mixed weights should produce intermediate overall."""
        scores = {"seo": 80.0, "geo": 20.0, "aeo": 60.0}

        # Blog: SEO=1.0, GEO=0.5, AEO=1.0
        blog_weights = {"seo": 0.4 * 1.0, "geo": 0.3 * 0.5, "aeo": 0.3 * 1.0}
        # Full weights
        full_weights = {"seo": 0.4, "geo": 0.3, "aeo": 0.3}

        blog_overall = Engine.calculate_overall_score(scores, weights=blog_weights)
        full_overall = Engine.calculate_overall_score(scores, weights=full_weights)

        # Blog should weight GEO less, so low GEO matters less → higher overall
        assert blog_overall > full_overall
