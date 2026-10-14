import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProjectAutomationsPage from "@/app/(app)/dashboard/projects/[projectId]/automations/page";

describe("ProjectAutomationsPage route", () => {
  it("carries the SOON treatment instead of the automations dashboard", async () => {
    const params = Promise.resolve({ projectId: "proj_01test" });
    render(await ProjectAutomationsPage({ params }));

    expect(screen.getByRole("region", { name: "Automations, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Automations is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // The real workflow engine, upgrade gate and modal never render, so
    // nothing invites a customer to create or manage automations from a
    // surface the sidebar does not list.
    expect(screen.queryByText(/Upgrade to Specialist/i)).toBeNull();
    expect(screen.queryByText(/New automation/i)).toBeNull();
    expect(screen.queryByText(/Notify team on SEO drop/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /Upgrade to Specialist/i })).toBeNull();
  });

  it("never dresses the unbuilt module as a plan upsell", async () => {
    const params = Promise.resolve({ projectId: "proj_01test" });
    const { container } = render(await ProjectAutomationsPage({ params }));

    expect(container.textContent ?? "").not.toMatch(
      /upgrade|unlock|locked|plan|specialist|executive|price|\$/i
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
