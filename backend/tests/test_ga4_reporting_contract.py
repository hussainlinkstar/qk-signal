"""SIGV2-1001: GA4 reporting contract tests.

Every expected number in this file is hand-calculated in a comment next to the
fixture. The assertions exist because the failure mode here is a plausible-
looking wrong number, not a crash. See docs/ga4-reporting-contract.md.
"""

from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from app.services.geo.ga4_reporting_service import (
    GA4PermissionError,
    GA4RateLimitError,
    GA4ReportingService,
    build_site_traffic_payload,
    channel_bucket_for_group,
    fetch_site_traffic,
)

# ---------------------------------------------------------------------------
# Hand-built rows
#
# Channel-mix fixture (used by several tests). Sessions are chosen so every
# arithmetic answer is an integer or a tidy decimal.
#
#   channel_group      source              cur   prev
#   Referral           chatgpt.com          30     0   -> AI (host = Referral)
#   Organic Search     search.brave.com     20     0   -> AI (host = Organic!)
#   Referral           forum.example        70    10   -> Referral
#   Organic Search     google              180   100   -> Organic
#   Direct             (direct)             50    40   -> Direct
#   Paid Search        google ads           40    20   -> Paid
#   Organic Social     facebook              0    30   -> Social (prev only)
#   Email              newsletter           10     0   -> Other
#   BrandNewGroup      unknown               0    20   -> Other (prev only)
#
# Current buckets:  AI=50  Referral=70  Organic=180  Direct=50  Paid=40
#                   Social=0  Other=10                 total=400
# Previous buckets: AI=0  Referral=10  Organic=100  Direct=40  Paid=20
#                   Social=30  Other=20                total=220
#
# Shares (1 decimal, unnormalised): AI 12.5, Referral 17.5, Organic 45.0,
# Direct 12.5, Paid 10.0, Social 0.0, Other 2.5  -> sum = 100.0 here
# ---------------------------------------------------------------------------


def _channel_row(range_key: str, group: str, source: str, sessions: float) -> dict:
    return {
        "dateRange": range_key,
        "sessionDefaultChannelGroup": group,
        "sessionSource": source,
        "sessions": sessions,
    }


CHANNEL_ROWS = [
    _channel_row("date_range_0", "Referral", "chatgpt.com", 30),
    _channel_row("date_range_0", "Organic Search", "search.brave.com", 20),
    _channel_row("date_range_0", "Referral", "forum.example", 70),
    _channel_row("date_range_0", "Organic Search", "google", 180),
    _channel_row("date_range_0", "Direct", "(direct)", 50),
    _channel_row("date_range_0", "Paid Search", "google ads", 40),
    _channel_row("date_range_0", "Email", "newsletter", 10),
    _channel_row("date_range_1", "Referral", "forum.example", 10),
    _channel_row("date_range_1", "Organic Search", "google", 100),
    _channel_row("date_range_1", "Direct", "(direct)", 40),
    _channel_row("date_range_1", "Paid Search", "google ads", 20),
    _channel_row("date_range_1", "Organic Social", "facebook", 30),
    _channel_row("date_range_1", "BrandNewGroup", "unknown", 20),
]


def _series_row(range_key: str, bucket: str, sessions: float, **metrics: float) -> dict:
    row = {
        "dateRange": range_key,
        "date": bucket,
        "sessions": sessions,
        "screenPageViews": 0.0,
        "keyEvents": 0.0,
        "engagedSessions": 0.0,
        "averageSessionDuration": 0.0,
    }
    row.update(metrics)
    return row


def _payload(**overrides) -> dict:
    kwargs = {
        "window_key": "7D",
        "timezone_name": "Europe/Bucharest",
        "fetched_at": datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc),
        "totals_rows": [
            {"dateRange": "date_range_0", "totalUsers": 120.0},
            {"dateRange": "date_range_1", "totalUsers": 90.0},
        ],
        "series_rows": [],
        "channel_rows": [],
        "event_rows": [],
        "event_channel_rows": [],
        "key_event_names": ["sign_up"],
        "data_quality": {
            "data_loss_from_other_row": False,
            "subject_to_thresholding": False,
            "truncated": False,
        },
    }
    kwargs.update(overrides)
    return build_site_traffic_payload(**kwargs)


# ---------------------------------------------------------------------------
# 2.1 totalUsers is de-duplicated and must not be summed
# ---------------------------------------------------------------------------


