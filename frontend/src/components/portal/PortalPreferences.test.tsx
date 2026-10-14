import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PortalPreferencesCard from "@/components/portal/PortalPreferences";

const mockFetchPrefs = vi.fn();
const mockUpdatePrefs = vi.fn();

vi.mock("@/services/portalService", () => ({
  fetchPortalPreferences: (...args: unknown[]) => mockFetchPrefs(...args),
  updatePortalPreferences: (...args: unknown[]) => mockUpdatePrefs(...args),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

describe("PortalPreferencesCard", () => {
  beforeEach(() => {
    mockFetchPrefs.mockReset();
    mockUpdatePrefs.mockReset();
  });

  it("renders loading skeleton initially then preferences form", async () => {
    mockFetchPrefs.mockResolvedValueOnce({
      email_digest_frequency: "weekly",
      notify_on_new_audit: true,
    });

    render(<PortalPreferencesCard />);

    // After loading
    await waitFor(() => {
      expect(screen.getByText("Notification Preferences")).toBeInTheDocument();
    });

    expect(screen.getByLabelText("Email digest frequency")).toBeInTheDocument();
    expect(screen.getByText("Notify on new audit")).toBeInTheDocument();
  });

  it("loads and displays saved preferences", async () => {
    mockFetchPrefs.mockResolvedValueOnce({
      email_digest_frequency: "daily",
      notify_on_new_audit: false,
    });

    render(<PortalPreferencesCard />);

    await waitFor(() => {
      expect(screen.getByText("Notification Preferences")).toBeInTheDocument();
    });

    const select = screen.getByLabelText("Email digest frequency") as HTMLSelectElement;
    expect(select.value).toBe("daily");
  });

  it("calls updatePortalPreferences on save", async () => {
    mockFetchPrefs.mockResolvedValueOnce({
      email_digest_frequency: "weekly",
      notify_on_new_audit: true,
    });
    mockUpdatePrefs.mockResolvedValueOnce({});

    render(<PortalPreferencesCard />);

    await waitFor(() => {
      expect(screen.getByText("Notification Preferences")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockUpdatePrefs).toHaveBeenCalledWith({
        email_digest_frequency: "weekly",
        notify_on_new_audit: true,
      });
    });
  });

  it("updates digest frequency via select", async () => {
    mockFetchPrefs.mockResolvedValueOnce({
      email_digest_frequency: "weekly",
      notify_on_new_audit: true,
    });
    mockUpdatePrefs.mockResolvedValueOnce({});

    render(<PortalPreferencesCard />);

    await waitFor(() => {
      expect(screen.getByText("Notification Preferences")).toBeInTheDocument();
    });

    const select = screen.getByLabelText("Email digest frequency") as HTMLSelectElement;
    fireEvent.change(select, { target: { value: "monthly" } });
    expect(select.value).toBe("monthly");

    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      expect(mockUpdatePrefs).toHaveBeenCalledWith({
        email_digest_frequency: "monthly",
        notify_on_new_audit: true,
      });
    });
  });
});
