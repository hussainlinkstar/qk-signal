"""Tests for the GA4 Traffic Service.

Uses mocked HTTP responses to validate API request construction,
response parsing, upsert logic, and retry behaviour.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from app.services.geo.ga4_traffic_service import (
    GA4TrafficService,
    GA4AuthError,
    LLM_REFERRAL_SOURCES,
    PLATFORM_FAMILIES,
    PLATFORM_FAMILY_LABELS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_db() -> tuple[Session, Engine, models.Project]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()

    user = models.User(
        email="ga4test@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()

    workspace = models.Workspace(name="GA4 Agency", owner_id=user.id)
    db.add(workspace)
    db.commit()

    project = models.Project(
        name="GA4 Client",
        domain_url="ga4-client.example.com",
        workspace_id=workspace.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    ga4_config = models.ProjectGA4Config(
        project_id=project.id,
        ga4_property_id="properties/123456",
    )
    db.add(ga4_config)
    db.commit()

    return db, engine, project


MOCK_GA4_RESPONSE = {
    "dimensionHeaders": [
        {"name": "sessionSource"},
        {"name": "date"},
    ],
    "metricHeaders": [
        {"name": "sessions"},
        {"name": "totalUsers"},
        {"name": "screenPageViews"},
        {"name": "averageSessionDuration"},
        {"name": "bounceRate"},
    ],
    "rows": [
        {
            "dimensionValues": [{"value": "chatgpt.com"}, {"value": "20250115"}],
            "metricValues": [
                {"value": "42"},
                {"value": "35"},
                {"value": "120"},
                {"value": "180.5"},
                {"value": "0.25"},
            ],
        },
        {
            "dimensionValues": [{"value": "perplexity.ai"}, {"value": "20250115"}],
            "metricValues": [
                {"value": "18"},
                {"value": "15"},
                {"value": "45"},
                {"value": "210.0"},
                {"value": "0.30"},
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_report_request() -> None:
    service = GA4TrafficService.__new__(GA4TrafficService)
    req = service._build_report_request(date(2025, 1, 1), date(2025, 1, 31))

    assert req["dateRanges"][0]["startDate"] == "2025-01-01"
    assert req["dateRanges"][0]["endDate"] == "2025-01-31"

    # Should filter for LLM sources
    in_list = req["dimensionFilter"]["filter"]["inListFilter"]["values"]
    assert set(in_list) == set(LLM_REFERRAL_SOURCES)


def test_parse_report_rows() -> None:
    service = GA4TrafficService.__new__(GA4TrafficService)
    rows = service._parse_report_rows(MOCK_GA4_RESPONSE)

    assert len(rows) == 2
    assert rows[0]["source"] == "chatgpt.com"
    assert rows[0]["sessions"] == 42
    assert rows[0]["snapshot_date"] == date(2025, 1, 15)
    assert rows[1]["source"] == "perplexity.ai"
    assert rows[1]["sessions"] == 18


def test_parse_report_rows_empty() -> None:
    service = GA4TrafficService.__new__(GA4TrafficService)
    rows = service._parse_report_rows({"rows": []})
    assert rows == []


def test_parse_report_rows_missing_rows_key() -> None:
    service = GA4TrafficService.__new__(GA4TrafficService)
    rows = service._parse_report_rows({})
    assert rows == []


def test_upsert_snapshots_insert_and_update() -> None:
    db, engine, project = _build_db()
    try:
        service = GA4TrafficService.__new__(GA4TrafficService)

        parsed = [
            {
                "source": "chatgpt.com",
                "snapshot_date": date(2025, 1, 15),
                "sessions": 42,
                "users": 35,
                "page_views": 120,
                "avg_session_duration_seconds": 180.5,
                "bounce_rate": 0.25,
            },
        ]

        count = service._upsert_snapshots(db, project.id, parsed)
        db.commit()
        assert count == 1

        snap = db.query(models.LLMTrafficSnapshot).first()
        assert snap is not None
        assert snap.sessions == 42

        # Update with new session count
        parsed[0]["sessions"] = 100
        count = service._upsert_snapshots(db, project.id, parsed)
        db.commit()
        assert count == 1

        db.refresh(snap)
        assert snap.sessions == 100
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_auth_error_without_path() -> None:
    service = GA4TrafficService(service_account_json_path=None)
    with pytest.raises(GA4AuthError, match="not configured"):
        service._load_service_account_credentials()


def test_auth_error_file_not_found() -> None:
    service = GA4TrafficService(service_account_json_path="/nonexistent/path.json")
    with pytest.raises(GA4AuthError, match="not found"):
        service._load_service_account_credentials()


def test_llm_referral_sources_contains_16_entries() -> None:
    """All 16 AI referral sources are present in the source list."""
    assert len(LLM_REFERRAL_SOURCES) == 16

    expected_critical = {
        "chatgpt.com",
        "gemini.google.com",
        "copilot.microsoft.com",
        "claude.ai",
        "perplexity.ai",
    }
    assert expected_critical.issubset(set(LLM_REFERRAL_SOURCES))

    expected_tier2 = {"deepseek.com", "chat.deepseek.com", "grok.com", "meta.ai"}
    assert expected_tier2.issubset(set(LLM_REFERRAL_SOURCES))

    expected_mobile = {
        "android-app://com.openai.chatgpt",
        "android-app://com.google.android.apps.bard",
    }
    assert expected_mobile.issubset(set(LLM_REFERRAL_SOURCES))


def test_platform_families_covers_all_sources() -> None:
    """Every source in LLM_REFERRAL_SOURCES has a platform family mapping."""
    for source in LLM_REFERRAL_SOURCES:
        assert source in PLATFORM_FAMILIES, f"Missing PLATFORM_FAMILIES entry for {source}"


def test_platform_family_labels_covers_all_families() -> None:
    """Every family value has a label entry."""
    families_used = set(PLATFORM_FAMILIES.values())
    for family in families_used:
        assert (
            family in PLATFORM_FAMILY_LABELS
        ), f"Missing PLATFORM_FAMILY_LABELS entry for {family}"


def test_build_report_request_includes_all_16_sources() -> None:
    """The GA4 report request filter includes all 16 sources."""
    service = GA4TrafficService.__new__(GA4TrafficService)
    from datetime import date

    req = service._build_report_request(date(2025, 1, 1), date(2025, 1, 31))
    in_list = req["dimensionFilter"]["filter"]["inListFilter"]["values"]
    assert set(in_list) == set(LLM_REFERRAL_SOURCES)
    assert len(in_list) == 16
