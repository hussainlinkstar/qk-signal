"""Full-bleed page chrome (header + footer) drawn via reportlab.

WeasyPrint CSS @page margin boxes are limited to the content area between
page margins.  This module draws the header accent strip, dark header bar,
logo, metadata text, and footer directly on the reportlab canvas so they
span the full A4 page width (210 mm / 595.28 pt).

Usage
-----
    overlay_bytes = build_chrome_overlay(branding_ctx, target_ctx, labels_ctx)
    # overlay_bytes is a single-page A4 PDF with transparent background

The caller (renderer.py) merges this overlay onto every content page
(skipping the cover page) using pypdf.
"""

from __future__ import annotations

import base64
import glob
import io
import logging
from typing import Any

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from services.pdf_reports.labels import _RTL_SHAPING_AVAILABLE, shape_rtl_text
from services.report_i18n_service import get_report_label


logger = logging.getLogger(__name__)


# ── A4 dimensions in points ──────────────────────────────────────────
_W, _H = A4  # 595.28, 841.89

# ── Layout constants (points) ────────────────────────────────────────
_ACCENT_STRIP_H = 3  # brand accent strip at the very top
_HEADER_BAR_H = 37  # dark bar below accent strip
_HEADER_TOTAL_H = _ACCENT_STRIP_H + _HEADER_BAR_H  # 40 pt

_SIDE_MARGIN = 40  # horizontal inset for text/logo (~14 mm)
_LOGO_MAX_W = 110  # max logo width
_LOGO_MAX_H = 20  # max logo height

_FOOTER_LINE_Y = 28  # y position of the footer separator line
_FOOTER_TEXT_Y = 14  # y baseline for footer text

# ── Defaults ─────────────────────────────────────────────────────────
_DEFAULT_PRIMARY = "#6366F1"
_DEFAULT_HEADER_BG = "#050A11"
_DEFAULT_HEADER_TEXT = "#94A3B8"
_DEFAULT_FOOTER_TEXT_COLOR = "#64748B"
_DEFAULT_BORDER_COLOR = "#E2E8F0"

# ── RTL chrome font: reportlab needs an explicit TTF/TTC with Arabic
#    coverage; it has no fontconfig fallback like WeasyPrint. The container
#    ships Noto Naskh Arabic via fonts-noto-core; other entries are
#    dev-machine fallbacks. Ordered by preference. ────────────────────────
_ARABIC_FONT_NAME = "ChromeArabic"
_ARABIC_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoKufiArabic-Regular.ttf",
    "/usr/share/fonts/opentype/noto/NotoNaskhArabic-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Noto Naskh Arabic.ttc",
    "/System/Library/Fonts/Supplemental/NotoNaskhArabic.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/DecoTypeNaskh.ttc",
    "/System/Library/Fonts/GeezaPro.ttc",
    "/System/Library/Fonts/Supplemental/Baghdad.ttc",
]
_ARABIC_FONT_GLOBS = [
    "/usr/share/fonts/**/Noto*Arabic*.ttf",
    "/usr/share/fonts/**/*Arabic*.ttf",
]
# U+0627 ARABIC LETTER ALEF must resolve to a glyph or the chrome renders tofu.
_ARABIC_PROBE_CODEPOINT = 0x627
_TTC_SUBFONT_INDICES = range(8)
_arabic_font_ready: bool | None = None


def _font_covers_arabic(font_name: str) -> bool:
    try:
        face = pdfmetrics.getFont(font_name).face
        char_to_glyph = getattr(face, "charToGlyph", None) or {}
        return bool(char_to_glyph.get(_ARABIC_PROBE_CODEPOINT))
    except Exception:
        return False


def _ensure_arabic_font() -> bool:
    """Register an Arabic-capable TTF/TTC under _ARABIC_FONT_NAME.

    Returns True only when a registered font actually maps Arabic
    codepoints; without it the chrome falls back to Latin text.
    """
    global _arabic_font_ready
    if _arabic_font_ready is not None:
        return _arabic_font_ready

    candidates = list(_ARABIC_FONT_CANDIDATES)
    for pattern in _ARABIC_FONT_GLOBS:
        candidates.extend(sorted(glob.glob(pattern, recursive=True)))

    probe_index = 0
    for path in candidates:
        is_collection = path.lower().endswith((".ttc", ".otc"))
        indices = _TTC_SUBFONT_INDICES if is_collection else (0,)
        for subfont_index in indices:
            probe_name = f"{_ARABIC_FONT_NAME}Probe{probe_index}"
            probe_index += 1
            try:
                pdfmetrics.registerFont(TTFont(probe_name, path, subfontIndex=subfont_index))
            except Exception:
                break
            if not _font_covers_arabic(probe_name):
                continue
            pdfmetrics.registerFont(TTFont(_ARABIC_FONT_NAME, path, subfontIndex=subfont_index))
            _arabic_font_ready = True
            return True
    logger.warning("No Arabic-capable TTF found for PDF chrome; RTL chrome degrades to Latin text")
    _arabic_font_ready = False
    return False


