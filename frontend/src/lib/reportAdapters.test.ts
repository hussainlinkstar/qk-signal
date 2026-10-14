import { describe, expect, it } from "vitest";

import {
  deriveImpactLevel,
  getAdvisorPlan,
  getAeoTabData,
  getAioView,
  getAuditEntities,
  getAuditPrimaryScore,
  getAuditRecommendations,
  getAuditScopedRecommendations,
  getAuditScoreGroups,
  getConsolidatedFixes,
  getDetailedAuditRecommendations,
  getGeoTabData,
  getPillars,
  getRecommendationItems,
  getSearchTypes,
  isMeasuredSearchType,
  isPendingSearchType,
  hasNumericScoreImpact,
  impactedPillars,
  matchRecommendationItem,
  resolveActionEffort,
  resolveActionImpact,
  resolveRecommendationImpact,
  getSeoTabData,
  getTechnicalTabData,
  normalizeAuditReport,
  problemCodeFromGroundingRefs,
  type AdvisorAction,
  type RecommendationItem,
} from "@/lib/reportAdapters";

const CANONICAL_SCHEMA_VERSION = "2026-03-09";

const buildCanonicalReport = (overrides: Record<string, unknown> = {}) =>
  normalizeAuditReport({
    schema_version: CANONICAL_SCHEMA_VERSION,
    site: { url: "https://pillars.example" },
    seo: {},
    geo: {},
    aeo: {},
    entities: { items: [] },
    competitors: [],
    scores: {},
    metadata: {},
    ...overrides,
  });

describe("normalizeAuditReport", () => {
  it("normalizes canonical backend payloads and prefers canonical score/recommendation/entity fields", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: {
        url: "https://canonical.example",
        performance: { status: "success", performance_score: 88 },
        network: { http_version: "2" },
      },
      seo: { suggestions: ["Add title tags"] },
      geo: { suggestions: ["Improve local citations"] },
      aeo: { suggestions: ["Add FAQ schema"] },
      entities: {
        items: [{ name: "Canonical Entity", type: "Company", relevance: 95 }],
        categories: ["Brand"],
      },
      scores: {
        seo: 91,
        geo: 84,
        aeo: 79,
        citability: 76,
        entity_matching: 81,
        trust_signals: 88,
        technical_seo: 72,
      },
      suggestions: ["Use canonical suggestions first"],
      metadata: { warnings: ["Canonical warning"] },
    });

    expect(normalized.url).toBe("https://canonical.example");
    expect(normalized.performance.performance_score).toBe(88);
    expect(normalized.network.http_version).toBe("2");
    expect(getAuditPrimaryScore(normalized, "seo")).toBe(91);
    expect(getAuditRecommendations(normalized)).toContain("Use canonical suggestions first");
    expect(getAuditEntities(normalized)[0]).toEqual({
      name: "Canonical Entity",
      type: "Company",
      relevance: 95,
    });

    expect(getAuditScoreGroups(normalized)).toEqual([
      { label: "Citability", score: 76 },
      { label: "Entity Match", score: 81 },
      { label: "Trust Signals", score: 88 },
      { label: "Technical SEO", score: 72 },
    ]);
  });

  it("normalizes mixed recommendation payloads into plain text lists", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://mixed.example" },
      suggestions: [
        { action: "Use action text" },
        { title: "Fallback title text" },
        "Plain string recommendation",
      ],
      seo: {
        recommendations: [
          "Shared recommendation",
          { action: "Improve headings" },
          { title: "Strengthen meta descriptions" },
        ],
      },
      geo: {
        suggestions: [
          { action: "Add local entities" },
          "Shared recommendation",
          { title: "Add local citations" },
        ],
      },
      aeo: {
        suggestions: [{ action: "Add FAQ schema" }, { title: "Add concise answers" }],
      },
      analysis: {
        recommendations: [{ action: "Use action text" }, "Shared recommendation"],
        geo_recommendations: [{ action: "Add local entities" }],
        aeo_score: { recommendations: [{ title: "Add concise answers" }] },
      },
    });

    expect(normalized.suggestions).toEqual([
      {
        title: "Use action text",
        action: "Use action text",
        priority: undefined,
        impact: undefined,
        category: undefined,
      },
      {
        title: "Fallback title text",
        action: "",
        priority: undefined,
        impact: undefined,
        category: undefined,
      },
      { title: "Plain string recommendation", action: "" },
    ]);

    expect(getAuditRecommendations(normalized)).toEqual([
      "Use action text",
      "Fallback title text",
      "Plain string recommendation",
      "Add local entities",
      "Shared recommendation",
      "Add local citations",
      "Add FAQ schema",
      "Add concise answers",
      "Improve headings",
      "Strengthen meta descriptions",
    ]);

    expect(getAuditScopedRecommendations(normalized, "geo")).toEqual([
      "Add local entities",
      "Shared recommendation",
      "Add local citations",
    ]);

    expect(getAuditScopedRecommendations(normalized, "aeo")).toEqual([
      "Add FAQ schema",
      "Add concise answers",
    ]);
  });

  it("throws when a canonical-looking payload omits schema_version", () => {
    expect(() =>
      normalizeAuditReport({
        site: { url: "https://broken.example" },
        seo: {},
        geo: {},
        aeo: {},
        entities: [],
        competitors: [],
        scores: {},
      })
    ).toThrow("schema_version");
  });

  it("does not synthesize legacy analysis mirrors for canonical payloads", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://strict.example" },
      seo: { onpage: 82 },
      geo: { visibility_index: 68 },
      aeo: { answerability_score: 74 },
      entities: { items: [{ name: "Strict Entity", type: "Company" }] },
      competitors: [],
      scores: {
        seo: 82,
        geo: 68,
        aeo: 74,
      },
      suggestions: [{ title: "Direct suggestion", action: "Direct suggestion" }],
    });

    expect(normalized.analysis).toEqual({});
    expect(normalized.analysis).not.toHaveProperty("seo_score");
    expect(normalized.analysis).not.toHaveProperty("recommendations");
    expect(normalized.analysis).not.toHaveProperty("entities_detected");
  });

  it("preserves the optional integrity certificate on canonical payloads", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://integrity.example" },
      seo: {},
      geo: {},
      aeo: {},
      entities: [],
      competitors: [],
      scores: { seo: 81, geo: 77, aeo: 79 },
      integrity_certificate: {
        schema_version: "integrity-certificate-1",
        dual_track_grounding_enabled: true,
        grounding_profile: "dual_track_v1",
        summary: {
          total_claims: 5,
          track_a_total: 3,
          track_a_supported: 2,
          track_a_flagged: 1,
          track_a_omitted: 0,
          track_b_total: 2,
          track_b_supported: 1,
          track_b_flagged: 1,
          track_b_omitted: 0,
        },
        blocked_claim_buckets: [{ track: "track_b", category: "generic_recommendation", count: 1 }],
        degraded: false,
        degraded_reason: null,
      },
    });

    expect(normalized.integrity_certificate?.grounding_profile).toBe("dual_track_v1");
    expect(normalized.integrity_certificate?.summary?.track_b_supported).toBe(1);
    expect(normalized.integrity_certificate?.blocked_claim_buckets?.[0]).toEqual({
      track: "track_b",
      category: "generic_recommendation",
      count: 1,
    });
  });

  it("falls back to legacy analysis payload structure", () => {
    const normalized = normalizeAuditReport({
      url: "https://legacy.example",
      analysis: {
        seo_score: { score: 61 },
        geo_score: { score: 57 },
        aeo_score: { score: 65 },
        recommendations: ["Legacy recommendation"],
        entities_detected: ["Legacy Entity"],
      },
      performance_metrics: { performance_score: 42 },
      network_analysis: { http_version: "1.1" },
      metadata: { warnings: ["Legacy warning"] },
    });

    expect(normalized.schema_version).toBe("legacy");
    expect(getAuditPrimaryScore(normalized, "seo")).toBe(61);
    expect(getAuditPrimaryScore(normalized, "geo")).toBe(57);
    expect(getAuditPrimaryScore(normalized, "aeo")).toBe(65);
    expect(getAuditRecommendations(normalized)).toEqual(["Legacy recommendation"]);
    expect(getAuditEntities(normalized)[0].name).toBe("Legacy Entity");

    expect(getAuditScoreGroups(normalized)).toEqual([
      { label: "SEO Score", score: 61 },
      { label: "AI Visibility Score", score: 57 },
      { label: "AI Answers Index", score: 65 },
    ]);
  });
});

