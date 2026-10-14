"""Tests for page_type_detector service."""

from __future__ import annotations

from services.page_type_detector import (
    PAGE_TYPE_ABOUT,
    PAGE_TYPE_BLOG_ARTICLE,
    PAGE_TYPE_BLOG_INDEX,
    PAGE_TYPE_CAREERS,
    PAGE_TYPE_CHECKOUT,
    PAGE_TYPE_CONTACT,
    PAGE_TYPE_DOCUMENTATION,
    PAGE_TYPE_FAQ,
    PAGE_TYPE_GENERIC,
    PAGE_TYPE_HOMEPAGE,
    PAGE_TYPE_LOGIN,
    PAGE_TYPE_PRICING,
    PAGE_TYPE_PRIVACY,
    PAGE_TYPE_PRODUCT,
    PAGE_TYPE_PRODUCT_LISTING,
    PAGE_TYPE_SEARCH,
    PAGE_TYPE_SIGNUP,
    PAGE_TYPE_TERMS,
    build_site_structure_summary,
    detect_page_type,
    filter_irrelevant_suggestions,
    get_audit_hint,
    get_page_type_label,
    get_schema_expectations,
)


class TestDetectPageType:
    """URL-based detection tests."""

    def test_homepage_root(self):
        assert detect_page_type(url="https://example.com/") == PAGE_TYPE_HOMEPAGE

    def test_homepage_empty_path(self):
        assert detect_page_type(url="https://example.com") == PAGE_TYPE_HOMEPAGE

    def test_faq_page(self):
        assert detect_page_type(url="https://example.com/faq") == PAGE_TYPE_FAQ

    def test_faq_frequently_asked(self):
        assert detect_page_type(url="https://example.com/frequently-asked") == PAGE_TYPE_FAQ

    def test_terms_page(self):
        assert detect_page_type(url="https://example.com/terms") == PAGE_TYPE_TERMS

    def test_terms_of_service(self):
        assert detect_page_type(url="https://example.com/terms-of-service") == PAGE_TYPE_TERMS

    def test_privacy_page(self):
        assert detect_page_type(url="https://example.com/privacy") == PAGE_TYPE_PRIVACY

    def test_privacy_policy(self):
        assert detect_page_type(url="https://example.com/privacy-policy") == PAGE_TYPE_PRIVACY

    def test_contact_page(self):
        assert detect_page_type(url="https://example.com/contact") == PAGE_TYPE_CONTACT

    def test_contact_us(self):
        assert detect_page_type(url="https://example.com/contact-us") == PAGE_TYPE_CONTACT

    def test_about_page(self):
        assert detect_page_type(url="https://example.com/about") == PAGE_TYPE_ABOUT

    def test_about_us(self):
        assert detect_page_type(url="https://example.com/about-us") == PAGE_TYPE_ABOUT

    def test_pricing_page(self):
        assert detect_page_type(url="https://example.com/pricing") == PAGE_TYPE_PRICING

    def test_blog_index(self):
        assert detect_page_type(url="https://example.com/blog/") == PAGE_TYPE_BLOG_INDEX

    def test_blog_article(self):
        assert detect_page_type(url="https://example.com/blog/my-article") == PAGE_TYPE_BLOG_ARTICLE

    def test_product_page(self):
        assert detect_page_type(url="https://example.com/products/widget-pro") == PAGE_TYPE_PRODUCT

    def test_products_listing(self):
        assert detect_page_type(url="https://example.com/products/") == PAGE_TYPE_PRODUCT_LISTING

    def test_docs_page(self):
        assert (
            detect_page_type(url="https://example.com/docs/getting-started")
            == PAGE_TYPE_DOCUMENTATION
        )

    def test_careers_page(self):
        assert detect_page_type(url="https://example.com/careers") == PAGE_TYPE_CAREERS

    def test_login_page(self):
        assert detect_page_type(url="https://example.com/login") == PAGE_TYPE_LOGIN

    def test_signup_page(self):
        assert detect_page_type(url="https://example.com/signup") == PAGE_TYPE_SIGNUP

    def test_checkout_page(self):
        assert detect_page_type(url="https://example.com/checkout") == PAGE_TYPE_CHECKOUT

    def test_search_page(self):
        assert detect_page_type(url="https://example.com/search?q=test") == PAGE_TYPE_SEARCH

    def test_case_study(self):
        from services.page_type_detector import PAGE_TYPE_CASE_STUDY

        assert detect_page_type(url="https://example.com/case-studies/acme") == PAGE_TYPE_CASE_STUDY

    def test_generic_fallback(self):
        assert detect_page_type(url="https://example.com/some-random-page") == PAGE_TYPE_GENERIC

    def test_no_url_no_content(self):
        assert detect_page_type() == PAGE_TYPE_HOMEPAGE  # path="/"

    def test_none_url(self):
        assert detect_page_type(url=None) == PAGE_TYPE_HOMEPAGE


