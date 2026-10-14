// Shared score-trend derivation (SIGV2-1181). The workspace overview's project
// cards and the project overview's AIO/SEO gauges must report the same movement
// for the same project, so both read the same audit history through this one
// module: the backend's `build_workspace_trends_overview` sparkline is literally
// the last 8 weekly buckets of `build_project_trend_payload` over 90 days, so
// asking `/api/projects/{id}/trends?period=90d&granularity=weekly` for one
// project returns the same buckets the workspace card already draws.

import type { ProjectTrendResponse } from "@/services/workspaceService";

/** The workspace overview asks for `90d` and the backend buckets its per-project
    sparkline weekly, keeping the last 8 buckets. */
export const SCORE_TREND_PERIOD = "90d" as const;
export const SCORE_TREND_GRANULARITY = "weekly" as const;
export const SCORE_TREND_MAX_POINTS = 8;

/** Approved sparkline accents under the gauges: AIO purple, SEO amber. */
export const AIO_TREND_COLOR = "#9333EA";
export const SEO_TREND_COLOR = "#D9930B";

export type ScoreTrendPoint = {
  seo?: number | null;
  aio?: number | null;
  overall: number | null;
};

/** A movement there is something to draw: at least two scored buckets and a
    real delta between the first and the last of them. */
export type ScoreTrend = {
  delta: number;
  points: number[];
};

export type ScoreTrendPair = {
  aio: ScoreTrend | null;
  seo: ScoreTrend | null;
};

export type ScoreDeltaMeta = { cls: string; text: string };

const average = (values: Array<number | null | undefined>): number | null => {
  const valid = values.filter((value): value is number => typeof value === "number");
  if (valid.length === 0) return null;
  return valid.reduce((sum, value) => sum + value, 0) / valid.length;
};

/** Sign, arrow and colour of a score movement. A rise is `--good`, a fall is
    `--bad` with its own minus sign, and a measured standstill is neutral. */
export const scoreDeltaMeta = (value: number | null | undefined): ScoreDeltaMeta | null => {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const rounded = Math.round(value);
  if (rounded > 0) return { cls: "text-(--good)", text: `↗ +${rounded}` };
  if (rounded < 0) return { cls: "text-(--bad)", text: `↘ ${rounded}` };
  return { cls: "text-(--t-3)", text: "→ 0" };
};

/** Scored values of one pillar, in bucket order. A bucket the pillar does not
    cover falls back to the bucket's overall score, exactly as the workspace
    overview card does, and a bucket with neither is dropped rather than
    plotted as a 0. */
export const scoreTrendPoints = (
  sparkline: ScoreTrendPoint[] | null | undefined,
  key: "seo" | "aio"
): number[] =>
  (sparkline ?? [])
    .map((point) => point[key] ?? point.overall)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));

/** One scored audit is a position, not a progression: with fewer than two
    scored buckets there is no movement to report, so the surface renders
    neither a delta nor a sparkline instead of a flat line or a 0. */
export const toScoreTrend = (
  delta: number | null | undefined,
  points: number[]
): ScoreTrend | null => {
  if (points.length < 2) return null;
  if (typeof delta !== "number" || !Number.isFinite(delta)) return null;
  return { delta, points };
};

/** AIO and SEO movement for one project, from the project's own trend payload.
    AIO rolls AEO and GEO up the way every other AIO surface does (`aioScore`,
    and the backend's own 50/50 `derive_aio`), and the deltas are the payload's
    own first-to-latest deltas, which is what the workspace card reads. */
export const deriveProjectScoreTrends = (
  trend: ProjectTrendResponse | null | undefined
): ScoreTrendPair => {
  const sparkline: ScoreTrendPoint[] = (trend?.data_points ?? [])
    .slice(-SCORE_TREND_MAX_POINTS)
    .map((point) => ({
      seo: point.seo,
      aio: average([point.aeo, point.geo]),
      overall: point.overall,
    }));
  return {
    aio: toScoreTrend(
      average([trend?.summary.delta.aeo, trend?.summary.delta.geo]),
      scoreTrendPoints(sparkline, "aio")
    ),
    seo: toScoreTrend(trend?.summary.delta.seo, scoreTrendPoints(sparkline, "seo")),
  };
};
