import { NextRequest, NextResponse } from "next/server";
import {
  sanitizeSystemStatusPayload,
  type StatusAudience,
  type SystemStatusPayload,
} from "@/lib/system-status";
import { isCookieSessionBearer } from "@/lib/auth-session";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const backendApiPrefix = "/api/v1";
const defaultTimeoutMs = getTimeoutFromEnv("PROXY_SHORT_TIMEOUT_MS", 5000);
const encoder = new TextEncoder();

type LoadStatusOptions = {
  path: string;
  audience: StatusAudience;
  token?: string;
  timeoutMs?: number;
  forwardSearchParams?: boolean;
};

type LoadStatusResult =
  | { ok: true; payload: SystemStatusPayload }
  | { ok: false; response: NextResponse };

type StreamStatusOptions = {
  path: string;
  audience: StatusAudience;
  token?: string;
  pollIntervalMs?: number;
};

type AdminTokenResult = { ok: true; token: string } | { ok: false; response: NextResponse };

function getTimeoutFromEnv(envKey: string, fallbackMs: number) {
  const rawValue = process.env[envKey];
  const parsed = rawValue ? Number(rawValue) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallbackMs;
}

function isMalformedToken(token?: string): boolean {
  if (!token) {
    return true;
  }
  const trimmed = token.trim();
  return trimmed.length === 0 || trimmed === "undefined" || trimmed === "null";
}

