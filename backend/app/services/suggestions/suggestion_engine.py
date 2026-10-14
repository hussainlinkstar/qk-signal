from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from problem_codes import normalize_problem_code

IMPACT_WEIGHTS: dict[str, int] = {"high": 3, "medium": 2, "low": 1}
EFFORT_WEIGHTS: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


def generate_unified_suggestions(
    module_outputs: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build a deduplicated, ROI-sorted suggestion list from all audit module outputs.

    Candidates carrying a deterministic ``problem_code`` dedupe on that code
    rather than on their action text: the code identifies the failing check, so
    two phrasings of the same deterministic problem collapse into one fix.
    Uncoded (LLM-authored) candidates keep deduping on normalized text.
    """

    suggestions = _extract_candidate_suggestions(module_outputs)

    deduped: dict[str, dict[str, Any]] = {}
    for suggestion in suggestions:
        key = suggestion.get("problem_code") or _normalize_action(suggestion["action"])
        if not key:
            continue

        existing = deduped.get(key)
        if existing is None or _roi_rank(suggestion) > _roi_rank(existing):
            deduped[key] = suggestion

    return sorted(deduped.values(), key=_sort_key)


def _extract_candidate_suggestions(
    module_outputs: Mapping[str, Any] | Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    queue: list[Any] = []
    if isinstance(module_outputs, Mapping):
        queue.extend(module_outputs.values())
    else:
        queue.extend(module_outputs)

    flattened: list[Any] = []
    while queue:
        current = queue.pop(0)
        if isinstance(current, Mapping):
            flattened.append(current)
            for key in ("recommendations", "suggestions", "items", "findings"):
                value = current.get(key)
                if isinstance(value, list):
                    queue.extend(value)
        elif isinstance(current, list):
            queue.extend(current)

    results: list[dict[str, Any]] = []
    for entry in flattened:
        suggestion = _normalize_suggestion(entry)
        if suggestion is not None:
            results.append(suggestion)

    return results


def _normalize_suggestion(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    action = _string_or_empty(
        entry.get("action") or entry.get("recommendation") or entry.get("title")
    )
    if not action:
        return None

    impact = _normalize_label(entry.get("impact"), IMPACT_WEIGHTS, fallback="medium")
    effort = _normalize_label(entry.get("effort"), EFFORT_WEIGHTS, fallback=None)
    justification = _string_or_empty(
        entry.get("justification") or entry.get("reason") or entry.get("why")
    )

    if not justification:
        justification = "Improves audit health based on module findings."

    # A deterministic ``problem_code`` and its grounding references are the only
    # durable identity a recommendation has across audits, so they are carried
    # through instead of being dropped with the rest of the source entry. An
    # unknown or absent code stays None: identity then falls back to the action
    # text, which can only under-suppress, never over-suppress.
    return {
        "impact": impact,
        "effort": effort,
        "action": action,
        "justification": justification,
        "problem_code": normalize_problem_code(entry.get("problem_code")),
        "grounded_by_findings": _string_list(entry.get("grounded_by_findings")),
        "derived_from": _string_list(entry.get("derived_from")),
    }


def _string_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [text for text in (_string_or_empty(item) for item in raw) if text]


def _normalize_label(raw: Any, allowed: dict[str, int], *, fallback: str | None) -> str | None:
    value = _string_or_empty(raw).lower()
    return value if value in allowed else fallback


def _string_or_empty(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _normalize_action(action: str) -> str:
    return re.sub(r"\s+", " ", action.strip().lower())


def _roi_rank(suggestion: Mapping[str, Any]) -> int:
    impact_weight = IMPACT_WEIGHTS[suggestion["impact"]]
    # Unrated effort ranks AS IF medium (documented substitution: dropping the
    # item from the ordering would hide the recommendation entirely).
    effort_weight = EFFORT_WEIGHTS.get(suggestion["effort"], 2)
    return impact_weight * 10 - effort_weight


def _sort_key(suggestion: Mapping[str, Any]) -> tuple[int, int, str]:
    impact_weight = IMPACT_WEIGHTS[suggestion["impact"]]
    effort_weight = EFFORT_WEIGHTS.get(suggestion["effort"], 2)
    return (-impact_weight, effort_weight, suggestion["action"].lower())


__all__ = ["generate_unified_suggestions"]
