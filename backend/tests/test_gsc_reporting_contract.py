"""SIGV2-1025: Search Console reporting contract tests.

Expected values are hand-calculated in comments. See
docs/search-console-reporting-contract.md.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from app.services.gsc_reporting_service import (
    GSCPermissionError,
    GSCRateLimitError,
    GSCReportingService,
    aggregate_pages,
    build_daily_series,
    build_pages_payload,
    classify_opportunity,
    normalize_page_key,
    recompute_ctr,
    sync_search_analytics,
    weighted_position,
)


# ---------------------------------------------------------------------------
# Section 2: weighted position and recomputed CTR
# ---------------------------------------------------------------------------


def test_position_is_impression_weighted_not_mean() -> None:
    # Hand calc: (10*1000 + 50*10) / 1010 = 10500/1010 = 10.3960...
    # Plain mean of (10, 50) = 30.0 - visibly wrong.
    rows = [
        {"position": 10.0, "impressions": 1000.0},
        {"position": 50.0, "impressions": 10.0},
    ]
    assert weighted_position(rows) == pytest.approx(10500.0 / 1010.0, rel=1e-6)
    assert weighted_position(rows) != pytest.approx(30.0)


def test_ctr_recomputed_not_averaged() -> None:
    # Rows: (clicks=90, imp=100) ctr 0.9 ; (clicks=1, imp=1000) ctr 0.001
    # Recomputed: 91/1100 = 0.082727...  Averaged ctr: 0.4505 - wrong.
    assert recompute_ctr(91, 1100) == pytest.approx(91.0 / 1100.0, rel=1e-6)


def test_zero_impressions_gives_null_ctr_and_position() -> None:
    assert recompute_ctr(0, 0) is None
    assert weighted_position([{"position": 0.0, "impressions": 0.0}]) is None


# ---------------------------------------------------------------------------
# URL normalization (section 6.1)
# ---------------------------------------------------------------------------


def test_normalize_page_key() -> None:
    assert normalize_page_key("https://www.example.com/Path/?a=1#x") == "/path/"
    assert normalize_page_key("https://www.example.com") == "/"
    assert normalize_page_key("/Blog%20Post/?q=2") == "/blog post/"
    assert normalize_page_key("sc-domain:example.com") == "/"
    assert normalize_page_key("https://example.com/A%20B") == "/a b"


# ---------------------------------------------------------------------------
# Pages aggregation + GA4 join (sections 6-7)
# ---------------------------------------------------------------------------

# Fixture (min_impressions=50):
#   /a    : two GSC URLs collapsing to one key:
#           "https://ex.com/A"       clicks 10, imp 400, pos 5
#           "https://ex.com/A?utm=1" clicks 5,  imp 100, pos 15
#           -> clicks 15, imp 500, weighted pos = (5*400 + 15*100)/500 = 7.0
#           -> collapsed_count 1
#   /b    : "https://ex.com/b"    clicks 60, imp 1000, pos 2
#   /c    : "https://ex.com/c"    clicks 0,  imp 20,  pos 8   -> below min imp
# GA4 sessions: /a -> 300, /b -> 700; /c absent -> unavailable
GSC_ROWS = [
    {
        "page": "https://ex.com/A",
        "date": "2026-10-01",
        "clicks": 10,
        "impressions": 400,
        "position": 5.0,
    },
    {
        "page": "https://ex.com/A?utm=1",
        "date": "2026-10-01",
        "clicks": 5,
        "impressions": 100,
        "position": 15.0,
    },
    {
        "page": "https://ex.com/b",
        "date": "2026-10-01",
        "clicks": 60,
        "impressions": 1000,
        "position": 2.0,
    },
    {
        "page": "https://ex.com/c",
        "date": "2026-10-01",
        "clicks": 0,
        "impressions": 20,
        "position": 8.0,
    },
]
GA4_SESSIONS = {"/a": 300.0, "/b": 700.0}


def test_pages_aggregate_and_collapse_count() -> None:
    pages = {p["page_key"]: p for p in aggregate_pages(GSC_ROWS, GA4_SESSIONS, min_impressions=50)}
    a = pages["/a"]
    assert a["clicks"] == 15
    assert a["impressions"] == 500
    assert a["avg_position"] == pytest.approx(7.0)
    assert a["collapsed_count"] == 1
    assert a["pages"] == ["https://ex.com/A", "https://ex.com/A?utm=1"]
    assert a["sessions"] == 300.0


def test_gsc_page_without_ga4_match_reports_sessions_unavailable() -> None:
    pages = {p["page_key"]: p for p in aggregate_pages(GSC_ROWS, GA4_SESSIONS, min_impressions=50)}
    assert pages["/c"]["sessions"] is None
    assert pages["/c"]["sessions_reason"] == "no_ga4_match"


def test_no_ga4_binding_reports_unavailable_never_clicks() -> None:
    pages = aggregate_pages(GSC_ROWS, None, min_impressions=50)
    for p in pages:
        assert p["sessions"] is None
        assert p["sessions_reason"] == "no_ga4_binding"


# ---------------------------------------------------------------------------
# Opportunity (section 7): all four values with evidence
# ---------------------------------------------------------------------------


def _page(position, impressions, ctr, incomplete=False):
    return {
        "avg_position": position,
        "impressions": impressions,
        "ctr": ctr,
        "incomplete": incomplete,
    }


def test_opportunity_striking_distance() -> None:
    result = classify_opportunity(_page(7.0, 500, 0.05), band_median_ctr=None, min_impressions=50)
    assert result["value"] == "striking_distance"
    assert result["evidence"]["weighted_position"] == 7.0
    assert result["evidence"]["min_impressions"] == 50


def test_opportunity_low_ctr() -> None:
    result = classify_opportunity(_page(2.0, 500, 0.02), band_median_ctr=0.05, min_impressions=50)
    assert result["value"] == "low_ctr"
    assert result["evidence"]["band_median_ctr"] == 0.05


def test_opportunity_none_vs_insufficient_data() -> None:
    # none: looked, nothing there (impressions >= min, no rule matched).
    none_result = classify_opportunity(
        _page(2.0, 500, 0.10), band_median_ctr=0.05, min_impressions=50
    )
    assert none_result["value"] == "none"
    # insufficient_data: below the min impressions.
    ins_result = classify_opportunity(
        _page(2.0, 20, 0.10), band_median_ctr=0.05, min_impressions=50
    )
    assert ins_result["value"] == "insufficient_data"
    # ... and an incomplete row is insufficient_data even with plenty of impressions.
    inc_result = classify_opportunity(
        _page(7.0, 500, 0.05, incomplete=True), band_median_ctr=None, min_impressions=50
    )
    assert inc_result["value"] == "insufficient_data"
    assert inc_result["evidence"]["incomplete"] is True


def test_opportunity_uses_property_band_median() -> None:
    # Two top-3 pages: ctrs 0.02 and 0.10 -> median 0.06. The 0.02 page is low_ctr.
    pages = aggregate_pages(
        [
            {
                "page": "https://ex.com/p1",
                "date": "2026-10-01",
                "clicks": 20,
                "impressions": 1000,
                "position": 2.0,
            },
            {
                "page": "https://ex.com/p2",
                "date": "2026-10-01",
                "clicks": 100,
                "impressions": 1000,
                "position": 2.0,
            },
        ],
        {},
        min_impressions=50,
    )
    by_key = {p["page_key"]: p for p in pages}
    # median of [0.02, 0.10] = 0.06
    assert by_key["/p1"]["opportunity"]["value"] == "low_ctr"
    assert by_key["/p1"]["opportunity"]["evidence"]["band_median_ctr"] == pytest.approx(0.06)
    assert by_key["/p2"]["opportunity"]["value"] == "none"


# ---------------------------------------------------------------------------
# Daily series: gaps are unavailable, not zero (section 3.2)
# ---------------------------------------------------------------------------


def test_daily_series_gap_is_unavailable_not_zero() -> None:
    start, end = date(2026, 9, 29), date(2026, 10, 1)
    rows = [
        {"date": "2026-09-29", "clicks": 5, "impressions": 100, "position": 10.0},
        {"date": "2026-10-01", "clicks": 7, "impressions": 200, "position": 8.0},
    ]
    series = {s["date"]: s for s in build_daily_series(rows, start, end)}
    assert series["2026-09-30"] == {"date": "2026-09-30", "available": False}
    assert series["2026-09-29"]["available"] is True
    assert series["2026-09-29"]["clicks"] == 5


# ---------------------------------------------------------------------------
# Payload: date-basis disclosure (section 3)
# ---------------------------------------------------------------------------


def _payload(ga4_tz, sessions=None):
    return build_pages_payload(
        site_url="https://ex.com/",
        window_key="7D",
        start=date(2026, 9, 25),
        end=date(2026, 10, 1),
        page_rows=GSC_ROWS,
        ga4_sessions_by_key=sessions,
        ga4_property_timezone=ga4_tz,
        min_impressions=50,
        query_meta={"completeness": "full"},
        data_state="all",
    )


def test_date_alignment_exact_only_for_los_angeles() -> None:
    assert _payload("America/Los_Angeles")["date_alignment"] == "exact"
    approx = _payload("Europe/Bucharest")
    assert approx["date_alignment"] == "approximate"
    assert approx["date_basis"] == "America/Los_Angeles"
    assert approx["ga4_property_timezone"] == "Europe/Bucharest"
    # No GA4 binding at all is also approximate, never silently exact.
    assert _payload(None)["date_alignment"] == "approximate"


def test_totals_recomputed() -> None:
    payload = _payload("UTC")
    # clicks 75, impressions 1520 -> ctr 75/1520 = 0.04934
    assert payload["totals"]["clicks"] == 75
    assert payload["totals"]["impressions"] == 1520
    assert payload["totals"]["ctr"] == pytest.approx(75.0 / 1520.0, rel=1e-6)


# ---------------------------------------------------------------------------
# query_search_analytics: encoding, pagination, ceiling, incomplete flag
# ---------------------------------------------------------------------------


def _gsc_page(rows, meta=None):
    return {
        "rows": [
            {
                "keys": r["keys"],
                "clicks": r.get("clicks", 0),
                "impressions": r.get("impressions", 0),
                "ctr": r.get("ctr", 0.0),
                "position": r.get("position", 0.0),
            }
            for r in rows
        ],
        "responseAggregationType": "auto",
        "metadata": meta or {},
    }


def test_property_forms_url_encoded_into_path(monkeypatch) -> None:
    service = GSCReportingService(access_token="tok")
    urls: list[str] = []
    monkeypatch.setattr(service, "_post", lambda url, body: urls.append(url) or _gsc_page([]))
    for site in ("https://www.example.com/", "sc-domain:example.com"):
        service.query_search_analytics(
            site,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 7),
            dimensions=["page"],
        )
    assert "https%3A%2F%2Fwww.example.com%2F" in urls[0]
    assert "sc-domain%3Aexample.com" in urls[1]


def test_paginates_across_pages_and_marks_ceiling_partial(monkeypatch) -> None:
    service = GSCReportingService(access_token="tok")
    calls: list[int] = []

    def fake_post(url, body):
        calls.append(body["startRow"])
        # Always a full page so pagination only stops at the ceiling.
        return _gsc_page(
            [{"keys": ["https://ex.com/p"], "impressions": 1} for _ in range(body["rowLimit"])]
        )

    monkeypatch.setattr(service, "_post", fake_post)
    rows, meta = service.query_search_analytics(
        "https://ex.com/",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 7),
        dimensions=["page"],
        row_limit=100,
        row_ceiling=250,
    )
    assert calls == [0, 100, 200]
    assert meta["completeness"] == "partial"
    assert meta["partial_reason"] == "row_ceiling_reached"
    assert len(rows) == 250


def test_first_incomplete_date_flags_rows(monkeypatch) -> None:
    service = GSCReportingService(access_token="tok")
    page = _gsc_page(
        [
            {"keys": ["https://ex.com/a", "2026-09-28"], "impressions": 10},
            {"keys": ["https://ex.com/a", "2026-09-30"], "impressions": 10},
            {"keys": ["https://ex.com/a", "2026-10-01"], "impressions": 10},
        ],
        meta={"first_incomplete_date": "2026-09-30"},
    )
    monkeypatch.setattr(service, "_post", lambda url, body: page)
    rows, meta = service.query_search_analytics(
        "https://ex.com/",
        start_date=date(2026, 9, 25),
        end_date=date(2026, 10, 1),
        dimensions=["page", "date"],
        data_state="all",
    )
    assert meta["first_incomplete_date"] == "2026-09-30"
    by_date = {r["date"]: r.get("_incomplete", False) for r in rows}
    assert by_date == {"2026-09-28": False, "2026-09-30": True, "2026-10-01": True}


def test_403_and_429_map_to_distinct_errors(monkeypatch) -> None:
    import httpx
    import types

    import app.services.gsc_reporting_service as gsc_service_module

    statuses = iter([403, 429, 429, 429, 429])

    class _Resp:
        def __init__(self, status):
            self.status_code = status

        def json(self):
            return {}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp(next(statuses))

    monkeypatch.setattr(httpx, "Client", _Client)
    # Record the backoff instead of paying it: the 429 retries would otherwise
    # sleep 2 + 4 + 8 real seconds, and the schedule itself was unasserted.
    # Patched on the service module's `time` namespace only, so the real
    # time.sleep elsewhere is untouched.
    sleeps: list[float] = []

    def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(gsc_service_module, "time", types.SimpleNamespace(sleep=_fake_sleep))
    service = GSCReportingService(access_token="tok")
    with pytest.raises(GSCPermissionError):
        service._post("https://x.test/", {})
    with pytest.raises(GSCRateLimitError):
        service._post("https://x.test/", {})
    assert sleeps == [2.0, 4.0, 8.0]


# ---------------------------------------------------------------------------
# Ingestion idempotency (section 8)
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


def test_sync_is_idempotent_no_duplicate_rows(db: Session) -> None:
    user = models.User(email="gsc@example.com", hashed_password="x")
    db.add(user)
    db.flush()
    ws = models.Workspace(name="ws", owner_id=user.id)
    db.add(ws)
    db.flush()
    project = models.Project(workspace_id=ws.id, name="p", language="en")
    db.add(project)
    db.commit()

    rows = [
        {
            "page": "https://ex.com/a",
            "date": "2026-10-01",
            "clicks": 5,
            "impressions": 100,
            "position": 8.0,
        },
    ]
    assert sync_search_analytics(db, project.id, "https://ex.com/", rows) == 1
    # Second run with updated metrics updates in place.
    rows[0]["clicks"] = 9
    assert sync_search_analytics(db, project.id, "https://ex.com/", rows) == 1
    stored = db.query(models.ProjectGSCPageMetric).all()
    assert len(stored) == 1
    assert stored[0].clicks == 9
