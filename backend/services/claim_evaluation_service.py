from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from services.ai_routing_policy import normalize_audit_tier
from services.claim_taxonomy_service import ClaimTaxonomyService


logger = logging.getLogger(__name__)

DUAL_TRACK_SHADOW_SCHEMA_VERSION = "dual-track-shadow-1"

STRICT_FACTUAL_GROUNDING = "strict_factual_grounding"
PRESCRIPTIVE_DERIVATION_REVIEW = "prescriptive_derivation_review"
MIXED_SPLIT_RESOLUTION = "mixed_split_resolution"

TRACK_B_LLM_SHADOW_MODE = "llm_shadow"
TRACK_B_DETERMINISTIC_SHADOW_MODE = "deterministic_shadow"
TRACK_B_JUDGE_UNAVAILABLE_MODE = "judge_unavailable"
TRACK_B_HYBRID_SHADOW_MODE = "hybrid_shadow"
TRACK_B_NOT_APPLICABLE_MODE = "not_applicable"
TRACK_B_NEEDS_MANUAL_REVIEW = "needs_manual_review"
TRACK_B_MANUALLY_APPROVED = "manually_approved"
TRACK_B_MANUALLY_REFUSED = "manually_refused"

SMART_TIER_JUDGE_CLAIM_LIMIT = 10
"""Maximum number of Track B claims to send to the LLM judge at smart tier.
Claims are ranked by deterministic severity (lowest certainty first) and only
the top N are LLM-evaluated; the rest stay deterministic-only."""

