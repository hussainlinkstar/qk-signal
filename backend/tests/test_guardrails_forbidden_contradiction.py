"""Guardrails goal-(b): flag claims that CONTRADICT forbidden brand facts.

Two layers, both deterministic and LLM-free:

1. Unit — the pure ``forbidden_facts_detector`` flags a claim that asserts a
   forbidden fact, ignores unrelated claims (no false positive), under-flags
   negated claims, and is a strict no-op when there are no forbidden facts.
2. Integration — ``HallucinationService.analyze`` ADDITIVELY annotates a
   contradicting finding (stricter only) WITHOUT touching any threshold, and is
   byte-for-byte identical to the prior behaviour when no forbidden facts are
   supplied.
"""

from __future__ import annotations

import copy

from services.forbidden_facts_detector import (
    build_forbidden_signature,
    claim_asserts_forbidden,
    detect_forbidden_contradictions,
)
from services.grounding_gate_service import (
    PASS_CERTAINTY_THRESHOLD,
    SOFT_FLAG_CERTAINTY_THRESHOLD,
    GroundingGateService,
)
from services.hallucination_service import HallucinationService


# ---------------------------------------------------------------------------
# Unit: pure detector
# ---------------------------------------------------------------------------
def test_detector_flags_claim_asserting_forbidden_fact() -> None:
    matches = detect_forbidden_contradictions(
        claim_texts=[
            "Acme is the undisputed market leader across Europe.",
            "The homepage loads quickly on mobile devices.",
        ],
        forbidden_statements=["Do not state we are the market leader."],
    )

    assert len(matches) == 1
    assert matches[0].claim_index == 0
    assert matches[0].forbidden_statement == "Do not state we are the market leader."
    assert set(matches[0].matched_tokens) == {"market", "leader"}


def test_detector_ignores_unrelated_claims_no_false_positive() -> None:
    matches = detect_forbidden_contradictions(
        claim_texts=[
            "The site has fast Core Web Vitals.",
            "Structured data is present on product pages.",
        ],
        forbidden_statements=["Do not state we are the market leader."],
    )
    assert matches == []


def test_detector_under_flags_negated_claim() -> None:
    # Favour false-negatives: a negated claim does NOT assert the forbidden fact.
    matches = detect_forbidden_contradictions(
        claim_texts=["Acme is not the market leader in this segment."],
        forbidden_statements=["Do not state we are the market leader."],
    )
    assert matches == []


def test_detector_requires_all_signature_tokens() -> None:
    # Only one of the two signature tokens present -> under-flag.
    matches = detect_forbidden_contradictions(
        claim_texts=["Acme is a market challenger."],
        forbidden_statements=["Do not claim we are the market leader."],
    )
    assert matches == []


def test_detector_under_flags_incidental_far_apart_cooccurrence() -> None:
    # Precision: both signature tokens ("market", "leader") are present but appear
    # far apart in unrelated phrases. Under the proximity window this is NOT an
    # assertion of the forbidden fact -> under-flag (no false positive).
    claim = (
        "Our market research is thorough and detailed across regions; "
        "separately, an industry leader recently praised the wider team."
    )
    matches = detect_forbidden_contradictions(
        claim_texts=[claim],
        forbidden_statements=["Do not state we are the market leader."],
    )
    assert matches == []
    # And the pure predicate agrees.
    assert claim_asserts_forbidden(claim, ["market", "leader"]) is False


def test_detector_flags_adjacent_contiguous_forbidden_assertion() -> None:
    # A true, contiguous assertion ("market leader" adjacent) is still flagged.
    matches = detect_forbidden_contradictions(
        claim_texts=["Acme is the market leader in this space."],
        forbidden_statements=["Do not state we are the market leader."],
    )
    assert len(matches) == 1
    assert matches[0].claim_index == 0
    assert set(matches[0].matched_tokens) == {"market", "leader"}
    assert claim_asserts_forbidden("We are the market leader.", ["market", "leader"]) is True


def test_detector_empty_inputs_are_noop() -> None:
    assert detect_forbidden_contradictions(claim_texts=[], forbidden_statements=["x y z"]) == []
    assert (
        detect_forbidden_contradictions(
            claim_texts=["Acme is the market leader."], forbidden_statements=[]
        )
        == []
    )


def test_signature_skips_low_signal_single_token() -> None:
    # "Do not say we are cheap" -> single content token "cheap" -> no signature.
    assert build_forbidden_signature("Do not say we are cheap.") == []
    assert claim_asserts_forbidden("We are cheap and fast.", []) is False


