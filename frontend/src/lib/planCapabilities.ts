export type PlanCapabilitySet = {
  monthly_price_usd: number;
  max_sites: number;
  max_audits: number;
  max_parallel_audits: number;
  max_workflows_per_project: number;
  seo: boolean;
  geo: boolean;
  aeo: boolean;
  entity_analysis: boolean;
  entity_authority: boolean;
  has_baseline_geo_visibility_index: boolean;
  has_aeo_answerability_score: boolean;
  has_core_entity_identity_check: boolean;
  has_performance_sync: boolean;
  has_pdf_audit_reports: boolean;
  has_custom_pricing: boolean;
  has_priority_pulse: boolean;
  has_predictive_intent_engine: boolean;
  has_semantic_graph_mapping: boolean;
  has_entity_enhancement: boolean;
  has_brand_integrity_guardrails: boolean;
  has_eeat_trust_audit: boolean;
  has_dedicated_strategist: boolean;
  has_advisor_recommendations: boolean;
  has_done_for_you_execution: boolean;
  /**
   * Live engine tracking (SIGV2-1108). Granted on EVERY plan by the backend:
   * `CAPABILITY_MATRIX` in `backend/app/config/plans.py` sets
   * `has_live_engine_tracking: True` for plan_starter, plan_agency_trial,
   * plan_standard, plan_specialist and plan_executive, and
   * `MINIMUM_PLAN_BY_FEATURE["has_live_engine_tracking"]` is `"plan_starter"`,
   * the lowest plan. The backend is the source of truth for entitlement, so
   * every entry below must stay `true`; a `false` here would advertise an
   * upgrade that changes nothing.
   */
  has_live_engine_tracking: boolean;
  has_high_confidence_mode: boolean;
  has_competitor_analysis: boolean;
  has_semantic_gap: boolean;
  /**
   * White-label, custom domain, white-label PDFs and multiple workspaces
   * (SIGV2-1026, re-aligned on SIGV2-1039). All four are granted by the
   * backend on `plan_executive` and only there: `CAPABILITY_MATRIX` in
   * `backend/app/config/plans.py` sets them `True` for plan_executive, and
   * `MINIMUM_PLAN_BY_FEATURE` names `"plan_executive"` for each.
   * `backend/tests/test_executive_entitlements.py::test_capability_matrix_executive_only`
   * pins that.
   *
   * This table used to hold `false` on every plan, Executive included, which
   * is how an entitled Executive customer ended up with a permanently locked
   * White-Label section and a disabled "Add Workspace" button for capabilities
   * the API would have served them. The backend is the source of truth for
   * entitlement; this table is only the offline fallback, and
   * `resolveServedCapability` below prefers the served value whenever the API
   * has resolved a current plan.
   */
  has_white_label: boolean;
  has_custom_domain: boolean;
  has_advanced_reporting: boolean;
  can_schedule_audits: boolean;
  pdf_white_label: boolean;
  api_access: boolean;
  mcp_access: boolean;
  can_export_to_jira: boolean;
  can_use_slack_integration: boolean;
  can_use_teams_integration: boolean;
  can_use_workflow_automations: boolean;
  has_parallel_audit_execution: boolean;
  has_volume_serp_api: boolean;
  has_dedicated_infrastructure: boolean;
  has_multi_workspace_federation: boolean;
  has_sla_guarantee: boolean;
  cms_push: boolean;
  lead_widget: boolean;
};

export type CanonicalPlanType =
  | "plan_starter"
  | "plan_agency_trial"
  | "plan_standard"
  | "plan_specialist"
  | "plan_executive";

