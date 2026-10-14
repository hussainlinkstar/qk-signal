from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

import models
from database import SessionLocal

logger = logging.getLogger(__name__)

SECTION_AI_PROVIDER_KEYS = "ai_provider_keys"
SECTION_SEARCH_CONFIG = "search_config"
SECTION_EMAIL_CONFIG = "email_config"
SECTION_OAUTH_CONFIG = "oauth_config"
SECTION_CLOUDFLARE_CONFIG = "cloudflare_config"
SECTION_SUPPORT_INFO = "support_info"
SECTION_RUNTIME_CONFIG = "runtime_config"


@dataclass(frozen=True)
class ConfigDefinition:
    section: str
    field: str
    runtime_meta: dict[str, Any] | None = None


def _runtime_meta(**kwargs: Any) -> dict[str, Any]:
    return dict(kwargs)


CONFIG_DEFINITIONS: dict[str, ConfigDefinition] = {
    # AI provider keys
    "GEMINI_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "gemini_api_key"),
    "GOOGLE_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "google_api_key"),
    "ANTHROPIC_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "anthropic_api_key"),
    "FIRECRAWL_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "firecrawl_api_key"),
    "PAGESPEED_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "pagespeed_api_key"),
    "SEARCH_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "search_api_key"),
    "SERPAPI_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "serpapi_api_key"),
    "GOOGLE_PLACES_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "google_places_api_key"),
    "GOOGLE_MAPS_API_KEY": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "google_maps_api_key"),
    "DATAFORSEO_LOGIN": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "dataforseo_login"),
    "DATAFORSEO_PASSWORD": ConfigDefinition(SECTION_AI_PROVIDER_KEYS, "dataforseo_password"),
    # Search config
    "SERPAPI_ENGINE": ConfigDefinition(
        SECTION_SEARCH_CONFIG,
        "serpapi_engine",
        runtime_meta=_runtime_meta(
            type="str",
            options=["google", "bing", "duckduckgo"],
            category="Search Config",
            description="SerpAPI search engine",
        ),
    ),
    "GOOGLE_PLACES_API_MODE": ConfigDefinition(
        SECTION_SEARCH_CONFIG,
        "google_places_api_mode",
        runtime_meta=_runtime_meta(
            type="str",
            options=["new", "legacy"],
            category="Search Config",
            description="Google Places API mode",
        ),
    ),
    "GOOGLE_PLACES_FALLBACK_TO_LEGACY": ConfigDefinition(
        SECTION_SEARCH_CONFIG,
        "google_places_fallback_to_legacy",
        runtime_meta=_runtime_meta(
            type="bool",
            category="Search Config",
            description="Allow Google Places legacy fallback when the new API fails",
        ),
    ),
    # Email config
    "MAIL_ENABLED": ConfigDefinition(SECTION_EMAIL_CONFIG, "enabled"),
    "EMAIL_PROVIDER": ConfigDefinition(SECTION_EMAIL_CONFIG, "provider"),
    "EMAIL_FROM_ADDRESS": ConfigDefinition(SECTION_EMAIL_CONFIG, "from_address"),
    "EMAIL_FROM_NAME": ConfigDefinition(SECTION_EMAIL_CONFIG, "from_name"),
    "SMTP_HOST": ConfigDefinition(SECTION_EMAIL_CONFIG, "smtp_host"),
    "SMTP_PORT": ConfigDefinition(SECTION_EMAIL_CONFIG, "smtp_port"),
    "SMTP_USERNAME": ConfigDefinition(SECTION_EMAIL_CONFIG, "smtp_username"),
    "SMTP_PASSWORD": ConfigDefinition(SECTION_EMAIL_CONFIG, "smtp_password"),
    "EMAIL_OUTBOX_MAX_ATTEMPTS": ConfigDefinition(
        SECTION_EMAIL_CONFIG,
        "outbox_max_attempts",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=20,
            category="Workers",
            description="Max email delivery attempts",
        ),
    ),
    "EMAIL_OUTBOX_BATCH_SIZE": ConfigDefinition(
        SECTION_EMAIL_CONFIG,
        "outbox_batch_size",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=200,
            category="Workers",
            description="Emails processed per outbox worker batch",
        ),
    ),
    # OAuth config
    "GOOGLE_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "google_client_id"),
    "GOOGLE_CLIENT_SECRET": ConfigDefinition(SECTION_OAUTH_CONFIG, "google_client_secret"),
    "GITHUB_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "github_client_id"),
    "GITHUB_CLIENT_SECRET": ConfigDefinition(SECTION_OAUTH_CONFIG, "github_client_secret"),
    "LINKEDIN_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "linkedin_client_id"),
    "LINKEDIN_CLIENT_SECRET": ConfigDefinition(SECTION_OAUTH_CONFIG, "linkedin_client_secret"),
    "JIRA_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "jira_client_id"),
    "JIRA_CLIENT_SECRET": ConfigDefinition(SECTION_OAUTH_CONFIG, "jira_client_secret"),
    "BING_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "bing_client_id"),
    "BING_CLIENT_SECRET": ConfigDefinition(SECTION_OAUTH_CONFIG, "bing_client_secret"),
    "MICROSOFT_SSO_CLIENT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "microsoft_sso_client_id"),
    "MICROSOFT_SSO_CLIENT_SECRET": ConfigDefinition(
        SECTION_OAUTH_CONFIG, "microsoft_sso_client_secret"
    ),
    "MICROSOFT_SSO_TENANT_ID": ConfigDefinition(SECTION_OAUTH_CONFIG, "microsoft_sso_tenant_id"),
    # Cloudflare
    "CLOUDFLARE_API_TOKEN": ConfigDefinition(SECTION_CLOUDFLARE_CONFIG, "api_token"),
    "CLOUDFLARE_ZONE_ID": ConfigDefinition(SECTION_CLOUDFLARE_CONFIG, "zone_id"),
    "CLOUDFLARE_CUSTOM_ORIGIN_SERVER": ConfigDefinition(
        SECTION_CLOUDFLARE_CONFIG,
        "custom_origin_server",
    ),
    "CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY": ConfigDefinition(
        SECTION_CLOUDFLARE_CONFIG,
        "auto_activate_on_verify",
    ),
    # Support
    "SUPPORT_EMAIL": ConfigDefinition(SECTION_SUPPORT_INFO, "support_email"),
    "BILLING_EMAIL": ConfigDefinition(SECTION_SUPPORT_INFO, "billing_email"),
    "PRIVACY_EMAIL": ConfigDefinition(SECTION_SUPPORT_INFO, "privacy_email"),
    "CONTACT_INBOX_ADDRESS": ConfigDefinition(SECTION_SUPPORT_INFO, "contact_inbox_address"),
    "CONTACT_TICKET_PREFIX": ConfigDefinition(SECTION_SUPPORT_INFO, "contact_ticket_prefix"),
    # Runtime config
    "LOGIN_RATE_LIMIT": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "LOGIN_RATE_LIMIT",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=100,
            category="Rate Limiting",
            description="Max failed logins per IP+account before lockout",
        ),
    ),
    "LOGIN_RATE_WINDOW": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "LOGIN_RATE_WINDOW",
        runtime_meta=_runtime_meta(
            type="int",
            min=60,
            max=3600,
            category="Rate Limiting",
            description="Per-account login failure window in seconds",
        ),
    ),
    "LOGIN_IP_RATE_LIMIT": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "LOGIN_IP_RATE_LIMIT",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=1000,
            category="Rate Limiting",
            description="Max failed logins per IP across all accounts",
        ),
    ),
    "LOGIN_IP_RATE_WINDOW": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "LOGIN_IP_RATE_WINDOW",
        runtime_meta=_runtime_meta(
            type="int",
            min=60,
            max=3600,
            category="Rate Limiting",
            description="Per-IP login failure window in seconds",
        ),
    ),
    "DEFAULT_RATE_LIMIT": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEFAULT_RATE_LIMIT",
        runtime_meta=_runtime_meta(
            type="int",
            min=10,
            max=10000,
            category="Rate Limiting",
            description="Default API rate limit per window",
        ),
    ),
    "DEFAULT_RATE_WINDOW": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEFAULT_RATE_WINDOW",
        runtime_meta=_runtime_meta(
            type="int",
            min=10,
            max=3600,
            category="Rate Limiting",
            description="Default rate limit window in seconds",
        ),
    ),
    "MAX_SESSIONS_PER_USER": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "MAX_SESSIONS_PER_USER",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=50,
            category="Rate Limiting",
            description="Maximum concurrent sessions per user",
        ),
    ),
    "GOOGLE_FAST_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GOOGLE_FAST_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "gemini-3.5-flash",
                "gemini-3.1-flash-lite",
                "gemini-2.5-flash",
                "gemini-2.5-pro",
            ],
            category="AI Models",
            description="Google fast-tier model",
        ),
    ),
    "GOOGLE_SMART_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GOOGLE_SMART_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "gemini-3.1-pro-preview",
                "gemini-3.5-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            ],
            category="AI Models",
            description="Google smart-tier model",
        ),
    ),
    "GOOGLE_LITE_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GOOGLE_LITE_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "gemini-3.1-flash-lite",
                "gemini-3.5-flash",
                "gemini-2.5-flash-lite",
                "gemini-2.5-flash",
            ],
            category="AI Models",
            description="Google lite-tier model",
        ),
    ),
    "CMS_GEMINI_TEXT_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CMS_GEMINI_TEXT_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "gemini-3.1-pro-preview",
                "gemini-3.5-flash",
                "gemini-2.5-pro",
                "gemini-2.5-flash",
            ],
            category="AI Models",
            description="CMS text generation model",
        ),
    ),
    "CMS_GEMINI_IMAGE_TIER": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CMS_GEMINI_IMAGE_TIER",
        runtime_meta=_runtime_meta(
            type="str",
            options=["flash", "pro"],
            category="AI Models",
            description="CMS image generation tier",
        ),
    ),
    "SUPPORT_CHAT_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "SUPPORT_CHAT_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
            category="AI Models",
            description="Support chat model",
        ),
    ),
    "OPENAI_LITE_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "OPENAI_LITE_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["gpt-5.4-nano", "gpt-5.4-mini"],
            category="AI Models",
            description="OpenAI lite-tier model",
        ),
    ),
    "OPENAI_FAST_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "OPENAI_FAST_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["gpt-5.4-mini", "gpt-5.4-nano", "gpt-5.4"],
            category="AI Models",
            description="OpenAI fast-tier model",
        ),
    ),
    "OPENAI_SMART_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "OPENAI_SMART_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["gpt-5.4", "gpt-5.4-mini", "gpt-5.4-nano"],
            category="AI Models",
            description="OpenAI smart-tier model",
        ),
    ),
    "ANTHROPIC_LITE_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "ANTHROPIC_LITE_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["claude-haiku-4-5", "claude-sonnet-4-6"],
            category="AI Models",
            description="Anthropic lite-tier model",
        ),
    ),
    "ANTHROPIC_FAST_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "ANTHROPIC_FAST_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6"],
            category="AI Models",
            description="Anthropic fast-tier model",
        ),
    ),
    "ANTHROPIC_SMART_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "ANTHROPIC_SMART_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"],
            category="AI Models",
            description="Anthropic smart-tier model",
        ),
    ),
    # --- AWS Bedrock model routing (the engine's sole live LLM provider) ---
    # Reasoning/measurement/embeddings/support-chat/pre-scan/case-study all
    # resolve to these. Runtime-editable so models can be rotated without a
    # redeploy. The credential (AWS_BEARER_TOKEN_BEDROCK) is intentionally NOT
    # runtime-configurable here — it lives in env/SSM and is read by boto3.
    "BEDROCK_SMART_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "BEDROCK_SMART_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
                "eu.amazon.nova-pro-v1:0",
            ],
            category="AI Models",
            description="Bedrock smart-tier model (deep reasoning / synthesis)",
        ),
    ),
    "BEDROCK_FAST_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "BEDROCK_FAST_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "eu.amazon.nova-lite-v1:0",
                "eu.amazon.nova-pro-v1:0",
                "eu.amazon.nova-micro-v1:0",
            ],
            category="AI Models",
            description="Bedrock fast-tier model (debate / standard reasoning)",
        ),
    ),
    "BEDROCK_LITE_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "BEDROCK_LITE_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "eu.amazon.nova-micro-v1:0",
                "eu.amazon.nova-lite-v1:0",
            ],
            category="AI Models",
            description="Bedrock lite-tier model (pre-scan / classification)",
        ),
    ),
    "BEDROCK_EMBEDDING_MODEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "BEDROCK_EMBEDDING_MODEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=[
                "eu.cohere.embed-v4:0",
                "eu.amazon.titan-embed-text-v2:0",
            ],
            category="AI Models",
            description="Bedrock embedding model",
        ),
    ),
    "AUDIT_OUTPUT_LANGUAGE": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "AUDIT_OUTPUT_LANGUAGE",
        runtime_meta=_runtime_meta(
            type="str",
            category="General",
            description="Default language for audit report output",
        ),
    ),
    "AUDIT_JOB_MAX_ATTEMPTS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "AUDIT_JOB_MAX_ATTEMPTS",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=10,
            category="Workers",
            description="Max retry attempts for audit jobs",
        ),
    ),
    "AUDIT_JOB_TIMEOUT_SECONDS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "AUDIT_JOB_TIMEOUT_SECONDS",
        runtime_meta=_runtime_meta(
            type="int",
            min=60,
            max=3600,
            category="Workers",
            description="Timeout per audit job in seconds",
        ),
    ),
    "GUEST_AUDIT_LIMIT": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GUEST_AUDIT_LIMIT",
        runtime_meta=_runtime_meta(
            type="int",
            min=0,
            max=10,
            category="Workers",
            description="Max audits for guest users",
        ),
    ),
    "GUEST_AUDIT_WINDOW_SECONDS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GUEST_AUDIT_WINDOW_SECONDS",
        runtime_meta=_runtime_meta(
            type="int",
            min=3600,
            max=604800,
            category="Workers",
            description="Guest audit rate window in seconds",
        ),
    ),
    "ACCESS_TOKEN_EXPIRE_MINUTES": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "ACCESS_TOKEN_EXPIRE_MINUTES",
        runtime_meta=_runtime_meta(
            type="int",
            min=5,
            max=1440,
            category="Auth",
            description="JWT access token lifetime in minutes",
        ),
    ),
    "REFRESH_TOKEN_EXPIRE_DAYS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "REFRESH_TOKEN_EXPIRE_DAYS",
        runtime_meta=_runtime_meta(
            type="int",
            min=1,
            max=90,
            category="Auth",
            description="JWT refresh token lifetime in days",
        ),
    ),
    "EMAIL_VERIFICATION_REQUIRED": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "EMAIL_VERIFICATION_REQUIRED",
        runtime_meta=_runtime_meta(
            type="bool",
            category="Auth",
            description="Require email verification before account activation",
        ),
    ),
    "DEBATE_TOTAL_TIMEOUT_FAST_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_TOTAL_TIMEOUT_FAST_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=15,
            max=300,
            category="AI Debate",
            description="FAST debate total timeout in seconds",
        ),
    ),
    "DEBATE_STEP_TIMEOUT_FAST_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_STEP_TIMEOUT_FAST_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=5,
            max=120,
            category="AI Debate",
            description="FAST debate per-step timeout in seconds",
        ),
    ),
    "DEBATE_COST_CAP_FAST_USD": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_COST_CAP_FAST_USD",
        runtime_meta=_runtime_meta(
            type="str",
            category="AI Debate",
            description="FAST debate hard cost cap in EUR",
        ),
    ),
    "DEBATE_TOTAL_TIMEOUT_SMART_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_TOTAL_TIMEOUT_SMART_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=60,
            max=1800,
            category="AI Debate",
            description="SMART debate total timeout in seconds",
        ),
    ),
    "DEBATE_STEP_TIMEOUT_SMART_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_STEP_TIMEOUT_SMART_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=15,
            max=300,
            category="AI Debate",
            description="SMART debate per-step timeout in seconds",
        ),
    ),
    "DEBATE_COST_CAP_SMART_USD": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_COST_CAP_SMART_USD",
        runtime_meta=_runtime_meta(
            type="str",
            category="AI Debate",
            description="SMART debate hard cost cap in EUR",
        ),
    ),
    "DEBATE_TOTAL_TIMEOUT_DEEP_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_TOTAL_TIMEOUT_DEEP_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=120,
            max=3600,
            category="AI Debate",
            description="DEEP_JUDGMENT debate total timeout in seconds",
        ),
    ),
    "DEBATE_STEP_TIMEOUT_DEEP_S": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_STEP_TIMEOUT_DEEP_S",
        runtime_meta=_runtime_meta(
            type="int",
            min=30,
            max=600,
            category="AI Debate",
            description="DEEP_JUDGMENT debate per-step timeout in seconds",
        ),
    ),
    "DEBATE_COST_CAP_DEEP_USD": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_COST_CAP_DEEP_USD",
        runtime_meta=_runtime_meta(
            type="str",
            category="AI Debate",
            description="DEEP_JUDGMENT debate hard cost cap in EUR",
        ),
    ),
    "DEBATE_CLAIM_LEDGER_MAX_ITEMS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "DEBATE_CLAIM_LEDGER_MAX_ITEMS",
        runtime_meta=_runtime_meta(
            type="int",
            min=3,
            max=30,
            category="Claim Ledger",
            description="Maximum claims per transfer packet",
        ),
    ),
    "CLAIM_LEDGER_PRIORITY_RECOMMENDATION": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CLAIM_LEDGER_PRIORITY_RECOMMENDATION",
        runtime_meta=_runtime_meta(
            type="int",
            min=100,
            max=500,
            category="Claim Ledger",
            description="Base priority score for recommendations",
        ),
    ),
    "CLAIM_LEDGER_PRIORITY_FINDING": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CLAIM_LEDGER_PRIORITY_FINDING",
        runtime_meta=_runtime_meta(
            type="int",
            min=100,
            max=500,
            category="Claim Ledger",
            description="Base priority score for findings",
        ),
    ),
    "CLAIM_LEDGER_SEVERITY_CRITICAL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CLAIM_LEDGER_SEVERITY_CRITICAL",
        runtime_meta=_runtime_meta(
            type="str",
            category="Claim Ledger",
            description="Confidence score for critical-severity claims (0.0-1.0)",
        ),
    ),
    "LOG_LEVEL": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "LOG_LEVEL",
        runtime_meta=_runtime_meta(
            type="str",
            options=["DEBUG", "INFO", "WARNING", "ERROR"],
            category="General",
            description="Application log level",
        ),
    ),
    "CORS_ORIGINS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "CORS_ORIGINS",
        runtime_meta=_runtime_meta(
            type="str",
            category="Infrastructure",
            description="Comma-separated allowed browser origins for CORS",
        ),
    ),
    "PUBLIC_SITE_ORIGINS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "PUBLIC_SITE_ORIGINS",
        runtime_meta=_runtime_meta(
            type="str",
            category="Infrastructure",
            description=(
                "Comma-separated marketing-site origins allowed to read the public "
                "plan catalog (no credentials, that endpoint only)"
            ),
        ),
    ),
    "ALLOWED_HOSTS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "ALLOWED_HOSTS",
        runtime_meta=_runtime_meta(
            type="str",
            category="Infrastructure",
            description="Comma-separated hostnames accepted by host validation",
        ),
    ),
    "S3_BUCKET_NAME": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "S3_BUCKET_NAME",
        runtime_meta=_runtime_meta(
            type="str",
            category="Storage",
            description="Object storage (S3) bucket for report and logo assets",
        ),
    ),
    "STORAGE_REPORTS_PREFIX": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "STORAGE_REPORTS_PREFIX",
        runtime_meta=_runtime_meta(
            type="str",
            category="Storage",
            description="Object prefix for generated reports",
        ),
    ),
    "GA4_SERVICE_ACCOUNT_JSON_PATH": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "GA4_SERVICE_ACCOUNT_JSON_PATH",
        runtime_meta=_runtime_meta(
            type="str",
            category="Analytics",
            description="Path to the GA4 service account credentials JSON file",
        ),
    ),
    "FEATURE_BILLING_ENABLED": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "FEATURE_BILLING_ENABLED",
        runtime_meta=_runtime_meta(
            type="bool",
            category="Billing",
            description="Enable or disable billing surfaces",
        ),
    ),
    "FEATURE_BILLING_GRACE_PERIOD": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "FEATURE_BILLING_GRACE_PERIOD",
        runtime_meta=_runtime_meta(
            type="bool",
            category="Billing",
            description="Enable or disable billing grace periods",
        ),
    ),
    "BILLING_GRACE_PERIOD_DAYS": ConfigDefinition(
        SECTION_RUNTIME_CONFIG,
        "BILLING_GRACE_PERIOD_DAYS",
        runtime_meta=_runtime_meta(
            type="int",
            min=0,
            max=60,
            category="Billing",
            description="Days a subscription can remain in grace period after failed payment",
        ),
    ),
}

