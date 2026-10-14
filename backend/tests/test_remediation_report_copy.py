from copy import deepcopy

import pytest

from services.pdf_reports.assembler import build_report_context
from services.pdf_reports.renderer import _ENVIRONMENT
from tests.test_pdf_report_renderer import _sample_audit_payload


def _project_context(language, impact):
    payload = _sample_audit_payload()
    payload["metadata"]["report_suite"] = {
        "project_report": {
            "coverage_start": "2026-01-01T00:00:00Z",
            "coverage_end": "2026-03-01T00:00:00Z",
            "task_movement": {"new": 2, "resolved": 1, "validated": 1},
            "task_status_summary": {"todo": 1, "done": 2, "validated": 1},
            "validated_impact": impact,
        }
    }
    original = deepcopy(payload)
    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"language": language},
        export_manifest={"report_kind": "project", "branding_mode": "platform"},
    )
    assert payload == original
    return context


@pytest.mark.parametrize(
    "language,headings",
    [
        ("en", ("Action progress", "Action status", "Action verification")),
        ("ar", ("تقدم الإجراءات", "حالة الإجراءات", "التحقق من الإجراءات")),
    ],
)
def test_project_report_uses_localized_action_copy(language, headings):
    context = _project_context(language, [])
    html = _ENVIRONMENT.get_template("partials/project_analysis.html.j2").render(**context)
    for heading in headings:
        assert heading in html
        assert heading in " ".join(row["label"] for row in context["toc_entries"])
    assert "Current tasks" not in html
    assert "Proven impact" not in html
    assert "New tasks" not in html


@pytest.mark.parametrize(
    "status,expected",
    [
        ("validated", "No longer reported in a later audit."),
        ("pending_validation", "Awaiting a later audit."),
        ("", "Awaiting a later audit."),
    ],
)
def test_report_verification_does_not_attribute_whole_audit_uplift(status, expected):
    context = _project_context(
        "en",
        [
            {
                "title": "Schema fix",
                "verification_status": status,
                "narrative": "Fixing Schema fix improved SEO by +25.",
                "delta": {"seo": 25},
            }
        ],
    )
    html = _ENVIRONMENT.get_template("partials/project_analysis.html.j2").render(**context)
    assert expected in html
    assert "improved SEO" not in html
    assert "+25" not in html
    assert "Current verification of completed actions." in html
    assert "Current project status." in html
    assert "2026" in html


@pytest.mark.parametrize(
    "language,empty_copy",
    [
        ("en", "No action verification results yet."),
        ("ar", "لا توجد نتائج للتحقق من الإجراءات حتى الآن."),
    ],
)
def test_empty_verification_does_not_claim_period_scoped_impact(language, empty_copy):
    context = _project_context(language, [])
    html = _ENVIRONMENT.get_template("partials/project_analysis.html.j2").render(**context)
    assert empty_copy in html
    assert "No validated task impact" not in html
