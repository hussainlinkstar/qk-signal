"""Tests for backend.services.visibility_scoring module."""

from services.visibility_scoring import (
    ScoreResult,
    matches_target_domain,
    normalize_domain,
    score_response,
)


# ── normalize_domain ──────────────────────────────────────────────────────


class TestNormalizeDomain:
    def test_bare_domain(self):
        assert normalize_domain("example.com") == "example.com"

    def test_strips_www(self):
        assert normalize_domain("www.example.com") == "example.com"

    def test_full_url(self):
        assert normalize_domain("https://www.example.com/page?q=1") == "example.com"

    def test_uppercase(self):
        assert normalize_domain("EXAMPLE.COM") == "example.com"

    def test_trailing_dot(self):
        assert normalize_domain("example.com.") == "example.com"

    def test_none_returns_none(self):
        assert normalize_domain(None) is None

    def test_empty_returns_none(self):
        assert normalize_domain("") is None

    def test_whitespace_only_returns_none(self):
        assert normalize_domain("   ") is None

    def test_http_scheme(self):
        assert normalize_domain("http://blog.example.com") == "blog.example.com"


# ── matches_target_domain ─────────────────────────────────────────────────


class TestMatchesTargetDomain:
    def test_exact_match(self):
        assert matches_target_domain("https://example.com/page", "example.com") is True

    def test_subdomain_match(self):
        assert matches_target_domain("https://blog.example.com", "example.com") is True

    def test_different_domain(self):
        assert matches_target_domain("https://other.com", "example.com") is False

    def test_none_target(self):
        assert matches_target_domain("https://example.com", None) is False

    def test_empty_target(self):
        assert matches_target_domain("https://example.com", "") is False

    def test_www_in_citation(self):
        assert matches_target_domain("https://www.example.com/path", "example.com") is True

    def test_www_in_target(self):
        assert matches_target_domain("https://example.com/path", "www.example.com") is True

    def test_partial_domain_no_false_positive(self):
        assert matches_target_domain("https://notexample.com", "example.com") is False

    def test_bare_domain_string_citation(self):
        """Fallback: domain substring check on bare citation text."""
        assert matches_target_domain("example.com", "example.com") is True


# ── score_response: citation_presence factor ──────────────────────────────


class TestCitationPresenceFactor:
    def test_no_citations_yields_zero(self):
        result = score_response("query", "Some text.", [], target_domain="example.com")
        assert result.breakdown["citation_presence"] == 0.0

    def test_single_matching_citation(self):
        result = score_response(
            "query", "Text.", ["https://example.com/page"], target_domain="example.com"
        )
        assert result.breakdown["citation_presence"] == 33.0  # 30 + 1*3

    def test_multiple_matching_citations(self):
        result = score_response(
            "query",
            "Text.",
            ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            target_domain="example.com",
        )
        assert result.breakdown["citation_presence"] == 39.0  # 30 + min(10, 3*3)

    def test_cap_at_40(self):
        many = [f"https://example.com/{i}" for i in range(10)]
        result = score_response("query", "Text.", many, target_domain="example.com")
        assert result.breakdown["citation_presence"] == 40.0  # 30 + min(10, 30)

    def test_unrelated_citation_yields_zero(self):
        result = score_response(
            "query", "Text.", ["https://other.com/page"], target_domain="example.com"
        )
        assert result.breakdown["citation_presence"] == 0.0


# ── score_response: citation_position factor ──────────────────────────────


class TestCitationPositionFactor:
    def test_first_position(self):
        result = score_response(
            "query",
            "Text.",
            ["https://example.com/page", "https://other.com"],
            target_domain="example.com",
        )
        assert result.breakdown["citation_position"] == 20.0  # idx 0 → 20 - 0*5

    def test_second_position(self):
        result = score_response(
            "query",
            "Text.",
            ["https://other.com", "https://example.com/page"],
            target_domain="example.com",
        )
        assert result.breakdown["citation_position"] == 15.0  # idx 1 → 20 - 1*5

    def test_fifth_position_is_zero(self):
        citations = [f"https://other{i}.com" for i in range(4)]
        citations.append("https://example.com")
        result = score_response("query", "Text.", citations, target_domain="example.com")
        assert result.breakdown["citation_position"] == 0.0  # idx 4 → 20 - 4*5 = 0

    def test_no_citations_zero(self):
        result = score_response("query", "Text.", [], target_domain="example.com")
        assert result.breakdown["citation_position"] == 0.0


