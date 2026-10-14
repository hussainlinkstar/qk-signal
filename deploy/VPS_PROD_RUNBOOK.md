# VPS Production Runbook

Complete step-by-step guide to deploy `qiko-signal` from scratch on a bare VPS.

Every command in this file is designed for a VPS that has **only Docker and Docker Compose** installed. No Python venv, no Node.js required on the host. All tooling runs inside throwaway Docker containers.

Last updated: March 18, 2026

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [VPS Initial Setup](#2-vps-initial-setup)
3. [Configure DNS](#3-configure-dns)
4. [Clone the Repository](#4-clone-the-repository)
5. [Configure AWS Credentials](#5-configure-aws-credentials)
6. [Create Production Env Files](#6-create-production-env-files)
7. [Seed Production Secrets Into AWS SSM](#7-seed-production-secrets-into-aws-ssm)
8. [Deploy the Production Stack](#8-deploy-the-production-stack)
9. [Verify Production](#9-verify-production)
10. [Post-Deploy: Create Admin User](#10-post-deploy-create-admin-user)
11. [Post-Deploy: Analytics Provisioning (Optional)](#11-post-deploy-analytics-provisioning-optional)
12. [Normal Redeploy Flow](#12-normal-redeploy-flow)
13. [Full Wipe and Redeploy](#13-full-wipe-and-redeploy)
14. [Security Checklist](#14-security-checklist)
15. [Troubleshooting](#15-troubleshooting)

---

## Service Reference

The VPS production stack (`docker-compose.vps.yml`) runs these services:

| Service | Port | Purpose | Network |
|---|---|---|---|
| `db` | 5432 | PostgreSQL 18 database | app-net |
| `redis` | 6379 | Redis 8 (queues, cache, rate limiting) | app-net |
| `backend` | 8000 | FastAPI API server (runs Alembic migrations on start) | proxy-net + app-net |
| `ai-service` | 8001 | Separate AI provider microservice | app-net |
| `audit-worker` | - | Redis queue consumer for audit jobs | app-net |
| `email-worker` | - | EmailOutbox polling worker | app-net |
| `billing-webhook-worker` | - | Stripe webhook processing worker | app-net |
| `pdf-worker` | - | PDF report generation worker | app-net |
| `external-webhook-worker` | - | Outbound webhook delivery worker | app-net |
| `monitoring-worker` | - | Project monitoring worker | app-net |
| `visibility-worker` | - | AI visibility index worker | app-net |
| `performance-worker` | - | Performance sync worker | app-net |
| `cron-sweeper` | - | Scheduled maintenance/cron worker | app-net |
| `frontend` | 3000 | Next.js production build | proxy-net |
| `caddy` | 80, 443 | Reverse proxy with automatic TLS | proxy-net |

**Network segmentation**: `proxy-net` (caddy, frontend, backend) and `app-net` (backend, workers, ai-service, db, redis). Frontend and Caddy cannot reach db/redis/workers directly.

**Total memory**: ~5GB across all services. Recommend a VPS with at least 8GB RAM.

---

## 1. Prerequisites

Before starting, you need:

- A VPS (Ubuntu 22.04+ or Debian 12+ recommended) with at least **8GB RAM** and **40GB disk**
- **Docker** and **Docker Compose** installed on the VPS
- DNS control for your domain (examples use `qiko.ai`)
- **AWS credentials** (IAM user/role) with read access to AWS SSM Parameter Store under `/qiko-signal/` in `eu-central-1` (`ssm:GetParametersByPath` + `kms:Decrypt`), plus `ssm:PutParameter` if you will seed secrets from the VPS
- The following API keys ready:
  - `GEMINI_API_KEY` (Google AI Studio)
  - `FIRECRAWL_API_KEY` (firecrawl.dev)
  - `PAGESPEED_API_KEY` (Google PageSpeed Insights)
  - `SMTP_PASSWORD` (SMTP / Gmail app password)
  - `STRIPE_SECRET_KEY_LIVE` + `STRIPE_WEBHOOK_SECRET_LIVE` (Stripe billing)

---

## 2. VPS Initial Setup

SSH into your VPS and install Docker if not already present:

```bash
ssh -i ~/.ssh/qiko-signal_rsa ubuntu@63.184.100.65
```

### Install Docker (if needed)

```bash
curl -fsSL https://get.docker.com | sh
```

### Verify Docker is working

```bash
docker --version
docker compose version
```

### Open firewall ports

```bash
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 22/tcp
ufw enable
```

### Add swap space (required for Docker builds)

The Next.js frontend build can consume 3-4GB of RAM. Without swap, the build will be killed by the OOM killer with `SIGABRT`. Add at least 4GB of swap:

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile

# Make persistent across reboots
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# Verify
free -h
```

### Ensure script permissions after git clone/pull

Git may not preserve execute bits. After cloning or pulling, always run:

```bash
chmod +x deploy.sh scripts/*.sh
```

---

## 3. Configure DNS

In your DNS provider (e.g. Cloudflare), create these records pointing to your VPS IP:

```
A     qiko.ai       <VPS_PUBLIC_IP>
AAAA  qiko.ai       <VPS_PUBLIC_IPV6>    (if applicable)
CNAME www                  qiko.ai.
A     custom               <VPS_PUBLIC_IP>
AAAA  custom               <VPS_PUBLIC_IPV6>    (if applicable)
```

Keep `www` proxied through Cloudflare. `custom.qiko.ai` should be proxied if using Cloudflare for SaaS, otherwise `DNS only`.

### Verify DNS propagation

```bash
dig +short qiko.ai
dig +short www.qiko.ai
dig +short custom.qiko.ai
```

---

## 4. Clone the Repository

```bash
cd /opt
git clone <your-repo-url> qiko-signal
cd /opt/docker/qiko-signal
```

All remaining commands assume you are in `/opt/docker/qiko-signal`.

---

## 5. Configure AWS Credentials

Production secrets live in **AWS SSM Parameter Store** under the `/qiko-signal/` prefix in region `eu-central-1`. The backend loads them at container startup via `backend/core/env_bootstrap.py`.

Provide AWS credentials to the host (and therefore to the containers) using whichever method your environment uses — an EC2 instance role is preferred. If you use a static IAM user, export the standard variables (add to `~/.bashrc` for persistence):

```bash
export AWS_REGION=eu-central-1
export AWS_ACCESS_KEY_ID=<your-access-key-id>
export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>
```

The IAM identity needs:
- `ssm:GetParametersByPath` on `/qiko-signal/*` and `kms:Decrypt` (runtime read)
- `ssm:PutParameter` and `kms:Encrypt` (only if you will seed secrets from the VPS)

### Verify SSM access

```bash
aws ssm get-parameters-by-path --path "/qiko-signal/" --recursive --region eu-central-1 --query 'Parameters[].Name'
```

If this returns a list of parameter names (or an empty list before seeding), access is working.

> Note: there is no generic Google ADC credentials file. Google APIs are configured per-feature via their own keys/paths (e.g. `GEMINI_API_KEY`, `GA4_SERVICE_ACCOUNT_JSON_PATH`, `GOOGLE_PLACES_API_KEY`, `GOOGLE_CLIENT_ID/SECRET`) in AWS SSM — set only the ones you use. GA4 mounts its own service-account JSON only if `GA4_SERVICE_ACCOUNT_JSON_PATH` is configured.

---

## 6. Create Production Env Files

Copy the templates:

```bash
cp .env.example .env
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
```

### Edit the root `.env`

```bash
nano .env
```

**Required values to fill in** (replace all `<YOUR_...>` placeholders):

These values can be filled directly in `.env` and/or seeded into AWS SSM (section 7). At startup the SSM overlay takes priority over `.env`, so SSM is the source of truth for deployed secrets.

| Variable | What to put | Source |
|---|---|---|
| `POSTGRES_PASSWORD` | Strong random password | Generate a strong value; store it in SSM (section 7) |
| `DATABASE_URL` | `postgresql://user:PASSWORD@db:5432/dbname` | Embed the same POSTGRES_PASSWORD |
| `JWT_SECRET` | 64-char hex secret | Generate a strong value; store it in SSM |
| `JWT_SECRET_KEY` | 64-char hex secret | Generate a strong value; store it in SSM |
| `JWT_REFRESH_SECRET_KEY` | 64-char hex secret | Generate a strong value; store it in SSM |
| `SESSION_SECRET_KEY` | 64-char hex secret | Generate a strong value; store it in SSM |
| `GEMINI_API_KEY` | Your Google AI Studio key | https://aistudio.google.com/ |
| `FIRECRAWL_API_KEY` | Your Firecrawl key | https://firecrawl.dev/ |
| `PAGESPEED_API_KEY` | Your PageSpeed API key | Google Cloud Console |
| `SMTP_PASSWORD` | SMTP app password | https://myaccount.google.com/apppasswords |
| `STRIPE_SECRET_KEY_LIVE` | Your Stripe live secret key | https://dashboard.stripe.com/ |
| `STRIPE_WEBHOOK_SECRET_LIVE` | Your Stripe live webhook secret | Stripe webhook settings |
| `DOMAIN` | `qiko.ai` | Already set in template |
| `ADMIN_EMAILS` | `your@email.com` | Your admin email address |

You can generate a strong 64-char hex secret with `openssl rand -hex 32`.

**Values to leave as-is** (already correct in template):
- `ENVIRONMENT=production`
- `APP_BASE_URL=https://qiko.ai`
- `FRONTEND_URL=https://qiko.ai`
- `BACKEND_URL=http://backend:8000`
- `REDIS_URL=redis://redis:6379` (embed the Redis password if you enable auth)
- `AI_SERVICE_URL=http://ai-service:8001`
- All `NEXT_PUBLIC_*` variables

**Optional but recommended**:
- `REDIS_PASSWORD` — enables Redis authentication
- `OPENAI_API_KEY` — for OpenAI provider support
- `ANTHROPIC_API_KEY` — for Anthropic provider support
- `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ZONE_ID` — for custom domain automation
- `STRIPE_PRICE_*` — Stripe price IDs for each plan

### Edit `frontend/.env`

```bash
nano frontend/.env
```

Set `JWT_SECRET` to the same value as in root `.env`. Everything else should already be correct from the template.

### backend/.env

The `backend/.env` template is intentionally minimal (nearly empty). You generally don't need to edit it unless you have backend-only overrides.

---

## 7. Seed Production Secrets Into AWS SSM

Store the production secrets under the `/qiko-signal/` prefix in AWS SSM Parameter Store (region `eu-central-1`). At startup the backend overlays these onto the environment and they take priority over `.env`.

Set a single secret:

```bash
aws ssm put-parameter --name /qiko-signal/JWT_SECRET_KEY --type SecureString --value "$(openssl rand -hex 32)" --overwrite --region eu-central-1
```

Seed many parameters at once from the local `.env` you filled in section 6:

```bash
python3 scripts/seed_ssm.py
```

Verify the parameters exist:

```bash
aws ssm get-parameters-by-path --path "/qiko-signal/" --recursive --region eu-central-1 --query 'Parameters[].Name'
```

Make sure `POSTGRES_PASSWORD`, `DATABASE_URL`, the JWT/session secrets, and the API keys from the section 6 table are all present.

---

## 8. Deploy the Production Stack

```bash
cd /opt/docker/qiko-signal
./scripts/deploy-production.sh
```

`deploy-production.sh` validates the compose config, builds images, starts all 15 services, and runs a health check. On each boot the backend overlays the `/qiko-signal/` AWS SSM parameters onto the environment via `backend/core/env_bootstrap.py`.

For non-interactive use (CI/scripted deploys), use `./deploy.sh`.

The first build will take several minutes (downloading base images, installing Python deps, building the Next.js frontend).

### Important: keep POSTGRES_PASSWORD consistent with the DB volume

PostgreSQL initializes its data volume with the `POSTGRES_PASSWORD` present on the **first** boot. If you later change `POSTGRES_PASSWORD` in SSM (or `.env`), the backend will fail with `FATAL: password authentication failed` because the existing DB volume still has the old password.

**Fix for password mismatch (destroys all DB data):**

```bash
docker compose -f docker-compose.vps.yml down
docker volume rm thothgraph_postgres_data
docker compose -f docker-compose.vps.yml up -d
```

This destroys and recreates the DB volume with the current password. **All database data will be lost.**

---

## 9. Verify Production

### Check all containers are running

```bash
docker compose -f docker-compose.vps.yml ps
```

Expected: all 15 services show `Up` or `healthy`:

```
db                        healthy
redis                     healthy
backend                   healthy
ai-service                running
audit-worker              running
email-worker              running
billing-webhook-worker    running
pdf-worker                running
external-webhook-worker   running
monitoring-worker         running
visibility-worker         running
performance-worker        running
cron-sweeper              running
frontend                  healthy
caddy                     running
```

### Check backend health

```bash
curl -s https://qiko.ai/api/v1/system-status | head
```

### Check that migrations ran

```bash
docker compose -f docker-compose.vps.yml logs backend | grep -i migration
```

If migrations need to be run manually:

```bash
docker compose -f docker-compose.vps.yml exec backend alembic upgrade head
```

### Tail live logs

```bash
docker compose -f docker-compose.vps.yml logs -f backend audit-worker email-worker frontend caddy
```

### Verify AWS SSM runtime access

```bash
docker compose -f docker-compose.vps.yml exec backend python -c "
from core.env_bootstrap import bootstrap_environment
import os
bootstrap_environment()
for k in ['DATABASE_URL','REDIS_URL','JWT_SECRET_KEY','GEMINI_API_KEY','SMTP_PASSWORD']:
    v = os.getenv(k,'')
    print(f'{k}={\"set\" if v else \"MISSING\"} ({len(v)} chars)')
"
```

### Test TLS

```bash
curl -I https://qiko.ai
```

Should return `HTTP/2 200` with `strict-transport-security` header.

### Optional: connectivity smoke test

```bash
./scripts/compose-connectivity-smoke.sh
```

---

## 10. Post-Deploy: Create Admin User

Register a user through the frontend at `https://qiko.ai/register`.

The email address must match one of the addresses in `ADMIN_EMAILS` env var to get admin privileges. Verify the email (check your inbox or check the email-worker logs).

To verify admin access, navigate to `https://qiko.ai/admin`.

---

## 11. Post-Deploy: Analytics Provisioning (Optional)

For Google Analytics / Search Console / Bing Webmaster setup:

```bash
cd /opt/docker/qiko-signal

# The script auto-detects SSH, checks prerequisites, and rebuilds frontend.
# Open an SSH tunnel for OAuth callback first (from your local machine):
# ssh -i ~/.ssh/qiko-signal_rsa -L 8085:127.0.0.1:8085 ubuntu@63.184.100.65

# Run interactively (prompts for service selection, rebuilds frontend):
python3 scripts/setup_analytics_production.py

# Or non-interactive (all services, auto-rebuild):
python3 scripts/setup_analytics_production.py --yes
```

### What the script provisions

The script uses the **GA4 Admin API v1alpha** (upgraded from v1beta) for enhanced configuration. After creating or reusing a GA4 property and web data stream it automatically:

- **Data retention**: sets retention to 14 months
- **Enhanced measurement**: enables all toggles — scrolls, outbound clicks, site search, video engagement, file downloads, page changes, form interactions
- **Key events**: creates `sign_up`, `login`, `generate_lead`, `begin_checkout`, `purchase`
- **Custom dimensions**: creates `user_plan`, `audit_type`, `audit_provider`, `content_group`
- **Search Console link**: links the GA4 property to Google Search Console

**Bing Webmaster Tools** now also batch-submits key URLs (`/`, `/pricing`, `/docs`, `/blog`, `/about`, `/faq`) for faster indexing.

### Fallback behavior

All enhanced GA4 configuration is **non-fatal**. If the v1alpha API is unavailable (e.g., library not installed or API not enabled), the script falls back to v1beta and skips enhanced settings. Core property and stream creation still succeeds.

---

## 12. Normal Redeploy Flow

After pushing code changes to `main`:

```bash
cd /opt/docker/qiko-signal
./scripts/rebuild.sh
```

Or non-interactively:

```bash
cd /opt/docker/qiko-signal
./scripts/rebuild.sh --non-interactive
```

`rebuild.sh` pulls latest code, rebuilds Docker images, and runs health checks. Secrets are overlaid from AWS SSM at container startup.

---

## 13. Full Wipe and Redeploy

**WARNING: This destroys all Docker volumes including the database. All data will be lost.**

```bash
cd /opt/docker/qiko-signal
./scripts/wipe-and-redeploy.sh
```

The script requires typing `YES` to confirm, then tears down all containers/volumes, prunes Docker, and launches the full interactive deploy flow.

---

## 14. Security Checklist

After deploying, verify these controls:

| Check | Command |
|---|---|
| TLS active | `curl -I https://qiko.ai` — valid cert, HSTS header |
| CSP headers | Browser DevTools: `Content-Security-Policy` present |
| Container hardening | `docker inspect qiko-signal-backend-1 --format '{{.HostConfig.ReadonlyRootfs}}'` — returns `true` |
| Cap drop | `docker inspect qiko-signal-backend-1 --format '{{.HostConfig.CapDrop}}'` — returns `[ALL]` |
| Credential roles | `docker compose -f docker-compose.vps.yml exec backend env \| grep SERVICE_CREDENTIAL_ROLE` |
| Redis auth (if configured) | `docker compose -f docker-compose.vps.yml exec redis redis-cli ping` — returns `NOAUTH` |

For detailed security docs:
- `docs/security-headers.md`
- `docs/redis-hardening.md`
- `docs/container-hardening.md`
- `docs/credential-isolation.md`
- `docs/bff-session-model.md`

---

## 15. Troubleshooting

### Containers fail to start

```bash
# Validate compose config
docker compose -f docker-compose.vps.yml config -q

# Check logs
docker compose -f docker-compose.vps.yml logs --tail=100 backend audit-worker frontend caddy
```

### Backend health check fails

Common causes:
- Alembic migrations failing: `docker compose -f docker-compose.vps.yml logs backend | grep -i error`
- SSM secrets not loaded: confirm AWS credentials/region are available to the container and the `/qiko-signal/` parameters exist (see "AWS SSM values are missing at runtime" below)
- Database not ready: `docker compose -f docker-compose.vps.yml ps db`
- Production security validation failing: check for `SESSION_SECRET_KEY (must be >= 32 chars)` or `REDIS_URL has no password` in logs. This means the required secrets are missing/empty. Seed them into SSM (section 7) then redeploy.
- DB password mismatch: `FATAL: password authentication failed for user "user"` means the PostgreSQL volume was initialized with a different password than the current one. See "Important: keep POSTGRES_PASSWORD consistent" in section 8.

### Frontend build fails with SIGABRT

The Next.js build was killed by the OOM killer. Fix:

1. Add swap space (see section 2)
2. The Dockerfile already sets `NODE_OPTIONS="--max-old-space-size=3072"` to cap the Node heap

### AWS SSM values are missing at runtime

- Verify AWS credentials/region are available to the container (`AWS_REGION=eu-central-1`, instance role or `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)
- Verify `SSM_ENABLED` is not set to `false` for production
- Verify the IAM identity has `ssm:GetParametersByPath` on `/qiko-signal/*` plus `kms:Decrypt`
- Verify the parameter exists: `aws ssm get-parameter --name /qiko-signal/SECRET_NAME --with-decryption --region eu-central-1`
- If the path is empty, seed it (section 7)

### Workers are not running

```bash
docker compose -f docker-compose.vps.yml ps --format "table {{.Service}}\t{{.Status}}"
```

Start a missing worker:

```bash
docker compose -f docker-compose.vps.yml up -d <worker-name>
```

### Redis NOAUTH errors

If `REDIS_PASSWORD` is set but workers fail:
- Ensure `REDIS_URL` includes the password: `redis://:YOUR_PASSWORD@redis:6379`
- Both `REDIS_PASSWORD` and `REDIS_URL` must be consistent
- See `docs/redis-hardening.md`

### Caddy cannot get TLS certificate

- Verify DNS records point to VPS IP: `dig +short qiko.ai`
- Verify ports 80 and 443 are open: `ufw status`
- Check Caddy logs: `docker compose -f docker-compose.vps.yml logs caddy`

### PDF generation permission error

If PDF reports fail with "storage root not writable":

```bash
docker compose -f docker-compose.vps.yml exec -u root backend chown -R appuser:appuser /home/appuser/generated_storage
docker compose -f docker-compose.vps.yml exec -u root pdf-worker chown -R appuser:appuser /home/appuser/generated_storage
```

### First deploy is very slow

The first `docker compose up --build` downloads base images and builds everything from scratch. Expect 5-15 minutes depending on VPS specs. Subsequent deploys reuse cached layers.

---

## Quick Reference: Full First-Time Deploy Sequence

Copy-paste version for when you know what you're doing:

```bash
# === On the VPS ===
ssh -i ~/.ssh/qiko-signal_rsa ubuntu@63.184.100.65
cd /opt/docker/qiko-signal

# Provide AWS credentials (or use an EC2 instance role)
export AWS_REGION=eu-central-1
export AWS_ACCESS_KEY_ID=<your-access-key-id>
export AWS_SECRET_ACCESS_KEY=<your-secret-access-key>

# One-time: add swap (prevents OOM during frontend build)
fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

# One-time: fix script permissions
chmod +x deploy.sh scripts/*.sh

# Create .env from templates, fill secrets, then seed AWS SSM
cp .env.example .env   # edit values
python3 scripts/seed_ssm.py

# Deploy
./scripts/deploy-production.sh

# Verify
docker compose -f docker-compose.vps.yml ps
curl -s https://qiko.ai/api/v1/system-status | head
```
