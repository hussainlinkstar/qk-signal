import sys
from pathlib import Path
from unittest.mock import patch

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from services.ai_engine import AIFactory


# Reasoning is now Bedrock-only: provider "google" normalizes to "bedrock", the
# primary generation path runs through ``_generate_with_bedrock`` and resilience
# state is tracked on ``circuit_breakers["bedrock"]``.
@pytest.mark.asyncio
@patch("services.ai_engine.DEBATE_ENABLED", False)
async def test_generate_audit_auth_errors_do_not_retry_or_open_breaker():
    ai = AIFactory()
    ai.provider_retry_config["bedrock"] = {"retries": 4, "base_delay": 0.0, "max_delay": 0.0}

    attempts = {"count": 0}

    async def _raise_auth_error(*_args, **_kwargs):
        attempts["count"] += 1
        raise Exception("401 Unauthorized: invalid API key")

    ai._generate_with_bedrock = _raise_auth_error

    response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    assert response["error_code"] == "provider_auth_error"
    assert response["retryable"] is False
    assert response["http_status"] == 401
    assert attempts["count"] == 1
    assert ai.circuit_breakers["bedrock"].failure_count == 0
    assert ai.circuit_breakers["bedrock"].is_open() is False

    async def _success(*_args, **_kwargs):
        return {
            "summary": "ok",
            "recommendations": [],
            "seo_score": 70,
            "geo_score": 70,
            "aeo_score": 70,
        }

    ai._generate_with_bedrock = _success

    second_response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    assert second_response["analysis"]["summary"] == "ok"


@pytest.mark.asyncio
@patch("services.ai_engine.DEBATE_ENABLED", False)
async def test_generate_audit_transient_errors_retry_and_open_breaker():
    ai = AIFactory()
    ai.provider_retry_config["bedrock"] = {"retries": 6, "base_delay": 0.0, "max_delay": 0.0}

    attempts = {"count": 0}

    async def _raise_timeout(*_args, **_kwargs):
        attempts["count"] += 1
        raise TimeoutError("504 Gateway Timeout")

    ai._generate_with_bedrock = _raise_timeout

    response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    assert response["error_code"] == "provider_unavailable"
    assert response["retryable"] is True
    assert response["http_status"] == 503
    # Breaker threshold is 3 failures: retries stop and the breaker opens after
    # the third transient failure.
    assert attempts["count"] == 3
    assert ai.circuit_breakers["bedrock"].is_open() is True

    async def _success(*_args, **_kwargs):
        attempts["count"] += 1
        return {
            "summary": "ok",
            "recommendations": [],
            "seo_score": 70,
            "geo_score": 70,
            "aeo_score": 70,
        }

    ai._generate_with_bedrock = _success

    blocked_response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    # Breaker is open, so the second call is short-circuited without invoking
    # the operation again (attempts stays at 3).
    assert "error" in blocked_response
    assert attempts["count"] == 3


@pytest.mark.asyncio
@patch("services.ai_engine.DEBATE_ENABLED", False)
async def test_generate_audit_quota_429_does_not_retry():
    ai = AIFactory()
    ai.provider_retry_config["bedrock"] = {"retries": 5, "base_delay": 0.0, "max_delay": 0.0}

    attempts = {"count": 0}

    class _Quota429Error(Exception):
        status_code = 429

    async def _raise_quota_error(*_args, **_kwargs):
        attempts["count"] += 1
        raise _Quota429Error("429 insufficient_quota: You exceeded your current quota")

    ai._generate_with_bedrock = _raise_quota_error

    response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    assert attempts["count"] == 1
    assert response["error_code"] == "provider_quota_exhausted"
    assert response["retryable"] is False
    assert response["http_status"] == 429


# Primary reasoning runs on Bedrock and there is no cross-provider fallback
# (single-vendor cutover): a primary failure is the canonical error.
@pytest.mark.asyncio
@patch("services.ai_engine.DEBATE_ENABLED", False)
async def test_structured_error_keeps_non_retryable_primary_as_canonical() -> None:
    ai = AIFactory()

    class _PrimaryInvalidRequest(Exception):
        status_code = 400
        error_code = "INVALID_ARGUMENT"

    async def _generate(provider: str, *_args, **_kwargs):
        raise _PrimaryInvalidRequest("400 INVALID_ARGUMENT: malformed prompt")

    ai._generate_with_provider = _generate

    response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    assert response["error_code"] == "provider_request_error"
    assert response["retryable"] is False
    assert response["http_status"] == 400
    assert response["primary_error"]["http_status"] == 400
    # Bedrock-only: no cross-provider fallback — the only recorded error is the
    # bedrock primary (never an OpenAI/Google fallback).
    assert len(response["fallback_errors"]) == 1
    assert response["fallback_errors"][0]["error_code"] == "provider_request_error"


@pytest.mark.asyncio
@patch("services.ai_engine.DEBATE_ENABLED", False)
async def test_structured_error_has_no_cross_provider_fallback() -> None:
    ai = AIFactory()

    async def _generate(provider: str, *_args, **_kwargs):
        raise TimeoutError("504 Gateway Timeout")

    ai._generate_with_provider = _generate

    response = await ai.generate_audit(
        provider="bedrock",
        tier="fast",
        content="# Example",
        screenshot_data=None,
        network_data={},
    )

    # Retryable primary failure, exhausted with no other provider to fall back to.
    assert response["error_code"] == "provider_unavailable"
    assert len(response["fallback_errors"]) == 1
    assert response["fallback_errors"][0]["error_code"] == "provider_unavailable"
