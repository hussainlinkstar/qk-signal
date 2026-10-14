import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import ProjectEntitiesPage from "@/app/(app)/dashboard/projects/[projectId]/entities/page";
import ProjectEntitiesClient from "@/app/(app)/dashboard/projects/[projectId]/entities/ProjectEntitiesClient";

vi.mock("@/hooks/useProjectLatestAudit", () => ({
  useProjectLatestAudit: () => ({
    loading: false,
    error: null,
    project: { id: 42, name: "Client Project" },
    latestAudit: {
      id: 101,
      audit_type: "DEEP",
      created_at: "2026-03-02T09:00:00.000Z",
      full_report: {
        entities: ["Brand Authority", "Service Page"],
        competitors: [{ name: "rival.example" }],
        suggestions: [
          {
            category: "semantic",
            title: "Expand topical coverage",
            action: "Add supporting entities to service pages.",
          },
        ],
      },
    },
  }),
}));

vi.mock("@/types/auditResult", () => ({
  isAuditResult: () => true,
}));

describe("ProjectEntitiesPage route", () => {
  const renderRoute = () => ProjectEntitiesPage({ params: Promise.resolve({ projectId: "42" }) });

  it("carries the SOON treatment instead of the entity feature", async () => {
    render(await renderRoute());

    expect(screen.getByRole("region", { name: "Entities, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Entities is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // None of the feature's own content renders, even though the audit data
    // behind it is available.
    expect(screen.queryByText("Detected Entities")).toBeNull();
    expect(screen.queryByText("Entity Surface")).toBeNull();
    expect(screen.queryByText("Competitor Coverage")).toBeNull();
    expect(screen.queryByText("Priority Semantic Roadmap")).toBeNull();
    expect(screen.queryByText("Brand Authority")).toBeNull();
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

describe("ProjectEntitiesClient", () => {
  it("replaces internal entity jargon with clear labels", () => {
    render(<ProjectEntitiesClient projectId="42" />);

    expect(screen.getByText("Detected Entities")).toBeInTheDocument();
    expect(screen.getByText("Tracked Competitors")).toBeInTheDocument();
    expect(screen.getByText("Priority Roadmap Items")).toBeInTheDocument();
    expect(screen.getByText("Competitor Coverage")).toBeInTheDocument();
    expect(screen.getByText("Audit Type:")).toBeInTheDocument();

    expect(screen.queryByText("Neural Entities")).not.toBeInTheDocument();
    expect(screen.queryByText("Semantic Vectors")).not.toBeInTheDocument();
    expect(screen.queryByText("Competitor Topology")).not.toBeInTheDocument();
    expect(screen.queryByText("Audit Vector:")).not.toBeInTheDocument();
  });
});
