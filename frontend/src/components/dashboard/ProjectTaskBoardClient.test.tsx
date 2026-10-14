import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import ProjectTaskBoardClient from "@/components/dashboard/ProjectTaskBoardClient";
import {
  createProjectTask,
  deleteProjectTask,
  fetchProjectCmsConnections,
  fetchProjectCmsDeploymentLog,
  fetchProjectTaskImpact,
  fetchProjectTasks,
  previewTaskCmsChange,
  reorderProjectTasks,
  rollbackTaskCmsChange,
  pushTaskCmsChange,
  updateProjectTask,
} from "@/services/workspaceService";

const getTokenMock = vi.fn(async () => "token-123");

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    isSignedIn: true,
    isLoading: false,
    getToken: getTokenMock,
  }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchProjectTasks: vi.fn(),
  fetchProjectTaskImpact: vi.fn(),
  createProjectTask: vi.fn(),
  updateProjectTask: vi.fn(),
  deleteProjectTask: vi.fn(),
  reorderProjectTasks: vi.fn(),
  fetchProjectCmsConnections: vi.fn(),
  fetchProjectCmsDeploymentLog: vi.fn(),
  previewTaskCmsChange: vi.fn(),
  pushTaskCmsChange: vi.fn(),
  rollbackTaskCmsChange: vi.fn(),
}));

const editableBoard = {
  project_id: 42,
  workspace_id: 3,
  can_edit: true,
  latest_audit_id: 501,
  latest_audit_at: "2026-03-02T12:00:00Z",
  assignees: [
    {
      user_id: 11,
      email: "owner@example.com",
      role: "ADMIN",
      is_owner: true,
    },
  ],
  summary: {
    todo: 1,
    in_progress: 0,
    done: 0,
    unassigned: 1,
    audit_linked: 1,
    overdue: 0,
    validated: 0,
  },
  tasks: [
    {
      id: 9,
      project_id: 42,
      title: "Add schema markup",
      description: "Ship FAQ schema.",
      status: "todo",
      priority: "critical",
      origin: "audit_recommendation",
      category: "Technical",
      source_audit_id: 501,
      source_recommendation_key: "technical:add-schema",
      assigned_to_user_id: null,
      assignee: null,
      due_date: null,
      resolved_at: null,
      verified_at: null,
      verification_audit_id: null,
      resolution_source: null,
      sort_order: 100,
      created_at: "2026-03-02T12:00:00Z",
      updated_at: "2026-03-02T12:00:00Z",
    },
  ],
};

const impactPayload = {
  project_id: 42,
  summary: {
    resolved_count: 0,
    validated_count: 0,
    pending_validation_count: 0,
    strongest_metric: null,
    strongest_delta: null,
  },
  items: [],
};

describe("ProjectTaskBoardClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchProjectTasks).mockResolvedValue(editableBoard as never);
    vi.mocked(fetchProjectTaskImpact).mockResolvedValue(impactPayload as never);
    vi.mocked(createProjectTask).mockResolvedValue(editableBoard.tasks[0] as never);
    vi.mocked(updateProjectTask).mockResolvedValue(editableBoard.tasks[0] as never);
    vi.mocked(deleteProjectTask).mockResolvedValue(undefined as never);
    vi.mocked(reorderProjectTasks).mockResolvedValue(editableBoard as never);
    vi.mocked(fetchProjectCmsConnections).mockResolvedValue([] as never);
    vi.mocked(fetchProjectCmsDeploymentLog).mockResolvedValue([] as never);
    vi.mocked(previewTaskCmsChange).mockResolvedValue(undefined as never);
    vi.mocked(pushTaskCmsChange).mockResolvedValue(undefined as never);
    vi.mocked(rollbackTaskCmsChange).mockResolvedValue(undefined as never);
  });

  it("loads the board and creates a manual task", async () => {
    render(<ProjectTaskBoardClient projectId="42" />);

    await waitFor(() => {
      expect(document.body).toHaveTextContent(/native task board/i);
    });
    expect(document.body).toHaveTextContent(/add schema markup/i);

    fireEvent.change(screen.getByLabelText("Task Title"), {
      target: { value: "Prepare launch checklist" },
    });
    fireEvent.click(screen.getByRole("button", { name: /add task/i }));

    await waitFor(() => {
      expect(createProjectTask).toHaveBeenCalledWith(
        "42",
        expect.objectContaining({ title: "Prepare launch checklist" }),
        expect.objectContaining({ Authorization: "Bearer token-123" })
      );
    });
  });

  it("renders a read-only state when editing is disabled", async () => {
    vi.mocked(fetchProjectTasks).mockResolvedValue({
      ...editableBoard,
      can_edit: false,
    } as never);

    render(<ProjectTaskBoardClient projectId="42" />);

    await waitFor(() => {
      expect(document.body).toHaveTextContent(/read-only for your current workspace role/i);
    });
    expect(screen.getByRole("button", { name: /add task/i })).toBeDisabled();
  });

  it("preserves the project in the empty board audit link", async () => {
    vi.mocked(fetchProjectTasks).mockResolvedValue({
      ...editableBoard,
      latest_audit_id: null,
      latest_audit_at: null,
      tasks: [],
    } as never);

    render(<ProjectTaskBoardClient projectId="42" />);

    expect(await screen.findByRole("link", { name: /Run project audit/i })).toHaveAttribute(
      "href",
      "/dashboard/audit?projectId=42"
    );
  });
});
