"""Tests for AEX-13: Enable Track B LLM Judge at Smart Tier.

Covers:
- Fast tier: no LLM judge call (deterministic only)
- Smart tier: LLM judge called on top 10 findings (fast model)
- Deep judgment tier: LLM judge called on all findings (smart model)
- Smart tier judge uses fast-tier model
- Smart tier top-10 claim selection by certainty
- Judge failure → graceful degradation to deterministic
- Shadow result metadata (judge_model_tier, judge_claim_limit)
"""

from __future__ import annotations

import pytest

from services.claim_evaluation_service import (
    ClaimEvaluationService,
    SMART_TIER_JUDGE_CLAIM_LIMIT,
    TRACK_B_DETERMINISTIC_SHADOW_MODE,
    TRACK_B_HYBRID_SHADOW_MODE,
)


# ── Fixtures ──────────────────────────────────────────────────────────


def _base_truth_context() -> dict:
    return {
        "target_profile": {
            "target_name": "Example Project",
            "target_url": "https://example.com",
            "target_metadata": {"target_country": "US", "language": "en"},
            "brand_truth_payload": {},
        },
        "supported_track_a_claims": [
            {
                "claim_id": "claim-a",
                "claim_text": "Missing FAQ schema reduces answer extraction on the homepage.",
                "field_path": "aeo_findings[0].description",
                "reason": "Supported Track A claim retained from grounding validation.",
                "evidence_refs": [],
            }
        ],
        "technical_agent_insights": [
            {
                "source_id": "insight-1",
                "source_label": "Technical insight",
                "source_type": "technical",
                "trust_tier": "T1",
                "insight_text": "Homepage answer extraction is constrained by missing FAQ schema.",
                "evidence_refs": [],
            }
        ],
        "domain_standards": [
            {
                "source_id": "standard-1",
                "category": "aeo",
                "excerpt": "FAQ schema improves answer extraction when the page already contains supported question-answer content.",
            }
        ],
    }


def _make_track_b_claim(claim_id: str, text: str, *, certainty: float = 0.5) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": text,
        "track": "track_b",
        "disposition": "supported",
        "certainty_score": certainty,
        "classification_basis": ["contains_imperative_action"],
        "evidence_refs": [{"source_key": "chunk-1", "excerpt": "Homepage content snippet."}],
    }


def _make_track_a_claim(claim_id: str, text: str) -> dict:
    return {
        "claim_id": claim_id,
        "claim_text": text,
        "track": "track_a",
        "disposition": "supported",
        "classification_basis": ["factual_observation"],
        "evidence_refs": [{"source_key": "chunk-1", "excerpt": "Page content."}],
    }


class _TrackingJudgeAIClient:
    """AI client that records all evaluate_track_b_claim calls."""

    def __init__(self):
        self.calls: list[dict] = []

    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        claim = kwargs["claim"]
        return {
            "judgment": {
                "claim_id": claim["claim_id"],
                "track": "B",
                "verdict": "flagged",
                "confidence_band": "medium",
                "problem_anchor_score": 0.80,
                "action_fit_score": 0.72,
                "site_specificity_score": 0.61,
                "novel_fact_risk_score": 0.15,
                "reason_codes": [],
                "problem_refs": ["claim-a"],
                "evidence_refs": ["chunk-1"],
                "explanation": "Recommendation is generally supported.",
                "judge_resolution": "LLM judge approved with moderate confidence.",
                "suggested_rewrite": "",
            },
            "provider": "google",
            "model": "gemini-2.5-flash",
        }


class _FailingJudgeAIClient:
    """AI client where evaluate_track_b_claim always raises."""

    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        raise RuntimeError("LLM judge quota exceeded")


class _NoJudgeClient:
    """AI client without evaluate_track_b_claim method."""

    pass


# ── Tests ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fast_tier_no_llm_judge():
    """Fast tier should NOT invoke LLM judge at all."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="fast",
        requested_tier="fast",
    )

    assert result is not None
    assert len(client.calls) == 0, "Fast tier should not make LLM judge calls"
    assert result["track_b_judge"]["enabled"] is False
    assert result["track_b_judge"]["available"] is False
    assert result["track_b_judge"]["mode"] == TRACK_B_DETERMINISTIC_SHADOW_MODE


@pytest.mark.asyncio
async def test_smart_tier_enables_llm_judge():
    """Smart tier should enable the LLM judge."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert result["track_b_judge"]["enabled"] is True
    assert result["track_b_judge"]["available"] is True
    assert result["track_b_judge"]["llm_evaluated_claims"] >= 1


@pytest.mark.asyncio
async def test_smart_tier_uses_fast_model():
    """Smart tier judge should use 'fast' tier model (not 'smart')."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert len(client.calls) >= 1
    for call in client.calls:
        assert (
            call["tier"] == "fast"
        ), f"Smart tier should pass tier='fast' to judge, got '{call['tier']}'"

    assert result["track_b_judge"]["judge_model_tier"] == "fast"


@pytest.mark.asyncio
async def test_deep_judgment_uses_smart_model():
    """Deep judgment tier judge should use 'deep_judgment' tier for model selection."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="deep_judgment",
    )

    assert len(client.calls) >= 1
    for call in client.calls:
        assert call["tier"] == "deep_judgment"

    assert result["track_b_judge"]["judge_model_tier"] == "deep_judgment"


