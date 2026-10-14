import React from "react";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/jobs",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
}));

vi.mock("@/components/admin/AdminGuardProvider", () => ({
  AdminGuardProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  useAdminAccess: () => ({ isAdmin: true, user: { email: "admin@example.test" } }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    user: { name: "Jake" },
    logout: vi.fn(),
    getToken: async () => "t",
    isSignedIn: true,
  }),
}));

vi.mock("@tanstack/react-query", () => ({
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

// The account control's module graph (react-query, workspaceService,
// WorkspaceSwitcher) is far heavier than what this nav-mapping test exercises;
// stub it and let the sidebar assertions stand alone.
vi.mock("@/components/app/SidebarWorkspaceMenu", () => ({
  default: ({ email }: { email: string }) => <div data-testid="sidebar-account-menu">{email}</div>,
}));

vi.mock("@/components/admin/AdminAlertBell", () => ({
  AdminAlertBell: () => <div data-testid="admin-alert-bell" />,
}));

// SignalAppFooter's cookie-settings button needs the consent context; the
// shell test only pins the nav mapping, so stub the hook.
vi.mock("@/contexts/CookieConsentContext", () => ({
  useCookieConsent: () => ({ openSettings: vi.fn() }),
}));

import AdminShell from "./AdminShell";

/**
 * AdminShell maps its own NavItem shape into SignalAppShell's presentation
 * type. SignalNavItem.href went optional (action items render as buttons);
 * this pins that every admin destination still renders as a real link.
 */
describe("AdminShell through the shared shell", () => {
  it("renders every mapped admin nav item as a link", () => {
    render(
      <AdminShell>
        <div>Admin content</div>
      </AdminShell>
    );

    const nav = screen.getByRole("navigation", { name: "Main navigation" });
    const expected = [
      "Dashboard",
      "Health & Status",
      "Workspaces",
      "User Management",
      "Security Logs",
      "Subscriptions",
      "Invoices & Payments",
      "Quotas & Commitments",
      "AI Spend & Usage",
      "Billing Configuration",
      "Infrastructure",
      "APM & Traces",
      "Active Alerts",
      "Model Lifecycle",
      "Claim Feedback",
      "Pricing Tiers & Features",
      "Runtime Configuration",
      "Global Settings",
      "Maintenance Mode",
      "AI Models & API Keys",
      "OAuth Clients",
      "Integration Health",
      "Email Configuration",
      "Email Footer & Social",
      "Activity Logs",
      "Data Privacy (GDPR)",
      "Data Lifecycle",
      "Job Queue",
      "Email Delivery",
      "Email Templates",
      "Audit History",
    ];
    for (const name of expected) {
      const link = within(nav).getByRole("link", { name });
      expect(link).toHaveAttribute("href", expect.stringMatching(/^\/admin\//));
    }
    // The current route keeps its active marker through the mapping.
    expect(within(nav).getByRole("link", { name: "Job Queue" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(within(nav).queryByRole("button", { name: "Job Queue" })).not.toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: /trial/i })).not.toBeInTheDocument();
  });
});
