import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import JiraExportModal from "@/components/dashboard/jira/JiraExportModal";

vi.mock("@/components/ui/Modal", () => ({
  default: ({ open, children }: { open: boolean; children: React.ReactNode }) =>
    open ? <div>{children}</div> : null,
}));

vi.mock("@/hooks/useJira", () => ({
  useJira: () => ({
    status: null,
    loading: true,
    exportIssue: vi.fn(),
    canExportToJira: true,
    initializeProject: vi.fn(),
  }),
}));

describe("JiraExportModal", () => {
  it("shows clear loading copy while Jira projects are loading", () => {
    render(
      <JiraExportModal
        open
        onClose={vi.fn()}
        projectId={42}
        defaultSummary="Improve FAQ coverage"
        defaultDescription="Add FAQ answers to core pages."
      />
    );

    expect(screen.getByText("Loading Jira projects...")).toBeInTheDocument();
    expect(screen.queryByText("Hydrating Project Matrix...")).not.toBeInTheDocument();
  });
});
