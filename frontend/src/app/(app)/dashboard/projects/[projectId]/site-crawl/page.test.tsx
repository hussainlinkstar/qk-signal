import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ProjectSiteCrawlPage from "@/app/(app)/dashboard/projects/[projectId]/site-crawl/page";

const mockUseParams = vi.fn();
const mockUseAuth = vi.fn();
const mockEstimateProjectSitemapCrawl = vi.fn();
const mockStartProjectSitemapCrawl = vi.fn();
const mockFetchSitemapCrawlStatus = vi.fn();
const mockFetchSitemapCrawlReport = vi.fn();
const mockEstimateSmartCrawl = vi.fn();
const mockStartSmartCrawl = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => mockUseParams(),
}));

vi.mock("@/contexts/AuthContext", () => ({
  useAuth: () => mockUseAuth(),
}));

vi.mock("@/services/workspaceService", () => ({
  estimateProjectSitemapCrawl: (...args: unknown[]) => mockEstimateProjectSitemapCrawl(...args),
  startProjectSitemapCrawl: (...args: unknown[]) => mockStartProjectSitemapCrawl(...args),
  fetchSitemapCrawlStatus: (...args: unknown[]) => mockFetchSitemapCrawlStatus(...args),
  fetchSitemapCrawlReport: (...args: unknown[]) => mockFetchSitemapCrawlReport(...args),
  // The page grew a smart-crawl path. Without these the module mock is
  // incomplete and the component throws before rendering anything.
  estimateSmartCrawl: (...args: unknown[]) => mockEstimateSmartCrawl(...args),
  startSmartCrawl: (...args: unknown[]) => mockStartSmartCrawl(...args),
}));

describe("ProjectSiteCrawlPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseParams.mockReturnValue({ projectId: "42" });
    mockUseAuth.mockReturnValue({
      getToken: async () => "token",
      isSignedIn: true,
      isLoading: false,
    });
    mockEstimateProjectSitemapCrawl.mockResolvedValue({
      url_count: 120,
    });
    mockStartProjectSitemapCrawl.mockResolvedValue({
      job_id: "crawl-1",
      status: "running",
      total_urls: 120,
    });
    mockFetchSitemapCrawlStatus.mockResolvedValue({
      id: "crawl-1",
      project_id: 42,
      user_id: 1,
      sitemap_url: "https://acme.test/sitemap.xml",
      status: "running",
      total_urls: 120,
      completed_urls: 4,
      failed_urls: 1,
      error: null,
      created_at: null,
      completed_at: null,
    });
    mockFetchSitemapCrawlReport.mockResolvedValue({
      id: "crawl-1",
      project_id: 42,
      status: "completed",
      report: {},
    });
  });

  it("estimates sitemap crawl cost", async () => {
    render(<ProjectSiteCrawlPage />);

    // The page defaults to Smart Crawl now. This test covers the sitemap path,
    // which still exists behind the Bulk Crawl tab.
    fireEvent.click(screen.getByRole("button", { name: "Bulk Crawl" }));

    fireEvent.change(screen.getByLabelText("Sitemap URL"), {
      target: { value: "https://acme.test/sitemap.xml" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Estimate Cost" }));

    // The sentence is interrupted by <strong> for the counts, so match on the
    // container's textContent rather than a single text node.
    expect(
      await screen.findByText(
        (_, node) => node?.textContent?.startsWith("Estimated crawl size:") ?? false
      )
    ).toBeTruthy();
    expect(mockEstimateProjectSitemapCrawl).toHaveBeenCalled();
  });

  it("starts crawl and shows running status", async () => {
    render(<ProjectSiteCrawlPage />);

    // Same as above: this asserts the sitemap service, which is the Bulk tab.
    fireEvent.click(screen.getByRole("button", { name: "Bulk Crawl" }));

    fireEvent.change(screen.getByLabelText("Sitemap URL"), {
      target: { value: "https://acme.test/sitemap.xml" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start Crawl" }));

    expect(await screen.findByText(/Status:/)).toBeInTheDocument();
    expect(screen.getByText("5 / 120 pages audited")).toBeInTheDocument();
    expect(mockStartProjectSitemapCrawl).toHaveBeenCalled();
  });
});
