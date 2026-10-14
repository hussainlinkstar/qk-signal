import { expect, test, type BrowserContext, type Locator, type Page } from "@playwright/test";

import { buildTestUser, registerAndLogin } from "./helpers";

const MOBILE_WIDTHS = [320, 375, 390, 412] as const;
const RESTORATION_WIDTH = 768;
const LOCAL_BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const LOCAL_HOSTNAMES = new Set(["localhost", "127.0.0.1", "::1"]);

type RouteId =
  | "workspace-overview"
  | "project-overview"
  | "aio"
  | "seo"
  | "competitors"
  | "automations"
  | "project-settings"
  | "workspace-settings"
  | "profile"
  | "billing"
  | "developer"
  | "connections";

type MobileRoute = {
  id: RouteId;
  path: (projectId: string) => string;
  ready: (page: Page) => Locator;
};

const ROUTES: MobileRoute[] = [
  {
    id: "workspace-overview",
    path: () => "/dashboard",
    ready: (page) => page.getByRole("heading", { name: "Workspace Overview", exact: true }),
  },
  {
    id: "project-overview",
    path: (projectId) => `/dashboard/projects/${projectId}`,
    ready: (page) => page.getByRole("heading", { name: "Dashboard", exact: true }),
  },
  {
    id: "aio",
    path: (projectId) => `/dashboard/projects/${projectId}/aeo`,
    ready: (page) => page.getByRole("heading", { name: /shown, and trusted, in AI answers/i }),
  },
  {
    id: "seo",
    path: (projectId) => `/dashboard/projects/${projectId}/seo`,
    ready: (page) => page.getByRole("heading", { name: /ranking in traditional search/i }),
  },
  {
    id: "competitors",
    path: (projectId) => `/dashboard/projects/${projectId}/competitive`,
    ready: (page) => page.getByRole("heading", { name: /Benchmark .* against your rivals/i }),
  },
  {
    id: "automations",
    path: (projectId) => `/dashboard/projects/${projectId}/automations`,
    ready: (page) => page.getByRole("heading", { name: "Automations", exact: true }),
  },
  {
    id: "project-settings",
    path: (projectId) => `/dashboard/projects/${projectId}/settings`,
    ready: (page) => page.getByRole("heading", { name: "Settings", exact: true }),
  },
  {
    id: "workspace-settings",
    path: () => "/dashboard/settings",
    ready: (page) => page.getByRole("heading", { name: "Workspace Settings", exact: true }),
  },
  {
    id: "profile",
    path: () => "/dashboard/account-settings",
    ready: (page) => page.getByRole("heading", { name: "My Profile", exact: true }),
  },
  {
    id: "billing",
    path: () => "/dashboard/billing",
    ready: (page) => page.getByRole("heading", { name: "Billing" }),
  },
  {
    id: "developer",
    path: () => "/dashboard/developer",
    ready: (page) => page.getByRole("heading", { name: /Developer Hub/i }),
  },
  {
    id: "connections",
    path: () => "/dashboard/connections",
    ready: (page) => page.getByRole("heading", { name: /Workspace Connections/i }),
  },
];

type OverflowMetrics = {
  viewportWidth: number;
  documentScrollWidth: number;
  bodyScrollWidth: number;
  overflowPx: number;
  offenders: Array<{
    selector: string;
    left: number;
    right: number;
    width: number;
    scrollWidth: number;
    clientWidth: number;
  }>;
};

function assertLocalBaseURL(baseURL: string): void {
  const parsed = new URL(baseURL);
  const hostname = parsed.hostname.replace(/^\[|\]$/g, "");
  if (!LOCAL_HOSTNAMES.has(hostname)) {
    throw new Error(
      `Refusing mobile reflow registration and project mutation on non-local host: ${hostname}`
    );
  }
}

