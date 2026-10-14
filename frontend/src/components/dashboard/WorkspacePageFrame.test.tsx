import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import {
  WorkspacePageHeaderContext,
  type WorkspacePageHeader,
} from "@/components/dashboard/workspacePageHeader";

describe("WorkspacePageFrame", () => {
  it("registers the workspace identity in the shared top bar", () => {
    const seen: WorkspacePageHeader[] = [];
    render(
      <WorkspacePageHeaderContext.Provider value={{ header: null, setHeader: (h) => seen.push(h) }}>
        <WorkspacePageFrame title="Agency Workspace" meta="3 projects">
          <div>Projects</div>
        </WorkspacePageFrame>
      </WorkspacePageHeaderContext.Provider>
    );

    // The title/meta render inside the shared .top bar (SignalTopBar), not a
    // second header; the frame only carries the approved .wrap padding.
    expect(seen).toContainEqual({ title: "Agency Workspace", meta: "3 projects" });
    expect(screen.getByText("Projects")).toBeInTheDocument();
    expect(screen.getByText("Projects").parentElement).toHaveClass(
      "flex-1",
      "pt-[18px]",
      "pb-3",
      "md:-mt-5",
      "md:-mb-3.5",
      "gap-[18px]"
    );
  });

  it("renders the canonical back link for workspace subpages", () => {
    render(
      <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
        <div>Settings</div>
      </WorkspacePageFrame>
    );

    expect(screen.getByRole("link", { name: "Back to Workspace Overview" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
  });
});
