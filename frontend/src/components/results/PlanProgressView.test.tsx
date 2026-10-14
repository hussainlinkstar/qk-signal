import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import PlanProgressView from "@/components/results/PlanProgressView";

const authState = {
  getToken: vi.fn().mockResolvedValue("token-123"),
  isLoading: false,
  isSignedIn: true,
  user: {
    id: "1",
    email: "owner@example.com",
    name: "Owner Example",
    subscription_plan: "plan_standard",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/planProgressService", () => ({
  fetchAdvisorPlanProgress: vi.fn(),
}));

// SIGV2-1168: done-for-you execution was withdrawn, but this view is what the
// entitlement still gates, so its locked state must keep selling Executive
// with copy about plan progress, not execution.
describe("PlanProgressView locked state", () => {
  it("renders a coherent Executive upsell for a plan without the capability", async () => {
    render(<PlanProgressView projectId="42" />);

    expect(await screen.findByText("Available on Executive and above")).toBeInTheDocument();
    expect(screen.getByText(/Advisor action plan evolves across audits/i)).toBeInTheDocument();
    expect(screen.queryByText(/Done for you/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\$|CMS|Jira|Slack/)).not.toBeInTheDocument();
  });
});
