import { createHash } from "node:crypto";
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const srcRoot = path.resolve(process.cwd(), "src");
const fontRoot = path.join(srcRoot, "app/fonts");

function sourceFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    return entry.isDirectory()
      ? sourceFiles(file)
      : /\.(?:[cm]?[jt]sx?|css|scss|html|mdx)$/.test(entry.name)
        ? [file]
        : [];
  });
}

const families = [
  { name: "inter", source: "app/layout.tsx", weights: ["400", "500", "600", "700"] },
  { name: "robotoMono", source: "app/layout.tsx", weights: ["400", "500"] },
  { name: "geistSans", source: "app/gate/page.tsx", weights: ["100 900"] },
  { name: "geistMono", source: "app/gate/page.tsx", weights: ["100 900"] },
];

describe("self-hosted font policy", () => {
  it("keeps Google font resolution and stylesheets out of all frontend sources", () => {
    const googleLoader = ["next", "font", "google"].join("/");
    const externalFont = new RegExp(
      `(?:@import|url\\(|\\bhref\\s*[:=]|\\bsrc\\s*[:=])[^;]{0,200}(?:${["fonts", "googleapis", "com"].join("\\.")}|${["fonts", "gstatic", "com"].join("\\.")})`
    );
    const violations = sourceFiles(srcRoot).flatMap((file) => {
      const source = readFileSync(file, "utf8");
      return source.includes(googleLoader) || externalFont.test(source)
        ? [path.relative(srcRoot, file)]
        : [];
    });
    expect(violations).toEqual([]);
  });

  it.each(families)("loads valid local WOFF2 files for $name at the required weights", (family) => {
    const sourcePath = path.join(srcRoot, family.source);
    const source = readFileSync(sourcePath, "utf8");
    const config = source.match(
      new RegExp(`const ${family.name} = localFont\\(\\{([\\s\\S]*?)\\n\\}\\);`)
    );
    expect(config, `${family.name} must use the local loader`).not.toBeNull();
    const options = config![1];
    const weights = Array.from(options.matchAll(/weight: "([\d ]+)"/g), (match) => match[1]);
    expect(weights).toEqual(family.weights);
    expect(options).toContain('display: "swap"');
    const files = Array.from(options.matchAll(/(?:path|src): "([^"]+\.woff2)"/g), (match) =>
      path.resolve(path.dirname(sourcePath), match[1])
    );
    expect(files.length).toBeGreaterThan(0);
    for (const file of files) {
      expect(path.dirname(file)).toBe(fontRoot);
      const bytes = readFileSync(file);
      expect(bytes.length).toBeGreaterThan(48);
      expect(bytes.subarray(0, 4).toString("ascii")).toBe("wOF2");
      expect(bytes.readUInt32BE(8)).toBe(bytes.length);
      expect(bytes.readUInt16BE(12)).toBeGreaterThan(0);
    }
  });

  it("preserves the original Unicode coverage and symbol fallbacks", () => {
    const manifest = JSON.parse(readFileSync(path.join(fontRoot, "font-sources.json"), "utf8"));
    const keys = ["inter", "robotomono", "geist", "geistmono"];
    for (const [index, family] of families.entries()) {
      const source = readFileSync(path.join(srcRoot, family.source), "utf8");
      const options = source.match(
        new RegExp(`const ${family.name} = localFont\\(\\{([\\s\\S]*?)\\n\\}\\);`)
      )![1];
      const range = options.match(/prop: "unicode-range",\s*value:\s*"([^"]+)"/);
      expect(range, `${family.name} must retain its Unicode boundary`).not.toBeNull();
      expect(range![1]).toBe(
        manifest.unicodeCoverage[keys[index]].ranges.map((r: string) => `U+${r}`).join(",")
      );
    }
    const interRanges = manifest.unicodeCoverage.inter.ranges.map((range: string) =>
      range.split("-").map((value: string) => parseInt(value, 16))
    );
    const includes = (code: number) =>
      interRanges.some(([start, end = start]: number[]) => code >= start && code <= end);
    expect(includes(0x41)).toBe(true);
    expect(includes(0x2192)).toBe(false);
    expect(includes(0x2197)).toBe(false);
  });

  it("pins every vendored font to its documented hash and license", () => {
    const manifest = JSON.parse(readFileSync(path.join(fontRoot, "font-sources.json"), "utf8")) as {
      fonts: { file: string; sha256: string; source: string; version: string; license: string }[];
    };
    expect(manifest.fonts).toHaveLength(8);
    for (const font of manifest.fonts) {
      const bytes = readFileSync(path.join(fontRoot, font.file));
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(font.sha256);
      expect(font.source).toMatch(/^https:\/\//);
      expect(font.version.length).toBeGreaterThan(0);
      expect(readFileSync(path.join(fontRoot, font.license), "utf8")).toContain(
        "SIL OPEN FONT LICENSE Version 1.1"
      );
    }
  });
});
