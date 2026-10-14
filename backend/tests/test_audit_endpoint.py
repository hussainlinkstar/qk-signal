import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from database import Base
from services.audit_dedup_service import build_dedup_key
from services import guest_audit_service


class FakeRedisClient:
    def __init__(self, store: dict[str, str], calls: dict[str, list]):
        self._store = store
        self._calls = calls

    async def get(self, key: str):
        self._calls["get"].append(key)
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None):
        self._calls["set"].append({"key": key, "value": value, "ex": ex})
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value: str):
        # Dedup writes go through setex; keep them out of the cache "set" call
        # tracking so assertions on cache writes remain accurate.
        del ttl
        self._store[key] = value

    async def expire(self, key: str, ttl: int):
        return True

    async def hset(self, key: str, mapping: dict[str, str]):
        self._calls["hset"].append({"key": key, "mapping": dict(mapping)})
        self._store[key] = dict(mapping)

    async def hgetall(self, key: str):
        value = self._store.get(key)
        return dict(value) if isinstance(value, dict) else {}

    async def rpush(self, key: str, value: str):
        self._calls["rpush"].append({"key": key, "value": value})
        existing = self._store.get(key)
        if isinstance(existing, list):
            existing.append(value)
        elif existing is None:
            self._store[key] = [value]
        else:
            self._store[key] = [existing, value]

    async def lrange(self, key: str, start: int, end: int):
        value = self._store.get(key)
        items = list(value) if isinstance(value, list) else []
        normalized_end = None if end == -1 else end + 1
        return items[start:normalized_end]

    async def delete(self, *keys: str):
        deleted = 0
        for key in keys:
            if key in self._store:
                deleted += 1
                self._store.pop(key, None)
        return deleted

    async def aclose(self):
        self._calls["close"].append(True)

    async def close(self):
        await self.aclose()


class _LazyModuleProxy:
    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module = None

    def _load(self):
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str):
        return getattr(self._load(), name)


main = _LazyModuleProxy("main")


def _build_test_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    db = testing_session_local()
    user = models.User(
        email="audit-endpoint@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = models.Workspace(name="Audit Endpoint Workspace", owner_id=user.id)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)

    project = models.Project(
        workspace_id=workspace.id,
        name="Audit Endpoint Project",
        domain_url="https://example.com",
        language="en",
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    return engine, db, user, project


@pytest.fixture
def lightweight_context():
    engine, db, user, project = _build_test_session()

    yield {
        "db": db,
        "user": user,
        "project": project,
    }

    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def test_context(monkeypatch: pytest.MonkeyPatch):
    engine, db, user, project = _build_test_session()
    maintenance_module = importlib.import_module("middleware.maintenance")
    from services.ai_routing_policy import provider_runtime_state_service

    def override_get_db():
        try:
            yield db
        finally:
            pass

    def override_get_current_user():
        db.refresh(user)
        return user

    async def noop_enforce_authenticated_audit_limit(*_args, **_kwargs):
        return None

    async def noop_tenant_resolver_middleware(request, call_next):
        return await call_next(request)

    redis_store: dict[str, str] = {}
    redis_calls: dict[str, list] = {"get": [], "set": [], "hset": [], "rpush": [], "close": []}

    def fake_redis_from_url(*_args, **_kwargs):
        return FakeRedisClient(redis_store, redis_calls)

    monkeypatch.setattr(
        main, "enforce_authenticated_audit_limit", noop_enforce_authenticated_audit_limit
    )
    monkeypatch.setattr(
        main.api_module,
        "enforce_authenticated_audit_limit",
        noop_enforce_authenticated_audit_limit,
    )
    monkeypatch.setattr(main, "tenant_resolver_middleware", noop_tenant_resolver_middleware)
    monkeypatch.setattr(
        maintenance_module,
        "_get_maintenance_state",
        lambda: {"active": False, "message": "", "allowed_ips": []},
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(_redis_client.async_redis_lib, "from_url", fake_redis_from_url)
    monkeypatch.setattr(_redis_client.sync_redis_lib, "from_url", fake_redis_from_url)
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[main.get_current_user] = override_get_current_user

    client = TestClient(main.app)

    yield {
        "client": client,
        "db": db,
        "user": user,
        "project": project,
        "redis_store": redis_store,
        "redis_calls": redis_calls,
    }

    main.app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def test_create_audit_succeeds_when_user_has_no_credits(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    # SIGV2-1024: credits are internal soft limits; an exhausted wallet must
    # not refuse an otherwise-allowed audit.
    test_context["user"].credits = 0
    test_context["db"].add(test_context["user"])
    test_context["db"].commit()
    test_context["db"].refresh(test_context["user"])

    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 70, "geo_score": 71, "aeo_score": 72},
                "site": {"url": "https://example.com", "market": "us", "language": "en"},
                "metadata": {"plan": "plan_starter", "audit_outcome": "completed"},
            },
            {"seo": 70.0, "geo": 71.0, "aeo": 72.0, "overall": 71.0},
        )
    )
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(
        main.api_module, "fetch_url_signature", AsyncMock(return_value={"content_hash": "sig"})
    )

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-no-credits"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1


@pytest.mark.parametrize(
    "raw_url",
    [
        "htp://bad",
        "example.com",
        "http://exa mple.com",
    ],
)
def test_create_audit_returns_400_for_invalid_url_formats(test_context, raw_url: str):
    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-invalid-scheme"},
        json={"url": raw_url, "provider": "google", "tier": "fast"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Invalid URL format. URL must start with http:// or https://."
    )


