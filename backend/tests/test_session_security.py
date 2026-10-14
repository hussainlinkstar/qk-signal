"""Tests for SEC-01: Session Middleware Secure Defaults & Cookie Hardening.

Covers:
- session_cookie_secure property (HTTPS enforcement)
- resolved_session_secret property (fallback chain & fail-fast)
- Production startup validation for weak/missing/colliding secrets
- Minimum session secret length enforcement in production
"""

import os
import pytest

os.environ.setdefault("SSM_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

from core.config import Settings


# ---------------------------------------------------------------------------
# Helpers – minimal valid production kwargs so unrelated validators pass
# ---------------------------------------------------------------------------
_STRONG_JWT = "jwt-key-that-is-long-enough-for-prod-12345678"
_STRONG_JWT_REFRESH = "jwt-refresh-key-that-is-long-enough-prod-12345678"
_STRONG_SESSION = "session-key-that-is-at-least-32-chars-long!!"
_STRONG_OAUTH = "oauth-enc-key-that-is-unique-and-long-1234567890"


def _prod_kwargs(**overrides):
    """Return a dict with the minimum valid production secrets, merged with overrides."""
    base = dict(
        ENVIRONMENT="production",
        JWT_SECRET_KEY=_STRONG_JWT,
        JWT_REFRESH_SECRET_KEY=_STRONG_JWT_REFRESH,
        SESSION_SECRET_KEY=_STRONG_SESSION,
        OAUTH_TOKEN_ENCRYPTION_KEY=_STRONG_OAUTH,
        ALLOW_LEGACY_PLAINTEXT_SECRETS=False,
        # SEC-04: production Redis must be authenticated (password in the URL)
        # and must not be the unauthenticated dev default.
        REDIS_URL="redis://:strong-redis-password@redis-prod.internal:6379",
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# session_cookie_secure property
# ---------------------------------------------------------------------------
class TestSessionCookieSecure:
    def test_false_in_development(self):
        s = Settings(ENVIRONMENT="development")
        assert s.session_cookie_secure is False

    def test_true_in_production(self):
        s = Settings(**_prod_kwargs())
        assert s.session_cookie_secure is True

    def test_true_in_staging(self):
        # Staging is a deployed environment: construction now requires the full
        # secret set, same as production.
        s = Settings(**_prod_kwargs(ENVIRONMENT="staging"))
        assert s.session_cookie_secure is True


# ---------------------------------------------------------------------------
# resolved_session_secret property
# ---------------------------------------------------------------------------
class TestResolvedSessionSecret:
    def test_dedicated_key_used_when_present(self):
        s = Settings(
            ENVIRONMENT="development", SESSION_SECRET_KEY="my-dedicated-secret-key-abcdef1234"
        )
        assert s.resolved_session_secret == "my-dedicated-secret-key-abcdef1234"

    def test_dev_falls_back_to_jwt_secret(self):
        s = Settings(
            ENVIRONMENT="development", SESSION_SECRET_KEY="", JWT_SECRET_KEY="jwt-fallback-key"
        )
        assert s.resolved_session_secret == "jwt-fallback-key"

    def test_dev_falls_back_to_literal_when_no_jwt(self):
        s = Settings(ENVIRONMENT="development", SESSION_SECRET_KEY="", JWT_SECRET_KEY="")
        assert s.resolved_session_secret == "dev_session_fallback"

    def test_dev_rejects_unsafe_session_key_falls_back(self):
        s = Settings(
            ENVIRONMENT="development", SESSION_SECRET_KEY="changeme", JWT_SECRET_KEY="jwt-key"
        )
        assert s.resolved_session_secret == "jwt-key"

    def test_production_uses_dedicated_key(self):
        s = Settings(**_prod_kwargs())
        assert s.resolved_session_secret == _STRONG_SESSION

    def test_non_dev_raises_without_session_key(self):
        """resolved_session_secret must raise outside development if the key is missing."""
        # Construction now enforces the secret set on deployed environments,
        # so build a valid one and then force the field empty via the same
        # object.__setattr__ mechanism the model's own validators use. The
        # property-level guard is a separate behaviour and stays covered.
        s = Settings(**_prod_kwargs(ENVIRONMENT="staging"))
        object.__setattr__(s, "SESSION_SECRET_KEY", "")
        with pytest.raises(ValueError, match="SESSION_SECRET_KEY is required"):
            _ = s.resolved_session_secret

    def test_non_dev_raises_on_unsafe_session_key(self):
        s = Settings(**_prod_kwargs(ENVIRONMENT="staging"))
        object.__setattr__(s, "SESSION_SECRET_KEY", "dev_session_fallback")
        with pytest.raises(ValueError, match="SESSION_SECRET_KEY is required"):
            _ = s.resolved_session_secret


# ---------------------------------------------------------------------------
# Deployed-environment startup validation (_validate_deployed_secrets)
# ---------------------------------------------------------------------------
class TestProductionStartupValidation:
    def test_valid_production_config_passes(self):
        s = Settings(**_prod_kwargs())
        assert s.is_production

    def test_fails_on_empty_session_secret(self):
        with pytest.raises(Exception, match="SESSION_SECRET_KEY"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY=""))

    def test_fails_on_unsafe_fallback_value(self):
        with pytest.raises(Exception, match="SESSION_SECRET_KEY"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY="session_secret_fallback"))

    def test_fails_on_dev_session_fallback_literal(self):
        with pytest.raises(Exception, match="SESSION_SECRET_KEY"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY="dev_session_fallback"))

    def test_fails_on_changeme(self):
        with pytest.raises(Exception, match="SESSION_SECRET_KEY"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY="changeme"))

    def test_fails_on_short_session_secret(self):
        with pytest.raises(Exception, match="must be >= 32 chars"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY="short-key"))

    def test_fails_when_session_equals_jwt(self):
        shared = _STRONG_JWT
        with pytest.raises(Exception, match="must differ from JWT_SECRET_KEY"):
            Settings(**_prod_kwargs(SESSION_SECRET_KEY=shared, JWT_SECRET_KEY=shared))

    def test_fails_when_oauth_key_collides_with_session(self):
        with pytest.raises(Exception, match="OAUTH_TOKEN_ENCRYPTION_KEY"):
            Settings(**_prod_kwargs(OAUTH_TOKEN_ENCRYPTION_KEY=_STRONG_SESSION))

    def test_fails_when_legacy_plaintext_secrets_allowed(self):
        with pytest.raises(Exception, match="ALLOW_LEGACY_PLAINTEXT_SECRETS"):
            Settings(**_prod_kwargs(ALLOW_LEGACY_PLAINTEXT_SECRETS=True))

    def test_development_allows_weak_secrets(self):
        """Development must not block startup on weak secrets.

        This is what keeps local development and the whole test suite working;
        it is the regression most likely to bite.
        """
        s = Settings(ENVIRONMENT="development", SESSION_SECRET_KEY="", JWT_SECRET_KEY="dev-secret")
        assert s.ENVIRONMENT == "development"

    def test_preprod_rejects_dev_secret_jwt(self):
        with pytest.raises(Exception, match="JWT_SECRET_KEY"):
            Settings(**_prod_kwargs(ENVIRONMENT="preprod", JWT_SECRET_KEY="dev-secret"))

    def test_preprod_rejects_empty_jwt(self):
        with pytest.raises(Exception, match="JWT_SECRET_KEY"):
            Settings(**_prod_kwargs(ENVIRONMENT="preprod", JWT_SECRET_KEY=""))

    def test_staging_with_valid_secrets_constructs(self):
        # Proves the change did not simply break every non-production
        # environment.
        s = Settings(**_prod_kwargs(ENVIRONMENT="staging"))
        assert s.ENVIRONMENT == "staging"

    def test_misspelled_environment_enforces_secrets(self):
        # The fail-safe default being asserted on purpose: a typo must not
        # disable the gate.
        with pytest.raises(Exception, match="JWT_SECRET_KEY"):
            Settings(**_prod_kwargs(ENVIRONMENT="prodution", JWT_SECRET_KEY="dev-secret"))

    def test_preprod_rejects_legacy_plaintext_secrets(self):
        # The other validator clauses now apply to preprod too, not just JWT.
        with pytest.raises(Exception, match="ALLOW_LEGACY_PLAINTEXT_SECRETS"):
            Settings(**_prod_kwargs(ENVIRONMENT="preprod", ALLOW_LEGACY_PLAINTEXT_SECRETS=True))
