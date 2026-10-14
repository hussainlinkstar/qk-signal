import type { AuditHistoryPayload } from "../dashboardAuditSelection";

export const canonicalHistoryFixture: AuditHistoryPayload[] = [
  {
    id: 20,
    status: "completed",
    full_report: {
      schema_version: "2026-03-09",
      site: { url: "https://new.example.com", market: "us", language: "en" },
      seo: { onpage: 77, performance: 73, indexing: 75 },
      geo: { visibility_index: 81, citation_share: 62, brand_anchor: 70 },
      aeo: { answerability_score: 65, extractable_pages: 9 },
      entities: ["NewCo"],
      competitors: [],
      suggestions: [],
      scores: { seo: 77, geo: 81, aeo: 65 },
      metadata: {
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        plan: "plan_specialist",
        version: "2.0",
      },
    },
  },
];

export const mixedHistoryFixture: AuditHistoryPayload[] = [
  {
    id: 1,
    status: "running",
    full_report: {
      site: { url: "https://ignored.example.com", market: "us", language: "en" },
      seo: { onpage: 10, performance: 10, indexing: 10 },
      geo: { visibility_index: 10, citation_share: 10, brand_anchor: 10 },
      aeo: { answerability_score: 10, extractable_pages: 1 },
      entities: [],
      competitors: [],
      suggestions: [],
      scores: { seo: 10, geo: 10, aeo: 10 },
      metadata: {
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
        plan: "plan_standard",
        version: "2.0",
      },
    },
  },
  {
    id: 2,
    status: "completed",
    full_report: {
      schema_version: "1.0",
      url: "https://legacy.example.com",
      analysis: {
        seo_score: { score: 54 },
        geo_score: { score: 44 },
        aeo_score: { score: 64 },
        entities_detected: ["LegacyCo"],
        recommendations: ["Add FAQ schema"],
      },
      performance: { performance_score: 50 },
      metadata: { plan: "plan_executive" },
    },
  },
];
