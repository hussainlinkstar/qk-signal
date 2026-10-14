"""Tests for the new monitoring database models.

Validates that ProjectGA4Config, LLMTrafficSnapshot, TargetKeyword,
and SERPTrackingSnapshot can be created, queried, and cascade-deleted
in an in-memory SQLite database.
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_db() -> tuple[Session, Engine, models.User, models.Project]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()

    user = models.User(
        email="test-monitoring@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(
        name="Test Agency",
        owner_id=user.id,
    )
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        name="Client Site",
        domain_url="example.com",
        workspace_id=workspace.id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return db, engine, user, project


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# ProjectGA4Config
# ---------------------------------------------------------------------------


def test_create_ga4_config() -> None:
    db, engine, user, project = _build_db()
    try:
        config = models.ProjectGA4Config(
            project_id=project.id,
            ga4_property_id="properties/123456",
        )
        db.add(config)
        db.commit()
        db.refresh(config)

        assert config.id is not None
        assert config.ga4_property_id == "properties/123456"
        assert config.is_active is True
        assert config.last_synced_at is None

        # Relationship
        db.refresh(project)
        assert project.ga4_config is not None
        assert project.ga4_config.id == config.id
    finally:
        _cleanup(db, engine)


def test_ga4_config_unique_per_project() -> None:
    db, engine, user, project = _build_db()
    try:
        db.add(models.ProjectGA4Config(project_id=project.id, ga4_property_id="properties/1"))
        db.commit()

        db.add(models.ProjectGA4Config(project_id=project.id, ga4_property_id="properties/2"))
        with pytest.raises(Exception):  # IntegrityError
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# LLMTrafficSnapshot
# ---------------------------------------------------------------------------


def test_create_llm_traffic_snapshot() -> None:
    db, engine, user, project = _build_db()
    try:
        snapshot = models.LLMTrafficSnapshot(
            project_id=project.id,
            source="chatgpt.com",
            snapshot_date=date(2025, 1, 15),
            sessions=42,
            users=35,
            page_views=120,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)

        assert snapshot.id is not None
        assert snapshot.source == "chatgpt.com"
        assert snapshot.sessions == 42
        assert snapshot.snapshot_date == date(2025, 1, 15)
    finally:
        _cleanup(db, engine)


def test_llm_traffic_snapshot_unique_constraint() -> None:
    db, engine, user, project = _build_db()
    try:
        db.add(
            models.LLMTrafficSnapshot(
                project_id=project.id,
                source="chatgpt.com",
                snapshot_date=date(2025, 1, 15),
                sessions=10,
            )
        )
        db.commit()

        # Same project + source + date should fail
        db.add(
            models.LLMTrafficSnapshot(
                project_id=project.id,
                source="chatgpt.com",
                snapshot_date=date(2025, 1, 15),
                sessions=20,
            )
        )
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, engine)


def test_llm_traffic_multiple_sources() -> None:
    db, engine, user, project = _build_db()
    try:
        for source in ["chatgpt.com", "perplexity.ai", "claude.ai"]:
            db.add(
                models.LLMTrafficSnapshot(
                    project_id=project.id,
                    source=source,
                    snapshot_date=date(2025, 1, 15),
                    sessions=10,
                )
            )
        db.commit()

        snapshots = (
            db.query(models.LLMTrafficSnapshot)
            .filter(models.LLMTrafficSnapshot.project_id == project.id)
            .all()
        )
        assert len(snapshots) == 3
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# TargetKeyword
# ---------------------------------------------------------------------------


def test_create_target_keyword() -> None:
    db, engine, user, project = _build_db()
    try:
        kw = models.TargetKeyword(
            project_id=project.id,
            keyword="best seo tools",
            language_code="en",
        )
        db.add(kw)
        db.commit()
        db.refresh(kw)

        assert kw.id is not None
        assert kw.keyword == "best seo tools"
        assert kw.is_active is True
        assert kw.search_engine == "google"
    finally:
        _cleanup(db, engine)


def test_target_keyword_unique_per_project() -> None:
    db, engine, user, project = _build_db()
    try:
        db.add(models.TargetKeyword(project_id=project.id, keyword="seo tools"))
        db.commit()

        db.add(models.TargetKeyword(project_id=project.id, keyword="seo tools"))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, engine)


def test_create_project_visibility_query() -> None:
    db, engine, user, project = _build_db()
    try:
        visibility_query = models.ProjectVisibilityQuery(
            project_id=project.id,
            query_text="best payroll software",
            query_type="aeo",
            providers=["google", "openai"],
        )
        db.add(visibility_query)
        db.commit()
        db.refresh(visibility_query)

        assert visibility_query.id is not None
        assert visibility_query.query_text == "best payroll software"
        assert visibility_query.providers == ["google", "openai"]

        db.refresh(project)
        assert len(project.visibility_queries) == 1
    finally:
        _cleanup(db, engine)


def test_project_visibility_query_unique_per_project() -> None:
    db, engine, user, project = _build_db()
    try:
        db.add(
            models.ProjectVisibilityQuery(project_id=project.id, query_text="best payroll software")
        )
        db.commit()

        db.add(
            models.ProjectVisibilityQuery(project_id=project.id, query_text="best payroll software")
        )
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# SERPTrackingSnapshot
# ---------------------------------------------------------------------------


def test_create_serp_tracking_snapshot() -> None:
    db, engine, user, project = _build_db()
    try:
        kw = models.TargetKeyword(project_id=project.id, keyword="seo audit")
        db.add(kw)
        db.commit()
        db.refresh(kw)

        snap = models.SERPTrackingSnapshot(
            keyword_id=kw.id,
            project_id=project.id,
            snapshot_date=date(2025, 2, 1),
            owns_featured_snippet=True,
            featured_snippet_url="https://example.com/seo-audit",
            paa_appearances=[
                {
                    "question": "What is an SEO audit?",
                    "url": "https://example.com/faq",
                    "position": 0,
                }
            ],
            organic_position=3,
            serp_features_present=["featured_snippet", "people_also_ask", "organic"],
        )
        db.add(snap)
        db.commit()
        db.refresh(snap)

        assert snap.id is not None
        assert snap.owns_featured_snippet is True
        assert snap.organic_position == 3
        assert len(snap.paa_appearances) == 1

        # Via keyword relationship
        db.refresh(kw)
        assert len(kw.serp_snapshots) == 1
    finally:
        _cleanup(db, engine)


def test_serp_snapshot_unique_per_keyword_date() -> None:
    db, engine, user, project = _build_db()
    try:
        kw = models.TargetKeyword(project_id=project.id, keyword="test kw")
        db.add(kw)
        db.commit()
        db.refresh(kw)

        db.add(
            models.SERPTrackingSnapshot(
                keyword_id=kw.id,
                project_id=project.id,
                snapshot_date=date(2025, 2, 1),
                owns_featured_snippet=False,
            )
        )
        db.commit()

        db.add(
            models.SERPTrackingSnapshot(
                keyword_id=kw.id,
                project_id=project.id,
                snapshot_date=date(2025, 2, 1),
                owns_featured_snippet=True,
            )
        )
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
    finally:
        _cleanup(db, engine)


# ---------------------------------------------------------------------------
# Cascade Deletion
# ---------------------------------------------------------------------------


def test_cascade_delete_project_removes_monitoring_data() -> None:
    """Deleting a project should cascade-delete all monitoring data."""
    db, engine, user, project = _build_db()
    try:
        # Add GA4 config
        db.add(models.ProjectGA4Config(project_id=project.id, ga4_property_id="properties/999"))
        # Add traffic snapshot
        db.add(
            models.LLMTrafficSnapshot(
                project_id=project.id,
                source="chatgpt.com",
                snapshot_date=date(2025, 1, 1),
                sessions=5,
            )
        )
        # Add keyword + SERP snapshot
        kw = models.TargetKeyword(project_id=project.id, keyword="cascade test")
        db.add(kw)
        db.add(
            models.ProjectVisibilityQuery(
                project_id=project.id,
                query_text="cascade visibility",
                providers=["google"],
            )
        )
        db.commit()
        db.refresh(kw)

        db.add(
            models.SERPTrackingSnapshot(
                keyword_id=kw.id,
                project_id=project.id,
                snapshot_date=date(2025, 2, 1),
                owns_featured_snippet=False,
            )
        )
        db.commit()

        # Verify data exists
        assert db.query(models.ProjectGA4Config).count() == 1
        assert db.query(models.LLMTrafficSnapshot).count() == 1
        assert db.query(models.TargetKeyword).count() == 1
        assert db.query(models.ProjectVisibilityQuery).count() == 1
        assert db.query(models.SERPTrackingSnapshot).count() == 1

        # Delete the project
        db.delete(project)
        db.commit()

        # All monitoring data should be gone
        assert db.query(models.ProjectGA4Config).count() == 0
        assert db.query(models.LLMTrafficSnapshot).count() == 0
        assert db.query(models.TargetKeyword).count() == 0
        assert db.query(models.ProjectVisibilityQuery).count() == 0
        assert db.query(models.SERPTrackingSnapshot).count() == 0
    finally:
        _cleanup(db, engine)
