"use client";

import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "@/i18n/en.json";
import ar from "@/i18n/ar.json";
import { RTL_LANGUAGES } from "@/lib/i18nFlags";

// English is the only always-on interface language. `ar` is registered in
// resources unconditionally (harmless), but only OFFERED in the UI when the
// RTL flag is on, see LanguageSwitcher / i18nFlags. This is the OFFER list;
// the resolvable catalogue below is wider (SIGV2-1063: passing this list to
// i18next made `changeLanguage("ar")` resolve `en`, so Arabic mirrored the
// layout without translating a single string).
export const supportedLngs = ["en"] as const;
export type SupportedLanguage = (typeof supportedLngs)[number];
export const defaultLanguage: SupportedLanguage = "en";
export const languageStorageKey = "geo-aeo-audit-tool.language";

// Full resolvable catalogue, including flag-gated languages. Handed to
// i18next so every registered locale actually resolves; `supportedLngs`
// stays the always-on offer list and the flag still governs which languages
// the UI presents.
export const allLanguages = ["en", ...RTL_LANGUAGES] as const;
export type AppLanguage = (typeof allLanguages)[number];

// Re-export the lightweight direction helpers so consumers can import them from
// the i18n entrypoint as well as from `@/lib/i18nFlags`.
export { RTL_LANGUAGES, localeDir } from "@/lib/i18nFlags";

const resources = {
  en: { translation: en },
  ar: { translation: ar },
};

if (!i18n.isInitialized) {
  void i18n.use(initReactI18next).init({
    resources,
    lng: defaultLanguage,
    fallbackLng: defaultLanguage,
    supportedLngs: [...allLanguages],
    showSupportNotice: false,
    interpolation: { escapeValue: false },
  });
}

export default i18n;
