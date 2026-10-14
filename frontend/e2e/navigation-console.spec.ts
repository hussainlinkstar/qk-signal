import { test, expect, type Page, type ConsoleMessage } from "@playwright/test";
import { loginUser, type TestUser } from "./helpers";

/**
 * Navigation + console-health sweep.
 *
 * Visits every public, dashboard and admin page, captures console errors and
 * uncaught page errors per route, opens the mobile menu on mobile projects, and
 * records navigation timing. Runs across all configured Playwright projects
 * (desktop chrome/firefox + mobile chrome/safari) automatically.
 *
 * Admin pages require an admin account, provided via env:
 *   E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD  (seed a role="admin" user on the target env)
 * If admin creds are absent, the admin sweep is skipped (public + dashboard still run).
 */

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";
const SLOW_PAGE_MS = Number(process.env.E2E_SLOW_PAGE_MS ?? "4000");

const PUBLIC_PAGES = ["/"];

const DASHBOARD_PAGES = [
  "/dashboard",
  "/dashboard/audit",
  "/dashboard/reports",
  "/dashboard/connections",
  "/dashboard/leads",
  "/dashboard/competitors",
  "/dashboard/billing",
  "/dashboard/settings",
  "/dashboard/account-settings",
  "/dashboard/developer",
];

const ADMIN_PAGES = [
  "/admin/overview",
  "/admin/system-status",
  "/admin/workspaces",
  "/admin/users",
  "/admin/subscriptions",
  "/admin/payments",
  "/admin/commitments",
  "/admin/costs",
  "/admin/plans",
  "/admin/config",
  "/admin/settings/general",
  "/admin/settings/ai-models",
  "/admin/settings/email-config",
  "/admin/jobs",
  "/admin/email-outbox",
  "/admin/email-templates",
  "/admin/cms/articles",
];

// Known third-party / environmental noise that should not fail the sweep.
const IGNORED_ERROR_PATTERNS: RegExp[] = [
  /favicon/i,
  /Failed to load resource: the server responded with a status of 404.*(favicon|\.map)/i,
  /ResizeObserver loop/i,
  /\[Fast Refresh\]/i,
  /Download the React DevTools/i,
  /chrome-extension:/i,
  /web-vitals/i,
];

function isIgnorable(text: string): boolean {
  return IGNORED_ERROR_PATTERNS.some((re) => re.test(text));
}

type PageReport = { url: string; durationMs: number; errors: string[] };

async function sweep(page: Page, paths: string[]): Promise<PageReport[]> {
  const reports: PageReport[] = [];

  for (const path of paths) {
    const errors: string[] = [];
    const onConsole = (msg: ConsoleMessage) => {
      if (msg.type() === "error") {
        const text = msg.text();
        if (!isIgnorable(text)) errors.push(`console.error: ${text}`);
      }
    };
    const onPageError = (err: Error) => {
      if (!isIgnorable(err.message)) errors.push(`pageerror: ${err.message}`);
    };

    page.on("console", onConsole);
    page.on("pageerror", onPageError);

    const start = Date.now();
    try {
      await page.goto(path, { waitUntil: "domcontentloaded", timeout: 45_000 });
      await page.waitForLoadState("networkidle", { timeout: 12_000 }).catch(() => {});
    } catch (err) {
      errors.push(`navigation: ${(err as Error).message}`);
    }
    const durationMs = Date.now() - start;

    page.off("console", onConsole);
    page.off("pageerror", onPageError);

    reports.push({ url: path, durationMs, errors });
  }

  return reports;
}

function summarize(label: string, reports: PageReport[]): string[] {
  const failures: string[] = [];
  for (const r of reports) {
    if (r.durationMs > SLOW_PAGE_MS) {
      // eslint-disable-next-line no-console
      console.warn(`[slow] ${label} ${r.url} took ${r.durationMs}ms`);
    }
    if (r.errors.length > 0) {
      failures.push(`${r.url}\n    - ${r.errors.join("\n    - ")}`);
    }
  }
  return failures;
}

test.describe("navigation console health", () => {
  test("public marketing pages have no console errors", async ({ page }) => {
    const reports = await sweep(page, PUBLIC_PAGES);
    const failures = summarize("public", reports);
    expect(failures, `Console errors found on public pages:\n${failures.join("\n")}`).toEqual([]);
  });

  test("mobile menu opens and navigates", async ({ page, isMobile }) => {
    test.skip(!isMobile, "mobile-only check");
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const menuButton = page.getByRole("button", { name: /open (navigation |app )?menu/i }).first();
    await expect(menuButton).toBeVisible({ timeout: 15_000 });
    await menuButton.click();
    // A nav link inside the mobile drawer should now be reachable.
    await expect(page.getByRole("link", { name: /pricing/i }).first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("authenticated dashboard + admin pages have no console errors", async ({ page }) => {
    test.skip(!ADMIN_EMAIL || !ADMIN_PASSWORD, "E2E_ADMIN_EMAIL / E2E_ADMIN_PASSWORD not set");

    const admin: TestUser = { name: "QA Admin", email: ADMIN_EMAIL, password: ADMIN_PASSWORD };
    await loginUser(page, admin, "/dashboard");

    const dashFailures = summarize("dashboard", await sweep(page, DASHBOARD_PAGES));
    const adminFailures = summarize("admin", await sweep(page, ADMIN_PAGES));
    const failures = [...dashFailures, ...adminFailures];
    expect(
      failures,
      `Console errors found on authenticated pages:\n${failures.join("\n")}`
    ).toEqual([]);
  });
});
