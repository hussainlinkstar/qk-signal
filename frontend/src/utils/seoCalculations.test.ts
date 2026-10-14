import { describe, expect, it } from "vitest";

import {
  calculateDelta,
  clampScore,
  computeScoreDelta,
  computeWeightedSeoIndex,
  filterActionsByCategory,
  getPriorityScore,
  normalizeScoreBreakdown,
  safeNumber,
  sortPriorityActions,
} from "./seoCalculations";

describe("seoCalculations", () => {
  it("clamps and normalizes invalid numeric values", () => {
    expect(clampScore("101")).toBe(100);
    expect(clampScore("-10")).toBe(0);
    expect(clampScore("NaN", 10, 20)).toBe(10);
    expect(safeNumber("x", 3)).toBe(3);
    expect(normalizeScoreBreakdown({ seo: "80", speed: null })).toEqual({
      seo: 80,
      speed: 0,
      indexing: 0,
      mobile: 0,
    });
  });

  it("computes deltas and weighted SEO index", () => {
    expect(
      computeScoreDelta(
        { seo: 80, speed: 70, indexing: 75, mobile: 65 },
        { seo: 60, speed: 50, indexing: 60, mobile: 70 }
      )
    ).toEqual({ seo: 20, speed: 20, indexing: 15, mobile: -5 });

    expect(computeWeightedSeoIndex({ seo: 80, speed: 70, indexing: 75, mobile: 65 })).toBe(74.5);
  });

  it("normalizes priority inputs and scores actions", () => {
    expect(getPriorityScore("High", "Low")).toBe(5);
    expect(getPriorityScore(3, 2)).toBe(4);
    expect(getPriorityScore("unknown", "unknown")).toBe(2);
  });

  it("sorts and filters priority actions", () => {
    const actions = [
      {
        id: "a",
        title: "Action A",
        description: "",
        category: "technical_seo" as const,
        priority: 2 as const,
        impact: "medium" as const,
        effort: "high" as const,
        eta_days: 5,
      },
      {
        id: "b",
        title: "Action B",
        description: "",
        category: "content_quality" as const,
        priority: 3 as const,
        impact: "high" as const,
        effort: "low" as const,
        eta_days: 2,
      },
      {
        id: "c",
        title: "Action C",
        description: "",
        category: "authority" as const,
        priority: 1 as const,
        impact: "low" as const,
        effort: "low" as const,
        eta_days: 7,
      },
    ];

    expect(sortPriorityActions(actions).map((action) => action.id)).toEqual(["b", "c", "a"]);
    expect(filterActionsByCategory(actions, "content").map((action) => action.id)).toEqual(["b"]);
    expect(filterActionsByCategory(actions, "backlinks").map((action) => action.id)).toEqual(["c"]);
    expect(filterActionsByCategory(actions, "all")).toHaveLength(3);
  });

  it("calculates trend delta with fallback when not enough audits", () => {
    expect(calculateDelta(84, 75)).toEqual({
      hasEnoughData: true,
      trend: "up",
      trendSymbol: "↑",
      percentage: 12,
    });

    expect(calculateDelta(60, 75)).toEqual({
      hasEnoughData: true,
      trend: "down",
      trendSymbol: "↓",
      percentage: 20,
    });

    expect(calculateDelta(80, undefined)).toEqual({
      hasEnoughData: false,
      trend: "flat",
      trendSymbol: "→",
      percentage: 0,
    });
  });
});
