import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 9 (Task 9.2) — the deterministic, per-role copy layer is applied to the
// report score surfaces (the SEO/AIO headline pillars + the AIO drilldown). Every
// shown pillar score carries a role-appropriate interpretation routed through
// `describeScore(...)`, so:
//   • A Marketer sees plain-language sentences ("You appear in ~X of 10 relevant
//     searches…") — never a raw 0–1 score, never banned jargon like "neural".
//   • A Specialist sees the raw stats first ("SEO sits at X/100, against a healthy
//     threshold of 60/100.").
// Numbers always render as X/100; the underlying scores/gating/layout are unchanged.
//
// This spec is authored for CI (it runs a real fast audit) and is not part of the
// local unit suite. It skips gracefully if a live audit cannot be produced.

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
  await roleGroup.getByRole("radio", { name: role }).click();
  await expect(roleGroup.getByRole("radio", { name: role })).toHaveAttribute(
    "aria-checked",
    "true"
  );
}

test.describe("per-role report copy layer", () => {
  test("Marketer sees plain-language interpretation (no raw 0–1, no jargon)", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("copy-layer-marketer");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    // Marketer is the default role mode for a fresh account.
    await runFastAuditAndOpenReport(page);

    // The SEO pillar renders a plain, benefit-led sentence — not a bare number.
    const marketerInterpretation = page.getByText(/You appear in ~\d+ of 10 relevant searches/i);
    await expect(marketerInterpretation.first()).toBeVisible();

    // The pillar copy line carries no raw 0–1 fraction and no banned jargon.
    const copyText = (await marketerInterpretation.first().innerText()).toLowerCase();
    expect(copyText).not.toMatch(/0\.\d/); // no raw 0–1 score
    expect(copyText).not.toContain("neural");
    expect(copyText).not.toContain("market dominance");

    // Specialist-only raw stat phrasing is absent for a Marketer.
    await expect(page.getByText(/sits at \d+\/100/i)).toHaveCount(0);
  });

  test("Specialist sees raw stats first", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("copy-layer-specialist");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await setRoleMode(page, "Specialist");

    await runFastAuditAndOpenReport(page);

    // Specialists get the raw numbers first in the pillar interpretation.
    await expect(page.getByText(/SEO sits at \d+\/100/i).first()).toBeVisible();
    await expect(page.getByText(/against a healthy threshold of 60\/100/i).first()).toBeVisible();
  });
});
