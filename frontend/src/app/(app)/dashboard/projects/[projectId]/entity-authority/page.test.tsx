import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ProjectEntityAuthorityPage from "@/app/(app)/dashboard/projects/[projectId]/entity-authority/page";

describe("ProjectEntityAuthorityPage route", () => {
  it("carries the SOON treatment instead of the entity authority report", async () => {
    const params = Promise.resolve({ projectId: "proj_01test" });
    render(await ProjectEntityAuthorityPage({ params }));

    expect(screen.getByRole("region", { name: "Entity Authority, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Entity Authority is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // The real entity scoring, gap analysis and entity tables never render,
    // so nothing invites a customer to configure or consume authority data
    // from a surface the project sidebar does not list.
    expect(screen.queryByText(/Entity Authority requires/i)).toBeNull();
    expect(screen.queryByText(/Upgrade to Specialist/i)).toBeNull();
    expect(screen.queryByText(/Add to Content Plan/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /Upgrade to Specialist/i })).toBeNull();
  });

  it("never dresses the unbuilt module as a plan upsell", async () => {
    const params = Promise.resolve({ projectId: "proj_01test" });
    const { container } = render(await ProjectEntityAuthorityPage({ params }));

    expect(container.textContent ?? "").not.toMatch(
      /upgrade|unlock|locked|plan|specialist|executive|price|\$/i
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
