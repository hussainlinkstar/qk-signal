"""AEX-03: Verify sub-component scores are capped at [0, 100] after proportional scaling."""

from pathlib import Path
import sys


sys.path.append(str(Path(__file__).resolve().parents[1]))


def _scale_components(det_total, blended_total, components):
    """Replicate the scaling logic from audit_runner.py for isolated testing."""
    if det_total <= 0:
        return components, False
    ratio = blended_total / det_total
    capped_any = False
    result = {}
    for key, val in components.items():
        if isinstance(val, (int, float)):
            scaled = round(val * ratio, 1)
            clamped = max(0.0, min(100.0, scaled))
            if clamped != scaled:
                capped_any = True
            result[key] = clamped
        else:
            result[key] = val
    return result, capped_any


class TestSubComponentScoreCapping:
    """Ensure proportional scaling never produces values outside [0, 100]."""

    def test_high_ratio_caps_at_100(self):
        """det=30, blended=90 => ratio=3.0 — components should be capped at 100."""
        components = {"core_web_vitals": 60.0, "meta_optimization": 80.0, "mobile": 45.0}
        result, capped = _scale_components(30, 90, components)
        assert all(v <= 100.0 for v in result.values())
        assert capped is True
        # 60 * 3.0 = 180 -> capped to 100
        assert result["core_web_vitals"] == 100.0
        # 80 * 3.0 = 240 -> capped to 100
        assert result["meta_optimization"] == 100.0
        # 45 * 3.0 = 135 -> capped to 100
        assert result["mobile"] == 100.0

    def test_low_ratio_no_capping(self):
        """det=80, blended=85 => ratio=1.0625 — no capping needed."""
        components = {"core_web_vitals": 60.0, "meta_optimization": 70.0, "mobile": 50.0}
        result, capped = _scale_components(80, 85, components)
        assert capped is False
        assert result["core_web_vitals"] == round(60.0 * 85 / 80, 1)
        assert result["meta_optimization"] == round(70.0 * 85 / 80, 1)

    def test_ratio_exactly_one_no_change(self):
        """det=50, blended=50 => ratio=1.0 — no change."""
        components = {"a": 30.0, "b": 20.0}
        result, capped = _scale_components(50, 50, components)
        assert result == {"a": 30.0, "b": 20.0}
        assert capped is False

    def test_ratio_below_one_floors_at_zero(self):
        """If blended < det, scores shrink. Negative shouldn't occur, but verify floor."""
        components = {"a": 10.0, "b": 5.0}
        result, capped = _scale_components(100, 20, components)
        # 10 * 0.2 = 2.0, 5 * 0.2 = 1.0 — all valid
        assert all(v >= 0.0 for v in result.values())
        assert result["a"] == 2.0
        assert result["b"] == 1.0

    def test_zero_det_total_no_scaling(self):
        """Division by zero guard: det_total=0 should skip scaling."""
        components = {"a": 50.0}
        result, capped = _scale_components(0, 70, components)
        assert result == {"a": 50.0}  # unchanged
        assert capped is False

    def test_mixed_types_in_components(self):
        """Non-numeric values should pass through unchanged."""
        components = {"a": 50.0, "label": "good", "b": 30.0}
        result, capped = _scale_components(40, 80, components)
        assert result["label"] == "good"
        assert isinstance(result["a"], float)
        assert result["a"] <= 100.0

    def test_all_scores_clamped_to_bounds(self):
        """Every scaled value must be in [0.0, 100.0]."""
        components = {f"comp_{i}": float(i * 10) for i in range(1, 11)}
        for det in [10, 20, 50]:
            for blended in [5, 50, 95, 100]:
                result, _ = _scale_components(det, blended, components)
                for key, val in result.items():
                    assert 0.0 <= val <= 100.0, (
                        f"Component {key}={val} out of bounds " f"(det={det}, blended={blended})"
                    )
