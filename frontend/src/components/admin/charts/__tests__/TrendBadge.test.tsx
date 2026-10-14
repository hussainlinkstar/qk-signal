import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TrendBadge from "../TrendBadge";

describe("TrendBadge", () => {
  it("shows positive change in green", () => {
    render(<TrendBadge changePct={25.3} />);
    const badge = screen.getByText("+25.3%");
    expect(badge).toBeInTheDocument();
  });

  it("shows negative change in red", () => {
    render(<TrendBadge changePct={-10.5} />);
    const badge = screen.getByText("-10.5%");
    expect(badge).toBeInTheDocument();
  });

  it("shows N/A when changePct is null", () => {
    render(<TrendBadge changePct={null} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("shows zero change", () => {
    render(<TrendBadge changePct={0} />);
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });

  it("accepts a custom label override", () => {
    render(<TrendBadge changePct={15} label="vs last month" />);
    expect(screen.getByText("vs last month")).toBeInTheDocument();
  });
});