def test_total_users_comes_from_single_range_not_row_sum() -> None:
    # The same 120 users visiting on 3 days still count as 120 for the range.
    # A naive implementation summing daily rows (120/day) would report 360.
    series_rows = [
        _series_row("date_range_0", "20260929", 100, screenPageViews=150),
        _series_row("date_range_0", "20260930", 100, screenPageViews=150),
        _series_row("date_range_0", "date_range_0_daily3", 0),
    ]
    series_rows[2] = _series_row("date_range_0", "20261001", 100, screenPageViews=150)
    payload = _payload(
        totals_rows=[
            {"dateRange": "date_range_0", "totalUsers": 120.0},
            {"dateRange": "date_range_1", "totalUsers": 0.0},
        ],
        series_rows=series_rows,
    )
    assert payload["overview"]["total_users"] == 120.0
    # Previous range is zero -> change is null, never infinity or 100%.
    assert payload["overview"]["changes"]["total_users"]["value"] is None


def test_total_users_report_shape_is_single_range_per_period() -> None:
    # fetch_site_traffic must request totalUsers with dims ["dateRange"] only:
    # no date/source dimension, so GA4 de-duplicates over the whole range.
    service = GA4ReportingService(access_token="tok")
    calls: list[dict] = []

    def fake_run_report(property_id, *, dimensions, metrics, date_ranges):
        calls.append({"dimensions": dimensions, "metrics": metrics})
        if metrics == ["totalUsers"]:
            return [{"dateRange": "date_range_0", "totalUsers": 5.0}], {}
        return [], {}

    service.run_report = fake_run_report  # type: ignore[method-assign]
    service.get_property_timezone = lambda pid: "UTC"  # type: ignore[method-assign]
    service.list_key_event_names = lambda pid: []  # type: ignore[method-assign]

    fetch_site_traffic(service, "properties/1", "7D")

    totals_calls = [c for c in calls if c["metrics"] == ["totalUsers"]]
    # Exactly one un-dimensioned totals query, so the published total is the
    # one GA4 de-duplicated over the whole range.
    assert [c for c in totals_calls if c["dimensions"] == ["dateRange"]] == [
        {"dimensions": ["dateRange"], "metrics": ["totalUsers"]}
    ]
    # The per-channel users query is a separate, permitted read (contract 2.1
    # allows per-channel user counts that are never presented as a total). It
    # must stay channel-dimensioned so it can never be mistaken for the
    # totals query and summed: summing de-duplicated per-channel users
    # double-counts anyone who arrived through two channels.
    assert [c["dimensions"] for c in totals_calls if c["dimensions"] != ["dateRange"]] == [
        ["dateRange", "sessionDefaultChannelGroup"]
    ]


# ---------------------------------------------------------------------------
# 2.3 average session duration is session-weighted
# ---------------------------------------------------------------------------


def test_avg_session_duration_is_session_weighted() -> None:
    # Hand calc: (1000*10 + 1*900) / 1001 = 10900/1001 = 10.8891...
    # A plain mean of (10, 900) gives 455.0 - visibly wrong.
    series_rows = [
        _series_row("date_range_0", "20260929", 1000, averageSessionDuration=10.0),
        _series_row("date_range_0", "20260930", 1, averageSessionDuration=900.0),
    ]
    payload = _payload(series_rows=series_rows)
    assert payload["overview"]["avg_session_duration"] == pytest.approx(10900.0 / 1001.0, rel=1e-6)
    assert payload["overview"]["avg_session_duration"] != pytest.approx(455.0)


def test_avg_session_duration_zero_sessions_is_null() -> None:
    payload = _payload(series_rows=[])
    assert payload["overview"]["avg_session_duration"] is None


# ---------------------------------------------------------------------------
# 2.2 engagement rate from components, not averaged
# ---------------------------------------------------------------------------


def test_engagement_rate_from_component_sums() -> None:
    # Rows: (engaged=90, sessions=100) rate 0.9; (engaged=2, sessions=1000) rate 0.002
    # Component sum: 92/1100 = 0.083636...  Averaged rate: 0.451 - wrong.
    series_rows = [
        _series_row("date_range_0", "20260929", 100, engagedSessions=90.0),
        _series_row("date_range_0", "20260930", 1000, engagedSessions=2.0),
    ]
    payload = _payload(series_rows=series_rows)
    assert payload["overview"]["engagement_rate"] == pytest.approx(92.0 / 1100.0, rel=1e-6)
    assert payload["overview"]["bounce_rate"] == pytest.approx(1 - 92.0 / 1100.0, rel=1e-6)


