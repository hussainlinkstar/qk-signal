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
 * Three selectable depth cards (UI/UX Fixes) — each shows what is included
 * and typical time, replacing the old segment control + duplicate table.
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
      <div
        role="group"
        aria-label={t("signalStartCheck.depth.heading")}
        className="grid gap-3 sm:grid-cols-3"
      >
        {TIERS.map((tier) => {
          const active = form.tier === tier.value;
          const isLocked = tier.value === "deep_judgment" && highConfidenceAccess.isLocked;
          const duration = tierDurations?.[tier.value]
            ? formatTierDurationRange(tierDurations[tier.value])
            : null;
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
                "flex h-full flex-col gap-2 rounded-[16px] border px-3.5 py-3.5 text-left transition-colors duration-150 disabled:cursor-not-allowed max-md:min-h-11",
                active
                  ? "border-(--ink) bg-(--ink) text-white"
                  : "border-[#E8ECF3] bg-[#FBFBFC] text-(--t-1) hover:border-[#D7DAE0] hover:bg-white",
                isLocked && "opacity-60"
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13.5px] font-bold">{t(tier.labelKey)}</span>
                {isLocked ? (
                  <span
                    className={cx(
                      "text-[10px] font-semibold uppercase tracking-[0.04em]",
                      active ? "text-white/70" : "text-(--warn)"
                    )}
                  >
                    {t("signalAudit.target.locked")}
                  </span>
                ) : null}
              </div>
              <p
                className={cx(
                  "m-0 flex-1 text-[12px] leading-[1.45]",
                  active ? "text-white/75" : "text-(--t-2)"
                )}
              >
                {t(tier.whatKey)}
              </p>
              {duration ? (
                <p
                  className={cx(
                    "m-0 text-[12px] font-semibold tabular-nums",
                    active ? "text-white" : "text-(--t-1)"
                  )}
                >
                  {duration}
                </p>
              ) : (
                <p className={cx("m-0 text-[12px]", active ? "text-white/40" : "text-(--t-3)")}>
                  —
                </p>
              )}
            </button>
          );
        })}
      </div>

      {highConfidenceAccess.isLoading ? (
        <p className="mt-3 text-xs text-(--t-3)">{t("signalAudit.target.planCheckLoading")}</p>
      ) : highConfidenceAccess.isLocked ? (
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
