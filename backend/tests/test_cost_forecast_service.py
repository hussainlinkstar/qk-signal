from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models  # noqa: E402
from database import Base  # noqa: E402
from services.cost_forecast_service import (  # noqa: E402
    analyze_serp_complexity,
    calculate_actual_audit_cost,
    forecast_audit_cost,
    get_calibration_factor,
)
from services.ai_routing_policy import provider_runtime_state_service  # noqa: E402


def _build_db() -> tuple[Session, object]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing_session(), engine


def _cleanup(db: Session, engine: object) -> None:
    db.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _mock_provider_runtime_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        provider_runtime_state_service,
        "get_status",
        lambda _provider: SimpleNamespace(configured=True, available=True, state="available"),
    )


def test_analyze_serp_complexity_scores_rich_serp_features() -> None:
    signal = analyze_serp_complexity(
        [
            {
                "items": [
                    {
                        "type": "organic",
                        "title": "Result 1",
                        "description": "x" * 650,
                    },
                    {
                        "type": "featured_snippet",
                        "title": "Snippet",
                        "description": "x" * 700,
                    },
                    {
                        "type": "people_also_ask",
                        "title": "What is GEO?",
                        "description": "Answer preview",
                    },
                    {
                        "type": "knowledge_panel",
                        "title": "Knowledge panel",
                    },
                ]
            }
        ]
    )

    assert signal.keyword_count == 1
    assert signal.total_organic_results >= 1
    assert signal.featured_snippet_present is True
    assert signal.paa_question_count >= 1
    assert signal.knowledge_panel_present is True
    assert signal.avg_serp_item_content_length > 0
    assert signal.serp_density_score > 0.5


def test_forecast_audit_cost_returns_dynamic_breakdown_for_deep_tier() -> None:
    forecast = forecast_audit_cost(
        audit_data={
            "content": "# Pricing page\n" + ("Deep audit content. " * 400),
            "title": "Dynamic pricing audit",
            "meta_description": "Forecast the real audit cost.",
            "structured_data": {"@type": "WebPage"},
        },
        dataforseo_results=[
            {
                "items": [
                    {"type": "organic", "title": "Forecast 1", "description": "x" * 500},
                    {"type": "featured_snippet", "title": "Snippet", "description": "x" * 550},
                    {"type": "people_also_ask", "title": "How much will it cost?"},
                ]
            }
        ],
        tier_class="deep",
        policy_version="v3",
        entities_count=3,
        category="finance",
        market="Romania",
    )

    assert forecast.estimated_credits >= 1
    assert float(forecast.estimated_total_cogs_usd) > 0
    assert forecast.breakdown["forecast_mode"] == "standard"
    assert forecast.breakdown["tier_class"] == "deep"
    assert len(forecast.breakdown["steps"]) == 3


def test_forecast_audit_cost_scales_multi_model_consensus_runs() -> None:
    baseline = forecast_audit_cost(
        audit_data={"content": "Consensus audit " * 250, "title": "Consensus"},
        dataforseo_results=None,
        tier_class="deep",
        policy_version="v3",
        entities_count=2,
        category="saas",
        market="US",
    )
    consensus = forecast_audit_cost(
        audit_data={"content": "Consensus audit " * 250, "title": "Consensus"},
        dataforseo_results=None,
        tier_class="deep",
        policy_version="v3",
        entities_count=2,
        category="saas",
        market="US",
        selected_models=["openai", "anthropic"],
    )

    assert consensus.breakdown["forecast_mode"] == "multi_model_consensus"
    assert consensus.breakdown["selected_models"] == ["openai", "anthropic"]
    assert len(consensus.breakdown["steps"]) == 3
    assert float(consensus.estimated_total_cogs_usd) > float(baseline.estimated_total_cogs_usd)


def test_forecast_audit_cost_uses_explicit_provider_route() -> None:
    forecast = forecast_audit_cost(
        audit_data={"content": "Provider override " * 160, "title": "Provider override"},
        dataforseo_results=None,
        tier_class="fast",
        policy_version="v3",
        provider="openai",
        category="saas",
        market="US",
    )

    # CUTOVER stage 1: reasoning routes unconditionally to bedrock, so the
    # explicit openai override collapses to the bedrock provider.
    assert forecast.breakdown["resolved_provider"] == "bedrock"
    assert forecast.breakdown["resolved_execution_tier"] == "fast"
    assert forecast.breakdown["steps"][0]["provider"] == "bedrock"