describe("tab data selectors", () => {
  it("uses direct canonical evidence for versioned reports and keeps legacy fallbacks scoped to legacy payloads", () => {
    const canonicalNormalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: {
        url: "https://selectors.example",
        performance: { performance_score: 44, seo_status: "legacy status" },
        network: { http_version: "1.1" },
      },
      seo: {
        status: "canonical status",
        structured_data_detected: true,
        audits: [{ title: "Canonical audit" }],
        core_web_vitals: {
          largest_contentful_paint: "2.1s",
          cumulative_layout_shift: "0.03",
        },
      },
      technical_signals: {
        performance: { score: 83, lcp_ms: 2100, cls: 0.03 },
        network: { http_version: "3", supports_http2: true },
      },
    });

    const legacyNormalized = normalizeAuditReport({
      url: "https://legacy-selectors.example",
      analysis: {
        seo_status: "analysis status",
        largest_contentful_paint: "3.9s",
        cumulative_layout_shift: "0.12",
      },
      performance_metrics: {
        performance_score: 77,
        seo_audits: [{ title: "Legacy audit" }],
      },
      network_analysis: { supports_http2: true },
    });

    const canonicalSeoData = getSeoTabData(canonicalNormalized);
    const canonicalTechnicalData = getTechnicalTabData(canonicalNormalized);
    const legacySeoData = getSeoTabData(legacyNormalized);
    const legacyTechnicalData = getTechnicalTabData(legacyNormalized);

    expect(canonicalSeoData.seoStatus).toBe("canonical status");
    expect(canonicalSeoData.structuredDataDetected).toBe(true);
    expect(canonicalSeoData.seoAudits).toEqual([{ title: "Canonical audit" }]);
    expect(canonicalSeoData.largestContentfulPaint).toBe("2.1s");
    expect(canonicalSeoData.cumulativeLayoutShift).toBe("0.03");
    expect(canonicalTechnicalData.performance.performance_score).toBe(83);
    expect(canonicalTechnicalData.network.http_version).toBe("3");

    expect(legacySeoData.seoStatus).toBe("analysis status");
    expect(legacySeoData.largestContentfulPaint).toBe("3.9s");
    expect(legacySeoData.cumulativeLayoutShift).toBe("0.12");
    expect(legacyTechnicalData.performance.performance_score).toBe(77);
    expect(legacyTechnicalData.network.supports_http2).toBe(true);
  });

  it("uses canonical AEO/GEO first and gracefully falls back to legacy analysis for partial payloads", () => {
    const canonicalNormalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://canonical-tabs.example" },
      aeo: { summary: "Canonical AEO summary", entity_clarity: "Strong clarity" },
      geo: {
        summary: "Canonical GEO summary",
        citability_score: 70,
        entity_matching_score: 71,
        trust_signals_score: 72,
        technical_seo_score: 73,
      },
      scores: {
        citability: 90,
        entity_matching: 91,
        trust_signals: 92,
        technical_seo: 93,
      },
    });

    const legacyNormalized = normalizeAuditReport({
      url: "https://legacy-tabs.example",
      analysis: {
        aeo_summary: "Legacy AEO summary",
        entity_clarity: "Needs refinement",
        aeo_score: { faq_coverage: "medium" },
        geo_summary: "Legacy GEO summary",
        citability_score: 55,
        entity_matching_score: 56,
        trust_signals_score: 57,
        technical_seo_score: 58,
      },
    });

    const canonicalAeo = getAeoTabData(canonicalNormalized);
    const canonicalGeo = getGeoTabData(canonicalNormalized);
    const legacyAeo = getAeoTabData(legacyNormalized);
    const legacyGeo = getGeoTabData(legacyNormalized);

    expect(canonicalAeo.summary).toBe("Canonical AEO summary");
    expect(canonicalAeo.entityClarity).toBe("Strong clarity");
    expect(canonicalGeo.summary).toBe("Canonical GEO summary");
    expect(canonicalGeo.citabilityScore).toBe(70);
    expect(canonicalGeo.entityMatchingScore).toBe(71);
    expect(canonicalGeo.trustSignalsScore).toBe(72);
    expect(canonicalGeo.technicalSeoScore).toBe(73);

    expect(legacyAeo.summary).toBe("Legacy AEO summary");
    expect(legacyAeo.entityClarity).toBe("Needs refinement");
    expect(legacyAeo.scoreDetails.faq_coverage).toBe("medium");
    expect(legacyGeo.summary).toBe("Legacy GEO summary");
    expect(legacyGeo.citabilityScore).toBe(55);
    expect(legacyGeo.entityMatchingScore).toBe(56);
    expect(legacyGeo.trustSignalsScore).toBe(57);
    expect(legacyGeo.technicalSeoScore).toBe(58);
  });

  it("derives overview AEO/GEO signals from canonical report fields when dedicated signal payloads are absent", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://signals.example" },
      aeo: {
        answerability_score: 66,
        schema_health: { score: 74 },
        schema_coverage: { coverage_percent: 74 },
        snippet_formatting: 73,
        information_gain: 68,
      },
      geo: {
        visibility_index: 72,
        citation_share: 44,
        brand_anchor: 38,
        entity_matching_score: 38,
      },
      scores: {
        seo: 81,
        geo: 72,
        aeo: 66,
        overall: 73,
      },
    });

    const aeoData = getAeoTabData(normalized);
    const geoData = getGeoTabData(normalized);

    expect(aeoData.scoreDetails.answerability_score).toBe(66);
    expect(aeoData.scoreDetails.voice_readiness_score).toBe(73);
    expect(aeoData.scoreDetails.schema_completeness).toBe(74);
    expect(aeoData.scoreDetails.content_freshness_score).toBe(68);

    expect(geoData.scoreDetails.citation_consistency_score).toBe(44);
    expect(geoData.scoreDetails.local_authority_score).toBe(38);
    expect(geoData.scoreDetails.relevance_score).toBe(38);
  });

  it("keeps canonical selectors unavailable instead of borrowing legacy analysis or benchmark values", () => {
    const normalized = normalizeAuditReport({
      schema_version: CANONICAL_SCHEMA_VERSION,
      site: { url: "https://mismatch.example" },
      seo: {},
      geo: {},
      aeo: {},
      entities: {},
      competitors: [],
      scores: {},
      analysis: {
        seo_score: { score: 64 },
        geo_score: { score: 52, summary: "legacy geo" },
        aeo_summary: "legacy aeo",
        entity_data: {
          entities: [{ name: "Legacy Entity", type: "Fallback" }],
          categories: ["Legacy"],
        },
      },
      metadata: {
        competitor_summary: {
          benchmark: {
            rows: [{ is_target: true, overall_score: 91, geo_visibility: 93, aeo_score: 88 }],
          },
        },
      },
    });

    expect(getAuditPrimaryScore(normalized, "seo")).toBe(0);
    expect(getAuditPrimaryScore(normalized, "geo")).toBe(0);
    expect(getAuditPrimaryScore(normalized, "aeo")).toBe(0);
    expect(getAuditScoreGroups(normalized)).toEqual([]);
    expect(getAeoTabData(normalized).summary).toBeUndefined();
    expect(getGeoTabData(normalized).summary).toBeUndefined();
    expect(getAuditEntities(normalized)).toEqual([]);
  });
});

