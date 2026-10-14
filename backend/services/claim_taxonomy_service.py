from __future__ import annotations

import re
from typing import Any


TRACK_A = "track_a"
TRACK_B = "track_b"
TRACK_MIXED = "mixed"

CLAIM_KIND_DESCRIPTIVE_OBSERVATION = "descriptive_observation"
CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION = "prescriptive_recommendation"
CLAIM_KIND_CAUSAL_HYPOTHESIS = "causal_hypothesis"
CLAIM_KIND_FORECAST_OR_IMPACT = "forecast_or_impact"
CLAIM_KIND_MIXED = "mixed"

_FACTUAL_VERBS = (
    "is",
    "are",
    "was",
    "were",
    "has",
    "have",
    "does",
    "offers",
    "serves",
    "includes",
    "contains",
    "mentions",
    "supports",
    "shows",
    "uses",
    "exists",
)
_ABSENCE_MARKERS = (
    "does not",
    "do not",
    "did not",
    "is missing",
    "are missing",
    "lacks",
    "lack",
    "missing",
    "not found",
    "no ",
    "without ",
)
_PRESCRIPTIVE_PATTERNS = (
    r"\badd\b",
    r"\bcreate\b",
    r"\bupdate\b",
    r"\bimprove\b",
    r"\boptimi[sz]e\b",
    r"\brewrite\b",
    r"\bexpand\b",
    r"\bpublish\b",
    r"\bbuild\b",
    r"\bclarify\b",
    r"\bprioriti[sz]e\b",
    r"\binclude\b",
    r"\bintroduce\b",
    r"\bremove\b",
    r"\bfix\b",
    r"\balign\b",
    r"\bshould\b",
    r"\bneeds?\s+to\b",
    r"\bconsider\b",
    r"\bfocus\s+on\b",
)
_FORECAST_MARKERS = (
    "will improve",
    "would improve",
    "can improve",
    "could improve",
    "may improve",
    "likely improve",
    "is likely to improve",
    "increase",
    "lift",
    "reduce",
    "drive",
    "boost",
)
_CAUSE_PREFIX_RE = re.compile(
    r"^\s*(?:because|since|as|given that|due to)\s+(?P<premise>.+?)[,;:]\s*(?P<action>.+?)\s*$",
    re.IGNORECASE,
)
_THEREFORE_SPLIT_RE = re.compile(
    r"^\s*(?P<premise>.+?)\s+(?:so|therefore|thus|which is why)\s+(?P<action>.+?)\s*$",
    re.IGNORECASE,
)
_QUOTED_PHRASE_RE = re.compile(r"['\"][^'\"]+['\"]")
_CURRENCY_OR_PERCENT_RE = re.compile(r"(?:\$|\bUSD\b|\bEUR\b|\b\d+(?:\.\d+)?%|\b\d+(?:\.\d+)?)")
_MID_SENTENCE_PROPER_NOUN_RE = re.compile(r"(?<!^)\b[A-Z][a-z]{2,}\b")
_BUSINESS_FACT_TOKENS = (
    "office",
    "offices",
    "branch",
    "branches",
    "certification",
    "certified",
    "partner",
    "partners",
    "pricing",
    "price",
    "cost",
    "fee",
    "plan",
    "location",
    "locations",
    "market",
    "markets",
    "service",
    "services",
)
_RECOMMENDATION_CONTEXT_FIELDS = {
    "recommendations",
    "strategic_roadmap",
    "market_dominance_projection",
    "neural_intelligence_grid",
}


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


