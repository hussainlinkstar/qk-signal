"""Advisor quality metrics + gate — EPIC 13 (re-scoped), increment 2.

Pure, deterministic quality metrics computed over an ``AdvisorPlan`` (the output
of ``advisor_service.build_advisor_plan``). These let the eval harness gate the
Advisor's quality before any LLM ``strategic_summary`` is added (increment 3), so
"more expert" stays *provable*, not vibes. No engine/LLM/DB coupling.

Metrics (all in [0,1]; empty plan => 1.0, vacuously passing):
  - advice_grounding_rate   : actions that trace to a finding/claim (must stay ~1.0)
  - actionability_rate      : actions with a concrete (non-generic) action statement
  - non_duplication_rate    : distinct actions (no repeated advice)
  - prioritization_sanity   : valid impact/effort labels + contiguous 1..n ranks
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_VALID_IMPACT = {"high", "medium", "low"}
_VALID_EFFORT = {"low", "medium", "high"}
_MIN_ACTION_WORDS = 4  # fewer words => generic ("improve seo") rather than actionable
_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class AdvisorThresholds:
    fast_advice_grounding_min: float = 0.80
    smart_advice_grounding_min: float = 0.90
    deep_advice_grounding_min: float = 0.95
    fast_actionability_min: float = 0.70
    smart_actionability_min: float = 0.80
    deep_actionability_min: float = 0.85
    fast_non_duplication_min: float = 0.85
    smart_non_duplication_min: float = 0.92
    deep_non_duplication_min: float = 0.95
    fast_prioritization_min: float = 0.95
    smart_prioritization_min: float = 1.0
    deep_prioritization_min: float = 1.0


DEFAULT_ADVISOR_THRESHOLDS = AdvisorThresholds()


@dataclass
class AdvisorMetrics:
    advice_grounding_rate: float
    actionability_rate: float
    non_duplication_rate: float
    prioritization_sanity: float


@dataclass
class AdvisorGateResult:
    tier: str
    passed: bool
    failures: list[str] = field(default_factory=list)


def _normalize_action(text: str) -> str:
    return _WS.sub(" ", str(text or "").strip().lower())


def _rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator > 0 else 1.0


def compute_advisor_metrics(plan: dict[str, Any] | None) -> AdvisorMetrics:
    actions = list((plan or {}).get("actions") or [])
    total = len(actions)
    if total == 0:
        return AdvisorMetrics(1.0, 1.0, 1.0, 1.0)

    grounded = 0
    actionable = 0
    valid_priority = 0
    normalized_actions: list[str] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        if action.get("grounded_by_findings") or action.get("derived_from"):
            grounded += 1
        normalized = _normalize_action(action.get("action"))
        normalized_actions.append(normalized)
        if len(normalized.split()) >= _MIN_ACTION_WORDS:
            actionable += 1
        impact = str(action.get("impact") or "").strip().lower()
        effort = str(action.get("effort") or "").strip().lower()
        if impact in _VALID_IMPACT and effort in _VALID_EFFORT:
            valid_priority += 1

    distinct = len({a for a in normalized_actions if a})
    non_duplication = _rate(distinct, len(normalized_actions))

    # Prioritization sanity also requires ranks to be the contiguous 1..n sequence.
    ranks = sorted(
        int(a["rank"]) for a in actions if isinstance(a, dict) and isinstance(a.get("rank"), int)
    )
    ranks_ok = ranks == list(range(1, total + 1))
    prioritization = _rate(valid_priority, total) if ranks_ok else 0.0

    return AdvisorMetrics(
        advice_grounding_rate=_rate(grounded, total),
        actionability_rate=_rate(actionable, total),
        non_duplication_rate=non_duplication,
        prioritization_sanity=prioritization,
    )


def _tier_threshold(thresholds: AdvisorThresholds, tier: str, metric: str) -> float:
    key = {"smart": "smart", "deep_judgment": "deep", "deep": "deep"}.get(tier, "fast")
    return float(getattr(thresholds, f"{key}_{metric}_min"))


def gate_advisor(
    metrics: AdvisorMetrics,
    *,
    tier: str = "fast",
    thresholds: AdvisorThresholds = DEFAULT_ADVISOR_THRESHOLDS,
) -> AdvisorGateResult:
    """Pure release gate for advisor metrics (tier-aware), no side effects."""
    checks = (
        ("advice_grounding", metrics.advice_grounding_rate),
        ("actionability", metrics.actionability_rate),
        ("non_duplication", metrics.non_duplication_rate),
        ("prioritization", metrics.prioritization_sanity),
    )
    failures: list[str] = []
    for name, value in checks:
        minimum = _tier_threshold(thresholds, tier, name)
        if value < minimum:
            failures.append(f"{name}_rate {value:.3f} < {minimum}")
    return AdvisorGateResult(tier=tier, passed=not failures, failures=failures)
