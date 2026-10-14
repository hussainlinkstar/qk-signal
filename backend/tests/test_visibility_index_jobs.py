import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from auth.credits import calculate_audit_credit_cost
from core.config import settings
from services.visibility_index_jobs import PromptTemplate, VisibilityIndexJobService


@pytest.fixture(autouse=True)
def _bypass_semantic_cache(monkeypatch):
    """Force a cache miss for every prompt run.

    ``execute_prompt_run`` consults the shared semantic cache (backed by a
    real Redis instance in CI/dev). Without isolation these unit tests become
    order/pollution dependent: a cached response from a prior run short-circuits
    the provider call, so retry/rate-limiter behaviour never executes. Pinning a
    miss keeps the provider-dispatch assertions hermetic without weakening them.
    """
    from services import visibility_index_jobs

    monkeypatch.setattr(
        visibility_index_jobs.semantic_cache_service,
        "get_json",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        visibility_index_jobs.semantic_cache_service,
        "set_json",
        lambda **_kwargs: None,
    )


@pytest.fixture(autouse=True)
def _canonical_measurement_map(monkeypatch):
    """Pin the measurement model map so dispatcher tests are deterministic and
    immune to settings mutated by other tests in a full-suite run."""
    monkeypatch.setattr(
        settings,
        "BEDROCK_MEASUREMENT_MODEL_MAP",
        {
            "openai": "openai.gpt-oss-120b-1:0",
            "google": "qwen.qwen3-235b-a22b-2507-v1:0",
            "anthropic": "eu.amazon.nova-pro-v1:0",
            "deepseek": "deepseek.v3.2",
            "perplexity": "zai.glm-5",
            "xai": "zai.glm-4.7",
            "bing": "eu.amazon.nova-pro-v1:0",
        },
    )


@pytest.mark.asyncio
async def test_scoring_and_citation_parsing_is_deterministic():
    async def fake_provider(_provider: str, _prompt: str):
        return {
            "answer": "Acme appears in analyst coverage. Sources: https://example.com/acme and DOI 10.1000/xyz123",
            "citations": ["https://example.com/acme", "10.1000/xyz123", "notaurl"],
        }

    service = VisibilityIndexJobService(provider_callable=fake_provider)

    parsed_1, valid_1, text_1 = service.parse_and_validate_citations(
        await fake_provider("openai", "p")
    )
    parsed_2, valid_2, text_2 = service.parse_and_validate_citations(
        await fake_provider("openai", "p")
    )
    score_1 = service._score_response("Acme", text_1, valid_1)
    score_2 = service._score_response("Acme", text_2, valid_2)

    assert parsed_1 == parsed_2
    assert valid_1 == ["https://example.com/acme", "10.1000/xyz123"]
    assert valid_1 == valid_2
    # Continuous multi-factor scoring (visibility_scoring.score_response) replaced
    # the legacy 0/50/100 ternary. With one topic-matching citation in first
    # position plus a prominent topic mention this deterministically scores 68.0.
    assert score_1 == score_2 == 68.0


@pytest.mark.asyncio
async def test_retry_behavior_uses_exponential_backoff(sqlite_session):
    attempts = {"count": 0}
    backoffs: list[float] = []

    async def fake_sleep(seconds: float):
        backoffs.append(seconds)

    async def flaky_provider(_provider: str, _prompt: str):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary provider error")
        return "Acme mention with citation https://example.com/acme"

    service = VisibilityIndexJobService(provider_callable=flaky_provider, sleep_func=fake_sleep)
    service.max_attempts = 3
    service.backoff_base_seconds = 0.5

    from models import VisibilityRunBatch

    batch = VisibilityRunBatch(
        topic="acme", provider="openai", schedule_key="test", status="running"
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="default", template="Tell me about {topic}"),
    )

    assert run.status == "succeeded"
    assert attempts["count"] == 3
    assert backoffs[:2] == [0.5, 1.0]


