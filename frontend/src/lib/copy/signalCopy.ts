import type { RoleMode } from "@/lib/roleMode";

/**
 * Deterministic, per-role copy layer (Qiko Signal — Phase 9, Tasks 9.1 + 9.3).
 *
 * Maps a raw signal `(metricKey, value, roleMode)` into a role-appropriate,
 * human-readable statement: `{ label, interpretation, nextAction? }`.
 *
 * Design constraints (see signal_persona_ux_redesign_spec.md §4):
 *  - Pure functions only — no I/O, no React, no fetch, no side effects.
 *  - Deterministic — same input always yields the same output.
 *  - English-only copy.
 *  - Numbers carry meaning: a 0–1 or 0–100 score is rendered as `X/100`
 *    plus an interpretive clause; never a bare number.
 *  - No banned jargon ("neural", "market dominance") in any output.
 */

export type CopyResult = {
  label: string;
  interpretation: string;
  nextAction?: string;
};

/** Static, presentational metadata for each supported metric. */
type MetricMeta = {
  /** Specialist/raw short code, e.g. "AIO". */
  code: string;
  /** Plain, client-friendly name, e.g. "AI answer visibility". */
  plainName: string;
  /** The plural noun describing where the brand appears, for "~X of 10" copy. */
  surfaceNoun: string;
};

const METRIC_META: Record<string, MetricMeta> = {
  seo: {
    code: "SEO",
    plainName: "search visibility",
    surfaceNoun: "relevant searches",
  },
  aio: {
    code: "AIO",
    plainName: "AI answer visibility",
    surfaceNoun: "relevant AI answers",
  },
  aeo: {
    code: "AI answers",
    plainName: "AI answers visibility",
    surfaceNoun: "relevant AI answers",
  },
  geo: {
    code: "AI visibility",
    plainName: "AI visibility",
    surfaceNoun: "relevant AI-generated answers",
  },
};

/** Fallback metadata for unknown metric keys (never throws). */
function metaFor(metricKey: string): MetricMeta {
  const known = METRIC_META[metricKey];
  if (known) {
    return known;
  }
  const code =
    metricKey
      .replace(/[^a-z0-9]+/gi, " ")
      .trim()
      .toUpperCase() || "SIGNAL";
  return {
    code,
    plainName: "visibility",
    surfaceNoun: "relevant results",
  };
}

/**
 * Normalize a score to an integer 0–100.
 * Values in the 0–1 range are treated as fractions (0.42 → 42); values above 1
 * are treated as already on a 0–100 scale. Result is clamped to [0, 100].
 */
function toScore100(value: number): number {
  const scaled = value > 0 && value <= 1 ? value * 100 : value;
  const rounded = Math.round(scaled);
  return Math.max(0, Math.min(100, rounded));
}

/** Roughly "X of 10", used for plain-language framing. */
function outOfTen(score100: number): number {
  return Math.round(score100 / 10);
}

type Band = "low" | "limited" | "moderate" | "solid" | "strong";

function bandFor(score100: number): Band {
  if (score100 >= 80) return "strong";
  if (score100 >= 60) return "solid";
  if (score100 >= 40) return "moderate";
  if (score100 >= 20) return "limited";
  return "low";
}

const BAND_WORD: Record<Band, string> = {
  low: "low",
  limited: "limited",
  moderate: "moderate",
  solid: "solid",
  strong: "strong",
};

/** Per-role copy builders: each takes resolved metric facts and returns copy. */
type RoleBuilder = (args: {
  meta: MetricMeta;
  score: number;
  band: Band;
  perTen: number;
}) => CopyResult;

