# Admin Configuration (DB-Backed Runtime Overrides)

## Overview

The platform supports **runtime-configurable settings** that can be changed from
the admin UI without restarting containers. These live in the
`OperationalSetting.admin_settings_payload` JSON column (PostgreSQL) and are
managed by `backend/services/configuration_service.py`.

## Architecture

```
┌──────────────┐    ┌───────────────┐    ┌───────────────────┐
│ Admin UI     │───>│ Admin API     │───>│ OperationalSetting│
│ /admin/config│    │ /admin/config │    │ (DB, JSON column) │
└──────────────┘    └───────────────┘    └───────────────────┘
                           │
                    ┌──────┴──────┐
                    │ ConfigSvc   │
                    │ (15s cache) │
                    └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         DB runtime    env / SSM     defaults
         (highest)     (fallback)    (lowest)
```

## Resolution Priority

`ConfigurationService.resolve_value(key)` resolves values in this order:

1. **DB runtime override** — stored in `admin_settings_payload["runtime_config"][key]`
2. **Environment variable / SSM secret** — `os.environ[key]` or Pydantic `Settings`
3. **Default value** — from `Settings` field defaults in `core/config.py`

The admin UI shows the source for each value as a badge: `runtime`, `env`, or `default`.

## Cache & Hot-Reload

- **Cache TTL**: 15 seconds (`ConfigurationService.CACHE_TTL_SECONDS`)
- **Invalidation**: `invalidate_cache()` is called on every `update_section()` and
  on `PATCH /admin/config` / `DELETE /admin/config/{key}` endpoints
- **Hot-reload**: Changes take effect within 15 seconds for all workers/processes
  that call `resolve_value()`. No container restart required.

## Admin API Endpoints

| Method   | Path                  | Description                                |
|----------|-----------------------|--------------------------------------------|
| `GET`    | `/admin/config`       | Full config view (all Settings fields)     |
| `GET`    | `/admin/config/editable` | Only runtime-configurable keys          |
| `PATCH`  | `/admin/config`       | Update one or more runtime overrides       |
| `DELETE` | `/admin/config/{key}` | Remove a runtime override (revert to env)  |

All endpoints require admin authentication (`get_current_user` + admin role).

## First-Boot Seeding

On first access, if `admin_settings_payload` has no managed sections,
`_seed_empty_payload_from_env()` auto-populates from env vars and SSM secrets.
This ensures the DB has sensible values even before an admin visits the config page.

## Runtime-Configurable Keys

### AI Models

| Key                     | Type   | Options                                          | Description                    |
|-------------------------|--------|--------------------------------------------------|--------------------------------|
| `GOOGLE_FAST_MODEL`     | `str`  | `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite` | Google fast-tier model |
| `GOOGLE_SMART_MODEL`    | `str`  | `gemini-2.5-pro`, `gemini-2.5-flash`             | Google smart-tier model        |
| `GOOGLE_LITE_MODEL`     | `str`  | `gemini-2.5-flash-lite`, `gemini-2.5-flash`      | Google lite-tier model         |
| `OPENAI_LITE_MODEL`     | `str`  | `gpt-5-nano`, `gpt-5-mini`                       | OpenAI lite-tier model         |
| `OPENAI_FAST_MODEL`     | `str`  | `gpt-5-mini`, `gpt-5-nano`, `gpt-5.4`            | OpenAI fast-tier model         |
| `OPENAI_SMART_MODEL`    | `str`  | `gpt-5.4`, `gpt-5-mini`, `gpt-5-nano`            | OpenAI smart-tier model        |
| `ANTHROPIC_LITE_MODEL`  | `str`  | `claude-haiku-4-5`, `claude-sonnet-4-6`           | Anthropic lite-tier model      |
| `ANTHROPIC_FAST_MODEL`  | `str`  | `claude-sonnet-4-6`, `claude-haiku-4-5`, `claude-opus-4-6` | Anthropic fast-tier model |
| `ANTHROPIC_SMART_MODEL` | `str`  | `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5` | Anthropic smart-tier model |
| `CMS_GEMINI_TEXT_MODEL`  | `str`  | `gemini-2.5-pro`, `gemini-2.5-flash`            | CMS text generation model      |
| `CMS_GEMINI_IMAGE_TIER`  | `str`  | `flash`, `pro`                                  | CMS image generation tier      |
| `SUPPORT_CHAT_MODEL`     | `str`  | `gemini-2.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.5-pro` | Support chat model |

### Rate Limiting

