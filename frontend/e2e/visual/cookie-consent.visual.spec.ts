import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// The cookie-consent banner is a real approved surface, but it only renders
// on a fresh context with no persisted decision, so the fixture suppresses it
// by default (the approved MVP captures show no banner). This spec opts back
// in with cookieConsent:"unset" and is the only place the banner is covered.
// ---------------------------------------------------------------------------

visualTest.describe("cookie consent", () => {
  visualTest.use({ cookieConsent: "unset" });

  visualTest("consent banner on first visit", async ({ page }) => {
    await gotoAndSettle(page, "/this-route-does-not-exist");
    // The banner's aria-label is translated ("Cookie consent banner" /
    // "شريط الموافقة على ملفات تعريف الارتباط"), so match either.
    const banner = page.getByRole("region", {
      name: /cookie consent banner|شريط الموافقة/i,
    });
    await expect(banner).toBeVisible();
    await expect(page).toHaveScreenshot("cookie-consent-banner.png", { fullPage: true });
  });
});
