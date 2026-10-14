import { expect, test } from "@playwright/test";

// ---------------------------------------------------------------------------
// Portal Flows
//
// The client portal at `/portal` is a protected route. The portal layout
// checks the user session via `serverFetch("/auth/me")`. Unauthenticated
// requests are redirected to `/login?session_expired=true&reason=auth_failed`.
//
// Regular E2E users (non-portal accounts) also redirect to `/dashboard`.
// These tests verify the redirect behaviour without requiring a portal account.
// ---------------------------------------------------------------------------

test.describe("Portal Flows", () => {
  test("should redirect unauthenticated portal access to the login page", async ({ page }) => {
    await page.goto("/portal");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
    await expect(page.getByText(/Sign in to/i)).toBeVisible({ timeout: 15_000 });
  });

  test("should redirect unauthenticated portal project access to login", async ({ page }) => {
    await page.goto("/portal/projects/1");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
    await expect(page.getByText(/Sign in to/i)).toBeVisible({ timeout: 15_000 });
  });

  test("should redirect unauthenticated portal profile access to login", async ({ page }) => {
    await page.goto("/portal/profile");
    await page.waitForLoadState("domcontentloaded");

    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
  });

  test("should show session-expired notice when redirected from portal", async ({ page }) => {
    await page.goto("/login?session_expired=true&reason=auth_failed");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByText(/Sign in to/i)).toBeVisible({ timeout: 15_000 });

    const hasSessionNotice = await page
      .getByText(/session expired|sign in to continue/i)
      .first()
      .isVisible({ timeout: 10_000 })
      .catch(() => false);

    expect(hasSessionNotice, "Expected a session-expired notice or toast to be visible").toBe(true);
  });
});
