import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ProjectDashboardLayout from "@/app/(app)/dashboard/projects/[projectId]/layout";

let pathnameState = "/dashboard/projects/42/seo";

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameState,
}));

describe("ProjectDashboardLayout", () => {
  beforeEach(() => {
    pathnameState = "/dashboard/projects/42/seo";
    window.scrollTo = vi.fn();
  });

  it("renders the active project page (chrome is owned by the workspace shell)", () => {
    render(
      <ProjectDashboardLayout>
        <div>Project page content</div>
      </ProjectDashboardLayout>
    );

    expect(screen.getByText("Project page content")).toBeInTheDocument();
    // The old three-pillar chrome must NOT be rendered by this layout anymore.
    expect(screen.queryByText("Project Snapshot")).not.toBeInTheDocument();
    expect(screen.queryByText("Analysis Modules")).not.toBeInTheDocument();
    expect(screen.queryByText("Execution Lanes")).not.toBeInTheDocument();
  });

  it("scrolls to the top when the active project module changes", () => {
    const { rerender } = render(
      <ProjectDashboardLayout>
        <div>Initial route content</div>
      </ProjectDashboardLayout>
    );

    vi.mocked(window.scrollTo).mockClear();
    pathnameState = "/dashboard/projects/42/aeo";

    rerender(
      <ProjectDashboardLayout>
        <div>Updated route content</div>
      </ProjectDashboardLayout>
    );

    expect(window.scrollTo).toHaveBeenCalledWith({ top: 0, left: 0, behavior: "auto" });
  });
});
