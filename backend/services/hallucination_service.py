from __future__ import annotations

import logging
import math
import re
from collections import Counter, defaultdict
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from services.claim_taxonomy_service import ClaimTaxonomyService

if TYPE_CHECKING:
    from services.embedding_service import EmbeddingCache

logger = logging.getLogger(__name__)

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
    "will",
    "with",
}


class HallucinationService:
    """Local retrieval-based grounding checks for AI-generated report claims."""

    _CRITICAL_TRUTH_FIELDS = {"pricing", "features", "policies"}
    _FIELD_RULES = (
        {"field": "summary", "label": "Summary", "kind": "text", "omittable": True},
        {
            "field": "recommendations",
            "label": "Recommendations",
            "kind": "list_strings",
            "omittable": True,
        },
        {
            "field": "seo_findings",
            "label": "SEO Findings",
            "kind": "list_dicts",
            "text_keys": ("description",),
        },
        {
            "field": "geo_findings",
            "label": "GEO Findings",
            "kind": "list_dicts",
            "text_keys": ("description",),
        },
        {
            "field": "aeo_findings",
            "label": "AEO Findings",
            "kind": "list_dicts",
            "text_keys": ("description",),
        },
        {
            "field": "executive_dossier",
            "label": "Executive Dossier",
            "kind": "text",
            "omittable": True,
        },
        {
            "field": "findings",
            "label": "Detailed Findings",
            "kind": "list_dicts",
            "text_keys": ("observation", "generative_impact", "implementation_guide"),
        },
        {
            "field": "strategic_roadmap",
            "label": "Strategic Roadmap",
            "kind": "text",
            "omittable": True,
        },
        {
            "field": "neural_intelligence_grid",
            "label": "Strategic Intelligence Grid",
            "kind": "list_dicts",
            "text_keys": ("discovery", "neural_logic", "architect_fix"),
        },
        {
            "field": "market_dominance_projection",
            "label": "Market Dominance Projection",
            "kind": "text",
            "omittable": True,
        },
    )
    _NARRATIVE_FIELDS = {
        "summary",
        "executive_dossier",
        "strategic_roadmap",
        "market_dominance_projection",
    }

    def __init__(
        self,
        *,
        chunk_size: int = 900,
        chunk_overlap: int = 140,
        max_passages: int = 3,
        grounding_threshold: float = 0.10,
        failing_score_threshold: int = 70,
        similarity_threshold: float = 0.85,
        embedding_batch_size: int = 32,
        certainty_threshold: float = 0.32,
        omit_threshold: float = 0.25,
        high_certainty_threshold: float = 0.70,
        embedding_grounding_threshold: float = 0.58,
        embedding_certainty_threshold: float = 0.50,
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.max_passages = max_passages
        self.grounding_threshold = grounding_threshold
        self.failing_score_threshold = failing_score_threshold
        self.similarity_threshold = similarity_threshold
        self.embedding_batch_size = embedding_batch_size
        self.certainty_threshold = certainty_threshold
        self.omit_threshold = omit_threshold
        self.high_certainty_threshold = high_certainty_threshold
        self.embedding_grounding_threshold = embedding_grounding_threshold
        self.embedding_certainty_threshold = embedding_certainty_threshold
        self.claim_taxonomy_service = ClaimTaxonomyService()

    def analyze(
        self,
        *,
        source_content: str,
        analysis: dict[str, Any],
        brand_truth_payload: dict[str, Any] | None = None,
        embedding_cache: EmbeddingCache | None = None,
        forbidden_brand_facts: list[Any] | None = None,
    ) -> dict[str, Any]:
        truth_payload = (
            brand_truth_payload
            if isinstance(brand_truth_payload, dict)
            else (
                analysis.get("brand_truth")
                if isinstance(analysis.get("brand_truth"), dict)
                else None
            )
        )
        if truth_payload:
            return self._analyze_against_brand_truth(
                analysis=analysis, brand_truth_payload=truth_payload
            )

        # Additive guardrail (goal-(b)): forbidden brand facts are layered ON TOP
        # of source-content grounding, never via the brand_truth short-circuit
        # above and never by altering a threshold. Empty list => zero change.
        forbidden_statements = self._normalize_forbidden_statements(forbidden_brand_facts)

        claim_items = self._extract_claim_items(analysis)
        if not claim_items:
            return self._empty_result(threshold=self.certainty_threshold)

        chunks = self._chunk_text(source_content)
        chunk_vectors, idf = self._build_index(chunks)

        use_dense = embedding_cache is not None and embedding_cache.using_dense

        claim_verifications: list[dict[str, Any]] = []
        evaluations: list[dict[str, Any]] = []
        unsupported: list[str] = []
        supported_count = 0

        for claim in claim_items:
            if use_dense:
                evidence_refs = self._retrieve_evidence_dense(
                    sentence=claim["text"],
                    chunks=chunks,
                    embedding_cache=embedding_cache,
                )
                grounded, certainty, raw_certainty, reason = self._classify_grounded_dense(
                    claim["text"],
                    evidence_refs,
                    embedding_cache,
                )
            else:
                evidence_refs = self._retrieve_relevant_evidence_refs(
                    sentence=claim["text"],
                    chunks=chunks,
                    chunk_vectors=chunk_vectors,
                    idf=idf,
                )
                grounded, certainty, raw_certainty, reason = self._classify_grounded(
                    claim["text"], evidence_refs
                )
            certainty_level = self._certainty_level(certainty)
            disposition = self._determine_disposition(
                grounded=grounded,
                certainty=certainty,
                omittable=bool(claim.get("omittable")),
                raw_certainty=raw_certainty,
            )
            hallucination = disposition != "supported"
            if not hallucination:
                supported_count += 1
            else:
                unsupported.append(claim["text"])

            discrepancy_type, severity = self._classify_grounding_discrepancy(
                field_group=str(claim.get("field_group") or ""),
                hallucination=hallucination,
                disposition=disposition,
            )

            top_match = evidence_refs[0] if evidence_refs else None
            claim_verification = {
                "claim_id": claim["id"],
                "claim_text": claim["text"],
                "matched_truth_key": str(
                    top_match.get("source_key") if top_match else "no_evidence"
                ),
                "truth_value": str(
                    top_match.get("excerpt")
                    if top_match
                    else "No relevant supporting passage found in crawled content."
                ),
                "similarity_score": round(certainty, 4),
                "hallucination": hallucination,
                "discrepancy_type": discrepancy_type,
                "severity": severity,
                "field_path": claim["field_path"],
                "field_label": claim["field_label"],
                "certainty_score": round(certainty, 4),
                "certainty_level": certainty_level,
                "disposition": disposition,
                "evidence_refs": evidence_refs,
                "track": claim.get("track"),
                "claim_kind": claim.get("claim_kind"),
                "classification_basis": list(claim.get("classification_basis") or []),
                "premise_refs": list(claim.get("premise_refs") or []),
                "omittable": bool(claim.get("omittable", False)),
            }
            claim_verifications.append(claim_verification)
            evaluations.append(
                {
                    "sentence": claim["text"],
                    "field_path": claim["field_path"],
                    "field_label": claim["field_label"],
                    "grounded": grounded,
                    "confidence": round(certainty, 4),
                    "certainty_score": round(certainty, 4),
                    "certainty_level": certainty_level,
                    "disposition": disposition,
                    "supporting_passages": [ref["excerpt"] for ref in evidence_refs],
                    "evidence_refs": evidence_refs,
                    "reason": reason,
                    "track": claim.get("track"),
                    "claim_kind": claim.get("claim_kind"),
                    "classification_basis": list(claim.get("classification_basis") or []),
                }
            )

        if forbidden_statements:
            supported_count, unsupported = self._apply_forbidden_fact_contradictions(
                claim_verifications=claim_verifications,
                evaluations=evaluations,
                forbidden_statements=forbidden_statements,
            )

        result = self._build_result_payload(
            analysis=analysis,
            claim_items=claim_items,
            claim_verifications=claim_verifications,
            evaluations=evaluations,
            supported_count=supported_count,
            unsupported=unsupported,
            threshold=self.embedding_certainty_threshold if use_dense else self.certainty_threshold,
        )
        if embedding_cache is not None:
            result["embedding_stats"] = embedding_cache.stats
        return result

    def _analyze_against_brand_truth(
        self, *, analysis: dict[str, Any], brand_truth_payload: dict[str, Any]
    ) -> dict[str, Any]:
        claim_items = self._extract_claim_items(analysis)
        truth_map = self._extract_truth_map(brand_truth_payload)
        if not claim_items or not truth_map:
            return self._empty_result(threshold=self.similarity_threshold)

        mapped_pairs: list[tuple[dict[str, Any], str, dict[str, Any]]] = []
        for claim in claim_items:
            truth_key, truth_payload = self._match_truth_for_claim(claim, truth_map)
            mapped_pairs.append((claim, truth_key, truth_payload))

        claim_texts = [pair[0]["text"] for pair in mapped_pairs]
        truth_texts = [pair[2]["text"] for pair in mapped_pairs]
        claim_vectors = self._embed_texts_in_batches(claim_texts)
        truth_vectors = self._embed_texts_in_batches(truth_texts)

        evaluations: list[dict[str, Any]] = []
        claim_verifications: list[dict[str, Any]] = []
        unsupported: list[str] = []
        supported_count = 0

        for (claim, truth_key, truth_payload), claim_vector, truth_vector in zip(
            mapped_pairs, claim_vectors, truth_vectors
        ):
            truth_value = truth_payload["text"]
            similarity = self._cosine_similarity(claim_vector, truth_vector)
            grounded = similarity >= self.similarity_threshold
            disposition = self._determine_disposition(
                grounded=grounded,
                certainty=similarity,
                omittable=bool(claim.get("omittable")),
            )
            hallucination = disposition != "supported"
            certainty_level = self._certainty_level(similarity)
            if not hallucination:
                supported_count += 1
            else:
                unsupported.append(claim["text"])

            discrepancy_type, severity = self._classify_discrepancy(
                claim_text=claim["text"],
                truth_key=truth_key,
                truth_payload=truth_payload,
                hallucination=hallucination,
            )
            if disposition == "omitted" and severity == "medium":
                severity = "high"

            evidence_refs = [
                {
                    "source_type": "brand_truth",
                    "source_key": truth_key,
                    "excerpt": truth_value,
                    "retrieval_score": round(similarity, 4),
                }
            ]
            claim_audit = {
                "claim_id": claim["id"],
                "claim_text": claim["text"],
                "matched_truth_key": truth_key,
                "truth_value": truth_value,
                "similarity_score": round(similarity, 4),
                "hallucination": hallucination,
                "discrepancy_type": discrepancy_type,
                "severity": severity,
                "field_path": claim.get("field_path"),
                "field_label": claim.get("field_label"),
                "certainty_score": round(similarity, 4),
                "certainty_level": certainty_level,
                "disposition": disposition,
                "evidence_refs": evidence_refs,
                "track": claim.get("track"),
                "claim_kind": claim.get("claim_kind"),
                "classification_basis": list(claim.get("classification_basis") or []),
                "premise_refs": list(claim.get("premise_refs") or []),
                "omittable": bool(claim.get("omittable", False)),
            }
            claim_verifications.append(claim_audit)
            evaluations.append(
                {
                    "sentence": claim["text"],
                    "field_path": claim.get("field_path"),
                    "field_label": claim.get("field_label"),
                    "grounded": grounded,
                    "confidence": round(similarity, 4),
                    "certainty_score": round(similarity, 4),
                    "certainty_level": certainty_level,
                    "disposition": disposition,
                    "supporting_passages": [truth_value],
                    "evidence_refs": evidence_refs,
                    "reason": f"Matched against brand truth '{truth_key}'.",
                    "track": claim.get("track"),
                    "claim_kind": claim.get("claim_kind"),
                    "classification_basis": list(claim.get("classification_basis") or []),
                }
            )
            logger.info("Claim verification audit", extra={"claim_audit": claim_audit})

        result = self._build_result_payload(
            analysis=analysis,
            claim_items=claim_items,
            claim_verifications=claim_verifications,
            evaluations=evaluations,
            supported_count=supported_count,
            unsupported=unsupported,
            threshold=self.similarity_threshold,
        )
        result["threshold"] = self.similarity_threshold
        return result

    def _build_result_payload(
        self,
        *,
        analysis: dict[str, Any],
        claim_items: list[dict[str, Any]],
        claim_verifications: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        supported_count: int,
        unsupported: list[str],
        threshold: float,
    ) -> dict[str, Any]:
        total = len(claim_items)
        score = int(round((supported_count / total) * 100)) if total else 100
        flagged = score < self.failing_score_threshold
        field_summaries = self._build_field_summaries(claim_items, claim_verifications)
        omitted_claims = sum(
            1 for claim in claim_verifications if str(claim.get("disposition") or "") == "omitted"
        )
        certainty_scores = [
            float(claim.get("certainty_score") or 0.0)
            for claim in claim_verifications
            if claim.get("certainty_score") is not None
        ]
        average_certainty = (
            sum(certainty_scores) / len(certainty_scores) if certainty_scores else 0.0
        )
        high_risk_discrepancies = [
            claim
            for claim in claim_verifications
            if claim.get("hallucination") and claim.get("severity") in {"high", "critical"}
        ]
        # Core metrics exclude narrative/omittable fields for a tighter accuracy signal.
        core_total = 0
        core_supported = 0
        for ci, cv in zip(claim_items, claim_verifications):
            if str(ci.get("field") or "") not in self._NARRATIVE_FIELDS:
                core_total += 1
                if str(cv.get("disposition") or "") == "supported":
                    core_supported += 1

        return {
            "score": score,
            "flagged": flagged,
            "unsupported_sentences": unsupported,
            "sentence_evaluations": evaluations,
            "total_sentences": total,
            "supported_sentences": supported_count,
            "core_total_sentences": core_total,
            "core_supported_sentences": core_supported,
            "claim_verifications": claim_verifications,
            "threshold": threshold,
            "omitted_claims": omitted_claims,
            "average_certainty": round(average_certainty, 4),
            "field_summaries": field_summaries,
            "high_risk_discrepancies": high_risk_discrepancies,
            "sanitized_analysis": self._sanitize_analysis(
                analysis, claim_items, claim_verifications
            ),
        }

    def _empty_result(self, *, threshold: float) -> dict[str, Any]:
        return {
            "score": 100,
            "flagged": False,
            "unsupported_sentences": [],
            "sentence_evaluations": [],
            "total_sentences": 0,
            "supported_sentences": 0,
            "core_total_sentences": 0,
            "core_supported_sentences": 0,
            "claim_verifications": [],
            "threshold": threshold,
            "omitted_claims": 0,
            "average_certainty": 1.0,
            "field_summaries": [],
            "high_risk_discrepancies": [],
            "sanitized_analysis": {},
        }

    def _extract_claim_items(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        claims = analysis.get("claims")
        if isinstance(claims, list):
            parsed_claims: list[dict[str, Any]] = []
            for index, item in enumerate(claims, start=1):
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    field_path = item.get("field_path")
                    field_label = item.get("field_label")
                    parsed_claims.append(
                        self.claim_taxonomy_service.annotate_claim(
                            {
                                "id": str(item.get("id") or f"claim-{index}"),
                                "text": item["text"].strip(),
                                "field_path": (
                                    field_path
                                    if isinstance(field_path, str) and field_path.strip()
                                    else None
                                ),
                                "field_label": (
                                    field_label
                                    if isinstance(field_label, str) and field_label.strip()
                                    else None
                                ),
                                "field_group": str(item.get("field_group") or "claims"),
                                "group_label": str(item.get("group_label") or "Claims"),
                                "omittable": bool(item.get("omittable", False)),
                                "extraction_kind": "provided_claim",
                            }
                        )
                    )
                elif isinstance(item, str) and item.strip():
                    parsed_claims.append(
                        self.claim_taxonomy_service.annotate_claim(
                            {
                                "id": f"claim-{index}",
                                "text": item.strip(),
                                "field_path": None,
                                "field_label": None,
                                "field_group": "claims",
                                "group_label": "Claims",
                                "omittable": False,
                                "extraction_kind": "provided_claim",
                            }
                        )
                    )
            if parsed_claims:
                return parsed_claims

        return self._extract_field_level_claims(analysis)

    def extract_claim_candidates(self, analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not isinstance(analysis, dict):
            return []
        return [
            dict(item) for item in self._extract_claim_items(analysis) if isinstance(item, dict)
        ]

    def _extract_field_level_claims(self, analysis: dict[str, Any]) -> list[dict[str, Any]]:
        claim_items: list[dict[str, Any]] = []
        claim_index = 0

        def _append_claim(
            *,
            text: str,
            field_path: str,
            field_label: str,
            field_group: str,
            group_label: str,
            omittable: bool,
            extraction_kind: str,
            item_index: int | None = None,
        ) -> None:
            nonlocal claim_index
            normalized = text.strip()
            if not normalized:
                return
            claim_index += 1
            claim_items.append(
                self.claim_taxonomy_service.annotate_claim(
                    {
                        "id": f"claim-{claim_index}",
                        "text": normalized,
                        "field_path": field_path,
                        "field_label": field_label,
                        "field_group": field_group,
                        "group_label": group_label,
                        "omittable": omittable,
                        "extraction_kind": extraction_kind,
                        "item_index": item_index,
                    }
                )
            )

        for rule in self._FIELD_RULES:
            field = rule["field"]
            label = rule["label"]
            value = analysis.get(field)
            kind = rule["kind"]
            omittable = bool(rule.get("omittable", False))

            if kind == "text" and isinstance(value, str):
                sentences = self._split_sentences(value)
                for sentence_index, sentence in enumerate(sentences, start=1):
                    field_label = (
                        label if len(sentences) == 1 else f"{label} sentence {sentence_index}"
                    )
                    _append_claim(
                        text=sentence,
                        field_path=field,
                        field_label=field_label,
                        field_group=field,
                        group_label=label,
                        omittable=omittable,
                        extraction_kind="sentence",
                    )
            elif kind == "list_strings" and isinstance(value, list):
                for item_index, item in enumerate(value):
                    if not isinstance(item, str):
                        continue
                    _append_claim(
                        text=item,
                        field_path=f"{field}[{item_index}]",
                        field_label=f"{label} {item_index + 1}",
                        field_group=field,
                        group_label=label,
                        omittable=omittable,
                        extraction_kind="list_item",
                        item_index=item_index,
                    )
            elif kind == "list_dicts" and isinstance(value, list):
                text_keys = tuple(rule.get("text_keys") or ())
                for item_index, item in enumerate(value):
                    if not isinstance(item, dict):
                        continue
                    for text_key in text_keys:
                        text = item.get(text_key)
                        if not isinstance(text, str):
                            continue
                        _append_claim(
                            text=text,
                            field_path=f"{field}[{item_index}].{text_key}",
                            field_label=f"{label} {item_index + 1} {text_key.replace('_', ' ')}",
                            field_group=field,
                            group_label=label,
                            omittable=omittable,
                            extraction_kind="dict_field",
                            item_index=item_index,
                        )

        return claim_items

    def _extract_truth_map(self, brand_truth_payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
        truths = brand_truth_payload.get("truths")
        truth_map: dict[str, dict[str, Any]] = {}
        if isinstance(truths, dict):
            for key, value in truths.items():
                if isinstance(value, str) and value.strip():
                    truth_map[str(key)] = {
                        "text": value.strip(),
                        "category": None,
                        "critical": False,
                    }
                elif isinstance(value, dict):
                    text = value.get("value") or value.get("text")
                    if isinstance(text, str) and text.strip():
                        category = value.get("category")
                        truth_map[str(key)] = {
                            "text": text.strip(),
                            "category": category if isinstance(category, str) else None,
                            "critical": bool(value.get("critical", False)),
                        }
        elif isinstance(truths, list):
            for index, item in enumerate(truths, start=1):
                if not isinstance(item, dict):
                    continue
                value = item.get("value") or item.get("text")
                if isinstance(value, str) and value.strip():
                    key = str(item.get("key") or item.get("id") or f"truth-{index}")
                    category = item.get("category")
                    truth_map[key] = {
                        "text": value.strip(),
                        "category": category if isinstance(category, str) else None,
                        "critical": bool(item.get("critical", False)),
                    }

        structured_sections = brand_truth_payload.get("critical_fields")
        if not isinstance(structured_sections, dict):
            structured_sections = brand_truth_payload
        for field in self._CRITICAL_TRUTH_FIELDS:
            self._append_structured_truth_entries(
                truth_map=truth_map,
                section_key=field,
                section_payload=structured_sections.get(field)
                if isinstance(structured_sections, dict)
                else None,
            )
        return truth_map

    def _append_structured_truth_entries(
        self,
        *,
        truth_map: dict[str, dict[str, Any]],
        section_key: str,
        section_payload: Any,
    ) -> None:
        if isinstance(section_payload, str) and section_payload.strip():
            truth_map[f"{section_key}-1"] = {
                "text": section_payload.strip(),
                "category": section_key,
                "critical": True,
            }
            return

        if isinstance(section_payload, list):
            for index, item in enumerate(section_payload, start=1):
                if isinstance(item, str) and item.strip():
                    truth_map[f"{section_key}-{index}"] = {
                        "text": item.strip(),
                        "category": section_key,
                        "critical": True,
                    }
                elif isinstance(item, dict):
                    text = item.get("value") or item.get("text")
                    if isinstance(text, str) and text.strip():
                        key = str(item.get("key") or item.get("id") or f"{section_key}-{index}")
                        truth_map[key] = {
                            "text": text.strip(),
                            "category": section_key,
                            "critical": True,
                        }
            return

        if isinstance(section_payload, dict):
            for index, (key, value) in enumerate(section_payload.items(), start=1):
                if isinstance(value, str) and value.strip():
                    truth_map[str(key) or f"{section_key}-{index}"] = {
                        "text": value.strip(),
                        "category": section_key,
                        "critical": True,
                    }
                elif isinstance(value, dict):
                    text = value.get("value") or value.get("text")
                    if isinstance(text, str) and text.strip():
                        truth_map[str(key) or f"{section_key}-{index}"] = {
                            "text": text.strip(),
                            "category": section_key,
                            "critical": True,
                        }

    def _match_truth_for_claim(
        self, claim: dict[str, Any], truth_map: dict[str, dict[str, Any]]
    ) -> tuple[str, dict[str, Any]]:
        claim_id = claim.get("id")
        if claim_id and claim_id in truth_map:
            return claim_id, truth_map[claim_id]

        claim_tokens = set(self._tokenize(claim.get("text", "")))
        best_key = next(iter(truth_map))
        best_value = truth_map[best_key]
        best_score = -1.0
        for key, value in truth_map.items():
            truth_tokens = set(self._tokenize(value.get("text", "")))
            if not claim_tokens or not truth_tokens:
                score = 0.0
            else:
                score = len(claim_tokens & truth_tokens) / len(claim_tokens | truth_tokens)
            if score > best_score:
                best_score = score
                best_key = key
                best_value = value
        return best_key, best_value

    def _classify_discrepancy(
        self,
        *,
        claim_text: str,
        truth_key: str,
        truth_payload: dict[str, Any],
        hallucination: bool,
    ) -> tuple[str | None, str]:
        text = " ".join(
            [claim_text or "", str(truth_key or ""), str(truth_payload.get("text") or "")]
        ).lower()
        category = str(truth_payload.get("category") or "").strip().lower()

        if not category:
            if any(
                token in text
                for token in ("price", "pricing", "cost", "plan", "billing", "fee", "usd", "eur")
            ):
                category = "pricing"
            elif any(
                token in text
                for token in (
                    "feature",
                    "integration",
                    "dashboard",
                    "automation",
                    "api",
                    "supports",
                )
            ):
                category = "features"
            elif any(
                token in text
                for token in (
                    "policy",
                    "refund",
                    "cancellation",
                    "cancel",
                    "privacy",
                    "security",
                    "gdpr",
                    "terms",
                    "sla",
                )
            ):
                category = "policies"

        discrepancy_type = {
            "pricing": "pricing_mismatch",
            "features": "features_mismatch",
            "policies": "policy_mismatch",
        }.get(category, "general_mismatch")

        if not hallucination:
            return discrepancy_type, "none"

        if bool(truth_payload.get("critical")) or category in self._CRITICAL_TRUTH_FIELDS:
            return discrepancy_type, "high"
        return discrepancy_type, "medium"

    def _build_field_summaries(
        self,
        claim_items: list[dict[str, Any]],
        claim_verifications: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for claim_item, verification in zip(claim_items, claim_verifications):
            grouped[str(claim_item.get("field_group") or "claims")].append(
                (claim_item, verification)
            )

        field_summaries: list[dict[str, Any]] = []
        for field_group, pairs in grouped.items():
            total_claims = len(pairs)
            supported_claims = sum(
                1
                for _, verification in pairs
                if str(verification.get("disposition") or "") == "supported"
            )
            flagged_claims = sum(
                1
                for _, verification in pairs
                if str(verification.get("disposition") or "") == "flagged"
            )
            omitted_claims = sum(
                1
                for _, verification in pairs
                if str(verification.get("disposition") or "") == "omitted"
            )
            certainty_scores = [
                float(verification.get("certainty_score") or 0.0)
                for _, verification in pairs
                if verification.get("certainty_score") is not None
            ]
            average_certainty = (
                sum(certainty_scores) / len(certainty_scores) if certainty_scores else 0.0
            )
            field_summaries.append(
                {
                    "field_path": field_group,
                    "label": str(pairs[0][0].get("group_label") or field_group),
                    "total_claims": total_claims,
                    "supported_claims": supported_claims,
                    "flagged_claims": flagged_claims,
                    "omitted_claims": omitted_claims,
                    "average_certainty": round(average_certainty, 4),
                    "certainty_level": self._certainty_level(average_certainty),
                }
            )

        field_summaries.sort(key=lambda item: str(item.get("field_path") or ""))
        return field_summaries

    def _sanitize_analysis(
        self,
        analysis: dict[str, Any],
        claim_items: list[dict[str, Any]],
        claim_verifications: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sanitized = deepcopy(analysis)
        omitted_sentences: dict[str, set[str]] = defaultdict(set)
        omitted_indices: dict[str, set[int]] = defaultdict(set)

        for claim_item, verification in zip(claim_items, claim_verifications):
            if str(verification.get("disposition") or "") != "omitted":
                continue
            field_group = str(claim_item.get("field_group") or "")
            extraction_kind = str(claim_item.get("extraction_kind") or "")
            if extraction_kind == "sentence":
                omitted_sentences[field_group].add(str(claim_item.get("text") or "").strip())
            elif extraction_kind == "list_item" and claim_item.get("item_index") is not None:
                omitted_indices[field_group].add(int(claim_item["item_index"]))

        for field_group, sentences in omitted_sentences.items():
            current_value = sanitized.get(field_group)
            if not isinstance(current_value, str):
                continue
            remaining_sentences = [
                sentence
                for sentence in self._split_sentences(current_value)
                if sentence.strip() and sentence.strip() not in sentences
            ]
            sanitized[field_group] = " ".join(remaining_sentences).strip() or None

        for field_group, indices in omitted_indices.items():
            current_value = sanitized.get(field_group)
            if not isinstance(current_value, list):
                continue
            sanitized[field_group] = [
                item for item_index, item in enumerate(current_value) if item_index not in indices
            ]

        return sanitized

    def _determine_disposition(
        self,
        *,
        grounded: bool,
        certainty: float,
        omittable: bool,
        raw_certainty: float | None = None,
    ) -> str:
        if grounded:
            return "supported"
        omit_score = raw_certainty if raw_certainty is not None else certainty
        if omittable and omit_score < self.omit_threshold:
            return "omitted"
        return "flagged"

    def _classify_grounding_discrepancy(
        self,
        *,
        field_group: str,
        hallucination: bool,
        disposition: str,
    ) -> tuple[str | None, str]:
        if not hallucination:
            return None, "none"
        if field_group == "recommendations":
            return "recommendation_grounding_gap", "high" if disposition == "omitted" else "medium"
        if field_group in self._NARRATIVE_FIELDS:
            return "narrative_grounding_gap", "high" if disposition == "omitted" else "medium"
        return "finding_grounding_gap", "medium"

    @staticmethod
    def _normalize_forbidden_statements(forbidden_brand_facts: list[Any] | None) -> list[str]:
        """Coerce the additive ``forbidden_brand_facts`` param to clean statements.

        Accepts a list of plain strings or of brand-fact dicts (``{"statement":
        ..., "is_forbidden": ...}``). Only ``is_forbidden`` dicts are kept. Any
        other / empty input yields ``[]`` so absence is a strict no-op.
        """
        if not isinstance(forbidden_brand_facts, list):
            return []
        statements: list[str] = []
        for item in forbidden_brand_facts:
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                if not item.get("is_forbidden"):
                    continue
                text = str(item.get("statement") or "").strip()
            else:
                continue
            if text:
                statements.append(text)
        return statements

    def _apply_forbidden_fact_contradictions(
        self,
        *,
        claim_verifications: list[dict[str, Any]],
        evaluations: list[dict[str, Any]],
        forbidden_statements: list[str],
    ) -> tuple[int, list[str]]:
        """Flag claims that assert a forbidden brand fact (ADDITIVE, stricter-only).

        Runs the pure ``forbidden_facts_detector`` over the already-computed
        claim verifications. For each contradicting claim it ANNOTATES the
        verification and forces it to a flagged disposition with zero certainty,
        so the downstream grounding gate treats it as ungrounded. This can only
        make grounding STRICTER (flag more); it never raises a certainty or
        loosens a threshold. Returns recomputed ``(supported_count, unsupported)``.
        """
        from services.forbidden_facts_detector import detect_forbidden_contradictions

        claim_texts = [str(cv.get("claim_text") or "") for cv in claim_verifications]
        matches = detect_forbidden_contradictions(
            claim_texts=claim_texts,
            forbidden_statements=forbidden_statements,
        )
        matches_by_index = {match.claim_index: match for match in matches}

        for index, verification in enumerate(claim_verifications):
            match = matches_by_index.get(index)
            if match is None:
                continue
            verification["hallucination"] = True
            verification["disposition"] = "flagged"
            verification["discrepancy_type"] = "forbidden_brand_fact_contradiction"
            verification["severity"] = "high"
            verification["certainty_score"] = 0.0
            verification["similarity_score"] = 0.0
            verification["certainty_level"] = "low"
            verification["forbidden_contradiction"] = True
            verification["forbidden_fact_statement"] = match.forbidden_statement
            if index < len(evaluations):
                evaluation = evaluations[index]
                evaluation["grounded"] = False
                evaluation["disposition"] = "flagged"
                evaluation["certainty_score"] = 0.0
                evaluation["confidence"] = 0.0
                evaluation["certainty_level"] = "low"
                evaluation["forbidden_contradiction"] = True
                evaluation["reason"] = (
                    "Claim asserts a forbidden brand fact; flagged by additive guardrail."
                )

        supported_count = sum(
            1 for cv in claim_verifications if str(cv.get("disposition") or "") == "supported"
        )
        unsupported = [
            str(cv.get("claim_text") or "")
            for cv in claim_verifications
            if str(cv.get("disposition") or "") != "supported"
        ]
        return supported_count, unsupported

    def _certainty_level(self, certainty: float) -> str:
        if certainty >= self.high_certainty_threshold:
            return "high"
        if certainty >= self.certainty_threshold:
            return "medium"
        return "low"

    def _embed_texts_in_batches(self, texts: list[str]) -> list[dict[str, float]]:
        vectors: list[dict[str, float]] = []
        for start in range(0, len(texts), self.embedding_batch_size):
            batch = texts[start : start + self.embedding_batch_size]
            vectors.extend(self._embed_batch(batch))
        return vectors

    def _embed_batch(self, texts: list[str]) -> list[dict[str, float]]:
        vectors: list[dict[str, float]] = []
        for text in texts:
            tokens = self._tokenize(text)
            counts = Counter(tokens)
            denom = sum(counts.values()) or 1
            vectors.append({token: count / denom for token, count in counts.items()})
        return vectors

    def _extract_claim_sentences(self, analysis: dict[str, Any]) -> list[str]:
        candidates = [claim.get("text") for claim in self._extract_field_level_claims(analysis)]
        deduped: list[str] = []
        seen: set[str] = set()
        for sentence in candidates:
            if not isinstance(sentence, str):
                continue
            normalized = sentence.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key not in seen:
                seen.add(key)
                deduped.append(normalized)
        return deduped

    def _split_sentences(self, text: str) -> list[str]:
        parts = re.split(r"(?<=[.!?])\s+|\n+", text.strip())
        return [part.strip(" -\t") for part in parts if part.strip(" -\t")]

    def _chunk_text(self, content: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", content or "").strip()
        if not normalized:
            return []

        chunks: list[str] = []
        start = 0
        length = len(normalized)
        while start < length:
            end = min(length, start + self.chunk_size)
            chunk = normalized[start:end].strip()
            if chunk:
                chunks.append(chunk)
            if end == length:
                break
            start = max(0, end - self.chunk_overlap)
        return chunks

    def _build_index(self, chunks: list[str]) -> tuple[list[dict[str, float]], dict[str, float]]:
        documents = [self._tokenize(chunk) for chunk in chunks]
        if not documents:
            return [], {}

        df: Counter[str] = Counter()
        for doc in documents:
            for token in set(doc):
                df[token] += 1

        total_docs = len(documents)
        idf = {token: math.log((total_docs + 1) / (freq + 1)) + 1 for token, freq in df.items()}

        vectors: list[dict[str, float]] = []
        for doc in documents:
            counts = Counter(doc)
            denom = sum(counts.values()) or 1
            vector = {
                token: (count / denom) * idf.get(token, 1.0) for token, count in counts.items()
            }
            vectors.append(vector)

        return vectors, idf

    def _retrieve_relevant_evidence_refs(
        self,
        *,
        sentence: str,
        chunks: list[str],
        chunk_vectors: list[dict[str, float]],
        idf: dict[str, float],
    ) -> list[dict[str, Any]]:
        if not chunks or not chunk_vectors:
            return []

        query_tokens = self._tokenize(sentence)
        if not query_tokens:
            return []

        counts = Counter(query_tokens)
        denom = sum(counts.values()) or 1
        query_vector = {
            token: (count / denom) * idf.get(token, 1.0) for token, count in counts.items()
        }

        scores: list[tuple[float, int]] = []
        for index, vector in enumerate(chunk_vectors):
            score = self._cosine_similarity(query_vector, vector)
            if score > 0:
                scores.append((score, index))

        scores.sort(key=lambda item: item[0], reverse=True)
        evidence_refs: list[dict[str, Any]] = []
        for score, index in scores[: self.max_passages]:
            evidence_refs.append(
                {
                    "source_type": "scraped_content",
                    "source_key": f"chunk-{index + 1}",
                    "excerpt": chunks[index],
                    "retrieval_score": round(score, 4),
                }
            )
        return evidence_refs

    # ── Dense (embedding) evidence retrieval & grounding ──────────────

    def _retrieve_evidence_dense(
        self,
        *,
        sentence: str,
        chunks: list[str],
        embedding_cache: EmbeddingCache,
    ) -> list[dict[str, Any]]:
        """Retrieve top-k evidence passages using dense embedding similarity."""
        from services.embedding_service import dense_cosine_similarity

        sentence_vec = embedding_cache.get(sentence)
        if sentence_vec is None:
            return []

        scores: list[tuple[float, int]] = []
        for idx, chunk in enumerate(chunks):
            chunk_vec = embedding_cache.get(chunk)
            if chunk_vec is None:
                continue
            sim = dense_cosine_similarity(sentence_vec, chunk_vec)
            if sim > 0:
                scores.append((sim, idx))

        scores.sort(key=lambda x: x[0], reverse=True)
        evidence_refs: list[dict[str, Any]] = []
        for sim, idx in scores[: self.max_passages]:
            evidence_refs.append(
                {
                    "source_type": "scraped_content",
                    "source_key": f"chunk-{idx + 1}",
                    "excerpt": chunks[idx],
                    "retrieval_score": round(sim, 4),
                    "retrieval_method": "embedding",
                }
            )
        return evidence_refs

    def _classify_grounded_dense(
        self,
        sentence: str,
        evidence_refs: list[dict[str, Any]],
        embedding_cache: EmbeddingCache,
    ) -> tuple[bool, float, float, str]:
        """Classify grounding using dense embedding cosine similarity.

        Returns (grounded, certainty, raw_similarity, reason).

        Unlike TF-IDF, embedding cosine similarity already occupies a
        meaningful 0-1 range, so no sigmoid rescaling is applied.
        """
        from services.embedding_service import dense_cosine_similarity

        if not evidence_refs:
            return False, 0.0, 0.0, "No relevant supporting passage found in crawled content."

        sentence_vec = embedding_cache.get(sentence)
        if sentence_vec is None:
            return False, 0.0, 0.0, "No embedding vector for claim (fallback expected)."

        best_sim = 0.0
        for ref in evidence_refs:
            excerpt = str(ref.get("excerpt") or "")
            passage_vec = embedding_cache.get(excerpt)
            if passage_vec is None:
                continue
            sim = dense_cosine_similarity(sentence_vec, passage_vec)
            best_sim = max(best_sim, sim)

        grounded = best_sim >= self.embedding_grounding_threshold
        reason = (
            "Claim meets the embedding grounding threshold against retrieved evidence."
            if grounded
            else "Claim did not meet the embedding similarity threshold against retrieved evidence."
        )
        return grounded, best_sim, best_sim, reason

    # ── TF-IDF grounding (original path) ─────────────────────────────

    def _classify_grounded(
        self, sentence: str, evidence_refs: list[dict[str, Any]]
    ) -> tuple[bool, float, float, str]:
        """Return (grounded, rescaled_certainty, raw_certainty, reason)."""
        if not evidence_refs:
            return False, 0.0, 0.0, "No relevant supporting passage found in crawled content."

        sentence_tokens = set(self._tokenize(sentence))
        if not sentence_tokens:
            return False, 0.0, 0.0, "Sentence has insufficient lexical signal for grounding."

        best_overlap = 0.0
        best_retrieval = 0.0
        best_bidirectional = 0.0
        for evidence_ref in evidence_refs:
            excerpt = str(evidence_ref.get("excerpt") or "")
            passage_tokens = set(self._tokenize(excerpt))
            if not passage_tokens:
                continue
            intersection = sentence_tokens & passage_tokens
            claim_recall = len(intersection) / len(sentence_tokens)
            passage_precision = len(intersection) / len(passage_tokens) if passage_tokens else 0.0
            overlap_ratio = claim_recall
            bidirectional = (
                (2 * claim_recall * passage_precision) / (claim_recall + passage_precision)
                if (claim_recall + passage_precision) > 0
                else 0.0
            )
            best_overlap = max(best_overlap, overlap_ratio)
            best_bidirectional = max(best_bidirectional, bidirectional)
            best_retrieval = max(best_retrieval, float(evidence_ref.get("retrieval_score") or 0.0))

        raw_certainty = max(
            best_overlap,
            min(1.0, (best_overlap * 0.5) + (best_retrieval * 0.3) + (best_bidirectional * 0.2)),
        )
        certainty = self._rescale_certainty(raw_certainty)
        grounded = (
            best_overlap >= self.grounding_threshold and certainty >= self.certainty_threshold
        )
        reason = (
            "Claim meets the grounding threshold against retrieved evidence."
            if grounded
            else "Claim did not meet the certainty threshold against retrieved evidence."
        )
        return grounded, certainty, raw_certainty, reason

    @staticmethod
    def _rescale_certainty(raw: float) -> float:
        """Rescale raw TF-IDF certainty using a sigmoid centered on the
        expected score distribution (mean ~0.10).

        TF-IDF lexical overlap between AI-generated analytical claims and
        raw webpage content is inherently low (0.05-0.25 typical range).
        A logistic curve maps this narrow band into a usable 0-1 range:
          - raw < 0.05  →  ~0.08  (very weak evidence)
          - raw ~ 0.08  →  ~0.30  (below average)
          - raw ~ 0.12  →  ~0.60  (moderate evidence)
          - raw ~ 0.16  →  ~0.82  (strong evidence)
          - raw > 0.20  →  ~0.95  (very strong evidence)
        """
        if raw <= 0:
            return 0.0
        return 1.0 / (1.0 + math.exp(-18.0 * (raw - 0.10)))

    def _tokenize(self, text: str) -> list[str]:
        words = re.findall(r"[a-zA-Z0-9]+", text.lower())
        return [word for word in words if len(word) > 2 and word not in _STOPWORDS]

    def _cosine_similarity(self, left: dict[str, float], right: dict[str, float]) -> float:
        if not left or not right:
            return 0.0

        dot = 0.0
        for token, value in left.items():
            dot += value * right.get(token, 0.0)

        left_norm = math.sqrt(sum(value * value for value in left.values()))
        right_norm = math.sqrt(sum(value * value for value in right.values()))
        if left_norm == 0 or right_norm == 0:
            return 0.0

        return dot / (left_norm * right_norm)
