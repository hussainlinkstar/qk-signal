"use client";

import Link from "next/link";
import React from "react";
import { useTranslation } from "react-i18next";
import { Shield } from "lucide-react";

import AuditSection from "@/components/results/AuditSection";
import SignalAlert, { SIGNAL_ALERT_ACTION } from "@/components/signal/SignalAlert";
import { cx } from "@/components/ui/utils";
import { formatTierDurationRange, type TierDurationsMap } from "@/hooks/useTierDurations";

type AuditDepthSectionProps = {
  auditForm: any;
  auditRunner: any;
  highConfidenceAccess: {
    isLocked: boolean;
    isLoading: boolean;
    currentPlanLabel: string;
    eligiblePlanLabels: string[];
  };
  highConfidenceEligibleLabel: string;
  /**
   * Measured per-tier durations, read once by the page (SIGV2-1177). A tier
   * absent from the map has no publishable measurement and its cell stays
   * empty; null means the read has not landed and no tier states a figure.
   */
  tierDurations: TierDurationsMap | null;
};

/**
 * The three depths of the approved How thorough section, in order.
 *
 * The Time column states the measured p25..p75 range served by
 * `/api/v1/audit/tier-durations`, the only place the product gets a tier's
 * runtime (SIGV2-1177), so this table and the Launch sentence cannot
 * disagree. A tier with no publishable measurement gets an empty cell: no
 * invented number ever appears here.
 */
const TIERS = [
  {
    value: "fast",
    labelKey: "signalStartCheck.depth.fast",
    whatKey: "signalStartCheck.depth.fastWhat",
  },
  {
    value: "smart",
    labelKey: "signalStartCheck.depth.smart",
    whatKey: "signalStartCheck.depth.smartWhat",
  },
  {
    value: "deep_judgment",
    labelKey: "signalStartCheck.depth.deep",
    whatKey: "signalStartCheck.depth.deepWhat",
  },
] as const;

export default function AuditDepthSection({
  auditForm,
  auditRunner,
  highConfidenceAccess,
  highConfidenceEligibleLabel,
  tierDurations,
}: AuditDepthSectionProps) {
  const { t } = useTranslation();
  const { form } = auditForm;

  return (
    <AuditSection
      id="audit-step-depth"
      heading={t("signalStartCheck.depth.heading")}
      description={t("signalStartCheck.depth.description")}
    >
      {/* `.seg`: one segmented control, the choice itself. The table below it
          is the trade-off, stated rather than only named. */}
      <div
        role="group"
        aria-label={t("signalStartCheck.depth.heading")}
        className="mb-3 inline-flex gap-[2px] rounded-[9px] border-0 bg-[#EEF1F6] p-[3px]"
      >
        {TIERS.map((tier) => {
          const active = form.tier === tier.value;
          const isLocked = tier.value === "deep_judgment" && highConfidenceAccess.isLocked;
          return (
            <button
              key={tier.value}
              type="button"
              aria-pressed={active}
              aria-label={
                isLocked
                  ? t("signalAudit.target.tierAriaLocked", { tier: t(tier.labelKey) })
                  : t("signalAudit.target.tierAria", { tier: t(tier.labelKey) })
              }
              disabled={auditRunner.isLoading || auditRunner.isPolling || isLocked}
              onClick={() => {
                if (isLocked) return;
                auditForm.setFormValue("tier", tier.value);
              }}
              className={cx(
                "rounded-[6px] border-none px-3 py-1.5 font-(family-name:--body-font) text-[12.5px] font-semibold transition-colors disabled:cursor-not-allowed max-md:min-h-11",
                active ? "bg-(--ink) text-white" : "bg-transparent text-(--t-2) hover:text-(--t-1)"
              )}
            >
              {t(tier.labelKey)}
              {isLocked && (
                <span className="ms-1.5 font-(family-name:--mono) text-[10px] uppercase tracking-[0.04em] text-(--warn)">
                  {t("signalAudit.target.locked")}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* `.wtable`: th mono 10px uppercase on a --line rule, td 13px on
          --line-2 rules, the time column mono. */}
      <table className="w-full border-collapse text-start">
        <thead>
          <tr>
            <th className="border-b border-(--line) px-4 py-[11px] text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalStartCheck.depth.columnTier")}
            </th>
            <th className="border-b border-(--line) px-4 py-[11px] text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalStartCheck.depth.columnWhat")}
            </th>
            <th className="border-b border-(--line) px-4 py-[11px] text-start font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalStartCheck.depth.columnTime")}
            </th>
          </tr>
        </thead>
        <tbody>
          {TIERS.map((tier) => {
            const active = form.tier === tier.value;
            return (
              <tr key={tier.value} className="border-b border-(--line-2) last:border-b-0">
                <td className="px-4 py-[13px] align-middle text-[13px]">
                  {active ? <b>{t(tier.labelKey)}</b> : t(tier.labelKey)}
                </td>
                <td className="px-4 py-[13px] align-middle text-[13px]">{t(tier.whatKey)}</td>
                <td className="px-4 py-[13px] align-middle font-(family-name:--mono) text-[13px]">
                  {tierDurations?.[tier.value]
                    ? formatTierDurationRange(tierDurations[tier.value])
                    : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>

      {highConfidenceAccess.isLoading ? (
        <p className="mt-3 text-xs text-(--t-3)">{t("signalAudit.target.planCheckLoading")}</p>
      ) : highConfidenceAccess.isLocked ? (
        /* SIGV2-1171: the plan lock is the same alert anatomy as every other
           blocked action. Its title used to be a 10.5px mono eyebrow in
           `--t-3` and its body 12px in `--t-3`, which is the quietest thing on
           the card and sat below the depth table rather than reading as the
           reason the depth cannot be chosen. */
        <SignalAlert
          tone="warning"
          className="mt-3"
          icon={<Shield strokeWidth={2} />}
          title={t("signalAudit.target.deepLockedTitle", {
            plan: highConfidenceAccess.currentPlanLabel,
          })}
          actions={
            <Link href="/dashboard/billing" className={SIGNAL_ALERT_ACTION}>
              {t("signalAudit.target.deepLockedCta")}
            </Link>
          }
        >
          {t("signalAudit.target.deepLockedBody", { plans: highConfidenceEligibleLabel })}
        </SignalAlert>
      ) : null}
    </AuditSection>
  );
}
