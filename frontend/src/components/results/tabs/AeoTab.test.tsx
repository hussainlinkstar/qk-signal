import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import AeoTab from "./AeoTab";

const { generateAiStrategicInsightsMock } = vi.hoisted(() => ({
  generateAiStrategicInsightsMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "42" }),
}));

vi.mock("@/hooks/useJiraExportTracker", () => ({
  useJiraExportTracker: () => ({
    getTrackedExport: () => null,
    markExported: vi.fn(),
  }),
}));

vi.mock("@/services/ai/aiStrategicInsightsService", () => ({
  generateAiStrategicInsights: (...args: unknown[]) => generateAiStrategicInsightsMock(...args),
}));

describe("AeoTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders grounded AEO ideas with confidence and source metadata", async () => {
    generateAiStrategicInsightsMock.mockResolvedValue({
      executive_summary: "Summary",
      critical_alerts: ["Alert"],
      priority_roadmap: [
        {
          task: "Task",
          category: "Content",
          impact: "high",
          effort_score: 3,
          reasoning: "Reasoning",
        },
      ],
      content_gap_theory: ["Gap"],
      technical_debt_explanation: "Debt",
      grounding_sources: [],
      aeo_query_ideas: [
        {
          text: "What is Acme and how does it work?",
          confidence: "high",
          label: "measured",
          source_basis: ["Project visibility monitoring", "Providers: google"],
          status_note: "Latest monitoring runs found 2 citation(s).",
          last_verified_at: "2026-03-10T09:00:00Z",
        },
      ],
      geo_prompt_ideas: [],
    });

    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[["answerability_score", 72]]}
        aeoEntityClarity="Clear entity coverage"
        aeoRecommendations={["Add FAQ schema"]}
        auditId={99}
        projectId={42}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("What is Acme and how does it work?")).toBeInTheDocument();
    });

    expect(screen.getByText("Refresh grounded queries")).toBeInTheDocument();
    expect(screen.getByText("measured")).toBeInTheDocument();
    expect(screen.getByText("high confidence")).toBeInTheDocument();
    expect(screen.getByText("Latest monitoring runs found 2 citation(s).")).toBeInTheDocument();
    expect(
      screen.getByText("Sources: Project visibility monitoring • Providers: google")
    ).toBeInTheDocument();
  });

  it("renders saved tracker queries as manual hypotheses without citation counters", async () => {
    window.localStorage.setItem(
      "aeo-query-tracker:workspace",
      JSON.stringify([
        {
          query: "How do buyers evaluate Acme?",
          trackedAt: "2026-03-10T09:00:00Z",
          citationHits: 7,
        },
      ])
    );

    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[["answerability_score", 72]]}
        aeoEntityClarity="Clear entity coverage"
        aeoRecommendations={["Add FAQ schema"]}
      />
    );

    await waitFor(() => {
      expect(screen.getAllByText("How do buyers evaluate Acme?").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("Manual Hypothesis Queue")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Saved as a manual hypothesis. Add project monitoring to validate this query with measured citation telemetry."
      )[0]
    ).toBeInTheDocument();
    expect(screen.queryByText(/Citation Hits:/i)).not.toBeInTheDocument();
  });

  it("renders readability findings and rewrite suggestions when the audit computed them", () => {
    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[["answerability_score", 72]]}
        aeoEntityClarity="Clear entity coverage"
        aeoRecommendations={["Add FAQ schema"]}
        readabilityFindings={["2 paragraph(s) exceed complexity thresholds."]}
        rewriteSuggestions={[
          {
            paragraph: "Signal runs your website through the engines people ask first.",
            score: 0.377,
            suggestion: "Split long sentences and move the direct answer to the opening sentence.",
          },
        ]}
      />
    );

    expect(screen.getByText("Readability & Extractability")).toBeInTheDocument();
    expect(screen.getByText("2 paragraph(s) exceed complexity thresholds.")).toBeInTheDocument();
    expect(
      screen.getByText(/Signal runs your website through the engines people ask first\./)
    ).toBeInTheDocument();
    expect(
      screen.getByText("Split long sentences and move the direct answer to the opening sentence.")
    ).toBeInTheDocument();
    expect(screen.getByText("Readability score: 38/100")).toBeInTheDocument();
  });

  it("omits the readability section entirely when there is nothing to show", () => {
    render(
      <AeoTab
        aeoScore={72}
        aeoScoreEntries={[["answerability_score", 72]]}
        aeoEntityClarity="Clear entity coverage"
        aeoRecommendations={["Add FAQ schema"]}
      />
    );

    expect(screen.queryByText("Readability & Extractability")).not.toBeInTheDocument();
  });
});