def test_forecast_audit_cost_uses_high_confidence_debate_routes_for_deep_judgment() -> None:
    forecast = forecast_audit_cost(
        audit_data={"content": "High confidence audit " * 320, "title": "High Confidence"},
        dataforseo_results=None,
        tier_class="deep",
        requested_tier="deep_judgment",
        policy_version="v3",
        entities_count=3,
        category="finance",
        market="US",
    )

    assert forecast.breakdown["requested_tier"] == "deep_judgment"
    assert forecast.breakdown["debate_profile"] == "high_confidence"
    assert forecast.breakdown["calibration_scope"] == "requested_tier"
    assert [step["role"] for step in forecast.breakdown["steps"]] == [
        "generator",
        "critic",
        "judge",
    ]
    # CUTOVER stage 1: every debate role collapses to bedrock; the per-role
    # execution tiers are still preserved (generator=fast, critic/judge=smart).
    assert [step["provider"] for step in forecast.breakdown["steps"]] == [
        "bedrock",
        "bedrock",
        "bedrock",
    ]
    assert [step["execution_tier"] for step in forecast.breakdown["steps"]] == [
        "fast",
        "smart",
        "smart",
    ]


def test_get_calibration_factor_uses_recent_ledger_rows() -> None:
    db, engine = _build_db()
    try:
        db.add_all(
            [
                models.AIEconomicsLedgerEntry(
                    policy_version="v3",
                    feature_key="audit.main",
                    tier_class="deep",
                    provider="google",
                    model="gemini-2.5-pro",
                    real_cost_usd=Decimal("1.20"),
                    credit_unit_value_usd=Decimal("0.10"),
                    implied_revenue_usd=Decimal("0.10"),
                    margin_usd=Decimal("0"),
                    payload_json={"estimated_total_cogs_usd": 1.0},
                ),
                models.AIEconomicsLedgerEntry(
                    policy_version="v3",
                    feature_key="audit.main",
                    tier_class="deep",
                    provider="google",
                    model="gemini-2.5-pro",
                    real_cost_usd=Decimal("2.40"),
                    credit_unit_value_usd=Decimal("0.10"),
                    implied_revenue_usd=Decimal("0.10"),
                    margin_usd=Decimal("0"),
                    payload_json={"estimated_total_cogs_usd": 2.0},
                ),
            ]
        )
        db.commit()

        factor, sample_size = get_calibration_factor(
            db,
            feature_key="audit.main",
            tier_class="deep",
        )

        assert sample_size == 2
        assert float(factor) == pytest.approx(1.2, rel=0.01)
    finally:
        _cleanup(db, engine)


def test_get_calibration_factor_segments_high_confidence_rows() -> None:
    db, engine = _build_db()
    try:
        db.add_all(
            [
                models.AIEconomicsLedgerEntry(
                    policy_version="v3",
                    feature_key="audit.main",
                    tier_class="deep",
                    provider="anthropic",
                    model="claude-opus-4-6",
                    real_cost_usd=Decimal("1.20"),
                    credit_unit_value_usd=Decimal("0.10"),
                    implied_revenue_usd=Decimal("0.10"),
                    margin_usd=Decimal("0"),
                    payload_json={"estimated_total_cogs_usd": 1.0, "requested_tier": "smart"},
                ),
                models.AIEconomicsLedgerEntry(
                    policy_version="v3",
                    feature_key="audit.main",
                    tier_class="deep",
                    provider="anthropic",
                    model="claude-opus-4-6",
                    real_cost_usd=Decimal("1.50"),
                    credit_unit_value_usd=Decimal("0.10"),
                    implied_revenue_usd=Decimal("0.10"),
                    margin_usd=Decimal("0"),
                    payload_json={
                        "estimated_total_cogs_usd": 1.0,
                        "requested_tier": "deep_judgment",
                        "debate_profile": "high_confidence",
                    },
                ),
            ]
        )
        db.commit()

        factor, sample_size = get_calibration_factor(
            db,
            feature_key="audit.main",
            tier_class="deep",
            requested_tier="deep_judgment",
        )

        assert sample_size == 1
        assert float(factor) == pytest.approx(1.5, rel=0.01)
    finally:
        _cleanup(db, engine)


