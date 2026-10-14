<p align="center">
  <a href="https://qiko.ai/signal">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset=".github/logo_dark.png">
      <img src=".github/logo.png" width="400" alt="Qiko Signal">
    </picture>
  </a>
</p>

<h3 align="center">AI Search Intelligence Platform</h3>

<p align="center">
  <a href="https://qiko.ai/signal">qiko.ai/signal</a>
</p>

---

> **Qiko Signal** is an enterprise AI search intelligence platform that audits, monitors, and optimizes how websites and brands appear across AI-powered search engines. It combines multi-provider AI analysis (Google Gemini, OpenAI, Anthropic, xAI/Grok, DeepSeek) with structured debate orchestration, claim grounding, and a proprietary signal warehouse to deliver actionable SEO, GEO, and AEO recommendations — then tracks the impact over time.

Qiko Signal is not a tool — it is a platform that agencies, SEO teams, and enterprises use to understand and improve their AI search visibility at scale.

## Table of Contents

- [Platform Capabilities](#platform-capabilities)
- [Architecture Overview](#architecture-overview)
- [Tech Stack](#tech-stack)
- [Codebase at a Glance](#codebase-at-a-glance)
- [Project Structure](#project-structure)
- [Plans & Pricing](#plans--pricing)
- [Product Features](#product-features)
  - [Core Audit Engine](#core-audit-engine)
  - [Project Management](#project-management)
  - [Monitoring & Analytics](#monitoring--analytics)
  - [Reports & Delivery](#reports--delivery)
  - [AI Content & Strategy](#ai-content--strategy)
  - [Integrations](#integrations)
  - [Billing & Commerce](#billing--commerce)
  - [Developer Platform (Headless API)](#developer-platform-headless-api)
  - [White-Label & Agency](#white-label--agency)
  - [Security & Compliance](#security--compliance)
  - [Marketing & CMS](#marketing--cms)
- [Requirements](#requirements)
- [Quick Start (Docker)](#quick-start-docker)
- [Installation (No Docker)](#installation-no-docker)
- [Configuration](#configuration)
  - [How Config Is Loaded](#how-config-is-loaded)
  - [Environment Templates](#environment-templates)
  - [Environment Variables Reference](#environment-variables-reference)
- [Running Locally](#running-locally)
- [Docker](#docker)
- [Database, Migrations, Seeds](#database-migrations-seeds)
- [Workers](#workers)
- [Testing](#testing)
- [Linting & Static Analysis](#linting--static-analysis)
- [API Documentation](#api-documentation)
- [Deployment](#deployment)
- [CI/CD](#cicd)
- [Operational Scripts](#operational-scripts)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [Documentation Index](#documentation-index)
- [Contributing](#contributing)
- [License](#license)

---

## Platform Capabilities

| Capability | Description |
| --- | --- |
| **AI Search Auditing** | Deep SEO + GEO + AEO analysis across Google, OpenAI, Anthropic, xAI/Grok, and DeepSeek models with multi-agent debate orchestration and claim grounding |
| **Visibility Monitoring** | Track AI citation status, visibility scores, and provider-level mention trends over time with automated alerting |
| **Competitive Intelligence** | Compare your AI search presence against competitors with semantic gap analysis and citation benchmarking |
| **Entity Authority** | Score and track how well your entities are represented in AI knowledge systems, with gap detection and graph visualization |
| **ROI Simulation** | Predictive traffic and revenue modeling based on GEO score improvements, powered by GSC snapshot data |
| **AI Bot Log Analysis** | Ingest and analyze server logs to understand AI crawler behavior, detect spoofing, and surface crawl waste |
| **Content Strategy** | CMS fix delivery (WordPress/Shopify) and structured recommendation workflows |
| **Report Delivery** | White-labeled PDF reports, multi-language localization, scheduled monthly progress reports, and annotation threads |
| **Agency White-Label** | Custom domains, branded portals, workspace branding, client management, and lead capture widgets |
| **Developer API** | Headless audit API with signed webhooks, bulk orchestration, BI connectors (Looker Studio, Google Sheets), and CSV exports |
| **Enterprise Billing** | Five-tier plan architecture with credit-based pricing, top-ups, tiered commitments, and Stripe-integrated checkout |

---

## Architecture Overview

```
                    ┌─────────────────────────────────────────────────┐
                    │               Caddy (TLS + Routing)             │
                    │   *.qiko.ai + custom domains (on-demand) │
                    └──────────────┬────────────────┬─────────────────┘
                                   │                │
                          /api/v1/*│                │ /*
                                   ▼                ▼
                    ┌──────────────────┐  ┌──────────────────┐
                    │  FastAPI Backend  │  │  Next.js Frontend │
                    │    :8000 (API)    │  │  :3000 (BFF+SSR)  │
                    └──────┬───────────┘  └──────────────────┘
                           │
              ┌────────────┼───────────────────┐
              ▼            ▼                   ▼
     ┌──────────────┐ ┌───────────┐   ┌──────────────┐
     │  PostgreSQL   │ │   Redis   │   │  AI Service   │
     │   18 (data)   │ │ 8 (queue) │   │  :8001 (LLM)  │
     └──────────────┘ └─────┬─────┘   └──────────────┘
                            │
        ┌───────────────────┼───────────────────────┐
        ▼                   ▼                       ▼
  ┌───────────┐   ┌──────────────────┐   ┌────────────────┐
  │  Audit    │   │  Email / PDF /   │   │  Monitoring /  │
  │  Worker   │   │  Billing Workers │   │  Cron Sweeper  │
  └───────────┘   └──────────────────┘   └────────────────┘
```

| Layer | Components |
| --- | --- |
| **Edge** | Caddy reverse proxy with automatic TLS (Let's Encrypt) and on-demand custom-domain certificates |
| **Frontend** | Next.js 16.3.6 App Router, BFF proxy to backend, nonce-based CSP, server-side rendering |
| **Backend API** | FastAPI with 30 routers, JWT + OAuth + MFA auth, plan-gated feature access, Prometheus metrics |
| **AI Service** | Standalone AI provider microservice (:8001) — Gemini, OpenAI, Anthropic, xAI/Grok, DeepSeek with health/quota fallback |
| **Database** | PostgreSQL 18 with 109 SQLAlchemy models and 113 Alembic migrations |
| **Queue** | Redis 8 for job queues (`audit_jobs`, `pdf_jobs`, `billing:webhook_events`, `visibility_index_jobs`) and semantic cache |
| **Workers** | 10 background workers — audit execution, PDF generation, email delivery, billing webhooks, visibility indexing, performance sync, monitoring, metrics snapshots, external webhooks, cron sweeper |
| **Secrets** | AWS SSM Parameter Store (SecureString) loaded via EC2 instance role, plus Fernet-encrypted DB columns |

---

## Tech Stack

| Layer | Technologies |
| --- | --- |
| **Frontend** | Next.js 16.3.6, React 18, TypeScript 5.9, Tailwind CSS 4 |
| **Frontend libs** | TanStack React Query 5, React Hook Form + Zod, Recharts, Framer Motion, i18next, jose, Lucide icons |
| **Backend** | Python 3.11, FastAPI 0.110, Pydantic 2.7, SQLAlchemy 2.0, Alembic 1.13, Authlib, httpx |
| **Database** | PostgreSQL 18 |
| **Queue / Cache** | Redis 8 |
| **AI providers** | Google Gemini (`google-genai` 0.5), OpenAI 1.35, Anthropic 0.30, xAI/Grok, DeepSeek |
| **Scraping / SEO** | Firecrawl (`firecrawl-py` 4.14), Google PageSpeed Insights API |
| **Auth** | PyJWT, passlib (Argon2), pyotp (MFA/TOTP), Authlib (OAuth), FIDO2 (passkeys) |
| **Payments** | Stripe 10.12 (USD) |
| **PDF** | WeasyPrint 62.3, Jinja2, inline SVG charts, ReportLab 4.2 |
| **Email** | Queued HTML outbox with SMTP (Gmail); 40 templates |
| **Observability** | Prometheus (`prometheus-client` 0.20), Sentry (`sentry-sdk` 2.19) |
| **Secrets** | AWS SSM Parameter Store (`boto3`) |
| **Testing** | pytest 9 + pytest-asyncio (backend), Vitest 4.1 (frontend), Playwright 1.58 (E2E) |
| **Linting** | Ruff 0.6 (backend), ESLint 8 + Prettier 3.6 (frontend) |
| **Deployment** | Docker, Docker Compose, Caddy 2.8, GitHub Actions, GHCR, Sigstore Cosign |

---

## Codebase at a Glance

| Metric | Count |
| --- | --- |
| Python source lines | ~430K across 552 files |
| TypeScript/TSX source lines | ~146K across 642 files |
| SQLAlchemy models | 109 |
| Alembic migrations | 113 |
| Backend services | 118 |
| Backend routers | 30 |
| Background workers | 10 |
| Frontend pages | 83 |
| Frontend components | 262 |
| Frontend hooks | 22 |
| Email templates | 40 |
| Backend tests | 338 test files, 3,424 tests |
| Frontend unit tests | 214 test files |
| Frontend E2E specs | 29 (Playwright) |
| i18n languages | 2 (English, Arabic) |
| Documentation files | 18 in `docs/` |
| Docker Compose services | 15 |

---

## Project Structure

```
qiko-signal/
├── backend/
│   ├── main.py                     # FastAPI app entrypoint
│   ├── ai_service.py               # Standalone AI orchestration service (:8001)
│   ├── audit_runner.py             # Core audit execution logic
│   ├── models.py                   # 109 SQLAlchemy ORM models
│   ├── database.py                 # DB session factory
│   ├── report_schema.py            # Canonical report Pydantic schemas
│   ├── admin.py                    # Admin router (~9,700 lines)
│   ├── queue_worker.py             # Audit job worker (Redis BRPOP)
│   ├── pdf_worker.py               # PDF report generation worker
│   ├── email_outbox_worker.py      # Queued email delivery worker
│   ├── billing_webhook_worker.py   # Stripe webhook processor
│   ├── external_webhook_worker.py  # Outbound webhook delivery
│   ├── visibility_index_worker.py  # Visibility index calculations
│   ├── performance_sync_worker.py  # Daily performance data sync
│   ├── monitoring_worker.py        # Monitoring pipeline worker
│   ├── metrics_snapshot_worker.py  # Metrics snapshot aggregation
│   ├── cron_sweeper.py             # Stale job cleanup + scheduled tasks
│   ├── core/
│   │   ├── config.py               # Pydantic settings (~150+ env vars)
│   │   ├── env_bootstrap.py        # Env loading + AWS SSM secret overlay
│   │   ├── redis_client.py         # Centralized Redis factory (auth/TLS)
│   │   ├── runtime_migrations.py   # Auto Alembic on startup
│   │   └── encrypted_types.py      # Fernet-encrypted DB columns
│   ├── auth/
│   │   ├── token_verifier.py       # JWT verification
│   │   ├── credits.py              # Credit system (calculate, decrement, verify)
│   │   ├── mfa.py                  # TOTP-based MFA
│   │   └── security.py             # Auth re-exports
│   ├── routers/                    # 30 API router modules
│   │   ├── api_router.py           # Core audit/user/entity endpoints (~7,250 lines)
│   │   ├── auth.py                 # Login, register, OAuth, MFA, tokens
│   │   ├── workspace_router.py     # Workspaces, projects, data sources (~7,270 lines)
│   │   ├── portal_router.py        # Client portal endpoints
│   │   ├── external_api_router.py  # Headless API (audit, export, webhooks)
│   │   ├── scheduling_router.py    # Scheduled audit management
│   │   ├── monitoring_router.py    # Visibility + bot log + mentions
│   │   ├── entity_authority_router.py
│   │   ├── workflow_router.py      # Automation rules
│   │   ├── alert_rules_router.py   # Alert rule management
│   │   ├── jira_router.py          # Jira integration
│   │   ├── slack_router.py         # Slack OAuth + messaging
│   │   ├── teams_router.py         # Teams webhook integration
│   │   ├── cms_router.py           # CMS content management
│   │   ├── content_router.py       # Public CMS articles
│   │   ├── contact_router.py       # Contact form
│   │   └── ...                     # + 12 more routers
│   ├── services/                   # 118 business logic modules
│   │   ├── ai_engine.py            # Multi-provider AI dispatch (~3,300 lines)
│   │   ├── debate_orchestrator.py  # V3 multi-agent debate (~3,800 lines)
│   │   ├── claim_taxonomy_service.py
│   │   ├── claim_evaluation_service.py
│   │   ├── unified_truth_context_service.py
│   │   ├── signal_warehouse_service.py
│   │   ├── project_visibility_service.py
│   │   ├── project_bot_log_analyzer_service.py
│   │   ├── entity_authority_service.py
│   │   ├── billing_calculator.py
│   │   ├── credit_commitment_service.py
│   │   ├── custom_domain_service.py
│   │   ├── email_service.py
│   │   ├── workflow_engine.py
│   │   ├── notification_router.py
│   │   ├── export_service.py
│   │   ├── pdf_reports/            # 10 PDF report modules
│   │   ├── cms_adapters/           # WordPress + Shopify adapters
│   │   ├── competitors/            # Competitive analysis modules
│   │   └── ...
│   ├── billing/                    # Stripe checkout/portal/webhook router
│   ├── schemas/                    # Pydantic request/response models
│   ├── middleware/                  # Rate limiter, security headers, tenant resolver
│   ├── alembic/versions/           # 113 migration files
│   ├── templates/                  # 40 email + report HTML templates
│   ├── scripts/                    # Startup, backfill, maintenance
│   ├── tests/                      # 338 pytest test files
│   ├── i18n/                       # Report localization JSONs
│   ├── app/config/plans.py         # Plan definitions + capability matrix
│   ├── Dockerfile
│   ├── Makefile                    # lint, format, format:check
│   ├── requirements.txt
│   └── constraints.txt             # pip-compile lock
├── frontend/
│   ├── src/
│   │   ├── app/                    # 83 Next.js App Router pages
│   │   │   ├── (auth)/             # Login, register, password flows
│   │   │   ├── (public)/           # Landing, pricing, blog, docs, etc.
│   │   │   ├── (app)/admin/        # 35 admin pages
│   │   │   ├── (app)/dashboard/    # 32 dashboard + project pages
│   │   │   ├── (portal)/           # Client portal pages
│   │   │   └── api/                # BFF proxy routes
│   │   ├── components/             # 262 React components
│   │   │   ├── ui/                 # Shared primitives (Button, Card, Modal, etc.)
│   │   │   ├── dashboard/          # Dashboard feature components
│   │   │   ├── admin/              # Admin panel components
│   │   │   ├── results/            # Audit result/report display
│   │   │   ├── billing/            # Credit top-up, commitment selectors
│   │   │   ├── portal/             # Client portal components
│   │   │   ├── settings/           # Settings components
│   │   │   └── marketing/          # Landing page components
│   │   ├── services/               # API service layer (http.ts, auth.service.ts)
│   │   ├── hooks/                  # 22 custom React hooks
│   │   ├── contexts/               # AuthContext, CookieConsentContext
│   │   ├── i18n/                   # en.json, ar.json translations
│   │   ├── types/                  # TypeScript type definitions
│   │   ├── lib/                    # Utilities (dateFormat, etc.)
│   │   └── middleware.ts           # Edge JWT verification (jose)
│   ├── e2e/                        # Playwright E2E tests
│   ├── Dockerfile
│   ├── package.json
│   ├── tailwind.config.ts
│   └── vitest.config.ts
├── deploy/
│   ├── Caddyfile                   # Reverse proxy + TLS + custom domain gate
│   ├── .env.vps.example            # VPS env template
│   └── VPS_DEPLOYMENT_RO.md        # VPS deployment guide
├── scripts/                        # Dev-setup, deploy, smoke tests
├── contracts/                      # Canonical audit payload schema
├── connectors/                     # BI connector source (Looker Studio, Sheets)
├── reports/templates/              # HTML report templates
├── docs/                           # 18 documentation files
├── planning/                       # Epics, tasks, bugs
├── docker-compose.yml              # Local development (15 services)
├── docker-compose.vps.yml          # VPS production stack + Caddy
├── deploy.sh                       # VPS deployment (delegates to scripts/deploy-production.sh)
├── ARCHITECTURE.md                 # In-depth technical architecture
└── CHANGELOG.md                    # Release notes
```

---

## Plans & Pricing

All pricing is in USD. Credits are the universal unit of consumption.

| Plan | Monthly Price | Credits/Month | Key Capabilities |
| --- | ---: | ---: | --- |
| **Starter** | Free | 1 scan/mo | Full SEO + GEO + AEO audit, PDF report, 1 site (1 scan per month) |
| **Standard** | $99 | 100 | Full audit access, PDF reports, email delivery, scheduled audits |
| **Specialist** | $399 | 500 | + Competitor analysis, semantic gap, Jira/Slack/Teams, commitments |
| **Executive** | $999 | 2,000 | + White-label, PDF branding, custom domains, workflow automations, API access |

Credit costs vary by provider (`google=1x`, `anthropic=1.5x`, `openai=2x`) and tier (`lite=0.5x`, `fast=1x`, `smart=3x`). Base credit value: $0.10.

---

## Product Features

### Core Audit Engine

- **Three audit domains** — SEO (technical + on-page), GEO (generative engine optimization), AEO (answer engine optimization) — all plan-gated.
- **Two audit tiers** — `Fast` (single-pass lightweight) and `Deep` / `deep_judgment` (multi-agent debate with prescriptive recommendations).
- **Website + Brand modes** — URL-based website audits and entity-only brand audits (no URL required) with full pipeline support.
- **Multi-provider AI** — Google Gemini (Flash/Pro), OpenAI (GPT-5 Nano/GPT-5), Anthropic (Sonnet/Opus), xAI/Grok, DeepSeek with runtime health/quota fallback.
- **Orchestra V3 debate** — FAST 3-agent, SMART 5-agent, and Delta Flow 8-agent parallel debate pipelines with claim ledgers, per-agent cost traces, and quality-gate heuristics.
- **Dual-track claim grounding** — Track A (descriptive) + Track B (prescriptive) claim taxonomy, `Unified Truth Context` assembly, integrity certificates, and `needs_manual_review` disposition.
- **Dynamic cost forecasting** — Pre-audit endpoint returns projected credits, USD cost, confidence, and consensus-run breakdown before credit acquisition.
- **Scheduled audits** — Cron-based recurring dispatch with target identity normalization and budget-pause on cap exhaustion.
- **Parallel execution** - Up to 10 concurrent audits (Executive) with plan-gated limits.
- **Sitemap batch crawl** — Parse index/nested/gzip sitemaps (up to 500 URLs), fan-out into audit queue, aggregate site-health reports.
- **Audit caching** — Redis semantic cache with configurable TTL per tier and `cache_behavior=bypass` for forced re-execution.
- **Prompt quality gate** — Deterministic V3 post-debate checks: grounding-rate, domain-boundary violations, anchor contradictions, consolidator dedup, magistrate flagging.

### Project Management

- **Workspace → Project hierarchy** — Multi-site workspace container with project-scoped audits, data sources, budgets, and team access.
- **Project tasks** — Task creation from audit recommendations, with Kanban lifecycle (`todo` → `in_progress` → `done`) and Jira export.
- **Workflow automations** — Project-level trigger/action/threshold rules reacting to `audit.completed`, `alert.triggered`, `report.generated`, and more.
- **Budget guardrails** — Per-project monthly credit caps, 80%/100% threshold alerts, and scheduled-audit pause on budget exhaustion.
- **Onboarding wizard** — Server-backed Getting Started checklist with email verification nudge.
- **RBAC** — Admin, Editor, Viewer, Client Readonly roles enforced at the API level.

### Monitoring & Analytics

- **AI visibility monitoring** — Track queries per provider, citation status, aggregated visibility score, trend history, and drop alerting.
- **Bot log analyzer** — Server-log ingestion (upload, Cloudflare Logpush, AWS S3, GCP), reverse-DNS spoofing detection, section heatmap, crawl waste diagnostics.
- **Off-page AEO mentions** — Mention ingestion with domain authority weighting, batch sentiment/entity analysis, trend aggregates, and drop alerting.
- **AI Search Volatility Index** — Global daily provider/industry snapshots with weather-style gauge, cosine similarity, citation Jaccard/churn, format change rate, and a public `/volatility` page.
- **Entity Authority** — Weighted coverage/depth/consistency/uniqueness scoring, gap detection, trend snapshots, knowledge graph visualization.
- **Historical trends** — Project score timelines (daily/weekly/monthly), workspace sparklines, period deltas, comparison endpoints.
- **Signal Warehouse** — Idempotent audit/visibility ingestion, anonymized cohort percentiles (`k>=10`), citation stability, remediation impact, provider cost-efficiency benchmarks.
- **Alert rules** — Configurable metric thresholds with notification routing through email, Slack, and Teams.

### Reports & Delivery

- **PDF reports** — WeasyPrint-based with SVG charts, dynamic branding, AI executive summaries, and canonical-schema section assembly.
- **Multi-language delivery** — Localized PDFs and emails with CJK-aware rendering (Japanese, Chinese); project-language defaults with one-off overrides.
- **Report annotations** — Audit-scoped recommendation threads with internal/client visibility control, inline badges, portal replies, and email notifications.
- **Monthly progress reports** — Automated 1st-of-month snapshots for scheduled-audit projects, branded email delivery, immutable archive.
- **Claim review queue** — Agency-side review for Track B `needs_manual_review` claims with approve/refuse disposition and signal warehouse propagation.
- **CSV/JSON exports** — Project score CSV, bulk pulls, raw JSON downloads, and connector-ready export service.

### AI Content & Strategy

- **CMS fix delivery** — Push approved fixes to WordPress and Shopify with preview/diff, signed confirmation, deployment logs, and rollback.
- **Strategic insights** — Executive summaries, roadmap items, AEO query ideas, GEO prompt ideas derived from audits + signal warehouse evidence.
- **Semantic gap mapping** — Competitor-vs-client gap analysis surfaced in competitive dashboards and AI briefs (Specialist+).
- **Entity extraction** — Entity graph mapping, semantic relationships, and entity enhancement services.
- **Debate trace inspection** — Encrypted per-agent prompt/output payloads, claim-ledger snapshots, cost metadata — inspectable in admin UI.

### Integrations

- **Jira** — Export audit recommendations as Jira issues with read-only task visibility in the client portal.
- **Slack** — OAuth workspace connection, default channel routing, project-scoped notification delivery and automation triggers.
- **Microsoft Teams** — Incoming webhook connection, workspace-scoped message delivery, and workflow automation actions.
- **Google Search Console** — OAuth Magic Link handshake, GSC traffic snapshot sync for ROI simulator and performance monitoring.
- **Google Analytics 4** — OAuth data connection via Magic Link handshake for performance sync.
- **Bing Webmaster** — OAuth data connection for search performance data.
- **Looker Studio connector** — Apps Script-based connector reading Qiko Signal CSV export endpoints for custom dashboards.
- **Google Sheets add-on** — Apps Script sidebar for importing project scores and audit data into spreadsheets.
- **Notification router** — Centralized event fan-out to email + Slack + Teams, respecting plan entitlements and workspace channel config.

### Billing & Commerce

- **Four-tier plans** - Starter through Executive with capability-gated feature access.
- **Credit system** — Provider/tier multipliers, atomic decrement/increment, pre-audit credit hold with TTL, cron-based stale hold expiration.
- **Dynamic top-ups** — One-time 100–2,000 credit purchases at $0.10/credit via Stripe Checkout with email confirmation.
- **Tiered commitments** — Monthly Growth/Scale/Enterprise commitment tiers (Specialist+) with fixed fee + metered overage and 80% utilization warnings.
- **Pricing Policy v2** — Versioned policy objects (provider/tier multipliers, floor/cap bounds, infra allocations), shadow-mode comparison, AI economics ledger.
- **Stripe integration** — Plan subscriptions, self-serve upgrades, customer portal, invoices, and webhook-driven fulfillment.
- **Admin Stripe catalog sync** — Test/live catalog management from `/admin/settings/payments` without implicitly flipping active mode.
- **Enterprise sales intake** — Structured company/volume modal generating pre-filled contact emails for custom pricing.

### Developer Platform (Headless API)

- **Headless audit API** — Customer-managed `stx_live_*` keys, `/api/v1/external/*` endpoints for single + bulk audit orchestration, per-key rate limits, idempotency.
- **Signed webhooks** — `X-Qiko Signal-Signature` on outbound payloads with retry delivery via dedicated external webhook worker.
- **Developer Hub** — `/dashboard/developer` with endpoint contracts, CSV connector setup, rate limits, webhook verification, and starter code samples.
- **API key management** — Create, rotate, revoke keys from `/dashboard/settings`; keys carry workspace + plan scope.
- **Embed keys** — Scoped `stx_embed_*` keys with per-key `allowed_origins` and daily quotas for lead widget integration.
- **BI connector endpoints** — CSV export and query endpoints consumed by Looker Studio and Google Sheets connectors.

### White-Label & Agency

- **Custom domains** — Workspace-owned CNAME domains with DNS verification, Cloudflare for SaaS custom hostname activation, and Caddy on-demand TLS fallback.
- **Workspace branding** — Brand name, logo, colors, favicon, page title, meta description, powered-by toggle, email sender metadata, social/legal footer links.
- **Client portal** — Dedicated `/portal` with assigned-project isolation, read-only dashboards, Jira task visibility, annotation replies, and magic-link onboarding.
- **PDF white-labeling** — Dynamic branding injection into report templates (Executive+).
- **Tenant-aware login** — Custom-domain host resolution to workspace, branded login/register/portal pages.
- **Email branding chain** — Platform defaults from admin settings, then workspace white-label overrides.
- **Lead capture widget** — Embeddable `widget.js` for third-party sites with origin validation; agencies monitor captured leads from `/dashboard/leads`.

### Security & Compliance

- **Authentication** — Custom JWT (HS256) with access/refresh tokens in httpOnly cookies via BFF proxy. Separate signing keys, configurable TTL.
- **MFA** — TOTP-based enrollment and verification via `pyotp`.
- **Passkeys** — FIDO2 WebAuthn registration and authentication.
- **OAuth SSO** — Google, GitHub, Microsoft, LinkedIn providers with callback recovery flows.
- **Password security** — Argon2 hashing via `passlib`, live strength feedback, configurable policy.
- **Session isolation** — Dedicated `SESSION_SECRET_KEY` with fail-fast validation; cross-tab logout via `StorageEvent`.
- **Security headers** — Three-layer defense: Caddy (HSTS/COOP), backend middleware (API CSP `default-src 'none'`), frontend (nonce-based CSP, report-only rollout).
- **SSRF protection** — `safe_async_fetch()`/`safe_sync_fetch()` with private IP blocking, DNS-rebinding guards, redirect revalidation, 10 MB response ceiling.
- **Container hardening** — `cap_drop: [ALL]`, `read_only: true`, `no-new-privileges`, `proxy-net`/`app-net` network segmentation.
- **CI security gates** — Gitleaks secret scanning, pip-audit CVE audit, Trivy filesystem/container scanning, Hadolint Dockerfile linting.
- **Encrypted columns** — Fernet encryption for sensitive DB fields (OAuth tokens, CMS credentials, debate traces).
- **Rate limiting** — In-memory per-IP+path + Redis-based per-endpoint limits.
- **Data retention** — Screenshots redacted after 30 days, audit records purged after 90 days unless flagged.
- **GDPR** — Cookie consent, GDPR-compliant unsubscribe, transactional email bypass, privacy inbox routing.

### Marketing & CMS

- **CMS content system** — Articles and case studies with AI-assisted generation, managed via admin CMS router.
- **Public guest audit** — Unauthenticated website or brand audit with rate-limited access.
- **Public volatility page** — Desktop-first AI Search Volatility dashboard at `/volatility` with gauge, sector heatmap, citation ledger, and alert preview.
- **Landing pages** — Marketing pages for landing, pricing, about, FAQ, blog, case studies, docs, sample reports.
- **Contact/sales intake** — Contact form submission and enterprise sales flow.
- **Embeddable lead widget** — Agency-operated `widget.js` for third-party sites.

---

## Requirements

### Option A: Docker-first (recommended)

- Docker Engine 20.10+ with Docker Compose plugin (v2).

### Option B: Local processes

- Python 3.11
- Node.js 24 LTS + npm
- PostgreSQL 18
- Redis 8

---

## Quick Start (Docker)

```bash
# 1. Bootstrap local dev environment (interactive — generates secrets, copies env files, starts Docker)
./scripts/setup-development.sh

# Or use the legacy non-interactive version:
# ./scripts/dev-setup.sh

# 2. If the AWS SSM secrets do not exist yet, ask a platform admin to create them
#    (secrets are provisioned in AWS SSM Parameter Store under /qiko-signal/).

# 3. Start infrastructure
docker compose up -d db redis

# 4. Start backend services (with hot-reload)
docker compose up -d backend ai-service audit-worker email-worker

# 5. (Optional) Start additional workers
docker compose up -d pdf-worker external-webhook-worker monitoring-worker visibility-worker performance-worker cron-sweeper

# 6. Start frontend with hot-reload (HMR)
docker compose --profile frontend-dev up -d frontend-dev
```

Endpoints after startup:

| Service | URL |
| --- | --- |
| Frontend (HMR) | `http://localhost:3000` |
| Backend Swagger UI | `http://localhost:8000/docs` |
| Backend OpenAPI JSON | `http://localhost:8000/openapi.json` |
| AI service health | `http://localhost:8001/health` |

> **Hot-reload**: Backend and AI service auto-reload on Python file changes (`--reload`). Frontend uses Next.js HMR. WSL2 file-watching is enabled via `WATCHPACK_POLLING=true`.

> **Note**: Local and production environments both use the real JWT/OAuth authentication flows.

> **PostgreSQL 18 note**: The official image expects the volume at `/var/lib/postgresql`, not `/var/lib/postgresql/data`. If your local `postgres_data` volume was created by an older compose config, reset it with `docker compose down -v` before restarting. For VPS/production data, perform a dump/restore or `pg_upgrade` instead.

---

## Installation (No Docker)

### 1) Clone

```bash
git clone <repo-url>
cd qiko-signal
```

### 2) Backend setup

```bash
cd backend
python3.11 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt -c constraints.txt
cp ../.env.development.example ../.env.development
cp .env.development.example .env.development
alembic upgrade head
```

Update `.env.development` host values for local processes:
- `DATABASE_URL` → `postgresql://user:password@localhost:5432/dbname`
- `REDIS_URL` → `redis://localhost:6379`
- `AI_SERVICE_URL` → `http://localhost:8001`

Start services in separate terminals:

```bash
# API server
uvicorn main:app --host 0.0.0.0 --port 8000 --log-level error --no-access-log

# Audit worker
python queue_worker.py

# AI service
uvicorn ai_service:app --host 0.0.0.0 --port 8001 --log-level error --no-access-log
```

### 3) Frontend setup

```bash
cd frontend
npm ci
cp .env.development.example .env.local
npm run dev
```

### 4) Stripe local webhooks

```bash
./scripts/dev-stripe-listen.sh
```

Copy the signing secret from Stripe CLI into `STRIPE_WEBHOOK_SECRET_TEST` in your local env.

---

## Configuration

### How Config Is Loaded

**Backend** (`backend/core/env_bootstrap.py` + `backend/core/config.py`):

1. Load backend/root dotenv files for bootstrap defaults.
2. Overlay bootstrap secrets from AWS SSM Parameter Store (`SSM_ENABLED=true`, default on).
3. Pydantic `Settings` validates the env/SSM layer and exposes typed values.
4. `services.configuration_service` overlays DB-managed keys from `OperationalSetting.admin_settings_payload`.
5. If the DB payload is empty, DB-managed keys are seeded automatically from env/SSM on first boot.

**Compose runtime**:
- Backend services load `ROOT_ENV_FILE` first, then `BACKEND_ENV_FILE` as optional overlay.
- Frontend service uses root env file (`ROOT_ENV_FILE`, default `./.env`).

**Frontend runtime**:
- Standard Next.js envs (`frontend/.env*`) when run directly via `npm`.
- In compose, environment is injected from root env + compose `environment` block.
- Edge middleware reads `JWT_SECRET` to verify tokens via `jose`.

### Environment Templates

| Template | Scope |
| --- | --- |
| `.env.example` | Canonical production bootstrap vars |
| `.env.development.example` | Canonical local bootstrap vars |
| `backend/.env.example` | Minimal backend-only overlay |
| `backend/.env.development.example` | Minimal backend-only dev overlay |
| `frontend/.env.example` | Frontend production template |
| `frontend/.env.development.example` | Frontend local dev template |

DB-managed settings should be edited from admin surfaces and served from Postgres at runtime. Keep those values in SSM only as bootstrap/reseed material.

### Environment Variables Reference

<details>
<summary><strong>Core infrastructure</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `DATABASE_URL` | Yes (backend) | `postgresql://user:password@db:5432/dbname` | SQLAlchemy/Alembic DB connection string |
| `REDIS_URL` | Yes (backend/worker) | `redis://redis:6379` | Queue + cache + metrics store |
| `AI_SERVICE_URL` | Yes (backend/worker) | `http://ai-service:8001` | Backend-to-AI-service URL |
| `BACKEND_URL` | Yes (frontend) | `http://backend:8000` | Next.js BFF proxy upstream |
| `FRONTEND_URL` | Yes (prod) | `http://localhost:3000` | Backend URL generation for redirects/emails |
| `APP_BASE_URL` | Yes (prod) | `http://localhost:3000` | Billing links + frontend URL fallback |
| `BACKEND_PUBLIC_URL` | Recommended (prod) | _(empty)_ | Public backend base for OAuth callbacks and external API docs |
| `CORS_ORIGINS` | Yes (prod) | `http://localhost:3000` | Comma-separated CORS allowlist (credentialed, all endpoints) |
| `PUBLIC_SITE_ORIGINS` | Optional | _(empty)_ | Marketing-site origins allowed to read the public plan catalog cross-origin (no credentials). Preprod only; live is same-origin |
| `RATE_LIMIT_PLANS_PUBLIC` | Optional | `60/min` | Per-IP rate limit for the public plan catalog endpoint |
| `APP_ENV` | Optional | `development` | Runtime environment switch |
| `DOMAIN` | Required (VPS) | _(empty)_ | Caddy host for TLS/proxy routing |
| `CUSTOM_DOMAIN_CNAME_TARGET` | Optional | `custom.qiko.ai` | DNS target for agency custom-domain CNAME records |
| `CLOUDFLARE_API_TOKEN` | Optional | _(empty)_ | Enables Cloudflare for SaaS custom hostname creation |
| `CLOUDFLARE_ZONE_ID` | Optional | _(empty)_ | Cloudflare zone ID for custom hostname API |

</details>

<details>
<summary><strong>Authentication</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `JWT_SECRET_KEY` | Yes (prod) | _(empty)_ | Access/email/password token signing secret |
| `JWT_REFRESH_SECRET_KEY` | Yes (prod) | _(empty)_ | Refresh token signing secret |
| `JWT_SECRET` | Recommended | _(empty)_ | Frontend middleware JWT verification secret |
| `JWT_ALGORITHM` | Optional | `HS256` | JWT algorithm |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Optional | `30` | Access token TTL |
| `REFRESH_TOKEN_EXPIRE_DAYS` | Optional | `7` | Refresh token TTL |
| `EMAIL_TOKEN_EXPIRE_HOURS` | Optional | `48` | Email verification token TTL |
| `PASSWORD_RESET_TOKEN_EXPIRE_HOURS` | Optional | `24` | Password reset token TTL |
| `ADMIN_EMAILS` | Optional | _(empty)_ | Comma-separated admin auto-promotion allowlist |

</details>

<details>
<summary><strong>OAuth providers</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GOOGLE_CLIENT_ID` | Optional | _(empty)_ | Google OAuth login + workspace connection |
| `GOOGLE_CLIENT_SECRET` | Optional | _(empty)_ | Google OAuth secret |
| `GITHUB_CLIENT_ID` | Optional | _(empty)_ | GitHub OAuth login |
| `GITHUB_CLIENT_SECRET` | Optional | _(empty)_ | GitHub OAuth secret |
| `BING_CLIENT_ID` | Optional | _(empty)_ | Microsoft Entra ID client for Bing Webmaster |
| `BING_CLIENT_SECRET` | Optional | _(empty)_ | Microsoft Entra ID secret for Bing Webmaster |
| `BING_WEBMASTER_API_KEY` | Optional | _(empty)_ | Bing Webmaster API for automated site provisioning |
| `BING_TENANT_ID` | Optional | `common` | Microsoft tenant for OpenID metadata |
| `BING_OAUTH_SCOPE` | Optional | `openid profile email offline_access` | Microsoft/Azure SSO scopes |
| `MICROSOFT_SSO_CLIENT_ID` | Optional | _(empty)_ | Dedicated Microsoft SSO app registration (falls back to `BING_CLIENT_ID`) |
| `MICROSOFT_SSO_CLIENT_SECRET` | Optional | _(empty)_ | Dedicated Microsoft SSO secret (falls back to `BING_CLIENT_SECRET`) |
| `MICROSOFT_SSO_TENANT_ID` | Optional | `common` | Microsoft SSO tenant (falls back to `BING_TENANT_ID`) |
| `OAUTH_TOKEN_ENCRYPTION_KEY` | Recommended (prod) | JWT secret fallback | Fernet key for encrypted OAuth token storage |

For Microsoft SSO, register `/api/v1/auth/microsoft/callback` on the Entra app. Bing Webmaster automation uses `BING_WEBMASTER_API_KEY`; otherwise falls back to manual verification.

</details>

<details>
<summary><strong>AI providers and models</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `GEMINI_API_KEY` | Required for Gemini | _(empty)_ | Primary Gemini key |
| `OPENAI_API_KEY` | Optional | _(empty)_ | OpenAI provider key |
| `ANTHROPIC_API_KEY` | Optional | _(empty)_ | Anthropic provider key |
| `FIRECRAWL_API_KEY` | Required for audits | _(empty)_ | Firecrawl scraper credential |
| `PAGESPEED_API_KEY` | Required for perf | _(empty)_ | Google PageSpeed API key |
| `GOOGLE_FAST_MODEL` | Optional | `gemini-3-flash` | Fast-tier Google model |
| `GOOGLE_SMART_MODEL` | Optional | `gemini-2.5-pro` | Smart-tier Google model |
| `OPENAI_FAST_MODEL` | Optional | `gpt-5-nano` | Fast-tier OpenAI model |
| `OPENAI_SMART_MODEL` | Optional | `gpt-5` | Smart-tier OpenAI model |
| `ANTHROPIC_FAST_MODEL` | Optional | `claude-sonnet-4-5` | Fast-tier Anthropic model |
| `ANTHROPIC_SMART_MODEL` | Optional | `claude-opus-4-6` | Smart-tier Anthropic model |

</details>

<details>
<summary><strong>Queue and audit configuration</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `RUN_MIGRATIONS` | Optional | `1` (backend) / `0` (worker) | Auto-run Alembic on startup |
| `AUDIT_QUEUE_NAME` | Optional | `audit_jobs` | Redis list key for audit jobs |
| `AUDIT_JOB_MAX_ATTEMPTS` | Optional | `3` | Worker retry attempts per job |
| `AUDIT_JOB_RETRY_DELAY_SECONDS` | Optional | `2` | Delay between retries |
| `AUDIT_JOB_TIMEOUT_SECONDS` | Optional | `900` | Timeout per job attempt (15 min) |
| `AUDIT_CACHE_TTL_SECONDS` | Optional | `86400` | Default audit cache TTL |
| `AUDIT_CACHE_TTL_FAST_SECONDS` | Optional | `86400` | Fast-tier cache TTL |
| `AUDIT_CACHE_TTL_SMART_SECONDS` | Optional | `86400` | Smart-tier cache TTL |
| `GUEST_AUDIT_LIMIT` | Optional | `1` | Guest audit max requests per window |
| `GUEST_AUDIT_WINDOW_SECONDS` | Optional | `86400` | Guest audit rate window |

</details>

<details>
<summary><strong>Billing (Stripe)</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `STRIPE_MODE` | Optional | `test` | Billing mode (`test` / `live`) |
| `STRIPE_SECRET_KEY_TEST` | Required for test billing | _(empty)_ | Stripe secret key (test) |
| `STRIPE_SECRET_KEY_LIVE` | Required for live billing | _(empty)_ | Stripe secret key (live) |
| `STRIPE_WEBHOOK_SECRET_TEST` | Optional | _(empty)_ | Webhook signing secret (test) |
| `STRIPE_WEBHOOK_SECRET_LIVE` | Optional | _(empty)_ | Webhook signing secret (live) |
| `STRIPE_PRICE_STANDARD*` | Required for checkout | _(empty)_ | Plan price IDs (mode-specific `*_TEST`/`*_LIVE`) |
| `STRIPE_PRICE_COMMITMENT_*` | Required for commitments | _(empty)_ | Commitment tier + overage price IDs |
| `FEATURE_BILLING_ENABLED` | Optional | `true` | Toggle billing APIs/UI |
| `BILLING_GRACE_PERIOD_DAYS` | Optional | `7` | Grace period duration |
| `STRIPE_WEBHOOK_QUEUE_NAME` | Optional | `billing:webhook_events` | Redis queue for webhook worker |

</details>

<details>
<summary><strong>Email</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `MAIL_ENABLED` | Optional | `false` | Enable queued outbound email delivery |
| `EMAIL_PROVIDER` | Optional | `smtp` | Delivery provider (`smtp` for SMTP (Gmail)) |
| `EMAIL_FROM_ADDRESS` | Recommended | `support@qiko.ai` | Sender email address |
| `EMAIL_FROM_NAME` | Recommended | `Qiko Signal Intelligence Analyzer` | Sender display name |
| `SMTP_PASSWORD` | Required for SMTP | _(set in SSM)_ | SMTP transactional email API key |
| `EMAIL_OUTBOX_MAX_ATTEMPTS` | Optional | `5` | Retry limit for queued delivery |
| `SUPPORT_EMAIL` | Optional | `support@qiko.ai` | Support inbox |
| `BILLING_EMAIL` | Optional | `billing@qiko.ai` | Billing inbox |
| `PRIVACY_EMAIL` | Optional | `privacy@qiko.ai` | Privacy inbox |

</details>

<details>
<summary><strong>Observability</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `TRACING_BACKEND` | Optional | `none` | Tracing backend (`none` or `sentry`) |
| `SENTRY_DSN` | Optional | _(empty)_ | Fallback Sentry DSN |
| `SENTRY_DSN_AUDIT_API` | Optional | _(empty)_ | DSN override for API service |
| `SENTRY_DSN_AUDIT_WORKER` | Optional | _(empty)_ | DSN override for audit worker |
| `SENTRY_DSN_AI_SERVICE` | Optional | _(empty)_ | DSN override for AI service |
| `SENTRY_TRACES_SAMPLE_RATE` | Optional | `0.2` | Trace sample rate |
| `NEXT_PUBLIC_SENTRY_ENABLED` | Optional | `false` | Frontend Sentry toggle |
| `NEXT_PUBLIC_SENTRY_DSN` | Optional | _(empty)_ | Frontend Sentry DSN |

</details>

<details>
<summary><strong>AWS SSM Parameter Store (secrets)</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `SSM_ENABLED` | Optional | `true` | Enable the SSM secret overlay at boot |
| `SSM_PARAM_PREFIX` | Optional | `/qiko-signal/` | Parameter path prefix loaded into the environment |
| `SSM_OVERRIDE` | Optional | `true` | If true, SSM values take precedence over existing env values |
| `AWS_REGION` | Optional | `eu-central-1` | AWS region for SSM and S3 |
| `S3_BUCKET_NAME` | Recommended | _(empty)_ | S3 bucket for report and logo assets |

Secrets are stored as SecureString parameters under the prefix and loaded via the EC2 instance role (no static credentials). See `core/env_bootstrap.py`.

</details>

<details>
<summary><strong>Frontend / BFF proxy</strong></summary>

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `PROXY_TIMEOUT_MS` | Optional | `90000` | Long BFF timeout (audit/AI/admin routes) |
| `PROXY_SHORT_TIMEOUT_MS` | Optional | `5000` / `15000` | Default short BFF timeout |
| `NEXT_PUBLIC_API_BASE_URL` | Optional | `/api/v1` | Client-side API base path |
| `NEXT_PUBLIC_APP_URL` | Recommended | `http://localhost:3000` | Public app URL for sitemap/links |

</details>

See [LOCAL_DEV_RUNBOOK.md](LOCAL_DEV_RUNBOOK.md) for the full localhost onboarding flow.
See [deploy/VPS_DEPLOYMENT_RO.md](deploy/VPS_DEPLOYMENT_RO.md) for the production flow.
See [deploy/VPS_PROD_RUNBOOK.md](deploy/VPS_PROD_RUNBOOK.md) for the step-by-step VPS production runbook.

---

## Running Locally

### Docker mode (recommended)

One-time setup:

```bash
./scripts/setup-development.sh
```

This refreshes the canonical root `.env.development`, creates the minimal `backend/.env.development` overlay, and syncs `frontend/.env.local` with a shared JWT secret.

Start the full stack with hot-reload:

```bash
docker compose up -d db redis
docker compose up -d backend ai-service audit-worker external-webhook-worker email-worker
docker compose --profile frontend-dev up -d frontend-dev
```

The local backend startup is centralized in `backend/scripts/start-backend.sh`. In development compose it runs with `BACKEND_RELOAD=1`, so Python changes are picked up instantly. The `frontend-dev` profile runs `npm run dev` with HMR. `WATCHPACK_POLLING=true` is pre-configured for WSL2 compatibility.

View logs:

```bash
docker compose logs -f backend ai-service audit-worker external-webhook-worker email-worker frontend-dev
```

Stop everything:

```bash
docker compose --profile frontend-dev down
```

### Process mode (no Docker)

Start PostgreSQL and Redis separately, then run the backend API, audit worker, AI service, and frontend using the commands in the [Installation](#installation-no-docker) section.

---

## Docker

### Services overview

**Local development** (`docker-compose.yml`):

| Service | Image | Port | Description |
| --- | --- | --- | --- |
| `backend` | `./backend` | 8000 | FastAPI API (migrations on start, reload in dev) |
| `audit-worker` | `./backend` | - | Async audit job processor |
| `external-webhook-worker` | `./backend` | - | Outbound webhook delivery |
| `email-worker` | `./backend` | - | Email outbox processor (SMTP) |
| `billing-webhook-worker` | `./backend` | - | Stripe webhook event processor |
| `pdf-worker` | `./backend` | - | PDF report generation |
| `ai-service` | `./backend` | 8001 | AI provider orchestration |
| `monitoring-worker` | `./backend` | - | Monitoring pipeline |
| `visibility-worker` | `./backend` | - | Visibility index calculations |
| `performance-worker` | `./backend` | - | Daily performance data sync |
| `cron-sweeper` | `./backend` | - | Scheduled cleanup + maintenance |
| `frontend` | `./frontend` | 3000 | Next.js production server |
| `frontend-dev` | `./frontend` (profile) | 3000 | Next.js dev with HMR |
| `db` | `postgres:18` | 5432 | PostgreSQL |
| `redis` | `redis:8` | 6379 | Cache and queues |

**VPS production** (`docker-compose.vps.yml`): same services plus:

| Service | Image | Port | Description |
| --- | --- | --- | --- |
| `caddy` | `caddy:2.8` | 80, 443 | Reverse proxy with automatic TLS (Let's Encrypt) |

### Build individual images

```bash
docker build -t qiko-signal-backend ./backend
docker build -t qiko-signal-frontend ./frontend
```

Backend Dockerfile: multi-stage (`lint` stage runs `ruff check`, production copies deps into `python:3.11-slim`). Frontend Dockerfile: 3-stage (`deps`, `builder`, `runner` on `node:24-alpine`).

### Connectivity smoke test

```bash
./scripts/compose-connectivity-smoke.sh
```

Tests internal (frontend -> backend:8000) and external (localhost:8000, localhost:3000) connectivity.

---

## Database, Migrations, Seeds

Apply migrations:

```bash
cd backend
alembic upgrade head
```

Rollback all and re-apply (destructive):

```bash
cd backend
alembic downgrade base
alembic upgrade head
```

Docker reset (drops Postgres volume):

```bash
docker compose down -v
docker compose up --build
```

> If upgrading an existing VPS/production Postgres volume, do not drop it. Use dump/restore or `pg_upgrade`.

Seeds:
- No dedicated seed script. Dev bootstrap uses the same real JWT/OAuth flows as production.
- On first boot, DB-managed settings auto-seed from env/SSM.

Data backfill and maintenance:

```bash
# Clean stale Redis audit cache entries
python backend/scripts/cache_cleanup.py [--redis-url URL] [--pattern 'audit:cache:*'] [--dry-run]

# Generate a PDF report from JSON
python backend/scripts/gen_report.py --input payload.json --output report.pdf
```

---

## Workers

| Worker | Entrypoint | Queue | Purpose |
| --- | --- | --- | --- |
| **audit-worker** | `python queue_worker.py` | `audit_jobs` | Core audit processing (scraping, AI, scoring). Required. |
| **external-webhook-worker** | `sh scripts/start-external-webhook-worker.sh` | `external_webhooks` | Signed outbound webhook delivery with retry tracking |
| **email-worker** | `python email_outbox_worker.py` | `email_outbox` (DB) | HTML email delivery via SMTP |
| **billing-webhook-worker** | `python billing_webhook_worker.py` | `billing:webhook_events` | Async Stripe webhook processing |
| **pdf-worker** | `python pdf_worker.py` | `pdf_jobs` | PDF report generation with branding |
| **visibility-worker** | `python visibility_index_worker.py` | `visibility_index_jobs` | Visibility index calculations |
| **performance-worker** | `python performance_sync_worker.py` | _(internal)_ | Daily performance data sync |
| **monitoring-worker** | `sh scripts/start-monitoring-worker.sh` (`--loop`) | _(internal)_ | Monitoring pipeline (GA4 LLM traffic + SERP tracking). Runs as a long-lived loop. |
| **metrics-snapshot-worker** | `python metrics_snapshot_worker.py` | _(internal)_ | Metrics snapshot aggregation |
| **cron-sweeper** | `python cron_sweeper.py` | _(scheduled)_ | Stale hold expiration, progress reports, budget alerts, commitment cycles, daily summaries, retention cleanup |

Stale job cleanup (run as cron or manually):

```bash
python backend/cron_sweeper.py
```

Marks running jobs without heartbeat (>5 min) or stuck queued jobs (>1 hour) as failed.

The **monitoring-worker** runs in continuous `--loop` mode so it stays a long-lived
container instead of exiting after one pass (which would otherwise leave Docker's
restart policy churning it in a backoff loop). Set `MONITORING_INTERVAL_SECONDS`
(default `86400`, i.e. daily) to change the cadence between runs.

---

## Testing

### Backend

```bash
pytest backend/tests
```

338 test files with `pytest-asyncio` and `pytest-cov`. Strict mocking — no real external network calls.

### Frontend unit tests

```bash
npm --prefix frontend test
npm --prefix frontend run test:unit
```

214 test files using Vitest with jsdom and `@testing-library/react`.

### Frontend E2E tests

```bash
npm --prefix frontend run test:e2e              # headless Chromium
npm --prefix frontend run test:e2e:headed        # headed browser
npm --prefix frontend run test:e2e:report        # Playwright HTML report
```

Two visual suites answer different questions (see `frontend/e2e/README.md`):

- `npm --prefix frontend run test:e2e:visual` — regression: each screen vs its own
  previously recorded snapshot (the `visual-regression` CI job).
- `npm --prefix frontend run test:design-compare` — design conformance: each screen vs
  renders of the approved MVP HTML (SIGV2-1066; references in `e2e/design-reference/`).

| Variable | Default | Description |
| --- | --- | --- |
| `E2E_BASE_URL` | `http://localhost:3000` | Target frontend URL |
| `E2E_AUDIT_URL` | `https://qiko.ai` | URL used in audit test flows |
| `E2E_AUDIT_TIMEOUT_MS` | `720000` (12 min) | Max wait for audit completion |

---

## Linting & Static Analysis

### Backend (Ruff)

```bash
make -C backend lint          # ruff check .
make -C backend format        # ruff format .
make -C backend format:check  # ruff format . --check
```

### Frontend (ESLint + Prettier)

```bash
npm --prefix frontend run lint          # eslint .
npm --prefix frontend run format        # prettier . --write
npm --prefix frontend run format:check  # prettier . --check
```

---

## API Documentation

### Base URLs

| Context | Base URL |
| --- | --- |
| Direct backend access | `http://localhost:8000/api/v1` |
| Through frontend BFF (browser) | `/api/*` (proxied to backend `/api/v1/*`) |

### Interactive docs

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

### Authentication

Bearer JWT in `Authorization: Bearer <token>` header, or httpOnly `auth_token` cookie via BFF proxy.

### Router groups

| Prefix | Key endpoints |
| --- | --- |
| `/api/v1/auth` | Login, register, OAuth (Google/GitHub/Microsoft/LinkedIn), password reset, email verify, MFA, passkeys, refresh |
| `/api/v1` (core) | `POST /audit/jobs`, `GET /audit/jobs/{id}`, audit history, entities, competitors, PDF export |
| `/api/v1` (workspaces) | Workspace CRUD, project management, data sources (GSC/GA4/Bing), magic links |
| `/api/v1` (portal) | Client portal branding, assigned projects, dashboards, Jira tasks |
| `/api/v1/billing` | Stripe checkout, portal, invoices, plans, top-ups, commitments |
| `/api/v1/external` | Headless API: audit orchestration, report retrieval, CSV export, webhooks, usage |
| `/api/v1/admin` | User management, subscriptions, CMS, audit retention, system status, settings |
| `/api/v1/projects` | Monitoring, entity authority, ROI simulator, alert rules |
| `/api/v1/scheduled-audits` | Scheduled audit management |
| `/api/v1/integrations/*` | Jira, Slack, Teams |

### Example: login

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=<email>" \
  --data-urlencode "password=<password>"
```

### Example: async audit flow

```bash
# Create audit job
curl -X POST http://localhost:8000/api/v1/audit/jobs \
  -H "Authorization: Bearer <access_token>" \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","provider":"google","tier":"fast"}'

# Poll job status
curl -X GET http://localhost:8000/api/v1/audit/jobs/<job_id> \
  -H "Authorization: Bearer <access_token>"
```

---

## Deployment

### VPS deployment (Docker Compose + Caddy)

1. Prepare env files:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
```

2. Set required production values: `DOMAIN`, public URLs, JWT secrets, DB/Redis, AI keys, Stripe keys.
   Use `https://qiko.ai` as the app base and `BACKEND_PUBLIC_URL=https://qiko.ai`.
   For white-label custom domains, set `CUSTOM_DOMAIN_CNAME_TARGET`. Optionally configure `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ZONE_ID` for Cloudflare for SaaS.

3. Start the stack (interactive):

```bash
./scripts/deploy-production.sh
```

Or non-interactively:

```bash
export GCP_PROJECT_ID=qiko-signal
./deploy.sh
```

Or manually:

```bash
docker compose -f docker-compose.vps.yml up -d --build
```

4. Verify:

```bash
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml logs -f caddy frontend backend audit-worker email-worker
```

Caddy handles automatic HTTPS (Let's Encrypt) and routes `/api/v1/*` to backend, all else to frontend. Custom domains use on-demand TLS with the internal domain-activation gate.

### Deploy scripts

| Script                            | Purpose                                      |
|-----------------------------------|----------------------------------------------|
| `scripts/deploy-production.sh`    | Interactive first-time & full production deploy |
| `deploy.sh`                       | Non-interactive wrapper (backward compat)    |
| `scripts/rebuild.sh`              | Interactive routine redeploy (pull + rebuild) |
| `scripts/wipe-and-redeploy.sh`    | Full wipe + clean redeploy (destructive)     |
| `scripts/setup-development.sh`    | Interactive local dev environment setup       |
| `scripts/dev-setup.sh`            | Non-interactive legacy dev setup              |

### Day-2 operations

```bash
# Routine update (interactive)
./scripts/rebuild.sh

# View logs
docker compose -f docker-compose.vps.yml logs -f <service>

# Stop
docker compose -f docker-compose.vps.yml down
```

---

## CI/CD

### CI (`.github/workflows/ci.yml`)

Triggers on PRs to `main`, `preprod` and `production`, plus manual dispatch. Merging to
`main` does not repeat the suite. Runs parallel jobs for changed application areas:

| Job                 | Runtime                              | Steps                                                                                                          |
| ------------------- | ------------------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `changes`           | Ubuntu                               | Commit identity, changed areas, workflow lint, promotion evidence                                              |
| `backend-ci`        | Python 3.11                          | Install deps, `make lint`, `make format:check`, `pytest backend/tests`                                         |
| `frontend-ci`       | Node.js 24                           | `npm ci`, lint, format, unit tests, design harness tests                                                       |
| `visual-and-design` | Pinned Playwright image + Node.js 24 | One production build, e2e typecheck, `visual-*` projects; full MVP comparison only on explicit manual dispatch |
| `security`          | Multi-tool                           | pip-audit, Trivy (filesystem/IaC/container), Hadolint                                                |

`CI Status` is the required aggregate check. On `main -> preprod` and
`preprod -> production`, it can reuse successful CI receipts from the same repository
within seven days. The promotion merge tree must equal the source tree; each reused
gate must match its tested content and the current verification policy. Backend and
frontend evidence includes shared contracts; security evidence matches the whole tree.
Missing, expired or invalid evidence falls back to normal checks. Reused evidence is
not republished as a fresh scan. Historical fingerprints are checked against the
run's actual source tree and successful gate jobs. Application jobs explicitly
check out the PR head; the mandatory candidate check requires that head tree to equal
the synthetic merge tree, so stale branches must be updated before CI. Commit identity, the full-history
secret scan and the aggregate gate always run.

The full MVP design comparison is opt-in through manual CI dispatch with
`design_comparison=true`; it does not delay normal development or promotions.
Blocking visual regression remains part of frontend development CI.

Promotion PRs to
`preprod`/`production` must merge as merge commits, not squashes: the live provenance gate
requires `main` to remain an ancestor of the promoted branch (see `AGENTS.md` §5).

### Docker publishing (`.github/workflows/docker-publish.yml`)

| Trigger | Action |
| --- | --- |
| Push to `main` | Build and push images to GHCR |
| Tags `v*.*.*` | Build, push, sign with Sigstore Cosign, generate CycloneDX SBOM |
| Scheduled (nightly) | Rebuild and push |
| Manual dispatch | On-demand build |

Matrix build for `backend` and `frontend` images with Docker Buildx and GHA caching.

---

## Operational Scripts

### Dev setup and deployment

```bash
# Interactive local dev setup (recommended)
./scripts/setup-development.sh

# Interactive production deploy (first-time or full)
./scripts/deploy-production.sh

# Routine production redeploy (pull + rebuild)
./scripts/rebuild.sh

# Non-interactive deploy (CI/backward compat)
GCP_PROJECT_ID=xxx ./deploy.sh

# Analytics / webmaster provisioning on VPS
python3 scripts/setup_analytics_production.py --headless
```

### Smoke tests and validation

```bash
# Docker Compose connectivity check
./scripts/compose-connectivity-smoke.sh

# Production audit smoke test (guest + fast + smart flows)
./scripts/prod-audit-3flows.sh

# Project-scoped v2 API smoke test
./scripts/project-scoped-smoke.sh
```

### AWS SSM Parameter Store

```bash
# Seed secrets from a .env file into SSM (SecureString under /qiko-signal/)
python scripts/seed_ssm.py

# Secrets are read at boot via the EC2 instance role; no static keys required.
```

---

## Troubleshooting

| Issue | Likely Cause | Fix |
| --- | --- | --- |
| `frontend-dev` fails to bind `:3000` | `frontend` and `frontend-dev` started together | Start explicit service list with `frontend-dev` only |
| Backend missing secrets at startup | SSM unreachable or params not seeded under `/qiko-signal/` | Verify the EC2 instance role can read SSM, then run `python scripts/seed_ssm.py` |
| 502 from Next.js BFF routes | `BACKEND_URL` unreachable from frontend | Compose: `http://backend:8000`. Direct: `http://localhost:8000` |
| Login works but protected pages redirect | Missing JWT secret in frontend middleware | Set `JWT_SECRET_KEY` or `JWT_SECRET` in frontend env |
| OAuth callback returns wrong host | `BACKEND_PUBLIC_URL` unset | Set to public API domain |
| Stripe endpoints return config errors | Missing mode-specific keys | Set `STRIPE_MODE` + `STRIPE_SECRET_KEY_*` + price IDs |
| `alembic upgrade head` fails on start | DB unavailable or bad `DATABASE_URL` | Ensure DB container is healthy; verify connection string |
| Missing tables/columns after deploy | Migrations skipped or backend not restarted | Run `alembic upgrade head` or set `RUN_MIGRATIONS=1` and restart |
| Audit jobs stuck in queued state | Worker not running or Redis unreachable | Start audit-worker; verify `REDIS_URL` matches |
| Emails stuck in pending/retry | `email-worker` not running or SMTP config missing | Start worker; verify `MAIL_ENABLED=true`, `EMAIL_PROVIDER=smtp`, `SMTP_PASSWORD` |
| Stale running jobs (no heartbeat) | Worker crashed mid-job | Run `python backend/cron_sweeper.py` |
| `monitoring-worker` restarting in a backoff loop | Started in run-once mode without `--loop` | Use `scripts/start-monitoring-worker.sh` (runs `--loop`); set `MONITORING_INTERVAL_SECONDS` to tune cadence |

---

## Security Notes

- Authentication bypass toggles are not supported.
- Rotate JWT and provider secrets regularly; avoid storing plain secrets in repo-tracked files.
- Prefer AWS SSM Parameter Store (`SSM_ENABLED=true`) + a least-privilege EC2 instance role over static `.env` secrets in production.
- Use HTTPS in production (Caddy) before enabling OAuth, auth cookies, and billing flows.
- Password hashing uses Argon2 via `passlib[argon2]`.
- All `.env` files are gitignored. The repo only tracks `.env.example` templates.

### Security Hardening (Phase 7)

The March 2026 security audit produced 10 hardening tasks (SEC-01 through SEC-10), all implemented:

| SEC | Summary |
| --- | --- |
| SEC-01 | Dedicated `SESSION_SECRET_KEY` with fail-fast validation; secure cookie defaults |
| SEC-02 | Three-layer CSP: Caddy, backend middleware, frontend nonce-based (report-only rollout) |
| SEC-03 | CI gates: gitleaks, pip-audit, Trivy, Hadolint; cosign signing + CycloneDX SBOM |
| SEC-04 | Centralized Redis factory (`core/redis_client.py`) with auth/TLS; production URL validation |
| SEC-05 | `cap_drop: [ALL]`, `read_only`, `no-new-privileges`, `proxy-net`/`app-net` segmentation |
| SEC-06 | Path traversal guards, scheme validation, raw-path fallback removed |
| SEC-07 | Vitest 4.x, flatted fix, ajv override; `npm audit` clean |
| SEC-08 | httpOnly-cookie-only auth; dead browser-token primitives removed |
| SEC-09 | `safe_async_fetch`/`safe_sync_fetch` with DNS-rebinding + response-size guards |
| SEC-10 | Secrets in AWS SSM Parameter Store (SecureString) loaded via a least-privilege EC2 instance role |

Full tracking: `docs/owasp-asvs-security-tracking-matrix.md`

---

## Documentation Index

| Document | Description |
| --- | --- |
| `ARCHITECTURE.md` | In-depth technical architecture: components, data flow, AI strategy, queue design, report schema |
| `CHANGELOG.md` | Release notes and version history |
| `LOCAL_DEV_RUNBOOK.md` | Full localhost onboarding flow |
| `deploy/VPS_DEPLOYMENT_RO.md` | Step-by-step VPS deployment guide |
| `deploy/VPS_PROD_RUNBOOK.md` | VPS production runbook |
| `docs/owasp-asvs-security-tracking-matrix.md` | OWASP/ASVS security tracking matrix |
| `docs/security-headers.md` | Three-layer CSP and security header architecture |
| `docs/ci-security.md` | CI/CD security scanning pipeline |
| `docs/redis-hardening.md` | Redis auth/TLS hardening guide |
| `docs/container-hardening.md` | Container runtime hardening |
| `docs/bff-session-model.md` | BFF session architecture and auth flows |
| `docs/credential-isolation.md` | Cloud credential isolation and rotation |
| `docs/ai-debate-plan-tier-matrix.md` | AI debate behavior across tiers and plans |
| `docs/external-connectors-step-by-step-runbook.md` | BI connector operator runbook |
| `docs/public-guest-audit-api.md` | Public guest audit contract for the marketing site |
| `contracts/canonical_audit_payload.sample.json` | Sample canonical audit JSON for contract testing |
| `contracts/canonical_audit_field_mapping_checklist.md` | Canonical payload field → UI consumer mapping |
| `frontend/e2e/README.md` | Playwright E2E test documentation |

---

## Contributing

1. Create a branch from `main`.
2. Make focused changes.
3. Run local quality gates:

```bash
make -C backend lint
make -C backend format:check
pytest backend/tests
npm --prefix frontend run lint
npm --prefix frontend run format:check
npm --prefix frontend test
```

4. Open PR to `main`.
5. If schema changes are included, add an Alembic migration under `backend/alembic/versions/`.

---

## License

This software is proprietary. Copyright (c) 2025-2026 Qiko Signal. All rights reserved. See [LICENSE.md](LICENSE.md) for full terms.

---

*Release notes are tracked in `CHANGELOG.md` and git tags. Docker images are published to GHCR on `v*.*.*` tags and nightly.*
