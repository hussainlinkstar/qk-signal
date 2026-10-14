"""Grounding gate between AI debate output and final report assembly.

Evaluates each finding against source evidence (via claim_verifications from the
HallucinationService) and excludes poorly-grounded findings from the final report.

Three finding-level dispositions:
  - passed:       Claims are well-grounded (avg certainty >= pass threshold)
  - soft_flagged: Partial grounding (between hard and pass thresholds); annotated
  - hard_flagged: No meaningful grounding (below hard threshold); excluded from report

Insertion point: audit_runner.py, between _record_dual_track_observability()
and AuditAnalysis.parse_obj(ai_analysis_results).
"""

from __future__ import annotations

import copy
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds (rescaled certainty, same scale as HallucinationService output)
# ---------------------------------------------------------------------------
PASS_CERTAINTY_THRESHOLD = 0.40
SOFT_FLAG_CERTAINTY_THRESHOLD = 0.15

# Findings field names that the gate inspects (list_dicts only, not narrative)
_GATED_FINDINGS_FIELDS = frozenset(
    {
        "seo_findings",
        "geo_findings",
        "aeo_findings",
        "findings",
        "neural_intelligence_grid",
    }
)

_FIELD_PATH_RE = re.compile(r"^(\w+)\[(\d+)\]")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class FindingVerdict:
    """Grounding verdict for a single finding (e.g. seo_findings[2])."""

    field_name: str
    index: int
    disposition: str  # "passed" | "soft_flagged" | "hard_flagged"
    avg_certainty: float
    claim_count: int
    supported_count: int
    claim_ids: list[str] = field(default_factory=list)


