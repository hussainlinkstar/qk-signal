import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchSiteTraffic } from "./monitoringService";

describe("fetchSiteTraffic", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("requests the contract endpoint with the window query", async () => {
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", availability: "available" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await fetchSiteTraffic(42, "90D", { Authorization: "Bearer t" });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [endpoint, init] = fetchSpy.mock.calls[0] ?? [];
    expect(endpoint).toBe("/api/v1/projects/42/monitoring/site-traffic?window=90D");
    expect(init?.method).toBe("GET");
    expect((init?.headers as Record<string, string>).Authorization).toBe("Bearer t");
  });

  it("returns the disconnected stub shape verbatim", async () => {
    vi.spyOn(global, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "disconnected", availability: "disconnected" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    const response = await fetchSiteTraffic(7, "7D", {});
    expect(response).toEqual({ status: "disconnected", availability: "disconnected" });
  });
});
