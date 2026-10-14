import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildCreateAuditJobPayload,
  createAuditJob,
  estimateAuditCredits,
  fetchAeoSiteStats,
  fetchAuditHistory,
  fetchLegacyAuditHistory,
  fetchUserProjects,
  fetchUserSites,
  mapAuditHistoryToViewModel,
  normalizeAeoSiteStatsPayload,
} from "./auditService";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("mapAuditHistoryToViewModel", () => {
  it("keeps unstructured strategist fields empty and surfaces a degraded data-quality warning", () => {
    const result = mapAuditHistoryToViewModel([
      {
        id: 10,
        status: "INVALID_STATUS",
        created_at: "2026-01-02T00:00:00Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com" },
          seo: { onpage: 91, performance: 77, indexing: 80 },
          geo: { visibility_index: 62, citation_share: 51, brand_anchor: 49 },
          aeo: { answerability_score: 71, extractable_pages: 8 },
          entities: [],
          competitors: [],
          scores: { seo: 91, geo: 62, aeo: 71 },
          suggestions: [{ title: "Fix headings", action: "Use one H1", priority: 1 }],
        },
      },
      {
        id: 11,
        created_at: "2026-01-03T00:00:00Z",
        full_report: {
          site: { url: "https://example.com/new" },
        },
      },
    ]);

    expect(result).toHaveLength(2);
    expect(result[0]).toMatchObject({
      auditId: 10,
      status: "completed",
      scores: { seo: 91, speed: 77, indexing: 80, mobile: 0 },
      priorityActions: [],
      issueCategories: [],
      dataQuality: expect.objectContaining({
        degraded: true,
      }),
    });
    expect(result[0]?.dataQuality?.issues).toContain(
      "Issue distribution is unavailable because the audit payload did not include structured issue_categories. The dashboard did not infer categories from generic suggestions."
    );
    expect(result[0]?.dataQuality?.issues).toContain(
      "Priority actions are unavailable because the audit payload did not include structured priority_actions. The dashboard did not infer impact or effort from suggestion text."
    );

    expect(result[1]).toMatchObject({
      auditId: 11,
      status: "completed",
      scores: { seo: 0, speed: 0, indexing: 0, mobile: 0 },
      priorityActions: [],
      issueCategories: [],
      aiInsights: {
        executive_summary: "",
      },
      dataQuality: expect.objectContaining({
        degraded: true,
      }),
    });

    expect(result[1]?.scoreDeltaVsPrevious).toEqual({
      seo: -91,
      speed: -77,
      indexing: -80,
      mobile: 0,
    });
  });

  it("drops invalid structured strategist rows instead of repairing them", () => {
    const result = mapAuditHistoryToViewModel([
      {
        id: 12,
        created_at: "2026-01-04T00:00:00Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com/suggestions" },
          seo: { onpage: 78, performance: 66, indexing: 64 },
          geo: { visibility_index: 52, citation_share: 41, brand_anchor: 39 },
          aeo: { answerability_score: 61, extractable_pages: 3 },
          entities: [],
          competitors: [],
          scores: { seo: 78, geo: 52, aeo: 61 },
          issue_categories: [{ key: "technical_seo", count: 2, severity: "high" }],
          priority_actions: [
            { id: "broken", title: "Broken payload", category: "technical_seo", priority: 2 },
          ],
        },
      },
    ]);

    expect(result[0]?.issueCategories).toEqual([]);
    expect(result[0]?.priorityActions).toEqual([]);
    expect(result[0]?.dataQuality?.issues).toContain(
      "Issue categories were present but invalid, so the issue distribution is unavailable."
    );
    expect(result[0]?.dataQuality?.issues).toContain(
      "Priority actions were present but invalid, so the action table is unavailable."
    );
  });

  it("prefers backend priority_actions payload unchanged when provided", () => {
    const result = mapAuditHistoryToViewModel([
      {
        id: 13,
        created_at: "2026-01-05T00:00:00Z",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://example.com/backend" },
          seo: { onpage: 88, performance: 74, indexing: 70 },
          geo: { visibility_index: 64, citation_share: 52, brand_anchor: 48 },
          aeo: { answerability_score: 67, extractable_pages: 4 },
          entities: [],
          competitors: [],
          scores: { seo: 88, geo: 64, aeo: 67 },
          priority_actions: [
            {
              id: "backend-action",
              title: "Server-provided action",
              description: "Use backend-calculated dimensions",
              category: "technical_seo",
              priority: 4,
              impact: "low",
              effort: "high",
            },
          ],
          suggestions: [
            { id: "ignored", title: "Ignored suggestion", category: "Content", priority: 1 },
          ],
        },
      },
    ]);

    expect(result[0]?.priorityActions).toEqual([
      expect.objectContaining({
        id: "backend-action",
        category: "technical_seo",
        priority: 4,
        impact: "low",
        effort: "high",
      }),
    ]);
    expect(result[0]?.dataQuality?.degraded).toBe(true);
  });
});

