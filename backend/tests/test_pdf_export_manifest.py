import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from job_models import parse_pdf_job_payload
from services.pdf_reports import resolve_export_manifest


def test_resolve_export_manifest_prefers_explicit_report_controls() -> None:
    manifest = resolve_export_manifest(
        explicit_report_kind="financial",
        explicit_branding_mode="platform",
        explicit_report_type="standard",
        template_type="Executive",
        hide_credit_cost=True,
    )

    assert manifest == {
        "report_kind": "financial",
        "branding_mode": "platform",
        "competitor_mode": None,
        "hide_credit_cost": True,
        "legacy_report_type": "standard",
        "render_report_type": "standard",
        "template_type": "Executive",
    }


def test_resolve_export_manifest_defaults_competitor_mode_for_competitor_reports() -> None:
    manifest = resolve_export_manifest(
        explicit_report_kind="competitors",
        explicit_branding_mode="platform",
        template_type="Comparative",
        hide_credit_cost=False,
    )

    assert manifest["report_kind"] == "competitors"
    assert manifest["branding_mode"] == "platform"
    assert manifest["competitor_mode"] == "latest"
    assert manifest["hide_credit_cost"] is False
    assert manifest["render_report_type"] == "battle"


def test_parse_pdf_job_payload_preserves_export_manifest() -> None:
    payload = parse_pdf_job_payload(
        {
            "job_id": "job-123",
            "user_id": 9,
            "template_type": "Executive",
            "audit_ids": [101],
            "options": {"report_kind": "standard"},
            "branding_config": {"report_kind": "standard"},
            "export_manifest": {
                "report_kind": "standard",
                "branding_mode": "platform",
                "competitor_mode": None,
                "hide_credit_cost": True,
                "legacy_report_type": "standard",
                "render_report_type": "standard",
                "template_type": "Executive",
            },
        }
    )

    assert payload.export_manifest is not None
    assert payload.export_manifest["report_kind"] == "standard"
    assert payload.export_manifest["branding_mode"] == "platform"
    assert payload.export_manifest["hide_credit_cost"] is True
