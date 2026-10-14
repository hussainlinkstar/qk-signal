from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("SSM_ENABLED", "false")

import models
from database import Base
from routers.api_router import get_db as api_router_get_db
from routers.api_router import router as api_router
from services.ai_search_volatility_service import AISearchVolatilityService


def _build_test_app() -> FastAPI:
    app = FastAPI()

    @app.middleware("http")
    async def attach_request_id(request, call_next):
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", "test-request-id")
        return response

    app.include_router(api_router)
    return app


def _build_client() -> tuple[TestClient, FastAPI, object]:
    app = _build_test_app()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[api_router_get_db] = override_get_db
    return TestClient(app), app, db


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
    # Dates relative to "today" so the public dashboard trailing window
    # (build_industry_matrix windows to today-N..today) stays deterministic.
    latest_run_date = datetime.now(timezone.utc).date()
    previous_run_date = latest_run_date - timedelta(days=1)
    db.add_all(
        [
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="google",
                run_date=previous_run_date,
                answer_text="Platform A and Platform B are recommended.",
                citation_domains_json=["platform-a.com", "platform-b.com"],
                citations_count=2,
                answer_format="paragraph",
                schema_version="1",
            ),
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="google",
                run_date=latest_run_date,
                answer_text="1. Platform C. 2. Platform B.",
                citation_domains_json=["platform-c.com", "platform-b.com"],
                citations_count=2,
                answer_format="list",
                schema_version="1",
            ),
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="openai",
                run_date=previous_run_date,
                answer_text="Platform X and Platform B are recommended.",
                citation_domains_json=["platform-x.com", "platform-b.com"],
                citations_count=2,
                answer_format="paragraph",
                schema_version="1",
            ),
            models.DailySeedQueryRun(
                seed_query_id=seed.id,
                provider="openai",
                run_date=latest_run_date,
                answer_text="1. Platform Y. 2. Platform B.",
                citation_domains_json=["platform-y.com", "platform-b.com"],
                citations_count=2,
                answer_format="list",
                schema_version="1",
            ),
        ]
    )
    db.commit()
    AISearchVolatilityService(db).rebuild_snapshots_for_date(run_date=latest_run_date)
    db.commit()


def test_public_volatility_dashboard_includes_matrix_and_ledger() -> None:
    client, app, db = _build_client()
    try:
        _seed_volatility_rows(db)
        response = client.get("/api/v1/volatility/public?provider=all&days=30")
        assert response.status_code == 200
        payload = response.json()
        assert payload["available_providers"] == ["google", "openai"]
        assert payload["summary"]["provider"] == "all"
        assert payload["summary"]["compared_queries"] == 2
        assert payload["industry_matrix"]["points"][0]["moving_queries"] == [
            "best llm observability platforms"
        ]
        assert len(payload["citation_ledger"]["rows"]) == 4
        assert payload["citation_ledger"]["rows"][0]["provider"] == "all"
        assert "X-Request-ID" in response.headers
    finally:
        _cleanup(app, db)
