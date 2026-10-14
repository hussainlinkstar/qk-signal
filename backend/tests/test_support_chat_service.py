import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services import support_chat_service
from services.ai_routing_policy import (
    provider_runtime_state_service,
    resolve_support_chat_route,
)
from services.ai_provider_runtime_service import ProviderRuntimeStatus


class _FakeOpenAIResponse:
    def __init__(self, content: str):
        self.choices = [
            type("Choice", (), {"message": type("Message", (), {"content": content})()})()
        ]


class _FakeOpenAIClient:
    def __init__(self, *, content: str | None = None, error: Exception | None = None):
        self._content = content
        self._error = error
        self.chat = type("Chat", (), {"completions": self})()

    async def create(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return _FakeOpenAIResponse(self._content or "")


class _FakeGoogleModels:
    def __init__(self, content: str):
        self._content = content

    async def generate_content(self, **_kwargs):
        return type("GoogleResponse", (), {"text": self._content})()


class _FakeGoogleClient:
    def __init__(self, content: str):
        self.aio = type("Aio", (), {"models": _FakeGoogleModels(content)})()


class _FakeBedrockClient:
    def __init__(self, *, content: str | None = None, error: Exception | None = None):
        self._content = content
        self._error = error

    def converse(self, **_kwargs):
        if self._error is not None:
            raise self._error
        return {"output": {"message": {"content": [{"text": self._content or ""}]}}}


class _FakeAIFactory:
    def __init__(
        self, *, bedrock_content: str | None = None, bedrock_error: Exception | None = None
    ):
        # Support chat is Bedrock-only now (single-vendor cutover).
        self.bedrock_client = _FakeBedrockClient(content=bedrock_content, error=bedrock_error)

    def get_model_instance(self, provider: str, tier: str):
        if provider == "bedrock":
            return ("bedrock", "eu.amazon.nova-micro-v1:0")
        return None


@pytest.fixture(autouse=True)
def _stub_knowledge_context(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        support_chat_service.knowledge_service, "get_domain_context", lambda *args, **kwargs: ""
    )
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda provider: ProviderRuntimeStatus(
            provider=provider,
            configured=True,
            available=True,
            state="healthy",
        ),
    )


def test_generate_support_chat_reply_uses_bedrock() -> None:
    result = asyncio.run(
        support_chat_service.generate_support_chat_reply(
            messages=[{"role": "user", "content": "Where can I see my invoices?"}],
            locale="en",
            ai_factory=_FakeAIFactory(
                bedrock_content="Open Dashboard > Billing to review invoices."
            ),
        )
    )

    assert result is not None
    assert result.source == "bedrock"
    assert result.model == "eu.amazon.nova-micro-v1:0"
    assert result.routing_feature_key == "support.thoth_chat"
    assert "Billing" in result.reply


def test_generate_support_chat_reply_returns_none_when_bedrock_fails() -> None:
    # Bedrock-only: no cross-provider fallback, so a failing engine yields no reply.
    result = asyncio.run(
        support_chat_service.generate_support_chat_reply(
            messages=[{"role": "user", "content": "How do I cancel my plan?"}],
            locale="en",
            ai_factory=_FakeAIFactory(bedrock_error=RuntimeError("bedrock unavailable")),
        )
    )

    assert result is None


def test_support_chat_response_source_accepts_the_routable_provider() -> None:
    """The route schema's ``source`` Literal must cover whatever provider the
    routing policy selects; a mismatch fails response validation and silently
    demotes every generated reply to the fallback."""
    from typing import get_args

    from routers.api_router import SupportChatResponse

    annotation = SupportChatResponse.model_fields["source"].annotation
    allowed = set(get_args(annotation))
    route = resolve_support_chat_route()
    assert route.provider in allowed
    assert "fallback" in allowed


def _support_chat_route():
    from routers.api_router import router

    return next(r for r in router.routes if getattr(r, "path", "") == "/api/v1/ai/support-chat")


def test_support_chat_route_carries_the_rate_limit_dependency() -> None:
    """The endpoint is LLM-backed and spend-bearing, so the limiter stays wired."""
    route = _support_chat_route()
    dependencies = [dep.call for dep in route.dependant.dependencies]
    assert any(
        getattr(dep, "__name__", "") == "enforce_support_chat_rate_limit" for dep in dependencies
    )


