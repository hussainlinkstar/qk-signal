import { cookies, headers as nextHeaders } from "next/headers";
import { redirect } from "next/navigation";
import {
  MOCK_PREVIEW_USER,
  isMockPreviewEnabled,
  isMockPreviewToken,
  isMockUserPath,
} from "@/lib/mockPreviewAuth";

const API_PREFIX = "/api/v1";
const DEFAULT_TIMEOUT_MS = getTimeoutFromEnv("PROXY_SHORT_TIMEOUT_MS", 5000);
export const SESSION_EXPIRED_REDIRECT_PATH = "/login?session_expired=true";

export type ServerFetchOptions = Omit<RequestInit, "headers"> & {
  headers?: HeadersInit;
  redirectOnUnauthorized?: boolean;
};

type FetchTarget = {
  url: URL;
  label: "primary" | "fallback";
};

function getTimeoutFromEnv(envKey: string, fallbackMs: number) {
  const rawValue = process.env[envKey];
  const parsed = rawValue ? Number(rawValue) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallbackMs;
}

function getBackendBaseUrl() {
  const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
  return backendUrl.endsWith("/") ? backendUrl : `${backendUrl}/`;
}

function buildBackendUrl(path: string) {
  const normalizedPath = path.startsWith(API_PREFIX)
    ? path
    : `${API_PREFIX}${path.startsWith("/") ? "" : "/"}${path}`;

  return new URL(normalizedPath.replace(/^\//, ""), getBackendBaseUrl());
}

function buildFetchTargets(path: string): FetchTarget[] {
  const primaryUrl = buildBackendUrl(path);
  const targets: FetchTarget[] = [{ url: primaryUrl, label: "primary" }];

  if (primaryUrl.hostname === "backend") {
    const fallbackUrl = new URL(primaryUrl.toString());
    fallbackUrl.hostname = "localhost";
    targets.push({ url: fallbackUrl, label: "fallback" });
  }

  return targets;
}

async function buildServerHeaders(headers?: HeadersInit) {
  const cookieStore = await cookies();
  const headerStore = await nextHeaders();
  const token = cookieStore.get("auth_token")?.value;
  const host = headerStore.get("host");

  const merged = new Headers(headers);
  merged.set("Accept", "application/json");
  if (host && !merged.has("x-forwarded-host")) {
    merged.set("x-forwarded-host", host);
  }

  if (token && token !== "undefined" && token !== "null") {
    merged.set("Authorization", `Bearer ${token}`);
  }

  return merged;
}

async function fetchWithTimeout(
  input: URL,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(input, {
      ...init,
      signal: controller.signal,
    });
  } finally {
    clearTimeout(timeoutId);
  }
}

function buildUpstreamErrorResponse(targetUrl: URL, timeoutMs: number, error: unknown): Response {
  const detail =
    error instanceof Error && error.name === "AbortError"
      ? `Upstream timeout after ${timeoutMs}ms.`
      : "Upstream unreachable.";

  console.error("Server fetch failed", {
    targetUrl: targetUrl.toString(),
    error: error instanceof Error ? error.message : String(error),
  });

  return new Response(
    JSON.stringify({
      error: "upstream_unreachable",
      upstream: targetUrl.origin,
      detail,
    }),
    {
      status: 502,
      headers: {
        "content-type": "application/json",
      },
    }
  );
}

/**
 * App Router server module helper.
 *
 * Usage in a server component/layout/page:
 * ```ts
 * import { serverFetch } from "@/utils/server-fetch";
 *
 * const response = await serverFetch("/users/me", { cache: "no-store" });
 * const data = await response.json();
 * ```
 */
export async function serverFetch(path: string, options: ServerFetchOptions = {}) {
  const { headers, redirectOnUnauthorized = true, ...init } = options;

  if (isMockPreviewEnabled() && isMockUserPath(path)) {
    const cookieStore = await cookies();
    const token = cookieStore.get("auth_token")?.value;
    if (isMockPreviewToken(token)) {
      return new Response(JSON.stringify(MOCK_PREVIEW_USER), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
    }
  }

  const requestInit: RequestInit = {
    ...init,
    headers: await buildServerHeaders(headers),
  };
  const targets = buildFetchTargets(path);
  const primaryTarget = targets[0];
  let lastError: unknown = null;
  let response: Response | null = null;

  for (const target of targets) {
    try {
      response = await fetchWithTimeout(target.url, requestInit, DEFAULT_TIMEOUT_MS);
      if (target.label === "fallback") {
        console.warn("Server fetch fallback upstream used", {
          targetUrl: target.url.toString(),
        });
      }
      break;
    } catch (error) {
      lastError = error;
      if (target.label === "fallback") {
        break;
      }
    }
  }

  if (!response) {
    response = buildUpstreamErrorResponse(primaryTarget.url, DEFAULT_TIMEOUT_MS, lastError);
  }

  if (response.status === 401 && redirectOnUnauthorized) {
    redirect(SESSION_EXPIRED_REDIRECT_PATH);
  }

  return response;
}