describe("buildCreateAuditJobPayload", () => {
  it("serializes optional targeting fields and normalizes comma-separated entities", () => {
    const payload = buildCreateAuditJobPayload({
      projectId: 1,
      url: "https://example.com",
      tier: "deep",
      requestId: "req-123",
      language: "fr",
      market: " Romania ",
      category: " finance ",
      entities: " OpenAI,  ChatGPT, , GEO ",
      auditData: {
        title: "Example title",
        entities_detected: ["OpenAI", "ChatGPT"],
      },
    });

    expect(payload).toEqual({
      project_id: 1,
      url: "https://example.com",
      audit_target_type: "website",
      target_url: "https://example.com",
      tier: "deep",
      request_id: "req-123",
      language: "fr",
      market: "Romania",
      category: "finance",
      entities: ["OpenAI", "ChatGPT", "GEO"],
      audit_data: {
        title: "Example title",
        entities_detected: ["OpenAI", "ChatGPT"],
      },
    });
  });

  it("supports brand-target payload fields", () => {
    const payload = buildCreateAuditJobPayload({
      projectId: 44,
      auditTargetType: "brand",
      targetName: "Acme",
      targetUrl: "https://acme.com",
      targetMetadata: { aliases: ["Acme Inc"] },
      tier: "fast",
      requestId: "req-brand-1",
    });

    expect(payload).toEqual({
      project_id: 44,
      audit_target_type: "brand",
      target_name: "Acme",
      target_url: "https://acme.com",
      target_metadata: { aliases: ["Acme Inc"] },
      tier: "fast",
      request_id: "req-brand-1",
    });
  });

  it("omits target URLs for brand-only payloads", () => {
    const payload = buildCreateAuditJobPayload({
      projectId: 45,
      auditTargetType: "brand",
      targetName: "Acme",
      tier: "fast",
      requestId: "req-brand-2",
    });

    expect(payload).toEqual({
      project_id: 45,
      audit_target_type: "brand",
      target_name: "Acme",
      tier: "fast",
      request_id: "req-brand-2",
    });
  });
});

describe("createAuditJob", () => {
  it("posts the extended payload to /api/audit/jobs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: "job-1", status: "queued" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await createAuditJob(
      {
        projectId: 1,
        url: "https://example.com",
        tier: "fast",
        requestId: "req-1",
        language: "en",
        market: "US",
        category: "saas",
        entities: ["OpenAI", "Search"],
      },
      { "Content-Type": "application/json" }
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [endpoint, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/audit/jobs");
    expect(requestInit.method).toBe("POST");
    expect(requestInit.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(String(requestInit.body))).toEqual({
      project_id: 1,
      tier: "fast",
      request_id: "req-1",
      audit_target_type: "website",
      url: "https://example.com",
      target_url: "https://example.com",
      language: "en",
      market: "US",
      category: "saas",
      entities: ["OpenAI", "Search"],
    });
  });
});

