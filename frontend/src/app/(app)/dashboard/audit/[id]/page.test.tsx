import React from "react";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { render as rtlRender, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import "@/i18n";
import QueryProvider from "@/components/QueryProvider";
import { ProjectScopeContext } from "@/components/dashboard/projectScope";

// The page's tree uses react-query, and the app supplies the client from the
// root layout (app/layout.tsx). Rendering the page bare therefore threw
// "No QueryClient set" before anything could be asserted, so the real provider
// wraps it here too rather than a bespoke client that could drift from it.
const render = (ui: React.ReactElement) => rtlRender(<QueryProvider>{ui}</QueryProvider>);

// The project-scope context is supplied by the dashboard layout; here only the
// setter matters, so the page can be observed registering (or not registering)
// the project its audit belongs to.
const renderWithProjectScope = (setProjectId: (projectId: string | number | null) => void) =>
  rtlRender(
    <QueryProvider>
      <ProjectScopeContext.Provider value={{ projectId: null, setProjectId }}>
        <AuditDetailsPage />
      </ProjectScopeContext.Provider>
    </QueryProvider>
  );

const {
  pushMock,
  getTokenMock,
  useWorkspaceHistoryMock,
  scheduleAutomationMock,
  fetchClaimReviewSummaryMock,
  fetchVisibilitySummaryMock,
  useAuditComparisonMock,
  exportMenuMock,
} = vi.hoisted(() => ({
  pushMock: vi.fn(),
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
  useWorkspaceHistoryMock: vi.fn(),
  scheduleAutomationMock: vi.fn(),
  fetchClaimReviewSummaryMock: vi.fn(),
  fetchVisibilitySummaryMock: vi.fn(),
  useAuditComparisonMock: vi.fn(),
  exportMenuMock: vi.fn(),
}));

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useParams: () => ({ id: "123" }),
    useRouter: () => ({ push: pushMock }),
  };
});

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    getToken: getTokenMock,
    isSignedIn: true,
  }),
}));

vi.mock("@/hooks/useWorkspaceHistory", () => ({
  useWorkspaceHistory: (...args: unknown[]) => useWorkspaceHistoryMock(...args),
}));

vi.mock("@/contexts/RoleModeContext", () => ({
  useRoleMode: () => ({ roleMode: "specialist", setRoleMode: vi.fn() }),
}));

vi.mock("@/components/results/ScheduleAutomation", () => ({
  ScheduleAutomation: (props: unknown) => {
    scheduleAutomationMock(props);
    return <div data-testid="schedule-automation" />;
  },
}));

// The approved Export control has its own test for locks, keyboard and job
// states (SignalExportMenu.test.tsx). Here it only has to be the control the
// header renders, so it is stubbed the same way the scheduler is.
vi.mock("@/components/signal/SignalExportMenu", () => ({
  default: (props: unknown) => {
    exportMenuMock(props);
    return <div data-testid="export-menu" />;
  },
}));

vi.mock("@/components/ui/TabErrorBoundary", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/results/tabs/OverviewTab", () => ({
  default: () => <div>Overview detail</div>,
}));

vi.mock("@/components/results/tabs/SeoTab", () => ({
  default: () => <div>Search detail</div>,
}));

vi.mock("@/components/results/tabs/AeoTab", () => ({
  default: () => <div>AI answers detail</div>,
}));

vi.mock("@/components/results/tabs/GeoTab", () => ({
  default: () => <div>AI visibility detail</div>,
}));

vi.mock("@/components/results/tabs/TechnicalTab", () => ({
  default: () => <div>Technical detail</div>,
}));

vi.mock("@/components/results/tabs/EntitiesTab", () => ({
  default: () => <div>Entities detail</div>,
}));

vi.mock("@/components/results/tabs/CompetitorsTab", () => ({
  default: () => <div>Competitors detail</div>,
}));

vi.mock("@/components/results/tabs/HallucinationsTab", () => ({
  default: () => <div>Accuracy detail</div>,
}));

vi.mock("@/components/results/ClaimReviewQueue", () => ({
  default: () => <div>Claim review queue</div>,
}));

vi.mock("@/services/claimReviewService", () => ({
  fetchClaimReviewSummary: (...args: unknown[]) => fetchClaimReviewSummaryMock(...args),
}));

vi.mock("@/services/monitoringService", () => ({
  fetchVisibilitySummary: (...args: unknown[]) => fetchVisibilitySummaryMock(...args),
}));

vi.mock("@/hooks/useAuditComparison", () => ({
  useAuditComparison: (...args: unknown[]) => useAuditComparisonMock(...args),
}));

