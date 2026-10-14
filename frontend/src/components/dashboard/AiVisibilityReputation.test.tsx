import React from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AiVisibilityReputation from "@/components/dashboard/AiVisibilityReputation";
import { tEn } from "@/test/i18nEn";
import type { VisibilityProviderResult, VisibilitySummaryResponse } from "@/types/monitoring";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const entitlements = {
  plan: "plan_specialist",
  max_queries: 50,
  used_queries: 2,
  remaining_queries: 48,
  allowed_providers: ["google", "openai", "anthropic"] as const,
  is_locked: false,
  estimated_cost_per_check: { google: 1, openai: 1, anthropic: 1 },
};

const baseSummary: VisibilitySummaryResponse = {
  project_id: 1,
  entitlements: { ...entitlements, allowed_providers: [...entitlements.allowed_providers] },
  queries_configured: 2,
  providers: ["google", "openai"],
  visibility_score: 67,
  score_breakdown: null,
  trend_delta: null,
  completed_checks: 4,
  pending_checks: 0,
  cited_checks: 2,
  total_checks: 4,
  last_updated_at: "2026-09-28T10:00:00.000Z",
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
      tracked_queries: 2,
      completed_checks: 2,
      cited_checks: 0,
      visibility_score: 20,
    },
    {
      provider: "anthropic",
      tracked_queries: 0,
      completed_checks: 0,
      cited_checks: 0,
      visibility_score: null,
    },
  ],
  queries: [
    {
      id: 1,
      project_id: 1,
      query_text: "q1",
      query_type: "geo",
      providers: ["google", "openai"],
      is_active: true,
      created_at: null,
      updated_at: null,
      average_score: 60,
      last_checked_at: null,
      results: [
        {
          provider: "google",
          status: "cited",
          batch_status: "completed",
          score: 90,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 1,
          presence: { state: "domain_citation", live_measured: true, reason: null },
        },
        {
          provider: "openai",
          status: "not_cited",
          batch_status: "completed",
          score: 30,
          score_breakdown: {
            citation_presence: 0,
            citation_position: 0,
            text_mention: 12,
            topic_relevance: 10,
          },
          last_checked_at: null,
          citations_found: 0,
          presence: { state: "brand_mention", live_measured: true, reason: null },
        },
      ],
    },
    {
      id: 2,
      project_id: 1,
      query_text: "q2",
      query_type: "geo",
      providers: ["google", "openai"],
      is_active: true,
      created_at: null,
      updated_at: null,
      average_score: 55,
      last_checked_at: null,
      results: [
        {
          provider: "google",
          status: "cited",
          batch_status: "completed",
          score: 80,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 2,
          presence: { state: "domain_citation", live_measured: true, reason: null },
        },
        {
          provider: "openai",
          status: "not_cited",
          batch_status: "completed",
          score: 20,
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 0,
          presence: { state: "measured_absent", live_measured: true, reason: null },
        },
      ],
    },
  ],
};

// Presence: 3 of 4 completed cells show the brand (domain_citation x2 + brand_mention x1).
// Citations: cited_checks 2 of 4. Engines: google+openai completed, brand present on both.
// Brand mentions: 1 of 4 named the brand without citing the site.

const stripPresence = (summary: VisibilitySummaryResponse): VisibilitySummaryResponse => ({
  ...summary,
  queries: summary.queries.map((q) => ({
    ...q,
    results: q.results.map((r) => {
      const cell: VisibilityProviderResult = { ...r };
      delete cell.presence;
      return cell;
    }),
  })),
});

describe("AiVisibilityReputation", () => {
  it("renders measured values for the four wired metrics from visibility-summary", () => {
    render(<AiVisibilityReputation aioScore={62} opportunity={null} summary={baseSummary} />);

    const row = (key: string) => document.querySelector(`[data-metric-key="${key}"]`)!;

    // Answer Presence: brand appeared in 3 of 4 completed checks.
    expect(row("answerPresence").textContent).toContain("3/4");
    // Source Citations: cited_checks 2 of 4.
    expect(row("sourceCitations").textContent).toContain("2/4");
    // Engine Coverage: brand present on 2 of the 2 engines with completed checks.
    expect(row("engineCoverage").textContent).toContain("2/2");
    // Brand Mentions: 1 of 4 cells is brand_mention, named but not cited.
    expect(row("brandMentions").textContent).toContain("1/4");
  });

  it("renders Brand Mentions as unmeasured, never 0, when the cells carry no presence", () => {
    // Without `presence` a cell only reports whether it was cited, so a
    // citation cannot be separated from a bare mention. A 0 would claim we
    // measured and found none (SIGV2-1104).
    render(
      <AiVisibilityReputation
        aioScore={62}
        opportunity={null}
        summary={stripPresence(baseSummary)}
      />
    );

    const row = (key: string) => document.querySelector(`[data-metric-key="${key}"]`)!;
    expect(row("brandMentions").textContent).not.toMatch(/\d/);
    expect(row("brandMentions").textContent).toContain(tEn("signalOverview.vrReasonNoData"));
    // The cited/not-cited fallback still measures the three neighbours.
    expect(row("answerPresence").textContent).toContain("2/4");
    expect(row("sourceCitations").textContent).toContain("2/4");
  });

  it("names the plan gate on the Brand Mentions row when the feature is locked", () => {
    render(
      <AiVisibilityReputation
        aioScore={62}
        opportunity={null}
        summary={{
          ...baseSummary,
          entitlements: { ...baseSummary.entitlements, is_locked: true },
        }}
      />
    );
    expect(document.querySelector('[data-metric-key="brandMentions"]')!.textContent).toContain(
      tEn("signalOverview.brandMentionsReason")
    );
  });

  it("keeps the unmeasured state when the plan locks the feature", () => {
    render(
      <AiVisibilityReputation
        aioScore={62}
        opportunity={null}
        summary={{
          ...baseSummary,
          entitlements: { ...baseSummary.entitlements, is_locked: true },
        }}
      />
    );
    for (const key of ["answerPresence", "sourceCitations", "engineCoverage", "brandMentions"]) {
      expect(document.querySelector(`[data-metric-key="${key}"]`)!.textContent).not.toMatch(
        /\d\/\d/
      );
    }
  });

  it("keeps the unmeasured state when no monitoring run has completed", () => {
    render(
      <AiVisibilityReputation
        aioScore={62}
        opportunity={null}
        summary={{
          ...baseSummary,
          completed_checks: 0,
          cited_checks: 0,
          queries: [],
          provider_breakdown: [],
        }}
      />
    );
    for (const key of ["answerPresence", "sourceCitations", "engineCoverage", "brandMentions"]) {
      expect(document.querySelector(`[data-metric-key="${key}"]`)!.textContent).not.toMatch(
        /\d\/\d/
      );
    }
  });

  it("keeps the unmeasured state while the summary has not loaded", () => {
    render(<AiVisibilityReputation aioScore={62} opportunity={null} summary={null} />);
    for (const key of ["answerPresence", "sourceCitations", "engineCoverage", "brandMentions"]) {
      expect(document.querySelector(`[data-metric-key="${key}"]`)!.textContent).not.toMatch(
        /\d\/\d/
      );
    }
  });

  it("renders only the four VISIBILITY rows, with no TRUST group left behind", () => {
    render(<AiVisibilityReputation aioScore={62} opportunity={null} summary={baseSummary} />);
    expect(
      [...document.querySelectorAll("[data-metric-key]")].map((e) =>
        e.getAttribute("data-metric-key")
      )
    ).toEqual(["answerPresence", "sourceCitations", "engineCoverage", "brandMentions"]);
  });
});
