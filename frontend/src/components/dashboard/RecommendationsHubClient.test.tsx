import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectRecommendationsPage from "@/app/(app)/dashboard/projects/[projectId]/fixes/page";
import RecommendationsHubClient from "@/components/dashboard/RecommendationsHubClient";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import {
  createProjectTask,
  fetchProjectTasks,
  updateProjectTask,
} from "@/services/workspaceService";
import { tEn } from "@/test/i18nEn";

const push = vi.fn();
const getToken = vi.fn(async () => "token-123");

const fixtures = vi.hoisted(() => ({
  recommendations: [] as Array<{
    title: string;
    description: string;
    category: string;
    impact: string;
    engines: string[];
  }>,
  diagnostics: { degraded: false, summary: "", issues: [] as string[] },
  annotationTargets: [] as Array<{
    sectionPath: string;
    sourceRecommendationKey: string | null;
    title: string;
    description: string;
    category: string;
  }>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));
vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
  useRouter: () => ({ push }),
}));
vi.mock("@/hooks/useProjectLatestAudit", () => ({ useProjectLatestAudit: vi.fn() }));
vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ isSignedIn: true, getToken }),
}));
vi.mock("@/lib/reportAdapters", () => ({
  // SIGV2-1193: the hub reads the one consolidated list, and every row of it
  // carries the channel that raised it. The fixtures below only vary the
  // fields each case is about, so the provenance is supplied here.
  getConsolidatedFixes: () =>
    fixtures.recommendations.map((rec) => ({ sources: ["audit_finding"], ...rec })),
  filterBrandOnlyRecommendations: (items: unknown) => items,
}));
vi.mock("@/lib/auditWorkspaceUtils", () => ({
  normalizeReportWithDiagnostics: (report: unknown) => ({
    report,
    diagnostics: fixtures.diagnostics,
  }),
}));
vi.mock("@/lib/integrityStatus", () => ({ getIntegrityStatusSnapshot: () => null }));
vi.mock("@/lib/projectAuditFeature", () => ({
  buildAuditRecordResponse: (audit: unknown) => audit,
}));
vi.mock("@/lib/auditAnnotationTargets", () => ({
  extractAuditAnnotationTargets: () => fixtures.annotationTargets,
}));
vi.mock("@/services/annotationService", () => ({
  fetchAuditAnnotations: vi.fn(async () => ({
    items: [],
    page: 1,
    per_page: 100,
    total: 0,
    has_more: false,
  })),
}));
vi.mock("@/hooks/useJiraExportTracker", () => ({
  useJiraExportTracker: () => ({ getTrackedExport: () => null, markExported: vi.fn() }),
}));
vi.mock("@/components/dashboard/AuditAnnotationThread", () => ({
  default: () => <div data-testid="annotation-thread" />,
}));
vi.mock("@/services/workspaceService", () => ({
  fetchProjectTasks: vi.fn(),
  createProjectTask: vi.fn(),
  updateProjectTask: vi.fn(),
}));

let currentBoard: Record<string, unknown> = {};

