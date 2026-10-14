from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"

from report_schema import TRACK_B_JUDGE_SCHEMA
from services.ai_engine import AIFactory
from services import ai_engine as ai_engine_module


@pytest.mark.asyncio
async def test_expand_recommendation_injects_category_kb_and_project_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        factory, "get_model_instance", lambda provider, tier: ("google", "gemini-test")
    )
    monkeypatch.setattr(
        ai_engine_module.knowledge_service,
        "get_domain_context",
        lambda category=None: "SEO KB RULES" if category == "seo" else "ALL KB",
    )

    async def _fake_generate_with_provider(
        provider, model_name, system_prompt, user_prompt, schema=None, *, temperature=None
    ):
        captured["provider"] = provider
        captured["model_name"] = model_name
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["schema"] = schema
        return {"guide_markdown": "## Strategic Context\nGrounded"}

    monkeypatch.setattr(factory, "_generate_with_provider", _fake_generate_with_provider)

    result = await factory.expand_recommendation(
        recommendation_text="Add FAQ schema to product pages.",
        site_url="https://example.com",
        category="seo",
        project_context={"project_name": "Example", "target_country": "US"},
    )

    assert result == "## Strategic Context\nGrounded"
    assert captured["provider"] == "google"
    assert captured["model_name"] == "gemini-test"
    assert "SEO KB RULES" in str(captured["system_prompt"])
    assert "Project context JSON" in str(captured["user_prompt"][0])
    assert '"project_name": "Example"' in str(captured["user_prompt"][0])


@pytest.mark.asyncio
async def test_evaluate_track_b_claim_uses_shadow_judge_schema_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = AIFactory()
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        factory, "get_model_instance", lambda provider, tier: ("openai", "gpt-test")
    )

    async def _fake_generate_with_provider(
        provider, model_name, system_prompt, user_prompt, schema=None, *, temperature=None
    ):
        captured["provider"] = provider
        captured["model_name"] = model_name
        captured["system_prompt"] = system_prompt
        captured["user_prompt"] = user_prompt
        captured["schema"] = schema
        captured["temperature"] = temperature
        return {
            "claim_id": "claim-1",
            "track": "B",
            "verdict": "supported",
            "problem_anchor_score": 0.88,
            "action_fit_score": 0.79,
            "site_specificity_score": 0.72,
            "novel_fact_risk_score": 0.12,
            "reason_codes": [],
            "problem_refs": ["claim-a"],
            "evidence_refs": ["chunk-1"],
            "explanation": "Anchored to a supported answer extraction issue.",
            "suggested_rewrite": "",
        }

    monkeypatch.setattr(factory, "_generate_with_provider", _fake_generate_with_provider)

    result = await factory.evaluate_track_b_claim(
        provider="openai",
        tier="deep_judgment",
        claim={
            "claim_id": "claim-1",
            "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
            "classification_basis": ["contains_imperative_action"],
            "premise_refs": ["claim-a"],
        },
        judge_context={
            "supported_problems": [{"problem_id": "claim-a", "text": "FAQ schema is missing."}],
            "target_profile": {"target_name": "Example"},
        },
    )

    assert captured["provider"] == "openai"
    assert captured["model_name"] == "gpt-test"
    assert captured["schema"] == TRACK_B_JUDGE_SCHEMA
    assert "supported_problems" in str(captured["user_prompt"][0])
    assert '"claim_id": "claim-1"' in str(captured["user_prompt"][0])
    assert "Prescriptive Judge for Track B" in str(captured["system_prompt"])
    assert result["provider"] == "openai"
    assert result["model"] == "gpt-test"
    assert result["judgment"]["track"] == "B"
    assert result["judgment"]["problem_refs"] == ["claim-a"]
