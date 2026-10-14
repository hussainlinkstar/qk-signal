import { expect, test } from "@playwright/test";

/**
 * Critical-path login coverage against a STABLE, pre-provisioned QA account
 * (no registration / email-verification dependency). Runs across the desktop
 * and mobile projects in playwright.config.ts.
 *
 * Env (falls back to the shared QA account on the Qiko Signal env):
 *   E2E_BASE_URL       e.g. https://signal-origin.qiko.ai/signal
 *   E2E_TEST_EMAIL     QA account email
 *   E2E_TEST_PASSWORD  QA account password
 */

const BASE = (process.env.E2E_BASE_URL ?? "http://localhost:3000").replace(/\/+$/, "");
const EMAIL = process.env.E2E_TEST_EMAIL ?? "qa-signal@qiko.ai";
const PASSWORD = process.env.E2E_TEST_PASSWORD ?? "QikoSignalQA!2026";
const loginUrl = `${BASE}/login`;

test.describe("Critical path: login", () => {
  // Pre-seed cookie consent so the banner never overlays the form (mobile).
  test.beforeEach(async ({ context }) => {
    const consent = JSON.stringify({
      version: 1,
      source: "accept-all",
      consentedAt: new Date().toISOString(),
      lastUpdatedAt: new Date().toISOString(),
      preferences: { necessary: true, preferences: true, analytics: true, marketing: true },
    });
    await context.addInitScript((rec) => {
      try {
        window.localStorage.setItem("geo-aeo-audit-tool.cookie-consent", rec);
      } catch (e) {
        /* ignore */
      }
    }, consent);
  });

  test("signs in with valid credentials and leaves the login page", async ({ page }) => {
    await page.goto(loginUrl);
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByPlaceholder("your@email.com")).toBeVisible();
    await page.getByPlaceholder("your@email.com").fill(EMAIL);
    const pwd = page.locator('input[type="password"]').first();
    await pwd.fill(PASSWORD);
    await pwd.press("Enter"); // submit via keyboard — viewport/overlay independent

    await expect(page).toHaveURL(/\/(dashboard|onboarding)/, { timeout: 30_000 });
    expect(page.url()).not.toContain("/login");

    const cookies = await page.context().cookies();
    expect(cookies.length).toBeGreaterThan(0);
  });

  test("rejects invalid credentials and stays on the login page", async ({ page }) => {
    await page.goto(loginUrl);
    await page.waitForLoadState("domcontentloaded");

    await page.getByPlaceholder("your@email.com").fill(EMAIL);
    const pwd = page.locator('input[type="password"]').first();
    await pwd.fill("WrongPassword999!");
    await pwd.press("Enter");

    await expect(
      page.getByText(/Failed to sign in|Invalid|incorrect|not found|password/i).first()
    ).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
  });
});
