"""SIGV2-1276: a white-label report is handed to the agency's client, so it
must not expose our commercial relationship with the agency - no credit
consumption figures and no plan-upgrade wording - unless the credit figures
are explicitly opted back in. Assertions run on the rendered PDF text, not on
context flags, so a template change cannot reintroduce either leak silently.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest
from pypdf import PdfReader

from services.pdf_reports.assembler import build_report_context
from services.pdf_reports.renderer import render_pdf_from_template
from tests.test_pdf_report_render_baseline import (
    _FINANCIAL_REPORT_SUITE,
    _real_render_skip_reason,
    _squash,
)
from tests.test_pdf_report_renderer import _sample_audit_payload

_SKIP_REASON = _real_render_skip_reason() or ""
pytestmark = pytest.mark.skipif(bool(_SKIP_REASON), reason=_SKIP_REASON or "ok")


def _rendered_text(branding_mode: str | None, *, redacted=None) -> str:
    payload = _sample_audit_payload()
    financial_suite = {"financial_report": dict(_FINANCIAL_REPORT_SUITE["financial_report"])}
    if redacted is not None:
        financial_suite["financial_report"]["redacted"] = redacted
    else:
        financial_suite["financial_report"].pop("redacted", None)
    payload["metadata"]["report_suite"] = financial_suite
    payload["metadata"]["locked_sections"] = {
        "competitors": {
            "is_locked": True,
            "capability_key": "has_competitor_analysis",
            "required_plan": "plan_specialist",
            "required_plan_label": "Specialist",
            "detail": "Competitor benchmarks are not included on the current plan.",
            "lock_origin": "read",
        }
    }

    export_manifest = {"report_kind": "financial"}
    if branding_mode is not None:
        export_manifest["branding_mode"] = branding_mode

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01T00:00:00Z"},
        export_manifest=export_manifest,
    )
    pdf_bytes = render_pdf_from_template(
        template_name="white_label.html", context=context, deterministic=True
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return _squash("\n".join(page.extract_text() for page in reader.pages))


def test_white_label_render_hides_credit_figures_and_upgrade_wording():
    text = _rendered_text("white_label")

    # Denylist over the extracted text: nothing about credit metering, the
    # ledger, plan tiers, upgrades or disclosure state may reach a document
    # destined for the agency's client.
    for forbidden in ("CREDIT", "LEDGER", "PLAN", "UPGRADE", "TIER", "DISCLOSURE"):
        assert forbidden not in text.upper(), f"white-label report leaked {forbidden!r}"
    # The locked section is still listed as not included (honest scope), just
    # without plan language.
    assert "NOTINCLUDED" in text.upper()


def test_platform_render_keeps_credit_figures_and_upgrade_wording():
    text = _rendered_text(None)

    assert "TOTALCONSUMED" in text.upper()
    assert "CREDITS" in text.upper()
    assert "AVAILABLEONTHESPECIALISTPLAN" in text.upper()


def test_white_label_credit_figures_require_explicit_opt_in():
    text = _rendered_text("white_label", redacted=False)
    assert "TOTALCONSUMED" in text.upper()

    withheld = _rendered_text("white_label", redacted=True)
    assert "TOTALCONSUMED" not in withheld.upper()
