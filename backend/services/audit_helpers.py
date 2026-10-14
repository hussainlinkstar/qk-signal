"""
Shared audit helpers, plan resolution, cost forecasting, budget notifications,
and URL helpers used by both api_router and queue_worker.

Centralised here (Item 24) to eliminate divergent duplicates across the codebase.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from sqlalchemy.orm import Session

import models
from app.config.plans import can_use_feature
from app.services.compliance.plan_validator import PlanValidator
from services.ai_routing_policy import normalize_audit_tier_class
from services.cost_forecast_service import (
    build_audit_forecast_input,
    forecast_audit_cost,
    serialize_cost_forecast,
)
from services.notification_router import NotificationRouter
from services.project_audit_scope import COMPETITOR_CATEGORY_MARKER

logger = logging.getLogger(__name__)

# Singleton validator, same instance used by api_router previously.
_plan_validator = PlanValidator()


# ---------------------------------------------------------------------------
# Plan resolution
# ---------------------------------------------------------------------------


def resolve_subscription_plan(user: models.User | None) -> str:
    """Canonical plan resolver, delegates to PlanValidator which validates
    against PLAN_ORDER, falls back to trial_plan, then "plan_starter"."""
    return _plan_validator.resolve_subscription_plan(user)


def resolve_plan_capabilities(user: models.User | None) -> dict[str, bool | int]:
    """Return capability dict for the user's effective plan, filtered to bool|int values."""
    return {
        key: value
        for key, value in _plan_validator.get_capabilities_for_user(user).items()
        if isinstance(value, (bool, int))
    }


# ---------------------------------------------------------------------------
# Competitor lite audit entitlement (SIGV2-1126)
# ---------------------------------------------------------------------------

COMPETITOR_LITE_AUDIT_FEATURE_KEY = "has_competitor_analysis"


def competitor_lite_audit_is_denied(*, plan: str | None, category: str | None) -> bool:
    """The one rule gating competitor lite audits, consulted from every path.

    A request whose category asks for a competitor lite audit requires the
    ``has_competitor_analysis`` capability from
    ``app.config.plans.CAPABILITY_MATRIX``; any other request is unaffected.
    The app endpoints, the external API and the worker that finally runs the
    job all call this, so the gate cannot be present on one enqueue path and
    missing on another. Only the shape of the refusal is per-surface.
    """
    if COMPETITOR_CATEGORY_MARKER not in str(category or "").strip().lower():
        return False
    return not can_use_feature(str(plan or ""), COMPETITOR_LITE_AUDIT_FEATURE_KEY)


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------


def frontend_base_url() -> str:
    return (
        os.getenv("FRONTEND_URL") or os.getenv("APP_BASE_URL") or "https://qiko.ai/signal"
    ).rstrip("/")


def project_budget_settings_url(project_id: int) -> str:
    return f"{frontend_base_url()}/dashboard/projects/{project_id}/settings"


# ---------------------------------------------------------------------------
# Cost forecast
# ---------------------------------------------------------------------------


def build_audit_cost_forecast(
    *,
    db: Session | None,
    requested_tier: str,
    policy_version: str | None,
    provider: str | None,
    target_url: str | None,
    target_name: str | None,
    target_metadata: dict[str, Any] | None,
    category: str | None,
    market: str | None,
    language: str | None,
    entities: list[str] | None,
    selected_models: list[str] | None = None,
    audit_data: dict[str, Any] | None = None,
    serp_preview: list[dict[str, Any]] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Build a cost forecast for an audit.  Returns (estimated_credits, serialised_forecast)."""
    forecast = forecast_audit_cost(
        audit_data=build_audit_forecast_input(
            target_url=target_url,
            target_name=target_name,
            target_metadata=target_metadata,
            category=category,
            market=market,
            language=language,
            audit_data=audit_data,
            entities=entities,
        ),
        dataforseo_results=serp_preview,
        tier_class=normalize_audit_tier_class(requested_tier),
        requested_tier=requested_tier,
        policy_version=policy_version,
        feature_key="audit.main",
        entities_count=len(entities or []),
        category=category,
        market=market,
        provider=provider,
        selected_models=selected_models,
        db=db,
    )
    return max(1, int(forecast.estimated_credits or 1)), serialize_cost_forecast(forecast)


# ---------------------------------------------------------------------------
# Budget notifications
# ---------------------------------------------------------------------------


def queue_notification(
    db: Session,
    *,
    user: models.User | None,
    to_email: str,
    template_key: str,
    context: Mapping[str, Any],
    correlation_id: str | None,
    workspace_id: int | None = None,
    project_id: int | None = None,
) -> None:
    """Dispatch a notification via NotificationRouter + trigger workflow evaluation."""
    try:
        # Lazy import to avoid circular dependency (workflow_engine → audit_helpers).
        from services.workflow_engine import evaluate_workflows_for_event

        NotificationRouter(db).dispatch_event(
            workspace_id=workspace_id,
            event_key=template_key,
            context=context,
            user=user,
            to_email=to_email,
            correlation_id=correlation_id,
        )
        evaluate_workflows_for_event(
            db,
            workspace_id=workspace_id,
            project_id=project_id,
            event_key=template_key,
            context=context,
        )
    except Exception as exc:
        logger.warning(
            "Failed to queue %s notification for %s", template_key, to_email, exc_info=exc
        )


def _internal_alert_recipients() -> list[str]:
    from core.config import settings

    raw = str(getattr(settings, "ADMIN_EMAILS", "") or "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def queue_project_budget_notifications(
    db: Session,
    *,
    project: models.Project | None,
    consumed_scans: int,
    monthly_limit_scans: int | None,
    percent_consumed: float | None,
    threshold_events: tuple[str, ...],
) -> None:
    """Route scan-cap threshold events to internal recipients.

    The 80% warning and cap-reached events notify ops when a project's
    scan cap is about to block runs. Delivery goes to ``ADMIN_EMAILS`` via
    EmailService; when no internal recipient is configured the event is
    logged only. The upstream ``warning_threshold_sent_at`` /
    ``limit_reached_sent_at`` markers keep each event firing once per
    crossing per cycle, so this stays retry-safe.
    """
    if project is None or monthly_limit_scans is None or not threshold_events:
        return

    effective_events = list(threshold_events)
    if "limit_reached" in effective_events:
        effective_events = ["limit_reached"]

    workspace = project.workspace
    workspace_name = workspace.name if workspace is not None else "Workspace"
    settings_url = project_budget_settings_url(project.id)
    recipients = _internal_alert_recipients()

    for event in effective_events:
        template_key = "budget.exceeded" if event == "limit_reached" else "budget.warning"
        context: dict[str, Any] = {
            "email": "",
            "project_name": project.name,
            "workspace_name": workspace_name,
            "consumed_scans": consumed_scans,
            "monthly_limit_scans": monthly_limit_scans,
            "settings_url": settings_url,
        }
        if event == "warning_80":
            context["percent_consumed"] = percent_consumed or 0
        if not recipients:
            logger.info(
                "Internal budget threshold event %s for project %s (%s/%s scans); "
                "no ADMIN_EMAILS configured",
                event,
                project.id,
                consumed_scans,
                monthly_limit_scans,
            )
            continue
        from services.email_service import EmailService

        email_svc = EmailService(db)
        for recipient in recipients:
            context["email"] = recipient
            email_svc.queue_template_email(
                to_email=recipient,
                template_key=template_key,
                context=dict(context),
            )
