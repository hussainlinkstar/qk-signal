import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import "@/i18n";

/**
 * The status pages exist because the API may be down: their chrome must not
 * depend on a fetch succeeding. This pins that rendering /maintenance issues
 * no request other than the health probe, and that the app 404 (same shell)
 * issues none at all.
 */

const authState = {
  logout: vi.fn(async () => {}),
  getToken: vi.fn(async () => "token-123"),
  isSignedIn: true,
  user: null as null | { email?: string; name?: string },
};

vi.mock("@/components/auth/custom-auth", () => ({ useAuth: () => authState }));
vi.mock("@/contexts/CookieConsentContext", () => ({
  useCookieConsent: () => ({ openSettings: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/maintenance",
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

const fetchUserWorkspaces = vi.fn(async () => []);
const fetchWorkspaceProjects = vi.fn(async () => []);
vi.mock("@/services/workspaceService", () => ({
  fetchUserWorkspaces: (...args: unknown[]) => fetchUserWorkspaces(...args),
  fetchWorkspaceProjects: (...args: unknown[]) => fetchWorkspaceProjects(...args),
}));

const HEALTH_URL = "/api/system-status/health";

const stubFetch = (status = 503) => {
  const fetchMock = vi.fn(async () => ({
    status,
    json: async () => ({ message: "Scheduled maintenance", retry_after: 300 }),
  }));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
};

const renderWithClient = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

import MaintenancePage from "./page";
import SignalNotFound from "@/components/signal/SignalNotFound";

describe("status page network behaviour", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isSignedIn = true;
    authState.user = { email: "razvan@qiko.ai", name: "Razvan Baba" };
  });

  it("issues only the health probe when rendering /maintenance", async () => {
    const fetchMock = stubFetch(503);
    renderWithClient(<MaintenancePage />);

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect((await screen.findAllByText("Scheduled maintenance")).length).toBeGreaterThan(0);

    const urls = fetchMock.mock.calls.map((call) => String(call[0]));
    expect(urls).toEqual([HEALTH_URL]);
    expect(fetchUserWorkspaces).not.toHaveBeenCalled();
    expect(fetchWorkspaceProjects).not.toHaveBeenCalled();
  });

  it("issues no request at all when rendering the app 404 shell", async () => {
    const fetchMock = stubFetch();
    renderWithClient(<SignalNotFound />);

    expect(await screen.findByText("404")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(fetchUserWorkspaces).not.toHaveBeenCalled();
    expect(fetchWorkspaceProjects).not.toHaveBeenCalled();
  });
});
