import json
import os
from typing import Any, Optional

from pydantic import AliasChoices, AnyHttpUrl, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from core.env_bootstrap import bootstrap_environment

bootstrap_environment()


def normalize_runtime_environment(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"prod", "production", "live"}:
        return "production"
    if normalized in {"dev", "development", "local", "test"}:
        return "development"
    return normalized or "development"


def resolve_effective_gemini_api_key(
    gemini_api_key: Optional[str],
    google_api_key: Optional[str],
) -> Optional[str]:
    resolved = (gemini_api_key or google_api_key or "").strip()
    return resolved or None


def effective_gemini_api_key_from_env() -> Optional[str]:
    try:
        return resolve_effective_gemini_api_key(
            settings.GEMINI_API_KEY,
            settings.GOOGLE_API_KEY,
        )
    except Exception:
        return resolve_effective_gemini_api_key(
            os.getenv("GEMINI_API_KEY"),
            os.getenv("GOOGLE_API_KEY"),
        )


def _legacy_debate_cost_cap_default() -> float:
    raw_value = (os.getenv("DEBATE_COST_CAP_USD") or "0.25").strip()
    try:
        return float(raw_value)
    except ValueError:
        return 0.25


def _tiered_debate_cost_cap_default(minimum: float) -> float:
    return max(float(minimum), _legacy_debate_cost_cap_default())


