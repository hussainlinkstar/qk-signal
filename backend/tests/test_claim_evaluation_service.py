import pytest

from services.claim_evaluation_service import ClaimEvaluationService


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


def test_claim_evaluation_service_supports_problem_linked_track_b_recommendation() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-1",
                "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
                "certainty_score": 0.82,
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["evaluation_mode"] == "prescriptive_derivation_review"
    assert shadow_claim["shadow_disposition"] == "supported"
    assert shadow_claim["reason_codes"] == []
    assert shadow_claim["problem_anchor_score"] >= 0.75
    assert shadow_claim["novel_fact_risk_score"] <= 0.25
    assert shadow_claim["judge_mode"] == "deterministic_shadow"
    assert result["track_b_judge"]["mode"] == "deterministic_shadow"


def test_claim_evaluation_service_omits_generic_track_b_recommendation() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-2",
                "claim_text": "Improve your content strategy.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
                "certainty_score": 0.61,
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "omitted"
    assert "generic_advice" in shadow_claim["reason_codes"]
    assert "no_supported_problem" in shadow_claim["reason_codes"]


def test_claim_evaluation_service_rewrites_overconcrete_location_claim() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-3",
                "claim_text": 'Add "Romania Wedding Planning" to the H1.',
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": [
                    "contains_imperative_action",
                    "contains_unsupported_concrete_token",
                ],
                "certainty_score": 0.58,
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "omitted"
    assert "invented_site_fact" in shadow_claim["reason_codes"]
    assert "unsupported_location" in shadow_claim["reason_codes"]
    assert "needs_narrower_wording" in shadow_claim["reason_codes"]
    assert shadow_claim["suggested_rewrite"] == (
        "Add an explicit local-market modifier to the H1 that matches the supported target market."
    )


def test_claim_evaluation_service_atomizes_mixed_claims_in_shadow_mode() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-mixed",
                "claim_text": "Because the business has a Paris branch, create a Paris FAQ page.",
                "track": "mixed",
                "disposition": "supported",
                "classification_basis": [
                    "mixed_fact_and_prescription",
                    "contains_imperative_action",
                    "contains_unsupported_concrete_token",
                ],
                "evidence_refs": [
                    {
                        "source_key": "chunk-1",
                        "excerpt": "The homepage focuses on wedding planning FAQs and local answer extraction.",
                    }
                ],
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    assert result["atomization"]["mixed_source_claims"] == 1
    assert result["atomization"]["split_claims_created"] == 2
    assert result["summary"]["track_a_claims"] == 1
    assert result["summary"]["track_b_claims"] == 1

    premise_claim = result["claims"][0]
    recommendation_claim = result["claims"][1]

    assert premise_claim["claim_id"] == "claim-mixed-a"
    assert premise_claim["source_claim_id"] == "claim-mixed"
    assert premise_claim["source_track"] == "mixed"
    assert premise_claim["atomization_role"] == "premise"
    assert premise_claim["track"] == "track_a"
    assert premise_claim["shadow_disposition"] == "omitted"

    assert recommendation_claim["claim_id"] == "claim-mixed-b"
    assert recommendation_claim["source_claim_id"] == "claim-mixed"
    assert recommendation_claim["source_track"] == "mixed"
    assert recommendation_claim["atomization_role"] == "recommendation"
    assert recommendation_claim["track"] == "track_b"
    assert recommendation_claim["premise_refs"] == ["claim-mixed-a"]
    assert recommendation_claim["shadow_disposition"] == "omitted"
    assert "unsupported_premise_ref" in recommendation_claim["reason_codes"]
    assert "unsupported_location" in recommendation_claim["reason_codes"]


class _TrackBJudgeAIClient:
    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        claim = kwargs["claim"]
        return {
            "judgment": {
                "claim_id": claim["claim_id"],
                "track": "B",
                "verdict": "flagged",
                "confidence_band": "medium",
                "problem_anchor_score": 0.88,
                "action_fit_score": 0.78,
                "site_specificity_score": 0.59,
                "novel_fact_risk_score": 0.18,
                "reason_codes": ["needs_narrower_wording"],
                "problem_refs": ["claim-a"],
                "evidence_refs": ["chunk-1"],
                "explanation": "Recommendation is relevant but slightly too concrete.",
                "judge_resolution": "Recommendation can remain with caution, but should be tightened before publication.",
                "suggested_rewrite": "Narrow the modifier to the supported target market.",
            },
            "provider": "openai",
            "model": "gpt-5.4",
        }


class _FailingTrackBJudgeAIClient:
    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        raise RuntimeError("judge unavailable")


