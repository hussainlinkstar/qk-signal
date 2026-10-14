"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import AuditSection from "@/components/results/AuditSection";
import { resolveResetInDays } from "@/lib/auditScanRun";

type AuditAllowanceSectionProps = {
  planLabel: string;
  /** Scans consumed in the current rolling window, null when not known. */
  used: number | null;
  /** Scans left, null for an uncapped plan, undefined when not known. */
  remaining: number | null | undefined;
  resetAt: string | null;
};

/**
 * The approved Allowance section (mockup: Signal Audit.html).
 *
 * The plan's monthly limit is `used + remaining`: the estimate endpoint
 * reports both halves of the rolling 30-day window, not the cap itself
 * (backend/services/scan_allowance_service.py). Nothing is rendered as a
 * number unless both halves arrived, so the section never shows an invented
 * cap, and the whole point of the section is that it says this before the
 * launch rather than at the moment of refusal.
 */
export default function AuditAllowanceSection({
  planLabel,
  used,
  remaining,
  resetAt,
}: AuditAllowanceSectionProps) {
  const { t } = useTranslation();

  const isUnlimited = remaining === null;
  const limit = typeof used === "number" && typeof remaining === "number" ? used + remaining : null;
  const resetInDays = resolveResetInDays(resetAt);
  const usedPct =
    limit !== null && limit > 0 ? Math.min(100, Math.round(((used as number) / limit) * 100)) : 0;

  return (
    <AuditSection
      id="audit-step-allowance"
      heading={t("signalStartCheck.allowance.heading")}
      description={t("signalStartCheck.allowance.description")}
    >
      {isUnlimited ? (
        <p className="m-0 text-[12.5px] font-semibold text-(--t-1)">
          {t("signalStartCheck.allowance.planLineUnlimited", { plan: planLabel })}
        </p>
      ) : limit !== null ? (
        <>
          <div className="mb-2 flex justify-between text-[12.5px] font-semibold">
            <span>
              {t("signalStartCheck.allowance.planLine", {
                plan: planLabel,
                limit: limit.toLocaleString(),
              })}
            </span>
            <b className="font-(family-name:--disp) text-(--purple)">
              {t("signalStartCheck.allowance.remaining", {
                remaining: (remaining as number).toLocaleString(),
              })}
            </b>
          </div>
          {/* `.range-track` + `.fillr`: the fill is the share of the window
              already used, not a progress indicator for this run. */}
          <div className="relative h-1.5 rounded-full bg-(--line)">
            <div
              className="absolute inset-y-0 start-0 rounded-full bg-linear-to-r from-(--blue) to-(--purple)"
              style={{ width: `${usedPct}%` }}
            />
          </div>
          <div className="mt-2 flex justify-between font-(family-name:--mono) text-[10.5px] text-(--t-3)">
            <span>
              {t("signalStartCheck.allowance.used", {
                used: (used as number).toLocaleString(),
              })}
            </span>
            {resetInDays !== null && (
              <span>
                {resetInDays === 0
                  ? t("signalStartCheck.allowance.resetsToday")
                  : t("signalStartCheck.allowance.resetsInDays", { count: resetInDays })}
              </span>
            )}
          </div>
        </>
      ) : (
        <p className="m-0 text-xs leading-[1.5] text-(--t-3)">
          {t("signalStartCheck.allowance.unknown")}
        </p>
      )}

      <p className="mt-2.5 text-xs leading-[1.5] text-(--t-3)">
        {t("signalStartCheck.allowance.thisScan")}
      </p>
    </AuditSection>
  );
}
