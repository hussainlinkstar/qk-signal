import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectVolatilityIndexPanel from "@/components/dashboard/ProjectVolatilityIndexPanel";

const getToken = vi.fn(async () => "token-123");
const fetchAISearchVolatilitySummary = vi.fn();
const fetchAISearchVolatilityTrends = vi.fn();

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken,
  }),
}));

vi.mock("@/services/monitoringService", () => ({
  fetchAISearchVolatilitySummary: (...args: unknown[]) => fetchAISearchVolatilitySummary(...args),
  fetchAISearchVolatilityTrends: (...args: unknown[]) => fetchAISearchVolatilityTrends(...args),
}));

describe("ProjectVolatilityIndexPanel", () => {
  it("renders plan lock state", async () => {
    fetchAISearchVolatilitySummary.mockRejectedValueOnce(
      new Error("AI Search Volatility Index requires Specialist")
    );
    fetchAISearchVolatilityTrends.mockRejectedValueOnce(
      new Error("AI Search Volatility Index requires Specialist")
    );

    render(<ProjectVolatilityIndexPanel projectId={42} />);

    expect(
      await screen.findByText("The AI Search Volatility Index requires Specialist")
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Correlate project movement with broader AI search turbulence/i)
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Upgrade to Specialist/i })).toBeInTheDocument();
  });

  it("renders no data state", async () => {
    fetchAISearchVolatilitySummary.mockResolvedValueOnce({
      provider: "all",
      generated_at: "2026-03-05T10:00:00Z",
      latest_snapshot_date: null,
      no_data: true,
      degraded: false,
      degraded_reasons: [],
      weather_label: "unknown",
      volatility_score: null,
      compared_queries: 0,
      changed_ratio: null,
      avg_text_similarity: null,
      avg_citation_jaccard: null,
      citation_churn_rate: null,
      format_change_rate: null,
      top_winners: [],
      top_losers: [],
      industries: [],
    });
    fetchAISearchVolatilityTrends.mockResolvedValueOnce({
      provider: "all",
      days: 30,
      points: [],
    });

    render(<ProjectVolatilityIndexPanel projectId={42} />);

    expect(await screen.findByText(/No Volatility Baseline Yet/i)).toBeInTheDocument();
  });

  it("renders populated volatility state", async () => {
    fetchAISearchVolatilitySummary.mockResolvedValueOnce({
      provider: "all",
      generated_at: "2026-03-05T10:00:00Z",
      latest_snapshot_date: "2026-03-05",
      no_data: false,
      degraded: false,
      degraded_reasons: [],
      weather_label: "stormy",
      volatility_score: 8.4,
      compared_queries: 120,
      changed_ratio: 0.58,
      avg_text_similarity: 0.62,
      avg_citation_jaccard: 0.41,
      citation_churn_rate: 0.59,
      format_change_rate: 0.24,
      top_winners: [{ domain: "example.com", delta: 7 }],
      top_losers: [{ domain: "legacy.example", delta: 5 }],
      industries: [
        { industry: "tech", volatility_score: 7.8, compared_queries: 40, changed_ratio: 0.53 },
      ],
    });
    fetchAISearchVolatilityTrends.mockResolvedValueOnce({
      provider: "all",
      days: 30,
      points: [
        { date: "2026-03-04", volatility_score: 6.1, compared_queries: 118, changed_ratio: 0.46 },
        { date: "2026-03-05", volatility_score: 8.4, compared_queries: 120, changed_ratio: 0.58 },
      ],
    });

    render(<ProjectVolatilityIndexPanel projectId={42} />);

    expect(
      await screen.findByRole("heading", { name: /AI Search Volatility Index/i })
    ).toBeInTheDocument();
    expect(screen.getAllByText("8.40/10")).toHaveLength(2);
    expect(screen.getByText(/stormy/i)).toBeInTheDocument();
    expect(screen.getByText(/example.com/i)).toBeInTheDocument();
  });
});
