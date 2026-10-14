import { NextRequest, NextResponse } from "next/server";
import { isCookieSessionBearer } from "@/lib/auth-session";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const backendApiPrefix = "/api/v1";
const defaultTimeoutMs = getTimeoutFromEnv("PROXY_TIMEOUT_MS", 90000);
const shortTimeoutMs = getTimeoutFromEnv("PROXY_SHORT_TIMEOUT_MS", 5000);

type ProxyOptions = {
  timeoutMs?: number;
};

type FetchTarget = {
  url: URL;
  label: "primary" | "fallback";
};

function isGenerateComplexPath(path: string): boolean {
  return path === "/reports/generate-complex" || path === "/api/v1/reports/generate-complex";
}

function parseLogPayload(text: string): unknown {
  const trimmed = text.trim();
  if (!trimmed) {
    return null;
  }

  try {
    return JSON.parse(trimmed) as unknown;
  } catch {
    return trimmed;
  }
}

function decodeRequestBody(body: ArrayBuffer | undefined): unknown {
  if (!body || body.byteLength === 0) {
    return null;
  }
  return parseLogPayload(new TextDecoder().decode(body));
}

async function logGenerateComplexValidationFailure({
  path,
  request,
  response,
  targetUrl,
  body,
}: {
  path: string;
  request: NextRequest;
  response: Response;
  targetUrl: URL;
  body: ArrayBuffer | undefined;
}): Promise<void> {
  if (process.env.NODE_ENV === "production") {
    return;
  }
  if (response.status !== 422 || !isGenerateComplexPath(path)) {
    return;
  }

  let responseBody: unknown = null;
  try {
    responseBody = parseLogPayload(await response.clone().text());
  } catch {
    responseBody = null;
  }

  console.warn("BFF proxy generate-complex validation failure", {
    method: request.method,
    targetUrl: targetUrl.toString(),
    requestId: response.headers.get("x-request-id") ?? request.headers.get("x-request-id") ?? null,
    requestBody: decodeRequestBody(body),
    responseBody,
  });
}

function getTimeoutFromEnv(envKey: string, fallbackMs: number) {
  const rawValue = process.env[envKey];
  const parsed = rawValue ? Number(rawValue) : Number.NaN;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallbackMs;
}

export const PROXY_TIMEOUTS = {
  default: defaultTimeoutMs,
  short: shortTimeoutMs,
} as const;

export async function proxyRequest(request: NextRequest, path: string, options: ProxyOptions = {}) {
  const base = backendUrl.endsWith("/") ? backendUrl : `${backendUrl}/`;
  const normalizedPath = path.startsWith(backendApiPrefix)
    ? path
    : path.startsWith("/v1/")
      ? `/api${path}`
      : `${backendApiPrefix}${path.startsWith("/") ? "" : "/"}${path}`;
  const targetUrl = new URL(normalizedPath.replace(/^\//, ""), base);
  targetUrl.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  const originalHost = request.headers.get("host");
  headers.delete("host");
  if (originalHost) {
    headers.set("x-forwarded-host", originalHost);
  }
  const rawAuthorization = headers.get("authorization");
  if (rawAuthorization) {
    const [scheme, token] = rawAuthorization.split(" ");
    if (scheme?.toLowerCase() === "bearer" && isCookieSessionBearer(token)) {
      headers.delete("authorization");
    }
  }

  const hasAuthorization = headers.has("authorization");
  if (!hasAuthorization) {
    const cookieToken = request.cookies.get("auth_token")?.value;
    if (cookieToken) {
      headers.set("authorization", `Bearer ${cookieToken}`);
    }
  }

  const body =
    request.method === "GET" || request.method === "HEAD" ? undefined : await request.arrayBuffer();
  const init: RequestInit = {
    method: request.method,
    headers,
    body,
    redirect: "manual",
  };

  const controller = new AbortController();
  const timeoutMs = options.timeoutMs ?? defaultTimeoutMs;
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  init.signal = controller.signal;

  const targets: FetchTarget[] = [{ url: targetUrl, label: "primary" }];
  if (targetUrl.hostname === "backend") {
    const fallbackUrl = new URL(targetUrl.toString());
    fallbackUrl.hostname = "localhost";
    targets.push({ url: fallbackUrl, label: "fallback" });
  }

  try {
    let response: Response | null = null;

    for (const target of targets) {
      try {
        response = await fetch(target.url, init);
        if (target.label === "fallback") {
          console.warn("BFF proxy fallback upstream used", {
            method: request.method,
            targetUrl: target.url.toString(),
          });
        }
        break;
      } catch (error) {
        if (target.label === "fallback") {
          throw error;
        }
      }
    }

    if (!response) {
      throw new Error("proxy_request_failed");
    }

    const responseHeaders = new Headers(response.headers);

    await logGenerateComplexValidationFailure({
      path: normalizedPath,
      request,
      response,
      targetUrl,
      body,
    });

    // Node.js Headers can mangle Set-Cookie by joining multiple values with
    // ", " which browsers reject. Re-append individual cookie values so each
    // one becomes its own Set-Cookie header on the outgoing response.
    const setCookies =
      typeof response.headers.getSetCookie === "function" ? response.headers.getSetCookie() : [];
    if (setCookies.length > 0) {
      responseHeaders.delete("set-cookie");
      for (const cookie of setCookies) {
        responseHeaders.append("set-cookie", cookie);
      }
    }

    return new NextResponse(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch (err) {
    const errorMessage =
      err instanceof Error
        ? err.name === "AbortError"
          ? `timeout after ${timeoutMs}ms`
          : err.message
        : String(err);
    console.error("BFF proxy fetch failed", {
      method: request.method,
      targetUrl: targetUrl.toString(),
      error: errorMessage,
    });

    return NextResponse.json(
      {
        error: "upstream_unreachable",
        upstream: targetUrl.origin,
      },
      { status: 502 }
    );
  } finally {
    clearTimeout(timeoutId);
  }
}
