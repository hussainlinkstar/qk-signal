import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DeveloperHubPage from "@/app/(app)/dashboard/developer/page";
import { fetchApiKeys } from "@/services/apiKeyService";

const pathnameState = {
  pathname: "/dashboard/developer",
};

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState.pathname,
}));

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isLoading: false,
  isSignedIn: true,
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/apiKeyService", () => ({
  fetchApiKeys: vi.fn(),
}));

describe("DeveloperHubPage", () => {
  beforeEach(() => {
    authState.getToken.mockClear();
    pathnameState.pathname = "/dashboard/developer";
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_specialist",
      api_access_enabled: true,
      mcp_access_enabled: true,
      developer_hub_url: "/dashboard/developer",
    });
  });

  it("uses the shared accessible tabs contract for developer sections", async () => {
    render(<DeveloperHubPage />);
    await screen.findByRole("heading", { name: /developer hub/i });

    const tablist = screen.getByRole("tablist");
    const hubTab = within(tablist).getByRole("tab", { name: "Hub" });
    const hubPanel = screen.getByRole("tabpanel", { name: "Hub" });

    expect(hubTab).toHaveAttribute("aria-selected", "true");
    expect(hubTab).toHaveAttribute("aria-controls", hubPanel.id);
    expect(hubPanel).toHaveAttribute("aria-labelledby", hubTab.id);

    fireEvent.click(within(tablist).getByRole("tab", { name: "Quick Start" }));
    const quickStartTab = within(tablist).getByRole("tab", { name: "Quick Start" });
    const quickStartPanel = screen.getByRole("tabpanel", { name: "Quick Start" });

    expect(quickStartTab).toHaveAttribute("aria-selected", "true");
    expect(quickStartTab).toHaveAttribute("aria-controls", quickStartPanel.id);
    expect(quickStartPanel).toHaveAttribute("aria-labelledby", quickStartTab.id);
  });

  it("renders the headless API reference and delivery notes", async () => {
    render(<DeveloperHubPage />);

    expect(await screen.findByRole("heading", { name: /developer hub/i })).toBeInTheDocument();
    expect(screen.getByText("API Access")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Manage API Keys" })).toHaveAttribute(
      "href",
      "/dashboard/settings"
    );

    fireEvent.click(screen.getByRole("tab", { name: "Quick Start" }));
    expect(screen.getByRole("heading", { name: "Quick Start" })).toBeInTheDocument();
    expect(screen.getByText("Starter Request")).toBeInTheDocument();
    expect(
      screen.getByText(/https:\/\/qiko\.ai\/signal\/api\/v1\/external\/audit/)
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "API Reference" }));
    expect(screen.getByText("Webhook Delivery")).toBeInTheDocument();
    expect(screen.getByText("Key Endpoints")).toBeInTheDocument();
    expect(screen.getByText("/api/v1/external/audit")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Full Docs" })).toHaveAttribute(
      "href",
      "/dashboard/developer/docs"
    );
  });

  it("renders canonical Executive API access as enabled without a lock card", async () => {
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_executive",
      api_access_enabled: true,
      mcp_access_enabled: true,
      developer_hub_url: "/dashboard/developer",
    });

    render(<DeveloperHubPage />);

    expect(await screen.findByText("Enabled")).toBeInTheDocument();
    expect(screen.getByText("Executive")).toBeInTheDocument();
    expect(screen.getByText("300 req/min")).toBeInTheDocument();
    expect(screen.queryByText("API Access Locked")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /upgrade for api access/i })).not.toBeInTheDocument();
  });

  it("shows upgrade guidance when the current plan lacks API access", async () => {
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_standard",
      api_access_enabled: false,
      mcp_access_enabled: false,
      developer_hub_url: "/dashboard/developer",
    });

    render(<DeveloperHubPage />);

    expect(await screen.findByText("API Access Locked")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upgrade for api access/i })).toHaveAttribute(
      "href",
      "/dashboard/billing"
    );

    // SIGV2-1310: it names what is locked and what is not.
    //
    // QA read the page as contradicting itself, because the Hub said the API
    // was locked while the same page still offered Download JSON. Both are
    // true and both are deliberate: the download is a product feature on
    // every plan, kept that way on purpose so moving it to this page did not
    // silently take it from plans that had it. Specialist buys keys and
    // calling the API yourself.
    const notice = screen.getByText(/available on Specialist and above/i);
    expect(notice.textContent).toContain("Creating API keys");
    expect(notice.textContent).toMatch(/JSON stays available on your current plan/i);
  });

  it("renders the MCP setup tab with endpoint, client configs and tool catalogue", async () => {
    render(<DeveloperHubPage />);
    await screen.findByRole("heading", { name: /developer hub/i });

    fireEvent.click(screen.getByRole("tab", { name: "MCP Setup" }));

    expect(screen.getByRole("heading", { name: "MCP Server" })).toBeInTheDocument();
    expect(screen.getAllByText(/https:\/\/qiko\.ai\/signal\/api\/v1\/mcp/).length).toBeGreaterThan(
      0
    );
    expect(screen.getByRole("heading", { name: "Connect a Client" })).toBeInTheDocument();
    expect(screen.getAllByText(/"mcpServers"/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/mcp_stdio_bridge\.py/).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { name: "Tool Catalogue" })).toBeInTheDocument();
    expect(screen.getAllByText("signal_run_audit").length).toBeGreaterThan(0);
    expect(screen.getByText("signal_list_projects")).toBeInTheDocument();
    expect(screen.queryByText("The MCP server requires Specialist")).not.toBeInTheDocument();
  });

  it("shows the MCP lock when the plan lacks the entitlement", async () => {
    vi.mocked(fetchApiKeys).mockResolvedValue({
      items: [],
      plan_type: "plan_standard",
      api_access_enabled: false,
      mcp_access_enabled: false,
      developer_hub_url: "/dashboard/developer",
    });

    render(<DeveloperHubPage />);
    await screen.findByRole("heading", { name: /developer hub/i });

    fireEvent.click(screen.getByRole("tab", { name: "MCP Setup" }));

    expect(await screen.findByText("The MCP server requires Specialist")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /upgrade to specialist/i })).toHaveAttribute(
      "href",
      "/dashboard/billing"
    );
  });
});
