import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["DISABLE_TRACING"] = "1"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"
os.environ["SSM_ENABLED"] = "0"

from services.advisor_metrics import (
    AdvisorMetrics,
    compute_advisor_metrics,
    gate_advisor,
)
from services.advisor_service import build_advisor_plan


def _grounded(action, impact="high", effort="low"):
    return {
        "action": action,
        "impact": impact,
        "effort": effort,
        "grounded_by_findings": ["seo.finding.1"],
        "derived_from": ["seo-rec-01"],
    }


def test_empty_plan_passes_vacuously():
    metrics = compute_advisor_metrics(build_advisor_plan([]))
    assert metrics == AdvisorMetrics(1.0, 1.0, 1.0, 1.0)
    assert gate_advisor(metrics, tier="smart").passed is True


def test_well_formed_plan_scores_perfectly():
    plan = build_advisor_plan(
        [
            _grounded("Add FAQPage schema to the pricing page"),
            _grounded(
                "Compress the hero image to under 200KB WebP", impact="high", effort="medium"
            ),
        ]
    )
    metrics = compute_advisor_metrics(plan)
    assert metrics.advice_grounding_rate == 1.0
    assert metrics.actionability_rate == 1.0
    assert metrics.non_duplication_rate == 1.0
    assert metrics.prioritization_sanity == 1.0
    assert gate_advisor(metrics, tier="deep_judgment").passed is True


def test_generic_actions_lower_actionability():
    # Single/short actions are generic, not actionable.
    plan = build_advisor_plan(
        [
            _grounded("Improve SEO"),
            _grounded("Add a descriptive FAQPage schema block to the pricing page"),
        ]
    )
    metrics = compute_advisor_metrics(plan)
    assert metrics.actionability_rate == 0.5  # one generic, one concrete


def test_duplicate_actions_lower_non_duplication():
    metrics = compute_advisor_metrics(
        build_advisor_plan(
            [
                _grounded("Add FAQPage schema to the pricing page"),
                _grounded("Add FAQPage schema to the pricing page"),
            ]
        )
    )
    assert metrics.non_duplication_rate == 0.5


def test_invalid_priority_labels_fail_sanity():
    # Bypass build_advisor_plan to inject an invalid label + ranks.
    plan = {
        "actions": [
            {
                "action": "do the thing properly here",
                "impact": "huge",
                "effort": "low",
                "grounded_by_findings": ["x"],
                "rank": 1,
            },
        ]
    }
    metrics = compute_advisor_metrics(plan)
    assert metrics.prioritization_sanity == 0.0


def test_gate_is_tier_strict():
    # actionability 0.75 passes fast (>=0.70) but fails smart (>=0.80).
    metrics = AdvisorMetrics(
        advice_grounding_rate=1.0,
        actionability_rate=0.75,
        non_duplication_rate=1.0,
        prioritization_sanity=1.0,
    )
    assert gate_advisor(metrics, tier="fast").passed is True
    smart = gate_advisor(metrics, tier="smart")
    assert smart.passed is False
    assert any("actionability" in f for f in smart.failures)
