from app.services.compliance.plan_validator import (
    PRICING_CAPABILITY_MATRIX,
    PlanComplianceError,
    validate_plan_compliance,
)


def test_validate_plan_compliance_passes_for_current_matrix() -> None:
    validate_plan_compliance()


def test_validate_plan_compliance_fails_on_pricing_mismatch() -> None:
    mismatched_matrix = {
        plan: capabilities.copy() for plan, capabilities in PRICING_CAPABILITY_MATRIX.items()
    }
    mismatched_matrix["plan_standard"]["geo"] = False

    try:
        validate_plan_compliance(capability_matrix=mismatched_matrix)
    except PlanComplianceError as exc:
        assert "plan='plan_standard', feature='geo'" in str(exc)
    else:
        raise AssertionError("Expected PlanComplianceError for pricing mismatch")
