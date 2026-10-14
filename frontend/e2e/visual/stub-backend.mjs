// SIGV2-1034 parity stub backend. Serves just enough of /api/v1 for the
// authed overview + onboarding wizard to render deterministically.
// Profiles keyed by the real X-Workspace-Id header (defaults to workspace 1):
//   workspace 1 "jake Workspace" -> 3 scored projects (matches the approved
//     workspace-overview capture exactly)
//   workspace 2 "Beta Workspace" -> 0 projects (first-run state; the wizard
//     auto-opens for a non-trial user)
import http from "node:http";
import { readFileSync } from "node:fs";

const NOW = "2026-09-29T12:00:00.000Z";

// SIGV2-1178: billing and project fixtures live in fixtures/*.json next to
// this file so the plans catalogue stays the verbatim serializer output of
// backend/services/public_plan_catalog.py (regenerate it, don't hand-edit it)
// and the other payloads stay reviewable. Serving these is what makes the
// billing screens render their real state instead of the silent "Free"
// fallback the budgets below were first calibrated on.
const fixture = (name) =>
  JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), "utf8"));

const billingPlans = fixture("billing-plans.json");
const billingInvoices = fixture("billing-invoices.json");
const usageAnalytics = fixture("usage-analytics.json");
const projectTrendsByProject = { 9: fixture("project-9-trends.json") };
const projectDataSourcesByProject = fixture("project-data-sources.json");

const user = {
  id: 1,
  email: "jake@qiko.ai",
  name: "Jake",
  is_staff: false,
  portal_only: false,
  subscription_plan: "plan_standard",
  role: "OWNER",
  email_verified: true,
};

const workspaces = [
  {
    id: 1,
    name: "jake Workspace",
    role: "OWNER",
    is_owner: true,
    project_count: 3,
    member_count: 1,
  },
  {
    id: 2,
    name: "Beta Workspace",
    role: "OWNER",
    is_owner: true,
    project_count: 0,
    member_count: 1,
  },
];

const spark = (values) =>
  values.map((overall, i) => ({ date: `2026-09-${String(22 + i).padStart(2, "0")}`, overall }));

const projectsByWorkspace = {
  1: [
    {
      id: 9,
      workspace_id: 1,
      name: "Northwind Hotels",
      domain_url: "https://northwind-hotels.com",
      target_country: "GLOBAL",
      language: "en",
      competitors: [],
      audit_count: 4,
      last_audit_at: "2026-09-29T10:00:00.000Z",
      latest_seo_score: 72,
      latest_geo_score: 61,
      latest_aeo_score: 61,
    },
    {
      id: 10,
      workspace_id: 1,
      name: "Coastline Resorts",
      domain_url: "https://coastline-resorts.com",
      target_country: "GLOBAL",
      language: "en",
      competitors: [],
      audit_count: 6,
      last_audit_at: "2026-09-29T07:00:00.000Z",
      latest_seo_score: 81,
      latest_geo_score: 76,
      latest_aeo_score: 76,
    },
    {
      id: 11,
      workspace_id: 1,
      name: "Harbour View Hotel",
      domain_url: "https://harbourview.co",
      target_country: "GLOBAL",
      language: "en",
      competitors: [],
      audit_count: 3,
      last_audit_at: "2026-09-28T12:00:00.000Z",
      latest_seo_score: 74,
      latest_geo_score: 62,
      latest_aeo_score: 62,
    },
  ],
  2: [],
};

const trendsByWorkspace = {
  1: {
    workspace_id: 1,
    period: "90d",
    projects: [
      {
        project_id: 9,
        name: "Northwind Hotels",
        domain_url: "https://northwind-hotels.com",
        last_audit_at: "2026-09-29T10:00:00.000Z",
        latest_scores: { seo: 72, geo: 61, aeo: 61, overall: 67 },
        delta: { seo: 3, geo: 3, aeo: 3, overall: 3 },
        trend_direction: "up",
        sparkline: spark([52, 54, 55, 53, 57, 58, 60, 61]),
      },
      {
        project_id: 10,
        name: "Coastline Resorts",
        domain_url: "https://coastline-resorts.com",
        last_audit_at: "2026-09-29T07:00:00.000Z",
        latest_scores: { seo: 81, geo: 76, aeo: 76, overall: 79 },
        delta: { seo: 1, geo: 2, aeo: 2, overall: 2 },
        trend_direction: "up",
        sparkline: spark([70, 71, 72, 73, 74, 75, 75, 76]),
      },
      {
        project_id: 11,
        name: "Harbour View Hotel",
        domain_url: "https://harbourview.co",
        last_audit_at: "2026-09-28T12:00:00.000Z",
        latest_scores: { seo: 74, geo: 62, aeo: 62, overall: 68 },
        delta: { seo: 2, geo: 3, aeo: 3, overall: 3 },
        trend_direction: "up",
        sparkline: spark([55, 56, 58, 59, 60, 61, 61, 62]),
      },
    ],
  },
  2: { workspace_id: 2, period: "90d", projects: [] },
};

const onboardingByWs = { 1: { steps: [], dismissed: null }, 2: { steps: [], dismissed: null } };

// SIGV2-1037 competitors fixtures: four tracked rivals for project 9, real
// shaped list/analysis/gaps/trends payloads so the leaderboard, hero rank,
// trend chart and 30-day column all photograph real states.
//
// Four, not two, because the approved page (Signal Competitors.html) depicts a
// project with four tracked rivals - "of 5 tracked", five leaderboard rows -
// and the design-comparison gate cannot mask a row count. With two rivals the
// built table was 130px shorter than the approved one and every section below
// it was measured against the wrong part of the approved page, so the figure
// was reporting a scenario difference rather than an implementation one.
// Four rivals is also inside the server-side cap (MAX_PROJECT_COMPETITORS = 5,
// services/project_competitive_service.py:18), so this is a state the product
// genuinely reaches; no field is invented to get here. The two added rivals
// carry the same shape as the first two: a succeeded benchmark, seo/aeo/geo
// scores, a project-minus-competitor delta and twelve months of history.
const projectCompetitors = {
  9: [
    {
      id: 21,
      project_id: 9,
      competitor_site_id: null,
      target_url: "https://coastline-resorts.com",
      normalized_domain: "coastline-resorts.com",
      display_name: "Coastline Resorts",
      auto_audit_enabled: true,
      created_at: "2026-08-01T09:00:00.000Z",
      latest_status: "succeeded",
      latest_failure_reason: null,
      last_benchmarked_at: "2026-09-29T07:00:00.000Z",
      latest_source_audit_id: 902,
      latest_scores: { seo: 81, geo: 77, aeo: 75, overall: 78 },
    },
    {
      id: 22,
      project_id: 9,
      competitor_site_id: null,
      target_url: "https://harbourview.co",
      normalized_domain: "harbourview.co",
      display_name: "Harbour View Hotel",
      auto_audit_enabled: true,
      created_at: "2026-08-02T09:00:00.000Z",
      latest_status: "succeeded",
      latest_failure_reason: null,
      last_benchmarked_at: "2026-09-28T12:00:00.000Z",
      latest_source_audit_id: 903,
      latest_scores: { seo: 74, geo: 60, aeo: 64, overall: 68 },
    },
    {
      id: 23,
      project_id: 9,
      competitor_site_id: null,
      target_url: "https://marinabaysuites.com",
      normalized_domain: "marinabaysuites.com",
      display_name: "Marina Bay Suites",
      auto_audit_enabled: true,
      created_at: "2026-08-03T09:00:00.000Z",
      latest_status: "succeeded",
      latest_failure_reason: null,
      last_benchmarked_at: "2026-09-28T09:00:00.000Z",
      latest_source_audit_id: 904,
      latest_scores: { seo: 69, geo: 53, aeo: 55, overall: 61 },
    },
    {
      id: 24,
      project_id: 9,
      competitor_site_id: null,
      target_url: "https://seaclifflodge.com",
      normalized_domain: "seaclifflodge.com",
      display_name: "Seacliff Lodge",
      auto_audit_enabled: true,
      created_at: "2026-08-04T09:00:00.000Z",
      latest_status: "succeeded",
      latest_failure_reason: null,
      last_benchmarked_at: "2026-09-27T09:00:00.000Z",
      latest_source_audit_id: 905,
      latest_scores: { seo: 58, geo: 47, aeo: 49, overall: 53 },
    },
  ],
};

