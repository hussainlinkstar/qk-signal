import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Task 2.5 — the audit report Overview leads with exactly TWO headline
// pillars (SEO + AIO) rather than the legacy 4-gauge matrix. AIO is the
// customer-facing roll-up of the unchanged AEO + GEO engine outputs. For the
// default Marketer mode the raw AEO/GEO gauges and standalone tabs are not
// shown as a headline — they live inside the AIO drilldown.

const AUDIT_TARGET_URL = process.env.E2E_AUDIT_URL ?? "https://thothgraph.com";
const AUDIT_WAIT_TIMEOUT_MS = Number(process.env.E2E_AUDIT_TIMEOUT_MS ?? 12 * 60 * 1000);
const AUDIT_TEST_TIMEOUT_MS = AUDIT_WAIT_TIMEOUT_MS + 60_000;

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

  // The report renders once the audit completes.
  await expect(page.getByText(/Verified by Qiko Signal NeuralCore/i)).toBeVisible({
    timeout: AUDIT_WAIT_TIMEOUT_MS,
  });
}

test.describe("two-pillar overview", () => {
  test("Overview shows exactly two headline pillars (SEO, AIO) for a Marketer", async ({
    page,
  }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("overview-two-pillar");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // Two headline pillars only: SEO + AIO.
    await expect(page.getByText("SEO", { exact: true })).toBeVisible();
    await expect(page.getByText("AIO", { exact: true })).toBeVisible();
    await expect(page.getByText(/Click SEO or AIO to see the detailed breakdown/i)).toBeVisible();

    // Scope badges reflect the SEO (website) + AIO (website & brand) framing.
    await expect(page.getByText("Website only", { exact: true })).toBeVisible();
    await expect(page.getByText("Website & Brand", { exact: true })).toBeVisible();

    // Marketer IA hides the standalone AEO/GEO tabs (they live in the AIO drilldown).
    await expect(page.getByRole("button", { name: /^AEO$/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^GEO$/ })).toHaveCount(0);
  });
});
