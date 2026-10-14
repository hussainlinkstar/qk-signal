import React from "react";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { ActiveAuditJob } from "@/hooks/useActiveAudits";

/* ------------------------------------------------------------------ */
/*  Mocks                                                             */
/* ------------------------------------------------------------------ */

const requestJsonMock = vi.fn();
vi.mock("@/services/http", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));

const useAuthMock = vi.fn<() => { isSignedIn: boolean }>();
vi.mock("@/contexts/AuthContext", () => ({
  useAuth: (...args: unknown[]) => useAuthMock(...(args as [])),
}));

/* ------------------------------------------------------------------ */
/*  Helpers                                                           */
/* ------------------------------------------------------------------ */

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        gcTime: 0,
      },
    },
  });

  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

function makeJob(overrides: Partial<ActiveAuditJob> = {}): ActiveAuditJob {
  return {
    job_id: "job-1",
    status: "running",
    audit_target_type: "website",
    target_name: "example.com",
    target_url: "https://example.com",
    tier: "basic",
    tier_display: "Fast Audit",
    started_at: "2024-01-01T00:00:00Z",
    last_heartbeat: "2024-01-01T00:01:00Z",
    stale: false,
    stale_reason: null,
    project_id: null,
    ...overrides,
  };
}

/* ------------------------------------------------------------------ */
/*  Tests                                                             */
/* ------------------------------------------------------------------ */

// Dynamic import so the mocks are in place when the module loads
async function importHook() {
  const mod = await import("@/hooks/useActiveAudits");
  return mod.useActiveAudits;
}

describe("useActiveAudits", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns empty activeJobs and hasActiveAudits=false when user is not signed in", async () => {
    useAuthMock.mockReturnValue({ isSignedIn: false });
    requestJsonMock.mockResolvedValue({ jobs: [makeJob()] });

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    // Query is disabled — requestJson should never be called
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(requestJsonMock).not.toHaveBeenCalled();
    expect(result.current.activeJobs).toEqual([]);
    expect(result.current.hasActiveAudits).toBe(false);
  });

  it("fetches /api/audit/jobs when user is signed in", async () => {
    const jobs = [makeJob({ job_id: "a1" }), makeJob({ job_id: "a2" })];
    useAuthMock.mockReturnValue({ isSignedIn: true });
    requestJsonMock.mockResolvedValue({ jobs });

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.activeJobs).toHaveLength(2);
    });

    expect(requestJsonMock).toHaveBeenCalledWith(
      expect.objectContaining({
        endpoint: "/api/audit/jobs",
        method: "GET",
        errorMessage: "Failed to fetch active audits",
      })
    );
    expect(result.current.hasActiveAudits).toBe(true);
    expect(result.current.activeJobs[0].job_id).toBe("a1");
    expect(result.current.activeJobs[1].job_id).toBe("a2");
  });

  it("returns hasActiveAudits=false when API returns empty jobs array", async () => {
    useAuthMock.mockReturnValue({ isSignedIn: true });
    requestJsonMock.mockResolvedValue({ jobs: [] });

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.activeJobs).toEqual([]);
    expect(result.current.hasActiveAudits).toBe(false);
  });

  it("exposes a refetch function", async () => {
    useAuthMock.mockReturnValue({ isSignedIn: true });
    requestJsonMock.mockResolvedValue({ jobs: [makeJob()] });

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.activeJobs).toHaveLength(1);
    });

    expect(typeof result.current.refetch).toBe("function");
  });

  it("reports isLoading=true while the first fetch is in flight", async () => {
    useAuthMock.mockReturnValue({ isSignedIn: true });

    let resolveFetch!: (value: { jobs: ActiveAuditJob[] }) => void;
    requestJsonMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    // While the fetch is pending, isLoading should be true
    expect(result.current.isLoading).toBe(true);
    expect(result.current.activeJobs).toEqual([]);

    // Resolve the fetch
    resolveFetch({ jobs: [makeJob()] });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.activeJobs).toHaveLength(1);
  });

  it("defaults to empty array when data.jobs is undefined", async () => {
    useAuthMock.mockReturnValue({ isSignedIn: true });
    // API returns an object without a jobs key
    requestJsonMock.mockResolvedValue({});

    const useActiveAudits = await importHook();

    const { result } = renderHook(() => useActiveAudits(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.activeJobs).toEqual([]);
    expect(result.current.hasActiveAudits).toBe(false);
  });
});
