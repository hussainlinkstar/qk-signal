from __future__ import annotations

import re
from typing import Any


class BrandAnchorService:
    """Analyze whether site pages consistently include the canonical brand anchor text."""

    _WHITESPACE_PATTERN = re.compile(r"\s+")

    @classmethod
    def _clean_anchor(cls, canonical_brand_definition: str) -> str:
        return cls._WHITESPACE_PATTERN.sub(" ", canonical_brand_definition or "").strip()

    @classmethod
    def _normalize(cls, value: str) -> str:
        return cls._clean_anchor(value).lower()

    @staticmethod
    def _page_identifier(page: Any, index: int) -> str:
        if isinstance(page, dict):
            for key in ("url", "loc", "path", "slug", "id", "title"):
                raw_identifier = page.get(key)
                if raw_identifier:
                    return str(raw_identifier)
        return f"page-{index + 1}"

    @staticmethod
    def _page_text(page: Any) -> str:
        if isinstance(page, str):
            return page
        if isinstance(page, dict):
            for key in ("content", "text", "body", "html", "markdown"):
                raw_content = page.get(key)
                if isinstance(raw_content, str):
                    return raw_content
        return ""

    def analyze_consistency(
        self, site_pages_content: list[Any], canonical_brand_definition: str
    ) -> dict[str, Any]:
        pages = site_pages_content or []
        if not pages:
            raise ValueError("site_pages_content is required")

        recommended_anchor = self._clean_anchor(canonical_brand_definition)
        if not recommended_anchor:
            raise ValueError("canonical_brand_definition is required")

        normalized_anchor = self._normalize(recommended_anchor)

        missing_pages: list[str] = []
        page_results: list[dict[str, Any]] = []
        pages_with_anchor = 0

        for index, page in enumerate(pages):
            identifier = self._page_identifier(page, index)
            page_text = self._page_text(page)
            has_anchor = normalized_anchor in self._normalize(page_text)

            if has_anchor:
                pages_with_anchor += 1
            else:
                missing_pages.append(identifier)

            page_results.append(
                {
                    "page": identifier,
                    "has_anchor": has_anchor,
                }
            )

        total_pages = len(pages)
        consistency_score = (pages_with_anchor / total_pages) * 100 if total_pages else 0.0

        return {
            "consistency_score": round(consistency_score, 2),
            "pages_missing_anchor": missing_pages,
            "exact_anchor_text_recommendation": recommended_anchor,
            "total_pages": total_pages,
            "pages_with_anchor": pages_with_anchor,
            "page_results": page_results,
        }
