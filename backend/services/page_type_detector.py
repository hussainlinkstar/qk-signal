"""Page-type detection utility.

Classifies a page by its URL path and (optionally) its content so that
downstream audit steps, schema-health checks, AI prompt construction,
recommendation filtering, can be page-type-aware.

Supported page types
--------------------
homepage, faq, terms, privacy, contact, about, pricing, blog_index,
blog_article, product, product_listing, documentation, case_study,
careers, login, signup, checkout, search, landing, generic
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Page-type constants
# ---------------------------------------------------------------------------
PAGE_TYPE_HOMEPAGE = "homepage"
PAGE_TYPE_FAQ = "faq"
PAGE_TYPE_TERMS = "terms"
PAGE_TYPE_PRIVACY = "privacy"
PAGE_TYPE_CONTACT = "contact"
PAGE_TYPE_ABOUT = "about"
PAGE_TYPE_PRICING = "pricing"
PAGE_TYPE_BLOG_INDEX = "blog_index"
PAGE_TYPE_BLOG_ARTICLE = "blog_article"
PAGE_TYPE_PRODUCT = "product"
PAGE_TYPE_PRODUCT_LISTING = "product_listing"
PAGE_TYPE_DOCUMENTATION = "documentation"
PAGE_TYPE_CASE_STUDY = "case_study"
PAGE_TYPE_CAREERS = "careers"
PAGE_TYPE_LOGIN = "login"
PAGE_TYPE_SIGNUP = "signup"
PAGE_TYPE_CHECKOUT = "checkout"
PAGE_TYPE_SEARCH = "search"
PAGE_TYPE_LANDING = "landing"
PAGE_TYPE_GENERIC = "generic"
PAGE_TYPE_BRAND_ENTITY = "brand_entity"

# ---------------------------------------------------------------------------
# Human-readable labels (used in AI prompts)
# ---------------------------------------------------------------------------
PAGE_TYPE_LABELS: dict[str, str] = {
    PAGE_TYPE_HOMEPAGE: "Homepage / Main Landing",
    PAGE_TYPE_FAQ: "FAQ / Help Center",
    PAGE_TYPE_TERMS: "Terms of Service / Legal",
    PAGE_TYPE_PRIVACY: "Privacy Policy / Legal",
    PAGE_TYPE_CONTACT: "Contact / Support",
    PAGE_TYPE_ABOUT: "About / Company Info",
    PAGE_TYPE_PRICING: "Pricing / Plans",
    PAGE_TYPE_BLOG_INDEX: "Blog Index / Archive",
    PAGE_TYPE_BLOG_ARTICLE: "Blog Post / Article",
    PAGE_TYPE_PRODUCT: "Product / Feature Page",
    PAGE_TYPE_PRODUCT_LISTING: "Product Listing / Category",
    PAGE_TYPE_DOCUMENTATION: "Documentation / Knowledge Base",
    PAGE_TYPE_CASE_STUDY: "Case Study / Success Story",
    PAGE_TYPE_CAREERS: "Careers / Job Listings",
    PAGE_TYPE_LOGIN: "Login / Authentication",
    PAGE_TYPE_SIGNUP: "Sign-up / Registration",
    PAGE_TYPE_CHECKOUT: "Checkout / Payment",
    PAGE_TYPE_SEARCH: "Search Results",
    PAGE_TYPE_LANDING: "Marketing Landing Page",
    PAGE_TYPE_GENERIC: "General Content Page",
    PAGE_TYPE_BRAND_ENTITY: "Brand Entity Audit (No Website)",
}

# ---------------------------------------------------------------------------
# URL-based pattern matchers (ordered by specificity)
# ---------------------------------------------------------------------------
_URL_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Legal / compliance
    (
        PAGE_TYPE_TERMS,
        re.compile(
            r"/(terms|tos|terms-of-service|terms-and-conditions|terms-of-use|legal|eula|acceptable-use)(/|$)",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_PRIVACY,
        re.compile(
            r"/(privacy|privacy-policy|data-protection|cookie-policy|gdpr|cookies)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Auth / account
    (
        PAGE_TYPE_LOGIN,
        re.compile(
            r"/(login|signin|sign-in|log-in|auth/login|authenticate)(/|$)",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_SIGNUP,
        re.compile(
            r"/(signup|sign-up|register|create-account|join|onboarding)(/|$)",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_CHECKOUT,
        re.compile(
            r"/(checkout|cart|payment|billing|purchase|order)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # FAQ / help
    (
        PAGE_TYPE_FAQ,
        re.compile(
            r"/(faq|faqs|frequently-asked|help|help-center|support|knowledge-base)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Company info
    (
        PAGE_TYPE_CONTACT,
        re.compile(
            r"/(contact|contact-us|get-in-touch|reach-out|enquiry|inquiry)(/|$)",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_ABOUT,
        re.compile(
            r"/(about|about-us|our-story|our-team|team|who-we-are|company|mission)(/|$)",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_CAREERS,
        re.compile(
            r"/(careers|jobs|work-with-us|join-us|positions|openings|hiring)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Commercial
    (
        PAGE_TYPE_PRICING,
        re.compile(
            r"/(pricing|prices|plans|packages|cost|subscription)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Case studies
    (
        PAGE_TYPE_CASE_STUDY,
        re.compile(
            r"/(case-stud(y|ies)|success-stor(y|ies)|customer-stor(y|ies)|testimonials?)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Documentation
    (
        PAGE_TYPE_DOCUMENTATION,
        re.compile(
            r"/(docs|documentation|api-docs|api-reference|reference|guides?|tutorials?|manual|wiki)(/|$)",
            re.IGNORECASE,
        ),
    ),
    # Blog (index must come before article to match /blog exactly)
    (
        PAGE_TYPE_BLOG_INDEX,
        re.compile(
            r"/(blog|news|articles|insights|resources|updates|press)/?$",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_BLOG_ARTICLE,
        re.compile(
            r"/(blog|news|articles|insights|resources|updates|press)/[^/]+",
            re.IGNORECASE,
        ),
    ),
    # Product pages
    (
        PAGE_TYPE_PRODUCT_LISTING,
        re.compile(
            r"/(products|solutions|features|services|offerings|categories|shop|store)/?$",
            re.IGNORECASE,
        ),
    ),
    (
        PAGE_TYPE_PRODUCT,
        re.compile(
            r"/(products?|solutions?|features?|services?)/[^/]+",
            re.IGNORECASE,
        ),
    ),
    # Search
    (
        PAGE_TYPE_SEARCH,
        re.compile(
            r"/(search|results|find)(/|$|\?)",
            re.IGNORECASE,
        ),
    ),
]

# Content-based heuristics (headline / heading patterns in markdown)
_CONTENT_SIGNALS: list[tuple[str, list[re.Pattern[str]], int]] = [
    # (page_type, [patterns], min_matches)
    (
        PAGE_TYPE_FAQ,
        [
            re.compile(r"frequently\s+asked\s+questions", re.IGNORECASE),
            re.compile(r"^#{1,3}\s+.+\?$", re.MULTILINE),
        ],
        1,
    ),
    (
        PAGE_TYPE_PRIVACY,
        [
            re.compile(
                r"(privacy\s+policy|data\s+protection|personal\s+data|cookies?\s+policy)",
                re.IGNORECASE,
            ),
            re.compile(
                r"(we\s+collect|information\s+we\s+(gather|collect|process))", re.IGNORECASE
            ),
        ],
        2,
    ),
    (
        PAGE_TYPE_TERMS,
        [
            re.compile(r"(terms\s+of\s+(service|use)|acceptable\s+use)", re.IGNORECASE),
            re.compile(
                r"(governing\s+law|limitation\s+of\s+liability|indemnification)", re.IGNORECASE
            ),
        ],
        2,
    ),
    (
        PAGE_TYPE_PRICING,
        [
            re.compile(
                r"(\$/month|€/month|per\s+month|/mo\b|billed\s+(monthly|annually))", re.IGNORECASE
            ),
            re.compile(
                r"(free\s+plan|starter|pro\s+plan|enterprise\s+plan|pricing\s+table)", re.IGNORECASE
            ),
        ],
        2,
    ),
]


def detect_page_type(
    url: str | None = None,
    content: str | None = None,
    *,
    title: str | None = None,
) -> str:
    """Return the best-guess page type for the given URL / content.

    Priority order:
    1. Homepage detection (path is / or empty)
    2. URL path pattern matching
    3. Content-signal heuristics (when enough evidence is present)
    4. Falls back to ``generic``
    """
    path = ""
    if url:
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/") or "/"
        except Exception:
            path = "/"

    # 1. Homepage
    if path == "/" or path == "":
        return PAGE_TYPE_HOMEPAGE

    # 2. URL patterns
    for page_type, pattern in _URL_PATTERNS:
        if pattern.search(path):
            return page_type

    # 3. Content signals (use markdown / text content)
    text = (content or "") + " " + (title or "")
    if text.strip():
        for page_type, patterns, min_matches in _CONTENT_SIGNALS:
            matches = sum(1 for p in patterns if p.search(text))
            if matches >= min_matches:
                return page_type

    return PAGE_TYPE_GENERIC


def get_page_type_label(page_type: str) -> str:
    """Human-readable label for a page type."""
    return PAGE_TYPE_LABELS.get(page_type, PAGE_TYPE_LABELS[PAGE_TYPE_GENERIC])


# ---------------------------------------------------------------------------
# Page-type-aware schema recommendations
# ---------------------------------------------------------------------------
# Which structured-data types are actually relevant per page type.
# A page type not listed here inherits the "generic" entry.
PAGE_TYPE_SCHEMA_EXPECTATIONS: dict[str, dict[str, Any]] = {
    PAGE_TYPE_HOMEPAGE: {
        "required_types": ["Organization", "WebSite"],
        "high_impact_types": ["Organization", "WebSite", "SiteNavigationElement"],
        "nice_to_have_types": ["LocalBusiness", "BreadcrumbList"],
    },
    PAGE_TYPE_FAQ: {
        "required_types": ["FAQPage"],
        "high_impact_types": ["FAQPage"],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_TERMS: {
        "required_types": [],
        "high_impact_types": [],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_PRIVACY: {
        "required_types": [],
        "high_impact_types": [],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_CONTACT: {
        "required_types": [],
        "high_impact_types": ["LocalBusiness", "ContactPoint"],
        "nice_to_have_types": ["Organization", "BreadcrumbList"],
    },
    PAGE_TYPE_ABOUT: {
        "required_types": ["Organization"],
        "high_impact_types": ["Organization"],
        "nice_to_have_types": ["Person", "BreadcrumbList"],
    },
    PAGE_TYPE_PRICING: {
        "required_types": [],
        "high_impact_types": ["Product", "Offer"],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_BLOG_INDEX: {
        "required_types": [],
        "high_impact_types": ["Blog", "CollectionPage"],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_BLOG_ARTICLE: {
        "required_types": ["Article"],
        "high_impact_types": ["Article", "BlogPosting"],
        "nice_to_have_types": ["BreadcrumbList", "Person"],
    },
    PAGE_TYPE_PRODUCT: {
        "required_types": ["Product"],
        "high_impact_types": ["Product", "Offer", "AggregateRating"],
        "nice_to_have_types": ["BreadcrumbList", "Review"],
    },
    PAGE_TYPE_PRODUCT_LISTING: {
        "required_types": [],
        "high_impact_types": ["CollectionPage", "ItemList"],
        "nice_to_have_types": ["BreadcrumbList", "Product"],
    },
    PAGE_TYPE_DOCUMENTATION: {
        "required_types": [],
        "high_impact_types": ["TechArticle", "HowTo"],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_CASE_STUDY: {
        "required_types": [],
        "high_impact_types": ["Article"],
        "nice_to_have_types": ["Organization", "BreadcrumbList"],
    },
    PAGE_TYPE_CAREERS: {
        "required_types": [],
        "high_impact_types": ["JobPosting"],
        "nice_to_have_types": ["Organization", "BreadcrumbList"],
    },
    PAGE_TYPE_LOGIN: {
        "required_types": [],
        "high_impact_types": [],
        "nice_to_have_types": [],
    },
    PAGE_TYPE_SIGNUP: {
        "required_types": [],
        "high_impact_types": [],
        "nice_to_have_types": [],
    },
    PAGE_TYPE_CHECKOUT: {
        "required_types": [],
        "high_impact_types": [],
        "nice_to_have_types": [],
    },
    PAGE_TYPE_SEARCH: {
        "required_types": [],
        "high_impact_types": ["SearchResultsPage"],
        "nice_to_have_types": ["BreadcrumbList"],
    },
    PAGE_TYPE_LANDING: {
        "required_types": [],
        "high_impact_types": ["Product", "Offer"],
        "nice_to_have_types": ["Organization", "BreadcrumbList"],
    },
    PAGE_TYPE_GENERIC: {
        "required_types": [],
        "high_impact_types": ["WebPage"],
        "nice_to_have_types": ["BreadcrumbList", "Organization"],
    },
}


def get_schema_expectations(page_type: str) -> dict[str, Any]:
    """Return the schema expectations for the given page type."""
    return PAGE_TYPE_SCHEMA_EXPECTATIONS.get(
        page_type,
        PAGE_TYPE_SCHEMA_EXPECTATIONS[PAGE_TYPE_GENERIC],
    )


# ---------------------------------------------------------------------------
# Audit relevance hints (tells the AI what to focus on per page type)
# ---------------------------------------------------------------------------
PAGE_TYPE_AUDIT_HINTS: dict[str, str] = {
    PAGE_TYPE_HOMEPAGE: (
        "This is the HOMEPAGE. Focus on: brand identity clarity, value proposition, "
        "navigation structure, Organization/WebSite schema, above-the-fold hierarchy, "
        "and whether the page communicates the core offering within 3 seconds."
    ),
    PAGE_TYPE_FAQ: (
        "This is an FAQ PAGE. Focus on: FAQPage schema implementation, question-answer "
        "pair quality, direct-answer extraction readiness for voice/AI search, "
        "and whether answers are concise enough for featured snippets."
    ),
    PAGE_TYPE_TERMS: (
        "This is a TERMS OF SERVICE / LEGAL page. Legal pages have minimal SEO/GEO/AEO "
        "value. Focus only on: basic accessibility, proper heading hierarchy, and whether "
        "the page is crawlable. Do NOT recommend FAQ schema, product schema, or "
        "content-marketing strategies for legal pages."
    ),
    PAGE_TYPE_PRIVACY: (
        "This is a PRIVACY POLICY / LEGAL page. Legal pages have minimal SEO/GEO/AEO "
        "value. Focus only on: basic accessibility, proper heading hierarchy, and whether "
        "the page is crawlable. Do NOT recommend FAQ schema, product schema, or "
        "content-marketing strategies for legal pages."
    ),
    PAGE_TYPE_CONTACT: (
        "This is a CONTACT PAGE. Focus on: LocalBusiness/ContactPoint schema, NAP "
        "(Name-Address-Phone) consistency, accessibility of contact methods, and "
        "whether the page supports local SEO signals."
    ),
    PAGE_TYPE_ABOUT: (
        "This is an ABOUT PAGE. Focus on: Organization schema, E-E-A-T signals "
        "(Experience, Expertise, Authoritativeness, Trustworthiness), team/founder "
        "information quality, and brand entity establishment for Knowledge Graph."
    ),
    PAGE_TYPE_PRICING: (
        "This is a PRICING PAGE. Focus on: Product/Offer schema, pricing transparency, "
        "comparison table structure, and whether pricing information is extractable "
        "by AI systems for direct-answer generation."
    ),
    PAGE_TYPE_BLOG_INDEX: (
        "This is a BLOG INDEX page. Focus on: content organization, category structure, "
        "internal linking patterns, pagination/infinite scroll handling, and whether "
        "the archive is efficiently crawlable."
    ),
    PAGE_TYPE_BLOG_ARTICLE: (
        "This is a BLOG ARTICLE. Focus on: Article/BlogPosting schema, content depth "
        "and originality, heading hierarchy, author attribution (E-E-A-T), "
        "internal/external link quality, and citation-worthiness for AI engines."
    ),
    PAGE_TYPE_PRODUCT: (
        "This is a PRODUCT/FEATURE PAGE. Focus on: Product schema, unique value "
        "proposition clarity, feature-benefit framing, competitive differentiation, "
        "and whether the content supports transactional intent queries."
    ),
    PAGE_TYPE_PRODUCT_LISTING: (
        "This is a PRODUCT LISTING / CATEGORY PAGE. Focus on: ItemList/CollectionPage "
        "schema, faceted navigation, filter accessibility, product card structure, "
        "and efficient crawlability of listed items."
    ),
    PAGE_TYPE_DOCUMENTATION: (
        "This is a DOCUMENTATION PAGE. Focus on: TechArticle/HowTo schema, code snippet "
        "readability, step-by-step structure, search-within-docs capability, and whether "
        "the content is structured for featured-snippet extraction."
    ),
    PAGE_TYPE_CASE_STUDY: (
        "This is a CASE STUDY / SUCCESS STORY. Focus on: narrative structure, measurable "
        "outcomes, client attribution, Article schema, and whether the content serves as "
        "trustworthy evidence for E-E-A-T and AI citation."
    ),
    PAGE_TYPE_CAREERS: (
        "This is a CAREERS PAGE. Focus on: JobPosting schema, structured job listing "
        "format, company culture communication, and Google for Jobs compatibility."
    ),
    PAGE_TYPE_LOGIN: (
        "This is a LOGIN PAGE. Auth pages have minimal SEO/GEO/AEO value. "
        "Focus only on: noindex directive, basic security indicators, and redirect behavior. "
        "Do NOT recommend content-marketing strategies for auth pages."
    ),
    PAGE_TYPE_SIGNUP: (
        "This is a SIGNUP / REGISTRATION PAGE. Auth pages have limited SEO value. "
        "Focus on: conversion-oriented UX, noindex handling, and form accessibility. "
        "Do NOT recommend content-marketing strategies for auth pages."
    ),
    PAGE_TYPE_CHECKOUT: (
        "This is a CHECKOUT / PAYMENT PAGE. Focus on: security signals, noindex handling, "
        "and transaction flow. Do NOT recommend content-marketing strategies."
    ),
    PAGE_TYPE_SEARCH: (
        "This is a SEARCH RESULTS PAGE. Focus on: noindex handling (search results "
        "should typically not be indexed), result rendering quality, and filter/facet "
        "structure."
    ),
    PAGE_TYPE_LANDING: (
        "This is a MARKETING LANDING PAGE. Focus on: conversion optimization, value "
        "proposition clarity, trust signals, CTA effectiveness, and whether the page "
        "supports both paid and organic discovery."
    ),
    PAGE_TYPE_GENERIC: (
        "Analyze this page on its own merits. Identify the primary purpose of the content "
        "and tailor recommendations to that purpose."
    ),
    PAGE_TYPE_BRAND_ENTITY: (
        "This is a BRAND ENTITY audit, no website URL was provided. "
        "Focus exclusively on: Knowledge Graph presence, entity authority signals, "
        "brand SERP optimization, AI engine visibility, citation strategies, "
        "and content authority signals. Do NOT recommend website-specific technical "
        "actions (meta tags, page speed, CLS/LCP, canonical URLs, internal linking, "
        "HTTP/2, robots.txt, HTTPS)."
    ),
}


def get_audit_hint(page_type: str) -> str:
    """Return the audit focus hint for the given page type."""
    return PAGE_TYPE_AUDIT_HINTS.get(
        page_type,
        PAGE_TYPE_AUDIT_HINTS[PAGE_TYPE_GENERIC],
    )


# ---------------------------------------------------------------------------
# Suggestion relevance filter
# ---------------------------------------------------------------------------

# Mapping of page types to regex patterns that mark a suggestion as irrelevant.
_IRRELEVANT_SUGGESTION_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    PAGE_TYPE_TERMS: [
        re.compile(r"\bfaq\s*(page)?\s*schema\b", re.I),
        re.compile(r"\bproduct\s*schema\b", re.I),
        re.compile(r"\boffer\s*schema\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bcontent.?market\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
    ],
    PAGE_TYPE_PRIVACY: [
        re.compile(r"\bfaq\s*(page)?\s*schema\b", re.I),
        re.compile(r"\bproduct\s*schema\b", re.I),
        re.compile(r"\boffer\s*schema\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bcontent.?market\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
    ],
    PAGE_TYPE_LOGIN: [
        re.compile(r"\bfaq\s*(page)?\s*schema\b", re.I),
        re.compile(r"\bproduct\s*schema\b", re.I),
        re.compile(r"\bcontent.?market\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
        re.compile(r"\barticle\s*schema\b", re.I),
    ],
    PAGE_TYPE_SIGNUP: [
        re.compile(r"\bfaq\s*(page)?\s*schema\b", re.I),
        re.compile(r"\bproduct\s*schema\b", re.I),
        re.compile(r"\bcontent.?market\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
    ],
    PAGE_TYPE_CHECKOUT: [
        re.compile(r"\bfaq\s*(page)?\s*schema\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bcontent.?market\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
    ],
    PAGE_TYPE_CONTACT: [
        re.compile(r"\bproduct\s*schema\b", re.I),
        re.compile(r"\boffer\s*schema\b", re.I),
        re.compile(r"\bblog\s*(post|article)\b", re.I),
        re.compile(r"\bhowto\s*schema\b", re.I),
    ],
    PAGE_TYPE_BRAND_ENTITY: [
        # Website-specific technical actions are irrelevant for brand-only audits
        re.compile(r"\bmeta\s*(tag|description|title)\b", re.I),
        re.compile(r"\b(page\s*speed|page\s*load|loading\s*speed)\b", re.I),
        re.compile(r"\b(core\s*web\s*vitals|cwv|cls|lcp|fid|inp|ttfb)\b", re.I),
        re.compile(r"\bcanonical\s*(url|tag)\b", re.I),
        re.compile(r"\balt\s*text\b", re.I),
        re.compile(r"\binternal\s*link", re.I),
        re.compile(r"\bhttp/?[23]\b", re.I),
        re.compile(r"\brobots\.txt\b", re.I),
        re.compile(r"\bsitemap(\.xml)?\b", re.I),
        re.compile(r"\bhttps\b", re.I),
        re.compile(r"\bssl\s*(cert|certificate)\b", re.I),
        re.compile(r"\bredirect\s*(chain|loop)\b", re.I),
        re.compile(r"\b(minif|compress|gzip|brotli)\b", re.I),
        re.compile(r"\b(lazy\s*load|image\s*optim)", re.I),
        re.compile(r"\bviewport\b", re.I),
        re.compile(r"\bmobile\s*(friendly|responsive)\b", re.I),
        re.compile(r"\b(heading|h[1-6])\s*(hierarchy|structure|tag)\b", re.I),
        re.compile(r"\b(crawl|index|noindex|nofollow)\b", re.I),
        re.compile(r"\b(render|ssr|csr|hydrat)\b", re.I),
        re.compile(r"\b(open\s*graph|og:)\b", re.I),
        re.compile(r"\bhreflang\b", re.I),
    ],
}


def filter_irrelevant_suggestions(
    suggestions: list[dict[str, str]],
    page_type: str,
) -> list[dict[str, str]]:
    """Remove suggestions that are clearly irrelevant for the detected page type.

    Uses deterministic pattern matching so that obviously misplaced suggestions
    (e.g. FAQ schema on a Terms page) are dropped before the AI enrichment call,
    saving tokens and improving output relevance.
    """
    patterns = _IRRELEVANT_SUGGESTION_PATTERNS.get(page_type)
    if not patterns:
        return suggestions

    filtered: list[dict[str, str]] = []
    for suggestion in suggestions:
        action = str(suggestion.get("action") or "").strip()
        if any(pat.search(action) for pat in patterns):
            continue
        filtered.append(suggestion)
    return filtered


# ---------------------------------------------------------------------------
# Smart-sample URL selection
# ---------------------------------------------------------------------------

# Page types ranked by audit value (higher = more important to include).
_PAGE_TYPE_PRIORITY: dict[str, int] = {
    PAGE_TYPE_HOMEPAGE: 100,
    PAGE_TYPE_PRODUCT: 90,
    PAGE_TYPE_PRODUCT_LISTING: 85,
    PAGE_TYPE_BLOG_ARTICLE: 80,
    PAGE_TYPE_LANDING: 75,
    PAGE_TYPE_FAQ: 70,
    PAGE_TYPE_PRICING: 65,
    PAGE_TYPE_ABOUT: 60,
    PAGE_TYPE_DOCUMENTATION: 55,
    PAGE_TYPE_CASE_STUDY: 50,
    PAGE_TYPE_CONTACT: 45,
    PAGE_TYPE_BLOG_INDEX: 40,
    PAGE_TYPE_CAREERS: 30,
    PAGE_TYPE_SEARCH: 20,
    PAGE_TYPE_GENERIC: 15,
    # Low-value page types (auth/legal) are rarely worth auditing
    PAGE_TYPE_TERMS: 5,
    PAGE_TYPE_PRIVACY: 5,
    PAGE_TYPE_LOGIN: 5,
    PAGE_TYPE_SIGNUP: 5,
    PAGE_TYPE_CHECKOUT: 5,
}

# Page types that are almost never worth spending credits on
_LOW_VALUE_PAGE_TYPES: set[str] = {
    PAGE_TYPE_TERMS,
    PAGE_TYPE_PRIVACY,
    PAGE_TYPE_LOGIN,
    PAGE_TYPE_SIGNUP,
    PAGE_TYPE_CHECKOUT,
}

# ---------------------------------------------------------------------------
# Dimension relevance weights per page type (AEX-06)
# ---------------------------------------------------------------------------
# Each page type maps to (seo_weight, geo_weight, aeo_weight).
# Weight 0.0 means the dimension is structurally irrelevant (shown as N/A).
# Weight 1.0 means full expectations apply.

PAGE_TYPE_DIMENSION_RELEVANCE: dict[str, tuple[float, float, float]] = {
    PAGE_TYPE_HOMEPAGE: (1.0, 1.0, 1.0),
    PAGE_TYPE_PRODUCT: (1.0, 0.8, 0.9),
    PAGE_TYPE_PRODUCT_LISTING: (1.0, 0.7, 0.6),
    PAGE_TYPE_BLOG_ARTICLE: (1.0, 0.5, 1.0),
    PAGE_TYPE_LANDING: (1.0, 0.8, 0.8),
    PAGE_TYPE_FAQ: (0.8, 0.3, 1.0),
    PAGE_TYPE_PRICING: (1.0, 0.5, 0.7),
    PAGE_TYPE_ABOUT: (0.9, 1.0, 0.6),
    PAGE_TYPE_DOCUMENTATION: (0.8, 0.2, 1.0),
    PAGE_TYPE_CASE_STUDY: (0.9, 0.4, 0.8),
    PAGE_TYPE_CONTACT: (0.7, 1.0, 0.3),
    PAGE_TYPE_BLOG_INDEX: (0.9, 0.3, 0.4),
    PAGE_TYPE_CAREERS: (0.7, 0.6, 0.2),
    PAGE_TYPE_SEARCH: (0.5, 0.1, 0.2),
    PAGE_TYPE_GENERIC: (1.0, 0.5, 0.5),
    PAGE_TYPE_TERMS: (0.5, 0.0, 0.0),
    PAGE_TYPE_PRIVACY: (0.5, 0.0, 0.0),
    PAGE_TYPE_LOGIN: (0.3, 0.0, 0.0),
    PAGE_TYPE_SIGNUP: (0.3, 0.0, 0.0),
    PAGE_TYPE_CHECKOUT: (0.6, 0.2, 0.1),
}

# Default for unknown page types, full weight on all dimensions
_DEFAULT_DIMENSION_RELEVANCE: tuple[float, float, float] = (1.0, 1.0, 1.0)


def get_dimension_relevance(page_type: str) -> dict[str, float]:
    """Return dimension relevance weights for a page type.

    Returns dict with keys 'seo', 'geo', 'aeo' and float weights [0.0, 1.0].
    """
    seo, geo, aeo = PAGE_TYPE_DIMENSION_RELEVANCE.get(
        page_type,
        _DEFAULT_DIMENSION_RELEVANCE,
    )
    return {"seo": seo, "geo": geo, "aeo": aeo}


def select_representative_urls(
    urls: list[str],
    *,
    max_per_type: int = 2,
    max_total: int = 15,
    include_low_value: bool = False,
) -> dict[str, list[str]]:
    """Select a representative sample of URLs from a sitemap for smart crawl.

    Groups URLs by page type, then picks up to ``max_per_type`` representative
    URLs from each type, prioritized by audit value.  URLs with distinct path
    depths or slugs are preferred over nearly-identical siblings.

    Returns a dict of ``{page_type: [url, ...]}`` with at most ``max_total``
    URLs across all types.
    """
    # 1. Classify every URL
    type_buckets: dict[str, list[str]] = {}
    for url in urls:
        ptype = detect_page_type(url)
        type_buckets.setdefault(ptype, []).append(url)

    # 2. Filter low-value types unless explicitly requested
    if not include_low_value:
        type_buckets = {
            ptype: bucket
            for ptype, bucket in type_buckets.items()
            if ptype not in _LOW_VALUE_PAGE_TYPES
        }

    # 3. Sort types by priority (highest first)
    sorted_types = sorted(
        type_buckets.keys(),
        key=lambda t: _PAGE_TYPE_PRIORITY.get(t, 10),
        reverse=True,
    )

    # 4. Select diverse URLs from each type
    selected: dict[str, list[str]] = {}
    total = 0
    for ptype in sorted_types:
        if total >= max_total:
            break
        bucket = type_buckets[ptype]
        picks = _pick_diverse_urls(bucket, max_count=min(max_per_type, max_total - total))
        if picks:
            selected[ptype] = picks
            total += len(picks)

    return selected


def _pick_diverse_urls(urls: list[str], max_count: int) -> list[str]:
    """Pick structurally diverse URLs from a list.

    Prefers URLs with different path depths or distinct slug patterns
    so the sample covers template variations rather than near-duplicates.
    """
    if len(urls) <= max_count:
        return list(urls)

    scored: list[tuple[float, str]] = []
    for url in urls:
        try:
            parsed = urlparse(url)
            path = parsed.path.rstrip("/") or "/"
            segments = [s for s in path.split("/") if s]
            depth = len(segments)
            # Prefer medium-depth pages (not too shallow, not too deep)
            depth_score = 1.0 / (1.0 + abs(depth - 2))
            # Prefer pages with readable slugs (not UUIDs or numeric IDs)
            slug = segments[-1] if segments else ""
            slug_readability = 0.5 if re.match(r"^[a-z][a-z0-9-]{2,}$", slug) else 0.0
            scored.append((depth_score + slug_readability, url))
        except Exception:
            scored.append((0.0, url))

    scored.sort(key=lambda t: t[0], reverse=True)

    # Pick from different depth levels for diversity
    selected: list[str] = []
    seen_depths: set[int] = set()
    for _score, url in scored:
        if len(selected) >= max_count:
            break
        try:
            parsed = urlparse(url)
            depth = len([s for s in parsed.path.rstrip("/").split("/") if s])
        except Exception:
            depth = 0
        if depth not in seen_depths or len(selected) < max_count:
            selected.append(url)
            seen_depths.add(depth)

    return selected[:max_count]


def build_smart_crawl_plan(urls: list[str], **kwargs) -> dict[str, Any]:
    """Build a smart crawl plan summary showing what would be audited.

    Returns a dict suitable for the estimate API response.
    """
    all_classified: dict[str, list[str]] = {}
    for url in urls:
        ptype = detect_page_type(url)
        all_classified.setdefault(ptype, []).append(url)

    selected = select_representative_urls(urls, **kwargs)
    selected_count = sum(len(v) for v in selected.values())

    plan_breakdown: list[dict[str, Any]] = []
    for ptype in sorted(
        all_classified.keys(),
        key=lambda t: _PAGE_TYPE_PRIORITY.get(t, 10),
        reverse=True,
    ):
        total_in_type = len(all_classified[ptype])
        sampled = selected.get(ptype, [])
        plan_breakdown.append(
            {
                "page_type": ptype,
                "label": get_page_type_label(ptype),
                "total_urls": total_in_type,
                "sampled_urls": len(sampled),
                "sample_urls": sampled,
                "skipped": ptype in _LOW_VALUE_PAGE_TYPES and ptype not in selected,
                "coverage_ratio": round(len(sampled) / total_in_type, 2) if total_in_type else 0,
            }
        )

    return {
        "total_site_urls": len(urls),
        "total_page_types": len(all_classified),
        "sampled_urls_count": selected_count,
        "plan": plan_breakdown,
        "selected_urls": selected,
    }


# ---------------------------------------------------------------------------
# Site-structure context builder (for sitemap audits)
# ---------------------------------------------------------------------------


def build_site_structure_summary(
    pages: list[dict[str, str | None]],
) -> str:
    """Build a concise site-structure summary from a list of page dicts.

    Each dict should have ``url`` and optionally ``page_type``.
    Returns a markdown-formatted summary string suitable for injection into
    AI prompts.
    """
    if not pages:
        return ""

    type_groups: dict[str, list[str]] = {}
    for page in pages:
        url = page.get("url") or ""
        ptype = page.get("page_type") or detect_page_type(url)
        label = get_page_type_label(ptype)
        type_groups.setdefault(label, []).append(url)

    lines = ["### SITE STRUCTURE CONTEXT"]
    lines.append(f"This site has {len(pages)} known pages:\n")
    for label, urls in sorted(type_groups.items()):
        lines.append(f"- **{label}** ({len(urls)} page{'s' if len(urls) != 1 else ''}):")
        for u in urls[:5]:
            lines.append(f"  - {u}")
        if len(urls) > 5:
            lines.append(f"  - ... and {len(urls) - 5} more")
    lines.append("")
    lines.append(
        "When making recommendations, consider that the site already has these pages. "
        "Do NOT recommend creating pages/features that already exist elsewhere on the site. "
        "For example, if the site has an FAQ page, do not recommend adding FAQ schema to non-FAQ pages."
    )
    return "\n".join(lines)
