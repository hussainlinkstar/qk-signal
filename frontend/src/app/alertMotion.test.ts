import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

// ---------------------------------------------------------------------------
// SIGV2-1222: the animated gradient edge, held as a contract.
//
// The edge is the one moving element on surfaces the screenshot gates
// photograph at zero pixel tolerance, so three things about it are
// load-bearing and all three can be undone by an edit that looks harmless:
//
// 1. It is a CSS animation. SIGV2-1178 cost a day to the alternative: the
//    score gauges were animated by framer-motion springs, Playwright caught
//    them at different frames between runs, and the fix was to honour the
//    reduced-motion hook so the harness could freeze them. A CSS animation is
//    stopped by `prefers-reduced-motion` and by the harness's own stylesheet;
//    an unconditional JS loop is stopped by neither.
// 2. `prefers-reduced-motion: reduce` stops it. That is an accessibility
//    requirement in its own right, not a test convenience: a continuously
//    moving element is a vestibular trigger and WCAG 2.2.2 applies.
// 3. The resting position is the declared one, so two runs of the visual
//    suite produce byte-identical snapshots rather than two frames of the
//    same sweep.
//
// The browser-side proof, which measures the computed animation in both
// motion preferences with the harness's determinism stylesheet switched off,
// is e2e/visual/alert-treatment.visual.spec.ts. This file is the cheap guard
// that stops the rule being deleted by an unrelated edit.
// ---------------------------------------------------------------------------

const globalsCss = readFileSync(`${process.cwd()}/src/app/globals.css`, "utf8");

/** The body of the `@media (prefers-reduced-motion: reduce)` rule that stops
 *  the two animated presentation tiers. */
const reducedMotionBlock = (() => {
  const marker = "@media (prefers-reduced-motion: reduce) {\n  .signal-pulse-dot,";
  const start = globalsCss.indexOf(marker);
  return start === -1 ? "" : globalsCss.slice(start, globalsCss.indexOf("}", start + 200) + 1);
})();

/** The masked ring rule, which is where the gradient actually lives. */
const ring = (() => {
  const marker = "  [data-signal-alert]::before,\n  .thoth-toast::before {";
  const start = globalsCss.indexOf(marker);
  return start === -1 ? "" : globalsCss.slice(start, globalsCss.indexOf("\n  }", start) + 4);
})();

describe("SIGV2-1222 animated gradient edge", () => {
  it("is driven by a CSS keyframe animation, not a script loop", () => {
    expect(globalsCss).toContain("@keyframes signal-alert-edge");
    expect(globalsCss).toMatch(/animation: signal-alert-edge \d+s linear infinite;/);
  });

  it("animates only background-position, so nothing reflows while it runs", () => {
    const keyframes = globalsCss.slice(
      globalsCss.indexOf("@keyframes signal-alert-edge"),
      globalsCss.indexOf("[data-signal-alert] {")
    );
    expect(keyframes).toContain("background-position: 0 0;");
    expect(keyframes).toContain("background-position: 100% 0;");
    expect(keyframes).not.toMatch(/transform|width|height|margin|padding/);
  });

  it("rests on the declared position, so a frozen frame is always the same frame", () => {
    expect(ring).toContain("background-position: 0 0;");
    expect(ring).toContain("background-size: 200% 100%;");
  });

  it("is stopped by prefers-reduced-motion on both the alert and the toast tier", () => {
    expect(reducedMotionBlock).toContain("@media (prefers-reduced-motion: reduce)");
    expect(reducedMotionBlock).toContain("[data-signal-alert]::before,");
    expect(reducedMotionBlock).toContain(".thoth-toast::before");
    expect(reducedMotionBlock).toContain("animation: none;");
  });

  it("mirrors the sweep in RTL, where the edge changes side with the text", () => {
    expect(globalsCss).toContain('[dir="rtl"] [data-signal-alert]::before,');
    expect(globalsCss).toContain(
      '[dir="rtl"] .thoth-toast::before {\n    animation-direction: reverse;'
    );
  });

  it("gives all four approved tones an edge, and no tone only a colour", () => {
    for (const tone of ["info", "success", "warning", "danger"]) {
      expect(globalsCss).toContain(`[data-signal-alert="${tone}"] {`);
    }
    // The glyph is the non-colour cue (WCAG 1.4.1, SIGV2-1171). It lives in
    // the components, so what this file holds is that the edge never became a
    // tone's only expression: each tone still names its own approved fill.
    for (const fill of ["--blue-s", "--good-s", "--warn-s", "--bad-s"]) {
      expect(globalsCss).toContain(`--al-fill: var(${fill});`);
    }
  });

  it("fades the tone background independently of the animated edge", () => {
    expect(globalsCss).toContain(
      "background-image: linear-gradient(to bottom, var(--al-fill), transparent 80%);"
    );
  });

  it("paints the gradient into a masked 1px ring, never over the panel fill", () => {
    // The rejected alternative was a two-layer padding-box/border-box
    // background. Every translucent tone fill let the edge gradient show
    // through the whole panel, which moved the `fixes` design figure 3.3
    // points on what is meant to be a one-pixel edge.
    expect(ring).toContain("inset: -1px;");
    expect(ring).toContain("padding: 1px;");
    expect(ring).toContain("mask-composite: exclude;");
    expect(ring).toContain("-webkit-mask-composite: xor;");
    expect(ring).toContain("z-index: -1;");
    expect(globalsCss).not.toContain("padding-box,");
  });

  it("keeps a plain tone border for a browser without mask-composite", () => {
    expect(globalsCss).toContain(
      "@supports ((mask-composite: exclude) or (-webkit-mask-composite: xor))"
    );
    const base = globalsCss.slice(
      globalsCss.indexOf("[data-signal-alert] {"),
      globalsCss.indexOf('[data-signal-alert="info"]')
    );
    expect(base).toContain("border: 1px solid var(--al-edge);");
    expect(base).toContain("isolation: isolate;");
  });
});
