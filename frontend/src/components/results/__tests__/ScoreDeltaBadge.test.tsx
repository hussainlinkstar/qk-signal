import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { tEn } from "@/test/i18nEn";
import ScoreDeltaBadge from "@/components/results/ScoreDeltaBadge";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// Mock Tooltip to just render children
vi.mock("@/components/ui/Tooltip", () => ({
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("ScoreDeltaBadge", () => {
  it("renders nothing when delta is null", () => {
    const { container } = render(<ScoreDeltaBadge delta={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when delta is undefined", () => {
    const { container } = render(<ScoreDeltaBadge delta={undefined} />);
    expect(container.innerHTML).toBe("");
  });

  it("renders positive delta with green styling", () => {
    render(<ScoreDeltaBadge delta={10} direction="up" />);
    const badge = screen.getByText("+10");
    expect(badge.className).toContain("text-emerald-400");
  });

  it("renders negative delta with red styling", () => {
    render(<ScoreDeltaBadge delta={-8} direction="down" />);
    const badge = screen.getByText(/8/);
    expect(badge.className).toContain("text-red-400");
  });

  it("renders stable delta with slate styling", () => {
    render(<ScoreDeltaBadge delta={0.5} direction="stable" />);
    const badge = screen.getByText("No change");
    expect(badge.className).toContain("text-(--t-2)");
  });

  it("infers direction from delta when not provided", () => {
    render(<ScoreDeltaBadge delta={15} />);
    expect(screen.getByText("+15")).toBeTruthy();
  });

  it("infers down direction from negative delta", () => {
    render(<ScoreDeltaBadge delta={-5} />);
    expect(screen.getByText(/5/)).toBeTruthy();
  });

  it("rounds delta to nearest integer", () => {
    render(<ScoreDeltaBadge delta={7.8} direction="up" />);
    expect(screen.getByText("+8")).toBeTruthy();
  });

  it("applies sm size classes by default", () => {
    render(<ScoreDeltaBadge delta={5} direction="up" />);
    const badge = screen.getByText("+5");
    expect(badge.className).toContain("text-[10px]");
  });

  it("applies md size classes when specified", () => {
    render(<ScoreDeltaBadge delta={5} direction="up" size="md" />);
    const badge = screen.getByText("+5");
    expect(badge.className).toContain("text-xs");
  });

  it("applies custom className", () => {
    render(<ScoreDeltaBadge delta={3} direction="up" className="my-custom" />);
    const badge = screen.getByText("+3");
    expect(badge.className).toContain("my-custom");
  });
});
