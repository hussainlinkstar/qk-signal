"""Plan capability configuration for backend feature gating."""

from __future__ import annotations

from typing import Final


CapabilityValue = bool | int
CapabilityMatrix = dict[str, dict[str, CapabilityValue]]
PlanPresentation = dict[str, str]
PlanAliasMap = dict[str, str]
PlanWeightMap = dict[str, int]


TRIAL_DURATION_DAYS: Final[int] = 14
TRIAL_CREDITS: Final[int] = 100
TRIAL_MAX_AUDITS: Final[int] = 5
ENTITLED_SUBSCRIPTION_STATUSES: Final[frozenset[str]] = frozenset({"active", "trialing"})
CANONICAL_PLAN_TYPES: Final[tuple[str, ...]] = (
    "plan_starter",
    "plan_agency_trial",
    "plan_standard",
    "plan_specialist",
    "plan_executive",
)
# Plans that must never appear on an unauthenticated surface.
PRIVATE_PLAN_IDS: Final[frozenset[str]] = frozenset({"plan_agency_trial"})
PUBLIC_PLAN_TYPES: Final[tuple[str, ...]] = tuple(
    plan for plan in CANONICAL_PLAN_TYPES if plan not in PRIVATE_PLAN_IDS
)

CAPABILITY_MATRIX: Final[CapabilityMatrix] = {
    "plan_starter": {
        "monthly_price_usd": 0,
        "credits_per_month": 12,
        "has_advisor_recommendations": False,
        "has_done_for_you_execution": False,
        "has_live_engine_tracking": True,
        "max_sites": 1,
        "max_audits": 1,
        "max_tracked_keywords": 5,
        "seo": True,
        "geo": True,
        "aeo": True,
        "entity_analysis": True,
        "entity_authority": False,
        "has_baseline_geo_visibility_index": True,
        "has_aeo_answerability_score": True,
        "has_core_entity_identity_check": True,
        "has_performance_sync": True,
        "has_pdf_audit_reports": True,
        "has_custom_pricing": False,
        "has_priority_pulse": False,
        "has_high_confidence_mode": False,
        "has_predictive_intent_engine": False,
        "has_semantic_graph_mapping": False,
        "has_entity_enhancement": False,
        "has_brand_integrity_guardrails": False,
        "has_eeat_trust_audit": False,
        "has_dedicated_strategist": False,
        "has_competitor_analysis": False,
        "has_semantic_gap": False,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": False,
        "can_schedule_audits": False,
        "pdf_white_label": False,
        "api_access": False,
        "mcp_access": False,
        "can_export_to_jira": False,
        "can_use_slack_integration": False,
        "can_use_teams_integration": False,
        "can_use_workflow_automations": False,
        "has_parallel_audit_execution": False,
        "has_volume_serp_api": False,
        "has_dedicated_infrastructure": False,
        "has_multi_workspace_federation": False,
        "has_sla_guarantee": False,
        "cms_push": False,
        "lead_widget": False,
        "max_parallel_audits": 1,
        "max_workflows_per_project": 0,
    },
    "plan_agency_trial": {
        "monthly_price_usd": 0,
        "credits_per_month": 0,  # Trial gets a one-time grant, not monthly refresh
        "has_advisor_recommendations": True,
        "has_done_for_you_execution": False,
        "has_live_engine_tracking": True,
        "max_sites": 3,
        "max_audits": 5,
        "max_tracked_keywords": 10,
        "seo": True,
        "geo": True,
        "aeo": True,
        "entity_analysis": True,
        "entity_authority": True,
        "has_baseline_geo_visibility_index": True,
        "has_aeo_answerability_score": True,
        "has_core_entity_identity_check": True,
        "has_performance_sync": True,
        "has_pdf_audit_reports": True,
        "has_custom_pricing": False,
        "has_priority_pulse": True,
        "has_high_confidence_mode": False,
        "has_predictive_intent_engine": True,
        "has_semantic_graph_mapping": True,
        "has_entity_enhancement": True,
        "has_brand_integrity_guardrails": False,
        "has_eeat_trust_audit": False,
        "has_dedicated_strategist": False,
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": False,
        "has_advanced_reporting": True,
        "can_schedule_audits": True,
        "pdf_white_label": False,
        "api_access": True,
        # Deliberately withheld from the trial even though ``api_access`` is
        # granted (SIGV2-1210): the MCP server hands a long-lived read channel
        # to an autonomous agent, and the agreed grant is Specialist and
        # Executive only. This is the reason the key exists separately from
        # ``api_access`` rather than reusing it.
        "mcp_access": False,
        "can_export_to_jira": True,
        "can_use_slack_integration": True,
        "can_use_teams_integration": True,
        "can_use_workflow_automations": True,
        "has_parallel_audit_execution": False,
        "has_volume_serp_api": False,
        "has_dedicated_infrastructure": False,
        "has_multi_workspace_federation": False,
        "has_sla_guarantee": False,
        "has_custom_domain": False,  # CNAME white label blocked on trial
        "cms_push": False,
        "lead_widget": True,
        "max_parallel_audits": 2,
        "max_workflows_per_project": 2,
    },
    "plan_standard": {
        "monthly_price_usd": 49,
        "credits_per_month": 800,
        "has_advisor_recommendations": True,
        "has_done_for_you_execution": False,
        "has_live_engine_tracking": True,
        "max_sites": 1,
        "max_audits": 200,
        "max_tracked_keywords": 10,
        "seo": True,
        "geo": True,
        "aeo": True,
        "entity_analysis": True,
        "entity_authority": False,
        "has_baseline_geo_visibility_index": True,
        "has_aeo_answerability_score": True,
        "has_core_entity_identity_check": True,
        "has_performance_sync": True,
        "has_pdf_audit_reports": True,
        "has_custom_pricing": False,
        "has_priority_pulse": False,
        "has_high_confidence_mode": False,
        "has_predictive_intent_engine": False,
        "has_semantic_graph_mapping": False,
        "has_entity_enhancement": False,
        "has_brand_integrity_guardrails": False,
        "has_eeat_trust_audit": False,
        "has_dedicated_strategist": False,
        "has_competitor_analysis": False,
        "has_semantic_gap": False,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": False,
        "can_schedule_audits": False,
        "pdf_white_label": False,
        "api_access": False,
        "mcp_access": False,
        "can_export_to_jira": False,
        "can_use_slack_integration": False,
        "can_use_teams_integration": False,
        "can_use_workflow_automations": False,
        "has_parallel_audit_execution": False,
        "has_volume_serp_api": False,
        "has_dedicated_infrastructure": False,
        "has_multi_workspace_federation": False,
        "has_sla_guarantee": False,
        "cms_push": False,
        "lead_widget": False,
        "max_parallel_audits": 1,
        "max_workflows_per_project": 0,
    },
    "plan_specialist": {
        "monthly_price_usd": 99,
        "credits_per_month": 3200,
        "has_advisor_recommendations": True,
        "has_done_for_you_execution": False,
        "has_live_engine_tracking": True,
        "max_sites": 10,
        "max_audits": 800,
        "max_tracked_keywords": 50,
        "seo": True,
        "geo": True,
        "aeo": True,
        "entity_analysis": True,
        "entity_authority": True,
        "has_baseline_geo_visibility_index": True,
        "has_aeo_answerability_score": True,
        "has_core_entity_identity_check": True,
        "has_performance_sync": True,
        "has_pdf_audit_reports": True,
        "has_custom_pricing": False,
        "has_priority_pulse": True,
        "has_high_confidence_mode": True,
        "has_predictive_intent_engine": True,
        "has_semantic_graph_mapping": True,
        "has_entity_enhancement": True,
        "has_brand_integrity_guardrails": False,
        "has_eeat_trust_audit": False,
        "has_dedicated_strategist": False,
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": True,
        "can_schedule_audits": True,
        "pdf_white_label": False,
        "api_access": True,
        "mcp_access": True,
        "can_export_to_jira": True,
        "can_use_slack_integration": True,
        "can_use_teams_integration": True,
        "can_use_workflow_automations": True,
        "has_parallel_audit_execution": False,
        "has_volume_serp_api": False,
        "has_dedicated_infrastructure": False,
        "has_multi_workspace_federation": False,
        "has_sla_guarantee": False,
        "cms_push": False,
        "lead_widget": True,
        "max_parallel_audits": 5,
        "max_workflows_per_project": 5,
    },
    "plan_executive": {
        "monthly_price_usd": 999,
        "credits_per_month": 8000,
        "has_advisor_recommendations": True,
        "has_done_for_you_execution": True,
        "has_live_engine_tracking": True,
        "max_sites": -1,
        "max_audits": 2000,
        "max_tracked_keywords": 200,
        "seo": True,
        "geo": True,
        "aeo": True,
        "entity_analysis": True,
        "entity_authority": True,
        "has_baseline_geo_visibility_index": True,
        "has_aeo_answerability_score": True,
        "has_core_entity_identity_check": True,
        "has_performance_sync": True,
        "has_pdf_audit_reports": True,
        "has_custom_pricing": True,
        "has_priority_pulse": True,
        "has_high_confidence_mode": True,
        "has_predictive_intent_engine": True,
        "has_semantic_graph_mapping": True,
        "has_entity_enhancement": True,
        "has_brand_integrity_guardrails": True,
        "has_eeat_trust_audit": True,
        "has_dedicated_strategist": True,
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": True,
        "has_custom_domain": True,
        "has_advanced_reporting": True,
        "can_schedule_audits": True,
        "pdf_white_label": True,
        "api_access": True,
        "mcp_access": True,
        "can_export_to_jira": True,
        "can_use_slack_integration": True,
        "can_use_teams_integration": True,
        "can_use_workflow_automations": True,
        "has_parallel_audit_execution": False,
        "has_volume_serp_api": False,
        "has_dedicated_infrastructure": False,
        "has_multi_workspace_federation": True,
        "has_sla_guarantee": False,
        "cms_push": True,
        "lead_widget": True,
        "max_parallel_audits": 10,
        "max_workflows_per_project": -1,
    },
}

