import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DashboardEntitiesPage from "@/app/(app)/dashboard/entities/page";

vi.mock("@/components/dashboard/ProjectRouteBridge", () => ({
  default: ({ moduleLabel }: { moduleLabel: string }) => (
    <div>Project Route Bridge Stub: {moduleLabel}</div>
  ),
}));

describe("DashboardEntitiesPage", () => {
  it("carries the SOON treatment instead of the entities module", () => {
    render(<DashboardEntitiesPage />);

    expect(screen.getByRole("region", { name: "Entities, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Entities is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // The module itself never renders: no project picker, no route into the
    // project entity pages.
    expect(screen.queryByText(/Project Route Bridge Stub/)).toBeNull();
    expect(screen.queryByText(/Select Project/i)).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("never dresses the unbuilt module as a plan upsell", () => {
    const { container } = render(<DashboardEntitiesPage />);

    expect(container.textContent ?? "").not.toMatch(
      /upgrade|unlock|locked|plan|specialist|executive|price|\$/i
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