/** Reusable MOBILE-R10 document-level horizontal overflow assertion. */
async function expectNoDocumentOverflow(page: Page, context: string): Promise<void> {
  const metrics = await page.evaluate<OverflowMetrics>(() => {
    const root = document.documentElement;
    const viewportWidth = root.clientWidth;
    const documentScrollWidth = root.scrollWidth;
    const bodyScrollWidth = document.body?.scrollWidth ?? 0;

    const selectorFor = (element: Element): string => {
      const htmlElement = element as HTMLElement;
      if (htmlElement.id) return `#${htmlElement.id}`;
      const classes = Array.from(htmlElement.classList).slice(0, 3).join(".");
      return `${element.tagName.toLowerCase()}${classes ? `.${classes}` : ""}`;
    };

    const offenders = Array.from(document.body?.querySelectorAll("*") ?? [])
      .map((element) => {
        const htmlElement = element as HTMLElement;
        const rect = htmlElement.getBoundingClientRect();
        return {
          selector: selectorFor(element),
          left: Math.round(rect.left * 10) / 10,
          right: Math.round(rect.right * 10) / 10,
          width: Math.round(rect.width * 10) / 10,
          scrollWidth: htmlElement.scrollWidth,
          clientWidth: htmlElement.clientWidth,
        };
      })
      .filter(
        (entry) =>
          entry.right > viewportWidth + 1 ||
          entry.left < -1 ||
          entry.scrollWidth > entry.clientWidth + 1
      )
      .sort((a, b) => Math.max(b.right - viewportWidth, 0) - Math.max(a.right - viewportWidth, 0))
      .slice(0, 8);

    return {
      viewportWidth,
      documentScrollWidth,
      bodyScrollWidth,
      overflowPx: Math.max(documentScrollWidth, bodyScrollWidth) - viewportWidth,
      offenders,
    };
  });

  expect(
    metrics.overflowPx,
    `${context} has document-level horizontal overflow:\n${JSON.stringify(metrics, null, 2)}`
  ).toBeLessThanOrEqual(1);
}

async function expectExactVisibleCount(
  items: Locator,
  expectedCount: number,
  context: string
): Promise<void> {
  await expect(items, `${context}: exact rendered element count`).toHaveCount(expectedCount);
  for (let index = 0; index < expectedCount; index += 1) {
    await expect(items.nth(index), `${context}: item ${index + 1} should be visible`).toBeVisible();
  }
}

async function expectStacked(
  items: Locator,
  expectedCount: number,
  context: string
): Promise<void> {
  await expectExactVisibleCount(items, expectedCount, context);

  for (let index = 1; index < expectedCount; index += 1) {
    const previous = await items.nth(index - 1).boundingBox();
    const current = await items.nth(index).boundingBox();
    expect(previous, `${context}: item ${index} should have a box`).not.toBeNull();
    expect(current, `${context}: item ${index + 1} should have a box`).not.toBeNull();
    expect(
      current!.y,
      `${context}: item ${index + 1} should stack below item ${index}`
    ).toBeGreaterThanOrEqual(previous!.y + previous!.height - 1);
  }
}

async function expectInline(items: Locator, expectedCount: number, context: string): Promise<void> {
  await expectExactVisibleCount(items, expectedCount, context);

  const first = await items.first().boundingBox();
  expect(first, `${context}: first item should have a box`).not.toBeNull();
  for (let index = 1; index < expectedCount; index += 1) {
    const current = await items.nth(index).boundingBox();
    expect(current, `${context}: item ${index + 1} should have a box`).not.toBeNull();
    expect(
      Math.abs(current!.y - first!.y),
      `${context}: item ${index + 1} should restore to the first row`
    ).toBeLessThanOrEqual(1);
    expect(current!.x, `${context}: item ${index + 1} should follow item ${index}`).toBeGreaterThan(
      first!.x
    );
  }
}

async function expectTwoColumnGrid(
  items: Locator,
  expectedCount: number,
  context: string
): Promise<void> {
  await expectExactVisibleCount(items, expectedCount, context);

  for (let index = 0; index < expectedCount; index += 2) {
    const left = await items.nth(index).boundingBox();
    const right = await items.nth(index + 1).boundingBox();
    expect(left, `${context}: left item ${index + 1} should have a box`).not.toBeNull();
    expect(right, `${context}: right item ${index + 2} should have a box`).not.toBeNull();
    expect(Math.abs(right!.y - left!.y), `${context}: pair should share a row`).toBeLessThanOrEqual(
      1
    );
    expect(right!.x, `${context}: pair should restore to two columns`).toBeGreaterThan(
      left!.x + left!.width - 1
    );
  }
}

