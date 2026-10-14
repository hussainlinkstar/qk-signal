import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1035: project dashboard (project overview page).
//
// These baselines are recorded against the e2e stub backend
// (e2e/visual/stub-backend.mjs), started by run-in-docker.sh on :8000. They
// capture layout and chrome deterministically, NOT production data: the stub
// serves a fixed Northwind Hotels project (id 9) with a latest audit whose
// full_report carries scores, search_types and suggestions, plus a fixed GA4
// site-traffic payload.
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

visualTest.describe("project overview", () => {
  visualTest("project dashboard", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9");
    // Wait for the last async section (GA4 site traffic) so the capture covers
    // the full approved layout, not a mid-load skeleton.
    await expect(page.locator('[data-metric="sessions"]')).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("project-overview.png", { fullPage: true });
  });
});
