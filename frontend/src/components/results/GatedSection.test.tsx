import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GatedSection from "@/components/results/GatedSection";

describe("GatedSection", () => {
  it("renders the caller-supplied feature bullets instead of a one-size-fits-all list", () => {
    render(
      <GatedSection
        title="Live engine tracking"
        teaser="Upgrade to measure live."
        requiredPlan="executive"
        requiredPlanLabel="Executive"
        features={["Real-time results on 6 consumer AI engines", "Model-specific visibility"]}
      />
    );

    expect(screen.getByText("Real-time results on 6 consumer AI engines")).toBeInTheDocument();
    expect(screen.getByText("Model-specific visibility")).toBeInTheDocument();
    // The old one-size-fits-all bullets must not leak in when custom features are given.
    expect(screen.queryByText("Full findings & deep analysis")).not.toBeInTheDocument();
  });

  it("falls back to a sensible default feature list when none is supplied", () => {
    render(
      <GatedSection
        title="Some feature"
        teaser="Upgrade to unlock."
        requiredPlan="standard"
        requiredPlanLabel="Standard"
      />
    );

    expect(screen.getByText("Full findings & deep analysis")).toBeInTheDocument();
  });

  it("renders distinct bullets for two different gated sections rendered side by side", () => {
    render(
      <>
        <GatedSection
          title="Live engine tracking"
          teaser="A"
          requiredPlan="executive"
          requiredPlanLabel="Executive"
          features={["Live engine bullet unique to this panel"]}
        />
        <GatedSection
          title="Done for you"
          teaser="B"
          requiredPlan="executive"
          requiredPlanLabel="Executive"
          features={["Execution bullet unique to this panel"]}
        />
      </>
    );

    expect(screen.getByText("Live engine bullet unique to this panel")).toBeInTheDocument();
    expect(screen.getByText("Execution bullet unique to this panel")).toBeInTheDocument();
  });
});

// SIGV2-1221. This card used to render one CTA for everybody: "Start Free,
// Unlock Full Report" pointing at /register. A signed-in Standard customer
// looking at an Executive-gated section was told to start a free account they
// already have, on a page that could not unlock anything, while the plan the
// card had just computed went nowhere. A guest audit token is what identifies
// the guest flow, so it is what selects the CTA.
describe("GatedSection upgrade call to action", () => {
  it("asks a signed-in customer to upgrade to the plan the card names", () => {
    render(
      <GatedSection
        title="Brand Guardrails"
        teaser="Keep generated reports grounded in your truth."
        requiredPlan="plan_executive"
        requiredPlanLabel="Executive"
      />
    );

    const cta = screen.getByRole("link", { name: /Upgrade to Executive/i });
    expect(cta).toHaveAttribute("href", "/dashboard/billing?section=plans&plan=plan_executive");
    expect(screen.queryByText(/Start Free/i)).not.toBeInTheDocument();
  });

  it("keeps the sign-up ask for a guest reading a shared audit", () => {
    render(
      <GatedSection
        title="AI answers intelligence"
        teaser="Sign up to see the full breakdown."
        guestAuditToken="tok-123"
      />
    );

    const cta = screen.getByRole("link", { name: /Start Free, Unlock Full Report/i });
    expect(cta).toHaveAttribute("href", "/register?guest_audit_token=tok-123");
  });

  // A guest gate withholds the whole tab from anyone who has not signed up,
  // and the free Starter plan unlocks it, so naming a paid plan next to a
  // "Start Free" button would put a price on something that costs nothing.
  it("states no plan when the caller names none", () => {
    render(<GatedSection title="AI visibility analysis" teaser="Sign up." guestAuditToken="t" />);

    expect(screen.queryByText(/Available on/i)).not.toBeInTheDocument();
  });

  it("falls back to a plan-free upgrade ask rather than inventing a plan", () => {
    render(<GatedSection title="Some section" teaser="Locked." />);

    const cta = screen.getByRole("link", { name: /Upgrade your plan/i });
    expect(cta).toHaveAttribute("href", "/dashboard/billing?section=plans");
  });
});
