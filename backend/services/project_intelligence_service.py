from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    MINIMUM_PLAN_BY_FEATURE,
    PLAN_PRESENTATION,
    can_use_feature,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from services.project_audit_scope import own_project_audit_clause


ProjectFeatureAccessKey = Literal[
    "monitoring",
    "automations",
    "advisor_recommendations",
    "entity_authority",
    "benchmark_intelligence",
    "scheduled_audits",
    "jira_export",
]
ProjectAuditModuleKey = Literal["seo", "aeo", "geo"]
ProjectAuditSelectionStatus = Literal["ready", "stale", "no_matching_audit", "no_audits"]

_BASIC_PLAN_ALIASES = {"plan_starter", "plan_starter", "plan_standard"}


def plan_display_name(plan: str | None) -> str | None:
    """The customer-facing name of a canonical plan id."""
    if not plan:
        return None
    presentation = PLAN_PRESENTATION.get(plan) or {}
    name = presentation.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return plan.removeprefix("plan_").replace("_", " ").title()


def required_plan_label_for_capability(capability_key: str) -> str | None:
    """The plan an upgrade prompt for this capability may name.

    ``None`` when the lowest plan that includes the capability is the free
    Starter plan: every plan already grants it, so there is no plan to upgrade
    to and naming one would sell a customer something they have.
    """
    required_plan = MINIMUM_PLAN_BY_FEATURE.get(capability_key)
    if not required_plan or required_plan == "plan_starter":
        return None
    return plan_display_name(required_plan)


@dataclass(frozen=True)
class ProjectFeatureRule:
    """One project capability gate and the sentence a locked surface shows.

    SIGV2-1221: neither the plan name nor the sentence that contains it is
    written out here. Both are derived from ``capability_key`` through
    ``MINIMUM_PLAN_BY_FEATURE``, because a hand-written plan name is a promise
    with nothing enforcing it. This table used to claim "Project monitoring
    requires Standard or higher" for ``has_performance_sync``, which
    ``MINIMUM_PLAN_BY_FEATURE`` puts on ``plan_starter`` - every plan grants
    it, so the rule could never deny anyone and the plan it named would have
    sold an upgrade that changed nothing.
    """

    capability_key: str
    #: Subject of the generated sentence, e.g. "Project monitoring".
    subject: str

    @property
    def required_plan(self) -> str | None:
        return required_plan_label_for_capability(self.capability_key)

    @property
    def detail(self) -> str:
        required_plan = self.required_plan
        if not required_plan:
            return f"{self.subject} is not available on this plan."
        return f"{self.subject} requires {required_plan} or higher."


@dataclass(frozen=True)
class ProjectAuditModuleRule:
    module_label: str
    compatible_audit_types: tuple[models.AuditType, ...]
    recommended_audit_type: Literal["STANDARD", "DEEP"]
    recommended_launch_tier: Literal["fast", "smart", "deep"]
    stale_after_days: int
    no_audits_message: str


@dataclass(frozen=True)
class ProjectModuleAuditSelection:
    module: ProjectAuditModuleKey
    status: ProjectAuditSelectionStatus
    message: str
    recommended_audit_type: Literal["STANDARD", "DEEP"]
    recommended_launch_tier: Literal["fast", "smart", "deep"]
    compatible_audit_types: tuple[str, ...]
    stale_after_days: int
    selected_audit_age_days: int | None
    selected_audit: models.Audit | None
    latest_audit: models.Audit | None


_FEATURE_RULES: dict[ProjectFeatureAccessKey, ProjectFeatureRule] = {
    "monitoring": ProjectFeatureRule(
        capability_key="has_performance_sync",
        subject="Project monitoring",
    ),
    "automations": ProjectFeatureRule(
        capability_key="can_use_workflow_automations",
        subject="Workflow automations",
    ),
    # SIGV2-1134: the Advisor action plan, and every preview of it, is its own
    # entitlement. It used to be read off "automations" on the dashboard, which
    # is a different capability (Specialist+), so a Standard customer who owns
    # the plan was told to upgrade to see a preview of it. One key, served from
    # here, now governs the plan and its previews.
    "advisor_recommendations": ProjectFeatureRule(
        capability_key="has_advisor_recommendations",
        subject="The Advisor action plan",
    ),
    "entity_authority": ProjectFeatureRule(
        capability_key="entity_authority",
        subject="Entity Authority",
    ),
    "benchmark_intelligence": ProjectFeatureRule(
        capability_key="has_competitor_analysis",
        subject="Benchmark intelligence",
    ),
    "scheduled_audits": ProjectFeatureRule(
        capability_key="can_schedule_audits",
        subject="Scheduled audits",
    ),
    "jira_export": ProjectFeatureRule(
        capability_key="can_export_to_jira",
        subject="Jira export",
    ),
}