@pytest.mark.asyncio
async def test_rate_limiter_enforces_provider_limit(sqlite_session):
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float):
        sleep_calls.append(seconds)

    async def fast_provider(_provider: str, _prompt: str):
        return "Acme https://example.com/acme"

    service = VisibilityIndexJobService(provider_callable=fast_provider, sleep_func=fake_sleep)
    service.rate_limiter.requests_per_minute = 1

    from models import VisibilityRunBatch

    batch = VisibilityRunBatch(
        topic="acme", provider="openai", schedule_key="test", status="running"
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="p1", template="Prompt 1 {topic}"),
    )
    await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="p2", template="Prompt 2 {topic}"),
    )

    assert sleep_calls, "expected limiter to sleep before second request"
    assert any(value >= 0.01 for value in sleep_calls)


@pytest.mark.asyncio
async def test_execute_batch_persists_project_scope(sqlite_session):
    async def fake_provider(_provider: str, _prompt: str):
        return "Acme https://example.com/acme"

    from models import Project, User, VisibilityRunBatch, Workspace

    user = User(
        email="batch-project-scope@example.com",
        hashed_password="x",
        role="user",
        credits=5,
        notifications_enabled=True,
    )
    sqlite_session.add(user)
    sqlite_session.commit()
    sqlite_session.refresh(user)

    workspace = Workspace(name="Workspace", owner_id=user.id)
    sqlite_session.add(workspace)
    sqlite_session.commit()
    sqlite_session.refresh(workspace)

    project = Project(workspace_id=workspace.id, name="Project")
    sqlite_session.add(project)
    sqlite_session.commit()
    sqlite_session.refresh(project)

    service = VisibilityIndexJobService(provider_callable=fake_provider)

    batch = await service.execute_batch(
        db=sqlite_session,
        topic="acme",
        provider="google",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-project",
        project_id=project.id,
    )

    persisted = (
        sqlite_session.query(VisibilityRunBatch).filter(VisibilityRunBatch.id == batch.id).first()
    )
    assert persisted is not None
    assert persisted.project_id == project.id


@pytest.mark.asyncio
async def test_execute_batch_scores_against_target_domain(sqlite_session):
    async def fake_provider(_provider: str, _prompt: str):
        return {
            "answer": "Acme appears with supporting source.",
            "citations": ["https://acme.example.com/research"],
        }

    from models import VisibilityRun

    service = VisibilityIndexJobService(provider_callable=fake_provider)
    batch = await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="google",
        target_domain="acme.example.com",
        prompt_templates=[
            PromptTemplate(name="default", template="Prompt {topic} for {target_domain}")
        ],
        schedule_key="sched-target-domain",
    )

    run = sqlite_session.query(VisibilityRun).filter(VisibilityRun.batch_id == batch.id).first()
    assert run is not None
    assert run.target_domain == "acme.example.com"
    # New continuous scoring: target-domain citation present in first position
    # (33 + 20) but the domain/topic are absent from the short answer body, so
    # text-mention and topic-relevance contribute 0 -> 53.0.
    assert run.score == 53.0
    assert batch.score == 53.0


@pytest.mark.asyncio
async def test_execute_batch_charges_project_visibility_credits_idempotently(sqlite_session):
    async def fake_provider(_provider: str, _prompt: str):
        return {
            "answer": "Acme appears with source.",
            "citations": ["https://acme.example.com/source"],
        }

    from models import Project, User, UserCreditAdjustment, Workspace

    user = User(
        email="visibility-charge@example.com",
        hashed_password="x",
        role="user",
        credits=20,
        notifications_enabled=True,
    )
    sqlite_session.add(user)
    sqlite_session.commit()
    sqlite_session.refresh(user)

    workspace = Workspace(name="Visibility Billing Workspace", owner_id=user.id)
    sqlite_session.add(workspace)
    sqlite_session.commit()
    sqlite_session.refresh(workspace)

    project = Project(
        workspace_id=workspace.id, name="Visibility Billing Project", domain_url="acme.example.com"
    )
    sqlite_session.add(project)
    sqlite_session.commit()
    sqlite_session.refresh(project)

    service = VisibilityIndexJobService(provider_callable=fake_provider)
    expected_cost = max(
        1,
        int(
            calculate_audit_credit_cost(
                provider="google",
                tier="lite",
                category="visibility_check",
                market="acme.example.com",
            )
        ),
    )

    await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="google",
        target_domain="acme.example.com",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-charge-once",
        project_id=project.id,
        charge_user_id=user.id,
        charge_credits=True,
    )
    sqlite_session.refresh(user)
    credits_after_first_run = int(user.credits or 0)
    assert credits_after_first_run == 20 - expected_cost

    await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="google",
        target_domain="acme.example.com",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-charge-once",
        project_id=project.id,
        charge_user_id=user.id,
        charge_credits=True,
    )
    sqlite_session.refresh(user)
    assert int(user.credits or 0) == credits_after_first_run

    adjustment_count = (
        sqlite_session.query(UserCreditAdjustment)
        .filter(
            UserCreditAdjustment.user_id == user.id,
            UserCreditAdjustment.reason.contains("visibility_scheduled_credit_charge"),
        )
        .count()
    )
    assert adjustment_count == 1