def test_engagement_rate_zero_sessions_is_null() -> None:
    payload = _payload(series_rows=[])
    assert payload["overview"]["engagement_rate"] is None
    assert payload["overview"]["bounce_rate"] is None


# ---------------------------------------------------------------------------
# 4.2 AI is subtracted from its host channel, including non-Referral hosts
# ---------------------------------------------------------------------------


def test_ai_sessions_subtracted_from_host_buckets() -> None:
    series_rows = [
        _series_row("date_range_0", "20261001", 400, screenPageViews=900),
        _series_row("date_range_1", "20260924", 220, screenPageViews=500),
    ]
    payload = _payload(series_rows=series_rows, channel_rows=CHANNEL_ROWS)

    mix = {entry["bucket"]: entry for entry in payload["channel_mix"]}
    # AI = 30 (chatgpt, host Referral) + 20 (brave, host Organic) = 50.
    assert mix["ai"]["sessions"] == 50
    # Both AI sources removed from their hosts: Referral 100-30=70, Organic 200-20=180.
    assert mix["referral"]["sessions"] == 70
    assert mix["organic"]["sessions"] == 180
    assert mix["direct"]["sessions"] == 50
    assert mix["paid"]["sessions"] == 40
    assert mix["social"]["sessions"] == 0
    assert mix["other"]["sessions"] == 10
    # Buckets + Other reconcile exactly to total sessions.
    assert sum(e["sessions"] for e in payload["channel_mix"]) == 400


def test_shares_one_decimal_and_reconcile() -> None:
    series_rows = [
        _series_row("date_range_0", "20261001", 400),
        _series_row("date_range_1", "20260924", 220),
    ]
    payload = _payload(series_rows=series_rows, channel_rows=CHANNEL_ROWS)
    mix = {entry["bucket"]: entry for entry in payload["channel_mix"]}
    assert mix["ai"]["share"] == 12.5
    assert mix["referral"]["share"] == 17.5
    assert mix["organic"]["share"] == 45.0
    assert mix["other"]["share"] == 2.5
    total_share = sum(e["share"] for e in payload["channel_mix"])
    assert abs(total_share - 100.0) < 0.7  # rounding residue visible, not absorbed

    # Share change is percentage points, labelled.
    # Organic prev share = 100/220*100 = 45.4545 -> 45.5; change = 45.0 - 45.5 = -0.5
    assert mix["organic"]["share_change"]["kind"] == "percentage_points"
    assert mix["organic"]["share_change"]["value"] == pytest.approx(-0.5, abs=0.11)
    # AI previous share 0 -> change is null, not a relative change of a percentage.
    assert mix["ai"]["share_change"]["value"] is None


def test_unknown_channel_group_falls_into_other() -> None:
    assert channel_bucket_for_group("SomeFutureGA4Group") == "other"
    assert channel_bucket_for_group("Email") == "other"
    assert channel_bucket_for_group("Paid Social") == "paid"
    assert channel_bucket_for_group("Organic Social") == "social"


def test_zero_sessions_period_gives_null_shares() -> None:
    payload = _payload(series_rows=[], channel_rows=[])
    assert all(e["share"] is None for e in payload["channel_mix"])
    assert payload["availability"] == "no_data"


# ---------------------------------------------------------------------------
# KPI hover-panel breakdowns: each card's own measured factors
# ---------------------------------------------------------------------------


