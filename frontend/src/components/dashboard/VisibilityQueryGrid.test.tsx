import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import VisibilityQueryGrid from "@/components/dashboard/VisibilityQueryGrid";
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
  visibility_score: 66.67,
  score_breakdown: null,
  trend_delta: 5,
  completed_checks: 3,
  pending_checks: 0,
  cited_checks: 2,
  total_checks: 3,
  last_updated_at: "2026-03-04T10:00:00.000Z",
  provider_breakdown: [],
  queries: [
    {
      id: 1,
      project_id: 42,
      query_text: "best payroll software",
      query_type: "aeo",
      providers: ["google", "openai"],
      is_active: true,
      created_at: "2026-03-02T10:00:00.000Z",
      updated_at: "2026-03-04T10:00:00.000Z",
      average_score: 50,
      last_checked_at: "2026-03-04T10:00:00.000Z",
      results: [
        {
          provider: "google",
          status: "cited",
          batch_status: "succeeded",
          score: 100,
          last_checked_at: "2026-03-04T10:00:00.000Z",
          citations_found: 1,
          score_breakdown: null,
        },
        {
          provider: "openai",
          status: "not_cited",
          batch_status: "succeeded",
          score: 0,
          last_checked_at: "2026-03-04T10:00:00.000Z",
          citations_found: 0,
          score_breakdown: null,
        },
      ],
    },
  ],
};

describe("VisibilityQueryGrid", () => {
  it("renders provider columns and status badges", () => {
    render(<VisibilityQueryGrid summary={summaryFixture} />);

    expect(screen.getByText("Query Visibility Grid")).toBeInTheDocument();
    // Columns are labelled from VISIBILITY_PROVIDER_LABELS, which now carries
    // model names rather than vendor names. Read from the map so a relabel
    // cannot silently break this again.
    expect(screen.getAllByText(VISIBILITY_PROVIDER_LABELS.google).length).toBeGreaterThan(0);
    expect(screen.getAllByText(VISIBILITY_PROVIDER_LABELS.openai).length).toBeGreaterThan(0);
    expect(screen.getAllByText("best payroll software").length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText(/google status cited/i).length).toBeGreaterThan(0);
    expect(screen.getAllByLabelText(/openai status not cited/i).length).toBeGreaterThan(0);
  });

  it("shows the no-data state when runs have not completed", () => {
    render(
      <VisibilityQueryGrid
        summary={{
          ...summaryFixture,
          completed_checks: 0,
          pending_checks: 2,
          total_checks: 2,
        }}
      />
    );

    expect(screen.getByText(/first provider runs have not completed yet/i)).toBeInTheDocument();
  });
});
