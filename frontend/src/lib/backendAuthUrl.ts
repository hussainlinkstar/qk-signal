import { BASE_PATH } from "@/lib/basePath";

/**
 * Absolute URL for a backend `/api/v1/auth/...` route the browser navigates to
 * directly, rather than through the BFF proxy.
 *
 * These legs must share the browser origin: Caddy routes `/api/v1/*` to the
 * backend, and the OAuth session cookie plus the provider's registered redirect
 * URIs all depend on origin and path matching. Local development is the one
 * exception, where the backend answers on port 8000.
 */
export function resolveBackendAuthUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;

  if (typeof window !== "undefined") {
    const hostname = window.location.hostname.trim().toLowerCase();
    const isLocalhost = hostname === "localhost" || hostname === "127.0.0.1";
    if (isLocalhost) {
      return new URL(`http://${hostname}:8000/api/v1${normalized}`).toString();
    }
    return new URL(`${window.location.origin}${BASE_PATH}/api/v1${normalized}`).toString();
  }

  return new URL(`http://localhost:8000/api/v1${normalized}`).toString();
}
