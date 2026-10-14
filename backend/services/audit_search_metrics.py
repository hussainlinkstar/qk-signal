"""Stored search-performance metrics, shaped for the audit (SIGV2-1265).

``project_gsc_page_metrics`` and ``project_bing_metrics`` are written by the
monitoring paths and, until this module existed, read by nobody: an audit saw
only which sources were bound, never what they measured.

Two rules hold everywhere below.

1. The two providers are separate datasets. Bing numbers are never added to,
   averaged with, or presented as Search Console numbers.
2. Absence is stated, never implied. A provider with no binding and a provider
   with a binding but no stored rows are different facts, and neither is
   reported as zero traffic.

Reads are local: this never calls a provider API, so it cannot slow down or
fail an audit because an upstream is down.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

import models

# Bing publishes a fixed recent window and Search Console is synced per report
# window; 28 days is the longest span both can realistically cover, and it is
# short enough that an audit quotes current behaviour rather than history.
SEARCH_METRICS_WINDOW_DAYS = 28

MAX_TOP_ROWS = 5

REASON_NO_BINDING = "no_active_binding"
REASON_NO_ROWS = "no_stored_rows"
REASON_NO_SITE_ROWS = "no_site_level_rows"

# Microsoft types AvgClickPosition / AvgImpressionPosition as int without
# documenting the scale, so no consumer may render a Bing position.
BING_POSITION_UNAVAILABLE_REASON = "bing_position_scale_unverified"


def _active_binding(
    db: Session,
    *,
    project_id: int,
    source_type: models.ProjectDataSourceType,
) -> models.ProjectDataSource | None:
    return (
        db.query(models.ProjectDataSource)
        .filter(
            models.ProjectDataSource.project_id == project_id,
            models.ProjectDataSource.source_type == source_type,
            models.ProjectDataSource.is_active.is_(True),
        )
        .first()
    )


def _period(days: list[date]) -> dict[str, str | None]:
    if not days:
        return {"start": None, "end": None}
    return {"start": min(days).isoformat(), "end": max(days).isoformat()}


def _unavailable(reason: str) -> dict[str, Any]:
    return {"available": False, "reason": reason}


def _search_console_metrics(db: Session, *, project_id: int, since: date) -> dict[str, Any]:
    binding = _active_binding(
        db,
        project_id=project_id,
        source_type=models.ProjectDataSourceType.GOOGLE_SEARCH_CONSOLE,
    )
    property_id = str(getattr(binding, "source_id", "") or "").strip() if binding else ""
    if not property_id:
        return _unavailable(REASON_NO_BINDING)

    rows = (
        db.query(models.ProjectGSCPageMetric)
        .filter(
            models.ProjectGSCPageMetric.project_id == project_id,
            models.ProjectGSCPageMetric.property == property_id,
            models.ProjectGSCPageMetric.date >= since,
        )
        .all()
    )
    if not rows:
        return _unavailable(REASON_NO_ROWS)

    by_page: dict[str, dict[str, float]] = defaultdict(lambda: {"clicks": 0.0, "impressions": 0.0})
    clicks = 0.0
    impressions = 0.0
    weighted_position = 0.0
    position_impressions = 0.0
    for row in rows:
        row_clicks = float(row.clicks or 0.0)
        row_impressions = float(row.impressions or 0.0)
        clicks += row_clicks
        impressions += row_impressions
        by_page[row.page]["clicks"] += row_clicks
        by_page[row.page]["impressions"] += row_impressions
        if row.position is not None and row_impressions > 0:
            weighted_position += float(row.position) * row_impressions
            position_impressions += row_impressions

    top_pages = sorted(
        (
            {"page": page, "clicks": totals["clicks"], "impressions": totals["impressions"]}
            for page, totals in by_page.items()
        ),
        key=lambda item: (item["clicks"], item["impressions"]),
        reverse=True,
    )[:MAX_TOP_ROWS]

    position: dict[str, Any] = (
        {"status": "available", "value": round(weighted_position / position_impressions, 2)}
        if position_impressions > 0
        else {"status": "unavailable", "reason": "no_position_rows"}
    )

    return {
        "available": True,
        "property": property_id,
        "period": _period([row.date for row in rows]),
        "clicks": clicks,
        "impressions": impressions,
        "pages": len(by_page),
        "top_pages": top_pages,
        "position": position,
    }


def _bing_metrics(db: Session, *, project_id: int, since: date) -> dict[str, Any]:
    binding = _active_binding(
        db,
        project_id=project_id,
        source_type=models.ProjectDataSourceType.BING_WEBMASTER,
    )
    site_url = str(getattr(binding, "source_id", "") or "").strip() if binding else ""
    if not site_url:
        return _unavailable(REASON_NO_BINDING)

    rows = (
        db.query(models.ProjectBingMetric)
        .filter(
            models.ProjectBingMetric.project_id == project_id,
            models.ProjectBingMetric.site_url == site_url,
            models.ProjectBingMetric.date >= since,
        )
        .all()
    )
    if not rows:
        return _unavailable(REASON_NO_ROWS)

    site_rows = [row for row in rows if row.dimension_type == "site"]
    query_rows = [row for row in rows if row.dimension_type == "query"]
    page_rows = [row for row in rows if row.dimension_type == "page"]

    by_query: dict[str, dict[str, float]] = defaultdict(lambda: {"clicks": 0.0, "impressions": 0.0})
    for row in query_rows:
        by_query[row.dimension]["clicks"] += float(row.clicks or 0.0)
        by_query[row.dimension]["impressions"] += float(row.impressions or 0.0)

    top_queries = sorted(
        (
            {"query": query, "clicks": totals["clicks"], "impressions": totals["impressions"]}
            for query, totals in by_query.items()
        ),
        key=lambda item: (item["clicks"], item["impressions"]),
        reverse=True,
    )[:MAX_TOP_ROWS]

    payload: dict[str, Any] = {
        "available": True,
        "site_url": site_url,
        "period": _period([row.date for row in rows]),
        "queries": len(by_query),
        "pages": len({row.dimension for row in page_rows}),
        "top_queries": top_queries,
        "position": {
            "status": "unavailable",
            "reason": BING_POSITION_UNAVAILABLE_REASON,
        },
    }

    # Query and page rows repeat the same traffic broken down differently, so
    # site-level rows are the only honest total. Without them the totals are
    # stated as missing rather than summed from a breakdown.
    if site_rows:
        payload["clicks"] = sum(float(row.clicks or 0.0) for row in site_rows)
        payload["impressions"] = sum(float(row.impressions or 0.0) for row in site_rows)
    else:
        payload["clicks"] = None
        payload["impressions"] = None
        payload["traffic_reason"] = REASON_NO_SITE_ROWS

    return payload


def load_project_search_metrics(db: Session, *, project_id: int) -> dict[str, Any]:
    """Search Console and Bing aggregates for the project's recent window."""
    since = date.today() - timedelta(days=SEARCH_METRICS_WINDOW_DAYS)
    return {
        "window_days": SEARCH_METRICS_WINDOW_DAYS,
        "google_search_console": _search_console_metrics(db, project_id=project_id, since=since),
        "bing_webmaster": _bing_metrics(db, project_id=project_id, since=since),
    }
