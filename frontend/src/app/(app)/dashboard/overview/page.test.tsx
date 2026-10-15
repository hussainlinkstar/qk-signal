import React from "react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DashboardOverviewPage, { beginFirstScanLaunch } from "@/app/(app)/dashboard/overview/page";
import { useOnboardingState } from "@/hooks/useOnboardingState";
import { useTrialStatus } from "@/hooks/useTrialStatus";
import { ONBOARDING_RESUME_KEY } from "@/lib/onboardingResume";
import { SCAN_LAUNCH_INTENT_KEY } from "@/lib/scanLaunchIntent";
import { fetchUserProjects } from "@/services/auditService";
import { tEn } from "@/test/i18nEn";
import { CookieConsentProvider } from "@/contexts/CookieConsentContext";
import {
  createProjectCompetitor,
  createWorkspaceProject,
  fetchCurrentWorkspace,
  fetchWorkspaceTrendOverview,
} from "@/services/workspaceService";

const routerPush = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush, replace: vi.fn() }),
  useSearchParams: () => searchParams,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const authState: {
  isSignedIn: boolean;
  getToken: () => Promise<string>;
  user?: { id: string; email_verified: boolean; subscription_plan: string };
} = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

const billingOverview: {
  current: { current_plan: string | null; plans: { id: string; capabilities: object }[] } | null;
} = { current: null };