const competitiveAnalysis = {
  9: {
    project_id: 9,
    project: {
      id: 9,
      name: "Northwind Hotels",
      url: "https://northwind-hotels.com",
      scores: { seo: 72, geo: 58, aeo: 64, overall: 66 },
      last_audit_at: "2026-09-29T10:00:00.000Z",
    },
    competitors: [
      {
        id: 21,
        name: "Coastline Resorts",
        url: "https://coastline-resorts.com",
        status: "succeeded",
        last_benchmarked_at: "2026-09-29T07:00:00.000Z",
        failure_reason: null,
        scores: { seo: 81, geo: 77, aeo: 75, overall: 78 },
        delta: { seo: -9, geo: -19, aeo: -11, overall: -12 },
      },
      {
        id: 22,
        name: "Harbour View Hotel",
        url: "https://harbourview.co",
        status: "succeeded",
        last_benchmarked_at: "2026-09-28T12:00:00.000Z",
        failure_reason: null,
        scores: { seo: 74, geo: 60, aeo: 64, overall: 68 },
        delta: { seo: -2, geo: -2, aeo: 0, overall: -2 },
      },
      {
        id: 23,
        name: "Marina Bay Suites",
        url: "https://marinabaysuites.com",
        status: "succeeded",
        last_benchmarked_at: "2026-09-28T09:00:00.000Z",
        failure_reason: null,
        scores: { seo: 69, geo: 53, aeo: 55, overall: 61 },
        delta: { seo: 3, geo: 5, aeo: 9, overall: 5 },
      },
      {
        id: 24,
        name: "Seacliff Lodge",
        url: "https://seaclifflodge.com",
        status: "succeeded",
        last_benchmarked_at: "2026-09-27T09:00:00.000Z",
        failure_reason: null,
        scores: { seo: 58, geo: 47, aeo: 49, overall: 53 },
        delta: { seo: 14, geo: 11, aeo: 15, overall: 13 },
      },
    ],
    rank: { seo: 3, aeo: 3, geo: 3, overall: 3 },
    updated_at: NOW,
    benchmark_status: {
      auto_competitor_audits_enabled: true,
      competitive_digest_frequency: "weekly",
      pending_competitors: 0,
      failed_competitors: 0,
      configured_competitors: 4,
      has_data: true,
    },
  },
};

const competitiveGaps = {
  9: {
    project_id: 9,
    gaps: [
      {
        competitor_id: 21,
        competitor_name: "Coastline Resorts",
        metric: "geo",
        project_score: 58,
        competitor_score: 77,
        delta: -19,
        severity: "high",
        reason: "Cited in more AI answers on travel queries",
        recommendation: "",
        evidence: [],
      },
      {
        competitor_id: 22,
        competitor_name: "Harbour View Hotel",
        metric: "seo",
        project_score: 72,
        competitor_score: 74,
        delta: -2,
        severity: "watch",
        reason: "Stronger on-page coverage for waterfront queries",
        recommendation: "",
        evidence: [],
      },
    ],
  },
};

const TREND_MONTHS = [
  "2025-10-01",
  "2025-11-01",
  "2025-12-01",
  "2026-01-01",
  "2026-02-01",
  "2026-03-01",
  "2026-04-01",
  "2026-05-01",
  "2026-06-01",
  "2026-07-01",
  "2026-08-01",
  "2026-09-01",
];
const TREND_SERIES = {
  overall: {
    you: [50, 52, 54, 56, 57, 59, 60, 61, 63, 64, 65, 66],
    c21: [66, 68, 69, 70, 72, 73, 74, 75, 76, 76, 77, 78],
    c22: [52, 53, 55, 57, 59, 60, 61, 62, 64, 65, 66, 68],
    // Marina Bay slipped a point over the last 30 days, Seacliff held: the
    // leaderboard's 30-day column reads first-minus-last of the 30d window
    // (indices 8..11), so these two exercise the down and the flat state.
    c23: [57, 58, 59, 60, 61, 62, 62, 63, 62, 62, 61, 61],
    c24: [45, 46, 47, 48, 49, 50, 51, 52, 53, 53, 53, 53],
  },
  seo: {
    you: [62, 63, 64, 65, 66, 67, 68, 69, 70, 70, 71, 72],
    c21: [72, 73, 74, 75, 76, 76, 77, 78, 79, 79, 80, 81],
    c22: [64, 65, 66, 67, 68, 69, 70, 71, 72, 72, 73, 74],
    c23: [63, 64, 65, 66, 66, 67, 68, 68, 69, 69, 69, 69],
    c24: [50, 51, 52, 53, 54, 55, 56, 57, 58, 58, 58, 58],
  },
  aeo: {
    you: [54, 55, 56, 57, 58, 59, 60, 60, 61, 62, 63, 64],
    c21: [65, 66, 67, 68, 69, 70, 71, 72, 73, 73, 74, 75],
    c22: [55, 56, 57, 58, 59, 59, 60, 61, 62, 62, 63, 64],
    c23: [48, 49, 50, 51, 52, 53, 53, 54, 54, 55, 55, 55],
    c24: [41, 42, 43, 44, 45, 46, 47, 47, 48, 48, 49, 49],
  },
  geo: {
    you: [48, 49, 50, 51, 52, 53, 54, 54, 55, 56, 57, 58],
    c21: [66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77],
    c22: [50, 51, 52, 53, 54, 55, 56, 57, 58, 58, 59, 60],
    c23: [46, 47, 48, 49, 50, 51, 51, 52, 52, 53, 53, 53],
    c24: [39, 40, 41, 42, 43, 44, 45, 45, 46, 46, 47, 47],
  },
};

const competitiveTrends = (pid, url) => {
  const query = new URL(url, "http://x").searchParams;
  const period = query.get("period") || "90d";
  const metric = query.get("metric") || "overall";
  const series = TREND_SERIES[metric] || TREND_SERIES.overall;
  const dates =
    period === "30d" ? ["2026-09-01", "2026-09-10", "2026-09-20", "2026-09-29"] : TREND_MONTHS;
  const idx = period === "30d" ? [8, 9, 10, 11] : TREND_MONTHS.map((_, i) => i);
  const line = (key, label, is_project, values) => ({
    key,
    label,
    is_project,
    points: idx.map((i) => ({ date: dates[idx.indexOf(i)], value: values[i] })),
  });
  return {
    project_id: pid,
    metric,
    period,
    lines: [
      line("project", "Northwind Hotels", true, series.you),
      line("21", "Coastline Resorts", false, series.c21),
      line("22", "Harbour View Hotel", false, series.c22),
      line("23", "Marina Bay Suites", false, series.c23),
      line("24", "Seacliff Lodge", false, series.c24),
    ],
  };
};

// SIGV2-1035 part 2 fixture: a fully `available` site-traffic payload so the
// project-overview visual spec can photograph the GA4 section deterministically.
// Dates/timezone come from the payload, matching the contract; the window
// query param only switches the reported grain (7D/15D daily, 90D weekly,
// 12M monthly), as the real backend does.
const siteTrafficFor = (window) => ({
  status: "ok",
  window,
  start_date: "2026-09-23",
  end_date: "2026-09-29",
  comparison_start_date: "2026-09-16",
  comparison_end_date: "2026-09-22",
  property_timezone: "America/New_York",
  bucket_granularity: window === "12M" ? "monthly" : window === "90D" ? "weekly" : "daily",
  bucket_boundary: "day",
  data_freshness: "2026-09-29T12:00:00+00:00",
  availability: "available",
  data_quality: {},
  overview: {
    sessions: 4800,
    pageviews: 12300,
    key_events: 214,
    engaged_sessions: 2784,
    total_users: 3100,
    engagement_rate: 0.58,
    bounce_rate: 0.42,
    avg_session_duration: 147,
    audience: { value: null, available: false, reason: "not_defined" },
    changes: {
      sessions: { value: 0.0045, kind: "relative" },
      pageviews: { value: -0.012, kind: "relative" },
      key_events: { value: 0.0061, kind: "relative" },
      total_users: { value: 0.0045, kind: "relative" },
    },
  },
  series: [
    { bucket: "2026-09-23", sessions: 640, pageviews: 1600, key_events: 28 },
    { bucket: "2026-09-24", sessions: 700, pageviews: 1800, key_events: 31 },
    { bucket: "2026-09-25", sessions: 690, pageviews: 1750, key_events: 30 },
    { bucket: "2026-09-26", sessions: 720, pageviews: 1810, key_events: 32 },
    { bucket: "2026-09-27", sessions: 680, pageviews: 1720, key_events: 30 },
    { bucket: "2026-09-28", sessions: 690, pageviews: 1790, key_events: 31 },
    { bucket: "2026-09-29", sessions: 680, pageviews: 1830, key_events: 32 },
  ],
  channel_mix: [
    {
      bucket: "organic",
      label: "Organic",
      sessions: 1632,
      share: 34,
      share_change: { value: 2, kind: "percentage_points" },
    },
    {
      bucket: "direct",
      label: "Direct",
      sessions: 1056,
      share: 22,
      share_change: { value: 1, kind: "percentage_points" },
    },
    {
      bucket: "referral",
      label: "Referral",
      sessions: 480,
      share: 10,
      share_change: { value: -1, kind: "percentage_points" },
    },
    {
      bucket: "ai",
      label: "AI assistants",
      sessions: 864,
      share: 18,
      share_change: { value: 3, kind: "percentage_points" },
    },
    {
      bucket: "paid",
      label: "Paid",
      sessions: 432,
      share: 9,
      share_change: { value: 0, kind: "percentage_points" },
    },
    {
      bucket: "social",
      label: "Social media",
      sessions: 336,
      share: 7,
      share_change: { value: -2, kind: "percentage_points" },
    },
    {
      bucket: "other",
      label: "Other",
      sessions: 48,
      share: 1,
      share_change: { value: 0, kind: "percentage_points" },
    },
  ],
  key_events: {
    state: "active",
    total: 214,
    change: { value: 0.0061, kind: "relative" },
    by_event: [],
    by_channel: [],
  },
});

