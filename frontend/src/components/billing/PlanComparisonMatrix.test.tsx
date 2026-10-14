import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import PlanComparisonMatrix from "@/components/billing/PlanComparisonMatrix";
import type { BillingPlan } from "@/types/billing";

const buildPlan = (
  id: BillingPlan["id"],
  name: string,
  capabilities: Record<string, boolean | number | null>
): BillingPlan => ({
  id,
  price_id: `price_${id}`,
  checkout_available: true,
  name,
  description: `${name} description`,
  highlight: `${name} highlight`,
  color: "primary",
  features: [`${name} feature`],
  capabilities: {
    monthly_price_usd: 99,
    max_sites: 1,
    max_audits: 25,
    ...capabilities,
  },
});

// The four keys are still served by the billing API and still gate real
// behaviour; SIGV2-1167 only stops the comparison tab advertising them.
const UNAVAILABLE_LABELS = [
  "Slack integration",
  "Teams integration",
  "Dedicated strategist",
  "Done-for-you execution",
];

// SIGV2-1206: these are served entitlements too, but none is an offerable MVP
// feature, so the curated allowlist keeps them off the comparison.
const UNPUBLISHED_LABELS = [
  "CMS push",
  "Lead widget",
  "Entity authority",
  "Workflow automations",
  "Max workflows per project",
];

describe("PlanComparisonMatrix", () => {
  it("does not render withdrawn or inactive capabilities as comparison rows", () => {
    const plans = [
      buildPlan("plan_standard", "Standard", {
        can_use_slack_integration: false,
        can_use_teams_integration: false,
        has_dedicated_strategist: false,
        has_done_for_you_execution: false,
        can_use_workflow_automations: false,
        has_competitor_analysis: false,
      }),
      buildPlan("plan_executive", "Executive", {
        can_use_slack_integration: true,
        can_use_teams_integration: true,
        has_dedicated_strategist: true,
        has_done_for_you_execution: true,
        can_use_workflow_automations: true,
        has_competitor_analysis: true,
      }),
    ];

    render(<PlanComparisonMatrix plans={plans} currentPlanId="plan_executive" />);

    const table = screen.getByRole("table", { name: "Plan comparison" });
    expect(table).toBeInTheDocument();

    for (const label of UNAVAILABLE_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
  });

  it("renders only curated publishable capabilities, never unavailable offers or unknown keys", () => {
    const plans = [
      buildPlan("plan_standard", "Standard", {
        cms_push: false,
        lead_widget: false,
        entity_authority: false,
        can_use_workflow_automations: false,
        max_workflows_per_project: 0,
        has_competitor_analysis: false,
        has_future_mvp_module: false,
      }),
      buildPlan("plan_executive", "Executive", {
        cms_push: true,
        lead_widget: true,
        entity_authority: true,
        can_use_workflow_automations: true,
        max_workflows_per_project: -1,
        has_competitor_analysis: true,
        has_future_mvp_module: true,
      }),
    ];

    render(<PlanComparisonMatrix plans={plans} currentPlanId="plan_executive" />);

    for (const label of UNPUBLISHED_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    // A key the API starts serving tomorrow shows nothing until it is
    // deliberately published, and no titled flag name is invented for it.
    expect(screen.queryByText("Future Mvp Module")).not.toBeInTheDocument();
    // A legitimate differing row keeps rendering.
    expect(screen.getByText("Competitor analysis")).toBeInTheDocument();
  });

  it("does not render withdrawn or inactive capabilities as shared-foundation badges", () => {
    const plans = [
      buildPlan("plan_standard", "Standard", {
        can_use_slack_integration: true,
        can_use_teams_integration: true,
        has_dedicated_strategist: true,
        has_done_for_you_execution: true,
        // An unpublished capability that is true on every plan is the badge
        // case: shared on paper, still not offerable.
        cms_push: true,
        has_competitor_analysis: false,
      }),
      buildPlan("plan_executive", "Executive", {
        can_use_slack_integration: true,
        can_use_teams_integration: true,
        has_dedicated_strategist: true,
        has_done_for_you_execution: true,
        cms_push: true,
        has_competitor_analysis: true,
      }),
    ];

    render(<PlanComparisonMatrix plans={plans} currentPlanId="plan_executive" />);

    for (const label of UNAVAILABLE_LABELS) {
      expect(screen.queryByText(label)).not.toBeInTheDocument();
    }
    expect(screen.queryByText("CMS push")).not.toBeInTheDocument();
  });
});