_TRACK_B_HARD_FAIL_REASON_CODES = {
    "unsupported_premise_ref",
    "invented_site_fact",
    "unsupported_location",
    "unsupported_service_label",
    "unsupported_benchmark",
    "track_b_judge_unavailable",
}
# Soft-fail codes produce "flagged" instead of "omitted", giving the claim
# a chance to pass grounding if the composite scores are strong enough.
_TRACK_B_SOFT_FAIL_REASON_CODES = {
    "no_supported_problem",
    "generic_advice",
}
_TRACK_B_REASON_CODE_PREFERENCE = (
    "track_b_judge_unavailable",
    "invented_site_fact",
    "unsupported_location",
    "unsupported_service_label",
    "unsupported_benchmark",
    "no_supported_problem",
    "unsupported_premise_ref",
    "generic_advice",
    "weak_action_problem_fit",
    "vision_only_overreach",
    "problem_already_solved",
    "needs_narrower_wording",
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "if",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "with",
}
_SITE_SPECIFIC_TOKENS = {
    "homepage",
    "home",
    "hero",
    "h1",
    "faq",
    "schema",
    "title",
    "page",
    "pages",
    "copy",
    "header",
    "footer",
}
_GENERIC_ADVICE_PHRASES = (
    "improve your content strategy",
    "improve content strategy",
    "improve your seo",
    "improve seo",
    "improve user experience",
    "improve the website",
)
_UNSUPPORTED_LOCATION_HINTS = {
    "romania",
    "paris",
    "berlin",
    "london",
    "madrid",
    "europe",
}
_SERVICE_LABEL_HINTS = {
    "wedding",
    "weddings",
    "planning",
    "plumbing",
    "roofing",
    "hvac",
    "dental",
    "legal",
}


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class ClaimEvaluationService:
    def __init__(self) -> None:
        self.taxonomy_service = ClaimTaxonomyService()

    def evaluate_shadow(
        self,
        *,
        claim_verifications: list[dict[str, Any]] | None,
        unified_truth_context: dict[str, Any] | None,
        debate_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(claim_verifications, list) or not claim_verifications:
            return None

        truth_context = unified_truth_context if isinstance(unified_truth_context, dict) else {}
        supported_problems = self._build_supported_problems(truth_context)
        support_corpus = self._build_support_corpus(
            truth_context=truth_context,
            supported_problems=supported_problems,
        )
        vision_corpus = self._build_vision_corpus(truth_context)
        site_tokens = self._build_site_tokens(truth_context)
        runtime_supported_problems = [dict(problem) for problem in supported_problems]
        runtime_support_corpus = list(support_corpus)
        runtime_vision_corpus = list(vision_corpus)

        claims: list[dict[str, Any]] = []
        for item in claim_verifications:
            if not isinstance(item, dict):
                continue
            for prepared in self._prepare_claim_variants(item):
                claim = self._evaluate_prepared_claim_deterministically(
                    claim=item,
                    prepared=prepared,
                    support_corpus=runtime_support_corpus,
                    vision_corpus=runtime_vision_corpus,
                    site_tokens=site_tokens,
                    supported_problems=runtime_supported_problems,
                    debate_metadata=debate_metadata,
                )
                if claim is None:
                    continue
                claims.append(claim)
                self._register_supported_shadow_track_a_claim(
                    shadow_claim=claim,
                    prepared=prepared,
                    supported_problems=runtime_supported_problems,
                    support_corpus=runtime_support_corpus,
                )

        return self._build_shadow_result(
            claims=claims,
            requested_tier="smart",
            judge_enabled=False,
            judge_available=False,
        )

    async def evaluate_shadow_async(
        self,
        *,
        claim_verifications: list[dict[str, Any]] | None,
        unified_truth_context: dict[str, Any] | None,
        ai_client: Any | None = None,
        provider: str | None = None,
        tier: str | None = None,
        requested_tier: str | None = None,
        debate_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(claim_verifications, list) or not claim_verifications:
            return None

        truth_context = unified_truth_context if isinstance(unified_truth_context, dict) else {}
        supported_problems = self._build_supported_problems(truth_context)
        support_corpus = self._build_support_corpus(
            truth_context=truth_context,
            supported_problems=supported_problems,
        )
        vision_corpus = self._build_vision_corpus(truth_context)
        site_tokens = self._build_site_tokens(truth_context)
        judge_context = self._build_track_b_judge_context(
            truth_context=truth_context,
            supported_problems=supported_problems,
        )
        runtime_supported_problems = [dict(problem) for problem in supported_problems]
        runtime_support_corpus = list(support_corpus)
        runtime_vision_corpus = list(vision_corpus)
        runtime_judge_context = {
            "target_profile": dict(judge_context.get("target_profile") or {}),
            "supported_problems": [
                dict(problem) for problem in judge_context.get("supported_problems", [])
            ],
            "supported_track_a_claims": [
                dict(item) for item in judge_context.get("supported_track_a_claims", [])
            ],
            "technical_agent_insights": [
                dict(item) for item in judge_context.get("technical_agent_insights", [])
            ],
            "domain_standards": [dict(item) for item in judge_context.get("domain_standards", [])],
        }
        normalized_requested_tier = normalize_audit_tier(requested_tier or tier)
        judge_enabled = normalized_requested_tier in ("deep_judgment", "smart")
        judge_available = judge_enabled and callable(
            getattr(ai_client, "evaluate_track_b_claim", None)
        )
        judge_tier_for_model = (
            "fast" if normalized_requested_tier == "smart" else normalized_requested_tier
        )
        judge_claim_limit = (
            SMART_TIER_JUDGE_CLAIM_LIMIT
            if normalized_requested_tier == "smart"
            else 0  # 0 means no limit (evaluate all)
        )

        claims: list[dict[str, Any]] = []

        if judge_available and judge_claim_limit > 0:
            # Smart tier: two-pass evaluation, deterministic first, then
            # LLM-judge the N most uncertain Track B claims.
            pending: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
            for item in claim_verifications:
                if not isinstance(item, dict):
                    continue
                for prepared in self._prepare_claim_variants(item):
                    evaluated = self._evaluate_prepared_claim_deterministically(
                        claim=item,
                        prepared=prepared,
                        support_corpus=runtime_support_corpus,
                        vision_corpus=runtime_vision_corpus,
                        site_tokens=site_tokens,
                        supported_problems=runtime_supported_problems,
                        debate_metadata=debate_metadata,
                    )
                    if evaluated is None:
                        continue
                    pending.append((item, prepared, evaluated))

            track_b_pending = [
                (i, (item, prep, ev))
                for i, (item, prep, ev) in enumerate(pending)
                if prep["track"] == "track_b"
            ]
            track_b_pending.sort(key=lambda x: float(x[1][2].get("certainty_score") or 1.0))
            promote_indices = {idx for idx, _ in track_b_pending[:judge_claim_limit]}

            for i, (item, prepared, deterministic_result) in enumerate(pending):
                if i in promote_indices:
                    judged = await self._evaluate_track_b_claim_with_ai(
                        claim=item,
                        prepared=prepared,
                        supported_problems=runtime_supported_problems,
                        ai_client=ai_client,
                        judge_context=runtime_judge_context,
                        judge_provider=provider,
                        judge_tier=judge_tier_for_model,
                        debate_metadata=debate_metadata,
                    )
                    result = judged if judged is not None else deterministic_result
                else:
                    result = deterministic_result
                claims.append(result)
                self._register_supported_shadow_track_a_claim(
                    shadow_claim=result,
                    prepared=prepared,
                    supported_problems=runtime_supported_problems,
                    support_corpus=runtime_support_corpus,
                    judge_context=runtime_judge_context,
                )
        else:
            # deep_judgment (no limit) or fast (judge_available=False)
            for item in claim_verifications:
                if not isinstance(item, dict):
                    continue
                for prepared in self._prepare_claim_variants(item):
                    claim = await self._evaluate_claim_async(
                        claim=item,
                        prepared=prepared,
                        support_corpus=runtime_support_corpus,
                        vision_corpus=runtime_vision_corpus,
                        site_tokens=site_tokens,
                        supported_problems=runtime_supported_problems,
                        judge_context=runtime_judge_context,
                        ai_client=ai_client,
                        judge_provider=provider,
                        judge_tier=judge_tier_for_model,
                        judge_available=judge_available,
                        debate_metadata=debate_metadata,
                    )
                    if claim is None:
                        continue
                    claims.append(claim)
                    self._register_supported_shadow_track_a_claim(
                        shadow_claim=claim,
                        prepared=prepared,
                        supported_problems=runtime_supported_problems,
                        support_corpus=runtime_support_corpus,
                        judge_context=runtime_judge_context,
                    )

        return self._build_shadow_result(
            claims=claims,
            requested_tier=normalized_requested_tier,
            judge_enabled=judge_enabled,
            judge_available=judge_available,
            judge_claim_limit=judge_claim_limit,
            judge_tier_for_model=judge_tier_for_model,
        )

    async def _evaluate_claim_async(
        self,
        *,
        claim: dict[str, Any],
        prepared: dict[str, Any],
        support_corpus: list[str],
        vision_corpus: list[str],
        site_tokens: set[str],
        supported_problems: list[dict[str, Any]],
        judge_context: dict[str, Any],
        ai_client: Any | None,
        judge_provider: str | None,
        judge_tier: str,
        judge_available: bool,
        debate_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if prepared["track"] == "track_b" and judge_available:
            judged = await self._evaluate_track_b_claim_with_ai(
                claim=claim,
                prepared=prepared,
                supported_problems=supported_problems,
                ai_client=ai_client,
                judge_context=judge_context,
                judge_provider=judge_provider,
                judge_tier=judge_tier,
                debate_metadata=debate_metadata,
            )
            if judged is not None:
                return judged

        return self._evaluate_prepared_claim_deterministically(
            claim=claim,
            prepared=prepared,
            support_corpus=support_corpus,
            vision_corpus=vision_corpus,
            site_tokens=site_tokens,
            supported_problems=supported_problems,
            debate_metadata=debate_metadata,
        )

    def _prepare_claim_variants(self, claim: dict[str, Any]) -> list[dict[str, Any]]:
        prepared = self._prepare_claim(claim)
        if prepared is None:
            return []
        if prepared["track"] != "mixed":
            return [prepared]

        source_claim_id = (
            prepared["base_payload"].get("claim_id")
            or prepared["base_payload"].get("field_path")
            or "mixed-claim"
        )
        field_path = _normalize_text(prepared["base_payload"].get("field_path"))
        field_group = field_path.split("[", 1)[0].split(".", 1)[0] if field_path else "claims"
        atomized_claims = self.taxonomy_service.atomize_claim(
            {
                "id": source_claim_id,
                "text": prepared["claim_text"],
                "field_group": field_group,
                "field_path": prepared["base_payload"].get("field_path"),
                "field_label": claim.get("field_label"),
            }
        )
        variants: list[dict[str, Any]] = []
        for atomized_claim in atomized_claims:
            if not isinstance(atomized_claim, dict):
                continue
            variant_claim = dict(claim)
            variant_claim["claim_id"] = _normalize_text(atomized_claim.get("id")) or source_claim_id
            variant_claim["claim_text"] = _normalize_text(atomized_claim.get("text"))
            variant_claim["track"] = (
                _normalize_text(atomized_claim.get("track")) or prepared["track"]
            )
            variant_claim["classification_basis"] = list(
                atomized_claim.get("classification_basis")
                if isinstance(atomized_claim.get("classification_basis"), list)
                else prepared["classification_basis"]
            )
            variant_claim["premise_refs"] = list(atomized_claim.get("premise_refs") or [])
            atomization_role = (
                "recommendation" if variant_claim["track"] == "track_b" else "premise"
            )
            if len(atomized_claims) == 1 and variant_claim["track"] == "track_a":
                atomization_role = "fallback_track_a"
            prepared_variant = self._prepare_claim(
                variant_claim,
                source_track="mixed",
                source_claim_id=source_claim_id,
                source_evaluation_mode=MIXED_SPLIT_RESOLUTION,
                atomized=True,
                atomization_role=atomization_role,
            )
            if prepared_variant is not None:
                variants.append(prepared_variant)
        return variants or [prepared]

    def _prepare_claim(
        self,
        claim: dict[str, Any],
        *,
        source_track: str | None = None,
        source_claim_id: str | None = None,
        source_evaluation_mode: str | None = None,
        atomized: bool = False,
        atomization_role: str | None = None,
    ) -> dict[str, Any] | None:
        claim_text = _normalize_text(claim.get("claim_text") or claim.get("text"))
        if not claim_text:
            return None

        track = _normalize_text(claim.get("track")).lower()
        if track not in {"track_a", "track_b", "mixed"}:
            field_path = _normalize_text(claim.get("field_path"))
            field_group = field_path.split("[", 1)[0].split(".", 1)[0] if field_path else ""
            track = str(
                self.taxonomy_service.annotate_claim(
                    {
                        "text": claim_text,
                        "field_group": field_group,
                    }
                ).get("track")
                or "track_a"
            ).lower()

        evaluation_mode = {
            "track_a": STRICT_FACTUAL_GROUNDING,
            "track_b": PRESCRIPTIVE_DERIVATION_REVIEW,
            "mixed": MIXED_SPLIT_RESOLUTION,
        }.get(track, STRICT_FACTUAL_GROUNDING)
        authoritative_disposition = _normalize_text(claim.get("disposition")).lower() or "supported"
        classification_basis = claim.get("classification_basis")
        if not isinstance(classification_basis, list):
            classification_basis = []

        claim_id = _normalize_text(claim.get("claim_id")) or None
        field_path = _normalize_text(claim.get("field_path")) or None
        premise_refs = self._normalize_string_list(claim.get("premise_refs"))

        return {
            "claim_text": claim_text,
            "track": track,
            "classification_basis": classification_basis,
            "base_payload": {
                "claim_id": claim_id,
                "claim_text": claim_text,
                "track": track,
                "evaluation_mode": evaluation_mode,
                "authoritative_disposition": authoritative_disposition,
                "field_path": field_path,
                "premise_refs": premise_refs,
                "source_track": source_track,
                "source_claim_id": source_claim_id,
                "source_evaluation_mode": source_evaluation_mode,
                "atomized": atomized,
                "atomization_role": atomization_role,
            },
        }

    def _evaluate_prepared_claim_deterministically(
        self,
        *,
        claim: dict[str, Any],
        prepared: dict[str, Any],
        support_corpus: list[str],
        vision_corpus: list[str],
        site_tokens: set[str],
        supported_problems: list[dict[str, Any]],
        debate_metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        claim_text = prepared["claim_text"]
        track = prepared["track"]
        base_payload = dict(prepared["base_payload"])

        if track == "track_a":
            if base_payload.get("source_track") == "mixed":
                return self._evaluate_atomized_track_a_claim(
                    claim=claim,
                    prepared=prepared,
                    support_corpus=support_corpus,
                    site_tokens=site_tokens,
                    supported_problems=supported_problems,
                )
            return {
                **base_payload,
                "shadow_disposition": base_payload["authoritative_disposition"],
                "certainty_score": _clamp(_safe_float(claim.get("certainty_score"))),
                "confidence_band": "high",
                "reason_codes": [],
                "problem_anchor_score": None,
                "action_fit_score": None,
                "site_specificity_score": None,
                "novel_fact_risk_score": None,
                "problem_refs": [],
                "evidence_refs": self._normalize_evidence_refs(claim.get("evidence_refs")),
                "explanation": "Track A claim inherits the authoritative factual grounding verdict.",
                "judge_resolution": "Factual grounding inherits the authoritative Track A verdict.",
                "suggested_rewrite": "",
                "judge_mode": None,
                "judge_provider": None,
                "judge_model": None,
            }

        if track == "mixed":
            return {
                **base_payload,
                "shadow_disposition": "omitted",
                "certainty_score": 0.0,
                "confidence_band": "contested",
                "reason_codes": ["needs_narrower_wording"],
                "problem_anchor_score": 0.0,
                "action_fit_score": 0.0,
                "site_specificity_score": 0.0,
                "novel_fact_risk_score": 1.0,
                "problem_refs": [],
                "evidence_refs": [],
                "explanation": (
                    "Mixed claim should be atomized before shadow evaluation; any unexpanded fallback stays omitted."
                ),
                "judge_resolution": "Claim stayed mixed or contradictory and was blocked pending a manual rewrite.",
                "suggested_rewrite": self._rewrite_claim(claim_text, ["needs_narrower_wording"]),
                "judge_mode": None,
                "judge_provider": None,
                "judge_model": None,
            }

        classification_basis = prepared["classification_basis"]
        problem_anchor_score = self._problem_anchor_score(claim_text, support_corpus)
        action_fit_score = self._action_fit_score(claim_text, support_corpus, classification_basis)
        site_specificity_score = self._site_specificity_score(
            claim_text, site_tokens, support_corpus
        )
        novel_fact_risk_score = self._novel_fact_risk_score(
            claim_text,
            classification_basis=classification_basis,
            support_corpus=support_corpus,
            site_tokens=site_tokens,
        )
        vision_only_overreach = self._is_vision_only_overreach(
            claim_text=claim_text,
            classification_basis=classification_basis,
            support_corpus=support_corpus,
            vision_corpus=vision_corpus,
            site_tokens=site_tokens,
        )

        problem_refs, matched_evidence_refs = self._match_problem_refs(
            claim_text=claim_text,
            supported_problems=supported_problems,
        )
        reason_codes: list[str] = []
        if problem_anchor_score < 0.45:
            reason_codes.append("no_supported_problem")
        if site_specificity_score < 0.35 or any(
            phrase in claim_text.lower() for phrase in _GENERIC_ADVICE_PHRASES
        ):
            reason_codes.append("generic_advice")
        if action_fit_score < 0.5:
            reason_codes.append("weak_action_problem_fit")
        if self._has_unsupported_premise_ref(
            premise_refs=base_payload.get("premise_refs"),
            supported_problems=supported_problems,
        ):
            reason_codes.append("unsupported_premise_ref")
        if vision_only_overreach:
            reason_codes.append("vision_only_overreach")
            reason_codes.append("invented_site_fact")
            if self._contains_unsupported_location(claim_text, site_tokens, support_corpus):
                reason_codes.append("unsupported_location")
            elif self._contains_unsupported_service_label(claim_text, site_tokens, support_corpus):
                reason_codes.append("unsupported_service_label")
            reason_codes.append("needs_narrower_wording")
        if novel_fact_risk_score > 0.55:
            reason_codes.append("invented_site_fact")
            if self._contains_unsupported_location(claim_text, site_tokens, support_corpus):
                reason_codes.append("unsupported_location")
            elif self._contains_unsupported_service_label(claim_text, site_tokens, support_corpus):
                reason_codes.append("unsupported_service_label")
            reason_codes.append("needs_narrower_wording")
        reason_codes = self._normalize_string_list(reason_codes)
        shadow_disposition = self._resolve_track_b_verdict(
            desired_verdict=None,
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
            reason_codes=reason_codes,
        )
        certainty_score = self._track_b_certainty_score(
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
        )
        confidence_band = self._resolve_track_b_confidence_band(
            desired_confidence_band=None,
            shadow_disposition=shadow_disposition,
            certainty_score=certainty_score,
        )
        if self._should_mark_needs_manual_review(
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            certainty_score=certainty_score,
            debate_metadata=debate_metadata,
        ):
            shadow_disposition = TRACK_B_NEEDS_MANUAL_REVIEW
            confidence_band = "contested"
        evidence_refs = self._normalize_string_list(
            [
                *self._normalize_evidence_refs(claim.get("evidence_refs")),
                *matched_evidence_refs,
            ]
        )
        suggested_rewrite = self._rewrite_claim(claim_text, reason_codes)
        explanation = self._build_track_b_explanation(
            shadow_disposition=shadow_disposition,
            reason_codes=reason_codes,
        )
        judge_resolution = self._build_track_b_judge_resolution(
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            reason_codes=reason_codes,
        )

        return self._build_track_b_payload(
            base_payload=base_payload,
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
            reason_codes=reason_codes,
            problem_refs=problem_refs,
            evidence_refs=evidence_refs,
            explanation=explanation,
            judge_resolution=judge_resolution,
            suggested_rewrite=suggested_rewrite,
            judge_mode=TRACK_B_DETERMINISTIC_SHADOW_MODE,
            judge_provider=None,
            judge_model=None,
        )

    async def _evaluate_track_b_claim_with_ai(
        self,
        *,
        claim: dict[str, Any],
        prepared: dict[str, Any],
        supported_problems: list[dict[str, Any]],
        ai_client: Any,
        judge_context: dict[str, Any],
        judge_provider: str | None,
        judge_tier: str,
        debate_metadata: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        claim_text = prepared["claim_text"]
        base_payload = dict(prepared["base_payload"])
        claim_id = base_payload.get("claim_id") or base_payload.get("field_path") or "track-b-claim"
        attempted_provider = str(judge_provider or "google").strip() or "google"
        attempted_model = None

        try:
            result = await ai_client.evaluate_track_b_claim(
                provider=attempted_provider,
                tier=judge_tier,
                claim={
                    "claim_id": claim_id,
                    "claim_text": claim_text,
                    "field_path": base_payload.get("field_path"),
                    "classification_basis": prepared["classification_basis"],
                    "premise_refs": base_payload.get("premise_refs"),
                    "disposition": base_payload.get("authoritative_disposition"),
                },
                judge_context=judge_context,
            )
        except Exception as exc:
            logger.warning("Track B judge unavailable for claim %s: %s", claim_id, exc)
            return self._build_track_b_unavailable_payload(
                base_payload=base_payload,
                claim_text=claim_text,
                judge_provider=attempted_provider,
                judge_model=attempted_model,
            )

        result_payload = result if isinstance(result, dict) else {}
        judgment = (
            result_payload.get("judgment")
            if isinstance(result_payload.get("judgment"), dict)
            else result_payload
        )
        judge_provider_value = _normalize_text(result_payload.get("provider")) or attempted_provider
        judge_model_value = _normalize_text(result_payload.get("model")) or None
        judge_usage_value = (
            dict(result_payload.get("usage"))
            if isinstance(result_payload.get("usage"), dict)
            else None
        )
        judge_latency_ms = _safe_float(result_payload.get("latency_ms"))
        attempted_model = judge_model_value

        if not isinstance(judgment, dict):
            return self._build_track_b_unavailable_payload(
                base_payload=base_payload,
                claim_text=claim_text,
                judge_provider=judge_provider_value,
                judge_model=attempted_model,
            )

        problem_anchor_score = _clamp(_safe_float(judgment.get("problem_anchor_score")))
        action_fit_score = _clamp(_safe_float(judgment.get("action_fit_score")))
        site_specificity_score = _clamp(_safe_float(judgment.get("site_specificity_score")))
        novel_fact_risk_score = _clamp(_safe_float(judgment.get("novel_fact_risk_score")))
        reason_codes = self._normalize_string_list(judgment.get("reason_codes"))
        problem_refs = self._normalize_string_list(judgment.get("problem_refs"))
        matched_problem_refs, matched_evidence_refs = self._match_problem_refs(
            claim_text=claim_text,
            supported_problems=supported_problems,
        )
        if not problem_refs:
            problem_refs = matched_problem_refs
        if self._has_unsupported_premise_ref(
            premise_refs=base_payload.get("premise_refs"),
            supported_problems=supported_problems,
        ):
            reason_codes.append("unsupported_premise_ref")
        evidence_refs = self._normalize_string_list(
            [
                *self._normalize_string_list(judgment.get("evidence_refs")),
                *self._normalize_evidence_refs(claim.get("evidence_refs")),
                *matched_evidence_refs,
            ]
        )
        suggested_rewrite = _normalize_text(judgment.get("suggested_rewrite"))
        if not suggested_rewrite:
            suggested_rewrite = self._rewrite_claim(claim_text, reason_codes)
        shadow_disposition = self._resolve_track_b_verdict(
            desired_verdict=_normalize_text(judgment.get("verdict")).lower() or None,
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
            reason_codes=reason_codes,
        )
        certainty_score = self._track_b_certainty_score(
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
        )
        confidence_band = self._resolve_track_b_confidence_band(
            desired_confidence_band=_normalize_text(judgment.get("confidence_band")).lower()
            or None,
            shadow_disposition=shadow_disposition,
            certainty_score=certainty_score,
        )
        if self._should_mark_needs_manual_review(
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            certainty_score=certainty_score,
            debate_metadata=debate_metadata,
        ):
            shadow_disposition = TRACK_B_NEEDS_MANUAL_REVIEW
            confidence_band = "contested"
        explanation = _normalize_text(
            judgment.get("explanation")
        ) or self._build_track_b_explanation(
            shadow_disposition=shadow_disposition,
            reason_codes=reason_codes,
        )
        judge_resolution = _normalize_text(
            judgment.get("judge_resolution")
        ) or self._build_track_b_judge_resolution(
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            reason_codes=reason_codes,
        )
        return self._build_track_b_payload(
            base_payload=base_payload,
            shadow_disposition=shadow_disposition,
            confidence_band=confidence_band,
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
            reason_codes=reason_codes,
            problem_refs=problem_refs,
            evidence_refs=evidence_refs,
            explanation=explanation,
            judge_resolution=judge_resolution,
            suggested_rewrite=suggested_rewrite,
            judge_mode=TRACK_B_LLM_SHADOW_MODE,
            judge_provider=judge_provider_value,
            judge_model=judge_model_value,
            judge_usage=judge_usage_value,
            judge_latency_ms=judge_latency_ms,
        )

    def _build_shadow_result(
        self,
        *,
        claims: list[dict[str, Any]],
        requested_tier: str,
        judge_enabled: bool,
        judge_available: bool,
        judge_claim_limit: int = 0,
        judge_tier_for_model: str = "",
    ) -> dict[str, Any] | None:
        if not claims:
            return None

        judge_mode = TRACK_B_NOT_APPLICABLE_MODE
        llm_claims = sum(
            1 for claim in claims if claim.get("judge_mode") == TRACK_B_LLM_SHADOW_MODE
        )
        deterministic_claims = sum(
            1 for claim in claims if claim.get("judge_mode") == TRACK_B_DETERMINISTIC_SHADOW_MODE
        )
        unavailable_claims = sum(
            1 for claim in claims if claim.get("judge_mode") == TRACK_B_JUDGE_UNAVAILABLE_MODE
        )
        track_b_claims = sum(1 for claim in claims if claim.get("track") == "track_b")
        if track_b_claims:
            if llm_claims and not deterministic_claims and not unavailable_claims:
                judge_mode = TRACK_B_LLM_SHADOW_MODE
            elif llm_claims:
                judge_mode = TRACK_B_HYBRID_SHADOW_MODE
            else:
                judge_mode = TRACK_B_DETERMINISTIC_SHADOW_MODE

        providers = sorted(
            {
                str(claim.get("judge_provider")).strip()
                for claim in claims
                if isinstance(claim.get("judge_provider"), str)
                and str(claim.get("judge_provider")).strip()
            }
        )
        models = sorted(
            {
                str(claim.get("judge_model")).strip()
                for claim in claims
                if isinstance(claim.get("judge_model"), str)
                and str(claim.get("judge_model")).strip()
            }
        )
        atomized_source_ids = {
            _normalize_text(claim.get("source_claim_id"))
            for claim in claims
            if _normalize_text(claim.get("source_track")) == "mixed"
            and _normalize_text(claim.get("source_claim_id"))
        }
        fallback_track_a_sources = {
            _normalize_text(claim.get("source_claim_id"))
            for claim in claims
            if _normalize_text(claim.get("atomization_role")) == "fallback_track_a"
            and _normalize_text(claim.get("source_claim_id"))
        }

        return {
            "schema_version": DUAL_TRACK_SHADOW_SCHEMA_VERSION,
            "status": "shadow",
            "authoritative_mode": "single_track",
            "summary": {
                "track_a_claims": sum(1 for claim in claims if claim.get("track") == "track_a"),
                "track_b_claims": track_b_claims,
                "mixed_claims": sum(1 for claim in claims if claim.get("track") == "mixed"),
                "supported_claims": sum(
                    1 for claim in claims if claim.get("shadow_disposition") == "supported"
                ),
                "flagged_claims": sum(
                    1 for claim in claims if claim.get("shadow_disposition") == "flagged"
                ),
                "needs_manual_review_claims": sum(
                    1
                    for claim in claims
                    if claim.get("shadow_disposition") == TRACK_B_NEEDS_MANUAL_REVIEW
                ),
                "omitted_claims": sum(
                    1 for claim in claims if claim.get("shadow_disposition") == "omitted"
                ),
            },
            "atomization": {
                "mixed_source_claims": len(atomized_source_ids),
                "split_claims_created": sum(
                    1
                    for claim in claims
                    if _normalize_text(claim.get("source_track")) == "mixed"
                    and _normalize_text(claim.get("atomization_role")) != "fallback_track_a"
                ),
                "fallback_track_a_claims": sum(
                    1
                    for claim in claims
                    if _normalize_text(claim.get("atomization_role")) == "fallback_track_a"
                ),
                "unsplittable_mixed_claims": len(fallback_track_a_sources),
            },
            "track_b_judge": {
                "requested_tier": requested_tier,
                "judge_model_tier": judge_tier_for_model or requested_tier,
                "judge_claim_limit": judge_claim_limit,
                "enabled": judge_enabled,
                "available": judge_available,
                "mode": judge_mode,
                "evaluated_claims": track_b_claims,
                "llm_evaluated_claims": llm_claims,
                "deterministic_fallback_claims": deterministic_claims,
                "judge_unavailable_claims": unavailable_claims,
                "needs_manual_review_claims": sum(
                    1
                    for claim in claims
                    if claim.get("track") == "track_b"
                    and claim.get("shadow_disposition") == TRACK_B_NEEDS_MANUAL_REVIEW
                ),
                "providers": providers,
                "models": models,
            },
            "claims": claims,
        }

    def _build_track_b_payload(
        self,
        *,
        base_payload: dict[str, Any],
        shadow_disposition: str,
        confidence_band: str,
        problem_anchor_score: float,
        action_fit_score: float,
        site_specificity_score: float,
        novel_fact_risk_score: float,
        reason_codes: list[str],
        problem_refs: list[str],
        evidence_refs: list[str],
        explanation: str,
        judge_resolution: str,
        suggested_rewrite: str,
        judge_mode: str,
        judge_provider: str | None,
        judge_model: str | None,
        judge_usage: dict[str, Any] | None = None,
        judge_latency_ms: float | None = None,
    ) -> dict[str, Any]:
        certainty_score = self._track_b_certainty_score(
            problem_anchor_score=problem_anchor_score,
            action_fit_score=action_fit_score,
            site_specificity_score=site_specificity_score,
            novel_fact_risk_score=novel_fact_risk_score,
        )
        return {
            **base_payload,
            "shadow_disposition": shadow_disposition,
            "certainty_score": round(certainty_score, 4),
            "confidence_band": confidence_band,
            "reason_codes": self._normalize_string_list(reason_codes),
            "problem_anchor_score": round(problem_anchor_score, 4),
            "action_fit_score": round(action_fit_score, 4),
            "site_specificity_score": round(site_specificity_score, 4),
            "novel_fact_risk_score": round(novel_fact_risk_score, 4),
            "problem_refs": self._normalize_string_list(problem_refs),
            "evidence_refs": self._normalize_string_list(evidence_refs),
            "explanation": explanation,
            "judge_resolution": judge_resolution,
            "suggested_rewrite": suggested_rewrite,
            "judge_mode": judge_mode,
            "judge_provider": judge_provider,
            "judge_model": judge_model,
            "judge_usage": dict(judge_usage or {}),
            "judge_latency_ms": round(float(judge_latency_ms or 0.0), 3),
        }

    def _build_track_b_unavailable_payload(
        self,
        *,
        base_payload: dict[str, Any],
        claim_text: str,
        judge_provider: str | None,
        judge_model: str | None,
    ) -> dict[str, Any]:
        reason_codes = ["track_b_judge_unavailable"]
        return self._build_track_b_payload(
            base_payload=base_payload,
            shadow_disposition="omitted",
            confidence_band="contested",
            problem_anchor_score=0.0,
            action_fit_score=0.0,
            site_specificity_score=0.0,
            novel_fact_risk_score=1.0,
            reason_codes=reason_codes,
            problem_refs=[],
            evidence_refs=[],
            explanation="Track B judge was unavailable; shadow evaluation safe-failed for this recommendation.",
            judge_resolution="Track B judge was unavailable; this recommendation requires manual verification before use.",
            suggested_rewrite=self._rewrite_claim(claim_text, reason_codes),
            judge_mode=TRACK_B_JUDGE_UNAVAILABLE_MODE,
            judge_provider=judge_provider,
            judge_model=judge_model,
        )

    def _evaluate_atomized_track_a_claim(
        self,
        *,
        claim: dict[str, Any],
        prepared: dict[str, Any],
        support_corpus: list[str],
        site_tokens: set[str],
        supported_problems: list[dict[str, Any]],
    ) -> dict[str, Any]:
        claim_text = prepared["claim_text"]
        base_payload = dict(prepared["base_payload"])
        local_support_corpus = list(support_corpus)
        for ref in claim.get("evidence_refs", []):
            if not isinstance(ref, dict):
                continue
            excerpt = _normalize_text(ref.get("excerpt"))
            if excerpt:
                local_support_corpus.append(excerpt)

        support_overlap = self._problem_anchor_score(claim_text, local_support_corpus)
        site_specificity = self._site_specificity_score(
            claim_text, site_tokens, local_support_corpus
        )
        certainty_score = _clamp((0.7 * support_overlap) + (0.3 * site_specificity))
        problem_refs, matched_evidence_refs = self._match_problem_refs(
            claim_text=claim_text,
            supported_problems=supported_problems,
        )
        evidence_refs = self._normalize_string_list(
            [
                *self._normalize_evidence_refs(claim.get("evidence_refs")),
                *matched_evidence_refs,
            ]
        )
        if support_overlap >= 0.75 or certainty_score >= 0.72:
            shadow_disposition = "supported"
            explanation = "Atomized mixed-premise claim is supported strongly enough to seed shadow Track B evaluation."
        elif support_overlap >= 0.55 or certainty_score >= 0.55:
            shadow_disposition = "flagged"
            explanation = "Atomized mixed-premise claim is plausible but not strong enough to promote into supported shadow truth."
        else:
            shadow_disposition = "omitted"
            explanation = "Atomized mixed-premise claim is not supported strongly enough to justify the derived recommendation."

        return {
            **base_payload,
            "shadow_disposition": shadow_disposition,
            "certainty_score": round(certainty_score, 4),
            "confidence_band": "high"
            if shadow_disposition == "supported"
            else ("medium" if shadow_disposition == "flagged" else "contested"),
            "reason_codes": [],
            "problem_anchor_score": None,
            "action_fit_score": None,
            "site_specificity_score": None,
            "novel_fact_risk_score": None,
            "problem_refs": problem_refs,
            "evidence_refs": evidence_refs,
            "explanation": explanation,
            "judge_resolution": explanation,
            "suggested_rewrite": "",
            "judge_mode": None,
            "judge_provider": None,
            "judge_model": None,
        }

    def _register_supported_shadow_track_a_claim(
        self,
        *,
        shadow_claim: dict[str, Any],
        prepared: dict[str, Any],
        supported_problems: list[dict[str, Any]],
        support_corpus: list[str],
        judge_context: dict[str, Any] | None = None,
    ) -> None:
        if shadow_claim.get("track") != "track_a":
            return
        if shadow_claim.get("shadow_disposition") != "supported":
            return

        claim_id = _normalize_text(shadow_claim.get("claim_id"))
        claim_text = prepared["claim_text"]
        if not claim_id or not claim_text:
            return
        if any(
            _normalize_text(problem.get("problem_id")) == claim_id for problem in supported_problems
        ):
            return

        evidence_refs = self._normalize_string_list(shadow_claim.get("evidence_refs"))
        problem_payload = {
            "problem_id": claim_id,
            "text": claim_text,
            "source_type": "shadow_track_a_claim",
            "evidence_refs": evidence_refs,
        }
        supported_problems.append(problem_payload)
        if claim_text not in support_corpus:
            support_corpus.append(claim_text)

        if not isinstance(judge_context, dict):
            return
        judge_context.setdefault("supported_problems", []).append(dict(problem_payload))
        judge_context.setdefault("supported_track_a_claims", []).append(
            {
                "claim_id": claim_id,
                "text": claim_text,
                "evidence_refs": evidence_refs,
            }
        )

    def _has_unsupported_premise_ref(
        self,
        *,
        premise_refs: Any,
        supported_problems: list[dict[str, Any]],
    ) -> bool:
        normalized_premise_refs = self._normalize_string_list(premise_refs)
        if not normalized_premise_refs:
            return False
        supported_problem_ids = {
            _normalize_text(problem.get("problem_id"))
            for problem in supported_problems
            if _normalize_text(problem.get("problem_id"))
        }
        return any(ref not in supported_problem_ids for ref in normalized_premise_refs)

    def _build_supported_problems(self, truth_context: dict[str, Any]) -> list[dict[str, Any]]:
        problems: list[dict[str, Any]] = []
        for index, item in enumerate(truth_context.get("supported_track_a_claims", []), start=1):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("claim_text") or item.get("text"))
            if not text:
                continue
            problems.append(
                {
                    "problem_id": _normalize_text(item.get("claim_id"))
                    or _normalize_text(item.get("field_path"))
                    or f"track-a-{index}",
                    "text": text,
                    "source_type": "supported_track_a_claim",
                    "evidence_refs": self._normalize_evidence_refs(item.get("evidence_refs")),
                }
            )
        for index, item in enumerate(truth_context.get("technical_agent_insights", []), start=1):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("insight_text") or item.get("text"))
            if not text:
                continue
            problems.append(
                {
                    "problem_id": _normalize_text(item.get("source_id")) or f"insight-{index}",
                    "text": text,
                    "source_type": _normalize_text(item.get("source_type")) or "technical_insight",
                    "evidence_refs": self._normalize_evidence_refs(item.get("evidence_refs")),
                }
            )
        return problems

    def _build_track_b_judge_context(
        self,
        *,
        truth_context: dict[str, Any],
        supported_problems: list[dict[str, Any]],
    ) -> dict[str, Any]:
        target_profile = (
            truth_context.get("target_profile")
            if isinstance(truth_context.get("target_profile"), dict)
            else {}
        )
        supported_track_a_claims: list[dict[str, Any]] = []
        for item in truth_context.get("supported_track_a_claims", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("claim_text") or item.get("text"))
            if not text:
                continue
            supported_track_a_claims.append(
                {
                    "claim_id": _normalize_text(item.get("claim_id"))
                    or _normalize_text(item.get("field_path")),
                    "text": text,
                    "evidence_refs": self._normalize_evidence_refs(item.get("evidence_refs")),
                }
            )
        technical_insights: list[dict[str, Any]] = []
        for item in truth_context.get("technical_agent_insights", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("insight_text") or item.get("text"))
            if not text:
                continue
            technical_insights.append(
                {
                    "source_id": _normalize_text(item.get("source_id")),
                    "text": text,
                    "source_type": _normalize_text(item.get("source_type")) or "technical",
                    "evidence_refs": self._normalize_evidence_refs(item.get("evidence_refs")),
                }
            )
        domain_standards: list[dict[str, Any]] = []
        for item in truth_context.get("domain_standards", []):
            if not isinstance(item, dict):
                continue
            excerpt = _normalize_text(item.get("excerpt"))
            if not excerpt:
                continue
            domain_standards.append(
                {
                    "source_id": _normalize_text(item.get("source_id")),
                    "category": _normalize_text(item.get("category")),
                    "excerpt": excerpt,
                }
            )
        return {
            "target_profile": target_profile,
            "supported_problems": supported_problems[:12],
            "supported_track_a_claims": supported_track_a_claims[:12],
            "technical_agent_insights": technical_insights[:12],
            "domain_standards": domain_standards[:5],
        }

    def _build_support_corpus(
        self,
        *,
        truth_context: dict[str, Any],
        supported_problems: list[dict[str, Any]],
    ) -> list[str]:
        corpus: list[str] = [
            problem["text"] for problem in supported_problems if problem.get("text")
        ]
        for item in truth_context.get("domain_standards", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("excerpt"))
            if text:
                corpus.append(text)
        return self._normalize_string_list(corpus)

    def _build_vision_corpus(self, truth_context: dict[str, Any]) -> list[str]:
        corpus: list[str] = []
        for item in truth_context.get("vision_agent_insights", []):
            if not isinstance(item, dict):
                continue
            text = _normalize_text(item.get("insight_text") or item.get("text"))
            if text:
                corpus.append(text)
        return self._normalize_string_list(corpus)

    def _build_site_tokens(self, truth_context: dict[str, Any]) -> set[str]:
        target_profile = (
            truth_context.get("target_profile")
            if isinstance(truth_context.get("target_profile"), dict)
            else {}
        )
        raw_values: list[str] = []
        raw_values.extend(
            [
                _normalize_text(target_profile.get("target_name")),
                _normalize_text(target_profile.get("target_url")),
            ]
        )
        for key in ("target_metadata", "brand_truth_payload"):
            payload = target_profile.get(key) if isinstance(target_profile.get(key), dict) else {}
            for value in payload.values():
                if isinstance(value, str):
                    raw_values.append(_normalize_text(value))
        parsed_url = urlparse(_normalize_text(target_profile.get("target_url")))
        if parsed_url.netloc:
            raw_values.append(parsed_url.netloc.replace("www.", " "))

        tokens = set()
        for value in raw_values:
            tokens.update(self._tokenize(value))
        tokens.update(_SITE_SPECIFIC_TOKENS)
        return tokens

    def _problem_anchor_score(self, claim_text: str, support_corpus: list[str]) -> float:
        if not support_corpus:
            return 0.0
        claim_tokens = self._tokenize(claim_text)
        if not claim_tokens:
            return 0.0
        overlaps = [
            self._overlap_ratio(claim_tokens, self._tokenize(item)) for item in support_corpus
        ]
        best_overlap = max(overlaps) if overlaps else 0.0
        if "schema" in claim_tokens and any(
            "schema" in self._tokenize(item) for item in support_corpus
        ):
            best_overlap += 0.15
        if any(token in claim_tokens for token in _SITE_SPECIFIC_TOKENS):
            best_overlap += 0.1
        return _clamp(best_overlap)

    def _action_fit_score(
        self,
        claim_text: str,
        support_corpus: list[str],
        classification_basis: list[Any],
    ) -> float:
        score = 0.35
        claim_tokens = self._tokenize(claim_text)
        if "contains_imperative_action" in {str(item) for item in classification_basis}:
            score += 0.25
        if any(token in claim_tokens for token in _SITE_SPECIFIC_TOKENS):
            score += 0.15
        if any(
            token in claim_tokens
            and any(token in self._tokenize(problem) for problem in support_corpus)
            for token in _SITE_SPECIFIC_TOKENS
        ):
            score += 0.2
        return _clamp(score)

    def _site_specificity_score(
        self,
        claim_text: str,
        site_tokens: set[str],
        support_corpus: list[str],
    ) -> float:
        claim_tokens = self._tokenize(claim_text)
        if not claim_tokens:
            return 0.0
        overlap = self._overlap_ratio(claim_tokens, list(site_tokens))
        if any(token in claim_tokens for token in _SITE_SPECIFIC_TOKENS):
            overlap += 0.25
        if any(
            self._overlap_ratio(claim_tokens, self._tokenize(item)) > 0.2 for item in support_corpus
        ):
            overlap += 0.2
        return _clamp(overlap)

    def _novel_fact_risk_score(
        self,
        claim_text: str,
        *,
        classification_basis: list[Any],
        support_corpus: list[str],
        site_tokens: set[str],
    ) -> float:
        basis = {str(item) for item in classification_basis}
        score = 0.15
        if "contains_unsupported_concrete_token" in basis:
            score += 0.35
        if "conditional_on_authoritative_metadata" in basis:
            score -= 0.15
        if self._contains_unsupported_location(claim_text, site_tokens, support_corpus):
            score += 0.2
        if self._contains_unsupported_service_label(claim_text, site_tokens, support_corpus):
            score += 0.2
        return _clamp(score)

    def _contains_unsupported_location(
        self,
        claim_text: str,
        site_tokens: set[str],
        support_corpus: list[str],
    ) -> bool:
        claim_tokens = set(self._tokenize(claim_text))
        support_tokens = (
            set().union(*(set(self._tokenize(item)) for item in support_corpus))
            if support_corpus
            else set()
        )
        for token in _UNSUPPORTED_LOCATION_HINTS:
            if token in claim_tokens and token not in site_tokens and token not in support_tokens:
                return True
        return False

    def _contains_unsupported_service_label(
        self,
        claim_text: str,
        site_tokens: set[str],
        support_corpus: list[str],
    ) -> bool:
        claim_tokens = set(self._tokenize(claim_text))
        support_tokens = (
            set().union(*(set(self._tokenize(item)) for item in support_corpus))
            if support_corpus
            else set()
        )
        for token in _SERVICE_LABEL_HINTS:
            if token in claim_tokens and token not in site_tokens and token not in support_tokens:
                return True
        return False

    def _is_vision_only_overreach(
        self,
        *,
        claim_text: str,
        classification_basis: list[Any],
        support_corpus: list[str],
        vision_corpus: list[str],
        site_tokens: set[str],
    ) -> bool:
        if not vision_corpus:
            return False

        claim_tokens = self._tokenize(claim_text)
        if not claim_tokens:
            return False

        basis = {str(item) for item in classification_basis}
        has_unsupported_concrete_fact = (
            "contains_unsupported_concrete_token" in basis
            or self._contains_unsupported_location(claim_text, site_tokens, support_corpus)
            or self._contains_unsupported_service_label(claim_text, site_tokens, support_corpus)
        )
        if not has_unsupported_concrete_fact:
            return False

        max_support_overlap = max(
            (self._overlap_ratio(claim_tokens, self._tokenize(item)) for item in support_corpus),
            default=0.0,
        )
        if max_support_overlap >= 0.35:
            return False

        max_vision_overlap = max(
            (self._overlap_ratio(claim_tokens, self._tokenize(item)) for item in vision_corpus),
            default=0.0,
        )
        return max_vision_overlap >= 0.2

    def _resolve_track_b_verdict(
        self,
        *,
        desired_verdict: str | None,
        problem_anchor_score: float,
        action_fit_score: float,
        site_specificity_score: float,
        novel_fact_risk_score: float,
        reason_codes: list[str],
    ) -> str:
        if any(code in _TRACK_B_HARD_FAIL_REASON_CODES for code in reason_codes):
            return "omitted"
        has_soft_fail = any(code in _TRACK_B_SOFT_FAIL_REASON_CODES for code in reason_codes)
        if desired_verdict == "omitted":
            return "omitted"
        if desired_verdict == TRACK_B_NEEDS_MANUAL_REVIEW:
            return TRACK_B_NEEDS_MANUAL_REVIEW
        if desired_verdict == "flagged":
            return "flagged"
        if (
            problem_anchor_score >= 0.65
            and action_fit_score >= 0.60
            and site_specificity_score >= 0.45
            and novel_fact_risk_score <= 0.35
            and not has_soft_fail
        ):
            return "supported"
        if (
            problem_anchor_score >= 0.45
            and action_fit_score >= 0.45
            and site_specificity_score >= 0.30
            and novel_fact_risk_score <= 0.60
        ):
            return "flagged"
        return "omitted"

    def _resolve_track_b_confidence_band(
        self,
        *,
        desired_confidence_band: str | None,
        shadow_disposition: str,
        certainty_score: float,
    ) -> str:
        if desired_confidence_band in {"high", "medium", "contested"}:
            return desired_confidence_band
        if shadow_disposition == TRACK_B_NEEDS_MANUAL_REVIEW:
            return "contested"
        if shadow_disposition == "supported" and certainty_score >= 0.75:
            return "high"
        if certainty_score >= 0.6 and shadow_disposition in {"supported", "flagged"}:
            return "medium"
        return "contested"

    def _should_mark_needs_manual_review(
        self,
        *,
        shadow_disposition: str,
        confidence_band: str,
        certainty_score: float,
        debate_metadata: dict[str, Any] | None,
    ) -> bool:
        if shadow_disposition not in {"supported", "flagged", TRACK_B_NEEDS_MANUAL_REVIEW}:
            return False
        if shadow_disposition == TRACK_B_NEEDS_MANUAL_REVIEW:
            return True
        if confidence_band == "contested":
            return True
        if certainty_score < 0.6:
            return True
        if not isinstance(debate_metadata, dict):
            return False

        debate_confidence_score = _safe_float(debate_metadata.get("debate_confidence_score"))
        judge_summary = (
            debate_metadata.get("judge_summary")
            if isinstance(debate_metadata.get("judge_summary"), dict)
            else {}
        )
        unresolved_disputes = int(judge_summary.get("unresolved_disputes") or 0)
        return debate_confidence_score < 0.6 and unresolved_disputes > 0

    def _track_b_certainty_score(
        self,
        *,
        problem_anchor_score: float,
        action_fit_score: float,
        site_specificity_score: float,
        novel_fact_risk_score: float,
    ) -> float:
        return _clamp(
            (0.4 * problem_anchor_score)
            + (0.3 * action_fit_score)
            + (0.2 * site_specificity_score)
            + (0.1 * (1 - novel_fact_risk_score))
        )

    def _match_problem_refs(
        self,
        *,
        claim_text: str,
        supported_problems: list[dict[str, Any]],
    ) -> tuple[list[str], list[str]]:
        claim_tokens = self._tokenize(claim_text)
        if not claim_tokens:
            return [], []

        matches: list[tuple[float, dict[str, Any]]] = []
        for problem in supported_problems:
            problem_text = _normalize_text(problem.get("text"))
            if not problem_text:
                continue
            score = self._overlap_ratio(claim_tokens, self._tokenize(problem_text))
            if score <= 0:
                continue
            if any(
                token in claim_tokens and token in self._tokenize(problem_text)
                for token in _SITE_SPECIFIC_TOKENS
            ):
                score += 0.1
            matches.append((score, problem))

        matches.sort(key=lambda item: item[0], reverse=True)
        selected = [problem for score, problem in matches[:3] if score >= 0.2]
        problem_refs = self._normalize_string_list(
            [problem.get("problem_id") for problem in selected]
        )
        evidence_refs: list[str] = []
        for problem in selected:
            evidence_refs.extend(self._normalize_evidence_refs(problem.get("evidence_refs")))
        return problem_refs, self._normalize_string_list(evidence_refs)

    def _build_track_b_explanation(
        self,
        *,
        shadow_disposition: str,
        reason_codes: list[str],
    ) -> str:
        ordered_reason_codes = self._sort_reason_codes(reason_codes)
        if "track_b_judge_unavailable" in ordered_reason_codes:
            return "Track B judge was unavailable, so shadow evaluation safe-failed."
        if "vision_only_overreach" in ordered_reason_codes:
            return (
                "Recommendation depends on imagery-only inference for a concrete business fact that is "
                "not supported by authoritative metadata or grounded site evidence."
            )
        if "invented_site_fact" in ordered_reason_codes:
            return "Recommendation introduces unsupported concrete facts that are not licensed by the truth context."
        if "unsupported_location" in ordered_reason_codes:
            return "Recommendation depends on an unsupported location token and must be narrowed before use."
        if "unsupported_service_label" in ordered_reason_codes:
            return "Recommendation depends on an unsupported service label and cannot pass Track B."
        if "unsupported_premise_ref" in ordered_reason_codes:
            return "Recommendation depends on a factual premise that was not supported strongly enough during mixed-claim shadow atomization."
        if "generic_advice" in ordered_reason_codes:
            return "Recommendation is too generic to justify for this specific site."
        if "no_supported_problem" in ordered_reason_codes:
            return "Recommendation does not resolve a supported problem from the current truth context."
        if "needs_narrower_wording" in ordered_reason_codes:
            return "Recommendation is directionally useful but too concrete for the evidence currently supported."
        if shadow_disposition == "supported":
            return "Recommendation is anchored to supported problems and stays within the supported site context."
        if shadow_disposition == TRACK_B_NEEDS_MANUAL_REVIEW:
            return "Recommendation may be useful, but the available evidence remains contested and requires human verification."
        if shadow_disposition == "flagged":
            return "Recommendation is relevant but needs tighter wording or stronger site-specific anchoring."
        return "Recommendation did not meet the Track B support thresholds."

    def _build_track_b_judge_resolution(
        self,
        *,
        shadow_disposition: str,
        confidence_band: str,
        reason_codes: list[str],
    ) -> str:
        ordered_reason_codes = self._sort_reason_codes(reason_codes)
        if shadow_disposition == TRACK_B_NEEDS_MANUAL_REVIEW or confidence_band == "contested":
            return "Signal weak or partially contradictory; manual verification required."
        if shadow_disposition == "supported":
            return "Recommendation is sufficiently grounded for automated acceptance."
        if shadow_disposition == "flagged":
            return "Recommendation can remain with caution, but should be tightened before publication."
        if "track_b_judge_unavailable" in ordered_reason_codes:
            return "Judge was unavailable; recommendation was safely blocked."
        return "Recommendation should remain blocked until stronger evidence is available."

    def _rewrite_claim(self, claim_text: str, reason_codes: list[str]) -> str:
        if not reason_codes or "needs_narrower_wording" not in reason_codes:
            return ""
        lowered = claim_text.lower()
        if "h1" in lowered:
            return "Add an explicit local-market modifier to the H1 that matches the supported target market."
        if "schema" in lowered:
            return "Add schema markup that matches the supported page intent and content."
        if "faq" in lowered:
            return "Add a FAQ element that matches the supported market, page, or offer set."
        return (
            "Narrow the recommendation to the supported market, page, or offer set and remove "
            "unsupported concrete facts."
        )

    def _normalize_evidence_refs(self, refs: Any) -> list[str]:
        if not isinstance(refs, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in refs:
            candidate = ""
            if isinstance(item, dict):
                candidate = (
                    _normalize_text(item.get("source_key"))
                    or _normalize_text(item.get("source_id"))
                    or _normalize_text(item.get("excerpt"))[:160]
                    or _normalize_text(item.get("source_type"))
                )
            else:
                candidate = _normalize_text(item)
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return normalized

    def _normalize_string_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            cleaned = _normalize_text(value)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    def _sort_reason_codes(self, reason_codes: list[str]) -> list[str]:
        return sorted(
            self._normalize_string_list(reason_codes),
            key=lambda code: (
                _TRACK_B_REASON_CODE_PREFERENCE.index(code)
                if code in _TRACK_B_REASON_CODE_PREFERENCE
                else len(_TRACK_B_REASON_CODE_PREFERENCE)
            ),
        )

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9]+", text.lower())
        return [word for word in words if len(word) > 2 and word not in _STOPWORDS]

    def _overlap_ratio(self, left: list[str], right: list[str]) -> float:
        if not left or not right:
            return 0.0
        left_set = set(left)
        right_set = set(right)
        return len(left_set & right_set) / len(left_set)