class TestContentBasedDetection:
    """Content/title heuristic tests."""

    def test_faq_content_with_questions(self):
        content = (
            "# Frequently Asked Questions\n"
            "## What is Qiko Signal?\n"
            "Qiko Signal is a GEO platform.\n"
            "## How does it work?\n"
            "It uses AI to audit sites.\n"
            "## Can I use it for free?\n"
            "Yes, we have a free tier.\n"
        )
        assert (
            detect_page_type(url="https://example.com/help-page", content=content) == PAGE_TYPE_FAQ
        )

    def test_privacy_content(self):
        content = (
            "Privacy Policy\n"
            "We collect personal data to provide our services. "
            "Information we gather includes your name and email."
        )
        result = detect_page_type(url="https://example.com/pages/info-notice", content=content)
        assert result == PAGE_TYPE_PRIVACY

    def test_terms_content(self):
        content = (
            "Terms of Service\n"
            "By using this service you agree to these terms. "
            "Limitation of liability applies."
        )
        result = detect_page_type(url="https://example.com/legal/usage", content=content)
        assert result == PAGE_TYPE_TERMS


class TestSchemaExpectations:
    """Schema expectations per page type."""

    def test_homepage_expects_organization(self):
        exp = get_schema_expectations(PAGE_TYPE_HOMEPAGE)
        assert "Organization" in exp["required_types"]
        assert "WebSite" in exp["required_types"]

    def test_faq_expects_faqpage(self):
        exp = get_schema_expectations(PAGE_TYPE_FAQ)
        assert "FAQPage" in exp["required_types"]

    def test_terms_expects_nothing(self):
        exp = get_schema_expectations(PAGE_TYPE_TERMS)
        assert exp["required_types"] == []
        assert exp["high_impact_types"] == []

    def test_privacy_expects_nothing(self):
        exp = get_schema_expectations(PAGE_TYPE_PRIVACY)
        assert exp["required_types"] == []
        assert exp["high_impact_types"] == []

    def test_product_expects_product(self):
        exp = get_schema_expectations(PAGE_TYPE_PRODUCT)
        assert "Product" in exp["required_types"]

    def test_blog_article_expects_article(self):
        exp = get_schema_expectations(PAGE_TYPE_BLOG_ARTICLE)
        assert "Article" in exp["required_types"]

    def test_login_expects_nothing(self):
        exp = get_schema_expectations(PAGE_TYPE_LOGIN)
        assert exp["required_types"] == []
        assert exp["high_impact_types"] == []


