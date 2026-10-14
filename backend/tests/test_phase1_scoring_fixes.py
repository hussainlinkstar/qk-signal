"""Tests for Phase 1 scoring fixes:

1. Hreflang no longer triggers from substring in content (false positive guard)
2. Sitemap no longer triggers from substring in content (false positive guard)
3. GEO sub-categories do not duplicate hreflang checks
4. Security headers check uses response_headers from network dict
5. Share token endpoint — POST creates token, GET validates token
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from score_utils import DeterministicScoringEngine, calculate_deterministic_scores

Engine = DeterministicScoringEngine


# ================================================================== #
#  Hreflang False-Positive Guard
# ================================================================== #


class TestHreflangFalsePositiveGuard:
    """Hreflang bonus must NOT fire from content mentioning 'hreflang'."""

    def test_hreflang_in_content_does_not_trigger_bonus(self):
        """A blog post discussing hreflang should not get the bonus."""
        penalties, bonuses = [], []
        Engine._calculate_technical_seo_score(
            meta={},
            content="Learn about hreflang tags for international SEO",
            penalties=penalties,
            bonuses=bonuses,
        )
        hreflang_bonuses = [b for b in bonuses if "hreflang" in b["reason"].lower()]
        assert (
            len(hreflang_bonuses) == 0
        ), f"Hreflang bonus should not fire from content, got {hreflang_bonuses}"

    def test_hreflang_in_meta_triggers_bonus(self):
        """When scraper provides hreflang metadata, the bonus should fire."""
        penalties, bonuses = [], []
        Engine._calculate_technical_seo_score(
            meta={"hreflang": "en"},
            content="",
            penalties=penalties,
            bonuses=bonuses,
        )
        hreflang_bonuses = [b for b in bonuses if "hreflang" in b["reason"].lower()]
        assert (
            len(hreflang_bonuses) == 1
        ), f"Hreflang bonus should fire from meta, got {hreflang_bonuses}"

    def test_no_hreflang_in_geo_subcategories(self):
        """GEO sub-category scores must NOT include hreflang checks (belongs in technical_seo)."""
        for fn_name in ("_calculate_content_citability_score", "_calculate_source_authority_score"):
            penalties, bonuses = [], []
            fn = getattr(Engine, fn_name)
            fn(
                "Learn about hreflang tags for international SEO",
                {"hreflang": "en"},
                penalties,
                bonuses,
            )
            hreflang_bonuses = [b for b in bonuses if "hreflang" in b["reason"].lower()]
            assert (
                len(hreflang_bonuses) == 0
            ), f"{fn_name} must NOT have hreflang bonus (it belongs in technical_seo), got {hreflang_bonuses}"


# ================================================================== #
#  Sitemap False-Positive Guard
# ================================================================== #


class TestSitemapFalsePositiveGuard:
    """Sitemap bonus must NOT fire from content mentioning 'sitemap'."""

    def test_sitemap_in_content_does_not_trigger_bonus(self):
        """An article about sitemaps should not get the bonus."""
        penalties, bonuses = [], []
        Engine._calculate_technical_seo_score(
            meta={},
            content="How to create a sitemap for your website",
            penalties=penalties,
            bonuses=bonuses,
        )
        sitemap_bonuses = [b for b in bonuses if "sitemap" in b["reason"].lower()]
        assert (
            len(sitemap_bonuses) == 0
        ), f"Sitemap bonus should not fire from content, got {sitemap_bonuses}"

    def test_sitemap_in_meta_triggers_bonus(self):
        """When scraper provides sitemap metadata, the bonus should fire."""
        penalties, bonuses = [], []
        Engine._calculate_technical_seo_score(
            meta={"sitemap": "https://example.com/sitemap.xml"},
            content="",
            penalties=penalties,
            bonuses=bonuses,
        )
        sitemap_bonuses = [b for b in bonuses if "sitemap" in b["reason"].lower()]
        assert (
            len(sitemap_bonuses) == 1
        ), f"Sitemap bonus should fire from meta, got {sitemap_bonuses}"


# ================================================================== #
#  Security Headers — Response Headers
# ================================================================== #


class TestSecurityHeadersFromResponseHeaders:
    """Security headers bonus must use actual HTTP response headers, not content."""

    def test_content_mentioning_csp_does_not_trigger_bonus(self):
        """A page discussing content-security-policy should not get the bonus."""
        penalties, bonuses = [], []
        Engine._calculate_security_accessibility_score(
            meta={"url": "https://example.com"},
            network={},
            content="Learn about content-security-policy and x-frame-options for security",
            penalties=penalties,
            bonuses=bonuses,
        )
        sec_bonuses = [b for b in bonuses if "security header" in b["reason"].lower()]
        assert (
            len(sec_bonuses) == 0
        ), f"Security headers bonus should not fire from content, got {sec_bonuses}"

    def test_response_headers_with_csp_triggers_bonus(self):
        """When response_headers contain CSP, the bonus should fire."""
        penalties, bonuses = [], []
        Engine._calculate_security_accessibility_score(
            meta={"url": "https://example.com"},
            network={
                "response_headers": {
                    "Content-Security-Policy": "default-src 'self'",
                    "X-Frame-Options": "DENY",
                }
            },
            content="",
            penalties=penalties,
            bonuses=bonuses,
        )
        sec_bonuses = [b for b in bonuses if "security header" in b["reason"].lower()]
        assert (
            len(sec_bonuses) == 1
        ), f"Security headers bonus should fire from response headers, got {sec_bonuses}"

    def test_response_headers_with_hsts_triggers_bonus(self):
        """HSTS in response headers should also trigger the bonus."""
        penalties, bonuses = [], []
        Engine._calculate_security_accessibility_score(
            meta={"url": "https://example.com"},
            network={
                "response_headers": {
                    "strict-transport-security": "max-age=31536000",
                }
            },
            content="",
            penalties=penalties,
            bonuses=bonuses,
        )
        sec_bonuses = [b for b in bonuses if "security header" in b["reason"].lower()]
        assert len(sec_bonuses) == 1

    def test_empty_response_headers_no_bonus(self):
        """Empty response_headers dict should not trigger the bonus."""
        penalties, bonuses = [], []
        Engine._calculate_security_accessibility_score(
            meta={"url": "https://example.com"},
            network={"response_headers": {}},
            content="",
            penalties=penalties,
            bonuses=bonuses,
        )
        sec_bonuses = [b for b in bonuses if "security header" in b["reason"].lower()]
        assert len(sec_bonuses) == 0


# ================================================================== #
#  Integration — calculate_deterministic_scores
# ================================================================== #


class TestDeterministicScoresIntegration:
    """Integration test: false-positive guards work through the top-level API."""

    def test_content_about_seo_techniques_no_false_positives(self):
        """A blog about SEO should not get sitemap/hreflang bonuses from content."""
        result = calculate_deterministic_scores(
            content="How to create a sitemap and configure hreflang tags for your website. "
            "Use content-security-policy headers for better security.",
            scrape_metadata={"title": "SEO Guide", "url": "https://example.com/blog/seo"},
        )
        seo_bonuses = result.get("seo_breakdown", {}).get("bonuses", [])
        sitemap_bonuses = [b for b in seo_bonuses if "sitemap" in b.get("reason", "").lower()]
        hreflang_bonuses = [b for b in seo_bonuses if "hreflang" in b.get("reason", "").lower()]
        assert len(sitemap_bonuses) == 0, f"Sitemap false positive: {sitemap_bonuses}"
        assert len(hreflang_bonuses) == 0, f"Hreflang false positive: {hreflang_bonuses}"

    def test_security_headers_via_network_data(self):
        """Security headers bonus should fire when response_headers are in network_data."""
        result = calculate_deterministic_scores(
            content="",
            scrape_metadata={"title": "Test", "url": "https://example.com"},
            network_data={
                "response_headers": {
                    "Content-Security-Policy": "default-src 'self'",
                },
            },
        )
        seo_bonuses = result.get("seo_breakdown", {}).get("bonuses", [])
        sec_bonuses = [b for b in seo_bonuses if "security header" in b.get("reason", "").lower()]
        assert len(sec_bonuses) == 1, f"Security headers bonus should fire: {sec_bonuses}"