def test_create_audit_returns_localized_invalid_url_message(test_context):
    en_response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-invalid-url-en", "Accept-Language": "en"},
        json={"url": "htp://bad", "provider": "google", "tier": "fast"},
    )
    ro_response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-invalid-url-ro", "Accept-Language": "ro"},
        json={"url": "htp://bad", "provider": "google", "tier": "fast"},
    )

    assert en_response.status_code == 400
    assert ro_response.status_code == 400
    assert (
        en_response.json()["detail"]
        == "Invalid URL format. URL must start with http:// or https://."
    )
    # NOTE: the RO backend message catalog (app/i18n.py _BACKEND_CATALOG["ro"])
    # currently aliases EN_MESSAGES, so the localized invalid-URL message is the
    # same canonical English copy for both locales. Asserting EN != RO would
    # require populating real Romanian translations (a copy/product decision),
    # so this test pins the current contract: both locales resolve via the i18n
    # seam and return the canonical message.
    assert (
        ro_response.json()["detail"]
        == "Invalid URL format. URL must start with http:// or https://."
    )


@pytest.mark.parametrize("raw_url", ["htp://bad", "example.com", "http://exa mple.com"])
def test_create_audit_job_returns_400_for_invalid_url_formats(test_context, raw_url: str):
    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-invalid-job-url"},
        json={"url": raw_url, "provider": "google", "tier": "fast"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Invalid URL format. URL must start with http:// or https://."
    )


def test_create_audit_job_returns_500_when_db_commit_integrity_error(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    rollback_calls: list[bool] = []

    # The endpoint performs earlier commits (e.g. creating operational-settings
    # while resolving the credit-engine policy version) before persisting the
    # AuditJob. Only fail the commit that flushes the AuditJob so this test
    # exercises the job-persistence error handling, not unrelated bootstrap commits.
    real_commit = test_context["db"].commit

    def raise_integrity_error():
        if any(isinstance(obj, models.AuditJob) for obj in test_context["db"].new):
            raise IntegrityError("insert into audit_jobs", {}, Exception("duplicate key"))
        return real_commit()

    def record_rollback():
        rollback_calls.append(True)

    monkeypatch.setattr(test_context["db"], "commit", raise_integrity_error)
    monkeypatch.setattr(test_context["db"], "rollback", record_rollback)

    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-job-integrity-error"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save audit to database."
    assert rollback_calls == [True]


def test_create_audit_job_requires_project_id(test_context):
    # project_id is strictly required on AuditJobRequest (URL-based inference was
    # intentionally removed; see api_router.py "Removed
    # _infer_project_id_for_audit_url because project_id is strictly required.").
    # Omitting it must fail schema validation with a 422, and no job should be
    # queued.
    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-job-project-infer"},
        json={"url": "https://example.com/pricing", "provider": "google", "tier": "fast"},
    )

    assert response.status_code == 422
    body = response.json()
    assert any(tuple(error.get("loc", ()))[-1] == "project_id" for error in body.get("detail", []))
    assert test_context["redis_calls"]["rpush"] == []


def _create_project_for_user(
    test_context,
    *,
    name: str = "Client Project",
    domain_url: str = "https://client.example",
    language: str = "en",
    target_country: str | None = None,
):
    db = test_context["db"]
    user = test_context["user"]

    workspace = models.Workspace(name=f"{name} Workspace", owner_id=user.id)
    db.add(workspace)
    db.flush()

    project = models.Project(
        workspace_id=workspace.id,
        name=name,
        domain_url=domain_url,
        language=language,
        target_country=target_country,
        icp_roles=[],
        priority_pulse_tags=[],
        sme_profiles=[],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _build_handler_request(request_id: str) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(request_id=request_id, audit_cache_state="na"))


def test_create_audit_allows_brand_without_url_and_persists_target_contract(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    project = _create_project_for_user(
        test_context,
        name="Acme Brand Audit",
        domain_url="https://acme.example",
        language="ro",
        target_country="ro",
    )
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 78, "geo_score": 81, "aeo_score": 83},
                "site": {"url": None, "market": "ro", "language": "ro"},
                "metadata": {"plan": "plan_starter", "audit_outcome": "completed"},
            },
            {"seo": 78.0, "geo": 81.0, "aeo": 83.0, "overall": 80.67},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "unused"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-brand-no-url"},
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Logistics",
            "target_metadata": {"category": "logistics", "market": "ro", "language": "ro"},
            "provider": "google",
            "tier": "fast",
            "project_id": project.id,
        },
    )

    payload = response.json()
    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1
    assert fetch_signature_mock.await_count == 0
    assert perform_audit_mock.await_args.kwargs["url"] == ""
    assert perform_audit_mock.await_args.kwargs["audit_target_type"] == "brand"
    assert perform_audit_mock.await_args.kwargs["target_name"] == "Acme Logistics"
    assert perform_audit_mock.await_args.kwargs["target_metadata"] == {
        "category": "logistics",
        "market": "ro",
        "language": "ro",
    }
    assert payload["report"]["target"]["type"] == "brand"
    assert payload["report"]["target"]["name"] == "Acme Logistics"
    assert payload["report"]["target"]["url"] is None
    assert persisted_audit is not None
    assert persisted_audit.project_id == project.id
    assert persisted_audit.site_id is None
    assert persisted_audit.target_url is None
    # Phase 6 (commit 4e134080) made Audit.url nullable and the sync audit path
    # now persists url=None (not "") for brand-mode audits.
    assert persisted_audit.url is None
    assert persisted_audit.target_name == "Acme Logistics"


