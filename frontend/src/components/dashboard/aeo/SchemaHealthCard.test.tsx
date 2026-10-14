import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SchemaHealthCard from "@/components/dashboard/aeo/SchemaHealthCard";

describe("SchemaHealthCard", () => {
  it("renders actionable high-impact blockers using missing types and blockers data", () => {
    render(
      <SchemaHealthCard
        avgScore={82}
        healthyAudits={8}
        issueCount={3}
        coveragePercent={65}
        coverageByType={{ FAQPage: 80, Product: 40 }}
        missingHighImpactTypes={[{ type: "SoftwareApplication", count: 2, percentage: 50 }]}
        highImpactBlockers={[
          {
            type: "SoftwareApplication",
            severity: "critical",
            recommendation:
              "Add JSON-LD SoftwareApplication with name, operatingSystem, offers, and aggregateRating.",
          },
        ]}
      />
    );

    expect(screen.getByText("High-impact AI answers blockers")).toBeInTheDocument();
    expect(screen.getByText("Software Application")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Add JSON-LD SoftwareApplication with name, operatingSystem, offers, and aggregateRating."
      )
    ).toBeInTheDocument();
  });
});
