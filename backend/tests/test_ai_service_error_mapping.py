import sys
from pathlib import Path
import json

sys.path.append(str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

import ai_service
from report_schema import AI_AUDIT_SCHEMA_VERSION


client = TestClient(ai_service.app)


class _FakeRedisClient:
    def __init__(self) -> None:
        self.events: dict[str, list[str]] = {}
        self.closed = False

    async def rpush(self, key: str, value: str) -> None:
        self.events.setdefault(key, []).append(value)

    async def aclose(self) -> None:
        self.closed = True


def _request_body() -> dict:
    return {
        "provider": "google",
        "tier": "fast",
        "content": "# Example",
        "screenshot_base64": "c2NyZWVuc2hvdA==",
        "network_data": {},
    }


def _analysis_payload() -> dict:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": "ok",
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.82,
            "brand_trust_score": 0.77,
            "knowledge_graph_presence": True,
            "dominant_entities": [],
        },
        "aeo_signals": {
            "answerability_score": 71.0,
            "voice_readiness_score": 68.0,
            "key_recommendations": [],
        },
        "geo_signals": {
            "citation_consistency_score": 69.0,
            "local_authority_score": 73.0,
        },
        "technical_signals": {
            "mobile_friendliness": 75.0,
            "security_score": 81.0,
        },
    }


def _track_b_judgment_payload() -> dict:
    return {
        "claim_id": "claim-1",
        "track": "B",
        "verdict": "supported",
        "confidence_band": "high",
        "problem_anchor_score": 0.92,
        "action_fit_score": 0.88,
        "site_specificity_score": 0.81,
        "novel_fact_risk_score": 0.1,
        "reason_codes": ["supported_problem_anchor"],
        "problem_refs": ["problem-1"],
        "evidence_refs": ["chunk-1"],
        "explanation": "Supported by the truth context.",
        "judge_resolution": "Recommendation is sufficiently grounded for automated acceptance.",
        "suggested_rewrite": "Keep the recommendation focused on the supported issue.",
    }


def _assert_valid_success_response(response_json: dict) -> None:
    assert response_json["provider"] == "google"
    assert response_json["model"] == "test-model"
    assert response_json["debate"] is None
    assert response_json["analysis"]["schema_version"] == AI_AUDIT_SCHEMA_VERSION
    assert response_json["analysis"]["summary"] == "ok"
    assert response_json["analysis"]["recommendations"] == []
    assert response_json["analysis"]["entity_analysis"]["entity_clarity_score"] == 0.82


def test_ai_service_accepts_valid_base64_payload(monkeypatch):
    async def _fake_generate_audit(**kwargs):
        assert kwargs["screenshot_data"] == b"screenshot"
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    response = client.post("/ai/audit", json=_request_body())

    assert response.status_code == 200
    _assert_valid_success_response(response.json())


def test_ai_service_wires_job_progress_callback_when_job_id_is_present(monkeypatch):
    fake_redis = _FakeRedisClient()

    async def _fake_generate_audit(**kwargs):
        assert callable(kwargs["on_event"])
        await kwargs["on_event"](
            {
                "event": "debate_step_started",
                "role": "proposer",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-test",
            }
        )
        await kwargs["on_event"](
            {
                "event": "debate_step_completed",
                "role": "proposer",
                "semantic_role": "generator",
                "provider": "google",
                "model": "gemini-test",
                "latency_ms": 512,
                "summary": "A" * 240,
            }
        )
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)
    monkeypatch.setattr(ai_service, "get_async_redis_client", lambda: fake_redis)

    payload = _request_body()
    payload["job_id"] = "job-live-1"
    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 200
    assert fake_redis.closed is True
    stored_events = [json.loads(item) for item in fake_redis.events["audit:job:job-live-1:events"]]
    assert stored_events[0]["type"] == "step_started"
    assert stored_events[0]["model"] == "gemini-test"
    assert stored_events[1]["type"] == "step_completed"
    assert stored_events[1]["status"] == "completed"
    assert len(stored_events[1]["summary"]) == 200


def test_ai_service_accepts_data_url_base64_payload(monkeypatch):
    async def _fake_generate_audit(**kwargs):
        assert kwargs["screenshot_data"] == b"screenshot"
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    payload = _request_body()
    payload["screenshot_base64"] = "data:image/png;base64,c2NyZWVuc2hvdA=="

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 200
    _assert_valid_success_response(response.json())


def test_ai_service_accepts_base64_payload_with_whitespace(monkeypatch):
    async def _fake_generate_audit(**kwargs):
        assert kwargs["screenshot_data"] == b"screenshot"
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    payload = _request_body()
    payload["screenshot_base64"] = " \n c2NyZWVuc2hvdA==\n\t"

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 200
    _assert_valid_success_response(response.json())


def test_ai_service_accepts_urlsafe_base64_payload_without_padding(monkeypatch):
    async def _fake_generate_audit(**kwargs):
        assert kwargs["screenshot_data"] == b"\xfb\xff"
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    payload = _request_body()
    payload["screenshot_base64"] = "-_8"

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 200
    _assert_valid_success_response(response.json())


