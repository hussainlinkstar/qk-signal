import { afterEach, describe, expect, it } from "vitest";
import i18n, { defaultLanguage } from "@/i18n";
import arCatalogue from "@/i18n/ar.json";

afterEach(async () => {
  await i18n.changeLanguage(defaultLanguage);
});

describe("i18n language resolution (SIGV2-1063)", () => {
  it("resolves Arabic strings when the Arabic language is selected", async () => {
    await i18n.changeLanguage("ar");
    expect(i18n.resolvedLanguage).toBe("ar");
    expect(i18n.t("signalOverview.actionsTitle")).toBe(arCatalogue.signalOverview.actionsTitle);
    expect(i18n.t("signalOverview.actionsTitle")).not.toBe("Prioritised fixes");
  });

  it("still falls back to English for a missing Arabic key", async () => {
    await i18n.changeLanguage("ar");
    expect(i18n.t("nonexistent.key.for.test")).toBe("nonexistent.key.for.test");
  });

  it("resolves English when the English language is selected", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.resolvedLanguage).toBe("en");
    expect(i18n.t("signalOverview.actionsTitle")).toBe("Prioritised fixes");
  });
});
