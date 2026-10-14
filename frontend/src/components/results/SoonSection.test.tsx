import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import SoonSection from "@/components/results/SoonSection";

describe("SoonSection", () => {
  it("announces the section as coming soon and hides the blurred preview from screen readers", () => {
    render(
      <SoonSection
        title="Tracked keywords"
        note="Keyword positions are not built yet."
        preview={<p>fabricated preview copy</p>}
      />
    );

    expect(screen.getByRole("region", { name: "Tracked keywords, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(screen.getByText("Keyword positions are not built yet.")).toBeVisible();

    const preview = screen.getByTestId("soon-section-preview");
    expect(preview).toHaveAttribute("aria-hidden", "true");
    expect(preview).toHaveAttribute("inert");
    // The fake content is present as decoration only, never as announced text:
    // its nearest aria-hidden ancestor is the preview wrapper itself.
    expect(screen.getByText("fabricated preview copy").closest("[aria-hidden='true']")).toBe(
      preview
    );
  });

  it("blurs and fades the preview instead of rendering it as real content", () => {
    render(<SoonSection title="Prompts we test" preview={<p>preview</p>} />);

    const preview = screen.getByTestId("soon-section-preview");
    expect(preview).toHaveClass("blur-[6px]");
    expect(preview).toHaveClass("opacity-40");
    expect(preview).toHaveClass("pointer-events-none");
  });

  it("makes the whole subtree non-interactive: nothing focusable, nothing clickable", () => {
    const onClick = vi.fn();
    render(
      <SoonSection
        title="Score targets"
        preview={
          <div>
            <button type="button" onClick={onClick}>
              Configure score targets
            </button>
            <a href="/dashboard/connections">Connect Search Console</a>
            <input aria-label="target" />
          </div>
        }
      />
    );

    // Nothing inside is exposed to assistive tech, so nothing is reachable by
    // role, and there is no control to activate.
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();

    // Every natively focusable child is taken out of the tab order, so Tab can
    // never land inside the preview even where `inert` is unsupported.
    const preview = screen.getByTestId("soon-section-preview");
    expect(preview).toHaveAttribute("inert");
    const focusable = Array.from(preview.querySelectorAll("button, a[href], input"));
    expect(focusable).toHaveLength(3);
    focusable.forEach((element) => expect(element).toHaveAttribute("tabindex", "-1"));
    expect(
      preview.querySelectorAll('[tabindex]:not([tabindex="-1"]), a[href]:not([tabindex])')
    ).toHaveLength(0);

    // Pointer input never reaches the preview in a browser (pointer-events-none
    // plus `inert`); jsdom implements neither, so the class contract above is
    // the guard and this asserts the overlay adds no handler of its own.
    const overlay = screen.getByText("SOON").parentElement as HTMLElement;
    expect(overlay).toHaveClass("pointer-events-none");
    fireEvent.click(overlay);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("renders a neutral placeholder when no preview is supplied", () => {
    render(<SoonSection title="Monitoring summary" />);

    const preview = screen.getByTestId("soon-section-preview");
    expect(preview).toBeInTheDocument();
    expect(preview.textContent).toBe("");
  });

  it("never dresses an unbuilt feature as a plan upsell", () => {
    const { container } = render(<SoonSection title="Top pages and opportunities" />);

    const text = container.textContent ?? "";
    expect(text).not.toMatch(/upgrade|unlock|plan|specialist|executive|price|\$/i);
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