def test_support_chat_route_carries_the_authentication_dependency() -> None:
    """SIGV2-1148: the route is authenticated, and deleting the dependency must
    fail here rather than silently reopening an anonymous LLM endpoint."""
    from auth.security import get_current_user

    route = _support_chat_route()
    assert any(dep.call is get_current_user for dep in route.dependant.dependencies)


def test_support_chat_rate_limiter_takes_no_caller_supplied_identifier() -> None:
    """The per-identity key must come from the session, never from a header.

    Keying on the client IP meant a caller who could set `x-forwarded-for`
    rotated their own counter away; the limiter no longer accepts a Request at
    all, so there is nothing caller-controlled left to key on."""
    import inspect

    from auth.security import get_current_user
    from fastapi import Request
    from routers.api_router import enforce_support_chat_rate_limit

    signature = inspect.signature(enforce_support_chat_rate_limit)
    assert [parameter.name for parameter in signature.parameters.values()] == ["user"]
    assert Request not in [
        parameter.annotation for parameter in signature.parameters.values()
    ], "the limiter must not read anything the caller can forge"

    dependency = signature.parameters["user"].annotation.__metadata__[0]
    assert dependency.dependency is get_current_user


class _CountingRedis:
    """Async Redis stand-in for the support-chat limiter's incr/expire calls."""

    def __init__(self, *, fail: bool = False):
        self.counts: dict[str, int] = {}
        self.fail = fail

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis unavailable")
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    async def expire(self, key, ttl):
        return None


def _patch_support_chat_redis(monkeypatch: pytest.MonkeyPatch, redis: _CountingRedis):
    import contextlib

    import routers.api_router as api_router_module

    @contextlib.asynccontextmanager
    async def _fake_get_async_redis(**_kwargs):
        yield redis

    monkeypatch.setattr(api_router_module, "get_async_redis", _fake_get_async_redis)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("RATE_LIMIT_SUPPORT_CHAT", raising=False)
    monkeypatch.delenv("RATE_LIMIT_SUPPORT_CHAT_GLOBAL", raising=False)
    return api_router_module


def _user(user_id: int = 7) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def test_support_chat_rate_limit_counts_under_its_own_key_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis = _CountingRedis()
    api_router_module = _patch_support_chat_redis(monkeypatch, redis)

    asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user()))

    assert redis.counts["ratelimit:support_chat:user:7"] == 1
    assert redis.counts["ratelimit:support_chat:global"] == 1


def test_support_chat_rate_limit_refuses_a_single_identity_over_its_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-identity cap binds, and the identity is the session's user id,
    so no caller-supplied header resets it."""
    from fastapi import HTTPException

    redis = _CountingRedis()
    api_router_module = _patch_support_chat_redis(monkeypatch, redis)
    monkeypatch.setenv("RATE_LIMIT_SUPPORT_CHAT", "1/min")

    asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user()))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user()))

    assert exc_info.value.status_code == 429


def test_support_chat_rate_limit_refuses_when_the_limiter_cannot_be_evaluated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spend-bearing: fails closed with 503 on a Redis outage."""
    from fastapi import HTTPException

    api_router_module = _patch_support_chat_redis(monkeypatch, _CountingRedis(fail=True))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user()))
    assert exc_info.value.status_code == 503


def test_support_chat_global_ceiling_holds_across_distinct_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each account gets its own per-identity counter, so spend is only bounded
    by the global ceiling, which is keyed on a constant and still refuses."""
    from fastapi import HTTPException

    redis = _CountingRedis()
    api_router_module = _patch_support_chat_redis(monkeypatch, redis)
    monkeypatch.setenv("RATE_LIMIT_SUPPORT_CHAT", "100/min")
    monkeypatch.setenv("RATE_LIMIT_SUPPORT_CHAT_GLOBAL", "3/min")

    for user_id in range(3):
        asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user(user_id)))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(api_router_module.enforce_support_chat_rate_limit(_user(99)))

    assert exc_info.value.status_code == 429
    assert redis.counts["ratelimit:support_chat:global"] == 4
    assert redis.counts["ratelimit:support_chat:user:0"] == 1


def test_support_chat_refuses_an_unauthenticated_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGV2-1148: no session, no LLM call. The generator must never be reached."""
    from fastapi.testclient import TestClient

    import routers.api_router as api_router_module
    from main import app

    monkeypatch.setenv("ENVIRONMENT", "local")
    calls: list[dict] = []

    async def _never(**kwargs):
        calls.append(kwargs)
        return None

    monkeypatch.setattr(api_router_module, "generate_support_chat_reply", _never)

    response = TestClient(app).post(
        "/api/v1/ai/support-chat",
        json={
            "locale": "en",
            "messages": [{"role": "user", "content": "Where are my invoices?"}],
        },
    )

    assert response.status_code == 401, response.text
    assert calls == []


