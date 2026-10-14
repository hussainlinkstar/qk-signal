import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1045 exemplar: proves the harness renders deterministically on routes
// needing neither authentication nor the backend.
//
//   /maintenance           - standalone client page; its health probe 404s
//                            without the API, leaving the rendered state stable
//   /this-route-does-not-exist - root not-found (marketing chrome + 404 body)
//
// Later stories add their own *.visual.spec.ts under e2e/visual/ following the
// same pattern. Baselines are recorded once per project inside the pinned
// Playwright image only - see e2e/README.md.
// ---------------------------------------------------------------------------

visualTest.describe("system states", () => {
  visualTest("maintenance page", async ({ page }) => {
    await gotoAndSettle(page, "/maintenance");
    await expect(page.getByRole("heading").first()).toBeVisible();
    await expect(page).toHaveScreenshot("maintenance.png", { fullPage: true });
  });

  visualTest("not found page", async ({ page }) => {
    await gotoAndSettle(page, "/this-route-does-not-exist");
    await expect(page.getByRole("heading").first()).toBeVisible();
    await expect(page).toHaveScreenshot("not-found.png", { fullPage: true });
  });
});
