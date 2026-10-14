import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Mock http module
vi.mock("@/services/http", () => ({
  requestJson: vi.fn(),
}));

import { useAuditComparison } from "@/hooks/useAuditComparison";
import { requestJson } from "@/services/http";

const mockRequestJson = vi.mocked(requestJson);

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

describe("useAuditComparison", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not fetch when auditId is null", () => {
    renderHook(() => useAuditComparison(null), { wrapper: createWrapper() });
    expect(mockRequestJson).not.toHaveBeenCalled();
  });

  it("does not fetch when auditId is undefined", () => {
    renderHook(() => useAuditComparison(undefined), { wrapper: createWrapper() });
    expect(mockRequestJson).not.toHaveBeenCalled();
  });

  it("fetches comparison data when auditId is provided", async () => {
    const mockData = {
      audit_id: 1,
      has_previous: true,
      previous_audit_id: 0,
      scores: {
        overall: { current: 72, previous: 65, delta: 7, direction: "up" },
        seo: { current: 80, previous: 75, delta: 5, direction: "up" },
        geo: { current: 60, previous: 65, delta: -5, direction: "down" },
        aeo: { current: 70, previous: 55, delta: 15, direction: "up" },
      },
      sub_components: {},
      history: [],
    };
    mockRequestJson.mockResolvedValue(mockData);

    const { result } = renderHook(() => useAuditComparison(1), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    // requestJson takes a single options object now, not (url, options).
    expect(mockRequestJson).toHaveBeenCalledWith({
      endpoint: "/api/audit/1/comparison",
      method: "GET",
      errorMessage: "Failed to fetch audit comparison",
    });
    expect(result.current.data?.has_previous).toBe(true);
    expect(result.current.data?.scores.overall.delta).toBe(7);
  });

  it("handles first audit with no previous", async () => {
    const mockData = {
      audit_id: 1,
      has_previous: false,
      scores: {
        overall: { current: 72 },
        seo: { current: 80 },
        geo: { current: 60 },
        aeo: { current: 70 },
      },
      sub_components: {},
      history: [{ audit_id: 1, date: "2026-01-01", overall: 72, seo: 80, geo: 60, aeo: 70 }],
    };
    mockRequestJson.mockResolvedValue(mockData);

    const { result } = renderHook(() => useAuditComparison(1), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.has_previous).toBe(false);
  });

  it("handles fetch error gracefully", async () => {
    mockRequestJson.mockRejectedValue(new Error("Not found"));

    const { result } = renderHook(() => useAuditComparison(999), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 5000 });
    expect(result.current.data).toBeUndefined();
  });
});
