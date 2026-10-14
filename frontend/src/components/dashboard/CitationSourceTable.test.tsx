import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import CitationSourceTable from "@/components/dashboard/CitationSourceTable";

describe("CitationSourceTable", () => {
  it("maps trust score ranges to High, Medium and Low badges with semantic styling", () => {
    render(
      <CitationSourceTable
        sources={[
          { domain: "high.example", citation_count: 22, trust_score: 90, owner: "my_site" },
          { domain: "medium.example", citation_count: 14, trust_score: 63, owner: "competitor" },
          { domain: "low.example", citation_count: 3, trust_score: 29, owner: "other" },
        ]}
      />
    );

    const highBadge = screen.getByText("High");
    const mediumBadge = screen.getByText("Medium");
    const lowBadge = screen.getByText("Low");

    expect(highBadge).toHaveClass("border-emerald-400/40", "bg-emerald-500/15", "text-emerald-100");
    expect(mediumBadge).toHaveClass("border-amber-400/40", "bg-amber-500/15", "text-amber-100");
    expect(lowBadge).toHaveClass("border-rose-400/40", "bg-rose-500/15", "text-rose-100");

    expect(screen.getByText("90 / 100")).toBeInTheDocument();
    expect(screen.getByText("63 / 100")).toBeInTheDocument();
    expect(screen.getByText("29 / 100")).toBeInTheDocument();

    expect(highBadge).toHaveAttribute("title", "90 / 100");
    expect(mediumBadge).toHaveAttribute("title", "63 / 100");
    expect(lowBadge).toHaveAttribute("title", "29 / 100");
  });
});
