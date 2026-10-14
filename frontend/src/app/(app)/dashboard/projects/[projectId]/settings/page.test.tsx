import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectSettingsPage from "@/app/(app)/dashboard/projects/[projectId]/settings/page";
import { tEn } from "@/test/i18nEn";
import {
  createProjectMagicLink,
  deleteProjectBudget,
  deleteProjectById,
  deleteProjectDataSource,
  fetchProjectBudget,
  fetchProjectById,
  fetchProjectDataSourceCatalog,
  fetchProjectDataSources,
  fetchProjectMagicLinkStatus,
  generateProjectSmartProfile,
  upsertProjectBudget,
  upsertProjectDataSource,
  updateProjectById,
} from "@/services/workspaceService";

const pushMock = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
  useRouter: () => ({ push: pushMock }),
}));

const authState = {
  isLoading: false,
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/components/settings/ProjectCompetitorManager", () => ({
  ProjectCompetitorManager: () => <div>Competitor manager</div>,
  default: () => <div>Competitor manager</div>,
}));

vi.mock("@/services/workspaceService", () => ({
  createProjectMagicLink: vi.fn(),
  deleteProjectBudget: vi.fn(),
  deleteProjectById: vi.fn(),
  deleteProjectDataSource: vi.fn(),
  fetchProjectBudget: vi.fn(),
  fetchProjectById: vi.fn(),
  fetchProjectDataSourceCatalog: vi.fn(),
  fetchProjectDataSources: vi.fn(),
  fetchProjectMagicLinkStatus: vi.fn(),
  generateProjectSmartProfile: vi.fn(),
  upsertProjectBudget: vi.fn(),
  upsertProjectDataSource: vi.fn(),
  updateProjectById: vi.fn(),
}));

const baseProject = {
  id: 42,
  workspace_id: 1,
  name: "Client Project",
  domain_url: "https://client.example",
  target_country: "RO",
  language: "en",
  icp_roles: ["CEO"],
  pain_points: "Low visibility",
  usp: "Strong delivery speed",
  competitors: ["https://comp-one.example"],
  priority_pulse_tags: ["GEO"],
  sme_profiles: ["https://linkedin.com/in/expert"],
  created_at: null,
  audit_count: 0,
  last_audit_at: null,
  latest_seo_score: null,
  latest_geo_score: null,
  latest_aeo_score: null,
  feature_access: {
    monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
    automations: { allowed: true, detail: null, status_code: null, required_plan: null },
    entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
    benchmark_intelligence: { allowed: true, detail: null, status_code: null, required_plan: null },
    scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
    jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
  },
};

const baseAssignments = [
  {
    id: 101,
    project_id: 42,
    provider: "google" as const,
    source_type: "google_search_console" as const,
    binding_mode: "workspace" as const,
    source_id: "sc-domain:client.example",
    source_label: "Client GSC",
    is_active: true,
    oauth_connection_id: 11,
    project_oauth_connection_id: null,
    workspace_provider_connected: true,
    updated_at: null,
  },
  {
    id: null,
    project_id: 42,
    provider: "google" as const,
    source_type: "google_analytics_4" as const,
    binding_mode: "workspace" as const,
    source_id: null,
    source_label: null,
    is_active: false,
    oauth_connection_id: 11,
    project_oauth_connection_id: null,
    workspace_provider_connected: true,
    updated_at: null,
  },
  {
    id: null,
    project_id: 42,
    provider: "bing" as const,
    source_type: "bing_webmaster" as const,
    binding_mode: "workspace" as const,
    source_id: null,
    source_label: null,
    is_active: false,
    oauth_connection_id: 21,
    project_oauth_connection_id: null,
    workspace_provider_connected: true,
    updated_at: null,
  },
];

const pendingMagicLinkStatus = {
  project_id: 42,
  status: "pending" as const,
  latest_link_created_at: "2026-02-24T08:00:00.000Z",
  latest_link_expires_at: "2026-02-27T08:00:00.000Z",
  latest_link_is_used: false,
  open_magic_link_count: 1,
  providers: [
    {
      provider: "google" as const,
      connected: false,
      connected_at: null,
      connected_by_email: null,
      has_refresh_token: false,
      expires_at: null,
      scope: null,
    },
    {
      provider: "bing" as const,
      connected: false,
      connected_at: null,
      connected_by_email: null,
      has_refresh_token: false,
      expires_at: null,
      scope: null,
    },
  ],
};

