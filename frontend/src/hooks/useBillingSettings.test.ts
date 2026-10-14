import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useBillingSettings } from "@/hooks/useBillingSettings";

const navigationState = vi.hoisted(() => ({
  pathname: "/dashboard/billing",
  push: vi.fn(),
  getToken: vi.fn().mockResolvedValue("token-123"),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => navigationState.pathname,
  useRouter: () => ({ push: navigationState.push }),
}));

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => ({
    getToken: navigationState.getToken,
    isSignedIn: true,
    isLoading: false,
  }),
}));

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function billingOverviewResponse(): Response {
  return jsonResponse({
    plans: [],
    current_plan: null,
    status: null,
    billing_interval: "month",
    portal_available: false,
    credit_price_usd: 0.1,
    top_up_max_credits: 10000,
  });
}

describe("useBillingSettings checkout conflict handling", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    navigationState.pathname = "/dashboard/billing";
    navigationState.push.mockReset();
  });

  it("displays the safe backend message for an already-active user", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(billingOverviewResponse())
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "base_subscription_checkout_conflict",
              message:
                "You already have an active subscription. Use plan management to change your plan.",
              current_plan: "plan_standard",
              current_status: "active",
              route: "/billing/upgrade",
            },
          },
          409
        )
      )
      .mockResolvedValueOnce(billingOverviewResponse());
    const { result } = renderHook(() => useBillingSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.handleCheckout("plan_specialist");
    });

    expect(result.current.actionError).toBe(
      "You already have an active subscription. Use plan management to change your plan."
    );
    expect(navigationState.push).toHaveBeenCalledWith("/dashboard/billing?section=plans");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("routes an active user from another surface to plan management", async () => {
    navigationState.pathname = "/dashboard/audit";
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(billingOverviewResponse())
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "base_subscription_checkout_conflict",
              message: "Use plan management.",
              route: "/billing/upgrade",
            },
          },
          409
        )
      )
      .mockResolvedValueOnce(billingOverviewResponse());
    const { result } = renderHook(() => useBillingSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.handleCheckout("plan_specialist");
    });

    expect(result.current.actionError).toBe("Use plan management.");
    expect(navigationState.push).toHaveBeenCalledWith("/dashboard/billing?section=plans");
  });

  it("opens billing recovery for a delinquent subscription", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(billingOverviewResponse())
      .mockResolvedValueOnce(
        jsonResponse(
          {
            detail: {
              code: "base_subscription_checkout_conflict",
              message: "Your subscription needs attention.",
              route: "/billing/portal-session",
            },
          },
          409
        )
      )
      .mockResolvedValueOnce(
        jsonResponse({ detail: "Billing recovery is temporarily unavailable." }, 503)
      );
    const { result } = renderHook(() => useBillingSettings());
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await act(async () => {
      await result.current.handleCheckout("plan_standard");
    });

    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      "/api/billing/portal-session",
      expect.objectContaining({ method: "POST" })
    );
    expect(result.current.actionError).toBe("Billing recovery is temporarily unavailable.");
  });
});