def test_create_audit_runs_selected_models_in_sync_path(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    test_context["user"].credits = 100
    test_context["db"].add(test_context["user"])
    test_context["db"].commit()
    test_context["db"].refresh(test_context["user"])

    # A client-submitted provider + selected_models is discarded on every plan
    # (_strip_client_model_selection, SIGV2-1139), which collapses the
    # multi-model fan-out to a single audit. This test is about the sync
    # consensus execution path rather than the gate, so the strip is replaced
    # with a pass-through here, the same way test_audit_routing_endpoints.py
    # does it. The plan_executive subscription below keeps the request on a
    # real top-tier plan.
    from routers import api_router as api_module

    monkeypatch.setattr(
        api_module,
        "_strip_client_model_selection",
        lambda *, provider, selected_models: (provider, selected_models),
    )
    routing_subscription = models.Subscription(
        user_id=test_context["user"].id,
        stripe_customer_id=f"cus_multi_model_{test_context['user'].id}",
        plan_type="plan_executive",
        status="active",
    )
    test_context["db"].add(routing_subscription)
    test_context["db"].commit()
    test_context["db"].refresh(test_context["user"])

    project = _create_project_for_user(
        test_context,
        name="Sync Multi Model Audit",
        domain_url="https://sync-multi-model.example",
    )

    perform_audit_mock = AsyncMock(
        side_effect=[
            (
                {
                    "analysis": {"seo_score": 79, "geo_score": 80, "aeo_score": 81},
                    "metadata": {
                        "audit_outcome": "completed",
                        "provider": "openai",
                        "tier": "smart",
                    },
                },
                {"seo": 79.0, "geo": 80.0, "aeo": 81.0, "overall": 80.0},
            ),
            (
                {
                    "analysis": {"seo_score": 77, "geo_score": 78, "aeo_score": 79},
                    "metadata": {
                        "audit_outcome": "completed",
                        "provider": "anthropic",
                        "tier": "smart",
                    },
                },
                {"seo": 77.0, "geo": 78.0, "aeo": 79.0, "overall": 78.0},
            ),
        ]
    )
    synthesize_mock = AsyncMock(
        return_value={
            "analysis": {"seo_score": 80, "geo_score": 81, "aeo_score": 82},
            "metadata": {"audit_outcome": "completed"},
        }
    )
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(
        main.api_module.audit_consensus_ai_factory,
        "synthesize_multi_model_results",
        synthesize_mock,
    )

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-sync-multi-model"},
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Logistics",
            "provider": "openai",
            "selected_models": ["openai", "anthropic"],
            "tier": "deep",
            "project_id": project.id,
        },
    )

    payload = response.json()
    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 2
    assert [call.kwargs["provider"] for call in perform_audit_mock.await_args_list] == [
        "openai",
        "anthropic",
    ]
    assert synthesize_mock.await_count == 1
    assert payload["report"]["metadata"]["selected_models"] == ["openai", "anthropic"]
    # The user's selected models are preserved for the per-model fan-out, but the
    # Bedrock cutover collapses the routed reasoning provider to "bedrock", so the
    # routing_mode is the runtime-fallback variant rather than a literal
    # "user_selected_provider".
    assert (
        payload["report"]["metadata"]["routing_mode"] == "user_selected_provider_runtime_fallback"
    )
    assert persisted_audit is not None
    assert persisted_audit.full_report["metadata"]["selected_models"] == ["openai", "anthropic"]


def test_create_audit_job_allows_brand_without_url_and_queues_nullable_target_url(
    test_context,
):
    project = _create_project_for_user(
        test_context,
        name="Queued Brand Audit",
        domain_url="https://queued-brand.example",
    )

    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-brand-job-no-url"},
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Logistics",
            "target_metadata": {"category": "logistics", "market": "ro"},
            "provider": "google",
            "tier": "fast",
            "project_id": project.id,
        },
    )

    payload = response.json()
    persisted_job = (
        test_context["db"]
        .query(models.AuditJob)
        .filter(models.AuditJob.id == payload["job_id"])
        .first()
    )
    queued_payload = json.loads(test_context["redis_calls"]["rpush"][0]["value"])

    assert response.status_code == 200
    assert payload["audit_target_type"] == "brand"
    assert payload["target_name"] == "Acme Logistics"
    assert payload["target_url"] is None
    assert persisted_job is not None
    assert persisted_job.project_id == project.id
    assert persisted_job.audit_target_type == models.AuditTargetType.BRAND
    assert persisted_job.target_name == "Acme Logistics"
    assert persisted_job.target_url is None
    assert persisted_job.url == ""
    assert queued_payload["audit_target_type"] == "brand"
    assert queued_payload["target_name"] == "Acme Logistics"
    assert queued_payload["target_url"] is None
    assert queued_payload["target_metadata"] == {"category": "logistics", "market": "ro"}
    assert queued_payload["project_id"] == project.id
    assert queued_payload["url"] == ""


