from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from services import audit_normalization_service


def _make_audit() -> models.Audit:
    return models.Audit(
        user_id=1,
        url="https://isolation.example.com/",
        geo_score=60,
        seo_score=70,
        aeo_score=40,
        full_report={
            "analysis": {
                "seo_score": 70,
                "geo_score": 60,
                "aeo_score": 40,
                "summary": "isolation target",
            },
        },
        created_at=datetime.now(timezone.utc),
    )


def test_one_failing_attach_does_not_break_other_metadata_views(monkeypatch) -> None:
    """A raising attach_* view is isolated: the audit report still returns with the
    other additive metadata views applied (one view can't 500 the whole audit)."""

    def _boom(report, **_kwargs):
        raise RuntimeError("simulated advisor failure")

    # Make the middle attach (advisor) raise; aio + search_types must still apply.
    monkeypatch.setattr(audit_normalization_service, "attach_advisor_view", _boom)

    report = audit_normalization_service.build_normalized_audit_report(_make_audit())

    metadata = report["metadata"]
    # The failing view is simply absent; the others survive.
    assert "advisor" not in metadata
    assert "aio" in metadata
    assert "search_types" in metadata


def test_all_attaches_present_on_happy_path() -> None:
    report = audit_normalization_service.build_normalized_audit_report(_make_audit())
    metadata = report["metadata"]
    assert "aio" in metadata
    assert "advisor" in metadata
    assert "search_types" in metadata
