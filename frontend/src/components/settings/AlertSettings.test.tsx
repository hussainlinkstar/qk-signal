import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AlertSettings from "@/components/settings/AlertSettings";
import { createAlertRule, deleteAlertRule, fetchAlertRules } from "@/services/alertRulesService";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
  },
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({ user: { email: "owner@example.com" } }),
}));

vi.mock("@/services/alertRulesService", () => ({
  fetchAlertRules: vi.fn(),
  createAlertRule: vi.fn(),
  updateAlertRule: vi.fn(),
  deleteAlertRule: vi.fn(),
}));

describe("AlertSettings", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchAlertRules).mockResolvedValue([
      {
        id: 1,
        project_id: 42,
        metric: "geo_score",
        condition: "below",
        threshold: 70,
        email_to: "owner@example.com",
        is_active: true,
        last_triggered_at: null,
        created_at: "2026-01-01T00:00:00.000Z",
        recent_logs: [],
      },
    ]);
  });

  it("shows a toast (not a native alert) when the email address is invalid", async () => {
    const alertSpy = vi.spyOn(window, "alert").mockImplementation(() => {});

    render(<AlertSettings projectId={42} />);

    fireEvent.click(await screen.findByRole("button", { name: /add rule/i }));
    fireEvent.change(screen.getByPlaceholderText("alert@example.com"), {
      target: { value: "not-an-email" },
    });
    fireEvent.click(screen.getByRole("button", { name: /save rule/i }));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith("Please enter a valid email address.");
    });
    expect(alertSpy).not.toHaveBeenCalled();
    expect(createAlertRule).not.toHaveBeenCalled();

    alertSpy.mockRestore();
  });

  it("shows the confirm dialog before deleting a rule, and only deletes after confirming", async () => {
    vi.mocked(deleteAlertRule).mockResolvedValue();
    const confirmSpy = vi.spyOn(window, "confirm").mockImplementation(() => true);

    render(<AlertSettings projectId={42} />);

    fireEvent.click(await screen.findByTitle("Delete rule"));

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(await screen.findByText("Confirm Deletion")).toBeInTheDocument();
    expect(deleteAlertRule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /confirm delete/i }));

    await waitFor(() => {
      expect(deleteAlertRule).toHaveBeenCalledWith(42, 1);
    });
    await waitFor(() => {
      expect(screen.queryByText("Confirm Deletion")).not.toBeInTheDocument();
    });

    confirmSpy.mockRestore();
  });
});
