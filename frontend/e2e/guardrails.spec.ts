import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 6 (Task 6.4) — Brand-integrity Guardrails UI.
//
// The Guardrails section lives on the project settings page
// (/dashboard/projects/{id}/settings#guardrails). It lets a user define the
// brand facts and forbidden claims the audit must respect.
//
// Gating is fail-safe LOCKED: an unknown / Starter plan resolves
// `has_brand_integrity_guardrails` to `false`, so the section renders blurred
// behind the existing `GatedSection` upsell ("Available on Executive and
// above"). The Executive-tier add/list/delete flow requires a pre-seeded
// Executive account supplied via env vars and skips when not configured so CI
// can run without billing setup.

const STATEMENT = `E2E guardrail ${Date.now()}`;

async function openProjectSettings(page: Page): Promise<string> {
  await page.goto("/dashboard/projects");
  await waitForDashboard(page);
  // Open the first project, then navigate to its settings.
  await page
    .getByRole("link", { name: /Settings/i })
    .first()
    .click();
  await expect(page).toHaveURL(/\/dashboard\/projects\/\d+\/settings/, { timeout: 30_000 });
  const match = page.url().match(/projects\/(\d+)\/settings/);
  return match?.[1] ?? "";
}

test.describe("Brand guardrails UI", () => {
  test("Starter tier: guardrails section is blurred behind the upsell", async ({ page }) => {
    const user = buildTestUser("guardrails-free");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    const projectId = await openProjectSettings(page);
    expect(projectId).not.toBe("");

    await page.locator("#guardrails").scrollIntoViewIfNeeded();
    await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible({
      timeout: 15_000,
    });
  });

  const executiveEmail = process.env.E2E_EXECUTIVE_EMAIL;
  const executivePassword = process.env.E2E_EXECUTIVE_PASSWORD;
  test("Executive tier: add a brand fact, see it listed, then delete it", async ({ page }) => {
    test.skip(!executiveEmail || !executivePassword, "E2E_EXECUTIVE_* credentials not configured");

    await loginUser(page, {
      name: "Executive",
      email: executiveEmail as string,
      password: executivePassword as string,
    });
    await waitForDashboard(page);

    const projectId = await openProjectSettings(page);
    expect(projectId).not.toBe("");

    const section = page.getByTestId("guardrails-section");
    await section.scrollIntoViewIfNeeded();
    await expect(section).toBeVisible();

    // Add a brand fact.
    await section.getByLabel(/Statement/i).fill(STATEMENT);
    await section.getByRole("button", { name: /Add Guardrail/i }).click();

    // It appears in the list.
    await expect(section.getByText(STATEMENT)).toBeVisible({ timeout: 15_000 });

    // Delete it.
    await section
      .getByRole("button", { name: new RegExp(`Remove guardrail: ${STATEMENT}`, "i") })
      .click();
    await expect(section.getByText(STATEMENT)).toHaveCount(0, { timeout: 15_000 });
  });
});
