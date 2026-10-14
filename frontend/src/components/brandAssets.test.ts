import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// SIGV2-1087 regression guard.
//
// `public/qiko-signal-logo.svg` and `public/qiko_signal_logo_dark.svg` were
// byte-identical 1.38MB SVG wrappers around the same 1149x635 PNG. Nothing in
// lint, typecheck, the unit suite or the visual suites noticed: an SVG looks
// like a vector to every tool we run, and an oversized asset renders perfectly,
// it just costs the user a megabyte and renders nondeterministically.
//
// These assertions are the thing that notices. They are byte budgets, so they
// fail on the weight itself rather than on a filename or an import, which means
// a reintroduction cannot dodge them by using a new name.
// ---------------------------------------------------------------------------

const PUBLIC_DIR = path.resolve(process.cwd(), "public");

const RASTER_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif"]);

/** The largest any brand lockup asset may be. The two retired SVGs were 21x this. */
const BRAND_ASSET_BUDGET_BYTES = 100 * 1024;

/** The ceiling for any image under `public/`, brand asset or not. */
const PUBLIC_IMAGE_BUDGET_BYTES = 512 * 1024;

/**
 * `public/icon.svg` is still an SVG wrapper around a raster: it holds
 * `icon-512.png` verbatim and is referenced as a favicon by `app/layout.tsx`
 * and `app/manifest.ts`. It is capped here at its current size so it cannot
 * grow, and left for its own ticket rather than folded into a logo change that
 * the visual gate has to clear. Adding an entry to this list is a deliberate,
 * reviewable act; it is not a way to make a failing assertion pass.
 */
const EMBEDDED_RASTER_SVG_ALLOWLIST: Record<string, number> = {
  "icon.svg": 240 * 1024,
};

/** Every image asset the brand components reference, resolved from their source. */
const BRAND_COMPONENT_SOURCES = [
  "src/components/AppLogo.tsx",
  "src/components/signal/SignalBrandLockup.tsx",
];

function listFiles(dir: string, prefix = ""): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const absolute = path.join(dir, entry);
    const relative = prefix ? `${prefix}/${entry}` : entry;
    return statSync(absolute).isDirectory() ? listFiles(absolute, relative) : [relative];
  });
}

function readPngSize(file: string): { width: number; height: number } {
  const header = readFileSync(file).subarray(16, 24);
  return { width: header.readUInt32BE(0), height: header.readUInt32BE(4) };
}

function brandAssetPaths(): string[] {
  const found = new Set<string>();
  // Every root-relative asset path these components hold as a string literal.
  // Comments reference filenames too, but never as a quoted absolute path, so
  // a historical note cannot masquerade as a shipped asset.
  const literal = /"(\/[^"]+\.(?:png|jpg|jpeg|gif|webp|avif|svg))"/g;
  for (const source of BRAND_COMPONENT_SOURCES) {
    const text = readFileSync(path.resolve(process.cwd(), source), "utf8");
    for (const match of text.matchAll(literal)) {
      found.add(match[1]);
    }
  }
  return [...found].sort();
}

describe("brand asset weight", () => {
  const assets = brandAssetPaths();

  it("resolves the brand assets from the components rather than a hardcoded list", () => {
    // If this ever reads empty the budget assertions below would vacuously
    // pass, which is the one failure mode a guard like this must not have.
    // After SIGV2-1087 the only brand asset is the Qiko mark: AppLogo renders
    // nothing else and every wordmark surface uses SignalBrandLockup.
    expect(assets).toEqual(["/qiko-logo.png"]);
  });

  it.each(assets)("%s exists and stays under the brand asset budget", (asset) => {
    const file = path.join(PUBLIC_DIR, asset);
    const bytes = statSync(file).size;
    expect(bytes).toBeLessThanOrEqual(BRAND_ASSET_BUDGET_BYTES);
  });

  it.each(assets)("%s is a raster, never an SVG standing in for one", (asset) => {
    expect(path.extname(asset)).not.toBe(".svg");
    expect(RASTER_EXTENSIONS.has(path.extname(asset))).toBe(true);
  });

  it("keeps the Qiko mark's intrinsic size close to what the surfaces render", () => {
    // The widest surface paints the mark 80px across (the auth lockup's 32px
    // height at a 237:95 aspect). 237px leaves ~3x of DPR headroom.
    const { width, height } = readPngSize(path.join(PUBLIC_DIR, "qiko-logo.png"));
    expect(width).toBe(237);
    expect(height).toBe(95);
  });

  it("keeps the Qiko mark unoptimized so it matches SignalBrandLockup byte for byte", () => {
    const source = readFileSync(path.resolve(process.cwd(), "src/components/AppLogo.tsx"), "utf8");
    expect(source).toMatch(/^\s*unoptimized\s*$/m);
  });

  it("has deleted the retired wordmark assets from public/", () => {
    // The 1.38MB SVG wrappers and the repurposed PNG must not quietly return
    // under public/: this is the assertion that notices the file, not an
    // import of it.
    for (const retired of [
      "qiko-signal-logo.svg",
      "qiko_signal_logo_dark.svg",
      "qiko-signal-logo.png",
    ]) {
      expect(() => statSync(path.join(PUBLIC_DIR, retired))).toThrow();
    }
  });
});

describe("public image weight", () => {
  const files = listFiles(PUBLIC_DIR);
  const images = files.filter((file) => RASTER_EXTENSIONS.has(path.extname(file).toLowerCase()));
  const svgs = files.filter((file) => path.extname(file).toLowerCase() === ".svg");

  it("finds the assets it is meant to be policing", () => {
    expect(images.length).toBeGreaterThan(5);
    expect(svgs.length).toBeGreaterThan(0);
  });

  it.each(images)("%s stays under the public image budget", (image) => {
    expect(statSync(path.join(PUBLIC_DIR, image)).size).toBeLessThanOrEqual(
      PUBLIC_IMAGE_BUDGET_BYTES
    );
  });

  it.each(svgs)("%s is a real vector, not a raster in an SVG wrapper", (svg) => {
    const text = readFileSync(path.join(PUBLIC_DIR, svg), "utf8");
    const embedsRaster = /<image[^>]*base64,/i.test(text) || /xlink:href="data:image\//i.test(text);
    const allowance = EMBEDDED_RASTER_SVG_ALLOWLIST[svg];

    if (allowance === undefined) {
      expect(embedsRaster).toBe(false);
      return;
    }

    // Allowlisted: it may still embed a raster, but it may not grow.
    expect(statSync(path.join(PUBLIC_DIR, svg)).size).toBeLessThanOrEqual(allowance);
  });
});
