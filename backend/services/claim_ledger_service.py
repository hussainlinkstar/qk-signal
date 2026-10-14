from __future__ import annotations

import os
from typing import Any


_DOMAIN_HINTS = {
    "aeo": (
        "aeo",
        "answer",
        "faq",
        "snippet",
        "voice",
        "llm",
        "conversational",
        "generative",
        "ai_search",
        "answerability",
    ),
    "seo": (
        "seo",
        "crawl",
        "index",
        "hreflang",
        "canonical",
        "sitemap",
        "robots",
        "backlink",
        "ranking",
        "title tag",
        "meta desc",
    ),
    "geo": (
        "geo",
        "entity",
        "entities",
        "local",
        "authority",
        "brand",
        "knowledge",
        "map",
        "nap",
        "address",
        "location",
        "citation",
        "review",
        "business profile",
    ),
}


def _severity_confidence() -> dict[str, float]:
    return {
        "critical": _safe_float(os.getenv("CLAIM_LEDGER_SEVERITY_CRITICAL"), 0.92),
        "warning": _safe_float(os.getenv("CLAIM_LEDGER_SEVERITY_WARNING"), 0.78),
        "info": _safe_float(os.getenv("CLAIM_LEDGER_SEVERITY_INFO"), 0.64),
    }


def _priority_recommendation() -> int:
    return _safe_int(os.getenv("CLAIM_LEDGER_PRIORITY_RECOMMENDATION"), 320)


def _priority_finding() -> int:
    return _safe_int(os.getenv("CLAIM_LEDGER_PRIORITY_FINDING"), 280)


def _priority_summary() -> int:
    return _safe_int(os.getenv("CLAIM_LEDGER_PRIORITY_SUMMARY"), 160)


def _priority_aeo_signal() -> int:
    return _safe_int(os.getenv("CLAIM_LEDGER_PRIORITY_AEO_SIGNAL"), 240)


def _summary_confidence_fallback() -> float:
    return _safe_float(os.getenv("CLAIM_LEDGER_SUMMARY_CONFIDENCE_FALLBACK"), 0.72)


def _summary_confidence_min() -> float:
    return _safe_float(os.getenv("CLAIM_LEDGER_SUMMARY_CONFIDENCE_MIN"), 0.45)


