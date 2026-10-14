"""Tests for plan-aware AI prompt gates — verifying that plan_gates flow through
context_payload and produce PLAN SCOPE directives in the AI prompt."""

import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DISABLE_TRACING", "1")

from services.audit_feature_gating_service import resolve_audit_execution_gates
from app.config.plans import can_use_feature


# ---------------------------------------------------------------------------
# resolve_audit_execution_gates tests
# ---------------------------------------------------------------------------


class TestResolveAuditExecutionGates:
    """Verify gate resolution returns correct booleans per plan."""

    def test_free_plan_blocks_all_premium_gates(self):
        gates = resolve_audit_execution_gates("plan_starter")
        assert gates["allow_predictive_intent"] is False
        assert gates["allow_competitor_analysis"] is False
        assert gates["allow_entity_enhancement"] is False

    def test_plan_standard_blocks_premium_gates(self):
        gates = resolve_audit_execution_gates("plan_standard")
        assert gates["allow_predictive_intent"] is False
        assert gates["allow_competitor_analysis"] is False

    def test_plan_specialist_allows_competitor_and_intent(self):
        gates = resolve_audit_execution_gates("plan_specialist")
        assert gates["allow_predictive_intent"] is True
        assert gates["allow_competitor_analysis"] is True
        assert gates["allow_entity_enhancement"] is True

    def test_plan_executive_allows_all(self):
        gates = resolve_audit_execution_gates("plan_executive")
        assert gates["allow_predictive_intent"] is True
        assert gates["allow_competitor_analysis"] is True
        assert gates["allow_entity_enhancement"] is True


# ---------------------------------------------------------------------------
# plan_gates dict construction tests (mirrors audit_runner.py logic)
# ---------------------------------------------------------------------------


def _build_plan_gates(user_plan: str) -> dict:
    """Reproduce the plan_gates dict as constructed in audit_runner.py."""
    gates = resolve_audit_execution_gates(user_plan)
    normalized = str(gates["normalized_plan"])
    return {
        "allow_competitor_analysis": bool(gates["allow_competitor_analysis"]),
        "allow_predictive_intent": bool(gates["allow_predictive_intent"]),
        "allow_semantic_graph": can_use_feature(normalized, "has_semantic_graph_mapping"),
        "allow_advanced_reporting": can_use_feature(normalized, "has_advanced_reporting"),
        "allow_brand_integrity": can_use_feature(normalized, "has_brand_integrity_guardrails"),
        "allow_eeat_trust": can_use_feature(normalized, "has_eeat_trust_audit"),
    }


class TestPlanGatesDict:
    """Verify the plan_gates dict used by context_payload."""

    def test_free_plan_gates_all_false(self):
        gates = _build_plan_gates("plan_starter")
        assert all(v is False for v in gates.values())

    def test_plan_standard_gates_all_false(self):
        gates = _build_plan_gates("plan_standard")
        assert all(v is False for v in gates.values())

    def test_plan_specialist_unlocks_most(self):
        gates = _build_plan_gates("plan_specialist")
        assert gates["allow_competitor_analysis"] is True
        assert gates["allow_predictive_intent"] is True
        assert gates["allow_semantic_graph"] is True
        assert gates["allow_advanced_reporting"] is True
        # brand_integrity and eeat_trust need plan_executive
        assert gates["allow_brand_integrity"] is False
        assert gates["allow_eeat_trust"] is False

    def test_plan_executive_unlocks_all(self):
        gates = _build_plan_gates("plan_executive")
        assert all(v is True for v in gates.values())


# ---------------------------------------------------------------------------
# AI prompt scope injection tests (simulate ai_engine.py logic)
# ---------------------------------------------------------------------------


def _build_plan_scope_section(plan_gates: dict) -> str:
    """Reproduce the plan scope prompt construction from ai_engine.py."""
    _plan_scope_lines: list[str] = []
    if plan_gates and not all(plan_gates.values()):
        if not plan_gates.get("allow_competitor_analysis"):
            _plan_scope_lines.append("- SKIP competitor benchmarking.")
        if not plan_gates.get("allow_predictive_intent"):
            _plan_scope_lines.append("- SKIP predictive intent classification.")
        if not plan_gates.get("allow_semantic_graph"):
            _plan_scope_lines.append("- SKIP detailed schema health and schema coverage analysis.")
        if not plan_gates.get("allow_advanced_reporting"):
            _plan_scope_lines.append("- SKIP advanced narrative reporting.")
        if not plan_gates.get("allow_brand_integrity"):
            _plan_scope_lines.append("- SKIP brand integrity guardrails.")
        if not plan_gates.get("allow_eeat_trust"):
            _plan_scope_lines.append("- SKIP E-E-A-T trust scoring.")
    if _plan_scope_lines:
        return "\n### PLAN SCOPE — FEATURE REDUCTION\n" + "\n".join(_plan_scope_lines) + "\n"
    return ""


class TestPlanScopePromptInjection:
    """Verify that plan scope directives are correctly generated."""

    def test_plan_standard_gets_all_skip_directives(self):
        gates = _build_plan_gates("plan_standard")
        scope = _build_plan_scope_section(gates)
        assert "PLAN SCOPE" in scope
        assert "SKIP competitor" in scope
        assert "SKIP predictive intent" in scope
        assert "SKIP detailed schema" in scope
        assert "SKIP advanced narrative" in scope
        assert "SKIP brand integrity" in scope
        assert "SKIP E-E-A-T" in scope

    def test_plan_specialist_only_skips_elite_features(self):
        gates = _build_plan_gates("plan_specialist")
        scope = _build_plan_scope_section(gates)
        assert "PLAN SCOPE" in scope
        assert "SKIP competitor" not in scope
        assert "SKIP predictive intent" not in scope
        assert "SKIP detailed schema" not in scope
        assert "SKIP advanced narrative" not in scope
        # These two require plan_executive
        assert "SKIP brand integrity" in scope
        assert "SKIP E-E-A-T" in scope

    def test_plan_executive_no_skip_directives(self):
        gates = _build_plan_gates("plan_executive")
        scope = _build_plan_scope_section(gates)
        assert scope == ""

    def test_empty_gates_no_scope(self):
        scope = _build_plan_scope_section({})
        assert scope == ""

    def test_all_true_gates_no_scope(self):
        gates = {
            k: True
            for k in [
                "allow_competitor_analysis",
                "allow_predictive_intent",
                "allow_semantic_graph",
                "allow_advanced_reporting",
                "allow_brand_integrity",
                "allow_eeat_trust",
            ]
        }
        scope = _build_plan_scope_section(gates)
        assert scope == ""
