import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1036: SEO detail page (Improve default tab + Keywords + Pages tabs).
//
// Baselines are recorded against the e2e stub backend
// (e2e/visual/stub-backend.mjs), started by run-in-docker.sh on :8000: the
// Northwind Hotels project (id 9) carries a versioned full_report, a SERP
// tracking payload and a Search Console pages payload (SIGV2-1025 shape).
// ---------------------------------------------------------------------------

const FAKE_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  Buffer.from(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + 86400, type: "access" })
  ).toString("base64url") +
  ".x";

async function signIn(page: import("@playwright/test").Page, workspaceId: string) {
  const base = "http://localhost:3123";
  await page.context().addCookies(
    [
      { name: "auth_token", value: FAKE_JWT },
      { name: "auth_refresh_token", value: FAKE_JWT },
    ].map((c) => ({ ...c, url: base }))
  );
  await page.addInitScript((ws) => {
    window.localStorage.setItem("active_workspace_id", ws);
  }, workspaceId);
}

visualTest.describe("seo detail", () => {
  visualTest("default tab", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/google");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("seo-detail.png", { fullPage: true });
  });

  visualTest("keywords tab", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/google");
    await page.locator("#signal-tab-keywords").click();
    await expect(page.getByText("boutique hotel waterfront")).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("seo-detail-keywords.png", { fullPage: true });
  });

  visualTest("pages tab", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/google");
    await page.locator("#signal-tab-pages").click();
    await expect(page.getByText("/waterfront")).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("seo-detail-pages.png", { fullPage: true });
  });
});
