import pytest

from services.claim_evaluation_service import ClaimEvaluationService
from services.reports.audit_result_adapter import to_canonical_audit_result


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
        "vision_agent_insights": [],
        "domain_standards": [
            {
                "source_id": "standard-1",
                "category": "aeo",
                "excerpt": "FAQ schema improves answer extraction when the page already contains supported question-answer content.",
            }
        ],
    }


def _base_report_payload() -> dict:
    return {
        "analysis": {
            "seo_score": 88,
            "geo_score": 84,
            "aeo_score": 79,
            "recommendations": ["Add schema"],
        },
        "performance": {"performance_score": 85},
        "metadata": {"market": "us", "language": "en", "plan": "plan_starter"},
    }


class _FailingTrackBJudgeAIClient:
    async def evaluate_track_b_claim(self, **kwargs) -> dict:
        raise RuntimeError("judge unavailable")


def test_dual_track_regression_fixture_strategic_site_specific_supported() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-1",
                "claim_text": "Add FAQ schema to the homepage to improve answer extraction.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "supported"
    assert shadow_claim["problem_anchor_score"] >= 0.75
    assert shadow_claim["reason_codes"] == []


def test_dual_track_regression_fixture_generic_advice_rejected() -> None:
    service = ClaimEvaluationService()

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-2",
                "claim_text": "Improve your content strategy.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": ["contains_imperative_action"],
            }
        ],
        unified_truth_context=_base_truth_context(),
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "omitted"
    assert "generic_advice" in shadow_claim["reason_codes"]
    assert "no_supported_problem" in shadow_claim["reason_codes"]


def test_dual_track_regression_fixture_fact_laundering_location_rejected() -> None:
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


def test_dual_track_regression_fixture_mixed_claim_split() -> None:
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

    premise_claim = result["claims"][0]
    recommendation_claim = result["claims"][1]

    assert premise_claim["track"] == "track_a"
    assert premise_claim["source_track"] == "mixed"
    assert premise_claim["shadow_disposition"] == "omitted"
    assert recommendation_claim["track"] == "track_b"
    assert recommendation_claim["premise_refs"] == ["claim-mixed-a"]
    assert recommendation_claim["shadow_disposition"] == "omitted"
    assert "unsupported_premise_ref" in recommendation_claim["reason_codes"]


def test_dual_track_regression_fixture_brand_metadata_locality_supported() -> None:
    service = ClaimEvaluationService()
    truth_context = _base_truth_context()
    truth_context["target_profile"]["target_metadata"] = {
        "target_country": "Romania",
        "primary_market": "Romania",
        "language": "ro",
    }
    truth_context["target_profile"]["brand_truth_payload"] = {
        "service_area": "Romania",
    }
    truth_context["supported_track_a_claims"] = [
        {
            "claim_id": "claim-ro",
            "claim_text": (
                "The homepage H1 lacks a Romania market modifier even though target metadata "
                "confirms Romania as the primary market."
            ),
            "field_path": "geo_findings[0].description",
            "reason": "Supported Track A claim retained from grounding validation.",
            "evidence_refs": [],
        }
    ]
    truth_context["technical_agent_insights"] = [
        {
            "source_id": "insight-ro",
            "source_label": "Technical insight",
            "source_type": "technical",
            "trust_tier": "T1",
            "insight_text": "Homepage H1 localization is weak for the Romania primary market.",
            "evidence_refs": [],
        }
    ]
    truth_context["domain_standards"] = [
        {
            "source_id": "standard-ro",
            "category": "geo",
            "excerpt": (
                "Homepage H1 local-market modifiers improve relevance when they match authoritative "
                "target metadata."
            ),
        }
    ]

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-4",
                "claim_text": (
                    "Add a Romania primary-market modifier to the homepage H1 because target metadata "
                    "confirms Romania as the primary market."
                ),
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": [
                    "contains_imperative_action",
                    "conditional_on_authoritative_metadata",
                ],
            }
        ],
        unified_truth_context=truth_context,
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "supported"
    assert "unsupported_location" not in shadow_claim["reason_codes"]
    assert shadow_claim["novel_fact_risk_score"] <= 0.25


