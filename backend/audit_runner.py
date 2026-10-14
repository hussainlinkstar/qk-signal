import asyncio
from dataclasses import dataclass
import logging
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

import models
from core.config import settings
from app.services.aeo.structure_service import analyze_json_ld_structure
from app.services.suggestions.problem_code_suggestions import build_problem_code_suggestions
from app.services.suggestions.suggestion_engine import generate_unified_suggestions
from problem_codes import normalize_problem_code
from report_schema import AuditAnalysis, AuditReport
from services.advisor_service import build_advisor_plan, generate_strategic_summary
from services.reports.audit_result_adapter import to_canonical_audit_result
from services.query_taxonomy import resolve_query_type
from services.entity_extraction import build_entity_list
from services.audit_feature_gating_service import (
    resolve_audit_execution_gates,
    sanitize_audit_payload_for_plan,
)
from app.config.plans import can_use_feature
from services.audit_data_sources import resolve_project_audit_data_sources
from services.ai_routing_policy import normalize_audit_tier
from services.project_audit_scope import competitor_audit_clause
from services.claim_evaluation_service import ClaimEvaluationService
from services.observability import redact_secrets
from observability import (
    audit_dual_track_claims_total,
    audit_dual_track_fallback_total,
    audit_dual_track_reason_codes_total,
)
from services.grounding_gate_service import GroundingGateService
from services.hallucination_service import HallucinationService
from services.embedding_service import EmbeddingCache
from services.resilience import ServiceUnavailableError
from services.unified_truth_context_service import UnifiedTruthContextService
from services.aeo_answerability_service import AEOAnswerabilityService
from services.geo_visibility_service import GeoVisibilityService
from score_utils import extract_score, DeterministicScoringEngine, calculate_deterministic_scores

logger = logging.getLogger(__name__)

AUDIT_OUTCOME_COMPLETED = "completed"
AUDIT_OUTCOME_DEGRADED = "degraded"
AUDIT_OUTCOME_FAILED = "failed"

CANONICAL_AUDIT_CATEGORIES = (
    "saas",
    "ecommerce",
    "finance",
    "health",
    "travel",
    "media",
    "dental clinic",
    "law firm",
    "hvac",
    "real estate",
    "plumbing",
    "roofing",
    "general",
)

CATEGORY_INFERENCE_SIGNALS: dict[str, tuple[str, ...]] = {
    "dental clinic": ("dental", "dentist", "orthodont", "teeth", "smile"),
    "law firm": ("law", "attorney", "legal", "injury", "litigation"),
    "hvac": ("hvac", "heating", "cooling", "air conditioning", "furnace"),
    "real estate": ("real estate", "realtor", "homes", "property", "mortgage"),
    "plumbing": ("plumbing", "plumber", "drain", "pipe", "water heater"),
    "roofing": ("roof", "roofing", "shingle", "gutter"),
    "ecommerce": ("shop", "store", "cart", "checkout", "buy now"),
    "saas": ("software", "platform", "api", "workflow", "automation"),
}


@dataclass(frozen=True)
class DualTrackExecutionDecision:
    rollout_mode: str
    effective_execution_mode: str
    should_evaluate_shadow: bool
    client_safe_authority: str = "single_track"


def _resolve_dual_track_execution(requested_tier: str | None) -> DualTrackExecutionDecision:
    normalized_tier = normalize_audit_tier(requested_tier or "").strip().lower()
    if normalized_tier == "deep_judgment":
        return DualTrackExecutionDecision(
            rollout_mode="canonical_deep_judgment",
            effective_execution_mode="shadow",
            should_evaluate_shadow=True,
        )
    return DualTrackExecutionDecision(
        rollout_mode="single_track_only",
        effective_execution_mode="disabled",
        should_evaluate_shadow=False,
    )


def _record_dual_track_observability(
    *,
    dual_track_shadow: dict[str, Any] | None,
    fallback_reason: str | None,
) -> None:
    if isinstance(dual_track_shadow, dict):
        claims = dual_track_shadow.get("claims")
        if isinstance(claims, list):
            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                track = str(claim.get("track") or "unknown").strip().lower() or "unknown"
                disposition = (
                    str(claim.get("shadow_disposition") or "unknown").strip().lower() or "unknown"
                )
                audit_dual_track_claims_total.labels(track, disposition).inc()
                reason_codes = claim.get("reason_codes")
                if isinstance(reason_codes, list):
                    for reason_code in reason_codes:
                        normalized_reason = str(reason_code or "").strip().lower()
                        if normalized_reason:
                            audit_dual_track_reason_codes_total.labels(
                                track,
                                normalized_reason,
                            ).inc()

    normalized_fallback_reason = str(fallback_reason or "").strip().lower()
    if normalized_fallback_reason:
        audit_dual_track_fallback_total.labels(normalized_fallback_reason).inc()


def _build_dual_track_metadata(
    *,
    rollout_mode: str,
    effective_execution_mode: str,
    dual_track_shadow: dict[str, Any] | None,
    unified_truth_context_version: str | None,
    fallback_reason: str | None,
    dual_track_grounding_enabled: bool,
    client_safe_authority: str = "single_track",
) -> dict[str, Any]:
    shadow_summary = dual_track_shadow.get("summary") if isinstance(dual_track_shadow, dict) else {}
    track_b_judge = (
        dual_track_shadow.get("track_b_judge") if isinstance(dual_track_shadow, dict) else {}
    )
    if not isinstance(shadow_summary, dict):
        shadow_summary = {}
    if not isinstance(track_b_judge, dict):
        track_b_judge = {}

    track_a_claim_count = int(shadow_summary.get("track_a_claims") or 0)
    track_b_claim_count = int(shadow_summary.get("track_b_claims") or 0)
    supported_claims = int(shadow_summary.get("supported_claims") or 0)
    flagged_claims = int(shadow_summary.get("flagged_claims") or 0)
    needs_manual_review_claims = int(shadow_summary.get("needs_manual_review_claims") or 0)
    omitted_claims = int(shadow_summary.get("omitted_claims") or 0)
    degraded = bool(fallback_reason or int(track_b_judge.get("judge_unavailable_claims") or 0) > 0)

    grounding_profile = (
        "dual_track_shadow_v1" if dual_track_grounding_enabled else "single_track_v1"
    )
    if fallback_reason in {
        "claim_classifier_unavailable",
        "claim_verifications_unavailable",
        "unified_truth_context_unavailable",
    }:
        grounding_profile = "single_track_fallback"

    return {
        "rollout_mode": rollout_mode,
        "effective_execution_mode": effective_execution_mode,
        "grounding_profile": grounding_profile,
        "dual_track_grounding_enabled": dual_track_grounding_enabled,
        "client_safe_authority": client_safe_authority,
        "unified_truth_context_version": unified_truth_context_version,
        "track_a_claim_count": track_a_claim_count,
        "track_b_claim_count": track_b_claim_count,
        "integrity_certificate_summary": {
            "track_a_claim_count": track_a_claim_count,
            "track_b_claim_count": track_b_claim_count,
            "supported_claims": supported_claims,
            "flagged_claims": flagged_claims,
            "needs_manual_review_claims": needs_manual_review_claims,
            "omitted_claims": omitted_claims,
            "degraded": degraded,
        },
        "fallback_reason": fallback_reason,
    }


def _normalize_usage_payload(usage: dict | None) -> dict[str, int]:
    payload = usage if isinstance(usage, dict) else {}
    prompt_tokens = int(
        payload.get("prompt_tokens")
        or payload.get("input_tokens")
        or payload.get("prompt_token_count")
        or 0
    )
    completion_tokens = int(
        payload.get("completion_tokens")
        or payload.get("output_tokens")
        or payload.get("candidates_token_count")
        or 0
    )
    total_tokens = int(payload.get("total_tokens") or (prompt_tokens + completion_tokens) or 0)
    return {
        "prompt_tokens": max(0, prompt_tokens),
        "completion_tokens": max(0, completion_tokens),
        "total_tokens": max(0, total_tokens),
    }


