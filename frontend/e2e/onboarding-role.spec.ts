import { expect, test } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Task 1.5 — the onboarding wizard must ask for the persona role first and
// persist it on the workspace via PATCH /workspaces/current before the
// existing workspace-setup step.
test.describe("onboarding role step", () => {
  test("onboarding asks for role and persists it", async ({ page }) => {
    const user = buildTestUser("onboarding-role");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    // The wizard auto-opens for fresh users on the overview page.
    await expect(page.getByText("What's your role?")).toBeVisible({ timeout: 30_000 });

    // All five persona options are offered.
    await expect(page.getByRole("button", { name: "Marketer" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Specialist" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Agency" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Enterprise" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Just exploring" })).toBeVisible();

    // Selecting a role and continuing persists role_mode and advances to the
    // workspace-setup step.
    const persistRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/workspaces/current") &&
        request.method() === "PATCH" &&
        (request.postData() ?? "").includes('"role_mode":"agency"')
    );

    await page.getByRole("button", { name: "Agency" }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    await persistRequest;

    // The existing workspace step appears next.
    await expect(page.getByText(/set up your workspace/i)).toBeVisible();
  });

  // Task 1.8 — the role picked in step 1 chooses a DEFAULT audit tier for the
  // first scan. Specialist → Deep (deep_judgment). It remains only a default:
  // the audit page still exposes the tier control and backend plan gating
  // continues to apply.
  test("specialist defaults the first scan to the Deep tier", async ({ page }) => {
    const user = buildTestUser("onboarding-role-tier");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await expect(page.getByText("What's your role?")).toBeVisible({ timeout: 30_000 });

    // Step 1 — pick Specialist and continue.
    await page.getByRole("button", { name: "Specialist" }).click();
    await page.getByRole("button", { name: /continue/i }).click();

    // Step 2 — workspace setup.
    await expect(page.getByText(/set up your workspace/i)).toBeVisible();
    await page.getByRole("button", { name: /continue/i }).click();

    // Step 3 — create the first project.
    await expect(page.getByText(/add your first project/i)).toBeVisible();
    await page.getByLabel("Project Name").fill("Specialist Site");
    await page.getByRole("button", { name: /create project/i }).click();

    // Step 4 — launch the first audit.
    await expect(page.getByText(/start your first audit/i)).toBeVisible();
    await page.getByRole("button", { name: /run audit now/i }).click();

    // The audit page opens with the Deep tier defaulted from the Specialist
    // role mode (the tier carries through the route query string).
    await page.waitForURL(/\/dashboard\/audit\?.*tier=deep_judgment/);

    // The tier control still renders (override remains possible) and the
    // Deep option is the active default.
    await expect(page.getByRole("button", { name: /analysis depth deep/i })).toBeVisible();
  });
});
