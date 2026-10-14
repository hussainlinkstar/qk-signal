import asyncio
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ["SSM_ENABLED"] = "0"
os.environ["DATABASE_URL"] = "postgresql://user:password@localhost:5432/testdb"

import models
from routers import admin_trial
from services import email_service, email_templates


import pytest as _pytest_for_fixtures


@_pytest_for_fixtures.fixture(autouse=True)
def _bypass_db_mail_setting(monkeypatch):
    """EmailService resolves MAIL_ENABLED from the DB first; with the in-memory
    fake sessions used here that must fall back to settings.MAIL_ENABLED."""
    monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *a, **k: None)


class FakeSession:
    def __init__(
        self,
        *,
        operational_settings: models.OperationalSetting | None = None,
        workspace: models.Workspace | None = None,
        user: models.User | None = None,
        query_errors: dict[object, Exception] | None = None,
    ):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []
        self.operational_settings = operational_settings
        self.workspace = workspace
        self.user = user
        self.query_errors = query_errors or {}

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def rollback(self):
        self.rollbacks += 1

    def query(self, entity):
        query_error = self.query_errors.get(entity)
        if query_error is not None:
            raise query_error
        return FakeQuery(self, entity)


class FakeQuery:
    def __init__(self, session: FakeSession, entity):
        self.session = session
        self.entity = entity

    def filter(self, *_args, **_kwargs):
        return self

    def limit(self, _value):
        return self

    def all(self):
        if self.entity is models.Workspace.id and self.session.workspace is not None:
            return [type("WorkspaceIdRow", (), {"id": self.session.workspace.id})()]
        return []

    def first(self):
        if self.entity is models.OperationalSetting:
            return self.session.operational_settings
        if self.entity is models.Workspace:
            return self.session.workspace
        if self.entity is models.User:
            return self.session.user
        return None


def _white_label_owner(owner_id: int = 1001) -> models.User:
    """Return a minimal User with a white-label-eligible subscription."""
    user = models.User(id=owner_id, email="owner@example.com", hashed_password="x")
    user.subscription = models.Subscription(
        id=1,
        user_id=owner_id,
        stripe_customer_id="cus_fake",
        plan_type="plan_executive",
        status="active",
    )
    return user


def test_render_template_formats_invoice_amount_and_category():
    rendered = email_templates.render_template(
        "invoice.paid",
        {
            "email": "finance@example.com",
            "amount_due": 19900,
            "currency": "usd",
            "manage_billing_url": "https://app.example.com/dashboard/billing",
        },
    )

    assert rendered.subject == "Payment received"
    assert rendered.category == "billing"
    assert "199.00 USD" in rendered.html
    assert "https://app.example.com/dashboard/billing" in rendered.text


