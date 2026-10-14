import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectFixesPage from "@/app/(app)/dashboard/projects/[projectId]/fixes/page";
import { ADVISOR_PLAN_ALLOWED, ADVISOR_PLAN_LOCKED } from "@/test/advisorPlanAccessFixtures";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
  Trans: ({ i18nKey, values }: { i18nKey: string; values?: Record<string, unknown> }) =>
    React.createElement(React.Fragment, null, tEn(i18nKey, values)),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
}));

vi.mock("@/types/auditResult", () => ({
  isAuditResult: () => true,
}));

const tasksMock = vi.hoisted(() => ({
  fetchProjectTasks: vi.fn(),
  createProjectTask: vi.fn(),
  updateProjectTask: vi.fn(),
}));

const decisionsMock = vi.hoisted(() => ({
  fetchRecommendationDecisions: vi.fn(),
  recordRecommendationDecision: vi.fn(),
}));

const authMock = vi.hoisted(() => ({
  getToken: vi.fn(async () => "token"),
  user: { subscription_plan: "plan_standard" } as Record<string, unknown> | null,
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: authMock.getToken, isSignedIn: true, user: authMock.user }),
}));

vi.mock("@/services/workspaceService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/workspaceService")>();
  return {
    ...actual,
    fetchProjectTasks: (...args: unknown[]) => tasksMock.fetchProjectTasks(...args),
    createProjectTask: (...args: unknown[]) => tasksMock.createProjectTask(...args),
    updateProjectTask: (...args: unknown[]) => tasksMock.updateProjectTask(...args),
  };
});

vi.mock("@/services/learningsService", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/learningsService")>();
  return {
    ...actual,
    fetchRecommendationDecisions: (...args: unknown[]) =>
      decisionsMock.fetchRecommendationDecisions(...args),
    recordRecommendationDecision: (...args: unknown[]) =>
      decisionsMock.recordRecommendationDecision(...args),
  };
});

vi.mock("@/components/app/WorkspaceSwitcher", () => ({
  workspaceHeaders: () => ({}),
}));

const makeTask = (overrides: Record<string, unknown> = {}) => ({
  id: 1,
  project_id: 42,
  title: "Resolve robots rules and sitemap gaps.",
  description: null,
  status: "in_progress",
  priority: "medium",
  origin: "audit_recommendation",
  category: "Technical",
  source_audit_id: 700,
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
});

const BOARD = {
  project_id: 42,
  workspace_id: 1,
  can_edit: true,
  latest_audit_id: 700,
  latest_audit_at: null,
  assignees: [],
  summary: {},
  tasks: [
    makeTask(),
    makeTask({
      id: 2,
      title: "Add FAQ schema to the location page",
      status: "done",
      resolved_at: "2026-09-20T10:00:00.000Z",
      resolution_source: "manual",
    }),
  ],
};

