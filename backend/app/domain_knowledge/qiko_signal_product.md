# Qiko Signal Product Knowledge Base, Support Bot Reference

This file is injected into the support assistant's prompt as a source of truth, so every line
here is effectively customer-facing copy. Scans are the only unit a customer has; the internal
cost unit never appears in this file.

## 1. What Is Qiko Signal

Qiko Signal is an AI visibility intelligence platform that measures how search engines and AI models discover, cite, and rank your brand. It scores every website or brand across three pillars:

- **SEO**, Search Engine Optimization (technical health, Core Web Vitals, structured data, crawlability)
- **AEO**, Answer Engine Optimization (featured snippet readiness, answerability, question-shaped content, AI Overview eligibility)
- **GEO**, Generative Engine Optimization (AI citation frequency, entity clarity, brand mention accuracy, AI share-of-voice)

Qiko Signal runs multiple AI models in parallel, Google Gemini, OpenAI, and Anthropic, producing cross-validated scores that eliminate single-model bias.

It tracks visibility across up to seven AI engines, depending on plan: Google Gemini (including AI Overviews), OpenAI (ChatGPT), Anthropic (Claude), Perplexity, xAI (Grok), DeepSeek and Meta (Llama). Copilot/Bing is not currently offered.

---

## 2. Scan Tiers

| Tier | Availability | What You Get |
|------|--------------|-------------|
| **Guest** | Free, no account needed, rate-limited | Core Web Vitals snapshot, HTTP/2 and HTTP/3 detection, basic AI recommendations. |
| **Fast** | All plans | Core technical SEO checks with a lightweight multi-model pass. |
| **Smart** | All plans | Full parallel multi-model analysis, deep AEO/GEO recommendations, entity mapping, comprehensive scoring. |
| **High Confidence** | Specialist and above | Adversarial multi-agent pipeline with up to 8 specialised AI agents (Generator, Critic, Judge), dual-track claim verification, integrity certificate. |

**This file deliberately states no scan duration** (SIGV2-1177). Durations are measured from the
recorded durations of completed scans and are injected into the assistant's prompt separately, as
a `SCAN DURATIONS` section, only when a depth has enough recorded runs to publish one. When that
section is absent, no figure exists and the correct answer is that we do not publish one for that
depth yet. Never write a duration into this file: a number here is a hardcoded constant again,
which is what SIGV2-1161 and SIGV2-1177 removed.

### Scan Modes
- **Website mode**, URL-centric. Crawls the URL for full technical diagnostics (Core Web Vitals, structured data, crawlability).
- **Brand mode**, Entity-centric. No URL required. Analyses how AI engines perceive the brand as an entity.

### Scan Allowance
- Each plan includes a number of scans per month. Scans are the only allowance a customer has.
- The tier does not change the count: one scan launched is one scan consumed, whether it is Fast, Smart or High Confidence.
- A sitemap crawl consumes one scan per crawled URL, and stops queuing when the allowance is exhausted.
- Usage is counted over a rolling 30-day window, so a slot frees up as the oldest counted scan leaves the window.
- A scan is counted when it is accepted. Successful, degraded and failed outcomes all count, so a failure is not a free retry. A duplicate launch for the same target is rejected before it is accepted, so a retry never counts twice.
- Scheduled scans, workflow-triggered scans and API-triggered scans count exactly like a manual launch.
- A competitor benchmark refresh that Signal initiates is never one of the customer's scans.
- For more capacity, change plan or ask about a commitment agreement from Dashboard > Billing.

---

## 3. Plans and Pricing (All in USD)

| Plan | Price | Sites | Scans/mo | Key Features |
|------|-------|-------|----------|-------------|
| **Starter** | Free | 1 | 1 | Full SEO/AEO/GEO scan with PDF report, one free scan per month. No card required for evaluation. |
| **Standard** | $49/mo | 1 | 200 | Core SEO/AEO/GEO scans, Core Web Vitals, PDF reports, performance sync. Ideal for solo practitioners. |
| **Specialist** | $99/mo | 10 | 800 | Unlocks High Confidence mode, API & MCP access, competitor analysis and semantic gap mapping. Built for growing teams and agencies. |
| **Executive** | Contact us for custom pricing | Unlimited | 2,000 | Custom agent development and unlimited sites. White-label workspace and PDF, custom domains, multi-workspace federation, brand integrity guardrails and E-E-A-T trust audit are available as bespoke work. For multi-brand operations. |

### Plan Upgrades and Downgrades
- Upgrades take effect immediately with prorated billing. New features unlock instantly.
- Downgrades take effect at the start of the next billing cycle.
- Manage from Dashboard > Billing.

---

## 4. High Confidence Mode (Detail)

Available on Specialist and above. It consumes one scan from the allowance, exactly like any other tier.

