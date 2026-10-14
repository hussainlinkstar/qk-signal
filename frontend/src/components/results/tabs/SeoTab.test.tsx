import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SeoTab from "@/components/results/tabs/SeoTab";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const props = (overrides: Partial<React.ComponentProps<typeof SeoTab>> = {}) => ({
  performance: { performance_score: 61 },
  seoAudits: [
    { title: "Document has a meta description", score: 1 },
    { title: "Links have descriptive text", score: 0.4 },
    { title: "Image elements have alt attributes", score: 0.5 },
  ],
  structuredDataDetected: false,
  lcpValue: "1322 ms",
  clsValue: "0.344",
  ...overrides,
});

// ---------------------------------------------------------------------------
// SIGV2-1302 / SIGV2-1286. This panel was two shadowed cards floating over the
// disclosure containing them, a badge reading "OS OK", body copy in capitals,
// and a section headed "Atomic SEO Protocols" that rendered nothing when the
// check list was empty. It is rebuilt on `.st` from signal.css, the shape the
// approved design already defines for this question.
// ---------------------------------------------------------------------------

describe("SeoTab, on the approved factor anatomy", () => {
  it("carries none of the pre-redesign visual language", () => {
    const { container } = render(<SeoTab {...props()} />);
    const markup = container.innerHTML;

    for (const token of [
      "rounded-4xl",
      "shadow-2xl",
      "blur-sm",
      "bg-linear-to-r",
      "tracking-[0.2em]",
      "drop-shadow",
    ]) {
      expect(markup).not.toContain(token);
    }
  });

  it("says none of the words that were ours rather than a customer's", () => {
    const { container } = render(<SeoTab {...props()} />);
    const text = container.textContent ?? "";

    expect(text).not.toContain("OS OK");
    expect(text).not.toContain("DATA ERR");
    expect(text).not.toContain("Atomic SEO Protocols");
    expect(text).not.toContain("SEARCH VISIBILITY CHECKS");
    // And no sentence shouted in capitals.
    expect(text).not.toContain("NO STRUCTURED DATA DETECTED");
  });

  it("shows one row per factor the scan measures", () => {
    const { container } = render(<SeoTab {...props()} />);

    expect(container.querySelectorAll("[data-score-factor]")).toHaveLength(3);
    expect(screen.getByText(tEn("signalSeoFactors.technical"))).toBeInTheDocument();
    expect(screen.getByText(tEn("signalSeoFactors.schema"))).toBeInTheDocument();
    expect(screen.getByText(tEn("signalSeoFactors.onPage"))).toBeInTheDocument();
  });

  it("opens a factor to say why you are here and how to improve", () => {
    const { container } = render(<SeoTab {...props()} />);
    const row = container.querySelector('[data-score-factor="technical"]') as HTMLElement;
    const trigger = row.querySelector("button") as HTMLButtonElement;

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(tEn("signalSeoFactors.whyTitle"))).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(tEn("signalSeoFactors.whyTitle"))).toBeInTheDocument();
    expect(screen.getByText(tEn("signalSeoFactors.howTitle"))).toBeInTheDocument();
    // The measurement is cited, not asserted.
    expect(row.textContent).toContain("1322 ms");
    expect(row.textContent).toContain("0.344");
  });

  it("puts the individual checks inside the factor they belong to", () => {
    // They used to sit under a heading of their own, which rendered empty
    // whenever the list was. Only the failing ones are worth the reader's
    // attention, which is where the points are.
    const { container } = render(<SeoTab {...props()} />);
    const row = container.querySelector('[data-score-factor="on-page"]') as HTMLElement;

    fireEvent.click(row.querySelector("button") as HTMLButtonElement);

    expect(row.textContent).toContain("Links have descriptive text");
    expect(row.textContent).toContain("Image elements have alt attributes");
    expect(row.textContent).not.toContain("Document has a meta description");
  });

  it("says not measured instead of scoring zero, and draws no bar", () => {
    const { container } = render(
      <SeoTab
        {...props({
          performance: {},
          structuredDataDetected: undefined,
          seoAudits: [],
        })}
      />
    );

    const rows = container.querySelectorAll("[data-score-factor]");
    expect(rows).toHaveLength(3);
    for (const row of Array.from(rows)) {
      expect(row.textContent).toContain(tEn("signalSeoFactors.notMeasured"));
      // An empty bar reads as a zero, so an unmeasured factor draws none.
      expect(row.querySelector("i")).toBeNull();
      const label = row.querySelector("button > span") as HTMLElement;
      expect(label.className).not.toContain("w-[52px]");
      expect(label.className).not.toContain("text-[26px]");
      expect(label.className).toContain("shrink-0");
    }
  });

  it("never announces a section it then leaves empty", () => {
    const { container } = render(<SeoTab {...props({ seoAudits: [] })} />);
    const row = container.querySelector('[data-score-factor="on-page"]') as HTMLElement;

    fireEvent.click(row.querySelector("button") as HTMLButtonElement);

    // No check list, so it says so in the space rather than leaving a heading
    // over nothing.
    expect(row.textContent).toContain(tEn("signalSeoFactors.onPageWhyNone"));
    expect(row.querySelectorAll("li")).toHaveLength(0);
  });

  it("explains itself rather than showing metrics a brand scan cannot have", () => {
    render(<SeoTab {...props({ isBrandWithoutUrl: true })} />);

    // SIGV2-1317: the explanation, without a heading repeating the section's
    // own name. The disclosure above already says what this section is, and
    // printing it again inside was the duplication the page was reported for.
    expect(screen.getByText(tEn("signalSeoFactors.unavailableBody"))).toBeInTheDocument();
    expect(screen.queryByText(tEn("signalSeoFactors.technical"))).not.toBeInTheDocument();
  });
  // The alignment itself, pinned. These are the declared values of `.st` in
  // the approved `signal.css`, the block `Signal SEO Detail.html` uses for
  // this exact question:
  //
  //   .st .sh    padding 16px 22px, gap 14px
  //   .st .num   display font, 900, 26px, width 52px, tracking -.02em
  //   .st .sn .t display font, 700, 14.5px
  //   .st .sn .d 12.5px, --t-3
  //   .st .sbar  150px wide, 7px tall, radius 999px, bg --line
  //   .st .body  padding 2px 22px 20px 74px
  //   .st .lab   mono 10.5px, tracking .08em, uppercase, --t-3
  //
  // A visual test would be the better guard, but this page is in none of the
  // 42 gated screens (SIGV2-1302), so until it is, the numbers are pinned
  // here rather than left to drift unobserved.
  it("matches the declared geometry of the approved factor row", () => {
    const { container } = render(<SeoTab {...props()} />);
    const row = container.querySelector('[data-score-factor="technical"]') as HTMLElement;
    const trigger = row.querySelector("button") as HTMLButtonElement;

    expect(trigger.className).toContain("px-[22px]");
    expect(trigger.className).toContain("gap-[14px]");

    const number = trigger.querySelector("span") as HTMLElement;
    expect(number.className).toContain("w-[52px]");
    expect(number.className).toContain("text-[26px]");
    expect(number.className).toContain("font-black");
    expect(number.className).toContain("tracking-[-0.02em]");

    const bar = trigger.querySelector("i")?.parentElement as HTMLElement;
    expect(bar.className).toContain("w-[150px]");
    expect(bar.className).toContain("h-[7px]");
    expect(bar.className).toContain("bg-(--line)");

    fireEvent.click(trigger);
    const body = row.querySelector(`#seo-factor-technical`) as HTMLElement;
    expect(body.className).toContain("px-[22px]");
    expect(body.className).toContain("ps-[74px]");

    // SIGV2-1317: the rows are not boxed again.
    //
    // This used to assert that their container was a card, which is how the
    // page ended up three cards deep: the section is the card, drawn by
    // `ReportDisclosure` on the approved Scan history anatomy, and the rows
    // live directly inside it.
    //
    // Worth separating two different 74px values, since they look alike and
    // only one was wrong. `ps-[74px]` above is the approved `.st .body`
    // indent, which lines a factor's detail up under its own score, and it
    // stays. The 74px removed in SIGV2-1317 was on the disclosure body, where
    // it indented a whole section away from its own heading.
    const container_ = row.parentElement as HTMLElement;
    expect(container_.className).not.toContain("rounded-(--r)");
    expect(container_.className).not.toContain("bg-(--panel)");
  });
});
