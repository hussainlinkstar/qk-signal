import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.audit_credit_reconciliation_service import (
    resolve_audit_credit_resolution,
    resolve_shadow_audit_credit_cost,
)
from services.cost_forecast_service import calculate_actual_audit_cost
from services.pricing_policy_service import calculate_credits_from_real_cost


def test_resolve_audit_credit_resolution_uses_report_provider_and_tier_when_available() -> None:
    resolution = resolve_audit_credit_resolution(
        full_report={
            "metadata": {
                "provider": "openai",
                "tier": "smart",
            }
        },
        estimated_credit_cost=2,
        default_provider="google",
        default_tier="smart",
        entities_count=0,
    )

    assert resolution.billed_provider == "openai"
    assert resolution.billed_tier == "smart"
    assert resolution.billable_credit_cost == 6
    assert resolution.cost_changed is True
    assert resolution.provider_changed is True


def test_resolve_audit_credit_resolution_falls_back_to_default_when_metadata_missing() -> None:
    resolution = resolve_audit_credit_resolution(
        full_report={"metadata": {}},
        estimated_credit_cost=3,
        default_provider="anthropic",
        default_tier="smart",
    )

    assert resolution.billed_provider == "anthropic"
    assert resolution.billed_tier == "smart"
    assert resolution.billable_credit_cost == 5
    assert resolution.cost_changed is True
    assert resolution.provider_changed is False


def test_resolve_audit_credit_resolution_uses_actual_debate_transcript_cost() -> None:
    full_report = {
        "metadata": {
            "provider": "google",
            "tier": "smart",
            "ai_generation": {
                "mode": "debate",
                "transcript": [
                    {
                        "role": "proposer",
                        "provider": "google",
                        "model": "gemini-2.5-flash",
                        "token_usage": {
                            "prompt_tokens": 5000,
                            "completion_tokens": 1000,
                            "total_tokens": 6000,
                        },
                    },
                    {
                        "role": "challenger",
                        "provider": "anthropic",
                        "model": "claude-opus-4-6",
                        "token_usage": {
                            "prompt_tokens": 6500,
                            "completion_tokens": 1200,
                            "total_tokens": 7700,
                        },
                    },
                    {
                        "role": "synthesizer",
                        "provider": "google",
                        "model": "gemini-2.5-pro",
                        "token_usage": {
                            "prompt_tokens": 7000,
                            "completion_tokens": 1500,
                            "total_tokens": 8500,
                        },
                    },
                ],
            },
        }
    }

    actual_cost = calculate_actual_audit_cost(
        report=full_report,
        policy_version=None,
        feature_key="audit.main",
    )
    expected_credits, _ = calculate_credits_from_real_cost(
        real_cost_usd=actual_cost.total_cogs_usd,
        policy_version=None,
        feature_key="audit.main",
        tier_class="deep",
        billable=True,
    )

    resolution = resolve_audit_credit_resolution(
        full_report=full_report,
        estimated_credit_cost=9,
        default_provider="google",
        default_tier="smart",
        policy_version=None,
        entities_count=3,
        category="seo",
        market="us",
    )

    assert resolution.billed_provider == "google"
    assert resolution.billed_tier == "smart"
    assert resolution.billable_credit_cost == expected_credits
    assert resolution.cost_changed is True
    assert resolution.resolution_reason == "debate_actual_usage_cost"


def test_resolve_audit_credit_resolution_uses_specialist_synthesis_transcript_cost() -> None:
    full_report = {
        "metadata": {
            "provider": "anthropic",
            "tier": "smart",
            "ai_generation": {
                "mode": "specialist_synthesis",
                "transcript": [
                    {
                        "role": "seo_expert",
                        "provider": "anthropic",
                        "model": "claude-opus-4-6",
                        "token_usage": {
                            "prompt_tokens": 5000,
                            "completion_tokens": 1000,
                            "total_tokens": 6000,
                        },
                    },
                    {
                        "role": "synthesizer",
                        "provider": "openai",
                        "model": "gpt-5.4-mini",
                        "token_usage": {
                            "prompt_tokens": 3500,
                            "completion_tokens": 700,
                            "total_tokens": 4200,
                        },
                    },
                ],
            },
        }
    }

    actual_cost = calculate_actual_audit_cost(
        report=full_report,
        policy_version=None,
        feature_key="audit.main",
    )
    expected_credits, _ = calculate_credits_from_real_cost(
        real_cost_usd=actual_cost.total_cogs_usd,
        policy_version=None,
        feature_key="audit.main",
        tier_class="deep",
        billable=True,
    )

    resolution = resolve_audit_credit_resolution(
        full_report=full_report,
        estimated_credit_cost=5,
        default_provider="anthropic",
        default_tier="smart",
        policy_version=None,
        entities_count=2,
        category="seo",
        market="us",
    )

    assert resolution.billable_credit_cost == expected_credits
    assert resolution.resolution_reason == "debate_actual_usage_cost"


def test_resolve_audit_credit_resolution_uses_selected_models_for_multi_model_runs() -> None:
    resolution = resolve_audit_credit_resolution(
        full_report={
            "metadata": {
                "provider": "openai",
                "tier": "smart",
                "selected_models": ["openai", "anthropic"],
            }
        },
        estimated_credit_cost=9,
        default_provider="openai",
        default_tier="smart",
        policy_version=None,
        entities_count=2,
        category="saas",
        market="us",
    )

    assert resolution.billed_provider == "openai"
    assert resolution.billed_tier == "smart"
    assert resolution.billable_credit_cost > 6
    assert resolution.resolution_reason == "multi_model_selected_models"


def test_resolve_shadow_audit_credit_cost_uses_actual_high_confidence_usage() -> None:
    full_report = {
        "metadata": {
            "tier": "deep_judgment",
            "requested_tier": "deep_judgment",
            "ai_generation": {
                "mode": "debate",
                "profile": "high_confidence",
                "transcript": [
                    {
                        "role": "proposer",
                        "semantic_role": "generator",
                        "provider": "anthropic",
                        "model": "claude-haiku-4-5",
                        "execution_tier": "fast",
                        "token_usage": {
                            "prompt_tokens": 4800,
                            "completion_tokens": 1200,
                            "total_tokens": 6000,
                        },
                    },
                    {
                        "role": "challenger",
                        "semantic_role": "critic",
                        "provider": "openai",
                        "model": "gpt-5.4",
                        "execution_tier": "smart",
                        "token_usage": {
                            "prompt_tokens": 7200,
                            "completion_tokens": 1400,
                            "total_tokens": 8600,
                        },
                    },
                    {
                        "role": "synthesizer",
                        "semantic_role": "judge",
                        "provider": "anthropic",
                        "model": "claude-opus-4-6",
                        "execution_tier": "smart",
                        "token_usage": {
                            "prompt_tokens": 7600,
                            "completion_tokens": 1600,
                            "total_tokens": 9200,
                        },
                    },
                ],
            },
        }
    }

    actual_cost = calculate_actual_audit_cost(
        report=full_report,
        policy_version="v3",
        feature_key="audit.main",
    )
    expected_credits, _ = calculate_credits_from_real_cost(
        real_cost_usd=actual_cost.total_cogs_usd,
        policy_version="v3",
        feature_key="audit.main",
        tier_class="deep",
        billable=True,
    )

    shadow_credits = resolve_shadow_audit_credit_cost(
        full_report=full_report,
        policy_version="v3",
        billed_provider="anthropic",
        billed_tier="deep_judgment",
    )

    assert shadow_credits == expected_credits
