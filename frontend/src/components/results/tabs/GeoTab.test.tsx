import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import GeoTab from "./GeoTab";

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

describe("GeoTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
  });

  it("renders grounded GEO prompts with source metadata", async () => {
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
      aeo_query_ideas: [],
      geo_prompt_ideas: [
        {
          text: "Acme vs Rival One",
          confidence: "medium",
          label: "hypothesis",
          source_basis: ["Project competitor list"],
          status_note:
            "Derived from tracked project competitors and should be validated with monitoring.",
          last_verified_at: null,
        },
      ],
    });

    render(
      <GeoTab
        geoScore={68}
        geoSummary="Entity trust needs work"
        geoTabData={{
          trustSignalsScore: 61,
          citabilityScore: 54,
          entityMatchingScore: 59,
          technicalSeoScore: 55,
        }}
        geoRecommendations={["Strengthen comparison pages"]}
        auditId={99}
        projectId={42}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Acme vs Rival One")).toBeInTheDocument();
    });

    expect(screen.getByText("Refresh grounded prompts")).toBeInTheDocument();
    expect(screen.getByText("hypothesis")).toBeInTheDocument();
    expect(screen.getByText("medium confidence")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Derived from tracked project competitors and should be validated with monitoring."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Sources: Project competitor list")).toBeInTheDocument();
  });

  it("renders saved tracker prompts as manual hypotheses without citation counters", async () => {
    window.localStorage.setItem(
      "geo-prompt-tracker:workspace",
      JSON.stringify([
        {
          prompt: "Acme vs Rival Two",
          trackedAt: "2026-03-10T09:00:00Z",
          citationHits: 4,
        },
      ])
    );

    render(
      <GeoTab
        geoScore={68}
        geoSummary="Entity trust needs work"
        geoTabData={{
          trustSignalsScore: 61,
          citabilityScore: 54,
          entityMatchingScore: 59,
          technicalSeoScore: 55,
        }}
        geoRecommendations={["Strengthen comparison pages"]}
      />
    );

    await waitFor(() => {
      expect(screen.getAllByText("Acme vs Rival Two").length).toBeGreaterThan(0);
    });

    expect(screen.getByText("Manual Hypothesis Queue")).toBeInTheDocument();
    expect(
      screen.getAllByText(
        "Saved as a manual hypothesis. Add project monitoring to validate this prompt with measured citation telemetry."
      )[0]
    ).toBeInTheDocument();
    expect(screen.queryByText(/Citation Hits:/i)).not.toBeInTheDocument();
  });
});
