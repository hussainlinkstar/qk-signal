# pyre-unsafe
"""AEX-05: Tests for brand name detection and GEO V3.1 sub-categories.

Verifies that:
- Brand name matching works with explicit brand_name parameter
- Brand name matching works via domain extraction fallback
- Common suffixes (Inc, LLC, Ltd) are stripped before matching
- GEO V3.1 sub-categories (content_citability, source_authority, entity_clarity) baseline correctly
- Brand_name flows through calculate_geo_score and calculate_deterministic_scores
"""

from score_utils import DeterministicScoringEngine, calculate_deterministic_scores

Engine = DeterministicScoringEngine


# ================================================================== #
#  1. Brand name matching helper (_match_brand_name)
# ================================================================== #


class TestBrandNameMatching:
    """Tests for _match_brand_name helper."""

    def test_no_brand_no_url_no_match(self):
        """With no brand name and no URL, nothing should match."""
        result = Engine._match_brand_name("Login Page", "", {})
        assert result == ""

    def test_generic_title_no_match(self):
        """Generic titles should not match even with a brand name."""
        result = Engine._match_brand_name("Login", "Acme Corp", {})
        assert result == ""

    def test_short_title_no_match(self):
        """Very short titles (< 3 chars) should not match."""
        result = Engine._match_brand_name("Hi", "Hi", {})
        assert result == ""

    def test_exact_brand_in_title(self):
        """Exact brand name in title should match."""
        result = Engine._match_brand_name("Acme Corp - Products", "Acme Corp", {})
        assert result == "Acme Corp"

    def test_brand_case_insensitive(self):
        """Brand matching should be case-insensitive."""
        result = Engine._match_brand_name("Welcome to ACME CORP", "Acme Corp", {})
        assert result == "Acme Corp"

    def test_brand_with_inc_suffix(self):
        """Inc suffix should be stripped before matching."""
        result = Engine._match_brand_name("Acme Products & Services", "Acme Inc.", {})
        assert result == "Acme"

    def test_brand_with_llc_suffix(self):
        """LLC suffix should be stripped before matching."""
        result = Engine._match_brand_name("Welcome to TechCo Solutions", "TechCo LLC", {})
        assert result == "TechCo"

    def test_brand_with_ltd_suffix(self):
        """Ltd suffix should be stripped before matching."""
        result = Engine._match_brand_name("Baker Industries Home", "Baker Industries Ltd", {})
        assert result == "Baker Industries"

    def test_brand_with_gmbh_suffix(self):
        """GmbH suffix should be stripped before matching."""
        result = Engine._match_brand_name("Müller Software - Home", "Müller Software GmbH", {})
        assert result == "Müller Software"

    def test_brand_not_in_title_no_match(self):
        """Brand name not in title should not match."""
        result = Engine._match_brand_name("Welcome to Our Site", "Acme Corp", {})
        assert result == ""

    def test_multi_word_brand_all_words_present(self):
        """Multi-word brand should match if all words appear."""
        result = Engine._match_brand_name(
            "The Big Data Solutions Platform", "Big Data Solutions", {}
        )
        assert result == "Big Data Solutions"

    def test_domain_fallback_match(self):
        """When no explicit brand, fall back to domain extraction."""
        result = Engine._match_brand_name(
            "Acme - Official Website",
            "",
            {"url": "https://www.acme.com/page"},
        )
        assert result == "acme"

    def test_domain_fallback_with_hyphen(self):
        """Domain with hyphens should be converted to spaces for matching."""
        result = Engine._match_brand_name(
            "Welcome to Acme Corp",
            "",
            {"url": "https://acme-corp.com"},
        )
        assert result == "acme corp"

    def test_domain_fallback_no_match(self):
        """Domain-derived brand not in title should not match."""
        result = Engine._match_brand_name(
            "Login Page",
            "",
            {"url": "https://www.acme.com"},
        )
        assert result == ""

    def test_empty_brand_name_string(self):
        """Empty/whitespace brand_name should not cause errors."""
        result = Engine._match_brand_name("Some Title", "  ", {})
        assert result == ""


# ================================================================== #
#  2. URL brand extraction helper (_extract_brand_from_url)
# ================================================================== #


class TestExtractBrandFromUrl:
    """Tests for _extract_brand_from_url helper."""

    def test_simple_domain(self):
        assert Engine._extract_brand_from_url("https://acme.com") == "acme"

    def test_www_stripped(self):
        assert Engine._extract_brand_from_url("https://www.acme.com") == "acme"

    def test_hyphenated_domain(self):
        assert Engine._extract_brand_from_url("https://acme-corp.com") == "acme corp"

    def test_with_path(self):
        assert Engine._extract_brand_from_url("https://acme.com/products/page") == "acme"

    def test_subdomain(self):
        result = Engine._extract_brand_from_url("https://blog.acme.com")
        assert result == "blog"  # Takes the first non-www/tld part

    def test_empty_url(self):
        assert Engine._extract_brand_from_url("") == ""

    def test_none_url(self):
        assert Engine._extract_brand_from_url(None) == ""

    def test_co_uk_domain(self):
        result = Engine._extract_brand_from_url("https://acme.co.uk")
        assert result == "acme"


# ================================================================== #
#  3. V3.1 GEO Sub-category Tests
# ================================================================== #