describe("estimateAuditCredits", () => {
  it("posts normalized payload to /api/v1/audit/estimate", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        consumes_scan: true,
        has_active_subscription: false,
        scans_used: 2,
        scans_remaining: 8,
        reset_at: null,
        confidence: 0.71,
        provider: "google",
        tier: "deep",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await estimateAuditCredits(
      {
        tier: "deep",
        category: " finance ",
        market: " Romania ",
        entities: " OpenAI,  GEO ",
        selectedModels: ["openai", "anthropic"],
        targetUrl: "https://example.com",
        auditData: {
          title: "Example",
          entities_detected: ["OpenAI", "GEO"],
        },
      },
      { Authorization: "Bearer token" }
    );

    expect(fetchMock).toHaveBeenCalledWith("/api/v1/audit/estimate", {
      method: "POST",
      headers: {
        Authorization: "Bearer token",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        tier: "deep",
        category: "finance",
        market: "Romania",
        entities: ["OpenAI", "GEO"],
        selected_models: ["openai", "anthropic"],
        target_url: "https://example.com",
        audit_data: {
          title: "Example",
          entities_detected: ["OpenAI", "GEO"],
        },
      }),
    });
  });

  it("includes brand target identity and provider intent for brand estimates", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        consumes_scan: true,
        has_active_subscription: true,
        scans_used: 2,
        scans_remaining: 8,
        reset_at: null,
        confidence: 0.74,
        provider: "openai",
        tier: "deep",
      }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await estimateAuditCredits(
      {
        auditTargetType: "brand",
        targetName: "Acme Logistics",
        targetMetadata: { aliases: ["Acme"] },
        provider: "openai",
        tier: "deep",
        category: "logistics",
      },
      { Authorization: "Bearer token" }
    );

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [endpoint, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/v1/audit/estimate");
    expect(requestInit.method).toBe("POST");
    expect(requestInit.headers).toEqual({
      Authorization: "Bearer token",
      "Content-Type": "application/json",
    });
    expect(JSON.parse(String(requestInit.body))).toEqual({
      audit_target_type: "brand",
      target_name: "Acme Logistics",
      target_metadata: { aliases: ["Acme"] },
      provider: "openai",
      tier: "deep",
      category: "logistics",
      market: null,
      entities: [],
    });
  });
});

describe("fetchUserProjects", () => {
  it("maps workspace projects into explicit project summary shape", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "12",
          workspace_id: 1,
          name: "Example",
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
          audit_count: "4",
          last_audit_at: "2026-01-19T12:00:00Z",
          latest_geo_score: "72",
          latest_aeo_score: null,
          latest_seo_score: null,
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const projects = await fetchUserProjects({ Authorization: "Bearer token" });

    expect(fetchMock).toHaveBeenCalledWith("/api/workspaces/current/projects", {
      method: "GET",
      headers: { Authorization: "Bearer token" },
      body: undefined,
    });
    expect(projects).toEqual([
      {
        project_id: 12,
        domain: "example.com",
        display_name: "Example",
        audit_count: 4,
        latest_seo_score: null,
        latest_geo_score: 72,
        latest_aeo_score: null,
        latest_audit_at: "2026-01-19T12:00:00Z",
        category: null,
        type: null,
        is_competitor: false,
      },
    ]);
  });
});

describe("fetchUserSites", () => {
  it("keeps the legacy site_id alias while exposing project_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: "12",
          workspace_id: 1,
          name: "Example",
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
          audit_count: "4",
          last_audit_at: "2026-01-19T12:00:00Z",
          latest_geo_score: "72",
          latest_aeo_score: null,
          latest_seo_score: null,
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const sites = await fetchUserSites({ Authorization: "Bearer token" });

    expect(sites).toEqual([
      {
        project_id: 12,
        site_id: 12,
        domain: "example.com",
        display_name: "Example",
        audit_count: 4,
        latest_seo_score: null,
        latest_geo_score: 72,
        latest_aeo_score: null,
        latest_audit_at: "2026-01-19T12:00:00Z",
        category: null,
        type: null,
        is_competitor: false,
      },
    ]);
  });
});
describe("fetchLegacyAuditHistory", () => {
  it("uses project-scoped history endpoint with include_full_report=true", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);

    await fetchLegacyAuditHistory({ Authorization: "Bearer token" }, 42);

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/42/audits?limit=100&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
  });

  it("throws an explicit error when payload entries cannot be normalized", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [
        {
          id: 1,
          project_id: 42,
          url: "https://example.com",
          geo_score: 50,
          status: "completed",
          created_at: "2026-01-01T00:00:00Z",
          full_report: null,
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLegacyAuditHistory({}, 42)).rejects.toThrow(
      "Audit history response missing full_report data."
    );
  });
});

