"""HTML escaping guarantees for the PDF report templates (SIGV2-1224).

The report templates are named `*.html.j2`, so a `select_autoescape` call
that only lists the `html` and `xml` extensions matches on the trailing
`.j2` and leaves every one of them unescaped. The entry templates
(`white_label.html`, `battle.html`) happened to be escaped because their own
name ends in `.html`, but Jinja decides autoescaping per template, so the
shared base and every partial rendered through `{% include %}` were not.

These tests pin the behaviour at both ends: the environment must select
autoescaping for every report template it can load, and persisted
audit-derived text carrying HTML metacharacters must reach the rendered
document as text rather than as markup, in LTR, RTL and mixed-direction
reports.
"""

from __future__ import annotations

import io
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.pdf_reports.assembler import build_report_context
from services.pdf_reports.renderer import _ENVIRONMENT, _TEMPLATE_DIR, render_pdf_from_template
from tests.test_pdf_report_renderer import _sample_audit_payload


# Harmless markup only: an element that would be structural if it were
# parsed, plus an attribute-bearing element and the bare metacharacters.
# Nothing here fetches anything, and no test renders it into a browser.
_MARKUP = "<script>alert(1)</script><img src=x onerror=y><b>bold</b>"
_METACHARS = "& < > \" '"
_PAYLOAD = f"{_MARKUP} {_METACHARS}"

_FSI = "\u2068"
_PDI = "\u2069"