def test_breakdowns_are_per_metric_and_measured() -> None:
    series_rows = [
        _series_row(
            "date_range_0",
            "20261001",
            400,
            screenPageViews=900,
            keyEvents=12,
            engagedSessions=240,
            averageSessionDuration=150,
        ),
        _series_row(
            "date_range_1",
            "20260924",
            220,
            screenPageViews=500,
            keyEvents=8,
            engagedSessions=110,
            averageSessionDuration=120,
        ),
    ]
    user_channel_rows = [
        {
            "dateRange": "date_range_0",
            "sessionDefaultChannelGroup": "Organic Search",
            "totalUsers": 200,
        },
        {"dateRange": "date_range_0", "sessionDefaultChannelGroup": "Direct", "totalUsers": 100},
        {
            "dateRange": "date_range_1",
            "sessionDefaultChannelGroup": "Organic Search",
            "totalUsers": 100,
        },
        {"dateRange": "date_range_1", "sessionDefaultChannelGroup": "Direct", "totalUsers": 100},
    ]
    event_channel_rows = [
        {
            "dateRange": "date_range_0",
            "sessionDefaultChannelGroup": "Referral",
            "sessionSource": "chatgpt.com",
            "keyEvents": 3,
        },
        {
            "dateRange": "date_range_1",
            "sessionDefaultChannelGroup": "Referral",
            "sessionSource": "forum.example",
            "keyEvents": 2,
        },
    ]
    payload = _payload(
        series_rows=series_rows,
        channel_rows=CHANNEL_ROWS,
        user_channel_rows=user_channel_rows,
        event_channel_rows=event_channel_rows,
    )

    br = payload["breakdowns"]
    sessions = {r["bucket"]: r["change"]["value"] for r in br["sessions"]}
    # Organic: cur 180 (200 minus brave's 20), prev 100 -> +80%
    assert sessions["organic"] == pytest.approx(0.8, rel=1e-6)

    users = {r["bucket"]: r["change"]["value"] for r in br["users"]}
    # Organic users 200 vs 100 -> +100%; Direct flat -> 0
    assert users["organic"] == pytest.approx(1.0, rel=1e-6)
    assert users["direct"] == pytest.approx(0.0, rel=1e-6)

    engagement = {r["metric"]: r["change"] for r in br["engagement"]}
    # engaged 240 vs 110 -> +118.18%; duration 150 vs 120 -> +25%
    assert engagement["engaged_sessions"]["value"] == pytest.approx(130 / 110, rel=1e-6)
    assert engagement["avg_session_duration"]["value"] == pytest.approx(0.25, rel=1e-6)
    # bounce: cur = 1 - 240/400 = 40%, prev = 1 - 110/220 = 50% -> -10pp
    assert engagement["bounce_rate"]["kind"] == "percentage_points"
    assert engagement["bounce_rate"]["value"] == pytest.approx(-10.0, abs=0.01)

    conversions = {r["bucket"]: r["change"]["value"] for r in br["conversions"]}
    # AI key events (chatgpt source) land in the ai bucket: 3 vs 0 -> null
    assert conversions["ai"] is None
    # Referral host bucket: cur loses the AI rows -> 0, prev 2 -> -100%
    assert conversions["referral"] == pytest.approx(-1.0, rel=1e-6)


def test_breakdowns_empty_when_no_user_channel_report() -> None:
    payload = _payload(
        series_rows=[_series_row("date_range_0", "20261001", 10)],
        channel_rows=CHANNEL_ROWS,
    )
    assert all(r["change"]["value"] is None for r in payload["breakdowns"]["users"])


# ---------------------------------------------------------------------------
# 3.1 change semantics
# ---------------------------------------------------------------------------


def test_volume_change_relative_and_zero_baseline_null() -> None:
    series_rows = [
        _series_row("date_range_0", "20261001", 400, screenPageViews=900, keyEvents=12),
        _series_row("date_range_1", "20260924", 220, screenPageViews=500),
    ]
    payload = _payload(series_rows=series_rows)
    changes = payload["overview"]["changes"]
    # (400-220)/220 = 0.8181...
    assert changes["sessions"]["value"] == pytest.approx(180.0 / 220.0, rel=1e-6)
    assert changes["sessions"]["kind"] == "relative"
    # pageviews previous 500 -> (900-500)/500 = 0.8
    assert changes["pageviews"]["value"] == pytest.approx(0.8, rel=1e-6)
    # key_events previous 0 -> null, never "new" or 100%.
    assert changes["key_events"]["value"] is None


# ---------------------------------------------------------------------------
# 5.1 key events: three distinct states
# ---------------------------------------------------------------------------


def _key_event_rows(total: float) -> list[dict]:
    return [{"dateRange": "date_range_0", "eventName": "sign_up", "keyEvents": total}]


def test_key_event_state_observed_zero() -> None:
    payload = _payload(
        series_rows=[_series_row("date_range_0", "20261001", 10)],
        event_rows=_key_event_rows(0),
        key_event_names=["sign_up"],
    )
    assert payload["key_events"]["state"] == "observed_zero"


