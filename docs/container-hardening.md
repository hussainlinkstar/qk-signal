# Container Runtime Hardening — SEC-05

## Overview

This document describes the container-level security controls applied to both the production (`docker-compose.vps.yml`) and local development (`docker-compose.yml`) Docker Compose configurations.

## Production (VPS) Hardening

### Read-Only Root Filesystems

All application containers run with `read_only: true`, making the container root filesystem immutable at runtime. This prevents attackers who gain code execution from persisting malware, modifying binaries, or tampering with application code.

**Writable paths** are provided only where needed via `tmpfs` and named volumes:

| Service | tmpfs | Named Volumes (writable) |
|---------|-------|--------------------------|
| backend | `/tmp` (100M) | `generated_storage` |
| audit-worker | `/tmp` (100M) | — |
| external-webhook-worker | `/tmp` (50M) | — |
| email-worker | `/tmp` (50M) | — |
| pdf-worker | `/tmp` (200M) | `generated_storage` |
| ai-service | `/tmp` (100M) | — |
| frontend | `/tmp` (50M), `/app/.next-build/cache` (100M) | — |
| caddy | `/tmp` (10M) | `caddy_data`, `caddy_config` |
| redis | `/tmp` (10M), `/data` (50M) | — |

**Note:** PostgreSQL (`db`) does not use `read_only` because its internal init and WAL processes write to multiple non-data directories. It is protected by capability restrictions instead.

### Dropped Linux Capabilities

All services use `cap_drop: [ALL]` to remove all default Linux capabilities. Capabilities are added back only where strictly required:

| Service | Capabilities Added Back | Reason |
|---------|------------------------|--------|
| caddy | `NET_BIND_SERVICE` | Bind to ports 80/443 |
| db (postgres) | `DAC_OVERRIDE`, `FOWNER`, `SETGID`, `SETUID` | PostgreSQL init requires file ownership changes and user switching |
| redis | `SETGID`, `SETUID` | Redis entrypoint switches from root to redis user |
| All others | None | No additional capabilities needed |

### No-New-Privileges

All services set `security_opt: [no-new-privileges:true]`, preventing processes from gaining new privileges via setuid/setgid binaries. This is a defense-in-depth measure that blocks privilege escalation even if a vulnerable setuid binary exists in the container image.

### PYTHONDONTWRITEBYTECODE

All Python-based services (backend, workers, ai-service) set `PYTHONDONTWRITEBYTECODE=1` to prevent Python from writing `.pyc` bytecode cache files, which would fail under `read_only: true`.

## Network Segmentation

### Production (VPS)

The production compose defines two isolated bridge networks:

```
proxy-net:  caddy <-> frontend <-> backend
app-net:    backend <-> workers <-> ai-service <-> db <-> redis
```

**Service-to-network mapping:**

| Service | proxy-net | app-net |
|---------|-----------|---------|
| caddy | yes | — |
| frontend | yes | — |
| backend | yes | yes |
| audit-worker | — | yes |
| external-webhook-worker | — | yes |
| email-worker | — | yes |
| pdf-worker | — | yes |
| ai-service | — | yes |
| db | — | yes |
| redis | — | yes |

**Key isolation guarantees:**
- Frontend cannot reach db, redis, or any worker
- Caddy cannot reach db, redis, or any worker
- Workers cannot reach the internet-facing proxy layer
- Backend bridges both networks (receives HTTP from proxy, queries data tier)

### Local Development

Local dev uses the default flat bridge network for simplicity. Network segmentation is not applied because:
- Dev containers share bind-mounted source code
- Hot-reload and debugging tools need broad connectivity
- Security risk is minimal on developer workstations

## Dockerfile Improvements

### Backend (`backend/Dockerfile`)
- Added `EXPOSE 8000` declaration
- Added `HEALTHCHECK` using `urllib.request` to query `/api/v1/system-status`

### Frontend (`frontend/Dockerfile`)
- Added `HEALTHCHECK` using `wget --spider` to probe `http://localhost:3000/`
- `EXPOSE 3000` was already present

## Local Development Hardening

The local dev compose (`docker-compose.yml`) applies a subset of production hardening:
- `cap_drop: [ALL]` on all services
- `security_opt: [no-new-privileges:true]` on all services
- `cap_add` for postgres (`DAC_OVERRIDE`, `FOWNER`, `SETGID`, `SETUID`) and redis (`SETGID`, `SETUID`)
- Healthchecks added to `db` and `redis` (previously missing)
- Backend `depends_on` upgraded to `service_healthy` for db and redis

**Not applied in local dev** (would conflict with bind mounts / hot-reload):
- `read_only: true` — source bind-mounts write `__pycache__`, `.pytest_cache`, etc.
- `tmpfs` mounts — not needed without `read_only`
- Network segmentation — dev needs flat connectivity

## Verification

After deploying, verify hardening with:

```bash
# Check read-only filesystem
docker exec <container> touch /test-write 2>&1
# Should fail with "Read-only file system"

# Check capabilities
docker exec <container> cat /proc/1/status | grep Cap
# CapEff should show 0000000000000000 for most services

# Check no-new-privileges
docker exec <container> cat /proc/1/status | grep NoNewPrivs
# Should show NoNewPrivs: 1

# Check network isolation
docker exec frontend ping -c1 db 2>&1
# Should fail (frontend cannot reach db on proxy-net)

docker exec backend ping -c1 db 2>&1
# Should succeed (backend is on app-net)
```
