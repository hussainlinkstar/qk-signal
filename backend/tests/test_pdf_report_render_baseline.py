"""Real-WeasyPrint render baseline for the PDF report suite.

tests/test_pdf_report_renderer.py monkeypatches `_load_weasyprint` in every
render test, so it asserts against a hardcoded `b"%PDF-1.7..."` literal and
would still pass with WeasyPrint uninstalled. This module deliberately does
not monkeypatch anything: it drives the real library end to end and pins what
a bad WeasyPrint bump would break.

What is pinned, per report kind:
  - structural validity (header, EOF marker, pypdf parses it, A4 page boxes)
  - the exact page count
  - text that must appear in the extracted content, including text that only
    exists inside the three inline SVG charts (services/pdf_reports/charts.py:
    radar, breakdown bar, trend line) and inside the two tables
    (partials/competitor_delta_table.html.j2, partials/financial_analysis.html.j2)
  - the reportlab chrome overlay, which stamps a header and a numbered footer
    on every page except the cover, so it moves with the page count

Baselines recorded against weasyprint 69.0 / pypdf 6.16.1 / reportlab 4.2.2.
If a dependency bump changes any number here, look at the rendered PDF before
changing the number.
"""

import io
import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from pypdf import PdfReader

from services.pdf_reports.assembler import build_report_context
from services.pdf_reports.renderer import _ENVIRONMENT, render_pdf_from_template
from tests.test_pdf_report_renderer import _sample_audit_payload


def _squash(value: str) -> str:
    """Drop all whitespace, so assertions survive glyph-run grouping noise.

    Page count is structural here (every `.report-section` has
    `break-before: page`) and was verified stable across five very different
    installed fonts, but PDF text extraction re-inserts or drops spaces
    depending on the font's kerning, so the SVG chart labels come back as
    "EntityClarity 30" with one font and "Entity Clarity 30" with another.
    Comparing without whitespace keeps the baseline honest without making it
    depend on which fonts the host happens to have.
    """
    return "".join(value.split())


def _real_render_skip_reason() -> str | None:
    """Return a skip reason when a real WeasyPrint render is impossible here.

    WeasyPrint needs native Pango/Cairo/GDK-PixBuf. The backend image installs
    them (see backend/Dockerfile), but a bare CI runner or a fresh dev box may
    not have them, and a missing shared library surfaces as an OSError from
    cffi at import time rather than as an ImportError.
    """
    try:
        from weasyprint import HTML
    except Exception as exc:
        return f"WeasyPrint is not importable ({type(exc).__name__}: {exc})"
    try:
        HTML(string="<p>probe</p>").write_pdf()
    except Exception as exc:
        return (
            "WeasyPrint cannot render, native Pango/Cairo libraries are missing or broken "
            f"({type(exc).__name__}: {exc})"
        )
    return None


_SKIP_REASON = _real_render_skip_reason()

pytestmark = pytest.mark.skipif(_SKIP_REASON is not None, reason=_SKIP_REASON or "")

_PROJECT_REPORT_SUITE = {
    "project_report": {
        "audit_count": 3,
        "coverage_start": "2026-01-01T00:00:00Z",
        "coverage_end": "2026-03-01T00:00:00Z",
        "delta": {"seo": 6, "geo": 5, "aeo": 4, "overall": 5},
        "trend_points": [
            {"date": "2026-01-01T00:00:00Z", "overall": 68, "seo": 69, "geo": 66, "aeo": 69},
            {"date": "2026-02-01T00:00:00Z", "overall": 71, "seo": 72, "geo": 69, "aeo": 71},
            {"date": "2026-03-01T00:00:00Z", "overall": 73, "seo": 75, "geo": 71, "aeo": 73},
        ],
        "task_status_summary": {"todo": 1, "in_progress": 1, "done": 2, "validated": 1},
        "task_movement": {"new": 2, "resolved": 1, "validated": 1},
        "validated_impact": [{"title": "Validated schema fix"}],
        "remaining_issues": ["Expand citations"],
    }
}

