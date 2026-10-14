import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1037: the action plan (Fixes) page.
//
// Baselines are recorded against the e2e stub backend
// (e2e/visual/stub-backend.mjs), started by run-in-docker.sh on :8000: the
// Northwind Hotels project (id 9) carries a metadata.advisor plan joined to
// canonical recommendations.items (measured and unrated ratings) plus a task
// board with one in-progress fix and one done record.
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

visualTest.describe("fixes", () => {
  visualTest("default", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/fixes");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30000 });
    await expect(page.getByTestId("fix-advisor-action-1")).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("fixes.png", { fullPage: true });
  });
});