class Settings(BaseSettings):
    """Canonical runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    ENVIRONMENT: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "APP_ENV"),
    )
    DOMAIN: Optional[str] = None
    APP_BASE_URL: str = "http://localhost:3000"
    FRONTEND_URL: str = "http://localhost:3000"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    CORS_ORIGINS: str = ""
    # Origins allowed to read the public plan catalog only. Kept separate from
    # CORS_ORIGINS because that allowlist is credentialed and applies to every
    # endpoint. Empty when the marketing site is same-origin (live).
    PUBLIC_SITE_ORIGINS: str = ""
    ALLOWED_HOSTS: str = "*"
    # Comma-separated CIDRs allowed to supply the x-forwarded-for chain and to
    # be skipped when walking it right-to-left. Default trusts loopback,
    # RFC1918 space (the Docker Traefik/Caddy/BFF hops) and the published
    # Cloudflare IPv4 ranges, the same ranges deploy/Caddyfile trusts.
    TRUSTED_PROXY_CIDRS: str = (
        "127.0.0.0/8,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,"
        "173.245.48.0/20,103.21.244.0/22,103.22.200.0/22,103.31.4.0/22,"
        "141.101.64.0/18,108.162.192.0/18,190.93.240.0/20,188.114.96.0/20,"
        "197.234.240.0/22,198.41.128.0/17,162.158.0.0/15,104.16.0.0/13,"
        "104.24.0.0/14,172.64.0.0/13,131.0.72.0/22"
    )
    RATE_LIMIT_PLANS_PUBLIC: str = "60/min"
    # Empty means "reuse GUEST_AUDIT_LIMIT / GUEST_AUDIT_WINDOW_SECONDS", so
    # the queued public path inherits the same per-IP budget as the legacy one
    # instead of quietly introducing a second, looser policy.
    RATE_LIMIT_GUEST_AUDIT_PUBLIC: str = ""

    # WebAuthn / Passkey configuration
    WEBAUTHN_RP_ID: str = "localhost"
    WEBAUTHN_RP_NAME: str = "Qiko Signal"
    WEBAUTHN_ORIGIN: str = "http://localhost:3000"
    # Operator-supplied CNAME target for workspace custom domains. Deliberately
    # unset: the approved hostname comes from the environment, and an empty or
    # invalid value disables the feature rather than serving an invented host.
    CUSTOM_DOMAIN_CNAME_TARGET: str = ""
    CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY: bool = True
    CUSTOM_DOMAIN_SYSTEM_HOSTS: str = ""
    CLOUDFLARE_API_TOKEN: Optional[str] = None
    CLOUDFLARE_ZONE_ID: Optional[str] = None
    CLOUDFLARE_API_BASE_URL: str = "https://api.cloudflare.com/client/v4"
    CLOUDFLARE_CUSTOM_HOSTNAME_VALIDATION_METHOD: str = "http"
    CLOUDFLARE_CUSTOM_ORIGIN_SERVER: Optional[str] = None
    DATABASE_URL: str = ""
    REDIS_URL: str = "redis://redis:6379"
    AI_SERVICE_URL: str = "http://ai-service:8001"
    RUN_MIGRATIONS: bool = True
    LOG_LEVEL: str = "INFO"

    SERVICE_CREDENTIAL_ROLE: Optional[str] = None
    CREDENTIAL_BOUNDARY_ENFORCE: bool = False

    # Service-to-service secret for Qiko Signal per-tenant key provisioning
    # (qiko-backend -> engine). When unset, the provisioning endpoint is disabled.
    SIGNAL_PROVISION_SECRET: Optional[str] = None
    SIGNAL_PROVISION_DEFAULT_CREDITS: int = 5
    S3_BUCKET_NAME: str = ""
    STORAGE_REPORTS_PREFIX: str = "reports/"
    STORAGE_LOGOS_PREFIX: str = "logos/"
    STORAGE_CMS_PREFIX: str = "cms/"
    STORAGE_REPORT_RETENTION_DAYS: int = 30
    STORAGE_SIGNED_URL_EXPIRY_MINUTES: int = 60
    LOCAL_STORAGE_ROOT: str = ""

    JWT_SECRET: Optional[str] = None
    JWT_SECRET_KEY: str = ""
    JWT_REFRESH_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REMEMBER_ME_ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080
    REMEMBER_ME_REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    SESSION_SECRET_KEY: str = ""
    EMAIL_TOKEN_EXPIRE_HOURS: int = 48
    PASSWORD_RESET_TOKEN_EXPIRE_HOURS: int = 24
    # Lifetime of a public audit share link, counted from the moment the token
    # is minted. Tokens issued before SIGV2-1250 have no expiry recorded and
    # keep working until they are rotated.
    AUDIT_SHARE_TOKEN_TTL_DAYS: int = 30
    EMAIL_VERIFICATION_REQUIRED: bool = True
    # Failed logins allowed per (client IP, account) before 429.
    LOGIN_RATE_LIMIT: int = 5
    LOGIN_RATE_WINDOW: int = 900
    # Failed logins allowed per client IP across all accounts (anti-spray).
    LOGIN_IP_RATE_LIMIT: int = 30
    LOGIN_IP_RATE_WINDOW: int = 300
    DEFAULT_RATE_LIMIT: int = 100
    DEFAULT_RATE_WINDOW: int = 60
    MAX_SESSIONS_PER_USER: int = 5
    SESSION_CLEANUP_INTERVAL: int = 3600
    ADMIN_EMAILS: str = ""
    MODERATOR_EMAILS: str = ""
    MFA_ISSUER: str = "Qiko Signal"
    MFA_SETUP_TOKEN_EXPIRE_SECONDS: int = 900
    OAUTH_TOKEN_ENCRYPTION_KEY: Optional[str] = None
    ALLOW_LEGACY_PLAINTEXT_SECRETS: bool = False

    MAIL_ENABLED: bool = False
    EMAIL_PROVIDER: str = "smtp"
    EMAIL_FROM_ADDRESS: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_FROM_ADDRESS", "MAIL_FROM"),
    )
    EMAIL_FROM_NAME: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("EMAIL_FROM_NAME", "MAIL_FROM_NAME"),
    )
    SMTP_HOST: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_HOST", "MAIL_SERVER"),
    )
    SMTP_PORT: int = Field(
        default=587,
        validation_alias=AliasChoices("SMTP_PORT", "MAIL_PORT"),
    )
    SMTP_USERNAME: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_USERNAME", "MAIL_USERNAME"),
    )
    SMTP_PASSWORD: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("SMTP_PASSWORD", "MAIL_PASSWORD"),
    )
    EMAIL_OUTBOX_MAX_ATTEMPTS: int = 5
    EMAIL_OUTBOX_POLL_INTERVAL_SECONDS: float = 15.0
    EMAIL_OUTBOX_ACTIVE_POLL_INTERVAL_SECONDS: float = 2.0
    EMAIL_OUTBOX_BATCH_SIZE: int = 25
    SUPPORT_EMAIL: Optional[str] = None
    BILLING_EMAIL: Optional[str] = None
    PRIVACY_EMAIL: Optional[str] = None
    CONTACT_INBOX_ADDRESS: Optional[str] = None
    CONTACT_TICKET_PREFIX: str = "STX"

    STRIPE_MODE: str = "test"
    STRIPE_SECRET_KEY_TEST: Optional[str] = None
    STRIPE_SECRET_KEY_LIVE: Optional[str] = None
    STRIPE_WEBHOOK_SECRET_TEST: Optional[str] = None
    STRIPE_WEBHOOK_SECRET_LIVE: Optional[str] = None
    STRIPE_PRICE_STANDARD: Optional[str] = None
    STRIPE_PRICE_SPECIALIST: Optional[str] = None
    STRIPE_PRICE_EXECUTIVE: Optional[str] = None
    STRIPE_PRICE_STANDARD_TEST: Optional[str] = None
    STRIPE_PRICE_SPECIALIST_TEST: Optional[str] = None
    STRIPE_PRICE_EXECUTIVE_TEST: Optional[str] = None
    STRIPE_PRICE_STANDARD_LIVE: Optional[str] = None
    STRIPE_PRICE_SPECIALIST_LIVE: Optional[str] = None
    STRIPE_PRICE_EXECUTIVE_LIVE: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_GROWTH_TEST: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_GROWTH_LIVE: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_SCALE_TEST: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_SCALE_LIVE: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_ENTERPRISE_TEST: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_ENTERPRISE_LIVE: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_OVERAGE_TEST: Optional[str] = None
    STRIPE_PRICE_COMMITMENT_OVERAGE_LIVE: Optional[str] = None
    FEATURE_BILLING_ENABLED: bool = True
    FEATURE_BILLING_GRACE_PERIOD: bool = True
    BILLING_GRACE_PERIOD_DAYS: int = 7
    STRIPE_WEBHOOK_QUEUE_NAME: str = "billing:webhook_events"

    GEMINI_API_KEY: Optional[str] = None
    GOOGLE_API_KEY: Optional[str] = None
    GOOGLE_FAST_MODEL: str = "gemini-3.5-flash"
    GOOGLE_SMART_MODEL: str = "gemini-3.5-flash"
    GOOGLE_LITE_MODEL: str = "gemini-3.1-flash-lite"
    CMS_GEMINI_TEXT_MODEL: str = "gemini-3.5-flash"
    CMS_GEMINI_IMAGE_MODEL: Optional[str] = None
    CMS_GEMINI_IMAGE_TIER: str = "flash"
    CMS_GEMINI_FLASH_IMAGE_MODEL: str = "gemini-2.5-flash-image"
    CMS_GEMINI_PRO_IMAGE_MODEL: str = "gemini-3-pro-image-preview"
    SUPPORT_CHAT_MODEL: str = "gemini-3.5-flash"
    GOOGLE_EMBEDDING_MODEL: str = "text-embedding-004"
    # OPENAI_*_MODEL routing keys are retained because core/model_resolution.py
    # (used by debate_orchestrator + cost_forecast_service) still resolves the
    # openai provider tier names from these env vars. The OpenAI/OpenRouter API
    # *keys/URLs* were removed — nothing in the engine calls those APIs anymore.
    OPENAI_LITE_MODEL: str = "gpt-4.1-nano"
    OPENAI_FAST_MODEL: str = "gpt-4.1-mini"
    OPENAI_SMART_MODEL: str = "gpt-4.1"
    ANTHROPIC_API_KEY: Optional[str] = None
    ANTHROPIC_LITE_MODEL: str = "claude-haiku-4.5"
    ANTHROPIC_FAST_MODEL: str = "claude-sonnet-4.6"
    ANTHROPIC_SMART_MODEL: str = "claude-opus-4.6"
    XAI_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    # --- AWS Bedrock (the engine's reasoning provider) ---
    # boto3 reads AWS_BEARER_TOKEN_BEDROCK (or standard AWS creds) from the
    # environment directly; no Settings field for the secret.
    BEDROCK_ENABLED: bool = True
    # eu-north-1 requires `eu.` inference-profile ids for on-demand invocation.
    BEDROCK_REGION: str = "eu-north-1"
    BEDROCK_LITE_MODEL: str = "eu.amazon.nova-micro-v1:0"
    BEDROCK_FAST_MODEL: str = "eu.amazon.nova-lite-v1:0"
    BEDROCK_SMART_MODEL: str = "eu.amazon.nova-pro-v1:0"
    # Cohere Embed v4 on Bedrock (eu-north-1), 1536-dim float embeddings.
    BEDROCK_EMBEDDING_MODEL: str = "eu.cohere.embed-v4:0"
    # When true (and BEDROCK_ENABLED), every reasoning/debate route resolves to
    # the Bedrock provider (audit + debate/team + pre-scan/site-classify).
    # Default false = zero behaviour change (prod stays on current providers).
    BEDROCK_ONLY_REASONING: bool = False
    # When true (and BEDROCK_ENABLED), every visibility (measurement-target)
    # run queries Bedrock models instead of the external engines. Default false
    # = zero behaviour change (visibility stays on the current external APIs).
    BEDROCK_ONLY_MEASUREMENT: bool = False
    # Maps each existing visibility provider key to a confirmed-serverless
    # Bedrock model id (the repositioned "engines"). Overridable via env as JSON.
    BEDROCK_MEASUREMENT_MODEL_MAP: dict[str, str] = Field(
        default_factory=lambda: {
            "openai": "openai.gpt-oss-120b-1:0",
            "google": "qwen.qwen3-235b-a22b-2507-v1:0",
            "anthropic": "eu.amazon.nova-pro-v1:0",
            "deepseek": "deepseek.v3.2",
            "perplexity": "zai.glm-5",
            "xai": "zai.glm-4.7",
            "bing": "eu.amazon.nova-pro-v1:0",
        }
    )
    # Per-region availability overrides for the measurement map (SIGV2-1028).
    # An engine listed with a model id substitutes for that region (only ever
    # a documented in-family substitution); an engine listed as None is
    # EXPLICITLY UNAVAILABLE in that region — it must never resolve to an
    # invalid model id and never silently substitute an unrelated model.
    # Engines absent from a region entry keep the default map entry.
    BEDROCK_MEASUREMENT_MODEL_REGION_OVERRIDES: dict[str, dict[str, Optional[str]]] = Field(
        default_factory=lambda: {
            "eu-central-1": {
                # Frankfurt carries zai.glm-4.7-flash but not zai.glm-4.7: same
                # GLM model family, so this is a defensible in-family
                # substitution for the xai proxy measurement.
                "xai": "zai.glm-4.7-flash",
                # deepseek.v3.2 and zai.glm-5 are not available in Frankfurt
                # and no related model exists to stand in for them; swapping
                # in an unrelated model (Qwen, GPT-OSS) would mislabel the
                # engine the measurement claims to represent. Explicitly
                # unavailable — since SIGV2-1023 both engines also have a live
                # OpenRouter primary, so the proxy degrades gracefully.
                "deepseek": None,
                "perplexity": None,
            }
        }
    )
    # --- OpenRouter live-engine measurement (Phase 11 / R10) ---
    # Measurement-only path: visibility queries run against the REAL consumer
    # models (GPT/Gemini/Claude/Grok/Perplexity/DeepSeek/Llama) via OpenRouter so
    # the "tracked across the engines people use" claim is accurate at model level.
    # Reasoning/debate/Advisor stay on Bedrock — do NOT route those here.
    # Default ON (SIGV2-1023): live measurement is enabled for all plans.
    # The real OPENROUTER_API_KEY is provisioned by a human into AWS SSM
    # (/qiko-signal/) + local .env; it must NEVER be committed or logged.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LIVE_ENGINE_MEASUREMENT_ENABLED: bool = True
    # Web retrieval for live measurement (SIGV2-1183). When ON, each measurement
    # request carries the OpenRouter `openrouter:web_search` server tool, so the
    # model can ground its answer in what the web says TODAY instead of its
    # trained weights. Without it only perplexity/sonar retrieves live.
    # Default ON since SIGV2-1188: enabling it multiplies the per-measurement
    # cost (search fees land in `usage.cost` on top of tokens), and the per-plan
    # prompt caps, engine rosters and sweep cadences in VISIBILITY_PLAN_LIMITS
    # are what bound that spend per plan.
    #
    # SIGV2-1216: that is a claim about two files agreeing, and it stopped
    # being true the day SIGV2-1211 repriced Specialist from $399 to $99
    # without touching the ladder, which put modelled measurement cost at about
    # 81% of the price. Specialist now sweeps every two days across four
    # engines, which brings it back to about 30%. Anyone changing a price or a
    # roster has to recompute this: the table in project_visibility_service.py
    # carries the per-engine arithmetic.
    OPENROUTER_WEB_SEARCH_ENABLED: bool = True
    # Maps each visibility engine key to a current OpenRouter model id. Override
    # via env as JSON. NOTE: Bing has NO entry — there is no public consumer API
    # for Bing/Copilot answers on OpenRouter, so it cannot be measured live and
    # stays on the controlled Bedrock panel.
    OPENROUTER_MEASUREMENT_MODEL_MAP: dict[str, str] = Field(
        default_factory=lambda: {
            "openai": "openai/gpt-5",
            "google": "google/gemini-2.5-pro",
            "anthropic": "anthropic/claude-sonnet-4.5",
            "xai": "x-ai/grok-4.3",
            "perplexity": "perplexity/sonar",
            "deepseek": "deepseek/deepseek-chat",
            "meta": "meta-llama/llama-4-maverick",
        }
    )
    # Master switch for AI-generated CMS content (blog articles + case studies).
    # Set false to retire AI content generation (single-vendor Bedrock cleanup).
    CMS_AI_GENERATION_ENABLED: bool = True
    FIRECRAWL_API_KEY: Optional[str] = None
    PAGESPEED_API_KEY: Optional[str] = None
    SEARCH_API_KEY: Optional[str] = None
    SEARCH_API_URL: Optional[str] = None
    SERPAPI_API_KEY: Optional[str] = None
    SERPAPI_URL: str = "https://serpapi.com/search.json"
    SERPAPI_ENGINE: str = "google"
    GOOGLE_PLACES_API_KEY: Optional[str] = None
    GOOGLE_MAPS_API_KEY: Optional[str] = None
    GOOGLE_PLACES_API_MODE: str = "new"
    GOOGLE_PLACES_FALLBACK_TO_LEGACY: bool = True
    GOOGLE_PLACES_NEW_TEXTSEARCH_URL: str = "https://places.googleapis.com/v1/places:searchText"
    GOOGLE_PLACES_NEW_FIELD_MASK: str = "places.displayName,places.name"
    DATAFORSEO_LOGIN: Optional[str] = None
    DATAFORSEO_PASSWORD: Optional[str] = None
    GA4_SERVICE_ACCOUNT_JSON_PATH: Optional[str] = None

    GOOGLE_CLIENT_ID: Optional[str] = None
    GOOGLE_CLIENT_SECRET: Optional[str] = None
    # Search Console Pages: minimum impressions before a page's Opportunity is
    # evaluated (contract docs/search-console-reporting-contract.md section 7).
    GSC_OPPORTUNITY_MIN_IMPRESSIONS: int = 50
    GITHUB_CLIENT_ID: Optional[str] = None
    GITHUB_CLIENT_SECRET: Optional[str] = None
    LINKEDIN_CLIENT_ID: str = ""
    LINKEDIN_CLIENT_SECRET: str = ""
    LINKEDIN_REDIRECT_URI: AnyHttpUrl | None = None
    JIRA_CLIENT_ID: Optional[str] = None
    JIRA_CLIENT_SECRET: Optional[str] = None
    BING_CLIENT_ID: Optional[str] = None
    BING_CLIENT_SECRET: Optional[str] = None
    # Bing Webmaster OAuth client (registered in the Webmaster portal under
    # Settings > API Access > OAuth Client). Empty keeps the feature inert:
    # connecting Bing reports explicitly unavailable rather than failing.
    BING_WEBMASTER_CLIENT_ID: Optional[str] = None
    BING_WEBMASTER_CLIENT_SECRET: Optional[str] = None
    BING_WEBMASTER_API_KEY: Optional[str] = None
    BING_TENANT_ID: str = "common"
    BING_OAUTH_SCOPE: str = "openid profile email offline_access"
    MICROSOFT_SSO_CLIENT_ID: Optional[str] = None
    MICROSOFT_SSO_CLIENT_SECRET: Optional[str] = None
    MICROSOFT_SSO_TENANT_ID: str = "common"

    AUDIT_QUEUE_NAME: str = "audit_jobs"
    AUDIT_QUEUE_METRICS_KEY: str = "audit:metrics"
    AUDIT_JOB_MAX_ATTEMPTS: int = 3
    MAX_CONCURRENT_AUDITS: int = 4
    AUDIT_JOB_RETRY_DELAY_SECONDS: float = 2.0
    AUDIT_JOB_TIMEOUT_SECONDS: int = 900
    AUDIT_OUTPUT_LANGUAGE: str = "en"
    GUEST_AUDIT_LIMIT: int = 1
    GUEST_AUDIT_WINDOW_SECONDS: int = 86400
    # Queued public guest audit (marketing site). An audit takes tens of
    # seconds, so the public path is submit plus poll and these bound the job
    # lifecycle rather than a request timeout.
    GUEST_AUDIT_QUEUE_NAME: str = "guest_audit_jobs"
    GUEST_AUDIT_JOB_TTL_SECONDS: int = 1800
    GUEST_AUDIT_JOB_TIMEOUT_SECONDS: int = 300
    # Dedupe window for complex report generation. The fingerprint covers
    # audit ids, not audit content, so a long window would hand a stale
    # report to someone deliberately regenerating after the data changed.
    # This absorbs double-clicks and client retries, nothing more.
    COMPLEX_REPORT_IDEMPOTENCY_WINDOW_SECONDS: int = 60
    GUEST_AUDIT_POLL_INTERVAL_MS: int = 3000
    # Backpressure, not a spend ceiling: it caps how many unstarted guest jobs
    # can be waiting at once, so a burst is refused at submit time instead of
    # queueing an unbounded amount of paid work.
    GUEST_AUDIT_MAX_QUEUE_DEPTH: int = 50
    GUEST_AUDIT_WORKER_CONCURRENCY: int = 2
    # A repeat submission for the same target inside this window is joined to
    # the job already running for it rather than paying for it twice.
    GUEST_AUDIT_TARGET_COOLDOWN_SECONDS: int = 900
    DEBATE_ENABLED: bool = True
    # EPIC 11 / S11.1 quick-scan: opt-in fast audit path that returns only the
    # deterministic component of an audit (skips LLM reasoning). Defaults OFF so
    # existing "lite" requests continue to route to the full fast audit.
    QUICK_SCAN_ENABLED: bool = False

    # EPIC 13 (re-scoped) — Advisor: a deterministic reducer that re-orders the
    # audit's already-grounded recommendations into a prioritized action plan,
    # plan-gated to specialist+ (has_advisor_synthesis). ENABLED in preprod;
    # DETERMINISTIC_ONLY=False also adds the single optional LLM strategic_summary.
    ADVISOR_SYNTHESIS_ENABLED: bool = True
    ADVISOR_DETERMINISTIC_ONLY: bool = False
    ADVISOR_MAX_ACTIONS: int = 10
    # Increment 3: a single optional Bedrock call that narrativizes the (grounded)
    # plan into a short strategic_summary. Only runs when ADVISOR_DETERMINISTIC_ONLY
    # is False. Never adds facts beyond the given actions.
    ADVISOR_SUMMARY_MAX_TOKENS: int = 400

    DEBATE_COST_CAP_USD: float = 0.25
    DEBATE_COST_CAP_MULTIPLIER: float = 1.35
    DEBATE_TOTAL_TIMEOUT_FAST_S: int = 60
    DEBATE_STEP_TIMEOUT_FAST_S: int = 15
    DEBATE_COST_CAP_FAST_USD: float = Field(
        default_factory=lambda: _tiered_debate_cost_cap_default(0.50)
    )
    DEBATE_TOTAL_TIMEOUT_SMART_S: int = 480
    DEBATE_STEP_TIMEOUT_SMART_S: int = 90
    DEBATE_COST_CAP_SMART_USD: float = Field(
        default_factory=lambda: _tiered_debate_cost_cap_default(5.00)
    )
    DEBATE_TOTAL_TIMEOUT_DEEP_S: int = 600
    DEBATE_STEP_TIMEOUT_DEEP_S: int = 90
    DEBATE_COST_CAP_DEEP_USD: float = Field(
        default_factory=lambda: _tiered_debate_cost_cap_default(20.00)
    )
    ANTHROPIC_MAX_TRANSFER_PACKET_CHARS: int = 8000
    ANTHROPIC_MAX_CRITIQUE_PACKET_CHARS: int = 6000
    ANTHROPIC_MAX_CONSOLIDATED_PACKET_CHARS: int = 12000
    ANTHROPIC_MAX_AUDIT_DATA_CHARS: int = 10000
    DEBATE_PIPELINE_VERSION: str = "v3"  # "v2" | "v3", controls the active pipeline
    # Greedy decoding for every scoring, judging and synthesis call. Any value
    # above 0 samples, so two identical audit inputs can return different
    # scores (SIGV2-1109). There is no sampling seed to fall back on: the only
    # reasoning provider is AWS Bedrock, and the converse API's inferenceConfig
    # accepts maxTokens, temperature, topP and stopSequences only.
    AUDIT_AI_TEMPERATURE: float = 0.0
    AUDIT_CRITIC_TEMPERATURE: float = (
        0.0  # Debate critics, kept at audit temperature for deterministic SEO/AEO scoring
    )
    # Score blend weights (deterministic vs AI). Higher deterministic weight
    # yields more consistent scores run-to-run because the deterministic signal
    # portion is reproducible. Must sum to ~1.0.
    AUDIT_DETERMINISTIC_SCORE_WEIGHT: float = 0.7
    AUDIT_AI_SCORE_WEIGHT: float = 0.3

    # AIO roll-up weights (customer-facing AIO = weighted mean of AEO + GEO).
    # Tunable without code change; default 50/50 yields the simple mean.
    AIO_AEO_WEIGHT: float = 0.5
    AIO_GEO_WEIGHT: float = 0.5
    # Product-level default score targets used when a project has no persisted
    # override (projects.aio_score_target / seo_score_target NULL). Values are
    # product configuration, recorded here so deployments can override them.
    PROJECT_DEFAULT_AIO_SCORE_TARGET: int = 78
    PROJECT_DEFAULT_SEO_SCORE_TARGET: int = 85

    TRACING_BACKEND: str = "none"
    SENTRY_DSN: Optional[str] = None
    SENTRY_DSN_AUDIT_API: Optional[str] = None
    SENTRY_DSN_AUDIT_WORKER: Optional[str] = None
    SENTRY_DSN_AI_SERVICE: Optional[str] = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.2
    SENTRY_ENVIRONMENT: str = "development"
    SENTRY_RELEASE: Optional[str] = None

    _UNSAFE_SECRET_VALUES = {
        "",
        "dev-secret",
        "session_secret_fallback",
        "dev_session_fallback",
        "changeme",
        "dev_oauth_token_encryption_key_change_me",
    }

    _MIN_SESSION_SECRET_LENGTH = 32

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _normalize_environment_value(cls, value: Any) -> str:
        return normalize_runtime_environment(None if value is None else str(value))

    @field_validator("EMAIL_PROVIDER", "TRACING_BACKEND", "STRIPE_MODE", mode="before")
    @classmethod
    def _normalize_lowercase_text(cls, value: Any) -> str:
        return str(value or "").strip().lower()

    @model_validator(mode="after")
    def _derive_webauthn_defaults(self) -> "Settings":
        """Auto-derive WebAuthn RP ID and origin from FRONTEND_URL when left at defaults."""
        from urllib.parse import urlparse

        frontend_parsed = urlparse(self.FRONTEND_URL)
        frontend_hostname = (frontend_parsed.hostname or "").lower()
        if (
            self.WEBAUTHN_RP_ID == "localhost"
            and frontend_hostname
            and frontend_hostname != "localhost"
        ):
            object.__setattr__(self, "WEBAUTHN_RP_ID", frontend_hostname)
        if (
            self.WEBAUTHN_ORIGIN == "http://localhost:3000"
            and frontend_hostname
            and frontend_hostname != "localhost"
        ):
            origin = f"{frontend_parsed.scheme}://{frontend_parsed.hostname}"
            if frontend_parsed.port and frontend_parsed.port not in (80, 443):
                origin += f":{frontend_parsed.port}"
            object.__setattr__(self, "WEBAUTHN_ORIGIN", origin)
        return self

    @model_validator(mode="after")
    def _validate_deployed_secrets(self) -> "Settings":
        # The test is "not development" rather than "is production" on purpose,
        # matching resolved_session_secret below. normalize_runtime_environment
        # passes unknown values through unchanged, so "preprod" and "staging"
        # reach here as themselves: deployed, internet-facing environments that
        # were previously unguarded. It is therefore fail-safe by construction:
        # a new or misspelled ENVIRONMENT value enforces secrets instead of
        # silently skipping enforcement.
        if self.ENVIRONMENT == "development":
            return self
        missing: list[str] = []
        if not self.JWT_SECRET_KEY or self.JWT_SECRET_KEY in self._UNSAFE_SECRET_VALUES:
            missing.append("JWT_SECRET_KEY")
        if (
            not self.JWT_REFRESH_SECRET_KEY
            or self.JWT_REFRESH_SECRET_KEY in self._UNSAFE_SECRET_VALUES
        ):
            missing.append("JWT_REFRESH_SECRET_KEY")
        if not self.SESSION_SECRET_KEY or self.SESSION_SECRET_KEY in self._UNSAFE_SECRET_VALUES:
            missing.append("SESSION_SECRET_KEY")
        elif len(self.SESSION_SECRET_KEY) < self._MIN_SESSION_SECRET_LENGTH:
            missing.append(
                f"SESSION_SECRET_KEY (must be >= {self._MIN_SESSION_SECRET_LENGTH} chars)"
            )
        elif self.SESSION_SECRET_KEY == self.JWT_SECRET_KEY:
            missing.append("SESSION_SECRET_KEY (must differ from JWT_SECRET_KEY)")
        if (
            not self.OAUTH_TOKEN_ENCRYPTION_KEY
            or self.OAUTH_TOKEN_ENCRYPTION_KEY in self._UNSAFE_SECRET_VALUES
            or self.OAUTH_TOKEN_ENCRYPTION_KEY == self.JWT_SECRET_KEY
            or (self.JWT_SECRET and self.OAUTH_TOKEN_ENCRYPTION_KEY == self.JWT_SECRET)
            or self.OAUTH_TOKEN_ENCRYPTION_KEY == self.SESSION_SECRET_KEY
        ):
            missing.append("OAUTH_TOKEN_ENCRYPTION_KEY")
        if self.ALLOW_LEGACY_PLAINTEXT_SECRETS:
            missing.append("ALLOW_LEGACY_PLAINTEXT_SECRETS=false")
        # SEC-04: Redis auth/TLS validation
        from core.redis_client import validate_redis_url_production

        redis_issues = validate_redis_url_production(self.REDIS_URL)
        if redis_issues:
            missing.extend(f"REDIS_URL ({issue})" for issue in redis_issues)
        if missing:
            raise ValueError(
                f"The {self.ENVIRONMENT!r} environment requires secure values for: "
                f"{', '.join(missing)}. "
                'Set these environment variables to strong, unique secrets.'
            )
        return self

    @staticmethod
    def _parse_env_list(value: Any, *, trim_trailing_slash: bool = False) -> list[str]:
        if value is None:
            return []

        if isinstance(value, (list, tuple, set)):
            items = [str(item).strip() for item in value if str(item).strip()]
        elif isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []

            parsed: Any = None
            if raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = None

            if isinstance(parsed, list):
                items = [str(item).strip() for item in parsed if str(item).strip()]
            elif isinstance(parsed, str):
                items = [parsed.strip()] if parsed.strip() else []
            else:
                items = [segment.strip() for segment in raw.split(",") if segment.strip()]
        else:
            rendered = str(value).strip()
            items = [rendered] if rendered else []

        if trim_trailing_slash:
            return [item.rstrip("/") for item in items]
        return items

    @property
    def APP_ENV(self) -> str:
        return self.ENVIRONMENT

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cors_origins(self) -> list[str]:
        return self._parse_env_list(self.CORS_ORIGINS, trim_trailing_slash=True)

    @property
    def public_site_origins(self) -> list[str]:
        return self._parse_env_list(self.PUBLIC_SITE_ORIGINS, trim_trailing_slash=True)

    @property
    def allowed_hosts(self) -> list[str]:
        return self._parse_env_list(self.ALLOWED_HOSTS)

    @property
    def trusted_proxy_cidrs(self) -> list[str]:
        return self._parse_env_list(self.TRUSTED_PROXY_CIDRS)

    @property
    def session_cookie_secure(self) -> bool:
        """Returns True if the environment is not development, enforcing HTTPS-only session cookies."""
        return self.ENVIRONMENT != "development"

    @property
    def resolved_session_secret(self) -> str:
        """Resolve the session middleware signing key.

        In development: falls back to JWT_SECRET_KEY, then a dev-only literal.
        Outside development: requires a dedicated SESSION_SECRET_KEY and raises
        at startup if it is missing, weak, or shared with JWT_SECRET_KEY.
        """
        key = (self.SESSION_SECRET_KEY or "").strip()
        if key and key not in self._UNSAFE_SECRET_VALUES:
            return key
        if self.ENVIRONMENT == "development":
            fallback = (self.JWT_SECRET_KEY or "").strip()
            return fallback if fallback else "dev_session_fallback"
        raise ValueError(
            "SESSION_SECRET_KEY is required outside local development. "
            "Set a strong, unique secret (>= 32 characters) that differs from JWT_SECRET_KEY."
        )

    @property
    def effective_gemini_api_key(self) -> Optional[str]:
        return resolve_effective_gemini_api_key(self.GEMINI_API_KEY, self.GOOGLE_API_KEY)


class RuntimeBackedSettings:
    def __init__(self, base_settings: Settings):
        super().__setattr__("_base_settings", base_settings)
        super().__setattr__("_local_overrides", {})

    @property
    def model_fields(self):  # pragma: no cover - thin delegation
        return self._base_settings.model_fields

    @property
    def APP_ENV(self) -> str:
        return self.ENVIRONMENT

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def cors_origins(self) -> list[str]:
        return self._base_settings._parse_env_list(self.CORS_ORIGINS, trim_trailing_slash=True)

    @property
    def public_site_origins(self) -> list[str]:
        return self._base_settings._parse_env_list(
            self.PUBLIC_SITE_ORIGINS, trim_trailing_slash=True
        )

    @property
    def allowed_hosts(self) -> list[str]:
        return self._base_settings._parse_env_list(self.ALLOWED_HOSTS)

    @property
    def session_cookie_secure(self) -> bool:
        return self.ENVIRONMENT != "development"

    @property
    def resolved_session_secret(self) -> str:
        """Delegate to the base Settings implementation."""
        key = (self.SESSION_SECRET_KEY or "").strip()
        if key and key not in self._base_settings._UNSAFE_SECRET_VALUES:
            return key
        if self.ENVIRONMENT == "development":
            fallback = (self.JWT_SECRET_KEY or "").strip()
            return fallback if fallback else "dev_session_fallback"
        raise ValueError(
            "SESSION_SECRET_KEY is required outside local development. "
            "Set a strong, unique secret (>= 32 characters) that differs from JWT_SECRET_KEY."
        )

    @property
    def effective_gemini_api_key(self) -> Optional[str]:
        return resolve_effective_gemini_api_key(self.GEMINI_API_KEY, self.GOOGLE_API_KEY)

    def __getattr__(self, name: str) -> Any:
        if name in self._local_overrides:
            return self._local_overrides[name]

        from services.configuration_service import CONFIG_DEFINITIONS, configuration_service

        if name in CONFIG_DEFINITIONS:
            env_default = getattr(self._base_settings, name, None)
            return configuration_service.resolve_value(
                name,
                env_settings=self._base_settings,
                default=env_default,
            )

        return getattr(self._base_settings, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"_base_settings", "_local_overrides"}:
            super().__setattr__(name, value)
            return
        self._local_overrides[name] = value

    def __delattr__(self, name: str) -> None:
        if name in self._local_overrides:
            del self._local_overrides[name]
            return
        delattr(self._base_settings, name)


_ENV_SETTINGS = Settings()


def get_env_setting_value(key: str, *, default: Any = None) -> Any:
    return getattr(_ENV_SETTINGS, key, default)


settings = RuntimeBackedSettings(_ENV_SETTINGS)