# The scan allowance the agency trial actually grants.
#
# ``trial_service.enforce_trial_audit_limit`` refuses a scan on
# ``audits_used >= max_audits``, and since SIGV2-1024 an exhausted internal
# credit balance no longer refuses anything, so this is the only number a
# trialling customer experiences as their allowance. A scan's internal credit
# cost is variable, so the grant must be stated from this field and never
# derived from a credit figure.
TRIAL_SCAN_ALLOWANCE: Final[int] = int(CAPABILITY_MATRIX["plan_agency_trial"]["max_audits"])

# Capability keys that exist for internal accounting only. The key stays in the
# matrix because internal readers need it (``trial_service``,
# ``plan_credit_grant_service``, ``billing/usage_analytics``), but no
# customer-facing label may be derived from it.
INTERNAL_CAPABILITY_KEYS: Final[frozenset[str]] = frozenset({"credits_per_month"})

# Plans sold on a negotiated price rather than a listed one (SIGV2-1211). The
# approved pricing table reads "Contact Us" in the Executive column, so no
# customer surface may quote it a monthly figure.
#
# The matrix entry keeps its list price on purpose. ``monthly_price_usd`` has
# two internal readers that are not presentation: ``admin_billing_helpers``
# sums it into MRR, and ``stripe_catalog_service`` turns it into a Stripe
# ``unit_amount``. Zeroing or nulling it would drop Executive revenue out of
# the admin figure without saying so, and would ask Stripe to create a $0
# recurring price. So the figure stays and is withheld at the catalogue
# boundary instead, which is the same shape ``UNPUBLISHED_CAPABILITY_KEYS``
# already uses for a live value that may not be stated to a customer.
CUSTOM_PRICED_PLAN_IDS: Final[frozenset[str]] = frozenset({"plan_executive"})

