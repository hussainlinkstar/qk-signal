import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import pytest

from services import ai_client as ai_client_module
from services.ai_client import AIClient


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, responses, calls):
        self._responses = responses
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, _url, json, timeout=None):
        self._calls.append(json)
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_ai_client_prefers_server_retryable_false(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            424,
            {
                "detail": {
                    "error": "timeout while validating key",
                    "retryable": False,
                }
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 3, "base_delay": 0, "max_delay": 0}

    result = await client.generate_audit(
        provider="google",
        tier="fast",
        content="x",
        screenshot_base64="",
        network_data={},
    )

    assert "error" in result
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ai_client_retries_when_server_marks_retryable(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            400,
            {
                "detail": {
                    "error": "upstream temporary outage",
                    "retryable": True,
                }
            },
        ),
        _FakeResponse(
            200,
            {
                "analysis": {
                    "summary": "ok",
                    "recommendations": [],
                    "seo_score": 70,
                    "geo_score": 70,
                    "aeo_score": 70,
                },
                "provider": "google",
                "model": "gemini-2.5-flash",
            },
        ),
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 2, "base_delay": 0, "max_delay": 0}

    result = await client.generate_audit(
        provider="google",
        tier="fast",
        content="x",
        screenshot_base64="",
        network_data={},
    )

    assert result["analysis"]["summary"] == "ok"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_ai_client_returns_structured_non_retryable_error_for_400(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            400,
            {
                "detail": {
                    "error": "invalid screenshot payload",
                    "error_code": "invalid_payload",
                    "retryable": False,
                    "type": "validation_error",
                }
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 2, "base_delay": 0, "max_delay": 0}

    result = await client.generate_audit(
        provider="google",
        tier="fast",
        content="x",
        screenshot_base64="",
        network_data={},
    )

    assert result["error"] == {
        "type": "validation_error",
        "error_code": "invalid_payload",
        "error_subtype": None,
        "http_status": 400,
        "retryable": False,
        "request_id": None,
        "payload_type": None,
        "source": None,
        "raw_type": None,
        "detail": "invalid screenshot payload",
    }
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_ai_client_normalizes_screenshot_payload_before_post(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            200,
            {
                "analysis": {
                    "summary": "ok",
                    "recommendations": [],
                    "seo_score": 70,
                    "geo_score": 70,
                    "aeo_score": 70,
                },
                "provider": "google",
                "model": "gemini-2.5-flash",
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 0, "base_delay": 0, "max_delay": 0}

    result = await client.generate_audit(
        provider="google",
        tier="fast",
        content="x",
        screenshot_base64="-_8",
        network_data={},
    )

    assert result["analysis"]["summary"] == "ok"
    assert calls[0]["screenshot_base64"] == "+/8="


@pytest.mark.asyncio
async def test_ai_client_allows_missing_screenshot_payload_for_brand_only_audits(
    monkeypatch,
) -> None:
    calls = []
    responses = [
        _FakeResponse(
            200,
            {
                "analysis": {
                    "summary": "ok",
                    "recommendations": [],
                    "seo_score": 70,
                    "geo_score": 70,
                    "aeo_score": 70,
                },
                "provider": "google",
                "model": "gemini-2.5-flash",
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 0, "base_delay": 0, "max_delay": 0}

    result = await client.generate_audit(
        provider="google",
        tier="fast",
        content="brand-only audit",
        screenshot_base64=None,
        network_data={},
    )

    assert result["analysis"]["summary"] == "ok"
    assert calls[0]["screenshot_base64"] is None


@pytest.mark.asyncio
async def test_ai_client_evaluate_track_b_claim_returns_judgment(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            200,
            {
                "judgment": {
                    "claim_id": "claim-1",
                    "track": "B",
                    "verdict": "supported",
                    "problem_anchor_score": 0.92,
                    "action_fit_score": 0.88,
                    "site_specificity_score": 0.81,
                    "novel_fact_risk_score": 0.1,
                    "reason_codes": ["supported_problem_anchor"],
                    "problem_refs": ["problem-1"],
                    "evidence_refs": ["chunk-1"],
                    "explanation": "Supported by the truth context.",
                    "suggested_rewrite": "Keep the recommendation focused on the supported issue.",
                },
                "provider": "google",
                "model": "gemini-2.5-pro",
                "usage": {"total_tokens": 123},
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 0, "base_delay": 0, "max_delay": 0}

    result = await client.evaluate_track_b_claim(
        provider="google",
        tier="deep_judgment",
        claim={"claim_id": "claim-1", "claim_text": "Add detailed service pages."},
        judge_context={"supported_problems": [{"problem_id": "problem-1"}]},
    )

    assert result["judgment"]["claim_id"] == "claim-1"
    assert result["model"] == "gemini-2.5-pro"
    assert calls[0]["tier"] == "deep_judgment"
    assert calls[0]["claim"]["claim_text"] == "Add detailed service pages."


@pytest.mark.asyncio
async def test_ai_client_evaluate_track_b_claim_raises_on_invalid_contract(monkeypatch):
    calls = []
    responses = [
        _FakeResponse(
            200,
            {
                "provider": "google",
                "model": "gemini-2.5-pro",
            },
        )
    ]

    monkeypatch.setattr(
        ai_client_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(responses, calls),
    )

    client = AIClient(base_url="http://test", timeout_seconds=0.01)
    client.retry_config = {"retries": 0, "base_delay": 0, "max_delay": 0}

    with pytest.raises(ai_client_module.AIServiceResponseError) as exc_info:
        await client.evaluate_track_b_claim(
            provider="google",
            tier="deep_judgment",
            claim={"claim_id": "claim-1", "claim_text": "Add detailed service pages."},
            judge_context={"supported_problems": [{"problem_id": "problem-1"}]},
        )

    assert "invalid Track B judge payload" in str(exc_info.value)
    assert len(calls) == 1
