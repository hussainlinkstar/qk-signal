"use client";

import React, { useMemo } from "react";
import { Check, Minus } from "lucide-react";
import { cx } from "@/components/ui/utils";
import type { BillingPlan, BillingPlanId } from "@/types/billing";

type PlanComparisonMatrixProps = {
  plans: BillingPlan[];
  currentPlanId: BillingPlanId | null;
};

const ORDERED_CAPABILITY_KEYS = [
  "monthly_price_usd",
  "max_sites",
  "max_audits",
  "max_parallel_audits",
  "max_workflows_per_project",
  "has_competitor_analysis",
  "has_semantic_gap",
  "has_advanced_reporting",
  "can_schedule_audits",
  "can_export_to_jira",
  "api_access",
  "has_white_label",
  "pdf_white_label",
  "has_brand_integrity_guardrails",
  "has_eeat_trust_audit",
  "has_dedicated_strategist",
  "has_high_confidence_mode",
  "has_priority_pulse",
  "has_predictive_intent_engine",
  "has_semantic_graph_mapping",
  "has_entity_enhancement",
  "has_parallel_audit_execution",
  "has_volume_serp_api",
  "has_dedicated_infrastructure",
  "has_multi_workspace_federation",
  "has_sla_guarantee",
  "has_custom_pricing",
  "has_pdf_audit_reports",
  "has_performance_sync",
  "has_baseline_geo_visibility_index",
  "has_aeo_answerability_score",
  "has_core_entity_identity_check",
  "entity_analysis",
  "seo",
  "geo",
  "aeo",
] as const;

const CAPABILITY_LABELS: Record<string, string> = {
  monthly_price_usd: "Monthly price",
  max_sites: "Tracked sites",
  max_audits: "Scans / month",
  max_parallel_audits: "Max parallel assessments",
  max_workflows_per_project: "Max workflows per project",
  has_competitor_analysis: "Competitor analysis",
  has_semantic_gap: "Semantic gap analysis",
  has_advanced_reporting: "Advanced reporting",
  can_schedule_audits: "Scheduled assessments",
  can_export_to_jira: "Jira export",
  // SIGV2-1210: one row for both halves of the same surface. The MCP server
  // authenticates with the same API key and is granted by the same plans, so
  // a second row would read as a second thing to buy. SIGV2-1211 shipped this
  // as "API access" because the server did not exist yet.
  api_access: "API & MCP access",
  has_white_label: "White-label workspace",
  pdf_white_label: "White-label PDFs",
  has_brand_integrity_guardrails: "Brand guardrails",
  has_eeat_trust_audit: "E-E-A-T trust assessment",
  has_dedicated_strategist: "Dedicated strategist",
  has_high_confidence_mode: "High Confidence mode",
  has_priority_pulse: "Priority monitoring",
  has_predictive_intent_engine: "Predictive intent engine",
  has_semantic_graph_mapping: "Semantic graph mapping",
  has_entity_enhancement: "Entity enhancement",
  has_parallel_audit_execution: "Parallel assessment execution",
  has_volume_serp_api: "Volume SERP API",
  has_dedicated_infrastructure: "Dedicated infrastructure",
  has_multi_workspace_federation: "Multi-workspace federation",
  has_sla_guarantee: "99.9% SLA guarantee",
  has_custom_pricing: "Custom pricing support",
  has_pdf_audit_reports: "PDF assessment reports",
  has_performance_sync: "Performance sync",
  has_baseline_geo_visibility_index: "AI visibility index",
  has_aeo_answerability_score: "Answer Engine Index readiness",
  has_core_entity_identity_check: "Entity identity checks",
  entity_analysis: "Entity analysis",
  seo: "SEO assessments",
  geo: "AI visibility assessments",
  aeo: "Answer engine assessments",
  // These ten differ across plans, so they always render. Without a label they
  // fell through to humanizeCapabilityKey and showed up as "Cms Push",
  // "Lead Widget" and "Use Slack Integration". Wording follows signal-MVP's
  // comparison rows where it has them.
  can_use_slack_integration: "Slack integration",
  can_use_teams_integration: "Teams integration",
  can_use_workflow_automations: "Workflow automations",
  has_custom_domain: "Custom domain",
  has_done_for_you_execution: "Done-for-you execution",
  has_live_engine_tracking: "Live engine tracking",
  has_advisor_recommendations: "Advisor recommendations",
  entity_authority: "Entity authority",
  cms_push: "CMS push",
  lead_widget: "Lead widget",
  // "Max tracked keywords" follows the approved pricing table's row name
  // (SIGV2-1211), matching the "Max parallel assessments" and "Max workflows
  // per project" rows beside it. This row is the keyword cap
  // (`max_tracked_keywords`, enforced by target_keyword_limit_service), not
  // the separate tracked-prompt cap SIGV2-1188 settled; the approved table's
  // 5/10/50/200 is this ladder and it is unchanged.
  max_tracked_keywords: "Max tracked keywords",
};

