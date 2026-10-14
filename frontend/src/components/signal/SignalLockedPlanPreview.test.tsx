import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { LockedActPreview, LockedFixPreview } from "@/components/signal/SignalLockedPlanPreview";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

describe("LockedActPreview", () => {
  it("renders the approved row anatomy with illustrative copy", () => {
    const { container } = render(<LockedActPreview accent="blue" />);
    expect(container.querySelectorAll("h3").length).toBe(3);
  });

  // SIGV2-1211: this layer is shown to a customer whose plan cannot see the
  // real action list, so an illustrative "+8 PTS" was a number that traces to
  // nothing at all. The preview rates impact as a category, like the rows it
  // stands in for.
  it("shows no illustrative point gain", () => {
    const { container } = render(<LockedActPreview />);
    expect(container.textContent).not.toContain("PTS");
    expect(container.textContent).not.toMatch(/\+\s?\d/);
  });

  it("rates the illustrative rows categorically", () => {
    render(<LockedActPreview />);
    expect(screen.getAllByText("Impact: High").length).toBe(2);
    expect(screen.getByText("Impact: Medium")).toBeInTheDocument();
  });
});

describe("LockedFixPreview", () => {
  it("keeps the categorical impact chips and prints no figure", () => {
    const { container } = render(<LockedFixPreview />);
    expect(container.querySelectorAll("h3").length).toBe(3);
    expect(container.textContent).not.toContain("PTS");
    expect(container.textContent).not.toMatch(/\+\s?\d/);
  });
});