_AUDIT_MODULE_RULES: dict[ProjectAuditModuleKey, ProjectAuditModuleRule] = {
    "seo": ProjectAuditModuleRule(
        module_label="SEO",
        compatible_audit_types=(
            models.AuditType.FAST,
            models.AuditType.SMART,
            models.AuditType.STANDARD,
            models.AuditType.DEEP,
        ),
        recommended_audit_type="STANDARD",
        recommended_launch_tier="fast",
        stale_after_days=30,
        no_audits_message="No SEO-compatible project audit exists yet. Run a standard audit to capture technical and search telemetry.",
    ),
    "aeo": ProjectAuditModuleRule(
        module_label="AEO",
        compatible_audit_types=(models.AuditType.SMART, models.AuditType.DEEP),
        recommended_audit_type="DEEP",
        recommended_launch_tier="smart",
        stale_after_days=14,
        no_audits_message="No AEO-compatible project audit exists yet. Run a deep audit to capture answer-engine coverage.",
    ),
    "geo": ProjectAuditModuleRule(
        module_label="GEO",
        compatible_audit_types=(models.AuditType.SMART, models.AuditType.DEEP),
        recommended_audit_type="DEEP",
        recommended_launch_tier="smart",
        stale_after_days=14,
        no_audits_message="No GEO-compatible project audit exists yet. Run a deep audit to capture generative visibility signals.",
    ),
}


def resolve_user_plan_alias(user: models.User | None) -> str:
    if user:
        resolved = resolve_plan_alias(resolve_entitled_subscription_plan(user))
        if resolved:
            return resolved
    if user and getattr(user, "trial_plan", None):
        resolved = resolve_plan_alias(str(user.trial_plan))
        if resolved:
            return resolved
    return "plan_starter"


def build_project_feature_access(user: models.User | None) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for feature_key, rule in _FEATURE_RULES.items():
        payload[feature_key] = resolve_project_capability_access(
            user,
            capability_key=rule.capability_key,
            detail=rule.detail,
        )
    return payload


def require_project_feature_access(
    user: models.User | None,
    feature_key: ProjectFeatureAccessKey,
) -> dict[str, Any]:
    access = build_project_feature_access(user).get(feature_key)
    if access is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This project feature is not available.",
        )
    if access["allowed"]:
        return access
    raise HTTPException(
        status_code=int(access["status_code"] or status.HTTP_403_FORBIDDEN),
        detail=str(access["detail"] or "This project feature is not available."),
    )