class _ContestedTrackBJudgeAIClient:
    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        claim = kwargs["claim"]
        return {
            "judgment": {
                "claim_id": claim["claim_id"],
                "track": "B",
                "verdict": "supported",
                "confidence_band": "contested",
                "problem_anchor_score": 0.92,
                "action_fit_score": 0.88,
                "site_specificity_score": 0.82,
                "novel_fact_risk_score": 0.12,
                "reason_codes": ["needs_narrower_wording"],
                "problem_refs": ["claim-a"],
                "evidence_refs": ["chunk-1"],
                "explanation": "Recommendation is plausible, but the evidence remains contested.",
                "judge_resolution": "Signal weak or partially contradictory; manual verification required.",
                "suggested_rewrite": "Keep the recommendation scoped to the supported target market.",
            },
            "provider": "openai",
            "model": "gpt-5.4",
        }


@pytest.mark.asyncio
async def test_claim_evaluation_service_async_uses_llm_track_b_judge_for_deep_judgment() -> None:
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            {
                "claim_id": "claim-llm",
                "claim_text": "Add a local-market modifier to the homepage H1 to improve answer extraction.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
                "evidence_refs": [
                    {"source_key": "chunk-1", "excerpt": "Homepage content snippet."}
                ],
            }
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=_TrackBJudgeAIClient(),
        provider="openai",
        tier="smart",
        requested_tier="deep_judgment",
    )

    assert result is not None
    assert result["track_b_judge"]["enabled"] is True
    assert result["track_b_judge"]["available"] is True
    assert result["track_b_judge"]["mode"] == "llm_shadow"
    shadow_claim = result["claims"][0]
    assert shadow_claim["judge_mode"] == "llm_shadow"
    assert shadow_claim["judge_provider"] == "openai"
    assert shadow_claim["judge_model"] == "gpt-5.4"
    assert shadow_claim["shadow_disposition"] == "flagged"
    assert shadow_claim["confidence_band"] == "medium"
    assert shadow_claim["problem_refs"] == ["claim-a"]
    assert shadow_claim["evidence_refs"] == ["chunk-1"]
    assert shadow_claim["explanation"] == "Recommendation is relevant but slightly too concrete."
    assert (
        shadow_claim["judge_resolution"]
        == "Recommendation can remain with caution, but should be tightened before publication."
    )


def test_claim_evaluation_service_marks_track_b_claim_for_manual_review_when_debate_remains_unresolved() -> (
    None
):
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-review",
                "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
                "certainty_score": 0.82,
            }
        ],
        unified_truth_context=_base_truth_context(),
        debate_metadata={
            "debate_confidence_score": 0.52,
            "judge_summary": {
                "accepted_claims": 2,
                "downgraded_claims": 1,
                "rejected_claims": 0,
                "unresolved_disputes": 1,
            },
        },
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "needs_manual_review"
    assert shadow_claim["confidence_band"] == "contested"
    assert (
        shadow_claim["judge_resolution"]
        == "Signal weak or partially contradictory; manual verification required."
    )
    assert result["summary"]["needs_manual_review_claims"] == 1
    assert result["track_b_judge"]["needs_manual_review_claims"] == 1


@pytest.mark.asyncio
async def test_claim_evaluation_service_async_safe_fails_when_track_b_judge_errors() -> None:
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            {
                "claim_id": "claim-fail",
                "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
            }
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=_FailingTrackBJudgeAIClient(),
        provider="openai",
        tier="smart",
        requested_tier="deep_judgment",
    )

    assert result is not None
    assert result["track_b_judge"]["mode"] == "deterministic_shadow"
    assert result["track_b_judge"]["judge_unavailable_claims"] == 1
    shadow_claim = result["claims"][0]
    assert shadow_claim["judge_mode"] == "judge_unavailable"
    assert shadow_claim["shadow_disposition"] == "omitted"
    assert shadow_claim["reason_codes"] == ["track_b_judge_unavailable"]


@pytest.mark.asyncio
async def test_claim_evaluation_service_async_marks_contested_track_b_claim_for_manual_review() -> (
    None
):
    service = ClaimEvaluationService()

    result = await service.evaluate_shadow_async(
        claim_verifications=[
            {
                "claim_id": "claim-contested",
                "claim_text": "Add a Romania wedding-planning FAQ block to the homepage.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": [
                    "contains_imperative_action",
                    "contains_unsupported_concrete_token",
                ],
            }
        ],
        unified_truth_context=_base_truth_context(),
        ai_client=_ContestedTrackBJudgeAIClient(),
        provider="openai",
        tier="smart",
        requested_tier="deep_judgment",
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["judge_mode"] == "llm_shadow"
    assert shadow_claim["shadow_disposition"] == "needs_manual_review"
    assert shadow_claim["confidence_band"] == "contested"
    assert (
        shadow_claim["judge_resolution"]
        == "Signal weak or partially contradictory; manual verification required."
    )
    assert result["summary"]["needs_manual_review_claims"] == 1