const STARTER_CAPABILITIES: PlanCapabilitySet = {
  monthly_price_usd: 0,
  has_advisor_recommendations: false,
  has_done_for_you_execution: false,
  has_live_engine_tracking: true,
  max_sites: 1,
  max_audits: 1,
  max_parallel_audits: 1,
  max_workflows_per_project: 0,
  seo: true,
  geo: true,
  aeo: true,
  entity_analysis: true,
  entity_authority: false,
  has_baseline_geo_visibility_index: true,
  has_aeo_answerability_score: true,
  has_core_entity_identity_check: true,
  has_performance_sync: true,
  has_pdf_audit_reports: true,
  has_custom_pricing: false,
  has_priority_pulse: false,
  has_predictive_intent_engine: false,
  has_semantic_graph_mapping: false,
  has_entity_enhancement: false,
  has_brand_integrity_guardrails: false,
  has_eeat_trust_audit: false,
  has_dedicated_strategist: false,
  has_high_confidence_mode: false,
  has_competitor_analysis: false,
  has_semantic_gap: false,
  has_white_label: false,
  has_custom_domain: false,
  has_advanced_reporting: false,
  can_schedule_audits: false,
  pdf_white_label: false,
  api_access: false,
  mcp_access: false,
  can_export_to_jira: false,
  can_use_slack_integration: false,
  can_use_teams_integration: false,
  can_use_workflow_automations: false,
  has_parallel_audit_execution: false,
  has_volume_serp_api: false,
  has_dedicated_infrastructure: false,
  has_multi_workspace_federation: false,
  has_sla_guarantee: false,
  cms_push: false,
  lead_widget: false,
};

const STANDARD_CAPABILITIES: PlanCapabilitySet = {
  monthly_price_usd: 49,
  has_advisor_recommendations: true,
  has_done_for_you_execution: false,
  has_live_engine_tracking: true,
  max_sites: 1,
  max_audits: 200,
  max_parallel_audits: 1,
  max_workflows_per_project: 0,
  seo: true,
  geo: true,
  aeo: true,
  entity_analysis: true,
  entity_authority: false,
  has_baseline_geo_visibility_index: true,
  has_aeo_answerability_score: true,
  has_core_entity_identity_check: true,
  has_performance_sync: true,
  has_pdf_audit_reports: true,
  has_custom_pricing: false,
  has_priority_pulse: false,
  has_predictive_intent_engine: false,
  has_semantic_graph_mapping: false,
  has_entity_enhancement: false,
  has_brand_integrity_guardrails: false,
  has_eeat_trust_audit: false,
  has_dedicated_strategist: false,
  has_high_confidence_mode: false,
  has_competitor_analysis: false,
  has_semantic_gap: false,
  has_white_label: false,
  has_custom_domain: false,
  has_advanced_reporting: false,
  can_schedule_audits: false,
  pdf_white_label: false,
  api_access: false,
  mcp_access: false,
  can_export_to_jira: false,
  can_use_slack_integration: false,
  can_use_teams_integration: false,
  can_use_workflow_automations: false,
  has_parallel_audit_execution: false,
  has_volume_serp_api: false,
  has_dedicated_infrastructure: false,
  has_multi_workspace_federation: false,
  has_sla_guarantee: false,
  cms_push: false,
  lead_widget: false,
};

const PLAN_WEIGHTS: Record<CanonicalPlanType, number> = {
  plan_starter: 3,
  plan_agency_trial: 20,
  plan_standard: 10,
  plan_specialist: 20,
  plan_executive: 30,
};

const PLAN_ALIASES: Record<string, CanonicalPlanType> = {
  trial: "plan_agency_trial",
  "agency trial": "plan_agency_trial",
  plan_agency_trial: "plan_agency_trial",
  plan_standard: "plan_standard",
  "neural core": "plan_standard",
  starter: "plan_starter",
  plan_starter: "plan_starter",
  standard: "plan_standard",
  specialist: "plan_specialist",
  executive: "plan_executive",
  basic: "plan_standard",
  "synapse basic": "plan_standard",
  plan_specialist: "plan_specialist",
  "synapse pro": "plan_specialist",
  pro: "plan_specialist",
  growth: "plan_specialist",
  smart: "plan_specialist",
  plan_executive: "plan_executive",
  "singularity elite": "plan_executive",
  enterprise: "plan_executive",
  deep_judgment: "plan_specialist",
  high_confidence: "plan_specialist",
};