def resolve_project_capability_access(
    user: models.User | None,
    *,
    capability_key: str,
    detail: str | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    """Resolve one capability gate, naming the plan the backend would require.

    SIGV2-1221: ``required_plan`` is no longer a caller argument. It is derived
    from ``capability_key``, so a caller cannot state a plan that does not hold
    the capability, and ``detail`` defaults to a sentence built from the same
    plan. A caller may still pass its own ``detail`` wording; it cannot pass
    its own plan.
    """
    plan_alias = resolve_user_plan_alias(user)
    allowed = can_use_feature(plan_alias, capability_key)
    required_plan = required_plan_label_for_capability(capability_key)
    if detail is None:
        rule_subject = subject or capability_key
        detail = (
            f"{rule_subject} requires {required_plan} or higher."
            if required_plan
            else f"{rule_subject} is not available on this plan."
        )
    status_code: int | None = None
    if not allowed:
        status_code = (
            status.HTTP_402_PAYMENT_REQUIRED
            if plan_alias in _BASIC_PLAN_ALIASES
            else status.HTTP_403_FORBIDDEN
        )
    return {
        "allowed": allowed,
        "detail": None if allowed else detail,
        "status_code": status_code,
        "required_plan": None if allowed else required_plan,
    }


def require_project_capability_access(
    user: models.User | None,
    *,
    capability_key: str,
    detail: str | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    access = resolve_project_capability_access(
        user,
        capability_key=capability_key,
        detail=detail,
        subject=subject,
    )
    if access["allowed"]:
        return access
    raise HTTPException(
        status_code=int(access["status_code"] or status.HTTP_403_FORBIDDEN),
        detail=str(access["detail"] or "This project feature is not available."),
    )


def select_project_module_audit(
    db: Session,
    *,
    project_id: int,
    module: ProjectAuditModuleKey,
    now: datetime | None = None,
) -> ProjectModuleAuditSelection:
    rule = _AUDIT_MODULE_RULES[module]
    latest_audit = (
        db.query(models.Audit)
        .filter(models.Audit.project_id == project_id, own_project_audit_clause())
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )
    selected_audit = (
        db.query(models.Audit)
        .filter(
            models.Audit.project_id == project_id,
            own_project_audit_clause(),
            models.Audit.audit_type.in_(rule.compatible_audit_types),
        )
        .order_by(models.Audit.created_at.desc(), models.Audit.id.desc())
        .first()
    )

    selected_audit_age_days: int | None = None
    reference_now = now or datetime.now(timezone.utc)
    if selected_audit is not None and selected_audit.created_at is not None:
        created_at = selected_audit.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        selected_audit_age_days = max(0, (reference_now - created_at).days)

    if latest_audit is None:
        return ProjectModuleAuditSelection(
            module=module,
            status="no_audits",
            message=rule.no_audits_message,
            recommended_audit_type=rule.recommended_audit_type,
            recommended_launch_tier=rule.recommended_launch_tier,
            compatible_audit_types=tuple(
                audit_type.value for audit_type in rule.compatible_audit_types
            ),
            stale_after_days=rule.stale_after_days,
            selected_audit_age_days=None,
            selected_audit=None,
            latest_audit=None,
        )

    if selected_audit is None:
        latest_type = (
            latest_audit.audit_type.value
            if isinstance(latest_audit.audit_type, models.AuditType)
            else str(latest_audit.audit_type or "")
        )
        return ProjectModuleAuditSelection(
            module=module,
            status="no_matching_audit",
            message=(
                f"Latest project audit is {latest_type or 'unknown'}, but {rule.module_label} requires "
                f"{rule.recommended_audit_type.lower()} coverage. Run a fresh {rule.recommended_launch_tier} audit."
            ),
            recommended_audit_type=rule.recommended_audit_type,
            recommended_launch_tier=rule.recommended_launch_tier,
            compatible_audit_types=tuple(
                audit_type.value for audit_type in rule.compatible_audit_types
            ),
            stale_after_days=rule.stale_after_days,
            selected_audit_age_days=None,
            selected_audit=None,
            latest_audit=latest_audit,
        )

    if selected_audit_age_days is not None and selected_audit_age_days >= rule.stale_after_days:
        return ProjectModuleAuditSelection(
            module=module,
            status="stale",
            message=(
                f"This {rule.module_label} view is using audit data that is {selected_audit_age_days} day"
                f"{'' if selected_audit_age_days == 1 else 's'} old. Run a fresh {rule.recommended_launch_tier} audit."
            ),
            recommended_audit_type=rule.recommended_audit_type,
            recommended_launch_tier=rule.recommended_launch_tier,
            compatible_audit_types=tuple(
                audit_type.value for audit_type in rule.compatible_audit_types
            ),
            stale_after_days=rule.stale_after_days,
            selected_audit_age_days=selected_audit_age_days,
            selected_audit=selected_audit,
            latest_audit=latest_audit,
        )

    return ProjectModuleAuditSelection(
        module=module,
        status="ready",
        message=f"Latest {rule.module_label} coverage is ready.",
        recommended_audit_type=rule.recommended_audit_type,
        recommended_launch_tier=rule.recommended_launch_tier,
        compatible_audit_types=tuple(
            audit_type.value for audit_type in rule.compatible_audit_types
        ),
        stale_after_days=rule.stale_after_days,
        selected_audit_age_days=selected_audit_age_days,
        selected_audit=selected_audit,
        latest_audit=latest_audit,
    )