@dataclass
class GroundingGateResult:
    """Aggregate result of the grounding gate evaluation."""

    total_findings: int = 0
    verified_findings: int = 0
    passed: int = 0
    soft_flagged: int = 0
    hard_flagged: int = 0
    # Findings the gate could not check, because no claim was extracted from
    # them. They are retained in the report, but they are not evidence of
    # anything having been verified and are counted separately from
    # ``passed`` so the summary cannot claim them.
    unverified: int = 0
    excluded_claims: list[str] = field(default_factory=list)
    finding_verdicts: list[dict[str, Any]] = field(default_factory=list)
    filtered_analysis: dict[str, Any] | None = None
    gate_applied: bool = True

    def to_metadata(self) -> dict[str, Any]:
        """Serialize to a dict suitable for report metadata / debate_metadata."""
        return {
            "total_findings": self.total_findings,
            "verified_findings": self.verified_findings,
            "passed": self.passed,
            "soft_flagged": self.soft_flagged,
            "hard_flagged": self.hard_flagged,
            "unverified": self.unverified,
            "excluded_claims": self.excluded_claims,
            "finding_verdicts": self.finding_verdicts,
            "gate_applied": self.gate_applied,
            "summary": self._summary(),
        }

    def _summary(self) -> str:
        """What the gate can honestly claim.

        Two things used to be overstated here. A gate that never ran still
        reported "N of N findings verified against page content", because the
        no-verifications path sets ``passed=total_findings`` to leave the
        analysis untouched. And findings with no extractable claim were added
        to ``passed``, so they were counted as verified without anything
        having been compared to the page. Both made the audit look more
        checked than it was, which is worse than saying nothing.
        """
        if not self.total_findings:
            return "No findings to verify"
        if not self.gate_applied:
            return (
                f"{self.total_findings} findings not verified: "
                "no claims were available to check against page content"
            )
        checked = self.passed + self.soft_flagged
        summary = f"{checked} of {self.total_findings} findings verified against page content"
        if self.unverified:
            summary += f", {self.unverified} not checkable"
        return summary


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class GroundingGateService:
    """Post-debate grounding gate for AI-generated findings.

    Reuses claim verifications from the HallucinationService (already computed
    earlier in the audit pipeline) to classify each finding's grounding level
    and filter the analysis dict before it is parsed into the report model.
    """

    def __init__(
        self,
        *,
        pass_threshold: float = PASS_CERTAINTY_THRESHOLD,
        soft_flag_threshold: float = SOFT_FLAG_CERTAINTY_THRESHOLD,
    ) -> None:
        self.pass_threshold = pass_threshold
        self.soft_flag_threshold = soft_flag_threshold

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def evaluate(
        self,
        *,
        ai_analysis_results: dict[str, Any],
        hallucination_result: dict[str, Any] | None = None,
        source_content: str | None = None,
    ) -> GroundingGateResult:
        """Evaluate findings grounding and return gate result with filtered analysis.

        Parameters
        ----------
        ai_analysis_results:
            The (possibly hallucination-sanitized) AI analysis dict.
        hallucination_result:
            Output of ``HallucinationService.analyze()``, containing
            ``claim_verifications``.  Preferred path, avoids re-computation.
        source_content:
            Raw crawled page text.  Used only as a fallback when
            ``hallucination_result`` is unavailable.
        """
        if not isinstance(ai_analysis_results, dict):
            return GroundingGateResult(gate_applied=False)

        total_findings = self._count_total_findings(ai_analysis_results)

        claim_verifications = self._resolve_claim_verifications(
            hallucination_result=hallucination_result,
            ai_analysis_results=ai_analysis_results,
            source_content=source_content,
        )

        if not claim_verifications:
            # No claims to check, so nothing is filtered and nothing is
            # verified. ``passed`` used to be set to the full finding count
            # here, which is what produced "N of N findings verified against
            # page content" for an audit whose gate never ran.
            return GroundingGateResult(
                total_findings=total_findings,
                verified_findings=0,
                passed=0,
                unverified=total_findings,
                filtered_analysis=ai_analysis_results,
                gate_applied=False,
            )

        finding_claims = self._map_claims_to_findings(claim_verifications)
        verdicts = self._compute_verdicts(finding_claims)
        result = self._apply_gate(ai_analysis_results, verdicts, total_findings)
        return result

    # ------------------------------------------------------------------
    # Claim resolution
    # ------------------------------------------------------------------
    def _resolve_claim_verifications(
        self,
        *,
        hallucination_result: dict[str, Any] | None,
        ai_analysis_results: dict[str, Any],
        source_content: str | None,
    ) -> list[dict[str, Any]]:
        """Extract claim verifications, with optional fresh-analysis fallback."""
        if isinstance(hallucination_result, dict):
            verifications = hallucination_result.get("claim_verifications")
            if isinstance(verifications, list) and verifications:
                return verifications

        if source_content:
            try:
                from services.hallucination_service import HallucinationService

                svc = HallucinationService()
                result = svc.analyze(
                    source_content=source_content,
                    analysis=ai_analysis_results,
                )
                return result.get("claim_verifications", [])
            except Exception:
                logger.warning(
                    "Grounding gate: fallback hallucination analysis failed",
                    exc_info=True,
                )

        return []

    # ------------------------------------------------------------------
    # Mapping claims → findings
    # ------------------------------------------------------------------
    @staticmethod
    def _map_claims_to_findings(
        claim_verifications: list[dict[str, Any]],
    ) -> dict[tuple[str, int], list[dict[str, Any]]]:
        """Group claim verifications by (field_name, item_index)."""
        mapping: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)

        for claim in claim_verifications:
            if not isinstance(claim, dict):
                continue
            field_path = claim.get("field_path") or ""
            match = _FIELD_PATH_RE.match(field_path)
            if not match:
                continue
            field_name = match.group(1)
            if field_name not in _GATED_FINDINGS_FIELDS:
                continue
            index = int(match.group(2))
            mapping[(field_name, index)].append(claim)

        return dict(mapping)

    # ------------------------------------------------------------------
    # Per-finding verdicts
    # ------------------------------------------------------------------
    def _compute_verdicts(
        self,
        finding_claims: dict[tuple[str, int], list[dict[str, Any]]],
    ) -> list[FindingVerdict]:
        """Compute grounding verdict for each finding based on its claims."""
        verdicts: list[FindingVerdict] = []

        for (field_name, index), claims in sorted(finding_claims.items()):
            certainties: list[float] = []
            supported = 0
            claim_ids: list[str] = []

            for claim in claims:
                certainty = float(claim.get("certainty_score") or 0.0)
                certainties.append(certainty)
                if claim.get("disposition") == "supported":
                    supported += 1
                claim_ids.append(str(claim.get("claim_id") or ""))

            avg_certainty = sum(certainties) / len(certainties) if certainties else 0.0

            if avg_certainty >= self.pass_threshold:
                disposition = "passed"
            elif avg_certainty >= self.soft_flag_threshold:
                disposition = "soft_flagged"
            else:
                disposition = "hard_flagged"

            verdicts.append(
                FindingVerdict(
                    field_name=field_name,
                    index=index,
                    disposition=disposition,
                    avg_certainty=avg_certainty,
                    claim_count=len(claims),
                    supported_count=supported,
                    claim_ids=claim_ids,
                )
            )

        return verdicts

    # ------------------------------------------------------------------
    # Apply gate to analysis dict
    # ------------------------------------------------------------------
    def _apply_gate(
        self,
        ai_analysis_results: dict[str, Any],
        verdicts: list[FindingVerdict],
        total_findings: int,
    ) -> GroundingGateResult:
        """Filter and annotate findings based on verdicts."""
        filtered = copy.deepcopy(ai_analysis_results)

        passed = 0
        soft_flagged = 0
        hard_flagged = 0
        excluded_claims: list[str] = []
        finding_verdict_dicts: list[dict[str, Any]] = []

        hard_flagged_indices: dict[str, set[int]] = defaultdict(set)
        soft_flagged_indices: dict[str, set[int]] = defaultdict(set)
        passed_indices: dict[str, set[int]] = defaultdict(set)

        for verdict in verdicts:
            verdict_dict = {
                "field": verdict.field_name,
                "index": verdict.index,
                "disposition": verdict.disposition,
                "avg_certainty": round(verdict.avg_certainty, 4),
                "claim_count": verdict.claim_count,
                "supported_count": verdict.supported_count,
            }
            finding_verdict_dicts.append(verdict_dict)

            if verdict.disposition == "passed":
                passed += 1
                passed_indices[verdict.field_name].add(verdict.index)
            elif verdict.disposition == "soft_flagged":
                soft_flagged += 1
                soft_flagged_indices[verdict.field_name].add(verdict.index)
            elif verdict.disposition == "hard_flagged":
                hard_flagged += 1
                hard_flagged_indices[verdict.field_name].add(verdict.index)
                excluded_claims.extend(verdict.claim_ids)

        verified_count = passed + soft_flagged + hard_flagged
        # Findings with no extractable claim are kept in the report - there is
        # nothing to object to - but they were also added to ``passed``, which
        # is what let the summary report them as verified against the page.
        # Nothing was compared, so they are counted on their own.
        unverified = max(0, total_findings - verified_count)

        # Annotate passed findings with grounding_confidence: "verified"
        for field_name, indices in passed_indices.items():
            findings_list = filtered.get(field_name)
            if not isinstance(findings_list, list):
                continue
            for i in indices:
                if i < len(findings_list) and isinstance(findings_list[i], dict):
                    findings_list[i]["grounding_confidence"] = "verified"

        # Annotate soft-flagged findings BEFORE removing hard-flagged
        for field_name, indices in soft_flagged_indices.items():
            findings_list = filtered.get(field_name)
            if not isinstance(findings_list, list):
                continue
            for i in indices:
                if i < len(findings_list) and isinstance(findings_list[i], dict):
                    findings_list[i]["grounding_confidence"] = "low"

        # Remove hard-flagged findings
        for field_name, indices in hard_flagged_indices.items():
            findings_list = filtered.get(field_name)
            if not isinstance(findings_list, list):
                continue
            filtered[field_name] = [
                item for i, item in enumerate(findings_list) if i not in indices
            ]

        return GroundingGateResult(
            total_findings=total_findings,
            verified_findings=verified_count,
            passed=passed,
            soft_flagged=soft_flagged,
            hard_flagged=hard_flagged,
            unverified=unverified,
            excluded_claims=excluded_claims,
            finding_verdicts=finding_verdict_dicts,
            filtered_analysis=filtered,
            gate_applied=True,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _count_total_findings(ai_analysis_results: dict[str, Any]) -> int:
        """Count total findings across all gated fields."""
        total = 0
        for field_name in _GATED_FINDINGS_FIELDS:
            value = ai_analysis_results.get(field_name)
            if isinstance(value, list):
                total += len(value)
        return total