def test_dual_track_regression_fixture_vision_only_overreach_rejected() -> None:
    service = ClaimEvaluationService()
    truth_context = _base_truth_context()
    truth_context["vision_agent_insights"] = [
        {
            "source_id": "vision-1",
            "source_label": "Vision insight",
            "source_type": "vision",
            "trust_tier": "T4",
            "insight_text": "Hero imagery suggests a luxury wedding aesthetic.",
            "limitations": ["Visual mood only; no verified service catalog facts."],
        }
    ]

    result = service.evaluate_shadow(
        claim_verifications=[
            {
                "claim_id": "claim-5",
                "claim_text": "Position the homepage copy around a luxury wedding planning service.",
                "track": "track_b",
                "disposition": "supported",
                "classification_basis": [
                    "contains_imperative_action",
                    "contains_unsupported_concrete_token",
                ],
            }
        ],
        unified_truth_context=truth_context,
    )

    assert result is not None
    shadow_claim = result["claims"][0]
    assert shadow_claim["shadow_disposition"] == "omitted"
    assert "vision_only_overreach" in shadow_claim["reason_codes"]
    assert "invented_site_fact" in shadow_claim["reason_codes"]
    assert "unsupported_service_label" in shadow_claim["reason_codes"]


@pytest.mark.asyncio
async def test_dual_track_regression_fixture_track_b_judge_unavailable_safe_fail() -> None:
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


def test_dual_track_regression_fixture_legacy_contract_parity() -> None:
    raw_report = {
        **_base_report_payload(),
        "hallucination": {
            "threshold": 0.85,
            "total_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-legacy",
                    "claim_text": "Unsupported award claim.",
                    "matched_truth_key": "no_evidence",
                    "truth_value": "No relevant supporting passage found in crawled content.",
                    "similarity_score": 0.12,
                    "hallucination": True,
                    "discrepancy_type": "general_mismatch",
                    "severity": "medium",
                    "field_path": "summary",
                    "field_label": "Summary sentence 1",
                    "certainty_score": 0.12,
                    "certainty_level": "low",
                    "disposition": "omitted",
                    "evidence_refs": [],
                }
            ],
            "omitted_claims": 1,
            "average_certainty": 0.12,
            "field_summaries": [],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["integrity_certificate"]["grounding_profile"] == "single_track_v1"
    assert result["integrity_certificate"]["summary"]["track_b_total"] == 0
    assert result["integrity_certificate"]["blocked_claim_buckets"] == [
        {"track": "track_a", "category": "missing_evidence", "count": 1}
    ]


def test_dual_track_regression_fixture_single_track_fallback_rendering() -> None:
    raw_report = {
        **_base_report_payload(),
        "metadata": {
            **_base_report_payload()["metadata"],
            "grounding_profile": "single_track_fallback",
            "fallback_reason": "unified_truth_context_unavailable",
        },
        "hallucination": {
            "threshold": 0.85,
            "total_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-fallback",
                    "claim_text": "The site already states its refund policy clearly.",
                    "matched_truth_key": "claim-fallback",
                    "truth_value": "The site already states its refund policy clearly.",
                    "similarity_score": 0.92,
                    "hallucination": False,
                    "discrepancy_type": None,
                    "severity": "none",
                    "field_path": "summary",
                    "field_label": "Summary sentence 1",
                    "certainty_score": 0.92,
                    "certainty_level": "high",
                    "disposition": "supported",
                    "evidence_refs": [],
                }
            ],
            "omitted_claims": 0,
            "average_certainty": 0.92,
            "field_summaries": [],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["integrity_certificate"] is not None
    assert result["integrity_certificate"]["summary"]["track_a_total"] == 1
    assert result["integrity_certificate"]["summary"]["track_b_total"] == 0
    assert result["integrity_certificate"]["degraded"] is False


def test_dual_track_regression_fixture_integrity_certificate_prefers_vision_bucket() -> None:
    raw_report = {
        **_base_report_payload(),
        "metadata": {
            **_base_report_payload()["metadata"],
            "dual_track_shadow": {
                "status": "shadow",
                "authoritative_mode": "single_track",
                "summary": {
                    "track_a_claims": 0,
                    "track_b_claims": 1,
                    "mixed_claims": 0,
                    "supported_claims": 0,
                    "flagged_claims": 0,
                    "omitted_claims": 1,
                },
                "track_b_judge": {
                    "requested_tier": "deep_judgment",
                    "enabled": True,
                    "available": True,
                    "mode": "llm_shadow",
                    "evaluated_claims": 1,
                    "llm_evaluated_claims": 1,
                    "deterministic_fallback_claims": 0,
                    "judge_unavailable_claims": 0,
                    "providers": ["openai"],
                    "models": ["gpt-5.4"],
                },
                "claims": [
                    {
                        "claim_id": "claim-vision",
                        "track": "track_b",
                        "shadow_disposition": "omitted",
                        "reason_codes": [
                            "vision_only_overreach",
                            "invented_site_fact",
                            "unsupported_service_label",
                        ],
                    }
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["integrity_certificate"]["blocked_claim_buckets"] == [
        {"track": "track_b", "category": "vision_only_overreach", "count": 1}
    ]
