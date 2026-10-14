from pathlib import Path
import sys

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from services.reports.audit_result_adapter import to_canonical_audit_result, to_client_safe_audit


def _base_analysis_payload() -> dict:
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


def test_to_canonical_audit_result_prefers_entities_key() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "entities": ["Canonical Entity", "Another Entity"],
        "analysis": {
            **_base_analysis_payload()["analysis"],
            "entities_detected": ["Legacy Entity"],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["entities"] == ["Canonical Entity", "Another Entity"]
    assert "entities_detected" not in result
    assert result["schema_version"] == "2026-03-09"
    assert result["score_contract"]["public_score_source"] == "deterministic_matrix"
    assert result["target"]["type"] == "website"
    assert result["target"]["url"].startswith("https://example.com")
    assert result["metadata"]["audit_target_type"] == "website"


def test_to_canonical_audit_result_falls_back_to_entities_detected() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "analysis": {
            **_base_analysis_payload()["analysis"],
            "entities_detected": ["Legacy Entity"],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["entities"] == ["Legacy Entity"]


def test_to_canonical_audit_result_promotes_readability_findings_from_answerability_audit() -> None:
    """AEOAnswerabilityService writes into aeo.answerability_audit (audit_runner.py), not
    aeo.readability_findings/rewrite_suggestions directly. The adapter must promote them so the
    AIO tab can actually show this real, computed content instead of an always-empty list."""
    raw_report = {
        **_base_analysis_payload(),
        "aeo": {
            "answerability_audit": {
                "readability_score": 0.42,
                "readability_findings": ["2 paragraph(s) exceed complexity thresholds."],
                "rewrite_suggestions": [
                    {
                        "paragraph": "Signal runs your website through the engines people ask first.",
                        "score": 0.377,
                        "suggestion": "Split long sentences and move the direct answer to the opening sentence.",
                    }
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["aeo"]["readability_findings"] == ["2 paragraph(s) exceed complexity thresholds."]
    assert result["aeo"]["rewrite_suggestions"][0]["suggestion"].startswith("Split long sentences")
    assert result["aeo"]["answerability_audit"]["readability_score"] == 0.42


def test_to_canonical_audit_result_prefers_top_level_readability_over_nested() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "aeo": {
            "readability_findings": ["Top-level finding"],
            "rewrite_suggestions": [
                {"paragraph": "p", "score": 0.1, "suggestion": "top-level suggestion"}
            ],
            "answerability_audit": {
                "readability_findings": ["Nested finding"],
                "rewrite_suggestions": [
                    {"paragraph": "p", "score": 0.2, "suggestion": "nested suggestion"}
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["aeo"]["readability_findings"] == ["Top-level finding"]
    assert result["aeo"]["rewrite_suggestions"][0]["suggestion"] == "top-level suggestion"


def test_to_canonical_audit_result_includes_claim_verification_results() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "hallucination": {
            "threshold": 0.85,
            "total_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-1",
                    "claim_text": "Our office is in Austin Texas.",
                    "matched_truth_key": "claim-1",
                    "truth_value": "Our office is in Austin Texas.",
                    "similarity_score": 1.0,
                    "hallucination": False,
                    "discrepancy_type": "general_mismatch",
                    "severity": "none",
                    "field_path": "summary",
                    "field_label": "Summary sentence 1",
                    "certainty_score": 1.0,
                    "certainty_level": "high",
                    "disposition": "supported",
                    "evidence_refs": [
                        {
                            "source_type": "brand_truth",
                            "source_key": "claim-1",
                            "excerpt": "Our office is in Austin Texas.",
                            "retrieval_score": 1.0,
                        }
                    ],
                    "track": "track_a",
                    "evaluation_mode": "strict_factual_grounding",
                    "claim_kind": "descriptive_observation",
                    "classification_basis": ["asserts_current_state"],
                    "premise_refs": [],
                    "reason_codes": [],
                    "problem_refs": [],
                    "problem_anchor_score": None,
                    "action_fit_score": None,
                    "site_specificity_score": None,
                    "novel_fact_risk_score": None,
                    "suggested_rewrite": None,
                    "omittable": False,
                }
            ],
            "omitted_claims": 0,
            "average_certainty": 1.0,
            "field_summaries": [
                {
                    "field_path": "summary",
                    "label": "Summary",
                    "total_claims": 1,
                    "supported_claims": 1,
                    "flagged_claims": 0,
                    "omitted_claims": 0,
                    "average_certainty": 1.0,
                    "certainty_level": "high",
                }
            ],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["hallucination"]["threshold"] == 0.85
    assert result["hallucination"]["total_claims"] == 1
    assert result["hallucination"]["flagged_claims"] == 0
    assert result["hallucination"]["omitted_claims"] == 0
    assert result["hallucination"]["average_certainty"] == 1.0
    assert result["hallucination"]["claims"][0]["matched_truth_key"] == "claim-1"
    assert result["hallucination"]["claims"][0]["severity"] == "none"
    assert result["hallucination"]["claims"][0]["field_path"] == "summary"
    assert result["hallucination"]["claims"][0]["certainty_level"] == "high"
    assert result["hallucination"]["claims"][0]["evidence_refs"][0]["source_key"] == "claim-1"
    assert result["hallucination"]["claims"][0]["track"] == "track_a"
    assert result["hallucination"]["claims"][0]["evaluation_mode"] == "strict_factual_grounding"
    assert result["hallucination"]["claims"][0]["claim_kind"] == "descriptive_observation"
    assert result["hallucination"]["claims"][0]["classification_basis"] == ["asserts_current_state"]
    assert result["hallucination"]["claims"][0]["premise_refs"] == []
    assert result["hallucination"]["claims"][0]["reason_codes"] == []
    assert result["hallucination"]["claims"][0]["problem_refs"] == []
    assert result["hallucination"]["claims"][0]["site_specificity_score"] is None
    assert result["hallucination"]["claims"][0]["novel_fact_risk_score"] is None
    assert result["hallucination"]["claims"][0]["suggested_rewrite"] is None
    assert result["hallucination"]["claims"][0]["omittable"] is False
    assert result["hallucination"]["high_risk_discrepancies"] == []
    assert result["hallucination"]["field_summaries"][0]["label"] == "Summary"


@pytest.mark.parametrize("invalid_readability_score", [None, "n/a"])
def test_to_canonical_audit_result_defaults_invalid_aeo_readability_score_to_none(
    invalid_readability_score: object,
) -> None:
    raw_report = {
        **_base_analysis_payload(),
        "aeo": {
            "readability_score": invalid_readability_score,
            "readability_findings": ["Sentences too long"],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["aeo"]["readability_score"] is None
    assert {"site", "seo", "geo", "aeo", "scores", "metadata"}.issubset(result.keys())
    assert result["site"]["url"].startswith("https://example.com")
    assert result["site"]["market"] == "us"
    assert result["site"]["language"] == "en"
    assert result["metadata"]["plan"] == "plan_starter"


def test_to_canonical_audit_result_keeps_metadata_extensions_after_normalization() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "metadata": {
            **_base_analysis_payload()["metadata"],
            "lite_refresh": {"enabled": True, "reason": "stale-content"},
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["metadata"]["lite_refresh"] == {"enabled": True, "reason": "stale-content"}


def test_to_canonical_audit_result_keeps_metadata_extensions_on_validation_fallback() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "metadata": {
            **_base_analysis_payload()["metadata"],
            "lite_refresh": {"enabled": True},
        },
        "suggestions": [
            {"title": "Missing action"},
        ],
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    assert result["metadata"]["lite_refresh"] == {"enabled": True}


def test_to_canonical_audit_result_preserves_fast_and_smart_intelligence_fields() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "analysis": {
            "summary": "Base summary",
            "recommendations": ["Add schema"],
            "seo_score": 81,
            "geo_score": 77,
            "aeo_score": 74,
            "executive_dossier": "Executive dossier text",
            "findings": [
                {
                    "source_agent": "Semantic",
                    "severity": "Critical",
                    "observation": "Entity mismatch",
                    "generative_impact": "High",
                    "implementation_guide": "Add organization schema",
                }
            ],
            "citation_probability_score": 0.64,
            "strategic_roadmap": "Strategic roadmap text",
            "neural_intelligence_grid": [
                {
                    "agent_correlation": "Semantic+Intent",
                    "discovery": "Category mismatch",
                    "neural_logic": "Inference penalty",
                    "architect_fix": "Refine category signals",
                    "priority_weight": 8.9,
                }
            ],
            "market_dominance_projection": "Dominance projection",
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")
    metadata = result["metadata"]

    assert metadata["executive_summary"] == "Executive dossier text"
    assert isinstance(metadata["intelligence_dossier"], list)
    assert metadata["strategic_summary"] == "Strategic roadmap text"
    assert isinstance(metadata["debate_findings"], list)
    assert metadata["competitive_positioning"] == "Dominance projection"
    assert metadata["aeo_citation_probability"]["score"] == 0.64
    assert result["confidence"]["narrative_confidence"] == "low"
    assert result["narrative"]["executive_summary"]["text"] == "Strategic roadmap text"
    assert result["narrative"]["competitive_positioning"]["text"] == "Dominance projection"
    assert result["recommendations"]["items"][0]["action"] == "Add schema"


def test_to_canonical_audit_result_preserves_existing_scores_with_iso_datetime_metadata() -> None:
    raw_report = {
        "site": {
            "url": "https://pixelartisanagency.ro/",
            "market": "romania",
            "language": "en",
        },
        "seo": {
            "onpage": 60.0,
            "performance": 83.0,
            "indexing": 60.0,
        },
        "geo": {
            "visibility_index": 60.0,
            "citation_share": None,
            "brand_anchor": None,
        },
        "aeo": {
            "answerability_score": 60.0,
            "extractable_pages": None,
            "schema_health": {"score": 0.0},
            "schema_coverage": {
                "coverage_by_type": {"FAQPage": 0.0},
                "coverage_percent": 0.0,
                "missing_high_impact_types": ["FAQPage"],
            },
            "readability_score": None,
            "readability_findings": [],
            "rewrite_suggestions": [],
        },
        "entities": ["React App", "Pixelartisanagency"],
        "competitors": [],
        "suggestions": [
            {
                "priority": 1,
                "title": "Optimize headings",
                "action": "Use a single descriptive H1.",
                "category": "Content",
            }
        ],
        "scores": {
            "seo": 32.8,
            "geo": 32.8,
            "aeo": 32.8,
            "overall": 32.8,
        },
        "metadata": {
            "created_at": "2026-02-26T18:22:22.836588Z",
            "updated_at": "2026-02-26T18:22:22.836588Z",
            "plan": "plan_executive",
            "version": "2.0",
            "service_status": {},
            "service_errors": {},
            "competitor_summary": {},
            "scores_available": True,
            "audit_outcome": "completed",
            "intent": "informational",
            "query_type": "informational",
            "technical_signals": {},
        },
        "hallucination": {
            "threshold": 0.85,
            "total_claims": 14,
            "flagged_claims": 0,
            "claims": [],
            "high_risk_discrepancies": [],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://pixelartisanagency.ro/")

    assert result["seo"]["onpage"] == 60.0
    assert result["seo"]["performance"] == 83.0
    assert result["seo"]["indexing"] == 60.0
    assert result["aeo"]["answerability_score"] == 60.0
    assert result["scores"]["seo"] == 32.8
    assert result["scores"]["overall"] == 32.8
    assert result["generated_at"] == "2026-02-26T18:22:22.836588Z"
    assert result["target"]["type"] == "website"
    assert result["target"]["url"] == "https://pixelartisanagency.ro/"


def test_to_canonical_audit_result_supports_brand_target_contract() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "site": {"url": None, "market": "global", "language": "en"},
        "target": {
            "type": "brand",
            "name": "Acme",
            "url": None,
            "metadata": {"aliases": ["ACME Inc"]},
        },
    }

    result = to_canonical_audit_result(
        raw_report,
        audit_url=None,
        audit_target_type="brand",
        target_name="Acme",
        target_url=None,
        target_metadata={"aliases": ["ACME Inc"], "domains": ["acme.com"]},
    )

    assert result["target"]["type"] == "brand"
    assert result["target"]["name"] == "Acme"
    assert result["target"]["url"] is None
    assert result["target"]["metadata"]["domains"] == ["acme.com"]
    assert result["site"]["url"] is None
    assert result["audit_mode"] == "brand"
    assert result["metadata"]["audit_target_type"] == "brand"
    assert result["metadata"]["target_name"] == "Acme"


def test_to_canonical_audit_result_builds_single_track_integrity_certificate() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "hallucination": {
            "threshold": 0.85,
            "total_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-1",
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
                    "track": "track_a",
                    "claim_kind": "descriptive_observation",
                    "classification_basis": ["asserts_current_state"],
                    "premise_refs": [],
                    "omittable": True,
                }
            ],
            "omitted_claims": 1,
            "average_certainty": 0.12,
            "field_summaries": [],
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    certificate = result["integrity_certificate"]
    assert certificate["schema_version"] == "integrity-certificate-1"
    assert certificate["dual_track_grounding_enabled"] is False
    assert certificate["grounding_profile"] == "single_track_v1"
    assert certificate["summary"]["total_claims"] == 1
    assert certificate["summary"]["track_a_omitted"] == 1
    assert certificate["summary"]["track_b_total"] == 0
    assert certificate["blocked_claim_buckets"] == [
        {"track": "track_a", "category": "missing_evidence", "count": 1}
    ]
    assert certificate["degraded"] is False
    assert certificate["degraded_reason"] is None


def test_to_canonical_audit_result_builds_dual_track_integrity_certificate_from_shadow_metadata() -> (
    None
):
    raw_report = {
        **_base_analysis_payload(),
        "hallucination": {
            "threshold": 0.85,
            "total_sentences": 1,
            "claim_verifications": [
                {
                    "claim_id": "claim-a",
                    "claim_text": "Missing FAQ schema reduces answer extraction.",
                    "matched_truth_key": "claim-a",
                    "truth_value": "Missing FAQ schema reduces answer extraction.",
                    "similarity_score": 0.91,
                    "hallucination": False,
                    "discrepancy_type": None,
                    "severity": "none",
                    "field_path": "summary",
                    "field_label": "Summary sentence 1",
                    "certainty_score": 0.91,
                    "certainty_level": "high",
                    "disposition": "supported",
                    "evidence_refs": [
                        {
                            "source_type": "scraped_content",
                            "source_key": "chunk-1",
                            "excerpt": "FAQ schema is missing.",
                            "retrieval_score": 0.91,
                        }
                    ],
                    "track": "track_a",
                    "claim_kind": "descriptive_observation",
                    "classification_basis": ["asserts_current_state"],
                    "premise_refs": [],
                    "omittable": False,
                }
            ],
            "omitted_claims": 0,
            "average_certainty": 0.91,
            "field_summaries": [],
        },
        "metadata": {
            **_base_analysis_payload()["metadata"],
            "dual_track_shadow": {
                "status": "shadow",
                "authoritative_mode": "single_track",
                "summary": {
                    "track_a_claims": 1,
                    "track_b_claims": 1,
                    "mixed_claims": 0,
                    "supported_claims": 1,
                    "flagged_claims": 0,
                    "omitted_claims": 1,
                },
                "track_b_judge": {
                    "requested_tier": "deep_judgment",
                    "enabled": True,
                    "available": False,
                    "mode": "deterministic_shadow",
                    "evaluated_claims": 1,
                    "llm_evaluated_claims": 0,
                    "deterministic_fallback_claims": 0,
                    "judge_unavailable_claims": 1,
                    "providers": [],
                    "models": [],
                },
                "claims": [
                    {
                        "claim_id": "claim-a",
                        "track": "track_a",
                        "shadow_disposition": "supported",
                    },
                    {
                        "claim_id": "claim-b",
                        "track": "track_b",
                        "shadow_disposition": "omitted",
                        "reason_codes": ["unsupported_premise_ref"],
                        "problem_refs": [],
                        "premise_refs": ["claim-mixed-a"],
                    },
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    certificate = result["integrity_certificate"]
    assert certificate["dual_track_grounding_enabled"] is True
    assert certificate["grounding_profile"] == "dual_track_v1"
    assert certificate["summary"]["track_a_total"] == 1
    assert certificate["summary"]["track_b_total"] == 1
    assert certificate["summary"]["track_b_omitted"] == 1
    assert certificate["blocked_claim_buckets"] == [
        {"track": "track_b", "category": "unsupported_factual_premise", "count": 1}
    ]
    assert certificate["degraded"] is True
    assert certificate["degraded_reason"] == "track_b_judge_unavailable"


def test_to_canonical_audit_result_counts_manual_review_track_b_claims_separately() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "metadata": {
            **_base_analysis_payload()["metadata"],
            "dual_track_shadow": {
                "status": "shadow",
                "authoritative_mode": "single_track",
                "summary": {
                    "track_a_claims": 0,
                    "track_b_claims": 1,
                    "mixed_claims": 0,
                    "supported_claims": 0,
                    "flagged_claims": 0,
                    "needs_manual_review_claims": 1,
                    "omitted_claims": 0,
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
                    "needs_manual_review_claims": 1,
                    "providers": ["openai"],
                    "models": ["gpt-5.4"],
                },
                "claims": [
                    {
                        "claim_id": "claim-b-review",
                        "claim_text": "Add a Romania wedding-planning FAQ block to the homepage.",
                        "track": "track_b",
                        "shadow_disposition": "needs_manual_review",
                        "confidence_band": "contested",
                        "judge_resolution": "Signal weak or partially contradictory; manual verification required.",
                        "reason_codes": ["needs_narrower_wording", "unsupported_location"],
                    },
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    certificate = result["integrity_certificate"]
    assert certificate["summary"]["track_b_total"] == 1
    assert certificate["summary"]["track_b_flagged"] == 0
    assert certificate["summary"]["track_b_needs_manual_review"] == 1
    assert certificate["summary"]["track_b_omitted"] == 0
    assert certificate["blocked_claim_buckets"] == [
        {"track": "track_b", "category": "manual_verification_required", "count": 1}
    ]
    assert certificate["degraded"] is False
    assert certificate["degraded_reason"] is None


def test_to_canonical_audit_result_treats_manual_review_overrides_as_export_safe_states() -> None:
    raw_report = {
        **_base_analysis_payload(),
        "metadata": {
            **_base_analysis_payload()["metadata"],
            "dual_track_shadow": {
                "status": "shadow",
                "authoritative_mode": "single_track",
                "summary": {
                    "track_a_claims": 0,
                    "track_b_claims": 2,
                    "mixed_claims": 0,
                    "supported_claims": 0,
                    "flagged_claims": 0,
                    "needs_manual_review_claims": 2,
                    "omitted_claims": 0,
                },
                "track_b_judge": {
                    "requested_tier": "deep_judgment",
                    "enabled": True,
                    "available": True,
                    "mode": "llm_shadow",
                    "evaluated_claims": 2,
                    "llm_evaluated_claims": 2,
                    "deterministic_fallback_claims": 0,
                    "judge_unavailable_claims": 0,
                    "needs_manual_review_claims": 2,
                    "providers": ["openai"],
                    "models": ["gpt-5.4"],
                },
                "claims": [
                    {
                        "claim_id": "seo-12",
                        "claim_text": "Add FAQ schema to product pages.",
                        "track": "track_b",
                        "shadow_disposition": "manually_approved",
                        "confidence_band": "contested",
                        "judge_resolution": "Agency validated the recommendation.",
                        "reason_codes": ["unsupported_premise_ref"],
                        "review_decision": {
                            "disposition": "manually_approved",
                            "note": "Validated by the content team.",
                        },
                    },
                    {
                        "claim_id": "geo-05",
                        "claim_text": "Expand local pages into unsupported cities.",
                        "track": "track_b",
                        "shadow_disposition": "manually_refused",
                        "confidence_band": "contested",
                        "judge_resolution": "Agency refused the recommendation.",
                        "reason_codes": ["unsupported_location"],
                        "review_decision": {
                            "disposition": "manually_refused",
                            "note": "Location coverage is not supported.",
                        },
                    },
                ],
            },
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    certificate = result["integrity_certificate"]
    assert certificate["summary"]["track_b_total"] == 1
    assert certificate["summary"]["track_b_supported"] == 1
    assert certificate["summary"]["track_b_needs_manual_review"] == 0
    assert certificate["summary"]["track_b_manually_approved"] == 1
    assert certificate["summary"]["track_b_manually_refused"] == 1
    assert certificate["blocked_claim_buckets"] == []
    assert (
        result["metadata"]["dual_track_shadow"]["claims"][1]["shadow_disposition"]
        == "manually_refused"
    )


def test_to_canonical_audit_result_preserves_existing_integrity_certificate_when_no_grounding_inputs_exist() -> (
    None
):
    raw_report = {
        **_base_analysis_payload(),
        "integrity_certificate": {
            "schema_version": "integrity-certificate-1",
            "dual_track_grounding_enabled": True,
            "grounding_profile": "dual_track_v1",
            "summary": {
                "total_claims": 2,
                "track_a_total": 1,
                "track_a_supported": 1,
                "track_a_flagged": 0,
                "track_a_omitted": 0,
                "track_b_total": 1,
                "track_b_supported": 0,
                "track_b_flagged": 1,
                "track_b_omitted": 0,
            },
            "blocked_claim_buckets": [
                {"track": "track_b", "category": "generic_recommendation", "count": 1}
            ],
            "degraded": False,
            "degraded_reason": None,
        },
    }

    result = to_canonical_audit_result(raw_report, audit_url="https://example.com")

    certificate = result["integrity_certificate"]
    assert certificate["grounding_profile"] == "dual_track_v1"
    assert certificate["summary"]["track_b_flagged"] == 1
    assert certificate["blocked_claim_buckets"] == [
        {"track": "track_b", "category": "generic_recommendation", "count": 1}
    ]


def test_to_client_safe_audit_strips_internal_fields_from_canonical_payload() -> None:
    canonical = to_canonical_audit_result(
        {
            **_base_analysis_payload(),
            "raw_ai_scores": {"seo": 91},
            "metadata": {
                **_base_analysis_payload()["metadata"],
                "ai_generation": {"provider": "google"},
            },
            "hallucination": {
                "threshold": 0.85,
                "total_sentences": 2,
                "claim_verifications": [
                    {
                        "claim_id": "claim-1",
                        "claim_text": "Unsupported award claim.",
                        "matched_truth_key": "no_evidence",
                        "truth_value": "No relevant supporting passage found in crawled content.",
                        "similarity_score": 0.21,
                        "hallucination": True,
                        "discrepancy_type": "general_mismatch",
                        "severity": "medium",
                        "field_path": "summary",
                        "field_label": "Summary sentence 1",
                        "certainty_score": 0.21,
                        "certainty_level": "low",
                        "disposition": "omitted",
                        "evidence_refs": [],
                    }
                ],
            },
        },
        audit_url="https://example.com",
    )

    client_safe = to_client_safe_audit(canonical)

    assert "raw_ai_scores" not in client_safe
    assert "hallucination" not in client_safe
    assert client_safe["integrity_certificate"]["grounding_profile"] == "single_track_v1"
    assert "plan" not in client_safe["metadata"]
    assert "ai_generation" not in client_safe["metadata"]
    assert client_safe["confidence"]["audit_mode"] == "website"


def _canonical_stored_report() -> dict:
    """A stored canonical report whose suggestions/recommendations items are in a
    shape the strict AuditResult model rejects, which is how production reports
    look. The happy-path re-validation fails and the fallback rebuild runs; the
    stored pillar sub-scores must still be served rather than zeroed."""
    return {
        "target": {
            "type": "website",
            "name": "Qiko",
            "url": "https://qiko.ai",
            "metadata": {},
        },
        "site": {"url": "https://qiko.ai", "market": "uk", "language": "en"},
        "seo": {
            "onpage": 68.0,
            "performance": 61.0,
            "indexing": 76.0,
            "core_web_vitals": 59.0,
            "technical_seo": 74.0,
            "onpage_content": 66.0,
            "eeat_trust": 56.0,
            "security_accessibility": 79.0,
        },
        "geo": {
            "visibility_index": 53.0,
            "citation_share": 38.0,
            "brand_anchor": 45.0,
            "advanced_local_schema": 64.0,
            "napw_completeness": 70.0,
            "spatial_content": 44.0,
            "brand_citation": 50.0,
            "content_citability": 58.0,
            "source_authority": 47.0,
            "entity_clarity": 61.0,
        },
        "aeo": {
            "answerability_score": 65.0,
            "extractable_pages": 9,
            "schema_health": {"pages_with_schema": 9, "pages_checked": 14, "errors": 2},
            "schema_coverage": {"faq": True, "howto": False},
            "readability_score": 0.73,
            "readability_findings": ["Wall of text on /pricing"],
            "rewrite_suggestions": [{"page": "/pricing", "issue": "long paragraphs"}],
            "llm_schema_readiness": 62.0,
            "semantic_entity_density": 55.0,
            "information_gain": 48.0,
            "snippet_formatting": 71.0,
        },
        "entities": ["Qiko"],
        "competitors": [],
        "suggestions": [
            {
                "title": "Publish structured data",
                "category": "Technical",
                "priority": 1,
            },
        ],
        "recommendations": {
            "items": [
                {
                    "id": "rec-1",
                    "title": "Add FAQ and HowTo schema",
                    "priority": 1,
                    "action": "Publish schema markup on key pages",
                    "expected_score_impact": {"overall": 8},
                },
            ],
        },
        "scores": {"seo": 70, "geo": 56, "aeo": 62, "overall": 63},
        "metadata": {
            "plan": "plan_executive",
            "demo_seed": True,
            "created_at": "2026-09-28T11:01:18.125613+00:00",
            "updated_at": "2026-09-28T11:01:18.125613+00:00",
            "version": "3.0",
        },
        "generated_at": "2026-09-28T11:01:18.125613+00:00",
    }


def test_to_canonical_audit_result_serves_stored_pillar_subscores_on_validation_fallback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    raw_report = _canonical_stored_report()

    with caplog.at_level(logging.WARNING):
        result = to_canonical_audit_result(raw_report, audit_url="https://qiko.ai")

    geo = result["geo"]
    assert geo["visibility_index"] == 53.0
    assert geo["citation_share"] == 38.0
    assert geo["brand_anchor"] == 45.0
    assert geo["advanced_local_schema"] == 64.0
    assert geo["napw_completeness"] == 70.0
    assert geo["spatial_content"] == 44.0
    assert geo["brand_citation"] == 50.0
    assert geo["content_citability"] == 58.0
    assert geo["source_authority"] == 47.0
    assert geo["entity_clarity"] == 61.0

    aeo = result["aeo"]
    assert aeo["answerability_score"] == 65.0
    assert aeo["llm_schema_readiness"] == 62.0
    assert aeo["semantic_entity_density"] == 55.0
    assert aeo["information_gain"] == 48.0
    assert aeo["snippet_formatting"] == 71.0
    assert aeo["readability_score"] == 0.73

    seo = result["seo"]
    assert seo["onpage"] == 68.0
    assert seo["performance"] == 61.0
    assert seo["indexing"] == 76.0
    assert seo["core_web_vitals"] == 59.0

    assert result["scores"]["seo"] == 70
    assert result["scores"]["geo"] == 56
    assert result["scores"]["aeo"] == 62

    # A stored canonical report that falls back must not do so silently: the
    # validation failure is logged at WARNING so it cannot hide again.
    assert any(
        record.levelno >= logging.WARNING and "canonical" in record.getMessage().lower()
        for record in caplog.records
    )