function makeTask(overrides: Record<string, unknown> = {}) {
  return {
    id: 900,
    project_id: 42,
    title: "Fix alpha",
    description: "First source item.",
    status: "todo",
    priority: "medium",
    origin: "audit_recommendation",
    category: "SEO",
    source_audit_id: 501,
    source_recommendation_key: null,
    assigned_to_user_id: null,
    assignee: null,
    due_date: null,
    resolved_at: null,
    verified_at: null,
    verification_audit_id: null,
    resolution_source: null,
    sort_order: 0,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function makeBoard(tasks: Array<Record<string, unknown>> = []) {
  return {
    project_id: 42,
    workspace_id: 7,
    can_edit: true,
    latest_audit_id: 501,
    latest_audit_at: "2026-01-10T00:00:00Z",
    assignees: [],
    summary: { total: tasks.length, done: 0, in_progress: 0, todo: tasks.length },
    tasks,
  };
}

const alphaKey = "seo:fix-alpha:aaaa1111bbbb";

const sixRecommendations = [
  {
    title: "Fix alpha",
    description: "First source item.",
    category: "SEO",
    impact: "Strategic",
    engines: ["SEO"],
  },
  {
    title: "Fix beta",
    description: "Second source item.",
    category: "AEO",
    impact: "Strategic",
    engines: ["AEO"],
  },
  {
    title: "Fix gamma",
    description: "Third source item.",
    category: "GEO",
    impact: "Strategic",
    engines: ["GEO"],
  },
  {
    title: "Fix delta",
    description: "Fourth source item.",
    category: "Technical SEO",
    impact: "Critical",
    engines: ["SEO"],
  },
  {
    title: "Fix epsilon",
    description: "Fifth source item.",
    category: "AEO",
    impact: "Strategic",
    engines: ["AEO"],
  },
  {
    title: "Fix zeta",
    description: "Sixth source item.",
    category: "GEO",
    impact: "Strategic",
    engines: ["GEO"],
  },
];

function mockAudit() {
  vi.mocked(useProjectLatestAudit).mockReturnValue({
    latestAudit: {
      id: 501,
      url: "https://example.com",
      full_report: { prioritized_actions: fixtures.recommendations },
    },
    loading: false,
  } as never);
}

async function renderClient() {
  let utils: ReturnType<typeof render> | undefined;
  await act(async () => {
    utils = render(<RecommendationsHubClient projectId="42" />);
  });
  return utils!;
}

function visibleCardTitles() {
  return screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
}

describe("RecommendationsHubClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fixtures.recommendations = sixRecommendations.map((item) => ({ ...item }));
    fixtures.diagnostics = { degraded: false, summary: "", issues: [] };
    fixtures.annotationTargets = [
      {
        sectionPath: "prioritized_actions[0]",
        sourceRecommendationKey: null,
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
      },
    ];
    mockAudit();
    currentBoard = makeBoard();
    vi.mocked(fetchProjectTasks).mockImplementation(async () => currentBoard as never);
    vi.mocked(updateProjectTask).mockImplementation(async (_projectId, taskId, payload) => {
      const tasks = (currentBoard.tasks as Array<Record<string, unknown>>).map((task) =>
        task.id === taskId ? { ...task, ...(payload as object) } : task
      );
      currentBoard = { ...currentBoard, tasks };
      return tasks.find((task) => task.id === taskId) as never;
    });
    vi.mocked(createProjectTask).mockImplementation(async (_projectId, payload) => {
      const created = makeTask({
        id: 991,
        ...(payload as object),
        resolved_at: "2026-01-12T00:00:00Z",
      });
      currentBoard = {
        ...currentBoard,
        tasks: [...(currentBoard.tasks as Array<Record<string, unknown>>), created],
      };
      return created as never;
    });
  });

  it("renders the fixes page heading through the client route", async () => {
    await act(async () => {
      render(<ProjectRecommendationsPage />);
    });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Your action plan" })
    ).toBeInTheDocument();
    expect(screen.queryByText("Hub")).not.toBeInTheDocument();
    // The approved subtitle literally says "ranked by impact per effort".
    expect(screen.getByText(/ranked by impact and effort/i)).toBeInTheDocument();
  });

  it("uses the approved filters and exposes pressed state", async () => {
    await renderClient();
    expect(screen.getByText("Show fixes for")).toBeInTheDocument();
    const all = screen.getByRole("button", { name: "All fixes" });
    const google = screen.getByRole("button", { name: "Google" });
    const answers = screen.getByRole("button", { name: "AI answers" });
    const visibility = screen.getByRole("button", { name: "AI visibility" });
    for (const button of [all, google, answers, visibility])
      expect(button).toHaveAttribute("type", "button");
    expect(all).toHaveAttribute("aria-pressed", "true");
    expect(google).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(answers);
    expect(answers).toHaveAttribute("aria-pressed", "true");
    expect(all).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix beta", "Fix epsilon"]));
    fireEvent.click(visibility);
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix gamma", "Fix zeta"]));
    fireEvent.click(google);
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix alpha", "Fix delta"]));
  });

  it("uses readable foregrounds on the tinted category and guidance surfaces", async () => {
    await renderClient();
    expect(screen.getByText("Google", { selector: "div" })).toHaveClass("text-(--t-1)");
    for (const badge of screen.getAllByText("AI answers", { selector: "div" })) {
      expect(badge).toHaveClass("text-(--primary-hover)");
    }
  });

  it("pages five cards at a time in unchanged source order", async () => {
    await renderClient();
    expect(visibleCardTitles()).toEqual([
      "Fix alpha",
      "Fix beta",
      "Fix gamma",
      "Fix delta",
      "Fix epsilon",
    ]);
    expect(screen.getByRole("button", { name: "Previous fixes" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Next fixes" }));
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix zeta"]));
    expect(screen.getByRole("button", { name: "Previous fixes" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Next fixes" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Previous fixes" }));
    await waitFor(() => expect(visibleCardTitles()[0]).toBe("Fix alpha"));
  });

  it("resets to the first page when the filter changes", async () => {
    await renderClient();
    fireEvent.click(screen.getByRole("button", { name: "Next fixes" }));
    await screen.findByRole("heading", { level: 2, name: "Fix zeta" });
    fireEvent.click(screen.getByRole("button", { name: "AI answers" }));
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix beta", "Fix epsilon"]));
    expect(screen.getByRole("button", { name: "Previous fixes" })).toBeDisabled();
  });

  it("clamps the visible page when the recommendation list shrinks", async () => {
    const utils = await renderClient();
    fireEvent.click(screen.getByRole("button", { name: "Next fixes" }));
    await screen.findByRole("heading", { level: 2, name: "Fix zeta" });
    fixtures.recommendations = [fixtures.recommendations[0]];
    mockAudit();
    await act(async () => {
      utils.rerender(<RecommendationsHubClient projectId="42" />);
    });
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix alpha"]));
    expect(screen.getByRole("button", { name: "Next fixes" })).toBeDisabled();
  });

  it("explains a filtered empty result without claiming completion", async () => {
    fixtures.recommendations = [fixtures.recommendations[1]];
    mockAudit();
    await renderClient();
    fireEvent.click(screen.getByRole("button", { name: "AI visibility" }));
    expect(await screen.findByText("No fixes match this filter.")).toBeInTheDocument();
    expect(screen.queryByText(/complete|done|healthy/i)).not.toBeInTheDocument();
  });

  it("keeps loading copy factual", async () => {
    vi.mocked(useProjectLatestAudit).mockReturnValue({ latestAudit: null, loading: true } as never);
    await renderClient();
    expect(screen.getByText("Loading recommended fixes...")).toBeInTheDocument();
    expect(screen.queryByText(/ranked|completed/i)).not.toBeInTheDocument();
  });

  it("preserves the project when beginning the initial assessment", async () => {
    vi.mocked(useProjectLatestAudit).mockReturnValue({
      latestAudit: null,
      loading: false,
    } as never);
    await renderClient();
    expect(screen.getByText("Check your website first")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Check your website" }));
    expect(push).toHaveBeenCalledWith("/dashboard/audit?projectId=42");
  });

  it("exposes diagnostics expansion state", async () => {
    fixtures.diagnostics = {
      degraded: true,
      summary: "Some report fields could not be read.",
      issues: ["Missing evidence", "Mismatched score"],
    };
    await renderClient();
    const toggle = screen.getByRole("button", { name: /review 2 details/i });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveClass("text-(--warn)");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Missing evidence/)).toBeInTheDocument();
  });

  it("seeds the filter from initialFilter", async () => {
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="seo" />);
    });
    expect(screen.getByRole("button", { name: "Google" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "All fixes" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix alpha", "Fix delta"]));
  });

  it("hides the filter row entirely when lockFilter is set", async () => {
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="seo" lockFilter />);
    });
    expect(screen.queryByRole("group", { name: "Fix filters" })).toBeNull();
    expect(screen.queryByText("Show fixes for")).toBeNull();
    await waitFor(() => expect(visibleCardTitles()).toEqual(["Fix alpha", "Fix delta"]));
  });

  it("keeps the default filter row and All fixes state without the new props", async () => {
    await renderClient();
    expect(screen.getByRole("group", { name: "Fix filters" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All fixes" })).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  });

  it("names only the other pillars a fix also helps, never the viewed one", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO"],
      },
      {
        title: "Fix beta",
        description: "Second source item.",
        category: "AEO",
        impact: "Strategic",
        engines: ["AEO"],
      },
    ];
    mockAudit();
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="seo" />);
    });
    expect(await screen.findByText("Also helps AI answers")).toBeInTheDocument();
    expect(screen.queryByText(/Also helps Google/)).toBeNull();
    expect(screen.getAllByText(/^Also helps /)).toHaveLength(1);
  });

  it("names Google when the same fix is viewed under AI answers", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO"],
      },
    ];
    mockAudit();
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="aeo" />);
    });
    expect(await screen.findByText("Also helps Google")).toBeInTheDocument();
  });

  it("produces the same marker regardless of engines array order", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
        impact: "Strategic",
        engines: ["AEO", "SEO"],
      },
    ];
    mockAudit();
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="seo" />);
    });
    expect(await screen.findByText("Also helps AI answers")).toBeInTheDocument();
  });

  it("states the full pillar list when no single pillar is being viewed", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO"],
      },
    ];
    mockAudit();
    await renderClient();
    expect(await screen.findByText("Helps Google and AI answers")).toBeInTheDocument();
    expect(screen.queryByText(/^Also helps /)).toBeNull();
  });

  it("joins the pillar list with commas for three and 'and' for two", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "Three pillars.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO", "GEO"],
      },
      {
        title: "Fix beta",
        description: "Two pillars.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO"],
      },
      {
        title: "Fix gamma",
        description: "One extra pillar.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "GEO"],
      },
    ];
    mockAudit();
    await renderClient();

    expect(
      await screen.findByText("Helps Google, AI answers and AI visibility")
    ).toBeInTheDocument();
    expect(screen.getByText("Helps Google and AI answers")).toBeInTheDocument();
    expect(screen.getByText("Helps Google and AI visibility")).toBeInTheDocument();
    expect(screen.queryByText(/and AI answers and/)).toBeNull();
  });

  it("joins a single extra pillar without a comma", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "Two pillars, one viewed.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO", "AEO", "GEO"],
      },
    ];
    mockAudit();
    await act(async () => {
      render(<RecommendationsHubClient projectId="42" initialFilter="seo" />);
    });
    expect(await screen.findByText("Also helps AI answers and AI visibility")).toBeInTheDocument();
  });

  it("shows no marker for a single-pillar recommendation", async () => {
    fixtures.recommendations = [
      {
        title: "Fix alpha",
        description: "First source item.",
        category: "SEO",
        impact: "Strategic",
        engines: ["SEO"],
      },
    ];
    mockAudit();
    await renderClient();
    expect(screen.queryByText(/Also helps |^Helps /)).toBeNull();
  });

  it("exposes discussion expansion state and keeps card actions", async () => {
    await renderClient();
    const discussion = screen.getByRole("button", { name: "Discuss" });
    expect(discussion).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(discussion);
    expect(discussion).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByTestId("annotation-thread")).toBeInTheDocument();
    expect(screen.queryAllByRole("button", { name: "Get guidance" })).toHaveLength(0);
    fireEvent.click(screen.getAllByRole("button", { name: "Open report" })[0]);
    expect(push).toHaveBeenCalledWith("/dashboard/audit/501");
  });

  it("updates the existing task when ticking a fix, never creating a duplicate", async () => {
    currentBoard = makeBoard([makeTask({ id: 900, source_recommendation_key: alphaKey })]);
    await renderClient();
    const tick = screen.getByRole("checkbox", { name: "Mark done: Fix alpha" });
    expect(tick).not.toBeChecked();
    await act(async () => {
      fireEvent.click(tick);
    });
    await waitFor(() =>
      expect(updateProjectTask).toHaveBeenCalledWith(
        "42",
        900,
        { status: "done" },
        { Authorization: "Bearer token-123" }
      )
    );
    expect(createProjectTask).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByRole("heading", { level: 2, name: "Fix alpha" })).toBeNull()
    );
    const doneSection = await screen.findByRole("heading", { name: "Done" });
    expect(doneSection).toBeInTheDocument();
    expect(
      screen.getByText("You marked this done. No check has confirmed it yet.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/no longer finds this problem/i)).toBeNull();
  });

  it("disables the tick with an explanation when no task matches a fix", async () => {
    await renderClient();
    const tick = screen.getByRole("checkbox", { name: "Mark done: Fix alpha" });
    expect(tick).toBeDisabled();
    expect(
      screen.getAllByText("You can mark this done after the next check.").length
    ).toBeGreaterThan(0);
    await act(async () => {
      fireEvent.click(tick);
    });
    expect(updateProjectTask).not.toHaveBeenCalled();
    expect(createProjectTask).not.toHaveBeenCalled();
    expect(screen.queryByRole("heading", { name: "Done" })).toBeNull();
  });

  it("disables the tick when two tasks match a fix ambiguously", async () => {
    currentBoard = makeBoard([makeTask({ id: 900 }), makeTask({ id: 901 })]);
    await renderClient();
    const tick = screen.getByRole("checkbox", { name: "Mark done: Fix alpha" });
    expect(tick).toBeDisabled();
    await act(async () => {
      fireEvent.click(tick);
    });
    expect(updateProjectTask).not.toHaveBeenCalled();
  });

  it("matches the task whose category agrees when titles collide", async () => {
    currentBoard = makeBoard([
      makeTask({ id: 900, category: "SEO" }),
      makeTask({ id: 901, category: "AEO" }),
    ]);
    await renderClient();
    const tick = screen.getByRole("checkbox", { name: "Mark done: Fix alpha" });
    expect(tick).toBeEnabled();
    await act(async () => {
      fireEvent.click(tick);
    });
    await waitFor(() =>
      expect(updateProjectTask).toHaveBeenCalledWith(
        "42",
        900,
        { status: "done" },
        expect.anything()
      )
    );
  });

  it("reverts the tick and reports the failure when the request fails", async () => {
    currentBoard = makeBoard([makeTask({ id: 900, source_recommendation_key: alphaKey })]);
    vi.mocked(updateProjectTask).mockRejectedValueOnce(new Error("network"));
    await renderClient();
    const tick = screen.getByRole("checkbox", { name: "Mark done: Fix alpha" });
    await act(async () => {
      fireEvent.click(tick);
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That change could not be saved. Try again."
    );
    expect(screen.getByRole("heading", { level: 2, name: "Fix alpha" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Done" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Mark done: Fix alpha" })).not.toBeChecked();
  });

  it("refills the active list to five after a completion", async () => {
    currentBoard = makeBoard([
      makeTask({
        id: 900,
        source_recommendation_key: alphaKey,
        status: "done",
        resolved_at: "2026-01-12T00:00:00Z",
        resolution_source: "manual",
      }),
    ]);
    await renderClient();
    await waitFor(() =>
      expect(visibleCardTitles()).toEqual([
        "Fix beta",
        "Fix gamma",
        "Fix delta",
        "Fix epsilon",
        "Fix zeta",
      ])
    );
    expect(screen.getByRole("heading", { name: "Done" })).toBeInTheDocument();
  });

  it("says the check confirmed a fix only when the task is validated", async () => {
    currentBoard = makeBoard([
      makeTask({
        id: 910,
        title: "Fix no longer listed",
        source_recommendation_key: "seo:fix-no-longer-listed:abc123def456",
        status: "done",
        resolved_at: "2026-01-11T00:00:00Z",
        verified_at: "2026-01-12T00:00:00Z",
        resolution_source: "audit_validated",
      }),
    ]);
    await renderClient();
    expect(
      await screen.findByText("The latest check no longer finds this problem.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/You marked this done/)).toBeNull();
  });

  it("says the latest check still sees a manually completed fix the check still lists", async () => {
    currentBoard = makeBoard([
      makeTask({
        id: 900,
        source_recommendation_key: alphaKey,
        status: "done",
        resolved_at: "2026-01-05T00:00:00Z",
        resolution_source: "manual",
      }),
    ]);
    await renderClient();
    expect(
      await screen.findByText("You marked this done. The latest check still sees this problem.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/no longer finds this problem/i)).toBeNull();
  });

  it("moves a fix back when undone, distinct from check confirmation", async () => {
    currentBoard = makeBoard([
      makeTask({
        id: 900,
        source_recommendation_key: alphaKey,
        status: "done",
        resolved_at: "2026-01-12T00:00:00Z",
        resolution_source: "manual",
      }),
    ]);
    await renderClient();
    const undo = await screen.findByRole("button", { name: "Move back to fixes" });
    await act(async () => {
      fireEvent.click(undo);
    });
    await waitFor(() =>
      expect(updateProjectTask).toHaveBeenCalledWith(
        "42",
        900,
        { status: "todo" },
        { Authorization: "Bearer token-123" }
      )
    );
    await waitFor(() =>
      expect(screen.getByRole("heading", { level: 2, name: "Fix alpha" })).toBeInTheDocument()
    );
    expect(screen.queryByText(/no longer finds this problem/i)).toBeNull();
  });

  it("reports a board load failure with a retry instead of hiding progress", async () => {
    vi.mocked(fetchProjectTasks).mockRejectedValueOnce(new Error("down"));
    await renderClient();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Your progress could not be loaded.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
