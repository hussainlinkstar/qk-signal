"""API tests for the learnings loop (recommendation decisions) — Task 7.2.

Covers the happy path (accept / dismiss -> list) for an authorized user, plus
the security gates: VIEWER cannot write (403), and a user from another tenant
cannot read/write a project they do not belong to (BFLA / tenant isolation).

Sync sqlite ``TestClient`` harness mirroring ``test_brand_facts_api``.
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
from app.services.learnings_service import compute_action_fingerprint
from auth.security import get_current_user_from_token as get_current_user
from database import Base
from main import app, get_db


def _build_harness():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    owner = models.User(email="owner@example.com", hashed_password="x", role="user")
    viewer = models.User(email="viewer@example.com", hashed_password="x", role="user")
    outsider = models.User(email="outsider@example.com", hashed_password="x", role="user")
    db.add_all([owner, viewer, outsider])
    db.commit()
    for u in (owner, viewer, outsider):
        db.refresh(u)

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
    return f"/api/v1/projects/{project_id}/recommendation-decisions"


def test_record_accept_and_dismiss_happy_path():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner

        accept = client.post(
            _base(project.id),
            json={"action_text": "Add FAQPage schema", "decision": "accepted"},
        )
        assert accept.status_code == 201, accept.text
        accepted = accept.json()
        assert accepted["decision"] == "accepted"
        assert accepted["action_fingerprint"] == compute_action_fingerprint("Add FAQPage schema")
        assert accepted["decided_by"] == owner.id

        dismiss = client.post(
            _base(project.id),
            json={
                "action_text": "Rewrite the meta description",
                "decision": "dismissed",
                "note": "Not relevant",
            },
        )
        assert dismiss.status_code == 201, dismiss.text
        assert dismiss.json()["decision"] == "dismissed"
        assert dismiss.json()["note"] == "Not relevant"

        listing = client.get(_base(project.id))
        assert listing.status_code == 200
        rows = listing.json()
        assert len(rows) == 2
        decisions = {row["action_fingerprint"]: row["decision"] for row in rows}
        assert decisions[compute_action_fingerprint("Add FAQPage schema")] == "accepted"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_action_text_persists_readable_label():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        # Control chars + surrounding whitespace must be stripped (RAW, not html-escaped).
        resp = client.post(
            _base(project.id),
            json={
                "action_text": "  Add <FAQPage> schema\t\x00to pricing  ",
                "decision": "accepted",
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["action_label"] == "Add <FAQPage> schema to pricing"
        # Fingerprint logic is unchanged (derived from the raw action_text).
        assert body["action_fingerprint"] == compute_action_fingerprint(
            "  Add <FAQPage> schema\t\x00to pricing  "
        )

        rows = client.get(_base(project.id)).json()
        assert rows[0]["action_label"] == "Add <FAQPage> schema to pricing"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_explicit_label_override_used():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        resp = client.post(
            _base(project.id),
            json={
                "action_text": "Add FAQPage schema",
                "action_label": "Custom readable label",
                "decision": "accepted",
            },
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["action_label"] == "Custom readable label"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_fingerprint_only_path_has_null_label():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        fp = compute_action_fingerprint("Some action")
        resp = client.post(
            _base(project.id),
            json={"action_fingerprint": fp, "decision": "dismissed"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["action_label"] is None
        assert resp.json()["action_fingerprint"] == fp
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_record_decision_upsert_on_fingerprint():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        first = client.post(
            _base(project.id),
            json={"action_text": "Add FAQPage schema", "decision": "accepted"},
        )
        assert first.status_code == 201
        second = client.post(
            _base(project.id),
            json={"action_text": "Add FAQPage schema", "decision": "dismissed"},
        )
        assert second.status_code == 201
        assert second.json()["id"] == first.json()["id"]

        listing = client.get(_base(project.id)).json()
        assert len(listing) == 1
        assert listing[0]["decision"] == "dismissed"
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_explicit_fingerprint_accepted():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        fp = compute_action_fingerprint("Some action")
        resp = client.post(
            _base(project.id),
            json={"action_fingerprint": fp, "decision": "dismissed"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["action_fingerprint"] == fp
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_viewer_cannot_write():
    client, db, state, _owner, viewer, _outsider, project = _build_harness()
    try:
        state["user"] = viewer
        resp = client.post(
            _base(project.id),
            json={"action_text": "Add FAQPage schema", "decision": "dismissed"},
        )
        assert resp.status_code == 403, resp.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cross_tenant_access_denied():
    client, db, state, _owner, _viewer, outsider, project = _build_harness()
    try:
        state["user"] = outsider
        read = client.get(_base(project.id))
        assert read.status_code == 403, read.text
        write = client.post(
            _base(project.id),
            json={"action_text": "Injected", "decision": "dismissed"},
        )
        assert write.status_code == 403, write.text
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_invalid_decision_rejected():
    client, db, state, owner, _viewer, _outsider, project = _build_harness()
    try:
        state["user"] = owner
        bad = client.post(
            _base(project.id),
            json={"action_text": "Add FAQPage schema", "decision": "nonsense"},
        )
        assert bad.status_code == 422
        missing = client.post(
            _base(project.id),
            json={"decision": "accepted"},
        )
        assert missing.status_code == 422
    finally:
        app.dependency_overrides.clear()
        db.close()
