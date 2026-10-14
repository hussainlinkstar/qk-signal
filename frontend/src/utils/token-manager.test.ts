import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { COOKIE_SESSION_BEARER } from "@/lib/auth-session";
import { TokenManager } from "@/utils/token-manager";

describe("TokenManager BFF session contract", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("returns the cookie-session sentinel when the server confirms an authenticated session", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          authenticated: true,
        }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    await expect(TokenManager.getAccessTokenWithFallback()).resolves.toBe(COOKIE_SESSION_BEARER);

    expect(fetchMock).toHaveBeenCalledWith("/api/auth/session?ensure=1", {
      method: "GET",
      credentials: "include",
      cache: "no-store",
    });
  });

  it("returns null when the server session cannot be ensured", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(TokenManager.getAccessTokenWithFallback()).resolves.toBeNull();
  });

  it("returns null when the session endpoint returns a non-ok status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 502 }));

    await expect(TokenManager.getAccessTokenWithFallback()).resolves.toBeNull();
  });

  it("returns null when the session endpoint throws a network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));

    await expect(TokenManager.getAccessTokenWithFallback()).resolves.toBeNull();
  });

  it("deduplicates concurrent ensureSession calls into a single fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const results = await Promise.all([
      TokenManager.ensureSession(),
      TokenManager.ensureSession(),
      TokenManager.ensureSession(),
    ]);

    expect(results).toEqual([true, true, true]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("force=true bypasses the deduplication cache", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ authenticated: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await TokenManager.ensureSession(true);
    await TokenManager.ensureSession(true);

    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("broadcasts logout without persisting any token material", () => {
    TokenManager.broadcastLogout();

    expect(localStorage.getItem("auth_logout")).toBeNull();
    expect(localStorage.getItem("auth_access_token")).toBeNull();
    expect(localStorage.getItem("auth_refresh_token")).toBeNull();
  });

  it("clearTokens is a no-op and does not throw", () => {
    localStorage.setItem("stale_key", "value");

    TokenManager.clearTokens();

    expect(localStorage.getItem("stale_key")).toBe("value");
  });
});
