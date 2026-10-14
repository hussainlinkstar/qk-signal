import { beforeEach, describe, expect, it, vi } from "vitest";

const { cookiesMock, headersMock, redirectMock } = vi.hoisted(() => ({
  cookiesMock: vi.fn(),
  headersMock: vi.fn(),
  redirectMock: vi.fn(),
}));

vi.mock("next/headers", () => ({
  cookies: cookiesMock,
  headers: headersMock,
}));

vi.mock("next/navigation", () => ({
  redirect: redirectMock,
}));

import { SESSION_EXPIRED_REDIRECT_PATH, serverFetch } from "./server-fetch";

describe("serverFetch", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
    delete process.env.BACKEND_URL;
    delete process.env.PROXY_SHORT_TIMEOUT_MS;

    cookiesMock.mockResolvedValue({
      get: vi.fn().mockReturnValue({ value: "test-token" }),
    });
    headersMock.mockResolvedValue(
      new Headers({
        host: "app.thothgraph.local",
      })
    );
  });

  it("falls back to localhost when the internal backend hostname is unreachable", async () => {
    process.env.BACKEND_URL = "http://backend:8000";

    const fetchMock = vi
      .fn()
      .mockRejectedValueOnce(new Error("connect ECONNREFUSED 172.18.0.5:8000"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 1 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await serverFetch("/users/me", { cache: "no-store" });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://backend:8000/api/v1/users/me");
    expect(String(fetchMock.mock.calls[1][0])).toBe("http://localhost:8000/api/v1/users/me");

    const requestHeaders = new Headers(fetchMock.mock.calls[0][1]?.headers);
    expect(requestHeaders.get("accept")).toBe("application/json");
    expect(requestHeaders.get("authorization")).toBe("Bearer test-token");
    expect(response.status).toBe(200);
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("returns a 502 response instead of throwing when the backend is unreachable", async () => {
    process.env.BACKEND_URL = "http://localhost:8000";

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("connect ECONNREFUSED")));

    const response = await serverFetch("/users/me", {
      cache: "no-store",
      redirectOnUnauthorized: false,
    });

    expect(response.status).toBe(502);
    await expect(response.json()).resolves.toMatchObject({
      error: "upstream_unreachable",
      upstream: "http://localhost:8000",
      detail: "Upstream unreachable.",
    });
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("redirects to the session-expired login path on unauthorized responses", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 401 })));

    await serverFetch("/users/me", { cache: "no-store" });

    expect(redirectMock).toHaveBeenCalledWith(SESSION_EXPIRED_REDIRECT_PATH);
  });
});
