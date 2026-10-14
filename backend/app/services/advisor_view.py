"""Deterministic Advisor view derivation (response-time only).

The Advisor plan ("what to fix, in order") is an ROI-ranked, grounding-enforced
roll-up of the audit's already-grounded recommendations. The deterministic
ranking lives in :func:`services.advisor_service.build_advisor_plan`; this module
only sources candidate suggestions from a normalized report and attaches the
resulting plan at ``metadata.advisor``.

Like :mod:`app.services.aio_view`, this is a pure, additive augmentation: it never
persists, never mutates the canonical ``CanonicalAuditAnalysisContract``, performs
no I/O and makes no LLM call (the optional ``generate_strategic_summary`` stays
off). The call is idempotent.
"""

from __future__ import annotations

from typing import Any, Optional

from app.services.learnings_service import is_suppressed
from services.advisor_service import build_advisor_plan

_EFFORT_LABELS = {"low", "medium", "high"}
_IMPACT_LABELS = {"low", "medium", "high"}


def _effort_label(item: dict[str, Any]) -> str | None:
    raw = str(item.get("effort") or item.get("estimated_effort") or "").strip().lower()
    return raw if raw in _EFFORT_LABELS else None


def _impact_label(item: dict[str, Any]) -> str:
    raw = str(item.get("impact") or "").strip().lower()
    if raw in _IMPACT_LABELS:
        return raw

    # Derive an impact label from the canonical ``expected_score_impact`` block
    # (per-dimension score deltas). The largest absolute delta drives the label.
    impact_block = item.get("expected_score_impact")
    if isinstance(impact_block, dict):
        deltas = [
            abs(float(value))
            for value in impact_block.values()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        if deltas:
            top = max(deltas)
            if top >= 10:
                return "high"
            if top >= 4:
                return "medium"
            return "low"
    return "medium"


def _report_suggestions(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect grounded suggestion candidates from a normalized report.

    The canonical report carries the audit's grounded recommendations at
    ``recommendations.items`` (each with ``action``, grounding refs,
    ``estimated_effort`` and ``expected_score_impact``). Legacy/raw shapes may
    instead expose a top-level ``suggestions`` list. Both are normalized into the
    shape ``build_advisor_plan`` expects (``action``/``impact``/``effort`` plus
    ``grounded_by_findings``/``derived_from``).
    """
    recommendations = report.get("recommendations")
    items = recommendations.get("items") if isinstance(recommendations, dict) else None
    if not isinstance(items, list):
        items = report.get("suggestions") if isinstance(report.get("suggestions"), list) else []

    suggestions: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        action = str(item.get("action") or item.get("title") or "").strip()
        if not action:
            continue
        suggestions.append(
            {
                "action": action,
                "title": (str(item.get("title") or "").strip() or None),
                "impact": _impact_label(item),
                "effort": _effort_label(item),
                "grounded_by_findings": item.get("grounded_by_findings") or [],
                "derived_from": item.get("derived_from") or [],
                "problem_code": item.get("problem_code"),
            }
        )
    return suggestions


def attach_advisor_view(
    report: Optional[dict],
    dismissed: Optional[set[str]] = None,
) -> Optional[dict]:
    """Attach the deterministic Advisor plan at ``metadata.advisor`` (response-time).

    Sources grounded suggestions from the report, ranks them deterministically via
    :func:`build_advisor_plan` with ``require_grounding=True`` (ungrounded advice is
    dropped), and stores the plan under ``metadata.advisor``. No LLM call is made
    (``strategic_summary`` stays ``None``). Missing data yields an empty plan
    (``actions: []``). Idempotent and never persisted.

    Learnings loop (Task 7.2): when ``dismissed`` is provided (the set of
    dismissed ``action_fingerprint`` values for the report's project), actions
    covered by one of those keys are suppressed from the plan. A suggestion is
    covered by its deterministic ``problem_code`` key, which survives the LLM
    rewording the action between audits, OR by the legacy digest of its action
    text (SIGV2-1118). When ``dismissed`` is ``None`` or empty the behaviour is
    unchanged (no suppression), keeping the call backward-compatible for callers
    without a resolvable project/db session.
    """
    if not isinstance(report, dict):
        return report

    suggestions = _report_suggestions(report)
    if dismissed:
        suggestions = [
            suggestion
            for suggestion in suggestions
            if not is_suppressed(
                dismissed,
                suggestion.get("action", ""),
                suggestion.get("problem_code"),
            )
        ]
    plan = build_advisor_plan(suggestions, require_grounding=True)

    metadata = dict(report.get("metadata")) if isinstance(report.get("metadata"), dict) else {}
    metadata["advisor"] = plan
    report["metadata"] = metadata
    return report
