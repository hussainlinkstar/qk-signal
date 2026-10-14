import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { AUTH_REDIRECT_PARAM } from "@/constants/auth";
import { GATE_COOKIE, GATE_PATH, computeGateToken, getGatePassword } from "@/lib/signalGate";
import { refreshSessionFromCookie } from "@/app/api/auth/_route-utils";

// ---------------------------------------------------------------------------
// SEC-02: Content Security Policy, nonce-per-request approach.
// The policy is built once and injected into every page response via the
// `Content-Security-Policy` header.  A fresh nonce is generated per
// request and propagated to Next.js via the `x-nonce` request header so
// that `<Script nonce>` and JSON-LD inline scripts are allowed.
//
// Third-party allowlist rationale (see docs/security-headers.md):
//   - Google Tag Manager / GA4, marketing analytics
//   - Google Fonts, typography (style-src + font-src)
//   - Google Cloud Storage, audit screenshots served from GCS buckets
// ---------------------------------------------------------------------------

function generateNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  // btoa is available in Edge Runtime (middleware runs at the edge)
  return btoa(String.fromCharCode(...bytes));
}

function buildCspHeader(nonce: string): string {
  const isDev = process.env.NODE_ENV === "development";

  // Next.js dev mode uses eval() for webpack HMR and source maps.
  // Allow 'unsafe-eval' only in development to suppress noisy violations.
  const scriptSrc = isDev
    ? `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' 'unsafe-eval' https://www.googletagmanager.com https://www.google-analytics.com https://tagmanager.google.com`
    : `script-src 'self' 'nonce-${nonce}' 'strict-dynamic' https://www.googletagmanager.com https://www.google-analytics.com https://tagmanager.google.com`;

  const directives = [
    `default-src 'self'`,
    scriptSrc,
    `style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://api.fontshare.com`,
    `font-src 'self' https://fonts.gstatic.com https://cdn.fontshare.com`,
    `img-src 'self' data: blob: https://storage.googleapis.com https://lh3.googleusercontent.com https://*.googleusercontent.com`,
    `connect-src 'self' https://www.google-analytics.com https://analytics.google.com https://*.google-analytics.com https://*.analytics.google.com https://stats.g.doubleclick.net`,
    `frame-src 'self' https://www.googletagmanager.com`,
    `worker-src 'self' blob:`,
    `object-src 'none'`,
    `base-uri 'self'`,
    `form-action 'self'`,
    `frame-ancestors 'none'`,
  ];

  // Skip report-uri in dev, violations from HMR/eval are expected noise
  // and the backend may not be running to accept reports.
  if (!isDev) {
    directives.push(`report-uri ${process.env.NEXT_PUBLIC_BASE_PATH || ""}/api/v1/csp-report`);
  }

  return directives.join("; ");
}

// Define known protected route prefixes that require authentication.
// All other routes (public marketing pages, unknown paths) pass through
// to Next.js routing, which renders proper 404 pages for non-existent URLs.
const protectedRoutePrefixes = ["/dashboard", "/admin", "/portal"];

// Only hard-redirect authenticated users away from strict entry pages.
const strictLoginRoutes = ["/", "/login", "/register"];
const dashboardRoot = "/dashboard";

const isMalformedToken = (value?: string): boolean => {
  if (!value) {
    return true;
  }

  const trimmedValue = value.trim();
  return trimmedValue === "" || trimmedValue === "undefined" || trimmedValue === "null";
};

const clearAuthCookies = (response: NextResponse): NextResponse => {
  response.cookies.delete("auth_token");
  response.cookies.delete("auth_refresh_token");
  return response;
};

const redirectToLogin = (request: NextRequest, pathname: string): NextResponse => {
  // Clone nextUrl (not new URL(..., request.url)) so the app basePath is preserved.
  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  loginUrl.search = "";
  loginUrl.searchParams.set(AUTH_REDIRECT_PARAM, pathname);

  const response = NextResponse.redirect(loginUrl);
  return clearAuthCookies(response);
};

const hasUsableSessionCookie = (token?: string): boolean => !isMalformedToken(token);

const decodeJwtClaims = (token?: string): Record<string, unknown> | null => {
  if (!token || isMalformedToken(token)) {
    return null;
  }

  const parts = token.split(".");
  if (parts.length < 2) {
    return null;
  }

  const normalizedPayload = parts[1].replace(/-/g, "+").replace(/_/g, "/");
  const padding = "=".repeat((4 - (normalizedPayload.length % 4)) % 4);

  try {
    const payload = atob(`${normalizedPayload}${padding}`);
    return JSON.parse(payload) as Record<string, unknown>;
  } catch {
    return null;
  }
};

