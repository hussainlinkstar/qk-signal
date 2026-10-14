from __future__ import annotations

import re
from typing import Any

from services.debate_orchestrator import (
    CONSOLIDATION_BYPASSED,
    CONSOLIDATION_DEGRADED,
    CONSOLIDATION_FULL,
)


QUALITY_GATE_SCHEMA_VERSION = "orchestra-v3-qg-1"

_GENERATOR_GROUNDING_RATE_MIN = 0.85
_GENERATOR_DOMAIN_BOUNDARY_VIOLATIONS_MAX = 0
_GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX = 0.10
_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MAX = 0.25
_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MIN = 0.03
_UNDER_FLAGGING_MIN_TOTAL_CLAIMS = 5

# Threshold tightening when consolidation is degraded/bypassed (AEX-14)
_DEGRADED_GROUNDING_RATE_BUMP = 0.10
_DEGRADED_CONTRADICTION_RATE_REDUCTION = 0.03

_ANCHOR_NUMERIC_PATTERNS: dict[str, re.Pattern[str]] = {
    "domain_authority": re.compile(r"domain authority[^0-9]{0,12}(\d+(?:\.\d+)?)", re.IGNORECASE),
    "pages_crawled": re.compile(r"pages? crawled[^0-9]{0,12}(\d+(?:\.\d+)?)", re.IGNORECASE),
    "backlinks_count": re.compile(r"backlinks?[^0-9]{0,12}(\d+(?:\.\d+)?)", re.IGNORECASE),
    "indexed_pages": re.compile(r"indexed pages?[^0-9]{0,12}(\d+(?:\.\d+)?)", re.IGNORECASE),
}
_POSITIVE_SCHEMA_MARKERS = (
    "present",
    "detected",
    "found",
    "implemented",
    "exists",
    "available",
    "configured",
)
_SCHEMA_TYPE_HINTS = (
    "faqpage",
    "organization",
    "product",
    "article",
    "howto",
    "localbusiness",
    "breadcrumblist",
    "webpage",
)
_ROLE_DOMAIN_RULES: dict[str, set[str]] = {
    "seo_generator": {"seo"},
    "geo_generator": {"geo"},
    "aeo_generator": {"aeo"},
    "aeo_geo_generator": {"aeo", "geo"},
}


def _normalize_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _round_to_payload(round_item: Any) -> dict[str, Any]:
    if isinstance(round_item, dict):
        payload = dict(round_item)
    else:
        payload = {
            "role": getattr(round_item, "role", None),
            "semantic_role": getattr(round_item, "semantic_role", None),
            "layer": getattr(round_item, "layer_index", None),
            "output": getattr(round_item, "output", None),
        }
    payload["role"] = str(payload.get("role") or "").strip()
    payload["semantic_role"] = str(payload.get("semantic_role") or "").strip()
    payload["output"] = _as_dict(payload.get("output"))
    payload["layer"] = _safe_int(payload.get("layer"))
    return payload


def _extract_claim_ledger(output: dict[str, Any]) -> list[dict[str, Any]]:
    claims = output.get("claim_ledger")
    if not isinstance(claims, list):
        return []
    return [row for row in claims if isinstance(row, dict)]


def _extract_consolidated_dispositions(output: dict[str, Any]) -> list[dict[str, Any]]:
    claims = output.get("consolidated_claim_disposition")
    if not isinstance(claims, list):
        return []
    return [row for row in claims if isinstance(row, dict)]


def _allowed_domains_for_role(role: str) -> set[str] | None:
    normalized_role = str(role or "").strip().lower()
    return _ROLE_DOMAIN_RULES.get(normalized_role)