describe("getAioView", () => {
  it("reads report.metadata.aio when present", () => {
    const report = buildCanonicalReport({
      scores: { seo: 80, aeo: 10, geo: 20 },
      metadata: {
        aio: {
          aio_score: 73,
          components: { aeo: 66, geo: 80 },
          summary: "AI visibility is strong",
          scope: "website_and_brand",
        },
      },
    });

    expect(getAioView(report)).toEqual({
      aio_score: 73,
      components: { aeo: 66, geo: 80 },
      summary: "AI visibility is strong",
      scope: "website_and_brand",
    });
  });

  it("falls back to the rounded mean of aeo/geo when metadata.aio is absent", () => {
    const report = buildCanonicalReport({ scores: { seo: 80, aeo: 41, geo: 60 } });

    const view = getAioView(report);
    expect(view).not.toBeNull();
    expect(view?.aio_score).toBe(51); // round((41 + 60) / 2) = round(50.5) = 51
    expect(view?.components).toEqual({ aeo: 41, geo: 60 });
    expect(view?.scope).toBe("website_and_brand");
  });

  it("uses the single present component when only one of aeo/geo exists", () => {
    const report = buildCanonicalReport({ scores: { seo: 80, aeo: 42 } });

    const view = getAioView(report);
    expect(view?.aio_score).toBe(42);
    expect(view?.components).toEqual({ aeo: 42, geo: null });
  });

  it("returns null when both aeo and geo are missing and no metadata.aio", () => {
    const report = buildCanonicalReport({ scores: { seo: 80 } });
    expect(getAioView(report)).toBeNull();
  });
});

describe("getSearchTypes", () => {
  const buildSearchTypes = () => [
    {
      id: "brand",
      label: "Brand",
      score: 82,
      answer_ratio: { present: 7, measured: 10 },
      trend: 4,
      insight: "Strong brand pull.",
      premium: false,
      source: "measured",
    },
    {
      id: "category",
      label: "Category",
      score: 61,
      trend: null,
      insight: "Mid category visibility.",
      premium: false,
      source: "derived",
    },
    {
      id: "problem",
      label: "Problem",
      score: 47,
      trend: -3,
      insight: "Problem queries trailing.",
      premium: false,
    },
    {
      id: "feature",
      label: "Feature",
      score: null,
      trend: null,
      insight: "No feature signal yet.",
      premium: false,
      source: "derived",
    },
    {
      id: "comparison",
      label: "Comparison",
      score: 55,
      trend: 2,
      insight: "Holding ground vs rivals.",
      premium: true,
      source: "measured",
    },
  ];

  it("maps report.metadata.search_types preserving order and shape", () => {
    const report = buildCanonicalReport({ metadata: { search_types: buildSearchTypes() } });

    const searchTypes = getSearchTypes(report);
    expect(searchTypes).toHaveLength(5);
    expect(searchTypes.map((t) => t.id)).toEqual([
      "brand",
      "category",
      "problem",
      "feature",
      "comparison",
    ]);

    const comparison = searchTypes.find((t) => t.id === "comparison");
    expect(comparison?.premium).toBe(true);
    expect(searchTypes.filter((t) => t.premium)).toHaveLength(1);

    const feature = searchTypes.find((t) => t.id === "feature");
    expect(feature?.score).toBeNull();
    expect(feature?.trend).toBeNull();
    expect(feature?.insight).toBe("No feature signal yet.");
  });

  it("maps the per-entry source provenance, defaulting to null when absent", () => {
    const report = buildCanonicalReport({ metadata: { search_types: buildSearchTypes() } });

    const searchTypes = getSearchTypes(report);
    expect(searchTypes.find((t) => t.id === "brand")?.source).toBe("measured");
    // The retired heuristic tag, still present in reports served before
    // SIGV2-1105. It is carried through so the UI can refuse it.
    expect(searchTypes.find((t) => t.id === "category")?.source).toBe("derived");
    // `problem` omits source entirely → null.
    expect(searchTypes.find((t) => t.id === "problem")?.source).toBeNull();
    expect(searchTypes.find((t) => t.id === "comparison")?.source).toBe("measured");
  });

  it("treats only a measured entry with a finite score as measured", () => {
    const report = buildCanonicalReport({ metadata: { search_types: buildSearchTypes() } });
    const byId = Object.fromEntries(getSearchTypes(report).map((t) => [t.id, t]));

    expect(isMeasuredSearchType(byId.brand)).toBe(true);
    expect(isMeasuredSearchType(byId.category)).toBe(false);
    expect(isMeasuredSearchType(byId.problem)).toBe(false);
    // `comparison` is measured with a score; `feature` is tagged derived with
    // no score at all.
    expect(isMeasuredSearchType(byId.comparison)).toBe(true);
    expect(isMeasuredSearchType(byId.feature)).toBe(false);
  });

  it("carries the pending provenance a queued measurement reports (SIGV2-1182)", () => {
    const report = buildCanonicalReport({
      metadata: {
        search_types: [
          { id: "brand", score: null, source: "pending" },
          { id: "category", score: null, source: "unmeasured" },
          { id: "problem", score: 44, source: "measured" },
          // A score with a pending tag is still not a measurement.
          { id: "feature", score: 70, source: "pending" },
          { id: "comparison", score: null, source: "derived" },
        ],
      },
    });

    const byId = Object.fromEntries(getSearchTypes(report).map((t) => [t.id, t]));
    expect(isPendingSearchType(byId.brand)).toBe(true);
    expect(isPendingSearchType(byId.category)).toBe(false);
    expect(isPendingSearchType(byId.problem)).toBe(false);
    expect(isPendingSearchType(byId.feature)).toBe(true);
    expect(isMeasuredSearchType(byId.feature)).toBe(false);
    expect(isPendingSearchType(byId.comparison)).toBe(false);
  });

  it("maps the answer ratio and rejects a shape it cannot support", () => {
    const report = buildCanonicalReport({
      metadata: {
        search_types: [
          { id: "brand", answer_ratio: { present: 7, measured: 10 } },
          { id: "category", answer_ratio: { present: 0, measured: 0 } },
          { id: "problem", answer_ratio: { present: 6, measured: 4 } },
          { id: "feature", answer_ratio: { measured: 4 } },
          { id: "comparison", answer_ratio: "7 of 10" },
        ],
      },
    });

    const byId = Object.fromEntries(getSearchTypes(report).map((t) => [t.id, t]));
    expect(byId.brand.answerRatio).toEqual({ present: 7, measured: 10 });
    for (const id of ["category", "problem", "feature", "comparison"]) {
      expect(byId[id].answerRatio).toBeNull();
    }
  });

  it("returns an empty array when metadata.search_types is absent", () => {
    const report = buildCanonicalReport({ metadata: {} });
    expect(getSearchTypes(report)).toEqual([]);
  });
});