class TestAuditHints:
    """Audit hints provide relevant guidance."""

    def test_terms_hint_warns_against_faq_schema(self):
        hint = get_audit_hint(PAGE_TYPE_TERMS)
        assert "Do NOT recommend FAQ schema" in hint

    def test_privacy_hint_warns_against_faq_schema(self):
        hint = get_audit_hint(PAGE_TYPE_PRIVACY)
        assert "Do NOT recommend FAQ schema" in hint

    def test_homepage_hint_mentions_brand(self):
        hint = get_audit_hint(PAGE_TYPE_HOMEPAGE)
        assert "brand" in hint.lower() or "value proposition" in hint.lower()

    def test_generic_returns_hint(self):
        hint = get_audit_hint(PAGE_TYPE_GENERIC)
        assert len(hint) > 10


class TestPageTypeLabel:
    def test_known_type(self):
        label = get_page_type_label(PAGE_TYPE_FAQ)
        assert "FAQ" in label

    def test_unknown_type_returns_generic(self):
        label = get_page_type_label("nonexistent_type")
        assert "General" in label


class TestSiteStructureSummary:
    def test_empty_pages(self):
        assert build_site_structure_summary([]) == ""

    def test_builds_summary(self):
        pages = [
            {"url": "https://example.com/"},
            {"url": "https://example.com/about"},
            {"url": "https://example.com/faq"},
            {"url": "https://example.com/blog/post-1"},
            {"url": "https://example.com/terms"},
        ]
        summary = build_site_structure_summary(pages)
        assert "SITE STRUCTURE CONTEXT" in summary
        assert "5 known pages" in summary
        assert "FAQ" in summary
        assert "Do NOT recommend creating pages" in summary

    def test_explicit_page_types_used(self):
        pages = [
            {"url": "https://example.com/x", "page_type": "pricing"},
            {"url": "https://example.com/y", "page_type": "product"},
        ]
        summary = build_site_structure_summary(pages)
        assert "Pricing" in summary
        assert "Product" in summary


class TestFilterIrrelevantSuggestions:
    """Tests for the page-type-aware suggestion relevance filter."""

    def test_terms_page_drops_faq_schema(self):
        suggestions = [
            {"action": "Implement FAQPage schema for common questions"},
            {"action": "Improve heading hierarchy for legal readability"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_TERMS)
        assert len(result) == 1
        assert "heading hierarchy" in result[0]["action"]

    def test_terms_page_drops_product_schema(self):
        suggestions = [
            {"action": "Add Product schema markup for pricing tiers"},
            {"action": "Ensure proper crawlability of legal content"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_TERMS)
        assert len(result) == 1
        assert "crawlability" in result[0]["action"]

    def test_privacy_page_drops_howto_schema(self):
        suggestions = [
            {"action": "Implement HowTo schema for step-by-step guide"},
            {"action": "Add last-updated date to policy page"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_PRIVACY)
        assert len(result) == 1
        assert "last-updated" in result[0]["action"]

    def test_login_page_drops_article_schema(self):
        suggestions = [
            {"action": "Add Article schema to improve AI visibility"},
            {"action": "Ensure noindex directive is set"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_LOGIN)
        assert len(result) == 1
        assert "noindex" in result[0]["action"]

    def test_generic_page_keeps_all_suggestions(self):
        suggestions = [
            {"action": "Add FAQ schema"},
            {"action": "Add Product schema"},
            {"action": "Improve Core Web Vitals"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_GENERIC)
        assert len(result) == 3

    def test_homepage_keeps_all_suggestions(self):
        suggestions = [
            {"action": "Add FAQ schema for common questions"},
            {"action": "Implement Organization schema"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_HOMEPAGE)
        assert len(result) == 2

    def test_empty_suggestions_returns_empty(self):
        assert filter_irrelevant_suggestions([], PAGE_TYPE_TERMS) == []

    def test_contact_page_drops_product_schema(self):
        suggestions = [
            {"action": "Add Product schema for services"},
            {"action": "Implement LocalBusiness schema for contact info"},
        ]
        result = filter_irrelevant_suggestions(suggestions, PAGE_TYPE_CONTACT)
        assert len(result) == 1
        assert "LocalBusiness" in result[0]["action"]
