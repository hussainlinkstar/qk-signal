import { afterEach, describe, expect, it, vi } from "vitest";

import { createBrandFact, deleteBrandFact, fetchBrandFacts } from "./brandFactsService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchBrandFacts", () => {
  it("loads project-scoped brand facts via the proxy endpoint", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      expect(String(input)).toBe("/api/projects/7/brand-facts");
      return {
        ok: true,
        status: 200,
        json: async () => [
          {
            id: 1,
            project_id: 7,
            kind: "fact",
            statement: "Founded in 2017.",
            is_forbidden: false,
            created_at: "2026-04-22T09:00:00Z",
          },
        ],
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await fetchBrandFacts(7, { Authorization: "Bearer token" });

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ id: 1, kind: "fact", is_forbidden: false });
  });

  it("surfaces a 402 plan-gate as an HttpRequestError", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 402,
      json: async () => ({ detail: "Brand integrity guardrails are available on Executive." }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchBrandFacts(7, {})).rejects.toMatchObject({ status: 402 });
  });
});

describe("createBrandFact", () => {
  it("posts the typed payload to the brand-facts endpoint", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/projects/9/brand-facts");
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({ kind: "claim", statement: "We never claim #1.", is_forbidden: true })
        );
        return {
          ok: true,
          status: 201,
          json: async () => ({
            id: 5,
            project_id: 9,
            kind: "claim",
            statement: "We never claim #1.",
            is_forbidden: true,
            created_at: "2026-04-22T10:00:00Z",
          }),
        };
      });
    vi.stubGlobal("fetch", fetchMock);

    const created = await createBrandFact(
      9,
      { kind: "claim", statement: "We never claim #1.", is_forbidden: true },
      { Authorization: "Bearer token" }
    );

    expect(created).toMatchObject({ id: 5, kind: "claim", is_forbidden: true });
  });
});

describe("deleteBrandFact", () => {
  it("issues a DELETE for the scoped fact id", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/projects/3/brand-facts/12");
        expect(init?.method).toBe("DELETE");
        return { ok: true, status: 204, json: async () => ({}) };
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      deleteBrandFact(3, 12, { Authorization: "Bearer token" })
    ).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