describe("getAdvisorPlan", () => {
  it("maps report.metadata.advisor to the UI shape preserving ROI order", () => {
    const report = buildCanonicalReport({
      metadata: {
        advisor: {
          schema_version: "advisor-det-1",
          strategic_summary: null,
          actions: [
            {
              rank: 1,
              action: "Add FAQ schema to the top product pages",
              title: "Add FAQ schema",
              impact: "high",
              effort: "low",
              roi_score: 29,
              grounded_by_findings: ["finding-12"],
              derived_from: ["claim-3"],
            },
            {
              rank: 2,
              action: "Expand thin category descriptions",
              impact: "medium",
              effort: "medium",
              roi_score: 18,
              grounded_by_findings: [],
              derived_from: [],
            },
          ],
        },
      },
    });

    const plan = getAdvisorPlan(report);
    expect(plan).not.toBeNull();
    expect(plan?.schemaVersion).toBe("advisor-det-1");
    expect(plan?.strategicSummary).toBeNull();
    expect(plan?.actions).toHaveLength(2);

    const [first, second] = plan!.actions;
    expect(first.rank).toBe(1);
    expect(first.id).toBe("advisor-action-1");
    expect(first.title).toBe("Add FAQ schema");
    expect(first.detail).toBe("Add FAQ schema to the top product pages");
    expect(first.impact).toBe("high");
    expect(first.effort).toBe("low");
    expect(first.groundedBy).toEqual(["finding-12", "claim-3"]);

    expect(second.rank).toBe(2);
    expect(second.title).toBe("Expand thin category descriptions");
    expect(second.detail).toBeNull();
    expect(second.impact).toBe("medium");
    expect(second.groundedBy).toEqual([]);
  });

  it("returns null when metadata.advisor is absent", () => {
    const report = buildCanonicalReport({ metadata: {} });
    expect(getAdvisorPlan(report)).toBeNull();
  });

  it("returns an empty action list when the advisor plan has no actions", () => {
    const report = buildCanonicalReport({
      metadata: { advisor: { schema_version: "advisor-det-1", actions: [] } },
    });
    const plan = getAdvisorPlan(report);
    expect(plan).not.toBeNull();
    expect(plan?.actions).toEqual([]);
  });

  it("marks every advisor-sourced action as coming from the advisor", () => {
    const report = buildCanonicalReport({
      metadata: {
        advisor: {
          actions: [{ rank: 1, action: "Do the thing", impact: "high", effort: "low" }],
        },
      },
    });
    expect(getAdvisorPlan(report)?.actions[0].impactSource).toBe("advisor");
  });
});

describe("deriveImpactLevel", () => {
  it("uses the backend's own bands so a rebuilt label cannot disagree", () => {
    expect(deriveImpactLevel({ seo: 12, geo: null, aeo: null, overall: null })).toBe("high");
    expect(deriveImpactLevel({ seo: 10, geo: null, aeo: null, overall: null })).toBe("high");
    expect(deriveImpactLevel({ seo: 4, geo: null, aeo: null, overall: null })).toBe("medium");
    expect(deriveImpactLevel({ seo: 3, geo: null, aeo: null, overall: null })).toBe("low");
    // The largest absolute delta drives the band, matching _impact_label.
    expect(deriveImpactLevel({ seo: 1, geo: -11, aeo: null, overall: null })).toBe("high");
  });

  it("returns null when nothing numeric was supplied", () => {
    expect(deriveImpactLevel(null)).toBeNull();
    expect(deriveImpactLevel({ seo: null, geo: null, aeo: null, overall: null })).toBeNull();
  });
});

