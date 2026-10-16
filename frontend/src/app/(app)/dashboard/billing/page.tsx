"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  ArrowUpRight,
  BarChart3,
  CreditCard,
  History,
  Loader2,
  Zap,
  Check,
  Shield,
  Layers,
  Package,
  TrendingUp,
} from "lucide-react";
import BillingSalesContactCard from "@/components/billing/BillingSalesContactCard";
import BillingIntervalToggle from "@/components/billing/BillingIntervalToggle";
import ScanAllowanceCard from "@/components/billing/ScanAllowanceCard";
import ScanUsageChart from "@/components/billing/ScanUsageChart";
import PlanChangeModal from "@/components/billing/PlanChangeModal";
import PlanComparisonMatrix from "@/components/billing/PlanComparisonMatrix";
import PlanRecommendationBanner from "@/components/billing/PlanRecommendationBanner";
import DashboardPageIntro from "@/components/dashboard/DashboardPageIntro";
import WorkspacePageFrame from "@/components/dashboard/WorkspacePageFrame";
import SignalAlert from "@/components/signal/SignalAlert";
import SignalTabs, { SignalTabPanel } from "@/components/signal/SignalTabs";
import Button, { buttonClasses } from "@/components/ui/Button";
import { GlassCard } from "@/components/ui/GlassComponents";
import { cx } from "@/components/ui/utils";
import { useBillingSettings } from "@/hooks/useBillingSettings";
import { useScanUsage } from "@/hooks/useScanUsage";
import { resolveQikoSiteUrl } from "@/lib/qiko-site-url";
import type { BillingInterval, BillingPlan, BillingPlanId } from "@/types/billing";
import { TIER_DISPLAY } from "@/constants/tiers";

const EMPTY_PLANS: BillingPlan[] = [];

const formatUsd = (value: number, maximumFractionDigits = 2) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits,
    minimumFractionDigits: maximumFractionDigits === 0 ? 0 : undefined,
  }).format(value);

const formatCompactNumber = (value: number) => new Intl.NumberFormat("en-US").format(value);

const formatPlanLimit = (value: number, noun: string) =>
  value < 0 ? `Unlimited ${noun}` : `Up to ${formatCompactNumber(value)} ${noun}`;

type PlanCapabilityBadge = { label: string; icon?: React.ReactNode };

const buildPlanCapabilityBadges = (plan: BillingPlan): PlanCapabilityBadge[] => {
  const badges: PlanCapabilityBadge[] = [];

  // SIGV2-1211: a plan carrying bespoke highlights states those literally and
  // derives nothing. Jake's framing is that the Executive extras are "an
  // up-sell to customers that we would custom build, not necessarily things
  // that are in Executive right now", so the badges must not be read off
  // `has_white_label` or `has_multi_workspace_federation`: both are offers
  // withdrawn from customer surfaces (SIGV2-1167) whose entitlement keys are
  // still set, so deriving a badge from them would advertise as shipped what
  // the product sells as consultancy. Returning early is what makes that
  // impossible rather than merely unlikely.
  if (plan.bespoke_highlights?.length) {
    return plan.bespoke_highlights.slice(0, 3).map((label) => ({ label }));
  }

  if (plan.capabilities.has_high_confidence_mode) {
    badges.push({ label: TIER_DISPLAY.deep_judgment, icon: <Shield className="h-3 w-3" /> });
  }
  if (plan.capabilities.has_parallel_audit_execution) {
    badges.push({ label: "Parallel", icon: <Layers className="h-3 w-3" /> });
  }
  if (plan.capabilities.has_sla_guarantee) {
    badges.push({ label: "99.9% SLA" });
  }
  if (plan.capabilities.has_multi_workspace_federation) {
    badges.push({ label: "Multi-Workspace" });
  }
  if (plan.capabilities.has_white_label) {
    badges.push({ label: "White Label" });
  }
  if (plan.capabilities.api_access) {
    badges.push({ label: "API Access" });
  }
  // SIGV2-1168: the dedicated-strategist offer was withdrawn - it names a
  // human service nobody delivers, so no badge is pushed for
  // `has_dedicated_strategist`. The capability key stays on the plan and the
  // badge can return if the offer ever becomes real again.

  return badges.slice(0, 3);
};

