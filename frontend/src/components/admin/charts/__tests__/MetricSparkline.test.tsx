import React from "react";
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import MetricSparkline from "../MetricSparkline";

const sampleData = [
  { date: "2026-03-01", value: 10 },
  { date: "2026-03-02", value: 20 },
  { date: "2026-03-03", value: 15 },
];

describe("MetricSparkline", () => {
  it("renders without crashing when given valid data", () => {
    const { container } = render(<MetricSparkline data={sampleData} />);
    expect(container.firstChild).toBeTruthy();
  });

  it("returns null for insufficient data (< 2 points)", () => {
    const { container } = render(<MetricSparkline data={[{ date: "2026-03-01", value: 5 }]} />);
    expect(container.firstChild).toBeNull();
  });

  it("returns null for empty data", () => {
    const { container } = render(<MetricSparkline data={[]} />);
    expect(container.firstChild).toBeNull();
  });
});