def _shape_rtl(text: str) -> str:
    """Return text in visual order with shaped Arabic presentation forms.

    reportlab draws strictly left to right and does not apply the Unicode
    bidi algorithm or Arabic joining, so RTL strings must be reshaped and
    reordered before drawString/drawRightString.
    """
    return shape_rtl_text("ar", text)


def _hex(value: str | None, fallback: str) -> HexColor:
    candidate = str(value or "").strip()
    if not candidate:
        return HexColor(fallback)
    if not candidate.startswith("#"):
        candidate = f"#{candidate}"
    try:
        return HexColor(candidate)
    except Exception:
        return HexColor(fallback)


def _data_uri_to_image_reader(data_uri: str | None) -> ImageReader | None:
    """Convert a base64 data URI to a reportlab ImageReader."""
    if not data_uri or not isinstance(data_uri, str):
        return None
    try:
        header, encoded = data_uri.split(",", 1)
        raw = base64.b64decode(encoded)
        return ImageReader(io.BytesIO(raw))
    except Exception:
        return None


def _draw_header(
    c: Canvas,
    *,
    primary_color: str | None,
    header_bg: str | None,
    header_text_color: str | None,
    header_mode: str | None,
    logo_image: ImageReader | None,
    agency_name: str | None,
    meta_left: str,
    meta_right: str,
    is_rtl: bool = False,
    meta_font: str = "Helvetica",
) -> None:
    """Draw the full-width header: accent strip + dark bar + logo + meta."""
    accent_color = _hex(primary_color, _DEFAULT_PRIMARY)
    bg_color = _hex(header_bg, _DEFAULT_HEADER_BG)
    text_color = _hex(header_text_color, _DEFAULT_HEADER_TEXT)

    # Brand accent strip across the full page width
    c.setFillColor(accent_color)
    c.rect(0, _H - _ACCENT_STRIP_H, _W, _ACCENT_STRIP_H, fill=1, stroke=0)

    # Dark header bar below the accent strip
    c.setFillColor(bg_color)
    c.rect(0, _H - _HEADER_TOTAL_H, _W, _HEADER_BAR_H, fill=1, stroke=0)

    # Brand side: logo or text (mirrored to the right edge under RTL)
    logo_y = _H - _HEADER_TOTAL_H + (_HEADER_BAR_H - _LOGO_MAX_H) / 2
    if logo_image and header_mode in ("platform_logo", "agency_logo"):
        logo_x = _W - _SIDE_MARGIN - _LOGO_MAX_W if is_rtl else _SIDE_MARGIN
        c.drawImage(
            logo_image,
            logo_x,
            logo_y,
            width=_LOGO_MAX_W,
            height=_LOGO_MAX_H,
            preserveAspectRatio=True,
            # Anchor to the margin side so narrower logos sit flush instead of
            # floating centred inside the fixed box.
            anchor="se" if is_rtl else "sw",
            mask="auto",
        )
    else:
        label = str(agency_name or "").strip() or "Report"
        label_font = meta_font if is_rtl else "Helvetica-Bold"
        if is_rtl:
            label = _shape_rtl(label)
        c.setFillColor(HexColor("#F8FAFC"))
        c.setFont(label_font, 9)
        text_y = _H - _HEADER_TOTAL_H + (_HEADER_BAR_H - 9) / 2
        if is_rtl:
            c.drawRightString(_W - _SIDE_MARGIN, text_y, label)
        else:
            c.drawString(_SIDE_MARGIN, text_y, label.upper())

    # Metadata text (mirrored to the left edge under RTL)
    c.setFillColor(text_color)
    c.setFont(meta_font, 8)
    meta_y = _H - _HEADER_TOTAL_H + (_HEADER_BAR_H - 8) / 2

    if is_rtl:
        left_x = _SIDE_MARGIN
        if meta_left:
            shaped = _shape_rtl(meta_left)
            c.drawString(left_x, meta_y, shaped)
            left_x += c.stringWidth(shaped, meta_font, 8) + 12
        if meta_right:
            c.drawString(left_x, meta_y, _shape_rtl(meta_right))
        return

    # Draw right-aligned metadata items
    right_x = _W - _SIDE_MARGIN
    if meta_right:
        c.drawRightString(right_x, meta_y, meta_right)
        right_x -= c.stringWidth(meta_right, meta_font, 8) + 12
    if meta_left:
        c.drawRightString(right_x, meta_y, meta_left)


