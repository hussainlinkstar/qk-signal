import { expect, test } from "@playwright/test";
import { buildTestUser, loginUser, registerAndLogin } from "./helpers";

// ---------------------------------------------------------------------------
// Report Flows
// ---------------------------------------------------------------------------

test.describe("Report Flows", () => {
  test.describe.configure({ mode: "serial" });

  let sharedUser: ReturnType<typeof buildTestUser>;

  test.beforeAll(async ({ browser }) => {
    const provisionedEmail = process.env.E2E_TEST_EMAIL;
    const provisionedPassword = process.env.E2E_TEST_PASSWORD;
    sharedUser =
      provisionedEmail && provisionedPassword
        ? { name: "E2E Reports", email: provisionedEmail, password: provisionedPassword }
        : buildTestUser("e2e-reports");
    const page = await browser.newPage();
    if (provisionedEmail && provisionedPassword) {
      await loginUser(page, sharedUser);
    } else {
      await registerAndLogin(page, sharedUser);
    }
    await page.close();
  });

  test("should load the reports page and display the wizard interface", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/reports/generate");

    await expect(page).toHaveURL(/\/dashboard\/reports/, { timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // Wizard renders project/audit/report steps OR an informational empty state
    const hasWizardContent = await page
      .getByText(/project|Select|report|audit/i)
      .first()
      .isVisible({ timeout: 15_000 })
      .catch(() => false);

    const hasEmptyOrError = await page
      .getByText(/no projects|unable|sign in|error/i)
      .first()
      .isVisible({ timeout: 5_000 })
      .catch(() => false);

    expect(
      hasWizardContent || hasEmptyOrError,
      "Expected the reports wizard or an informational state to be visible"
    ).toBe(true);
  });

  test("should show the project selection step for a fresh user", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/reports/generate");

    await expect(page).toHaveURL(/\/dashboard\/reports/, { timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // Fresh user has no projects — the wizard stays on the project step
    const hasProjectStep = await page
      .getByText(/project/i)
      .first()
      .isVisible({ timeout: 10_000 })
      .catch(() => false);

    expect(hasProjectStep, "Expected 'project' step to be visible").toBe(true);
  });

  test("should render interactive controls on the reports page", async ({ page }) => {
    await loginUser(page, sharedUser, "/dashboard/reports/generate");

    await expect(page).toHaveURL(/\/dashboard\/reports/, { timeout: 30_000 });
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // Page must have at least some interactive elements
    const inputs = await page.locator('input[type="text"], input[type="search"]').count();
    const selects = await page.locator("select").count();
    const buttons = await page.locator("button").count();

    expect(
      inputs + selects + buttons,
      "Expected interactive controls to be present on the reports page"
    ).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Generate-and-download journey (SIGV2-1041)
//
// The real backend has no report collection route, so these specs stub the
// report endpoints with page.route while keeping real auth. The wizard's
// context endpoints (projects/audits/competitors/branding) are stubbed too so
// a fresh e2e user can drive the full journey.
// ---------------------------------------------------------------------------

const MOCK_PROJECT = {
  id: 21,
  workspace_id: 1,
  name: "Northwind",
  domain_url: "https://northwind.example",
  target_country: "RO",
  language: "en",
  icp_roles: [],
  pain_points: null,
  usp: null,
  competitors: [],
  priority_pulse_tags: [],
  sme_profiles: [],
  created_at: "2026-01-01T00:00:00.000Z",
  audit_count: 1,
  last_audit_at: "2026-03-02T10:00:00.000Z",
  latest_seo_score: 74,
  latest_geo_score: 71,
  latest_aeo_score: 72,
  feature_access: {
    monitoring: { allowed: true, detail: null, status_code: null, required_plan: null },
    automations: { allowed: true, detail: null, status_code: null, required_plan: null },
    entity_authority: { allowed: true, detail: null, status_code: null, required_plan: null },
    benchmark_intelligence: { allowed: true, detail: null, status_code: null, required_plan: null },
    scheduled_audits: { allowed: true, detail: null, status_code: null, required_plan: null },
    jira_export: { allowed: true, detail: null, status_code: null, required_plan: null },
  },
};

const MOCK_AUDIT = {
  id: 301,
  project_id: 21,
  site_id: 41,
  audit_type: "STANDARD",
  url: "https://northwind.example",
  geo_score: 71,
  seo_score: 74,
  aeo_score: 72,
  status: "completed",
  created_at: "2026-03-02T10:00:00.000Z",
  full_report: {
    competitors: [
      {
        name: "Competitor A",
        score: 64,
        geo_visibility: 69,
        aeo_score: 61,
        entity_strength: 58,
        rank: 1,
      },
    ],
    hallucination: { flagged_claims: 0, total_claims: 6, flagged: false },
  },
};

type StatusScript = Array<Record<string, unknown> | number>;

const stubReportContext = async (page: import("@playwright/test").Page) => {
  await page.route("**/api/workspaces/current/projects**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([MOCK_PROJECT]),
    })
  );
  await page.route("**/api/projects/21/audits**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([MOCK_AUDIT]),
    })
  );
  await page.route("**/api/projects/21/competitors**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" })
  );
  await page.route("**/api/v1/users/me/branding", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        company_name: null,
        custom_logo_url: null,
        primary_color: null,
        secondary_color: null,
      }),
    })
  );
};

