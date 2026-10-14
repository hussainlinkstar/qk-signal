import type { PriorityAction, ScoreBreakdown, ScoreKey } from "@/types/aiStrategist";

export type PriorityCategoryFilter = "all" | "technical" | "content" | "backlinks";

export type DeltaResult = {
  hasEnoughData: boolean;
  trend: "up" | "down" | "flat";
  trendSymbol: "↑" | "↓" | "→";
  percentage: number;
};

const HIGH_MEDIUM_LOW_SCALE: Record<string, number> = {
  high: 3,
  medium: 2,
  low: 1,
};

export const clampScore = (value: unknown, min = 0, max = 100): number => {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) {
    return min;
  }
  return Math.max(min, Math.min(max, n));
};

export const safeNumber = (value: unknown, fallback = 0): number => {
  const n = typeof value === "number" ? value : Number(value);
  return Number.isFinite(n) ? n : fallback;
};

export const normalizeScoreBreakdown = (
  input: Partial<Record<ScoreKey, unknown>>
): ScoreBreakdown => ({
  seo: clampScore(input.seo),
  speed: clampScore(input.speed),
  indexing: clampScore(input.indexing),
  mobile: clampScore(input.mobile),
});

export const computeScoreDelta = (
  current: ScoreBreakdown,
  previous?: ScoreBreakdown
): Partial<Record<ScoreKey, number>> => {
  if (!previous) {
    return {};
  }

  return {
    seo: current.seo - previous.seo,
    speed: current.speed - previous.speed,
    indexing: current.indexing - previous.indexing,
    mobile: current.mobile - previous.mobile,
  };
};

export const computeWeightedSeoIndex = (
  score: ScoreBreakdown,
  weights: Partial<Record<ScoreKey, number>> = {}
): number => {
  const w = {
    seo: weights.seo ?? 0.4,
    speed: weights.speed ?? 0.2,
    indexing: weights.indexing ?? 0.25,
    mobile: weights.mobile ?? 0.15,
  };

  const total = w.seo + w.speed + w.indexing + w.mobile || 1;
  const raw =
    score.seo * w.seo +
    score.speed * w.speed +
    score.indexing * w.indexing +
    score.mobile * w.mobile;

  return clampScore(raw / total);
};

export const normalizePriorityMetric = (value: unknown): number => {
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (normalized in HIGH_MEDIUM_LOW_SCALE) {
      return HIGH_MEDIUM_LOW_SCALE[normalized];
    }
  }

  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return HIGH_MEDIUM_LOW_SCALE.medium;
  }

  return Math.max(1, Math.min(3, numeric));
};

export const getPriorityScore = (impact: unknown, effort: unknown): number => {
  const normalizedImpact = normalizePriorityMetric(impact);
  const normalizedEffort = normalizePriorityMetric(effort);

  return normalizedImpact * 2 - normalizedEffort;
};

export const sortPriorityActions = (actions: PriorityAction[]): PriorityAction[] =>
  [...actions].sort((a, b) => {
    const scoreDiff = getPriorityScore(b.impact, b.effort) - getPriorityScore(a.impact, a.effort);

    if (scoreDiff !== 0) {
      return scoreDiff;
    }

    return (a.priority ?? Number.MAX_SAFE_INTEGER) - (b.priority ?? Number.MAX_SAFE_INTEGER);
  });

export const normalizeActionCategory = (value: unknown): Exclude<PriorityCategoryFilter, "all"> => {
  const normalized = String(value ?? "")
    .trim()
    .toLowerCase();

  if (["content", "content_quality"].includes(normalized)) {
    return "content";
  }

  if (["backlinks", "authority", "offpage", "off_page"].includes(normalized)) {
    return "backlinks";
  }

  return "technical";
};

export const filterActionsByCategory = (
  actions: PriorityAction[],
  category: PriorityCategoryFilter
): PriorityAction[] => {
  if (category === "all") {
    return actions;
  }

  return actions.filter((action) => normalizeActionCategory(action.category) === category);
};

export const calculateDelta = (
  latestValue?: number | null,
  previousValue?: number | null
): DeltaResult => {
  if (!Number.isFinite(latestValue) || !Number.isFinite(previousValue)) {
    return { hasEnoughData: false, trend: "flat", trendSymbol: "→", percentage: 0 };
  }

  const current = Number(latestValue);
  const previous = Number(previousValue);

  if (previous === 0) {
    const trend = current === 0 ? "flat" : "up";
    return {
      hasEnoughData: true,
      trend,
      trendSymbol: trend === "up" ? "↑" : "→",
      percentage: current === 0 ? 0 : 100,
    };
  }

  const diff = ((current - previous) / Math.abs(previous)) * 100;
  const rounded = Math.round(Math.abs(diff));

  if (diff > 0) {
    return { hasEnoughData: true, trend: "up", trendSymbol: "↑", percentage: rounded };
  }

  if (diff < 0) {
    return { hasEnoughData: true, trend: "down", trendSymbol: "↓", percentage: rounded };
  }

  return { hasEnoughData: true, trend: "flat", trendSymbol: "→", percentage: 0 };
};