@pytest.mark.asyncio
async def test_smart_tier_top_10_selection():
    """Smart tier should LLM-judge at most SMART_TIER_JUDGE_CLAIM_LIMIT claims."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    claims = [
        _make_track_b_claim(f"c-{i}", f"Recommendation number {i}.", certainty=i * 0.05)
        for i in range(1, 16)  # 15 Track B claims
    ]

    result = await service.evaluate_shadow_async(
        claim_verifications=claims,
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert len(client.calls) == SMART_TIER_JUDGE_CLAIM_LIMIT
    assert result["track_b_judge"]["judge_claim_limit"] == SMART_TIER_JUDGE_CLAIM_LIMIT


@pytest.mark.asyncio
async def test_smart_tier_selects_lowest_certainty_claims():
    """Smart tier should LLM-judge claims with the lowest deterministic certainty."""
    client = _TrackingJudgeAIClient()
    ClaimEvaluationService()

    claims = [
        _make_track_b_claim("high-cert", "Well-grounded recommendation.", certainty=0.9),
        _make_track_b_claim("low-cert", "Poorly-grounded recommendation.", certainty=0.1),
        _make_track_b_claim("mid-cert", "Moderate recommendation.", certainty=0.5),
    ]

    service_with_limit_2 = ClaimEvaluationService()

    result = await service_with_limit_2.evaluate_shadow_async(
        claim_verifications=claims,
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    [c.get("claim_id") for c in client.calls if "claim" in c]
    [c["claim"]["claim_id"] for c in client.calls]
    assert len(client.calls) == 3  # all 3 < limit of 10


@pytest.mark.asyncio
async def test_deep_judgment_evaluates_all_claims():
    """Deep judgment tier should evaluate ALL Track B claims with LLM."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    claims = [
        _make_track_b_claim(f"c-{i}", f"Recommendation {i}.")
        for i in range(1, 16)  # 15 claims
    ]

    result = await service.evaluate_shadow_async(
        claim_verifications=claims,
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="deep_judgment",
    )

    assert result is not None
    assert len(client.calls) == 15, "Deep judgment should evaluate ALL claims"
    assert result["track_b_judge"]["judge_claim_limit"] == 0


@pytest.mark.asyncio
async def test_smart_tier_hybrid_mode_when_limit_exceeded():
    """With >10 Track B claims, smart tier should produce hybrid_shadow mode."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    claims = [
        _make_track_b_claim(f"c-{i}", f"Recommendation {i}.")
        for i in range(1, 16)  # 15 claims, only 10 get LLM
    ]

    result = await service.evaluate_shadow_async(
        claim_verifications=claims,
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert result["track_b_judge"]["mode"] == TRACK_B_HYBRID_SHADOW_MODE
    assert result["track_b_judge"]["llm_evaluated_claims"] == SMART_TIER_JUDGE_CLAIM_LIMIT
    assert result["track_b_judge"]["deterministic_fallback_claims"] == 5


@pytest.mark.asyncio
async def test_smart_tier_judge_failure_graceful_degradation():
    """When LLM judge fails, smart tier should fall back to deterministic."""
    client = _FailingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert result["track_b_judge"]["enabled"] is True
    claim = result["claims"][0]
    assert claim["judge_mode"] in (
        TRACK_B_DETERMINISTIC_SHADOW_MODE,
        "judge_unavailable",
    )


@pytest.mark.asyncio
async def test_smart_tier_no_judge_method():
    """Smart tier with client lacking evaluate_track_b_claim stays deterministic."""
    client = _NoJudgeClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert result["track_b_judge"]["enabled"] is True
    assert result["track_b_judge"]["available"] is False
    assert result["track_b_judge"]["mode"] == TRACK_B_DETERMINISTIC_SHADOW_MODE


@pytest.mark.asyncio
async def test_smart_tier_track_a_not_llm_judged():
    """Track A claims should never be sent to the LLM judge."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_a_claim("c-a", "The page is missing FAQ schema."),
            _make_track_b_claim("c-b", "Add FAQ schema to the homepage."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    judge_claim_ids = [c["claim"]["claim_id"] for c in client.calls]
    assert "c-a" not in judge_claim_ids
    assert len(client.calls) >= 1


@pytest.mark.asyncio
async def test_shadow_result_metadata_fields():
    """Shadow result should include judge_model_tier and judge_claim_limit."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            _make_track_b_claim("c-1", "Add FAQ schema."),
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    judge = result["track_b_judge"]
    assert "judge_model_tier" in judge
    assert "judge_claim_limit" in judge
    assert judge["judge_model_tier"] == "fast"
    assert judge["judge_claim_limit"] == SMART_TIER_JUDGE_CLAIM_LIMIT
    assert judge["requested_tier"] == "smart"


@pytest.mark.asyncio
async def test_smart_tier_fewer_than_limit_all_judged():
    """When Track B claims < limit, all should be LLM-judged."""
    client = _TrackingJudgeAIClient()
    service = ClaimEvaluationService()

    claims = [
        _make_track_b_claim(f"c-{i}", f"Recommendation {i}.")
        for i in range(1, 4)  # only 3 claims
    ]

    result = await service.evaluate_shadow_async(
        claim_verifications=claims,
        unified_truth_context=_base_truth_context(),
        ai_client=client,
        provider="google",
        tier="smart",
        requested_tier="smart",
    )

    assert result is not None
    assert len(client.calls) == 3
    assert result["track_b_judge"]["llm_evaluated_claims"] == 3
    assert result["track_b_judge"]["deterministic_fallback_claims"] == 0


def test_smart_tier_judge_claim_limit_constant():
    """SMART_TIER_JUDGE_CLAIM_LIMIT should be 10."""
    assert SMART_TIER_JUDGE_CLAIM_LIMIT == 10