// SIGV2-1035 part 2 fixtures: project detail and a latest audit with a
// versioned canonical full_report (scores + metadata.search_types) so the
// project dashboard can be photographed with real-shaped data.
const projectDetails = Object.fromEntries(
  projectsByWorkspace[1].map((p) => [
    p.id,
    {
      ...p,
      competitors: [],
      feature_access: {
        automations: { allowed: false },
        // SIGV2-1134: the stub user is on plan_standard, which the backend
        // grants `has_advisor_recommendations`, so the action plan and its
        // dashboard preview are both open. They used to disagree here, exactly
        // as they disagreed in the product.
        advisor_recommendations: {
          allowed: true,
          detail: null,
          status_code: null,
          required_plan: null,
        },
        benchmark_intelligence: { allowed: true },
      },
    },
  ])
);

// SIGV2-1194: visibility-queries list + coverage for the prompt-setup
// surfaces. Four generated prompts on project 9 cover brand, category,
// problem and feature; comparison is deliberately left uncovered so the gate
// photographs the incomplete state (open empty group, info notice, the
// per-type add-starter action), which is the state the approved design draws.
const stubQuery = (id, pid, text, searchType) => ({
  id,
  project_id: pid,
  query_text: text,
  query_type: "aeo",
  search_type: searchType,
  search_type_source: "stored",
  search_type_suggested: searchType,
  origin: "generated",
  is_generated: true,
  providers: ["openrouter"],
  is_active: true,
  created_at: NOW,
  updated_at: NOW,
});

const stubQueriesFor = (pid) =>
  pid === 9
    ? [
        stubQuery(71, pid, "What is Northwind Hotels known for?", "brand"),
        stubQuery(
          72,
          pid,
          "Which boutique hotels are worth considering near the harbour?",
          "category"
        ),
        stubQuery(
          73,
          pid,
          "Where can I stay for a quiet night before an early meeting?",
          "problem"
        ),
        stubQuery(74, pid, "Which waterfront hotels have soundproof rooms?", "feature"),
      ]
    : [];

const SEARCH_TYPE_FIXTURE = [
  { id: "brand", label: "Brand", suggested: "What is Northwind Hotels known for?" },
  {
    id: "category",
    label: "Category",
    suggested: "Which boutique hotels are worth considering near the harbour?",
  },
  {
    id: "problem",
    label: "Problem",
    suggested: "Where can I stay for a quiet night before an early meeting?",
  },
  {
    id: "feature",
    label: "Feature",
    suggested: "Which waterfront hotels have soundproof rooms?",
  },
  {
    id: "comparison",
    label: "Comparison",
    suggested: "How does Northwind Hotels compare with Coastline Resorts?",
  },
];

const coverageFor = (pid) => {
  const queries = stubQueriesFor(pid);
  return SEARCH_TYPE_FIXTURE.map((type) => {
    const count = queries.filter((q) => q.search_type === type.id).length;
    return {
      id: type.id,
      label: type.label,
      premium: false,
      prompt_count: count,
      covered: count > 0,
      suggested_prompt: count > 0 ? null : type.suggested,
    };
  });
};

const visibilityEntitlements = () => ({
  plan: "plan_standard",
  plan_label: "Specialist",
  upgrade_plan: "plan_executive",
  upgrade_plan_label: "Executive",
  upgrade_max_queries: 50,
  max_queries: 20,
  used_queries: stubQueriesFor(9).length,
  remaining_queries: 16,
  allowed_providers: ["openrouter"],
  is_locked: false,
  estimated_cost_per_check: {},
});

const stubVisibilityQuery = (pid, fields) => ({
  id: 9000 + Math.floor(Math.random() * 900),
  project_id: pid,
  query_text: "",
  query_type: "aeo",
  search_type: null,
  search_type_source: null,
  search_type_suggested: null,
  origin: "customer",
  is_generated: false,
  providers: ["openrouter"],
  is_active: true,
  created_at: NOW,
  updated_at: NOW,
  ...fields,
});

const visibilityQueriesPayload = (pid) => ({
  project_id: pid,
  entitlements: visibilityEntitlements(),
  queries: stubQueriesFor(pid),
  coverage: coverageFor(pid),
});

const latestAuditByProject = {
  9: {
    id: 901,
    url: "https://northwind-hotels.com",
    status: "completed",
    completed_at: "2026-09-29T10:00:00.000Z",
    seo_score: 72,
    aeo_score: 61,
    geo_score: 61,
    full_report: {
      schema_version: "2.0",
      target: {
        type: "website",
        name: "Northwind Hotels",
        url: "https://northwind-hotels.com",
        metadata: {},
      },
      site: { url: "https://northwind-hotels.com", market: "hospitality", language: "en" },
      scores: { seo: 72, aeo: 64, geo: 58, overall: 64 },
      seo: {
        onpage: 70,
        performance: 68,
        indexing: 78,
        core_web_vitals: 81,
        technical_seo: 74,
        onpage_content: 70,
        eeat_trust: 66,
        security_accessibility: 58,
      },
      aeo: { answerability_score: 64, extractable_pages: 9 },
      geo: { visibility_index: 58, citation_share: 0.31, brand_anchor: 0.42 },
      entities: [],
      competitors: [],
      metadata: {
        created_at: "2026-09-29T10:00:00.000Z",
        updated_at: "2026-09-29T10:00:00.000Z",
        plan: "plan_standard",
        version: "2.0",
        // SIGV2-1105: every type is measured, with the answers it was measured
        // over, because that is the only state these cards now render. There
        // is no "derived" estimate left to photograph, and the per-type
        // `answer_ratio` is the approved `.ft-ratio` line.
        search_types: [
          {
            id: "brand",
            label: "Brand Understanding",
            score: 78,
            answer_ratio: { present: 7, measured: 10 },
            trend: 3,
            insight: "AI describes your brand correctly in most answers.",
            premium: false,
            source: "measured",
          },
          {
            id: "category",
            label: "Category Visibility",
            score: 44,
            answer_ratio: { present: 4, measured: 10 },
            trend: 3,
            insight: "You appear in some category answers.",
            premium: false,
            source: "measured",
          },
          {
            id: "problem",
            label: "Customer Problem",
            score: 30,
            answer_ratio: { present: 3, measured: 10 },
            trend: -2,
            insight: "Rivals appear above you in problem-style queries.",
            premium: false,
            source: "measured",
          },
          {
            id: "comparison",
            label: "Competitor Comparisons",
            score: 22,
            answer_ratio: { present: 2, measured: 10 },
            trend: 1,
            insight: "Recommended in only a few comparison answers.",
            premium: true,
            source: "measured",
          },
          {
            id: "feature",
            label: "Feature Recognition",
            score: 60,
            answer_ratio: { present: 6, measured: 10 },
            trend: 3,
            insight: "Most key features are attributed to you by AI.",
            premium: false,
            source: "measured",
          },
        ],
        // SIGV2-1037: the deterministic Advisor plan the Fixes page ranks,
        // joined to the canonical recommendations.items below so effort and
        // impact chips can tell a measured rating from a defaulted one.
        advisor: {
          schema_version: "1.0",
          actions: [
            {
              rank: 1,
              title: "Fix crawl and indexation coverage",
              action: "Resolve robots rules, sitemap gaps and duplicate canonicals.",
              impact: "high",
              effort: "low",
              roi_score: 9.2,
              grounded_by_findings: ["seo.technical_seo", "seo.indexing"],
              derived_from: [],
            },
            {
              rank: 2,
              title: "Publish a structured data feed",
              action:
                "Expose rooms, amenities, rates and live availability as a machine-readable feed.",
              impact: "high",
              effort: "medium",
              roi_score: 6.4,
              grounded_by_findings: ["aeo.answerability_score"],
              derived_from: [],
            },
            {
              rank: 3,
              title: "Earn authoritative backlinks",
              action: "Pitch travel and local press with data-led stories.",
              impact: "medium",
              effort: "high",
              roi_score: 3.1,
              grounded_by_findings: [],
              derived_from: [],
            },
            {
              rank: 4,
              title: "Rewrite the offers page around tracked prompts",
              action:
                "Reframe the offers page around the questions your tracked prompts actually ask.",
              impact: "medium",
              effort: "medium",
              roi_score: 2.8,
              grounded_by_findings: [],
              derived_from: [],
            },
          ],
        },
      },
      recommendations: {
        items: [
          {
            title: "Fix crawl and indexation coverage",
            action: "Resolve robots rules, sitemap gaps and duplicate canonicals.",
            category: "Technical",
            estimated_effort: "low",
            expected_score_impact: { seo: 6, geo: null, aeo: null, overall: 6 },
            rationale: "Blocked or slow-to-index pages cannot rank.",
            grounded_by_findings: ["seo.technical_seo", "seo.indexing"],
            derived_from: [],
          },
          {
            title: "Publish a structured data feed",
            action:
              "Expose rooms, amenities, rates and live availability as a machine-readable feed.",
            category: "Content",
            estimated_effort: "medium",
            expected_score_impact: { seo: null, geo: 5, aeo: 7, overall: 8 },
            rationale: "AI cannot recommend what it cannot read.",
            grounded_by_findings: ["aeo.answerability_score"],
            derived_from: [],
          },
          {
            title: "Earn authoritative backlinks",
            action: "Pitch travel and local press with data-led stories.",
            category: "Backlinks",
            estimated_effort: "high",
            // Every dimension null: the unrated-impact case the page must
            // render as "not rated" rather than a defaulted Medium.
            expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
            rationale: "Backlink authority trails the named competitors.",
            grounded_by_findings: [],
            derived_from: [],
          },
          {
            title: "Rewrite the offers page around tracked prompts",
            action:
              "Reframe the offers page around the questions your tracked prompts actually ask.",
            category: "Content",
            // No estimated_effort at all: the unrated-effort case.
            expected_score_impact: { seo: null, geo: null, aeo: 3, overall: 3 },
            rationale: "Engines quote direct answers, not marketing copy.",
            grounded_by_findings: [],
            derived_from: [],
          },
        ],
      },
      suggestions: [
        {
          title: "Publish structured room and availability data",
          description: "Expose amenities, rates and live availability as a machine-readable feed.",
          impact: "high",
          category: "DATA FEED",
        },
        {
          title: "Publish problem-intent landing pages",
          description:
            "Ship pages that map each USP to the problem it solves, with quotable headings.",
          impact: "high",
          category: "CONTENT",
        },
        {
          title: "Build comparison content",
          description: "Publish honest comparison pages against named competitors.",
          impact: "medium",
          category: "COMPARISONS",
        },
      ],
    },
  },
};

