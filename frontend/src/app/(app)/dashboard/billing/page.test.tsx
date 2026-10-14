import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import BillingPage from "@/app/(app)/dashboard/billing/page";

vi.mock("@/components/billing/PlanChangeModal", () => ({
  default: ({
    open,
    targetPlanId,
    targetBillingInterval,
    onSuccess,
  }: {
    open: boolean;
    targetPlanId: string | null;
    targetBillingInterval: string;
    onSuccess: () => void;
  }) =>
    open ? (
      <div role="dialog" aria-label="Plan change modal stub">
        <span>Modal target plan: {targetPlanId}</span>
        <span>Modal target interval: {targetBillingInterval}</span>
        <button type="button" onClick={onSuccess}>
          Complete mocked plan change
        </button>
      </div>
    ) : null,
}));

let searchParamsState = new URLSearchParams("");

const authState = {
  isSignedIn: true,
  isLoading: false,
  getToken: vi.fn(async () => "token-123"),
};

vi.mock("@/components/auth/custom-auth", () => ({
  useAuth: () => authState,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => searchParamsState,
}));

const buildBillingOverview = (overrides?: Partial<Record<string, unknown>>) => ({
  current_plan: "plan_specialist",
  status: "active",
  billing_interval: "month",
  pending_plan_change: null,
  portal_available: true,
  plans: [
    {
      id: "plan_standard",
      price_id: "price_nc",
      annual_price_id: "price_nc_year",
      checkout_available: true,
      annual_checkout_available: true,
      name: "Standard",
      description: "Launch your first AI visibility workflows.",
      highlight: "For solo operators.",
      color: "slate",
      features: ["25 audits/mo", "Up to 1 site", "PDF audit reports"],
      capabilities: {
        monthly_price_usd: 99,
        max_sites: 1,
        max_audits: 25,
        has_competitor_analysis: false,
        has_advanced_reporting: false,
        api_access: false,
        has_high_confidence_mode: false,
      },
    },
    {
      id: "plan_specialist",
      price_id: "price_sp",
      annual_price_id: "price_sp_year",
      checkout_available: true,
      annual_checkout_available: true,
      name: "Specialist",
      description: "Unlock advanced monitoring and automation.",
      highlight: "For scaling teams.",
      color: "primary",
      features: ["100 audits/mo", "Up to 10 sites", "Advanced reporting"],
      capabilities: {
        monthly_price_usd: 399,
        max_sites: 10,
        max_audits: 100,
        has_competitor_analysis: true,
        has_advanced_reporting: true,
        api_access: false,
        has_high_confidence_mode: false,
      },
    },
    {
      id: "plan_executive",
      price_id: "price_se",
      checkout_available: true,
      name: "Executive",
      description: "Enterprise-grade governance, automation, and integrations.",
      highlight: "For multi-brand agencies.",
      color: "indigo",
      features: ["1000 audits/mo", "Unlimited sites", "API access"],
      capabilities: {
        monthly_price_usd: 999,
        max_sites: -1,
        max_audits: 1000,
        has_competitor_analysis: true,
        has_advanced_reporting: true,
        api_access: true,
        has_high_confidence_mode: true,
        max_parallel_audits: 10,
        has_parallel_audit_execution: false,
        has_sla_guarantee: false,
        has_multi_workspace_federation: false,
        has_white_label: true,
        has_dedicated_strategist: true,
      },
    },
  ],
  ...overrides,
});

const planCard = (name: string) => {
  const card = screen.getByRole("heading", { name }).closest(".group");
  if (!card) {
    throw new Error(`Unable to find the ${name} plan card`);
  }
  return within(card as HTMLElement);
};

