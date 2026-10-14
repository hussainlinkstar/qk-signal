import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RoleModeProvider } from "@/contexts/RoleModeContext";
import RoleModeSwitcher from "@/components/app/RoleModeSwitcher";
import {
  fetchCurrentWorkspace,
  updateCurrentWorkspace,
  type WorkspaceSummary,
} from "@/services/workspaceService";

const { getTokenMock } = vi.hoisted(() => ({
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock, isSignedIn: true }),
}));

vi.mock("@/components/app/WorkspaceSwitcher", () => ({
  workspaceHeaders: () => ({ "X-Workspace-Id": "7" }),
}));

vi.mock("@/services/workspaceService", () => ({
  fetchCurrentWorkspace: vi.fn(),
  updateCurrentWorkspace: vi.fn(),
}));

vi.mock("sonner", () => ({
  toast: { error: vi.fn() },
}));

const fetchCurrentWorkspaceMock = vi.mocked(fetchCurrentWorkspace);
const updateCurrentWorkspaceMock = vi.mocked(updateCurrentWorkspace);

const buildWorkspace = (overrides: Partial<WorkspaceSummary> = {}): WorkspaceSummary => ({
  id: 7,
  name: "Acme",
  owner_id: 1,
  created_at: null,
  role: "ADMIN",
  is_owner: true,
  project_count: 0,
  member_count: 1,
  oauth_connection_count: 0,
  role_mode: "marketer",
  ...overrides,
});

describe("RoleModeProvider + RoleModeSwitcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getTokenMock.mockResolvedValue("token-123");
  });

  it("hydrates the active role mode from the current workspace", async () => {
    fetchCurrentWorkspaceMock.mockResolvedValue(buildWorkspace({ role_mode: "agency" }));

    render(
      <RoleModeProvider>
        <RoleModeSwitcher />
      </RoleModeProvider>
    );

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Agency" })).toHaveAttribute("aria-checked", "true")
    );
  });

  it("defaults to marketer when the workspace has no role_mode", async () => {
    fetchCurrentWorkspaceMock.mockResolvedValue(buildWorkspace({ role_mode: null }));

    render(
      <RoleModeProvider>
        <RoleModeSwitcher />
      </RoleModeProvider>
    );

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Marketer" })).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
  });

  it("persists the selected role via updateCurrentWorkspace and updates context optimistically", async () => {
    fetchCurrentWorkspaceMock.mockResolvedValue(buildWorkspace({ role_mode: "marketer" }));
    updateCurrentWorkspaceMock.mockResolvedValue(buildWorkspace({ role_mode: "specialist" }));

    render(
      <RoleModeProvider>
        <RoleModeSwitcher />
      </RoleModeProvider>
    );

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Marketer" })).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );

    fireEvent.click(screen.getByRole("radio", { name: "Specialist" }));

    await waitFor(() =>
      expect(updateCurrentWorkspaceMock).toHaveBeenCalledWith(
        { role_mode: "specialist" },
        expect.objectContaining({ Authorization: "Bearer token-123" })
      )
    );

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Specialist" })).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
  });

  it("rolls back the optimistic update when persistence fails", async () => {
    fetchCurrentWorkspaceMock.mockResolvedValue(buildWorkspace({ role_mode: "marketer" }));
    updateCurrentWorkspaceMock.mockRejectedValue(new Error("nope"));

    render(
      <RoleModeProvider>
        <RoleModeSwitcher />
      </RoleModeProvider>
    );

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Marketer" })).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );

    fireEvent.click(screen.getByRole("radio", { name: "Agency" }));

    await waitFor(() => expect(updateCurrentWorkspaceMock).toHaveBeenCalled());

    await waitFor(() =>
      expect(screen.getByRole("radio", { name: "Marketer" })).toHaveAttribute(
        "aria-checked",
        "true"
      )
    );
  });
});
