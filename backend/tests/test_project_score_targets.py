"""SIGV2-1006: per-project AIO/SEO score targets and gap projection.

Covers persisted targets through the project-settings boundary (AC1/AC5),
strict 0-100 integer validation with no partial writes (AC2), the
``gap = max(0, target - current)`` rule with null gap on unmeasured
scores (AC3), and consistency of the returned target view (AC4).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from routers.workspace_router import (
    ProjectCreateRequest,
    ProjectUpdateRequest,
    create_project_in_current_workspace,
    get_project,
    update_project,
)


def _build_db() -> tuple[Session, Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory(), engine


def _make_user(db: Session, email: str, *, plan: str = "plan_specialist") -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=50)
    db.add(user)
    db.flush()
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{user.id}",
            plan_type=plan,
            status="active",
        )
    )
    return user


def _create_project(db: Session, user: models.User, name: str = "Alpha"):
    return create_project_in_current_workspace(
        payload=ProjectCreateRequest(name=name, domain_url="alpha.example"),
        user=user,
        db=db,
    )


def _add_audit(
    db: Session,
    *,
    user: models.User,
    project_id: int,
    seo: float | None = None,
    geo: float = 0.0,
    aeo: float | None = None,
) -> models.Audit:
    audit = models.Audit(
        user_id=user.id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://alpha.example",
        seo_score=seo,
        geo_score=geo,
        aeo_score=aeo,
        full_report={},
        created_at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    db.add(audit)
    db.commit()
    return audit


# ---------------------------------------------------------------------------
# AC2: validation, no partial writes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 100])
def test_target_bounds_accepted(value: int) -> None:
    payload = ProjectUpdateRequest(aio_score_target=value, seo_score_target=value)
    assert payload.aio_score_target == value
    assert payload.seo_score_target == value


@pytest.mark.parametrize("value", [-1, 101, True, False, 75.5, "80", "high", [80], {"v": 80}])
def test_target_invalid_inputs_rejected(value) -> None:
    with pytest.raises(ValidationError):
        ProjectUpdateRequest(aio_score_target=value)
    with pytest.raises(ValidationError):
        ProjectUpdateRequest(seo_score_target=value)


def test_invalid_target_produces_no_partial_write() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])

        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(aio_score_target=60),
            user=user,
            db=db,
        )
        db.commit()

        # Any invalid sibling value must leave the row untouched. Validation
        # happens at request parsing, so construct the union-invalid payload
        # the same way FastAPI would reject it.
        with pytest.raises(ValidationError):
            ProjectUpdateRequest.model_validate(
                {"aio_score_target": 90, "seo_score_target": "not-a-number"}
            )

        project = db.get(models.Project, project_id)
        assert project.aio_score_target == 60
        assert project.seo_score_target is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# AC1/AC4: persistence and consistent target view
# ---------------------------------------------------------------------------


def test_targets_persist_and_round_trip_per_project() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        first = _create_project(db, user, "Alpha")
        second = _create_project(db, user, "Beta")
        first_id, second_id = int(first["id"]), int(second["id"])

        update_project(
            project_id=first_id,
            payload=ProjectUpdateRequest(aio_score_target=66, seo_score_target=71),
            user=user,
            db=db,
        )
        update_project(
            project_id=second_id,
            payload=ProjectUpdateRequest(aio_score_target=90),
            user=user,
            db=db,
        )

        reloaded_first = get_project(project_id=first_id, user=user, db=db)
        reloaded_second = get_project(project_id=second_id, user=user, db=db)
        assert reloaded_first["score_targets"]["aio"]["target"] == 66
        assert reloaded_first["score_targets"]["seo"]["target"] == 71
        # Second project keeps its own override on aio and the configured
        # default on seo - values are independent per project.
        assert reloaded_second["score_targets"]["aio"]["target"] == 90
        assert reloaded_second["score_targets"]["seo"]["target"] == 85
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_unset_targets_use_configured_defaults() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        payload = get_project(project_id=int(created["id"]), user=user, db=db)
        assert payload["score_targets"]["aio"]["target"] == 78
        assert payload["score_targets"]["seo"]["target"] == 85
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_clearing_target_restores_configured_default() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])
        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(aio_score_target=66),
            user=user,
            db=db,
        )
        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(aio_score_target=None),
            user=user,
            db=db,
        )
        payload = get_project(project_id=project_id, user=user, db=db)
        assert payload["score_targets"]["aio"]["target"] == 78
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# AC3: gap semantics
# ---------------------------------------------------------------------------


def test_gap_is_target_minus_current_for_aio() -> None:
    """AC3 example: AIO 62 against a 78 target reports a 16-point gap."""
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])
        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(aio_score_target=78, seo_score_target=78),
            user=user,
            db=db,
        )
        _add_audit(db, user=user, project_id=project_id, seo=76.0, geo=62.0, aeo=62.0)

        payload = get_project(project_id=project_id, user=user, db=db)
        aio = payload["score_targets"]["aio"]
        seo = payload["score_targets"]["seo"]
        assert aio["current"] == 62
        assert aio["gap"] == 16
        assert aio["measured_at"] is not None
        assert seo["current"] == 76.0
        assert seo["gap"] == 2.0
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_unmeasured_score_returns_null_gap() -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])
        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(aio_score_target=78, seo_score_target=78),
            user=user,
            db=db,
        )
        payload = get_project(project_id=project_id, user=user, db=db)
        for key in ("aio", "seo"):
            view = payload["score_targets"][key]
            assert view["current"] is None
            assert view["gap"] is None
            assert view["measured_at"] is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize("current,expected_gap", [(85.0, 0.0), (92.0, 0.0)])
def test_reached_and_exceeded_target_returns_zero_gap(current: float, expected_gap: float) -> None:
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])
        update_project(
            project_id=project_id,
            payload=ProjectUpdateRequest(seo_score_target=85),
            user=user,
            db=db,
        )
        _add_audit(db, user=user, project_id=project_id, seo=current, geo=50.0)
        payload = get_project(project_id=project_id, user=user, db=db)
        view = payload["score_targets"]["seo"]
        assert view["current"] == current
        assert view["gap"] == expected_gap
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_aio_current_uses_canonical_rollup() -> None:
    # audits.geo_score is NOT NULL, so AIO is always measured once an audit
    # exists: derive_aio weights aeo+geo, and a missing aeo falls back to geo.
    db, engine = _build_db()
    try:
        user = _make_user(db, "owner@example.com")
        created = _create_project(db, user)
        project_id = int(created["id"])
        _add_audit(db, user=user, project_id=project_id, seo=70.0, geo=50.0)
        payload = get_project(project_id=project_id, user=user, db=db)
        assert payload["score_targets"]["seo"]["current"] == 70.0
        assert payload["score_targets"]["aio"]["current"] == 50
        assert payload["score_targets"]["aio"]["gap"] == 28
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


# ---------------------------------------------------------------------------
# AC5: ownership and roles
# ---------------------------------------------------------------------------


def test_viewer_cannot_update_targets() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com")
        created = _create_project(db, owner)
        project_id = int(created["id"])
        workspace = db.query(models.Workspace).filter(models.Workspace.owner_id == owner.id).one()
        viewer = _make_user(db, "viewer@example.com")
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=viewer.id,
                role=models.WorkspaceRole.VIEWER,
            )
        )
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            update_project(
                project_id=project_id,
                payload=ProjectUpdateRequest(aio_score_target=66),
                user=viewer,
                db=db,
            )
        assert exc_info.value.status_code == 403
        assert db.get(models.Project, project_id).aio_score_target is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_foreign_tenant_cannot_read_or_write_targets() -> None:
    db, engine = _build_db()
    try:
        owner = _make_user(db, "owner@example.com")
        created = _create_project(db, owner)
        project_id = int(created["id"])
        foreign = _make_user(db, "foreign@example.com")

        with pytest.raises(HTTPException) as read_exc:
            get_project(project_id=project_id, user=foreign, db=db)
        assert read_exc.value.status_code in (403, 404)
        with pytest.raises(HTTPException) as write_exc:
            update_project(
                project_id=project_id,
                payload=ProjectUpdateRequest(aio_score_target=66),
                user=foreign,
                db=db,
            )
        assert write_exc.value.status_code in (403, 404)
        assert db.get(models.Project, project_id).aio_score_target is None
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
