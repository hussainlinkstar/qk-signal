import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.testclient import TestClient

import models
from auth.security import get_current_user_from_token as get_current_user
import services.service_health as service_health
import system_checks


app = FastAPI()
app.include_router(system_checks.router, prefix="/api/v1")


def _override_get_db():
    yield object()


app.dependency_overrides[system_checks.get_db] = _override_get_db
client = TestClient(app)


def _reset_dependency_overrides() -> None:
    app.dependency_overrides = {system_checks.get_db: _override_get_db}


def _admin_user() -> models.User:
    return models.User(
        email="admin-system-status@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )


def _guest_user() -> models.User:
    return models.User(
        email="guest-system-status@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )


async def _fake_payload(_db):
    return {
        "services": {
            "database": {
                "name": "PostgreSQL Database",
                "status": "Major Outage",
                "details": "could not connect to db.internal:5432",
            },
            "project_data_sources": {
                "name": "Project Data Sources",
                "status": "Operational",
                "details": "",
            },
            "cache": {
                "name": "Redis Cache",
                "status": "Operational",
                "details": "",
            },
            "bing": {
                "name": "Bing Search",
                "status": "Operational",
                "details": "",
            },
            "perplexity": {
                "name": "Perplexity API",
                "status": "Not Configured",
                "details": "PERPLEXITY_API_KEY is not configured.",
            },
        },
        "audit_metrics": {
            "jobs_started": 10,
            "jobs_succeeded": 9,
            "jobs_failed": 1,
            "job_attempts_total": 11,
            "job_retries": 2,
            "job_duration_seconds_total": 123.5,
        },
        "available_models": ["google", "openai", "bing"],
    }


def _patch_async_redis(monkeypatch, *, metrics: dict[str, str] | None = None) -> None:
    class FakeRedisClient:
        async def ping(self):
            return True

        async def hgetall(self, _key):
            return metrics or {}

        async def get(self, _key):
            return None

    @asynccontextmanager
    async def fake_get_async_redis(**_kwargs):
        yield FakeRedisClient()

    monkeypatch.setattr(system_checks, "get_async_redis", fake_get_async_redis)
    # service_health.py holds its own reference to get_async_redis (it's a
    # separate module), so tests that don't care about live Firecrawl health
    # still need this patched to avoid a real (timed-out) Redis connection
    # attempt from system_checks' get_service_health("firecrawl") call.
    monkeypatch.setattr(service_health, "get_async_redis", fake_get_async_redis)


def test_guest_can_read_public_system_status(monkeypatch) -> None:
    monkeypatch.setattr(system_checks, "_build_system_status_payload", _fake_payload)

    response = client.get("/api/v1/system-status")

    assert response.status_code == 200
    payload = response.json()
    assert "services" in payload
    assert "audit_metrics" not in payload
    assert "orchestra_v3_readiness" not in payload
    assert payload["services"]["database"] == {
        "name": "Database",
        "status": "Major Outage",
    }
    assert payload["services"]["project_data_sources"] == {
        "name": "Data Sources",
        "status": "Operational",
    }
    assert payload["services"]["bing"] == {
        "name": "Bing Search",
        "status": "Operational",
    }
    assert "details" not in payload["services"]["database"]
    assert "details" not in payload["services"]["project_data_sources"]
    assert "details" not in payload["services"]["perplexity"]


def test_guest_is_blocked_from_admin_system_status(monkeypatch) -> None:
    monkeypatch.setattr(system_checks, "_build_system_status_payload", _fake_payload)

    def override_get_current_user() -> models.User:
        return _guest_user()

    app.dependency_overrides[get_current_user] = override_get_current_user

    response = client.get("/api/v1/system-status/admin")

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required."

    _reset_dependency_overrides()


def test_admin_can_read_full_admin_system_status(monkeypatch) -> None:
    monkeypatch.setattr(system_checks, "_build_system_status_payload", _fake_payload)

    def override_get_current_user() -> models.User:
        return _admin_user()

    app.dependency_overrides[get_current_user] = override_get_current_user

    response = client.get("/api/v1/system-status/admin")

    assert response.status_code == 200
    payload = response.json()
    assert payload["services"]["database"]["details"] == "could not connect to db.internal:5432"
    assert payload["services"]["project_data_sources"]["status"] == "Operational"
    assert payload["audit_metrics"]["jobs_started"] == 10

    _reset_dependency_overrides()


def test_project_data_sources_dependency_marks_status_as_outage(monkeypatch) -> None:
    class FakeDb:
        def execute(self, statement):
            query = str(statement).lower()
            if "project_data_sources" in query:
                raise RuntimeError("relation project_data_sources does not exist")
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "FIRECRAWL_API_KEY", "test-firecrawl-key")
    monkeypatch.setattr(system_checks.settings, "ANTHROPIC_API_KEY", "test-anthropic-key")
    monkeypatch.setattr(system_checks.settings, "DEBATE_ENABLED", True)
    monkeypatch.setattr(
        system_checks, "effective_gemini_api_key_from_env", lambda: "test-gemini-key"
    )

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["database"]["status"] == "Operational"
    assert payload["services"]["project_data_sources"]["status"] == "Major Outage"
    assert (
        "relation project_data_sources does not exist"
        in payload["services"]["project_data_sources"]["details"]
    )


def test_firecrawl_shows_degraded_when_recent_calls_are_failing(monkeypatch) -> None:
    """A configured-but-out-of-credits Firecrawl account must not read as
    Operational just because the key is present; the System Status page is
    where an admin would actually notice a billing outage like this."""

    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "FIRECRAWL_API_KEY", "test-firecrawl-key")

    async def fake_get_service_health(service):
        assert service == "firecrawl"
        return {
            "ok": False,
            "detail": "Payment Required: Insufficient credits to perform this request.",
            "at": "2026-08-19T00:00:00+00:00",
        }

    monkeypatch.setattr(system_checks, "get_service_health", fake_get_service_health)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["scraper"]["status"] == "Degraded"
    assert "Insufficient credits" in payload["services"]["scraper"]["details"]