const ROLE_BUILDERS: Record<RoleMode, RoleBuilder> = {
  // Plain, benefit-led language. No raw codes, no jargon.
  marketer: ({ meta, score, perTen }) => ({
    label: `${capitalize(meta.plainName)} ${score}/100`,
    interpretation: `You appear in ~${perTen} of 10 ${meta.surfaceNoun} — there's clear room to grow.`,
    nextAction: "Focus on the few actions that lift visibility the most.",
  }),

  // Raw stats first, then the diagnostic read. Specialists want the numbers.
  specialist: ({ meta, score, band }) => ({
    label: `${meta.code} ${score}/100`,
    interpretation: `${capitalize(BAND_WORD[band])} — ${meta.code} sits at ${score}/100, against a healthy threshold of 60/100.`,
    nextAction: "Prioritise the highest-severity findings first.",
  }),

  // Client-ready summary phrasing with an attached plan.
  agency: ({ meta, score, band }) => ({
    label: `${capitalize(meta.plainName)} ${score}/100`,
    interpretation: `Your brand's ${meta.plainName} is ${BAND_WORD[band]} (${score}/100). A prioritised action plan is included.`,
    nextAction: "Share the prioritised action plan with the client.",
  }),

  // Governance framing: markets, drift vs baseline, claims to verify.
  enterprise: ({ meta, score, band }) => ({
    label: `${meta.code} ${score}/100`,
    interpretation: `AI visibility ${score}/100 (${BAND_WORD[band]}) across tracked markets. Watch for drift vs baseline and verify any unsupported claims.`,
    nextAction: "Review the claim ledger and set a drift alert vs baseline.",
  }),

  // Simplest possible framing for someone just exploring.
  explorer: ({ meta, score, perTen }) => ({
    label: `${capitalize(meta.plainName)}: ${score}/100`,
    interpretation: `You show up about ${perTen} in 10 times. Let's fix the easiest things first.`,
    nextAction: "Start with the 2 simplest fixes.",
  }),
};

function capitalize(text: string): string {
  return text.length === 0 ? text : text[0].toUpperCase() + text.slice(1);
}

/** Copy used when there is no score to show yet (value === null). */
function noDataCopy(meta: MetricMeta, role: RoleMode): CopyResult {
  const base: CopyResult = {
    label: `${meta.code} — not enough data yet`,
    interpretation: "Not enough data yet to score this — run or refresh the audit to populate it.",
  };
  if (role === "specialist" || role === "enterprise") {
    base.nextAction = "Re-run the audit to collect the missing signals.";
  }
  return base;
}

/**
 * Map a raw signal into a role-appropriate, human-readable statement.
 * Pure and deterministic. Unknown metric keys fall back to generic copy;
 * `null` values yield a graceful "not enough data yet" result (no bare number).
 */
export function describeScore(metricKey: string, value: number | null, role: RoleMode): CopyResult {
  const meta = metaFor(metricKey);

  if (value === null || Number.isNaN(value)) {
    return noDataCopy(meta, role);
  }

  const score = toScore100(value);
  const band = bandFor(score);
  const perTen = outOfTen(score);

  const build = ROLE_BUILDERS[role] ?? ROLE_BUILDERS.marketer;
  return build({ meta, score, band, perTen });
}

/**
 * Replacement glossary (Task 9.3): jargon → plain language, aligned to the
 * Phase 10 renames (Deep Analysis, competitive_positioning, debate_findings).
 * Keys are the legacy/jargon terms; values are the plain UI replacements.
 * No replacement value may contain banned jargon ("neural", "market dominance").
 */
export const GLOSSARY: Record<string, string> = {
  neural: "AI",
  neural_authority: "AI authority",
  neural_debate: "debate findings",
  market_dominance: "competitive positioning",
  "market dominance": "competitive positioning",
  market_dominance_index: "competitive positioning score",
  generative_authority_metrics: "AI authority signals",
  deep_judgment: "Deep Analysis",
  citation_share: "citation share",
  brand_anchor: "brand strength",
  visibility_index: "visibility score",
  answerability_score: "answer readiness",
  extractable_pages: "answer-ready pages",
  seo: "search visibility",
  aio: "AI answer visibility",
  aeo: "answer-engine visibility",
  geo: "generative AI visibility",
};