def test_key_event_state_not_configured() -> None:
    payload = _payload(
        series_rows=[_series_row("date_range_0", "20261001", 10)],
        event_rows=[],
        key_event_names=[],
    )
    assert payload["key_events"]["state"] == "not_configured"


def test_key_event_state_unknown_when_listing_fails() -> None:
    payload = _payload(
        series_rows=[_series_row("date_range_0", "20261001", 10)],
        event_rows=_key_event_rows(0),
        key_event_names=None,
    )
    assert payload["key_events"]["state"] == "unknown"


def test_key_event_state_active_and_channel_attribution() -> None:
    # Key events by channel follow the same bucket/AI rules: 3 keyEvents from
    # a chatgpt Referral session attribute to ai, not referral.
    event_channel_rows = [
        _channel_row("date_range_0", "Referral", "chatgpt.com", 0) | {"keyEvents": 3.0},
        _channel_row("date_range_0", "Referral", "forum.example", 0) | {"keyEvents": 7.0},
        _channel_row("date_range_0", "Email", "newsletter", 0) | {"keyEvents": 2.0},
    ]
    payload = _payload(
        series_rows=[_series_row("date_range_0", "20261001", 10, keyEvents=12)],
        event_rows=_key_event_rows(12),
        event_channel_rows=event_channel_rows,
        key_event_names=["sign_up"],
    )
    assert payload["key_events"]["state"] == "active"
    by_channel = {e["bucket"]: e["key_events"] for e in payload["key_events"]["by_channel"]}
    assert by_channel["ai"] == 3.0
    assert by_channel["referral"] == 7.0
    assert by_channel["other"] == 2.0
    # Each key event attributed once: buckets reconcile to the total.
    assert sum(by_channel.values()) == 12.0


# ---------------------------------------------------------------------------
# 6. data quality flags
# ---------------------------------------------------------------------------


def test_data_quality_flags_mark_availability_partial() -> None:
    for flag in ("data_loss_from_other_row", "subject_to_thresholding", "truncated"):
        quality = {
            "data_loss_from_other_row": False,
            "subject_to_thresholding": False,
            "truncated": False,
            flag: True,
        }
        payload = _payload(
            series_rows=[_series_row("date_range_0", "20261001", 10)],
            data_quality=quality,
        )
        assert payload["availability"] == "partial"
        assert payload["data_quality"][flag] is True


# ---------------------------------------------------------------------------
# 3. periods echo
# ---------------------------------------------------------------------------


def test_payload_echoes_boundaries_timezone_and_freshness() -> None:
    payload = _payload(series_rows=[_series_row("date_range_0", "20261001", 10)])
    for key in (
        "start_date",
        "end_date",
        "comparison_start_date",
        "comparison_end_date",
        "property_timezone",
        "bucket_granularity",
        "bucket_boundary",
        "data_freshness",
        "availability",
    ):
        assert key in payload
    assert payload["property_timezone"] == "Europe/Bucharest"
    assert payload["bucket_granularity"] == "daily"
    assert payload["bucket_boundary"] == "days"
    # Comparison window is the immediately preceding equal-length interval.
    start = date.fromisoformat(payload["start_date"])
    comp_end = date.fromisoformat(payload["comparison_end_date"])
    comp_start = date.fromisoformat(payload["comparison_start_date"])
    assert comp_end == start - timedelta(days=1)
    assert (comp_end - comp_start).days == (date.fromisoformat(payload["end_date"]) - start).days


def test_audience_is_unavailable_not_relabelled() -> None:
    payload = _payload(series_rows=[_series_row("date_range_0", "20261001", 10)])
    assert payload["overview"]["audience"] == {
        "value": None,
        "available": False,
        "reason": "not_defined",
    }


# ---------------------------------------------------------------------------
# run_report: pagination, truncation, error mapping
# ---------------------------------------------------------------------------


def _report_response(rows, row_count=None, metadata=None):
    return {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": [{"name": "sessions"}],
        "rows": [
            {
                "dimensionValues": [{"value": r["date"]}],
                "metricValues": [{"value": str(r["sessions"])}],
            }
            for r in rows
        ],
        "rowCount": len(rows) if row_count is None else row_count,
        "metadata": metadata or {},
    }


