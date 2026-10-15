import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ProjectAeoPage from "@/app/(app)/dashboard/projects/[projectId]/ai-answers/page";
import { exportVariantsResponse } from "@/services/__fixtures__/exportVariants";
import { tEn } from "@/test/i18nEn";
import { PageHeaderHarness } from "@/test/pageHeaderHarness";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const navMock = vi.hoisted(() => ({ search: new URLSearchParams("") }));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
  useSearchParams: () => navMock.search,
}));

vi.mock("@/types/auditResult", () => ({
  isAuditResult: () => true,
}));

const trendsMock = vi.hoisted(() => ({
  fetchProjectTrends: vi.fn(),
}));

const visibilityMock = vi.hoisted(() => ({
  fetchVisibilitySummary: vi.fn(),
  fetchVisibilityQueries: vi.fn(),
  createVisibilityQuery: vi.fn(),
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

vi.mock("@/services/workspaceService", () => ({
  fetchProjectTrends: (...args: unknown[]) => trendsMock.fetchProjectTrends(...args),
}));

vi.mock("@/services/monitoringService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/monitoringService")>();
  return {
    ...actual,
    fetchVisibilitySummary: (...args: unknown[]) => visibilityMock.fetchVisibilitySummary(...args),
    fetchVisibilityQueries: (...args: unknown[]) => visibilityMock.fetchVisibilityQueries(...args),
    createVisibilityQuery: (...args: unknown[]) => visibilityMock.createVisibilityQuery(...args),
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

const auditMock = vi.hoisted(() => ({
  current: {
    project: { latest_aeo_score: 82, latest_geo_score: 72 },
    loading: false,
    error: null,
    latestAudit: {
      id: 700,
      full_report: {
        aeo: { answerability_score: 82 },
        geo: { visibility_index: 72 },
        metadata: {
          search_types: [],
        },
        suggestions: [],
      },
    },
  } as Record<string, unknown>,
}));
const defaultAudit = auditMock.current;

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => auditMock.current,
}));

const SUMMARY = {
  project_id: 42,
  entitlements: { is_locked: false },
  queries_configured: 3,
  providers: ["openai", "anthropic", "perplexity"],
  visibility_score: 55,
  score_breakdown: null,
  trend_delta: null,
  completed_checks: 6,
  pending_checks: 0,
  cited_checks: 3,
  total_checks: 6,
  last_updated_at: null,
  provider_breakdown: [
    {
      provider: "openai",
      tracked_queries: 3,
      completed_checks: 3,
      cited_checks: 2,
      visibility_score: 82,
    },
    {
      provider: "anthropic",
      tracked_queries: 3,
      completed_checks: 2,
      cited_checks: 1,
      visibility_score: 54,
    },
    {
      provider: "perplexity",
      tracked_queries: 3,
      completed_checks: 1,
      cited_checks: 0,
      visibility_score: 12,
    },
  ],
  queries: [
    {
      id: 1,
      project_id: 42,
      query_text: "best boutique hotels near the harbour",
      query_type: "aeo",
      providers: ["openai", "anthropic"],
      is_active: true,
      created_at: null,
      updated_at: null,
      average_score: 60,
      last_checked_at: null,
      results: [
        {
          provider: "openai",
          status: "cited",
          batch_status: null,
          score: 90,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 2,
        },
        {
          provider: "anthropic",
          status: "not_cited",
          batch_status: null,
          score: 40,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 0,
        },
      ],
    },
    {
      id: 2,
      project_id: 42,
      query_text: "tell me about Northwind Hotels",
      query_type: "geo",
      providers: ["perplexity"],
      is_active: true,
      created_at: null,
      updated_at: null,
      average_score: null,
      last_checked_at: null,
      results: [
        {
          provider: "perplexity",
          status: "not_cited",
          batch_status: null,
          score: null,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 0,
        },
      ],
    },
    {
      id: 3,
      project_id: 42,
      query_text: "quiet hotel with late checkout",
      query_type: "aeo",
      providers: [],
      is_active: true,
      created_at: null,
      updated_at: null,
      average_score: null,
      last_checked_at: null,
      results: [],
    },
  ],
};

// The Prompts tab's own list feed (SIGV2-1194): the same three prompts,
// filed under their scored types, with one type left uncovered so the
// incomplete state is what renders.
const QUERY_LIST = {
  project_id: 42,
  entitlements: {
    plan: "plan_standard",
    plan_label: "Standard",
    upgrade_plan: "plan_specialist",
    upgrade_plan_label: "Specialist",
    upgrade_max_queries: 50,
    max_queries: 10,
    used_queries: 3,
    remaining_queries: 7,
    allowed_providers: ["openai", "anthropic"],
    is_locked: false,
    estimated_cost_per_check: { openai: 1, anthropic: 1 },
  },
  queries: [
    {
      id: 1,
      project_id: 42,
      query_text: "best boutique hotels near the harbour",
      query_type: "aeo",
      search_type: "category",
      search_type_source: "stored",
      origin: "customer",
      is_generated: false,
      providers: ["openai", "anthropic"],
      is_active: true,
      created_at: null,
      updated_at: null,
    },
    {
      id: 2,
      project_id: 42,
      query_text: "tell me about Northwind Hotels",
      query_type: "geo",
      search_type: "brand",
      search_type_source: "stored",
      origin: "generated",
      is_generated: true,
      providers: ["perplexity"],
      is_active: true,
      created_at: null,
      updated_at: null,
    },
    {
      id: 3,
      project_id: 42,
      query_text: "quiet hotel with late checkout",
      query_type: "aeo",
      search_type: null,
      search_type_source: null,
      origin: "customer",
      is_generated: false,
      providers: [],
      is_active: true,
      created_at: null,
      updated_at: null,
    },
  ],
  coverage: ["brand", "category", "problem", "feature", "comparison"].map((id) => ({
    id,
    label: id,
    premium: false,
    prompt_count: id === "brand" || id === "category" ? 1 : 0,
    covered: id === "brand" || id === "category",
    suggested_prompt:
      id === "brand" || id === "category" ? null : `suggested ${id} question for the project`,
  })),
};

beforeEach(() => {
  navMock.search = new URLSearchParams("");
  trendsMock.fetchProjectTrends.mockReset();
  trendsMock.fetchProjectTrends.mockResolvedValue(null);
  visibilityMock.fetchVisibilitySummary.mockReset();
  visibilityMock.fetchVisibilitySummary.mockResolvedValue(SUMMARY);
  visibilityMock.fetchVisibilityQueries.mockReset();
  visibilityMock.fetchVisibilityQueries.mockResolvedValue(QUERY_LIST);
  visibilityMock.createVisibilityQuery.mockReset();
  visibilityMock.createVisibilityQuery.mockResolvedValue({
    id: 4,
    project_id: 42,
    query_text: "quiet hotel with a late checkout",
    query_type: "aeo",
    providers: ["openai"],
    is_active: true,
    created_at: null,
    updated_at: null,
  });
  reportMock.generateComplexReportPdf.mockReset();
  reportMock.fetchComplexReportStatus.mockReset();
  reportMock.downloadComplexReportPdfBlob.mockReset();
  reportMock.fetchReportExportVariants.mockReset();
  reportMock.fetchReportExportVariants.mockResolvedValue(exportVariantsResponse());
  authMock.user = { subscription_plan: "plan_specialist" };
});

afterEach(() => {
  auditMock.current = defaultAudit;
});

describe("ProjectAeoPage (approved AIO detail)", () => {
  it("lays the AIO detail out as the approved four tabs", () => {
    render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );

    const tabs = screen.getAllByRole("tab");
    expect(tabs.map((t) => t.textContent)).toEqual([
      expect.stringContaining("Improve"),
      expect.stringContaining("Search types"),
      expect.stringContaining("By engine"),
      expect.stringContaining("Prompts"),
    ]);
    expect(screen.getByRole("tab", { name: /Improve/ })).toHaveAttribute("aria-selected", "true");

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Are you shown, and trusted, in AI answers?",
      })
    ).toBeInTheDocument();
  });

  // SIGV2-1111: the overview's "Appearance in AI answers" explanation links
  // here. Landing on Improve would make that link a lie.
  it("opens the Prompts tab directly when ?tab=prompts asks for it", async () => {
    navMock.search = new URLSearchParams("tab=prompts");

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    expect(screen.getByRole("tab", { name: /Prompts/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: /Improve/ })).toHaveAttribute("aria-selected", "false");
    expect(document.getElementById("signal-tabpanel-prompts")).not.toHaveAttribute("hidden");
    await waitFor(() =>
      expect(screen.getByText("best boutique hotels near the harbour")).toBeInTheDocument()
    );
  });

  it("ignores a tab the page does not have", async () => {
    navMock.search = new URLSearchParams("tab=nonsense");

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    expect(screen.getByRole("tab", { name: /Improve/ })).toHaveAttribute("aria-selected", "true");
  });

  it("renders the AIO hero with the real derived score", () => {
    render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );

    expect(screen.getByText("AIO score · AI search")).toBeInTheDocument();
    // Hero score = round(mean(aeo 82, geo 72)) = 77.
    expect(screen.getAllByText("77").length).toBeGreaterThan(0);
    // No score target exists anywhere in the product (SIGV2-1006), so the
    // "Path to target" card states that instead of showing a number.
    expect(screen.getByText("Score targets are not available yet")).toBeInTheDocument();
    expect(screen.queryByText(/Path to target/i)).toBeNull();
  });

  it("shows the canonical scores when the report sections are zero", () => {
    auditMock.current = {
      project: { latest_aeo_score: 64, latest_geo_score: 64 },
      loading: false,
      error: null,
      latestAudit: {
        full_report: {
          scores: { aeo: 64, geo: 64 },
          aeo: { answerability_score: 0 },
          geo: { visibility_index: 0 },
          metadata: { search_types: [] },
          suggestions: [],
        },
      },
    };

    const { container } = render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );

    expect(container.querySelector("[data-score-ring] [data-signal-enter='count']")?.textContent).toBe(
      "64"
    );
    expect(container.querySelector('span[class*="text-[30px]"]')?.textContent).toBe("64");
  });

  it("switches to the Search types tab and expands a row", async () => {
    auditMock.current = {
      project: { latest_aeo_score: 82, latest_geo_score: 72 },
      loading: false,
      error: null,
      latestAudit: {
        full_report: {
          aeo: { answerability_score: 82 },
          geo: { visibility_index: 72 },
          metadata: {
            search_types: [
              {
                id: "brand",
                label: "Brand",
                score: 78,
                answer_ratio: { present: 7, measured: 10 },
                insight: "Described correctly in 7 of 10 answers.",
                source: "measured",
              },
              {
                // Tagged with the retired heuristic source, as reports served
                // before SIGV2-1105 are. Its score is not rendered.
                id: "category",
                label: "Category",
                score: 54,
                insight: "Appears in 44% of shortlists.",
                source: "derived",
              },
            ],
          },
          suggestions: [],
        },
      },
    };

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: /Search types/ }));

    // A score nobody measured is not shown, however the payload labels it
    // (SIGV2-1105): the derived row carries no figure and says so.
    const brandRow = screen.getByRole("button", { name: /Brand/ });
    const categoryRow = screen.getByRole("button", { name: /Category/ });
    expect(brandRow).toHaveTextContent("Measured");
    // The approved Signal AIO Detail.html types card has no .ft-ratio line;
    // the answer ratio belongs to the overview feed cards only, so it must
    // not render here even when the payload carries it (SIGV2-1105).
    expect(brandRow).not.toHaveTextContent("7 of 10 answers");
    expect(brandRow).not.toHaveTextContent("Estimated");
    expect(categoryRow).toHaveTextContent("Not measured");
    expect(categoryRow).not.toHaveTextContent("Estimated");
    expect(categoryRow).not.toHaveTextContent("54");

    fireEvent.click(brandRow);
    expect(screen.getByText("Described correctly in 7 of 10 answers.")).toBeInTheDocument();
    // Per-search-type action lists have no source; the section names why
    // rather than re-showing the global recommendations under a type heading.
    expect(
      screen.getAllByText(/Per-search-type actions are not produced yet/i).length
    ).toBeGreaterThan(0);
  });

  // SIGV2-1194: the Prompts tab is the approved prompt-setup surface in
  // manage mode - the project's own prompts grouped under their scored
  // search types, with per-row Edit/Remove and the gaps stated.
  it("renders the project's prompts grouped under their scored search types", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    const panel = within(document.getElementById("signal-tabpanel-prompts")!);
    await waitFor(() =>
      expect(panel.getByText("best boutique hotels near the harbour")).toBeInTheDocument()
    );

    // Manage mode's own heading and the badge naming a customised set.
    expect(panel.getByText("Your project prompts")).toBeInTheDocument();
    expect(panel.getByText("Project prompts")).toBeInTheDocument();

    // Groups follow the canonical order; an uncovered type is open and says so.
    const groups = Array.from(
      document
        .getElementById("signal-tabpanel-prompts")!
        .querySelectorAll("details[data-prompt-group]")
    );
    expect(groups.map((g) => g.getAttribute("data-prompt-group"))).toEqual([
      "brand",
      "category",
      "problem",
      "feature",
      "comparison",
      "pending",
    ]);
    const categoryGroup = groups[1] as HTMLElement;
    expect(
      within(categoryGroup).getByText("best boutique hotels near the harbour")
    ).toBeInTheDocument();
    const problemGroup = groups[2] as HTMLDetailsElement;
    expect(problemGroup.open).toBe(true);
    expect(within(problemGroup).getByText("No prompts")).toBeInTheDocument();

    // Origins: the generated prompt carries the Signal marker.
    expect(panel.getByText("Added by Signal")).toBeInTheDocument();
    expect(panel.getAllByText("Added by you").length).toBe(2);

    // The incomplete coverage is stated as information, never a refusal.
    expect(
      panel.getByText(/an untested type has no score/).closest("[data-signal-inline-note]")
    ).toHaveAttribute("data-signal-inline-note", "info");
    // And no control anywhere on the tab offers a search-type choice.
    expect(panel.queryByRole("combobox")).toBeNull();
  });

  it("files an untyped prompt under Pending classification as unscored", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    await waitFor(() =>
      expect(screen.getByText("quiet hotel with late checkout")).toBeInTheDocument()
    );
    const pending = document.querySelector(
      "#signal-tabpanel-prompts details[data-prompt-group='pending']"
    ) as HTMLElement;
    expect(pending).not.toBeNull();
    expect(within(pending).getByText("quiet hotel with late checkout")).toBeInTheDocument();
    expect(within(pending).getByText(/not scored under any search type/)).toBeInTheDocument();
  });

  it("renders measured provider rows on the By engine tab without inventing a status", async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /By engine/ }));
    const panel = within(document.getElementById("signal-tabpanel-engines")!);
    await waitFor(() => expect(panel.getByText("ChatGPT")).toBeInTheDocument());

    expect(panel.getByText("Claude")).toBeInTheDocument();
    expect(panel.getByText("Perplexity")).toBeInTheDocument();
    // Real measured facts per provider.
    expect(panel.getByText("Cited in 2 of 3 checks")).toBeInTheDocument();
    // A provider score is not a three-way editorial status; no mapping exists
    // in the backend, so the status slot is explicitly unmeasured.
    expect(panel.getAllByText("Not measured").length).toBeGreaterThanOrEqual(3);
    expect(panel.queryByText("Recommended")).toBeNull();
    expect(panel.queryByText("Mentioned")).toBeNull();
    expect(panel.queryByText("Absent")).toBeNull();
    // SIGV2-1299: these fixture cells carry no provenance at all, so no claim
    // either way is made about which model answered.
    expect(panel.queryByTestId("engine-standin-openai")).toBeNull();
    expect(panel.queryByTestId("engine-standin-anthropic")).toBeNull();
  });

  // SIGV2-1299. On preprod, five consecutive days of answers came from the
  // stand-in Bedrock panel under consumer engine labels, so a row that did not
  // reach its named engine has to say so rather than read as a measurement of
  // that engine.
  it("marks an engine row whose answers came from the stand-in model", async () => {
    const presence = (live: boolean) => ({
      state: "domain_citation" as const,
      live_measured: live,
      reason: live ? null : "proxy_measurement_not_live",
    });
    visibilityMock.fetchVisibilitySummary.mockResolvedValue({
      ...SUMMARY,
      queries: [
        {
          ...SUMMARY.queries[0],
          results: [
            // Reached the named engine.
            {
              ...SUMMARY.queries[0].results[0],
              engine_source: "openrouter_live",
              presence: presence(true),
            },
            // Fell back for every check.
            {
              ...SUMMARY.queries[0].results[1],
              engine_source: "bedrock_proxy",
              presence: presence(false),
            },
          ],
        },
        {
          ...SUMMARY.queries[1],
          results: [
            // One engine, one live answer and one stand-in answer.
            {
              ...SUMMARY.queries[1].results[0],
              engine_source: "openrouter_live",
              presence: presence(true),
            },
            {
              ...SUMMARY.queries[1].results[0],
              engine_source: "bedrock_proxy",
              presence: presence(false),
            },
          ],
        },
      ],
    });

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /By engine/ }));
    const panel = within(document.getElementById("signal-tabpanel-engines")!);
    await waitFor(() => expect(panel.getByText("ChatGPT")).toBeInTheDocument());

    // ChatGPT was reached, so nothing is added to its row.
    expect(panel.queryByTestId("engine-standin-openai")).toBeNull();

    // Claude was not reached at all.
    const claude = panel.getByTestId("engine-standin-anthropic");
    expect(claude).toHaveTextContent("Stand-in model, not Claude");
    expect(claude.getAttribute("title")).toContain("not measured on Claude");

    // Perplexity was reached for some checks and not others.
    const perplexity = panel.getByTestId("engine-standin-perplexity");
    expect(perplexity).toHaveTextContent("Some answers from a stand-in model, not Perplexity");

    // The disclosure never names the substitute model to the customer.
    expect(panel.queryByText(/qwen/i)).toBeNull();
    expect(panel.queryByText(/nova/i)).toBeNull();
    expect(panel.queryByText(/bedrock/i)).toBeNull();
  });

  it("names why the prompts and engine tabs are empty when monitoring is not entitled", async () => {
    visibilityMock.fetchVisibilitySummary.mockResolvedValue({
      ...SUMMARY,
      entitlements: { is_locked: true },
      providers: [],
      provider_breakdown: [],
      queries: [],
    });
    visibilityMock.fetchVisibilityQueries.mockResolvedValue({
      ...QUERY_LIST,
      entitlements: { ...QUERY_LIST.entitlements, is_locked: true },
      queries: [],
    });

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/visibility monitoring is not included/i).length).toBeGreaterThan(
        0
      )
    );
  });

  it("keeps the action plan locked behind the Standard upgrade when advisor recommendations are not allowed", () => {
    auditMock.current = {
      project: {
        latest_aeo_score: 82,
        latest_geo_score: 72,
        feature_access: {
          advisor_recommendations: {
            allowed: false,
            detail: null,
            status_code: null,
            required_plan: "Standard",
          },
        },
      },
      loading: false,
      error: null,
      latestAudit: {
        id: 700,
        project_id: 42,
        url: "https://client.example",
        audit_type: "STANDARD",
        created_at: "2026-02-01T09:00:00.000Z",
        status: "completed",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://client.example", market: "us", language: "en" },
          scores: { aeo: 82, geo: 72 },
          aeo: { answerability_score: 82 },
          geo: { visibility_index: 72 },
          entities: [],
          competitors: [],
          metadata: {
            created_at: "2026-02-01T09:00:00.000Z",
            updated_at: "2026-02-01T09:00:00.000Z",
            search_types: [],
          },
          suggestions: [
            {
              category: "aeo",
              title: "Answer the top questions directly",
              action: "Add a short answer block above the fold.",
            },
          ],
        },
      },
    };

    const { container } = render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );

    const blurred = container.querySelector('[class*="blur-[6px]"]') as HTMLElement;
    expect(blurred).not.toBeNull();
    // Blur is presentation, not authorization: the gated suggestion content
    // must not sit in the DOM behind the card. The approved .lockcontent shows
    // illustrative .act rows (heading, description, chips) instead.
    expect(document.body.textContent).not.toContain("Answer the top questions directly");
    // SIGV2-1211: the illustrative rows rate impact as a category. A figure
    // shown to a plan that cannot see the real list traces to nothing.
    expect(blurred.textContent).not.toContain("PTS");
    expect(blurred.textContent).toContain("Impact: High");
    expect(blurred.querySelectorAll("h3").length).toBe(3);
    expect(blurred).toHaveAttribute("aria-hidden", "true");
    expect(screen.getByRole("link", { name: /Upgrade to Standard/i })).toHaveAttribute(
      "href",
      "/dashboard/billing?section=plans&plan=plan_standard"
    );
  });

  it("labels the Improve list as audit findings, with its own count (SIGV2-1175)", async () => {
    // The Improve tab and the action plan read disjoint data sets; each names
    // its source and states its own count so the button can never again read
    // as the expanded version of this list.
    auditMock.current = {
      project: {
        latest_aeo_score: 82,
        latest_geo_score: 72,
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
      latestAudit: {
        id: 700,
        project_id: 42,
        url: "https://client.example",
        audit_type: "STANDARD",
        created_at: "2026-02-01T09:00:00.000Z",
        status: "completed",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://client.example", market: "us", language: "en" },
          scores: { aeo: 82, geo: 72 },
          aeo: { answerability_score: 82 },
          geo: { visibility_index: 72 },
          entities: [],
          competitors: [],
          metadata: {
            created_at: "2026-02-01T09:00:00.000Z",
            updated_at: "2026-02-01T09:00:00.000Z",
            search_types: [],
          },
          suggestions: [
            {
              category: "aeo",
              title: "Answer the top questions directly",
              action: "Add a short answer block above the fold.",
            },
            {
              category: "geo",
              title: "Name the brand consistently",
              action: "Use one spelling everywhere the site mentions itself.",
            },
          ],
        },
      },
    };

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
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

  it("rates Improve impact as a category, never as a predicted gain (SIGV2-1211)", async () => {
    auditMock.current = {
      project: {
        latest_aeo_score: 82,
        latest_geo_score: 72,
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
      latestAudit: {
        id: 700,
        project_id: 42,
        url: "https://client.example",
        audit_type: "STANDARD",
        created_at: "2026-02-01T09:00:00.000Z",
        status: "completed",
        full_report: {
          schema_version: "2026-03-09",
          site: { url: "https://client.example", market: "us", language: "en" },
          scores: {
            aeo: 82,
            geo: 72,
            aeo_breakdown: { penalties: [{ reason: "No answer-ready summary", impact: -12 }] },
          },
          aeo: { answerability_score: 82 },
          geo: { visibility_index: 72 },
          entities: [],
          competitors: [],
          metadata: {
            created_at: "2026-02-01T09:00:00.000Z",
            updated_at: "2026-02-01T09:00:00.000Z",
            search_types: [],
          },
          suggestions: [
            {
              category: "aeo",
              title: "Answer the top questions directly",
              action: "Add a short answer block above the fold.",
            },
          ],
        },
      },
    };

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    const panel = document.getElementById("signal-tabpanel-improve")!;
    // The penalty carries a measured deduction, so the band is real and the
    // row is rated. The deduction is not a promise of what a fix would gain,
    // so the number itself is never printed.
    expect(within(panel).getByText("Impact: High")).toBeInTheDocument();
    // The plain suggestion carries no numeric source at all, so it stays
    // unrated instead of defaulting to Medium.
    expect(within(panel).getByText("Impact: not rated")).toBeInTheDocument();
    expect(within(panel).queryByText("Impact: Medium")).toBeNull();
    expect(panel.textContent).not.toContain("PTS");
    expect(panel.textContent).not.toMatch(/\+\s?\d/);
    expect(panel.textContent).not.toMatch(/\d+\s*(pts?|points?)/i);
  });

  it("offers the approved Export menu and requests the aio report kind", async () => {
    // The approved control is `.exp-menu` (Signal AIO Detail.html:55 ->
    // mockup/app.js wireExport), not a one-shot button: Export opens a menu
    // headed "Export report" and the variant chosen drives the request.
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
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });

    const trigger = screen.getByRole("button", { name: /^Export$/i });
    expect(trigger).toHaveAttribute("aria-haspopup", "menu");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await act(async () => {
      fireEvent.click(trigger);
    });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Export report")).toBeInTheDocument();

    await act(async () => {
      fireEvent.click(screen.getByRole("menuitem", { name: /AIO report/ }));
    });

    await waitFor(() =>
      expect(reportMock.generateComplexReportPdf).toHaveBeenCalledWith(
        expect.objectContaining({
          audit_ids: [700],
          project_id: 42,
          report_options: expect.objectContaining({
            report_kind: "aio",
            report_type: "standard",
            branding_mode: "platform",
          }),
        }),
        expect.objectContaining({ Authorization: "Bearer token" })
      )
    );
  });

  it("only offers the report kinds this screen sells", async () => {
    // SIGV2-1255: every non-competitors screen offers the four report kinds.
    // The Competitors report belongs to the competitors screen.
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Export$/i }));
    });

    expect(screen.getAllByRole("menuitem")).toHaveLength(4);
    expect(screen.queryByRole("menuitem", { name: /Competitors report/ })).not.toBeInTheDocument();
  });

  it("locks a variant the plan does not include, and names the plan that unlocks it", async () => {
    // The lock comes from the backend entitlement answer, never from a
    // client-side plan table. No kind locks on a PDF-capable plan, so the
    // fixture answers the way it would if that ever changed.
    reportMock.fetchReportExportVariants.mockResolvedValue(
      exportVariantsResponse({ seo: { locked: true, required_plan_label: "Standard" } })
    );
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^Export$/i }));
    });

    const seo = screen.getByRole("menuitem", { name: "SEO report - Locked, Standard" });
    expect(seo).toHaveAttribute("aria-disabled", "true");
    await act(async () => {
      fireEvent.click(seo);
    });
    expect(reportMock.generateComplexReportPdf).not.toHaveBeenCalled();
  });

  it("does not describe an empty recommendation list as a clean bill of health", () => {
    render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );
    expect(screen.getByText("No priority actions are listed for this check.")).toBeInTheDocument();
    expect(screen.queryByText(/you're in good shape/i)).toBeNull();
  });

  it("keeps the prompts and engines tabs honest when the visibility feeds fail", async () => {
    visibilityMock.fetchVisibilitySummary.mockRejectedValue(new Error("boom"));
    visibilityMock.fetchVisibilityQueries.mockRejectedValue(new Error("boom"));

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    // The prompt list names its own failure rather than claiming emptiness.
    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/could not be read/i).length).toBeGreaterThan(0)
    );
    // The engines tab reads the summary feed and says so.
    fireEvent.click(screen.getByRole("tab", { name: /By engine/ }));
    await waitFor(() =>
      expect(screen.getAllByText(/could not be loaded/i).length).toBeGreaterThan(0)
    );
  });

  // ------------------------------------------------------------------
  // SIGV2-1142: Add prompt is a dialog on this tab. It used to navigate to a
  // monitoring page the approved MVP does not contain, where creation then
  // refused without saying why.
  // ------------------------------------------------------------------
  const ENTITLED = {
    plan: "plan_standard",
    plan_label: "Standard",
    upgrade_plan: "plan_specialist",
    upgrade_plan_label: "Specialist",
    upgrade_max_queries: 50,
    max_queries: 10,
    used_queries: 3,
    remaining_queries: 7,
    allowed_providers: ["openai", "anthropic"],
    is_locked: false,
    estimated_cost_per_check: { openai: 1, anthropic: 1 },
  };

  const openAddPrompt = async () => {
    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    const panel = within(document.getElementById("signal-tabpanel-prompts")!);
    // The prompt-setup surface loads its own list before its actions exist.
    await waitFor(() =>
      expect(panel.getByRole("button", { name: /Add your own/ })).toBeInTheDocument()
    );
    await act(async () => {
      fireEvent.click(panel.getByRole("button", { name: /Add your own/ }));
    });
    return screen.getByRole("dialog");
  };

  it("adds a prompt from the Prompts tab without leaving the page", async () => {
    const dialog = await openAddPrompt();
    expect(
      within(dialog).getByText("3 of 10 prompts used on Standard, 7 remaining.")
    ).toBeInTheDocument();

    fireEvent.change(within(dialog).getByPlaceholderText("best boutique hotels near the harbour"), {
      target: { value: "  quiet hotel with a late checkout  " },
    });

    // The refreshed list feed carries the new prompt; with no resolvable type
    // it lands under Pending classification.
    visibilityMock.fetchVisibilityQueries.mockResolvedValue({
      ...QUERY_LIST,
      entitlements: { ...QUERY_LIST.entitlements, used_queries: 4, remaining_queries: 6 },
      queries: [
        ...QUERY_LIST.queries,
        {
          id: 4,
          project_id: 42,
          query_text: "quiet hotel with a late checkout",
          query_type: "aeo",
          search_type: null,
          search_type_source: null,
          origin: "customer",
          is_generated: false,
          providers: ["openai"],
          is_active: true,
          created_at: null,
          updated_at: null,
        },
      ],
    });

    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add prompt" }));
    });

    expect(visibilityMock.createVisibilityQuery).toHaveBeenCalledTimes(1);
    const [projectArg, payload] = visibilityMock.createVisibilityQuery.mock.calls[0];
    expect(projectArg).toBe("42");
    expect(payload).toEqual({
      query_text: "quiet hotel with a late checkout",
      query_type: "aeo",
      providers: ["openai"],
    });

    // The dialog closes and the reloaded list shows the new prompt, pending.
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() =>
      expect(screen.getByText("quiet hotel with a late checkout")).toBeInTheDocument()
    );
  });

  it("disables adding once the plan's prompt allowance is spent", async () => {
    visibilityMock.fetchVisibilityQueries.mockResolvedValue({
      ...QUERY_LIST,
      entitlements: { ...QUERY_LIST.entitlements, used_queries: 10, remaining_queries: 0 },
    });

    await act(async () => {
      render(
        <PageHeaderHarness>
          <ProjectAeoPage />
        </PageHeaderHarness>
      );
    });
    fireEvent.click(screen.getByRole("tab", { name: /Prompts/ }));
    const panel = within(document.getElementById("signal-tabpanel-prompts")!);
    await waitFor(() =>
      expect(panel.getByRole("button", { name: /Add your own/ })).toBeInTheDocument()
    );

    // At the cap the surface refuses the add before the dialog can open, so
    // the modal's cap copy is never the thing a customer hits first.
    expect(panel.getByRole("button", { name: /Add your own/ })).toBeDisabled();
    fireEvent.click(panel.getByRole("button", { name: /Add your own/ }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(visibilityMock.createVisibilityQuery).not.toHaveBeenCalled();
  });

  it("shows the API's own refusal rather than failing silently", async () => {
    visibilityMock.fetchVisibilityQueries.mockResolvedValue({
      ...QUERY_LIST,
      entitlements: ENTITLED,
    });
    visibilityMock.createVisibilityQuery.mockRejectedValue(
      new Error(
        "Prompt limit reached: your Standard plan tracks 10 prompts, 10 are in use and 0 remain. Remove a prompt, or upgrade to Specialist to track 50."
      )
    );

    const dialog = await openAddPrompt();
    fireEvent.change(within(dialog).getByPlaceholderText("best boutique hotels near the harbour"), {
      target: { value: "one prompt too many" },
    });
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add prompt" }));
    });

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      within(screen.getByRole("dialog")).getByText(/Prompt limit reached: your Standard plan/)
    ).toBeInTheDocument();
  });

  it("asks for the prompt text instead of doing nothing when it is empty", async () => {
    visibilityMock.fetchVisibilityQueries.mockResolvedValue({
      ...QUERY_LIST,
      entitlements: ENTITLED,
    });

    const dialog = await openAddPrompt();
    await act(async () => {
      fireEvent.click(within(dialog).getByRole("button", { name: "Add prompt" }));
    });

    expect(
      within(dialog).getByText("Enter the prompt you want Signal to test.")
    ).toBeInTheDocument();
    expect(visibilityMock.createVisibilityQuery).not.toHaveBeenCalled();
  });

  it("announces load failures and retries through refetch", () => {
    const refetch = vi.fn();
    auditMock.current = {
      ...defaultAudit,
      error: "Network failed",
      latestAudit: null,
      refetch,
    };

    render(
      <PageHeaderHarness>
        <ProjectAeoPage />
      </PageHeaderHarness>
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Network failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});