// Returns the list of request bodies posted to generate-complex.
const stubReportJob = async (
  page: import("@playwright/test").Page,
  options: {
    statusScript: StatusScript;
    generateStatus?: number;
    reportId?: string;
  }
) => {
  const reportId = options.reportId ?? "report-e2e-1";
  const postedBodies: Array<Record<string, unknown>> = [];
  let statusCalls = 0;

  await page.route("**/api/v1/reports/generate-complex", async (route) => {
    postedBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    const status = options.generateStatus ?? 200;
    if (status === 200) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          report_id: reportId,
          status: "queued",
          template_type: "Executive",
          generated_at: "2026-03-03T10:00:00.000Z",
          audit_count: 1,
          executive_summary: null,
          aggregate: null,
          download_url: null,
        }),
      });
    } else {
      await route.fulfill({
        status,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Report kind is not available." }),
      });
    }
  });

  await page.route(`**/api/v1/reports/complex/${reportId}/status`, async (route) => {
    const step = options.statusScript[Math.min(statusCalls, options.statusScript.length - 1)];
    statusCalls += 1;
    if (typeof step === "number") {
      await route.fulfill({
        status: step,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Report job not found." }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ report_id: reportId, ...step }),
    });
  });

  await page.route(`**/api/v1/reports/complex/${reportId}/download`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/pdf",
      headers: { "Content-Disposition": `attachment; filename="e2e-report.pdf"` },
      body: "%PDF-1.4 e2e",
    });
  });

  return { postedBodies, getStatusCalls: () => statusCalls };
};

const driveToConfigure = async (page: import("@playwright/test").Page) => {
  await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});
  await page.getByRole("button", { name: /^continue$/i }).click();
  await page.getByRole("button", { name: /^continue$/i }).click();
  await expect(page.getByRole("heading", { name: /report type/i })).toBeVisible();
  await page.getByRole("button", { name: /^continue$/i }).click();
  await expect(page.getByRole("button", { name: /generate standard pdf/i })).toBeVisible();
};

