from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, pass_context, select_autoescape

from services.pdf_reports.labels import report_label
from services.report_i18n_service import is_rtl_report_language


_PDF_CREATION_DATE_RE = re.compile(rb"/CreationDate\s*\(D:[^\)]*\)")
_PDF_MOD_DATE_RE = re.compile(rb"/ModDate\s*\(D:[^\)]*\)")
_PDF_ID_RE = re.compile(rb"/ID\s*\[<[^>]*>\s*<[^>]*>\]")
_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

# Autoescaping is selected per template name, and the report templates are
# named `*.html.j2`, so a bare ("html", "xml") selection matches on the
# trailing `.j2` and silently leaves them unescaped. Only the two entry
# templates (`white_label.html`, `battle.html`) were covered; the shared base
# and every included partial were not, which is where almost all persisted
# audit text is rendered. The `.j2` suffixes are listed explicitly and the
# default is True, so a template added under a name nobody anticipated
# escapes rather than silently stops escaping.
_ENVIRONMENT = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "xml", "html.j2", "htm.j2", "xml.j2", "j2"),
        default_for_string=True,
        default=True,
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)


@pass_context
def _template_label(context: Any, text: str | None) -> str | None:
    language = context.get("language") or "en"
    return report_label(language, text)


_ENVIRONMENT.globals["l"] = _template_label


@pass_context
def _bidi_isolate(context: Any, text: Any) -> Any:
    """Wrap a content string in first-strong isolate controls.

    Narrative fields keep their source language in localized reports; the
    isolate lets an English paragraph inside an RTL page (or vice versa)
    keep its own internal direction, so terminal punctuation stays at the
    end of the run instead of jumping to the paragraph edge. Only applied
    for RTL report languages, where the paragraph base direction differs
    from the content's own direction.
    """
    if not text or not isinstance(text, str):
        return text
    language = context.get("language") or "en"
    if not is_rtl_report_language(language):
        return text
    if text.startswith("⁨"):
        return text
    return f"⁨{text}⁩"


_ENVIRONMENT.filters["bi"] = _bidi_isolate


def _normalize_pdf_bytes(pdf_bytes: bytes) -> bytes:
    normalized = _PDF_CREATION_DATE_RE.sub(b"/CreationDate (D:20240101000000Z)", pdf_bytes)
    normalized = _PDF_MOD_DATE_RE.sub(b"/ModDate (D:20240101000000Z)", normalized)
    normalized = _PDF_ID_RE.sub(
        b"/ID [<00000000000000000000000000000000> <00000000000000000000000000000000>]",
        normalized,
    )
    return normalized


def _load_weasyprint() -> tuple[type | None, type | None]:
    try:
        from weasyprint import CSS as WeasyCSS, HTML as WeasyHTML
    except Exception:
        return None, None
    return WeasyCSS, WeasyHTML


def _build_stylesheet() -> str:
    return (_TEMPLATE_DIR / "report.css.j2").read_text(encoding="utf-8")


def _fonts_uri() -> str:
    return (_TEMPLATE_DIR.parent / "assets" / "fonts").as_uri()


def _apply_chrome_overlay(
    body_pdf: bytes,
    context: dict[str, Any],
) -> bytes:
    """Merge reportlab full-bleed header/footer onto every page after the cover.

    Falls back to the raw WeasyPrint output if pypdf or reportlab are
    unavailable, or if the input PDF cannot be parsed (e.g. in tests
    with dummy WeasyPrint stubs).
    """
    try:
        from pypdf import PdfReader, PdfWriter
        from services.pdf_reports.chrome_overlay import build_chrome_overlay
    except Exception:
        return body_pdf

    branding = context.get("branding", {})
    target = context.get("target", {})
    labels = context.get("labels", {})

    try:
        reader = PdfReader(io.BytesIO(body_pdf))
    except Exception:
        return body_pdf

    writer = PdfWriter()

    for idx, page in enumerate(reader.pages):
        if idx == 0:
            # Cover page, no header/footer chrome
            writer.add_page(page)
            continue

        # Page numbers: cover is conceptually page 0, content starts at 1
        page_num = idx

        overlay_bytes = build_chrome_overlay(
            branding,
            target,
            labels,
            page_number=page_num,
        )
        overlay_reader = PdfReader(io.BytesIO(overlay_bytes))
        overlay_page = overlay_reader.pages[0]

        # Merge the chrome overlay on top of the content page
        page.merge_page(overlay_page)
        writer.add_page(page)

    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def render_pdf_from_template(
    *,
    template_name: str,
    context: dict[str, Any],
    deterministic: bool = False,
) -> bytes:
    css_class, html_class = _load_weasyprint()
    if css_class is None or html_class is None:
        raise RuntimeError("WeasyPrint is required for PDF rendering.")

    stylesheet = css_class(string=_build_stylesheet())
    template = _ENVIRONMENT.get_template(template_name)
    html = template.render(**{"fonts_uri": _fonts_uri(), **context})
    pdf_bytes = html_class(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf(
        stylesheets=[stylesheet]
    )

    # Apply full-bleed header/footer chrome via reportlab overlay
    pdf_bytes = _apply_chrome_overlay(pdf_bytes, context)

    if deterministic:
        return _normalize_pdf_bytes(pdf_bytes)
    return pdf_bytes
