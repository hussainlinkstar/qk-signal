# Security Headers & Content Security Policy

This document describes the browser security header configuration for the
Qiko Signal platform, introduced in **TASK-47 / SEC-02**.

## Header Layers (Defense in Depth)

Headers are applied at **three layers** so that protection is maintained even
if one layer is bypassed or misconfigured:

| Layer | File | Applies To |
|-------|------|-----------|
| Caddy reverse proxy | `deploy/Caddyfile` | All production traffic |
| Next.js frontend | `frontend/next.config.mjs` + `frontend/src/middleware.ts` | All page responses |
| FastAPI backend | `backend/middleware/security_headers.py` | All API responses |

## Static Headers (all layers)

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Prevents click-jacking (legacy) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Restricts browser APIs |
| `X-XSS-Protection` | `0` | Disables flawed legacy XSS auditor |
| `Cross-Origin-Opener-Policy` | `same-origin` | Isolates browsing context |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Forces HTTPS (Caddy only) |

## Content Security Policy (CSP)

### Frontend CSP (pages)

CSP is set dynamically in `frontend/src/middleware.ts` using a per-request
nonce.  The policy is currently deployed in **report-only mode**
(`Content-Security-Policy-Report-Only`) since the SEC-11 rollback
(2026-03-20).  A `report-uri` directive sends violation reports to
`POST /api/v1/csp-report` on the backend, where they are logged and
buffered for the admin security posture dashboard.

### Directive Breakdown

| Directive | Value | Rationale |
|-----------|-------|-----------|
| `default-src` | `'self'` | Deny by default; each resource type must be explicitly allowed |
| `script-src` | `'self' 'nonce-{N}' 'strict-dynamic' https://www.googletagmanager.com https://www.google-analytics.com https://tagmanager.google.com` | Nonce for inline scripts; strict-dynamic for GTM-loaded children |
| `style-src` | `'self' 'unsafe-inline' https://fonts.googleapis.com` | `unsafe-inline` required for React `style={}` props, framer-motion, recharts, styled-jsx |
| `font-src` | `'self' https://fonts.gstatic.com` | Google Fonts WOFF2 files |
| `img-src` | `'self' data: blob: https://storage.googleapis.com` | Data URIs for screenshots, blob for PDF export, GCS for stored screenshots |
| `connect-src` | `'self' https://*.ingest.sentry.io https://*.sentry.io https://www.google-analytics.com https://analytics.google.com https://*.google-analytics.com https://*.analytics.google.com https://stats.g.doubleclick.net` | Sentry telemetry + GA4 beacons |
| `frame-src` | `'self' https://www.googletagmanager.com` | GTM noscript iframe |
| `worker-src` | `'self' blob:` | Sentry Session Replay web workers |
| `object-src` | `'none'` | No Flash/Java plugins |
| `base-uri` | `'self'` | Prevent `<base>` hijacking |
| `form-action` | `'self'` | Forms submit to same origin only |
| `frame-ancestors` | `'none'` | Prevents embedding in iframes (replaces X-Frame-Options) |
| `upgrade-insecure-requests` | — | Auto-upgrades HTTP to HTTPS |
| `report-uri` | `/api/v1/csp-report` | Sends violation reports to backend for admin monitoring |

### Backend CSP (API)

The backend middleware (`backend/middleware/security_headers.py`) applies a
minimal API-only CSP:

```
default-src 'none'; frame-ancestors 'none'; base-uri 'none'
```

API responses are JSON-only and should never execute scripts or load resources.

## Adding a New Third-Party Integration

When adding a new external script, font, or service to the frontend:

1. Identify which CSP directives need updating (e.g., `script-src` for a new
   analytics tool, `connect-src` for a new API, `img-src` for a new CDN).
2. Update `buildCspHeader()` in `frontend/src/middleware.ts`.
3. If the integration is loaded via GTM, `'strict-dynamic'` may cover it
   automatically; test first before adding explicit domains.
4. Deploy with `Content-Security-Policy-Report-Only` first and check browser
   DevTools console for violations before switching to enforcing mode.
5. Update this document with the new allowlist entry and rationale.

## CSP Enforcement History

1. **SEC-02** (initial): Deployed with `Content-Security-Policy-Report-Only`.
2. **SEC-11** (2026-03-16): Promoted to `Content-Security-Policy` (enforcing).
   Added `report-uri /api/v1/csp-report` for violation monitoring.
   Admin summary available at `GET /api/v1/csp-report/summary`.
3. **SEC-11 rollback** (2026-03-20): Reverted to report-only.
   Enforcing mode blocked ALL JavaScript because Next.js inline scripts
   (RSC payloads, webpack bootstrap) lacked nonce attributes.  The middleware
   now propagates the nonce via `x-nonce` request headers so Next.js can
   apply nonces to its own scripts.  Upgrade path back to enforcing:
   - Deploy with report-only; verify inline scripts in rendered HTML carry
     `nonce=` attributes (View Source).
   - Confirm zero CSP violations in browser console under report-only.
   - Change `"Content-Security-Policy-Report-Only"` to
     `"Content-Security-Policy"` in `middleware.ts` `attachCsp()`.
   - Monitor the admin CSP report summary for regressions.

If a future integration causes unexpected violations, temporarily revert
the header name in `middleware.ts` back to `Content-Security-Policy-Report-Only`
and monitor via the admin CSP report summary before re-enforcing.

## Embed Widget

The embed widget (`/public/embed/widget.js`) is served TO third-party sites
and runs under their CSP, not ours.  It loads Cloudflare Turnstile from
`https://challenges.cloudflare.com` — this does not need to be in the main
app CSP.

## CSRF Protection

Cross-Site Request Forgery (CSRF) is mitigated through the **cookie
`SameSite` attribute** and the **BFF session model**:

| Control | Implementation |
|---------|---------------|
| `SameSite=Lax` | All auth cookies (`auth_token`, `refresh_token`) are set with `sameSite: "lax"` in `frontend/src/app/api/auth/_route-utils.ts`. This prevents browsers from sending cookies on cross-origin POST/PUT/DELETE requests. |
| httpOnly cookies | Auth tokens are stored as `httpOnly` cookies — JavaScript cannot read or exfiltrate them. |
| No ambient credentials in API calls | Client-side `requestJson()` / `requestVoid()` use the BFF proxy which attaches cookies automatically; no explicit `Authorization` header is sent from the browser. |
| JSON content type | State-changing API endpoints expect `Content-Type: application/json`, which cannot be submitted by a plain HTML form (form POSTs produce `application/x-www-form-urlencoded` or `multipart/form-data`). |

**Risk assessment**: `SameSite=Lax` blocks cross-origin POST requests, which
covers the primary CSRF attack vector.  The `GET`-safe exception is
acceptable because all state-changing operations use `POST`/`PUT`/`PATCH`/`DELETE`.
No additional CSRF token header is required under this model.
