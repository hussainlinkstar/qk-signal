from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from routers.workspace_router import (
    get_project_budget,
    get_workspace_cost_breakdown,
    put_project_budget,
    remove_project_budget,
    ProjectBudgetUpsertRequest,
)
from services.project_budget_service import (
    check_project_scan_capacity,
    consume_project_scan,
    enforce_project_scan_cap,
    get_project_budget_snapshot,
)


def _build_db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory()


def _cleanup(db: Session) -> None:
    engine = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_workspace(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(
        email="owner-budget@example.com",
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Budget Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Budgeted Project",
        domain_url="https://budget.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def test_consume_project_scan_tracks_usage_thresholds_and_cap() -> None:
    db = _build_db()
    try:
        owner, _workspace, project = _seed_workspace(db)
        put_project_budget(
            workspace_id=project.workspace_id,
            project_id=project.id,
            payload=ProjectBudgetUpsertRequest(monthly_limit_scans=10, cycle_anchor_day=1),
            user=owner,
            db=db,
        )

        for _ in range(7):
            consume_project_scan(db, project_id=project.id)
        db.commit()

        snapshot = get_project_budget_snapshot(db, project_id=project.id)
        assert snapshot.consumed_scans == 7
        assert snapshot.remaining_scans == 3
        assert snapshot.warning_threshold_reached is False

        result = consume_project_scan(db, project_id=project.id)
        db.commit()
        assert result.status == "consumed"
        assert result.consumed_scans == 8
        assert "warning_80" in result.threshold_events

        result = consume_project_scan(db, project_id=project.id)
        db.commit()
        assert result.status == "consumed"
        assert result.consumed_scans == 9
        assert result.threshold_events == ()

        result = consume_project_scan(db, project_id=project.id)
        db.commit()
        assert result.status == "consumed"
        assert result.consumed_scans == 10
        assert result.remaining_scans == 0
        assert "limit_reached" in result.threshold_events

        blocked = consume_project_scan(db, project_id=project.id)
        assert blocked.status == "budget_exceeded"
        assert blocked.remaining_scans == 0
        assert blocked.consumed_scans == 10
    finally:
        _cleanup(db)


def test_consume_project_scan_never_blocks_without_a_cap() -> None:
    db = _build_db()
    try:
        _owner, _workspace, project = _seed_workspace(db)
        for _ in range(50):
            result = consume_project_scan(db, project_id=project.id)
            assert result.status == "consumed"
        db.commit()

        snapshot = get_project_budget_snapshot(db, project_id=project.id)
        assert snapshot.monthly_limit_scans is None
        assert snapshot.consumed_scans == 50
        assert snapshot.remaining_scans is None
    finally:
        _cleanup(db)


def test_enforce_project_scan_cap_raises_402_with_scan_wording() -> None:
    db = _build_db()
    try:
        owner, _workspace, project = _seed_workspace(db)
        put_project_budget(
            workspace_id=project.workspace_id,
            project_id=project.id,
            payload=ProjectBudgetUpsertRequest(monthly_limit_scans=1, cycle_anchor_day=1),
            user=owner,
            db=db,
        )

        enforce_project_scan_cap(db, project=project)
        db.commit()

        with pytest.raises(HTTPException) as excinfo:
            enforce_project_scan_cap(db, project=project)
        assert excinfo.value.status_code == 402
        detail = str(excinfo.value.detail)
        assert "scans" in detail
        assert "credit" not in detail.lower()
        assert "Budgeted Project" in detail
    finally:
        _cleanup(db)


def test_enforce_project_scan_cap_noop_without_project() -> None:
    db = _build_db()
    try:
        _seed_workspace(db)
        assert enforce_project_scan_cap(db, project=None) is None
    finally:
        _cleanup(db)


def test_check_project_scan_capacity_does_not_consume() -> None:
    db = _build_db()
    try:
        owner, _workspace, project = _seed_workspace(db)
        put_project_budget(
            workspace_id=project.workspace_id,
            project_id=project.id,
            payload=ProjectBudgetUpsertRequest(monthly_limit_scans=5, cycle_anchor_day=1),
            user=owner,
            db=db,
        )
        first = check_project_scan_capacity(db, project_id=project.id)
        second = check_project_scan_capacity(db, project_id=project.id)
        db.commit()
        assert first.consumed_scans == 0
        assert second.consumed_scans == 0
    finally:
        _cleanup(db)


def test_project_budget_endpoints_round_trip_and_cost_breakdown() -> None:
    db = _build_db()
    try:
        owner, workspace, project = _seed_workspace(db)

        saved = put_project_budget(
            workspace_id=workspace.id,
            project_id=project.id,
            payload=ProjectBudgetUpsertRequest(monthly_limit_scans=2500, cycle_anchor_day=5),
            user=owner,
            db=db,
        )
        current = get_project_budget(
            workspace_id=workspace.id,
            project_id=project.id,
            user=owner,
            db=db,
        )
        breakdown = get_workspace_cost_breakdown(
            workspace_id=workspace.id,
            user=owner,
            db=db,
        )
        removed = remove_project_budget(
            workspace_id=workspace.id,
            project_id=project.id,
            user=owner,
            db=db,
        )

        assert saved["monthly_limit_scans"] == 2500
        assert current["budget_configured"] is True
        assert current["cycle_anchor_day"] == 5
        assert breakdown["workspace_id"] == workspace.id
        assert len(breakdown["projects"]) == 1
        assert breakdown["projects"][0]["project_name"] == "Budgeted Project"
        assert removed["budget_configured"] is False
        assert removed["monthly_limit_scans"] is None
    finally:
        _cleanup(db)
