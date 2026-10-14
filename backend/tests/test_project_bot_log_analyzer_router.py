from __future__ import annotations

from datetime import date, timedelta

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
        email=f"botlogs-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=120,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    db.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_botlogs_{plan_type}",
            stripe_subscription_id=f"sub_botlogs_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    db.commit()

    if workspace_role is None:
        workspace_owner_id = user.id
    else:
        owner = models.User(
            email=f"botlogs-owner-{plan_type}@example.com",
            hashed_password="x",
            role="user",
            credits=120,
        )
        db.add(owner)
        db.commit()
        db.refresh(owner)
        workspace_owner_id = owner.id

    workspace = models.Workspace(name="Bot Logs Workspace", owner_id=workspace_owner_id)
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
        name="Bot Logs Project",
        domain_url="https://botlogs.example",
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


def test_bot_log_summary_requires_synapse_or_higher() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        response = client.get(f"/api/v1/projects/{project.id}/monitoring/bot-logs/summary")
        assert response.status_code == 402
        assert "Specialist" in response.json()["detail"]
    finally:
        _cleanup(app, db)


def test_bot_log_upload_and_summary_flow(monkeypatch) -> None:
    from services import project_bot_log_analyzer_service as bot_log_service

    monkeypatch.setattr(
        bot_log_service,
        "_verify_ip_against_suffixes",
        lambda ip_address, suffixes: ip_address.startswith("66."),
    )

    client, app, db, _user, project = _build_client(plan_type="plan_specialist")
    try:
        source_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/bot-logs/sources",
            json={
                "source_type": "cloudflare_logpush",
                "display_name": "Cloudflare Enterprise",
                "config": {"dataset": "http_requests", "bucket": "cf-botlogs"},
                "is_active": True,
            },
        )
        assert source_response.status_code == 200

        # Use a recent date so the trailing 30-day summary window includes these logs.
        log_day = (date.today() - timedelta(days=1)).strftime("%d/%b/%Y")
        log_content = "\n".join(
            [
                f'66.249.66.1 - - [{log_day}:12:31:00 +0000] "GET /blog/launch HTTP/1.1" 200 1024 "-" "GPTBot/1.2"',
                f'10.0.0.9 - - [{log_day}:12:33:00 +0000] "GET /products/widget HTTP/1.1" 404 128 "-" "PerplexityBot/1.0"',
                f'10.0.0.10 - - [{log_day}:12:34:00 +0000] "GET /private/report HTTP/1.1" 503 128 "-" "CCBot/2.0"',
            ]
        )

        upload_response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/bot-logs/upload",
            files={"file": ("access.log", log_content, "text/plain")},
        )
        assert upload_response.status_code == 201
        upload_payload = upload_response.json()
        assert upload_payload["bot_hits"] == 3
        assert upload_payload["aggregate_rows"] >= 2

        summary_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/bot-logs/summary?days=30"
        )
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()

        assert summary_payload["project_id"] == project.id
        assert summary_payload["no_data"] is False
        assert summary_payload["totals"]["total_hits"] == 3
        assert summary_payload["totals"]["error_4xx_hits"] == 1
        assert summary_payload["totals"]["error_5xx_hits"] == 1
        assert len(summary_payload["bot_breakdown"]) >= 2
        assert "X-Request-ID" in summary_response.headers
    finally:
        _cleanup(app, db)


def test_bot_log_source_write_requires_workspace_write_access() -> None:
    client, app, db, _user, project = _build_client(
        plan_type="plan_specialist",
        workspace_role=models.WorkspaceRole.VIEWER,
    )
    try:
        response = client.post(
            f"/api/v1/projects/{project.id}/monitoring/bot-logs/sources",
            json={
                "source_type": "aws_s3",
                "display_name": "S3 Nightly",
                "config": {"bucket": "agency-logs"},
                "is_active": True,
            },
        )
        assert response.status_code == 403
        assert "Workspace write access required" in response.json()["detail"]
    finally:
        _cleanup(app, db)
