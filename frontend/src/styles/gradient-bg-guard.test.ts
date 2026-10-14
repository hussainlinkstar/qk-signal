import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

// `bg-(--name)` compiles to `background-color: var(--name)`. When --name holds
// a gradient the declaration is invalid and silently dropped, so the element
// renders with no fill at all. The image-valued form is `bg-(image:--name)`.
const frontendRoot = path.resolve(__dirname, "../..");
const globalsCss = fs.readFileSync(path.join(frontendRoot, "src/app/globals.css"), "utf8");

const imageTokens = [...globalsCss.matchAll(/--([a-z0-9-]+):\s*[^;]*gradient\(/gi)].map(
  (match) => match[1]
);

const collectSources = (dir: string, pattern = /\.(tsx|jsx)$/): string[] =>
  fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return collectSources(full, pattern);
    return pattern.test(entry.name) ? [full] : [];
  });

// A `bg-(--name)` (or text-/border-/ring-(--name)) token that nothing ever
// assigns makes the generated `var(--name)` declaration invalid at computed
// time: the fill silently drops and a light label sits on a light surface,
// visible only through the literal hover colour. SIGV2-1092. Assignments live
// in stylesheets (`--name: value`) and inline styles (`"--name": value`), so
// both forms count as definitions wherever they appear under src/.
const definedTokens = new Set(
  [...globalsCss.matchAll(/--([a-z0-9-]+)\s*:/gi)].map((match) => match[1])
);
for (const file of collectSources(path.join(frontendRoot, "src"), /\.css$/)) {
  const source = fs.readFileSync(file, "utf8");
  for (const match of source.matchAll(/--([a-z0-9-]+)\s*:/gi)) {
    definedTokens.add(match[1]);
  }
}
for (const file of collectSources(path.join(frontendRoot, "src"))) {
  const source = fs.readFileSync(file, "utf8");
  for (const match of source.matchAll(/["']--([a-z0-9-]+)["']\s*:/gi)) {
    definedTokens.add(match[1]);
  }
}

const tokenUtilityPattern =
  /(?:bg|text|border|ring|fill|stroke|from|via|to|outline|shadow)-\((?:image:)?--([a-z0-9-]+)\)/g;

const unreferencedTokens = (source: string): string[] => {
  const missing: string[] = [];
  for (const match of source.matchAll(tokenUtilityPattern)) {
    if (!definedTokens.has(match[1])) missing.push(`--${match[1]}`);
  }
  return missing;
};

describe("gradient tokens need the bg-(image:) form", () => {
  it("has image-valued custom properties to guard", () => {
    expect(imageTokens).toContain("grad");
  });

  it("never applies a gradient token through background-color", () => {
    const offenders: string[] = [];
    for (const file of collectSources(path.join(frontendRoot, "src"))) {
      const source = fs.readFileSync(file, "utf8");
      for (const token of imageTokens) {
        const bare = new RegExp(`bg-\\(--${token}\\)`);
        if (bare.test(source)) offenders.push(`${file}: bg-(--${token})`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

// Two unprefixed `bg-(--a)` utilities on one element do not override by class
// order: the winner is whichever rule Tailwind emits later in the stylesheet.
// `bg-(--ink)` sorts before `bg-(--panel)`, so a panel base plus a conditional
// ink override silently renders panel-coloured - the audit page's "Start the
// check" button shipped white-on-white this way. Conditional fills must be
// exclusive branches, never stacked tokens.
const bareFillPattern = /(?<![\w:()!-])bg-\(--[a-z0-9-]+\)(?![\w()!-])/g;

// Split a cx() argument list on top-level commas, tracking bracket depth and
// quote state so nested calls and strings do not split the wrong way.
const splitTopLevel = (inner: string): string[] => {
  const parts: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let start = 0;
  for (let i = 0; i < inner.length; i++) {
    const c = inner[i];
    if (quote) {
      if (c === quote && inner[i - 1] !== "\\") quote = null;
    } else if (c === '"' || c === "'" || c === "`") {
      quote = c;
    } else if (c === "(" || c === "[" || c === "{") {
      depth++;
    } else if (c === ")" || c === "]" || c === "}") {
      depth--;
    } else if (c === "," && depth === 0) {
      parts.push(inner.slice(start, i));
      start = i + 1;
    }
  }
  parts.push(inner.slice(start));
  return parts;
};

// For one cx() argument, separate fills that always apply (unconditional
// string segments) from fills inside the two branches of a ternary. `a ? x :
// y` makes x and y exclusive with each other; `a && x` only adds x.
const argFills = (arg: string): { unconditional: Set<string>; conditional: Set<string> } => {
  const unconditional = new Set<string>();
  const conditional = new Set<string>();
  // Pull string literals out in order, noting whether `?` or `&&` precedes.
  const literal = /(["'`])([^"'`]*)\1/g;
  for (const m of arg.matchAll(literal)) {
    const before = arg.slice(0, m.index);
    const fills = m[2].match(bareFillPattern) ?? [];
    const inBranch =
      /\?\s*$/.test(before) ||
      /:\s*$/.test(before) ||
      /&&\s*$/.test(before) ||
      /\|\|\s*$/.test(before);
    for (const f of fills) {
      (inBranch ? conditional : unconditional).add(f);
    }
  }
  return { unconditional, conditional };
};

const stackedTokenFills = (source: string): string[] => {
  const offenders: string[] = [];
  const cxCall = /\b(?:cx|clsx|cn)\s*\(/g;
  for (const start of source.matchAll(cxCall)) {
    let depth = 0;
    let end = start.index;
    for (let i = start.index; i < source.length; i++) {
      if (source[i] === "(") depth++;
      else if (source[i] === ")") {
        depth--;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    const expr = source.slice(start.index, end + 1);
    const inner = expr.slice(expr.indexOf("(") + 1, -1);
    const unconditional = new Set<string>();
    const conditional = new Set<string>();
    for (const arg of splitTopLevel(inner)) {
      const { unconditional: u, conditional: c } = argFills(arg);
      u.forEach((f) => unconditional.add(f));
      c.forEach((f) => conditional.add(f));
    }
    // A fill that is always applied plus a different fill applied in any
    // branch compete on sheet order - that is the white-on-white defect.
    const conflicts = [...conditional].filter((f) => !unconditional.has(f));
    if (unconditional.size > 0 && conflicts.length > 0) {
      offenders.push(expr.replace(/\s+/g, " ").trim().slice(0, 80));
    }
  }
  return offenders;
};

describe("one element must not stack two bare token fills", () => {
  it("flags a stacked panel-plus-ink fill", () => {
    expect(
      stackedTokenFills('cx("bg-(--panel) border-(--line)", on ? "bg-(--ink)" : "")')
    ).toHaveLength(1);
    expect(
      stackedTokenFills('cx("border", on ? "bg-(--ink) text-white" : "bg-(--panel)")')
    ).toEqual([]);
    expect(stackedTokenFills('cx("bg-(--panel)", "hover:bg-(--ink)")')).toEqual([]);
    expect(stackedTokenFills('cx("bg-(--panel)", on && "bg-(--good-s)!")')).toEqual([]);
  });

  it("no source stacks two bare token fills on one element", () => {
    const offenders: string[] = [];
    for (const file of collectSources(path.join(frontendRoot, "src"))) {
      for (const snippet of stackedTokenFills(fs.readFileSync(file, "utf8"))) {
        offenders.push(`${file}: ${snippet}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

// A `ring-offset-*` utility draws the offset band in --tw-ring-offset-color,
// which defaults to white. On a gradient-filled control that lands as a 2px
// white frame tight against the fill - Razvan's "white border" on the upgrade
// CTA. Gradient controls must use the 3px --ring halo (or an outline) with no
// offset band.
const gradientFillWithOffset = (source: string): string[] => {
  const offenders: string[] = [];
  const literal = /(["'`])([^"'`]*)\1/g;
  for (const m of source.matchAll(literal)) {
    const classes = m[2];
    if (/bg-\(image:--[a-z0-9-]+\)/.test(classes) && /ring-offset/.test(classes)) {
      offenders.push(classes.replace(/\s+/g, " ").trim().slice(0, 80));
    }
  }
  return offenders;
};

describe("gradient-filled controls never carry a white ring-offset band", () => {
  it("flags ring-offset on a gradient fill", () => {
    expect(
      gradientFillWithOffset('"bg-(image:--grad) focus-visible:ring-2 focus-visible:ring-offset-2"')
    ).toHaveLength(1);
    expect(
      gradientFillWithOffset('"bg-(image:--grad) focus-visible:shadow-[0_0_0_3px_var(--ring)]"')
    ).toEqual([]);
    expect(gradientFillWithOffset('"bg-(--ink) focus-visible:ring-offset-2"')).toEqual([]);
  });

  it("no source pairs a gradient fill with ring-offset", () => {
    const offenders: string[] = [];
    for (const file of collectSources(path.join(frontendRoot, "src"))) {
      for (const snippet of gradientFillWithOffset(fs.readFileSync(file, "utf8"))) {
        offenders.push(`${file}: ${snippet}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});

describe("token utilities must resolve to a defined custom property", () => {
  it("flags a token that resolves to nothing", () => {
    expect(unreferencedTokens('className="bg-(--definitely-undefined-token)"')).toEqual([
      "--definitely-undefined-token",
    ]);
    expect(unreferencedTokens('className="bg-(--ink) text-(--t-1)"')).toEqual([]);
  });

  it("no source applies an undefined token utility", () => {
    const offenders: string[] = [];
    for (const file of collectSources(path.join(frontendRoot, "src"))) {
      const source = fs.readFileSync(file, "utf8");
      for (const token of unreferencedTokens(source)) {
        offenders.push(`${file}: --${token.slice(2)} undefined`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
