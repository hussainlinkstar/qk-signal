/**
 * Internationalization helpers.
 *
 * Arabic is a shipped language, so the RTL foundation is ON by default and
 * `NEXT_PUBLIC_ENABLE_RTL="false"` is an explicit opt-out kill switch.
 *
 * It used to be opt-in ("true" required), which made Arabic unreachable in
 * every environment whose compose overlay did not declare the build arg:
 * `NEXT_PUBLIC_*` is inlined at build time, so an undeclared arg never reaches
 * the bundle. On preprod that overlay lives outside this repo, so the switcher
 * could not render and `ar` was never offered to i18next, which silently
 * disabled the translation itself rather than just the control (SIGV2-1060).
 * Defaulting on removes the out-of-repo dependency.
 */

/** Master switch for the Arabic/RTL foundation. On unless explicitly disabled. */
export const RTL_ENABLED = process.env.NEXT_PUBLIC_ENABLE_RTL !== "false";

/** Languages that render right-to-left. */
export const RTL_LANGUAGES = ["ar"] as const;

export type RtlLanguage = (typeof RTL_LANGUAGES)[number];

export type TextDirection = "ltr" | "rtl";

/**
 * Resolve the writing direction for a given language code.
 * Unknown / undefined languages fall back to "ltr".
 */
export const localeDir = (lng: string | undefined | null): TextDirection =>
  lng && (RTL_LANGUAGES as readonly string[]).includes(lng) ? "rtl" : "ltr";
