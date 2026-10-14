"""Tests for the GET /admin/metrics/timeseries endpoint helpers."""

import sys
from datetime import date
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[1]))

from admin import (
    _build_daily_series,
    _compute_summary,
    VALID_PERIODS,
    VALID_METRICS,
)


# ── _build_daily_series ─────────────────────────────────────────


def test_build_daily_series_fills_gaps() -> None:
    """Days with no data should be zero-filled."""
    start = date(2026, 3, 1)
    end = date(2026, 3, 5)
    rows = [
        (date(2026, 3, 1), 5),
        (date(2026, 3, 3), 10),
        (date(2026, 3, 5), 7),
    ]
    result = _build_daily_series(rows, start, end)

    assert len(result) == 5
    assert result[0] == {"date": "2026-03-01", "value": 5.0}
    assert result[1] == {"date": "2026-03-02", "value": 0.0}
    assert result[2] == {"date": "2026-03-03", "value": 10.0}
    assert result[3] == {"date": "2026-03-04", "value": 0.0}
    assert result[4] == {"date": "2026-03-05", "value": 7.0}


def test_build_daily_series_empty_rows() -> None:
    start = date(2026, 3, 1)
    end = date(2026, 3, 3)
    result = _build_daily_series([], start, end)

    assert len(result) == 3
    assert all(p["value"] == 0.0 for p in result)


def test_build_daily_series_single_day() -> None:
    d = date(2026, 3, 1)
    rows = [(d, 42)]
    result = _build_daily_series(rows, d, d)

    assert len(result) == 1
    assert result[0] == {"date": "2026-03-01", "value": 42.0}


# ── _compute_summary ────────────────────────────────────────────


def test_compute_summary_positive_growth() -> None:
    result = _compute_summary(150.0, 100.0)
    assert result["current"] == 150.0
    assert result["previous_period"] == 100.0
    assert result["change_pct"] == 50.0


def test_compute_summary_negative_growth() -> None:
    result = _compute_summary(80.0, 100.0)
    assert result["change_pct"] == -20.0


def test_compute_summary_zero_previous() -> None:
    result = _compute_summary(50.0, 0.0)
    assert result["change_pct"] == 100.0


def test_compute_summary_both_zero() -> None:
    result = _compute_summary(0.0, 0.0)
    assert result["change_pct"] is None


# ── Constants validation ────────────────────────────────────────


def test_valid_periods_includes_expected_keys() -> None:
    assert "7d" in VALID_PERIODS
    assert "30d" in VALID_PERIODS
    assert "90d" in VALID_PERIODS
    assert "365d" in VALID_PERIODS


def test_valid_metrics_includes_expected() -> None:
    assert "audits" in VALID_METRICS
    assert "emails" in VALID_METRICS
    assert "cost" in VALID_METRICS
