"""Tests for the Advisor-plan progress / delta service + API (R12 Executive).

Covers the PURE ``compute_plan_delta`` / ``build_plan_progress`` helpers (stable
action identity via ``compute_action_fingerprint`` on the ``action`` text field,
matching how snapshots store the plan) and the read-only, Executive-gated
``GET /api/v1/projects/{project_id}/advisor-plan-progress`` endpoint.

Sync sqlite ``TestClient`` harness mirroring ``test_brand_facts_api`` and
``test_advisor_plan_snapshot``.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from app.services.advisor_plan_snapshot_service import (
    build_plan_progress,
    compute_plan_delta,
    record_snapshot,
)
from app.services.learnings_service import compute_action_fingerprint
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db

PLAN_EXECUTIVE = "plan_executive"  # has_done_for_you_execution = True
PLAN_NO_FEATURE = "plan_specialist"  # has_done_for_you_execution = False


def _plan(actions: list[dict]) -> dict:
    return {
        "schema_version": "advisor-det-1",
        "actions": actions,
        "strategic_summary": None,
        "metadata": {},
    }


def _action(text: str, *, impact: str = "high", effort: str = "low", rank: int = 1) -> dict:
    return {"action": text, "title": text.title(), "impact": impact, "effort": effort, "rank": rank}


# --- compute_plan_delta (pure) -------------------------------------------


def test_delta_added_resolved_carried_by_fingerprint() -> None:
    prev = _plan([_action("Add FAQ schema"), _action("Fix meta description")])
    curr = _plan([_action("Add FAQ schema"), _action("Compress hero image")])

    delta = compute_plan_delta(prev, curr)

    added = {a["action"] for a in delta["actions_added"]}
    resolved = {a["action"] for a in delta["actions_resolved"]}
    carried = {a["action"] for a in delta["actions_carried"]}
    assert added == {"Compress hero image"}
    assert resolved == {"Fix meta description"}
    assert carried == {"Add FAQ schema"}

    # Identity is the shared fingerprint of the action text.
    carried_fp = delta["actions_carried"][0]["fingerprint"]
    assert carried_fp == compute_action_fingerprint("Add FAQ schema")


def test_delta_uses_normalized_fingerprint_for_identity() -> None:
    # Same recommendation, different casing/whitespace => same fingerprint => carried.
    prev = _plan([_action("Add FAQ Schema")])
    curr = _plan([_action("  add faq schema  ")])

    delta = compute_plan_delta(prev, curr)

    assert delta["actions_added"] == []
    assert delta["actions_resolved"] == []
    assert len(delta["actions_carried"]) == 1


def test_delta_impact_delta_and_summaries() -> None:
    prev = _plan([_action("A", impact="high"), _action("B", impact="low")])
    curr = _plan(
        [_action("A", impact="high"), _action("C", impact="high"), _action("D", impact="medium")]
    )

    delta = compute_plan_delta(prev, curr)

    assert delta["summary_prev"] == {
        "total_actions": 2,
        "high_impact": 1,
        "medium_impact": 0,
        "low_impact": 1,
    }
    assert delta["summary_curr"] == {
        "total_actions": 3,
        "high_impact": 2,
        "medium_impact": 1,
        "low_impact": 0,
    }
    assert delta["impact_delta"] == {
        "total_actions": 1,
        "high_impact": 1,
        "medium_impact": 1,
        "low_impact": -1,
    }


def test_delta_prev_none_is_all_added() -> None:
    curr = _plan([_action("A"), _action("B")])

    delta = compute_plan_delta(None, curr)

    assert {a["action"] for a in delta["actions_added"]} == {"A", "B"}
    assert delta["actions_resolved"] == []
    assert delta["actions_carried"] == []
    assert delta["impact_delta"]["total_actions"] == 2
    assert delta["summary_prev"]["total_actions"] == 0


# --- build_plan_progress (pure) ------------------------------------------


class _FakeSnap:
    def __init__(self, advisor_plan: dict, plan_summary: dict, created_at: datetime) -> None:
        self.advisor_plan = advisor_plan
        self.plan_summary = plan_summary
        self.created_at = created_at


def _summary(total: int, high: int, medium: int = 0, low: int = 0) -> dict:
    return {
        "total_actions": total,
        "high_impact": high,
        "medium_impact": medium,
        "low_impact": low,
    }


def test_build_plan_progress_trend_and_latest_delta() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    snap1 = _FakeSnap(
        _plan([_action("A"), _action("B", impact="low")]), _summary(2, 1, low=1), base
    )
    snap2 = _FakeSnap(
        _plan([_action("A"), _action("C")]),
        _summary(2, 2),
        base + timedelta(days=7),
    )

    progress = build_plan_progress([snap1, snap2])

    assert progress["first_summary"]["total_actions"] == 2
    assert progress["latest_summary"]["high_impact"] == 2
    assert [pt["total_actions"] for pt in progress["trend"]] == [2, 2]
    assert [pt["high_impact"] for pt in progress["trend"]] == [1, 2]
    assert progress["trend"][0]["created_at"] == base.isoformat()

    delta = progress["latest_delta"]
    assert delta is not None
    assert {a["action"] for a in delta["actions_added"]} == {"C"}
    assert {a["action"] for a in delta["actions_resolved"]} == {"B"}
    assert {a["action"] for a in delta["actions_carried"]} == {"A"}


def test_build_plan_progress_defensive_under_two_snapshots() -> None:
    empty = build_plan_progress([])
    assert empty == {
        "latest_summary": None,
        "first_summary": None,
        "trend": [],
        "latest_delta": None,
    }

    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    single = _FakeSnap(_plan([_action("A")]), _summary(1, 1), base)
    progress = build_plan_progress([single])
    assert progress["latest_delta"] is None
    assert progress["first_summary"] == progress["latest_summary"]
    assert len(progress["trend"]) == 1


# --- API harness ----------------------------------------------------------


def _seed_subscription(db, user: models.User, plan_type: str, suffix: str) -> None:
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{suffix}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()


def _create_audit(db, *, user_id: int, project_id: int, created_at: datetime, request_id: str):
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


def _build_harness(owner_plan: str = PLAN_EXECUTIVE):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    owner = models.User(email="owner@example.com", hashed_password="x", role="user")
    outsider = models.User(email="outsider@example.com", hashed_password="x", role="user")
    db.add_all([owner, outsider])
    db.commit()
    db.refresh(owner)
    db.refresh(outsider)

    _seed_subscription(db, owner, owner_plan, "owner")
    _seed_subscription(db, outsider, PLAN_EXECUTIVE, "outsider")

    workspace = models.Workspace(name="Owner WS", owner_id=owner.id)
    other_workspace = models.Workspace(name="Outsider WS", owner_id=outsider.id)
    db.add_all([workspace, other_workspace])
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Project A",
        domain_url="https://snap.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    state = {"user": owner}

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return state["user"]

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    client = TestClient(app)
    return client, db, state, owner, outsider, project


def _seed_two_snapshots(db, owner_id: int, project_id: int) -> None:
    base = datetime.now(timezone.utc)
    audit_a = _create_audit(
        db, user_id=owner_id, project_id=project_id, created_at=base, request_id="a"
    )
    audit_b = _create_audit(
        db,
        user_id=owner_id,
        project_id=project_id,
        created_at=base + timedelta(days=7),
        request_id="b",
    )
    db.commit()
    snap_a = record_snapshot(
        db,
        audit_a.id,
        project_id,
        _plan([_action("Add FAQ schema"), _action("Fix meta", impact="low")]),
    )
    snap_a.created_at = base
    snap_b = record_snapshot(
        db, audit_b.id, project_id, _plan([_action("Add FAQ schema"), _action("Compress hero")])
    )
    snap_b.created_at = base + timedelta(days=7)
    db.commit()


def _url(project_id: int) -> str:
    return f"/api/v1/projects/{project_id}/advisor-plan-progress"


def test_api_returns_progress_for_seeded_snapshots():
    client, db, state, owner, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        _seed_two_snapshots(db, owner.id, project.id)

        resp = client.get(_url(project.id))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["first_summary"]["total_actions"] == 2
        assert body["latest_summary"]["high_impact"] == 2
        assert len(body["trend"]) == 2
        delta = body["latest_delta"]
        assert {a["action"] for a in delta["actions_added"]} == {"Compress hero"}
        assert {a["action"] for a in delta["actions_resolved"]} == {"Fix meta"}
        assert {a["action"] for a in delta["actions_carried"]} == {"Add FAQ schema"}
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_no_snapshots_returns_empty_but_valid_200():
    client, db, state, owner, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        resp = client.get(_url(project.id))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body == {
            "latest_summary": None,
            "first_summary": None,
            "trend": [],
            "latest_delta": None,
        }
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_cross_tenant_denied_403():
    client, db, state, owner, outsider, project = _build_harness()
    try:
        _seed_two_snapshots(db, owner.id, project.id)
        state["user"] = outsider  # Executive plan, but not a member of the workspace
        resp = client.get(_url(project.id))
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_api_without_done_for_you_execution_returns_402():
    client, db, state, owner, _outsider, project = _build_harness(owner_plan=PLAN_NO_FEATURE)
    try:
        state["user"] = owner  # member + has access, but plan lacks the capability
        resp = client.get(_url(project.id))
        assert resp.status_code == 402, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()