const CAPABILITY_MATRIX: Record<string, PlanCapabilitySet> = {
  plan_starter: { ...STARTER_CAPABILITIES },
  plan_agency_trial: {
    monthly_price_usd: 0,
    has_advisor_recommendations: true,
    has_done_for_you_execution: false,
    has_live_engine_tracking: true,
    max_sites: 3,
    max_audits: 5,
    max_parallel_audits: 2,
    max_workflows_per_project: 2,
    seo: true,
    geo: true,
    aeo: true,
    entity_analysis: true,
    entity_authority: true,
    has_baseline_geo_visibility_index: true,
    has_aeo_answerability_score: true,
    has_core_entity_identity_check: true,
    has_performance_sync: true,
    has_pdf_audit_reports: true,
    has_custom_pricing: false,
    has_priority_pulse: true,
    has_predictive_intent_engine: true,
    has_semantic_graph_mapping: true,
    has_entity_enhancement: true,
    has_brand_integrity_guardrails: false,
    has_eeat_trust_audit: false,
    has_dedicated_strategist: false,
    has_high_confidence_mode: false,
    has_competitor_analysis: true,
    has_semantic_gap: true,
    has_white_label: false,
    has_custom_domain: false,
    has_advanced_reporting: true,
    can_schedule_audits: true,
    pdf_white_label: false,
    api_access: true,
    // SIGV2-1210: deliberately false while `api_access` is true. The
    // agency trial reaches the REST API but not the MCP server, which is
    // the reason `mcp_access` exists as a separate key rather than reusing
    // `api_access`. Mirrors CAPABILITY_MATRIX in backend/app/config/plans.py.
    mcp_access: false,
    can_export_to_jira: true,
    can_use_slack_integration: true,
    can_use_teams_integration: true,
    can_use_workflow_automations: true,
    has_parallel_audit_execution: false,
    has_volume_serp_api: false,
    has_dedicated_infrastructure: false,
    has_multi_workspace_federation: false,
    has_sla_guarantee: false,
    cms_push: false,
    lead_widget: true,
  },
  plan_standard: { ...STANDARD_CAPABILITIES },
  plan_specialist: {
    monthly_price_usd: 99,
    has_advisor_recommendations: true,
    has_done_for_you_execution: false,
    has_live_engine_tracking: true,
    max_sites: 10,
    max_audits: 800,
    max_parallel_audits: 5,
    max_workflows_per_project: 5,
    seo: true,
    geo: true,
    aeo: true,
    entity_analysis: true,
    entity_authority: true,
    has_baseline_geo_visibility_index: true,
    has_aeo_answerability_score: true,
    has_core_entity_identity_check: true,
    has_performance_sync: true,
    has_pdf_audit_reports: true,
    has_custom_pricing: false,
    has_priority_pulse: true,
    has_predictive_intent_engine: true,
    has_semantic_graph_mapping: true,
    has_entity_enhancement: true,
    has_brand_integrity_guardrails: false,
    has_eeat_trust_audit: false,
    has_dedicated_strategist: false,
    has_high_confidence_mode: true,
    has_competitor_analysis: true,
    has_semantic_gap: true,
    has_white_label: false,
    has_custom_domain: false,
    has_advanced_reporting: true,
    can_schedule_audits: true,
    pdf_white_label: false,
    api_access: true,
    mcp_access: true,
    can_export_to_jira: true,
    can_use_slack_integration: true,
    can_use_teams_integration: true,
    can_use_workflow_automations: true,
    has_parallel_audit_execution: false,
    has_volume_serp_api: false,
    has_dedicated_infrastructure: false,
    has_multi_workspace_federation: false,
    has_sla_guarantee: false,
    cms_push: false,
    lead_widget: true,
  },
  plan_executive: {
    monthly_price_usd: 999,
    has_advisor_recommendations: true,
    has_done_for_you_execution: true,
    has_live_engine_tracking: true,
    max_sites: -1,
    max_audits: 2000,
    max_parallel_audits: 10,
    max_workflows_per_project: -1,
    seo: true,
    geo: true,
    aeo: true,
    entity_analysis: true,
    entity_authority: true,
    has_baseline_geo_visibility_index: true,
    has_aeo_answerability_score: true,
    has_core_entity_identity_check: true,
    has_performance_sync: true,
    has_pdf_audit_reports: true,
    has_custom_pricing: true,
    has_priority_pulse: true,
    has_predictive_intent_engine: true,
    has_semantic_graph_mapping: true,
    has_entity_enhancement: true,
    has_brand_integrity_guardrails: true,
    has_eeat_trust_audit: true,
    has_dedicated_strategist: true,
    has_high_confidence_mode: true,
    has_competitor_analysis: true,
    has_semantic_gap: true,
    has_white_label: true,
    has_custom_domain: true,
    has_advanced_reporting: true,
    can_schedule_audits: true,
    pdf_white_label: true,
    api_access: true,
    mcp_access: true,
    can_export_to_jira: true,
    can_use_slack_integration: true,
    can_use_teams_integration: true,
    can_use_workflow_automations: true,
    has_parallel_audit_execution: false,
    has_volume_serp_api: false,
    has_dedicated_infrastructure: false,
    has_multi_workspace_federation: true,
    has_sla_guarantee: false,
    cms_push: true,
    lead_widget: true,
  },
};

