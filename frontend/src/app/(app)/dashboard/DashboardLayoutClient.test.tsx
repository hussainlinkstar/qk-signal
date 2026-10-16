import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardLayoutClient from "./DashboardLayoutClient";
import { useRegisterProjectScope } from "@/components/dashboard/projectScope";
import { WORKSPACE_CHANGE_EVENT } from "@/components/app/WorkspaceSwitcher";
import "@/i18n";

const authState = {
  isSignedIn: true,
  isLoading: false,
  getToken: vi.fn(async () => "token-123"),
};

let pathnameState = "/dashboard";
let searchParamsState = new URLSearchParams();
const localStorageValues = new Map<string, string>();
const localStorageMock = {
  get length() {
    return localStorageValues.size;
  },
  clear: () => localStorageValues.clear(),
  getItem: (key: string) => localStorageValues.get(key) ?? null,
  key: (index: number) => Array.from(localStorageValues.keys())[index] ?? null,
  removeItem: (key: string) => localStorageValues.delete(key),
  setItem: (key: string, value: string) => localStorageValues.set(key, value),
} satisfies Storage;

const resolveRequestUrl = (input: RequestInfo | URL) =>
  typeof input === "string" ? input : input instanceof Request ? input.url : input.toString();

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/contexts/RoleModeContext", () => ({
  useRoleMode: () => ({ roleMode: "agency" }),
}));

const routerMock = vi.hoisted(() => ({ push: vi.fn(), refresh: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState,
  useRouter: () => routerMock,
  useSearchParams: () => searchParamsState,
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/app/SidebarWorkspaceMenu", () => ({
  default: ({
    projectScope = false,
    activeProjectId = null,
  }: {
    projectScope?: boolean;
    activeProjectId?: string | null;
  }) => (
    <div
      data-testid="sidebar-switcher"
      data-project-scope={String(projectScope)}
      data-active-project-id={activeProjectId ?? ""}
    >
      Workspace Menu Stub
    </div>
  ),
}));

const openCookieSettings = vi.fn();
vi.mock("@/contexts/CookieConsentContext", () => ({
  useCookieConsent: () => ({ openSettings: openCookieSettings }),
}));

vi.mock("@/components/navigation/navItemStyles", () => ({
  getNavItemClassName: () => "nav-item",
}));

const buildSummary = (overrides?: Partial<Record<string, unknown>>) => ({
  id: 42,
  email: "owner@example.com",
  role: "user",
  included_audits_30d: 1000,
  remaining_included_audits_30d: 996,
  audits_run_30d: 4,
  subscription: {
    plan_type: "plan_executive",
    status: "active",
    current_period_end: null,
    cancel_at_period_end: false,
  },
  capabilities: {},
  ...overrides,
});

const buildBranding = (overrides?: Partial<Record<string, unknown>>) => ({
  workspace_id: 1,
  workspace_name: "Agency Workspace",
  company_name: "Agency Workspace",
  custom_logo_url: null,
  primary_color: "#FF4D2D",
  secondary_color: "#14B8A6",
  custom_favicon_url: null,
  custom_page_title: "Agency Workspace",
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
  dns_target: "custom.example",
  domains: [],
  ...overrides,
});

const featureAccess = {
  monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
  automations: { allowed: true, detail: null, status_code: null, required_plan: null },
  entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
  benchmark_intelligence: { allowed: true, detail: null, status_code: null, required_plan: null },
  scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
  jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
};

