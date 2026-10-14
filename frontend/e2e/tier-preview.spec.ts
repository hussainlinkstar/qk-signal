import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 5 (Task 5.3) — non-prod tier preview control.
//
// The `TierPreviewControl` is a QA-only visual override gated behind the
// `NEXT_PUBLIC_ENABLE_TIER_PREVIEW` flag. It swaps the *displayed* capability
// booleans so the value-ladder blur/unlock states can be eyeballed per tier
// WITHOUT changing real entitlements or issuing any server call.
//
// This suite is authored for CI but skips unless the preview flag is enabled
// for the frontend build under test (it is off in prod, so the control never
// mounts there). When enabled, cycling Free → Executive toggles the Advisor
// and Execution panels between blurred ("Upgrade to view") and unlocked.

const TIER_PREVIEW_ENABLED = process.env.NEXT_PUBLIC_ENABLE_TIER_PREVIEW === "true";

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

async function previewTier(page: Page, planKey: string): Promise<void> {
  await page.getByTestId(`tier-preview-${planKey}`).click();
}

test.describe("Non-prod tier preview control", () => {
  test.skip(!TIER_PREVIEW_ENABLED, "NEXT_PUBLIC_ENABLE_TIER_PREVIEW not enabled for this build");

  test("cycling tiers toggles Advisor + Execution unlock/blur", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("tier-preview");
    await registerAndLogin(page, user);
    await waitForDashboard(page);
    await runFastAuditAndOpenReport(page);

    // The QA control only mounts when the flag is on.
    await expect(page.getByTestId("tier-preview-control")).toBeVisible();

    // Free → Advisor (Standard+) and Execution (Executive+) both blurred.
    await previewTier(page, "plan_starter");
    await expect(page.getByText(/Available on Standard and above/i).first()).toBeVisible();
    await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible();

    // Standard → Advisor unlocked; Execution still blurred.
    await previewTier(page, "plan_standard");
    await expect(page.getByTestId("advisor-panel").first()).toBeVisible();
    await expect(page.getByText(/Available on Standard and above/i)).toHaveCount(0);
    await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible();

    // Specialist → Advisor unlocked; Execution still blurred.
    await previewTier(page, "plan_specialist");
    await expect(page.getByTestId("advisor-panel").first()).toBeVisible();
    await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible();

    // Executive → both Advisor and Execution unlocked.
    await previewTier(page, "plan_executive");
    await expect(page.getByTestId("advisor-panel").first()).toBeVisible();
    await expect(page.getByTestId("execution-panel").first()).toBeVisible();
    await expect(page.getByText(/Available on Executive and above/i)).toHaveCount(0);

    // Back to Live → real (Starter) entitlements re-blur both panels.
    await page.getByTestId("tier-preview-live").click();
    await expect(page.getByText(/Available on Standard and above/i).first()).toBeVisible();
    await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible();
  });
});
