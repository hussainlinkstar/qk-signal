from __future__ import annotations

from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from database import get_db
from routers.entity_authority_router import (
    get_current_user,
    router as entity_authority_router,
)


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(entity_authority_router)
    return app


def _build_client(
    *,
    plan_type: str = "plan_specialist",
    workspace_role: models.WorkspaceRole | None = None,
) -> tuple[TestClient, FastAPI, object, models.User, models.Project]:
    app = _build_test_app()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()

    user = models.User(
        email=f"entity-authority-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=50,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    subscription = models.Subscription(
        user_id=user.id,
        stripe_customer_id=f"cus_{plan_type}",
        stripe_subscription_id=f"sub_{plan_type}",
        plan_type=plan_type,
        status="active",
    )
    db.add(subscription)
    db.commit()
    db.refresh(user)

    if workspace_role is None:
        workspace_owner_id = user.id
    else:
        owner = models.User(
            email=f"owner-{plan_type}@example.com",
            hashed_password="x",
            role="user",
            credits=50,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        workspace_owner_id = owner.id

    workspace = models.Workspace(name="Entity Workspace", owner_id=workspace_owner_id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    if workspace_role is not None:
        membership = models.WorkspaceUser(
            workspace_id=workspace.id,
            user_id=user.id,
            role=workspace_role,
        )
        db.add(membership)
        db.commit()

    project = models.Project(
        workspace_id=workspace.id,
        name="Entity Project",
        domain_url="entity.example",
        icp_roles=["entity authority", "knowledge graph"],
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    audit = models.Audit(
        user_id=user.id,
        project_id=project.id,
        project_scope=models.AUDIT_PROJECT_SCOPE_OWN,
        url="https://entity.example",
        geo_score=71,
        seo_score=75,
        aeo_score=73,
        full_report={
            "analysis": {
                "entities_detected": [
                    {
                        "name": "Entity Authority",
                        "type": "Concept",
                        "relevance_score": 90,
                        "mention_count": 2,
                    },
                    {
                        "name": "Knowledge Graph",
                        "type": "Concept",
                        "relevance_score": 70,
                        "mention_count": 1,
                    },
                ],
            }
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    return TestClient(app), app, db, user, project


def _cleanup(app: FastAPI, db, engine) -> None:
    app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def test_entity_authority_requires_synapse_or_higher() -> None:
    client, test_app, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        response = client.get(f"/api/v1/projects/{project.id}/entity-authority")
        assert response.status_code == 402
        assert "Specialist" in response.json()["detail"]
    finally:
        _cleanup(test_app, db, db.get_bind())


def test_entity_authority_endpoints_return_project_payloads() -> None:
    client, test_app, db, _user, project = _build_client(plan_type="plan_specialist")
    try:
        score_response = client.get(f"/api/v1/projects/{project.id}/entity-authority")
        assert score_response.status_code == 200
        body = score_response.json()
        assert body["project_id"] == project.id
        assert set(body["breakdown"].keys()) == {"coverage", "depth", "consistency", "uniqueness"}
        assert "X-Request-ID" in score_response.headers

        gaps_response = client.get(f"/api/v1/projects/{project.id}/entity-authority/gaps")
        assert gaps_response.status_code == 200
        assert isinstance(gaps_response.json(), list)

        graph_response = client.get(f"/api/v1/projects/{project.id}/entity-graph")
        assert graph_response.status_code == 200
        graph_body = graph_response.json()
        assert graph_body["project_id"] == project.id
        assert isinstance(graph_body["nodes"], list)
        assert isinstance(graph_body["edges"], list)

        trend_response = client.get(f"/api/v1/projects/{project.id}/entity-authority/trend")
        assert trend_response.status_code == 200
        assert trend_response.json()["project_id"] == project.id

        recompute_response = client.post(f"/api/v1/projects/{project.id}/entity-authority/compute")
        assert recompute_response.status_code == 200
        assert recompute_response.json()["project_id"] == project.id
    finally:
        _cleanup(test_app, db, db.get_bind())


def test_entity_authority_recompute_requires_workspace_write_access() -> None:
    client, test_app, db, _user, project = _build_client(
        plan_type="plan_specialist",
        workspace_role=models.WorkspaceRole.VIEWER,
    )
    try:
        get_response = client.get(f"/api/v1/projects/{project.id}/entity-authority")
        assert get_response.status_code == 200

        post_response = client.post(f"/api/v1/projects/{project.id}/entity-authority/compute")
        assert post_response.status_code == 403
        assert "Workspace write access required" in post_response.json()["detail"]
    finally:
        _cleanup(test_app, db, db.get_bind())
