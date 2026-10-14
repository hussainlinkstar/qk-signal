import { describe, expect, it } from "vitest";

import { parseAiStrategicInsights } from "./aiStrategicInsightsService";

describe("parseAiStrategicInsights", () => {
  it("parses grounded strategic ideas and source metadata", () => {
    const parsed = parseAiStrategicInsights(
      JSON.stringify({
        executive_summary: "Summary",
        critical_alerts: ["Alert A"],
        priority_roadmap: [
          {
            task: "Task",
            category: "Content",
            impact: "high",
            effort_score: 3,
            reasoning: "Reasoning",
            confidence: "high",
            label: "inferred",
            source_basis: ["Latest canonical audit recommendations"],
          },
        ],
        content_gap_theory: ["Gap"],
        technical_debt_explanation: "Debt",
        grounding_sources: [
          {
            label: "Project visibility monitoring",
            source_type: "monitoring",
            measured: true,
            updated_at: "2026-03-10T09:00:00Z",
          },
        ],
        aeo_query_ideas: [
          {
            text: "What is Acme and how does it work?",
            confidence: "high",
            label: "measured",
            source_basis: ["Project visibility monitoring"],
            status_note: "Latest monitoring runs found 2 citation(s).",
            last_verified_at: "2026-03-10T09:00:00Z",
          },
        ],
        geo_prompt_ideas: [
          {
            text: "Acme vs Rival One",
            confidence: "medium",
            label: "hypothesis",
            source_basis: ["Project competitor list"],
          },
        ],
      })
    );

    expect(parsed).not.toBeNull();
    expect(parsed?.grounding_sources).toEqual([
      {
        label: "Project visibility monitoring",
        source_type: "monitoring",
        measured: true,
        updated_at: "2026-03-10T09:00:00Z",
      },
    ]);
    expect(parsed?.aeo_query_ideas[0]).toMatchObject({
      text: "What is Acme and how does it work?",
      confidence: "high",
      label: "measured",
    });
    expect(parsed?.geo_prompt_ideas[0]).toMatchObject({
      text: "Acme vs Rival One",
      label: "hypothesis",
    });
  });
});