**Pipeline**: Three domain-isolated generators (SEO, GEO, AEO) → three domain-scoped critics → consolidator → global magistrate. Each agent role runs on a different AI provider.

**Dual-Track Verification**:
- Track A: Factual/descriptive claims verified through strict evidence grounding.
- Track B: Prescriptive/strategic recommendations verified against the Unified Truth Context.

**Integrity Certificate**: Shows how many claims were fully supported, flagged for review, blocked as unsupported, or require manual disposition. Includes per-track breakdowns.

---

## 5. Dashboard Features

### Workspace-Level
- **Overview**, Workspace summary, project list, recent scans.
- **Audit**, Run new scans, view scan history.
- **Billing**, Plan management, invoice history, commitment agreements.
- **Reports**, Cross-project report library with multi-language delivery.
- **Settings**, Workspace settings, API keys, white-label branding, custom domains, email footer.
- **Connections**, Google Search Console, Bing Webmaster Tools, Google Analytics 4. Jira, Slack and Microsoft Teams are not currently available.
- **Developer**, API documentation, API keys, webhook configuration.

### Project-Level
- **SEO / AEO / GEO dashboards**, Pillar-specific scores and trends.
- **Monitoring**, AI visibility queries, summaries, trend aggregation, bot log analysis.
- **Competitive Analysis**, Benchmark against competitors across all three pillars.
- **ROI Simulator**, Predictive traffic/ROI modeling from GSC data.
- **Recommendations**, Prioritised action items with recommendation badges.
- **Reports**, Project-scoped report generation and annotation threads.
- **Settings**, Project configuration, team access.

The following pages are not currently available: standalone Entity Authority, workflow Automations, project Timeline, Content Hub/Content Strategy, project Tasks board and Dashboard > Scheduled Audits.

---

## 6. Integrations

- **Google Search Console**, Import performance data and search analytics.
- **Bing Webmaster Tools**, Import Bing search data.
- **Google Analytics 4**, Import traffic and referral data.
- **Webhooks**, Outbound event notifications (scan completion, score changes, alerts).
- **REST API**, Programmatic access with API key auth (Specialist+).
- **CSV/JSON Export**, Compatible with Looker Studio, Google Sheets, Power BI.

Jira, Slack and Microsoft Teams integrations are not currently available.

---

## 7. Security and Compliance

- **Data Privacy**: Enterprise API deployments with zero-retention agreements. Scan data is never used to train third-party AI models.
- **Encryption**: TLS in transit, Fernet column-level encryption at rest.
- **MFA**: TOTP-based (Google Authenticator, Authy, 1Password). Enable in Dashboard > Account Settings > Security. Issuer: "Qiko Signal".
- **RBAC**: Owner, Editor, Viewer, Client portal roles per workspace.
- **GDPR**: Cookie consent, right to deletion, data retention (screenshots redacted after 30 days, scans purged after 90 days unless flagged).
- **Container Hardening**: Read-only filesystems, dropped capabilities, network segmentation.
- **Custom Domains**: Executive can serve the portal on branded domains (e.g., signal.youragency.com) as bespoke work.

---

## 8. Account Management

- **Login**: Email/password with optional MFA. OAuth via Google and GitHub.
- **Password Reset**: Dashboard > Account Settings or forgot-password flow.
- **MFA Setup**: Dashboard > Account Settings > Security. Generate secret → scan QR → confirm OTP. Lost device? Contact support@qiko.ai for manual recovery.
- **Workspace Roles**: Managed in Dashboard > Settings. Invite by email with Owner/Editor/Viewer roles.

---

## 9. Common Support Scenarios

### Billing
- View invoices: Dashboard > Billing > Invoice History.
- Change plan: Dashboard > Billing > select new plan.
- Need more scans than the plan includes: change plan, or ask about a commitment agreement from Dashboard > Billing.
- Cancel: Dashboard > Billing or contact billing@qiko.ai.
- All billing in USD via Stripe.

### Scans
- Run a scan: Dashboard > Audit > enter URL or brand name > select tier > Run.
- Guest scan: free and available without an account, rate-limited. Do not promise a specific page; offer to walk the customer through signing in for a full scan instead.

### Reports
- Generate PDF: Open a scan result > click "Export PDF".
- White-label PDF: Executive (configure branding in Dashboard > Settings).
- Multi-language: Configure language per project in project settings.

### API
- Get API key: Dashboard > Settings or Dashboard > Developer.
- API docs: Dashboard > Developer > Docs.
- Webhooks: Dashboard > Developer > Webhooks.

---

## 10. Contact

- **General support**: support@qiko.ai
- **Billing**: billing@qiko.ai
- **Website**: https://qiko.ai/signal
- **Documentation**: https://qiko.ai/signal/docs
- **FAQ**: https://qiko.ai/signal/faq