// Mock-preview convenience: /dashboard/audit/2 serves the rich Northwind
// full_report. Visual baselines still rely on history ids 900/902/903 and on
// audit 901 staying unresolvable via GET /api/v1/audits/901.
const mockPreviewAuditsById = {
  2: {
    id: 2,
    project_id: 9,
    audit_type: "SMART",
    url: latestAuditByProject[9].url,
    audit_target_type: "website",
    status: "completed",
    completed_at: latestAuditByProject[9].completed_at,
    created_at: latestAuditByProject[9].completed_at,
    seo_score: latestAuditByProject[9].seo_score,
    aeo_score: latestAuditByProject[9].aeo_score,
    geo_score: latestAuditByProject[9].geo_score,
    full_report: latestAuditByProject[9].full_report,
  },
};

const fakeJwt = (extra = {}) => {
  const header = Buffer.from(JSON.stringify({ alg: "HS256" })).toString("base64url");
  const payload = Buffer.from(
    JSON.stringify({
      sub: "1",
      exp: Math.floor(Date.now() / 1000) + 86400 * 7,
      type: "access",
      ...extra,
    })
  ).toString("base64url");
  return `${header}.${payload}.mock-preview`;
};

// SIGV2-1187: the project dashboard's scan-history card lists this project's
// audits. The compared Overview design draws three rows (two completed Smart
// scans, one failed), so the fixture tells the same story.
const projectAuditHistory = {
  9: [
    {
      id: 903,
      project_id: 9,
      audit_type: "SMART",
      url: "https://northwind-hotels.com",
      audit_target_type: "website",
      geo_score: 62,
      seo_score: 76,
      aeo_score: 64,
      status: "completed",
      created_at: "2026-10-06T10:00:00.000Z",
      full_report: null,
    },
    {
      id: 902,
      project_id: 9,
      audit_type: "SMART",
      url: "https://northwind-hotels.com",
      audit_target_type: "website",
      geo_score: 62,
      seo_score: 76,
      aeo_score: 64,
      status: "completed",
      created_at: "2026-09-28T10:00:00.000Z",
      full_report: null,
    },
    {
      id: 900,
      project_id: 9,
      audit_type: "SMART",
      url: "https://northwind-hotels.com",
      audit_target_type: "website",
      geo_score: 0,
      seo_score: null,
      aeo_score: null,
      status: "failed",
      created_at: "2026-09-18T10:00:00.000Z",
      full_report: null,
    },
  ],
};

// SIGV2-1037 fixtures: the project task board the Fixes page reads status
// from. Titles join to advisor actions by exact text (the backend preserves
// `action` verbatim, and the board row uses the action's short title).
const stubTask = (pid, overrides = {}) => ({
  id: 1,
  project_id: pid,
  title: "Task",
  description: null,
  status: "todo",
  priority: "medium",
  origin: "audit_recommendation",
  category: "Technical",
  source_audit_id: 901,
  source_recommendation_key: null,
  assigned_to_user_id: null,
  assignee: null,
  due_date: null,
  resolved_at: null,
  verified_at: null,
  verification_audit_id: null,
  resolution_source: null,
  sort_order: 0,
  created_at: NOW,
  updated_at: NOW,
  ...overrides,
});

const emptyTaskBoard = (pid) => ({
  project_id: pid,
  workspace_id: 1,
  can_edit: true,
  latest_audit_id: 901,
  latest_audit_at: NOW,
  assignees: [],
  summary: { total: 0, done: 0 },
  tasks: [],
});

const taskBoardByProject = {
  9: {
    ...emptyTaskBoard(9),
    summary: { total: 2, done: 1 },
    tasks: [
      stubTask(9, {
        id: 91,
        title: "Fix crawl and indexation coverage",
        status: "in_progress",
        category: "Technical",
      }),
      stubTask(9, {
        id: 92,
        title: "Add FAQ schema to the location page",
        status: "done",
        category: "Content",
        resolved_at: "2026-09-22T10:00:00.000Z",
        resolution_source: "manual",
      }),
    ],
  },
};

// SIGV2-1036 fixture: a populated visibility-summary so the AIO detail page's
// By engine and Prompts tabs can be photographed with real-shaped monitoring
// data (unlocked entitlements, per-provider scores and per-query results).
const visibilitySummaryByProject = {
  9: {
    project_id: 9,
    entitlements: {
      plan: "plan_standard",
      max_queries: 25,
      used_queries: 4,
      remaining_queries: 21,
      allowed_providers: ["openai", "anthropic", "perplexity", "google"],
      is_locked: false,
      estimated_cost_per_check: {},
    },
    queries_configured: 4,
    providers: ["openai", "anthropic", "perplexity", "google"],
    visibility_score: 55,
    score_breakdown: null,
    trend_delta: 4,
    completed_checks: 9,
    pending_checks: 1,
    cited_checks: 5,
    total_checks: 10,
    last_updated_at: "2026-09-29T10:30:00.000Z",
    provider_breakdown: [
      {
        provider: "openai",
        tracked_queries: 4,
        completed_checks: 4,
        cited_checks: 3,
        visibility_score: 74,
      },
      {
        provider: "anthropic",
        tracked_queries: 4,
        completed_checks: 3,
        cited_checks: 2,
        visibility_score: 58,
      },
      {
        provider: "perplexity",
        tracked_queries: 4,
        completed_checks: 2,
        cited_checks: 0,
        visibility_score: 21,
      },
      {
        provider: "google",
        tracked_queries: 4,
        completed_checks: 0,
        cited_checks: 0,
        visibility_score: null,
      },
    ],
    queries: [
      {
        id: 501,
        project_id: 9,
        query_text: "best boutique hotels near the harbour",
        query_type: "aeo",
        providers: ["openai", "anthropic", "perplexity"],
        is_active: true,
        created_at: "2026-09-20T09:00:00.000Z",
        updated_at: "2026-09-29T10:30:00.000Z",
        average_score: 61,
        last_checked_at: "2026-09-29T10:30:00.000Z",
        results: [
          {
            provider: "openai",
            status: "cited",
            batch_status: null,
            score: 88,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 2,
          },
          {
            provider: "anthropic",
            status: "cited",
            batch_status: null,
            score: 62,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 1,
          },
          {
            provider: "perplexity",
            status: "not_cited",
            batch_status: null,
            score: 33,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 0,
          },
        ],
      },
      {
        id: 502,
        project_id: 9,
        query_text: "tell me about Northwind Hotels",
        query_type: "geo",
        providers: ["openai", "anthropic"],
        is_active: true,
        created_at: "2026-09-20T09:00:00.000Z",
        updated_at: "2026-09-29T10:30:00.000Z",
        average_score: 55,
        last_checked_at: "2026-09-29T10:30:00.000Z",
        results: [
          {
            provider: "openai",
            status: "cited",
            batch_status: null,
            score: 71,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 1,
          },
          {
            provider: "anthropic",
            status: "not_cited",
            batch_status: null,
            score: 39,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 0,
          },
        ],
      },
      {
        id: 503,
        project_id: 9,
        query_text: "quiet hotel with late checkout",
        query_type: "aeo",
        providers: ["perplexity"],
        is_active: true,
        created_at: "2026-09-22T09:00:00.000Z",
        updated_at: "2026-09-29T10:30:00.000Z",
        average_score: null,
        last_checked_at: null,
        results: [
          {
            provider: "perplexity",
            status: "pending",
            batch_status: null,
            score: null,
            score_breakdown: null,
            last_checked_at: null,
            citations_found: 0,
          },
        ],
      },
      {
        id: 504,
        project_id: 9,
        query_text: "Northwind Hotels vs Coastline Resorts",
        query_type: "geo",
        providers: ["openai"],
        is_active: true,
        created_at: "2026-09-24T09:00:00.000Z",
        updated_at: "2026-09-29T10:30:00.000Z",
        average_score: 44,
        last_checked_at: "2026-09-29T10:30:00.000Z",
        results: [
          {
            provider: "openai",
            status: "not_cited",
            batch_status: null,
            score: 44,
            score_breakdown: null,
            last_checked_at: "2026-09-29T10:30:00.000Z",
            citations_found: 0,
          },
        ],
      },
    ],
  },
};

