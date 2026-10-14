// SIGV2-1066 / SIGV2-1115: approved-design <-> built-screen comparison gate.
//
// For every approved MVP HTML page this renders the design page and the built
// route at 1440x900 and 1440x1100, English and Arabic, then emits a difference
// percentage, a diff image and a PASS/FAIL verdict per variant.
//
// Reference model (SIGV2-1066, criterion 3 of Gate 1):
//   * The approved design renders are the baseline, committed under
//     e2e/design-reference/ with manifest.json recording each source filename
//     and a SHA-256 of the source HTML. A design change is therefore a
//     visible, reviewable event (hash mismatch -> DESIGN_CHANGED).
//   * `--update-reference` re-records that set deliberately, the same way
//     `test:e2e:visual:update` re-records regression baselines.
//   * Named exclusion regions (fixture data, chart rasterisation) are masked
//     on BOTH renders before diffing; each is listed in the report with its
//     justification. They are never widened to make a screen pass.
//
// What SIGV2-1115 changed, and why:
//   1. FULL PAGE. Both sides are captured with `fullPage: true`. The old
//      harness photographed the first viewport only, so on the dashboard it
//      compared roughly 39% of the page and anything below the fold could
//      diverge unseen. Heights differ between the two documents, so the diff
//      is computed over the union canvas: pixelmatch across the overlapping
//      region, plus every pixel of the non-overlapping region counted as
//      divergent. A page that is far shorter or taller than its design IS
//      divergent, and the number now says so.
//   2. A REAL GATE. Every screen must have an entry in thresholds.json
//      (committed, so changing it is a reviewable act). A variant over its
//      screen's threshold fails, and the process exits non-zero. A screen
//      with no threshold entry fails - a missing screen is never a pass.
//      Thresholds are seeded from the CURRENT measured divergence with
//      `--write-thresholds`, so the gate starts green and ratchets downward
//      as the known gaps are closed.
//   3. NO SILENT SKIPS. `status: "not-implemented"` is now a hard failure.
//      A design page with genuinely no build target belongs in
//      EXCLUDED_DESIGNS in screens.mjs, with its reason, and nowhere else.
//
// What SIGV2-1138 changed, and why:
//   1. PER-TAB COMPARISON. A tabbed screen was photographed in its default
//      tab only, and the drilldowns additionally masked their tab panels, so
//      work inside a non-default tab was invisible to this gate in BOTH
//      directions: it could not confirm an alignment and it could not catch a
//      regression. Measured twice: the My Profile Data tab was rebuilt to the
//      approved design and the figure did not move at all (24.04 before and
//      after), and the AIO Prompts tab gained prompt creation with a
//      byte-identical figure (16.62 both times). A screen's `tabs` entries in
//      screens.mjs now each become their own comparison screen, id
//      `<screen>-tab-<tab>`, with its own reference renders, its own
//      exclusions and its own budget. The tab is activated on BOTH sides
//      before the capture; the states of one screen share a single page load
//      per viewport and locale, so a tab costs a settle and a screenshot
//      rather than another navigation.
//   2. SHARED-ASSET HASHING. The manifest recorded a SHA-256 of each screen's
//      own HTML and nothing else, so an edit to signal.css (or app.js, which
//      injects the sidebar into every approved page) would have invalidated
//      every reference PNG in the set with no hash anywhere to notice.
//      SHARED_DESIGN_ASSETS are hashed alongside each screen's source and
//      recorded with every reference, and a drift is a DESIGN_CHANGED
//      failure like any other design change.
//
// Modes:
//   (default)            compare and gate; exit 1 on any failure
//   --reference-only     CI mode: do not render the approved design at all,
//                        use the committed reference PNGs plus the design-side
//                        exclusion geometry recorded in manifest.json. The
//                        approved mockups live outside this repo and are not
//                        available to a CI checkout.
//   --update-reference   re-render and re-record the reference set (local,
//                        deliberate; needs the mockups mounted at /design)
//   --write-thresholds   re-seed thresholds.json from this run's measurements
//   --screens=a,b        restrict the run to specific comparison screen ids.
//                        Naming a base screen selects it and all of its
//                        per-tab screens; naming `<screen>-tab-<tab>` selects
//                        that one tab.
//   --shard=i/n          run only shard i of n (CI matrix). Both flags are
//                        filters and the shard is applied AFTER --screens:
//                        the screen-restricted set is what gets partitioned,
//                        so sharding a restricted run is well defined. A
//                        malformed value exits 1; it never falls back to an
//                        unsharded run, because that would run the whole
//                        catalogue in every matrix leg. assertPartition()
//                        runs on every sharded invocation so no screen can
//                        be silently dropped from the aggregate coverage.
//
// Environment (provided by e2e/visual/compare-to-design.sh):
//   APP_URL     built Next app     (default http://localhost:3123)
//   STUB_URL    stub backend       (default http://localhost:8000)
//   DESIGN_URL  static design host (default http://localhost:3100)
//   DESIGN_DIR  mounted mockup dir (default /design)

import { chromium } from "playwright";
import { PNG } from "pngjs";
import pixelmatch from "pixelmatch";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  EXCLUDED_DESIGNS,
  VIEWPORTS,
  LOCALES,
  SHARED_DESIGN_ASSETS,
  COMPARISON_SCREEN_IDS,
  screenGroups,
} from "./screens.mjs";
import { assertPartition, parseShardArg, shardGroups } from "./shard.mjs";
import { hashDesignAssets } from "./design-assets.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const REFERENCE_DIR = join(HERE, "..", "design-reference");
const REPORT_DIR = join(HERE, "report");
const MANIFEST_PATH = join(REFERENCE_DIR, "manifest.json");
const THRESHOLDS_PATH = join(HERE, "thresholds.json");

const APP_URL = process.env.APP_URL || "http://localhost:3123";
const STUB_URL = process.env.STUB_URL || "http://localhost:8000";
const DESIGN_URL = process.env.DESIGN_URL || "http://localhost:3100";
const DESIGN_DIR = process.env.DESIGN_DIR || "/design";
const UPDATE_REFERENCE = process.argv.includes("--update-reference");
const WRITE_THRESHOLDS = process.argv.includes("--write-thresholds");
const REFERENCE_ONLY = process.argv.includes("--reference-only") && !UPDATE_REFERENCE;
const ONLY = (process.argv.find((a) => a.startsWith("--screens=")) || "")
  .replace("--screens=", "")
  .split(",")
  .filter(Boolean);
