"""AEX-14: Consolidator Degradation Signal — comprehensive tests.

Covers:
  - DebateResult.consolidation_status field defaults and propagation
  - Quality gate threshold tightening for degraded/bypassed consolidation
  - Quality gate output shape (consolidation_status, effective_thresholds)
  - Magistrate prompt injection for each consolidation status
  - _build_debate_result forwarding consolidation_status
"""

from __future__ import annotations

from dataclasses import fields as dc_fields
from unittest.mock import patch

import pytest

from services.debate_orchestrator import (
    CONSOLIDATION_BYPASSED,
    CONSOLIDATION_DEGRADED,
    CONSOLIDATION_FULL,
    CONSOLIDATION_PARTIAL,
    DebateResult,
    _build_debate_result,
    _build_global_magistrate_prompt,
)
from services.prompt_quality_gate import (
    _DEGRADED_CONTRADICTION_RATE_REDUCTION,
    _DEGRADED_GROUNDING_RATE_BUMP,
    _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX,
    _GENERATOR_GROUNDING_RATE_MIN,
    prompt_quality_gate_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generator_round(
    *,
    role: str = "seo_generator",
    domain: str = "seo",
    claims: list[dict] | None = None,
    layer: int = 1,
) -> dict:
    if claims is None:
        claims = [
            {
                "claim_id": f"{domain}-01",
                "domain": domain,
                "claim_text": "Add internal links from category pages.",
                "evidence_refs": ["crawl-link-map"],
            },
        ]
    return {
        "role": role,
        "semantic_role": "generator",
        "layer": layer,
        "output": {"claim_ledger": claims},
    }


def _make_consolidator_round(
    *,
    dispositions: list[dict] | None = None,
    layer: int = 3,
) -> dict:
    if dispositions is None:
        dispositions = [
            {"claim_id": "seo-01", "domain": "seo", "disposition": "accepted"},
        ]
    return {
        "role": "consolidator",
        "semantic_role": "judge",
        "layer": layer,
        "output": {
            "consolidated_claim_disposition": dispositions,
            "dedup_count": 0,
        },
    }


_DEFAULT_ANCHOR = {
    "critical_metrics": {
        "domain_authority": 34,
        "pages_crawled": 18,
        "schema_types_found": ["Article", "FAQPage"],
    }
}

_DEFAULT_JUDGE_SUMMARY = {
    "accepted_claims": 1,
    "downgraded_claims": 0,
    "rejected_claims": 0,
    "unresolved_disputes": 0,
}


# ---------------------------------------------------------------------------
# 1. DebateResult dataclass — consolidation_status field
# ---------------------------------------------------------------------------


class TestDebateResultConsolidationField:
    def test_field_exists_with_correct_default(self):
        field_names = {f.name for f in dc_fields(DebateResult)}
        assert "consolidation_status" in field_names

        field_meta = next(f for f in dc_fields(DebateResult) if f.name == "consolidation_status")
        assert field_meta.default == CONSOLIDATION_FULL

    def test_constants_are_distinct_strings(self):
        values = {
            CONSOLIDATION_FULL,
            CONSOLIDATION_PARTIAL,
            CONSOLIDATION_BYPASSED,
            CONSOLIDATION_DEGRADED,
        }
        assert len(values) == 4
        for v in values:
            assert isinstance(v, str) and len(v) > 0


# ---------------------------------------------------------------------------
# 2. _build_debate_result — consolidation_status forwarding
# ---------------------------------------------------------------------------


class TestBuildDebateResultConsolidation:
    _BASE_KWARGS = dict(
        rounds=[],
        final_synthesis={},
        synthesis_reasoning="test",
        debate_confidence_score=0.5,
        total_token_usage={},
        total_latency_ms=100.0,
        total_estimated_cost_usd=0.01,
        profile="test",
        pipeline_type="delta_flow",
    )

    def test_defaults_to_full(self):
        result = _build_debate_result(**self._BASE_KWARGS)
        assert result.consolidation_status == CONSOLIDATION_FULL

    @pytest.mark.parametrize(
        "status",
        [
            CONSOLIDATION_FULL,
            CONSOLIDATION_PARTIAL,
            CONSOLIDATION_BYPASSED,
            CONSOLIDATION_DEGRADED,
        ],
    )
    def test_forwards_each_status(self, status):
        result = _build_debate_result(**self._BASE_KWARGS, consolidation_status=status)
        assert result.consolidation_status == status


# ---------------------------------------------------------------------------
# 3. Magistrate prompt injection
# ---------------------------------------------------------------------------


class TestMagistratePromptConsolidationNotice:
    _AUDIT_DATA = {"url": "https://example.com", "business_name": "Test"}
    _GEN_PACKETS = {"seo": {"claim_ledger": []}}

    @patch("services.debate_orchestrator.load_prompt_with_context", return_value="System prompt")
    def test_full_consolidation_no_notice(self, _mock_prompt):
        _system, user_parts = _build_global_magistrate_prompt(
            self._AUDIT_DATA,
            generator_packets=self._GEN_PACKETS,
            consolidated_packet={"domain_summaries": {}},
            critique_packets=None,
            prompt_context="",
            consolidation_status=CONSOLIDATION_FULL,
        )
        user_text = user_parts[0] if user_parts else ""
        assert "CONSOLIDATION STATUS" not in user_text

    @patch("services.debate_orchestrator.load_prompt_with_context", return_value="System prompt")
    def test_bypassed_injects_notice(self, _mock_prompt):
        _system, user_parts = _build_global_magistrate_prompt(
            self._AUDIT_DATA,
            generator_packets=self._GEN_PACKETS,
            consolidated_packet=None,
            critique_packets={"seo": {"challenges": []}},
            prompt_context="",
            consolidation_status=CONSOLIDATION_BYPASSED,
        )
        user_text = user_parts[0] if user_parts else ""
        assert "CONSOLIDATION STATUS: BYPASSED" in user_text
        assert "failed entirely" in user_text
        assert "mini-consolidation" in user_text

    @patch("services.debate_orchestrator.load_prompt_with_context", return_value="System prompt")
    def test_degraded_injects_notice(self, _mock_prompt):
        _system, user_parts = _build_global_magistrate_prompt(
            self._AUDIT_DATA,
            generator_packets=self._GEN_PACKETS,
            consolidated_packet={"partial": True},
            critique_packets=None,
            prompt_context="",
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        user_text = user_parts[0] if user_parts else ""
        assert "CONSOLIDATION STATUS: DEGRADED" in user_text
        assert "incomplete output" in user_text
        assert "reduced trust" in user_text

    @patch("services.debate_orchestrator.load_prompt_with_context", return_value="System prompt")
    def test_partial_injects_notice(self, _mock_prompt):
        _system, user_parts = _build_global_magistrate_prompt(
            self._AUDIT_DATA,
            generator_packets=self._GEN_PACKETS,
            consolidated_packet={"partial": True},
            critique_packets=None,
            prompt_context="",
            consolidation_status=CONSOLIDATION_PARTIAL,
        )
        user_text = user_parts[0] if user_parts else ""
        assert "CONSOLIDATION STATUS: PARTIAL" in user_text
        assert "extra scrutiny" in user_text

    @patch("services.debate_orchestrator.load_prompt_with_context", return_value="System prompt")
    def test_bypassed_uses_critique_packets_not_consolidated(self, _mock_prompt):
        critique = {"seo": {"challenges": ["issue-1"]}}
        _system, user_parts = _build_global_magistrate_prompt(
            self._AUDIT_DATA,
            generator_packets=self._GEN_PACKETS,
            consolidated_packet=None,
            critique_packets=critique,
            prompt_context="",
            consolidation_status=CONSOLIDATION_BYPASSED,
        )
        user_text = user_parts[0] if user_parts else ""
        assert "Critique Packets" in user_text
        assert "Consolidated Packet" not in user_text


# ---------------------------------------------------------------------------
# 4. Quality gate — consolidation_status in output and effective thresholds
# ---------------------------------------------------------------------------


class TestQualityGateConsolidationOutput:
    def test_output_contains_consolidation_status_full(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="delta_flow",
            judge_summary=_DEFAULT_JUDGE_SUMMARY,
            consolidation_status=CONSOLIDATION_FULL,
        )
        assert result["consolidation_status"] == CONSOLIDATION_FULL
        assert "effective_thresholds" in result
        assert result["effective_thresholds"]["grounding_rate_min"] == round(
            _GENERATOR_GROUNDING_RATE_MIN, 4
        )
        assert result["effective_thresholds"]["contradiction_rate_max"] == round(
            _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX, 4
        )

    def test_output_contains_consolidation_status_bypassed(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="delta_flow",
            judge_summary=_DEFAULT_JUDGE_SUMMARY,
            consolidation_status=CONSOLIDATION_BYPASSED,
        )
        assert result["consolidation_status"] == CONSOLIDATION_BYPASSED

    def test_effective_thresholds_tightened_when_degraded(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="delta_flow",
            judge_summary=_DEFAULT_JUDGE_SUMMARY,
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        expected_grounding = round(
            min(1.0, _GENERATOR_GROUNDING_RATE_MIN + _DEGRADED_GROUNDING_RATE_BUMP),
            4,
        )
        expected_contradiction = round(
            max(
                0.0,
                _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX - _DEGRADED_CONTRADICTION_RATE_REDUCTION,
            ),
            4,
        )
        assert result["effective_thresholds"]["grounding_rate_min"] == expected_grounding
        assert result["effective_thresholds"]["contradiction_rate_max"] == expected_contradiction

    def test_effective_thresholds_tightened_when_bypassed(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="delta_flow",
            consolidation_status=CONSOLIDATION_BYPASSED,
        )
        assert result["effective_thresholds"]["grounding_rate_min"] > _GENERATOR_GROUNDING_RATE_MIN
        assert (
            result["effective_thresholds"]["contradiction_rate_max"]
            < _GENERATOR_ANCHOR_CONTRADICTION_RATE_MAX
        )

    def test_default_consolidation_status_is_full(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="delta_flow",
        )
        assert result["consolidation_status"] == CONSOLIDATION_FULL


# ---------------------------------------------------------------------------
# 5. Quality gate — threshold tightening triggers additional violations
# ---------------------------------------------------------------------------


class TestQualityGateThresholdTightening:
    """Verify that degraded consolidation causes borderline outputs to fail."""

    def _make_borderline_grounding_claims(self, grounded_count: int, total: int) -> list[dict]:
        """Build claims where exactly `grounded_count` of `total` have evidence."""
        claims = []
        for i in range(total):
            claims.append(
                {
                    "claim_id": f"seo-{i:02d}",
                    "domain": "seo",
                    "claim_text": f"Claim number {i}.",
                    "evidence_refs": ["ref-1"] if i < grounded_count else [],
                }
            )
        return claims

    def test_borderline_grounding_passes_with_full_consolidation(self):
        """90% grounding > 85% threshold → passes when consolidation is full."""
        claims = self._make_borderline_grounding_claims(grounded_count=9, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            judge_summary={
                "accepted_claims": 10,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "unresolved_disputes": 0,
            },
            consolidation_status=CONSOLIDATION_FULL,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_grounding_rate_low" not in violation_codes

    def test_borderline_grounding_fails_with_degraded_consolidation(self):
        """90% grounding < 95% tightened threshold → fails when degraded."""
        claims = self._make_borderline_grounding_claims(grounded_count=9, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            judge_summary={
                "accepted_claims": 10,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "unresolved_disputes": 0,
            },
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_grounding_rate_low" in violation_codes

    def test_borderline_grounding_fails_with_bypassed_consolidation(self):
        """Same borderline output fails with bypassed status too."""
        claims = self._make_borderline_grounding_claims(grounded_count=9, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            consolidation_status=CONSOLIDATION_BYPASSED,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_grounding_rate_low" in violation_codes

    def test_partial_consolidation_uses_normal_thresholds(self):
        """PARTIAL is not in the tightened set — uses normal thresholds."""
        claims = self._make_borderline_grounding_claims(grounded_count=9, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            consolidation_status=CONSOLIDATION_PARTIAL,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_grounding_rate_low" not in violation_codes

    def test_perfect_grounding_passes_even_when_degraded(self):
        """100% grounding passes regardless of consolidation status."""
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            judge_summary=_DEFAULT_JUDGE_SUMMARY,
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_grounding_rate_low" not in violation_codes


# ---------------------------------------------------------------------------
# 6. Quality gate — contradiction threshold tightening
# ---------------------------------------------------------------------------


class TestQualityGateContradictionTightening:
    def _make_contradiction_claims(self, contradicting: int, total: int) -> list[dict]:
        """Build claims where `contradicting` out of `total` contradict the anchor."""
        claims = []
        for i in range(total):
            if i < contradicting:
                claims.append(
                    {
                        "claim_id": f"seo-{i:02d}",
                        "domain": "seo",
                        "claim_text": "Domain authority is 99.",
                        "evidence_refs": ["ref-1"],
                    }
                )
            else:
                claims.append(
                    {
                        "claim_id": f"seo-{i:02d}",
                        "domain": "seo",
                        "claim_text": "Improve internal linking structure.",
                        "evidence_refs": ["ref-1"],
                    }
                )
        return claims

    def test_borderline_contradiction_passes_with_full(self):
        """1/10 = 10% contradiction rate == threshold → passes with full consolidation."""
        claims = self._make_contradiction_claims(contradicting=1, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor={
                "critical_metrics": {
                    "domain_authority": 34,
                    "pages_crawled": 18,
                    "schema_types_found": ["Article"],
                }
            },
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            judge_summary={
                "accepted_claims": 10,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "unresolved_disputes": 0,
            },
            consolidation_status=CONSOLIDATION_FULL,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_anchor_contradiction_rate_high" not in violation_codes

    def test_borderline_contradiction_fails_with_degraded(self):
        """1/10 = 10% > tightened 7% threshold → fails when degraded."""
        claims = self._make_contradiction_claims(contradicting=1, total=10)
        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor={
                "critical_metrics": {
                    "domain_authority": 34,
                    "pages_crawled": 18,
                    "schema_types_found": ["Article"],
                }
            },
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            judge_summary={
                "accepted_claims": 10,
                "downgraded_claims": 0,
                "rejected_claims": 0,
                "unresolved_disputes": 0,
            },
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        violation_codes = {v["code"] for v in result["violations"]}
        assert "generator_anchor_contradiction_rate_high" in violation_codes


# ---------------------------------------------------------------------------
# 7. Quality gate — violation threshold metadata
# ---------------------------------------------------------------------------


class TestQualityGateViolationThresholdMetadata:
    """Verify violation records use effective (tightened) thresholds."""

    def test_violation_threshold_reflects_tightened_value(self):
        """When degraded, violation threshold should be the tightened value, not the base."""
        claims = []
        for i in range(10):
            claims.append(
                {
                    "claim_id": f"seo-{i:02d}",
                    "domain": "seo",
                    "claim_text": f"Claim {i}.",
                    "evidence_refs": ["ref"] if i < 9 else [],
                }
            )

        result = prompt_quality_gate_service.evaluate(
            rounds=[
                _make_generator_round(claims=claims),
                _make_consolidator_round(
                    dispositions=[
                        {"claim_id": f"seo-{i:02d}", "domain": "seo", "disposition": "accepted"}
                        for i in range(10)
                    ],
                ),
            ],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="deep_judgment",
            pipeline_type="delta_flow",
            consolidation_status=CONSOLIDATION_DEGRADED,
        )
        grounding_violations = [
            v for v in result["violations"] if v["code"] == "generator_grounding_rate_low"
        ]
        assert len(grounding_violations) == 1
        tightened_min = min(1.0, _GENERATOR_GROUNDING_RATE_MIN + _DEGRADED_GROUNDING_RATE_BUMP)
        assert grounding_violations[0]["threshold"] == tightened_min


# ---------------------------------------------------------------------------
# 8. Existing tests still pass with new parameter
# ---------------------------------------------------------------------------


class TestQualityGateBackwardCompatibility:
    """Ensure old call sites without consolidation_status still work."""

    def test_evaluate_without_consolidation_status_defaults_to_full(self):
        result = prompt_quality_gate_service.evaluate(
            rounds=[_make_generator_round(), _make_consolidator_round()],
            evidence_anchor=_DEFAULT_ANCHOR,
            requested_tier="smart",
            pipeline_type="smart_5step",
            judge_summary=_DEFAULT_JUDGE_SUMMARY,
        )
        assert result["consolidation_status"] == CONSOLIDATION_FULL
        assert result["effective_thresholds"]["grounding_rate_min"] == round(
            _GENERATOR_GROUNDING_RATE_MIN, 4
        )
        assert result["passed"] is True
