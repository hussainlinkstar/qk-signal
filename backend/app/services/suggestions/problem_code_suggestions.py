"""Deterministic problem candidates: the suggestion channel that carries identity.

Every other suggestion candidate in the audit originates in LLM prose, so its
wording (and therefore its text hash) drifts between runs. This module opens a
second channel: the deterministic scoring engine's failed checks, each already
tagged with a stable ``code`` (see :mod:`problem_codes`), become suggestion
candidates that carry that code from birth.

The code is attached here, BEFORE enrichment rewrites the copy, and is passed
through the pipeline untouched. That is what makes a dismissal survive a
reworded title: identity is the failing check, not the sentence describing it.

Pure and deterministic: no LLM, no DB, no network, no mutation of its inputs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from problem_codes import (
    impact_label_for_points,
    normalize_problem_code,
    seed_action_for,
)

#: Breakdown keys in a ``calculate_deterministic_scores`` result, mapped to the
#: score dimension used in grounding references.
_BREAKDOWN_KEYS: tuple[tuple[str, str], ...] = (
    ("seo_breakdown", "seo"),
    ("geo_breakdown", "geo"),
    ("aeo_breakdown", "aeo"),
)


def grounding_ref(dimension: str, code: str) -> str:
    """Return the evidence reference for a deterministic problem.

    Unlike the positional ``{domain}.finding.{n}`` references derived from LLM
    findings, this reference is stable and resolvable: the penalty it names is
    persisted in the report's own score breakdown, so a reader can verify the
    recommendation against measured page signals.
    """
    return f"{dimension}.penalty.{code}"


def build_problem_code_suggestions(
    deterministic_scores: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Turn coded deterministic penalties into suggestion candidates.

    Reads ``seo_breakdown`` / ``geo_breakdown`` / ``aeo_breakdown`` penalties,
    keeps the entries whose ``code`` is a known problem code, and emits one
    candidate per code (first occurrence wins, so a check that penalises two
    dimensions still yields a single fix). Penalties without a code, e.g. a
    failed scrape or an AI-finding-derived entry, are ignored: a code may only
    come from a deterministic check.

    Impact is read off the penalty's own point deduction; effort is left unset
    because nothing deterministic measures it, and the Advisor discloses that
    substitution rather than inventing a rating.
    """
    if not isinstance(deterministic_scores, Mapping):
        return []

    suggestions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for breakdown_key, dimension in _BREAKDOWN_KEYS:
        breakdown = deterministic_scores.get(breakdown_key)
        if not isinstance(breakdown, Mapping):
            continue
        penalties = breakdown.get("penalties")
        if not isinstance(penalties, list):
            continue

        for penalty in penalties:
            if not isinstance(penalty, Mapping):
                continue
            code = normalize_problem_code(penalty.get("code"))
            if code is None or code in seen:
                continue
            seed_action = seed_action_for(code)
            if not seed_action:
                continue
            seen.add(code)

            reason = str(penalty.get("reason") or "").strip()
            justification = (
                f"A deterministic check on the audited page failed: {reason}."
                if reason
                else "A deterministic check on the audited page failed."
            )
            reference = grounding_ref(dimension, code)
            suggestions.append(
                {
                    "action": seed_action,
                    "impact": impact_label_for_points(penalty.get("impact")),
                    "effort": None,
                    "justification": justification,
                    "problem_code": code,
                    "grounded_by_findings": [reference],
                    "derived_from": [reference],
                }
            )

    return suggestions


__all__ = ["build_problem_code_suggestions", "grounding_ref"]
