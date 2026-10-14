"""API tests for per-project brand facts CRUD (Task 6.2).

Covers the happy path (create -> list -> delete) for an authorized user, and
the security gates: VIEWER cannot write (403), and a user from another tenant
cannot read/write a project they do not belong to (BFLA / tenant isolation).

Sync sqlite ``TestClient`` harness mirroring ``test_workspace_role_mode_api``.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db

PLAN_WITH_GUARDRAILS = "plan_executive"


def _seed_subscription(db, user: models.User, suffix: str) -> None:
    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_{suffix}",
            plan_type=PLAN_WITH_GUARDRAILS,
            status="active",
        )
    )
    db.commit()


def _build_harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    owner = models.User(
        email="owner@example.com",
        hashed_password="x",
        role="user",
    )
    viewer = models.User(
        email="viewer@example.com",
        hashed_password="x",
        role="user",
    )
    outsider = models.User(
        email="outsider@example.com",
        hashed_password="x",
        role="user",
    )
    db.add_all([owner, viewer, outsider])
    db.commit()
    for u in (owner, viewer, outsider):
        db.refresh(u)

    _seed_subscription(db, owner, "owner")
    _seed_subscription(db, viewer, "viewer")
    _seed_subscription(db, outsider, "outsider")

    workspace = models.Workspace(name="Owner WS", owner_id=owner.id)
    other_workspace = models.Workspace(name="Outsider WS", owner_id=outsider.id)
    db.add_all([workspace, other_workspace])
    db.commit()
    db.refresh(workspace)
    db.refresh(other_workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Project A",
        icp_roles=[],
        competitors_json=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # viewer is a VIEWER member of the owner workspace
    db.add(
        models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=viewer.id,
            role=models.WorkspaceRole.VIEWER,
        )
    )
    db.commit()

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
    return client, db, state, owner, viewer, outsider, project


def _base(project_id: int) -> str:
    return f"/api/v1/projects/{project_id}/brand-facts"


def test_create_list_delete_happy_path():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner

        create = client.post(
            _base(project.id),
            json={
                "kind": "claim",
                "statement": "We are ISO 27001 certified.",
                "is_forbidden": False,
            },
        )
        assert create.status_code == 201, create.text
        created = create.json()
        assert created["statement"] == "We are ISO 27001 certified."
        assert created["kind"] == "claim"
        assert created["is_forbidden"] is False
        fact_id = created["id"]

        listing = client.get(_base(project.id))
        assert listing.status_code == 200
        rows = listing.json()
        assert any(row["id"] == fact_id for row in rows)

        delete = client.delete(f"{_base(project.id)}/{fact_id}")
        assert delete.status_code == 204

        after = client.get(_base(project.id))
        assert all(row["id"] != fact_id for row in after.json())
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_statement_stored_raw_not_html_escaped():
    """HTML metacharacters are stored verbatim (escape at output, not storage).

    Markup-bearing text like ``Tom & Jerry <b>brand</b>`` must round-trip as the
    real characters — React escapes UI text nodes and the evidence anchor needs
    the genuine text. Control characters are still stripped/collapsed.
    """
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        statement = 'Tom & Jerry <b>brand</b> says "hi" > all\x07\tand\x00more'
        resp = client.post(
            _base(project.id),
            json={"kind": "fact", "statement": statement, "is_forbidden": False},
        )
        assert resp.status_code == 201, resp.text
        stored = resp.json()["statement"]
        # Raw metacharacters preserved (NOT &amp; / &lt; / &gt;).
        assert stored == 'Tom & Jerry <b>brand</b> says "hi" > all and more'
        assert "&amp;" not in stored
        assert "&lt;" not in stored
        assert "&gt;" not in stored
        # Control characters were stripped/collapsed.
        assert "\x00" not in stored
        assert "\x07" not in stored
        assert "\t" not in stored

        # Round-trips through the list endpoint unchanged.
        listing = client.get(_base(project.id))
        assert listing.status_code == 200
        assert any(row["statement"] == stored for row in listing.json())
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_viewer_cannot_write():
    client, db, state, _owner, viewer, _outsider, project = _build_harness()
    try:
        state["user"] = viewer
        resp = client.post(
            _base(project.id),
            json={"kind": "fact", "statement": "Founded in 2010.", "is_forbidden": False},
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cross_tenant_access_denied():
    client, db, state, _owner, _viewer, outsider, project = _build_harness()
    try:
        state["user"] = outsider
        # Read attempt on a project in a workspace the outsider does not belong to
        read = client.get(_base(project.id))
        assert read.status_code == 403, read.text
        # Write attempt likewise denied
        write = client.post(
            _base(project.id),
            json={"kind": "fact", "statement": "Injected.", "is_forbidden": False},
        )
        assert write.status_code == 403, write.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_invalid_input_rejected():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        empty = client.post(
            _base(project.id),
            json={"kind": "fact", "statement": "   ", "is_forbidden": False},
        )
        assert empty.status_code == 422
        bad_kind = client.post(
            _base(project.id),
            json={"kind": "nonsense", "statement": "Valid statement.", "is_forbidden": False},
        )
        assert bad_kind.status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()
