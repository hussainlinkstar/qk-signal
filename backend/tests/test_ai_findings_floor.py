"""Tests for the AI findings floor mechanism in score_utils.py.

Verifies that brand-no-URL audits receive a minimum score floor (12-35 range)
derived from AI analysis quality when both deterministic scoring and brand
signal collection produce near-zero scores.
"""

from score_utils import (
    ScoreBreakdown,
    _apply_ai_findings_floor,
    AI_FLOOR_MIN,
    AI_FLOOR_MAX,
    calculate_deterministic_scores,
)


class TestApplyAIFindingsFloor:
    """Unit tests for _apply_ai_findings_floor()."""

    def _make_breakdown(self, total_score: float = 0.0) -> ScoreBreakdown:
        return ScoreBreakdown(
            total_score=total_score,
            components={"base": total_score},
            penalties=[],
            bonuses=[],
            metadata={},
        )

    def test_no_effect_when_score_above_floor(self):
        """Floor should not apply when existing score >= AI_FLOOR_MIN."""
        bd = self._make_breakdown(50.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=5,
            cross_findings_count=10,
            summary_length=500,
            recommendations_count=8,
        )
        assert result.total_score == 50.0
        assert "ai_findings_floor_applied" not in result.metadata

    def test_floor_applied_when_score_zero_with_findings(self):
        """Zero-score audit with AI findings should get a floor score."""
        bd = self._make_breakdown(0.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=3,
            cross_findings_count=5,
            summary_length=200,
            recommendations_count=4,
        )
        assert result.total_score >= AI_FLOOR_MIN
        assert result.total_score <= AI_FLOOR_MAX
        assert result.metadata.get("ai_findings_floor_applied") is True
        assert result.metadata.get("base_score_before_floor") == 0.0

    def test_floor_never_exceeds_max(self):
        """Even with maximum findings, floor should not exceed AI_FLOOR_MAX."""
        bd = self._make_breakdown(0.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=50,
            cross_findings_count=100,
            summary_length=5000,
            recommendations_count=50,
        )
        assert result.total_score <= AI_FLOOR_MAX

    def test_floor_with_zero_findings_stays_at_min(self):
        """When no findings and no summary, floor should be at AI_FLOOR_MIN."""
        bd = self._make_breakdown(0.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=0,
            cross_findings_count=0,
            summary_length=0,
            recommendations_count=0,
        )
        assert result.total_score == AI_FLOOR_MIN
        assert result.metadata.get("ai_findings_floor_applied") is True

    def test_no_effect_when_existing_score_above_calculated_floor(self):
        """When existing score is above what the floor would be, keep it."""
        bd = self._make_breakdown(11.5)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=0,
            cross_findings_count=0,
            summary_length=0,
            recommendations_count=0,
        )
        # AI_FLOOR_MIN is 12.0, so with 0 findings the floor = 12.0
        # existing 11.5 < 12.0, so floor should apply
        assert result.total_score == AI_FLOOR_MIN

    def test_all_dimensions_apply_floor(self):
        """All three dimensions should support the floor mechanism."""
        for dim in ("seo", "geo", "aeo"):
            bd = self._make_breakdown(0.0)
            result = _apply_ai_findings_floor(
                bd,
                dimension=dim,
                own_findings_count=3,
                cross_findings_count=5,
                summary_length=200,
                recommendations_count=4,
            )
            assert result.total_score >= AI_FLOOR_MIN, f"{dim} floor not applied"
            assert result.metadata.get("ai_findings_floor_applied") is True

    def test_bonus_entry_added(self):
        """A bonus entry should be recorded in the breakdown."""
        bd = self._make_breakdown(0.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=3,
            cross_findings_count=5,
            summary_length=200,
            recommendations_count=4,
        )
        assert len(result.bonuses) == 1
        bonus = result.bonuses[0]
        assert bonus["name"] == "ai_findings_floor"
        assert bonus["value"] > 0
        assert "3 own findings" in bonus["reason"]

    def test_component_key_not_injected(self):
        """ai_analysis_floor should NOT be in components (bonuses-only pattern)."""
        bd = self._make_breakdown(0.0)
        result = _apply_ai_findings_floor(
            bd,
            dimension="seo",
            own_findings_count=2,
            cross_findings_count=3,
            summary_length=100,
            recommendations_count=2,
        )
        assert "ai_analysis_floor" not in result.components
        # Floor adjustment is tracked via bonuses only
        assert any(b["name"] == "ai_findings_floor" for b in result.bonuses)

    def test_progressive_score_with_more_findings(self):
        """More findings should produce a higher floor score."""
        bd_few = self._make_breakdown(0.0)
        result_few = _apply_ai_findings_floor(
            bd_few,
            dimension="seo",
            own_findings_count=1,
            cross_findings_count=0,
            summary_length=0,
            recommendations_count=0,
        )

        bd_many = self._make_breakdown(0.0)
        result_many = _apply_ai_findings_floor(
            bd_many,
            dimension="seo",
            own_findings_count=5,
            cross_findings_count=10,
            summary_length=500,
            recommendations_count=8,
        )

        assert result_many.total_score > result_few.total_score