_FINANCIAL_REPORT_SUITE = {
    "financial_report": {
        "redacted": False,
        "budget_status": "healthy",
        "current_period": {
            "start": "2026-03-01T00:00:00Z",
            "end": "2026-03-31T00:00:00Z",
            "consumed_credits": 21,
            "remaining_credits": 79,
        },
        "recent_periods": [{"period_start": "2026-02-01T00:00:00Z", "consumed_credits": 18}],
        "ledger_rows": [
            {
                "date": "2026-03-02T00:00:00Z",
                "target": "example.com",
                "credits_consumed": 7,
                "estimated_credits": 9,
                "audit_type": "audit",
                "status": "completed",
            }
        ],
        "total_consumed_credits": 7,
        "run_count": 1,
    }
}

# The markers below only exist inside the inline SVG charts: the surrounding
# HTML never writes "AVERAGE SCORE", the axis tick row, or the mixed-case bar
# labels (the tables render those same components uppercased and spelled out,
# e.g. "SEMANTIC ENTITY DENSITY"). If WeasyPrint stops rasterising the SVG data
# URIs, these disappear while the rest of the page still renders.
_RADAR_SVG_TEXT = ["AVERAGE SCORE", "across all pillars"]
_BREAKDOWN_BAR_SVG_TEXT = ["Entity Clarity 81", "LLM Schema 77"]
_TREND_LINE_SVG_TEXT = [
    "0 20 40 60 80 100",
    "January 01, 2026 February 01, 2026 March 01, 2026",
    "GEO SEO AEO",
]

_BASELINES = [
    pytest.param(
        "white_label.html",
        None,
        "standard",
        None,
        # Check reports keep the same sections and pack them onto two pages.
        2,
        [
            "VISIBILITY REPORT",
            "How AI and search see your website",
            "Where you stand",
            "WHAT IS HOLDING EACH ONE BACK",
            "Questions people ask AI",
            "Trust signals",
            "SEO factors",
            "Actions",
            "Evidence",
            "INTEGRITY & CONFIDENCE CERTIFICATE",
        ],
        id="standard",
    ),
    pytest.param(
        "white_label.html",
        _PROJECT_REPORT_SUITE,
        "standard",
        {"report_kind": "project", "branding_mode": "platform", "hide_credit_cost": True},
        11,
        [
            "PROJECT AI VISIBILITY EXECUTIVE DIAGNOSTIC example.com",
            "Score change",
            "Trend over time",
            "Action status TO DO 1 IN PROGRESS 1 DONE 2 VALIDATED 1",
            *_RADAR_SVG_TEXT,
            *_TREND_LINE_SVG_TEXT,
        ],
        id="project",
    ),
    pytest.param(
        "white_label.html",
        _FINANCIAL_REPORT_SUITE,
        "standard",
        {"report_kind": "financial", "branding_mode": "platform", "hide_credit_cost": False},
        6,
        [
            "FINANCIAL AI VISIBILITY EXECUTIVE DIAGNOSTIC example.com",
            "Financial Summary TOTAL CONSUMED 7 credits RUNS RECORDED 1",
            "Report history DATE AUDIT TYPE TARGET ESTIMATED CONSUMED",
            "2026-03-02T00:00:00Z AUDIT example.com 9 7",
        ],
        id="financial",
    ),
    pytest.param(
        "battle.html",
        None,
        "battle",
        {
            "report_kind": "competitors",
            "branding_mode": "platform",
            "render_report_type": "battle",
            "hide_credit_cost": True,
        },
        9,
        [
            "COMPETITORS AI VISIBILITY BATTLE REPORT example.com",
            "How you rank against competitors RANK BRAND GEO VISIBILITY AEO SCORE ENTITY STRENGTH OVERALL SCORE",
            "1 Leader Corp 79.0 78.0 75.0 77.33",
            "2 example.com 71.0 76.0 71.0 72.67",
            "How your score changed",
            *_RADAR_SVG_TEXT,
            # Comparison series legend, radar SVG only.
            "Target Competitor",
        ],
        id="battle",
    ),
]


