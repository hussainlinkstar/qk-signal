"""Report library decisions: the frozen name, the period, and the real expiry.

Pure logic, no router and no session work, so the enqueue paths, the queued
PDF worker and the list endpoint all reach the same answer.

Three rules this module exists to enforce:

1. A report's name is derived from its kind plus its period and then frozen at
   generation. Resolving it on read would rewrite the name of every historical
   report the day the format changes, and a name the customer has already
   quoted must not move under them.
2. A report with no requested period is named from its generation date and
   reads as "all time". The minimum and maximum of the selected audits are not
   a period the customer asked for, so they are never used to invent one.
3. Link expiry is computed from the retention policy that already governs the
   stored artifact, so the library shows an expired link as expired instead of
   leaving the customer to find out by clicking it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

# The kinds the product exposes today. `aio` and `seo` are real kinds in the
# renderer but are not offered as library actions yet, so they are labelled
# here and nowhere else.
REPORT_KIND_LABELS: Mapping[str, str] = {
    "standard": "Standard",
    "executive": "Executive",
    "project": "Project",
    "competitors": "Competitors",
    "financial": "Financial",
    "aio": "AI visibility",
    "seo": "Search",
}

_FALLBACK_KIND_LABEL = "Report"
_ALL_TIME_NAME_SUFFIX = "all time"


def resolve_report_kind_from_manifest(export_manifest: Mapping[str, Any] | None) -> str | None:
    """Read the stored kind without re-deriving it.

    The manifest resolved at enqueue is the authorization record (SIGV2-1019);
    the library reads it rather than keeping a second copy that could diverge
    from the one the entitlement checks evaluate.
    """
    if not isinstance(export_manifest, Mapping):
        return None
    raw_kind = str(export_manifest.get("report_kind") or "").strip().lower()
    return raw_kind or None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_day(value: datetime) -> str:
    return f"{value.day} {value.strftime('%b')} {value.year}"


def _format_period_for_name(
    period_start: datetime | None,
    period_end: datetime | None,
) -> str | None:
    start = _as_utc(period_start)
    end = _as_utc(period_end)
    if start is None and end is None:
        return None
    if start is not None and end is not None:
        if start.date() == end.date():
            return _format_day(start)
        return f"{_format_day(start)} to {_format_day(end)}"
    if start is not None:
        return f"from {_format_day(start)}"
    assert end is not None
    return f"until {_format_day(end)}"


def resolve_report_name(
    *,
    report_kind: str | None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
    generated_at: datetime | None = None,
) -> str:
    """Build the name written to the report record at generation time."""
    kind_label = REPORT_KIND_LABELS.get(
        str(report_kind or "").strip().lower(), _FALLBACK_KIND_LABEL
    )
    period_label = _format_period_for_name(period_start, period_end)
    if period_label is None:
        reference = _as_utc(generated_at) or datetime.now(timezone.utc)
        return f"{kind_label} report - {_ALL_TIME_NAME_SUFFIX}, {_format_day(reference)}"
    return f"{kind_label} report - {period_label}"


def resolve_stored_report_name(job: Any) -> str:
    """The stored name, or a read-time fallback for rows predating the column.

    Rows written before the `name` column existed have nothing frozen to
    serve. They get a name derived here, which is the one case where the
    format applies at read time; new rows always carry their own.
    """
    stored = str(getattr(job, "name", None) or "").strip()
    if stored:
        return stored
    return resolve_report_name(
        report_kind=resolve_report_kind_from_manifest(getattr(job, "export_manifest", None)),
        period_start=getattr(job, "period_start", None),
        period_end=getattr(job, "period_end", None),
        generated_at=getattr(job, "created_at", None),
    )


@dataclass(frozen=True)
class ReportLinkExpiry:
    """What the Link expiry column shows, resolved server-side."""

    expires_at: datetime | None
    expired: bool
    days_remaining: int | None


def resolve_report_link_expiry(
    job: Any,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> ReportLinkExpiry:
    """Resolve the download link's real expiry for one report row.

    Only a succeeded artifact has a link to expire: a queued, running or
    failed job has no file, and the column renders a dash for it. An already
    expired job needs no arithmetic, its artifact is gone.

    `retention_days` is passed in per report rather than read from the caller's
    plan, so a later per-plan retention policy cannot silently relabel the
    expiry of a report generated under a different one.
    """
    status = str(getattr(job, "status", "") or "").strip().lower()
    if status == "expired":
        return ReportLinkExpiry(expires_at=None, expired=True, days_remaining=0)
    if status != "succeeded":
        return ReportLinkExpiry(expires_at=None, expired=False, days_remaining=None)

    reference = (
        _as_utc(getattr(job, "completed_at", None))
        or _as_utc(getattr(job, "updated_at", None))
        or _as_utc(getattr(job, "created_at", None))
    )
    if reference is None or retention_days <= 0:
        return ReportLinkExpiry(expires_at=None, expired=False, days_remaining=None)

    expires_at = reference + timedelta(days=retention_days)
    current_time = _as_utc(now) or datetime.now(timezone.utc)
    remaining = expires_at - current_time
    if remaining.total_seconds() <= 0:
        return ReportLinkExpiry(expires_at=expires_at, expired=True, days_remaining=0)
    return ReportLinkExpiry(
        expires_at=expires_at,
        expired=False,
        days_remaining=int(remaining.total_seconds() // 86400),
    )