describe("fetchAuditHistory", () => {
  it("loads project-scoped history for a selected project without legacy fallback", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce({
      ok: true,
      json: async () => [
        {
          id: 7,
          project_id: 42,
          url: "https://example.com",
          audit_type: "DEEP",
          geo_score: 71,
          seo_score: 75,
          aeo_score: 68,
          status: "completed",
          created_at: "2026-01-02T00:00:00Z",
          full_report: { site: { url: "https://example.com" } },
        },
      ],
    });
    vi.stubGlobal("fetch", fetchMock);

    const history = await fetchAuditHistory({ Authorization: "Bearer token" }, 42);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/42/audits?limit=100&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
    expect(history).toEqual([
      expect.objectContaining({
        id: 7,
        project_id: 42,
        geo_score: 71,
        seo_score: 75,
        aeo_score: 68,
      }),
    ]);
  });

  it("aggregates workspace history from project-scoped audit feeds only", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          { id: 12, name: "Alpha", domain_url: "https://alpha.example" },
          { id: 34, name: "Beta", domain_url: "https://beta.example" },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            id: 101,
            project_id: 12,
            url: "https://alpha.example",
            audit_type: "STANDARD",
            geo_score: 51,
            seo_score: 62,
            aeo_score: 49,
            status: "completed",
            created_at: "2026-01-01T00:00:00Z",
            full_report: { site: { url: "https://alpha.example" } },
          },
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => [
          {
            id: 202,
            project_id: 34,
            url: "https://beta.example",
            audit_type: "DEEP",
            geo_score: 73,
            seo_score: 78,
            aeo_score: 70,
            status: "completed",
            created_at: "2026-01-03T00:00:00Z",
            full_report: { site: { url: "https://beta.example" } },
          },
        ],
      });
    vi.stubGlobal("fetch", fetchMock);

    const history = await fetchAuditHistory({ Authorization: "Bearer token" });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/workspaces/current/projects", {
      method: "GET",
      headers: { Authorization: "Bearer token" },
      body: undefined,
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/projects/12/audits?limit=25&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/projects/34/audits?limit=25&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
    expect(history.map((entry) => entry.id)).toEqual([101, 202]);
  });
});

