import { describe, expect, it } from "vitest";

import {
  deriveProjectScoreTrends,
  scoreDeltaMeta,
  scoreTrendPoints,
  toScoreTrend,
} from "./projectScoreTrend";
import type { ProjectTrendResponse } from "@/services/workspaceService";

const point = (
  date: string,
  seo: number | null,
  aeo: number | null,
  geo: number | null
): ProjectTrendResponse["data_points"][number] => ({
  date,
  seo,
  geo,
  aeo,
  overall:
    [seo, geo, aeo].filter((value): value is number => typeof value === "number").length === 0
      ? null
      : [seo, geo, aeo]
          .filter((value): value is number => typeof value === "number")
          .reduce((sum, value) => sum + value, 0) /
        [seo, geo, aeo].filter((value): value is number => typeof value === "number").length,
  audit_count: 1,
  latest_audit_at: `${date}T10:00:00.000Z`,
});

const trend = (
  points: ProjectTrendResponse["data_points"],
  delta: ProjectTrendResponse["summary"]["delta"]
): ProjectTrendResponse => ({
  project_id: 42,
  period: "90d",
  granularity: "weekly",
  data_points: points,
  summary: {
    first: points[0] ?? null,
    latest: points[points.length - 1] ?? null,
    delta,
    trend_direction: { seo: "stable", geo: "stable", aeo: "stable", overall: "stable" },
  },
});

describe("scoreDeltaMeta", () => {
  it("signs and colours a rise, a fall and a measured standstill", () => {
    expect(scoreDeltaMeta(3)).toEqual({ cls: "text-(--good)", text: "▲ +3" });
    expect(scoreDeltaMeta(-4.2)).toEqual({ cls: "text-(--bad)", text: "▼ 4" });
    expect(scoreDeltaMeta(0)).toEqual({ cls: "text-(--t-3)", text: "→ 0" });
  });

  it("has nothing to say about a movement that was never measured", () => {
    expect(scoreDeltaMeta(null)).toBeNull();
    expect(scoreDeltaMeta(undefined)).toBeNull();
    expect(scoreDeltaMeta(Number.NaN)).toBeNull();
  });
});

describe("scoreTrendPoints", () => {
  it("falls back to the bucket's overall score and drops unscored buckets", () => {
    expect(
      scoreTrendPoints(
        [{ seo: 50, overall: 44 }, { seo: null, overall: 47 }, { overall: null }],
        "seo"
      )
    ).toEqual([50, 47]);
  });
});

describe("toScoreTrend", () => {
  it("reports nothing for a single scored bucket, which is a position not a movement", () => {
    expect(toScoreTrend(0, [62])).toBeNull();
    expect(toScoreTrend(3, [])).toBeNull();
  });

  it("reports nothing when the delta itself was never measured", () => {
    expect(toScoreTrend(null, [47, 52])).toBeNull();
  });
});

describe("deriveProjectScoreTrends", () => {
  it("reads the real series and deltas out of the project's trend payload", () => {
    const result = deriveProjectScoreTrends(
      trend(
        [
          point("2026-07-06", 66, 45, 49),
          point("2026-07-13", 70, 50, 54),
          point("2026-07-20", 74, 58, 62),
        ],
        { seo: 8, aeo: 13, geo: 13, overall: 11 }
      )
    );

    // AIO rolls AEO and GEO up 50/50, the same way every other AIO surface
    // does, so the plotted series is the rolled-up history, not a guess.
    expect(result.aio).toEqual({ delta: 13, points: [47, 52, 60] });
    expect(result.seo).toEqual({ delta: 8, points: [66, 70, 74] });
  });

  it("keeps only the last eight buckets, as the workspace overview card does", () => {
    const points = Array.from({ length: 11 }, (_, index) =>
      point(`2026-07-${String(index + 1).padStart(2, "0")}`, 50 + index, 40 + index, 40 + index)
    );
    const result = deriveProjectScoreTrends(
      trend(points, { seo: 10, aeo: 10, geo: 10, overall: 10 })
    );

    expect(result.seo?.points).toEqual([53, 54, 55, 56, 57, 58, 59, 60]);
    expect(result.aio?.points).toEqual([43, 44, 45, 46, 47, 48, 49, 50]);
  });

  it("reports no movement at all for a single scored audit", () => {
    const result = deriveProjectScoreTrends(
      trend([point("2026-07-20", 74, 58, 62)], { seo: 0, aeo: 0, geo: 0, overall: 0 })
    );

    expect(result).toEqual({ aio: null, seo: null });
  });

  it("reports no movement when there is no history to read", () => {
    expect(deriveProjectScoreTrends(null)).toEqual({ aio: null, seo: null });
    expect(
      deriveProjectScoreTrends(trend([], { seo: null, aeo: null, geo: null, overall: null }))
    ).toEqual({ aio: null, seo: null });
  });

  it("carries a fall through as a fall", () => {
    const result = deriveProjectScoreTrends(
      trend([point("2026-07-06", 74, 58, 62), point("2026-07-13", 69, 53, 55)], {
        seo: -5,
        aeo: -5,
        geo: -7,
        overall: -6,
      })
    );

    expect(result.seo).toEqual({ delta: -5, points: [74, 69] });
    expect(result.aio).toEqual({ delta: -6, points: [60, 54] });
  });
});
