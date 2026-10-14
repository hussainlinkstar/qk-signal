from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from routers import api_router


def _build_audit_record(*, competitors: list[dict] | None = None):
    return SimpleNamespace(
        full_report={
            "metadata": {
                "title": "alpha",
                "language": "en",
            },
            "analysis": {
                "summary": "Primary benchmark summary.",
            },
            "geo": {"score": 80},
            "seo": {"score": 82},
            "aeo": {"score": 79},
            "competitors": competitors or [],
        },
        created_at=datetime(2026, 3, 8, tzinfo=timezone.utc),
        url="https://alpha.example.com/page-1",
        target_url="https://alpha.example.com/page-1",
        target_name="Alpha",
        target_metadata={"industry": "SaaS"},
        audit_target_type="website",
        audit_type="DEEP",
        user=SimpleNamespace(
            subscription=SimpleNamespace(plan_type="plan_specialist", status="active"),
            trial_plan=None,
        ),
    )


def _build_options(**overrides):
    payload = {
        "sections": ["overview", "geo", "seo", "aeo"],
        "primary_color": "#0EA5E9",
        "secondary_color": "#E2E8F0",
        "language": "en",
        "comparison_competitor_name": None,
        "comparison_competitor_rank": None,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def test_build_complex_report_pdf_uses_canonical_competitor_summary(
    monkeypatch: pytest.MonkeyPatch,
):
    captured: dict[str, object] = {}

    def _fake_render_battle_report_pdf(**kwargs):
        captured.update(kwargs)
        return b"pdf"

    monkeypatch.setattr(api_router, "render_battle_report_pdf", _fake_render_battle_report_pdf)

    audit = _build_audit_record(
        competitors=[
            {
                "name": "Competitor A",
                "score": 64,
                "source": "serp",
                "confidence_score": 0.91,
                "geo_visibility": 69,
                "aeo_score": 61,
                "entity_strength": 58,
                "rank": 1,
            }
        ]
    )

    pdf_bytes = api_router._build_complex_report_pdf(
        selected_audits=[audit],
        template_type="Comparative",
        options=_build_options(
            comparison_competitor_name="Competitor A", comparison_competitor_rank=1
        ),
        user=SimpleNamespace(),
    )

    assert pdf_bytes == b"pdf"
    assert captured["left_title"] == "Alpha"
    assert captured["right_title"] == "Competitor A"

    right_full_report = captured["right_full_report"]
    assert right_full_report["scores"]["overall"] == 64
    assert right_full_report["scores"]["geo"] == 69
    assert right_full_report["scores"]["aeo"] == 61
    assert right_full_report["metadata"]["entity_analysis"]["entity_clarity_score"] == 58
    assert (
        right_full_report["metadata"]["competitor_summary"]["derived_from_canonical_competitor"]
        is True
    )
    assert "Competitor A benchmark snapshot" in right_full_report["metadata"]["executive_summary"]


def test_build_complex_report_pdf_requires_canonical_competitor_summary():
    audit = _build_audit_record(competitors=[])

    with pytest.raises(ValueError, match="does not contain competitor data"):
        api_router._build_complex_report_pdf(
            selected_audits=[audit],
            template_type="Comparative",
            options=_build_options(),
            user=SimpleNamespace(),
        )
