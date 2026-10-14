"""Unit tests for the debate orchestrator state machine."""

import asyncio
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
sys.modules.setdefault("dotenv", SimpleNamespace(load_dotenv=lambda *args, **kwargs: False))


class _FallbackNamespace(SimpleNamespace):
    """SimpleNamespace that returns None for missing attributes instead of raising."""

    def __getattr__(self, name):
        return None


if "core.config" not in sys.modules:
    core_config_module = ModuleType("core.config")
    core_config_module.settings = _FallbackNamespace(
        DEBATE_ENABLED=True,
        DEBATE_COST_CAP_USD=0.25,
        DEBATE_COST_CAP_MULTIPLIER=1.35,
        DEBATE_TOTAL_TIMEOUT_FAST_S=60,
        DEBATE_STEP_TIMEOUT_FAST_S=15,
        DEBATE_COST_CAP_FAST_USD=0.50,
        DEBATE_TOTAL_TIMEOUT_SMART_S=300,
        DEBATE_STEP_TIMEOUT_SMART_S=60,
        DEBATE_COST_CAP_SMART_USD=5.0,
        DEBATE_TOTAL_TIMEOUT_DEEP_S=600,
        DEBATE_STEP_TIMEOUT_DEEP_S=90,
        DEBATE_COST_CAP_DEEP_USD=20.0,
    )
    core_config_module.effective_gemini_api_key_from_env = lambda: None
    sys.modules["core.config"] = core_config_module
sys.modules.setdefault(
    "services.cost_forecast_service",
    _FallbackNamespace(
        forecast_audit_cost=lambda **kwargs: SimpleNamespace(estimated_llm_cost_usd=0.0)
    ),
)

from report_schema import AI_AUDIT_SCHEMA_VERSION
from services.ai_routing_policy import AuditRouteResolution
from services.ai_routing_policy import provider_runtime_state_service
from services.debate_orchestrator import (
    DebateAgentResult,
    PipelineConfig,
    _build_aeo_geo_generator_prompt,
    _build_aeo_critic_prompt,
    _build_aeo_generator_prompt,
    _aggregate_usage,
    _build_centralized_critic_prompt,
    _build_challenger_prompt,
    _build_consolidator_prompt,
    _build_deep_seo_generator_prompt,
    _build_fast_critic_prompt,
    _build_fast_proposer_prompt,
    _build_fast_synthesizer_prompt,
    _build_geo_critic_prompt,
    _build_geo_generator_prompt,
    _build_global_magistrate_prompt,
    _build_magistrate_prompt,
    _build_proposer_prompt,
    _build_seo_critic_prompt,
    _build_seo_generator_prompt,
    _build_smart_synthesizer_prompt,
    _build_synthesizer_prompt,
    _estimate_step_cost,
    _prepare_anthropic_prompt_inputs,
    _resolve_pipeline_config,
    _run_agent_step,
    _run_agent_step_with_cascade,
    run_debate,
)


@pytest.fixture(autouse=True)
def _mock_provider_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="available"),
    )


def _canonical_analysis(summary: str = "ok") -> dict:
    return {
        "schema_version": AI_AUDIT_SCHEMA_VERSION,
        "summary": summary,
        "recommendations": [],
        "seo_findings": [],
        "geo_findings": [],
        "aeo_findings": [],
        "entity_analysis": {
            "entity_clarity_score": 0.8,
            "brand_trust_score": 0.75,
            "knowledge_graph_presence": True,
            "dominant_entities": [],
        },
        "aeo_signals": {
            "answerability_score": 70.0,
            "voice_readiness_score": 68.0,
            "key_recommendations": [],
        },
        "geo_signals": {
            "citation_consistency_score": 69.0,
            "local_authority_score": 71.0,
        },
        "technical_signals": {
            "mobile_friendliness": 78.0,
            "security_score": 85.0,
        },
        "seo_score": 70,
        "geo_score": 71,
        "aeo_score": 72,
    }


def _strict_critic_output() -> dict:
    return {
        "unsupported_claims": [
            {
                "target_claim": "Authority graph is complete",
                "issue_type": "unsupported_claim",
                "severity": "critical",
                "counter_argument": "The crawl evidence does not show authoritative citation coverage.",
                "suggested_disposition": "downgrade",
            }
        ],
        "invented_links_or_citations": [],
        "weak_recommendations": [],
        "missed_items": ["FAQ schema evidence is absent"],
        "unresolved_questions": ["Is there a verifiable citation source for the benchmark claim?"],
        "confidence_delta": -0.2,
        "_thothgraph_usage": {
            "prompt_tokens": 2000,
            "completion_tokens": 800,
            "total_tokens": 2800,
        },
    }


def _seo_expert_output(summary: str = "seo") -> dict:
    return {
        "claim_ledger": [
            {
                "claim_id": "seo-01",
                "domain": "seo",
                "claim_text": "Faceted URLs are wasting crawl budget.",
                "confidence": 0.91,
                "evidence_refs": ["seo_findings[0]"],
                "recommended_action": "Block crawl traps on faceted pages.",
            }
        ],
        "seo_findings": [
            {
                "description": f"{summary} finding",
                "severity": "critical",
                "category": "indexing",
            }
        ],
        "technical_signals": {
            "mobile_friendliness": 78.0,
            "security_score": 85.0,
            "accessibility_score": 74.0,
        },
        "_thothgraph_usage": {
            "prompt_tokens": 1000,
            "completion_tokens": 450,
            "total_tokens": 1450,
        },
    }


def _aeo_geo_expert_output(summary: str = "aeo-geo") -> dict:
    return {
        "claim_ledger": [
            {
                "claim_id": "aeo-geo-01",
                "domain": "aeo_geo",
                "claim_text": "Entity references are inconsistent across answer surfaces.",
                "confidence": 0.88,
                "evidence_refs": ["geo_findings[0]", "aeo_findings[0]"],
                "recommended_action": "Normalize brand and answer entities across core pages.",
            }
        ],
        "summary": summary,
        "recommendations": ["Normalize entity references across service and FAQ pages."],
        "geo_findings": [
            {
                "description": "Entity references are inconsistent across local citations.",
                "severity": "warning",
                "category": "citations",
            }
        ],
        "geo_signals": {
            "citation_consistency_score": 61.0,
            "local_authority_score": 58.0,
            "relevance_score": 57.0,
            "competitor_overlap_score": 52.0,
        },
        "entity_analysis": {
            "entity_clarity_score": 64.0,
            "brand_trust_score": 59.0,
            "knowledge_graph_presence": False,
            "dominant_entities": ["Brand"],
        },
        "aeo_findings": [
            {
                "description": "Answer blocks are missing on transactional pages.",
                "severity": "warning",
                "category": "answerability",
            }
        ],
        "aeo_signals": {
            "answerability_score": 67.0,
            "content_freshness_score": 55.0,
            "schema_completeness": 54.0,
            "voice_readiness_score": 62.0,
            "key_recommendations": ["Add concise answer blocks to service pages."],
        },
        "citation_probability_score": 0.42,
        "_thothgraph_usage": {
            "prompt_tokens": 1050,
            "completion_tokens": 500,
            "total_tokens": 1550,
        },
    }


def _geo_expert_output(summary: str = "geo") -> dict:
    return {
        "claim_ledger": [
            {
                "claim_id": "geo-01",
                "domain": "geo",
                "claim_text": "Brand authority is inconsistent across local citations.",
                "confidence": 0.86,
                "evidence_refs": ["geo_findings[0]"],
                "recommended_action": "Normalize entity and location references across citations.",
            }
        ],
        "geo_findings": [
            {
                "description": f"{summary} finding",
                "severity": "warning",
                "category": "authority",
            }
        ],
        "geo_signals": {
            "citation_consistency_score": 63.0,
            "local_authority_score": 59.0,
            "relevance_score": 60.0,
            "competitor_overlap_score": 54.0,
        },
        "entity_analysis": {
            "entity_clarity_score": 66.0,
            "brand_trust_score": 61.0,
            "knowledge_graph_presence": False,
            "dominant_entities": ["Brand"],
        },
        "_thothgraph_usage": {"prompt_tokens": 980, "completion_tokens": 420, "total_tokens": 1400},
    }


def _aeo_expert_output(summary: str = "aeo") -> dict:
    return {
        "claim_ledger": [
            {
                "claim_id": "aeo-01",
                "domain": "aeo",
                "claim_text": "Transactional pages are missing concise answer blocks.",
                "confidence": 0.84,
                "evidence_refs": ["aeo_findings[0]"],
                "recommended_action": "Add short answer blocks to high-intent service pages.",
            }
        ],
        "aeo_findings": [
            {
                "description": f"{summary} finding",
                "severity": "warning",
                "category": "answerability",
            }
        ],
        "aeo_signals": {
            "answerability_score": 68.0,
            "content_freshness_score": 57.0,
            "schema_completeness": 56.0,
            "voice_readiness_score": 63.0,
            "key_recommendations": ["Add concise answer blocks to service pages."],
        },
        "citation_probability_score": 0.44,
        "_thothgraph_usage": {"prompt_tokens": 960, "completion_tokens": 410, "total_tokens": 1370},
    }