async function expectSelectedTabContained(
  page: Page,
  expectedTabCount: number,
  selectedName: string,
  context: string
): Promise<void> {
  const tablist = page.getByRole("tablist");
  await expectExactVisibleCount(tablist, 1, `${context} local tab scroller`);
  await expectExactVisibleCount(tablist.getByRole("tab"), expectedTabCount, `${context} tabs`);

  const overflowX = await tablist.evaluate((element) => getComputedStyle(element).overflowX);
  expect(
    ["auto", "scroll"],
    `${context} tabs should own horizontal overflow instead of widening the document`
  ).toContain(overflowX);

  const requestedTab = tablist.getByRole("tab", { name: selectedName, exact: true });
  await expectExactVisibleCount(requestedTab, 1, `${context} requested tab`);
  await requestedTab.click();

  const selectedTab = tablist.locator('[role="tab"][aria-selected="true"]');
  await expectExactVisibleCount(selectedTab, 1, `${context} selected tab`);
  await expect(selectedTab).toHaveText(selectedName);

  const tablistBox = await tablist.boundingBox();
  const selectedBox = await selectedTab.boundingBox();
  expect(tablistBox, `${context} tablist should have a box`).not.toBeNull();
  expect(selectedBox, `${context} selected tab should have a box`).not.toBeNull();
  expect(selectedBox!.x).toBeGreaterThanOrEqual(tablistBox!.x - 1);
  expect(selectedBox!.x + selectedBox!.width).toBeLessThanOrEqual(
    tablistBox!.x + tablistBox!.width + 1
  );
}

async function expectLabelledLocalScroller(
  scroller: Locator,
  contentSelector: "pre" | "table",
  context: string
): Promise<void> {
  await expectExactVisibleCount(scroller, 1, `${context} labelled local scroller`);
  await expect(scroller).toHaveAttribute("aria-label", context);
  await expectExactVisibleCount(scroller.locator(contentSelector), 1, `${context} content`);
  const overflowX = await scroller.evaluate((element) => getComputedStyle(element).overflowX);
  expect(["auto", "scroll"], `${context} should own horizontal overflow`).toContain(overflowX);
}

async function expectProfileFormGeometry(page: Page, restored: boolean): Promise<void> {
  const grids = page.locator('[role="tabpanel"] .wgrid2, [role="tabpanel"] .wgrid3');
  const expectedFieldCounts = [3, 2, 2, 3, 2, 3];
  await expectExactVisibleCount(
    grids,
    expectedFieldCounts.length,
    `${restored ? "RESTORE" : "MOBILE-R5"} profile form grids`
  );
  for (let index = 0; index < expectedFieldCounts.length; index += 1) {
    const fields = grids.nth(index).locator(":scope > .wfield");
    if (restored) {
      await expectInline(
        fields,
        expectedFieldCounts[index],
        `RESTORE profile form grid ${index + 1}`
      );
    } else {
      await expectStacked(
        fields,
        expectedFieldCounts[index],
        `MOBILE-R5 profile form grid ${index + 1}`
      );
    }
  }

  await expectSelectedTabContained(page, 5, restored ? "Security" : "Data", "Account");
  if (!restored) {
    await expectSelectedTabContained(page, 5, "Security", "Account");
  }
  const securityGrid = page.locator('[role="tabpanel"] .wgrid3');
  if (restored) {
    await expectInline(
      securityGrid.locator(":scope > .wfield"),
      3,
      "RESTORE Security password form grid"
    );
  } else {
    await expectStacked(
      securityGrid.locator(":scope > .wfield"),
      3,
      "MOBILE-R5 Security password form grid"
    );
  }
}

async function expectBillingPlansGeometry(page: Page, restored: boolean): Promise<void> {
  await expectSelectedTabContained(page, 5, "Plans", "Billing");
  await expect(page.getByRole("heading", { name: "Available Plans", exact: true })).toBeVisible();

  const monthly = page.getByRole("button", { name: "Monthly", exact: true });
  const annual = page.getByRole("button", { name: "Annual", exact: true });
  await expectExactVisibleCount(monthly, 1, "Billing monthly interval action");
  await expectExactVisibleCount(annual, 1, "Billing annual interval action");
  await monthly.click();
  await expect(monthly).toHaveAttribute("aria-pressed", "true");
  await expect(annual).toHaveAttribute("aria-pressed", "false");
  await annual.click();
  await expect(monthly).toHaveAttribute("aria-pressed", "false");
  await expect(annual).toHaveAttribute("aria-pressed", "true");
  await expectInline(
    monthly.locator("xpath=..").getByRole("button"),
    2,
    `${restored ? "RESTORE" : "MOBILE-R6"} BillingIntervalToggle actions`
  );

  const planCards = page.locator('[role="tabpanel"] [id^="plan-plan_"]');
  if (restored) {
    await expectTwoColumnGrid(planCards, 4, "RESTORE Billing plan cards");
  } else {
    await expectStacked(planCards, 4, "MOBILE-R6 Billing plan cards");
  }
}

