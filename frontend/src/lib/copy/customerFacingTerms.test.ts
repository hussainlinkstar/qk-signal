import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const frontendRoot = path.resolve(__dirname, "../../..");

/* Customer-facing copy must not contain a bare "AEO" or "GEO": the settled
   naming is "AI answers" (aeo) and "AI visibility" (geo), with "SEO and AIO"
   for the whole offering. Identifiers, payload literals, keys and comments
   are exempt; this scans rendered strings, JSX text and i18n values. */

const ACRONYM = /\b(?:AEO|GEO)\b/;

// Payload literals that legitimately keep the acronym: engine values, type
// unions, comparisons and option values. An acronym is allowed only when the
// line carrying it also carries one of these identifier markers.
const IDENTIFIER_CONTEXT =
  /includes\(|=== |!== |engines\b|Array<|as const|\bvalue:|\bid:|\bkey:|\btype\b|interface\b|\bimport\b|\bexport\b|semantic_role|engine ===|penaltyEngineMap|\brawEngines\b/;

// Markers that make a quoted string a display string even when the acronym is
// its whole content (e.g. { label: "AEO" } renders "AEO" to the user).
const DISPLAY_CONTEXT =
  /\blabel:|\btitle:|\balt:|\bname:|\bdescription\b|\bplaceholder\b|\baria-|\bteaser\b|\baccent\b|\bsubtitle\b|\bcaption\b|\bsectionName\b|\bheading\b|\bsummary\b/;

const stripComments = (source: string) =>
  source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "")
    .replace(/^\s*\/\/.*$/gm, "");

const findViolations = (file: string): string[] => {
  const source = stripComments(fs.readFileSync(path.join(frontendRoot, file), "utf8"));
  const violations: string[] = [];
  source.split("\n").forEach((line, index) => {
    if (!ACRONYM.test(line)) return;
    for (const match of line.matchAll(/(["'`])([^"'`]*\b(?:AEO|GEO)\b[^"'`]*)\1/g)) {
      const literal = match[2];
      const isBareAcronym = /^(?:AEO|GEO|AEO\+GEO|AEO\/GEO)$/.test(literal.trim());
      if (isBareAcronym && IDENTIFIER_CONTEXT.test(line) && !DISPLAY_CONTEXT.test(line)) {
        continue;
      }
      violations.push(`${file}:${index + 1} ${literal}`);
    }
    const withoutStrings = line.replace(/(["'`])(?:(?!\1).)*\1/g, '""');
    if (ACRONYM.test(withoutStrings) && !IDENTIFIER_CONTEXT.test(line)) {
      violations.push(`${file}:${index + 1} ${withoutStrings.trim()}`);
    }
  });
  return violations;
};

const collectSources = (dir: string): string[] => {
  const base = path.join(frontendRoot, dir);
  const files: string[] = [];
  for (const entry of fs.readdirSync(base, { withFileTypes: true })) {
    const rel = `${dir}/${entry.name}`;
    if (entry.isDirectory()) {
      if (["__tests__", "fixtures", "node_modules"].includes(entry.name)) continue;
      files.push(...collectSources(rel));
      continue;
    }
    if (/\.(tsx|ts)$/.test(entry.name) && !/\.(test|spec|stories)\.(tsx|ts)$/.test(entry.name)) {
      files.push(rel);
    }
  }
  return files;
};

// Approved-mockup copy exceptions: the Add Project modal subtitle is the
// verbatim approved string ("...tracking SEO, AEO, and GEO performance.").
const I18N_EXEMPTIONS = new Set([".projectForm.sub"]);

const collectJsonValues = (file: string): string[] => {
  const data = JSON.parse(fs.readFileSync(path.join(frontendRoot, file), "utf8")) as unknown;
  const violations: string[] = [];
  const walk = (node: unknown, trail: string) => {
    if (typeof node === "string") {
      if (I18N_EXEMPTIONS.has(trail)) return;
      if (ACRONYM.test(node)) violations.push(`${file} ${trail}=${node}`);
      return;
    }
    if (Array.isArray(node)) node.forEach((item, i) => walk(item, `${trail}[${i}]`));
    else if (node && typeof node === "object") {
      for (const [key, value] of Object.entries(node)) walk(value, `${trail}.${key}`);
    }
  };
  walk(data, "");
  return violations;
};

describe("customer-facing terminology", () => {
  it("keeps bare AEO and GEO out of rendered copy across app, portal and components", () => {
    const files = [
      ...collectSources("src/app"),
      ...collectSources("src/components"),
      ...collectSources("src/lib"),
      ...collectSources("src/hooks"),
      ...collectSources("src/services"),
      ...collectSources("src/constants"),
      ...collectSources("src/types"),
    ];
    const violations = files.flatMap(findViolations);
    expect(violations).toEqual([]);
  });

  it("keeps bare AEO and GEO out of i18n values", () => {
    expect([
      ...collectJsonValues("src/i18n/en.json"),
      ...collectJsonValues("src/i18n/ar.json"),
    ]).toEqual([]);
  });
});
