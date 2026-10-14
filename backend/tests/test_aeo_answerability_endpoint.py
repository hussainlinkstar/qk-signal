import sys
from pathlib import Path
from unittest.mock import AsyncMock

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
def client(monkeypatch: pytest.MonkeyPatch):
    user = models.User(
        email="answerability-endpoint@example.com",
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

    score_mock = AsyncMock(
        return_value={
            "url": "https://example.com",
            "domain": "example.com",
            "raw_features": {
                "schema_presence": 1.0,
                "backlink_count": 0.0,
                "freshness_days": 30.0,
                "domain_authority": 0.0,
            },
            "normalized_features": {
                "schema_presence": 1.0,
                "backlink_count": 0.0,
                "freshness": 0.5,
                "domain_authority": 0.0,
            },
            "score": {
                "value": 52,
                "model": "deterministic_logistic_v1",
                "raw_model_output": 0.1,
            },
            "factor_explanations": [],
            "history": [{"timestamp": "2025-01-01T00:00:00+00:00", "score": 52}],
            "answer_failure_reasons": [],
            "readability_score": 0.0,
            "readability_findings": [],
            "rewrite_suggestions": [],
        }
    )

    monkeypatch.setattr(main.aeo_answerability_service, "score_url", score_mock)
    main.app.dependency_overrides[main.get_current_user] = override_current_user
    main.app.dependency_overrides[main.get_db] = override_get_db

    test_client = TestClient(main.app)
    try:
        yield test_client, score_mock
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.mark.parametrize(
    "raw_url",
    [
        "htp://bad",
        "example.com",
        "http://exa mple.com",
    ],
)
def test_aeo_answerability_returns_400_for_invalid_url_formats(client, raw_url: str):
    test_client, score_mock = client

    response = test_client.post("/api/v1/aeo/answerability", json={"url": raw_url})

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Invalid URL format. URL must start with http:// or https://."
    )
    assert score_mock.await_count == 0


def test_aeo_answerability_response_includes_history_points(client):
    test_client, _ = client

    response = test_client.post("/api/v1/aeo/answerability", json={"url": "https://example.com"})

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload["history"], list)
    assert payload["history"]
    assert set(payload["history"][0].keys()) == {"timestamp", "score"}
