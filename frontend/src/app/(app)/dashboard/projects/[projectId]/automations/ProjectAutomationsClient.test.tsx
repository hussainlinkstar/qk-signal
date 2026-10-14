import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { PageHeaderHarness } from "@/test/pageHeaderHarness";

const {
  fetchProjectWorkflows,
  createProjectWorkflow,
  updateProjectWorkflow,
  deleteProjectWorkflow,
  testProjectWorkflow,
  getTokenMock,
  toastSuccess,
  toastError,
  projectState,
} = vi.hoisted(() => ({
  fetchProjectWorkflows: vi.fn(),
  createProjectWorkflow: vi.fn(),
  updateProjectWorkflow: vi.fn(),
  deleteProjectWorkflow: vi.fn(),
  testProjectWorkflow: vi.fn(),
  getTokenMock: vi.fn().mockResolvedValue("token-123"),
  toastSuccess: vi.fn(),
  toastError: vi.fn(),
  projectState: {
    project: {
      feature_access: { automations: { allowed: true } },
    },
  },
}));

vi.mock("next/navigation", async () => {
  const actual = await vi.importActual<typeof import("next/navigation")>("next/navigation");
  return {
    ...actual,
    useParams: () => ({ projectId: "42" }),
  };
});

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ getToken: getTokenMock }),
}));