def test_queue_template_email_creates_outbox_entry(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_template_email(
        to_email="ops@example.com",
        template_key="audit.completed",
        context={
            "target_url": "https://example.com",
            "report_url": "https://app.example.com/dashboard/reports/42",
            "geo_score": 91,
            "seo_score": 84,
            "aeo_score": 88,
        },
        user_id=12,
        correlation_id="audit-42",
    )

    assert isinstance(entry, models.EmailOutbox)
    assert entry.user_id == 12
    assert entry.category == "audit_notification"
    assert entry.template_key == "audit.completed"
    assert entry.correlation_id == "audit-42"
    assert "Your audit is ready" in entry.html_body
    assert session.added[-1] is entry


def test_queue_email_creates_outbox_entry(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)

    entry = email_service.queue_email(
        session,
        to_email="trial@example.com",
        subject="Trial invitation",
        html_body="<p>hello</p>",
        category="trial_invitation",
        correlation_id="trial.invitation:42",
    )

    assert isinstance(entry, models.EmailOutbox)
    assert entry.to_email == "trial@example.com"
    assert entry.subject == "Trial invitation"
    assert entry.category == "trial_invitation"
    assert entry.correlation_id == "trial.invitation:42"
    assert entry.status == "pending"
    assert session.commits == 1
    assert session.refreshed == [entry]


def test_queue_email_returns_none_when_mail_disabled(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", False, raising=False)
    monkeypatch.setattr(
        "core.db_settings_resolver.resolve_db_setting",
        lambda key, _db: False if key == "MAIL_ENABLED" else None,
    )

    entry = email_service.queue_email(
        session,
        to_email="trial@example.com",
        subject="Trial invitation",
        html_body="<p>hello</p>",
    )

    assert entry is None
    assert session.added == []
    assert session.commits == 0


def test_email_service_rolls_back_when_db_settings_lookup_fails(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "core.db_settings_resolver.resolve_db_setting",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("relation operational_settings does not exist")
        ),
    )

    service = email_service.EmailService(session)

    assert service._enabled is True
    assert service._max_attempts == int(
        getattr(email_service.settings, "EMAIL_OUTBOX_MAX_ATTEMPTS", 5) or 5
    )
    assert session.rollbacks == 1


def test_render_template_localizes_audit_completed_email_language():
    rendered = email_templates.render_template(
        "audit.completed",
        {
            "email": "ops@example.com",
            "target_url": "https://example.com",
            "report_url": "https://app.example.com/dashboard/reports/42",
            "geo_score": 91,
            "seo_score": 84,
            "aeo_score": 88,
            "language": "ro",
        },
    )

    assert rendered.subject == "Audit finalizat pentru example.com"
    assert '<html lang="ro"' in rendered.html
    assert "Deschide raportul de audit" in rendered.html


def test_rendered_email_css_blocks_stay_within_gmail_safe_size():
    rendered = email_templates.render_template(
        "audit.completed",
        {
            "email": "ops@example.com",
            "target_url": "https://example.com",
            "report_url": "https://app.example.com/dashboard/reports/42",
            "geo_score": 91,
            "seo_score": 84,
            "aeo_score": 88,
        },
    )

    style_blocks = re.findall(
        r"<style\b[^>]*>(.*?)</style>",
        rendered.html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    assert len(style_blocks) >= 4
    assert all(len(block) < 8192 for block in style_blocks)


def test_send_welcome_email_commits_outbox_entry(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    monkeypatch.setattr(
        email_service.settings, "FRONTEND_URL", "https://app.example.com", raising=False
    )
    service = email_service.EmailService(session)

    entry = asyncio.run(
        service.send_welcome_email(
            "founder@example.com",
            user_id=7,
            user_name="Acme",
            correlation_id="auth.welcome:7",
        )
    )

    assert isinstance(entry, models.EmailOutbox)
    assert entry.correlation_id == "auth.welcome:7"
    assert entry.to_email == "founder@example.com"
    assert session.commits == 1
    assert session.refreshed == [entry]


def test_send_trial_invitation_email_uses_shared_template_layout(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    monkeypatch.setenv("FRONTEND_URL", "https://app.example.com")

    invitation = models.TrialInvitation(
        id=42,
        email="trial@example.com",
        contact_name="Agency Owner",
        token="trial-token",
        expires_at=datetime(2026, 4, 7, tzinfo=timezone.utc),
    )

    admin_trial._send_trial_invitation_email(
        db=session,
        invitation=invitation,
        admin_name="Qiko Signal Sales",
    )

    entry = session.added[-1]
    assert isinstance(entry, models.EmailOutbox)
    assert entry.to_email == "trial@example.com"
    assert entry.template_key == "trial.invitation"
    assert entry.category == "trial_invitation"
    assert "Agency Trial Invitation" in entry.html_body
    assert 'class="meta-chip' in entry.html_body
    assert "trial_token=trial-token" in entry.html_body
    assert "Qiko Signal Sales invited you to try" in entry.html_body
    assert session.commits == 1
    assert session.refreshed == [entry]


def test_queue_trial_feedback_request_email_uses_shared_template_layout(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_trial_feedback_request_email(
        "trial@example.com",
        feedback_url="https://app.example.com/trial-feedback/feedback-token",
        admin_name="Qiko Signal Sales",
        trial_ended_at="April 07, 2026",
        user_id=99,
        user_name="Agency Owner",
        correlation_id="trial.feedback_request:99",
    )

    assert isinstance(entry, models.EmailOutbox)
    assert entry.to_email == "trial@example.com"
    assert entry.template_key == "trial.feedback_request"
    assert entry.category == "trial_feedback"
    assert "How was your trial?" in entry.html_body
    assert "feedback/feedback-token" in entry.html_body
    assert "Qiko Signal Sales would appreciate your feedback" in entry.html_body


def test_client_invitation_template_uses_transactional_footer_copy():
    rendered = email_templates.render_template(
        "workspace.client_invitation",
        {
            "email": "client@example.com",
            "recipient_name": "Portal Client",
            "workspace_name": "Acme Workspace",
            "agency_name": "Acme Agency",
            "invitation_url": "https://app.example.com/invite/client",
            "portal_url": "https://app.example.com/portal",
            "project_names": ["Project A"],
        },
    )

    assert "unsubscribe" not in rendered.html.lower()
    assert "because you have an account" not in rendered.html.lower()
    assert "set your password and finish access setup" in rendered.html.lower()


def test_render_template_supports_commitment_activation():
    rendered = email_templates.render_template(
        "commitment.activated",
        {
            "email": "finance@example.com",
            "user_name": "Acme Lab",
            "tier": "growth",
            "committed_credits": 2000,
            "monthly_fee_usd": "180.00",
            "cycle_end": "2026-04-01T00:00:00+00:00",
        },
    )

    assert "growth" in rendered.subject.lower()
    assert rendered.category == "billing"
    assert "Growth" in rendered.html
    assert "180.00" in rendered.html
    assert "2026-04-01" in rendered.html
    # SIGV2-1080: the committed volume is denominated in internal credits and
    # must never reach a customer, even when the sender still passes it.
    assert "2000" not in rendered.html
    assert "2,000" not in rendered.html


def test_render_template_renders_dynamic_footer_context():
    rendered = email_templates.render_template(
        "invoice.paid",
        {
            "email": "finance@example.com",
            "amount_due": 19900,
            "currency": "usd",
            "logo_light_url": "https://cdn.example.com/branding/acme-logo.png",
            "social_links": [
                {
                    "platform": "linkedin",
                    "label": "LinkedIn",
                    "glyph": "in",
                    "url": "https://linkedin.com/company/thothgraph",
                },
                {"platform": "x", "label": "X", "glyph": "X", "url": "https://x.com/thothgraph"},
            ],
            "footer_links": [
                {"label": "About", "url": "https://thothgraph.com/about"},
                {"label": "Privacy", "url": "https://thothgraph.com/privacy"},
            ],
            "company_legal_name": "Qiko Signal Labs SRL",
            "company_address": "42 Orbit Avenue\nBucharest",
            "company_trademark_text": "Qiko Signal is a trademark.",
        },
    )

    # The footer was intentionally simplified (commit 91b6b3d7): the social
    # "Follow us" row, footer nav links and the trademark line were removed.
    # The footer now keeps the logo, support, copyright, and — on marketing
    # emails only — the unsubscribe link and the company legal name/address.
    assert "acme-logo.png" in rendered.html
    assert "Qiko Signal Labs SRL" in rendered.html
    assert "42 Orbit Avenue" in rendered.html
    # Removed footer elements must no longer be rendered.
    assert "linkedin.com/company/thothgraph" not in rendered.html
    assert "x.com/thothgraph" not in rendered.html
    assert "/email/social/linkedin.svg" not in rendered.html
    assert "thothgraph.com/privacy" not in rendered.html
    assert "Qiko Signal is a trademark." not in rendered.html


def test_render_template_skips_svg_logo_assets_for_email_clients():
    rendered = email_templates.render_template(
        "invoice.paid",
        {
            "email": "finance@example.com",
            "brand_name": "Acme Agency",
            "custom_logo_url": "https://cdn.example.com/branding/acme-logo.svg",
        },
    )

    assert "https://cdn.example.com/branding/acme-logo.svg" not in rendered.html
    assert "Acme Agency" in rendered.html


def test_admin_system_alert_template_renders_new_base_layout():
    rendered = email_templates.render_template(
        "admin_system_alert",
        {
            "email": "ops@example.com",
            "dashboard_url": "https://app.example.com/dashboard",
            "severity": "critical",
            "rule_name": "CPU saturation",
            "metric_key": "node.cpu.utilization",
            "current_value": "97.2%",
            "threshold_value": "90%",
            "message": "CPU stayed above threshold for 5m.",
            "timestamp": "2026-03-07T21:30:00Z",
        },
    )

    assert "Email template rendering failed." not in rendered.html
    assert "System alert triggered" in rendered.html
    assert "node.cpu.utilization" in rendered.html


def test_queue_template_email_uses_platform_footer_defaults(monkeypatch):
    session = FakeSession(
        operational_settings=models.OperationalSetting(
            admin_settings_payload={
                "email_footer_defaults": {
                    "social_linkedin_url": "https://linkedin.com/company/platform-default",
                    "footer_about_url": "https://platform.example/about",
                    "footer_privacy_url": "https://platform.example/privacy",
                    "company_legal_name": "Platform Legal Name SRL",
                    "company_trademark_text": "Platform is a trademark.",
                }
            }
        )
    )
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_template_email(
        to_email="ops@example.com",
        template_key="invoice.paid",
        context={
            "email": "ops@example.com",
            "amount_due": 1200,
            "currency": "usd",
        },
    )

    assert isinstance(entry, models.EmailOutbox)
    # Simplified footer keeps only the company legal name from platform defaults;
    # socials, footer nav links, and trademark line were intentionally removed.
    assert "Platform Legal Name SRL" in entry.html_body
    assert "linkedin.com/company/platform-default" not in entry.html_body
    assert "platform.example/about" not in entry.html_body
    assert "platform.example/privacy" not in entry.html_body
    assert "Platform is a trademark." not in entry.html_body


def test_queue_template_email_workspace_footer_overrides_platform_defaults(monkeypatch):
    session = FakeSession(
        operational_settings=models.OperationalSetting(
            admin_settings_payload={
                "email_footer_defaults": {
                    "social_linkedin_url": "https://linkedin.com/company/platform-default",
                    "footer_about_url": "https://platform.example/about",
                    "company_legal_name": "Platform Legal Name SRL",
                }
            }
        ),
        workspace=models.Workspace(
            id=42,
            name="Workspace One",
            owner_id=1001,
            social_linkedin_url="https://linkedin.com/company/workspace-brand",
            footer_about_url="https://workspace.example/about",
            company_legal_name="Workspace Legal Name SRL",
        ),
        user=_white_label_owner(),
    )
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_template_email(
        to_email="ops@example.com",
        template_key="invoice.paid",
        context={
            "email": "ops@example.com",
            "amount_due": 1200,
            "currency": "usd",
        },
        workspace_id=42,
    )

    assert isinstance(entry, models.EmailOutbox)
    # Workspace override still applies to the retained footer field (legal name);
    # the platform default must not leak through. Socials/nav links were removed
    # from the footer entirely (commit 91b6b3d7).
    assert "Workspace Legal Name SRL" in entry.html_body
    assert "Platform Legal Name SRL" not in entry.html_body
    assert "linkedin.com/company/workspace-brand" not in entry.html_body
    assert "workspace.example/about" not in entry.html_body
    assert "linkedin.com/company/platform-default" not in entry.html_body
    assert "platform.example/about" not in entry.html_body


def test_queue_template_email_workspace_svg_logo_falls_back_to_brand_text(monkeypatch):
    session = FakeSession(
        workspace=models.Workspace(
            id=42,
            name="Workspace One",
            owner_id=1001,
            company_name="Acme Workspace",
            custom_logo_url="https://cdn.example.com/branding/acme-logo.svg",
        ),
        user=_white_label_owner(),
    )
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_template_email(
        to_email="ops@example.com",
        template_key="invoice.paid",
        context={
            "email": "ops@example.com",
            "amount_due": 1200,
            "currency": "usd",
        },
        workspace_id=42,
    )

    assert isinstance(entry, models.EmailOutbox)
    assert "https://cdn.example.com/branding/acme-logo.svg" not in entry.html_body
    assert "Acme Workspace" in entry.html_body


def test_queue_template_email_workspace_branding_skipped_without_white_label(monkeypatch):
    """Workspace branding fields must NOT override platform defaults when the
    owner's plan does not include white-label."""
    non_wl_user = models.User(id=1001, email="owner@example.com", hashed_password="x")
    non_wl_user.subscription = models.Subscription(
        id=1,
        user_id=1001,
        stripe_customer_id="cus_basic",
        plan_type="plan_specialist",
    )
    session = FakeSession(
        workspace=models.Workspace(
            id=42,
            name="Workspace One",
            owner_id=1001,
            company_name="Acme Non-WL",
            social_linkedin_url="https://linkedin.com/company/acme-nwl",
            company_legal_name="Acme Non-WL SRL",
        ),
        user=non_wl_user,
    )
    monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
    service = email_service.EmailService(session)

    entry = service.queue_template_email(
        to_email="ops@example.com",
        template_key="invoice.paid",
        context={
            "email": "ops@example.com",
            "amount_due": 1200,
            "currency": "usd",
        },
        workspace_id=42,
    )

    assert isinstance(entry, models.EmailOutbox)
    assert "linkedin.com/company/acme-nwl" not in entry.html_body
    assert "Acme Non-WL SRL" not in entry.html_body
    assert entry.from_name is None
    assert entry.reply_to is None
