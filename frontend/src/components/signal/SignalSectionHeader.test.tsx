import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SignalSectionHeader from "@/components/signal/SignalSectionHeader";

describe("SignalSectionHeader", () => {
  it("renders the approved .sec row: h2, 1px .ln divider, .mini note, spacer", () => {
    const { container } = render(
      <SignalSectionHeader
        title="Top pages and opportunities across traditional search"
        note="measured audit signals"
      />
    );

    const heading = screen.getByRole("heading", {
      name: "Top pages and opportunities across traditional search",
    });
    const root = heading.parentElement!;

    // .sec: inline flex row with the approved 12px gap and wrap.
    expect(root).toHaveClass("flex", "items-center", "gap-3", "flex-wrap");
    // .sec h2: Satoshi 17px/800 (shared rule; detail pages override via titleClassName).
    expect(heading).toHaveClass(
      "font-(family-name:--disp)",
      "text-[17px]",
      "font-extrabold",
      "tracking-[-0.01em]"
    );
    // .ln: the vertical 1px --line-2 divider beside the title, not a hairline.
    const divider = heading.nextElementSibling as HTMLElement;
    expect(divider).toHaveClass("h-4", "w-px", "bg-(--line-2)");
    // .mini: 12.5px --t-3 body text, not mono.
    const note = screen.getByText("measured audit signals");
    expect(note).toHaveClass("text-[12.5px]", "text-(--t-3)");
    expect(note.className).not.toContain("font-mono");
    // The spacer pushes any action to the trailing edge.
    expect(divider.parentElement!.querySelector(".flex-1")).not.toBeNull();
  });

  it("keeps the GA source chip beside the title", () => {
    render(<SignalSectionHeader title="Top pages" gaSource="Google Analytics · GA4" />);
    const source = screen.getByText("Google Analytics · GA4");
    expect(source).toHaveClass("inline-flex", "text-[12.5px]");
  });
});
