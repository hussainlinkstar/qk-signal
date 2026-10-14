import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalAnnotationThread from "@/components/portal/PortalAnnotationThread";
import {
  createPortalAnnotationReply,
  fetchPortalAuditAnnotations,
} from "@/services/annotationService";

const getTokenMock = vi.fn(async () => "token-123");

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: getTokenMock,
  }),
}));

vi.mock("@/services/annotationService", () => ({
  fetchPortalAuditAnnotations: vi.fn(),
  createPortalAnnotationReply: vi.fn(),
}));

describe("PortalAnnotationThread", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchPortalAuditAnnotations).mockResolvedValue({
      items: [
        {
          id: 7,
          audit_id: 501,
          project_id: 42,
          user_id: 11,
          user_display_name: "agency",
          parent_id: null,
          section_path: "prioritized_actions[1]",
          source_recommendation_key: null,
          content: "This fix is scheduled for the next release train.",
          visibility: "client_visible",
          is_deleted: false,
          created_at: "2026-03-02T12:00:00Z",
          updated_at: null,
          can_edit: false,
          can_delete: false,
          replies: [],
        },
      ],
      page: 1,
      per_page: 50,
      total: 1,
      has_more: false,
    } as never);
    vi.mocked(createPortalAnnotationReply).mockResolvedValue({ id: 8 } as never);
  });

  it("renders the client-visible thread and sends a reply", async () => {
    render(
      <PortalAnnotationThread
        projectId={42}
        auditId={501}
        sectionPath="prioritized_actions[1]"
        title="Strengthen entity-backed FAQs"
        initialCount={1}
      />
    );

    expect(await screen.findByText(/scheduled for the next release train/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Reply/i }));
    fireEvent.change(screen.getByLabelText("Annotation content"), {
      target: { value: "Please keep us posted once QA is complete." },
    });
    fireEvent.click(screen.getByRole("button", { name: /Send reply/i }));

    await waitFor(() => {
      expect(createPortalAnnotationReply).toHaveBeenCalledWith(
        42,
        501,
        expect.objectContaining({
          parent_id: 7,
          section_path: "prioritized_actions[1]",
          content: "Please keep us posted once QA is complete.",
        }),
        { Authorization: "Bearer token-123" }
      );
    });
  });
});
