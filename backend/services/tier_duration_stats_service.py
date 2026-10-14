"""Per-tier scan duration aggregates, derived from recorded runs (SIGV2-1177).

Why this module exists
----------------------
The product used to state a runtime per depth from a constant. SIGV2-1161
removed one set of invented figures (``~2 min`` / ``~8 min`` / ``~10 min``) and
replaced them with the approved design's (``~5`` / ``~15`` / ``~45``), which are
a real source but still not a measurement. Jake's decision was to state nothing
until the figures come from recorded data. This module is the measurement:
``audit_jobs`` already records ``tier``, ``started_at`` and ``completed_at`` for
every job, so a per-tier duration is derivable from runs that actually happened.

The statistic, and why
----------------------
Per tier this computes the **median (p50) and the interquartile range
(p25..p75)** of completed run durations, and publishes the IQR as a range in
whole minutes.

* **Median, not mean.** Scan duration is long-tailed: a provider latency spike,
  a retried stage or an unusually large site stretches the upper end, and a
  mean is dragged along with it until it describes no run anyone had. The
  median is the duration a customer actually meets most often, and one slow
  outlier cannot move it.
* **A range, not a single figure.** "about 8 minutes" and "5 to 12 minutes" are
  different promises. The spread between a fast run and a slow one is real, so
  the published figure states it instead of hiding it behind one number. The
  IQR is the middle half of runs, which is exactly what the customer-facing
  copy claims: *half of the last N scans at this depth finished in low..high
  minutes*.
* **Rounded outward.** ``low`` is ``floor(p25)`` and ``high`` is ``ceil(p75)``
  in minutes, so the published claim is a superset of the measured interval and
  stays true after rounding. Rounding inward could state a range narrower than
  the one that was measured.
* The median is stored alongside the quartiles for operators and for any future
  surface, but no customer-facing copy states it today, because no copy claims
  a single typical figure.

What is excluded, and why
-------------------------
* **Anything that is not ``succeeded``.** This is a whitelist, so failed,
  cancelled, queued and running jobs are all excluded by construction: a failed
  job's duration is the duration of a failure, not of a scan, and a job still
  running has no duration at all.
* **Sitemap crawl children.** ``audit_jobs.sitemap_crawl_job_id`` is a FK to
  ``sitemap_crawl_jobs``, so these are distinguishable in the table, and they
  are excluded. A sitemap crawl queues one audit job per crawled URL; those
  runs are machine-paced and contend with each other, so their durations
  describe a crawl's internals rather than the depth a customer picked on the
  start-scan screen. Including them would move a tier's figure with the size of
  whatever sitemaps happened to be crawled in the window.
* **Signal-initiated competitor refreshes** (``scan_origin ==
  "competitor_refresh"``), for the same reason: the customer did not launch
  them, so they are not the thing the Launch sentence is describing. ``NULL``
  ``scan_origin`` is kept: it means the write path declared nothing, not that
  the run was Signal's.
* **Non-positive durations.** Clock skew or a mis-set timestamp, not a run.

Thresholds
----------
``MIN_SAMPLE_SIZE`` runs per tier inside ``WINDOW_DAYS`` before anything is
published, and a published row expires after ``MAX_STAT_AGE_DAYS``. Below the
threshold the quartiles are not even stored, so no reader can publish a figure
derived from three runs by accident. The surface then states nothing: no
placeholder, no zero, no "about 0 minutes".
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median, quantiles

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

import models
from core.tier_labels import normalize_tier

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────────────────────

#: Completed runs required for a tier before any figure is published.
#:
#: 20 is chosen so the published quartiles rest on several observations each
#: rather than on a single run: at n=20 the p25 and p75 sit around the 5th/6th
#: and 15th/16th ordered values, so no one slow or fast run can set the range by
#: itself. It is also low enough that a tier reaches it within days of ordinary
#: traffic, so a real figure is not withheld for a quarter. Below it the product
#: says nothing, which is the whole point of this ticket.
MIN_SAMPLE_SIZE = 20

#: Rolling window the sample is drawn from. Long enough to clear the threshold
#: on a quiet tier, short enough that the figure describes the current pipeline
#: rather than a model, prompt or provider the product no longer runs.
WINDOW_DAYS = 90

#: A published row older than this is treated as unpublished. The sweep runs
#: hourly, so a week of silence means the sweep is broken, and a frozen figure
#: from an unknown pipeline state is exactly the kind of number this ticket
#: exists to stop serving.
MAX_STAT_AGE_DAYS = 7

#: Hard ceiling on rows pulled per tier, newest first. The window already bounds
#: this; the cap bounds memory if a tier ever runs at an unexpected volume.
MAX_SAMPLE_ROWS = 5000

#: The tiers a customer can choose on the start-scan screen. ``lite`` is absent
#: on purpose: it is not a selectable depth and no surface asks for its runtime.
AGGREGATED_TIERS: tuple[str, ...] = ("fast", "smart", "deep_judgment")

#: Jobs Signal launched for its own competitor benchmark refresh, never a scan
#: the customer asked for (SIGV2-1129).
_COMPETITOR_REFRESH_ORIGIN = "competitor_refresh"

#: The only status whose duration is the duration of a scan.
_SUCCEEDED_STATUS = "succeeded"

#: Identifies the statistic in the API payload, so a consumer cannot mistake the
#: pair of numbers for a mean, a min/max or a timeout.
STATISTIC_ID = "p25_p75_minutes"


@dataclass(frozen=True)
class PublishedTierDuration:
    """A per-tier figure that has cleared every publication gate."""

    tier: str
    low_minutes: int
    high_minutes: int
    median_minutes: int
    sample_size: int
    window_days: int
    computed_at: datetime


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _collect_durations(db: Session, tier: str, *, cutoff: datetime) -> list[float]:
    """Return the completed run durations in seconds for one tier.

    Rows are selected rather than aggregated in SQL on purpose: percentiles are
    dialect-specific (``percentile_cont`` does not exist on SQLite, which the
    test suite runs on), and the window plus ``MAX_SAMPLE_ROWS`` keeps the row
    count small enough that computing them in Python is cheaper than carrying a
    dialect fork.
    """
    statement = (
        select(models.AuditJob.started_at, models.AuditJob.completed_at)
        .where(
            models.AuditJob.tier == tier,
            models.AuditJob.status == _SUCCEEDED_STATUS,
            models.AuditJob.started_at.isnot(None),
            models.AuditJob.completed_at.isnot(None),
            models.AuditJob.completed_at >= cutoff,
            # Sitemap crawl children are distinguishable by this FK and are not
            # the depth a customer picked. See the module docstring.
            models.AuditJob.sitemap_crawl_job_id.is_(None),
            # NULL has to be allowed explicitly: `scan_origin != '...'` is NULL,
            # not true, for a row that declared no origin, so a plain inequality
            # would silently drop every unclassified job.
            or_(
                models.AuditJob.scan_origin.is_(None),
                models.AuditJob.scan_origin != _COMPETITOR_REFRESH_ORIGIN,
            ),
        )
        .order_by(models.AuditJob.completed_at.desc())
        .limit(MAX_SAMPLE_ROWS)
    )

    durations: list[float] = []
    for started_at, completed_at in db.execute(statement).all():
        started = _as_utc(started_at)
        completed = _as_utc(completed_at)
        if started is None or completed is None:
            continue
        seconds = (completed - started).total_seconds()
        if seconds <= 0:
            # Clock skew or a mis-set timestamp, not a run.
            continue
        durations.append(seconds)
    return durations


def _quartiles(durations: list[float]) -> tuple[float, float, float]:
    """Return ``(p25, p50, p75)`` in seconds.

    Only called with at least ``MIN_SAMPLE_SIZE`` samples, so
    ``statistics.quantiles`` is always given enough data points.
    """
    ordered = sorted(durations)
    p25, _p50, p75 = quantiles(ordered, n=4, method="inclusive")
    return float(p25), float(median(ordered)), float(p75)


def recompute_tier_duration_stats(
    db: Session, *, now: datetime | None = None
) -> dict[str, dict[str, object]]:
    """Recompute and upsert one row per selectable tier.

    Returns a per-tier summary for the sweep log. Does not commit: the caller
    owns the transaction, matching every other task in ``cron_sweeper``.

    A tier below ``MIN_SAMPLE_SIZE`` still gets a row, recording the real
    sample size with **NULL quartiles**. Storing the sample size without the
    figures is deliberate: an operator can see how far a tier is from
    publishable, and no reader can accidentally serve quartiles that were never
    allowed to be published.
    """
    reference = _as_utc(now) or datetime.now(timezone.utc)
    cutoff = reference - timedelta(days=WINDOW_DAYS)
    summary: dict[str, dict[str, object]] = {}

    existing_rows = {
        row.tier: row
        for row in db.execute(
            select(models.AuditTierDurationStat).where(
                models.AuditTierDurationStat.tier.in_(AGGREGATED_TIERS)
            )
        )
        .scalars()
        .all()
    }

    for tier in AGGREGATED_TIERS:
        durations = _collect_durations(db, tier, cutoff=cutoff)
        sample_size = len(durations)
        publishable = sample_size >= MIN_SAMPLE_SIZE
        p25 = p50 = p75 = None
        if publishable:
            p25, p50, p75 = _quartiles(durations)

        row = existing_rows.get(tier)
        if row is None:
            row = models.AuditTierDurationStat(tier=tier)
            db.add(row)
        row.sample_size = sample_size
        row.window_days = WINDOW_DAYS
        row.min_sample_size = MIN_SAMPLE_SIZE
        row.p25_seconds = p25
        row.p50_seconds = p50
        row.p75_seconds = p75
        row.computed_at = reference

        summary[tier] = {
            "sample_size": sample_size,
            "published": publishable,
        }

    return summary


def _to_published(
    row: models.AuditTierDurationStat, *, now: datetime
) -> PublishedTierDuration | None:
    """Apply every publication gate to a stored row.

    The gates are re-applied at read time rather than trusted from the write:
    a row can go stale after it was written, and the threshold can be raised
    without a recompute having run yet.
    """
    tier = normalize_tier(row.tier)
    if tier not in AGGREGATED_TIERS:
        return None

    sample_size = int(row.sample_size or 0)
    threshold = int(row.min_sample_size or MIN_SAMPLE_SIZE)
    if sample_size < max(threshold, MIN_SAMPLE_SIZE):
        return None

    if row.p25_seconds is None or row.p75_seconds is None or row.p50_seconds is None:
        return None

    computed_at = _as_utc(row.computed_at)
    if computed_at is None or computed_at < now - timedelta(days=MAX_STAT_AGE_DAYS):
        return None

    low = max(1, math.floor(float(row.p25_seconds) / 60.0))
    high = max(low, math.ceil(float(row.p75_seconds) / 60.0))
    return PublishedTierDuration(
        tier=tier,
        low_minutes=low,
        high_minutes=high,
        # Half-up rather than ``round``, whose banker's rounding would send a
        # 10.5-minute median to 10. Nothing customer-facing states this figure,
        # but an operator reading it should not have to know that rule.
        median_minutes=max(1, math.floor(float(row.p50_seconds) / 60.0 + 0.5)),
        sample_size=sample_size,
        window_days=int(row.window_days or WINDOW_DAYS),
        computed_at=computed_at,
    )


def get_published_tier_durations(
    db: Session, *, now: datetime | None = None
) -> dict[str, PublishedTierDuration]:
    """Return the publishable per-tier figures, keyed by canonical tier id.

    A tier with no measurement, too small a sample or a stale row is **absent**
    from the mapping. There is no placeholder entry and no zero: a caller that
    finds nothing must state nothing.
    """
    reference = _as_utc(now) or datetime.now(timezone.utc)
    rows = (
        db.execute(
            select(models.AuditTierDurationStat).where(
                models.AuditTierDurationStat.tier.in_(AGGREGATED_TIERS)
            )
        )
        .scalars()
        .all()
    )

    published: dict[str, PublishedTierDuration] = {}
    for row in rows:
        resolved = _to_published(row, now=reference)
        if resolved is not None:
            published[resolved.tier] = resolved
    return published


def format_duration_phrase(figure: PublishedTierDuration) -> str:
    """Render one figure as the exact claim the numbers support.

    The wording is load-bearing. These two numbers are quartiles, so the only
    true statement is about the middle half of the sample, and the sample size
    is named so the claim carries its own evidence. Never reword this into
    "takes about N minutes": that is a different, unsupported claim.
    """
    if figure.low_minutes == figure.high_minutes:
        # Only reachable when the measured quartiles round to the same whole
        # minute. "within" stays true where a degenerate "N to N" range would
        # read like a promise of exactness.
        return (
            f"half of the last {figure.sample_size} scans finished within "
            f"{figure.high_minutes} minutes"
        )
    return (
        f"half of the last {figure.sample_size} scans finished in "
        f"{figure.low_minutes} to {figure.high_minutes} minutes"
    )


def describe_published_tier_durations(
    published: dict[str, PublishedTierDuration],
    *,
    labels: dict[str, str],
    inline: bool = False,
) -> str | None:
    """Render the measured figures for the support surfaces.

    ``labels`` maps tier id to the name the surface already uses for it, so this
    does not quietly rename a depth the customer sees elsewhere. ``inline``
    switches between a bulleted block (the assistant's prompt) and a single
    sentence fragment (the canned fallback reply).

    A tier with no published figure contributes **nothing**; ``None`` comes back
    when nothing is publishable at all, and the caller must then omit durations
    from what it says rather than describing a scan as instant or quick.
    """
    entries = [
        (label, format_duration_phrase(published[tier]))
        for tier, label in labels.items()
        if tier in published
    ]
    if not entries:
        return None
    if inline:
        return "; ".join(f"{label}: {phrase}" for label, phrase in entries) + "."
    return "\n".join(f"- {label}: {phrase}." for label, phrase in entries)
