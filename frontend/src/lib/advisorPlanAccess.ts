import { resolvePlanType } from "@/lib/planCapabilities";

/**
 * SIGV2-1134: one served entitlement for the Advisor action plan and for every
 * preview of it.
 *
 * The action plan page and the project dashboard's top-three preview card are
 * the same feature at two depths, but they used to gate on two different
 * capabilities: the plan page on `has_advisor_recommendations` (Standard and
 * up) and the dashboard card on `feature_access.automations`, which is
 * `can_use_workflow_automations` (Specialist and up). A Standard customer
 * could therefore open the full plan while the dashboard told them to upgrade
 * to Specialist to preview it.
 *
 * Both now read `feature_access.advisor_recommendations`, which the backend
 * builds from `has_advisor_recommendations` in
 * `services/project_intelligence_service.py`. Nothing here consults the
 * offline capability table: the entitlement, the plan that lock copy names and
 * the billing link the lock points at all come from that served payload, so
 * the two surfaces cannot disagree with each other or with the backend.
 */

export const ADVISOR_PLAN_FEATURE_KEY = "advisor_recommendations";

const BILLING_PLANS_HREF = "/dashboard/billing?section=plans";

type ServedFeatureAccessState = {
  allowed?: boolean | null;
  required_plan?: string | null;
};

type ProjectWithAdvisorAccess = {
  feature_access?: {
    advisor_recommendations?: ServedFeatureAccessState | null;
  } | null;
};

export type AdvisorPlanAccess = {
  /** True only when the served payload positively grants the plan. */
  allowed: boolean;
  /**
   * SIGV2-1305: whether the payload actually said anything about this.
   *
   * `allowed` is false both for a customer whose plan excludes the feature and
   * for a payload that has not arrived or arrived without `feature_access`.
   * Those are different facts and only the first one justifies an upsell.
   *
   * QA found a Standard customer being asked to upgrade for the action plan
   * their plan grants. Checked against the account: `plan_standard`, active,
   * `has_advisor_recommendations` true, so the entitlement is right and what
   * they saw was the unknown state wearing the locked state's clothes.
   *
   * Telling somebody who is already paying to pay again is the single worst
   * thing a billing-adjacent surface can do, so an unknown entitlement now
   * says nothing rather than guessing downwards.
   */
  resolved: boolean;
  /** The plan the backend says is required, or null when it named none. */
  requiredPlan: string | null;
  /** Billing link, deep-linked to that plan only when it resolves to a real one. */
  upgradeHref: string;
};

/**
 * Resolve the Advisor action plan entitlement from a served project payload.
 *
 * Fail-safe in one direction only: anything other than a positive `allowed`
 * is LOCKED, including a payload that has not arrived yet.
 */
export const resolveAdvisorPlanAccess = (
  project: ProjectWithAdvisorAccess | null | undefined
): AdvisorPlanAccess => {
  const served = project?.feature_access?.advisor_recommendations ?? null;

  const rawRequiredPlan =
    typeof served?.required_plan === "string" ? served.required_plan.trim() : "";
  const requiredPlan = rawRequiredPlan || null;

  // The served value is a display name ("Standard"); the billing page takes a
  // canonical plan id. Resolve it through the shared alias table so a name the
  // frontend does not recognise becomes a plain billing link instead of an
  // invented query parameter.
  const canonicalPlan = requiredPlan ? resolvePlanType(`plan_${requiredPlan.toLowerCase()}`) : null;

  return {
    allowed: served?.allowed === true,
    // The payload spoke: it carried the key and a boolean for it. A missing
    // key, a null, or no payload at all is silence, not a refusal.
    resolved: typeof served?.allowed === "boolean",
    requiredPlan,
    upgradeHref: canonicalPlan ? `${BILLING_PLANS_HREF}&plan=${canonicalPlan}` : BILLING_PLANS_HREF,
  };
};
