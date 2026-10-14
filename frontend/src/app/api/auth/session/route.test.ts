import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";

import { GET, POST } from "./route";

const createJwtWithExp = (exp: number, extraPayload: Record<string, unknown> = {}): string => {
  const header = Buffer.from(JSON.stringify({ alg: "none", typ: "JWT" })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({ exp, ...extraPayload })).toString("base64url");
  return `${header}.${payload}.`;
};

describe("/api/auth/session route", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("returns authenticated status from cookies without exposing tokens", async () => {
    const request = new NextRequest("http://localhost/api/auth/session", {
      headers: {
        cookie: "auth_token=access-1; auth_refresh_token=refresh-1",
      },
    });

    const response = await GET(request);
    const payload = await response.json();

    expect(payload).toEqual({
      authenticated: true,
    });
  });

  it("refreshes the cookie-backed session when ensure=1 is requested", async () => {
    const nowSeconds = Math.floor(Date.now() / 1000);
    const expiredAccessToken = createJwtWithExp(nowSeconds - 60);
    const refreshToken = createJwtWithExp(nowSeconds + 600);
    const freshAccessToken = createJwtWithExp(nowSeconds + 900);
    const freshRefreshToken = createJwtWithExp(nowSeconds + 1800, { remember_me: true });

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            access_token: freshAccessToken,
            refresh_token: freshRefreshToken,
          }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        )
      )
    );

    const request = new NextRequest("http://localhost/api/auth/session?ensure=1", {
      headers: {
        cookie: `auth_token=${expiredAccessToken}; auth_refresh_token=${refreshToken}`,
      },
    });

    const response = await GET(request);
    const payload = await response.json();

    expect(payload).toEqual({ authenticated: true });
    const setCookieHeader = response.headers.get("set-cookie") ?? "";
    expect(setCookieHeader).toContain(`auth_token=${freshAccessToken}`);
    expect(setCookieHeader).toContain(`auth_refresh_token=${freshRefreshToken}`);
  });

  it("sets httpOnly auth cookies when posting valid SSO tokens", async () => {
    const request = new NextRequest("http://localhost/api/auth/session", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({
        access_token: "access-token",
        refresh_token: "refresh-token",
      }),
    });

    const response = await POST(request);
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ authenticated: true });

    const setCookieHeader = response.headers.get("set-cookie") ?? "";
    expect(setCookieHeader).toContain("auth_token=access-token");
    expect(setCookieHeader).toContain("auth_refresh_token=refresh-token");
    expect(setCookieHeader).toContain("HttpOnly");
  });

  it("rejects malformed SSO token payloads", async () => {
    const request = new NextRequest("http://localhost/api/auth/session", {
      method: "POST",
      headers: {
        "content-type": "application/json",
      },
      body: JSON.stringify({ access_token: "access-only" }),
    });

    const response = await POST(request);
    expect(response.status).toBe(400);
  });
});
