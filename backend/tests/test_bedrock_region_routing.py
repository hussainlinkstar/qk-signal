"""SIGV2-1028: Frankfurt-ready Bedrock routing without flipping the default.

Covers: the single region accessor + cached-client invalidation at all three
runtime sites, the region-aware measurement model map (eu-central-1 overrides),
explicit unavailability (never an invalid model id, never a silent substitute),
the forced-outage Frankfurt degradation matrix, embedding immutability, the
documented inference-profile routing metadata, and the default-region pin.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.bedrock_runtime import (
    BEDROCK_EMBEDDING_DIMENSIONS,
    BedrockModelUnavailableError,
    configured_bedrock_region,
    inference_profile_routing,
    measurement_map_inventory,
    resolve_bedrock_measurement_model,
)
from core.config import settings
from services import openrouter_client
from services.openrouter_client import OpenRouterError
from services.visibility_index_jobs import VisibilityIndexJobService

NEUTRAL_PROMPT = "What are the leading CRM tools for small businesses?"

DEFAULT_MAP = dict(settings.BEDROCK_MEASUREMENT_MODEL_MAP)
FRANKFURT = "eu-central-1"
STOCKHOLM = "eu-north-1"


# --- Default region pin ------------------------------------------------------


def test_default_region_is_still_stockholm():
    """The default must NOT move to Frankfurt in this change. Flipping it is a
    deliberate, separately-authorized act (AC2/AC6); pin it so that flip is a
    visible one-line change."""
    assert settings.BEDROCK_REGION == STOCKHOLM
    assert configured_bedrock_region() == STOCKHOLM


# --- Region-aware measurement map resolution ----------------------------------


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("openai", "openai.gpt-oss-120b-1:0"),
        ("google", "qwen.qwen3-235b-a22b-2507-v1:0"),
        ("anthropic", "eu.amazon.nova-pro-v1:0"),
        ("deepseek", "deepseek.v3.2"),
        ("perplexity", "zai.glm-5"),
        ("xai", "zai.glm-4.7"),
        ("bing", "eu.amazon.nova-pro-v1:0"),
    ],
)
def test_stockholm_resolves_full_map(provider, expected):
    assert resolve_bedrock_measurement_model(provider, STOCKHOLM) == expected


@pytest.mark.parametrize(
    "provider,expected",
    [
        # Unchanged in Frankfurt (default map carries over).
        ("openai", "openai.gpt-oss-120b-1:0"),
        ("google", "qwen.qwen3-235b-a22b-2507-v1:0"),
        ("anthropic", "eu.amazon.nova-pro-v1:0"),
        ("bing", "eu.amazon.nova-pro-v1:0"),
        # In-family substitution: glm-4.7 -> glm-4.7-flash.
        ("xai", "zai.glm-4.7-flash"),
        # Explicitly unavailable — never an invalid id, never a substitute.
        ("deepseek", None),
        ("perplexity", None),
    ],
)
def test_frankfurt_resolves_overrides(provider, expected):
    assert resolve_bedrock_measurement_model(provider, FRANKFURT) == expected


def test_explicit_unavailability_never_returns_a_model():
    """deepseek/perplexity in Frankfurt must resolve to None, not to an
    unrelated stand-in model id."""
    assert resolve_bedrock_measurement_model("deepseek", FRANKFURT) is None
    assert resolve_bedrock_measurement_model("perplexity", FRANKFURT) is None


# --- _run_provider degradation in Frankfurt -----------------------------------


def _frankfurt(monkeypatch):
    monkeypatch.setattr(settings, "BEDROCK_REGION", FRANKFURT)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["deepseek", "perplexity"])
async def test_unavailable_in_region_raises_never_calls_bedrock(monkeypatch, provider):
    """Region-configured-unavailable engine: explicit error, and boto3 (the
    Bedrock call) is never reached with an invalid model id."""
    _frankfurt(monkeypatch)

    bedrock_called = {"value": False}

    async def fake_bedrock(self, model_id, prompt):  # pragma: no cover
        bedrock_called["value"] = True
        return {"answer": "should never run"}

    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=False)
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", False)

    with pytest.raises(BedrockModelUnavailableError, match=FRANKFURT):
        await service._run_provider(provider, NEUTRAL_PROMPT)
    assert bedrock_called["value"] is False


@pytest.mark.asyncio
async def test_frankfurt_openrouter_outage_matrix(monkeypatch):
    """Forced OpenRouter outage + Frankfurt region: deepseek and perplexity
    degrade explicitly; xai falls back to its in-family Frankfurt model."""
    _frankfurt(monkeypatch)
    monkeypatch.setattr(settings, "LIVE_ENGINE_MEASUREMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "OPENROUTER_MEASUREMENT_MODEL_MAP",
        {
            "deepseek": "deepseek/deepseek-chat",
            "perplexity": "perplexity/sonar",
            "xai": "x-ai/grok",
        },
    )

    async def outage(model, prompt, **kwargs):
        raise OpenRouterError("OpenRouter request timed out")

    bedrock_calls: list[str] = []

    async def fake_bedrock(self, model_id, prompt):
        bedrock_calls.append(model_id)
        return {"answer": "proxy", "model": model_id, "engine_source": "bedrock_proxy"}

    monkeypatch.setattr(openrouter_client, "query_model", outage)
    monkeypatch.setattr(VisibilityIndexJobService, "_run_bedrock", fake_bedrock)

    service = VisibilityIndexJobService(live_engine_entitled=True)

    result = await service._run_provider("xai", NEUTRAL_PROMPT)
    assert result["engine_source"] == "bedrock_proxy"
    assert bedrock_calls == ["zai.glm-4.7-flash"]

    for provider in ("deepseek", "perplexity"):
        with pytest.raises(BedrockModelUnavailableError, match="unavailable"):
            await service._run_provider(provider, NEUTRAL_PROMPT)


# --- Region accessor + cached-client invalidation ------------------------------


class _FakeRuntimeClient:
    def __init__(self, region):
        self.region = region

    def converse(self, **kwargs):
        return {"output": {"message": {"content": [{"text": "ok"}]}}}


def test_region_change_takes_effect_at_all_three_client_sites(monkeypatch):
    """All three Bedrock-runtime client sites must resolve the NEW region after
    the setting flips — including the cached ai_engine client."""
    import boto3

    built: list[str] = []

    def fake_client(service, region_name=None, **kwargs):
        built.append(region_name)
        return _FakeRuntimeClient(region_name)

    monkeypatch.setattr(boto3, "client", fake_client)
    monkeypatch.setattr(settings, "BEDROCK_ENABLED", True)

    # Site 3 (ai_engine): builds at construction for the current region.
    from services.ai_engine import AIFactory

    factory = AIFactory()
    assert factory._get_bedrock_client().region == STOCKHOLM

    # Site 2 (visibility_index_jobs): lazy per-instance client.
    vis_service = VisibilityIndexJobService()
    assert vis_service._get_bedrock_client().region == STOCKHOLM

    # Flip the configured region mid-process.
    monkeypatch.setattr(settings, "BEDROCK_REGION", FRANKFURT)

    # Site 1 (core/bedrock_text): per call, always current.
    from core import bedrock_text

    captured = {}

    def fake_converse_factory():
        client = _FakeRuntimeClient(configured_bedrock_region())
        captured["client"] = client
        return client

    monkeypatch.setattr(bedrock_text, "create_bedrock_runtime_client", fake_converse_factory)
    monkeypatch.setattr(bedrock_text, "bedrock_available", lambda: True)
    bedrock_text.bedrock_generate_text("sys", "user")
    assert captured["client"].region == FRANKFURT

    # Site 3: the cached ai_engine client must invalidate and rebuild.
    assert factory._get_bedrock_client().region == FRANKFURT
    # Site 2: same for the visibility service client.
    assert vis_service._get_bedrock_client().region == FRANKFURT


# --- Embedding immutability ----------------------------------------------------


def test_embedding_model_and_dimensions_unchanged():
    """A casual substitution here would silently invalidate every stored vector."""
    assert settings.BEDROCK_EMBEDDING_MODEL == "eu.cohere.embed-v4:0"
    assert BEDROCK_EMBEDDING_DIMENSIONS == 1536
    from services.embedding_service import EMBEDDING_DIMENSION

    assert EMBEDDING_DIMENSION == 1536


# --- Routing metadata ----------------------------------------------------------


def test_inference_profile_routing_types():
    assert inference_profile_routing("eu.amazon.nova-pro-v1:0") == {
        "routing_type": "cross-region",
        "destination_scope": "eu",
    }
    assert inference_profile_routing("zai.glm-4.7") == {
        "routing_type": "regional",
        "destination_scope": "configured-region",
    }


def test_measurement_map_inventory_reports_availability():
    stockholm = measurement_map_inventory(STOCKHOLM)
    assert all(entry["available"] for entry in stockholm.values())

    frankfurt = measurement_map_inventory(FRANKFURT)
    assert frankfurt["xai"]["model"] == "zai.glm-4.7-flash"
    assert frankfurt["deepseek"]["available"] is False
    assert frankfurt["deepseek"]["model"] is None
    assert FRANKFURT in frankfurt["deepseek"]["reason"]
    assert frankfurt["perplexity"]["available"] is False


# --- Admin inventory surface ---------------------------------------------------


def test_admin_inventory_is_nonsecret_and_region_aware(monkeypatch):
    import admin

    payload = admin._get_bedrock_inventory()
    assert payload["region"] == STOCKHOLM
    assert payload["embedding_model"] == "eu.cohere.embed-v4:0"
    assert payload["embedding_dimensions"] == 1536
    assert payload["text_models"]["smart"]["model"] == settings.BEDROCK_SMART_MODEL
    assert payload["measurement_map"]["deepseek"]["available"] is True

    serialized = str(payload)
    for marker in ("AWS_BEARER_TOKEN", "sk-", "secret", "aws_secret"):
        assert marker.lower() not in serialized.lower()


# --- Scripts keep the real default ----------------------------------------------


def test_script_region_default_tracks_settings(monkeypatch):
    from scripts import signal_enable_invocation_logging, signal_submit_distillation

    monkeypatch.setattr(settings, "BEDROCK_REGION", FRANKFURT)
    assert signal_enable_invocation_logging._default_bedrock_region() == FRANKFURT
    assert signal_submit_distillation._default_bedrock_region() == FRANKFURT
