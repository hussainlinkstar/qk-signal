import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import WorkspaceSettingsPage from "@/app/(app)/dashboard/settings/page";
import { tEn } from "@/test/i18nEn";
import { fetchApiKeys } from "@/services/apiKeyService";
import {
  fetchWorkspaceWhiteLabelSettings,
  fetchWorkspaceProjects,
  fetchCurrentWorkspace,
  fetchWorkspaceCostBreakdown,
  fetchWorkspaceMembers,
  inviteWorkspaceClient,
} from "@/services/workspaceService";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isLoading: false,
  isSignedIn: true,
  user: {
    id: "1",
    email: "owner@example.com",
    name: "Owner Example",
    subscription_plan: "plan_executive",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
  useUser: () => ({
    user: {
      id: "1",
      email: "owner@example.com",
      name: "Owner Example",
    },
  }),
}));

vi.mock("@/components/settings/ApiKeysSection", () => ({
  ApiKeysSection: () => <div>API Keys</div>,
  default: () => <div>API Keys</div>,
}));

vi.mock("@/components/app/RoleModeSwitcher", () => ({
  __esModule: true,
  default: () => null,
}));

vi.mock("@/components/app/WorkspaceSwitcher", () => ({
  workspaceHeaders: vi.fn(() => ({})),
  getActiveWorkspaceId: vi.fn(() => 1),
  setActiveWorkspaceId: vi.fn(),
}));

vi.mock("@/components/app/CreateWorkspaceModal", () => ({
  CreateWorkspaceModal: () => null,
  UpgradeToMultiWorkspaceModal: () => null,
}));

vi.mock("@/components/app/InviteToMultipleWorkspacesModal", () => ({
  __esModule: true,
  default: () => null,
}));

