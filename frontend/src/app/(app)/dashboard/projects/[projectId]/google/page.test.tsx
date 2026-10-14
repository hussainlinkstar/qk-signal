import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectSeoPage from "@/app/(app)/dashboard/projects/[projectId]/google/page";
import { exportVariantsResponse } from "@/services/__fixtures__/exportVariants";
import { tEn } from "@/test/i18nEn";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/types/auditResult", () => ({
  isAuditResult: () => true,
}));

vi.mock("@/lib/auditWorkspaceUtils", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/auditWorkspaceUtils")>()),
  normalizeReportWithDiagnostics: (report: unknown) => ({
    report,
    diagnostics: { summary: null, serviceIssues: [], modules: { seo: null } },
  }),
}));

vi.mock("@/lib/projectAuditFeature", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/projectAuditFeature")>()),
  buildAuditRecordResponse: (audit: unknown) => audit,
}));

const monitoringMock = vi.hoisted(() => ({
  fetchSerpTrackingSummary: vi.fn(),
  listTargetKeywords: vi.fn(),
  createTargetKeyword: vi.fn(),
  fetchSearchConsolePages: vi.fn(),
}));

const reportMock = vi.hoisted(() => ({
  generateComplexReportPdf: vi.fn(),
  fetchComplexReportStatus: vi.fn(),
  downloadComplexReportPdfBlob: vi.fn(),
  fetchReportExportVariants: vi.fn(),
}));

const authMock = vi.hoisted(() => ({
  getToken: vi.fn(async () => "token"),
  user: { subscription_plan: "plan_specialist" } as Record<string, unknown> | null,
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: authMock.getToken, isSignedIn: true, user: authMock.user }),
}));

vi.mock("@/services/monitoringService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/monitoringService")>();
  return {
    ...actual,
    fetchSerpTrackingSummary: (...args: unknown[]) =>
      monitoringMock.fetchSerpTrackingSummary(...args),
    listTargetKeywords: (...args: unknown[]) => monitoringMock.listTargetKeywords(...args),
    createTargetKeyword: (...args: unknown[]) => monitoringMock.createTargetKeyword(...args),
    fetchSearchConsolePages: (...args: unknown[]) =>
      monitoringMock.fetchSearchConsolePages(...args),
  };
});

vi.mock("@/services/reportService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/reportService")>();
  return {
    ...actual,
    generateComplexReportPdf: (...args: unknown[]) => reportMock.generateComplexReportPdf(...args),
    fetchComplexReportStatus: (...args: unknown[]) => reportMock.fetchComplexReportStatus(...args),
    downloadComplexReportPdfBlob: (...args: unknown[]) =>
      reportMock.downloadComplexReportPdfBlob(...args),
    fetchReportExportVariants: (...args: unknown[]) =>
      reportMock.fetchReportExportVariants(...args),
  };
});

const STALE_SELECTION = {
  module: "seo",
  status: "stale",
  message: "This Google view is using check data that is 38 days old. Run a fresh check.",
  recommended_audit_type: "STANDARD",
  recommended_launch_tier: "fast",
  compatible_audit_types: ["FAST", "SMART", "STANDARD", "DEEP"],
  stale_after_days: 30,
  selected_audit_age_days: 38,
  selected_audit: null,
  latest_audit: null,
};

const auditMock = vi.hoisted(() => ({
  current: {
    project: {
      latest_seo_score: 81,
      latest_geo_score: 71,
      latest_aeo_score: 78,
      feature_access: {
        advisor_recommendations: {
          allowed: true,
          detail: null,
          status_code: null,
          required_plan: null,
        },
      },
    },
    loading: false,
    error: null,
    auditSelection: null as unknown,
    latestAudit: {
      id: 700,
      status: "completed" as string,
      url: "https://client.example",
      full_report: {
        schema_version: "2026-03-09",
        site: { url: "https://client.example", market: "us", language: "en" },
        scores: { seo: 81 },
        seo: {
          onpage: 79,
          performance: 72,
          indexing: 88,
          core_web_vitals: 70,
          technical_seo: 55,
          onpage_content: 40,
          eeat_trust: 30,
          security_accessibility: 90,
        },
        suggestions: [
          { category: "technical", title: "Fix meta tags", action: "Add missing metadata." },
        ],
      },
    },
  } as Record<string, unknown>,
}));
const defaultAudit = auditMock.current;

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => auditMock.current,
}));

