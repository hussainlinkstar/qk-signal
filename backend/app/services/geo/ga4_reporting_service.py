"""GA4 site-traffic reporting service (SIGV2-1001).

Implements the query layer behind ``docs/ga4-reporting-contract.md``. Every
aggregation rule in that file is binding; the comments here cite the contract
section each non-obvious rule comes from.

Reads run under the customer's own OAuth bearer (resolved by
``ga4_oauth_service``), never the shared service account. No token or secret
appears in responses, logs or error details.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.services.geo.ga4_traffic_service import (
    GA4_DATA_API_BASE,
    GA4AuthError,
    LLM_REFERRAL_SOURCES,
)

logger = logging.getLogger(__name__)

GA4_ADMIN_API_BASE = "https://analyticsadmin.googleapis.com/v1beta"

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRYABLE_STATUS_CODES = {500, 502, 503}
REPORT_PAGE_LIMIT = 10000
REPORT_MAX_PAGES = 50


class GA4ReportError(Exception):
    """Raised when a GA4 reporting call fails in a non-auth way."""


class GA4RateLimitError(Exception):
    """Raised when GA4 returns 429 after retries are exhausted."""


# SIGV2-1202: a 401 and a 403 are different facts and must not be collapsed
# into one "reconnect" instruction.
#   401 - the authorization itself is invalid or expired. Reconnecting fixes it.
#   403 - the authorization is fine and Google refused this request: either the
#         property is not shared with this account, or the grant is missing the
#         analytics scope. Reconnecting the same account fixes neither, and
#         telling the customer to reconnect is what produced the loop.
GA4_REASON_INVALID_CREDENTIALS = "invalid_credentials"
GA4_REASON_INSUFFICIENT_SCOPE = "insufficient_scope"
GA4_REASON_PROPERTY_DENIED = "property_denied"
GA4_REASON_PERMISSION_DENIED = "permission_denied"

# Markers are matched against the provider's error body for classification
# only. The body itself never leaves this module: Google's messages can name
# the signed-in account, so only the fixed reason codes above are propagated.
_SCOPE_DENIED_MARKERS = (
    "access_token_scope_insufficient",
    "insufficient authentication scopes",
    "insufficient_scope",
)
_PROPERTY_DENIED_MARKERS = (
    "sufficient permissions",
    "permission to access",
    "user does not have",
    "caller does not have permission",
)


def classify_permission_failure(status_code: int, body_text: str) -> str:
    """Reason code for a 401/403, from the fixed vocabulary above."""
    if status_code == 401:
        return GA4_REASON_INVALID_CREDENTIALS
    text = (body_text or "").lower()
    if any(marker in text for marker in _SCOPE_DENIED_MARKERS):
        return GA4_REASON_INSUFFICIENT_SCOPE
    if any(marker in text for marker in _PROPERTY_DENIED_MARKERS):
        return GA4_REASON_PROPERTY_DENIED
    # An unrecognised 403 is a denial of some kind, but it is not evidence of a
    # property denial, so it is never reported as one.
    return GA4_REASON_PERMISSION_DENIED


def _permission_failure_text(response: Any) -> str:
    """Error text from a provider response, for classification only."""
    payload: Any = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    parts: list[str] = []
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            parts.append(str(error.get("message") or ""))
            parts.append(str(error.get("status") or ""))
            for key in ("details", "errors"):
                entries = error.get(key)
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            parts.append(str(entry.get("reason") or ""))
                            parts.append(str(entry.get("message") or ""))
        elif isinstance(error, str):
            parts.append(error)
        parts.append(str(payload.get("error_description") or ""))
    if not any(part.strip() for part in parts):
        text = getattr(response, "text", "")
        if isinstance(text, str):
            parts.append(text[:500])
    return " ".join(parts)


class GA4PermissionError(Exception):
    """Raised when GA4/Admin API returns 401 or 403: access revoked or denied.

    SIGV2-1202: carries the HTTP status and a reason code from the vocabulary
    above so the caller can tell an invalid authorization (401) from a refused
    account (403), and a property denial from a missing scope. The message is
    a reason code only - no provider text, so no account identifier can reach
    a response body, a log line or ``last_error``.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        if reason:
            self.reason = reason
        elif status_code == 401:
            self.reason = GA4_REASON_INVALID_CREDENTIALS
        else:
            self.reason = GA4_REASON_PERMISSION_DENIED


