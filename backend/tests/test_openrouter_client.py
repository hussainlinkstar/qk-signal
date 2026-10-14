import logging
import sys
from pathlib import Path

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services import openrouter_client
from services.openrouter_client import OpenRouterError, query_model

_SECRET_KEY = "sk-or-test-SUPERSECRET-do-not-log"

_OK_BODY = {
    "model": "openai/gpt-5",
    "choices": [{"message": {"role": "assistant", "content": "Acme is a leading CRM."}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "cost": 0.00042},
}


class _MockClient:
    """Stand-in for httpx.AsyncClient that records the outbound request."""

    captured: dict = {}

    def __init__(self, *args, **kwargs):
        type(self).captured["init_kwargs"] = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, headers=None, json=None):
        type(self).captured["url"] = url
        type(self).captured["headers"] = headers
        type(self).captured["json"] = json
        request = httpx.Request("POST", url)
        return httpx.Response(200, json=_OK_BODY, request=request)


def _client_returning(body: dict):
    """A _MockClient subclass that answers with ``body`` instead of _OK_BODY."""

    class _BodyClient(_MockClient):
        async def post(self, url, headers=None, json=None):
            type(self).captured["url"] = url
            type(self).captured["headers"] = headers
            type(self).captured["json"] = json
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    _BodyClient.captured = {}
    return _BodyClient


@pytest.fixture(autouse=True)
def _set_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", _SECRET_KEY)
    monkeypatch.setattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    # Pin the web-search flag OFF so these tests are immune to settings
    # mutated elsewhere in a full-suite run. The default is also OFF.
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", False)
    _MockClient.captured = {}


