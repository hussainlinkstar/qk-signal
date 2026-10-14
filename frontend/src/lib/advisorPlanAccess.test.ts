import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { ADVISOR_PLAN_FEATURE_KEY, resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { ADVISOR_PLAN_ALLOWED, ADVISOR_PLAN_LOCKED } from "@/test/advisorPlanAccessFixtures";

const read = (relative: string): string => readFileSync(resolve(process.cwd(), relative), "utf8");

// The two surfaces that present the Advisor action plan: the plan itself and
// the project dashboard's top-three preview of it.
const ADVISOR_PLAN_SURFACES = [
  "src/app/(app)/dashboard/projects/[projectId]/fixes/page.tsx",
  "src/app/(app)/dashboard/projects/[projectId]/page.tsx",
];

describe("resolveAdvisorPlanAccess", () => {
  it("grants only on a positive served allowance", () => {
    expect(resolveAdvisorPlanAccess({ feature_access: ADVISOR_PLAN_ALLOWED }).allowed).toBe(true);
    expect(resolveAdvisorPlanAccess({ feature_access: ADVISOR_PLAN_LOCKED }).allowed).toBe(false);
  });

  it("is locked while nothing has been served yet", () => {
    // The project payload arrives asynchronously. Defaulting to granted would
    // flash the plan before the entitlement is known.
    expect(resolveAdvisorPlanAccess(null).allowed).toBe(false);
    expect(resolveAdvisorPlanAccess(undefined).allowed).toBe(false);
    expect(resolveAdvisorPlanAccess({}).allowed).toBe(false);
    expect(resolveAdvisorPlanAccess({ feature_access: {} }).allowed).toBe(false);
  });

  it("takes the plan to name, and the plan to link to, from the served payload", () => {
    const access = resolveAdvisorPlanAccess({ feature_access: ADVISOR_PLAN_LOCKED });

    expect(access.requiredPlan).toBe("Standard");
    expect(access.upgradeHref).toBe("/dashboard/billing?section=plans&plan=plan_standard");
  });

  it("names no plan when the payload named none", () => {
    const access = resolveAdvisorPlanAccess({
      feature_access: {
        advisor_recommendations: {
          allowed: false,
          detail: null,
          status_code: 402,
          required_plan: null,
        },
      },
    });

    expect(access.requiredPlan).toBeNull();
    expect(access.upgradeHref).toBe("/dashboard/billing?section=plans");
  });

  it("refuses to build a billing link from a plan name it cannot resolve", () => {
    const access = resolveAdvisorPlanAccess({
      feature_access: {
        advisor_recommendations: {
          allowed: false,
          detail: null,
          status_code: 402,
          required_plan: "Platinum Deluxe",
        },
      },
    });

    // The name is still shown, because the backend said it; the deep link is
    // not invented from it.
    expect(access.requiredPlan).toBe("Platinum Deluxe");
    expect(access.upgradeHref).toBe("/dashboard/billing?section=plans");
  });
});

// SIGV2-1134. The defect was not a wrong boolean, it was two surfaces of one
// feature answering to two different entitlements: the plan page to
// has_advisor_recommendations (Standard and up) and the dashboard preview to
// feature_access.automations, which is can_use_workflow_automations
// (Specialist and up). A Standard customer could open the full plan and was
// told on the dashboard to upgrade to Specialist to preview it.
describe("the Advisor action plan is one entitlement on every surface", () => {
  it("resolves both surfaces through the one shared helper", () => {
    for (const relative of ADVISOR_PLAN_SURFACES) {
      const source = read(relative);
      expect(source, relative).toContain("resolveAdvisorPlanAccess");
    }
  });

  it("gates neither surface on workflow automations", () => {
    for (const relative of ADVISOR_PLAN_SURFACES) {
      const source = read(relative);
      expect(source, relative).not.toContain("automations");
    }
  });

  it("reads entitlement from the served payload, never the offline plan table", () => {
    for (const relative of ADVISOR_PLAN_SURFACES) {
      const source = read(relative);
      expect(source, relative).not.toContain("resolvePlanCapabilities");
      expect(source, relative).not.toContain("subscription_plan");
    }
  });

  // The served key has to be the one the backend actually builds, or the gate
  // silently resolves to "absent" and locks an entitled customer out.
  it("uses the feature key the backend serves, keyed on the advisor capability", () => {
    const rules = read("../backend/services/project_intelligence_service.py");

    expect(ADVISOR_PLAN_FEATURE_KEY).toBe("advisor_recommendations");
    expect(rules).toContain(`"${ADVISOR_PLAN_FEATURE_KEY}": ProjectFeatureRule(`);
    expect(
      rules.slice(rules.indexOf(`"${ADVISOR_PLAN_FEATURE_KEY}": ProjectFeatureRule(`))
    ).toContain('capability_key="has_advisor_recommendations"');
  });
});
