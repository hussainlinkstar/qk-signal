import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import "@/i18n";
import SearchTypeFeeds from "./SearchTypeFeeds";
import VisibilityPanels from "./VisibilityPanels";
import type { SearchType } from "@/lib/reportAdapters";

const searchTypes: SearchType[] = ["brand", "category", "problem", "feature", "comparison"].map(
  (id) => ({
    id,
    label: id,
    score: 61,
    answerRatio: null,
    trend: 2,
    insight: "A measured test insight.",
    premium: false,
    source: "measured",
  })
);

describe("MVP dashboard card geometry", () => {
  it.each(["measured", "pending", "unmeasured"] as const)(
    "keeps %s search-type cards static until detail content exists",
    (source) => {
      const { container } = render(
        <SearchTypeFeeds searchTypes={searchTypes.map((st) => ({ ...st, source }))} />
      );

      expect(container.querySelectorAll("[data-search-type]")).toHaveLength(5);
      expect(screen.queryAllByRole("link")).toHaveLength(0);
      expect(screen.queryAllByRole("button")).toHaveLength(0);
      expect(container.querySelector("[tabindex]")).not.toBeInTheDocument();
      expect(screen.getAllByText("A measured test insight.")).toHaveLength(5);
    }
  );

  it("uses the approved feed order, two-line labels and per-type progress colours", () => {
    const { container } = render(<SearchTypeFeeds searchTypes={searchTypes} />);
    expect(
      [...container.querySelectorAll("[data-search-type]")].map((e) =>
        e.getAttribute("data-search-type")
      )
    ).toEqual(["brand", "category", "problem", "comparison", "feature"]);
    expect(screen.getByText("Brand Understanding")).toHaveClass("whitespace-pre-line");
    expect(screen.getByRole("heading", { name: /Why AI recommends/ })).toHaveClass(
      "text-[17px]",
      "font-extrabold"
    );
    expect(container.querySelector('[data-search-type="category"] [data-signal-bar]')).toHaveStyle({
      background: "var(--warn)",
    });
    expect(screen.getAllByText("Measured")).toHaveLength(5);
    expect(screen.getAllByText("Answer ratio not measured")).toHaveLength(5);
  });

  it("shows the answers checked for a type as the approved ratio line (SIGV2-1105)", () => {
    const { container } = render(
      <SearchTypeFeeds
        searchTypes={searchTypes.map((st) =>
          st.id === "brand" ? { ...st, answerRatio: { present: 7, measured: 10 } } : st
        )}
      />
    );

    expect(
      container.querySelector('[data-search-type="brand"] [data-answer-ratio]')
    ).toHaveAttribute("data-answer-ratio", "measured");
    expect(screen.getByText("7 of 10 answers")).toBeInTheDocument();
    // Every other type still has nothing to count, and still says so.
    expect(screen.getAllByText("Answer ratio not measured")).toHaveLength(4);
  });

  it("never renders an unmeasured per-type score, however the payload labels it", () => {
    render(
      <SearchTypeFeeds searchTypes={searchTypes.map((st) => ({ ...st, source: "unmeasured" }))} />
    );

    expect(screen.queryByText("61")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not measured")).toHaveLength(5);
    expect(screen.getAllByText("No prompt data yet")).toHaveLength(5);
    expect(screen.queryByText("Estimated")).not.toBeInTheDocument();
  });

  it("says a measurement is running rather than that there is no data (SIGV2-1182)", () => {
    // Jake added prompts and these cards still read "No prompt data yet".
    // Once a run is queued for a type, the chip has to say so: "nothing will
    // happen" and "wait a moment" are different answers.
    const { container } = render(
      <SearchTypeFeeds
        searchTypes={searchTypes.map((st) =>
          st.id === "brand" || st.id === "comparison"
            ? { ...st, score: null, source: "pending" }
            : { ...st, score: null, source: "unmeasured" }
        )}
      />
    );

    expect(screen.getAllByText("Measurement in progress")).toHaveLength(2);
    expect(screen.getAllByText("No prompt data yet")).toHaveLength(3);
    expect(
      container.querySelector('[data-search-type="brand"]')?.getAttribute("data-measurement-state")
    ).toBe("pending");
    expect(
      container
        .querySelector('[data-search-type="category"]')
        ?.getAttribute("data-measurement-state")
    ).toBe("unmeasured");
    // A pending card still invents no figure.
    expect(screen.queryByText("61")).not.toBeInTheDocument();
  });

  it("never treats a pending label as a measurement, even with a score attached", () => {
    render(
      <SearchTypeFeeds searchTypes={searchTypes.map((st) => ({ ...st, source: "pending" }))} />
    );

    expect(screen.queryByText("61")).not.toBeInTheDocument();
    expect(screen.getAllByText("Measurement in progress")).toHaveLength(5);
  });

  it("refuses the retired derived estimate still present in older reports", () => {
    // Reports served before SIGV2-1105 carry a heuristic score tagged
    // "derived". The score is real data about something else, so it is not
    // shown under a search-type label.
    render(
      <SearchTypeFeeds searchTypes={searchTypes.map((st) => ({ ...st, source: "derived" }))} />
    );

    expect(screen.queryByText("61")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not measured")).toHaveLength(5);
  });

  it("keeps the visibility panel anatomy, ring slot and compact suggestion buttons", () => {
    const { container } = render(
      <VisibilityPanels aioScore={61} seoScore={72} aioHref="/ai" seoHref="/seo" />
    );
    expect(container.querySelector('[data-panel="aio"] [data-panel-heading]')).toHaveClass(
      "pb-3.5",
      "border-b"
    );
    expect(container.querySelector('[data-panel="aio"] [data-panel-body]')).toHaveClass(
      "gap-[30px]",
      "pt-[18px]",
      "items-center"
    );
    expect(container.querySelector('[data-panel="aio"] [data-score-gauge]')).toHaveClass(
      "w-[150px]"
    );
    expect(screen.getByRole("link", { name: "AIO improvement suggestions" })).toHaveClass(
      "leading-[normal]"
    );
    expect(screen.getByRole("link", { name: "AIO improvement suggestions" })).toHaveAttribute(
      "href",
      "/ai"
    );
    expect(screen.getByText("61")).toBeInTheDocument();
    expect(screen.getAllByText("No target set")).toHaveLength(2);
    // The two gaps that cannot be subtracted without a target, plus the AIO
    // appearance stat. The SEO panel's second stat was removed (SIGV2-1111),
    // and the target is the ring's own tag, not a row (SIGV2-1125).
    expect(screen.getAllByText("Not measured")).toHaveLength(3);
    expect(screen.queryByText("Score target")).not.toBeInTheDocument();
    expect(screen.queryByText("Search engine visibility")).not.toBeInTheDocument();
  });

  it("pins both actions to the bottom of a shared-height pair (SIGV2-1125)", () => {
    const { container } = render(
      <VisibilityPanels aioScore={61} seoScore={72} aioHref="/ai" seoHref="/seo" />
    );

    // The grid stretches both cards; `h-full` + `flex-1` hand the leftover
    // height to the body, so each ring centres on the full card and each
    // action sits on the same line as its neighbour's.
    for (const variant of ["aio", "seo"]) {
      expect(container.querySelector(`[data-panel="${variant}"]`)).toHaveClass("h-full", "flex");
      expect(container.querySelector(`[data-panel="${variant}"] [data-panel-body]`)).toHaveClass(
        "flex-1",
        "items-center"
      );
      expect(container.querySelector(`[data-panel="${variant}"] [data-panel-action]`)).toHaveClass(
        "mt-auto"
      );
    }
  });

  it("gives each pillar its own room-to-improvement sentence", () => {
    render(<VisibilityPanels aioScore={61} seoScore={72} aioHref="/ai" seoHref="/seo" />);

    expect(screen.getAllByText("Room to improvement")).toHaveLength(2);
    expect(
      screen.getByText(
        "Your website is not showing up often in AI generated answers. The fixes below move this the most."
      )
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your website is not ranking as well as it could in Google search results. The fixes below move this the most."
      )
    ).toBeInTheDocument();
  });

  it("shows the persisted score targets when the project has them", () => {
    render(
      <VisibilityPanels
        aioScore={61}
        seoScore={72}
        aioTarget={78}
        seoTarget={85}
        aioHref="/ai"
        seoHref="/seo"
      />
    );
    // The approved card carries the target on the ring's own tag, so that is
    // the only place it appears (SIGV2-1125).
    expect(screen.getByText("Target 78")).toBeInTheDocument();
    expect(screen.getByText("Target 85")).toBeInTheDocument();
    // Only the AIO appearance stat is left unmeasured once both targets exist.
    expect(screen.getAllByText("Not measured")).toHaveLength(1);
  });

  it("subtracts the gap to target from the two values already on the card", () => {
    const { container } = render(
      <VisibilityPanels
        aioScore={61}
        seoScore={72}
        aioTarget={78}
        seoTarget={85}
        aioHref="/ai"
        seoHref="/seo"
      />
    );

    expect(screen.getAllByText("Gap to target")).toHaveLength(2);
    expect(
      container.querySelector('[data-panel="aio"] [data-stat="gapToTarget"]')?.textContent
    ).toContain("17 pts");
    expect(
      container.querySelector('[data-panel="seo"] [data-stat="gapToTarget"]')?.textContent
    ).toContain("13 pts");
  });

  it("says At target rather than a negative gap once the score passes it", () => {
    const { container } = render(
      <VisibilityPanels
        aioScore={80}
        seoScore={85}
        aioTarget={78}
        seoTarget={85}
        aioHref="/ai"
        seoHref="/seo"
      />
    );

    expect(
      container.querySelector('[data-panel="aio"] [data-stat="gapToTarget"]')?.textContent
    ).toContain("At target");
    expect(
      container.querySelector('[data-panel="seo"] [data-stat="gapToTarget"]')?.textContent
    ).toContain("At target");
  });
});