/**
 * The customer-facing name of each plan, mirroring `PLAN_PRESENTATION` in
 * `backend/app/config/plans.py`.
 */
export const PLAN_DISPLAY_NAMES: Record<CanonicalPlanType, string> = {
  plan_starter: "Starter",
  plan_agency_trial: "Agency Trial",
  plan_standard: "Standard",
  plan_specialist: "Specialist",
  plan_executive: "Executive",
};

export const PUBLIC_PLAN_TYPES = [
  "plan_starter",
  "plan_standard",
  "plan_specialist",
  "plan_executive",
] as const;

export const PUBLIC_PLAN_OPTIONS = PUBLIC_PLAN_TYPES.map((value) => ({
  value,
  label: PLAN_DISPLAY_NAMES[value],
}));

export type PlanCapabilityKey = keyof PlanCapabilitySet;

/**
 * The lowest plan that includes each capability, mirroring
 * `MINIMUM_PLAN_BY_FEATURE` in `backend/app/config/plans.py`.
 *
 * SIGV2-1221. An upgrade prompt that names a plan is making a promise, so the
 * plan it names has to be the plan the backend would actually require. Every
 * lock surface derives its plan name from this table instead of writing one
 * out by hand, which is how "Project monitoring requires Standard" survived
 * for a capability every plan already grants.
 * `planLocks.test.ts` pins this table against the backend file, so a backend
 * change that is not mirrored here fails the frontend suite rather than
 * shipping a prompt that names the wrong plan.
 */
export const MINIMUM_PLAN_BY_FEATURE: Partial<Record<PlanCapabilityKey, CanonicalPlanType>> = {
  seo: "plan_starter",
  geo: "plan_starter",
  aeo: "plan_starter",
  entity_analysis: "plan_starter",
  has_performance_sync: "plan_starter",
  has_pdf_audit_reports: "plan_starter",
  has_advisor_recommendations: "plan_standard",
  entity_authority: "plan_specialist",
  has_priority_pulse: "plan_specialist",
  has_predictive_intent_engine: "plan_specialist",
  has_semantic_graph_mapping: "plan_specialist",
  has_entity_enhancement: "plan_specialist",
  has_competitor_analysis: "plan_specialist",
  has_semantic_gap: "plan_specialist",
  has_advanced_reporting: "plan_specialist",
  can_schedule_audits: "plan_specialist",
  api_access: "plan_specialist",
  mcp_access: "plan_specialist",
  can_export_to_jira: "plan_specialist",
  can_use_slack_integration: "plan_specialist",
  can_use_teams_integration: "plan_specialist",
  can_use_workflow_automations: "plan_specialist",
  lead_widget: "plan_specialist",
  has_custom_pricing: "plan_executive",
  has_brand_integrity_guardrails: "plan_executive",
  has_eeat_trust_audit: "plan_executive",
  has_dedicated_strategist: "plan_executive",
  has_done_for_you_execution: "plan_executive",
  has_live_engine_tracking: "plan_starter",
  has_high_confidence_mode: "plan_specialist",
  has_white_label: "plan_executive",
  has_custom_domain: "plan_executive",
  pdf_white_label: "plan_executive",
  has_multi_workspace_federation: "plan_executive",
  cms_push: "plan_executive",
};