let AuditDetailsPage: React.ComponentType;

const baseHistory = () => ({
  reportLoading: false,
  reportError: null,
  selectedAuditId: 123,
  setSelectedAuditId: vi.fn(),
  activeReport: {
    schema_version: "canonical",
    url: "https://example.com",
    target: {
      type: "website",
      name: "Example",
      url: "https://example.com",
      metadata: {},
    },
    analysis: {},
    performance: {},
    network: {},
    warnings: [],
    metadata: {},
    seo: { onpage: 81 },
    aeo: { answerability_score: 66 },
    geo: { visibility_index: 72 },
    scores: { overall: 73, seo: 81, aeo: 66, geo: 72 },
    competitors: [],
    entities: [],
    technical_signals: {
      performance: { score: 79 },
      network: { supports_http2: true },
    },
    hallucination: null,
  },
  activeAuditMeta: {
    id: 123,
    url: "https://example.com",
    auditTargetType: "website",
    targetName: "Example",
    targetUrl: "https://example.com",
    targetMetadata: {},
    geoScore: 72,
    seoScore: 81,
    aeoScore: 66,
    status: "completed",
    auditType: "FAST",
    createdAt: "2026-03-05T10:00:00Z",
    projectId: 7,
  },
});

const comparisonWithPrevious = () => ({
  audit_id: 123,
  has_previous: true,
  previous_audit_id: 99,
  previous_audit_date: "2026-02-19T10:00:00Z",
  scores: {
    overall: { current: 73, previous: 69, delta: 4, direction: "up" as const },
    seo: { current: 81, previous: 79, delta: 2, direction: "up" as const },
    geo: { current: 72, previous: 70, delta: 2, direction: "up" as const },
    aeo: { current: 66, previous: 62, delta: 4, direction: "up" as const },
  },
  sub_components: {
    seo: {
      core_web_vitals: { current: 70, previous: 55, delta: 15, direction: "up" as const },
      technical_seo: { current: 68, previous: 68, delta: 0, direction: "stable" as const },
      // No customer-facing name: must not reach the screen.
      future_component: { current: 40, previous: 10, delta: 30, direction: "up" as const },
    },
    aeo: {
      snippet_formatting: { current: 45, previous: 52, delta: -7, direction: "down" as const },
    },
  },
  history: [],
});

// What the backend returns when the only earlier scan is not comparable (a
// different scan depth, or another project): the current scores, and nothing
// to compare them with. Stale previous/delta values are deliberately included
// to prove the screen reads has_previous and not the numbers beside it.
const comparisonWithoutComparableBaseline = () => ({
  audit_id: 123,
  has_previous: false,
  scores: {
    overall: { current: 73, previous: 67, delta: 6, direction: "up" as const },
    seo: { current: 81, previous: 75, delta: 6, direction: "up" as const },
    geo: { current: 72, previous: 66, delta: 6, direction: "up" as const },
    aeo: { current: 66, previous: 60, delta: 6, direction: "up" as const },
  },
  sub_components: {
    seo: {
      core_web_vitals: { current: 70, previous: 55, delta: 15, direction: "up" as const },
    },
  },
  history: [],
});

const visibilitySummary = (overrides: Record<string, unknown> = {}) => ({
  project_id: 7,
  entitlements: {
    plan: "specialist",
    max_queries: 10,
    used_queries: 2,
    remaining_queries: 8,
    allowed_providers: ["openai"],
    is_locked: false,
    estimated_cost_per_check: {},
  },
  queries_configured: 2,
  providers: ["openai"],
  visibility_score: 41,
  score_breakdown: null,
  trend_delta: 5,
  completed_checks: 4,
  pending_checks: 0,
  cited_checks: 2,
  total_checks: 4,
  last_updated_at: "2026-03-04T09:00:00Z",
  provider_breakdown: [],
  queries: [],
  ...overrides,
});

