import React from "react";
import { render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import I18nProvider from "@/components/I18nProvider";
import { languageStorageKey } from "@/i18n";

const setCookie = (value: string) => {
  document.cookie = `preferred_language=${value};path=/`;
};

const clearCookie = () => {
  document.cookie = "preferred_language=;path=/;max-age=0";
};

describe("I18nProvider interface language resolution", () => {
  afterEach(() => {
    clearCookie();
    document.documentElement.lang = "";
    document.documentElement.dir = "";
  });

  it("falls back to English when localStorage holds a retired ro preference", async () => {
    window.localStorage.setItem(languageStorageKey, "ro");

    render(<I18nProvider>{null}</I18nProvider>);

    await waitFor(() => {
      expect(window.localStorage.getItem(languageStorageKey)).toBe("en");
      expect(document.documentElement.lang).toBe("en");
      expect(document.documentElement.dir).toBe("ltr");
    });
  });

  it("falls back to English when the preferred_language cookie is ro", async () => {
    setCookie("ro");

    render(<I18nProvider>{null}</I18nProvider>);

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("en");
      expect(window.localStorage.getItem(languageStorageKey)).toBe("en");
    });
  });

  it("resolves English by default when no preference is stored", async () => {
    render(<I18nProvider>{null}</I18nProvider>);

    await waitFor(() => {
      expect(document.documentElement.lang).toBe("en");
    });
  });
});
