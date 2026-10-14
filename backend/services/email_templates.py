from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.aio_view import derive_aio
from services.report_i18n_service import get_email_copy, normalize_report_language

logger = logging.getLogger(__name__)

template_dir = Path(__file__).parent.parent / "templates"
# Every email template here is named `*.html`, so this selection already
# escapes all of them. It is written fail-closed anyway: the PDF report
# environment used the same two-extension form against `*.html.j2` names and
# silently escaped nothing (SIGV2-1224), and an email template added under a
# `.j2` suffix would reintroduce exactly that.
env = Environment(
    loader=FileSystemLoader(str(template_dir)),
    autoescape=select_autoescape(
        enabled_extensions=("html", "htm", "xml", "html.j2", "htm.j2", "xml.j2", "j2"),
        default_for_string=True,
        default=True,
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)

SubjectBuilder = Callable[[Mapping[str, Any]], str]

RENDER_FAILURE_MARKER = "Email template rendering failed."

DEFAULT_BRAND_PRIMARY = "#0C0F16"
DEFAULT_BRAND_SECONDARY = "#22D3EE"
DEFAULT_BRAND_ACCENT = "#9333EA"
DEFAULT_LOGO_PATH = "/email/qiko-logo.png"
DEFAULT_LOGO_DARK_PATH = "/email/qiko-logo.png"
SOCIAL_ICON_PATHS = {
    "facebook": "/email/social/facebook.svg",
    "x": "/email/social/x.svg",
    "instagram": "/email/social/instagram.svg",
    "linkedin": "/email/social/linkedin.svg",
    "youtube": "/email/social/youtube.svg",
    "tiktok": "/email/social/tiktok.svg",
}
SOCIAL_ICON_DARK_PATHS = {
    "facebook": "/email/social/facebook-white.svg",
    "x": "/email/social/x-white.svg",
    "instagram": "/email/social/instagram-white.svg",
    "linkedin": "/email/social/linkedin-white.svg",
    "youtube": "/email/social/youtube-white.svg",
    "tiktok": "/email/social/tiktok-white.svg",
}


@dataclass(frozen=True)
class EmailTemplateDefinition:
    subject: str | SubjectBuilder
    html_template: str
    category: str


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str
    category: str


def app_base_url() -> str:
    for key in ("FRONTEND_URL", "APP_BASE_URL"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value.rstrip("/")
    return "https://qiko.ai/signal"


def _support_address() -> str:
    for key in ("SUPPORT_EMAIL", "EMAIL_FROM_ADDRESS", "MAIL_FROM"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return "support@qiko.ai"


def _normalize_hex_color(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    if len(candidate) in (4, 7) and candidate.startswith("#"):
        hex_part = candidate[1:]
        if all(char in "0123456789abcdefABCDEF" for char in hex_part):
            return candidate
    return fallback


def _aio_rollup(aeo: Any, geo: Any) -> int | None:
    return derive_aio({"aeo_score": aeo, "geo_score": geo}).get("aio_score")


def _parse_delta(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _derive_aio_delta(delta: Mapping[str, Any]) -> str | None:
    """Roll aeo/geo movement into a signed AIO delta string.

    With the default 50/50 weights the mean of the component deltas equals the
    delta of the mean, so this matches ``derive_aio`` applied to the endpoints.
    """
    aeo = _parse_delta(delta.get("aeo"))
    geo = _parse_delta(delta.get("geo"))
    if aeo is None and geo is None:
        return None
    if aeo is None or geo is None:
        merged = aeo if aeo is not None else geo
    else:
        merged = (aeo + geo) / 2
    return f"{merged:+g}"


def _default_logo_url(base_url: str) -> str:
    return f"{base_url}{DEFAULT_LOGO_PATH}"


def _default_logo_dark_url(base_url: str) -> str:
    return f"{base_url}{DEFAULT_LOGO_DARK_PATH}"


def normalize_email_logo_url(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    lowered = candidate.lower()
    if lowered.startswith("data:image/svg+xml"):
        return None
    if lowered.startswith("data:"):
        return candidate
    parsed = urlparse(candidate)
    if (parsed.path or "").lower().endswith((".svg", ".svgz")):
        return None
    return candidate


def _normalize_social_links(value: Any, *, base_url: str) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        platform = str(item.get("platform") or "").strip().lower()
        label = str(item.get("label") or _humanize(platform) or "Social").strip()
        icon_url = str(item.get("icon_url") or "").strip()
        if not icon_url and platform in SOCIAL_ICON_PATHS:
            icon_url = f"{base_url}{SOCIAL_ICON_PATHS[platform]}"
        icon_dark_url = str(item.get("icon_dark_url") or "").strip()
        if not icon_dark_url and platform in SOCIAL_ICON_DARK_PATHS:
            icon_dark_url = f"{base_url}{SOCIAL_ICON_DARK_PATHS[platform]}"
        glyph = str(item.get("glyph") or "").strip()
        entry: dict[str, str] = {
            "platform": platform,
            "url": url,
            "label": label,
            "icon_url": icon_url,
            "glyph": glyph or label[:2].upper(),
        }
        if icon_dark_url:
            entry["icon_dark_url"] = icon_dark_url
        normalized.append(entry)
    return normalized


def _humanize(value: str | None) -> str | None:
    if not value:
        return None
    words = str(value).replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) if words else None


_METRIC_NAME_I18N: dict[str, tuple[str, str]] = {
    "seo_score": ("metric_label_seo_score", "SEO score"),
    "aio_score": ("metric_label_aio_score", "AIO score"),
    "ai_visibility_score": ("metric_label_aio_score", "AIO score"),
    "geo_score": ("metric_label_aio_score", "AIO score"),
    "aeo_score": ("metric_label_aio_score", "AIO score"),
}


def _i18n_or(email_i18n: Mapping[str, Any], key: str, fallback: str) -> str:
    value = email_i18n.get(key) if isinstance(email_i18n, Mapping) else None
    if isinstance(value, str) and value.strip():
        return value
    return fallback


def _round_half_up(value: float) -> int:
    # floor(x + 0.5) matches derive_aio's rounding so the card movement never
    # disagrees with the score it sits under.
    return int(math.floor(value + 0.5))


def _score_movement_text(
    email_i18n: Mapping[str, Any], points: float | None, period: str
) -> str | None:
    if points is None:
        return None
    rounded = _round_half_up(points)
    if rounded > 0:
        singular = rounded == 1
        template = _i18n_or(
            email_i18n,
            "score_delta_up_one" if singular else "score_delta_up",
            "Up {points} point since {period}" if singular else "Up {points} points since {period}",
        )
    elif rounded < 0:
        singular = rounded == -1
        template = _i18n_or(
            email_i18n,
            "score_delta_down_one" if singular else "score_delta_down",
            "Down {points} point since {period}"
            if singular
            else "Down {points} points since {period}",
        )
    else:
        template = _i18n_or(email_i18n, "score_delta_flat", "No change since {period}")
    return template.replace("{points}", str(abs(rounded))).replace("{period}", period)


def _rank_movement_text(email_i18n: Mapping[str, Any], current: Any, previous: Any) -> str | None:
    if current is None or previous is None:
        return None
    try:
        current_int = int(current)
        previous_int = int(previous)
    except (TypeError, ValueError):
        return None
    if current_int < previous_int:
        template = _i18n_or(email_i18n, "rank_delta_up", "Up from #{previous}")
    elif current_int > previous_int:
        template = _i18n_or(email_i18n, "rank_delta_down", "Down from #{previous}")
    else:
        template = _i18n_or(email_i18n, "rank_delta_flat", "No change")
    return template.replace("{previous}", str(previous_int))


def _metric_name_display(metric_name: Any, email_i18n: Mapping[str, Any]) -> str | None:
    key = str(metric_name or "").strip().lower()
    if not key:
        return None
    i18n_key, fallback = _METRIC_NAME_I18N.get(key, ("metric_label_unknown", "Visibility score"))
    label = email_i18n.get(i18n_key) if isinstance(email_i18n, Mapping) else None
    if isinstance(label, str) and label.strip():
        return label.strip()
    return fallback


def _recipient_name(context: Mapping[str, Any]) -> str:
    for key in ("user_name", "name", "company_name"):
        value = context.get(key)
        if value:
            return str(value)
    email = context.get("email")
    if email and "@" in str(email):
        return str(email).split("@", 1)[0]
    return str(email or "there")


def _short_target(value: str | None) -> str:
    if not value:
        return "your workspace"
    parsed = urlparse(str(value))
    return parsed.netloc or str(value)


def _format_money(value: Any, currency: str | None) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if amount == amount.to_integral_value():
        amount = amount / Decimal("100")
    return f"{amount.quantize(Decimal('0.01'))} {(currency or 'USD').upper()}"


def _resolve_email_language(context: Mapping[str, Any]) -> str:
    return normalize_report_language(
        str(
            context.get("lang") or context.get("language") or context.get("report_language") or "en"
        )
    )


def _localized_email_subject(
    template_key: str,
    context: Mapping[str, Any],
    fallback: str,
) -> str:
    language = _resolve_email_language(context)
    localized = get_email_copy(
        language,
        template_key,
        context={
            **dict(context),
            "target_host": _short_target(context.get("target_url")),
            "domain_suffix": f" ({context.get('domain_url')})" if context.get("domain_url") else "",
        },
    ).get("subject")
    if isinstance(localized, str) and localized.strip():
        return localized
    return fallback


def _default_text(subject: str, context: Mapping[str, Any]) -> str:
    fields = [
        ("Target", context.get("target_url")),
        ("Project", context.get("project_name")),
        ("Plan", context.get("plan_name_display") or context.get("current_plan_display")),
        ("Previous plan", context.get("previous_plan_display")),
        ("Amount", context.get("formatted_amount")),
        ("Report", context.get("report_url")),
        ("Dashboard", context.get("dashboard_url")),
        ("Billing", context.get("billing_url") or context.get("manage_billing_url")),
        ("Models", context.get("model_names_csv")),
        ("Message", context.get("message")),
        ("Verification", context.get("verification_url")),
        ("Reset", context.get("reset_url")),
        ("Invitation", context.get("invitation_url")),
        ("Portal", context.get("portal_url")),
        ("Feedback", context.get("feedback_url")),
    ]
    lines = [subject]
    for label, value in fields:
        if value:
            lines.append(f"{label}: {value}")
    return "\n".join(lines)


def _subject_audit_completed(context: Mapping[str, Any]) -> str:
    return _localized_email_subject(
        "audit.completed",
        context,
        f"Audit completed for {_short_target(context.get('target_url'))}",
    )


def _subject_consensus_ready(context: Mapping[str, Any]) -> str:
    return _localized_email_subject(
        "audit.consensus_ready",
        context,
        f"Multi-model consensus ready for {_short_target(context.get('target_url'))}",
    )


def _subject_plan_changed(context: Mapping[str, Any]) -> str:
    return f"Plan updated: {context.get('plan_name_display') or context.get('plan_name') or 'your plan'}"


def _subject_alert_triggered(context: Mapping[str, Any]) -> str:
    return f"Alert triggered for {context.get('project_name') or 'your project'}"


def _subject_alert_visibility_score_drop(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"AIO score dropped for {project_name}"


def _subject_alert_aeo_mention_drop(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"Off-page mentions dropped for {project_name}"


def _subject_guest_audit_followup(context: Mapping[str, Any]) -> str:
    target_name = str(context.get("target_name") or "").strip()
    fallback = (
        f"Your free audit for {target_name} is ready" if target_name else "Your free audit is ready"
    )
    return _localized_email_subject("guest_audit.followup", context, fallback)


def _subject_audit_failed(context: Mapping[str, Any]) -> str:
    return f"Audit failed for {_short_target(context.get('target_url'))}"


def _subject_client_invitation(context: Mapping[str, Any]) -> str:
    workspace_name = str(context.get("workspace_name") or "your client portal").strip()
    return f"You're invited to {workspace_name}"


def _subject_trial_invitation(context: Mapping[str, Any]) -> str:
    brand = str(context.get("brand_name") or "Qiko Signal").strip()
    return f"You're Invited to Try {brand} - 14-Day Agency Trial"


def _subject_trial_feedback_request(context: Mapping[str, Any]) -> str:
    brand = str(context.get("brand_name") or "Qiko Signal").strip()
    return f"How was your {brand} trial?"


def _subject_welcome(context: Mapping[str, Any]) -> str:
    brand = str(context.get("brand_name") or "Qiko Signal").strip()
    return f"Welcome to {brand}"


def _subject_domain_verified(context: Mapping[str, Any]) -> str:
    return f"Domain verified: {context.get('domain') or 'your custom domain'}"


def _subject_ssl_provisioned(context: Mapping[str, Any]) -> str:
    return f"White-label domain is live: {context.get('domain') or 'your custom domain'}"


def _subject_domain_error(context: Mapping[str, Any]) -> str:
    return f"Domain setup needs attention: {context.get('domain') or 'your custom domain'}"


def _subject_budget_warning(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"Project scan cap warning: {project_name}"


def _subject_budget_exceeded(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"Project scan cap reached: {project_name}"


def _subject_progress_report(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    month_label = str(context.get("report_month_label") or "this month").strip()
    return _localized_email_subject(
        "project.progress_report",
        context,
        f"{project_name} progress report for {month_label}",
    )


def _subject_competitive_digest(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    period = str(context.get("report_period") or "competitive").strip()
    return _localized_email_subject(
        "competitive.digest",
        context,
        f"{project_name} {period} competitive digest",
    )


def _subject_annotation_created(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"New report annotation on {project_name}"


def _subject_annotation_replied(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"New reply on {project_name}"


def _subject_commitment_activated(context: Mapping[str, Any]) -> str:
    tier = _humanize(str(context.get("tier") or "audit commitment"))
    return f"Your {tier} audit commitment is active"


def _subject_commitment_renewed(context: Mapping[str, Any]) -> str:
    return "Your audit commitment renewed"


def _subject_commitment_warning(context: Mapping[str, Any]) -> str:
    usage_pct = context.get("usage_pct") or context.get("percent_used") or 0
    return f"You've used {usage_pct}% of your committed volume"


def _subject_commitment_canceled(context: Mapping[str, Any]) -> str:
    tier = _humanize(str(context.get("tier") or "audit commitment"))
    return f"Your {tier} audit commitment has been canceled"


def _subject_lead_captured(context: Mapping[str, Any]) -> str:
    lead_email = str(context.get("lead_email") or "new prospect").strip()
    return f"New lead captured: {lead_email}"


def _subject_sitemap_crawl_complete(context: Mapping[str, Any]) -> str:
    project_name = str(context.get("project_name") or "your project").strip()
    return f"Sitemap crawl complete for {project_name}"


def _subject_admin_system_alert(context: Mapping[str, Any]) -> str:
    rule_name = str(context.get("rule_name") or "System rule").strip()
    return f"System alert: {rule_name}"


def _subject_model_lifecycle_alert(context: Mapping[str, Any]) -> str:
    provider = str(context.get("provider") or "AI provider").strip().title()
    severity = str(context.get("severity") or "warning").strip().upper()
    return f"[{severity}] Model lifecycle alert: {provider}"


TEMPLATE_DEFINITIONS: dict[str, EmailTemplateDefinition] = {
    "auth.verification": EmailTemplateDefinition(
        "Verify your email", "verification.html", "account_notification"
    ),
    "auth.password_reset": EmailTemplateDefinition(
        "Reset your password", "password_reset.html", "account_notification"
    ),
    "auth.welcome": EmailTemplateDefinition(
        _subject_welcome, "welcome.html", "account_notification"
    ),
    "invoice.paid": EmailTemplateDefinition("Payment received", "invoice_paid.html", "billing"),
    "invoice.payment_failed": EmailTemplateDefinition(
        "Payment action required", "invoice_failed.html", "billing"
    ),
    "subscription.deleted": EmailTemplateDefinition(
        "Subscription canceled", "subscription_deleted.html", "billing"
    ),
    "plan.changed": EmailTemplateDefinition(_subject_plan_changed, "plan_changed.html", "billing"),
    "commitment.activated": EmailTemplateDefinition(
        _subject_commitment_activated,
        "commitment_activated.html",
        "billing",
    ),
    "commitment.renewed": EmailTemplateDefinition(
        _subject_commitment_renewed,
        "commitment_renewed.html",
        "billing",
    ),
    "commitment.overage_warning": EmailTemplateDefinition(
        _subject_commitment_warning,
        "commitment_overage_warning.html",
        "billing",
    ),
    "commitment.canceled": EmailTemplateDefinition(
        _subject_commitment_canceled,
        "commitment_canceled.html",
        "billing",
    ),
    "audit.completed": EmailTemplateDefinition(
        _subject_audit_completed, "audit_completed.html", "audit_notification"
    ),
    "audit.consensus_ready": EmailTemplateDefinition(
        _subject_consensus_ready, "consensus_ready.html", "audit_notification"
    ),
    "guest_audit.followup": EmailTemplateDefinition(
        _subject_guest_audit_followup,
        "guest_audit_followup.html",
        "audit_notification",
    ),
    "alert.triggered": EmailTemplateDefinition(
        _subject_alert_triggered, "alert_triggered.html", "alert_notification"
    ),
    "alert.visibility_score_drop": EmailTemplateDefinition(
        _subject_alert_visibility_score_drop,
        "alert_visibility_score_drop.html",
        "alert_notification",
    ),
    "alert.aeo_mention_drop": EmailTemplateDefinition(
        _subject_alert_aeo_mention_drop,
        "alert_aeo_mention_drop.html",
        "alert_notification",
    ),
    "admin_system_alert": EmailTemplateDefinition(
        _subject_admin_system_alert,
        "admin_system_alert.html",
        "system_alert",
    ),
    "admin.model_lifecycle_alert": EmailTemplateDefinition(
        _subject_model_lifecycle_alert,
        "model_lifecycle_alert.html",
        "system_alert",
    ),
    "audit.failed": EmailTemplateDefinition(
        _subject_audit_failed, "audit_failed.html", "system_alert"
    ),
    "report.failed": EmailTemplateDefinition(
        "Report generation failed", "report_failed.html", "system_alert"
    ),
    "audit.schedule_paused": EmailTemplateDefinition(
        "Scheduled audit paused", "schedule_paused.html", "system_alert"
    ),
    "budget.warning": EmailTemplateDefinition(
        _subject_budget_warning, "budget_warning.html", "system_alert"
    ),
    "budget.exceeded": EmailTemplateDefinition(
        _subject_budget_exceeded, "budget_exceeded.html", "system_alert"
    ),
    "project.progress_report": EmailTemplateDefinition(
        _subject_progress_report,
        "progress_report.html",
        "report_delivery",
    ),
    "competitive.digest": EmailTemplateDefinition(
        _subject_competitive_digest,
        "competitive_digest.html",
        "report_delivery",
    ),
    "annotation.created": EmailTemplateDefinition(
        _subject_annotation_created,
        "annotation_created.html",
        "collaboration",
    ),
    "annotation.replied": EmailTemplateDefinition(
        _subject_annotation_replied,
        "annotation_replied.html",
        "collaboration",
    ),
    "workspace.client_invitation": EmailTemplateDefinition(
        _subject_client_invitation,
        "client_invitation.html",
        "account_notification",
    ),
    "trial.invitation": EmailTemplateDefinition(
        _subject_trial_invitation,
        "plan_agency_trial_invitation.html",
        "trial_invitation",
    ),
    "trial.feedback_request": EmailTemplateDefinition(
        _subject_trial_feedback_request,
        "trial_feedback_request.html",
        "trial_feedback",
    ),
    "trial.explorer_transition": EmailTemplateDefinition(
        "Your trial ended, welcome to the Explorer plan",
        "trial_explorer_transition.html",
        "account_notification",
    ),
    "workspace.domain_verified": EmailTemplateDefinition(
        _subject_domain_verified,
        "domain_verified.html",
        "account_notification",
    ),
    "workspace.ssl_provisioned": EmailTemplateDefinition(
        _subject_ssl_provisioned,
        "ssl_provisioned.html",
        "account_notification",
    ),
    "workspace.domain_error": EmailTemplateDefinition(
        _subject_domain_error,
        "domain_error.html",
        "system_alert",
    ),
    "lead.captured": EmailTemplateDefinition(
        _subject_lead_captured,
        "lead_captured.html",
        "lead_notification",
    ),
    "sitemap.crawl_complete": EmailTemplateDefinition(
        _subject_sitemap_crawl_complete,
        "sitemap_crawl_complete.html",
        "audit_notification",
    ),
}

# Shared dummy context used by admin preview endpoints and CLI preview script.
DEFAULT_PREVIEW_CONTEXT: dict[str, Any] = {
    "email": "user@example.com",
    "user_name": "Qiko Signal QA",
    "company_name": "Qiko Signal",
    "target_url": "https://example.com/target",
    "project_name": "Acme SEO Project",
    "plan_name": "plan_specialist",
    "previous_plan": "plan_standard",
    "current_plan": "plan_executive",
    "amount_due": "4900",
    "amount_paid": "4900",
    "currency": "usd",
    "report_url": "https://qiko.ai/signal/report/123",
    "dashboard_url": "https://qiko.ai/signal/dashboard",
    "billing_url": "https://qiko.ai/signal/billing",
    "manage_billing_url": "https://qiko.ai/signal/billing",
    "model_names_csv": "Gemini 2.5 Flash, Gemini 2.5 Pro",
    "message": "Performance dropped significantly below 80%.",
    "verification_url": "https://qiko.ai/signal/auth/verify?token=abc",
    "reset_url": "https://qiko.ai/signal/auth/reset?token=xyz",
    "metric_name": "aio_score",
    "condition": "below threshold",
    "unsubscribe_token": "preview-unsub-token-1234",
    "unsubscribe_url": "https://qiko.ai/signal/api/v1/auth/unsubscribe?token=preview-unsub-token-1234",
    "is_transactional": False,
    # Scores and audit fields
    "geo_score": 85,
    "seo_score": 78,
    "aeo_score": 91,
    "overall_score": 82,
    "target_name": "example.com",
    "signup_url": "https://qiko.ai/signal/signup",
    "threshold": 80,
    "error_message": "Timeout connecting to target",
    "job_id": "job-20260302-001",
    "report_name": "March 2026 Monthly Report",
    # Budget fields
    "workspace_name": "Acme Corp",
    "consumed_scans": 90,
    "monthly_limit_scans": 100,
    "percent_consumed": 90.0,
    "settings_url": "https://qiko.ai/signal/settings",
    # Client invitation fields
    "invitation_url": "https://qiko.ai/signal/invite?token=abc",
    "portal_url": "https://qiko.ai/signal/portal",
    "agency_name": "Digital Agency Inc",
    "project_names": ["Acme SEO Project", "Landing Page Audit"],
    # Progress report fields
    "report_month_label": "March 2026",
    "current_scores": {"seo": 80, "geo": 75, "aeo": 85, "audit_count": 12},
    "delta": {"seo": "+5", "geo": "+3", "aeo": "+8"},
    "highlights": [
        "Improved meta descriptions across 23 pages",
        "Schema markup coverage increased to 87%",
    ],
    "remaining_issues": ["Missing alt text on product images", "Thin content on 4 category pages"],
    # Competitive digest fields
    "competitor_count": 3,
    "report_period": "weekly",
    "current_rank": {"aio": 1, "geo": 1, "seo": 2, "aeo": 1},
    "previous_rank": {"aio": 3, "geo": 2, "seo": 2, "aeo": 1},
    "updated_at": "2026-03-01",
    "domain_url": "https://example.com",
    # Annotation fields
    "annotation_author": "Jane Smith",
    "annotation_content": "We should revisit the schema markup strategy for product pages.",
    # Commitment fields
    "tier": "growth",
    "monthly_fee_usd": "149.00",
    "monthly_fee_currency": "USD",
    "usage_pct": 90,
    "cycle_end": "2026-04-01",
    # Alert fields
    "rule_name": "CPU saturation",
    "severity": "critical",
    "metric_key": "node.cpu.utilization",
    "current_value": "97.2%",
    "threshold_value": "90%",
    "timestamp": "2026-03-07T21:30:00Z",
    "metric_value": 72,
    "baseline_metric_value": 85,
    # Model lifecycle fields
    "provider": "google",
    "alert_type": "model_deprecation",
    "affected_models": "gemini-2.5-flash",
    "description": "The provider announced a retirement date for a configured model.",
    "source_url": "https://ai.google.dev/gemini-api/docs/changelog",
    # Lead capture fields
    "lead_email": "prospect@company.com",
    "lead_url": "https://prospect-company.com",
    "lead_entity": "Prospect Company",
    "lead_id": "lead-20260302-017",
    # Sitemap crawl fields
    "sitemap_url": "https://example.com/sitemap.xml",
    "total_urls": 247,
    "completed_urls": 230,
    "failed_urls": 17,
    # Custom domain fields
    "domain": "audits.acme.com",
    "dns_target": "proxy.qiko.ai",
    "preview_url": "https://audits.acme.com",
    # Trial fields
    "inviter_name": "Dana Ops",
    "admin_name": "Dana Ops",
    "register_url": "https://qiko.ai/signal/register?invite=abc",
    "upgrade_url": "https://qiko.ai/signal/dashboard/billing",
    "feedback_url": "https://qiko.ai/signal/trial-feedback?token=abc",
    "trial_audit_limit": 5,
    "trial_duration_days": 14,
    "trial_ended_at": "2026-03-15",
    "invitation_expires_at": "2026-03-21",
}


def render_template(template_key: str, context: Mapping[str, Any]) -> RenderedEmail:
    definition = TEMPLATE_DEFINITIONS.get(template_key)
    if definition is None:
        raise ValueError(f"Unsupported email template: {template_key}")

    payload = dict(context)
    base_url = app_base_url()
    raw_custom_logo_url = payload.get("custom_logo_url")
    raw_logo_light_url = payload.get("logo_light_url")
    raw_logo_dark_url = payload.get("logo_dark_url")
    has_explicit_logo_input = any(
        str(value or "").strip()
        for value in (raw_custom_logo_url, raw_logo_light_url, raw_logo_dark_url)
    )
    payload.setdefault("brand_name", "Qiko Signal")
    payload.setdefault("brand_mark", "SX")
    payload.setdefault("current_year", datetime.now(timezone.utc).year)
    payload.setdefault("support_address", _support_address())
    payload.setdefault("email", context.get("email") or "there")
    payload.setdefault("recipient_name", _recipient_name(payload))
    payload.setdefault("dashboard_url", f"{base_url}/dashboard")
    payload.setdefault("manage_billing_url", f"{base_url}/dashboard/billing")
    payload.setdefault("billing_url", payload.get("manage_billing_url"))
    payload.setdefault(
        "formatted_amount",
        _format_money(
            payload.get("amount_due") or payload.get("amount_paid"), payload.get("currency")
        ),
    )
    payload.setdefault("plan_name_display", _humanize(payload.get("plan_name")))
    payload.setdefault("previous_plan_display", _humanize(payload.get("previous_plan")))
    payload.setdefault("current_plan_display", _humanize(payload.get("current_plan")))
    payload.setdefault("condition_display", _humanize(payload.get("condition")))
    payload.setdefault("target_host", _short_target(payload.get("target_url")))
    payload.setdefault(
        "domain_suffix", f" ({payload.get('domain_url')})" if payload.get("domain_url") else ""
    )
    payload.setdefault("social_links", [])
    payload.setdefault("footer_links", [])
    payload.setdefault("company_address", None)
    payload.setdefault("company_legal_name", None)
    payload.setdefault("company_trademark_text", None)
    payload.setdefault("view_in_browser_url", payload.get("browser_url"))
    payload.setdefault("brand_home_url", base_url)
    payload["brand_primary_color"] = _normalize_hex_color(
        payload.get("brand_primary_color"),
        DEFAULT_BRAND_PRIMARY,
    )
    payload["brand_secondary_color"] = _normalize_hex_color(
        payload.get("brand_secondary_color"),
        DEFAULT_BRAND_SECONDARY,
    )
    payload["brand_accent_color"] = _normalize_hex_color(
        payload.get("brand_accent_color"),
        DEFAULT_BRAND_ACCENT,
    )
    payload["is_default_brand_logo"] = not has_explicit_logo_input
    payload.setdefault(
        "aio_score",
        _aio_rollup(payload.get("aeo_score"), payload.get("geo_score")),
    )
    current_scores = payload.get("current_scores")
    if isinstance(current_scores, Mapping):
        current_scores = dict(current_scores)
        current_scores.setdefault(
            "aio",
            _aio_rollup(current_scores.get("aeo"), current_scores.get("geo")),
        )
        payload["current_scores"] = current_scores
    delta = payload.get("delta")
    if isinstance(delta, Mapping):
        delta = dict(delta)
        delta.setdefault("aio", _derive_aio_delta(delta))
        payload["delta"] = delta
    payload["custom_logo_url"] = normalize_email_logo_url(raw_custom_logo_url)
    payload["logo_light_url"] = normalize_email_logo_url(raw_logo_light_url)
    if payload["logo_light_url"] is None:
        if payload["custom_logo_url"]:
            payload["logo_light_url"] = payload["custom_logo_url"]
        elif not has_explicit_logo_input:
            payload["logo_light_url"] = _default_logo_url(base_url)
    payload["logo_dark_url"] = normalize_email_logo_url(raw_logo_dark_url)
    if payload["logo_dark_url"] is None:
        if not has_explicit_logo_input:
            payload["logo_dark_url"] = _default_logo_dark_url(base_url)
        else:
            payload["logo_dark_url"] = payload["logo_light_url"]
    payload["social_links"] = _normalize_social_links(
        payload.get("social_links"), base_url=base_url
    )
    language = _resolve_email_language(payload)
    payload.setdefault("lang", language)

    subject = definition.subject(payload) if callable(definition.subject) else definition.subject
    payload.setdefault("subject", subject)
    payload.setdefault("preheader", subject)
    payload.setdefault("email_i18n", get_email_copy(language, template_key, context=payload))
    payload.setdefault(
        "metric_name_display",
        _metric_name_display(payload.get("metric_name"), payload.get("email_i18n") or {}),
    )

    i18n_map = payload.get("email_i18n")
    period = _i18n_or(i18n_map, "score_delta_period", "last month")
    delta_map = payload.get("delta") if isinstance(payload.get("delta"), Mapping) else {}
    payload.setdefault(
        "score_movement",
        {
            key: _score_movement_text(i18n_map, _parse_delta(delta_map.get(key)), period)
            for key in ("aio", "seo")
        },
    )
    current_rank_map = (
        payload.get("current_rank") if isinstance(payload.get("current_rank"), Mapping) else {}
    )
    previous_rank_map = (
        payload.get("previous_rank") if isinstance(payload.get("previous_rank"), Mapping) else {}
    )
    payload.setdefault(
        "rank_movement",
        {
            key: _rank_movement_text(
                i18n_map, current_rank_map.get(key), previous_rank_map.get(key)
            )
            for key in ("aio", "seo")
        },
    )

    # GDPR unsubscribe plumbing
    payload.setdefault("is_transactional", False)
    if payload.get("unsubscribe_token"):
        payload.setdefault(
            "unsubscribe_url",
            f"{base_url}/api/v1/auth/unsubscribe?token={payload['unsubscribe_token']}",
        )
    else:
        payload.setdefault("unsubscribe_url", "")

    try:
        html = env.get_template(definition.html_template).render(**payload)
    except Exception:
        logger.exception("Failed to render HTML template %s", definition.html_template)
        html = f"<html><body><h1>{subject}</h1><p>{RENDER_FAILURE_MARKER}</p></body></html>"

    return RenderedEmail(
        subject=subject,
        html=html,
        text=_default_text(subject, payload),
        category=definition.category,
    )
