import { expect, test, type Page } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin, waitForDashboard } from "./helpers";

// Phase 8 (Task 8.3) — the conversational, audit-grounded Advisor chat. A panel
// on the report ("Ask the advisor") answers questions strictly about THIS audit
// and renders the reply plus citation chips (finding ids). It is gated to
// Standard+ via the same `canSeeAdvisor` capability as the Advisor panel: Free
// sees a blurred `GatedSection` upsell ("Available on Standard and above").
//
// The Free-tier (blurred) assertion runs live against a freshly-registered
// Starter account. The grounded-answer flow requires a Standard+ account
// supplied via env vars; it skips when those credentials are not configured so
// CI can run without billing setup.

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

test.describe("Advisor chat", () => {
  test("Free tier: advisor chat is blurred behind the Standard upsell", async ({ page }) => {
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    const user = buildTestUser("advisor-chat-free");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await runFastAuditAndOpenReport(page);

    // The gated chat renders the upsell teaser, not an interactive input.
    await expect(page.getByText(/Available on Standard and above/i).first()).toBeVisible();
  });

  const standardEmail = process.env.E2E_STANDARD_EMAIL;
  const standardPassword = process.env.E2E_STANDARD_PASSWORD;
  test("Standard tier: ask a question → grounded answer with a citation chip", async ({ page }) => {
    test.skip(!standardEmail || !standardPassword, "E2E_STANDARD_* credentials not configured");
    test.setTimeout(AUDIT_TEST_TIMEOUT_MS);

    await loginUser(page, {
      name: "Standard",
      email: standardEmail as string,
      password: standardPassword as string,
    });
    await waitForDashboard(page);
    await runFastAuditAndOpenReport(page);

    const chat = page.getByTestId("advisor-chat");
    await expect(chat).toBeVisible();
    await expect(chat.getByRole("heading", { name: /Ask the advisor/i })).toBeVisible();

    // Ask a grounded question about this audit.
    await chat.getByTestId("advisor-chat-input").fill("Why am I losing the comparison queries?");
    await chat.getByTestId("advisor-chat-send").click();

    // The question echoes as a user turn and an assistant reply arrives.
    await expect(chat.getByTestId("advisor-chat-message-user").first()).toContainText(
      /comparison queries/i
    );
    await expect(chat.getByTestId("advisor-chat-message-assistant").first()).toBeVisible({
      timeout: 30_000,
    });

    // The grounded answer cites at least one finding (citation chip).
    await expect(chat.getByTestId("advisor-chat-citation").first()).toBeVisible();
  });
});