def _build_ai_generation_metadata(
    *,
    provider_used: str | None,
    model_name: str | None,
    ai_analysis_results: dict[str, object] | None,
    debate_metadata: dict[str, object] | None = None,
    usage_payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    analysis_payload = ai_analysis_results if isinstance(ai_analysis_results, dict) else {}
    raw_usage = (
        usage_payload
        if isinstance(usage_payload, dict)
        else next(
            (
                value
                for key, value in analysis_payload.items()
                if isinstance(key, str)
                and key.startswith("_")
                and key.endswith("_usage")
                and isinstance(value, dict)
            ),
            None,
        )
    )
    usage = _normalize_usage_payload(raw_usage if isinstance(raw_usage, dict) else None)
    generation_metadata: dict[str, object] = {
        "mode": "single",
        "provider": str(provider_used or "").strip() or None,
        "model": str(model_name or "").strip() or None,
    }
    if usage["total_tokens"] > 0:
        generation_metadata["usage"] = usage

    debate_payload = (
        debate_metadata if isinstance(debate_metadata, dict) else analysis_payload.get("_debate")
    )
    if isinstance(debate_payload, dict):
        metadata_mode = str(debate_payload.get("mode") or "debate").strip().lower() or "debate"
        transcript = (
            debate_payload.get("transcript")
            if isinstance(debate_payload.get("transcript"), list)
            else []
        )
        generation_metadata["mode"] = metadata_mode
        generation_metadata["provider"] = (
            str(debate_payload.get("provider") or "multi-provider").strip() or "multi-provider"
        )
        generation_metadata["model"] = (
            str(debate_payload.get("model") or "multi-agent").strip() or "multi-agent"
        )
        aggregated_usage = _normalize_usage_payload(
            debate_payload.get("usage")
            if isinstance(debate_payload.get("usage"), dict)
            else debate_payload.get("total_token_usage")
            if isinstance(debate_payload.get("total_token_usage"), dict)
            else None
        )
        if aggregated_usage["total_tokens"] > 0:
            generation_metadata["usage"] = aggregated_usage
        if metadata_mode == "debate":
            generation_metadata["debate_confidence_score"] = debate_payload.get(
                "debate_confidence_score"
            )
            if isinstance(debate_payload.get("profile"), str) and debate_payload.get("profile"):
                generation_metadata["profile"] = str(debate_payload.get("profile"))
            if isinstance(debate_payload.get("fallback_reason"), str) and debate_payload.get(
                "fallback_reason"
            ):
                generation_metadata["fallback_reason"] = str(debate_payload.get("fallback_reason"))
            if isinstance(debate_payload.get("judge_summary"), dict):
                generation_metadata["judge_summary"] = dict(debate_payload.get("judge_summary"))
            if isinstance(debate_payload.get("judge_authority"), str) and debate_payload.get(
                "judge_authority"
            ):
                generation_metadata["judge_authority"] = str(debate_payload.get("judge_authority"))
            generation_metadata["estimated_llm_cost_usd"] = debate_payload.get(
                "total_estimated_cost_usd"
            ) or debate_payload.get("total_estimated_cost_usd")
        elif isinstance(debate_payload.get("fallback_reason"), str) and debate_payload.get(
            "fallback_reason"
        ):
            generation_metadata["fallback_reason"] = str(debate_payload.get("fallback_reason"))
        generation_metadata["transcript"] = [
            {
                "role": str(item.get("role") or "").strip() or "unknown",
                "semantic_role": str(item.get("semantic_role") or "").strip() or None,
                "provider": str(item.get("provider") or "").strip().lower() or None,
                "model": str(item.get("model") or "").strip() or None,
                "output_summary": str(item.get("output_summary") or "").strip() or None,
                "token_usage": _normalize_usage_payload(
                    item.get("token_usage") if isinstance(item.get("token_usage"), dict) else None
                ),
                "latency_ms": float(item.get("latency_ms") or 0.0),
                "routing_mode": str(item.get("routing_mode") or "").strip() or None,
                "route_reason": str(item.get("route_reason") or "").strip() or None,
                "requested_tier": str(item.get("requested_tier") or "").strip() or None,
                "execution_tier": str(item.get("execution_tier") or "").strip() or None,
            }
            for item in transcript
            if isinstance(item, dict)
        ]
    return generation_metadata


def _append_track_b_transcript_entries(
    ai_generation_metadata: dict[str, object],
    dual_track_shadow: dict[str, Any] | None,
) -> dict[str, object]:
    if not isinstance(ai_generation_metadata, dict):
        return ai_generation_metadata
    if str(ai_generation_metadata.get("mode") or "").strip().lower() != "specialist_synthesis":
        return ai_generation_metadata
    if not isinstance(dual_track_shadow, dict):
        return ai_generation_metadata

    transcript = ai_generation_metadata.get("transcript")
    if not isinstance(transcript, list):
        return ai_generation_metadata

    claims = dual_track_shadow.get("claims")
    if not isinstance(claims, list):
        return ai_generation_metadata

    appended_entries: list[dict[str, object]] = []
    total_usage = _normalize_usage_payload(
        ai_generation_metadata.get("usage")
        if isinstance(ai_generation_metadata.get("usage"), dict)
        else None
    )

    for claim in claims:
        if not isinstance(claim, dict):
            continue
        if str(claim.get("track") or "").strip().lower() != "track_b":
            continue
        if str(claim.get("judge_mode") or "").strip().lower() != "llm_shadow":
            continue
        usage = _normalize_usage_payload(
            claim.get("judge_usage") if isinstance(claim.get("judge_usage"), dict) else None
        )
        if usage["total_tokens"] <= 0:
            continue
        entry = {
            "role": "track_b_judge",
            "claim_id": str(claim.get("claim_id") or "").strip() or None,
            "provider": str(claim.get("judge_provider") or "").strip().lower() or None,
            "model": str(claim.get("judge_model") or "").strip() or None,
            "output_summary": (
                f"Track B judge result for {str(claim.get('claim_id') or '').strip() or 'claim'}"
            ),
            "token_usage": usage,
            "latency_ms": float(claim.get("judge_latency_ms") or 0.0),
            "requested_tier": "deep_judgment",
            "execution_tier": "smart",
        }
        appended_entries.append(entry)
        total_usage["prompt_tokens"] += usage["prompt_tokens"]
        total_usage["completion_tokens"] += usage["completion_tokens"]
        total_usage["total_tokens"] += usage["total_tokens"]

    if not appended_entries:
        return ai_generation_metadata

    transcript.extend(appended_entries)
    ai_generation_metadata["usage"] = total_usage
    return ai_generation_metadata


def _append_post_processing_transcript_entries(
    ai_generation_metadata: dict[str, object],
    transcript_entries: list[dict[str, object]] | None,
) -> dict[str, object]:
    if not isinstance(ai_generation_metadata, dict):
        return ai_generation_metadata

    normalized_entries = [entry for entry in (transcript_entries or []) if isinstance(entry, dict)]
    if not normalized_entries:
        return ai_generation_metadata

    total_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for entry in normalized_entries:
        usage = _normalize_usage_payload(
            entry.get("token_usage") if isinstance(entry.get("token_usage"), dict) else None
        )
        total_usage["prompt_tokens"] += usage["prompt_tokens"]
        total_usage["completion_tokens"] += usage["completion_tokens"]
        total_usage["total_tokens"] += usage["total_tokens"]

    ai_generation_metadata["post_processing_transcript"] = normalized_entries
    ai_generation_metadata["post_processing_usage"] = total_usage
    return ai_generation_metadata


def _synthesize_dual_track_claim_verifications(
    ai_analysis_results: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    extracted_claims = HallucinationService().extract_claim_candidates(ai_analysis_results)
    synthesized_claims: list[dict[str, Any]] = []

    for index, item in enumerate(extracted_claims, start=1):
        claim_text = str(item.get("text") or "").strip()
        if not claim_text:
            continue

        track = str(item.get("track") or "").strip().lower()
        if track not in {"track_b", "mixed"}:
            continue

        classification_basis = (
            list(item.get("classification_basis"))
            if isinstance(item.get("classification_basis"), list)
            else []
        )
        premise_refs = (
            list(item.get("premise_refs")) if isinstance(item.get("premise_refs"), list) else []
        )
        synthesized_claims.append(
            {
                "claim_id": str(item.get("id") or f"canonical-claim-{index}").strip()
                or f"canonical-claim-{index}",
                "claim_text": claim_text,
                "field_path": str(item.get("field_path") or "").strip() or None,
                "field_label": str(item.get("field_label") or "").strip() or None,
                "track": track,
                "classification_basis": classification_basis,
                "premise_refs": premise_refs,
                "disposition": "supported",
                "hallucination": False,
                "certainty_score": 1.0,
                "evidence_refs": [],
            }
        )

    return synthesized_claims


def _resolve_dual_track_claim_verifications(
    *,
    hallucination_result: dict[str, Any] | None,
    ai_analysis_results: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str | None]:
    normalized_claims: list[dict[str, Any]] = []
    if isinstance(hallucination_result, dict):
        for key in ("claim_verifications", "claims"):
            raw_claims = hallucination_result.get(key)
            if not isinstance(raw_claims, list):
                continue
            normalized_claims = [dict(item) for item in raw_claims if isinstance(item, dict)]
            if not normalized_claims:
                continue
            if any(
                str(item.get("track") or "").strip().lower() in {"track_b", "mixed"}
                for item in normalized_claims
            ):
                return normalized_claims, "hallucination_verifications"
            break

    synthesized_claims = _synthesize_dual_track_claim_verifications(ai_analysis_results)
    if synthesized_claims:
        return [*normalized_claims, *synthesized_claims], "canonical_analysis_fallback"

    if normalized_claims:
        return normalized_claims, "hallucination_verifications"

    return [], None


def _finalize_hallucination_result(
    hallucination_result: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any] | None]:
    if not isinstance(hallucination_result, dict):
        return hallucination_result, [], None

    claim_verifications = hallucination_result.get("claim_verifications")
    high_risk_discrepancies: list[dict[str, Any]] = []
    if isinstance(claim_verifications, list):
        for claim in claim_verifications:
            if not isinstance(claim, dict):
                continue
            discrepancy_type = str(claim.get("discrepancy_type") or "general_mismatch")
            severity = str(
                claim.get("severity") or ("medium" if claim.get("hallucination") else "none")
            ).lower()
            claim["discrepancy_type"] = discrepancy_type
            claim["severity"] = severity
            if claim.get("hallucination") and severity in {"high", "critical"}:
                high_risk_discrepancies.append(claim)

    hallucination_result["high_risk_discrepancies"] = high_risk_discrepancies
    sanitized_analysis = (
        hallucination_result.get("sanitized_analysis")
        if isinstance(hallucination_result.get("sanitized_analysis"), dict)
        else None
    )
    return hallucination_result, high_risk_discrepancies, sanitized_analysis


def _resolve_forbidden_brand_facts(
    db: Session | None,
    project_id: int | None,
) -> list[str]:
    """Per-project FORBIDDEN brand-fact statements for the additive guardrail.

    Defensive and additive: returns ``[]`` when there is no db/project, no
    forbidden facts, or on any failure — so absence is a strict no-op and a
    missing guardrails table can never break a live audit. The statements are
    layered ON TOP of source-content grounding (never via the brand_truth
    short-circuit) and never alter a threshold.
    """
    if not isinstance(db, Session) or project_id is None:
        return []
    try:
        from app.services.brand_facts_service import get_brand_facts_evidence

        items = get_brand_facts_evidence(db, project_id)
    except Exception:
        logger.warning(
            "Forbidden brand facts unavailable for project_id=%s",
            project_id,
            exc_info=True,
        )
        return []
    return [
        str(item.get("statement") or "").strip()
        for item in items
        if isinstance(item, dict)
        and item.get("is_forbidden")
        and str(item.get("statement") or "").strip()
    ]


async def _to_canonical_suggestions(
    *,
    unified_suggestions: list[dict[str, Any]],
    ai_client,
    provider: str,
    tier: str,
    market: str,
    language: str,
    page_type: str | None = None,
    page_type_label: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    canonical: list[dict[str, Any]] = []
    post_processing_transcript: list[dict[str, object]] = []
    normalized_tier = normalize_audit_tier(tier)
    for index, suggestion in enumerate(unified_suggestions, start=1):
        action = str(suggestion.get("action") or "").strip()
        if not action:
            continue
        enriched = await ai_client.generate_suggestion_detail(
            provider=provider,
            tier=tier,
            suggestion=action,
            market=market,
            language=language,
            page_type=page_type,
            page_type_label=page_type_label,
        )
        short_title = str((enriched or {}).get("short_title") or action).strip() or action
        detailed_action = (
            str((enriched or {}).get("comprehensive_action") or action).strip() or action
        )
        category_raw = str((enriched or {}).get("category") or "").strip().lower()
        # No fabricated category: absent enrichment classification stays null,
        # matching the explicit-null pattern of expected_score_impact.
        category = {"technical": "Technical", "content": "Content", "backlinks": "Backlinks"}.get(
            category_raw
        )
        detail_usage = _normalize_usage_payload(
            (enriched or {}).get("usage")
            if isinstance((enriched or {}).get("usage"), dict)
            else None
        )
        if detail_usage["total_tokens"] > 0:
            post_processing_transcript.append(
                {
                    "role": "suggestion_detail",
                    "semantic_role": "post_processing",
                    "provider": str((enriched or {}).get("provider") or provider or "")
                    .strip()
                    .lower()
                    or None,
                    "model": str((enriched or {}).get("model") or "").strip() or None,
                    "operation": "generate_suggestion_detail",
                    "output_summary": short_title[:200] if short_title else action[:200],
                    "token_usage": detail_usage,
                    "latency_ms": float((enriched or {}).get("latency_ms") or 0.0),
                    "requested_tier": normalized_tier,
                    "execution_tier": normalized_tier,
                    "suggestion_priority": index,
                }
            )
        rationale = str((enriched or {}).get("rationale") or "").strip() or None
        if not rationale:
            justification = str(suggestion.get("justification") or "").strip()
            if justification and justification != "Direct recommendation from AI analysis.":
                rationale = justification
        estimated_effort = str((enriched or {}).get("estimated_effort") or "").strip().lower()
        if estimated_effort not in {"low", "medium", "high"}:
            candidate_effort = str(suggestion.get("effort") or "").strip().lower()
            estimated_effort = (
                candidate_effort if candidate_effort in {"low", "medium", "high"} else None
            )
        owner = str((enriched or {}).get("owner") or "").strip().lower()
        if owner not in {"engineering", "content", "seo", "marketing"}:
            owner = "engineering"
        confidence = str((enriched or {}).get("confidence") or "").strip().lower()
        if confidence not in {"low", "medium", "high"}:
            confidence = "medium"
        affected_scores_raw = (enriched or {}).get("affected_scores")
        valid_dims = {"seo", "geo", "aeo"}
        if isinstance(affected_scores_raw, list):
            affected_scores = [
                s
                for s in affected_scores_raw
                if isinstance(s, str) and s.strip().lower() in valid_dims
            ]
        else:
            affected_scores = []
        # Empty stays empty: a fabricated ["seo"] would assert a score-leverage
        # claim nobody measured.

        # Extract expected_score_impact from enriched detail
        raw_impact = (enriched or {}).get("expected_score_impact")
        expected_score_impact = (
            raw_impact
            if isinstance(raw_impact, dict)
            else {"seo": None, "geo": None, "aeo": None, "overall": None}
        )

        # The enrichment call above rewrote title and action, which is exactly
        # why identity cannot live in that text. ``problem_code`` was attached
        # by the deterministic channel before this call and is carried over
        # verbatim, along with the grounding reference naming the failed check.
        problem_code = normalize_problem_code(suggestion.get("problem_code"))
        canonical.append(
            {
                "priority": index,
                "title": short_title,
                "action": detailed_action,
                "category": category,
                "rationale": rationale,
                "summary": detailed_action[:200] if detailed_action else None,
                "estimated_effort": estimated_effort,
                "owner": owner,
                "confidence": confidence,
                "cross_score_leverage": affected_scores,
                "expected_score_impact": expected_score_impact,
                "problem_code": problem_code,
                "grounded_by_findings": list(suggestion.get("grounded_by_findings") or []),
                "derived_from": list(suggestion.get("derived_from") or []),
            }
        )
    return canonical, post_processing_transcript


_POSITIVE_FINDING_SIGNALS = frozenset(
    {
        "already",
        "present",
        "exists",
        "configured",
        "implemented",
        "valid",
        "correct",
        "properly",
        "detected",
        "good",
        "enabled",
        "strong",
        "adequate",
        "sufficient",
        "healthy",
        "compliant",
    }
)
_NEGATIVE_REC_SIGNALS = frozenset(
    {
        "add",
        "implement",
        "create",
        "missing",
        "install",
        "enable",
        "include",
        "introduce",
        "set up",
        "configure",
        "fix",
        "repair",
    }
)


def _is_contradicted(recommendation_text: str, finding_desc: str) -> bool:
    """Return True when a finding confirms presence but the rec asks to add it."""
    rec_words = set(recommendation_text.split())
    finding_words = set(finding_desc.split())
    finding_has_positive = bool(finding_words & _POSITIVE_FINDING_SIGNALS)
    rec_has_negative = bool(rec_words & _NEGATIVE_REC_SIGNALS)
    return finding_has_positive and rec_has_negative


def _ground_suggestions_to_findings(
    suggestions: list[dict[str, object]],
    findings: dict[str, list[dict[str, object]]],
) -> list[dict[str, object]]:
    """Link recommendations to their source findings via keyword overlap.

    Skips matches where the finding indicates the issue is already resolved
    (positive polarity) but the recommendation asks to add/fix it (negative
    polarity), i.e. semantic contradictions.

    Keyword matches are MERGED into any references the suggestion already
    carries: a deterministic problem candidate arrives grounded in the failed
    check that produced it, and that reference must survive, since it is the
    only non-positional evidence pointer in the report.
    """
    all_findings: list[tuple[str, str, str]] = []
    for domain, domain_findings in findings.items():
        for idx, finding in enumerate(domain_findings):
            desc = str(finding.get("description") or "").lower()
            cat = str(finding.get("category") or "").lower()
            finding_id = f"{domain}.finding.{idx + 1}"
            all_findings.append((finding_id, desc, cat))

    for suggestion in suggestions:
        action_text = str(suggestion.get("action") or "").lower()
        title_text = str(suggestion.get("title") or "").lower()
        combined = f"{title_text} {action_text}"

        matched_ids = []
        for finding_id, desc, cat in all_findings:
            words_in_common = sum(1 for word in combined.split() if len(word) > 3 and word in desc)
            keyword_match = words_in_common >= 2 or (cat and len(cat) > 3 and cat in combined)
            if keyword_match and not _is_contradicted(combined, desc):
                matched_ids.append(finding_id)

        if matched_ids:
            suggestion["grounded_by_findings"] = _merge_refs(
                suggestion.get("grounded_by_findings"), matched_ids, limit=5
            )
            suggestion["derived_from"] = _merge_refs(
                suggestion.get("derived_from"), matched_ids, limit=3
            )
    return suggestions


def _merge_refs(existing: object, matched_ids: list[str], *, limit: int) -> list[str]:
    """Return existing references first, then new matches, deduped and capped."""
    merged: list[str] = []
    for ref in list(existing or []) + list(matched_ids):
        text = str(ref).strip()
        if text and text not in merged:
            merged.append(text)
    return merged[:limit]


def _analysis_module_suggestions(analysis_payload: dict) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    for score_key in ("seo_score", "geo_score", "aeo_score"):
        score_payload = analysis_payload.get(score_key)
        if not isinstance(score_payload, dict):
            continue
        for list_key in ("suggestions", "recommendations", "items", "findings"):
            entries = score_payload.get(list_key)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, str) and entry.strip():
                    suggestions.append(
                        {
                            "action": entry.strip(),
                            "impact": "medium",
                            "effort": None,
                            "justification": f"Derived from {score_key} {list_key}.",
                        }
                    )
                elif isinstance(entry, dict):
                    suggestions.append(entry)
    return suggestions


def _empty_performance_metrics(message: str) -> dict:
    return {
        "status": "error",
        "message": message,
        "performance_score": 0,
        "first_contentful_paint": "N/A",
        "largest_contentful_paint": "N/A",
        "speed_index": "N/A",
        "total_blocking_time": "N/A",
        "interaction_to_next_paint": "N/A",
        "cumulative_layout_shift": "N/A",
        "seo_status": "disabled",
        "seo_error": message,
    }


def _sanitize_performance_for_ai(metrics: dict, scrape_ok: bool) -> dict:
    """Return a copy of *metrics* safe for AI context injection.

    When the page was successfully scraped but PageSpeed Insights timed out or
    errored, the raw error payload (``"status": "error", "message": "…timed
    out…"``) can mislead the AI into claiming the page is down.  Replace the
    error details with a neutral note so the AI doesn't hallucinate
    catastrophic findings.
    """
    if not isinstance(metrics, dict):
        return metrics
    status = str(metrics.get("status") or "").strip().lower()
    if status not in ("error", "timeout") or not scrape_ok:
        return metrics
    sanitized = dict(metrics)
    sanitized["status"] = "unavailable"
    sanitized["message"] = (
        "Performance measurement was unavailable for this page. "
        "This does NOT indicate the page is down or broken, "
        "it means the Lighthouse tool could not be reached. "
        "Do NOT generate findings about server errors, timeouts, or the page being unreachable."
    )
    return sanitized


SCRAPER_TOOL_LABELS = {
    "firecrawl": "Firecrawl Scraper",
    "fallback": "Fallback Scraper (httpx)",
}


def _resolve_scraper_label(scrape_method: object) -> str:
    """Return the report label for the scraper that actually fetched the page.

    The label is handed to the model as evidence-provenance context, so it must
    describe the fetch that really happened. Only "firecrawl" and "fallback"
    exist today, but new methods are expected, and silently reporting an
    unknown method as the httpx fallback would be another false claim, so
    unrecognised values are echoed back instead of collapsing into a two-way
    branch.
    """
    method = str(scrape_method or "").strip().lower()
    if not method:
        return "Unknown Scraper"
    known_label = SCRAPER_TOOL_LABELS.get(method)
    if known_label:
        return known_label
    return f"{method.replace('_', ' ').title()} Scraper"


def _empty_network_metrics() -> dict:
    return {
        "http_version": "Unknown",
        "supports_http2": False,
        "supports_http3_inferred": False,
    }


def _infer_market(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().strip()
    if not host:
        return "global"

    host_parts = [part for part in host.split(".") if part and part != "www"]
    if not host_parts:
        return "global"

    country_like = host_parts[-1] if len(host_parts[-1]) == 2 else ""
    geography_tokens = {
        "atlanta",
        "new-york",
        "newyork",
        "london",
        "paris",
        "berlin",
        "toronto",
        "bucharest",
        "cluj",
        "timisoara",
        "iasi",
        "chicago",
        "dallas",
        "miami",
        "los-angeles",
        "seattle",
    }
    for token in reversed(host_parts[:-1]):
        if token in geography_tokens:
            return token.replace("-", " ")
        if country_like and len(token) in (2, 3):
            return f"{token}-{country_like}".strip("-")

    path_segments = [segment for segment in (parsed.path or "").split("/") if segment]
    if path_segments:
        segment = path_segments[0].lower()
        if segment in geography_tokens:
            return segment.replace("-", " ")

    return "global"


def _infer_language_from_content(page_content: str | None, metadata: dict | None) -> str | None:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    for key in ("language", "lang"):
        value = normalized_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    locale = normalized_metadata.get("locale")
    if isinstance(locale, str) and locale.strip():
        locale_text = locale.strip().lower().replace("_", "-")
        return locale_text.split("-", 1)[0]

    content = page_content or ""
    html_lang_match = re.search(
        r"<html[^>]*\blang\s*=\s*[\"']?([a-zA-Z-]{2,12})", content, re.IGNORECASE
    )
    if html_lang_match:
        return html_lang_match.group(1).strip().lower().split("-", 1)[0]

    meta_locale_match = re.search(
        r"(?:og:locale|content-language)\s*[\"'=:>\s]+([a-zA-Z]{2}(?:[_-][a-zA-Z]{2})?)",
        content,
        re.IGNORECASE,
    )
    if meta_locale_match:
        return meta_locale_match.group(1).strip().lower().replace("_", "-").split("-", 1)[0]

    return None


def _infer_market_from_content(url: str, page_content: str | None, metadata: dict | None) -> str:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    for key in ("market", "country", "region"):
        value = normalized_metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    locale = normalized_metadata.get("locale")
    if isinstance(locale, str) and locale.strip():
        locale_text = locale.strip().lower().replace("_", "-")
        locale_parts = [part for part in locale_text.split("-") if part]
        if len(locale_parts) >= 2 and len(locale_parts[1]) == 2:
            return locale_parts[1]

    content = page_content or ""
    content_locale_match = re.search(
        r"(?:og:locale|content-language)\s*[\"'=:>\s]+([a-zA-Z]{2})[_-]([a-zA-Z]{2})",
        content,
        re.IGNORECASE,
    )
    if content_locale_match:
        return content_locale_match.group(2).strip().lower()

    return _infer_market(url)


def _infer_category(
    *,
    url: str,
    page_content: str | None = None,
    title: str | None = None,
    headings: list[str] | None = None,
) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or ""
    heading_text = " ".join(
        item for item in (headings or []) if isinstance(item, str) and item.strip()
    )
    signal_text = " ".join(
        part for part in (host, path, title or "", heading_text, page_content or "") if part
    ).lower()
    signal_text = re.sub(r"\s+", " ", signal_text)

    best_category = "general"
    best_score = 0
    for category, keywords in CATEGORY_INFERENCE_SIGNALS.items():
        score = sum(1 for keyword in keywords if keyword in signal_text)
        if score > best_score:
            best_score = score
            best_category = category
    return best_category


# ---------------------------------------------------------------------------
# Thin / placeholder content detection
# ---------------------------------------------------------------------------

# Phrases that indicate a page is a stub or placeholder
_PLACEHOLDER_PHRASES = re.compile(
    r"no\s+(?:published|available)\s+\w+(?:\s+\w+)*\s+yet"
    r"|coming\s+soon"
    r"|under\s+construction"
    r"|page\s+not\s+found"
    r"|this\s+page\s+is\s+empty"
    r"|content\s+coming\s+soon"
    r"|nothing\s+(?:here|to\s+show)\s+yet",
    re.IGNORECASE,
)

_THIN_CONTENT_WORD_THRESHOLD = 50  # pages with fewer meaningful words are thin


def _detect_thin_content(markdown_content: str | None) -> dict | None:
    """Return a thin-content descriptor dict if the page is too thin for meaningful audit, else None."""
    if not markdown_content or not markdown_content.strip():
        return {"is_thin": True, "reason": "empty_page", "word_count": 0}

    # Strip markdown boilerplate (links, images, headers markup) for word counting
    text = re.sub(r"[#*\[\]()!`>|_\-=]", " ", markdown_content)
    words = text.split()
    word_count = len(words)

    if word_count < _THIN_CONTENT_WORD_THRESHOLD:
        placeholder_match = _PLACEHOLDER_PHRASES.search(markdown_content)
        reason = "placeholder_page" if placeholder_match else "insufficient_content"
        return {"is_thin": True, "reason": reason, "word_count": word_count}

    # Even if above threshold, check for placeholder phrases
    placeholder_match = _PLACEHOLDER_PHRASES.search(markdown_content)
    if placeholder_match and word_count < 150:
        return {"is_thin": True, "reason": "placeholder_page", "word_count": word_count}

    return None


def _discovery_context(
    url: str,
    page_content: str | None = None,
    *,
    title: str | None = None,
    headings: list[str] | None = None,
    category_override: str | None = None,
    market_override: str | None = None,
) -> tuple[str, str]:
    category = (
        category_override.strip()
        if isinstance(category_override, str) and category_override.strip()
        else _infer_category(
            url=url,
            page_content=page_content,
            title=title,
            headings=headings,
        )
    )
    market = (
        market_override.strip()
        if isinstance(market_override, str) and market_override.strip()
        else _infer_market(url)
    )
    return category, market


def _resolve_audit_intent_query(url: str, metadata: dict | None, category: str) -> str:
    normalized_metadata = metadata if isinstance(metadata, dict) else {}
    query_candidate = normalized_metadata.get("query") or normalized_metadata.get("search_query")
    if isinstance(query_candidate, str) and query_candidate.strip():
        return query_candidate.strip()

    title = normalized_metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    return f"{url} {category}".strip()


def _has_numeric_score_value(analysis: dict, score_key: str) -> bool:
    if not isinstance(analysis, dict) or score_key not in analysis:
        return False
    score_value = analysis.get(score_key)
    if isinstance(score_value, dict):
        score_value = score_value.get("score")
    try:
        float(score_value)
    except (TypeError, ValueError):
        return False
    return True


def _scores_available_from_analysis(analysis: dict) -> bool:
    return any(
        _has_numeric_score_value(analysis, score_key)
        for score_key in ("seo_score", "geo_score", "aeo_score")
    )


def ai_scored_dimensions(analysis: dict) -> dict[str, bool]:
    """Which pillars the model actually produced a usable number for.

    ``extract_score`` coerces a missing or unparseable pillar to ``0.0``,
    which is indistinguishable from a model that assessed the pillar and
    scored it zero. Anything that weights the AI score needs the difference.
    """
    return {
        dim: _has_numeric_score_value(analysis, f"{dim}_score") for dim in ("seo", "geo", "aeo")
    }


def blend_pillar_score(
    *,
    deterministic: object,
    ai: object,
    ai_scored: bool,
    det_weight: float,
    ai_weight: float,
) -> float | None:
    """One pillar's published score, or ``None`` to leave it unchanged.

    A pillar the model did not score keeps its deterministic value. Until
    this, a single numeric pillar switched the blend on for all three and the
    absent ones arrived as ``0.0``, so a deterministic SEO of 80 published 56
    whenever the model happened to omit its SEO score: a 24-point penalty for
    the model's silence, on the dimension nobody assessed. It also made the
    same unchanged site score differently run to run, purely on whether the
    model emitted every pillar.
    """
    if not ai_scored:
        return None
    if not isinstance(ai, (int, float)) or not isinstance(deterministic, (int, float)):
        return None
    blended = round(det_weight * float(deterministic) + ai_weight * float(ai), 1)
    return max(0.0, min(100.0, blended))


def canonical_score_breakdown(full_report: dict | None) -> dict[str, float]:
    if not isinstance(full_report, dict):
        return {"seo": 0.0, "geo": 0.0, "aeo": 0.0, "overall": 0.0}

    scores = full_report.get("scores") if isinstance(full_report.get("scores"), dict) else {}

    def _as_float(value: object) -> float:
        try:
            # Clamp every persisted score into the valid [0, 100] range so a
            # malformed blend or AI payload can never write an out-of-range
            # score to the audit table columns.
            return max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            return 0.0

    score_breakdown = {
        "seo": _as_float(scores.get("seo")),
        "geo": _as_float(scores.get("geo")),
        "aeo": _as_float(scores.get("aeo")),
    }
    score_breakdown["overall"] = _as_float(
        scores.get("overall")
        if scores.get("overall") is not None
        # Weighted overall: SEO 40% + AEO 30% + GEO 30%
        else DeterministicScoringEngine.calculate_overall_score(score_breakdown)
    )
    return score_breakdown


def _normalize_ai_error_payload(payload: object) -> dict:
    if isinstance(payload, dict):
        return payload
    return {"detail": str(payload)}


def _validation_error_operator_detail(error_payload: dict) -> str:
    subtype = error_payload.get("error_subtype")
    source = error_payload.get("source")
    parts = ["AI analysis could not be completed due to invalid upstream request handling"]
    if isinstance(subtype, str) and subtype.strip():
        parts.append(f"subtype={subtype.strip()}")
    if isinstance(source, str) and source.strip():
        parts.append(f"source={source.strip()}")
    return "; ".join(parts)


_BENCHMARK_METRICS = ("geo_visibility", "aeo_score", "entity_strength")
_BENCHMARK_COLUMNS = [
    {"key": "rank", "label": "Rank", "type": "number"},
    {"key": "name", "label": "Brand", "type": "text"},
    {"key": "geo_visibility", "label": "GEO Visibility", "type": "score"},
    {"key": "aeo_score", "label": "AEO Score", "type": "score"},
    {"key": "entity_strength", "label": "Entity Strength", "type": "score"},
    {"key": "overall_score", "label": "Overall", "type": "score"},
]


def _normalize_competitor_identity(value: object) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""

    looks_like_domain = raw_value.startswith(("http://", "https://")) or (
        "." in raw_value and " " not in raw_value
    )
    if looks_like_domain:
        parsed = urlparse(
            raw_value if raw_value.startswith(("http://", "https://")) else f"https://{raw_value}"
        )
        host = (parsed.hostname or parsed.path or "").strip().lower()
        if host.startswith("www."):
            host = host[4:]
        if host:
            return host

    return re.sub(r"\s+", " ", raw_value).strip().lower()


def _benchmark_metric(value: float | int | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(100.0, float(value))), 2)


def _benchmark_overall_score(metrics: dict[str, float | None]) -> float | None:
    values = [float(value) for value in metrics.values() if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _empty_benchmark_deltas() -> dict[str, None]:
    return {metric: None for metric in _BENCHMARK_METRICS}


def _benchmark_confidence_label(value: float | None) -> str:
    if value is None:
        return "low"
    if value >= 0.8:
        return "high"
    if value >= 0.6:
        return "medium"
    return "low"


def _latest_project_snapshots_by_competitor(
    db: Session,
    *,
    project_id: int,
) -> dict[int, models.ProjectCompetitorSnapshot]:
    snapshots = (
        db.query(models.ProjectCompetitorSnapshot)
        .filter(
            models.ProjectCompetitorSnapshot.project_id == project_id,
            models.ProjectCompetitorSnapshot.status == "succeeded",
        )
        .order_by(
            models.ProjectCompetitorSnapshot.competitor_id.asc(),
            models.ProjectCompetitorSnapshot.captured_at.desc().nullslast(),
            models.ProjectCompetitorSnapshot.updated_at.desc().nullslast(),
            models.ProjectCompetitorSnapshot.id.desc(),
        )
        .all()
    )

    latest_by_competitor: dict[int, models.ProjectCompetitorSnapshot] = {}
    for snapshot in snapshots:
        latest_by_competitor.setdefault(snapshot.competitor_id, snapshot)
    return latest_by_competitor


def _latest_project_audits_by_host(
    db: Session,
    *,
    project_id: int,
) -> dict[str, models.Audit]:
    """Latest competitor-side audit per host, for grounding benchmark rows.

    SIGV2-1117: this lookup exists to ground a discovered competitor in a real
    measurement, so it reads the competitor-scoped audits positively. Without the
    clause a candidate whose name resolves to the project's own host would ground
    a benchmark row in the project's own scores.
    """
    audits = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, competitor_audit_clause())
        .order_by(models.Audit.created_at.desc().nullslast(), models.Audit.id.desc())
        .all()
    )

    latest_by_host: dict[str, models.Audit] = {}
    for audit in audits:
        host_key = _normalize_competitor_identity(audit.url)
        if host_key and host_key not in latest_by_host:
            latest_by_host[host_key] = audit
    return latest_by_host


