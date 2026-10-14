/**
 * Shared style-token constants for signal-light components. Mirrors the
 * pattern already used by cardStyleTokens.ts / tableTokens.ts / chartTokens.ts
 * for the dark theme, scoped to the signal-light design system instead.
 * Source of truth: /Users/user/signal-MVP/signal.css.
 */

export type SignalScoreLevel = "good" | "warn" | "bad";

/** Mirrors src/lib/scoreColors.ts's 71/41 thresholds, mapped to signal colors. */
export function signalScoreLevel(score: number): SignalScoreLevel {
  if (score >= 71) return "good";
  if (score >= 41) return "warn";
  return "bad";
}

/* SVG gauge strokes are decorative, so they take the approved signal.css
   values verbatim (#12A150/#D9930B/#E5484D). They intentionally differ from
   the --good/--warn/--bad tokens, which hold darker accessible values for
   text (recorded deviation in globals.css). Text must go through
   SIGNAL_SCORE_TEXT_CLASS / SIGNAL_DELTA_CLASS, not these hexes. */
export const SIGNAL_SCORE_STROKE: Record<SignalScoreLevel, string> = {
  good: "#12A150",
  warn: "#D9930B",
  bad: "#E5484D",
};

export const SIGNAL_SCORE_TEXT_CLASS: Record<SignalScoreLevel, string> = {
  good: "text-(--good)",
  warn: "text-(--warn)",
  bad: "text-(--bad)",
};

export const SIGNAL_CARD_CLASS = "rounded-[16px] border border-(--line) bg-(--panel)";

export const SIGNAL_DELTA_CLASS: Record<"up" | "dn" | "flat", string> = {
  up: "text-(--good)",
  dn: "text-(--bad)",
  flat: "text-(--t-3)",
};
