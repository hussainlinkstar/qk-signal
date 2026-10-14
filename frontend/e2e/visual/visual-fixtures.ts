import { test as base, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Visual-regression fixture (SIGV2-1045).
//
// One entry point for every pixel-compare spec:
//
//   import { visualTest, expect, gotoAndSettle } from "./visual-fixtures";
//   visualTest("maintenance", async ({ page }) => { ... });
//
// What it enforces, per test:
//   - a fixed wall clock (page.clock) so time-dependent rendering cannot drift
//   - a seeded Math.random so generated values are stable run to run
//   - a determinism stylesheet: animations/transitions off, caret hidden via
//     CSS (never caret:"hide", which injects inline caret-color and reads as a
//     hydration mismatch), scrollbars suppressed
//   - document.fonts.ready settled before each screenshot, plus a check that
//     the three self-hosted families the app ships (Inter, Roboto Mono,
//     Satoshi) really loaded
//   - document.documentElement.dir matching the project's locale, checked in
//     gotoAndSettle BEFORE any screenshot, so a silently-LTR "Arabic" baseline
//     can never be written to disk
//   - cookie consent pre-set to a persisted "accept all" record (the real
//     localStorage record + cookie from src/lib/cookieConsent.ts), so the
//     banner does not render. The approved MVP captures show no banner;
//     consent is only reachable via the footer "Cookie settings" link. A spec
//     opts in to photographing it with test.use({ cookieConsent: "unset" }).
//   - a hard FAIL if any request is made to an external font host
//     (fonts.googleapis.com / fonts.gstatic.com / api.fontshare.com /
//     cdn.fontshare.com). Requests are aborted on the first hit and the list
//     is checked again at teardown. All fonts are self-hosted via next/font;
//     an external request means the CSP font entries are live code, not
//     leftovers.
//
// Masks: this fixture offers none. A mask is only ever permitted for content
// that is genuinely nondeterministic, must be listed with a written reason,
// and may never cover layout or a component under test. See e2e/README.md.
// ---------------------------------------------------------------------------

export type VisualLocale = "en" | "ar";

// "accepted" (default): seed the persisted consent state so the banner does
// not render, matching the approved MVP captures which show no banner.
// "unset": leave a fresh context with no decision, for the spec that
// photographs the banner itself.
export type CookieConsentMode = "accepted" | "unset";

/** The option type each `visual-*` project contributes to `use` in the config. */
export interface VisualOptions {
  visualLocale: VisualLocale;
  cookieConsent?: CookieConsentMode;
}

const FIXED_NOW = new Date("2026-09-29T12:00:00.000Z");
const SEED = 1045;

const EXTERNAL_FONT_HOSTS = [
  "fonts.googleapis.com",
  "fonts.gstatic.com",
  "api.fontshare.com",
  "cdn.fontshare.com",
];

const REQUIRED_FONT_FAMILIES = [/inter/i, /roboto\s*mono/i, /satoshi/i];

// Mirror of src/lib/cookieConsent.ts: the provider reads the record from
// localStorage; persistConsentRecord also writes this cookie. Both are seeded
// so the rendered state equals a real "accept all" decision.
const CONSENT_STORAGE_KEY = "geo-aeo-audit-tool.cookie-consent";
const CONSENT_COOKIE_NAME = "geo_aeo_cookie_consent";
const CONSENT_COOKIE_VALUE = "v1.p1a1m1"; // serializeConsentCookie(all accepted)

const DETERMINISM_CSS = `
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
    caret-color: transparent !important;
  }
  ::-webkit-scrollbar { width: 0 !important; height: 0 !important; }
  * { scrollbar-width: none !important; }
`;

// External-font hits collected per page so gotoAndSettle can fail fast and the
// teardown can report the complete list.
const externalFontRequests = new WeakMap<Page, string[]>();

function externalFontsHit(page: Page): string[] {
  return externalFontRequests.get(page) ?? [];
}

export const visualTest = base.extend<
  { visualLocale: VisualLocale; cookieConsent: CookieConsentMode },
  Record<never, never>
>({
  // Project-scoped option: each visual-* project sets it in playwright.config.ts
  visualLocale: ["en", { option: true }],

  // Spec-scoped option: "accepted" hides the banner (the approved default);
  // a spec opts in to photographing it with test.use({ cookieConsent: "unset" })
  cookieConsent: ["accepted", { option: true }],

  page: async ({ page, visualLocale, cookieConsent }, use, testInfo) => {
    // Locale cookie before the first navigation. The root layout reads
    // preferred_language server-side and resolves html dir from it.
    const baseURL = testInfo.project.use.baseURL ?? "http://localhost:3000";
    await page.context().addCookies([
      {
        name: "preferred_language",
        value: visualLocale,
        url: baseURL,
      },
    ]);

    if (cookieConsent !== "unset") {
      const record = {
        version: 1,
        source: "accept-all",
        consentedAt: FIXED_NOW.toISOString(),
        lastUpdatedAt: FIXED_NOW.toISOString(),
        preferences: { necessary: true, preferences: true, analytics: true, marketing: true },
      };
      await page
        .context()
        .addCookies([{ name: CONSENT_COOKIE_NAME, value: CONSENT_COOKIE_VALUE, url: baseURL }]);
      await page.addInitScript(
        ([key, value]) => {
          window.localStorage.setItem(key, value);
        },
        [CONSENT_STORAGE_KEY, JSON.stringify(record)]
      );
    }

    // Fail on any external font-host request: abort the request the moment it
    // is observed and keep the URL for the teardown report.
    externalFontRequests.set(page, []);
    await page.route(
      (url) => EXTERNAL_FONT_HOSTS.some((host) => url.hostname === host),
      async (route) => {
        externalFontRequests.get(page)?.push(route.request().url());
        await route.abort();
      }
    );

    // Fixed clock (page.clock exists in @playwright/test 1.58).
    await page.clock.install({ time: FIXED_NOW });
    await page.clock.setFixedTime(FIXED_NOW);

    // Seeded Math.random so generated content is identical across runs.
    await page.addInitScript((seed) => {
      let state = seed >>> 0;
      Math.random = () => {
        // mulberry32: small deterministic PRNG, adequate for stable renders
        state |= 0;
        state = (state + 0x6d2b79f5) | 0;
        let t = Math.imul(state ^ (state >>> 15), 1 | state);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    }, SEED);

    // Determinism stylesheet, applied as early as the document has a head.
    await page.addInitScript((css) => {
      const apply = () => {
        const style = document.createElement("style");
        style.dataset.visualDeterminism = "true";
        style.textContent = css;
        (document.head ?? document.documentElement).appendChild(style);
      };
      if (document.head) {
        apply();
      } else {
        document.addEventListener("DOMContentLoaded", apply, { once: true });
      }
    }, DETERMINISM_CSS);

    // eslint-disable-next-line react-hooks/rules-of-hooks -- Playwright fixture `use`, not a React hook
    await use(page);

    // Teardown report: the full list of external font hits observed during the
    // test. Direction and font-family checks live in gotoAndSettle so they run
    // before any screenshot can be written.
    const hits = externalFontsHit(page);
    if (hits.length > 0) {
      throw new Error(
        `visual fixture: external font host request(s) observed and aborted:\n  ` +
          hits.join("\n  ") +
          `\nFonts must stay self-hosted; investigate before recording baselines.`
      );
    }
  },
});

export { expect };

// Navigate, wait for the document to settle, and run the pre-screenshot
// guarantees. Specs must call this before toHaveScreenshot; it is what stops a
// wrong-direction or missing-font baseline from ever being written.
export async function gotoAndSettle(page: Page, path: string): Promise<void> {
  await page.goto(path, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {
    // networkidle can time out when a page holds a connection (SSE, long
    // polling); domcontentloaded + fonts.ready below is the real gate.
  });
  await page.evaluate(async () => {
    await document.fonts.ready;
  });

  // Any external font request already observed fails immediately, not at
  // teardown, so a spec stops before writing or comparing a screenshot.
  const fontHits = externalFontsHit(page);
  if (fontHits.length > 0) {
    throw new Error(
      `visual fixture: external font host request(s) observed and aborted:\n  ` +
        fontHits.join("\n  ")
    );
  }

  // Direction is resolved from the preferred_language cookie this context was
  // seeded with, so the expected value cannot drift from what was requested.
  const lang = (await page.context().cookies()).find((c) => c.name === "preferred_language")?.value;
  const expectedDir = lang === "ar" ? "rtl" : "ltr";
  const dir = await page.evaluate(() => document.documentElement.dir);
  if (dir !== expectedDir) {
    throw new Error(
      `visual fixture: document direction is "${dir}", expected "${expectedDir}" ` +
        `(preferred_language=${lang ?? "unset"}). An Arabic baseline that rendered LTR ` +
        `must never be recorded.`
    );
  }

  const families = await page.evaluate(() => Array.from(document.fonts).map((f) => f.family));
  const missing = REQUIRED_FONT_FAMILIES.filter((wanted) => !families.some((f) => wanted.test(f)));
  if (missing.length > 0) {
    throw new Error(
      `visual fixture: expected font families did not load. ` +
        `Loaded: [${families.join(", ")}]. Missing pattern(s): ${missing
          .map((r) => r.source)
          .join(", ")}`
    );
  }
}
