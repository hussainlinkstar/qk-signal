# Redis Auth/TLS & Service Secret Hardening

> SEC-04 implementation reference. Updated 2026-03-16.

## Overview

Redis is used for queues (`audit_jobs`, `pdf_jobs`, `billing:webhook_events`,
`visibility_index_jobs`), rate limiting, session/token deny-listing, OAuth code
storage, and inter-service cache. This document describes the hardened
connection contract introduced by SEC-04.

## Connection Architecture

### Centralized Factory (`backend/core/redis_client.py`)

All new Redis usage should go through the centralized factory:

```python
from core.redis_client import get_async_redis, get_async_redis_client
from core.redis_client import get_sync_redis, get_sync_redis_client

# Short-lived (routers, middleware, services)
async with get_async_redis() as r:
    await r.set("key", "value")

# Long-lived (workers) — caller manages lifecycle
client = get_async_redis_client()
try:
    ...  # worker loop
finally:
    await client.aclose()

# Synchronous (passkey, ROI simulator, admin helpers)
with get_sync_redis() as r:
    r.set("key", "value")
```

All clients created by the factory have:

| Setting | Value | Notes |
|---|---|---|
| `decode_responses` | `True` | Consistent string handling |
| `socket_timeout` | 5.0s | Prevents hung connections |
| `socket_connect_timeout` | 3.0s | Prevents slow-start hangs |
| `health_check_interval` | 30s | Workers only; 0 for ephemeral |

### TLS Support

When `REDIS_URL` uses the `rediss://` scheme, the `redis-py` library
automatically negotiates TLS. No additional configuration is needed in
application code.

```env
# Plain (dev only)
REDIS_URL=redis://redis:6379

# Authenticated
REDIS_URL=redis://:YOUR_STRONG_PASSWORD@redis:6379

# Authenticated + TLS
REDIS_URL=rediss://:YOUR_STRONG_PASSWORD@redis:6380
```

## Production Validation

The `Settings._validate_production_secrets()` validator in
`backend/core/config.py` now checks `REDIS_URL` in non-dev environments:

| Check | Severity | Behavior |
|---|---|---|
| No password in URL | **Error** | Blocks startup |
| Dev-default hostname (`redis`, `localhost`) without password | **Error** | Blocks startup |
| No TLS (`redis://` instead of `rediss://`) | **Warning** | Logged, not blocking |
| Empty hostname | **Error** | Blocks startup |

### Local Development Escape Hatch

In `ENVIRONMENT=development` (the default), Redis URL validation is skipped
entirely. The bare `redis://redis:6379` default works without auth.

## Docker Compose Configuration

### Local dev (`docker-compose.yml`)

```yaml
redis:
  image: redis:8
```

No password, no TLS. `REDIS_URL=redis://redis:6379` across all services.

### Production VPS (`docker-compose.vps.yml`)

```yaml
redis:
  image: redis:8
  command: >-
    sh -c '
    if [ -n "$$REDIS_PASSWORD" ]; then
      exec redis-server --requirepass "$$REDIS_PASSWORD"
    else
      exec redis-server
    fi'
  environment:
    - REDIS_PASSWORD=${REDIS_PASSWORD:-}
  healthcheck:
    test: >-
      sh -c '
      if [ -n "$$REDIS_PASSWORD" ]; then
        redis-cli -a "$$REDIS_PASSWORD" --no-auth-warning ping
      else
        redis-cli ping
      fi'
```

**To enable auth:**

1. Set `REDIS_PASSWORD=<strong-password>` in your `.env`
2. Set `REDIS_URL=redis://:strong-password@redis:6379` in your `.env`
3. Both values must match

The health check now passes the `-a` flag when `REDIS_PASSWORD` is set,
preventing false-negative health failures.

## Migrated Components

The following components now use the centralized factory:

| Component | Type | Client Lifetime |
|---|---|---|
| `queue_worker.py` | async | Long-lived (process) |
| `pdf_worker.py` | async | Long-lived (process) |
| `billing_webhook_worker.py` | async | Long-lived (process) |
| `visibility_index_worker.py` | async | Long-lived (process) |
| `external_webhook_worker.py` | async | Long-lived (process) |
| `system_checks.py` | async | Per-request (health check) |
| `middleware/session_checker.py` | async | Per-request (middleware) |
| `routers/api_router.py` | async | Per-request (9 call sites) |
| `routers/auth.py` | async | Per-request (5 call sites) |
| `routers/workspace_router.py` | async | Per-request |
| `routers/external_api_router.py` | async | Per-request (3 call sites) |
| `routers/embed_router.py` | async | Per-request |
| `admin.py` | async+sync | Per-request (7 call sites) |
| `ai_service.py` | async | Long-lived (process) |
| `services/workflow_engine.py` | sync | Per-request |
| `services/external_webhook_service.py` | sync | Per-request |
| `services/external_api_service.py` | sync | Per-request |
| `services/ai_provider_runtime_service.py` | sync | Per-request |
| `services/sitemap_crawler_service.py` | async | Per-request (4 call sites) |
| `services/embed_service.py` | async | Per-request |
| `services/passkey_service.py` | sync | Per-request |
| `services/semantic_cache_service.py` | sync | Per-request |
| `scripts/validate_expert_pipeline.py` | sync | Script lifetime |
| `scripts/cache_cleanup.py` | sync | Script lifetime |

All `redis.from_url()` call sites have been migrated to the centralized
factory (SEC-13, completed 2026-03-16). Zero direct `from_url()` calls
remain outside `core/redis_client.py` and test files.

## Running Locally with Auth (Optional)

To test authenticated Redis in local dev:

```bash
# In .env
REDIS_PASSWORD=dev-test-password
REDIS_URL=redis://:dev-test-password@redis:6379

# Restart
docker compose down && docker compose up -d
```

## Troubleshooting

### "NOAUTH Authentication required"

The `REDIS_URL` does not include the password. Update it to
`redis://:PASSWORD@host:port`.

### Health check failing after enabling password

Ensure the `REDIS_PASSWORD` env var is available to the `redis` container, not
just to application containers.

### "Connection refused" after enabling TLS

Redis does not support TLS natively in the official Docker image without custom
config. For TLS, use a managed Redis service (e.g. AWS ElastiCache, Redis
Cloud) or a TLS-terminating proxy (e.g. stunnel).
