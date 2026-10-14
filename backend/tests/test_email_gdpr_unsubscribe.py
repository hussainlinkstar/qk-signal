"""Tests for TASK-21: Email Notifications Refresh & GDPR Unsubscribe.

Covers:
- Template rendering with new white/clean design
- is_transactional flag on verification and password_reset
- Unsubscribe URL injection into lifecycle emails
- Notification gate in queue_template_email (opt-out block)
- Unsubscribe endpoint behaviour
- All 20 templates render without error
"""

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import models
from services import email_service, email_templates


# ── Helpers ──────────────────────────────────────────────────────


class FakeSession:
    """Minimal stand-in for a SQLAlchemy Session."""

    def __init__(self):
        self.added: list = []
        self.commits: int = 0
        self.refreshed: list = []
        self._users: dict[int, models.User] = {}

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def query(self, model):
        return _FakeQuery(self._users, model)


class _FakeQuery:
    def __init__(self, users: dict, model=None):
        self._users = users
        self._model = model
        self._filters = []

    def filter(self, *args):
        self._filters.extend(args)
        return self

    def limit(self, *args):
        return self

    def _matches(self):
        # Only the User table is populated in these tests; other lookups
        # (OperationalSetting, Workspace, …) resolve to nothing so the email
        # service falls back to its platform defaults.
        if self._model is not None and self._model is not models.User:
            return []
        return list(self._users.values())

    def first(self):
        matches = self._matches()
        return matches[0] if matches else None

    def all(self):
        return self._matches()


def _make_user(
    user_id: int = 1,
    notifications_enabled: bool = True,
    unsubscribe_token: str | None = None,
) -> models.User:
    user = models.User(
        id=user_id,
        email=f"user{user_id}@example.com",
        notifications_enabled=notifications_enabled,
        unsubscribe_token=unsubscribe_token or str(uuid.uuid4()),
        # Granular per-category preferences default on (server_default="true"),
        # but column defaults aren't applied to un-persisted instances, so set
        # them explicitly here.
        notify_product_updates=True,
        notify_audit_alerts=True,
        notify_billing=True,
    )
    return user


# ── Template rendering tests ────────────────────────────────────


class TestTemplateDesign:
    """Verify all templates render and reflect the white/clean redesign."""

    def test_all_templates_render_without_error(self):
        """Smoke test: every registered template renders."""
        context = {
            "email": "test@example.com",
            "user_name": "Test User",
            "target_url": "https://example.com",
            "project_name": "Test Project",
            "report_url": "https://example.com/report/1",
            "dashboard_url": "https://example.com/dashboard",
            "manage_billing_url": "https://example.com/billing",
            "billing_url": "https://example.com/billing",
            "verification_url": "https://example.com/verify?token=abc",
            "reset_url": "https://example.com/reset?token=xyz",
            "model_names_csv": "Gemini 2.5 Flash",
            "message": "Alert message",
            "geo_score": 85,
            "seo_score": 78,
            "aeo_score": 91,
            "plan_name": "plan_specialist",
            "previous_plan": "plan_standard",
            "amount_due": "4900",
            "currency": "usd",
            "credit_balance": 2,
            "metric_name": "geo_score",
            "condition": "below_threshold",
            "threshold": 80,
            "error_message": "Timeout",
            "job_id": "job-123",
            "report_name": "Monthly Report",
            "workspace_name": "Acme Corp",
            "consumed_credits": 90,
            "monthly_limit_credits": 100,
            "percent_consumed": 90.0,
            "settings_url": "https://example.com/settings",
            "invitation_url": "https://example.com/invite",
            "portal_url": "https://example.com/portal",
            "agency_name": "Test Agency",
            "project_names": ["Project A"],
            "report_month_label": "March 2026",
            "current_scores": {"seo": 80, "geo": 75, "aeo": 85, "audit_count": 12},
            "delta": {"seo": "+5", "geo": "+3", "aeo": "+8"},
            "highlights": ["Improved meta descriptions"],
            "remaining_issues": ["Missing schema markup"],
            "competitor_count": 3,
            "current_rank": {"geo": 1, "seo": 2, "aeo": 1},
            "updated_at": "2026-03-01",
            "unsubscribe_token": "test-token-1234",
        }

        for key in email_templates.TEMPLATE_DEFINITIONS:
            rendered = email_templates.render_template(key, context)
            assert rendered.html, f"Template {key} returned empty HTML"
            assert rendered.subject, f"Template {key} returned empty subject"

    def test_base_uses_white_background(self):
        """New base_email.html must use a light #F6F7F9 outer and #FFFFFF card."""
        rendered = email_templates.render_template(
            "auth.welcome",
            {"email": "test@example.com", "unsubscribe_token": "tok"},
        )
        assert "#F6F7F9" in rendered.html or "#f6f7f9" in rendered.html.lower()
        assert "#FFFFFF" in rendered.html or "#ffffff" in rendered.html.lower()
        # Old dark theme colour should be gone
        assert "#050b14" not in rendered.html

    def test_logo_present(self):
        """The Qiko Signal logo image must be in the rendered output."""
        rendered = email_templates.render_template(
            "auth.welcome",
            {"email": "test@example.com", "unsubscribe_token": "tok"},
        )
        assert "Qiko Signal" in rendered.html
        # Rebrand moved the inline SVG wordmark to a hosted PNG logo asset.
        assert "qiko-logo.png" in rendered.html

    def test_footer_has_gdpr_disclaimer_for_lifecycle_email(self):
        rendered = email_templates.render_template(
            "auth.welcome",
            {
                "email": "test@example.com",
                "unsubscribe_token": "tok-abc",
                "is_transactional": False,
            },
        )
        assert "unsubscribe" in rendered.html.lower()
        assert "tok-abc" in rendered.html


