"""Tests for re-canonicalization of stored canonical audit reports.

Validates that ``to_canonical_audit_result`` preserves existing scores and
breakdowns when re-processing a report that was previously stored via
``model_dump(mode="json")`` (e.g. when loading from the database for API
responses).

Key bug scenario: stored reports have ``generated_at`` as an ISO string
(serialised by Pydantic), but ``AuditResult`` uses ``strict=True`` which
rejects string→datetime coercion.  Without the fix, the happy-path
validation fails and the fallback re-computes scores from scratch without
page content, zeroing out all content-dependent sub-components.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.reports.audit_result_adapter import (
    _prepare_raw_report_for_validation,
    to_canonical_audit_result,
)


def _make_stored_canonical_report(
    *,
    seo_score: float = 72.5,
    geo_score: float = 65.3,
    aeo_score: float = 58.1,
    overall_score: float = 66.0,
    scraped_content: str = "This is a sample page with enough content for scoring.",
) -> dict:
    """Build a dict that simulates a stored canonical report (post model_dump(mode='json')).

    The key characteristic is that ``generated_at`` and metadata timestamps are
    ISO strings (as produced by ``model_dump(mode="json")``), and there is no
    ``markdown_content`` at the top level.
    """
    now_iso = "2026-03-15T10:30:00+00:00"
    return {
        "schema_version": "2026-03-09",
        "audit_mode": "website",
        "score_source": "blended_v3",
        "generated_at": now_iso,
        "score_contract": {
            "public_score_source": "deterministic_matrix",
            "public_score_version": "3.0",
            "has_internal_alternative_scores": False,
        },
        "confidence": {
            "audit_mode": "website",
            "has_external_data_sources": False,
            "external_data_coverage": 0,
            "finding_confidence": "high",
            "competitive_confidence": "low",
            "narrative_confidence": "low",
            "warnings": [],
            "grounding_status": {
                "flagged": False,
                "supported_sentences": 0,
                "total_sentences": 0,
                "support_ratio": 0,
            },
        },
        "narrative": {
            "executive_summary": {
                "text": None,
                "source_type": "ai_synthesis",
                "confidence": "low",
                "supported_sentence_ratio": 0,
                "requires_review": False,
            },
            "intelligence_dossier": {
                "text": None,
                "source_type": "ai_synthesis",
                "confidence": "low",
                "supported_sentence_ratio": 0,
                "requires_review": False,
            },
            "strategic_roadmap": {
                "text": None,
                "source_type": "ai_synthesis",
                "confidence": "low",
                "supported_sentence_ratio": 0,
                "requires_review": False,
            },
        },
        "recommendations": {
            "items": [],
            "total_count": 0,
            "category_breakdown": {},
        },
        "competitive": {},
        "target": {
            "type": "website",
            "name": "https://example.com",
            "url": "https://example.com",
            "metadata": {},
        },
        "site": {
            "url": "https://example.com",
            "market": "us",
            "language": "en",
        },
        "seo": {
            "onpage": seo_score,
            "performance": 80.0,
            "indexing": 75.0,
            "core_web_vitals": 70.0,
            "technical_seo": 68.0,
            "onpage_content": 65.0,
            "eeat_trust": 60.0,
            "security_accessibility": 55.0,
        },
        "geo": {
            "visibility_index": geo_score,
            "citation_share": None,
            "brand_anchor": None,
            "advanced_local_schema": 50.0,
            "napw_completeness": 45.0,
            "spatial_content": 40.0,
            "content_citability": 50.0,
            "source_authority": 45.0,
            "entity_clarity": 40.0,
            "brand_citation": 35.0,
        },
        "aeo": {
            "answerability_score": aeo_score,
            "extractable_pages": None,
            "schema_health": {},
            "schema_coverage": {},
            "readability_score": None,
            "readability_findings": [],
            "rewrite_suggestions": [],
            "llm_schema_readiness": 55.0,
            "semantic_entity_density": 50.0,
            "information_gain": 48.0,
            "snippet_formatting": 45.0,
        },
        "entities": ["example.com"],
        "competitors": [],
        "suggestions": [],
        "scores": {
            "seo": seo_score,
            "geo": geo_score,
            "aeo": aeo_score,
            "overall": overall_score,
            "seo_breakdown": {
                "score": seo_score,
                "components": {
                    "core_web_vitals": 70.0,
                    "technical_seo": 68.0,
                    "onpage_content": 65.0,
                    "eeat_trust": 60.0,
                    "security_accessibility": 55.0,
                },
                "penalties": [],
                "bonuses": [],
            },
            "geo_breakdown": {
                "score": geo_score,
                "components": {
                    "content_citability": 50.0,
                    "source_authority": 45.0,
                    "entity_clarity": 40.0,
                    "brand_citation": 35.0,
                },
                "penalties": [],
                "bonuses": [],
            },
            "aeo_breakdown": {
                "score": aeo_score,
                "components": {
                    "llm_schema_readiness": 55.0,
                    "semantic_entity_density": 50.0,
                    "information_gain": 48.0,
                    "snippet_formatting": 45.0,
                },
                "penalties": [],
                "bonuses": [],
            },
            "scoring_version": "3.0",
        },
        "metadata": {
            "created_at": now_iso,
            "updated_at": now_iso,
            "plan": "plan_specialist",
            "version": "2026-03-09",
            "service_status": {},
            "service_errors": {},
            "competitor_summary": {},
            "scores_available": True,
            "audit_outcome": "completed",
            "intent": "informational",
            "query_type": "informational",
            "technical_signals": {},
            "score_source": "blended_v3",
            "page_type": "homepage",
            "market": "us",
            "language": "en",
            "target_name": "https://example.com",
            "target_url": "https://example.com",
            "audit_target_type": "website",
            "target_metadata": {},
            "scraped_content": scraped_content,
        },
        "deltas_vs_target": None,
        "hallucination": None,
    }


class TestPrepareRawReportForValidation:
    """Tests for the _prepare_raw_report_for_validation helper."""

    def test_normalizes_generated_at_from_string(self) -> None:
        raw = {"generated_at": "2026-03-15T10:30:00+00:00", "metadata": {}}
        result = _prepare_raw_report_for_validation(raw)
        assert isinstance(result["generated_at"], datetime)
        assert result["generated_at"].year == 2026

    def test_preserves_generated_at_when_already_datetime(self) -> None:
        dt = datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)
        raw = {"generated_at": dt, "metadata": {}}
        result = _prepare_raw_report_for_validation(raw)
        assert result["generated_at"] is dt

    def test_normalizes_metadata_timestamps(self) -> None:
        raw = {
            "metadata": {
                "created_at": "2026-03-15T10:00:00+00:00",
                "updated_at": "2026-03-15T10:30:00+00:00",
            }
        }
        result = _prepare_raw_report_for_validation(raw)
        assert isinstance(result["metadata"]["created_at"], datetime)
        assert isinstance(result["metadata"]["updated_at"], datetime)

    def test_strips_extra_fields_not_in_audit_result(self) -> None:
        raw = {
            "markdown_content": "page content here",
            "_brand_signals": {"summary": {}},
            "analysis": {"seo_score": 80},
            "performance": {"performance_score": 75},
            "generated_at": "2026-03-15T10:30:00+00:00",
            "metadata": {},
            "target": {"type": "website", "name": "test"},
        }
        result = _prepare_raw_report_for_validation(raw)
        assert "markdown_content" not in result
        assert "_brand_signals" not in result
        assert "analysis" not in result
        assert "performance" not in result
        assert "target" in result
        assert "metadata" in result

    def test_handles_missing_metadata(self) -> None:
        raw = {"generated_at": "2026-03-15T10:30:00+00:00"}
        result = _prepare_raw_report_for_validation(raw)
        assert isinstance(result["generated_at"], datetime)


class TestRecanonicalizationPreservesScores:
    """Tests that to_canonical_audit_result preserves scores from stored reports."""

    def test_stored_canonical_report_preserves_seo_breakdown(self) -> None:
        stored = _make_stored_canonical_report(seo_score=72.5)
        result = to_canonical_audit_result(
            stored,
            audit_url="https://example.com",
            plan="plan_specialist",
        )
        scores = result.get("scores", {})
        seo_breakdown = scores.get("seo_breakdown")
        assert seo_breakdown is not None
        components = seo_breakdown.get("components", {})
        assert components.get("technical_seo") is not None
        assert (
            components.get("technical_seo") > 0
        ), "technical_seo should not be zero after re-canonicalization"

    def test_stored_canonical_report_preserves_geo_breakdown(self) -> None:
        stored = _make_stored_canonical_report(geo_score=65.3)
        result = to_canonical_audit_result(
            stored,
            audit_url="https://example.com",
            plan="plan_specialist",
        )
        scores = result.get("scores", {})
        geo_breakdown = scores.get("geo_breakdown")
        assert geo_breakdown is not None
        components = geo_breakdown.get("components", {})
        assert components.get("content_citability") is not None
        assert (
            components.get("content_citability") > 0
        ), "content_citability should not be zero after re-canonicalization"

    def test_stored_canonical_report_preserves_aeo_breakdown(self) -> None:
        stored = _make_stored_canonical_report(aeo_score=58.1)
        result = to_canonical_audit_result(
            stored,
            audit_url="https://example.com",
            plan="plan_specialist",
        )
        scores = result.get("scores", {})
        aeo_breakdown = scores.get("aeo_breakdown")
        assert aeo_breakdown is not None
        components = aeo_breakdown.get("components", {})
        assert components.get("semantic_entity_density") is not None
        assert (
            components.get("semantic_entity_density") > 0
        ), "semantic_entity_density should not be zero after re-canonicalization"

    def test_stored_report_with_string_generated_at_passes_validation(self) -> None:
        stored = _make_stored_canonical_report()
        result = to_canonical_audit_result(
            stored,
            audit_url="https://example.com",
            plan="plan_specialist",
        )
        assert "generated_at" in result
        assert result["schema_version"] == "2026-03-09"
        assert result["audit_mode"] == "website"

    def test_no_scraping_failed_penalties_for_stored_report(self) -> None:
        stored = _make_stored_canonical_report()
        result = to_canonical_audit_result(
            stored,
            audit_url="https://example.com",
            plan="plan_specialist",
        )
        scores = result.get("scores", {})
        for dim in ("seo_breakdown", "geo_breakdown", "aeo_breakdown"):
            breakdown = scores.get(dim, {})
            penalties = breakdown.get("penalties", [])
            for penalty in penalties:
                reason = penalty.get("reason", "") if isinstance(penalty, dict) else ""
                assert (
                    "Scraping failed" not in reason
                ), f"Found 'Scraping failed' penalty in {dim}: {reason}"


class TestHappyPathValidation:
    """Verify the happy path (AuditResult.model_validate) actually succeeds for
    stored canonical reports, rather than silently falling through to the
    fallback path that re-computes scores."""

    def test_happy_path_runs_for_stored_canonical_report(self) -> None:
        """The deterministic scoring function should NOT be called when
        re-canonicalising a stored canonical report, because the happy path
        should succeed and preserve existing scores."""
        from unittest.mock import patch

        stored = _make_stored_canonical_report(seo_score=72.5, geo_score=65.3, aeo_score=58.1)
        with patch(
            "services.reports.audit_result_adapter.calculate_deterministic_scores",
            side_effect=AssertionError("fallback path should not be reached"),
        ):
            result = to_canonical_audit_result(
                stored,
                audit_url="https://example.com",
                plan="plan_specialist",
            )
        # Scores should be preserved from the stored report, not re-computed
        scores = result.get("scores", {})
        assert scores.get("seo") is not None
        assert scores.get("geo") is not None
        assert scores.get("aeo") is not None


class TestFallbackContentSource:
    """Tests that the fallback path uses metadata.scraped_content."""

    def test_fallback_uses_metadata_scraped_content(self) -> None:
        raw = {
            "analysis": {
                "seo_score": 80,
                "geo_score": 75,
                "aeo_score": 70,
                "recommendations": ["Add schema"],
            },
            "performance": {"performance_score": 85},
            "metadata": {
                "market": "us",
                "language": "en",
                "plan": "plan_starter",
                "scraped_content": (
                    "This is sample page content with enough text for the scoring "
                    "engine to detect that scraping succeeded. It needs to be long "
                    "enough that the word count exceeds the thin content threshold. "
                    "Adding more words here to ensure the content is substantial "
                    "enough for the deterministic scoring engine to recognise it. "
                    "The quick brown fox jumps over the lazy dog multiple times. "
                ),
            },
        }
        result = to_canonical_audit_result(
            raw,
            audit_url="https://example.com",
            plan="plan_starter",
        )
        scores = result.get("scores", {})
        seo_breakdown = scores.get("seo_breakdown", {})
        components = seo_breakdown.get("components", {})
        assert components.get("technical_seo", 0) > 0 or components.get("onpage_content", 0) > 0, (
            "At least one content-dependent SEO component should be non-zero "
            "when metadata.scraped_content is available"
        )

    def test_fallback_without_any_content_zeros_content_components(self) -> None:
        """When there is truly no content and no scrape metadata, content-dependent
        components should be zeroed out with 'Scraping failed' penalties."""
        raw = {
            "analysis": {
                "seo_score": 80,
                "geo_score": 75,
                "aeo_score": 70,
            },
            "performance": {},
            "metadata": {
                "market": "us",
                "language": "en",
                "plan": "plan_starter",
            },
        }
        # Pass empty audit_url so there is no title fallback from URL
        result = to_canonical_audit_result(
            raw,
            audit_url="",
            plan="plan_starter",
        )
        scores = result.get("scores", {})
        seo_breakdown = scores.get("seo_breakdown", {})
        penalties = seo_breakdown.get("penalties", [])
        has_scrape_failed = any(
            "Scraping failed" in (p.get("reason", "") if isinstance(p, dict) else "")
            for p in penalties
        )
        assert (
            has_scrape_failed
        ), "Expected a 'Scraping failed' penalty when no content/metadata is available"
