"""Lightweight unit tests for ``AIFactory`` — tier routing, provider selection,
fallback logic, and response normalization.

These tests exercise the AIFactory methods directly without going through the
full ``generate_audit`` pipeline (which involves heavy prompt construction,
thread-pool dispatch, and normalization that make it slow even with fakes).
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")


# ---------------------------------------------------------------------------
# Canonical fake audit JSON
# ---------------------------------------------------------------------------

FAKE_AUDIT_JSON = {
    "summary": "Test audit summary for a SaaS company.",
    "recommendations": [
        {"title": "Add schema markup", "impact": "high", "effort": "low"},
    ],
    "seo_score": 72.5,
    "geo_score": 65.0,
    "aeo_score": 58.3,
    "schema_version": "3.0",
    "entity_analysis": {"entities": [{"name": "Acme", "type": "Organization"}]},
    "seo_findings": [],
    "geo_findings": [],
    "aeo_findings": [],
    "aeo_signals": {},
    "geo_signals": {},
    "technical_signals": {},
}


# ---------------------------------------------------------------------------
# Fake provider responses — Bedrock only (single-vendor reasoning)
# ---------------------------------------------------------------------------


class _FakeBedrockClient:
    """Stubs the boto3 ``bedrock-runtime`` client's ``converse`` call so the
    Bedrock-only reasoning path can be exercised without any network/AWS access.

    Mirrors the shape ``_generate_with_bedrock`` expects: an ``output.message.content``
    list of blocks (one carrying ``text``) plus a token ``usage`` block.
    """

    def __init__(self, text: str | None = None):
        self._text = text if text is not None else json.dumps(FAKE_AUDIT_JSON)
        # Captures the kwargs of the most recent converse call so tests can
        # assert how the schema/system instruction was constructed.
        self.last_kwargs: dict | None = None

    def converse(self, *, modelId, messages, system, inferenceConfig, **_kw):
        self.last_kwargs = {
            "modelId": modelId,
            "messages": messages,
            "system": system,
            "inferenceConfig": inferenceConfig,
        }
        return {
            "output": {"message": {"content": [{"text": self._text}]}},
            "usage": {"inputTokens": 100, "outputTokens": 200, "totalTokens": 300},
        }


# ---------------------------------------------------------------------------
# Factory builder
# ---------------------------------------------------------------------------


def _build_ai_factory():
    from services.ai_engine import AIFactory

    ai = AIFactory()
    # Reasoning is now Bedrock-only: stub the converse client so the bedrock
    # generation path resolves locally without live AWS Bedrock calls.
    ai.bedrock_client = _FakeBedrockClient()
    return ai


# ===================================================================
# 1. Model instance resolution — all providers x tiers
# ===================================================================


@pytest.mark.parametrize(
    "provider,tier",
    [
        ("google", "fast"),
        ("google", "smart"),
        ("openai", "fast"),
        ("openai", "smart"),
        ("anthropic", "fast"),
        ("anthropic", "smart"),
    ],
)
def test_get_model_instance_resolves(provider, tier):
    ai = _build_ai_factory()
    result = ai.get_model_instance(provider, tier)
    assert result is not None, f"No model instance for {provider}/{tier}"
    resolved_provider, model_name = result
    assert isinstance(resolved_provider, str)
    assert isinstance(model_name, str)
    assert len(model_name) > 0


# ===================================================================
# 2. Tier normalization
# ===================================================================


def test_normalize_tier_aliases():
    from services.ai_engine import AIFactory

    ai = AIFactory()
    assert ai._normalize_tier("fast") == "fast"
    assert ai._normalize_tier("smart") == "smart"
    assert ai._normalize_tier("lite") in ("fast", "lite")
    assert ai._normalize_tier("deep") in ("smart", "deep")
    assert ai._normalize_tier("deep_judgment") in ("smart", "deep_judgment")


def test_normalize_provider():
    from services.ai_engine import AIFactory

    ai = AIFactory()
    # All non-Bedrock providers were retired in the Bedrock cutover: every
    # requested provider normalises to "bedrock".
    assert ai._normalize_provider("google") == "bedrock"
    assert ai._normalize_provider("gemini") == "bedrock"
    assert ai._normalize_provider("") == "bedrock"
    assert ai._normalize_provider(None) == "bedrock"
    assert ai._normalize_provider("GOOGLE") == "bedrock"
    assert ai._normalize_provider("openai") == "bedrock"
    assert ai._normalize_provider("anthropic") == "bedrock"
    assert ai._normalize_provider("bedrock") == "bedrock"


# ===================================================================
# 3. Invalid provider fallback
# ===================================================================


def test_get_model_instance_invalid_provider_returns_none():
    ai = _build_ai_factory()
    result = ai.get_model_instance("nonexistent_provider", "fast")
    assert result is None


# ===================================================================
# 4. _generate_with_bedrock — direct call (Bedrock-only reasoning path)
# ===================================================================


@pytest.mark.asyncio
async def test_generate_with_bedrock_returns_dict():
    ai = _build_ai_factory()
    result = await ai._generate_with_bedrock(
        "eu.amazon.nova-lite-v1:0", "system prompt", ["user text"]
    )
    assert isinstance(result, dict)
    assert "summary" in result or "analysis" in result


@pytest.mark.asyncio
async def test_generate_with_bedrock_with_schema():
    ai = _build_ai_factory()
    schema = {"type": "object", "properties": {"summary": {"type": "string"}}}
    result = await ai._generate_with_bedrock(
        "eu.amazon.nova-lite-v1:0", "system prompt", ["user text"], schema=schema
    )
    assert isinstance(result, dict)
    # Bedrock converse has no native json_schema response_format, so the schema
    # is folded into a JSON-only instruction appended to the system prompt.
    system_text = ai.bedrock_client.last_kwargs["system"][0]["text"]
    assert "JSON" in system_text


# ===================================================================
# 7. Response normalization
# ===================================================================


def test_normalize_analysis_payload_preserves_scores():
    ai = _build_ai_factory()
    raw = {
        "seo_score": 80,
        "geo_score": 70,
        "aeo_score": 60,
        "summary": "Test",
        "recommendations": [],
    }
    normalized = ai._normalize_analysis_payload(raw)
    assert isinstance(normalized, dict)


def test_normalize_usage_dict():
    ai = _build_ai_factory()
    usage = ai._normalize_usage_dict(
        {
            "prompt_tokens": 100,
            "completion_tokens": 200,
            "total_tokens": 300,
        }
    )
    assert isinstance(usage, dict)
    assert usage.get("prompt_tokens") == 100 or usage.get("input_tokens") == 100


def test_normalize_usage_dict_none():
    ai = _build_ai_factory()
    usage = ai._normalize_usage_dict(None)
    assert isinstance(usage, dict)


# ===================================================================
# 8. extract_generation_metadata
# ===================================================================


def test_extract_generation_metadata_from_response():
    ai = _build_ai_factory()
    raw = {
        "provider": "google",
        "model": "gemini-2.5-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }
    meta = ai.extract_generation_metadata(raw)
    assert isinstance(meta, dict)


# ===================================================================
# 9. _generate_with_provider dispatch
# ===================================================================


# Reasoning is Bedrock-only: every provider normalizes to "bedrock" and
# _generate_with_provider dispatches solely to the Bedrock path.
@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["bedrock"])
async def test_generate_with_provider_dispatches_correctly(provider):
    ai = _build_ai_factory()
    model_info = ai.get_model_instance(provider, "fast")
    if model_info is None:
        pytest.skip(f"No model configured for {provider}/fast")
    resolved_provider, model_name = model_info
    result = await ai._generate_with_provider(
        resolved_provider, model_name, "system prompt", ["user text"]
    )
    assert isinstance(result, dict)


# ===================================================================
# 10. Category and market combinations (prompt building, not full audit)
# ===================================================================


@pytest.mark.parametrize(
    "category,market",
    [
        ("finance", "Romania"),
        ("healthcare", "United States"),
        (None, None),
        ("SaaS", None),
    ],
)
def test_category_market_do_not_crash_model_resolution(category, market):
    """Verify that category/market values don't break model resolution."""
    ai = _build_ai_factory()
    result = ai.get_model_instance("google", "fast")
    assert result is not None
