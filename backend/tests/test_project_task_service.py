from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
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
from routers.workspace_router import (
    ProjectTaskCreateRequest,
    ProjectTaskReorderColumnRequest,
    ProjectTaskReorderRequest,
    ProjectTaskUpdateRequest,
    create_project_task,
    delete_project_task,
    get_project_task_impact,
    list_project_tasks,
    reorder_project_tasks,
    update_project_task,
)
from services.project_task_service import build_project_task_impact_payload, sync_project_tasks


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


def _seed_project(db: Session) -> tuple[models.User, models.Workspace, models.Project]:
    owner = models.User(
        email="tasks-owner@example.com", hashed_password="x", role="user", credits=20
    )
    db.add(owner)
    db.flush()

    workspace = models.Workspace(name="Task Ops", owner_id=owner.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name="Client North",
        domain_url="https://client-north.example",
        target_country="US",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(owner)
    db.refresh(workspace)
    db.refresh(project)
    return owner, workspace, project


def _create_audit(
    db: Session,
    *,
    user_id: int,
    project_id: int,
    created_at: datetime,
    scores: tuple[float, float, float],
    suggestions: list[dict[str, object]] | None = None,
) -> models.Audit:
    audit = models.Audit(
        user_id=user_id,
        project_id=project_id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://client-north.example",
        seo_score=scores[0],
        geo_score=scores[1],
        aeo_score=scores[2],
        full_report={
            "metadata": {"audit_outcome": "completed"},
            "suggestions": suggestions or [],
        },
        created_at=created_at,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def test_sync_project_tasks_backfills_history_and_builds_impact_payload() -> None:
    db, engine = _build_db()
    try:
        owner, _workspace, project = _seed_project(db)
        audit_1 = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            created_at=datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc),
            scores=(50, 45, 40),
            suggestions=[
                {
                    "title": "Add schema markup",
                    "action": "Ship FAQ schema.",
                    "priority": 1,
                    "category": "Technical",
                },
                {
                    "title": "Expand FAQ coverage",
                    "action": "Answer commercial objections.",
                    "priority": 2,
                    "category": "Content",
                },
            ],
        )
        audit_2 = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            created_at=datetime(2026, 1, 24, 9, 0, tzinfo=timezone.utc),
            scores=(58, 52, 48),
            suggestions=[
                {
                    "title": "Add schema markup",
                    "action": "Ship FAQ schema.",
                    "priority": 1,
                    "category": "Technical",
                },
            ],
        )
        audit_3 = _create_audit(
            db,
            user_id=owner.id,
            project_id=project.id,
            created_at=datetime(2026, 2, 10, 9, 0, tzinfo=timezone.utc),
            scores=(66, 60, 59),
            suggestions=[
                {
                    "title": "Refresh internal linking",
                    "action": "Support high-intent pages.",
                    "priority": 2,
                    "category": "Technical",
                },
            ],
        )

        tasks = sync_project_tasks(db, project_id=project.id)

        assert len(tasks) == 3

        tasks_by_title = {task.title: task for task in tasks}
        schema_task = tasks_by_title["Add schema markup"]
        faq_task = tasks_by_title["Expand FAQ coverage"]
        links_task = tasks_by_title["Refresh internal linking"]

        assert schema_task.status == models.ProjectTaskStatus.DONE
        assert schema_task.source_audit_id == audit_1.id
        assert schema_task.verification_audit_id == audit_3.id
        assert schema_task.resolution_source == models.ProjectTaskResolutionSource.AUDIT_VALIDATED

        assert faq_task.status == models.ProjectTaskStatus.DONE
        assert faq_task.source_audit_id == audit_1.id
        assert faq_task.verification_audit_id == audit_2.id

        assert links_task.status == models.ProjectTaskStatus.TODO
        assert links_task.source_audit_id == audit_3.id

        impact_payload = build_project_task_impact_payload(db, project_id=project.id)
        assert impact_payload["summary"]["resolved_count"] == 2
        assert impact_payload["summary"]["validated_count"] == 2
        assert impact_payload["summary"]["strongest_metric"] == "aeo"
        assert any(
            item["task_id"] == schema_task.id and item["delta"]["seo"] == pytest.approx(16.0)
            for item in impact_payload["items"]
        )
        assert any(
            item["task_id"] == faq_task.id and item["delta"]["geo"] == pytest.approx(7.0)
            for item in impact_payload["items"]
        )
    finally:
        _cleanup(db, engine)


def test_project_task_crud_reorder_and_delete_flow() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project(db)
        editor = models.User(
            email="editor@example.com", hashed_password="x", role="user", credits=0
        )
        db.add(editor)
        db.flush()
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=editor.id,
                role=models.WorkspaceRole.EDITOR,
            )
        )
        db.commit()
        db.refresh(editor)

        created = create_project_task(
            project_id=project.id,
            payload=ProjectTaskCreateRequest(
                title="Prepare implementation checklist",
                description="Turn audit insights into an execution list.",
                assigned_to_user_id=editor.id,
                priority="high",
            ),
            user=owner,
            db=db,
        )
        assert created["assigned_to_user_id"] == editor.id
        assert created["status"] == "todo"

        updated = update_project_task(
            project_id=project.id,
            task_id=created["id"],
            payload=ProjectTaskUpdateRequest(
                status="in_progress",
                due_date=date(2026, 3, 15),
            ),
            user=owner,
            db=db,
        )
        assert updated["status"] == "in_progress"
        assert updated["due_date"] == "2026-03-15"

        board = list_project_tasks(project_id=project.id, user=owner, db=db)
        assert board["summary"]["in_progress"] == 1
        assert board["can_edit"] is True

        reordered = reorder_project_tasks(
            project_id=project.id,
            payload=ProjectTaskReorderRequest(
                columns=[
                    ProjectTaskReorderColumnRequest(status="todo", task_ids=[]),
                    ProjectTaskReorderColumnRequest(status="in_progress", task_ids=[]),
                    ProjectTaskReorderColumnRequest(status="done", task_ids=[created["id"]]),
                ]
            ),
            user=owner,
            db=db,
        )
        assert reordered["summary"]["done"] == 1

        impact = get_project_task_impact(project_id=project.id, user=owner, db=db)
        assert impact["summary"]["resolved_count"] == 1
        assert impact["summary"]["pending_validation_count"] == 1

        delete_project_task(project_id=project.id, task_id=created["id"], user=owner, db=db)
        refreshed = list_project_tasks(project_id=project.id, user=owner, db=db)
        assert refreshed["tasks"] == []
    finally:
        _cleanup(db, engine)


def test_project_task_board_is_read_only_for_client_portal_members() -> None:
    db, engine = _build_db()
    try:
        owner, workspace, project = _seed_project(db)
        client_user = models.User(
            email="client@example.com", hashed_password="x", role="user", credits=0
        )
        db.add(client_user)
        db.flush()
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=client_user.id,
            role=models.WorkspaceRole.CLIENT_READONLY,
        )
        db.add(membership)
        db.flush()
        db.add(
            models.WorkspaceUserProjectAccess(
                workspace_user_id=membership.id,
                project_id=project.id,
            )
        )
        db.commit()
        db.refresh(client_user)

        board = list_project_tasks(project_id=project.id, user=client_user, db=db)
        assert board["can_edit"] is False

        with pytest.raises(HTTPException) as exc_info:
            create_project_task(
                project_id=project.id,
                payload=ProjectTaskCreateRequest(title="Client should not create"),
                user=client_user,
                db=db,
            )
        assert exc_info.value.status_code == 403
    finally:
        _cleanup(db, engine)