class TestTransactionalFlag:
    """Verification and password_reset must hide GDPR unsubscribe link."""

    def test_verification_is_transactional(self):
        rendered = email_templates.render_template(
            "auth.verification",
            {"email": "v@example.com", "verification_url": "https://example.com/verify"},
        )
        # The template sets is_transactional = true, so unsubscribe text is hidden
        assert "unsubscribe" not in rendered.html.lower() or "is_transactional" in rendered.html

    def test_password_reset_is_transactional(self):
        rendered = email_templates.render_template(
            "auth.password_reset",
            {"email": "r@example.com", "reset_url": "https://example.com/reset"},
        )
        assert "unsubscribe" not in rendered.html.lower() or "is_transactional" in rendered.html


class TestUnsubscribeUrlInjection:
    """render_template must build unsubscribe_url from unsubscribe_token."""

    def test_unsubscribe_url_injected_when_token_present(self):
        rendered = email_templates.render_template(
            "invoice.paid",
            {
                "email": "u@example.com",
                "amount_due": 1000,
                "currency": "usd",
                "unsubscribe_token": "my-token-123",
            },
        )
        assert "/api/v1/auth/unsubscribe?token=my-token-123" in rendered.html

    def test_no_unsubscribe_url_when_no_token(self):
        rendered = email_templates.render_template(
            "invoice.paid",
            {"email": "u@example.com", "amount_due": 1000, "currency": "usd"},
        )
        # Without token, there should be no token= in the url
        assert "token=" not in rendered.html


# ── Notification gate tests ──────────────────────────────────────