const SERP_SUMMARY = {
  project_id: 42,
  total_keywords: 4,
  snippets_owned: 1,
  snippets_gained: 1,
  snippets_lost: 0,
  paa_appearances_total: 2,
  ai_overview_count: 1,
  ai_overview_cited_count: 0,
  latest_snapshots: [
    {
      keyword: "boutique hotel waterfront",
      keyword_id: 11,
      snapshot_date: "2026-09-28",
      owns_featured_snippet: true,
      featured_snippet_url: "https://client.example/rooms",
      paa_appearances: [],
      organic_position: 4,
      serp_features_present: ["featured_snippet"],
      ai_overview_detected: true,
      ai_overview_cites_target: true,
      ai_overview_source_urls: null,
    },
    {
      keyword: "quiet hotel late checkout",
      keyword_id: 12,
      snapshot_date: "2026-09-28",
      owns_featured_snippet: false,
      featured_snippet_url: null,
      paa_appearances: [],
      organic_position: 12,
      serp_features_present: [],
      ai_overview_detected: false,
      ai_overview_cites_target: false,
      ai_overview_source_urls: null,
    },
    {
      keyword: "pet friendly seaside hotel",
      keyword_id: 13,
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
};

const KEYWORDS = [
  {
    id: 11,
    keyword: "boutique hotel waterfront",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-09-01T00:00:00.000Z",
  },
  {
    id: 12,
    keyword: "quiet hotel late checkout",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-09-01T00:00:00.000Z",
  },
  {
    id: 13,
    keyword: "pet friendly seaside hotel",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-09-01T00:00:00.000Z",
  },
  {
    id: 14,
    keyword: "weekend break by the sea",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-09-05T00:00:00.000Z",
  },
];

const opportunity = (value: string, evidence: Record<string, unknown>) => ({
  value,
  evidence: {
    weighted_position: null,
    impressions: 0,
    ctr: null,
    band_median_ctr: null,
    min_impressions: 200,
    incomplete: false,
    ...evidence,
  },
});

const GSC_PAGES = {
  property: "https://client.example/",
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
  totals: { clicks: 410, impressions: 9200, ctr: 0.0446, position: 7.4 },
  pages: [
    {
      page_key: "/rooms/deluxe-king",
      pages: ["https://client.example/rooms/deluxe-king"],
      collapsed_count: 0,
      clicks: 210,
      impressions: 4200,
      ctr: 0.05,
      avg_position: 3.2,
      sessions: 6240,
      sessions_reason: null,
      incomplete: false,
      opportunity: opportunity("low_ctr", {
        weighted_position: 3.2,
        impressions: 4200,
        ctr: 0.05,
        band_median_ctr: 0.07,
      }),
    },
    {
      page_key: "/waterfront",
      pages: ["https://client.example/waterfront"],
      collapsed_count: 0,
      clicks: 160,
      impressions: 3800,
      ctr: 0.042,
      avg_position: 9.1,
      sessions: 4110,
      sessions_reason: null,
      incomplete: false,
      opportunity: opportunity("striking_distance", {
        weighted_position: 9.1,
        impressions: 3800,
        ctr: 0.042,
      }),
    },
    {
      page_key: "/amenities",
      pages: ["https://client.example/amenities"],
      collapsed_count: 0,
      clicks: 40,
      impressions: 1200,
      ctr: 0.033,
      avg_position: 6.4,
      sessions: null,
      sessions_reason: "no_ga4_match",
      incomplete: true,
      opportunity: opportunity("insufficient_data", {
        weighted_position: 6.4,
        impressions: 1200,
        ctr: 0.033,
        incomplete: true,
      }),
    },
  ],
  series: [],
  fetched_at: "2026-09-29T12:00:00.000Z",
};

beforeEach(() => {
  monitoringMock.fetchSerpTrackingSummary.mockReset();
  monitoringMock.fetchSerpTrackingSummary.mockResolvedValue(SERP_SUMMARY);
  monitoringMock.listTargetKeywords.mockReset();
  monitoringMock.listTargetKeywords.mockResolvedValue(KEYWORDS);
  monitoringMock.createTargetKeyword.mockReset();
  monitoringMock.createTargetKeyword.mockResolvedValue({
    id: 15,
    keyword: "hotel with a cooling mattress",
    search_engine: "google",
    language_code: "en",
    location_code: null,
    is_active: true,
    created_at: "2026-10-06T00:00:00.000Z",
  });
  monitoringMock.fetchSearchConsolePages.mockReset();
  monitoringMock.fetchSearchConsolePages.mockResolvedValue(GSC_PAGES);
  reportMock.generateComplexReportPdf.mockReset();
  reportMock.fetchComplexReportStatus.mockReset();
  reportMock.downloadComplexReportPdfBlob.mockReset();
  reportMock.fetchReportExportVariants.mockReset();
  reportMock.fetchReportExportVariants.mockResolvedValue(exportVariantsResponse());
  authMock.user = { subscription_plan: "plan_specialist" };
  auditMock.current = defaultAudit;
});

describe("ProjectSeoPage (approved SEO detail)", () => {
  it("lays the SEO detail out as the approved four tabs", () => {
    render(
      <PageHeaderHarness>
        <ProjectSeoPage />
      </PageHeaderHarness>
    );

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Improve"),
      expect.stringContaining("Ranking factors"),
      expect.stringContaining("Keywords"),
      expect.stringContaining("Pages"),
    ]);
    expect(screen.getByRole("tab", { name: /Improve/ })).toHaveAttribute("aria-selected", "true");
  });

  it("shows an illustrative action plan behind the lock, never the real one", async () => {
    auditMock.current = {
      ...defaultAudit,
      project: {
        ...defaultAudit.project,
        feature_access: {
          advisor_recommendations: {
            allowed: false,
            detail: null,
            status_code: null,
            required_plan: "Standard",
          },
        },
      },
      // This suite mocks buildAuditRecordResponse/normalizeReportWithDiagnostics
      // as pass-throughs, so the canonical report is the audit object itself.
      latestAudit: {
        ...(defaultAudit.latestAudit as Record<string, unknown>),
        detailed_seo_recommendations: [
          { title: "Fix meta tags", description: "Add missing metadata." },
        ],
      },
    };
    let container!: HTMLElement;
    await act(async () => {
      container = render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      ).container;
    });

    const blurred = container.querySelector('[class*="blur-[6px]"]') as HTMLElement;
    expect(blurred).not.toBeNull();
    // Blur is presentation, not authorization: the real recommendation must
    // not sit anywhere in the DOM; the .lockcontent shows illustrative .act
    // rows (heading, description, chips) instead.
    expect(document.body.textContent).not.toContain("Fix meta tags");
    // SIGV2-1211: the illustrative rows rate impact as a category. A figure
    // shown to a plan that cannot see the real list traces to nothing.
    expect(blurred.textContent).not.toContain("PTS");
    expect(blurred.textContent).toContain("Impact: High");
    expect(blurred.querySelectorAll("h3").length).toBe(3);
    expect(blurred).toHaveAttribute("aria-hidden", "true");
    // SIGV2-1255: the gate is the Advisor action plan (Standard and up), not
    // the withdrawn workflow automations feature, and the lock copy never
    // hardcodes "Specialist".
    expect(document.body.textContent).not.toContain("Specialist");
    expect(document.body.textContent).toContain("Standard");
    expect(screen.getByRole("link", { name: /Upgrade to Standard/i })).toHaveAttribute(
      "href",
      "/dashboard/billing?section=plans&plan=plan_standard"
    );
  });

  it("rates Improve impact as a category, never as a predicted gain (SIGV2-1211)", async () => {
    // This suite mocks the normalizer as a pass-through, so the canonical
    // report is the audit object itself.
    auditMock.current = {
      ...defaultAudit,
      latestAudit: {
        ...(defaultAudit.latestAudit as Record<string, unknown>),
        scores: {
          seo: 81,
          seo_breakdown: { penalties: [{ reason: "Missing canonical URL", impact: -12 }] },
        },
        suggestions: [
          { category: "technical", title: "Fix meta tags", action: "Add missing metadata." },
        ],
      },
    };
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });

    const panel = document.getElementById("signal-tabpanel-improve")!;
    // The penalty carries a measured deduction, so the band is real and the
    // row is rated. The deduction itself is not a promise of what a fix would
    // gain, so the number is never printed.
    expect(within(panel).getByText("Impact: High")).toBeInTheDocument();
    // The plain suggestion carries no numeric source at all, so it stays
    // unrated instead of defaulting to Medium.
    expect(within(panel).getByText("Impact: not rated")).toBeInTheDocument();
    expect(within(panel).queryByText("Impact: Medium")).toBeNull();
    expect(panel.textContent).not.toContain("PTS");
    expect(panel.textContent).not.toMatch(/\+\s?\d/);
    expect(panel.textContent).not.toMatch(/\d+\s*(pts?|points?)/i);
  });

  it("labels the Improve list as audit findings, with its own count (SIGV2-1175)", async () => {
    // The Improve tab and the action plan read disjoint data sets; each names
    // its source and states its own count so the button can never again read
    // as the expanded version of this list.
    auditMock.current = {
      ...defaultAudit,
      latestAudit: {
        ...(defaultAudit.latestAudit as Record<string, unknown>),
        suggestions: [
          { category: "technical", title: "Fix meta tags", action: "Add missing metadata." },
          { category: "content", title: "Thin homepage copy", action: "Expand the copy." },
        ],
      },
    };
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });

    const panel = document.getElementById("signal-tabpanel-improve")!;
    // Row titles are h3; the hidden lock overlay has one too, excluded here.
    const rendered =
      panel.querySelectorAll("h3").length - panel.querySelectorAll('[class*="z-10"] h3').length;
    expect(rendered).toBe(2);
    expect(panel).toHaveTextContent(`${rendered} of 2 audit findings`);
    expect(within(panel).getByRole("link", { name: "Advisor action plan" })).toHaveAttribute(
      "href",
      "/dashboard/projects/42/fixes"
    );
    expect(within(panel).queryByRole("link", { name: "Full action plan" })).toBeNull();
    // SIGV2-1193: the Improve list and the action plan are one list now, so
    // every row states the channel that raised it and the link goes to the
    // same list in full rather than to a different data set. No numeric
    // impact appears on any of these rows either.
    expect(within(panel).getAllByText("From the audit").length).toBe(rendered);
    expect(panel.textContent).not.toMatch(/\d+\s*(pts?|points?|%)/i);
    expect(panel.textContent).not.toMatch(/[+\u2212-]\s?\d+(\.\d+)?\s*(pt|point|%)/i);
  });

  it("states the finding total but no shown count while the list is locked", async () => {
    auditMock.current = {
      ...defaultAudit,
      project: {
        ...defaultAudit.project,
        feature_access: {
          advisor_recommendations: {
            allowed: false,
            detail: null,
            status_code: null,
            required_plan: "Standard",
          },
        },
      },
      latestAudit: {
        ...(defaultAudit.latestAudit as Record<string, unknown>),
        suggestions: [
          { category: "technical", title: "Fix meta tags", action: "Add missing metadata." },
        ],
      },
    };
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });

    const panel = document.getElementById("signal-tabpanel-improve")!;
    expect(panel).toHaveTextContent("1 audit findings, ranked by impact");
  });

  it("shows the canonical SEO score and no invented target", () => {
    render(
      <PageHeaderHarness>
        <ProjectSeoPage />
      </PageHeaderHarness>
    );

    expect(screen.getAllByText("81").length).toBeGreaterThan(0);
    // SIGV2-1006: no score target is persisted anywhere, so the card says so.
    expect(screen.getByText("Score targets are not available yet")).toBeInTheDocument();
    expect(screen.queryByText(/85/)).not.toBeInTheDocument();
  });

  it("lists the five measured ranking factors, not the repeated aggregate", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Ranking factors/ }));
    const panel = within(document.getElementById("signal-tabpanel-factors")!);

    expect(panel.getByText("Core Web Vitals")).toBeInTheDocument();
    expect(panel.getByText("Technical setup")).toBeInTheDocument();
    expect(panel.getByText("On-page content")).toBeInTheDocument();
    expect(panel.getByText("Expertise and trust")).toBeInTheDocument();
    expect(panel.getByText("Security and accessibility")).toBeInTheDocument();
    expect(panel.queryByText("On-page signals")).not.toBeInTheDocument();
  });

  it("marks per-factor fix lists as unmeasured rather than showing the global list", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Ranking factors/ }));
    const panel = within(document.getElementById("signal-tabpanel-factors")!);

    fireEvent.click(panel.getByRole("button", { name: /Core Web Vitals/ }));
    expect(panel.getAllByText(/per-factor fix lists are not produced yet/i).length).toBeGreaterThan(
      0
    );
    // The global recommendation must not appear under a factor heading.
    expect(panel.queryByText("Fix meta tags")).toBeNull();
  });

  it("renders keywords with real positions and an honest trend column", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Keywords/ }));
    const panel = within(document.getElementById("signal-tabpanel-keywords")!);
    await waitFor(() => expect(panel.getByText("boutique hotel waterfront")).toBeInTheDocument());

    const row1 = panel.getByText("boutique hotel waterfront").closest("tr")!;
    expect(row1).toHaveTextContent("#4");
    const row2 = panel.getByText("quiet hotel late checkout").closest("tr")!;
    expect(row2).toHaveTextContent("#12");
    // A snapshot exists but carries no position.
    const row3 = panel.getByText("pet friendly seaside hotel").closest("tr")!;
    expect(row3).toHaveTextContent(/Not measured/i);
    // A tracked keyword with no snapshot yet.
    const row4 = panel.getByText("weekend break by the sea").closest("tr")!;
    expect(row4).toHaveTextContent(/Not measured/i);

    // Trend needs two dated snapshots; the endpoint returns the latest one
    // per keyword only, so every row is unmeasured with the reason attached.
    expect(row1).toHaveTextContent(/Not measured/i);
    const trendCells = document
      .getElementById("signal-tabpanel-keywords")!
      .querySelectorAll("td[data-col='trend']");
    expect(trendCells).toHaveLength(4);
    trendCells.forEach((td) => expect(td).toHaveTextContent(/Not measured/i));

    // Intent and search volume do not exist in the product: no such columns.
    expect(panel.queryByText("Intent")).toBeNull();
    expect(panel.queryByText(/Volume/)).toBeNull();
  });

  // ------------------------------------------------------------------
  // SIGV2-1145: Add keyword is a dialog on this tab. It used to navigate to a
  // monitoring page the approved MVP does not contain. Tracked keywords carry
  // no plan allowance anywhere in the product, so the dialog states no cap it
  // cannot read; the refusals that exist are the API's own and are shown.
  // ------------------------------------------------------------------
  const openAddKeyword = async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Keywords/ }));
    const panel = within(document.getElementById("signal-tabpanel-keywords")!);
    await act(async () => {
      fireEvent.click(panel.getByRole("button", { name: /Add keyword/ }));
    });
    return screen.getByRole("dialog");
  };

  it("adds a keyword from the Keywords tab without leaving the page", async () => {
    const dialog = await openAddKeyword();

    fireEvent.change(within(dialog).getByPlaceholderText("boutique hotel waterfront"), {
      target: { value: "  hotel with a cooling mattress  " },
    });

    // The new keyword has no position until the next ranking check runs, so
    // the reloaded feed carries it with no snapshot and the table says so.
    monitoringMock.listTargetKeywords.mockResolvedValue([
      ...KEYWORDS,
      {
        id: 15,
        keyword: "hotel with a cooling mattress",
        search_engine: "google",
        language_code: "en",
        location_code: null,
        is_active: true,
        created_at: "2026-10-06T00:00:00.000Z",
      },
    ]);

    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add keyword" }));
    });

    expect(monitoringMock.createTargetKeyword).toHaveBeenCalledTimes(1);
    const [projectArg, payload] = monitoringMock.createTargetKeyword.mock.calls[0];
    expect(projectArg).toBe("42");
    expect(payload).toEqual({ keyword: "hotel with a cooling mattress" });

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const row = screen.getByText("hotel with a cooling mattress").closest("tr")!;
    expect(row).toHaveTextContent(/Not measured/i);
  });

  it("shows the API's own refusal rather than failing silently", async () => {
    monitoringMock.createTargetKeyword.mockRejectedValue(
      new Error("Keyword already exists for this project")
    );

    const dialog = await openAddKeyword();
    fireEvent.change(within(dialog).getByPlaceholderText("boutique hotel waterfront"), {
      target: { value: "boutique hotel waterfront" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add keyword" }));
    });

    const stillOpen = screen.getByRole("dialog");
    expect(
      within(stillOpen).getByText("Keyword already exists for this project")
    ).toBeInTheDocument();
    // And the refusal points at where an existing keyword is managed.
    expect(
      within(stillOpen).getByRole("link", { name: "Manage tracked keywords" })
    ).toHaveAttribute("href", "/dashboard/projects/42/monitoring#tracked-keywords");
  });

  it("asks for the keyword instead of doing nothing when it is empty", async () => {
    const dialog = await openAddKeyword();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add keyword" }));
    });

    expect(
      within(dialog).getByText("Enter the keyword you want Signal to track.")
    ).toBeInTheDocument();
    expect(monitoringMock.createTargetKeyword).not.toHaveBeenCalled();
    // A field this dialog can fix is not a reason to send anyone elsewhere.
    expect(within(dialog).queryByRole("link", { name: "Manage tracked keywords" })).toBeNull();
  });

  it("never sends Add keyword to the unapproved monitoring page", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Keywords/ }));
    const panel = within(document.getElementById("signal-tabpanel-keywords")!);
    await waitFor(() => expect(panel.getByText("boutique hotel waterfront")).toBeInTheDocument());

    expect(panel.getByRole("button", { name: /Add keyword/ })).toBeInTheDocument();
    expect(
      panel
        .queryAllByRole("link", { hidden: true })
        .filter((node) => node.getAttribute("href")?.includes("/monitoring"))
    ).toHaveLength(0);
  });

  it("offers the same dialog when no keyword is tracked yet", async () => {
    monitoringMock.listTargetKeywords.mockResolvedValue([]);
    monitoringMock.fetchSerpTrackingSummary.mockResolvedValue({
      ...SERP_SUMMARY,
      total_keywords: 0,
      latest_snapshots: [],
    });

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Keywords/ }));
    const panel = within(document.getElementById("signal-tabpanel-keywords")!);
    await waitFor(() => expect(panel.getByText(/No tracked keywords yet/i)).toBeInTheDocument());

    await act(async () => {
      fireEvent.click(panel.getAllByRole("button", { name: /Add keyword/ })[1]);
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("renders the pages table with sessions distinct from clicks and named gaps", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Pages/ }));
    const panel = within(document.getElementById("signal-tabpanel-pages")!);
    await waitFor(() => expect(panel.getByText("/waterfront")).toBeInTheDocument());

    // Sessions are GA4 values, never GSC clicks.
    const row1 = panel.getByText("/rooms/deluxe-king").closest("tr")!;
    expect(row1).toHaveTextContent("6,240");
    const row3 = panel.getByText("/amenities").closest("tr")!;
    // /amenities has 40 clicks but no GA4 match: the sessions cell must not
    // show the click count or a blank.
    expect(row3).toHaveTextContent(/Not available/i);
    expect(row3).not.toHaveTextContent("40");
    expect(row3.querySelector("[data-reason='no_ga4_match']")).not.toBeNull();
    // Impression-weighted position from the payload, not recomputed.
    expect(row1).toHaveTextContent("3.2");
    // Incomplete rows are flagged.
    expect(row3).toHaveTextContent(/incomplete/i);
    // Opportunity renders the backend verdict, not a recomputed one.
    expect(row1).toHaveTextContent(/Low click-through/i);
    expect(panel.getByText("/waterfront").closest("tr")!).toHaveTextContent(/Page-2 push/i);
    // date_basis and approximate alignment are named in the section chrome.
    expect(panel.getByText(/America\/Los_Angeles/)).toBeInTheDocument();
    expect(panel.getByText(/approximate/i)).toBeInTheDocument();
  });

  it("names why pages cannot load when Search Console is disconnected", async () => {
    monitoringMock.fetchSearchConsolePages.mockResolvedValue({
      status: "disconnected",
      availability: "disconnected",
    });
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Pages/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/Search Console is not connected/i).length).toBeGreaterThan(0)
    );
  });

  it("offers the approved Export menu and requests the seo report kind", async () => {
    // Signal SEO Detail.html:54 -> mockup/app.js wireExport: Export opens the
    // `.exp-menu`, and the variant chosen drives the request.
    reportMock.generateComplexReportPdf.mockResolvedValue({
      report_id: "r1",
      status: "queued",
      template_type: "Executive",
      generated_at: "",
      audit_count: 1,
      executive_summary: null,
      aggregate: null,
      download_url: null,
    });
    reportMock.fetchComplexReportStatus.mockResolvedValue({
      report_id: "r1",
      status: "succeeded",
      download_url: "/x",
    });

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });

    const trigger = screen.getByRole("button", { name: /^Export$/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    await act(async () => {
      fireEvent.click(trigger);
    });
    expect(screen.getByText("Export report")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /SEO report/ }));
    });

    await waitFor(() =>
      expect(reportMock.generateComplexReportPdf).toHaveBeenCalledWith(
        expect.objectContaining({
          audit_ids: [700],
          report_options: expect.objectContaining({
            report_kind: "seo",
            report_type: "standard",
          }),
        }),
        expect.objectContaining({ Authorization: "Bearer token" })
      )
    );
  });

  it("locks a variant the plan does not include, and names the plan that unlocks it", async () => {
    // The lock is the API's answer, not a client-side table: the fixture
    // answers as it would if a kind ever stopped being free.
    reportMock.fetchReportExportVariants.mockResolvedValue(
      exportVariantsResponse({ aio: { locked: true, required_plan_label: "Standard" } })
    );
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectSeoPage />
        </PageHeaderHarness>
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Export$/i }));
    });

    const aio = screen.getByRole("menuitem", { name: "AIO report - Locked, Standard" });
    expect(aio).toHaveAttribute("aria-disabled", "true");
    await act(async () => {
      fireEvent.click(aio);
    });
    expect(reportMock.generateComplexReportPdf).not.toHaveBeenCalled();
  });

  it("warns when the view is built on stale check data", () => {
    auditMock.current = { ...defaultAudit, auditSelection: STALE_SELECTION };
    render(
      <PageHeaderHarness>
        <ProjectSeoPage />
      </PageHeaderHarness>
    );

    expect(screen.getByText("Refresh Recommended")).toBeInTheDocument();
    expect(screen.getByText(/38 days old/i)).toBeInTheDocument();
  });

  // SIGV2-1036: both directions, because the defect was the banner rendering
  // in the healthy case. The old block's message came from
  // `diagnostics.summary`, which is never empty, so every audit got an amber
  // banner titled "Partial evidence" whose own body said the evidence was
  // complete, and its 113px of flow pushed every section below it out of
  // register with the approved frame. It is now gated on the audit record's
  // own status alone.
  it("says nothing about evidence when the check is healthy", () => {
    auditMock.current = { ...defaultAudit };
    render(
      <PageHeaderHarness>
        <ProjectSeoPage />
      </PageHeaderHarness>
    );

    expect(screen.queryByText(/degraded state/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Partial evidence")).not.toBeInTheDocument();
    // The old unconditional message, which is what made the block always-on.
    expect(screen.queryByText(/direct audit evidence is available/i)).not.toBeInTheDocument();
  });

  it("warns when the check completed in a degraded state", () => {
    auditMock.current = {
      ...defaultAudit,
      latestAudit: { ...defaultAudit.latestAudit, status: "degraded" },
    };
    render(
      <PageHeaderHarness>
        <ProjectSeoPage />
      </PageHeaderHarness>
    );

    expect(screen.getByText("This check ran in a degraded state")).toBeInTheDocument();
    expect(screen.getByText("Only directly supported fields are shown.")).toBeInTheDocument();
  });
});