const isTokenProbablyValid = (token?: string): boolean => {
  if (!hasUsableSessionCookie(token)) {
    return false;
  }
  const claims = decodeJwtClaims(token);
  if (!claims) {
    return false;
  }
  const exp = claims.exp;
  if (typeof exp !== "number") {
    return false;
  }
  const now = Math.floor(Date.now() / 1000);
  return exp > now;
};

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isSessionExpired = request.nextUrl.searchParams.get("session_expired") === "true";

  // 0. Private preview gate. When SIGNAL_GATE_PASSWORD is set, lock the whole
  // platform behind a single shared password (cookie-based, SPA-friendly: one
  // prompt, no native auth popups, no broken XHR/CORS/SSE flows).
  const gatePassword = getGatePassword();
  if (gatePassword && !pathname.startsWith(GATE_PATH)) {
    const gateCookie = request.cookies.get(GATE_COOKIE)?.value;
    const expectedToken = await computeGateToken(gatePassword);
    if (gateCookie !== expectedToken) {
      // Clone nextUrl so the redirect keeps the configured basePath (/signal).
      const target = `${pathname}${request.nextUrl.search}`;
      const gateUrl = request.nextUrl.clone();
      gateUrl.pathname = GATE_PATH;
      gateUrl.search = "";
      gateUrl.searchParams.set("next", target);
      return NextResponse.redirect(gateUrl);
    }
  }

  // 1. Allow API proxy routes to pass through (FastAPI handles their auth)
  if (pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  // SEC-02: Generate a CSP nonce for this request.  The nonce is passed
  // downstream via a request header so that Next.js can read it in
  // layouts/components if needed.
  const nonce = generateNonce();
  const cspHeader = buildCspHeader(nonce);

  // SEC-02: Propagate nonce to Next.js via request headers so it can
  // apply nonces to its own inline scripts (RSC payloads, webpack).
  // Next.js reads the nonce by parsing the CSP header from the *request*
  // headers, setting only `x-nonce` is not enough.  We set both the
  // full CSP (so the framework can extract the nonce) and `x-nonce`
  // (for manual reads via `headers().get("x-nonce")` in layouts).
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", cspHeader);

  // Helper: create a NextResponse.next() with nonce-aware request headers.
  const nextWithCsp = (): NextResponse =>
    NextResponse.next({ request: { headers: requestHeaders } });

  // Helper: attach CSP + nonce to any response (next or redirect).
  // SEC-11 rollback: Report-only until nonce propagation is verified
  // end-to-end on all Next.js inline scripts.  Once confirmed, switch
  // back to "Content-Security-Policy" for enforcement and re-add
  // `upgrade-insecure-requests` to the directive list in buildCspHeader().
  const attachCsp = (response: NextResponse): NextResponse => {
    response.headers.set("Content-Security-Policy-Report-Only", cspHeader);
    response.headers.set("x-nonce", nonce);
    return response;
  };

  // 2. Validate token for edge runtime safety
  const tokenCookie = request.cookies.get("auth_token")?.value;
  const isTokenValid = isTokenProbablyValid(tokenCookie);

  // 3. Let expired sessions reach the login page and clear stale cookies
  // so the user is not bounced back into protected app routes.
  if (pathname === "/login" && isSessionExpired) {
    return attachCsp(clearAuthCookies(nextWithCsp()));
  }

  // 4. Handle authenticated users trying to access strict login pages.
  if (isTokenValid && strictLoginRoutes.includes(pathname)) {
    // Clone nextUrl so the app basePath is preserved in the redirect.
    const dashboardUrl = request.nextUrl.clone();
    dashboardUrl.pathname = dashboardRoot;
    dashboardUrl.search = "";
    return attachCsp(NextResponse.redirect(dashboardUrl));
  }

  // 5. Handle unauthenticated users trying to access protected routes.
  // Only redirect for known protected route prefixes, unknown paths
  // pass through so Next.js can render a proper 404 page instead of
  // incorrectly bouncing visitors to /login.
  const isProtectedRoute = protectedRoutePrefixes.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
  );

  if (!isTokenValid && isProtectedRoute) {
    if (pathname === "/login" || isSessionExpired) {
      return attachCsp(nextWithCsp());
    }

    // SIGNAL-1005: an expired access token doesn't mean the session is dead.
    // Try the refresh token before wiping cookies and bouncing to /login, the
    // same silent refresh the client already does via TokenManager.ensureSession(),
    // but for hard navigations, which never reach that client code otherwise.
    //
    // SIGV2-1304: only for a real navigation, which is the case this exists
    // for.
    //
    // `/auth/refresh` rotates: it deactivates the session it was given and
    // issues a new one, so a second request carrying the same refresh token
    // gets "Session has been revoked or expired" and the route then clears the
    // cookies. The client is safe, `TokenManager` holds one in-flight promise
    // and concurrent callers share it. This path is not, because it runs once
    // per request, and Next prefetches several routes at once: each prefetch
    // arrives with the same not-yet-rotated cookie and rotates it again.
    //
    // Returning from Stripe checkout is the worst case for that, and it is
    // where QA saw it: a navigation with an access token that expired while
    // the customer was on Stripe, landing on a page whose links are prefetched
    // immediately. The upgrade succeeds and the session dies.
    //
    // `next-router-prefetch` cannot be read here, Next strips its own Flight
    // headers from the request in middleware. `Sec-Fetch-Dest` is set by the
    // browser, is not stripped, and says exactly what is needed: `document`
    // is a navigation, a prefetch or an RSC fetch is `empty`.
    const fetchDest = request.headers.get("sec-fetch-dest");
    const isDocumentNavigation = fetchDest === null || fetchDest === "document";

    const refreshTokenCookie = request.cookies.get("auth_refresh_token")?.value;
    if (isDocumentNavigation && isTokenProbablyValid(refreshTokenCookie)) {
      const refreshed = await refreshSessionFromCookie(refreshTokenCookie as string);
      let refreshSucceeded = false;
      try {
        const body = (await refreshed.json()) as { authenticated?: boolean } | null;
        refreshSucceeded = body?.authenticated === true;
      } catch {
        refreshSucceeded = false;
      }

      if (refreshSucceeded) {
        const response = nextWithCsp();
        refreshed.cookies.getAll().forEach((cookie) => response.cookies.set(cookie));
        return attachCsp(response);
      }
    }

    return attachCsp(redirectToLogin(request, pathname));
  }

  return attachCsp(nextWithCsp());
}

export const config = {
  matcher: [
    // Explicitly match the bare root: with basePath the `/((?!...).*)` pattern
    // does not match "/" on its own, which left qiko.ai/signal ungated.
    "/",
    "/((?!api|_next/static|_next/image|_next/data|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|json|webmanifest|map|txt|xml)$).*)",
  ],
};
