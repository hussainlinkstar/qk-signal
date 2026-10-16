import React from "react";
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrackedCompetitorsSection from "./TrackedCompetitorsSection";
import { fetchProjectCompetitors, fetchProjectById } from "@/services/workspaceService";

const authState = {
  isLoading: false,
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
  user: {
    subscription_plan: "plan_standard",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/services/workspaceService", () => ({
  createProjectCompetitor: vi.fn(),
  deleteProjectCompetitor: vi.fn(),
  fetchProjectById: vi.fn(),
  fetchProjectCompetitors: vi.fn(),
  updateProjectById: vi.fn(),
}));

describe("TrackedCompetitorsSection plan gate", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.user = { subscription_plan: "plan_standard" };
    vi.mocked(fetchProjectById).mockResolvedValue({} as never);
    vi.mocked(fetchProjectCompetitors).mockResolvedValue([] as never);
  });

  it("covers the whole card, heading included, with a single lock overlay", async () => {
    render(<TrackedCompetitorsSection projectId="42" />);

    const section = document.getElementById("competitors");
    expect(section).not.toBeNull();

    // The heading stays inside the covered card rather than floating sharp
    // above the blur.
    const heading = screen.getByText("signalProjectSettings.competitors.heading");
    expect(section).toContainElement(heading);

    // Exactly one overlay, positioned against the section itself.
    const overlayTitles = await screen.findAllByText(
      /Competitive Intelligence requires Specialist/i
    );
    expect(overlayTitles).toHaveLength(1);
    expect(section).toContainElement(overlayTitles[0]);
    expect(section?.className).toContain("relative");
    expect(section?.className).toContain("overflow-hidden");
  });

  it("renders the roster chips with no overlay on an eligible plan", async () => {
    authState.user = { subscription_plan: "plan_specialist" };
    render(<TrackedCompetitorsSection projectId="42" />);

    expect(await screen.findByRole("button", { name: "Add competitor" })).toBeInTheDocument();
    expect(
      screen.queryByText(/Competitive Intelligence requires Specialist/i)
    ).not.toBeInTheDocument();
  });
});