vi.mock("sonner", () => ({
  toast: { success: toastSuccess, error: toastError },
}));

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => ({
    project: projectState.project,
    latestAudit: null,
    loading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

vi.mock("@/services/workflowService", async () => {
  const actual = await vi.importActual<typeof import("@/services/workflowService")>(
    "@/services/workflowService"
  );
  return {
    ...actual,
    fetchProjectWorkflows: (...args: unknown[]) => fetchProjectWorkflows(...args),
    createProjectWorkflow: (...args: unknown[]) => createProjectWorkflow(...args),
    updateProjectWorkflow: (...args: unknown[]) => updateProjectWorkflow(...args),
    deleteProjectWorkflow: (...args: unknown[]) => deleteProjectWorkflow(...args),
    testProjectWorkflow: (...args: unknown[]) => testProjectWorkflow(...args),
  };
});

let ProjectAutomationsClient: React.ComponentType;

const sampleWorkflow = {
  id: 5,
  workspace_id: 1,
  project_id: 42,
  name: "Notify team on SEO drop",
  description: null,
  trigger_config: {
    type: "metric_threshold" as const,
    metric: "seo_score",
    condition: "below" as const,
    value: 70,
  },
  actions_config: [{ type: "send_slack" as const, config: { channel_id: "C123" } }],
  cooldown_minutes: 60,
  is_active: true,
  last_triggered_at: null,
  created_at: "2026-01-01T00:00:00.000Z",
  updated_at: "2026-01-01T00:00:00.000Z",
};

describe("ProjectAutomationsClient (real Workflow Automations engine, MVP visual style)", () => {
  beforeAll(async () => {
    const pageModule =
      await import("@/app/(app)/dashboard/projects/[projectId]/automations/ProjectAutomationsClient");
    ProjectAutomationsClient = pageModule.default;
  });

  beforeEach(() => {
    vi.clearAllMocks();
    getTokenMock.mockResolvedValue("token-123");
    projectState.project = { feature_access: { automations: { allowed: true } } };
    fetchProjectWorkflows.mockResolvedValue([sampleWorkflow]);
  });

  it("renders real automations with their real trigger and action summaries", async () => {
    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );

    expect(await screen.findByText("Notify team on SEO drop")).toBeInTheDocument();
    expect(screen.getByText(/SEO score drops below 70/)).toBeInTheDocument();
    expect(screen.getByText(/Send Slack message/)).toBeInTheDocument();
    expect(await screen.findByText("1 ACTIVE")).toBeInTheDocument();
  });

  it("pauses an active automation via the real updateProjectWorkflow call", async () => {
    updateProjectWorkflow.mockResolvedValue({ ...sampleWorkflow, is_active: false });

    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );
    await screen.findByText("Notify team on SEO drop");

    fireEvent.click(screen.getByRole("button", { name: /^Pause$/i }));

    await waitFor(() =>
      expect(updateProjectWorkflow).toHaveBeenCalledWith(
        "42",
        5,
        { is_active: false },
        { Authorization: "Bearer token-123" }
      )
    );
    expect(toastSuccess).toHaveBeenCalledWith("Automation paused.");
  });

  it("runs a test via the real testProjectWorkflow call", async () => {
    testProjectWorkflow.mockResolvedValue({
      run: {
        id: 1,
        workflow_id: 5,
        triggered_at: null,
        trigger_event: "manual_test",
        trigger_context: {},
        status: "success",
        action_results: [],
        completed_at: null,
      },
    });

    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );
    await screen.findByText("Notify team on SEO drop");

    fireEvent.click(screen.getByRole("button", { name: /^Test$/i }));

    await waitFor(() =>
      expect(testProjectWorkflow).toHaveBeenCalledWith(
        "42",
        5,
        {},
        { Authorization: "Bearer token-123" }
      )
    );
    expect(toastSuccess).toHaveBeenCalledWith("Test run success.");
  });

  it("requires a second click before deleting an automation", async () => {
    deleteProjectWorkflow.mockResolvedValue(undefined);

    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );
    await screen.findByText("Notify team on SEO drop");

    const deleteButton = screen.getByRole("button", { name: /^Delete$/i });
    fireEvent.click(deleteButton);
    expect(deleteProjectWorkflow).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /Confirm delete/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Confirm delete/i }));

    await waitFor(() =>
      expect(deleteProjectWorkflow).toHaveBeenCalledWith("42", 5, {
        Authorization: "Bearer token-123",
      })
    );
  });

  it("creates a new automation via the real createProjectWorkflow call", async () => {
    createProjectWorkflow.mockResolvedValue({ ...sampleWorkflow, id: 9, name: "New rule" });
    fetchProjectWorkflows
      .mockResolvedValueOnce([sampleWorkflow])
      .mockResolvedValueOnce([sampleWorkflow]);

    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );
    await screen.findByText("Notify team on SEO drop");

    fireEvent.click(screen.getByRole("button", { name: /New automation/i }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.change(within(dialog).getByPlaceholderText("Notify team on SEO drop"), {
      target: { value: "New rule" },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: /^Create automation$/i }));

    await waitFor(() => expect(createProjectWorkflow).toHaveBeenCalled());
    expect(createProjectWorkflow.mock.calls[0][0]).toBe("42");
    expect(createProjectWorkflow.mock.calls[0][1]).toMatchObject({ name: "New rule" });
    expect(toastSuccess).toHaveBeenCalledWith("Automation created.");
  });

  it("shows the Pro gate and never calls the workflow endpoints when locked", async () => {
    projectState.project = { feature_access: { automations: { allowed: false } } };

    render(
      <PageHeaderHarness>
        <ProjectAutomationsClient />
      </PageHeaderHarness>
    );

    expect(await screen.findByText("Specialist")).toBeInTheDocument();
    const gate = screen.getByRole("dialog", { name: "Automate the follow-up work" });
    expect(gate).toHaveAccessibleDescription(
      /Turn recommendations and score changes into real actions/i
    );
    expect(fetchProjectWorkflows).not.toHaveBeenCalled();

    // The page behind the gate is blurred and pointer-events:none while locked,
    // so the gate must not be dismissible: doing so used to strand the user on an
    // unreadable, non-interactive page. Upgrade and the fallback are the only exits.
    expect(within(gate).queryByRole("button", { name: /close/i })).not.toBeInTheDocument();
    expect(within(gate).queryByRole("button", { name: "Not now" })).not.toBeInTheDocument();
    expect(within(gate).getByRole("link", { name: "Upgrade to Specialist" })).toBeVisible();
    expect(within(gate).getByRole("link", { name: "Back to dashboard" })).toBeVisible();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Automate the follow-up work" })).toBeInTheDocument();
  });
});
