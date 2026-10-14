import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import QueryHeatmap from "@/components/dashboard/aeo/QueryHeatmap";

describe("QueryHeatmap", () => {
  it("shows user-friendly labels", () => {
    render(
      <QueryHeatmap
        categories={[
          { query_type: "commercial_pricing", count: 4, percentage: 40 },
          { query_type: "instructional", count: 2, percentage: 20 },
        ]}
      />
    );

    expect(screen.getByText("Commercial · Pricing")).toBeInTheDocument();
    expect(screen.getByText("How-to / Instructional")).toBeInTheDocument();
  });

  it("renders categories in stable taxonomy order", () => {
    render(
      <QueryHeatmap
        categories={[
          { query_type: "commercial_comparison", count: 1, percentage: 10 },
          { query_type: "causal", count: 1, percentage: 10 },
          { query_type: "instructional", count: 1, percentage: 10 },
        ]}
      />
    );

    const labels = screen
      .getAllByText(/How-to \/ Instructional|Why \/ Causal|Commercial · Comparison/)
      .map((node) => node.textContent);
    expect(labels).toEqual(["How-to / Instructional", "Why / Causal", "Commercial · Comparison"]);
  });
});