def test_calculate_actual_audit_cost_aggregates_debate_transcript() -> None:
    actual = calculate_actual_audit_cost(
        report={
            "metadata": {
                "ai_generation": {
                    "mode": "debate",
                    "provider": "multi-provider",
                    "model": "multi-agent",
                    "transcript": [
                        {
                            "role": "proposer",
                            "provider": "google",
                            "model": "gemini-2.5-flash",
                            "token_usage": {
                                "prompt_tokens": 1500,
                                "completion_tokens": 600,
                                "total_tokens": 2100,
                            },
                        },
                        {
                            "role": "synthesizer",
                            "provider": "anthropic",
                            "model": "claude-opus-4-6",
                            "token_usage": {
                                "prompt_tokens": 1800,
                                "completion_tokens": 900,
                                "total_tokens": 2700,
                            },
                        },
                    ],
                }
            }
        },
        policy_version="v3",
    )

    assert actual.usage_mode == "debate"
    assert actual.step_count == 2
    assert actual.input_tokens == 3300
    assert actual.output_tokens == 1500
    assert actual.token_cost_usd == Decimal("0.033450")
    assert float(actual.token_cost_usd) > 0
    assert float(actual.total_cogs_usd) >= float(actual.token_cost_usd)


def test_calculate_actual_audit_cost_preserves_specialist_synthesis_mode() -> None:
    actual = calculate_actual_audit_cost(
        report={
            "metadata": {
                "ai_generation": {
                    "mode": "specialist_synthesis",
                    "provider": "multi-provider",
                    "model": "multi-agent",
                    "transcript": [
                        {
                            "role": "seo_expert",
                            "provider": "anthropic",
                            "model": "claude-opus-4-6",
                            "token_usage": {
                                "prompt_tokens": 1200,
                                "completion_tokens": 400,
                                "total_tokens": 1600,
                            },
                        },
                        {
                            "role": "synthesizer",
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "token_usage": {
                                "prompt_tokens": 900,
                                "completion_tokens": 200,
                                "total_tokens": 1100,
                            },
                        },
                    ],
                }
            }
        },
        policy_version="v3",
    )

    assert actual.usage_mode == "specialist_synthesis"
    assert actual.step_count == 2
    assert actual.input_tokens == 2100
    assert actual.output_tokens == 600


def test_calculate_actual_audit_cost_includes_post_processing_transcript_for_single_call() -> None:
    actual = calculate_actual_audit_cost(
        report={
            "metadata": {
                "ai_generation": {
                    "mode": "single",
                    "provider": "google",
                    "model": "gemini-2.5-pro",
                    "usage": {
                        "prompt_tokens": 2000,
                        "completion_tokens": 500,
                        "total_tokens": 2500,
                    },
                    "post_processing_transcript": [
                        {
                            "role": "suggestion_detail",
                            "semantic_role": "post_processing",
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "operation": "generate_suggestion_detail",
                            "token_usage": {
                                "prompt_tokens": 150,
                                "completion_tokens": 50,
                                "total_tokens": 200,
                            },
                            "execution_tier": "fast",
                        },
                        {
                            "role": "suggestion_detail",
                            "semantic_role": "post_processing",
                            "provider": "openai",
                            "model": "gpt-5.4-mini",
                            "operation": "generate_suggestion_detail",
                            "token_usage": {
                                "prompt_tokens": 120,
                                "completion_tokens": 40,
                                "total_tokens": 160,
                            },
                            "execution_tier": "fast",
                        },
                    ],
                }
            }
        },
        policy_version="v3",
    )

    assert actual.usage_mode == "single"
    assert actual.step_count == 3
    assert actual.input_tokens == 2270
    assert actual.output_tokens == 590
    assert actual.breakdown["steps"][0]["pipeline_stage"] == "generation"
    assert actual.breakdown["steps"][1]["pipeline_stage"] == "post_processing"
    assert actual.breakdown["steps"][1]["operation"] == "generate_suggestion_detail"


def test_calculate_actual_audit_cost_supports_top_level_ai_generation_payloads() -> None:
    actual = calculate_actual_audit_cost(
        report={
            "requested_tier": "deep_judgment",
            "ai_generation": {
                "mode": "debate",
                "provider": "anthropic",
                "model": "claude-opus-4-6",
                "transcript": [
                    {
                        "role": "judge",
                        "provider": "anthropic",
                        "model": "claude-4-6-opus",
                        "token_usage": {
                            "prompt_tokens": 1000,
                            "completion_tokens": 500,
                            "total_tokens": 1500,
                        },
                    }
                ],
            },
        },
        policy_version="v3",
    )

    assert actual.breakdown["requested_tier"] == "deep_judgment"
    assert actual.token_cost_usd == Decimal("0.017500")
    assert actual.breakdown["steps"][0]["model"] == "claude-4-6-opus"