const auditMock = vi.hoisted(() => {
  const report = {
    schema_version: "2.0",
    target: { type: "website", name: "Northwind", url: "https://x.example", metadata: {} },
    site: { url: "https://x.example", market: "us", language: "en" },
    scores: { seo: 72, aeo: 61, geo: 58, overall: 64 },
    seo: { technical_seo: 55 },
    entities: [],
    competitors: [],
    metadata: {
      created_at: "2026-09-29T10:00:00.000Z",
      updated_at: "2026-09-29T10:00:00.000Z",
      plan: "plan_standard",
      version: "2.0",
      advisor: {
        schema_version: "1.0",
        actions: [
          {
            rank: 1,
            title: "Fix crawl issues",
            action: "Resolve robots rules and sitemap gaps.",
            impact: "high",
            effort: "low",
            roi_score: 9.2,
            grounded_by_findings: ["seo.technical_seo"],
            derived_from: [],
            // Raised by a deterministic check, so it has durable identity.
            problem_code: "missing_canonical_url",
          },
          {
            rank: 2,
            title: "Publish a data feed",
            action: "Expose amenities as a machine-readable feed.",
            impact: "medium",
            effort: "medium",
            roi_score: 5.1,
            grounded_by_findings: [],
            derived_from: [],
          },
          {
            rank: 3,
            title: "Earn authoritative backlinks",
            action: "Pitch travel and local press.",
            impact: "medium",
            effort: "medium",
            roi_score: 4.0,
            grounded_by_findings: [],
            derived_from: [],
          },
        ],
      },
    },
    recommendations: {
      items: [
        {
          title: "Fix crawl issues",
          action: "Resolve robots rules and sitemap gaps.",
          category: "Technical",
          estimated_effort: "low",
          expected_score_impact: { seo: 6, geo: null, aeo: null, overall: 6 },
          rationale: "Blocked pages cannot rank.",
          grounded_by_findings: ["seo.technical_seo"],
          derived_from: [],
          problem_code: "missing_canonical_url",
        },
        {
          title: "Publish a data feed",
          action: "Expose amenities as a machine-readable feed.",
          category: "Content",
          // No estimated_effort and every impact dimension null: the unrated case.
          expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
          rationale: "AI cannot recommend what it cannot read.",
          grounded_by_findings: [],
          derived_from: [],
        },
        {
          title: "Earn authoritative backlinks",
          action: "Pitch travel and local press.",
          category: "Backlinks",
          estimated_effort: "high",
          expected_score_impact: { seo: null, geo: 4, aeo: 3, overall: 5 },
          grounded_by_findings: [],
          derived_from: [],
        },
      ],
    },
  };
  return {
    current: {
      // Overwritten by reset() with the shared served fixture; vi.hoisted
      // factories run before imports, so this seed cannot reference it.
      project: { latest_seo_score: 72, feature_access: {} },
      loading: false,
      error: null as null | string,
      auditSelection: null as unknown,
      latestAudit: {
        id: 700,
        status: "completed",
        url: "https://x.example",
        full_report: report,
      } as unknown,
    },
  };
});

type StubReport = { metadata: Record<string, unknown> } & Record<string, unknown>;
const FULL_REPORT = (auditMock.current.latestAudit as { full_report: StubReport }).full_report;

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => auditMock.current,
}));

const reset = () => {
  auditMock.current = {
    ...auditMock.current,
    loading: false,
    error: null,
    project: { latest_seo_score: 72, feature_access: ADVISOR_PLAN_ALLOWED },
    latestAudit: {
      id: 700,
      status: "completed",
      url: "https://x.example",
      full_report: FULL_REPORT,
    },
  };
  tasksMock.fetchProjectTasks.mockResolvedValue(BOARD);
  tasksMock.createProjectTask.mockResolvedValue(makeTask({ id: 9, status: "done" }));
  tasksMock.updateProjectTask.mockResolvedValue(makeTask({ status: "done" }));
  decisionsMock.fetchRecommendationDecisions.mockResolvedValue([]);
  decisionsMock.recordRecommendationDecision.mockResolvedValue({ id: 5 });
};

