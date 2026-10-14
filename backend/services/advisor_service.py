"""Deterministic Advisor synthesis — EPIC 13 (re-scoped), increment 1.

Reduces the audit's already-grounded recommendations/suggestions into a
prioritized action plan (``AdvisorPlan``). This is **pure + deterministic**:
no LLM, no DB, no network. It only re-orders + annotates suggestions that are
ALREADY grounded in findings/claims, so it cannot hallucinate advice. An optional
LLM ``strategic_summary`` is a separate, gated later increment.

Ranking = ROI (impact / effort) with a tie-break on grounding strength.
Ungrounded suggestions are dropped (advice must trace to a finding/claim).
"""

from __future__ import annotations

import logging
from typing import Any

from problem_codes import normalize_problem_code

logger = logging.getLogger(__name__)

ADVISOR_SCHEMA_VERSION = "advisor-det-1"

_ADVISOR_SUMMARY_SYSTEM = (
    "You are a senior SEO/GEO/AEO consultant writing a 2-3 sentence strategic "
    "summary of an ALREADY-DECIDED, prioritized action plan. Hard rules: only "
    "narrativize the actions you are given (their order is the priority); do NOT "
    "invent new actions, facts, metrics, brands, or recommendations; do NOT cite "
    "anything not in the list. Output plain prose only (no markdown, no lists)."
)

_IMPACT_WEIGHT = {"high": 3, "medium": 2, "low": 1}
_EFFORT_WEIGHT = {"low": 1, "medium": 2, "high": 3}


def _grounding_refs(suggestion: dict[str, Any]) -> tuple[list[str], list[str]]:
    grounded = [str(x) for x in (suggestion.get("grounded_by_findings") or []) if str(x).strip()]
    derived = [str(x) for x in (suggestion.get("derived_from") or []) if str(x).strip()]
    return grounded, derived


def _roi_score(impact: str, effort: str) -> int:
    """Higher impact + lower effort => higher priority."""
    return _IMPACT_WEIGHT.get(impact, 2) * 10 - _EFFORT_WEIGHT.get(effort, 2)


def build_advisor_plan(
    suggestions: list[dict[str, Any]] | None,
    *,
    max_actions: int = 10,
    require_grounding: bool = True,
) -> dict[str, Any]:
    """Build a deterministic, grounded, prioritized AdvisorPlan from suggestions.

    Each input suggestion is a dict with at least ``action`` and, ideally,
    ``impact``/``effort`` and grounding (``grounded_by_findings``/``derived_from``).
    Returns an AdvisorPlan dict; ``strategic_summary`` is always ``None`` here
    (LLM synthesis is a later increment).
    """
    items = [s for s in (suggestions or []) if isinstance(s, dict)]
    total_candidates = len(items)

    ranked: list[dict[str, Any]] = []
    dropped_ungrounded = 0
    for suggestion in items:
        action = str(suggestion.get("action") or "").strip()
        if not action:
            continue
        grounded, derived = _grounding_refs(suggestion)
        if require_grounding and not (grounded or derived):
            dropped_ungrounded += 1
            continue
        impact = str(suggestion.get("impact") or "medium").strip().lower()
        effort_raw = str(suggestion.get("effort") or "").strip().lower()
        effort_known = effort_raw in _EFFORT_WEIGHT
        # Substitution disclosed, not silent: unrated effort is ranked as if
        # "medium" (hiding the action would be worse), and the payload says so.
        effort_for_rank = effort_raw if effort_known else "medium"
        ranked.append(
            {
                "action": action,
                "title": (str(suggestion.get("title") or "").strip() or None),
                "impact": impact,
                "effort": effort_raw if effort_known else None,
                "ranking_assumptions": ({"effort": "medium"} if not effort_known else {}),
                "roi_score": _roi_score(impact, effort_for_rank),
                "grounded_by_findings": grounded,
                "derived_from": derived,
                # The action's durable identity when a deterministic check
                # raised it. The dismissal key and the plan delta both read it
                # from here, so suppression and progress cannot disagree.
                "problem_code": normalize_problem_code(suggestion.get("problem_code")),
            }
        )

    # Deterministic order: ROI desc, then grounding strength desc, then action text
    # for a stable tie-break (so the same audit yields the same plan).
    ranked.sort(key=lambda a: (-a["roi_score"], -len(a["grounded_by_findings"]), a["action"]))

    capped = ranked[: max(0, int(max_actions))]
    for rank, action in enumerate(capped, start=1):
        action["rank"] = rank

    return {
        "schema_version": ADVISOR_SCHEMA_VERSION,
        "actions": capped,
        "strategic_summary": None,
        "metadata": {
            "total_candidates": total_candidates,
            "actions_count": len(capped),
            "dropped_ungrounded": dropped_ungrounded,
            "deterministic_only": True,
        },
    }


def generate_strategic_summary(plan: dict[str, Any] | None, *, tier: str = "smart") -> str | None:
    """Optional single Bedrock call that narrativizes the grounded plan (increment 3).

    Returns a short plain-prose summary, or ``None`` when there are no actions or
    Bedrock is unavailable / errors. Pure-prose; the system prompt forbids adding
    any fact/action beyond the supplied (already-grounded) list.
    """
    actions = list((plan or {}).get("actions") or [])
    if not actions:
        return None

    # Imported lazily so the deterministic path never depends on the Bedrock helper.
    from core.bedrock_text import bedrock_available, bedrock_generate_text
    from core.config import settings

    if not bedrock_available():
        return None

    lines = [
        f"{a.get('rank', i)}. {a.get('action', '')} (impact={a.get('impact', '?')}, effort={a.get('effort', '?')})"
        for i, a in enumerate(actions[:5], start=1)
        if isinstance(a, dict)
    ]
    user = (
        "Prioritized action plan (highest priority first):\n"
        + "\n".join(lines)
        + "\n\nWrite the 2-3 sentence strategic summary."
    )
    try:
        text = bedrock_generate_text(
            _ADVISOR_SUMMARY_SYSTEM,
            user,
            tier=tier,
            max_tokens=int(getattr(settings, "ADVISOR_SUMMARY_MAX_TOKENS", 400)),
            temperature=0.3,
            use_case="advisor_summary",
        )
    except Exception:
        logger.exception("Advisor strategic_summary synthesis failed")
        return None

    cleaned = (text or "").strip()
    return cleaned or None
