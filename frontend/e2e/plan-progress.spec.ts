import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin, waitForDashboard } from "./helpers";

// R12 (Task R12.3) — Executive "Plan Progress" UI.
//
// The Plan Progress section lives on the project settings page
// (/dashboard/projects/{id}/settings#plan-progress). It shows how a project's
// Advisor action plan evolves across audits — a compact trend (total +
// high-impact actions over time) and the latest audit-over-audit delta. It is
// read-only and never triggers auto-execution.
//
// Gating is fail-safe LOCKED: an unknown / Starter plan resolves
// `has_done_for_you_execution` to `false`, so the section renders blurred
// behind the existing `GatedSection` upsell ("Available on Executive and
// above"). The Executive-tier trend/delta view requires a pre-seeded Executive
// account supplied via env vars and skips when not configured so CI can run
// without billing setup.

async function openProjectSettings(page: Page): Promise<string> {
  await page.goto("/dashboard/projects");
  await waitForDashboard(page);
  await page
    .getByRole("link", { name: /Settings/i })
    .first()
    .click();
  await expect(page).toHaveURL(/\/dashboard\/projects\/\d+\/settings/, { timeout: 30_000 });
  const match = page.url().match(/projects\/(\d+)\/settings/);
  return match?.[1] ?? "";
}

test.describe("Plan progress UI", () => {
  test("Starter tier: plan-progress section is blurred behind the upsell", async ({ page }) => {
    const user = buildTestUser("plan-progress-free");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    const projectId = await openProjectSettings(page);
    expect(projectId).not.toBe("");

    await page.locator("#plan-progress").scrollIntoViewIfNeeded();
    await expect(
      page
        .locator("#plan-progress")
        .getByText(/Available on Executive and above/i)
        .first()
    ).toBeVisible({ timeout: 15_000 });
  });

  const executiveEmail = process.env.E2E_EXECUTIVE_EMAIL;
  const executivePassword = process.env.E2E_EXECUTIVE_PASSWORD;
  test("Executive tier: sees the plan-progress trend and delta surface", async ({ page }) => {
    test.skip(!executiveEmail || !executivePassword, "E2E_EXECUTIVE_* credentials not configured");

    await loginUser(page, {
      name: "Executive",
      email: executiveEmail as string,
      password: executivePassword as string,
    });
    await waitForDashboard(page);

    const projectId = await openProjectSettings(page);
    expect(projectId).not.toBe("");

    const section = page.getByTestId("plan-progress-view");
    await section.scrollIntoViewIfNeeded();
    await expect(section).toBeVisible({ timeout: 15_000 });

    // The section explains its read-only continuous-management intent.
    await expect(section.getByText(/How your Advisor plan evolves/i)).toBeVisible();
    // It must not present any upsell to an Executive account.
    await expect(section.getByText(/Available on Executive and above/i)).toHaveCount(0);
  });
});