# Bespoke consultancy copy for the Executive card, as Jake worded it.
#
# 🔴 This is copy, never entitlement. Jake's framing is that these entries are
# "an up-sell to customers that we would custom build, not necessarily things
# that are in Executive right now", so each line is a literal string and none
# of it may be derived from a capability key. In particular it must never be
# derived from ``can_use_workflow_automations`` or
# ``max_workflows_per_project`` (unpublished while Automations is Coming Soon,
# SIGV2-1206) or from ``has_white_label``, ``pdf_white_label`` and
# ``has_multi_workspace_federation`` (reclassified as custom build work rather
# than shipped capability). Deriving any of it would re-publish in one move
# what SIGV2-1206 unpublished and what SIGV2-1167 withdrew.
#
# ``tests/test_approved_pricing_tiers.py`` flips all five keys off and asserts
# the copy does not move, which is what keeps that true.
BESPOKE_PLAN_HIGHLIGHTS: Final[dict[str, tuple[str, ...]]] = {
    "plan_executive": (
        "Agent development",
        "Custom workflows",
        "Paid ads / marketing insights",
    ),
}
BESPOKE_PLAN_INCLUSIONS: Final[dict[str, tuple[str, ...]]] = {
    "plan_executive": (
        "Agent deployment and hosting",
        "Workflow automation to fit your processes",
        "AI consultancy and development",
    ),
}

# Capability keys that may never be stated to a customer, whatever a surface
# asks for. This is the availability side of SIGV2-1206: a backend flag is not
# proof a feature ships, so entitlement metadata alone cannot be a saleable
# feature list.
#
# Membership and why:
# * ``can_use_slack_integration``, ``can_use_teams_integration``,
#   ``has_dedicated_strategist``, ``has_done_for_you_execution``: withdrawn
#   from customer surfaces on 6 Oct (SIGV2-1167; SIGV2-1168 removed the two
#   that had nothing behind them).
# * ``cms_push``: CMS delivery is not an active MVP journey; new setup is
#   disabled (SHOW_CMS_FIX_DELIVERY).
# * ``lead_widget``, ``entity_authority``: standalone offers with no approved
#   active MVP journey. The audit-time entity analysis customers actually use
#   is the separate ``entity_analysis`` key and stays publishable.
# * ``can_use_workflow_automations``, ``max_workflows_per_project``:
#   Automations is Coming Soon (SIGV2-1196); neither the flag nor its quota
#   may be advertised until it ships.
# * ``mcp_access``: the MCP server is live and gated (SIGV2-1210), and it is
#   advertised, but through the ``api_access`` row rather than a row of its
#   own. It is the same surface behind the same API key on the same plans, so
#   a second row would read as a second thing to buy. This key therefore
#   stays unpublished to keep it from generating that duplicate row, while
#   remaining a live entitlement gate.
#
# These remain live entitlement gates: the keys stay in CAPABILITY_MATRIX and
# MINIMUM_PLAN_BY_FEATURE and keep granting exactly what they granted. Only
# customer-facing publication is refused here.
UNPUBLISHED_CAPABILITY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "can_use_slack_integration",
        "can_use_teams_integration",
        "has_dedicated_strategist",
        "has_done_for_you_execution",
        "cms_push",
        "lead_widget",
        "entity_authority",
        "can_use_workflow_automations",
        "max_workflows_per_project",
        "mcp_access",
    }
)