def test_stream_audit_job_events_returns_status_and_sanitized_debate_events(test_context):
    job = models.AuditJob(
        id="job-events-1",
        user_id=test_context["user"].id,
        project_id=test_context["project"].id,
        status="running",
        url="https://example.com",
        request_id="req-events-1",
    )
    test_context["db"].add(job)
    test_context["db"].commit()

    test_context["redis_store"]["audit:job:job-events-1"] = {
        "status": "succeeded",
        "audit_id": "321",
        "requested_tier": "deep_judgment",
    }
    test_context["redis_store"]["audit:job:job-events-1:events"] = [
        json.dumps(
            {
                "type": "pipeline_started",
                "pipeline_type": "delta_flow",
                "total_agents": 8,
                "parallel_layers": 2,
                "estimated_duration_s": 480,
            }
        ),
        json.dumps(
            {
                "type": "layer_started",
                "pipeline_type": "delta_flow",
                "layer": 1,
                "layer_name": "Specialized Generation",
                "agents_in_layer": 3,
                "parallel": True,
            }
        ),
        json.dumps(
            {
                "type": "step_started",
                "role": "proposer",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-test",
            }
        ),
        json.dumps(
            {
                "type": "step_completed",
                "role": "proposer",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-test",
                "status": "completed",
                "summary": "Grounded summary",
                "latency_ms": 420,
            }
        ),
    ]

    response = test_context["client"].get("/api/v1/audit/jobs/job-events-1/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: job_status" in response.text
    assert '"status": "succeeded"' in response.text
    assert "event: pipeline_started" in response.text
    assert '"pipeline_type": "delta_flow"' in response.text
    assert "event: layer_started" in response.text
    assert '"layer_name": "Specialized Generation"' in response.text
    assert "event: step_started" in response.text
    assert '"model": "gemini-test"' in response.text
    assert "event: step_completed" in response.text
    assert '"summary": "Grounded summary"' in response.text


def test_create_audit_job_returns_500_when_db_commit_programming_error(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    rollback_calls: list[bool] = []

    # Only fail the AuditJob-persisting commit (see integrity-error test note).
    real_commit = test_context["db"].commit

    def raise_programming_error():
        if any(isinstance(obj, models.AuditJob) for obj in test_context["db"].new):
            raise ProgrammingError(
                "insert into audit_jobs",
                {},
                Exception('relation "audit_jobs" does not exist'),
            )
        return real_commit()

    def record_rollback():
        rollback_calls.append(True)

    monkeypatch.setattr(test_context["db"], "commit", raise_programming_error)
    monkeypatch.setattr(test_context["db"], "rollback", record_rollback)

    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-job-programming-error"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save audit to database."
    assert rollback_calls == [True]


def test_create_audit_job_returns_500_when_db_commit_unexpected_error(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    rollback_calls: list[bool] = []

    # Only fail the AuditJob-persisting commit (see integrity-error test note).
    real_commit = test_context["db"].commit

    def raise_unexpected_error():
        if any(isinstance(obj, models.AuditJob) for obj in test_context["db"].new):
            raise RuntimeError("database unavailable")
        return real_commit()

    def record_rollback():
        rollback_calls.append(True)

    monkeypatch.setattr(test_context["db"], "commit", raise_unexpected_error)
    monkeypatch.setattr(test_context["db"], "rollback", record_rollback)

    response = test_context["client"].post(
        "/api/v1/audit/jobs",
        headers={"X-Request-ID": "req-job-unexpected-error"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save audit to database."
    assert rollback_calls == [True]


@pytest.mark.parametrize("raw_url", ["htp://bad", "example.com", "http://exa mple.com"])
def test_create_guest_audit_returns_400_for_invalid_url_formats(test_context, raw_url: str):
    response = test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-invalid-guest-url"},
        json={"url": raw_url},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"] == "Invalid URL format. URL must start with http:// or https://."
    )


def test_create_guest_audit_brand_mode_requires_target_name_or_entity(test_context):
    response = test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-brand-missing-target"},
        json={"audit_target_type": "brand"},
    )

    assert response.status_code == 422
    error_messages = [entry["msg"] for entry in response.json().get("detail", [])]
    assert any(
        "Brand audits require target_name or entity." in message for message in error_messages
    )


def test_create_guest_audit_brand_mode_without_url_returns_target_aware_payload(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    scraper_mock = AsyncMock(return_value={"success_status": True, "markdown_content": "ignored"})
    perf_mock = AsyncMock(return_value={"performance_score": 99, "seo_audits": []})
    network_mock = AsyncMock(return_value={"supports_http2": True, "supports_http3_inferred": True})
    ai_mock = AsyncMock(
        return_value={
            "analysis": {
                "intelligence_summary": "Brand context processed.",
                "detailed_recommendations": [
                    {
                        "agent": "Semantic Engine",
                        "finding": "Strengthen entity profile",
                        "why_it_matters": "Low entity clarity reduces citation probability.",
                        "fix": "Add structured data and consolidate brand mentions.",
                    }
                ],
                "aeo_teaser": "Answer engines can cite this brand more consistently.",
            }
        }
    )

    monkeypatch.setattr(
        guest_audit_service.scraper_service, "get_page_content_and_screenshot", scraper_mock
    )
    monkeypatch.setattr(
        guest_audit_service.performance_service, "get_performance_metrics", perf_mock
    )
    monkeypatch.setattr(
        guest_audit_service.network_service, "analyze_network_protocols", network_mock
    )
    monkeypatch.setattr(guest_audit_service.ai_client, "generate_audit", ai_mock)

    response = test_context["client"].post(
        "/api/v1/guest-audit",
        headers={"X-Request-ID": "req-guest-brand-no-url"},
        json={
            "audit_target_type": "brand",
            "target_name": "Acme Logistics",
            "target_metadata": {"industry": "logistics"},
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["target"]["type"] == "brand"
    assert payload["target"]["name"] == "Acme Logistics"
    assert payload["target"]["url"] is None
    assert payload["metadata"]["audit_target_type"] == "brand"
    assert payload["metadata"]["target_name"] == "Acme Logistics"
    assert payload["metadata"]["target_metadata"] == {"industry": "logistics"}
    assert payload["score_groups"][0]["locked"] is True
    assert "technical performance and protocol checks were skipped" in payload["insights"][0]
    assert scraper_mock.await_count == 0
    assert perf_mock.await_count == 0
    assert network_mock.await_count == 0
    assert ai_mock.await_count == 1
    assert "Target type: brand" in ai_mock.await_args.kwargs["content"]

    # Verify detailed_seo_recommendations are mapped to the frontend contract shape
    recs = payload["detailed_seo_recommendations"]
    assert len(recs) == 1
    assert recs[0]["source"] == "Semantic Engine"
    assert recs[0]["title"] == "Strengthen entity profile"
    assert recs[0]["description"] == "Low entity clarity reduces citation probability."
    assert recs[0]["implementation"] == "Add structured data and consolidate brand mentions."
    assert recs[0]["priority"] == "Warning"


def test_create_audit_uses_cache_hit_without_running_audit(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    # The cache subject is request.resolved_target_url(), which serializes the
    # HttpUrl with a trailing slash ("https://example.com/"). The Bedrock cutover
    # collapses the routed provider to "bedrock" (route.provider), which is what
    # the endpoint uses to build the cache key.
    normalized_url = "https://example.com/"
    cache_key = main.build_audit_cache_key(
        normalized_url,
        "bedrock",
        "fast",
        f"project:{test_context['project'].id}|requested_tier:fast",
    )
    dedup_key = build_dedup_key(
        user_id=test_context["user"].id,
        target_url=normalized_url,
        target_name=normalized_url,
        tier="fast",
        project_id=test_context["project"].id,
    )
    cached_report = {
        "analysis": {"seo_score": 81, "geo_score": 75, "aeo_score": 72},
        "metadata": {"plan": "plan_starter"},
    }
    test_context["redis_store"][cache_key] = json.dumps(
        {
            "report": cached_report,
            "scores": {"seo": 76, "geo": 76, "aeo": 76, "overall": 76},
            "metadata": {"content_hash": "same-signature"},
        }
    )

    perform_audit_mock = AsyncMock(
        return_value=({}, {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0})
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "same-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-cache-hit"},
        json={
            "url": "https://example.com",
            "project_id": test_context["project"].id,
            "provider": "google",
            "tier": "fast",
        },
    )

    payload = response.json()
    test_context["db"].refresh(test_context["user"])

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 0
    assert payload["audit_id"] > 0
    # The dedup pre-check issues a GET before the cache lookup GET, so both keys
    # are read (in that order).
    assert test_context["redis_calls"]["get"] == [dedup_key, cache_key]
    assert payload["request_id"] == "req-cache-hit"
    assert payload["report"]["site"]["url"].rstrip("/") == normalized_url.rstrip("/")
    assert test_context["redis_calls"]["set"] == []


def test_create_audit_does_not_use_cache_when_signature_fetch_fails(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    normalized_url = "https://example-cache-failure.com"
    cache_key = main.build_audit_cache_key(
        normalized_url,
        "google",
        "fast",
        f"project:{test_context['project'].id}|requested_tier:fast",
    )
    test_context["redis_store"][cache_key] = json.dumps(
        {
            "report": {"analysis": {"seo_score": 71, "geo_score": 72, "aeo_score": 73}},
            "scores": {"seo": 72, "geo": 72, "aeo": 72, "overall": 72},
            "metadata": {"content_hash": "possibly-stale"},
        }
    )

    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    fetch_signature_mock = AsyncMock(side_effect=RuntimeError("head request failed"))
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-cache-signature-failed"},
        json={
            "url": normalized_url,
            "project_id": test_context["project"].id,
            "provider": "google",
            "tier": "fast",
        },
    )

    payload = response.json()
    test_context["db"].refresh(test_context["user"])

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1
    assert len(test_context["redis_calls"]["set"]) == 1
    assert payload["request_id"] == "req-cache-signature-failed"
    assert payload["report"]["site"]["url"].rstrip("/") == normalized_url


def test_create_audit_bypass_cache_forces_fresh_run_and_marks_metadata(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    normalized_url = "https://example-bypass-cache.com"
    cache_key = main.build_audit_cache_key(
        normalized_url,
        "bedrock",
        "fast",
        f"project:{test_context['project'].id}|requested_tier:fast",
    )
    dedup_key = build_dedup_key(
        user_id=test_context["user"].id,
        target_url=normalized_url,
        target_name=normalized_url,
        tier="fast",
        project_id=test_context["project"].id,
    )
    test_context["redis_store"][cache_key] = json.dumps(
        {
            "report": {
                "analysis": {"seo_score": 40, "geo_score": 41, "aeo_score": 42},
                "metadata": {"cache_behavior": "default", "cache_state": "hit"},
            },
            "scores": {"seo": 41, "geo": 41, "aeo": 41, "overall": 41},
            "metadata": {"content_hash": "same-signature"},
        }
    )

    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "same-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-cache-bypass"},
        json={
            "url": normalized_url,
            "project_id": test_context["project"].id,
            "provider": "google",
            "tier": "fast",
            "cache_behavior": "bypass",
        },
    )

    payload = response.json()
    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1
    # cache_behavior=bypass skips the cache-lookup GET entirely; the only GET is
    # the dedup pre-check (and notably NOT the cache_key).
    assert test_context["redis_calls"]["get"] == [dedup_key]
    assert cache_key not in test_context["redis_calls"]["get"]
    assert len(test_context["redis_calls"]["set"]) == 1
    assert payload["request_id"] == "req-cache-bypass"
    assert payload["report"]["metadata"]["cache_behavior"] == "bypass"
    assert payload["report"]["metadata"]["cache_state"] == "bypass"
    assert persisted_audit is not None
    assert persisted_audit.full_report["metadata"]["cache_behavior"] == "bypass"
    assert persisted_audit.full_report["metadata"]["cache_state"] == "bypass"


def test_create_audit_returns_503_when_ai_service_is_unavailable(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    perform_audit_mock = AsyncMock(
        side_effect=main.HTTPException(
            status_code=503,
            detail="AI analysis is currently unavailable; please retry shortly.",
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-ai-unavailable"},
        json={
            "url": "https://example.com",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    assert response.status_code == 503
    assert (
        response.json()["detail"] == "AI analysis is currently unavailable; please retry shortly."
    )
    assert perform_audit_mock.await_count == 1


def test_create_audit_runs_audit_and_caches_on_cache_miss_and_decrements_credits(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    normalized_url = "https://example.org"
    cache_key = main.build_audit_cache_key(
        normalized_url,
        "google",
        "fast",
        f"project:{test_context['project'].id}|requested_tier:fast",
    )
    test_context["redis_store"][cache_key] = json.dumps(
        {
            "report": {"analysis": {"seo_score": 40, "geo_score": 41, "aeo_score": 42}},
            "scores": {"seo": 41, "geo": 41, "aeo": 41, "overall": 41},
            "metadata": {"content_hash": "stale-signature"},
        }
    )

    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-cache-miss"},
        json={
            "url": "https://example.org",
            "project_id": test_context["project"].id,
            "provider": "google",
            "tier": "fast",
        },
    )

    payload = response.json()
    test_context["db"].refresh(test_context["user"])

    assert response.status_code == 200
    assert perform_audit_mock.await_count == 1
    assert len(test_context["redis_calls"]["set"]) == 1
    assert payload["audit_id"] > 0
    assert payload["request_id"] == "req-cache-miss"
    assert payload["report"]["site"]["url"].rstrip("/") == normalized_url

    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )
    assert persisted_audit is not None
    assert persisted_audit.geo_score == pytest.approx(88.0)
    assert persisted_audit.seo_score == pytest.approx(91.0)
    assert persisted_audit.aeo_score == pytest.approx(84.0)


def test_create_audit_persists_provider_and_tier_metadata_when_provider_missing(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 65, "geo_score": 55, "aeo_score": 75},
                "metadata": {"plan": "plan_starter", "model": "gpt-5.4"},
            },
            {"seo": 65.0, "geo": 55.0, "aeo": 75.0, "overall": 65.0},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-provider-tier-persist"},
        json={
            "url": "https://example-provider-tier.com",
            "provider": "google",
            "tier": "smart",
            "project_id": test_context["project"].id,
        },
    )

    payload = response.json()
    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )

    assert response.status_code == 200
    assert persisted_audit is not None
    metadata = persisted_audit.full_report.get("metadata", {})
    assert metadata.get("provider") == "gpt-5.4"
    assert metadata.get("tier") == "smart"


def test_create_audit_propagates_market_and_language_to_response_and_db(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 81, "geo_score": 79, "aeo_score": 77},
                "metadata": {
                    "plan": "plan_starter",
                    "market": "ro",
                    "language": "ro",
                    "intent": "transactional",
                },
            },
            {"seo": 81.0, "geo": 79.0, "aeo": 77.0, "overall": 79.0},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-market-language"},
        json={
            "url": "https://example-market-language.com",
            "provider": "google",
            "tier": "fast",
            "market": "ro",
            "language": "ro",
            "project_id": test_context["project"].id,
        },
    )

    payload = response.json()
    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == payload["audit_id"])
        .first()
    )

    assert response.status_code == 200
    assert payload["report"]["site"]["market"] == "ro"
    assert payload["report"]["site"]["language"] == "ro"
    assert persisted_audit is not None
    assert persisted_audit.full_report["site"]["market"] == "ro"
    assert persisted_audit.full_report["site"]["language"] == "ro"
    assert persisted_audit.intent == "transactional"
    assert persisted_audit.query_type == "decision_making"


def test_create_audit_links_to_project_when_project_id_is_provided(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    workspace = models.Workspace(name="Agency", owner_id=test_context["user"].id)
    test_context["db"].add(workspace)
    test_context["db"].flush()
    project = models.Project(
        workspace_id=workspace.id,
        name="Client Alpha",
        domain_url="https://client-alpha.example",
        target_country="ro",
        language="ro",
    )
    test_context["db"].add(project)
    test_context["db"].commit()
    test_context["db"].refresh(project)

    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 81, "geo_score": 79, "aeo_score": 77},
                "metadata": {"plan": "plan_starter", "audit_outcome": "completed"},
            },
            {"seo": 81.0, "geo": 79.0, "aeo": 77.0, "overall": 79.0},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "project-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-project-linked"},
        json={
            "url": "https://client-alpha.example",
            "provider": "google",
            "tier": "smart",
            "project_id": project.id,
        },
    )

    assert response.status_code == 200
    await_kwargs = perform_audit_mock.await_args.kwargs
    assert await_kwargs["project_id"] == project.id

    persisted_audit = (
        test_context["db"]
        .query(models.Audit)
        .filter(models.Audit.id == response.json()["audit_id"])
        .first()
    )
    assert persisted_audit is not None
    assert persisted_audit.project_id == project.id
    assert persisted_audit.audit_type == models.AuditType.DEEP


