import { describe, expect, it } from "vitest";

import { RTL_LANGUAGES, localeDir } from "./i18nFlags";

describe("localeDir", () => {
  it("returns rtl for Arabic", () => {
    expect(localeDir("ar")).toBe("rtl");
  });

  it("returns ltr for en and unregistered codes", () => {
    expect(localeDir("en")).toBe("ltr");
    expect(localeDir("ro")).toBe("ltr");
  });

  it("falls back to ltr for unknown / empty languages", () => {
    expect(localeDir(undefined)).toBe("ltr");
    expect(localeDir(null)).toBe("ltr");
    expect(localeDir("")).toBe("ltr");
    expect(localeDir("xx")).toBe("ltr");
  });

  it("marks every RTL language as rtl", () => {
    for (const lng of RTL_LANGUAGES) {
      expect(localeDir(lng)).toBe("rtl");
    }
  });
});
