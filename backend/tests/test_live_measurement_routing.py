import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services import openrouter_client
from services import visibility_index_jobs
from services.visibility_index_jobs import (
    VisibilityIndexJobService,
    resolve_project_billing_context,
)

# The public, NEUTRAL visibility query templates (Brand/Category/Problem/
# Feature/Comparison). Only text built from these may leave the system.
NEUTRAL_PROMPT = "What are the leading CRM tools for small businesses?"

# Markers of private project context that must NEVER cross the firewall.
FORBIDDEN_CONTEXT_MARKERS = [
    "internal_project_id",
    "customer_email",
    "api_secret",
    "OPENROUTER_API_KEY",
    "sk-or-",
    "tenant_id",
]


@pytest.mark.asyncio
async def test_flag_on_routes_to_openrouter_with_mapped_model(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {"openai": "openai/gpt-5"},
    )

    calls = {}

    async def fake_query_model(model, prompt, **kwargs):
        calls["model"] = model
        calls["prompt"] = prompt
        return {"text": "Acme is great", "usage": {}, "cost": 0.001, "model": model}

    bedrock_called = {"value": False}

    async def fake_bedrock(self, model_id, prompt):  # pragma: no cover - must not run
        bedrock_called["value"] = True
        return {"answer": "bedrock"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    # Flag on AND the owning plan holds the live-engine add-on.
    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("openai", NEUTRAL_PROMPT)

    assert calls["model"] == "openai/gpt-5"  # mapped model id from settings
    assert bedrock_called["value"] is False  # Bedrock NOT called
    assert result["engine_source"] == "openrouter_live"
    assert result["answer"] == "Acme is great"


@pytest.mark.asyncio
async def test_flag_on_openrouter_failure_falls_back_to_bedrock(monkeypatch):
    """Flag on + entitled + the live OpenRouter call raises → fall back to the
    Bedrock measurement panel so the run still succeeds with proxy data."""
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {"openai": "openai/gpt-5"},
    )

    openrouter_calls = {"count": 0}

    async def fake_query_model(model, prompt, **kwargs):
        openrouter_calls["count"] += 1
        raise RuntimeError("HTTP 402: insufficient OpenRouter credit")

    bedrock_args = {}

    async def fake_bedrock(self, model_id, prompt):
        bedrock_args["model_id"] = model_id
        bedrock_args["prompt"] = prompt
        return {"answer": "from bedrock fallback"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("openai", NEUTRAL_PROMPT)

    # OpenRouter was attempted exactly once and raised.
    assert openrouter_calls["count"] == 1
    # Bedrock was used as the fallback, with the unchanged neutral prompt.
    assert bedrock_args["model_id"] == settings.BEDROCK_MEASUREMENT_MODEL_MAP["openai"]
    assert bedrock_args["prompt"] == NEUTRAL_PROMPT
    # The returned result is Bedrock's (proxy data), not an exception.
    assert result["answer"] == "from bedrock fallback"


@pytest.mark.asyncio
async def test_flag_on_but_plan_not_entitled_uses_bedrock(monkeypatch):
    """Flag on but the owning plan lacks `has_live_engine_tracking` → Bedrock.

    The paid add-on entitlement is a hard gate: without it, live measurement
    never happens even when the global flag is enabled.
    """
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {"openai": "openai/gpt-5"},
    )

    openrouter_called = {"value": False}

    async def fake_query_model(model, prompt, **kwargs):  # pragma: no cover
        openrouter_called["value"] = True
        return {"text": "x", "usage": {}, "cost": 0.0, "model": model}

    bedrock_args = {}

    async def fake_bedrock(self, model_id, prompt):
        bedrock_args["model_id"] = model_id
        return {"answer": "from bedrock"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    # Default entitlement is False (fail-safe LOCKED).
    service = VisibilityIndexJobService()
    result = await service._run_provider("openai", NEUTRAL_PROMPT)

    assert openrouter_called["value"] is False  # OpenRouter NOT called
    assert bedrock_args["model_id"] == settings.BEDROCK_MEASUREMENT_MODEL_MAP["openai"]
    assert result["answer"] == "from bedrock"


@pytest.mark.asyncio
async def test_flag_off_uses_bedrock_and_never_calls_openrouter(monkeypatch):
    # Default state: flag OFF.
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", False)

    openrouter_called = {"value": False}

    async def fake_query_model(model, prompt, **kwargs):  # pragma: no cover
        openrouter_called["value"] = True
        return {"text": "x", "usage": {}, "cost": 0.0, "model": model}

    bedrock_args = {}

    async def fake_bedrock(self, model_id, prompt):
        bedrock_args["model_id"] = model_id
        return {"answer": "from bedrock"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService()
    result = await service._run_provider("openai", NEUTRAL_PROMPT)

    assert openrouter_called["value"] is False  # OpenRouter NOT called
    # Existing Bedrock path used with the unchanged Bedrock model map.
    assert bedrock_args["model_id"] == settings.BEDROCK_MEASUREMENT_MODEL_MAP["openai"]
    assert result["answer"] == "from bedrock"


@pytest.mark.asyncio
async def test_firewall_only_neutral_prompt_leaves(monkeypatch):
    """Prove the only payload sent to OpenRouter is the neutral visibility query
    — no secrets, internal IDs, or customer data."""
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {"openai": "openai/gpt-5"},
    )

    sent = {}

    async def fake_query_model(model, prompt, **kwargs):
        sent["model"] = model
        sent["prompt"] = prompt
        sent["kwargs"] = kwargs
        return {"text": "ok", "usage": {}, "cost": 0.0, "model": model}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    await service._run_provider("openai", NEUTRAL_PROMPT)

    # Exactly the neutral prompt was sent — nothing more.
    assert sent["prompt"] == NEUTRAL_PROMPT
    for marker in FORBIDDEN_CONTEXT_MARKERS:
        assert marker not in sent["prompt"]
    # No extra positional/keyword context was smuggled alongside the prompt.
    assert sent["kwargs"] == {}


@pytest.mark.asyncio
async def test_unmapped_engine_falls_back_to_bedrock_even_when_flag_on(monkeypatch):
    # Bing has no OpenRouter entry — must stay on the controlled Bedrock panel.
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)

    openrouter_called = {"value": False}

    async def fake_query_model(model, prompt, **kwargs):  # pragma: no cover
        openrouter_called["value"] = True
        return {"text": "x", "usage": {}, "cost": 0.0, "model": model}

    async def fake_bedrock(self, model_id, prompt):
        return {"answer": "bedrock-bing"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)
    result = await service._run_provider("bing", NEUTRAL_PROMPT)

    assert openrouter_called["value"] is False
    assert result["answer"] == "bedrock-bing"


