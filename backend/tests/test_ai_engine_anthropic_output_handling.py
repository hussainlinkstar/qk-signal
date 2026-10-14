import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from report_schema import SEO_EXPERT_SCHEMA
from services.ai_engine import AIFactory


@pytest.mark.asyncio
async def test_call_claude_expert_falls_back_to_domain_fallback_when_bedrock_attempts_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    attempts = {"bedrock": 0}

    async def _fake_call_with_resilience(provider: str, operation):
        if provider == "bedrock":
            attempts["bedrock"] += 1
            raise ValueError("bedrock expert failure")
        return await operation()

    async def _fake_domain_fallback(*, domain: str, context_text: str, schema: dict):
        assert domain == "seo"
        assert context_text == "ctx"
        assert schema == SEO_EXPERT_SCHEMA
        return factory._attach_generation_metadata(
            {
                "seo_findings": [],
                "technical_signals": {
                    "mobile_friendliness": 80.0,
                    "security_score": 90.0,
                    "accessibility_score": 70.0,
                },
            },
            provider="bedrock",
            model_name="eu.amazon.nova-lite-v1:0",
            usage={"prompt_tokens": 25, "completion_tokens": 10, "total_tokens": 35},
        )

    monkeypatch.setattr(factory, "_call_with_resilience", _fake_call_with_resilience)
    monkeypatch.setattr(factory, "_call_openai_domain_fallback", _fake_domain_fallback)

    payload, warning = await factory._call_claude_expert(
        domain="seo",
        model_name="claude-opus-4-6",
        context_text="ctx",
        schema=SEO_EXPERT_SCHEMA,
    )

    # Both the primary attempt and the explicit-json retry run under the
    # bedrock resilience breaker before the domain fallback is invoked.
    assert attempts["bedrock"] == 2
    # Marker string is preserved for downstream telemetry compatibility.
    assert warning == "seo_expert_fell_back_to_openai"
    assert payload["seo_findings"] == []
    assert payload["claim_ledger"] == []
    assert payload["_thothgraph_provider"] == "bedrock"


class _FakeBedrockClient:
    """Stub bedrock-runtime client; records the converse() call, no network."""

    def __init__(self, response: dict):
        self.response = response
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_call_claude_expert_attempt_hydrates_missing_claim_ledger_from_bedrock_text_payload() -> (
    None
):
    # The expert attempt now runs exclusively on Bedrock (smart tier). It must
    # still hydrate a missing claim_ledger from the model's text payload.
    factory = AIFactory()
    canned = {
        "output": {
            "message": {
                "content": [
                    {
                        "text": (
                            '{"seo_findings":[{"description":"Critical crawl issue on faceted URLs.",'
                            '"severity":"critical","category":"indexing"}],'
                            '"technical_signals":{"mobile_friendliness":78,"security_score":88}}'
                        )
                    }
                ]
            }
        },
        "usage": {"inputTokens": 12, "outputTokens": 8, "totalTokens": 20},
    }
    fake_client = _FakeBedrockClient(canned)
    factory.bedrock_client = fake_client

    payload = await factory._call_claude_expert_attempt(
        domain="seo",
        model_name="claude-opus-4-6",  # ignored; resolves bedrock smart internally
        context_text="ctx",
        schema=SEO_EXPERT_SCHEMA,
    )

    # The expert attempt routes to the resolved bedrock smart model.
    assert fake_client.calls[0]["modelId"] == "eu.amazon.nova-pro-v1:0"
    assert payload["claim_ledger"][0]["domain"] == "seo"
    assert payload["claim_ledger"][0]["claim_text"] == "Critical crawl issue on faceted URLs."


def test_safe_expert_default_includes_empty_claim_ledger() -> None:
    factory = AIFactory()

    assert factory._safe_expert_default("seo")["claim_ledger"] == []
    assert factory._safe_expert_default("geo")["claim_ledger"] == []
    assert factory._safe_expert_default("aeo")["claim_ledger"] == []
