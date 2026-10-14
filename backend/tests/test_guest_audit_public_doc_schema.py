"""SIGV2-1062 — guard: the public guest-audit API doc must match the code.

The doc (``docs/public-guest-audit-api.md``) documented
``guest-audit-public/1`` while the code emitted ``/2``, and never mentioned
``aio_insights`` at all. This test fails when the emitted schema version and
the documented one drift apart again.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.guest_audit_public import (
    MAX_PUBLIC_AIO_INSIGHTS,
    PUBLIC_RESULT_SCHEMA_VERSION,
)

DOC_PATH = Path(__file__).resolve().parents[2] / "docs" / "public-guest-audit-api.md"


def _doc() -> str:
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_documents_current_schema_version() -> None:
    doc = _doc()
    assert PUBLIC_RESULT_SCHEMA_VERSION in doc, (
        f"{DOC_PATH.name} does not mention the emitted schema version "
        f"{PUBLIC_RESULT_SCHEMA_VERSION!r}. Either update the document to the "
        f"new contract, or, if the bump was unintentional, revert "
        f"PUBLIC_RESULT_SCHEMA_VERSION in services/guest_audit_public.py."
    )


def test_doc_contains_no_stale_schema_version() -> None:
    doc = _doc()
    stale = {
        match
        for match in re.findall(r"guest-audit-public/\d+", doc)
        if match != PUBLIC_RESULT_SCHEMA_VERSION
    }
    assert not stale, (
        f"{DOC_PATH.name} still references stale schema version(s) {sorted(stale)} "
        f"while the code emits {PUBLIC_RESULT_SCHEMA_VERSION!r}. Update the "
        f"document's example response and version prose."
    )


def test_doc_documents_aio_insights_and_its_cap() -> None:
    doc = _doc()
    assert "aio_insights" in doc, (
        f"{DOC_PATH.name} does not document the aio_insights field emitted in "
        "the public result. Add it to the example response and describe its "
        "shape (title/description strings, AEO then GEO then improvements, "
        "deduplicated, capped)."
    )
    assert str(MAX_PUBLIC_AIO_INSIGHTS) in doc, (
        f"{DOC_PATH.name} does not state the aio_insights cap "
        f"({MAX_PUBLIC_AIO_INSIGHTS} entries). A consumer sizing a UI needs it."
    )
