import React from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BillingSuccessPage from "./page";

const auth = { isSignedIn: true, getToken: vi.fn(async () => "test-token") };

vi.mock("@/components/auth/custom-auth", () => ({ useAuth: () => auth }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("session_id=test-session"),
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (key: string) => key }) }));

describe("Billing activation alerts", () => {
  beforeEach(() => {
    auth.isSignedIn = true;
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("announces pending activation without claiming that the subscription is active", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ status: "pending" })));
    render(<BillingSuccessPage />);

    const message = await screen.findByText(
      "Finalizing activation. This should only take a moment."
    );
    expect(message.closest('[role="status"]')).toHaveAttribute("data-signal-alert", "info");
    expect(document.querySelector('[data-signal-alert="success"]')).toBeNull();
  });

  it("renders confirmed activation with the shared success treatment and preserves navigation", async () => {
    vi.mocked(fetch).mockResolvedValue(new Response(JSON.stringify({ status: "active" })));
    render(<BillingSuccessPage />);

    const message = await screen.findByText("Your subscription is active and ready to use.");
    const alert = message.closest('[role="status"]');
    expect(alert).toHaveAttribute("data-signal-alert", "success");
    expect(alert?.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("link", { name: "Go to billing overview" })).toHaveAttribute(
      "href",
      "/dashboard/billing"
    );
    expect(screen.getByText("Checkout session: test-session")).toBeInTheDocument();
  });

  it("keeps a failed verification visible as a danger alert", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Verification unavailable" }), { status: 503 })
    );
    render(<BillingSuccessPage />);

    const message = await screen.findByText("Verification unavailable");
    expect(message.closest('[role="alert"]')).toHaveAttribute("data-signal-alert", "danger");
  });

  it("uses a warning when activation times out", async () => {
    vi.useFakeTimers();
    vi.mocked(fetch).mockImplementation(() => new Promise(() => {}));
    render(<BillingSuccessPage />);
    await act(async () => {
      vi.advanceTimersByTime(60000);
    });

    expect(screen.getByRole("alert")).toHaveAttribute("data-signal-alert", "warning");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Activation is taking longer than expected."
    );
  });

  it("announces the sign-in requirement as a failure without making a billing request", () => {
    auth.isSignedIn = false;
    render(<BillingSuccessPage />);

    expect(screen.getByRole("alert")).toHaveAttribute("data-signal-alert", "danger");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sign in to verify your subscription activation."
    );
    expect(fetch).not.toHaveBeenCalled();
  });
});