# ---------------------------------------------------------------------------
# Integration: HallucinationService.analyze (no LLM, TF-IDF path)
# ---------------------------------------------------------------------------
def _analysis_fixture() -> dict:
    return {
        "claims": [
            {
                "id": "c1",
                "text": "Acme is the undisputed market leader in Europe.",
                "field_path": "seo_findings[0]",
                "field_label": "Brand positioning",
                "field_group": "seo_findings",
                "group_label": "SEO Findings",
            },
            {
                "id": "c2",
                "text": "The website serves all pages over HTTPS.",
                "field_path": "seo_findings[1]",
                "field_label": "Transport security",
                "field_group": "seo_findings",
                "group_label": "SEO Findings",
            },
        ]
    }


_SOURCE = (
    "Welcome to the website. The website serves all pages over HTTPS "
    "and uses modern transport security across every page."
)


def test_analyze_annotates_forbidden_contradiction() -> None:
    service = HallucinationService()
    result = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
        forbidden_brand_facts=["Do not state we are the market leader."],
    )

    verifications = {cv["claim_id"]: cv for cv in result["claim_verifications"]}
    flagged = verifications["c1"]
    assert flagged["forbidden_contradiction"] is True
    assert flagged["forbidden_fact_statement"] == "Do not state we are the market leader."
    assert flagged["disposition"] == "flagged"
    assert flagged["hallucination"] is True
    assert flagged["discrepancy_type"] == "forbidden_brand_fact_contradiction"
    assert flagged["severity"] == "high"
    assert flagged["certainty_score"] == 0.0

    # Unrelated claim is untouched by the guardrail.
    assert "forbidden_contradiction" not in verifications["c2"]


def test_analyze_accepts_brand_fact_dicts_and_filters_non_forbidden() -> None:
    service = HallucinationService()
    result = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
        forbidden_brand_facts=[
            {"statement": "Do not state we are the market leader.", "is_forbidden": True},
            {"statement": "We serve pages over HTTPS.", "is_forbidden": False},
        ],
    )
    verifications = {cv["claim_id"]: cv for cv in result["claim_verifications"]}
    assert verifications["c1"].get("forbidden_contradiction") is True
    # The non-forbidden fact must NOT cause any flagging.
    assert "forbidden_contradiction" not in verifications["c2"]


def test_no_forbidden_facts_is_byte_identical() -> None:
    service = HallucinationService()
    baseline = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
    )
    with_empty_param = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
        forbidden_brand_facts=[],
    )
    with_none_param = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
        forbidden_brand_facts=None,
    )
    # Only-non-forbidden dicts must also be a strict no-op.
    with_non_forbidden = service.analyze(
        source_content=_SOURCE,
        analysis=_analysis_fixture(),
        forbidden_brand_facts=[{"statement": "We serve HTTPS.", "is_forbidden": False}],
    )

    assert with_empty_param == baseline
    assert with_none_param == baseline
    assert with_non_forbidden == baseline


def test_grounding_gate_excludes_forbidden_finding_without_threshold_change() -> None:
    # Thresholds are untouched by this feature.
    assert PASS_CERTAINTY_THRESHOLD == 0.40
    assert SOFT_FLAG_CERTAINTY_THRESHOLD == 0.15

    service = HallucinationService()
    analysis = _analysis_fixture()
    # The gate operates on the findings lists; pair the extracted claims with the
    # findings they describe so finding removal is observable.
    analysis["seo_findings"] = [
        {
            "description": "Acme is the undisputed market leader in Europe.",
            "label": "Brand positioning",
        },
        {"description": "The website serves all pages over HTTPS.", "label": "Transport security"},
    ]
    hallucination_result = service.analyze(
        source_content=_SOURCE,
        analysis=analysis,
        forbidden_brand_facts=["Do not state we are the market leader."],
    )

    gate = GroundingGateService()
    result = gate.evaluate(
        ai_analysis_results=copy.deepcopy(analysis),
        hallucination_result=hallucination_result,
    )

    # The forbidden-contradiction finding (seo_findings[0]) is hard-flagged
    # (zero certainty) and removed -> grounding got STRICTER, not looser.
    remaining = list((result.filtered_analysis or {}).get("seo_findings", []))
    assert result.hard_flagged >= 1
    # seo_findings[0] (the forbidden claim) is gone; the HTTPS finding remains.
    assert all(f.get("label") != "Brand positioning" for f in remaining if isinstance(f, dict))
