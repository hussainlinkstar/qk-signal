import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = path.resolve(__dirname, "../..");
const globalsSource = fs.readFileSync(path.join(frontendRoot, "src/app/globals.css"), "utf8");
const themeInlineStart = globalsSource.indexOf("@theme inline");
const themeInlineBlock = globalsSource.slice(
  themeInlineStart,
  globalsSource.indexOf("\n}", themeInlineStart)
);

// Class-name prefix -> CSS variable backing the Tailwind colour.
const TOKEN_VARS: Record<string, string> = {
  background: "--background",
  foreground: "--foreground",
  primary: "--primary",
  "primary-hover": "--primary-hover",
  "primary-foreground": "--primary-foreground",
  secondary: "--secondary",
  "secondary-foreground": "--secondary-foreground",
  accent: "--accent",
  "accent-foreground": "--accent-foreground",
  success: "--success",
  warning: "--warning",
  danger: "--danger",
  info: "--info",
  ring: "--ring",
  surface: "--surface",
  "surface-subtle": "--surface-subtle",
  "surface-elevated": "--surface-elevated",
  "surface-border": "--border",
  "surface-strong": "--border-hover",
  "text-primary": "--text",
  "text-muted": "--text-muted",
  "text-soft": "--text-soft",
  brand: "--brand-primary",
  "brand-hover": "--brand-hover",
  "brand-sky": "--sky-300",
  "brand-seo": "--brand-seo",
  "brand-aeo": "--brand-aeo",
  "brand-geo": "--brand-geo",
  "chart-1": "--chart-1",
  "chart-2": "--chart-2",
  "chart-3": "--chart-3",
  "chart-4": "--chart-4",
  "chart-5": "--chart-5",
  "chart-6": "--chart-6",
};

const UTILITY_PREFIXES = [
  "bg",
  "text",
  "border",
  "ring",
  "from",
  "via",
  "to",
  "fill",
  "stroke",
  "divide",
  "outline",
  "decoration",
  "placeholder",
  "caret",
  "accent",
];

const collectSourceFiles = (dir: string): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return collectSourceFiles(full);
    }
    return /\.(tsx?|jsx?)$/.test(entry.name) &&
      !entry.name.endsWith(".test.ts") &&
      !entry.name.endsWith(".test.tsx")
      ? [full]
      : [];
  });

const tokenPattern = Object.keys(TOKEN_VARS)
  .map((token) => token.replace(/-/g, "\\-"))
  .join("|");
const utilityPattern = UTILITY_PREFIXES.join("|");
const alphaClass = new RegExp(`(?:${utilityPattern})-(${tokenPattern})/(\\d+)`, "g");

describe("Token colour alpha capability", () => {
  it("keeps every var()-backed Tailwind colour inside @theme inline", () => {
    const offenders = Object.entries(TOKEN_VARS).filter(
      ([utilityToken, cssVar]) =>
        !new RegExp(
          `--color-${utilityToken.replace(/-/g, "\\-")}: var\\(${cssVar.replace(/-/g, "\\-")},`
        ).test(themeInlineBlock)
    );
    expect(offenders).toEqual([]);
  });

  it("declares token colours as runtime-overridable var() references", () => {
    const lines = themeInlineBlock.split("\n").filter((line) => /--color-/.test(line));
    const notVarBacked = lines.filter((line) => !/var\(--[a-z0-9-]+,\s*[^)]+\)/i.test(line));
    expect(notVarBacked).toEqual([]);
    expect(lines.length).toBeGreaterThanOrEqual(Object.keys(TOKEN_VARS).length);
  });

  it("fails if source uses /N opacity on a token colour that is not alpha-capable", () => {
    const offenders: string[] = [];
    for (const file of collectSourceFiles(path.join(frontendRoot, "src"))) {
      const source = fs.readFileSync(file, "utf8");
      for (const match of source.matchAll(alphaClass)) {
        const token = match[1];
        const cssVar = TOKEN_VARS[token];
        const isCapable = themeInlineBlock.includes(`var(${cssVar},`);
        if (!isCapable) {
          offenders.push(`${path.relative(frontendRoot, file)}: ${match[0]}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
