/**
 * SIGV2-1134: the served `advisor_recommendations` feature-access states, shared
 * by every test that covers the Advisor action plan or a preview of it.
 *
 * The point of sharing them is that the project dashboard's preview card and the
 * action plan page must be exercised with the same payload shape. They used to
 * gate on two different capabilities, so a Standard customer could open the full
 * plan while the dashboard told them to upgrade to Specialist to preview it.
 *
 * The wording of `detail` and the `required_plan` value here mirror
 * `_FEATURE_RULES["advisor_recommendations"]` in
 * `backend/services/project_intelligence_service.py`.
 */

export type ServedAdvisorPlanAccess = {
  advisor_recommendations: {
    allowed: boolean;
    detail: string | null;
    status_code: number | null;
    required_plan: string | null;
  };
};

export const ADVISOR_PLAN_ALLOWED: ServedAdvisorPlanAccess = {
  advisor_recommendations: {
    allowed: true,
    detail: null,
    status_code: null,
    required_plan: null,
  },
};

export const ADVISOR_PLAN_LOCKED: ServedAdvisorPlanAccess = {
  advisor_recommendations: {
    allowed: false,
    detail: "The Advisor action plan requires Standard or higher.",
    status_code: 402,
    required_plan: "Standard",
  },
};