describe("fixes page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    reset();
  });

  it("states the count of cards rendered, and names each row's source (SIGV2-1193)", async () => {
    render(<ProjectFixesPage />);
    expect(await screen.findByText("Your action plan")).toBeInTheDocument();
    expect(
      screen.getByText(
        "All fixes, ranked by impact and effort. Your dashboard shows the top three."
      )
    ).toBeInTheDocument();

    // The stated count is the number of cards actually in the active list, so
    // the two can never drift apart again. Finished work is counted on its own
    // accordion instead (SIGV2-1211), not folded into this line.
    //
    // SIGV2-1193: this line used to read "N Advisor recommendations", because
    // the page was one of two lists and SIGV2-1175 made each name its source.
    // There is one list now, so the count names no channel and the row does
    // the naming instead.
    await screen.findByTestId("fix-advisor-action-1");
    const cards = screen.queryAllByTestId(/^fix-advisor-action-/);
    expect(cards.length).toBe(3);
    expect(screen.getByText(`${cards.length} fixes to act on`)).toBeInTheDocument();
    expect(screen.queryByText(/Advisor recommendations/)).toBeNull();
    for (const card of cards) {
      expect(card.textContent).toContain("From your action plan");
    }
  });

  it("lists the audit's own findings in the same plan (SIGV2-1193)", async () => {
    // The page used to show the Advisor plan only, while the Improve tab
    // showed the audit's score-breakdown findings, and the two totals were
    // read as a contradiction. One list now: a coded penalty the plan also
    // raised folds into its action, and one it did not raise is listed here
    // on its own row, labelled with where it came from.
    const report = {
      ...FULL_REPORT,
      scores: {
        ...(FULL_REPORT.scores as Record<string, unknown>),
        seo_breakdown: {
          penalties: [
            // Same problem as the plan's first action (problem_code
            // missing_canonical_url): one row, not two.
            { reason: "Missing canonical URL", impact: -15, code: "missing_canonical_url" },
            // Raised by the audit only.
            { reason: "Missing meta description", impact: -9, code: "missing_meta_description" },
          ],
        },
      },
    };
    auditMock.current = {
      ...auditMock.current,
      latestAudit: {
        ...(auditMock.current.latestAudit as Record<string, unknown>),
        full_report: report,
      } as never,
    };

    render(<ProjectFixesPage />);

    await screen.findByText("Fix crawl issues");
    // The coded penalty folded into the plan's action rather than adding a
    // second card for the same problem.
    expect(screen.queryByText("Missing canonical URL")).toBeNull();
    // The audit-only finding is here, and says so.
    const auditOnly = screen.getByText("Missing meta description").closest("[data-testid]")!;
    expect(auditOnly.textContent).toContain("From the audit");
    expect(screen.getByText("4 fixes to act on")).toBeInTheDocument();
    // Still no numeric impact, on a list that now carries measured penalty
    // deductions as well as expected-score deltas.
    const list = screen.getByText("4 fixes to act on").parentElement!;
    expect(list.textContent).not.toMatch(/\d+\s*(pts?|points?|%)/i);
  });

  it("renders the approved pagehead, alert and ranked cards", async () => {
    render(<ProjectFixesPage />);
    expect(await screen.findByText("Your action plan")).toBeInTheDocument();
    expect(screen.getByText(/categorical impact, not a point estimate/)).toBeInTheDocument();
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    expect(within(fix1).getByText("Fix crawl issues")).toBeInTheDocument();
    expect(within(fix1).getByText("1")).toBeInTheDocument();
    expect(screen.getByTestId("fix-advisor-action-2")).toBeInTheDocument();
    expect(screen.getByTestId("fix-advisor-action-3")).toBeInTheDocument();
  });

  it("never leaks the mockup's build annotation to a customer", async () => {
    const { container } = render(<ProjectFixesPage />);
    await screen.findByTestId("fix-advisor-action-1");
    expect(container.textContent).not.toContain("@needs-backend");
    expect(container.textContent).not.toContain("SIGV2-");
  });

  it("renders no numeric impact figure anywhere on the plan", async () => {
    // The product rule: impact is categorical, never a point estimate. The
    // canonical items in this fixture carry real expected_score_impact
    // numbers (6, 4, 3, 5), so a regression that prints a delta, a "+6 pts"
    // or a percentage uplift fails here rather than in front of a customer.
    render(<ProjectFixesPage />);
    await screen.findByTestId("fix-advisor-action-1");
    for (const id of ["fix-advisor-action-1", "fix-advisor-action-2", "fix-advisor-action-3"]) {
      const text = screen.getByTestId(id).textContent ?? "";
      expect(text).not.toMatch(/\d+\s*(pts?|points?|%)/i);
      expect(text).not.toMatch(/[+\u2212-]\s?\d+(\.\d+)?\s*(pt|point|%)/i);
      // No bare score delta from expected_score_impact either.
      expect(text).not.toMatch(/\b(seo|aeo|geo|overall)\b[^.]{0,12}\d/i);
    }
  });

  it("hardcodes none of the mockup's demo rows or demo brand", () => {
    // Row titles are LLM-generated per audit, so this is a source check, not
    // a render check: a fixture may legitimately contain any title, but the
    // page and its strings must never ship the mockup's demo content.
    const sources = [
      "src/app/(app)/dashboard/projects/[projectId]/fixes/page.tsx",
      "src/i18n/en.json",
    ]
      .map((relative) => readFileSync(resolve(process.cwd(), relative), "utf8"))
      .join("\n");
    for (const demo of [
      "Publish a structured data feed",
      "Reclaim uncited brand mentions",
      "Fix crawl & indexation on 14 pages",
      "Earn authoritative backlinks",
      "Answer-style rewrite of the offers page",
      "Compress hero imagery below 200KB",
      "northwindhotels.com",
      "Northwind",
      "@needs-backend",
    ]) {
      expect(sources).not.toContain(demo);
    }
  });

  it("renders measured effort and impact chips from the canonical item", async () => {
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    expect(within(fix1).getByText("Effort: Low")).toBeInTheDocument();
    expect(within(fix1).getByText("Impact: High")).toBeInTheDocument();
    expect(within(fix1).getByText("Category · Technical")).toBeInTheDocument();
  });

  it("renders unrated chips when effort is absent and impact is all-null", async () => {
    render(<ProjectFixesPage />);
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    expect(within(fix2).getByText("Effort: not rated")).toBeInTheDocument();
    expect(within(fix2).getByText("Impact: not rated")).toBeInTheDocument();
    expect(within(fix2).queryByText(/Effort: Medium/)).not.toBeInTheDocument();
  });

  it("names the moved pillar only when a numeric delta exists", async () => {
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    expect(fix1.textContent).toContain("SEO score");
    expect(fix1.textContent).not.toContain("AIO score");
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    expect(fix2.textContent).not.toContain("SEO score");
    expect(fix2.textContent).not.toContain("AIO score");
    const fix3 = await screen.findByTestId("fix-advisor-action-3");
    expect(fix3.textContent).toContain("AIO score");
  });

  it("shows the Backlinks class under the Authority label", async () => {
    render(<ProjectFixesPage />);
    const fix3 = await screen.findByTestId("fix-advisor-action-3");
    expect(within(fix3).getByText("Category · Authority")).toBeInTheDocument();
  });

  it("filters by category with only real classes and no Feature chip", async () => {
    render(<ProjectFixesPage />);
    await screen.findByTestId("fix-advisor-action-1");
    expect(screen.queryByRole("button", { name: "Feature" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Authority" }));
    expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument();
    expect(screen.getByTestId("fix-advisor-action-3")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Technical" }));
    expect(screen.getByTestId("fix-advisor-action-1")).toBeInTheDocument();
    expect(screen.queryByTestId("fix-advisor-action-3")).not.toBeInTheDocument();
  });

  it("falls back to canonical recommendations when the advisor plan is empty", async () => {
    // SIGV2-1096: a scan can produce recommendations but no findings for the
    // grounding gate to attach to, so the advisor drops every candidate. The
    // page must list the real recommendations, not claim no check ran.
    const report = {
      ...FULL_REPORT,
      metadata: {
        ...FULL_REPORT.metadata,
        advisor: {
          schema_version: "advisor-det-1",
          actions: [],
          strategic_summary: null,
          metadata: { total_candidates: 3, actions_count: 0, dropped_ungrounded: 3 },
        },
      },
    };
    auditMock.current = {
      ...auditMock.current,
      latestAudit: {
        ...(auditMock.current.latestAudit as Record<string, unknown>),
        full_report: report,
      } as never,
    };
    render(<ProjectFixesPage />);
    expect(await screen.findByTestId("fix-rec-1")).toBeInTheDocument();
    expect(screen.getByText("Publish a data feed")).toBeInTheDocument();
    expect(screen.getByTestId("fix-rec-3")).toBeInTheDocument();
    expect(screen.queryByText(/Run a check to get a ranked list/)).not.toBeInTheDocument();
  });

  it("tells the truth when a finished scan produced no fixes", async () => {
    const report = {
      ...FULL_REPORT,
      metadata: { ...FULL_REPORT.metadata, advisor: null },
      recommendations: { items: [] },
    };
    auditMock.current = {
      ...auditMock.current,
      latestAudit: {
        ...(auditMock.current.latestAudit as Record<string, unknown>),
        full_report: report,
      } as never,
    };
    render(<ProjectFixesPage />);
    expect(await screen.findByText(/finished without finding fixes to act on/)).toBeInTheDocument();
    expect(screen.queryByText(/Run a check to get a ranked list/)).not.toBeInTheDocument();
  });

  it("shows board status and filters the active list by it", async () => {
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    expect(within(fix1).getByText("In progress")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "In progress" }));
    expect(screen.getByTestId("fix-advisor-action-1")).toBeInTheDocument();
    expect(screen.queryByTestId("fix-advisor-action-2")).not.toBeInTheDocument();
  });

  // SIGV2-1211: the status filter triages live work, so it offers only the
  // states the active list can hold. Done is not one of them any more: it
  // lives on the Completed accordion, and a filter that can never match
  // anything is worse than an absent one (same reason "Feature" is absent
  // from the category row).
  it("offers no Done option in the status filter", async () => {
    render(<ProjectFixesPage />);
    await screen.findByTestId("fix-advisor-action-1");
    expect(screen.getByRole("button", { name: "Not started" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "In progress" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Done" })).not.toBeInTheDocument();
  });

  it("folds done board records into a Completed accordion, closed by default", async () => {
    render(<ProjectFixesPage />);
    const trigger = await screen.findByTestId("fix-history-completed-trigger");
    // One done orphan on the board, and it is not in the DOM until asked for.
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveTextContent("Completed actions · 1");
    expect(screen.queryByText("Add FAQ schema to the location page")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    const panel = screen.getByTestId("fix-history-completed-panel");
    expect(panel).toHaveAttribute("id", trigger.getAttribute("aria-controls"));
    expect(within(panel).getByText("Add FAQ schema to the location page")).toBeInTheDocument();
    expect(within(panel).getByText(/Kept here so the record is complete/)).toBeInTheDocument();
  });

  it("marks done via the task update endpoint and moves the card into Completed", async () => {
    // First load returns the in-progress board; the post-mutation refetch
    // returns the persisted done state.
    const doneBoard = {
      ...BOARD,
      tasks: BOARD.tasks.map((task) => (task.id === 1 ? { ...task, status: "done" } : task)),
    };
    tasksMock.fetchProjectTasks.mockReset();
    tasksMock.fetchProjectTasks.mockResolvedValue(doneBoard);
    tasksMock.fetchProjectTasks.mockResolvedValueOnce(BOARD);
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    fireEvent.click(within(fix1).getByRole("button", { name: "Mark done" }));
    await waitFor(() =>
      expect(tasksMock.updateProjectTask).toHaveBeenCalledWith(
        "42",
        1,
        { status: "done" },
        expect.anything()
      )
    );
    // Out of the active list, and findable under Completed, which now counts
    // two records.
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument()
    );
    const trigger = screen.getByTestId("fix-history-completed-trigger");
    expect(trigger).toHaveTextContent("Completed actions · 2");
    fireEvent.click(trigger);
    const panel = screen.getByTestId("fix-history-completed-panel");
    expect(within(panel).getByTestId("fix-advisor-action-1")).toBeInTheDocument();
  });

  it("sends a completed action back to the active list without deleting it", async () => {
    const doneBoard = {
      ...BOARD,
      tasks: BOARD.tasks.map((task) => (task.id === 1 ? { ...task, status: "done" } : task)),
    };
    tasksMock.fetchProjectTasks.mockReset();
    tasksMock.fetchProjectTasks.mockResolvedValue(BOARD);
    tasksMock.fetchProjectTasks.mockResolvedValueOnce(doneBoard);
    render(<ProjectFixesPage />);
    const trigger = await screen.findByTestId("fix-history-completed-trigger");
    fireEvent.click(trigger);
    const row = within(screen.getByTestId("fix-history-completed-panel")).getByTestId(
      "fix-advisor-action-1"
    );
    fireEvent.click(within(row).getByRole("button", { name: "Mark not started" }));
    await waitFor(() =>
      expect(tasksMock.updateProjectTask).toHaveBeenCalledWith(
        "42",
        1,
        { status: "todo" },
        expect.anything()
      )
    );
    await waitFor(() =>
      expect(screen.getByText("Moved back to your active actions.")).toBeInTheDocument()
    );
  });

  it("creates a task when marking an untracked fix done", async () => {
    render(<ProjectFixesPage />);
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    fireEvent.click(within(fix2).getByRole("button", { name: "Mark done" }));
    await waitFor(() =>
      expect(tasksMock.createProjectTask).toHaveBeenCalledWith(
        "42",
        expect.objectContaining({
          title: "Publish a data feed",
          status: "done",
          category: "Content",
          source_audit_id: 700,
        }),
        expect.anything()
      )
    );
    // The server derives the recommendation key and the audit_recommendation
    // origin from source_audit_id + title; the client sends no key of its own.
    expect(tasksMock.createProjectTask.mock.calls[0][1]).not.toHaveProperty(
      "source_recommendation_key"
    );
  });

  it("matches a server-synced task by its persisted title", async () => {
    // The sync path persists the canonical recommendation title, which differs
    // from the advisor action detail; the join is the normalized title, the
    // same check resolve_task_recommendation_key uses server-side.
    tasksMock.fetchProjectTasks.mockResolvedValue({
      ...BOARD,
      tasks: [
        makeTask({
          title: "fix crawl issues",
          status: "in_progress",
          source_recommendation_key: "technical:fix-crawl-issues:13214b27a614",
        }),
      ],
    });
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    expect(within(fix1).getByText("In progress")).toBeInTheDocument();
  });

  it("hides a fix whose dismissal was persisted by a previous session", async () => {
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        action_fingerprint: "abc",
        action_label: "Expose amenities as a machine-readable feed.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    expect(await screen.findByTestId("fix-advisor-action-1")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-2")).not.toBeInTheDocument()
    );
    expect(screen.getByTestId("fix-advisor-action-3")).toBeInTheDocument();
  });

  it("rolls back and surfaces the error when mark-done fails", async () => {
    tasksMock.updateProjectTask.mockRejectedValueOnce(new Error("denied"));
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    fireEvent.click(within(fix1).getByRole("button", { name: "Mark done" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("denied"));
    // Rolled back: back in the active list, still in progress, action buttons
    // restored. The optimistic write moved the card into Completed, so this
    // has to be re-queried rather than read off the stale node.
    const restored = screen.getByTestId("fix-advisor-action-1");
    expect(within(restored).getByText("In progress")).toBeInTheDocument();
    expect(within(restored).getByRole("button", { name: "Mark done" })).toBeInTheDocument();
  });

  it("dismisses via recommendation-decisions with the raw action text", async () => {
    render(<ProjectFixesPage />);
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    fireEvent.click(within(fix2).getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(decisionsMock.recordRecommendationDecision).toHaveBeenCalledWith(
        "42",
        {
          action_text: "Expose amenities as a machine-readable feed.",
          // LLM-authored advice has no deterministic code, so it keeps text
          // identity and will reappear if the next audit rewords it. That is
          // the honest residual, not something to paper over.
          problem_code: null,
          decision: "dismissed",
        },
        expect.anything()
      )
    );
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-2")).not.toBeInTheDocument()
    );
  });

  it("dismisses a deterministic fix with its problem code", async () => {
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    fireEvent.click(within(fix1).getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(decisionsMock.recordRecommendationDecision).toHaveBeenCalledWith(
        "42",
        {
          action_text: "Resolve robots rules and sitemap gaps.",
          problem_code: "missing_canonical_url",
          decision: "dismissed",
        },
        expect.anything()
      )
    );
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument()
    );
  });

  it("hides a deterministic fix dismissed under wording from a previous audit", async () => {
    // SIGV2-1118: the stored decision is keyed on the failing check, and its
    // label is the OLD audit's wording, which no longer matches this audit's
    // text. Suppression must still hold.
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 11,
        project_id: 42,
        action_fingerprint: "problem:missing_canonical_url",
        action_label: "Set a canonical link element on every indexable page.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    expect(await screen.findByTestId("fix-advisor-action-2")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument()
    );
    expect(screen.getByTestId("fix-advisor-action-3")).toBeInTheDocument();
  });

  it("keeps a fix dismissed across a reload", async () => {
    // The acceptance criterion, exercised as two real mounts rather than
    // asserted from the code path: dismiss, then remount with the decision
    // the server now returns, as a fresh page load would.
    const { unmount } = render(<ProjectFixesPage />);
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    fireEvent.click(within(fix2).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(decisionsMock.recordRecommendationDecision).toHaveBeenCalled());
    const posted = decisionsMock.recordRecommendationDecision.mock.calls[0][1] as {
      action_text: string;
    };
    unmount();

    // Second load: the server replays the decision it persisted. The advisor
    // plan still carries the action, because the persisted report is
    // unfiltered; the page must suppress it from the stored action_label.
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 11,
        project_id: 42,
        action_fingerprint: "fp",
        action_label: posted.action_text,
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    expect(await screen.findByTestId("fix-advisor-action-1")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByTestId("fix-advisor-action-2")).not.toBeInTheDocument()
    );
  });

  it("posts the canonical action text as the dismiss key on the fallback path", async () => {
    // The dismiss key must be the canonical `action`, because
    // attach_advisor_view fingerprints that exact string to suppress the fix
    // server-side. On the recommendations fallback the advisor action's
    // `detail` holds the rationale, so keying off it would post the wrong
    // text and backend suppression would silently never match.
    const report = {
      ...FULL_REPORT,
      metadata: { ...FULL_REPORT.metadata, advisor: { schema_version: "1.0", actions: [] } },
      recommendations: {
        items: [
          {
            title: "Expose amenities as a machine-readable feed.",
            action: "Expose amenities as a machine-readable feed.",
            category: "Content",
            rationale: "AI cannot recommend what it cannot read.",
            expected_score_impact: { seo: null, geo: null, aeo: null, overall: null },
            grounded_by_findings: [],
            derived_from: [],
          },
        ],
      },
    };
    auditMock.current = {
      ...auditMock.current,
      latestAudit: {
        ...(auditMock.current.latestAudit as Record<string, unknown>),
        full_report: report,
      } as never,
    };
    render(<ProjectFixesPage />);
    const row = await screen.findByTestId("fix-rec-1");
    fireEvent.click(within(row).getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(decisionsMock.recordRecommendationDecision).toHaveBeenCalledWith(
        "42",
        {
          action_text: "Expose amenities as a machine-readable feed.",
          // No deterministic check raised this item, so it has no durable key
          // and falls back to text identity.
          problem_code: null,
          decision: "dismissed",
        },
        expect.anything()
      )
    );
  });

  it("restores the card when dismiss fails", async () => {
    decisionsMock.recordRecommendationDecision.mockRejectedValueOnce(new Error("denied"));
    render(<ProjectFixesPage />);
    const fix2 = await screen.findByTestId("fix-advisor-action-2");
    fireEvent.click(within(fix2).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("denied"));
    expect(screen.getByTestId("fix-advisor-action-2")).toBeInTheDocument();
  });

  // SIGV2-1211: dismissed rows used to be dropped from the joined row set
  // entirely, so there was nothing left to list. They are retained and listed
  // here instead; no decision record is deleted to make that work.
  it("lists a dismissed action in its own accordion, closed by default", async () => {
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        action_fingerprint: "problem:missing_canonical_url",
        action_label: "Resolve robots rules and sitemap gaps.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    const trigger = await screen.findByTestId("fix-history-dismissed-trigger");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveTextContent("Dismissed actions · 1");
    expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument();

    fireEvent.click(trigger);
    const panel = screen.getByTestId("fix-history-dismissed-panel");
    expect(panel).toHaveAttribute("id", trigger.getAttribute("aria-controls"));
    const row = within(panel).getByTestId("fix-advisor-action-1");
    expect(within(row).getByText("Fix crawl issues")).toBeInTheDocument();
    expect(within(row).getByText("Dismissed")).toBeInTheDocument();
    // The problem_code join still holds inside the accordion, so a reworded
    // action is recognised as the one that was dismissed.
    expect(within(row).getByText("Category · Technical")).toBeInTheDocument();
  });

  it("restores a dismissed action by superseding the decision, never deleting it", async () => {
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        action_fingerprint: "problem:missing_canonical_url",
        action_label: "Resolve robots rules and sitemap gaps.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    fireEvent.click(await screen.findByTestId("fix-history-dismissed-trigger"));
    const row = within(screen.getByTestId("fix-history-dismissed-panel")).getByTestId(
      "fix-advisor-action-1"
    );
    fireEvent.click(within(row).getByRole("button", { name: "Restore" }));
    await waitFor(() =>
      expect(decisionsMock.recordRecommendationDecision).toHaveBeenCalledWith(
        "42",
        {
          action_text: "Resolve robots rules and sitemap gaps.",
          problem_code: "missing_canonical_url",
          decision: "accepted",
        },
        expect.anything()
      )
    );
    // Back in the active list, and the accordion is gone with nothing left in it.
    await waitFor(() => expect(screen.getByTestId("fix-advisor-action-1")).toBeInTheDocument());
    expect(screen.queryByTestId("fix-history-dismissed-trigger")).not.toBeInTheDocument();
    expect(screen.getByText("Restored to your active actions.")).toBeInTheDocument();
  });

  it("keeps a failed restore recoverable", async () => {
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        action_fingerprint: "problem:missing_canonical_url",
        action_label: "Resolve robots rules and sitemap gaps.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    decisionsMock.recordRecommendationDecision.mockRejectedValueOnce(new Error("denied"));
    render(<ProjectFixesPage />);
    fireEvent.click(await screen.findByTestId("fix-history-dismissed-trigger"));
    const row = within(screen.getByTestId("fix-history-dismissed-panel")).getByTestId(
      "fix-advisor-action-1"
    );
    fireEvent.click(within(row).getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("denied"));
    // Still dismissed, and the Restore button is live again for a retry.
    const retry = within(screen.getByTestId("fix-history-dismissed-panel")).getByTestId(
      "fix-advisor-action-1"
    );
    expect(within(retry).getByRole("button", { name: "Restore" })).toBeEnabled();
    expect(screen.queryAllByTestId("fix-advisor-action-1").length).toBe(1);
  });

  it("says so when every action is finished rather than claiming a filter hid them", async () => {
    decisionsMock.fetchRecommendationDecisions.mockResolvedValue([
      {
        id: 9,
        project_id: 42,
        action_fingerprint: "problem:missing_canonical_url",
        action_label: "Resolve robots rules and sitemap gaps.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
      {
        id: 10,
        project_id: 42,
        action_fingerprint: "fp2",
        action_label: "Expose amenities as a machine-readable feed.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
      {
        id: 11,
        project_id: 42,
        action_fingerprint: "fp3",
        action_label: "Pitch travel and local press.",
        decision: "dismissed",
        note: null,
        decided_by: 1,
        created_at: null,
      },
    ]);
    render(<ProjectFixesPage />);
    await waitFor(() =>
      expect(screen.getByText(/done or dismissed. Open the sections below/)).toBeInTheDocument()
    );
    expect(screen.getByTestId("fix-history-dismissed-trigger")).toHaveTextContent(
      "Dismissed actions · 3"
    );
  });

  it("offers no history accordion when there is no history", async () => {
    tasksMock.fetchProjectTasks.mockResolvedValue({ ...BOARD, tasks: [] });
    render(<ProjectFixesPage />);
    await screen.findByTestId("fix-advisor-action-1");
    await waitFor(() =>
      expect(screen.queryByTestId("fix-history-completed-trigger")).not.toBeInTheDocument()
    );
    expect(screen.queryByTestId("fix-history-dismissed-trigger")).not.toBeInTheDocument();
  });

  it("renders the empty state when the plan has no actions", async () => {
    // SIGV2-1096: with no advisor actions AND no canonical items, a completed
    // audit shows the honest finished-without-fixes state.
    auditMock.current = {
      ...auditMock.current,
      latestAudit: {
        id: 700,
        status: "completed",
        url: "https://x.example",
        full_report: {
          ...FULL_REPORT,
          metadata: { ...FULL_REPORT.metadata, advisor: { actions: [] } },
          recommendations: { items: [] },
        },
      },
    };
    render(<ProjectFixesPage />);
    expect(await screen.findByText(/finished without finding fixes to act on/)).toBeInTheDocument();
  });

  // SIGV2-1134: the gate is the served `advisor_recommendations` entitlement,
  // and the plan it names is the one the backend named. This used to resolve
  // off the offline capability table keyed on `user.subscription_plan`.
  it("locks the plan, naming the plan the backend requires", async () => {
    auditMock.current = {
      ...auditMock.current,
      project: { latest_seo_score: 72, feature_access: ADVISOR_PLAN_LOCKED },
    };
    render(<ProjectFixesPage />);
    expect(await screen.findByText("Unlock your action plan")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upgrade to Standard" })).toHaveAttribute(
      "href",
      expect.stringContaining("plan_standard")
    );
    expect(screen.queryByTestId("fix-advisor-action-1")).not.toBeInTheDocument();
  });

  it("disables mutations when the board is read-only", async () => {
    tasksMock.fetchProjectTasks.mockResolvedValue({ ...BOARD, can_edit: false });
    render(<ProjectFixesPage />);
    const fix1 = await screen.findByTestId("fix-advisor-action-1");
    await waitFor(() =>
      expect(within(fix1).getByRole("button", { name: "Mark done" })).toBeDisabled()
    );
    expect(within(fix1).getByRole("button", { name: "Dismiss" })).toBeDisabled();
  });
});
