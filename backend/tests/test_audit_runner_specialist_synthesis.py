import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from audit_runner import _append_track_b_transcript_entries, _build_ai_generation_metadata


def test_build_ai_generation_metadata_supports_specialist_synthesis_mode() -> None:
    metadata = _build_ai_generation_metadata(
        provider_used="anthropic",
        model_name="claude-opus-4-6",
        ai_analysis_results={},
        debate_metadata={
            "enabled": True,
            "mode": "specialist_synthesis",
            "provider": "multi-provider",
            "model": "multi-agent",
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 40,
                "total_tokens": 140,
            },
            "transcript": [
                {
                    "role": "seo_expert",
                    "provider": "anthropic",
                    "model": "claude-opus-4-6",
                    "output_summary": "SEO specialist output",
                    "execution_tier": "smart",
                    "token_usage": {
                        "prompt_tokens": 30,
                        "completion_tokens": 10,
                        "total_tokens": 40,
                    },
                }
            ],
        },
    )

    assert metadata["mode"] == "specialist_synthesis"
    assert metadata["provider"] == "multi-provider"
    assert metadata["model"] == "multi-agent"
    assert metadata["usage"]["total_tokens"] == 140
    assert metadata["transcript"][0]["role"] == "seo_expert"
    assert metadata["transcript"][0]["output_summary"] == "SEO specialist output"


def test_report_schema_preserves_specialist_synthesis_enabled_flag() -> None:
    from report_schema import AuditReport

    report = AuditReport(
        analysis={"schema_version": "1.0"},
        performance={},
        network={},
        metadata={},
        debate={
            "enabled": True,
            "transcript": [
                {
                    "role": "seo_expert",
                    "provider": "anthropic",
                    "model": "claude-opus-4-6",
                    "output_summary": "SEO specialist output",
                }
            ],
        },
    ).dict()

    assert report["debate"]["enabled"] is True
    assert report["debate"]["transcript"][0]["role"] == "seo_expert"


def test_report_schema_preserves_extended_debate_contract_fields() -> None:
    from report_schema import AuditReport

    report = AuditReport(
        analysis={"schema_version": "1.0"},
        performance={},
        network={},
        metadata={},
        debate={
            "enabled": True,
            "profile": "high_confidence",
            "fallback_reason": "judge_unavailable",
            "judge_authority": "fallback",
            "pipeline_type": "fast_3step",
            "parallel_layers": 0,
            "agent_count": 3,
            "judge_summary": {
                "accepted_claims": 3,
                "downgraded_claims": 1,
                "rejected_claims": 1,
                "unresolved_disputes": 1,
            },
            "per_agent_costs": [
                {
                    "role": "fast_proposer",
                    "semantic_role": "generator",
                    "provider": "google",
                    "model": "gemini-2.5-flash",
                    "execution_tier": "fast",
                    "latency_ms": 12.5,
                    "cost_usd": 0.01,
                    "tokens": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                }
            ],
            "transcript": [],
        },
    ).dict()

    assert report["debate"]["profile"] == "high_confidence"
    assert report["debate"]["fallback_reason"] == "judge_unavailable"
    assert report["debate"]["judge_authority"] == "fallback"
    assert report["debate"]["pipeline_type"] == "fast_3step"
    assert report["debate"]["agent_count"] == 3
    assert report["debate"]["per_agent_costs"][0]["execution_tier"] == "fast"
    assert report["debate"]["judge_summary"]["accepted_claims"] == 3


def test_build_ai_generation_metadata_uses_explicit_single_call_usage_payload() -> None:
    metadata = _build_ai_generation_metadata(
        provider_used="google",
        model_name="gemini-2.5-pro",
        ai_analysis_results={},
        usage_payload={
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "total_tokens": 100,
        },
    )

    assert metadata["mode"] == "single"
    assert metadata["provider"] == "google"
    assert metadata["model"] == "gemini-2.5-pro"
    assert metadata["usage"]["total_tokens"] == 100


def test_append_track_b_transcript_entries_extends_specialist_usage() -> None:
    metadata = {
        "mode": "specialist_synthesis",
        "transcript": [
            {
                "role": "seo_expert",
                "token_usage": {
                    "prompt_tokens": 30,
                    "completion_tokens": 10,
                    "total_tokens": 40,
                },
            }
        ],
        "usage": {
            "prompt_tokens": 30,
            "completion_tokens": 10,
            "total_tokens": 40,
        },
    }

    updated = _append_track_b_transcript_entries(
        metadata,
        {
            "claims": [
                {
                    "claim_id": "rec_001",
                    "track": "track_b",
                    "judge_mode": "llm_shadow",
                    "judge_provider": "anthropic",
                    "judge_model": "claude-opus-4-6",
                    "judge_usage": {
                        "prompt_tokens": 12,
                        "completion_tokens": 6,
                        "total_tokens": 18,
                    },
                    "judge_latency_ms": 22.5,
                },
                {
                    "claim_id": "rec_002",
                    "track": "track_b",
                    "judge_mode": "deterministic_shadow",
                    "judge_provider": "anthropic",
                    "judge_model": "claude-opus-4-6",
                },
            ]
        },
    )

    assert len(updated["transcript"]) == 2
    assert updated["transcript"][1]["role"] == "track_b_judge"
    assert updated["transcript"][1]["claim_id"] == "rec_001"
    assert updated["transcript"][1]["output_summary"] == "Track B judge result for rec_001"
    assert updated["usage"]["total_tokens"] == 58