// SIGV2-1036 fixtures: SERP keyword tracking and the Search Console pages
// contract for the SEO detail tabs (keyword + position from the latest dated
// snapshot; pages with GA4 sessions, one sessions-less row and one incomplete
// row so the honest states are photographed).
const serpTrackingByProject = {
  9: {
    project_id: 9,
    total_keywords: 5,
    snippets_owned: 1,
    snippets_gained: 1,
    snippets_lost: 0,
    paa_appearances_total: 3,
    ai_overview_count: 2,
    ai_overview_cited_count: 1,
    latest_snapshots: [
      {
        keyword: "boutique hotel waterfront",
        keyword_id: 601,
        snapshot_date: "2026-09-28",
        owns_featured_snippet: true,
        featured_snippet_url: "https://northwind-hotels.com/rooms",
        paa_appearances: [],
        organic_position: 4,
        serp_features_present: ["featured_snippet"],
        ai_overview_detected: true,
        ai_overview_cites_target: true,
        ai_overview_source_urls: null,
      },
      {
        keyword: "quiet hotel late checkout",
        keyword_id: 602,
        snapshot_date: "2026-09-28",
        owns_featured_snippet: false,
        featured_snippet_url: null,
        paa_appearances: [],
        organic_position: 12,
        serp_features_present: [],
        ai_overview_detected: true,
        ai_overview_cites_target: false,
        ai_overview_source_urls: null,
      },
      {
        keyword: "best hotels near the harbour",
        keyword_id: 603,
        snapshot_date: "2026-09-28",
        owns_featured_snippet: false,
        featured_snippet_url: null,
        paa_appearances: [],
        organic_position: 9,
        serp_features_present: [],
        ai_overview_detected: false,
        ai_overview_cites_target: false,
        ai_overview_source_urls: null,
      },
      {
        keyword: "northwind hotels booking",
        keyword_id: 604,
        snapshot_date: "2026-09-28",
        owns_featured_snippet: false,
        featured_snippet_url: null,
        paa_appearances: [],
        organic_position: 1,
        serp_features_present: [],
        ai_overview_detected: false,
        ai_overview_cites_target: false,
        ai_overview_source_urls: null,
      },
      {
        keyword: "pet friendly seaside hotel",
        keyword_id: 605,
        snapshot_date: "2026-09-28",
        owns_featured_snippet: false,
        featured_snippet_url: null,
        paa_appearances: [],
        organic_position: null,
        serp_features_present: [],
        ai_overview_detected: false,
        ai_overview_cites_target: false,
        ai_overview_source_urls: null,
      },
    ],
  },
};

const targetKeywordsByProject = {
  9: [
    {
      id: 601,
      keyword: "boutique hotel waterfront",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-01T09:00:00.000Z",
    },
    {
      id: 602,
      keyword: "quiet hotel late checkout",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-01T09:00:00.000Z",
    },
    {
      id: 603,
      keyword: "best hotels near the harbour",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-02T09:00:00.000Z",
    },
    {
      id: 604,
      keyword: "northwind hotels booking",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-03T09:00:00.000Z",
    },
    {
      id: 605,
      keyword: "pet friendly seaside hotel",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-04T09:00:00.000Z",
    },
    {
      id: 606,
      keyword: "weekend break by the sea",
      search_engine: "google",
      language_code: "en",
      location_code: null,
      is_active: true,
      created_at: "2026-09-05T09:00:00.000Z",
    },
  ],
};

const gscPagesByProject = {
  9: {
    property: "https://northwind-hotels.com/",
    window: "7D",
    start_date: "2026-09-23",
    end_date: "2026-09-29",
    date_basis: "America/Los_Angeles",
    ga4_property_timezone: "America/New_York",
    date_alignment: "approximate",
    data_state: "all",
    first_incomplete_date: "2026-09-29",
    response_aggregation_type: "byPage",
    completeness: "full",
    partial_reason: null,
    url_normalization: "strip_host_query_fragment_percent_decode_lowercase_preserve_trailing_slash",
    totals: { clicks: 812, impressions: 19100, ctr: 0.0425, position: 7.1 },
    pages: [
      {
        page_key: "/rooms/deluxe-king",
        pages: ["https://northwind-hotels.com/rooms/deluxe-king"],
        collapsed_count: 0,
        clicks: 320,
        impressions: 6800,
        ctr: 0.047,
        avg_position: 3.2,
        sessions: 6240,
        sessions_reason: null,
        incomplete: false,
        opportunity: {
          value: "low_ctr",
          evidence: {
            weighted_position: 3.2,
            impressions: 6800,
            ctr: 0.047,
            band_median_ctr: 0.07,
            min_impressions: 200,
            incomplete: false,
          },
        },
      },
      {
        page_key: "/waterfront",
        pages: ["https://northwind-hotels.com/waterfront"],
        collapsed_count: 0,
        clicks: 240,
        impressions: 5400,
        ctr: 0.044,
        avg_position: 9.1,
        sessions: 4110,
        sessions_reason: null,
        incomplete: false,
        opportunity: {
          value: "striking_distance",
          evidence: {
            weighted_position: 9.1,
            impressions: 5400,
            ctr: 0.044,
            band_median_ctr: null,
            min_impressions: 200,
            incomplete: false,
          },
        },
      },
      {
        page_key: "/amenities",
        pages: ["https://northwind-hotels.com/amenities"],
        collapsed_count: 0,
        clicks: 140,
        impressions: 3200,
        ctr: 0.044,
        avg_position: 6.4,
        sessions: 3580,
        sessions_reason: null,
        incomplete: false,
        opportunity: {
          value: "none",
          evidence: {
            weighted_position: 6.4,
            impressions: 3200,
            ctr: 0.044,
            band_median_ctr: null,
            min_impressions: 200,
            incomplete: false,
          },
        },
      },
      {
        page_key: "/offers/weekend",
        pages: ["https://northwind-hotels.com/offers/weekend"],
        collapsed_count: 0,
        clicks: 72,
        impressions: 2400,
        ctr: 0.03,
        avg_position: 12.3,
        sessions: null,
        sessions_reason: "no_ga4_match",
        incomplete: false,
        opportunity: {
          value: "striking_distance",
          evidence: {
            weighted_position: 12.3,
            impressions: 2400,
            ctr: 0.03,
            band_median_ctr: null,
            min_impressions: 200,
            incomplete: false,
          },
        },
      },
      {
        page_key: "/reviews",
        pages: ["https://northwind-hotels.com/reviews"],
        collapsed_count: 0,
        clicks: 40,
        impressions: 1300,
        ctr: 0.031,
        avg_position: 8.2,
        sessions: 1510,
        sessions_reason: null,
        incomplete: true,
        opportunity: {
          value: "insufficient_data",
          evidence: {
            weighted_position: 8.2,
            impressions: 1300,
            ctr: 0.031,
            band_median_ctr: null,
            min_impressions: 200,
            incomplete: true,
          },
        },
      },
    ],
    series: [],
    fetched_at: "2026-09-29T12:00:00.000Z",
  },
};

