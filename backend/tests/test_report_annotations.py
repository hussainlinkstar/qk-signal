from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

import models
from database import Base
from routers.portal_router import (
    create_portal_audit_annotation_reply,
    list_portal_audit_annotations,
)
from routers.workspace_router import (
    create_audit_annotation,
    list_audit_annotations,
    remove_audit_annotation,
    update_audit_annotation,
)
from schemas.annotations import AnnotationCreateRequest, AnnotationUpdateRequest
from services.email_service import EmailService
from services.workspace_rbac import attach_portal_access_context


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


def _seed_workspace(db: Session) -> dict[str, object]:
    owner = models.User(email="owner@example.com", hashed_password="x", role="user", credits=10)
    editor = models.User(email="editor@example.com", hashed_password="x", role="user", credits=0)
    viewer = models.User(email="viewer@example.com", hashed_password="x", role="user", credits=0)
    client = models.User(email="client@example.com", hashed_password="x", role="user", credits=0)
    db.add_all([owner, editor, viewer, client])
    db.flush()

    workspace = models.Workspace(name="Annotation Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    editor_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=editor.id,
        role=models.WorkspaceRole.EDITOR,
    )
    viewer_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=viewer.id,
        role=models.WorkspaceRole.VIEWER,
    )
    client_membership = models.WorkspaceUser(
        workspace_id=workspace.id,
        user_id=client.id,
        role=models.WorkspaceRole.CLIENT_READONLY,
    )
    db.add_all([editor_membership, viewer_membership, client_membership])
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Northwind",
        domain_url="https://northwind.example",
        language="en",
        target_country="US",
    )
    db.add(project)
    db.flush()

    db.add(
        models.WorkspaceUserProjectAccess(
            workspace_user_id=client_membership.id,
            project_id=project.id,
        )
    )

    audit = models.Audit(
        user_id=owner.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url=project.domain_url,
        geo_score=61,
        seo_score=64,
        aeo_score=66,
        full_report={
            "metadata": {"audit_outcome": "completed"},
            "prioritized_actions": [
                {
                    "title": "Expand comparison pages with structured data",
                    "description": "Ship FAQ and comparison schema on high-intent pages.",
                    "category": "Technical",
                },
                {
                    "title": "Strengthen entity-backed FAQs",
                    "description": "Answer commercial objections with cited proof points.",
                    "category": "Content",
                },
            ],
            "analysis": {
                "recommendations": [
                    "Refresh internal linking around the highest-intent pages.",
                ],
            },
        },
        created_at=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(owner)
    db.refresh(editor)
    db.refresh(viewer)
    db.refresh(client)
    db.refresh(workspace)
    db.refresh(project)
    db.refresh(audit)

    return {
        "owner": owner,
        "editor": editor,
        "viewer": viewer,
        "client": client,
        "workspace": workspace,
        "project": project,
        "audit": audit,
    }


def test_agency_annotation_crud_threading_and_soft_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    queued: list[str] = []
    try:
        seeded = _seed_workspace(db)
        owner = seeded["owner"]
        editor = seeded["editor"]
        viewer = seeded["viewer"]
        audit = seeded["audit"]

        monkeypatch.setattr(
            EmailService,
            "queue_template_email",
            lambda self, *, to_email, template_key, **kwargs: queued.append(
                f"{to_email}:{template_key}"
            )
            or None,
        )

        created = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="prioritized_actions[0]",
                content="Marked for the next sprint and safe to expose to the client.",
                visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
            ),
            user=owner,
            db=db,
        )

        reply = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                parent_id=created.id,
                content="Implementation has started and schema QA is blocked on content review.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=editor,
            db=db,
        )

        board = list_audit_annotations(audit_id=audit.id, user=viewer, db=db)
        assert board["total"] == 1
        assert (
            board["items"][0].content
            == "Marked for the next sprint and safe to expose to the client."
        )
        assert board["items"][0].replies[0].id == reply.id
        assert board["items"][0].source_recommendation_key is not None
        assert any(item.endswith(":annotation.created") for item in queued)
        assert any(item.endswith(":annotation.replied") for item in queued)

        updated = update_audit_annotation(
            audit_id=audit.id,
            annotation_id=created.id,
            payload=AnnotationUpdateRequest(
                content="Marked for the next sprint and queued for a client-visible launch note.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=owner,
            db=db,
        )
        assert (
            updated.content
            == "Marked for the next sprint and queued for a client-visible launch note."
        )
        assert updated.visibility == models.AnnotationVisibility.INTERNAL.value
        assert updated.replies[0].visibility == models.AnnotationVisibility.INTERNAL.value

        with pytest.raises(HTTPException) as viewer_create_exc:
            create_audit_annotation(
                audit_id=audit.id,
                payload=AnnotationCreateRequest(
                    section_path="prioritized_actions[1]",
                    content="Viewer should not create notes.",
                ),
                user=viewer,
                db=db,
            )
        assert viewer_create_exc.value.status_code == 403

        deleted = remove_audit_annotation(
            audit_id=audit.id,
            annotation_id=created.id,
            user=owner,
            db=db,
        )
        assert deleted.is_deleted is True
        board_after_delete = list_audit_annotations(
            audit_id=audit.id,
            section_path="prioritized_actions[0]",
            user=viewer,
            db=db,
        )
        assert board_after_delete["total"] == 1
        assert board_after_delete["items"][0].content == "[Deleted]"
        assert len(board_after_delete["items"][0].replies) == 1
    finally:
        _cleanup(db, engine)


def test_annotation_pagination_visibility_filter_and_leaf_delete_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        owner = seeded["owner"]
        viewer = seeded["viewer"]
        audit = seeded["audit"]

        monkeypatch.setattr(EmailService, "queue_template_email", lambda self, **kwargs: None)

        first = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="prioritized_actions[0]",
                content="Internal launch prep.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=owner,
            db=db,
        )
        second = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="prioritized_actions[1]",
                content="Client-ready narrative.",
                visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
            ),
            user=owner,
            db=db,
        )
        third = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="analysis.recommendations[0]",
                content="Cross-link with task board.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=owner,
            db=db,
        )
        remove_audit_annotation(
            audit_id=audit.id,
            annotation_id=third.id,
            user=owner,
            db=db,
        )

        page_one = list_audit_annotations(
            audit_id=audit.id,
            page=1,
            per_page=1,
            user=viewer,
            db=db,
        )
        page_two = list_audit_annotations(
            audit_id=audit.id,
            page=2,
            per_page=1,
            user=viewer,
            db=db,
        )
        client_visible_only = list_audit_annotations(
            audit_id=audit.id,
            visibility=models.AnnotationVisibility.CLIENT_VISIBLE.value,
            user=viewer,
            db=db,
        )

        assert first.id != second.id
        assert page_one["total"] == 2
        assert len(page_one["items"]) == 1
        assert page_one["has_more"] is True
        assert len(page_two["items"]) == 1
        assert page_two["has_more"] is False
        assert client_visible_only["total"] == 1
        assert client_visible_only["items"][0].id == second.id
    finally:
        _cleanup(db, engine)


