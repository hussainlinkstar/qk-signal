import { describe, expect, it } from "vitest";

import { ROLE_MODES, type RoleMode } from "@/lib/roleMode";

import { describeScore, GLOSSARY, type CopyResult } from "./signalCopy";

const METRIC_KEYS = ["seo", "aio", "aeo", "geo"] as const;
const BANNED = ["neural", "market dominance"] as const;

function allText(result: CopyResult): string {
  return [result.label, result.interpretation, result.nextAction ?? ""].join(" ");
}

describe("describeScore — §4 per-role table (aio=42)", () => {
  it("marketer gets plain '~4 of 10' framing", () => {
    expect(describeScore("aio", 42, "marketer").interpretation).toMatch(/appear in ~4 of 10/i);
  });

  it("specialist label exposes the raw stat 'AIO 42/100'", () => {
    expect(describeScore("aio", 42, "specialist").label).toMatch(/AIO 42\/100/);
  });

  it("enterprise interpretation uses governance framing (markets/drift/claims)", () => {
    expect(describeScore("aio", 42, "enterprise").interpretation).toMatch(/markets|drift|claims/i);
  });

  it("agency phrasing is client-ready (action plan)", () => {
    const result = describeScore("aio", 42, "agency");
    expect(`${result.interpretation} ${result.nextAction ?? ""}`).toMatch(/action plan|client/i);
  });

  it("explorer phrasing is the simplest (easiest fixes)", () => {
    const result = describeScore("aio", 42, "explorer");
    expect(allText(result)).toMatch(/easiest|simpl/i);
  });
});

describe("number rendering rules", () => {
  it("renders 0–1 style scores as X/100 (geo_score=0.42 → 42/100)", () => {
    const result = describeScore("geo", 0.42, "specialist");
    expect(result.label).toMatch(/42\/100/);
  });

  it("renders 0–100 style scores as X/100", () => {
    const result = describeScore("seo", 42, "specialist");
    expect(result.label).toMatch(/42\/100/);
  });

  it("never emits a bare score without the /100 denominator (across roles/metrics)", () => {
    for (const metric of METRIC_KEYS) {
      for (const role of ROLE_MODES) {
        const result = describeScore(metric, 42, role);
        const text = allText(result);
        // Any '42' must be part of '42/100', never a bare standalone number.
        const bareScore = /(?<!\/)\b42\b(?!\/100)/.test(text);
        expect(bareScore, `bare score in ${metric}/${role}: "${text}"`).toBe(false);
      }
    }
  });

  it("always provides an interpretive clause (non-empty interpretation)", () => {
    for (const metric of METRIC_KEYS) {
      for (const role of ROLE_MODES) {
        expect(describeScore(metric, 70, role).interpretation.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("null handling", () => {
  it("handles null value gracefully without a bare number", () => {
    for (const role of ROLE_MODES) {
      const result = describeScore("geo", null, role);
      expect(result.interpretation).toMatch(/not enough data|no data/i);
      expect(result.label).not.toMatch(/\d/);
    }
  });
});

describe("unknown metric keys", () => {
  it("returns a sensible default rather than throwing", () => {
    const result = describeScore("totally_unknown_metric", 42, "specialist");
    expect(result.label.length).toBeGreaterThan(0);
    expect(result.interpretation.length).toBeGreaterThan(0);
    expect(result.label).toMatch(/42\/100/);
  });
});

describe("anti-jargon sweep", () => {
  const sampleValues: Array<number | null> = [null, 0, 0.42, 17, 42, 60, 85, 100];
  const sampleMetrics = [...METRIC_KEYS, "unknown_metric"];

  it("no describeScore output contains banned jargon for any role/metric/value", () => {
    for (const metric of sampleMetrics) {
      for (const role of ROLE_MODES as readonly RoleMode[]) {
        for (const value of sampleValues) {
          const text = allText(describeScore(metric, value, role)).toLowerCase();
          for (const banned of BANNED) {
            expect(text.includes(banned), `"${banned}" in ${metric}/${role}/${value}`).toBe(false);
          }
        }
      }
    }
  });
});

describe("GLOSSARY", () => {
  it("maps jargon → plain replacements for banned terms", () => {
    expect(Object.keys(GLOSSARY).length).toBeGreaterThan(0);
    expect(GLOSSARY).toHaveProperty("market_dominance");
    expect(GLOSSARY).toHaveProperty("neural_authority");
  });

  it("no glossary replacement value contains banned jargon", () => {
    for (const value of Object.values(GLOSSARY)) {
      const lower = value.toLowerCase();
      for (const banned of BANNED) {
        expect(lower.includes(banned), `"${banned}" in glossary value "${value}"`).toBe(false);
      }
    }
  });
});

describe("determinism", () => {
  it("returns identical output for identical input", () => {
    expect(describeScore("aio", 42, "marketer")).toEqual(describeScore("aio", 42, "marketer"));
  });
});
