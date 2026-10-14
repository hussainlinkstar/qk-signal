"""Per-plan cap on tracked SERP keywords (SIGV2-1150).

Tracked prompts have been capped per plan since SIGV2-1142, but tracked
keywords had no ceiling of any kind: ``create_target_keyword`` checked project
access and nothing else. Each keyword costs one DataForSEO SERP task per
monitoring cycle (one ``task_post`` per active keyword, daily by default), so an
uncapped list is an uncapped recurring cost.

These tests pin the cap, the refusal wording, the reactivation hole it would
otherwise leave open, and the grandfathering promise: a project already over the
cap keeps every keyword it has and the monitoring worker keeps syncing all of
them.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from app.config.plans import CANONICAL_PLAN_TYPES, CAPABILITY_MATRIX
from database import Base
from services.target_keyword_limit_service import (
    count_active_keywords,
    enforce_keyword_limit,
    keyword_allowances,
    max_tracked_keywords,
    resolve_project_plan,
)

try:
    from main import app, get_current_user, get_db
except Exception:  # pragma: no cover - service-level tests still run
    app = None
    get_current_user = None
    get_db = None


# The decision (SIGV2-1150): the keyword cap mirrors the prompt cap ladder,
# because keywords are the same class of tracked, per-cycle-metered resource.
EXPECTED_KEYWORD_CAPS = {
    "plan_starter": 5,
    "plan_agency_trial": 10,
    "plan_standard": 10,
    "plan_specialist": 50,
    "plan_executive": 200,
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_project_context(plan_type: str = "plan_standard"):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()

    user = models.User(
        email=f"keyword-cap-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=25,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_keyword_{plan_type}",
            stripe_subscription_id=f"sub_keyword_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()
    db.refresh(user)

    workspace = models.Workspace(name="Keyword Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="northwind.example",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return db, user, project


def _build_client(plan_type: str = "plan_standard"):
    if app is None or get_db is None or get_current_user is None:
        pytest.skip("main app import unavailable in this test runtime")

    db, user, project = _build_project_context(plan_type=plan_type)

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app), db, user, project


def _cleanup(db) -> None:
    if app is not None:
        app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def _seed_keywords(db, project, count: int, *, is_active: bool = True, prefix: str = "kw") -> None:
    for index in range(count):
        db.add(
            models.TargetKeyword(
                project_id=project.id,
                keyword=f"{prefix} {index}",
                is_active=is_active,
            )
        )
    db.commit()


def _create(client, project, keyword: str):
    return client.post(
        f"/api/v1/projects/{project.id}/monitoring/keywords",
        json={"keyword": keyword},
    )


# ---------------------------------------------------------------------------
# The cap exists in the capability matrix
# ---------------------------------------------------------------------------


def test_every_plan_declares_a_keyword_allowance() -> None:
    for plan in CANONICAL_PLAN_TYPES:
        assert (
            "max_tracked_keywords" in CAPABILITY_MATRIX[plan]
        ), f"'{plan}' declares no keyword allowance, so its keyword list is uncapped"
        assert isinstance(CAPABILITY_MATRIX[plan]["max_tracked_keywords"], int)


def test_keyword_allowance_mirrors_the_prompt_cap_ladder() -> None:
    assert keyword_allowances() == EXPECTED_KEYWORD_CAPS


def test_unknown_plan_falls_back_to_the_free_allowance() -> None:
    assert max_tracked_keywords("plan_does_not_exist") == EXPECTED_KEYWORD_CAPS["plan_starter"]


# ---------------------------------------------------------------------------
# Creation is refused at the cap, allowed under it
# ---------------------------------------------------------------------------


def test_create_succeeds_under_the_cap() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        _seed_keywords(db, project, 9)
        response = _create(client, project, "the tenth keyword")
        assert response.status_code == 201
        assert count_active_keywords(db, project.id) == 10
    finally:
        _cleanup(db)


def test_create_is_refused_at_the_cap_with_an_actionable_message() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        _seed_keywords(db, project, 10)
        response = _create(client, project, "one keyword too many")

        assert response.status_code == 402
        detail = response.json()["detail"]
        assert "Keyword limit reached" in detail
        assert "Standard" in detail
        assert "10 keywords" in detail
        assert "10 are in use" in detail
        assert "0 remain" in detail
        assert "Specialist" in detail
        assert "50" in detail
        assert "—" not in detail

        # The refusal must not have created anything.
        assert count_active_keywords(db, project.id) == 10
    finally:
        _cleanup(db)


def test_inactive_keywords_do_not_consume_the_cap() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        _seed_keywords(db, project, 10, is_active=False, prefix="retired")
        response = _create(client, project, "a fresh keyword")
        assert response.status_code == 201
        assert count_active_keywords(db, project.id) == 1
    finally:
        _cleanup(db)


def test_reactivating_a_soft_deleted_keyword_at_the_cap_is_refused() -> None:
    """The hole: reactivation is a create as far as the sync cost is concerned."""
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        _seed_keywords(db, project, 10)
        db.add(models.TargetKeyword(project_id=project.id, keyword="retired", is_active=False))
        db.commit()

        response = _create(client, project, "retired")
        assert response.status_code == 402
        assert "Keyword limit reached" in response.json()["detail"]

        retired = (
            db.query(models.TargetKeyword)
            .filter(
                models.TargetKeyword.project_id == project.id,
                models.TargetKeyword.keyword == "retired",
            )
            .one()
        )
        db.refresh(retired)
        assert retired.is_active is False
        assert count_active_keywords(db, project.id) == 10
    finally:
        _cleanup(db)


def test_reactivating_under_the_cap_still_works() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        db.add(models.TargetKeyword(project_id=project.id, keyword="retired", is_active=False))
        db.commit()

        response = _create(client, project, "retired")
        assert response.status_code == 201
        assert response.json()["keyword"] == "retired"
        assert count_active_keywords(db, project.id) == 1
    finally:
        _cleanup(db)


def test_an_active_duplicate_is_still_a_conflict_not_a_cap_refusal() -> None:
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        _seed_keywords(db, project, 9)
        db.add(models.TargetKeyword(project_id=project.id, keyword="already tracked"))
        db.commit()

        response = _create(client, project, "already tracked")
        assert response.status_code == 409
    finally:
        _cleanup(db)


def test_top_plan_refusal_does_not_promise_an_upgrade_that_does_not_exist() -> None:
    db, _user, project = _build_project_context(plan_type="plan_executive")
    try:
        assert resolve_project_plan(project) == "plan_executive"
        _seed_keywords(db, project, EXPECTED_KEYWORD_CAPS["plan_executive"])

        with pytest.raises(Exception) as excinfo:
            enforce_keyword_limit(db, project)

        detail = str(excinfo.value.detail)
        assert "Executive" in detail
        assert "200 keywords" in detail
        assert "upgrade" not in detail.lower()
    finally:
        _cleanup(db)


def test_a_project_without_an_entitled_subscription_uses_the_free_cap() -> None:
    client, db, user, project = _build_client(plan_type="plan_standard")
    try:
        subscription = (
            db.query(models.Subscription).filter(models.Subscription.user_id == user.id).one()
        )
        subscription.status = "canceled"
        db.commit()

        assert resolve_project_plan(project) == "plan_starter"
        _seed_keywords(db, project, EXPECTED_KEYWORD_CAPS["plan_starter"])

        response = _create(client, project, "one keyword too many")
        assert response.status_code == 402
        assert "Starter" in response.json()["detail"]
        assert "5 keywords" in response.json()["detail"]
    finally:
        _cleanup(db)


# ---------------------------------------------------------------------------
# Grandfathering: nothing existing is cut off
# ---------------------------------------------------------------------------


def test_a_project_over_the_cap_keeps_every_keyword_and_still_syncs(monkeypatch) -> None:
    """Enforcement is on creation only (SIGV2-1150, AC4).

    A project that already tracks more keywords than its plan now allows keeps
    all of them, the list endpoint still returns all of them, and
    ``sync_serp_data`` still checks all of them: the worker's query is driven by
    ``is_active`` alone and consults no plan.
    """
    client, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        over_cap = EXPECTED_KEYWORD_CAPS["plan_standard"] + 2
        _seed_keywords(db, project, over_cap, prefix="grandfathered")

        listed = client.get(f"/api/v1/projects/{project.id}/monitoring/keywords")
        assert listed.status_code == 200
        assert len(listed.json()) == over_cap
        assert count_active_keywords(db, project.id) == over_cap

        from app.services.aeo.dataforseo_service import DataForSEOService

        service = DataForSEOService(login="test", password="test")
        checked: list[str] = []
        monkeypatch.setattr(
            DataForSEOService,
            "check_keyword",
            lambda self, db_, keyword, target_domain: checked.append(keyword.keyword),
        )

        synced = service.sync_serp_data(
            db=db,
            project_id=project.id,
            target_domain="northwind.example",
        )
        assert synced == over_cap
        assert len(checked) == over_cap

        # Only a new keyword is refused, and nothing was deactivated by it.
        refused = _create(client, project, "a brand new keyword")
        assert refused.status_code == 402
        assert count_active_keywords(db, project.id) == over_cap
    finally:
        _cleanup(db)
