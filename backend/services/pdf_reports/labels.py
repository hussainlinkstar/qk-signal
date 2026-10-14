from __future__ import annotations

import re

from services.report_i18n_service import get_report_label, is_rtl_report_language


_LABEL_SLUG_RE = re.compile(r"[^a-z0-9]+")

# First-strong isolate / pop-directional-isolate. WeasyPrint does not support
# `unicode-bidi: plaintext` or `dir="auto"`, so embedded labels carry their own
# direction: an English sentence inside an RTL page keeps its trailing
# punctuation at the end, and an Arabic label inside an LTR run stays intact.
_FSI = "⁨"
_PDI = "⁩"

# python-bidi is LGPL-2.1+ (dynamic import, unmodified) and arabic-reshaper
# is MIT. They are required because reportlab draws strictly left to right
# with no bidi reordering or Arabic joining, and WeasyPrint-pinned LTR SVG
# text has the same limitation, so RTL strings must arrive pre-shaped in
# visual order. Longer term the header/footer chrome should move to
# WeasyPrint (native bidi support), which would remove this dependency and
# the manual shaping entirely. Licence flagged for sign-off; see the
# SIGV2-1016 review notes.
try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    _RTL_SHAPING_AVAILABLE = True
except Exception:
    arabic_reshaper = None
    get_display = None
    _RTL_SHAPING_AVAILABLE = False


def shape_rtl_text(language: str | None, text: str | None) -> str | None:
    """Return `text` reshaped into visual order for LTR-only consumers.

    Only applies to RTL report languages; every other input is returned
    unchanged so non-RTL output stays byte-identical. Isolate controls are
    stripped first since the reshaper must see raw logical text.
    """
    if not text or not is_rtl_report_language(language):
        return text
    if not _RTL_SHAPING_AVAILABLE:
        return text
    stripped = text.replace(_FSI, "").replace(_PDI, "")
    try:
        return get_display(arabic_reshaper.reshape(stripped))
    except Exception:
        return stripped


def report_label(language: str, text: str | None) -> str | None:
    """Resolve a hardcoded English chrome label through the report catalog.

    The catalog key is derived from the literal itself (`pdf.s.<slug>`), so a
    missing translation always falls back to the unchanged English text and
    never to a raw key. The resolved string is wrapped in Unicode isolate
    controls so it renders correctly inside paragraphs of either direction.
    """
    if not text:
        return text
    if text.startswith(_FSI):
        return text
    slug = _LABEL_SLUG_RE.sub("_", text.lower()).strip("_")
    if not slug:
        return text
    resolved = get_report_label(language, f"pdf.s.{slug}", default=text)
    if not resolved:
        return resolved
    if not is_rtl_report_language(language):
        return resolved
    return f"{_FSI}{resolved}{_PDI}"
