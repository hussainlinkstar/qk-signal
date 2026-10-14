import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchRecommendationDecisions, recordRecommendationDecision } from "./learningsService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchRecommendationDecisions", () => {
  it("loads project-scoped decisions via the proxy endpoint", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("/api/projects/7/recommendation-decisions");
      return {
        ok: true,
        status: 200,
        json: async () => [
          {
            id: 1,
            project_id: 7,
            action_fingerprint: "abc123",
            action_label: "Add FAQPage schema",
            decision: "dismissed",
            note: null,
            decided_by: 4,
            created_at: "2026-04-22T09:00:00Z",
          },
        ],
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await fetchRecommendationDecisions(7, { Authorization: "Bearer token" });

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: 1,
      decision: "dismissed",
      action_fingerprint: "abc123",
      action_label: "Add FAQPage schema",
    });
  });

  it("surfaces an error status as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 403,
      json: async () => ({ detail: "Forbidden." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchRecommendationDecisions(7, {})).rejects.toMatchObject({ status: 403 });
  });
});

describe("recordRecommendationDecision", () => {
  it("posts action_text + decision to the decisions endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/projects/9/recommendation-decisions");
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({ action_text: "Add structured FAQ markup.", decision: "dismissed" })
        );
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 5,
            project_id: 9,
            action_fingerprint: "deadbeef",
            decision: "dismissed",
            note: null,
            decided_by: 2,
            created_at: "2026-04-22T10:00:00Z",
          }),
        };
      });
    vi.stubGlobal("fetch", fetchMock);

    const created = await recordRecommendationDecision(
      9,
      { action_text: "Add structured FAQ markup.", decision: "dismissed" },
      { Authorization: "Bearer token" }
    );

    expect(created).toMatchObject({ id: 5, decision: "dismissed" });
  });
});