| Key                     | Type  | Min  | Max   | Description                           |
|-------------------------|-------|------|-------|---------------------------------------|
| `LOGIN_RATE_LIMIT`      | `int` | 1    | 100   | Max login attempts per window         |
| `LOGIN_RATE_WINDOW`     | `int` | 60   | 3600  | Login rate limit window in seconds    |
| `DEFAULT_RATE_LIMIT`    | `int` | 10   | 10000 | Default API rate limit per window     |
| `DEFAULT_RATE_WINDOW`   | `int` | 10   | 3600  | Default rate limit window in seconds  |
| `MAX_SESSIONS_PER_USER` | `int` | 1    | 50    | Maximum concurrent sessions per user  |

### Auth

| Key                            | Type   | Min | Max  | Description                                       |
|--------------------------------|--------|-----|------|---------------------------------------------------|
| `ACCESS_TOKEN_EXPIRE_MINUTES`  | `int`  | 5   | 1440 | JWT access token lifetime in minutes              |
| `REFRESH_TOKEN_EXPIRE_DAYS`    | `int`  | 1   | 90   | JWT refresh token lifetime in days                |
| `EMAIL_VERIFICATION_REQUIRED`  | `bool` | —   | —    | Require email verification before account activation |

### Workers

| Key                        | Type  | Min | Max | Description                              |
|----------------------------|-------|-----|-----|------------------------------------------|
| `AUDIT_JOB_MAX_ATTEMPTS`  | `int` | 1   | 10  | Max retry attempts for audit jobs        |
| `AUDIT_JOB_TIMEOUT_SECONDS` | `int` | 60 | 3600 | Timeout per audit job in seconds       |
| `GUEST_AUDIT_LIMIT`       | `int` | 0   | 10  | Max audits for guest users               |
| `GUEST_AUDIT_WINDOW_SECONDS` | `int` | 3600 | 604800 | Guest audit rate window in seconds |
| `EMAIL_OUTBOX_MAX_ATTEMPTS`  | `int` | 1  | 20  | Max email delivery attempts              |
| `EMAIL_OUTBOX_BATCH_SIZE`    | `int` | 1  | 200 | Emails processed per outbox worker batch |

### AI Debate

| Key                              | Type  | Min | Max  | Description                                   |
|----------------------------------|-------|-----|------|-----------------------------------------------|
| `DEBATE_TOTAL_TIMEOUT_FAST_S`   | `int` | 15  | 300  | FAST debate total timeout in seconds          |
| `DEBATE_STEP_TIMEOUT_FAST_S`    | `int` | 5   | 120  | FAST debate per-step timeout in seconds       |
| `DEBATE_COST_CAP_FAST_EUR`      | `str` | —   | —    | FAST debate hard cost cap in USD              |
| `DEBATE_TOTAL_TIMEOUT_SMART_S`  | `int` | 60  | 1800 | SMART debate total timeout in seconds         |
| `DEBATE_STEP_TIMEOUT_SMART_S`   | `int` | 15  | 300  | SMART debate per-step timeout in seconds      |
| `DEBATE_COST_CAP_SMART_EUR`     | `str` | —   | —    | SMART debate hard cost cap in USD             |
| `DEBATE_TOTAL_TIMEOUT_DEEP_S`   | `int` | 120 | 3600 | DEEP_JUDGMENT debate total timeout in seconds |
| `DEBATE_STEP_TIMEOUT_DEEP_S`    | `int` | 30  | 600  | DEEP_JUDGMENT debate per-step timeout in seconds |
| `DEBATE_COST_CAP_DEEP_EUR`      | `str` | —   | —    | DEEP_JUDGMENT debate hard cost cap in USD     |

### Claim Ledger

| Key                                  | Type  | Min | Max | Description                                  |
|--------------------------------------|-------|-----|-----|----------------------------------------------|
| `DEBATE_CLAIM_LEDGER_MAX_ITEMS`      | `int` | 3   | 30  | Maximum claims per transfer packet           |
| `CLAIM_LEDGER_PRIORITY_RECOMMENDATION` | `int` | 100 | 500 | Base priority score for recommendations   |
| `CLAIM_LEDGER_PRIORITY_FINDING`      | `int` | 100 | 500 | Base priority score for findings             |
| `CLAIM_LEDGER_SEVERITY_CRITICAL`     | `str` | —   | —   | Confidence score for critical-severity claims |

### Search Config

| Key                                | Type   | Options                        | Description                                      |
|------------------------------------|--------|--------------------------------|--------------------------------------------------|
| `SERPAPI_ENGINE`                   | `str`  | `google`, `bing`, `duckduckgo` | SerpAPI search engine                            |
| `GOOGLE_PLACES_API_MODE`          | `str`  | `new`, `legacy`                | Google Places API mode                           |
| `GOOGLE_PLACES_FALLBACK_TO_LEGACY`| `bool` | —                              | Allow Google Places legacy fallback on failure   |

### General

