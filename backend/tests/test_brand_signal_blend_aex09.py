# pyre-unsafe
"""Tests for AEX-09: Brand signal boost uses real blending (not max)."""

import pytest
from score_utils import (
    ScoreBreakdown,
    _apply_brand_signal_boost,
    BRAND_SIGNAL_WEIGHT,
    BRAND_BASE_WEIGHT,
)


def _make_breakdown(total: float, **kwargs) -> ScoreBreakdown:
    return ScoreBreakdown(
        total_score=total,
        components=kwargs.get("components", {}),
        penalties=kwargs.get("penalties", []),
        bonuses=kwargs.get("bonuses", []),
        metadata=kwargs.get("metadata", {}),
    )


class TestBrandSignalBlend:
    """Tests that brand signal boost blends instead of replacing."""

    def test_low_base_high_brand_blends(self):
        """base=10, brand=80 → blended ≈ 59 (not 80)."""
        bd = _make_breakdown(10.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=30.0,  # → 100 normalized
            kg_score=25.0,  # → 100 normalized
            wiki_score=25.0,  # → 100 normalized
            ai_vis_score=20.0,  # → 100 normalized
        )
        # brand_score = 100 * (0.45+0.25+0.15+0.15) = 100
        # blended = 0.30 * 10 + 0.70 * 100 = 3 + 70 = 73
        assert result.total_score == pytest.approx(73.0, abs=1.0)
        # Must NOT be 100 (the old max behavior)
        assert result.total_score < 80

    def test_high_base_low_brand_no_boost(self):
        """base=90, brand=50 → no boost applied (brand <= base)."""
        bd = _make_breakdown(90.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=10.0,  # → 33.3 normalized
            kg_score=10.0,  # → 40.0 normalized
            wiki_score=10.0,  # → 40.0 normalized
            ai_vis_score=10.0,  # → 50.0 normalized
        )
        # brand_score ≈ 33.3*0.45 + 40*0.25 + 40*0.15 + 50*0.15 ≈ 15+10+6+7.5 = 38.5
        # 38.5 < 90, so no boost
        assert result.total_score == 90.0

    def test_both_zero(self):
        """base=0, brand=0 → blended = 0."""
        bd = _make_breakdown(0.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=0.0,
            kg_score=0.0,
            wiki_score=0.0,
            ai_vis_score=0.0,
        )
        assert result.total_score == 0.0

    def test_metadata_includes_source_scores(self):
        """Both base and brand signal scores must be in metadata."""
        bd = _make_breakdown(10.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="geo",
            serp_score=20.0,
            kg_score=20.0,
            wiki_score=20.0,
            ai_vis_score=15.0,
        )
        assert result.metadata["brand_signal_boosted"] is True
        assert "base_deterministic_score" in result.metadata
        assert result.metadata["base_deterministic_score"] == 10.0
        assert "brand_signal_score" in result.metadata
        assert result.metadata["brand_signal_score"] > 0

    def test_blend_ratio_in_metadata(self):
        """Blend ratio should be stored in metadata."""
        bd = _make_breakdown(5.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="aeo",
            serp_score=30.0,
            kg_score=25.0,
            wiki_score=25.0,
            ai_vis_score=20.0,
        )
        assert "blend_ratio" in result.metadata
        assert result.metadata["blend_ratio"]["brand"] == BRAND_SIGNAL_WEIGHT
        assert result.metadata["blend_ratio"]["base"] == BRAND_BASE_WEIGHT

    def test_all_dimensions_use_blend(self):
        """All three dimensions (SEO, GEO, AEO) should use blend, not max."""
        for dim in ("seo", "geo", "aeo"):
            bd = _make_breakdown(10.0)
            result = _apply_brand_signal_boost(
                bd,
                dimension=dim,
                serp_score=30.0,
                kg_score=25.0,
                wiki_score=25.0,
                ai_vis_score=20.0,
            )
            # Blended should be between 10 and 100
            assert result.total_score > 10.0, f"{dim}: blended should be > base"
            assert (
                result.total_score < 100.0
            ), f"{dim}: blended should be < brand_score (was max before)"
            # Verify metadata
            assert result.metadata.get("brand_signal_boosted") is True
            assert result.metadata["base_deterministic_score"] == 10.0

    def test_blend_constants_sum_to_one(self):
        """Brand + base weights should sum to 1.0 for a proper weighted average."""
        assert BRAND_SIGNAL_WEIGHT + BRAND_BASE_WEIGHT == pytest.approx(1.0)

    def test_moderate_brand_moderate_base(self):
        """base=40, brand=60 → blended = 0.30*40 + 0.70*60 = 12 + 42 = 54."""
        bd = _make_breakdown(40.0)
        # Construct signals that produce brand_score ≈ 60
        # serp: 18/30*100 = 60 → 60*0.45 = 27
        # kg: 15/25*100 = 60 → 60*0.25 = 15
        # wiki: 15/25*100 = 60 → 60*0.15 = 9
        # ai_vis: 12/20*100 = 60 → 60*0.15 = 9
        # total: 27+15+9+9 = 60
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=18.0,
            kg_score=15.0,
            wiki_score=15.0,
            ai_vis_score=12.0,
        )
        # blended = 0.30 * 40 + 0.70 * 60 = 12 + 42 = 54
        assert result.total_score == pytest.approx(54.0, abs=1.0)

    def test_brand_components_stored(self):
        """Brand signal sub-components should be stored in breakdown components."""
        bd = _make_breakdown(5.0, components={"existing": 5.0})
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=30.0,
            kg_score=25.0,
            wiki_score=25.0,
            ai_vis_score=20.0,
        )
        assert "brand_serp_presence" in result.components
        assert "brand_knowledge_graph" in result.components
        assert "brand_wikidata" in result.components
        assert "brand_ai_visibility" in result.components
        # Existing components preserved
        assert result.components["existing"] == 5.0

    def test_bonus_records_boost_value(self):
        """A bonus entry should record the boost amount."""
        bd = _make_breakdown(10.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=30.0,
            kg_score=25.0,
            wiki_score=25.0,
            ai_vis_score=20.0,
        )
        brand_bonuses = [b for b in result.bonuses if b.get("name") == "brand_signal_boost"]
        assert len(brand_bonuses) == 1
        assert brand_bonuses[0]["value"] > 0
        assert "70/30 blend" in brand_bonuses[0]["reason"]

    def test_score_clamped_to_100(self):
        """Blended score should never exceed 100."""
        bd = _make_breakdown(95.0)
        result = _apply_brand_signal_boost(
            bd,
            dimension="seo",
            serp_score=30.0,
            kg_score=25.0,
            wiki_score=25.0,
            ai_vis_score=20.0,
        )
        # brand_score = 100 → 100 > 95 so boost applied
        # blended = 0.30*95 + 0.70*100 = 28.5 + 70 = 98.5
        assert result.total_score <= 100.0