def test_ai_service_accepts_standard_base64_payload_without_padding(monkeypatch):
    async def _fake_generate_audit(**kwargs):
        assert kwargs["screenshot_data"] == b"screenshot"
        return {
            "analysis": _analysis_payload(),
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    payload = _request_body()
    payload["screenshot_base64"] = "c2NyZWVuc2hvdA"

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 200
    _assert_valid_success_response(response.json())


def test_ai_service_rejects_malformed_base64_payload():
    payload = _request_body()
    payload["screenshot_base64"] = "not-base64!!"

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid screenshot payload"


def test_ai_service_rejects_empty_decoded_screenshot_payload():
    payload = _request_body()
    payload["screenshot_base64"] = ""

    response = client.post("/ai/audit", json=payload)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid screenshot payload"


def test_ai_service_maps_non_retryable_auth_error(monkeypatch):
    async def _fake_generate_audit(**_kwargs):
        return {
            "error": "invalid api key",
            "error_code": "provider_auth_error",
            "retryable": False,
            "http_status": 401,
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    response = client.post("/ai/audit", json=_request_body())

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "error": "invalid api key",
        "error_code": "provider_auth_error",
        "retryable": False,
    }


def test_ai_service_maps_retryable_provider_outage(monkeypatch):
    async def _fake_generate_audit(**_kwargs):
        return {
            "error": "provider unavailable",
            "error_code": "provider_unavailable",
            "retryable": True,
            "http_status": 503,
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    response = client.post("/ai/audit", json=_request_body())

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "error": "provider unavailable",
        "error_code": "provider_unavailable",
        "retryable": True,
    }


def test_ai_service_coerces_non_versioned_audit_analysis(monkeypatch):
    """Missing schema_version is now backfilled by coerce_payload_for_contract,
    so the AI service returns 200 with the default version injected."""

    async def _fake_generate_audit(**_kwargs):
        invalid = _analysis_payload()
        invalid.pop("schema_version")
        return {
            "analysis": invalid,
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(ai_service.ai_factory, "generate_audit", _fake_generate_audit)

    response = client.post("/ai/audit", json=_request_body())

    assert response.status_code == 200
    body = response.json()
    assert "analysis" in body
    assert body["analysis"]["schema_version"] is not None


def test_ai_service_track_b_claim_returns_valid_payload(monkeypatch):
    async def _fake_evaluate_track_b_claim(**kwargs):
        assert kwargs["provider"] == "google"
        assert kwargs["tier"] == "deep_judgment"
        assert kwargs["claim"]["claim_id"] == "claim-1"
        assert kwargs["judge_context"]["supported_problems"][0]["problem_id"] == "problem-1"
        return {
            "judgment": _track_b_judgment_payload(),
            "provider": "google",
            "model": "test-model",
            "usage": {"total_tokens": 123},
        }

    monkeypatch.setattr(
        ai_service.ai_factory, "evaluate_track_b_claim", _fake_evaluate_track_b_claim
    )

    response = client.post(
        "/ai/track-b-claim",
        json={
            "provider": "google",
            "tier": "deep_judgment",
            "claim": {
                "claim_id": "claim-1",
                "claim_text": "Add detailed service pages.",
            },
            "judge_context": {
                "supported_problems": [{"problem_id": "problem-1"}],
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "google"
    assert payload["model"] == "test-model"
    assert payload["judgment"]["claim_id"] == "claim-1"
    assert payload["judgment"]["track"] == "B"


def test_ai_service_suggestion_detail_accepts_null_category(monkeypatch):
    """SIGV2-1232: the model legitimately returns category: null when the
    suggestion does not fit Technical/Content/Backlinks. That must render as
    a 200 with category omitted/null, not a 500 ResponseValidationError."""

    async def _fake_generate_suggestion_detail(**kwargs):
        assert kwargs["suggestion"] == "Improve internal linking structure."
        return {
            "short_title": "Improve internal linking",
            "comprehensive_action": "Add contextual links between related pages.",
            "category": None,
            "provider": "google",
            "model": "test-model",
            "usage": {"total_tokens": 42},
            "latency_ms": 123.0,
        }

    monkeypatch.setattr(
        ai_service.ai_factory, "generate_suggestion_detail", _fake_generate_suggestion_detail
    )

    response = client.post(
        "/ai/suggestion-detail",
        json={
            "provider": "google",
            "tier": "fast",
            "suggestion": "Improve internal linking structure.",
            "market": "global",
            "language": "en",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["category"] is None
    assert body["short_title"] == "Improve internal linking"


def test_ai_service_track_b_claim_rejects_invalid_contract(monkeypatch):
    async def _fake_evaluate_track_b_claim(**_kwargs):
        invalid = _track_b_judgment_payload()
        invalid.pop("verdict")
        return {
            "judgment": invalid,
            "provider": "google",
            "model": "test-model",
        }

    monkeypatch.setattr(
        ai_service.ai_factory, "evaluate_track_b_claim", _fake_evaluate_track_b_claim
    )

    response = client.post(
        "/ai/track-b-claim",
        json={
            "provider": "google",
            "tier": "deep_judgment",
            "claim": {
                "claim_id": "claim-1",
                "claim_text": "Add detailed service pages.",
            },
            "judge_context": {
                "supported_problems": [{"problem_id": "problem-1"}],
            },
        },
    )

    assert response.status_code == 502
    assert response.json()["detail"]["error_code"] == "invalid_track_b_judge_contract"
