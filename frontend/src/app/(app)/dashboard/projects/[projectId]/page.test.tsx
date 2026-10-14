import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectOverviewPage from "@/app/(app)/dashboard/projects/[projectId]/page";
import { peekScanLaunchIntent, SCAN_LAUNCH_INTENT_KEY } from "@/lib/scanLaunchIntent";
import { ADVISOR_PLAN_ALLOWED, ADVISOR_PLAN_LOCKED } from "@/test/advisorPlanAccessFixtures";
import "@/i18n";

const mocks = vi.hoisted(() => ({
  useProjectLatestAudit: vi.fn(),
  useSiteTraffic: vi.fn(),
  traffic: vi.fn(() => null),
  recommendations: vi.fn(),
  history: vi.fn(),
  trends: vi.fn(),
  getToken: vi.fn(async () => "token"),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchProjectAudits: mocks.history,
  fetchProjectTrends: mocks.trends,
}));

// The overview panel now asks monitoring for the visibility summary; tests
// that need it override this mock per-case.
vi.mock("@/services/monitoringService", () => ({
  fetchVisibilitySummary: vi.fn(async () => {
    throw new Error("no monitoring run");
  }),
}));

vi.mock("@/components/dashboard/LLMTrafficChart", () => ({ default: mocks.traffic }));
vi.mock("@/lib/deriveRecommendations", async () => ({
  ...(await vi.importActual<typeof import("@/lib/deriveRecommendations")>(
    "@/lib/deriveRecommendations"
  )),
  deriveRecommendations: mocks.recommendations,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
}));

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: mocks.useProjectLatestAudit,
}));

vi.mock("@/hooks/useSiteTraffic", () => ({
  useSiteTraffic: mocks.useSiteTraffic,
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: mocks.getToken,
    isSignedIn: true,
    user: null,
  }),
}));

vi.mock("@/types/auditResult", () => ({
  isAuditResult: () => true,
}));

const baseProject = {
  id: 42,
  name: "Client Project",
  domain_url: "https://client.example",
  audit_count: 12,
  last_audit_at: "2026-03-01T10:00:00.000Z",
  latest_seo_score: 81,
  latest_aeo_score: 74,
  latest_geo_score: 69,
  feature_access: {},
  competitors: [],
};

const baseLatestAudit = {
  id: 101,
  url: "https://client.example",
  status: "completed",
  full_report: {
    seo: { onpage: 82, performance: 72, indexing: 89 }, // avg -> 81
    aeo: { answerability_score: 74 },
    geo: { visibility_index: 69 }, // AIO = mean(74,69) -> 72
    metadata: {},
  },
};