_TOP_LEVEL_SCORE_FIELDS = (
    "seo_score",
    "geo_score",
    "aeo_score",
    "citation_probability_score",
)
_COMPACT_SECTION_FIELDS = (
    "technical_signals",
    "geo_signals",
    "aeo_signals",
    "entity_analysis",
)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class ClaimLedgerService:
    def __init__(
        self,
        *,
        max_claims: int | None = None,
        max_text_chars: int | None = None,
        max_refs: int | None = None,
    ) -> None:
        env_max_claims = _safe_int(os.getenv("DEBATE_CLAIM_LEDGER_MAX_ITEMS"), 12)
        self.max_claims = max(3, max_claims if max_claims is not None else env_max_claims)
        env_max_text = _safe_int(os.getenv("CLAIM_LEDGER_MAX_TEXT_CHARS"), 220)
        self.max_text_chars = max(
            80, max_text_chars if max_text_chars is not None else env_max_text
        )
        env_max_refs = _safe_int(os.getenv("CLAIM_LEDGER_MAX_REFS"), 3)
        self.max_refs = max(1, max_refs if max_refs is not None else env_max_refs)

    def build_analysis_transfer_packet(
        self,
        payload: dict[str, Any] | None,
        *,
        expert_domain: str | None = None,
    ) -> dict[str, Any]:
        analysis = payload if isinstance(payload, dict) else {}
        model_claim_ledger = self._normalize_model_claim_ledger(
            analysis.get("claim_ledger"),
            expert_domain=expert_domain,
        )
        claim_ledger = model_claim_ledger or self._extract_claim_ledger(
            analysis,
            expert_domain=expert_domain,
        )
        returned_claims = claim_ledger[: self.max_claims]
        return {
            "summary": self._clean_text(analysis.get("summary"), limit=280),
            "score_snapshot": self._build_score_snapshot(analysis),
            "claim_ledger": returned_claims,
            "claim_ledger_summary": {
                "returned_claims": len(returned_claims),
                "omitted_claims": max(0, len(claim_ledger) - len(returned_claims)),
                "used_model_claim_ledger": bool(model_claim_ledger),
            },
        }

    def build_challenge_transfer_packet(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        challenge_payload = payload if isinstance(payload, dict) else {}
        challenge_ledger = self._extract_challenge_ledger(challenge_payload)
        returned_challenges = challenge_ledger[: self.max_claims]
        return {
            "challenge_ledger": returned_challenges,
            "challenge_summary": {
                "returned_challenges": len(returned_challenges),
                "omitted_challenges": max(0, len(challenge_ledger) - len(returned_challenges)),
                "confidence_delta": round(
                    _safe_float(challenge_payload.get("confidence_delta")), 4
                ),
            },
            "missed_items": self._normalize_string_list(
                challenge_payload.get("missed_items"), limit=6
            ),
            "unresolved_questions": self._normalize_string_list(
                challenge_payload.get("unresolved_questions")
                or challenge_payload.get("disagreements"),
                limit=6,
            ),
        }

    def _normalize_model_claim_ledger(
        self,
        raw_claim_ledger: Any,
        *,
        expert_domain: str | None = None,
    ) -> list[dict[str, Any]]:
        if not isinstance(raw_claim_ledger, list):
            return []

        normalized: list[dict[str, Any]] = []
        for index, item in enumerate(raw_claim_ledger, start=1):
            if not isinstance(item, dict):
                continue
            claim_text = self._clean_text(item.get("claim_text"))
            if not claim_text:
                continue
            domain = self._normalize_domain(
                item.get("domain"),
                fallback=expert_domain or self._infer_domain(claim_text),
            )
            claim_id = self._clean_text(item.get("claim_id"), limit=48) or f"{domain}-{index:02d}"
            normalized.append(
                {
                    "claim_id": claim_id,
                    "domain": domain,
                    "claim_text": claim_text,
                    "confidence": round(_clamp(_safe_float(item.get("confidence"), 0.7)), 4),
                    "evidence_refs": self._normalize_string_list(
                        item.get("evidence_refs"), limit=self.max_refs
                    ),
                    "recommended_action": self._clean_text(item.get("recommended_action")),
                }
            )
        return normalized

    def _extract_claim_ledger(
        self,
        payload: dict[str, Any],
        *,
        expert_domain: str | None = None,
    ) -> list[dict[str, Any]]:
        scored_entries: list[tuple[int, int, dict[str, Any]]] = []
        order = 0

        def add_entry(priority: int, entry: dict[str, Any]) -> None:
            nonlocal order
            scored_entries.append((priority, order, entry))
            order += 1

        summary = self._clean_text(payload.get("summary"), limit=280)
        if summary:
            summary_domain = self._normalize_domain(expert_domain, fallback="cross_domain")
            add_entry(
                _priority_summary(),
                {
                    "claim_id": f"{summary_domain}-summary-01",
                    "domain": summary_domain,
                    "claim_text": summary,
                    "confidence": round(self._resolve_summary_confidence(payload), 4),
                    "evidence_refs": ["summary"],
                    "recommended_action": "",
                },
            )

        for index, recommendation in enumerate(payload.get("recommendations") or [], start=1):
            recommendation_text = self._clean_text(recommendation)
            if not recommendation_text:
                continue
            domain = self._normalize_domain(
                expert_domain or self._infer_domain(recommendation_text),
                fallback="cross_domain",
            )
            add_entry(
                _priority_recommendation() - index,
                {
                    "claim_id": f"{domain}-rec-{index:02d}",
                    "domain": domain,
                    "claim_text": recommendation_text,
                    "confidence": round(self._resolve_summary_confidence(payload), 4),
                    "evidence_refs": [f"recommendations[{index - 1}]"],
                    "recommended_action": recommendation_text,
                },
            )

        for domain, field_name in (
            ("seo", "seo_findings"),
            ("geo", "geo_findings"),
            ("aeo", "aeo_findings"),
        ):
            findings = payload.get(field_name)
            if not isinstance(findings, list):
                continue
            severity_sorted = sorted(
                enumerate(findings, start=1),
                key=lambda pair: self._finding_priority(pair[1]),
                reverse=True,
            )
            for visible_index, (source_index, item) in enumerate(severity_sorted, start=1):
                if not isinstance(item, dict):
                    continue
                description = self._clean_text(item.get("description"))
                if not description:
                    continue
                severity = str(item.get("severity") or "").strip().lower()
                add_entry(
                    _priority_finding() - visible_index,
                    {
                        "claim_id": f"{domain}-finding-{visible_index:02d}",
                        "domain": self._normalize_domain(expert_domain, fallback=domain),
                        "claim_text": description,
                        "confidence": round(self._resolve_finding_confidence(payload, severity), 4),
                        "evidence_refs": [f"{field_name}[{source_index - 1}]"],
                        "recommended_action": self._clean_text(item.get("category")),
                    },
                )

        aeo_signals = payload.get("aeo_signals")
        if isinstance(aeo_signals, dict):
            for index, recommendation in enumerate(
                aeo_signals.get("key_recommendations") or [], start=1
            ):
                recommendation_text = self._clean_text(recommendation)
                if not recommendation_text:
                    continue
                add_entry(
                    _priority_aeo_signal() - index,
                    {
                        "claim_id": f"aeo-signal-{index:02d}",
                        "domain": self._normalize_domain(expert_domain, fallback="aeo"),
                        "claim_text": recommendation_text,
                        "confidence": round(self._resolve_section_confidence(aeo_signals), 4),
                        "evidence_refs": [f"aeo_signals.key_recommendations[{index - 1}]"],
                        "recommended_action": recommendation_text,
                    },
                )

        ordered_entries = [
            entry for _, _, entry in sorted(scored_entries, key=lambda item: (-item[0], item[1]))
        ]
        return ordered_entries[: self.max_claims * 2]

    def _extract_challenge_ledger(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []

        def add_entry(
            *,
            target_claim: Any,
            counter_argument: Any,
            severity: Any,
            issue_type: str,
            suggested_disposition: str,
        ) -> None:
            claim_text = self._clean_text(target_claim)
            counter_text = self._clean_text(counter_argument, limit=260)
            if not claim_text and not counter_text:
                return
            normalized_severity = str(severity or "").strip().lower()
            if normalized_severity not in {"critical", "moderate", "minor"}:
                normalized_severity = "moderate"
            entries.append(
                {
                    "claim_id": f"challenge-{len(entries) + 1:02d}",
                    "target_claim": claim_text or issue_type,
                    "issue_type": issue_type,
                    "severity": normalized_severity,
                    "counter_argument": counter_text,
                    "suggested_disposition": suggested_disposition,
                }
            )

        for field_name in (
            "unsupported_claims",
            "invented_links_or_citations",
            "weak_recommendations",
        ):
            issues = payload.get(field_name)
            if not isinstance(issues, list):
                continue
            for item in issues:
                if not isinstance(item, dict):
                    continue
                add_entry(
                    target_claim=item.get("target_claim"),
                    counter_argument=item.get("counter_argument"),
                    severity=item.get("severity"),
                    issue_type=str(item.get("issue_type") or field_name[:-1]).strip().lower()
                    or "challenge",
                    suggested_disposition=(
                        str(item.get("suggested_disposition") or "").strip().lower() or "review"
                    ),
                )

        challenges = payload.get("challenges")
        if isinstance(challenges, list):
            for item in challenges:
                if not isinstance(item, dict):
                    continue
                add_entry(
                    target_claim=item.get("target_claim"),
                    counter_argument=item.get("counter_argument"),
                    severity=item.get("severity"),
                    issue_type="challenge",
                    suggested_disposition="review",
                )

        return entries

    def _build_score_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot: dict[str, Any] = {}
        for field_name in _TOP_LEVEL_SCORE_FIELDS:
            value = payload.get(field_name)
            if isinstance(value, (int, float)):
                snapshot[field_name] = float(value)

        for field_name in _COMPACT_SECTION_FIELDS:
            section = payload.get(field_name)
            if not isinstance(section, dict):
                continue
            compact_section: dict[str, Any] = {}
            for key, value in section.items():
                if isinstance(value, (int, float, bool)):
                    compact_section[key] = value
                elif isinstance(value, list):
                    compact_values = [
                        self._clean_text(item, limit=48)
                        for item in value
                        if self._clean_text(item, limit=48)
                    ]
                    if compact_values:
                        compact_section[key] = compact_values[:4]
            if compact_section:
                snapshot[field_name] = compact_section
        return snapshot

    def _resolve_summary_confidence(self, payload: dict[str, Any]) -> float:
        numeric_scores = [
            _safe_float(payload.get(field_name)) / 100.0
            for field_name in ("seo_score", "geo_score", "aeo_score")
            if isinstance(payload.get(field_name), (int, float))
        ]
        if numeric_scores:
            return _clamp(
                sum(numeric_scores) / len(numeric_scores), minimum=_summary_confidence_min()
            )
        return _summary_confidence_fallback()

    def _resolve_finding_confidence(self, payload: dict[str, Any], severity: str) -> float:
        severity_conf = _severity_confidence().get(severity, 0.7)
        return max(severity_conf, self._resolve_summary_confidence(payload) - 0.05)

    @staticmethod
    def _resolve_section_confidence(section: dict[str, Any]) -> float:
        numeric_values = [
            float(value) / 100.0 for value in section.values() if isinstance(value, (int, float))
        ]
        if numeric_values:
            return _clamp(sum(numeric_values) / len(numeric_values), minimum=0.5)
        return 0.68

    def _normalize_domain(self, value: Any, *, fallback: str) -> str:
        normalized = str(value or "").strip().lower().replace(" ", "_")
        return normalized or fallback

    def _infer_domain(self, text: str) -> str:
        lowered = text.lower()
        for domain, hints in _DOMAIN_HINTS.items():
            if any(hint in lowered for hint in hints):
                return domain
        return "cross_domain"

    def _finding_priority(self, item: Any) -> int:
        if not isinstance(item, dict):
            return 0
        severity = str(item.get("severity") or "").strip().lower()
        return {"critical": 3, "warning": 2, "info": 1}.get(severity, 0)

    def _normalize_string_list(self, value: Any, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value:
            cleaned = self._clean_text(item, limit=72)
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
            if len(normalized) >= limit:
                break
        return normalized

    def _clean_text(self, value: Any, *, limit: int | None = None) -> str:
        if not isinstance(value, str):
            return ""
        cleaned = " ".join(value.strip().split())
        if not cleaned:
            return ""
        text_limit = limit if limit is not None else self.max_text_chars
        if len(cleaned) <= text_limit:
            return cleaned
        return cleaned[: max(1, text_limit - 3)].rstrip() + "..."


claim_ledger_service = ClaimLedgerService()