describe("resolveActionImpact / resolveActionEffort", () => {
  const action = (over: Partial<AdvisorAction> = {}): AdvisorAction => ({
    id: "advisor-action-1",
    rank: 1,
    title: "Do the thing",
    detail: null,
    impact: "medium",
    effort: "medium",
    impactSource: "advisor",
    groundedBy: [],
    ...over,
  });

  const item = (over: Partial<RecommendationItem> = {}): RecommendationItem => ({
    action: "Do the thing",
    title: "Do the thing",
    category: "Technical",
    rationale: null,
    estimatedEffort: null,
    expectedScoreImpact: null,
    groundedBy: [],
    ...over,
  });

  it("reports impact as unmeasured when no score delta backs it", () => {
    // The backend always writes an impact label, defaulting to "medium", so
    // the label alone is not evidence. Without deltas the row stays honest.
    expect(resolveActionImpact(action({ impact: "medium" }), item())).toEqual({
      measured: false,
      level: null,
    });
    expect(
      resolveActionImpact(
        action(),
        item({ expectedScoreImpact: { seo: null, geo: null, aeo: null, overall: null } })
      )
    ).toEqual({ measured: false, level: null });
    expect(resolveActionImpact(action(), null)).toEqual({ measured: false, level: null });
  });

  it("trusts the advisor label once a delta proves something was measured", () => {
    expect(
      resolveActionImpact(
        action({ impact: "high" }),
        item({ expectedScoreImpact: { seo: 6, geo: null, aeo: null, overall: 6 } })
      )
    ).toEqual({ measured: true, level: "high" });
  });

  it("rebuilds the label from deltas when the advisor never ranked the action", () => {
    // The recommendations fallback synthesises actions; its impact must come
    // from the item's own deltas, never from a placeholder.
    expect(
      resolveActionImpact(
        action({ impact: "medium", impactSource: "derived" }),
        item({ expectedScoreImpact: { seo: 14, geo: null, aeo: null, overall: 14 } })
      )
    ).toEqual({ measured: true, level: "high" });
    expect(
      resolveActionImpact(
        action({ impact: "medium", impactSource: "derived" }),
        item({ expectedScoreImpact: { seo: 2, geo: null, aeo: null, overall: 2 } })
      )
    ).toEqual({ measured: true, level: "low" });
  });

  it("takes effort only from the canonical item, never the defaulted label", () => {
    expect(resolveActionEffort(action({ effort: "medium" }), item())).toEqual({
      measured: false,
      level: null,
    });
    expect(
      resolveActionEffort(action({ effort: "medium" }), item({ estimatedEffort: "high" }))
    ).toEqual({ measured: true, level: "high" });
    expect(resolveActionEffort(action(), null)).toEqual({ measured: false, level: null });
  });

  it("never yields a numeric level", () => {
    const resolved = resolveActionImpact(
      action({ impact: "high" }),
      item({ expectedScoreImpact: { seo: 18, geo: 4, aeo: 9, overall: 18 } })
    );
    expect(["low", "medium", "high"]).toContain(resolved.level);
  });
});

describe("getPillars", () => {
  it("returns SEO and AIO pillars with the correct scope labels and scores", () => {
    const report = buildCanonicalReport({
      scores: { seo: 80, aeo: 40, geo: 60 },
    });

    const pillars = getPillars(report);
    expect(pillars).toHaveLength(2);

    const [seo, aio] = pillars;
    expect(seo.key).toBe("seo");
    expect(seo.label).toBe("SEO");
    expect(seo.score).toBe(80);
    expect(seo.scopeLabel).toBe("Website only");
    expect(typeof seo.color).toBe("string");

    expect(aio.key).toBe("aio");
    expect(aio.label).toBe("AIO");
    expect(aio.score).toBe(50); // mean of aeo 40 + geo 60
    expect(aio.scopeLabel).toBe("Website & Brand");
    expect(typeof aio.color).toBe("string");
  });

  it("yields a null AIO score when AEO and GEO are unavailable", () => {
    const report = buildCanonicalReport({ scores: { seo: 80 } });
    const [, aio] = getPillars(report);
    expect(aio.score).toBeNull();
  });
});

describe("getDetailedAuditRecommendations", () => {
  it("surfaces each AI-finding-derived penalty as its own grounded card instead of a generic bucket", () => {
    const report = buildCanonicalReport({
      scores: {
        aeo_breakdown: {
          penalties: [
            {
              reason: "The FAQ section lacks FAQPage schema markup.",
              impact: -7.5,
              description:
                "The FAQ section lacks FAQPage schema markup, so answer engines cannot extract it as a direct Q&A pair.",
              severity: "critical",
              category: "structured_data",
              rationale:
                "FAQPage schema is required for AI engines to lift a direct answer from FAQ content.",
              confidence: 0.92,
              estimated_effort: "low",
              source: "ai_finding",
            },
          ],
        },
      },
    });

    const recs = getDetailedAuditRecommendations(report);
    const finding = recs.find((r) => r.title.includes("FAQPage schema markup"));

    expect(finding).toBeDefined();
    expect(finding!.description).toContain("cannot extract it as a direct Q&A pair");
    expect(finding!.description).toContain("required for AI engines to lift a direct answer");
    expect(finding!.impact).toBe("Critical");
    expect(finding!.category).toBe("Structured Data");
    expect(finding!.confidence).toBe("high");
    // The old generic bucket text must never appear.
    expect(recs.some((r) => r.title.includes("AI-detected"))).toBe(false);
    expect(recs.some((r) => /^Fix: .* to improve \w+ score\.$/.test(r.description))).toBe(false);
  });

  it("gives deterministic penalties specific, actionable fix guidance instead of a tautological template", () => {
    const report = buildCanonicalReport({
      scores: {
        seo_breakdown: {
          penalties: [{ reason: "Missing canonical URL", impact: -15 }],
        },
      },
    });

    const recs = getDetailedAuditRecommendations(report);
    const canonical = recs.find((r) => r.title === "Missing canonical URL");

    expect(canonical).toBeDefined();
    expect(canonical!.description.toLowerCase()).toContain('rel="canonical"');
    expect(canonical!.description).not.toBe("Fix: missing canonical url to improve SEO score.");
  });

  it("falls back to the generic template only for an unrecognized deterministic penalty reason", () => {
    const report = buildCanonicalReport({
      scores: {
        geo_breakdown: {
          penalties: [{ reason: "Some brand-new penalty reason", impact: -12 }],
        },
      },
    });

    const recs = getDetailedAuditRecommendations(report);
    const unknown = recs.find((r) => r.title === "Some brand-new penalty reason");
    expect(unknown).toBeDefined();
    expect(unknown!.description).toBe("Fix: some brand-new penalty reason to improve GEO score.");
  });

  it("folds a coded deterministic penalty into the canonical item for the same problem (SIGV2-1175)", () => {
    // The same failing check feeds both channels: the suggestion-engine
    // candidate carries problem_code, the seo_breakdown penalty carries the
    // same code. Different titles, one problem - the list must contain one
    // entry, keeping the actionable guidance plus the penalty's measured
    // points.
    const report = buildCanonicalReport({
      site: { url: "https://pillars.example" },
      suggestions: [
        {
          title: "Implement Canonical URL Tag on Homepage",
          action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
          category: "Technical",
          priority: 3,
          problem_code: "missing_canonical_url",
        },
      ],
      scores: {
        seo_breakdown: {
          penalties: [
            { reason: "Missing canonical URL", impact: -15, code: "missing_canonical_url" },
          ],
        },
      },
    });

    const recs = getDetailedAuditRecommendations(report);
    const coded = recs.filter((r) => r.problemCode === "missing_canonical_url");

    expect(coded).toHaveLength(1);
    expect(coded[0].title).toBe("Implement Canonical URL Tag on Homepage");
    expect(coded[0].description).toContain("canonical URL tag");
    expect(coded[0].impactValue).toBe(-15);
    // The penalty's measured band (>=15 pts -> Critical) wins over the item's
    // unmeasured priority label.
    expect(coded[0].impact).toBe("Critical");
    expect(recs.some((r) => r.title === "Missing canonical URL")).toBe(false);
  });

  it("keeps two entries when only one side carries the problem code", () => {
    // Identity fails toward showing: an uncoded LLM item can never be proven
    // to be the penalty's problem, so it must not be suppressed.
    const report = buildCanonicalReport({
      suggestions: [
        {
          title: "Implement Canonical URL Tag on Homepage",
          action: "Add a canonical URL tag.",
          category: "Technical",
        },
      ],
      scores: {
        seo_breakdown: {
          penalties: [
            { reason: "Missing canonical URL", impact: -15, code: "missing_canonical_url" },
          ],
        },
      },
    });

    const recs = getDetailedAuditRecommendations(report);
    expect(recs.some((r) => r.title === "Implement Canonical URL Tag on Homepage")).toBe(true);
    expect(recs.some((r) => r.title === "Missing canonical URL")).toBe(true);
  });
});

