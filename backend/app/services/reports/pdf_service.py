from __future__ import annotations

import re
from dataclasses import dataclass

CSS = None
HTML = None

_HEX_COLOR_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")
_PDF_CREATION_DATE_RE = re.compile(rb"/CreationDate\s*\(D:[^\)]*\)")
_PDF_MOD_DATE_RE = re.compile(rb"/ModDate\s*\(D:[^\)]*\)")
_PDF_ID_RE = re.compile(rb"/ID\s*\[<[^>]*>\s*<[^>]*>\]")


@dataclass(slots=True)
class WhiteLabelBranding:
    company_name: str = ""
    logo_url: str | None = None
    primary_color: str = "#00040e"
    secondary_color: str = "#E2E8F0"
    text_color: str = "#00040e"


def _normalize_hex_color(color: str, fallback: str) -> str:
    cleaned = (color or "").strip()
    if not _HEX_COLOR_RE.match(cleaned):
        return fallback
    return cleaned if cleaned.startswith("#") else f"#{cleaned}"


def _build_branding_header(branding: WhiteLabelBranding) -> str:
    company_name = branding.company_name.strip() or "White-Label Report"
    logo_html = ""
    if branding.logo_url:
        logo_html = (
            f'<img src="{branding.logo_url}" alt="{company_name} logo" class="report-logo" />'
        )

    return (
        '<header class="report-header">'
        f"{logo_html}"
        '<div class="report-title-wrap">'
        f'<h1 class="report-title">{company_name}</h1>'
        "</div>"
        "</header>"
    )


def _build_styles(branding: WhiteLabelBranding) -> str:
    primary_color = _normalize_hex_color(branding.primary_color, "#00040e")
    secondary_color = _normalize_hex_color(branding.secondary_color, "#E2E8F0")
    text_color = _normalize_hex_color(branding.text_color, "#00040e")

    return f"""
    @page {{
        size: A4;
        margin: 14mm;
    }}

    body {{
        color: {text_color};
        font-family: Inter, Arial, sans-serif;
        font-size: 12px;
        line-height: 1.45;
        margin: 0;
    }}

    .report-header {{
        align-items: center;
        background: linear-gradient(90deg, {primary_color}, {secondary_color});
        border-radius: 10px;
        color: white;
        display: flex;
        gap: 14px;
        margin-bottom: 18px;
        min-height: 54px;
        padding: 10px 14px;
    }}

    .report-logo {{
        background: white;
        border-radius: 6px;
        height: 38px;
        object-fit: contain;
        padding: 4px;
        width: auto;
        max-width: 140px;
    }}

    .report-title {{
        color: white;
        font-size: 18px;
        font-weight: 700;
        margin: 0;
    }}

    h1, h2, h3 {{
        color: {primary_color};
        page-break-after: avoid;
    }}

    table {{
        border-collapse: collapse;
        width: 100%;
    }}

    th, td {{
        border: 1px solid {secondary_color};
        padding: 8px;
        text-align: left;
    }}
    """


def _build_document_html(html: str, branding: WhiteLabelBranding | None) -> str:
    header = _build_branding_header(branding) if branding else ""
    return f"""
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
      </head>
      <body>
        {header}
        <main>{html}</main>
      </body>
    </html>
    """


def _normalize_pdf_bytes(pdf_bytes: bytes) -> bytes:
    normalized = _PDF_CREATION_DATE_RE.sub(b"/CreationDate (D:20240101000000Z)", pdf_bytes)
    normalized = _PDF_MOD_DATE_RE.sub(b"/ModDate (D:20240101000000Z)", normalized)
    normalized = _PDF_ID_RE.sub(
        b"/ID [<00000000000000000000000000000000> <00000000000000000000000000000000>]", normalized
    )
    return normalized


def _load_weasyprint() -> tuple[type | None, type | None]:
    global CSS, HTML

    if CSS is not None and HTML is not None:
        return CSS, HTML

    try:
        from weasyprint import CSS as WeasyCSS, HTML as WeasyHTML
    except Exception:  # pragma: no cover - handled at runtime for environments without weasyprint
        return None, None

    CSS = WeasyCSS
    HTML = WeasyHTML
    return CSS, HTML


def render_html_to_pdf(
    html: str,
    *,
    branding: WhiteLabelBranding | None = None,
    base_url: str | None = None,
    deterministic: bool = True,
) -> bytes:
    css_class, html_class = _load_weasyprint()

    if html_class is None or css_class is None:
        raise RuntimeError("WeasyPrint is required for HTML to PDF rendering.")

    effective_branding = branding or WhiteLabelBranding()
    document_html = _build_document_html(html, effective_branding)
    stylesheet = css_class(string=_build_styles(effective_branding))
    pdf_bytes = html_class(string=document_html, base_url=base_url).write_pdf(
        stylesheets=[stylesheet]
    )

    if deterministic:
        return _normalize_pdf_bytes(pdf_bytes)
    return pdf_bytes
