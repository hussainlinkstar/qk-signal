import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ScoreTargetsCard from "@/components/settings/ScoreTargetsCard";
import { fetchProjectById, updateProjectById } from "@/services/workspaceService";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const authState = {
  isLoading: false,
  isSignedIn: true,
  getToken: vi.fn(async () => "token-123"),
  user: {
    subscription_plan: "plan_specialist",
  },
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("@/services/workspaceService", () => ({
  fetchProjectById: vi.fn(),
  updateProjectById: vi.fn(),
}));

const projectWithTargets = {
  id: 7,
  workspace_id: 3,
  score_targets: {
    aio: { current: 61, target: 78, gap: 17, measured_at: "2026-10-01T00:00:00Z" },
    seo: { current: 72, target: 85, gap: 13, measured_at: "2026-10-01T00:00:00Z" },
  },
};

describe("ScoreTargetsCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.isLoading = false;
    authState.isSignedIn = true;
    vi.mocked(fetchProjectById).mockResolvedValue(projectWithTargets as never);
    vi.mocked(updateProjectById).mockResolvedValue(projectWithTargets as never);
  });

  it("renders sliders initialised to the resolved targets", async () => {
    render(<ScoreTargetsCard projectId={7} />);

    const aio = await screen.findByRole("slider", { name: /aio target/i });
    const seo = screen.getByRole("slider", { name: /seo target/i });
    expect(aio).toHaveValue("78");
    expect(seo).toHaveValue("85");
    expect(screen.getByText(/now 61/i)).toBeInTheDocument();
    expect(screen.getByText(/now 72/i)).toBeInTheDocument();
  });

  it("saves both score targets via the project PATCH", async () => {
    render(<ScoreTargetsCard projectId={7} />);

    const aio = await screen.findByRole("slider", { name: /aio target/i });
    fireEvent.change(aio, { target: { value: "82" } });

    fireEvent.click(screen.getByRole("button", { name: /save targets/i }));

    await waitFor(() =>
      expect(updateProjectById).toHaveBeenCalledWith(
        7,
        { aio_score_target: 82, seo_score_target: 85 },
        expect.anything()
      )
    );
  });

  it("reports honestly when no score has been measured", async () => {
    vi.mocked(fetchProjectById).mockResolvedValue({
      ...projectWithTargets,
      score_targets: {
        aio: { current: null, target: 78, gap: null, measured_at: null },
        seo: { current: null, target: 85, gap: null, measured_at: null },
      },
    } as never);

    render(<ScoreTargetsCard projectId={7} />);

    await screen.findByRole("slider", { name: /aio target/i });
    expect(screen.getAllByText(/not measured/i).length).toBe(2);
  });
});
