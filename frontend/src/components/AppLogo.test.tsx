import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AppLogo from "@/components/AppLogo";

// SIGV2-1087: the old wordmark variants and the SVG-wrapped 1.38MB raster are
// gone. AppLogo renders the bare Qiko mark, the same asset
// SignalBrandLockup uses, and nothing else.
describe("AppLogo", () => {
  it("renders the Qiko mark on the approved lockup's own asset and rendering", () => {
    render(<AppLogo iconClassName="h-[21px] w-auto" />);

    const mark = screen.getByAltText("Qiko");
    // Unoptimized and 237x95, exactly as SignalBrandLockup renders it, so the
    // recorded in-app baselines do not move.
    expect(mark.getAttribute("src")).toContain("/qiko-logo.png");
    expect(mark.getAttribute("src")).not.toContain("/_next/image");
    expect(mark).toHaveAttribute("width", "237");
    expect(mark).toHaveAttribute("height", "95");
  });

  it("renders exactly one image: there is no second dark-variant copy", () => {
    const { container } = render(<AppLogo />);

    expect(container.querySelectorAll("img")).toHaveLength(1);
    // The retired `auto` variant rendered the same artwork twice and hid one
    // copy with `dark:hidden` / `hidden dark:block` (SIGV2-1087).
    expect(container.querySelector(".dark\\:hidden")).toBeNull();
  });
});
