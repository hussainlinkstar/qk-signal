# VPS Deployment Guide (Docker, Caddy, AWS SSM, and Environment Standard)

Last updated: March 16, 2026

This document defines the deployment standard and environment rules for production.
It is not the primary step-by-step runbook.

Use these documents by intent:

- For local developer setup, use [LOCAL_DEV_RUNBOOK.md](/home/razvan/qiko-signal/LOCAL_DEV_RUNBOOK.md)
- For first-time VPS bring-up, deploy, redeploy, and wipe/rebuild, use [VPS_PROD_RUNBOOK.md](/home/razvan/qiko-signal/deploy/VPS_PROD_RUNBOOK.md)
- Use this document only for the canonical environment/AWS SSM rules and deployment policy

This repository uses a strict environment split:

- Production runtime uses `ENVIRONMENT=production`
- Production secrets live in AWS SSM Parameter Store under the `/qiko-signal/` prefix (region `eu-central-1`)
- Development runtime uses `ENVIRONMENT=development`
- Local development uses the `.env.development` file directly with `SSM_ENABLED=false` (no secret manager)

The backend bootstrap layer maps `ENVIRONMENT` to the legacy `APP_ENV` alias internally, so the templates should treat `ENVIRONMENT` as canonical.

The deployed secret overlay is controlled by `SSM_ENABLED` (default `true`), `SSM_PARAM_PREFIX` (default `/qiko-signal/`), `SSM_OVERRIDE` (default `true`), and `AWS_REGION` (default `eu-central-1`). If AWS is unreachable the overlay is skipped and the dotenv/env values are used.

---

## Stack Overview

Production deploys with `docker-compose.vps.yml` and runs:

- `db` — PostgreSQL 18
- `redis` — Redis 8
- `backend` — FastAPI API server
- `ai-service` — Separate AI provider microservice
- `audit-worker` — Redis queue consumer for audit jobs
- `email-worker` — EmailOutbox polling worker
- `pdf-worker` — PDF report generation worker
- `external-webhook-worker` — Outbound webhook delivery worker
- `frontend` — Next.js production build
- `caddy` — Reverse proxy with auto TLS

Network segmentation: `proxy-net` (caddy, frontend, backend) and `app-net` (backend, workers, ai-service, db, redis).

All containers run with `read_only: true`, `cap_drop: [ALL]`, `no-new-privileges`, memory/CPU limits, and per-service `SERVICE_CREDENTIAL_ROLE` (SEC-10).

The production domain for this project is `qiko.ai`.

For security documentation, see:

- `docs/security-headers.md` — CSP, HSTS, browser headers
- `docs/redis-hardening.md` — Redis auth/TLS
- `docs/container-hardening.md` — Container runtime hardening
- `docs/credential-isolation.md` — Per-service credential architecture

---

## Operational Runbooks

For execution steps, do not use this file as a checklist.

- First-time VPS setup, DNS, credentials upload, AWS SSM seeding, deploy, verification, redeploy, and wipe/rebuild live in [VPS_PROD_RUNBOOK.md](/home/razvan/qiko-signal/deploy/VPS_PROD_RUNBOOK.md)
- Local Docker/WSL setup, dotenv bootstrap, troubleshooting, and reset flow live in [LOCAL_DEV_RUNBOOK.md](/home/razvan/qiko-signal/LOCAL_DEV_RUNBOOK.md)

---

## AWS SSM Parameter Store Standard

### Parameter Naming Rules

- All production secrets live under the `/qiko-signal/` prefix, for example `/qiko-signal/DATABASE_URL`
- Secrets are stored as `SecureString` parameters in region `eu-central-1`
- The logical env key is the parameter name with the prefix stripped (e.g. `/qiko-signal/DATABASE_URL` → `DATABASE_URL`)

### Managing SSM Parameters

Use the AWS CLI to create, update, and inspect parameters:

```bash
# List all production secrets
aws ssm get-parameters-by-path --path "/qiko-signal/" --recursive --region eu-central-1

# Set or update a single secret
aws ssm put-parameter --name /qiko-signal/<KEY> --type SecureString --value "<VALUE>" --overwrite --region eu-central-1
```

To seed many parameters at once from a local `.env`, use `scripts/seed_ssm.py`.

The backend loads these parameters at container startup via `backend/core/env_bootstrap.py` and overlays them onto the process environment.

### IAM Required for SSM Operations

- Runtime containers need read access: `ssm:GetParametersByPath` (and `kms:Decrypt` for the SecureString key) on the `/qiko-signal/` path.
- An operator seeding secrets additionally needs `ssm:PutParameter` (and `kms:Encrypt`).

### Empty Prefix Rule

If `SSM_ENABLED=true` and the `/qiko-signal/` path is empty, the overlay contributes nothing and the backend falls back to the dotenv/env values.

Before the first production deploy:

1. seed the expected secrets under `/qiko-signal/` (via `aws ssm put-parameter` or `scripts/seed_ssm.py`)
2. verify IAM read access for the runtime role
3. only then deploy to the VPS

Use the execution steps from:

- [LOCAL_DEV_RUNBOOK.md](/home/razvan/qiko-signal/LOCAL_DEV_RUNBOOK.md) for local bootstrap
- [VPS_PROD_RUNBOOK.md](/home/razvan/qiko-signal/deploy/VPS_PROD_RUNBOOK.md) for VPS bootstrap

---

## Execution Summary

The canonical operational flow is:

1. Follow [VPS_PROD_RUNBOOK.md](/home/razvan/qiko-signal/deploy/VPS_PROD_RUNBOOK.md) for VPS execution
2. Keep production env files root-first, with `backend/.env` only for backend-only overrides
3. Keep local env files root-first, with `backend/.env.development` only for backend-only overrides
4. Treat AWS SSM as bootstrap/reseed storage for DB-managed settings, not the day-to-day runtime source of truth

---

## Notes

- `NEXT_PUBLIC_*` values are build-time values for Next.js. Changing them in SSM requires a frontend rebuild.
- `EMAIL_PROVIDER=smtp` is the default email transport. Set `SMTP_PASSWORD` in AWS SSM for production.
- The production templates intentionally use `ENVIRONMENT` instead of `APP_ENV`; the code preserves backward compatibility automatically.