# --- Entitlement resolution + cost ledger (DB-backed) ----------------------


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


def _seed_project(session, *, plan_type: str):
    """Create user(+subscription)/workspace/project; return the project."""
    import models

    user = models.User(
        email=f"live-{plan_type}@example.com",
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
            stripe_customer_id=f"cus_{plan_type}",
            stripe_subscription_id=f"sub_{plan_type}",
            plan_type=plan_type,
            status="active",
        )
    )
    session.commit()

    workspace = models.Workspace(name=f"ws-{plan_type}", owner_id=user.id)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)

    project = models.Project(workspace_id=workspace.id, name="Live Project")
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def test_entitlement_resolves_from_workspace_owner_plan(sqlite_session):
    """SIGV2-1023: every plan holds has_live_engine_tracking → all entitled."""
    for plan_type in (
        "plan_starter",
        "plan_agency_trial",
        "plan_standard",
        "plan_specialist",
        "plan_executive",
    ):
        project = _seed_project(sqlite_session, plan_type=plan_type)
        ctx = resolve_project_billing_context(sqlite_session, project.id)
        assert ctx.live_engine_entitled is True, plan_type
        assert ctx.workspace_id == project.workspace_id
        assert ctx.user_id is not None

    # Fail-safe: unknown project → locked, no attribution.
    missing = resolve_project_billing_context(sqlite_session, 999999)
    assert missing.live_engine_entitled is False
    assert missing.workspace_id is None


