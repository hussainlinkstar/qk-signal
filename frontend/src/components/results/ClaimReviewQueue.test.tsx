import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ClaimReviewQueue from "@/components/results/ClaimReviewQueue";

const { fetchClaimReviewQueueMock, submitClaimReviewMock, toastSuccessMock, toastErrorMock } =
  vi.hoisted(() => ({
    fetchClaimReviewQueueMock: vi.fn(),
    submitClaimReviewMock: vi.fn(),
    toastSuccessMock: vi.fn(),
    toastErrorMock: vi.fn(),
  }));

vi.mock("sonner", () => ({
  toast: {
    success: (...args: unknown[]) => toastSuccessMock(...args),
    error: (...args: unknown[]) => toastErrorMock(...args),
  },
}));

vi.mock("@/services/claimReviewService", () => ({
  fetchClaimReviewQueue: (...args: unknown[]) => fetchClaimReviewQueueMock(...args),
  submitClaimReview: (...args: unknown[]) => submitClaimReviewMock(...args),
}));

const getAuthHeaders = vi.fn().mockResolvedValue({ Authorization: "Bearer token-123" });

const baseQueueResponse = {
  audit_id: 123,
  total_flagged: 2,
  reviewed: 0,
  approved_count: 0,
  refused_count: 0,
  pending: 2,
  can_review: true,
  claims: [
    {
      claim_id: "seo-12",
      domain: "seo",
      claim_text: "Add entity-backed FAQ blocks to the product pages.",
      current_disposition: "needs_manual_review" as const,
      confidence_score: 0.52,
      confidence_band: "contested",
      critique_reference: "Critic could not find enough evidence across the entity graph.",
      evidence_anchor_excerpt: {
        scores: { seo: 74, geo: 66 },
        critical_metrics: { pages_crawled: 18, entity_count: 3 },
      },
      reason_codes: ["unsupported_premise_ref"],
      problem_refs: ["seo-problem-1"],
      evidence_refs: ["faq-gap"],
      suggested_rewrite: "Limit the FAQ recommendation to pages with verified support content.",
      review_decision: null,
    },
    {
      claim_id: "geo-05",
      domain: "geo",
      claim_text: "Expand local landing pages for Bucharest and Cluj.",
      current_disposition: "manually_approved" as const,
      confidence_score: 0.61,
      confidence_band: "medium",
      critique_reference:
        "Agency validated the location recommendation against supported coverage.",
      evidence_anchor_excerpt: null,
      reason_codes: ["unsupported_location"],
      problem_refs: ["geo-problem-2"],
      evidence_refs: ["local-gap"],
      suggested_rewrite: null,
      review_decision: {
        id: 7,
        audit_id: 123,
        project_id: 22,
        claim_id: "geo-05",
        claim_domain: "geo",
        claim_text: "Expand local landing pages for Bucharest and Cluj.",
        original_disposition: "needs_manual_review",
        review_disposition: "manually_approved" as const,
        review_note: "Validated against the actual service-area plan.",
        reviewed_by_id: 9,
        reviewed_by_display_name: "maria",
        reviewed_at: "2026-03-16T10:45:00Z",
        schema_version: "1",
      },
    },
  ],
};

describe("ClaimReviewQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAuthHeaders.mockResolvedValue({ Authorization: "Bearer token-123" });
    fetchClaimReviewQueueMock.mockResolvedValue(baseQueueResponse);
    submitClaimReviewMock.mockResolvedValue({
      id: 1,
      audit_id: 123,
      project_id: 22,
      claim_id: "seo-12",
      claim_domain: "seo",
      claim_text: baseQueueResponse.claims[0].claim_text,
      original_disposition: "needs_manual_review",
      review_disposition: "manually_approved",
      review_note: "Validated by the strategist.",
      reviewed_by_id: 4,
      reviewed_by_display_name: "editor",
      reviewed_at: "2026-03-16T11:00:00Z",
      schema_version: "1",
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
  });

  it("filters the review queue by domain", async () => {
    render(<ClaimReviewQueue auditId={123} getAuthHeaders={getAuthHeaders} />);

    expect(await screen.findByText(/Add entity-backed FAQ blocks/i)).toBeInTheDocument();
    expect(screen.getByText(/Expand local landing pages/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Filter review queue by domain/i), {
      target: { value: "geo" },
    });

    expect(screen.queryByText(/Add entity-backed FAQ blocks/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Expand local landing pages/i)).toBeInTheDocument();
  });

  it("submits an approval and refreshes the queue summary", async () => {
    const onSummaryChange = vi.fn();
    fetchClaimReviewQueueMock.mockResolvedValueOnce(baseQueueResponse).mockResolvedValueOnce({
      ...baseQueueResponse,
      reviewed: 1,
      approved_count: 1,
      pending: 1,
      claims: [
        {
          ...baseQueueResponse.claims[0],
          current_disposition: "manually_approved" as const,
          review_decision: {
            id: 1,
            audit_id: 123,
            project_id: 22,
            claim_id: "seo-12",
            claim_domain: "seo",
            claim_text: baseQueueResponse.claims[0].claim_text,
            original_disposition: "needs_manual_review",
            review_disposition: "manually_approved" as const,
            review_note: "Validated by the strategist.",
            reviewed_by_id: 4,
            reviewed_by_display_name: "editor",
            reviewed_at: "2026-03-16T11:00:00Z",
            schema_version: "1",
          },
        },
        baseQueueResponse.claims[1],
      ],
    });

    render(
      <ClaimReviewQueue
        auditId={123}
        getAuthHeaders={getAuthHeaders}
        onSummaryChange={onSummaryChange}
      />
    );

    expect(await screen.findByText(/Add entity-backed FAQ blocks/i)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Review note for seo-12/i), {
      target: { value: "Validated by the strategist." },
    });
    fireEvent.click(screen.getAllByRole("button", { name: /Approve/i })[0]);

    await waitFor(() => {
      expect(submitClaimReviewMock).toHaveBeenCalledWith(
        123,
        "seo-12",
        {
          disposition: "manually_approved",
          note: "Validated by the strategist.",
        },
        { Authorization: "Bearer token-123" }
      );
    });

    await waitFor(() => {
      expect(onSummaryChange).toHaveBeenLastCalledWith(
        expect.objectContaining({
          approved_count: 1,
          pending_count: 1,
        })
      );
    });
    expect(toastSuccessMock).toHaveBeenCalled();
  });

  it("disables review actions when the queue is readonly", async () => {
    fetchClaimReviewQueueMock.mockResolvedValue({
      ...baseQueueResponse,
      can_review: false,
    });

    render(<ClaimReviewQueue auditId={123} getAuthHeaders={getAuthHeaders} />);

    expect(await screen.findByText(/Add entity-backed FAQ blocks/i)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Approve/i })[0]).toBeDisabled();
    expect(screen.getAllByRole("button", { name: /Refuse/i })[0]).toBeDisabled();
  });
});
