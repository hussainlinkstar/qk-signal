/**
 * Unified score color utility, single source of truth for
 * threshold breakpoints and color tokens across all components.
 */

export type ScoreLevel = "excellent" | "warning" | "critical";

export type ScoreColorResult = {
  level: ScoreLevel;
  /** Tailwind text color class */
  text: string;
  /** Tailwind bg color class */
  bg: string;
  /** Hex color for SVG/Canvas usage */
  hex: string;
  /** Human-readable label */
  label: string;
};

/**
 * Returns consistent color tokens for a 0-100 score.
 *
 * Thresholds:
 *  - ≥ 71 → excellent (GEO teal)
 *  - ≥ 41 → warning (amber)
 *  - < 41 → critical (red)
 */
export function getScoreColor(score: number): ScoreColorResult {
  if (score >= 71)
    return {
      level: "excellent",
      text: "text-success",
      bg: "bg-success",
      hex: "#16A34A",
      label: "Strong",
    };
  if (score >= 41)
    return {
      level: "warning",
      text: "text-warning",
      bg: "bg-warning",
      hex: "#D97706",
      label: "Developing",
    };
  return {
    level: "critical",
    text: "text-danger",
    bg: "bg-danger",
    hex: "#DC2626",
    label: "Critical",
  };
}

/**
 * Returns just the hex color string for SVG stroke usage.
 */
export function getScoreStrokeHex(score: number): string {
  return getScoreColor(score).hex;
}