vi.mock("@/hooks/useBillingSettings", () => ({
  useBillingSettings: () => ({ billingOverview: billingOverview.current }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => ({ isSignedIn: false, getToken: async () => null }),
}));

vi.mock("@/contexts/RoleModeContext", () => ({
  useRoleMode: () => ({ roleMode: "marketer", setRoleMode: vi.fn() }),
}));

vi.mock("@/services/auditService", async () => {
  const actual = await vi.importActual("@/services/auditService");
  return {
    ...actual,
    fetchUserProjects: vi.fn(),
  };
});

vi.mock("@/services/workspaceService", () => ({
  fetchCurrentWorkspace: vi.fn(),
  createWorkspaceProject: vi.fn(),
  createProjectCompetitor: vi.fn(),
  fetchWorkspaceTrendOverview: vi.fn(),
}));

vi.mock("@/services/integrationService", () => ({
  fetchWorkspaceDataConnections: vi.fn(async () => []),
}));

vi.mock("@/hooks/useOnboardingState", () => ({
  useOnboardingState: vi.fn(),
}));

vi.mock("@/hooks/useTrialStatus", () => ({
  useTrialStatus: vi.fn(),
}));

const updateOnboardingStateMock = vi.fn(async () => ({
  completed_steps: [],
  started_at: null,
  dismissed_at: null,
  updated_at: null,
}));

const featureAccess = {
  monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
  automations: { allowed: true, detail: null, status_code: null, required_plan: null },
  entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
  benchmark_intelligence: { allowed: true, detail: null, status_code: null, required_plan: null },
  scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
  jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
};

// Reads come from here so a test can name the active workspace; writes stay a
// no-op, which is how this suite has always treated localStorage.
const localStorageValues: Record<string, string> = {};

describe("DashboardOverviewPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    for (const key of Object.keys(localStorageValues)) delete localStorageValues[key];
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: {
        clear: vi.fn(),
        getItem: vi.fn((key: string) => localStorageValues[key] ?? null),
        removeItem: vi.fn(),
        setItem: vi.fn(),
      },
    });
    window.sessionStorage.clear();
    searchParams = new URLSearchParams();
    billingOverview.current = null;
    delete authState.user;
    routerPush.mockReset();
    updateOnboardingStateMock.mockClear();
    vi.mocked(useOnboardingState).mockReturnValue({
      state: {
        completed_steps: [],
        started_at: null,
        dismissed_at: null,
        updated_at: null,
      },
      isLoading: false,
      error: null,
      refresh: vi.fn(),
      updateState: updateOnboardingStateMock,
    });
    vi.mocked(useTrialStatus).mockReturnValue({
      trial: {
        is_trial: false,
        trial_active: false,
        trial_expired: false,
        trial_plan: null,
        trial_started_at: null,
        trial_ends_at: null,
        days_remaining: 0,
        credits_remaining: 0,
        credits_total: 0,
        audits_used: 0,
        audits_total: 0,
        concierge_completed: false,
        limits_reached: false,
        limit_reason: null,
      },
      isLoading: false,
      refresh: vi.fn(),
      showPaywall: false,
      showConciergeOnboarding: false,
    });
    vi.mocked(fetchCurrentWorkspace).mockResolvedValue({
      id: 1,
      name: "Workspace",
      owner_id: 1,
      created_at: null,
      role: "ADMIN",
      is_owner: true,
      project_count: 1,
      member_count: 1,
      oauth_connection_count: 0,
    });
    vi.mocked(createWorkspaceProject).mockResolvedValue({
      id: 100,
      workspace_id: 1,
      name: "Created",
      domain_url: null,
      target_country: null,
      language: "en",
      icp_roles: [],
      pain_points: null,
      usp: null,
      competitors: [],
      priority_pulse_tags: [],
      sme_profiles: [],
      created_at: null,
      audit_count: 0,
      last_audit_at: null,
      latest_seo_score: null,
      latest_geo_score: null,
      latest_aeo_score: null,
      feature_access: featureAccess,
    });
    vi.mocked(fetchWorkspaceTrendOverview).mockResolvedValue({
      workspace_id: 1,
      period: "90d",
      projects: [
        {
          project_id: 42,
          name: "Test Project",
          domain_url: "https://example.com",
          last_audit_at: "2026-03-12T09:00:00Z",
          latest_scores: { seo: 80, geo: 75, aeo: 70, overall: 75 },
          delta: { seo: 0, aeo: 0, geo: 0, overall: 2.45 },
          trend_direction: { seo: "stable", aeo: "stable", geo: "stable", overall: "up" },
          sparkline: [],
        },
      ],
    });
    vi.mocked(fetchUserProjects).mockResolvedValue([
      {
        project_id: 42,
        domain: "example.com",
        display_name: "Example",
        audit_count: 3,
        latest_seo_score: null,
        latest_geo_score: 80,
        latest_aeo_score: 74,
        latest_audit_at: null,
      },
    ]);
  });

  it("keeps the project grid ahead of compact onboarding for returning workspaces", () => {
    const source = readFileSync(
      `${process.cwd()}/src/app/(app)/dashboard/overview/page.tsx`,
      "utf8"
    );

    expect(source.indexOf('<section className="space-y-[18px]">')).toBeGreaterThan(-1);
    expect(source.indexOf("{shouldShowChecklist ? (")).toBeGreaterThan(
      source.indexOf('<section className="space-y-[18px]">')
    );
  });

  it("renders the MVP workspace overview with the Add Project tile", async () => {
    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

    expect(await screen.findByRole("heading", { name: /workspace overview/i })).toBeInTheDocument();
    // The project grid always renders the dashed Add Project tile (MVP layout).
    expect(await screen.findByRole("button", { name: /add project/i })).toBeInTheDocument();
  });

  // SIGV2-1121: one or two projects do not fill the first grid row, so the
  // tile used to sit beside them. The approved mockup hides this because it
  // renders exactly three cards, which fill the row at the design viewport.
  it.each([1, 2])(
    "opens a new grid row for the Add Project tile with %i project(s)",
    async (projectCount) => {
      vi.mocked(fetchUserProjects).mockResolvedValue(
        Array.from({ length: projectCount }, (_unused, index) => ({
          project_id: 42 + index,
          domain: `example-${index}.com`,
          display_name: `Example ${index}`,
          audit_count: 3,
          latest_seo_score: 70,
          latest_geo_score: 80,
          latest_aeo_score: 74,
          latest_audit_at: null,
        }))
      );

      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

      const tile = await screen.findByRole("button", { name: /add project/i });
      const grid = tile.parentElement as HTMLElement;
      expect(grid.className).toContain("grid-cols-[repeat(auto-fill,minmax(280px,1fr))]");
      expect(grid.querySelectorAll("a[href^='/dashboard/projects/']")).toHaveLength(projectCount);

      // Add Project stays in normal grid flow (same row when space allows).
      expect(grid.lastElementChild).toBe(tile);
      expect(tile).not.toHaveClass("col-start-1");
      expect(tile.className).not.toMatch(/\bcol-span-/);
    }
  );

  it("portals the create-project modal with the shell's CSS scope hooks intact", async () => {
    render(
      <div data-signal-theme className="app-shell">
        <main>
          <CookieConsentProvider>
            <DashboardOverviewPage />
          </CookieConsentProvider>
        </main>
      </div>
    );

    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));

    const dialog = await screen.findByRole("dialog");
    const wrapper = dialog.closest(".app-shell");
    expect(wrapper?.parentElement).toBe(document.body);
    expect(wrapper?.querySelector("[data-signal-theme]")).not.toBeNull();
    expect(wrapper).toHaveClass("app-shell");

    const cancel = within(dialog).getByRole("button", { name: "Cancel" });
    const submit = within(dialog).getByRole("button", { name: "Add Project" });
    expect(cancel.tagName).toBe("BUTTON");
    expect(submit.tagName).toBe("BUTTON");
    expect(cancel.className).toContain("bg-(--panel)");
    expect(submit.className).toContain("bg-(--ink)");

    // The reporting language offers only what the product can produce.
    const language = within(dialog).getByLabelText("Reporting language");
    expect(
      within(language)
        .getAllByRole("option")
        .map((o) => o.textContent)
    ).toEqual(["English", "Arabic (العربية)"]);
  });

  it("renders the approved .modal anatomy with a single keyboard focus ring", async () => {
    render(
      <div data-signal-theme className="app-shell">
        <main>
          <CookieConsentProvider>
            <DashboardOverviewPage />
          </CookieConsentProvider>
        </main>
      </div>
    );

    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));
    const dialog = await screen.findByRole("dialog");

    // signal.css `.modal`: eyebrow, title, sub, 2-up grid, actions - and the
    // approved title is the dialog's accessible name, not a hidden "Dialog".
    expect(dialog).toHaveAccessibleName("Start Project");
    expect(within(dialog).getByText("Initialize Project")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        "Create a domain workspace and begin tracking SEO, AEO, and GEO performance."
      )
    ).toBeInTheDocument();
    expect(dialog.className).toContain("max-w-[560px]");
    expect(dialog.className).toContain("rounded-[20px]");
    expect(dialog.className).toContain("p-[28px_30px_26px]");

    // SIGV2-1201: both action buttons stay keyboard-visible, with the one
    // approved 3px --ring and no competing outline.
    for (const name of ["Cancel", "Add Project"]) {
      const button = within(dialog).getByRole("button", { name });
      expect(button.className).toContain("focus-visible:ring-[3px]");
      expect(button.className).toContain("focus-visible:ring-(--ring)");
      expect(button.className).toContain("focus-visible:outline-hidden");
      button.focus();
      expect(document.activeElement).toBe(button);
    }

    // Every field is tabbable, and the shell - not the bare control - owns
    // the focus indicator, so a mouse click paints no blue inner ring.
    const controls = [...dialog.querySelectorAll<HTMLElement>("input, select")];
    expect(controls).toHaveLength(4);
    for (const control of controls) {
      expect(control.tabIndex).toBeGreaterThanOrEqual(0);
      expect(control.parentElement).toHaveClass("input-shell");
      expect(control.parentElement?.className).toContain(
        "focus-within:shadow-[0_0_0_3px_var(--ring)]"
      );
    }
  });

  it("announces load failures and retries the project fetch", async () => {
    vi.mocked(fetchUserProjects)
      .mockRejectedValueOnce(new Error("Network failed"))
      .mockResolvedValue([]);

    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

    // The persona modal aria-hides the page; dismiss it before interacting.
    fireEvent.click(await screen.findByRole("button", { name: /set up later/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Network failed");
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(vi.mocked(fetchUserProjects)).toHaveBeenCalledTimes(2));
    // The empty project list reopens the persona modal; dismiss it again.
    fireEvent.click(await screen.findByRole("button", { name: /set up later/i }));
    expect(await screen.findByRole("button", { name: /add project/i })).toBeInTheDocument();
  });

  it("keeps the entered values and shows the error when project creation fails", async () => {
    vi.mocked(createWorkspaceProject).mockRejectedValueOnce(new Error("Domain already tracked"));

    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });
    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));

    const dialog = await screen.findByRole("dialog");
    const nameInput = within(dialog).getByLabelText("Project name");
    fireEvent.change(nameInput, { target: { value: "Acme Site" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Add Project" }));

    await waitFor(() => expect(createWorkspaceProject).toHaveBeenCalledTimes(1));
    expect(await within(dialog).findByText("Domain already tracked")).toBeInTheDocument();
    // The modal stays open and the entered data is preserved for a retry.
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect((nameInput as HTMLInputElement).value).toBe("Acme Site");
  });

  it("issues a single create call for a double submit", async () => {
    let release!: () => void;
    vi.mocked(createWorkspaceProject).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = () =>
            resolve({
              id: 101,
              workspace_id: 1,
              name: "Acme Site",
              domain_url: null,
              target_country: null,
              language: "en",
              icp_roles: [],
              pain_points: null,
              usp: null,
              competitors: [],
              priority_pulse_tags: [],
              sme_profiles: [],
              created_at: null,
              audit_count: 0,
              last_audit_at: null,
              latest_seo_score: null,
              latest_geo_score: null,
              latest_aeo_score: null,
              feature_access: featureAccess,
            });
        })
    );

    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });
    fireEvent.click(await screen.findByRole("button", { name: /add project/i }));

    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByLabelText("Project name"), {
      target: { value: "Acme Site" },
    });
    const submit = within(dialog).getByRole("button", { name: "Add Project" });
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(createWorkspaceProject).toHaveBeenCalledTimes(1));
    release();
    await waitFor(() => expect(routerPush).toHaveBeenCalledWith("/dashboard/projects/101"));
  });

  it("invalidates scoped project data when the workspace changes", async () => {
    const { WORKSPACE_CHANGE_EVENT } = await import("@/components/app/WorkspaceSwitcher");

    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });
    expect(await screen.findByText("Example")).toBeInTheDocument();
    expect(vi.mocked(fetchUserProjects)).toHaveBeenCalledTimes(1);

    vi.mocked(fetchUserProjects).mockResolvedValue([]);

    await act(async () => {
      window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGE_EVENT, { detail: { workspaceId: 2 } }));
    });

    await waitFor(() => expect(vi.mocked(fetchUserProjects)).toHaveBeenCalledTimes(2));
    // The previous workspace's card is gone as soon as the switch lands.
    expect(screen.queryByText("Example")).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // SIGV2-1220: connecting GA4 at onboarding step 4 left the app and never
  // came back to it. The callback returned to Connections, and because a
  // project now existed the page treated onboarding as finished, so the wizard
  // did not reopen at all and the remaining steps were unreachable.
  // -------------------------------------------------------------------------

  describe("the GA4 connect round trip", () => {
    const resumeRecord = () => {
      const raw = window.sessionStorage.getItem(ONBOARDING_RESUME_KEY);
      return raw === null ? null : JSON.parse(raw);
    };

    const openWizardAtGa4 = async () => {
      // No projects yet, so the wizard auto-opens at step 1.
      vi.mocked(fetchUserProjects).mockResolvedValue([]);
      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

      fireEvent.change(await screen.findByPlaceholderText("yourdomain.com"), {
        target: { value: "acme.com" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Continue" }));
      await screen.findByText("Market & reporting language");
      fireEvent.click(screen.getByRole("button", { name: "Continue" }));
      await screen.findByText("Competitors to track");
      fireEvent.click(screen.getByRole("button", { name: "Skip / Continue" }));
      await screen.findByText("Connect Google Analytics");
    };

    it("records where to come back to and names the return destination", async () => {
      localStorageValues.active_workspace_id = "7";
      const assign = vi.fn();
      Object.defineProperty(window, "location", {
        configurable: true,
        value: { href: "", assign },
      });

      await openWizardAtGa4();
      fireEvent.click(await screen.findByRole("button", { name: "Connect GA4" }));

      // The project created at step 2 and the step to resume, in this tab only.
      expect(resumeRecord()).toEqual(
        expect.objectContaining({ workspaceId: 7, projectId: 100, step: 4 })
      );
      // SIGV2-1207's workspace_id still rides along; return_to is a key, not
      // a URL, so nothing here can become a redirect target.
      expect(window.location.href).toContain(
        "/api/workspaces/current/oauth-connections/google/start"
      );
      expect(window.location.href).toContain("workspace_id=7");
      expect(window.location.href).toContain("return_to=onboarding");
    });

    it("reopens the wizard at the GA4 step after a successful return", async () => {
      localStorageValues.active_workspace_id = "7";
      window.sessionStorage.setItem(
        ONBOARDING_RESUME_KEY,
        JSON.stringify({ workspaceId: 7, projectId: 42, step: 4, createdAt: Date.now() })
      );
      searchParams = new URLSearchParams("provider=google&status=connected");

      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

      // The project exists, which used to mean "onboarding finished".
      expect(await screen.findByText("Connect Google Analytics")).toBeInTheDocument();
      expect(screen.getByText("Step 4 of 5: Google Analytics (optional)")).toBeInTheDocument();
    });

    it("keeps the setup and says what happened when the connect was refused", async () => {
      localStorageValues.active_workspace_id = "7";
      window.sessionStorage.setItem(
        ONBOARDING_RESUME_KEY,
        JSON.stringify({ workspaceId: 7, projectId: 42, step: 4, createdAt: Date.now() })
      );
      searchParams = new URLSearchParams("provider=google&status=error&message=access_denied");

      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

      expect(await screen.findByText(/did not finish connecting/)).toBeInTheDocument();
      // Still on the GA4 step, so Retry and Skip are both reachable.
      expect(screen.getByRole("button", { name: "Try connecting again" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Skip / Continue" })).toBeInTheDocument();
    });

    it("does not resume a setup recorded in a different workspace", async () => {
      localStorageValues.active_workspace_id = "9";
      window.sessionStorage.setItem(
        ONBOARDING_RESUME_KEY,
        JSON.stringify({ workspaceId: 7, projectId: 42, step: 4, createdAt: Date.now() })
      );
      searchParams = new URLSearchParams("provider=google&status=connected");

      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

      await screen.findByRole("button", { name: /add project/i });
      expect(screen.queryByText("Connect Google Analytics")).not.toBeInTheDocument();
    });

    it("forgets the context once the customer leaves the wizard", async () => {
      localStorageValues.active_workspace_id = "7";
      window.sessionStorage.setItem(
        ONBOARDING_RESUME_KEY,
        JSON.stringify({ workspaceId: 7, projectId: 42, step: 4, createdAt: Date.now() })
      );
      searchParams = new URLSearchParams("provider=google&status=connected");

      render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });
      await screen.findByText("Connect Google Analytics");

      fireEvent.click(screen.getByRole("button", { name: /set up later/i }));

      await waitFor(() => expect(resumeRecord()).toBeNull());
    });
  });

  // SIGV2-1220: the competitor step reads the entitlement the API serves, so
  // an ineligible plan is told rather than being allowed to try and refused.
  it("locks the competitor step when the served plan withholds it", async () => {
    vi.mocked(fetchUserProjects).mockResolvedValue([]);
    authState.user = { id: "1", email_verified: true, subscription_plan: "plan_executive" };
    billingOverview.current = {
      current_plan: "plan_standard",
      plans: [
        { id: "plan_standard", capabilities: { has_competitor_analysis: false } },
        { id: "plan_specialist", capabilities: { has_competitor_analysis: true } },
      ],
    };

    render(<DashboardOverviewPage />, { wrapper: CookieConsentProvider });

    fireEvent.change(await screen.findByPlaceholderText("yourdomain.com"), {
      target: { value: "acme.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByText("Market & reporting language");
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    // The served plan is the entitlement, even though the local table would
    // have granted it for the plan on the user record.
    expect(await screen.findByText("Competitor tracking is on Specialist")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "+ Add competitor" })).not.toBeInTheDocument();
    expect(createProjectCompetitor).not.toHaveBeenCalled();
  });

  // SIGV2-1159: "Run my first scan" must reach a running scan, not a second
  // setup page. The href only prefills the form, which is why it carries no
  // start flag of any kind; the authority to start is the launch intent, which
  // lives in this tab's sessionStorage where no link can reach it.
  describe("beginFirstScanLaunch", () => {
    const intent = () => {
      const raw = window.sessionStorage.getItem(SCAN_LAUNCH_INTENT_KEY);
      return raw === null ? null : JSON.parse(raw);
    };

    it("prefills from the target the wizard collected and records the intent", () => {
      const href = beginFirstScanLaunch(42, {
        url: "northwind.example",
        name: "Northwind Hotels",
      });

      expect(href).toBe(
        "/dashboard/audit?projectId=42&url=northwind.example&targetName=Northwind+Hotels"
      );
      expect(intent()).toEqual(
        expect.objectContaining({ projectId: 42, target: "northwind.example" })
      );
    });

    it("grants no authority through the href itself", () => {
      const href = beginFirstScanLaunch(42, { url: "northwind.example", name: "Northwind" });

      // Nothing in the query may act as a trigger: the whole point of the
      // intent is that a link cannot start a scan on its own.
      expect(href).not.toContain("start=");
    });

    it("falls back to the project's own domain when the wizard names no target", () => {
      const href = beginFirstScanLaunch(42, undefined, {
        domain: "northwind.example",
        display_name: "Northwind Hotels",
      });

      expect(href).toBe(
        "/dashboard/audit?projectId=42&url=northwind.example&targetName=Northwind+Hotels"
      );
      expect(intent()).toEqual(
        expect.objectContaining({ projectId: 42, target: "northwind.example" })
      );
    });

    it("records no intent when no target can be resolved", () => {
      expect(beginFirstScanLaunch(42, undefined, { domain: null, display_name: null })).toBe(
        "/dashboard/audit?projectId=42"
      );
      expect(intent()).toBeNull();
    });
  });
  // SIGV2-1307 ---------------------------------------------------------------
  // QA: "Add Project kept 'Project name is required' after the name was
  // filled, including during submit."
  //
  // `creationMessage` was only cleared once a submit got past the guard, so
  // typing a name left the complaint on screen, and the next submit showed it
  // for as long as the request took. A message that survives the thing it
  // describes teaches people to ignore validation, which costs more than the
  // one message.
  //
  // This reads the source rather than driving the form, and says so: the
  // creation form lives inside the onboarding wizard and reaching it from
  // here would test the wizard's routing more than this behaviour. What is
  // worth pinning is that the setter clears the message and that the message
  // is a named constant, so the setter cannot drift from the string it is
  // matching.
  describe("the project-name validation message", () => {
    // `new URL(..., import.meta.url)` does not survive the parentheses in
    // the (app) route group, so the path is joined from the project root the
    // way `visualLanguage.test.ts` does.
    const source = readFileSync(
      join(process.cwd(), "src/app/(app)/dashboard/overview/page.tsx"),
      "utf8"
    );

    it("is a named constant rather than a literal in two places", () => {
      expect(source).toContain("const PROJECT_NAME_REQUIRED_MESSAGE =");
      // Exactly one literal, in the constant.
      const literals = source.match(/"Project name is required\."/g) ?? [];
      expect(literals).toHaveLength(1);
    });

    it("is cleared by the name setter, not only by a later submit", () => {
      expect(source).toContain("const setProjectName = useCallback");
      expect(source).toContain(
        "current === PROJECT_NAME_REQUIRED_MESSAGE && value.trim() ? null : current"
      );
    });

    it("leaves a real failure alone", () => {
      // The setter clears only the message whose condition has gone. A
      // server error from the last attempt is still true while you retype.
      expect(source).not.toContain("setCreationMessage(null);\n    setProjectNameState");
    });
  });
});
