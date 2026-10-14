import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const layout = readFileSync(path.join(process.cwd(), "src/app/layout.tsx"), "utf8");
const css = readFileSync(path.join(process.cwd(), "src/app/globals.css"), "utf8");

describe("Signal toast presentation", () => {
  it("positions the toast stack in the bottom-right with mobile-safe gutters", () => {
    expect(layout).toContain('position="bottom-right"');
    expect(layout).toContain("offset={{ bottom: 24, right: 24 }}");
    expect(layout).toContain("mobileOffset={16}");
    expect(layout).not.toContain('icon: "mt-0! self-start!"');
    expect(layout).not.toContain("p-0!");
  });

  it("uses the MVP ink toast surface and centres sentence-case text", () => {
    const toast = css.slice(css.indexOf(".thoth-toast {"), css.indexOf(".thoth-toast-panel {"));
    expect(toast).toContain("background: var(--ink)");
    expect(toast).toContain("color: var(--panel)");
    // SIGV2-1222: the 1px edge is the shared animated ring, with the solid
    // tone colour kept as the no-mask-composite fallback. The ink surface
    // itself did not change.
    expect(toast).toContain("border: 1px solid var(--al-edge);");
    expect(toast).toContain("border-radius: 10px");
    expect(toast).toContain("text-align: center");
    expect(toast).toContain("letter-spacing: normal");
    expect(toast).not.toContain("text-transform: uppercase");
    expect(toast).not.toContain("font-family: var(--mono)");
  });

  // SIGV2-1171: tone is carried by one of the four approved `.alert` glyph
  // shapes, never by colour alone (WCAG 1.4.1). A plain coloured dot reads as
  // identical to a colour-blind customer, so the marker is the lucide glyph
  // and the old 8px circle may not come back.
  it("marks tone with the four approved glyphs, not a coloured dot", () => {
    expect(layout).toContain("success:");
    expect(layout).toContain("CheckCircle2");
    expect(layout).toContain("XCircle");
    expect(layout).toContain("AlertTriangle");
    expect(layout).toContain("Info");
    const icon = css.slice(
      css.indexOf(".thoth-toast-icon {"),
      css.indexOf(".thoth-toast-success {")
    );
    expect(icon).not.toContain("border-radius: 50%");
    expect(icon).not.toContain("background:");
  });

  // SIGV2-1222: the gradient edge is added to the tone, never substituted for
  // it. Every status tone still sets --toast-indicator, which is what colours
  // the glyph, so removing the glyph to leave "just the pretty edge" fails
  // here as well as in the assertion above.
  it("adds the gradient edge to each tone without replacing its glyph colour", () => {
    for (const tone of ["success", "error", "warning", "info"]) {
      const rule = css.slice(
        css.indexOf(`.thoth-toast-${tone} {`),
        css.indexOf(`.thoth-toast-${tone} {`) + 260
      );
      expect(rule).toContain("--toast-indicator:");
      expect(rule).toContain("--al-edge:");
      expect(rule).toContain("--al-edge-hi:");
    }
  });

  // The slide-in was already stopped under reduced motion; the edge joins it.
  // A toast that keeps sweeping while the rest of the page is frozen is both
  // a WCAG 2.2.2 failure and a non-deterministic screenshot.
  it("stops both toast animations under prefers-reduced-motion", () => {
    const animation = css.slice(
      css.indexOf(".thoth-toast {\n  animation: toastin"),
      css.indexOf(".skel-line {")
    );
    expect(animation).toContain("@media (prefers-reduced-motion: reduce)");
    expect(animation).toContain(".thoth-toast,");
    expect(animation).toContain(".thoth-toast::before");
    expect(animation).toContain("animation: none;");
  });
});