def test_run_report_never_sends_daterange_as_a_dimension(monkeypatch) -> None:
    # GA4 rejects "dateRange" in dimensions with INVALID_ARGUMENT - it is a
    # pseudo-dimension Google adds to the response automatically when the
    # request carries multiple dateRanges. The wire body must never contain
    # it, while parsed rows still get the key from the response headers.
    service = GA4ReportingService(access_token="tok")
    bodies: list[dict] = []

    def fake_post(property_id, body):
        bodies.append(body)
        return {
            "dimensionHeaders": [{"name": "dateRange"}, {"name": "date"}],
            "metricHeaders": [{"name": "sessions"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "date_range_0"}, {"value": "20261001"}],
                    "metricValues": [{"value": "5"}],
                },
                {
                    "dimensionValues": [{"value": "date_range_1"}, {"value": "20260924"}],
                    "metricValues": [{"value": "3"}],
                },
            ],
            "rowCount": 2,
            "metadata": {},
        }

    monkeypatch.setattr(service, "_post_report", fake_post)
    rows, _flags = service.run_report(
        "properties/1",
        dimensions=["dateRange", "date"],
        metrics=["sessions"],
        date_ranges=[
            {"startDate": "2026-09-25", "endDate": "2026-10-01"},
            {"startDate": "2026-08-25", "endDate": "2026-08-31"},
        ],
    )
    assert bodies[0]["dimensions"] == [{"name": "date"}]
    assert [r["dateRange"] for r in rows] == ["date_range_0", "date_range_1"]


def test_run_report_paginates_to_completion(monkeypatch) -> None:
    service = GA4ReportingService(access_token="tok")
    pages = [
        _report_response([{"date": "20261001", "sessions": 5}] * 3, row_count=5),
        _report_response([{"date": "20261002", "sessions": 5}] * 2, row_count=5),
    ]
    calls: list[int] = []

    def fake_post(property_id, body):
        calls.append(body["offset"])
        return pages[len(calls) - 1]

    monkeypatch.setattr(service, "_post_report", fake_post)
    rows, flags = service.run_report(
        "properties/1",
        dimensions=["date"],
        metrics=["sessions"],
        date_ranges=[{"startDate": "2026-09-25", "endDate": "2026-10-01"}],
    )
    assert len(rows) == 5
    assert calls == [0, 3]
    assert flags["truncated"] is False


def test_run_report_reports_truncation(monkeypatch) -> None:
    import app.services.geo.ga4_reporting_service as svc_mod

    monkeypatch.setattr(svc_mod, "REPORT_MAX_PAGES", 2)
    service = GA4ReportingService(access_token="tok")
    page = _report_response([{"date": "20261001", "sessions": 5}], row_count=100)
    monkeypatch.setattr(service, "_post_report", lambda pid, body: page)

    rows, flags = service.run_report(
        "properties/1",
        dimensions=["date"],
        metrics=["sessions"],
        date_ranges=[{"startDate": "2026-09-25", "endDate": "2026-10-01"}],
    )
    assert flags["truncated"] is True
    assert len(rows) == 2


def test_run_report_surfaces_quality_metadata(monkeypatch) -> None:
    service = GA4ReportingService(access_token="tok")
    page = _report_response(
        [{"date": "20261001", "sessions": 5}],
        metadata={"dataLossFromOtherRow": True, "subjectToThresholding": True},
    )
    monkeypatch.setattr(service, "_post_report", lambda pid, body: page)
    _rows, flags = service.run_report(
        "properties/1",
        dimensions=["date"],
        metrics=["sessions"],
        date_ranges=[{"startDate": "2026-09-25", "endDate": "2026-10-01"}],
    )
    assert flags["data_loss_from_other_row"] is True
    assert flags["subject_to_thresholding"] is True


def _httpx_response(status: int, payload: dict | None = None):
    class _Resp:
        status_code = status
        content = b"x"

        def json(self):
            return payload or {}

    return _Resp()