def _build_target_benchmark_metrics(
    *,
    target_name: str,
    score_breakdown: dict[str, float],
) -> dict[str, float | str]:
    return {
        "name": target_name,
        "geo_visibility": _benchmark_metric(score_breakdown.get("geo")) or 0.0,
        "aeo_score": _benchmark_metric(score_breakdown.get("aeo")) or 0.0,
        # The legacy benchmark table uses entity_strength as the SEO axis in the audit UI.
        "entity_strength": _benchmark_metric(score_breakdown.get("seo")) or 0.0,
    }


def _build_grounded_competitor_row_from_snapshot(
    *,
    candidate: dict[str, Any],
    snapshot: models.ProjectCompetitorSnapshot,
) -> dict[str, Any] | None:
    metrics = {
        "geo_visibility": _benchmark_metric(snapshot.geo_score),
        "aeo_score": _benchmark_metric(snapshot.aeo_score),
        "entity_strength": _benchmark_metric(snapshot.seo_score),
    }
    if any(value is None for value in metrics.values()):
        return None

    return {
        "name": str(candidate.get("name") or "").strip(),
        **metrics,
        "measurement_source": "project_snapshot",
        "captured_at": snapshot.captured_at.isoformat() if snapshot.captured_at else None,
        "source_audit_id": snapshot.source_audit_id,
        "competitor_audit_id": snapshot.competitor_audit_id,
        "confidence_label": "high",
        "confidence_score": 1.0,
        "exploratory": False,
        "source": str(candidate.get("source") or "tracked competitor"),
    }


def _build_grounded_competitor_row_from_audit(
    *,
    candidate: dict[str, Any],
    audit: models.Audit,
) -> dict[str, Any] | None:
    metrics = {
        "geo_visibility": _benchmark_metric(audit.geo_score),
        "aeo_score": _benchmark_metric(audit.aeo_score),
        "entity_strength": _benchmark_metric(audit.seo_score),
    }
    if any(value is None for value in metrics.values()):
        return None

    return {
        "name": str(candidate.get("name") or "").strip(),
        **metrics,
        "measurement_source": "audited_competitor_crawl",
        "captured_at": audit.created_at.isoformat() if audit.created_at else None,
        "source_audit_id": audit.id,
        "competitor_audit_id": audit.id,
        "confidence_label": "high",
        "confidence_score": 1.0,
        "exploratory": False,
        "source": str(candidate.get("source") or "tracked competitor"),
    }


