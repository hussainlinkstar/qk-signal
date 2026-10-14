"""Task 6.3 — feed project brand facts into the audit evidence anchor.

Two layers of verification:

1. Unit: ``get_brand_facts_evidence`` returns structured, namespaced items for
   a project's brand facts (and ``[]`` when there are none / no db / no project).
2. Integration (no LLM): the evidence-anchor builder
   (``UnifiedTruthContextService.build_context``) ADDITIVELY includes those items
   under a clearly-namespaced ``brand_facts`` key, including forbidden facts,
   without disturbing the existing evidence-anchor structure.

These tests must NOT run the LLM pipeline; everything is seeded against an
in-memory SQLite database.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.services.brand_facts_service import (
    create_brand_fact,
    get_brand_facts_evidence,
)
from database import Base
from services.unified_truth_context_service import UnifiedTruthContextService


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup_db(db, engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_project(db) -> models.Project:
    user = models.User(
        email="owner@example.com",
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()
    workspace = models.Workspace(name="Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Project",
        domain_url="https://example.com",
    )
    db.add(project)
    db.flush()
    db.commit()
    db.refresh(project)
    return project


def test_get_brand_facts_evidence_returns_structured_items() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        create_brand_fact(
            db,
            project_id=project.id,
            kind="fact",
            statement="Our headquarters is in Austin, Texas.",
            is_forbidden=False,
        )
        create_brand_fact(
            db,
            project_id=project.id,
            kind="claim",
            statement="We never claim to be HIPAA certified.",
            is_forbidden=True,
        )
        db.commit()

        evidence = get_brand_facts_evidence(db, project.id)

        assert len(evidence) == 2
        for item in evidence:
            assert set(item.keys()) == {"kind", "statement", "is_forbidden", "source"}
            assert item["source"] == "brand_fact"

        first, second = evidence
        assert first["kind"] == "fact"
        assert first["statement"] == "Our headquarters is in Austin, Texas."
        assert first["is_forbidden"] is False

        assert second["kind"] == "claim"
        assert second["is_forbidden"] is True
    finally:
        _cleanup_db(db, engine)


def test_get_brand_facts_evidence_empty_cases() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        # No facts seeded for this project.
        assert get_brand_facts_evidence(db, project.id) == []
        # Defensive guards.
        assert get_brand_facts_evidence(db, None) == []
        assert get_brand_facts_evidence(None, project.id) == []
    finally:
        _cleanup_db(db, engine)


def test_build_context_includes_brand_facts_additively() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        create_brand_fact(
            db,
            project_id=project.id,
            kind="fact",
            statement="Founded in 2015 in Berlin.",
            is_forbidden=False,
        )
        create_brand_fact(
            db,
            project_id=project.id,
            kind="claim",
            statement="Do not state we are the market leader.",
            is_forbidden=True,
        )
        db.commit()

        context = UnifiedTruthContextService(db).build_context(
            project_id=project.id,
            audit_target_type="website",
            target_name=project.name,
            target_url=project.domain_url,
            category="saas",
            market="germany",
            source_content="Some scraped page content about the company.",
        )

        # Additive: the namespaced key is present alongside existing anchors.
        assert "brand_facts" in context
        assert context["schema_version"] == "utc-1"
        assert "scraped_text" in context
        assert "domain_standards" in context

        brand_facts = context["brand_facts"]
        assert len(brand_facts) == 2
        statements = {item["statement"] for item in brand_facts}
        assert "Founded in 2015 in Berlin." in statements
        # Forbidden fact is carried into the evidence anchor.
        forbidden = [item for item in brand_facts if item["is_forbidden"]]
        assert len(forbidden) == 1
        assert forbidden[0]["statement"] == "Do not state we are the market leader."
        assert forbidden[0]["source"] == "brand_fact"
    finally:
        _cleanup_db(db, engine)


def test_build_context_brand_facts_empty_when_no_project() -> None:
    db, engine = _build_db()
    try:
        context = UnifiedTruthContextService(db).build_context(
            project_id=None,
            audit_target_type="website",
            target_name="Anon",
            target_url="https://example.com",
            category="saas",
            market="germany",
            source_content="content",
        )
        assert context["brand_facts"] == []
    finally:
        _cleanup_db(db, engine)
