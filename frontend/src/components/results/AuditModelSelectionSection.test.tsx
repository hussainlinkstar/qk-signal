import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditModelSelectionSection from "@/components/results/AuditModelSelectionSection";
import { type CanonicalPlanType, resolvePlanCapabilities } from "@/lib/planCapabilities";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const CANONICAL_PLANS: CanonicalPlanType[] = [
  "plan_starter",
  "plan_agency_trial",
  "plan_standard",
  "plan_specialist",
  "plan_executive",
];

describe("AuditModelSelectionSection", () => {
  it("is the approved plan-managed summary bar (SIGV2-1188)", () => {
    // The Oct-6 mockup replaces the engine pill list with a summary strip:
    // bold "Managed by your plan" + scope chip, and a caption explaining that
    // allowance and models follow the plan.
    render(<AuditModelSelectionSection />);

    expect(
      screen.getByRole("heading", { name: "Models included with your plan" })
    ).toBeInTheDocument();
    expect(screen.getByText("Managed by your plan")).toBeInTheDocument();
    expect(screen.getByText("Same models across the project")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Your prompt allowance and available models follow your plan. You do not need to configure models for each question."
      )
    ).toBeInTheDocument();
  });

  it("offers no control: no plan grants per-scan model routing (SIGV2-1139)", () => {
    // The bar is a statement of what the plan manages. It must not render an
    // interactive element, and the copy must not name a plan as granting a
    // capability no plan grants; the backend discards submitted model picks.
    const { container } = render(<AuditModelSelectionSection />);

    expect(container.querySelectorAll("input")).toHaveLength(0);
    expect(container.querySelectorAll("button")).toHaveLength(0);
    expect(container.querySelectorAll("a")).toHaveLength(0);

    // SIGV2-1120: this used to assert `has_custom_ai_model_routing` was false
    // on every plan. The key has been deleted from the capability contract
    // rather than left false, so the assertion now pins its absence. That is
    // the stronger claim: a false key can be flipped, a missing key has to be
    // reintroduced on both sides before anything can grant a model choice.
    for (const plan of CANONICAL_PLANS) {
      expect(resolvePlanCapabilities(plan)).not.toHaveProperty("has_custom_ai_model_routing");
    }
  });

  it("does not enumerate engines or promise a roster change", () => {
    // The strip deliberately stays engine-agnostic until the entitlement
    // response lands: no model names, no counts that could drift from billing.
    render(<AuditModelSelectionSection />);

    for (const name of ["ChatGPT", "Gemini", "Perplexity", "Claude", "Grok", "DeepSeek", "Llama"]) {
      expect(screen.queryByText(name)).not.toBeInTheDocument();
    }
    expect(
      screen.queryByText(/10 prompts|200 models|models of your choice/)
    ).not.toBeInTheDocument();
  });
});