def test_annotation_targets_include_canonical_recommendations_items() -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        owner = seeded["owner"]
        audit = seeded["audit"]
        audit.full_report = {
            "recommendations": {
                "items": [
                    {
                        "title": "Strengthen entity-backed FAQs",
                        "action": "Answer commercial objections with cited proof points.",
                        "category": "content",
                    }
                ]
            }
        }
        db.add(audit)
        db.commit()
        db.refresh(audit)

        created = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="recommendations.items[0]",
                content="Canonical recommendation thread.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=owner,
            db=db,
        )

        assert created.section_path == "recommendations.items[0]"
        assert created.source_recommendation_key is not None
    finally:
        _cleanup(db, engine)


def test_portal_reply_constraints_and_visibility_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    db, engine = _build_db()
    try:
        seeded = _seed_workspace(db)
        owner = seeded["owner"]
        client = seeded["client"]
        project = seeded["project"]
        audit = seeded["audit"]

        monkeypatch.setattr(EmailService, "queue_template_email", lambda self, **kwargs: None)

        internal_annotation = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="prioritized_actions[0]",
                content="Internal status only.",
                visibility=models.AnnotationVisibility.INTERNAL,
            ),
            user=owner,
            db=db,
        )
        client_annotation = create_audit_annotation(
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                section_path="prioritized_actions[1]",
                content="Shared with the client for rollout planning.",
                visibility=models.AnnotationVisibility.CLIENT_VISIBLE,
            ),
            user=owner,
            db=db,
        )

        portal_user = attach_portal_access_context(db, user=client)

        portal_list = list_portal_audit_annotations(
            project_id=project.id,
            audit_id=audit.id,
            user=portal_user,
            db=db,
        )
        assert portal_list["total"] == 1
        assert portal_list["items"][0].id == client_annotation.id

        with pytest.raises(HTTPException) as no_parent_exc:
            create_portal_audit_annotation_reply(
                project_id=project.id,
                audit_id=audit.id,
                payload=AnnotationCreateRequest(content="Top-level portal note"),
                user=portal_user,
                db=db,
            )
        assert no_parent_exc.value.status_code == 400

        with pytest.raises(HTTPException) as internal_reply_exc:
            create_portal_audit_annotation_reply(
                project_id=project.id,
                audit_id=audit.id,
                payload=AnnotationCreateRequest(
                    parent_id=internal_annotation.id,
                    content="Client should not reply here.",
                ),
                user=portal_user,
                db=db,
            )
        assert internal_reply_exc.value.status_code == 403

        reply = create_portal_audit_annotation_reply(
            project_id=project.id,
            audit_id=audit.id,
            payload=AnnotationCreateRequest(
                parent_id=client_annotation.id,
                content="We have scheduled this for the next release train.",
            ),
            user=portal_user,
            db=db,
        )
        assert reply.parent_id == client_annotation.id
        assert reply.visibility == models.AnnotationVisibility.CLIENT_VISIBLE.value

        refreshed = list_portal_audit_annotations(
            project_id=project.id,
            audit_id=audit.id,
            section_path="prioritized_actions[1]",
            user=portal_user,
            db=db,
        )
        assert (
            refreshed["items"][0].replies[0].content
            == "We have scheduled this for the next release train."
        )
    finally:
        _cleanup(db, engine)
