import { createInstance } from "i18next";
import { describe, expect, it } from "vitest";

import en from "./en.json";
import ar from "./ar.json";
import { allLanguages, supportedLngs } from "./index";

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

const flattenKeys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([key, value]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return flattenKeys(value as Record<string, unknown>, nextKey);
    }
    return [nextKey];
  });

const baseKey = (key: string): string => key.replace(PLURAL_SUFFIX, "");

describe("locale files", () => {
  const enKeys = flattenKeys(en as Record<string, unknown>).sort();
  const arKeys = flattenKeys(ar as Record<string, unknown>).sort();

  it("contain the same translation base keys in en and ar", () => {
    // Plural categories are language-dependent: Arabic legitimately carries
    // zero/two/few/many where English only needs one/other. Compare the key
    // sets with plural suffixes stripped so parity still catches real gaps.
    expect([...new Set(arKeys.map(baseKey))].sort()).toEqual(
      [...new Set(enKeys.map(baseKey))].sort()
    );
  });

  it("ships English as the only always-on interface language", () => {
    expect(supportedLngs).toEqual(["en"]);
    expect(allLanguages).not.toContain("ro");
  });

  it("resolves the Arabic allowance-reset count string for every plural category", async () => {
    const i18n = createInstance();
    await i18n.init({
      lng: "ar",
      resources: { ar: { translation: ar } },
      interpolation: { escapeValue: false },
      showSupportNotice: false,
    });

    for (const count of [0, 1, 2, 3, 11]) {
      const rendered = i18n.t("signalStartCheck.allowance.resetsInDays", { count });
      expect(rendered).not.toBe("signalStartCheck.allowance.resetsInDays");
      expect(rendered).not.toContain("resetsInDays");
      expect(rendered.length).toBeGreaterThan(0);
    }
  });
});
