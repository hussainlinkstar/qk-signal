import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectTasksPage from "@/app/(app)/dashboard/projects/[projectId]/tasks/page";

vi.mock("@/components/dashboard/ProjectTaskBoardClient", () => ({
  default: () => <div>Project Task Board Stub</div>,
}));

describe("ProjectTasksPage route", () => {
  const renderRoute = () => ProjectTasksPage({ params: Promise.resolve({ projectId: "42" }) });

  it("carries the SOON treatment instead of the task board", async () => {
    render(await renderRoute());

    expect(screen.getByRole("region", { name: "Tasks, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Tasks is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // The board never renders, so nothing invites a customer to create,
    // reorder or deploy a task from a surface the sidebar calls unbuilt.
    expect(screen.queryByText("Project Task Board Stub")).toBeNull();
    expect(screen.queryByText("To Do")).toBeNull();
    expect(screen.queryByText("In Progress")).toBeNull();
    expect(screen.queryByText(/New Task/i)).toBeNull();
  });

  it("never dresses the unbuilt module as a plan upsell", async () => {
    const { container } = render(await renderRoute());

    expect(container.textContent ?? "").not.toMatch(
      /upgrade|unlock|locked|plan|specialist|executive|price|\$/i
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
