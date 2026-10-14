import { NextRequest, NextResponse } from "next/server";

import { getTokenMaxAgeSeconds, isUsableToken, shouldPersistCookies } from "@/lib/auth-session";

const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
const apiPrefix = "/api/v1";

type TokenPayload = {
  access_token: string;
  refresh_token: string;
};

function secureCookieOptions(maxAge?: number) {
  const secure = process.env.NODE_ENV === "production";
  return {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    secure,
    ...(typeof maxAge === "number" ? { maxAge } : {}),
  };
}

export function buildAuthUrl(path: string): URL {
  const base = backendUrl.endsWith("/") ? backendUrl : `${backendUrl}/`;
  return new URL(`${apiPrefix}${path}`.replace(/^\//, ""), base);
}

export function isTokenPayload(value: unknown): value is TokenPayload {
  if (!value || typeof value !== "object") {
    return false;
  }

  const payload = value as Record<string, unknown>;
  return (
    typeof payload.access_token === "string" &&
    isUsableToken(payload.access_token) &&
    typeof payload.refresh_token === "string" &&
    isUsableToken(payload.refresh_token)
  );
}

export function applyAuthCookies(
  response: NextResponse,
  accessToken: string,
  refreshToken: string
): void {
  const rememberMe = shouldPersistCookies(refreshToken);
  const accessTokenMaxAge = getTokenMaxAgeSeconds(accessToken);
  const refreshTokenMaxAge = getTokenMaxAgeSeconds(refreshToken);

  response.cookies.set(
    "auth_token",
    accessToken,
    secureCookieOptions(rememberMe ? accessTokenMaxAge : undefined)
  );
  response.cookies.set(
    "auth_refresh_token",
    refreshToken,
    secureCookieOptions(rememberMe ? refreshTokenMaxAge : undefined)
  );
}

export function clearAuthCookies(response: NextResponse): void {
  const secure = process.env.NODE_ENV === "production";
  const options = {
    httpOnly: true,
    sameSite: "lax" as const,
    path: "/",
    secure,
    maxAge: 0,
    expires: new Date(0),
  };

  response.cookies.set("auth_token", "", options);
  response.cookies.set("auth_refresh_token", "", options);
}

function buildForwardHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  headers.delete("host");
  return headers;
}

export async function forwardAuthExchange(
  request: NextRequest,
  upstreamPath: string,
  options: { expectTokenPayload?: boolean } = {}
): Promise<NextResponse> {
  const { expectTokenPayload = true } = options;
  const targetUrl = buildAuthUrl(upstreamPath);
  const headers = buildForwardHeaders(request);

  try {
    const body =
      request.method === "GET" || request.method === "HEAD" ? undefined : await request.text();
    const upstreamResponse = await fetch(targetUrl, {
      method: request.method,
      headers,
      ...(body !== undefined ? { body } : {}),
      redirect: "manual",
    });

    const data = await upstreamResponse.json().catch(() => null);
    if (!upstreamResponse.ok) {
      return NextResponse.json(data ?? { detail: "Authentication failed" }, {
        status: upstreamResponse.status,
      });
    }

    if (!expectTokenPayload) {
      return NextResponse.json(data ?? {}, { status: upstreamResponse.status });
    }

    if (!isTokenPayload(data)) {
      return NextResponse.json(
        { detail: "Invalid auth token payload from upstream" },
        { status: 502 }
      );
    }

    const response = NextResponse.json(
      { authenticated: true },
      { status: upstreamResponse.status }
    );
    applyAuthCookies(response, data.access_token, data.refresh_token);
    return response;
  } catch {
    return NextResponse.json({ detail: "Auth upstream unreachable" }, { status: 502 });
  }
}

export async function refreshSessionFromCookie(refreshToken: string): Promise<NextResponse> {
  try {
    const upstreamResponse = await fetch(buildAuthUrl("/auth/refresh"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        accept: "application/json",
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
      redirect: "manual",
    });

    const data = await upstreamResponse.json().catch(() => null);
    if (!upstreamResponse.ok) {
      const response = NextResponse.json({ authenticated: false }, { status: 200 });
      if (upstreamResponse.status === 401 || upstreamResponse.status === 403) {
        clearAuthCookies(response);
      }
      return response;
    }

    if (!isTokenPayload(data)) {
      const response = NextResponse.json({ authenticated: false }, { status: 502 });
      clearAuthCookies(response);
      return response;
    }

    const response = NextResponse.json({ authenticated: true }, { status: 200 });
    applyAuthCookies(response, data.access_token, data.refresh_token);
    return response;
  } catch {
    return NextResponse.json({ detail: "Auth upstream unreachable" }, { status: 502 });
  }
}
