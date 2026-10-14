import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import {
  WorkspacePageHeaderContext,
  type WorkspacePageHeader,
} from "@/components/dashboard/workspacePageHeader";
import { buildScanLaunchHref } from "@/lib/scanLaunch";
import {
  recordScanLaunchIntent,
  SCAN_LAUNCH_INTENT_KEY,
  SCAN_LAUNCH_INTENT_TTL_MS,
} from "@/lib/scanLaunchIntent";
import { tEn } from "@/test/i18nEn";

const {
  getTokenMock,
  useAuditFormMock,
  useAuditRunnerMock,
  useWorkspaceHistoryMock,
  auditConfigurationFormMock,
  fetchVisibilitySummaryMock,
  fetchVisibilityQueriesMock,
  pushMock,
  replaceMock,
  searchParamsState,
  userPlanState,
  signedInState,
} = vi.hoisted(() => ({
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
  useAuditFormMock: vi.fn(),
  useAuditRunnerMock: vi.fn(),
  useWorkspaceHistoryMock: vi.fn(),
  auditConfigurationFormMock: vi.fn(),
  fetchVisibilitySummaryMock: vi.fn(),
  fetchVisibilityQueriesMock: vi.fn(),
  pushMock: vi.fn(),
  replaceMock: vi.fn(),
  searchParamsState: { current: new URLSearchParams("") },
  userPlanState: { current: "plan_executive" },
  signedInState: { current: true },
}));

vi.mock("@/services/monitoringService", () => ({
  fetchVisibilitySummary: (...args: unknown[]) => fetchVisibilitySummaryMock(...args),
  // SIGV2-1176: the prompts section and the launch gate read the project's
  // prompt list from here.
  fetchVisibilityQueries: (...args: unknown[]) => fetchVisibilityQueriesMock(...args),
}));

/** A prompt list payload in the shape the visibility-queries endpoint serves. */
const promptList = (
  queries: Array<{ id: number; query_text: string; query_type?: "aeo" | "geo" }>,
  entitlements: Record<string, unknown> = {}
) => ({
  project_id: 42,
  entitlements: {
    plan: "plan_standard",
    plan_label: "Standard",
    max_queries: 10,
    used_queries: queries.length,
    remaining_queries: Math.max(0, 10 - queries.length),
    allowed_providers: ["openai"],
    is_locked: false,
    estimated_cost_per_check: {},
    ...entitlements,
  },
  queries: queries.map((query) => ({
    project_id: 42,
    query_type: "aeo" as const,
    providers: ["openai"],
    is_active: true,
    created_at: null,
    updated_at: null,
    ...query,
  })),
});

// `replace` is spied on as well as `push`: SIGV2-1163 removed an automatic
// navigation from this page, and a reintroduction could use either.
vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsState.current,
  useRouter: () => ({ push: pushMock, replace: replaceMock }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({
    getToken: getTokenMock,
    isSignedIn: signedInState.current,
    user: { subscription_plan: userPlanState.current },
  }),
}));

vi.mock("@/hooks/useAuditForm", () => ({
  useAuditForm: (...args: unknown[]) => useAuditFormMock(...args),
}));

vi.mock("@/hooks/useAuditRunner", () => ({
  useAuditRunner: (...args: unknown[]) => useAuditRunnerMock(...args),
}));

vi.mock("@/hooks/useWorkspaceHistory", () => ({
  useWorkspaceHistory: (...args: unknown[]) => useWorkspaceHistoryMock(...args),
}));

vi.mock("@/hooks/useBillingSettings", () => ({
  useBillingSettings: () => ({
    isLoading: false,
    billingOverview: null,
  }),
}));

vi.mock("@/hooks/useTierDurations", () => ({
  useTierDurations: () => ({
    durations: null,
    isLoading: false,
  }),
}));

vi.mock("@/components/results/AuditConfigurationForm", () => ({
  default: React.forwardRef(function MockAuditConfigurationForm(
    props: Record<string, unknown>,
    _ref
  ) {
    auditConfigurationFormMock(props);
    return <div data-testid="audit-configuration-form" />;
  }),
}));

