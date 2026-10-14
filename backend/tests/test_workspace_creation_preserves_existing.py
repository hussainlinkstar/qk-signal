"""SIGV2-1157 / SIGV2-1158 regression tests.

Two customer-facing guarantees are pinned here:

* the first workspace is named after the company entered at sign-up, and the
  owner can rename it afterwards;
* creating a second workspace only changes which workspace is *active*. It
  never moves, reassigns or hides the company and projects set up in the first
  one, and the first workspace stays listed and reachable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models  # noqa: E402
from database import Base  # noqa: E402
from routers.workspace_router import (  # noqa: E402
    WorkspaceCreateRequest,
    WorkspaceUpdateRequest,
    create_workspace,
    get_current_workspace,
    list_current_workspace_projects,
    list_user_workspaces,
    update_current_workspace,
)
from services.tenant_context import (  # noqa: E402
    reset_active_workspace_id,
    set_active_workspace_id,
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


def _cleanup(db: Session, engine: Engine) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


def _seed_owner(db: Session, *, company_name: str | None) -> models.User:
    owner = models.User(
        email="owner@raizn.example",
        hashed_password="x",
        role="user",
        credits=50,
        company_name=company_name,
    )
    db.add(owner)
    db.flush()
    db.add(
        models.Subscription(
            user_id=owner.id,
            stripe_customer_id="cus_multi_workspace",
            plan_type="plan_executive",
            status="active",
        )
    )
    db.commit()
    db.refresh(owner)
    return owner


class _ActiveWorkspace:
    """Stand-in for the ``X-Workspace-Id`` header the browser sends."""

    def __init__(self, workspace_id: int | None) -> None:
        self._workspace_id = workspace_id

    def __enter__(self) -> None:
        self._token = set_active_workspace_id(self._workspace_id)

    def __exit__(self, *_exc_info: object) -> None:
        reset_active_workspace_id(self._token)


def test_first_workspace_is_named_after_the_signup_company() -> None:
    """SIGV2-1157: the company entered at sign-up names the owner's workspace."""
    db, engine = _build_db()
    try:
        owner = _seed_owner(db, company_name="Raizn")

        with _ActiveWorkspace(None):
            workspace = get_current_workspace(user=owner, db=db)

        assert workspace["name"] == "Raizn Workspace"
    finally:
        _cleanup(db, engine)


def test_the_owner_can_rename_the_workspace() -> None:
    """SIGV2-1157: renaming is available to the workspace owner."""
    db, engine = _build_db()
    try:
        owner = _seed_owner(db, company_name="Raizn")

        with _ActiveWorkspace(None):
            created = get_current_workspace(user=owner, db=db)

        with _ActiveWorkspace(created["id"]):
            renamed = update_current_workspace(
                payload=WorkspaceUpdateRequest(name="Raizn"),
                user=owner,
                db=db,
            )

        assert renamed["name"] == "Raizn"
    finally:
        _cleanup(db, engine)


def test_creating_a_second_workspace_keeps_the_first_one_and_its_projects() -> None:
    """SIGV2-1158: a new workspace never hides or loses the earlier one."""
    db, engine = _build_db()
    try:
        owner = _seed_owner(db, company_name="Raizn")

        with _ActiveWorkspace(None):
            first = get_current_workspace(user=owner, db=db)

        project = models.Project(
            workspace_id=first["id"],
            name="Raizn",
            domain_url="https://raizn.example",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        with _ActiveWorkspace(first["id"]):
            second = create_workspace(
                payload=WorkspaceCreateRequest(name="Second Workspace"),
                user=owner,
                db=db,
            )

        assert second["id"] != first["id"]

        # Nothing moved: the project still belongs to the first workspace.
        db.refresh(project)
        assert project.workspace_id == first["id"]

        # The first workspace is still listed, with its project still counted.
        with _ActiveWorkspace(second["id"]):
            listed = list_user_workspaces(user=owner, db=db)
        by_id = {item["id"]: item for item in listed}
        assert set(by_id) == {first["id"], second["id"]}
        assert by_id[first["id"]]["name"] == first["name"]
        assert by_id[first["id"]]["project_count"] == 1
        assert by_id[second["id"]]["project_count"] == 0

        # The new workspace is correctly empty, the scoping is not weakened.
        with _ActiveWorkspace(second["id"]):
            second_projects = list_current_workspace_projects(user=owner, db=db)
        assert second_projects == []

        # Switching back reaches the original project again.
        with _ActiveWorkspace(first["id"]):
            first_projects = list_current_workspace_projects(user=owner, db=db)
        assert [item["name"] for item in first_projects] == ["Raizn"]
    finally:
        _cleanup(db, engine)


def test_creating_a_second_workspace_does_not_change_the_default_workspace() -> None:
    """Without an explicit selection the owner still lands on the first workspace."""
    db, engine = _build_db()
    try:
        owner = _seed_owner(db, company_name="Raizn")

        with _ActiveWorkspace(None):
            first = get_current_workspace(user=owner, db=db)

        with _ActiveWorkspace(first["id"]):
            create_workspace(
                payload=WorkspaceCreateRequest(name="Second Workspace"),
                user=owner,
                db=db,
            )

        with _ActiveWorkspace(None):
            current = get_current_workspace(user=owner, db=db)

        assert current["id"] == first["id"]
    finally:
        _cleanup(db, engine)


def test_a_second_workspace_is_refused_without_the_multi_workspace_plan() -> None:
    """Scoping and entitlements stay intact: no plan, no extra workspace."""
    from fastapi import HTTPException

    db, engine = _build_db()
    try:
        owner = models.User(
            email="starter@example.com",
            hashed_password="x",
            role="user",
            credits=5,
            company_name="Starter Co",
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)

        with pytest.raises(HTTPException) as excinfo:
            create_workspace(
                payload=WorkspaceCreateRequest(name="Second Workspace"),
                user=owner,
                db=db,
            )

        assert excinfo.value.status_code == 403
    finally:
        _cleanup(db, engine)
