import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import TrialFeedbackPage from "./page";

const fetchMock = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ token: "trial-feedback-token" }),
}));

vi.mock("@/components/signal/SignalBrandLockup", () => ({
  default: () => <div>Logo</div>,
}));

describe("TrialFeedbackPage", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  it("loads a pending feedback request and submits the response", async () => {
    fetchMock
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          token: "trial-feedback-token",
          status: "pending",
          recipient_email: "trial@example.com",
          recipient_name: "Trial User",
          requested_by_name: "Qiko Signal Sales",
          trigger_reason: "trial_expired",
          trial_started_at: "2026-02-20T00:00:00+00:00",
          trial_ended_at: "2026-03-06T00:00:00+00:00",
          expires_at: "2026-04-20T00:00:00+00:00",
          submitted_at: null,
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          status: "submitted",
          submitted_at: "2026-03-08T10:00:00+00:00",
        }),
      });

    render(<TrialFeedbackPage />);

    expect(await screen.findByText("Tell us how the trial felt")).toBeInTheDocument();
    expect(await screen.findByText("trial@example.com")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rate 4 out of 5" }));
    fireEvent.change(screen.getByLabelText("What worked well?"), {
      target: { value: "Audit output was strong." },
    });
    fireEvent.change(screen.getByLabelText("What felt missing or confusing?"), {
      target: { value: "Needed more automations." },
    });
    fireEvent.change(screen.getByLabelText("What should we improve next?"), {
      target: { value: "Speed up onboarding." },
    });

    fireEvent.click(screen.getByRole("button", { name: "Submit Feedback" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("Feedback received")).toBeInTheDocument();
  });
});