# Admin-facing capability labels. The admin plans screen is staff-only, so an
# internal unit may be named here; ``customer_facing_capability_label`` is the
# boundary that keeps it off a customer surface.
CAPABILITY_DESCRIPTIONS: Final[dict[str, str]] = {
    "monthly_price_usd": "Monthly plan price in USD",
    "credits_per_month": "Internal metering allowance per month (not customer-facing)",
    "max_sites": "Maximum tracked sites (-1 = unlimited)",
    "max_audits": "Maximum audits per month",
    "max_tracked_keywords": "Maximum tracked SERP keywords per project (-1 = unlimited)",
    "seo": "SEO audit module",
    "geo": "GEO audit module",
    "aeo": "AEO audit module",
    "entity_analysis": "Entity analysis module",
    "has_baseline_geo_visibility_index": "GEO visibility index",
    "has_aeo_answerability_score": "AEO answerability score",
    "has_core_entity_identity_check": "Core entity identity check",
    "has_performance_sync": "Performance sync monitoring",
    "has_pdf_audit_reports": "PDF audit report generation",
    "has_custom_pricing": "Custom pricing support",
    "has_priority_pulse": "Priority pulse alerts",
    "has_high_confidence_mode": "High-confidence audit mode",
    "has_predictive_intent_engine": "Predictive intent engine",
    "has_semantic_graph_mapping": "Semantic graph mapping",
    "has_entity_enhancement": "Entity enhancement suggestions",
    "has_brand_integrity_guardrails": "Brand integrity guardrails",
    "has_eeat_trust_audit": "E-E-A-T trust audit",
    "has_dedicated_strategist": "Dedicated strategist support",
    "has_advisor_recommendations": "AI recommendations (Advisor action plan)",
    "has_done_for_you_execution": "Done-for-you execution (push fixes to CMS/Jira/Slack)",
    "has_live_engine_tracking": "Live engine tracking (real-engine visibility measurement via OpenRouter)",
    "has_competitor_analysis": "Competitor analysis",
    "has_semantic_gap": "Semantic gap detection",
    "has_white_label": "White-label branding",
    "has_custom_domain": "Custom domain support",
    "has_advanced_reporting": "Advanced reporting dashboards",
    "can_schedule_audits": "Scheduled audit automation",
    "pdf_white_label": "PDF white-label branding",
    # SIGV2-1210: one row covers both halves of the same surface. The MCP
    # server authenticates with the same API key and is granted by the same
    # plans, so splitting it into a second row would imply a second thing to
    # buy. SIGV2-1211 deliberately shipped this row as "API access" because
    # the server did not exist yet; it does now, so the claim and the product
    # land together. ``test_public_plan_catalog`` pins that the two
    # capabilities agree on every public plan, which is what makes the
    # combined wording true rather than merely convenient.
    "api_access": "API & MCP access",
    "mcp_access": "MCP server access for AI agents",
    "can_export_to_jira": "Jira export integration",
    "can_use_slack_integration": "Slack integration",
    "can_use_teams_integration": "Teams integration",
    "can_use_workflow_automations": "Workflow automations",
    "entity_authority": "Entity authority module",
    "has_parallel_audit_execution": "Parallel audit execution",
    "has_volume_serp_api": "Volume SERP API access",
    "has_dedicated_infrastructure": "Dedicated infrastructure",
    "has_multi_workspace_federation": "Multiple workspaces",
    "has_sla_guarantee": "99.9% SLA guarantee",
    "cms_push": "CMS push integration",
    "lead_widget": "Lead capture widget",
    "max_parallel_audits": "Max parallel audits",
    "max_workflows_per_project": "Max workflows per project (-1 = unlimited)",
}