const mockDashboardFetch = ({
  summary = buildSummary(),
  branding = buildBranding(),
  project,
  projects = [],
}: {
  summary?: Record<string, unknown>;
  branding?: Record<string, unknown>;
  project?: Record<string, unknown>;
  projects?: Record<string, unknown>[];
} = {}) =>
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = resolveRequestUrl(input);

    if (url === "/api/users/me") {
      return new Response(JSON.stringify(summary), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url === "/api/workspaces/current/white-label") {
      return new Response(JSON.stringify(branding), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    if (url === "/api/workspaces/current/projects") {
      return Response.json(projects);
    }

    if (url === "/api/projects/3" && project) {
      return new Response(JSON.stringify(project), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }

    return new Response("Not Found", { status: 404 });
  });

describe("DashboardLayoutClient", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    pathnameState = "/dashboard";
    searchParamsState = new URLSearchParams();
    authState.getToken.mockClear();
    routerMock.push.mockClear();
    routerMock.refresh.mockClear();
    openCookieSettings.mockClear();
    document.title = "Default Title";
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the project read-only in the top bar; switching lives in the sidebar", async () => {
    pathnameState = "/dashboard/projects/3";
    const project = {
      id: 3,
      name: "Example site",
      domain_url: "https://example.com",
      feature_access: featureAccess,
    };
    mockDashboardFetch({ project, projects: [project] });
    render(
      <DashboardLayoutClient>
        <div>Site content</div>
      </DashboardLayoutClient>
    );

    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    await screen.findByText("example.com");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("renders the approved project IA with SOON entries announced and Sign out as an action", async () => {
    pathnameState = "/dashboard/projects/3";
    const project = {
      id: 3,
      name: "Example site",
      domain_url: "https://example.com",
      feature_access: featureAccess,
    };
    mockDashboardFetch({ project, projects: [project] });
    render(
      <DashboardLayoutClient>
        <div>Site content</div>
      </DashboardLayoutClient>
    );

    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    for (const label of ["Intelligence", "Automation", "Account"]) {
      expect(nav).toHaveTextContent(label);
    }
    for (const name of [
      "Dashboard",
      "AIO score",
      "SEO score",
      "Competitors",
      "Entities",
      "Tasks",
      "Settings",
    ]) {
      expect(nav).toHaveTextContent(name);
    }
    for (const soonName of ["Entities", "Tasks"]) {
      const soon = within(nav).getByTitle(soonName);
      expect(soon).toHaveAttribute("aria-disabled", "true");
      // SOON entries claim no link role and carry no route.
      expect(soon).not.toHaveAttribute("role");
      expect(soon).not.toHaveAttribute("href");
    }
    // Fixes is deliberately not a sidebar entry; Components is the mockup's
    // internal catalogue and never appears in the customer IA.
    expect(within(nav).queryByText("Fixes")).not.toBeInTheDocument();
    expect(within(nav).queryByText("Components")).not.toBeInTheDocument();
    expect(within(nav).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("renders the approved workspace IA on workspace routes", async () => {
    mockDashboardFetch();
    render(
      <DashboardLayoutClient>
        <div>Workspace content</div>
      </DashboardLayoutClient>
    );

    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    for (const name of [
      "Overview",
      "Workspace settings",
      "My profile",
      "Billing",
      "Developer Hub",
    ]) {
      expect(await within(nav).findByRole("link", { name })).toBeInTheDocument();
    }
    expect(within(nav).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });

  it("renders the approved page footer after main and opens the real consent settings", async () => {
    mockDashboardFetch();
    render(
      <DashboardLayoutClient>
        <div>Workspace content</div>
      </DashboardLayoutClient>
    );

    const footer = await screen.findByRole("contentinfo");
    expect(footer.compareDocumentPosition(screen.getByRole("main")) & 2).toBeTruthy();
    expect(screen.getByRole("main").parentElement).toHaveClass("min-h-[calc(100dvh-2rem)]");
    for (const label of ["Terms", "Privacy", "Cookies"]) {
      expect(within(footer).getByRole("link", { name: label })).toHaveAttribute("target", "_blank");
    }
    fireEvent.click(within(footer).getByRole("button", { name: "Cookie settings" }));
    expect(openCookieSettings).toHaveBeenCalledTimes(1);
  });

  it("opens the shell palette on ⌘K with the authorised destinations, navigates on Enter", async () => {
    pathnameState = "/dashboard/projects/3";
    const project = {
      id: 3,
      name: "Example site",
      domain_url: "https://example.com",
      feature_access: featureAccess,
    };
    mockDashboardFetch({ project, projects: [project] });
    render(
      <DashboardLayoutClient>
        <div>Site content</div>
      </DashboardLayoutClient>
    );

    // The top-bar affordance and ⌘K open the same palette.
    const input = await screen.findByRole("combobox");
    fireEvent.focus(input);
    const dialog = await screen.findByRole("listbox");
    for (const name of ["Dashboard", "AIO score", "SEO score", "Competitors", "Settings"]) {
      expect(within(dialog).getByRole("option", { name })).toBeInTheDocument();
    }
    // Non-navigating and unapproved entries are never reachable here.
    for (const name of ["Entities", "Tasks", "Fixes", "Components"]) {
      expect(within(dialog).queryByRole("option", { name })).not.toBeInTheDocument();
    }
    fireEvent.keyDown(input, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("listbox")).not.toBeInTheDocument());

    fireEvent.keyDown(document, { key: "k", metaKey: true });
    await screen.findByRole("listbox");
    fireEvent.change(input, { target: { value: "compet" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(routerMock.push).toHaveBeenCalledWith("/dashboard/projects/3/competitors");
  });

  it("offers the real cookie-settings action inside the palette", async () => {
    mockDashboardFetch();
    render(
      <DashboardLayoutClient>
        <div>Workspace content</div>
      </DashboardLayoutClient>
    );

    fireEvent.keyDown(document, { key: "k", metaKey: true });
    const dialog = await screen.findByRole("listbox");
    fireEvent.click(within(dialog).getByRole("option", { name: "Cookie preferences" }));
    expect(openCookieSettings).toHaveBeenCalledTimes(1);
  });

  it("caps and centers only the workspace dashboard shell", async () => {
    mockDashboardFetch();

    render(
      <DashboardLayoutClient>
        <div>Workspace content</div>
      </DashboardLayoutClient>
    );

    await screen.findByText("Workspace content");
    // Full-bleed flat shell — no outer stage padding or floating radius.
    expect(screen.getByTestId("signal-app-shell").firstElementChild).toHaveClass(
      "flex",
      "min-h-dvh",
      "w-full"
    );
    expect(screen.getByTestId("signal-app-shell").firstElementChild).not.toHaveClass(
      "my-3",
      "rounded-[28px]"
    );
    expect(screen.getByTestId("workspace-dashboard-gutter")).toHaveClass(
      "min-h-screen",
      "bg-[#F7F8FA]"
    );
  });

  it("reloads shared and page consumers when the active workspace changes", async () => {
    const fetchMock = mockDashboardFetch();
    const childMounted = vi.fn();

    function WorkspaceConsumer() {
      React.useEffect(() => {
        childMounted();
      }, []);
      return <div>Workspace consumer</div>;
    }

    render(
      <DashboardLayoutClient>
        <WorkspaceConsumer />
      </DashboardLayoutClient>
    );

    await waitFor(() => expect(childMounted).toHaveBeenCalledTimes(1));
    await act(async () => {
      window.dispatchEvent(new CustomEvent(WORKSPACE_CHANGE_EVENT, { detail: { workspaceId: 2 } }));
    });

    await waitFor(() => expect(childMounted).toHaveBeenCalledTimes(2));
    await waitFor(() => {
      const summaryCalls = fetchMock.mock.calls.filter(
        ([input]) => resolveRequestUrl(input as RequestInfo | URL) === "/api/users/me"
      );
      expect(summaryCalls).toHaveLength(2);
    });
  });

  it("applies workspace branding colors, custom page title, and powered-by visibility", async () => {
    mockDashboardFetch({
      branding: buildBranding({
        workspace_name: "Acme Ops",
        company_name: "Acme Signals",
        custom_page_title: "Acme Command Center",
        primary_color: "#00F2FF",
        secondary_color: "#1D4ED8",
        hide_powered_by: true,
      }),
    });

    render(
      <DashboardLayoutClient>
        <div>Workspace content</div>
      </DashboardLayoutClient>
    );

    await screen.findAllByText("Acme Signals");

    const shell = document.querySelector("[data-workspace-dashboard-shell='true']");
    expect(shell?.getAttribute("style")).toContain("--primary: #00F2FF");
    expect(shell?.getAttribute("style")).toContain("--accent: #1D4ED8");

    await waitFor(() => {
      expect(document.title).toBe("Workspace Overview | Acme Command Center");
    });

    expect(screen.queryByText(/Powered by Qiko Signal/i)).not.toBeInTheDocument();
  });

  it("reserves mobile bottom space and scroll padding for the fixed chat launcher", async () => {
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      writable: true,
      value: 390,
    });
    window.dispatchEvent(new Event("resize"));
    mockDashboardFetch();

    render(
      <DashboardLayoutClient>
        <button type="button">Last page control</button>
      </DashboardLayoutClient>
    );

    const main = await screen.findByRole("main");
    expect(main).toHaveClass("pb-24", "scroll-pb-24", "md:pb-4", "md:scroll-pb-8");
  });

  it("shows project name in project context instead of raw project id", async () => {
    pathnameState = "/dashboard/projects/3/overview";
    mockDashboardFetch({
      project: {
        id: 3,
        workspace_id: 1,
        name: "Auchan",
        domain_url: "https://www.auchan.ro",
        target_country: "RO",
        language: "ro",
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
      },
    });

    render(
      <DashboardLayoutClient>
        <div>Project content</div>
      </DashboardLayoutClient>
    );

    expect(await screen.findByText("auchan.ro")).toBeInTheDocument();
    expect(screen.queryByText(/^3$/)).not.toBeInTheDocument();
  });

  // SIGV2-1180. A scan, its history and its report live at /dashboard/audit,
  // outside the project segment, so reaching them from inside a project used
  // to replace that project's menu with the workspace one.
  describe("sidebar scope on a project's scan, history and report", () => {
    const project = {
      id: 3,
      name: "Example site",
      domain_url: "https://example.com",
      feature_access: featureAccess,
    };

    const expectProjectMenu = async () => {
      const nav = screen.getByRole("navigation", { name: "Main navigation" });
      expect(await within(nav).findByRole("link", { name: "Dashboard" })).toHaveAttribute(
        "href",
        "/dashboard/projects/3"
      );
      expect(within(nav).getByRole("link", { name: "AIO score" })).toHaveAttribute(
        "href",
        "/dashboard/projects/3/ai-answers"
      );
      expect(within(nav).getByRole("link", { name: "SEO score" })).toHaveAttribute(
        "href",
        "/dashboard/projects/3/google"
      );
      expect(within(nav).getByRole("link", { name: "Settings" })).toHaveAttribute(
        "href",
        "/dashboard/projects/3/settings"
      );
      // The workspace-only entries are not what this scope renders.
      for (const workspaceOnly of ["Workspace settings", "Developer Hub", "My profile"]) {
        expect(within(nav).queryByRole("link", { name: workspaceOnly })).not.toBeInTheDocument();
      }
      const switcher = screen.getByTestId("sidebar-switcher");
      expect(switcher).toHaveAttribute("data-project-scope", "true");
      expect(switcher).toHaveAttribute("data-active-project-id", "3");
    };

    const expectWorkspaceMenu = async () => {
      const nav = screen.getByRole("navigation", { name: "Main navigation" });
      expect(await within(nav).findByRole("link", { name: "Overview" })).toHaveAttribute(
        "href",
        "/dashboard"
      );
      expect(within(nav).getByRole("link", { name: "Developer Hub" })).toBeInTheDocument();
      expect(within(nav).queryByRole("link", { name: "AIO score" })).not.toBeInTheDocument();
      const switcher = screen.getByTestId("sidebar-switcher");
      expect(switcher).toHaveAttribute("data-project-scope", "false");
      expect(switcher).toHaveAttribute("data-active-project-id", "");
    };

    it("keeps the project menu on that project's scan page", async () => {
      pathnameState = "/dashboard/audit";
      searchParamsState = new URLSearchParams("projectId=3&tab=overview");
      mockDashboardFetch({ project, projects: [project] });

      render(
        <DashboardLayoutClient>
          <div>Scan content</div>
        </DashboardLayoutClient>
      );

      await expectProjectMenu();
    });

    it("keeps the project menu on that project's scan history", async () => {
      pathnameState = "/dashboard/audit";
      searchParamsState = new URLSearchParams("projectId=3&tab=history");
      mockDashboardFetch({ project, projects: [project] });

      render(
        <DashboardLayoutClient>
          <div>History content</div>
        </DashboardLayoutClient>
      );

      await expectProjectMenu();
    });

    it("keeps the project menu on a report that registers the audit's project", async () => {
      pathnameState = "/dashboard/audit/55";
      mockDashboardFetch({ project, projects: [project] });

      function Report() {
        useRegisterProjectScope(3);
        return <div>Report content</div>;
      }

      render(
        <DashboardLayoutClient>
          <Report />
        </DashboardLayoutClient>
      );

      await screen.findByText("Report content");
      await expectProjectMenu();
    });

    it("keeps the workspace menu on the workspace-level scan form", async () => {
      pathnameState = "/dashboard/audit";
      mockDashboardFetch({ project, projects: [project] });

      render(
        <DashboardLayoutClient>
          <div>Scan content</div>
        </DashboardLayoutClient>
      );

      await expectWorkspaceMenu();
    });

    it("keeps the workspace menu on a report with no project behind it", async () => {
      pathnameState = "/dashboard/audit/55";
      mockDashboardFetch({ project, projects: [project] });

      function Report() {
        useRegisterProjectScope(null);
        return <div>Report content</div>;
      }

      render(
        <DashboardLayoutClient>
          <Report />
        </DashboardLayoutClient>
      );

      await screen.findByText("Report content");
      await expectWorkspaceMenu();
    });

    it("resolves no project scope from a projectId that is not a project id", async () => {
      pathnameState = "/dashboard/audit";
      searchParamsState = new URLSearchParams("projectId=../../admin/users");
      mockDashboardFetch({ project, projects: [project] });

      render(
        <DashboardLayoutClient>
          <div>Scan content</div>
        </DashboardLayoutClient>
      );

      await expectWorkspaceMenu();
    });

    it("leaves a workspace route workspace-scoped whatever it carries in the query", async () => {
      pathnameState = "/dashboard/settings";
      searchParamsState = new URLSearchParams("projectId=3");
      mockDashboardFetch({ project, projects: [project] });

      render(
        <DashboardLayoutClient>
          <div>Workspace settings content</div>
        </DashboardLayoutClient>
      );

      await expectWorkspaceMenu();
    });
  });
});
