import { expect, gotoAndSettle, visualTest } from "./visual-fixtures";

// ---------------------------------------------------------------------------
// SIGV2-1036: AIO detail page (Improve default tab + Prompts tab).
//
// Baselines are recorded against the e2e stub backend
// (e2e/visual/stub-backend.mjs), started by run-in-docker.sh on :8000: the
// Northwind Hotels project (id 9) carries a versioned full_report and a
// populated visibility-summary feed for the By engine / Prompts tabs.
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

visualTest.describe("aio detail", () => {
  visualTest("default tab", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/ai-answers");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 30000 });
    await expect(page).toHaveScreenshot("aio-detail.png", { fullPage: true });
  });

  visualTest("prompts tab", async ({ page }) => {
    await signIn(page, "1");
    await gotoAndSettle(page, "/dashboard/projects/9/ai-answers");
    await page.locator("#signal-tab-prompts").click();
    // Wait for the async visibility feed before photographing the
    // prompt-setup surface (SIGV2-1194): the stub's brand starter question
    // appears once the group renders open.
    await expect(page.getByText("What is Northwind Hotels known for?")).toBeVisible({
      timeout: 30000,
    });
    await expect(page).toHaveScreenshot("aio-detail-prompts.png", { fullPage: true });
  });
});
