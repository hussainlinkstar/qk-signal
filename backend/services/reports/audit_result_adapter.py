# pyre-unsafe
from __future__ import annotations

import logging
import re
import types as _types
from datetime import datetime, timezone
from typing import Any, Mapping, Union, get_args, get_origin

from pydantic import BaseModel as _PydanticBase

from app.models.audit import AuditResult
from problem_codes import normalize_problem_code
from services.query_taxonomy import resolve_query_type
from score_utils import calculate_deterministic_scores

logger = logging.getLogger(__name__)


_CORE_METADATA_FIELDS = {
    "created_at",
    "updated_at",
    "plan",
    "version",
    "service_status",
    "service_errors",
    "competitor_summary",
    "scores_available",
    "audit_outcome",
    "intent",
    "query_type",
    "technical_signals",
    "hallucination",
}

_AUDIT_TARGET_TYPES = {"website", "brand"}
_CANONICAL_SCHEMA_VERSION = "2026-03-09"
_PUBLIC_SCORE_SOURCE = "deterministic_matrix"
_PUBLIC_SCORE_VERSION = "3.0"
_RECOMMENDATION_CATEGORIES = {
    "technical": "technical",
    "content": "content",
    "backlinks": "authority",
    "authority": "authority",
    "local": "local_authority",
    "schema": "machine_readability",
    "entity": "entity_authority",
    "geo": "local_authority",
    "seo": "technical",
    "aeo": "machine_readability",
}
_CLIENT_SAFE_METADATA_BLOCKLIST = {
    "ai_generation",
    "ai_provider",
    "billable_credit_cost",
    "billing",
    "billing_metadata",
    "billing_provider",
    "billing_tier",
    "consumed_credit_cost",
    "cost_forecast",
    "credit_cost_reconciled",
    "credit_hold_id",
    "credit_hold_shortfall",
    "credit_hold_status",
    "credit_reconciliation_reason",
    "debug",
    "estimated_credit_cost",
    "estimated_llm_cost",
    "execution_metadata",
    "internal_chain",
    "locked_credit_cost",
    "model",
    "model_metadata",
    "orchestration",
    "provider",
    "provider_metadata",
    "released_credit_cost",
    "token_usage",
    "transcript",
}
_TRACK_A_INTEGRITY_BUCKETS = {"unsupported_fact", "conflicting_source", "missing_evidence"}
_TRACK_B_INTEGRITY_BUCKETS = {
    "generic_recommendation",
    "manual_verification_required",
    "unsupported_factual_premise",
    "weak_problem_linkage",
    "vision_only_overreach",
    "safely_blocked_during_degraded_review",
}


def _normalize_target_type(value: Any) -> str:
    enum_value = getattr(value, "value", value)
    normalized = str(enum_value or "website").strip().lower()
    return normalized if normalized in _AUDIT_TARGET_TYPES else "website"


def _normalize_target_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_target_url(value: Any) -> str | None:
    normalized = _normalize_target_name(value)
    if not normalized:
        return None
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    return None


def _normalize_target_metadata(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_score(value: Any, default: float | None = None) -> float | None:
    candidate = value
    if isinstance(value, dict):
        candidate = value.get("score", default)
    try:
        score = float(candidate)
    except (TypeError, ValueError):
        score = default
    if score is None:
        return None
    return max(0.0, min(100.0, score))


def _as_ratio(value: Any, default: float | None = 0.0) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed is None:
        return None
    if parsed > 1:
        parsed = parsed / 100
    return max(0.0, min(1.0, parsed))


def _as_int(value: Any, default: int | None = 0) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    if parsed is None:
        return None
    return max(0, parsed)


def _stored_score(section: dict[str, Any], key: str, fallback: Any) -> float | None:
    """A pillar sub-score already stored in the report's canonical section wins
    over a rebuilt default; the computed source is only the fallback for when the
    stored value is absent or non-numeric."""
    stored = _as_score(section.get(key), default=None)
    return stored if stored is not None else fallback


def _normalize_benchmark_delta(raw_delta: Any) -> dict[str, float] | None:
    if not isinstance(raw_delta, dict):
        return None

    def _as_delta(value: Any) -> float | None:
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    normalized = {
        "geo_visibility": _as_delta(raw_delta.get("geo_visibility")),
        "aeo_score": _as_delta(raw_delta.get("aeo_score")),
        "entity_strength": _as_delta(raw_delta.get("entity_strength")),
    }
    if not any(value is not None for value in normalized.values()):
        return None
    return normalized


def _normalize_evidence_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    refs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_key = str(item.get("source_key") or "").strip()
        excerpt = str(item.get("excerpt") or "").strip()
        if not source_key or not excerpt:
            continue
        refs.append(
            {
                "source_type": str(item.get("source_type") or "scraped_content").strip()
                or "scraped_content",
                "source_key": source_key,
                "excerpt": excerpt,
                "retrieval_score": _as_ratio(item.get("retrieval_score"), default=0.0),
            }
        )
    return refs


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            continue
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def _normalize_field_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None

    field_path = str(value.get("field_path") or "").strip()
    label = str(value.get("label") or "").strip()
    if not field_path or not label:
        return None

    return {
        "field_path": field_path,
        "label": label,
        "total_claims": _as_int(value.get("total_claims"), default=0) or 0,
        "supported_claims": _as_int(value.get("supported_claims"), default=0) or 0,
        "flagged_claims": _as_int(value.get("flagged_claims"), default=0) or 0,
        "omitted_claims": _as_int(value.get("omitted_claims"), default=0) or 0,
        "average_certainty": _as_ratio(value.get("average_certainty"), default=0.0),
        "certainty_level": _normalize_confidence_level(value.get("certainty_level"), default="low"),
    }


def _normalize_hallucination(raw_hallucination: Any) -> dict[str, Any] | None:
    if not isinstance(raw_hallucination, dict):
        return None

    claim_verifications = raw_hallucination.get("claim_verifications")
    if not isinstance(claim_verifications, list):
        claim_verifications = raw_hallucination.get("claims")
    claims: list[dict[str, Any]] = []
    if isinstance(claim_verifications, list):
        for item in claim_verifications:
            if not isinstance(item, dict):
                continue
            claim_text = item.get("claim_text")
            matched_truth_key = item.get("matched_truth_key")
            truth_value = item.get("truth_value")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (claim_text, matched_truth_key, truth_value)
            ):
                continue
            discrepancy_type = str(item.get("discrepancy_type") or "").strip() or None
            severity = str(item.get("severity") or "").strip().lower() or None
            if severity not in {"none", "low", "medium", "high", "critical"}:
                severity = "medium" if bool(item.get("hallucination", False)) else "none"

            claims.append(
                {
                    "claim_id": str(item.get("claim_id") or f"claim-{len(claims)+1}"),
                    "claim_text": claim_text.strip(),
                    "matched_truth_key": matched_truth_key.strip(),
                    "truth_value": truth_value.strip(),
                    "similarity_score": _as_ratio(item.get("similarity_score"), default=0.0),
                    "hallucination": bool(item.get("hallucination", False)),
                    "discrepancy_type": discrepancy_type,
                    "severity": severity,
                    "field_path": str(item.get("field_path") or "").strip() or None,
                    "field_label": str(item.get("field_label") or "").strip() or None,
                    "certainty_score": _as_ratio(
                        item.get("certainty_score"),
                        default=_as_ratio(item.get("similarity_score"), default=0.0),
                    ),
                    "certainty_level": _normalize_confidence_level(
                        item.get("certainty_level"),
                        default="low",
                    ),
                    "disposition": str(item.get("disposition") or "supported").strip().lower()
                    if str(item.get("disposition") or "supported").strip().lower()
                    in {"supported", "flagged", "omitted"}
                    else ("flagged" if bool(item.get("hallucination", False)) else "supported"),
                    "evidence_refs": _normalize_evidence_refs(item.get("evidence_refs")),
                    "track": str(item.get("track") or "").strip().lower() or None
                    if str(item.get("track") or "").strip().lower()
                    in {"track_a", "track_b", "mixed"}
                    else None,
                    "evaluation_mode": str(item.get("evaluation_mode") or "").strip() or None,
                    "claim_kind": str(item.get("claim_kind") or "").strip().lower() or None
                    if str(item.get("claim_kind") or "").strip().lower()
                    in {
                        "descriptive_observation",
                        "prescriptive_recommendation",
                        "causal_hypothesis",
                        "forecast_or_impact",
                        "mixed",
                    }
                    else None,
                    "classification_basis": _normalize_string_list(
                        item.get("classification_basis")
                    ),
                    "premise_refs": _normalize_string_list(item.get("premise_refs")),
                    "reason_codes": _normalize_string_list(item.get("reason_codes")),
                    "problem_refs": _normalize_string_list(item.get("problem_refs")),
                    "problem_anchor_score": _as_ratio(
                        item.get("problem_anchor_score"), default=None
                    ),
                    "action_fit_score": _as_ratio(item.get("action_fit_score"), default=None),
                    "site_specificity_score": _as_ratio(
                        item.get("site_specificity_score"), default=None
                    ),
                    "novel_fact_risk_score": _as_ratio(
                        item.get("novel_fact_risk_score"), default=None
                    ),
                    "suggested_rewrite": str(item.get("suggested_rewrite") or "").strip() or None,
                    "omittable": bool(item.get("omittable", False)),
                }
            )

    threshold = _as_ratio(raw_hallucination.get("threshold"), default=0.85)
    total_claims = (
        _as_int(
            raw_hallucination.get("total_claims"),
            default=_as_int(raw_hallucination.get("total_sentences"), default=len(claims)),
        )
        or 0
    )
    flagged_claims = (
        _as_int(
            raw_hallucination.get("flagged_claims"),
            default=sum(1 for claim in claims if claim.get("hallucination")),
        )
        or 0
    )
    omitted_claims = (
        _as_int(
            raw_hallucination.get("omitted_claims"),
            default=sum(1 for claim in claims if claim.get("disposition") == "omitted"),
        )
        or 0
    )
    average_certainty = _as_ratio(
        raw_hallucination.get("average_certainty"),
        default=_mean([claim.get("certainty_score") for claim in claims]),
    )

    high_risk_discrepancies = [
        claim
        for claim in claims
        if claim.get("hallucination") and claim.get("severity") in {"high", "critical"}
    ]
    field_summaries_raw = raw_hallucination.get("field_summaries")
    field_summaries: list[dict[str, Any]] = []
    if isinstance(field_summaries_raw, list):
        for item in field_summaries_raw:
            normalized = _normalize_field_summary(item)
            if normalized:
                field_summaries.append(normalized)

    return {
        "threshold": threshold,
        "total_claims": total_claims,
        "flagged_claims": flagged_claims,
        "omitted_claims": omitted_claims,
        "average_certainty": average_certainty or 0.0,
        "claims": claims,
        "high_risk_discrepancies": high_risk_discrepancies,
        "field_summaries": field_summaries,
    }