let SHARD;
try {
  SHARD = parseShardArg(process.argv);
} catch (err) {
  console.error(err.message);
  process.exit(1);
}

// Recording runs measure, they do not judge. Every other run gates.
const GATING = !UPDATE_REFERENCE && !WRITE_THRESHOLDS;

const READY_TIMEOUT_MS = Number(process.env.DESIGN_COMPARE_READY_TIMEOUT_MS || 60000);
// SIGV2-1138: budget for activating one tab and seeing its panel appear. A
// click that lands and a panel that never shows is a real defect, so this is
// short enough to report rather than hang the run.
const TAB_TIMEOUT_MS = Number(process.env.DESIGN_COMPARE_TAB_TIMEOUT_MS || 20000);

// Quiescence budget: the page must hold the same layout signature for
// SETTLE_STABLE_SAMPLES consecutive samples before it is photographed.
const SETTLE_INTERVAL_MS = 250;
const SETTLE_STABLE_SAMPLES = 8;
const SETTLE_MAX_SAMPLES = 120;

// Determinism mirrors e2e/visual/visual-fixtures.ts: fixed clock, seeded
// Math.random, no animations/caret/scrollbars, persisted cookie-consent so
// the banner never renders (the approved captures show none).
const FIXED_NOW = "2026-09-29T12:00:00.000Z";
const SEED = 1045;
const CONSENT_STORAGE_KEY = "geo-aeo-audit-tool.cookie-consent";
const CONSENT_COOKIE_NAME = "geo_aeo_cookie_consent";
const CONSENT_COOKIE_VALUE = "v1.p1a1m1";
const FAKE_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  Buffer.from(
    JSON.stringify({ sub: "1", exp: Math.floor(Date.now() / 1000) + 86400, type: "access" })
  ).toString("base64url") +
  ".x";

const DETERMINISM_CSS = `
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
    scroll-behavior: auto !important;
    caret-color: transparent !important;
  }
  ::-webkit-scrollbar { width: 0 !important; height: 0 !important; }
  * { scrollbar-width: none !important; }
`;

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");
const vpName = (vp) => `${vp.width}x${vp.height}`;

// Both generated JSON files are committed, so they have to satisfy
// `npm run format:check` in frontend-ci. Running them through Prettier here
// means re-recording never leaves the tree unformatted; JSON.stringify's
// output does not match Prettier's for nested arrays.
async function writeJson(path, value) {
  const raw = JSON.stringify(value, null, 2) + "\n";
  try {
    const prettier = await import("prettier");
    const options = (await prettier.resolveConfig(path)) ?? {};
    writeFileSync(path, await prettier.format(raw, { ...options, filepath: path }));
  } catch {
    writeFileSync(path, raw);
    console.warn(`prettier unavailable; wrote ${path} unformatted, run npm run format`);
  }
}

// Wait until the page stops changing before photographing it.
//
// `networkidle` is not enough: on several screens an async payload lands after
// it and the document then grows (audit-start, fixes). A full-page capture
// taken mid-flight is a different picture every run, which showed up as CI and
// a local run disagreeing by 4 to 12 percentage points on exactly those two
// screens. The signature covers height and rendered text length, so a payload
// that swaps content without changing height is caught too.
async function settle(page, label) {
  let last = null;
  let stable = 0;
  for (let i = 0; i < SETTLE_MAX_SAMPLES && stable < SETTLE_STABLE_SAMPLES; i++) {
    const signature = await page.evaluate(
      () => `${document.documentElement.scrollHeight}:${(document.body?.innerText ?? "").length}`
    );
    stable = signature === last ? stable + 1 : 0;
    last = signature;
    await page.waitForTimeout(SETTLE_INTERVAL_MS);
  }
  if (stable < SETTLE_STABLE_SAMPLES) {
    console.warn(`${label} never stopped changing within the settle budget; capture may vary`);
  }
}

function loadManifest() {
  if (!existsSync(MANIFEST_PATH)) return { screens: {} };
  return JSON.parse(readFileSync(MANIFEST_PATH, "utf8"));
}

function loadThresholds() {
  if (!existsSync(THRESHOLDS_PATH)) return { screens: {} };
  const parsed = JSON.parse(readFileSync(THRESHOLDS_PATH, "utf8"));
  return { screens: parsed.screens ?? {} };
}

// SIGV2-1138: hash the files every approved page shares.
//
// The manifest recorded a SHA-256 of each screen's own HTML and nothing else,
// so an edit to signal.css (or to app.js, which injects the sidebar into every
// page) would have invalidated every reference PNG in the set with no hash
// anywhere to notice. Returns null in --reference-only mode, where the
// mockups are not mounted and no design-side hash can be computed at all.
function sharedAssetHashes(additionalAssets = []) {
  if (REFERENCE_ONLY) return null;
  return hashDesignAssets(DESIGN_DIR, [...SHARED_DESIGN_ASSETS, ...additionalAssets]);
}

// Compare the shared-asset hashes recorded with a reference against the ones
// on disk now. Returns a human detail string when the reference can no longer
// be trusted, or null when it still can.
function sharedAssetDrift(recorded, current) {
  if (!current) return null;
  if (!recorded || Object.keys(recorded).length === 0) {
    return (
      `this reference was recorded before the shared design assets ` +
      `(${SHARED_DESIGN_ASSETS.join(", ")}) were hashed, so nothing can prove it was ` +
      "rendered against the current stylesheet. Re-run test:design-compare:update."
    );
  }
  const drifted = [];
  for (const [name, hash] of Object.entries(current)) {
    if (recorded[name] !== hash) {
      drifted.push(
        `${name} (recorded ${String(recorded[name]).slice(0, 12)}, now ${String(hash).slice(0, 12)})`
      );
    }
  }
  if (!drifted.length) return null;
  return (
    `shared design assets changed since the reference was recorded: ${drifted.join("; ")}. ` +
    "Every reference render depends on them, so re-run test:design-compare:update and " +
    "review the new references."
  );
}