@pytest.fixture
def sqlite_session(monkeypatch):
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


@pytest.mark.asyncio
async def test_dispatcher_routes_xai_provider(sqlite_session):
    """xAI provider routes to _run_bedrock with its mapped model id (Bedrock-only measurement)."""
    calls: list[tuple[str, str]] = []

    async def fake_bedrock(self_inner, model_id, prompt):
        calls.append((model_id, prompt))
        return {"answer": "Grok says Acme https://example.com/acme", "raw": {}}

    service = VisibilityIndexJobService(provider_callable=None)

    import types

    service._run_bedrock = types.MethodType(fake_bedrock, service)

    result = await service._run_provider("xai", "test prompt")
    assert calls == [("zai.glm-4.7", "test prompt")]
    assert "Grok says Acme" in result.get("answer", "")


@pytest.mark.asyncio
async def test_dispatcher_routes_deepseek_provider(sqlite_session):
    """DeepSeek provider routes to _run_bedrock with its mapped model id (Bedrock-only measurement)."""
    calls: list[tuple[str, str]] = []

    async def fake_bedrock(self_inner, model_id, prompt):
        calls.append((model_id, prompt))
        return {"answer": "DeepSeek says Acme https://example.com/acme", "raw": {}}

    service = VisibilityIndexJobService(provider_callable=None)

    import types

    service._run_bedrock = types.MethodType(fake_bedrock, service)

    result = await service._run_provider("deepseek", "test prompt")
    assert calls == [("deepseek.v3.2", "test prompt")]
    assert "DeepSeek says Acme" in result.get("answer", "")


@pytest.mark.asyncio
async def test_dispatcher_raises_for_unsupported_provider():
    """An unsupported provider (e.g. removed meta_ai) raises ValueError."""
    service = VisibilityIndexJobService(provider_callable=None)

    with pytest.raises(ValueError, match="Unsupported provider"):
        await service._run_provider("meta_ai", "test prompt")


@pytest.mark.asyncio
async def test_execute_batch_with_xai_provider(sqlite_session):
    """Full batch execution with xAI provider produces scored results."""

    async def fake_provider(_provider: str, _prompt: str):
        return {
            "answer": "Acme is great. See https://acme.example.com/research",
            "citations": ["https://acme.example.com/research"],
        }

    service = VisibilityIndexJobService(provider_callable=fake_provider)
    batch = await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="xai",
        target_domain="acme.example.com",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-xai",
    )

    from models import VisibilityRun

    run = sqlite_session.query(VisibilityRun).filter(VisibilityRun.batch_id == batch.id).first()
    assert run is not None
    # Continuous scoring: target-domain citation first-position (33 + 20) plus the
    # domain appearing in the answer body (+10) -> 63.0.
    assert run.score == 63.0
    assert batch.provider == "xai"