const formatPlanName = (planId: string | null | undefined) =>
  String(planId ?? "")
    .split("_")
    .filter(Boolean)
    .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
    .join(" ") || "Free";

const formatBillingInterval = (interval: BillingInterval) =>
  interval === "year" ? "Annual billing" : "Monthly billing";

const formatDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  });

const joinPlanNames = (names: string[]) => {
  if (names.length <= 1) return names[0] ?? "";
  if (names.length === 2) return `${names[0]} or ${names[1]}`;
  return `${names.slice(0, -1).join(", ")}, or ${names[names.length - 1]}`;
};

/* SIGV2-1171: the page's own `StatusAlert` is gone. It drew three tones out of
   raw Tailwind palette colours (blue-400, amber-400, rose-400) that are not
   Signal tokens, told the tones apart by colour and a 20px icon, and had no
   `role`, so nothing was announced. Every outcome now goes through the shared
   `SignalAlert`, which is the approved `.alert` anatomy from the component
   sheet. */

// Plan Card Component
const PlanCard = ({
  plan,
  isCurrent,
  canCheckout,
  hasActiveSubscription,
  selfServicePlanChangesAllowed,
  billingInterval,
  activeBillingInterval,
  planActionsDisabled,
  onCheckout,
  onPlanChange,
  isLoading,
}: {
  plan: BillingPlan;
  isCurrent: boolean;
  canCheckout: boolean;
  hasActiveSubscription: boolean;
  selfServicePlanChangesAllowed: boolean;
  billingInterval: BillingInterval;
  activeBillingInterval: BillingInterval;
  planActionsDisabled: boolean;
  onCheckout: () => void;
  onPlanChange: () => void;
  isLoading: boolean;
}) => {
  const capabilityBadges = buildPlanCapabilityBadges(plan);
  const isAnnual = billingInterval === "year";
  const isCurrentIntervalChange = isCurrent && billingInterval !== activeBillingInterval;
  const isSelectedIntervalAvailable = isAnnual
    ? plan.annual_checkout_available
    : plan.checkout_available;
  const monthlyPrice = plan.capabilities.monthly_price_usd;
  const annualTotal = plan.annual_price_usd;
  // SIGV2-1211: a negotiated plan has no figure to show, discount or divide.
  // `custom_priced` is checked rather than inferring from a null price so the
  // card states "Custom pricing" deliberately, and never because a payload
  // happened to omit a number.
  const isCustomPriced = plan.custom_priced === true || monthlyPrice === null;
  const effectiveMonthly =
    monthlyPrice === null ? null : isAnnual && annualTotal ? annualTotal / 12 : monthlyPrice;
  const contactOnly = isCustomPriced || plan.cta === "contact";
  const contactHref = `${resolveQikoSiteUrl()}/labs#contact`;

  return (
    <GlassCard
      className={cx(
        "group relative flex h-full min-w-0 flex-col gap-5 p-5 transition-all duration-200 sm:gap-6 sm:p-6",
        "border-0 bg-white",
        isCurrent
          ? "ring-1 ring-(--ink)/15"
          : "hover:bg-[#FBFBFC]"
      )}
    >
      {/* Plan Header */}
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-(--foreground)">{plan.name}</h3>
          {isCurrent && (
            <span className="flex items-center gap-1.5 text-xs text-(--primary)">
              <span className="h-1.5 w-1.5 rounded-full bg-(--primary)" />
              Current
            </span>
          )}
        </div>

        {/* Fixed-height zones keep every card's price, metrics and button on
            the same line across the row: a one-line highlight and a missing
            badge row used to shift each card's contents by a different
            amount. */}
        <p className="min-h-10 text-sm text-(--muted-foreground) line-clamp-2">{plan.highlight}</p>

        {/* Capability Badges - one reserved row. A badge that does not fit is
            clipped, not wrapped to a second row. */}
        <div className="flex h-6 flex-wrap items-start gap-1.5 overflow-hidden">
          {capabilityBadges.map((badge) => (
            <span
              key={badge.label}
              className="flex items-center gap-1 rounded-full bg-(--surface-elevated) px-2 py-1 text-xs text-(--foreground)"
            >
              {badge.icon}
              {badge.label}
            </span>
          ))}
        </div>
      </div>

      {/* Pricing - the annual line keeps its slot whether or not it renders,
          so the metrics block sits at the same height on every card. */}
      <div className="flex flex-col gap-1">
        <div className="flex items-baseline gap-2">
          {isCustomPriced ? (
            // Not "Free" and not "$0": this is the most expensive plan, and a
            // zero would read as the cheapest.
            <span className="text-3xl font-bold text-(--foreground)">Custom pricing</span>
          ) : monthlyPrice === 0 ? (
            <span className="text-3xl font-bold text-(--foreground)">Free</span>
          ) : (
            <>
              <span className="text-3xl font-bold text-(--foreground)">
                {formatUsd(effectiveMonthly ?? 0, 0)}
              </span>
              <span className="text-sm text-(--muted-foreground)">/ month</span>
            </>
          )}
        </div>
        <p className="min-h-4 text-xs text-emerald-400">
          {!isCustomPriced && isAnnual && annualTotal
            ? `${formatUsd(annualTotal, 0)} billed annually`
            : ""}
        </p>
      </div>

      {/* Key Metrics */}
      <div className="grid gap-2">
        <div className="flex items-center justify-between rounded-lg bg-(--surface-elevated) p-3">
          <span className="text-xs text-(--muted-foreground)">Audits</span>
          <span className="text-sm font-medium text-(--foreground)">
            {plan.capabilities.max_audits < 0
              ? "Unlimited"
              : `${formatCompactNumber(plan.capabilities.max_audits)}/mo`}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-(--surface-elevated) p-3">
          <span className="text-xs text-(--muted-foreground)">Sites</span>
          <span className="text-sm font-medium text-(--foreground)">
            {plan.capabilities.max_sites < 0
              ? "Unlimited"
              : formatCompactNumber(plan.capabilities.max_sites)}
          </span>
        </div>
        <div className="flex items-center justify-between rounded-lg bg-(--surface-elevated) p-3">
          <span className="text-xs text-(--muted-foreground)">Per audit</span>
          <span className="text-sm font-medium text-(--foreground)">
            {/* No price means no unit price. "Free" was the fallback for a
                zero price, and applying it to a negotiated plan would state
                the opposite of the truth. */}
            {isCustomPriced
              ? "Custom"
              : effectiveMonthly !== null &&
                  effectiveMonthly > 0 &&
                  plan.capabilities.max_audits > 0
                ? formatUsd(effectiveMonthly / plan.capabilities.max_audits, 3)
                : "Free"}
          </span>
        </div>
      </div>

      {/* Features List — flex-1 fills leftover height so CTAs align across cards */}
      <div className="flex min-h-[7.5rem] flex-1 flex-col gap-2">
        {plan.features.slice(0, 5).map((feature, index) => (
          <div key={index} className="flex items-start gap-2">
            <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-(--good)" />
            <span className="text-xs text-(--muted-foreground)">{feature}</span>
          </div>
        ))}
      </div>

      {/* Action Button — solid ink pills, not plain text */}
      <div className="mt-auto border-t border-[#EEF1F6] pt-4">
        {/* SIGV2-1211: a contact-only plan never offers checkout. The backend
            refuses it too (`_raise_for_non_self_service_plan` 409s on a
            `contact` CTA), so this is the same decision stated once on each
            side rather than a presentational nicety that a crafted request
            could step around. Checked before `isCurrent` so an existing
            Executive subscriber sees the contact route as well, instead of a
            billing-interval toggle for a price nobody published. */}
        {contactOnly ? (
          <a
            href={contactHref}
            className={cx(buttonClasses({ variant: "inverse", size: "md" }), "w-full")}
          >
            Contact us
          </a>
        ) : hasActiveSubscription && !selfServicePlanChangesAllowed ? null : isCurrent ? (
          <Button
            onClick={onPlanChange}
            loading={isLoading}
            variant={isCurrentIntervalChange ? "inverse" : "ghost"}
            size="md"
            className="w-full"
            disabled={
              !isCurrentIntervalChange ||
              !isSelectedIntervalAvailable ||
              isLoading ||
              planActionsDisabled
            }
          >
            {isCurrentIntervalChange ? "Change Billing Interval" : "Active plan"}
          </Button>
        ) : hasActiveSubscription ? (
          <Button
            onClick={onPlanChange}
            loading={isLoading}
            variant="inverse"
            size="md"
            className="w-full"
            disabled={isLoading || planActionsDisabled || !isSelectedIntervalAvailable}
          >
            Change Plan
          </Button>
        ) : (
          <Button
            onClick={onCheckout}
            loading={isLoading}
            variant="inverse"
            size="md"
            className="w-full"
            disabled={
              isLoading ||
              planActionsDisabled ||
              !canCheckout ||
              (isAnnual && !plan.annual_checkout_available)
            }
          >
            {canCheckout && (!isAnnual || plan.annual_checkout_available)
              ? "Subscribe"
              : "Unavailable"}
          </Button>
        )}
      </div>
    </GlassCard>
  );
};