def test_ga4_403_and_429_are_distinct(monkeypatch) -> None:
    import httpx
    import time

    statuses = iter([403, 429, 429, 429, 429])

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def request(self, *a, **k):
            return _httpx_response(next(statuses))

    monkeypatch.setattr(httpx, "Client", _Client)
    # Record the backoff instead of paying it: the 429 retries would otherwise
    # sleep 2 + 4 + 8 real seconds, and the schedule itself was unasserted.
    # The service does `import time` inside _get, so there is no module-level
    # namespace to patch; monkeypatch restores time.sleep after the test.
    sleeps: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(time, "sleep", _fake_sleep)
    service = GA4ReportingService(access_token="tok")
    with pytest.raises(GA4PermissionError):
        service._get("https://example.test/x")
    with pytest.raises(GA4RateLimitError):
        service._get("https://example.test/y")
    assert sleeps == [2.0, 4.0, 8.0]


# ---------------------------------------------------------------------------
# 6. idempotent sync (LLMTrafficSnapshot upsert does not duplicate)
# ---------------------------------------------------------------------------


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_sync_traffic_is_idempotent(db: Session, monkeypatch) -> None:
    from app.services.geo.ga4_traffic_service import GA4TrafficService

    user = models.User(email="idem@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="ws", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(workspace_id=workspace.id, name="p", language="en")
    db.add(project)
    db.commit()

    service = GA4TrafficService(access_token="tok")
    report = {
        "dimensionHeaders": [{"name": "sessionSource"}, {"name": "date"}],
        "metricHeaders": [
            {"name": "sessions"},
            {"name": "totalUsers"},
            {"name": "screenPageViews"},
            {"name": "averageSessionDuration"},
            {"name": "bounceRate"},
        ],
        "rows": [
            {
                "dimensionValues": [{"value": "chatgpt.com"}, {"value": "20261001"}],
                "metricValues": [
                    {"value": "10"},
                    {"value": "8"},
                    {"value": "12"},
                    {"value": "30"},
                    {"value": "0.5"},
                ],
            }
        ],
    }
    monkeypatch.setattr(service, "_call_ga4_api", lambda pid, body: report)

    assert service.sync_traffic(db, project.id, "properties/1") == 1
    assert service.sync_traffic(db, project.id, "properties/1") == 1
    rows = db.query(models.LLMTrafficSnapshot).all()
    assert len(rows) == 1
    assert rows[0].sessions == 10


def test_breakdown_rows_carry_the_current_value_not_only_the_change() -> None:
    """A new property has one period, so no change can be computed.

    This is the preprod case that produced the identical-tooltip report:
    project 19 is a fresh GA4 property, every `change.value` came back null,
    and a change-only row had nothing for the surface to render. With every
    row dropped on every card, five panels built to show five different
    things all fell back to the same "no breakdown" sentence.

    The value is always measurable even when the change is not, so each row
    carries both and the panel degrades to "Organic 7" rather than to silence.
    """
    # One period only: no date_range_1 rows anywhere.
    series_rows = [
        _series_row(
            "date_range_0",
            "20261001",
            11,
            screenPageViews=17,
            keyEvents=0,
            engagedSessions=7,
            averageSessionDuration=234.37,
        ),
    ]
    user_channel_rows = [
        {
            "dateRange": "date_range_0",
            "sessionDefaultChannelGroup": "Organic Search",
            "totalUsers": 3,
        },
    ]
    # One period of channel sessions, so the current value is measurable and
    # the change is not.
    channel_rows = [
        _channel_row("date_range_0", "Organic Search", "google", 11),
    ]
    payload = _payload(
        series_rows=series_rows,
        channel_rows=channel_rows,
        user_channel_rows=user_channel_rows,
    )
    breakdowns = payload["breakdowns"]

    # Every change is unavailable, exactly as on the real property.
    for rows in breakdowns.values():
        for row in rows:
            assert row["change"]["value"] is None, row

    # ... and yet every row still has something true to show.
    organic = next(r for r in breakdowns["sessions"] if r["bucket"] == "organic")
    assert organic["value"] == 11.0

    users_organic = next(r for r in breakdowns["users"] if r["bucket"] == "organic")
    assert users_organic["value"] == 3.0

    engagement = {r["metric"]: r for r in breakdowns["engagement"]}
    assert engagement["engaged_sessions"]["value"] == 7.0
    assert engagement["engaged_sessions"]["value_kind"] == "count"
    # Bounce rate is already scaled to 0-100 so the surface does not rescale.
    assert engagement["bounce_rate"]["value_kind"] == "percent"
    assert 0 <= engagement["bounce_rate"]["value"] <= 100
    assert engagement["avg_session_duration"]["value_kind"] == "seconds"
    assert engagement["avg_session_duration"]["value"] == 234.37
