"""Configuration package for backend app."""

from .plans import (
    CAPABILITY_MATRIX,
    FEATURE_FLAGS,
    MINIMUM_PLAN_BY_FEATURE,
    PLANS,
    can_use_feature,
    get_plan_capabilities,
    get_plan_functionalities,
    get_plan_weight,
    list_plan_functionalities,
    plan_meets_requirement,
    resolve_plan_requirement_alias,
)

__all__ = [
    "CAPABILITY_MATRIX",
    "FEATURE_FLAGS",
    "MINIMUM_PLAN_BY_FEATURE",
    "PLANS",
    "can_use_feature",
    "get_plan_capabilities",
    "get_plan_functionalities",
    "get_plan_weight",
    "list_plan_functionalities",
    "plan_meets_requirement",
    "resolve_plan_requirement_alias",
]