@pytest.mark.parametrize(
    "template_name,report_suite,report_type,export_manifest,expected_pages,expected_text",
    _BASELINES,
)
def test_render_pdf_from_template_real_weasyprint_baseline(
    template_name,
    report_suite,
    report_type,
    export_manifest,
    expected_pages,
    expected_text,
):
    payload = _sample_audit_payload()
    if report_suite is not None:
        payload["metadata"]["report_suite"] = report_suite

    context_kwargs = {
        # Explicit UTC instant, so the rendered dates do not depend on the
        # timezone of the machine running the suite.
        "agency_branding_data": {"generated_date": "2026-01-01T00:00:00Z"},
    }
    if export_manifest is not None:
        context_kwargs["export_manifest"] = export_manifest

    context = build_report_context(payload, report_type, **context_kwargs)
    pdf_bytes = render_pdf_from_template(
        template_name=template_name,
        context=context,
        deterministic=True,
    )

    assert pdf_bytes.startswith(b"%PDF-1.")
    assert b"%%EOF" in pdf_bytes[-1024:]

    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert not reader.is_encrypted
    assert len(reader.pages) == expected_pages

    pages = [_squash(page.extract_text()) for page in reader.pages]
    document_text = "\n".join(pages)
    for fragment in expected_text:
        assert _squash(fragment) in document_text, f"missing from rendered PDF: {fragment!r}"

    for index, page in enumerate(reader.pages):
        # A4 portrait, 595.28 x 841.89 pt.
        assert round(float(page.mediabox.width)) == 595
        assert round(float(page.mediabox.height)) == 842

        if index == 0:
            # The cover carries no reportlab chrome.
            assert "Page" not in pages[index]
            continue

        # reportlab chrome overlay: header target name, footer text, page number.
        assert "example.com" in pages[index]
        assert _squash("Generated by Qiko Signal - Intelligence Analyzer") in pages[index]
        assert _squash(f"Page {index}") in pages[index]


def test_withheld_sections_placeholder_renders_no_gated_content():
    """SIGV2-1019 AC3: locked sections render as withheld placeholders that
    carry only the section id, the public-safe detail and the plan label."""
    skip_reason = _real_render_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    payload = _sample_audit_payload()
    payload["metadata"]["locked_sections"] = {
        "competitors": {
            "is_locked": True,
            "capability_key": "has_competitor_analysis",
            "required_plan": "plan_specialist",
            "required_plan_label": "Specialist",
            "detail": "Competitor benchmarks and discovered rivals are locked on the current plan.",
            "lock_origin": "read",
        }
    }

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01T00:00:00Z"},
    )
    pdf_bytes = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
        deterministic=True,
    )

    reader = PdfReader(io.BytesIO(pdf_bytes))
    document_text = _squash("\n".join(page.extract_text() for page in reader.pages))

    # Placeholder is present with the allowed fields only.
    assert _squash("Sections not included in this report") in document_text
    assert _squash("locked on the current plan") in document_text
    assert "AVAILABLEONTHESPECIALISTPLAN" in document_text.upper()

    # Forbidden strings must not leak into the rendered artifact.
    for forbidden in (
        "has_competitor_analysis",
        "capability_key",
        "plan_specialist",
        "lock_origin",
        "Leader Corp",
    ):
        assert (
            _squash(forbidden).upper() not in document_text.upper()
        ), f"leaked into rendered PDF: {forbidden!r}"


_ARABIC_RE = re.compile(r"[؀-ۿ]")


def _embedded_font_names(reader: PdfReader) -> set[str]:
    names: set[str] = set()
    for page in reader.pages:
        resources = page.get("/Resources") or {}
        fonts = resources.get("/Font") or {}
        for font_ref in fonts.values():
            font = font_ref.get_object()
            base = font.get("/BaseFont")
            if base:
                names.add(str(base))
            descendant = font.get("/DescendantFonts")
            if descendant:
                for sub in descendant:
                    sub_font = sub.get_object()
                    sub_base = sub_font.get("/BaseFont")
                    if sub_base:
                        names.add(str(sub_base))
    return names


