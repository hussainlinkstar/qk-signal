import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignalHero from "@/components/signal/SignalHero";

describe("SignalHero mobile layout", () => {
  it("stacks gauge, copy, and target by default and restores the horizontal hero at md", () => {
    render(
      <SignalHero
        score={72}
        eyebrow="SEO score"
        title="Ranking in traditional search"
        description="Focused mobile behavior"
        target={{ now: 72, target: 85, note: "Close the highest-value gaps" }}
      />
    );

    const heading = screen.getByRole("heading", { name: "Ranking in traditional search" });
    const copy = heading.parentElement;
    const root = copy?.parentElement;
    expect(root).not.toBeNull();
    expect(root).toHaveClass("min-w-0", "flex-col", "gap-5", "p-5");
    expect(root).toHaveClass("md:flex-row", "md:items-center", "md:gap-[26px]", "md:p-[24px_28px]");

    const sections = Array.from(root!.children).filter(
      (element): element is HTMLElement =>
        element instanceof HTMLElement && element.tagName === "DIV"
    );
    expect(sections).toHaveLength(3);
    expect(sections[0]).toHaveClass("self-center", "md:self-auto", "flex-none");
    expect(sections[1]).toBe(copy);
    expect(sections[1]).toHaveClass("min-w-0", "flex-1");
    expect(sections[2]).toHaveClass("w-full", "md:w-[250px]", "flex-none");
  });
});