describe("ProjectOverviewPage (signal-MVP dashboard)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    mocks.recommendations.mockReturnValue([]);
    mocks.history.mockResolvedValue([]);
    // No score history by default: the gauges then carry no trend at all.
    mocks.trends.mockRejectedValue(new Error("no trend history"));
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: baseLatestAudit,
    });
    mocks.useSiteTraffic.mockReturnValue({
      traffic: null,
      loading: true,
      error: null,
      window: "7D",
      setWindow: vi.fn(),
      refetch: vi.fn(),
    });
  });

  it("renders the R1 overview with explained scores and clear next steps", () => {
    render(<ProjectOverviewPage />);

    expect(screen.getByRole("heading", { name: "Dashboard", level: 1 })).toBeInTheDocument();
    // Approved spanel layout: each panel links out via its suggestions pill.
    expect(screen.getByRole("link", { name: /AIO improvement suggestions/ })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers"
    );
    expect(screen.getByRole("link", { name: /SEO improvement suggestions/ })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/google"
    );
    expect(screen.getByText("AI tools search results")).toBeInTheDocument();
    expect(screen.getByText("Search engine ranking")).toBeInTheDocument();
    // The approved header's Rescan uses the real audit launch path and shows
    // the actual last-audit timestamp. SIGV2-1184: the link names the target
    // this project last scanned, so the setup form is not empty on arrival.
    const rescan = screen.getByRole("link", { name: /Rescan/ });
    expect(rescan).toHaveAttribute(
      "href",
      "/dashboard/audit?projectId=42&tab=overview&url=https%3A%2F%2Fclient.example&targetName=Client+Project&targetType=website"
    );
    // "(...)" carries the real last-audit timestamp (relative when recent).
    expect(rescan.textContent).toMatch(/\(.+\)/);

    // Real derived scores: SEO = mean(82,72,89)=81, AIO = mean(74,69)=72.
    expect(screen.getAllByText("81").length).toBeGreaterThan(0);
    expect(screen.getAllByText("72").length).toBeGreaterThan(0);

    // AI engines strip + prioritised-fixes section are always present.
    expect(screen.queryByText("AI engines measured")).not.toBeInTheDocument();
    expect(screen.queryByText("ChatGPT")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prioritised fixes" })).toBeInTheDocument();
    expect(mocks.traffic).not.toHaveBeenCalled();
    expect(screen.queryByText("MONITORING")).not.toBeInTheDocument();
  });

  it("shows only the three highest-ranked actions and links to the full list", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: ADVISOR_PLAN_ALLOWED },
      latestAudit: baseLatestAudit,
    });
    mocks.recommendations.mockReturnValue([
      {
        title: "Clarify your description",
        description: "Explain what your business does.",
        impact: "Optimization",
        category: "AEO",
      },
      {
        title: "Fix the missing page title",
        description: "Give this page a clear title.",
        impact: "Critical",
        category: "SEO",
      },
      {
        title: "Update your contact details",
        description: "Keep the address consistent.",
        impact: "Strategic",
        category: "GEO",
      },
      {
        title: "Fourth action",
        description: "Not in the summary.",
        impact: "Optimization",
        category: "SEO",
      },
    ]);
    render(<ProjectOverviewPage />);
    const region = screen.getByRole("region", { name: "Prioritised fixes" });
    const actionTitles = within(region)
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(actionTitles).toEqual([
      "Fix the missing page title",
      "Update your contact details",
      "Clarify your description",
    ]);
    // The approved row links out through the advisor-plan side panel.
    expect(within(region).getAllByRole("link", { name: /Open action plan/ })).toHaveLength(3);
    for (const link of within(region).getAllByRole("link", { name: /Open action plan/ })) {
      expect(link).toHaveAttribute("href", "/dashboard/projects/42/fixes");
    }
    // Categorical impact and the real category chip; no invented point delta.
    expect(within(region).getByText("High impact")).toBeInTheDocument();
    expect(within(region).getByText("Medium impact")).toBeInTheDocument();
    expect(within(region).getAllByText("SEO").length).toBeGreaterThan(0);
    expect(within(region).queryByText(/\+\d+ est/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Fourth action")).not.toBeInTheDocument();
  });

  it("does not invent scores or movement before the first check", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: {
        ...baseProject,
        audit_count: 0,
        last_audit_at: null,
        latest_seo_score: null,
        latest_aeo_score: null,
        latest_geo_score: null,
      },
      latestAudit: null,
    });
    render(<ProjectOverviewPage />);
    // Two visibility rings plus the reputation gauge name the unmeasured
    // state instead of rendering a bare dash (SIGV2-1097).
    expect(screen.getAllByText("Not checked")).toHaveLength(3);
    // A project that was never scanned gets the first-scan wording instead of
    // "Rescan" - a scan that does not exist cannot be re-run.
    const rescan = screen.getByRole("link", { name: /Run first scan/ });
    expect(rescan).not.toHaveTextContent(/ago/);
    // With no audit to repeat the target is the project's own domain, so the
    // first scan still arrives at a filled-in form (SIGV2-1184).
    expect(rescan).toHaveAttribute(
      "href",
      "/dashboard/audit?projectId=42&tab=overview&url=https%3A%2F%2Fclient.example&targetName=Client+Project&targetType=website"
    );
    expect(screen.queryByText(/since (the |your )?previous check/i)).not.toBeInTheDocument();
    expect(mocks.traffic).not.toHaveBeenCalled();
  });

  // SIGV2-1184 gave Rescan a target, so the setup form is no longer empty on
  // arrival. SIGV2-1256 took the launch authority back out of it: recording
  // an intent here made the audit page start the run by itself, so a single
  // click went straight to a running scan with nothing left to choose and one
  // of the plan's scans already spent. The href prefills the form and stops
  // there; the customer presses Start. Auto-start stays where the wizard has
  // already collected the configuration (SIGV2-1159).
  describe("Rescan (SIGV2-1184, SIGV2-1256)", () => {
    it("prefills the setup form without authorising a run", () => {
      render(<ProjectOverviewPage />);

      expect(window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY)).toBeNull();

      const rescan = screen.getByRole("link", { name: /Rescan/ });
      expect(rescan).toHaveAttribute(
        "href",
        "/dashboard/audit?projectId=42&tab=overview&url=https%3A%2F%2Fclient.example&targetName=Client+Project&targetType=website"
      );

      fireEvent.click(rescan);

      // Pressing it authorises nothing, so the audit page's auto-start has no
      // intent to act on and the customer lands on the form.
      expect(window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY)).toBeNull();
      expect(peekScanLaunchIntent()).toBeNull();
    });

    it("authorises nothing when the project has no resolvable target", () => {
      mocks.useProjectLatestAudit.mockReturnValue({
        loading: false,
        error: null,
        project: { ...baseProject, domain_url: null, last_audit_at: null },
        latestAudit: null,
      });

      render(<ProjectOverviewPage />);

      const rescan = screen.getByRole("link", { name: /Run first scan/ });
      // No target to prefill, so the setup form opens as it always did.
      expect(rescan).toHaveAttribute(
        "href",
        "/dashboard/audit?projectId=42&tab=overview&targetType=website"
      );
      fireEvent.click(rescan);
      expect(window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY)).toBeNull();
    });
  });

  it("does not turn an empty action list into an all-clear claim", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: ADVISOR_PLAN_ALLOWED },
      latestAudit: baseLatestAudit,
    });
    render(<ProjectOverviewPage />);
    expect(screen.getByText("No priority actions are listed for this check.")).toBeInTheDocument();
    expect(screen.queryByText(/you're in good shape/i)).not.toBeInTheDocument();
  });

  it("keeps the UI-only pass on existing data without fetching comparison history", async () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: {
        ...baseLatestAudit,
        project_id: 42,
        audit_type: "STANDARD",
        created_at: "2026-03-01T10:00:00Z",
        seo_score: 81,
        aeo_score: 74,
        geo_score: 69,
      },
    });
    await act(async () => {
      render(<ProjectOverviewPage />);
    });
    // The scan-history card owns the single audits-list call (SIGV2-1187);
    // the assertion that matters stays: no comparison-history fetch feeds a
    // made-up trend line.
    expect(mocks.history).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText(/Up \d+ points|Down \d+ points|No change since/)
    ).not.toBeInTheDocument();
  });

  // The plan is sold, so an unentitled customer gets the approved lockgate
  // rather than the content.
  //
  // SIGV2-1305: this used to lean on `baseProject`'s empty `feature_access`,
  // which is the ambiguity the ticket is about. An absent entitlement and a
  // refused one are different facts, so the refusal is now explicit, as a
  // real locked payload is.
  it("locks the prioritised fixes when the advisor plan is not allowed", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: ADVISOR_PLAN_LOCKED },
      latestAudit: baseLatestAudit,
    });

    const { container } = render(<ProjectOverviewPage />);

    expect(container.querySelector('[class*="blur-[6px]"]')).not.toBeNull();
    expect(screen.getByText("Unlock your action plan")).toBeInTheDocument();
  });

  // SIGV2-1305: QA found a Standard customer asked to upgrade for the action
  // plan their plan grants. Checked against that account: plan_standard,
  // active, `has_advisor_recommendations` true. So the entitlement was right
  // and what they saw was the unknown state wearing the locked state's
  // clothes, which `resolveAdvisorPlanAccess` admitted in its own comment.
  //
  // Telling somebody who is already paying to pay again is the worst thing a
  // billing-adjacent surface can do, so silence no longer produces a demand
  // for money. The blur stays: protecting content on an unknown entitlement
  // is the fail-safe direction, and it is only the upsell that was unsafe.
  it("does not ask for money when the payload never stated the entitlement", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: {} },
      latestAudit: baseLatestAudit,
    });

    const { container } = render(<ProjectOverviewPage />);

    expect(screen.queryByText("Unlock your action plan")).not.toBeInTheDocument();
    expect(screen.queryByText(/upgrade/i)).not.toBeInTheDocument();
    // Still withheld, just not sold.
    expect(container.querySelector('[class*="blur-[6px]"]')).not.toBeNull();
  });

  // SIGV2-1134: the lock named Specialist while the plan page it previews was
  // included from Standard up, so a Standard customer was told to upgrade to
  // see a preview of something they already owned. The plan named here and the
  // billing link both come from the served payload now.
  it("names the plan the backend requires, and links to it", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: ADVISOR_PLAN_LOCKED },
      latestAudit: baseLatestAudit,
    });

    render(<ProjectOverviewPage />);

    expect(screen.getByText("Standard")).toBeInTheDocument();
    expect(screen.queryByText("Specialist")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upgrade to Standard" })).toHaveAttribute(
      "href",
      "/dashboard/billing?section=plans&plan=plan_standard"
    );
  });

  // A payload that names no plan must not have one invented for it.
  it("falls back to a plan-free upgrade prompt when the payload names none", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: {
        ...baseProject,
        feature_access: {
          advisor_recommendations: {
            allowed: false,
            detail: null,
            status_code: 402,
            required_plan: null,
          },
        },
      },
      latestAudit: baseLatestAudit,
    });

    render(<ProjectOverviewPage />);

    expect(screen.getByRole("link", { name: "Upgrade your plan" })).toHaveAttribute(
      "href",
      "/dashboard/billing?section=plans"
    );
  });

  // Blur is presentation, not authorization: gated fix titles and
  // descriptions must not sit in the DOM at all. The locked layer renders the
  // approved .fix row anatomy (numbered rows, headings, impact chips) with
  // generic illustrative copy, so it looks like a real plan without carrying
  // one.
  it("shows an illustrative action plan behind the lock, never the real one", () => {
    const { container } = render(<ProjectOverviewPage />);

    const blurred = container.querySelector('[class*="blur-[6px]"]') as HTMLElement;
    expect(blurred).not.toBeNull();
    // None of the customer's actual recommendations anywhere in the DOM.
    const dom = document.body.textContent || "";
    expect(dom).not.toContain("Fix the missing page title");
    expect(dom).not.toContain("Give this page a clear title.");
    // Structured illustrative rows are present: three numbered .fix rows with
    // headings and chips, not blank placeholder bars.
    expect(blurred.querySelectorAll("h3").length).toBe(3);
    expect(blurred.textContent).toContain("Improve crawl coverage");
    expect(blurred.textContent).toContain("High impact");
    expect(blurred).toHaveAttribute("aria-hidden", "true");
    // The approved gate layer is a plain centred overlay; no extra veil or
    // backdrop blur beyond the spec's 6px content blur.
    expect(container.querySelector('[class*="backdrop-blur"]')).toBeNull();
  });

  it("leaves the prioritised fixes open when the advisor plan is allowed", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: {
        ...baseProject,
        feature_access: ADVISOR_PLAN_ALLOWED,
      },
      latestAudit: baseLatestAudit,
    });

    const { container } = render(<ProjectOverviewPage />);

    expect(container.querySelector('[class*="mt-3.5"]')).not.toBeNull();
    expect(container.querySelector('[class*="blur-[6px]"]')).toBeNull();
    expect(screen.queryByText("Unlock your action plan")).not.toBeInTheDocument();
  });

  // SIGNAL-1000: this dashboard tile averaged raw sub-fields (seo.onpage/
  // performance/indexing, aeo.answerability_score, geo.visibility_index)
  // instead of using the same canonical scores.seo/aeo/geo the SEO and AIO
  // detail tabs already show for the exact same audit, so the two headline
  // numbers disagreed with themselves one click apart.
  it("uses the canonical scores.seo/aeo/geo, matching the real SEO and AIO tabs, instead of averaging raw sub-fields", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: {
        ...baseLatestAudit,
        full_report: {
          ...baseLatestAudit.full_report,
          // Raw sub-fields a naive average would produce 46 (seo) / 4 (aio) from,
          // exactly the SIGNAL-1000 repro numbers.
          seo: { onpage: 18.8, performance: 100.0, indexing: 18.8 },
          aeo: { answerability_score: 0.0 },
          geo: { visibility_index: 6.9 },
          scores: { seo: 25.2, aeo: 25.6, geo: 10.8, overall: 21.0 },
        },
      },
    });

    render(<ProjectOverviewPage />);

    // seoScore = round(scores.seo) = round(25.2) = 25.
    //
    // SIGV2-1308: aioScore = round(mean(25.6, 10.8)) = round(18.2) = 18.
    //
    // This asserted 19, which was round(mean(round(25.6), round(10.8))), so
    // round(mean(26, 11)) = round(18.5). Rounding the parts before averaging
    // them moved the answer by a whole point on these inputs, and by one point
    // on the real project QA looked at, which read 49 on the workspace
    // overview and 50 on its own dashboard at the same moment. The overview
    // averages raw and rounds for display; this rounded twice.
    //
    // 18 is the right number. Rounding is a display step and happens once.
    expect(screen.getAllByText("25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("18").length).toBeGreaterThan(0);
    expect(screen.queryAllByText("19")).toHaveLength(0);
    expect(screen.queryByText("46")).not.toBeInTheDocument();
    expect(screen.queryByText("4")).not.toBeInTheDocument();
  });

  it("announces load failures and retries through refetch", () => {
    const refetch = vi.fn();
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: "Network failed",
      project: null,
      latestAudit: null,
      refetch,
    });

    render(<ProjectOverviewPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("Network failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

// SIGV2-1035: GA4 Traffic & Conversions. The hook is mocked so these tests
// assert the section renders each contract state as itself; hook behaviour
// (stale-response discard) is covered in src/hooks/useSiteTraffic.test.tsx.
const trafficPayload = (overrides: Record<string, unknown> = {}) => ({
  status: "ok" as const,
  window: "7D",
  start_date: "2026-09-23",
  end_date: "2026-09-29",
  comparison_start_date: "2026-09-16",
  comparison_end_date: "2026-09-22",
  property_timezone: "America/New_York",
  bucket_granularity: "daily",
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
      sessions: 0,
      share: 0,
      share_change: { value: null, kind: "percentage_points" },
    },
  ],
  breakdowns: {
    sessions: [],
    users: [],
    engagement: [],
    conversions: [],
  },
  key_events: {
    state: "active",
    total: 214,
    change: { value: 0.0061, kind: "relative" },
    by_event: [],
    by_channel: [],
  },
  ...overrides,
});

