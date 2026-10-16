import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { exportVariantsResponse } from "@/services/__fixtures__/exportVariants";
import { tEn } from "@/test/i18nEn";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn, i18n: { language: "en" } }),
}));

const {
  fetchProjectCompetitors,
  fetchProjectCompetitiveAnalysis,
  fetchProjectCompetitiveGaps,
  fetchProjectCompetitiveTrends,
  createProjectCompetitor,
  deleteProjectCompetitor,
  refreshProjectCompetitiveAnalysis,
  getTokenMock,
  toastSuccess,
  toastError,
  projectState,
  auditState,
  fetchReportExportVariants,
} = vi.hoisted(() => ({
  fetchProjectCompetitors: vi.fn(),
  fetchProjectCompetitiveAnalysis: vi.fn(),
  fetchProjectCompetitiveGaps: vi.fn(),
  fetchProjectCompetitiveTrends: vi.fn(),
  createProjectCompetitor: vi.fn(),
  deleteProjectCompetitor: vi.fn(),
  refreshProjectCompetitiveAnalysis: vi.fn(),
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  projectState: {
    project: {
      name: "Northwind Hotels",
      domain_url: "https://northwind-hotels.com",
      feature_access: { benchmark_intelligence: { allowed: true } },
    },
  },
  auditState: {
    latestAudit: null as null | { id?: number; full_report: unknown },
  },
  fetchReportExportVariants: vi.fn(),
}));

vi.mock("@/services/reportService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/reportService")>();
  return {
    ...actual,
    fetchReportExportVariants: (...args: unknown[]) => fetchReportExportVariants(...args),
  };
});

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useParams: () => ({ projectId: "42" }),
  };
});

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock, isSignedIn: true }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => ({
    project: projectState.project,
    latestAudit: auditState.latestAudit,
    loading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/types/auditResult", async () => {
  const actual = await vi.importActual<typeof import("@/types/auditResult")>("@/types/auditResult");
  return {
    ...actual,
    isAuditResult: () => true,
  };
});

vi.mock("@/services/workspaceService", async () => {
  const actual = await vi.importActual<typeof import("@/services/workspaceService")>(
    "@/services/workspaceService"
  );
  return {
    ...actual,
    fetchProjectCompetitors: (...args: unknown[]) => fetchProjectCompetitors(...args),
    fetchProjectCompetitiveAnalysis: (...args: unknown[]) =>
      fetchProjectCompetitiveAnalysis(...args),
    fetchProjectCompetitiveGaps: (...args: unknown[]) => fetchProjectCompetitiveGaps(...args),
    fetchProjectCompetitiveTrends: (...args: unknown[]) => fetchProjectCompetitiveTrends(...args),
    createProjectCompetitor: (...args: unknown[]) => createProjectCompetitor(...args),
    deleteProjectCompetitor: (...args: unknown[]) => deleteProjectCompetitor(...args),
    refreshProjectCompetitiveAnalysis: (...args: unknown[]) =>
      refreshProjectCompetitiveAnalysis(...args),
  };
});

let ProjectCompetitorsPage: React.ComponentType;