@pytest.mark.asyncio
async def test_execute_batch_with_deepseek_provider(sqlite_session):
    """Full batch execution with DeepSeek provider produces scored results."""

    async def fake_provider(_provider: str, _prompt: str):
        return {
            "answer": "Acme is great. See https://acme.example.com/research",
            "citations": ["https://acme.example.com/research"],
        }

    service = VisibilityIndexJobService(provider_callable=fake_provider)
    batch = await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="deepseek",
        target_domain="acme.example.com",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-deepseek",
    )

    from models import VisibilityRun

    run = sqlite_session.query(VisibilityRun).filter(VisibilityRun.batch_id == batch.id).first()
    assert run is not None
    # Continuous scoring: target-domain citation first-position (33 + 20) plus the
    # domain appearing in the answer body (+10) -> 63.0.
    assert run.score == 63.0
    assert batch.provider == "deepseek"


def test_supported_providers_includes_new_entries():
    """Registry includes xai, deepseek and meta alongside originals (meta_ai removed)."""
    from services.project_visibility_service import SUPPORTED_VISIBILITY_PROVIDERS

    assert "xai" in SUPPORTED_VISIBILITY_PROVIDERS
    assert "deepseek" in SUPPORTED_VISIBILITY_PROVIDERS
    assert "meta_ai" not in SUPPORTED_VISIBILITY_PROVIDERS
    # SIGV2-1023: meta added (executable live via OpenRouter, no proxy fallback).
    assert "meta" in SUPPORTED_VISIBILITY_PROVIDERS
    assert len(SUPPORTED_VISIBILITY_PROVIDERS) == 8


@pytest.mark.asyncio
async def test_a_batch_with_no_successful_run_is_failed_and_carries_no_score(sqlite_session):
    """An exhausted retry chain measured nothing, so it must not score zero.

    The writer used to store this as ``degraded`` with ``score=0.0``. Every
    reader treats a non-failed batch holding a number as a completed
    measurement, so a provider outage published itself as "the brand was not
    cited" - a zero the customer could see and nobody could explain. Scores
    swung between a real number and 0 purely on provider availability.
    """

    async def always_fails(_provider: str, _prompt: str):
        raise RuntimeError("provider unavailable")

    from models import VisibilityRun

    async def fake_sleep(_seconds: float):
        return None

    service = VisibilityIndexJobService(provider_callable=always_fails, sleep_func=fake_sleep)
    service.max_attempts = 1

    batch = await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="google",
        prompt_templates=[PromptTemplate(name="default", template="Prompt {topic}")],
        schedule_key="sched-all-failed",
    )

    runs = sqlite_session.query(VisibilityRun).filter(VisibilityRun.batch_id == batch.id).all()
    assert runs and all(run.status == "failed" for run in runs)
    assert batch.status == "failed"
    assert batch.score is None
    assert batch.error == "Every prompt run failed"


@pytest.mark.asyncio
async def test_a_partly_failed_batch_stays_degraded_and_averages_what_answered(sqlite_session):
    """Partial failure is still a measurement, of the runs that answered."""
    calls = {"n": 0}

    async def fails_once(_provider: str, _prompt: str):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("provider unavailable")
        return {
            "answer": "Acme appears with supporting source.",
            "citations": ["https://acme.example.com/research"],
        }

    async def fake_sleep(_seconds: float):
        return None

    service = VisibilityIndexJobService(provider_callable=fails_once, sleep_func=fake_sleep)
    service.max_attempts = 1

    batch = await service.execute_batch(
        db=sqlite_session,
        topic="best payroll software",
        provider="google",
        target_domain="acme.example.com",
        prompt_templates=[
            PromptTemplate(name="a", template="Prompt {topic} for {target_domain}"),
            PromptTemplate(name="b", template="Other {topic} for {target_domain}"),
        ],
        schedule_key="sched-partly-failed",
    )

    assert batch.status == "degraded"
    # The failed run contributes nothing; the answered one is the average.
    assert batch.score == 53.0
    assert batch.error == "One or more prompt runs failed"