class TestContentCitabilityScoring:
    """Tests for _calculate_content_citability_score."""

    def test_empty_content_scores_zero(self):
        score = Engine._calculate_content_citability_score("", {}, [], [])
        assert score == 0.0

    def test_deep_content_with_headings(self):
        """Content with 800+ words and headings should score well."""
        content = "<h1>Main Title</h1>\n<h2>Section A</h2>\n<h2>Section B</h2>\n" + " ".join(
            ["word"] * 900
        )
        score = Engine._calculate_content_citability_score(content, {}, [], [])
        assert score >= 20  # depth bonus + heading bonus

    def test_qa_headings_boost(self):
        """Question-format headings should boost score."""
        content = (
            "## What is machine learning?\nML is defined as...\n## How does it work?\nIt refers to...\n## Why use it?\n"
            + " ".join(["word"] * 300)
        )
        score = Engine._calculate_content_citability_score(content, {}, [], [])
        assert score > 0

    def test_lists_and_tables_boost(self):
        """Structured content (lists/tables) should boost score."""
        content = "<h1>Guide</h1><ul><li>Item 1</li><li>Item 2</li></ul>" + " ".join(["word"] * 300)
        score = Engine._calculate_content_citability_score(content, {}, [], [])
        assert score > 0


class TestSourceAuthorityScoring:
    """Tests for _calculate_source_authority_score."""

    def test_empty_content_scores_zero(self):
        score = Engine._calculate_source_authority_score("", {}, [], [])
        assert score == 0.0

    def test_author_meta_gives_points(self):
        score = Engine._calculate_source_authority_score(
            "some text here", {"author": "Jane Doe"}, [], []
        )
        assert score >= 15

    def test_authoritative_links_boost(self):
        """Links to .gov, .edu, or research domains should boost score."""
        content = 'See <a href="https://www.gov.uk/guidance">gov.uk</a> and <a href="https://scholar.google.com/paper">scholar</a>'
        score = Engine._calculate_source_authority_score(content, {}, [], [])
        assert score >= 10

    def test_date_metadata_boosts(self):
        score = Engine._calculate_source_authority_score(
            "some content", {"publishedTime": "2024-03-15"}, [], []
        )
        assert score >= 15


class TestEntityClarityScoring:
    """Tests for _calculate_entity_clarity_score."""

    def test_no_schema_no_content_zero(self):
        score = Engine._calculate_entity_clarity_score({}, "", [], [])
        assert score == 0.0

    def test_faq_schema_gives_points(self):
        score = Engine._calculate_entity_clarity_score(
            {"detected_schema_types": ["FAQPage"]}, "", [], []
        )
        assert score >= 15

    def test_multiple_schemas_accumulate(self):
        schema = {"detected_schema_types": ["Organization", "Article", "FAQPage", "Person"]}
        score = Engine._calculate_entity_clarity_score(schema, "", [], [])
        assert score >= 40  # 20 + 15 + 15 + 10 = 60, capped at 60 for schema portion

    def test_entity_definitions_in_content(self):
        content = (
            "Machine Learning is defined as a subset of AI. NLP refers to language processing."
        )
        score = Engine._calculate_entity_clarity_score({}, content, [], [])
        assert score > 0


# ================================================================== #
#  4. Threading through calculate_geo_score
# ================================================================== #


class TestGeoScoreV31Threading:
    """Verify V3.1 sub-categories flow through calculate_geo_score."""

    def test_geo_score_returns_new_component_keys(self):
        """calculate_geo_score should return new V3.1 component keys."""
        result = Engine.calculate_geo_score(
            schema_analysis={"detected_schema_types": ["Organization", "Article"]},
            content="Machine Learning is defined as a subset of AI. Written by Dr. Smith.",
        )
        assert "entity_clarity" in result.components
        assert "content_citability" in result.components
        assert "source_authority" in result.components
        assert "brand_citation" in result.components
        # Old keys should NOT be present
        assert "napw_completeness" not in result.components
        assert "spatial_content" not in result.components
        assert "advanced_local_schema" not in result.components

    def test_geo_score_version_is_3_1(self):
        """Metadata should indicate V3.1."""
        result = Engine.calculate_geo_score(content="")
        assert result.metadata.get("version") == "3.1"

    def test_geo_score_with_schema_scores_higher(self):
        """Content with schema should score higher than empty content."""
        empty = Engine.calculate_geo_score(content="")
        with_schema = Engine.calculate_geo_score(
            schema_analysis={"detected_schema_types": ["Organization", "FAQPage", "Article"]},
            content="This is a comprehensive guide. Written by expert John Doe, Ph.D.",
        )
        assert with_schema.total_score > empty.total_score


# ================================================================== #
#  5. Threading through calculate_deterministic_scores
# ================================================================== #


class TestDeterministicScoresV31Threading:
    """Verify V3.1 scoring flows through the full scoring pipeline."""

    def test_geo_breakdown_uses_new_keys(self):
        """Full pipeline should produce geo_breakdown with V3.1 component keys."""
        scores = calculate_deterministic_scores(
            schema_analysis={"detected_schema_types": ["Organization"]},
            content="Some content here.",
        )
        geo_components = scores.get("geo_breakdown", {}).get("components", {})
        assert "entity_clarity" in geo_components or "content_citability" in geo_components

    def test_well_formed_content_boosts_geo(self):
        """Well-formed content with schema should produce higher GEO than empty."""
        empty = calculate_deterministic_scores(content="")
        rich = calculate_deterministic_scores(
            schema_analysis={"detected_schema_types": ["Organization", "FAQPage", "Article"]},
            content="Machine Learning is defined as a subset of AI. Written by Dr. Jane Smith. Published: 2024-03-15.",
        )
        assert rich["geo_score"] > empty["geo_score"]