const setTraffic = (traffic: unknown, ga4WorkspaceConnected: boolean | null = null) =>
  mocks.useSiteTraffic.mockReturnValue({
    traffic,
    ga4WorkspaceConnected,
    loading: false,
    error: null,
    window: "7D",
    setWindow: vi.fn(),
    refetch: vi.fn(),
  });

describe("Site traffic section (GA4, SIGV2-1035)", () => {
  beforeEach(() => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: baseLatestAudit,
    });
  });

  it("renders the approved five-card KPI row in the mock's order", () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);

    const section = screen.getByRole("region", { name: "Traffic and conversions" });
    const cards = [...section.querySelectorAll("[data-metric]")];
    expect(cards.map((c) => c.getAttribute("data-metric"))).toEqual([
      "sessions",
      "users",
      "engagement",
      "conversions",
      "audience",
    ]);
    // Available contract fields the design does not show are not rendered.
    expect(section.querySelector('[data-metric="pageviews"]')).toBeNull();
    expect(section.querySelector('[data-metric="bounce"]')).toBeNull();
    expect(section.querySelector('[data-metric="duration"]')).toBeNull();

    // Values come from the payload, compacted.
    expect(cards[0].textContent).toContain("4.8K");
    expect(cards[1].textContent).toContain("3.1K");
    expect(cards[2].textContent).toContain("58%");
    expect(cards[3].textContent).toContain("214");

    // Only sessions, users and key events carry contract change values:
    // three delta pills, Engagement renders the same card without one.
    for (const i of [0, 1, 3]) {
      expect(cards[i].textContent).toMatch(/↗|↘/);
    }
    expect(cards[2].textContent).not.toMatch(/↗|↘/);
  });

  it("labels relative deltas as % and share changes as percentage points", () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "Traffic and conversions" });
    expect(section.textContent).toMatch(/\+0\.45%/);
    expect(section.textContent).toMatch(/\+2\.0 pp|\+2\.0/);
  });

  it("never renders a number on the Audience card", () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);
    const card = document.querySelector('[data-metric="audience"]');
    expect(card?.textContent).toContain("Audience");
    expect(card?.textContent).toContain("Not measured");
    expect(card?.textContent).not.toMatch(/\d/);
  });

  it("routes disconnected to the property binding when the workspace account exists", () => {
    setTraffic({ status: "disconnected", availability: "disconnected" }, true);
    render(<ProjectOverviewPage />);
    expect(screen.getByText(/Google Analytics is not connected/)).toBeInTheDocument();
    // The account is already linked at workspace level; the missing piece is
    // the per-project GA4 property binding, made in project settings'
    // Connected data section.
    expect(screen.getByRole("link", { name: "Choose a GA4 property" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/settings#data-sources"
    );
  });

  it("routes disconnected to workspace connections when the account is missing", () => {
    setTraffic({ status: "disconnected", availability: "disconnected" }, false);
    render(<ProjectOverviewPage />);
    expect(screen.getByText(/Google Analytics is not connected/)).toBeInTheDocument();
    // No workspace Google connection exists, so the next step is connecting
    // the account - the property picker cannot help before that.
    expect(screen.getByRole("link", { name: "Connect Google Analytics" })).toHaveAttribute(
      "href",
      "/dashboard/connections"
    );
  });

  it("renders revoked and provider_error as distinct states", () => {
    setTraffic({ status: "revoked", availability: "unavailable" });
    const { unmount } = render(<ProjectOverviewPage />);
    expect(screen.getByText(/access was revoked/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Reconnect Google Analytics" })).toBeInTheDocument();
    unmount();

    setTraffic({ status: "provider_error", availability: "unavailable" });
    render(<ProjectOverviewPage />);
    expect(screen.getByText(/Analytics data could not be loaded/)).toBeInTheDocument();
  });

  it("renders no_data as its own empty state, not as zeros", () => {
    setTraffic(trafficPayload({ availability: "no_data" }));
    render(<ProjectOverviewPage />);
    expect(screen.getByText("No traffic data for this period")).toBeInTheDocument();
    expect(document.querySelector('[data-metric="sessions"]')).toBeNull();
  });

  it("surfaces partial data with the quality flags named", () => {
    setTraffic(
      trafficPayload({
        availability: "partial",
        data_quality: { subject_to_thresholding: true, truncated: true },
      })
    );
    render(<ProjectOverviewPage />);
    const notice = screen.getByText(/This data is partial/);
    expect(notice.textContent).toContain("thresholding");
    expect(notice.textContent).toContain("truncated");
  });

  it("distinguishes observed_zero conversions from not_configured", () => {
    setTraffic(
      trafficPayload({
        key_events: {
          state: "observed_zero",
          total: 0,
          change: { value: null, kind: "relative" },
          by_event: [],
          by_channel: [],
        },
      })
    );
    const { unmount } = render(<ProjectOverviewPage />);
    const card = document.querySelector('[data-metric="conversions"]');
    // A measured zero renders as a number, not a setup message.
    expect(card?.textContent).toContain("0");
    expect(card?.textContent).not.toContain("No key events are configured");
    unmount();

    setTraffic(
      trafficPayload({
        key_events: {
          state: "not_configured",
          total: 0,
          change: { value: null, kind: "relative" },
          by_event: [],
          by_channel: [],
        },
      })
    );
    render(<ProjectOverviewPage />);
    // SIGV2-1204: the sentence is now on the card and in the card's help
    // panel, so assert it on the card rather than expecting one match in the
    // whole document.
    expect(document.querySelector('[data-metric="conversions"]')?.textContent).toContain(
      "No key events are configured in GA4."
    );
  });

  it("renders every channel bucket the payload carries, including Other", () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "Traffic and conversions" });
    for (const label of [
      "Organic",
      "Direct",
      "Referral",
      "AI assistants",
      "Paid",
      "Social media",
      "Other",
    ]) {
      // The xsell overlay repeats channel labels, so assert the legend copy exists.
      expect(within(section).getAllByText(label).length).toBeGreaterThan(0);
    }
    // Shares shown verbatim, not normalised.
    expect(within(section).getByText("34%")).toBeInTheDocument();
  });

  it("drives the window through the period control and shows the reported grain", () => {
    const setWindow = vi.fn();
    mocks.useSiteTraffic.mockReturnValue({
      traffic: trafficPayload({ bucket_granularity: "daily" }),
      loading: false,
      error: null,
      window: "7D",
      setWindow,
      refetch: vi.fn(),
    });
    render(<ProjectOverviewPage />);
    fireEvent.click(screen.getByRole("button", { name: "90D" }));
    expect(setWindow).toHaveBeenCalledWith("90D");
    expect(screen.getByText("Daily")).toBeInTheDocument();
  });

  it("states the payload's dates, timezone and freshness on the GA4 badge", async () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);

    // SIGV2-1125: Contract 3/7 still requires these four facts to be stated
    // from the payload, but no longer as a paragraph under the charts: that
    // was 26px of vertical flow the approved design has no element for. They
    // hang off the block's own GA4 provenance badge instead.
    const badge = screen.getByRole("button", {
      name: "Data details",
    });
    await act(async () => {
      badge.focus();
    });

    const line = await screen.findByText(/2026-09-23 to 2026-09-29/);
    expect(line.textContent).toContain("2026-09-16 to 2026-09-22");
    expect(line.textContent).toContain("America/New_York");
    expect(line.textContent).toContain("2026-09-29T12:00:00+00:00");
  });

  it("keeps the range out of vertical flow under the charts", () => {
    setTraffic(trafficPayload());
    const { container } = render(<ProjectOverviewPage />);

    // The paragraph is gone, and the facts are not rendered until the badge
    // is focused or hovered, so the block costs the approved height.
    expect(container.textContent).not.toContain("2026-09-23 to 2026-09-29");
    expect(container.querySelector("[data-traffic-provenance]")).toBeInTheDocument();
  });
});

