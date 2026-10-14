import { describe, expect, it } from "vitest";

import { AUDIT_FORM_DEFAULTS } from "@/lib/auditFormSchema";
import { resolveProjectTargetCountry } from "@/lib/projectTargetCountry";

describe("resolveProjectTargetCountry", () => {
  it("drops the free-text market values the scan form actually produces", () => {
    // These are the values the launch form carries: the default empty market,
    // the pre-scan autofill (a country or city name, not a code) and the
    // placeholder's own example. Every one of them was sent as target_country
    // and rejected by the API, which is what blocked the scan (SIGV2-1110).
    expect(resolveProjectTargetCountry(AUDIT_FORM_DEFAULTS.market)).toBeNull();
    expect(resolveProjectTargetCountry("")).toBeNull();
    expect(resolveProjectTargetCountry("   ")).toBeNull();
    expect(resolveProjectTargetCountry(null)).toBeNull();
    expect(resolveProjectTargetCountry(undefined)).toBeNull();
  });

  it("resolves a country name to its ISO 3166-1 alpha-2 code", () => {
    expect(resolveProjectTargetCountry("Romania")).toBe("RO");
    expect(resolveProjectTargetCountry("romania")).toBe("RO");
    expect(resolveProjectTargetCountry("United States")).toBe("US");
    expect(resolveProjectTargetCountry("United Arab Emirates")).toBe("AE");
  });

  it("accepts a code that is already ISO 3166-1 alpha-2", () => {
    expect(resolveProjectTargetCountry("us")).toBe("US");
    expect(resolveProjectTargetCountry(" RO ")).toBe("RO");
  });

  it("resolves the everyday names that are not ISO codes", () => {
    // "UK" is what people type and it is not an ISO code; GB is.
    expect(resolveProjectTargetCountry("UK")).toBe("GB");
    expect(resolveProjectTargetCountry("U.K.")).toBe("GB");
    expect(resolveProjectTargetCountry("USA")).toBe("US");
    expect(resolveProjectTargetCountry("England")).toBe("GB");
  });

  it("reads the country out of a city and country market", () => {
    expect(resolveProjectTargetCountry("London, UK")).toBe("GB");
    expect(resolveProjectTargetCountry("Bucharest, Romania")).toBe("RO");
    expect(resolveProjectTargetCountry("Dubai, United Arab Emirates")).toBe("AE");
  });

  it("returns null rather than guessing a country it cannot resolve", () => {
    // A guessed country reaches the audit prompt, so no value is safer than
    // a wrong one. "Global" is a deliberate no-single-market answer.
    expect(resolveProjectTargetCountry("Global")).toBeNull();
    expect(resolveProjectTargetCountry("GLOBAL")).toBeNull();
    expect(resolveProjectTargetCountry("Europe")).toBeNull();
    expect(resolveProjectTargetCountry("DACH region")).toBeNull();
    expect(resolveProjectTargetCountry("GLO")).toBeNull();
    expect(resolveProjectTargetCountry("ZZ")).toBeNull();
  });
});
