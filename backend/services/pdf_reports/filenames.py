from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


_INVALID_FILENAME_CHARS_RE = re.compile(r"[\\/:*?\"<>|\x00-\x1f]")
_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_component(value: Any, *, fallback: str) -> str:
    candidate = str(value or "").strip()
    if hasattr(value, "value"):
        candidate = str(getattr(value, "value") or "").strip()
    if not candidate:
        return fallback

    candidate = _INVALID_FILENAME_CHARS_RE.sub("-", candidate)
    candidate = _WHITESPACE_RE.sub(" ", candidate)
    candidate = candidate.strip(" ._-")
    return candidate or fallback


def _normalize_timestamp(value: datetime | None) -> str:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
    return timestamp.strftime("%Y%m%dT%H%M%SZ")


_REPORT_KIND_ACRONYMS = {"aio": "AIO", "seo": "SEO"}


def resolve_pdf_export_filename(
    *,
    project_name: Any,
    audit_type: Any,
    report_type: Any,
    report_kind: Any | None = None,
    timestamp: datetime | None = None,
) -> str:
    normalized_project = _normalize_component(project_name, fallback="Project")
    raw_kind = str(report_kind or "").strip().lower()
    normalized_report_kind = _normalize_component(
        _REPORT_KIND_ACRONYMS.get(raw_kind, raw_kind.replace("_", " ").title()),
        fallback="",
    ).strip()
    normalized_audit_type = _normalize_component(audit_type, fallback="Audit")
    normalized_report_type = _normalize_component(report_type, fallback="Report")
    normalized_timestamp = _normalize_timestamp(timestamp)
    if normalized_report_kind:
        return f"{normalized_project}_{normalized_report_kind}_{normalized_timestamp}.pdf"
    return f"{normalized_project}_{normalized_audit_type}_{normalized_report_type}_{normalized_timestamp}.pdf"
