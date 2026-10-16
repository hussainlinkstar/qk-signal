import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// SIGV2-1217: the two focus defects in globals.css, held as a contract.
//
// 1. The global `:focus-visible` rule set `outline: 2px solid transparent` on
//    every a/button/input/select/textarea/[role=button] in the product. That
//    declaration is Tailwind v3's `outline-none` (v4: `outline-hidden`): it
//    exists so a COMPONENT can draw its own ring and still keep an outline in
//    forced-colors mode. Applied globally it means every interactive element
//    that draws nothing of its own shows nothing at all on a keyboard tab.
//    628 of the 713 interactive elements in src/ were in that position, which
//    is a WCAG 2.4.7 failure across almost the whole app.
//
// 2. @tailwindcss/forms styles every bare input/select/textarea on `:focus`
//    (so a mouse click too) with a #2563eb border and ring, and paints its
//    own chevron under any explicit one. SIGV2-1201 solved this for the
//    shared project-setup fields with two opt-in classes rather than a global
//    override; this ticket adopts them on the surfaces that still had it.
//    The plugin's base layer is deliberately left in place: every form in the
//    product renders through it.
//
// The browser-side proof that focus is actually visible, and that nobody gets
// two rings, is e2e/visual/focus-treatment.visual.spec.ts. This file is the
// cheap guard that stops either defect being reintroduced by an edit.
// ---------------------------------------------------------------------------

const globalsCss = readFileSync(`${process.cwd()}/src/app/globals.css`, "utf8").replace(
  /\r\n/g,
  "\n"
);

const INTERACTIVES = ':is(a, button, input, select, textarea, [role="button"]):focus-visible';

describe("SIGV2-1217 global keyboard focus indicator", () => {
  it("no longer hands every interactive element a transparent outline", () => {
    expect(globalsCss).not.toContain(`${INTERACTIVES} {\n    outline: 2px solid transparent;`);
  });

  it("gives them a real outline in a named colour instead", () => {
    expect(globalsCss).toContain(
      `${INTERACTIVES} {\n    outline: 2px solid var(--focus-ring);\n    outline-offset: 2px;\n  }`
    );
  });

  it("defines --focus-ring for both themes, light and dark", () => {
    // The light app (dashboard/admin): solid approved brand indigo, 6.9:1 on
    // --panel. The design's own --ring is rgba(79,70,229,.28), about 1.3:1,
    // so it stays a shell/ring token and is not used as an outline colour.
    expect(globalsCss).toContain("--focus-ring: var(--brand);");
    // The dark brand theme (marketing, auth, portal) needs the light indigo.
    expect(globalsCss).toContain("--focus-ring: #a5b4fc;");
  });

  it("is an outline, never a base-layer box-shadow", () => {
    // A `shadow-*` utility sits in a later cascade layer and would replace a
    // base-layer box-shadow outright, so six interactive elements carrying a
    // resting shadow would have silently kept no indicator at all.
    const rule = globalsCss.slice(
      globalsCss.indexOf(INTERACTIVES),
      globalsCss.indexOf("Autofill overrides")
    );
    expect(rule).not.toMatch(/box-shadow/);
  });

  it("follows the system highlight colour in forced-colors mode", () => {
    expect(globalsCss).toContain("@media (forced-colors: active)");
    expect(globalsCss).toContain("outline-color: Highlight;");
  });

  it("keeps suppressing the user-agent ring for a plain pointer click", () => {
    // `:focus` without `:focus-visible` is a mouse click. The approved design
    // shows no ring there, and this rule is why; removing it would light
    // every control on click.
    expect(globalsCss).toContain(
      ':is(a, button, input, select, textarea, [role="button"]):focus {\n    outline: none;\n  }'
    );
  });
});

describe("SIGV2-1217 forms-plugin opt-ins", () => {
  // The plugin's base layer stays. Every surface that used to inherit its
  // `:focus` treatment now names one of SIGV2-1201's two classes instead:
  // `.input-shell` where a wrapper draws the control, `.field-focus-ring`
  // where the control is standalone.
  const surfaces: Array<[string, string, number]> = [
    ["src/components/signal/SignalDataTable.tsx", "input-shell", 1],
    ["src/app/(app)/dashboard/settings/page.tsx", "field-focus-ring", 6],
    [
      "src/app/(app)/dashboard/projects/[projectId]/settings/sections/ProjectDetailsSection.tsx",
      "field-focus-ring",
      9,
    ],
    [
      "src/app/(app)/dashboard/projects/[projectId]/settings/sections/ConnectedDataSection.tsx",
      "field-focus-ring",
      3,
    ],
    ["src/components/dashboard/settings/ConnectionsPanels.tsx", "field-focus-ring", 2],
    ["src/components/results/AuditContextSection.tsx", "field-focus-ring", 1],
    ["src/components/settings/WorkspaceWhiteLabelSection.tsx", "field-focus-ring", 2],
  ];

  for (const [file, className, count] of surfaces) {
    it(`${file} opts in to .${className}`, () => {
      const source = readFileSync(`${process.cwd()}/${file}`, "utf8");
      const matches = source.match(new RegExp(className, "g")) ?? [];
      expect(matches).toHaveLength(count);
    });
  }

  it("leaves the plugin's own base layer alone", () => {
    // Removing it is the cleaner eventual answer and the riskier one: every
    // form in the product renders through it.
    expect(globalsCss).toContain("@plugin '@tailwindcss/forms';");
  });

  it("keeps SIGV2-1201's rules class-scoped, so nothing is suppressed globally", () => {
    const scoped = globalsCss
      .slice(globalsCss.indexOf("/* SIGV2-1201"), globalsCss.indexOf("@layer utilities {"))
      .replace(/\/\*[\s\S]*?\*\//g, "");
    const selectors = scoped.match(/^ {2}\S[^{}\n]*\{$/gm) ?? [];
    expect(selectors.length).toBeGreaterThan(0);
    for (const selector of selectors) {
      expect(selector.trim()).toMatch(/^\.(input-shell|field-focus-ring)\b/);
    }
  });
});

describe("SIGV2-1217 sibling-drawn focus indicators", () => {
  it("opts the score-target slider out, so its knob is not ringed twice", () => {
    // The only element in src/ that draws its focus indicator on a SIBLING:
    // a transparent full-width range input whose knob lights via
    // `peer-focus-visible`. The new global outline would have drawn a second
    // ring around the whole track.
    const source = readFileSync(
      `${process.cwd()}/src/components/settings/ScoreTargetsCard.tsx`,
      "utf8"
    );
    expect(source).toContain("focus-visible:outline-hidden");
    // `outline-hidden`, not `outline-none`: forced-colors mode keeps a ring.
    expect(source).not.toContain("focus-visible:outline-none");
    expect(source).toContain("peer-focus-visible:shadow-[0_0_0_3px_var(--ring)]");
  });

  it("leaves the sr-only checkbox peers alone", () => {
    // `sr-only` clips the input to 1x1 with `clip`, which clips its outline
    // too, so the new rule cannot double their visible sibling ring.
    for (const file of [
      "src/components/auth/AuthCheckbox.tsx",
      "src/components/dashboard/ProjectBotLogAnalyzerPanel.tsx",
    ]) {
      const source = readFileSync(`${process.cwd()}/${file}`, "utf8");
      expect(source).toContain("peer sr-only");
      expect(source).toMatch(/peer-focus-visible:ring/);
    }
  });
});
