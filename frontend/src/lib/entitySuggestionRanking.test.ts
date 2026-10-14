import { describe, expect, it } from "vitest";

import { rankEntitySuggestionsFromHistory } from "@/lib/entitySuggestionRanking";

describe("rankEntitySuggestionsFromHistory", () => {
  it("prioritizes entities by frequency and recency", () => {
    const now = Date.parse("2026-01-20T00:00:00.000Z");
    const history = [
      {
        created_at: "2026-01-19T00:00:00.000Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com", market: "us", language: "en" },
          seo: { onpage: 80, performance: 78, indexing: 79 },
          geo: { visibility_index: 74, citation_share: 41, brand_anchor: 39 },
          aeo: { answerability_score: 69, extractable_pages: 4 },
          entities: [
            { name: "Acme", type: "Organization", relevance: 88 },
            { name: "Search Console", type: "Product", relevance: 65 },
          ],
          competitors: [],
          suggestions: [],
          scores: { seo: 80, geo: 74, aeo: 69 },
          metadata: {
            created_at: "2026-01-19T00:00:00.000Z",
            updated_at: "2026-01-19T00:00:00.000Z",
          },
        },
      },
      {
        created_at: "2026-01-18T00:00:00.000Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com", market: "us", language: "en" },
          seo: { onpage: 79, performance: 77, indexing: 78 },
          geo: { visibility_index: 73, citation_share: 40, brand_anchor: 38 },
          aeo: { answerability_score: 68, extractable_pages: 4 },
          entities: [
            { name: "Acme", type: "Organization", relevance: 90 },
            { name: "Technical SEO", type: "Entity", relevance: 72 },
          ],
          competitors: [],
          suggestions: [],
          scores: { seo: 79, geo: 73, aeo: 68 },
          metadata: {
            created_at: "2026-01-18T00:00:00.000Z",
            updated_at: "2026-01-18T00:00:00.000Z",
          },
        },
      },
      {
        created_at: "2026-01-01T00:00:00.000Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com", market: "us", language: "en" },
          seo: { onpage: 65, performance: 64, indexing: 63 },
          geo: { visibility_index: 55, citation_share: 32, brand_anchor: 28 },
          aeo: { answerability_score: 60, extractable_pages: 3 },
          entities: [{ name: "Legacy Entity", type: "Entity", relevance: 99 }],
          competitors: [],
          suggestions: [],
          scores: { seo: 65, geo: 55, aeo: 60 },
          metadata: {
            created_at: "2026-01-01T00:00:00.000Z",
            updated_at: "2026-01-01T00:00:00.000Z",
          },
        },
      },
    ];

    const ranked = rankEntitySuggestionsFromHistory(history, [], { nowTs: now, limit: 5 });

    expect(ranked[0]).toMatchObject({ name: "Acme", type: "Organization", confidence: 90 });
    expect(ranked.map((item) => item.name)).toEqual([
      "Acme",
      "Search Console",
      "Technical SEO",
      "Legacy Entity",
    ]);
  });

  it("filters out entities already selected", () => {
    const history = [
      {
        created_at: "2026-01-19T00:00:00.000Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com", market: "us", language: "en" },
          seo: { onpage: 80, performance: 78, indexing: 79 },
          geo: { visibility_index: 74, citation_share: 41, brand_anchor: 39 },
          aeo: { answerability_score: 69, extractable_pages: 4 },
          entities: [
            { name: "Acme", type: "Organization", relevance: 88 },
            { name: "Acme", type: "Organization", relevance: 88 },
            { name: "Knowledge Graph", type: "Entity", relevance: 77 },
          ],
          competitors: [],
          suggestions: [],
          scores: { seo: 80, geo: 74, aeo: 69 },
          metadata: {
            created_at: "2026-01-19T00:00:00.000Z",
            updated_at: "2026-01-19T00:00:00.000Z",
          },
        },
      },
    ];

    const ranked = rankEntitySuggestionsFromHistory(history, [
      { name: "acme", type: "Organization", confidence: 92 },
    ]);

    expect(ranked).toEqual([{ name: "Knowledge Graph", type: "Entity", confidence: 77 }]);
  });
});