const connectedMagicLinkStatus = {
  ...pendingMagicLinkStatus,
  status: "connected" as const,
  providers: [
    {
      provider: "google" as const,
      connected: true,
      connected_at: "2026-02-24T08:05:00.000Z",
      connected_by_email: "client-owner@example.com",
      has_refresh_token: true,
      expires_at: null,
      scope:
        "openid email profile https://www.googleapis.com/auth/webmasters.readonly https://www.googleapis.com/auth/analytics.readonly",
    },
    pendingMagicLinkStatus.providers[1],
  ],
};

const baseBudget = {
  project_id: 42,
  workspace_id: 1,
  project_name: "Client Project",
  domain_url: "https://client.example",
  budget_configured: true,
  monthly_limit_scans: 5000,
  cycle_anchor_day: 1,
  current_period_start: "2026-03-01",
  current_period_end: "2026-04-01",
  consumed_scans: 1200,
  remaining_scans: 3800,
  percent_consumed: 24,
  status: "healthy" as const,
  warning_threshold_reached: false,
  limit_reached: false,
  recent_periods: [
    {
      period_start: "2026-02-01",
      period_end: "2026-03-01",
      cycle_anchor_day: 1,
      budget_limit_scans: 5000,
      consumed_scans: 4100,
      remaining_scans: 900,
      percent_consumed: 82,
      warning_threshold_reached: true,
      limit_reached: false,
      status: "warning" as const,
    },
  ],
};