// The page resolves entitlement from the served /api/billing/plans payload and
// falls back to the plan table only until it arrives. These tests exercise the
// fallback deliberately (there is no plans payload here), so the assertions
// below pin what `subscription_plan` resolves to.
vi.mock("@/hooks/useBillingSettings", () => ({
  useBillingSettings: () => ({ billingOverview: null }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchCurrentWorkspace: vi.fn(),
  fetchWorkspaceCostBreakdown: vi.fn(),
  fetchWorkspaceMembers: vi.fn(),
  fetchWorkspaceProjects: vi.fn(),
  fetchWorkspaceWhiteLabelSettings: vi.fn(),
  fetchUserWorkspaces: vi.fn().mockResolvedValue([]),
  addWorkspaceMember: vi.fn(),
  createWorkspaceCustomDomain: vi.fn(),
  deleteWorkspace: vi.fn(),
  deleteWorkspaceCustomDomain: vi.fn(),
  inviteWorkspaceClient: vi.fn(),
  removeWorkspaceMember: vi.fn(),
  updateCurrentWorkspace: vi.fn(),
  updateWorkspaceWhiteLabelSettings: vi.fn(),
  updateWorkspaceMemberRole: vi.fn(),
  verifyWorkspaceCustomDomain: vi.fn(),
}));

vi.mock("@/services/apiKeyService", () => ({
  fetchApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
}));

describe("WorkspaceSettingsPage", () => {
  beforeEach(() => {
    // Call counts leak between tests otherwise: only getToken used to be
    // cleared, so an assertion about a service NOT being called saw the
    // previous test's call.
    vi.clearAllMocks();
    authState.getToken.mockResolvedValue("token-123");
    authState.user.subscription_plan = "plan_executive";

    const featureAccess = {
      monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
      automations: { allowed: true, detail: null, status_code: null, required_plan: null },
      entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
      benchmark_intelligence: {
        allowed: true,
        detail: null,
        status_code: null,
        required_plan: null,
      },
      scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
      jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
    };

    vi.mocked(fetchCurrentWorkspace).mockResolvedValue({
      id: 1,
      name: "Agency Workspace",
      owner_id: 1,
      created_at: null,
      role: "ADMIN",
      is_owner: true,
      project_count: 4,
      member_count: 2,
      oauth_connection_count: 1,
    });
    vi.mocked(fetchWorkspaceMembers).mockResolvedValue([
      {
        user_id: 1,
        email: "owner@example.com",
        role: "ADMIN",
        is_owner: true,
        created_at: null,
      },
    ]);
    vi.mocked(fetchWorkspaceProjects).mockResolvedValue([
      {
        id: 11,
        workspace_id: 1,
        name: "Acme Project",
        domain_url: "https://acme.example",
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
      },
    ]);
    vi.mocked(fetchWorkspaceCostBreakdown).mockResolvedValue({
      workspace_id: 1,
      generated_at: "2026-03-02T10:00:00.000Z",
      projects: [
        {
          project_id: 11,
          workspace_id: 1,
          project_name: "Acme Project",
          domain_url: "https://acme.example",
          budget_configured: true,
          monthly_limit_scans: 3000,
          cycle_anchor_day: 1,
          current_period_start: "2026-03-01",
          current_period_end: "2026-04-01",
          consumed_scans: 1800,
          remaining_scans: 1200,
          percent_consumed: 60,
          status: "healthy",
          warning_threshold_reached: false,
          limit_reached: false,
          recent_periods: [],
        },
      ],
    });
    vi.mocked(fetchWorkspaceWhiteLabelSettings).mockResolvedValue({
      workspace_id: 1,
      workspace_name: "Agency Workspace",
      company_name: "Agency Workspace",
      custom_logo_url: "https://cdn.example.com/logo.svg",
      primary_color: "#FF4D2D",
      secondary_color: "#14B8A6",
      custom_favicon_url: "https://cdn.example.com/favicon.png",
      custom_page_title: "Agency Workspace Portal",
      custom_meta_description: "Branded agency workspace.",
      hide_powered_by: false,
      email_sender_name: "Agency Ops",
      email_reply_to: "ops@agency.example",
      social_facebook_url: null,
      social_x_url: "https://x.com/agency",
      social_instagram_url: null,
      social_linkedin_url: "https://linkedin.com/company/agency",
      social_youtube_url: null,
      social_tiktok_url: null,
      company_address: "42 Agency Street\nBucharest",
      company_legal_name: "Agency SRL",
      company_trademark_text: "Agency is a trademark of Agency SRL.",
      footer_about_url: "https://agency.example/about",
      footer_blog_url: "https://agency.example/blog",
      footer_support_url: "https://agency.example/support",
      footer_legal_url: "https://agency.example/legal",
      footer_preferences_url: "https://agency.example/preferences",
      footer_privacy_url: "https://agency.example/privacy",
      dns_target: "custom.example",
      domains: [
        {
          id: 9,
          domain: "audit.agency.example",
          dns_target: "custom.example",
          verified: true,
          ssl_status: "active",
          verification_error: null,
          verification_checked_at: "2026-03-03T12:00:00.000Z",
          activated_at: "2026-03-03T12:01:00.000Z",
          created_at: "2026-03-03T11:55:00.000Z",
          preview_url: "https://audit.agency.example",
        },
      ],
    });
    vi.mocked(inviteWorkspaceClient).mockResolvedValue({
      user_id: 7,
      email: "client@example.com",
      role: "CLIENT_READONLY",
      project_ids: [11],
      invited: true,
      created_at: null,
      email_queued: false,
      invitation_url: "https://localhost:3000/reset-password?token=manual-token",
    });
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_specialist",
      api_access_enabled: true,
      mcp_access_enabled: true,
      developer_hub_url: "/dashboard/developer",
    });
  });

  it("renders clear workspace and team labels", async () => {
    render(<WorkspaceSettingsPage />);

    await screen.findByText("Workspace Identity");

    expect(screen.getByText("Workspace name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Team/ }));

    expect(screen.getByText(/Team Roster/)).toBeInTheDocument();
    expect(screen.getByText("Invite Team Member")).toBeInTheDocument();
    expect(screen.getAllByText("Role").length).toBeGreaterThan(0);
    expect(screen.getByText("ADMIN · Owner")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: /Client Access/ }));

    expect(screen.getByRole("heading", { name: /Invite Client/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /invite client/i })).toBeInTheDocument();

    const developerTab = screen.getByRole("tab", { name: "Developer" });
    fireEvent.click(developerTab);
    const developerPanel = screen.getByRole("tabpanel", { name: "Developer" });
    expect(developerTab).toHaveAttribute("aria-controls", developerPanel.id);
    expect(developerPanel).toHaveAttribute("aria-labelledby", developerTab.id);

    expect(screen.getByText("Project Cost Breakdown")).toBeInTheDocument();
    expect(screen.getByText("API Keys")).toBeInTheDocument();

    expect(screen.queryByText("Management Matrix")).not.toBeInTheDocument();
    expect(screen.queryByText("Workspace Global Identifier")).not.toBeInTheDocument();
    expect(screen.queryByText("Authorized Personas")).not.toBeInTheDocument();
    expect(screen.queryByText("Node Persona")).not.toBeInTheDocument();
  }, 10_000);

  it("submits a client portal invitation from workspace settings", async () => {
    render(<WorkspaceSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: /Client Access/ }));
    await screen.findByRole("heading", { name: /Invite Client/ });

    fireEvent.change(screen.getByPlaceholderText("client@brand.com"), {
      target: { value: "client@example.com" },
    });
    fireEvent.change(screen.getByPlaceholderText("Jane Client"), {
      target: { value: "Acme Stakeholder" },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: /acme project/i }));
    fireEvent.click(screen.getByRole("button", { name: /invite client/i }));

    await waitFor(() => {
      expect(inviteWorkspaceClient).toHaveBeenCalledWith(
        1,
        {
          email: "client@example.com",
          name: "Acme Stakeholder",
          project_ids: [11],
        },
        { Authorization: "Bearer token-123" }
      );
    });

    expect(await screen.findByText("client@example.com")).toBeInTheDocument();
    expect(await screen.findByText("CLIENT_READONLY")).toBeInTheDocument();
    expect(await screen.findByText("Manual onboarding link")).toBeInTheDocument();
    expect(
      await screen.findByText("https://localhost:3000/reset-password?token=manual-token")
    ).toBeInTheDocument();
  }, 10_000);

  it("loads workspace cost breakdown data", async () => {
    render(<WorkspaceSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "Developer" }));
    expect(await screen.findByText("Project Cost Breakdown")).toBeInTheDocument();

    await waitFor(() => {
      expect(fetchWorkspaceCostBreakdown).toHaveBeenCalledWith(1, {
        Authorization: "Bearer token-123",
      });
    });

    expect(screen.getByText("Caps Active")).toBeInTheDocument();
    expect(screen.getAllByText("Acme Project").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("3,000")).toBeInTheDocument();
    expect(screen.getByText("1,800")).toBeInTheDocument();
  });

  it("keeps the Developer tab discoverable when API actions are plan locked", async () => {
    authState.user.subscription_plan = "plan_starter";
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_starter",
      api_access_enabled: false,
      mcp_access_enabled: false,
      developer_hub_url: "/dashboard/developer",
    });

    render(<WorkspaceSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "Developer" }));
    expect(await screen.findByText("API Keys")).toBeInTheDocument();
  });

  // SIGV2-1039. This used to assert the opposite: that the White-Label tab must
  // be absent "because the capability is False on every plan". That premise was
  // read off the frontend plan table, which disagreed with the backend.
  // `CAPABILITY_MATRIX` in backend/app/config/plans.py grants has_white_label on
  // plan_executive, every endpoint behind the tab is implemented in
  // workspace_router.py, and SIGV2-1026 confirmed it production-ready. So on an
  // entitled plan the approved section must be present and must work.
  it("offers the approved White-Label tab, wired, on an entitled plan", async () => {
    authState.user.subscription_plan = "plan_executive";

    render(<WorkspaceSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "White-Label" }));

    expect(await screen.findByText("Tenant Status")).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchWorkspaceWhiteLabelSettings).toHaveBeenCalled();
    });

    // Every approved sub-section is present, and each is bound to a field the
    // white-label endpoint actually persists.
    expect(screen.getByText("Brand Identity")).toBeInTheDocument();
    expect(screen.getByText("Brand Colors")).toBeInTheDocument();
    expect(screen.getByText("Email Sender")).toBeInTheDocument();
    expect(screen.getByText("Social Links")).toBeInTheDocument();
    expect(screen.getByText("Footer & Legal")).toBeInTheDocument();
    expect(screen.getByText("Custom Domain")).toBeInTheDocument();
    expect(screen.getByText("Deployment Checklist")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save White-Label Settings" })).toBeInTheDocument();

    // Loaded values are shown, not blanks, and the real DNS target is used.
    expect(screen.getByDisplayValue("Agency Workspace Portal")).toBeInTheDocument();
    expect(screen.getByDisplayValue("#FF4D2D")).toBeInTheDocument();
    // The verified domain is the live custom hostname in Tenant Status and the
    // row in Custom Domain, so it legitimately appears twice.
    expect(screen.getAllByText("audit.agency.example").length).toBe(2);
    expect(screen.getByText("Live with a valid certificate")).toBeInTheDocument();
  }, 10_000);

  it("states the plan position instead of rendering dead white-label controls", async () => {
    // Every endpoint behind the tab answers 402 below Executive, so an editable
    // field here would be a control that cannot act.
    authState.user.subscription_plan = "plan_standard";

    render(<WorkspaceSettingsPage />);

    fireEvent.click(await screen.findByRole("tab", { name: "White-Label" }));

    expect(await screen.findByText("White-label branding requires Executive")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save White-Label Settings" })
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Brand Identity")).not.toBeInTheDocument();
    expect(fetchWorkspaceWhiteLabelSettings).not.toHaveBeenCalled();
  });

  it("routes multiple workspaces to sales, not to an upgrade button", async () => {
    // The approved design is explicit: "Multiple workspaces require a custom
    // plan arranged with sales", Add Workspace disabled, Contact Sales primary.
    authState.user.subscription_plan = "plan_standard";

    render(<WorkspaceSettingsPage />);

    await screen.findByText("Multiple workspaces require a custom plan arranged with sales.");
    expect(screen.getByRole("button", { name: "Add Workspace" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Contact Sales" })).toHaveAttribute(
      "href",
      expect.stringContaining("mailto:")
    );
    expect(screen.queryByRole("button", { name: "View Plans" })).not.toBeInTheDocument();
  });

  // The approved page has no Connections block: workspace integrations live on
  // their own /dashboard/connections route. Until SIGV2-1265 that route had no
  // way in, so the panel stays absent but the link does not.
  it("keeps workspace connections off the approved General panel", async () => {
    render(<WorkspaceSettingsPage />);

    await screen.findByText("Workspace Identity");
    expect(screen.queryByText("Workspace Connections")).not.toBeInTheDocument();
    expect(screen.queryByText(/Google Analytics/)).not.toBeInTheDocument();
  });

  it("links the General panel to the connections page", async () => {
    render(<WorkspaceSettingsPage />);

    await screen.findByText("Workspace Identity");
    expect(screen.getByRole("link", { name: /manage workspace connections/i })).toHaveAttribute(
      "href",
      "/dashboard/connections"
    );
  });
  // SIGV2-1311 ---------------------------------------------------------------
  // QA, logged as a blocker: "When Team Roster was 0, no Invite action was
  // shown. After the owner appeared (Team 1), Invite Team Member appeared."
  //
  // The whole load sat in one try, so a failure anywhere left `workspace` null
  // and `members` empty, and the page rendered that as fact: a roster of zero
  // with no Invite control, because `canManage` reads a role nobody had
  // loaded. A workspace always has at least its owner, so a roster of zero is
  // not a reachable state, and the only signal that anything had failed was a
  // toast that disappears.
  it("says the settings could not be read instead of drawing an empty workspace", async () => {
    vi.mocked(fetchCurrentWorkspace).mockRejectedValue(new Error("Upstream unavailable"));

    render(<WorkspaceSettingsPage />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Workspace settings could not be loaded");
    expect(alert.textContent).toContain("Upstream unavailable");

    // And none of the confident empty state: no roster of zero, and no
    // statement about what the customer may or may not do.
    expect(screen.queryByText(/No internal team members found/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
  });
});
