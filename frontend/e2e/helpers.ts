import { expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type TestUser = {
  name: string;
  email: string;
  password: string;
};

// ---------------------------------------------------------------------------
// User factory
// ---------------------------------------------------------------------------

export function buildTestUser(prefix = "e2e"): TestUser {
  const nonce = `${Date.now()}-${Math.round(Math.random() * 100_000)}`;
  return {
    name: `E2E ${nonce}`,
    email: `${prefix}+${nonce}@example.com`,
    password: "QikoSignalE2E123!",
  };
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

export async function registerUser(page: Page, user: TestUser): Promise<void> {
  await page.goto("/register");
  await page.waitForLoadState("domcontentloaded");

  await page.getByPlaceholder("Agency or company name").fill(user.name);
  await page.getByPlaceholder("you@company.com").fill(user.email);

  const passwordInputs = page.locator('input[type="password"]');
  await passwordInputs.nth(0).fill(user.password);
  await passwordInputs.nth(1).fill(user.password);

  const legalCheckbox = page.locator("#register-legal-consent");
  // The restyled register page renders this input as sr-only with a styled
  // span on top, so a strict-actionability check can never click it.
  if (await legalCheckbox.count()) {
    await legalCheckbox.check({ force: true });
  }

  await page.getByRole("button", { name: /Create account/i }).click();

  // Wait for redirect to /login after successful registration
  await expect(page).toHaveURL(/\/login/, { timeout: 30_000 });
}

// ---------------------------------------------------------------------------
// Login
// ---------------------------------------------------------------------------

export async function loginUser(
  page: Page,
  user: TestUser,
  expectedPath = "/dashboard/overview"
): Promise<void> {
  await page.goto(`/login?redirect_url=${encodeURIComponent(expectedPath)}`);
  await page.waitForLoadState("domcontentloaded");

  await page.getByPlaceholder("your@email.com").fill(user.email);
  await page.locator('input[type="password"]').first().fill(user.password);
  await page.getByRole("button", { name: /^Sign In$/i }).click();

  // Wait for redirect to dashboard
  await expect(page).toHaveURL(new RegExp(expectedPath.replace(/\//g, "\\/")), {
    timeout: 30_000,
  });
}

// ---------------------------------------------------------------------------
// Register + Login combined
// ---------------------------------------------------------------------------

export async function registerAndLogin(
  page: Page,
  user: TestUser,
  expectedPath = "/dashboard/overview"
): Promise<void> {
  await registerUser(page, user);
  await loginUser(page, user, expectedPath);
}

// ---------------------------------------------------------------------------
// Wait for dashboard to be fully loaded
// ---------------------------------------------------------------------------

export async function waitForDashboard(page: Page): Promise<void> {
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
  // Wait for the main content to load — spinner disappears
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {
    // networkidle can be unreliable on slow pages — continue anyway
  });
}