describe("canonical recommendation items (SIGV2-1037)", () => {
  const reportWithItems = (items: unknown[]) =>
    ({
      schema_version: CANONICAL_SCHEMA_VERSION,
      recommendations: { items },
    }) as unknown as Parameters<typeof getRecommendationItems>[0];

  it("maps effort, impact deltas, category, rationale and grounding refs", () => {
    const items = getRecommendationItems(
      reportWithItems([
        {
          title: "Fix crawl issues",
          action: "Resolve robots rules.",
          category: "Technical",
          estimated_effort: "low",
          expected_score_impact: { seo: 6, geo: null, aeo: 2, overall: 7 },
          rationale: "Blocked pages cannot rank.",
          grounded_by_findings: ["seo.technical_seo"],
          derived_from: ["f-1"],
        },
      ])
    );
    expect(items).toHaveLength(1);
    expect(items[0].action).toBe("Resolve robots rules.");
    expect(items[0].category).toBe("Technical");
    expect(items[0].estimatedEffort).toBe("low");
    expect(items[0].expectedScoreImpact?.seo).toBe(6);
    expect(items[0].groundedBy).toEqual(["seo.technical_seo", "f-1"]);
  });

  it("keeps unrated fields null instead of inventing a medium", () => {
    const items = getRecommendationItems(
      reportWithItems([{ title: "Do a thing", action: "Do a thing.", category: "Content" }])
    );
    expect(items[0].estimatedEffort).toBeNull();
    expect(items[0].expectedScoreImpact).toBeNull();
    expect(hasNumericScoreImpact(items[0].expectedScoreImpact)).toBe(false);
    expect(impactedPillars(items[0].expectedScoreImpact)).toEqual([]);
  });

  it("rejects an invalid effort value rather than defaulting", () => {
    const items = getRecommendationItems(
      reportWithItems([{ action: "x", estimated_effort: "trivial" }])
    );
    expect(items[0].estimatedEffort).toBeNull();
  });

  it("treats an all-null impact dict as unrated, not measured", () => {
    const items = getRecommendationItems(
      reportWithItems([
        {
          action: "x",
          expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
        },
      ])
    );
    expect(items[0].expectedScoreImpact).not.toBeNull();
    expect(hasNumericScoreImpact(items[0].expectedScoreImpact)).toBe(false);
  });

  it("maps seo deltas to the SEO pillar and aeo/geo deltas to AIO", () => {
    expect(impactedPillars({ seo: 3, geo: null, aeo: null, overall: 3 })).toEqual(["seo"]);
    expect(impactedPillars({ seo: null, geo: 2, aeo: 1, overall: 2 })).toEqual(["aio"]);
    expect(impactedPillars({ seo: 1, geo: null, aeo: 2, overall: 3 })).toEqual(["seo", "aio"]);
  });

  it("joins an advisor action to its canonical item by action text", () => {
    const items = getRecommendationItems(
      reportWithItems([{ title: "Short", action: "The full action text.", category: "Backlinks" }])
    );
    const action = {
      id: "advisor-action-1",
      rank: 1,
      title: "Short",
      detail: "The full action text.",
      impact: "medium" as const,
      effort: "medium" as const,
      groundedBy: [],
    };
    expect(matchRecommendationItem(action, items)?.category).toBe("Backlinks");
    expect(
      matchRecommendationItem({ ...action, title: "Other", detail: "unrelated" }, items)
    ).toBeNull();
  });

  // SIGV2-1037: "Impact: not rated" has exactly one cause, and it is not a
  // broken join. The advisor flattens the long action text into `action` and
  // the short headline into `title` (build_advisor_plan), so the only shared
  // key between a plan action and its canonical item is that long text - and
  // the join uses it. This pins both halves apart from each other: a row whose
  // headline matches NOTHING in the items array still joins through the action
  // text and still shows a measured impact, while a row that joins perfectly
  // and carries explicit nulls shows "not rated". So an unrated chip means the
  // audit measured nothing, never that the lookup missed.
  it("resolves a measured impact through the action-text join alone", () => {
    const items = getRecommendationItems(
      reportWithItems([
        {
          title: "Rebuilt headline the advisor never saw",
          action: "Expose rooms, amenities, rates and live availability as a feed.",
          category: "Content",
          estimated_effort: "medium",
          expected_score_impact: { seo: null, geo: 5, aeo: 7, overall: 8 },
        },
        {
          title: "Earn authoritative backlinks",
          action: "Pitch travel and local press with data-led stories.",
          category: "Backlinks",
          estimated_effort: "high",
          expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
        },
      ])
    );
    const planned = {
      id: "advisor-action-1",
      rank: 1,
      title: "Publish a structured data feed",
      detail: "Expose rooms, amenities, rates and live availability as a feed.",
      impact: "high" as const,
      effort: "medium" as const,
      impactSource: "advisor" as const,
      groundedBy: [],
      problemCode: null,
    };
    const joined = matchRecommendationItem(planned, items);
    expect(joined?.category).toBe("Content");
    expect(resolveActionImpact(planned, joined)).toEqual({ measured: true, level: "high" });

    const unrated = {
      ...planned,
      id: "advisor-action-2",
      rank: 2,
      title: "Earn authoritative backlinks",
      detail: "Pitch travel and local press with data-led stories.",
      impact: "medium" as const,
    };
    const unratedItem = matchRecommendationItem(unrated, items);
    expect(unratedItem?.category).toBe("Backlinks");
    expect(unratedItem?.expectedScoreImpact).not.toBeNull();
    expect(resolveActionImpact(unrated, unratedItem)).toEqual({ measured: false, level: null });
    expect(resolveActionEffort(unrated, unratedItem)).toEqual({ measured: true, level: "high" });
  });
});