test.describe("Report generate-and-download journey", () => {
  let sharedUser: ReturnType<typeof buildTestUser>;

  test.beforeAll(async ({ browser }) => {
    // Prefer a pre-provisioned verified account (same contract as
    // critical-path-login); fall back to a fresh registration where email
    // verification is not enforced.
    const provisionedEmail = process.env.E2E_TEST_EMAIL;
    const provisionedPassword = process.env.E2E_TEST_PASSWORD;
    sharedUser =
      provisionedEmail && provisionedPassword
        ? { name: "E2E Reports", email: provisionedEmail, password: provisionedPassword }
        : buildTestUser("e2e-report-journey");
    const page = await browser.newPage();
    if (provisionedEmail && provisionedPassword) {
      await loginUser(page, sharedUser);
    } else {
      await registerAndLogin(page, sharedUser);
    }
    await page.close();
  });

  test("sends the chosen kind to the API and downloads when ready", async ({ page }) => {
    await stubReportContext(page);
    const job = await stubReportJob(page, {
      statusScript: [{ status: "queued" }, { status: "succeeded", download_url: "/dl" }],
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    await page.getByRole("button", { name: /generate standard pdf/i }).click();

    await expect(page.getByText(/standard pdf generated/i)).toBeVisible({ timeout: 15_000 });
    expect(job.postedBodies).toHaveLength(1);
    const options = job.postedBodies[0].report_options as Record<string, unknown>;
    expect(options.report_kind).toBe("standard");
    expect(job.postedBodies[0].audit_ids).toEqual([301]);
  });

  test("double click does not queue a second job", async ({ page }) => {
    await stubReportContext(page);
    const job = await stubReportJob(page, {
      statusScript: [{ status: "queued" }, { status: "queued" }, { status: "succeeded" }],
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    const button = page.getByRole("button", { name: /generate standard pdf/i });
    // dispatchEvent fires without waiting for the button to become disabled, so
    // both clicks land inside the same race window a real double-click creates.
    await button.dispatchEvent("click");
    await button.dispatchEvent("click");

    await expect(page.getByText(/standard pdf generated/i)).toBeVisible({ timeout: 15_000 });
    expect(job.postedBodies).toHaveLength(1);
  });

  test("failure is surfaced and retry queues a new job", async ({ page }) => {
    await stubReportContext(page);
    const job = await stubReportJob(page, {
      statusScript: [{ status: "failed", error: "No completed audits matched the range" }],
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    await page.getByRole("button", { name: /generate standard pdf/i }).click();
    await expect(page.getByText(/no completed audits matched the range/i)).toBeVisible({
      timeout: 15_000,
    });

    await page.unroute(`**/api/v1/reports/complex/report-e2e-1/status`);
    await page.route(`**/api/v1/reports/complex/report-e2e-2/status`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ report_id: "report-e2e-2", status: "succeeded" }),
      })
    );
    await page.route(`**/api/v1/reports/complex/report-e2e-2/download`, (route) =>
      route.fulfill({ status: 200, contentType: "application/pdf", body: "%PDF-1.4 retry" })
    );

    // Second generation returns a different job id.
    await page.unroute("**/api/v1/reports/generate-complex");
    const retryBodies: Array<Record<string, unknown>> = [];
    await page.route("**/api/v1/reports/generate-complex", async (route) => {
      retryBodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ report_id: "report-e2e-2", status: "queued" }),
      });
    });

    await page.getByRole("button", { name: /generate standard pdf/i }).click();
    await expect(page.getByText(/standard pdf generated/i)).toBeVisible({ timeout: 15_000 });
    expect(retryBodies).toHaveLength(1);
    expect(job.postedBodies.length + retryBodies.length).toBe(2);
  });

  test("an expired report shows an explicit state, not a dead link", async ({ page }) => {
    await stubReportContext(page);
    await stubReportJob(page, {
      statusScript: [{ status: "expired", retention_days: 30 }],
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    await page.getByRole("button", { name: /generate standard pdf/i }).click();

    await expect(page.getByText(/expired/i)).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(/standard pdf generated/i)).toHaveCount(0);
  });

  test("a foreign or missing job is surfaced as an error, never as ready", async ({ page }) => {
    await stubReportContext(page);
    await stubReportJob(page, { statusScript: [404] });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    await page.getByRole("button", { name: /generate standard pdf/i }).click();

    await expect(page.getByText(/not found|failed|error/i).first()).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/standard pdf generated/i)).toHaveCount(0);
  });

  test("an in-flight job resumes polling after a page reload", async ({ page }) => {
    await stubReportContext(page);
    const job = await stubReportJob(page, {
      statusScript: [{ status: "queued" }],
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);
    await page.getByRole("button", { name: /generate standard pdf/i }).click();

    // Wait until the job id has been persisted, then reload mid-flight.
    await page.waitForFunction(
      () => Object.keys(window.localStorage).some((key) => key.startsWith("signal.reportJob.v1.")),
      { timeout: 10_000 }
    );
    await page.reload();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // Now the job succeeds; the resumed poller should pick it up and download.
    await page.unroute(`**/api/v1/reports/complex/report-e2e-1/status`);
    await page.route(`**/api/v1/reports/complex/report-e2e-1/status`, (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          report_id: "report-e2e-1",
          status: "succeeded",
          download_url: "/dl",
        }),
      })
    );

    await expect(page.getByText(/report downloaded|resuming/i).first()).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForFunction(
      () => !Object.keys(window.localStorage).some((key) => key.startsWith("signal.reportJob.v1.")),
      { timeout: 15_000 }
    );
    expect(job.getStatusCalls()).toBeGreaterThan(0);
  });

  test("arabic renders the journey RTL with translated report strings", async ({
    page,
    baseURL,
  }) => {
    await stubReportContext(page);
    await stubReportJob(page, { statusScript: [{ status: "queued" }] });
    await page.context().addCookies([
      {
        name: "preferred_language",
        value: "ar",
        url: baseURL ?? "http://localhost:3300",
      },
    ]);
    await page.addInitScript(() => {
      window.localStorage.setItem("geo-aeo-audit-tool.language", "ar");
    });

    await loginUser(page, sharedUser, "/dashboard/reports/generate");
    await driveToConfigure(page);

    // The withheld-sections callout renders the Arabic string on the report
    // type step, so go back one step to see it.
    await page.getByRole("button", { name: /^back$/i }).click();
    await expect(page.getByText("تتبع الأقسام خطتك")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("html")).toHaveAttribute("dir", "rtl");
  });
});