vi.mock("@/components/ui/Card", () => ({
  default: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

vi.mock("@/components/ui/GlassComponents", () => ({
  GlassCard: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

let AuditDashboardPage: React.ComponentType;
let resolveStartCheckTab: (raw: string | null | undefined) => string;

describe("AuditDashboardPage", () => {
  beforeAll(async () => {
    const pageModule = await import("@/app/(app)/dashboard/audit/page");
    AuditDashboardPage = pageModule.default;
    resolveStartCheckTab = pageModule.resolveStartCheckTab;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    searchParamsState.current = new URLSearchParams("");
    userPlanState.current = "plan_executive";
    signedInState.current = true;
    window.sessionStorage.clear();

    useAuditFormMock.mockReturnValue({
      form: {
        provider: "google",
        tier: "deep_judgment",
        url: "",
        targetUrl: "",
        targetName: "",
      },
      setFormValue: vi.fn(),
      validateForm: vi.fn(),
      verifyUrlPreflight: vi.fn(),
      isPreflightChecking: false,
      preflightError: "",
    });

    useAuditRunnerMock.mockReturnValue({
      isLoading: false,
      isPolling: false,
      runPhase: "idle",
      runSnapshot: null,
    });

    useWorkspaceHistoryMock.mockReturnValue({
      fetchAuditRecord: vi.fn(),
      invalidateHistory: vi.fn(),
      upsertHistoryEntry: vi.fn(),
      sortedHistory: [],
    });

    fetchVisibilitySummaryMock.mockReset();
    // The default project has a prompt, so the mandatory-prompt gate
    // (SIGV2-1176) is satisfied and is not what any unrelated case is testing.
    fetchVisibilityQueriesMock.mockReset();
    fetchVisibilityQueriesMock.mockResolvedValue(
      promptList([{ id: 1, query_text: "best boutique hotels near the harbour" }])
    );
  });

  // The succeeded view's third stat (SIGV2-1123). The scan has no visibility
  // measurement of its own, so the figure is the project's, read from the
  // monitoring summary of the project the finished audit belongs to.
  describe("AI visibility on the succeeded view", () => {
    const succeededRunner = (overrides: Record<string, unknown> = {}) => ({
      isLoading: false,
      isPolling: false,
      runPhase: "succeeded",
      runSnapshot: {
        jobId: "job-1",
        phase: "succeeded",
        targetLabel: "example.com",
        targetUrl: "https://example.com",
        tier: "smart",
        stages: [],
        error: null,
        startedAt: null,
        completedAt: null,
        auditId: 42,
      },
      completedAuditMeta: { auditId: 42, aioScore: 64, seoScore: 74 },
      ...overrides,
    });

    const lastProps = () =>
      auditConfigurationFormMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;

    it("reads the project of the finished audit and passes the measured figure", async () => {
      useAuditRunnerMock.mockReturnValue(succeededRunner());
      useWorkspaceHistoryMock.mockReturnValue({
        fetchAuditRecord: vi.fn(),
        invalidateHistory: vi.fn(),
        upsertHistoryEntry: vi.fn(),
        sortedHistory: [{ id: 42, projectId: 7, createdAt: "2026-09-01T10:00:00Z" }],
      });
      fetchVisibilitySummaryMock.mockResolvedValue({
        project_id: 7,
        entitlements: { is_locked: false },
        visibility_score: 41.4,
        trend_delta: 5.2,
        completed_checks: 12,
        last_updated_at: "2026-08-29T09:00:00Z",
      });

      render(<AuditDashboardPage />);

      await waitFor(() => {
        expect(lastProps()).toEqual(
          expect.objectContaining({
            visibility: {
              state: "measured",
              percent: 41,
              delta: 5,
              measuredAt: "2026-08-29T09:00:00Z",
            },
          })
        );
      });
      expect(fetchVisibilitySummaryMock).toHaveBeenCalledWith(7, {
        Authorization: "Bearer token-123",
      });
    });

    it("reads nothing when the finished scan has no project behind it", () => {
      useAuditRunnerMock.mockReturnValue(succeededRunner());

      render(<AuditDashboardPage />);

      expect(fetchVisibilitySummaryMock).not.toHaveBeenCalled();
      expect(lastProps()).toEqual(expect.objectContaining({ visibility: null }));
    });

    it("reads nothing while the run has not finished", () => {
      useAuditRunnerMock.mockReturnValue(
        succeededRunner({ runPhase: "running", isPolling: true, completedAuditMeta: null })
      );
      searchParamsState.current = new URLSearchParams("projectId=7");

      render(<AuditDashboardPage />);

      expect(fetchVisibilitySummaryMock).not.toHaveBeenCalled();
      expect(lastProps()).toEqual(expect.objectContaining({ visibility: null }));
    });
  });

  // SIGV2-1163: a finished scan stays on its completed state. The approved
  // design makes that state terminal, with four actions the user chooses
  // between, so the page must never navigate on its own - a timed redirect was
  // tried here and withdrawn. These tests exist so it cannot come back by
  // accident: any reintroduced navigation, on any run phase, fails them.
  //
  // The destination fix the complaint actually needed is covered separately by
  // "points the run breadcrumb's Dashboard at the project dashboard" below
  // (SIGV2-1164).
  describe("a finished scan does not navigate on its own", () => {
    const runnerFor = (phase: "running" | "succeeded" | "failed") => ({
      isLoading: false,
      isPolling: phase === "running",
      runPhase: phase,
      runSnapshot: {
        jobId: "job-1",
        phase,
        targetLabel: "example.com",
        targetUrl: "https://example.com",
        tier: "smart",
        stages: [],
        error: phase === "failed" ? "The crawl stage could not reach the site." : null,
        startedAt: null,
        completedAt: null,
        auditId: phase === "succeeded" ? 42 : null,
      },
      completedAuditMeta:
        phase === "succeeded" ? { auditId: 42, aioScore: 64, seoScore: 74 } : null,
    });

    const completedEntry = (overrides: Record<string, unknown> = {}) => ({
      id: 42,
      url: "https://example.com",
      targetName: "Example",
      geoScore: 81,
      projectId: 7,
      ...overrides,
    });

    const lastOnAuditComplete = () => {
      const params = useAuditRunnerMock.mock.calls.at(-1)?.[0] as {
        onAuditComplete: (entry: unknown, report?: unknown) => void;
      };
      return params.onAuditComplete;
    };

    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    // A generous budget: a reintroduced timed redirect would have to be longer
    // than this to escape the assertion, and nothing on this page should be
    // waiting ten seconds to move the user anyway.
    const LONGER_THAN_ANY_PLAUSIBLE_DELAY_MS = 10_000;

    it("stays on the completed state after a successful run, with no project navigation", () => {
      useAuditRunnerMock.mockReturnValue(runnerFor("running"));

      const { rerender } = render(<AuditDashboardPage />);

      const onAuditComplete = lastOnAuditComplete();
      act(() => {
        onAuditComplete(completedEntry());
      });

      useAuditRunnerMock.mockReturnValue(runnerFor("succeeded"));
      rerender(<AuditDashboardPage />);

      act(() => {
        vi.advanceTimersByTime(LONGER_THAN_ANY_PLAUSIBLE_DELAY_MS);
      });

      expect(pushMock).not.toHaveBeenCalled();
      expect(replaceMock).not.toHaveBeenCalled();
      expect(screen.getByText("Status: succeeded.")).toBeInTheDocument();
    });

    it("stays put with its failure state when the scan fails", () => {
      useAuditRunnerMock.mockReturnValue(runnerFor("running"));
      const { rerender } = render(<AuditDashboardPage />);

      useAuditRunnerMock.mockReturnValue(runnerFor("failed"));
      rerender(<AuditDashboardPage />);

      act(() => {
        vi.advanceTimersByTime(LONGER_THAN_ANY_PLAUSIBLE_DELAY_MS);
      });

      expect(pushMock).not.toHaveBeenCalled();
      expect(replaceMock).not.toHaveBeenCalled();
      expect(screen.getByText("Status: failed.")).toBeInTheDocument();
    });

    it("does not move a user who re-opens a run that had already finished", () => {
      useAuditRunnerMock.mockReturnValue(runnerFor("succeeded"));

      render(<AuditDashboardPage />);

      act(() => {
        lastOnAuditComplete()(completedEntry());
        vi.advanceTimersByTime(LONGER_THAN_ANY_PLAUSIBLE_DELAY_MS);
      });

      expect(pushMock).not.toHaveBeenCalled();
      expect(replaceMock).not.toHaveBeenCalled();
    });

    it("does not navigate for a completed scan that names a project either", () => {
      // The project id is what a redirect would have used as its destination,
      // so this is the case that would regress first.
      searchParamsState.current = new URLSearchParams("projectId=9");
      useAuditRunnerMock.mockReturnValue(runnerFor("running"));

      render(<AuditDashboardPage />);

      act(() => {
        lastOnAuditComplete()(completedEntry({ projectId: 7 }));
        vi.advanceTimersByTime(LONGER_THAN_ANY_PLAUSIBLE_DELAY_MS);
      });

      expect(pushMock).not.toHaveBeenCalled();
      expect(replaceMock).not.toHaveBeenCalled();
    });
  });

  it("prefills the form from url, targetType, targetName and tier query params", () => {
    const setFormValue = vi.fn();
    useAuditFormMock.mockReturnValue({
      form: {
        provider: "google",
        tier: "fast",
        url: "",
        targetUrl: "",
        targetName: "",
      },
      setFormValue,
      validateForm: vi.fn(),
      verifyUrlPreflight: vi.fn(),
      isPreflightChecking: false,
      preflightError: "",
    });
    searchParamsState.current = new URLSearchParams(
      "url=https://example.com&targetType=brand&targetName=Acme&tier=deep_judgment"
    );

    render(<AuditDashboardPage />);

    expect(setFormValue).toHaveBeenCalledWith("auditTargetType", "brand");
    expect(setFormValue).toHaveBeenCalledWith("tier", "deep_judgment");
    expect(setFormValue).toHaveBeenCalledWith("targetName", "Acme");
    expect(setFormValue).toHaveBeenCalledWith("url", "https://example.com");
    expect(setFormValue).toHaveBeenCalledWith("targetUrl", "https://example.com");
  });

  // SIGV2-1170: the link's named target is handed to the form hook so a
  // stored draft for a different site is set aside rather than restored over
  // it. `useAuditForm` is mocked here; the restore behaviour itself is pinned
  // in useAuditForm.test.ts, and the autostart still refuses any target the
  // intent did not name (cases below).
  it("hands the link's named target to the form hook so it outranks a stale draft", () => {
    searchParamsState.current = new URLSearchParams("projectId=42&url=https://test.com&start=1");

    render(<AuditDashboardPage />);

    expect(useAuditFormMock).toHaveBeenCalledWith(
      expect.objectContaining({ linkTarget: "https://test.com" })
    );
  });

  it("disables the start action while a run is in flight", () => {
    useAuditRunnerMock.mockReturnValue({
      isLoading: false,
      isPolling: true,
      runPhase: "running",
      runSnapshot: null,
    });

    render(<AuditDashboardPage />);

    const renderedProps = auditConfigurationFormMock.mock.calls.at(-1)?.[0];
    expect(renderedProps).toEqual(expect.objectContaining({ isStartDisabled: true }));
  });

  it("disables the start action when the deep tier is locked by plan", () => {
    useAuditFormMock.mockReturnValue({
      form: {
        provider: "google",
        tier: "deep_judgment",
        url: "",
        targetUrl: "",
        targetName: "",
      },
      setFormValue: vi.fn(),
      validateForm: vi.fn(),
      verifyUrlPreflight: vi.fn(),
      isPreflightChecking: false,
      preflightError: "",
    });
    useAuditRunnerMock.mockReturnValue({
      isLoading: false,
      isPolling: false,
      runPhase: "idle",
      runSnapshot: null,
    });
    userPlanState.current = "plan_starter";

    render(<AuditDashboardPage />);

    const renderedProps = auditConfigurationFormMock.mock.calls.at(-1)?.[0];
    expect(renderedProps).toEqual(expect.objectContaining({ isStartDisabled: true }));
    expect(renderedProps).toEqual(
      expect.objectContaining({
        highConfidenceAccess: expect.objectContaining({ isLocked: true }),
      })
    );
  });

  it("leads with the approved start-scan page head while no run is attached", () => {
    render(<AuditDashboardPage />);

    expect(screen.getByTestId("audit-configuration-form")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 1, name: "Start a scan" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Set up the audit before it runs. A scan adds a new snapshot - it replaces nothing, your full history is kept."
      )
    ).toBeInTheDocument();
  });

  it("passes no runtime estimate to the configuration form", () => {
    render(<AuditDashboardPage />);

    const renderedProps = auditConfigurationFormMock.mock.calls.at(-1)?.[0];
    expect(renderedProps).not.toHaveProperty("estimatedRuntime");
  });

  it("switches the page head to the run status for each run phase", () => {
    const snapshot = {
      jobId: "job-1",
      phase: "running",
      targetLabel: "example.com",
      targetUrl: "https://example.com",
      tier: "smart",
      stages: [],
      error: null,
      startedAt: null,
      completedAt: null,
      auditId: null,
    };

    const cases = [
      [
        "running",
        "Status: running. It is safe to leave this page - the scan keeps going and the result lands on your dashboard.",
      ],
      ["succeeded", "Status: succeeded."],
      ["failed", "Status: failed."],
    ] as const;

    for (const [phase, status] of cases) {
      useAuditRunnerMock.mockReturnValue({
        isLoading: false,
        isPolling: phase === "running",
        runPhase: phase,
        runSnapshot: { ...snapshot, phase },
      });

      const { unmount } = render(<AuditDashboardPage />);
      expect(
        screen.getByRole("heading", { level: 1, name: "Scanning example.com" })
      ).toBeInTheDocument();
      expect(screen.getByText(status)).toBeInTheDocument();
      unmount();
    }
  });

  it("resolves every tab value to a known state", () => {
    expect(resolveStartCheckTab("history")).toBe("history");
    expect(resolveStartCheckTab(" HISTORY ")).toBe("history");
    expect(resolveStartCheckTab("start")).toBe("start");
    expect(resolveStartCheckTab("overview")).toBe("start");
    expect(resolveStartCheckTab("")).toBe("start");
    expect(resolveStartCheckTab(null)).toBe("start");
  });

  // SIGV2-1187: `?tab=history` no longer opens a disclosure here - the scan
  // history lives on the project dashboard. A project-scoped legacy link is
  // forwarded to that card's `#scan-history` anchor; a bare one cannot pick a
  // project, so it simply stays on the setup form.
  it("forwards a project-scoped tab=history link to the dashboard card", async () => {
    searchParamsState.current = new URLSearchParams("tab=History&projectId=3");

    render(<AuditDashboardPage />);

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/dashboard/projects/3#scan-history")
    );
  });

  it("keeps a bare tab=history link on the setup form, without forwarding", () => {
    searchParamsState.current = new URLSearchParams("tab=history");

    render(<AuditDashboardPage />);

    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("audit-configuration-form")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /your recent scans/i })).not.toBeInTheDocument();
  });

  it("falls back to the start state for an unrecognised tab value", () => {
    searchParamsState.current = new URLSearchParams("tab=overview");

    render(<AuditDashboardPage />);

    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("audit-configuration-form")).toBeInTheDocument();
  });

  it("renders no history card in any phase (SIGV2-1187)", () => {
    const snapshot = {
      jobId: "job-1",
      phase: "succeeded",
      targetLabel: "example.com",
      targetUrl: "https://example.com",
      tier: "smart",
      stages: [],
      error: null,
      startedAt: null,
      completedAt: null,
      auditId: 42,
    };

    for (const phase of ["idle", "running", "succeeded", "failed"] as const) {
      useAuditRunnerMock.mockReturnValue({
        isLoading: false,
        isPolling: phase === "running",
        runPhase: phase,
        runSnapshot: { ...snapshot, phase },
      });

      const { unmount } = render(<AuditDashboardPage />);
      expect(screen.queryByRole("button", { name: /your recent scans/i })).not.toBeInTheDocument();
      expect(screen.queryByTestId("audit-history-list")).not.toBeInTheDocument();
      unmount();
    }
  });

  it("registers the approved run breadcrumb, with an honest leaf per phase", () => {
    const snapshot = {
      jobId: "job-1",
      phase: "running",
      targetLabel: "example.com",
      targetUrl: "https://example.com",
      tier: "smart",
      stages: [],
      error: null,
      startedAt: null,
      completedAt: null,
      auditId: null,
    };

    const cases = [
      ["running", "Scan in progress"],
      ["succeeded", "Scan finished"],
      ["failed", "Scan failed"],
    ] as const;

    for (const [phase, leaf] of cases) {
      useAuditRunnerMock.mockReturnValue({
        isLoading: false,
        isPolling: phase === "running",
        runPhase: phase,
        runSnapshot: { ...snapshot, phase },
      });

      let header: WorkspacePageHeader = null;
      const Harness = () => {
        const [current, setCurrent] = React.useState<WorkspacePageHeader>(null);
        header = current;
        return (
          <WorkspacePageHeaderContext.Provider value={{ header: current, setHeader: setCurrent }}>
            <AuditDashboardPage />
            {/* The real shell renders the registered crumb inside SignalTopBar. */}
            <div data-testid="top-bar">{current?.crumb}</div>
          </WorkspacePageHeaderContext.Provider>
        );
      };

      const { unmount } = render(<Harness />);
      expect(header).not.toBeNull();
      const bar = screen.getByTestId("top-bar");
      expect(bar.textContent).toContain("Dashboard");
      expect(bar.textContent).toContain("Start a scan");
      expect(bar.textContent).toContain(leaf);
      unmount();
    }
  });

  // SIGV2-1164: "Dashboard" on the run views is this project's dashboard, the
  // destination the approved design links it to, not the workspace overview.
  it("points the run breadcrumb's Dashboard at the project dashboard", () => {
    searchParamsState.current = new URLSearchParams("projectId=7");
    useAuditRunnerMock.mockReturnValue({
      isLoading: false,
      isPolling: false,
      runPhase: "succeeded",
      runSnapshot: {
        jobId: "job-1",
        phase: "succeeded",
        targetLabel: "example.com",
        targetUrl: "https://example.com",
        tier: "smart",
        stages: [],
        error: null,
        startedAt: null,
        completedAt: null,
        auditId: 42,
      },
      completedAuditMeta: { auditId: 42, aioScore: 64, seoScore: 74 },
    });

    const Harness = () => {
      const [current, setCurrent] = React.useState<WorkspacePageHeader>(null);
      return (
        <WorkspacePageHeaderContext.Provider value={{ header: current, setHeader: setCurrent }}>
          <AuditDashboardPage />
          <div data-testid="top-bar">{current?.crumb}</div>
        </WorkspacePageHeaderContext.Provider>
      );
    };

    render(<Harness />);

    const bar = screen.getByTestId("top-bar");
    expect(bar.querySelector("a[href='/dashboard/projects/7']")?.textContent).toBe("Dashboard");
    expect(bar.querySelector("a[href='/dashboard']")).toBeNull();
    expect(
      (auditConfigurationFormMock.mock.calls.at(-1)?.[0] as Record<string, unknown>).dashboardHref
    ).toBe("/dashboard/projects/7");
  });

  it("keeps the workspace overview as the Dashboard fallback with no project to route to", () => {
    useAuditRunnerMock.mockReturnValue({
      isLoading: false,
      isPolling: true,
      runPhase: "running",
      runSnapshot: {
        jobId: "job-1",
        phase: "running",
        targetLabel: "example.com",
        targetUrl: "https://example.com",
        tier: "smart",
        stages: [],
        error: null,
        startedAt: null,
        completedAt: null,
        auditId: null,
      },
    });

    render(<AuditDashboardPage />);

    expect(
      (auditConfigurationFormMock.mock.calls.at(-1)?.[0] as Record<string, unknown>).dashboardHref
    ).toBe("/dashboard");
  });

  it("registers no breadcrumb on the start-scan form", () => {
    const setHeader = vi.fn();

    render(
      <WorkspacePageHeaderContext.Provider value={{ header: null, setHeader }}>
        <AuditDashboardPage />
      </WorkspacePageHeaderContext.Provider>
    );

    expect(setHeader).toHaveBeenCalledWith(null);
    expect(setHeader).not.toHaveBeenCalledWith(
      expect.objectContaining({ crumb: expect.anything() })
    );
  });

  // SIGV2-1159: the approved onboarding's last step runs the scan, so a launch
  // that already confirmed it must not meet the setup form a second time.
  //
  // The authority to start is a `sessionStorage` launch intent, never the URL.
  // The form prefills itself from `?url=`, so any URL-derived check compares an
  // attacker-supplied value with itself; the security review of PR #279 found
  // that `?url=attacker.tld&start=1` would spend a signed-in customer's scan on
  // a target they never chose. These cases pin the intent as the only
  // authority, and `a crafted link alone` is the regression test for it.
  describe("a launch that starts the scan itself", () => {
    const formWithTarget = (url: string) => ({
      form: {
        provider: "google",
        tier: "fast",
        url,
        targetUrl: url,
        targetName: "Northwind",
      },
      setFormValue: vi.fn(),
      validateForm: vi.fn(),
      verifyUrlPreflight: vi.fn(),
      isPreflightChecking: false,
      preflightError: "",
    });

    const idleRunner = () => {
      const handleSubmit = vi.fn();
      useAuditRunnerMock.mockReturnValue({
        isLoading: false,
        isPolling: false,
        runPhase: "idle",
        runSnapshot: null,
        handleSubmit,
      });
      return handleSubmit;
    };

    /** Writes an intent directly, so its age and target are under test control. */
    const storeIntent = (intent: { projectId?: number; target: string; ageMs?: number }) => {
      window.sessionStorage.setItem(
        SCAN_LAUNCH_INTENT_KEY,
        JSON.stringify({
          projectId: intent.projectId ?? 42,
          target: intent.target,
          createdAt: Date.now() - (intent.ageMs ?? 0),
        })
      );
    };

    const storedIntent = () => window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY);

    it("starts the run once when the launch intent matches the form target", async () => {
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      recordScanLaunchIntent({ projectId: 42, target: "northwind.example" });
      searchParamsState.current = new URLSearchParams(
        "projectId=42&url=northwind.example&targetName=Northwind"
      );

      const { rerender } = render(<AuditDashboardPage />);
      rerender(<AuditDashboardPage />);

      // The project's prompt list has to be known before a launch is allowed
      // at all (SIGV2-1176), so the start waits for that read rather than
      // racing it.
      await waitFor(() => expect(handleSubmit).toHaveBeenCalledTimes(1));
    });

    it("consumes the intent, so a reload cannot start a second scan", async () => {
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const first = idleRunner();
      recordScanLaunchIntent({ projectId: 42, target: "northwind.example" });
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      const { unmount } = render(<AuditDashboardPage />);
      await waitFor(() => expect(first).toHaveBeenCalledTimes(1));
      expect(storedIntent()).toBeNull();
      unmount();

      // The same URL again, which is all a reload has to go on.
      const second = idleRunner();
      render(<AuditDashboardPage />);
      await waitFor(() => expect(fetchVisibilityQueriesMock).toHaveBeenCalled());

      expect(second).not.toHaveBeenCalled();
    });

    it("never starts a scan from a crafted link alone, whatever it carries", () => {
      // The vector the security gate found: an emailed link, a signed-in
      // victim, no intent in this tab. The form prefills from ?url=, so the
      // page's own view of the target IS the attacker's value.
      useAuditFormMock.mockReturnValue(formWithTarget("https://attacker.tld"));
      const handleSubmit = idleRunner();
      searchParamsState.current = new URLSearchParams(
        "projectId=42&url=https://attacker.tld&targetName=Attacker&start=1&tier=deep_judgment"
      );

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start on an intent older than its expiry", async () => {
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      storeIntent({ target: "northwind.example", ageMs: SCAN_LAUNCH_INTENT_TTL_MS + 1_000 });
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      render(<AuditDashboardPage />);

      // And it is discarded rather than left to be read again. The read of
      // the prompt list gates the whole launch check, so the discard happens
      // once that has landed.
      await waitFor(() => expect(storedIntent()).toBeNull());
      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start when the link names a project the intent did not", () => {
      // Inside a live intent's window, a crafted link must not keep the
      // authorised target while redirecting the run at another project.
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      storeIntent({ projectId: 42, target: "northwind.example" });
      searchParamsState.current = new URLSearchParams("projectId=999&url=northwind.example");

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start when the intent names a different target than the form", () => {
      // A draft restored from an earlier visit holds a different site.
      useAuditFormMock.mockReturnValue(formWithTarget("https://coastline.example"));
      const handleSubmit = idleRunner();
      storeIntent({ target: "northwind.example" });
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start while re-attaching to a run that is already going", () => {
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      storeIntent({ target: "northwind.example" });
      searchParamsState.current = new URLSearchParams(
        "projectId=42&url=northwind.example&reattach=job-1"
      );

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start when the chosen depth is locked by the plan", () => {
      useAuditFormMock.mockReturnValue({
        ...formWithTarget("https://northwind.example"),
        form: {
          provider: "google",
          tier: "deep_judgment",
          url: "https://northwind.example",
          targetUrl: "https://northwind.example",
          targetName: "Northwind",
        },
      });
      const handleSubmit = idleRunner();
      storeIntent({ target: "northwind.example" });
      userPlanState.current = "plan_starter";
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    it("does not start for a signed-out visitor", () => {
      signedInState.current = false;
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      storeIntent({ target: "northwind.example" });
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
    });

    // SIGV2-1256: Rescan on the project dashboard prefills this page and
    // stops. It used to record a launch intent too, which this effect acted
    // on, so Rescan went straight to a running scan: nothing left to choose,
    // and one of the plan's scans spent on a single click. The exact link
    // that control builds is what is exercised here, so the two cannot drift
    // apart silently.
    it("does not start a run for the project dashboard's Rescan link", () => {
      const href = buildScanLaunchHref(
        42,
        { url: "https://northwind.example", name: "Northwind", targetType: "website" },
        { tab: "overview" }
      );
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      searchParamsState.current = new URLSearchParams(href.split("?")[1] ?? "");

      render(<AuditDashboardPage />);

      expect(handleSubmit).not.toHaveBeenCalled();
      expect(storedIntent()).toBeNull();
    });

    // SIGV2-1176 interacts with this path: a Rescan of a project with no
    // prompts must not start a scan that can only produce empty AI answer
    // surfaces. The guard is the same `isStartDisabled` the Start button
    // uses, so the customer lands on the setup form with the prompts section
    // asking for the one thing that is missing.
    it("does not start a rescan while the project has no prompts", async () => {
      fetchVisibilityQueriesMock.mockResolvedValue(promptList([]));
      useAuditFormMock.mockReturnValue(formWithTarget("https://northwind.example"));
      const handleSubmit = idleRunner();
      recordScanLaunchIntent({ projectId: 42, target: "northwind.example" });
      searchParamsState.current = new URLSearchParams("projectId=42&url=northwind.example");

      render(<AuditDashboardPage />);
      await waitFor(() => expect(fetchVisibilityQueriesMock).toHaveBeenCalled());

      expect(handleSubmit).not.toHaveBeenCalled();
      // The authority is left intact, so adding the prompt the section asks
      // for starts the run the customer already asked for.
      expect(storedIntent()).not.toBeNull();
    });
  });

  // SIGV2-1176: Jake's design makes at least one prompt mandatory to launch a
  // scan, because a project with none leaves five separate surfaces empty.
  // The gate is narrow on purpose: it may only refuse a customer who can
  // actually do something about it.
  describe("the mandatory prompt (SIGV2-1176)", () => {
    const lastProps = () =>
      auditConfigurationFormMock.mock.calls.at(-1)?.[0] as Record<string, unknown>;

    const renderWithProject = async (query = "projectId=42") => {
      searchParamsState.current = new URLSearchParams(query);
      render(<AuditDashboardPage />);
      await waitFor(() => expect(auditConfigurationFormMock).toHaveBeenCalled());
    };

    it("reads the active prompts of the project the scan names", async () => {
      await renderWithProject();
      await waitFor(() =>
        expect(fetchVisibilityQueriesMock).toHaveBeenCalledWith(
          42,
          { Authorization: "Bearer token-123" },
          false
        )
      );
      await waitFor(() => expect(lastProps().isStartDisabled).toBe(false));
      expect((lastProps().prompts as { prompts: unknown[] }).prompts).toHaveLength(1);
    });

    it("refuses the launch while the project has no prompts", async () => {
      fetchVisibilityQueriesMock.mockResolvedValue(promptList([]));
      await renderWithProject();
      await waitFor(() => expect(lastProps().isStartDisabled).toBe(true));
      expect((lastProps().prompts as { blocksLaunch: boolean }).blocksLaunch).toBe(true);
    });

    it("refuses the launch until the prompt list has actually been read", async () => {
      let release: (value: unknown) => void = () => {};
      fetchVisibilityQueriesMock.mockReturnValue(
        new Promise((resolve) => {
          release = resolve;
        })
      );
      await renderWithProject();
      // An unread list is not an empty one, but it is not a satisfied
      // requirement either: nothing may start on no evidence.
      expect(lastProps().isStartDisabled).toBe(true);
      await act(async () => {
        release(promptList([{ id: 9, query_text: "who sells the best coffee in Soho" }]));
      });
      await waitFor(() => expect(lastProps().isStartDisabled).toBe(false));
    });

    it("does not hold up a scan that has no project to read prompts for", async () => {
      // The workspace-level form finds or creates the project when the run
      // starts, so there is no list to read and nothing to attach a prompt
      // to. Blocking here would make a first-ever scan impossible.
      await renderWithProject("");
      expect(fetchVisibilityQueriesMock).not.toHaveBeenCalled();
      expect(lastProps().isStartDisabled).toBe(false);
      expect((lastProps().prompts as { projectId: number | null }).projectId).toBeNull();
    });

    it("does not hold up a scan when the prompt list cannot be read", async () => {
      fetchVisibilityQueriesMock.mockRejectedValue(new Error("monitoring is unreachable"));
      await renderWithProject();
      await waitFor(() =>
        expect((lastProps().prompts as { error: string | null }).error).toBe(
          "monitoring is unreachable"
        )
      );
      expect(lastProps().isStartDisabled).toBe(false);
    });

    it("does not hold up a scan on a plan that permits no prompts at all", async () => {
      // Every plan in the served ladder allows prompts, so this is the
      // env-override case. A requirement the customer has no way to meet must
      // not be the thing standing between them and a scan.
      fetchVisibilityQueriesMock.mockResolvedValue(
        promptList([], { is_locked: true, max_queries: 0, remaining_queries: 0 })
      );
      await renderWithProject();
      await waitFor(() =>
        expect((lastProps().prompts as { isPlanLocked: boolean }).isPlanLocked).toBe(true)
      );
      expect(lastProps().isStartDisabled).toBe(false);
    });

    it("keeps the launch open for a project at its plan cap, which has prompts by definition", async () => {
      // The cap counts active prompts, so "at the cap" implies at least one
      // prompt exists and the mandatory rule is already met. The cap then
      // only stops further additions, which the dialog states.
      fetchVisibilityQueriesMock.mockResolvedValue(
        promptList(
          Array.from({ length: 10 }, (_, index) => ({
            id: index + 1,
            query_text: `prompt ${index + 1}`,
          })),
          { remaining_queries: 0 }
        )
      );
      await renderWithProject();
      await waitFor(() => expect(lastProps().isStartDisabled).toBe(false));
      const prompts = lastProps().prompts as { canAddPrompt: boolean; hasPrompt: boolean };
      expect(prompts.hasPrompt).toBe(true);
      expect(prompts.canAddPrompt).toBe(false);
    });
  });
});
