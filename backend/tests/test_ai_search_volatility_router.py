from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from auth.security import get_current_user_from_token as get_current_user
from database import Base, get_db
from routers.monitoring_router import router as monitoring_router
from services.ai_search_volatility_service import AISearchVolatilityService


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
    plan_type: str = "plan_specialist",
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
        email=f"volatility-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=100,
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

    workspace = models.Workspace(name="Volatility Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Volatility Project",
        domain_url="https://volatility.example",
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


def _seed_volatility_rows(db) -> None:
    seed = models.GlobalVolatilitySeedQuery(
        query_text="best llm observability platforms",
        normalized_query="best llm observability platforms",
        industry="tech",
        priority_weight=1.0,
        is_active=True,
        source="test",
        schema_version="1",
    )
    db.add(seed)
    db.flush()
    db.add_all(
        [
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="all",
                run_date=date(2026, 3, 4),
                answer_text="Platform A and Platform B are recommended.",
                citation_domains_json=["platform-a.com", "platform-b.com"],
                citations_count=2,
                answer_format="paragraph",
                schema_version="1",
            ),
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="all",
                run_date=date(2026, 3, 5),
                answer_text="1. Platform C. 2. Platform B.",
                citation_domains_json=["platform-c.com", "platform-b.com"],
                citations_count=2,
                answer_format="list",
                schema_version="1",
            ),
        ]
    )
    db.commit()
    AISearchVolatilityService(db).rebuild_snapshots_for_date(run_date=date(2026, 3, 5))
    db.commit()


def test_ai_search_volatility_requires_synapse_or_higher() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_standard")
    try:
        response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/ai-search-volatility/summary"
        )
        assert response.status_code == 402
        assert "Specialist" in response.json()["detail"]
    finally:
        _cleanup(app, db)


def test_ai_search_volatility_summary_and_trends() -> None:
    client, app, db, _user, project = _build_client(plan_type="plan_specialist")
    try:
        _seed_volatility_rows(db)
        summary_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/ai-search-volatility/summary?provider=all&days=30"
        )
        assert summary_response.status_code == 200
        summary_payload = summary_response.json()
        assert summary_payload["provider"] == "all"
        assert summary_payload["volatility_score"] is not None
        assert summary_payload["compared_queries"] >= 1
        assert "X-Request-ID" in summary_response.headers

        trends_response = client.get(
            f"/api/v1/projects/{project.id}/monitoring/ai-search-volatility/trends?provider=all&days=30"
        )
        assert trends_response.status_code == 200
        trends_payload = trends_response.json()
        assert trends_payload["provider"] == "all"
        assert len(trends_payload["points"]) == 30
    finally:
        _cleanup(app, db)
