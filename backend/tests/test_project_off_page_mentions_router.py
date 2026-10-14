from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base, get_db
from routers.monitoring_router import router as monitoring_router


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(monitoring_router)
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
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    user = models.User(
        email=f"offpage-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=250,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_offpage_{plan_type}",
            stripe_subscription_id=f"sub_offpage_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    if workspace_role is None:
        workspace_owner_id = user.id
    else:
        owner = models.User(
            email=f"offpage-owner-{plan_type}@example.com",
            hashed_password="x",
            role="user",
            credits=250,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        db.add(
            models.Subscription(
                user_id=owner.id,
                stripe_customer_id=f"cus_offpage_owner_{plan_type}",
                stripe_subscription_id=f"sub_offpage_owner_{plan_type}",
                plan_type=plan_type,
                status="active",
            )
        )
        db.commit()
        workspace_owner_id = owner.id

    workspace = models.Workspace(name="Off Page Workspace", owner_id=workspace_owner_id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    if workspace_role is not None:
        db.add(
            models.WorkspaceUser(
                workspace_id=workspace.id,
                user_id=user.id,
                role=workspace_role,
            )
        )
        db.commit()

    project = models.Project(
        workspace_id=workspace.id,
        name="Off Page Project",
        domain_url="https://offpage.example",
        icp_roles=["enterprise geo", "aeo platform"],
        usp="Citation monitoring and authority insights",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

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


def _cleanup(app: FastAPI, db) -> None:
    app.dependency_overrides.clear()
    bind = db.get_bind()
    db.close()
    Base.metadata.drop_all(bind=bind)


def test_off_page_mentions_summary_requires_synapse_or_higher() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        response = client.get(f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/summary")
        assert response.status_code == 402
        assert "Specialist" in response.json()["detail"]
    finally:
        _cleanup(app, db)


def test_off_page_mentions_ingest_and_read_flow() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_specialist")
    try:
        # Use recent timestamps so they fall inside the trailing 30-day summary window.
        recent_ts = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ingest_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/ingest",
            json={
                "source_type": "manual_import",
                "run_analysis": False,
                "skip_existing": True,
                "mentions": [
                    {
                        "title": "Best enterprise GEO tools",
                        "snippet": "Qiko Signal is a recommended enterprise GEO platform.",
                        "mention_url": "https://reddit.com/r/seo/comments/1",
                        "source_domain": "reddit.com",
                        "published_at": recent_ts,
                        "sentiment_label": "positive",
                        "sentiment_score": 0.78,
                        "linked_keywords": ["enterprise geo"],
                        "entities": ["Qiko Signal"],
                    },
                    {
                        "title": "Comparing AEO vendors",
                        "snippet": "One team reported slower onboarding with some tools.",
                        "mention_url": "https://quora.com/Which-AEO-tool",
                        "source_domain": "quora.com",
                        "published_at": recent_ts,
                        "sentiment_label": "negative",
                        "sentiment_score": -0.44,
                        "linked_keywords": ["aeo platform"],
                        "entities": ["Qiko Signal"],
                    },
                ],
            },
        )
        assert ingest_response.status_code == 201
        ingest_payload = ingest_response.json()
        assert ingest_payload["ingested_mentions"] == 2
        assert ingest_payload["skipped_mentions"] == 0
        assert ingest_payload["project_id"] == project.id

        summary_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/summary"
        )
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["project_id"] == project.id
        assert summary_payload["totals"]["total_mentions"] == 2
        assert summary_payload["totals"]["positive_mentions"] == 1
        assert summary_payload["totals"]["negative_mentions"] == 1
        assert summary_payload["no_data"] is False
        assert "X-Request-ID" in summary_response.headers

        trends_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/trends?days=30"
        )
        assert trends_response.status_code == 200
        trends_payload = trends_response.json()
        assert trends_payload["project_id"] == project.id
        assert len(trends_payload["points"]) == 30

        feed_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/feed?days=30&limit=10"
        )
        assert feed_response.status_code == 200
        feed_payload = feed_response.json()
        assert len(feed_payload) == 2
        assert feed_payload[0]["source_domain"] in {"quora.com", "reddit.com"}
    finally:
        _cleanup(app, db)


def test_off_page_mentions_ingest_requires_workspace_write_access() -> None:
    client, app, db, _user, project = _build_client(
        plan_type="plan_specialist",
        workspace_role=models.WorkspaceRole.VIEWER,
    )
    try:
        response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/off-page-mentions/ingest",
            json={
                "source_type": "manual_import",
                "run_analysis": False,
                "mentions": [
                    {
                        "snippet": "Qiko Signal mention in a forum thread.",
                        "source_domain": "reddit.com",
                    }
                ],
            },
        )
        assert response.status_code == 403
        assert "Workspace write access required" in response.json()["detail"]
    finally:
        _cleanup(app, db)
