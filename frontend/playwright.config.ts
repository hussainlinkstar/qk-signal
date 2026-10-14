import { defineConfig, devices } from "@playwright/test";
import type { VisualOptions } from "./e2e/visual/visual-fixtures";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
const webServerCommand = process.env.E2E_WEB_SERVER_CMD;

// Audit flows need up to 12 minutes — all other flows 90 seconds max.
// Each spec file overrides with test.setTimeout() where appropriate.
const DEFAULT_TIMEOUT_MS = 90_000;

export default defineConfig<VisualOptions>({
  testDir: "./e2e",

  // Run specs sequentially to avoid registration race conditions on shared DB
  fullyParallel: false,
  workers: 1,

  // 2 retries in CI catches transient network / animation flakiness
  retries: process.env.CI ? 2 : 0,

  reporter: [
    ["list"],
    ["html", { open: "never" }],
    ...(process.env.CI ? ([["github"]] as const) : []),
  ],

  // Default per-test timeout — audit-flows.spec.ts overrides per test
  timeout: DEFAULT_TIMEOUT_MS,

  expect: {
    // Generous assertion timeout to handle slow React re-renders
    timeout: 15_000,
    toHaveScreenshot: {
      // Near-zero tolerance (SIGV2-1045): the approved mockup capture is the
      // reference and any real pixel difference is either a defect or an
      // explicitly recorded, approved correction. One ceiling only.
      // threshold is the tightest non-zero value instead of 0: Playwright
      // compares with pixelmatch, whose per-pixel YIQ delta is
      // 0.5053*dy^2 + 0.299*di^2 + 0.1957*dq^2 and whose pass bound is
      // 35215 * threshold^2. A 1/255 rounding on all three channels gives
      // delta 0.5053, needing threshold >= 0.003788 to be ignored; a 2/255
      // change gives delta 2.0212, needing >= 0.007576. 0.004 ignores exactly
      // a one-unit rasteriser rounding and still fails anything larger.
      // Guarded by src/test/visualDiffThreshold.test.ts.
      maxDiffPixels: 0,
      threshold: 0.004,
      animations: "disabled",
      scale: "css",
      // Deliberately not caret:"hide": it injects an inline caret-color which
      // reads as a hydration mismatch. The caret is suppressed by the
      // determinism stylesheet in e2e/visual/visual-fixtures.ts instead.
      caret: "initial",
    },
  },

  use: {
    baseURL,
    // Always collect trace / video on failure for easier debugging
    trace: "retain-on-failure",
    video: "retain-on-failure",
    screenshot: "only-on-failure",
    // Consistent viewport
    viewport: { width: 1280, height: 800 },
    // Ignore HTTPS errors when running against localhost
    ignoreHTTPSErrors: true,
    // Give extra time for slow actions (fill, click)
    actionTimeout: 10_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: /.*\.visual\.spec\.ts/,
    },
    {
      name: "desktop-firefox",
      use: { ...devices["Desktop Firefox"] },
      testIgnore: /.*\.visual\.spec\.ts/,
    },
    {
      name: "mobile-chrome",
      use: { ...devices["Pixel 5"] },
      testIgnore: /.*\.visual\.spec\.ts/,
    },
    {
      name: "mobile-safari",
      use: { ...devices["iPhone 13"] },
      testIgnore: /.*\.visual\.spec\.ts/,
    },
    // Visual-regression projects (SIGV2-1045). Baselines are generated and
    // compared ONLY inside the pinned image mcr.microsoft.com/playwright:
    // v1.58.2-jammy, locally and in CI, so font rasterisation is identical in
    // both. Never record a baseline rendered on macOS.
    {
      name: "visual-1440x900-en",
      testMatch: /.*\.visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        colorScheme: "light",
        contextOptions: { reducedMotion: "reduce" },
        locale: "en",
        visualLocale: "en",
      },
    },
    {
      name: "visual-1440x1100-en",
      testMatch: /.*\.visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1100 },
        deviceScaleFactor: 1,
        colorScheme: "light",
        contextOptions: { reducedMotion: "reduce" },
        locale: "en",
        visualLocale: "en",
      },
    },
    {
      name: "visual-1440x900-ar",
      testMatch: /.*\.visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        colorScheme: "light",
        contextOptions: { reducedMotion: "reduce" },
        locale: "ar",
        visualLocale: "ar",
      },
    },
    {
      name: "visual-1440x1100-ar",
      testMatch: /.*\.visual\.spec\.ts/,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 1100 },
        deviceScaleFactor: 1,
        colorScheme: "light",
        contextOptions: { reducedMotion: "reduce" },
        locale: "ar",
        visualLocale: "ar",
      },
    },
  ],

  ...(webServerCommand
    ? {
        webServer: {
          command: webServerCommand,
          url: baseURL,
          reuseExistingServer: !process.env.CI,
          timeout: 180_000,
        },
      }
    : {}),
});