def _mean(scores: list[float | None]) -> float | None:
    present = [score for score in scores if score is not None]
    if not present:
        return None
    return sum(present) / len(present)


def _normalize_shadow_claims(raw_dual_track_shadow: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_dual_track_shadow, dict):
        return []

    raw_claims = raw_dual_track_shadow.get("claims")
    if not isinstance(raw_claims, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in raw_claims:
        if not isinstance(item, dict):
            continue
        track = str(item.get("track") or "").strip().lower()
        if track not in {"track_a", "track_b", "mixed"}:
            continue
        shadow_disposition = str(item.get("shadow_disposition") or "").strip().lower()
        if shadow_disposition not in {
            "supported",
            "flagged",
            "needs_manual_review",
            "manually_approved",
            "manually_refused",
            "omitted",
        }:
            shadow_disposition = "omitted"
        normalized.append(
            {
                "claim_id": str(item.get("claim_id") or "").strip() or None,
                "claim_text": str(item.get("claim_text") or "").strip() or None,
                "track": track,
                "shadow_disposition": shadow_disposition,
                "domain": str(item.get("domain") or "").strip().lower() or None,
                "certainty_score": _as_ratio(item.get("certainty_score"), default=None),
                "confidence_band": str(item.get("confidence_band") or "").strip().lower() or None,
                "explanation": str(item.get("explanation") or "").strip() or None,
                "judge_resolution": str(item.get("judge_resolution") or "").strip() or None,
                "reason_codes": _normalize_string_list(item.get("reason_codes")),
                "problem_refs": _normalize_string_list(item.get("problem_refs")),
                "evidence_refs": _normalize_string_list(item.get("evidence_refs")),
                "premise_refs": _normalize_string_list(item.get("premise_refs")),
                "source_track": str(item.get("source_track") or "").strip().lower() or None,
                "source_claim_id": str(item.get("source_claim_id") or "").strip() or None,
                "review_decision": _as_dict(item.get("review_decision")) or None,
            }
        )
    return normalized


def _is_active_track_b_claim(claim: dict[str, Any]) -> bool:
    return claim.get("track") == "track_b" and claim.get("shadow_disposition") != "manually_refused"


def _categorize_track_a_integrity_bucket(
    claim: dict[str, Any] | None,
    *,
    shadow_claim: dict[str, Any] | None,
) -> str:
    claim_payload = claim if isinstance(claim, dict) else {}
    discrepancy_type = str(claim_payload.get("discrepancy_type") or "").strip().lower()
    matched_truth_key = str(claim_payload.get("matched_truth_key") or "").strip().lower()
    evidence_refs = claim_payload.get("evidence_refs")
    if (
        matched_truth_key == "no_evidence"
        or not isinstance(evidence_refs, list)
        or not evidence_refs
    ):
        return "missing_evidence"
    if discrepancy_type.endswith("mismatch"):
        return "conflicting_source"
    if (
        isinstance(shadow_claim, dict)
        and str(shadow_claim.get("source_track") or "").strip().lower() == "mixed"
    ):
        return "missing_evidence"
    return "unsupported_fact"


def _categorize_track_b_integrity_bucket(claim: dict[str, Any]) -> str:
    if claim.get("shadow_disposition") == "needs_manual_review":
        return "manual_verification_required"
    reason_codes = set(_normalize_string_list(claim.get("reason_codes")))
    if "track_b_judge_unavailable" in reason_codes:
        return "safely_blocked_during_degraded_review"
    if "vision_only_overreach" in reason_codes:
        return "vision_only_overreach"
    if "generic_advice" in reason_codes:
        return "generic_recommendation"
    if reason_codes & {
        "unsupported_premise_ref",
        "invented_site_fact",
        "unsupported_location",
        "unsupported_service_label",
        "unsupported_benchmark",
    }:
        return "unsupported_factual_premise"
    if reason_codes & {"no_supported_problem", "weak_action_problem_fit", "problem_already_solved"}:
        return "weak_problem_linkage"
    return "weak_problem_linkage"


def _build_integrity_certificate_buckets(
    *,
    hallucination_claims: list[dict[str, Any]],
    shadow_claims: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    hallucination_by_id = {
        str(claim.get("claim_id") or "").strip(): claim
        for claim in hallucination_claims
        if isinstance(claim, dict) and str(claim.get("claim_id") or "").strip()
    }

    for claim in shadow_claims:
        if _is_active_track_b_claim(claim) and claim.get("shadow_disposition") in {
            "flagged",
            "needs_manual_review",
            "omitted",
        }:
            category = _categorize_track_b_integrity_bucket(claim)
            counts[("track_b", category)] = counts.get(("track_b", category), 0) + 1
        elif claim.get("track") == "track_a" and claim.get("shadow_disposition") in {
            "flagged",
            "omitted",
        }:
            category = _categorize_track_a_integrity_bucket(
                hallucination_by_id.get(str(claim.get("claim_id") or "").strip()),
                shadow_claim=claim,
            )
            counts[("track_a", category)] = counts.get(("track_a", category), 0) + 1

    if not shadow_claims:
        for claim in hallucination_claims:
            if claim.get("disposition") not in {"flagged", "omitted"}:
                continue
            category = _categorize_track_a_integrity_bucket(claim, shadow_claim=None)
            counts[("track_a", category)] = counts.get(("track_a", category), 0) + 1

    buckets = [
        {"track": track, "category": category, "count": count}
        for (track, category), count in counts.items()
        if count > 0
    ]
    buckets.sort(key=lambda item: (item["track"], item["category"]))
    return buckets


def _build_integrity_certificate_degraded(
    raw_dual_track_shadow: Any,
) -> tuple[bool, str | None]:
    if not isinstance(raw_dual_track_shadow, dict):
        return False, None

    track_b_judge = (
        raw_dual_track_shadow.get("track_b_judge")
        if isinstance(raw_dual_track_shadow.get("track_b_judge"), dict)
        else {}
    )
    if not bool(track_b_judge.get("enabled")):
        return False, None

    judge_unavailable_claims = (
        _as_int(track_b_judge.get("judge_unavailable_claims"), default=0) or 0
    )
    if judge_unavailable_claims <= 0:
        return False, None
    if not bool(track_b_judge.get("available", True)):
        return True, "track_b_judge_unavailable"
    return True, "track_b_judge_partially_unavailable"


def _build_integrity_certificate(
    *,
    raw_report: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> dict[str, Any] | None:
    existing_certificate = _as_dict(canonical_payload.get("integrity_certificate"))
    if not existing_certificate:
        existing_certificate = _as_dict(raw_report.get("integrity_certificate"))

    hallucination = _as_dict(canonical_payload.get("hallucination"))
    metadata = _as_dict(canonical_payload.get("metadata"))
    raw_dual_track_shadow = metadata.get("dual_track_shadow")
    shadow_claims = _normalize_shadow_claims(raw_dual_track_shadow)
    hallucination_claims = (
        hallucination.get("claims") if isinstance(hallucination.get("claims"), list) else []
    )

    if not hallucination_claims and not shadow_claims:
        return existing_certificate or None

    if shadow_claims:
        track_a_claims = [claim for claim in shadow_claims if claim.get("track") == "track_a"]
        track_b_claims = [claim for claim in shadow_claims if claim.get("track") == "track_b"]
        active_track_b_claims = [
            claim for claim in track_b_claims if _is_active_track_b_claim(claim)
        ]
        summary = {
            "total_claims": len(track_a_claims) + len(active_track_b_claims),
            "track_a_total": len(track_a_claims),
            "track_a_supported": sum(
                1 for claim in track_a_claims if claim.get("shadow_disposition") == "supported"
            ),
            "track_a_flagged": sum(
                1 for claim in track_a_claims if claim.get("shadow_disposition") == "flagged"
            ),
            "track_a_omitted": sum(
                1 for claim in track_a_claims if claim.get("shadow_disposition") == "omitted"
            ),
            "track_b_total": len(active_track_b_claims),
            "track_b_supported": sum(
                1
                for claim in active_track_b_claims
                if claim.get("shadow_disposition") in {"supported", "manually_approved"}
            ),
            "track_b_flagged": sum(
                1 for claim in active_track_b_claims if claim.get("shadow_disposition") == "flagged"
            ),
            "track_b_needs_manual_review": sum(
                1
                for claim in active_track_b_claims
                if claim.get("shadow_disposition") == "needs_manual_review"
            ),
            "track_b_omitted": sum(
                1 for claim in active_track_b_claims if claim.get("shadow_disposition") == "omitted"
            ),
            "track_b_manually_approved": sum(
                1
                for claim in track_b_claims
                if claim.get("shadow_disposition") == "manually_approved"
            ),
            "track_b_manually_refused": sum(
                1
                for claim in track_b_claims
                if claim.get("shadow_disposition") == "manually_refused"
            ),
        }
        dual_track_grounding_enabled = True
        grounding_profile = "dual_track_v1"
    else:
        summary = {
            "total_claims": len(hallucination_claims),
            "track_a_total": len(hallucination_claims),
            "track_a_supported": sum(
                1 for claim in hallucination_claims if claim.get("disposition") == "supported"
            ),
            "track_a_flagged": sum(
                1 for claim in hallucination_claims if claim.get("disposition") == "flagged"
            ),
            "track_a_omitted": sum(
                1 for claim in hallucination_claims if claim.get("disposition") == "omitted"
            ),
            "track_b_total": 0,
            "track_b_supported": 0,
            "track_b_flagged": 0,
            "track_b_needs_manual_review": 0,
            "track_b_omitted": 0,
        }
        dual_track_grounding_enabled = False
        grounding_profile = "single_track_v1"

    degraded, degraded_reason = _build_integrity_certificate_degraded(raw_dual_track_shadow)
    return {
        "schema_version": "integrity-certificate-1",
        "dual_track_grounding_enabled": dual_track_grounding_enabled,
        "grounding_profile": grounding_profile,
        "summary": summary,
        "blocked_claim_buckets": _build_integrity_certificate_buckets(
            hallucination_claims=hallucination_claims,
            shadow_claims=shadow_claims,
        ),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
    }


def _as_datetime(value: Any, default: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return default
    return default


# ---------------------------------------------------------------------------
# Recursive preparation for strict Pydantic v2 re-validation
# ---------------------------------------------------------------------------
# After a JSONB / JSON round-trip stored canonical reports suffer from three
# artefacts that cause ``AuditResult.model_validate()`` to reject them:
#   1. ``int`` where ``float`` is expected (JSONB normalises 75.0 → 75)
#   2. ISO strings where ``datetime`` is expected (model_dump(mode="json"))
#   3. Extra keys in nested dicts whose models use ``extra="forbid"``
# The helpers below walk the Pydantic model tree and fix these in-place so
# the happy-path validation succeeds without falling through to the costly
# deterministic-scoring fallback.
# ---------------------------------------------------------------------------


def _unwrap_annotated(tp: Any) -> Any:
    """Strip ``Annotated[X, ...]`` wrappers (e.g. ``NonNegativeFloat``)."""
    if hasattr(tp, "__metadata__"):
        inner = getattr(tp, "__args__", None)
        return inner[0] if inner else tp
    return tp


def _extract_model_class(annotation: Any) -> type | None:
    """Return nested ``BaseModel`` subclass from *annotation*, or ``None``."""
    unwrapped = _unwrap_annotated(annotation)
    if isinstance(unwrapped, type) and issubclass(unwrapped, _PydanticBase):
        return unwrapped
    origin = get_origin(unwrapped)
    args = get_args(unwrapped)
    if origin is Union or isinstance(unwrapped, _types.UnionType):
        for arg in args or ():
            if arg is type(None):
                continue
            result = _extract_model_class(arg)
            if result is not None:
                return result
    return None


def _extract_list_item_model(annotation: Any) -> type | None:
    """If *annotation* is ``List[SomeModel]``, return ``SomeModel``."""
    unwrapped = _unwrap_annotated(annotation)
    origin = get_origin(unwrapped)
    args = get_args(unwrapped)
    if origin is list and args:
        return _extract_model_class(args[0])
    if origin is Union or isinstance(unwrapped, _types.UnionType):
        for arg in args or ():
            if arg is type(None):
                continue
            result = _extract_list_item_model(arg)
            if result is not None:
                return result
    return None


def _annotation_resolves_to(annotation: Any, target: type) -> bool:
    """Check whether *annotation* ultimately resolves to *target* (e.g. ``float``)."""
    unwrapped = _unwrap_annotated(annotation)
    if unwrapped is target:
        return True
    origin = get_origin(unwrapped)
    args = get_args(unwrapped)
    if origin is Union or isinstance(unwrapped, _types.UnionType):
        return any(_annotation_resolves_to(a, target) for a in (args or ()) if a is not type(None))
    return False


def _deep_prepare_for_validation(data: Any, model_cls: type) -> dict[str, Any]:
    """Recursively fix JSONB/JSON round-trip artefacts for strict validation."""
    if not isinstance(data, dict):
        return data
    if not (isinstance(model_cls, type) and issubclass(model_cls, _PydanticBase)):
        return data

    fields = model_cls.model_fields
    extra_cfg = model_cls.model_config.get("extra", "ignore")

    result: dict[str, Any] = {}
    for key, value in data.items():
        if key not in fields:
            if extra_cfg != "forbid":
                result[key] = value
            continue

        if value is None:
            result[key] = None
            continue

        annotation = fields[key].annotation

        nested_model = _extract_model_class(annotation)
        if nested_model is not None and isinstance(value, dict):
            result[key] = _deep_prepare_for_validation(value, nested_model)
            continue

        list_model = _extract_list_item_model(annotation)
        if list_model is not None and isinstance(value, list):
            result[key] = [
                _deep_prepare_for_validation(item, list_model) if isinstance(item, dict) else item
                for item in value
            ]
            continue

        if (
            _annotation_resolves_to(annotation, float)
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            result[key] = float(value)
            continue

        if _annotation_resolves_to(annotation, datetime) and isinstance(value, str):
            result[key] = _as_datetime(value, datetime.now(timezone.utc))
            continue

        result[key] = value

    return result


_AUDIT_RESULT_FIELDS = set(AuditResult.model_fields.keys())


def _prepare_raw_report_for_validation(raw_report: dict[str, Any]) -> dict[str, Any]:
    """Prepare a stored canonical report for strict ``AuditResult`` re-validation.

    Handles JSONB/JSON round-trip artefacts: extra field stripping,
    int→float coercion, and str→datetime coercion throughout the entire
    model tree.
    """
    return _deep_prepare_for_validation(raw_report, AuditResult)


def _as_list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str) and item.strip()]


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _slugify(value: Any, *, default: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return normalized or default


def _normalize_confidence_level(value: Any, default: str = "low") -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"high", "medium", "low"}:
        return normalized
    return default


def _confidence_from_ratio(ratio: float | None, *, default: str = "low") -> str:
    if ratio is None:
        return default
    if ratio >= 0.75:
        return "high"
    if ratio >= 0.4:
        return "medium"
    return "low"


def _extract_external_source_summary(
    raw_report: dict[str, Any], metadata: dict[str, Any]
) -> tuple[bool, float]:
    source_payload = raw_report.get("data_sources")
    if not source_payload:
        source_payload = metadata.get("data_sources")

    rows: list[bool] = []
    if isinstance(source_payload, dict):
        for value in source_payload.values():
            if isinstance(value, dict):
                connected = bool(
                    value.get("connected")
                    or value.get("enabled")
                    or value.get("available")
                    or value.get("configured")
                )
                status = str(value.get("status") or "").strip().lower()
                if status in {"connected", "available", "ready", "complete"}:
                    connected = True
                rows.append(connected)
            elif isinstance(value, bool):
                rows.append(value)
    elif isinstance(source_payload, list):
        for value in source_payload:
            if isinstance(value, dict):
                rows.append(
                    bool(
                        value.get("connected")
                        or value.get("enabled")
                        or value.get("available")
                        or value.get("configured")
                    )
                )
            elif isinstance(value, bool):
                rows.append(value)

    if not rows:
        return False, 0.0
    connected = sum(1 for value in rows if value)
    return connected > 0, round(connected / len(rows), 2)


def _extract_grounding_status(
    raw_report: dict[str, Any],
    canonical_payload: dict[str, Any],
    *,
    narrative_present: bool,
) -> dict[str, Any]:
    raw_confidence = _as_dict(raw_report.get("confidence"))
    grounding = _as_dict(raw_confidence.get("grounding_status"))
    hallucination = _as_dict(canonical_payload.get("hallucination"))

    # Prefer core (non-narrative) metrics when available for a tighter accuracy signal.
    core_total = _as_int(hallucination.get("core_total_sentences"), default=0) or 0
    core_supported = _as_int(hallucination.get("core_supported_sentences"), default=0) or 0

    total_sentences = (
        _as_int(
            grounding.get("total_sentences", hallucination.get("total_claims")),
            default=0,
        )
        or 0
    )
    supported_sentences = _as_int(grounding.get("supported_sentences"), default=None)
    if supported_sentences is None:
        flagged_claims = _as_int(hallucination.get("flagged_claims"), default=0) or 0
        supported_sentences = max(total_sentences - flagged_claims, 0) if total_sentences else 0

    # Use core metrics for support_ratio when available, this excludes
    # narrative/synthesis fields whose low lexical overlap would otherwise
    # drag the ratio down without reflecting actual grounding quality.
    if core_total > 0:
        support_ratio = core_supported / core_total
    else:
        support_ratio = _as_ratio(grounding.get("support_ratio"), default=None)
        if support_ratio is None:
            if total_sentences > 0:
                support_ratio = supported_sentences / total_sentences
            else:
                support_ratio = 0.0 if narrative_present else 1.0

    flagged = bool(grounding.get("flagged")) or bool(
        narrative_present and total_sentences > 0 and supported_sentences < total_sentences
    )

    return {
        "flagged": flagged,
        "supported_sentences": supported_sentences,
        "total_sentences": total_sentences,
        "support_ratio": round(max(0.0, min(1.0, support_ratio)), 2),
    }


def _build_score_contract(
    raw_report: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> dict[str, Any]:
    existing = _as_dict(canonical_payload.get("score_contract"))
    scores = _as_dict(canonical_payload.get("scores"))
    internal = _as_dict(raw_report.get("internal"))
    has_internal_scores = bool(raw_report.get("raw_ai_scores")) or bool(
        internal.get("raw_ai_scores")
    )
    return {
        "public_score_source": str(
            existing.get("public_score_source")
            or canonical_payload.get("score_source")
            or _PUBLIC_SCORE_SOURCE
        ),
        "public_score_version": str(
            existing.get("public_score_version")
            or scores.get("scoring_version")
            or _PUBLIC_SCORE_VERSION
        ),
        "has_internal_alternative_scores": bool(
            existing.get("has_internal_alternative_scores", has_internal_scores)
        ),
    }


def _normalize_narrative_block(
    value: Any,
    *,
    fallback_text: str | None,
    fallback_confidence: str,
    support_ratio: float,
    default_source_type: str = "ai_synthesis",
) -> dict[str, Any] | None:
    payload = _as_dict(value)
    text = str(payload.get("text") or fallback_text or "").strip()
    if not text:
        return None

    confidence = _normalize_confidence_level(
        payload.get("confidence"),
        default=fallback_confidence,
    )
    normalized_support_ratio = _as_ratio(
        payload.get("supported_sentence_ratio"),
        default=support_ratio,
    )
    if normalized_support_ratio is None:
        normalized_support_ratio = support_ratio

    source_type = (
        str(payload.get("source_type") or default_source_type).strip().lower()
        or default_source_type
    )
    if source_type not in {"deterministic_summary", "ai_synthesis", "hybrid"}:
        source_type = default_source_type

    requires_review = bool(payload.get("requires_review")) or confidence == "low"

    return {
        "text": text,
        "source_type": source_type,
        "confidence": confidence,
        "supported_sentence_ratio": round(max(0.0, min(1.0, normalized_support_ratio)), 2),
        "requires_review": requires_review,
        "client_safe": bool(payload.get("client_safe", True)),
    }


def _build_narrative_block(
    raw_report: dict[str, Any],
    canonical_payload: dict[str, Any],
    confidence_summary: dict[str, Any],
) -> dict[str, Any]:
    existing = _as_dict(canonical_payload.get("narrative"))
    metadata = _as_dict(canonical_payload.get("metadata"))
    support_ratio = (
        _as_ratio(
            _as_dict(confidence_summary.get("grounding_status")).get("support_ratio"),
            default=0.0,
        )
        or 0.0
    )
    narrative_confidence = _normalize_confidence_level(
        confidence_summary.get("narrative_confidence"),
        default="low",
    )

    executive_summary = _normalize_narrative_block(
        existing.get("executive_summary"),
        fallback_text=(
            # Read NEW key first, falling back to the legacy persisted key.
            str(metadata.get("strategic_summary") or "").strip()
            or str(metadata.get("neural_executive_summary") or "").strip()
            or str(metadata.get("executive_summary") or "").strip()
            or str(_as_dict(raw_report.get("analysis")).get("summary") or "").strip()
        ),
        fallback_confidence=narrative_confidence,
        support_ratio=support_ratio,
        default_source_type="hybrid",
    )
    # Read NEW key first, falling back to the legacy persisted key so historical
    # ``full_report`` JSON still renders.
    competitive_positioning = _normalize_narrative_block(
        existing.get("competitive_positioning") or existing.get("market_dominance_blueprint"),
        fallback_text=(
            str(metadata.get("competitive_positioning") or "").strip()
            or str(metadata.get("market_dominance_blueprint") or "").strip()
            or None
        ),
        fallback_confidence=narrative_confidence,
        support_ratio=support_ratio,
    )

    debate_findings = existing.get("debate_findings")
    if not isinstance(debate_findings, list):
        debate_findings = existing.get("strategic_intelligence_grid")
    if not isinstance(debate_findings, list):
        debate_findings = metadata.get("debate_findings")
    if not isinstance(debate_findings, list):
        debate_findings = metadata.get("strategic_intelligence_grid")

    return {
        "executive_summary": executive_summary,
        "debate_findings": debate_findings if isinstance(debate_findings, list) else [],
        "competitive_positioning": competitive_positioning,
    }


def _normalize_recommendation_dimensions(value: Any, *, fallback: list[str]) -> list[str]:
    if isinstance(value, list):
        dimensions = [
            str(item).strip().lower()
            for item in value
            if str(item).strip().lower() in {"seo", "geo", "aeo", "overall"}
        ]
        if dimensions:
            return dimensions
    return fallback


def _normalize_expected_score_impact(value: Any) -> dict[str, float | int | None]:
    payload = _as_dict(value)
    return {
        "seo": _as_int(payload.get("seo"), default=None),
        "geo": _as_int(payload.get("geo"), default=None),
        "aeo": _as_int(payload.get("aeo"), default=None),
        "overall": _as_int(payload.get("overall"), default=None),
    }


def _normalize_recommendation_owner(value: Any, *, category: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"engineering", "content", "seo", "client", "operations"}:
        return normalized
    if category == "content":
        return "content"
    if category in {"authority", "local_authority", "entity_authority"}:
        return "seo"
    return "engineering"


def _normalize_recommendation_effort(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in {"low", "medium", "high"} else None


def _normalize_recommendation_item(item: Mapping[str, Any], *, index: int) -> dict[str, Any] | None:
    action = str(item.get("action") or "").strip()
    title = str(item.get("title") or action).strip()
    if not title and not action:
        return None

    # No fabricated category: an absent or unmapped value stays null rather
    # than silently landing in the "technical" bucket.
    raw_category = str(item.get("category") or "").strip().lower()
    category = _RECOMMENDATION_CATEGORIES.get(raw_category, raw_category) if raw_category else None
    summary = (
        str(
            item.get("summary")
            or item.get("description")
            or item.get("why_it_matters")
            or item.get("body")
            or ""
        ).strip()
        or None
    )
    rationale = str(item.get("rationale") or item.get("why") or "").strip() or summary
    # Empty leverage stays empty; keyword-guessing dimensions would fabricate
    # a score claim nobody made.
    dimensions = _normalize_recommendation_dimensions(
        item.get("cross_score_leverage") or item.get("affected_scores"),
        fallback=[],
    )
    confidence = _normalize_confidence_level(
        item.get("confidence"),
        default="medium",
    )
    source_type = str(item.get("source_type") or "deterministic_plus_ai_packaging").strip().lower()
    if source_type not in {"deterministic", "deterministic_plus_ai_packaging", "ai_inference"}:
        source_type = "deterministic_plus_ai_packaging"

    return {
        "id": str(item.get("id") or f"rec.{_slugify(title or action, default=f'item_{index}')}")[
            :128
        ],
        "priority": _as_int(item.get("priority"), default=index) or index,
        "category": category,
        "title": title or action,
        "summary": summary,
        "action": action or title,
        "rationale": rationale,
        "derived_from": _as_list_of_strings(item.get("derived_from")),
        "grounded_by_findings": _as_list_of_strings(
            item.get("grounded_by_findings")
            or item.get("evidence_refs")
            or item.get("derived_from")
        ),
        # Carried through, never derived here: a code may only originate from a
        # deterministic check, and an unknown value normalizes to None so the
        # recommendation falls back to text identity.
        "problem_code": normalize_problem_code(item.get("problem_code")),
        "expected_score_impact": _normalize_expected_score_impact(
            item.get("expected_score_impact")
        ),
        "cross_score_leverage": dimensions,
        "estimated_effort": _normalize_recommendation_effort(item.get("estimated_effort")),
        "owner": _normalize_recommendation_owner(item.get("owner"), category=category),
        "dependencies": _as_list_of_strings(item.get("dependencies")),
        "confidence": confidence,
        "source_type": source_type,
        "client_safe": bool(item.get("client_safe", True)),
        "requires_human_review": bool(item.get("requires_human_review")) or confidence == "low",
    }


def _build_recommendations_block(
    raw_report: dict[str, Any], canonical_payload: dict[str, Any]
) -> dict[str, Any]:
    existing = _as_dict(canonical_payload.get("recommendations"))
    raw_items = existing.get("items")
    if not isinstance(raw_items, list):
        raw_items = raw_report.get("suggestions")
    if not isinstance(raw_items, list):
        raw_items = canonical_payload.get("suggestions")

    items: list[dict[str, Any]] = []
    if isinstance(raw_items, list):
        for index, suggestion in enumerate(raw_items, start=1):
            if isinstance(suggestion, Mapping):
                normalized = _normalize_recommendation_item(suggestion, index=index)
                if normalized:
                    items.append(normalized)

    if not items:
        recommendations = _as_dict(raw_report.get("analysis")).get("recommendations")
        if isinstance(recommendations, list):
            for index, recommendation in enumerate(recommendations, start=1):
                if not isinstance(recommendation, str) or not recommendation.strip():
                    continue
                normalized = _normalize_recommendation_item(
                    {
                        "priority": index,
                        "title": f"Recommendation {index}",
                        "action": recommendation.strip(),
                        "category": "technical",
                    },
                    index=index,
                )
                if normalized:
                    items.append(normalized)

    items.sort(key=lambda item: (item.get("priority", 999), str(item.get("title", "")).lower()))
    return {"items": items}


def _build_competitive_block(
    canonical_payload: dict[str, Any], *, competitive_confidence: str
) -> dict[str, Any]:
    metadata = _as_dict(canonical_payload.get("metadata"))
    competitor_summary = _as_dict(metadata.get("competitor_summary"))
    existing = _as_dict(canonical_payload.get("competitive"))
    benchmark = _as_dict(existing.get("benchmark"))
    if not benchmark:
        benchmark = _as_dict(competitor_summary.get("benchmark"))

    rows = benchmark.get("rows") if isinstance(benchmark.get("rows"), list) else []
    columns = benchmark.get("columns") if isinstance(benchmark.get("columns"), list) else []
    benchmark_summary = _as_dict(benchmark.get("summary"))
    target_name = str(_as_dict(canonical_payload.get("target")).get("name") or "").strip() or None
    target_row = next((row for row in rows if isinstance(row, dict) and row.get("is_target")), None)
    competitor_rows = [row for row in rows if isinstance(row, dict) and not row.get("is_target")]

    deltas = _as_dict(canonical_payload.get("deltas_vs_target"))
    insight_pairs = [
        ("GEO visibility", _as_int(deltas.get("geo_visibility"), default=None)),
        ("AEO score", _as_int(deltas.get("aeo_score"), default=None)),
        ("Entity strength", _as_int(deltas.get("entity_strength"), default=None)),
    ]
    target_advantage = [
        f"{label} leads by {abs(value)} pts"
        for label, value in insight_pairs
        if value is not None and value < 0
    ]
    target_risks = [
        f"{label} trails by {value} pts"
        for label, value in insight_pairs
        if value is not None and value > 0
    ]
    largest_gaps = [
        f"{label}: {value:+d} pts"
        for label, value in sorted(
            [(label, value) for label, value in insight_pairs if value is not None],
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:3]
    ]

    return {
        "summary": {
            "target": target_name,
            "competitor_count": len(competitor_rows),
            "target_rank": _as_int(_as_dict(target_row).get("rank"), default=None),
            "confidence": _normalize_confidence_level(
                _as_dict(existing.get("summary")).get("confidence")
                or benchmark_summary.get("confidence")
                or competitor_summary.get("confidence"),
                default=competitive_confidence,
            ),
            "mode": str(
                benchmark_summary.get("mode") or competitor_summary.get("mode") or "grounded"
            ),
            "has_score_deltas": bool(
                benchmark_summary.get("has_score_deltas")
                if benchmark_summary.get("has_score_deltas") is not None
                else competitor_summary.get("has_score_deltas")
            ),
            "message": str(
                benchmark_summary.get("message") or competitor_summary.get("message") or ""
            ).strip()
            or None,
        },
        "benchmark": {
            "columns": columns,
            "rows": rows,
        },
        "insights": {
            "target_advantage": target_advantage,
            "target_risks": target_risks,
            "largest_gaps": largest_gaps,
        },
    }


def _build_confidence_summary(
    raw_report: dict[str, Any], canonical_payload: dict[str, Any]
) -> dict[str, Any]:
    metadata = _as_dict(canonical_payload.get("metadata"))
    competitor_summary = _as_dict(metadata.get("competitor_summary"))
    target = _as_dict(canonical_payload.get("target"))
    scores = _as_dict(canonical_payload.get("scores"))
    existing = _as_dict(canonical_payload.get("confidence"))
    narrative_present = any(
        (
            str(metadata.get("strategic_summary") or "").strip(),
            str(metadata.get("neural_executive_summary") or "").strip(),
            str(metadata.get("executive_summary") or "").strip(),
            str(metadata.get("competitive_positioning") or "").strip(),
            str(metadata.get("market_dominance_blueprint") or "").strip(),
        )
    )

    has_external_sources, external_coverage = _extract_external_source_summary(raw_report, metadata)
    grounding_status = _extract_grounding_status(
        raw_report,
        canonical_payload,
        narrative_present=narrative_present,
    )

    benchmark = _as_dict(_as_dict(metadata.get("competitor_summary")).get("benchmark"))
    rows = benchmark.get("rows") if isinstance(benchmark.get("rows"), list) else []
    competitive_confidence = _normalize_confidence_level(
        existing.get("competitive_confidence") or competitor_summary.get("confidence"),
        default="medium" if rows else "low",
    )
    narrative_confidence = _normalize_confidence_level(
        existing.get("narrative_confidence"),
        default=_confidence_from_ratio(grounding_status.get("support_ratio"), default="low"),
    )

    warnings = _as_list_of_strings(existing.get("warnings"))
    if not has_external_sources:
        warnings.append("External analytics and search data were not connected for this audit.")
    if rows and competitive_confidence == "low":
        warnings.append("Competitive benchmark confidence is reduced and should be reviewed.")
    if str(competitor_summary.get("mode") or "").strip().lower() == "exploratory":
        warnings.append(
            "Competitor discovery is exploratory only until tracked competitor audits are available."
        )
    if narrative_present and narrative_confidence == "low":
        warnings.append(
            "Strategic narrative contains low-confidence interpretation and should be reviewed."
        )

    return {
        "audit_mode": _normalize_target_type(existing.get("audit_mode") or target.get("type")),
        "has_external_data_sources": has_external_sources,
        "external_data_coverage": external_coverage,
        "finding_confidence": _normalize_confidence_level(
            existing.get("finding_confidence"),
            default="high"
            if any(scores.get(key) is not None for key in ("seo", "geo", "aeo"))
            else "medium",
        ),
        "competitive_confidence": competitive_confidence,
        "narrative_confidence": narrative_confidence,
        "warnings": list(dict.fromkeys(warnings)),
        "grounding_status": grounding_status,
    }


def _enrich_canonical_payload(
    raw_report: dict[str, Any], canonical_payload: dict[str, Any]
) -> dict[str, Any]:
    metadata = _as_dict(canonical_payload.get("metadata"))
    target = _as_dict(canonical_payload.get("target"))
    generated_at = _as_datetime(
        canonical_payload.get("generated_at")
        or metadata.get("updated_at")
        or metadata.get("created_at"),
        datetime.now(timezone.utc),
    )

    enriched = dict(canonical_payload)
    enriched["schema_version"] = str(
        canonical_payload.get("schema_version") or _CANONICAL_SCHEMA_VERSION
    )
    enriched["audit_mode"] = _normalize_target_type(
        canonical_payload.get("audit_mode") or target.get("type")
    )
    enriched["score_source"] = str(canonical_payload.get("score_source") or _PUBLIC_SCORE_SOURCE)
    enriched["generated_at"] = generated_at
    enriched["score_contract"] = _build_score_contract(raw_report, canonical_payload)
    enriched["confidence"] = _build_confidence_summary(raw_report, canonical_payload)
    enriched["narrative"] = _build_narrative_block(
        raw_report, canonical_payload, enriched["confidence"]
    )
    enriched["recommendations"] = _build_recommendations_block(raw_report, canonical_payload)
    enriched["competitive"] = _build_competitive_block(
        canonical_payload,
        competitive_confidence=_as_dict(enriched["confidence"]).get(
            "competitive_confidence", "low"
        ),
    )
    enriched["integrity_certificate"] = _build_integrity_certificate(
        raw_report=raw_report,
        canonical_payload=canonical_payload,
    )
    return enriched


# Fail-closed allowlist for metadata keys copied into the canonical result.
# Only keys a report writer or test is known to produce may pass through; an
# unknown key added upstream can no longer smuggle content into canonical
# metadata. Lockable keys cleared by _LOCKABLE_AUDIT_FEATURES locking are
# absent from the sanitized payload before this runs, so listing them here
# cannot resurrect them for unentitled plans. The exception is
# entity_analysis: deliberately NOT cleared by _lock_entities because it is
# non-gated metadata (see its comment below).
_METADATA_EXTENSION_ALLOWLIST = frozenset(
    {
        # Target and audit descriptors seeded for canonicalization and
        # asserted by adapter tests.
        "audit_target_type",
        "target_name",
        "target_url",
        "target_metadata",
        # Persisted audit metadata written by audit_runner at capture time.
        # provider/model/tier are internal keys consumed by
        # _ensure_report_provider_tier and cost reconciliation; the client-safe
        # projection blocklist strips them at the API surface, not here.
        "provider",
        "model",
        "tier",
        "warnings",
        "quick_scan",
        "requested_tier",
        "score_version",
        "page_type",
        "category",
        "market",
        "language",
        "advisor",
        "project_id",
        "workspace_id",
        "data_source_mode",
        "has_external_data_sources",
        "data_sources",
        "brand_signals_summary",
        "wikidata_entity",
        "knowledge_panel",
        "scrape_method",
        "scraped_content",
        "search_types",
        "lite_refresh",
        # Pipeline diagnostics read by smoke tests, cost services and the
        # integrity projection. Internal only, not gated report content.
        "ai_generation",
        "fallback_reason",
        "grounding_gate",
        # SIGV2-1205: per-engine measurement rows attached to the audit
        # snapshot, and the recomputation provenance written by the fallback
        # canonicalization path when a stored score is absent.
        "engines",
        "score_provenance",
        "score_source",
        "raw_ai_scores",
        "deterministic_scores",
        # Written by audit_normalization_service for the same payload.
        "current_plan",
        "query_category",
        # Render-time seeds consumed by the PDF context builders.
        "report_suite",
        # Non-gated passthrough, deliberately not cleared by _lock_entities:
        # the `brand` search-type heuristic prefers
        # entity_analysis.brand_trust_score (services/query_taxonomy.py:253)
        # on every plan, and the PDF entity_strength column
        # (_entity_strength_score, assembler.py) only renders on competitors
        # reports, which no unentitled plan can obtain.
        "entity_analysis",
        # Deterministic AEO+GEO roll-up attached by attach_aio_view at
        # response time (app/services/aio_view.py). Non-gated, consumed by
        # the aio report-kind sections.
        "aio",
        # Lock metadata needed to render withheld-section placeholders.
        "locked_sections",
        # Credit cost disclosure read by the integrity page builder.
        "estimated_credit_cost",
        "consumed_credit_cost",
        # Narrative metadata written into report metadata by the debate
        # pipeline and consumed by the PDF context builders. These keys are
        # cleared by advanced-reporting locking for unentitled plans; the
        # allowlist cannot resurrect them because the sanitized payload no
        # longer carries them.
        "executive_summary",
        "neural_executive_summary",
        "strategic_summary",
        "strategic_intelligence_grid",
        "market_dominance_blueprint",
        "competitive_positioning",
        "debate_findings",
        # Asserted by adapter tests as passthrough but with no current
        # production writer. Kept so those assertions stay meaningful;
        # a future writer inherits the allowlist entry automatically.
        "intelligence_dossier",
        "aeo_citation_probability",
        # Dual-track grounding metadata asserted by adapter tests; present
        # only on payloads whose plan carried brand-integrity entitlement.
        "dual_track_shadow",
        "dual_track_grounding",
        "dual_track_grounding_enabled",
        "grounding_profile",
        "integrity_certificate_summary",
        "unified_truth_context_version",
        "track_a_claim_count",
        "track_b_claim_count",
    }
)


def _extract_metadata_extensions(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key in _METADATA_EXTENSION_ALLOWLIST}


def _normalize_seo_checks(raw_checks: Any) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    if not isinstance(raw_checks, list):
        return checks

    for item in raw_checks:
        if not isinstance(item, dict):
            continue

        check_name = str(item.get("name") or item.get("check") or item.get("id") or "").strip()
        if not check_name:
            continue

        checks.append(
            {
                "name": check_name,
                "status": str(item.get("status") or "unknown").strip().lower() or "unknown",
                "passed": bool(item.get("passed")) if item.get("passed") is not None else None,
                "details": str(item.get("details") or item.get("message") or "").strip() or None,
            }
        )
    return checks


def _extract_technical_signals(
    raw_report: dict[str, Any], analysis: dict[str, Any], performance: dict[str, Any]
) -> dict[str, Any]:
    network = raw_report.get("network") if isinstance(raw_report.get("network"), dict) else {}
    legacy_seo_checks = (
        raw_report.get("seo_audit_checks")
        or raw_report.get("seo_checks")
        or analysis.get("seo_audit_checks")
        or analysis.get("seo_checks")
    )

    return {
        "performance": {
            "score": _as_score(
                performance.get("performance_score", analysis.get("performance_score")),
                default=None,
            ),
            "lcp_ms": _as_int(performance.get("lcp_ms", analysis.get("lcp_ms")), default=None),
            "cls": _as_ratio(performance.get("cls", analysis.get("cls")), default=None),
        },
        "network": {
            "http_version": str(network.get("http_version") or "").strip() or None,
            "supports_http2": bool(network.get("supports_http2")),
            "supports_http3": bool(
                network.get("supports_http3") or network.get("supports_http3_inferred")
            ),
            "supports_http3_inferred": bool(network.get("supports_http3_inferred")),
        },
        "seo_audit_checks": _normalize_seo_checks(legacy_seo_checks),
    }


def _extract_entity_analysis(analysis: dict[str, Any]) -> dict[str, Any]:
    raw = analysis.get("entity_analysis")
    if not isinstance(raw, dict):
        return {}

    dominant_entities = raw.get("dominant_entities")
    return {
        "entity_clarity_score": _as_score(raw.get("entity_clarity_score"), default=0.0),
        "brand_trust_score": _as_score(raw.get("brand_trust_score"), default=0.0),
        "knowledge_graph_presence": bool(raw.get("knowledge_graph_presence")),
        "dominant_entities": [str(item) for item in dominant_entities if isinstance(item, str)]
        if isinstance(dominant_entities, list)
        else [],
    }


def _extract_aeo_signals(analysis: dict[str, Any]) -> dict[str, Any]:
    raw = analysis.get("aeo_signals")
    if not isinstance(raw, dict):
        return {}

    key_recommendations = raw.get("key_recommendations")
    return {
        "answerability_score": _as_score(raw.get("answerability_score"), default=0.0),
        "content_freshness_score": _as_score(raw.get("content_freshness_score"), default=0.0),
        "schema_completeness": _as_score(raw.get("schema_completeness"), default=0.0),
        "voice_readiness_score": _as_score(raw.get("voice_readiness_score"), default=0.0),
        "tone_of_voice_score": _as_score(raw.get("tone_of_voice_score"), default=0.0),
        "featured_snippet_likelihood": _as_score(
            raw.get("featured_snippet_likelihood"), default=0.0
        ),
        "key_recommendations": [str(item) for item in key_recommendations if isinstance(item, str)]
        if isinstance(key_recommendations, list)
        else [],
    }


def _extract_geo_signals(analysis: dict[str, Any]) -> dict[str, Any]:
    raw = analysis.get("geo_signals")
    if not isinstance(raw, dict):
        return {}

    return {
        "citation_consistency_score": _as_score(raw.get("citation_consistency_score"), default=0.0),
        "local_authority_score": _as_score(raw.get("local_authority_score"), default=0.0),
        "relevance_score": _as_score(raw.get("relevance_score"), default=0.0),
        "competitor_overlap_score": _as_score(raw.get("competitor_overlap_score"), default=0.0),
        "topical_depth_score": _as_score(raw.get("topical_depth_score"), default=0.0),
        "freshness_signal": _as_score(raw.get("freshness_signal"), default=0.0),
    }


def _resolve_entities(raw_report: dict[str, Any], analysis: dict[str, Any]) -> list[str]:
    candidates = [
        raw_report.get("entities"),
        analysis.get("entities"),
        analysis.get("entities_detected"),
    ]

    for candidate in candidates:
        entities = _as_list_of_strings(candidate)
        if entities:
            return entities

    return []


def to_canonical_audit_result(
    raw_report: dict[str, Any] | None,
    *,
    audit_url: str | None,
    audit_target_type: str = "website",
    target_name: str | None = None,
    target_url: str | None = None,
    target_metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
    plan: str = "plan_starter",
    version: str = "2.0",
) -> dict[str, Any]:
    if isinstance(raw_report, dict):
        try:
            validation_payload = _prepare_raw_report_for_validation(raw_report)
            if isinstance(validation_payload, dict):
                validation_metadata = (
                    validation_payload.get("metadata")
                    if isinstance(validation_payload.get("metadata"), dict)
                    else {}
                )
                validation_site = (
                    validation_payload.get("site")
                    if isinstance(validation_payload.get("site"), dict)
                    else {}
                )
                if not isinstance(validation_payload.get("target"), dict):
                    seeded_target_url = (
                        _normalize_target_url(validation_payload.get("target_url"))
                        or _normalize_target_url(validation_metadata.get("target_url"))
                        or _normalize_target_url(validation_site.get("url"))
                        or _normalize_target_url(validation_payload.get("url"))
                        or _normalize_target_url(audit_url)
                    )
                    seeded_target_type = _normalize_target_type(
                        validation_payload.get("audit_target_type")
                        or validation_metadata.get("audit_target_type")
                        or audit_target_type
                    )
                    seeded_target_name = (
                        _normalize_target_name(validation_payload.get("target_name"))
                        or _normalize_target_name(validation_metadata.get("target_name"))
                        or seeded_target_url
                        or ("Brand audit" if seeded_target_type == "brand" else None)
                    )
                    seeded_target_metadata = {
                        **_normalize_target_metadata(validation_payload.get("target_metadata")),
                        **_normalize_target_metadata(validation_metadata.get("target_metadata")),
                        **_normalize_target_metadata(target_metadata),
                    }
                    validation_payload["target"] = {
                        "type": seeded_target_type,
                        "name": seeded_target_name,
                        "url": seeded_target_url,
                        "metadata": seeded_target_metadata,
                    }
                if validation_payload.get("generated_at") is None:
                    validation_payload["generated_at"] = (
                        validation_metadata.get("updated_at")
                        or validation_metadata.get("created_at")
                        or created_at
                        or datetime.now(timezone.utc)
                    )
            validated_model = AuditResult.model_validate(validation_payload)
            validated = validated_model.model_dump()

            resolved_plan = str(plan or "plan_starter")
            metadata = validated.get("metadata", {})
            target_payload = (
                validated.get("target") if isinstance(validated.get("target"), dict) else {}
            )
            if isinstance(metadata, dict):
                if metadata.get("plan") != resolved_plan:
                    metadata["plan"] = resolved_plan
                metadata["audit_target_type"] = _normalize_target_type(target_payload.get("type"))
                metadata["target_name"] = _normalize_target_name(target_payload.get("name"))
                metadata["target_url"] = _normalize_target_url(target_payload.get("url"))
                metadata["target_metadata"] = _normalize_target_metadata(
                    target_payload.get("metadata")
                )
                validated["metadata"] = metadata
            return AuditResult.model_validate(
                _deep_prepare_for_validation(
                    _enrich_canonical_payload(raw_report, validated),
                    AuditResult,
                )
            ).model_dump(mode="json")
        except Exception as exc:
            # A report that already looks canonical (scores + pillar sections) but
            # fails strict validation used to drop into the silent rebuild below,
            # which zeroed every stored pillar sub-score. Log loudly in that case
            # so a stored-but-unservable report cannot hide; a raw, non-canonical
            # write-path payload failing validation is routine and stays at debug.
            if isinstance(raw_report.get("scores"), dict) and isinstance(
                raw_report.get("target"), dict
            ):
                logger.warning(
                    "Stored canonical audit report failed re-validation; rebuilding "
                    "from stored section values via fallback path: %s",
                    exc,
                )
            else:
                logger.debug("Happy-path re-validation failed, using fallback: %s", exc)
    else:
        raw_report = {}

    analysis = (
        raw_report.get("analysis", {}) if isinstance(raw_report.get("analysis"), dict) else {}
    )
    performance = (
        raw_report.get("performance", {}) if isinstance(raw_report.get("performance"), dict) else {}
    )
    metadata = (
        raw_report.get("metadata", {}) if isinstance(raw_report.get("metadata"), dict) else {}
    )
    network = raw_report.get("network", {}) if isinstance(raw_report.get("network"), dict) else {}
    raw_aeo_section = raw_report.get("aeo") if isinstance(raw_report.get("aeo"), dict) else {}
    raw_geo_section = raw_report.get("geo") if isinstance(raw_report.get("geo"), dict) else {}
    raw_seo_section = raw_report.get("seo") if isinstance(raw_report.get("seo"), dict) else {}
    raw_scores_section = (
        raw_report.get("scores") if isinstance(raw_report.get("scores"), dict) else {}
    )
    scrape_metadata = (
        metadata.get("scrape_metadata", {})
        if isinstance(metadata.get("scrape_metadata"), dict)
        else {}
    )
    raw_target = raw_report.get("target") if isinstance(raw_report.get("target"), dict) else {}
    raw_target_metadata = _normalize_target_metadata(raw_target.get("metadata"))

    resolved_target_type = _normalize_target_type(
        audit_target_type
        or raw_target.get("type")
        or metadata.get("audit_target_type")
        or raw_report.get("audit_target_type")
    )
    resolved_target_url = (
        _normalize_target_url(target_url)
        or _normalize_target_url(raw_target.get("url"))
        or _normalize_target_url(metadata.get("target_url"))
        or _normalize_target_url(raw_report.get("target_url"))
        or _normalize_target_url(audit_url)
    )
    resolved_target_name = (
        _normalize_target_name(target_name)
        or _normalize_target_name(raw_target.get("name"))
        or _normalize_target_name(metadata.get("target_name"))
        or _normalize_target_name(raw_report.get("target_name"))
    )
    resolved_target_metadata = {
        **raw_target_metadata,
        **_normalize_target_metadata(metadata.get("target_metadata")),
        **_normalize_target_metadata(raw_report.get("target_metadata")),
        **_normalize_target_metadata(target_metadata),
    }
    if resolved_target_type == "website" and not resolved_target_name and resolved_target_url:
        resolved_target_name = resolved_target_url
    if resolved_target_type == "brand" and not resolved_target_name:
        resolved_target_name = "Brand audit"
    canonical_site_url = resolved_target_url or _normalize_target_url(audit_url)

    # Build schema analysis from available data
    schema_analysis = {
        "detected_schema_types": raw_aeo_section.get("schema_health", {}).get(
            "detected_schema_types", []
        )
        if isinstance(raw_aeo_section.get("schema_health"), dict)
        else [],
        "coverage_percent": raw_aeo_section.get("schema_coverage", {}).get("coverage_percent", 0.0)
        if isinstance(raw_aeo_section.get("schema_coverage"), dict)
        else 0.0,
        "coverage_by_type": raw_aeo_section.get("schema_coverage", {}).get("coverage_by_type", {})
        if isinstance(raw_aeo_section.get("schema_coverage"), dict)
        else {},
    }

    timestamp = created_at or datetime.now(timezone.utc)
    timestamp_utc = timestamp.astimezone(timezone.utc)

    # Use new deterministic scoring engine v2.0 for consistent scores
    # Extract brand signals for brand audits (stored by audit_runner)
    _brand_signals_raw = raw_report.get("_brand_signals") if isinstance(raw_report, dict) else None
    _detected_page_type = metadata.get("page_type") or raw_report.get("page_type") or None

    # Build AI findings metadata for brand-no-URL score floor
    _ai_findings_meta: dict[str, Any] | None = None
    if resolved_target_type == "brand" and not canonical_site_url:
        _seo_f = analysis.get("seo_findings", [])
        _geo_f = analysis.get("geo_findings", [])
        _aeo_f = analysis.get("aeo_findings", [])
        _summary = analysis.get("summary") or analysis.get("intelligence_summary") or ""
        _recs = raw_report.get("suggestions", [])
        _ai_findings_meta = {
            "seo_findings_count": len(_seo_f) if isinstance(_seo_f, list) else 0,
            "geo_findings_count": len(_geo_f) if isinstance(_geo_f, list) else 0,
            "aeo_findings_count": len(_aeo_f) if isinstance(_aeo_f, list) else 0,
            "summary_length": len(_summary) if isinstance(_summary, str) else 0,
            "recommendations_count": len(_recs) if isinstance(_recs, list) else 0,
        }

    deterministic_scores = calculate_deterministic_scores(
        performance_metrics=performance,
        schema_analysis=schema_analysis,
        scrape_metadata=scrape_metadata
        or {
            "title": metadata.get("title") or metadata.get("target_name") or resolved_target_name,
            "url": canonical_site_url or "",
            "language": metadata.get("language"),
            "locale": metadata.get("locale") or metadata.get("market"),
            "headings": metadata.get("headings"),
        },
        network_data=network,
        content=raw_report.get("markdown_content") or metadata.get("scraped_content") or "",
        seo_findings=analysis.get("seo_findings", []),
        geo_findings=analysis.get("geo_findings", []),
        aeo_findings=analysis.get("aeo_findings", []),
        brand_signals=_brand_signals_raw if isinstance(_brand_signals_raw, dict) else None,
        brand_name=resolved_target_name or None,
        page_type=_detected_page_type if isinstance(_detected_page_type, str) else None,
        ai_findings_meta=_ai_findings_meta,
    )

    # When the report is canonical-shaped (it carries `scores`), the stored
    # headline scores win; the deterministic recompute is only a fallback for
    # write-path payloads that never persisted them.
    seo_score = _stored_score(raw_scores_section, "seo", deterministic_scores["seo_score"])
    geo_score = _stored_score(raw_scores_section, "geo", deterministic_scores["geo_score"])
    aeo_score = _stored_score(raw_scores_section, "aeo", deterministic_scores["aeo_score"])
    overall_score = _stored_score(
        raw_scores_section, "overall", deterministic_scores["overall_score"]
    )

    # SIGV2-1205: when a canonical-shaped report carries no stored pillar score
    # and the deterministic fallback supplies one, the payload must say so.
    # A recomputed value is not a stored measurement; the provenance record is
    # what lets a reader tell them apart.
    scoring_version = str(deterministic_scores.get("version") or "")
    score_provenance = {
        key: (
            {"stored": True}
            if _as_score(raw_scores_section.get(key), default=None) is not None
            else {
                "stored": False,
                "source": "deterministic",
                "version": scoring_version or None,
            }
        )
        for key in ("seo", "geo", "aeo", "overall")
    }

    scores_available = any(score > 0 for score in (seo_score, geo_score, aeo_score))
    audit_outcome = str(
        metadata.get("audit_outcome") or ("completed" if scores_available else "degraded")
    )

    suggestions: list[dict[str, Any]] = []
    structured_suggestions = raw_report.get("suggestions")
    if isinstance(structured_suggestions, list):
        for index, suggestion in enumerate(structured_suggestions, start=1):
            if not isinstance(suggestion, dict):
                continue
            action = str(suggestion.get("action") or "").strip()
            if not action:
                continue
            title = str(suggestion.get("title") or action).strip()
            if not title:
                continue
            suggestions.append(
                {
                    "priority": _as_int(suggestion.get("priority"), default=index) or index,
                    "title": title,
                    "action": action,
                    "category": str(suggestion.get("category") or "Technical"),
                }
            )

    if not suggestions:
        recommendations = analysis.get("recommendations")
        if isinstance(recommendations, list):
            for index, recommendation in enumerate(recommendations, start=1):
                if isinstance(recommendation, str) and recommendation.strip():
                    suggestions.append(
                        {
                            "priority": index,
                            "title": f"Recommendation {index}",
                            "action": recommendation,
                            "category": "Technical",
                        }
                    )

    seo_components = (deterministic_scores.get("seo_breakdown") or {}).get("components", {})
    geo_components = (deterministic_scores.get("geo_breakdown") or {}).get("components", {})
    aeo_components = (deterministic_scores.get("aeo_breakdown") or {}).get("components", {})
    aeo_signals = (
        analysis.get("aeo_signals") if isinstance(analysis.get("aeo_signals"), dict) else {}
    )
    # AEOAnswerabilityService writes its findings into aeo.answerability_audit (see
    # audit_runner.py), not to aeo.readability_findings/rewrite_suggestions directly.
    # Fall back to that nested path so the real, computed values reach the canonical
    # report instead of always resolving to an empty list.
    answerability_audit_raw = (
        raw_aeo_section.get("answerability_audit")
        if isinstance(raw_aeo_section.get("answerability_audit"), dict)
        else {}
    )

    canonical_payload = {
        "target": {
            "type": resolved_target_type,
            "name": resolved_target_name,
            "url": canonical_site_url,
            "metadata": resolved_target_metadata,
        },
        "site": {
            "url": canonical_site_url,
            "market": str(metadata.get("market") or "global"),
            "language": str(metadata.get("language") or "en"),
        },
        "seo": {
            "onpage": _stored_score(raw_seo_section, "onpage", seo_score),
            "performance": _stored_score(
                raw_seo_section,
                "performance",
                _as_score(performance.get("performance_score"), default=seo_score),
            ),
            "indexing": _stored_score(
                raw_seo_section,
                "indexing",
                _as_score(analysis.get("indexing_score"), default=seo_score),
            ),
            "core_web_vitals": _stored_score(
                raw_seo_section,
                "core_web_vitals",
                _as_score(seo_components.get("core_web_vitals"), default=None),
            ),
            "technical_seo": _stored_score(
                raw_seo_section,
                "technical_seo",
                _as_score(seo_components.get("technical_seo"), default=None),
            ),
            "onpage_content": _stored_score(
                raw_seo_section,
                "onpage_content",
                _as_score(seo_components.get("onpage_content"), default=None),
            ),
            "eeat_trust": _stored_score(
                raw_seo_section,
                "eeat_trust",
                _as_score(seo_components.get("eeat_trust"), default=None),
            ),
            "security_accessibility": _stored_score(
                raw_seo_section,
                "security_accessibility",
                _as_score(seo_components.get("security_accessibility"), default=None),
            ),
        },
        "geo": {
            "visibility_index": _stored_score(raw_geo_section, "visibility_index", geo_score),
            "citation_share": _stored_score(
                raw_geo_section,
                "citation_share",
                _as_score(analysis.get("citation_share"), default=None),
            ),
            "brand_anchor": _stored_score(
                raw_geo_section,
                "brand_anchor",
                _as_score(analysis.get("brand_anchor"), default=None),
            ),
            "advanced_local_schema": _stored_score(
                raw_geo_section,
                "advanced_local_schema",
                _as_score(geo_components.get("advanced_local_schema"), default=None),
            ),
            "napw_completeness": _stored_score(
                raw_geo_section,
                "napw_completeness",
                _as_score(geo_components.get("napw_completeness"), default=None),
            ),
            "spatial_content": _stored_score(
                raw_geo_section,
                "spatial_content",
                _as_score(geo_components.get("spatial_content"), default=None),
            ),
            "content_citability": _stored_score(
                raw_geo_section,
                "content_citability",
                _as_score(geo_components.get("content_citability"), default=None),
            ),
            "source_authority": _stored_score(
                raw_geo_section,
                "source_authority",
                _as_score(geo_components.get("source_authority"), default=None),
            ),
            "entity_clarity": _stored_score(
                raw_geo_section,
                "entity_clarity",
                _as_score(geo_components.get("entity_clarity"), default=None),
            ),
            "brand_citation": _stored_score(
                raw_geo_section,
                "brand_citation",
                _as_score(geo_components.get("brand_citation"), default=None),
            ),
            "visibility_audit": raw_geo_section.get("visibility_audit")
            if isinstance(raw_geo_section.get("visibility_audit"), dict)
            else {},
        },
        "aeo": {
            "answerability_score": _stored_score(
                raw_aeo_section,
                "answerability_score",
                _as_score(aeo_signals.get("answerability_score"), default=aeo_score),
            ),
            "extractable_pages": _as_int(
                raw_aeo_section.get("extractable_pages"),
                default=_as_int(analysis.get("extractable_pages"), default=None),
            ),
            "schema_health": raw_aeo_section.get("schema_health")
            if isinstance(raw_aeo_section.get("schema_health"), dict)
            else {},
            "schema_coverage": raw_aeo_section.get("schema_coverage")
            if isinstance(raw_aeo_section.get("schema_coverage"), dict)
            else {},
            "readability_score": _as_ratio(
                aeo_signals.get("content_freshness_score")
                if "content_freshness_score" in aeo_signals
                else raw_aeo_section.get("readability_score"),
                default=None,
            ),
            "readability_findings": [
                str(item)
                for item in (
                    raw_aeo_section.get("readability_findings")
                    or answerability_audit_raw.get("readability_findings")
                    or []
                )
                if isinstance(item, str)
            ],
            "rewrite_suggestions": [
                item
                for item in (
                    raw_aeo_section.get("rewrite_suggestions")
                    or answerability_audit_raw.get("rewrite_suggestions")
                    or []
                )
                if isinstance(item, dict)
            ],
            # V3 granular sub-scores
            "llm_schema_readiness": _stored_score(
                raw_aeo_section,
                "llm_schema_readiness",
                _as_score(aeo_components.get("llm_schema_readiness"), default=None),
            ),
            "semantic_entity_density": _stored_score(
                raw_aeo_section,
                "semantic_entity_density",
                _as_score(aeo_components.get("semantic_entity_density"), default=None),
            ),
            "information_gain": _stored_score(
                raw_aeo_section,
                "information_gain",
                _as_score(aeo_components.get("information_gain"), default=None),
            ),
            "snippet_formatting": _stored_score(
                raw_aeo_section,
                "snippet_formatting",
                _as_score(aeo_components.get("snippet_formatting"), default=None),
            ),
            "answerability_audit": answerability_audit_raw,
        },
        "entities": _resolve_entities(raw_report, analysis),
        "competitors": [
            {
                "name": str(item.get("name")),
                "score": _as_score(item.get("score"), default=None),
                "source": str(item.get("source") or "unknown"),
                "confidence_score": _as_ratio(item.get("confidence_score"), default=0.0),
                # Absent competitor measurements stay absent; a measured 0
                # still round-trips as 0 (SIGV2-1205).
                "geo_visibility": _as_score(item.get("geo_visibility"), default=None),
                "aeo_score": _as_score(item.get("aeo_score"), default=None),
                "entity_strength": _as_score(item.get("entity_strength"), default=None),
                "rank": _as_int(item.get("rank"), default=0),
            }
            for item in raw_report.get("competitors", [])
            if isinstance(item, dict) and item.get("name")
        ],
        "suggestions": suggestions,
        "scores": {
            "seo": seo_score,
            "geo": geo_score,
            "aeo": aeo_score,
            "overall": overall_score,
            "seo_breakdown": deterministic_scores.get("seo_breakdown"),
            "geo_breakdown": deterministic_scores.get("geo_breakdown"),
            "aeo_breakdown": deterministic_scores.get("aeo_breakdown"),
            "scoring_version": deterministic_scores.get("version", "2.0"),
            **(
                {"dimension_relevance": deterministic_scores["dimension_relevance"]}
                if "dimension_relevance" in deterministic_scores
                else {}
            ),
            **(
                {"na_dimensions": deterministic_scores["na_dimensions"]}
                if "na_dimensions" in deterministic_scores
                else {}
            ),
        },
        "metadata": {
            "created_at": _as_datetime(metadata.get("created_at"), timestamp_utc),
            "updated_at": _as_datetime(metadata.get("updated_at"), timestamp_utc),
            "plan": str(plan or metadata.get("plan") or "plan_starter"),
            "version": str(metadata.get("version") or version),
            "service_status": metadata.get("service_status")
            if isinstance(metadata.get("service_status"), dict)
            else {},
            "service_errors": metadata.get("service_errors")
            if isinstance(metadata.get("service_errors"), dict)
            else {},
            "competitor_summary": metadata.get("competitor_summary")
            if isinstance(metadata.get("competitor_summary"), dict)
            else (
                raw_report.get("competitor_summary")
                if isinstance(raw_report.get("competitor_summary"), dict)
                else {}
            ),
            "scores_available": bool(metadata.get("scores_available", scores_available)),
            "audit_outcome": audit_outcome,
            "intent": str(metadata.get("intent")).strip().lower()
            if str(metadata.get("intent") or "").strip().lower()
            in {"informational", "transactional", "navigational"}
            else None,
            "query_type": resolve_query_type(
                query_type=metadata.get("query_type") or metadata.get("queryType"),
                intent=metadata.get("intent"),
            ),
            "technical_signals": _extract_technical_signals(raw_report, analysis, performance),
            "score_provenance": score_provenance,
            "audit_target_type": resolved_target_type,
            "target_name": resolved_target_name,
            "target_url": canonical_site_url,
            "target_metadata": resolved_target_metadata,
            "entity_analysis": _extract_entity_analysis(analysis),
            "aeo_signals": _extract_aeo_signals(analysis),
            "geo_signals": _extract_geo_signals(analysis),
            "executive_summary": str(analysis.get("executive_dossier") or "").strip() or None,
            "intelligence_dossier": analysis.get("findings")
            if isinstance(analysis.get("findings"), list)
            else None,
            "aeo_citation_probability": {
                "score": _as_score(analysis.get("citation_probability_score"), default=None),
                "primary_blockers": [],
                "citation_readiness": "Ready"
                if (_as_score(analysis.get("citation_probability_score"), default=0.0) or 0.0) >= 70
                else "Partial"
                if (_as_score(analysis.get("citation_probability_score"), default=0.0) or 0.0) >= 40
                else "Blocked",
            }
            if analysis.get("citation_probability_score") is not None
            else None,
            # De-jargoned key (derives from ``strategic_roadmap``). Kept distinct
            # from ``executive_summary`` (which maps ``executive_dossier``) so the
            # two narrative sources are never conflated. Read sites fall back to
            # the legacy ``neural_executive_summary`` key for old persisted reports.
            "strategic_summary": str(analysis.get("strategic_roadmap") or "").strip() or None,
            # De-jargoned metadata keys. The canonical LLM-contract keys
            # (``neural_intelligence_grid`` / ``market_dominance_projection``)
            # are read here and surfaced under the renamed metadata keys.
            "debate_findings": analysis.get("neural_intelligence_grid")
            if isinstance(analysis.get("neural_intelligence_grid"), list)
            else None,
            "competitive_positioning": str(
                analysis.get("market_dominance_projection") or ""
            ).strip()
            or None,
            **_extract_metadata_extensions(metadata),
        },
        "deltas_vs_target": _normalize_benchmark_delta(raw_report.get("deltas_vs_target")),
        "hallucination": _normalize_hallucination(raw_report.get("hallucination")),
    }

    return AuditResult.model_validate(
        _enrich_canonical_payload(raw_report, canonical_payload)
    ).model_dump(mode="json")


def extract_canonical_recommendation_items(report: Any) -> list[dict[str, Any]]:
    if not isinstance(report, dict):
        return []

    block = _build_recommendations_block(report, report)
    raw_items = block.get("items")
    if not isinstance(raw_items, list):
        return []

    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            continue
        items.append({**item, "index": index})
    return items


def extract_canonical_recommendation_texts(report: Any, *, limit: int | None = None) -> list[str]:
    items = extract_canonical_recommendation_items(report)
    texts: list[str] = []
    for item in items:
        text = str(item.get("action") or item.get("title") or "").strip()
        if not text:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def _normalize_recommendation_consumer_key(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip().lower()
    action = str(item.get("action") or "").strip().lower()
    category = str(item.get("category") or "").strip().lower()
    return "|".join(part for part in (title, action, category) if part)


def extract_normalized_recommendation_items(
    report: Any, *, limit: int | None = None
) -> list[dict[str, Any]]:
    if not isinstance(report, dict):
        return []

    rows: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    def append_from(value: Any, *, fallback_category: str | None = None) -> bool:
        if not isinstance(value, list):
            return False

        for entry in value:
            if isinstance(entry, str):
                normalized = _normalize_recommendation_item(
                    {
                        "title": entry,
                        "action": entry,
                        "category": fallback_category,
                    },
                    index=len(rows) + 1,
                )
            elif isinstance(entry, Mapping):
                normalized = _normalize_recommendation_item(
                    {
                        **entry,
                        "category": entry.get("category") or fallback_category,
                    },
                    index=len(rows) + 1,
                )
            else:
                continue

            if not normalized:
                continue

            dedupe_key = _normalize_recommendation_consumer_key(normalized)
            if dedupe_key and dedupe_key in seen_keys:
                continue

            if dedupe_key:
                seen_keys.add(dedupe_key)
            rows.append({**normalized, "index": len(rows)})
            if limit is not None and len(rows) >= limit:
                return True
        return False

    if append_from(extract_canonical_recommendation_items(report)):
        return rows

    top_level_recommendations = report.get("recommendations")
    if isinstance(top_level_recommendations, list):
        if append_from(top_level_recommendations):
            return rows

    if append_from(report.get("prioritized_actions")):
        return rows
    if append_from(report.get("priority_actions")):
        return rows
    if append_from(report.get("suggestions")):
        return rows

    analysis = _as_dict(report.get("analysis"))
    append_from(analysis.get("recommendations"))
    return rows


def extract_normalized_recommendation_texts(report: Any, *, limit: int | None = None) -> list[str]:
    texts: list[str] = []
    for item in extract_normalized_recommendation_items(report, limit=limit):
        text = str(item.get("action") or item.get("title") or "").strip()
        if not text:
            continue
        texts.append(text)
        if limit is not None and len(texts) >= limit:
            break
    return texts


def extract_canonical_entities(report: Any, *, limit: int | None = None) -> list[str]:
    if not isinstance(report, dict):
        return []

    analysis = _as_dict(report.get("analysis"))
    entities = _as_list_of_strings(report.get("entities")) or _resolve_entities(report, analysis)
    if limit is None:
        return entities
    return entities[:limit]


def extract_canonical_schema_coverage(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}

    aeo = _as_dict(report.get("aeo"))
    schema_coverage = _as_dict(aeo.get("schema_coverage"))
    if schema_coverage:
        return schema_coverage

    analysis = _as_dict(report.get("analysis"))
    return _as_dict(analysis.get("schema_coverage"))


def _sanitize_metadata_extensions_for_client(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        lowered = str(key).strip().lower()
        if lowered in _CLIENT_SAFE_METADATA_BLOCKLIST:
            continue
        if lowered in {"plan", "service_status", "service_errors"}:
            continue
        sanitized[key] = value
    return sanitized


def _strip_client_unsafe_keys(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).strip().lower()
            if lowered in _CLIENT_SAFE_METADATA_BLOCKLIST:
                continue
            cleaned[key] = _strip_client_unsafe_keys(item)
        return cleaned
    if isinstance(value, list):
        return [_strip_client_unsafe_keys(item) for item in value]
    return value


def to_client_safe_audit(audit: dict[str, Any] | None) -> dict[str, Any]:
    canonical = dict(audit) if isinstance(audit, dict) else {}
    safe = _strip_client_unsafe_keys(canonical)
    safe.pop("raw_ai_scores", None)
    safe.pop("hallucination", None)

    metadata = _sanitize_metadata_extensions_for_client(_as_dict(safe.get("metadata")))
    safe["metadata"] = metadata

    recommendations = _as_dict(safe.get("recommendations"))
    if isinstance(recommendations.get("items"), list):
        recommendations["items"] = [
            item
            for item in recommendations["items"]
            if isinstance(item, dict) and bool(item.get("client_safe", True))
        ]
        safe["recommendations"] = recommendations

    narrative = _as_dict(safe.get("narrative"))
    # Include legacy keys so historical persisted reports are still sanitized.
    for key in (
        "executive_summary",
        "competitive_positioning",
        "market_dominance_blueprint",
    ):
        block = _as_dict(narrative.get(key))
        if block and not bool(block.get("client_safe", True)):
            narrative[key] = None
    safe["narrative"] = narrative
    return safe


def to_whitelabel_safe_audit(audit: dict[str, Any] | None) -> dict[str, Any]:
    safe = to_client_safe_audit(audit)
    metadata = _as_dict(safe.get("metadata"))
    metadata.pop("vendor_name", None)
    safe["metadata"] = metadata
    return safe