@pytest.mark.asyncio
async def test_live_measurement_records_cost_into_ledger(sqlite_session, monkeypatch):
    """A live (entitled) OpenRouter run records its cost in the economics ledger."""
    import models

    project = _seed_project(sqlite_session, plan_type="plan_executive")

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_MEASUREMENT_MODEL_MAP", {"openai": "openai/gpt-5"})
    # Bypass the semantic cache so the live path actually executes.
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "get_json", lambda **_k: None)
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "set_json", lambda **_k: None)

    async def fake_query_model(model, prompt, **kwargs):
        return {
            "text": "Acme leads the category. https://acme.example.com",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            "cost": 0.0042,
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
        schedule_key="sched-live-cost",
        project_id=project.id,
    )

    assert batch.status == "succeeded"

    entries = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .all()
    )
    assert len(entries) == 1
    entry = entries[0]
    assert float(entry.token_cost_usd) == pytest.approx(0.0042)
    assert entry.input_tokens == 10
    assert entry.output_tokens == 20
    assert entry.project_id == project.id
    assert entry.workspace_id == project.workspace_id


@pytest.mark.asyncio
async def test_live_measurement_records_cost_when_cost_unknown(sqlite_session, monkeypatch):
    """Missing cost is recorded as explicit UNKNOWN, not a measured zero."""
    import models

    project = _seed_project(sqlite_session, plan_type="plan_executive")

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_MEASUREMENT_MODEL_MAP", {"openai": "openai/gpt-5"})
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "get_json", lambda **_k: None)
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "set_json", lambda **_k: None)

    async def fake_query_model(model, prompt, **kwargs):
        # No usage, no cost field — unknown, not free.
        return {"text": "Acme.", "usage": {}, "cost": None, "model": model}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)

    service = VisibilityIndexJobService()
    await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")
        ],
        schedule_key="sched-live-cost-unknown",
        project_id=project.id,
    )

    entries = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .all()
    )
    assert len(entries) == 1
    assert float(entries[0].token_cost_usd) == 0.0
    assert entries[0].payload_json["cost_known"] is False
    assert entries[0].payload_json["cost_state"] == "unknown"


@pytest.mark.asyncio
async def test_non_entitled_batch_uses_bedrock_and_records_no_live_cost(
    sqlite_session, monkeypatch
):
    """Fail-safe: a project whose workspace cannot be resolved stays on
    Bedrock and logs no live-cost entry (SIGV2-1023: all five plans are
    entitled, so the only unentitled case left is an unresolvable context)."""
    import models

    project = _seed_project(sqlite_session, plan_type="plan_standard")
    project.workspace_id = 999999  # workspace does not resolve → entitlement False
    sqlite_session.commit()

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_MEASUREMENT_MODEL_MAP", {"openai": "openai/gpt-5"})
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "get_json", lambda **_k: None)
    monkeypatch.setattr(visibility_index_jobs.semantic_cache_service, "set_json", lambda **_k: None)

    openrouter_called = {"value": False}

    async def fake_query_model(model, prompt, **kwargs):  # pragma: no cover
        openrouter_called["value"] = True
        return {"text": "x", "usage": {}, "cost": 0.0, "model": model}

    async def fake_bedrock(self, model_id, prompt):
        return {"answer": "Acme via bedrock. https://acme.example.com"}

    monkeypatch.setattr(openrouter_client, "query_model", fake_query_model)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService()
    await service.execute_batch(
        db=sqlite_session,
        topic="crm tools",
        provider="openai",
        prompt_templates=[
            visibility_index_jobs.PromptTemplate(name="default", template="Prompt {topic}")
        ],
        schedule_key="sched-bedrock",
        project_id=project.id,
    )

    assert openrouter_called["value"] is False
    entries = (
        sqlite_session.query(models.AIEconomicsLedgerEntry)
        .filter(models.AIEconomicsLedgerEntry.feature_key == "visibility.live_engine_measurement")
        .count()
    )
    assert entries == 0


# --- SIGV2-1183: structured citations survive the client and reach the worker ---


def _stub_http_client(body: dict):
    """An httpx.AsyncClient stand-in that answers every POST with ``body``."""
    import httpx

    class _StubClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, headers=None, json=None):
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    return _StubClient