def _consolidated_output(summary: str = "delta-consolidated", confidence: float = 0.82) -> dict:
    return {
        "domain_summaries": {
            "seo": {
                "accepted_claims": 1,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "needs_manual_review": 0,
                "top_findings": ["SEO crawl traps remain unresolved."],
                "recommended_actions": ["Block crawl traps on faceted pages."],
            },
            "geo": {
                "accepted_claims": 1,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "needs_manual_review": 0,
                "top_findings": ["Entity authority is inconsistent across citations."],
                "recommended_actions": [
                    "Normalize entity and location references across citations."
                ],
            },
            "aeo": {
                "accepted_claims": 1,
                "downgraded_claims": 1,
                "rejected_claims": 0,
                "needs_manual_review": 0,
                "top_findings": ["Answer blocks are missing on service pages."],
                "recommended_actions": ["Add concise answer blocks to service pages."],
            },
        },
        "cross_domain_conflicts": [],
        "consolidated_claim_disposition": [
            {
                "claim_id": "seo-01",
                "domain": "seo",
                "original_confidence": 0.91,
                "post_critique_confidence": 0.88,
                "disposition": "accepted",
                "critique_reference": "seo.challenge_01",
            },
            {
                "claim_id": "geo-01",
                "domain": "geo",
                "original_confidence": 0.86,
                "post_critique_confidence": 0.81,
                "disposition": "accepted",
                "critique_reference": "geo.challenge_01",
            },
            {
                "claim_id": "aeo-01",
                "domain": "aeo",
                "original_confidence": 0.84,
                "post_critique_confidence": 0.71,
                "disposition": "downgraded",
                "critique_reference": "aeo.challenge_01",
            },
        ],
        "dedup_count": 1,
        "dedup_details": [
            {
                "removed_domain": "aeo",
                "kept_domain": "geo",
                "topic": "entity_authority",
                "reason": "Domain Boundary Contract: geo owns entity authority topics.",
            }
        ],
        "synthesis_reasoning": summary,
        "overall_confidence_score": confidence,
        "_thothgraph_usage": {
            "prompt_tokens": 1800,
            "completion_tokens": 500,
            "total_tokens": 2300,
        },
    }


def _judge_output(summary: str = "final") -> dict:
    return {
        **_canonical_analysis(summary),
        "synthesis_reasoning": "The judge retained only the grounded conclusions.",
        "debate_confidence_score": 0.91,
        "judge_summary": {
            "accepted_claims": 4,
            "downgraded_claims": 1,
            "rejected_claims": 1,
            "unresolved_disputes": 1,
        },
        "_thothgraph_usage": {
            "prompt_tokens": 3000,
            "completion_tokens": 1000,
            "total_tokens": 4000,
        },
    }


def _make_route(
    provider: str, tier: str, role: str, *, requested_tier: str = "smart"
) -> AuditRouteResolution:
    return AuditRouteResolution(
        feature_key=f"audit.debate.{role}",
        requested_tier=requested_tier,
        tier_class="fast" if tier == "fast" else "deep",
        product_label=(
            "High Confidence / Prescriptive Confidence mode"
            if requested_tier == "deep_judgment"
            else ("Fast" if requested_tier == "fast" else "Smart")
        ),
        provider=provider,
        execution_tier=tier,
    )


def _make_factory(side_effects=None):
    factory = MagicMock()

    if side_effects is None:
        side_effects = [
            {
                **_canonical_analysis("proposal"),
                "_thothgraph_usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "total_tokens": 1500,
                },
            },
            {
                "challenges": [
                    {
                        "target_claim": "Schema is complete",
                        "counter_argument": "Missing FAQ schema",
                        "severity": "moderate",
                    }
                ],
                "missed_items": ["No hreflang"],
                "disagreements": [],
                "confidence_delta": -0.1,
                "_thothgraph_usage": {
                    "prompt_tokens": 2000,
                    "completion_tokens": 800,
                    "total_tokens": 2800,
                },
            },
            {
                **_canonical_analysis("final"),
                "synthesis_reasoning": "Challenger correctly identified missing FAQ schema.",
                "debate_confidence_score": 0.89,
                "_thothgraph_usage": {
                    "prompt_tokens": 3000,
                    "completion_tokens": 1000,
                    "total_tokens": 4000,
                },
            },
        ]

    factory._generate_with_provider = AsyncMock(side_effect=side_effects)
    factory.get_model_instance = MagicMock(
        side_effect=lambda provider, tier: (provider, f"{provider}-model")
    )
    factory.extract_generation_metadata = MagicMock(
        side_effect=lambda payload: {
            "usage": payload.get("_thothgraph_usage", {}) if isinstance(payload, dict) else {}
        }
    )
    return factory


SAMPLE_AUDIT_DATA = {
    "content": "# Test page\nSample content for audit.",
    "network_data": {"http2": True},
    "context_payload": {},
}


def test_prepare_anthropic_prompt_inputs_truncates_to_budget() -> None:
    original_system_prompt = "system|" * 2_500
    original_user_prompt = ["payload|" * 8_000]

    system_prompt, user_prompt, truncated, original_total_chars = _prepare_anthropic_prompt_inputs(
        role="centralized_critic",
        system_prompt=original_system_prompt,
        user_prompt=original_user_prompt,
    )

    assert truncated is True
    assert original_total_chars > 50_000
    assert len(system_prompt) + len(user_prompt[0]) <= 50_000
    assert len(system_prompt) <= 12_000
    assert len(user_prompt[0]) < len(original_user_prompt[0])
    assert user_prompt[0].endswith("[Truncated for Anthropic payload budget]")


@pytest.mark.asyncio
@patch("services.debate_orchestrator.resolve_debate_route")
async def test_run_agent_step_falls_back_when_anthropic_payload_is_too_large(
    mock_resolve: MagicMock,
) -> None:
    factory = _make_factory()
    attempts: list[tuple[str, int, int]] = []
    original_system_prompt = "system|" * 2_500
    original_user_prompt = ["payload|" * 8_000]

    async def _fake_generate(
        provider: str,
        model_name: str,
        system_prompt: str,
        user_prompt: list,
        schema: dict[str, object] | None = None,
        *,
        temperature: float | None = None,
    ) -> dict[str, object]:
        del model_name, schema, temperature
        attempts.append(
            (
                provider,
                len(system_prompt),
                len(user_prompt[0]) if user_prompt and isinstance(user_prompt[0], str) else 0,
            )
        )
        if provider == "anthropic":
            raise ValueError("payload too large for anthropic")
        return {
            "summary": "fallback-ok",
            "_thothgraph_usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
            },
        }

    factory._generate_with_provider = AsyncMock(side_effect=_fake_generate)
    mock_resolve.return_value = _make_route("openai", "smart", "centralized_critic")

    rounds: list[DebateAgentResult] = []
    result = await _run_agent_step(
        ai_factory=factory,
        rounds=rounds,
        role="centralized_critic",
        system_prompt=original_system_prompt,
        user_prompt=original_user_prompt,
        schema={"required": ["summary"]},
        required_keys=("summary",),
        requested_tier="smart",
        step_timeout_s=5,
        route_override=_make_route("anthropic", "smart", "centralized_critic"),
        layer_index=2,
    )

    assert [attempt[0] for attempt in attempts] == ["anthropic", "openai"]
    assert attempts[0][1] <= 12_000
    assert attempts[0][2] < len(original_user_prompt[0])
    assert attempts[1][1] == len(original_system_prompt)
    assert attempts[1][2] == len(original_user_prompt[0])
    assert result.provider == "openai"
    assert result.model == "openai-model"
    assert result.route_resolution is not None
    assert result.route_resolution.provider == "openai"
    assert len(rounds) == 1


