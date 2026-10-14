import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import en from "./en.json";

// A missing translation is invisible to every other test in this suite. i18next
// resolves an unknown key by returning the key itself, so a broken lookup still
// renders a string, still satisfies a `toBeInTheDocument`, and still screenshots
// as a plausible-looking label. That is how four white-label toasts shipped
// showing `wsSettings.whiteLabel.domainAdded` to agency customers (SIGV2-1227):
// the strings existed, but under `customDomain.*`, and nothing compared the call
// sites against the catalogue.
//
// This test closes the class rather than the four instances. It reads every
// literal key passed to `t()` across the app and asserts the catalogue can
// resolve it.

const here = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(here, "..");

const PLURAL_SUFFIX = /_(zero|one|two|few|many|other)$/;

const flattenKeys = (obj: Record<string, unknown>, prefix = ""): string[] =>
  Object.entries(obj).flatMap(([key, value]) => {
    const nextKey = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object" && !Array.isArray(value)) {
      return flattenKeys(value as Record<string, unknown>, nextKey);
    }
    return [nextKey];
  });

const catalogue = new Set(flattenKeys(en as Record<string, unknown>));
const catalogueBases = new Set([...catalogue].map((key) => key.replace(PLURAL_SUFFIX, "")));

const collectSourceFiles = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" || entry.name === ".next"
        ? []
        : collectSourceFiles(full);
    }
    if (!/\.tsx?$/.test(entry.name)) return [];
    // The i18n suite deliberately asserts on unresolvable keys.
    if (/\.test\.tsx?$/.test(entry.name)) return [];
    return [full];
  });

interface Reference {
  file: string;
  line: number;
  key: string;
}

// Matches `t("some.key"` and `i18nKey="some.key"`. Keys built from variables or
// template literals are out of scope on purpose: they cannot be checked
// statically, and guessing at them would make this test unreliable.
const CALL_SITE = /(?:\bt\(\s*|i18nKey=\{?\s*)["']([A-Za-z0-9_][A-Za-z0-9_.-]*)["']/g;

// Reads the argument list following a matched key so a call that supplies its
// own `defaultValue` can be skipped: it renders real copy whether or not the
// catalogue carries the key, so it is not a user-visible defect.
const callSuppliesDefault = (source: string, keyEndIndex: number): boolean => {
  let depth = 1;
  let index = keyEndIndex;
  while (index < source.length && depth > 0) {
    const char = source[index];
    if (char === "(") depth += 1;
    else if (char === ")") depth -= 1;
    index += 1;
  }
  return source.slice(keyEndIndex, index).includes("defaultValue");
};

const collectReferences = (): Reference[] => {
  const references: Reference[] = [];
  for (const file of collectSourceFiles(SRC)) {
    const source = readFileSync(file, "utf-8");
    // Precomputed so a match index becomes a line number without rescanning.
    const lineStarts = [0];
    for (let i = 0; i < source.length; i += 1) {
      if (source[i] === "\n") lineStarts.push(i + 1);
    }

    for (const match of source.matchAll(CALL_SITE)) {
      const key = match[1];
      // A bare identifier is a local variable or a namespace, not a path.
      if (!key.includes(".")) continue;
      const end = match.index + match[0].length;
      if (callSuppliesDefault(source, end)) continue;

      let line = lineStarts.findIndex((start) => start > match.index);
      line = line === -1 ? lineStarts.length : line;

      references.push({ file: path.relative(SRC, file), line, key });
    }
  }
  return references;
};

describe("translation call sites (SIGV2-1227)", () => {
  const references = collectReferences();

  it("finds the translation call sites to check", () => {
    // Guards the scanner itself. If a refactor changes how `t()` is called and
    // the regex stops matching, every assertion below would pass vacuously.
    expect(references.length).toBeGreaterThan(500);
  });

  it("resolves every literal translation key against the English catalogue", () => {
    const unresolved = references
      .filter(
        ({ key }) => !catalogue.has(key) && !catalogueBases.has(key.replace(PLURAL_SUFFIX, ""))
      )
      .map(({ file, line, key }) => `${file}:${line} -> ${key}`);

    // Listed in full: the failure message is the fix list.
    expect(unresolved).toEqual([]);
  });

  it("never points a call site at a namespace instead of a string", () => {
    // `t("wsSettings.whiteLabel")` resolves to an object, which i18next renders
    // as the key. A parent of a real key is therefore just as broken as a key
    // that does not exist, and the check above would not see it.
    const namespaces = new Set<string>();
    for (const key of catalogue) {
      const parts = key.split(".");
      for (let i = 1; i < parts.length; i += 1) {
        namespaces.add(parts.slice(0, i).join("."));
      }
    }

    const pointingAtNamespace = references
      .filter(({ key }) => namespaces.has(key))
      .map(({ file, line, key }) => `${file}:${line} -> ${key}`);

    expect(pointingAtNamespace).toEqual([]);
  });
});
