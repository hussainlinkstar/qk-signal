import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import MetricLineChart from "../MetricLineChart";
import MetricBarChart from "../MetricBarChart";

const sampleData = [
  { date: "2026-03-01", value: 10 },
  { date: "2026-03-02", value: 20 },
  { date: "2026-03-03", value: 15 },
];

describe("MetricLineChart", () => {
  it("renders chart container for valid data", () => {
    const { container } = render(<MetricLineChart data={sampleData} label="Cost" />);
    expect(container.firstChild).toBeTruthy();
  });

  it("shows fallback message for empty data", () => {
    render(<MetricLineChart data={[]} label="Cost" />);
    expect(screen.getByText("Not enough data to display chart.")).toBeInTheDocument();
  });
});

describe("MetricBarChart", () => {
  it("renders chart container for valid data", () => {
    const { container } = render(<MetricBarChart data={sampleData} label="Assessments" />);
    expect(container.firstChild).toBeTruthy();
  });

  it("shows fallback message for empty data", () => {
    render(<MetricBarChart data={[]} label="Assessments" />);
    expect(screen.getByText("Not enough data to display chart.")).toBeInTheDocument();
  });
});
