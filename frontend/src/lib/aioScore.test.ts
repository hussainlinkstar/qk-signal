import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { computeAioScore } from "./aioScore";

describe("computeAioScore", () => {
  it("averages the canonical aeo and geo scores", () => {
    expect(computeAioScore({ scores: { aeo: 66, geo: 72 } })).toBe(69);
  });

  it("keeps a real 0 sub-score instead of falling through to section values", () => {
    // SIGNAL-1000: `??` does not fall through 0, so an audit scored 0 in one
    // half must still average correctly rather than showing the raw section
    // value or a different number on another screen.
    expect(
      computeAioScore({
        scores: { aeo: 0, geo: 72 },
        aeo: { answerability_score: 80 },
      })
    ).toBe(36);
  });

  it("falls back to the project latest scores, then the raw section scores", () => {
    expect(
      computeAioScore(
        { aeo: { answerability_score: 60 }, geo: { visibility_index: 70 } },
        { aeo: 50, geo: 40 }
      )
    ).toBe(45);
    expect(
      computeAioScore({
        aeo: { answerability_score: 60 },
        geo: { visibility_index: 70 },
      })
    ).toBe(65);
  });

  it("averages over the scores that exist and returns null when none do", () => {
    expect(computeAioScore({ scores: { aeo: null, geo: 72 } })).toBe(72);
    expect(computeAioScore({})).toBeNull();
    expect(computeAioScore(null)).toBeNull();
  });
});

describe("AIO headline consistency across screens", () => {
  const frontendRoot = path.resolve(__dirname, "..");

  it("the audit report and the project overview both headline the shared helper", () => {
    const auditReport = readFileSync(
      path.join(frontendRoot, "app/(app)/dashboard/audit/[id]/page.tsx"),
      "utf8"
    );
    const overview = readFileSync(
      path.join(frontendRoot, "app/(app)/dashboard/projects/[projectId]/page.tsx"),
      "utf8"
    );

    // The same helper must produce the AIO headline on both screens, or the
    // two pages can show different numbers for the same audit again.
    expect(auditReport).toContain("computeAioScore(activeReport)");
    expect(overview).toContain("computeAioScore(latestReport");
    expect(overview).not.toContain("answerability_score ??");
  });
  // SIGV2-1308 ---------------------------------------------------------------
  // QA: one project read 49 on the workspace overview and 50 on its own
  // dashboard, at the same moment, from the same two inputs.
  //
  // Both numbers were computed correctly. They disagreed because they rounded
  // at different stages: the overview averages the raw values and rounds for
  // display, while this rounded each part first, then averaged, then rounded
  // again. Half a point of rounding error, and a customer with no way to
  // reconcile two screens of their own product.
  it("rounds once, so it agrees with a surface that averages the raw values", () => {
    // The shape of the disagreement, in the smallest numbers that show it.
    const aeo = 48.6;
    const geo = 49.6;

    const averageOfRaw = Math.round((aeo + geo) / 2);
    const roundedPartsFirst = Math.round((Math.round(aeo) + Math.round(geo)) / 2);

    // The two approaches genuinely differ here, which is the whole ticket.
    expect(averageOfRaw).toBe(49);
    expect(roundedPartsFirst).toBe(50);

    expect(computeAioScore(null, { aeo, geo })).toBe(averageOfRaw);
  });

  it("does not round a part before averaging, on the reported repro", () => {
    // round(mean(25.6, 10.8)) = round(18.2) = 18.
    // The old behaviour was round(mean(26, 11)) = round(18.5) = 19.
    expect(computeAioScore({ scores: { aeo: 25.6, geo: 10.8 } })).toBe(18);
  });

  it("still returns a whole number, since the score is displayed as one", () => {
    const value = computeAioScore(null, { aeo: 48.6, geo: 49.6 });
    expect(value).not.toBeNull();
    expect(Number.isInteger(value as number)).toBe(true);
  });
});
