"""Search Console performance reporting service (SIGV2-1025).

Implements the query layer behind ``docs/search-console-reporting-contract.md``.
Every aggregation rule in that file is binding; comments cite the section each
non-obvious rule comes from.

Reads run under the customer's own OAuth bearer (resolved and refreshed through
the shared Google primitive), never a service account. No token or secret
appears in responses, logs or error details.
"""

from __future__ import annotations

import logging
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import quote, unquote, urlsplit
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

import models

logger = logging.getLogger(__name__)

GSC_API_BASE = "https://www.googleapis.com/webmasters/v3"
GSC_DATE_BASIS = "America/Los_Angeles"

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {500, 502, 503}

# Contract section 4: explicit rowLimit, page by startRow, hard ceiling of
# 50,000 rows per day per search type. Anything stopped by a bound is partial.
ROW_LIMIT = 25_000
ROW_CEILING = 50_000

# Contract section 7: position bands used for the low_ctr median comparison.
POSITION_BANDS: tuple[tuple[str, float, float], ...] = (
    ("top3", 0.0, 3.0),
    ("4_10", 3.0, 10.0),
    ("11_20", 10.0, 20.0),
    ("beyond_20", 20.0, float("inf")),
)


class GSCReportError(Exception):
    """Raised when a Search Console call fails in a non-auth way."""


class GSCRateLimitError(Exception):
    """Raised when Search Console returns 429 after retries are exhausted."""


class GSCPermissionError(Exception):
    """Raised when Search Console returns 401/403: revoked or denied."""


# ---------------------------------------------------------------------------
# Metric aggregation (contract section 2)
# ---------------------------------------------------------------------------


def recompute_ctr(clicks: float, impressions: float) -> Optional[float]:
    """SUM(clicks) / SUM(impressions); null on zero impressions, never 0."""
    if not impressions:
        return None
    return clicks / impressions


def weighted_position(rows: list[dict[str, Any]]) -> Optional[float]:
    """Impression-weighted mean of per-row average position.

    The API returns a per-row *average* position; a plain mean of those is
    wrong whenever impressions differ, which is always. Zero total impressions
    yields null, never 0.
    """
    total_impressions = sum(float(r.get("impressions") or 0.0) for r in rows)
    if not total_impressions:
        return None
    weighted = sum(
        float(r.get("position") or 0.0) * float(r.get("impressions") or 0.0) for r in rows
    )
    return weighted / total_impressions


def position_band(weighted_pos: Optional[float]) -> Optional[str]:
    if weighted_pos is None:
        return None
    for name, lo, hi in POSITION_BANDS:
        if lo < weighted_pos <= hi or (name == "top3" and 0 < weighted_pos <= hi):
            return name
    return None


# ---------------------------------------------------------------------------
# URL normalization for the GA4 join (contract section 6.1)
# ---------------------------------------------------------------------------