describe("AuditDetailsPage", () => {
  beforeAll(async () => {
    const pageModule = await import("@/app/(app)/dashboard/audit/[id]/page");
    AuditDetailsPage = pageModule.default;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    fetchClaimReviewSummaryMock.mockResolvedValue({
      audit_id: 123,
      total_flagged: 0,
      approved_count: 0,
      refused_count: 0,
      pending_count: 0,
      impact: {
        score_recalculated: false,
        export_excluded_claims: 0,
        note: "No review impact.",
      },
    });

    useWorkspaceHistoryMock.mockReturnValue(baseHistory());
    useAuditComparisonMock.mockReturnValue({ data: undefined });
    fetchVisibilitySummaryMock.mockRejectedValue(new Error("no monitoring"));
  });

  it("renders the report as one ordered page in the design's section order", async () => {
    render(<AuditDetailsPage />);

    const order = [
      "New scores",
      "Prioritised fixes",
      "Are you shown, and trusted, in AI answers?",
      "Are you ranking in traditional search?",
      "Turn fixes into action",
    ];

    const headings = order.map((title) => screen.getByRole("heading", { name: title }));
    for (let i = 1; i < headings.length; i += 1) {
      const relation = headings[i - 1].compareDocumentPosition(headings[i]);
      expect(relation & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
  });

  it("offers the approved four next steps, pointing at the sections on this page", async () => {
    render(<AuditDetailsPage />);

    expect(screen.getByRole("link", { name: "Open AIO detail" })).toHaveAttribute(
      "href",
      "#report-aio"
    );
    expect(screen.getByRole("link", { name: "Open SEO detail" })).toHaveAttribute(
      "href",
      "#report-seo"
    );
    expect(screen.getByRole("link", { name: "Review the fix plan" })).toHaveAttribute(
      "href",
      "#report-sec-fixes"
    );
    // SIGV2-1164: "Dashboard" is this report's own project dashboard, the
    // destination the approved design links it to, not the workspace overview.
    expect(screen.getByRole("link", { name: "Back to dashboard" })).toHaveAttribute(
      "href",
      "/dashboard/projects/7"
    );

    for (const [id, heading] of [
      ["report-aio", "Are you shown, and trusted, in AI answers?"],
      ["report-seo", "Are you ranking in traditional search?"],
      ["report-sec-fixes", "Prioritised fixes"],
    ] as const) {
      const target = document.getElementById(id);
      expect(target, `#${id} is missing`).not.toBeNull();
      expect(target).toContainElement(screen.getByRole("heading", { name: heading }));
    }
  });

  it("says there is nothing to compare against when the check has no predecessor", async () => {
    render(<AuditDetailsPage />);

    expect(
      screen.getByText(
        "This is the first scan we hold for this site, so there is nothing to compare it against yet."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What changed" })).not.toBeInTheDocument();
  });

  // SIGV2-1109. The backend only reports a baseline when it is comparable:
  // same site, same scan depth, same project. When it is not, the response
  // carries has_previous false and the screen must show no delta at all,
  // rather than a number produced against an incomparable run.
  it("shows no delta when the backend reports no comparable baseline", async () => {
    useAuditComparisonMock.mockReturnValue({ data: comparisonWithoutComparableBaseline() });

    render(<AuditDetailsPage />);

    expect(
      screen.getByText(
        "This is the first scan we hold for this site, so there is nothing to compare it against yet."
      )
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "What changed" })).not.toBeInTheDocument();
    expect(screen.queryByText(/^\+\d+$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^\u2212\d+$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/moved from/)).not.toBeInTheDocument();
  });

  it("names the previous scan and reports only score groups that really moved", async () => {
    useAuditComparisonMock.mockReturnValue({ data: comparisonWithPrevious() });

    render(<AuditDetailsPage />);

    expect(screen.getByText("Versus your previous scan on Feb 19, 2026.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What changed" })).toBeInTheDocument();
    expect(screen.getByText("Page speed and stability moved from 55 to 70.")).toBeInTheDocument();
    expect(screen.getByText("Snippet formatting moved from 52 to 45.")).toBeInTheDocument();
    // A one-point-or-less move is "stable" to the backend, so it is not a change.
    expect(screen.queryByText(/Technical setup moved/)).not.toBeInTheDocument();
    // An unmapped component key never prints its machine name.
    expect(screen.queryByText(/future_component/)).not.toBeInTheDocument();
  });

  it("never renders an AI visibility figure without a completed monitoring run", async () => {
    fetchVisibilitySummaryMock.mockResolvedValue(
      visibilitySummary({ completed_checks: 0, visibility_score: null })
    );

    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchVisibilitySummaryMock).toHaveBeenCalled());

    expect(screen.queryByText("AI visibility")).not.toBeInTheDocument();
  });

  it("renders the AI visibility figure, naming monitoring as its source, once measured", async () => {
    fetchVisibilitySummaryMock.mockResolvedValue(visibilitySummary());

    render(<AuditDetailsPage />);

    expect(await screen.findByText("AI visibility")).toBeInTheDocument();

    // SIGV2-1295: the caption says what the score means, the same job its two
    // neighbours do. The provenance it used to carry inline, 80 characters in
    // a 22ch column, wrapped to four lines and lifted the scores beside it;
    // it is now the content of a tooltip rather than body text.
    expect(screen.getByText("Visibility across the prompts you track")).toBeInTheDocument();
    expect(screen.queryByText(/not by this scan/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Where this score comes from")).toBeInTheDocument();
  });

  it("keeps every capability reachable behind disclosures", async () => {
    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(screen.getByText("AI answers detail")).toBeInTheDocument();
    expect(screen.getByText("AI visibility detail")).toBeInTheDocument();
    expect(screen.getByText("Competitors detail")).toBeInTheDocument();
    expect(screen.getByText("Entities detail")).toBeInTheDocument();
    expect(screen.getByText("Accuracy detail")).toBeInTheDocument();
    expect(screen.getByText("Search detail")).toBeInTheDocument();
    expect(screen.getByText("Technical detail")).toBeInTheDocument();
    expect(screen.getByText("Overview detail")).toBeInTheDocument();
  });

  it("exports through the approved header control, not an invented page section", async () => {
    // SIGV2-1124: the page used to carry an "Export this report" disclosure
    // with "PDF or JSON, to share or keep". Neither string, nor the heading
    // above them, appears anywhere in the 24 approved MVP mockups, so the
    // section was removed and the approved `.exp-menu` put in the header.
    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(screen.getByTestId("export-menu")).toBeInTheDocument();
    expect(exportMenuMock).toHaveBeenCalledWith(
      expect.objectContaining({ page: "report", reportKind: "standard" })
    );

    expect(screen.queryByText("Export this report")).not.toBeInTheDocument();
    expect(screen.queryByText("PDF or JSON, to share or keep")).not.toBeInTheDocument();
    expect(screen.queryByText("Generate PDF report")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Download JSON/i })).not.toBeInTheDocument();
  });

  it("builds the header export from the audit being viewed", async () => {
    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(exportMenuMock).toHaveBeenCalledWith(expect.objectContaining({ auditId: 123 }));
  });

  it("keeps the recurring audits bar visible in the header", async () => {
    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(scheduleAutomationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "compact",
        compactLockedMode: "strip",
        className: "min-w-0 w-full flex-1",
      })
    );
  });

  it("passes canonical provider and tier metadata into scheduler audit params", async () => {
    const history = baseHistory();
    history.activeReport.metadata = {
      billing_provider: "anthropic",
      provider: "gpt-5",
      requested_tier: "deep_judgment",
      selected_models: ["openai", "anthropic"],
    };
    history.activeAuditMeta.auditType = "DEEP";
    useWorkspaceHistoryMock.mockReturnValue(history);

    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(scheduleAutomationMock).toHaveBeenCalledWith(
      expect.objectContaining({
        auditParams: expect.objectContaining({
          provider: "anthropic",
          tier: "deep_judgment",
          selected_models: ["openai", "anthropic"],
        }),
      })
    );
  });

  it("shows the claims review section when the audit has manual review claims", async () => {
    fetchClaimReviewSummaryMock.mockResolvedValue({
      audit_id: 123,
      total_flagged: 2,
      approved_count: 0,
      refused_count: 0,
      pending_count: 2,
      impact: {
        score_recalculated: false,
        export_excluded_claims: 0,
        note: "Pending manual review.",
      },
    });

    render(<AuditDetailsPage />);

    expect(await screen.findByRole("button", { name: /Claims to review/i })).toBeInTheDocument();
  });

  it("routes from the report to the project's full action plan", async () => {
    const history = baseHistory();
    useWorkspaceHistoryMock.mockReturnValue({
      ...history,
      activeAuditMeta: { ...history.activeAuditMeta, projectId: 7 },
    });

    render(<AuditDetailsPage />);

    expect(await screen.findByRole("link", { name: "Full action plan" })).toHaveAttribute(
      "href",
      "/dashboard/projects/7/fixes"
    );
  });

  it("omits the action plan link when the audit belongs to no project", async () => {
    // A guest or orphaned audit has no plan page, so the control is absent
    // rather than pointing at a project route that cannot resolve. With the
    // invented export block gone (SIGV2-1124) that leaves the whole section
    // with nothing in it, so it is not rendered as an empty frame either.
    const history = baseHistory();
    useWorkspaceHistoryMock.mockReturnValue({
      ...history,
      activeAuditMeta: { ...history.activeAuditMeta, projectId: undefined },
    });

    render(<AuditDetailsPage />);
    await waitFor(() => expect(fetchClaimReviewSummaryMock).toHaveBeenCalled());

    expect(screen.queryByRole("link", { name: "Full action plan" })).not.toBeInTheDocument();
    expect(screen.queryByText("Turn fixes into action")).not.toBeInTheDocument();
  });

  it("keeps the claim review queue reachable with no project behind the audit", async () => {
    // "Claims to review" has no approved home anywhere in the MVP design, so
    // it must stay reachable while that is settled with the stakeholder. The
    // surviving wrapper is the one it already had.
    fetchClaimReviewSummaryMock.mockResolvedValue({
      audit_id: 123,
      total_flagged: 2,
      approved_count: 0,
      refused_count: 0,
      pending_count: 2,
      impact: {
        score_recalculated: false,
        export_excluded_claims: 0,
        note: "Pending manual review.",
      },
    });
    const history = baseHistory();
    useWorkspaceHistoryMock.mockReturnValue({
      ...history,
      activeAuditMeta: { ...history.activeAuditMeta, projectId: undefined },
    });

    render(<AuditDetailsPage />);

    expect(await screen.findByRole("button", { name: /Claims to review/i })).toBeInTheDocument();
    expect(screen.getByText("Turn fixes into action")).toBeInTheDocument();
  });

  // SIGV2-1180: a report opened from a project's history is still that
  // project's view. Its URL names no project, so the page itself registers the
  // one the audit record returns and the layout keeps the project menu.
  it("registers the audit's own project as the sidebar scope", async () => {
    const setProjectId = vi.fn();
    renderWithProjectScope(setProjectId);

    await waitFor(() => expect(setProjectId).toHaveBeenCalledWith(7));
  });

  it("registers no project scope when the audit belongs to none", async () => {
    const history = baseHistory();
    useWorkspaceHistoryMock.mockReturnValue({
      ...history,
      activeAuditMeta: { ...history.activeAuditMeta, projectId: undefined },
    });
    const setProjectId = vi.fn();
    renderWithProjectScope(setProjectId);

    await waitFor(() => expect(setProjectId).toHaveBeenCalledWith(null));
    expect(setProjectId).not.toHaveBeenCalledWith(7);
  });
});

