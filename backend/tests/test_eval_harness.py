"""Eval harness tests (EPIC 11 / S11.4) — deterministic, no API keys.

Two layers:
  - the pure threshold gate (release-gating logic), and
  - a composition smoke that runs the real deterministic integrity services.
"""

from tests.fixtures.eval_harness import (
    DEFAULT_THRESHOLDS,
    EvalCorpusItem,
    EvalMetrics,
    gate,
    run_eval_harness,
)


# --------------------------- pure threshold gate ---------------------------


def test_gate_passes_when_metrics_clear_thresholds() -> None:
    metrics = EvalMetrics(grounding_rate=0.90, hallucination_rate=0.05, claim_accuracy=0.90)
    assert gate(metrics, tier="fast").passed is True
    assert gate(metrics, tier="smart").passed is True


def test_gate_fails_fast_tier_on_low_grounding() -> None:
    metrics = EvalMetrics(grounding_rate=0.70, hallucination_rate=0.05, claim_accuracy=0.90)
    result = gate(metrics, tier="fast")
    assert result.passed is False
    assert any("grounding_rate" in f for f in result.failures)


def test_smart_tier_is_stricter_than_fast() -> None:
    # 0.80 clears fast (0.75) but not smart (0.85).
    metrics = EvalMetrics(grounding_rate=0.80, hallucination_rate=0.05, claim_accuracy=0.90)
    assert gate(metrics, tier="fast").passed is True
    assert gate(metrics, tier="smart").passed is False


def test_gate_fails_on_excess_hallucination() -> None:
    metrics = EvalMetrics(grounding_rate=0.95, hallucination_rate=0.30, claim_accuracy=0.90)
    result = gate(metrics, tier="fast")
    assert result.passed is False
    assert any("hallucination_rate" in f for f in result.failures)


def test_gate_fails_on_low_claim_accuracy() -> None:
    metrics = EvalMetrics(grounding_rate=0.95, hallucination_rate=0.05, claim_accuracy=0.50)
    result = gate(metrics, tier="fast")
    assert result.passed is False
    assert any("claim_accuracy" in f for f in result.failures)


def test_default_thresholds_match_s11_4_ac() -> None:
    assert DEFAULT_THRESHOLDS.fast_grounding_min == 0.75
    assert DEFAULT_THRESHOLDS.smart_grounding_min == 0.85
    assert DEFAULT_THRESHOLDS.hallucination_max == 0.15


# ------------------------- composition smoke (real services) ----------------


def _corpus() -> list[EvalCorpusItem]:
    return [
        EvalCorpusItem(
            analysis={
                "seo_findings": [
                    {
                        "description": "The homepage is missing a meta description tag.",
                        "severity": "high",
                    }
                ],
            },
            evidence=(
                "The homepage is the main entry point. It has a title and an H1 "
                "heading but no meta description tag in the document head."
            ),
        ),
        EvalCorpusItem(
            analysis={"seo_findings": []},
            evidence="An empty audit with no findings to verify.",
        ),
    ]


def test_run_eval_harness_composes_services_and_returns_wellformed_metrics() -> None:
    metrics, result, details = run_eval_harness(_corpus(), tier="fast")

    # Metrics are well-formed rates in [0, 1].
    for value in (metrics.grounding_rate, metrics.hallucination_rate, metrics.claim_accuracy):
        assert 0.0 <= value <= 1.0

    # The gate produced a decision for the requested tier with consistent failures.
    assert result.tier == "fast"
    assert isinstance(result.passed, bool)
    assert result.passed == (len(result.failures) == 0)

    # One detail record per corpus item (services were actually invoked).
    assert len(details) == len(_corpus())


# ------------------- an unmeasured harness must not pass -------------------


def test_gate_fails_when_nothing_was_measured() -> None:
    """A harness that checked nothing must not report a release-ready pass.

    `_safe_rate` used to return 1.0 for an empty denominator, so a corpus
    that produced no findings scored a perfect grounding rate and sailed
    through every threshold. The harness announced its best possible result
    at exactly the moment it had verified nothing.
    """
    metrics = EvalMetrics(grounding_rate=None, hallucination_rate=None, claim_accuracy=None)
    result = gate(metrics, tier="fast")

    assert result.passed is False
    assert any("grounding_rate not measured" in f for f in result.failures)
    assert any("hallucination_rate not measured" in f for f in result.failures)
    assert any("claim_accuracy not measured" in f for f in result.failures)


def test_gate_fails_on_a_single_unmeasured_metric() -> None:
    """One missing metric is enough: the others cannot vouch for it."""
    metrics = EvalMetrics(grounding_rate=0.95, hallucination_rate=0.01, claim_accuracy=None)
    result = gate(metrics, tier="fast")

    assert result.passed is False
    assert result.failures == ["claim_accuracy not measured: no claim was extracted"]


def test_an_empty_corpus_reports_no_metrics_and_fails() -> None:
    metrics, result, details = run_eval_harness([])

    assert details == []
    assert metrics.grounding_rate is None
    assert metrics.total_findings == 0
    assert result.passed is False


def test_soft_flagged_findings_are_not_counted_as_grounded() -> None:
    """`soft_flagged` is the gate's "unsure, kept with a warning" verdict.

    Adding it to the grounded numerator inflated the rate with precisely the
    findings the gate could not vouch for, which is how a release gate ends
    up certifying the cases it was least certain about. They are reported on
    their own field instead.
    """
    corpus = [
        EvalCorpusItem(
            analysis={
                "seo_findings": [
                    {
                        "description": "The page loads in under two seconds on mobile.",
                        "severity": "high",
                    }
                ]
            },
            evidence="An unrelated page about office furniture and delivery times.",
        )
    ]
    metrics, _result, _details = run_eval_harness(corpus)

    # Whatever the dispositions came out as, the arithmetic must hold and the
    # soft-flagged ones must not be inside the passed count.
    assert metrics.total_findings >= 1
    assert metrics.passed_findings + metrics.soft_flagged_findings <= metrics.total_findings
    if metrics.grounding_rate is not None:
        assert metrics.grounding_rate == metrics.passed_findings / metrics.total_findings