// SIGV2-1130: the report library collection. Obviously synthetic fixture rows,
// shaped exactly like the real response, including names in the product's own
// frozen "<Kind> report - <period>" form. Timestamps are relative to the
// request so the rendered Created and Link expiry strings are stable across
// runs instead of drifting with the wall clock.
const reportLibraryFixture = () => {
  const now = Date.now();
  const iso = (ms) => new Date(ms).toISOString();
  const HOUR = 3600 * 1000;
  const DAY = 24 * HOUR;
  const retention_days = 30;
  const row = (overrides) => ({
    report_kind: "standard",
    period_start: null,
    period_end: null,
    size_bytes: null,
    error: null,
    expires_at: null,
    link_expired: false,
    link_expiry_days_remaining: null,
    retention_days,
    download_url: null,
    ...overrides,
  });
  const succeeded = (id, name, kind, created_ms, size_bytes, days_left, period) =>
    row({
      report_id: id,
      name,
      report_kind: kind,
      status: "succeeded",
      created_at: iso(now - created_ms),
      size_bytes,
      expires_at: iso(now + days_left * DAY + HOUR),
      link_expiry_days_remaining: days_left,
      download_url: `/api/v1/reports/complex/${id}/download`,
      ...period,
    });
  const q2 = { period_start: "2026-04-01T00:00:00.000Z", period_end: "2026-06-30T23:59:59.000Z" };
  const june = { period_start: "2026-06-01T00:00:00.000Z", period_end: "2026-06-30T23:59:59.000Z" };
  const q1 = { period_start: "2026-01-01T00:00:00.000Z", period_end: "2026-03-31T23:59:59.000Z" };
  const may = { period_start: "2026-05-01T00:00:00.000Z", period_end: "2026-05-31T23:59:59.000Z" };
  const items = [
    row({
      report_id: "stub-running",
      name: "Standard report - all time, 5 Oct 2026",
      status: "running",
      created_at: iso(now - 20 * 1000),
    }),
    succeeded(
      "stub-standard-q2",
      "Standard report - 1 Apr 2026 to 30 Jun 2026",
      "standard",
      2 * HOUR,
      2_516_582,
      6,
      q2
    ),
    succeeded(
      "stub-executive-june",
      "Executive report - 1 Jun 2026 to 30 Jun 2026",
      "executive",
      DAY,
      3_250_585,
      5,
      june
    ),
    succeeded(
      "stub-competitors",
      "Competitors report - all time, 2 Oct 2026",
      "competitors",
      3 * DAY,
      1_887_436,
      3,
      {}
    ),
    succeeded(
      "stub-financial",
      "Financial report - 1 Apr 2026 to 30 Jun 2026",
      "financial",
      6 * DAY,
      962_560,
      1,
      q2
    ),
    row({
      report_id: "stub-project-expired",
      name: "Project report - all time, 28 Sep 2026",
      report_kind: "project",
      status: "expired",
      created_at: iso(now - 7 * DAY),
      size_bytes: 12_288,
      link_expired: true,
      link_expiry_days_remaining: 0,
    }),
    row({
      report_id: "stub-standard-q1-expired",
      name: "Standard report - 1 Jan 2026 to 31 Mar 2026",
      status: "expired",
      created_at: iso(now - 14 * DAY),
      size_bytes: 2_306_867,
      link_expired: true,
      link_expiry_days_remaining: 0,
      ...q1,
    }),
    row({
      report_id: "stub-executive-failed",
      name: "Executive report - 1 May 2026 to 31 May 2026",
      report_kind: "executive",
      status: "failed",
      created_at: iso(now - 21 * DAY),
      error: "Report generation timed out (no heartbeat detected)",
      ...may,
    }),
  ];
  return { items, total: items.length, limit: 100, offset: 0 };
};

// The app's onboarding fetch does not send X-Workspace-Id, so key onboarding
// state off the last workspace header seen on requests that do carry it
// (workspaces/current, projects), matching a session-scoped backend.
let lastSeenWs = 1;

const wid = (req) => {
  const raw = req.headers["x-workspace-id"];
  const id = parseInt(Array.isArray(raw) ? raw[0] : (raw ?? "0"), 10);
  if (projectsByWorkspace[id] !== undefined) {
    lastSeenWs = id;
    return id;
  }
  return lastSeenWs;
};

