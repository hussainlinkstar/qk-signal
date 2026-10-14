"""Tests for SEC-11 (CSP report endpoint) and SEC-12 (expanded security checks).

Covers:
- CSP Level 2 and Reporting API v1 report ingestion
- Graceful degradation on invalid JSON
- Admin-only access for CSP report summary
- Session secret strength checks
- Redis auth & TLS posture checks
- Credential boundary check
- SSRF protection check
- Security headers middleware check
"""

import os

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("SSM_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

import models
from auth.security import get_current_admin_user
from core.config import settings
import system_checks
from system_checks import router as system_router
from admin import _build_security_checks


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_test_app() -> FastAPI:
    """Create a minimal FastAPI app with just the system_checks router."""
    test_app = FastAPI()
    test_app.include_router(system_router, prefix="/api/v1")
    return test_app


def _admin_user() -> models.User:
    return models.User(
        email="admin-csp@example.com",
        hashed_password="x",
        role="admin",
        credits=5,
        notifications_enabled=True,
    )


def _find_check(checks: list[dict], key: str) -> dict:
    """Return the first check dict whose ``key`` matches *key*."""
    for check in checks:
        if check.get("key") == key:
            return check
    raise AssertionError(f"No security check with key={key!r}")


# ---------------------------------------------------------------------------
# CSP Report Endpoint Tests (SEC-11)
# ---------------------------------------------------------------------------


class TestCspReportEndpoint:
    """POST /api/v1/csp-report ingestion tests."""

    def setup_method(self):
        # Reset CSP report state before each test so tests are independent
        system_checks._CSP_REPORT_BUFFER.clear()
        system_checks._csp_violation_count = 0

    def test_csp_report_accepts_level2_format(self):
        """CSP Level 2 format with ``csp-report`` wrapper returns 204."""
        app = _build_test_app()
        client = TestClient(app)
        response = client.post(
            "/api/v1/csp-report",
            json={
                "csp-report": {
                    "blocked-uri": "https://evil.example.com/tracker.js",
                    "violated-directive": "script-src 'self'",
                    "document-uri": "https://app.example.com/dashboard",
                    "source-file": "https://app.example.com/main.js",
                }
            },
        )
        assert response.status_code == 204

    def test_csp_report_accepts_reporting_api_format(self):
        """Reporting API v1 array format returns 204."""
        app = _build_test_app()
        client = TestClient(app)
        response = client.post(
            "/api/v1/csp-report",
            json=[
                {
                    "type": "csp-violation",
                    "body": {
                        "blockedURL": "https://cdn.ads.example/pixel.gif",
                        "effectiveDirective": "img-src",
                        "documentURL": "https://app.example.com/page",
                        "sourceFile": "https://app.example.com/bundle.js",
                    },
                }
            ],
        )
        assert response.status_code == 204

    def test_csp_report_returns_204_on_invalid_json(self):
        """Invalid JSON body still returns 204 (graceful degradation)."""
        app = _build_test_app()
        client = TestClient(app)
        response = client.post(
            "/api/v1/csp-report",
            content=b"this is not valid json {{{",
            headers={"Content-Type": "application/csp-report"},
        )
        assert response.status_code == 204

    def test_csp_report_summary_requires_admin(self):
        """GET /csp-report/summary without auth returns 401 or 403."""
        app = _build_test_app()
        app.dependency_overrides.clear()
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/csp-report/summary")
        assert response.status_code in (401, 403)

    def test_csp_report_summary_returns_data(self):
        """Admin can retrieve CSP violation summary after ingesting a report."""
        app = _build_test_app()
        client = TestClient(app)

        # Ingest a report first
        client.post(
            "/api/v1/csp-report",
            json={
                "csp-report": {
                    "blocked-uri": "https://evil.example.com/script.js",
                    "violated-directive": "script-src 'self'",
                    "document-uri": "https://app.example.com/",
                }
            },
        )

        # Override admin auth
        def override_get_current_admin_user():
            return _admin_user()

        app.dependency_overrides[get_current_admin_user] = override_get_current_admin_user

        try:
            response = client.get("/api/v1/csp-report/summary")
            assert response.status_code == 200
            payload = response.json()
            assert payload["total_violations"] >= 1
            assert isinstance(payload["recent_reports"], list)
            assert len(payload["recent_reports"]) >= 1
        finally:
            app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Security Checks Tests (SEC-12) — _build_security_checks()
# ---------------------------------------------------------------------------


class TestSecurityChecksSessionSecret:
    """SEC-01: Session secret strength in _build_security_checks()."""

    def test_security_checks_session_secret_fail(self, monkeypatch):
        """Empty SESSION_SECRET_KEY → status='fail'."""
        monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "")
        monkeypatch.setattr(settings, "JWT_SECRET_KEY", "some-jwt-key")
        checks = _build_security_checks()
        entry = _find_check(checks, "session_secret")
        assert entry["status"] == "fail"

    def test_security_checks_session_secret_too_short(self, monkeypatch):
        """SESSION_SECRET_KEY shorter than 32 chars → status='warn'."""
        monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "short")
        monkeypatch.setattr(settings, "JWT_SECRET_KEY", "some-jwt-key")
        checks = _build_security_checks()
        entry = _find_check(checks, "session_secret")
        assert entry["status"] == "warn"

    def test_security_checks_session_secret_matches_jwt(self, monkeypatch):
        """SESSION_SECRET_KEY == JWT_SECRET_KEY → status='warn'."""
        shared = "a" * 64
        monkeypatch.setattr(settings, "SESSION_SECRET_KEY", shared)
        monkeypatch.setattr(settings, "JWT_SECRET_KEY", shared)
        checks = _build_security_checks()
        entry = _find_check(checks, "session_secret")
        assert entry["status"] == "warn"

    def test_security_checks_session_secret_pass(self, monkeypatch):
        """Proper 64-char secret distinct from JWT → status='pass'."""
        monkeypatch.setattr(settings, "SESSION_SECRET_KEY", "s" * 64)
        monkeypatch.setattr(settings, "JWT_SECRET_KEY", "j" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "session_secret")
        assert entry["status"] == "pass"