// SIGV2-1206: the comparison is a curated publishing allowlist, not the
// served entitlement matrix. A key renders a row or a badge only when it is
// listed here, which means a capability the API starts serving tomorrow shows
// nothing until it is deliberately published. The entitlement keys stay
// served and keep gating real behaviour; this set only decides what the tab
// is allowed to advertise.
//
// Served but deliberately unpublished:
// - can_use_slack_integration, can_use_teams_integration,
//   has_dedicated_strategist, has_done_for_you_execution: withdrawn from
//   customer surfaces on 6 Oct (SIGV2-1167, 1168).
// - cms_push: CMS delivery is not an active MVP journey
//   (SHOW_CMS_FIX_DELIVERY is off in ConnectionsPanels).
// - lead_widget, entity_authority: standalone offers with no approved active
//   MVP journey; the used audit-time entity analysis is the separate
//   entity_analysis key and stays published.
// - can_use_workflow_automations, max_workflows_per_project: Automations is
//   Coming Soon (SIGV2-1196), so neither the boolean nor the quota may be
//   advertised until it ships.
// - credits_per_month, monthly_price_usd and the all-false infrastructure
//   flags (has_parallel_audit_execution, has_volume_serp_api,
//   has_dedicated_infrastructure, has_sla_guarantee): internal, already the
//   price, or grants nothing today. has_custom_ai_model_routing was in this
//   list until SIGV2-1120 deleted the key from the capability contract
//   outright, so it is no longer served and has nothing to unpublish.
const PUBLISHABLE_CAPABILITY_KEYS = new Set([
  "max_sites",
  "max_audits",
  "max_tracked_keywords",
  "max_parallel_audits",
  "seo",
  "geo",
  "aeo",
  "entity_analysis",
  "has_live_engine_tracking",
  "has_baseline_geo_visibility_index",
  "has_aeo_answerability_score",
  "has_core_entity_identity_check",
  "has_performance_sync",
  "has_pdf_audit_reports",
  "has_advisor_recommendations",
  "has_priority_pulse",
  "has_high_confidence_mode",
  "has_predictive_intent_engine",
  "has_semantic_graph_mapping",
  "has_entity_enhancement",
  "has_brand_integrity_guardrails",
  "has_eeat_trust_audit",
  "has_competitor_analysis",
  "has_semantic_gap",
  "has_white_label",
  "has_custom_domain",
  "has_advanced_reporting",
  "can_schedule_audits",
  "pdf_white_label",
  "api_access",
  "can_export_to_jira",
  "has_multi_workspace_federation",
  "has_custom_pricing",
]);

const formatUsd = (value: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);

const formatMetricValue = (key: string, rawValue: number | null | undefined) => {
  // Custom-negotiated plans come back with a null price from both catalogs, so
  // the matrix has to say "Custom" here exactly like the marketing card does,
  // instead of falling through to the generic "-" placeholder.
  if (rawValue === null && key === "monthly_price_usd") {
    return "Custom";
  }

  // Handle undefined or missing values
  if (rawValue === undefined || rawValue === null) {
    if (key === "max_sites") {
      // Special handling for tracked sites based on plan context
      return "-";
    }
    return "-";
  }

  if (key === "monthly_price_usd") {
    return `${formatUsd(rawValue)}/mo`;
  }

  // Special handling for -1 values (unlimited)
  if (rawValue === -1 || rawValue < 0) {
    return "Unlimited";
  }

  return new Intl.NumberFormat("en-US").format(rawValue);
};

