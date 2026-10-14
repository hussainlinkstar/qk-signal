import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from admin import (
    _extract_credits_used,
    _get_audit_report_metadata,
    _resolve_audit_score,
)
from models import Audit


def _audit() -> Audit:
    return Audit(geo_score=12, seo_score=34, aeo_score=56)


def test_resolve_audit_score_prefers_canonical_scores_block() -> None:
    report = {"scores": {"seo": 45, "geo": 25, "aeo": 75}}
    audit = _audit()

    assert _resolve_audit_score(audit, report, "seo") == 45
    assert _resolve_audit_score(audit, report, "geo") == 25
    assert _resolve_audit_score(audit, report, "aeo") == 75


def test_resolve_audit_score_falls_back_to_legacy_sections() -> None:
    report = {
        "seo": {"onpage": 61},
        "geo": {"visibility_index": 49},
        "aeo": {"answerability_score": 73},
    }

    assert _resolve_audit_score(_audit(), report, "seo") == 61
    assert _resolve_audit_score(_audit(), report, "geo") == 49
    assert _resolve_audit_score(_audit(), report, "aeo") == 73


def test_report_metadata_supports_model_fallback_and_credits_extraction() -> None:
    report = {"metadata": {"model": "gpt-5.4", "credits_used": 2}}

    provider, tier, has_screenshot = _get_audit_report_metadata(report)

    assert provider == "gpt-5.4"
    assert tier is None
    assert has_screenshot is False
    assert _extract_credits_used(report) == 2