class ClaimTaxonomyService:
    """Classifies extracted claims without changing current grounding verdict logic."""

    def annotate_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        normalized_text = _normalize_text(claim.get("text"))
        annotated = dict(claim)
        if not normalized_text:
            annotated.update(
                {
                    "track": TRACK_A,
                    "claim_kind": CLAIM_KIND_DESCRIPTIVE_OBSERVATION,
                    "classification_basis": [],
                    "premise_refs": [],
                    "omittable": bool(claim.get("omittable", False)),
                }
            )
            return annotated

        field_group = _normalize_text(claim.get("field_group")).lower()
        track, claim_kind, classification_basis = self._classify_claim(
            text=normalized_text,
            field_group=field_group,
        )
        annotated.update(
            {
                "text": normalized_text,
                "track": track,
                "claim_kind": claim_kind,
                "classification_basis": classification_basis,
                "premise_refs": [],
                "omittable": bool(claim.get("omittable", False)),
            }
        )
        return annotated

    def atomize_claim(self, claim: dict[str, Any]) -> list[dict[str, Any]]:
        annotated = self.annotate_claim(claim)
        if annotated.get("track") != TRACK_MIXED:
            return [annotated]

        split_payload = self._split_mixed_claim(annotated)
        if split_payload is None:
            fallback = dict(annotated)
            fallback["track"] = TRACK_A
            fallback["claim_kind"] = CLAIM_KIND_DESCRIPTIVE_OBSERVATION
            fallback["classification_basis"] = self._dedupe_basis(
                [
                    *fallback.get("classification_basis", []),
                    "mixed_unsplittable_defaults_to_track_a",
                ]
            )
            return [fallback]

        base_id = str(annotated.get("id") or "claim")
        premise = dict(annotated)
        premise.update(
            {
                "id": f"{base_id}-a",
                "text": split_payload["premise"],
            }
        )
        premise = self.annotate_claim(premise)

        recommendation = dict(annotated)
        recommendation.update(
            {
                "id": f"{base_id}-b",
                "text": split_payload["recommendation"],
            }
        )
        recommendation = self.annotate_claim(recommendation)
        recommendation["premise_refs"] = [premise["id"]]
        recommendation["classification_basis"] = self._dedupe_basis(
            [*recommendation.get("classification_basis", []), "derived_from_supported_premise"]
        )
        return [premise, recommendation]

    def _classify_claim(
        self,
        *,
        text: str,
        field_group: str,
    ) -> tuple[str, str, list[str]]:
        lowered = text.lower()
        basis: list[str] = []

        has_conditional_recommendation = self._is_metadata_conditioned_recommendation(lowered)
        has_prescriptive_marker = self._has_prescriptive_marker(lowered)
        has_factual_marker = self._has_factual_marker(lowered)
        has_forecast_marker = any(marker in lowered for marker in _FORECAST_MARKERS)

        if field_group in _RECOMMENDATION_CONTEXT_FIELDS and has_prescriptive_marker:
            basis.append("field_recommendation_context")

        if has_conditional_recommendation:
            basis.append("conditional_on_authoritative_metadata")
        if self._asserts_absence(lowered):
            basis.append("asserts_absence")
        if has_factual_marker:
            basis.append("asserts_current_state")
        if has_prescriptive_marker:
            basis.append("contains_imperative_action")
        if has_forecast_marker:
            basis.append("contains_forecast_or_impact")
        if self._contains_unsupported_concrete_token(text, prescriptive=has_prescriptive_marker):
            basis.append("contains_unsupported_concrete_token")

        if has_conditional_recommendation:
            track = TRACK_B
        elif has_factual_marker and has_prescriptive_marker:
            track = TRACK_MIXED
            basis.append("mixed_fact_and_prescription")
        elif has_prescriptive_marker or (
            field_group in _RECOMMENDATION_CONTEXT_FIELDS and has_forecast_marker
        ):
            track = TRACK_B
        else:
            track = TRACK_A

        if track == TRACK_MIXED:
            claim_kind = CLAIM_KIND_MIXED
        elif track == TRACK_B and (has_forecast_marker and not has_prescriptive_marker):
            claim_kind = CLAIM_KIND_FORECAST_OR_IMPACT
        elif track == TRACK_B:
            claim_kind = CLAIM_KIND_PRESCRIPTIVE_RECOMMENDATION
        elif self._has_causal_marker(lowered):
            claim_kind = CLAIM_KIND_CAUSAL_HYPOTHESIS
        elif has_forecast_marker:
            claim_kind = CLAIM_KIND_FORECAST_OR_IMPACT
        else:
            claim_kind = CLAIM_KIND_DESCRIPTIVE_OBSERVATION

        return track, claim_kind, self._dedupe_basis(basis)

    def _split_mixed_claim(self, claim: dict[str, Any]) -> dict[str, str] | None:
        text = str(claim.get("text") or "").strip()
        if not text or text.lower().startswith("if "):
            return None

        for matcher in (_CAUSE_PREFIX_RE, _THEREFORE_SPLIT_RE):
            match = matcher.match(text)
            if not match:
                continue

            premise = _normalize_text(match.group("premise"))
            recommendation = _normalize_text(match.group("action"))
            if not premise or not recommendation:
                return None
            return {
                "premise": self._ensure_terminal_punctuation(premise),
                "recommendation": self._ensure_terminal_punctuation(recommendation),
            }
        return None

    def _has_factual_marker(self, lowered: str) -> bool:
        if self._asserts_absence(lowered):
            return True
        if any(f" {verb} " in f" {lowered} " for verb in _FACTUAL_VERBS):
            return True
        return any(
            token in lowered
            for token in (
                "found in the crawl",
                "was found",
                "were found",
                "detected",
                "observed",
                "present on the site",
                "available on the site",
            )
        )

    def _asserts_absence(self, lowered: str) -> bool:
        normalized = f" {lowered} "
        return any(marker in normalized for marker in _ABSENCE_MARKERS)

    def _has_prescriptive_marker(self, lowered: str) -> bool:
        return any(re.search(pattern, lowered) for pattern in _PRESCRIPTIVE_PATTERNS)

    def _has_causal_marker(self, lowered: str) -> bool:
        return any(token in lowered for token in ("because", "due to", "driven by", "caused by"))

    def _is_metadata_conditioned_recommendation(self, lowered: str) -> bool:
        if " if " not in f" {lowered} " or not self._has_prescriptive_marker(lowered):
            return False
        return any(
            marker in lowered
            for marker in (
                "supported market",
                "supported target market",
                "target market",
                "target markets",
                "supported region",
                "supported locale",
            )
        ) or lowered.startswith("if ")

    def _contains_unsupported_concrete_token(self, text: str, *, prescriptive: bool) -> bool:
        if not prescriptive:
            return False
        lowered = text.lower()
        if _QUOTED_PHRASE_RE.search(text):
            return True
        if _CURRENCY_OR_PERCENT_RE.search(text):
            return True
        if any(token in lowered for token in _BUSINESS_FACT_TOKENS):
            return True
        return _MID_SENTENCE_PROPER_NOUN_RE.search(text) is not None

    def _dedupe_basis(self, basis: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for item in basis:
            normalized = _normalize_text(item)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _ensure_terminal_punctuation(self, value: str) -> str:
        if not value:
            return value
        if value[-1] in ".!?":
            return value
        return f"{value}."