// SIGV2-1138: activate one tab on the approved page.
//
// The mockup's own mechanism (app.js `wireTabs`): a click on
// `#tabs button[data-tab=X]` moves the `on` class onto that button and onto
// `.panelw[data-panel=X]`, which signal.css shows with `display:block`.
// Waiting for the panel to be visible rather than sleeping means a catalogue
// entry naming a tab that does not exist fails loudly instead of quietly
// photographing the default tab again, which is the exact failure this
// ticket exists to remove.
async function activateDesignTab(page, tab) {
  await page.click(`#tabs button[data-tab="${tab}"]`, { timeout: TAB_TIMEOUT_MS });
  await page.waitForSelector(`.panelw[data-panel="${tab}"].on`, {
    state: "visible",
    timeout: TAB_TIMEOUT_MS,
  });
}

// SIGV2-1138: the built counterpart. Every tabbed screen in the app uses
// components/signal/SignalTabs, which renders `#signal-tab-<id>` for the
// control and `#signal-tabpanel-<id>` for the panel (either absent until
// selected, or present with `hidden`), so one selector pair covers all of
// them. Tab ids differ between the two sides on some screens (workspace
// settings), hence `designTab` / `buildTab` in the catalogue.
async function activateBuiltTab(page, tab) {
  await page.click(`[id="signal-tab-${tab}"]`, { timeout: TAB_TIMEOUT_MS });
  await page.waitForSelector(`[id="signal-tabpanel-${tab}"]`, {
    state: "visible",
    timeout: TAB_TIMEOUT_MS,
  });
}

// Capture one state (default tab, or a named tab) of an already-loaded page.
// A failure is confined to its own state: the page stays usable, so one
// broken tab does not cost the run every other tab of the same screen.
async function captureStates(page, states, side, viewport, locale) {
  const { label, activate, tabKey, exclusionKey } = side;
  const captures = {};
  for (const state of states) {
    try {
      if (state.tab) await activate(page, state.tab[tabKey]);
      // Tab activation can move the scroll position (SignalTabs calls
      // scrollIntoView on the newly selected control). A full-page capture is
      // the document, not the viewport, but sticky chrome renders differently
      // when scrolled, so both sides start every capture at the top.
      await page.evaluate(() => window.scrollTo(0, 0));
      await settle(page, `${label} ${state.id} ${vpName(viewport)}-${locale}`);
      captures[state.id] = {
        png: await page.screenshot({ fullPage: true }),
        boxes: await collectBoxes(page, state.exclusions, exclusionKey),
      };
    } catch (err) {
      captures[state.id] = { error: err.message.split("\n")[0] };
    }
  }
  return captures;
}