class TestDebateHappyPath:
    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_fast_pipeline_returns_three_rounds(self, mock_resolve):
        mock_resolve.side_effect = [
            _make_route("google", "fast", "fast_proposer", requested_tier="fast"),
            _make_route("anthropic", "fast", "fast_critic", requested_tier="fast"),
            _make_route("openai", "fast", "fast_synthesizer", requested_tier="fast"),
        ]
        factory = _make_factory()

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Fast context",
            requested_tier="fast",
        )

        assert result.profile == "fast_3step"
        assert result.pipeline_type == "fast_3step"
        assert result.parallel_layers == 0
        assert len(result.rounds) == 3
        assert result.rounds[0].role == "fast_proposer"
        assert result.rounds[1].role == "fast_critic"
        assert result.rounds[2].role == "fast_synthesizer"
        assert all(
            round_result.route_resolution.execution_tier == "fast" for round_result in result.rounds
        )
        assert result.agent_count == 3
        assert len(result.per_agent_costs) == 3
        assert all(item["execution_tier"] == "fast" for item in result.per_agent_costs)

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_fast_pipeline_collects_trace_records(self, mock_resolve):
        mock_resolve.side_effect = [
            _make_route("google", "fast", "fast_proposer", requested_tier="fast"),
            _make_route("anthropic", "fast", "fast_critic", requested_tier="fast"),
            _make_route("openai", "fast", "fast_synthesizer", requested_tier="fast"),
        ]
        factory = _make_factory()

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Fast context",
            requested_tier="fast",
        )

        assert len(result.trace_records) == 3
        assert [item["agent_role"] for item in result.trace_records] == [
            "fast_proposer",
            "fast_critic",
            "fast_synthesizer",
        ]
        assert all(item["pipeline_type"] == "fast_3step" for item in result.trace_records)
        assert all(item["status"] == "completed" for item in result.trace_records)
        assert (
            result.trace_records[0]["output_claim_ledger"]["claim_ledger_summary"][
                "returned_claims"
            ]
            >= 1
        )
        assert (
            result.trace_records[1]["output_claim_ledger"]["challenge_summary"][
                "returned_challenges"
            ]
            >= 1
        )

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_smart_v3_pipeline_produces_five_rounds(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.return_value = {
            "seo_generator": _make_route("google", "smart", "seo_generator"),
            "aeo_geo_generator": _make_route("anthropic", "smart", "aeo_geo_generator"),
        }
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "centralized_critic"),
            _make_route("google", "fast", "smart_synthesizer"),
            _make_route("openai", "smart", "magistrate"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _aeo_geo_expert_output("aeo-geo-generator"),
                _strict_critic_output(),
                {
                    **_canonical_analysis("smart-synthesis"),
                    "synthesis_reasoning": "Combined the strongest SEO and AEO/GEO claims.",
                    "debate_confidence_score": 0.83,
                    "_thothgraph_usage": {
                        "prompt_tokens": 1500,
                        "completion_tokens": 500,
                        "total_tokens": 2000,
                    },
                },
                _judge_output("smart-final"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Smart V3",
            requested_tier="smart",
        )

        assert result.profile == "smart_5step"
        assert result.pipeline_type == "smart_5step"
        assert result.parallel_layers == 1
        assert len(result.rounds) == 5
        assert [round_result.role for round_result in result.rounds] == [
            "seo_generator",
            "aeo_geo_generator",
            "centralized_critic",
            "smart_synthesizer",
            "magistrate",
        ]
        assert result.rounds[0].route_resolution.execution_tier == "smart"
        assert result.rounds[1].route_resolution.execution_tier == "smart"
        assert result.rounds[3].route_resolution.execution_tier == "fast"
        assert result.rounds[4].route_resolution.execution_tier == "smart"
        assert result.agent_count == 5
        assert len(result.per_agent_costs) == 5
        assert result.per_agent_costs[3]["execution_tier"] == "fast"
        assert result.per_agent_costs[4]["execution_tier"] == "smart"
        assert result.judge_authority == "primary"
        assert result.final_synthesis["summary"] == "smart-final"

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_smart_v3_follow_up_steps_use_compact_transfer_packets(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.return_value = {
            "seo_generator": _make_route("google", "smart", "seo_generator"),
            "aeo_geo_generator": _make_route("anthropic", "smart", "aeo_geo_generator"),
        }
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "centralized_critic"),
            _make_route("google", "fast", "smart_synthesizer"),
            _make_route("openai", "smart", "magistrate"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _aeo_geo_expert_output("aeo-geo-generator"),
                _strict_critic_output(),
                {
                    **_canonical_analysis("smart-synthesis"),
                    "synthesis_reasoning": "Combined the strongest SEO and AEO/GEO claims.",
                    "debate_confidence_score": 0.83,
                    "_thothgraph_usage": {
                        "prompt_tokens": 1500,
                        "completion_tokens": 500,
                        "total_tokens": 2000,
                    },
                },
                _judge_output("smart-final"),
            ]
        )

        await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Smart V3",
            requested_tier="smart",
        )

        critic_prompt = factory._generate_with_provider.call_args_list[2].args[3][0]
        synthesizer_prompt = factory._generate_with_provider.call_args_list[3].args[3][0]

        assert "SEO Transfer Packet" in critic_prompt
        assert "AEO+GEO Transfer Packet" in critic_prompt
        assert "claim_ledger" in critic_prompt
        assert "raw generator outputs" in critic_prompt
        assert "Centralized Critique Packet" in synthesizer_prompt
        assert "AEO+GEO Transfer Packet" in synthesizer_prompt

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_produces_eight_rounds(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "geo_critic": _make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _geo_expert_output("geo-generator"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                _strict_critic_output(),
                _strict_critic_output(),
                _consolidated_output("delta-consolidated", 0.82),
                _judge_output("delta-final"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow",
            requested_tier="deep_judgment",
        )

        assert result.profile == "delta_flow"
        assert result.pipeline_type == "delta_flow"
        assert result.parallel_layers == 2
        assert len(result.rounds) == 8
        assert [round_result.role for round_result in result.rounds] == [
            "seo_generator",
            "geo_generator",
            "aeo_generator",
            "seo_critic",
            "geo_critic",
            "aeo_critic",
            "consolidator",
            "global_magistrate",
        ]
        assert all(
            result.rounds[index].route_resolution.execution_tier == "smart" for index in range(8)
        )
        assert result.judge_authority == "primary"
        assert result.agent_count == 8
        assert result.final_synthesis["summary"] == "delta-final"

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_critics_receive_own_domain_only_and_consolidator_receives_three_critiques(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "geo_critic": _make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _geo_expert_output("geo-generator"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                _strict_critic_output(),
                _strict_critic_output(),
                _consolidated_output("delta-consolidated", 0.82),
                _judge_output("delta-final"),
            ]
        )

        await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow",
            requested_tier="deep_judgment",
        )

        prompts = [call.args[3][0] for call in factory._generate_with_provider.call_args_list]
        seo_critic_prompt = next(
            prompt for prompt in prompts if "## SEO Transfer Packet:" in prompt
        )
        geo_critic_prompt = next(
            prompt for prompt in prompts if "## GEO Transfer Packet:" in prompt
        )
        aeo_critic_prompt = next(
            prompt for prompt in prompts if "## AEO Transfer Packet:" in prompt
        )
        consolidator_prompt = next(prompt for prompt in prompts if "## Critique Packets:" in prompt)
        consolidator_system = next(
            call.args[2]
            for call in factory._generate_with_provider.call_args_list
            if "Consolidator agent" in call.args[2]
        )

        assert "Faceted URLs are wasting crawl budget." in seo_critic_prompt
        assert "Brand authority is inconsistent" not in seo_critic_prompt
        assert "Brand authority is inconsistent across local citations." in geo_critic_prompt
        assert "Transactional pages are missing concise answer blocks." not in geo_critic_prompt
        assert "Transactional pages are missing concise answer blocks." in aeo_critic_prompt
        assert "Faceted URLs are wasting crawl budget." not in aeo_critic_prompt
        assert '"seo"' in consolidator_prompt
        assert '"geo"' in consolidator_prompt
        assert '"aeo"' in consolidator_prompt
        assert "Evidence Anchor" in consolidator_system

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_fast_pipeline_uses_compact_transfer_packets(self, mock_resolve):
        mock_resolve.side_effect = [
            _make_route("google", "fast", "fast_proposer", requested_tier="fast"),
            _make_route("anthropic", "fast", "fast_critic", requested_tier="fast"),
            _make_route("openai", "fast", "fast_synthesizer", requested_tier="fast"),
        ]
        factory = _make_factory(
            side_effects=[
                {
                    **_canonical_analysis("proposal"),
                    "recommendations": ["Add FAQ schema to the services page."],
                    "seo_findings": [
                        {
                            "description": "Critical crawl issue on parameter pages.",
                            "severity": "critical",
                            "category": "indexing",
                        }
                    ],
                    "_thothgraph_usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                },
                {
                    "challenges": [
                        {
                            "target_claim": "FAQ schema is already strong",
                            "counter_argument": "Evidence does not show FAQ schema on the key services page.",
                            "severity": "moderate",
                        }
                    ],
                    "missed_items": ["No hreflang"],
                    "disagreements": [],
                    "confidence_delta": -0.1,
                    "_thothgraph_usage": {
                        "prompt_tokens": 2000,
                        "completion_tokens": 800,
                        "total_tokens": 2800,
                    },
                },
                {
                    **_canonical_analysis("final"),
                    "synthesis_reasoning": "Compact transfer packets preserved only the grounded claims.",
                    "debate_confidence_score": 0.84,
                    "_thothgraph_usage": {
                        "prompt_tokens": 3000,
                        "completion_tokens": 1000,
                        "total_tokens": 4000,
                    },
                },
            ]
        )

        await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Fast",
            requested_tier="fast",
        )

        critic_prompt = factory._generate_with_provider.call_args_list[1].args[3][0]
        synthesizer_prompt = factory._generate_with_provider.call_args_list[2].args[3][0]

        assert "Transfer Packet" in critic_prompt
        assert "claim_ledger" in critic_prompt
        assert "Critical crawl issue on parameter pages." in critic_prompt
        assert "full proposer output" in critic_prompt
        assert "Review Packet" in synthesizer_prompt
        assert "FAQ schema is already strong" in synthesizer_prompt


class TestDebatePartialFailures:
    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_graceful_one_generator_fails(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                RuntimeError("geo generator down"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                _strict_critic_output(),
                _consolidated_output("delta-consolidated", 0.79),
                _judge_output("delta-final"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow fallback",
            requested_tier="deep_judgment",
        )

        assert [round_result.role for round_result in result.rounds] == [
            "seo_generator",
            "aeo_generator",
            "seo_critic",
            "aeo_critic",
            "consolidator",
            "global_magistrate",
        ]
        assert result.fallback_reason == "generator_unavailable"
        assert result.final_synthesis["summary"] == "delta-final"

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_graceful_one_critic_fails(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "geo_critic": _make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _geo_expert_output("geo-generator"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                RuntimeError("geo critic down"),
                _strict_critic_output(),
                _consolidated_output("delta-consolidated", 0.8),
                _judge_output("delta-final"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow fallback",
            requested_tier="deep_judgment",
        )

        assert "geo_critic" not in [round_result.role for round_result in result.rounds]
        assert result.fallback_reason == "critic_unavailable"
        assert result.final_synthesis["summary"] == "delta-final"

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_graceful_consolidator_fails(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "geo_critic": _make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _geo_expert_output("geo-generator"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                _strict_critic_output(),
                _strict_critic_output(),
                RuntimeError("consolidator down"),
                _judge_output("delta-final"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow fallback",
            requested_tier="deep_judgment",
        )

        assert "consolidator" not in [round_result.role for round_result in result.rounds]
        assert result.fallback_reason == "consolidator_unavailable"
        assert result.final_synthesis["summary"] == "delta-final"

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_delta_flow_graceful_magistrate_fails_returns_consolidator_backed_output(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.side_effect = [
            {
                "seo_generator": _make_route(
                    "google", "smart", "seo_generator", requested_tier="deep_judgment"
                ),
                "geo_generator": _make_route(
                    "anthropic", "smart", "geo_generator", requested_tier="deep_judgment"
                ),
                "aeo_generator": _make_route(
                    "openai", "smart", "aeo_generator", requested_tier="deep_judgment"
                ),
            },
            {
                "seo_critic": _make_route(
                    "anthropic", "smart", "seo_critic", requested_tier="deep_judgment"
                ),
                "geo_critic": _make_route(
                    "openai", "smart", "geo_critic", requested_tier="deep_judgment"
                ),
                "aeo_critic": _make_route(
                    "google", "smart", "aeo_critic", requested_tier="deep_judgment"
                ),
            },
        ]
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "consolidator", requested_tier="deep_judgment"),
            _make_route("openai", "smart", "global_magistrate", requested_tier="deep_judgment"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _geo_expert_output("geo-generator"),
                _aeo_expert_output("aeo-generator"),
                _strict_critic_output(),
                _strict_critic_output(),
                _strict_critic_output(),
                _consolidated_output("delta-consolidated", 0.82),
                RuntimeError("magistrate down"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Delta Flow fallback",
            requested_tier="deep_judgment",
        )

        assert "global_magistrate" not in [round_result.role for round_result in result.rounds]
        assert result.fallback_reason == "judge_unavailable"
        assert result.final_provider == "openai"
        assert result.final_model == "openai-model"
        assert result.final_synthesis["summary"] == "delta-consolidated"
        assert result.debate_confidence_score == 0.82
        assert result.judge_summary == {
            "accepted_claims": 2,
            "downgraded_claims": 1,
            "rejected_claims": 0,
            "unresolved_disputes": 0,
        }

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_smart_v3_critic_failure_returns_combined_generators(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.return_value = {
            "seo_generator": _make_route("google", "smart", "seo_generator"),
            "aeo_geo_generator": _make_route("anthropic", "smart", "aeo_geo_generator"),
        }
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "centralized_critic"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _aeo_geo_expert_output("aeo-geo-generator"),
                RuntimeError("critic failed"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Smart fallback",
            requested_tier="smart",
        )

        assert len(result.rounds) == 2
        assert result.profile == "smart_5step"
        assert result.pipeline_type == "smart_5step"
        assert result.fallback_reason == "critic_unavailable"
        assert result.final_synthesis["summary"].startswith("Centralized critic unavailable")
        assert result.final_synthesis["recommendations"]

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    async def test_smart_v3_magistrate_failure_returns_synthesizer_packet(
        self,
        mock_resolve_layer,
        mock_resolve,
    ):
        mock_resolve_layer.return_value = {
            "seo_generator": _make_route("google", "smart", "seo_generator"),
            "aeo_geo_generator": _make_route("anthropic", "smart", "aeo_geo_generator"),
        }
        mock_resolve.side_effect = [
            _make_route("openai", "smart", "centralized_critic"),
            _make_route("google", "fast", "smart_synthesizer"),
            _make_route("openai", "smart", "magistrate"),
        ]
        factory = _make_factory(
            side_effects=[
                _seo_expert_output("seo-generator"),
                _aeo_geo_expert_output("aeo-geo-generator"),
                _strict_critic_output(),
                {
                    **_canonical_analysis("smart-synthesis"),
                    "synthesis_reasoning": "Prepared final packet for magistrate.",
                    "debate_confidence_score": 0.79,
                    "_thothgraph_usage": {
                        "prompt_tokens": 1500,
                        "completion_tokens": 500,
                        "total_tokens": 2000,
                    },
                },
                RuntimeError("magistrate failed"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Smart fallback",
            requested_tier="smart",
        )

        assert len(result.rounds) == 4
        assert result.fallback_reason == "judge_unavailable"
        assert result.final_provider == "google"
        assert result.final_model == "google-model"
        assert result.final_synthesis["summary"] == "smart-synthesis"
        assert result.debate_confidence_score == 0.79

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_fast_critic_failure_returns_unchallenged(self, mock_resolve):
        mock_resolve.side_effect = [
            _make_route("google", "fast", "fast_proposer", requested_tier="fast"),
            _make_route("anthropic", "fast", "fast_critic", requested_tier="fast"),
        ]
        factory = _make_factory(
            side_effects=[
                {
                    **_canonical_analysis("fast-proposal-only"),
                    "_thothgraph_usage": {
                        "prompt_tokens": 1000,
                        "completion_tokens": 500,
                        "total_tokens": 1500,
                    },
                },
                RuntimeError("Anthropic unavailable"),
            ]
        )

        result = await run_debate(
            ai_factory=factory,
            audit_data=SAMPLE_AUDIT_DATA,
            prompt_context="Fast fallback",
            requested_tier="fast",
        )

        assert len(result.rounds) == 1
        assert result.profile == "fast_3step"
        assert result.pipeline_type == "fast_3step"
        assert result.fallback_reason == "critic_unavailable"
        assert "without challenge" in result.synthesis_reasoning

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_generator_failure_raises(self, mock_resolve):
        mock_resolve.return_value = _make_route("google", "fast", "proposer")
        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(side_effect=RuntimeError("Google down"))

        with pytest.raises((RuntimeError, TimeoutError)):
            await run_debate(
                ai_factory=factory,
                audit_data=SAMPLE_AUDIT_DATA,
                prompt_context="Test",
                requested_tier="deep_judgment",
            )


class TestDebateTimeout:
    @pytest.mark.asyncio
    @patch.dict(
        "services.debate_orchestrator._PIPELINE_CONFIGS",
        {
            "fast": PipelineConfig(
                total_timeout_s=5,
                step_timeout_s=1,
                cost_cap_usd=0.50,
                max_completion_tokens=3_000,
                profile_label="fast_3step",
            )
        },
        clear=False,
    )
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_step_timeout(self, mock_resolve):
        # SIGNAL-1025: run_debate() was called without requested_tier, so it
        # defaulted to "smart" (step_timeout_s=90s in production config)
        # regardless of _make_route's "fast" argument, which only sets the
        # mocked route's execution_tier/tier_class, not the pipeline config
        # actually used. With a 90s step timeout and a 60s mocked sleep, the
        # provider call never actually timed out, it ran to completion and
        # failed downstream schema validation instead (via the smart tier's
        # cascade-retry path, several ~60s rounds, "TimeoutError" only
        # incidentally in the assertion because RuntimeError was also
        # accepted). Passing requested_tier="fast" selects the pipeline that
        # (per _run_fast_pipeline's own comment) propagates a step timeout
        # directly with no cascade retry, and the config override above makes
        # that timeout deterministic and fast instead of depending on
        # production defaults or a real 60s sleep.
        mock_resolve.return_value = _make_route("google", "fast", "proposer", requested_tier="fast")

        async def slow_provider(*_args, **_kwargs):
            await asyncio.sleep(5)
            return {}

        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(side_effect=slow_provider)

        # TimeoutError is a builtin alias of asyncio.TimeoutError on Python
        # 3.11+; both are listed for clarity about which timeout this is
        # asserting on. RuntimeError deliberately excluded: this test is
        # only meaningful if the failure is genuinely the step timeout
        # cancelling the provider call, not some other error swallowed by a
        # broader except clause.
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await run_debate(
                ai_factory=factory,
                audit_data=SAMPLE_AUDIT_DATA,
                prompt_context="Test",
                requested_tier="fast",
            )


class TestPipelineSelector:
    def test_resolve_pipeline_config_returns_v3_targets(self):
        smart = _resolve_pipeline_config("smart")
        deep = _resolve_pipeline_config("deep_judgment")

        assert smart.profile_label == "smart_5step"
        assert smart.total_timeout_s > 0
        assert smart.step_timeout_s > 0
        assert deep.profile_label == "delta_flow"
        assert deep.total_timeout_s >= smart.total_timeout_s
        assert deep.step_timeout_s > 0

    @pytest.mark.asyncio
    async def test_fast_pipeline_profile_is_available(self):
        assert _resolve_pipeline_config("fast").profile_label == "fast_3step"

    @pytest.mark.asyncio
    @patch.dict(
        "services.debate_orchestrator._PIPELINE_CONFIGS",
        {
            "fast": PipelineConfig(
                total_timeout_s=60,
                step_timeout_s=15,
                cost_cap_usd=0.001,
                max_completion_tokens=3_000,
                profile_label="fast_3step",
            )
        },
        clear=False,
    )
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_fast_pipeline_respects_cost_cap(self, mock_resolve):
        mock_resolve.side_effect = [
            _make_route("google", "fast", "fast_proposer", requested_tier="fast"),
        ]
        factory = _make_factory(
            side_effects=[
                {
                    **_canonical_analysis("expensive-fast"),
                    "_thothgraph_usage": {
                        "prompt_tokens": 100000,
                        "completion_tokens": 50000,
                        "total_tokens": 150000,
                    },
                },
            ]
        )

        with pytest.raises(RuntimeError, match="FAST debate cost cap exceeded"):
            await run_debate(
                ai_factory=factory,
                audit_data=SAMPLE_AUDIT_DATA,
                prompt_context="Fast",
                requested_tier="fast",
            )


class TestHelpers:
    def test_aggregate_usage(self):
        rounds = [
            DebateAgentResult(
                role="proposer",
                semantic_role="generator",
                provider="google",
                model="m1",
                output={},
                token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            ),
            DebateAgentResult(
                role="challenger",
                semantic_role="critic",
                provider="anthropic",
                model="m2",
                output={},
                token_usage={"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            ),
        ]
        total = _aggregate_usage(rounds)
        assert total == {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}

    def test_estimate_step_cost_fast(self):
        with patch(
            "services.debate_orchestrator.get_token_pricing_for_model",
            return_value={"input": 1, "output": 2},
        ):
            cost = _estimate_step_cost(
                "proposer",
                {"prompt_tokens": 10000, "completion_tokens": 5000},
            )
        assert cost == pytest.approx(0.02, rel=0.01)

    def test_estimate_step_cost_smart(self):
        with patch(
            "services.debate_orchestrator.get_token_pricing_for_model",
            return_value={"input": 0.5, "output": 1.5},
        ):
            cost = _estimate_step_cost(
                "challenger",
                {"prompt_tokens": 8000, "completion_tokens": 4000},
            )
        assert cost == pytest.approx(0.01, rel=0.01)

    def test_build_proposer_prompt_returns_system_and_user(self):
        system, user = _build_proposer_prompt({"key": "val"}, "context")
        assert "Proposer" in system
        assert isinstance(user, list)

    def test_build_fast_proposer_prompt_returns_system_and_user(self):
        system, user = _build_fast_proposer_prompt({"key": "val"}, "context")
        assert "FAST multi-agent" in system
        assert "Orchestrator Context" in system
        assert isinstance(user, list)

    def test_build_seo_generator_prompt_returns_system_and_user(self):
        system, user = _build_seo_generator_prompt({"key": "val"}, "context")
        assert "SMART Orchestra V3" in system
        assert "Orchestrator Context" in system
        assert isinstance(user, list)

    def test_build_deep_seo_generator_prompt_returns_system_and_user(self):
        system, user = _build_deep_seo_generator_prompt({"key": "val"}, "context")
        assert "DEEP_JUDGMENT Delta Flow" in system
        assert "Orchestrator Context" in system
        assert isinstance(user, list)

    def test_build_aeo_geo_generator_prompt_returns_system_and_user(self):
        system, user = _build_aeo_geo_generator_prompt({"key": "val"}, "context")
        assert "SMART Orchestra V3" in system
        assert isinstance(user, list)

    def test_build_geo_generator_prompt_returns_system_and_user(self):
        system, user = _build_geo_generator_prompt({"key": "val"}, "context")
        assert "DEEP_JUDGMENT Delta Flow" in system
        assert isinstance(user, list)

    def test_build_aeo_generator_prompt_returns_system_and_user(self):
        system, user = _build_aeo_generator_prompt({"key": "val"}, "context")
        assert "DEEP_JUDGMENT Delta Flow" in system
        assert isinstance(user, list)

    def test_build_fast_critic_prompt_contains_transfer_packet(self):
        system, user = _build_fast_critic_prompt(
            {"key": "val"},
            {
                **_canonical_analysis("proposal"),
                "recommendations": ["Add FAQ schema"],
            },
        )
        assert "FAST multi-agent" in system
        assert "Transfer Packet" in user[0]
        assert "claim_ledger" in user[0]

    def test_build_centralized_critic_prompt_contains_both_transfer_packets(self):
        system, user = _build_centralized_critic_prompt(
            {"key": "val"},
            seo_proposal=_seo_expert_output("seo"),
            aeo_geo_proposal=_aeo_geo_expert_output("aeo-geo"),
        )
        assert "centralized critic" in system.lower()
        assert "SEO Transfer Packet" in user[0]
        assert "AEO+GEO Transfer Packet" in user[0]
        assert "claim_ledger" in user[0]

    def test_build_delta_critics_only_receive_own_domain_packets(self):
        seo_system, seo_user = _build_seo_critic_prompt({"key": "val"}, _seo_expert_output("seo"))
        geo_system, geo_user = _build_geo_critic_prompt({"key": "val"}, _geo_expert_output("geo"))
        aeo_system, aeo_user = _build_aeo_critic_prompt({"key": "val"}, _aeo_expert_output("aeo"))
        assert "SEO Critic" in seo_system
        assert "## SEO Transfer Packet:" in seo_user[0]
        assert "## GEO Transfer Packet:" in geo_user[0]
        assert "## AEO Transfer Packet:" in aeo_user[0]
        assert "Faceted URLs are wasting crawl budget." in seo_user[0]
        assert "Brand authority is inconsistent across local citations." in geo_user[0]
        assert "Transactional pages are missing concise answer blocks." in aeo_user[0]

    def test_build_fast_synthesizer_prompt_contains_both_packets(self):
        system, user = _build_fast_synthesizer_prompt(
            {"key": "val"},
            {
                **_canonical_analysis("proposal"),
                "recommendations": ["Add FAQ schema"],
            },
            {
                "challenges": [
                    {
                        "target_claim": "Schema is complete",
                        "counter_argument": "Missing FAQ schema",
                        "severity": "moderate",
                    }
                ],
                "missed_items": [],
                "disagreements": [],
                "confidence_delta": -0.1,
            },
            "ctx",
        )
        assert "FAST multi-agent" in system
        assert "Transfer Packet" in user[0]
        assert "Review Packet" in user[0]

    def test_build_smart_synthesizer_prompt_contains_all_packets(self):
        system, user = _build_smart_synthesizer_prompt(
            {"key": "val"},
            seo_proposal=_seo_expert_output("seo"),
            aeo_geo_proposal=_aeo_geo_expert_output("aeo-geo"),
            critique=_strict_critic_output(),
            prompt_context="ctx",
        )
        assert "SEO Transfer Packet" in user[0]
        assert "AEO+GEO Transfer Packet" in user[0]
        assert "Centralized Critique Packet" in user[0]

    def test_build_magistrate_prompt_contains_synthesis_packet(self):
        system, user = _build_magistrate_prompt(
            {"key": "val"},
            synthesis_packet={
                **_canonical_analysis("smart-synthesis"),
                "synthesis_reasoning": "Prepared final packet for magistrate.",
                "debate_confidence_score": 0.79,
            },
            critique=_strict_critic_output(),
            prompt_context="ctx",
        )
        assert "magistrate" in system.lower()
        assert "Synthesis Packet" in user[0]
        assert "Centralized Critique Packet" in user[0]

    def test_build_consolidator_prompt_contains_generator_and_critique_packets(self):
        system, user = _build_consolidator_prompt(
            {"key": "val"},
            generator_packets={
                "seo": {"claim_ledger": [{"claim_id": "seo-01"}]},
                "geo": {"claim_ledger": [{"claim_id": "geo-01"}]},
                "aeo": {"claim_ledger": [{"claim_id": "aeo-01"}]},
            },
            critique_packets={
                "seo": {"challenge_ledger": [{"target_claim": "seo-01"}]},
                "geo": {"challenge_ledger": [{"target_claim": "geo-01"}]},
                "aeo": {"challenge_ledger": [{"target_claim": "aeo-01"}]},
            },
            prompt_context="ctx",
        )
        assert "Consolidator" in system
        assert "Generator Transfer Packets" in user[0]
        assert "Critique Packets" in user[0]

    def test_build_global_magistrate_prompt_contains_consolidated_packet(self):
        system, user = _build_global_magistrate_prompt(
            {"key": "val"},
            generator_packets={"seo": {"claim_ledger": [{"claim_id": "seo-01"}]}},
            consolidated_packet=_consolidated_output(),
            critique_packets=None,
            prompt_context="ctx",
        )
        assert "Global Magistrate" in system
        assert "Generator Transfer Packets" in user[0]
        assert "Consolidated Packet" in user[0]

    def test_build_challenger_prompt_contains_proposal(self):
        system, user = _build_challenger_prompt(
            {"key": "val"},
            {
                **_canonical_analysis("proposal"),
                "recommendations": ["Add FAQ schema"],
                "seo_findings": [
                    {
                        "description": "Critical crawl issue on parameter pages.",
                        "severity": "critical",
                        "category": "indexing",
                    }
                ],
            },
        )
        assert "Challenger" in system
        assert "Transfer Packet" in user[0]
        assert "Add FAQ schema" in user[0]

    def test_build_synthesizer_prompt_contains_both(self):
        system, user = _build_synthesizer_prompt(
            {"key": "val"},
            {
                **_canonical_analysis("proposal"),
                "recommendations": ["Add FAQ schema"],
            },
            {
                "challenges": [
                    {
                        "target_claim": "Schema is complete",
                        "counter_argument": "Missing FAQ schema",
                        "severity": "moderate",
                    }
                ],
                "missed_items": [],
                "disagreements": [],
                "confidence_delta": -0.1,
            },
            "ctx",
        )
        assert "Synthesizer" in system
        assert "Transfer Packet" in user[0]
        assert "Review Packet" in user[0]


# ---------------------------------------------------------------------------
# Shadow Mode A/B tests
# ---------------------------------------------------------------------------


class TestShadowMode:
    """Tests for pipeline version selection and shadow comparison extraction."""

    def test_select_pipeline_runner_v3_returns_named_functions(self):
        from services.debate_orchestrator import _select_pipeline_runner

        fast = _select_pipeline_runner(version="v3", normalized_tier="fast")
        smart = _select_pipeline_runner(version="v3", normalized_tier="smart")
        deep = _select_pipeline_runner(version="v3", normalized_tier="deep_judgment")
        assert fast.__name__ == "_run_fast_pipeline"
        assert smart.__name__ == "_run_smart_pipeline"
        assert deep.__name__ == "_run_delta_flow_pipeline"

    def test_select_pipeline_runner_v2_returns_wrapper(self):
        from services.debate_orchestrator import _select_pipeline_runner

        wrapper = _select_pipeline_runner(version="v2", normalized_tier="smart")
        assert wrapper.__name__ == "_v2_wrapper"

    def test_select_pipeline_runner_v3_unknown_tier_raises(self):
        from services.debate_orchestrator import _select_pipeline_runner

        with pytest.raises(ValueError, match="No V3 pipeline"):
            _select_pipeline_runner(version="v3", normalized_tier="unknown_tier")


# ---------------------------------------------------------------------------
# Safe JSON truncation and empty generator output tests
# ---------------------------------------------------------------------------


class TestSafeJsonSection:
    """Tests for _safe_json_section — safe JSON truncation without mid-token breaks."""

    def test_returns_full_json_when_under_budget(self):
        from services.debate_orchestrator import _safe_json_section

        payload = {"key": "value", "num": 42}
        result = _safe_json_section(payload, 1000)
        assert result == '{"key": "value", "num": 42}'

    def test_truncates_dict_by_dropping_low_priority_keys(self):
        from services.debate_orchestrator import _safe_json_section

        payload = {
            "synthesis_reasoning": "important",
            "debate_confidence_score": 0.85,
            "market_dominance_projection": "x" * 5000,
            "neural_intelligence_grid": [{"a": 1}] * 50,
        }
        result = _safe_json_section(payload, 200)
        assert len(result) <= 200
        # High-priority keys should be retained
        assert "synthesis_reasoning" in result
        assert "debate_confidence_score" in result

    def test_fallback_slicing_preserves_json_boundary(self):
        from services.debate_orchestrator import _safe_json_section

        # An array payload that can't be pruned by key-dropping
        payload = ["x" * 100 for _ in range(20)]
        result = _safe_json_section(payload, 150)
        assert len(result) <= 200  # allows truncation marker
        assert "...[truncated]" in result

    def test_small_budget_still_produces_output(self):
        from services.debate_orchestrator import _safe_json_section

        result = _safe_json_section({"a": 1}, 5)
        assert len(result) > 0


class TestEmptyGeneratorOutputs:
    """Tests for _empty_seo_generator_output and _empty_aeo_geo_generator_output."""

    def test_seo_output_has_required_keys(self):
        from services.debate_orchestrator import _empty_seo_generator_output

        output = _empty_seo_generator_output()
        assert "claim_ledger" in output
        assert "seo_findings" in output
        assert "technical_signals" in output
        assert output["technical_signals"]["mobile_friendliness"] == 0
        assert output["technical_signals"]["security_score"] == 0

    def test_aeo_geo_output_has_required_keys(self):
        from services.debate_orchestrator import _empty_aeo_geo_generator_output

        output = _empty_aeo_geo_generator_output()
        for key in [
            "claim_ledger",
            "summary",
            "recommendations",
            "geo_findings",
            "geo_signals",
            "entity_analysis",
            "aeo_findings",
            "aeo_signals",
            "citation_probability_score",
        ]:
            assert key in output, f"Missing key: {key}"
        assert output["geo_signals"]["citation_consistency_score"] == 0
        assert output["aeo_signals"]["answerability_score"] == 0


class TestBuildSynthesisTransferPacket:
    """Tests for _build_synthesis_transfer_packet — compact magistrate input."""

    def test_extracts_core_fields(self):
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        full_output = {
            "synthesis_reasoning": "Reconciled SEO and GEO signals.",
            "debate_confidence_score": 0.82,
            "schema_version": "3.2",
            "overall_score": 75,
            "seo_score": 80,
            "geo_score": 70,
            "aeo_score": 65,
            "technical_signals": {"mobile_friendliness": 0.9, "security_score": 0.8},
            "geo_signals": {"citation_consistency_score": 0.7, "local_authority_score": 0.6},
            "aeo_signals": {"answerability_score": 0.5, "voice_readiness_score": 0.4},
            "entity_analysis": {"entity_clarity_score": 0.6, "brand_trust_score": 0.7},
            "executive_dossier": "Executive summary text" * 100,
            "summary": "Short summary",
            "seo_findings": [{"f": i} for i in range(20)],
            "recommendations": ["r1", "r2", "r3"],
            "neural_intelligence_grid": [{"g": i} for i in range(30)],
            "market_dominance_projection": "Projection" * 500,
        }
        packet = _build_synthesis_transfer_packet(full_output)

        # Core fields preserved
        assert packet["synthesis_reasoning"] == "Reconciled SEO and GEO signals."
        assert packet["debate_confidence_score"] == 0.82
        assert packet["overall_score"] == 75

        # Findings capped at 6
        assert len(packet["seo_findings"]) == 6
        assert len(packet["recommendations"]) == 3  # only 3 recs

        # Long narratives capped at 800 chars
        assert len(packet["executive_dossier"]) <= 800

        # Low-priority fields NOT in the packet
        assert "neural_intelligence_grid" not in packet
        assert "market_dominance_projection" not in packet

    def test_handles_empty_output(self):
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        packet = _build_synthesis_transfer_packet({})
        assert isinstance(packet, dict)
        assert len(packet) == 0


# ---------------------------------------------------------------------------
# Cascade fallback tests
# ---------------------------------------------------------------------------


class TestCascadeFallback:
    """Tests for _run_agent_step_with_cascade — provider cascade on failure."""

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator._emit_debate_event", new_callable=AsyncMock)
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_retries_on_provider_error(self, mock_resolve, mock_emit):
        """First provider fails, cascade re-resolves and succeeds on second."""
        google_route = _make_route("google", "smart", "centralized_critic")
        anthropic_route = _make_route("anthropic", "smart", "centralized_critic")
        mock_resolve.return_value = anthropic_route

        call_count = 0

        async def _fake_generate(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Provider google returned 500")
            return {
                **_canonical_analysis("cascade ok"),
                "_thothgraph_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            }

        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(side_effect=_fake_generate)

        result = await _run_agent_step_with_cascade(
            ai_factory=factory,
            rounds=[],
            role="centralized_critic",
            system_prompt="sys",
            user_prompt=["user"],
            schema=None,
            required_keys=("summary",),
            requested_tier="smart",
            step_timeout_s=10,
            on_event=mock_emit,
            route_override=google_route,
            layer_index=2,
        )
        assert result.provider == "anthropic"
        assert result.cascade_waste_cost_usd > 0
        assert call_count == 2
        # Verify SSE retry event was emitted
        retry_calls = [
            c
            for c in mock_emit.call_args_list
            if len(c.args) >= 2
            and c.args[1] == "debate_step_started"
            and c.kwargs.get("cascade_retry") is True
        ]
        assert len(retry_calls) >= 1

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator._emit_debate_event", new_callable=AsyncMock)
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_does_not_retry_timeout(self, mock_resolve, mock_emit):
        """Timeouts should propagate immediately, not trigger cascade."""
        route = _make_route("google", "smart", "centralized_critic")

        async def _slow_provider(*_args, **_kwargs):
            raise asyncio.TimeoutError("step timed out")

        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(side_effect=_slow_provider)

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await _run_agent_step_with_cascade(
                ai_factory=factory,
                rounds=[],
                role="centralized_critic",
                system_prompt="sys",
                user_prompt=["user"],
                schema=None,
                required_keys=("summary",),
                requested_tier="smart",
                step_timeout_s=10,
                route_override=route,
                layer_index=2,
            )
        # Should have been called exactly once — no retry
        assert factory._generate_with_provider.call_count == 1

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator._emit_debate_event", new_callable=AsyncMock)
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_exhaustion_reraises(self, mock_resolve, mock_emit):
        """When all providers are exhausted, last exception is re-raised."""
        # resolve_debate_route always returns the same provider — so excluded
        # set will never find a non-excluded provider, triggering exhaustion.
        mock_resolve.return_value = _make_route("google", "smart", "centralized_critic")

        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(side_effect=RuntimeError("all providers down"))

        with pytest.raises(RuntimeError, match="all providers down"):
            await _run_agent_step_with_cascade(
                ai_factory=factory,
                rounds=[],
                role="centralized_critic",
                system_prompt="sys",
                user_prompt=["user"],
                schema=None,
                required_keys=("summary",),
                requested_tier="smart",
                step_timeout_s=10,
                route_override=_make_route("google", "smart", "centralized_critic"),
                layer_index=2,
            )

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator._emit_debate_event", new_callable=AsyncMock)
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_exclude_provider_cleared_on_retry(self, mock_resolve, mock_emit):
        """On retries, exclude_provider is passed as None (not stale original)."""
        google_route = _make_route("google", "smart", "seo_generator")
        openai_route = _make_route("openai", "smart", "seo_generator")
        mock_resolve.return_value = openai_route

        call_count = 0
        captured_kwargs = []

        original_run_agent_step = _run_agent_step

        async def _tracking_run_agent_step(**kwargs):
            nonlocal call_count
            call_count += 1
            captured_kwargs.append(kwargs.get("exclude_provider"))
            if call_count == 1:
                raise RuntimeError("google 429")
            return await original_run_agent_step(**kwargs)

        factory = _make_factory()
        factory._generate_with_provider = AsyncMock(
            return_value={
                **_canonical_analysis("ok"),
                "_thothgraph_usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 50,
                    "total_tokens": 150,
                },
            }
        )

        with patch(
            "services.debate_orchestrator._run_agent_step", side_effect=_tracking_run_agent_step
        ):
            await _run_agent_step_with_cascade(
                ai_factory=factory,
                rounds=[],
                role="seo_generator",
                system_prompt="sys",
                user_prompt=["user"],
                schema=None,
                required_keys=("summary",),
                requested_tier="smart",
                step_timeout_s=10,
                exclude_provider="anthropic",
                route_override=google_route,
                layer_index=1,
            )
        # First call: original exclude_provider="anthropic"
        assert captured_kwargs[0] == "anthropic"
        # Second call (retry): exclude_provider=None
        assert captured_kwargs[1] is None


# ---------------------------------------------------------------------------
# Layer 1 partial failure tests
# ---------------------------------------------------------------------------


class TestLayer1PartialFailure:
    """Test that one generator failing produces partial results instead of crash."""

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_routes_for_layer")
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_seo_generator_fails_pipeline_continues(self, mock_resolve, mock_resolve_layer):
        """SEO generator fails (after cascade exhaustion) -> empty SEO output used -> pipeline continues."""
        seo_route = _make_route("google", "smart", "seo_generator")
        aeo_geo_route = _make_route("anthropic", "smart", "aeo_geo_generator")
        mock_resolve_layer.return_value = {
            "seo_generator": seo_route,
            "aeo_geo_generator": aeo_geo_route,
        }
        mock_resolve.return_value = _make_route("openai", "smart", "centralized_critic")

        # Mock at _run_agent_step level so we can distinguish by role
        _aeo_geo_output = {
            **_canonical_analysis("aeo_geo ok"),
            "claim_ledger": [{"claim": "c1", "evidence": "e1", "confidence": 0.9}],
            "citation_probability_score": 0.65,
        }
        _synthesizer_output = {
            **_canonical_analysis("synthesized"),
            "synthesis_reasoning": "Reconciled partial data.",
            "debate_confidence_score": 0.75,
            "claim_ledger": [],
        }
        _critic_output = {
            "unsupported_claims": [],
            "invented_links_or_citations": [],
            "weak_recommendations": [],
            "missed_items": [],
            "unresolved_questions": [],
            "confidence_delta": 0.0,
            "_thothgraph_usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
        }
        _magistrate_output = {
            **_canonical_analysis("final"),
            "synthesis_reasoning": "Verdict issued.",
            "debate_confidence_score": 0.80,
            "judge_summary": {
                "accepted_claims": 1,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "unresolved_disputes": 0,
            },
            "claim_ledger": [],
        }

        async def _role_aware_step(**kwargs):
            role = kwargs["role"]
            if role == "seo_generator":
                raise RuntimeError("SEO generator all providers exhausted")
            output_map = {
                "aeo_geo_generator": _aeo_geo_output,
                "centralized_critic": _critic_output,
                "smart_synthesizer": _synthesizer_output,
                "magistrate": _magistrate_output,
            }
            output = output_map.get(role, _synthesizer_output)
            return DebateAgentResult(
                role=role,
                semantic_role="generator" if "generator" in role else "critic",
                provider=kwargs.get("route_override", _make_route("openai", "smart", role)).provider
                if kwargs.get("route_override")
                else "openai",
                model="mock-model",
                output=output,
                token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
                latency_ms=100.0,
                route_resolution=kwargs.get("route_override"),
                step_cost_usd=0.01,
                layer_index=kwargs.get("layer_index"),
            )

        with patch("services.debate_orchestrator._run_agent_step", side_effect=_role_aware_step):
            result = await run_debate(
                ai_factory=_make_factory(),
                audit_data=SAMPLE_AUDIT_DATA,
                prompt_context="Test partial failure",
                requested_tier="smart",
            )

        assert result is not None
        assert len(result.rounds) >= 2
        # The SEO generator round should be the fallback with provider="none"
        seo_round = next((r for r in result.rounds if r.role == "seo_generator"), None)
        assert seo_round is not None
        assert seo_round.provider == "none"
        assert seo_round.model == "fallback"
        assert seo_round.output["seo_findings"] == []


# ---------------------------------------------------------------------------
# Autocalibration: safe JSON round-trip property tests
# ---------------------------------------------------------------------------


class TestSafeJsonAutocalibration:
    """Property-based autocalibration tests for _safe_json_section.

    These tests verify that truncated output is always consumable
    (valid JSON or ends with truncation marker) across a variety of
    payload shapes and budget pressures.
    """

    def test_all_priority_keys_survive_at_generous_budget(self):
        """With enough budget, all priority keys from a realistic payload survive."""
        from services.debate_orchestrator import _safe_json_section, _SYNTHESIS_PRIORITY_KEYS

        payload = {}
        for key in _SYNTHESIS_PRIORITY_KEYS:
            payload[key] = f"value_{key}"
        result = _safe_json_section(payload, 50000)
        assert result == json.dumps(payload, default=str)
        for key in _SYNTHESIS_PRIORITY_KEYS:
            assert key in result

    def test_high_priority_keys_survive_extreme_pressure(self):
        """Under extreme budget pressure, the highest-priority keys survive."""
        from services.debate_orchestrator import _safe_json_section

        payload = {
            "synthesis_reasoning": "important",
            "debate_confidence_score": 0.9,
            "schema_version": "3.2",
            "seo_findings": [{"f": i, "detail": "x" * 200} for i in range(50)],
            "geo_findings": [{"f": i, "detail": "x" * 200} for i in range(50)],
            "aeo_findings": [{"f": i, "detail": "x" * 200} for i in range(50)],
            "recommendations": ["r" * 300 for _ in range(20)],
            "neural_intelligence_grid": [{"g": i} for i in range(100)],
            "market_dominance_projection": "P" * 10000,
            "strategic_roadmap": "R" * 5000,
        }
        result = _safe_json_section(payload, 300)
        assert len(result) <= 300
        # The top 3 keys should survive: synthesis_reasoning, debate_confidence_score, schema_version
        parsed = json.loads(result)
        assert "synthesis_reasoning" in parsed
        assert "debate_confidence_score" in parsed

    def test_truncated_output_is_parseable_or_marked(self):
        """For array payloads (can't drop keys), result is either valid JSON or has marker."""
        from services.debate_orchestrator import _safe_json_section

        for size in [50, 100, 200, 500, 1000]:
            payload = [{"item": i, "data": "x" * 50} for i in range(30)]
            result = _safe_json_section(payload, size)
            try:
                json.loads(result)
            except json.JSONDecodeError:
                assert (
                    "...[truncated]" in result
                ), f"At budget={size}, result is neither valid JSON nor truncation-marked: {result[:80]}"

    def test_round_trip_for_various_dict_budgets(self):
        """Dict payloads always produce valid JSON at any budget (keys get dropped)."""
        from services.debate_orchestrator import _safe_json_section

        payload = {
            "synthesis_reasoning": "test",
            "debate_confidence_score": 0.5,
            "overall_score": 75,
            "seo_findings": [{"f": i} for i in range(100)],
            "neural_intelligence_grid": list(range(200)),
        }
        for budget in [20, 50, 100, 200, 500, 1000, 5000]:
            result = _safe_json_section(payload, budget)
            # Dict key-dropping should always produce valid JSON
            try:
                parsed = json.loads(result)
                assert isinstance(parsed, dict)
            except json.JSONDecodeError:
                # Fallback slicing may kick in if even {} exceeds budget
                assert "...[truncated]" in result or budget < 5

    def test_empty_payloads(self):
        """Edge cases: empty dict, empty list, None, numbers."""
        from services.debate_orchestrator import _safe_json_section

        assert _safe_json_section({}, 100) == "{}"
        assert _safe_json_section([], 100) == "[]"
        assert _safe_json_section(None, 100) == "null"
        assert _safe_json_section(42, 100) == "42"


# ---------------------------------------------------------------------------
# Autocalibration: synthesis transfer packet size budget tests
# ---------------------------------------------------------------------------


class TestSynthesisTransferPacketAutocalibration:
    """Fuzz-style tests verifying _build_synthesis_transfer_packet always
    produces compact output that fits within the magistrate's char budget
    and preserves all scoring fields.
    """

    def _make_rich_synthesis(self, *, findings_count=50, narrative_length=3000) -> dict:
        """Build a realistically large synthesizer output."""
        return {
            "synthesis_reasoning": "R" * narrative_length,
            "debate_confidence_score": 0.88,
            "schema_version": "3.2",
            "overall_score": 78,
            "seo_score": 82,
            "geo_score": 71,
            "aeo_score": 69,
            "citation_probability_score": 0.65,
            "technical_signals": {"mobile_friendliness": 0.9, "security_score": 0.85},
            "geo_signals": {"citation_consistency_score": 0.72, "local_authority_score": 0.68},
            "aeo_signals": {"answerability_score": 0.55, "voice_readiness_score": 0.48},
            "entity_analysis": {"entity_clarity_score": 0.7, "brand_trust_score": 0.65},
            "executive_dossier": "E" * narrative_length,
            "summary": "S" * narrative_length,
            "strategic_roadmap": "SR" * narrative_length,
            "seo_findings": [
                {"title": f"SEO finding {i}", "detail": "d" * 200, "severity": "warning"}
                for i in range(findings_count)
            ],
            "geo_findings": [
                {"title": f"GEO finding {i}", "detail": "d" * 200} for i in range(findings_count)
            ],
            "aeo_findings": [
                {"title": f"AEO finding {i}", "detail": "d" * 200} for i in range(findings_count)
            ],
            "findings": [{"title": f"General {i}"} for i in range(findings_count)],
            "recommendations": [f"Rec {i}: {'x' * 100}" for i in range(findings_count)],
            "claim_ledger": [{"claim": f"Claim {i}", "evidence": "e" * 100} for i in range(30)],
            "neural_intelligence_grid": [{"g": i, "data": "x" * 500} for i in range(50)],
            "market_dominance_projection": "M" * 10000,
        }

    def test_packet_fits_within_magistrate_budget(self):
        """Transfer packet + _safe_json_section should always fit in 10000 chars."""
        from services.debate_orchestrator import (
            _build_synthesis_transfer_packet,
            _safe_json_section,
        )

        synthesis = self._make_rich_synthesis(findings_count=100, narrative_length=5000)
        packet = _build_synthesis_transfer_packet(synthesis)
        serialized = _safe_json_section(packet, 10000)
        assert len(serialized) <= 10000

    def test_scoring_fields_always_preserved(self):
        """All numeric scoring fields must survive the transfer packet."""
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        for findings_count in [0, 5, 50, 200]:
            synthesis = self._make_rich_synthesis(findings_count=findings_count)
            packet = _build_synthesis_transfer_packet(synthesis)
            for score_key in (
                "overall_score",
                "seo_score",
                "geo_score",
                "aeo_score",
                "citation_probability_score",
                "debate_confidence_score",
            ):
                assert score_key in packet, f"Missing {score_key} with {findings_count} findings"

    def test_signal_objects_always_preserved(self):
        """Signal sub-objects must survive regardless of payload size."""
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        synthesis = self._make_rich_synthesis(findings_count=200, narrative_length=10000)
        packet = _build_synthesis_transfer_packet(synthesis)
        for signal_key in ("technical_signals", "geo_signals", "aeo_signals", "entity_analysis"):
            assert signal_key in packet, f"Missing {signal_key}"
            assert isinstance(packet[signal_key], dict)

    def test_findings_capped_and_low_priority_excluded(self):
        """Findings arrays are capped; neural_intelligence_grid and market_dominance_projection excluded."""
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        synthesis = self._make_rich_synthesis(findings_count=100)
        packet = _build_synthesis_transfer_packet(synthesis)
        for findings_key in ("seo_findings", "geo_findings", "aeo_findings"):
            assert len(packet[findings_key]) <= 6
        assert len(packet["claim_ledger"]) <= 12
        assert "neural_intelligence_grid" not in packet
        assert "market_dominance_projection" not in packet

    def test_narratives_capped_at_800_chars(self):
        """Long narrative fields are capped at 800 characters."""
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        synthesis = self._make_rich_synthesis(narrative_length=5000)
        packet = _build_synthesis_transfer_packet(synthesis)
        for narrative_key in ("executive_dossier", "summary", "strategic_roadmap"):
            assert len(packet[narrative_key]) <= 800

    def test_packet_compression_ratio(self):
        """Transfer packet should be meaningfully smaller than the full output."""
        from services.debate_orchestrator import _build_synthesis_transfer_packet

        synthesis = self._make_rich_synthesis(findings_count=100, narrative_length=5000)
        full_size = len(json.dumps(synthesis, default=str))
        packet = _build_synthesis_transfer_packet(synthesis)
        packet_size = len(json.dumps(packet, default=str))
        # The packet should be at most 30% of the full output for large payloads
        ratio = packet_size / full_size
        assert ratio < 0.30, f"Compression ratio {ratio:.2%} is too high (want <30%)"


# ---------------------------------------------------------------------------
# Provider cascade retry tests
# ---------------------------------------------------------------------------


class TestCascadeRetry:
    """Tests for _run_agent_step_with_cascade — provider fallback on failure."""

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_retries_on_provider_error(self, mock_resolve):
        """First provider fails with RuntimeError → cascade retries with next provider."""
        mock_resolve.return_value = _make_route("openai", "smart", "seo_generator")
        factory = _make_factory(
            side_effects=[
                RuntimeError("google 429 rate limited"),
                _seo_expert_output("seo-via-openai"),
            ]
        )

        result = await _run_agent_step_with_cascade(
            ai_factory=factory,
            rounds=[],
            role="seo_generator",
            system_prompt="test",
            user_prompt=["test"],
            schema=None,
            required_keys=("seo_findings",),
            requested_tier="smart",
            step_timeout_s=30,
            route_override=_make_route("google", "smart", "seo_generator"),
        )

        assert result.output["seo_findings"] is not None
        assert factory._generate_with_provider.call_count == 2

    @pytest.mark.asyncio
    async def test_cascade_does_not_retry_on_timeout(self):
        """TimeoutError must propagate immediately — no cascade retry."""
        factory = _make_factory(side_effects=[asyncio.TimeoutError("step budget exceeded")])

        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            await _run_agent_step_with_cascade(
                ai_factory=factory,
                rounds=[],
                role="seo_generator",
                system_prompt="test",
                user_prompt=["test"],
                schema=None,
                required_keys=("seo_findings",),
                requested_tier="smart",
                step_timeout_s=30,
                route_override=_make_route("google", "smart", "seo_generator"),
            )

        assert factory._generate_with_provider.call_count == 1

    @pytest.mark.asyncio
    @patch("services.debate_orchestrator.resolve_debate_route")
    async def test_cascade_exhausted_raises_last_exception(self, mock_resolve):
        """All cascade attempts fail → the last exception is re-raised."""
        mock_resolve.return_value = _make_route("google", "smart", "seo_generator")
        factory = _make_factory(
            side_effects=[
                RuntimeError("google down"),
                RuntimeError("openai down"),
                RuntimeError("anthropic down"),
            ]
        )

        with pytest.raises(RuntimeError, match="down"):
            await _run_agent_step_with_cascade(
                ai_factory=factory,
                rounds=[],
                role="seo_generator",
                system_prompt="test",
                user_prompt=["test"],
                schema=None,
                required_keys=("seo_findings",),
                requested_tier="smart",
                step_timeout_s=30,
                route_override=_make_route("google", "smart", "seo_generator"),
            )


@pytest.mark.asyncio
@patch("services.debate_orchestrator.resolve_debate_route")
async def test_cascade_relaxes_preference_exclusion_as_last_resort(mock_resolve):
    """When a step excludes a provider only as a *preference* (e.g. critic
    wants a different provider than the generator) and every other provider
    fails, the cascade must fall back to the excluded provider instead of
    degrading the audit."""
    factory = _make_factory()
    calls: list[str] = []

    async def _fake_generate(
        provider, model_name, system_prompt, user_prompt, schema=None, *, temperature=None
    ):
        del model_name, system_prompt, user_prompt, schema, temperature
        calls.append(provider)
        if provider in ("openai", "anthropic"):
            raise ValueError(f"{provider} credit balance too low")
        return {
            "summary": "ok",
            "_thothgraph_usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    factory._generate_with_provider = AsyncMock(side_effect=_fake_generate)

    def _resolve(role, requested_tier=None, exclude_provider=None, preferred_provider=None):
        if preferred_provider == "google":
            return _make_route("google", "smart", role)
        if exclude_provider == "openai":
            return _make_route("anthropic", "smart", role)
        if exclude_provider == "anthropic":
            return _make_route("openai", "smart", role)
        return _make_route("openai", "smart", role)

    mock_resolve.side_effect = _resolve

    rounds: list[DebateAgentResult] = []
    result = await _run_agent_step_with_cascade(
        ai_factory=factory,
        rounds=rounds,
        role="centralized_critic",
        system_prompt="sys",
        user_prompt=["payload"],
        schema={"required": ["summary"]},
        required_keys=("summary",),
        requested_tier="smart",
        step_timeout_s=5,
        exclude_provider="google",
    )

    # Fell back to the (credited) excluded provider instead of raising.
    assert result.provider == "google"
    assert "google" in calls
    # The other providers were attempted first before relaxing the preference.
    assert "openai" in calls
    assert "anthropic" in calls
