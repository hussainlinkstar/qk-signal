import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.ai_engine import AIFactory


class _FakeBedrockClient:
    """Stub bedrock-runtime client; records the converse() call, no network."""

    def __init__(self, response: dict):
        self.response = response
        self.calls: list[dict] = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


@pytest.mark.asyncio
async def test_generate_with_bedrock_returns_parsed_dict_with_metadata() -> None:
    factory = AIFactory()
    canned = {
        "output": {
            "message": {"content": [{"text": '{"seo_findings": []}'}]},
        },
        "usage": {"inputTokens": 10, "outputTokens": 5, "totalTokens": 15},
    }
    fake_client = _FakeBedrockClient(canned)
    factory.bedrock_client = fake_client

    result = await factory._generate_with_bedrock(
        "amazon.nova-micro-v1:0",
        "sys",
        ["hi"],
    )

    # Parsed JSON payload is returned verbatim.
    assert result["seo_findings"] == []

    # Generation metadata is attached, tagged as the bedrock provider.
    metadata = AIFactory.extract_generation_metadata(result)
    assert metadata["provider"] == "bedrock"
    assert metadata["model"] == "amazon.nova-micro-v1:0"
    assert metadata["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
    }

    # converse() was invoked deterministically with the expected shape.
    assert len(fake_client.calls) == 1
    call = fake_client.calls[0]
    assert call["modelId"] == "amazon.nova-micro-v1:0"
    assert call["messages"] == [{"role": "user", "content": [{"text": "hi"}]}]
    assert call["system"][0]["text"].startswith("sys")
    assert "JSON" in call["system"][0]["text"]
    assert call["inferenceConfig"] == {"maxTokens": 8192}


def test_get_model_instance_resolves_bedrock_models() -> None:
    # Closes the generate_audit fallback leak: bedrock must resolve to a model
    # (else routing→bedrock falls back to openai). Provider key stays "bedrock".
    factory = AIFactory()
    assert factory.get_model_instance("bedrock", "smart") == (
        "bedrock",
        "eu.amazon.nova-pro-v1:0",
    )
    assert factory.get_model_instance("bedrock", "fast") == ("bedrock", "eu.amazon.nova-lite-v1:0")
    assert factory.get_model_instance("bedrock", "lite") == ("bedrock", "eu.amazon.nova-micro-v1:0")


@pytest.mark.asyncio
async def test_generate_with_bedrock_raises_when_client_unconfigured() -> None:
    factory = AIFactory()
    factory.bedrock_client = None

    with pytest.raises(ConnectionError):
        await factory._generate_with_bedrock("amazon.nova-micro-v1:0", "sys", ["hi"])