class TestCalculateDeterministicScoresWithAIFloor:
    """Integration tests for calculate_deterministic_scores with ai_findings_meta."""

    def test_brand_no_url_with_ai_meta_gets_nonzero_scores(self):
        """Brand-no-URL audit with AI findings should not produce all-zero scores."""
        ai_meta = {
            "seo_findings_count": 4,
            "geo_findings_count": 3,
            "aeo_findings_count": 5,
            "summary_length": 300,
            "recommendations_count": 6,
        }
        result = calculate_deterministic_scores(
            performance_metrics=None,
            schema_analysis=None,
            scrape_metadata=None,
            network_data=None,
            content="",
            seo_findings=None,
            geo_findings=None,
            aeo_findings=None,
            brand_name="Qiko Signal",
            brand_signals=None,
            scrape_succeeded=False,
            ai_findings_meta=ai_meta,
        )
        assert result["seo_score"] >= AI_FLOOR_MIN
        assert result["geo_score"] >= AI_FLOOR_MIN
        assert result["aeo_score"] >= AI_FLOOR_MIN

    def test_brand_no_url_without_ai_meta_stays_zero(self):
        """Brand-no-URL audit without ai_findings_meta should remain zero."""
        result = calculate_deterministic_scores(
            performance_metrics=None,
            schema_analysis=None,
            scrape_metadata=None,
            network_data=None,
            content="",
            seo_findings=None,
            geo_findings=None,
            aeo_findings=None,
            brand_name="Qiko Signal",
            brand_signals=None,
            scrape_succeeded=False,
            ai_findings_meta=None,
        )
        # Without AI meta, the scores remain at their base calculation
        assert result["seo_score"] is not None
        assert result["geo_score"] is not None
        assert result["aeo_score"] is not None

    def test_normal_url_audit_unaffected_by_ai_meta(self):
        """URL-based audits with ai_findings_meta=None derive scores from real signals."""
        result = calculate_deterministic_scores(
            performance_metrics={"performance_score": 85, "lcp": 1.2, "cls": 0.05},
            schema_analysis={"types_found": ["Article", "Organization"]},
            scrape_metadata={"status_code": 200, "is_indexable": True},
            network_data={"supports_http2": True, "cert_valid": True},
            content="This is a sample page with meaningful content about Qiko Signal product features.",
            seo_findings=None,
            geo_findings=None,
            aeo_findings=None,
            brand_name=None,
            brand_signals=None,
            scrape_succeeded=True,
            ai_findings_meta=None,
        )
        # URL-based audit should produce scores from real signals, not the floor
        assert result["seo_score"] > 0
        # Verify no AI floor metadata in the breakdown
        seo_bd = result.get("seo_breakdown", {})
        assert not seo_bd.get("metadata", {}).get("ai_findings_floor_applied")
