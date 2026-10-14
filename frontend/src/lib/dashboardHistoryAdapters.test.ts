import { describe, expect, it } from "vitest";

import {
  buildMetricTrendData,
  buildScoreDistributionData,
  mapGeoWeeklyTrendData,
  normalizeAuditHistoryPayload,
} from "./dashboardHistoryAdapters";

const makeReport = (score: number, createdAt: string, auditOutcome = "completed") => ({
  schema_version: "2026-03-09",
  site: { url: "https://example.com", market: "us", language: "en" },
  seo: { onpage: score, performance: score, indexing: score },
  geo: { visibility_index: score, citation_share: score, brand_anchor: score },
  aeo: { answerability_score: score, extractable_pages: 1 },
  entities: [],
  competitors: [],
  suggestions: [],
  scores: { seo: score, geo: score, aeo: score },
  metadata: {
    created_at: createdAt,
    updated_at: createdAt,
    plan: "plan_specialist",
    version: "2.0",
    audit_outcome: auditOutcome,
  },
});

describe("dashboardHistoryAdapters", () => {
  it("preserves canonical reports with nullable geo/aeo numeric fields", () => {
    const canonicalReport = makeReport(70, "2026-01-01T00:00:00Z");
    canonicalReport.geo.citation_share = null;
    canonicalReport.geo.brand_anchor = null;
    canonicalReport.aeo.extractable_pages = null;

    const history = normalizeAuditHistoryPayload([
      { id: 1, status: "completed", full_report: canonicalReport },
    ]);

    expect(history).toHaveLength(1);
    expect(history[0]?.geo.citation_share).toBeNull();
    expect(history[0]?.geo.brand_anchor).toBeNull();
    expect(history[0]?.aeo.extractable_pages).toBeNull();
  });

  it("applies shared target, score, and plan precedence to canonical history payloads", () => {
    const history = normalizeAuditHistoryPayload([
      {
        id: 11,
        status: "completed",
        audit_target_type: "brand",
        target_name: "ExampleCo",
        target_url: "https://example.com",
        target_metadata: { category: "saas" },
        seo_score: 81,
        geo_score: 73,
        aeo_score: 66,
        full_report: {
          schema_version: "2026-03-09",
          target: {
            type: "website",
            name: "Legacy Example",
            url: "https://legacy.example.com",
            metadata: { category: "legacy" },
          },
          site: { url: "https://legacy.example.com", market: "us", language: "en" },
          seo: { onpage: 70, performance: 68, indexing: 69 },
          geo: { visibility_index: 72, citation_share: 44, brand_anchor: 38 },
          aeo: { answerability_score: 64, extractable_pages: 12 },
          entities: [],
          competitors: [],
          suggestions: [],
          scores: { seo: 70, geo: 72, aeo: 64, overall: 69 },
          metadata: {
            created_at: "2026-01-03T00:00:00Z",
            updated_at: "2026-01-03T00:00:00Z",
            plan: "fast",
            current_plan: "growth",
            version: "2.0",
          },
        },
      },
    ]);

    expect(history).toHaveLength(1);
    expect(history[0]?.target).toEqual({
      type: "brand",
      name: "ExampleCo",
      url: "https://example.com",
      metadata: { category: "saas" },
    });
    expect(history[0]?.site.url).toBe("https://example.com");
    expect(history[0]?.scores).toEqual({ seo: 81, geo: 73, aeo: 66, overall: 74 });
    expect(history[0]?.metadata.plan).toBe("fast");
    expect(history[0]?.metadata.current_plan).toBe("growth");
  });

  it("excludes degraded and failed audits from trend/distribution widgets", () => {
    const history = normalizeAuditHistoryPayload([
      { id: 1, status: "completed", full_report: makeReport(70, "2026-01-01T00:00:00Z") },
      { id: 2, status: "degraded", full_report: makeReport(0, "2026-01-02T00:00:00Z", "degraded") },
      { id: 3, status: "failed", full_report: makeReport(0, "2026-01-03T00:00:00Z", "failed") },
    ]);

    const trend = buildMetricTrendData(history, (audit) => audit.scores.seo);
    expect(trend).toHaveLength(1);
    expect(trend[0]?.value).toBe(70);

    const distribution = buildScoreDistributionData(history, (audit) => audit.scores.seo);
    expect(distribution.reduce((total, bucket) => total + bucket.count, 0)).toBe(1);
  });

  it("maps weekly GEO trend points to date/score/citations format", () => {
    const trend = mapGeoWeeklyTrendData([
      { date: "2026-02-15", score: 61, citations: 13, intent: "informational" },
      { date: "2026-02-01", score: 57, citations: 9, intent: "informational" },
      { date: "2026-02-08", score: 60, citations: 11, intent: "informational" },
    ]);

    expect(trend).toEqual([
      { date: "2026-02-01", score: 57, citations: 9 },
      { date: "2026-02-08", score: 60, citations: 11 },
      { date: "2026-02-15", score: 61, citations: 13 },
    ]);
  });

  it("falls back to overall score when a selector yields a non-numeric value", () => {
    const report = makeReport(70, "2026-01-01T00:00:00Z");
    (report.scores as Record<string, unknown>).overall = 73;

    const history = normalizeAuditHistoryPayload([
      { id: 1, status: "completed", full_report: report },
    ]);

    const trend = buildMetricTrendData(history, () => Number.NaN);
    const distribution = buildScoreDistributionData(history, () => Number.NaN, 10);

    expect(trend[0]?.value).toBe(73);
    expect(distribution.find((bucket) => bucket.bucket === "70-79")?.count).toBe(1);
  });

  it("rejects canonical-looking payloads that expose root entities without schema_version", () => {
    expect(() =>
      normalizeAuditHistoryPayload([
        {
          id: 1,
          status: "completed",
          full_report: {
            url: "https://example.com",
            analysis: {},
            entities: {
              items: [" Alpha ", { name: "Beta" }, { entity: "Gamma" }, { value: "" }],
              entities: [{ label: "Alpha" }, "Beta"],
            },
            metadata: {},
          },
        },
      ])
    ).toThrow("Canonical audit payload is missing a versioned schema_version.");
  });

  it("extracts entities from analysis entity_data and entity_summary fallbacks", () => {
    const history = normalizeAuditHistoryPayload([
      {
        id: 1,
        status: "completed",
        full_report: {
          url: "https://example.com",
          analysis: {
            entities_detected: "not-an-array",
            entity_data: {
              entities: [{ name: "Delta" }, " Epsilon "],
            },
            entity_summary: {
              entities: [{ label: "Epsilon" }, { entity: "Zeta" }],
            },
          },
          metadata: {},
        },
      },
    ]);

    expect(history).toHaveLength(1);
    expect(history[0]?.entities).toEqual(["Delta", "Epsilon", "Zeta"]);
  });
});
