import { beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { POST } from "./route";

describe("/api/auth/logout route", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("forwards logout to upstream when auth token cookie exists", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const request = new NextRequest("http://localhost/api/auth/logout", {
      method: "POST",
      headers: {
        cookie: "auth_token=test-token; auth_refresh_token=refresh-token",
      },
    });

    await POST(request);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [targetUrl, options] = fetchMock.mock.calls[0];
    const forwardedHeaders = new Headers(options?.headers);
    expect(String(targetUrl)).toContain("/api/v1/auth/logout");
    expect(options?.method).toBe("POST");
    expect(forwardedHeaders.get("Authorization")).toBe("Bearer test-token");
    expect(forwardedHeaders.get("Content-Type")).toBe("application/json");
    expect(options?.body).toBe(JSON.stringify({ refresh_token: "refresh-token" }));
  });

  it("always clears auth cookies even if upstream logout fails", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("upstream unavailable"));
    vi.stubGlobal("fetch", fetchMock);

    const request = new NextRequest("http://localhost/api/auth/logout", {
      method: "POST",
      headers: {
        cookie: "auth_token=test-token; auth_refresh_token=refresh-token",
      },
    });

    const response = await POST(request);

    expect(response.status).toBe(200);
    const setCookieHeader = response.headers.get("set-cookie") ?? "";
    expect(setCookieHeader).toContain("auth_token=");
    expect(setCookieHeader).toContain("auth_refresh_token=");
    expect(setCookieHeader).toContain("Max-Age=0");
  });
});
