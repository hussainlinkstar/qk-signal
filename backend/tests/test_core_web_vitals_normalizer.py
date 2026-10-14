import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.seo.performance_service import normalize_core_web_vitals


def test_normalize_core_web_vitals_uses_lighthouse_audits():
    pagespeed_result = {
        "lighthouseResult": {
            "audits": {
                "largest-contentful-paint": {"numericValue": 2200},
                "cumulative-layout-shift": {"numericValue": 0.2},
                "first-contentful-paint": {"numericValue": 4000},
            }
        }
    }

    normalized = normalize_core_web_vitals(pagespeed_result)

    assert normalized["lcp"] == {
        "value": 2200.0,
        "status": "good",
        "target_threshold": 2500,
        "unit": "ms",
    }
    assert normalized["cls"] == {
        "value": 0.2,
        "status": "needs_improvement",
        "target_threshold": 0.1,
        "unit": "score",
    }
    assert normalized["fcp"] == {
        "value": 4000.0,
        "status": "bad",
        "target_threshold": 1800,
        "unit": "ms",
    }


def test_normalize_core_web_vitals_falls_back_to_loading_experience():
    pagespeed_result = {
        "loadingExperience": {
            "metrics": {
                "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 3500},
                "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 50},
                "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1200},
            }
        }
    }

    normalized = normalize_core_web_vitals(pagespeed_result)

    assert normalized["lcp"]["status"] == "needs_improvement"
    assert normalized["lcp"]["value"] == 3500.0
    assert normalized["cls"]["status"] == "bad"
    assert normalized["cls"]["value"] == 0.5
    assert normalized["fcp"]["status"] == "good"
    assert normalized["fcp"]["value"] == 1200.0
