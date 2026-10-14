import os

os.environ.setdefault("SSM_ENABLED", "false")
os.environ.setdefault("ENVIRONMENT", "development")

from core.config import (
    Settings,
    effective_gemini_api_key_from_env,
    resolve_effective_gemini_api_key,
    settings as runtime_settings,
)


def test_cors_origins_accepts_csv():
    settings = Settings(CORS_ORIGINS="https://app.example.com, https://www.example.com/")
    assert settings.cors_origins == ["https://app.example.com", "https://www.example.com"]


def test_cors_origins_accepts_json_list():
    settings = Settings(CORS_ORIGINS='["https://app.example.com","https://www.example.com/"]')
    assert settings.cors_origins == ["https://app.example.com", "https://www.example.com"]


def test_allowed_hosts_accepts_csv():
    settings = Settings(ALLOWED_HOSTS="app.example.com,api.example.com")
    assert settings.allowed_hosts == ["app.example.com", "api.example.com"]


def test_environment_normalizes_prod_aliases():
    # Constructing a production Settings now enforces secure-secret validation
    # (SEC-04), so supply the minimum valid production secrets/Redis URL to
    # isolate the assertion to environment-alias normalization.
    settings = Settings(
        ENVIRONMENT="prod",
        JWT_SECRET_KEY="jwt-key-that-is-long-enough-for-prod-12345678",
        JWT_REFRESH_SECRET_KEY="jwt-refresh-key-that-is-long-enough-prod-12345678",
        SESSION_SECRET_KEY="session-key-that-is-at-least-32-chars-long!!",
        OAUTH_TOKEN_ENCRYPTION_KEY="oauth-enc-key-that-is-unique-and-long-1234567890",
        REDIS_URL="redis://:strongpassword@redis-prod:6379",
    )
    assert settings.ENVIRONMENT == "production"
    assert settings.APP_ENV == "production"


def test_environment_accepts_legacy_app_env_alias():
    settings = Settings(APP_ENV="local")
    assert settings.ENVIRONMENT == "development"
    assert settings.APP_ENV == "development"


def test_effective_gemini_api_key_prefers_gemini_env():
    settings = Settings(GEMINI_API_KEY="gemini-key", GOOGLE_API_KEY="legacy-google-key")
    assert settings.effective_gemini_api_key == "gemini-key"


def test_effective_gemini_api_key_falls_back_to_google_alias():
    settings = Settings(GEMINI_API_KEY=None, GOOGLE_API_KEY="legacy-google-key")
    assert settings.effective_gemini_api_key == "legacy-google-key"


def test_resolve_effective_gemini_api_key_strips_and_prioritizes_gemini():
    assert resolve_effective_gemini_api_key("  gemini-key  ", "legacy-google-key") == "gemini-key"


def test_effective_gemini_api_key_from_env_accepts_legacy_alias(monkeypatch):
    # effective_gemini_api_key_from_env() now resolves against the runtime
    # `settings` singleton (RuntimeBackedSettings) rather than reading os.environ
    # directly, so override the singleton to exercise the legacy GOOGLE_API_KEY
    # alias fallback.
    monkeypatch.setattr(runtime_settings, "GEMINI_API_KEY", None)
    monkeypatch.setattr(runtime_settings, "GOOGLE_API_KEY", "legacy-google-key")
    assert effective_gemini_api_key_from_env() == "legacy-google-key"


def test_email_settings_accept_legacy_mail_aliases(monkeypatch):
    # The canonical SMTP env vars are present in the runtime container and would
    # otherwise win over the init kwargs via AliasChoices; clear them so the
    # legacy MAIL_* aliases are actually exercised.
    for canonical in (
        "EMAIL_FROM_ADDRESS",
        "EMAIL_FROM_NAME",
        "SMTP_HOST",
        "SMTP_PORT",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(canonical, raising=False)

    settings = Settings(
        MAIL_FROM="legacy-from@example.com",
        MAIL_FROM_NAME="Legacy Sender",
        MAIL_SERVER="smtp.legacy.test",
        MAIL_PORT="2525",
        MAIL_USERNAME="legacy-user",
        MAIL_PASSWORD="legacy-pass",
    )

    assert settings.EMAIL_FROM_ADDRESS == "legacy-from@example.com"
    assert settings.EMAIL_FROM_NAME == "Legacy Sender"
    assert settings.SMTP_HOST == "smtp.legacy.test"
    assert settings.SMTP_PORT == 2525
    assert settings.SMTP_USERNAME == "legacy-user"
    assert settings.SMTP_PASSWORD == "legacy-pass"