describe("normalizeAeoSiteStatsPayload", () => {
  it("normalizes partial payloads from legacy audits", () => {
    const normalized = normalizeAeoSiteStatsPayload(
      {
        audit_count: "4",
        top_performing_queries: [{ query: "geo audit", aeo_score: "88" }],
        query_benchmark: {
          site_domain: "example.com",
          queries: [
            {
              query: "what is aeo",
              winner: "site",
              site: { domain: "example.com" },
            },
          ],
        },
      },
      99
    );

    expect(normalized).toMatchObject({
      site_id: 99,
      audit_count: 4,
      answer_dominance: {
        site_primary_count: 0,
        competitor_primary_count: 0,
        site_primary_share_total: 0,
        competitor_primary_share_total: 0,
        unknown_share_total: 0,
      },
      schema_health: {
        avg_score: 0,
        healthy_audits: 0,
        issue_count: 0,
        coverage_percent: 0,
        coverage_by_type: {},
        missing_high_impact_types: [],
        high_impact_blockers: [],
      },
      readability_insights: {
        avg_readability_score: null,
        low_readability_audits: 0,
        findings: [],
        top_rewrite_suggestions: [],
      },
      competitor_benchmark: {
        site_avg_aeo_score: 0,
        competitor_avg_aeo_score: null,
        score_gap: null,
        competitor_count: 0,
      },
      trustworthiness_signal_coverage: null,
    });

    expect(normalized.top_performing_queries[0]).toMatchObject({
      query: "geo audit",
      aeo_score: 88,
      created_at: null,
      intent: null,
      query_type: null,
    });

    expect(normalized.query_benchmark.queries[0]).toMatchObject({
      query: "what is aeo",
      winner: "site",
      site: {
        domain: "example.com",
        answer_relevance: null,
        answer_excerpt: null,
      },
      battle_for_snippet: {
        winner: "site",
      },
    });
  });

  it("normalizes readability insights payload", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      readability_insights: {
        avg_readability_score: "0.42",
        low_readability_audits: "3",
        findings: [{ finding: "Long sentences", count: "2", percentage: "40" }],
        top_rewrite_suggestions: [
          { paragraph: "Complex paragraph", suggestion: "Break into bullets.", score: "0.2" },
        ],
      },
    });

    expect(normalized.readability_insights).toEqual({
      avg_readability_score: 0.42,
      low_readability_audits: 3,
      findings: [{ finding: "Long sentences", count: 2, percentage: 40 }],
      top_rewrite_suggestions: [
        { paragraph: "Complex paragraph", suggestion: "Break into bullets.", score: 0.2 },
      ],
    });
  });

  it("keeps trustworthiness signal fields nullable without forcing zeros", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      trustworthiness_signal_coverage: null,
      trustworthiness_trend: [
        { date: "2026-01-12", score: null, audit_count: 3, signal_coverage: null },
      ],
    });

    expect(normalized.trustworthiness_signal_coverage).toBeNull();
    expect(normalized.trustworthiness_trend[0]).toEqual({
      date: "2026-01-12",
      score: null,
      audit_count: 3,
      signal_coverage: null,
    });
  });

  it("normalizes schema coverage breakdown", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      schema_health: {
        coverage_percent: "66.5",
        coverage_by_type: { FAQPage: "70", HowTo: 20, Product: "10" },
        missing_high_impact_types: [{ type: "HowTo", count: "2", percentage: "50" }],
      },
    });

    expect(normalized.schema_health.coverage_percent).toBe(66.5);
    expect(normalized.schema_health.coverage_by_type).toEqual({
      FAQPage: 70,
      HowTo: 20,
      Product: 10,
    });
    expect(normalized.schema_health.missing_high_impact_types[0]).toEqual({
      type: "HowTo",
      count: 2,
      percentage: 50,
    });
    expect(normalized.schema_health.high_impact_blockers).toEqual([]);
  });

  it("normalizes high-impact schema blockers from mixed payload formats", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      schema_health: {
        missing_high_impact_types: ["SoftwareApplication"],
        high_impact_blockers: [
          "Missing SoftwareApplication schema is a high-impact blocker.",
          {
            type: "FAQPage",
            severity: "critical",
            recommendation: "Add JSON-LD FAQPage with mainEntity question/answer pairs.",
          },
        ],
      },
    });

    expect(normalized.schema_health.missing_high_impact_types).toEqual([
      { type: "SoftwareApplication", count: 0, percentage: 0 },
    ]);
    expect(normalized.schema_health.high_impact_blockers).toEqual([
      {
        type: "SoftwareApplication",
        severity: "high",
        recommendation: "Missing SoftwareApplication schema is a high-impact blocker.",
      },
      {
        type: "FAQPage",
        severity: "critical",
        recommendation: "Add JSON-LD FAQPage with mainEntity question/answer pairs.",
      },
    ]);
  });

  it("normalizes competitor list and explicit result states", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      query_benchmark: {
        site_domain: "example.com",
        queries: [
          {
            query: "best crm",
            winner: "competitor",
            winner_reason: "score_delta",
            site: {
              domain: "example.com",
              answer_relevance: 72,
              answer_relevance_source: "aeo.answer_relevance",
            },
            competitor: { domain: "rival-b.com", answer_relevance: 85 },
            competitors: [
              {
                site_id: 12,
                domain: "rival-a.com",
                answer_relevance: 80,
                answer_relevance_source: "analysis.answer_relevance",
              },
              {
                site_id: 13,
                domain: "rival-b.com",
                answer_relevance: 85,
                answer_relevance_source: "aeo.answer_relevance",
              },
            ],
          },
          {
            query: "pricing",
            winner: "no_data",
            site: { domain: "example.com", answer_relevance: null },
            competitor: { domain: null, answer_relevance: null },
          },
        ],
      },
    });

    expect(normalized.query_benchmark.queries[0]).toMatchObject({
      winner: "competitor",
      winner_reason: "score_delta",
      result_state: "lost",
      competitors: [
        { domain: "rival-a.com", answer_relevance: 80 },
        { domain: "rival-b.com", answer_relevance: 85 },
      ],
    });

    expect(normalized.query_benchmark.queries[1]).toMatchObject({
      winner: "no_data",
      result_state: "no_data",
    });
  });

  it("keeps nullable score fields as null when backend sends null", () => {
    const normalized = normalizeAeoSiteStatsPayload({
      site_id: 5,
      competitor_benchmark: {
        site_avg_aeo_score: 51,
        competitor_avg_aeo_score: null,
        score_gap: null,
        competitor_count: 1,
      },
    });

    expect(normalized.competitor_benchmark).toEqual({
      site_avg_aeo_score: 51,
      competitor_avg_aeo_score: null,
      score_gap: null,
      competitor_count: 1,
    });
  });
});