PLAN_PRESENTATION: Final[dict[str, PlanPresentation]] = {
    "plan_starter": {
        "name": "Starter",
        "description": "Full SEO, AEO and GEO audit, one free scan per month.",
        "highlight": "The full platform, free.",
        "color": "teal",
    },
    "plan_agency_trial": {
        "name": "Agency Trial",
        "description": (
            f"{TRIAL_DURATION_DAYS}-day free trial with {TRIAL_SCAN_ALLOWANCE} full scans."
        ),
        "highlight": "The full platform on trial.",
        "color": "emerald",
    },
    "plan_standard": {
        "name": "Standard",
        "description": "Daily AI visibility monitoring for a single brand.",
        "highlight": "For solo operators.",
        "color": "slate",
    },
    "plan_specialist": {
        "name": "Specialist",
        "description": "Advanced monitoring, automation and competitor intelligence.",
        "highlight": "For scaling teams.",
        "color": "primary",
    },
    "plan_executive": {
        "name": "Executive",
        # The dedicated strategist was withdrawn from the customer-facing plan
        # comparison on 6 Oct (SIGV2-1167) as not offered or not yet active.
        # This description is served on the unauthenticated public catalog, so
        # leaving the clause here would promise a prospect what the product has
        # stopped showing a paying customer. The entitlement key itself is
        # untouched (SIGV2-1168).
        "description": "Custom agent development and unlimited sites.",
        "highlight": "For multi-brand agencies.",
        "color": "indigo",
        # The approved pricing table reads "Contact Us" in this column
        # (SIGV2-1211), so Executive leaves the self-service checkout path.
        # ``billing/router._raise_for_non_self_service_plan`` already refuses a
        # checkout for a plan whose CTA is "contact"; until now that guard was
        # dormant because nothing set the field. Setting it here is what makes
        # the refusal and the card's "Contact us" button the same decision
        # rather than two that can drift.
        "cta": "contact",
    },
}

# The CTA a plan gets when its presentation entry names none: ordinary
# self-service checkout.
DEFAULT_PLAN_CTA: Final[str] = "self_serve"

PLAN_ALIASES: Final[PlanAliasMap] = {plan: plan for plan in CANONICAL_PLAN_TYPES}

PLAN_REQUIREMENT_ALIASES: Final[PlanAliasMap] = {
    "plan_starter": "plan_starter",
    "trial": "plan_agency_trial",
    "agency trial": "plan_agency_trial",
    "plan_agency_trial": "plan_agency_trial",
    "neural core": "plan_standard",
    "plan_standard": "plan_standard",
    "synapse pro": "plan_specialist",
    "plan_specialist": "plan_specialist",
    "singularity elite": "plan_executive",
    "plan_executive": "plan_executive",
}

PLAN_WEIGHTS: Final[PlanWeightMap] = {
    "plan_starter": 3,
    "plan_agency_trial": 5,
    "plan_standard": 10,
    "plan_specialist": 20,
    "plan_executive": 30,
}

MINIMUM_PLAN_BY_FEATURE: Final[dict[str, str]] = {
    # The three audit modules and basic entity analysis are included from the
    # free Starter plan. They are declared here so any surface that states a
    # required plan for them (a lock card, an upgrade prompt) reads the same
    # source of truth as every other capability instead of hand-writing one.
    "seo": "plan_starter",
    "geo": "plan_starter",
    "aeo": "plan_starter",
    "entity_analysis": "plan_starter",
    "has_performance_sync": "plan_starter",
    "has_pdf_audit_reports": "plan_starter",
    "has_advisor_recommendations": "plan_standard",
    "entity_authority": "plan_specialist",
    "has_priority_pulse": "plan_specialist",
    "has_predictive_intent_engine": "plan_specialist",
    "has_semantic_graph_mapping": "plan_specialist",
    "has_entity_enhancement": "plan_specialist",
    "has_competitor_analysis": "plan_specialist",
    "has_semantic_gap": "plan_specialist",
    "has_advanced_reporting": "plan_specialist",
    "can_schedule_audits": "plan_specialist",
    "api_access": "plan_specialist",
    "mcp_access": "plan_specialist",
    "can_export_to_jira": "plan_specialist",
    "can_use_slack_integration": "plan_specialist",
    "can_use_teams_integration": "plan_specialist",
    "can_use_workflow_automations": "plan_specialist",
    "lead_widget": "plan_specialist",
    "has_custom_pricing": "plan_executive",
    "has_brand_integrity_guardrails": "plan_executive",
    "has_eeat_trust_audit": "plan_executive",
    "has_dedicated_strategist": "plan_executive",
    "has_done_for_you_execution": "plan_executive",
    "has_live_engine_tracking": "plan_starter",
    "has_high_confidence_mode": "plan_specialist",
    "has_white_label": "plan_executive",
    "has_custom_domain": "plan_executive",
    "pdf_white_label": "plan_executive",
    "has_multi_workspace_federation": "plan_executive",
    "cms_push": "plan_executive",
}


