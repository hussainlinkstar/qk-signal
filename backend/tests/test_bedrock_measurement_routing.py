import sys
import types
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.visibility_index_jobs import VisibilityIndexJobService


@pytest.fixture(autouse=True)
def _canonical_measurement_map(monkeypatch):
    """Pin the measurement model map so these tests are deterministic and
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
@pytest.mark.parametrize(
    "provider,expected_model_id",
    [
        ("openai", "openai.gpt-oss-120b-1:0"),
        ("google", "qwen.qwen3-235b-a22b-2507-v1:0"),
        ("anthropic", "eu.amazon.nova-pro-v1:0"),
        ("deepseek", "deepseek.v3.2"),
    ],
)
async def test_measurement_always_routes_to_bedrock_with_mapped_model(provider, expected_model_id):
    """Measurement is Bedrock-only and unconditional: _run_provider always
    routes to _run_bedrock with the model id mapped for the provider,
    never touching the legacy external engines."""
    bedrock_calls: list[tuple[str, str]] = []

    async def stub_bedrock(self_inner, model_id, prompt):
        bedrock_calls.append((model_id, prompt))
        return {"answer": f"bedrock:{model_id}", "raw": {}}

    async def fail_external(self_inner, prompt):
        raise AssertionError("external engine must not be called; measurement is Bedrock-only")

    service = VisibilityIndexJobService(provider_callable=None)
    service._run_bedrock = types.MethodType(stub_bedrock, service)
    for attr in ("_run_openai", "_run_google", "_run_anthropic", "_run_deepseek"):
        setattr(service, attr, types.MethodType(fail_external, service))

    result = await service._run_provider(provider, "test prompt")

    assert bedrock_calls == [(expected_model_id, "test prompt")]
    assert result["answer"] == f"bedrock:{expected_model_id}"


@pytest.mark.asyncio
async def test_unmapped_provider_raises_value_error():
    """A provider with no Bedrock mapping raises ValueError instead of
    falling back to an external engine."""
    service = VisibilityIndexJobService(provider_callable=None)

    with pytest.raises(ValueError, match="Unsupported provider 'unknown'"):
        await service._run_provider("unknown", "test prompt")


@pytest.mark.asyncio
async def test_provider_callable_takes_precedence():
    """An injected provider_callable (used by tests) still wins over the
    unconditional Bedrock measurement routing."""

    async def fake_provider(provider, prompt):
        return {"answer": f"callable:{provider}", "citations": []}

    service = VisibilityIndexJobService(provider_callable=fake_provider)
    result = await service._run_provider("openai", "test prompt")

    assert result["answer"] == "callable:openai"