def test_create_audit_rejects_project_not_owned_or_shared(
    test_context,
):
    another_user = models.User(
        email="another-owner@example.com",
        hashed_password="x",
        role="user",
        credits=5,
    )
    test_context["db"].add(another_user)
    test_context["db"].flush()
    foreign_workspace = models.Workspace(name="Foreign Agency", owner_id=another_user.id)
    test_context["db"].add(foreign_workspace)
    test_context["db"].flush()
    foreign_project = models.Project(
        workspace_id=foreign_workspace.id,
        name="Foreign Client",
        domain_url="https://foreign.example",
    )
    test_context["db"].add(foreign_project)
    test_context["db"].commit()

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-project-forbidden"},
        json={
            "url": "https://foreign.example",
            "provider": "google",
            "tier": "fast",
            "project_id": foreign_project.id,
        },
    )

    assert response.status_code == 403
    # The project is in a workspace the user has no membership in, so RBAC
    # (resolve_project_access_service -> assert_workspace_member) rejects at the
    # workspace gate before any project-level assignment check.
    assert response.json()["detail"] == "Not authorized for this workspace."


def test_newly_created_audit_history_and_detail_include_score_fields(
    lightweight_context,
    monkeypatch: pytest.MonkeyPatch,
):
    import routers.api_router as api_module
    from services.ai_routing_policy import provider_runtime_state_service

    project = _create_project_for_user(
        lightweight_context,
        name="Score History Project",
        domain_url="https://example-scores.com",
    )
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "analysis": {"seo_score": 91, "geo_score": 88, "aeo_score": 84},
                "metadata": {"plan": "plan_starter"},
            },
            {"seo": 91.0, "geo": 88.0, "aeo": 84.0, "overall": 87.67},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(api_module, "fetch_url_signature", fetch_signature_mock)
    monkeypatch.setattr(
        api_module, "enforce_authenticated_audit_limit", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="healthy"),
    )
    import core.redis_client as _redis_client

    monkeypatch.setattr(
        _redis_client.async_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(
            {}, {"get": [], "set": [], "hset": [], "rpush": [], "close": []}
        ),
    )
    monkeypatch.setattr(
        _redis_client.sync_redis_lib,
        "from_url",
        lambda *_args, **_kwargs: FakeRedisClient(
            {}, {"get": [], "set": [], "hset": [], "rpush": [], "close": []}
        ),
    )

    create_payload = asyncio.run(
        api_module.create_audit(
            user=lightweight_context["user"],
            request=api_module.AuditRequest(
                url="https://example-scores.com",
                provider="google",
                tier="fast",
                project_id=project.id,
            ),
            http_request=_build_handler_request("req-history-detail-scores"),
            db=lightweight_context["db"],
        )
    )

    audit_id = create_payload["audit_id"]

    persisted_audit = (
        lightweight_context["db"].query(models.Audit).filter(models.Audit.id == audit_id).one()
    )
    assert persisted_audit.project_id == project.id
    assert persisted_audit.geo_score == pytest.approx(88.0)
    assert persisted_audit.seo_score == pytest.approx(91.0)
    assert persisted_audit.aeo_score == pytest.approx(84.0)

    detail_payload = api_module.get_audit_record(
        audit_id=audit_id,
        user=lightweight_context["user"],
        db=lightweight_context["db"],
    )
    assert detail_payload["geo_score"] == pytest.approx(88.0)
    assert detail_payload["seo_score"] == pytest.approx(91.0)
    assert detail_payload["aeo_score"] == pytest.approx(84.0)