async def _measure_with_body(monkeypatch, body: dict):
    """Run the REAL OpenRouter client against ``body`` and return the worker's
    response dict, so the test proves the citation fields survive the whole
    client -> worker boundary rather than a hand-built stub."""
    import httpx

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(settings, "OPENROUTER_MEASUREMENT_MODEL_MAP", {"openai": "openai/gpt-5"})
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "sk-or-test-not-a-real-key")
    monkeypatch.setattr(httpx, "AsyncClient", _stub_http_client(body))

    service = VisibilityIndexJobService(live_engine_entitled=True)
    return service, await service._run_provider("openai", NEUTRAL_PROMPT)


@pytest.mark.asyncio
async def test_perplexity_citations_reach_citation_candidates(monkeypatch):
    body = {
        "model": "perplexity/sonar",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads the CRM pack."}}],
        "citations": ["https://acme.example.com/crm", "https://news.example.com/crm"],
    }
    service, response = await _measure_with_body(monkeypatch, body)

    assert response["engine_source"] == "openrouter_live"
    # TOP level: that is where _extract_citation_candidates reads.
    assert response["citations"] == [
        "https://acme.example.com/crm",
        "https://news.example.com/crm",
    ]
    parsed, valid, text = service.parse_and_validate_citations(response)
    assert valid == [
        "https://acme.example.com/crm",
        "https://news.example.com/crm",
    ]
    assert text == "Acme leads the CRM pack."


@pytest.mark.asyncio
async def test_message_annotations_reach_citation_candidates(monkeypatch):
    body = {
        "model": "openai/gpt-5",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Acme leads the CRM pack.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url_citation": {
                                "url": "https://acme.example.com/crm",
                                "title": "Acme CRM",
                            },
                        }
                    ],
                }
            }
        ],
    }
    service, response = await _measure_with_body(monkeypatch, body)

    assert "annotations" in response
    parsed, valid, _text = service.parse_and_validate_citations(response)
    assert valid == ["https://acme.example.com/crm"]


@pytest.mark.asyncio
async def test_search_results_reach_citation_candidates(monkeypatch):
    body = {
        "model": "openai/gpt-5",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads."}}],
        "search_results": [
            {"url": "https://acme.example.com/one", "title": "One"},
            {"link": "https://acme.example.com/two", "title": "Two"},
        ],
    }
    service, response = await _measure_with_body(monkeypatch, body)

    _parsed, valid, _text = service.parse_and_validate_citations(response)
    assert valid == ["https://acme.example.com/one", "https://acme.example.com/two"]


@pytest.mark.asyncio
async def test_web_pages_reach_citation_candidates(monkeypatch):
    body = {
        "model": "openai/gpt-5",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads."}}],
        "webPages": {"value": [{"url": "https://acme.example.com/bing"}]},
    }
    service, response = await _measure_with_body(monkeypatch, body)

    _parsed, valid, _text = service.parse_and_validate_citations(response)
    assert valid == ["https://acme.example.com/bing"]


@pytest.mark.asyncio
async def test_grounding_metadata_reaches_citation_candidates(monkeypatch):
    body = {
        "model": "google/gemini-2.5-pro",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Acme leads.",
                    "groundingMetadata": {
                        "groundingChunks": [{"web": {"uri": "https://acme.example.com/grounded"}}]
                    },
                }
            }
        ],
    }
    service, response = await _measure_with_body(monkeypatch, body)

    _parsed, valid, _text = service.parse_and_validate_citations(response)
    assert valid == ["https://acme.example.com/grounded"]


@pytest.mark.asyncio
async def test_no_citation_fields_still_falls_back_to_prose_extraction(monkeypatch):
    """Unchanged behaviour for a provider that reports no structured sources:
    the URLs are scraped out of the model's prose exactly as before."""
    body = {
        "model": "deepseek/deepseek-chat",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Acme leads. See https://acme.example.com/blog for more.",
                }
            }
        ],
    }
    service, response = await _measure_with_body(monkeypatch, body)

    for field in openrouter_client.CITATION_FIELDS:
        assert field not in response
    _parsed, valid, _text = service.parse_and_validate_citations(response)
    assert valid == ["https://acme.example.com/blog"]
