import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConnectionsPage from "@/app/(app)/dashboard/connections/page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(""),
}));

const authState = {
  getToken: vi.fn(async () => "token-123"),
  isLoading: false,
  isSignedIn: true,
};

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

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

describe("ConnectionsPage", () => {
  beforeEach(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: localStorageMock,
    });
    authState.getToken.mockClear();
    window.localStorage.clear();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }

      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(
          JSON.stringify([
            {
              provider: "google",
              connected: true,
              configured: true,
              has_refresh_token: true,
              token_type: "Bearer",
              scope: "analytics.readonly",
              expires_at: null,
              updated_at: null,
              access_token_preview: "tok_1234",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      if (input === "/api/workspaces/current/projects") {
        return new Response(
          JSON.stringify([
            {
              id: 101,
              workspace_id: 1,
              name: "Client Project",
              domain_url: "https://client.example.com",
              target_country: "US",
              language: "en",
              icp_roles: [],
              pain_points: null,
              usp: null,
              competitors: [],
              priority_pulse_tags: [],
              sme_profiles: [],
              created_at: null,
              audit_count: 3,
              last_audit_at: null,
              latest_seo_score: null,
              latest_geo_score: null,
              latest_aeo_score: null,
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      if (input === "/api/projects/101/cms/connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      if (input === "/api/integrations/slack/status") {
        return new Response(
          JSON.stringify({
            is_connected: true,
            team_id: "T123",
            team_name: "Ops HQ",
            bot_user_id: "B123",
            default_channel_id: "C123",
            default_channel_name: "seo-alerts",
            scope: "chat:write channels:read",
            updated_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      if (input === "/api/integrations/slack/channels") {
        return new Response(
          JSON.stringify([
            { id: "C123", name: "seo-alerts" },
            { id: "C456", name: "delivery" },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      if (input === "/api/integrations/teams/status") {
        return new Response(
          JSON.stringify({
            is_connected: false,
            channel_name: null,
            webhook_preview: null,
            updated_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      throw new Error(`Unexpected fetch call: ${input}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the workspace connections card and hides the non-MVP sections", async () => {
    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    // CMS Fix Delivery and AI Bot Log Analyzer have no analogue in the
    // approved MVP design; both sections are flag-hidden by default.
    expect(screen.queryByRole("heading", { name: "CMS Fix Delivery" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI Bot Log Analyzer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /open bot log analyzer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /monitoring hub/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
  });

  // Stranding guard: a workspace that already pushed CMS credentials must
  // still see and remove them even though the section is flag-hidden.
  it("still renders an existing CMS connection row when the section is hidden", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(
          JSON.stringify([
            {
              id: 101,
              workspace_id: 1,
              name: "Client Project",
              domain_url: "https://client.example.com",
              target_country: "US",
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
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/projects/101/cms/connections") {
        return new Response(
          JSON.stringify([
            {
              id: 55,
              project_id: 101,
              workspace_id: 1,
              cms_type: "wordpress",
              site_url: "https://client.example.com",
              status: "verified",
              last_verified_at: "2026-01-01T00:00:00Z",
              schema_version: "1.0",
              created_at: null,
              updated_at: null,
              credentials_preview: {},
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    // The card survives because one connector has a live connection; the
    // connector with none stays hidden.
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: "CMS Fix Delivery" })).toBeInTheDocument();
    });
    expect(screen.getByText("WordPress")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
    expect(screen.queryByText("Shopify")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up/i })).not.toBeInTheDocument();
  });

  // SIGV2-1207: the OAuth start is a browser redirect, so it cannot carry the
  // X-Workspace-Id header. The active workspace must ride as a query parameter
  // or the backend binds the connection to the user's oldest workspace.
  it("carries the active workspace id on the OAuth start URL", async () => {
    window.localStorage.setItem("active_workspace_id", "42");
    const originalLocation = window.location;
    const navigated: string[] = [];
    Object.defineProperty(window, "location", {
      configurable: true,
      value: {
        hostname: "localhost",
        origin: "http://localhost",
        protocol: "http:",
        host: "localhost",
        port: "",
        pathname: "/",
        search: "",
        hash: "",
        assign: vi.fn(),
        replace: vi.fn(),
        reload: vi.fn(),
        set href(value: string) {
          navigated.push(value);
        },
        get href() {
          return "http://localhost/";
        },
        toString: () => "http://localhost/",
      },
    });
    try {
      render(<ConnectionsPage />);
      await screen.findByRole("heading", { name: "Workspace Connections" });

      fireEvent.click(screen.getByRole("button", { name: "Connect Bing" }));

      expect(navigated).toEqual([
        "/api/workspaces/current/oauth-connections/bing/start?workspace_id=42",
      ]);
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        value: originalLocation,
      });
    }
  });

  // signal-MVP `.conn` rows inside `.wsec` cards: flat hairline-separated
  // rows with a 32px icon tile, no nested --paper tiles.
  it("renders connections as flat conn rows, not nested tiles", async () => {
    render(<ConnectionsPage />);
    const heading = await screen.findByRole("heading", { name: "Workspace Connections" });
    const section = heading.parentElement as HTMLElement;
    const rows = section.querySelectorAll('[class*="border-t-(--line-2)"]');
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.className).toContain("py-3");
      expect(row.className).toContain("flex");
    }
    // No nested tile anywhere inside a section card.
    expect(section.querySelector('[class*="rounded-(--r-md)"][class*="bg-(--paper)"]')).toBeNull();
    // 32px icon tiles exist per row.
    expect(
      section.querySelectorAll('[class*="h-8"][class*="bg-(--line-2)"]').length
    ).toBeGreaterThan(0);
  });

  it("contains focus, closes with Escape, and restores focus for configuration dialogs", async () => {
    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: /workspace connections/i });

    const opener = screen.getByRole("button", { name: "Configure" });
    opener.focus();
    fireEvent.click(opener);

    const dialog = await screen.findByRole("dialog", { name: "Configure Slack Channel" });
    const closeButton = within(dialog).getByRole("button", {
      name: "Close Configure Slack Channel",
    });
    expect(dialog).toContainElement(closeButton);
    expect(dialog).toContainElement(document.activeElement as HTMLElement);

    fireEvent.keyDown(document, { key: "Escape" });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(opener).toHaveFocus();
  });

  it("renders the expanded integrations surface across every connection tab", async () => {
    window.localStorage.setItem("active_workspace_id", "42");
    render(<ConnectionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /workspace connections/i })).toBeInTheDocument();
    });

    const workspaceRequest = vi
      .mocked(globalThis.fetch)
      .mock.calls.find(([input]) => input === "/api/workspaces/current/oauth-connections");
    expect(workspaceRequest?.[1]?.headers).toEqual(
      expect.objectContaining({
        Authorization: "Bearer token-123",
        "X-Workspace-Id": "42",
      })
    );

    expect(
      screen.getByText(/workspace-level integrations power shared data access/i)
    ).toBeInTheDocument();
    expect(screen.getByText("Google Search Console & GA4")).toBeInTheDocument();
    expect(screen.getByText("Bing Webmaster Tools")).toBeInTheDocument();
    expect(screen.getByText("Atlassian Jira")).toBeInTheDocument();
    expect(screen.getByText("Slack")).toBeInTheDocument();
    // Teams is visible again (SIGV2-1265), but as an announced integration
    // that cannot be connected yet rather than a hidden one.
    expect(screen.getByText("Microsoft Teams")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /configure teams/i })).not.toBeInTheDocument();
    expect(screen.getByText(/Ops HQ/)).toBeInTheDocument();
    expect(screen.getByText(/#seo-alerts/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /test/i })).toBeInTheDocument();
    // Corrected pill rule: a pill is suppressed only when it restates what the
    // action already says ("Not connected" beside Connect). Pills that add
    // state - Connected, Reconnect required, Needs API key - stay.
    expect(screen.queryByText(/not connected/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/^connected$/i).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("button", { name: /connect/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/advanced options/i).length).toBeGreaterThan(0);

    // CMS Fix Delivery and AI Bot Log Analyzer are flag-hidden: no connector
    // has a live connection in this fixture, so the whole card is gone.
    expect(screen.queryByText("WordPress")).not.toBeInTheDocument();
    expect(screen.queryByText("Shopify")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "AI Bot Log Analyzer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /open bot log analyzer/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /monitoring hub/i })).not.toBeInTheDocument();
  });

  it("shows the CMS connector needs-key state and a verify CTA when credentials are unverified", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(
          JSON.stringify([
            {
              id: 101,
              workspace_id: 1,
              name: "Client Project",
              domain_url: "https://client.example.com",
              target_country: "US",
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
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/projects/101/cms/connections") {
        return new Response(
          JSON.stringify([
            {
              id: 55,
              project_id: 101,
              workspace_id: 1,
              cms_type: "wordpress",
              site_url: "https://client.example.com",
              status: "pending",
              last_verified_at: null,
              schema_version: "1.0",
              created_at: null,
              updated_at: null,
              credentials_preview: {},
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(
          JSON.stringify({
            is_connected: false,
            team_id: null,
            team_name: null,
            bot_user_id: null,
            default_channel_id: null,
            default_channel_name: null,
            scope: null,
            updated_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(
          JSON.stringify({
            is_connected: false,
            channel_name: null,
            webhook_preview: null,
            updated_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /workspace connections/i })).toBeInTheDocument();
    });

    // "Needs API key" states something the Verify action does not, so the pill
    // stays beside the action.
    await waitFor(() => {
      expect(screen.getByText("Needs API key")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Verify" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /set up wordpress/i })).not.toBeInTheDocument();
    // Shopify has no connection, so its row is hidden with the section flag.
    expect(screen.queryByRole("button", { name: /set up shopify/i })).not.toBeInTheDocument();
  });

  it("shows the integration plan lock state when the plan does not include it", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(
          JSON.stringify([
            {
              id: 101,
              workspace_id: 1,
              name: "Client Project",
              domain_url: "https://client.example.com",
              target_country: "US",
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
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/projects/101/cms/connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(
          JSON.stringify({ detail: "Slack integrations require Specialist or higher." }),
          { status: 402, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(
          JSON.stringify({ detail: "Teams integrations require Specialist or higher." }),
          { status: 402, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /workspace connections/i })).toBeInTheDocument();
    });

    // Slack and Teams are not shipping yet (SIGV2-1265), so the row says that
    // instead of advertising a plan upgrade for a feature nobody can buy into.
    await waitFor(() => {
      expect(screen.getAllByText("Coming soon").length).toBeGreaterThan(0);
    });
    expect(screen.queryByRole("button", { name: /connect slack/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/upgrade required/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/slack integrations require specialist or higher/i)
    ).not.toBeInTheDocument();
    expect(screen.getByText("Microsoft Teams")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /connect teams/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /configure teams/i })).not.toBeInTheDocument();
  });

  it("marks Jira, Slack and Teams coming soon and offers no way to connect them", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(
          JSON.stringify([
            { provider: "google", connected: true, configured: true, has_refresh_token: true },
            { provider: "jira", connected: false, configured: true },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (
        input === "/api/integrations/slack/status" ||
        input === "/api/integrations/teams/status"
      ) {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    await waitFor(() => {
      expect(screen.getAllByText("Coming soon")).toHaveLength(3);
    });

    for (const title of ["Atlassian Jira", "Slack", "Microsoft Teams"]) {
      const row = screen.getByText(title).closest('[class*="border-t-(--line-2)"]') as HTMLElement;
      expect(row).not.toBeNull();
      expect(within(row).getByText("Coming soon")).toBeInTheDocument();
      // No connect, configure or advanced affordance on an unshipped row.
      expect(row.querySelector("button, a")).toBeNull();
    }

    // The shipping providers are untouched.
    expect(screen.getByRole("button", { name: /connect bing/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /disconnect/i }).length).toBeGreaterThan(0);
  });

  // signal-MVP `.badge-ok` is sentence case (signal.css has no text-transform
  // on it), and a `.conn` row shows a status pill OR an action, never both.
  it("renders status pills sentence-cased and never beside an action", async () => {
    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /disconnect/i }).length).toBeGreaterThan(0);
    });

    const statusRe =
      /^(connected|not connected|not configured|needs api key|upgrade required|reconnect required|coming soon)$/i;
    const rows = [...document.querySelectorAll<HTMLElement>('[class*="border-t-(--line-2)"]')];
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      const hasAction = Boolean(row.querySelector("button, a"));
      // A redundant pill ("Not connected" / "Not configured" beside an action
      // that already says it) is banned; stateful pills may coexist.
      const hasRedundantPill = [...row.querySelectorAll("span")].some((s) =>
        /^(not connected|not configured)$/i.test(s.textContent?.trim() ?? "")
      );
      expect(hasAction && hasRedundantPill).toBe(false);
    }
    for (const pill of [...document.querySelectorAll("main span")].filter((s) =>
      statusRe.test(s.textContent?.trim() ?? "")
    )) {
      expect(pill.className).not.toContain("uppercase");
    }
    // A connected row keeps its `.badge-ok` pill beside the Disconnect action.
    const connectedPill = screen
      .getAllByText(/^connected$/i)
      .find((el) => el.closest('[class*="border-t-(--line-2)"]'));
    expect(connectedPill).toBeDefined();
    const connectedRow = connectedPill?.closest('[class*="border-t-(--line-2)"]');
    expect(connectedRow?.querySelector("button, a")).not.toBeNull();
  });

  // A masked token fragment and refresh flag are internal plumbing, not
  // customer information; the connected Google row instead routes to the
  // per-project GA4 property binding in Connected data settings.
  it("shows an actionable sub-line on the connected Google row, not token internals", async () => {
    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: /disconnect/i }).length).toBeGreaterThan(0);
    });

    expect(document.body.textContent).not.toMatch(/Token: /);
    expect(document.body.textContent).not.toMatch(/Refresh: /);
    expect(screen.getByRole("link", { name: /GA4 property/i })).toHaveAttribute(
      "href",
      "/dashboard/projects/101/settings#data-sources"
    );
  });

  // SIGV2-1190: a project whose GA4 property is already bound must not be
  // shown setup guidance; the row states the finished binding instead.
  it("hides the GA4 property prompt when every project is already bound", async () => {
    const baseImplementation = vi.mocked(globalThis.fetch).getMockImplementation() as typeof fetch;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (input === "/api/projects/101/data-sources") {
        return new Response(
          JSON.stringify([
            {
              id: 9,
              project_id: 101,
              provider: "google",
              source_type: "google_analytics_4",
              binding_mode: "workspace",
              source_id: "properties/123",
              source_label: "Client GA4",
              is_active: true,
              oauth_connection_id: 5,
              project_oauth_connection_id: null,
              workspace_provider_connected: true,
              updated_at: null,
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      return baseImplementation(input, init);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });
    await waitFor(() => {
      expect(screen.getByText(/GA4 property linked for every project/i)).toBeInTheDocument();
    });
    expect(screen.queryByRole("link", { name: /GA4 property/i })).not.toBeInTheDocument();
  });

  // An expired token without a refresh token cannot self-heal: the row must
  // say "Reconnect required", which no action label conveys.
  it("shows Reconnect required for a stale token beside the action", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(
          JSON.stringify([
            {
              provider: "google",
              connected: true,
              configured: true,
              has_refresh_token: false,
              token_type: "Bearer",
              scope: "analytics.readonly",
              expires_at: "2020-01-01T00:00:00Z",
              updated_at: null,
              access_token_preview: "tok_stale",
            },
          ]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    const pill = await screen.findByText("Reconnect required");
    expect(pill.className).not.toContain("uppercase");
    const row = pill.closest('[class*="border-t-(--line-2)"]') as HTMLElement;
    expect(row.querySelector("button, a")).not.toBeNull();
  });

  // "Not configured in this environment" is prose, not `.s` technical meta -
  // it must render in body type, and its row keeps the muted pill because no
  // action can exist for it.
  it("keeps the unconfigured explanation out of the mono family and shows a pill-only row", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(
          JSON.stringify([{ provider: "bing", connected: false, configured: false }]),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    const note = await screen.findByText(/not configured in this environment/i);
    expect(note.className).not.toContain("--mono");

    const pill = screen.getByText("Not configured");
    expect(pill.className).not.toContain("uppercase");
    const row = pill.closest('[class*="border-t-(--line-2)"]') as HTMLElement;
    expect(row).not.toBeNull();
    expect(row.querySelector("button, a")).toBeNull();
  });

  it("still surfaces an already-connected Teams workspace so it cannot be stranded", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input !== "string") {
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      }
      if (input === "/api/workspaces/current/oauth-connections") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/workspaces/current/projects") {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/slack/status") {
        return new Response(JSON.stringify({ is_connected: false }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (input === "/api/integrations/teams/status") {
        return new Response(
          JSON.stringify({
            is_connected: true,
            channel_name: "ops-alerts",
            webhook_preview: "https://outlook.office.com/webhook/abc",
            updated_at: null,
          }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unexpected fetch call: ${input}`);
    });

    render(<ConnectionsPage />);
    await screen.findByRole("heading", { name: "Workspace Connections" });

    await waitFor(() => {
      expect(screen.getByText("Microsoft Teams")).toBeInTheDocument();
    });
    expect(screen.getByText(/ops-alerts/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
  });
});
