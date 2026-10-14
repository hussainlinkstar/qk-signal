from services.audit_job_event_service import (
    normalize_debate_progress_event,
    summarize_debate_output,
)


def test_summarize_debate_output_v3_critics_return_safe_counts():
    """BUG-041: V3 critic roles must return count-based summaries, not raw JSON."""
    v3_critic_output = {
        "unsupported_claims": [
            {
                "target_claim": "Secret claim text",
                "counter_argument": "Secret counter",
                "severity": "critical",
                "issue_type": "unsupported_claim",
                "suggested_disposition": "remove",
            },
        ],
        "invented_links_or_citations": [
            {
                "target_claim": "Fake link",
                "counter_argument": "Not real",
                "severity": "moderate",
                "issue_type": "invented_link_or_citation",
                "suggested_disposition": "remove",
            },
        ],
        "weak_recommendations": [],
        "missed_items": ["item1"],
        "unresolved_questions": ["q1"],
        "confidence_delta": -0.15,
    }

    for role in ("fast_critic", "centralized_critic", "seo_critic", "geo_critic", "aeo_critic"):
        result = summarize_debate_output(role, v3_critic_output)
        assert result is not None, f"{role} returned None"
        assert "1 unsupported claims" in result, f"{role}: expected count summary, got: {result}"
        assert "1 invented citations" in result, f"{role}: expected count summary, got: {result}"
        assert "0 weak recommendations" in result, f"{role}: expected count summary, got: {result}"
        assert "Secret claim text" not in result, f"{role}: leaked claim text in: {result}"
        assert "Secret counter" not in result, f"{role}: leaked counter-argument in: {result}"


def test_summarize_debate_output_legacy_challenger_still_works():
    """Ensure legacy challenger summary is not broken."""
    legacy_output = {
        "challenges": [{"target_claim": "x", "counter_argument": "y", "severity": "critical"}],
        "missed_items": ["a", "b"],
        "disagreements": ["z"],
        "confidence_delta": -0.10,
    }
    result = summarize_debate_output("challenger", legacy_output)
    assert result is not None
    assert "1 challenges" in result
    assert "2 missed items" in result
    assert "1 disagreements" in result


def test_summarize_debate_output_challenger_v3_shape():
    """Challenger with V3 output shape (unsupported_claims) also gets safe summary."""
    v3_shape = {
        "unsupported_claims": [{"target_claim": "x"}],
        "invented_links_or_citations": [],
        "weak_recommendations": [{"target_claim": "y"}],
    }
    result = summarize_debate_output("challenger", v3_shape)
    assert result is not None
    assert "1 unsupported claims" in result
    assert "1 weak recommendations" in result


def test_summarize_debate_output_summary_key_preferred():
    """If output has a 'summary' key, it should be used regardless of role."""
    output = {"summary": "Safe summary text", "unsupported_claims": [{"target_claim": "secret"}]}
    result = summarize_debate_output("seo_critic", output)
    assert result == "Safe summary text"


def test_summarize_debate_output_seo_generator_no_raw_json():
    """Generator outputs must produce human-readable summaries, not raw JSON with claim_ledger."""
    seo_output = {
        "claim_ledger": [
            {"claim_id": "SEO-H1-001", "domain": "seo", "claim_text": "H1 is missing"},
            {"claim_id": "SEO-H1-002", "domain": "seo", "claim_text": "Meta is too long"},
        ],
        "seo_findings": [
            {"title": "Missing H1", "severity": "high"},
            {"title": "Long meta description", "severity": "medium"},
            {"title": "Missing canonical", "severity": "low"},
        ],
        "technical_signals": {"performance_score": 78, "security_score": 90},
    }
    result = summarize_debate_output("seo_generator", seo_output)
    assert result is not None
    assert "claim_ledger" not in result, f"Raw claim_ledger leaked: {result}"
    assert "claim_id" not in result, f"Raw claim_id leaked: {result}"
    assert "SEO-H1-001" not in result, f"Raw claim ID leaked: {result}"
    assert "3 SEO findings" in result
    assert "2 claims verified" in result


