import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import BenchmarkPercentileBadge from "@/components/dashboard/BenchmarkPercentileBadge";

describe("BenchmarkPercentileBadge", () => {
  it("renders the loading state", () => {
    render(
      <BenchmarkPercentileBadge
        loading
        planLocked={false}
        error={null}
        benchmark={null}
        citationStability={null}
        remediationImpact={null}
      />
    );

    expect(screen.getByText("Loading Benchmark Intelligence")).toBeInTheDocument();
  });

  it("renders the plan-locked state", () => {
    render(
      <BenchmarkPercentileBadge
        loading={false}
        planLocked
        error={null}
        benchmark={null}
        citationStability={null}
        remediationImpact={null}
      />
    );

    expect(
      screen.getByText("Benchmark comparisons are available on Specialist.")
    ).toBeInTheDocument();
  });

  it("renders the insufficient cohort state", () => {
    render(
      <BenchmarkPercentileBadge
        loading={false}
        planLocked={false}
        error={null}
        benchmark={{
          project_id: 7,
          metric: "geo_score",
          status: "insufficient_data",
          percentile: null,
          top_percent: null,
          cohort_key: "industry:saas:geo_score",
          cohort_label: "Industry: saas (geo_score)",
          cohort_size: 6,
          project_value: 61,
          period_date: "2026-03-05",
        }}
        citationStability={null}
        remediationImpact={null}
      />
    );

    expect(screen.getByText("Not enough similar projects yet.")).toBeInTheDocument();
  });

  it("renders success metrics and percentile copy", () => {
    render(
      <BenchmarkPercentileBadge
        loading={false}
        planLocked={false}
        error={null}
        benchmark={{
          project_id: 7,
          metric: "geo_score",
          status: "ok",
          percentile: 82,
          top_percent: 18,
          cohort_key: "industry:saas:geo_score",
          cohort_label: "Industry: saas (geo_score)",
          cohort_size: 23,
          project_value: 75,
          period_date: "2026-03-05",
        }}
        citationStability={{
          project_id: 7,
          score_type: "citation_stability",
          score_version: "v1",
          status: "ok",
          value: 79.2,
          confidence: "high",
          data_points_used: 14,
          components: {},
          weights: {},
          computed_at: "2026-03-05T12:00:00.000Z",
        }}
        remediationImpact={{
          project_id: 7,
          score_type: "remediation_impact",
          score_version: "v1",
          status: "ok",
          value: 68.1,
          confidence: "medium",
          data_points_used: 7,
          components: {},
          weights: {},
          computed_at: "2026-03-05T12:00:00.000Z",
        }}
      />
    );

    expect(screen.getByText("You are in the top 18% of similar projects.")).toBeInTheDocument();
    expect(screen.getByText("Cohort size: 23")).toBeInTheDocument();
    expect(screen.getByText("79")).toBeInTheDocument();
    expect(screen.getByText("68")).toBeInTheDocument();
  });
});