PLANS: Final[dict[str, dict[str, list[str] | dict[str, CapabilityValue]]]] = {
    plan: {
        "functionalities": [
            feature
            for feature, enabled in capabilities.items()
            if isinstance(enabled, bool) and enabled
        ],
        "capabilities": capabilities,
    }
    for plan, capabilities in CAPABILITY_MATRIX.items()
}

# Backward-compatible alias.
FEATURE_FLAGS: Final[CapabilityMatrix] = CAPABILITY_MATRIX


def get_plan_capabilities(plan: str) -> dict[str, CapabilityValue]:
    """Return capability flags for a plan, defaulting to an empty matrix."""
    return CAPABILITY_MATRIX.get(plan, {})


def get_plan_functionalities(plan: str) -> list[str]:
    """Return enabled functionalities for a plan from the capability matrix."""
    plan_config = PLANS.get(plan, {})
    functionalities = plan_config.get("functionalities", [])
    return list(functionalities)


def list_plan_functionalities() -> dict[str, list[str]]:
    """Return enabled functionalities for each plan from the capability matrix."""
    return {plan: get_plan_functionalities(plan) for plan in CAPABILITY_MATRIX}


def resolve_plan_requirement_alias(plan: str | None) -> str | None:
    if not isinstance(plan, str):
        return None
    normalized = plan.strip().lower()
    if not normalized:
        return None
    return PLAN_REQUIREMENT_ALIASES.get(normalized)


def get_plan_weight(plan: str | None) -> int:
    resolved_plan = resolve_plan_requirement_alias(plan) or resolve_plan_alias(plan)
    if not resolved_plan:
        return 0
    return PLAN_WEIGHTS.get(resolved_plan, 0)


def plan_meets_requirement(plan: str | None, required_plan: str | None) -> bool:
    return get_plan_weight(plan) >= get_plan_weight(required_plan)


def can_use_feature(plan: str, feature: str) -> bool:
    """Return whether a plan allows a given feature."""
    if bool(get_plan_capabilities(plan).get(feature, False)):
        return True

    minimum_plan = MINIMUM_PLAN_BY_FEATURE.get(feature)
    if minimum_plan is None:
        return False
    return plan_meets_requirement(plan, minimum_plan)


def resolve_plan_alias(plan: str | None) -> str | None:
    """Return an exact canonical runtime plan ID, without compatibility aliases."""
    if not isinstance(plan, str):
        return None
    return PLAN_ALIASES.get(plan)


def resolve_entitled_subscription_plan(user_or_subscription: object | None) -> str | None:
    """Return a subscription plan only when its billing status grants access.

    The input may be a user-like object with a ``subscription`` attribute or a
    subscription-like object itself. Billing records in pending, delinquent,
    canceled, or any other non-entitled status never contribute product access.
    """
    if user_or_subscription is None:
        return None

    subscription = getattr(user_or_subscription, "subscription", None)
    if subscription is None:
        subscription = user_or_subscription

    status = getattr(subscription, "status", None)
    if not isinstance(status, str) or status.strip().lower() not in ENTITLED_SUBSCRIPTION_STATUSES:
        return None

    plan_type = getattr(subscription, "plan_type", None)
    if not isinstance(plan_type, str) or plan_type not in CANONICAL_PLAN_TYPES:
        return None
    return plan_type


def customer_facing_capability_label(key: str) -> str | None:
    """Return a label that may be shown to a customer, or ``None`` if none exists.

    Internal accounting keys have no customer-facing label, so a customer
    surface skips them instead of falling back to a titled key name. Credits
    stay the internal unit; scans are what they are told about.

    SIGV2-1206: the same is true of any key without a curated description and
    of every key in ``UNPUBLISHED_CAPABILITY_KEYS``. A titled flag name is not
    copy, and an entitlement flag is not proof the feature is offered, so a
    new backend flag can never publish itself through this function.
    """
    if key in INTERNAL_CAPABILITY_KEYS or key in UNPUBLISHED_CAPABILITY_KEYS:
        return None
    return CAPABILITY_DESCRIPTIONS.get(key)


