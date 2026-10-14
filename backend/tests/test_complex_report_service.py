import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.services.reports.complex_report_service import build_monthly_performance_report


def _build_audit(created_at: datetime, seo: float, geo: float, aeo: float) -> models.Audit:
    audit = models.Audit(
        url="https://example.com",
        geo_score=geo,
        seo_score=seo,
        aeo_score=aeo,
        full_report={
            "scores": {
                "seo": seo,
                "geo": geo,
                "aeo": aeo,
            }
        },
    )
    audit.created_at = created_at
    return audit


def test_build_monthly_performance_report_returns_empty_for_empty_interval():
    audits = [
        _build_audit(datetime(2025, 1, 1), 60, 62, 59),
        _build_audit(datetime(2025, 1, 15), 70, 72, 69),
    ]

    result = build_monthly_performance_report(
        site_id=12,
        audits=audits,
        start_date=datetime(2025, 2, 1),
        end_date=datetime(2025, 2, 28),
    )

    assert result.audit_count == 0
    assert result.overall_avg == 0
    assert result.trend_direction == "stable"


def test_build_monthly_performance_report_uses_partial_interval_only():
    audits = [
        _build_audit(datetime(2025, 1, 1), 60, 62, 59),
        _build_audit(datetime(2025, 1, 15), 70, 72, 69),
        _build_audit(datetime(2025, 2, 2), 80, 83, 78),
    ]

    result = build_monthly_performance_report(
        site_id=12,
        audits=audits,
        start_date=datetime(2025, 1, 10),
        end_date=datetime(2025, 1, 31),
    )

    assert result.audit_count == 1
    assert result.seo_avg == 70
    assert result.geo_avg == 72
    assert result.aeo_avg == 69


def test_build_monthly_performance_report_trend_is_up_on_filtered_data():
    audits = [
        _build_audit(datetime(2025, 1, 1), 40, 40, 40),
        _build_audit(datetime(2025, 1, 10), 60, 60, 60),
        _build_audit(datetime(2025, 1, 20), 75, 75, 75),
    ]

    result = build_monthly_performance_report(
        site_id=12,
        audits=audits,
        start_date=datetime(2025, 1, 10),
        end_date=datetime(2025, 1, 20),
    )

    assert result.audit_count == 2
    assert result.trend_direction == "up"


def test_build_monthly_performance_report_trend_is_down_on_filtered_data():
    audits = [
        _build_audit(datetime(2025, 1, 1), 95, 92, 93),
        _build_audit(datetime(2025, 1, 10), 80, 79, 78),
        _build_audit(datetime(2025, 1, 20), 61, 60, 59),
    ]

    result = build_monthly_performance_report(
        site_id=12,
        audits=audits,
        start_date=datetime(2025, 1, 10),
        end_date=datetime(2025, 1, 20),
    )

    assert result.audit_count == 2
    assert result.trend_direction == "down"


def test_build_monthly_performance_report_trend_is_stable_on_filtered_data():
    audits = [
        _build_audit(datetime(2025, 1, 1), 50, 50, 50),
        _build_audit(datetime(2025, 1, 10), 60, 60, 60),
        _build_audit(datetime(2025, 1, 20), 60.5, 60, 60),
    ]

    result = build_monthly_performance_report(
        site_id=12,
        audits=audits,
        start_date=datetime(2025, 1, 10),
        end_date=datetime(2025, 1, 20),
    )

    assert result.audit_count == 2
    assert result.trend_direction == "stable"
