import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import SignalXSell from "@/components/signal/SignalXSell";

const rows = [
  { label: "Organic", value: "+0.6 pp" },
  { label: "Direct", value: "-0.4 pp", negative: true },
];

function renderCard() {
  return render(
    <SignalXSell
      head="Sessions"
      question="What caused the drop?"
      body="Channel share change versus the previous period."
      rows={rows}
    >
      <div>4.8k</div>
    </SignalXSell>
  );
}

describe("SignalXSell", () => {
  it("renders hidden until the card is hovered or focused", () => {
    renderCard();
    const overlay = screen.getByRole("tooltip");
    expect(overlay).toHaveClass("opacity-0", "invisible");
    expect(overlay).toHaveTextContent("Sessions");
    expect(overlay).toHaveTextContent("Organic");
  });

  it("reveals on mouseenter and hides on mouseleave", () => {
    renderCard();
    const card = screen.getByRole("tooltip").parentElement as HTMLElement;
    fireEvent.mouseEnter(card);
    expect(screen.getByRole("tooltip")).toHaveClass("opacity-100");
    fireEvent.mouseLeave(card);
    expect(screen.getByRole("tooltip")).toHaveClass("opacity-0");
  });

  it("reveals on focus, hides on blur and on Escape", () => {
    renderCard();
    const card = screen.getByRole("tooltip").parentElement as HTMLElement;
    fireEvent.focus(card);
    expect(screen.getByRole("tooltip")).toHaveClass("opacity-100");
    fireEvent.keyDown(card, { key: "Escape" });
    expect(screen.getByRole("tooltip")).toHaveClass("opacity-0");
    fireEvent.focus(card);
    fireEvent.blur(card);
    expect(screen.getByRole("tooltip")).toHaveClass("opacity-0");
  });

  it("uses the approved dark-card classes", () => {
    renderCard();
    const overlay = screen.getByRole("tooltip");
    expect(overlay).toHaveClass("fixed", "w-[296px]", "rounded-[14px]", "bg-[#11151F]");
  });
});