describe("ProjectSettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    pushMock.mockReset();
    window.scrollTo = vi.fn();

    authState.isLoading = false;
    authState.isSignedIn = true;
    authState.getToken = vi.fn(async () => "token-123");

    vi.mocked(fetchProjectById).mockResolvedValue(baseProject);
    vi.mocked(fetchProjectBudget).mockResolvedValue(baseBudget);
    vi.mocked(fetchProjectDataSources).mockResolvedValue(baseAssignments);
    vi.mocked(fetchProjectDataSourceCatalog).mockImplementation(async (_projectId, sourceType) => {
      if (sourceType === "google_search_console") {
        return {
          source_type: sourceType,
          provider: "google",
          workspace_provider_connected: true,
          items: [
            {
              id: "sc-domain:client.example",
              label: "sc-domain:client.example",
              description: "siteOwner",
            },
          ],
          required_scopes: ["https://www.googleapis.com/auth/webmasters.readonly"],
          granted_scopes: ["gsc.read"],
          missing_scopes: [],
          error: null,
          fetched_at: "2026-02-24T08:00:00.000Z",
        };
      }
      if (sourceType === "google_analytics_4") {
        return {
          source_type: sourceType,
          provider: "google",
          workspace_provider_connected: true,
          items: [{ id: "properties/12345", label: "Client GA4", description: null }],
          required_scopes: ["https://www.googleapis.com/auth/analytics.readonly"],
          granted_scopes: ["ga4.read"],
          missing_scopes: [],
          error: null,
          fetched_at: "2026-02-24T08:00:00.000Z",
        };
      }
      return {
        source_type: sourceType,
        provider: "bing",
        workspace_provider_connected: true,
        items: [
          {
            id: "https://client.example/",
            label: "https://client.example/",
            description: "siteOwner",
          },
        ],
        required_scopes: ["offline_access"],
        granted_scopes: ["offline_access"],
        missing_scopes: [],
        error: null,
        fetched_at: "2026-02-24T08:00:00.000Z",
      };
    });
    vi.mocked(fetchProjectMagicLinkStatus).mockResolvedValue(pendingMagicLinkStatus);
    vi.mocked(deleteProjectById).mockResolvedValue();
    vi.mocked(deleteProjectBudget).mockResolvedValue({
      ...baseBudget,
      budget_configured: false,
      monthly_limit_scans: null,
      remaining_scans: null,
      percent_consumed: null,
      status: "unlimited",
    });
    vi.mocked(upsertProjectBudget).mockResolvedValue({
      ...baseBudget,
      monthly_limit_scans: 6000,
      remaining_scans: 4800,
      percent_consumed: 20,
    });
    vi.mocked(upsertProjectDataSource).mockResolvedValue(baseAssignments[0]);
    vi.mocked(deleteProjectDataSource).mockResolvedValue();
    vi.mocked(updateProjectById).mockResolvedValue(baseProject);
    vi.mocked(generateProjectSmartProfile).mockResolvedValue({
      project: baseProject,
      model: null,
      required_fields: ["name", "domain_url", "target_country", "language"],
      missing_required_fields: [],
      generated_fields: [],
      skipped_fields: [],
      grounded_sources: ["project_profile_fields"],
    });
    vi.mocked(createProjectMagicLink).mockResolvedValue({
      project_id: 42,
      token: "magic-token-42",
      link_url: "https://thothgraph.com/connect/magic-token-42",
      expires_at: "2026-02-27T08:00:00.000Z",
      is_used: false,
      created_at: null,
    });
  });

  it("opens with the designed Product Settings order and honest targets", async () => {
    render(<ProjectSettingsPage />);

    const panel = await screen.findByRole("tabpanel");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Settings");
    expect(screen.getByRole("tab", { name: "Product Settings" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(panel).toHaveAttribute("aria-labelledby", "signal-tab-product");
    expect(Array.from(panel.querySelectorAll("h3")).map((node) => node.textContent)).toEqual([
      "Score targets",
      "Tracked competitors",
      "Tracked prompts",
      "Connected data",
      "Monitoring",
    ]);
    expect(
      await within(panel).findByRole("button", { name: /add competitor/i })
    ).toBeInTheDocument();

    // The monitoring summary does not exist in the product, so it carries the
    // SOON treatment: no button (dead or otherwise) and no upsell language
    // borrowed from the plan gates. Tracked prompts DO exist, so they are no
    // longer in this list (SIGV2-1114). Score targets are real: the project
    // PATCH persists aio_score_target / seo_score_target.
    const soonSections = Array.from(panel.querySelectorAll('[data-testid="soon-section"]'));
    expect(soonSections.map((node) => node.getAttribute("aria-label"))).toEqual([
      "Monitoring summary, coming soon",
    ]);
    soonSections.forEach((node) => {
      expect(node).toHaveTextContent("SOON");
      expect(node.querySelector("button, a")).toBeNull();
    });
    expect(panel).not.toHaveTextContent("Configure score targets");
  });

  it("routes tracked prompts to the Prompts tab instead of claiming it is unbuilt", async () => {
    render(<ProjectSettingsPage />);

    const panel = await screen.findByRole("tabpanel");
    // The feature ships on the AIO detail page, so settings must not say it is
    // not built (SIGV2-1114).
    expect(panel).not.toHaveTextContent("Choosing your own questions is not built yet");
    const link = within(panel).getByRole("link", { name: "Open tracked prompts" });
    expect(link).toHaveAttribute("href", "/dashboard/projects/42/ai-answers?tab=prompts");
  });

  it("keeps the danger zone last in the Brand Settings order", async () => {
    render(<ProjectSettingsPage />);

    const brandTab = await screen.findByRole("tab", { name: "Brand Settings" });
    fireEvent.click(brandTab);
    await waitFor(() => expect(brandTab).toHaveAttribute("aria-selected", "true"));

    const panel = screen.getByRole("tabpanel");
    expect(panel).toHaveAttribute("aria-labelledby", "signal-tab-brand");
    const headings = Array.from(panel.querySelectorAll("h3")).map((node) => node.textContent);

    expect(headings[0]).toBe("Node Settings");
    expect(headings.at(-1)).toBe("Delete Project · Danger zone");
    expect(headings.indexOf("Budget Guardrails")).toBeGreaterThan(0);
    expect(headings.indexOf("Monitoring Alerts")).toBeGreaterThan(
      headings.indexOf("Budget Guardrails")
    );
  });

  it("supports source assignment save and magic link lifecycle refresh", async () => {
    vi.mocked(fetchProjectMagicLinkStatus)
      .mockResolvedValueOnce(pendingMagicLinkStatus)
      .mockResolvedValue(connectedMagicLinkStatus);

    render(<ProjectSettingsPage />);

    await waitFor(() => {
      expect(fetchProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });

    expect(await screen.findByText("Connected data")).toBeInTheDocument();
    expect(screen.queryByText("External Handshake Protocols")).not.toBeInTheDocument();
    expect(screen.queryByText("Commit Mapping")).not.toBeInTheDocument();
    expect(screen.queryByText("Generate Secure Link")).not.toBeInTheDocument();

    // SIGV2-1169: the binding controls sit behind each row's action, so the
    // panel has to be opened before the row can be saved.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Manage Search Console" })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole("button", { name: "Choose a Google Analytics property" }));
    fireEvent.click(screen.getByRole("button", { name: "Manage Search Console" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save Search Console" })).not.toBeDisabled();
    });

    fireEvent.click(screen.getByRole("button", { name: "Save Google Analytics" }));

    await waitFor(() => {
      expect(upsertProjectDataSource).toHaveBeenCalledWith(
        "42",
        "google_analytics_4",
        expect.objectContaining({
          binding_mode: "workspace",
          source_id: "properties/12345",
          source_label: "Client GA4",
          // Choosing a property and saving it means the user wants it used:
          // a new binding must persist active, not silently inactive.
          is_active: true,
        }),
        { Authorization: "Bearer token-123" }
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Save Search Console" }));

    await waitFor(() => {
      expect(upsertProjectDataSource).toHaveBeenCalledWith(
        "42",
        "google_search_console",
        expect.objectContaining({
          binding_mode: "workspace",
          source_id: "sc-domain:client.example",
          source_label: "Client GSC",
          is_active: true,
        }),
        { Authorization: "Bearer token-123" }
      );
    });

    expect(await screen.findByText("Search Console saved.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Create access link/i }));

    await waitFor(() => {
      expect(createProjectMagicLink).toHaveBeenCalledWith("42", 72, {
        Authorization: "Bearer token-123",
      });
    });
    expect(
      await screen.findByText("https://thothgraph.com/connect/magic-token-42")
    ).toBeInTheDocument();
    expect(await screen.findByText("Access link created.")).toBeInTheDocument();
    expect(screen.queryByText(/Token:/)).not.toBeInTheDocument();

    await waitFor(() => {
      expect(vi.mocked(fetchProjectMagicLinkStatus).mock.calls.length).toBeGreaterThanOrEqual(2);
    });
    expect((await screen.findAllByText("Connected")).length).toBeGreaterThan(0);
  }, 10_000);

  it("shows a visible error when generating a handshake link fails", async () => {
    vi.mocked(createProjectMagicLink).mockRejectedValueOnce(
      new Error("Handshake provider is temporarily unavailable.")
    );

    render(<ProjectSettingsPage />);

    await waitFor(() => {
      expect(fetchProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });

    const generateButton = await screen.findByRole("button", {
      name: /Create access link/i,
    });
    fireEvent.click(generateButton);

    await waitFor(() => {
      expect(createProjectMagicLink).toHaveBeenCalledWith("42", 72, {
        Authorization: "Bearer token-123",
      });
    });

    expect(
      await screen.findByText("Handshake provider is temporarily unavailable.")
    ).toBeInTheDocument();
    expect(screen.queryByText(/thothgraph\.com\/connect/)).not.toBeInTheDocument();
  });

  it("renders Connected data rows in the approved .conn anatomy", async () => {
    render(<ProjectSettingsPage />);
    await screen.findByText("Connected data");

    // Google Analytics row: approved mono descriptor, and an action rather
    // than a prose status while the property is unbound.
    const gaRow = screen.getByText("Google Analytics").closest("div.flex")!;
    expect(gaRow.className).toContain("items-center");
    expect(gaRow.className).toContain("gap-3");
    expect(gaRow.className).toContain("py-3");
    expect(within(gaRow as HTMLElement).getByText("Traffic and AI referrals")).toBeTruthy();

    // A bound+active source carries the approved badge-ok pill, with the
    // approved row names (Search Console, not Google Search Console).
    const gscRow = screen.getByText("Search Console").closest("div.flex")!;
    const badge = within(gscRow as HTMLElement).getByText("Connected");
    expect(badge.className).toContain("rounded-[999px]");
    expect(badge.className).toContain("bg-(--good-s)");

    // SIGV2-1169: no "sources in use" counter, and the binding controls stay
    // hidden until a row's action opens them.
    expect(screen.queryByText(/sources in use/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save Google Analytics" })).not.toBeInTheDocument();

    // The Google grant is already held at workspace level (Khuzaima's report):
    // the row must not tell him to connect an account again - the step left is
    // choosing which account this project uses.
    expect(
      within(gaRow as HTMLElement).getByRole("button", {
        name: "Choose a Google Analytics property",
      })
    ).toBeInTheDocument();
    expect(
      within(gaRow as HTMLElement).queryByRole("button", { name: /Connect Google Analytics/ })
    ).not.toBeInTheDocument();
  });

  it("opens a row's binding panel through its row action only", async () => {
    render(<ProjectSettingsPage />);
    await screen.findByText("Connected data");

    const choose = await screen.findByRole("button", {
      name: "Choose a Google Analytics property",
    });
    expect(choose).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("google_analytics_4-panel")).not.toBeInTheDocument();

    fireEvent.click(choose);

    expect(choose).toHaveAttribute("aria-expanded", "true");
    const panel = document.getElementById("google_analytics_4-panel")!;
    expect(panel).toBeInTheDocument();
    // Every capability stays reachable inside the disclosure: binding mode,
    // account picker, manual entry, use/save/remove and refresh.
    expect(within(panel).getByLabelText("Data source")).toBeInTheDocument();
    expect(within(panel).getByLabelText("GA4 property")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Enter property ID")).toBeInTheDocument();
    expect(within(panel).getByLabelText("Use for this project")).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Refresh Google Analytics accounts" })
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Save Google Analytics" })
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: "Remove Google Analytics" })
    ).toBeInTheDocument();
  });

  it("offers the account connection step when the workspace grant is missing", async () => {
    vi.mocked(fetchProjectDataSources).mockResolvedValue([
      {
        ...baseAssignments[1],
        workspace_provider_connected: false,
      },
    ]);
    vi.mocked(fetchProjectDataSourceCatalog).mockResolvedValue({
      source_type: "google_analytics_4",
      provider: "google",
      workspace_provider_connected: false,
      items: [],
      required_scopes: [],
      granted_scopes: [],
      missing_scopes: [],
      error: "workspace_provider_not_connected",
      fetched_at: "2026-02-24T08:00:00.000Z",
    } as never);

    render(<ProjectSettingsPage />);
    await screen.findByText("Connected data");

    // The Google account itself is not connected, so the row action is the
    // account connection step (SIGV2-1169), opening the row's panel.
    const connect = await screen.findByRole("button", {
      name: "Connect Google Analytics",
    });
    fireEvent.click(connect);

    const panel = await waitFor(() => document.getElementById("google_analytics_4-panel")!);
    expect(panel).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Manage connections" })).toHaveAttribute(
      "href",
      "/dashboard/connections"
    );
    // The client-shared-access mode is still reachable without a grant.
    expect(within(panel).getByLabelText("Data source")).toBeInTheDocument();
  });

  it("scrolls the Connected data card into view for a #data-sources hash", async () => {
    window.location.hash = "#data-sources";
    const scrollSpy = vi
      .spyOn(HTMLElement.prototype, "scrollIntoView")
      .mockImplementation(() => {});
    try {
      render(<ProjectSettingsPage />);
      await screen.findByText("Connected data");
      await waitFor(() => expect(scrollSpy).toHaveBeenCalled());
      const section = document.getElementById("data-sources")!;
      expect(section.tabIndex).toBe(-1);
    } finally {
      scrollSpy.mockRestore();
      window.location.hash = "";
    }
  });

  it("styles the handshake block with the approved sub-block vocabulary", async () => {
    render(<ProjectSettingsPage />);
    const heading = await screen.findByText("Ask the client for access");
    expect(heading.className).toContain("text-[13.5px]");
    expect(heading.className).toContain("font-semibold");
    const description = screen.getByText(
      "Request access to the client's Google or Bing data without sharing your own login."
    );
    expect(description.className).toContain("text-[12px]");
    expect(description.className).toContain("leading-[1.45]");
    const chip = await screen.findByText("Waiting on the client");
    expect(chip.className).toContain("uppercase");
    expect(chip.className).toContain("font-mono");
    expect(chip.className).toContain("text-(--purple-deep)");
  });

  it("saves and removes project budget guardrails", async () => {
    render(<ProjectSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "Brand Settings" }));
    expect(await screen.findByText("Budget Guardrails")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Monthly Scan Cap"), {
      target: { value: "6000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save Cap" }));

    await waitFor(() => {
      expect(upsertProjectBudget).toHaveBeenCalledWith(
        1,
        "42",
        {
          monthly_limit_scans: 6000,
          cycle_anchor_day: 1,
        },
        { Authorization: "Bearer token-123" }
      );
    });
    expect(await screen.findByText("Project budget guardrail saved.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove Cap" }));

    await waitFor(() => {
      expect(deleteProjectBudget).toHaveBeenCalledWith(1, "42", {
        Authorization: "Bearer token-123",
      });
    });
    expect(
      await screen.findByText("Project budget guardrail removed. This project is now unlimited.")
    ).toBeInTheDocument();
  }, 10_000);

  it("treats a blank scan cap as removing the cap", async () => {
    render(<ProjectSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "Brand Settings" }));
    expect(await screen.findByText("Budget Guardrails")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Monthly Scan Cap"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save Cap" }));

    await waitFor(() => {
      expect(deleteProjectBudget).toHaveBeenCalledWith(1, "42", {
        Authorization: "Bearer token-123",
      });
    });
    expect(upsertProjectBudget).not.toHaveBeenCalled();
  }, 10_000);

  it("launches a Smart audit for the current project from the grounded-update modal", async () => {
    render(<ProjectSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "Brand Settings" }));
    const generateButton = await screen.findByRole("button", { name: "Generate via AI" });
    await waitFor(() => expect(generateButton).not.toBeDisabled());
    fireEvent.click(generateButton);

    fireEvent.click(await screen.findByRole("button", { name: /Run Smart Audit/i }));

    expect(pushMock).toHaveBeenCalledWith("/dashboard/audit?projectId=42&tier=smart&tab=overview");
  });

  it("shows signed-out guardrails and skips protected API calls", async () => {
    authState.isSignedIn = false;
    authState.getToken = vi.fn(async () => null);

    render(<ProjectSettingsPage />);

    expect(
      await screen.findByText("Sign in to manage project data source mappings.")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Brand Settings" }));
    expect(await screen.findByText("Sign in to manage project settings.")).toBeInTheDocument();
    expect(fetchProjectById).not.toHaveBeenCalled();
  });

  it("deletes project after name confirmation and redirects to workspace", async () => {
    render(<ProjectSettingsPage />);

    await waitFor(() => {
      expect(fetchProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });

    fireEvent.click(await screen.findByRole("tab", { name: "Brand Settings" }));
    const confirmInput = await screen.findByPlaceholderText("Project Name...");
    fireEvent.change(confirmInput, { target: { value: "Client Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete Project" }));

    await waitFor(() => {
      expect(deleteProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });
    expect(pushMock).toHaveBeenCalledWith("/dashboard");
  });

  it("shows a visible error when project deletion fails", async () => {
    vi.mocked(deleteProjectById).mockRejectedValueOnce(
      new Error("Project has active audits and cannot be deleted.")
    );

    render(<ProjectSettingsPage />);

    await waitFor(() => {
      expect(fetchProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });

    fireEvent.click(await screen.findByRole("tab", { name: "Brand Settings" }));
    const confirmInput = await screen.findByPlaceholderText("Project Name...");
    fireEvent.change(confirmInput, { target: { value: "Client Project" } });
    fireEvent.click(screen.getByRole("button", { name: "Delete Project" }));

    await waitFor(() => {
      expect(deleteProjectById).toHaveBeenCalledWith("42", {
        Authorization: "Bearer token-123",
      });
    });

    expect(
      await screen.findByText("Project has active audits and cannot be deleted.")
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalledWith("/dashboard");
  });
});