def test_arabic_report_renders_rtl_with_arabic_glyphs():
    """ar projects render RTL: Arabic catalog text, an embedded Arabic font,
    and machine values (URLs, scores) kept in LTR order."""
    skip_reason = _real_render_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    payload = _sample_audit_payload()
    payload["metadata"]["language"] = "ar"

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={
            "generated_date": "2026-01-01T00:00:00Z",
        },
    )
    assert context["language"] == "ar"
    assert context["is_rtl"] is True
    assert context["is_cjk"] is False
    assert context["labels"]["target"] == "الهدف"

    pdf_bytes = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
        deterministic=True,
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    document_text = "\n".join(page.extract_text() for page in reader.pages)

    # Arabic text is in the render: shaped Arabic glyphs always extract to
    # Arabic-script codepoints (ToUnicode may substitute a few letters per
    # font, but never outside the script).
    assert _ARABIC_RE.search(document_text), "no Arabic glyphs extracted"

    # The Arabic font stack resolved to a real font and no replacement
    # characters leaked through. Font names differ per host (Noto Naskh
    # Arabic in the container, system fallbacks elsewhere), so assert a real
    # embedded font rather than a specific family.
    font_names = _embedded_font_names(reader)
    assert font_names, "no fonts embedded in the rendered PDF"
    assert "�" not in document_text

    # Machine-readable values survive: the URL stays intact and LTR.
    assert "example.com" in document_text

    # Exact-string assertions live on the rendered HTML: which Unicode
    # characters a shaped Arabic run extracts to depends on the resolved
    # font's ToUnicode coverage, so pypdf cannot be trusted to reproduce a
    # specific Arabic string across environments.
    html = _ENVIRONMENT.get_template("white_label.html").render(**{"fonts_uri": "", **context})
    # Shaped Arabic arrives in visual order, so match the script, not a
    # specific logical-order string.
    assert re.search(r"[؀-ۿ]", html)
    assert 'dir="rtl"' in html
    assert 'lang="ar"' in html


def test_arabic_mixed_content_document():
    """Arabic, Latin and URL content in one report extract cleanly."""
    skip_reason = _real_render_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    payload = _sample_audit_payload()
    payload["metadata"]["language"] = "ar-AE"
    payload["suggestions"][0]["title"] = "تحسين Schema على https://example.com/faq"
    payload["suggestions"][0]["summary"] = "إضافة بيانات منظمة عربية Arabic schema data."

    context = build_report_context(
        payload,
        "standard",
        agency_branding_data={"generated_date": "2026-01-01T00:00:00Z"},
    )
    pdf_bytes = render_pdf_from_template(
        template_name="white_label.html",
        context=context,
        deterministic=True,
    )
    reader = PdfReader(io.BytesIO(pdf_bytes))
    document_text = _squash("\n".join(page.extract_text() for page in reader.pages))

    assert _ARABIC_RE.search(document_text)
    assert "example.com" in document_text
    assert "�" not in document_text

    # Latin embedded inside an RTL-shaped run extracts differently (or not
    # at all) depending on which Arabic font fontconfig resolves, because
    # ToUnicode coverage varies per font: DecoType Naskh on macOS exposes
    # the Latin glyphs, Noto Naskh in the container does not. The visual
    # render is correct in both, so the mixed-content assertions go on the
    # rendered HTML, which is font-independent and fails if the strings
    # never reach the document.
    html = _ENVIRONMENT.get_template("white_label.html").render(**context)
    assert "https://example.com/faq" in html
    assert "تحسين Schema على" in html
    assert "Arabic schema data." in html


def test_report_language_precedence_project_preference_survives_ui_locale():
    """AC1: the reporting preference is resolved from explicit language, then
    project preference, then fallback. A UI-locale-only change sends no
    explicit language and must not overwrite a saved project preference."""
    from routers.api_router import _resolve_report_language_for_audits
    from types import SimpleNamespace

    audit = SimpleNamespace(
        project=SimpleNamespace(language="ar"),
        full_report={"metadata": {"language": "en"}},
    )

    # No explicit language (UI locale toggles do not send one): the saved
    # project preference wins over the audit's own English metadata.
    assert _resolve_report_language_for_audits([audit]) == "ar"

    # Explicit request language is the only override and still wins.
    assert _resolve_report_language_for_audits([audit], explicit_language="en") == "en"
    assert _resolve_report_language_for_audits([audit], explicit_language="ar-EG") == "ar"

    # Without a project preference the audit metadata is used.
    orphan = SimpleNamespace(project=None, full_report={"metadata": {"language": "ro"}})
    assert _resolve_report_language_for_audits([orphan]) == "ro"
    empty = SimpleNamespace(project=None, full_report={})
    assert _resolve_report_language_for_audits([empty]) == "en"