export default function BillingPage() {
  const searchParams = useSearchParams();
  const settings = useBillingSettings();
  const usage = useScanUsage(30);
  const [planChangeTarget, setPlanChangeTarget] = useState<BillingPlanId | null>(null);
  const [activeSection, setActiveSection] = useState(() => {
    const requested = searchParams.get("section");
    const known = ["overview", "usage", "plans", "comparison"];
    return requested && known.includes(requested) ? requested : "overview";
  });
  const [billingInterval, setBillingInterval] = useState<BillingInterval>("month");
  const billingIntervalInitializedRef = useRef(false);
  const billingIntervalInteractedRef = useRef(false);
  const plans = settings.billingOverview?.plans ?? EMPTY_PLANS;
  const visiblePlans = useMemo(
    () => plans.filter((plan) => plan.id !== "plan_agency_trial"),
    [plans]
  );
  // Deep-linked recommended plan (e.g. from an "Upgrade to Pro" gate CTA):
  // ?section=plans&plan=plan_specialist → scroll to and highlight that card.
  const highlightPlanId = searchParams.get("plan");
  const activeBillingInterval = settings.billingOverview?.billing_interval;

  useEffect(() => {
    if (
      activeBillingInterval &&
      !billingIntervalInitializedRef.current &&
      !billingIntervalInteractedRef.current
    ) {
      setBillingInterval(activeBillingInterval);
      billingIntervalInitializedRef.current = true;
    }
  }, [activeBillingInterval]);

  const handleBillingIntervalChange = (interval: BillingInterval) => {
    billingIntervalInteractedRef.current = true;
    setBillingInterval(interval);
  };

  useEffect(() => {
    if (activeSection !== "plans" || !highlightPlanId) return;
    const el = document.getElementById(`plan-${highlightPlanId}`);
    if (el) {
      const t = window.setTimeout(
        () => el.scrollIntoView({ behavior: "smooth", block: "center" }),
        120
      );
      return () => window.clearTimeout(t);
    }
  }, [activeSection, highlightPlanId, plans.length]);

  const currentPlan = useMemo(
    () => plans.find((plan) => plan.id === settings.billingOverview?.current_plan) ?? null,
    [plans, settings.billingOverview?.current_plan]
  );
  const pendingPlanChange = ["active", "trialing"].includes(settings.billingOverview?.status ?? "")
    ? (settings.billingOverview?.pending_plan_change ?? null)
    : null;
  const pendingPlanName = pendingPlanChange
    ? (plans.find((plan) => plan.id === pendingPlanChange.target_plan)?.name ??
      formatPlanName(pendingPlanChange.target_plan))
    : null;

  const currentPlanLabel = useMemo(() => {
    const currentPlanId = settings.billingOverview?.current_plan;
    if (!currentPlanId) {
      // SIGV2-1178: a failed plan load must not print a confident wrong
      // answer. "Free" is only honest when the catalogue actually loaded and
      // reported no subscription.
      return settings.error ? "Unavailable" : "Free";
    }
    if (currentPlanId === "plan_agency_trial") {
      return "Trial Plan";
    }
    if (currentPlanId === "plan_executive") {
      return "Executive";
    }
    if (currentPlanId === "plan_specialist") {
      return "Specialist";
    }
    if (currentPlanId === "plan_standard") {
      return "Standard";
    }
    if (currentPlanId === "plan_starter") {
      return "Starter";
    }
    return currentPlan?.name ?? currentPlanId;
  }, [currentPlan, settings.billingOverview?.current_plan, settings.error]);

  const isPortalAvailable = settings.billingOverview?.portal_available ?? false;
  const hasActiveSubscription = Boolean(
    settings.billingOverview?.current_plan &&
    settings.billingOverview?.status &&
    ["active", "trialing"].includes(settings.billingOverview.status)
  );
  const selfServicePlanChangesAllowed =
    settings.billingOverview?.current_plan !== "plan_agency_trial";
  const highConfidenceEligiblePlans = useMemo(
    () =>
      visiblePlans
        .filter((plan) => plan.capabilities.has_high_confidence_mode === true)
        .map((plan) => plan.name),
    [visiblePlans]
  );
  const highConfidenceUnlockLabel = useMemo(
    () =>
      joinPlanNames(
        highConfidenceEligiblePlans.length ? highConfidenceEligiblePlans : ["Executive"]
      ),
    [highConfidenceEligiblePlans]
  );
  const currentPlanSupportsHighConfidence =
    currentPlan?.capabilities.has_high_confidence_mode === true;
  const currentPlanDisplayName =
    currentPlan?.name ?? formatPlanName(settings.billingOverview?.current_plan);

  // Section navigation
  const sections = [
    { id: "overview", label: "Overview", icon: CreditCard },
    { id: "usage", label: "Usage", icon: TrendingUp },
    { id: "plans", label: "Plans", icon: Package },
    // The Commitments tab is withdrawn pending commitment checkout
    // configuration (SIGV2-1165); the Stripe price ids are unset in this
    // environment, so every checkout attempt it offered would fail.
    { id: "comparison", label: "Comparison", icon: BarChart3 },
  ];

  if (settings.isLoading) {
    return (
      <div role="status" className="flex min-h-[60vh] flex-col items-center justify-center gap-4">
        <Loader2 className="h-10 w-10 animate-spin text-(--muted-foreground)" aria-hidden="true" />
        <p className="text-xs text-(--muted-foreground)">Loading billing overview...</p>
      </div>
    );
  }

  return (
    <WorkspacePageFrame backHref="/dashboard" backLabel="Back to Workspace Overview">
      <div className="min-w-0 space-y-6">
        {/* Page Header */}
        <DashboardPageIntro title="Billing">
          Manage your subscription, invoices, and upgrade options
        </DashboardPageIntro>

        {/* Status Alerts */}
        {pendingPlanChange && (
          <SignalAlert tone="info" title="Plan change scheduled">
            Your subscription will change to {pendingPlanName} with{" "}
            {formatBillingInterval(pendingPlanChange.target_billing_interval)} on{" "}
            <span className="font-semibold text-(--t-1)">
              {formatDate(pendingPlanChange.effective_at)}
            </span>
            .
          </SignalAlert>
        )}

        {/* SIGV2-1171: the two failure channels sit above the tab panels, not
            inside one of them. `useBillingSettings` writes every portal and
            checkout refusal to one `actionError`, and the page only rendered
            it in Overview - so a checkout refused from the Plans tab left an
            unchanged plan card and no message anywhere on screen, which is the
            "nothing happened" report this ticket exists for. The 409 conflict
            path makes it sharper still: it routes the customer to
            ?section=plans, away from the only place the reason was printed. */}
        {settings.actionError && (
          <SignalAlert
            tone="danger"
            title="Action failed"
            onDismiss={() => settings.setActionError("")}
            dismissLabel="Dismiss the billing action failure"
          >
            {settings.actionError}
          </SignalAlert>
        )}

        {/* SIGV2-1178: a failed plan load is a reported failure, not a "Free"
            plan. Until this alert existed the page answered that failure by
            claiming the customer was on Free and offering to "choose a paid
            plan", which is the confident wrong answer the ticket calls out. */}
        {settings.error && (
          <SignalAlert tone="danger" title="Billing details unavailable">
            {settings.error} The subscription details shown below may not reflect your actual plan.
            Please retry or contact support if this persists.
          </SignalAlert>
        )}

        {/* Section Navigation — MVP `.tabs` (underline, plain text) */}
        <SignalTabs tabs={sections} activeId={activeSection} onChange={setActiveSection} />

        {/* Overview Section */}
        {activeSection === "overview" && (
          <SignalTabPanel id="overview" activeId={activeSection}>
            <div className="space-y-4">
              {/* Active Subscription Card */}
              <GlassCard className="relative overflow-hidden rounded-[22px] border-0 bg-white p-5 sm:p-6">
                <div className="absolute right-8 top-8 opacity-5">
                  <Zap className="h-24 w-24" />
                </div>

                <div className="flex flex-col gap-6 md:flex-row md:items-start md:justify-between">
                  <div className="flex items-start gap-4">
                    <div className="rounded-lg bg-primary/10 p-3">
                      <Zap className="h-6 w-6 text-primary" />
                    </div>
                    <div className="space-y-4">
                      <div>
                        <p className="text-xs text-(--muted-foreground)">Active Subscription</p>
                        <h2 className="mt-1 text-[22px] font-extrabold text-(--foreground)">
                          {currentPlanLabel}
                        </h2>
                        {/* "pending" is an internal artefact: the subscription
                            row exists because a checkout started, not because
                            one completed. Showing it under a plan named "Free"
                            reads as a broken state ("Free · Status: pending"),
                            so only real subscription lifecycle states render. */}
                        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                          {settings.billingOverview?.status &&
                            settings.billingOverview.status !== "pending" && (
                              <span className="inline-flex items-center gap-2 text-(--primary)">
                                <span className="h-1.5 w-1.5 rounded-full bg-(--primary)" />
                                Status: {settings.billingOverview.status.replace(/_/g, " ")}
                              </span>
                            )}
                          {activeBillingInterval && (
                            <span className="text-(--muted-foreground)">
                              {formatBillingInterval(activeBillingInterval)}
                            </span>
                          )}
                          {usage.data?.renewal_date && (
                            <span className="text-(--muted-foreground)">
                              Renews {formatDate(usage.data.renewal_date)}
                            </span>
                          )}
                        </div>
                      </div>

                      <p className="max-w-xl text-sm text-(--muted-foreground)">
                        {currentPlan?.highlight ??
                          "Start on a paid plan to unlock the Stripe billing portal and premium automation add-ons."}
                      </p>

                      {currentPlan && (
                        <div className="flex flex-wrap gap-2">
                          <span className="rounded-full bg-(--surface-elevated) px-3 py-1 text-xs">
                            {formatPlanLimit(currentPlan.capabilities.max_audits, "audits")}
                          </span>
                          <span className="rounded-full bg-(--surface-elevated) px-3 py-1 text-xs">
                            {formatPlanLimit(currentPlan.capabilities.max_sites, "sites")}
                          </span>
                          {/* Two chips, not three: the approved mockup (Signal
                              Billing.html line 110) draws a third chip repeating
                              the audit allowance. That is a defect in the mockup
                              carried into the build; the audit and site limits
                              are each stated once. Do not restore the third chip
                              from the design without correcting the mockup first. */}
                        </div>
                      )}

                      {/* High Confidence Mode Info */}
                      <div
                        className={cx(
                          "rounded-[12px] px-4 py-3.5",
                          currentPlanSupportsHighConfidence
                            ? "bg-[color-mix(in_srgb,var(--primary)_5%,transparent)] border-0"
                            : "bg-(--surface-subtle) border-0"
                        )}
                      >
                        <div className="flex items-start gap-3">
                          <Shield
                            className={cx(
                              "h-5 w-5 mt-0.5",
                              currentPlanSupportsHighConfidence
                                ? "text-(--primary)"
                                : "text-(--muted-foreground)"
                            )}
                          />
                          <div>
                            <p className="text-sm font-medium text-(--foreground)">
                              High Confidence Mode
                            </p>
                            <p className="mt-1 text-xs text-(--muted-foreground)">
                              {currentPlanSupportsHighConfidence
                                ? `Your ${currentPlanDisplayName} plan includes the stricter multi-agent High Confidence audit path.`
                                : `Upgrade to ${highConfidenceUnlockLabel} to unlock the stricter High Confidence audit path.`}
                            </p>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Action Buttons */}
                  <div className="flex flex-col gap-2">
                    {isPortalAvailable ? (
                      <Button
                        onClick={settings.handlePortal}
                        loading={settings.actionLoading === "portal"}
                        disabled={pendingPlanChange !== null}
                        variant="inverse"
                        size="sm"
                      >
                        Manage Billing
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Button>
                    ) : (
                      <div className="rounded-[14px] border-0 bg-[#EEF1F6] px-4 py-2 text-xs text-(--muted-foreground) text-center">
                        {settings.error
                          ? "Billing portal unavailable"
                          : "Choose a paid plan to unlock billing portal"}
                      </div>
                    )}
                    <Link
                      href="/dashboard/billing/history"
                      className={buttonClasses({ variant: "ghost", size: "sm" })}
                    >
                      <History className="h-3.5 w-3.5" />
                      Billing History
                    </Link>
                  </div>
                </div>
              </GlassCard>

              {/* Cycle snapshot so Overview is not only plan marketing + enterprise CTA */}
              <GlassCard className="rounded-[22px] border-0 bg-white p-5 sm:p-6">
                <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <p className="text-xs text-(--muted-foreground)">This billing cycle</p>
                    <h3 className="mt-1 text-lg font-semibold text-(--foreground)">Scan usage</h3>
                    <p className="mt-1 max-w-lg text-sm text-(--muted-foreground)">
                      How much of your {currentPlanLabel} allowance you have used this period.
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => setActiveSection("usage")}
                  >
                    View usage details
                    <TrendingUp className="h-3.5 w-3.5" />
                  </Button>
                </div>

                {usage.isLoading || !usage.data ? (
                  <div className="mt-5 flex h-16 items-center justify-center text-xs text-(--muted-foreground)">
                    {usage.error ?? "Loading scan usage..."}
                  </div>
                ) : (
                  <div className="mt-5 grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                        Used
                      </p>
                      <p className="text-xl font-semibold text-(--foreground)">
                        {formatCompactNumber(usage.data.scans_used)}
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                        Remaining
                      </p>
                      <p className="text-xl font-semibold text-(--foreground)">
                        {usage.data.scans_remaining === null
                          ? "Unlimited"
                          : formatCompactNumber(usage.data.scans_remaining)}
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                        Allowance
                      </p>
                      <p className="text-xl font-semibold text-(--foreground)">
                        {usage.data.scan_allowance === null
                          ? "Unlimited"
                          : formatCompactNumber(usage.data.scan_allowance)}
                      </p>
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wider text-(--muted-foreground)">
                        7-day burn
                      </p>
                      <p className="text-xl font-semibold text-(--foreground)">
                        {usage.data.burn_rate_7d.toFixed(1)}
                        <span className="ml-1 text-xs font-normal text-(--muted-foreground)">
                          /day
                        </span>
                      </p>
                    </div>
                  </div>
                )}
              </GlassCard>
            </div>
          </SignalTabPanel>
        )}

        {/* Usage Section */}
        {activeSection === "usage" && (
          <SignalTabPanel id="usage" activeId={activeSection}>
            <ScanAllowanceCard data={usage.data} isLoading={usage.isLoading} />

            <ScanUsageChart
              dailyUsage={usage.data?.daily_usage ?? []}
              scanAllowance={usage.data?.scan_allowance ?? null}
              isLoading={usage.isLoading}
              error={usage.error}
            />

            {usage.data?.recommendation && (
              <PlanRecommendationBanner recommendation={usage.data.recommendation} />
            )}
          </SignalTabPanel>
        )}

        {/* Plans Section */}
        {activeSection === "plans" && (
          <SignalTabPanel id="plans" activeId={activeSection}>
            <div className="flex flex-col items-stretch gap-4 sm:flex-row sm:items-center sm:justify-between">
              <h2 className="text-lg font-semibold text-(--foreground)">Available Plans</h2>
              {/* SIGV2-1171 deliberately left `settings.error` - the failure
                  to LOAD the plan list - exactly as it was, and it is the one
                  thing on this page this ticket does not fix.

                  It deserves a page-level alert: when the plan load fails,
                  this page answers by claiming the customer is on Free and
                  offering "Choose a paid plan to unlock billing portal", which
                  is a confident wrong answer rather than a reported failure.
                  But it cannot be fixed here. The design-comparison harness
                  photographs this page with its plan load ALREADY FAILING -
                  the stub serves no /api/v1/billing/plans - so the recorded
                  budgets for `billing` (24), `billing-tab-usage` (30.3),
                  `billing-tab-plans` (20.9) and `billing-tab-comparison`
                  (65.3) were all measured against a silently failed page.
                  Making that failure visible measures +21.85pp, +8.10pp,
                  +13.89pp and +3.72pp over those budgets respectively, and
                  even the smallest in-place treatment puts
                  `billing-tab-plans` on 20.84 against a 20.9 ceiling.
                  Fixing it needs the stub to serve a plan catalogue first, so
                  the gate compares the state the approved design draws. That
                  is a harness change with its own re-measurement, raised as
                  its own ticket, not a threshold edit smuggled in here.

                  The `actionError` alert above the tab panels IS the fix this
                  ticket owes: that is the refused checkout and refused portal
                  path, the one that read as a dead button. */}
              <div className="flex min-w-0 flex-col items-stretch gap-3 sm:flex-row sm:items-center sm:gap-4">
                {settings.error && <p className="text-xs text-rose-400">{settings.error}</p>}
                <BillingIntervalToggle
                  value={billingInterval}
                  onChange={handleBillingIntervalChange}
                />
              </div>
            </div>

            <div className="grid items-stretch gap-4 md:grid-cols-2 xl:grid-cols-4">
              {visiblePlans.map((plan) => {
                const isCurrent = settings.billingOverview?.current_plan === plan.id;
                const canCheckout = plan.checkout_available && Boolean(plan.price_id);

                const isHighlighted = highlightPlanId === plan.id;
                return (
                  <div
                    key={plan.id}
                    id={`plan-${plan.id}`}
                    className={cx(
                      "h-full min-w-0",
                      isHighlighted &&
                        "rounded-[18px] ring-2 ring-(--purple) ring-offset-2 ring-offset-(--paper) transition-shadow"
                    )}
                  >
                    <PlanCard
                      plan={plan}
                      isCurrent={isCurrent}
                      canCheckout={canCheckout}
                      hasActiveSubscription={hasActiveSubscription}
                      selfServicePlanChangesAllowed={selfServicePlanChangesAllowed}
                      billingInterval={billingInterval}
                      activeBillingInterval={activeBillingInterval ?? "month"}
                      planActionsDisabled={pendingPlanChange !== null}
                      onCheckout={() => {
                        if (!pendingPlanChange) {
                          void settings.handleCheckout(plan.id, billingInterval);
                        }
                      }}
                      onPlanChange={() => {
                        if (!pendingPlanChange) {
                          setPlanChangeTarget(plan.id);
                        }
                      }}
                      isLoading={settings.actionLoading === plan.id}
                    />
                  </div>
                );
              })}
            </div>
          </SignalTabPanel>
        )}

        {/* Comparison Section */}
        {activeSection === "comparison" && (
          <SignalTabPanel id="comparison" activeId={activeSection}>
            <PlanComparisonMatrix
              plans={visiblePlans}
              currentPlanId={settings.billingOverview?.current_plan ?? null}
            />
          </SignalTabPanel>
        )}

        {/* Overview because that is where signal-MVP puts the enterprise card, and
          Plans because a custom, negotiated arrangement is not one of the four
          self-service tiers, so Contact Sales is the only route to it. It used to
          render outside every panel, which repeated the same sales card on Usage
          and Comparison as well. Commitments returns with SIGV2-1166. */}
        {(activeSection === "overview" || activeSection === "plans") && (
          <div className="w-full pt-2">
            <BillingSalesContactCard />
          </div>
        )}

        <PlanChangeModal
          open={planChangeTarget !== null}
          onClose={() => setPlanChangeTarget(null)}
          targetPlanId={planChangeTarget}
          targetBillingInterval={billingInterval}
          getAuthHeaders={settings.getAuthHeaders}
          onSuccess={() => void settings.loadBillingOverview()}
        />
      </div>
    </WorkspacePageFrame>
  );
}
