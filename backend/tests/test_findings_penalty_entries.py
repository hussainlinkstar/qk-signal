# pyre-unsafe
"""Tests that AI findings surface as individual, real penalty entries instead
of a single opaque "AI-detected X issues (N findings)" bucket.

Prior behavior collapsed every finding returned by the AI experts into one
generic penalty reason used only for score math, discarding the model's real
`description`/`severity`/`category`/`rationale` before it ever reached the
report. This regression-tests the fix: each critical/warning finding must
produce its own penalty entry carrying the real finding content, and the
aggregate score deduction must be unchanged.
"""

import pytest

from score_utils import DeterministicScoringEngine as DSE


def _finding(
    description: str,
    *,
    severity: str = "critical",
    category: str = "content",
    rationale: str = "",
    confidence: float = 0.9,
    estimated_effort: str = "medium",
) -> dict:
    return {
        "description": description,
        "severity": severity,
        "category": category,
        "rationale": rationale,
        "confidence": confidence,
        "estimated_effort": estimated_effort,
    }


class TestFindingsSurfaceAsIndividualPenalties:
    def test_seo_score_emits_one_penalty_per_finding_not_a_bucket(self):
        findings = [
            _finding("Homepage is missing Organization schema entirely.", severity="critical"),
            _finding("Meta description duplicates the page title verbatim.", severity="warning"),
        ]
        result = DSE.calculate_seo_score(findings=findings)

        bucket_reasons = [p for p in result.penalties if "AI-detected" in p.get("reason", "")]
        assert bucket_reasons == [], f"generic bucket penalty should be gone, got {bucket_reasons}"

        finding_penalties = [p for p in result.penalties if p.get("source") == "ai_finding"]
        assert len(finding_penalties) == 2

        critical_entry = next(p for p in finding_penalties if p["severity"] == "critical")
        assert "Organization schema" in critical_entry["description"]
        assert critical_entry["category"] == "content"
        assert critical_entry["impact"] < 0

        warning_entry = next(p for p in finding_penalties if p["severity"] == "warning")
        assert "duplicates the page title" in warning_entry["description"]

    def test_geo_score_finding_penalty_reason_is_a_real_headline(self):
        findings = [
            _finding(
                "The brand has no Wikidata entity, which blocks AI knowledge-panel citation.",
                severity="critical",
                category="entity_authority",
            )
        ]
        result = DSE.calculate_geo_score(findings=findings)
        finding_penalties = [p for p in result.penalties if p.get("source") == "ai_finding"]
        assert len(finding_penalties) == 1
        entry = finding_penalties[0]
        # The short "reason" (used as the card title) must not just be the
        # generic bucket text, and must not be empty.
        assert entry["reason"]
        assert "AI-detected" not in entry["reason"]
        assert entry["category"] == "entity_authority"

    def test_aeo_score_ignores_info_severity_findings_for_penalties(self):
        findings = [_finding("Purely informational note.", severity="info")]
        result = DSE.calculate_aeo_score(findings=findings)
        finding_penalties = [p for p in result.penalties if p.get("source") == "ai_finding"]
        assert finding_penalties == []

    def test_aggregate_score_deduction_is_unchanged_by_the_refactor(self):
        findings = [
            _finding(f"Critical issue number {i}.", severity="critical") for i in range(1, 4)
        ]
        expected_penalty = DSE._calculate_findings_penalty(findings)

        without_findings = DSE.calculate_aeo_score()
        with_findings = DSE.calculate_aeo_score(findings=findings)

        assert with_findings.total_score == pytest.approx(
            max(0.0, without_findings.total_score - expected_penalty), abs=0.15
        )