def normalize_page_key(url_or_path: str) -> str:
    """Normalize a GSC full URL or a GA4 path to a host-free comparison key.

    Strip scheme+host, strip query+fragment, percent-decode, lowercase the
    path, preserve a trailing slash except the root which is ``/``.
    """
    raw = (url_or_path or "").strip()
    if not raw:
        return "/"
    if raw.startswith("sc-domain:"):
        # A domain property identifier carries no page path.
        return "/"
    if "://" in raw:
        raw = urlsplit(raw).path
    path = raw.split("?", 1)[0].split("#", 1)[0]
    path = unquote(path).lower()
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and path.endswith("/"):
        pass  # trailing slash preserved
    return path or "/"


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GSCReportingService:
    """Queries the Search Console API with a customer OAuth bearer."""

    def __init__(self, access_token: str) -> None:
        if not access_token:
            raise GSCPermissionError("gsc_missing_access_token")
        self._access_token = access_token

    def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.post(url, json=body, headers=headers)
            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise GSCReportError(f"gsc_request_failed:{type(exc).__name__}") from exc

            if response.status_code == 200:
                payload = response.json()
                return payload if isinstance(payload, dict) else {}

            if response.status_code == 429:
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
                    continue
                raise GSCRateLimitError("gsc_rate_limited")

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_DELAY_SECONDS * (2**attempt))
                continue

            if response.status_code in (401, 403):
                raise GSCPermissionError(f"gsc_access_denied_{response.status_code}")

            raise GSCReportError(f"gsc_http_{response.status_code}")

        raise GSCReportError("gsc_retries_exhausted")

    def query_search_analytics(
        self,
        site_url: str,
        *,
        start_date: date,
        end_date: date,
        dimensions: list[str],
        data_state: str = "all",
        aggregation_type: str = "auto",
        row_limit: int = ROW_LIMIT,
        row_ceiling: int = ROW_CEILING,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Paginated searchAnalytics/query; returns (rows, metadata).

        Metadata carries: ``first_incomplete_date``, ``response_aggregation_type``,
        ``completeness`` (``full`` | ``partial``) and ``partial_reason``.
        Rows on/after ``first_incomplete_date`` get ``_incomplete: True``.
        """
        encoded = quote(site_url, safe="")
        url = f"{GSC_API_BASE}/sites/{encoded}/searchAnalytics/query"

        rows: list[dict[str, Any]] = []
        meta: dict[str, Any] = {
            "first_incomplete_date": None,
            "response_aggregation_type": None,
            "completeness": "full",
            "partial_reason": None,
        }
        start_row = 0
        while True:
            body = {
                "startDate": start_date.isoformat(),
                "endDate": end_date.isoformat(),
                "dimensions": dimensions,
                "dataState": data_state,
                "aggregationType": aggregation_type,
                "rowLimit": row_limit,
                "startRow": start_row,
            }
            payload = self._post(url, body)

            api_meta = payload.get("metadata") or {}
            if api_meta.get("first_incomplete_date") and not meta["first_incomplete_date"]:
                meta["first_incomplete_date"] = api_meta["first_incomplete_date"]
            if payload.get("responseAggregationType"):
                meta["response_aggregation_type"] = payload["responseAggregationType"]

            page_rows = payload.get("rows", []) or []
            for row in page_rows:
                keys = row.get("keys", []) or []
                parsed: dict[str, Any] = dict(zip(dimensions, keys))
                parsed["clicks"] = float(row.get("clicks") or 0.0)
                parsed["impressions"] = float(row.get("impressions") or 0.0)
                parsed["ctr"] = float(row.get("ctr") or 0.0)
                parsed["position"] = float(row.get("position") or 0.0)
                rows.append(parsed)

            if len(page_rows) < row_limit:
                break
            start_row += len(page_rows)
            if start_row >= row_ceiling:
                # Contract 4: 50,000 rows/day/search-type hard ceiling. Any
                # result stopped by it is partial, never a presented total.
                meta["completeness"] = "partial"
                meta["partial_reason"] = "row_ceiling_reached"
                del rows[row_ceiling:]
                break

        if meta["first_incomplete_date"]:
            cutoff = date.fromisoformat(str(meta["first_incomplete_date"]))
            for row in rows:
                row_date = row.get("date")
                if isinstance(row_date, str) and row_date and row_date >= cutoff.isoformat():
                    row["_incomplete"] = True

        return rows, meta


# ---------------------------------------------------------------------------
# Period computation (contract section 3): Search Console reports in PT.
# ---------------------------------------------------------------------------

GSC_WINDOWS: dict[str, int] = {"7D": 7, "15D": 15, "90D": 90, "12M": 365}


def compute_gsc_period(window_key: str) -> tuple[date, date]:
    """[start, end] in Pacific Time; end is yesterday PT since today accumulates."""
    if window_key not in GSC_WINDOWS:
        raise ValueError(f"unsupported_gsc_window:{window_key}")
    today_pt = datetime.now(ZoneInfo(GSC_DATE_BASIS)).date()
    end = today_pt - timedelta(days=1)
    start = end - timedelta(days=GSC_WINDOWS[window_key] - 1)
    return start, end


# ---------------------------------------------------------------------------
# Pages table (contract sections 6-7)
# ---------------------------------------------------------------------------


def aggregate_pages(
    rows: list[dict[str, Any]],
    ga4_sessions_by_key: Optional[dict[str, float]],
    *,
    min_impressions: int,
    sessions_unavailable_reason: str = "no_ga4_binding",
) -> list[dict[str, Any]]:
    """Aggregate per-normalized-page rows into the Pages table shape.

    ``ga4_sessions_by_key`` maps normalized GA4 pagePath keys to sessions, or
    None when no authorized GA4 binding exists - in which case every row's
    Sessions is unavailable with a reason, never filled with clicks.
    """
    pages: dict[str, dict[str, Any]] = {}
    for row in rows:
        page_url = str(row.get("page") or "")
        key = normalize_page_key(page_url)
        entry = pages.setdefault(
            key,
            {
                "pages": [],
                "clicks": 0.0,
                "impressions": 0.0,
                "_pos_weight": 0.0,
                "incomplete": False,
            },
        )
        entry["pages"].append(page_url)
        clicks = float(row.get("clicks") or 0.0)
        impressions = float(row.get("impressions") or 0.0)
        entry["clicks"] += clicks
        entry["impressions"] += impressions
        entry["_pos_weight"] += float(row.get("position") or 0.0) * impressions
        entry["incomplete"] = entry["incomplete"] or bool(row.get("_incomplete"))

    out: list[dict[str, Any]] = []
    for key, entry in pages.items():
        impressions = entry["impressions"]
        clicks = entry["clicks"]
        position = entry["_pos_weight"] / impressions if impressions else None
        ctr = recompute_ctr(clicks, impressions)
        if ga4_sessions_by_key is None:
            sessions: Optional[float] = None
            sessions_reason = sessions_unavailable_reason
        else:
            sessions = ga4_sessions_by_key.get(key)
            sessions_reason = None if sessions is not None else "no_ga4_match"
        out.append(
            {
                "page_key": key,
                "pages": sorted(set(entry["pages"])),
                "collapsed_count": len(set(entry["pages"])) - 1,
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "avg_position": position,
                "sessions": sessions,
                "sessions_reason": sessions_reason,
                "incomplete": entry["incomplete"],
            }
        )

    # Opportunity needs the band-median CTR across the property's own pages.
    band_ctrs: dict[str, list[float]] = {}
    for page in out:
        band = position_band(page["avg_position"])
        if band and page["ctr"] is not None and not page["incomplete"]:
            band_ctrs.setdefault(band, []).append(page["ctr"])
    band_medians = {band: statistics.median(values) for band, values in band_ctrs.items() if values}

    for page in out:
        page["opportunity"] = classify_opportunity(
            page,
            band_median_ctr=band_medians.get(position_band(page["avg_position"]) or ""),
            min_impressions=min_impressions,
        )
    out.sort(key=lambda p: (-(p["impressions"]), p["page_key"]))
    return out


def classify_opportunity(
    page: dict[str, Any],
    *,
    band_median_ctr: Optional[float],
    min_impressions: int,
) -> dict[str, Any]:
    """Four-value classification with its evidence attached (contract 7)."""
    position = page["avg_position"]
    impressions = page["impressions"]
    ctr = page["ctr"]

    evidence = {
        "weighted_position": position,
        "impressions": impressions,
        "ctr": ctr,
        "band_median_ctr": band_median_ctr,
        "min_impressions": min_impressions,
        "incomplete": page["incomplete"],
    }

    if page["incomplete"] or impressions < min_impressions:
        verdict = "insufficient_data"
    elif position is not None and 4 <= position <= 20:
        verdict = "striking_distance"
    elif (
        position is not None
        and position <= 3
        and band_median_ctr is not None
        and ctr is not None
        and ctr < band_median_ctr
    ):
        verdict = "low_ctr"
    else:
        verdict = "none"

    return {"value": verdict, "evidence": evidence}


def sessions_by_page_key(ga4_rows: list[dict[str, Any]]) -> dict[str, float]:
    """Map normalized GA4 pagePath rows to sessions (contract 6.1)."""
    out: dict[str, float] = {}
    for row in ga4_rows:
        key = normalize_page_key(str(row.get("pagePath") or ""))
        out[key] = out.get(key, 0.0) + float(row.get("sessions") or 0.0)
    return out


# ---------------------------------------------------------------------------
# Ingestion (contract section 8): idempotent upsert at page+date grain
# ---------------------------------------------------------------------------


def sync_search_analytics(
    db: Session,
    project_id: int,
    site_url: str,
    rows: list[dict[str, Any]],
) -> int:
    """Upsert parsed page+date rows; returns rows written. Idempotent."""
    written = 0
    for row in rows:
        page = str(row.get("page") or "")
        row_date_raw = row.get("date")
        if not page or not row_date_raw:
            continue
        row_date = (
            row_date_raw
            if isinstance(row_date_raw, date)
            else date.fromisoformat(str(row_date_raw))
        )
        existing = (
            db.query(models.ProjectGSCPageMetric)
            .filter(
                models.ProjectGSCPageMetric.project_id == project_id,
                models.ProjectGSCPageMetric.property == site_url,
                models.ProjectGSCPageMetric.page == page,
                models.ProjectGSCPageMetric.date == row_date,
            )
            .first()
        )
        fields = {
            "clicks": float(row.get("clicks") or 0.0),
            "impressions": float(row.get("impressions") or 0.0),
            "position": float(row.get("position")) if row.get("position") is not None else None,
            "is_incomplete": bool(row.get("_incomplete")),
        }
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
        else:
            db.add(
                models.ProjectGSCPageMetric(
                    project_id=project_id,
                    property=site_url,
                    page=page,
                    date=row_date,
                    **fields,
                )
            )
        written += 1
    db.commit()
    return written


def stored_page_rows(
    db: Session,
    project_id: int,
    site_url: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Read stored metrics back as service-shaped rows for aggregation."""
    stored = (
        db.query(models.ProjectGSCPageMetric)
        .filter(
            models.ProjectGSCPageMetric.project_id == project_id,
            models.ProjectGSCPageMetric.property == site_url,
            models.ProjectGSCPageMetric.date >= start,
            models.ProjectGSCPageMetric.date <= end,
        )
        .all()
    )
    return [
        {
            "page": r.page,
            "date": r.date.isoformat(),
            "clicks": r.clicks,
            "impressions": r.impressions,
            "position": r.position or 0.0,
            "_incomplete": bool(r.is_incomplete),
        }
        for r in stored
    ]


# ---------------------------------------------------------------------------
# Payload assembly (pure; tests drive it with hand-built rows)
# ---------------------------------------------------------------------------


def build_daily_series(
    rows: list[dict[str, Any]],
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Per-day totals for the window.

    Contract 3.2: the API omits days with no data. A day absent from the rows
    is rendered ``available: false``, never backfilled with zeros.
    """
    by_date: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = str(row.get("date") or "")
        if not day:
            continue
        entry = by_date.setdefault(day, {"clicks": 0.0, "impressions": 0.0, "_pos_w": 0.0})
        entry["clicks"] += float(row.get("clicks") or 0.0)
        imp = float(row.get("impressions") or 0.0)
        entry["impressions"] += imp
        entry["_pos_w"] += float(row.get("position") or 0.0) * imp

    series: list[dict[str, Any]] = []
    day = start
    while day <= end:
        key = day.isoformat()
        entry = by_date.get(key)
        if entry is None:
            series.append({"date": key, "available": False})
        else:
            series.append(
                {
                    "date": key,
                    "available": True,
                    "clicks": entry["clicks"],
                    "impressions": entry["impressions"],
                    "ctr": recompute_ctr(entry["clicks"], entry["impressions"]),
                    "position": (
                        entry["_pos_w"] / entry["impressions"] if entry["impressions"] else None
                    ),
                }
            )
        day += timedelta(days=1)
    return series


def build_pages_payload(
    *,
    site_url: str,
    window_key: str,
    start: date,
    end: date,
    page_rows: list[dict[str, Any]],
    ga4_sessions_by_key: Optional[dict[str, float]],
    ga4_property_timezone: Optional[str],
    min_impressions: int,
    query_meta: dict[str, Any],
    data_state: str,
    sessions_unavailable_reason: str = "no_ga4_binding",
) -> dict[str, Any]:
    """Assemble the Pages payload per the contract.

    ``ga4_property_timezone`` is the GA4 property timezone (or None when there
    is no GA4 binding). ``date_alignment`` is ``exact`` only when it is
    ``America/Los_Angeles``; otherwise ``approximate`` and both zones are named
    (contract section 3).
    """
    pages = aggregate_pages(
        page_rows,
        ga4_sessions_by_key,
        min_impressions=min_impressions,
        sessions_unavailable_reason=sessions_unavailable_reason,
    )
    totals_clicks = sum(p["clicks"] for p in pages)
    totals_impressions = sum(p["impressions"] for p in pages)

    if ga4_property_timezone == GSC_DATE_BASIS:
        date_alignment = "exact"
    else:
        date_alignment = "approximate"

    return {
        "property": site_url,
        "window": window_key,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "date_basis": GSC_DATE_BASIS,
        "ga4_property_timezone": ga4_property_timezone,
        "date_alignment": date_alignment,
        "data_state": data_state,
        "first_incomplete_date": query_meta.get("first_incomplete_date"),
        "response_aggregation_type": query_meta.get("response_aggregation_type"),
        "completeness": query_meta.get("completeness", "full"),
        "partial_reason": query_meta.get("partial_reason"),
        "url_normalization": "strip_host_query_fragment_percent_decode_lowercase_preserve_trailing_slash",
        "totals": {
            "clicks": totals_clicks,
            "impressions": totals_impressions,
            "ctr": recompute_ctr(totals_clicks, totals_impressions),
            "position": weighted_position(
                [{"position": p["avg_position"], "impressions": p["impressions"]} for p in pages]
            ),
        },
        "pages": pages,
        "series": build_daily_series(page_rows, start, end),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