# ── score_response: text_mention factor ───────────────────────────────────


class TestTextMentionFactor:
    def test_no_mention(self):
        result = score_response("query", "No domain here.", [], target_domain="example.com")
        assert result.breakdown["text_mention"] == 0.0

    def test_single_mention_late(self):
        """Domain appears once, past the 20% mark of text."""
        padding = "x " * 500
        text = padding + "Visit example.com for more."
        result = score_response("query", text, [], target_domain="example.com")
        assert result.breakdown["text_mention"] == 10.0  # base only

    def test_mention_early(self):
        """Domain appears early (<20% of text length)."""
        text = "example.com is the best tool. " + ("x " * 200)
        result = score_response("query", text, [], target_domain="example.com")
        assert result.breakdown["text_mention"] >= 15.0  # 10 base + 5 early

    def test_multiple_mentions(self):
        text = "example.com is great. Visit example.com or example.com."
        result = score_response("query", text, [], target_domain="example.com")
        # 10 (present) + 5 (early) + min(5, 2*2=4) = 19
        assert result.breakdown["text_mention"] == 19.0


# ── score_response: topic_relevance factor ────────────────────────────────


class TestTopicRelevanceFactor:
    def test_no_topic_match(self):
        result = score_response("acme review", "Nothing related.", [], target_domain="example.com")
        assert result.breakdown["topic_relevance"] == 0.0

    def test_topic_present_late(self):
        padding = "x " * 500
        text = padding + "Check out the acme review."
        result = score_response("acme review", text, [], target_domain="example.com")
        assert result.breakdown["topic_relevance"] == 10.0  # base only

    def test_topic_early(self):
        text = "acme review guide " + ("x " * 200)
        result = score_response("acme review", text, [], target_domain="example.com")
        assert result.breakdown["topic_relevance"] >= 15.0

    def test_recommendation_keyword_nearby(self):
        text = "This is the best acme review out there."
        result = score_response("acme review", text, [], target_domain="example.com")
        # 10 (present) + 0 (not early, position > 30%) + 5 (recommend) = 15
        assert result.breakdown["topic_relevance"] == 15.0

    def test_recommendation_keyword_nearby_and_early(self):
        text = "acme review is best recommended. " + ("x " * 200)
        result = score_response("acme review", text, [], target_domain="example.com")
        # 10 (present) + 5 (early) + 5 (recommend) = 20
        assert result.breakdown["topic_relevance"] == 20.0


# ── score_response: end-to-end scenarios ──────────────────────────────────


class TestScoreResponseEndToEnd:
    def test_perfect_score(self):
        """All factors maxed out."""
        topic = "best seo tool"
        domain = "example.com"
        text = (
            "example.com is the best seo tool and the recommended leading choice. "
            "Visit example.com, example.com, example.com."
        )
        citations = [f"https://example.com/{i}" for i in range(5)]
        result = score_response(topic, text, citations, target_domain=domain)
        assert result.score == 100.0

    def test_zero_score(self):
        result = score_response("query", "Unrelated content.", ["https://other.com"])
        assert result.score == 0.0
        assert all(v == 0.0 for v in result.breakdown.values())

    def test_returns_score_result(self):
        result = score_response("query", "Text.", [])
        assert isinstance(result, ScoreResult)
        assert isinstance(result.score, float)
        assert isinstance(result.breakdown, dict)
        assert set(result.breakdown.keys()) == {
            "citation_presence",
            "citation_position",
            "text_mention",
            "topic_relevance",
        }

    def test_score_never_exceeds_100(self):
        """Even with all factors overflowing, score is capped at 100."""
        topic = "best seo"
        domain = "example.com"
        text = "example.com best seo recommended leading top ideal excellent " * 50
        citations = [f"https://example.com/{i}" for i in range(20)]
        result = score_response(topic, text, citations, target_domain=domain)
        assert result.score <= 100.0

    def test_no_target_domain_falls_back_to_topic_in_citations(self):
        """Without a target domain, citation matching uses topic substring."""
        result = score_response(
            "acme", "Some text.", ["https://acme.com/page", "https://other.com"]
        )
        assert result.breakdown["citation_presence"] > 0.0

    def test_empty_text(self):
        result = score_response("query", "", ["https://example.com"], target_domain="example.com")
        assert isinstance(result.score, float)
        assert result.breakdown["text_mention"] == 0.0
        assert result.breakdown["topic_relevance"] == 0.0
