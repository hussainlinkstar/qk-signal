"""Tests for the per-audit Advisor-plan snapshot persistence (R12 foundation).

Covers the pure ``summarize_plan`` counter and the defensive
``record_snapshot`` / ``list_snapshots`` persistence helpers against an
in-memory SQLite database (sync ``Session``, matching the worker/routers).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from app.services.advisor_plan_snapshot_service import (
    list_snapshots,
    record_snapshot,
    summarize_plan,
)
from database import Base


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _cleanup(db: Session, engine: object) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_project(db: Session) -> models.Project:
    owner = models.User(email="snap@example.com", hashed_password="x", role="user", credits=10)
    db.add(owner)
    db.flush()
    workspace = models.Workspace(name="Snap Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Snap Client",
        domain_url="https://snap.example",
        target_country="US",
        language="en",
    )
    db.add(project)
    db.flush()
    db._owner = owner  # type: ignore[attr-defined]
    return project


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    created_at: datetime,
    request_id: str,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://snap.example",
        target_url="https://snap.example",
        target_name="snap.example",
        geo_score=50.0,
        seo_score=60.0,
        aeo_score=40.0,
        request_id=request_id,
        created_at=created_at,
        full_report={"metadata": {}},
    )
    db.add(audit)
    db.flush()
    return audit


def _plan(impacts: list[str]) -> dict:
    return {
        "schema_version": "advisor-det-1",
        "actions": [
            {"action": f"Fix {i}", "impact": impact, "effort": "low", "rank": i}
            for i, impact in enumerate(impacts, start=1)
        ],
        "strategic_summary": None,
        "metadata": {},
    }


# --- summarize_plan -------------------------------------------------------


def test_summarize_plan_counts_by_impact() -> None:
    summary = summarize_plan(_plan(["high", "high", "medium", "low"]))
    assert summary == {
        "total_actions": 4,
        "high_impact": 2,
        "medium_impact": 1,
        "low_impact": 1,
    }


def test_summarize_plan_empty_and_malformed() -> None:
    zeros = {"total_actions": 0, "high_impact": 0, "medium_impact": 0, "low_impact": 0}
    assert summarize_plan({"actions": []}) == zeros
    assert summarize_plan({}) == zeros
    assert summarize_plan(None) == zeros
    # unknown impact still counts toward total only
    assert summarize_plan(_plan(["urgent"])) == {
        "total_actions": 1,
        "high_impact": 0,
        "medium_impact": 0,
        "low_impact": 0,
    }


# --- record_snapshot ------------------------------------------------------


def test_record_snapshot_creates_one_row() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=db._owner.id,  # type: ignore[attr-defined]
            project_id=project.id,
            created_at=datetime.now(timezone.utc),
            request_id="req-1",
        )
        db.commit()

        row = record_snapshot(db, audit.id, project.id, _plan(["high", "low"]))
        db.commit()

        assert row is not None
        assert row.audit_id == audit.id
        assert row.project_id == project.id
        assert row.plan_summary["total_actions"] == 2
        assert row.plan_summary["high_impact"] == 1
        assert row.advisor_plan["actions"][0]["action"] == "Fix 1"
        assert len(list_snapshots(db, project.id)) == 1
    finally:
        _cleanup(db, engine)


def test_record_snapshot_upserts_on_rerun() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=db._owner.id,  # type: ignore[attr-defined]
            project_id=project.id,
            created_at=datetime.now(timezone.utc),
            request_id="req-1",
        )
        db.commit()

        first = record_snapshot(db, audit.id, project.id, _plan(["high"]))
        db.commit()
        second = record_snapshot(db, audit.id, project.id, _plan(["high", "medium", "low"]))
        db.commit()

        assert first is not None and second is not None
        assert first.id == second.id  # same row, no duplicate
        rows = list_snapshots(db, project.id)
        assert len(rows) == 1
        assert rows[0].plan_summary["total_actions"] == 3
    finally:
        _cleanup(db, engine)


def test_record_snapshot_noops_on_empty_plan() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        audit = _create_audit(
            db,
            user_id=db._owner.id,  # type: ignore[attr-defined]
            project_id=project.id,
            created_at=datetime.now(timezone.utc),
            request_id="req-1",
        )
        db.commit()

        assert record_snapshot(db, audit.id, project.id, {"actions": []}) is None
        assert record_snapshot(db, audit.id, project.id, None) is None
        db.commit()
        assert list_snapshots(db, project.id) == []
    finally:
        _cleanup(db, engine)


def test_record_snapshot_defensive_on_missing_ids() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        db.commit()
        # missing audit_id / project_id => no-op, never raises
        assert record_snapshot(db, None, project.id, _plan(["high"])) is None
        assert record_snapshot(db, 999, None, _plan(["high"])) is None
        db.commit()
        assert list_snapshots(db, project.id) == []
    finally:
        _cleanup(db, engine)


def test_list_snapshots_is_chronological() -> None:
    db, engine = _build_db()
    try:
        project = _seed_project(db)
        owner_id = db._owner.id  # type: ignore[attr-defined]
        base = datetime.now(timezone.utc)
        audit_a = _create_audit(
            db, user_id=owner_id, project_id=project.id, created_at=base, request_id="a"
        )
        audit_b = _create_audit(
            db,
            user_id=owner_id,
            project_id=project.id,
            created_at=base + timedelta(hours=1),
            request_id="b",
        )
        db.commit()

        # record newest first to prove ordering is by created_at, not insert order
        snap_b = record_snapshot(db, audit_b.id, project.id, _plan(["high"]))
        snap_b.created_at = base + timedelta(hours=2)
        db.flush()
        snap_a = record_snapshot(db, audit_a.id, project.id, _plan(["low"]))
        snap_a.created_at = base + timedelta(hours=1)
        db.commit()

        rows = list_snapshots(db, project.id)
        assert [r.audit_id for r in rows] == [audit_a.id, audit_b.id]
    finally:
        _cleanup(db, engine)
