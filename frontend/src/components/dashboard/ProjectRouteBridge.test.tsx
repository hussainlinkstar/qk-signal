import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectRouteBridge from "@/components/dashboard/ProjectRouteBridge";
import { fetchWorkspaceProjects } from "@/services/workspaceService";

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    isSignedIn: true,
    isLoading: false,
    getToken: vi.fn(async () => "token-123"),
  }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchWorkspaceProjects: vi.fn(),
}));

describe("ProjectRouteBridge", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    vi.mocked(fetchWorkspaceProjects).mockResolvedValue([
      { id: 42, name: "Client Project", domain_url: "https://client.example" },
    ] as never);
  });

  it("uses clear project routing copy", async () => {
    window.localStorage.setItem("active_workspace_id", "42");
    render(
      <ProjectRouteBridge
        moduleLabel="Competitor Intelligence"
        description="Open a project-specific intelligence view."
      />
    );

    await waitFor(() => {
      expect(fetchWorkspaceProjects).toHaveBeenCalledWith({
        Authorization: "Bearer token-123",
        "X-Workspace-Id": "42",
      });
    });

    expect(document.body).toHaveTextContent(/project routing/i);
    expect(document.body).toHaveTextContent(/active/i);
    expect(screen.queryByText("Select Targeted Node")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Authorization vector required for project access.")
    ).not.toBeInTheDocument();
  });
});
