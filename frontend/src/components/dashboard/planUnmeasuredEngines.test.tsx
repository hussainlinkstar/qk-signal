import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AIVisibilityScoreCard from "@/components/dashboard/AIVisibilityScoreCard";
import BrandVsCompetitorVisibilityChart from "@/components/dashboard/BrandVsCompetitorVisibilityChart";
import VisibilityQueryGrid from "@/components/dashboard/VisibilityQueryGrid";
import VisibilityQueryManager from "@/components/dashboard/VisibilityQueryManager";
import VisibilityTrendChart from "@/components/dashboard/VisibilityTrendChart";
import { tEn } from "@/test/i18nEn";
import type {
  ComparativeVisibilityResponse,
  VisibilityEntitlements,
  VisibilityQuerySummaryRow,
  VisibilitySummaryResponse,
  VisibilityTrendResponse,
} from "@/types/monitoring";

/**
 * SIGV2-1216: an engine a plan stopped measuring renders nowhere.
 *
 * Specialist stopped measuring Gemini when the plan was repriced, so a
 * Specialist project that was measured on it keeps its recorded cells while
 * the sweep stops refreshing them. Every fixture here carries `google` the way
 * such a payload really would: in the prompt row, the provider breakdown, the
 * trend series and the comparative domains, with a plan roster that no longer
 * includes it.
 *
 * The backend filters all of it already. This is the display-side half, for
 * the same reason as SIGV2-1215: a cached response or an older backend must
 * not be able to put a frozen card back on screen. The engine kept on screen
 * throughout is Perplexity, which Specialist does measure, so these tests show
 * the filter is per-engine rather than a blanket refusal.
 */

const requestJson = vi.hoisted(() => vi.fn());
vi.mock("@/services/http", () => ({ requestJson }));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const entitlements: VisibilityEntitlements = {
  plan: "plan_specialist",
  max_queries: 50,
  used_queries: 1,
  remaining_queries: 49,
  // The Specialist roster after SIGV2-1216: no `google`.
  allowed_providers: ["openai", "perplexity", "xai", "deepseek"],
  is_locked: false,
  estimated_cost_per_check: { openai: 1, perplexity: 1, xai: 1, deepseek: 1 },
};

const queryWithGemini: VisibilityQuerySummaryRow = {
  id: 1,
  project_id: 7,
  query_text: "best payroll software",
  query_type: "aeo",
  // Stored while the plan still measured Gemini.
  providers: ["google", "perplexity"],
  is_active: true,
  created_at: "2026-09-01T10:00:00.000Z",
  average_score: 55,
  last_checked_at: "2026-09-20T10:00:00.000Z",
  results: [
    {
      provider: "google",
      status: "cited",
      score: 90,
      last_checked_at: "2026-09-20T10:00:00.000Z",
    },
    {
      provider: "perplexity",
      status: "not_cited",
      score: 20,
      last_checked_at: "2026-10-08T10:00:00.000Z",
    },
  ],
};

const summary: VisibilitySummaryResponse = {
  project_id: 7,
  entitlements,
  queries_configured: 1,
  providers: ["google", "perplexity"],
  visibility_score: 55,
  score_breakdown: null,
  trend_delta: null,
  completed_checks: 2,
  pending_checks: 0,
  cited_checks: 1,
  total_checks: 2,
  last_updated_at: "2026-10-08T10:00:00.000Z",
  provider_breakdown: [
    {
      provider: "google",
      tracked_queries: 1,
      completed_checks: 1,
      cited_checks: 1,
      // The frozen number. It is the last thing Gemini ever measured.
      visibility_score: 90,
    },
    {
      provider: "perplexity",
      tracked_queries: 1,
      completed_checks: 1,
      cited_checks: 0,
      visibility_score: 20,
    },
  ],
  queries: [queryWithGemini],
};

const trends: VisibilityTrendResponse = {
  project_id: 7,
  days: 30,
  providers: ["google", "perplexity"],
  points: [
    {
      date: "2026-10-08",
      visibility_score: 55,
      completed_checks: 2,
      cited_checks: 1,
      providers: { google: 90, perplexity: 20 },
    },
  ],
};

