import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchCompetitorCompare,
  fetchCompetitorMatrix,
  linkCompetitorToSite,
  linkDiscoveredCompetitors,
  unlinkCompetitorFromSite,
} from "./competitorsService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("fetchCompetitorMatrix", () => {
  it("prefers project-scoped data from latest assessment report", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/projects/5") {
        return {
          ok: true,
          json: async () => ({
            id: 5,
            workspace_id: 1,
            name: "Demo project",
            domain_url: "https://example.com",
            target_country: "RO",
            language: "en",
            icp_roles: [],
            pain_points: null,
            usp: null,
            competitors: [],
            priority_pulse_tags: [],
            sme_profiles: [],
            created_at: "2026-01-01T00:00:00Z",
            audit_count: 1,
            last_audit_at: "2026-01-10T00:00:00Z",
            latest_seo_score: 50,
            latest_geo_score: 70,
            latest_aeo_score: 60,
          }),
        };
      }

      if (url === "/api/projects/5/audits/latest?include_full_report=true") {
        return {
          ok: true,
          json: async () => ({
            id: 99,
            project_id: 5,
            audit_type: "DEEP",
            url: "https://example.com",
            geo_score: 70,
            seo_score: 50,
            aeo_score: 60,
            status: "completed",
            created_at: "2026-01-10T00:00:00Z",
            full_report: {
              competitors: [
                {
                  name: "rival-one.com",
                  score: 78,
                  geo_visibility: 81,
                  aeo_score: 76,
                  entity_strength: 73,
                  shared_entities: ["seo"],
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const rows = await fetchCompetitorMatrix(5, { Authorization: "Bearer token" });

    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      name: "rival-one.com",
      geo_score: 81,
      aeo_score: 76,
      seo_score: 73,
      gap_to_you: 18,
    });
  });

  it("propagates project-scoped lookup failures", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (
        url === "/api/projects/5" ||
        url === "/api/projects/5/audits/latest?include_full_report=true"
      ) {
        return {
          ok: false,
          json: async () => ({ detail: "Not Found" }),
        };
      }

      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchCompetitorMatrix(5, {})).rejects.toThrow("Not Found");
  });
});

describe("fetchCompetitorCompare", () => {
  it("builds project-scoped compare payload from latest assessment data", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/projects/8") {
        return {
          ok: true,
          json: async () => ({
            id: 8,
            workspace_id: 1,
            name: "Project A",
            domain_url: "https://project-a.com",
            target_country: "US",
            language: "en",
            icp_roles: [],
            pain_points: null,
            usp: null,
            competitors: [],
            priority_pulse_tags: [],
            sme_profiles: [],
            created_at: "2026-01-01T00:00:00Z",
            audit_count: 1,
            last_audit_at: "2026-01-10T00:00:00Z",
            latest_seo_score: 50,
            latest_geo_score: 70,
            latest_aeo_score: 60,
          }),
        };
      }

      if (url === "/api/projects/8/audits/latest?include_full_report=true") {
        return {
          ok: true,
          json: async () => ({
            id: 99,
            project_id: 8,
            audit_type: "DEEP",
            url: "https://project-a.com",
            geo_score: 70,
            seo_score: 50,
            aeo_score: 60,
            status: "completed",
            created_at: "2026-01-10T00:00:00Z",
            full_report: {
              competitors: [
                {
                  name: "rival-two.com",
                  score: 75,
                  geo_visibility: 74,
                  aeo_score: 73,
                  entity_strength: 72,
                  shared_entities: ["schema"],
                  missing_answers: [
                    { query: "best audit", competitor_citations: ["rival-two.com"] },
                  ],
                },
              ],
            },
          }),
        };
      }

      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const matrix = await fetchCompetitorMatrix(8, {});
    const competitorId = matrix[0]?.id ?? 0;
    const compare = await fetchCompetitorCompare(8, competitorId, {});

    expect(compare).toMatchObject({
      labels: ["AI visibility", "AI answers", "SEO"],
      site_scores: [70, 60, 50],
      comp_scores: [74, 73, 72],
      base_site: "https://project-a.com",
      comp_site: "rival-two.com",
    });
    expect(compare.common_entities).toEqual([
      { entity: "schema", site_citations: 0, comp_citations: 0 },
    ]);
    expect(compare.missing_answers).toEqual([
      { query: "best audit", competitor_citations: ["rival-two.com"] },
    ]);
  });
});

describe("canonical project competitor writes", () => {
  const competitor = {
    id: 91,
    project_id: 11,
    competitor_site_id: null,
    target_url: "new-rival.com",
    normalized_domain: "new-rival.com",
    display_name: "New Rival",
    auto_audit_enabled: true,
    created_at: "2026-01-01T00:00:00Z",
    latest_status: "not_started",
    latest_failure_reason: null,
    last_benchmarked_at: null,
    latest_source_audit_id: null,
    latest_scores: { geo: null, seo: null, aeo: null, overall: null },
  };

  it("links through canonical project competitor CRUD and returns the persisted ID", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/projects/11/competitors");
        expect(init?.method).toBe("POST");
        expect(init?.body).toBe(
          JSON.stringify({ target_url: "new-rival.com", display_name: "New Rival" })
        );
        return { ok: true, json: async () => competitor };
      });
    vi.stubGlobal("fetch", fetchMock);

    const result = await linkCompetitorToSite(
      11,
      { competitor_domain: "new-rival.com", display_name: "New Rival" },
      { Authorization: "Bearer token" }
    );

    expect(result.id).toBe(91);
    expect(result.normalized_domain).toBe("new-rival.com");
    expect(fetchMock).not.toHaveBeenCalledWith(
      "/api/projects/11",
      expect.objectContaining({ method: "PATCH" })
    );
  });

  it("unlinks by canonical project competitor ID", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        expect(String(input)).toBe("/api/projects/11/competitors/91");
        expect(init?.method).toBe("DELETE");
        return { ok: true, json: async () => ({}) };
      });
    vi.stubGlobal("fetch", fetchMock);

    await unlinkCompetitorFromSite(11, 91, { Authorization: "Bearer token" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("deduplicates bulk links against the canonical roster and duplicate inputs", async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url === "/api/projects/11/competitors" && init?.method === "GET") {
          return {
            ok: true,
            json: async () => [
              {
                ...competitor,
                id: 80,
                target_url: "existing.com",
                normalized_domain: "existing.com",
              },
            ],
          };
        }
        if (url === "/api/projects/11/competitors" && init?.method === "POST") {
          expect(init.body).toBe(
            JSON.stringify({ target_url: "new-rival.com", display_name: "New Rival" })
          );
          return { ok: true, json: async () => competitor };
        }
        throw new Error(`Unexpected URL: ${url}`);
      });
    vi.stubGlobal("fetch", fetchMock);

    const result = await linkDiscoveredCompetitors(
      11,
      [
        { competitor_domain: "existing.com" },
        { competitor_domain: "new-rival.com", display_name: "New Rival" },
        { competitor_domain: "https://www.new-rival.com/", display_name: "Duplicate Rival" },
      ],
      { Authorization: "Bearer token" }
    );

    expect(result.linked).toEqual([competitor]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