| Key                     | Type  | Options                             | Description                              |
|-------------------------|-------|--------------------------------------|------------------------------------------|
| `LOG_LEVEL`             | `str` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Application log level                    |
| `AUDIT_OUTPUT_LANGUAGE` | `str` | —                                    | Default language for audit report output |

### Infrastructure

| Key                    | Type  | Description                                                                                             |
|------------------------|-------|---------------------------------------------------------------------------------------------------------|
| `CORS_ORIGINS`         | `str` | Comma-separated allowed browser origins for CORS (credentialed, applies to every endpoint)              |
| `PUBLIC_SITE_ORIGINS`  | `str` | Comma-separated marketing-site origins allowed to read `GET /api/v1/billing/plans/public` (no credentials, that endpoint only). Empty when the site is same-origin |
| `ALLOWED_HOSTS`        | `str` | Comma-separated hostnames accepted by host validation                                                   |

### Storage

| Key                  | Type  | Description                                           |
|----------------------|-------|-------------------------------------------------------|
| `GCS_BUCKET_NAME`    | `str` | Google Cloud Storage bucket for report and logo assets |
| `GCS_REPORTS_PREFIX` | `str` | Object prefix for generated reports                   |

### Analytics

| Key                            | Type  | Description                                        |
|--------------------------------|-------|----------------------------------------------------|
| `GA4_SERVICE_ACCOUNT_JSON_PATH`| `str` | Path to the GA4 service account credentials JSON   |

### Billing

| Key                            | Type   | Min | Max | Description                                               |
|--------------------------------|--------|-----|-----|------------------------------------------------------------|
| `FEATURE_BILLING_ENABLED`      | `bool` | —   | —   | Enable or disable billing surfaces                        |
| `FEATURE_BILLING_GRACE_PERIOD` | `bool` | —   | —   | Enable or disable billing grace periods                   |
| `BILLING_GRACE_PERIOD_DAYS`    | `int`  | 0   | 60  | Days a subscription can remain in grace period             |

## Non-Editable Config Sections (Seeded from Env/SSM)

These keys are stored in the DB payload but are **not** editable from the
runtime config admin UI. They are seeded on first boot from env/SSM.

### AI Provider Keys (`ai_provider_keys`)

`GEMINI_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
`FIRECRAWL_API_KEY`, `PAGESPEED_API_KEY`, `SEARCH_API_KEY`, `SERPAPI_API_KEY`,
`GOOGLE_PLACES_API_KEY`, `GOOGLE_MAPS_API_KEY`, `DATAFORSEO_LOGIN`,
`DATAFORSEO_PASSWORD`

### Email Config (`email_config`)

`MAIL_ENABLED`, `EMAIL_PROVIDER`, `EMAIL_FROM_ADDRESS`, `EMAIL_FROM_NAME`,
`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`

### OAuth Config (`oauth_config`)

`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`,
`GITHUB_CLIENT_SECRET`, `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`,
`JIRA_CLIENT_ID`, `JIRA_CLIENT_SECRET`, `BING_CLIENT_ID`, `BING_CLIENT_SECRET`,
`MICROSOFT_SSO_CLIENT_ID`, `MICROSOFT_SSO_CLIENT_SECRET`, `MICROSOFT_SSO_TENANT_ID`

### Cloudflare Config (`cloudflare_config`)

`CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`,
`CLOUDFLARE_CUSTOM_ORIGIN_SERVER`, `CUSTOM_DOMAIN_AUTO_ACTIVATE_ON_VERIFY`

### Support Info (`support_info`)

`SUPPORT_EMAIL`, `BILLING_EMAIL`, `PRIVACY_EMAIL`,
`CONTACT_INBOX_ADDRESS`, `CONTACT_TICKET_PREFIX`

## Admin UI Surfaces

| Page                           | Path                  | Purpose                                     |
|--------------------------------|-----------------------|---------------------------------------------|
| Runtime Configuration          | `/admin/config`       | View/edit all runtime-configurable settings |
| Integration & Security Health  | `/admin/settings/configuration` | Integration status, credential inventory, security checks |
| AI Models                      | `/admin/settings/ai-models` | Quick AI model routing controls         |

## Implementation Files

| Component              | File                                           |
|------------------------|-------------------------------------------------|
| Config registry        | `backend/services/configuration_service.py`    |
| Compatibility layer    | `backend/core/runtime_config.py`               |
| Admin API endpoints    | `backend/admin.py` (config section)            |
| DB model               | `backend/models.py` (`OperationalSetting`)     |
| Frontend runtime page  | `frontend/src/app/(app)/admin/config/page.tsx` |
| Frontend health page   | `frontend/src/app/(app)/admin/settings/configuration/page.tsx` |