const comparative: ComparativeVisibilityResponse = {
  project_id: 7,
  competitors_last_measured_at: "2026-10-01T10:00:00.000Z",
  competitor_sweep_interval_seconds: 7 * 24 * 3600,
  allowed_providers: ["openai", "perplexity", "xai", "deepseek"],
  domains: {
    "brand.example": {
      is_primary: true,
      label: "brand.example",
      providers: {
        google: { visibility_score: 90, cited_count: 2, total_checks: 3 },
        perplexity: { visibility_score: 20, cited_count: 0, total_checks: 3 },
      },
      trend: [{ date: "2026-10-08", scores: { google: 90, perplexity: 20 } }],
      share_of_voice: 60,
      last_measured_at: "2026-10-08T10:00:00.000Z",
    },
    "rival.example": {
      is_primary: false,
      label: "Rival",
      providers: {
        perplexity: { visibility_score: 40, cited_count: 1, total_checks: 3 },
      },
      trend: [{ date: "2026-10-08", scores: { perplexity: 40 } }],
      share_of_voice: 40,
      last_measured_at: "2026-10-01T10:00:00.000Z",
    },
  },
};

beforeEach(() => {
  requestJson.mockReset();
  requestJson.mockResolvedValue(comparative);
});

const expectNoGemini = () => {
  expect(screen.queryByText(/Gemini/i)).not.toBeInTheDocument();
  expect(screen.queryByText(/^google$/i)).not.toBeInTheDocument();
  // The frozen score itself must be gone, not merely unlabelled.
  expect(screen.queryByText("90%")).not.toBeInTheDocument();
};

describe("no surface renders an engine the plan stopped measuring (SIGV2-1216)", () => {
  it("gives it no card on the visibility score card", () => {
    render(<AIVisibilityScoreCard summary={summary} />);

    expect(screen.getByText("Perplexity")).toBeInTheDocument();
    expectNoGemini();
  });

  it("gives it no column in the query grid", () => {
    render(<VisibilityQueryGrid summary={summary} />);

    expect(screen.getAllByText("Perplexity").length).toBeGreaterThan(0);
    expectNoGemini();
  });

  it("gives it no line or legend entry in the trend chart", () => {
    render(
      <VisibilityTrendChart trends={trends} allowedProviders={entitlements.allowed_providers} />
    );

    expectNoGemini();
  });

  it("leaves the series alone when no roster is in scope", () => {
    // The guard that stops a payload which has not loaded yet from emptying a
    // list that should be full.
    render(<VisibilityTrendChart trends={trends} />);

    expect(screen.getAllByText("Gemini").length).toBeGreaterThan(0);
  });

  it("gives it no engine toggle on a prompt that still stores it", () => {
    render(
      <VisibilityQueryManager
        projectId={7}
        queries={[queryWithGemini]}
        entitlements={entitlements}
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
      />
    );

    expectNoGemini();
  });

  it("gives it no tab on the brand-vs-competitor engine filter", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="7" />);

    // The chart has loaded: the competitor row is on screen.
    expect((await screen.findAllByText("Rival")).length).toBeGreaterThan(0);
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs).not.toContain("Gemini");
    // The default tab was `google`, the very engine Specialist stopped
    // measuring, so without the roster the chart would open on an empty view.
    expect(tabs.length).toBeGreaterThan(0);
    expectNoGemini();
  });
  // SIGV2-1302 ---------------------------------------------------------------
  // The test above was intermittent, and chasing it found the cause rather
  // than a flake. `BrandVsCompetitorVisibilityChart` initialised its engine to
  // a hardcoded "google", the one engine Specialist stops measuring, and
  // corrected itself in an effect. An effect runs after the paint, so the
  // chart published a frame carrying Gemini's frozen score, and whether the
  // assertion saw it depended on which render pass it landed in.
  //
  // Same class as SIGV2-1263, where a hardcoded `["google"]` fallback survived
  // the plan. "Briefly" still counts: the rule is that no surface renders an
  // engine the plan stopped measuring.
  it("never paints a disallowed engine, not even before an effect could correct it", async () => {
    render(<BrandVsCompetitorVisibilityChart projectId="7" />);

    // Assert from the first paint onwards, not after the dust settles.
    expectNoGemini();

    expect((await screen.findAllByText("Rival")).length).toBeGreaterThan(0);
    expectNoGemini();

    // And the engine it did open on is one the plan measures.
    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent?.toLowerCase());
    expect(tabs.length).toBeGreaterThan(0);
    const selected = screen
      .getAllByRole("tab")
      .find((tab) => tab.getAttribute("aria-selected") === "true");
    if (selected) {
      expect(selected.textContent?.toLowerCase()).not.toBe("google");
      expect(selected.textContent?.toLowerCase()).not.toContain("gemini");
    }
  });
});
