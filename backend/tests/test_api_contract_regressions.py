from datetime import datetime, timezone
import contextlib
import json
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from auth.security import get_current_user_from_token
from database import Base
from database import get_db
import main
from routers import api_router


@pytest.fixture
def client_with_db(monkeypatch: pytest.MonkeyPatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="contract@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    audit = models.Audit(
        user_id=user.id,
        url="https://example.com/",
        geo_score=78,
        full_report={
            "analysis": {"seo_score": 84, "geo_score": 76, "aeo_score": 73},
            "performance": {"performance_score": 91},
            "network": {"supports_http2": True},
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)

    async def noop_enforce_authenticated_audit_limit(*_args, **_kwargs):
        return None

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        return user

    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    monkeypatch.setattr(api_router.plan_validator, "has_feature", lambda p, f: True)

    # BUG-023: Prevent _app_lifespan from running real DB migrations against the
    # in-memory SQLite test engine, which causes the TestClient to hang.
    from core import runtime_migrations

    monkeypatch.setattr(runtime_migrations, "apply_pending_migrations_if_needed", lambda: None)

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[api_router.get_db] = override_get_db
    main.app.dependency_overrides[get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user
    main.app.dependency_overrides[api_router.get_current_user] = override_get_current_user
    main.app.dependency_overrides[get_current_user_from_token] = override_get_current_user

    test_client = TestClient(main.app, raise_server_exceptions=False)
    try:
        yield test_client, audit
    finally:
        main.app.dependency_overrides.clear()
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_error_detail_contract_for_invalid_audit_url(client_with_db):
    client, _ = client_with_db

    response = client.post(
        "/api/v1/audit",
        json={"url": "invalid", "provider": "google", "tier": "fast"},
    )

    assert response.status_code == 400
    payload = response.json()
    assert set(payload.keys()) == {"detail"}
    assert payload["detail"] == "Invalid URL format. URL must start with http:// or https://."


def test_white_label_uses_seo_score_terminology(client_with_db):
    client, audit = client_with_db

    response = client.post(
        "/api/v1/reports/white-label",
        json={
            "audit_id": audit.id,
            "agency_name": "Contract QA",
            "primary_color": "#FF4D2D",
            "include_competitor_analysis": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert "seo_score" in payload["score_breakdown"]
    assert any(
        highlight.startswith("SEO score checked in at") for highlight in payload["highlights"]
    )


def test_openapi_documents_official_status_values(client_with_db):
    client, _ = client_with_db

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schemas = response.json()["components"]["schemas"]

    history_status = schemas["AuditHistoryEntry"]["properties"]["status"]
    assert set(history_status["enum"]) == {
        "completed",
        "degraded",
        "failed",
        "archived",
        "purged",
    }

    job_status = schemas["AuditJobStatusResponse"]["properties"]["status"]
    assert set(job_status["enum"]) == {"queued", "running", "succeeded", "failed"}

    answerability_history = schemas["AEOAnswerabilityResponse"]["properties"]["history"]
    assert answerability_history["type"] == "array"

    def _enum_values(schema_property: dict) -> set[str]:
        # These fields are now Optional[Literal[...]] which OpenAPI serializes as
        # anyOf: [{enum: [...]}, {type: null}] rather than a top-level "enum".
        if "enum" in schema_property:
            return set(schema_property["enum"])
        for variant in schema_property.get("anyOf", []):
            if "enum" in variant:
                return set(variant["enum"])
        raise AssertionError(f"No enum found in schema property: {schema_property}")

    complex_report_options = schemas["ComplexReportOptions"]["properties"]
    assert _enum_values(complex_report_options["report_kind"]) == {
        "standard",
        "executive",
        "project",
        "competitors",
        "financial",
        "aio",
        "seo",
    }
    assert _enum_values(complex_report_options["branding_mode"]) == {"platform", "white_label"}
    assert _enum_values(complex_report_options["competitor_mode"]) == {"latest", "trend"}
    assert complex_report_options["hide_credit_cost"]["default"] is True


def test_ai_strategic_insights_contract(client_with_db, monkeypatch: pytest.MonkeyPatch):
    client, audit = client_with_db

    response = client.post(
        "/api/v1/ai/strategic-insights",
        json={"audit_id": audit.id},
    )

    assert response.status_code == 200
    assert "X-Request-ID" in response.headers
    payload = response.json()
    assert set(payload.keys()) == {"content"}
    assert isinstance(payload["content"], str)

    content_payload = json.loads(payload["content"])
    assert {
        "executive_summary",
        "critical_alerts",
        "priority_roadmap",
        "content_gap_theory",
        "technical_debt_explanation",
        "generated_at",
        "audit_id",
        "project_id",
        "grounding_sources",
        "aeo_query_ideas",
        "geo_prompt_ideas",
    }.issubset(set(content_payload.keys()))


def test_update_user_branding_roundtrip_and_color_validation(client_with_db):
    client, _ = client_with_db

    invalid = client.put(
        "/api/v1/users/me/branding",
        json={"primary_color": "orange"},
    )
    assert invalid.status_code == 422

    response = client.put(
        "/api/v1/users/me/branding",
        json={
            "custom_logo_url": "data:image/png;base64,ZmFrZQ==",
            "company_name": "Contract QA",
            "primary_color": "#112233",
            "secondary_color": "#445566",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "custom_logo_url": "data:image/png;base64,ZmFrZQ==",
        "company_name": "Contract QA",
        "primary_color": "#112233",
        "secondary_color": "#445566",
    }


def test_white_label_pdf_uses_persisted_branding_with_request_override(
    client_with_db, monkeypatch: pytest.MonkeyPatch
):
    client, audit = client_with_db
    captured: dict[str, object] = {}

    class _FakeRedisClient:
        async def rpush(self, queue_name: str, payload: str):
            captured["queue_name"] = queue_name
            captured["job_payload"] = json.loads(payload)
            return 1

        async def close(self):
            return None

    # The PDF endpoint now enqueues via the get_async_redis() async context
    # manager (core.redis_client) instead of redis.from_url, so patch that.
    @contextlib.asynccontextmanager
    async def _fake_get_async_redis(*_args, **_kwargs):
        yield _FakeRedisClient()

    monkeypatch.setattr(api_router, "get_async_redis", _fake_get_async_redis)

    branding_response = client.put(
        "/api/v1/users/me/branding",
        json={
            "custom_logo_url": "data:image/png;base64,cGVyc2lzdGVk",
            "company_name": "Persisted Agency",
            "primary_color": "#223344",
            "secondary_color": "#556677",
        },
    )
    assert branding_response.status_code == 200

    response = client.post(
        "/api/v1/reports/white-label/pdf",
        json={
            "audit_id": audit.id,
            "agency_name": None,
            "title": None,
            "primary_color": "#AABBCC",
            "include_competitor_analysis": False,
        },
    )

    assert response.status_code == 200
    assert captured["queue_name"] == "pdf_jobs"
    job_payload = captured["job_payload"]
    assert isinstance(job_payload, dict)

    branding = job_payload["branding_config"]
    assert branding["company_name"] == "Persisted Agency"
    assert branding["primary_color"] == "#AABBCC"
    assert branding["secondary_color"] == "#556677"
    assert branding["custom_logo_url"] == "data:image/png;base64,cGVyc2lzdGVk"
    assert branding["report_kind"] == "executive"
    assert branding["branding_mode"] == "platform"
    assert branding["hide_credit_cost"] is True

    export_manifest = job_payload["export_manifest"]
    assert export_manifest == {
        "report_kind": "executive",
        "branding_mode": "platform",
        "competitor_mode": None,
        "hide_credit_cost": True,
        # legacy_report_type only echoes an explicitly-supplied report_type; the
        # request omits it, so it is None. The derived value lives in
        # render_report_type.
        "legacy_report_type": None,
        "render_report_type": "branded",
        "template_type": "Executive",
    }


def test_generate_complex_report_rejects_inverted_date_range(client_with_db):
    client, audit = client_with_db

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id],
            "template_type": "Executive",
            "date_from": "2026-03-10T00:00:00Z",
            "date_to": "2026-03-01T00:00:00Z",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
            },
        },
    )

    assert response.status_code == 422
    assert "date_from must be earlier than or equal to date_to" in response.text


def test_generate_complex_report_rejects_competitor_mode_for_non_competitor_exports(client_with_db):
    client, audit = client_with_db

    response = client.post(
        "/api/v1/reports/generate-complex",
        json={
            "audit_ids": [audit.id],
            "template_type": "Executive",
            "report_options": {
                "mode": "individual",
                "sections": ["overview"],
                "report_kind": "standard",
                "competitor_mode": "trend",
            },
        },
    )

    assert response.status_code == 422
    assert "competitor_mode can only be used for competitor report exports" in response.text