# ---------------------------------------------------------------------------
# Windows and granularity (contract section 3)
# ---------------------------------------------------------------------------

# window key -> (length in days, bucket granularity, GA4 granularity dimension,
#                human-stated bucket boundary rule)
REPORT_WINDOWS: dict[str, tuple[int, str, str, str]] = {
    "7D": (7, "daily", "date", "days"),
    "15D": (15, "daily", "date", "days"),
    "90D": (90, "weekly", "week", "iso_weeks"),
    "12M": (365, "monthly", "month", "calendar_months"),
}


# ---------------------------------------------------------------------------
# Channel mix mapping (contract section 4.1)
#
# THE SINGLE TABLE. Six presentation buckets plus a mandatory "other". Any
# channel group not listed here - known remainder groups and anything GA4 adds
# later - falls into "other". It is never guessed and never dropped.
# ---------------------------------------------------------------------------

CHANNEL_BUCKETS: tuple[str, ...] = (
    "organic",
    "direct",
    "referral",
    "ai",
    "paid",
    "social",
    "other",
)

CHANNEL_BUCKET_LABELS: dict[str, str] = {
    "organic": "Organic",
    "direct": "Direct",
    "referral": "Referral",
    "ai": "AI",
    "paid": "Paid",
    "social": "Social",
    "other": "Other",
}

CHANNEL_GROUP_TO_BUCKET: dict[str, str] = {
    "Organic Search": "organic",
    "Direct": "direct",
    "Referral": "referral",
    "Paid Search": "paid",
    "Paid Shopping": "paid",
    "Paid Video": "paid",
    "Display": "paid",
    "Cross-network": "paid",
    # Judgement call recorded in contract 4.1: Paid Social answers "what did
    # spend produce"; Social means organic social only.
    "Paid Social": "paid",
    "Organic Social": "social",
    "Email": "other",
    "Affiliates": "other",
    "Organic Video": "other",
    "Organic Shopping": "other",
    "Audio": "other",
    "SMS": "other",
    "Mobile Push Notifications": "other",
    "Unassigned": "other",
}

OTHER_BUCKET = "other"


def normalize_ga4_property_id(raw: Optional[str]) -> Optional[str]:
    """Return ``properties/<digits>`` or None if the value is unusable.

    The id is interpolated into GA4 API URLs, so anything that is not digits
    after the prefix is dropped rather than passed through.
    """
    value = (raw or "").strip()
    if value.startswith("properties/"):
        value = value[len("properties/") :]
    if not value.isdigit():
        return None
    return f"properties/{value}"


def channel_bucket_for_group(channel_group: str) -> str:
    """Map a GA4 sessionDefaultChannelGroup value to a presentation bucket.

    Unknown or new groups fall into Other, never a guessed bucket.
    """
    return CHANNEL_GROUP_TO_BUCKET.get(channel_group, OTHER_BUCKET)


def _is_ai_source(session_source: str) -> bool:
    return session_source in LLM_REFERRAL_SOURCES


# ---------------------------------------------------------------------------
# Derived-metric helpers (contract sections 2.2, 2.3, 3.1)
# ---------------------------------------------------------------------------


def engagement_rate(engaged_sessions: int, sessions: int) -> Optional[float]:
    """SUM(engagedSessions) / SUM(sessions); null when sessions is zero."""
    if not sessions:
        return None
    return engaged_sessions / sessions


def weighted_avg_session_duration(rows: list[dict[str, Any]]) -> Optional[float]:
    """Session-weighted average over per-row averageSessionDuration values.

    Contract 2.3: GA4 exposes no total-duration metric, so the per-row average
    must be re-weighted. Zero total sessions yields null.
    """
    total_sessions = sum(row["sessions"] for row in rows)
    if not total_sessions:
        return None
    weighted = sum(row["averageSessionDuration"] * row["sessions"] for row in rows)
    return weighted / total_sessions


def relative_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """(current - previous) / previous for volume metrics; null on zero/missing baseline."""
    if previous is None or previous == 0 or current is None:
        return None
    return (current - previous) / previous