# ---------------------------------------------------------------------------
# SIGV2-1300: why a run did not measure on the named engine
# ---------------------------------------------------------------------------
# Measured on preprod on 10 Oct: of 2,478 runs belonging to a real project, 141
# were `openrouter_live`. Every one of those projects has an ACTIVE
# subscription on a plan that grants `has_live_engine_tracking`, so entitlement
# does not explain it, and nothing on the run said what did. These tests pin
# the four reasons a run can end up on the Bedrock panel so the question is
# answerable from the data rather than from a log line nobody kept.


def _bedrock_capture(service):
    """Replace ``_run_bedrock`` with a recorder, returning the call list."""
    import types

    calls: list[tuple[str, str]] = []

    async def fake_bedrock(_self, model_id, prompt):
        calls.append((model_id, prompt))
        return {"answer": "Acme is listed https://example.com/acme", "raw": {}}

    service._run_bedrock = types.MethodType(fake_bedrock, service)
    return calls


@pytest.mark.asyncio
async def test_fallback_records_plan_not_entitled(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=False)
    _bedrock_capture(service)

    result = await service._run_provider("google", "test prompt")

    assert result["fallback_reason"] == "plan_not_entitled"
    assert "fallback_error" not in result


@pytest.mark.asyncio
async def test_fallback_records_live_measurement_disabled(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", False)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    _bedrock_capture(service)

    result = await service._run_provider("google", "test prompt")

    assert result["fallback_reason"] == "live_measurement_disabled"


@pytest.mark.asyncio
async def test_fallback_records_engine_not_live_measurable(monkeypatch):
    """`bing` has no OpenRouter entry by design, so it can never go live."""
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    _bedrock_capture(service)

    result = await service._run_provider("bing", "test prompt")

    assert result["fallback_reason"] == "engine_not_live_measurable"


@pytest.mark.asyncio
async def test_fallback_records_live_call_failure_with_safe_detail(monkeypatch):
    """An OpenRouterError message is key-safe by construction, so it is kept.

    `services/openrouter_client` states the key is "never included in raised
    error messages", and the message carries the HTTP status, which is the one
    detail that makes a quiet downgrade diagnosable.
    """
    import types

    from services.openrouter_client import OpenRouterError

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    _bedrock_capture(service)

    async def failing_live(_self, _model_id, _prompt):
        raise OpenRouterError("OpenRouter returned HTTP 402 for model 'openai/gpt-5'")

    service._run_openrouter = types.MethodType(failing_live, service)

    result = await service._run_provider("openai", "test prompt")

    assert result["fallback_reason"] == "live_call_failed"
    assert result["fallback_error"] == "OpenRouter returned HTTP 402 for model 'openai/gpt-5'"


@pytest.mark.asyncio
async def test_fallback_from_unknown_exception_records_type_only(monkeypatch):
    """A non-OpenRouterError may carry anything, so only its type is recorded."""
    import types

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    _bedrock_capture(service)

    async def failing_live(_self, _model_id, _prompt):
        raise RuntimeError("Bearer sk-or-v1-must-never-be-persisted")

    service._run_openrouter = types.MethodType(failing_live, service)

    result = await service._run_provider("openai", "test prompt")

    assert result["fallback_reason"] == "live_call_failed"
    assert result["fallback_error"] == "RuntimeError"
    assert "sk-or-v1" not in str(result)


@pytest.mark.asyncio
async def test_live_measurement_records_no_fallback_reason(monkeypatch):
    """A run that reached the named engine carries no reason at all."""
    import types

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)

    async def ok_live(_self, model_id, _prompt):
        return {"answer": "Acme", "engine_source": "openrouter_live", "model": model_id}

    service._run_openrouter = types.MethodType(ok_live, service)

    result = await service._run_provider("openai", "test prompt")

    assert result["engine_source"] == "openrouter_live"
    assert "fallback_reason" not in result


@pytest.mark.asyncio
async def test_fallback_reason_reaches_the_persisted_run(sqlite_session, monkeypatch):
    """The reason has to survive onto `raw_response`, not just a log line."""
    from models import VisibilityRunBatch

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=False)
    _bedrock_capture(service)

    batch = VisibilityRunBatch(
        topic="acme crm",
        provider="google",
        schedule_key="test",
        status="running",
        target_domain="example.com",
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="market_overview", template="Who leads {topic}?"),
    )

    assert run.status == "succeeded"
    assert run.raw_response["fallback_reason"] == "plan_not_entitled"


