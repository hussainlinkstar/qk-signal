import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalProjectActions from "@/components/portal/PortalProjectActions";

const mockFetchHistory = vi.fn();
const mockDownloadPdf = vi.fn();

vi.mock("@/services/portalService", () => ({
  fetchPortalAuditHistory: (...args: unknown[]) => mockFetchHistory(...args),
  downloadPortalPdf: (...args: unknown[]) => mockDownloadPdf(...args),
  submitRecommendationApproval: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("PortalProjectActions", () => {
  beforeEach(() => {
    mockFetchHistory.mockReset();
    mockDownloadPdf.mockReset();
  });

  it("renders audit history toggle and download PDF button", () => {
    render(<PortalProjectActions projectId="42" auditId={10} />);

    expect(screen.getByText("Audit history")).toBeInTheDocument();
    expect(screen.getByText("Download PDF")).toBeInTheDocument();
  });

  it("hides PDF button when auditId is null", () => {
    render(<PortalProjectActions projectId="42" auditId={null} />);

    expect(screen.getByText("Audit history")).toBeInTheDocument();
    expect(screen.queryByText("Download PDF")).not.toBeInTheDocument();
  });

  it("loads and shows audit history on toggle", async () => {
    mockFetchHistory.mockResolvedValueOnce({
      items: [
        {
          id: 1,
          created_at: "2026-03-20T10:00:00Z",
          seo_score: 72,
          geo_score: 65,
          aeo_score: 80,
          status: "completed",
        },
      ],
      total: 1,
      page: 1,
      page_size: 10,
    });

    render(<PortalProjectActions projectId="42" auditId={10} />);

    fireEvent.click(screen.getByText("Audit history"));

    await waitFor(() => {
      expect(mockFetchHistory).toHaveBeenCalledWith("42", 1, 10);
    });

    await waitFor(() => {
      expect(screen.getByText("72")).toBeInTheDocument();
    });
  });

  it("shows a retryable error when audit history loading fails", async () => {
    mockFetchHistory.mockRejectedValueOnce(new Error("Service unavailable")).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      page_size: 10,
    });

    render(<PortalProjectActions projectId="42" auditId={10} />);
    fireEvent.click(screen.getByText("Audit history"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Failed to load audit history.");
    expect(screen.queryByText("No audit history yet.")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(mockFetchHistory).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("No audit history yet.")).toBeInTheDocument();
  });

  it("calls downloadPortalPdf on PDF button click", async () => {
    mockDownloadPdf.mockResolvedValueOnce(undefined);

    render(<PortalProjectActions projectId="42" auditId={10} />);
    fireEvent.click(screen.getByText("Download PDF"));

    await waitFor(() => {
      expect(mockDownloadPdf).toHaveBeenCalledWith("42", 10);
    });
  });
});