async function expectRouteReflow(page: Page, route: MobileRoute): Promise<void> {
  if (route.id === "workspace-overview") {
    await expectExactVisibleCount(
      page.locator(".wso .pgrid > .pcard"),
      1,
      "workspace project card"
    );
  }

  if (route.id === "project-overview") {
    await expectStacked(page.locator(".ov .scores > .spanel"), 2, "MOBILE-R1 project score cards");
  }

  if (route.id === "aio") {
    await expectStacked(
      page.locator(".detail .hero > .gwrap, .detail .hero > .hmeta, .detail .hero > .gap"),
      3,
      "MOBILE-R2 AIO hero gauge, copy, and target"
    );
  }

  if (route.id === "seo") {
    const title = page.getByRole("heading", { name: /ranking in traditional search/i });
    await expectExactVisibleCount(title, 1, "MOBILE-R2 SEO hero title");
    const hero = title.locator("xpath=../..");
    await expectStacked(
      hero.locator(":scope > div"),
      3,
      "MOBILE-R2 SEO hero gauge, copy, and target"
    );
  }

  if (route.id === "competitors") {
    const root = page.locator("main.sg > div");
    await expectExactVisibleCount(root, 1, "MOBILE-R3 competitor page root");
    await expect(root).not.toHaveClass(/(?:^|\s)comp(?:\s|$)/);
  }

  if (route.id === "automations") {
    const dialog = page.getByRole("dialog", { name: "Automate the follow-up work" });
    await expectExactVisibleCount(dialog, 1, "MOBILE-R4 Starter upgrade dialog");

    const viewport = page.viewportSize();
    const dialogBox = await dialog.boundingBox();
    expect(viewport, "MOBILE-R4 viewport should be available").not.toBeNull();
    expect(dialogBox, "MOBILE-R4 upgrade dialog should have a box").not.toBeNull();
    expect(dialogBox!.x).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.y).toBeGreaterThanOrEqual(0);
    expect(dialogBox!.x + dialogBox!.width).toBeLessThanOrEqual(viewport!.width);
    expect(dialogBox!.y + dialogBox!.height).toBeLessThanOrEqual(viewport!.height);

    const closeButton = dialog.getByRole("button", { name: /close/i });
    await expectExactVisibleCount(closeButton, 1, "MOBILE-R4 Starter dialog close button");
    const closeBox = await closeButton.boundingBox();
    expect(closeBox, "MOBILE-R4 close button should have a box").not.toBeNull();
    expect(closeBox!.x).toBeGreaterThanOrEqual(dialogBox!.x);
    expect(closeBox!.y).toBeGreaterThanOrEqual(dialogBox!.y);
    expect(closeBox!.x + closeBox!.width).toBeLessThanOrEqual(dialogBox!.x + dialogBox!.width);
    expect(closeBox!.y + closeBox!.height).toBeLessThanOrEqual(dialogBox!.y + dialogBox!.height);

    await expectNoDocumentOverflow(page, "MOBILE-R4 Starter upgrade dialog open");
    await closeButton.click();
    await expect(dialog, "MOBILE-R4 Starter upgrade dialog should close").toHaveCount(0);
    await expectNoDocumentOverflow(page, "MOBILE-R4 Starter upgrade dialog closed");
  }

  if (route.id === "project-settings") {
    await expectExactVisibleCount(
      page.getByRole("tablist").getByRole("tab"),
      2,
      "project settings tabs"
    );
  }

  if (route.id === "workspace-settings") {
    await expectExactVisibleCount(
      page.getByRole("tablist").getByRole("tab"),
      5,
      "workspace settings tabs"
    );
  }

  if (route.id === "profile") {
    await expectProfileFormGeometry(page, false);
  }

  if (route.id === "billing") {
    await expectBillingPlansGeometry(page, false);
    await expectSelectedTabContained(page, 5, "Comparison", "Billing");
  }

  if (route.id === "developer") {
    await expectStacked(page.locator(".fstat > .fc"), 3, "MOBILE-R7 developer metrics");
    await expectSelectedTabContained(page, 3, "Quick Start", "Developer");
    await expectLabelledLocalScroller(
      page.locator('[aria-label="Starter API request"]'),
      "pre",
      "Starter API request"
    );
    await expectSelectedTabContained(page, 3, "API Reference", "Developer");
    await expectLabelledLocalScroller(
      page.locator('[aria-label="Key API endpoints"]'),
      "table",
      "Key API endpoints"
    );
  }

  if (route.id === "connections") {
    await expectSelectedTabContained(page, 4, "Reporting", "Connections");
  }
}

