import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AUTH_REDIRECT_PARAM } from "@/constants/auth";

import { config, middleware } from "@/middleware";

const createJwt = (payload: Record<string, unknown>) => {
  const encode = (value: Record<string, unknown>) =>
    Buffer.from(JSON.stringify(value)).toString("base64url");

  return `${encode({ alg: "none", typ: "JWT" })}.${encode(payload)}.signature`;
};

const createRequest = (
  pathname: string,
  token?: string,
  refreshToken?: string,
  // SIGV2-1304: what the browser says the request is for. A real navigation
  // is "document"; a prefetch or an RSC fetch is "empty".
  fetchDest?: string
) => {
  const headers = new Headers();

  const cookiePairs = [
    token ? `auth_token=${token}` : null,
    refreshToken ? `auth_refresh_token=${refreshToken}` : null,
  ].filter(Boolean);

  if (cookiePairs.length > 0) {
    headers.set("cookie", cookiePairs.join("; "));
  }
  if (fetchDest) {
    headers.set("sec-fetch-dest", fetchDest);
  }

  return new NextRequest(`http://localhost${pathname}`, { headers });
};

describe("middleware route matching", () => {
  it("redirects unauthenticated users from /dashboard to /login", async () => {
    const response = await middleware(createRequest("/dashboard"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      `http://localhost/login?${AUTH_REDIRECT_PARAM}=%2Fdashboard`
    );
  });

  it("redirects unauthenticated users from nested dashboard paths", async () => {
    const response = await middleware(createRequest("/dashboard/account-settings"));

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      `http://localhost/login?${AUTH_REDIRECT_PARAM}=%2Fdashboard%2Faccount-settings`
    );
  });

  it("allows /api/* requests to pass through", async () => {
    const response = await middleware(createRequest("/api/health"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("treats / as exact-only public route", async () => {
    const response = await middleware(createRequest("/"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows exact /pricing public route without redirect", async () => {
    const response = await middleware(createRequest("/pricing"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows exact /volatility public route without redirect", async () => {
    const response = await middleware(createRequest("/volatility"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows /blog public route without redirect", async () => {
    const response = await middleware(createRequest("/blog"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows nested /blog paths without redirect", async () => {
    const response = await middleware(createRequest("/blog/example-post"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows /case-studies public route without redirect", async () => {
    const response = await middleware(createRequest("/case-studies"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows nested /case-studies paths without redirect", async () => {
    const response = await middleware(createRequest("/case-studies/example-slug"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("allows magic-link connect routes without redirect", async () => {
    const response = await middleware(createRequest("/connect/magic-token-42"));

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("redirects authenticated users from /login to /dashboard", async () => {
    const response = await middleware(
      createRequest("/login", createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 3600 }))
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/dashboard");
  });

  it("allows /login?session_expired=true with stale cookies and clears auth cookies", async () => {
    const response = await middleware(createRequest("/login?session_expired=true", "stale-token"));

    expect(response.status).toBe(200);
    expect(response.headers.get("location")).toBeNull();
    expect(response.headers.get("set-cookie")).toContain("auth_token=;");
    expect(response.headers.get("set-cookie")).toContain("auth_refresh_token=;");
  });

  it("redirects authenticated users from landing page to /dashboard", async () => {
    const response = await middleware(
      createRequest("/", createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 3600 }))
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost/dashboard");
  });

  it("does not trust portal_only claim for middleware redirects", async () => {
    const response = await middleware(
      createRequest(
        "/portal/projects/42",
        createJwt({ sub: "1", portal_only: false, exp: Math.floor(Date.now() / 1000) + 3600 })
      )
    );

    expect(response.status).toBe(200);
    expect(response.headers.get("x-middleware-next")).toBe("1");
  });

  it("treats expired jwt as unauthenticated", async () => {
    const response = await middleware(
      createRequest(
        "/dashboard/reports",
        createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) - 10 })
      )
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toContain("/login");
  });

  // SIGNAL-1005: an expired access token with a still-valid refresh token
  // must silently refresh on a hard navigation instead of force-logging the
  // user out and destroying the refresh token too.
  describe("expired access token with a valid refresh token", () => {
    afterEach(() => {
      vi.unstubAllGlobals();
    });

    const expiredAccessToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) - 10 });
    const validRefreshToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 600 });

    it("silently refreshes and lets the request through instead of redirecting to /login", async () => {
      const freshAccessToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 900 });
      const freshRefreshToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 1800 });

      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(
              JSON.stringify({ access_token: freshAccessToken, refresh_token: freshRefreshToken }),
              { status: 200, headers: { "Content-Type": "application/json" } }
            )
          )
      );

      const response = await middleware(
        createRequest("/dashboard/reports", expiredAccessToken, validRefreshToken)
      );

      expect(response.status).toBe(200);
      expect(response.headers.get("location")).toBeNull();
      const setCookieHeader = response.headers.get("set-cookie") ?? "";
      expect(setCookieHeader).toContain(`auth_token=${freshAccessToken}`);
      expect(setCookieHeader).toContain(`auth_refresh_token=${freshRefreshToken}`);
    });

    // SIGV2-1304 ------------------------------------------------------------
    // QA: "After Free to Standard, Billing showed 'Session has been revoked'
    // and Unavailable. A later login loaded Standard / active."
    //
    // `/auth/refresh` rotates, deactivating the session it was given, so a
    // second request carrying the same refresh token is rejected and the
    // cookies are cleared. The client is safe, TokenManager shares one
    // in-flight promise. This path runs once per request, and Next prefetches
    // several routes at once, each arriving with the same not-yet-rotated
    // cookie. Returning from Stripe is the worst case: a navigation whose
    // access token expired on the checkout page, landing somewhere whose links
    // are prefetched at once.
    it("does not rotate the session for a prefetch", async () => {
      const refreshCall = vi.fn();
      vi.stubGlobal("fetch", refreshCall);

      const response = await middleware(
        createRequest("/dashboard/billing", expiredAccessToken, validRefreshToken, "empty")
      );

      // Nothing was refreshed, so nothing was rotated out from under the
      // navigation that is about to arrive.
      expect(refreshCall).not.toHaveBeenCalled();
      expect(response.headers.get("location")).toContain("/login");
    });

    it("still refreshes for a real navigation", async () => {
      const freshAccessToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 900 });
      const freshRefreshToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 1800 });
      const refreshCall = vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ access_token: freshAccessToken, refresh_token: freshRefreshToken }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      vi.stubGlobal("fetch", refreshCall);

      const response = await middleware(
        createRequest("/dashboard/billing", expiredAccessToken, validRefreshToken, "document")
      );

      expect(refreshCall).toHaveBeenCalledTimes(1);
      expect(response.status).toBe(200);
      expect(response.headers.get("set-cookie") ?? "").toContain(`auth_token=${freshAccessToken}`);
    });

    it("still refreshes when the browser sends no Sec-Fetch-Dest at all", async () => {
      // Older clients and non-browser agents omit it. Treating an absent
      // header as "not a navigation" would lock those out of the silent
      // refresh this path exists for.
      const freshAccessToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 900 });
      const freshRefreshToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) + 1800 });
      const refreshCall = vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ access_token: freshAccessToken, refresh_token: freshRefreshToken }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          )
        );
      vi.stubGlobal("fetch", refreshCall);

      const response = await middleware(
        createRequest("/dashboard/billing", expiredAccessToken, validRefreshToken)
      );

      expect(refreshCall).toHaveBeenCalledTimes(1);
      expect(response.status).toBe(200);
    });

    it("falls back to redirecting to /login when the refresh token is itself rejected", async () => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(JSON.stringify({ detail: "Invalid refresh token" }), { status: 401 })
          )
      );

      const response = await middleware(
        createRequest("/dashboard/reports", expiredAccessToken, validRefreshToken)
      );

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });

    it("falls back to redirecting to /login when the refresh upstream is unreachable", async () => {
      vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

      const response = await middleware(
        createRequest("/dashboard/reports", expiredAccessToken, validRefreshToken)
      );

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });

    it("does not attempt a refresh when the refresh token is also expired", async () => {
      const fetchSpy = vi.fn();
      vi.stubGlobal("fetch", fetchSpy);
      const expiredRefreshToken = createJwt({ sub: "1", exp: Math.floor(Date.now() / 1000) - 10 });

      const response = await middleware(
        createRequest("/dashboard/reports", expiredAccessToken, expiredRefreshToken)
      );

      expect(fetchSpy).not.toHaveBeenCalled();
      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });
  });

  describe("malformed tokens", () => {
    it("redirects users with 'undefined' token to login", async () => {
      const response = await middleware(createRequest("/dashboard", "undefined"));

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });

    it("redirects users with 'null' token to login", async () => {
      const response = await middleware(createRequest("/dashboard", "null"));

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });

    it("redirects users with empty string token to login", async () => {
      const response = await middleware(createRequest("/dashboard", " "));

      expect(response.status).toBe(307);
      expect(response.headers.get("location")).toContain("/login");
    });
  });

  it("uses a matcher that excludes api/auth handlers, next internals, and static assets", () => {
    expect(config.matcher).toEqual([
      "/",
      "/((?!api|_next/static|_next/image|_next/data|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico|css|js|json|webmanifest|map|txt|xml)$).*)",
    ]);
  });

  it("keeps protected app paths guarded while excluded paths pass through", async () => {
    const excludedApiAuth = await middleware(createRequest("/api/auth/session"));
    expect(excludedApiAuth.status).toBe(200);
    expect(excludedApiAuth.headers.get("x-middleware-next")).toBe("1");

    const protectedAppPath = await middleware(createRequest("/dashboard/reports"));
    expect(protectedAppPath.status).toBe(307);
    expect(protectedAppPath.headers.get("location")).toBe(
      `http://localhost/login?${AUTH_REDIRECT_PARAM}=%2Fdashboard%2Freports`
    );
  });
});