/** The lowest plan that includes a capability, or null when none declares it. */
export const minimumPlanForCapability = (
  capabilityKey: PlanCapabilityKey
): CanonicalPlanType | null => MINIMUM_PLAN_BY_FEATURE[capabilityKey] ?? null;

/**
 * The plan name an upgrade prompt for this capability may state.
 *
 * Returns null for a capability the lowest plan already grants: there is no
 * plan to upgrade to, so naming one would sell a customer something they have.
 */
export const requiredPlanLabelForCapability = (capabilityKey: PlanCapabilityKey): string | null => {
  const plan = minimumPlanForCapability(capabilityKey);
  if (!plan || plan === "plan_starter") {
    return null;
  }
  return PLAN_DISPLAY_NAMES[plan];
};

export const resolvePlanType = (planType: string | null | undefined): CanonicalPlanType | null => {
  if (typeof planType !== "string") {
    return null;
  }

  const normalized = planType.trim().toLowerCase();
  if (!normalized) {
    return null;
  }

  return PLAN_ALIASES[normalized] ?? null;
};

export const getPlanWeight = (planType: string | null | undefined): number => {
  const resolved = resolvePlanType(planType);
  return resolved ? PLAN_WEIGHTS[resolved] : PLAN_WEIGHTS.plan_starter;
};

export const hasPlanCapability = (
  planType: string | null | undefined,
  requiredPlan: string | null | undefined
): boolean => getPlanWeight(planType) >= getPlanWeight(requiredPlan);

export const resolvePlanCapabilities = (planType: string | null | undefined): PlanCapabilitySet => {
  const resolved = resolvePlanType(planType);
  if (!resolved) {
    return STARTER_CAPABILITIES;
  }

  return CAPABILITY_MATRIX[resolved] ?? STARTER_CAPABILITIES;
};

/**
 * The entitlement the API actually serves, with the table above as the
 * offline fallback only.
 *
 * `/api/billing/plans` returns `plans[].capabilities` straight out of the
 * backend `CAPABILITY_MATRIX` plus the `current_plan` the customer is on, so
 * when that payload has arrived it is the entitlement, full stop. Resolution
 * is fail-safe in both directions: once the current plan is identified, a key
 * the served plan does not grant is LOCKED, and the table is not consulted to
 * overrule it. The table is read only before the payload resolves, or when the
 * customer has no current plan on file.
 *
 * This is the same shape as the capability resolution in
 * `components/results/AuditWorkspace.tsx`, generalised so the settings screens
 * can share it rather than growing a second, divergent copy.
 */
export const resolveServedCapability = (
  served:
    | {
        current_plan?: string | null;
        plans?: { id: string; capabilities?: Record<string, unknown> }[];
      }
    | null
    | undefined,
  key: keyof PlanCapabilitySet,
  fallbackPlanType: string | null | undefined
): boolean => {
  const currentPlan = served?.current_plan;
  const servedPlan = currentPlan ? served?.plans?.find((plan) => plan.id === currentPlan) : null;

  if (servedPlan) {
    return servedPlan.capabilities?.[key] === true;
  }

  return resolvePlanCapabilities(fallbackPlanType)[key] === true;
};