def diff_capabilities(current_plan: str, target_plan: str) -> dict[str, list[str]]:
    """Compare two plans and return human-readable gained/lost features."""
    current_caps = get_plan_capabilities(current_plan)
    target_caps = get_plan_capabilities(target_plan)
    if not current_caps or not target_caps:
        return {"gained": [], "lost": []}

    _SKIP_KEYS = {
        "monthly_price_usd",
        "credits_per_month",
        "max_sites",
        "max_audits",
        "max_parallel_audits",
        "max_workflows_per_project",
        "max_tracked_keywords",
    }
    gained: list[str] = []
    lost: list[str] = []

    for key in sorted(set(current_caps) | set(target_caps)):
        if key in _SKIP_KEYS:
            continue
        cur = current_caps.get(key, False)
        tgt = target_caps.get(key, False)
        if cur == tgt:
            continue
        label = customer_facing_capability_label(key)
        if label is None:
            continue
        if isinstance(cur, bool) and isinstance(tgt, bool):
            if tgt and not cur:
                gained.append(label)
            elif cur and not tgt:
                lost.append(label)
        elif isinstance(cur, (int, float)) and isinstance(tgt, (int, float)):
            if tgt > cur:
                gained.append(label)
            elif cur > tgt:
                lost.append(label)

    return {"gained": gained, "lost": lost}


def get_plan_monthly_price_usd(plan: str | None) -> int:
    resolved_plan = resolve_plan_alias(plan)
    if not resolved_plan:
        return 0
    capabilities = get_plan_capabilities(resolved_plan)
    monthly_price = capabilities.get("monthly_price_usd", 0)
    return int(monthly_price) if isinstance(monthly_price, int) else 0


def is_custom_priced(plan: str | None) -> bool:
    """Whether a plan's price is negotiated rather than listed.

    Resolved through the canonical alias map so a compatibility spelling
    cannot route around the withholding.
    """
    resolved_plan = resolve_plan_alias(plan)
    if resolved_plan is None:
        return False
    return resolved_plan in CUSTOM_PRICED_PLAN_IDS


def plan_cta(plan: str | None) -> str:
    """The call to action a plan's card should offer."""
    resolved_plan = resolve_plan_alias(plan)
    if resolved_plan is None:
        return DEFAULT_PLAN_CTA
    cta = PLAN_PRESENTATION.get(resolved_plan, {}).get("cta")
    return cta if isinstance(cta, str) and cta.strip() else DEFAULT_PLAN_CTA


def bespoke_plan_highlights(plan: str | None) -> tuple[str, ...]:
    """Literal up-sell highlights for a plan, or empty when it has none.

    Never derived from ``CAPABILITY_MATRIX``. See ``BESPOKE_PLAN_HIGHLIGHTS``.
    """
    resolved_plan = resolve_plan_alias(plan)
    if resolved_plan is None:
        return ()
    return BESPOKE_PLAN_HIGHLIGHTS.get(resolved_plan, ())


def bespoke_plan_inclusions(plan: str | None) -> tuple[str, ...]:
    """Literal up-sell inclusions for a plan, or empty when it has none.

    Never derived from ``CAPABILITY_MATRIX``. See ``BESPOKE_PLAN_INCLUSIONS``.
    """
    resolved_plan = resolve_plan_alias(plan)
    if resolved_plan is None:
        return ()
    return BESPOKE_PLAN_INCLUSIONS.get(resolved_plan, ())


def customer_facing_monthly_price_usd(plan: str | None) -> int | None:
    """The monthly figure a customer may be shown, or ``None`` when negotiated.

    ``None`` and not ``0``: the billing card, the comparison header and the
    marketing site all read a zero amount as "Free", so a zeroed price would
    advertise the most expensive plan as the cheapest. Internal readers want
    the list price and call ``get_plan_monthly_price_usd`` instead.
    """
    if is_custom_priced(plan):
        return None
    resolved_plan = resolve_plan_alias(plan)
    if resolved_plan is None:
        return None
    monthly_price = get_plan_capabilities(resolved_plan).get("monthly_price_usd")
    if isinstance(monthly_price, bool) or not isinstance(monthly_price, int):
        return None
    return monthly_price


def _format_site_allowance(max_sites: int) -> str:
    if max_sites < 0:
        return "Unlimited sites"
    site_label = "site" if max_sites == 1 else "sites"
    return f"Up to {max_sites} {site_label}"


def _format_audit_allowance(max_audits: int) -> str:
    if max_audits < 0:
        return "Unlimited audits/mo"
    # Starter allows exactly one, which read as "1 audits/mo" without the
    # singular branch.
    noun = "audit" if max_audits == 1 else "audits"
    return f"{max_audits} {noun}/mo"


def _format_parallel_audit_allowance(max_parallel_audits: int) -> str:
    if max_parallel_audits <= 0:
        return "Parallel audit execution"
    return f"Up to {max_parallel_audits} concurrent audits"


