import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import FixRow from "@/app/(app)/dashboard/audit/[id]/report/FixRow";
import { tEn } from "@/test/i18nEn";
import type { ConsolidatedFix } from "@/lib/reportAdapters";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

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

describe("audit report FixRow", () => {
  it("states impact as a category only", () => {
    render(<FixRow fix={fix({ impactValue: -15 })} />);
    expect(screen.getByText("Impact: Critical")).toBeInTheDocument();
  });

  // SIGV2-1211: the row already carries a categorical impact chip, so the
  // numeric badge was a second, competing impact statement, and the figure it
  // printed was a predicted gain rather than anything measured.
  it("prints no predicted point gain beside the fix", () => {
    const { container } = render(<FixRow fix={fix({ impactValue: -15 })} />);
    expect(container.textContent).not.toContain("PTS");
    expect(container.textContent).not.toMatch(/\+\s?\d/);
    expect(container.textContent).not.toMatch(/\d+\s*(pts?|points?)/i);
  });

  it("prints no figure for a fix that carries no numeric deduction either", () => {
    const { container } = render(<FixRow fix={fix({ impact: "Optimization" })} />);
    expect(screen.getByText("Impact: Optimization")).toBeInTheDocument();
    expect(container.textContent).not.toContain("PTS");
  });

  // SIGV2-1193: the audit's findings and the action plan are one list now, so
  // the row says which channel raised it. The customer keeps the answer
  // SIGV2-1175 gave them; it just moved from the list onto the row.
  it("names the channel that raised the fix", () => {
    render(<FixRow fix={fix()} />);
    expect(screen.getByText("From the audit")).toBeInTheDocument();
  });

  it("names both channels when both raised the same problem", () => {
    const { container } = render(
      <FixRow fix={fix({ sources: ["action_plan", "audit_finding"], impactValue: -15 })} />
    );
    expect(screen.getByText("From your action plan")).toBeInTheDocument();
    expect(screen.getByText("From the audit")).toBeInTheDocument();
    // Still no number, on a row that carries one.
    expect(container.textContent).not.toMatch(/\d+\s*(pts?|points?|%)/i);
  });
});
