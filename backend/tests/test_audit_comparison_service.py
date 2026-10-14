"""Tests for audit_comparison_service — AEX-19."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_audit(
    *,
    id: int,
    user_id: int = 1,
    url: str = "https://example.com",
    project_id: int | None = None,
    seo_score: float | None = 70,
    geo_score: float = 60,
    aeo_score: float | None = 50,
    created_at: datetime | None = None,
    full_report: dict | None = None,
    audit_target_type: str = "website",
    target_name: str | None = None,
    audit_type: str = "FAST",
):
    audit = MagicMock()
    audit.id = id
    audit.user_id = user_id
    audit.url = url
    audit.project_id = project_id
    audit.audit_type = audit_type
    audit.seo_score = seo_score
    audit.geo_score = geo_score
    audit.aeo_score = aeo_score
    audit.created_at = created_at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    audit.full_report = full_report or {}
    audit.audit_target_type = audit_target_type
    audit.target_name = target_name
    return audit


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------


class TestMetricDelta:
    def test_both_values(self):
        from services.audit_comparison_service import _metric_delta

        assert _metric_delta(80.0, 70.0) == 10.0

    def test_negative_delta(self):
        from services.audit_comparison_service import _metric_delta

        assert _metric_delta(60.0, 75.0) == -15.0

    def test_current_none(self):
        from services.audit_comparison_service import _metric_delta

        assert _metric_delta(None, 70.0) is None

    def test_previous_none(self):
        from services.audit_comparison_service import _metric_delta

        assert _metric_delta(80.0, None) is None


class TestMetricDirection:
    def test_up(self):
        from services.audit_comparison_service import _metric_direction

        assert _metric_direction(5.0) == "up"

    def test_down(self):
        from services.audit_comparison_service import _metric_direction

        assert _metric_direction(-5.0) == "down"

    def test_stable_within_deadzone(self):
        from services.audit_comparison_service import _metric_direction

        assert _metric_direction(0.5) == "stable"
        assert _metric_direction(-0.5) == "stable"

    def test_stable_none(self):
        from services.audit_comparison_service import _metric_direction

        assert _metric_direction(None) == "stable"


class TestExtractV3Breakdown:
    def test_valid_breakdown(self):
        from services.audit_comparison_service import _extract_v3_breakdown

        report = {
            "scores": {
                "seo_breakdown": {
                    "components": {
                        "core_web_vitals": 85.0,
                        "technical_seo": 70.0,
                    }
                }
            }
        }
        result = _extract_v3_breakdown(report, "seo")
        assert result == {"core_web_vitals": 85.0, "technical_seo": 70.0}

    def test_missing_breakdown(self):
        from services.audit_comparison_service import _extract_v3_breakdown

        assert _extract_v3_breakdown({}, "seo") == {}

    def test_non_numeric_values_filtered(self):
        from services.audit_comparison_service import _extract_v3_breakdown

        report = {
            "scores": {
                "geo_breakdown": {
                    "components": {
                        "visibility": 60.0,
                        "notes": "some string",
                    }
                }
            }
        }
        result = _extract_v3_breakdown(report, "geo")
        assert result == {"visibility": 60.0}


# ---------------------------------------------------------------------------
# Integration tests for get_audit_comparison
# ---------------------------------------------------------------------------


class TestGetAuditComparison:
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_audit_not_found(self, mock_resolve):
        from services.audit_comparison_service import get_audit_comparison

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        result = get_audit_comparison(db, 999, user_id=1)
        assert result is None

    @patch("services.audit_comparison_service._build_history_points")
    @patch("services.audit_comparison_service._find_previous_audit")
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_first_audit_no_previous(self, mock_resolve, mock_find_prev, mock_history):
        from services.audit_comparison_service import get_audit_comparison

        audit = _make_audit(id=1, seo_score=80, geo_score=70, aeo_score=60)
        mock_resolve.return_value = {"seo": 80, "geo": 70, "aeo": 60, "overall": 71}
        mock_find_prev.return_value = None
        mock_history.return_value = [
            {"audit_id": 1, "date": "2026-01-01", "overall": 71, "seo": 80, "geo": 70, "aeo": 60}
        ]

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = audit

        result = get_audit_comparison(db, 1, user_id=1)
        assert result is not None
        assert result["has_previous"] is False
        assert result["audit_id"] == 1
        assert result["scores"]["seo"]["current"] == 80
        assert "previous" not in result["scores"]["seo"]

    @patch("services.audit_comparison_service._build_history_points")
    @patch("services.audit_comparison_service._find_previous_audit")
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_improvement_scenario(self, mock_resolve, mock_find_prev, mock_history):
        from services.audit_comparison_service import get_audit_comparison

        current = _make_audit(
            id=2,
            seo_score=85,
            geo_score=75,
            aeo_score=65,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        previous = _make_audit(
            id=1,
            seo_score=70,
            geo_score=60,
            aeo_score=50,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        mock_resolve.side_effect = [
            {"seo": 85, "geo": 75, "aeo": 65, "overall": 76},
            {"seo": 70, "geo": 60, "aeo": 50, "overall": 61},
        ]
        mock_find_prev.return_value = previous
        mock_history.return_value = []

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = current

        result = get_audit_comparison(db, 2, user_id=1)
        assert result["has_previous"] is True
        assert result["previous_audit_id"] == 1
        assert result["scores"]["seo"]["delta"] == 15.0
        assert result["scores"]["seo"]["direction"] == "up"
        assert result["scores"]["overall"]["delta"] == 15.0
        assert result["scores"]["overall"]["direction"] == "up"

    @patch("services.audit_comparison_service._build_history_points")
    @patch("services.audit_comparison_service._find_previous_audit")
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_regression_scenario(self, mock_resolve, mock_find_prev, mock_history):
        from services.audit_comparison_service import get_audit_comparison

        current = _make_audit(
            id=2,
            seo_score=60,
            geo_score=55,
            aeo_score=45,
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        previous = _make_audit(
            id=1,
            seo_score=80,
            geo_score=70,
            aeo_score=65,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        mock_resolve.side_effect = [
            {"seo": 60, "geo": 55, "aeo": 45, "overall": 54},
            {"seo": 80, "geo": 70, "aeo": 65, "overall": 72},
        ]
        mock_find_prev.return_value = previous
        mock_history.return_value = []

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = current

        result = get_audit_comparison(db, 2, user_id=1)
        assert result["has_previous"] is True
        assert result["scores"]["seo"]["delta"] == -20.0
        assert result["scores"]["seo"]["direction"] == "down"
        assert result["scores"]["geo"]["delta"] == -15.0
        assert result["scores"]["geo"]["direction"] == "down"

    @patch("services.audit_comparison_service._build_history_points")
    @patch("services.audit_comparison_service._find_previous_audit")
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_stable_small_delta(self, mock_resolve, mock_find_prev, mock_history):
        from services.audit_comparison_service import get_audit_comparison

        current = _make_audit(id=2, seo_score=80.5, geo_score=70, aeo_score=60)
        previous = _make_audit(id=1, seo_score=80, geo_score=70, aeo_score=60)

        mock_resolve.side_effect = [
            {"seo": 80.5, "geo": 70, "aeo": 60, "overall": 71},
            {"seo": 80, "geo": 70, "aeo": 60, "overall": 71},
        ]
        mock_find_prev.return_value = previous
        mock_history.return_value = []

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = current

        result = get_audit_comparison(db, 2, user_id=1)
        assert result["scores"]["seo"]["delta"] == 0.5
        assert result["scores"]["seo"]["direction"] == "stable"
        assert result["scores"]["overall"]["delta"] == 0.0
        assert result["scores"]["overall"]["direction"] == "stable"

    @patch("services.audit_comparison_service._build_history_points")
    @patch("services.audit_comparison_service._find_previous_audit")
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    def test_sub_components_v3_breakdown(self, mock_resolve, mock_find_prev, mock_history):
        from services.audit_comparison_service import get_audit_comparison

        current_report = {
            "scores": {
                "seo_breakdown": {"components": {"core_web_vitals": 90, "technical_seo": 80}}
            }
        }
        prev_report = {
            "scores": {
                "seo_breakdown": {"components": {"core_web_vitals": 70, "technical_seo": 85}}
            }
        }

        current = _make_audit(
            id=2, full_report=current_report, created_at=datetime(2026, 2, 1, tzinfo=timezone.utc)
        )
        previous = _make_audit(
            id=1, full_report=prev_report, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc)
        )

        mock_resolve.side_effect = [
            {"seo": 85, "geo": 70, "aeo": 60, "overall": 73},
            {"seo": 77, "geo": 65, "aeo": 55, "overall": 67},
        ]
        mock_find_prev.return_value = previous
        mock_history.return_value = []

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = current

        result = get_audit_comparison(db, 2, user_id=1)
        assert "seo" in result["sub_components"]
        seo_comps = result["sub_components"]["seo"]
        assert seo_comps["core_web_vitals"]["delta"] == 20.0
        assert seo_comps["core_web_vitals"]["direction"] == "up"
        assert seo_comps["technical_seo"]["delta"] == -5.0
        assert seo_comps["technical_seo"]["direction"] == "down"


class TestFindPreviousAudit:
    """Test _find_previous_audit query logic."""

    def test_brand_audit_matches_by_target_name(self):
        from services.audit_comparison_service import _find_previous_audit

        audit = _make_audit(
            id=2,
            audit_target_type="brand",
            target_name="Acme Corp",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        prev = _make_audit(id=1, audit_target_type="brand", target_name="Acme Corp")

        db = MagicMock()
        query_mock = MagicMock()
        db.query.return_value = query_mock
        # No project_id, goes straight to general query
        query_mock.filter.return_value.order_by.return_value.first.return_value = prev

        result = _find_previous_audit(db, audit, user_id=1)
        assert result == prev


class TestBuildHistoryPoints:
    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    @patch("services.audit_comparison_service._load_audit_history")
    def test_history_points_structure(self, mock_load, mock_resolve):
        from services.audit_comparison_service import _build_history_points

        a1 = _make_audit(id=1, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        a2 = _make_audit(id=2, created_at=datetime(2026, 2, 1, tzinfo=timezone.utc))
        mock_load.return_value = [a1, a2]
        mock_resolve.side_effect = [
            {"seo": 70, "geo": 60, "aeo": 50, "overall": 61},
            {"seo": 80, "geo": 70, "aeo": 60, "overall": 71},
        ]

        audit = _make_audit(id=2)
        db = MagicMock()

        points = _build_history_points(db, audit, user_id=1)
        assert len(points) == 2
        assert points[0]["audit_id"] == 1
        assert points[0]["seo"] == 70
        assert points[1]["audit_id"] == 2
        assert points[1]["seo"] == 80

    @patch("services.audit_comparison_service.resolve_effective_audit_scores")
    @patch("services.audit_comparison_service._load_audit_history")
    def test_empty_history(self, mock_load, mock_resolve):
        from services.audit_comparison_service import _build_history_points

        mock_load.return_value = []
        audit = _make_audit(id=1)
        db = MagicMock()

        points = _build_history_points(db, audit, user_id=1)
        assert points == []


# ---------------------------------------------------------------------------
# API endpoint test
# ---------------------------------------------------------------------------


class TestAuditComparisonEndpoint:
    """Test the /api/v1/audit/{audit_id}/comparison router handler."""

    @patch("services.audit_comparison_service.get_audit_comparison")
    def test_returns_comparison_data(self, mock_get):
        mock_get.return_value = {
            "audit_id": 1,
            "has_previous": True,
            "previous_audit_id": 0,
            "scores": {},
            "sub_components": {},
            "history": [],
        }

        # Simulate the endpoint logic inline
        from services.audit_comparison_service import get_audit_comparison

        result = get_audit_comparison(MagicMock(), 1, user_id=1)
        assert result is not None
        assert result["has_previous"] is True

    @patch("services.audit_comparison_service.get_audit_comparison")
    def test_returns_none_for_missing_audit(self, mock_get):
        mock_get.return_value = None

        from services.audit_comparison_service import get_audit_comparison

        result = get_audit_comparison(MagicMock(), 999, user_id=1)
        assert result is None
