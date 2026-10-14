import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import LeadsPage from "@/app/(app)/dashboard/leads/page";

describe("LeadsPage route", () => {
  it("carries the SOON treatment instead of the leads dashboard", async () => {
    render(await LeadsPage());

    expect(screen.getByRole("region", { name: "Leads, coming soon" })).toBeVisible();
    expect(screen.getByText("SOON")).toBeVisible();
    expect(
      screen.getByText("Leads is not built yet. It will show up here once it is ready.")
    ).toBeVisible();

    // The real leads table, embed keys and widget code never render, so
    // nothing invites a customer to create or manage capture widgets from a
    // surface the sidebar does not list.
    expect(screen.queryByText(/The Leads dashboard requires/i)).toBeNull();
    expect(screen.queryByText(/Upgrade to Specialist/i)).toBeNull();
    expect(screen.queryByText(/lead@example.com/i)).toBeNull();
    expect(screen.queryByRole("link", { name: /Upgrade to Specialist/i })).toBeNull();
  });

  it("never dresses the unbuilt module as a plan upsell", async () => {
    const { container } = render(await LeadsPage());

    expect(container.textContent ?? "").not.toMatch(
      /upgrade|unlock|locked|plan|specialist|executive|price|\$/i
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.querySelector("button")).toBeNull();
  });
});
