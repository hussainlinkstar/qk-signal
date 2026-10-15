"use client";

import { useTranslation } from "react-i18next";
import i18n, { allLanguages, languageStorageKey } from "@/i18n";
import { RTL_ENABLED, localeDir } from "@/lib/i18nFlags";
import { cx } from "@/components/ui/utils";

const LANGUAGE_LABEL_KEYS: Record<(typeof allLanguages)[number], string> = {
  en: "common.english",
  ar: "common.arabic",
};

/**
 * The one place a UI language change happens: i18next, document lang/dir,
 * the `preferred_language` cookie and the localStorage key. Shared with the
 * command palette's language actions so both paths persist identically.
 */
export function changeAppLanguage(lng: string) {
  void i18n.changeLanguage(lng);
  if (typeof document !== "undefined") {
    document.documentElement.lang = lng;
    document.documentElement.dir = localeDir(lng);
    document.cookie = `preferred_language=${lng};path=/;max-age=31536000;SameSite=Lax`;
  }
  if (typeof window !== "undefined") {
    window.localStorage.setItem(languageStorageKey, lng);
  }
}

/**
 * Flag-gated language switcher. Renders nothing when `NEXT_PUBLIC_ENABLE_RTL`
 * is "false"; the flag is on by default (opt-out). It offers en + ar and
 * persists the choice (localStorage + cookie) while keeping document
 * `lang`/`dir` in sync.
 *
 * `compact` renders the approved `.lang-toggle` control (EN / ع pills) used
 * in the signal-MVP top bar; the default variant keeps full language names.
 */
export default function LanguageSwitcher({
  className,
  variant = "default",
}: {
  className?: string;
  variant?: "default" | "compact";
}) {
  const { t, i18n: instance } = useTranslation();

  if (!RTL_ENABLED) {
    return null;
  }

  const current = instance.resolvedLanguage ?? instance.language;

  const changeLanguage = changeAppLanguage;

  if (variant === "compact") {
    const shortLabel: Record<string, string> = { en: "EN", ar: "ع" };
    return (
      <div
        role="group"
        aria-label={t("common.language")}
        className={cx(
          "inline-flex items-center gap-px rounded-full bg-(--line-2) p-0.5",
          className
        )}
      >
        {allLanguages.map((lng) => {
          const isActive = current === lng;
          return (
            <button
              key={lng}
              type="button"
              lang={lng}
              aria-pressed={isActive}
              aria-label={t(LANGUAGE_LABEL_KEYS[lng])}
              onClick={() => changeLanguage(lng)}
              className={cx(
                "rounded-full px-2.5 py-1 text-xs font-bold leading-[1.4] transition-colors",
                isActive
                  ? "bg-(--panel) text-(--t-1) shadow-[0_1px_3px_rgba(0,0,0,0.10)]"
                  : "text-(--t-3) hover:text-(--t-1)"
              )}
            >
              {shortLabel[lng] ?? lng.toUpperCase()}
            </button>
          );
        })}
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={t("common.language")}
      className={cx(
        "inline-flex items-center gap-1 rounded-full border-0  p-1",
        className
      )}
    >
      {allLanguages.map((lng) => {
        const isActive = current === lng;
        return (
          <button
            key={lng}
            type="button"
            lang={lng}
            aria-pressed={isActive}
            onClick={() => changeLanguage(lng)}
            className={cx(
              "rounded-full px-3 py-1 text-xs font-semibold transition-colors duration-200",
              isActive
                ? "bg-(--primary) text-white"
                : "text-(--text-muted) hover:text-(--foreground)"
            )}
          >
            {t(LANGUAGE_LABEL_KEYS[lng])}
          </button>
        );
      })}
    </div>
  );
}
