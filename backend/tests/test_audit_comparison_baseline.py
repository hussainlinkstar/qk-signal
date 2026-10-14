"""Baseline selection for score deltas, against a real database (SIGV2-1109).

``_find_previous_audit`` used to ignore scan depth entirely and to treat the
project as a soft preference with a fallback that dropped it, so a Fast scan
could be compared against a Deep scan, or against an audit belonging to a
different project. The delta it produced measured the pipeline or the wrong
site, not a change of this site.

These tests run the real SQLAlchemy query against an in-memory database, so
they assert what the filters do rather than what a mocked query chain was told
to return.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models  # noqa: E402
from database import Base  # noqa: E402
from services.audit_comparison_service import (  # noqa: E402
    _find_previous_audit,
    _load_audit_history,
    get_audit_comparison,
)

BASE_TIME = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
URL = "https://example.com"


def _build_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return session_factory(), engine


def _cleanup_db(db, engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _make_user(db) -> models.User:
    user = models.User(
        email="baseline@example.com",
        hashed_password="x",
        role="user",
        credits=10,
        notifications_enabled=True,
    )
    db.add(user)
    db.flush()
    return user


def _add_audit(
    db,
    *,
    user_id: int,
    minutes_ago: int,
    audit_type: models.AuditType = models.AuditType.FAST,
    project_id: int | None = None,
    url: str = URL,
    seo_score: float = 70.0,
    geo_score: float = 60.0,
    aeo_score: float = 50.0,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        url=url,
        audit_type=audit_type,
        audit_target_type=models.AuditTargetType.WEBSITE,
        project_id=project_id,
        seo_score=seo_score,
        geo_score=geo_score,
        aeo_score=aeo_score,
        full_report={},
        created_at=BASE_TIME - timedelta(minutes=minutes_ago),
    )
    db.add(audit)
    db.flush()
    return audit


def _make_project(db, user: models.User, *, name: str) -> models.Project:
    workspace = models.Workspace(name=f"ws-{name}", owner_id=user.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name=name,
        domain_url=URL,
    )
    db.add(project)
    db.flush()
    return project


class TestDepthMatching:
    def test_returns_nothing_when_the_only_candidate_has_another_depth(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            _add_audit(db, user_id=user.id, minutes_ago=60, audit_type=models.AuditType.DEEP)
            current = _add_audit(
                db, user_id=user.id, minutes_ago=0, audit_type=models.AuditType.FAST
            )

            assert _find_previous_audit(db, current, user.id) is None
        finally:
            _cleanup_db(db, engine)

    def test_returns_the_previous_audit_of_the_same_depth(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            _add_audit(db, user_id=user.id, minutes_ago=30, audit_type=models.AuditType.DEEP)
            same_depth = _add_audit(
                db, user_id=user.id, minutes_ago=60, audit_type=models.AuditType.FAST
            )
            current = _add_audit(
                db, user_id=user.id, minutes_ago=0, audit_type=models.AuditType.FAST
            )

            assert _find_previous_audit(db, current, user.id) is same_depth
        finally:
            _cleanup_db(db, engine)


class TestProjectMatching:
    def test_returns_nothing_when_the_only_candidate_belongs_to_another_project(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            other = _make_project(db, user, name="other")
            mine = _make_project(db, user, name="mine")
            _add_audit(db, user_id=user.id, minutes_ago=60, project_id=other.id)
            current = _add_audit(db, user_id=user.id, minutes_ago=0, project_id=mine.id)

            assert _find_previous_audit(db, current, user.id) is None
        finally:
            _cleanup_db(db, engine)

    def test_returns_nothing_when_the_only_candidate_has_no_project(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            mine = _make_project(db, user, name="mine")
            _add_audit(db, user_id=user.id, minutes_ago=60, project_id=None)
            current = _add_audit(db, user_id=user.id, minutes_ago=0, project_id=mine.id)

            assert _find_previous_audit(db, current, user.id) is None
        finally:
            _cleanup_db(db, engine)

    def test_returns_the_previous_audit_of_the_same_project(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            other = _make_project(db, user, name="other")
            mine = _make_project(db, user, name="mine")
            _add_audit(db, user_id=user.id, minutes_ago=30, project_id=other.id)
            same_project = _add_audit(db, user_id=user.id, minutes_ago=60, project_id=mine.id)
            current = _add_audit(db, user_id=user.id, minutes_ago=0, project_id=mine.id)

            assert _find_previous_audit(db, current, user.id) is same_project
        finally:
            _cleanup_db(db, engine)


class TestHistoryMatching:
    def test_history_holds_only_comparable_audits(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            project = _make_project(db, user, name="mine")
            other = _make_project(db, user, name="other")
            _add_audit(
                db,
                user_id=user.id,
                minutes_ago=90,
                project_id=project.id,
                audit_type=models.AuditType.DEEP,
            )
            _add_audit(db, user_id=user.id, minutes_ago=80, project_id=other.id)
            comparable = _add_audit(db, user_id=user.id, minutes_ago=60, project_id=project.id)
            current = _add_audit(db, user_id=user.id, minutes_ago=0, project_id=project.id)

            history = _load_audit_history(db, current, user.id)

            assert [a.id for a in history] == [comparable.id, current.id]
        finally:
            _cleanup_db(db, engine)


class TestComparisonPayloadWithoutComparableBaseline:
    """The payload every delta surface renders from must carry no delta."""

    def test_no_delta_is_reported_against_an_audit_of_another_depth(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            _add_audit(
                db,
                user_id=user.id,
                minutes_ago=60,
                audit_type=models.AuditType.DEEP,
                seo_score=60.0,
                geo_score=50.0,
                aeo_score=40.0,
            )
            current = _add_audit(
                db,
                user_id=user.id,
                minutes_ago=0,
                audit_type=models.AuditType.FAST,
                seo_score=70.0,
                geo_score=60.0,
                aeo_score=50.0,
            )
            db.commit()

            result = get_audit_comparison(db, current.id, user.id)

            assert result is not None
            assert result["has_previous"] is False
            assert "previous_audit_id" not in result
            for dimension in ("overall", "seo", "geo", "aeo"):
                entry = result["scores"][dimension]
                assert "delta" not in entry
                assert "previous" not in entry
            assert result["sub_components"] == {}
        finally:
            _cleanup_db(db, engine)

    def test_no_delta_is_reported_against_an_audit_of_another_project(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            other = _make_project(db, user, name="other")
            mine = _make_project(db, user, name="mine")
            _add_audit(db, user_id=user.id, minutes_ago=60, project_id=other.id, seo_score=60.0)
            current = _add_audit(
                db, user_id=user.id, minutes_ago=0, project_id=mine.id, seo_score=70.0
            )
            db.commit()

            result = get_audit_comparison(db, current.id, user.id)

            assert result is not None
            assert result["has_previous"] is False
            assert "delta" not in result["scores"]["seo"]
        finally:
            _cleanup_db(db, engine)

    def test_delta_is_reported_against_a_comparable_baseline(self):
        db, engine = _build_db()
        try:
            user = _make_user(db)
            project = _make_project(db, user, name="mine")
            previous = _add_audit(
                db,
                user_id=user.id,
                minutes_ago=60,
                project_id=project.id,
                seo_score=60.0,
            )
            current = _add_audit(
                db,
                user_id=user.id,
                minutes_ago=0,
                project_id=project.id,
                seo_score=70.0,
            )
            db.commit()

            result = get_audit_comparison(db, current.id, user.id)

            assert result is not None
            assert result["has_previous"] is True
            assert result["previous_audit_id"] == previous.id
            assert result["scores"]["seo"]["delta"] == 10.0
        finally:
            _cleanup_db(db, engine)
