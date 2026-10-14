import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AIVisibilityScoreCard from "@/components/dashboard/AIVisibilityScoreCard";
import { VISIBILITY_PROVIDER_LABELS } from "@/components/dashboard/visibilityUtils";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

const summaryFixture: VisibilitySummaryResponse = {
  project_id: 42,
  entitlements: {
    plan: "plan_specialist",
    max_queries: 50,
    used_queries: 2,
    remaining_queries: 48,
    allowed_providers: ["google", "openai", "anthropic"],
    is_locked: false,
    estimated_cost_per_check: {
      google: 1,
      openai: 1,
      anthropic: 1,
    },
  },
  queries_configured: 2,
  providers: ["google", "openai"],
  visibility_score: 67,
  score_breakdown: {
    citation_presence: 30,
    citation_position: 15,
    text_mention: 12,
    topic_relevance: 10,
  },
  trend_delta: -12.5,
  completed_checks: 3,
  pending_checks: 0,
  cited_checks: 2,
  total_checks: 3,
  last_updated_at: "2026-03-04T10:00:00.000Z",
  provider_breakdown: [
    {
      provider: "google",
      tracked_queries: 2,
      completed_checks: 2,
      cited_checks: 2,
      visibility_score: 100,
    },
    {
      provider: "openai",
      tracked_queries: 1,
      completed_checks: 1,
      cited_checks: 0,
      visibility_score: 0,
    },
  ],
  queries: [],
};

describe("AIVisibilityScoreCard", () => {
  it("renders the score and trend delta", () => {
    render(<AIVisibilityScoreCard summary={summaryFixture} />);

    expect(screen.getByText("AI Visibility Score")).toBeInTheDocument();
    expect(screen.getByText("67%")).toBeInTheDocument();
    expect(screen.getByText(/-12\.5 pts vs previous run/i)).toBeInTheDocument();
    // Provider labels are model names now, so these read from the shared map.
    expect(screen.getByText(VISIBILITY_PROVIDER_LABELS.google)).toBeInTheDocument();
    expect(screen.getByText(VISIBILITY_PROVIDER_LABELS.openai)).toBeInTheDocument();
  });

  it("shows the onboarding state when there are no configured queries", () => {
    render(
      <AIVisibilityScoreCard
        summary={{
          ...summaryFixture,
          queries_configured: 0,
          completed_checks: 0,
          total_checks: 0,
          provider_breakdown: [],
        }}
      />
    );

    expect(screen.getByText(/Add queries to track/i)).toBeInTheDocument();
  });

  it("shows a loading skeleton", () => {
    const { container } = render(<AIVisibilityScoreCard summary={null} loading />);
    expect(container.querySelector(".animate-pulse")).not.toBeNull();
  });
});