def test_firecrawl_stays_operational_when_no_recent_failures_recorded(monkeypatch) -> None:
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "FIRECRAWL_API_KEY", "test-firecrawl-key")

    async def fake_get_service_health(_service):
        return None

    monkeypatch.setattr(system_checks, "get_service_health", fake_get_service_health)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["scraper"]["status"] == "Operational"


def test_firecrawl_health_check_is_skipped_when_key_is_not_configured(monkeypatch) -> None:
    """The missing-key message is more specific than a generic health-record
    failure, so real-time health should not override it."""

    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "FIRECRAWL_API_KEY", None)

    called = False

    async def fake_get_service_health(_service):
        nonlocal called
        called = True
        return {"ok": False, "detail": "should not be reached"}

    monkeypatch.setattr(system_checks, "get_service_health", fake_get_service_health)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert called is False
    assert payload["services"]["scraper"]["status"] == "Degraded"
    assert "FIRECRAWL_API_KEY not configured" in payload["services"]["scraper"]["details"]


def test_llm_gateway_status_no_longer_tracks_openrouter(monkeypatch) -> None:
    # The OpenRouter LLM gateway (and its OpenAI fallback) were retired — the
    # engine runs reasoning/measurement on AWS Bedrock. The status payload no
    # longer surfaces an "openrouter" service and tracks no gateway providers.
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "FIRECRAWL_API_KEY", "test-firecrawl-key")

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert "openrouter" not in payload["services"]
    assert payload["available_models"] == []


def test_serpapi_reports_outage_when_the_provider_rejects_the_key(monkeypatch) -> None:
    """A present-but-rejected key must never be published as Operational: the
    public status page was telling the world SerpAPI was fine while every GEO
    visibility query failed with HTTP 401."""

    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "SERPAPI_API_KEY", "revoked-key")

    async def fake_probe(api_key):
        assert api_key == "revoked-key"
        return {
            "state": system_checks.PROBE_INVALID_KEY,
            "detail": "SerpAPI rejected the configured API key (HTTP 401).",
        }

    monkeypatch.setattr(system_checks, "probe_serpapi", fake_probe)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["serpapi"]["status"] == "Major Outage"
    assert "HTTP 401" in payload["services"]["serpapi"]["details"]


def test_serpapi_reports_operational_only_when_the_probe_succeeds(monkeypatch) -> None:
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "SERPAPI_API_KEY", "working-key")

    async def fake_probe(_api_key):
        return {"state": system_checks.PROBE_OPERATIONAL, "detail": ""}

    monkeypatch.setattr(system_checks, "probe_serpapi", fake_probe)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["serpapi"]["status"] == "Operational"


def test_serpapi_falls_back_to_unknown_when_the_probe_is_inconclusive(monkeypatch) -> None:
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "SERPAPI_API_KEY", "some-key")

    async def fake_probe(_api_key):
        return {"state": "unknown", "detail": "SerpAPI health probe did not complete."}

    monkeypatch.setattr(system_checks, "probe_serpapi", fake_probe)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["serpapi"]["status"] == "Unknown"


def test_serpapi_is_not_probed_when_no_key_is_configured(monkeypatch) -> None:
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "SERPAPI_API_KEY", None)
    monkeypatch.setattr(system_checks.settings, "SEARCH_API_KEY", None)

    called = False

    async def fake_probe(_api_key):
        nonlocal called
        called = True
        return {"state": system_checks.PROBE_OPERATIONAL, "detail": ""}

    monkeypatch.setattr(system_checks, "probe_serpapi", fake_probe)

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert called is False
    assert payload["services"]["serpapi"]["status"] == "Not Configured"


def test_generic_search_provider_is_unverified_rather_than_operational(monkeypatch) -> None:
    class FakeDb:
        def execute(self, _statement):
            return None

    _patch_async_redis(monkeypatch)
    monkeypatch.setattr(system_checks.settings, "SERPAPI_API_KEY", None)
    monkeypatch.setattr(system_checks.settings, "SEARCH_API_KEY", "generic-search-key")

    payload = asyncio.run(system_checks._build_system_status_payload(FakeDb()))

    assert payload["services"]["serpapi"]["status"] == "Unknown"
    assert "no health probe" in payload["services"]["serpapi"]["details"].lower()
