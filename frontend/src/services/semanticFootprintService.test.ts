import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fetchEntityGraph,
  fetchSemanticGap,
  fetchSiteMap,
  mapGraphCategory,
} from "@/services/semanticFootprintService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("semanticFootprintService", () => {
  it("fetchSiteMap derives entities from latest project audit payload", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: 1,
          audit_count: 2,
          last_audit_at: "2026-01-03T00:00:00Z",
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          project_id: 1,
          created_at: "2026-01-03T00:00:00Z",
          full_report: {
            entities: [
              {
                name: "Acme",
                normalized_key: "acme",
                frequency: 4,
                avg_relevance_score: 0.82,
                category: "brand",
              },
            ],
          },
        }),
      });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchSiteMap(1)).resolves.toEqual({
      siteId: 1,
      auditCount: 2,
      lastSeenAt: "2026-01-03T00:00:00Z",
      entities: [
        {
          name: "Acme",
          normalizedKey: "acme",
          frequency: 4,
          avgRelevanceScore: 0.82,
          category: "brand",
        },
      ],
    });
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/projects/1", {
      method: "GET",
      headers: {},
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/projects/1/audits/latest?include_full_report=true&audit_type=DEEP",
      {
        method: "GET",
        headers: {},
      }
    );
  });

  it("fetchSemanticGap handles empty collections", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          siteId: 1,
          generatedAt: "2026-01-01T00:00:00Z",
          categories: [],
          venn: [],
          heatmap: [],
          opportunities: [],
          knowledgeGraph: { nodes: [], edges: [] },
          brandAssociations: [],
        }),
      })
    );

    const payload = await fetchSemanticGap(1, 2);
    expect(payload.venn).toEqual([]);
    expect(payload.knowledgeGraph.nodes).toEqual([]);
    expect(payload.knowledgeGraph.categories).toEqual([]);
  });

  it("normalizes graph category mapping explicitly", () => {
    expect(mapGraphCategory("person")).toBe("Person");
    expect(mapGraphCategory("Organization")).toBe("Organization");
    expect(mapGraphCategory("product")).toBe("Product");
    expect(mapGraphCategory("unknown")).toBe("Concept");
  });

  it("fetchEntityGraph returns normalized graph payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          url: "https://example.com",
          uniqueness: {},
          categories: ["person", "product"],
          url_mentions: ["https://example.com/about"],
          nodes: [
            {
              key: "name:person:john",
              name: "John",
              type: "PERSON",
              category: "person",
              normalized_name: "john",
              sourceURLs: ["https://example.com/about"],
            },
          ],
          edges: [
            {
              from: "name:person:john",
              to: "name:organization:acme",
              relation: "MENTIONED_IN",
              source: "text",
              page_url: "https://example.com/about",
            },
          ],
        }),
      })
    );

    const payload = await fetchEntityGraph("https://example.com");
    expect(payload.categories).toEqual(["Person", "Product"]);
    expect(payload.edges[0]?.relation).toBe("MENTIONED_IN");
  });

  it("throws API detail message for contract errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "semantic-gap unavailable" }),
      })
    );

    await expect(fetchSemanticGap(1, 2)).rejects.toThrow("semantic-gap unavailable");
  });
});
