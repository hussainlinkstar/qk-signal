"use client";

import { useEffect } from "react";
import { I18nextProvider } from "react-i18next";
import i18n, { defaultLanguage, languageStorageKey, supportedLngs } from "@/i18n";
import { RTL_ENABLED, RTL_LANGUAGES, localeDir } from "@/lib/i18nFlags";

// Languages offered for resolution. en always; ar only when the flag is on.
const offeredLanguages: readonly string[] = RTL_ENABLED
  ? [...supportedLngs, ...RTL_LANGUAGES]
  : supportedLngs;

const resolveInitialLanguage = () => {
  if (typeof window === "undefined") {
    return defaultLanguage;
  }

  const storedLanguage = window.localStorage.getItem(languageStorageKey);
  if (storedLanguage && offeredLanguages.includes(storedLanguage)) {
    return storedLanguage;
  }

  const cookieLanguage = document.cookie
    .split("; ")
    .find((entry) => entry.startsWith("preferred_language="))
    ?.split("=")[1];

  if (cookieLanguage && offeredLanguages.includes(cookieLanguage)) {
    return cookieLanguage;
  }

  return defaultLanguage;
};

export default function I18nProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const initialLanguage = resolveInitialLanguage();
    void i18n.changeLanguage(initialLanguage);
    document.documentElement.lang = initialLanguage;
    document.documentElement.dir = localeDir(initialLanguage);
    // Persist so future SSR and client reads pick up the resolved language
    window.localStorage.setItem(languageStorageKey, initialLanguage);
    document.cookie = `preferred_language=${initialLanguage};path=/;max-age=31536000;SameSite=Lax`;
  }, []);

  return <I18nextProvider i18n={i18n}>{children}</I18nextProvider>;
}
