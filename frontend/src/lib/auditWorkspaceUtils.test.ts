import { describe, expect, it } from "vitest";

import {
  normalizeDiscoveredCategory,
  normalizeDiscoveredLanguage,
  normalizeDiscoveredMarket,
  normalizeReport,
  normalizeReportWithDiagnostics,
} from "@/lib/auditWorkspaceUtils";

describe("normalizeDiscoveredCategory", () => {
  it("expands generic saas into explicit category wording", () => {
    expect(normalizeDiscoveredCategory("SaaS")).toBe("SaaS - B2B Software Platform");
  });

  it("expands generic local business with contextual specialization", () => {
    expect(
      normalizeDiscoveredCategory("Local Business", {
        url: "https://dentist-example.com",
      })
    ).toBe("Local Business - Dental Clinic");
  });

  it("falls back local business to service provider when specialization is unknown", () => {
    expect(normalizeDiscoveredCategory("local business")).toBe("Local Business - Service Provider");
  });

  it("maps generic business labels to SaaS when tech context is clear", () => {
    expect(
      normalizeDiscoveredCategory("Local Business", {
        url: "https://app.thothgraph.com",
      })
    ).toBe("SaaS - B2B Software Platform");
  });

  it("re-maps local business service-provider labels to SaaS when hostname is clearly tech", () => {
    expect(
      normalizeDiscoveredCategory("Local Business - Service Provider", {
        url: "https://app.thothgraph.com",
      })
    ).toBe("SaaS - B2B Software Platform");
  });

  it("re-maps generic agency category to event-planner when AI context mentions weddings/events", () => {
    expect(
      normalizeDiscoveredCategory("Agency - Marketing / Creative", {
        url: "https://wedding-events.example",
        entities: [
          { name: "Event planning and coordination", type: "AI Detected", confidence: 90 },
          { name: "Wedding planning", type: "AI Detected", confidence: 90 },
          { name: "Floral design and arrangements", type: "AI Detected", confidence: 90 },
        ],
      })
    ).toBe("Local Business - Event Planner & Wedding Services");
  });

  it("maps rich AI category wording for wedding and event decoration to event planner taxonomy", () => {
    expect(
      normalizeDiscoveredCategory("Event Planning / Wedding & Event Decoration / Floral Design", {
        url: "https://wedding-events.example",
      })
    ).toBe("Local Business - Event Planner & Wedding Services");
  });

  it("normalizes ecommerce aliases", () => {
    expect(normalizeDiscoveredCategory("ecommerce")).toBe("E-commerce - Online Retail Store");
  });

  it("normalizes language aliases into supported codes", () => {
    expect(normalizeDiscoveredLanguage("French")).toBe("fr");
    expect(normalizeDiscoveredLanguage("en-US")).toBe("en");
  });

  it("falls back to English for languages the product no longer offers", () => {
    expect(normalizeDiscoveredLanguage("Romanian")).toBe("en");
    expect(normalizeDiscoveredLanguage("ro")).toBe("en");
    expect(normalizeDiscoveredLanguage("ro-RO")).toBe("en");
  });

  it("normalizes market aliases without forcing country by TLD", () => {
    expect(normalizeDiscoveredMarket("romania")).toBe("Romania");
    expect(normalizeDiscoveredMarket("")).toBe("");
  });
});

describe("report normalization", () => {
  it("rejects canonical-looking payloads that omit schema_version", () => {
    const result = normalizeReportWithDiagnostics(
      {
        id: 1,
        url: "https://broken.example",
        geo_score: 50,
        created_at: "2026-03-10T00:00:00Z",
        full_report: {
          site: { url: "https://broken.example" },
          seo: {},
          geo: {},
          aeo: {},
          entities: [],
          competitors: [],
          scores: {},
        },
      },
      "https://broken.example"
    );

    expect(result.report).toBeNull();
    expect(result.diagnostics.source).toBe("mismatched");
    expect(result.diagnostics.summary).toContain("schema_version");
    expect(() =>
      normalizeReport(
        {
          id: 1,
          url: "https://broken.example",
          geo_score: 50,
          created_at: "2026-03-10T00:00:00Z",
          full_report: {
            site: { url: "https://broken.example" },
            seo: {},
            geo: {},
            aeo: {},
            entities: [],
            competitors: [],
            scores: {},
          },
        },
        "https://broken.example"
      )
    ).toThrow(/schema_version/i);
  });

  it("marks root score injections as fallback evidence instead of treating them as measured", () => {
    const result = normalizeReportWithDiagnostics(
      {
        id: 2,
        url: "https://fallback.example",
        seo_score: 77,
        geo_score: 61,
        aeo_score: 58,
        created_at: "2026-03-10T00:00:00Z",
        full_report: {
          schema_version: "2026-03-09",
          site: {},
          seo: {
            onpage: 77,
            performance: 63,
            indexing: 59,
          },
          geo: {},
          aeo: {},
          entities: [],
          competitors: [],
          scores: {
            geo: 61,
            aeo: 58,
          },
        },
      },
      "https://fallback.example"
    );

    expect(result.report?.url).toBe("https://fallback.example");
    expect(result.report?.scores?.seo).toBe(77);
    expect(result.diagnostics.degraded).toBe(true);
    expect(
      result.diagnostics.modules.seo.fields.find((field) => field.key === "overall")?.status
    ).toBe("fallback");
    expect(result.diagnostics.summary).toContain("fallback");
  });
});
