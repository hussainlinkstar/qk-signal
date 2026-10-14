from datetime import datetime, timezone
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.pdf_reports.filenames import resolve_pdf_export_filename


def test_resolve_pdf_export_filename_uses_requested_convention():
    filename = resolve_pdf_export_filename(
        project_name="Lavan Events",
        audit_type="DEEP",
        report_type="Executive",
        report_kind="executive",
        timestamp=datetime(2026, 3, 8, 10, 5, 7, tzinfo=timezone.utc),
    )

    assert filename == "Lavan Events_Executive_20260308T100507Z.pdf"


def test_resolve_pdf_export_filename_sanitizes_invalid_characters_and_fallbacks():
    filename = resolve_pdf_export_filename(
        project_name=" Project:/Name* ",
        audit_type="",
        report_type="Comparative?",
        timestamp=datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
    )

    assert filename == "Project--Name_Audit_Comparative_20260101T000000Z.pdf"


def test_resolve_pdf_export_filename_falls_back_to_legacy_components_without_report_kind():
    filename = resolve_pdf_export_filename(
        project_name="Acme",
        audit_type="Lite",
        report_type="Battle",
        timestamp=datetime(2026, 2, 2, 12, 0, 0, tzinfo=timezone.utc),
    )

    assert filename == "Acme_Lite_Battle_20260202T120000Z.pdf"
