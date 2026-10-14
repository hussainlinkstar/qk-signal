import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import DashboardCompetitorsPage from "@/app/(app)/dashboard/competitors/page";

vi.mock("@/components/dashboard/ProjectRouteBridge", () => ({
  default: ({ moduleLabel }: { moduleLabel: string }) => (
    <div>Project Route Bridge Stub: {moduleLabel}</div>
  ),
}));

// The legacy /dashboard/entities bridge is no longer one of these: SIGV2-1196
// gives it the SOON treatment the sidebar already shows, covered by
// entities/page.test.tsx.
describe("dashboard legacy route bridges", () => {
  it("routes legacy dashboard modules through the project bridge", () => {
    render(<DashboardCompetitorsPage />);
    expect(
      screen.getByText("Project Route Bridge Stub: Competitor Intelligence")
    ).toBeInTheDocument();
  });
});
