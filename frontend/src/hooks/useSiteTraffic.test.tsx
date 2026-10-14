import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { useSiteTraffic } from "@/hooks/useSiteTraffic";
import { fetchSiteTraffic } from "@/services/monitoringService";
import type { SiteTrafficResponse } from "@/types/siteTraffic";

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: vi.fn().mockResolvedValue("token-123"),
    isSignedIn: true,
    isLoading: false,
  }),
}));

vi.mock("@/services/monitoringService", () => ({
  fetchSiteTraffic: vi.fn(),
}));

const fetchProjectDataSources = vi.fn();
vi.mock("@/services/workspaceService", () => ({
  fetchProjectDataSources: (...args: unknown[]) => fetchProjectDataSources(...args),
}));

const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (err: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
};

const payload = (window: string): SiteTrafficResponse =>
  ({ status: "ok", window, availability: "available" }) as SiteTrafficResponse;

describe("useSiteTraffic", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads traffic for the project and default 7D window", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue(payload("7D"));
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchSiteTraffic).toHaveBeenCalledWith("42", "7D", expect.anything());
    expect(result.current.traffic).toMatchObject({ window: "7D" });
  });

  it("discards a stale response when the window changes mid-flight", async () => {
    const slow7d = deferred<SiteTrafficResponse>();
    const fast90d = deferred<SiteTrafficResponse>();
    vi.mocked(fetchSiteTraffic)
      .mockImplementationOnce(() => slow7d.promise)
      .mockImplementationOnce(() => fast90d.promise);

    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(fetchSiteTraffic).toHaveBeenCalledTimes(1));

    act(() => result.current.setWindow("90D"));
    await waitFor(() => expect(fetchSiteTraffic).toHaveBeenCalledTimes(2));
    expect(fetchSiteTraffic).toHaveBeenLastCalledWith("42", "90D", expect.anything());

    // The newer request resolves first; the older must not overwrite it.
    await act(async () => fast90d.resolve(payload("90D")));
    await waitFor(() => expect(result.current.traffic).toMatchObject({ window: "90D" }));
    await act(async () => slow7d.resolve(payload("7D")));
    expect(result.current.traffic).toMatchObject({ window: "90D" });
  });

  it("derives ga4WorkspaceConnected from the GA4 assignment when disconnected", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "disconnected",
      availability: "disconnected",
    });
    fetchProjectDataSources.mockResolvedValue([
      {
        id: null,
        project_id: 42,
        provider: "google",
        source_type: "google_analytics_4",
        binding_mode: "workspace",
        source_id: null,
        source_label: null,
        is_active: false,
        oauth_connection_id: 11,
        project_oauth_connection_id: null,
        workspace_provider_connected: true,
        updated_at: null,
      },
    ]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4WorkspaceConnected).toBe(true));
    expect(fetchProjectDataSources).toHaveBeenCalledWith("42", expect.anything());
    // The stub row is unbound, so nothing is paused.
    expect(result.current.ga4BoundInactive).toBe(false);
  });

  it("reports a bound-but-switched-off GA4 binding separately from disconnected", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "disconnected",
      availability: "disconnected",
    });
    fetchProjectDataSources.mockResolvedValue([
      {
        id: 55,
        project_id: 42,
        provider: "google",
        source_type: "google_analytics_4",
        binding_mode: "workspace",
        source_id: "properties/123",
        source_label: "Client GA4",
        is_active: false,
        oauth_connection_id: 11,
        project_oauth_connection_id: null,
        workspace_provider_connected: true,
        updated_at: null,
      },
    ]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4BoundInactive).toBe(true));
    expect(result.current.ga4WorkspaceConnected).toBe(true);
  });

  it("does not report bound-inactive for an active binding", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "disconnected",
      availability: "disconnected",
    });
    fetchProjectDataSources.mockResolvedValue([
      {
        id: 55,
        project_id: 42,
        provider: "google",
        source_type: "google_analytics_4",
        binding_mode: "workspace",
        source_id: "properties/123",
        source_label: "Client GA4",
        is_active: true,
        oauth_connection_id: 11,
        project_oauth_connection_id: null,
        workspace_provider_connected: true,
        updated_at: null,
      },
    ]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4WorkspaceConnected).toBe(true));
    expect(result.current.ga4BoundInactive).toBe(false);
  });

  it("reports ga4WorkspaceConnected false when no workspace provider exists", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "disconnected",
      availability: "disconnected",
    });
    fetchProjectDataSources.mockResolvedValue([]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4WorkspaceConnected).toBe(false));
  });

  it("resolves the workspace account state for a permission denial too", async () => {
    // SIGV2-1202: the account-versus-binding distinction used to be made for
    // "disconnected" only, so the permission-denied card had no way to know
    // whether changing the Google account was even a route the customer had.
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "permission_denied",
      availability: "unavailable",
      reason: "property_denied",
    });
    fetchProjectDataSources.mockResolvedValue([
      {
        id: 55,
        project_id: 42,
        provider: "google",
        source_type: "google_analytics_4",
        binding_mode: "workspace",
        source_id: "properties/123",
        source_label: "Client GA4",
        is_active: true,
        oauth_connection_id: 11,
        project_oauth_connection_id: null,
        workspace_provider_connected: true,
        updated_at: null,
      },
    ]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4WorkspaceConnected).toBe(true));
    expect(fetchProjectDataSources).toHaveBeenCalledWith("42", expect.anything());
  });

  it("reports no workspace grant for a client-authorized binding that is denied", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue({
      status: "permission_denied",
      availability: "unavailable",
      reason: "property_denied",
    });
    fetchProjectDataSources.mockResolvedValue([
      {
        id: 55,
        project_id: 42,
        provider: "google",
        source_type: "google_analytics_4",
        binding_mode: "client_magic_link",
        source_id: "properties/123",
        source_label: "Client GA4",
        is_active: true,
        oauth_connection_id: null,
        project_oauth_connection_id: 9,
        workspace_provider_connected: false,
        updated_at: null,
      },
    ]);
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.ga4WorkspaceConnected).toBe(false));
  });

  it("does not fetch data sources for a connected payload", async () => {
    vi.mocked(fetchSiteTraffic).mockResolvedValue(payload("7D"));
    const { result } = renderHook(() => useSiteTraffic("42"));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchProjectDataSources).not.toHaveBeenCalled();
    expect(result.current.ga4WorkspaceConnected).toBeNull();
  });

  it("discards a stale response when the project changes mid-flight", async () => {
    const first = deferred<SiteTrafficResponse>();
    const second = deferred<SiteTrafficResponse>();
    vi.mocked(fetchSiteTraffic)
      .mockImplementationOnce(() => first.promise)
      .mockImplementationOnce(() => second.promise);

    const { result, rerender } = renderHook(({ id }) => useSiteTraffic(id), {
      initialProps: { id: "42" },
    });
    await waitFor(() => expect(fetchSiteTraffic).toHaveBeenCalledTimes(1));

    rerender({ id: "9" });
    await waitFor(() => expect(fetchSiteTraffic).toHaveBeenCalledTimes(2));

    await act(async () => second.resolve(payload("7D")));
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => first.resolve(payload("7D")));
    expect(fetchSiteTraffic).toHaveBeenLastCalledWith("9", "7D", expect.anything());
    expect(result.current.error).toBeNull();
  });
});