class PromptQualityGate:
    THRESHOLDS = {
        "generator_grounding_rate_min": _GENERATOR_GROUNDING_RATE_MIN,
        "generator_domain_boundary_violations_max": _GENERATOR_DOMAIN_BOUNDARY_VIOLATIONS_MAX,
        "generator_anchor_contradiction_rate_max": _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX,
        "magistrate_needs_manual_review_rate_max": _MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MAX,
        "magistrate_needs_manual_review_rate_min": _MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MIN,
    }

    def evaluate(
        self,
        *,
        rounds: list[Any],
        evidence_anchor: dict[str, Any] | None,
        requested_tier: str,
        pipeline_type: str | None,
        judge_summary: dict[str, Any] | None = None,
        consolidation_status: str = CONSOLIDATION_FULL,
    ) -> dict[str, Any]:
        normalized_rounds = [_round_to_payload(item) for item in rounds]
        anchor = evidence_anchor if isinstance(evidence_anchor, dict) else {}

        # Tighten thresholds when consolidation is degraded/bypassed (AEX-14)
        is_degraded = consolidation_status in (CONSOLIDATION_BYPASSED, CONSOLIDATION_DEGRADED)
        effective_grounding_min = (
            min(1.0, _GENERATOR_GROUNDING_RATE_MIN + _DEGRADED_GROUNDING_RATE_BUMP)
            if is_degraded
            else _GENERATOR_GROUNDING_RATE_MIN
        )
        effective_contradiction_max = (
            max(
                0.0,
                _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX - _DEGRADED_CONTRADICTION_RATE_REDUCTION,
            )
            if is_degraded
            else _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX
        )

        violations: list[dict[str, Any]] = []
        agent_checks: list[dict[str, Any]] = []
        total_generator_claims = 0
        manual_review_count: int | None = None
        total_disposition_claims: int | None = None

        for round_payload in normalized_rounds:
            role = round_payload["role"]
            semantic_role = round_payload["semantic_role"]
            output = round_payload["output"]

            if (
                semantic_role == "generator"
                or role.endswith("_generator")
                or role in {"fast_proposer"}
            ):
                generator_check = self._check_generator_output(
                    role=role,
                    layer=round_payload["layer"],
                    output=output,
                    evidence_anchor=anchor,
                    grounding_rate_min=effective_grounding_min,
                    contradiction_rate_max=effective_contradiction_max,
                )
                agent_checks.append(generator_check)
                violations.extend(generator_check["violations"])
                total_generator_claims += int(generator_check["claim_count"])
                continue

            if role == "consolidator":
                consolidator_check = self._check_consolidator_output(
                    role=role,
                    layer=round_payload["layer"],
                    output=output,
                )
                agent_checks.append(consolidator_check)
                violations.extend(consolidator_check["violations"])
                if consolidator_check["total_claims"] > 0:
                    total_disposition_claims = int(consolidator_check["total_claims"])
                    manual_review_count = int(consolidator_check["manual_review_count"])

        if total_disposition_claims in (None, 0):
            fallback_total_claims, fallback_manual_review_count = (
                self._resolve_manual_review_counts_from_judge_summary(
                    judge_summary=judge_summary,
                )
            )
            if fallback_total_claims > 0:
                total_disposition_claims = fallback_total_claims
                manual_review_count = fallback_manual_review_count

        magistrate_check = self._check_magistrate_output(
            total_claims=total_disposition_claims or total_generator_claims,
            manual_review_count=manual_review_count or 0,
        )
        agent_checks.append(magistrate_check)
        violations.extend(magistrate_check["violations"])

        passed = len(violations) == 0
        return {
            "schema_version": QUALITY_GATE_SCHEMA_VERSION,
            "requested_tier": str(requested_tier or "").strip() or "unknown",
            "pipeline_type": str(pipeline_type or "").strip() or "unknown",
            "consolidation_status": consolidation_status,
            "passed": passed,
            "thresholds": dict(self.THRESHOLDS),
            "effective_thresholds": {
                "grounding_rate_min": round(effective_grounding_min, 4),
                "contradiction_rate_max": round(effective_contradiction_max, 4),
            },
            "total_claims_evaluated": max(total_disposition_claims or 0, total_generator_claims),
            "violation_count": len(violations),
            "violations": violations,
            "agent_checks": agent_checks,
        }

    def _check_generator_output(
        self,
        *,
        role: str,
        layer: int | None,
        output: dict[str, Any],
        evidence_anchor: dict[str, Any],
        grounding_rate_min: float = _GENERATOR_GROUNDING_RATE_MIN,
        contradiction_rate_max: float = _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX,
    ) -> dict[str, Any]:
        claims = _extract_claim_ledger(output)
        allowed_domains = _allowed_domains_for_role(role)
        domain_boundary_violations = 0
        missing_grounding = 0
        anchor_contradictions = 0

        for claim in claims:
            domain = str(claim.get("domain") or "").strip().lower()
            if allowed_domains and domain not in allowed_domains:
                domain_boundary_violations += 1

            evidence_refs = claim.get("evidence_refs")
            if not isinstance(evidence_refs, list) or not any(
                _normalize_text(item) for item in evidence_refs
            ):
                missing_grounding += 1

            if self._claim_contradicts_anchor(claim=claim, evidence_anchor=evidence_anchor):
                anchor_contradictions += 1

        claim_count = len(claims)
        grounding_rate = 1.0 if claim_count == 0 else 1.0 - (missing_grounding / claim_count)
        contradiction_rate = 0.0 if claim_count == 0 else (anchor_contradictions / claim_count)

        violations: list[dict[str, Any]] = []

        if claim_count == 0:
            violations.append(
                self._build_violation(
                    code="generator_claim_collapse",
                    severity="error",
                    message=f"{role} produced zero claims, possible generator collapse.",
                    agent_role=role,
                    layer=layer,
                    observed=0,
                    threshold=1,
                )
            )

        if domain_boundary_violations > _GENERATOR_DOMAIN_BOUNDARY_VIOLATIONS_MAX:
            violations.append(
                self._build_violation(
                    code="generator_domain_boundary_violation",
                    severity="error",
                    message=(
                        f"{role} emitted {domain_boundary_violations} cross-domain claim(s), exceeding the strict "
                        "boundary limit."
                    ),
                    agent_role=role,
                    layer=layer,
                    observed=domain_boundary_violations,
                    threshold=_GENERATOR_DOMAIN_BOUNDARY_VIOLATIONS_MAX,
                )
            )

        if claim_count > 0 and grounding_rate < grounding_rate_min:
            violations.append(
                self._build_violation(
                    code="generator_grounding_rate_low",
                    severity="warning",
                    message=(
                        f"{role} grounded {grounding_rate:.0%} of claims with evidence refs "
                        f"(minimum {grounding_rate_min:.0%})."
                    ),
                    agent_role=role,
                    layer=layer,
                    observed=round(grounding_rate, 4),
                    threshold=grounding_rate_min,
                )
            )

        if claim_count > 0 and contradiction_rate > contradiction_rate_max:
            violations.append(
                self._build_violation(
                    code="generator_anchor_contradiction_rate_high",
                    severity="warning",
                    message=(
                        f"{role} contradicted anchor metrics in {contradiction_rate:.0%} of claims "
                        f"(max {contradiction_rate_max:.0%})."
                    ),
                    agent_role=role,
                    layer=layer,
                    observed=round(contradiction_rate, 4),
                    threshold=contradiction_rate_max,
                )
            )

        return {
            "agent_role": role,
            "layer": layer,
            "check_type": "generator",
            "passed": len(violations) == 0,
            "claim_count": claim_count,
            "metrics": {
                "grounding_rate": round(grounding_rate, 4),
                "domain_boundary_violations": domain_boundary_violations,
                "anchor_contradictions": anchor_contradictions,
            },
            "violation_codes": [item["code"] for item in violations],
            "violations": violations,
        }

    def _check_consolidator_output(
        self,
        *,
        role: str,
        layer: int | None,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        dispositions = _extract_consolidated_dispositions(output)
        claim_ids = [
            str(item.get("claim_id") or "").strip()
            for item in dispositions
            if _normalize_text(item.get("claim_id"))
        ]
        unique_claim_ids = {claim_id for claim_id in claim_ids if claim_id}
        duplicate_claim_ids = max(0, len(claim_ids) - len(unique_claim_ids))
        dedup_count = max(0, _safe_int(output.get("dedup_count")) or 0)
        manual_review_count = sum(
            1
            for item in dispositions
            if str(item.get("disposition") or "").strip().lower() == "needs_manual_review"
        )

        violations: list[dict[str, Any]] = []
        if duplicate_claim_ids > 0:
            violations.append(
                self._build_violation(
                    code="consolidator_duplicate_claim_ids",
                    severity="warning",
                    message=f"{role} returned duplicate consolidated claim IDs after deduplication.",
                    agent_role=role,
                    layer=layer,
                    observed=duplicate_claim_ids,
                    threshold=0,
                )
            )
        if dispositions and dedup_count > len(dispositions):
            violations.append(
                self._build_violation(
                    code="consolidator_invalid_dedup_count",
                    severity="warning",
                    message=f"{role} reported dedup_count greater than the surviving consolidated claims.",
                    agent_role=role,
                    layer=layer,
                    observed=dedup_count,
                    threshold=len(dispositions),
                )
            )

        return {
            "agent_role": role,
            "layer": layer,
            "check_type": "consolidator",
            "passed": len(violations) == 0,
            "claim_count": len(dispositions),
            "total_claims": len(dispositions),
            "manual_review_count": manual_review_count,
            "metrics": {
                "dedup_count": dedup_count,
                "duplicate_claim_ids": duplicate_claim_ids,
            },
            "violation_codes": [item["code"] for item in violations],
            "violations": violations,
        }

    def _check_magistrate_output(
        self,
        *,
        total_claims: int,
        manual_review_count: int,
    ) -> dict[str, Any]:
        total_claims = max(0, int(total_claims or 0))
        manual_review_count = max(0, int(manual_review_count or 0))
        manual_review_rate = 0.0 if total_claims == 0 else manual_review_count / total_claims
        violations: list[dict[str, Any]] = []

        if total_claims > 0 and manual_review_rate > _MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MAX:
            violations.append(
                self._build_violation(
                    code="magistrate_over_flagging",
                    severity="warning",
                    message=(
                        f"Manual review rate reached {manual_review_rate:.0%}, above the expected "
                        f"{_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MAX:.0%} ceiling."
                    ),
                    agent_role="global_magistrate",
                    layer=None,
                    observed=round(manual_review_rate, 4),
                    threshold=_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MAX,
                )
            )

        if (
            total_claims > _UNDER_FLAGGING_MIN_TOTAL_CLAIMS
            and manual_review_rate < _MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MIN
        ):
            violations.append(
                self._build_violation(
                    code="magistrate_under_flagging",
                    severity="warning",
                    message=(
                        f"Manual review rate fell to {manual_review_rate:.0%}, below the expected "
                        f"{_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MIN:.0%} floor."
                    ),
                    agent_role="global_magistrate",
                    layer=None,
                    observed=round(manual_review_rate, 4),
                    threshold=_MAGISTRATE_NEEDS_MANUAL_REVIEW_RATE_MIN,
                )
            )

        return {
            "agent_role": "global_magistrate",
            "layer": None,
            "check_type": "magistrate",
            "passed": len(violations) == 0,
            "claim_count": total_claims,
            "metrics": {
                "manual_review_count": manual_review_count,
                "manual_review_rate": round(manual_review_rate, 4),
            },
            "violation_codes": [item["code"] for item in violations],
            "violations": violations,
        }

    def _resolve_manual_review_counts_from_judge_summary(
        self,
        *,
        judge_summary: dict[str, Any] | None,
    ) -> tuple[int, int]:
        payload = judge_summary if isinstance(judge_summary, dict) else {}
        accepted_claims = max(0, _safe_int(payload.get("accepted_claims")) or 0)
        downgraded_claims = max(0, _safe_int(payload.get("downgraded_claims")) or 0)
        rejected_claims = max(0, _safe_int(payload.get("rejected_claims")) or 0)
        unresolved_disputes = max(0, _safe_int(payload.get("unresolved_disputes")) or 0)
        total_claims = accepted_claims + downgraded_claims + rejected_claims + unresolved_disputes
        return total_claims, unresolved_disputes

    def _claim_contradicts_anchor(
        self,
        *,
        claim: dict[str, Any],
        evidence_anchor: dict[str, Any],
    ) -> bool:
        claim_text = _normalize_text(claim.get("claim_text")).lower()
        if not claim_text:
            return False

        critical_metrics = _as_dict(evidence_anchor.get("critical_metrics"))
        schema_types = {
            str(item).strip().lower()
            for item in critical_metrics.get("schema_types_found", [])
            if _normalize_text(item)
        }
        if "schema" in claim_text and any(
            marker in claim_text for marker in _POSITIVE_SCHEMA_MARKERS
        ):
            for schema_hint in _SCHEMA_TYPE_HINTS:
                if schema_hint in claim_text and schema_hint not in schema_types:
                    return True

        for metric_key, pattern in _ANCHOR_NUMERIC_PATTERNS.items():
            anchor_value = _safe_float(critical_metrics.get(metric_key))
            if anchor_value is None:
                continue
            match = pattern.search(claim_text)
            if match is None:
                continue
            claimed_value = _safe_float(match.group(1))
            if claimed_value is None:
                continue
            tolerance = max(1.0, abs(anchor_value) * 0.15)
            if abs(claimed_value - anchor_value) > tolerance:
                return True

        return False

    @staticmethod
    def _build_violation(
        *,
        code: str,
        severity: str,
        message: str,
        agent_role: str | None,
        layer: int | None,
        observed: Any,
        threshold: Any,
    ) -> dict[str, Any]:
        return {
            "code": code,
            "severity": severity,
            "message": message,
            "agent_role": agent_role,
            "layer": layer,
            "observed": observed,
            "threshold": threshold,
        }


prompt_quality_gate_service = PromptQualityGate()