export default function PlanComparisonMatrix({ plans, currentPlanId }: PlanComparisonMatrixProps) {
  const comparisonKeys = useMemo(() => {
    const union = new Set<string>();
    plans.forEach((plan) => {
      Object.keys(plan.capabilities).forEach((key) => union.add(key));
    });

    return (
      Array.from(union)
        // The price is already in each plan's column header, and signal-MVP's
        // comparison table has no price row, so it would just repeat itself.
        .filter((key) => key !== "monthly_price_usd")
        .filter((key) => PUBLISHABLE_CAPABILITY_KEYS.has(key))
        // No label means no approved copy exists, so the row renders
        // nothing rather than falling back to a titled flag name.
        .filter((key) => key in CAPABILITY_LABELS)
        .filter((key) => {
          const values = plans.map((plan) => plan.capabilities[key]);
          return new Set(values.map((value) => String(value))).size > 1;
        })
        .sort((left, right) => {
          const leftIndex = ORDERED_CAPABILITY_KEYS.indexOf(
            left as (typeof ORDERED_CAPABILITY_KEYS)[number]
          );
          const rightIndex = ORDERED_CAPABILITY_KEYS.indexOf(
            right as (typeof ORDERED_CAPABILITY_KEYS)[number]
          );
          if (leftIndex === -1 && rightIndex === -1) {
            return left.localeCompare(right);
          }
          if (leftIndex === -1) {
            return 1;
          }
          if (rightIndex === -1) {
            return -1;
          }
          return leftIndex - rightIndex;
        })
    );
  }, [plans]);

  const sharedFoundation = useMemo(() => {
    const union = new Set<string>();
    plans.forEach((plan) => {
      Object.entries(plan.capabilities).forEach(([key, value]) => {
        if (typeof value === "boolean") {
          union.add(key);
        }
      });
    });

    return Array.from(union)
      .filter((key) => PUBLISHABLE_CAPABILITY_KEYS.has(key))
      .filter((key) => key in CAPABILITY_LABELS)
      .filter((key) => plans.every((plan) => plan.capabilities[key] === true))
      .sort((left, right) => {
        const leftIndex = ORDERED_CAPABILITY_KEYS.indexOf(
          left as (typeof ORDERED_CAPABILITY_KEYS)[number]
        );
        const rightIndex = ORDERED_CAPABILITY_KEYS.indexOf(
          right as (typeof ORDERED_CAPABILITY_KEYS)[number]
        );
        if (leftIndex === -1 && rightIndex === -1) {
          return left.localeCompare(right);
        }
        if (leftIndex === -1) {
          return 1;
        }
        if (rightIndex === -1) {
          return -1;
        }
        return leftIndex - rightIndex;
      })
      .slice(0, 6);
  }, [plans]);

  if (plans.length === 0 || comparisonKeys.length === 0) {
    return null;
  }

  // Get tracked sites value for each plan from the max_sites capability
  const getTrackedSitesValue = (plan: BillingPlan) => {
    const maxSites = plan.capabilities.max_sites;
    if (maxSites === undefined || maxSites === 0) {
      // For Standard and Specialist plans that might have this missing
      if (plan.id === "plan_standard") return 1;
      if (plan.id === "plan_specialist") return 10;
      return 0;
    }
    return maxSites;
  };

  return (
    <div className="overflow-hidden rounded-md border border-(--line) bg-(--line-2)">
      <section aria-labelledby="plan-comparison-heading">
        <div className="border-b border-(--line) px-6 py-6 md:px-8">
          <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-(--t-3)">
                Compare Every Capability
              </p>
              <h3 id="plan-comparison-heading" className="mt-2 text-xl font-semibold text-(--t-1)">
                See what changes before you upgrade
              </h3>
              <p className="mt-2 max-w-3xl text-sm text-(--t-2)">
                Pricing, usage capacity, and premium delivery capabilities are compared side by side
                from the live billing API.
              </p>
            </div>
            <div className="rounded-md border border-(--line) bg-(--line-2) px-4 py-3 text-xs text-(--t-3)">
              Only differentiating capabilities are shown below.
            </div>
          </div>

          {sharedFoundation.length > 0 ? (
            <div className="mt-5 flex flex-wrap gap-2">
              {sharedFoundation.map((key) => (
                <span
                  key={key}
                  className="rounded-full bg-(--line-2) px-3 py-1 text-xs text-(--t-2) border border-(--line)"
                >
                  {CAPABILITY_LABELS[key]}
                </span>
              ))}
            </div>
          ) : null}
        </div>

        <div className="overflow-x-auto">
          <table
            aria-label="Plan comparison"
            className="w-full min-w-[760px] border-collapse text-sm"
          >
            <thead>
              <tr className="border-b border-(--line) bg-(--paper) text-left">
                <th className="px-4 py-3 font-mono text-[10px] font-normal uppercase tracking-[0.09em] text-(--t-3)">
                  Capability
                </th>
                {plans.map((plan) => {
                  const isCurrent = currentPlanId === plan.id;
                  return (
                    <th
                      key={plan.id}
                      className={cx(
                        "px-4 py-3 align-top font-mono text-[10px] uppercase tracking-[0.09em]",
                        isCurrent &&
                          "border-b-2 border-b-(--purple) bg-[linear-gradient(180deg,rgba(147,51,234,.07),rgba(37,99,235,.03))] text-(--purple)"
                      )}
                    >
                      <div className="flex flex-col gap-2 items-center text-center">
                        <div className="flex items-center gap-2">
                          <span className="font-(family-name:--disp) text-sm font-semibold normal-case tracking-normal text-(--t-1)">
                            {plan.name}
                          </span>
                          {isCurrent ? (
                            <span className="text-[10px] font-semibold normal-case tracking-normal text-(--purple)">
                              Current plan
                            </span>
                          ) : null}
                        </div>
                        <span className="text-xs text-(--t-3)">
                          {plan.capabilities.monthly_price_usd === null
                            ? "Custom"
                            : `${formatUsd(plan.capabilities.monthly_price_usd)}/mo`}
                        </span>
                      </div>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {comparisonKeys.map((key) => (
                <tr
                  key={key}
                  className="border-b border-(--line-2) last:border-b-0 hover:bg-(--line-2) transition-colors"
                >
                  <th className="px-4 py-3 text-left text-[13px] font-medium text-(--t-2)">
                    {CAPABILITY_LABELS[key]}
                  </th>
                  {plans.map((plan) => {
                    let value = plan.capabilities[key];
                    const isCurrent = currentPlanId === plan.id;

                    // Special handling for tracked sites
                    if (key === "max_sites" && (value === undefined || value === 0)) {
                      value = getTrackedSitesValue(plan);
                    }

                    return (
                      <td
                        key={`${plan.id}-${key}`}
                        className={cx(
                          "px-4 py-3 text-center text-[13px]",
                          isCurrent &&
                            "bg-[linear-gradient(180deg,rgba(147,51,234,.07),rgba(37,99,235,.03))]"
                        )}
                      >
                        {typeof value === "number" ? (
                          <span className="font-(family-name:--disp) font-extrabold text-(--t-1)">
                            {formatMetricValue(key, value)}
                          </span>
                        ) : value ? (
                          <span className="inline-flex items-center justify-center text-(--purple)">
                            <Check aria-hidden="true" className="h-4 w-4" />
                            <span className="sr-only">Included</span>
                          </span>
                        ) : (
                          <span className="inline-flex items-center justify-center text-(--t-3)">
                            <Minus aria-hidden="true" className="h-4 w-4" />
                            <span className="sr-only">Not included</span>
                          </span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