def test_support_chat_answers_an_authenticated_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authenticated path still reaches the handler and returns a reply."""
    from fastapi.testclient import TestClient

    import routers.api_router as api_router_module
    from main import app, get_current_user

    monkeypatch.setenv("ENVIRONMENT", "local")

    async def _reply(**_kwargs):
        return SimpleNamespace(
            reply="Open Dashboard > Billing to review invoices.",
            source="bedrock",
            model="eu.amazon.nova-micro-v1:0",
        )

    monkeypatch.setattr(api_router_module, "generate_support_chat_reply", _reply)
    app.dependency_overrides[get_current_user] = lambda: _user()
    try:
        response = TestClient(app).post(
            "/api/v1/ai/support-chat",
            json={
                "locale": "en",
                "messages": [{"role": "user", "content": "Where are my invoices?"}],
            },
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_name"] == "Qiko"
    assert body["reply"]


# ── SIGV2-1177: no hardcoded scan duration reaches the assistant ────────────


def _prompt(**kwargs) -> str:
    return support_chat_service.build_support_chat_prompt(
        [SimpleNamespace(role="user", content="How long does a Smart scan take?")],
        "en",
        **kwargs,
    )


def test_support_chat_prompt_states_no_duration_of_its_own() -> None:
    """The product reference carries no figure the model can repeat.

    SIGV2-1161 removed one set of invented durations and SIGV2-1177 removed the
    approved-design ones from here too. A number written back into these lines
    is a constant again, so this asserts the absence directly rather than
    trusting a comment.
    """
    prompt = _prompt()

    for forbidden in ("~5 min", "~15 min", "~45 min", "~2 min", "~8 min", "~10 min"):
        assert forbidden not in prompt
    assert "Typically" not in prompt
    # The rule naming the section still stands; the section itself is absent,
    # because there is nothing measured to put in it.
    assert "SCAN DURATIONS (measured" not in prompt


def test_support_chat_prompt_forbids_inventing_a_duration() -> None:
    prompt = _prompt()

    assert "Never estimate" in prompt
    assert "do not publish a figure for it yet" in prompt


def test_support_chat_prompt_carries_the_measured_durations_when_they_exist() -> None:
    measured = "- Smart: half of the last 37 scans finished in 7 to 15 minutes."

    prompt = _prompt(measured_durations=measured)

    assert measured in prompt
    assert "SCAN DURATIONS (measured, not estimated" in prompt
    # The copy must carry the statistic's own caveats, not just the numbers.
    assert "middle half of recent runs" in prompt
    assert "never restate a range as a single figure" in prompt


def test_support_chat_fallback_states_no_duration_without_a_measurement() -> None:
    import routers.api_router as api_router_module

    reply = api_router_module._build_support_chat_fallback_reply("how long is an audit?", "en")

    assert "Fast" in reply
    assert "minute" not in reply
    assert "min)" not in reply
    assert "recorded durations" not in reply


def test_support_chat_fallback_states_the_measured_duration_when_it_exists() -> None:
    import routers.api_router as api_router_module

    reply = api_router_module._build_support_chat_fallback_reply(
        "how long is an audit?",
        "en",
        measured_durations="Fast: half of the last 90 scans finished in 2 to 5 minutes.",
    )

    assert "On recorded durations, Fast: half of the last 90 scans finished in 2 to 5 minutes." in (
        reply
    )
    assert "A large site takes longer." in reply
