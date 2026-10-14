"""Determinism of the audit scoring, judging and synthesis calls (SIGV2-1109).

Two back-to-back scans of the same site returned different scores. The audit
pipeline sampled (``AUDIT_AI_TEMPERATURE`` 0.2, debate critics up to 0.4) and
the "fixed sampling seed" in ``core.config`` was read by nothing, so the code
looked reproducible while it was not.

The only reasoning provider is AWS Bedrock. Its ``converse`` API takes
``maxTokens``, ``temperature``, ``topP`` and ``stopSequences`` in
``inferenceConfig`` and exposes no sampling seed, so the dead seed setting was
removed rather than wired through.

What these tests prove: the parameters this codebase hands to the model client
are deterministic. What they do not prove: that a real provider returns an
identical score for an identical input. That is end-to-end behaviour and needs
repeated live scans to assert.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core.config import settings  # noqa: E402
from report_schema import SEO_EXPERT_SCHEMA  # noqa: E402
from services.debate_orchestrator import _temperature_for_role  # noqa: E402


class _RecordingBedrockClient:
    """Captures the kwargs of every ``converse`` call made against it."""

    def __init__(self, payload: dict[str, Any] | None = None):
        self._text = json.dumps(payload or {"summary": "ok"})
        self.calls: list[dict[str, Any]] = []

    def converse(self, *, modelId, messages, system, inferenceConfig, **_kw):
        self.calls.append(
            {
                "modelId": modelId,
                "messages": messages,
                "system": system,
                "inferenceConfig": inferenceConfig,
            }
        )
        return {
            "output": {"message": {"content": [{"text": self._text}]}},
            "usage": {"inputTokens": 10, "outputTokens": 20, "totalTokens": 30},
        }


def _build_ai_factory() -> tuple[Any, _RecordingBedrockClient]:
    from services.ai_engine import AIFactory

    ai = AIFactory()
    client = _RecordingBedrockClient()
    ai.bedrock_client = client
    return ai, client


class TestDeterminismConfig:
    def test_audit_temperature_is_greedy(self):
        assert settings.AUDIT_AI_TEMPERATURE == 0.0

    def test_critic_temperature_matches_audit_temperature(self):
        assert settings.AUDIT_CRITIC_TEMPERATURE == settings.AUDIT_AI_TEMPERATURE

    def test_no_dead_sampling_seed_setting(self):
        # Bedrock converse has no seed parameter. A setting nothing reads makes
        # the pipeline look reproducible when it is not, so it must not exist.
        assert not hasattr(settings, "AUDIT_AI_SEED")


class TestDebateStepTemperature:
    @pytest.mark.parametrize(
        "role",
        [
            "seo_generator",
            "aeo_geo_gen",
            "proposer",
            "seo_critic",
            "centralized_critic",
            "consolidator",
            "synthesizer",
            "fast_synthesizer",
            "smart_synthesizer",
            "judge",
            "magistrate",
            "global_magistrate",
        ],
    )
    def test_every_debate_role_decodes_greedily(self, role):
        assert _temperature_for_role(role) == 0.0

    def test_configured_zero_is_not_treated_as_unset(self, monkeypatch):
        # The previous implementation used ``or`` as its default, so a
        # configured 0.0 fell through to 0.2 (0.4 for critics).
        monkeypatch.setattr(settings, "AUDIT_AI_TEMPERATURE", 0.0, raising=False)
        monkeypatch.setattr(settings, "AUDIT_CRITIC_TEMPERATURE", 0.0, raising=False)
        assert _temperature_for_role("judge") == 0.0
        assert _temperature_for_role("seo_critic") == 0.0


class TestModelClientReceivesDeterministicParameters:
    """The temperature that actually reaches the Bedrock client, per call site."""

    @pytest.mark.asyncio
    async def test_domain_expert_scoring_call(self):
        ai, client = _build_ai_factory()
        await ai._call_claude_expert_attempt(
            domain="seo",
            # Ignored by the callee, which resolves the Bedrock smart model
            # from settings. Never a hard-coded model id.
            model_name="",
            context_text="evidence anchor",
            schema=SEO_EXPERT_SCHEMA,
        )
        assert client.calls, "expert scoring made no Bedrock call"
        assert client.calls[-1]["inferenceConfig"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_synthesis_call(self):
        ai, client = _build_ai_factory()
        await ai._call_openai_synthesizer({"seo": {}, "aeo": {}, "geo": {}})
        assert client.calls, "synthesis made no Bedrock call"
        assert client.calls[-1]["inferenceConfig"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_judge_call(self):
        ai, client = _build_ai_factory()
        await ai.evaluate_track_b_claim(
            provider="bedrock",
            tier="smart",
            claim={"claim_id": "c1", "claim_text": "Add FAQ schema."},
            judge_context={},
        )
        assert client.calls, "judge made no Bedrock call"
        assert client.calls[-1]["inferenceConfig"]["temperature"] == 0.0

    @pytest.mark.asyncio
    async def test_no_sampling_seed_is_sent_to_the_provider(self):
        ai, client = _build_ai_factory()
        await ai._call_openai_synthesizer({"seo": {}})
        inference_config = client.calls[-1]["inferenceConfig"]
        assert "seed" not in inference_config