describe("Overview header, visibility and reputation (SIGV2-1035 part 2)", () => {
  beforeEach(() => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: baseLatestAudit,
    });
  });

  it("drives the traffic window from the approved header pills and labels the period", () => {
    const setWindow = vi.fn();
    mocks.useSiteTraffic.mockReturnValue({
      traffic: null,
      loading: true,
      error: null,
      window: "7D",
      setWindow,
      refetch: vi.fn(),
    });
    render(<ProjectOverviewPage />);

    expect(screen.getByText(/Last 7 days/)).toBeInTheDocument();
    // Without a traffic payload there is no invented trend claim.
    expect(screen.queryByText(/tracking (up|down)/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "90D" }));
    expect(setWindow).toHaveBeenCalledWith("90D");
  });

  it("shows tracking up/down only from the payload's sessions change", () => {
    mocks.useSiteTraffic.mockReturnValue({
      traffic: trafficPayload(),
      loading: false,
      error: null,
      window: "15D",
      setWindow: vi.fn(),
      refetch: vi.fn(),
    });
    render(<ProjectOverviewPage />);
    expect(screen.getByText(/Last 15 days/)).toBeInTheDocument();
    expect(screen.getByText(/tracking up/)).toBeInTheDocument();

    mocks.useSiteTraffic.mockReturnValue({
      traffic: trafficPayload({
        overview: {
          ...trafficPayload().overview,
          changes: {
            ...trafficPayload().overview.changes,
            sessions: { value: -0.02, kind: "relative" },
          },
        },
      }),
      loading: false,
      error: null,
      window: "7D",
      setWindow: vi.fn(),
      refetch: vi.fn(),
    });
    render(<ProjectOverviewPage />);
    expect(screen.getByText(/tracking down/)).toBeInTheDocument();
  });

  it("renders the five-card KPI row only for sessions/users/engagement/conversions/audience", () => {
    setTraffic(trafficPayload());
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "Traffic and conversions" });
    expect(
      [...section.querySelectorAll("[data-metric]")].map((c) => c.getAttribute("data-metric"))
    ).toEqual(["sessions", "users", "engagement", "conversions", "audience"]);
  });

  it("renders search-type feeds from report metadata, measured figures only", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: {
        ...baseLatestAudit,
        full_report: {
          ...baseLatestAudit.full_report,
          // Versioned so normalization accepts the canonical-shaped fixture.
          schema_version: "2.0",
          metadata: {
            search_types: [
              {
                id: "brand",
                label: "Brand Understanding",
                score: 78,
                answer_ratio: { present: 7, measured: 10 },
                trend: 3,
                insight: "AI describes your brand correctly.",
                source: "measured",
              },
              {
                // Still tagged with the retired heuristic source, as reports
                // served before SIGV2-1105 are. Its score is not rendered.
                id: "category",
                label: "Category Visibility",
                score: 44,
                trend: 3,
                insight: "You appear in some category answers.",
                source: "derived",
              },
              {
                id: "problem",
                label: "Customer Problem",
                score: 30,
                trend: -2,
                insight: "Rivals appear above you.",
                source: "measured",
              },
              {
                id: "comparison",
                label: "Competitor Comparisons",
                score: null,
                trend: 1,
                insight: "Recommended in few comparisons.",
                source: "unmeasured",
              },
              {
                id: "feature",
                label: "Feature Recognition",
                score: 60,
                trend: 3,
                insight: "Six in ten features are attributed.",
                source: "measured",
              },
            ],
          },
        },
      },
    });
    render(<ProjectOverviewPage />);

    const section = screen.getByRole("region", {
      name: "Why AI recommends your website",
    });
    expect(within(section).getByText("Brand Understanding")).toBeInTheDocument();
    expect(within(section).getByText("78")).toBeInTheDocument();
    // The approved `.ft-ratio` line, measured for the one type that has it.
    expect(within(section).getByText("7 of 10 answers")).toBeInTheDocument();
    expect(within(section).getAllByText("Answer ratio not measured")).toHaveLength(4);
    // Three measured types. The derived and unmeasured ones show no figure at
    // all, and no "Estimated" label remains on this surface (SIGV2-1105).
    expect(within(section).getAllByText("Measured")).toHaveLength(3);
    expect(within(section).queryByText("Estimated")).not.toBeInTheDocument();
    expect(within(section).getAllByText("Not measured")).toHaveLength(2);
    expect(within(section).queryByText("44")).not.toBeInTheDocument();
    expect(within(section).queryAllByRole("link")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "AIO improvement suggestions" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/ai-answers"
    );
  });

  it("renders real ring scores with an explicit no-target and unmeasured stats", () => {
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "Your website visibility" });

    // Real scores in the rings.
    expect(within(section).getByText("81")).toBeInTheDocument();
    expect(within(section).getByText("72")).toBeInTheDocument();

    // This project has no score target (SIGV2-1006): the approved chip
    // renders the no-target state, never a number, and the gap row that
    // subtracts from it is unmeasured for the same reason (SIGV2-1125).
    expect(within(section).getAllByText("No target set")).toHaveLength(2);
    expect(within(section).getAllByText("Gap to target")).toHaveLength(2);

    // The AIO stat reads the visibility summary, which this case cannot load,
    // so it is unmeasured rather than printing 0. The SEO panel's "Search
    // engine visibility" line was removed (SIGV2-1111), so the gap and the
    // AIO appearance stat are the only rows beside the rings.
    expect(within(section).getByText("Appearance in AI answers")).toBeInTheDocument();
    expect(within(section).queryByText("Search engine visibility")).not.toBeInTheDocument();
    expect(within(section).getAllByText("Not measured")).toHaveLength(3);
    expect(within(section).queryByText("Score target")).not.toBeInTheDocument();
    // SIGV2-1125: the sentence explaining the unmeasured state lives in the
    // (i) tooltip now, not as a third line of row body text that made the two
    // cards different heights.
    expect(
      within(section).queryByText("No completed AI visibility monitoring run yet.")
    ).not.toBeInTheDocument();
    expect(within(section).queryByText(/4\/10|1st page/)).not.toBeInTheDocument();

    // SIGV2-1111: the (i) beside that stat sends people to the Prompts tab
    // that produces the figure, not to the AIO tab they land on by default.
    expect(
      within(section).getByRole("link", {
        name: "Add or manage prompts",
      })
    ).toHaveAttribute("href", "/dashboard/projects/42/ai-answers?tab=prompts");
  });

  it("renders the AI visibility & reputation structure with honest unmeasured states", () => {
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "AI visibility & reputation" });

    // The overall ring carries the real AIO score.
    expect(within(section).getByText("72")).toBeInTheDocument();

    // The find title appears in the summary column and the group header; the
    // four approved rows are the whole VISIBILITY card.
    for (const title of [
      "Does AI find you?",
      "Answer Presence",
      "Source Citations",
      "Engine Coverage",
      "Brand Mentions",
    ]) {
      expect(within(section).getAllByText(title).length).toBeGreaterThan(0);
    }

    // The trust panel and its two unsourced rows were removed (SIGV2-1111):
    // the product has no figure for any of them.
    for (const gone of ["Does AI TRUST you?", "Recommendation Win Rate", "Domain Authority"]) {
      expect(within(section).queryByText(gone)).toBeNull();
    }

    // Each unmeasured slot names why, and none of the mock's placeholder
    // figures or peer comparisons leak through. With the monitoring summary
    // unavailable all four rows report the no-run reason.
    expect(
      within(section).getAllByText(/plan-gated|no completed AI visibility monitoring run/i).length
    ).toBeGreaterThanOrEqual(4);
    for (const pattern of [
      /15\/30/,
      /11\/24/,
      /7\/7/,
      /Below average/,
      /Above average/,
      /Low Volume/,
      /vs \d+% avg/,
    ]) {
      expect(within(section).queryByText(pattern)).toBeNull();
    }
  });

  it("surfaces the top fix as the biggest opportunity, not a fabricated claim", () => {
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: { ...baseProject, feature_access: ADVISOR_PLAN_ALLOWED },
      latestAudit: baseLatestAudit,
    });
    mocks.recommendations.mockReturnValue([
      {
        title: "Fix the missing page title",
        description: "Give this page a clear title.",
        impact: "Critical",
        category: "SEO",
      },
    ]);
    render(<ProjectOverviewPage />);
    const section = screen.getByRole("region", { name: "AI visibility & reputation" });
    expect(within(section).getByText("Biggest opportunity")).toBeInTheDocument();
    expect(within(section).getByText("Fix the missing page title")).toBeInTheDocument();
  });
});