// SIGV2-1211: the Improve surfaces read DetailedRecommendation, not the
// Advisor plan, so they need their own door onto the same bands. Impact is
// categorical by product rule; the numeric value decides the band and is
// never printed.
describe("resolveRecommendationImpact", () => {
  it("bands a measured deduction, ignoring its sign", () => {
    expect(resolveRecommendationImpact({ impactValue: -12 })).toEqual({
      measured: true,
      level: "high",
    });
    expect(resolveRecommendationImpact({ impactValue: 12 })).toEqual({
      measured: true,
      level: "high",
    });
    expect(resolveRecommendationImpact({ impactValue: -5 })).toEqual({
      measured: true,
      level: "medium",
    });
    expect(resolveRecommendationImpact({ impactValue: -2 })).toEqual({
      measured: true,
      level: "low",
    });
  });

  it("agrees with the band the action plan would show for the same value", () => {
    for (const value of [1, 3.9, 4, 9.9, 10, 25]) {
      expect(resolveRecommendationImpact({ impactValue: -value }).level).toBe(
        deriveImpactLevel({ seo: null, geo: null, aeo: null, overall: value })
      );
    }
  });

  it("stays unrated with no numeric source, never defaulting to medium", () => {
    expect(resolveRecommendationImpact({})).toEqual({ measured: false, level: null });
    expect(resolveRecommendationImpact({ impactValue: undefined })).toEqual({
      measured: false,
      level: null,
    });
    // Zero is "this problem costs nothing", which is not a rating.
    expect(resolveRecommendationImpact({ impactValue: 0 })).toEqual({
      measured: false,
      level: null,
    });
    expect(resolveRecommendationImpact({ impactValue: Number.NaN })).toEqual({
      measured: false,
      level: null,
    });
  });
});

