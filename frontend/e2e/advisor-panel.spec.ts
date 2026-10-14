import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 3 (Tasks 3.2–3.4) — the deterministic, ROI-ranked Advisor plan is
// surfaced in the report as a "What to fix, in order" panel: a numbered list of
// actions, each with an expected-lift chip and an effort tag. The plan is
// sourced from `report.metadata.advisor` (attached by the backend in Task 3.1)
// and mapped via `getAdvisorPlan`. Plan-tier gating (`isLocked`) is wired in
// Phase 5; here we assert the panel renders for a real audit.

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

test.describe("Advisor panel", () => {
  test("report shows an ROI-ranked 'What to fix, in order' action list", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("advisor-panel");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    const panel = page.getByTestId("advisor-panel");
    await expect(panel).toBeVisible();

    // Header + ROI subtitle.
    await expect(panel.getByRole("heading", { name: /What to fix, in order/i })).toBeVisible();
    await expect(panel.getByText(/biggest, easiest wins first/i)).toBeVisible();

    // At least one numbered action with an expected-lift chip and an effort tag.
    const firstAction = panel.locator("ol > li").first();
    await expect(firstAction).toBeVisible();
    await expect(firstAction.getByText(/lift/i)).toBeVisible();
    await expect(firstAction.getByText(/effort/i)).toBeVisible();
  });
});
