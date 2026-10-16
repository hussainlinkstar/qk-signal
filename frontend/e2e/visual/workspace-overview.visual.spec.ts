import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1034: workspace overview (project grid) and the first-project
// onboarding wizard.
//
// These baselines are recorded against the e2e stub backend
// (e2e/visual/stub-backend.mjs), started by run-in-docker.sh on :8000. They
// capture layout and chrome deterministically, NOT production data: the stub
// serves two fixed workspaces - "Jake Workspace" with three scored projects
// and "Beta Workspace" with zero, which drives the wizard auto-open.
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

visualTest.describe("workspace overview", () => {
  visualTest("project grid", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/overview");
    await expect(page.locator("a[href*='/dashboard/projects/']").first()).toBeVisible({
      timeout: 30000,
    });
    await expect(page).toHaveScreenshot("workspace-overview.png", { fullPage: true });
  });

  visualTest("onboarding wizard", async ({ page }) => {
    // Onboarding state is shared stub state: earlier specs PATCH it via the
    // overview auto-complete effects, so reset it before this capture.
    await page.request.post("http://localhost:8000/api/v1/__reset");
    await signIn(page, "2");
    await gotoAndSettle(page, "/dashboard/overview");
    await expect(page.getByTestId("onboarding-wizard")).toBeVisible({ timeout: 60000 });
    await expect(page).toHaveScreenshot("workspace-onboarding.png", { fullPage: true });
  });
});
