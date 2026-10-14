import { COOKIE_SESSION_BEARER } from "@/lib/auth-session";

/**
 * Server-authoritative session manager.
 *
 * All authentication state lives in httpOnly cookies managed by the BFF
 * (Next.js API routes).  This class never stores or exposes real JWT
 * tokens to browser JavaScript.  It provides:
 *
 * - `getAccessTokenWithFallback()`, returns the sentinel
 *   `COOKIE_SESSION_BEARER` ("__cookie_session__") when a valid server
 *   session exists, or `null` when it does not.  The BFF proxy strips
 *   the sentinel from outgoing `Authorization` headers and injects the
 *   real httpOnly cookie token before forwarding to the backend.
 *
 * - `ensureSession()`, asks the BFF to validate (and silently refresh)
 *   the current cookie-backed session.  Concurrent calls are deduplicated.
 *
 * - `broadcastLogout()`, signals other browser tabs to clear their
 *   in-memory auth state via a `StorageEvent` on `localStorage`.
 *
 * - `clearTokens()`, intentional no-op retained for call-site
 *   compatibility.  No token material exists in `localStorage`.
 */
export class TokenManager {
  private static sessionPromise: Promise<boolean> | null = null;

  /** @deprecated No-op, tokens live in httpOnly cookies, not localStorage. */
  static clearTokens(): void {
    // Intentional no-op.  Retained so existing call sites (AuthContext,
    // AuthService) compile without changes.  Real cookie cleanup happens
    // server-side via the BFF logout route.
  }

  /**
   * Returns the cookie-session sentinel when a valid server session
   * exists, or `null` when it does not.  Never returns real JWT material.
   */
  static async getAccessTokenWithFallback(): Promise<string | null> {
    const authenticated = await this.ensureSession();
    return authenticated ? COOKIE_SESSION_BEARER : null;
  }

  /**
   * Broadcasts a logout signal to other open tabs via `StorageEvent`.
   * The `AuthProvider` listens for this event and clears in-memory state.
   */
  static broadcastLogout(): void {
    if (typeof window === "undefined") return;

    localStorage.setItem("auth_logout", String(Date.now()));
    localStorage.removeItem("auth_logout");
  }

  /**
   * Validates (and silently refreshes) the cookie-backed session by
   * calling the BFF session endpoint.  Concurrent calls share a single
   * in-flight request.
   */
  static async ensureSession(force = false): Promise<boolean> {
    if (typeof window === "undefined") {
      return false;
    }

    if (force) {
      return this.fetchSessionState();
    }

    if (this.sessionPromise) {
      return this.sessionPromise;
    }

    this.sessionPromise = this.fetchSessionState();
    try {
      return await this.sessionPromise;
    } finally {
      this.sessionPromise = null;
    }
  }

  private static async fetchSessionState(): Promise<boolean> {
    try {
      const response = await fetch("/api/auth/session?ensure=1", {
        method: "GET",
        credentials: "include",
        cache: "no-store",
      });

      if (!response.ok) {
        return false;
      }

      const payload = (await response.json().catch(() => null)) as {
        authenticated?: boolean;
      } | null;

      return payload?.authenticated === true;
    } catch {
      return false;
    }
  }
}
