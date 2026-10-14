import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CommitmentTierSelector from "@/components/billing/CommitmentTierSelector";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn, i18n: { language: "en" } }),
}));

const buildPayload = (overrides?: Partial<Record<string, unknown>>) => ({
  eligible: true,
  locked_reason: null,
  current_plan: "plan_specialist",
  commitment: null,
  tiers: [
    {
      tier: "growth",
      label: "Growth",
      committed_credits: 2000,
      rate_per_credit: 0.09,
      discount_pct: 10,
      monthly_fee_usd: 180,
      overage_rate: 0.1,
    },
    {
      tier: "scale",
      label: "Scale",
      committed_credits: 5000,
      rate_per_credit: 0.08,
      discount_pct: 20,
      monthly_fee_usd: 400,
      overage_rate: 0.1,
    },
    {
      tier: "enterprise",
      label: "Enterprise",
      committed_credits: 8750,
      rate_per_credit: 0.07,
      discount_pct: 30,
      monthly_fee_usd: 612.5,
      overage_rate: 0.1,
    },
  ],
  ...overrides,
});

describe("CommitmentTierSelector", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (typeof input === "string" && input === "/api/billing/commitment-tiers") {
        return new Response(JSON.stringify(buildPayload()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (typeof input === "string" && input === "/api/billing/commitment-checkout") {
        return new Response(
          JSON.stringify({ checkout_url: "https://checkout.stripe.com/c/pay/cs_commitment" }),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }
      throw new Error(`Unexpected fetch call: ${String(input)} ${JSON.stringify(init ?? {})}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a plan lock state for ineligible workspaces", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify(
          buildPayload({
            eligible: false,
            locked_reason: "Audit commitments are available on Specialist and Executive.",
          })
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByText("Specialist+ Required");
    expect(
      screen.getByText("Audit commitments are available on Specialist and Executive.")
    ).toBeInTheDocument();
  });

  // SIGNAL-1002: the "Current plan" chip showed the raw slug ("plan executive")
  // instead of a real plan name.
  it("shows a human-readable plan name, not the raw slug", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify(buildPayload({ current_plan: "plan_executive" })), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByText("Executive");
    expect(screen.queryByText("plan executive")).not.toBeInTheDocument();
    expect(screen.queryByText(/^plan_/)).not.toBeInTheDocument();
  });

  it("starts Stripe checkout for the selected tier", async () => {
    const assignMock = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign: assignMock });

    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByRole("button", { name: /start growth/i });
    fireEvent.click(screen.getByRole("button", { name: /start growth/i }));

    await waitFor(() => {
      expect(globalThis.fetch).toHaveBeenCalledWith("/api/billing/commitment-checkout", {
        method: "POST",
        headers: {
          Authorization: "Bearer token-123",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tier: "growth" }),
      });
    });

    expect(assignMock).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_commitment");
  });

  // SIGV2-1128: the overage state is still stated, qualitatively. It used to be
  // stated as "1,200 above commitment" and "124% used", both of which are
  // internal credit figures.
  it("states the overage without publishing a credit figure", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify(
          buildPayload({
            commitment: {
              id: 7,
              tier: "scale",
              committed_credits: 5000,
              rate_per_credit: 0.08,
              monthly_fee_usd: 400,
              overage_rate: 0.1,
              status: "active",
              cancel_at_period_end: false,
              cycle_start: "2026-03-01T00:00:00Z",
              cycle_end: "2026-04-01T00:00:00Z",
              credits_used: 6200,
              credits_remaining: 0,
              overage_credits: 1200,
              usage_pct: 124,
              nearing_limit: true,
              in_overage: true,
              pending_tier: null,
              pending_change_effective_at: null,
            },
          })
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByText("Over commitment");
    expect(
      screen.getByText("Usage above your committed volume is billed at the standard rate.")
    ).toBeInTheDocument();
    expect(screen.getByText("Current cycle ends on Apr 1, 2026.")).toBeInTheDocument();
    expect(screen.queryByText(/1,200/)).not.toBeInTheDocument();
    expect(screen.queryByText(/124%/)).not.toBeInTheDocument();
    expect(screen.queryByText(/6,200/)).not.toBeInTheDocument();
  });

  it("keeps the on-track cycle state qualitative", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify(
          buildPayload({
            commitment: {
              id: 8,
              tier: "growth",
              committed_credits: 2000,
              rate_per_credit: 0.09,
              monthly_fee_usd: 180,
              overage_rate: 0.1,
              status: "active",
              cancel_at_period_end: false,
              cycle_start: "2026-03-01T00:00:00Z",
              cycle_end: "2026-04-01T00:00:00Z",
              credits_used: 400,
              credits_remaining: 1600,
              overage_credits: 0,
              usage_pct: 20,
              nearing_limit: false,
              in_overage: false,
              pending_tier: null,
              pending_change_effective_at: null,
            },
          })
        ),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      )
    );

    render(
      <CommitmentTierSelector
        getAuthHeaders={async () => ({ Authorization: "Bearer token-123" })}
      />
    );

    await screen.findByText("On track");
    // The monthly fee shows twice: on the active commitment and on its tier card.
    expect(screen.getAllByText("$180.00").length).toBeGreaterThan(0);
    expect(screen.queryByText(/1,600/)).not.toBeInTheDocument();
    expect(screen.queryByText(/% used/)).not.toBeInTheDocument();
  });
});