def test_summarize_debate_output_geo_generator_no_raw_json():
    """GEO generator should produce readable summary."""
    geo_output = {
        "claim_ledger": [{"claim_id": "GEO-001", "domain": "geo", "claim_text": "NAP data"}],
        "geo_findings": [{"title": "Incomplete NAP", "severity": "high"}],
        "geo_signals": {"local_schema_coverage": 0.3},
        "entity_analysis": {"entities": [{"name": "Acme Inc"}, {"name": "Acme HQ"}]},
    }
    result = summarize_debate_output("geo_generator", geo_output)
    assert result is not None
    assert "claim_ledger" not in result
    assert "1 GEO findings" in result
    assert "1 claims verified" in result
    assert "2 entities" in result


def test_summarize_debate_output_aeo_generator_no_raw_json():
    """AEO generator should produce readable summary."""
    aeo_output = {
        "claim_ledger": [{"claim_id": "AEO-001", "domain": "aeo", "claim_text": "Schema"}],
        "aeo_findings": [{"title": "Missing FAQ schema"}, {"title": "No HowTo markup"}],
        "aeo_signals": {"answerability_score": 65},
        "citation_probability_score": 72,
    }
    result = summarize_debate_output("aeo_generator", aeo_output)
    assert result is not None
    assert "claim_ledger" not in result
    assert "2 AEO findings" in result
    assert "citation probability 72" in result


def test_summarize_debate_output_unknown_role_with_claim_ledger():
    """Even unknown roles should not leak claim_ledger if present in output."""
    output = {
        "claim_ledger": [{"claim_id": "X-001", "domain": "seo"}],
        "seo_findings": [{"title": "Test"}],
    }
    result = summarize_debate_output("some_future_generator", output)
    assert result is not None
    assert "claim_ledger" not in result


def test_summarize_debate_output_fallback_excludes_claim_ledger():
    """Fallback JSON dump must not include claim_ledger even for unknown roles."""
    output = {
        "claim_ledger": [{"claim_id": "X-001"}],
        "some_field": "visible",
    }
    result = summarize_debate_output("unknown_role_without_claim_ledger_match", output)
    # Since "claim_ledger" is in output, the generator path takes over
    assert result is not None
    assert "claim_id" not in result


def test_normalize_debate_progress_event_preserves_v3_pipeline_and_layer_metadata():
    normalized = normalize_debate_progress_event(
        {
            "event": "debate_pipeline_started",
            "pipeline_type": "delta_flow",
            "total_agents": 8,
            "parallel_layers": 2,
            "estimated_duration_s": 480,
            "internal_prompt": "must_not_leak",
        }
    )

    assert normalized == {
        "type": "pipeline_started",
        "occurred_at": normalized["occurred_at"],
        "pipeline_type": "delta_flow",
        "total_agents": 8,
        "parallel_layers": 2,
        "estimated_duration_s": 480,
    }


def test_normalize_debate_progress_event_sanitizes_step_and_completion_payloads():
    normalized_step = normalize_debate_progress_event(
        {
            "event": "debate_step_completed",
            "role": "seo_generator",
            "semantic_role": "generator",
            "provider": "google",
            "model": "gemini-test",
            "pipeline_type": "delta_flow",
            "layer": 1,
            "domain": "seo",
            "summary": "A" * 240,
            "latency_ms": 3210,
            "_prompt": "hidden",
        }
    )
    normalized_complete = normalize_debate_progress_event(
        {
            "event": "debate_complete",
            "pipeline_type": "delta_flow",
            "profile": "delta_flow",
            "judge_authority": "primary",
            "confidence": 0.87,
            "fallback_reason": "timeout_due_to_proxy_disconnect",
            "total_latency_ms": 285000,
            "total_cost_usd": 4.5234567,
        }
    )

    assert normalized_step == {
        "type": "step_completed",
        "occurred_at": normalized_step["occurred_at"],
        "role": "seo_generator",
        "semantic_role": "generator",
        "provider": "google",
        "model": "gemini-test",
        "pipeline_type": "delta_flow",
        "domain": "seo",
        "layer": 1,
        "latency_ms": 3210,
        "status": "completed",
        "summary": f'{"A" * 197}...',
    }
    assert normalized_complete == {
        "type": "debate_finished",
        "occurred_at": normalized_complete["occurred_at"],
        "profile": "delta_flow",
        "judge_authority": "primary",
        "pipeline_type": "delta_flow",
        "total_latency_ms": 285000,
        "confidence_score": 0.87,
        "fallback_reason": "timeout_due_to_proxy_disconnect",
    }
