"""Advisor suppression of dismissed recommendations — Task 7.2.

Given a normalized report and a set of dismissed action fingerprints,
``attach_advisor_view`` must drop the matching actions from
``report.metadata.advisor.actions`` while leaving all others intact. When no
dismissed set is supplied the behaviour is unchanged (backward-compatible).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.advisor_view import attach_advisor_view
from app.services.learnings_service import compute_action_fingerprint


def _report() -> dict:
    return {
        "recommendations": {
            "items": [
                {
                    "action": "Add FAQPage schema to the pricing page",
                    "impact": "high",
                    "estimated_effort": "low",
                    "grounded_by_findings": ["f1"],
                },
                {
                    "action": "Rewrite the meta description",
                    "impact": "medium",
                    "estimated_effort": "low",
                    "grounded_by_findings": ["f2"],
                },
            ]
        }
    }


def _action_texts(report: dict) -> list[str]:
    return [a["action"] for a in report["metadata"]["advisor"]["actions"]]


def test_dismissed_action_suppressed():
    fp = compute_action_fingerprint("Rewrite the meta description")
    result = attach_advisor_view(_report(), dismissed={fp})
    actions = _action_texts(result)
    assert "Rewrite the meta description" not in actions
    assert "Add FAQPage schema to the pricing page" in actions


def test_no_dismissed_set_is_backward_compatible():
    baseline = _action_texts(attach_advisor_view(_report()))
    with_none = _action_texts(attach_advisor_view(_report(), dismissed=None))
    with_empty = _action_texts(attach_advisor_view(_report(), dismissed=set()))
    assert baseline == with_none == with_empty
    assert "Rewrite the meta description" in baseline
    assert "Add FAQPage schema to the pricing page" in baseline


def test_fingerprint_matching_is_case_insensitive():
    # Fingerprint normalises strip+lowercase, so a differently-cased action text
    # still maps to the same dismissed fingerprint.
    fp = compute_action_fingerprint("ADD FAQPAGE SCHEMA TO THE PRICING PAGE")
    result = attach_advisor_view(_report(), dismissed={fp})
    assert "Add FAQPage schema to the pricing page" not in _action_texts(result)
