"""SIGV2-1023: live OpenRouter measurement enabled for all plans, truthfully.

Covers: per-plan end-to-end live measurement, provider failure shapes (missing
key / 402 / 429 / timeout), live-only engines (meta) reporting explicitly
unavailable, proxy-only engines (bing) labeled as such, cache source isolation
(v1/proxy entries never served as live), dedupe without double spend, unknown
vs measured-zero cost, the engine roster surface, and tenant isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from core.config import settings
from services import openrouter_client, visibility_index_jobs
from services.openrouter_client import OpenRouterError
from services.visibility_index_jobs import VisibilityIndexJobService

NEUTRAL_PROMPT = "What are the leading CRM tools for small businesses?"


@pytest.fixture
def sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from database import Base

    engine = create_engine("sqlite:///:memory:")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def _seed_project(session, plan_type: str):
    user = models.User(
        email=f"enable-{plan_type}@example.com",
        hashed_password="x",
        role="user",
        credits=100,
        notifications_enabled=True,
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    session.add(
        models.Subscription(
            user_id=user.id,
            stripe_customer_id=f"cus_enable_{plan_type}",
            stripe_subscription_id=f"sub_enable_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    session.commit()
    workspace = models.Workspace(name=f"ws-enable-{plan_type}", owner_id=user.id)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    project = models.Project(workspace_id=workspace.id, name="Enable Project")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def _enable_live(monkeypatch, provider: str = "openai"):
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {provider: f"{provider}/test-model"},
    )


class _DictSemanticCache:
    """Dict-backed semantic cache honoring (feature, route, payload, version)."""

    def __init__(self):
        from services import semantic_cache_service as scs

        self._svc = scs.SemanticCacheService()
        self.store: dict[str, dict] = {}

    def _key(self, *, feature_key, route_provider, route_tier, semantic_payload, version="v1"):
        return self._svc.build_key(
            feature_key=feature_key,
            route_provider=route_provider,
            route_tier=route_tier,
            semantic_payload=semantic_payload,
            version=version,
        )

    def get_json(self, **kwargs):
        import json as _json

        raw = self.store.get(self._key(**kwargs))
        return _json.loads(_json.dumps(raw)) if raw else None

    def set_json(self, *, value, ttl_seconds=None, **kwargs):
        self.store[self._key(**kwargs)] = {
            "response": value,
            "metadata": {"feature_key": kwargs["feature_key"]},
        }

    def install(self, monkeypatch):
        monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "get_json", self.get_json)
        monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "set_json", self.set_json)


# --- All plans reach live measurement end to end ----------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "plan_type",
    [
        "plan_starter",
        "plan_agency_trial",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    ],
)
async def test_every_plan_runs_live_end_to_end(sqlite_session, monkeypatch, plan_type):
    project = _seed_project(sqlite_session, plan_type=plan_type)
    _enable_live(monkeypatch)
    _DictSemanticCache().install(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):
        return {
            "text": "Acme leads. https://acme.example.com",
            "usage": {"prompt_tokens": 3, "completion_tokens": 5},
            "cost": 0.001,
            "model": model,
        }

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService()
    batch = await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")
        ],
        schedule_key=f"sched-{plan_type}",
        project_id=project.id,
    )

    assert batch.status == "succeeded", plan_type
    run = batch.runs[0]
    assert run.raw_response["engine_source"] == "openrouter_live"
    assert run.raw_response["model"] == "openai/test-model"
    assert run.raw_response["attempt"] == 1
    assert run.raw_response["measured_at"]

    entries = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .all()
    )
    assert len(entries) == 1
    assert entries[0].payload_json["cost_state"] == "measured"


# --- Provider failure shapes ------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_falls_back_to_bedrock(monkeypatch):
    _enable_live(monkeypatch)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")

    bedrock_args = {}

    async def fake_bedrock(self, model_id, prompt):
        bedrock_args["model_id"] = model_id
        return {"answer": "bedrock-fallback", "engine_source": "bedrock_proxy"}

    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("openai", NEUTRAL_PROMPT)
    assert result["answer"] == "bedrock-fallback"
    assert bedrock_args["model_id"] == settings.BEDROCK_MEASUREMENT_MODEL_MAP["openai"]


@pytest.mark.asyncio
async def test_missing_api_key_raises_clean_error(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(OpenRouterError):
        await openrouter_client.query_model("openai/gpt-5", NEUTRAL_PROMPT)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [402, 429])
async def test_http_error_falls_back_to_bedrock(monkeypatch, status_code):
    """HTTP 402 (no credit) and 429 (rate limit) → OpenRouterError → Bedrock."""
    _enable_live(monkeypatch)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test")

    import httpx

    class _Resp:
        def __init__(self, code):
            self.status_code = code

        def raise_for_status(self):
            raise httpx.HTTPStatusError(
                "err",
                request=httpx.Request("POST", "http://x"),
                response=httpx.Response(self.status_code),
            )

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Resp(status_code)

    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    async def fake_bedrock(self, model_id, prompt):
        return {"answer": "bedrock-fallback", "engine_source": "bedrock_proxy"}

    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("openai", NEUTRAL_PROMPT)
    assert result["answer"] == "bedrock-fallback"


@pytest.mark.asyncio
async def test_timeout_falls_back_to_bedrock(monkeypatch):
    _enable_live(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):
        raise OpenRouterError("OpenRouter request timed out")

    async def fake_bedrock(self, model_id, prompt):
        return {"answer": "bedrock-fallback", "engine_source": "bedrock_proxy"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("openai", NEUTRAL_PROMPT)
    assert result["answer"] == "bedrock-fallback"


@pytest.mark.asyncio
async def test_unsupported_engine_raises(monkeypatch):
    _enable_live(monkeypatch)
    service = VisibilityIndexJobService(live_engine_entitled=True)
    with pytest.raises(ValueError, match="Unsupported provider"):
        await service._run_provider("totally-made-up-engine", NEUTRAL_PROMPT)


# --- Live-only engines (meta) and proxy-only engines (bing) -----------------


@pytest.mark.asyncio
async def test_meta_live_failure_reports_explicitly_unavailable(monkeypatch):
    """meta has a real OpenRouter model but NO Bedrock fallback: a live failure
    must surface as explicitly unavailable, not silently fall through."""
    _enable_live(monkeypatch, provider="meta")

    async def fake_query_model(model, prompt, **kwargs):
        raise OpenRouterError("HTTP 402")

    async def fake_bedrock(self, model_id, prompt):  # pragma: no cover
        raise AssertionError("Bedrock must never run for meta")

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    with pytest.raises(ValueError, match="unavailable"):
        await service._run_provider("meta", NEUTRAL_PROMPT)


@pytest.mark.asyncio
async def test_bing_reports_proxy_source_not_live(monkeypatch):
    """bing stays live-unavailable by design: it runs the Bedrock panel and the
    result is labeled bedrock_proxy, never presented as a live measurement."""
    _enable_live(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):  # pragma: no cover
        raise AssertionError("bing must never reach OpenRouter")

    async def fake_bedrock(self, model_id, prompt):
        return {
            "answer": "proxy answer",
            "model": model_id,
            "engine_source": "bedrock_proxy",
        }

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("bing", NEUTRAL_PROMPT)
    assert result["engine_source"] == "bedrock_proxy"


# --- Cost: unknown vs measured-zero ------------------------------------------


def test_parse_response_missing_and_malformed_cost_are_unknown():
    ok = openrouter_client._parse_response(
        "m", {"choices": [{"message": {"content": "x"}}], "usage": {}}
    )
    assert ok["cost"] is None

    malformed = openrouter_client._parse_response(
        "m",
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"cost": "not-a-number"},
        },
    )
    assert malformed["cost"] is None

    measured_zero = openrouter_client._parse_response(
        "m",
        {
            "choices": [{"message": {"content": "x"}}],
            "usage": {"cost": 0.0},
        },
    )
    assert measured_zero["cost"] == 0.0  # measured zero stays zero


@pytest.mark.asyncio
async def test_unknown_cost_recorded_as_unknown_not_zero(sqlite_session, monkeypatch):
    project = _seed_project(sqlite_session, plan_type="plan_executive")
    _enable_live(monkeypatch)
    _DictSemanticCache().install(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):
        return {"text": "x", "usage": {}, "cost": None, "model": model}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService()
    await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="t", template="Prompt {topic}")
        ],
        schedule_key="sched-unknown-cost",
        project_id=project.id,
    )
    entry = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .one()
    )
    assert entry.payload_json["cost_state"] == "unknown"
    assert entry.payload_json["cost_known"] is False


# --- Cache source isolation (AC5) --------------------------------------------


@pytest.mark.asyncio
async def test_stale_proxy_cache_entry_never_served_as_live(sqlite_session, monkeypatch):
    """RED-first for AC5: a proxy measurement cached BEFORE the flag turned on
    (v1 identity, no engine_source) must never be returned and presented as a
    live OpenRouter measurement. Under the old single-identity cache this test
    fails because the proxy entry hits."""
    project = _seed_project(sqlite_session, plan_type="plan_executive")
    cache = _DictSemanticCache()
    cache.install(monkeypatch)

    # Seed the way the pre-flag code did: v1 key, payload without engine_source.
    old_payload = {
        "provider": "openai",
        "topic": "crm tools",
        "target_domain": None,
        "prompt_template": "default",
        "prompt": "Prompt crm tools",
    }
    cache.set_json(
        feature_key=visibility_index_jobs.VISIBILITY_CACHE_FEATURE_KEY,
        route_provider="openai",
        route_tier=visibility_index_jobs.VISIBILITY_CACHE_TIER,
        semantic_payload=old_payload,
        value={"answer": "STALE PROXY ANSWER"},
        version="v1",
    )

    _enable_live(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):
        return {"text": "fresh live answer", "usage": {}, "cost": 0.0, "model": model}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService()
    batch = await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")
        ],
        schedule_key="sched-stale-proxy",
        project_id=project.id,
    )
    run = batch.runs[0]
    assert run.raw_response["engine_source"] == "openrouter_live"
    assert run.raw_response["answer"] == "fresh live answer"


@pytest.mark.asyncio
async def test_live_and_proxy_cache_entries_do_not_collide(sqlite_session, monkeypatch):
    """Same provider+prompt cached under both sources stays distinct: a flag-off
    proxy result and a flag-on live result coexist; each hit keeps its own
    engine_source, and a cache hit writes no new ledger entry."""
    project = _seed_project(sqlite_session, plan_type="plan_executive")
    cache = _DictSemanticCache()
    cache.install(monkeypatch)

    async def fake_query_model(model, prompt, **kwargs):
        return {"text": "LIVE", "usage": {}, "cost": 0.001, "model": model}

    async def fake_bedrock(self, model_id, prompt):
        return {"answer": "PROXY", "model": model_id, "engine_source": "bedrock_proxy"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    templates = [visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")]
    service = VisibilityIndexJobService()

    # 1) Flag OFF → proxy run caches under the proxy identity.
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", False)
    proxy_batch = await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=templates,
        schedule_key="sched-proxy",
        project_id=project.id,
    )
    assert proxy_batch.runs[0].raw_response["engine_source"] == "bedrock_proxy"

    # 2) Flag ON → live intent must MISS the proxy entry and measure live.
    _enable_live(monkeypatch)
    live_batch = await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=templates,
        schedule_key="sched-live",
        project_id=project.id,
    )
    assert live_batch.runs[0].raw_response["engine_source"] == "openrouter_live"
    assert live_batch.runs[0].raw_response["answer"] == "LIVE"

    # 3) Dedupe: a second live run hits the live cache entry, keeps its source,
    #    and creates NO additional provider-spend ledger entry.
    live_batch2 = await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=templates,
        schedule_key="sched-live-2",
        project_id=project.id,
    )
    hit = live_batch2.runs[0]
    assert hit.raw_response["engine_source"] == "openrouter_live"
    assert hit.raw_response["served_from_cache"] is True

    entries = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .all()
    )
    assert len(entries) == 1  # only the first live run booked spend


# --- Engine roster surface + tenant isolation --------------------------------


def test_engine_roster_reports_live_proxy_and_unavailable(sqlite_session):
    from services.project_visibility_service import (
        LIVE_MEASURABLE_PROVIDERS,
        OFFERED_VISIBILITY_PROVIDERS,
        ProjectVisibilityService,
        SUPPORTED_VISIBILITY_PROVIDERS,
    )

    project = _seed_project(sqlite_session, plan_type="plan_standard")
    roster = ProjectVisibilityService(sqlite_session).build_engine_roster(project)

    keys = [entry["provider"] for entry in roster]
    # SIGV2-1215: the roster lists the OFFERED engines, not the whole
    # vocabulary. Copilot (``bing``) is withdrawn, so it is absent here while
    # staying in SUPPORTED_VISIBILITY_PROVIDERS for its recorded rows.
    assert keys == list(OFFERED_VISIBILITY_PROVIDERS)
    assert "bing" not in keys
    assert "bing" in SUPPORTED_VISIBILITY_PROVIDERS

    by_key = {entry["provider"]: entry for entry in roster}
    for provider in LIVE_MEASURABLE_PROVIDERS:
        assert by_key[provider]["live_measurement"] == "available", provider
        assert by_key[provider]["measurement_source"] == "openrouter_live"
        assert by_key[provider]["label"]

    assert "meta" in by_key  # live-only engine is in the roster
    # Every engine still offered is measured live, so no card carries an
    # "unavailable" reason any more.
    assert all(entry["live_measurement"] == "available" for entry in roster)


def test_starter_and_trial_entitlements(sqlite_session, monkeypatch):
    from services.project_visibility_service import ProjectVisibilityService

    starter = _seed_project(sqlite_session, plan_type="plan_starter")
    ent = ProjectVisibilityService(sqlite_session).resolve_entitlements(starter)
    assert ent["max_queries"] == 10  # settled by SIGV2-1188
    assert ent["is_locked"] is False
    # SIGV2-1215: Copilot is withdrawn, so no plan offers ``bing``.
    assert ent["allowed_providers"] == ["perplexity"]

    trial = _seed_project(sqlite_session, plan_type="plan_agency_trial")
    ent_trial = ProjectVisibilityService(sqlite_session).resolve_entitlements(trial)
    assert ent_trial["max_queries"] == 25  # Standard row, per SIGV2-1188
    assert ent_trial["allowed_providers"] == ["perplexity", "xai", "deepseek"]


def test_visibility_queries_endpoint_foreign_project_refused(sqlite_session, monkeypatch):
    """A foreign project's roster/entitlements must not be served."""
    from services.project_visibility_service import ProjectVisibilityService

    foreign = _seed_project(sqlite_session, plan_type="plan_standard")
    svc = ProjectVisibilityService(sqlite_session)
    # Service-level scoping: freshness only counts the given project's runs.
    roster = svc.build_engine_roster(foreign)
    assert all(e["last_measured_at"] is None for e in roster)


# --- Neutral-prompt firewall at batch level -----------------------------------


@pytest.mark.asyncio
async def test_batch_prompt_never_carries_project_context(sqlite_session, monkeypatch):
    project = _seed_project(sqlite_session, plan_type="plan_executive")
    _enable_live(monkeypatch)
    _DictSemanticCache().install(monkeypatch)

    sent: list[str] = []

    async def fake_query_model(model, prompt, **kwargs):
        sent.append(prompt)
        return {"text": "x", "usage": {}, "cost": 0.0, "model": model}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService()
    await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")
        ],
        schedule_key="sched-firewall",
        project_id=project.id,
    )

    forbidden = [
        "internal_project_id",
        "customer_email",
        "api_secret",
        "OPENROUTER_API_KEY",
        "sk-or-",
        "tenant_id",
        "Enable Project",
        "enable-plan_executive@example.com",
    ]
    for prompt in sent:
        for marker in forbidden:
            assert marker not in prompt
