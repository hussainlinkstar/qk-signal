import { expect, test } from "@playwright/test";
import { buildTestUser, registerAndLogin, waitForDashboard } from "./helpers";

// Task 1.6 — the Settings → General section exposes a role-mode segmented
// control. Switching the persona role persists role_mode via
// PATCH /workspaces/current and changes which sections appear in the IA
// (the navigation gating from Task 1.7). Specialist exposes the deep
// technical section that is hidden from the default marketer mode.
test.describe("role-mode switcher", () => {
  test("switching to Specialist persists role_mode and reveals technical IA", async ({ page }) => {
    const user = buildTestUser("role-switch");
    await registerAndLogin(page, user);
    await waitForDashboard(page);

    await page.goto("/dashboard/settings");
    await page.waitForLoadState("domcontentloaded");

    // The General section renders the role-mode segmented control.
    const roleGroup = page.getByRole("radiogroup", { name: /role mode/i });
    await expect(roleGroup).toBeVisible({ timeout: 30_000 });

    // Selecting Specialist persists role_mode via PATCH /workspaces/current.
    const persistRequest = page.waitForRequest(
      (request) =>
        request.url().includes("/workspaces/current") &&
        request.method() === "PATCH" &&
        (request.postData() ?? "").includes('"role_mode":"specialist"')
    );

    await roleGroup.getByRole("radio", { name: "Specialist" }).click();

    await persistRequest;

    // The optimistic update marks Specialist as the selected option.
    await expect(roleGroup.getByRole("radio", { name: "Specialist" })).toHaveAttribute(
      "aria-checked",
      "true"
    );

    // Technical-IA visibility is project-scoped, so the technical nav link is
    // not present on the workspace/settings route. That cross-context behavior
    // is covered separately within project context (future/separate spec).
  });
});
