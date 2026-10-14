from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import EmailStr
from sqlalchemy.orm import Session

import models
from app.config.plans import (
    can_use_feature,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from core.config import settings
from services.email_sender import send as send_email_now
from services.email_templates import render_template
from services.report_i18n_service import normalize_report_language


EMAIL_FOOTER_SOCIAL_FIELDS = (
    ("x", "social_x_url", "X", "X"),
    ("linkedin", "social_linkedin_url", "LinkedIn", "in"),
)
EMAIL_FOOTER_LINK_FIELDS = (
    ("About", "footer_about_url"),
    ("Blog", "footer_blog_url"),
    ("Support", "footer_support_url"),
    ("Legal", "footer_legal_url"),
    ("Preferences", "footer_preferences_url"),
    ("Privacy", "footer_privacy_url"),
)
EMAIL_FOOTER_URL_FIELD_NAMES = tuple(
    [item[1] for item in EMAIL_FOOTER_SOCIAL_FIELDS]
    + [item[1] for item in EMAIL_FOOTER_LINK_FIELDS]
)
EMAIL_FOOTER_TEXT_FIELD_NAMES = (
    "company_address",
    "company_legal_name",
    "company_trademark_text",
)
EMAIL_FOOTER_BRANDING_FIELD_NAMES = (
    "brand_primary_color",
    "brand_secondary_color",
    "logo_light_url",
    "logo_dark_url",
)
EMAIL_FOOTER_FIELD_NAMES = (
    EMAIL_FOOTER_URL_FIELD_NAMES + EMAIL_FOOTER_TEXT_FIELD_NAMES + EMAIL_FOOTER_BRANDING_FIELD_NAMES
)


class EmailService:
    def __init__(self, db: Session | None = None):
        self.db = db
        self._logger = logging.getLogger(__name__)
        if db is not None:
            try:
                from core.db_settings_resolver import resolve_db_setting

                mail_enabled = resolve_db_setting("MAIL_ENABLED", db)
                self._enabled = (
                    bool(mail_enabled) if mail_enabled is not None else settings.MAIL_ENABLED
                )
                max_attempts = resolve_db_setting("EMAIL_OUTBOX_MAX_ATTEMPTS", db)
                self._max_attempts = (
                    int(max_attempts)
                    if max_attempts is not None
                    else int(getattr(settings, "EMAIL_OUTBOX_MAX_ATTEMPTS", 5) or 5)
                )
            except Exception:
                self._rollback_db_session()
                self._enabled = settings.MAIL_ENABLED
                self._max_attempts = int(getattr(settings, "EMAIL_OUTBOX_MAX_ATTEMPTS", 5) or 5)
        else:
            self._enabled = settings.MAIL_ENABLED
            self._max_attempts = int(getattr(settings, "EMAIL_OUTBOX_MAX_ATTEMPTS", 5) or 5)

    def _rollback_db_session(self) -> None:
        if self.db is None or not hasattr(self.db, "rollback"):
            return
        try:
            self.db.rollback()
        except Exception:
            pass

    def _frontend_url(self) -> str:
        base_url = (
            getattr(settings, "FRONTEND_URL", None)
            or os.getenv("FRONTEND_URL")
            or os.getenv("APP_BASE_URL")
            or "https://qiko.ai/signal"
        )
        return str(base_url).rstrip("/")

    def _resolve_workspace_for_context(
        self,
        *,
        workspace_id: int | None,
        user_id: int | None,
        context: Mapping[str, Any],
    ) -> models.Workspace | None:
        if self.db is None or not hasattr(self.db, "query"):
            return None

        resolved_workspace_id = workspace_id
        if resolved_workspace_id is None:
            context_workspace_id = context.get("workspace_id")
            if context_workspace_id is not None:
                try:
                    resolved_workspace_id = int(context_workspace_id)
                except (TypeError, ValueError):
                    resolved_workspace_id = None

        if resolved_workspace_id is None and context.get("project_id") is not None:
            try:
                project_id = int(context.get("project_id"))
            except (TypeError, ValueError):
                project_id = None
            if project_id is not None:
                project = (
                    self.db.query(models.Project).filter(models.Project.id == project_id).first()
                )
                if project is not None:
                    resolved_workspace_id = project.workspace_id

        if resolved_workspace_id is None and user_id is not None:
            owned_workspaces = (
                self.db.query(models.Workspace.id)
                .filter(models.Workspace.owner_id == user_id)
                .limit(2)
                .all()
            )
            if len(owned_workspaces) == 1:
                resolved_workspace_id = int(owned_workspaces[0].id)

        if resolved_workspace_id is None:
            return None

        workspace = (
            self.db.query(models.Workspace)
            .filter(models.Workspace.id == resolved_workspace_id)
            .first()
        )
        return workspace

    def _workspace_has_white_label(self, workspace: models.Workspace) -> bool:
        """Check if the workspace owner's subscription plan includes white-label."""
        try:
            owner = workspace.owner
            if owner is None and self.db is not None:
                owner = (
                    self.db.query(models.User).filter(models.User.id == workspace.owner_id).first()
                )
            if owner is None:
                return False
            plan_type = resolve_entitled_subscription_plan(owner)
            if plan_type == "plan_agency_trial":
                plan_type = None
            if plan_type is None and getattr(owner, "trial_plan", None):
                plan_type = str(owner.trial_plan).strip().lower()
            if plan_type is None:
                return False
            resolved = resolve_plan_alias(plan_type) or plan_type
            return can_use_feature(resolved, "has_white_label")
        except Exception:
            return False

    def _resolve_sender_overrides(
        self,
        *,
        workspace: models.Workspace | None,
        white_label_allowed: bool = False,
    ) -> tuple[str | None, str | None]:
        if workspace is None or not white_label_allowed:
            return None, None
        sender_name = str(workspace.email_sender_name or "").strip() or None
        reply_to = str(workspace.email_reply_to or "").strip() or None
        return sender_name, reply_to

    def _default_platform_footer_values(self) -> dict[str, str | None]:
        frontend_url = self._frontend_url()
        return {
            "social_facebook_url": None,
            "social_x_url": None,
            "social_instagram_url": None,
            "social_linkedin_url": None,
            "social_youtube_url": None,
            "social_tiktok_url": None,
            "company_address": None,
            "company_legal_name": "Qiko Signal",
            "company_trademark_text": "Qiko Signal is a registered trademark of Qiko Signal SRL.",
            "footer_about_url": f"{frontend_url}/about",
            "footer_blog_url": f"{frontend_url}/blog",
            "footer_support_url": f"{frontend_url}/contact",
            "footer_legal_url": f"{frontend_url}/terms",
            "footer_preferences_url": f"{frontend_url}/preferences",
            "footer_privacy_url": f"{frontend_url}/privacy",
            "brand_primary_color": None,
            "brand_secondary_color": None,
            "logo_light_url": None,
            "logo_dark_url": None,
        }

    def _normalize_footer_field_value(self, field_name: str, value: object) -> str | None:
        normalized = str(value or "").strip() or None
        if normalized is None:
            return None
        if field_name in EMAIL_FOOTER_URL_FIELD_NAMES and not (
            normalized.startswith("http://") or normalized.startswith("https://")
        ):
            return None
        return normalized

    def _load_platform_footer_values(self) -> dict[str, str | None]:
        defaults = self._default_platform_footer_values()
        if self.db is None or not hasattr(self.db, "query"):
            return defaults

        try:
            operational_settings = self.db.query(models.OperationalSetting).first()
        except Exception:
            self._rollback_db_session()
            return defaults
        if operational_settings is None:
            return defaults

        payload = (
            operational_settings.admin_settings_payload
            if isinstance(operational_settings.admin_settings_payload, dict)
            else {}
        )
        raw_footer_defaults = payload.get("email_footer_defaults")
        if not isinstance(raw_footer_defaults, dict):
            return defaults

        for field_name in EMAIL_FOOTER_FIELD_NAMES:
            if field_name not in raw_footer_defaults:
                continue
            defaults[field_name] = self._normalize_footer_field_value(
                field_name,
                raw_footer_defaults.get(field_name),
            )
        return defaults

    def _build_footer_context_from_values(self, values: Mapping[str, str | None]) -> dict[str, Any]:
        frontend_url = self._frontend_url()
        social_icon_paths = {
            "x": "/email/social/x.svg",
            "linkedin": "/email/social/linkedin.svg",
        }
        social_icon_dark_paths = {
            "x": "/email/social/x-white.svg",
            "linkedin": "/email/social/linkedin-white.svg",
        }
        social_links: list[dict[str, str]] = []
        for platform, field_name, label, glyph in EMAIL_FOOTER_SOCIAL_FIELDS:
            normalized_url = self._normalize_footer_field_value(field_name, values.get(field_name))
            if not normalized_url:
                continue
            social_links.append(
                {
                    "platform": platform,
                    "url": normalized_url,
                    "label": label,
                    "glyph": glyph,
                    "icon_url": f"{frontend_url}{social_icon_paths[platform]}",
                    "icon_dark_url": f"{frontend_url}{social_icon_dark_paths[platform]}",
                }
            )

        footer_links: list[dict[str, str]] = []
        for label, field_name in EMAIL_FOOTER_LINK_FIELDS:
            normalized_url = self._normalize_footer_field_value(field_name, values.get(field_name))
            if not normalized_url:
                continue
            footer_links.append({"label": label, "url": normalized_url})

        return {
            "social_links": social_links,
            "footer_links": footer_links,
            "company_address": self._normalize_footer_field_value(
                "company_address",
                values.get("company_address"),
            ),
            "company_legal_name": self._normalize_footer_field_value(
                "company_legal_name",
                values.get("company_legal_name"),
            ),
            "company_trademark_text": self._normalize_footer_field_value(
                "company_trademark_text",
                values.get("company_trademark_text"),
            ),
            "brand_primary_color": self._normalize_footer_field_value(
                "brand_primary_color",
                values.get("brand_primary_color"),
            ),
            "brand_secondary_color": self._normalize_footer_field_value(
                "brand_secondary_color",
                values.get("brand_secondary_color"),
            ),
            "logo_light_url": self._normalize_footer_field_value(
                "logo_light_url",
                values.get("logo_light_url"),
            ),
            "logo_dark_url": self._normalize_footer_field_value(
                "logo_dark_url",
                values.get("logo_dark_url"),
            ),
        }

    def _workspace_has_footer_overrides(self, workspace: models.Workspace) -> bool:
        for field_name in EMAIL_FOOTER_FIELD_NAMES:
            raw_value = getattr(workspace, field_name, None)
            if str(raw_value or "").strip():
                return True
        return False

    def _workspace_footer_values(self, workspace: models.Workspace) -> dict[str, str | None]:
        return {
            "social_facebook_url": str(workspace.social_facebook_url or "").strip() or None,
            "social_x_url": str(workspace.social_x_url or "").strip() or None,
            "social_instagram_url": str(workspace.social_instagram_url or "").strip() or None,
            "social_linkedin_url": str(workspace.social_linkedin_url or "").strip() or None,
            "social_youtube_url": str(workspace.social_youtube_url or "").strip() or None,
            "social_tiktok_url": str(workspace.social_tiktok_url or "").strip() or None,
            "company_address": str(workspace.company_address or "").strip() or None,
            "company_legal_name": str(workspace.company_legal_name or "").strip() or None,
            "company_trademark_text": str(workspace.company_trademark_text or "").strip() or None,
            "footer_about_url": str(workspace.footer_about_url or "").strip() or None,
            "footer_blog_url": str(workspace.footer_blog_url or "").strip() or None,
            "footer_support_url": str(workspace.footer_support_url or "").strip() or None,
            "footer_legal_url": str(workspace.footer_legal_url or "").strip() or None,
            "footer_preferences_url": str(workspace.footer_preferences_url or "").strip() or None,
            "footer_privacy_url": str(workspace.footer_privacy_url or "").strip() or None,
        }

    def _build_workspace_footer_context(self, workspace: models.Workspace) -> dict[str, Any]:
        frontend_url = self._frontend_url()
        workspace_footer_context = self._build_footer_context_from_values(
            self._workspace_footer_values(workspace)
        )
        if not workspace_footer_context.get("company_legal_name"):
            workspace_footer_context["company_legal_name"] = (
                str(workspace.company_name or "").strip() or None
            )
        custom_logo = str(workspace.custom_logo_url or "").strip()
        logo_light_url = custom_logo or f"{frontend_url}/email/qiko-signal-logo-light.png"
        logo_dark_url = custom_logo or f"{frontend_url}/email/qiko-signal-logo-dark.png"
        brand_primary_color = str(workspace.primary_color or "").strip() or None
        brand_secondary_color = str(workspace.secondary_color or "").strip() or None

        return {
            "social_links": workspace_footer_context["social_links"],
            "footer_links": workspace_footer_context["footer_links"],
            "company_address": workspace_footer_context["company_address"],
            "company_legal_name": workspace_footer_context["company_legal_name"],
            "company_trademark_text": workspace_footer_context["company_trademark_text"],
            "email_brand_name": str(workspace.company_name or "").strip() or None,
            "logo_light_url": logo_light_url,
            "logo_dark_url": logo_dark_url,
            "brand_primary_color": brand_primary_color,
            "brand_secondary_color": brand_secondary_color,
            "brand_home_url": frontend_url,
        }

    def queue_template_email(
        self,
        *,
        to_email: str,
        template_key: str,
        context: Mapping[str, Any],
        language: str | None = None,
        user_id: int | None = None,
        workspace_id: int | None = None,
        correlation_id: str | None = None,
        commit: bool = False,
    ) -> models.EmailOutbox | None:
        if not self._enabled:
            self._logger.info("Skipping %s email because outbound mail is disabled.", template_key)
            return None
        if self.db is None:
            raise RuntimeError("A database session is required to queue email notifications.")

        # ── GDPR notification gate ──────────────────────────────────
        # Transactional emails (verification, password_reset) always go through.
        # Lifecycle/marketing emails are blocked when the user opted out.
        _TRANSACTIONAL_KEYS = {"auth.verification", "auth.password_reset"}
        # Operational emails always delivered (workspace invitations, domain events, annotations).
        _OPERATIONAL_KEYS = {
            "workspace.client_invitation",
            "workspace.domain_verified",
            "workspace.ssl_provisioned",
            "workspace.domain_error",
            "annotation.created",
            "annotation.replied",
        }
        is_transactional = template_key in _TRANSACTIONAL_KEYS
        is_operational = template_key in _OPERATIONAL_KEYS

        # Map template categories (from email_templates.py) → User column for granular opt-out.
        _CATEGORY_TO_PREFERENCE: dict[str, str] = {
            "account_notification": "notify_product_updates",
            "trial_invitation": "notify_product_updates",
            "trial_feedback": "notify_product_updates",
            "report_delivery": "notify_product_updates",
            "lead_notification": "notify_product_updates",
            "audit_notification": "notify_audit_alerts",
            "alert_notification": "notify_audit_alerts",
            "system_alert": "notify_audit_alerts",
            "billing": "notify_billing",
        }

        if (
            not is_transactional
            and not is_operational
            and user_id
            and self.db
            and hasattr(self.db, "query")
        ):
            user = self.db.query(models.User).filter(models.User.id == user_id).first()
            if user and not user.notifications_enabled:
                self._logger.info(
                    "Skipping %s email to user %s, notifications disabled.",
                    template_key,
                    user_id,
                )
                return None
            # Granular per-category check
            if user and user.notifications_enabled:
                from services.email_templates import TEMPLATE_DEFINITIONS

                tpl_def = TEMPLATE_DEFINITIONS.get(template_key)
                if tpl_def:
                    pref_attr = _CATEGORY_TO_PREFERENCE.get(tpl_def.category)
                    if pref_attr and not getattr(user, pref_attr, True):
                        self._logger.info(
                            "Skipping %s email to user %s, %s preference disabled.",
                            template_key,
                            user_id,
                            pref_attr,
                        )
                        return None
            # Inject unsubscribe token so templates can render the link
            if user and user.unsubscribe_token:
                context = dict(context, unsubscribe_token=user.unsubscribe_token)

        resolved_language = normalize_report_language(
            language
            or (str(context.get("lang")) if context.get("lang") else None)
            or (str(context.get("language")) if context.get("language") else None)
            or (str(context.get("report_language")) if context.get("report_language") else None)
        )

        payload = dict(context)
        payload.setdefault("email", context.get("email") or to_email)
        payload.setdefault("is_transactional", is_transactional or is_operational)
        payload.setdefault("lang", resolved_language)
        payload.setdefault("language", resolved_language)
        platform_footer_context = self._build_footer_context_from_values(
            self._load_platform_footer_values()
        )
        for key, value in platform_footer_context.items():
            payload.setdefault(key, value)
        workspace = self._resolve_workspace_for_context(
            workspace_id=workspace_id,
            user_id=user_id,
            context=context,
        )
        white_label_allowed = workspace is not None and self._workspace_has_white_label(workspace)
        if workspace is not None and white_label_allowed:
            footer_context = self._build_workspace_footer_context(workspace)
            workspace_has_footer_overrides = self._workspace_has_footer_overrides(workspace)
            for key, value in footer_context.items():
                if key in {
                    "social_links",
                    "footer_links",
                    "company_address",
                    "company_legal_name",
                    "company_trademark_text",
                }:
                    if workspace_has_footer_overrides:
                        payload[key] = value
                        continue
                payload.setdefault(key, value)
            if footer_context.get("email_brand_name"):
                payload.setdefault("brand_name", footer_context["email_brand_name"])
        rendered = render_template(template_key, payload)
        sender_name_override, reply_to_override = self._resolve_sender_overrides(
            workspace=workspace,
            white_label_allowed=white_label_allowed,
        )
        entry = models.EmailOutbox(
            user_id=user_id,
            to_email=to_email,
            from_name=sender_name_override,
            reply_to=reply_to_override,
            subject=rendered.subject,
            html_body=rendered.html,
            text_body=rendered.text,
            category=rendered.category,
            template_key=template_key,
            correlation_id=correlation_id,
            status="pending",
        )
        self.db.add(entry)
        if commit:
            self.db.commit()
            self.db.refresh(entry)
        return entry

    async def send_verification_email(
        self,
        email: EmailStr,
        token: str,
        *,
        user_id: int | None = None,
    ) -> models.EmailOutbox | None:
        verification_url = f"{self._frontend_url()}/verify-email?token={token}"
        return self.queue_template_email(
            to_email=str(email),
            template_key="auth.verification",
            context={"verification_url": verification_url},
            user_id=user_id,
            correlation_id=f"auth.verify:{email}",
            commit=True,
        )

    async def send_password_reset_email(
        self,
        email: EmailStr,
        token: str,
        *,
        user_id: int | None = None,
    ) -> models.EmailOutbox | None:
        reset_url = f"{self._frontend_url()}/reset-password?token={token}"
        return self.queue_template_email(
            to_email=str(email),
            template_key="auth.password_reset",
            context={"reset_url": reset_url},
            user_id=user_id,
            correlation_id=f"auth.password-reset:{email}",
            commit=True,
        )

    async def send_welcome_email(
        self,
        email: EmailStr,
        *,
        user_id: int | None = None,
        user_name: str | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="auth.welcome",
            context={
                "user_name": user_name,
                "dashboard_url": f"{self._frontend_url()}/dashboard",
            },
            user_id=user_id,
            correlation_id=correlation_id
            or (f"auth.welcome:{user_id}" if user_id is not None else f"auth.welcome:{email}"),
            commit=True,
        )

    def queue_trial_feedback_request_email(
        self,
        email: EmailStr,
        *,
        feedback_url: str,
        admin_name: str | None = None,
        trial_ended_at: str | None = None,
        user_id: int | None = None,
        user_name: str | None = None,
        correlation_id: str | None = None,
        commit: bool = True,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="trial.feedback_request",
            context={
                "feedback_url": feedback_url,
                "admin_name": admin_name,
                "trial_ended_at": trial_ended_at,
                "user_name": user_name,
            },
            user_id=user_id,
            correlation_id=correlation_id or f"trial.feedback_request:{email}",
            commit=commit,
        )

    async def send_client_invitation_email(
        self,
        email: EmailStr,
        *,
        invitation_url: str,
        workspace_name: str,
        portal_url: str,
        agency_name: str | None = None,
        project_names: list[str] | None = None,
        user_id: int | None = None,
        invitee_name: str | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="workspace.client_invitation",
            context={
                "invitation_url": invitation_url,
                "portal_url": portal_url,
                "workspace_name": workspace_name,
                "agency_name": agency_name,
                "project_names": project_names or [],
                "user_name": invitee_name,
            },
            user_id=user_id,
            correlation_id=correlation_id or f"workspace.client-invite:{email}:{workspace_name}",
            commit=True,
        )

    async def send_project_budget_warning_email(
        self,
        email: EmailStr,
        *,
        project_name: str,
        workspace_name: str,
        consumed_scans: int,
        monthly_limit_scans: int,
        percent_consumed: float,
        settings_url: str,
        user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="budget.warning",
            context={
                "project_name": project_name,
                "workspace_name": workspace_name,
                "consumed_scans": consumed_scans,
                "monthly_limit_scans": monthly_limit_scans,
                "percent_consumed": percent_consumed,
                "settings_url": settings_url,
            },
            user_id=user_id,
            correlation_id=correlation_id or f"budget.warning:{project_name}:{email}",
            commit=True,
        )

    async def send_project_budget_exceeded_email(
        self,
        email: EmailStr,
        *,
        project_name: str,
        workspace_name: str,
        consumed_scans: int,
        monthly_limit_scans: int,
        settings_url: str,
        user_id: int | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="budget.exceeded",
            context={
                "project_name": project_name,
                "workspace_name": workspace_name,
                "consumed_scans": consumed_scans,
                "monthly_limit_scans": monthly_limit_scans,
                "settings_url": settings_url,
            },
            user_id=user_id,
            correlation_id=correlation_id or f"budget.exceeded:{project_name}:{email}",
            commit=True,
        )

    async def send_lead_captured_email(
        self,
        email: EmailStr,
        *,
        workspace_name: str | None,
        lead_email: str,
        lead_url: str,
        lead_entity: str | None,
        lead_id: int,
        dashboard_url: str,
        user_id: int | None = None,
        workspace_id: int | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="lead.captured",
            context={
                "workspace_name": workspace_name,
                "lead_email": lead_email,
                "lead_url": lead_url,
                "lead_entity": lead_entity,
                "lead_id": lead_id,
                "dashboard_url": dashboard_url,
            },
            user_id=user_id,
            workspace_id=workspace_id,
            correlation_id=correlation_id or f"lead.captured:{lead_id}:{email}",
            commit=True,
        )

    async def send_sitemap_crawl_complete_email(
        self,
        email: EmailStr,
        *,
        workspace_name: str | None,
        project_name: str,
        sitemap_url: str,
        total_urls: int,
        completed_urls: int,
        failed_urls: int,
        report_url: str,
        user_id: int | None = None,
        workspace_id: int | None = None,
        correlation_id: str | None = None,
    ) -> models.EmailOutbox | None:
        return self.queue_template_email(
            to_email=str(email),
            template_key="sitemap.crawl_complete",
            context={
                "workspace_name": workspace_name,
                "project_name": project_name,
                "sitemap_url": sitemap_url,
                "total_urls": total_urls,
                "completed_urls": completed_urls,
                "failed_urls": failed_urls,
                "report_url": report_url,
            },
            user_id=user_id,
            workspace_id=workspace_id,
            correlation_id=correlation_id or f"sitemap.crawl_complete:{project_name}:{email}",
            commit=True,
        )

    async def process_outbox_batch(self, *, limit: int = 25) -> int:
        if not self._enabled or self.db is None:
            return 0

        entries = (
            self.db.query(models.EmailOutbox)
            .filter(models.EmailOutbox.status.in_(["pending", "retry"]))
            .order_by(models.EmailOutbox.created_at.asc())
            .limit(limit)
            .all()
        )

        processed = 0
        for entry in entries:
            entry.attempts = int(entry.attempts or 0) + 1
            try:
                result = await asyncio.to_thread(
                    send_email_now,
                    to=entry.to_email,
                    subject=entry.subject,
                    html=entry.html_body,
                    text=entry.text_body,
                    category=entry.category,
                    correlation_id=entry.correlation_id,
                    from_name=entry.from_name,
                    reply_to=entry.reply_to,
                    db=self.db,
                )
                entry.status = "sent"
                entry.provider = result.get("provider")
                entry.last_error = None
                entry.sent_at = datetime.now(timezone.utc)
            except Exception as exc:
                entry.last_error = str(exc)
                entry.status = "failed" if entry.attempts >= self._max_attempts else "retry"
                self._logger.warning(
                    "Failed to deliver email outbox entry %s to %s",
                    entry.id,
                    entry.to_email,
                    exc_info=exc,
                )
            finally:
                self.db.add(entry)
                self.db.commit()
                processed += 1

        return processed


def queue_email(
    db: Session,
    *,
    to_email: str,
    subject: str,
    html_body: str | None = None,
    text_body: str | None = None,
    user_id: int | None = None,
    category: str | None = None,
    correlation_id: str | None = None,
    from_name: str | None = None,
    reply_to: str | None = None,
    commit: bool = True,
) -> models.EmailOutbox | None:
    """Queue an ad-hoc email directly in EmailOutbox."""
    service = EmailService(db)
    if not service._enabled:
        service._logger.warning(
            "Skipping ad-hoc email to %s because outbound mail is disabled.",
            to_email,
        )
        return None

    entry = models.EmailOutbox(
        user_id=user_id,
        to_email=to_email,
        from_name=from_name,
        reply_to=reply_to,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        category=category,
        correlation_id=correlation_id,
        status="pending",
    )
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    return entry
