import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const configPath = path.resolve(process.cwd(), "playwright.config.ts");

describe("visual screenshot diff threshold", () => {
  it("ignores exactly a 1/255 rasteriser rounding and nothing larger", () => {
    const source = readFileSync(configPath, "utf8");
    const block = source.match(/toHaveScreenshot:\s*\{([\s\S]*?)\n\s*\}/);
    expect(block, "playwright.config.ts must configure toHaveScreenshot").not.toBeNull();
    const threshold = block![1].match(/threshold:\s*([\d.]+)/);
    expect(threshold, "toHaveScreenshot must set an explicit threshold").not.toBeNull();
    const value = Number(threshold![1]);
    // pixelmatch per-pixel YIQ delta: 0.5053*dy^2 + 0.299*di^2 + 0.1957*dq^2;
    // a pixel passes when delta <= 35215 * threshold^2. A 1/255 change on all
    // three channels gives delta 0.5053, needing threshold >= 0.003788; a
    // 2/255 change gives delta 2.0212, needing threshold >= 0.007576. The
    // window below admits only values that absorb the former while still
    // failing the latter.
    expect(value).toBeGreaterThanOrEqual(0.003788);
    expect(value).toBeLessThan(0.007576);
  });
});
