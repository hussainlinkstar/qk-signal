import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1222: the animated gradient alert edge, measured in a real browser.
//
// Two separate things are proved here, and neither can be seen from markup.
//
// 1. The edge really is still when motion is reduced. The check is two
//    screenshots of the alert a second and a half apart, with the harness's
//    own `animation: none !important` stylesheet switched off first, so the
//    page's rules are what answer. Reading `animation-name` alone would not
//    do: it reports `none` on a tree where the sweep was never added, and it
//    reports `none` on a tree where a requestAnimationFrame loop is moving
//    the gradient every frame. Comparing two frames catches both, whatever
//    mechanism a future edit reaches for.
//
//    This is the shape of failure SIGV2-1178 cost a day to: framer-motion
//    springs on the score gauges were captured at different frames between
//    runs, and the fix was to honour the reduced-motion hook.
//
//    The control is the same page in a context that does NOT ask for reduced
//    motion, where the two frames must differ. Without it the assertion above
//    would pass just as happily on a tree with no animation at all.
//
// 2. The tone is still carried by a glyph, not by the gradient. SIGV2-1171
//    put the four approved `.alert` shapes on these surfaces because colour
//    alone fails WCAG 1.4.1, and a redesign is exactly when that gets quietly
//    dropped in favour of "the pretty edge".
//
// The baseline is scoped to the alert itself rather than the page, so it
// moves when the treatment moves and not when the report table's fixture rows
// change underneath it.
// ---------------------------------------------------------------------------

const BASE = "http://localhost:3123";
const ALERT_ROUTE = "/dashboard/reports";

// Long enough for the 6s sweep to travel a visible distance (a quarter of a
// cycle), short enough not to slow the suite.
const SWEEP_SAMPLE_MS = 1500;

const FAKE_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  Buffer.from(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + 86400, type: "access" })
  ).toString("base64url") +
  ".x";

const AUTH_COOKIES = [
  { name: "auth_token", value: FAKE_JWT },
  { name: "auth_refresh_token", value: FAKE_JWT },
].map((c) => ({ ...c, url: BASE }));

async function signIn(page: import("@playwright/test").Page) {
  await page.context().addCookies(AUTH_COOKIES);
  await page.addInitScript(() => {
    window.localStorage.setItem("active_workspace_id", "1");
  });
}

/** Switch off the fixture's determinism stylesheet, so the page's own rules
 *  are what decide whether the edge moves. */
async function unfreeze(page: import("@playwright/test").Page) {
  await page.evaluate(() => {
    for (const style of Array.from(
      document.querySelectorAll<HTMLStyleElement>("style[data-visual-determinism]")
    )) {
      style.disabled = true;
    }
  });
}

/** Two pictures of the alert, SWEEP_SAMPLE_MS apart. */
async function twoFrames(
  page: import("@playwright/test").Page,
  alert: import("@playwright/test").Locator
) {
  const first = await alert.screenshot({ animations: "allow" });
  await page.waitForTimeout(SWEEP_SAMPLE_MS);
  const second = await alert.screenshot({ animations: "allow" });
  return [first, second] as const;
}

visualTest.describe("alert treatment", () => {
  visualTest("the alert tier carries a glyph and a frozen gradient edge", async ({ page }) => {
    await signIn(page);
    await gotoAndSettle(page, ALERT_ROUTE);

    const alert = page.locator("[data-signal-alert]").first();
    await expect(alert).toBeVisible({ timeout: 30000 });

    // SIGV2-1171's non-colour cue, still present after the restyle.
    await expect(alert.locator("svg").first()).toBeVisible();

    await expect(alert).toHaveScreenshot("alert-gradient-edge.png");
  });

  visualTest("prefers-reduced-motion is what stops the edge", async ({ page, browser }) => {
    await signIn(page);
    await gotoAndSettle(page, ALERT_ROUTE);

    const alert = page.locator("[data-signal-alert]").first();
    await expect(alert).toBeVisible({ timeout: 30000 });

    await unfreeze(page);
    expect(
      await page.evaluate(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches),
      "the visual projects run with reducedMotion: reduce"
    ).toBe(true);

    const [still1, still2] = await twoFrames(page, alert);
    expect(
      still2.equals(still1),
      "the alert changed between two frames 1.5s apart with reduced motion asked for: " +
        "something is still animating that prefers-reduced-motion cannot stop"
    ).toBe(true);

    // The same page without the preference. If this did not move, the
    // assertion above would be vacuous: it would pass on a tree where the
    // edge was simply never animated.
    const context = await browser.newContext({
      reducedMotion: "no-preference",
      viewport: { width: 1440, height: 900 },
    });
    try {
      await context.addCookies(AUTH_COOKIES);
      const plain = await context.newPage();
      await plain.addInitScript(() => {
        window.localStorage.setItem("active_workspace_id", "1");
      });
      await plain.goto(`${BASE}${ALERT_ROUTE}`, { waitUntil: "domcontentloaded" });
      const moving = plain.locator("[data-signal-alert]").first();
      await expect(moving).toBeVisible({ timeout: 30000 });

      expect(
        await plain.evaluate(
          () =>
            getComputedStyle(document.querySelector("[data-signal-alert]")!, "::before")
              .animationName
        ),
        "the edge is not a CSS animation on the ring, so nothing the browser can disable " +
          "is driving it"
      ).toBe("signal-alert-edge");

      const [moved1, moved2] = await twoFrames(plain, moving);
      expect(
        moved2.equals(moved1),
        "the edge did not move in 1.5s without the preference, so the reduced-motion " +
          "assertion above proves nothing"
      ).toBe(false);
    } finally {
      await context.close();
    }
  });
});
