"""AEX-02: Verify overall score uses weighted formula (SEO 40% + AEO 30% + GEO 30%)."""

from pathlib import Path
import sys


sys.path.append(str(Path(__file__).resolve().parents[1]))

from score_utils import DeterministicScoringEngine


class TestOverallScoreWeighting:
    """Ensure calculate_overall_score uses the documented SEO 40% / AEO 30% / GEO 30% weights."""

    def test_asymmetric_scores_produce_weighted_result(self):
        """SEO=90, GEO=40, AEO=40 should produce 60 (weighted), not ~57 (simple avg)."""
        scores = {"seo": 90.0, "geo": 40.0, "aeo": 40.0}
        result = DeterministicScoringEngine.calculate_overall_score(scores)
        # Weighted: 90*0.4 + 40*0.3 + 40*0.3 = 36 + 12 + 12 = 60
        assert result == 60.0

    def test_equal_scores_produce_same_value(self):
        """When all dimensions are equal, weighting doesn't matter."""
        scores = {"seo": 70.0, "geo": 70.0, "aeo": 70.0}
        result = DeterministicScoringEngine.calculate_overall_score(scores)
        assert result == 70.0

    def test_seo_dominant_weight(self):
        """High SEO should pull overall up more than high GEO or AEO alone."""
        seo_heavy = {"seo": 100.0, "geo": 0.0, "aeo": 0.0}
        geo_heavy = {"seo": 0.0, "geo": 100.0, "aeo": 0.0}
        aeo_heavy = {"seo": 0.0, "geo": 0.0, "aeo": 100.0}

        assert DeterministicScoringEngine.calculate_overall_score(seo_heavy) == 40.0
        assert DeterministicScoringEngine.calculate_overall_score(geo_heavy) == 30.0
        assert DeterministicScoringEngine.calculate_overall_score(aeo_heavy) == 30.0

    def test_zero_scores_produce_zero(self):
        scores = {"seo": 0.0, "geo": 0.0, "aeo": 0.0}
        assert DeterministicScoringEngine.calculate_overall_score(scores) == 0.0

    def test_max_scores_produce_100(self):
        scores = {"seo": 100.0, "geo": 100.0, "aeo": 100.0}
        assert DeterministicScoringEngine.calculate_overall_score(scores) == 100.0

    def test_clamped_at_100(self):
        """Even if individual scores somehow exceed 100, overall is capped."""
        scores = {"seo": 120.0, "geo": 120.0, "aeo": 120.0}
        assert DeterministicScoringEngine.calculate_overall_score(scores) == 100.0

    def test_missing_keys_handled_gracefully(self):
        """If a dimension is missing, weighting adjusts proportionally."""
        scores = {"seo": 80.0}  # only SEO present
        result = DeterministicScoringEngine.calculate_overall_score(scores)
        # Should be 80*0.4/0.4 = 80 (renormalized)
        assert result == 80.0

    def test_default_weights_match_documented_values(self):
        """Verify the default weight dict is SEO=0.4, AEO=0.3, GEO=0.3."""
        scores = {"seo": 50.0, "geo": 50.0, "aeo": 50.0}
        # With equal scores and any valid weights, result should be 50
        assert DeterministicScoringEngine.calculate_overall_score(scores) == 50.0

        # Verify asymmetric: explicit weights match the method's defaults
        scores2 = {"seo": 100.0, "geo": 50.0, "aeo": 50.0}
        result = DeterministicScoringEngine.calculate_overall_score(scores2)
        expected = 100 * 0.4 + 50 * 0.3 + 50 * 0.3  # 40 + 15 + 15 = 70
        assert result == expected