@pytest.mark.asyncio
async def test_query_model_posts_correct_url_header_body(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("openai/gpt-5", "How visible is Acme in CRM?")

    cap = _MockClient.captured
    assert cap["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert cap["headers"]["Authorization"] == f"Bearer {_SECRET_KEY}"
    assert cap["json"]["model"] == "openai/gpt-5"
    assert cap["json"]["messages"] == [{"role": "user", "content": "How visible is Acme in CRM?"}]
    # Deterministic measurement.
    assert cap["json"]["temperature"] == 0
    # Bounded timeout configured on the client.
    assert cap["init_kwargs"].get("timeout") == openrouter_client.DEFAULT_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_query_model_parses_text_usage_cost(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    result = await query_model("openai/gpt-5", "prompt")

    assert result["text"] == "Acme is a leading CRM."
    assert result["usage"]["prompt_tokens"] == 12
    assert result["cost"] == pytest.approx(0.00042)
    assert result["model"] == "openai/gpt-5"


@pytest.mark.asyncio
async def test_missing_key_raises_clean_error(monkeypatch):
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "")
    with pytest.raises(OpenRouterError):
        await query_model("openai/gpt-5", "prompt")


@pytest.mark.asyncio
async def test_timeout_raises_openrouter_error(monkeypatch):
    class _TimeoutClient(_MockClient):
        async def post(self, url, headers=None, json=None):
            raise httpx.TimeoutException("boom")

    monkeypatch.setattr(httpx, "AsyncClient", _TimeoutClient)
    with pytest.raises(OpenRouterError, match="timed out"):
        await query_model("openai/gpt-5", "prompt")


@pytest.mark.asyncio
async def test_http_status_error_raises_openrouter_error(monkeypatch):
    class _ErrClient(_MockClient):
        async def post(self, url, headers=None, json=None):
            request = httpx.Request("POST", url)
            return httpx.Response(503, json={"error": "down"}, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _ErrClient)
    with pytest.raises(OpenRouterError, match="503"):
        await query_model("openai/gpt-5", "prompt")


@pytest.mark.asyncio
async def test_api_key_never_logged(monkeypatch, caplog):
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    with caplog.at_level(logging.DEBUG, logger="services.openrouter_client"):
        await query_model("openai/gpt-5", "prompt")

    full_log = " ".join(record.getMessage() for record in caplog.records)
    full_log += " " + " ".join(str(record.__dict__) for record in caplog.records)
    assert _SECRET_KEY not in full_log


@pytest.mark.asyncio
async def test_api_key_never_in_raised_error(monkeypatch):
    class _ErrClient(_MockClient):
        async def post(self, url, headers=None, json=None):
            request = httpx.Request("POST", url)
            return httpx.Response(401, json={"error": "bad key"}, request=request)

    monkeypatch.setattr(httpx, "AsyncClient", _ErrClient)
    with pytest.raises(OpenRouterError) as exc_info:
        await query_model("openai/gpt-5", "prompt")
    assert _SECRET_KEY not in str(exc_info.value)


# --- SIGV2-1183: live web retrieval + structured citation passthrough ---


@pytest.mark.asyncio
async def test_web_search_tool_absent_when_flag_off(monkeypatch):
    """Default state: no `tools` key at all, so live spend is unchanged."""
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", False)
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("openai/gpt-5", "prompt")

    payload = _MockClient.captured["json"]
    assert "tools" not in payload
    # And no deprecated surface leaked in either.
    assert "plugins" not in payload
    assert not payload["model"].endswith(":online")


@pytest.mark.asyncio
async def test_web_search_tool_requested_when_flag_on(monkeypatch):
    """Flag on: request OpenRouter's web-search SERVER TOOL, not `:online`
    and not the deprecated `web` plugin."""
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("openai/gpt-5", "prompt")

    payload = _MockClient.captured["json"]
    assert payload["tools"][0]["type"] == "openrouter:web_search"
    assert "plugins" not in payload
    # SIGV2-1269: the retrieved context is bounded. Sent bare, one measured
    # call arrived with 17,405 input tokens against 27 without search.
    params = payload["tools"][0]["parameters"]
    assert params["search_context_size"] == "low"
    assert params["max_results"] == 5
    assert params["max_total_results"] == 5
    # The model slug is untouched: no `:online` suffix.
    assert payload["model"] == "openai/gpt-5"


@pytest.mark.asyncio
async def test_web_search_tool_never_attached_to_perplexity(monkeypatch):
    """SIGV2-1314: the server tool 404s on every Perplexity call.

    Verified live against OpenRouter: ``perplexity/sonar`` with
    ``tools: [{"type": "openrouter:web_search"}]`` returns HTTP 404,
    "No endpoints found that support tool use" — Perplexity's completions
    endpoint does not support generic tool/function calling at all, so
    OpenRouter's routing fails before the request reaches Perplexity. This is
    why 0 of 3,257+ Perplexity runs on preprod ever measured live (SIGV2-1300).

    Perplexity does not need the tool anyway: a raw call with neither `tools`
    nor `plugins` still returned `url_citation` annotations, because the
    `sonar` family always grounds natively.
    """
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("perplexity/sonar", "prompt")

    payload = _MockClient.captured["json"]
    assert "tools" not in payload
    assert "plugins" not in payload


@pytest.mark.asyncio
async def test_web_search_tool_still_attached_to_other_engines(monkeypatch):
    """The Perplexity carve-out must not quietly disable the tool everywhere.

    Confirmed live: Google, OpenAI, Anthropic, DeepSeek and xAI all accept the
    server tool. Only Perplexity's endpoint rejects it.
    """
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    for model in [
        "openai/gpt-5",
        "google/gemini-2.5-pro",
        "anthropic/claude-sonnet-4.5",
        "deepseek/deepseek-chat",
        "x-ai/grok-4.3",
    ]:
        _MockClient.captured = {}
        await query_model(model, "prompt")
        assert _MockClient.captured["json"].get("tools") == [
            openrouter_client.WEB_SEARCH_TOOL
        ], f"expected the web-search tool to still be attached for {model}"


@pytest.mark.asyncio
async def test_perplexity_sonar_pro_variant_also_skips_the_tool(monkeypatch):
    """Any perplexity/* model id is a sonar-family completions endpoint."""
    monkeypatch.setattr(settings, "OPENROUTER_WEB_SEARCH_ENABLED", True)
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("perplexity/sonar-pro-search", "prompt")

    assert "tools" not in _MockClient.captured["json"]


@pytest.mark.asyncio
async def test_top_level_citations_pass_through(monkeypatch):
    """Perplexity-style `citations` on the response object."""
    body = {
        "model": "perplexity/sonar",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads."}}],
        "citations": ["https://example.com/acme", "https://news.example.com/crm"],
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("perplexity/sonar", "prompt")

    assert result["citations"] == [
        "https://example.com/acme",
        "https://news.example.com/crm",
    ]


@pytest.mark.asyncio
async def test_message_annotations_pass_through(monkeypatch):
    """OpenAI-compatible `url_citation` annotations live on the MESSAGE."""
    annotations = [
        {
            "type": "url_citation",
            "url_citation": {
                "url": "https://example.com/acme",
                "title": "Acme CRM review",
                "start_index": 10,
                "end_index": 40,
            },
        }
    ]
    body = {
        "model": "openai/gpt-5",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Acme leads.",
                    "annotations": annotations,
                }
            }
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("openai/gpt-5", "prompt")

    # Verbatim, not reshaped.
    assert result["annotations"] == annotations


@pytest.mark.asyncio
async def test_search_results_sources_and_web_pages_pass_through(monkeypatch):
    body = {
        "model": "openai/gpt-5",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads."}}],
        "sources": ["https://example.com/one"],
        "search_results": [{"url": "https://example.com/two", "title": "Two"}],
        "webPages": {"value": [{"url": "https://example.com/three"}]},
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("openai/gpt-5", "prompt")

    assert result["sources"] == ["https://example.com/one"]
    assert result["search_results"] == [{"url": "https://example.com/two", "title": "Two"}]
    assert result["webPages"] == {"value": [{"url": "https://example.com/three"}]}


@pytest.mark.asyncio
async def test_grounding_metadata_on_message_passes_through(monkeypatch):
    grounding = {"groundingChunks": [{"web": {"uri": "https://example.com/acme", "title": "Acme"}}]}
    body = {
        "model": "google/gemini-2.5-pro",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Acme leads.",
                    "groundingMetadata": grounding,
                }
            }
        ],
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("google/gemini-2.5-pro", "prompt")

    assert result["groundingMetadata"] == grounding


@pytest.mark.asyncio
async def test_absent_citation_fields_are_absent_not_empty(monkeypatch):
    """A provider that reports nothing must leave the keys OUT entirely, so the
    caller's prose-extraction fallback still triggers. An empty list would be a
    placeholder claiming the provider answered 'no sources'."""
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    result = await query_model("openai/gpt-5", "prompt")

    for field in openrouter_client.CITATION_FIELDS:
        assert field not in result
    # The pre-existing contract is unchanged.
    assert set(result) == {"text", "usage", "cost", "model"}


@pytest.mark.asyncio
async def test_empty_citation_containers_are_dropped(monkeypatch):
    """An explicitly empty `citations: []` is not a citation: drop it rather
    than forwarding a misleading empty placeholder."""
    body = {
        "model": "openai/gpt-5",
        "choices": [
            {"message": {"role": "assistant", "content": "Acme leads.", "annotations": []}}
        ],
        "citations": [],
        "search_results": [{"url": "https://example.com/real"}],
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("openai/gpt-5", "prompt")

    assert "citations" not in result
    assert "annotations" not in result
    assert result["search_results"] == [{"url": "https://example.com/real"}]


@pytest.mark.asyncio
async def test_citation_passthrough_does_not_disturb_text_usage_cost(monkeypatch):
    body = {
        "model": "openai/gpt-5",
        "choices": [{"message": {"role": "assistant", "content": "Acme leads."}}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 7, "cost": 0.0021},
        "citations": ["https://example.com/acme"],
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("openai/gpt-5", "prompt")

    assert result["text"] == "Acme leads."
    assert result["usage"]["prompt_tokens"] == 5
    assert result["cost"] == pytest.approx(0.0021)
    assert result["model"] == "openai/gpt-5"


# ---------------------------------------------------------------------------
# SIGV2-1269: a reasoning model must not spend the whole budget thinking, and
# a billed response with no answer must not reach the score.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reasoning_effort_is_minimal_and_budget_leaves_room_for_an_answer(monkeypatch):
    """The measurement wants the answer, not the deliberation.

    On a reasoning model both share one `max_tokens` budget, and OpenRouter
    documents the failure: a small budget is consumed entirely by reasoning
    and the response comes back with empty content, billed in full. Ten such
    calls cost $0.52 on preprod and each was scored as an absence.

    "minimal" rather than "none" because gpt-5 rejects disabling reasoning
    outright with HTTP 400.
    """
    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)

    await query_model("openai/gpt-5", "prompt")

    payload = _MockClient.captured["json"]
    assert payload["reasoning"] == {"effort": "minimal"}
    assert payload["max_tokens"] >= 4096


@pytest.mark.asyncio
async def test_a_billed_response_with_no_answer_is_a_failure(monkeypatch):
    """Paying for silence is not a measurement.

    The provider charged for 1024 output tokens, spent all of them reasoning,
    and returned empty content with `finish_reason: "length"`. Scoring that
    records "the brand was not cited" for an answer the engine never gave.
    """
    body = {
        "model": "openai/gpt-5",
        "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "length"}],
        "usage": {
            "prompt_tokens": 27,
            "completion_tokens": 1024,
            "cost": 0.01027,
            "completion_tokens_details": {"reasoning_tokens": 1024},
        },
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    with pytest.raises(OpenRouterError) as exc:
        await query_model("openai/gpt-5", "prompt")

    message = str(exc.value)
    assert "no answer" in message
    assert "1024" in message
    assert _SECRET_KEY not in message


@pytest.mark.asyncio
async def test_a_provider_that_produced_no_tokens_at_all_is_left_alone(monkeypatch):
    """An empty answer with no output tokens is a different thing.

    Nothing was billed and nothing was thought, so there is no paid-for
    silence to reject. That case keeps its existing handling downstream,
    where an empty answer is already excluded from the score rather than
    counted as a citation miss (SIGV2-1263).
    """
    body = {
        "model": "perplexity/sonar",
        "choices": [{"message": {"role": "assistant", "content": ""}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 27, "completion_tokens": 0, "cost": 0.0},
    }
    monkeypatch.setattr(httpx, "AsyncClient", _client_returning(body))

    result = await query_model("perplexity/sonar", "prompt")

    assert result["text"] == ""
    assert result["cost"] == 0.0
