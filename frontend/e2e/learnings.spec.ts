import { expect, test, type Page } from "@playwright/test";
import { loginUser, waitForDashboard } from "./helpers";

// Phase 7 (Task 7.3) — Learnings loop UI.
//
// Users accept/dismiss Advisor recommendations from the report's "What to fix,
// in order" panel. Dismissing an action removes it from the current plan and
// records a decision; the backend suppresses dismissed actions on future
// audits. The full accept/dismiss history is shown under the project settings
// Learnings section (/dashboard/projects/{id}/settings#learnings).
//
// The accept/dismiss controls only render for a project-scoped audit on a
// Standard+ plan (the Advisor panel is otherwise gated/blurred). This flow
// therefore requires a pre-seeded Standard+ account supplied via env vars and
// skips when not configured so CI can run without billing setup.

const AUDIT_TARGET_URL = process.env.E2E_AUDIT_URL ?? "https://thothgraph.com";
const AUDIT_WAIT_TIMEOUT_MS = Number(process.env.E2E_AUDIT_TIMEOUT_MS ?? 12 * 60 * 1000);
const AUDIT_TEST_TIMEOUT_MS = AUDIT_WAIT_TIMEOUT_MS + 180_000;

const standardEmail = process.env.E2E_STANDARD_EMAIL;
const standardPassword = process.env.E2E_STANDARD_PASSWORD;

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

test.describe("Learnings loop UI", () => {
  test("dismiss an advisor action → it disappears, is logged under Learnings, and persists", async ({
    page,
  }) => {
    test.skip(!standardEmail || !standardPassword, "E2E_STANDARD_* credentials not configured");
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    await loginUser(page, {
      name: "Standard",
      email: standardEmail as string,
      password: standardPassword as string,
    });
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    const panel = page.getByTestId("advisor-panel");
    await panel.scrollIntoViewIfNeeded();
    await expect(panel).toBeVisible();

    // Capture the first action's headline text before dismissing it.
    const firstAction = panel.locator("ol > li").first();
    await expect(firstAction).toBeVisible();
    const actionTitle = (await firstAction.locator("p").first().innerText()).trim();
    const initialCount = await panel.locator("ol > li").count();

    // Dismiss it — the row is optimistically removed from the plan.
    await firstAction.getByRole("button", { name: /^Dismiss/i }).click();
    await expect(panel.locator("ol > li")).toHaveCount(initialCount - 1, { timeout: 15_000 });
    await expect(panel.getByText(actionTitle, { exact: true })).toHaveCount(0);

    // The decision is recorded under the project's Learnings section.
    await page.goto("/dashboard/projects");
    await waitForDashboard(page);
    await page
      .getByRole("link", { name: /Settings/i })
      .first()
      .click();
    await expect(page).toHaveURL(/\/dashboard\/projects\/\d+\/settings/, { timeout: 30_000 });

    const learnings = page.getByTestId("learnings-view");
    await learnings.scrollIntoViewIfNeeded();
    await expect(learnings).toBeVisible();
    await expect(learnings.getByText(/Dismissed/i).first()).toBeVisible({ timeout: 15_000 });
    const dismissedCount = await learnings.getByTestId("learnings-row").count();
    expect(dismissedCount).toBeGreaterThan(0);

    // It persists across a reload.
    await page.reload();
    await learnings.scrollIntoViewIfNeeded();
    await expect(learnings).toBeVisible();
    await expect(learnings.getByTestId("learnings-row")).toHaveCount(dismissedCount, {
      timeout: 15_000,
    });
  });
});
