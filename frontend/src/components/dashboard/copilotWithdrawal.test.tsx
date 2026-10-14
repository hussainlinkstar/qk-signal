import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AIVisibilityScoreCard from "@/components/dashboard/AIVisibilityScoreCard";
import BrandVsCompetitorVisibilityChart from "@/components/dashboard/BrandVsCompetitorVisibilityChart";
import VisibilityQueryGrid from "@/components/dashboard/VisibilityQueryGrid";
import VisibilityQueryManager from "@/components/dashboard/VisibilityQueryManager";
import VisibilityTrendChart from "@/components/dashboard/VisibilityTrendChart";
import SignalAddPromptModal from "@/components/signal/SignalAddPromptModal";
import { tEn } from "@/test/i18nEn";
import type {
  ComparativeVisibilityResponse,
  VisibilityEntitlements,
  VisibilityQuerySummaryRow,
  VisibilitySummaryResponse,
  VisibilityTrendResponse,
} from "@/types/monitoring";

/**
 * SIGV2-1215: Copilot leaves the product, so no surface may render it.
 *
 * Each fixture here deliberately carries `bing` the way a real payload from a
 * project that selected Copilot while it was offered still would: a stored
 * prompt naming it, a provider breakdown row, a trend series, an entitlement
 * roster. The backend filters it out, and these tests pin the display side as
 * well, so a withdrawn engine cannot reappear through a cached response, an
 * older backend, or a list the client builds for itself.
 */

const requestJson = vi.hoisted(() => vi.fn());
vi.mock("@/services/http", () => ({ requestJson }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const entitlements: VisibilityEntitlements = {
  plan: "plan_executive",
  max_queries: 200,
  used_queries: 1,
  remaining_queries: 199,
  // The shape an older backend would still send.
  allowed_providers: ["google", "bing", "perplexity"],
  is_locked: false,
  estimated_cost_per_check: { google: 1, bing: 1, perplexity: 1 },
};

const queryWithCopilot: VisibilityQuerySummaryRow = {
  id: 1,
  project_id: 7,
  query_text: "best payroll software",
  query_type: "aeo",
  providers: ["google", "bing"],
  is_active: true,
  created_at: "2026-09-01T10:00:00.000Z",
  average_score: 50,
  last_checked_at: "2026-09-20T10:00:00.000Z",
  results: [
    {
      provider: "google",
      status: "cited",
      score: 80,
      last_checked_at: "2026-09-20T10:00:00.000Z",
    },
    {
      provider: "bing",
      status: "not_cited",
      score: 20,
      last_checked_at: "2026-09-20T10:00:00.000Z",
    },
  ],
};

const summary: VisibilitySummaryResponse = {
  project_id: 7,
  entitlements,
  queries_configured: 1,
  providers: ["google", "bing"],
  visibility_score: 50,
  score_breakdown: null,
  trend_delta: null,
  completed_checks: 2,
  pending_checks: 0,
  cited_checks: 1,
  total_checks: 2,
  last_updated_at: "2026-09-20T10:00:00.000Z",
  provider_breakdown: [
    {
      provider: "google",
      tracked_queries: 1,
      completed_checks: 1,
      cited_checks: 1,
      visibility_score: 80,
    },
    {
      provider: "bing",
      tracked_queries: 1,
      completed_checks: 1,
      cited_checks: 0,
      visibility_score: 20,
    },
  ],
  queries: [queryWithCopilot],
};

const trends: VisibilityTrendResponse = {
  project_id: 7,
  days: 30,
  providers: ["google", "bing"],
  points: [
    {
      date: "2026-09-20",
      visibility_score: 50,
      completed_checks: 2,
      cited_checks: 1,
      providers: { google: 80, bing: 20 },
    },
  ],
};

const comparative: ComparativeVisibilityResponse = {
  project_id: 7,
  // SIGV2-1208 freshness fields: a withdrawn engine must not reappear through
  // them either.
  competitors_last_measured_at: "2026-09-20T10:00:00.000Z",
  competitor_sweep_interval_seconds: 7 * 24 * 3600,
  domains: {
    "brand.example": {
      is_primary: true,
      label: "brand.example",
      providers: {
        google: { visibility_score: 70, cited_count: 2, total_checks: 3 },
        bing: { visibility_score: 10, cited_count: 0, total_checks: 3 },
      },
      trend: [{ date: "2026-09-20", scores: { google: 70, bing: 10 } }],
      share_of_voice: 60,
      last_measured_at: "2026-09-20T10:00:00.000Z",
    },
    "rival.example": {
      is_primary: false,
      label: "Rival",
      providers: {
        google: { visibility_score: 40, cited_count: 1, total_checks: 3 },
      },
      trend: [{ date: "2026-09-20", scores: { google: 40 } }],
      share_of_voice: 40,
      last_measured_at: "2026-09-20T10:00:00.000Z",
    },
  },
};

beforeEach(() => {
  requestJson.mockReset();
  requestJson.mockResolvedValue(comparative);
});

const expectNoCopilot = () => {
  expect(screen.queryByText(/Copilot/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/^bing$/i)).not.toBeInTheDocument();
};

describe("no surface renders Copilot (SIGV2-1215)", () => {
  it("keeps it out of the per-engine breakdown on the visibility score card", () => {
    render(<AIVisibilityScoreCard summary={summary} />);

    expect(screen.getByText("Gemini")).toBeInTheDocument();
    expectNoCopilot();
  });

  it("keeps it out of the query grid's engine columns", () => {
    render(<VisibilityQueryGrid summary={summary} />);

    expect(screen.getAllByText("Gemini").length).toBeGreaterThan(0);
    expectNoCopilot();
  });

  it("keeps it out of the trend chart's series and legend", () => {
    render(<VisibilityTrendChart trends={trends} />);

    expectNoCopilot();
  });

  it("keeps it out of the engine toggles a customer can select", () => {
    render(
      <VisibilityQueryManager
        projectId={7}
        queries={[queryWithCopilot]}
        entitlements={entitlements}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expectNoCopilot();
  });

  it("keeps it out of the add-prompt engine list", () => {
    render(
      <SignalAddPromptModal
        open
        projectId="7"
        entitlements={entitlements}
        getAuthHeaders={async () => ({})}
        onClose={vi.fn()}
        onCreated={vi.fn()}
      />
    );

    expectNoCopilot();
  });

  it("keeps it out of the brand-vs-competitor engine filter", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="7" />);

    // The chart has loaded: the competitor row is on screen.
    expect((await screen.findAllByText("Rival")).length).toBeGreaterThan(0);
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).not.toContain("Copilot");
    expectNoCopilot();
  });
});
