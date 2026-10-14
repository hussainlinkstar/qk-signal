"""Contract tests for the admin AI-models settings surface after the Bedrock
cutover (GET/PATCH /admin/settings/ai-providers)."""

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from database import Base
from auth.token_verifier import get_current_user as base_get_current_user
from admin import get_db
from main import app


def _setup():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session()
    user = models.User(
        email="admin@example.com",
        hashed_password="hashed",
        role="admin",
        credits=100,
        notifications_enabled=True,
        unsubscribe_token="admin-unsub-token",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    setattr(user, "resolved_role", "admin")

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[base_get_current_user] = lambda: user
    return TestClient(app), db, engine


def _teardown(client, db, engine):
    client.close()
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_ai_providers_returns_bedrock_routing_contract():
    client, db, engine = _setup()
    try:
        resp = client.get("/api/v1/admin/settings/ai-providers")
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # Bedrock model routing replaces the retired Google/OpenAI/Anthropic keys.
        routing = body["model_routing"]
        assert set(routing) == {
            "BEDROCK_SMART_MODEL",
            "BEDROCK_FAST_MODEL",
            "BEDROCK_LITE_MODEL",
            "BEDROCK_EMBEDDING_MODEL",
        }
        for retired in (
            "GOOGLE_FAST_MODEL",
            "OPENAI_SMART_MODEL",
            "ANTHROPIC_SMART_MODEL",
            "CMS_GEMINI_TEXT_MODEL",
            "SUPPORT_CHAT_MODEL",
        ):
            assert retired not in routing

        # Read-only Bedrock credential status: boolean only, never the token value.
        status = body["bedrock_status"]
        assert isinstance(status["configured"], bool)
        assert "region" in status
        joined = " ".join(str(v) for v in status.values())
        assert "AWS_BEARER_TOKEN_BEDROCK" not in joined

        # Read-only measurement model map is present (display-only).
        assert isinstance(body["measurement_model_map"], dict)

        # Retired LLM reasoning keys are no longer surfaced on this page.
        keys = body["ai_provider_keys"]
        for retired_key in ("gemini_api_key", "google_api_key", "anthropic_api_key"):
            assert retired_key not in keys
    finally:
        _teardown(client, db, engine)


def test_ai_providers_patch_rejects_retired_llm_keys():
    client, db, engine = _setup()
    try:
        # Data-provider + CMS keys still patchable.
        resp = client.patch(
            "/api/v1/admin/settings/ai-providers/bulk",
            json={"keys": {"firecrawl_api_key": "fc-test-123"}},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "BEDROCK_SMART_MODEL" in body["model_routing"]

        # Retired LLM keys are not part of the patch model and are ignored.
        resp2 = client.patch(
            "/api/v1/admin/settings/ai-providers/bulk",
            json={"keys": {"anthropic_api_key": "sk-should-be-ignored"}},
        )
        assert resp2.status_code == 200, resp2.text
        assert "anthropic_api_key" not in resp2.json()["ai_provider_keys"]
    finally:
        _teardown(client, db, engine)