function buildUpstreamUrl(path: string, request?: NextRequest): URL {
  const base = backendUrl.endsWith("/") ? backendUrl : `${backendUrl}/`;
  const normalizedPath = path.startsWith(backendApiPrefix)
    ? path
    : `${backendApiPrefix}${path.startsWith("/") ? "" : "/"}${path}`;
  const url = new URL(normalizedPath.replace(/^\//, ""), base);
  if (request) {
    url.search = request.nextUrl.search;
  }
  return url;
}

async function fetchWithTimeout(
  input: URL,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

async function parseUpstreamError(response: Response): Promise<Record<string, unknown>> {
  const fallback = { detail: "Unable to fetch system status." };
  try {
    const parsed = (await response.json()) as Record<string, unknown>;
    return parsed && typeof parsed === "object" ? parsed : fallback;
  } catch {
    return fallback;
  }
}

export const getRequestToken = (request: NextRequest): string | undefined => {
  const authHeader = request.headers.get("authorization");
  if (authHeader) {
    const [scheme, token] = authHeader.split(" ");
    if (
      scheme?.toLowerCase() === "bearer" &&
      !isMalformedToken(token) &&
      !isCookieSessionBearer(token)
    ) {
      return token.trim();
    }
  }

  const cookieToken = request.cookies.get("auth_token")?.value;
  return isMalformedToken(cookieToken) ? undefined : cookieToken?.trim();
};

const STAFF_ROLES = new Set(["admin", "moderator"]);

async function isStaffToken(token: string): Promise<boolean> {
  const meUrl = buildUpstreamUrl("/users/me");
  const response = await fetchWithTimeout(
    meUrl,
    {
      method: "GET",
      headers: {
        accept: "application/json",
        authorization: `Bearer ${token}`,
      },
      cache: "no-store",
      redirect: "manual",
    },
    defaultTimeoutMs
  ).catch(() => null);

  if (!response?.ok) {
    return false;
  }

  const payload = (await response.json().catch(() => null)) as { role?: string } | null;
  return STAFF_ROLES.has(payload?.role ?? "");
}

export async function requireAdminToken(request: NextRequest): Promise<AdminTokenResult> {
  const token = getRequestToken(request);
  if (!token) {
    return {
      ok: false,
      response: NextResponse.json({ detail: "Authentication required." }, { status: 401 }),
    };
  }

  const isAdmin = await isStaffToken(token);
  if (!isAdmin) {
    return {
      ok: false,
      response: NextResponse.json({ detail: "Admin access required." }, { status: 403 }),
    };
  }

  return { ok: true, token };
}

export async function loadSanitizedStatusPayload(
  request: NextRequest,
  options: LoadStatusOptions
): Promise<LoadStatusResult> {
  const {
    path,
    audience,
    token,
    timeoutMs = defaultTimeoutMs,
    forwardSearchParams = true,
  } = options;

  const upstreamUrl = buildUpstreamUrl(path, forwardSearchParams ? request : undefined);
  const headers = new Headers();
  headers.set("accept", "application/json");
  if (token) {
    headers.set("authorization", `Bearer ${token}`);
  }

  let upstreamResponse: Response;
  try {
    upstreamResponse = await fetchWithTimeout(
      upstreamUrl,
      {
        method: "GET",
        headers,
        cache: "no-store",
        redirect: "manual",
      },
      timeoutMs
    );
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AbortError"
        ? "Upstream timeout."
        : "Upstream unreachable.";
    return {
      ok: false,
      response: NextResponse.json({ detail: message }, { status: 502 }),
    };
  }

  if (!upstreamResponse.ok) {
    const payload = await parseUpstreamError(upstreamResponse);
    return {
      ok: false,
      response: NextResponse.json(payload, { status: upstreamResponse.status }),
    };
  }

  const upstreamPayload = await upstreamResponse.json().catch(() => null);
  if (!upstreamPayload || typeof upstreamPayload !== "object") {
    return {
      ok: false,
      response: NextResponse.json({ detail: "Invalid upstream payload." }, { status: 502 }),
    };
  }

  return {
    ok: true,
    payload: sanitizeSystemStatusPayload(upstreamPayload, audience),
  };
}

function encodeData(payload: SystemStatusPayload): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(payload)}\n\n`);
}

function encodeError(message: string): Uint8Array {
  return encoder.encode(`event: status_error\ndata: ${JSON.stringify({ message })}\n\n`);
}

function encodePing(): Uint8Array {
  return encoder.encode(": ping\n\n");
}

export function createStatusStreamResponse(
  request: NextRequest,
  options: StreamStatusOptions
): Response {
  const { path, audience, token, pollIntervalMs = 15000 } = options;

  let pollInterval: ReturnType<typeof setInterval> | undefined;
  let keepAliveInterval: ReturnType<typeof setInterval> | undefined;
  let isClosed = false;

  const closeStream = (controller: ReadableStreamDefaultController<Uint8Array>) => {
    if (isClosed) {
      return;
    }
    isClosed = true;
    if (pollInterval) {
      clearInterval(pollInterval);
    }
    if (keepAliveInterval) {
      clearInterval(keepAliveInterval);
    }
    controller.close();
  };

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const pushStatus = async () => {
        const result = await loadSanitizedStatusPayload(request, {
          path,
          audience,
          token,
          forwardSearchParams: false,
        });
        if (isClosed) {
          return;
        }

        if ("response" in result) {
          let message = "Unable to fetch live status.";
          try {
            const payload = (await result.response.json()) as { detail?: string; message?: string };
            message = payload.detail ?? payload.message ?? message;
          } catch {
            // Ignore JSON parse errors and use fallback message.
          }

          controller.enqueue(encodeError(message));
          if (result.response.status === 401 || result.response.status === 403) {
            closeStream(controller);
          }
          return;
        }

        controller.enqueue(encodeData(result.payload));
      };

      void pushStatus();
      pollInterval = setInterval(() => {
        void pushStatus();
      }, pollIntervalMs);

      keepAliveInterval = setInterval(() => {
        controller.enqueue(encodePing());
      }, 20000);

      request.signal.addEventListener("abort", () => {
        closeStream(controller);
      });
    },
    cancel() {
      isClosed = true;
      if (pollInterval) {
        clearInterval(pollInterval);
      }
      if (keepAliveInterval) {
        clearInterval(keepAliveInterval);
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