describe("customer-facing copy", () => {
  const reportDir = path.join(__dirname, "report");
  const sources = [
    path.join(__dirname, "page.tsx"),
    ...readdirSync(reportDir)
      .filter((file) => file.endsWith(".tsx"))
      .map((file) => path.join(reportDir, file)),
  ];

  it("never shows AEO or GEO jargon on the screen", () => {
    for (const source of sources) {
      const text = readFileSync(source, "utf-8");
      // SIGV2-1317: comments go first.
      //
      // This guard is about what a customer reads, and it was scanning the
      // whole file, so it failed on a comment explaining why the jargon had
      // been removed. That is the opposite of what it is for: the note that
      // records the decision is exactly the note you want to keep, and a
      // guard that forbids naming the thing it guards against makes the
      // reasoning unwritable.
      //
      // Rendered strings are still covered, which is the point.
      const withoutComments = text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|\s)\/\/.*$/gm, "");
      // Strip identifiers that legitimately name the underlying engine data
      // (tab components, payload fields) but must never reach a customer.
      const stripped = withoutComments
        .replace(/aeo[A-Z]\w*/g, "")
        .replace(/geo[A-Z]\w*/g, "")
        .replace(/Aeo\w*/g, "")
        .replace(/Geo\w*/g, "")
        .replace(/includes\("(AEO|GEO|SEO)"\)/g, "")
        .replace(/report-sec-\w+/g, "");
      expect(stripped, `${source} leaks AEO/GEO to customers`).not.toMatch(/\bAEO\b|\bGEO\b/);
    }
  });

  it("has matching English and Arabic copy for every report key", async () => {
    const en = JSON.parse(
      readFileSync(path.join(__dirname, "../../../../../i18n/en.json"), "utf-8")
    );
    const ar = JSON.parse(
      readFileSync(path.join(__dirname, "../../../../../i18n/ar.json"), "utf-8")
    );

    const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;
    const flatten = (obj: Record<string, unknown>, prefix = ""): string[] =>
      Object.entries(obj).flatMap(([key, value]) =>
        typeof value === "object" && value !== null
          ? flatten(value as Record<string, unknown>, `${prefix}${key}.`)
          : [`${prefix}${key.replace(PLURAL_SUFFIX, "")}`]
      );

    expect([...new Set(flatten(ar.signalAuditReport))].sort()).toEqual(
      [...new Set(flatten(en.signalAuditReport))].sort()
    );
  });
});
