"""Validation utilities that keep plan gating aligned with pricing promises."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    CAPABILITY_MATRIX,
    PLANS,
    CapabilityValue,
    get_plan_capabilities,
    resolve_entitled_subscription_plan,
)

try:
    from sqlalchemy import or_
    from sqlalchemy.orm import Session, object_session
    import models as _models

    _HAS_DB = True
except Exception:  # noqa: BLE001
    _HAS_DB = False


PLAN_ORDER = CANONICAL_PLAN_TYPES

# Plans that sit outside the linear paid upgrade ladder. The 14-day agency
# trial deliberately unlocks premium (executive-tier) capabilities even though
# it is free / low-weight, so it must be excluded from the monotonic
# "no premium feature on a lower plan only" leakage check.
NON_HIERARCHY_PLANS: frozenset[str] = frozenset({"plan_agency_trial"})

# Capabilities promised on the public pricing pages.
PRICING_CAPABILITY_MATRIX: dict[str, dict[str, CapabilityValue]] = {
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
        "credits_per_month": 0,
        "has_advisor_recommendations": True,
        "has_done_for_you_execution": False,
        "has_live_engine_tracking": True,
        "max_sites": 3,
        "max_audits": 5,
        "max_tracked_keywords": 10,
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": True,
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
        "can_schedule_audits": True,
        "pdf_white_label": False,
        "api_access": True,
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
        "has_competitor_analysis": False,
        "has_semantic_gap": False,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": False,
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
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": False,
        "has_custom_domain": False,
        "has_advanced_reporting": True,
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
        "has_competitor_analysis": True,
        "has_semantic_gap": True,
        "has_white_label": True,
        "has_custom_domain": True,
        "has_advanced_reporting": True,
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


# ---------------------------------------------------------------------------
# Workspace capability override policy (SIGV2-1147)
# ---------------------------------------------------------------------------
#
# THE RULE, in one sentence: a ``WorkspaceCapabilityOverride`` row is honoured
# only for a capability listed in ``OVERRIDABLE_CAPABILITIES``, and the admin
# surface refuses to write a row for anything else.
#
# Why a named subset and not "every gate consults the override table":
#
# 1. There are two entitlement chokepoints in this backend, not one.
#    ``app.config.plans.can_use_feature(plan, feature)`` is keyed by *plan*
#    and is a pure function; it cannot see a workspace, a user or an override,
#    and its signature is shared by roughly forty call sites. Overrides are
#    keyed by *workspace*. The two do not compose. Only the user-keyed
#    ``PlanValidator.has_feature`` chokepoint can resolve an override at all,
#    so a capability whose gating passes through ``can_use_feature`` anywhere
#    would be granted by the API and refused by the worker, which is worse
#    than being uniformly inert.
# 2. Several capabilities have no runtime reader whatsoever. Granting them
#    cannot change behaviour because nothing asks. ``has_dedicated_strategist``,
#    ``has_sla_guarantee`` and ``has_custom_pricing`` are commercial
#    arrangements, not code paths. The worked example used to be
#    ``has_custom_ai_model_routing``, whose gate claimed an admin could grant
#    it per workspace while the branch was unreachable (SIGV2-1139); the key
#    was deleted outright in SIGV2-1120 rather than left inert, because a key
#    nothing reads still reads to the next person as a capability that exists.
# 3. ``monthly_price_usd`` and ``credits_per_month`` are plan metadata consumed
#    plan-scoped by Stripe catalogue sync, MRR reporting, the public pricing
#    catalogue and the monthly credit grant. A per-workspace row cannot change
#    a Stripe price and must not be allowed to look as though it can.
#
# Scope note that belongs on the record: an override is written against a
# workspace, but every gate that can honour one receives a *user*. Entitlement
# in this product is user-scoped (the subscription hangs off ``User``) and the
# admin surface already derives a workspace's plan from its owner's
# subscription, so an enforced override grants the capability to the workspace
# owner. An owner holding several workspaces therefore receives the grant on
# all of them. All three currently overridable capabilities are user-scoped
# features, so that is the intended effect rather than a leak, but a future
# addition to the set must re-check this.

# Not capabilities: plan price and the included credit allowance.
PRICING_METADATA_CAPABILITIES: frozenset[str] = frozenset(
    {
        "monthly_price_usd",
        "credits_per_month",
    }
)

# Numeric allowances. Read plan-scoped by the audit/site/workflow/keyword
# accounting paths and republished on the public pricing catalogue, so a
# per-workspace value would disagree with itself depending on which reader ran.
PLAN_SCOPED_LIMIT_CAPABILITIES: frozenset[str] = frozenset(
    {
        "max_sites",
        "max_audits",
        "max_parallel_audits",
        "max_workflows_per_project",
        "max_tracked_keywords",
    }
)

# Boolean capabilities that no runtime gate reads. Either the module is always
# on (the audit dimensions and the baseline scores), or the capability
# describes something bought outside the product (a strategist, an SLA,
# negotiated pricing), or the gate that once read it has been deleted.
UNGATED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "seo",
        "geo",
        "aeo",
        "entity_analysis",
        "has_baseline_geo_visibility_index",
        "has_aeo_answerability_score",
        "has_core_entity_identity_check",
        "has_custom_pricing",
        "has_priority_pulse",
        "has_dedicated_strategist",
        "has_custom_domain",
        "has_parallel_audit_execution",
        "has_volume_serp_api",
        "has_dedicated_infrastructure",
        "has_sla_guarantee",
    }
)

# Boolean capabilities gated, at least partly, through the plan-keyed
# ``can_use_feature`` chokepoint. Honouring an override for these would grant
# the capability at one enforcement point and refuse it at another.
PLAN_KEYED_GATE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "api_access",
        # SIGV2-1210: read by ``can_use_feature`` at the MCP endpoint's plan
        # gate, which receives an API key principal and no workspace, so a
        # per-workspace row could never be resolved there.
        "mcp_access",
        "can_export_to_jira",
        "can_schedule_audits",
        "can_use_workflow_automations",
        "cms_push",
        "entity_authority",
        "has_advanced_reporting",
        "has_brand_integrity_guardrails",
        "has_competitor_analysis",
        "has_done_for_you_execution",
        "has_eeat_trust_audit",
        "has_entity_enhancement",
        "has_high_confidence_mode",
        "has_multi_workspace_federation",
        "has_performance_sync",
        "has_predictive_intent_engine",
        "has_semantic_gap",
        "has_semantic_graph_mapping",
        "has_white_label",
        "lead_widget",
        "pdf_white_label",
    }
)

# Boolean capabilities every canonical plan already grants. An override can
# only widen, and there is nothing left to widen.
UNIVERSALLY_GRANTED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "has_live_engine_tracking",
        "has_pdf_audit_reports",
    }
)

# The escape hatch. Boolean, withheld by at least one plan, and gated solely
# through ``PlanValidator.has_feature``, so one enforced decision covers every
# enforcement point.
OVERRIDABLE_CAPABILITIES: frozenset[str] = frozenset(
    {
        "can_use_slack_integration",
        "can_use_teams_integration",
        "has_advisor_recommendations",
    }
)


class OverrideEnforcement(NamedTuple):
    """Verdict on whether a workspace override for ``capability`` does anything."""

    capability: str
    is_enforced: bool
    reason: str


def _is_granted_by_every_plan(capability: str) -> bool:
    return all(
        CAPABILITY_MATRIX.get(plan, {}).get(capability) is True for plan in CANONICAL_PLAN_TYPES
    )


def describe_override_enforcement(capability: str) -> OverrideEnforcement:
    """Return whether a workspace override for ``capability`` is enforced, and why.

    The ``reason`` is written to be shown to the administrator who is about to
    create the row, so it states the consequence rather than the taxonomy.
    """
    known_keys = set(next(iter(CAPABILITY_MATRIX.values()), {}))
    if capability not in known_keys:
        return OverrideEnforcement(
            capability,
            False,
            "No plan defines this capability, so no gate can read it.",
        )

    if capability in PRICING_METADATA_CAPABILITIES:
        return OverrideEnforcement(
            capability,
            False,
            (
                "This is plan billing metadata, not an entitlement gate. It is read "
                "per plan by Stripe catalogue sync, revenue reporting and the credit "
                "grant, none of which can see a workspace row."
            ),
        )

    if capability in PLAN_SCOPED_LIMIT_CAPABILITIES:
        return OverrideEnforcement(
            capability,
            False,
            (
                "This allowance is read per plan by the audit, site, workflow and "
                "keyword accounting paths and republished on the public pricing catalogue, "
                "so a per-workspace value would not be applied consistently."
            ),
        )

    if capability in UNGATED_CAPABILITIES:
        return OverrideEnforcement(
            capability,
            False,
            (
                "No runtime gate reads this capability, so granting it cannot change "
                "what the product does."
            ),
        )

    if _is_granted_by_every_plan(capability):
        return OverrideEnforcement(
            capability,
            False,
            "Every plan already grants this capability, so there is nothing to grant.",
        )

    if capability in PLAN_KEYED_GATE_CAPABILITIES:
        return OverrideEnforcement(
            capability,
            False,
            (
                "This capability is gated per plan rather than per workspace, so an "
                "override would be honoured at some enforcement points and ignored at "
                "others. Change the customer's plan instead."
            ),
        )

    if capability in OVERRIDABLE_CAPABILITIES:
        return OverrideEnforcement(
            capability,
            True,
            "Enforced: granting this capability unlocks it for the workspace owner.",
        )

    return OverrideEnforcement(
        capability,
        False,
        (
            "This capability has not been reviewed for per-workspace overrides. "
            "Classify it in plan_validator.py before granting it."
        ),
    )


def is_overridable_capability(capability: str) -> bool:
    """Return whether a workspace override for ``capability`` is enforced at runtime."""
    return describe_override_enforcement(capability).is_enforced


def capability_override_policy() -> dict[str, OverrideEnforcement]:
    """Return the enforcement verdict for every capability the plan matrix defines."""
    return {
        capability: describe_override_enforcement(capability)
        for capability in next(iter(CAPABILITY_MATRIX.values()), {})
    }


class PlanComplianceError(ValueError):
    """Raised when the plan matrix violates compliance requirements."""


class PlanValidator:
    """Runtime validator used by API routes for feature gating decisions."""

    def normalize_plan_type(self, plan: str | None) -> str | None:
        if isinstance(plan, str) and plan in CANONICAL_PLAN_TYPES:
            return plan
        return None

    def resolve_subscription_plan(self, user: object | None) -> str:
        if user is None:
            return "plan_starter"

        plan_type = resolve_entitled_subscription_plan(user)
        normalized = self.normalize_plan_type(plan_type)
        if normalized:
            return normalized
        # Fall back to trial_plan for Explorer and active trials
        trial_plan = getattr(user, "trial_plan", None)
        trial_normalized = self.normalize_plan_type(trial_plan)
        if trial_normalized:
            return trial_normalized
        return "plan_starter"

    def get_capabilities_for_user(self, user: object | None) -> dict[str, CapabilityValue]:
        return get_plan_capabilities(self.resolve_subscription_plan(user))

    def has_feature(
        self,
        user: object | None,
        feature_key: str,
        *,
        db: "Session | None" = None,
    ) -> bool:
        """Return whether ``user`` may use ``feature_key``.

        The plan matrix decides first. If the plan withholds the capability and
        the capability is one of ``OVERRIDABLE_CAPABILITIES``, an active
        ``WorkspaceCapabilityOverride`` on a workspace this user owns grants it
        (SIGV2-1147). Capabilities outside that set are decided by the matrix
        alone, and the admin surface refuses to write an override row for them,
        so there is no silently ignored grant.

        The override lookup runs only on the denial path and only for a
        reviewed capability, so a plan that already grants the capability costs
        no query. ``db`` may be passed explicitly; otherwise the session the
        ``user`` instance is already attached to is used, and when there is
        none the matrix verdict stands.
        """
        capabilities = self.get_capabilities_for_user(user)
        if bool(capabilities.get(feature_key, False)):
            return True
        if feature_key not in OVERRIDABLE_CAPABILITIES:
            return False
        return self._has_override_grant(user, feature_key, db=db)

    def _resolve_override_session(
        self,
        user: object | None,
        db: "Session | None",
    ) -> "Session | None":
        if db is not None:
            return db
        if not _HAS_DB or user is None:
            return None
        try:
            return object_session(user)
        except Exception:  # noqa: BLE001
            return None

    def _has_override_grant(
        self,
        user: object | None,
        feature_key: str,
        *,
        db: "Session | None" = None,
    ) -> bool:
        """Return True when an owned workspace holds an active grant for ``feature_key``.

        Any failure to resolve the override is treated as "no grant". This is
        an entitlement check, so it fails closed rather than raising out of a
        gate.
        """
        session = self._resolve_override_session(user, db)
        user_id = getattr(user, "id", None)
        if session is None or not isinstance(user_id, int):
            return False

        from datetime import datetime, timezone as tz

        now = datetime.now(tz.utc)
        try:
            override = (
                session.query(_models.WorkspaceCapabilityOverride)
                .join(
                    _models.Workspace,
                    _models.Workspace.id == _models.WorkspaceCapabilityOverride.workspace_id,
                )
                .filter(
                    _models.Workspace.owner_id == user_id,
                    _models.WorkspaceCapabilityOverride.capability_key == feature_key,
                    or_(
                        _models.WorkspaceCapabilityOverride.expires_at.is_(None),
                        _models.WorkspaceCapabilityOverride.expires_at > now,
                    ),
                )
                .first()
            )
        except Exception:  # noqa: BLE001
            return False
        return override is not None and override.override_value is True

    def is_basic_plan(self, user: object | None) -> bool:
        return self.resolve_subscription_plan(user) in {"plan_starter", "plan_standard"}

    def can_schedule_audits(self, user: object | None) -> bool:
        return self.has_feature(user, "can_schedule_audits")

    def site_limit_for_user(self, user: object | None) -> int | None:
        max_sites = self.get_capabilities_for_user(user).get("max_sites")
        if not isinstance(max_sites, int):
            return None
        return max_sites

    # --- Override-aware resolution (TASK_ADMIN-06) ---

    def get_effective_capability(
        self,
        db: "Session",
        plan_name: str,
        capability: str,
        workspace_id: int | None = None,
    ) -> CapabilityValue | None:
        """Return the capability value for a workspace, applying an enforced override.

        An override is applied only when ``describe_override_enforcement``
        reports the capability as enforced (SIGV2-1147). For every other
        capability this returns the plan matrix value, which is what the
        runtime gates do, so this helper cannot report an entitlement the
        product will not honour. Admin callers that need to show a stored but
        unenforced row should read the row and the policy verdict separately.
        """
        base_value = CAPABILITY_MATRIX.get(plan_name, {}).get(capability)
        if not _HAS_DB or workspace_id is None:
            return base_value
        if not is_overridable_capability(capability):
            return base_value
        from datetime import datetime, timezone as tz

        now = datetime.now(tz.utc)
        override = (
            db.query(_models.WorkspaceCapabilityOverride)
            .filter(
                _models.WorkspaceCapabilityOverride.workspace_id == workspace_id,
                _models.WorkspaceCapabilityOverride.capability_key == capability,
                or_(
                    _models.WorkspaceCapabilityOverride.expires_at.is_(None),
                    _models.WorkspaceCapabilityOverride.expires_at > now,
                ),
            )
            .first()
        )
        if override is not None:
            return override.override_value
        return base_value


def _matrix_for_comparison(
    matrix: dict[str, dict[str, CapabilityValue]],
    *,
    plans: tuple[str, ...],
    features: tuple[str, ...],
) -> dict[str, dict[str, CapabilityValue]]:
    return {
        plan: {feature: matrix.get(plan, {}).get(feature, False) for feature in features}
        for plan in plans
    }


def _validate_no_plan_leakage(
    capability_matrix: dict[str, dict[str, CapabilityValue]],
    *,
    plan_order: tuple[str, ...],
) -> list[str]:
    """Ensure premium-only capabilities cannot be enabled on lower plans only."""
    issues: list[str] = []
    # Drop promotional/trial plans that intentionally unlock premium features
    # outside the linear upgrade ladder (e.g. the 14-day agency trial).
    plan_order = tuple(plan for plan in plan_order if plan not in NON_HIERARCHY_PLANS)
    features = {feature for capabilities in capability_matrix.values() for feature in capabilities}
    for feature in sorted(features):
        if feature == "max_sites" or not isinstance(
            capability_matrix.get(plan_order[0], {}).get(feature), bool
        ):
            continue
        highest_enabled_index = max(
            (
                idx
                for idx, plan in enumerate(plan_order)
                if capability_matrix.get(plan, {}).get(feature, False)
            ),
            default=-1,
        )
        if highest_enabled_index <= 0:
            continue

        for idx in range(highest_enabled_index):
            plan = plan_order[idx]
            next_plan = plan_order[idx + 1]
            current_enabled = capability_matrix.get(plan, {}).get(feature, False)
            next_enabled = capability_matrix.get(next_plan, {}).get(feature, False)
            if current_enabled and not next_enabled:
                issues.append(
                    f"Feature '{feature}' is enabled for '{plan}' but disabled for higher plan '{next_plan}'."
                )

    return issues


def _validate_functionality_projection(
    capability_matrix: dict[str, dict[str, CapabilityValue]],
) -> list[str]:
    """Ensure PLANS['functionalities'] is derived from the capability matrix."""
    issues: list[str] = []
    for plan, capabilities in capability_matrix.items():
        expected = sorted(
            [
                feature
                for feature, enabled in capabilities.items()
                if isinstance(enabled, bool) and enabled
            ]
        )
        actual = sorted(PLANS.get(plan, {}).get("functionalities", []))
        if expected != actual:
            issues.append(
                f"Plan '{plan}' functionalities mismatch. expected={expected}, actual={actual}."
            )
    return issues


def _validate_pricing_alignment(
    capability_matrix: dict[str, dict[str, CapabilityValue]],
    pricing_capabilities: dict[str, dict[str, CapabilityValue]],
) -> list[str]:
    """Ensure backend feature gates match published pricing capabilities."""
    plans = tuple(sorted(set(capability_matrix) | set(pricing_capabilities)))
    features = tuple(
        sorted(
            {
                feature
                for plan in plans
                for feature in set(capability_matrix.get(plan, {}))
                | set(pricing_capabilities.get(plan, {}))
            }
        )
    )

    normalized_backend = _matrix_for_comparison(
        capability_matrix,
        plans=plans,
        features=features,
    )
    normalized_pricing = _matrix_for_comparison(
        pricing_capabilities,
        plans=plans,
        features=features,
    )

    issues: list[str] = []
    for plan in plans:
        for feature in features:
            backend_enabled = normalized_backend[plan][feature]
            pricing_enabled = normalized_pricing[plan][feature]
            if backend_enabled != pricing_enabled:
                issues.append(
                    "Pricing/capabilities mismatch for "
                    f"plan='{plan}', feature='{feature}': "
                    f"backend={backend_enabled}, pricing={pricing_enabled}."
                )

    return issues


def validate_plan_compliance(
    capability_matrix: dict[str, dict[str, CapabilityValue]] | None = None,
    pricing_capabilities: dict[str, dict[str, CapabilityValue]] | None = None,
) -> None:
    """Raise PlanComplianceError if plan gating is out of compliance."""
    matrix = capability_matrix or CAPABILITY_MATRIX
    pricing = pricing_capabilities or PRICING_CAPABILITY_MATRIX

    issues: list[str] = []
    issues.extend(_validate_no_plan_leakage(matrix, plan_order=PLAN_ORDER))
    issues.extend(_validate_functionality_projection(matrix))
    issues.extend(_validate_pricing_alignment(matrix, pricing))

    if issues:
        detail = "\n - ".join(issues)
        raise PlanComplianceError(f"Plan compliance validation failed:\n - {detail}")


def validate_plan_compliance_from_repo_root(repo_root: str | Path) -> None:
    """Compatibility helper for CI jobs that call validators by repository root."""
    _ = Path(repo_root)
    validate_plan_compliance()


if __name__ == "__main__":
    validate_plan_compliance()
