import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 5 (Task 5.2) — the value-ladder blurred upsell. Each tier teases the
// rung above via the existing `GatedSection` upsell ("Upgrade to view"):
//   - Free       → Advisor panel blurred (→ Standard); competitor blurred.
//   - Standard   → Advisor unlocked; Competitor + Comparison blurred (→ Specialist).
//   - Specialist → Competitor unlocked; Execution panel blurred (→ Executive).
//   - Executive  → all unlocked.
//
// Gating is fail-safe LOCKED: an unknown/guest/Starter plan resolves every
// premium capability to `false`. The Free-tier assertions run live against a
// freshly-registered (Starter) account. Higher tiers require a pre-seeded
// account per plan supplied via env vars; those tests skip when the matching
// credentials are not provided so CI can run the suite without billing setup.

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

// The Advisor panel is gated to Standard+. When locked, it renders blurred
// behind the upsell ("Available on Standard and above"); when unlocked the
// `advisor-panel` testid is directly visible.
async function expectAdvisorLocked(page: Page): Promise<void> {
  await expect(page.getByText(/Available on Standard and above/i).first()).toBeVisible();
}

async function expectAdvisorUnlocked(page: Page): Promise<void> {
  await expect(page.getByTestId("advisor-panel").first()).toBeVisible();
  await expect(page.getByText(/Available on Standard and above/i)).toHaveCount(0);
}

// The done-for-you Execution panel is gated to Executive+.
async function expectExecutionLocked(page: Page): Promise<void> {
  await expect(page.getByText(/Available on Executive and above/i).first()).toBeVisible();
}

async function expectExecutionUnlocked(page: Page): Promise<void> {
  await expect(page.getByTestId("execution-panel").first()).toBeVisible();
  await expect(page.getByText(/Available on Executive and above/i)).toHaveCount(0);
}

// The Competitor view is gated to Specialist+ (server-enforced locked section
// rendered via PlanLockNotice on the Competitors tab).
async function openCompetitorsTab(page: Page): Promise<void> {
  await page.getByRole("button", { name: /Competitors/i }).click();
}

async function expectCompetitorLocked(page: Page): Promise<void> {
  await openCompetitorsTab(page);
  await expect(page.getByText(/Specialist/i).first()).toBeVisible();
  await expect(page.getByText(/Upgrade to Specialist/i).first()).toBeVisible();
}

async function expectCompetitorUnlocked(page: Page): Promise<void> {
  await openCompetitorsTab(page);
  await expect(page.getByText(/Upgrade to Specialist/i)).toHaveCount(0);
}

test.describe("Value-ladder blurred upsell", () => {
  test("Free tier: Advisor + Execution blurred, Competitor gated", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("upsell-free");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // Advisor (Standard+) and Execution (Executive+) are both blurred teasers.
    await expectAdvisorLocked(page);
    await expectExecutionLocked(page);

    // Competitor view is gated to Specialist+.
    await expectCompetitorLocked(page);
  });

  // --- Higher tiers: require pre-seeded accounts (skip when unconfigured) ---

  const standardEmail = process.env.E2E_STANDARD_EMAIL;
  const standardPassword = process.env.E2E_STANDARD_PASSWORD;
  test("Standard tier: Advisor unlocked, Competitor + Comparison blurred", async ({ page }) => {
    test.skip(!standardEmail || !standardPassword, "E2E_STANDARD_* credentials not configured");
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    await loginUser(page, {
      name: "Standard",
      email: standardEmail as string,
      password: standardPassword as string,
    });
    await waitForDashboard(page);
    await runFastAuditAndOpenReport(page);

    await expectAdvisorUnlocked(page);
    // Comparison search type stays gated to Specialist+.
    await page.getByText("AIO", { exact: true }).click();
    await expect(page.getByText(/Available on Specialist and above/i).first()).toBeVisible();
    await expectCompetitorLocked(page);
  });

  const specialistEmail = process.env.E2E_SPECIALIST_EMAIL;
  const specialistPassword = process.env.E2E_SPECIALIST_PASSWORD;
  test("Specialist tier: Competitor unlocked, Execution blurred", async ({ page }) => {
    test.skip(
      !specialistEmail || !specialistPassword,
      "E2E_SPECIALIST_* credentials not configured"
    );
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    await loginUser(page, {
      name: "Specialist",
      email: specialistEmail as string,
      password: specialistPassword as string,
    });
    await waitForDashboard(page);
    await runFastAuditAndOpenReport(page);

    await expectAdvisorUnlocked(page);
    await expectExecutionLocked(page);
    await expectCompetitorUnlocked(page);
  });

  const executiveEmail = process.env.E2E_EXECUTIVE_EMAIL;
  const executivePassword = process.env.E2E_EXECUTIVE_PASSWORD;
  test("Executive tier: Advisor, Competitor and Execution all unlocked", async ({ page }) => {
    test.skip(!executiveEmail || !executivePassword, "E2E_EXECUTIVE_* credentials not configured");
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    await loginUser(page, {
      name: "Executive",
      email: executiveEmail as string,
      password: executivePassword as string,
    });
    await waitForDashboard(page);
    await runFastAuditAndOpenReport(page);

    await expectAdvisorUnlocked(page);
    await expectExecutionUnlocked(page);
    await expectCompetitorUnlocked(page);
  });
});
