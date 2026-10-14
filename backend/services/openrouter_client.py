"""OpenRouter live-engine measurement client (Phase 11 / R10).

Measurement-only: this client sends *neutral visibility prompts* to the real
consumer models (GPT/Gemini/Claude/Grok/Perplexity/DeepSeek/Llama) via the
OpenRouter chat-completions API. Reasoning/debate/Advisor never use this path —
they stay on Bedrock.

Firewall + key-safety invariants enforced here:
  * Only the caller-supplied prompt text is sent (no project context is added).
  * The API key is read from settings and sent as a Bearer header; it is NEVER
    logged, never returned, and never included in raised error messages.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger(__name__)

# Bounded latency budget for an outbound measurement call. Per AGENTS §4.4 LLM
# calls must not block; this client is async and time-bounded so a slow/hung
# engine can never stall a worker indefinitely.
DEFAULT_TIMEOUT_SECONDS = 30.0
# OpenRouter recommends these attribution headers; they carry no secrets.
_REFERER = "https://qiko.ai/signal"
_TITLE = "Qiko Signal"

# OpenRouter's server-side web-search tool (SIGV2-1183). Requested as a `tools`
# entry, NOT via the deprecated `:online` model suffix or `plugins: [{"id":
# "web"}]`: the server tool is the supported surface and it lets the model
# decide whether (and how often) to search instead of always searching once.
#
# SIGV2-1269: the parameters are explicit. Sent bare, the retrieved context was
# unbounded and a measured call arrived with 17,405 input tokens against 27
# without search, a 644x increase that cost 5.3x and returned no citations at
# all. `search_context_size: "low"` pins a 5K character cap per result rather
# than letting the engine pick adaptively, and `max_total_results` bounds the
# whole request so an agentic loop cannot keep buying context.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "openrouter:web_search",
    "parameters": {
        "max_results": 5,
        "max_total_results": 5,
        "search_context_size": "low",
    },
}

# SIGV2-1269: reasoning models spend `max_tokens` on thinking before they emit
# anything, and OpenRouter documents the consequence: "a small max_tokens can
# be consumed entirely by reasoning, returning finish_reason: 'length' with
# empty content" - and the reasoning tokens are billed regardless. Every live
# `openai/gpt-5` measurement was doing exactly that: 1024 output tokens billed,
# zero characters of answer, $0.0103 to $0.0548 a call, and the empty answer
# then scored as an absence.
#
# "minimal" rather than "none" because gpt-5 rejects disabling outright
# ("Reasoning is mandatory for this endpoint and cannot be disabled", HTTP
# 400). Measured on the real prompt, "minimal" brings reasoning tokens to 0 and
# returns a 4,000+ character answer for the same price.
REASONING_EFFORT: dict[str, Any] = {"effort": "minimal"}

# Enough headroom for the answer to finish. At 1024 the same call came back
# `finish_reason: "length"` mid-sentence, which truncates the citation list the
# score is built from; at 4096 it finishes with `stop` for $0.003 more.
DEFAULT_MAX_TOKENS = 4096

# Structured citation/grounding fields a provider may attach to a measurement
# response. They are passed through verbatim so the visibility worker can read
# real, provider-reported sources instead of regex-scraping the model's prose.
# Both naming variants are listed where providers disagree; the key is never
# renamed and the value is never reshaped.
CITATION_FIELDS: tuple[str, ...] = (
    "citations",
    "sources",
    "search_results",
    "searchResults",
    "webPages",
    "groundingMetadata",
    "grounding_metadata",
    "annotations",
)


class OpenRouterError(RuntimeError):
    """Raised on any OpenRouter failure. The message never contains the API key."""


async def query_model(
    model: str,
    prompt: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Send a single neutral visibility prompt to ``model`` via OpenRouter.

    Args:
        model: OpenRouter model id (e.g. ``openai/gpt-5``). Resolved by the
            caller from ``settings.OPENROUTER_MEASUREMENT_MODEL_MAP`` — never
            hard-coded here.
        prompt: The neutral visibility query text. This is the ONLY content that
            leaves the system; callers must not embed private project context.

    Returns:
        ``{"text": str, "usage": dict, "cost": float | None, "model": str}``
        where ``cost`` is ``None`` when OpenRouter reports no usable cost
        (unknown, not free). Any structured citation field the provider
        reported (see ``CITATION_FIELDS``) is added verbatim; a field the
        provider did not report is absent, never an empty placeholder.

    Raises:
        OpenRouterError: on missing key, HTTP error, timeout, or unpar. The
            error message never includes the API key.
    """
    api_key = settings.OPENROUTER_API_KEY
    if not api_key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not configured; live-engine measurement is unavailable"
        )

    url = f"{settings.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": _REFERER,
        "X-Title": _TITLE,
    }
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        # A measurement wants the answer a user would see, not the model's
        # private deliberation, and on a reasoning model the two share one
        # token budget. See REASONING_EFFORT.
        "reasoning": dict(REASONING_EFFORT),
    }
    # SIGV2-1314: Perplexity's `sonar` family has no generic tool/function
    # calling at all, so OpenRouter's router rejects the web-search SERVER
    # TOOL for it with "No endpoints found that support tool use" before the
    # request ever reaches Perplexity - a 404 on every single call, which is
    # why not one Perplexity measurement had gone live before this. The tool
    # is also unnecessary there: `sonar` grounds natively on every call with
    # no opt-in, confirmed live with citations returned carrying neither
    # `tools` nor `plugins`. Every other engine accepts the tool unchanged.
    web_search = bool(settings.OPENROUTER_WEB_SEARCH_ENABLED) and not model.startswith(
        "perplexity/"
    )
    if web_search:
        # Live web grounding, off by default: see OPENROUTER_WEB_SEARCH_ENABLED
        # in core.config for the cost gate (SIGV2-1188).
        payload["tools"] = [dict(WEB_SEARCH_TOOL)]

    # Structured logging — model only, NEVER the key, headers, or prompt body.
    logger.info(
        "openrouter_measurement_request",
        extra={"model": model, "web_search": web_search},
    )

    try:
        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException as exc:
        logger.warning("openrouter_measurement_timeout", extra={"model": model})
        raise OpenRouterError(f"OpenRouter request timed out for model '{model}'") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning(
            "openrouter_measurement_http_error",
            extra={"model": model, "status_code": status},
        )
        raise OpenRouterError(f"OpenRouter returned HTTP {status} for model '{model}'") from exc
    except httpx.HTTPError as exc:
        logger.warning("openrouter_measurement_request_error", extra={"model": model})
        raise OpenRouterError(f"OpenRouter request failed for model '{model}'") from exc

    return _parse_response(model, data)