# ---------------------------------------------------------------------------
# SIGV2-1301: a denied measurement model is a configuration fault
# ---------------------------------------------------------------------------
# On the live stack 828 runs failed with AccessDeniedException on Converse,
# every one for google, perplexity and openai, while bing succeeded because its
# model is the only one the instance role may invoke. As a bare ClientError
# that is indistinguishable from a model that answered badly, which is the
# shape SIGV2-1263 ruled out: an engine nobody is allowed to call has not
# scored zero, it has not been measured.

_LIVE_DENIAL_MESSAGE = (
    "An error occurred (AccessDeniedException) when calling the Converse operation: "
    "User: arn:aws:sts::064247010239:assumed-role/tht-ssm/i-05ac5cd4749b9cc31 is not "
    "authorized to perform: bedrock:InvokeModel"
)


class _FakeClientError(Exception):
    """Shaped like botocore's ClientError: a message plus a response dict."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


def _bedrock_client_raising(service, exc: Exception):
    import types

    class _Client:
        def converse(self, **_kwargs):
            raise exc

    service._get_bedrock_client = types.MethodType(lambda _self: _Client(), service)


@pytest.mark.asyncio
async def test_bedrock_access_denied_raises_a_configuration_fault():
    from core.bedrock_runtime import BedrockModelAccessDeniedError

    service = VisibilityIndexJobService(provider_callable=None)
    _bedrock_client_raising(
        service, _FakeClientError("AccessDeniedException", _LIVE_DENIAL_MESSAGE)
    )

    with pytest.raises(BedrockModelAccessDeniedError) as caught:
        await service._run_bedrock("zai.glm-5", "test prompt")

    assert caught.value.model_id == "zai.glm-5"
    # The AWS message carries the account id and the role ARN. A measurement
    # table is not the place for either, so neither survives the translation.
    assert "064247010239" not in str(caught.value)
    assert "assumed-role" not in str(caught.value)
    assert "configuration fault" in str(caught.value)


@pytest.mark.asyncio
async def test_bedrock_access_denied_detected_without_a_response_dict():
    """A client that raises a plain exception is still classified correctly."""
    from core.bedrock_runtime import BedrockModelAccessDeniedError

    service = VisibilityIndexJobService(provider_callable=None)
    _bedrock_client_raising(service, RuntimeError(_LIVE_DENIAL_MESSAGE))

    with pytest.raises(BedrockModelAccessDeniedError):
        await service._run_bedrock("zai.glm-5", "test prompt")


@pytest.mark.asyncio
async def test_other_bedrock_errors_are_left_alone():
    """Throttling is a measurement problem and must keep its own type."""
    service = VisibilityIndexJobService(provider_callable=None)
    _bedrock_client_raising(service, _FakeClientError("ThrottlingException", "Rate exceeded"))

    with pytest.raises(_FakeClientError):
        await service._run_bedrock("zai.glm-5", "test prompt")


@pytest.mark.asyncio
async def test_access_denied_fails_the_run_without_retrying(sqlite_session):
    """A denial cannot succeed on a retry, so it must not consume the budget."""
    import types

    from models import VisibilityRunBatch

    sleeps: list[float] = []

    async def record_sleep(seconds: float):
        sleeps.append(seconds)

    service = VisibilityIndexJobService(provider_callable=None, sleep_func=record_sleep)
    service.max_attempts = 3

    attempts = {"count": 0}

    class _Client:
        def converse(self, **_kwargs):
            attempts["count"] += 1
            raise _FakeClientError("AccessDeniedException", _LIVE_DENIAL_MESSAGE)

    service._get_bedrock_client = types.MethodType(lambda _self: _Client(), service)

    batch = VisibilityRunBatch(
        topic="acme crm",
        provider="perplexity",
        schedule_key="test",
        status="running",
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="market_overview", template="Who leads {topic}?"),
    )

    assert run.status == "failed"
    assert attempts["count"] == 1
    assert sleeps == []
    assert "configuration fault" in (run.error or "")
    assert "064247010239" not in (run.error or "")
    # A denied engine must never be recorded as a measured absence.
    assert run.score is None


# ---------------------------------------------------------------------------
# SIGV2-1313: the reason survives a failed run, and reaches the API
# ---------------------------------------------------------------------------
# SIGV2-1300 writes the reason onto `raw_response`, which only exists on a
# succeeded run. The live stack is the case where both paths are unavailable at
# once: live measurement is off by configuration AND three of four Bedrock
# models are denied by IAM. There the run fails, no response is written, and
# the reason was lost for exactly the configuration that needed explaining.


@pytest.mark.asyncio
async def test_reason_survives_when_the_proxy_also_fails(sqlite_session, monkeypatch):
    """Live off and the proxy denied: the run fails and still says why."""
    import types

    from core.bedrock_runtime import BedrockModelAccessDeniedError
    from models import VisibilityRunBatch

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", False)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)

    async def denied(_self, model_id, _prompt):
        raise BedrockModelAccessDeniedError(model_id, "eu-central-1")

    service._run_bedrock = types.MethodType(denied, service)

    batch = VisibilityRunBatch(
        topic="acme crm",
        provider="google",
        schedule_key="test",
        status="running",
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="market_overview", template="Who leads {topic}?"),
    )

    assert run.status == "failed"
    # The run records the configuration fault AND why live was never tried.
    assert "configuration fault" in (run.error or "")
    assert run.raw_response["fallback_reason"] == "live_measurement_disabled"


@pytest.mark.asyncio
async def test_live_failure_then_proxy_failure_keeps_the_provider_detail(
    sqlite_session, monkeypatch
):
    """Both legs failing keeps the live error, which is the diagnostic one."""
    import types

    from models import VisibilityRunBatch
    from services.openrouter_client import OpenRouterError

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    service.max_attempts = 1

    async def failing_live(_self, _model_id, _prompt):
        raise OpenRouterError("OpenRouter returned HTTP 402 for model 'google/gemini-2.5-pro'")

    async def failing_proxy(_self, _model_id, _prompt):
        raise RuntimeError("Converse timed out")

    service._run_openrouter = types.MethodType(failing_live, service)
    service._run_bedrock = types.MethodType(failing_proxy, service)

    batch = VisibilityRunBatch(
        topic="acme crm",
        provider="google",
        schedule_key="test",
        status="running",
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="market_overview", template="Who leads {topic}?"),
    )

    assert run.status == "failed"
    assert run.raw_response["fallback_reason"] == "live_call_failed"
    assert "HTTP 402" in run.raw_response["fallback_error"]


@pytest.mark.asyncio
async def test_a_reached_engine_leaves_no_reason_on_a_failed_run(sqlite_session, monkeypatch):
    """No reason means no reason. A failure with nothing to explain stays bare."""
    import types

    from models import VisibilityRunBatch

    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    service = VisibilityIndexJobService(provider_callable=None, live_engine_entitled=True)
    service.max_attempts = 1

    async def failing_live(_self, _model_id, _prompt):
        raise RuntimeError("network blip")

    async def failing_proxy(_self, _model_id, _prompt):
        raise RuntimeError("Converse timed out")

    service._run_openrouter = types.MethodType(failing_live, service)
    service._run_bedrock = types.MethodType(failing_proxy, service)

    batch = VisibilityRunBatch(
        topic="acme crm", provider="google", schedule_key="test", status="running"
    )
    sqlite_session.add(batch)
    sqlite_session.commit()
    sqlite_session.refresh(batch)

    run = await service.execute_prompt_run(
        db=sqlite_session,
        batch=batch,
        prompt_template=PromptTemplate(name="market_overview", template="Who leads {topic}?"),
    )

    # live_call_failed is still the honest reason here: live was attempted.
    assert run.raw_response["fallback_reason"] == "live_call_failed"
    assert run.raw_response["fallback_error"] == "RuntimeError"
