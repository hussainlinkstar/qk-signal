import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Task 4.3 — opening the AIO drilldown surfaces the 5 customer-facing search
// types (Brand, Category, Problem, Feature, Comparison) as cards. The premium
// Comparison card is gated to Specialist+: on a Standard (or guest/starter)
// plan it is blurred behind the "Upgrade to view" upsell.

const AUDIT_TARGET_URL = process.env.E2E_AUDIT_URL ?? "https://thothgraph.com";
const AUDIT_WAIT_TIMEOUT_MS = Number(process.env.E2E_AUDIT_TIMEOUT_MS ?? 12 * 60 * 1000);
const AUDIT_TEST_TIMEOUT_MS = AUDIT_WAIT_TIMEOUT_MS + 120_000;

async function runFastAuditAndOpenReport(page: Page): Promise<void> {
  await page.goto("/dashboard/audit");
  await expect(page.getByRole("heading", { name: /Audit Workspace/i })).toBeVisible();

  await page.locator("#audit-url").evaluate((node, value) => {
    const input = node as HTMLInputElement;
    input.value = String(value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }, AUDIT_TARGET_URL);

  const runAuditButton = page.getByRole("button", { name: /Initialize Neural Scan/i });
  await expect(runAuditButton).toBeEnabled();
  await runAuditButton.click();

  await expect(page.getByText(/Verified by Qiko Signal NeuralCore/i)).toBeVisible({
    timeout: AUDIT_WAIT_TIMEOUT_MS,
  });
}

test.describe("Search types under AIO", () => {
  test("AIO drilldown shows the 5 search-type cards with Comparison gated", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("search-types-standard");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // Open the AIO drilldown.
    await page.getByText("AIO", { exact: true }).click();
    await expect(page.getByText(/AI engine visibility & reputation/i)).toBeVisible();

    // The "Search types" group and the 5 named cards are rendered.
    await expect(page.getByText(/^Search types$/i)).toBeVisible();
    await expect(page.getByText(/^Brand$/i)).toBeVisible();
    await expect(page.getByText(/^Category$/i)).toBeVisible();
    await expect(page.getByText(/^Problem$/i)).toBeVisible();
    await expect(page.getByText(/^Feature$/i)).toBeVisible();
    await expect(page.getByText(/^Comparison search type$/i)).toBeVisible();

    // On a non-Specialist plan, the Comparison card is gated (blurred upsell).
    await expect(page.getByText(/Upgrade to view|Unlock Full Report/i).first()).toBeVisible();
    await expect(page.getByText(/Available on Specialist and above/i)).toBeVisible();
  });

  // Regression guard for the Phase 4 gating leak: the `/dashboard/audit/[id]`
  // detail route renders <OverviewTab> directly. The `canSeeComparison` prop
  // must be passed (and default to LOCKED) so the premium Comparison card stays
  // gated for non-Specialist plans on the detail route too.
  test("audit detail route keeps the Comparison card gated for non-Specialist plans", async ({
    page,
  }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("search-types-detail-standard");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // Open the audit history list and navigate into the standalone detail route.
    await page.goto("/dashboard/audit");
    const reportLink = page.locator('a[href^="/dashboard/audit/"]').first();
    await expect(reportLink).toBeVisible();
    await reportLink.click();
    await expect(page).toHaveURL(/\/dashboard\/audit\/[^/]+$/);

    // Open the AIO drilldown on the detail route.
    await page.getByText("AIO", { exact: true }).click();
    await expect(page.getByText(/^Comparison search type$/i)).toBeVisible();

    // The Comparison card must remain gated (blurred upsell) on this route.
    await expect(page.getByText(/Upgrade to view|Unlock Full Report/i).first()).toBeVisible();
    await expect(page.getByText(/Available on Specialist and above/i)).toBeVisible();
  });
});
