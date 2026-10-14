import React from "react";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import SmartCrawlExplanation from "../SmartCrawlExplanation";
import type { SmartCrawlReportData, PageTypeBreakdownEntry } from "../SmartCrawlExplanation";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({}),
}));

const BASE_SMART_CRAWL: SmartCrawlReportData = {
  mode: "smart_sample",
  total_site_urls: 200,
  sampled_urls: 8,
  coverage_ratio: 0.04,
  page_type_distribution: {
    blog_article: 100,
    product: 50,
    homepage: 1,
    faq: 10,
  },
  extrapolated_issues: [],
  extrapolation_note:
    "This smart crawl audited 8 representative pages out of 200 total site pages.",
};

const PAGE_TYPE_BREAKDOWN: Record<string, PageTypeBreakdownEntry> = {
  blog_article: {
    count: 3,
    avg_geo: 65,
    avg_seo: 72,
    avg_aeo: 58,
    avg_overall: 65,
  },
  product: {
    count: 2,
    avg_geo: 80,
    avg_seo: 85,
    avg_aeo: 70,
    avg_overall: 78,
  },
  homepage: {
    count: 1,
    avg_geo: 90,
    avg_seo: 88,
    avg_aeo: 82,
    avg_overall: 87,
  },
};

describe("SmartCrawlExplanation", () => {
  it("renders coverage summary stats", () => {
    render(
      <SmartCrawlExplanation
        smartCrawl={BASE_SMART_CRAWL}
        pageTypeBreakdown={PAGE_TYPE_BREAKDOWN}
      />
    );

    expect(screen.getByText("Smart Crawl Analysis")).toBeInTheDocument();
    expect(screen.getByText("8 / 200")).toBeInTheDocument(); // Pages sampled
    expect(screen.getByText("4% of site")).toBeInTheDocument();
  });

  it("renders page type breakdown table", () => {
    render(
      <SmartCrawlExplanation
        smartCrawl={BASE_SMART_CRAWL}
        pageTypeBreakdown={PAGE_TYPE_BREAKDOWN}
      />
    );

    expect(screen.getByText("Scores by Page Type")).toBeInTheDocument();
    expect(screen.getByText("blog article")).toBeInTheDocument();
    expect(screen.getByText("product")).toBeInTheDocument();
  });

  it("shows no-issues banner when no extrapolated issues", () => {
    render(
      <SmartCrawlExplanation
        smartCrawl={BASE_SMART_CRAWL}
        pageTypeBreakdown={PAGE_TYPE_BREAKDOWN}
      />
    );

    expect(screen.getByText("No critical issues projected across page types.")).toBeInTheDocument();
  });

  it("renders extrapolated issues with confidence badges", () => {
    const withIssues: SmartCrawlReportData = {
      ...BASE_SMART_CRAWL,
      extrapolated_issues: [
        {
          page_type: "blog_article",
          label: "Blog Post / Article",
          sampled: 3,
          estimated_total: 100,
          avg_score: 45,
          projected_affected_pages: 100,
          confidence: "high",
          insight:
            "Based on 3 sampled Blog Post / Article page(s) (avg score: 45.0/100), an estimated 100 pages of this type likely share similar issues.",
        },
      ],
    };

    render(
      <SmartCrawlExplanation smartCrawl={withIssues} pageTypeBreakdown={PAGE_TYPE_BREAKDOWN} />
    );

    expect(screen.getByText("Projected Site-wide Issues")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText(/100 estimated total/)).toBeInTheDocument();
  });

  it("renders extrapolation note", () => {
    render(
      <SmartCrawlExplanation
        smartCrawl={BASE_SMART_CRAWL}
        pageTypeBreakdown={PAGE_TYPE_BREAKDOWN}
      />
    );

    expect(screen.getByText(BASE_SMART_CRAWL.extrapolation_note)).toBeInTheDocument();
  });

  it("handles null pageTypeBreakdown gracefully", () => {
    render(<SmartCrawlExplanation smartCrawl={BASE_SMART_CRAWL} pageTypeBreakdown={null} />);

    // Should still render without crashing
    expect(screen.getByText("Smart Crawl Analysis")).toBeInTheDocument();
    // Table should not render
    expect(screen.queryByText("Scores by Page Type")).not.toBeInTheDocument();
  });

  it("calculates type diversity percentage correctly", () => {
    // 3 sampled types out of 4 total = 75%
    render(
      <SmartCrawlExplanation
        smartCrawl={BASE_SMART_CRAWL}
        pageTypeBreakdown={PAGE_TYPE_BREAKDOWN}
      />
    );

    expect(screen.getByText("3 / 4")).toBeInTheDocument();
    expect(screen.getByText("75% type diversity")).toBeInTheDocument();
  });
});
