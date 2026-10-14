from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from routers.api_router import (
    ClaimFeedbackRequest,
    delete_claim_feedback,
    get_claim_feedback_summary,
    get_previous_audit_feedback,
    list_claim_feedback,
    submit_claim_feedback,
)


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return factory(), engine


def _user(db: Session, email: str) -> models.User:
    user = models.User(email=email, hashed_password="x", role="user", credits=100)
    db.add(user)
    db.flush()
    return user


def _workspace(db: Session, owner: models.User) -> models.Workspace:
    workspace = models.Workspace(name=f"Workspace {owner.id}", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    return workspace


def _project(db: Session, workspace: models.Workspace, name: str) -> models.Project:
    project = models.Project(
        workspace_id=workspace.id,
        name=name,
        domain_url=f"https://{name.lower()}.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()
    return project


def _audit(db: Session, user: models.User, project: models.Project, url: str) -> models.Audit:
    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=url,
        geo_score=70,
        seo_score=70,
        aeo_score=70,
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.flush()
    return audit


def _membership(
    db: Session,
    workspace: models.Workspace,
    user: models.User,
    role: models.WorkspaceRole,
    project: models.Project | None = None,
) -> models.WorkspaceUser:
    membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=user.id,
        role=role,
    )
    db.add(membership)
    db.flush()
    if project is not None:
        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project.id,
            )
        )
        db.flush()
    return membership


def _feedback_body() -> ClaimFeedbackRequest:
    return ClaimFeedbackRequest(
        claim_key="claim:one",
        claim_text="The claim",
        feedback_type="agree",
    )


def test_cross_tenant_feedback_reads_return_not_found() -> None:
    db, engine = _build_db()
    try:
        owner = _user(db, "owner@example.com")
        workspace = _workspace(db, owner)
        project = _project(db, workspace, "Alpha")
        audit = _audit(db, owner, project, "https://alpha.example")
        outsider = _user(db, "outsider@example.com")
        db.commit()

        for operation in (
            lambda: list_claim_feedback(audit.id, outsider, db, False),
            lambda: get_claim_feedback_summary(audit.id, outsider, db),
            lambda: get_previous_audit_feedback(audit.id, outsider, db),
        ):
            with pytest.raises(HTTPException) as exc:
                operation()
            assert exc.value.status_code == 404
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.mark.parametrize(
    "role", [models.WorkspaceRole.VIEWER, models.WorkspaceRole.CLIENT_READONLY]
)
def test_read_only_roles_cannot_submit_feedback(role: models.WorkspaceRole) -> None:
    db, engine = _build_db()
    try:
        owner = _user(db, "owner@example.com")
        workspace = _workspace(db, owner)
        project = _project(db, workspace, "Alpha")
        audit = _audit(db, owner, project, "https://alpha.example")
        reader = _user(db, f"{role.value.lower()}@example.com")
        _membership(db, workspace, reader, role, project)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            submit_claim_feedback(audit.id, _feedback_body(), reader, db)
        assert exc.value.status_code == 404
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_unassigned_manager_cannot_submit_but_assigned_manager_can() -> None:
    db, engine = _build_db()
    try:
        owner = _user(db, "owner@example.com")
        workspace = _workspace(db, owner)
        project = _project(db, workspace, "Alpha")
        audit = _audit(db, owner, project, "https://alpha.example")
        unassigned = _user(db, "unassigned@example.com")
        _membership(db, workspace, unassigned, models.WorkspaceRole.MANAGER)
        assigned = _user(db, "assigned@example.com")
        _membership(db, workspace, assigned, models.WorkspaceRole.MANAGER, project)
        db.commit()

        with pytest.raises(HTTPException) as exc:
            submit_claim_feedback(audit.id, _feedback_body(), unassigned, db)
        assert exc.value.status_code == 404

        response = submit_claim_feedback(audit.id, _feedback_body(), assigned, db)
        assert response["audit_id"] == audit.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_delete_feedback_must_match_audit_id() -> None:
    db, engine = _build_db()
    try:
        owner = _user(db, "owner@example.com")
        workspace = _workspace(db, owner)
        project = _project(db, workspace, "Alpha")
        audit_one = _audit(db, owner, project, "https://alpha.example/one")
        audit_two = _audit(db, owner, project, "https://alpha.example/two")
        db.commit()
        created = submit_claim_feedback(audit_one.id, _feedback_body(), owner, db)

        with pytest.raises(HTTPException) as exc:
            delete_claim_feedback(audit_two.id, created["id"], owner, db)
        assert exc.value.status_code == 404
        assert (
            db.query(models.ClaimFeedback).filter(models.ClaimFeedback.id == created["id"]).count()
            == 1
        )
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