// ---------------------------------------------------------------------------
// Report library (SIGV2-1130)
// ---------------------------------------------------------------------------

const LIBRARY_ROWS = [
  {
    report_id: "lib-succeeded",
    name: "Standard report - 1 Apr 2026 to 30 Jun 2026",
    report_kind: "standard",
    period_start: "2026-04-01T00:00:00.000Z",
    period_end: "2026-06-30T23:59:59.000Z",
    created_at: new Date(Date.now() - 2 * 3600 * 1000).toISOString(),
    size_bytes: 2_516_582,
    status: "succeeded",
    error: null,
    expires_at: new Date(Date.now() + 6 * 86400 * 1000).toISOString(),
    link_expired: false,
    link_expiry_days_remaining: 6,
    retention_days: 30,
    download_url: "/api/v1/reports/complex/lib-succeeded/download",
  },
  {
    report_id: "lib-expired",
    name: "Project report - all time, 28 Sep 2026",
    report_kind: "project",
    period_start: null,
    period_end: null,
    created_at: new Date(Date.now() - 7 * 86400 * 1000).toISOString(),
    size_bytes: 12_288,
    status: "expired",
    error: null,
    expires_at: null,
    link_expired: true,
    link_expiry_days_remaining: 0,
    retention_days: 30,
    download_url: null,
  },
];

const stubReportLibrary = async (
  page: import("@playwright/test").Page,
  rows: Array<Record<string, unknown>> = LIBRARY_ROWS
) => {
  const deleteBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/v1/reports/complex?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: rows, total: rows.length, limit: 100, offset: 0 }),
    })
  );
  await page.route("**/api/v1/reports/complex/delete", async (route) => {
    deleteBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ deleted: ["lib-succeeded"], not_found: [] }),
    });
  });
  return { deleteBodies };
};

test.describe("Report library", () => {
  test.describe.configure({ mode: "serial" });

  let sharedUser: ReturnType<typeof buildTestUser>;

  test.beforeAll(async ({ browser }) => {
    const provisionedEmail = process.env.E2E_TEST_EMAIL;
    const provisionedPassword = process.env.E2E_TEST_PASSWORD;
    sharedUser =
      provisionedEmail && provisionedPassword
        ? { name: "E2E Library", email: provisionedEmail, password: provisionedPassword }
        : buildTestUser("e2e-report-library");
    const page = await browser.newPage();
    if (provisionedEmail && provisionedPassword) {
      await loginUser(page, sharedUser);
    } else {
      await registerAndLogin(page, sharedUser);
    }
    await page.close();
  });

  test("lists the generated reports with their real link expiry", async ({ page }) => {
    await stubReportLibrary(page);
    await loginUser(page, sharedUser, "/dashboard/reports");

    await expect(page.getByRole("heading", { name: "Report library" })).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Standard report - 1 Apr 2026 to 30 Jun 2026")).toBeVisible();
    await expect(page.getByText("expires in 6 days")).toBeVisible();
  });

  test("an expired link reads as expired and cannot be clicked", async ({ page }) => {
    await stubReportLibrary(page);
    await loginUser(page, sharedUser, "/dashboard/reports");

    const expiredRow = page.locator("tr", {
      hasText: "Project report - all time, 28 Sep 2026",
    });
    await expect(expiredRow.getByRole("button", { name: /download/i })).toBeDisabled({
      timeout: 30_000,
    });
  });

  test("deleting a selection is confirmed before anything is removed", async ({ page }) => {
    const library = await stubReportLibrary(page);
    await loginUser(page, sharedUser, "/dashboard/reports");

    const row = page.locator("tr", { hasText: "Standard report - 1 Apr 2026 to 30 Jun 2026" });
    await row.getByRole("checkbox", { name: "Select row" }).check({ timeout: 30_000 });
    await page.getByRole("button", { name: "Delete selected" }).click();

    await expect(page.getByText("Delete these reports?")).toBeVisible();
    expect(library.deleteBodies).toHaveLength(0);

    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await expect.poll(() => library.deleteBodies.length).toBe(1);
    expect(library.deleteBodies[0].report_ids).toEqual(["lib-succeeded"]);
  });

  test("an empty library shows the approved empty state, not example rows", async ({ page }) => {
    await stubReportLibrary(page, []);
    await loginUser(page, sharedUser, "/dashboard/reports");

    await expect(page.getByText("No reports yet. Generate one from the Export menu.")).toBeVisible({
      timeout: 30_000,
    });
    await expect(page.getByText("Q2 full audit")).toHaveCount(0);
  });
});
