import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalShell from "@/components/portal/PortalShell";
import type { PortalBranding } from "@/services/portalService";

const pushMock = vi.fn();
const logoutMock = vi.fn(async () => undefined);
const useAuthMock = vi.fn(() => ({
  logout: logoutMock,
  user: { email: "client@example.com" },
  isLoading: false,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/portal",
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => useAuthMock(),
}));

const baseBranding: PortalBranding = {
  workspace_id: 7,
  workspace_name: "Northwind Workspace",
  agency_name: "Northwind Agency",
  custom_logo_url: null,
  primary_color: "#FF4D2D",
  secondary_color: "#14B8A6",
  custom_favicon_url: null,
  custom_page_title: null,
  hide_powered_by: false,
};

describe("PortalShell", () => {
  beforeEach(() => {
    pushMock.mockReset();
    logoutMock.mockClear();
    useAuthMock.mockReset();
    useAuthMock.mockReturnValue({
      logout: logoutMock,
      user: { email: "client@example.com" },
      isLoading: false,
    });
    document.title = "Qiko Signal";
  });

  it("keeps platform attribution visible when hide_powered_by is false", () => {
    render(
      <PortalShell branding={baseBranding} projects={[]}>
        <div>Portal body</div>
      </PortalShell>
    );

    expect(screen.getByText("Client Portal")).toBeInTheDocument();
    expect(screen.getByText(/Powered by Qiko Signal/i)).toBeInTheDocument();
  });

  it("switches to white-label copy and document title when hide_powered_by is true", async () => {
    render(
      <PortalShell
        branding={{ ...baseBranding, agency_name: null, hide_powered_by: true }}
        projects={[]}
      >
        <div>Portal body</div>
      </PortalShell>
    );

    expect(screen.getByText("White-label portal")).toBeInTheDocument();
    expect(screen.queryByText(/Powered by Qiko Signal/i)).not.toBeInTheDocument();

    await waitFor(() => {
      expect(document.title).toBe("Northwind Workspace");
    });
  });

  // SIGNAL-1006: portal pages fell back to the root layout's generic marketing
  // title whenever the workspace had neither a custom_page_title nor
  // hide_powered_by set, which is the common (non-white-label) case.
  it("sets a portal-specific document title even without custom branding", async () => {
    render(
      <PortalShell branding={baseBranding} projects={[]}>
        <div>Portal body</div>
      </PortalShell>
    );

    await waitFor(() => {
      expect(document.title).toBe("Northwind Workspace - Client Portal");
    });
  });

  // SIGNAL-1006: the sidebar showed the placeholder "Portal user" instead of
  // a loading state while auth was still resolving, which looked like a real
  // (wrong) identity rather than a transient loading state.
  it("shows a loading state instead of the 'Portal user' placeholder while auth is resolving", () => {
    useAuthMock.mockReturnValue({ logout: logoutMock, user: null, isLoading: true });

    render(
      <PortalShell branding={baseBranding} projects={[]}>
        <div>Portal body</div>
      </PortalShell>
    );

    expect(screen.queryByText("Portal user")).not.toBeInTheDocument();
  });

  it("falls back to 'Portal user' once loading finishes with no user", () => {
    useAuthMock.mockReturnValue({ logout: logoutMock, user: null, isLoading: false });

    render(
      <PortalShell branding={baseBranding} projects={[]}>
        <div>Portal body</div>
      </PortalShell>
    );

    expect(screen.getByText("Portal user")).toBeInTheDocument();
  });
});
