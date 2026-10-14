import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuditHistory } from "@/hooks/useAuditHistory";
import { DEFAULT_AI_STRATEGIC_INSIGHTS, type AiStrategistViewModel } from "@/types/aiStrategist";

const authState = {
  isSignedIn: true,
  getToken: vi.fn(async () => "token"),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

const searchParamsState = {
  get: vi.fn(() => null as string | null),
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => searchParamsState,
}));

const fetchAuditHistoryMock = vi.fn();
const mapAuditHistoryToViewModelMock = vi.fn();
const generateAiStrategicInsightsMock = vi.fn();

vi.mock("@/services/auditService", () => ({
  fetchAuditHistory: (...args: unknown[]) => fetchAuditHistoryMock(...args),
  mapAuditHistoryToViewModel: (...args: unknown[]) => mapAuditHistoryToViewModelMock(...args),
}));

vi.mock("@/services/ai/aiStrategicInsightsService", () => ({
  generateAiStrategicInsights: (...args: unknown[]) => generateAiStrategicInsightsMock(...args),
}));

const buildViewModel = (): AiStrategistViewModel => ({
  auditId: 99,
  siteUrl: "https://acme.test",
  createdAt: "2025-01-02T00:00:00.000Z",
  status: "completed",
  scores: { seo: 75, speed: 72, indexing: 81, mobile: 69 },
  scoreDeltaVsPrevious: {},
  issueCategories: [],
  priorityActions: [],
  aiInsights: {
    executive_summary: "Original summary",
    critical_alerts: ["A"],
    priority_roadmap: [
      {
        task: "Improve title tags",
        category: "content",
        impact: "high",
        effort_score: 2,
        reasoning: "important",
      },
    ],
    content_gap_theory: ["Gap"],
    technical_debt_explanation: "Debt",
    grounding_sources: [],
    aeo_query_ideas: [],
    geo_prompt_ideas: [],
  },
});

describe("useAuditHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    searchParamsState.get.mockReturnValue(null);
  });

  it("falls back to default insights with warning when AI payload is invalid", async () => {
    const raw = [{ id: 99, full_report: { foo: "bar" } }];
    fetchAuditHistoryMock.mockResolvedValue(raw);
    mapAuditHistoryToViewModelMock.mockReturnValue([buildViewModel()]);
    generateAiStrategicInsightsMock.mockResolvedValue(null);

    const { result } = renderHook(() => useAuditHistory());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.aiError).toBeNull();
    expect(result.current.aiWarning).toBe(
      "Grounded strategic insights were unavailable, so placeholder data is shown."
    );
    expect(result.current.lastAiRefresh).toBeTruthy();
    expect(result.current.latest?.aiInsights).toEqual(DEFAULT_AI_STRATEGIC_INSIGHTS);
  });

  it("sets user-safe aiError and keeps retry flow for provider failures", async () => {
    const raw = [{ id: 99, full_report: { foo: "bar" } }];
    fetchAuditHistoryMock.mockResolvedValue(raw);
    mapAuditHistoryToViewModelMock.mockReturnValue([buildViewModel()]);
    generateAiStrategicInsightsMock.mockRejectedValue(new Error("Unexpected token at line 1"));

    const { result } = renderHook(() => useAuditHistory());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.aiWarning).toBeNull();
    expect(result.current.aiError).toBe(
      "Unable to refresh grounded strategic insights right now. Please try again."
    );
    expect(result.current.aiError).not.toContain("Unexpected token");
  });

  it("passes selected projectId and filters mismatched audits", async () => {
    searchParamsState.get.mockImplementation(((key: string) =>
      key === "projectId" ? "123" : null) as () => string | null);
    const raw = [
      { id: 1, project_id: 111, full_report: { foo: "bar" } },
      { id: 2, project_id: 123, full_report: { foo: "baz" } },
    ];
    fetchAuditHistoryMock.mockResolvedValue(raw);
    mapAuditHistoryToViewModelMock.mockReturnValue([buildViewModel()]);
    generateAiStrategicInsightsMock.mockResolvedValue(DEFAULT_AI_STRATEGIC_INSIGHTS);

    const { result } = renderHook(() => useAuditHistory());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(fetchAuditHistoryMock).toHaveBeenCalledWith({ Authorization: "Bearer token" }, 123);
    expect(mapAuditHistoryToViewModelMock).toHaveBeenCalledWith([raw[1]]);
  });

  it("falls back to the legacy siteId query alias when projectId is absent", async () => {
    searchParamsState.get.mockImplementation(((key: string) =>
      key === "siteId" ? "123" : null) as () => string | null);
    const raw = [
      { id: 10, full_report: { foo: "first" } },
      { id: 11, full_report: { foo: "second" } },
    ];
    fetchAuditHistoryMock.mockResolvedValue(raw);
    mapAuditHistoryToViewModelMock.mockReturnValue([buildViewModel()]);
    generateAiStrategicInsightsMock.mockResolvedValue(DEFAULT_AI_STRATEGIC_INSIGHTS);

    const { result } = renderHook(() => useAuditHistory());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(fetchAuditHistoryMock).toHaveBeenCalledWith({ Authorization: "Bearer token" }, 123);
    expect(mapAuditHistoryToViewModelMock).toHaveBeenCalledWith(raw);
  });

  it("enters loading state and refetches when switching projects", async () => {
    let selectedProject = "123";
    searchParamsState.get.mockImplementation(((key: string) =>
      key === "projectId" ? selectedProject : null) as () => string | null);

    const firstRaw = [{ id: 1, project_id: 123, full_report: { foo: "first" } }];
    const secondRaw = [{ id: 2, project_id: 456, full_report: { foo: "second" } }];

    let resolveSecondFetch: ((value: unknown[]) => void) | null = null;
    fetchAuditHistoryMock.mockResolvedValueOnce(firstRaw).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSecondFetch = resolve;
        })
    );

    mapAuditHistoryToViewModelMock.mockReturnValue([buildViewModel()]);
    generateAiStrategicInsightsMock.mockResolvedValue(DEFAULT_AI_STRATEGIC_INSIGHTS);

    const { result, rerender } = renderHook(() => useAuditHistory());

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    selectedProject = "456";
    rerender();

    await waitFor(() => {
      expect(result.current.loading).toBe(true);
    });

    resolveSecondFetch?.(secondRaw);

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(fetchAuditHistoryMock).toHaveBeenNthCalledWith(
      1,
      { Authorization: "Bearer token" },
      123
    );
    expect(fetchAuditHistoryMock).toHaveBeenNthCalledWith(
      2,
      { Authorization: "Bearer token" },
      456
    );
    expect(mapAuditHistoryToViewModelMock).toHaveBeenLastCalledWith(secondRaw);
  });
});