def _parse_response(model: str, data: dict[str, Any]) -> dict[str, Any]:
    """Parse an OpenRouter chat-completions response into a normalized dict."""
    try:
        choices = data["choices"]
        text = choices[0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("openrouter_measurement_parse_error", extra={"model": model})
        raise OpenRouterError(
            f"OpenRouter response could not be parsed for model '{model}'"
        ) from exc

    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    message = message if isinstance(message, dict) else {}

    usage = data.get("usage") or {}
    _reject_answerless_response(model, text, choices[0], usage)
    # A missing or unparseable usage cost is UNKNOWN, not free: keep it as None
    # so the economics ledger can record an explicit unknown state. Zero means
    # the provider genuinely reported a zero cost.
    cost: float | None = None
    if isinstance(usage, dict):
        # `or` here would drop a genuinely reported 0.0 — check None explicitly.
        raw_cost = usage.get("cost")
        if raw_cost is None:
            raw_cost = usage.get("total_cost")
        try:
            cost = float(raw_cost) if raw_cost is not None else None
        except (TypeError, ValueError):
            cost = None

    parsed: dict[str, Any] = {
        "text": text or "",
        "usage": usage,
        "cost": cost,
        "model": data.get("model", model),
    }
    parsed.update(_extract_citation_fields(data, message))
    return parsed


def _reject_answerless_response(
    model: str,
    text: Any,
    choice: Any,
    usage: Any,
) -> None:
    """Fail a billed response that contains no answer (SIGV2-1269).

    A response can be charged in full and still carry nothing: on a reasoning
    model the output budget goes to thinking first, and when it runs out the
    provider returns ``finish_reason: "length"`` with empty content. Ten such
    calls cost $0.52 on preprod and every one of them was then scored as "the
    brand was not cited", which is a measurement the engine never made.

    Reasoning effort and the token budget are set so this should not happen,
    but a model we cannot tune, or a future one, must not be able to put a
    paid-for silence back into the score. Failing here routes it through the
    worker's existing provider-failure path, where it is excluded from the
    score instead of counted as an absence.

    The emptiness has to be distinguished from a provider that legitimately
    answered nothing at all: the test is that tokens were produced and none of
    them reached the answer.
    """
    if isinstance(text, str) and text.strip():
        return

    usage = usage if isinstance(usage, dict) else {}
    details = usage.get("completion_tokens_details")
    details = details if isinstance(details, dict) else {}

    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    completion_tokens = _as_int(usage.get("completion_tokens"))
    reasoning_tokens = _as_int(details.get("reasoning_tokens"))
    visible_tokens = completion_tokens - reasoning_tokens
    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None

    if completion_tokens <= 0:
        return

    logger.warning(
        "openrouter_measurement_answerless",
        extra={
            "model": model,
            "finish_reason": finish_reason,
            "completion_tokens": completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "visible_tokens": visible_tokens,
        },
    )
    raise OpenRouterError(
        f"OpenRouter billed {completion_tokens} output tokens for model '{model}' "
        f"but returned no answer ({reasoning_tokens} spent on reasoning, "
        f"finish_reason={finish_reason!r}); not scoring a paid-for silence"
    )


def _extract_citation_fields(data: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    """Collect the provider-reported citation fields, verbatim.

    Providers disagree about where they attach sources: Perplexity puts
    ``citations`` on the response object, OpenAI-compatible responses put
    ``annotations`` on the message, Google puts ``groundingMetadata`` on the
    message. So both locations are read, with the chosen message winning for a
    key present in both (it is the more specific source for that choice).

    A field the provider did not report is omitted entirely rather than set to
    an empty list/dict, so the caller's fallback to prose extraction keeps
    working byte-for-byte for a provider that reports nothing.
    """
    collected: dict[str, Any] = {}
    for source in (data, message):
        if not isinstance(source, dict):
            continue
        for field in CITATION_FIELDS:
            value = source.get(field)
            # Skip missing AND empty values: an empty list is not a citation,
            # and writing it would look like a provider-reported absence.
            if value is None:
                continue
            if isinstance(value, (list, dict, str)) and not value:
                continue
            collected[field] = value
    return collected
