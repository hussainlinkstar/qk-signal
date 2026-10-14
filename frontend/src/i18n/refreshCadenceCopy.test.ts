import { readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import en from "./en.json";
import ar from "./ar.json";

/**
 * SIGV2-1229: copy that states how often a number refreshes is a claim about
 * that number's freshness.
 *
 * The competitor gate said "Search and visibility scores for every rival,
 * updated daily." while the competitor sweep had been weekly since SIGV2-1208.
 * Same class as SIGV2-1215 and SIGV2-1216: a surface asserting a measurement
 * the backend is not taking.
 *
 * The sentence was a literal, so nothing failed when the cadence moved. This
 * test derives the cadence word from the backend's own interval, recorded in
 * `contracts/visibility_providers.json` and pinned to `VISIBILITY_PLAN_LIMITS`
 * by `backend/tests/test_visibility_provider_contract.py`. Changing a cadence
 * in the backend therefore fails a test that names the sentence to fix, rather
 * than leaving the claim to rot.
 */
const contractPath = path.resolve(__dirname, "../../../contracts/visibility_providers.json");
const contract = JSON.parse(readFileSync(contractPath, "utf8")) as {
  plans: Record<
    string,
    {
      allowed_providers: string[];
      sweep_interval_seconds: number;
      competitor_sweep_interval_seconds: number | null;
    }
  >;
};

const DAY_SECONDS = 24 * 3600;
const WEEK_SECONDS = 7 * DAY_SECONDS;

/** The English word for a cadence, or null when it needs stating in days. */
const cadenceWord = (seconds: number): string | null => {
  if (seconds === DAY_SECONDS) return "daily";
  if (seconds === WEEK_SECONDS) return "weekly";
  return null;
};

const ARABIC_CADENCE_WORD: Record<string, string> = {
  daily: "يومياً",
  weekly: "أسبوعياً",
};

/**
 * The cadence the competitor surfaces describe: the scheduled competitor sweep
 * on the plans that schedule one. Plans that do not sell competitor analysis
 * carry null (on-demand only) and say nothing about a frequency.
 */
const competitorCadences = new Set(
  Object.values(contract.plans)
    .map((plan) => plan.competitor_sweep_interval_seconds)
    .filter((seconds): seconds is number => seconds !== null)
);

describe("competitor refresh copy states the cadence the backend actually runs", () => {
  it("has one competitor cadence to describe", () => {
    // Every plan that schedules competitor measurement uses the same interval,
    // which is what lets one sentence describe it. If that stops being true,
    // the sentence has to become per-plan rather than quietly wrong.
    expect(competitorCadences.size).toBe(1);
  });

  const [competitorCadenceSeconds] = [...competitorCadences];
  const expectedWord = cadenceWord(competitorCadenceSeconds);

  it("has a word for the cadence", () => {
    // A 48-hour sweep has no one-word English name, and "daily" is not it
    // (SIGV2-1216 is why this is worth asserting). If this fails, the copy has
    // to state the interval in days, as the on-screen indicator already does.
    expect(expectedWord).not.toBeNull();
  });

  it("says in English exactly what the sweep does", () => {
    expect(en.signalCompetitors.gate.featureBody).toBe(
      `Search and visibility scores for every rival, refreshed ${expectedWord}.`
    );
  });

  it("says in Arabic exactly what the sweep does", () => {
    const word = ARABIC_CADENCE_WORD[expectedWord as string];
    expect(word).toBeTruthy();
    expect(ar.signalCompetitors.gate.featureBody).toContain(word);
  });

  it("claims no other frequency anywhere in the competitor copy", () => {
    const otherWords = ["daily", "weekly", "hourly", "monthly"].filter(
      (word) => word !== expectedWord
    );
    const otherArabic = Object.entries(ARABIC_CADENCE_WORD)
      .filter(([word]) => word !== expectedWord)
      .map(([, arabic]) => arabic);

    const strings = (namespace: Record<string, unknown>): string[] =>
      Object.values(namespace).flatMap((value) =>
        typeof value === "string"
          ? [value]
          : value && typeof value === "object"
            ? strings(value as Record<string, unknown>)
            : []
      );

    for (const sentence of [
      ...strings(en.signalCompetitors),
      ...strings(en.signalCompetitorVisibility),
    ]) {
      for (const word of otherWords) {
        expect(sentence.toLowerCase()).not.toContain(word);
      }
    }
    for (const sentence of [
      ...strings(ar.signalCompetitors),
      ...strings(ar.signalCompetitorVisibility),
    ]) {
      for (const word of otherArabic) {
        expect(sentence).not.toContain(word);
      }
    }
  });
});
