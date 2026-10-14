import { expect, test } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin, registerUser } from "./helpers";

// ---------------------------------------------------------------------------
// Auth Flows
// 90s per-test (default from playwright.config.ts) is sufficient here.
// ---------------------------------------------------------------------------

test.describe("Authentication Flows", () => {
  test.describe.configure({ mode: "serial" });

  test("Registration flow: create a new account and redirect to login", async ({ page }) => {
    const user = buildTestUser("e2e-reg");
    await page.goto("/register");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByText(/Create your/i)).toBeVisible();
    await expect(page.getByPlaceholder("Agency or company name")).toBeVisible();
    await expect(page.getByPlaceholder("you@company.com")).toBeVisible();

    await page.getByPlaceholder("Agency or company name").fill(user.name);
    await page.getByPlaceholder("you@company.com").fill(user.email);

    const passwordInputs = page.locator('input[type="password"]');
    await passwordInputs.nth(0).fill(user.password);
    await passwordInputs.nth(1).fill(user.password);

    const legalCheckbox = page.locator("#register-legal-consent");
    if (await legalCheckbox.isVisible({ timeout: 3_000 }).catch(() => false)) {
      await legalCheckbox.check();
    }

    await page.getByRole("button", { name: /Create account/i }).click();
    await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
  });

  test("Login flow: sign in with valid credentials and reach the dashboard", async ({ page }) => {
    const user = buildTestUser("e2e-login");
    await registerUser(page, user);

    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByText(/Sign in to/i)).toBeVisible();
    await expect(page.getByPlaceholder("your@email.com")).toBeVisible();

    await page.getByPlaceholder("your@email.com").fill(user.email);
    await page.locator('input[type="password"]').first().fill(user.password);
    await page.getByRole("button", { name: /^Sign In$/i }).click();

    await expect(page).toHaveURL(/\/dashboard\/overview/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: /Site Selection Hub/i })).toBeVisible();
  });

  test("Login with invalid credentials: display error feedback", async ({ page }) => {
    await page.goto("/login");
    await page.waitForLoadState("domcontentloaded");

    await page.getByPlaceholder("your@email.com").fill("nonexistent-e2e@example.com");
    await page.locator('input[type="password"]').first().fill("WrongPassword999!");
    await page.getByRole("button", { name: /^Sign In$/i }).click();

    await expect(
      page.getByText(/Failed to sign in|Invalid|incorrect|not found/i).first()
    ).toBeVisible({ timeout: 10_000 });

    await expect(page).toHaveURL(/\/login/);
  });

  test("Forgot password flow: submit email and verify success state", async ({ page }) => {
    await page.goto("/forgot-password");
    await page.waitForLoadState("domcontentloaded");

    await expect(page.getByText(/Recover/i).first()).toBeVisible();
    await expect(page.getByPlaceholder("your@email.com")).toBeVisible();

    await page.getByPlaceholder("your@email.com").fill("e2e-forgot@example.com");
    await page.getByRole("button", { name: /Send reset instructions/i }).click();

    await expect(page.getByText(/Check your inbox/i).first()).toBeVisible({ timeout: 15_000 });

    // SIGV2-1088: the shared auth footer owns the only route back to sign-in.
    const signInLinks = page.locator('a[href="/login"]');
    await expect(signInLinks).toHaveCount(1);
    await expect(signInLinks.first()).toBeVisible();
  });

  test("Logout flow: sign out from the dashboard and return to login", async ({ page }) => {
    const user = buildTestUser("e2e-logout");
    await registerAndLogin(page, user);

    await expect(page).toHaveURL(/\/dashboard\/overview/, { timeout: 30_000 });
    await expect(page.getByRole("heading", { name: /Site Selection Hub/i })).toBeVisible();

    // Locate the user menu trigger via data-testid first, then fall back to aria
    const userMenuTrigger = page
      .getByTestId("user-menu-trigger")
      .or(page.getByRole("button", { name: /user menu|account/i }))
      .first();

    if (await userMenuTrigger.isVisible({ timeout: 5_000 }).catch(() => false)) {
      await userMenuTrigger.click();
    } else {
      // Last resort: sidebar avatar button (single uppercase letter or initials)
      const initials = user.name
        .split(" ")
        .map((n) => n[0])
        .join("")
        .toUpperCase();
      await page
        .locator("button")
        .filter({ hasText: new RegExp(`^${initials}$`) })
        .last()
        .click();
    }

    const signOutButton = page
      .getByRole("button", { name: /Sign Out/i })
      .or(page.getByRole("menuitem", { name: /Sign Out/i }))
      .first();
    await expect(signOutButton).toBeVisible({ timeout: 8_000 });
    await signOutButton.click();

    await expect(page).toHaveURL(/\/login/, { timeout: 15_000 });
  });
});
