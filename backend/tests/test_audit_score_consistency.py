"""Score consistency: persisted audit columns must mirror full_report["scores"].

Covers:
- canonical_score_breakdown reads from full_report["scores"]
- canonical_score_breakdown clamps every dimension into [0, 100]
- the multi-model audit path derives the persisted breakdown from the
  synthesized full_report (not the first model's raw scores)
"""

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from audit_runner import canonical_score_breakdown


class TestCanonicalScoreBreakdown:
    def test_reads_from_full_report_scores(self):
        full_report = {"scores": {"seo": 54.0, "geo": 33.0, "aeo": 47.0, "overall": 44.7}}
        breakdown = canonical_score_breakdown(full_report)
        assert breakdown["seo"] == 54.0
        assert breakdown["geo"] == 33.0
        assert breakdown["aeo"] == 47.0
        assert breakdown["overall"] == 44.7

    def test_clamps_values_above_100(self):
        full_report = {"scores": {"seo": 140.0, "geo": 33.0, "aeo": 47.0, "overall": 120.0}}
        breakdown = canonical_score_breakdown(full_report)
        assert breakdown["seo"] == 100.0
        assert breakdown["overall"] == 100.0

    def test_clamps_negative_values(self):
        full_report = {"scores": {"seo": -10.0, "geo": 33.0, "aeo": 47.0}}
        breakdown = canonical_score_breakdown(full_report)
        assert breakdown["seo"] == 0.0
        assert breakdown["geo"] == 33.0

    def test_non_numeric_defaults_to_zero(self):
        full_report = {"scores": {"seo": "n/a", "geo": None, "aeo": 47.0}}
        breakdown = canonical_score_breakdown(full_report)
        assert breakdown["seo"] == 0.0
        assert breakdown["geo"] == 0.0
        assert breakdown["aeo"] == 47.0

    def test_missing_report_returns_zeros(self):
        assert canonical_score_breakdown(None) == {
            "seo": 0.0,
            "geo": 0.0,
            "aeo": 0.0,
            "overall": 0.0,
        }

    def test_multi_model_consistency_invariant(self):
        """Persisted columns derived via canonical_score_breakdown must equal
        the synthesized full_report scores (the multi-model bug previously
        persisted the first model's raw scores instead)."""
        synthesized = {"scores": {"seo": 61.0, "geo": 40.0, "aeo": 52.0, "overall": 51.7}}
        breakdown = canonical_score_breakdown(synthesized)
        for dim in ("seo", "geo", "aeo"):
            assert breakdown[dim] == synthesized["scores"][dim]


class TestScoreBlendWeights:
    def test_default_weights_are_deterministic_leaning(self):
        from core.config import settings

        det = settings.AUDIT_DETERMINISTIC_SCORE_WEIGHT
        ai = settings.AUDIT_AI_SCORE_WEIGHT
        assert det >= ai, "deterministic weight should dominate for consistency"
        assert abs((det + ai) - 1.0) < 1e-6, "weights must sum to 1.0"

    def test_blend_formula_favours_deterministic_signal(self):
        from core.config import settings

        det_weight = settings.AUDIT_DETERMINISTIC_SCORE_WEIGHT
        ai_weight = settings.AUDIT_AI_SCORE_WEIGHT
        det_val, ai_val = 50.0, 90.0
        blended = round(det_weight * det_val + ai_weight * ai_val, 1)
        # With deterministic-leaning weights the blend stays closer to the
        # (reproducible) deterministic value than to the volatile AI value.
        assert abs(blended - det_val) <= abs(blended - ai_val)


class TestPartialAiScoreBlend:
    """A pillar the model did not score must not be blended as zero.

    `extract_score` coerces a missing pillar to 0.0 and a single numeric
    pillar used to switch the blend on for all three, so a deterministic SEO
    of 80 published 56 whenever the model omitted its SEO score. That is a
    24-point penalty for the model's silence on a dimension nobody assessed,
    and it is one of the reasons the same unchanged site scored differently
    run to run.
    """

    def test_an_unscored_pillar_keeps_its_deterministic_value(self):
        from audit_runner import blend_pillar_score

        assert (
            blend_pillar_score(
                deterministic=80.0,
                ai=0.0,
                ai_scored=False,
                det_weight=0.7,
                ai_weight=0.3,
            )
            is None
        )

    def test_a_scored_pillar_is_blended(self):
        from audit_runner import blend_pillar_score

        assert (
            blend_pillar_score(
                deterministic=80.0,
                ai=60.0,
                ai_scored=True,
                det_weight=0.7,
                ai_weight=0.3,
            )
            == 74.0
        )

    def test_a_pillar_the_model_genuinely_scored_zero_is_still_blended(self):
        from audit_runner import blend_pillar_score

        # The model looked and said zero: that is evidence, and 56 is right.
        assert (
            blend_pillar_score(
                deterministic=80.0,
                ai=0.0,
                ai_scored=True,
                det_weight=0.7,
                ai_weight=0.3,
            )
            == 56.0
        )

    def test_blended_values_stay_inside_the_valid_range(self):
        from audit_runner import blend_pillar_score

        assert (
            blend_pillar_score(
                deterministic=100.0, ai=1000.0, ai_scored=True, det_weight=0.7, ai_weight=0.3
            )
            == 100.0
        )
        assert (
            blend_pillar_score(
                deterministic=0.0, ai=-50.0, ai_scored=True, det_weight=0.7, ai_weight=0.3
            )
            == 0.0
        )

    def test_scored_dimensions_distinguishes_absence_from_a_real_zero(self):
        from audit_runner import ai_scored_dimensions

        scored = ai_scored_dimensions(
            {
                "seo_score": 0,
                "geo_score": {"score": 42},
                # aeo_score absent entirely
            }
        )
        assert scored == {"seo": True, "geo": True, "aeo": False}

    def test_an_unparseable_pillar_counts_as_unscored(self):
        from audit_runner import ai_scored_dimensions

        scored = ai_scored_dimensions(
            {"seo_score": "not a number", "geo_score": None, "aeo_score": 51.0}
        )
        assert scored == {"seo": False, "geo": False, "aeo": True}
