import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it } from "vitest";

import SignalBrandLockup from "@/components/signal/SignalBrandLockup";

describe("SignalBrandLockup", () => {
  it("renders the MVP lockup: qiko-logo.png at 21px plus the Signal word", () => {
    render(<SignalBrandLockup />);
    const logo = screen.getByAltText("Qiko");
    expect(logo.getAttribute("src")).toContain("qiko-logo.png");
    expect(logo).toHaveClass("h-[21px]", "w-auto");
    const word = screen.getByText("Signal");
    expect(word).toHaveClass(
      "font-(family-name:--disp)",
      "text-[16px]",
      "font-medium",
      "tracking-[-0.01em]",
      "text-(--t-3)"
    );
    expect(logo.parentElement).toHaveClass("gap-[9px]");
  });

  it("keeps the approved larger auth lockup via the auth size variant", () => {
    render(<SignalBrandLockup size="auth" />);
    const logo = screen.getByAltText("Qiko");
    expect(logo.getAttribute("src")).toContain("qiko-logo.png");
    expect(logo).toHaveAttribute("height", "32");
    expect(screen.getByText("Signal")).toHaveClass("text-[22px]");
    expect(logo.parentElement).toHaveClass("gap-[6px]");
  });

  it("lets a surface override the lockup word", () => {
    render(<SignalBrandLockup word="Admin" />);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
