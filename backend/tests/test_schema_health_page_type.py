"""Tests for page-type-aware schema health analysis."""

from __future__ import annotations

from app.services.aeo.structure_service import analyze_json_ld_structure


class TestPageTypeAwareSchemaHealth:
    """Verify that schema health checks are page-type-aware."""

    MINIMAL_HTML = "<html><body><p>Hello</p></body></html>"
    HTML_WITH_FAQPAGE = (
        "<html><body>"
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"FAQPage","mainEntity":[]}'
        "</script>"
        "</body></html>"
    )

    def test_terms_page_no_missing_faqpage(self):
        """Terms pages should NOT be flagged for missing FAQPage."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="terms")
        assert "FAQPage" not in result["missing_required_types"]
        assert "FAQPage" not in result["missing_high_impact_types"]

    def test_privacy_page_no_missing_faqpage(self):
        """Privacy pages should NOT be flagged for missing FAQPage."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="privacy")
        assert "FAQPage" not in result["missing_required_types"]
        assert "Product" not in result["missing_required_types"]

    def test_faq_page_expects_faqpage(self):
        """FAQ pages SHOULD flag missing FAQPage."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="faq")
        assert "FAQPage" in result["missing_required_types"]

    def test_faq_page_has_faqpage(self):
        """FAQ pages with FAQPage present should not flag it as missing."""
        result = analyze_json_ld_structure(self.HTML_WITH_FAQPAGE, page_type="faq")
        assert "FAQPage" not in result["missing_required_types"]
        assert "FAQPage" in result["detected_schema_types"]

    def test_homepage_expects_organization(self):
        """Homepage should flag missing Organization."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="homepage")
        assert "Organization" in result["missing_required_types"]
        assert "WebSite" in result["missing_required_types"]

    def test_login_page_no_requirements(self):
        """Login pages should have zero schema requirements."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="login")
        assert result["missing_required_types"] == []
        assert result["missing_high_impact_types"] == []
        assert result["coverage_percent"] == 100.0

    def test_product_page_expects_product(self):
        """Product pages should flag missing Product schema."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="product")
        assert "Product" in result["missing_required_types"]

    def test_blog_article_expects_article(self):
        """Blog articles should flag missing Article schema."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, page_type="blog_article")
        assert "Article" in result["missing_required_types"]

    def test_legacy_mode_still_works(self):
        """Without page_type, legacy site_category mode should work."""
        result = analyze_json_ld_structure(self.MINIMAL_HTML, site_category="generic")
        # Legacy generic template requires FAQPage, HowTo, Product
        assert "FAQPage" in result["missing_required_types"]
        assert "HowTo" in result["missing_required_types"]
        assert "Product" in result["missing_required_types"]

    def test_page_type_overrides_category(self):
        """When page_type is provided, it should override site_category."""
        result = analyze_json_ld_structure(
            self.MINIMAL_HTML,
            site_category="generic",
            page_type="terms",
        )
        # page_type=terms should yield no requirements even when site_category=generic
        assert result["missing_required_types"] == []
