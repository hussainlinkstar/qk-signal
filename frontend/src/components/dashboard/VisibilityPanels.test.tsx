import React from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";

import VisibilityPanels from "./VisibilityPanels";
import en from "@/i18n/en.json";
import type { ScoreTrend } from "@/lib/projectScoreTrend";
import type { VisibilityProviderResult, VisibilitySummaryResponse } from "@/types/monitoring";

const copy = en.signalOverview;
const PROMPTS_HREF = "/dashboard/projects/42/ai-answers?tab=prompts";

// Same shape as the AiVisibilityReputation fixture: 3 of 4 completed cells
// show the brand (domain_citation x2 + brand_mention x1).
const baseSummary: VisibilitySummaryResponse = {
  project_id: 42,
  entitlements: {
    plan: "plan_specialist",
    max_queries: 50,
    used_queries: 2,
    remaining_queries: 48,
    allowed_providers: ["google", "openai"],
    is_locked: false,
    estimated_cost_per_check: { google: 1, openai: 1 },
  },
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
  ],
  queries: [
    {
      id: 1,
      project_id: 42,
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
          score_breakdown: null,
          last_checked_at: null,
          citations_found: 0,
          presence: { state: "brand_mention", live_measured: true, reason: null },
        },
      ],
    },
    {
      id: 2,
      project_id: 42,
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

const renderPanels = (
  summary: VisibilitySummaryResponse | null,
  trends: { aioTrend?: ScoreTrend | null; seoTrend?: ScoreTrend | null } = {}
) =>
  render(
    <VisibilityPanels
      aioScore={61}
      seoScore={72}
      aioTarget={78}
      seoTarget={85}
      aioHref="/dashboard/projects/42/ai-answers"
      seoHref="/dashboard/projects/42/google"
      promptsHref={PROMPTS_HREF}
      summary={summary}
      {...trends}
    />
  );

const appearanceRow = () => document.querySelector('[data-stat="appearance"]')!;

/* SIGV2-1125: the unmeasured state's explanation lives in the (i) tooltip
   already attached to the row, not as a third line of row body text, so it
   has to be opened to be read. Focus alone opens it, no pointer. */
const openStatInfo = async () => {
  const trigger = appearanceRow().querySelector<HTMLElement>("[data-stat-info]")!;
  await act(async () => {
    trigger.focus();
  });
  return trigger;
};

describe("Appearance in AI answers (SIGV2-1111)", () => {
  it("renders the measured ratio the visibility summary supports", () => {
    renderPanels(baseSummary);

    // The same measurement as the "Answer Presence" row lower down the page,
    // from the one shared derivation: the brand appeared in 3 of 4 completed
    // checks.
    expect(appearanceRow().textContent).toContain(copy.appearanceStat);
    expect(appearanceRow().textContent).toContain("3/4");
    expect(appearanceRow().textContent).not.toContain(copy.notMeasured);
  });

  it("renders unmeasured with a reason, never 0, when no run has completed", async () => {
    renderPanels({ ...baseSummary, completed_checks: 0, cited_checks: 0, queries: [] });

    expect(appearanceRow().textContent).toContain(copy.notMeasured);
    expect(appearanceRow().textContent).not.toMatch(/\d/);

    // The row says "Not measured"; the (i) says why. Neither is a 0.
    await openStatInfo();
    await waitFor(() =>
      expect(screen.getAllByText(copy.appearanceStatReasonNoRun).length).toBeGreaterThan(0)
    );
  });

  it("renders unmeasured with the plan reason, never 0, when the entitlement is locked", async () => {
    renderPanels({
      ...baseSummary,
      entitlements: { ...baseSummary.entitlements, is_locked: true },
    });

    expect(appearanceRow().textContent).toContain(copy.notMeasured);
    expect(appearanceRow().textContent).not.toMatch(/\d/);

    await openStatInfo();
    await waitFor(() =>
      expect(screen.getAllByText(copy.appearanceStatReasonLocked).length).toBeGreaterThan(0)
    );
  });

  it("renders unmeasured while the summary has not loaded", () => {
    renderPanels(null);

    expect(appearanceRow().textContent).toContain(copy.notMeasured);
    expect(appearanceRow().textContent).not.toMatch(/\d/);
  });

  it("keeps the unmeasured reason out of the row body so the pair keeps one height", () => {
    renderPanels({ ...baseSummary, completed_checks: 0, cited_checks: 0, queries: [] });

    // The sentence used to render here and made the AIO card three lines
    // taller than the SEO card (SIGV2-1125).
    expect(appearanceRow().textContent).not.toContain(copy.appearanceStatReasonNoRun);
  });

  it("drops the reason from the explanation once the figure is measured", async () => {
    renderPanels(baseSummary);

    await openStatInfo();
    await waitFor(() =>
      expect(screen.getAllByText(copy.appearanceStatInfo).length).toBeGreaterThan(0)
    );
    expect(screen.queryByText(copy.appearanceStatReasonNoRun)).not.toBeInTheDocument();
    expect(screen.queryByText(copy.appearanceStatReasonLocked)).not.toBeInTheDocument();
  });

  it("reads the same derivation as the Answer Presence row, including its fallback", () => {
    // Cells without `presence` fall back to the cited/not-cited status, which
    // is what the VISIBILITY row does with the same payload: 2 of 4 cited.
    // One derivation, one number, on both halves of the page.
    const noPresence: VisibilitySummaryResponse = {
      ...baseSummary,
      queries: baseSummary.queries.map((q) => ({
        ...q,
        results: q.results.map((r) => {
          const cell: VisibilityProviderResult = { ...r };
          delete cell.presence;
          return cell;
        }),
      })),
    };
    renderPanels(noPresence);

    expect(appearanceRow().textContent).toContain("2/4");
  });

  it("explains the figure through a keyboard-reachable (i) that links to Prompts", async () => {
    renderPanels(baseSummary);

    const trigger = screen.getByRole("link", { name: copy.appearanceStatInfoCta });
    expect(trigger).toHaveAttribute("href", PROMPTS_HREF);
    expect(appearanceRow()).toContainElement(trigger);

    // A native link, so it is in the tab order, and its accessible name names
    // the destination rather than relying on a hover-only title attribute.
    expect(trigger).not.toHaveAttribute("title");

    // Focus alone, no pointer, reveals the explanation.
    await act(async () => {
      trigger.focus();
    });
    expect(trigger).toHaveFocus();
    await waitFor(() =>
      expect(screen.getAllByText(copy.appearanceStatInfo).length).toBeGreaterThan(0)
    );
  });

  it("keeps the peer comparison labels out of the card", () => {
    renderPanels(baseSummary);
    for (const pattern of [/Below average/i, /Above average/i, /Low Volume/i]) {
      expect(screen.queryByText(pattern)).not.toBeInTheDocument();
    }
  });
});

/* SIGV2-1181: the progressive change under each gauge. The series and the
   delta are the project's own score history, the same movement the workspace
   overview card reports, so a project with no progression must show neither
   rather than a flat line, a single point or a 0. */
describe("Gauge trend and sparkline (SIGV2-1181)", () => {
  const trendBlock = (variant: "aio" | "seo") =>
    document.querySelector(`[data-score-trend="${variant}"]`);
  const sparkFor = (variant: "aio" | "seo") =>
    trendBlock(variant)?.parentElement?.querySelector("svg[data-spark]") ?? null;

  it("draws the real series and the signed delta once there are two scored audits", () => {
    renderPanels(baseSummary, {
      aioTrend: { delta: 3, points: [47, 49, 52, 50, 55, 57, 59, 62] },
      seoTrend: { delta: 2, points: [66, 68, 69, 70, 72, 73, 74, 76] },
    });

    expect(trendBlock("aio")).not.toBeNull();
    expect(trendBlock("aio")!.textContent).toBe("▲ +3");
    expect(trendBlock("aio")!.querySelector("span")!.className).toContain("text-(--good)");
    expect(sparkFor("aio")).toHaveAttribute("data-spark", "47,49,52,50,55,57,59,62");

    expect(trendBlock("seo")!.textContent).toBe("▲ +2");
    expect(sparkFor("seo")).toHaveAttribute("data-spark", "66,68,69,70,72,73,74,76");
  });

  it("explains the movement to a screen reader", () => {
    renderPanels(baseSummary, { aioTrend: { delta: 3, points: [59, 62] } });

    expect(
      screen.getByLabelText(
        copy.scoreTrendLabel.replace("{{name}}", "AIO").replace("{{change}}", "+3")
      )
    ).toBeInTheDocument();
  });

  it("says nothing at all when the project has fewer than two scored audits", () => {
    renderPanels(baseSummary, { aioTrend: null, seoTrend: null });

    expect(trendBlock("aio")).toBeNull();
    expect(trendBlock("seo")).toBeNull();
    expect(document.querySelectorAll("svg[data-spark]")).toHaveLength(0);
    // No trend, no lift: the gauge keeps its own position on the card.
    expect(document.querySelector("[data-score-gauge]")!.className).not.toContain("-mt-2.5");
  });

  it("renders a fall as a fall, with the negative sign and colour", () => {
    renderPanels(baseSummary, { seoTrend: { delta: -4, points: [76, 74, 70, 68] } });

    expect(trendBlock("seo")!.textContent).toBe("▼ 4");
    expect(trendBlock("seo")!.querySelector("span")!.className).toContain("text-(--bad)");
    expect(trendBlock("seo")!.querySelector("span")!.className).not.toContain("text-(--good)");
    expect(sparkFor("seo")).toHaveAttribute("data-spark", "76,74,70,68");
    expect(
      screen.getByLabelText(
        copy.scoreTrendLabel.replace("{{name}}", "SEO").replace("{{change}}", "-4")
      )
    ).toBeInTheDocument();
  });
});