def percentage_point_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    """current - previous for share metrics; null on zero/missing baseline.

    Contract 3.1: a zero or missing previous period yields null, and that rule
    applies to share changes as much as volume changes.
    """
    if previous is None or previous == 0 or current is None:
        return None
    return current - previous


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class GA4ReportingService:
    """Queries the GA4 Data and Admin APIs with a customer OAuth bearer."""

    def __init__(self, access_token: str) -> None:
        if not access_token:
            raise GA4AuthError("GA4ReportingService requires an access token")
        self._access_token = access_token

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _get(self, url: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        return self._request("GET", url, params=params)

    def _post_report(self, property_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", f"{GA4_DATA_API_BASE}/{property_id}:runReport", json=body)

    def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        import time

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                with httpx.Client(timeout=60.0) as client:
                    response = client.request(method, url, headers=headers, **kwargs)
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "GA4 request error: %s, retrying in %.1fs (attempt %d/%d)",
                        type(exc).__name__,
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise GA4ReportError(f"ga4_request_failed:{type(exc).__name__}") from exc

            if response.status_code == 200:
                payload = response.json()
                return payload if isinstance(payload, dict) else {}

            if response.status_code == 429:
                if attempt < MAX_RETRIES:
                    delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "GA4 rate limited (429), retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        MAX_RETRIES,
                    )
                    time.sleep(delay)
                    continue
                raise GA4RateLimitError("ga4_rate_limited")

            if response.status_code in RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
                delay = RETRY_BASE_DELAY_SECONDS * (2**attempt)
                logger.warning(
                    "GA4 returned %d, retrying in %.1fs (attempt %d/%d)",
                    response.status_code,
                    delay,
                    attempt + 1,
                    MAX_RETRIES,
                )
                time.sleep(delay)
                continue

            if response.status_code in (401, 403):
                reason = classify_permission_failure(
                    response.status_code,
                    _permission_failure_text(response),
                )
                raise GA4PermissionError(
                    f"ga4_access_denied_{response.status_code}:{reason}",
                    status_code=response.status_code,
                    reason=reason,
                )

            raise GA4ReportError(f"ga4_http_{response.status_code}")

        raise GA4ReportError("ga4_retries_exhausted") from last_error

    # ------------------------------------------------------------------
    # Admin API
    # ------------------------------------------------------------------

    def get_property_timezone(self, property_id: str) -> Optional[str]:
        """Property timezone from the Admin API; None when unavailable."""
        try:
            payload = self._get(f"{GA4_ADMIN_API_BASE}/{property_id}")
        except (GA4ReportError, GA4RateLimitError):
            logger.warning("GA4 property metadata fetch failed for %s", property_id)
            return None
        timezone_name = str(payload.get("timeZone") or "").strip()
        return timezone_name or None

    def list_key_event_names(self, property_id: str) -> Optional[list[str]]:
        """Configured key-event names, or None when the listing failed.

        Contract 5.1: only a successful Admin API listing may distinguish
        ``not_configured`` (empty list) from ``observed_zero``. None means the
        state is ``unknown``.
        """
        names: list[str] = []
        page_token: Optional[str] = None
        try:
            for _ in range(10):
                params: dict[str, str] = {"pageSize": "200"}
                if page_token:
                    params["pageToken"] = page_token
                payload = self._get(f"{GA4_ADMIN_API_BASE}/{property_id}/keyEvents", params=params)
                events = payload.get("keyEvents", [])
                if isinstance(events, list):
                    for event in events:
                        if isinstance(event, dict):
                            name = str(event.get("eventName") or "").strip()
                            if name:
                                names.append(name)
                page_token_value = payload.get("nextPageToken")
                page_token = str(page_token_value).strip() if page_token_value else None
                if not page_token:
                    break
        except (GA4ReportError, GA4RateLimitError, GA4PermissionError):
            logger.warning("GA4 key events listing failed for %s", property_id)
            return None
        return names

    # ------------------------------------------------------------------
    # runReport with pagination and data-quality flags
    # ------------------------------------------------------------------

    def run_report(
        self,
        property_id: str,
        *,
        dimensions: list[str],
        metrics: list[str],
        date_ranges: list[dict[str, str]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Run a paginated report; return (parsed rows, data-quality flags).

        Flags detected (contract section 6): ``dataLossFromOtherRow`` and
        ``subjectToThresholding`` from ResponseMetaData, plus ``truncated``
        when pagination hits the bounded maximum before rowCount.
        """
        all_rows: list[dict[str, Any]] = []
        flags: dict[str, Any] = {
            "data_loss_from_other_row": False,
            "subject_to_thresholding": False,
            "truncated": False,
        }
        dimension_headers: list[str] = []
        metric_headers: list[str] = []
        offset = 0

        for _page in range(REPORT_MAX_PAGES):
            # GA4 rejects "dateRange" in dimensions (INVALID_ARGUMENT: it is a
            # pseudo-dimension usable in Pivot/OrderBy only). With multiple
            # dateRanges Google adds the column to the response on its own, and
            # our parsing reads dimensionHeaders from the response, so
            # filtering here keeps parsed["dateRange"] intact while no caller
            # can reintroduce the 400.
            wire_dimensions = [d for d in dimensions if d != "dateRange"]
            body: dict[str, Any] = {
                "dateRanges": date_ranges,
                "metrics": [{"name": m} for m in metrics],
                "keepEmptyRows": False,
                "limit": REPORT_PAGE_LIMIT,
                "offset": offset,
            }
            if wire_dimensions:
                body["dimensions"] = [{"name": d} for d in wire_dimensions]
            payload = self._post_report(property_id, body)

            if not dimension_headers:
                dimension_headers = [h.get("name", "") for h in payload.get("dimensionHeaders", [])]
                metric_headers = [h.get("name", "") for h in payload.get("metricHeaders", [])]

            metadata = payload.get("metadata") or {}
            if metadata.get("dataLossFromOtherRow"):
                flags["data_loss_from_other_row"] = True
            if metadata.get("subjectToThresholding"):
                flags["subject_to_thresholding"] = True

            for row in payload.get("rows", []) or []:
                dim_values = [v.get("value", "") for v in row.get("dimensionValues", [])]
                metric_values = [v.get("value", "0") for v in row.get("metricValues", [])]
                parsed: dict[str, Any] = dict(zip(dimension_headers, dim_values))
                for name, raw in zip(metric_headers, metric_values):
                    try:
                        parsed[name] = float(raw)
                    except (TypeError, ValueError):
                        parsed[name] = 0.0
                all_rows.append(parsed)

            row_count = int(payload.get("rowCount") or 0)
            fetched = offset + len(payload.get("rows", []) or [])
            if fetched >= row_count or not payload.get("rows"):
                break
            offset = fetched
        else:
            # Reached REPORT_MAX_PAGES without seeing all rows.
            flags["truncated"] = True

        return all_rows, flags


# ---------------------------------------------------------------------------
# Period computation (contract section 3)
# ---------------------------------------------------------------------------


def compute_periods(window_key: str, timezone_name: str) -> dict[str, Any]:
    """Current and comparison date ranges in the GA4 property timezone.

    The end date is "yesterday" in the property timezone: GA4's current day is
    still accumulating and would poison period-over-period comparisons.
    """
    if window_key not in REPORT_WINDOWS:
        raise ValueError(f"unsupported_report_window:{window_key}")
    days, granularity, ga4_dim, bucket_rule = REPORT_WINDOWS[window_key]
    try:
        tz = ZoneInfo(timezone_name)
    except Exception:
        tz = timezone.utc
        timezone_name = "UTC"
    today = datetime.now(tz).date()
    end = today - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return {
        "start": start,
        "end": end,
        "previous_start": prev_start,
        "previous_end": prev_end,
        "timezone": timezone_name,
        "granularity": granularity,
        "ga4_granularity_dimension": ga4_dim,
        "bucket_boundary": bucket_rule,
    }


# ---------------------------------------------------------------------------
# Aggregation (contract sections 2-5)
# ---------------------------------------------------------------------------


def _range_key(row: dict[str, Any]) -> str:
    return str(row.get("dateRange") or "date_range_0")


def _sum_metric(rows: list[dict[str, Any]], metric: str) -> float:
    return sum(float(row.get(metric) or 0.0) for row in rows)


def aggregate_overview(
    series_rows: list[dict[str, Any]],
    totals_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the overview KPIs.

    ``series_rows`` are per-bucket rows with component metrics for the current
    range only (``date_range_0`` rows of the series report already filtered).
    ``totals_rows`` are the two dateRange rows of the dedicated totalUsers
    report (contract 2.1: a single range per period, never summed).
    """
    sessions = _sum_metric(series_rows, "sessions")
    pageviews = _sum_metric(series_rows, "screenPageViews")
    key_events = _sum_metric(series_rows, "keyEvents")
    engaged = _sum_metric(series_rows, "engagedSessions")
    duration_rows = [
        {
            "sessions": float(r.get("sessions") or 0.0),
            "averageSessionDuration": float(r.get("averageSessionDuration") or 0.0),
        }
        for r in series_rows
    ]
    users_by_range = {r.get("dateRange"): float(r.get("totalUsers") or 0.0) for r in totals_rows}
    return {
        "sessions": sessions,
        "pageviews": pageviews,
        "key_events": key_events,
        "engaged_sessions": engaged,
        "total_users": users_by_range,
        "engagement_rate": engagement_rate(int(engaged), int(sessions)),
        "avg_session_duration": weighted_avg_session_duration(duration_rows),
        # Contract 2.4: Audience is deliberately unimplemented.
        "audience": None,
    }


def compute_channel_mix(
    channel_rows: list[dict[str, Any]], total_sessions: float
) -> dict[str, dict[str, Any]]:
    """Bucket sessions for one range, AI subtracted from host buckets.

    Contract 4.2: rows whose sessionSource is in LLM_REFERRAL_SOURCES are
    attributed to AI and are NOT counted in whichever bucket their channel
    group mapped to - the host bucket is reduced by exactly those sessions.
    """
    buckets = {bucket: 0.0 for bucket in CHANNEL_BUCKETS}
    for row in channel_rows:
        sessions = float(row.get("sessions") or 0.0)
        if _is_ai_source(str(row.get("sessionSource") or "")):
            buckets["ai"] += sessions
        else:
            buckets[channel_bucket_for_group(str(row.get("sessionDefaultChannelGroup") or ""))] += (
                sessions
            )
    shares = {
        bucket: (round(buckets[bucket] / total_sessions * 100, 1) if total_sessions else None)
        for bucket in CHANNEL_BUCKETS
    }
    return {
        bucket: {"sessions": buckets[bucket], "share": shares[bucket]} for bucket in CHANNEL_BUCKETS
    }


def _format_bucket_label(dim: str, raw: str) -> str:
    """Human label for a granularity dimension value (contract 3)."""
    raw = str(raw)
    if dim == "date" and len(raw) == 8:
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if dim == "week":
        return f"W{raw}"
    if dim == "month" and len(raw) == 2:
        return raw
    return raw


def _bucket_metric_sums(
    rows: list[dict[str, Any]], metric: str, *, ai_from_source: bool
) -> dict[str, float]:
    """Sum a metric into channel buckets for one range.

    ``ai_from_source`` mirrors compute_channel_mix: rows whose sessionSource is
    an LLM referrer move to the ``ai`` bucket. Only usable when the report
    carries sessionSource; per-channel users are requested without it (a user
    can share two sources), so that breakdown sums by channel group alone.
    """
    buckets = {bucket: 0.0 for bucket in CHANNEL_BUCKETS}
    for row in rows:
        value = float(row.get(metric) or 0.0)
        if ai_from_source and _is_ai_source(str(row.get("sessionSource") or "")):
            buckets["ai"] += value
        else:
            buckets[channel_bucket_for_group(str(row.get("sessionDefaultChannelGroup") or ""))] += (
                value
            )
    return buckets


def _metric_breakdown(cur: dict[str, float], prev: dict[str, float]) -> list[dict[str, Any]]:
    """Per-channel rows for the KPI hover panels: the value, and the change.

    ``value`` carries the current period on its own. A property with no
    previous period - a new GA4 account, or a window that reaches back before
    the property existed - has no computable change, so a change-only row had
    nothing to show and was dropped. With every row dropped, every card fell
    back to the same "no breakdown" sentence, which is how five cards built to
    show five different things ended up reading identically.

    The value is always measurable; the change is not. Reporting the split
    this way means the panel degrades to "Organic 7" instead of to silence.
    """
    return [
        {
            "bucket": bucket,
            "label": CHANNEL_BUCKET_LABELS[bucket],
            "value": cur[bucket],
            "change": {
                "value": relative_change(cur[bucket], prev[bucket]),
                "kind": "relative",
            },
        }
        for bucket in CHANNEL_BUCKETS
    ]


def build_site_traffic_payload(
    *,
    window_key: str,
    timezone_name: str,
    fetched_at: datetime,
    totals_rows: list[dict[str, Any]],
    series_rows: list[dict[str, Any]],
    channel_rows: list[dict[str, Any]],
    event_rows: list[dict[str, Any]],
    event_channel_rows: list[dict[str, Any]],
    user_channel_rows: Optional[list[dict[str, Any]]] = None,
    key_event_names: Optional[list[str]],
    data_quality: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the site-traffic payload from parsed GA4 rows.

    Pure function: every aggregation rule of docs/ga4-reporting-contract.md
    sections 2-5 lives here so tests can feed hand-built rows and assert the
    hand-calculated outputs without touching HTTP.
    """
    periods = compute_periods(window_key, timezone_name)
    ga4_dim = periods["ga4_granularity_dimension"]

    cur_series = [r for r in series_rows if _range_key(r) == "date_range_0"]
    prev_series = [r for r in series_rows if _range_key(r) == "date_range_1"]

    overview = aggregate_overview(cur_series, totals_rows)
    prev_overview = aggregate_overview(prev_series, totals_rows)

    cur_sessions = overview["sessions"]
    prev_sessions = prev_overview["sessions"]

    overview_payload = {
        "sessions": cur_sessions,
        "pageviews": overview["pageviews"],
        "key_events": overview["key_events"],
        "engaged_sessions": overview["engaged_sessions"],
        "total_users": overview["total_users"].get("date_range_0"),
        "engagement_rate": overview["engagement_rate"],
        # Contract 2.2: bounce is 1 - engagementRate, never averaged or summed.
        "bounce_rate": (
            None if overview["engagement_rate"] is None else 1 - overview["engagement_rate"]
        ),
        "avg_session_duration": overview["avg_session_duration"],
        # Contract 2.4: Audience is deliberately unimplemented.
        "audience": {"value": None, "available": False, "reason": "not_defined"},
        "changes": {
            "sessions": {
                "value": relative_change(cur_sessions, prev_sessions),
                "kind": "relative",
            },
            "pageviews": {
                "value": relative_change(overview["pageviews"], prev_overview["pageviews"]),
                "kind": "relative",
            },
            "key_events": {
                "value": relative_change(overview["key_events"], prev_overview["key_events"]),
                "kind": "relative",
            },
            "total_users": {
                "value": relative_change(
                    overview["total_users"].get("date_range_0"),
                    overview["total_users"].get("date_range_1"),
                ),
                "kind": "relative",
            },
        },
    }

    # Time series for the current range, one entry per bucket.
    series_payload = [
        {
            "bucket": _format_bucket_label(ga4_dim, str(row.get(ga4_dim) or "")),
            "sessions": float(row.get("sessions") or 0.0),
            "pageviews": float(row.get("screenPageViews") or 0.0),
            "key_events": float(row.get("keyEvents") or 0.0),
        }
        for row in cur_series
    ]

    cur_channel = [r for r in channel_rows if _range_key(r) == "date_range_0"]
    prev_channel = [r for r in channel_rows if _range_key(r) == "date_range_1"]
    cur_mix = compute_channel_mix(cur_channel, cur_sessions)
    prev_mix = compute_channel_mix(prev_channel, prev_sessions)
    channel_mix = [
        {
            "bucket": bucket,
            "label": CHANNEL_BUCKET_LABELS[bucket],
            "sessions": cur_mix[bucket]["sessions"],
            "share": cur_mix[bucket]["share"],
            # Contract 3.1: share changes are percentage points, labelled.
            "share_change": {
                "value": percentage_point_change(
                    cur_mix[bucket]["share"], prev_mix[bucket]["share"]
                ),
                "kind": "percentage_points",
            },
        }
        for bucket in CHANNEL_BUCKETS
    ]

    cur_events = [r for r in event_rows if _range_key(r) == "date_range_0"]
    prev_events = [r for r in event_rows if _range_key(r) == "date_range_1"]
    cur_event_channel = [r for r in event_channel_rows if _range_key(r) == "date_range_0"]
    prev_event_channel = [r for r in event_channel_rows if _range_key(r) == "date_range_1"]

    total_key_events = _sum_metric(cur_events, "keyEvents")
    prev_key_events = _sum_metric(prev_events, "keyEvents")

    if key_event_names is None:
        key_event_state = "unknown"
    elif not key_event_names:
        key_event_state = "not_configured"
    elif total_key_events == 0:
        key_event_state = "observed_zero"
    else:
        key_event_state = "active"

    events_breakdown = [
        {
            "event_name": str(r.get("eventName") or ""),
            "key_events": float(r.get("keyEvents") or 0.0),
        }
        for r in cur_events
        if str(r.get("eventName") or "")
    ]

    event_channel_buckets = {bucket: 0.0 for bucket in CHANNEL_BUCKETS}
    for row in cur_event_channel:
        count = float(row.get("keyEvents") or 0.0)
        if _is_ai_source(str(row.get("sessionSource") or "")):
            event_channel_buckets["ai"] += count
        else:
            group = str(row.get("sessionDefaultChannelGroup") or "")
            event_channel_buckets[channel_bucket_for_group(group)] += count
    events_by_channel = [
        {
            "bucket": bucket,
            "label": CHANNEL_BUCKET_LABELS[bucket],
            "key_events": event_channel_buckets[bucket],
        }
        for bucket in CHANNEL_BUCKETS
    ]

    partial = any(
        [
            data_quality.get("data_loss_from_other_row"),
            data_quality.get("subject_to_thresholding"),
            data_quality.get("truncated"),
        ]
    )
    if cur_sessions == 0 and prev_sessions == 0:
        availability = "no_data"
    elif partial:
        availability = "partial"
    else:
        availability = "available"

    # Per-card hover-panel breakdowns (the approved xsell overlay's factor
    # rows). Each KPI gets its own measured factors, never another card's:
    # sessions/users/conversions are per-channel relative changes; engagement
    # is its own GA4 components. Users rows are GA4 per-channel counts, which
    # overlap - a person arriving through two channels counts in both, so the
    # rows are change factors only and never reconcile to the total (2.1).
    user_channel_rows = user_channel_rows or []
    cur_user_channel = [r for r in user_channel_rows if _range_key(r) == "date_range_0"]
    prev_user_channel = [r for r in user_channel_rows if _range_key(r) == "date_range_1"]

    cur_bounce = (
        None if overview["engagement_rate"] is None else (1 - overview["engagement_rate"]) * 100
    )
    prev_bounce = (
        None
        if prev_overview["engagement_rate"] is None
        else (1 - prev_overview["engagement_rate"]) * 100
    )
    breakdowns = {
        "sessions": _metric_breakdown(
            {b: cur_mix[b]["sessions"] for b in CHANNEL_BUCKETS},
            {b: prev_mix[b]["sessions"] for b in CHANNEL_BUCKETS},
        ),
        "users": _metric_breakdown(
            _bucket_metric_sums(cur_user_channel, "totalUsers", ai_from_source=False),
            _bucket_metric_sums(prev_user_channel, "totalUsers", ai_from_source=False),
        ),
        "engagement": [
            {
                "metric": "engaged_sessions",
                "value": overview["engaged_sessions"],
                "value_kind": "count",
                "change": {
                    "value": relative_change(
                        overview["engaged_sessions"], prev_overview["engaged_sessions"]
                    ),
                    "kind": "relative",
                },
            },
            {
                "metric": "bounce_rate",
                # Already scaled to 0-100 above, so the surface renders it as
                # a percentage without rescaling it a second time.
                "value": cur_bounce,
                "value_kind": "percent",
                "change": {
                    "value": percentage_point_change(cur_bounce, prev_bounce),
                    "kind": "percentage_points",
                },
            },
            {
                "metric": "avg_session_duration",
                "value": overview["avg_session_duration"],
                "value_kind": "seconds",
                "change": {
                    "value": relative_change(
                        overview["avg_session_duration"], prev_overview["avg_session_duration"]
                    ),
                    "kind": "relative",
                },
            },
        ],
        "conversions": _metric_breakdown(
            _bucket_metric_sums(cur_event_channel, "keyEvents", ai_from_source=True),
            _bucket_metric_sums(prev_event_channel, "keyEvents", ai_from_source=True),
        ),
    }

    return {
        "window": window_key,
        "start_date": periods["start"].isoformat(),
        "end_date": periods["end"].isoformat(),
        "comparison_start_date": periods["previous_start"].isoformat(),
        "comparison_end_date": periods["previous_end"].isoformat(),
        "property_timezone": periods["timezone"],
        "bucket_granularity": periods["granularity"],
        "bucket_boundary": periods["bucket_boundary"],
        "data_freshness": fetched_at.isoformat(),
        "availability": availability,
        "data_quality": data_quality,
        "overview": overview_payload,
        "series": series_payload,
        "channel_mix": channel_mix,
        "breakdowns": breakdowns,
        "key_events": {
            "state": key_event_state,
            "total": total_key_events,
            "change": {
                "value": relative_change(total_key_events, prev_key_events),
                "kind": "relative",
            },
            "by_event": events_breakdown,
            "by_channel": events_by_channel,
        },
    }


def _site_traffic_reports(
    service: GA4ReportingService,
    property_id: str,
    window_key: str,
    periods: dict[str, Any],
) -> dict[str, Any]:
    """Run the five reports the payload needs and merge quality flags."""
    ranges = [
        {
            "startDate": periods["start"].isoformat(),
            "endDate": periods["end"].isoformat(),
        },
        {
            "startDate": periods["previous_start"].isoformat(),
            "endDate": periods["previous_end"].isoformat(),
        },
    ]
    quality: dict[str, Any] = {
        "data_loss_from_other_row": False,
        "subject_to_thresholding": False,
        "truncated": False,
    }

    def _merge(flags: dict[str, Any]) -> None:
        for key in quality:
            quality[key] = quality[key] or flags.get(key, False)

    # Contract 2.1: totalUsers comes from its own request, one dateRange per
    # period, never derived by summing daily or per-channel rows.
    totals_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange"],
        metrics=["totalUsers"],
        date_ranges=ranges,
    )
    _merge(flags)

    series_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange", periods["ga4_granularity_dimension"]],
        metrics=[
            "sessions",
            "screenPageViews",
            "keyEvents",
            "engagedSessions",
            "averageSessionDuration",
        ],
        date_ranges=ranges,
    )
    _merge(flags)

    channel_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange", "sessionDefaultChannelGroup", "sessionSource"],
        metrics=["sessions"],
        date_ranges=ranges,
    )
    _merge(flags)

    event_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange", "eventName"],
        metrics=["keyEvents"],
        date_ranges=ranges,
    )
    _merge(flags)

    event_channel_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange", "sessionDefaultChannelGroup", "sessionSource"],
        metrics=["keyEvents"],
        date_ranges=ranges,
    )
    _merge(flags)

    # Contract 2.1 honoured: per-channel users are GA4's own per-group counts,
    # never summed into a total and labelled as overlapping buckets. Used only
    # for the Users KPI's per-channel change breakdown.
    user_channel_rows, flags = service.run_report(
        property_id,
        dimensions=["dateRange", "sessionDefaultChannelGroup"],
        metrics=["totalUsers"],
        date_ranges=ranges,
    )
    _merge(flags)

    return {
        "totals_rows": totals_rows,
        "series_rows": series_rows,
        "channel_rows": channel_rows,
        "event_rows": event_rows,
        "event_channel_rows": event_channel_rows,
        "user_channel_rows": user_channel_rows,
        "data_quality": quality,
    }


def fetch_site_traffic(
    service: GA4ReportingService,
    property_id: str,
    window_key: str,
    persisted_timezone: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[str]]:
    """Fetch and assemble the site-traffic payload.

    Returns (payload, property_timezone_seen) so the caller can persist the
    timezone on the binding. Falls back to the persisted timezone, then UTC,
    when the Admin API is unreachable; that fallback is flagged in
    data_quality.
    """
    timezone_name = service.get_property_timezone(property_id)
    timezone_source = "admin_api"
    if not timezone_name:
        timezone_name = persisted_timezone or "UTC"
        timezone_source = "persisted" if persisted_timezone else "assumed_utc"

    periods = compute_periods(window_key, timezone_name)
    reports = _site_traffic_reports(service, property_id, window_key, periods)
    key_event_names = service.list_key_event_names(property_id)

    data_quality = dict(reports["data_quality"])
    data_quality["timezone_source"] = timezone_source

    payload = build_site_traffic_payload(
        window_key=window_key,
        timezone_name=timezone_name,
        fetched_at=datetime.now(timezone.utc),
        totals_rows=reports["totals_rows"],
        series_rows=reports["series_rows"],
        channel_rows=reports["channel_rows"],
        event_rows=reports["event_rows"],
        event_channel_rows=reports["event_channel_rows"],
        user_channel_rows=reports["user_channel_rows"],
        key_event_names=key_event_names,
        data_quality=data_quality,
    )
    return payload, timezone_name if timezone_source == "admin_api" else None
