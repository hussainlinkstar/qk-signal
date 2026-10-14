from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from main import app, get_current_user, get_db


def test_visibility_index_trends_and_latest_endpoints() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    user = models.User(
        email="visibility@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    batch1 = models.VisibilityRunBatch(
        topic="acme payroll",
        provider="openai",
        schedule_key="sched-1",
        status="succeeded",
        score=50.0,
        created_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    batch2 = models.VisibilityRunBatch(
        topic="acme payroll",
        provider="openai",
        schedule_key="sched-2",
        status="succeeded",
        score=100.0,
        created_at=datetime.now(timezone.utc),
    )
    db.add_all([batch1, batch2])
    db.commit()
    db.refresh(batch2)

    run = models.VisibilityRun(
        batch_id=batch2.id,
        topic="acme payroll",
        provider="openai",
        prompt_template="market_overview",
        prompt="Who is visible for acme payroll?",
        raw_response={"text": "Acme https://example.com/acme"},
        parsed_citations=["https://example.com/acme"],
        valid_citations=["https://example.com/acme"],
        score=100.0,
        status="succeeded",
    )
    db.add(run)
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

    client = TestClient(app)

    trends_response = client.get(
        "/api/v1/visibility-index/trends",
        params={"topic": "acme payroll", "provider": "openai", "days": 30},
    )
    latest_response = client.get(
        "/api/v1/visibility-index/latest",
        params={"topic": "acme payroll", "provider": "openai"},
    )

    assert trends_response.status_code == 200
    assert latest_response.status_code == 200
    assert len(trends_response.json()["points"]) == 2
    assert latest_response.json()["status"] == "succeeded"
    assert latest_response.json()["runs"][0]["valid_citations"] == ["https://example.com/acme"]

    app.dependency_overrides.clear()
    db.close()