describe("fetchAeoSiteStats", () => {
  it("prefers project-scoped endpoints and normalizes payload", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/projects/7") {
        return {
          ok: true,
          json: async () => ({
            id: 7,
            workspace_id: 1,
            name: "Example",
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
            audit_count: 2,
            last_audit_at: "2026-01-10T00:00:00Z",
            latest_seo_score: 70,
            latest_geo_score: 72,
            latest_aeo_score: 68,
          }),
        };
      }

      if (url === "/api/projects/7/audits/latest?include_full_report=true") {
        return {
          ok: true,
          json: async () => ({
            id: 101,
            project_id: 7,
            audit_type: "SMART",
            url: "https://example.com",
            geo_score: 72,
            seo_score: 70,
            aeo_score: 68,
            status: "completed",
            created_at: "2026-01-10T00:00:00Z",
            full_report: {
              query_benchmark: {
                queries: [],
              },
            },
          }),
        };
      }

      if (url === "/api/projects/7/audits?limit=100&include_full_report=true") {
        return {
          ok: true,
          json: async () => [
            {
              id: 101,
              project_id: 7,
              audit_type: "SMART",
              url: "https://example.com",
              geo_score: 72,
              seo_score: 70,
              aeo_score: 68,
              status: "completed",
              created_at: "2026-01-10T00:00:00Z",
              full_report: { query_benchmark: { queries: [] } },
            },
          ],
        };
      }

      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchAeoSiteStats({ Authorization: "Bearer token" }, 7);

    expect(fetchMock).toHaveBeenCalledWith("/api/projects/7", {
      method: "GET",
      headers: { Authorization: "Bearer token" },
      body: undefined,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/7/audits/latest?include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/projects/7/audits?limit=100&include_full_report=true",
      {
        method: "GET",
        headers: { Authorization: "Bearer token" },
        body: undefined,
      }
    );
    expect(result.site_id).toBe(7);
    expect(result.query_benchmark.queries).toEqual([]);
    expect(result.answer_failure_reasons).toEqual([]);
  });

  it("propagates project-scoped errors when project context cannot be loaded", async () => {
    const fetchMock = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (
        url === "/api/projects/7" ||
        url === "/api/projects/7/audits/latest?include_full_report=true" ||
        url === "/api/projects/7/audits?limit=100&include_full_report=true"
      ) {
        return {
          ok: false,
          json: async () => ({ detail: "Not Found" }),
        };
      }

      throw new Error(`Unexpected URL: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchAeoSiteStats({ Authorization: "Bearer token" }, 7)).rejects.toThrow(
      "Not Found"
    );

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/projects/7", {
      method: "GET",
      headers: { Authorization: "Bearer token" },
      body: undefined,
    });
  });
});
