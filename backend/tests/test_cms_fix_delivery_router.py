from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base, get_db
from routers.cms_router import get_current_user, router as cms_router
from services import cms_fix_delivery_service
from services.cms_adapters.base_adapter import CMSChangePreview, CMSPushResult


class _StubAdapter:
    def __init__(self) -> None:
        self.push_count = 0

    async def test_connection(self) -> bool:
        return True

    async def preview_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
    ) -> CMSChangePreview:
        return CMSChangePreview(
            page_url=page_url,
            field=field,
            current_value="<meta name='description' content='legacy' />",
            proposed_value=new_value,
            diff_html="<section>diff</section>",
        )

    async def push_change(
        self,
        *,
        page_url: str,
        field: str,
        new_value: str,
        approved_by: int,
    ) -> CMSPushResult:
        self.push_count += 1
        return CMSPushResult(
            success=True,
            page_url=page_url,
            revision_id=f"rev-{self.push_count}",
            error_message=None,
        )

    async def rollback_change(self, *, revision_id: str) -> bool:
        return bool(revision_id)


@pytest.fixture
def app_client():
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(cms_router)

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    def seed_data(plan_type: str) -> tuple[models.User, models.Project, models.ProjectTask]:
        user = models.User(
            email=f"cms-{plan_type}@example.com",
            hashed_password="x",
            role="user",
            credits=100,
            notifications_enabled=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        db.add(
            models.Subscription(
                user_id=user.id,
                stripe_customer_id=f"cus_{plan_type}",
                stripe_subscription_id=f"sub_{plan_type}",
                plan_type=plan_type,
                status="active",
            )
        )
        db.commit()

        workspace = models.Workspace(name=f"CMS Workspace {plan_type}", owner_id=user.id)
        db.add(workspace)
        db.commit()
        db.refresh(workspace)

        project = models.Project(
            workspace_id=workspace.id,
            name="CMS Project",
            domain_url="https://example.com",
        )
        db.add(project)
        db.commit()
        db.refresh(project)

        task = models.ProjectTask(
            project_id=project.id,
            created_by_user_id=user.id,
            title="Inject schema",
            description="<script type='application/ld+json'>{}</script>",
            status=models.ProjectTaskStatus.TODO,
            priority=models.ProjectTaskPriority.HIGH,
            origin=models.ProjectTaskOrigin.MANUAL,
            category="Technical",
            sort_order=100,
            schema_version="1",
            metadata_json={
                "ai_code_snippet": '<script type=\'application/ld+json\'>{"@type":"FAQPage"}</script>'
            },
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return user, project, task

    state: dict[str, object] = {}

    def set_context(*, plan_type: str) -> None:
        user, project, task = seed_data(plan_type)
        state["user"] = user
        state["project"] = project
        state["task"] = task

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

    try:
        yield client, db, set_context, state
    finally:
        app.dependency_overrides.clear()
        bind = db.get_bind()
        db.close()
        Base.metadata.drop_all(bind=bind)


def _create_connection(client: TestClient, project_id: int) -> int:
    response = client.post(
        f"/api/v1/projects/{project_id}/cms/connect",
        json={
            "cms_type": "wordpress",
            "site_url": "https://cms.example.com",
            "credentials": {"username": "admin", "app_password": "secret"},
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def test_preview_requires_plan_executive_plan(app_client) -> None:
    client, _db, set_context, state = app_client
    set_context(plan_type="plan_specialist")
    project = state["project"]
    task = state["task"]
    connection_id = _create_connection(client, project.id)

    response = client.get(
        f"/api/v1/tasks/{task.id}/cms/preview",
        params={
            "connection_id": connection_id,
            "page_url": "https://example.com/pricing",
            "field": "head_scripts",
        },
    )

    assert response.status_code == 402
    assert "Executive" in response.json()["detail"]
    assert "X-Request-ID" in response.headers


def test_push_and_rollback_create_immutable_logs(app_client, monkeypatch) -> None:
    client, db, set_context, state = app_client
    set_context(plan_type="plan_executive")
    project = state["project"]
    task = state["task"]
    connection_id = _create_connection(client, project.id)

    stub = _StubAdapter()
    monkeypatch.setattr(cms_fix_delivery_service, "get_cms_adapter", lambda _connection: stub)

    preview_response = client.get(
        f"/api/v1/tasks/{task.id}/cms/preview",
        params={
            "connection_id": connection_id,
            "page_url": "https://example.com/pricing",
            "field": "head_scripts",
        },
    )
    assert preview_response.status_code == 200
    preview_payload = preview_response.json()

    push_response = client.post(
        f"/api/v1/tasks/{task.id}/cms/push",
        json={
            "connection_id": connection_id,
            "page_url": "https://example.com/pricing",
            "field": "head_scripts",
            "confirmation_token": preview_payload["confirmation_token"],
        },
    )
    assert push_response.status_code == 200
    push_payload = push_response.json()
    assert push_payload["success"] is True
    assert push_payload["deployment_log"]["status"] == "pushed"

    db_task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task.id).first()
    assert db_task is not None
    assert db_task.status == models.ProjectTaskStatus.DONE

    rollback_response = client.post(
        f"/api/v1/tasks/{task.id}/cms/rollback",
        json={
            "connection_id": connection_id,
            "deployment_log_id": push_payload["deployment_log"]["id"],
        },
    )
    assert rollback_response.status_code == 200
    rollback_payload = rollback_response.json()
    assert rollback_payload["success"] is True
    assert rollback_payload["deployment_log"]["status"] == "rolled_back"

    db_task = db.query(models.ProjectTask).filter(models.ProjectTask.id == task.id).first()
    assert db_task is not None
    assert db_task.status == models.ProjectTaskStatus.TODO

    logs_response = client.get(f"/api/v1/projects/{project.id}/cms/deployment-log")
    assert logs_response.status_code == 200
    logs = logs_response.json()
    assert len(logs) == 2
    statuses = [entry["status"] for entry in logs]
    assert "pushed" in statuses
    assert "rolled_back" in statuses


def test_confirmation_token_expiry() -> None:
    base_time = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)

    original_now = cms_fix_delivery_service._utcnow
    try:
        cms_fix_delivery_service._utcnow = lambda: base_time
        token = cms_fix_delivery_service.build_confirmation_token(
            task_id=1,
            connection_id=2,
            page_url="https://example.com/page",
            field="meta_title",
            value="New title",
            ttl_seconds=60,
        )
        cms_fix_delivery_service._utcnow = lambda: base_time + timedelta(seconds=120)
        with pytest.raises(ValueError, match="expired"):
            cms_fix_delivery_service.validate_confirmation_token(
                token=token,
                task_id=1,
                connection_id=2,
                page_url="https://example.com/page",
                field="meta_title",
                value="New title",
            )
    finally:
        cms_fix_delivery_service._utcnow = original_now
