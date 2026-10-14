import { expect, test } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin } from "./helpers";

// ---------------------------------------------------------------------------
// Billing Flows
// ---------------------------------------------------------------------------

test.describe("Billing Flows", () => {
  test.describe.configure({ mode: "serial" });

  let sharedUser: ReturnType<typeof buildTestUser>;

  test.beforeAll(async ({ browser }) => {
    sharedUser = buildTestUser("e2e-billing");
    const page = await browser.newPage();
    await registerAndLogin(page, sharedUser);
    await page.close();
  });

  test("should display the billing page with plan information", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/billing");

    await expect(page.getByText(/Billing/i).first()).toBeVisible({ timeout: 30_000 });

    await expect(
      page.getByText(/Active Subscription|Current|Free|Explorer|Plan/i).first()
    ).toBeVisible();
  });

  test("should display plan cards in the Plans section", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/billing");

    await expect(page.getByText(/Billing/i).first()).toBeVisible({ timeout: 30_000 });

    const plansTab = page
      .getByRole("button", { name: /Plans/i })
      .or(page.getByRole("tab", { name: /Plans/i }))
      .first();
    await expect(plansTab).toBeVisible({ timeout: 10_000 });
    await plansTab.click();

    await expect(page.getByText(/Available Plans/i).first()).toBeVisible({ timeout: 15_000 });

    await expect(page.getByText(/audits\/mo/i).first()).toBeVisible({ timeout: 10_000 });
  });

  test("should display plan comparison matrix", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/billing");

    await expect(page.getByText(/Billing/i).first()).toBeVisible({ timeout: 30_000 });

    const comparisonTab = page
      .getByRole("button", { name: /Comparison/i })
      .or(page.getByRole("tab", { name: /Comparison/i }))
      .first();
    await expect(comparisonTab).toBeVisible({ timeout: 10_000 });
    await comparisonTab.click();

    await expect(page.getByText(/Plan Comparison/i).first()).toBeVisible({ timeout: 15_000 });
  });

  test("should display the billing history page", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/billing/history");

    await expect(page.getByText(/Billing History/i).first()).toBeVisible({ timeout: 30_000 });

    await expect(page.getByText(/Invoice History/i).first()).toBeVisible({ timeout: 15_000 });

    // Either invoices are listed or the empty-state is shown
    const hasInvoices = await page
      .getByText(/paid|pending|draft/i)
      .first()
      .isVisible({ timeout: 5_000 })
      .catch(() => false);
    const hasEmptyState = await page
      .getByText(/No invoices yet/i)
      .isVisible({ timeout: 5_000 })
      .catch(() => false);

    expect(
      hasInvoices || hasEmptyState,
      "Expected invoice rows or 'No invoices yet' empty state"
    ).toBe(true);
  });
});