ENV_TO_DB_MAP: dict[str, tuple[str, str]] = {
    key: (definition.section, definition.field) for key, definition in CONFIG_DEFINITIONS.items()
}
RUNTIME_CONFIGURABLE_KEYS: dict[str, dict[str, Any]] = {
    key: dict(definition.runtime_meta)
    for key, definition in CONFIG_DEFINITIONS.items()
    if definition.runtime_meta is not None
}
ALL_MANAGED_SECTIONS = tuple(
    dict.fromkeys(definition.section for definition in CONFIG_DEFINITIONS.values())
)

SENSITIVE_FIELD_PATTERNS = {
    "api_key",
    "secret",
    "password",
    "token",
    "login",
    "client_secret",
    "webhook_secret",
    "dsn",
    "credential",
}
SENSITIVE_KEY_PATTERNS = {"SECRET", "KEY", "PASSWORD", "TOKEN", "DSN", "CREDENTIAL"}


def is_sensitive_field(field_name: str) -> bool:
    lower = field_name.lower()
    return any(pattern in lower for pattern in SENSITIVE_FIELD_PATTERNS)


def is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return any(pattern in upper for pattern in SENSITIVE_KEY_PATTERNS)


def mask_value(value: Any) -> str:
    rendered = str(value or "")
    if len(rendered) <= 4:
        return "****"
    return "****" + rendered[-4:]


