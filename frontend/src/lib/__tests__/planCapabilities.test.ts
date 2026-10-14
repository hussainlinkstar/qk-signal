import { describe, expect, it } from "vitest";

import {
  getPlanWeight,
  hasPlanCapability,
  resolvePlanCapabilities,
  resolvePlanType,
  resolveServedCapability,
} from "@/lib/planCapabilities";

// SIGV2-1039. These four are granted by the backend on plan_executive and only
// there (`CAPABILITY_MATRIX` and `MINIMUM_PLAN_BY_FEATURE` in
// backend/app/config/plans.py, pinned by
// backend/tests/test_executive_entitlements.py::test_capability_matrix_executive_only).
// This table held `false` for all four on every plan including Executive, so
// an entitled customer saw a permanently locked White-Label section and a dead
// "Add Workspace" button. Same class of defect as the live-engine-tracking one.
const EXECUTIVE_ONLY_KEYS = [
  "has_white_label",
  "has_custom_domain",
  "pdf_white_label",
  "has_multi_workspace_federation",
] as const;

describe("resolvePlanCapabilities", () => {
  it("normalizes human-readable plan labels before resolving capabilities", () => {
    expect(resolvePlanType("Executive")).toBe("plan_executive");
    expect(resolvePlanType("Agency Trial")).toBe("plan_agency_trial");
    expect(resolvePlanType("Specialist")).toBe("plan_specialist");
  });

  it("keeps Specialist aligned with backend-gated API and automation features", () => {
    const capabilities = resolvePlanCapabilities("plan_specialist");

    expect(capabilities.api_access).toBe(true);
    expect(capabilities.can_schedule_audits).toBe(true);
    expect(capabilities.entity_authority).toBe(true);
    expect(capabilities.has_high_confidence_mode).toBe(true);
    expect(capabilities.lead_widget).toBe(true);
  });

  it("keeps Standard locked out of premium feature bundles", () => {
    const capabilities = resolvePlanCapabilities("plan_standard");

    expect(capabilities.api_access).toBe(false);
    expect(capabilities.has_competitor_analysis).toBe(false);
    expect(capabilities.has_high_confidence_mode).toBe(false);
    expect(capabilities.pdf_white_label).toBe(false);
    expect(capabilities.lead_widget).toBe(false);
  });

  it("keeps starter and unresolved plans locked out of paid capabilities", () => {
    const starterCapabilities = resolvePlanCapabilities("plan_starter");
    const unknownCapabilities = resolvePlanCapabilities("starter_v2");

    expect(starterCapabilities.api_access).toBe(false);
    expect(starterCapabilities.can_schedule_audits).toBe(false);
    expect(starterCapabilities.has_white_label).toBe(false);
    expect(starterCapabilities.monthly_price_usd).toBe(0);

    expect(unknownCapabilities.api_access).toBe(false);
    expect(unknownCapabilities.can_schedule_audits).toBe(false);
    expect(unknownCapabilities.has_white_label).toBe(false);
  });

  it("unlocks high confidence mode from Specialist upwards", () => {
    expect(resolvePlanCapabilities("plan_specialist").has_high_confidence_mode).toBe(true);
    expect(resolvePlanCapabilities("plan_executive").has_high_confidence_mode).toBe(true);
    expect(resolvePlanCapabilities("plan_standard").has_high_confidence_mode).toBe(false);
  });

  it("keeps Executive inheriting Specialist capabilities for display-name inputs", () => {
    const capabilities = resolvePlanCapabilities("Executive");

    expect(capabilities.api_access).toBe(true);
    expect(capabilities.can_schedule_audits).toBe(true);
    expect(capabilities.can_export_to_jira).toBe(true);
    expect(capabilities.has_competitor_analysis).toBe(true);
  });
});

describe("hasPlanCapability", () => {
  it("grants higher plans access to lower-plan requirements", () => {
    expect(hasPlanCapability("plan_executive", "plan_specialist")).toBe(true);
    expect(hasPlanCapability("plan_executive", "Executive")).toBe(true);
    expect(hasPlanCapability("Executive", "Specialist")).toBe(true);
  });

  it("denies lower plans from higher-plan requirements", () => {
    expect(hasPlanCapability("plan_standard", "plan_specialist")).toBe(false);
    expect(hasPlanCapability("plan_specialist", "plan_executive")).toBe(false);
  });

  it("exposes stable weights for canonical paid plan hierarchy", () => {
    expect(getPlanWeight("plan_starter")).toBeLessThan(getPlanWeight("plan_standard"));
    expect(getPlanWeight("plan_standard")).toBeLessThan(getPlanWeight("plan_specialist"));
    expect(getPlanWeight("plan_specialist")).toBeLessThan(getPlanWeight("plan_executive"));
    // Executive is the top tier: nothing outranks it.
    expect(getPlanWeight("plan_executive")).toBeGreaterThanOrEqual(
      getPlanWeight("plan_agency_trial")
    );
  });
});

describe("executive-only entitlements agree with the backend", () => {
  it("grants all four on Executive and on no other plan", () => {
    const plans = [
      "plan_starter",
      "plan_agency_trial",
      "plan_standard",
      "plan_specialist",
      "plan_executive",
    ] as const;

    for (const plan of plans) {
      const capabilities = resolvePlanCapabilities(plan);
      for (const key of EXECUTIVE_ONLY_KEYS) {
        expect(capabilities[key], `${plan}.${key}`).toBe(plan === "plan_executive");
      }
    }
  });
});

describe("resolveServedCapability", () => {
  const served = {
    current_plan: "plan_executive",
    plans: [
      { id: "plan_standard", capabilities: { has_white_label: false } },
      { id: "plan_executive", capabilities: { has_white_label: true } },
    ],
  };

  it("uses the entitlement the API serves for the current plan", () => {
    expect(resolveServedCapability(served, "has_white_label", "plan_standard")).toBe(true);
  });

  it("does not let the local table overrule a served plan that withholds the key", () => {
    // Fail-safe: once the API has identified the plan, a key it does not grant
    // is LOCKED, even if the offline table disagrees.
    const standard = { ...served, current_plan: "plan_standard" };
    expect(resolveServedCapability(standard, "has_white_label", "plan_executive")).toBe(false);
  });

  it("falls back to the local table only before the payload resolves", () => {
    expect(resolveServedCapability(null, "has_white_label", "plan_executive")).toBe(true);
    expect(resolveServedCapability(null, "has_white_label", "plan_standard")).toBe(false);
    // A payload with no current plan on file is also a fallback case.
    expect(
      resolveServedCapability(
        { current_plan: null, plans: served.plans },
        "has_white_label",
        "plan_executive"
      )
    ).toBe(true);
  });
});
