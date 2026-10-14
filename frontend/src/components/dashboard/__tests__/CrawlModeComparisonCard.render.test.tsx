import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import CrawlModeComparisonCard from "../CrawlModeComparisonCard";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({}),
}));

describe("CrawlModeComparisonCard", () => {
  it("renders the comparison table with both modes", () => {
    render(
      <CrawlModeComparisonCard recommendation={null} activeMode="smart" onSelectMode={() => {}} />
    );

    expect(screen.getByText("Smart Crawl vs Bulk Crawl")).toBeInTheDocument();
    expect(screen.getByText("Pages analyzed")).toBeInTheDocument();
    expect(screen.getByText("Scans")).toBeInTheDocument();
    expect(screen.getByText("Coverage")).toBeInTheDocument();
  });

  it("shows recommendation banner when recommendation is provided", () => {
    render(
      <CrawlModeComparisonCard
        recommendation={{
          recommended: "smart",
          reason: "Your site has 500+ pages",
        }}
        activeMode="smart"
        onSelectMode={() => {}}
      />
    );

    expect(screen.getByText(/Recommended:/)).toBeInTheDocument();
    expect(screen.getByText(/Your site has 500\+ pages/)).toBeInTheDocument();
  });

  it("hides recommendation banner when null", () => {
    render(
      <CrawlModeComparisonCard recommendation={null} activeMode="bulk" onSelectMode={() => {}} />
    );

    expect(screen.queryByText(/Recommended:/)).not.toBeInTheDocument();
  });

  it("highlights active mode column", () => {
    render(
      <CrawlModeComparisonCard recommendation={null} activeMode="bulk" onSelectMode={() => {}} />
    );

    // The Bulk Crawl header button should have the active styling class
    const bulkButton = screen.getByRole("button", {
      name: /Select Bulk Crawl mode/i,
    });
    expect(bulkButton.className).toContain("text-primary");
  });
});