class _ElementCollector(HTMLParser):
    """Collect tag names and attribute names from a rendered document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attrs: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        for name, _value in attrs:
            self.attrs.add(name)

    handle_startendtag = handle_starttag


def _collect(html: str) -> _ElementCollector:
    parser = _ElementCollector()
    parser.feed(html)
    parser.close()
    return parser


def _poisoned_payload(language: str | None = None) -> dict:
    """A stored audit whose persisted free-text fields carry metacharacters.

    Only fields that are genuinely free text in the canonical contract are
    poisoned. `suggestions[].category` is a literal enum and is rejected by
    `AuditResult` validation before it ever reaches a template, which is
    worth knowing: not every "dynamic" field is attacker-shaped.
    """
    payload = _sample_audit_payload()
    payload["target"]["name"] = f"Acme {_PAYLOAD}"
    payload["suggestions"][0]["title"] = f"Add FAQ schema {_PAYLOAD}"
    payload["suggestions"][0]["summary"] = f"Publish JSON-LD {_PAYLOAD}"
    payload["suggestions"][0]["action"] = f"Publish {_PAYLOAD}"
    payload["metadata"]["neural_executive_summary"] = f"Summary {_PAYLOAD}"
    payload["metadata"]["market_dominance_blueprint"] = f"Blueprint {_PAYLOAD}"
    payload["metadata"]["strategic_intelligence_grid"][0]["agent_correlation"] = (
        f"Correlation {_PAYLOAD}"
    )
    if language is not None:
        payload["metadata"]["language"] = language
    return payload


def _render_html(template_name: str, payload: dict) -> str:
    context = build_report_context(
        payload,
        "battle" if template_name == "battle.html" else "standard",
        agency_branding_data={"generated_date": "2026-01-01T00:00:00Z"},
    )
    template = _ENVIRONMENT.get_template(template_name)
    return template.render(**{"fonts_uri": "", **context})


def _report_template_names() -> list[str]:
    names = []
    for path in sorted(_TEMPLATE_DIR.rglob("*")):
        if not path.is_file():
            continue
        name = path.relative_to(_TEMPLATE_DIR).as_posix()
        if name.endswith(".css.j2"):
            # Stylesheet, read as raw text and never rendered by Jinja.
            continue
        names.append(name)
    return names


@pytest.mark.parametrize("template_name", _report_template_names())
def test_every_report_template_selects_autoescaping(template_name: str):
    assert _ENVIRONMENT.autoescape(template_name) is True, (
        f"{template_name} is loaded without autoescaping; every value it "
        "renders would reach the document as markup"
    )


def test_every_email_template_selects_autoescaping():
    """The other Jinja environment in the backend, checked for the same trap.

    Its templates are named `*.html`, so it was never affected, but the
    selection is pinned here so a `.j2`-suffixed email template cannot
    reintroduce the problem unnoticed.
    """
    from services.email_templates import TEMPLATE_DEFINITIONS, env as email_env

    assert TEMPLATE_DEFINITIONS
    for key, definition in TEMPLATE_DEFINITIONS.items():
        assert (
            email_env.autoescape(definition.html_template) is True
        ), f"email template {definition.html_template} ({key}) is not autoescaped"
    assert email_env.autoescape("future_template.html.j2") is True


@pytest.mark.parametrize("template_name", ["white_label.html", "battle.html"])
def test_persisted_metacharacters_render_as_text_not_markup(template_name: str):
    html = _render_html(template_name, _poisoned_payload())

    assert _MARKUP not in html
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    # The word "onerror" still appears, as escaped text inside an element's
    # content. What must not happen is it becoming an attribute, so the
    # check is on the parsed document, not on the raw string.
    collected = _collect(html)
    assert "script" not in collected.tags
    assert "onerror" not in collected.attrs
    # The poisoned `<b>` must not become a real element either.
    assert "b" not in collected.tags


def test_escaping_keeps_the_poisoned_text_readable():
    """Escaped output still carries the original characters as content."""
    html = _render_html("white_label.html", _poisoned_payload())

    parser = HTMLParser()
    chunks: list[str] = []
    parser.handle_data = chunks.append  # type: ignore[method-assign]
    parser.feed(html)
    parser.close()

    text = " ".join(chunks)
    assert "<script>alert(1)</script>" in text
    assert "Add FAQ schema" in text


def test_intentional_markup_survives_escaping():
    """Structure the templates own is untouched: charts, logos, headings."""
    html = _render_html("white_label.html", _poisoned_payload())
    collected = _collect(html)

    for tag in ("html", "head", "style", "body", "section", "h1", "h2", "img"):
        assert tag in collected.tags, f"template structure lost: <{tag}>"
    # Inline base64 logo/chart data URIs are unaffected by attribute escaping.
    assert 'src="data:image/' in html
    assert "&amp;lt;" not in html, "double escaping detected"
    # The `<style>` block only interpolates the percent-encoded fonts URI,
    # which carries no HTML metacharacters, so the CSS is byte-identical.
    assert "@font-face" in html
    assert "&amp;" not in html.split("</style>", 1)[0]


@pytest.mark.parametrize("language", ["en", "ar", "ar-AE"])
def test_bidi_isolate_filter_does_not_bypass_escaping(language: str):
    """The `bi` filter returns a plain string, so Jinja must still escape it.

    RTL reports wrap narrative text in first-strong isolate controls. Those
    controls are Unicode, not markup, and the wrapping must not hand Jinja a
    value it treats as already-safe.
    """
    payload = _poisoned_payload(language=language)
    payload["suggestions"][0]["summary"] = f"إضافة بيانات منظمة {_PAYLOAD} schema data."
    html = _render_html("white_label.html", payload)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    collected = _collect(html)
    assert "script" not in collected.tags
    assert "onerror" not in collected.attrs

    if language == "en":
        # No RTL report language, so no isolate controls are introduced.
        assert _FSI not in html
        assert _PDI not in html
    else:
        # Direction isolation is still applied on top of the escaped value.
        assert _FSI in html and _PDI in html
        assert 'dir="rtl"' in html
    assert "إضافة بيانات منظمة" in html


def _real_render_skip_reason() -> str | None:
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - environment dependent
        return f"WeasyPrint is not importable ({type(exc).__name__}: {exc})"
    try:
        HTML(string="<p>probe</p>").write_pdf()
    except Exception as exc:  # pragma: no cover - environment dependent
        return (
            "WeasyPrint cannot render, native Pango/Cairo libraries are missing or broken "
            f"({type(exc).__name__}: {exc})"
        )
    return None


def test_metacharacters_reach_the_rendered_pdf_as_visible_text():
    """End to end through real WeasyPrint: the markup is printed, not parsed.

    The assertion deliberately sits on the suggestion title, which renders
    inside `partials/standard_analysis.html.j2`. The cover is written by
    `white_label.html`, whose own name already selected autoescaping, so a
    cover-only assertion would have passed before the fix.
    """
    skip_reason = _real_render_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    from pypdf import PdfReader

    payload = _poisoned_payload()
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
    document_text = "".join("".join(page.extract_text().split()) for page in reader.pages)

    assert "AddFAQschema<script>alert(1)</script>" in document_text
    assert "<b>bold</b>" in document_text


def test_injected_image_reference_is_not_fetched_into_the_report(tmp_path):
    """No resource named by persisted text is resolved during rendering.

    This is the one effect that was reproducible rather than theoretical.
    WeasyPrint resolves `src` attributes while it rasterises the page, so an
    unescaped `<img>` in a stored field became a real element and its target
    was read and drawn into the PDF. The probe is a local file, so the test
    never touches the network, but the same fetcher handles http(s).
    """
    skip_reason = _real_render_skip_reason()
    if skip_reason:
        pytest.skip(skip_reason)

    from pypdf import PdfReader

    probe = tmp_path / "probe.svg"
    probe.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="40">'
        '<text x="0" y="30" font-size="20">PROBEFETCHED</text></svg>',
        encoding="utf-8",
    )

    payload = _sample_audit_payload()
    payload["suggestions"][0]["title"] = (
        f'Add FAQ schema <img src="{probe.as_uri()}" width="200" height="40" />'
    )
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
    document_text = "".join("".join(page.extract_text().split()) for page in reader.pages)

    assert "PROBEFETCHED" not in document_text
    # The reference is still visible, as the text it always was.
    assert "probe.svg" in document_text
