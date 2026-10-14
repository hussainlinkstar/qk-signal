import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.geo.brand_anchor_service import BrandAnchorService


def test_analyze_consistency_computes_score_and_missing_pages():
    service = BrandAnchorService()

    result = service.analyze_consistency(
        site_pages_content=[
            {"url": "https://example.com", "content": "Welcome to ACME Cloud for teams."},
            {"url": "https://example.com/about", "content": "About our platform."},
            {"url": "https://example.com/pricing", "content": "Why choose Acme   Cloud today"},
        ],
        canonical_brand_definition="Acme Cloud",
    )

    assert result["consistency_score"] == pytest.approx(66.67)
    assert result["pages_missing_anchor"] == ["https://example.com/about"]
    assert result["exact_anchor_text_recommendation"] == "Acme Cloud"


def test_analyze_consistency_supports_string_pages_and_fallback_identifiers():
    service = BrandAnchorService()

    result = service.analyze_consistency(
        site_pages_content=[
            "Intro with Nimbus CRM included.",
            "No mention here.",
        ],
        canonical_brand_definition="Nimbus CRM",
    )

    assert result["pages_with_anchor"] == 1
    assert result["pages_missing_anchor"] == ["page-2"]


def test_analyze_consistency_validates_inputs():
    service = BrandAnchorService()

    with pytest.raises(ValueError, match="site_pages_content is required"):
        service.analyze_consistency(site_pages_content=[], canonical_brand_definition="Acme")

    with pytest.raises(ValueError, match="canonical_brand_definition is required"):
        service.analyze_consistency(site_pages_content=["content"], canonical_brand_definition=" ")