// ---------------------------------------------------------------------------
// SIGV2-1193: one consolidated list
//
// The audit used to show two lists of things to fix with different totals,
// and a stakeholder read the difference as a contradiction ("22 versus 10").
// These tests pin the join that merged them, and the one thing that makes a
// merge worth having: a consolidated list that counts the same problem twice
// is strictly worse than two honest lists.
// ---------------------------------------------------------------------------
describe("getConsolidatedFixes", () => {
  const CODE = "missing_canonical_url";

  const withAdvisor = (actions: Array<Record<string, unknown>>) => ({
    schema_version: "advisor-det-1",
    actions,
    strategic_summary: null,
  });

  it("yields one row for a coded penalty and the coded action plan entry for it", () => {
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Implement Canonical URL Tag on Homepage",
            action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
            impact: "high",
            effort: "low",
            grounded_by_findings: [`seo.penalty.${CODE}`],
            problem_code: CODE,
          },
        ]),
      },
      recommendations: {
        items: [
          {
            title: "Implement Canonical URL Tag on Homepage",
            action: "Add a canonical URL tag pointing at the homepage's preferred URL.",
            category: "Technical",
            estimated_effort: "low",
            expected_score_impact: { seo: 12, geo: null, aeo: null, overall: 12 },
            grounded_by_findings: [`seo.penalty.${CODE}`],
            problem_code: CODE,
          },
        ],
      },
      scores: {
        seo_breakdown: {
          penalties: [{ reason: "Missing canonical URL", impact: -15, code: CODE }],
        },
      },
    });

    const fixes = getConsolidatedFixes(report);
    const coded = fixes.filter((fix) => fix.problemCode === CODE);

    expect(coded).toHaveLength(1);
    // The action plan's wording survives; the penalty's measured points,
    // section and engine are folded in.
    expect(coded[0].title).toBe("Implement Canonical URL Tag on Homepage");
    expect(coded[0].impactValue).toBe(-15);
    expect(coded[0].engines).toContain("SEO");
    // Both channels are named, because the customer can still see which list
    // a fix came from (SIGV2-1175) - it is just stated on the row now.
    expect(coded[0].sources).toEqual(["action_plan", "audit_finding"]);
    expect(fixes.some((fix) => fix.title === "Missing canonical URL")).toBe(false);
  });

  it("merges an entry coded only by its grounding reference", () => {
    // Step 2 of the join. `{dimension}.penalty.{code}` is emitted by exactly
    // one function, for a registry code, so decoding it is transport, not
    // inference. Nothing in the pipeline produces this shape today (the code
    // and the reference are attached together), which is why it is pinned
    // here rather than left to be discovered.
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Add the canonical tag",
            action: "Point the homepage at its preferred URL.",
            impact: "high",
            grounded_by_findings: [`seo.penalty.${CODE}`],
            problem_code: null,
          },
        ]),
      },
      scores: {
        seo_breakdown: {
          penalties: [{ reason: "Missing canonical URL", impact: -15, code: CODE }],
        },
      },
    });

    const fixes = getConsolidatedFixes(report);

    expect(fixes).toHaveLength(1);
    expect(fixes[0].title).toBe("Add the canonical tag");
    expect(fixes[0].problemCode).toBe(CODE);
    expect(fixes[0].sources).toEqual(["action_plan", "audit_finding"]);
  });

  it("reads a problem code out of a penalty reference and nothing else", () => {
    expect(problemCodeFromGroundingRefs([`seo.penalty.${CODE}`])).toBe(CODE);
    expect(problemCodeFromGroundingRefs([`AEO.PENALTY.${CODE.toUpperCase()}`])).toBe(CODE);
    // Keyword grounding only ever produces finding references, and those name
    // a position in a list, not a problem.
    expect(problemCodeFromGroundingRefs(["seo.finding.1"])).toBeNull();
    expect(problemCodeFromGroundingRefs(["seo.thin_content"])).toBeNull();
    expect(problemCodeFromGroundingRefs(["penalty.no_https"])).toBeNull();
    expect(problemCodeFromGroundingRefs([])).toBeNull();
  });

  it("never merges two genuinely different problems", () => {
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Add the canonical tag",
            action: "Point the homepage at its preferred URL.",
            impact: "high",
            grounded_by_findings: ["seo.finding.1"],
            problem_code: CODE,
          },
        ]),
      },
      scores: {
        seo_breakdown: {
          penalties: [
            { reason: "Missing canonical URL", impact: -15, code: CODE },
            { reason: "Missing meta description", impact: -9, code: "missing_meta_description" },
          ],
        },
      },
    });

    const fixes = getConsolidatedFixes(report);

    expect(fixes).toHaveLength(2);
    expect(fixes.map((fix) => fix.problemCode).sort()).toEqual([CODE, "missing_meta_description"]);
  });

  it("shows an uncoded entry exactly once, labelled with its own source", () => {
    // Identity fails toward showing the fix: an uncoded, LLM-authored action
    // can never be proven to be the penalty's problem, so it is listed on its
    // own row rather than folded into one.
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Publish a comparison page",
            action: "Compare your plans against the two competitors buyers ask about.",
            impact: "medium",
            grounded_by_findings: ["seo.finding.3"],
          },
        ]),
      },
      scores: {
        seo_breakdown: {
          penalties: [{ reason: "Missing canonical URL", impact: -15, code: CODE }],
        },
      },
    });

    const fixes = getConsolidatedFixes(report);
    const uncoded = fixes.filter((fix) => fix.title === "Publish a comparison page");

    expect(uncoded).toHaveLength(1);
    expect(uncoded[0].problemCode).toBeNull();
    expect(uncoded[0].sources).toEqual(["action_plan"]);
    const penalty = fixes.find((fix) => fix.problemCode === CODE);
    expect(penalty?.sources).toEqual(["audit_finding"]);
  });

  it("does not reinstate the candidates the Advisor's grounding gate dropped", () => {
    // `build_advisor_plan(require_grounding=True)` drops an ungrounded
    // candidate. The consolidated list reads the plan, so the dropped
    // candidate stays dropped: eligibility is the Advisor's and is unchanged.
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Grounded action",
            action: "Do the grounded thing.",
            impact: "medium",
            grounded_by_findings: ["seo.finding.1"],
          },
        ]),
      },
      recommendations: {
        items: [
          {
            title: "Grounded action",
            action: "Do the grounded thing.",
            grounded_by_findings: ["seo.finding.1"],
          },
          {
            title: "Ungrounded action",
            action: "Do the thing nothing supports.",
            grounded_by_findings: [],
            derived_from: [],
          },
        ],
      },
    });

    const fixes = getConsolidatedFixes(report);

    expect(fixes.map((fix) => fix.title)).toEqual(["Grounded action"]);
  });

  it("lists the canonical candidates when the plan is empty (SIGV2-1096)", () => {
    // A degraded run can emit recommendations and no findings at all, so the
    // gate drops every candidate and the plan comes back empty. Listing them
    // unrated is honest; claiming no check ran is not. All-or-nothing: this
    // never reinstates a subset while keeping the rest of a plan.
    const report = buildCanonicalReport({
      metadata: { advisor: withAdvisor([]) },
      recommendations: {
        items: [
          { title: "First candidate", action: "Do the first thing.", grounded_by_findings: [] },
          { title: "Second candidate", action: "Do the second thing.", grounded_by_findings: [] },
        ],
      },
    });

    const fixes = getConsolidatedFixes(report);

    expect(fixes.map((fix) => fix.title).sort()).toEqual(["First candidate", "Second candidate"]);
    for (const fix of fixes) {
      expect(fix.impactLevel).toEqual({ measured: false, level: null });
    }
  });

  it("counts a fix once when the plan and the suggestions array hold the same advice", () => {
    // `recommendations.items` is built from `suggestions` and the plan from
    // the items, so all three are the same content at different stages. Only
    // one of them is ever read, which is what stops one fix becoming three
    // rows for want of a shared code.
    const shared = {
      title: "Publish a comparison page",
      action: "Compare your plans against the two competitors buyers ask about.",
    };
    const report = buildCanonicalReport({
      suggestions: [shared],
      recommendations: { items: [{ ...shared, grounded_by_findings: ["seo.finding.3"] }] },
      metadata: {
        advisor: withAdvisor([
          { rank: 1, ...shared, impact: "medium", grounded_by_findings: ["seo.finding.3"] },
        ]),
      },
    });

    expect(getConsolidatedFixes(report)).toHaveLength(1);
  });

  it("leaves an unrated row unrated rather than giving it a default band", () => {
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Unrated action",
            action: "Nothing measured this.",
            // The Advisor's own labels are silently defaulted to "medium",
            // which is exactly why they are not trusted on their own.
            impact: "medium",
            effort: "medium",
            grounded_by_findings: ["seo.finding.1"],
          },
        ]),
      },
      recommendations: {
        items: [
          {
            title: "Unrated action",
            action: "Nothing measured this.",
            expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
            grounded_by_findings: ["seo.finding.1"],
          },
        ],
      },
    });

    const [fix] = getConsolidatedFixes(report);

    expect(fix.impactLevel).toEqual({ measured: false, level: null });
    expect(fix.effortLevel).toEqual({ measured: false, level: null });
    expect(fix.pillars).toEqual([]);
  });

  it("orders by severity, then the measured bands, with unrated last", () => {
    const report = buildCanonicalReport({
      scores: {
        seo_breakdown: {
          penalties: [
            { reason: "Unrated problem", impact: 0 },
            { reason: "Optimization problem", impact: -4 },
            { reason: "Critical problem", impact: -22 },
            { reason: "Strategic problem", impact: -11 },
          ],
        },
      },
    });

    expect(getConsolidatedFixes(report).map((fix) => fix.title)).toEqual([
      "Critical problem",
      "Strategic problem",
      "Optimization problem",
      "Unrated problem",
    ]);
  });

  it("ranks the list once, so every surface shows the same positions", () => {
    const report = buildCanonicalReport({
      scores: {
        seo_breakdown: {
          penalties: [
            { reason: "Second", impact: -11 },
            { reason: "First", impact: -22 },
          ],
        },
      },
    });

    const fixes = getConsolidatedFixes(report);
    expect(fixes.map((fix) => [fix.rank, fix.title])).toEqual([
      [1, "First"],
      [2, "Second"],
    ]);
    expect(new Set(fixes.map((fix) => fix.id)).size).toBe(fixes.length);
  });

  it("prints no numeric impact on any row it hands a surface", () => {
    // The numeric fields still exist on the models and are read to pick a
    // band and to order. They are never part of what a row says.
    const report = buildCanonicalReport({
      metadata: {
        advisor: withAdvisor([
          {
            rank: 1,
            title: "Add the canonical tag",
            action: "Point the homepage at its preferred URL.",
            impact: "high",
            grounded_by_findings: [`seo.penalty.${CODE}`],
            problem_code: CODE,
          },
        ]),
      },
      recommendations: {
        items: [
          {
            title: "Add the canonical tag",
            action: "Point the homepage at its preferred URL.",
            expected_score_impact: { seo: 12, geo: null, aeo: null, overall: 12 },
            grounded_by_findings: [`seo.penalty.${CODE}`],
            problem_code: CODE,
          },
        ],
      },
      scores: {
        seo_breakdown: {
          penalties: [{ reason: "Missing canonical URL", impact: -15, code: CODE }],
        },
      },
    });

    for (const fix of getConsolidatedFixes(report)) {
      const rendered = [fix.title, fix.description, fix.category, fix.impact].join(" ");
      expect(rendered).not.toMatch(/[+\u2212-]?\s?\d+(\.\d+)?\s*(pts?|points?|%)/i);
      expect(rendered).not.toMatch(/\b(seo|aeo|geo|overall)\b[^.]{0,12}\d/i);
    }
  });

  it("keeps a report with no plan and no items on its suggestions array", () => {
    const report = buildCanonicalReport({
      suggestions: [{ title: "Legacy suggestion", action: "Do the legacy thing." }],
    });

    const fixes = getConsolidatedFixes(report);
    expect(fixes.map((fix) => fix.title)).toEqual(["Legacy suggestion"]);
    expect(fixes[0].sources).toEqual(["audit_finding"]);
  });
});
