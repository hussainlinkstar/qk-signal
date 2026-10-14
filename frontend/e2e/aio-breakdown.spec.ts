import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Task 2.4 — opening the AIO pillar reveals a single "AI engine visibility &
// reputation" drilldown that groups the existing AEO + GEO panel content. The
// standalone AEO and GEO tabs only appear in the Specialist IA (shownInMode
// from Phase 1); other modes consume AEO/GEO exclusively through the drilldown.

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

async function setRoleMode(page: Page, role: "Marketer" | "Specialist"): Promise<void> {
  await page.goto("/dashboard/settings");
  await page.waitForLoadState("domcontentloaded");
  const roleGroup = page.getByRole("radiogroup", { name: /role mode/i });
  await expect(roleGroup).toBeVisible({ timeout: 30_000 });

  const persistRequest = page.waitForRequest(
    (request) => request.url().includes("/workspaces/current") && request.method() === "PATCH"
  );
  await roleGroup.getByRole("radio", { name: role }).click();
  await persistRequest;
}

test.describe("AIO drilldown", () => {
  test("Marketer opens AIO and sees the grouped AEO + GEO breakdown", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("aio-breakdown-marketer");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // The breakdown is collapsed until the AIO pillar is opened.
    await expect(page.getByText(/AI engine visibility & reputation/i)).toHaveCount(0);

    await page.getByText("AIO", { exact: true }).click();

    // The grouped drilldown surfaces the AEO + GEO content under one header.
    await expect(page.getByText(/AI engine visibility & reputation/i)).toBeVisible();
    await expect(page.getByText(/Answer Engine readiness \(AEO\)/i)).toBeVisible();
    await expect(page.getByText(/Generative Engine visibility \(GEO\)/i)).toBeVisible();
  });

  test("Specialist also gets standalone AEO and GEO tabs", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("aio-breakdown-specialist");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await setRoleMode(page, "Specialist");
    await runFastAuditAndOpenReport(page);

    // Specialist IA keeps AEO + GEO as their own tabs (shownInMode === true).
    await expect(page.getByRole("button", { name: /^AEO$/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /^GEO$/ })).toBeVisible();
  });
});