def _resolve_grounded_competitor_rows(
    *,
    db: Session | None,
    project_id: int | None,
    discovered_competitors: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if db is None or project_id is None or not discovered_competitors:
        return [], list(discovered_competitors)

    project = db.query(models.Project).filter(models.Project.id == project_id).first()
    if project is None:
        return [], list(discovered_competitors)

    latest_snapshots_by_competitor = _latest_project_snapshots_by_competitor(
        db, project_id=project_id
    )
    latest_audits_by_host = _latest_project_audits_by_host(db, project_id=project_id)

    competitors_by_key: dict[str, models.ProjectCompetitor] = {}
    for competitor in project.competitors:
        keys = {
            _normalize_competitor_identity(competitor.display_name),
            _normalize_competitor_identity(competitor.normalized_domain),
            _normalize_competitor_identity(competitor.target_url),
        }
        for key in keys:
            if key and key not in competitors_by_key:
                competitors_by_key[key] = competitor

    grounded_rows: list[dict[str, Any]] = []
    exploratory_candidates: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    for candidate in discovered_competitors:
        candidate_name = str(candidate.get("name") or "").strip()
        candidate_key = _normalize_competitor_identity(candidate_name)
        if not candidate_name or not candidate_key:
            continue

        grounded_row: dict[str, Any] | None = None
        project_competitor = competitors_by_key.get(candidate_key)
        if project_competitor is not None:
            latest_snapshot = latest_snapshots_by_competitor.get(project_competitor.id)
            if latest_snapshot is not None:
                grounded_row = _build_grounded_competitor_row_from_snapshot(
                    candidate=candidate,
                    snapshot=latest_snapshot,
                )

            if grounded_row is None:
                latest_audit = latest_audits_by_host.get(
                    _normalize_competitor_identity(project_competitor.normalized_domain)
                )
                if latest_audit is not None:
                    grounded_row = _build_grounded_competitor_row_from_audit(
                        candidate=candidate,
                        audit=latest_audit,
                    )
        else:
            latest_audit = latest_audits_by_host.get(candidate_key)
            if latest_audit is not None:
                grounded_row = _build_grounded_competitor_row_from_audit(
                    candidate=candidate,
                    audit=latest_audit,
                )

        if grounded_row is None:
            exploratory_candidates.append(candidate)
            continue

        dedupe_key = _normalize_competitor_identity(grounded_row.get("name"))
        if dedupe_key in seen_names:
            continue
        seen_names.add(dedupe_key)
        grounded_rows.append(grounded_row)

    return grounded_rows, exploratory_candidates


def _build_benchmark_row(
    *,
    name: str,
    metrics: dict[str, float | None],
    target_metrics: dict[str, float],
    is_target: bool,
    measurement_source: str,
    confidence_label: str,
    confidence_score: float | None,
    exploratory: bool,
    source: str | None = None,
    captured_at: str | None = None,
    source_audit_id: int | None = None,
    competitor_audit_id: int | None = None,
) -> dict[str, Any]:
    deltas = (
        _empty_benchmark_deltas()
        if exploratory
        else {
            metric: round(float(metrics[metric]) - float(target_metrics[metric]), 2)
            if metrics.get(metric) is not None
            else None
            for metric in _BENCHMARK_METRICS
        }
    )
    return {
        "rank": None,
        "name": name,
        "is_target": is_target,
        **metrics,
        "overall_score": _benchmark_overall_score(metrics),
        "deltas_vs_target": deltas,
        "measurement_source": measurement_source,
        "confidence_label": confidence_label,
        "confidence_score": confidence_score,
        "exploratory": exploratory,
        "source": source,
        "captured_at": captured_at,
        "source_audit_id": source_audit_id,
        "competitor_audit_id": competitor_audit_id,
    }


def _build_exploratory_benchmark_row(candidate: dict[str, Any]) -> dict[str, Any]:
    confidence_score = max(0.0, min(1.0, float(candidate.get("confidence_score") or 0.0)))
    return _build_benchmark_row(
        name=str(candidate.get("name") or "").strip(),
        metrics={
            "geo_visibility": None,
            "aeo_score": None,
            "entity_strength": None,
        },
        target_metrics={
            "geo_visibility": 0.0,
            "aeo_score": 0.0,
            "entity_strength": 0.0,
        },
        is_target=False,
        measurement_source="discovery_estimate",
        confidence_label=_benchmark_confidence_label(confidence_score),
        confidence_score=confidence_score,
        exploratory=True,
        source=str(candidate.get("source") or "unknown"),
    ) | {
        "overall_score": round(confidence_score * 100.0, 2),
    }


def _build_competitor_benchmark_payload(
    *,
    target_name: str,
    target_metrics: dict[str, float],
    grounded_competitors: list[dict[str, Any]],
    exploratory_competitors: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    measured_rows = [
        _build_benchmark_row(
            name=target_name,
            metrics=target_metrics,
            target_metrics=target_metrics,
            is_target=True,
            measurement_source="current_audit",
            confidence_label="high",
            confidence_score=1.0,
            exploratory=False,
            source="current_audit",
        )
    ]
    for competitor in grounded_competitors:
        metrics = {
            metric: _benchmark_metric(competitor.get(metric)) for metric in _BENCHMARK_METRICS
        }
        if any(value is None for value in metrics.values()):
            continue
        measured_rows.append(
            _build_benchmark_row(
                name=str(competitor.get("name") or "").strip(),
                metrics=metrics,
                target_metrics=target_metrics,
                is_target=False,
                measurement_source=str(competitor.get("measurement_source") or "project_snapshot"),
                confidence_label=str(competitor.get("confidence_label") or "high"),
                confidence_score=float(competitor.get("confidence_score") or 1.0),
                exploratory=False,
                source=str(competitor.get("source") or "tracked competitor"),
                captured_at=str(competitor.get("captured_at") or "") or None,
                source_audit_id=(
                    int(competitor["source_audit_id"])
                    if competitor.get("source_audit_id") is not None
                    else None
                ),
                competitor_audit_id=(
                    int(competitor["competitor_audit_id"])
                    if competitor.get("competitor_audit_id") is not None
                    else None
                ),
            )
        )

    target_rank: int | None = None
    if len(measured_rows) > 1:
        measured_rows.sort(
            key=lambda row: float(row.get("overall_score") or 0.0),
            reverse=True,
        )
        for index, row in enumerate(measured_rows, start=1):
            row["rank"] = index
            if row.get("is_target"):
                target_rank = index
    else:
        measured_rows[0]["rank"] = None

    exploratory_rows = [
        _build_exploratory_benchmark_row(candidate)
        for candidate in sorted(
            exploratory_competitors,
            key=lambda item: float(item.get("confidence_score") or 0.0),
            reverse=True,
        )
        if str(candidate.get("name") or "").strip()
    ]

    mode = "grounded"
    confidence = "high"
    message: str | None = None
    if grounded_competitors and exploratory_rows:
        mode = "mixed"
        confidence = "medium"
        message = (
            "Measured competitive deltas are shown only for tracked competitor audits. "
            "Newly discovered brands remain exploratory until they have audited evidence."
        )
    elif exploratory_rows:
        mode = "exploratory"
        confidence = "low"
        message = (
            "Competitor discovery is exploratory for this audit. "
            "Run tracked competitor audits to unlock measured GEO, SEO, and AEO deltas."
        )

    benchmark = {
        "columns": list(_BENCHMARK_COLUMNS),
        "rows": [*measured_rows, *exploratory_rows],
        "summary": {
            "target": target_name,
            "competitor_count": len(grounded_competitors) + len(exploratory_rows),
            "target_rank": target_rank,
            "measured_competitor_count": len(grounded_competitors),
            "exploratory_competitor_count": len(exploratory_rows),
            "mode": mode,
            "confidence": confidence,
            "has_score_deltas": bool(grounded_competitors),
            "message": message,
        },
    }
    return benchmark, benchmark["summary"]


def get_top_site_competitors(db: Session, *, site_id: int, limit: int = 3) -> list[models.Site]:
    """Return associated competitors ordered by their latest known audit score."""
    if limit <= 0:
        return []

    latest_competitor_audits = (
        db.query(
            models.Audit.site_id.label("site_id"),
            func.max(models.Audit.created_at).label("latest_created_at"),
        )
        .group_by(models.Audit.site_id)
        .subquery()
    )

    latest_competitor_scores = (
        db.query(
            models.Audit.site_id.label("site_id"),
            models.Audit.geo_score.label("geo_score"),
        )
        .join(
            latest_competitor_audits,
            (models.Audit.site_id == latest_competitor_audits.c.site_id)
            & (models.Audit.created_at == latest_competitor_audits.c.latest_created_at),
        )
        .subquery()
    )

    return (
        db.query(models.Site)
        .join(
            models.site_competitors, models.site_competitors.c.competitor_site_id == models.Site.id
        )
        .outerjoin(latest_competitor_scores, latest_competitor_scores.c.site_id == models.Site.id)
        .filter(models.site_competitors.c.site_id == site_id)
        .order_by(
            latest_competitor_scores.c.geo_score.desc().nullslast(),
            models.Site.domain.asc(),
        )
        .limit(limit)
        .all()
    )


async def _build_embedding_cache(
    *,
    ai_client,
    hallucination_service: HallucinationService,
    markdown_content: str,
    ai_analysis_results: dict[str, Any],
) -> EmbeddingCache | None:
    """Pre-compute dense embeddings for evidence chunks and claim texts.

    Returns a warmed ``EmbeddingCache`` or ``None`` when the AI client
    does not support embeddings.
    """
    if not hasattr(ai_client, "embed_texts"):
        return None

    chunks = hallucination_service._chunk_text(markdown_content)
    claim_items = hallucination_service._extract_claim_items(ai_analysis_results)
    claim_texts = [c["text"] for c in claim_items if isinstance(c.get("text"), str)]

    all_texts = chunks + claim_texts
    if not all_texts:
        return None

    cache = EmbeddingCache(embed_fn=ai_client.embed_texts)
    await cache.warm(all_texts)
    return cache


async def perform_audit(
    *,
    url: str,
    provider: str,
    tier: str,
    job_id: str | None = None,
    requested_tier: str | None = None,
    audit_target_type: str = "website",
    target_name: str | None = None,
    target_metadata: dict | None = None,
    category: str | None = None,
    market: str | None = None,
    language: str | None = None,
    entities: list[str] | None = None,
    project_id: int | None = None,
    user_plan: str = "plan_starter",
    scraper_service,
    performance_service,
    network_service,
    ai_client,
    ai_service_enabled: bool = True,
    hallucination_service=None,
    competitor_discovery_service=None,
    competitor_benchmark_service=None,
    brand_truth_payload: dict | None = None,
    db=None,
    performance_snapshot_service=None,
    predictive_intent_service=None,
    site_structure_summary: str | None = None,
    event_sink=None,
) -> tuple[dict, dict[str, float]]:
    # SIGV2-1021: optional async sink for public stage-progress events
    # ({event, stage, reason?} -> appended allowlisted to the job's event
    # list). Emission is best-effort and never alters audit behaviour.
    async def _emit_stage(event: str, stage: str, **fields) -> None:
        if event_sink is None:
            return
        try:
            await event_sink({"event": event, "stage": stage, **fields})
        except Exception:  # pragma: no cover - progress emission must not fail audits
            logger.debug("Stage progress emission failed for stage=%s", stage, exc_info=True)

    warnings: list[str] = []
    # EPIC 11 / S11.1 quick-scan: capture the RAW requested tier before
    # normalisation collapses "lite"/"quick" -> "fast". Used only by the
    # flag-gated quick-scan early-return below; does not affect routing.
    _raw_requested_tier = str(requested_tier or tier or "").strip().lower()
    requested_tier = normalize_audit_tier(requested_tier or tier)
    data_source_context: dict | None = None
    resolved_target_type = str(audit_target_type or "website").strip().lower()
    if resolved_target_type not in {"website", "brand"}:
        resolved_target_type = "website"
    is_brand_without_url = resolved_target_type == "brand" and not url.strip()
    audit_label = target_name or url or "brand audit"
    execution_gates = resolve_audit_execution_gates(user_plan)
    normalized_user_plan = str(execution_gates["normalized_plan"])
    allow_predictive_intent = bool(execution_gates["allow_predictive_intent"])
    allow_competitor_analysis = bool(execution_gates["allow_competitor_analysis"])
    allow_entity_enhancement = bool(execution_gates["allow_entity_enhancement"])
    allow_advisor_synthesis = bool(execution_gates.get("allow_advisor_synthesis", False))

    if not allow_predictive_intent:
        logger.info(
            "Skipped based on plan constraints: predictive_intent disabled for plan=%s target=%s",
            normalized_user_plan,
            audit_label,
        )
    if not allow_competitor_analysis:
        logger.info(
            "Skipped based on plan constraints: competitors disabled for plan=%s target=%s",
            normalized_user_plan,
            audit_label,
        )
    if not allow_entity_enhancement:
        logger.info(
            "Skipped based on plan constraints: entity_enhancement disabled for plan=%s target=%s",
            normalized_user_plan,
            audit_label,
        )

    if not ai_service_enabled:
        logger.warning("AI service usage is disabled by operational settings for %s", audit_label)
        raise HTTPException(
            status_code=503,
            detail="AI analysis is currently disabled by operational settings.",
        )
    if db is not None and project_id is not None:
        try:
            data_source_context, source_warnings = resolve_project_audit_data_sources(
                db,
                project_id=project_id,
            )
            warnings.extend(source_warnings)
            project_profile = (
                data_source_context.get("project_profile", {})
                if isinstance(data_source_context, dict)
                else {}
            )
            if not (isinstance(market, str) and market.strip()):
                project_market = project_profile.get("target_country")
                if isinstance(project_market, str) and project_market.strip():
                    market = project_market.strip().lower()
            if not (isinstance(language, str) and language.strip()):
                project_language = project_profile.get("language")
                if isinstance(project_language, str) and project_language.strip():
                    language = project_language.strip().lower()
        except Exception as exc:
            logger.warning(
                "Project data source context resolution failed for project_id=%s: %s",
                project_id,
                exc,
            )
            warnings.append(
                "Project data context could not be resolved; using AI Estimates Only mode."
            )

    from services.page_type_detector import (
        detect_page_type,
        filter_irrelevant_suggestions,
        get_audit_hint,
        get_page_type_label,
    )

    if is_brand_without_url:
        # Brand audits without a URL skip scraper, performance, and network analysis.
        logger.info("Brand audit mode (no URL) for target=%s", audit_label)
        await _emit_stage("stage_skipped", "signal_collection", reason="brand_target")
        scraped_data = {
            "success_status": False,
            "url": "",
            "error": {"error_code": "brand_mode", "message": "Brand audit, no URL to scrape."},
        }
        markdown_content = None
        screenshot_base64 = None
        scrape_metadata: dict = {}
        page_title = target_name or ""
        page_headings = None
        thin_content_info = None
        performance_task = None
        network_task = None
        answerability_task = None
        geo_visibility_task = None

        brand_meta = target_metadata if isinstance(target_metadata, dict) else {}
        requested_market = market
        category = (
            category.strip()
            if isinstance(category, str) and category.strip()
            else str(brand_meta.get("category") or "general").strip() or "general"
        )
        market = (
            market.strip()
            if isinstance(market, str) and market.strip()
            else str(brand_meta.get("market") or "global").strip() or "global"
        )
        final_language = (
            language.strip().lower()
            if isinstance(language, str) and language.strip()
            else str(brand_meta.get("language") or "en").strip().lower() or "en"
        )
        final_market = market
        schema_structure = {}
        detected_page_type = "brand_entity"  # brand audits use dedicated page type for filtering

        # Collect external brand signals for grounded analysis
        brand_signals: dict = {}
        try:
            from services.brand_signal_collector_service import BrandSignalCollectorService

            brand_signal_service = BrandSignalCollectorService()
            brand_signals = await brand_signal_service.collect_brand_signals(
                brand_name=target_name or "",
                category=category,
                market=market,
                domain=brand_meta.get("domain") or brand_meta.get("website"),
            )
            logger.info(
                "Brand signals collected for %s: %d signals, presence_score=%.1f",
                audit_label,
                brand_signals.get("summary", {}).get("signals_collected", 0),
                brand_signals.get("summary", {}).get("brand_presence_score", 0),
            )
        except Exception as exc:
            logger.warning("Brand signal collection failed for %s: %s", audit_label, exc)
            brand_signals = {"status": "error", "error": str(exc)}
    else:
        await _emit_stage("stage_started", "signal_collection")
        scraper_task = asyncio.create_task(scraper_service.get_page_content_and_screenshot(url))
        if performance_snapshot_service is not None and db is not None:
            performance_task = asyncio.create_task(
                performance_snapshot_service.get_or_fetch_snapshot(db, url=url)
            )
        else:
            performance_task = asyncio.create_task(performance_service.get_performance_metrics(url))
        network_task = asyncio.create_task(network_service.analyze_network_protocols(url))
        answerability_task = asyncio.create_task(
            asyncio.wait_for(
                AEOAnswerabilityService().score_url(url, prevalidated=True),
                timeout=15.0,
            )
        )

        # Lightweight HTML fetch for JSON-LD schema extraction.
        # Firecrawl strips <script> tags (only_main_content=True), so JSON-LD
        # is lost from raw_html. This parallel GET fetches the full HTML page
        # specifically for schema analysis, same pattern as the guest audit.
        async def _fetch_html_for_schema(target_url: str) -> str | None:
            try:
                from services.url_validation import safe_async_fetch

                resp = await safe_async_fetch(target_url, method="GET", timeout=10.0)
                ct = resp.headers.get("content-type", "")
                if "html" in ct:
                    return resp.text
            except Exception:
                pass
            return None

        schema_html_task = asyncio.create_task(_fetch_html_for_schema(url))

        try:
            scraped_data = await scraper_task
        except Exception as exc:
            for task in (performance_task, network_task, schema_html_task, answerability_task):
                if task is not None:
                    task.cancel()
            logger.error("Error during data fetching for %s: %s", url, exc)
            scraped_data = {
                "success_status": False,
                "error": {
                    "error_code": "fetch_error",
                    "message": f"Error during data fetching: {exc}",
                },
                "url": url,
            }
        # A failed scrape still yields a degraded report, not a failed audit.
        await _emit_stage(
            "stage_completed",
            "signal_collection",
            outcome=("degraded" if not scraped_data.get("success_status") else "completed"),
        )

        markdown_content = scraped_data.get("markdown_content")
        raw_html_content = scraped_data.get("raw_html")
        screenshot_base64 = scraped_data.get("screenshot_base64")
        scrape_metadata = (
            scraped_data.get("metadata", {})
            if isinstance(scraped_data.get("metadata"), dict)
            else {}
        )
        page_title = str(scrape_metadata.get("title") or "")
        page_headings = scrape_metadata.get("headings")

        requested_market = market
        category, market = _discovery_context(
            url,
            markdown_content,
            title=page_title,
            headings=page_headings if isinstance(page_headings, list) else None,
            category_override=category,
            market_override=market,
        )

        detected_language = _infer_language_from_content(markdown_content, scrape_metadata)
        final_language = (
            language.strip().lower()
            if isinstance(language, str) and language.strip()
            else detected_language or "en"
        )
        detected_market = _infer_market_from_content(url, markdown_content, scrape_metadata)
        final_market = (
            requested_market.strip().lower()
            if isinstance(requested_market, str) and requested_market.strip()
            else detected_market
        )
        market = final_market

        # --- Page-type detection ---
        detected_page_type = detect_page_type(
            url=url or None,
            content=markdown_content,
            title=scrape_metadata.get("title"),
        )

        # Resolve lightweight HTML for schema extraction (has full <script> tags)
        schema_html = None
        try:
            schema_html = await schema_html_task
        except Exception as exc:
            logger.warning("Schema HTML fetch failed for %s: %s", url, exc)
        schema_structure = analyze_json_ld_structure(
            schema_html or raw_html_content or markdown_content or "",
            site_category=category,
            page_type=detected_page_type,
        )

        # --- Thin / placeholder content detection ---
        thin_content_info = _detect_thin_content(markdown_content)

        # GEO visibility, search-based brand citation check (needs resolved market)
        geo_visibility_task = asyncio.create_task(
            asyncio.wait_for(
                GeoVisibilityService().run_visibility_audit(
                    target=url,
                    location=final_market or market or "global",
                ),
                timeout=20.0,
            )
        )

    intent_query = (
        _resolve_audit_intent_query(url, scrape_metadata, category)
        if url.strip()
        else (target_name or category)
    )
    audit_intent = "informational"
    if not allow_predictive_intent:
        audit_intent = None
    elif predictive_intent_service is not None and db is not None:
        try:
            audit_intent = predictive_intent_service.classify_query_intent(
                db,
                query=intent_query,
                category=category,
            )
        except Exception as exc:
            logger.warning("Intent classification failed for %s: %s", audit_label, exc)
    audit_query_type = resolve_query_type(
        query_type=(scrape_metadata.get("query_type") or scrape_metadata.get("queryType")),
        intent=audit_intent,
    )
    competitor_task = None
    if allow_competitor_analysis and competitor_discovery_service is not None:
        competitor_task = asyncio.create_task(
            asyncio.wait_for(
                competitor_discovery_service.discover_competitors(
                    site_url=url or (target_name or ""),
                    category=category,
                    market=market,
                    content=markdown_content,
                ),
                timeout=8,
            )
        )

    async def _resolve_competitor_task() -> dict | Exception | None:
        if competitor_task is None:
            return None
        try:
            return await competitor_task
        except Exception as exc:  # noqa: BLE001 - normalized below
            return exc

    gather_tasks = []
    task_labels = []
    if performance_task is not None:
        gather_tasks.append(performance_task)
        task_labels.append("performance")
    if network_task is not None:
        gather_tasks.append(network_task)
        task_labels.append("network")
    if answerability_task is not None:
        gather_tasks.append(answerability_task)
        task_labels.append("answerability")
    if geo_visibility_task is not None:
        gather_tasks.append(geo_visibility_task)
        task_labels.append("geo_visibility")
    gather_tasks.append(_resolve_competitor_task())
    task_labels.append("competitor")

    # SIGV2-1292: measurement announces that it started, like the others do.
    #
    # It only ever emitted `stage_completed` or `stage_skipped`, so its row
    # could never read as running: it sat queued from the start and flipped
    # straight to done. Measured on a real 44 second scan on preprod, that is
    # a 7.3 second window, the second longest in the run, during which the
    # stage was working and the screen said it had not begun.
    #
    # Edward reported the scan jumping from queued to finished with no sign of
    # progress. The events are all recorded correctly, and two of four stages
    # never said they had begun, which is most of what he was looking for.
    await _emit_stage("stage_started", "measurement")

    gather_results = await asyncio.gather(*gather_tasks, return_exceptions=True)
    result_map = dict(zip(task_labels, gather_results))

    # Measurement stage: every gated task absent means nothing ran at all
    # (e.g. brand target with competitor discovery disabled); a task that
    # returned an exception is a partial provider failure = degraded, not
    # failed (AC4).
    if all(result is None for result in gather_results):
        await _emit_stage("stage_skipped", "measurement", reason="not_applicable")
    else:
        failed_labels = [
            label for label, result in result_map.items() if isinstance(result, Exception)
        ]
        await _emit_stage(
            "stage_completed",
            "measurement",
            outcome="degraded" if failed_labels else "completed",
            reason="partial_measurement_failure" if failed_labels else None,
            summary=",".join(failed_labels) if failed_labels else None,
        )

    performance_result = result_map.get("performance")
    network_result = result_map.get("network")
    competitor_result = result_map.get("competitor")

    if performance_result is None:
        performance_metrics = _empty_performance_metrics(
            "Brand audit, no URL to measure performance."
        )
    elif isinstance(performance_result, Exception):
        logger.warning(
            "Performance metrics fetch failed for %s: %s", audit_label, performance_result
        )
        warnings.append("Performance metrics were unavailable; returning an empty snapshot.")
        performance_metrics = _empty_performance_metrics("Performance metrics were unavailable.")
    elif hasattr(performance_result, "metrics"):
        performance_metrics = performance_result.metrics
        if performance_result.history:
            performance_metrics["history"] = performance_result.history
        if performance_metrics.get("status") and performance_metrics.get("status") != "success":
            warning_message = performance_metrics.get(
                "message",
                "Performance metrics were unavailable; returning a partial report.",
            )
            warnings.append(warning_message)
    elif isinstance(performance_result, dict):
        performance_metrics = performance_result
        if performance_metrics.get("status") and performance_metrics.get("status") != "success":
            warning_message = performance_metrics.get(
                "message",
                "Performance metrics were unavailable; returning a partial report.",
            )
            warnings.append(warning_message)
    else:
        warnings.append("Performance metrics were unavailable; returning an empty snapshot.")
        performance_metrics = _empty_performance_metrics("Performance metrics were unavailable.")

    if network_result is None:
        network_data = _empty_network_metrics()
    elif isinstance(network_result, Exception):
        logger.warning("Network analysis failed for %s: %s", audit_label, network_result)
        warnings.append("Network protocol analysis was unavailable; returning an empty snapshot.")
        network_data = _empty_network_metrics()
    elif isinstance(network_result, dict):
        network_data = network_result
        if (
            network_data.get("http_version") in (None, "Unknown")
            and not network_data.get("supports_http2")
            and not network_data.get("supports_http3_inferred")
        ):
            warnings.append("Network protocol analysis could not determine HTTP support.")
    else:
        warnings.append("Network protocol analysis was unavailable; returning an empty snapshot.")
        network_data = _empty_network_metrics()

    # Inject HTTP response headers from scraper into network_data for scoring
    _scraper_response_headers = (
        scraped_data.get("response_headers") if isinstance(scraped_data, dict) else None
    )
    if _scraper_response_headers and isinstance(_scraper_response_headers, dict):
        network_data["response_headers"] = {
            k.lower(): v for k, v in _scraper_response_headers.items()
        }

    # --- AEO answerability result ---
    answerability_result = result_map.get("answerability")
    answerability_data: dict = {}
    if answerability_result is None:
        pass  # brand mode or skipped, leave empty
    elif isinstance(answerability_result, Exception):
        logger.warning(
            "AEO answerability scoring failed for %s: %s", audit_label, answerability_result
        )
        answerability_data = {"status": "error", "error": str(answerability_result)}
    elif isinstance(answerability_result, dict):
        answerability_data = answerability_result
    else:
        logger.warning(
            "AEO answerability returned unexpected type for %s: %s",
            audit_label,
            type(answerability_result),
        )

    # --- GEO visibility result ---
    geo_visibility_result = result_map.get("geo_visibility")
    geo_visibility_data: dict = {}
    if geo_visibility_result is None:
        pass  # brand mode or skipped, leave empty
    elif isinstance(geo_visibility_result, Exception):
        logger.warning("GEO visibility audit failed for %s: %s", audit_label, geo_visibility_result)
        geo_visibility_data = {"status": "error", "error": str(geo_visibility_result)}
    elif isinstance(geo_visibility_result, dict):
        geo_visibility_data = geo_visibility_result
    else:
        logger.warning(
            "GEO visibility returned unexpected type for %s: %s",
            audit_label,
            type(geo_visibility_result),
        )

    ai_analysis_results: dict = {}
    ai_response: dict[str, Any] = {}
    model_name = None
    provider_used = provider
    service_status: dict[str, str] = {
        "firecrawl": "ok",
        "ai_service": "ok",
        "pagespeed": "ok",
        "network": "ok",
        "predictive_intent": "ok",
        "competitors": "ok",
        "entity_enhancement": "ok",
        "answerability": "ok"
        if (answerability_data and answerability_data.get("status") != "error")
        else ("skipped" if not answerability_data else "degraded"),
        "geo_visibility": "ok"
        if (geo_visibility_data and geo_visibility_data.get("status") != "error")
        else ("skipped" if not geo_visibility_data else "degraded"),
    }
    service_errors: dict[str, str] = {}

    if not allow_predictive_intent:
        service_status["predictive_intent"] = "skipped_plan"
        service_errors["predictive_intent"] = (
            "Skipped based on plan constraints. Predictive intent requires Specialist or above."
        )
    if not allow_competitor_analysis:
        service_status["competitors"] = "skipped_plan"
        service_errors["competitors"] = (
            "Skipped based on plan constraints. Competitor analysis requires Specialist or above."
        )
    if not allow_entity_enhancement:
        service_status["entity_enhancement"] = "skipped_plan"
        service_errors["entity_enhancement"] = (
            "Skipped based on plan constraints. Entity enhancement requires Specialist or above."
        )

    if isinstance(performance_result, Exception):
        service_status["pagespeed"] = "disabled"
        service_errors["pagespeed"] = str(performance_result)
    elif performance_metrics.get("status") != "success":
        service_status["pagespeed"] = "degraded"
        service_errors["pagespeed"] = performance_metrics.get(
            "message",
            "Performance metrics were unavailable.",
        )

    network_unknown = (
        network_data.get("http_version") in (None, "Unknown")
        and not network_data.get("supports_http2")
        and not network_data.get("supports_http3_inferred")
    )
    if isinstance(network_result, Exception):
        service_status["network"] = "disabled"
        service_errors["network"] = str(network_result)
    elif not isinstance(network_result, dict):
        service_status["network"] = "disabled"
        service_errors["network"] = "Network protocol analysis was unavailable."
    elif network_unknown:
        service_status["network"] = "degraded"
        service_errors["network"] = "Network protocol analysis could not determine HTTP support."

    discovered_competitors: list[dict] = []
    competitor_benchmark: dict = {}
    debate_metadata: dict[str, object] | None = None
    site_host = urlparse(url).hostname or url if url.strip() else (target_name or "brand")
    if not allow_competitor_analysis:
        pass
    elif competitor_discovery_service is None:
        service_status["competitors"] = "disabled"
        service_errors["competitors"] = "Competitor discovery service is unavailable."
    elif isinstance(competitor_result, Exception):
        # SIGV2-1233: some exceptions (e.g. asyncio.TimeoutError()) carry no
        # message at all, so str(exc)/redact_secrets(exc) alone can render as
        # an empty string. Always include the exception type so the log line
        # stays diagnosable even when the message is empty.
        competitor_error_type = type(competitor_result).__name__
        safe_competitor_message = redact_secrets(competitor_result)
        safe_competitor_error = (
            f"{competitor_error_type}: {safe_competitor_message}"
            if safe_competitor_message
            else f"{competitor_error_type} (no further detail provided by the exception)"
        )
        logger.warning(
            "Competitor discovery failed for %s: %s",
            url,
            safe_competitor_error,
            exc_info=competitor_result,
        )
        service_status["competitors"] = "degraded"
        service_errors["competitors"] = safe_competitor_error
        warnings.append(
            "Competitor analysis was unavailable; continuing without competitor insights."
        )
    elif isinstance(competitor_result, dict):
        provider_health = str(competitor_result.get("provider_health") or "ok").strip().lower()
        provider_errors = competitor_result.get("provider_errors")
        if provider_health in {"disabled", "degraded"}:
            service_status["competitors"] = provider_health
            if isinstance(provider_errors, dict) and provider_errors:
                service_errors["competitors"] = "; ".join(
                    f"{key}: {value}" for key, value in provider_errors.items() if value
                )
            elif provider_health == "disabled":
                service_errors["competitors"] = "External competitor providers are not configured."

        discovered_competitors = [
            item for item in competitor_result.get("competitors", []) if isinstance(item, dict)
        ]
    else:
        service_status["competitors"] = "degraded"
        service_errors["competitors"] = "Competitor discovery returned an unexpected payload."
        warnings.append(
            "Competitor analysis was unavailable; continuing without competitor insights."
        )

    can_run_ai = scraped_data.get("success_status") and markdown_content
    if is_brand_without_url:
        can_run_ai = True
        service_status["firecrawl"] = "disabled"
        service_errors["firecrawl"] = "Brand audit, no URL to scrape."

    if not can_run_ai:
        scrape_error = scraped_data.get("error", "Unknown")
        service_status["firecrawl"] = "disabled"
        service_status["ai_service"] = "disabled"
        service_errors["firecrawl"] = str(scrape_error)
        service_errors["ai_service"] = "Skipped because scraping failed."
        warnings.append("Scraping failed; returning a partial report without AI analysis.")
        await _emit_stage("stage_skipped", "analysis", reason="upstream_data_unavailable")
    else:
        scrape_method = scraped_data.get("scrape_method", "firecrawl")
        scraper_label = _resolve_scraper_label(scrape_method)
        tools_engaged = [scraper_label, "Gemini 2.0 Flash Vision", "Google PSI"]
        if not screenshot_base64:
            warnings.append("Screenshot unavailable; audit proceeds with content-only analysis.")
        if scrape_method == "fallback":
            warnings.append(
                "Firecrawl unavailable; content scraped via fallback (no JS rendering)."
            )
        if allow_predictive_intent:
            tools_engaged.append("Predictive Intent v1")
        if is_brand_without_url:
            tools_engaged = ["Brand Entity Analysis", "Gemini 2.0 Flash Vision"]
            if allow_predictive_intent:
                tools_engaged.append("Predictive Intent v1")
            if brand_signals and brand_signals.get("summary", {}).get("signals_collected", 0) > 0:
                tools_engaged.extend(["Brand Signal Collector", "SERP Analysis", "Wikidata Lookup"])
        truth_context_service = UnifiedTruthContextService(db if isinstance(db, Session) else None)
        context_payload = {
            "orchestrator": "Audit Orchestrator v2.5",
            "tools_engaged": tools_engaged,
            "target_url": url or None,
            "audit_target_type": resolved_target_type,
            "target_name": target_name,
            "category_detected": category,
            "market_detected": market,
            "performance": _sanitize_performance_for_ai(
                performance_metrics if performance_metrics else {},
                scrape_ok=bool(markdown_content),
            ),
            "network": network_data if network_data else {},
            "scrape_succeeded": bool(markdown_content),
            "data_sources": data_source_context if isinstance(data_source_context, dict) else {},
        }
        if target_metadata and isinstance(target_metadata, dict):
            context_payload["target_metadata"] = target_metadata
        if brand_truth_payload:
            context_payload["brand_truth"] = brand_truth_payload
        # Inject collected brand signals for grounded brand audit analysis
        if is_brand_without_url and brand_signals and brand_signals.get("summary"):
            context_payload["brand_signals"] = {
                "serp": brand_signals.get("serp", {}),
                "knowledge_graph": brand_signals.get("knowledge_graph", {}),
                "wikidata": brand_signals.get("wikidata", {}),
                "ai_visibility": brand_signals.get("ai_visibility", {}),
                "summary": brand_signals.get("summary", {}),
            }
        context_payload["unified_truth_context"] = truth_context_service.build_context(
            project_id=project_id,
            audit_target_type=resolved_target_type,
            target_name=target_name,
            target_url=url or None,
            category=category,
            market=market,
            source_content=markdown_content,
            target_metadata=target_metadata if isinstance(target_metadata, dict) else None,
            brand_truth_payload=brand_truth_payload
            if isinstance(brand_truth_payload, dict)
            else None,
            performance_metrics=performance_metrics
            if isinstance(performance_metrics, dict)
            else None,
            network_data=network_data if isinstance(network_data, dict) else None,
            data_source_context=data_source_context
            if isinstance(data_source_context, dict)
            else None,
        )

        # --- Inject page-type context into AI payload ---
        if detected_page_type:
            context_payload["page_type"] = detected_page_type
            context_payload["page_type_label"] = get_page_type_label(detected_page_type)
            context_payload["page_type_audit_hint"] = get_audit_hint(detected_page_type)
        # site_structure_summary is injected by sitemap_crawler_service
        # when running a multi-page site crawl (see queue_next_batch).
        if site_structure_summary:
            context_payload["site_structure_summary"] = site_structure_summary

        # --- Inject schema detection results so AI knows what already exists ---
        if schema_structure and isinstance(schema_structure, dict):
            context_payload["schema_structure"] = {
                "detected_schema_types": schema_structure.get("detected_schema_types", []),
                "missing_required_types": schema_structure.get("missing_required_types", []),
                "missing_high_impact_types": schema_structure.get("missing_high_impact_types", []),
                "coverage_percent": schema_structure.get("coverage_percent", 0.0),
            }

        # --- Inject plan-aware feature gates so AI skips generating locked content ---
        context_payload["plan_gates"] = {
            "allow_competitor_analysis": allow_competitor_analysis,
            "allow_predictive_intent": allow_predictive_intent,
            "allow_semantic_graph": can_use_feature(
                normalized_user_plan, "has_semantic_graph_mapping"
            ),
            "allow_advanced_reporting": can_use_feature(
                normalized_user_plan, "has_advanced_reporting"
            ),
            "allow_brand_integrity": can_use_feature(
                normalized_user_plan, "has_brand_integrity_guardrails"
            ),
            "allow_eeat_trust": can_use_feature(normalized_user_plan, "has_eeat_trust_audit"),
        }

        # --- Inject thin-content warning so AI avoids findings on placeholder pages ---
        if thin_content_info:
            context_payload["thin_content"] = thin_content_info
            warnings.append(
                f"Page has thin/placeholder content ({thin_content_info['reason']}, "
                f"{thin_content_info['word_count']} words). Findings may be limited."
            )

        ai_content = (
            markdown_content
            or f"Brand audit for: {target_name or 'Unknown Brand'}. Category: {category}. Market: {market}."
        )
        ai_screenshot = screenshot_base64

        # ── EPIC 11 / S11.1 quick-scan ─────────────────────────────────────
        # Flag-gated fast path: return ONLY the deterministic component of the
        # audit (no LLM reasoning, no debate, no findings/recommendations) when
        # an opt-in "lite"/"quick" tier is requested. Deterministic inputs reuse
        # the exact pre-scan variables assembled above, and findings are None so
        # the scores equal the pure deterministic base (no AI penalties). Gated
        # to the website path for now (brand-without-URL keeps the full path).
        # Defaults OFF, so live full-audit behaviour is unchanged.
        if (
            settings.QUICK_SCAN_ENABLED
            and not is_brand_without_url
            and _raw_requested_tier in {"lite", "quick"}
        ):
            quick_det = calculate_deterministic_scores(
                performance_metrics=performance_metrics,
                schema_analysis=schema_structure,
                scrape_metadata=scrape_metadata,
                network_data=network_data,
                content=markdown_content,
                page_type=detected_page_type,
                scrape_succeeded=bool(markdown_content),
                brand_signals=None,
                brand_name=target_name or None,
                seo_findings=None,
                geo_findings=None,
                aeo_findings=None,
            )
            quick_scores: dict[str, float] = {
                "seo": float(quick_det.get("seo_score") or 0.0),
                "geo": float(quick_det.get("geo_score") or 0.0),
                "aeo": float(quick_det.get("aeo_score") or 0.0),
                "overall": float(quick_det.get("overall_score") or 0.0),
            }
            quick_report: dict[str, Any] = {
                "url": url,
                "quick_scan": True,
                "scores": {
                    "seo": quick_scores["seo"],
                    "geo": quick_scores["geo"],
                    "aeo": quick_scores["aeo"],
                    "overall": quick_scores["overall"],
                    "seo_breakdown": quick_det.get("seo_breakdown"),
                    "geo_breakdown": quick_det.get("geo_breakdown"),
                    "aeo_breakdown": quick_det.get("aeo_breakdown"),
                },
                "performance": performance_metrics,
                "network": network_data,
                "warnings": warnings,
                "metadata": {
                    "quick_scan": True,
                    "tier": tier,
                    "requested_tier": _raw_requested_tier,
                    "score_source": "deterministic_quick_scan",
                    "score_version": quick_det.get("version"),
                    "page_type": detected_page_type,
                    "category": category,
                    "market": final_market,
                    "language": final_language,
                    "scores_available": True,
                    "audit_outcome": AUDIT_OUTCOME_COMPLETED,
                },
            }
            logger.info(
                "Quick-scan deterministic path returned for %s (requested_tier=%s)",
                audit_label,
                _raw_requested_tier,
            )
            await _emit_stage("stage_skipped", "analysis", reason="deterministic_quick_scan")
            return quick_report, quick_scores

        await _emit_stage("stage_started", "analysis")
        ai_response = await ai_client.generate_audit(
            provider=provider,
            tier=tier,
            requested_tier=requested_tier,
            job_id=job_id,
            content=ai_content,
            screenshot_base64=ai_screenshot,
            network_data=network_data,
            category=category,
            market=market,
            query_type=audit_query_type,
            context_payload=context_payload,
        )
        if "error" in ai_response:
            await _emit_stage("stage_failed", "analysis", reason="ai_service_unavailable")
            service_status["ai_service"] = "disabled"
            service_errors["ai_service"] = str(ai_response["error"])
            error_payload = _normalize_ai_error_payload(ai_response.get("error"))
            retryable = error_payload.get("retryable")
            http_status = error_payload.get("http_status")
            error_subtype = error_payload.get("error_subtype")
            request_id = error_payload.get("request_id")
            payload_type = error_payload.get("payload_type") or error_payload.get("raw_type")
            if isinstance(ai_response.get("error"), ServiceUnavailableError):
                retryable = True
            if retryable is False or http_status == 400:
                logger.warning(
                    "AI upstream validation failure mapped to 422 (subtype=%s, request_id=%s, payload_type=%s)",
                    error_subtype,
                    request_id,
                    payload_type,
                )
                raise HTTPException(
                    status_code=422,
                    detail=_validation_error_operator_detail(error_payload),
                )
            raise HTTPException(
                status_code=503,
                detail="AI analysis is currently unavailable; please retry shortly.",
            )
        else:
            # Providers that run the debate emit their own progress events;
            # stage_completed here is idempotent for those and authoritative
            # for providers that emit nothing.
            await _emit_stage("stage_completed", "analysis")
            ai_analysis_results = ai_response.get("analysis", {})
            model_name = ai_response.get("model")
            provider_used = ai_response.get("provider", provider)
            debate_metadata = (
                ai_response.get("debate") if isinstance(ai_response.get("debate"), dict) else None
            )

    if isinstance(ai_analysis_results, dict):
        entity_enhancement_ai_client = ai_client if allow_entity_enhancement else None
        ai_generation_metadata = _build_ai_generation_metadata(
            provider_used=provider_used,
            model_name=model_name,
            ai_analysis_results=ai_analysis_results,
            debate_metadata=debate_metadata,
            usage_payload=ai_response.get("usage")
            if isinstance(ai_response.get("usage"), dict)
            else None,
        )
        merged_entities = await build_entity_list(
            ai_client=entity_enhancement_ai_client,
            provider=provider_used,
            tier=tier,
            ai_entities=ai_analysis_results.get("entities_detected"),
            request_entities=entities,
            markdown_content=markdown_content,
        )
        ai_analysis_results["entities_detected"] = merged_entities
    else:
        ai_generation_metadata = {}
        merged_entities = []

    hallucination_result: dict | None = None
    supported_track_a_claims: list[dict[str, Any]] = []
    dual_track_shadow: dict[str, Any] | None = None
    dual_track_fallback_reason: str | None = None
    unified_truth_context_version: str | None = None
    embedding_cache: EmbeddingCache | None = None
    if hallucination_service is not None and brand_truth_payload is None:
        try:
            embedding_cache = await _build_embedding_cache(
                ai_client=ai_client,
                hallucination_service=hallucination_service,
                markdown_content=markdown_content,
                ai_analysis_results=ai_analysis_results,
            )
        except Exception as exc:
            logger.warning("Failed to build embedding cache: %s", str(exc)[:200])
    dual_track_rollout = _resolve_dual_track_execution(requested_tier)
    forbidden_brand_facts = _resolve_forbidden_brand_facts(
        db if isinstance(db, Session) else None, project_id
    )
    # ADDITIVE: only forward the guardrail kwarg when there are forbidden facts,
    # so absence is byte-for-byte unchanged (and back-compatible with any
    # analyze() signature that predates the param).
    forbidden_facts_kwargs: dict[str, Any] = (
        {"forbidden_brand_facts": forbidden_brand_facts} if forbidden_brand_facts else {}
    )
    try:
        if hallucination_service is not None:
            hallucination_result = hallucination_service.analyze(
                source_content=markdown_content,
                analysis=ai_analysis_results,
                brand_truth_payload=brand_truth_payload,
                embedding_cache=embedding_cache,
                **forbidden_facts_kwargs,
            )
            hallucination_result, high_risk_discrepancies, sanitized_analysis = (
                _finalize_hallucination_result(hallucination_result)
            )
            supported_track_a_claims = UnifiedTruthContextService(
                db if isinstance(db, Session) else None
            ).build_supported_track_a_claims_from_hallucination(hallucination_result)
            if isinstance(sanitized_analysis, dict) and sanitized_analysis:
                ai_analysis_results = sanitized_analysis

            debate_backed = isinstance(debate_metadata, dict) and debate_metadata.get("enabled")
            # Debate-backed audits normally skip the secondary validation loop because
            # the multi-agent debate already cross-validates claims (timeout fix in
            # 5b97ad30). Deep-judgment requests are the exception: their secondary
            # re-grounding pass is a deliberate accuracy feature and must still run even
            # when the audit is debate-backed.
            is_deep_judgment_request = requested_tier == "deep_judgment"
            if (
                tier == "smart"
                and high_risk_discrepancies
                and (not debate_backed or is_deep_judgment_request)
            ):
                logger.info("Triggering Smart Tier Secondary Validation Loop for %s", url)
                correction_prompt = (
                    "Secondary validation loop triggered. Regenerate the audit using only claims "
                    "that can be tied to the provided crawl content or brand-truth evidence.\n"
                    "Low-certainty claims detected:\n"
                )
                for claim in high_risk_discrepancies:
                    evidence_excerpt = ""
                    evidence_refs = claim.get("evidence_refs")
                    if (
                        isinstance(evidence_refs, list)
                        and evidence_refs
                        and isinstance(evidence_refs[0], dict)
                    ):
                        evidence_excerpt = str(evidence_refs[0].get("excerpt") or "").strip()
                    correction_prompt += (
                        f"- Field: {claim.get('field_label') or claim.get('field_path') or 'Unknown'}\n"
                        f"  Claim: {claim.get('claim_text', 'Unknown')}\n"
                        f"  Certainty: {claim.get('certainty_score', 'n/a')}\n"
                    )
                    if evidence_excerpt:
                        correction_prompt += f"  Best evidence: {evidence_excerpt[:280]}\n"
                correction_prompt += (
                    "\nPlease re-evaluate the Strategic Intelligence Grid and related recommendations "
                    "using only grounded evidence."
                )

                correction_tools = [
                    _resolve_scraper_label(scraped_data.get("scrape_method", "firecrawl")),
                    "Gemini 2.0 Flash Vision",
                    "Google PSI",
                    "Hallucination Service",
                ]
                if is_brand_without_url:
                    correction_tools = [
                        "Brand Entity Analysis",
                        "Gemini 2.0 Flash Vision",
                        "Hallucination Service",
                    ]

                context_payload = {
                    "orchestrator": "Deep Analysis Architect",
                    "tools_engaged": correction_tools,
                    "target_url": url or None,
                    "audit_target_type": resolved_target_type,
                    "target_name": target_name,
                    "category_detected": category,
                    "market_detected": market,
                    "performance": _sanitize_performance_for_ai(
                        performance_metrics if performance_metrics else {},
                        scrape_ok=bool(markdown_content),
                    ),
                    "network": network_data if network_data else {},
                    "scrape_succeeded": bool(markdown_content),
                    "data_sources": data_source_context
                    if isinstance(data_source_context, dict)
                    else {},
                    "correction_loop_feedback": correction_prompt,
                }
                if detected_page_type:
                    context_payload["page_type"] = detected_page_type
                    context_payload["page_type_label"] = get_page_type_label(detected_page_type)
                    context_payload["page_type_audit_hint"] = get_audit_hint(detected_page_type)
                if target_metadata and isinstance(target_metadata, dict):
                    context_payload["target_metadata"] = target_metadata
                if brand_truth_payload and isinstance(brand_truth_payload, dict):
                    context_payload["brand_truth"] = brand_truth_payload
                context_payload["unified_truth_context"] = UnifiedTruthContextService(
                    db if isinstance(db, Session) else None
                ).build_context(
                    project_id=project_id,
                    audit_target_type=resolved_target_type,
                    target_name=target_name,
                    target_url=url or None,
                    category=category,
                    market=market,
                    source_content=markdown_content,
                    target_metadata=target_metadata if isinstance(target_metadata, dict) else None,
                    brand_truth_payload=brand_truth_payload
                    if isinstance(brand_truth_payload, dict)
                    else None,
                    performance_metrics=performance_metrics
                    if isinstance(performance_metrics, dict)
                    else None,
                    network_data=network_data if isinstance(network_data, dict) else None,
                    data_source_context=data_source_context
                    if isinstance(data_source_context, dict)
                    else None,
                    supported_track_a_claims=supported_track_a_claims,
                )

                ai_response_second_pass = await ai_client.generate_audit(
                    provider=provider,
                    tier=tier,
                    requested_tier=requested_tier,
                    job_id=job_id,
                    content=ai_content,
                    screenshot_base64=ai_screenshot,
                    network_data=network_data,
                    category=category,
                    market=market,
                    query_type=audit_query_type,
                    context_payload=context_payload,
                )

                if "error" not in ai_response_second_pass:
                    ai_analysis_results = ai_response_second_pass.get("analysis", {})
                    model_name = ai_response_second_pass.get("model")
                    provider_used = ai_response_second_pass.get("provider", provider)
                    debate_metadata = (
                        ai_response_second_pass.get("debate")
                        if isinstance(ai_response_second_pass.get("debate"), dict)
                        else None
                    )
                    hallucination_result = hallucination_service.analyze(
                        source_content=markdown_content,
                        analysis=ai_analysis_results,
                        brand_truth_payload=brand_truth_payload,
                        embedding_cache=embedding_cache,
                        **forbidden_facts_kwargs,
                    )
                    hallucination_result, high_risk_discrepancies, sanitized_analysis = (
                        _finalize_hallucination_result(hallucination_result)
                    )
                    supported_track_a_claims = UnifiedTruthContextService(
                        db if isinstance(db, Session) else None
                    ).build_supported_track_a_claims_from_hallucination(hallucination_result)
                    if isinstance(sanitized_analysis, dict) and sanitized_analysis:
                        ai_analysis_results = sanitized_analysis
                    ai_generation_metadata = _build_ai_generation_metadata(
                        provider_used=provider_used,
                        model_name=model_name,
                        ai_analysis_results=ai_analysis_results,
                        debate_metadata=debate_metadata,
                        usage_payload=(
                            ai_response_second_pass.get("usage")
                            if isinstance(ai_response_second_pass.get("usage"), dict)
                            else None
                        ),
                    )
                    merged_entities = await build_entity_list(
                        ai_client=entity_enhancement_ai_client,
                        provider=provider_used,
                        tier=tier,
                        ai_entities=ai_analysis_results.get("entities_detected"),
                        request_entities=entities,
                        markdown_content=markdown_content,
                    )
                    ai_analysis_results["entities_detected"] = merged_entities
                    warnings.append(
                        "A secondary validation pass re-grounded low-certainty claims before packaging the report."
                    )

            unsupported = hallucination_result.get("unsupported_sentences", [])
            omitted_claims = int(hallucination_result.get("omitted_claims") or 0)
            if hallucination_result.get("flagged"):
                warnings.append(
                    "Potential low-certainty AI claims were flagged; review certainty details before publishing."
                )
            elif omitted_claims:
                warnings.append(
                    f"Low-certainty AI claims were removed from the public narrative ({omitted_claims} claim(s))."
                )
            elif unsupported:
                warnings.append(
                    f"Some AI claims may be weakly grounded ({len(unsupported)} claim(s))."
                )
    except Exception as exc:
        logger.warning("Hallucination analysis failed for %s: %s", url, exc)
        warnings.append("Hallucination analysis was unavailable for this audit.")

    if isinstance(hallucination_result, dict) and dual_track_rollout.should_evaluate_shadow:
        try:
            shadow_truth_context = UnifiedTruthContextService(
                db if isinstance(db, Session) else None
            ).build_context(
                project_id=project_id,
                audit_target_type=resolved_target_type,
                target_name=target_name,
                target_url=url or None,
                category=category,
                market=market,
                source_content=markdown_content,
                target_metadata=target_metadata if isinstance(target_metadata, dict) else None,
                brand_truth_payload=brand_truth_payload
                if isinstance(brand_truth_payload, dict)
                else None,
                performance_metrics=performance_metrics
                if isinstance(performance_metrics, dict)
                else None,
                network_data=network_data if isinstance(network_data, dict) else None,
                data_source_context=data_source_context
                if isinstance(data_source_context, dict)
                else None,
                supported_track_a_claims=supported_track_a_claims,
            )
            unified_truth_context_version = (
                str(shadow_truth_context.get("schema_version") or "").strip() or None
            )
        except Exception as exc:
            logger.warning(
                "Unified Truth Context unavailable for dual-track shadow %s: %s", url, exc
            )
            warnings.append(
                "Dual-track truth context was unavailable for this audit; single-track grounding remained authoritative."
            )
            dual_track_fallback_reason = "unified_truth_context_unavailable"
        else:
            shadow_claim_verifications, shadow_claim_source = (
                _resolve_dual_track_claim_verifications(
                    hallucination_result=hallucination_result,
                    ai_analysis_results=ai_analysis_results
                    if isinstance(ai_analysis_results, dict)
                    else None,
                )
            )
            if shadow_claim_source == "canonical_analysis_fallback":
                warnings.append(
                    "Dual-track shadow recovered prescriptive claim candidates from the final audit payload because grounding validation returned no claim list."
                )
            elif not shadow_claim_verifications:
                warnings.append(
                    "Dual-track shadow could not derive claim candidates from grounding validation or the final audit payload; single-track grounding remained authoritative."
                )
                dual_track_fallback_reason = "claim_verifications_unavailable"

            try:
                if shadow_claim_verifications:
                    dual_track_shadow = await ClaimEvaluationService().evaluate_shadow_async(
                        claim_verifications=shadow_claim_verifications,
                        unified_truth_context=shadow_truth_context,
                        debate_metadata=debate_metadata,
                        ai_client=ai_client,
                        provider=provider_used or provider,
                        tier=tier,
                        requested_tier=requested_tier,
                    )
            except Exception as exc:
                logger.warning("Dual-track shadow evaluation unavailable for %s: %s", url, exc)
                warnings.append(
                    "Dual-track claim classification was unavailable for this audit; single-track grounding remained authoritative."
                )
                dual_track_fallback_reason = "claim_classifier_unavailable"
            else:
                if isinstance(dual_track_shadow, dict) and shadow_claim_source:
                    dual_track_shadow["claim_source"] = shadow_claim_source

    if (
        dual_track_fallback_reason is None
        and isinstance(dual_track_shadow, dict)
        and isinstance(dual_track_shadow.get("track_b_judge"), dict)
        and bool(dual_track_shadow["track_b_judge"].get("enabled"))
        and (
            not bool(dual_track_shadow["track_b_judge"].get("available"))
            or int(dual_track_shadow["track_b_judge"].get("judge_unavailable_claims") or 0) > 0
        )
    ):
        dual_track_fallback_reason = "track_b_judge_unavailable"

    ai_generation_metadata = _append_track_b_transcript_entries(
        ai_generation_metadata,
        dual_track_shadow,
    )

    dual_track_metadata = _build_dual_track_metadata(
        rollout_mode=dual_track_rollout.rollout_mode,
        effective_execution_mode=dual_track_rollout.effective_execution_mode,
        dual_track_shadow=dual_track_shadow,
        unified_truth_context_version=unified_truth_context_version,
        fallback_reason=dual_track_fallback_reason,
        dual_track_grounding_enabled=bool(dual_track_shadow),
        client_safe_authority=dual_track_rollout.client_safe_authority,
    )
    _record_dual_track_observability(
        dual_track_shadow=dual_track_shadow,
        fallback_reason=dual_track_fallback_reason,
    )

    # ── Grounding Gate ───────────────────────────────────────────────
    # Evaluate every finding against source evidence and exclude
    # hard-flagged (ungrounded) findings before report assembly.
    grounding_gate_metadata: dict[str, Any] | None = None
    try:
        gate_result = GroundingGateService().evaluate(
            ai_analysis_results=ai_analysis_results,
            hallucination_result=hallucination_result,
            source_content=markdown_content,
        )
        if gate_result.gate_applied and isinstance(gate_result.filtered_analysis, dict):
            ai_analysis_results = gate_result.filtered_analysis
        grounding_gate_metadata = gate_result.to_metadata()
    except Exception:
        logger.warning("Grounding gate failed, proceeding without filtering", exc_info=True)
        grounding_gate_metadata = {"gate_applied": False, "error": "gate_exception"}

    if isinstance(debate_metadata, dict) and grounding_gate_metadata:
        debate_metadata["grounding_gate"] = grounding_gate_metadata

    # Pydantic v2 API (parse_obj is deprecated). extra="allow" on AuditAnalysis
    # is intentional so legacy payload keys are preserved, not dropped.
    analysis = AuditAnalysis.model_validate(ai_analysis_results)

    score_breakdown = {
        "seo": extract_score(ai_analysis_results, "seo_score"),
        "geo": extract_score(ai_analysis_results, "geo_score"),
        "aeo": extract_score(ai_analysis_results, "aeo_score"),
    }
    scores_available = _scores_available_from_analysis(ai_analysis_results)
    # Which pillars the model actually scored, so the blend below can leave
    # the ones it skipped alone instead of charging the site for silence.
    scored_dimensions = ai_scored_dimensions(ai_analysis_results)
    # Weighted overall: SEO 40% + AEO 30% + GEO 30%
    score_breakdown["overall"] = DeterministicScoringEngine.calculate_overall_score(score_breakdown)

    competitor_summary_meta: dict[str, Any] = {
        "mode": "grounded",
        "confidence": "high",
        "has_score_deltas": False,
        "message": None,
        "measured_competitor_count": 0,
        "exploratory_competitor_count": 0,
    }
    if discovered_competitors:
        target_metrics = _build_target_benchmark_metrics(
            target_name=site_host,
            score_breakdown=score_breakdown,
        )
        grounded_competitors, exploratory_competitors = _resolve_grounded_competitor_rows(
            db=db if isinstance(db, Session) else None,
            project_id=project_id,
            discovered_competitors=discovered_competitors,
        )
        competitor_benchmark, competitor_summary_meta = _build_competitor_benchmark_payload(
            target_name=str(target_metrics["name"]),
            target_metrics={metric: float(target_metrics[metric]) for metric in _BENCHMARK_METRICS},
            grounded_competitors=grounded_competitors,
            exploratory_competitors=exploratory_competitors,
        )
        benchmark_message = competitor_summary_meta.get("message")
        if isinstance(benchmark_message, str) and benchmark_message:
            warnings.append(benchmark_message)

    competitors_payload: list[dict] = []
    benchmark_rows = (
        competitor_benchmark.get("rows", []) if isinstance(competitor_benchmark, dict) else []
    )
    benchmark_map = {
        _normalize_competitor_identity(row.get("name", "")): row
        for row in benchmark_rows
        if isinstance(row, dict) and not row.get("is_target")
    }
    for candidate in discovered_competitors:
        name = str(candidate.get("name", "")).strip()
        if not name:
            continue
        benchmark_row = benchmark_map.get(_normalize_competitor_identity(name), {})
        exploratory = bool(benchmark_row.get("exploratory"))
        source_label = str(candidate.get("source") or "unknown")
        if exploratory:
            source_label = f"{source_label} estimate"
        competitors_payload.append(
            {
                "name": name,
                "source": source_label,
                "confidence_score": float(candidate.get("confidence_score") or 0.0),
                "score": float(
                    benchmark_row.get("overall_score")
                    or (float(candidate.get("confidence_score") or 0.0) * 100.0)
                ),
                "geo_visibility": float(benchmark_row.get("geo_visibility") or 0.0),
                "aeo_score": float(benchmark_row.get("aeo_score") or 0.0),
                "entity_strength": float(benchmark_row.get("entity_strength") or 0.0),
                "rank": int(benchmark_row.get("rank") or 0),
            }
        )

    supplemental_recommendations = [
        {
            "action": recommendation,
            "impact": "medium",
            "effort": None,
            "justification": "Direct recommendation from AI analysis.",
        }
        for recommendation in (analysis.recommendations or [])
        if isinstance(recommendation, str) and recommendation.strip()
    ]
    # SIGV2-1118: the deterministic problem channel. Every other candidate below
    # originates in LLM prose whose wording drifts between audits, so a dismissal
    # keyed on that text is lost as soon as the model rephrases the fix. The
    # scoring engine's failed checks are the one vocabulary that does not drift:
    # each carries a stable ``code`` which rides through enrichment untouched and
    # becomes the dismissal key.
    #
    # Scored from the deterministic signals only (``findings=None``): an
    # AI-findings-derived penalty would reintroduce the drift this channel
    # exists to remove. Requires a scraped page, so brand-only audits (no URL,
    # no content, empty scrape metadata) are skipped rather than fed page-tag
    # problems that cannot apply to them.
    problem_code_suggestions: list[dict[str, Any]] = []
    if not is_brand_without_url and markdown_content:
        try:
            problem_code_suggestions = build_problem_code_suggestions(
                calculate_deterministic_scores(
                    performance_metrics=performance_metrics,
                    schema_analysis=schema_structure,
                    scrape_metadata=scrape_metadata,
                    network_data=network_data,
                    content=markdown_content,
                    page_type=detected_page_type,
                    scrape_succeeded=True,
                    brand_signals=None,
                    brand_name=target_name or None,
                    seo_findings=None,
                    geo_findings=None,
                    aeo_findings=None,
                )
            )
        except Exception:
            # Never block an audit on the identity channel: without it the fix
            # list is unchanged and dismissals fall back to text identity.
            logger.exception("Deterministic problem-code suggestions failed for %s", audit_label)
            problem_code_suggestions = []

    module_outputs = {
        "analysis": {
            "suggestions": _analysis_module_suggestions(ai_analysis_results),
        },
        "performance": performance_metrics,
        "network": network_data,
        "competitors": {
            "items": discovered_competitors,
            "benchmark": competitor_benchmark,
        },
        "analysis_recommendations": {"suggestions": supplemental_recommendations},
        "deterministic_problems": {"suggestions": problem_code_suggestions},
    }
    unified_suggestions = generate_unified_suggestions(module_outputs)
    if detected_page_type:
        unified_suggestions = filter_irrelevant_suggestions(unified_suggestions, detected_page_type)
    canonical_suggestions, suggestion_detail_transcript = await _to_canonical_suggestions(
        unified_suggestions=unified_suggestions,
        ai_client=ai_client,
        provider=provider_used,
        tier=tier,
        market=final_market,
        language=final_language,
        page_type=detected_page_type if detected_page_type else None,
        page_type_label=get_page_type_label(detected_page_type) if detected_page_type else None,
    )
    finding_sources = {}
    for domain_key, finding_list in [
        ("seo", [f.dict() if hasattr(f, "dict") else f for f in (analysis.seo_findings or [])]),
        ("geo", [f.dict() if hasattr(f, "dict") else f for f in (analysis.geo_findings or [])]),
        ("aeo", [f.dict() if hasattr(f, "dict") else f for f in (analysis.aeo_findings or [])]),
    ]:
        if finding_list:
            finding_sources[domain_key] = finding_list
    if finding_sources:
        canonical_suggestions = _ground_suggestions_to_findings(
            canonical_suggestions, finding_sources
        )

    # EPIC 13 (re-scoped) — deterministic Advisor plan over the grounded suggestions.
    # Off by default; LLM-free; attached to the report below. Never blocks the audit.
    advisor_plan = None
    if settings.ADVISOR_SYNTHESIS_ENABLED and allow_advisor_synthesis:
        try:
            advisor_plan = build_advisor_plan(
                canonical_suggestions,
                max_actions=int(settings.ADVISOR_MAX_ACTIONS),
            )
            # Increment 3: optional single LLM call to narrativize the grounded plan.
            if advisor_plan is not None and not settings.ADVISOR_DETERMINISTIC_ONLY:
                summary = generate_strategic_summary(advisor_plan, tier=str(tier or "smart"))
                if summary:
                    advisor_plan["strategic_summary"] = summary
                    advisor_plan["metadata"]["deterministic_only"] = False
        except Exception:
            logger.exception("Advisor synthesis failed; continuing without an advisor plan")
            advisor_plan = None

    ai_generation_metadata = _append_post_processing_transcript_entries(
        ai_generation_metadata,
        suggestion_detail_transcript,
    )

    legacy_report = AuditReport(
        url=url,
        analysis=analysis,
        entities=merged_entities,
        performance=performance_metrics,
        network=network_data,
        warnings=warnings,
        metadata={
            **(
                scraped_data.get("metadata", {})
                if isinstance(scraped_data.get("metadata", {}), dict)
                else {}
            ),
            "provider": provider_used,
            "tier": tier,
            "model": model_name,
            "category": category,
            "market": final_market,
            "language": final_language,
            "intent": audit_intent,
            "query_type": audit_query_type,
            "warnings": warnings,
            "hallucination": hallucination_result,
            "ai_generation": ai_generation_metadata,
            "dual_track_shadow": dual_track_shadow,
            "dual_track_grounding": {
                **dual_track_metadata,
                "source": "canonical",
            },
            "grounding_profile": dual_track_metadata["grounding_profile"],
            "dual_track_grounding_enabled": dual_track_metadata["dual_track_grounding_enabled"],
            "unified_truth_context_version": dual_track_metadata["unified_truth_context_version"],
            "track_a_claim_count": dual_track_metadata["track_a_claim_count"],
            "track_b_claim_count": dual_track_metadata["track_b_claim_count"],
            "integrity_certificate_summary": dual_track_metadata["integrity_certificate_summary"],
            "fallback_reason": dual_track_metadata["fallback_reason"],
            "grounding_gate": grounding_gate_metadata,
            "competitor_summary": {
                "total_discovered": len(discovered_competitors),
                "total_benchmarked": int(
                    competitor_summary_meta.get("measured_competitor_count") or 0
                ),
                "exploratory_count": int(
                    competitor_summary_meta.get("exploratory_competitor_count") or 0
                ),
                "mode": competitor_summary_meta.get("mode"),
                "confidence": competitor_summary_meta.get("confidence"),
                "has_score_deltas": bool(competitor_summary_meta.get("has_score_deltas")),
                "message": competitor_summary_meta.get("message"),
                "benchmark": competitor_benchmark or {},
            },
        },
        screenshot_base64=screenshot_base64,
        hallucination=hallucination_result,
        competitors=competitors_payload,
        suggestions=canonical_suggestions,
        debate=debate_metadata if isinstance(debate_metadata, dict) else None,
    ).dict()
    legacy_report["competitors"] = competitors_payload
    if advisor_plan is not None:
        legacy_report["advisor"] = advisor_plan
        # Also stash under metadata so it survives canonicalization
        # (AuditResult.metadata is a flexible Dict[str, object]) and is queryable
        # from the stored report / external report endpoint.
        if isinstance(legacy_report.get("metadata"), dict):
            legacy_report["metadata"]["advisor"] = advisor_plan
    existing_aeo = legacy_report.get("aeo") if isinstance(legacy_report.get("aeo"), dict) else {}
    legacy_report["aeo"] = {
        **existing_aeo,
        "schema_coverage": {
            "coverage_by_type": schema_structure.get("coverage_by_type", {}),
            "coverage_percent": schema_structure.get("coverage_percent", 0.0),
            "missing_high_impact_types": schema_structure.get("missing_high_impact_types", []),
        },
        "schema_health": {
            "score": schema_structure.get("coverage_percent", 0.0),
            "detected_schema_types": schema_structure.get("detected_schema_types", []),
            "missing_required_types": schema_structure.get("missing_required_types", []),
            "missing_fields_by_type": schema_structure.get("missing_fields_by_type", {}),
            "high_impact_blockers": schema_structure.get("high_impact_blockers", []),
            "missing_high_impact_types": schema_structure.get("missing_high_impact_types", []),
        },
    }

    # Inject AEO answerability data (from AEOAnswerabilityService)
    if answerability_data:
        legacy_report["aeo"]["answerability_audit"] = answerability_data

    # Inject GEO visibility data (from GeoVisibilityService)
    if geo_visibility_data:
        existing_geo = (
            legacy_report.get("geo") if isinstance(legacy_report.get("geo"), dict) else {}
        )
        legacy_report["geo"] = {
            **existing_geo,
            "visibility_audit": geo_visibility_data,
        }

    ai_status = str(service_status.get("ai_service") or "").strip().lower()
    audit_outcome = AUDIT_OUTCOME_COMPLETED
    if ai_status != "ok":
        audit_outcome = AUDIT_OUTCOME_DEGRADED if scores_available else AUDIT_OUTCOME_FAILED
    elif not scores_available:
        audit_outcome = AUDIT_OUTCOME_DEGRADED

    report_metadata = legacy_report.get("metadata", {})
    report_metadata["market"] = final_market
    report_metadata["language"] = final_language
    report_metadata["service_status"] = service_status
    report_metadata["scores_available"] = scores_available
    report_metadata["audit_outcome"] = audit_outcome
    report_metadata["page_type"] = detected_page_type
    if isinstance(data_source_context, dict):
        report_metadata["project_id"] = data_source_context.get("project_id")
        report_metadata["workspace_id"] = data_source_context.get("workspace_id")
        report_metadata["data_source_mode"] = data_source_context.get("mode")
        report_metadata["has_external_data_sources"] = bool(
            data_source_context.get("has_external_data")
        )
        report_metadata["data_sources"] = data_source_context
    elif project_id is not None:
        report_metadata["project_id"] = project_id
        report_metadata["data_source_mode"] = "ai_estimate_only"
        report_metadata["has_external_data_sources"] = False
    if service_errors:
        report_metadata["service_errors"] = service_errors
    # Store brand signals summary in metadata for frontend display
    if is_brand_without_url and brand_signals and brand_signals.get("summary"):
        report_metadata["brand_signals_summary"] = brand_signals.get("summary", {})
        wikidata = brand_signals.get("wikidata", {})
        if wikidata.get("entity_exists"):
            report_metadata["wikidata_entity"] = {
                "entity_id": wikidata.get("entity_id"),
                "label": wikidata.get("label"),
                "description": wikidata.get("description"),
                "has_wikipedia": wikidata.get("has_wikipedia", False),
                "sitelinks_count": wikidata.get("sitelinks_count", 0),
            }
        kg = brand_signals.get("knowledge_graph", {})
        if kg.get("has_knowledge_panel"):
            report_metadata["knowledge_panel"] = {
                "title": kg.get("title"),
                "type": kg.get("type"),
                "description": kg.get("description"),
            }
    # Persist scraped page content (truncated) so calibration / debate layers
    # can access it without refetching.  Cap at 20 KB to keep DB payload reasonable.
    if markdown_content:
        report_metadata["scraped_content"] = markdown_content[:20_000]
    if scraped_data.get("scrape_method"):
        report_metadata["scrape_method"] = scraped_data["scrape_method"]
    legacy_report["metadata"] = report_metadata
    # Inject markdown_content at top level so the adapter can pass it
    # to deterministic scoring (score_utils).
    if markdown_content:
        legacy_report["markdown_content"] = markdown_content[:20_000]
    # Pass brand signals for deterministic scoring boost
    if is_brand_without_url and brand_signals and brand_signals.get("summary"):
        legacy_report["_brand_signals"] = brand_signals

    full_report = to_canonical_audit_result(
        legacy_report,
        audit_url=url or None,
        audit_target_type=resolved_target_type,
        target_name=target_name or None,
        target_url=url or None,
        target_metadata=target_metadata if isinstance(target_metadata, dict) else {},
        created_at=datetime.now(timezone.utc),
        plan=user_plan,
    )
    report_metadata = (
        full_report.get("metadata") if isinstance(full_report.get("metadata"), dict) else {}
    )
    report_metadata["score_source"] = "blended_v3"
    report_metadata["page_type"] = detected_page_type
    if scores_available:
        report_metadata["raw_ai_scores"] = dict(score_breakdown)

    # --- Blend AI scores with deterministic scores ---
    # Deterministic scores provide objective, signal-based consistency;
    # AI scores add qualitative differentiation (page-type relevance,
    # content quality, scoring-rubric calibration).
    # Blend: deterministic + AI, weights from settings (deterministic-weighted
    # by default for run-to-run consistency).
    canonical_scores = (
        full_report.get("scores") if isinstance(full_report.get("scores"), dict) else {}
    )
    if scores_available and canonical_scores:
        AI_WEIGHT = float(getattr(settings, "AUDIT_AI_SCORE_WEIGHT", 0.3))
        DET_WEIGHT = float(getattr(settings, "AUDIT_DETERMINISTIC_SCORE_WEIGHT", 0.7))
        det_snapshot = {dim: canonical_scores.get(dim) for dim in ("seo", "geo", "aeo")}
        for dim in ("seo", "geo", "aeo"):
            # A pillar the model did not score keeps its deterministic value;
            # see ``blend_pillar_score`` for why blending silence as zero was
            # a 24-point penalty on the dimension nobody assessed.
            blended = blend_pillar_score(
                deterministic=canonical_scores.get(dim),
                ai=score_breakdown.get(dim),
                ai_scored=scored_dimensions.get(dim, False),
                det_weight=DET_WEIGHT,
                ai_weight=AI_WEIGHT,
            )
            if blended is not None:
                canonical_scores[dim] = blended
        # Recompute overall from blended component scores
        # Weighted overall: SEO 40% + AEO 30% + GEO 30%
        canonical_scores["overall"] = DeterministicScoringEngine.calculate_overall_score(
            {
                d: canonical_scores.get(d, 0.0)
                for d in ("seo", "geo", "aeo")
                if isinstance(canonical_scores.get(d), (int, float))
            }
        )
        # Scale breakdown sub-components so they remain consistent with
        # the blended top-level score.  Without this, the frontend
        # ScoreBreakdownAccordion would show a blended header score
        # whose weighted components still sum to the old deterministic
        # total, confusing users who verify the arithmetic.
        for dim in ("seo", "geo", "aeo"):
            det_total = det_snapshot.get(dim)
            blended_total = canonical_scores.get(dim)
            breakdown = canonical_scores.get(f"{dim}_breakdown")
            if (
                isinstance(det_total, (int, float))
                and isinstance(blended_total, (int, float))
                and isinstance(breakdown, dict)
                and det_total > 0
            ):
                ratio = blended_total / det_total
                breakdown["score"] = blended_total
                components = breakdown.get("components")
                if isinstance(components, dict):
                    capped_any = False
                    for comp_key in list(components):
                        comp_val = components[comp_key]
                        if isinstance(comp_val, (int, float)):
                            scaled = round(comp_val * ratio, 1)
                            # Cap sub-component scores to [0, 100]
                            clamped = max(0.0, min(100.0, scaled))
                            if clamped != scaled:
                                capped_any = True
                            components[comp_key] = clamped
                    if capped_any:
                        breakdown["_components_capped"] = True
        full_report["scores"] = canonical_scores
        report_metadata["deterministic_scores"] = {
            k: v for k, v in det_snapshot.items() if isinstance(v, (int, float))
        }

    full_report["metadata"] = report_metadata
    full_report = sanitize_audit_payload_for_plan(
        full_report,
        normalized_user_plan,
        lock_origin="execution",
        section_keys={"competitors", "predictive_intent", "entities"},
    )

    return full_report, canonical_score_breakdown(full_report)