async function renderDesign(browser, screen, viewport, locale, states) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  // The mockup app.js applies `qiko-lang` on load (applyLang -> dir + I18N_AR).
  await page.addInitScript((lang) => {
    try {
      window.localStorage.setItem("qiko-lang", lang);
    } catch {
      /* storage may be unavailable; page defaults to en */
    }
  }, locale);
  await page.addInitScript((css) => {
    const apply = () => {
      const style = document.createElement("style");
      style.textContent = css;
      (document.head ?? document.documentElement).appendChild(style);
    };
    if (document.head) apply();
    else document.addEventListener("DOMContentLoaded", apply, { once: true });
  }, DETERMINISM_CSS);
  await page.goto(`${DESIGN_URL}/${encodeURIComponent(screen.designFile)}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  // app.js injects the sidebar/nav after DOMContentLoaded.
  await page
    .waitForSelector("aside.side .nav a, .app .side .nav a", { timeout: 15000 })
    .catch(() => {});
  if (screen.designUnlockBodyClass) {
    await page.evaluate((cls) => document.body.classList.remove(cls), screen.designUnlockBodyClass);
  }
  const dir = await page.evaluate(() => document.documentElement.dir);
  // SIGV2-1115: full page, not the first viewport.
  // SIGV2-1138: one capture per state, all from this single page load.
  const captures = await captureStates(
    page,
    states,
    {
      label: "design",
      activate: activateDesignTab,
      tabKey: "design",
      exclusionKey: "designSelector",
    },
    viewport,
    locale
  );
  await context.close();
  return { captures, dir };
}

async function renderBuilt(browser, screen, viewport, locale, states) {
  // reducedMotion reaches JS-driven animation (framer-motion springs like
  // ScoreGauge) that the injected `animation: none` stylesheet cannot settle.
  const context = await browser.newContext({
    viewport,
    ignoreHTTPSErrors: true,
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  await page.context().addCookies(
    [
      { name: "auth_token", value: FAKE_JWT },
      { name: "auth_refresh_token", value: FAKE_JWT },
      { name: "preferred_language", value: locale },
      { name: CONSENT_COOKIE_NAME, value: CONSENT_COOKIE_VALUE },
    ].map((c) => ({ ...c, url: APP_URL }))
  );
  const consentRecord = {
    version: 1,
    source: "accept-all",
    consentedAt: FIXED_NOW,
    lastUpdatedAt: FIXED_NOW,
    preferences: { necessary: true, preferences: true, analytics: true, marketing: true },
  };
  await page.addInitScript(
    ([key, value, ws, css, seed]) => {
      window.localStorage.setItem(key, value);
      if (ws) window.localStorage.setItem("active_workspace_id", ws);
      const apply = () => {
        const style = document.createElement("style");
        style.textContent = css;
        (document.head ?? document.documentElement).appendChild(style);
      };
      if (document.head) apply();
      else document.addEventListener("DOMContentLoaded", apply, { once: true });
      let state = seed >>> 0;
      Math.random = () => {
        state |= 0;
        state = (state + 0x6d2b79f5) | 0;
        let t = Math.imul(state ^ (state >>> 15), 1 | state);
        t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
        return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
      };
    },
    [
      CONSENT_STORAGE_KEY,
      JSON.stringify(consentRecord),
      screen.workspaceId ?? null,
      DETERMINISM_CSS,
      SEED,
    ]
  );
  try {
    await page.clock.install({ time: new Date(FIXED_NOW) });
    await page.clock.setFixedTime(new Date(FIXED_NOW));
  } catch {
    // Clock API unavailable in this context; fixture timestamps come from the
    // stub payload anyway.
  }
  if (screen.resetStub) {
    await page.request.post(`${STUB_URL}/api/v1/__reset`).catch(() => {});
  }
  await page.goto(`${APP_URL}${screen.route}`, { waitUntil: "domcontentloaded" });
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  if (screen.readySelector) {
    // A readySelector that never appears means the route did not render. That
    // is a failure of this screen, reported loudly, not a skip and not a
    // crash that takes the whole run down with it.
    try {
      await page.waitForSelector(screen.readySelector, { timeout: READY_TIMEOUT_MS });
    } catch (err) {
      await context.close();
      throw err;
    }
  }
  const dir = await page.evaluate(() => document.documentElement.dir);
  // SIGV2-1115: full page, not the first viewport.
  // SIGV2-1138: one capture per state, all from this single page load.
  const captures = await captureStates(
    page,
    states,
    {
      label: "built",
      activate: activateBuiltTab,
      tabKey: "build",
      exclusionKey: "buildSelector",
    },
    viewport,
    locale
  );
  await context.close();
  return { captures, dir };
}

async function collectBoxes(page, exclusions, key) {
  const boxes = [];
  for (const ex of exclusions ?? []) {
    const sel = ex[key];
    if (!sel) continue;
    const rects = await page.evaluate((s) => {
      const out = [];
      for (const el of document.querySelectorAll(s)) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
          // Document coordinates: a full-page screenshot is the document, not
          // the viewport, so a viewport-relative rect would land in the wrong
          // place on any page that is scrolled.
          out.push({
            x: r.x + window.scrollX,
            y: r.y + window.scrollY,
            w: r.width,
            h: r.height,
          });
        }
      }
      return out;
    }, sel);
    // Snap to the integer grid here, once. The reference set persists these
    // rectangles as integers so --reference-only can mask the design side
    // without the mockups; if the live path masked with sub-pixel floats
    // instead, the two modes would disagree by a tenth of a percent or so and
    // a gate calibrated in one would be wrong in the other. Measured: up to
    // 0.11pp of drift before this snap, which is more than the thresholds'
    // rounding headroom.
    boxes.push({
      name: ex.name,
      selector: sel,
      rects: rects.map((r) => ({
        x: Math.round(r.x),
        y: Math.round(r.y),
        w: Math.round(r.w),
        h: Math.round(r.h),
      })),
    });
  }
  return boxes;
}

// Exclusion geometry is persisted with the reference set so --reference-only
// runs (CI, where the approved mockups are not available) mask the design side
// exactly as the recording run did.
const serialiseBoxes = (boxes) =>
  Object.fromEntries(boxes.map((b) => [b.name, b.rects.map((r) => [r.x, r.y, r.w, r.h])]));

const deserialiseBoxes = (raw) =>
  Object.entries(raw ?? {}).map(([name, rects]) => ({
    name,
    rects: rects.map(([x, y, w, h]) => ({ x, y, w, h })),
  }));

// Paint each excluded region the same constant colour on BOTH renders before
// diffing, so legitimately different content inside them contributes zero.
function mask(png, boxes) {
  for (const b of boxes) {
    for (const r of b.rects) {
      const x0 = Math.max(0, Math.floor(r.x));
      const y0 = Math.max(0, Math.floor(r.y));
      const x1 = Math.min(png.width, Math.ceil(r.x + r.w));
      const y1 = Math.min(png.height, Math.ceil(r.y + r.h));
      for (let y = y0; y < y1; y++) {
        for (let x = x0; x < x1; x++) {
          const i = (y * png.width + x) * 4;
          png.data[i] = 255;
          png.data[i + 1] = 0;
          png.data[i + 2] = 255;
          png.data[i + 3] = 255;
        }
      }
    }
  }
}

function cropTo(src, width, height) {
  if (src.width === width && src.height === height) return src;
  const out = new PNG({ width, height });
  PNG.bitblt(src, out, 0, 0, width, height, 0, 0);
  return out;
}

// Full-page renders differ in height. Rather than pad one side with a colour
// and hope the colour never occurs (it would silently under-count), the two
// images are diffed over their overlap and every pixel outside the overlap is
// counted as divergent outright. The denominator is the union canvas.
function diffFullPage(designPng, builtPng) {
  const overlapW = Math.min(designPng.width, builtPng.width);
  const overlapH = Math.min(designPng.height, builtPng.height);
  const unionW = Math.max(designPng.width, builtPng.width);
  const unionH = Math.max(designPng.height, builtPng.height);
  const unionArea = unionW * unionH;
  const overlapArea = overlapW * overlapH;

  const diff = new PNG({ width: unionW, height: unionH });
  // Mark the whole canvas as "outside the overlap" first (opaque orange), then
  // let pixelmatch overwrite the overlapping region.
  for (let i = 0; i < diff.data.length; i += 4) {
    diff.data[i] = 255;
    diff.data[i + 1] = 140;
    diff.data[i + 2] = 0;
    diff.data[i + 3] = 255;
  }

  let overlapDiffPixels = 0;
  if (overlapArea > 0) {
    const a = cropTo(designPng, overlapW, overlapH);
    const b = cropTo(builtPng, overlapW, overlapH);
    const overlapDiff = new PNG({ width: overlapW, height: overlapH });
    overlapDiffPixels = pixelmatch(a.data, b.data, overlapDiff.data, overlapW, overlapH, {
      threshold: 0,
      includeAA: false,
    });
    PNG.bitblt(overlapDiff, diff, 0, 0, overlapW, overlapH, 0, 0);
  }

  const nonOverlapPixels = unionArea - overlapArea;
  const diffPixels = overlapDiffPixels + nonOverlapPixels;
  return {
    diff,
    overlapDiffPixels,
    nonOverlapPixels,
    diffPixels,
    unionW,
    unionH,
    diffPercent: Number(((diffPixels / unionArea) * 100).toFixed(2)),
  };
}

const only = (id) => ONLY.length === 0 || ONLY.includes(id);
const roundUpToTenth = (n) => Math.ceil(n * 10) / 10;

async function main() {
  mkdirSync(REFERENCE_DIR, { recursive: true });
  mkdirSync(REPORT_DIR, { recursive: true });

  const manifest = loadManifest();
  manifest.viewports = VIEWPORTS.map(vpName);
  manifest.locales = LOCALES;
  manifest.screens = manifest.screens ?? {};
  const thresholds = loadThresholds();

  // One browser per screen, not one for the whole run. Full-page captures of
  // the taller screens grow Chromium's memory enough that later screens in a
  // single long-lived browser start timing out on their ready selector and
  // report a RENDER_FAILED they do not deserve. Observed on the first
  // full-page run: billing, fixes, settings and workspace-settings all failed
  // in sequence and all four passed on their own.
  let browser = null;
  const report = {
    generatedBy: "e2e/design-comparison/compare.mjs",
    mode: UPDATE_REFERENCE
      ? "update-reference"
      : WRITE_THRESHOLDS
        ? "write-thresholds"
        : REFERENCE_ONLY
          ? "reference-only"
          : "compare",
    gating: GATING,
    appUrl: APP_URL,
    designUrl: REFERENCE_ONLY ? null : DESIGN_URL,
    shard: SHARD,
    screens: [],
  };

  // SIGV2-1219: a filter token that matches nothing is a typo, not a pass.
  // `--screens=dashbaord` used to select zero screens, compare zero variants
  // and exit 0 with "0/0 screens pass", which reads exactly like success.
  const knownIds = new Set(COMPARISON_SCREEN_IDS);
  const knownBaseIds = new Set(screenGroups().map((g) => g.screen.id));
  const unknown = ONLY.filter((id) => !knownIds.has(id) && !knownBaseIds.has(id));
  if (unknown.length) {
    console.error(
      `--screens names ${unknown.length === 1 ? "a screen that does" : "screens that do"} ` +
        `not exist: ${unknown.join(", ")}. Nothing would have been compared.`
    );
    process.exit(1);
  }

  // Shard over the --screens-restricted set, not the raw catalogue: both are
  // filters, so the run's group set is whatever --screens leaves behind.
  const selected = screenGroups().filter((group) =>
    group.states.some((s) => only(s.id) || only(group.screen.id))
  );
  let groups = selected;
  if (SHARD) {
    assertPartition(selected, SHARD.count);
    groups = shardGroups(selected, SHARD);
    const countStates = (gs) =>
      gs.reduce((n, g) => n + g.states.filter((s) => only(s.id) || only(g.screen.id)).length, 0);
    console.log(
      `shard ${SHARD.index}/${SHARD.count}: ` +
        `${groups.length} of ${selected.length} screen groups, ` +
        `${countStates(groups)} of ${countStates(selected)} comparison states`
    );
  }

  // SIGV2-1138: the shared stylesheet and script every approved page pulls in.
  // Recorded with every reference and checked on every local run.
  const sharedHashes = sharedAssetHashes();
  report.sharedDesignAssets = sharedHashes;

  for (const group of groups) {
    const screen = group.screen;
    const screenAssetHashes = sharedAssetHashes(screen.designAssets ?? []);
    // A filter token selects either one comparison screen or, when it names
    // the base screen, that screen and all of its tab screens.
    const states = group.states.filter((s) => only(s.id) || only(screen.id));
    if (!states.length) continue;

    const entries = new Map(
      states.map((state) => [
        state.id,
        {
          id: state.id,
          designFile: screen.designFile,
          status: screen.status,
          ticket: screen.ticket,
          route: screen.route,
          tab: state.tab ? { ...state.tab } : null,
          variants: [],
          failures: [],
        },
      ])
    );
    const pushEntries = () => {
      for (const state of states) report.screens.push(entries.get(state.id));
    };

    // SIGV2-1115: a catalogued screen with no build target is a failure of
    // the run. The only sanctioned way to not compare an approved page is
    // EXCLUDED_DESIGNS in screens.mjs, which is printed in the report.
    if (screen.status !== "built") {
      for (const entry of entries.values()) {
        entry.result = "FAIL";
        entry.failures.push({
          reason: "NOT_IMPLEMENTED",
          detail:
            `${screen.ticket}: catalogued as not-implemented (${screen.route}). ` +
            "Either build it, or move the design page to EXCLUDED_DESIGNS with a reason.",
        });
      }
      pushEntries();
      continue;
    }

    const sourcePath = join(DESIGN_DIR, screen.designFile);
    const sourceHash =
      !REFERENCE_ONLY && existsSync(sourcePath) ? sha256(readFileSync(sourcePath)) : null;
    const missingShared = Object.entries(sharedHashes ?? {})
      .filter(([, hash]) => hash === null)
      .map(([name]) => name);

    for (const state of states) {
      const entry = entries.get(state.id);
      const threshold = thresholds.screens[state.id];
      entry.thresholdPercent = threshold?.maxDiffPercent ?? null;
      if (!WRITE_THRESHOLDS && (!threshold || typeof threshold.maxDiffPercent !== "number")) {
        entry.failures.push({
          reason: "NO_THRESHOLD",
          detail:
            `No entry for "${state.id}" in e2e/design-comparison/thresholds.json. ` +
            "A screen without a committed threshold cannot pass.",
        });
      }
      entry.sourceHash = sourceHash;
      if (!REFERENCE_ONLY && sourceHash === null) {
        entry.failures.push({
          reason: "MISSING_DESIGN_SOURCE",
          detail: `Approved page not found at ${sourcePath}.`,
        });
      }
      if (missingShared.length) {
        entry.failures.push({
          reason: "MISSING_DESIGN_SOURCE",
          detail: `Shared design asset(s) not found under ${DESIGN_DIR}: ${missingShared.join(", ")}.`,
        });
      }
    }

    for (const viewport of VIEWPORTS) {
      for (const locale of LOCALES) {
        // One browser per screen, per viewport, per locale. Full-page captures
        // of the taller screens grow Chromium's memory enough that a
        // long-lived browser starts timing out on later ready selectors and
        // reports a RENDER_FAILED nothing deserves (observed on the first
        // full-page run: billing, fixes, settings and workspace-settings
        // failed in sequence and all four passed on their own). Per-tab
        // capture multiplies the captures per page load, so the browser is
        // recycled more often than it was, not less.
        if (browser) await browser.close();
        browser = await chromium.launch();

        let design = null;
        if (!REFERENCE_ONLY) {
          design = await renderDesign(browser, screen, viewport, locale, states);
        }

        let built = null;
        let builtError = null;
        try {
          built = await renderBuilt(browser, screen, viewport, locale, states);
        } catch (err) {
          builtError = err.message.split("\n")[0];
        }

        for (const state of states) {
          const entry = entries.get(state.id);
          const refName = `${state.id}-${vpName(viewport)}-${locale}.png`;
          const refPath = join(REFERENCE_DIR, refName);
          const variant = {
            viewport: vpName(viewport),
            locale,
            reference: refName,
            failures: [],
          };
          if (state.tab) variant.tab = state.tab.id;
          const declaredExclusions = (state.exclusions ?? []).map((e) => e.name).sort();

          const designCapture = design?.captures[state.id] ?? null;
          if (design) variant.designDir = design.dir;
          if (designCapture?.error) {
            // The approved page could not be put into this state at all -
            // almost always a catalogue entry naming a tab the mockup does
            // not have. Never a pass.
            variant.failures.push({
              reason: "DESIGN_STATE_FAILED",
              detail: `${screen.designFile} could not be captured in state "${state.id}": ${designCapture.error}`,
            });
          }

          if (UPDATE_REFERENCE && designCapture?.png) {
            const png = PNG.sync.read(designCapture.png);
            writeFileSync(refPath, designCapture.png);
            manifest.screens[state.id] = manifest.screens[state.id] ?? {};
            manifest.screens[state.id][refName] = {
              sourceFile: screen.designFile,
              sourceSha256: sourceHash,
              // SIGV2-1138: the shared stylesheet and script every approved
              // page depends on, recorded so a change to either invalidates
              // this reference loudly instead of silently.
              sharedSha256: screenAssetHashes ?? {},
              ...(state.tab ? { tab: state.tab.id, designTab: state.tab.design } : {}),
              pngSha256: sha256(designCapture.png),
              width: png.width,
              height: png.height,
              designDir: design.dir,
              // Persisted so --reference-only can mask the design side without
              // the approved mockups being present.
              exclusionRects: serialiseBoxes(designCapture.boxes),
            };
          }

          const current = manifest.screens[state.id]?.[refName];
          let referencePng = null;
          let designBoxes = [];
          const sharedDrift = sharedAssetDrift(current?.sharedSha256, screenAssetHashes);

          if (UPDATE_REFERENCE && designCapture?.png) {
            referencePng = PNG.sync.read(designCapture.png);
            designBoxes = designCapture.boxes;
          } else if (UPDATE_REFERENCE) {
            // Capture failed above; already recorded as DESIGN_STATE_FAILED.
          } else if (!current || !existsSync(refPath)) {
            variant.failures.push({
              reason: "MISSING_REFERENCE",
              detail: `No committed reference for ${refName}; run test:design-compare:update.`,
            });
          } else if (!REFERENCE_ONLY && current.sourceSha256 !== sourceHash) {
            variant.failures.push({
              reason: "DESIGN_CHANGED",
              detail:
                `${screen.designFile} has changed since the reference was recorded ` +
                `(recorded ${current.sourceSha256?.slice(0, 12)}, now ${sourceHash?.slice(0, 12)}). ` +
                "Re-run test:design-compare:update and review the new references.",
            });
          } else if (sharedDrift) {
            variant.failures.push({ reason: "DESIGN_CHANGED", detail: sharedDrift });
          } else {
            const bytes = readFileSync(refPath);
            if (current.pngSha256 && sha256(bytes) !== current.pngSha256) {
              variant.failures.push({
                reason: "REFERENCE_TAMPERED",
                detail: `${refName} does not match the SHA-256 recorded in manifest.json.`,
              });
            }
            const recordedExclusions = Object.keys(current.exclusionRects ?? {}).sort();
            if (recordedExclusions.join("|") !== declaredExclusions.join("|")) {
              variant.failures.push({
                reason: "EXCLUSIONS_CHANGED",
                detail:
                  `Exclusions in screens.mjs (${declaredExclusions.join(", ") || "none"}) do not ` +
                  `match those recorded with the reference (${recordedExclusions.join(", ") || "none"}). ` +
                  "Re-run test:design-compare:update.",
              });
            }
            if (variant.failures.length === 0) {
              referencePng = PNG.sync.read(bytes);
              designBoxes = REFERENCE_ONLY
                ? deserialiseBoxes(current.exclusionRects)
                : designCapture.boxes;
              variant.designDir = variant.designDir ?? current.designDir;
            }
          }

          if (!referencePng) {
            entry.variants.push(variant);
            continue;
          }

          const builtCapture = built?.captures[state.id] ?? null;
          if (builtError || !builtCapture || builtCapture.error) {
            variant.failures.push({
              reason: "RENDER_FAILED",
              detail:
                `${screen.route} did not render in state "${state.id}": ` +
                `${builtError ?? builtCapture?.error ?? "no capture produced"}`,
            });
            entry.variants.push(variant);
            continue;
          }

          variant.builtDir = built.dir;
          if (variant.designDir && built.dir !== variant.designDir) {
            variant.directionMismatch = `design=${variant.designDir} built=${built.dir}`;
          }
          writeFileSync(
            join(REPORT_DIR, `${state.id}-${vpName(viewport)}-${locale}-built.png`),
            builtCapture.png
          );

          const builtPng = PNG.sync.read(builtCapture.png);
          mask(referencePng, designBoxes);
          mask(builtPng, builtCapture.boxes);

          variant.designSize = `${referencePng.width}x${referencePng.height}`;
          variant.builtSize = `${builtPng.width}x${builtPng.height}`;
          variant.heightDelta = builtPng.height - referencePng.height;

          const result = diffFullPage(referencePng, builtPng);
          variant.diffPixels = result.diffPixels;
          variant.overlapDiffPixels = result.overlapDiffPixels;
          variant.nonOverlapPixels = result.nonOverlapPixels;
          variant.unionSize = `${result.unionW}x${result.unionH}`;
          variant.diffPercent = result.diffPercent;
          variant.diffImage = `report/${state.id}-${vpName(viewport)}-${locale}-diff.png`;
          writeFileSync(
            join(REPORT_DIR, `${state.id}-${vpName(viewport)}-${locale}-diff.png`),
            PNG.sync.write(result.diff)
          );
          variant.exclusionsApplied = (state.exclusions ?? []).map((e) => ({
            name: e.name,
            reason: e.reason,
            designRects: designBoxes.find((b) => b.name === e.name)?.rects.length ?? 0,
            builtRects: builtCapture.boxes.find((b) => b.name === e.name)?.rects.length ?? 0,
          }));

          if (typeof entry.thresholdPercent === "number") {
            if (variant.diffPercent > entry.thresholdPercent) {
              variant.failures.push({
                reason: "OVER_THRESHOLD",
                detail: `${variant.diffPercent}% exceeds the ${entry.thresholdPercent}% threshold for ${state.id}.`,
              });
            }
          }
          variant.verdict = variant.failures.length === 0 ? "PASS" : "FAIL";
          entry.variants.push(variant);
        }
      }
    }

    for (const state of states) {
      const entry = entries.get(state.id);
      entry.measured = Object.fromEntries(
        entry.variants
          .filter((v) => typeof v.diffPercent === "number")
          .map((v) => [`${v.viewport}-${v.locale}`, v.diffPercent])
      );
      entry.maxDiffPercent = Object.values(entry.measured).reduce((a, b) => Math.max(a, b), 0);
      const variantFailures = entry.variants.flatMap((v) =>
        v.failures.map((f) => ({ ...f, variant: `${v.viewport}-${v.locale}` }))
      );
      entry.failures.push(...variantFailures);
      entry.result = entry.failures.length === 0 ? "PASS" : "FAIL";
    }
    pushEntries();
  }

  // Pruning must not run on a sharded update: this process sees only its own
  // shard's groups, so every other shard's references would look stale.
  if (UPDATE_REFERENCE && ONLY.length === 0 && !SHARD) {
    // Prune references for screens that have left the catalogue, so the
    // committed set cannot drift into holding pictures of things nobody
    // compares any more.
    const live = new Set(COMPARISON_SCREEN_IDS);
    for (const id of Object.keys(manifest.screens)) {
      if (live.has(id)) continue;
      for (const refName of Object.keys(manifest.screens[id])) {
        const stale = join(REFERENCE_DIR, refName);
        if (existsSync(stale)) rmSync(stale);
      }
      delete manifest.screens[id];
      console.log(`pruned reference set for removed screen "${id}"`);
    }
  }
  if (UPDATE_REFERENCE) {
    await writeJson(MANIFEST_PATH, manifest);
  }

  if (WRITE_THRESHOLDS) {
    await writeThresholds(report, thresholds);
  }

  report.summary = {
    screens: report.screens.length,
    passed: report.screens.filter((s) => s.result === "PASS").length,
    failed: report.screens.filter((s) => s.result === "FAIL").length,
  };

  writeFileSync(join(REPORT_DIR, "report.json"), JSON.stringify(report, null, 2) + "\n");
  writeFileSync(join(REPORT_DIR, "report.md"), renderMarkdown(report, thresholds));
  console.log(renderConsole(report));
  console.log(`report written to ${join(REPORT_DIR, "report.md")}`);
  if (browser) await browser.close();

  // SIGV2-1219: "0/0 screens pass" is not a pass. Whatever filtered the run
  // down to nothing (a shard count larger than the catalogue, a screens list
  // that selects no state), a run that measured nothing cannot be the
  // evidence a budget is ratcheted from.
  if (report.summary.screens === 0) {
    console.error(
      "no screen was compared: this run measured nothing and proves nothing. " +
        "Check --screens / --shard."
    );
    process.exitCode = 1;
    return;
  }

  if (GATING && report.summary.failed > 0) {
    process.exitCode = 1;
  }
}

// Seeds thresholds.json from this run's measurements. Each screen's threshold
// is its CURRENT worst variant, rounded up to the next 0.1 percentage point
// (the precision the report itself quotes). The gate therefore starts green
// and can only be ratcheted downward as screens are brought closer to the
// approved design. Raising a threshold to make a failing screen pass defeats
// the entire point of the file and is not an acceptable fix.
async function writeThresholds(report, previous) {
  const now = new Date().toISOString().slice(0, 10);
  const screens = { ...previous.screens };
  for (const s of report.screens) {
    if (s.result === "FAIL" && s.failures.some((f) => f.reason !== "OVER_THRESHOLD")) {
      // Do not seed a threshold from a run that could not measure the screen.
      continue;
    }
    if (!Object.keys(s.measured ?? {}).length) continue;
    // `ciMeasured` is hand-recorded from a CI artifact for the few screens
    // whose built render differs between a local container and a GitHub
    // runner, and it is PRESERVED across re-seeding. Without that, a local
    // re-record would quietly drop the budget below what CI actually measures
    // and the gate would start failing for a reason nobody could reproduce.
    const previous = screens[s.id];
    const ciMeasured = previous?.ciMeasured;
    const ciMax = ciMeasured ? Math.max(...Object.values(ciMeasured)) : 0;
    screens[s.id] = {
      maxDiffPercent: roundUpToTenth(Math.max(s.maxDiffPercent, ciMax)),
      measuredMaxPercent: s.maxDiffPercent,
      measured: s.measured,
      ...(ciMeasured
        ? {
            ciMeasured,
            ciMeasuredNote: previous.ciMeasuredNote,
            ciMeasuredOn: previous.ciMeasuredOn,
          }
        : {}),
      measuredOn: now,
      ticket: s.ticket,
    };
  }
  const ordered = {};
  for (const id of COMPARISON_SCREEN_IDS) if (screens[id]) ordered[id] = screens[id];
  await writeJson(THRESHOLDS_PATH, {
    $schema: "SIGV2-1115 design-vs-build divergence budget",
    $policy: [
      "maxDiffPercent is a ceiling, not a target. It was seeded from the measured",
      "divergence at the time the screen was first gated, rounded up to the next 0.1",
      "percentage point, so the gate starts green and ratchets.",
      "Lowering a value is ordinary progress and needs no ceremony.",
      "Raising a value to make a failing screen pass is not an acceptable fix: the",
      "failure means the build moved away from the approved design, so fix the build",
      "or get the design change approved and re-record the reference set.",
      "measured/measuredMaxPercent record what was actually observed when the value",
      "was set, so a later reviewer can see the headroom at a glance.",
      "ciMeasured, where present, is the same measurement taken on a GitHub runner for",
      "a screen whose built render differs between environments. The budget is the max",
      "of the two, both are kept, and ciMeasuredNote says what is unexplained.",
    ],
    screens: ordered,
  });
}

function renderConsole(report) {
  const lines = [""];
  const pad = (s, n) => String(s).padEnd(n);
  // SIGV2-1138: the per-tab screen ids (`<screen>-tab-<tab>`) are longer than
  // the base ones, so the column is wide enough not to run the verdict off
  // the end of the line.
  const idWidth = report.screens.reduce((w, s) => Math.max(w, s.id.length), 22) + 1;
  lines.push(
    `${pad("SCREEN", idWidth)} ${pad("VARIANT", 18)} ${pad("DIFF%", 8)} ${pad("LIMIT%", 8)} VERDICT`
  );
  lines.push("-".repeat(idWidth + 46));
  for (const s of report.screens) {
    if (!s.variants.length) {
      lines.push(
        `${pad(s.id, idWidth)} ${pad("-", 18)} ${pad("-", 8)} ${pad(s.thresholdPercent ?? "-", 8)} ${s.result}`
      );
      continue;
    }
    for (const v of s.variants) {
      lines.push(
        `${pad(s.id, idWidth)} ${pad(`${v.viewport}-${v.locale}`, 18)} ` +
          `${pad(v.diffPercent ?? "-", 8)} ${pad(s.thresholdPercent ?? "-", 8)} ${v.verdict ?? "FAIL"}`
      );
    }
  }
  lines.push("-".repeat(idWidth + 46));
  const failed = report.screens.filter((s) => s.result === "FAIL");
  for (const s of failed) {
    for (const f of s.failures) {
      lines.push(`FAIL ${s.id}${f.variant ? ` [${f.variant}]` : ""}: ${f.reason} - ${f.detail}`);
    }
  }
  lines.push(
    `${report.summary.passed}/${report.summary.screens} screens pass` +
      (report.gating ? "" : " (recording run, not gating)")
  );
  return lines.join("\n");
}

function renderMarkdown(report, thresholds) {
  const lines = [
    "# Design-vs-build comparison (SIGV2-1066, gated by SIGV2-1115)",
    "",
    `Mode: \`${report.mode}\`. Gating: **${report.gating ? "yes" : "no (recording run)"}**.`,
    ...(report.shard ? [`Shard: \`${report.shard.index}/${report.shard.count}\`.`] : []),
    "",
    "Each variant compares the committed approved-design render (e2e/design-reference/)",
    "against the built route rendered on the stub backend. Both sides are captured",
    "full-page; pixelmatch runs at threshold=0 over the overlapping region and every",
    "pixel outside the overlap counts as divergent, over the union canvas.",
    "",
    "Screens whose id ends `-tab-<tab>` are per-tab comparisons (SIGV2-1138): the same",
    "tab is activated on BOTH sides before the capture, so content inside a non-default",
    "tab is compared rather than masked behind whichever tab each side opens on.",
    "",
    `**${report.summary.passed}/${report.summary.screens} screens pass.**`,
    "",
    "| Screen | Viewport | Locale | Diff % | Limit % | Verdict | Design px | Built px | Diff px | Diff image |",
    "|---|---|---|---|---|---|---|---|---|---|",
  ];
  for (const s of report.screens) {
    const limit = s.thresholdPercent ?? "-";
    if (!s.variants.length) {
      lines.push(`| ${s.id} | - | - | - | ${limit} | **${s.result}** | - | - | - | - |`);
      continue;
    }
    for (const v of s.variants) {
      lines.push(
        `| ${s.id} | ${v.viewport} | ${v.locale} | ${v.diffPercent ?? "-"}% | ${limit}% | ` +
          `${v.verdict === "PASS" ? "PASS" : "**FAIL**"} | ${v.designSize ?? "-"} | ` +
          `${v.builtSize ?? "-"} | ${v.diffPixels ?? "-"} | ${v.diffImage ?? "-"} |`
      );
    }
  }

  const failed = report.screens.filter((s) => s.result === "FAIL");
  lines.push("", "## Failures", "");
  if (!failed.length) lines.push("None.");
  for (const s of failed) {
    for (const f of s.failures) {
      lines.push(`- **${s.id}**${f.variant ? ` (${f.variant})` : ""}: \`${f.reason}\` ${f.detail}`);
    }
  }

  lines.push("", "## Thresholds in force", "");
  lines.push("| Screen | Limit % | Measured when set | Set on |");
  lines.push("|---|---|---|---|");
  for (const s of report.screens) {
    const t = thresholds.screens[s.id];
    if (!t) {
      lines.push(`| ${s.id} | **none** | - | - |`);
      continue;
    }
    lines.push(
      `| ${s.id} | ${t.maxDiffPercent}% | ${t.measuredMaxPercent ?? "-"}% | ${t.measuredOn ?? "-"} |`
    );
  }

  // SIGV2-1138: say, in the report itself, which tab each per-tab screen
  // photographs and what it carries, so a reader of the table never has to
  // guess whether a figure covers a panel or only the frame around it.
  const tabScreens = report.screens.filter((s) => s.tab);
  if (tabScreens.length) {
    lines.push("", "## Per-tab screens", "");
    lines.push("| Screen | Design tab | Built tab | Max diff % | Limit % | What it captures |");
    lines.push("|---|---|---|---|---|---|");
    for (const s of tabScreens) {
      lines.push(
        `| ${s.id} | ${s.tab.design} | ${s.tab.build} | ${s.maxDiffPercent ?? "-"}% | ` +
          `${s.thresholdPercent ?? "none"} | ${s.tab.captures ?? "-"} |`
      );
    }
  }

  lines.push("", "## Exclusions applied", "");
  const seen = new Set();
  let anyExclusion = false;
  for (const s of report.screens) {
    for (const v of s.variants ?? []) {
      for (const e of v.exclusionsApplied ?? []) {
        const key = `${s.id}:${e.name}`;
        if (seen.has(key)) continue;
        seen.add(key);
        anyExclusion = true;
        lines.push(
          `- **${s.id} / ${e.name}** (${e.designRects} design region(s), ${e.builtRects} built region(s)): ${e.reason}`
        );
      }
    }
  }
  if (!anyExclusion) lines.push("None.");

  lines.push("", "## Deliberately excluded design pages", "");
  for (const e of EXCLUDED_DESIGNS) {
    lines.push(`- ${e.designFile}: ${e.reason}`);
  }
  lines.push("");
  return lines.join("\n");
}

export { renderDesign, serialiseBoxes, sharedAssetDrift, sharedAssetHashes };

// SIGV2-1219: realpath on both sides. `resolve()` keeps symlinks while the
// ESM loader resolves them, so a checkout reached through a symlinked path
// failed this comparison, main() never ran, and node exited 0 having done
// nothing - another way for this gate to pass without checking anything.
const realpath = (p) => {
  try {
    return realpathSync(p);
  } catch {
    return resolve(p);
  }
};
const entryPath = process.argv[1] ? realpath(resolve(process.argv[1])) : null;
if (entryPath && entryPath === realpath(fileURLToPath(import.meta.url))) {
  main().catch((err) => {
    console.error(err);
    process.exit(1);
  });
}
