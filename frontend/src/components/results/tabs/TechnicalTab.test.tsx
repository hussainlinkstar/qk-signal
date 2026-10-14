import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TechnicalTab from "@/components/results/tabs/TechnicalTab";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const props = (overrides: Partial<React.ComponentProps<typeof TechnicalTab>> = {}) => ({
  performance: {
    performance_score: 61,
    largest_contentful_paint: 1322,
    cumulative_layout_shift: 0.344,
  },
  network: { http_version: "h2", supports_http2: true, supports_http3_inferred: false },
  technicalSignals: { seo_audit_checks: ["Canonical link present", "Robots.txt reachable"] },
  ...overrides,
});

// ---------------------------------------------------------------------------
// SIGV2-1302. "Site health" was three glowing tiles and two shadowed cards,
// every label in `font-black uppercase tracking-[0.2em]`, every string value
// forced to capitals, and an empty state drawn at 30% opacity behind a 48px
// icon in 200px of reserved blank card.
// ---------------------------------------------------------------------------

describe("TechnicalTab, on the approved visual language", () => {
  it("carries none of the pre-redesign visual language", () => {
    const { container } = render(<TechnicalTab {...props()} />);
    const markup = container.innerHTML;

    for (const token of [
      "rounded-4xl",
      "shadow-2xl",
      "blur-sm",
      "blur-xl",
      "bg-linear-to-r",
      "bg-linear-to-br",
      "tracking-[0.2em]",
      "drop-shadow",
    ]) {
      expect(markup).not.toContain(token);
    }
  });

  // SIGV2-1317: Site health is one object, not three.
  //
  // This asserted that each of its three groups was its own card. Inside the
  // disclosure, which is already a card on the approved Scan history
  // anatomy, that put the reader three borders deep for one set of numbers,
  // and it is the nesting the page was reported for.
  //
  // The groups divide the approved way instead: `.st`, a single
  // `border-top: 1px solid var(--line-2)`. A rule between two things reads as
  // a division; a border all the way round reads as a new object.
  it("divides its groups with a rule rather than boxing each one", () => {
    const { container } = render(<TechnicalTab {...props()} />);

    const groups = Array.from(container.querySelectorAll("[data-site-health]"));
    expect(groups.length).toBeGreaterThan(1);

    for (const group of groups) {
      expect(group.className).not.toContain("rounded-(--r)");
      expect(group.className).not.toContain("bg-(--panel)");
      expect(group.className).not.toContain("shadow");
    }
  });

  it("prints a value as it came instead of shouting it", () => {
    // `formatMetric` used to return `value.toUpperCase()`, which is how "h2"
    // reached the customer as "H2".
    render(<TechnicalTab {...props()} />);

    expect(screen.getByText("h2")).toBeInTheDocument();
    expect(screen.queryByText("H2")).not.toBeInTheDocument();
  });

  it("lists the checks it has", () => {
    render(<TechnicalTab {...props()} />);

    expect(screen.getByText("Canonical link present")).toBeInTheDocument();
    expect(screen.getByText("Robots.txt reachable")).toBeInTheDocument();
  });

  it("states an empty check list in words, not as a decoration", () => {
    const { container } = render(
      <TechnicalTab {...props({ technicalSignals: { seo_audit_checks: [] } })} />
    );
    const card = container.querySelector('[data-site-health="checks"]') as HTMLElement;

    expect(card.textContent).toContain(tEn("signalAuditReport.siteHealth.checksEmpty"));
    // No 200px of reserved blank, no icon standing in for an answer.
    expect(card.querySelector("svg")).toBeNull();
    expect(card.innerHTML).not.toContain("opacity-30");
    expect(card.innerHTML).not.toContain("min-h-");
  });

  it("says a metric was not collected rather than printing a bare zero", () => {
    const { container } = render(<TechnicalTab {...props({ performance: {} })} />);
    const card = container.querySelector('[data-site-health="performance"]') as HTMLElement;

    expect(card.textContent).toContain(tEn("signalAuditReport.siteHealth.notCollected"));
    expect(card.textContent).not.toContain("0");
  });

  it("keeps an unmeasured value visually quieter than a measured one", () => {
    const { container } = render(<TechnicalTab {...props({ performance: {} })} />);
    const card = container.querySelector('[data-site-health="performance"]') as HTMLElement;
    const values = Array.from(card.querySelectorAll("[data-metric-value]"));

    expect(values).toHaveLength(3);
    for (const value of values) {
      expect(value.getAttribute("data-metric-value")).toBe("unmeasured");
      expect(value.className).toContain("text-(--t-3)");
    }
  });
});