describe("BillingPage", () => {
  beforeEach(() => {
    searchParamsState = new URLSearchParams("");
    authState.getToken.mockClear();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(buildBillingOverview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  // It used to render outside every tab panel, so the same sales card repeated on
  // all five. It stays on Overview, where signal-MVP puts it, and on Plans,
  // because a custom, negotiated arrangement is not one of the four self-service
  // tiers and Contact Sales is the only route to it.
  it("shows the enterprise contact card on overview and plans, not on the other tabs", async () => {
    render(<BillingPage />);
    await screen.findByText("Active Subscription");

    expect(screen.getByText("Need a custom plan?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    expect(screen.getByText("Need a custom plan?")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Comparison" }));
    expect(screen.queryByText("Need a custom plan?")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Usage" }));
    expect(screen.queryByText("Need a custom plan?")).not.toBeInTheDocument();
  });

  // SIGV2-1165: the Commitments tab is withdrawn until commitment checkout is
  // configured; re-adding it must be a deliberate revert, not an accident.
  it("does not render a Commitments tab", async () => {
    render(<BillingPage />);
    await screen.findByText("Active Subscription");

    const tablist = screen.getByRole("tablist");
    expect(within(tablist).getByRole("tab", { name: "Overview" })).toBeInTheDocument();
    expect(within(tablist).getByRole("tab", { name: "Usage" })).toBeInTheDocument();
    expect(within(tablist).getByRole("tab", { name: "Plans" })).toBeInTheDocument();
    expect(within(tablist).getByRole("tab", { name: "Comparison" })).toBeInTheDocument();
    expect(within(tablist).queryByRole("tab", { name: "Commitments" })).not.toBeInTheDocument();
  });

  it("falls back to Overview for ?section=commitments and ignores the retired checkout params", async () => {
    searchParamsState = new URLSearchParams("section=commitments&commitment=success");

    render(<BillingPage />);
    await screen.findByText("Active Subscription");

    const overviewTab = screen.getByRole("tab", { name: "Overview" });
    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    expect(screen.queryByText(/Commitment checkout/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Commitment Widget Stub")).not.toBeInTheDocument();
  });

  it("uses the shared accessible tabs contract for billing sections", async () => {
    render(<BillingPage />);
    await screen.findByText("Active Subscription");

    const tablist = screen.getByRole("tablist");
    const overviewTab = within(tablist).getByRole("tab", { name: "Overview" });
    const overviewPanel = screen.getByRole("tabpanel", { name: "Overview" });

    expect(overviewTab).toHaveAttribute("aria-selected", "true");
    expect(overviewTab).toHaveAttribute("aria-controls", overviewPanel.id);
    expect(overviewPanel).toHaveAttribute("aria-labelledby", overviewTab.id);

    fireEvent.click(within(tablist).getByRole("tab", { name: "Plans" }));
    const plansTab = within(tablist).getByRole("tab", { name: "Plans" });
    const plansPanel = screen.getByRole("tabpanel", { name: "Plans" });

    expect(plansTab).toHaveAttribute("aria-selected", "true");
    expect(plansTab).toHaveAttribute("aria-controls", plansPanel.id);
    expect(plansPanel).toHaveAttribute("aria-labelledby", plansTab.id);
  });

  it("renders canonical plan entitlements from the billing API instead of stale hard-coded copy", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");

    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    await waitFor(() => {
      expect(screen.getByText("25 audits/mo")).toBeInTheDocument();
      expect(screen.getByText("100 audits/mo")).toBeInTheDocument();
      expect(screen.getByText("1000 audits/mo")).toBeInTheDocument();
    });

    expect(screen.queryByText("5 audits/mo")).not.toBeInTheDocument();
    expect(screen.queryByText("50 audits/mo")).not.toBeInTheDocument();
    expect(screen.queryByText("Unlimited audits")).not.toBeInTheDocument();
  });

  it("uses clear commercial copy instead of internal jargon", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");

    expect(screen.getByText("Manage Billing")).toBeInTheDocument();
    expect(screen.getAllByText(/Billing/).length).toBeGreaterThan(0);
    expect(screen.getByRole("heading", { level: 1, name: "Billing" })).toBeInTheDocument();
    expect(screen.getByText("Active Subscription")).toBeInTheDocument();
    expect(screen.getByText("Need a custom plan?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Contact Sales" })).toBeInTheDocument();
    expect(screen.getAllByText("Up to 10 sites").length).toBeGreaterThan(0);
    expect(
      screen.getByText("Upgrade to Executive to unlock the stricter High Confidence audit path.")
    ).toBeInTheDocument();
    expect(screen.getByText("High Confidence Mode")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    expect(screen.getAllByText("Change Plan").length).toBeGreaterThan(0);

    expect(screen.queryByText("Upgrade Matrices")).not.toBeInTheDocument();
    expect(screen.queryByText("Active Node")).not.toBeInTheDocument();
    expect(screen.queryByText("Upgrade Vector")).not.toBeInTheDocument();
    expect(screen.queryByText("Need Custom Clearance?")).not.toBeInTheDocument();
    expect(screen.queryByText("Initiate Handshake (Billing)")).not.toBeInTheDocument();
    expect(screen.queryByText("REL_2026.4")).not.toBeInTheDocument();
    expect(screen.queryByText("Architectural Features")).not.toBeInTheDocument();
  });

  it("renders a live plan comparison matrix and highlights the current plan in it", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Comparison" }));

    await screen.findByRole("table", { name: "Plan comparison" });

    expect(screen.getByText("Compare Every Capability")).toBeInTheDocument();
    expect(screen.getByText("Competitor analysis")).toBeInTheDocument();
    expect(screen.getByText("Advanced reporting")).toBeInTheDocument();
    expect(screen.getByText("API & MCP access")).toBeInTheDocument();
    expect(screen.getAllByText("High Confidence mode").length).toBeGreaterThan(0);
    expect(screen.getByText("Max parallel assessments")).toBeInTheDocument();
    expect(screen.getAllByText(/current plan/i).length).toBeGreaterThan(0);
  });

  it("hides the billing portal CTA when the user has no Stripe customer yet", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(buildBillingOverview({ portal_available: false })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    await screen.findByText("Choose a paid plan to unlock billing portal");

    expect(screen.queryByText("Manage Billing")).not.toBeInTheDocument();
    expect(screen.getByText("Choose a paid plan to unlock billing portal")).toBeInTheDocument();
  });

  it("keeps Manage Billing available and invokes the portal API without a pending plan change", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(buildBillingOverview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (typeof input === "string" && input === "/api/billing/portal-session") {
        return new Response(JSON.stringify({ detail: "Portal request captured" }), {
          status: 500,
          headers: { "Content-Type": "application/json" },
        });
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    const manageBilling = await screen.findByRole("button", { name: /Manage Billing/ });
    expect(manageBilling).toBeEnabled();

    fireEvent.click(manageBilling);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/billing/portal-session",
        expect.objectContaining({ method: "POST" })
      )
    );
  });

  /* SIGV2-1171. `useBillingSettings` writes every portal and checkout failure
     to one `actionError`, and the page only rendered it inside the Overview
     panel. A checkout refused from the Plans tab therefore left the customer
     looking at an unchanged plan card with no message anywhere on screen, and
     the 409 conflict path makes it worse by routing to ?section=plans. The
     alert now sits above the panels, so it is at the action whichever tab ran
     it. */
  it("states a refused portal request as an alert, in whichever tab the action ran", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(buildBillingOverview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (typeof input === "string" && input === "/api/billing/portal-session") {
        return new Response(JSON.stringify({ detail: { message: "Stripe is unreachable." } }), {
          status: 503,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);
    fireEvent.click(await screen.findByRole("button", { name: /Manage Billing/ }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Action failed");
    expect(alert).toHaveTextContent("Stripe is unreachable.");
    expect(alert).toHaveAttribute("data-signal-alert", "danger");

    // Still there after switching tab: the message belongs to the action, and
    // the 409 conflict path moves the customer to Plans on its own.
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Stripe is unreachable.");
  });

  it("disables checkout for plans that are not configured in the current billing environment", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(
          JSON.stringify(
            buildBillingOverview({
              current_plan: null,
              status: null,
              portal_available: false,
              plans: [
                buildBillingOverview().plans[0],
                buildBillingOverview().plans[1],
                {
                  ...buildBillingOverview().plans[2],
                  price_id: "",
                  checkout_available: false,
                },
              ],
            })
          ),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    await screen.findByText("Choose a paid plan to unlock billing portal");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    await screen.findByText("Unavailable");

    const unavailableButton = screen.getByRole("button", { name: /unavailable/i });
    expect(unavailableButton).toBeDisabled();
  });

  it("hides the internal agency trial plan from plan cards", async () => {
    const agencyTrialPlan = {
      ...buildBillingOverview().plans[0],
      id: "plan_agency_trial",
      price_id: "",
      checkout_available: false,
      name: "Agency Trial",
      description: "Invite-only hidden agency trial plan.",
      highlight: "Internal trial plan.",
      features: ["Trial audits included"],
      capabilities: {
        monthly_price_usd: 0,
        max_sites: 5,
        max_audits: 100,
        has_competitor_analysis: true,
        has_advanced_reporting: true,
        api_access: false,
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(
          JSON.stringify(
            buildBillingOverview({
              current_plan: "plan_agency_trial",
              plans: [agencyTrialPlan, ...buildBillingOverview().plans],
            })
          ),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    await screen.findByText("Active Subscription");

    expect(screen.queryByText("Agency Trial")).not.toBeInTheDocument();
    expect(screen.getByText("Trial Plan")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    // Contact Sales is in the BillingSalesContactCard button
    expect(screen.getByRole("button", { name: "Contact Sales" })).toBeInTheDocument();
  });

  // SIGV2-1168: the dedicated-strategist offer was withdrawn, so the plan
  // card must not advertise it even when the capability key is still set.
  it("renders no Strategist badge when has_dedicated_strategist is true, and keeps the other badges", async () => {
    const strategistPlan = {
      ...buildBillingOverview().plans[2],
      capabilities: {
        monthly_price_usd: 999,
        max_sites: -1,
        max_audits: 1000,
        api_access: false,
        has_white_label: true,
        has_dedicated_strategist: true,
      },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(
          JSON.stringify(
            buildBillingOverview({
              plans: [...buildBillingOverview().plans.slice(0, 2), strategistPlan],
            })
          ),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);
    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    const executive = planCard("Executive");
    expect(executive.getByText("White Label")).toBeInTheDocument();
    expect(executive.queryByText("Strategist")).not.toBeInTheDocument();
    expect(screen.queryByText("Strategist")).not.toBeInTheDocument();
  });

  // A "pending" subscription row is written when a checkout starts, not when
  // one completes, so the plan is still Free. Printing the internal status
  // alongside it produced the reported "Free / Status: pending", which reads
  // as a stuck payment rather than "no subscription yet".
  it("does not print the internal pending status under the Free plan", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(
          JSON.stringify(
            buildBillingOverview({
              current_plan: null,
              status: "pending",
              portal_available: false,
            })
          ),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    expect(await screen.findByRole("heading", { level: 2, name: "Free" })).toBeInTheDocument();
    expect(screen.queryByText(/Status: pending/)).not.toBeInTheDocument();
  });

  // SIGV2-1200: the approved mockup duplicates the audit allowance in the
  // chip row; the build states it once. Assert on count, not presence.
  it("states the audit allowance exactly once in the active-subscription chips", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");

    expect(screen.getAllByText("Up to 100 audits")).toHaveLength(1);
    expect(screen.getAllByText("Up to 10 sites").length).toBeGreaterThan(0);
  });

  it("suppresses self-service plan mutations for a current contact-only plan while retaining billing visibility", async () => {
    // Agency Trial is the only remaining non-self-service plan.
    const contactOnlyOverview = buildBillingOverview({ current_plan: "plan_agency_trial" });
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(contactOnlyOverview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    expect(
      await screen.findByRole("heading", { level: 2, name: "Trial Plan" })
    ).toBeInTheDocument();
    expect(screen.getByText("Status: active")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Manage Billing/ })).toBeEnabled();
    expect(screen.getByRole("link", { name: /Billing History/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    expect(screen.queryByRole("button", { name: "Change Plan" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Change Billing Interval/i })
    ).not.toBeInTheDocument();

    const contactSales = screen.getByRole("button", { name: "Contact Sales" });
    expect(contactSales).toBeEnabled();
    fireEvent.click(contactSales);
    expect(screen.getByRole("heading", { name: "Tell us what you need" })).toBeInTheDocument();
  });

  it("renders canonical Executive as active and entitled instead of Free", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(
          JSON.stringify(buildBillingOverview({ current_plan: "plan_executive" })),
          {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }
        );
      }

      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    expect(await screen.findByRole("heading", { level: 2, name: "Executive" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 2, name: "Free" })).not.toBeInTheDocument();
    const highConfidenceCard = screen
      .getByText("High Confidence Mode")
      .closest("div[class*='rounded']");
    expect(highConfidenceCard).not.toBeNull();
    expect(
      within(highConfidenceCard as HTMLElement).getByText(/plan includes .*High Confidence/i)
    ).toBeInTheDocument();
    expect(
      within(highConfidenceCard as HTMLElement).queryByText(/upgrade/i)
    ).not.toBeInTheDocument();
  });

  it("passes the selected billing interval to the plan change modal", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    fireEvent.click(screen.getByRole("button", { name: "Annual" }));
    fireEvent.click(planCard("Standard").getByRole("button", { name: "Change Plan" }));

    expect(screen.getByText("Modal target plan: plan_standard")).toBeInTheDocument();
    expect(screen.getByText("Modal target interval: year")).toBeInTheDocument();
  });

  it("enables the current plan only for an interval change and disables it for the active interval", async () => {
    render(<BillingPage />);

    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    expect(planCard("Specialist").getByRole("button")).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Annual" }));
    expect(
      planCard("Specialist").getByRole("button", { name: /change billing interval/i })
    ).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Monthly" }));
    expect(planCard("Specialist").getByRole("button")).toBeDisabled();
  });

  it.each([
    {
      targetName: "annual",
      activeInterval: "month",
      targetIntervalLabel: "Annual",
      unavailableFields: { annual_price_id: "", annual_checkout_available: false },
      availableFields: {
        annual_price_id: "price_sp_year",
        annual_checkout_available: true,
      },
    },
    {
      targetName: "monthly",
      activeInterval: "year",
      targetIntervalLabel: "Monthly",
      unavailableFields: { price_id: "", checkout_available: false },
      availableFields: { price_id: "price_sp", checkout_available: true },
    },
  ])(
    "enables the current-plan $targetName interval CTA only when its target price is available",
    async ({ activeInterval, targetIntervalLabel, unavailableFields, availableFields }) => {
      const overviewWithSpecialistFields = (fields: Record<string, unknown>) => {
        const overview = buildBillingOverview({ billing_interval: activeInterval });
        return {
          ...overview,
          plans: overview.plans.map((plan) =>
            plan.id === "plan_specialist" ? { ...plan, ...fields } : plan
          ),
        };
      };
      let overview = overviewWithSpecialistFields(unavailableFields);
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(JSON.stringify(overview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      const unavailableRender = render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      fireEvent.click(screen.getByRole("button", { name: targetIntervalLabel }));

      const unavailableCta = planCard("Specialist").getByRole("button", {
        name: /change billing interval/i,
      });
      expect(unavailableCta).toBeDisabled();
      fireEvent.click(unavailableCta);
      expect(
        screen.queryByRole("dialog", { name: "Plan change modal stub" })
      ).not.toBeInTheDocument();
      unavailableRender.unmount();

      overview = overviewWithSpecialistFields(availableFields);
      render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      fireEvent.click(screen.getByRole("button", { name: targetIntervalLabel }));

      expect(
        planCard("Specialist").getByRole("button", { name: /change billing interval/i })
      ).toBeEnabled();
    }
  );

  it.each([
    {
      targetName: "annual",
      activeInterval: "month",
      targetIntervalLabel: "Annual",
      unavailableFields: { annual_price_id: "", annual_checkout_available: false },
      availableFields: {
        annual_price_id: "price_nc_year",
        annual_checkout_available: true,
      },
    },
    {
      targetName: "monthly",
      activeInterval: "year",
      targetIntervalLabel: "Monthly",
      unavailableFields: { price_id: "", checkout_available: false },
      availableFields: { price_id: "price_nc", checkout_available: true },
    },
  ])(
    "enables a non-current plan Change Plan CTA for the $targetName interval only when that price is available",
    async ({ activeInterval, targetIntervalLabel, unavailableFields, availableFields }) => {
      const overviewWithStandardFields = (fields: Record<string, unknown>) => {
        const overview = buildBillingOverview({ billing_interval: activeInterval });
        return {
          ...overview,
          plans: overview.plans.map((plan) =>
            plan.id === "plan_standard" ? { ...plan, ...fields } : plan
          ),
        };
      };
      let overview = overviewWithStandardFields(unavailableFields);
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(JSON.stringify(overview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      const unavailableRender = render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      fireEvent.click(screen.getByRole("button", { name: targetIntervalLabel }));

      const unavailableCta = planCard("Standard").getByRole("button", {
        name: "Change Plan",
      });
      expect(unavailableCta).toBeDisabled();
      fireEvent.click(unavailableCta);
      expect(
        screen.queryByRole("dialog", { name: "Plan change modal stub" })
      ).not.toBeInTheDocument();
      unavailableRender.unmount();

      overview = overviewWithStandardFields(availableFields);
      render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      fireEvent.click(screen.getByRole("button", { name: targetIntervalLabel }));

      expect(planCard("Standard").getByRole("button", { name: "Change Plan" })).toBeEnabled();
    }
  );

  it.each([
    {
      modeCase: "runtime test with an active live subscription",
      monthlyAvailable: true,
      annualAvailable: false,
    },
    {
      modeCase: "runtime live with an active test subscription",
      monthlyAvailable: false,
      annualAvailable: true,
    },
  ])(
    "reflects mode-specific interval availability for $modeCase",
    async ({ monthlyAvailable, annualAvailable }) => {
      const overview = buildBillingOverview();
      const modeSpecificOverview = {
        ...overview,
        plans: overview.plans.map((plan) =>
          plan.id === "plan_standard"
            ? {
                ...plan,
                price_id: monthlyAvailable ? "price_subscription_mode_standard_month" : "",
                checkout_available: monthlyAvailable,
                annual_price_id: annualAvailable ? "price_subscription_mode_standard_year" : "",
                annual_checkout_available: annualAvailable,
              }
            : plan
        ),
      };
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(JSON.stringify(modeSpecificOverview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

      const monthlyCta = planCard("Standard").getByRole("button", { name: "Change Plan" });
      if (monthlyAvailable) {
        expect(monthlyCta).toBeEnabled();
      } else {
        expect(monthlyCta).toBeDisabled();
      }

      fireEvent.click(screen.getByRole("button", { name: "Annual" }));
      const annualCta = planCard("Standard").getByRole("button", { name: "Change Plan" });
      if (annualAvailable) {
        expect(annualCta).toBeEnabled();
      } else {
        expect(annualCta).toBeDisabled();
      }
    }
  );

  it("initializes the interval selector from an asynchronously loaded annual subscription", async () => {
    let resolveOverview: ((response: Response) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Promise<Response>((resolve) => {
          resolveOverview = resolve;
        });
      }
      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);
    expect(screen.getByText("Loading billing overview...")).toBeInTheDocument();

    await waitFor(() => expect(resolveOverview).toBeTypeOf("function"));
    await act(async () => {
      resolveOverview?.(
        new Response(JSON.stringify(buildBillingOverview({ billing_interval: "year" })), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      );
    });

    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));

    expect(screen.getByRole("button", { name: "Annual" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Monthly" })).toHaveAttribute(
      "aria-pressed",
      "false"
    );
  });

  it("does not overwrite an interacted interval selection when the overview reloads", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (typeof input === "string" && input === "/api/billing/plans") {
        return new Response(JSON.stringify(buildBillingOverview()), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`Unexpected fetch call: ${String(input)}`);
    });

    render(<BillingPage />);

    await screen.findByText("Active Subscription");
    fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
    fireEvent.click(screen.getByRole("button", { name: "Annual" }));
    fireEvent.click(planCard("Standard").getByRole("button", { name: "Change Plan" }));
    fireEvent.click(screen.getByRole("button", { name: "Complete mocked plan change" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("button", { name: "Annual" })).toHaveAttribute("aria-pressed", "true");
  });

  it.each(["canceled", "incomplete_expired"])(
    "ignores a complete pending plan change for terminal status %s and starts checkout for the selected interval",
    async (status) => {
      const terminalOverview = buildBillingOverview({
        current_plan: null,
        status,
        billing_interval: "month",
        pending_plan_change: {
          target_plan: "plan_standard",
          target_billing_interval: "month",
          effective_at: "2026-08-15T12:00:00+00:00",
          schedule_id: "sub_sched_stale_terminal_downgrade",
        },
      });
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(JSON.stringify(terminalOverview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        if (typeof input === "string" && input === "/api/billing/checkout-session") {
          return new Response(JSON.stringify({ detail: "Checkout request captured" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      render(<BillingPage />);

      await screen.findByText("Active Subscription");
      expect(screen.queryByText("Plan change scheduled")).not.toBeInTheDocument();

      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      fireEvent.click(screen.getByRole("button", { name: "Annual" }));
      const subscribeButton = planCard("Standard").getByRole("button", { name: "Subscribe" });
      expect(subscribeButton).toBeEnabled();

      fireEvent.click(subscribeButton);

      await waitFor(() =>
        expect(fetchMock).toHaveBeenCalledWith(
          "/api/billing/checkout-session",
          expect.objectContaining({
            method: "POST",
            body: JSON.stringify({ plan: "plan_standard", billing_interval: "year" }),
          })
        )
      );
    }
  );

  it.each(["active", "trialing"])(
    "restores a persisted pending downgrade for status %s and blocks billing management and plan changes",
    async (status) => {
      const pendingOverview = buildBillingOverview({
        status,
        billing_interval: "year",
        pending_plan_change: {
          target_plan: "plan_standard",
          target_billing_interval: "month",
          effective_at: "2026-08-15T12:00:00+00:00",
          schedule_id: "sub_sched_persisted_downgrade",
        },
      });
      const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(JSON.stringify(pendingOverview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          });
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      const firstRender = render(<BillingPage />);
      await screen.findByText("Plan change scheduled");
      firstRender.unmount();

      render(<BillingPage />);

      expect(await screen.findByText("Plan change scheduled")).toBeInTheDocument();
      expect(screen.getByText(/Standard/)).toBeInTheDocument();
      expect(screen.getByText(/Monthly billing/)).toBeInTheDocument();
      expect(screen.getByText("August 15, 2026")).toBeInTheDocument();

      const manageBilling = screen.getByRole("button", { name: /Manage Billing/ });
      expect(manageBilling).toBeDisabled();
      fireEvent.click(manageBilling);
      expect(fetchMock).not.toHaveBeenCalledWith("/api/billing/portal-session", expect.anything());

      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      expect(planCard("Standard").getByRole("button")).toBeDisabled();
      expect(planCard("Executive").getByRole("button")).toBeDisabled();
    }
  );

  it("opens the structured sales intake modal from the enterprise CTA", async () => {
    render(<BillingPage />);

    await screen.findByText("Need a custom plan?");

    fireEvent.click(screen.getByRole("button", { name: "Contact Sales" }));

    expect(screen.getByRole("heading", { name: "Tell us what you need" })).toBeInTheDocument();
    expect(screen.getByLabelText("Company name")).toBeInTheDocument();
    expect(screen.getByLabelText("Monthly audits target")).toBeInTheDocument();
    expect(screen.getByLabelText("Billing requirements")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Email Draft" })).toBeInTheDocument();
  });
  // SIGV2-1211: Jake's four instructions for the Executive billing card, each
  // asserted on its own so a regression names which one broke.
  //
  // The card is the only place the Executive up-sell appears. Its copy is
  // literal consultancy text served as `bespoke_highlights` and `features`,
  // never derived from a capability key: `has_white_label`,
  // `has_multi_workspace_federation` and the workflow-automation keys are all
  // either withdrawn (SIGV2-1167) or unpublished (SIGV2-1206), so deriving the
  // card from them would undo both.
  describe("the Executive card (SIGV2-1211)", () => {
    const executivePlan = () => ({
      ...buildBillingOverview().plans[2],
      custom_priced: true,
      cta: "contact",
      bespoke_highlights: [
        "Agent development",
        "Custom workflows",
        "Paid ads / marketing insights",
      ],
      annual_price_usd: null,
      features: [
        "2000 audits/mo",
        "Agent deployment and hosting",
        "Workflow automation to fit your processes",
        "AI consultancy and development",
      ],
      capabilities: {
        ...buildBillingOverview().plans[2].capabilities,
        monthly_price_usd: null,
      },
    });

    const renderWithExecutive = async (currentPlan: string | null = "plan_specialist") => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
        if (typeof input === "string" && input === "/api/billing/plans") {
          return new Response(
            JSON.stringify(
              buildBillingOverview({
                current_plan: currentPlan,
                plans: [...buildBillingOverview().plans.slice(0, 2), executivePlan()],
              })
            ),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        throw new Error(`Unexpected fetch call: ${String(input)}`);
      });

      render(<BillingPage />);
      await screen.findByText("Active Subscription");
      fireEvent.click(screen.getByRole("tab", { name: "Plans" }));
      return planCard("Executive");
    };

    it("quotes no monthly figure, and does not fall back to Free", async () => {
      const executive = await renderWithExecutive();

      expect(executive.getByText("Custom pricing")).toBeInTheDocument();
      // A null price must not read as the cheapest plan, nor as $0.
      expect(executive.queryByText("Free")).not.toBeInTheDocument();
      expect(executive.queryByText("$0")).not.toBeInTheDocument();
      expect(executive.queryByText("$999")).not.toBeInTheDocument();
      expect(executive.queryByText("/ month")).not.toBeInTheDocument();
    });

    it("states no per-audit unit price when there is no price to divide", async () => {
      const executive = await renderWithExecutive();

      // The card divides price by scans. With no price that arithmetic has no
      // answer, and "Free" would be the opposite of the truth.
      expect(executive.getByText("Per audit")).toBeInTheDocument();
      expect(executive.getByText("Custom")).toBeInTheDocument();
    });

    it("shows Jake's three highlights instead of capability-derived badges", async () => {
      const executive = await renderWithExecutive();

      expect(executive.getByText("Agent development")).toBeInTheDocument();
      expect(executive.getByText("Custom workflows")).toBeInTheDocument();
      expect(executive.getByText("Paid ads / marketing insights")).toBeInTheDocument();

      // The badges these replaced. `has_white_label` is still true on the
      // served plan, so their absence proves the card stopped deriving.
      expect(executive.queryByText("White Label")).not.toBeInTheDocument();
      expect(executive.queryByText("Multi-Workspace")).not.toBeInTheDocument();
      expect(executive.queryByText("API Access")).not.toBeInTheDocument();
    });

    it("shows the scan allowance then Jake's three consultancy lines", async () => {
      const executive = await renderWithExecutive();

      expect(executive.getByText("2000 audits/mo")).toBeInTheDocument();
      expect(executive.getByText("Agent deployment and hosting")).toBeInTheDocument();
      expect(executive.getByText("Workflow automation to fit your processes")).toBeInTheDocument();
      expect(executive.getByText("AI consultancy and development")).toBeInTheDocument();
    });

    it("offers Contact us on the marketing site, never a Subscribe button", async () => {
      const executive = await renderWithExecutive();

      const contact = executive.getByRole("link", { name: "Contact us" });
      expect(contact).toHaveAttribute("href", "https://qiko.ai/labs#contact");
      expect(executive.queryByRole("button", { name: "Subscribe" })).not.toBeInTheDocument();
      expect(executive.queryByRole("button", { name: "Change Plan" })).not.toBeInTheDocument();
    });

    it("still offers Contact us to a visitor with no subscription at all", async () => {
      const executive = await renderWithExecutive(null);

      expect(executive.getByRole("link", { name: "Contact us" })).toBeInTheDocument();
      expect(executive.queryByRole("button", { name: "Subscribe" })).not.toBeInTheDocument();
    });

    it("leaves a listed plan's price, ticks and Subscribe button alone", async () => {
      await renderWithExecutive(null);

      const standard = planCard("Standard");
      expect(standard.getByText("$99")).toBeInTheDocument();
      expect(standard.getByText("/ month")).toBeInTheDocument();
      expect(standard.queryByText("Custom pricing")).not.toBeInTheDocument();
      expect(standard.queryByRole("link", { name: "Contact us" })).not.toBeInTheDocument();
    });
  });
});
