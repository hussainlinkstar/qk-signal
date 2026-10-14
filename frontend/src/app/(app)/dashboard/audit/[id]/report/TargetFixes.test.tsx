import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TargetFixes from "@/app/(app)/dashboard/audit/[id]/report/TargetFixes";
import { tEn } from "@/test/i18nEn";
import type { ConsolidatedFix } from "@/lib/reportAdapters";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

// ---------------------------------------------------------------------------
// SIGV2-1218: this shortlist summed `impactValue` across its three rows and
// printed "+N pts" plus a projected destination score ("72 -> 85").
//
// SIGV2-1211 had already withdrawn the per-item predicted point gain from the
// Improve tabs, these same fix rows and the locked-plan preview, because a
// predicted gain is a promise about a future measurement the product cannot
// keep. Summing three of those withdrawn figures and naming a destination
// score is the stronger version of the same claim, so it goes too. What is
// left is the honest part: which three actions to do first, in order.
// ---------------------------------------------------------------------------

const fix = (overrides: Partial<ConsolidatedFix> = {}): ConsolidatedFix => ({
  id: "fix-1",
  rank: 1,
  title: "Set a canonical link element",
  description: "Duplicate URLs split ranking signals.",
  category: "Technical",
  impact: "Critical",
  engines: ["SEO"],
  // SIGV2-1193: a row always knows which channel raised it.
  sources: ["audit_finding"],
  impactLevel: { measured: false, level: null },
  effortLevel: { measured: false, level: null },
  pillars: [],
  groundedBy: [],
  actionText: null,
  ...overrides,
});

const fixes: ConsolidatedFix[] = [
  fix({ title: "First fix", impactValue: -8 }),
  fix({ title: "Second fix", impactValue: -3 }),
  fix({ title: "Third fix", impactValue: -2 }),
  fix({ title: "Fourth fix", impactValue: -1 }),
];

describe("audit report TargetFixes", () => {
  it("projects no destination score and sums no point total", () => {
    const { container } = render(<TargetFixes fixes={fixes} />);

    // The summed gain was 13, the projected target 85 from a score of 72.
    expect(container.textContent).not.toContain("pts");
    expect(container.textContent).not.toMatch(/\+\s?\d/);
    expect(container.textContent).not.toMatch(/\d+\s*(pts?|points?)/i);
    expect(container.textContent).not.toContain("→");
    expect(container.textContent).not.toContain("85");
    expect(container.textContent).not.toContain("72");
    expect(container.textContent).not.toMatch(/target/i);
    expect(container.querySelector(".w-\\[250px\\], .sm\\:w-\\[250px\\]")).toBeNull();
  });

  it("keeps the three highest-priority fixes, in the order it was given them", () => {
    render(<TargetFixes fixes={fixes} />);

    const titles = screen
      .getAllByRole("heading", { level: 3 })
      .map((heading) => heading.textContent);
    expect(titles).toEqual(["First fix", "Second fix", "Third fix"]);
    expect(screen.queryByText("Fourth fix")).toBeNull();
  });

  it("heads the shortlist with the count it is actually showing", () => {
    render(<TargetFixes fixes={fixes} />);

    // The old heading interpolated the PROJECTED SCORE into its count slot,
    // so a three-row list was titled "(85)".
    expect(
      screen.getByRole("heading", { level: 2, name: "Start with these (3)" })
    ).toBeInTheDocument();
  });

  it("states each fix's impact as the category SIGV2-1211 settled on", () => {
    render(<TargetFixes fixes={fixes.slice(0, 1)} />);

    expect(screen.getByText("Impact: Critical")).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Start with these (1)" })).toBeVisible();
  });

  it("renders nothing when there is no fix to prioritise", () => {
    const { container } = render(<TargetFixes fixes={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
