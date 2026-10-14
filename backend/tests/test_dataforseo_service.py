"""Tests for the DataForSEO SERP Tracking Service.

Uses mocked HTTP responses to validate task posting, SERP parsing
(Featured Snippet & PAA detection), and error handling.
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
from app.services.aeo.dataforseo_service import (
    DataForSEOService,
    DataForSEOAuthError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_db() -> tuple[Session, Engine, models.Project, models.TargetKeyword]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()

    user = models.User(
        email="serp-test@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()

    workspace = models.Workspace(name="SERP Agency", owner_id=user.id)
    db.add(workspace)
    db.commit()

    project = models.Project(
        name="SERP Client",
        domain_url="example.com",
        workspace_id=workspace.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    keyword = models.TargetKeyword(
        project_id=project.id,
        keyword="best seo tools 2025",
        language_code="en",
    )
    db.add(keyword)
    db.commit()
    db.refresh(keyword)

    return db, engine, project, keyword


MOCK_SERP_RESULT = {
    "result": [
        {
            "items": [
                {
                    "type": "featured_snippet",
                    "url": "https://example.com/best-seo-tools",
                    "title": "Best SEO Tools in 2025",
                    "description": "Here are the top 10 SEO tools you should be using...",
                },
                {
                    "type": "people_also_ask",
                    "items": [
                        {
                            "title": "What is the best free SEO tool?",
                            "url": "https://example.com/free-seo-tools",
                        },
                        {
                            "title": "What SEO tools do agencies use?",
                            "url": "https://other-site.com/agency-tools",
                        },
                    ],
                },
                {
                    "type": "organic",
                    "url": "https://example.com/best-seo-tools",
                    "rank_absolute": 1,
                },
                {
                    "type": "organic",
                    "url": "https://competitor.com/seo-tools",
                    "rank_absolute": 2,
                },
            ]
        }
    ]
}


# ---------------------------------------------------------------------------
# Tests — Parsing
# ---------------------------------------------------------------------------


def test_domain_matches_exact() -> None:
    assert DataForSEOService._domain_matches("https://example.com/page", "example.com") is True


def test_domain_matches_with_www() -> None:
    assert DataForSEOService._domain_matches("https://www.example.com/page", "example.com") is True


def test_domain_matches_subdomain() -> None:
    assert DataForSEOService._domain_matches("https://blog.example.com/page", "example.com") is True


def test_domain_no_match() -> None:
    assert DataForSEOService._domain_matches("https://other.com/page", "example.com") is False


def test_parse_serp_results_with_snippet_ownership() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_RESULT, "example.com")

    assert result["owns_featured_snippet"] is True
    assert result["featured_snippet_url"] == "https://example.com/best-seo-tools"
    assert result["organic_position"] == 1


def test_parse_serp_results_paa_detection() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_RESULT, "example.com")

    # Only the first PAA item matches example.com
    assert len(result["paa_appearances"]) == 1
    assert result["paa_appearances"][0]["question"] == "What is the best free SEO tool?"


def test_parse_serp_results_no_ownership() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_RESULT, "competitor.com")

    assert result["owns_featured_snippet"] is False
    assert result["featured_snippet_url"] is None
    assert result["organic_position"] == 2
    assert len(result["paa_appearances"]) == 0


def test_parse_serp_results_empty() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results({"result": []}, "example.com")

    assert result["owns_featured_snippet"] is False
    assert result["organic_position"] is None
    assert result["paa_appearances"] == []


def test_parse_serp_features_present() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_RESULT, "example.com")

    assert "featured_snippet" in result["serp_features_present"]
    assert "people_also_ask" in result["serp_features_present"]
    assert "organic" in result["serp_features_present"]


# ---------------------------------------------------------------------------
# Tests — Persistence
# ---------------------------------------------------------------------------


def test_upsert_snapshot_insert() -> None:
    db, engine, project, keyword = _build_db()
    try:
        service = DataForSEOService.__new__(DataForSEOService)

        serp_data = {
            "owns_featured_snippet": True,
            "featured_snippet_url": "https://example.com/page",
            "featured_snippet_content": "Some content",
            "paa_appearances": [],
            "organic_position": 1,
            "serp_features_present": ["featured_snippet"],
        }

        snap = service._upsert_snapshot(db, keyword, serp_data, date(2025, 2, 1), "abc123")
        db.commit()

        assert snap.id is not None
        assert snap.owns_featured_snippet is True
        assert snap.keyword_id == keyword.id
        assert snap.project_id == project.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_snapshot_update() -> None:
    db, engine, project, keyword = _build_db()
    try:
        service = DataForSEOService.__new__(DataForSEOService)
        snapshot_date = date(2025, 2, 1)

        serp_data_v1 = {
            "owns_featured_snippet": False,
            "featured_snippet_url": None,
            "featured_snippet_content": None,
            "paa_appearances": [],
            "organic_position": 5,
            "serp_features_present": ["organic"],
        }
        service._upsert_snapshot(db, keyword, serp_data_v1, snapshot_date)
        db.commit()

        # Update: now owns the snippet
        serp_data_v2 = {
            "owns_featured_snippet": True,
            "featured_snippet_url": "https://example.com/page",
            "featured_snippet_content": "New content",
            "paa_appearances": [{"question": "Q?", "url": "https://example.com", "position": 0}],
            "organic_position": 1,
            "serp_features_present": ["featured_snippet", "organic"],
        }
        service._upsert_snapshot(db, keyword, serp_data_v2, snapshot_date, "newHash")
        db.commit()

        # Should still be 1 row
        count = db.query(models.SERPTrackingSnapshot).count()
        assert count == 1

        snap = db.query(models.SERPTrackingSnapshot).first()
        assert snap.owns_featured_snippet is True
        assert snap.organic_position == 1
        assert snap.raw_response_hash == "newHash"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# Tests — Auth
# ---------------------------------------------------------------------------


def test_auth_error_without_credentials() -> None:
    with pytest.raises(DataForSEOAuthError, match="required"):
        DataForSEOService(login=None, password=None)


def test_auth_error_with_empty_credentials() -> None:
    with pytest.raises(DataForSEOAuthError, match="required"):
        DataForSEOService(login="", password="")


# ---------------------------------------------------------------------------
# Tests — AI Overview Detection
# ---------------------------------------------------------------------------


MOCK_SERP_WITH_AI_OVERVIEW = {
    "result": [
        {
            "items": [
                {
                    "type": "ai_overview",
                    "text": "Here is an AI-generated overview of the best SEO tools...",
                    "references": [
                        {"url": "https://example.com/seo-guide", "title": "SEO Guide"},
                        {"url": "https://competitor.com/tools", "title": "Competitor Tools"},
                    ],
                },
                {
                    "type": "featured_snippet",
                    "url": "https://example.com/best-seo-tools",
                    "description": "Top SEO tools for 2025",
                },
                {
                    "type": "organic",
                    "url": "https://example.com/best-seo-tools",
                    "rank_absolute": 1,
                },
            ]
        }
    ]
}


MOCK_SERP_AI_OVERVIEW_NOT_CITED = {
    "result": [
        {
            "items": [
                {
                    "type": "ai_overview",
                    "text": "AI overview about tools...",
                    "references": [
                        {"url": "https://competitor.com/page1"},
                        {"url": "https://other-site.com/page2"},
                    ],
                },
                {
                    "type": "organic",
                    "url": "https://example.com/page",
                    "rank_absolute": 3,
                },
            ]
        }
    ]
}


MOCK_SERP_AI_OVERVIEW_GOOGLE_TYPE = {
    "result": [
        {
            "items": [
                {
                    "type": "google_ai_overview",
                    "description": "Google AI overview content",
                    "items": [
                        {"link": "https://example.com/ref1"},
                    ],
                },
            ]
        }
    ]
}


def test_parse_ai_overview_detected_and_cited() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_WITH_AI_OVERVIEW, "example.com")

    assert result["ai_overview_detected"] is True
    assert result["ai_overview_cites_target"] is True
    assert result["ai_overview_text"] == "Here is an AI-generated overview of the best SEO tools..."
    assert result["ai_overview_source_urls"] == [
        "https://example.com/seo-guide",
        "https://competitor.com/tools",
    ]
    assert "ai_overview" in result["serp_features_present"]


def test_parse_ai_overview_not_cited() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_AI_OVERVIEW_NOT_CITED, "example.com")

    assert result["ai_overview_detected"] is True
    assert result["ai_overview_cites_target"] is False
    assert result["ai_overview_source_urls"] == [
        "https://competitor.com/page1",
        "https://other-site.com/page2",
    ]


def test_parse_ai_overview_google_type_variant() -> None:
    """Handles the 'google_ai_overview' type name and 'items[].link' ref format."""
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_AI_OVERVIEW_GOOGLE_TYPE, "example.com")

    assert result["ai_overview_detected"] is True
    assert result["ai_overview_cites_target"] is True
    assert result["ai_overview_source_urls"] == ["https://example.com/ref1"]
    assert result["ai_overview_text"] == "Google AI overview content"


def test_parse_no_ai_overview() -> None:
    """Legacy SERP without AI Overview has all AIO fields as defaults."""
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results(MOCK_SERP_RESULT, "example.com")

    assert result["ai_overview_detected"] is False
    assert result["ai_overview_cites_target"] is False
    assert result["ai_overview_source_urls"] is None
    assert result["ai_overview_text"] is None


def test_parse_empty_result_ai_overview_defaults() -> None:
    service = DataForSEOService.__new__(DataForSEOService)
    result = service._parse_serp_results({"result": []}, "example.com")

    assert result["ai_overview_detected"] is False
    assert result["ai_overview_cites_target"] is False
    assert result["ai_overview_source_urls"] is None
    assert result["ai_overview_text"] is None


def test_upsert_snapshot_with_ai_overview() -> None:
    db, engine, project, keyword = _build_db()
    try:
        service = DataForSEOService.__new__(DataForSEOService)

        serp_data = {
            "owns_featured_snippet": False,
            "featured_snippet_url": None,
            "featured_snippet_content": None,
            "paa_appearances": [],
            "organic_position": 2,
            "serp_features_present": ["ai_overview", "organic"],
            "ai_overview_detected": True,
            "ai_overview_cites_target": True,
            "ai_overview_source_urls": ["https://example.com/ref"],
            "ai_overview_text": "AI text here",
        }

        snap = service._upsert_snapshot(db, keyword, serp_data, date(2025, 3, 1), "hash1")
        db.commit()

        assert snap.ai_overview_detected is True
        assert snap.ai_overview_cites_target is True
        assert snap.ai_overview_source_urls == ["https://example.com/ref"]
        assert snap.ai_overview_text == "AI text here"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_snapshot_update_ai_overview() -> None:
    db, engine, project, keyword = _build_db()
    try:
        service = DataForSEOService.__new__(DataForSEOService)
        snapshot_date = date(2025, 3, 2)

        # Insert without AIO
        serp_v1 = {
            "owns_featured_snippet": False,
            "featured_snippet_url": None,
            "featured_snippet_content": None,
            "paa_appearances": [],
            "organic_position": 5,
            "serp_features_present": ["organic"],
            "ai_overview_detected": False,
            "ai_overview_cites_target": False,
            "ai_overview_source_urls": None,
            "ai_overview_text": None,
        }
        service._upsert_snapshot(db, keyword, serp_v1, snapshot_date)
        db.commit()

        # Update with AIO
        serp_v2 = {
            "owns_featured_snippet": False,
            "featured_snippet_url": None,
            "featured_snippet_content": None,
            "paa_appearances": [],
            "organic_position": 5,
            "serp_features_present": ["ai_overview", "organic"],
            "ai_overview_detected": True,
            "ai_overview_cites_target": False,
            "ai_overview_source_urls": ["https://other.com/ref"],
            "ai_overview_text": "Updated AI text",
        }
        service._upsert_snapshot(db, keyword, serp_v2, snapshot_date, "hash2")
        db.commit()

        count = db.query(models.SERPTrackingSnapshot).count()
        assert count == 1

        snap = db.query(models.SERPTrackingSnapshot).first()
        assert snap.ai_overview_detected is True
        assert snap.ai_overview_cites_target is False
        assert snap.ai_overview_text == "Updated AI text"
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_upsert_backward_compat_without_ai_overview_keys() -> None:
    """Upsert gracefully handles serp_data dicts that lack AI Overview keys."""
    db, engine, project, keyword = _build_db()
    try:
        service = DataForSEOService.__new__(DataForSEOService)

        # Legacy dict without AI Overview keys
        serp_data = {
            "owns_featured_snippet": True,
            "featured_snippet_url": "https://example.com/page",
            "featured_snippet_content": "Content",
            "paa_appearances": [],
            "organic_position": 1,
            "serp_features_present": ["featured_snippet"],
        }

        snap = service._upsert_snapshot(db, keyword, serp_data, date(2025, 3, 3))
        db.commit()

        assert snap.ai_overview_detected is False
        assert snap.ai_overview_cites_target is False
        assert snap.ai_overview_source_urls is None
        assert snap.ai_overview_text is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
