import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchAdvisorPlanProgress } from "./planProgressService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchAdvisorPlanProgress", () => {
  it("loads project-scoped plan progress via the proxy endpoint", async () => {
    const payload = {
      latest_summary: { total_actions: 8, high_impact: 2, medium_impact: 4, low_impact: 2 },
      first_summary: { total_actions: 14, high_impact: 6, medium_impact: 5, low_impact: 3 },
      trend: [
        { created_at: "2026-01-04T09:00:00Z", total_actions: 14, high_impact: 6 },
        { created_at: "2026-02-04T09:00:00Z", total_actions: 8, high_impact: 2 },
      ],
      latest_delta: {
        actions_added: [],
        actions_resolved: [
          {
            fingerprint: "abc123",
            action: "Add FAQ schema to pricing page",
            title: null,
            impact: "high",
            effort: "low",
            rank: 1,
          },
        ],
        actions_carried: [],
        impact_delta: { total_actions: -6, high_impact: -4, medium_impact: -1, low_impact: -1 },
        summary_prev: { total_actions: 14, high_impact: 6, medium_impact: 5, low_impact: 3 },
        summary_curr: { total_actions: 8, high_impact: 2, medium_impact: 4, low_impact: 2 },
      },
    };

    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("/api/projects/7/advisor-plan-progress");
      return {
        ok: true,
        status: 200,
        json: async () => payload,
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAdvisorPlanProgress(7, { Authorization: "Bearer token" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.trend).toHaveLength(2);
    expect(result.latest_delta?.actions_resolved).toHaveLength(1);
    expect(result.latest_delta?.impact_delta.high_impact).toBe(-4);
  });

  it("returns an empty-but-valid shape for a project with no history", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        latest_summary: null,
        first_summary: null,
        trend: [],
        latest_delta: null,
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAdvisorPlanProgress("3", {});

    expect(result.trend).toEqual([]);
    expect(result.latest_delta).toBeNull();
  });

  it("surfaces a 402 plan-gate as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: "Advisor-plan progress is available on Executive." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAdvisorPlanProgress(7, {})).rejects.toMatchObject({ status: 402 });
  });
});
