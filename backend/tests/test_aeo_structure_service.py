import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.aeo.structure_service import (
    analyze_json_ld_structure,
    calculate_schema_coverage,
    detect_extractable_answer_block,
)


def test_calculate_schema_coverage_returns_percentages_and_missing_high_impact_types():
    result = calculate_schema_coverage(
        detected_types={"FAQPage", "Product"},
        required_types={"FAQPage", "HowTo", "Product"},
        high_impact_types={"FAQPage", "HowTo"},
    )

    assert result == {
        "coverage_by_type": {"FAQPage": 100.0, "HowTo": 0.0, "Product": 100.0},
        "coverage_percent": 66.67,
        "missing_high_impact_types": ["HowTo"],
    }


def test_detect_extractable_answer_block_success():
    html = """
    <h2>What is technical SEO?</h2>
    <p>Technical SEO is the process of improving a site so search engines can crawl, render, and index it efficiently.</p>
    <p>It includes optimizing robots.txt, sitemap coverage, page speed, and internal linking architecture.</p>
    """

    result = detect_extractable_answer_block(html)

    assert result["extractable"] is True
    assert result["reason"] == ""


def test_detect_extractable_answer_block_fails_without_question_heading():
    html = """
    <h2>Technical SEO fundamentals</h2>
    <p>Technical SEO improves crawlability and indexing.</p>
    <p>Supporting details appear here.</p>
    """

    result = detect_extractable_answer_block(html)

    assert result == {
        "extractable": False,
        "reason": "No H2/H3 question heading found.",
    }


def test_detect_extractable_answer_block_fails_when_answer_too_long():
    html = """
    <h3>How do canonical tags work?</h3>
    <p>
      Canonical tags help search engines understand the preferred version of a page among duplicates, but this
      paragraph intentionally contains enough words to cross the threshold so that it should no longer be treated
      as a direct extractable answer because it exceeds the target length and becomes too verbose for quick answer
      extraction workflows across broad content libraries in enterprise editorial systems where responses need concise summaries instead of long-form prose for machine-readable snippets and rapid answer surfacing.
    </p>
    <p>Additional supporting detail is present.</p>
    """

    result = detect_extractable_answer_block(html)

    assert result == {
        "extractable": False,
        "reason": "Direct answer paragraph must be under 60 words.",
    }


def test_detect_extractable_answer_block_fails_without_supporting_details():
    html = """
    <h2>Why is crawl budget important?</h2>
    <p>Crawl budget determines how much attention search bots can allocate to your important pages.</p>
    """

    result = detect_extractable_answer_block(html)

    assert result == {
        "extractable": False,
        "reason": "Direct answer must be followed by supporting details.",
    }


def test_detect_extractable_answer_block_fails_when_answer_is_not_immediate_next_block():
    html = """
    <h2>What is local SEO?</h2>
    <ul><li>Context bullet before answer paragraph.</li></ul>
    <p>Local SEO optimizes your business visibility for nearby searches.</p>
    <p>Supporting details appear here.</p>
    """

    result = detect_extractable_answer_block(html)

    assert result == {
        "extractable": False,
        "reason": "Question heading must be immediately followed by an answer paragraph.",
    }


def test_analyze_json_ld_structure_detects_software_application_type():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      "name": "Acme App",
      "description": "Automation suite",
      "applicationCategory": "BusinessApplication",
      "operatingSystem": "Web",
      "offers": {"@type": "Offer", "price": "29"}
    }
    </script>
    """

    result = analyze_json_ld_structure(html, site_category="software")

    assert result["detected_schema_types"] == ["SoftwareApplication"]
    assert result["missing_required_types"] == ["FAQPage", "HowTo", "Product"]
    assert result["missing_fields_by_type"] == {}
    assert result["high_impact_blockers"] == []
    assert result["coverage_by_type"] == {
        "FAQPage": 0.0,
        "HowTo": 0.0,
        "Product": 0.0,
        "SoftwareApplication": 100.0,
    }
    assert result["coverage_percent"] == 25.0
    assert result["missing_high_impact_types"] == ["FAQPage", "HowTo"]


def test_analyze_json_ld_structure_reports_missing_required_software_type():
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Organization",
      "name": "Acme"
    }
    </script>
    """

    result = analyze_json_ld_structure(html, site_category="software")

    assert result["detected_schema_types"] == ["Organization"]
    assert result["missing_required_types"] == [
        "FAQPage",
        "HowTo",
        "Product",
        "SoftwareApplication",
    ]
    assert result["coverage_percent"] == 0.0


def test_analyze_json_ld_structure_flags_high_impact_blocker_for_software_sites():
    result = analyze_json_ld_structure("", site_category="software")

    assert result["missing_required_types"] == [
        "FAQPage",
        "HowTo",
        "Product",
        "SoftwareApplication",
    ]
    assert result["coverage_percent"] == 0.0
    assert result["high_impact_blockers"] == [
        "Missing SoftwareApplication schema is a high-impact AEO blocker for software sites."
    ]
