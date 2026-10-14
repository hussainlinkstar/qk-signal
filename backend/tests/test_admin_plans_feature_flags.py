"""Tests for TASK_ADMIN-06 — Plan & Feature Flag Management endpoints + helpers."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

import app.config.plans as plans

# ---------------------------------------------------------------------------
# 1. Plan comparison endpoint helpers
# ---------------------------------------------------------------------------

from app.config.plans import (
    CAPABILITY_MATRIX,
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
    get_plan_weight,
    plan_meets_requirement,
    resolve_plan_alias,
)


class TestPlanCapabilities:
    """Verify the plan config is internally consistent."""

    def test_all_canonical_plans_exist(self):
        assert set(CAPABILITY_MATRIX) == {
            "plan_starter",
            "plan_agency_trial",
            "plan_standard",
            "plan_specialist",
            "plan_executive",
        }

    def test_canonical_plan_types_match_application_plan_ids(self):
        assert set(plans.CANONICAL_PLAN_TYPES) == set(CAPABILITY_MATRIX)

    def test_all_plans_have_same_keys(self):
        keys_per_plan = [set(caps.keys()) for caps in CAPABILITY_MATRIX.values()]
        assert all(k == keys_per_plan[0] for k in keys_per_plan)

    def test_plan_standard_price_is_the_approved_tier(self):
        # $49 since SIGV2-1211 (was $99). The admin plans screen is staff-only
        # and reads the raw matrix, so it shows the list price for every plan.
        assert CAPABILITY_MATRIX["plan_standard"]["monthly_price_usd"] == 49
        assert CAPABILITY_MATRIX["plan_specialist"]["monthly_price_usd"] == 99

    def test_plan_executive_has_unlimited_sites(self):
        assert CAPABILITY_MATRIX["plan_executive"]["max_sites"] == -1

    def test_can_use_feature_true(self):
        assert can_use_feature("plan_executive", "api_access") is True

    def test_can_use_feature_false(self):
        assert can_use_feature("plan_standard", "api_access") is False

    def test_plan_meets_requirement_uses_hierarchy(self):
        assert plan_meets_requirement("plan_executive", "plan_specialist") is True
        assert plan_meets_requirement("plan_standard", "plan_specialist") is False

    def test_plan_weights_are_ordered(self):
        assert get_plan_weight("plan_starter") < get_plan_weight("plan_standard")
        assert get_plan_weight("plan_standard") < get_plan_weight("plan_specialist")
        assert get_plan_weight("plan_specialist") < get_plan_weight("plan_executive")
        # Executive is the top tier: no canonical plan outranks it.
        assert all(
            get_plan_weight(plan) <= get_plan_weight("plan_executive")
            for plan in plans.CANONICAL_PLAN_TYPES
        )

    def test_can_use_feature_falls_back_to_minimum_plan_hierarchy(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setitem(CAPABILITY_MATRIX["plan_executive"], "api_access", False)
        assert MINIMUM_PLAN_BY_FEATURE["api_access"] == "plan_specialist"
        assert can_use_feature("plan_executive", "api_access") is True

    def test_resolve_plan_alias_requires_canonical_plan_ids(self):
        assert resolve_plan_alias("starter") is None
        assert resolve_plan_alias("pro") is None
        assert resolve_plan_alias("enterprise") is None
        assert resolve_plan_alias("agency") is None

    def test_presentation_entries(self):
        for plan in CAPABILITY_MATRIX:
            assert plan in PLAN_PRESENTATION, f"Missing presentation for {plan}"
            assert "name" in PLAN_PRESENTATION[plan]

    def test_capability_count(self):
        for plan, caps in CAPABILITY_MATRIX.items():
            assert len(caps) >= 30, f"Plan {plan} has only {len(caps)} capabilities"


# ---------------------------------------------------------------------------
# 2. Plan compliance — pricing alignment
# ---------------------------------------------------------------------------

from app.services.compliance.plan_validator import (
    OVERRIDABLE_CAPABILITIES,
    PRICING_CAPABILITY_MATRIX,
    _HAS_DB,
    PlanValidator,
    validate_plan_compliance,
)


class TestPricingAlignment:
    """Verify PRICING_CAPABILITY_MATRIX matches CAPABILITY_MATRIX after fix."""

    def test_api_access_plan_specialist_matches(self):
        """The drift bug should be fixed — both should be True."""
        assert CAPABILITY_MATRIX["plan_specialist"]["api_access"] is True
        assert PRICING_CAPABILITY_MATRIX["plan_specialist"]["api_access"] is True

    def test_validate_plan_compliance_passes(self):
        """After the drift fix, compliance validation should pass."""
        # Should not raise
        validate_plan_compliance()


# ---------------------------------------------------------------------------
# 3. PlanValidator.get_effective_capability
# ---------------------------------------------------------------------------


class TestGetEffectiveCapability:
    """Test override-aware capability resolution.

    SIGV2-1147 narrowed this resolver: an override is applied only for a
    capability in ``OVERRIDABLE_CAPABILITIES``. ``max_audits`` is deliberately
    not one of them (it is read per plan by the audit accounting paths and
    republished on the public pricing catalogue), so the cases below use it to
    pin the plan-value behaviour and use an overridable boolean capability to
    pin the override behaviour. Full coverage of the policy itself lives in
    ``test_workspace_capability_override_policy.py``.
    """

    OVERRIDABLE_CAPABILITY = "can_use_slack_integration"

    def setup_method(self):
        self.validator = PlanValidator()

    def test_returns_base_value_without_workspace(self):
        mock_db = MagicMock()
        result = self.validator.get_effective_capability(mock_db, "plan_standard", "max_audits")
        assert result == 200

    def test_returns_base_value_with_no_override(self):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.first.return_value = None
        result = self.validator.get_effective_capability(
            mock_db, "plan_standard", "max_audits", workspace_id=1
        )
        assert result == 200

    def test_returns_override_value_for_an_overridable_capability(self):
        if not _HAS_DB:
            pytest.skip("Workspace override resolution requires DB-backed plan validator imports")

        mock_override = MagicMock()
        mock_override.override_value = True

        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.first.return_value = mock_override

        assert CAPABILITY_MATRIX["plan_standard"][self.OVERRIDABLE_CAPABILITY] is False
        result = self.validator.get_effective_capability(
            mock_db, "plan_standard", self.OVERRIDABLE_CAPABILITY, workspace_id=1
        )
        assert result is True

    def test_ignores_an_override_on_a_plan_scoped_capability(self):
        """A stored row for a plan-scoped allowance must not alter the answer."""
        mock_override = MagicMock()
        mock_override.override_value = 100

        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_query.filter.return_value.first.return_value = mock_override

        result = self.validator.get_effective_capability(
            mock_db, "plan_standard", "max_audits", workspace_id=1
        )
        assert result == 200

    def test_unknown_plan_returns_none(self):
        mock_db = MagicMock()
        result = self.validator.get_effective_capability(mock_db, "nonexistent_plan", "max_audits")
        assert result is None


# ---------------------------------------------------------------------------
# 4. CAPABILITY_DESCRIPTIONS coverage
# ---------------------------------------------------------------------------


# We import the descriptions dict from admin.py indirectly via importability check
class TestCapabilityDescriptions:
    """Verify the admin descriptions dict covers all capability keys."""

    def test_all_keys_have_descriptions(self):
        # Import lazily to avoid full admin.py boot dependency
        try:
            from admin import CAPABILITY_DESCRIPTIONS
        except Exception:
            pytest.skip("Cannot import admin.CAPABILITY_DESCRIPTIONS in test env")

        sample_keys = set(next(iter(CAPABILITY_MATRIX.values())).keys())
        described = set(CAPABILITY_DESCRIPTIONS.keys())
        missing = sample_keys - described
        assert not missing, f"Missing descriptions for: {missing}"


# ---------------------------------------------------------------------------
# 5. Additive-only guarantee
# ---------------------------------------------------------------------------
#
# The arithmetic guard that used to be asserted here is gone (SIGV2-1147). It
# re-implemented, in the test, a numeric comparison the endpoint made against
# whichever plan happened to be first in CAPABILITY_MATRIX rather than the
# workspace owner's plan, and it covered numeric capabilities that can no
# longer be overridden at all. The additive-only property is now structural:
# every overridable capability is boolean and the endpoint accepts True only.
# The endpoint-level assertions live in
# test_workspace_capability_override_policy.py.


class TestAdditiveGuard:
    """Every overridable capability is boolean, so an override can only grant."""

    def test_overridable_capabilities_are_boolean_on_every_plan(self):
        for capability in OVERRIDABLE_CAPABILITIES:
            for plan, caps in CAPABILITY_MATRIX.items():
                assert isinstance(caps[capability], bool), (
                    f"{plan}.{capability} is not boolean, so 'True only' is no longer "
                    "sufficient to guarantee an override is additive"
                )
