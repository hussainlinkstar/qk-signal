"""Agent/audit eval harness (EPIC 11 / S11.4, ties S8.5).

Composes the engine's **deterministic** integrity services into a single
release-gating harness that needs **no API keys** (CI-safe):

  - ``HallucinationService.analyze``      (sparse / no embedding_cache) → hallucination rate
  - ``GroundingGateService.evaluate``     → grounding rate
  - ``ClaimEvaluationService.evaluate_shadow`` → claim disposition accuracy

The harness has two layers:
  1. **Pure metrics + threshold gating** (``EvalThresholds``/``EvalMetrics``/``gate``) —
     no engine coupling, trivially unit-testable; this is the part that gates releases.
  2. **Composition** (``run_eval_harness``) — runs the real deterministic services over a
     small corpus and reduces their output into ``EvalMetrics``.

Thresholds (from S11.4 AC): fast grounding ≥ 0.75, smart grounding ≥ 0.85,
hallucination ≤ 0.15.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.claim_evaluation_service import ClaimEvaluationService
from services.grounding_gate_service import GroundingGateService
from services.hallucination_service import HallucinationService


@dataclass(frozen=True)
class EvalThresholds:
    fast_grounding_min: float = 0.75
    smart_grounding_min: float = 0.85
    hallucination_max: float = 0.15
    claim_accuracy_min: float = 0.75


DEFAULT_THRESHOLDS = EvalThresholds()


@dataclass
class EvalMetrics:
    """Measured rates, or ``None`` where there was nothing to measure.

    ``None`` is not a passing value. An empty corpus, or a run the engine
    produced no findings for, used to report a perfect 1.0 and sail through
    the gate: the harness announced its best possible result precisely when
    it had checked nothing. A release gate that cannot fail on absent
    evidence is not a gate.
    """

    grounding_rate: float | None
    hallucination_rate: float | None
    claim_accuracy: float | None
    # How the grounding rate was reached, so a thin corpus is visible rather
    # than hidden behind a ratio.
    total_findings: int = 0
    passed_findings: int = 0
    soft_flagged_findings: int = 0


@dataclass
class GateResult:
    tier: str
    passed: bool
    failures: list[str] = field(default_factory=list)


def gate(
    metrics: EvalMetrics,
    *,
    tier: str = "fast",
    thresholds: EvalThresholds = DEFAULT_THRESHOLDS,
) -> GateResult:
    """Pure release gate: compare metrics to tier thresholds (no side effects)."""
    grounding_min = (
        thresholds.smart_grounding_min if tier == "smart" else thresholds.fast_grounding_min
    )
    failures: list[str] = []
    # An unmeasured metric fails. It is the difference between "the engine is
    # grounded" and "the harness looked at nothing", and only one of those is
    # a reason to release.
    if metrics.grounding_rate is None:
        failures.append("grounding_rate not measured: the corpus produced no findings")
    elif metrics.grounding_rate < grounding_min:
        failures.append(f"grounding_rate {metrics.grounding_rate:.3f} < {grounding_min}")
    if metrics.hallucination_rate is None:
        failures.append("hallucination_rate not measured: no item was analysed")
    elif metrics.hallucination_rate > thresholds.hallucination_max:
        failures.append(
            f"hallucination_rate {metrics.hallucination_rate:.3f} > {thresholds.hallucination_max}"
        )
    if metrics.claim_accuracy is None:
        failures.append("claim_accuracy not measured: no claim was extracted")
    elif metrics.claim_accuracy < thresholds.claim_accuracy_min:
        failures.append(
            f"claim_accuracy {metrics.claim_accuracy:.3f} < {thresholds.claim_accuracy_min}"
        )
    return GateResult(tier=tier, passed=not failures, failures=failures)


@dataclass
class EvalCorpusItem:
    """One corpus entry: an AI analysis dict + the source it must be grounded in."""

    analysis: dict[str, Any]
    evidence: str
    truth_context: dict[str, Any] | None = None


def _safe_rate(numerator: int, denominator: int) -> float | None:
    """The rate, or ``None`` when the denominator is zero.

    Previously this returned a caller-supplied ``empty`` default of 1.0, so
    "nothing to measure" and "everything perfect" were the same number.
    """
    return (numerator / denominator) if denominator > 0 else None


def run_eval_harness(
    corpus: list[EvalCorpusItem],
    *,
    tier: str = "fast",
    thresholds: EvalThresholds = DEFAULT_THRESHOLDS,
) -> tuple[EvalMetrics, GateResult, list[dict[str, Any]]]:
    """Run the deterministic services over the corpus and gate the aggregate metrics.

    Returns ``(metrics, gate_result, per_item_details)``. No network / no keys.
    """
    hallucination_svc = HallucinationService()
    grounding_svc = GroundingGateService()
    claim_svc = ClaimEvaluationService()

    total_findings = 0
    grounded_findings = 0
    soft_flagged_findings = 0
    hallucination_scores: list[float] = []
    claim_total = 0
    claim_supported = 0
    details: list[dict[str, Any]] = []

    for item in corpus:
        hallucination_result = hallucination_svc.analyze(
            source_content=item.evidence,
            analysis=item.analysis,
            brand_truth_payload=None,
            embedding_cache=None,  # sparse mode → deterministic
        )
        # hallucination score is 0-100 ("how grounded"); rate = 1 - score/100.
        score = float(hallucination_result.get("score", 100))
        hallucination_scores.append(max(0.0, min(1.0, 1.0 - score / 100.0)))

        gate_result = grounding_svc.evaluate(
            ai_analysis_results=item.analysis,
            hallucination_result=hallucination_result,
            source_content=item.evidence,
        )
        total_findings += int(gate_result.total_findings)
        # Only findings the gate actually passed count as grounded.
        # ``soft_flagged`` is the gate's own "below the pass threshold, kept
        # with a warning" disposition, so counting it here inflated the rate
        # with exactly the findings the gate was unsure about. It is reported
        # separately instead.
        grounded_findings += int(gate_result.passed)
        soft_flagged_findings += int(gate_result.soft_flagged)

        claim_result = claim_svc.evaluate_shadow(
            claim_verifications=hallucination_result.get("claim_verifications", []),
            unified_truth_context=item.truth_context,
        )
        claims = (claim_result or {}).get("claims", []) if claim_result else []
        claim_total += len(claims)
        claim_supported += sum(1 for c in claims if c.get("shadow_disposition") == "supported")

        details.append(
            {
                "hallucination_score": score,
                "total_findings": gate_result.total_findings,
                "passed": gate_result.passed,
                "soft_flagged": gate_result.soft_flagged,
                "hard_flagged": gate_result.hard_flagged,
                "claims": len(claims),
            }
        )

    metrics = EvalMetrics(
        grounding_rate=_safe_rate(grounded_findings, total_findings),
        hallucination_rate=(
            sum(hallucination_scores) / len(hallucination_scores) if hallucination_scores else None
        ),
        claim_accuracy=_safe_rate(claim_supported, claim_total),
        total_findings=total_findings,
        passed_findings=grounded_findings,
        soft_flagged_findings=soft_flagged_findings,
    )
    return metrics, gate(metrics, tier=tier, thresholds=thresholds), details