def _parse_boolish(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


class ConfigurationService:
    CACHE_TTL_SECONDS = 15

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._payload_cache: dict[str, Any] = {}
        self._payload_cache_ts: float = 0.0
        self._secret_provider = None

    def invalidate_cache(self) -> None:
        with self._lock:
            self._payload_cache = {}
            self._payload_cache_ts = 0.0

    def _open_session(self, db: Session | None) -> tuple[Session, bool]:
        if db is not None:
            return db, False
        return SessionLocal(), True

    @staticmethod
    def _touch_refresh_marker(op: models.OperationalSetting) -> None:
        op.cache_refresh_requested_at = datetime.now(timezone.utc)

    def _get_or_create_operational_settings(self, db: Session) -> models.OperationalSetting:
        op = db.query(models.OperationalSetting).first()
        if op is not None:
            return op

        op = models.OperationalSetting(
            fallback_model_enabled=True,
            pricing_v2_enabled=True,
            credit_engine_v2_enabled=True,
            pricing_v2_shadow_mode=False,
            pricing_v3_shadow_mode=False,
            report_retention_days=30,
            admin_settings_payload={},
        )
        db.add(op)
        db.commit()
        db.refresh(op)
        return op

    @staticmethod
    def _normalize_payload(payload: object) -> dict[str, Any]:
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _has_any_managed_section(payload: Mapping[str, Any]) -> bool:
        for section in ALL_MANAGED_SECTIONS:
            value = payload.get(section)
            if isinstance(value, dict) and value:
                return True
        return False

    def _env_value(
        self,
        key: str,
        *,
        env_settings: object | None = None,
        default: Any = None,
    ) -> Any:
        if env_settings is not None and hasattr(env_settings, key):
            return getattr(env_settings, key, default)

        if key in os.environ:
            return os.getenv(key, default)

        try:
            from core.config import get_env_setting_value

            return get_env_setting_value(key, default=default)
        except Exception:
            return os.getenv(key, default)

    def _bootstrap_seed_value(self, key: str) -> Any:
        if key in os.environ:
            return self._env_value(key, default=None)
        return None

    def _coerce_value(
        self,
        key: str,
        value: Any,
        *,
        env_settings: object | None = None,
        default: Any = None,
    ) -> Any:
        meta = RUNTIME_CONFIGURABLE_KEYS.get(key)
        if meta:
            value_type = meta.get("type", "str")
            if value_type == "int":
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return default
            if value_type == "bool":
                default_bool = default if isinstance(default, bool) else False
                return _parse_boolish(value, default=default_bool)
            return str(value)

        env_value = self._env_value(key, env_settings=env_settings, default=default)
        if isinstance(env_value, bool):
            return _parse_boolish(value, default=env_value)
        if isinstance(env_value, int) and not isinstance(env_value, bool):
            try:
                return int(value)
            except (TypeError, ValueError):
                return env_value
        return value

    def _seed_empty_payload_from_env(
        self, db: Session, op: models.OperationalSetting
    ) -> dict[str, Any]:
        payload = self._normalize_payload(op.admin_settings_payload)
        if self._has_any_managed_section(payload):
            return payload

        section_updates: dict[str, dict[str, Any]] = {}
        for key, definition in CONFIG_DEFINITIONS.items():
            seed_value = self._bootstrap_seed_value(key)
            if seed_value is None or seed_value == "":
                continue
            section_updates.setdefault(definition.section, {})[definition.field] = seed_value

        if not section_updates:
            return payload

        for section, updates in section_updates.items():
            payload[section] = dict(updates)

        op.admin_settings_payload = dict(payload)
        self._touch_refresh_marker(op)
        try:
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(op, "admin_settings_payload")
        except Exception:
            pass
        db.commit()
        db.refresh(op)
        logger.info(
            "Seeded operational settings payload from env/SSM bootstrap for sections: %s",
            ", ".join(sorted(section_updates)),
        )
        return self._normalize_payload(op.admin_settings_payload)

    def _load_payload_from_db(self, db: Session) -> dict[str, Any]:
        op = self._get_or_create_operational_settings(db)
        payload = self._normalize_payload(op.admin_settings_payload)
        if not payload or not self._has_any_managed_section(payload):
            payload = self._seed_empty_payload_from_env(db, op)
        return payload

    def get_payload(
        self, db: Session | None = None, *, force_refresh: bool = False
    ) -> dict[str, Any]:
        now = time.time()
        if not force_refresh:
            with self._lock:
                if now - self._payload_cache_ts < self.CACHE_TTL_SECONDS:
                    return dict(self._payload_cache)

        session, should_close = self._open_session(db)
        try:
            payload = self._load_payload_from_db(session)
        except Exception:
            logger.debug("Failed to load DB-backed configuration payload.", exc_info=True)
            payload = {}
        finally:
            if should_close:
                session.close()

        with self._lock:
            self._payload_cache = dict(payload)
            self._payload_cache_ts = time.time()
        return dict(payload)

    def get_section(
        self,
        section: str,
        db: Session | None = None,
        *,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        payload = self.get_payload(db, force_refresh=force_refresh)
        value = payload.get(section, {})
        return dict(value) if isinstance(value, dict) else {}

    def get_section_masked(self, section: str, db: Session | None = None) -> dict[str, Any]:
        section_payload = self.get_section(section, db)
        return {
            key: (mask_value(value) if is_sensitive_field(key) else value)
            for key, value in section_payload.items()
            if value is not None and value != ""
        }

    def resolve_value(
        self,
        key: str,
        *,
        db: Session | None = None,
        env_settings: object | None = None,
        default: Any = None,
        force_refresh: bool = False,
    ) -> Any:
        definition = CONFIG_DEFINITIONS.get(key)
        env_default = self._env_value(key, env_settings=env_settings, default=default)
        if definition is None:
            return env_default

        section = self.get_section(definition.section, db, force_refresh=force_refresh)
        raw_value = section.get(definition.field)
        if raw_value is None or raw_value == "":
            return env_default
        return self._coerce_value(
            key,
            raw_value,
            env_settings=env_settings,
            default=env_default,
        )

    def update_section(
        self,
        section: str,
        updates: Mapping[str, Any],
        db: Session,
    ) -> None:
        op = self._get_or_create_operational_settings(db)
        payload = self._normalize_payload(op.admin_settings_payload)
        current = payload.get(section, {})
        if not isinstance(current, dict):
            current = {}

        merged = dict(current)
        merged.update(dict(updates))
        payload[section] = {
            key: value for key, value in merged.items() if value is not None and value != ""
        }

        op.admin_settings_payload = dict(payload)
        self._touch_refresh_marker(op)
        try:
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(op, "admin_settings_payload")
        except Exception:
            pass
        db.commit()
        self.invalidate_cache()

    def get_runtime_overrides(self, db: Session | None = None) -> dict[str, Any]:
        return self.get_section(SECTION_RUNTIME_CONFIG, db)

    def get_all_sections_status(self, db: Session | None = None) -> dict[str, dict[str, Any]]:
        return {section: self.get_section_masked(section, db) for section in ALL_MANAGED_SECTIONS}

    def validate_runtime_value(self, key: str, value: Any) -> tuple[bool, str]:
        meta = RUNTIME_CONFIGURABLE_KEYS.get(key)
        if not meta:
            return False, f"Key '{key}' is not runtime-configurable."

        value_type = meta.get("type", "str")
        if value_type == "int":
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                return False, f"'{key}' must be an integer."
            min_value = meta.get("min")
            max_value = meta.get("max")
            if min_value is not None and normalized < min_value:
                return False, f"'{key}' minimum is {min_value}."
            if max_value is not None and normalized > max_value:
                return False, f"'{key}' maximum is {max_value}."
        elif value_type == "bool":
            normalized = str(value).strip().lower()
            if normalized not in {
                "0",
                "1",
                "true",
                "false",
                "yes",
                "no",
                "on",
                "off",
            } and not isinstance(value, bool):
                return False, f"'{key}' must be a boolean."
        else:
            options = meta.get("options")
            if options and str(value) not in options:
                return False, f"'{key}' must be one of: {', '.join(options)}."

        return True, ""

    def coerce_runtime_value(self, key: str, value: Any) -> Any:
        meta = RUNTIME_CONFIGURABLE_KEYS.get(key, {})
        value_type = meta.get("type", "str")
        if value_type == "int":
            return int(value)
        if value_type == "bool":
            return _parse_boolish(value, default=False)
        return str(value)

    def seed_from_env(self, db: Session, *, dry_run: bool = False) -> dict[str, list[str]]:
        seeded: list[str] = []
        skipped: list[str] = []
        section_updates: dict[str, dict[str, Any]] = {}

        for key, definition in CONFIG_DEFINITIONS.items():
            seed_value = self._bootstrap_seed_value(key)
            if seed_value is None or seed_value == "":
                skipped.append(key)
                continue

            existing = self.get_section(definition.section, db).get(definition.field)
            if existing not in (None, ""):
                skipped.append(key)
                continue

            section_updates.setdefault(definition.section, {})[definition.field] = seed_value
            seeded.append(key)

        if not dry_run:
            for section, updates in section_updates.items():
                self.update_section(section, updates, db)

        return {"seeded": seeded, "skipped": skipped}


configuration_service = ConfigurationService()
