import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuditAnnotationThread from "@/components/dashboard/AuditAnnotationThread";
import { createAuditAnnotation, fetchAuditAnnotations } from "@/services/annotationService";
import { fetchCurrentWorkspace } from "@/services/workspaceService";

const getTokenMock = vi.fn(async () => "token-123");

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    isSignedIn: true,
    getToken: getTokenMock,
    user: { id: "11" },
  }),
}));

vi.mock("@/services/annotationService", () => ({
  fetchAuditAnnotations: vi.fn(),
  createAuditAnnotation: vi.fn(),
  updateAuditAnnotation: vi.fn(),
  deleteAuditAnnotation: vi.fn(),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchCurrentWorkspace: vi.fn(),
}));

describe("AuditAnnotationThread", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchCurrentWorkspace).mockResolvedValue({
      id: 1,
      name: "Ops",
      owner_id: 11,
      created_at: null,
      role: "ADMIN",
      is_owner: true,
      project_count: 1,
      member_count: 1,
      oauth_connection_count: 0,
    } as never);
    vi.mocked(fetchAuditAnnotations).mockResolvedValue({
      items: [
        {
          id: 4,
          audit_id: 501,
          project_id: 42,
          user_id: 11,
          user_display_name: "owner",
          parent_id: null,
          section_path: "prioritized_actions[0]",
          source_recommendation_key: null,
          content: "Client-ready rollout note.",
          visibility: "client_visible",
          is_deleted: false,
          created_at: "2026-03-02T12:00:00Z",
          updated_at: null,
          can_edit: true,
          can_delete: true,
          replies: [],
        },
      ],
      page: 1,
      per_page: 50,
      total: 1,
      has_more: false,
    } as never);
    vi.mocked(createAuditAnnotation).mockResolvedValue({
      id: 5,
    } as never);
  });

  it("renders existing annotations and creates a new note", async () => {
    render(
      <AuditAnnotationThread
        auditId={501}
        sectionPath="prioritized_actions[0]"
        title="Expand comparison pages"
      />
    );

    expect(await screen.findByText(/Client-ready rollout note/i)).toBeInTheDocument();
    const textarea = await screen.findByLabelText("Annotation content");

    fireEvent.change(textarea, {
      target: { value: "Publish this in the next client update." },
    });
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Add annotation/i })).toBeEnabled();
    });
    fireEvent.click(screen.getByRole("button", { name: /Add annotation/i }));

    await waitFor(() => {
      expect(createAuditAnnotation).toHaveBeenCalledWith(
        501,
        expect.objectContaining({
          section_path: "prioritized_actions[0]",
          content: "Publish this in the next client update.",
        }),
        { Authorization: "Bearer token-123" }
      );
    });
  });

  it("renders a viewer lock when write access is disabled", async () => {
    vi.mocked(fetchCurrentWorkspace).mockResolvedValue({
      id: 1,
      name: "Ops",
      owner_id: 11,
      created_at: null,
      role: "VIEWER",
      is_owner: false,
      project_count: 1,
      member_count: 1,
      oauth_connection_count: 0,
    } as never);
    vi.mocked(fetchAuditAnnotations).mockResolvedValue({
      items: [],
      page: 1,
      per_page: 50,
      total: 0,
      has_more: false,
    } as never);

    render(
      <AuditAnnotationThread
        auditId={501}
        sectionPath="prioritized_actions[0]"
        title="Expand comparison pages"
      />
    );

    expect(await screen.findByText(/Viewer access can review threads/i)).toBeInTheDocument();
  });
});