def _draw_footer(
    c: Canvas,
    *,
    footer_mode: str | None,
    footer_text: str | None,
    border_color: str | None,
    text_color: str | None,
    page_number: int | None = None,
    page_label: str = "Page",
    is_rtl: bool = False,
    footer_font: str = "Helvetica",
) -> None:
    """Draw the full-width footer: separator line + text + page number."""
    if footer_mode == "blank" and page_number is None:
        return

    line_color = _hex(border_color, _DEFAULT_BORDER_COLOR)
    font_color = _hex(text_color, _DEFAULT_FOOTER_TEXT_COLOR)

    # Thin separator line
    c.setStrokeColor(line_color)
    c.setLineWidth(0.5)
    c.line(_SIDE_MARGIN, _FOOTER_LINE_Y, _W - _SIDE_MARGIN, _FOOTER_LINE_Y)

    c.setFillColor(font_color)
    c.setFont(footer_font, 7.5)

    if is_rtl:
        # Right: footer text; left: page number
        if footer_mode != "blank" and footer_text:
            c.drawRightString(_W - _SIDE_MARGIN, _FOOTER_TEXT_Y, _shape_rtl(str(footer_text)))
        if page_number is not None:
            c.drawString(
                _SIDE_MARGIN,
                _FOOTER_TEXT_Y,
                _shape_rtl(f"{page_label} {page_number}"),
            )
        return

    # Left: footer text
    if footer_mode != "blank" and footer_text:
        c.drawString(_SIDE_MARGIN, _FOOTER_TEXT_Y, str(footer_text))

    # Right: page number
    if page_number is not None:
        c.drawRightString(
            _W - _SIDE_MARGIN,
            _FOOTER_TEXT_Y,
            f"{page_label} {page_number}",
        )


def build_chrome_overlay(
    branding: dict[str, Any],
    target: dict[str, Any],
    labels: dict[str, Any],
    *,
    page_number: int | None = None,
) -> bytes:
    """Return a single-page A4 PDF with the header and footer drawn.

    The PDF has a transparent background so it can be merged on top of
    the WeasyPrint-rendered content pages.
    """
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    branding = dict(branding)

    # Extract branding values
    colors = branding.get("colors", {})
    logo_data_uri = branding.get("header_logo_data_uri") or branding.get("logo_data_uri")
    logo_image = _data_uri_to_image_reader(logo_data_uri)

    generated_label = labels.get("generated_on", "Generated on")
    generated_date = branding.get("generated_date_long") or branding.get("generated_date", "")
    target_name = target.get("name", "")
    page_label = labels.get("page_label", "Page")

    is_rtl = bool(branding.get("is_rtl"))
    # reportlab cannot shape Arabic itself; when the reshaping pipeline or an
    # Arabic TTF is unavailable, degrade the chrome to its Latin fallback
    # rather than emitting missing-glyph boxes.
    chrome_font = "Helvetica"
    chrome_degraded = False
    if is_rtl:
        if _RTL_SHAPING_AVAILABLE and _ensure_arabic_font():
            chrome_font = _ARABIC_FONT_NAME
        else:
            is_rtl = False
            chrome_degraded = True

    if chrome_degraded:
        generated_label = get_report_label("en", "pdf.generated_on", default="Generated on")
        page_label = get_report_label("en", "pdf.page_label", default="Page")
        target_name = target_name if target_name.isascii() else ""
        if footer_text := branding.get("footer_text"):
            branding["footer_text"] = footer_text if footer_text.isascii() else None

    meta_left = f"{generated_label} {generated_date}".strip()
    meta_right = target_name

    _draw_header(
        c,
        primary_color=colors.get("primary") or colors.get("cover_accent"),
        header_bg=colors.get("header_bg"),
        header_text_color=colors.get("header_text"),
        header_mode=branding.get("header_mode"),
        logo_image=logo_image,
        agency_name=branding.get("agency_name"),
        meta_left=meta_left,
        meta_right=meta_right,
        is_rtl=is_rtl,
        meta_font=chrome_font,
    )

    _draw_footer(
        c,
        footer_mode=branding.get("footer_mode"),
        footer_text=branding.get("footer_text"),
        border_color=colors.get("border"),
        text_color=colors.get("muted"),
        page_number=page_number,
        page_label=page_label,
        is_rtl=is_rtl,
        footer_font=chrome_font,
    )

    c.showPage()
    c.save()
    return buf.getvalue()
