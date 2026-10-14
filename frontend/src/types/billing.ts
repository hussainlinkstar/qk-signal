export type BillingPlanId =
  | "plan_starter"
  | "plan_agency_trial"
  | "plan_standard"
  | "plan_specialist"
  | "plan_executive";

export type BillingPlanColor = "slate" | "primary" | "indigo" | "amber" | "teal";

export type BillingInterval = "month" | "year";

export type PlanCapabilities = {
  /** Null on custom-negotiated plans, where the price is not self-service. */
  monthly_price_usd: number | null;
  max_sites: number;
  max_audits: number;
  [key: string]: boolean | number | null;
};

/** How a plan is bought. `contact` plans have no self-service checkout. */
export type BillingPlanCta = "self_serve" | "contact" | "private";

export type BillingPlan = {
  id: BillingPlanId;
  price_id: string;
  annual_price_id?: string;
  checkout_available: boolean;
  annual_checkout_available?: boolean;
  annual_price_usd?: number | null;
  name: string;
  description: string;
  highlight: string;
  color: BillingPlanColor;
  features: string[];
  capabilities: PlanCapabilities;
  /**
   * True when the price is negotiated rather than listed (SIGV2-1211). The
   * card must then state "Custom pricing" and offer a contact route, because
   * `capabilities.monthly_price_usd` is deliberately null and would otherwise
   * render as "Free".
   */
  custom_priced?: boolean;
  cta?: BillingPlanCta;
  /**
   * Literal up-sell copy for a custom-priced plan, served by the backend.
   *
   * 🔴 Never derive these from a capability flag. They describe bespoke
   * consultancy work, not shipped entitlement, and the keys a derivation
   * would reach for (`has_white_label`, `has_multi_workspace_federation`,
   * `can_use_workflow_automations`) are withdrawn or unpublished.
   */
  bespoke_highlights?: string[];
};

export type PendingPlanChange = {
  target_plan: BillingPlanId;
  target_billing_interval: BillingInterval;
  effective_at: string;
  schedule_id: string;
};

export type BillingOverviewResponse = {
  plans: BillingPlan[];
  current_plan: BillingPlanId | null;
  status: string | null;
  billing_interval?: BillingInterval;
  pending_plan_change: PendingPlanChange | null;
  portal_available: boolean;
};

export type Invoice = {
  date: string | null;
  amounts: {
    amount_due: number | null;
    amount_paid: number | null;
    amount_remaining: number | null;
  };
  currency: string | null;
  status: string;
  hosted_invoice_url: string | null;
  invoice_pdf: string | null;
};

export type InvoiceResponse = {
  invoices: Invoice[];
};

export type CommitmentTierId = "growth" | "scale" | "enterprise";

export type CommitmentTier = {
  tier: CommitmentTierId;
  label: string;
  committed_credits: number;
  rate_per_credit: number;
  discount_pct: number;
  monthly_fee_usd: number;
  overage_rate: number;
};

export type CommitmentStatus = {
  id: number;
  tier: string;
  committed_credits: number;
  rate_per_credit: number;
  monthly_fee_usd: number;
  overage_rate: number;
  status: string;
  cancel_at_period_end: boolean;
  cycle_start: string | null;
  cycle_end: string | null;
  credits_used: number;
  credits_remaining: number;
  overage_credits: number;
  usage_pct: number;
  nearing_limit: boolean;
  /**
   * SIGV2-1128: the customer surface describes the cycle from these two flags.
   * The credit-denominated fields above are internal monitoring values and must
   * not reach a customer-facing render.
   */
  in_overage: boolean;
  pending_tier: string | null;
  pending_change_effective_at: string | null;
};

export type CommitmentSurfaceResponse = {
  eligible: boolean;
  locked_reason: string | null;
  current_plan: string | null;
  tiers: CommitmentTier[];
  commitment: CommitmentStatus | null;
};

export type CommitmentActionResponse = {
  message?: string;
  commitment?: CommitmentStatus | null;
};

export type TrialStatus = {
  is_trial: boolean;
  trial_active: boolean;
  trial_expired: boolean;
  trial_plan: string | null;
  trial_started_at: string | null;
  trial_ends_at: string | null;
  days_remaining: number;
  credits_remaining: number;
  credits_total: number;
  audits_used: number;
  audits_total: number;
  concierge_completed: boolean;
  limits_reached: boolean;
  limit_reason: "trial_expired" | "audits_exhausted" | null;
};

// ---------------------------------------------------------------------------
//  Usage analytics types
// ---------------------------------------------------------------------------

export type ScanUsagePoint = {
  date: string;
  scans_used: number;
};

export type ScanAllowanceWarning = {
  show_warning: boolean;
  /** Scans left in the current 30-day window. */
  remaining: number;
  /** Size of the scan allowance. */
  allowance: number;
  pct_remaining: number | null;
  /** Which allowance is being measured. The customer-facing allowance is
      scans; the backend always reports ``"scans"``. */
  unit: "scans";
};

export type PlanRecommendation = {
  recommended_plan: string;
  recommended_plan_label: string;
  reasons: string[];
  message: string;
} | null;

export type UsageAnalyticsResponse = {
  daily_usage: ScanUsagePoint[];
  scans_used: number;
  scans_remaining: number | null;
  /** Monthly scan allowance; null when the plan is uncapped. */
  scan_allowance: number | null;
  reset_at: string | null;
  renewal_date: string | null;
  current_plan: string;
  burn_rate_7d: number;
  burn_rate_30d: number;
  days_until_depletion: number | null;
  depletion_date: string | null;
  will_exhaust_before_renewal: boolean;
  projected_overage: number;
  /**
   * SIGV2-1306: null when a projection was published, otherwise why it was
   * not, so the surface can say that rather than printing a figure the
   * backend would not stand behind.
   */
  projection_reason: "insufficient_history" | "no_usage_yet" | "allowance_uncapped" | null;
  /** Days since the first recorded usage, not the number of rows returned. */
  observed_days: number;
  warning: ScanAllowanceWarning;
  recommendation: PlanRecommendation;
};