/* SIGV2-1181: Jake asked for the progressive change back under the two
   gauges, matching what the workspace overview already reports for the same
   project. It therefore reads the project's own score history (90 days,
   weekly buckets) from the trends payload the workspace overview card is
   built from, and says nothing at all when there is no progression. */
describe("Gauge trend and sparkline (SIGV2-1181)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.recommendations.mockReturnValue([]);
    mocks.history.mockResolvedValue([]);
    mocks.useProjectLatestAudit.mockReturnValue({
      loading: false,
      error: null,
      project: baseProject,
      latestAudit: baseLatestAudit,
    });
    mocks.useSiteTraffic.mockReturnValue({
      traffic: null,
      loading: true,
      error: null,
      window: "7D",
      setWindow: vi.fn(),
      refetch: vi.fn(),
    });
    // No score history unless the case supplies one.
    mocks.trends.mockRejectedValue(new Error("no trend history"));
  });

  const bucket = (date: string, seo: number, aeo: number, geo: number) => ({
    date,
    seo,
    geo,
    aeo,
    overall: (seo + geo + aeo) / 3,
    audit_count: 1,
    latest_audit_at: `${date}T10:00:00.000Z`,
  });

  const trendPayload = (
    points: ReturnType<typeof bucket>[],
    delta: { seo: number | null; geo: number | null; aeo: number | null; overall: number | null }
  ) => ({
    project_id: 42,
    period: "90d",
    granularity: "weekly",
    data_points: points,
    summary: {
      first: points[0] ?? null,
      latest: points[points.length - 1] ?? null,
      delta,
      trend_direction: { seo: "up", geo: "up", aeo: "up", overall: "up" },
    },
  });

  const trendBlock = (variant: "aio" | "seo") =>
    document.querySelector(`[data-score-trend="${variant}"]`);

  it("asks for the same history the workspace overview reads for this project", async () => {
    mocks.trends.mockResolvedValue(
      trendPayload([bucket("2026-07-06", 66, 45, 49), bucket("2026-07-13", 74, 58, 62)], {
        seo: 8,
        aeo: 13,
        geo: 13,
        overall: 11,
      })
    );

    await act(async () => {
      render(<ProjectOverviewPage />);
    });

    expect(mocks.trends).toHaveBeenCalledWith(
      "42",
      { Authorization: "Bearer token" },
      { period: "90d", granularity: "weekly" }
    );
  });

  it("draws the real series and delta under both gauges once two audits are scored", async () => {
    mocks.trends.mockResolvedValue(
      trendPayload([bucket("2026-07-06", 66, 45, 49), bucket("2026-07-13", 74, 58, 62)], {
        seo: 8,
        aeo: 13,
        geo: 13,
        overall: 11,
      })
    );

    await act(async () => {
      render(<ProjectOverviewPage />);
    });

    // AIO is the 50/50 AEO+GEO roll-up of each bucket: 47 then 60.
    expect(trendBlock("aio")!.textContent).toBe("↗ +13");
    expect(document.querySelector('[data-score-trend="aio"]')!.parentElement!).toContainHTML(
      'data-spark="47,60"'
    );
    expect(trendBlock("seo")!.textContent).toBe("↗ +8");
    expect(document.querySelector('[data-score-trend="seo"]')!.parentElement!).toContainHTML(
      'data-spark="66,74"'
    );
  });

  it("draws neither a delta nor a sparkline for a single scored audit", async () => {
    mocks.trends.mockResolvedValue(
      trendPayload([bucket("2026-07-13", 74, 58, 62)], {
        seo: 0,
        aeo: 0,
        geo: 0,
        overall: 0,
      })
    );

    await act(async () => {
      render(<ProjectOverviewPage />);
    });

    expect(trendBlock("aio")).toBeNull();
    expect(trendBlock("seo")).toBeNull();
    expect(document.querySelectorAll("svg[data-spark]")).toHaveLength(0);
    expect(document.body.textContent).not.toContain("→ 0");
  });

  it("draws nothing when the history cannot be read at all", async () => {
    await act(async () => {
      render(<ProjectOverviewPage />);
    });

    expect(trendBlock("aio")).toBeNull();
    expect(trendBlock("seo")).toBeNull();
  });

  it("reports a fall as a fall under the gauge", async () => {
    mocks.trends.mockResolvedValue(
      trendPayload([bucket("2026-07-06", 78, 62, 66), bucket("2026-07-13", 74, 56, 58)], {
        seo: -4,
        aeo: -6,
        geo: -8,
        overall: -6,
      })
    );

    await act(async () => {
      render(<ProjectOverviewPage />);
    });

    expect(trendBlock("seo")!.textContent).toBe("↘ -4");
    expect(trendBlock("seo")!.querySelector("span")!.className).toContain("text-(--bad)");
    expect(trendBlock("aio")!.textContent).toBe("↘ -7");
    expect(trendBlock("aio")!.querySelector("span")!.className).toContain("text-(--bad)");
  });
});
