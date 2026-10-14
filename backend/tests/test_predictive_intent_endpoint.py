import sys
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import main
import models
from database import Base


@pytest.fixture
def client():
    user = models.User(
        email="intent-endpoint@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )

    def override_current_user():
        return user

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = testing_session_local()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[main.get_current_user] = override_current_user
    main.app.dependency_overrides[main.get_db] = override_get_db

    test_client = TestClient(main.app)
    try:
        yield test_client, db
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_intent_predict_endpoint_returns_ranked_questions_and_persists_telemetry(client):
    test_client, db = client
    ingest_payload = {
        "entries": [
            {"question": "How to optimize schema markup?", "context": "JSON-LD examples"},
            {"question": "How to reduce LCP?", "context": "performance tuning"},
        ]
    }

    ingest_response = test_client.post("/api/v1/intent/ingest", json=ingest_payload)
    assert ingest_response.status_code == 200

    predict_response = test_client.post(
        "/api/v1/intent/predict",
        json={"query": "schema optimization tips", "top_k": 2},
    )

    assert predict_response.status_code == 200
    payload = predict_response.json()
    assert payload["top_k"] == 2
    assert len(payload["predictions"]) == 2
    assert (
        payload["predictions"][0]["normalized_score"]
        >= payload["predictions"][1]["normalized_score"]
    )
    assert all(0.0 <= row["normalized_score"] <= 1.0 for row in payload["predictions"])

    telemetry_rows = db.query(models.IntentQueryTelemetry).all()
    assert len(telemetry_rows) == 1