class TestSecurityChecksRedis:
    """SEC-04: Redis auth & TLS checks in _build_security_checks()."""

    def test_security_checks_redis_auth_warn_when_no_password(self, monkeypatch):
        """REDIS_URL without password → redis_auth status='warn'."""
        monkeypatch.setenv("REDIS_URL", "redis://redis:6379")
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "redis_auth")
        assert entry["status"] == "warn"

    def test_security_checks_redis_auth_pass_with_password(self, monkeypatch):
        """REDIS_URL with password → redis_auth status='pass'."""
        monkeypatch.setenv("REDIS_URL", "redis://:secret@redis:6379")
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "redis_auth")
        assert entry["status"] == "pass"

    def test_security_checks_redis_tls_warn(self, monkeypatch):
        """redis:// scheme (no TLS) → redis_tls status='warn'."""
        monkeypatch.setenv("REDIS_URL", "redis://:secret@redis:6379")
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "redis_tls")
        assert entry["status"] == "warn"

    def test_security_checks_redis_tls_pass(self, monkeypatch):
        """rediss:// scheme (TLS) → redis_tls status='pass'."""
        monkeypatch.setenv("REDIS_URL", "rediss://:secret@redis:6380")
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "redis_tls")
        assert entry["status"] == "pass"


class TestSecurityChecksModuleImports:
    """SEC-09 & SEC-02: Module availability checks in _build_security_checks()."""

    def test_security_checks_ssrf_protection(self, monkeypatch):
        """ssrf_protection check is present with expected status.

        When ``services.url_validation`` is importable the status is ``pass``;
        otherwise ``fail``.  We assert the check key exists and the status
        matches the module's availability in the current environment.
        """
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "ssrf_protection")
        # Determine expected status based on actual module availability
        try:
            from services.url_validation import safe_async_fetch  # noqa: F401

            expected = "pass"
        except ImportError:
            expected = "fail"
        assert entry["status"] == expected

    def test_security_checks_security_headers_middleware(self, monkeypatch):
        """SecurityHeadersMiddleware is importable → security_headers_middleware status='pass'."""
        monkeypatch.setenv("JWT_SECRET_KEY", "j" * 64)
        monkeypatch.setenv("SESSION_SECRET_KEY", "s" * 64)
        checks = _build_security_checks()
        entry = _find_check(checks, "security_headers_middleware")
        assert entry["status"] == "pass"