class TestNotificationGate:
    """queue_template_email must respect notifications_enabled."""

    def test_lifecycle_email_blocked_when_opted_out(self, monkeypatch):
        user = _make_user(user_id=5, notifications_enabled=False)
        session = FakeSession()
        session._users = {5: user}
        monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
        # Same reason as the sibling test below, plus one this assertion is
        # uniquely sensitive to: EmailService.__init__ -> resolve_db_setting ->
        # ConfigurationService.get_payload has a 15-second process-wide cache,
        # and on a miss it loads the payload through *this* FakeSession and
        # creates the OperationalSetting row it finds missing. That write lands
        # in session.added, so "nothing was queued" became "one unrelated row
        # was added" purely as a function of how much wall-clock time the tests
        # before this one took. Stubbing the resolver removes the dependency on
        # the clock instead of leaving an assertion that passes by luck.
        monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *_a, **_kw: None)
        svc = email_service.EmailService(session)

        result = svc.queue_template_email(
            to_email=user.email,
            template_key="audit.completed",
            context={
                "target_url": "https://example.com",
                "geo_score": 80,
                "seo_score": 70,
                "aeo_score": 90,
            },
            user_id=5,
        )
        assert result is None
        assert session.added == []

    def test_transactional_email_not_blocked_when_opted_out(self, monkeypatch):
        user = _make_user(user_id=6, notifications_enabled=False)
        session = FakeSession()
        session._users = {6: user}
        monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
        # EmailService.__init__ calls core.db_settings_resolver.resolve_db_setting
        # for a live DB override before falling back to `settings`. FakeSession
        # has no OperationalSetting rows, so that resolver falls through to
        # get_env_setting_value's own read of the raw env-derived settings
        # object, bypassing the settings monkeypatch above entirely. Force it
        # to report "no DB override" so the fallback to `settings.MAIL_ENABLED`
        # actually applies.
        monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *_a, **_kw: None)
        svc = email_service.EmailService(session)

        result = svc.queue_template_email(
            to_email=user.email,
            template_key="auth.verification",
            context={"verification_url": "https://example.com/verify?token=x"},
            user_id=6,
        )
        assert result is not None
        assert isinstance(result, models.EmailOutbox)

    def test_unsubscribe_token_injected_into_context(self, monkeypatch):
        token = "injected-token-abc"
        user = _make_user(user_id=7, notifications_enabled=True, unsubscribe_token=token)
        session = FakeSession()
        session._users = {7: user}
        monkeypatch.setattr(email_service.settings, "MAIL_ENABLED", True, raising=False)
        monkeypatch.setattr("core.db_settings_resolver.resolve_db_setting", lambda *_a, **_kw: None)
        svc = email_service.EmailService(session)

        entry = svc.queue_template_email(
            to_email=user.email,
            template_key="auth.welcome",
            context={"dashboard_url": "https://example.com/dashboard"},
            user_id=7,
        )
        assert entry is not None
        assert token in entry.html_body


# ── Unsubscribe endpoint tests ──────────────────────────────────


class TestUnsubscribeEndpoint:
    """Unit tests for the GET /auth/unsubscribe handler."""

    def test_valid_token_disables_notifications(self):
        from routers.auth import unsubscribe

        token = str(uuid.uuid4())
        user = _make_user(user_id=10, unsubscribe_token=token)
        user.notifications_enabled = True

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = user

        response = asyncio.run(unsubscribe(token=token, db=mock_db))
        assert user.notifications_enabled is False
        mock_db.commit.assert_called_once()
        assert response.status_code == 200
        assert b"Unsubscribed" in response.body

    def test_invalid_token_returns_404(self):
        from routers.auth import unsubscribe
        from fastapi import HTTPException

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(unsubscribe(token="bad-token", db=mock_db))
        assert exc_info.value.status_code == 404


# ── Competitive digest migration test ───────────────────────────


class TestCompetitiveDigestMigration:
    """competitive_digest.html must now use base_email.html."""

    def test_competitive_digest_renders_with_base(self):
        rendered = email_templates.render_template(
            "competitive.digest",
            {
                "email": "test@example.com",
                "project_name": "Acme",
                "workspace_name": "Agency Corp",
                "competitor_count": 5,
                "dashboard_url": "https://example.com/dashboard",
                "highlights": ["Improved citation score"],
                "current_rank": {"geo": 2, "seo": 1, "aeo": 3},
                "updated_at": "2026-03-01",
                "unsubscribe_token": "tok",
            },
        )
        # Should inherit from base now → has the light background
        assert "#F6F7F9" in rendered.html or "#f6f7f9" in rendered.html.lower()
        # Old standalone dark bg should be gone
        assert "#07111f" not in rendered.html
