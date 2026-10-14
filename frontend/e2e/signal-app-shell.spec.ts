import { expect, test } from "@playwright/test";
import { buildTestUser, registerAndLogin } from "./helpers";

// ---------------------------------------------------------------------------
// SignalAppShell — shared dashboard/admin sidebar (Phase 1 of the signal-MVP
// UI rewrite, see docs/superpowers/plans/2026-07-13-signal-mvp-ui-rewrite.md).
// Requires the full stack running (backend + DB), same as auth-flows.spec.ts.
// ---------------------------------------------------------------------------

test.describe("SignalAppShell", () => {
  test("dashboard: active nav item is highlighted for the current route", async ({ page }) => {
    const user = buildTestUser("e2e-signal-shell");
    await registerAndLogin(page, user, "/dashboard/overview");

    await page.goto("/dashboard/billing");
    await page.waitForLoadState("domcontentloaded");

    const active = page.locator('[data-signal-nav-item][aria-current="page"]');
    await expect(active).toHaveText(/Billing/);
  });

  test("dashboard: sidebar renders inside the signal-light theme scope", async ({ page }) => {
    const user = buildTestUser("e2e-signal-shell");
    await registerAndLogin(page, user, "/dashboard/overview");

    await expect(
      page.locator("[data-workspace-dashboard-shell] [data-signal-theme]")
    ).toBeVisible();
  });

  test("dashboard: workspace scope renders the approved IA", async ({ page }) => {
    const user = buildTestUser("e2e-signal-shell");
    await registerAndLogin(page, user, "/dashboard/overview");

    await page.goto("/dashboard/billing");
    await page.waitForLoadState("domcontentloaded");

    const nav = page.getByRole("navigation", { name: "Main navigation" });
    for (const name of [
      "Overview",
      "Workspace Settings",
      "My Profile",
      "Billing",
      "Developer Hub",
    ]) {
      await expect(nav.getByRole("link", { name })).toBeVisible();
    }
    // Sign out is an action, never a link.
    await expect(nav.getByRole("button", { name: "Sign out" })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Sign out" })).toHaveCount(0);
    // The mockup's Components catalogue is not customer IA.
    await expect(nav.getByText("Components")).toHaveCount(0);
    // Approved footer: page-level, after <main>, with the consent control.
    await expect(
      page.locator("footer").getByRole("button", { name: "Cookie settings" })
    ).toBeVisible();
  });

  test("dashboard: ⌘K palette lists the authorised destinations and navigates", async ({
    page,
  }) => {
    const user = buildTestUser("e2e-signal-shell");
    await registerAndLogin(page, user, "/dashboard/overview");

    // Both the top-bar affordance and ⌘K open the same palette.
    await page.getByRole("button", { name: "Search" }).click();
    const palette = page.getByRole("dialog");
    await expect(palette).toBeVisible();
    for (const name of ["Overview", "Workspace Settings", "My Profile", "Billing"]) {
      await expect(palette.getByRole("option", { name })).toBeVisible();
    }
    // Non-navigating and unapproved entries are never reachable here.
    for (const name of ["Entities", "Tasks", "Fixes", "Components"]) {
      await expect(palette.getByRole("option", { name })).toHaveCount(0);
    }

    await page.keyboard.press("Escape");
    await expect(palette).not.toBeVisible();

    await page.keyboard.press(process.platform === "darwin" ? "Meta+K" : "Control+K");
    await expect(palette).toBeVisible();
    await palette.getByRole("combobox").fill("billing");
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\/dashboard\/billing/);
  });
});