def build_plan_feature_list(plan: str) -> list[str]:
    """Marketing highlights for a plan, served on the public plan catalog.

    Four capabilities are deliberately never stated here, no matter what the
    matrix grants: ``has_dedicated_strategist``, ``has_done_for_you_execution``,
    ``can_use_slack_integration`` and ``can_use_teams_integration``. All four
    were withdrawn from the customer-facing plan comparison on 6 Oct
    (SIGV2-1167) as not offered or not yet active, and this list reaches an
    anonymous prospect through ``/api/v1/billing/plans/public``, so advertising
    them here would contradict the product. They remain live entitlement gates
    (SIGV2-1168): the keys stay in ``CAPABILITY_MATRIX`` and nothing about who
    may use them changes.

    This is marketing copy, not an entitlement source. A consumer that needs to
    know whether a plan includes a capability reads the published entitlement
    matrix (``services/public_plan_catalog.py``), because a highlight list
    omits capabilities a plan genuinely has: Specialist does not mention PDF
    reports, yet ``MINIMUM_PLAN_BY_FEATURE`` grants them from Starter.

    SIGV2-1211: a plan with bespoke inclusions states its scan allowance and
    then that literal copy, and derives nothing else. Executive's derived
    lines were "Multiple workspaces" and "White-label workspace and PDF
    delivery", read straight off ``has_multi_workspace_federation`` and
    ``has_white_label``; Jake reclassified both as custom build work, so
    continuing to derive them would advertise as shipped what the product now
    offers as consultancy. The allowance line stays derived because it is a
    real, enforced figure (``scan_allowance_service`` counts against it).
    """
    capabilities = get_plan_capabilities(plan)
    if not capabilities:
        return []

    features: list[str] = []
    max_audits = int(capabilities.get("max_audits", 0))
    max_sites = int(capabilities.get("max_sites", 0))
    features.append(_format_audit_allowance(max_audits))

    bespoke = bespoke_plan_inclusions(plan)
    if bespoke:
        return [features[0], *bespoke]

    features.append(_format_site_allowance(max_sites))

    if capabilities.get("has_parallel_audit_execution"):
        features.append(
            _format_parallel_audit_allowance(int(capabilities.get("max_parallel_audits", 0)))
        )
    if capabilities.get("has_sla_guarantee"):
        features.append("99.9% SLA")
    if capabilities.get("has_multi_workspace_federation"):
        features.append("Multiple workspaces")
    if capabilities.get("has_white_label"):
        features.append("White-label delivery")
    if capabilities.get("api_access"):
        features.append("API access")
    # No ``has_dedicated_strategist`` highlight: withdrawn from customer
    # surfaces by SIGV2-1167, and this list is published unauthenticated. The
    # same goes for done-for-you execution and the Slack/Teams integrations,
    # which is why none of the three is read here either. See the docstring.
    if capabilities.get("has_competitor_analysis") and capabilities.get("has_semantic_gap"):
        features.append("Competitor & gap analysis")
    elif capabilities.get("has_competitor_analysis"):
        features.append("Competitor analysis")

    if capabilities.get("has_advanced_reporting"):
        features.append("Advanced reporting")

    if capabilities.get("can_schedule_audits"):
        features.append("Scheduled audits")

    if capabilities.get("has_pdf_audit_reports"):
        features.append("PDF audit reports")
    if capabilities.get("has_performance_sync"):
        features.append("Performance monitoring")

    unique_features: list[str] = []
    for feature in features:
        if feature not in unique_features:
            unique_features.append(feature)

    return unique_features[:7]


def get_plan_catalog_entry(
    plan: str,
) -> dict[str, str | bool | float | None | list[str] | dict[str, CapabilityValue | None]]:
    """The customer-facing projection of a plan.

    This is the boundary that withholds a negotiated price (SIGV2-1211). The
    raw ``CAPABILITY_MATRIX`` entry keeps Executive's list price for MRR and
    Stripe; what leaves here carries ``None`` instead, together with the
    ``custom_priced`` and ``cta`` flags a surface needs to render "Custom
    pricing" and a contact button rather than a figure and a Subscribe button.
    """
    capabilities = get_plan_capabilities(plan)
    presentation = PLAN_PRESENTATION.get(plan, {})
    custom_priced = is_custom_priced(plan)
    monthly_price = customer_facing_monthly_price_usd(plan)
    if custom_priced and capabilities:
        # A copy, so the shared matrix is never mutated by being read.
        capabilities = {**capabilities, "monthly_price_usd": None}
    annual_price_usd = None
    if isinstance(monthly_price, (int, float)) and monthly_price > 0:
        from billing.config import ANNUAL_DISCOUNT_PCT

        annual_price_usd = round(monthly_price * 12 * (1 - ANNUAL_DISCOUNT_PCT / 100), 2)
    return {
        "id": plan,
        "name": presentation.get("name", plan.replace("_", " ").title()),
        "description": presentation.get("description", ""),
        "highlight": presentation.get("highlight", ""),
        "color": presentation.get("color", "slate"),
        "features": build_plan_feature_list(plan),
        "capabilities": capabilities,
        "annual_price_usd": annual_price_usd,
        "custom_priced": custom_priced,
        "cta": plan_cta(plan),
        "bespoke_highlights": list(bespoke_plan_highlights(plan)),
    }