http
  .createServer((req, res) => {
    const url = new URL(req.url, "http://x");
    const p = url.pathname;
    const id = wid(req);
    let status = 404;
    let body = { detail: `stub: no route ${p}` };

    const ok = (b) => {
      status = 200;
      body = b;
    };

    if (p === "/api/v1/auth/me") ok(user);
    else if (p === "/api/v1/auth/login" || p === "/api/v1/auth/refresh") {
      ok({ access_token: fakeJwt(), refresh_token: fakeJwt({ type: "refresh", remember_me: true }) });
    } else if (p === "/api/v1/users/me")
      ok({ ...user, trial: { is_trial: false, trial_active: false, trial_expired: false } });
    else if (p === "/api/v1/users/me/onboarding") {
      if (req.method === "PATCH") {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", () => {
          const patch = JSON.parse(raw || "{}");
          const ob = onboardingByWs[id];
          const add = patch.add_completed_steps ?? patch.completed_steps ?? [];
          ob.steps = [...new Set([...ob.steps, ...add])];
          if (patch.dismissed === true) ob.dismissed = NOW;
          res.writeHead(200, { "content-type": "application/json" });
          res.end(
            JSON.stringify({
              completed_steps: ob.steps,
              started_at: NOW,
              dismissed_at: ob.dismissed,
              updated_at: NOW,
            })
          );
        });
        return;
      }
      const ob = onboardingByWs[id];
      ok({
        completed_steps: ob.steps,
        started_at: null,
        dismissed_at: ob.dismissed,
        updated_at: NOW,
      });
    } else if (p === "/api/v1/auth/passkeys/list") ok([{ id: "pk-1", name: "Laptop" }]);
    else if (p === "/api/v1/workspaces") ok(workspaces);
    else if (p === "/api/v1/workspaces/current") ok(workspaces.find((w) => w.id === id));
    else if (p === "/api/v1/workspaces/current/projects") ok(projectsByWorkspace[id]);
    // Team badge counts in the settings tab strip come from this list; the
    // design draws one owner row (Team 1, Client Access 0).
    else if (p === "/api/v1/workspaces/current/members")
      ok([
        {
          user_id: user.id,
          email: user.email,
          role: "ADMIN",
          is_owner: true,
          created_at: NOW,
        },
      ]);
    else if (p === "/api/v1/workspaces/current/oauth-connections") ok([]);
    else if (/^\/api\/v1\/workspaces\/\d+\/trends\/overview$/.test(p)) ok(trendsByWorkspace[id]);
    // SIGV2-1035: GA4 site-traffic contract (see docs/ga4-reporting-contract.md).
    else if (/^\/api\/v1\/projects\/\d+\/monitoring\/site-traffic$/.test(p)) {
      ok(siteTrafficFor(url.searchParams.get("window") ?? "7D"));
    }
    // SIGV2-1036: visibility monitoring summary for the AIO detail tabs.
    else if (/^\/api\/v1\/projects\/\d+\/monitoring\/visibility-summary$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const summary = visibilitySummaryByProject[pid];
      if (summary) ok(summary);
      else {
        status = 404;
        body = { detail: "Visibility summary not found" };
      }
    }
    // SIGV2-1194: the prompt list + per-type coverage the approved prompt
    // setup reads, on both the scan-setup section and the AIO Prompts tab.
    // Without this route the whole surface photographed its "unavailable"
    // state and the gate measured nothing. Project 9 carries four generated
    // prompts covering brand/category/problem/feature and leaves comparison
    // uncovered, so the incomplete state (uncovered group open, info notice,
    // add-starter action) is the state compared.
    else if (/^\/api\/v1\/projects\/\d+\/monitoring\/visibility-queries$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      if (req.method === "POST") {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", () => {
          const payload = JSON.parse(raw || "{}");
          res.writeHead(200, { "content-type": "application/json" });
          res.end(
            JSON.stringify(
              stubVisibilityQuery(pid, {
                query_text: payload.query_text ?? "",
                query_type: payload.query_type ?? "aeo",
                providers: payload.providers ?? ["openrouter"],
                search_type: payload.search_type ?? null,
                origin: "customer",
                is_generated: false,
              })
            )
          );
        });
        return;
      }
      ok(visibilityQueriesPayload(pid));
    } else if (
      /^\/api\/v1\/projects\/\d+\/monitoring\/visibility-queries\/generate-base$/.test(p) &&
      req.method === "POST"
    ) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const created = coverageFor(pid)
        .filter((entry) => !entry.covered && entry.suggested_prompt)
        .map((entry) =>
          stubVisibilityQuery(pid, {
            query_text: entry.suggested_prompt,
            query_type: "aeo",
            providers: ["openrouter"],
            search_type: entry.id,
            origin: "generated",
            is_generated: true,
          })
        );
      ok({
        project_id: pid,
        reason: created.length ? "created" : "already_covered",
        created,
        coverage: coverageFor(pid).map((entry) => ({
          ...entry,
          covered: true,
          prompt_count: Math.max(1, entry.prompt_count),
          suggested_prompt: null,
        })),
        entitlements: visibilityEntitlements(),
      });
    } else if (/^\/api\/v1\/projects\/\d+\/monitoring\/visibility-queries\/\d+$/.test(p)) {
      const qid = Number(p.match(/visibility-queries\/(\d+)/)?.[1]);
      if (req.method === "DELETE") {
        status = 204;
        body = null;
      } else if (req.method === "PATCH") {
        let raw = "";
        req.on("data", (c) => (raw += c));
        req.on("end", () => {
          const payload = JSON.parse(raw || "{}");
          const existing = stubQueriesFor(Number(p.match(/projects\/(\d+)/)?.[1])).find(
            (q) => q.id === qid
          );
          res.writeHead(200, { "content-type": "application/json" });
          res.end(
            JSON.stringify({
              ...existing,
              ...payload,
              id: qid,
              // An edit makes the row the customer's own.
              ...(payload.query_text !== undefined
                ? { origin: "customer", is_generated: false }
                : {}),
              updated_at: NOW,
            })
          );
        });
        return;
      }
    }
    // SIGV2-1036: SERP keyword tracking, tracked keywords and Search Console
    // pages for the SEO detail tabs.
    else if (/^\/api\/v1\/projects\/\d+\/monitoring\/serp-tracking$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(
        serpTrackingByProject[pid] ?? {
          project_id: pid,
          total_keywords: 0,
          snippets_owned: 0,
          snippets_gained: 0,
          snippets_lost: 0,
          paa_appearances_total: 0,
          ai_overview_count: 0,
          ai_overview_cited_count: 0,
          latest_snapshots: [],
        }
      );
    } else if (/^\/api\/v1\/projects\/\d+\/monitoring\/keywords$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(targetKeywordsByProject[pid] ?? []);
    } else if (/^\/api\/v1\/projects\/\d+\/monitoring\/search-console\/pages$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const payload = gscPagesByProject[pid];
      if (payload) ok(payload);
      else ok({ status: "disconnected", availability: "disconnected" });
    }
    // SIGV2-1037: project task board + recommendation decisions for the Fixes
    // page. One in-progress row matching advisor action 1 and one done orphan
    // so the dimmed record card photographs like the approved mock.
    else if (/^\/api\/v1\/projects\/\d+\/competitors$/.test(p) && req.method === "GET") {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(projectCompetitors[pid] ?? []);
    } else if (/^\/api\/v1\/projects\/\d+\/competitive-analysis\/trends/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(competitiveTrends(pid, req.url ?? ""));
    } else if (/^\/api\/v1\/projects\/\d+\/competitive-analysis\/gaps/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(competitiveGaps[pid] ?? { project_id: pid, gaps: [] });
    } else if (/^\/api\/v1\/projects\/\d+\/competitive-analysis$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(competitiveAnalysis[pid] ?? null);
    } else if (/^\/api\/v1\/projects\/\d+\/tasks$/.test(p) && req.method === "GET") {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(taskBoardByProject[pid] ?? emptyTaskBoard(pid));
    } else if (/^\/api\/v1\/projects\/\d+\/tasks$/.test(p) && req.method === "POST") {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok({ ...stubTask(pid, { title: "Created task", status: "done" }), id: 990 });
    } else if (/^\/api\/v1\/projects\/\d+\/tasks\/\d+$/.test(p) && req.method === "PUT") {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const tid = Number(p.match(/tasks\/(\d+)/)?.[1]);
      ok({ ...stubTask(pid, { title: "Updated task", status: "done" }), id: tid });
    } else if (
      /^\/api\/v1\/projects\/\d+\/recommendation-decisions$/.test(p) &&
      req.method === "GET"
    ) {
      ok([]);
    } else if (
      /^\/api\/v1\/projects\/\d+\/recommendation-decisions$/.test(p) &&
      req.method === "POST"
    ) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok({
        id: 991,
        project_id: pid,
        action_fingerprint: "stub",
        action_label: null,
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: NOW,
      });
    }
    // SIGV2-1035 part 2: project detail + latest audit (full report) fixtures.
    else if (/^\/api\/v1\/projects\/\d+\/audits\/latest$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(latestAuditByProject[pid] ?? null);
    }
    // SIGV2-1187: the dashboard scan-history card's list endpoint. Registered
    // before the bare `/projects/{id}` catch-all below.
    else if (/^\/api\/v1\/projects\/\d+\/audits$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(projectAuditHistory[pid] ?? []);
    }
    // SIGV2-1178: project settings' Connected data card and the overview's
    // GA4 provenance both read this. The fixture reproduces the serializer's
    // per-source-type list for the approved design state (GA4 bound via a
    // client magic link, so no workspace OAuth grant is held and Search
    // Console + Bing correctly offer "Connect"). Unknown projects get the
    // all-unbound triplet the real endpoint always returns.
    else if (/^\/api\/v1\/projects\/\d+\/data-sources$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const emptyBinding = (sourceType, provider) => ({
        id: null,
        project_id: pid,
        provider,
        source_type: sourceType,
        binding_mode: "workspace",
        source_id: null,
        source_label: null,
        is_active: false,
        oauth_connection_id: null,
        project_oauth_connection_id: null,
        workspace_provider_connected: false,
        updated_at: null,
      });
      ok(
        projectDataSourcesByProject[pid] ?? [
          emptyBinding("google_search_console", "google"),
          emptyBinding("google_analytics_4", "google"),
          emptyBinding("bing_webmaster", "bing"),
        ]
      );
    }
    // SIGV2-1178: the project-overview score gauges read this for the delta
    // and sparkline delivered in SIGV2-1181. Without it the harness
    // photographs the no-history state and that component is never gated.
    else if (/^\/api\/v1\/projects\/\d+\/trends$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(
        projectTrendsByProject[pid] ?? {
          project_id: pid,
          period: url.searchParams.get("period") ?? "90d",
          granularity: url.searchParams.get("granularity") ?? "weekly",
          data_points: [],
          summary: {
            first: null,
            latest: null,
            delta: { seo: null, geo: null, aeo: null, overall: null },
            trend_direction: { seo: "stable", geo: "stable", aeo: "stable", overall: "stable" },
          },
        }
      );
    }
    // Budget guardrails + monitoring alerts on the project settings page.
    // The design draws the no-cap state (cycle Jul 1 - Aug 1, 0 scans,
    // Unlimited) and the empty alert list; without these routes both cards
    // render their error toast on every capture.
    else if (/^\/api\/v1\/workspaces\/\d+\/projects\/\d+\/budget$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const proj = projectDetails[pid];
      ok({
        project_id: pid,
        workspace_id: id,
        project_name: proj?.name ?? "Project",
        domain_url: proj?.domain_url ?? null,
        budget_configured: false,
        monthly_limit_scans: null,
        cycle_anchor_day: 1,
        current_period_start: "2026-07-01",
        current_period_end: "2026-08-01",
        consumed_scans: 0,
        remaining_scans: null,
        percent_consumed: null,
        status: "unlimited",
        warning_threshold_reached: false,
        limit_reached: false,
        recent_periods: [],
      });
    } else if (/^\/api\/v1\/projects\/\d+\/alerts$/.test(p)) {
      ok([]);
    }
    // Per-project audit list (dashboard scan-history card and the projects
    // table read it). Same fixture the SIGV2-1187 branch serves.
    else if (/^\/api\/v1\/projects\/\d+\/audits$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok(projectAuditHistory[pid] ?? []);
    }
    // Single audit record by id - the results/detail screens refetch their
    // audit this way even after reading it from the project route. Serves the
    // scan-history rows only: audit 901 must stay unresolvable so the
    // audit-run comparison keeps photographing its documented "audit not
    // found" state (see screens.mjs, SIGV2-1038).
    else if (/^\/api\/v1\/audits\/\d+$/.test(p)) {
      const aid = Number(p.match(/audits\/(\d+)/)?.[1]);
      const found =
        mockPreviewAuditsById[aid] ??
        Object.values(projectAuditHistory)
          .flat()
          .find((a) => a.id === aid);
      if (found) ok(found);
      else {
        status = 404;
        body = { detail: "Audit not found" };
      }
    } else if (/^\/api\/v1\/audits\/\d+\/review-summary$/.test(p)) {
      const aid = Number(p.match(/audits\/(\d+)/)?.[1]);
      ok({
        audit_id: aid,
        total_flagged: 0,
        approved_count: 0,
        refused_count: 0,
        pending_count: 0,
        impact: { score_recalculated: false, export_excluded_claims: 0, note: "" },
      });
    }
    // Score deltas vs the previous completed run for the same target.
    else if (/^\/api\/v1\/audit\/\d+\/comparison$/.test(p)) {
      const aid = Number(p.match(/audit\/(\d+)/)?.[1]);
      ok({
        audit_id: aid,
        has_previous: true,
        previous_audit_id: 900,
        previous_audit_date: "2026-09-18T10:00:00.000Z",
        scores: {
          overall: { current: 64, previous: 58, delta: 6, direction: "up" },
          seo: { current: 72, previous: 68, delta: 4, direction: "up" },
          geo: { current: 61, previous: 55, delta: 6, direction: "up" },
          aeo: { current: 61, previous: 60, delta: 1, direction: "stable" },
        },
        sub_components: {},
        history: [
          {
            audit_id: 900,
            date: "2026-09-18T10:00:00.000Z",
            overall: 58,
            seo: 68,
            geo: 55,
            aeo: 60,
          },
          {
            audit_id: 901,
            date: "2026-09-29T10:00:00.000Z",
            overall: 64,
            seo: 72,
            geo: 61,
            aeo: 61,
          },
        ],
      });
    }
    // Measured per-tier durations (SIGV2-1177): the launch sentence and the
    // depth table read these, and the approved design states a figure for
    // each tier.
    else if (p === "/api/v1/audit/tier-durations")
      ok({
        statistic: "p25..p75",
        min_sample_size: 5,
        window_days: 90,
        tiers: {
          fast: {
            low_minutes: 4,
            high_minutes: 7,
            median_minutes: 5,
            sample_size: 128,
            window_days: 90,
            computed_at: NOW,
          },
          smart: {
            low_minutes: 12,
            high_minutes: 19,
            median_minutes: 15,
            sample_size: 96,
            window_days: 90,
            computed_at: NOW,
          },
          deep_judgment: {
            low_minutes: 33,
            high_minutes: 52,
            median_minutes: 41,
            sample_size: 26,
            window_days: 90,
            computed_at: NOW,
          },
        },
      });
    // GA4 magic-link binding status - project 9 is bound via a client link
    // (project_oauth_connection_id 7 in the data-sources fixture), so the
    // status is connected with a google provider row.
    else if (/^\/api\/v1\/projects\/\d+\/magic-link-status$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      ok({
        project_id: pid,
        status: pid === 9 ? "connected" : "not_requested",
        latest_link_created_at: pid === 9 ? "2026-09-25T09:00:00.000Z" : null,
        latest_link_expires_at: null,
        latest_link_is_used: pid === 9,
        open_magic_link_count: 0,
        providers:
          pid === 9
            ? [
                {
                  provider: "google",
                  connected: true,
                  connected_at: "2026-09-25T10:00:00.000Z",
                  connected_by_email: "owner@northwind-hotels.com",
                  has_refresh_token: true,
                  expires_at: null,
                  scope: "https://www.googleapis.com/auth/analytics.readonly",
                },
              ]
            : [],
      });
    }
    // Picker catalogues for the Connect flow: no workspace OAuth grant is
    // held in this fixture state, so each catalogue reports that honestly.
    else if (/^\/api\/v1\/projects\/\d+\/data-sources\/[a-z_0-9]+\/catalog$/.test(p)) {
      const sourceType = p.match(/data-sources\/([a-z_0-9]+)\/catalog/)?.[1];
      ok({
        source_type: sourceType,
        provider: sourceType === "bing_webmaster" ? "bing" : "google",
        workspace_provider_connected: false,
        items: [],
        required_scopes: [],
        granted_scopes: [],
        missing_scopes: [],
        error: null,
        fetched_at: NOW,
      });
    }
    // Developer tab: the API key list (empty) and the workspace cost
    // breakdown, which is the same budget-guardrail shape per project.
    else if (p === "/api/v1/settings/api-keys")
      ok({
        items: [],
        plan_type: "plan_executive",
        api_access_enabled: true,
        developer_hub_url: "/dashboard/developer",
      });
    else if (/^\/api\/v1\/workspaces\/\d+\/cost-breakdown$/.test(p)) {
      ok({
        workspace_id: id,
        generated_at: NOW,
        projects: (projectsByWorkspace[id] ?? []).map((proj) => ({
          project_id: proj.id,
          workspace_id: id,
          project_name: proj.name,
          domain_url: proj.domain_url ?? null,
          budget_configured: false,
          monthly_limit_scans: null,
          cycle_anchor_day: 1,
          current_period_start: "2026-07-01",
          current_period_end: "2026-08-01",
          consumed_scans: proj.audit_count ?? 0,
          remaining_scans: null,
          percent_consumed: null,
          status: "unlimited",
          warning_threshold_reached: false,
          limit_reached: false,
          recent_periods: [],
        })),
      });
    }
    // Account settings boot fan-out: profile, notification preferences, MFA
    // status, white-label branding - all served so My Profile renders its
    // real state instead of a boot error.
    else if (p === "/api/v1/users/me/profile")
      ok({
        user_id: user.id,
        email: user.email,
        name: user.name,
        company_legal_name: null,
        company_registration_number: null,
        company_vat_number: null,
        billing_email: null,
        billing_phone: null,
        billing_address_line1: null,
        billing_address_line2: null,
        billing_city: null,
        billing_state: null,
        billing_postal_code: null,
        billing_country: null,
        billing_website_url: null,
        billing_tax_exempt: false,
        stripe_customer_id: null,
        role: "OWNER",
        notifications_enabled: true,
        mfa_enabled: false,
      });
    else if (p === "/api/v1/users/me/notification-preferences")
      ok({
        user_id: user.id,
        notifications_enabled: true,
        notify_product_updates: true,
        notify_audit_alerts: true,
        notify_billing: true,
      });
    else if (p === "/api/v1/users/me/mfa/status") ok({ enabled: false });
    else if (p === "/api/v1/users/me/branding")
      ok({
        custom_logo_url: null,
        company_name: null,
        primary_color: null,
        secondary_color: null,
      });
    // Browser CSP violation reports: fire-and-forget, acknowledge quietly.
    else if (p === "/api/v1/csp-report") ok({});
    else if (/^\/api\/v1\/projects\/\d+$/.test(p)) {
      const pid = Number(p.match(/projects\/(\d+)/)?.[1]);
      const proj = projectDetails[pid];
      if (proj) ok(proj);
      else {
        status = 404;
        body = { detail: "Project not found" };
      }
    }
    // 503 so /maintenance renders its card; a 200 would redirect it home.
    // Deliberately no `message`: the page must fall back to its own approved
    // i18n copy, so the baseline asserts product text, not fixture prose.
    else if (p === "/api/v1/system-status/health") {
      status = 503;
      body = { status: "maintenance" };
    }
    // Test-only reset so a spec can start from pristine onboarding state
    // regardless of what earlier specs PATCHed.
    else if (p === "/api/v1/__reset" && req.method === "POST") {
      onboardingByWs[1] = { steps: [], dismissed: null };
      onboardingByWs[2] = { steps: [], dismissed: null };
      ok({ reset: true });
    } else if (p === "/api/v1/reports/complex" && req.method === "GET") {
      ok(reportLibraryFixture());
    } else if (p === "/api/v1/reports/export-variants") {
      // SIGV2-1124: the approved Export menu's locks come from the backend.
      // The stub user is on plan_standard, so this mirrors what
      // CAPABILITY_MATRIX grants that plan: the Standard PDF only.
      ok({
        plan: user.subscription_plan,
        variants: [
          {
            key: "standard",
            report_type: "standard",
            report_kind: null,
            template_type: "Executive",
            locked: false,
            required_capability: "has_pdf_audit_reports",
            required_plan: "plan_starter",
            required_plan_label: "Starter",
          },
          {
            key: "branded",
            report_type: "branded",
            report_kind: null,
            template_type: "Executive",
            locked: true,
            required_capability: "has_advanced_reporting",
            required_plan: "plan_specialist",
            required_plan_label: "Specialist",
          },
          {
            key: "competitors",
            report_type: "standard",
            report_kind: "competitors",
            template_type: "Executive",
            locked: true,
            required_capability: "has_competitor_analysis",
            required_plan: "plan_specialist",
            required_plan_label: "Specialist",
          },
          {
            key: "whitelabel",
            report_type: "whitelabel",
            report_kind: null,
            template_type: "Executive",
            locked: true,
            required_capability: "pdf_white_label",
            required_plan: "plan_executive",
            required_plan_label: "Executive",
          },
        ],
      });
    } else if (p === "/api/v1/maintenance-notice") ok({ active: false, notice: null });
    else if (p === "/api/v1/billing/scan-warning") ok({ show: false });
    // SIGV2-1178: the real catalogue from public_plan_catalog.py (verbatim
    // fixture) plus the current subscription the approved design draws:
    // "Current plan: Executive". Without this route the billing page's plan
    // load failed on every capture and the budgets were calibrated on the
    // silent "Free" fallback instead of the real page.
    else if (p === "/api/v1/billing/plans") ok(billingPlans);
    else if (p === "/api/v1/billing/invoices") {
      const limit = Number(url.searchParams.get("limit"));
      ok({
        invoices:
          Number.isInteger(limit) && limit > 0
            ? billingInvoices.invoices.slice(0, limit)
            : billingInvoices.invoices,
      });
    } else if (p === "/api/v1/billing/usage-analytics") ok(usageAnalytics);
    // SIGV2-1039: the real WorkspaceWhiteLabelSettingsResponse shape. The old
    // `{ enabled: false }` matched no schema in the backend and would have
    // rendered the White-Label tab as an empty form. The tab is not the
    // default one, so this is not reached by the design comparison, but a stub
    // that answers in a shape the product never serves is a trap.
    else if (p === "/api/v1/workspaces/current/white-label")
      ok({
        workspace_id: 1,
        workspace_name: "jake Workspace",
        company_name: "jake Workspace",
        custom_logo_url: null,
        primary_color: "#6366F1",
        secondary_color: "#22D3EE",
        custom_favicon_url: null,
        custom_page_title: "Signal by jake",
        custom_meta_description: null,
        hide_powered_by: false,
        email_sender_name: null,
        email_reply_to: null,
        social_facebook_url: null,
        social_x_url: null,
        social_instagram_url: null,
        social_linkedin_url: null,
        social_youtube_url: null,
        social_tiktok_url: null,
        company_address: null,
        company_legal_name: null,
        company_trademark_text: null,
        footer_about_url: null,
        footer_blog_url: null,
        footer_support_url: null,
        footer_legal_url: null,
        footer_preferences_url: null,
        footer_privacy_url: null,
        dns_target: "custom.qiko.ai",
        domains: [],
      });

    if (status === 404) console.log(`stub miss: ${req.method} ${p}`);
    res.writeHead(status, { "content-type": "application/json" });
    res.end(JSON.stringify(body));
  })
  .listen(Number(process.env.PORT || 8000), "0.0.0.0", () =>
    console.log(`stub backend on :${process.env.PORT || 8000}`)
  );
