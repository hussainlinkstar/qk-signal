import { describe, expect, it } from "vitest";
import { COUNTRIES } from "./countryData";
import { GLOBAL_TARGET_MARKET, TARGET_MARKET_OPTIONS, toTargetCountry } from "./targetMarket";

const ISO_ALPHA2 = /^[A-Z]{2}$/;

describe("target market options", () => {
  it("offers only real ISO 3166-1 alpha-2 codes plus the Global sentinel", () => {
    const knownCodes = new Set(COUNTRIES.map((c) => c.code));
    expect(knownCodes.size).toBe(COUNTRIES.length);

    for (const option of TARGET_MARKET_OPTIONS) {
      if (option.code === GLOBAL_TARGET_MARKET) continue;
      expect(option.code).toMatch(ISO_ALPHA2);
      expect(knownCodes.has(option.code)).toBe(true);
    }
    expect(TARGET_MARKET_OPTIONS[0].code).toBe(GLOBAL_TARGET_MARKET);
  });

  it("contains no non-ISO sentinel such as GLO, EU or UK as a selectable value", () => {
    const codes = TARGET_MARKET_OPTIONS.map((o) => o.code);
    for (const bad of ["GLO", "EU", "UK", "GLOBAL-LEGACY", ""]) {
      expect(codes).not.toContain(bad);
    }
  });

  it("maps Global to no country and a real country to its two-letter code", () => {
    expect(toTargetCountry(GLOBAL_TARGET_MARKET)).toBeNull();
    expect(toTargetCountry("")).toBeNull();
    expect(toTargetCountry("US")).toBe("US");
    expect(toTargetCountry("gb")).toBe("GB");
  });
});
