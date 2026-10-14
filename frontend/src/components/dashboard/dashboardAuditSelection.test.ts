import { describe, expect, it } from "vitest";

import { canonicalHistoryFixture, mixedHistoryFixture } from "./__fixtures__/auditHistoryPayloads";
import { selectLatestDashboardAudit } from "./dashboardAuditSelection";

describe("selectLatestDashboardAudit", () => {
  it("returns canonical audit results directly when they exist", () => {
    const selected = selectLatestDashboardAudit(canonicalHistoryFixture);

    expect(selected?.site.url).toBe("https://new.example.com");
    expect(selected?.scores.geo).toBe(81);
  });

  it("falls back to legacy payload adaptation for old records", () => {
    const selected = selectLatestDashboardAudit(mixedHistoryFixture);

    expect(selected).not.toBeNull();
    expect(selected?.site.url).toBe("https://legacy.example.com");
    expect(selected?.scores).toEqual({ seo: 54, geo: 44, aeo: 64, overall: 54 });
    expect(selected?.suggestions[0]?.action).toBe("Add FAQ schema");
    expect(selected?.metadata.plan).toBe("plan_executive");
  });

  it("down-ranks degraded audits when a completed report exists", () => {
    const selected = selectLatestDashboardAudit([
      {
        id: 100,
        status: "completed",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://stable.example.com", market: "us", language: "en" },
          seo: { onpage: 61, performance: 63, indexing: 62 },
          geo: { visibility_index: 58, citation_share: 40, brand_anchor: 45 },
          aeo: { answerability_score: 52, extractable_pages: 5 },
          entities: [],
          competitors: [],
          suggestions: [],
          scores: { seo: 61, geo: 58, aeo: 52 },
          metadata: {
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
            plan: "plan_specialist",
            version: "2.0",
            audit_outcome: "completed",
          },
        },
      },
      {
        id: 101,
        status: "degraded",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://fallback.example.com", market: "us", language: "en" },
          seo: { onpage: 0, performance: 0, indexing: 0 },
          geo: { visibility_index: 0, citation_share: 0, brand_anchor: 0 },
          aeo: { answerability_score: 0, extractable_pages: 0 },
          entities: [],
          competitors: [],
          suggestions: [],
          scores: { seo: 0, geo: 0, aeo: 0 },
          metadata: {
            created_at: "2026-01-02T00:00:00Z",
            updated_at: "2026-01-02T00:00:00Z",
            plan: "plan_specialist",
            version: "2.0",
            audit_outcome: "degraded",
          },
        },
      },
    ]);

    expect(selected?.site.url).toBe("https://stable.example.com");
  });
});