def test_create_audit_returns_200_with_external_service_failure_metadata(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "site": {"url": "https://example.net", "market": "global", "language": "en"},
                "seo": {"onpage": 0, "performance": 92, "indexing": 0},
                "geo": {"visibility_index": 0, "citation_share": 0, "brand_anchor": 0},
                "aeo": {"answerability_score": 0, "extractable_pages": 0},
                "entities": [],
                "competitors": [],
                "suggestions": [],
                "scores": {"seo": 0, "geo": 0, "aeo": 0, "overall": 0},
                "metadata": {
                    "plan": "plan_starter",
                    "version": "2.0",
                    "service_status": {
                        "firecrawl": "disabled",
                        "ai_service": "disabled",
                        "pagespeed": "ok",
                        "network": "ok",
                    },
                    "service_errors": {
                        "firecrawl": "{'error_code': 'timeout', 'message': 'Firecrawl timeout'}",
                        "ai_service": "Skipped because scraping failed.",
                    },
                },
            },
            {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-service-failure"},
        json={
            "url": "https://example.net",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    payload = response.json()

    assert response.status_code == 200
    assert payload["request_id"] == "req-service-failure"
    assert payload["report"]["metadata"]["service_status"]["firecrawl"] == "disabled"
    assert payload["report"]["metadata"]["service_status"]["pagespeed"] == "ok"
    assert payload["report"]["metadata"]["service_status"]["network"] == "ok"
    assert payload["report"]["metadata"]["service_errors"]["firecrawl"]


def test_create_audit_does_not_decrement_credits_for_ai_outage_failed_outcome(
    test_context,
    monkeypatch: pytest.MonkeyPatch,
):
    # A total AI outage yields NO usable scores, so the pipeline resolves the
    # outcome to "failed" (audit_runner: ai_status != ok and not scores_available
    # -> AUDIT_OUTCOME_FAILED). Failed outcomes are non-billable, so credits must
    # not be decremented. The billability check (is_billable_audit_outcome) reads
    # metadata.audit_outcome, which is where the pipeline records the outcome.
    perform_audit_mock = AsyncMock(
        return_value=(
            {
                "site": {
                    "url": "https://example-ai-outage.net",
                    "market": "global",
                    "language": "en",
                },
                "seo": {"onpage": 0, "performance": 0, "indexing": 0},
                "geo": {"visibility_index": 0, "citation_share": 0, "brand_anchor": 0},
                "aeo": {"answerability_score": 0, "extractable_pages": 0},
                "entities": [],
                "competitors": [],
                "suggestions": [],
                "scores": {"seo": 0, "geo": 0, "aeo": 0, "overall": 0},
                "metadata": {
                    "plan": "plan_starter",
                    "version": "2.0",
                    "audit_outcome": "failed",
                    "scores_available": False,
                    "service_status": {
                        "firecrawl": "ok",
                        "ai_service": "error",
                        "pagespeed": "ok",
                        "network": "ok",
                    },
                    "service_errors": {
                        "ai_service": "OpenAI request timed out.",
                    },
                },
            },
            {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0},
        )
    )
    fetch_signature_mock = AsyncMock(return_value={"content_hash": "fresh-signature"})
    monkeypatch.setattr(main.api_module, "perform_audit", perform_audit_mock)
    monkeypatch.setattr(main.api_module, "fetch_url_signature", fetch_signature_mock)

    response = test_context["client"].post(
        "/api/v1/audit",
        headers={"X-Request-ID": "req-ai-outage-failed"},
        json={
            "url": "https://example-ai-outage.net",
            "provider": "google",
            "tier": "fast",
            "project_id": test_context["project"].id,
        },
    )

    payload = response.json()
    test_context["db"].refresh(test_context["user"])

    assert response.status_code == 200
    assert payload["report"]["metadata"]["audit_outcome"] == "failed"
    assert payload["report"]["metadata"]["service_status"]["ai_service"] == "error"


def test_audit_preflight_returns_success_for_reachable_url(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    class PreflightClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(
            self, method: str, url: str, headers: dict[str, str] | None = None, **kwargs
        ):
            _ = headers
            return main.api_module.httpx.Response(
                200, request=main.api_module.httpx.Request(method, url)
            )

    monkeypatch.setattr(main.api_module.httpx, "AsyncClient", PreflightClient)

    response = test_context["client"].get(
        "/api/v1/audit/preflight", params={"url": "https://example.com"}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["method"] == "HEAD"


def test_audit_preflight_accepts_challenge_responses_as_reachable(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    class PreflightClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(
            self, method: str, url: str, headers: dict[str, str] | None = None, **kwargs
        ):
            _ = headers
            return main.api_module.httpx.Response(
                403, request=main.api_module.httpx.Request(method, url)
            )

    monkeypatch.setattr(main.api_module.httpx, "AsyncClient", PreflightClient)

    response = test_context["client"].get(
        "/api/v1/audit/preflight", params={"url": "https://example.com"}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["status_code"] == 403
    assert response.json()["method"] == "HEAD"


def test_audit_preflight_falls_back_to_get_when_head_probe_fails(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    class PreflightClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(
            self, method: str, url: str, headers: dict[str, str] | None = None, **kwargs
        ):
            _ = headers
            if method == "HEAD":
                raise main.api_module.httpx.RequestError(
                    "network down", request=main.api_module.httpx.Request("HEAD", url)
                )
            return main.api_module.httpx.Response(
                200, request=main.api_module.httpx.Request(method, url)
            )

    monkeypatch.setattr(main.api_module.httpx, "AsyncClient", PreflightClient)

    response = test_context["client"].get(
        "/api/v1/audit/preflight", params={"url": "https://example.com"}
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["method"] == "GET"


def test_audit_preflight_returns_502_when_all_reachability_probes_fail(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    class PreflightClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(
            self, method: str, url: str, headers: dict[str, str] | None = None, **kwargs
        ):
            _ = method, headers
            raise main.api_module.httpx.RequestError(
                "network down", request=main.api_module.httpx.Request("GET", url)
            )

    monkeypatch.setattr(main.api_module.httpx, "AsyncClient", PreflightClient)

    response = test_context["client"].get(
        "/api/v1/audit/preflight", params={"url": "https://example.com"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to reach the target URL."


def test_audit_preflight_returns_502_for_ssl_verification_errors(
    test_context, monkeypatch: pytest.MonkeyPatch
):
    class PreflightClient:
        def __init__(self, *args, **kwargs):
            _ = args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(
            self, method: str, url: str, headers: dict[str, str] | None = None, **kwargs
        ):
            _ = headers
            if method == "HEAD":
                raise main.api_module.httpx.RequestError(
                    "head probe failed", request=main.api_module.httpx.Request("HEAD", url)
                )
            raise main.api_module.httpx.RequestError(
                "[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed",
                request=main.api_module.httpx.Request(method, url),
            )

    monkeypatch.setattr(main.api_module.httpx, "AsyncClient", PreflightClient)

    response = test_context["client"].get(
        "/api/v1/audit/preflight", params={"url": "https://example.com"}
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Unable to reach the target URL."
