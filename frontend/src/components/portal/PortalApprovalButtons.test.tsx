import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PortalApprovalButtons } from "@/components/portal/PortalApprovalButtons";
import type { PortalApprovalInfo } from "@/services/portalService";

const mockSubmit = vi.fn();

vi.mock("@/services/portalService", () => ({
  submitRecommendationApproval: (...args: unknown[]) => mockSubmit(...args),
}));

describe("PortalApprovalButtons", () => {
  beforeEach(() => {
    mockSubmit.mockReset();
  });

  it("renders approve, reject, and defer buttons when no current approval", () => {
    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={null}
      />
    );

    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(screen.getByText("Defer")).toBeInTheDocument();
  });

  it("shows approval badge when approved and offers change button", () => {
    const approval: PortalApprovalInfo = {
      status: "approved",
      decided_at: "2026-03-20T10:00:00Z",
      note: null,
    };

    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={approval}
      />
    );

    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Change")).toBeInTheDocument();
    expect(screen.queryByText("Reject")).not.toBeInTheDocument();
  });

  it("shows rejected badge for rejected status", () => {
    const approval: PortalApprovalInfo = {
      status: "rejected",
      decided_at: "2026-03-20T10:00:00Z",
      note: "Not needed",
    };

    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={approval}
      />
    );

    expect(screen.getByText("Rejected")).toBeInTheDocument();
  });

  it("shows deferred badge for deferred status", () => {
    const approval: PortalApprovalInfo = {
      status: "deferred",
      decided_at: "2026-03-20T10:00:00Z",
      note: null,
    };

    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={approval}
      />
    );

    expect(screen.getByText("Deferred")).toBeInTheDocument();
  });

  it("reveals action buttons when Change is clicked", () => {
    const approval: PortalApprovalInfo = {
      status: "approved",
      decided_at: "2026-03-20T10:00:00Z",
      note: null,
    };

    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={approval}
      />
    );

    fireEvent.click(screen.getByText("Change"));
    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Reject")).toBeInTheDocument();
    expect(screen.getByText("Defer")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();
  });

  it("updates the rendered approval from the successful response", async () => {
    mockSubmit.mockResolvedValueOnce({
      id: 1,
      audit_id: 10,
      source_recommendation_key: "fix_titles",
      section_path: null,
      status: "approved",
      decided_at: "2026-03-20T10:00:00Z",
      note: null,
    });

    const onChange = vi.fn();
    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={null}
        onApprovalChange={onChange}
      />
    );

    fireEvent.click(screen.getByText("Approve"));

    await waitFor(() => {
      expect(screen.getByText("Approved")).toBeInTheDocument();
    });
    expect(screen.queryByText("Reject")).not.toBeInTheDocument();
    expect(mockSubmit).toHaveBeenCalledWith("42", 10, "fix_titles", "approved");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("shows an inline error and keeps the actions available when submission fails", async () => {
    mockSubmit.mockRejectedValueOnce(new Error("Approval service unavailable"));

    render(
      <PortalApprovalButtons
        projectId="42"
        auditId={10}
        recommendationKey="fix_titles"
        currentApproval={null}
      />
    );

    fireEvent.click(screen.getByText("Approve"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Approval service unavailable");
    expect(screen.getByText("Approve")).toBeEnabled();
    expect(screen.getByText("Reject")).toBeEnabled();
    expect(mockSubmit).toHaveBeenCalledTimes(1);
  });
});