async function expectRouteRestoration(page: Page, route: MobileRoute): Promise<void> {
  if (route.id === "project-overview") {
    await expectInline(page.locator(".ov .scores > .spanel"), 2, "RESTORE project score cards");
  }

  if (route.id === "aio") {
    await expectInline(
      page.locator(".detail .hero > .gwrap, .detail .hero > .hmeta, .detail .hero > .gap"),
      3,
      "RESTORE AIO hero gauge, copy, and target"
    );
  }

  if (route.id === "seo") {
    const title = page.getByRole("heading", { name: /ranking in traditional search/i });
    const hero = title.locator("xpath=../..");
    await expectInline(hero.locator(":scope > div"), 3, "RESTORE SEO hero gauge, copy, and target");
  }

  if (route.id === "profile") {
    await expectProfileFormGeometry(page, true);
  }

  if (route.id === "billing") {
    await expectBillingPlansGeometry(page, true);
  }

  if (route.id === "developer") {
    await expectInline(page.locator(".fstat > .fc"), 3, "RESTORE developer metrics");
  }
}

test.describe("Signal mobile reflow RED matrix", () => {
  let fixtureStorageState: Awaited<ReturnType<BrowserContext["storageState"]>>;
  let projectId: string;

  test.beforeAll(async ({ browser }) => {
    assertLocalBaseURL(LOCAL_BASE_URL);

    const setupContext = await browser.newContext({ baseURL: LOCAL_BASE_URL });
    try {
      const setupPage = await setupContext.newPage();
      const user = buildTestUser("e2e-mobile-reflow");
      await registerAndLogin(setupPage, user);

      const response = await setupPage.request.post("/api/workspaces/current/projects", {
        data: {
          name: "Mobile Reflow Fixture",
          domain_url: "https://mobile-reflow.example",
          target_country: "US",
          language: "en",
        },
      });
      expect(response, "Local fixture project creation should succeed").toBeOK();
      const project = (await response.json()) as { id?: unknown };
      expect(typeof project.id).toBe("number");
      projectId = String(project.id);
      fixtureStorageState = await setupContext.storageState();
    } finally {
      await setupContext.close();
    }
  });

  for (const width of MOBILE_WIDTHS) {
    for (const route of ROUTES) {
      test(`${route.id} reflows without document overflow at ${width}px`, async ({ browser }) => {
        const context = await browser.newContext({
          baseURL: LOCAL_BASE_URL,
          storageState: fixtureStorageState,
        });
        try {
          const page = await context.newPage();
          await page.setViewportSize({ width, height: 900 });
          await page.goto(route.path(projectId));
          await expect(route.ready(page), `${route.id} route readiness`).toHaveCount(1);
          await expect(route.ready(page), `${route.id} route readiness`).toBeVisible();

          await expectRouteReflow(page, route);
          await expectNoDocumentOverflow(page, `${route.id} at ${width}px`);
        } finally {
          await context.close();
        }
      });
    }
  }

  for (const route of ROUTES) {
    test(`${route.id} restores responsive layout at ${RESTORATION_WIDTH}px`, async ({
      browser,
    }) => {
      const context = await browser.newContext({
        baseURL: LOCAL_BASE_URL,
        storageState: fixtureStorageState,
      });
      try {
        const page = await context.newPage();
        await page.setViewportSize({ width: RESTORATION_WIDTH, height: 900 });
        await page.goto(route.path(projectId));
        await expect(route.ready(page), `${route.id} restoration readiness`).toHaveCount(1);
        await expect(route.ready(page), `${route.id} restoration readiness`).toBeVisible();

        await expectRouteRestoration(page, route);
        await expectNoDocumentOverflow(page, `${route.id} at ${RESTORATION_WIDTH}px`);
      } finally {
        await context.close();
      }
    });
  }
});
