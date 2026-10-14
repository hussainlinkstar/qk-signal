# BFF Session Model & Server-Side Session Authority

> SEC-08 reference document.  Describes the authentication architecture
> after the strict BFF migration.

## Overview

All user authentication state is managed **server-side** through a
Backend-for-Frontend (BFF) proxy pattern.  Browser JavaScript never
has access to real JWT tokens.

```
Browser ─── (cookies auto-sent) ──→ Next.js BFF ─── (reads cookie, ──→ FastAPI Backend
                                    (API routes)     adds Bearer header)   (verifies JWT)
```

## Token Storage

| Where             | What                                          |
| ----------------- | --------------------------------------------- |
| `auth_token`      | Access JWT — httpOnly, sameSite=lax, secure    |
| `auth_refresh_token` | Refresh JWT — httpOnly, sameSite=lax, secure |

Both cookies are set by the BFF auth routes in
`frontend/src/app/api/auth/_route-utils.ts`.  The `secure` flag is
enabled in production environments.

**No token material is stored in `localStorage`, `sessionStorage`, or
any other browser-accessible store.**

## Sentinel Token Pattern

Client-side code that needs to know whether a session exists calls
`TokenManager.getAccessTokenWithFallback()`, which returns:

- `"__cookie_session__"` — a sentinel string indicating "a valid
  server session exists".  This is **not** a real JWT.
- `null` — no session exists.

Components pass the sentinel as `Authorization: Bearer __cookie_session__`
on requests to `/api/*`.  The BFF proxy (`frontend/src/app/api/proxy.ts`)
strips the sentinel header and injects the real `auth_token` cookie
value before forwarding to the backend.

## Auth Flows

### Email + Password Login

1. Browser `POST /api/auth/login` (BFF route).
2. BFF forwards form data to backend `POST /api/v1/auth/login`.
3. Backend returns `{ access_token, refresh_token }`.
4. BFF sets both as httpOnly cookies.
5. BFF returns `{ authenticated: true }` — **tokens never reach JS**.
6. `AuthContext` calls `authService.getCurrentUser()` to load profile.

### OAuth (Google / GitHub / Microsoft / LinkedIn)

1. Backend redirects browser to provider with OAuth state.
2. Provider redirects to backend callback.
3. Backend stores tokens in Redis under a one-time code (60 s TTL).
4. Backend redirects browser to `/auth/callback?code=<one-time>`.
5. Frontend `POST /api/auth/exchange-code` exchanges code for session.
6. BFF calls backend, gets tokens, sets httpOnly cookies.
7. `AuthContext.setSession()` validates the new session.

### Passkey (WebAuthn)

1. Frontend requests challenge from backend via BFF proxy.
2. Browser performs WebAuthn assertion.
3. Frontend `POST /api/auth/passkeys/login/verify` (BFF route).
4. BFF forwards to backend, gets tokens, sets httpOnly cookies.

### Token Refresh (Silent, Server-Side)

1. `TokenManager.ensureSession()` → `GET /api/auth/session?ensure=1`.
2. BFF session route checks access token expiry from the cookie.
3. If near-expiry, BFF sends `auth_refresh_token` cookie to backend
   `POST /api/v1/auth/refresh`.
4. Backend performs refresh-token rotation: invalidates old token,
   issues new pair.
5. BFF sets new httpOnly cookies.
6. Returns `{ authenticated: true }` to browser.

Concurrent `ensureSession()` calls are deduplicated into a single
in-flight request.

### Logout

1. `AuthService.logout()` → `POST /api/auth/logout` (BFF).
2. BFF reads cookies, forwards to backend with Bearer + refresh token.
3. Backend revokes session JTI in Redis and deactivates DB session row.
4. BFF clears both httpOnly cookies (`maxAge: 0`).
5. `TokenManager.broadcastLogout()` fires a `StorageEvent` so other
   tabs clear in-memory auth state.

### Cross-Tab Logout

Uses `localStorage` key `auth_logout` as a signaling channel.  The
`AuthProvider` listens for `StorageEvent` on this key.  When another
tab broadcasts logout, the current tab:
- Sets `user` to `null` (clears in-memory state).
- Redirects to `/login` if not already there.

**No sensitive data is written to `localStorage`.**

## Server Components (SSR)

`frontend/src/utils/server-fetch.ts` reads the `auth_token` cookie via
Next.js `cookies()` API and adds `Authorization: Bearer <token>` when
calling the backend directly (bypassing the BFF proxy).

## Backend Session Revocation

The backend maintains a dual-layer revocation system:

1. **JTI-based Redis deny list** (`session:revoked:{jti}`) — checked by
   `SessionRevocationMiddleware` on every request.  Fast unsigned JWT
   decode extracts the JTI; signature verification happens downstream.
2. **Refresh token hash deny list** (`token:denied:{hash}`) — checked
   during refresh-token rotation.
3. **DB session rows** (`UserSession.is_active`) — authoritative record
   checked during refresh.

## Key Files

| File | Purpose |
| --- | --- |
| `frontend/src/utils/token-manager.ts` | Client session manager (sentinel pattern) |
| `frontend/src/services/auth.service.ts` | Client auth service (login, logout, profile) |
| `frontend/src/contexts/AuthContext.tsx` | React auth context provider |
| `frontend/src/app/api/auth/_route-utils.ts` | BFF cookie management (set/clear/refresh) |
| `frontend/src/app/api/auth/session/route.ts` | BFF session check & refresh endpoint |
| `frontend/src/app/api/auth/login/route.ts` | BFF login forwarding |
| `frontend/src/app/api/auth/logout/route.ts` | BFF logout + cookie cleanup |
| `frontend/src/app/api/proxy.ts` | BFF proxy (sentinel stripping, cookie→Bearer) |
| `frontend/src/utils/server-fetch.ts` | SSR fetch with cookie auth |
| `frontend/src/lib/auth-session.ts` | Shared JWT decode/expiry utilities |
| `backend/routers/auth.py` | Backend auth endpoints |
| `backend/auth/token_verifier.py` | JWT verification + user resolution |
| `backend/services/auth_service.py` | Token creation + session management |
| `backend/middleware/session_checker.py` | JTI revocation middleware |

## Security Properties

- **No XSS token theft**: Real tokens are in httpOnly cookies, invisible
  to JavaScript.
- **No CSRF on mutations**: All auth mutations use `POST` with
  `sameSite=lax` cookies, which are not sent on cross-origin POST.
- **Token refresh is invisible**: The browser never handles refresh
  tokens directly — the BFF manages the rotation.
- **Session revocation is immediate**: Redis-based JTI deny list +
  DB session deactivation.
- **Cross-tab logout is reliable**: `StorageEvent` fires synchronously
  across tabs in the same origin.