describe("ProjectCompetitorsPage (real competitor CRUD, MVP visual style)", () => {
  beforeAll(async () => {
    const pageModule = await import("@/app/(app)/dashboard/projects/[projectId]/competitors/page");
    ProjectCompetitorsPage = pageModule.default;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getTokenMock.mockResolvedValue("token-123");
    fetchReportExportVariants.mockResolvedValue(
      // Specialist, so the Competitors report this screen leads with is
      // unlocked.
      exportVariantsResponse({ competitors: { locked: false } }, "plan_specialist")
    );
    auditState.latestAudit = null;
    projectState.project = {
      name: "Northwind Hotels",
      domain_url: "https://northwind-hotels.com",
      feature_access: { benchmark_intelligence: { allowed: true } },
    };
    fetchProjectCompetitors.mockResolvedValue([
      {
        id: 7,
        project_id: 42,
        competitor_site_id: null,
        target_url: "https://coastline-resorts.com",
        normalized_domain: "coastline-resorts.com",
        display_name: "Coastline Resorts",
        auto_audit_enabled: true,
        created_at: "2026-01-01T00:00:00.000Z",
        latest_status: "succeeded",
        latest_failure_reason: null,
        last_benchmarked_at: "2026-01-05T00:00:00.000Z",
        latest_source_audit_id: 99,
        latest_scores: { geo: 80, seo: 81, aeo: 72, overall: 78 },
      },
    ]);
    fetchProjectCompetitiveAnalysis.mockResolvedValue({
      project_id: 42,
      project: {
        id: 42,
        name: "Northwind Hotels",
        url: "https://northwind-hotels.com",
        scores: { geo: 60, seo: 72, aeo: 62, overall: 66 },
        last_audit_at: "2026-01-04T00:00:00.000Z",
      },
      competitors: [
        {
          id: 7,
          name: "Coastline Resorts",
          url: "https://coastline-resorts.com",
          status: "succeeded",
          last_benchmarked_at: "2026-01-05T00:00:00.000Z",
          failure_reason: null,
          scores: { geo: 80, seo: 81, aeo: 72, overall: 78 },
          delta: { geo: -20, seo: -9, aeo: -10, overall: -12 },
        },
      ],
      rank: { geo: 2, seo: 2, aeo: 2, overall: 2 },
      updated_at: "2026-01-05T00:00:00.000Z",
      benchmark_status: {
        auto_competitor_audits_enabled: true,
        competitive_digest_frequency: "weekly",
        pending_competitors: 0,
        failed_competitors: 0,
        configured_competitors: 1,
        has_data: true,
      },
    });
    fetchProjectCompetitiveGaps.mockResolvedValue({
      project_id: 42,
      generated_at: "2026-01-05T00:00:00.000Z",
      summary: { gap_count: 1, largest_gap_metric: "seo", largest_gap_delta: 9 },
      gaps: [
        {
          competitor_id: 7,
          competitor_name: "Coastline Resorts",
          metric: "seo",
          project_score: 72,
          competitor_score: 81,
          delta: 9,
          severity: "medium",
          reason: "Stronger backlink authority",
          recommendation: "Publish more linkable location pages",
          evidence: [],
        },
      ],
      pending_competitors: [],
      failed_competitors: [],
    });
    fetchProjectCompetitiveTrends.mockImplementation((_id, _h, options) => {
      const period = options?.period ?? "1y";
      const points =
        period === "30d"
          ? [
              { date: "2026-09-08", value: null },
              { date: "2026-09-15", value: null },
            ]
          : [];
      return Promise.resolve({
        project_id: 42,
        metric: options?.metric ?? "overall",
        period,
        lines: [
          {
            key: "project",
            label: "Northwind Hotels",
            is_project: true,
            points:
              period === "30d"
                ? [
                    { date: "2026-09-08", value: 63 },
                    { date: "2026-09-29", value: 66 },
                  ]
                : [
                    { date: "2026-08-01", value: 60 },
                    { date: "2026-09-01", value: 63 },
                    { date: "2026-09-29", value: 66 },
                  ],
          },
          {
            key: "7",
            label: "Coastline Resorts",
            is_project: false,
            points:
              period === "30d"
                ? [
                    { date: "2026-09-08", value: 76 },
                    { date: "2026-09-29", value: 78 },
                  ]
                : [
                    { date: "2026-08-01", value: 72 },
                    { date: "2026-09-01", value: 75 },
                    { date: "2026-09-29", value: 78 },
                  ],
          },
        ],
      });
    });
  });

  it("renders a real leaderboard with a You row and a tracked competitor, ranked by visibility", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect((await screen.findAllByText("Coastline Resorts")).length).toBeGreaterThan(0);
    expect(screen.getByText("YOU")).toBeInTheDocument();
    // Visibility (overall) for the competitor row.
    expect(screen.getAllByText("78").length).toBeGreaterThan(0);
    // Real measured-gap section driven by fetchProjectCompetitiveGaps.
    expect(screen.getByText("Where you're behind")).toBeInTheDocument();
    expect(screen.getByText(/Where Coastline Resorts is ahead/)).toBeInTheDocument();
  });

  it("MOBILE-R3 does not reuse the .comp settings-chip class on the competitor page root", async () => {
    const { container } = render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect((await screen.findAllByText("Coastline Resorts")).length).toBeGreaterThan(0);
    expect(container.firstElementChild).not.toHaveClass("comp");
  });

  it("adds a competitor via the real createProjectCompetitor call", async () => {
    createProjectCompetitor.mockResolvedValue({
      id: 8,
      project_id: 42,
      competitor_site_id: null,
      target_url: "https://harbourview.co",
      normalized_domain: "harbourview.co",
      display_name: "Harbour View",
      auto_audit_enabled: true,
      created_at: "2026-01-06T00:00:00.000Z",
      latest_status: "not_started",
      latest_failure_reason: null,
      last_benchmarked_at: null,
      latest_source_audit_id: null,
      latest_scores: { geo: null, seo: null, aeo: null, overall: null },
    });

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    fireEvent.click(screen.getAllByRole("button", { name: /Add competitor/i })[0]);
    const dialog = await screen.findByRole("dialog");
    const urlInput = within(dialog).getByPlaceholderText("https://competitor.com");
    fireEvent.change(urlInput, { target: { value: "https://harbourview.co" } });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Add competitor$/i }));

    await waitFor(() =>
      expect(createProjectCompetitor).toHaveBeenCalledWith(
        "42",
        { target_url: "https://harbourview.co", display_name: null },
        { Authorization: "Bearer token-123" }
      )
    );
    expect(toastSuccess).toHaveBeenCalledWith("Competitor added.");
  });

  it("removes a competitor via the real deleteProjectCompetitor call", async () => {
    deleteProjectCompetitor.mockResolvedValue(undefined);

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    fireEvent.click(screen.getByRole("button", { name: /Remove Coastline Resorts/i }));

    await waitFor(() =>
      expect(deleteProjectCompetitor).toHaveBeenCalledWith("42", 7, {
        Authorization: "Bearer token-123",
      })
    );
    expect(toastSuccess).toHaveBeenCalledWith("Competitor removed.");
  });

  it("shows the Pro gate and never calls the competitor endpoints when locked", async () => {
    projectState.project = {
      name: "Northwind Hotels",
      domain_url: "https://northwind-hotels.com",
      feature_access: { benchmark_intelligence: { allowed: false } },
    };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findByText("Specialist")).toBeInTheDocument();
    const gate = screen.getByRole("dialog", { name: "See how you stack up" });
    expect(gate).toHaveAccessibleDescription(
      /Track your search and recommendation scores against every competitor/i
    );
    expect(fetchProjectCompetitors).not.toHaveBeenCalled();

    // The page behind the gate is blurred and pointer-events:none while locked,
    // so the gate must not be dismissible: doing so used to strand the user on an
    // unreadable, non-interactive page. Upgrade and the fallback are the only exits.
    expect(within(gate).queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    expect(within(gate).queryByRole("button", { name: "Not now" })).not.toBeInTheDocument();
    expect(within(gate).getByRole("link", { name: "Upgrade to Specialist" })).toBeVisible();
    expect(within(gate).getByRole("link", { name: "Back to dashboard" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "See how you stack up" })).toBeInTheDocument();
  });

  const reportWithComparisons = {
    aeo_site_stats: {
      competitor_snippet_comparisons: [
        {
          query: "Which hotel has the best sea view?",
          winner: "competitor",
          site: {
            domain: "northwind-hotels.com",
            answer_relevance: 30,
            answer_excerpt: "Northwind is by the harbour.",
          },
          competitor: {
            domain: "coastline-resorts.com",
            answer_relevance: 92,
            answer_excerpt: "Coastline Resorts has panoramic sea views.",
            selected_audit_timestamp: "2026-01-05T00:00:00.000Z",
          },
        },
        {
          query: "Which hotel is the cheapest?",
          winner: "no_data",
          site: {
            domain: "northwind-hotels.com",
            answer_relevance: null,
            answer_excerpt: null,
          },
          competitor: null,
          competitors: [
            {
              domain: "coastline-resorts.com",
              answer_relevance: null,
              answer_excerpt: null,
            },
          ],
        },
        {
          query: "Which hotel allows pets?",
          winner: "competitor",
          winner_reason: "missing_site_data",
          site: {
            domain: "northwind-hotels.com",
            answer_relevance: null,
            answer_excerpt: null,
          },
          competitor: {
            domain: "coastline-resorts.com",
            answer_relevance: null,
            answer_excerpt: null,
          },
        },
      ],
    },
  };

  it("shows one card per competitor with its real win count", async () => {
    auditState.latestAudit = { full_report: reportWithComparisons };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect((await screen.findAllByText("Coastline Resorts")).length).toBeGreaterThan(0);
    // One measured competitor win out of two measured questions; the
    // missing_site_data entry is reported as not measured, never as a win.
    expect(screen.getByText("Wins 1 of 2 questions")).toBeInTheDocument();
    expect(screen.getByText("1 question was not measured.")).toBeInTheDocument();
    expect(screen.getByText("On 1 question AI named nobody.")).toBeInTheDocument();
  });

  it("reveals the winning answer excerpt and its date through the disclosure", async () => {
    auditState.latestAudit = { full_report: reportWithComparisons };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    const toggle = screen.getByRole("button", { name: "See the questions" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/panoramic sea views/i)).not.toBeInTheDocument();

    fireEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Which hotel has the best sea view?")).toBeInTheDocument();
    expect(screen.getByText(/panoramic sea views/i)).toBeInTheDocument();
    expect(screen.getByText("Answer from Jan 5, 2026")).toBeInTheDocument();
  });

  it("says a competitor was not assessed when it appears in no measured question", async () => {
    auditState.latestAudit = {
      full_report: {
        aeo_site_stats: {
          competitor_snippet_comparisons: [
            {
              query: "Which hotel has the best sea view?",
              winner: "competitor",
              site: {
                domain: "northwind-hotels.com",
                answer_relevance: 30,
                answer_excerpt: "Northwind is by the harbour.",
              },
              competitor: {
                domain: "untracked-rival.com",
                answer_relevance: 92,
                answer_excerpt: "Some other hotel wins.",
              },
            },
          ],
        },
      },
    };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findAllByText("Coastline Resorts")).not.toHaveLength(0);
    expect(screen.getByText("Not assessed on any question in this check.")).toBeInTheDocument();
    expect(
      screen.getByText(/a competitor won, but we could not tell which one/)
    ).toBeInTheDocument();
  });

  it("shows real benchmark status and offers a benchmark run for unmeasured competitors", async () => {
    // SIGV2-1095: a competitor added then scanned manually gets no benchmark -
    // competitor jobs only enqueue for scheduled audits. The page must say so
    // and offer the existing refresh endpoint instead of an empty table.
    fetchProjectCompetitors.mockResolvedValue([
      {
        id: 7,
        project_id: 42,
        competitor_site_id: null,
        target_url: "https://coastline-resorts.com",
        normalized_domain: "coastline-resorts.com",
        display_name: "Coastline Resorts",
        auto_audit_enabled: true,
        created_at: "2026-01-01T00:00:00.000Z",
        latest_status: "not_started",
        latest_failure_reason: null,
        last_benchmarked_at: null,
        latest_source_audit_id: null,
        latest_scores: { geo: null, seo: null, aeo: null, overall: null },
      },
    ]);
    refreshProjectCompetitiveAnalysis.mockResolvedValue({
      project_id: 42,
      queued_jobs: ["job-1"],
      skipped_competitors: [],
      message: "queued",
    });
    auditState.latestAudit = { full_report: reportWithComparisons };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findAllByText("Not benchmarked yet")).not.toHaveLength(0);
    const cta = await screen.findByRole("button", { name: "Benchmark competitors" });
    fireEvent.click(cta);
    await waitFor(() =>
      expect(refreshProjectCompetitiveAnalysis).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      })
    );
  });

  it("shows an honest empty state when no competitors are tracked", async () => {
    fetchProjectCompetitors.mockResolvedValue([]);

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findByText(/No competitors tracked yet/)).toBeInTheDocument();
  });

  it("says there is no check yet when competitors exist but no audit ran", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findByText(/No check has run yet for this site/)).toBeInTheDocument();
  });

  it("says the check produced no question comparisons when the report lacks them", async () => {
    auditState.latestAudit = {
      full_report: { aeo_site_stats: { competitor_snippet_comparisons: [] } },
    };

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(
      await screen.findByText(/did not compare answers on individual questions/)
    ).toBeInTheDocument();
  });

  it("keeps the Add button disabled at the five-competitor limit", async () => {
    fetchProjectCompetitors.mockResolvedValue(
      Array.from({ length: 5 }, (_, i) => ({
        id: i + 1,
        project_id: 42,
        competitor_site_id: null,
        target_url: `https://rival-${i}.com`,
        normalized_domain: `rival-${i}.com`,
        display_name: `Rival ${i}`,
        auto_audit_enabled: true,
        created_at: "2026-01-01T00:00:00.000Z",
        latest_status: "succeeded",
        latest_failure_reason: null,
        last_benchmarked_at: null,
        latest_source_audit_id: null,
        latest_scores: { geo: null, seo: null, aeo: null, overall: null },
      }))
    );

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findByText("Rival 0");

    /*
     * The limit disables a button the page registers into the shell header from
     * an effect, so it lands one commit after the list that `findByText` waited
     * for. React schedules that passive effect on a task while the
     * MutationObserver resolving `findByText` runs on a microtask, so at the
     * instant the first row becomes observable the header still holds the
     * pre-limit render and the button is observably enabled. Waiting on the
     * list proves nothing about the button; wait for the limit state itself.
     */
    const addButton = await waitFor(() => {
      const [button] = screen.getAllByRole("button", { name: /Add competitor/i });
      expect(button).toBeDisabled();
      return button;
    });
    expect(addButton).toHaveAttribute("title", "You can track up to 5 competitors.");
  });

  it("never renders banned wording in the visible copy", async () => {
    auditState.latestAudit = { full_report: reportWithComparisons };

    const { container } = render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    // AIO and "blended visibility" are approved vocabulary (the AIO column
    // and the chart caption); AEO/GEO raw labels and share-of-voice are not.
    expect(container.textContent).not.toMatch(/\bAEO\b|\bGEO\b|share of voice/i);
  });

  it("renders the hero rank badge, ordinal title and gap-to-#1 from analysis.rank", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    expect(await screen.findByText("2nd")).toBeInTheDocument();
    expect(screen.getByText("of 2 tracked")).toBeInTheDocument();
    expect(screen.getByText("You're 2nd for AI & search visibility")).toBeInTheDocument();
    expect(screen.getByText("Gap to #1")).toBeInTheDocument();
    // project overall 66 -> leader overall 78.
    const gapCard = screen.getByText("Gap to #1").parentElement!;
    expect(gapCard.textContent).toContain("66");
    expect(gapCard.textContent).toContain("78");
  });

  it("falls back to the generic hero when analysis.rank is absent", async () => {
    fetchProjectCompetitiveAnalysis.mockResolvedValue({
      project_id: 42,
      project: { id: 42, name: "Northwind Hotels", url: null, scores: null, last_audit_at: null },
      competitors: [],
      rank: { seo: null, aeo: null, geo: null, overall: null },
      updated_at: null,
      benchmark_status: {
        auto_competitor_audits_enabled: true,
        competitive_digest_frequency: "weekly",
        pending_competitors: 0,
        failed_competitors: 0,
        configured_competitors: 1,
        has_data: false,
      },
    });

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.getAllByText("Who gets recommended instead of you").length).toBeGreaterThan(0);
    expect(screen.queryByText("of 2 tracked")).not.toBeInTheDocument();
  });

  it("renders leaderboard rank numbers and the AIO roll-up column", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.getAllByText("AIO").length).toBeGreaterThan(0);
    // Coastline aeo 72 + geo 80 -> 76.
    const row = screen
      .getAllByRole("row")
      .find((tr) => within(tr).queryByText("Coastline Resorts"))!;
    expect(within(row).getByText("76")).toBeInTheDocument();
    // Rank cells: leader first, then the project row.
    const ranks = screen
      .getAllByRole("row")
      .slice(1)
      .map((tr) => tr.querySelector("td")?.textContent);
    expect(ranks).toEqual(["1", "2"]);
  });

  it("shows a real 30-day change when the trends feed has history", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.getByText("30-day")).toBeInTheDocument();
    expect(screen.getByText("▲ +3")).toBeInTheDocument(); // project 63->66
    expect(screen.getByText("▲ +2")).toBeInTheDocument(); // Coastline 76->78
  });

  it("labels the last column Gap vs you without arrows when no history exists", async () => {
    fetchProjectCompetitiveTrends.mockResolvedValue({
      project_id: 42,
      metric: "overall",
      period: "30d",
      lines: [],
    });

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.getByText("Gap vs you")).toBeInTheDocument();
    expect(screen.getByText("-12")).toBeInTheDocument();
    expect(screen.queryByText("▲")).not.toBeInTheDocument();
    expect(screen.queryByText("▼")).not.toBeInTheDocument();
  });

  // SIGV2-1174: the head-to-head block is retired, not repopulated. Measuring
  // its three AI-mention rows would mean running every tracked competitor
  // through the project's whole prompt set, so the cost is competitors x
  // prompts with no cap. The section must not come back by accident, so assert
  // every piece of it is absent: the heading in both phrasings, the sub-label,
  // both card titles and all six row labels.
  it("renders no head-to-head section against the leader", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.queryByText("Where Coastline Resorts beats you")).not.toBeInTheDocument();
    expect(screen.queryByText("How you compare with Coastline Resorts")).not.toBeInTheDocument();
    expect(screen.queryByText("head-to-head vs the leader")).not.toBeInTheDocument();

    for (const label of [
      "AI assistant recommendations",
      "Search & authority",
      "Grok mentions",
      "Perplexity mentions",
      "ChatGPT mentions",
      "Backlink authority",
      "Review recency & volume",
      "Query rank on shared queries",
    ]) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }

    // The six rows were the only unmeasured placeholders on this screen.
    expect(screen.queryByText("Not measured")).not.toBeInTheDocument();
    expect(document.querySelector("[data-unmeasured]")).toBeNull();
  });

  // SIGV2-1116: the "Behind" chip used to render unconditionally on both
  // head-to-head cards, in the danger colour, over six "Not measured" rows. A
  // verdict must never outlive its evidence. With that block retired
  // (SIGV2-1174) the gaps card is the only place allowed to claim a standing,
  // because each of its rows carries a measured project and competitor score.
  it("puts the only Behind verdict on the measured gaps card", async () => {
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    const behind = screen.getAllByText("Behind");
    expect(behind).toHaveLength(1);
    const gapsCard = screen
      .getByText("Where Coastline Resorts is ahead")
      .closest("div")!.parentElement!;
    expect(within(gapsCard).getByText("Behind")).toBeInTheDocument();
  });

  it("renders no Behind verdict anywhere when no measured gap exists", async () => {
    fetchProjectCompetitiveGaps.mockResolvedValue({
      project_id: 42,
      generated_at: "2026-01-05T00:00:00.000Z",
      summary: { gap_count: 0, largest_gap_metric: null, largest_gap_delta: null },
      gaps: [],
      pending_competitors: [],
      failed_competitors: [],
    });

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.queryByText("Behind")).not.toBeInTheDocument();
  });

  it("never claims the leader beats you, whatever the measured visibility", async () => {
    fetchProjectCompetitiveAnalysis.mockResolvedValue({
      project_id: 42,
      project: {
        id: 42,
        name: "Northwind Hotels",
        url: "https://northwind-hotels.com",
        scores: { geo: 90, seo: 90, aeo: 90, overall: 90 },
        last_audit_at: "2026-01-04T00:00:00.000Z",
      },
      competitors: [],
      rank: { geo: 1, seo: 1, aeo: 1, overall: 1 },
      updated_at: "2026-01-05T00:00:00.000Z",
      benchmark_status: {
        auto_competitor_audits_enabled: true,
        competitive_digest_frequency: "weekly",
        pending_competitors: 0,
        failed_competitors: 0,
        configured_competitors: 1,
        has_data: true,
      },
    });

    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );
    await screen.findAllByText("Coastline Resorts");

    expect(screen.queryByText("How you compare with Coastline Resorts")).not.toBeInTheDocument();
    expect(screen.queryByText("Where Coastline Resorts beats you")).not.toBeInTheDocument();
  });

  it("leads the Export menu with the Competitors report on this screen", async () => {
    // SIGV2-1255: the competitors screen sells its own report first, then the
    // four report kinds every screen offers.
    auditState.latestAudit = { id: 700, full_report: {} };
    render(
      <PageHeaderHarness>
        <ProjectCompetitorsPage />
      </PageHeaderHarness>
    );

    const trigger = await screen.findByRole("button", { name: "Export" });
    await waitFor(() => expect(trigger).toBeEnabled());
    fireEvent.click(trigger);

    const items = screen.getAllByRole("menuitem");
    expect(items).toHaveLength(5);
    expect(items[0]).toHaveTextContent("Competitors report");
    expect(items.map((item) => item.textContent?.slice(0, 20))).toEqual([
      expect.stringContaining("Competitors report"),
      expect.stringContaining("Standard report"),
      expect.stringContaining("Executive report"),
      expect.stringContaining("AIO report"),
      expect.stringContaining("SEO report"),
    ]);
  });
});
