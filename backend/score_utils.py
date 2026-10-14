# pyre-unsafe
# score_utils.py, V3 Deterministic Scoring Engine

import re
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from services.geo_signals_extractor import (
    geo_signals_extractor_service,
)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of how a score was calculated.

    Each entry in ``penalties`` is ``{"reason": str, "impact": number}``. A
    penalty raised by a check the customer can act on also carries
    ``"code"``: a stable identifier from :mod:`problem_codes` that does not
    change between audits, unlike the LLM-written recommendation text. It is
    what a dismissal is keyed on, so treat an existing code as permanent
    (renaming one orphans stored customer decisions). Penalties that describe
    our own fetch rather than a fix, e.g. a failed scrape, carry no code.
    """

    total_score: float
    components: Dict[str, float] = field(default_factory=dict)
    penalties: List[Dict[str, Any]] = field(default_factory=list)
    bonuses: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class DeterministicScoringEngine:
    """
    Mathematical Engine V3.0, enterprise-grade deterministic scoring.

    Calculates objective scores based on measurable, factual signals
    extracted from page content, performance metrics, and structured
    data analysis.  Ensures consistent scores across audits when the
    underlying data has not changed, eliminating LLM variability.
    """

    # V3 Weight configuration, enterprise-grade granular sub-categories
    SEO_WEIGHTS = {
        "core_web_vitals": 0.25,
        "technical_seo": 0.20,
        "onpage_content": 0.20,
        "eeat_trust": 0.20,
        "security_accessibility": 0.15,
    }

    GEO_WEIGHTS = {
        "content_citability": 0.30,  # How well AI engines can cite this content
        "source_authority": 0.25,  # Trust/authority signals for AI citation
        "entity_clarity": 0.25,  # Schema coverage + entity definition quality
        "brand_citation": 0.20,  # Brand presence signals across platforms
    }

    AEO_WEIGHTS = {
        "llm_schema_readiness": 0.30,
        "semantic_entity_density": 0.25,
        "information_gain": 0.25,
        "snippet_formatting": 0.20,
    }

    # Penalty configuration for findings-based fallback
    CRITICAL_PENALTY = 15.0
    WARNING_PENALTY = 5.0
    INFO_PENALTY = 0.0
    # Max penalty from AI findings, raised from 10 to 45 (AEX-10) so that
    # severe content issues meaningfully impact the deterministic score while
    # still bounding model-dependent variance via diminishing returns.
    # Expected: 5 critical → ~32.5, 10 critical → ~40.5
    FINDINGS_PENALTY_CAP = 45.0

    # ------------------------------------------------------------------ #
    #  Content format detection & dual-format helpers (AEX-07)
    # ------------------------------------------------------------------ #
    _HTML_TAG_RE = re.compile(
        r"<(?:html|head|body|div|p|h[1-6]|table|ul|ol|dl|img)\b", re.IGNORECASE
    )

    @classmethod
    def _detect_content_format(cls, content: str) -> str:
        """Detect whether content is HTML or markdown."""
        if not content:
            return "html"  # default / empty
        if cls._HTML_TAG_RE.search(content):
            return "html"
        return "markdown"

    # Compiled markdown patterns
    _MD_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
    _MD_H1_RE = re.compile(r"^#\s", re.MULTILINE)
    _MD_H2_RE = re.compile(r"^#{2}\s", re.MULTILINE)
    _MD_H3_RE = re.compile(r"^#{3}\s", re.MULTILINE)
    _MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
    _MD_TABLE_RE = re.compile(r"^\|.+\|.+\|", re.MULTILINE)
    _MD_LIST_UL_RE = re.compile(r"^\s*[-*+]\s", re.MULTILINE)
    _MD_LIST_OL_RE = re.compile(r"^\s*\d+\.\s", re.MULTILINE)
    _MD_DEFINITION_RE = re.compile(r"^:\s+\S", re.MULTILINE)
    _MD_QA_RE = re.compile(r"^#{1,6}\s+[^\n]*\?\s*\n+(?:\S[^\n]{20,200})", re.MULTILINE)
    _MD_BOLD_RE = re.compile(r"\*\*[^*]+\*\*|__[^_]+__")

    @classmethod
    def _has_headings_h2(cls, content: str, fmt: str) -> bool:
        if fmt == "html":
            return "<h2" in content.lower() or bool(cls._MD_H2_RE.search(content))
        return bool(cls._MD_H2_RE.search(content))

    @classmethod
    def _has_headings_h3(cls, content: str, fmt: str) -> bool:
        if fmt == "html":
            return "<h3" in content.lower() or bool(cls._MD_H3_RE.search(content))
        return bool(cls._MD_H3_RE.search(content))

    @classmethod
    def _count_images(cls, content: str, fmt: str) -> list:
        """Return list of image matches (HTML <img> tags or markdown images)."""
        if fmt == "html":
            return re.findall(r"<img[^>]*>", content, re.IGNORECASE)
        return cls._MD_IMAGE_RE.findall(content)

    @classmethod
    def _count_image_alt_ratio(cls, content: str, fmt: str) -> tuple:
        """Return (total_images, images_with_alt)."""
        if fmt == "html":
            images = re.findall(r"<img[^>]*>", content, re.IGNORECASE)
            with_alt = sum(
                1
                for img in images
                if re.search(r'alt\s*=\s*"[^"]+"|alt\s*=\s*\'[^\']+\'', img, re.IGNORECASE)
            )
            return len(images), with_alt
        # Markdown: ![alt text](url), alt is non-empty if alt group is non-empty
        matches = cls._MD_IMAGE_RE.findall(content)
        with_alt = sum(1 for alt, _ in matches if alt.strip())
        return len(matches), with_alt

    @classmethod
    def _has_lists(cls, content: str, fmt: str) -> bool:
        if fmt == "html":
            return bool(re.search(r"<(ul|ol)[^>]*>", content, re.IGNORECASE))
        return bool(cls._MD_LIST_UL_RE.search(content)) or bool(cls._MD_LIST_OL_RE.search(content))

    @classmethod
    def _count_lists(cls, content: str, fmt: str) -> int:
        if fmt == "html":
            return len(re.findall(r"<(?:ol|ul)[^>]*>", content, re.IGNORECASE))
        # Count markdown list "blocks" by counting unique list starts after blank lines
        ul = len(cls._MD_LIST_UL_RE.findall(content))
        ol = len(cls._MD_LIST_OL_RE.findall(content))
        # Estimate block count (each block averages ~3-5 items)
        return max(1, (ul + ol) // 3) if (ul + ol) > 0 else 0

    @classmethod
    def _has_tables(cls, content: str, fmt: str) -> bool:
        if fmt == "html":
            return bool(re.search(r"<table[^>]*>", content, re.IGNORECASE))
        return bool(cls._MD_TABLE_RE.search(content))

    @classmethod
    def _count_tables(cls, content: str, fmt: str) -> int:
        if fmt == "html":
            return len(re.findall(r"<table", content.lower()))
        # Markdown: count separator rows (|---|---|) as table indicators
        separators = re.findall(r"^\|[\s\-:|]+\|", content, re.MULTILINE)
        return len(separators)

    @classmethod
    def _has_definition_markup(cls, content: str, fmt: str) -> bool:
        if fmt == "html":
            cl = content.lower()
            return "<dl" in cl or "<dt" in cl or "<dd" in cl
        return bool(cls._MD_DEFINITION_RE.search(content))

    @classmethod
    def _count_qa_patterns(cls, content: str, fmt: str) -> int:
        if fmt == "html":
            return len(re.findall(r"\?\s*</h[1-6]>\s*<p>[^<]{20,200}</p>", content, re.IGNORECASE))
        return len(cls._MD_QA_RE.findall(content))

    @classmethod
    def _extract_paragraphs(cls, content: str, fmt: str) -> list:
        """Extract paragraph text for conciseness checking."""
        if fmt == "html":
            return re.findall(r"<p[^>]*>([^<]+)</p>", content, re.IGNORECASE)
        # Markdown: split on double newlines, filter out headings/lists/tables
        blocks = re.split(r"\n\n+", content)
        return [
            b.strip()
            for b in blocks
            if b.strip()
            and not b.strip().startswith("#")
            and not b.strip().startswith("|")
            and not b.strip().startswith("-")
            and not b.strip().startswith("*")
            and not re.match(r"^\d+\.", b.strip())
            and len(b.strip()) > 10
        ]

    # ------------------------------------------------------------------ #
    #  SEO Score (V3)
    # ------------------------------------------------------------------ #
    @classmethod
    def calculate_seo_score(
        cls,
        *,
        performance_metrics: Optional[Dict[str, Any]] = None,
        scrape_metadata: Optional[Dict[str, Any]] = None,
        network_data: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        findings: Optional[List[Dict[str, Any]]] = None,
        scrape_succeeded: bool = True,
    ) -> ScoreBreakdown:
        """
        V3 SEO Score, enterprise-grade granular calculation.

        Sub-categories:
        - Core Web Vitals & Performance (25%)
        - Technical SEO (20%)
        - On-Page & Content Quality (20%)
        - E-E-A-T & Trust Signals (20%)
        - Security & Accessibility (15%)

        When *scrape_succeeded* is False, content-dependent sub-categories
        (technical_seo, onpage_content, eeat_trust) are set to 0 without
        penalties, absence of evidence ≠ evidence of absence.
        """
        components: Dict[str, float] = {}
        penalties: List[Dict[str, Any]] = []
        bonuses: List[Dict[str, Any]] = []

        perf = performance_metrics or {}
        meta = scrape_metadata or {}
        network = network_data or {}
        page_content = content or ""

        components["core_web_vitals"] = cls._calculate_core_web_vitals_score(
            perf, penalties, bonuses
        )

        if scrape_succeeded:
            components["technical_seo"] = cls._calculate_technical_seo_score(
                meta, page_content, penalties, bonuses
            )
            components["onpage_content"] = cls._calculate_onpage_content_score(
                meta, page_content, penalties, bonuses
            )
            components["eeat_trust"] = cls._calculate_eeat_trust_score(
                page_content, meta, penalties, bonuses
            )
        else:
            components["technical_seo"] = 0.0
            components["onpage_content"] = 0.0
            components["eeat_trust"] = 0.0
            penalties.append(
                {"reason": "Scraping failed, content-dependent SEO checks skipped", "impact": 0}
            )

        components["security_accessibility"] = cls._calculate_security_accessibility_score(
            meta, network, page_content, penalties, bonuses
        )

        total = sum(components.get(k, 0.0) * w for k, w in cls.SEO_WEIGHTS.items())

        if findings:
            fp = cls._calculate_findings_penalty(findings)
            if fp > 0:
                total = max(0.0, total - fp)
            penalties.extend(cls._findings_to_penalty_entries(findings, category_fallback="seo"))

        return ScoreBreakdown(
            total_score=float(round(max(0.0, min(100.0, total)), 1)),
            components=components,
            penalties=penalties,
            bonuses=bonuses,
            metadata={"version": "3.0", "category": "seo"},
        )

    # ------------------------------------------------------------------ #
    #  GEO Score (V3)
    # ------------------------------------------------------------------ #
    @classmethod
    def calculate_geo_score(
        cls,
        *,
        schema_analysis: Optional[Dict[str, Any]] = None,
        scrape_metadata: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        findings: Optional[List[Dict[str, Any]]] = None,
        brand_name: Optional[str] = None,
        scrape_succeeded: bool = True,
    ) -> ScoreBreakdown:
        """
        V3.1 GEO Score, Generative Engine Optimization scoring.

        Sub-categories:
        - Content Citability (30%), How well AI engines can cite this content
        - Source Authority (25%), Trust/authority signals for AI citation preference
        - Entity Clarity (25%), Schema coverage + entity definition quality
        - Brand & Citation Readiness (20%), Brand presence across platforms

        When *scrape_succeeded* is False, content-dependent sub-categories
        are set to 0 without penalties.
        """
        components: Dict[str, float] = {}
        penalties: List[Dict[str, Any]] = []
        bonuses: List[Dict[str, Any]] = []

        schema = schema_analysis or {}
        meta = scrape_metadata or {}
        page_content = content or ""

        # AEX-15: extract dynamic geo signals (international, service-area, industry)
        geo_signals = geo_signals_extractor_service.extract(
            content=page_content,
            schema_analysis=schema,
            scrape_metadata=meta,
        )

        # Entity clarity uses schema data (always available)
        components["entity_clarity"] = cls._calculate_entity_clarity_score(
            schema, page_content, penalties, bonuses
        )

        if scrape_succeeded:
            components["content_citability"] = cls._calculate_content_citability_score(
                page_content,
                meta,
                penalties,
                bonuses,
            )
            components["source_authority"] = cls._calculate_source_authority_score(
                page_content,
                meta,
                penalties,
                bonuses,
            )
            components["brand_citation"] = cls._calculate_brand_citation_score(
                page_content, schema, penalties, bonuses
            )
        else:
            components["content_citability"] = 0.0
            components["source_authority"] = 0.0
            components["brand_citation"] = 0.0
            penalties.append(
                {"reason": "Scraping failed, content-dependent GEO checks skipped", "impact": 0}
            )

        total = sum(components.get(k, 0.0) * w for k, w in cls.GEO_WEIGHTS.items())

        if findings:
            fp = cls._calculate_findings_penalty(findings)
            if fp > 0:
                total = max(0.0, total - fp)
            penalties.extend(cls._findings_to_penalty_entries(findings, category_fallback="geo"))

        return ScoreBreakdown(
            total_score=float(round(max(0.0, min(100.0, total)), 1)),
            components=components,
            penalties=penalties,
            bonuses=bonuses,
            metadata={
                "version": "3.1",
                "category": "geo",
                "extracted_geo_signals": {
                    "signal_count": geo_signals.signal_count,
                    "address_formats": geo_signals.address_formats_detected,
                    "service_area_detected": geo_signals.service_area_detected,
                    "industry_labels": geo_signals.industry_labels_detected,
                    "schema_location_properties": geo_signals.schema_location_properties,
                    "has_international": geo_signals.has_international_signals,
                },
            },
        )

    # ------------------------------------------------------------------ #
    #  AEO Score (V3)
    # ------------------------------------------------------------------ #
    @classmethod
    def calculate_aeo_score(
        cls,
        *,
        schema_analysis: Optional[Dict[str, Any]] = None,
        scrape_metadata: Optional[Dict[str, Any]] = None,
        content: Optional[str] = None,
        findings: Optional[List[Dict[str, Any]]] = None,
        scrape_succeeded: bool = True,
    ) -> ScoreBreakdown:
        """
        V3 AEO Score, enterprise-grade granular calculation.

        Sub-categories:
        - AI/LLM Schema Readiness (30%)
        - Semantic & Entity Density (25%)
        - Information Gain & Readability (25%)
        - Snippet & LLM Formatting (20%)

        When *scrape_succeeded* is False, content-dependent sub-categories
        (semantic_entity_density, information_gain, snippet_formatting)
        are set to 0 without penalties.
        """
        components: Dict[str, float] = {}
        penalties: List[Dict[str, Any]] = []
        bonuses: List[Dict[str, Any]] = []

        schema = schema_analysis or {}
        page_content = content or ""

        components["llm_schema_readiness"] = cls._calculate_llm_schema_score(
            schema, penalties, bonuses
        )

        if scrape_succeeded:
            components["semantic_entity_density"] = cls._calculate_semantic_entity_score(
                page_content, penalties, bonuses
            )
            components["information_gain"] = cls._calculate_information_gain_score(
                page_content, penalties, bonuses
            )
            components["snippet_formatting"] = cls._calculate_snippet_formatting_score(
                page_content, penalties, bonuses
            )
        else:
            components["semantic_entity_density"] = 0.0
            components["information_gain"] = 0.0
            components["snippet_formatting"] = 0.0
            penalties.append(
                {"reason": "Scraping failed, content-dependent AEO checks skipped", "impact": 0}
            )

        total = sum(components.get(k, 0.0) * w for k, w in cls.AEO_WEIGHTS.items())

        if findings:
            fp = cls._calculate_findings_penalty(findings)
            if fp > 0:
                total = max(0.0, total - fp)
            penalties.extend(cls._findings_to_penalty_entries(findings, category_fallback="aeo"))

        return ScoreBreakdown(
            total_score=float(round(max(0.0, min(100.0, total)), 1)),
            components=components,
            penalties=penalties,
            bonuses=bonuses,
            metadata={"version": "3.0", "category": "aeo"},
        )

    # ------------------------------------------------------------------ #
    #  Legacy / Overall helpers
    # ------------------------------------------------------------------ #
    @classmethod
    def calculate_overall_score(
        cls,
        scores: Dict[str, float],
        weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """Calculates the weighted overall score. Default: SEO 40%, AEO 30%, GEO 30%."""
        if weights is None:
            weights = {"seo": 0.4, "aeo": 0.3, "geo": 0.3}
        total_weight = 0.0
        weighted_sum = 0.0
        for key, weight in weights.items():
            if key in scores:
                weighted_sum += scores[key] * weight
                total_weight += weight
        if total_weight == 0.0:
            return 0.0
        return max(0.0, min(100.0, float(round(weighted_sum / total_weight))))

    # ================================================================== #
    #  V3 SEO Sub-category Helpers
    # ================================================================== #

    @classmethod
    def _calculate_core_web_vitals_score(
        cls,
        perf: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Core Web Vitals & Performance, LCP, CLS, TBT, TTFB (25%)."""
        # Direct performance score from PageSpeed Insights
        perf_score = cls._extract_numeric(perf.get("performance_score"), 0)
        if perf_score > 0:
            if perf_score >= 90:
                bonuses.append(
                    {"reason": f"Excellent performance score ({perf_score})", "impact": 10}
                )
            return min(100.0, perf_score)

        # Estimate from individual CWV metrics (0 when metric unavailable, no evidence = no score)
        lcp = cls._parse_timing_value(perf.get("largest_contentful_paint"))
        lcp_score = (100 if lcp < 2500 else (80 if lcp < 4000 else 40)) if lcp > 0 else 0
        if lcp > 0 and lcp >= 4000:
            penalties.append(
                {"reason": f"Poor LCP ({lcp:.0f}ms)", "impact": -15, "code": "poor_lcp"}
            )

        cls_val = cls._parse_cls_value(perf.get("cumulative_layout_shift"))
        cls_score = (
            (100 if cls_val < 0.1 else (75 if cls_val < 0.25 else 35)) if cls_val >= 0 else 0
        )
        if cls_val >= 0.25:
            penalties.append(
                {"reason": f"Poor CLS ({cls_val:.3f})", "impact": -15, "code": "poor_cls"}
            )

        tbt = cls._parse_timing_value(perf.get("total_blocking_time"))
        tbt_score = (100 if tbt < 200 else (75 if tbt < 600 else 35)) if tbt > 0 else 0

        ttfb = cls._parse_timing_value(perf.get("time_to_first_byte") or perf.get("ttfb"))
        ttfb_score = (100 if ttfb < 800 else (70 if ttfb < 1800 else 35)) if ttfb > 0 else 0

        return lcp_score * 0.30 + cls_score * 0.25 + tbt_score * 0.25 + ttfb_score * 0.20

    @classmethod
    def _calculate_technical_seo_score(
        cls,
        meta: Dict[str, Any],
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Technical SEO, indexability, canonicalization, mobile, hreflang, sitemap (20%)."""
        score = 0.0
        content_lower = content.lower()

        # Canonical (+20)
        if meta.get("canonical"):
            score += 20
            bonuses.append({"reason": "Canonical URL present", "impact": 20})
        else:
            penalties.append(
                {"reason": "Missing canonical URL", "impact": -15, "code": "missing_canonical_url"}
            )

        # Mobile-friendliness / viewport (+20)
        if meta.get("viewport") or "viewport" in content_lower:
            score += 20
            bonuses.append({"reason": "Mobile viewport configured", "impact": 20})
        else:
            penalties.append(
                {
                    "reason": "No mobile viewport meta",
                    "impact": -15,
                    "code": "missing_mobile_viewport",
                }
            )

        # Hreflang (+15), check metadata; markdown content does not include <head> link tags
        if meta.get("hreflang"):
            score += 15
            bonuses.append({"reason": "Hreflang tags present", "impact": 15})

        # Sitemap reference (+15), rely on scraper metadata, not naive content search
        if meta.get("sitemap"):
            score += 15
            bonuses.append({"reason": "Sitemap reference detected", "impact": 15})

        # Robots / indexability (+15 or -25)
        robots = str(meta.get("robots") or "").lower()
        if "noindex" in robots:
            score -= 25
            penalties.append(
                {"reason": "Page set to noindex", "impact": -25, "code": "page_noindex"}
            )
        elif robots and "index" in robots:
            score += 15
            bonuses.append({"reason": "Indexable robots directive", "impact": 15})

        # HTML lang attribute (+10)
        if meta.get("language") or meta.get("lang") or "lang=" in content_lower:
            score += 10
            bonuses.append({"reason": "HTML lang attribute set", "impact": 10})

        # Charset declaration (+5)
        if "charset" in content_lower:
            score += 5
            bonuses.append({"reason": "Charset declaration present", "impact": 5})

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_onpage_content_score(
        cls,
        meta: Dict[str, Any],
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """On-Page & Content Quality, meta tags, heading hierarchy, alt-text, word count (20%)."""
        score = 0.0

        # Title
        title = meta.get("title") or ""
        if title and 30 <= len(title.strip()) <= 60:
            score += 15
            bonuses.append({"reason": "Optimal title length", "impact": 15})
        elif title and len(title.strip()) >= 10:
            score += 10
        elif title:
            score += 5
            penalties.append({"reason": "Title too short", "impact": -5, "code": "title_too_short"})
        else:
            penalties.append(
                {"reason": "Missing page title", "impact": -15, "code": "missing_page_title"}
            )

        # Meta description
        desc = meta.get("description") or meta.get("meta_description") or ""
        if desc and 120 <= len(desc.strip()) <= 160:
            score += 15
            bonuses.append({"reason": "Optimal meta description length", "impact": 15})
        elif desc and len(desc.strip()) >= 50:
            score += 10
        elif desc:
            score += 5
            penalties.append(
                {
                    "reason": "Meta description too short",
                    "impact": -5,
                    "code": "meta_description_too_short",
                }
            )
        else:
            penalties.append(
                {
                    "reason": "Missing meta description",
                    "impact": -15,
                    "code": "missing_meta_description",
                }
            )

        # Heading hierarchy H1-H6
        headings = meta.get("headings", [])
        content_lower = content.lower()
        fmt = cls._detect_content_format(content)
        h1_count = (
            sum(1 for h in headings if isinstance(h, str) and h.strip())
            if isinstance(headings, list)
            else 0
        )
        # Fallback: detect H1 from markdown/HTML content when metadata headings missing
        if h1_count == 0 and content:
            if fmt == "html":
                h1_count = content_lower.count("<h1")
            else:
                h1_count = len(cls._MD_H1_RE.findall(content))
        has_h2 = cls._has_headings_h2(content, fmt)
        has_h3 = cls._has_headings_h3(content, fmt)

        if h1_count == 1:
            score += 10
            bonuses.append({"reason": "Single H1 tag present", "impact": 10})
        elif h1_count > 1:
            score += 5
            penalties.append(
                {
                    "reason": f"Multiple H1 tags ({h1_count})",
                    "impact": -5,
                    "code": "multiple_h1_tags",
                }
            )
        else:
            penalties.append({"reason": "No H1 tag found", "impact": -10, "code": "missing_h1"})
        if has_h2:
            score += 5
        if has_h3:
            score += 5

        # Image alt-text coverage
        total_images, with_alt = cls._count_image_alt_ratio(content, fmt)
        if total_images > 0:
            alt_ratio = with_alt / total_images
            if alt_ratio >= 0.9:
                score += 10
                bonuses.append(
                    {
                        "reason": f"Excellent alt-text coverage ({with_alt}/{total_images})",
                        "impact": 10,
                    }
                )
            elif alt_ratio >= 0.5:
                score += 5
            else:
                penalties.append(
                    {
                        "reason": f"Poor alt-text coverage ({with_alt}/{total_images})",
                        "impact": -5,
                        "code": "poor_alt_text_coverage",
                    }
                )

        # Word count vs DOM size ratio
        words = len(content.split()) if content else 0
        if words >= 1500:
            score += 15
            bonuses.append({"reason": f"Comprehensive content ({words} words)", "impact": 15})
        elif words >= 800:
            score += 10
        elif words >= 300:
            score += 5
        elif words > 0:
            penalties.append(
                {"reason": f"Thin content ({words} words)", "impact": -10, "code": "thin_content"}
            )

        # OG tags
        if meta.get("og:title") or meta.get("og_title"):
            score += 5
            bonuses.append({"reason": "Open Graph tags present", "impact": 5})

        # Structured content markers
        if cls._has_lists(content, fmt):
            score += 5
        if cls._has_tables(content, fmt):
            score += 5

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_eeat_trust_score(
        cls,
        content: str,
        meta: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """E-E-A-T & Trust Signals, author bios, about/contact, privacy, authority links (20%)."""
        score = 0.0
        content_lower = content.lower()

        # Author attribution, structured checks only (AEX-10)
        # Replaces the old r"author" regex which matched "unauthorized", CSS classes, etc.
        author_detected = False

        # Strong signal: <meta name="author" content="..."> (+20)
        if re.search(r'<meta\s+[^>]*name\s*=\s*["\']author["\']', content, re.IGNORECASE):
            author_detected = True

        # Strong signal: JSON-LD Person author (+20)
        if not author_detected and re.search(r'"@type"\s*:\s*"Person"', content):
            author_detected = True

        # Strong signal: rel="author" link (+20)
        if not author_detected and re.search(r'rel\s*=\s*["\']author["\']', content, re.IGNORECASE):
            author_detected = True

        # Moderate signal: visible byline "By Name" / "Written by Name" (+20)
        if not author_detected and re.search(
            r"(?:written\s+by|posted\s+by|by)\s+[A-Z][a-z]+\s+[A-Z][a-z]+",
            content,
        ):
            author_detected = True

        # Moderate signal: author bio section (class/id containing "author-bio", "author-info", "byline")
        if not author_detected and re.search(
            r'(?:class|id)\s*=\s*["\'][^"\']*(?:author-bio|author-info|byline)[^"\']*["\']',
            content,
            re.IGNORECASE,
        ):
            author_detected = True

        if author_detected:
            score += 20
            bonuses.append({"reason": "Author attribution detected", "impact": 20})

        # About / Contact pages (+20)
        if re.search(r'href\s*=\s*["\'][^"\']*(?:about|contact)[^"\']*["\']', content_lower):
            score += 20
            bonuses.append({"reason": "About/Contact page links found", "impact": 20})

        # Privacy policy (+15)
        if "privacy" in content_lower and (
            "policy" in content_lower or re.search(r'href\s*=\s*["\'][^"\']*privacy', content_lower)
        ):
            score += 15
            bonuses.append({"reason": "Privacy policy reference found", "impact": 15})

        # Outbound links to authoritative domains (+20 / +10)
        authority_domains = [
            "wikipedia.org",
            "gov.",
            ".edu",
            "scholar.google",
            "pubmed",
            "reuters.com",
            "bbc.com",
            "nytimes.com",
        ]
        outbound_links = re.findall(r'href\s*=\s*["\']https?://([^"\'>/]+)', content, re.IGNORECASE)
        authority_count = sum(
            1 for link in outbound_links if any(d in link for d in authority_domains)
        )
        if authority_count >= 3:
            score += 20
            bonuses.append(
                {
                    "reason": f"Strong authority linking ({authority_count} authoritative links)",
                    "impact": 20,
                }
            )
        elif authority_count >= 1:
            score += 10
            bonuses.append({"reason": f"Authority link(s) found ({authority_count})", "impact": 10})

        # Citations / references (+10)
        if re.search(r"\[(?:\d+|citation)", content_lower):
            score += 10
            bonuses.append({"reason": "Citation markers detected", "impact": 10})

        # Date / freshness (+10)
        if re.search(r"(?:published|updated|modified)\s*:?\s*\d{4}", content, re.IGNORECASE):
            score += 10
            bonuses.append({"reason": "Content date marker found", "impact": 10})

        # Structured author schema (+5), note: this is additive to author detection above
        if re.search(r'"@type"\s*:\s*"Person"', content) or "schema.org/Person" in content:
            score += 5
            bonuses.append({"reason": "Structured author schema detected", "impact": 5})

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_security_accessibility_score(
        cls,
        meta: Dict[str, Any],
        network: Dict[str, Any],
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Security & Accessibility, HTTPS, HTTP/2+, mixed content, ARIA (15%)."""
        score = 0.0

        # HTTPS (+30 or -30 penalty for HTTP)
        url = meta.get("url") or ""
        is_https = str(url).startswith("https://")
        if is_https:
            score += 30
            bonuses.append({"reason": "HTTPS enabled", "impact": 30})
        elif str(url).startswith("http://"):
            score -= 30
            penalties.append({"reason": "Not using HTTPS", "impact": -30, "code": "no_https"})

        # HTTP/2 (+15)
        if network.get("supports_http2"):
            score += 15
            bonuses.append({"reason": "HTTP/2 supported", "impact": 15})

        # HTTP/3 (+10)
        if network.get("supports_http3_inferred") or network.get("supports_http3"):
            score += 10
            bonuses.append({"reason": "HTTP/3 supported", "impact": 10})

        # Mixed content (-15)
        content_lower = content.lower()
        if is_https and re.search(r'src\s*=\s*["\']http://', content, re.IGNORECASE):
            score -= 15
            penalties.append(
                {
                    "reason": "Mixed content detected (HTTP resources on HTTPS page)",
                    "impact": -15,
                    "code": "mixed_content",
                }
            )
        elif is_https:
            score += 10
            bonuses.append({"reason": "No mixed content issues", "impact": 10})

        # ARIA labels (+15 / +8)
        aria_count = len(re.findall(r"aria-(?:label|describedby|labelledby)", content_lower))
        if aria_count >= 5:
            score += 15
            bonuses.append(
                {"reason": f"Good ARIA accessibility ({aria_count} attributes)", "impact": 15}
            )
        elif aria_count >= 1:
            score += 8
            bonuses.append({"reason": f"ARIA attributes present ({aria_count})", "impact": 8})

        # Role attributes (+10)
        if "role=" in content_lower:
            score += 10
            bonuses.append({"reason": "ARIA role attributes found", "impact": 10})

        # Security headers, check actual HTTP response headers, not page content
        response_headers = network.get("response_headers", {})
        if response_headers and isinstance(response_headers, dict):
            _rh_lower = {k.lower(): v for k, v in response_headers.items()}
            security_headers_found = sum(
                1
                for h in ("content-security-policy", "x-frame-options", "strict-transport-security")
                if h in _rh_lower
            )
            if security_headers_found >= 1:
                score += 10
                bonuses.append(
                    {
                        "reason": f"Security headers present ({security_headers_found}/3)",
                        "impact": 10,
                    }
                )

        return min(100.0, max(0.0, score))

    # ================================================================== #
    #  V3.1 GEO Sub-category Helpers (Generative Engine Optimization)
    # ================================================================== #

    # -- Regex patterns for content citability --
    _STAT_PATTERN = re.compile(
        r"\b\d+(?:\.\d+)?%|\b\d{1,3}(?:,\d{3})+\b|\$\d+|\d+x\b", re.IGNORECASE
    )
    _DEFINITION_PATTERN = re.compile(
        r"(?:is defined as|refers to|is a type of|also known as|meaning|i\.e\.|e\.g\.)",
        re.IGNORECASE,
    )
    _DIRECT_ANSWER_RE = re.compile(r"^#{1,3}\s+[^\n]*\?\s*$", re.MULTILINE)

    @classmethod
    def _calculate_content_citability_score(
        cls,
        content: str,
        meta: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Content Citability, How well AI engines can extract and cite this content (30%).

        Measures: heading structure, direct answers, factual density,
        paragraph length, content depth, and definition patterns.
        """
        score = 0.0
        text = re.sub(r"<[^>]+>", " ", content)
        text_lower = text.lower()
        text_clean = re.sub(r"\s+", " ", text).strip()
        if not text_clean:
            return score

        fmt = cls._detect_content_format(content)
        words = text_clean.split()
        word_count = len(words)

        # 1. Content depth, sufficient length for AI to cite (+15 / +8)
        if word_count >= 800:
            score += 15
            bonuses.append({"reason": f"Strong content depth ({word_count} words)", "impact": 15})
        elif word_count >= 300:
            score += 8
            bonuses.append({"reason": f"Adequate content depth ({word_count} words)", "impact": 8})

        # 2. Clear heading hierarchy (+15 / +8)
        if fmt == "markdown":
            h1s = len(cls._MD_H1_RE.findall(content))
            h2s = len(cls._MD_H2_RE.findall(content))
            h3s = len(cls._MD_H3_RE.findall(content))
        else:
            h1s = len(re.findall(r"<h1\b", content, re.IGNORECASE))
            h2s = len(re.findall(r"<h2\b", content, re.IGNORECASE))
            h3s = len(re.findall(r"<h3\b", content, re.IGNORECASE))
        total_headings = h1s + h2s + h3s
        if total_headings >= 4 and h2s >= 2:
            score += 15
            bonuses.append(
                {"reason": f"Clear heading hierarchy ({total_headings} headings)", "impact": 15}
            )
        elif total_headings >= 2:
            score += 8
            bonuses.append(
                {"reason": f"Basic heading structure ({total_headings} headings)", "impact": 8}
            )

        # 3. Direct answerable content, Q&A headings, definition patterns (+20 / +10)
        qa_headings = len(cls._DIRECT_ANSWER_RE.findall(content))
        definitions = len(cls._DEFINITION_PATTERN.findall(text_clean))
        direct_answer_signals = qa_headings + definitions
        if direct_answer_signals >= 3:
            score += 20
            bonuses.append(
                {
                    "reason": f"Strong direct-answer content ({direct_answer_signals} patterns)",
                    "impact": 20,
                }
            )
        elif direct_answer_signals >= 1:
            score += 10
            bonuses.append(
                {
                    "reason": f"Some direct-answer content ({direct_answer_signals} patterns)",
                    "impact": 10,
                }
            )

        # 4. Factual density, statistics, numbers, data points (+15 / +8)
        stats = cls._STAT_PATTERN.findall(text_clean)
        if len(stats) >= 5:
            score += 15
            bonuses.append(
                {"reason": f"High factual density ({len(stats)} data points)", "impact": 15}
            )
        elif len(stats) >= 2:
            score += 8
            bonuses.append({"reason": f"Some factual data ({len(stats)} data points)", "impact": 8})

        # 5. Lists and tables, structured citable content (+10)
        if fmt == "markdown":
            has_lists = bool(
                cls._MD_LIST_UL_RE.search(content) or cls._MD_LIST_OL_RE.search(content)
            )
            has_tables = bool(cls._MD_TABLE_RE.search(content))
        else:
            has_lists = bool(re.search(r"<(?:ul|ol|li)\b", content, re.IGNORECASE))
            has_tables = bool(re.search(r"<table\b", content, re.IGNORECASE))
        if has_lists or has_tables:
            score += 10
            bonuses.append(
                {"reason": "Structured content (lists/tables) for AI extraction", "impact": 10}
            )

        # 6. Short citable paragraphs, avg paragraph length in readable range (+10)
        paragraphs = [p.strip() for p in re.split(r"\n\n+", text_clean) if len(p.strip()) > 20]
        if paragraphs:
            avg_para_words = sum(len(p.split()) for p in paragraphs) / len(paragraphs)
            if 20 <= avg_para_words <= 100:
                score += 10
                bonuses.append(
                    {"reason": "Concise paragraphs suitable for AI citation", "impact": 10}
                )

        # 7. Summary/conclusion section (+5)
        summary_keywords = [
            "in summary",
            "in conclusion",
            "to summarize",
            "key takeaway",
            "bottom line",
            "tldr",
            "tl;dr",
        ]
        if any(kw in text_lower for kw in summary_keywords):
            score += 5
            bonuses.append({"reason": "Summary/conclusion section detected", "impact": 5})

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_source_authority_score(
        cls,
        content: str,
        meta: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Source Authority, Trust and credibility signals that make AI prefer this source (25%).

        Measures: authoritative outbound links, author attribution,
        content freshness, citations/references, and professional credentials.
        """
        score = 0.0
        content_lower = content.lower()
        if not content_lower.strip():
            return score

        # 1. Authoritative outbound links, .gov, .edu, research domains (+20 / +10)
        authority_domains = re.findall(
            r'https?://[^\s"\'<>]*\.(?:gov|edu|ac\.[a-z]{2}|org)[/\s"\'<>]',
            content_lower,
        )
        scholarly_links = re.findall(
            r"https?://(?:scholar\.google|pubmed|arxiv|doi\.org|jstor|ncbi\.nlm)",
            content_lower,
        )
        auth_link_count = len(set(authority_domains)) + len(set(scholarly_links))
        if auth_link_count >= 3:
            score += 20
            bonuses.append(
                {
                    "reason": f"Strong authoritative references ({auth_link_count} links)",
                    "impact": 20,
                }
            )
        elif auth_link_count >= 1:
            score += 10
            bonuses.append(
                {"reason": f"Some authoritative references ({auth_link_count} links)", "impact": 10}
            )

        # 2. Author attribution (+15)
        author = meta.get("author") or ""
        has_author_meta = bool(author)
        has_author_byline = bool(
            re.search(r"(?:written by|author|by)\s+[A-Z][a-z]+", content, re.IGNORECASE)
        )
        if has_author_meta or has_author_byline:
            score += 15
            bonuses.append({"reason": "Author attribution present", "impact": 15})

        # 3. Content freshness, published/modified date (+15 / +8)
        pub_date = (
            meta.get("publishedTime")
            or meta.get("published_time")
            or meta.get("datePublished")
            or ""
        )
        mod_date = (
            meta.get("modifiedTime") or meta.get("modified_time") or meta.get("dateModified") or ""
        )
        if pub_date or mod_date:
            score += 15
            bonuses.append({"reason": "Published/modified date metadata present", "impact": 15})
        elif re.search(
            r"(?:published|updated|last modified|date)\s*:?\s*\w+\s+\d{1,2},?\s+\d{4}",
            content,
            re.IGNORECASE,
        ):
            score += 8
            bonuses.append({"reason": "Date reference detected in content", "impact": 8})

        # 4. Citations and references section (+15 / +8)
        has_citations = bool(
            re.search(
                r"(?:references|bibliography|sources|works cited|footnotes)\s*[:\n]", content_lower
            )
        )
        bracket_refs = len(re.findall(r"\[\d+\]", content))
        if has_citations or bracket_refs >= 3:
            score += 15
            bonuses.append({"reason": "Citations/references section detected", "impact": 15})
        elif bracket_refs >= 1:
            score += 8
            bonuses.append({"reason": "Some citation references present", "impact": 8})

        # 5. Professional credentials / expertise signals (+10)
        credential_patterns = [
            r"\b(?:Ph\.?D|M\.?D|J\.?D|MBA|CPA|PE)\b",
            r"\b(?:certified|licensed|accredited|board-certified)\b",
            r"\b(?:expert|specialist|consultant|professor|researcher)\b",
        ]
        credential_count = sum(
            1 for p in credential_patterns if re.search(p, content, re.IGNORECASE)
        )
        if credential_count >= 2:
            score += 10
            bonuses.append({"reason": "Professional credentials/expertise signals", "impact": 10})
        elif credential_count >= 1:
            score += 5
            bonuses.append({"reason": "Some expertise signals", "impact": 5})

        # 6. About/contact page references (+10)
        if re.search(r'href="[^"]*(?:about|team|contact|author)', content_lower):
            score += 10
            bonuses.append({"reason": "About/contact page linked (trust signal)", "impact": 10})

        # 7. Privacy policy / terms (+5)
        if re.search(r"(?:privacy policy|terms of service|terms of use|disclaimer)", content_lower):
            score += 5
            bonuses.append({"reason": "Legal/privacy pages present (trust signal)", "impact": 5})

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_entity_clarity_score(
        cls,
        schema: Dict[str, Any],
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Entity Clarity, Schema coverage and entity definition quality for AI comprehension (25%).

        Expands beyond local-only schema to evaluate ALL schema types relevant
        to generative engine comprehension: Organization, Product, Article, FAQ,
        HowTo, Person, etc., plus entity definition patterns in content.
        """
        score = 0.0
        detected_types = set(schema.get("detected_schema_types", []))

        # Comprehensive schema scoring, all types that help AI understand entities
        ai_relevant_schemas = {
            # Organization & brand identity
            "Organization": 15,
            "LocalBusiness": 12,
            "Corporation": 12,
            # Content types that AI engines parse well
            "Article": 15,
            "NewsArticle": 12,
            "BlogPosting": 12,
            "WebPage": 8,
            # Structured answer schemas
            "FAQPage": 15,
            "QAPage": 12,
            "HowTo": 12,
            # Product & commerce
            "Product": 12,
            "Offer": 8,
            "Review": 10,
            "AggregateRating": 8,
            # People & expertise
            "Person": 10,
            "ContactPoint": 8,
            # Place & geo
            "Place": 8,
            "PostalAddress": 5,
            "GeoCoordinates": 5,
            # Events & time-bound
            "Event": 8,
            # Lists and collections
            "ItemList": 8,
            "BreadcrumbList": 5,
        }

        schema_score = 0.0
        for schema_type, points in ai_relevant_schemas.items():
            if schema_type in detected_types:
                schema_score += points
                bonuses.append({"reason": f"{schema_type} schema present", "impact": points})

        # Also credit sub-types not explicitly listed
        for detected in detected_types:
            if detected not in ai_relevant_schemas:
                schema_score += 5
                bonuses.append({"reason": f"{detected} schema detected", "impact": 5})

        # Cap schema portion at 60 points (leaves room for content-based entity clarity)
        score += min(60.0, schema_score)

        # Content-based entity clarity (up to 40 points)
        if content:
            text = re.sub(r"<[^>]+>", " ", content)
            text = re.sub(r"\s+", " ", text).strip()

            # Entity definitions in content (+15)
            entity_defs = len(
                re.findall(
                    r"(?:is a|is an|refers to|is defined as|also known as|abbreviated as)\s",
                    text.lower(),
                )
            )
            if entity_defs >= 3:
                score += 15
                bonuses.append(
                    {"reason": f"Clear entity definitions ({entity_defs} patterns)", "impact": 15}
                )
            elif entity_defs >= 1:
                score += 8
                bonuses.append({"reason": f"Some entity definitions ({entity_defs})", "impact": 8})

            # Named entities present in content (+15)
            entities = cls._extract_entities(text)
            unique_entities = set(entities)
            if len(unique_entities) >= 8:
                score += 15
                bonuses.append(
                    {
                        "reason": f"Rich entity presence ({len(unique_entities)} unique entities)",
                        "impact": 15,
                    }
                )
            elif len(unique_entities) >= 3:
                score += 8
                bonuses.append(
                    {"reason": f"Some entities present ({len(unique_entities)})", "impact": 8}
                )

            # SameAs / identity links help AI map entities (+10)
            schema_str = str(schema).lower()
            if "sameas" in schema_str:
                score += 10
                bonuses.append(
                    {"reason": "SameAs links present (entity disambiguation)", "impact": 10}
                )

        if score == 0:
            penalties.append(
                {
                    "reason": "No schema or entity clarity signals detected",
                    "impact": -10,
                    "code": "missing_entity_schema",
                }
            )

        return min(100.0, max(0.0, score))

    # Legacy _calculate_napw_score and _calculate_spatial_content_score
    # were removed in V3.1 GEO scoring redesign (replaced by
    # content_citability, source_authority, entity_clarity).

    @classmethod
    def _calculate_brand_citation_score(
        cls,
        content: str,
        schema: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Brand & Citation Readiness, SameAs, review links, social profiles (20%)."""
        score = 0.0
        content_lower = content.lower()

        # SameAs in schema (social profiles) (+25)
        if "sameAs" in str(schema) or "sameas" in str(schema).lower():
            score += 25
            bonuses.append({"reason": "SameAs schema (social profiles) present", "impact": 25})

        # External review platforms (+25 / +15)
        review_platforms = [
            "google.com/maps",
            "trustpilot",
            "yelp",
            "tripadvisor",
            "bbb.org",
            "glassdoor",
        ]
        found_platforms = [p for p in review_platforms if p in content_lower]
        if len(found_platforms) >= 2:
            score += 25
            bonuses.append(
                {
                    "reason": f"Multiple review platforms linked ({', '.join(found_platforms)})",
                    "impact": 25,
                }
            )
        elif found_platforms:
            score += 15
            bonuses.append(
                {"reason": f"Review platform linked ({found_platforms[0]})", "impact": 15}
            )

        # Social profile links (+20 / +10)
        social_platforms = [
            "facebook.com",
            "twitter.com",
            "x.com",
            "linkedin.com",
            "instagram.com",
            "youtube.com",
        ]
        social_found = sum(1 for p in social_platforms if p in content_lower)
        if social_found >= 3:
            score += 20
            bonuses.append(
                {"reason": f"Strong social presence ({social_found} platforms)", "impact": 20}
            )
        elif social_found >= 1:
            score += 10
            bonuses.append({"reason": f"Social profile links found ({social_found})", "impact": 10})

        # Email address (+10)
        if re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", content):
            score += 10
            bonuses.append({"reason": "Email address found", "impact": 10})

        # Business hours (+10)
        if re.search(
            r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", content_lower
        ):
            score += 10
            bonuses.append({"reason": "Business hours mention", "impact": 10})

        # NAP consistency in schema (+10)
        schema_str = str(schema).lower()
        if any(k in schema_str for k in ["telephone", "address", "postalcode"]):
            score += 10
            bonuses.append({"reason": "Contact details in structured data", "impact": 10})

        return min(100.0, max(0.0, score))

    # ================================================================== #
    #  V3 AEO Sub-category Helpers
    # ================================================================== #

    @classmethod
    def _calculate_llm_schema_score(
        cls,
        schema: Dict[str, Any],
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """AI/LLM Schema Readiness, FAQPage, QAPage, HowTo, Article, ItemList (30%)."""
        detected_types = set(schema.get("detected_schema_types", []))
        coverage_percent = cls._extract_numeric(schema.get("coverage_percent"), 0.0)
        score = coverage_percent * 0.3  # Base from coverage

        aeo_schemas = {
            "FAQPage": 22,
            "QAPage": 18,
            "HowTo": 18,
            "Article": 12,
            "ItemList": 10,
            "Question": 5,
            "Answer": 5,
            "HowToStep": 5,
            "HowToSection": 3,
            "NewsArticle": 8,
            "BlogPosting": 8,
        }
        for schema_type, points in aeo_schemas.items():
            if schema_type in detected_types:
                score += points
                bonuses.append({"reason": f"{schema_type} schema present", "impact": points})

        if score < 10 and not detected_types:
            penalties.append(
                {
                    "reason": "No AEO-relevant schema detected",
                    "impact": -15,
                    "code": "missing_aeo_schema",
                }
            )

        return min(100.0, max(0.0, score))

    # ------------------------------------------------------------------ #
    #  Named entity extraction helpers (AEX-08)
    # ------------------------------------------------------------------ #

    # Stop words that frequently begin capitalized phrases at sentence start
    # but are NOT named entities. Includes common adjectives and verbs.
    _ENTITY_STOP_STARTS = frozenset(
        {
            # Articles and determiners
            "the",
            "a",
            "an",
            "this",
            "that",
            "these",
            "those",
            # Common verbs (present/past/gerund)
            "is",
            "are",
            "was",
            "were",
            "has",
            "have",
            "had",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "do",
            "does",
            "did",
            "can",
            "be",
            "been",
            "being",
            "get",
            "got",
            "let",
            "make",
            "take",
            "come",
            "go",
            "see",
            "read",
            "find",
            "use",
            "using",
            "include",
            "includes",
            "including",
            "need",
            "keep",
            "ensure",
            "learn",
            "check",
            "try",
            "run",
            "set",
            "add",
            "give",
            "start",
            "stop",
            "help",
            "want",
            "know",
            "think",
            "look",
            "show",
            "turn",
            "call",
            "ask",
            "tell",
            "follow",
            "create",
            "build",
            "work",
            "provide",
            "develop",
            "developed",
            "understand",
            "consider",
            # Pronouns
            "it",
            "its",
            "my",
            "our",
            "your",
            "their",
            "his",
            "her",
            "we",
            "they",
            "you",
            "he",
            "she",
            # Quantifiers/determiners
            "some",
            "many",
            "most",
            "all",
            "any",
            "each",
            "every",
            "both",
            "few",
            "more",
            "other",
            "such",
            "no",
            "not",
            "only",
            "very",
            # Common adjectives that start sentences
            "best",
            "main",
            "key",
            "top",
            "big",
            "new",
            "old",
            "good",
            "great",
            "first",
            "last",
            "next",
            "quick",
            "important",
            "comprehensive",
            "complete",
            "full",
            "latest",
            "recent",
            "current",
            "modern",
            "simple",
            "basic",
            "advanced",
            "general",
            "specific",
            "common",
            "popular",
            "essential",
            "critical",
            "major",
            "primary",
            "strong",
            "clear",
            "final",
            "overall",
            "total",
            "real",
            "true",
            "open",
            "plan_starter",
            "high",
            "low",
            "long",
            "short",
            "different",
            "similar",
            "additional",
            "beautiful",
            "effective",
            "successful",
            "significant",
            # Adverbs/conjunctions/prepositions
            "if",
            "when",
            "while",
            "where",
            "how",
            "what",
            "which",
            "who",
            "why",
            "here",
            "there",
            "now",
            "then",
            "also",
            "just",
            "still",
            "even",
            "much",
            "well",
            "too",
            "yet",
            "already",
            "ever",
            "never",
            "always",
            "often",
            "however",
            "therefore",
            "thus",
            "hence",
            "so",
            "but",
            "and",
            "or",
            "nor",
            "for",
            "yet",
            "after",
            "before",
            "since",
            "until",
            "although",
            "because",
            "unless",
            "whether",
            "in",
            "on",
            "at",
            "to",
            "from",
            "with",
            "about",
            "over",
            "under",
            "between",
            "through",
            "into",
            "during",
        }
    )

    # Common non-entity multi-word phrases that happen to be capitalized
    _ENTITY_STOP_PHRASES = frozenset(
        {
            "read more",
            "learn more",
            "click here",
            "sign up",
            "log in",
            "see also",
            "in this article",
            "table of contents",
            "get started",
            "find out",
            "view all",
            "show more",
            "next steps",
            "key takeaways",
            "main points",
            "quick summary",
            "related articles",
            "featured image",
            "share this",
        }
    )

    # Multi-word capitalized entities: "Google Search Console", "New York City"
    # Uses [ \t]+ (not \s+) to avoid matching across line breaks.
    # Connectors limited to prepositions that appear INSIDE entity names (of, the)
    # Deliberately excludes "and", "for", "in" which typically join separate entities
    _MULTI_WORD_ENTITY_RE = re.compile(
        r"\b([A-Z][a-z]+(?:[ \t]+(?:[A-Z][a-z]+|&|of|the|de|la|le|von|van|der|al|el))*(?:[ \t]+[A-Z][a-z]+)+)\b"
    )

    # Single-word proper nouns: well-known standalone entities (min 2 chars, not ALL-CAPS short words)
    _SINGLE_PROPER_RE = re.compile(r"(?<![.\w])([A-Z][a-z]{2,})(?!\w)")

    # Acronyms and all-caps entities: "NASA", "IBM", "GDPR" (2-6 uppercase letters)
    _ACRONYM_RE = re.compile(r"\b([A-Z]{2,6})\b")

    # Common all-caps words that are NOT entities
    _ACRONYM_STOP = frozenset(
        {
            "THE",
            "AND",
            "FOR",
            "NOT",
            "BUT",
            "ARE",
            "WAS",
            "HAS",
            "HAD",
            "GET",
            "SET",
            "PUT",
            "ALL",
            "ANY",
            "CAN",
            "MAY",
            "LET",
            "USE",
            "NEW",
            "OLD",
            "BIG",
            "SEE",
            "NOW",
            "HOW",
            "WHO",
            "WHY",
            "OUR",
            "YOU",
            "HIS",
            "HER",
            "ITS",
            "CSS",
            "HTML",
            "HTTP",
            "URL",
            "API",
            "FAQ",
            "TBD",
            "ETC",
            "PDF",
            "RSS",
            "XML",
            "JSON",
            "SQL",
            "PHP",
            "TOS",
            "DIV",
            "IMG",
            "ALT",
            "SRC",
            "USD",
            "EUR",
            "GBP",
        }
    )

    @classmethod
    def _extract_entities(cls, text: str) -> List[str]:
        """Extract named entities from plain text using improved heuristics.

        Uses three regex passes (multi-word, acronym, single-word proper nouns)
        plus stop-phrase filtering to reduce false positives from sentence-start
        capitalization and common non-entity phrases.

        Returns a list of detected entity strings (may contain duplicates).
        """
        if not text:
            return []

        entities: List[str] = []

        # Pass 1: Multi-word capitalized sequences
        for match in cls._MULTI_WORD_ENTITY_RE.finditer(text):
            candidate = match.group(1).strip()

            # Strip leading stop words (handles sentence-start caps like "Use Google...")
            words = candidate.split()
            while words and words[0].lower() in cls._ENTITY_STOP_STARTS:
                words = words[1:]
            if len(words) < 2:
                continue
            candidate = " ".join(words)

            # Filter: full phrase (lowered) must not be a stop phrase
            if candidate.lower() in cls._ENTITY_STOP_PHRASES:
                continue
            # Must have at least 2 content words (exclude short articles/preps)
            content_words = [
                w
                for w in candidate.split()
                if len(w) > 2
                and w.lower()
                not in {"the", "of", "de", "la", "le", "von", "van", "der", "al", "el"}
            ]
            if len(content_words) >= 2:
                entities.append(candidate)

        # Pass 2: Acronyms (2-6 uppercase letters)
        for match in cls._ACRONYM_RE.finditer(text):
            acronym = match.group(1)
            if acronym not in cls._ACRONYM_STOP:
                entities.append(acronym)

        # Pass 3: Single-word proper nouns, only count words that appear
        # mid-sentence (preceded by lowercase or punctuation, not at sentence start)
        sentences = re.split(r"[.!?]\s+", text)
        for sentence in sentences:
            words_in_sentence = sentence.split()
            # Skip the first word of each sentence (likely capitalized naturally)
            for word in words_in_sentence[1:]:
                m = cls._SINGLE_PROPER_RE.match(word)
                if m:
                    proper = m.group(1)
                    if proper.lower() not in cls._ENTITY_STOP_STARTS:
                        entities.append(proper)

        return entities

    @classmethod
    def _calculate_semantic_entity_score(
        cls,
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Semantic & Entity Density, named entity extraction, semantic clustering (25%)."""
        score = 0.0
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return score

        words = text.split()
        word_count = len(words)

        # Minimum content threshold (+5)
        if word_count >= 100:
            score += 5
            bonuses.append(
                {"reason": f"Sufficient content length ({word_count} words)", "impact": 5}
            )

        # Named entity detection with improved heuristics (AEX-08) (+30 / +20 / +10)
        entities = cls._extract_entities(text)
        unique_entities = set(entities)
        if len(unique_entities) >= 10:
            score += 30
            bonuses.append(
                {
                    "reason": f"Rich entity density ({len(unique_entities)} unique entities)",
                    "impact": 30,
                }
            )
        elif len(unique_entities) >= 5:
            score += 20
            bonuses.append(
                {"reason": f"Good entity density ({len(unique_entities)} entities)", "impact": 20}
            )
        elif len(unique_entities) >= 2:
            score += 10
            bonuses.append(
                {"reason": f"Some entities detected ({len(unique_entities)})", "impact": 10}
            )

        # Semantic keyword clustering (unique meaningful words ratio) (+25 / +12)
        if word_count >= 100:
            unique_words = set(w.lower() for w in words if len(w) > 3)
            diversity = len(unique_words) / word_count
            if diversity >= 0.4:
                score += 25
                bonuses.append(
                    {"reason": f"High vocabulary diversity ({diversity:.0%})", "impact": 25}
                )
            elif diversity >= 0.25:
                score += 12
                bonuses.append(
                    {"reason": f"Moderate vocabulary diversity ({diversity:.0%})", "impact": 12}
                )
            else:
                penalties.append(
                    {
                        "reason": "Low vocabulary diversity",
                        "impact": -10,
                        "code": "low_vocabulary_diversity",
                    }
                )

        # Topic sentence markers (+15)
        topic_markers = re.findall(r"(?:(?:is|are|refers to|means|defined as)\s)", text.lower())
        if len(topic_markers) >= 3:
            score += 15
            bonuses.append({"reason": "Strong topic sentence markers", "impact": 15})
        elif len(topic_markers) >= 1:
            score += 8
            bonuses.append({"reason": "Topic sentence markers present", "impact": 8})

        # Definition patterns (+10)
        if re.search(r"(?:is defined as|refers to|is a type of|also known as)", text.lower()):
            score += 10
            bonuses.append({"reason": "Definition patterns detected", "impact": 10})

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_information_gain_score(
        cls,
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Information Gain & Readability, Flesch-Kincaid, sentence variety, passive voice, boilerplate (25%)."""
        score = 0.0
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return score

        sentences = re.split(r"[.!?]+", text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
        if not sentences:
            return score

        # Flesch-Kincaid approximation (+25 / +15 / +8)
        total_words = sum(len(s.split()) for s in sentences)
        total_syllables = sum(cls._count_syllables(w) for s in sentences for w in s.split())
        avg_sentence_len = total_words / len(sentences)
        avg_syllables_per_word = total_syllables / total_words if total_words else 2

        fk_grade = 0.39 * avg_sentence_len + 11.8 * avg_syllables_per_word - 15.59
        # Target: grade 6-10 for web content
        if 6 <= fk_grade <= 10:
            score += 25
            bonuses.append(
                {
                    "reason": f"Optimal readability (Flesch-Kincaid grade {fk_grade:.1f})",
                    "impact": 25,
                }
            )
        elif 4 <= fk_grade <= 12:
            score += 15
            bonuses.append({"reason": f"Good readability (FK grade {fk_grade:.1f})", "impact": 15})
        elif fk_grade > 14:
            penalties.append(
                {
                    "reason": f"Content too complex (FK grade {fk_grade:.1f})",
                    "impact": -10,
                    "code": "content_too_complex",
                }
            )
        else:
            score += 8

        # Sentence variety (+25 / +12)
        first_words = [s.split()[0].lower() for s in sentences if s.split()]
        unique_starters = len(set(first_words))
        variety = unique_starters / len(first_words) if first_words else 0
        if variety > 0.7:
            score += 25
            bonuses.append({"reason": "Excellent sentence variety", "impact": 25})
        elif variety > 0.5:
            score += 12
            bonuses.append({"reason": "Good sentence variety", "impact": 12})

        # Passive voice detection (+15 / -10)
        passive_matches = len(
            re.findall(
                r"\b(?:is|are|was|were|been|being)\s+(?:\w+ed|built|done|gone|made|seen|taken)\b",
                text,
                re.IGNORECASE,
            )
        )
        passive_ratio = passive_matches / len(sentences) if sentences else 0
        if passive_ratio > 0.3:
            score -= 10
            penalties.append(
                {
                    "reason": f"High passive voice usage ({passive_ratio:.0%})",
                    "impact": -10,
                    "code": "high_passive_voice",
                }
            )
        elif passive_ratio < 0.1:
            score += 15
            bonuses.append({"reason": "Active voice predominant", "impact": 15})

        # Boilerplate / fluff detection (+10 / -8)
        fluff_phrases = [
            "as you know",
            "it goes without saying",
            "needless to say",
            "in this article",
            "in this blog post",
            "as mentioned above",
            "without further ado",
            "at the end of the day",
        ]
        fluff_count = sum(1 for phrase in fluff_phrases if phrase in text.lower())
        if fluff_count >= 3:
            score -= 8
            penalties.append(
                {
                    "reason": f"Boilerplate language detected ({fluff_count} phrases)",
                    "impact": -8,
                    "code": "boilerplate_language",
                }
            )
        elif fluff_count == 0 and total_words > 200:
            score += 10
            bonuses.append({"reason": "No boilerplate filler language", "impact": 10})

        # Content depth, adequate word count (+10)
        if total_words >= 500:
            score += 10
            bonuses.append({"reason": f"Good content depth ({total_words} words)", "impact": 10})
        elif total_words >= 200:
            score += 5

        return min(100.0, max(0.0, score))

    @classmethod
    def _calculate_snippet_formatting_score(
        cls,
        content: str,
        penalties: List[Dict[str, Any]],
        bonuses: List[Dict[str, Any]],
    ) -> float:
        """Snippet & LLM Formatting, Q→A density, tables, lists, definitions (20%)."""
        score = 0.0
        content_lower = content.lower()
        fmt = cls._detect_content_format(content)

        # Direct Q→A patterns (+25 / +12)
        qa_count = cls._count_qa_patterns(content, fmt)
        if qa_count >= 3:
            score += 25
            bonuses.append({"reason": f"Strong Q&A format ({qa_count} patterns)", "impact": 25})
        elif qa_count >= 1:
            score += 12
            bonuses.append({"reason": f"Q&A format detected ({qa_count})", "impact": 12})

        # Tables (+20 / +10)
        table_count = cls._count_tables(content, fmt)
        if table_count >= 2:
            score += 20
            bonuses.append({"reason": f"Data tables present ({table_count})", "impact": 20})
        elif table_count == 1:
            score += 10
            bonuses.append({"reason": "Data table present", "impact": 10})

        # Bulleted / numbered lists (+20 / +10)
        list_count = cls._count_lists(content, fmt)
        if list_count >= 3:
            score += 20
            bonuses.append({"reason": f"Rich list formatting ({list_count} lists)", "impact": 20})
        elif list_count >= 1:
            score += 10
            bonuses.append({"reason": "Structured lists present", "impact": 10})

        # Definition markup (+15)
        if cls._has_definition_markup(content, fmt):
            score += 15
            bonuses.append({"reason": "Definition list markup present", "impact": 15})

        # Short concise paragraphs (+15 / +8)
        paragraphs = cls._extract_paragraphs(content, fmt)
        concise = [p for p in paragraphs if 10 <= len(p.split()) <= 50]
        if len(concise) >= 5:
            score += 15
            bonuses.append({"reason": f"{len(concise)} concise answer paragraphs", "impact": 15})
        elif concise:
            score += 8
            bonuses.append({"reason": "Some concise paragraphs present", "impact": 8})

        # Summary / TL;DR pattern (+5)
        if re.search(r"(?:summary|tl;?dr|key takeaway|in brief)", content_lower):
            score += 5
            bonuses.append({"reason": "Summary/takeaway pattern detected", "impact": 5})

        return min(100.0, max(0.0, score))

    # ================================================================== #
    #  Shared utility helpers
    # ================================================================== #

    # Common business name suffixes to strip for fuzzy matching
    _BRAND_SUFFIXES = re.compile(
        r"\s*[,.]?\s*(?:inc|llc|ltd|co|corp|corporation|company|group|"
        r"gmbh|ag|sa|s\.?a\.?|s\.?r\.?l\.?|plc|pty|b\.?v\.?)\.?\s*$",
        re.IGNORECASE,
    )

    @classmethod
    def _match_brand_name(
        cls,
        title: str,
        brand_name: str,
        meta: Dict[str, Any],
    ) -> str:
        """Check if a page title contains the brand/business name.

        Returns the matched brand string, or empty string if no match.
        Strategy:
          1. If explicit brand_name given → check title contains it (fuzzy, suffix-stripped).
          2. Else extract brand token from URL domain and check title.
          3. Never match generic titles like "Login", "Home", "Page".
        """
        title_lower = title.strip().lower()
        if not title_lower or len(title_lower) < 3:
            return ""

        # 1. Explicit brand name matching
        if brand_name and len(brand_name.strip()) >= 2:
            brand_clean = brand_name.strip()
            # First try full brand name (case-insensitive)
            if brand_clean.lower() in title_lower:
                return brand_clean
            # Then try with suffix stripped (Inc, LLC, Ltd, Corp, etc.)
            core_brand = cls._BRAND_SUFFIXES.sub("", brand_clean).strip()
            if core_brand and len(core_brand) >= 2 and core_brand.lower() != brand_clean.lower():
                if core_brand.lower() in title_lower:
                    return core_brand
                # Try each word of multi-word brand (minimum 3 chars to avoid false positives)
                brand_words = [w for w in core_brand.split() if len(w) >= 3]
                if brand_words and all(w.lower() in title_lower for w in brand_words):
                    return core_brand

        # 2. Domain-derived brand matching
        url = meta.get("url") or ""
        domain_brand = cls._extract_brand_from_url(url)
        if domain_brand and len(domain_brand) >= 3:
            if domain_brand.lower() in title_lower:
                return domain_brand

        return ""

    @classmethod
    def _extract_brand_from_url(cls, url: str) -> str:
        """Extract a candidate brand token from a URL's domain.

        e.g. "https://www.acme-corp.com/page" → "acme corp"
        """
        if not url:
            return ""
        # Strip protocol and path
        domain = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
        domain = domain.split("/")[0].split("?")[0]
        # Remove port
        domain = domain.split(":")[0]
        # Remove TLD and www
        parts = domain.split(".")
        parts = [
            p
            for p in parts
            if p.lower()
            not in ("www", "com", "org", "net", "io", "co", "uk", "de", "fr", "eu", "app", "dev")
        ]
        if not parts:
            return ""
        # Take the main domain part (usually the first non-www part)
        brand = parts[0]
        # Convert hyphens/underscores to spaces
        brand = brand.replace("-", " ").replace("_", " ")
        return brand

    @classmethod
    def _extract_numeric(cls, value: Any, default: float = 0.0) -> float:
        """Safely extract numeric value."""
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _parse_timing_value(cls, value: Any) -> float:
        """Parse timing values like '2.3 s' or '2300 ms' to milliseconds."""
        if value is None or value == "N/A":
            return -1
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).lower().strip()
        match = re.search(r"([\d.]+)\s*(s|ms)?", text)
        if not match:
            return -1
        num = float(match.group(1))
        unit = match.group(2) or "ms"
        return num * 1000 if unit == "s" else num

    @classmethod
    def _parse_cls_value(cls, value: Any) -> float:
        """Parse CLS value."""
        if value is None or value == "N/A":
            return -1
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(str(value).strip())
        except ValueError:
            return -1

    @classmethod
    def _count_syllables(cls, word: str) -> int:
        """Approximate syllable count for readability calculations."""
        word = word.lower().strip(".,!?;:\"'")
        if not word:
            return 1
        count = len(re.findall(r"[aeiouy]+", word))
        if word.endswith("e") and count > 1:
            count -= 1
        return max(1, count)

    @classmethod
    def _finding_title(cls, description: str, *, max_len: int = 90) -> str:
        """Derive a short card headline from a finding's full description.

        Findings from the AI experts (report_schema._FINDING_ITEM_JSON_SCHEMA)
        only carry `description`, not a separate title. Prefer the first
        sentence; fall back to a word-boundary truncation.
        """
        text = (description or "").strip()
        if not text:
            return "Untitled finding"
        match = re.match(r"^(.{1,%d}?[.!?])(\s|$)" % max_len, text)
        if match:
            return match.group(1).strip()
        if len(text) <= max_len:
            return text
        truncated = text[:max_len].rsplit(" ", 1)[0].strip()
        return f"{truncated}\u2026" if truncated else f"{text[:max_len].strip()}\u2026"

    @classmethod
    def _findings_to_penalty_entries(
        cls, findings: List[Dict[str, Any]], *, category_fallback: str
    ) -> List[Dict[str, Any]]:
        """Convert individual AI findings into one penalty entry per finding.

        Previously every finding was collapsed into a single opaque
        "AI-detected issues (N findings)" bucket used only for score math,
        which discarded the model's real description/rationale before it
        ever reached the report UI. This mirrors the same tiered point scale
        as `_calculate_findings_penalty` for the per-item impact shown on
        each card, so the *sum* of displayed impacts tracks the aggregate
        deduction (modulo the shared `FINDINGS_PENALTY_CAP`, which still
        bounds the actual score change computed separately).
        """
        entries: List[Dict[str, Any]] = []
        critical_index = 0
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            severity = str(finding.get("severity", "")).lower().strip()
            description = str(finding.get("description", "")).strip()
            if not description or severity not in ("critical", "warning"):
                continue

            if severity == "critical":
                critical_index += 1
                if critical_index <= 3:
                    impact = cls.CRITICAL_PENALTY * 0.5
                elif critical_index <= 6:
                    impact = cls.CRITICAL_PENALTY * 0.333
                else:
                    impact = cls.CRITICAL_PENALTY * 0.133
            else:
                impact = cls.WARNING_PENALTY * 0.5

            confidence = finding.get("confidence")
            estimated_effort = finding.get("estimated_effort")
            entries.append(
                {
                    "reason": cls._finding_title(description),
                    "impact": -round(impact, 1),
                    "description": description,
                    "severity": severity,
                    "category": str(finding.get("category") or category_fallback).strip()
                    or category_fallback,
                    "rationale": str(finding.get("rationale") or "").strip() or None,
                    "confidence": confidence if isinstance(confidence, (int, float)) else None,
                    "estimated_effort": estimated_effort
                    if estimated_effort in ("low", "medium", "high")
                    else None,
                    "source": "ai_finding",
                }
            )
        return entries

    @classmethod
    def _calculate_findings_penalty(cls, findings: List[Dict[str, Any]]) -> float:
        """Calculate penalty from AI findings with tiered diminishing returns (AEX-10).

        Tiered scaling prevents runaway penalties from model variance while
        allowing severe issues to meaningfully impact the score:
          - Critical findings 1-3: 7.5 each (full penalty)
          - Critical findings 4-6: 5.0 each (diminishing)
          - Critical findings 7+:  2.0 each (minimal additional)
          - Warnings: 2.5 each (unchanged)
        Cap: FINDINGS_PENALTY_CAP = 45
        """
        critical_count = 0
        warning_count = 0
        for finding in findings:
            severity = str(finding.get("severity", "")).lower().strip()
            if severity == "critical":
                critical_count += 1
            elif severity == "warning":
                warning_count += 1

        penalty = 0.0
        # Tiered critical penalties
        for i in range(1, critical_count + 1):
            if i <= 3:
                penalty += cls.CRITICAL_PENALTY * 0.5  # 7.5 per finding
            elif i <= 6:
                penalty += cls.CRITICAL_PENALTY * 0.333  # ~5.0 per finding
            else:
                penalty += cls.CRITICAL_PENALTY * 0.133  # ~2.0 per finding

        # Warning penalties (flat rate)
        penalty += warning_count * cls.WARNING_PENALTY * 0.5  # 2.5 per warning

        return min(cls.FINDINGS_PENALTY_CAP, penalty)


# ====================================================================== #
#  Public convenience functions (backward compatible)
# ====================================================================== #


def extract_score(analysis: dict, key: str) -> float:
    """Legacy extractor, kept for backward compatibility."""
    value = analysis.get(key, {})
    if isinstance(value, dict):
        return float(value.get("score", 0) or 0)
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


# ------------------------------------------------------------------ #
#  Brand signal scoring boost for brand audits
# ------------------------------------------------------------------ #

# Weight mapping: how each brand signal contributes to each dimension.
# SEO cares most about SERP presence, GEO about KG + Wikidata, AEO about AI visibility.
_BRAND_SIGNAL_WEIGHTS: Dict[str, Dict[str, float]] = {
    "seo": {"serp": 0.45, "kg": 0.25, "wiki": 0.15, "ai_vis": 0.15},
    "geo": {"serp": 0.20, "kg": 0.35, "wiki": 0.30, "ai_vis": 0.15},
    "aeo": {"serp": 0.15, "kg": 0.20, "wiki": 0.20, "ai_vis": 0.45},
}


# Blend ratios for brand signal boost (AEX-09).
# When brand signals exceed the base deterministic score, we blend rather
# than replace so that poor website quality still pulls the score down.
BRAND_SIGNAL_WEIGHT = 0.70
BRAND_BASE_WEIGHT = 0.30


def _apply_brand_signal_boost(
    breakdown: ScoreBreakdown,
    *,
    dimension: str,
    serp_score: float,
    kg_score: float,
    wiki_score: float,
    ai_vis_score: float,
) -> ScoreBreakdown:
    """Boost a low deterministic breakdown using brand signal scores.

    When a brand audit has no scraped page content, the normal deterministic
    scoring produces very low scores.  This function blends the base
    deterministic score with an external brand signal score (70/30 weighted
    blend) so that poor website quality still drags the result down rather
    than being entirely replaced.
    """
    weights = _BRAND_SIGNAL_WEIGHTS.get(dimension, _BRAND_SIGNAL_WEIGHTS["seo"])

    # Normalize signal scores to 0-100 scale
    raw_signals = {
        "serp": min(100.0, (serp_score / 30.0) * 100.0) if serp_score else 0.0,
        "kg": min(100.0, (kg_score / 25.0) * 100.0) if kg_score else 0.0,
        "wiki": min(100.0, (wiki_score / 25.0) * 100.0) if wiki_score else 0.0,
        "ai_vis": min(100.0, (ai_vis_score / 20.0) * 100.0) if ai_vis_score else 0.0,
    }

    brand_score = sum(raw_signals[key] * weight for key, weight in weights.items())
    brand_score = round(min(100.0, max(0.0, brand_score)), 1)

    # Only boost if brand signals provide a higher score than the base
    if brand_score <= breakdown.total_score:
        return breakdown

    # Weighted blend instead of max (AEX-09): brand 70% + base 30%
    blended_score = round(
        BRAND_BASE_WEIGHT * breakdown.total_score + BRAND_SIGNAL_WEIGHT * brand_score, 1
    )
    blended_score = min(100.0, max(0.0, blended_score))

    components = dict(breakdown.components)
    components["brand_serp_presence"] = round(raw_signals["serp"] * weights["serp"], 1)
    components["brand_knowledge_graph"] = round(raw_signals["kg"] * weights["kg"], 1)
    components["brand_wikidata"] = round(raw_signals["wiki"] * weights["wiki"], 1)
    components["brand_ai_visibility"] = round(raw_signals["ai_vis"] * weights["ai_vis"], 1)

    bonuses = list(breakdown.bonuses)
    bonuses.append(
        {
            "name": "brand_signal_boost",
            "value": round(blended_score - breakdown.total_score, 1),
            "reason": "Score supplemented by external brand presence signals (70/30 blend)",
        }
    )

    return ScoreBreakdown(
        total_score=blended_score,
        components=components,
        penalties=list(breakdown.penalties),
        bonuses=bonuses,
        metadata={
            **breakdown.metadata,
            "brand_signal_boosted": True,
            "base_deterministic_score": breakdown.total_score,
            "brand_signal_score": brand_score,
            "blend_ratio": {"brand": BRAND_SIGNAL_WEIGHT, "base": BRAND_BASE_WEIGHT},
        },
    )


# ------------------------------------------------------------------ #
#  AI findings score floor for brand-no-URL audits
# ------------------------------------------------------------------ #

# When a brand audit has no URL and brand signal collection returns zero
# signals, the deterministic engine produces near-zero scores.  However, the
# AI analysis may still generate meaningful findings and recommendations.
# This function establishes a minimum score floor (12-35 range) derived from
# AI analysis quality so that well-known brands that simply lack external
# signal coverage still receive a reasonable baseline score.

_AI_FLOOR_DIMENSION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "seo": {"own_findings": 0.50, "cross_findings": 0.20, "summary_quality": 0.30},
    "geo": {"own_findings": 0.50, "cross_findings": 0.20, "summary_quality": 0.30},
    "aeo": {"own_findings": 0.50, "cross_findings": 0.20, "summary_quality": 0.30},
}

AI_FLOOR_MIN = 12.0
AI_FLOOR_MAX = 35.0


def _apply_ai_findings_floor(
    breakdown: ScoreBreakdown,
    *,
    dimension: str,
    own_findings_count: int,
    cross_findings_count: int,
    summary_length: int,
    recommendations_count: int,
) -> ScoreBreakdown:
    """Establish a minimum score floor from AI analysis quality.

    For brand-no-URL audits where both deterministic scoring and brand signal
    collection produce near-zero scores, the AI may still have generated
    meaningful analysis.  This function derives a floor score (12-35 range)
    from the AI findings so that the report does not show all-zeros when
    analysis was actually performed.

    Only applies when the existing total_score is below AI_FLOOR_MIN.
    """
    if breakdown.total_score >= AI_FLOOR_MIN:
        return breakdown

    weights = _AI_FLOOR_DIMENSION_WEIGHTS.get(dimension, _AI_FLOOR_DIMENSION_WEIGHTS["seo"])

    # own_findings score: 0-100 based on finding count (0->0, 1->30, 3->60, 5+->100)
    own_score = min(100.0, own_findings_count * 20.0) if own_findings_count > 0 else 0.0

    # cross_findings score: other dimension findings indicate broader AI analysis ran
    cross_score = min(100.0, cross_findings_count * 15.0) if cross_findings_count > 0 else 0.0

    # summary_quality: derived from AI summary length + recommendation count
    summary_score = 0.0
    if summary_length > 50:
        summary_score += min(50.0, summary_length / 10.0)
    if recommendations_count > 0:
        summary_score += min(50.0, recommendations_count * 12.5)
    summary_score = min(100.0, summary_score)

    raw_floor = (
        own_score * weights["own_findings"]
        + cross_score * weights["cross_findings"]
        + summary_score * weights["summary_quality"]
    )

    # Scale raw 0-100 into the AI_FLOOR_MIN..AI_FLOOR_MAX range
    floor_score = AI_FLOOR_MIN + (raw_floor / 100.0) * (AI_FLOOR_MAX - AI_FLOOR_MIN)
    floor_score = round(min(AI_FLOOR_MAX, max(AI_FLOOR_MIN, floor_score)), 1)

    if floor_score <= breakdown.total_score:
        return breakdown

    bonuses = list(breakdown.bonuses)
    bonuses.append(
        {
            "name": "ai_findings_floor",
            "value": round(floor_score - breakdown.total_score, 1),
            "reason": (
                f"Score floor from AI analysis quality "
                f"({own_findings_count} own findings, "
                f"{cross_findings_count} cross findings, "
                f"{recommendations_count} recommendations)"
            ),
        }
    )

    return ScoreBreakdown(
        total_score=floor_score,
        components=dict(breakdown.components),
        penalties=list(breakdown.penalties),
        bonuses=bonuses,
        metadata={
            **breakdown.metadata,
            "ai_findings_floor_applied": True,
            "base_score_before_floor": breakdown.total_score,
            "floor_score": floor_score,
        },
    )


def calculate_deterministic_scores(
    *,
    performance_metrics: Optional[Dict[str, Any]] = None,
    schema_analysis: Optional[Dict[str, Any]] = None,
    scrape_metadata: Optional[Dict[str, Any]] = None,
    network_data: Optional[Dict[str, Any]] = None,
    content: Optional[str] = None,
    seo_findings: Optional[List[Dict[str, Any]]] = None,
    geo_findings: Optional[List[Dict[str, Any]]] = None,
    aeo_findings: Optional[List[Dict[str, Any]]] = None,
    brand_signals: Optional[Dict[str, Any]] = None,
    brand_name: Optional[str] = None,
    page_type: Optional[str] = None,
    scrape_succeeded: Optional[bool] = None,
    ai_findings_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Convenience function to calculate all deterministic scores at once.

    Returns a dictionary with scores and breakdowns for SEO, GEO, AEO, and overall.

    When ``scrape_succeeded`` is explicitly False (or auto-detected as False),
    content-dependent scoring sub-categories are set to 0 without penalties
    instead of penalising the page for missing HTML tags that were never fetched.

    When ``brand_signals`` is provided (brand audits without URL), the scoring
    engine uses external signal data to produce grounded scores instead of
    returning near-zero values.

    When ``page_type`` is provided, dimension relevance weights are applied:
    irrelevant dimensions (weight 0.0) are marked N/A and excluded from the
    overall score calculation.
    """
    # Auto-detect scrape success when not explicitly provided
    if scrape_succeeded is None:
        _meta = scrape_metadata or {}
        _has_scrape_meta = any(
            _meta.get(k)
            for k in ("title", "canonical", "viewport", "description", "meta_description")
        )
        scrape_succeeded = _has_scrape_meta or bool(content and content.strip())

    engine = DeterministicScoringEngine

    seo_breakdown = engine.calculate_seo_score(
        performance_metrics=performance_metrics,
        scrape_metadata=scrape_metadata,
        network_data=network_data,
        content=content,
        findings=seo_findings,
        scrape_succeeded=scrape_succeeded,
    )

    geo_breakdown = engine.calculate_geo_score(
        schema_analysis=schema_analysis,
        scrape_metadata=scrape_metadata,
        content=content,
        findings=geo_findings,
        brand_name=brand_name,
        scrape_succeeded=scrape_succeeded,
    )

    aeo_breakdown = engine.calculate_aeo_score(
        schema_analysis=schema_analysis,
        scrape_metadata=scrape_metadata,
        content=content,
        findings=aeo_findings,
        scrape_succeeded=scrape_succeeded,
    )

    # For brand audits with signals, supplement near-zero deterministic scores
    if brand_signals and isinstance(brand_signals, dict):
        summary = (
            brand_signals.get("summary") if isinstance(brand_signals.get("summary"), dict) else {}
        )
        components = (
            summary.get("score_components")
            if isinstance(summary.get("score_components"), dict)
            else {}
        )
        signals_collected = summary.get("signals_collected", 0)

        if signals_collected > 0:
            seo_breakdown = _apply_brand_signal_boost(
                seo_breakdown,
                dimension="seo",
                serp_score=components.get("serp_presence", 0),
                kg_score=components.get("knowledge_graph", 0),
                wiki_score=components.get("wikidata_presence", 0),
                ai_vis_score=components.get("ai_visibility", 0),
            )
            geo_breakdown = _apply_brand_signal_boost(
                geo_breakdown,
                dimension="geo",
                serp_score=components.get("serp_presence", 0),
                kg_score=components.get("knowledge_graph", 0),
                wiki_score=components.get("wikidata_presence", 0),
                ai_vis_score=components.get("ai_visibility", 0),
            )
            aeo_breakdown = _apply_brand_signal_boost(
                aeo_breakdown,
                dimension="aeo",
                serp_score=components.get("serp_presence", 0),
                kg_score=components.get("knowledge_graph", 0),
                wiki_score=components.get("wikidata_presence", 0),
                ai_vis_score=components.get("ai_visibility", 0),
            )

    # ── AI findings floor for brand-no-URL (when both base + signals are low)
    if ai_findings_meta and isinstance(ai_findings_meta, dict):
        _seo_fc = ai_findings_meta.get("seo_findings_count", 0)
        _geo_fc = ai_findings_meta.get("geo_findings_count", 0)
        _aeo_fc = ai_findings_meta.get("aeo_findings_count", 0)
        _total_cross = _seo_fc + _geo_fc + _aeo_fc
        _summary_len = ai_findings_meta.get("summary_length", 0)
        _rec_count = ai_findings_meta.get("recommendations_count", 0)

        seo_breakdown = _apply_ai_findings_floor(
            seo_breakdown,
            dimension="seo",
            own_findings_count=_seo_fc,
            cross_findings_count=_total_cross - _seo_fc,
            summary_length=_summary_len,
            recommendations_count=_rec_count,
        )
        geo_breakdown = _apply_ai_findings_floor(
            geo_breakdown,
            dimension="geo",
            own_findings_count=_geo_fc,
            cross_findings_count=_total_cross - _geo_fc,
            summary_length=_summary_len,
            recommendations_count=_rec_count,
        )
        aeo_breakdown = _apply_ai_findings_floor(
            aeo_breakdown,
            dimension="aeo",
            own_findings_count=_aeo_fc,
            cross_findings_count=_total_cross - _aeo_fc,
            summary_length=_summary_len,
            recommendations_count=_rec_count,
        )

    # ── Page-type dimension relevance (AEX-06) ──────────────────────────
    relevance: Dict[str, float] = {"seo": 1.0, "geo": 1.0, "aeo": 1.0}
    na_dimensions: List[str] = []

    if page_type:
        try:
            from services.page_type_detector import get_dimension_relevance

            relevance = get_dimension_relevance(page_type)
        except ImportError:
            pass  # graceful fallback, full weights

        for dim in ("seo", "geo", "aeo"):
            if relevance.get(dim, 1.0) == 0.0:
                na_dimensions.append(dim)

    # Build overall score with relevance-adjusted weights
    # Default weights: SEO 40%, AEO 30%, GEO 30%
    base_weights = {"seo": 0.4, "geo": 0.3, "aeo": 0.3}
    adjusted_weights = {dim: base_weights[dim] * relevance.get(dim, 1.0) for dim in base_weights}
    raw_scores = {
        "seo": seo_breakdown.total_score,
        "geo": geo_breakdown.total_score,
        "aeo": aeo_breakdown.total_score,
    }
    overall_score = engine.calculate_overall_score(raw_scores, weights=adjusted_weights)

    result: Dict[str, Any] = {
        "seo_score": seo_breakdown.total_score,
        "geo_score": geo_breakdown.total_score,
        "aeo_score": aeo_breakdown.total_score,
        "overall_score": overall_score,
        "seo_breakdown": {
            "score": seo_breakdown.total_score,
            "components": seo_breakdown.components,
            "penalties": seo_breakdown.penalties,
            "bonuses": seo_breakdown.bonuses,
        },
        "geo_breakdown": {
            "score": geo_breakdown.total_score,
            "components": geo_breakdown.components,
            "penalties": geo_breakdown.penalties,
            "bonuses": geo_breakdown.bonuses,
        },
        "aeo_breakdown": {
            "score": aeo_breakdown.total_score,
            "components": aeo_breakdown.components,
            "penalties": aeo_breakdown.penalties,
            "bonuses": aeo_breakdown.bonuses,
        },
        "version": "3.0",
        "scrape_succeeded": scrape_succeeded,
    }

    # Attach page-type relevance metadata
    if page_type:
        result["page_type"] = page_type
        result["dimension_relevance"] = relevance
        if na_dimensions:
            result["na_dimensions"] = na_dimensions

    return result
