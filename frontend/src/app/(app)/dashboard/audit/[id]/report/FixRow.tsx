"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import type { ConsolidatedFix } from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";

// SIGV2-1211: impact is categorical by product rule. The row already states
// it as a category below, so the "+N PTS" badge that used to sit here was a
// second, competing impact statement, and the figure it printed was a
// predicted gain dressed as a measurement. `impactValue` is a measured score
// deduction, not a promise of what a fix recovers, so it is not printed.
//
// SIGV2-1193: the row also states which channel raised it, because the audit's
// findings and the action plan are one list now and the customer keeps the
// answer SIGV2-1175 gave them about where a fix came from.
export default function FixRow({ fix, rank }: { fix: ConsolidatedFix; rank?: number }) {
  const { t } = useTranslation();

  return (
    <div className="flex items-start gap-3 border-t border-t-(--line-2) px-[18px] py-3 first:border-t-0">
      {rank != null ? (
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-(--line-2) font-(family-name:--disp) text-[14px] font-bold text-(--t-1)">
          {rank}
        </div>
      ) : null}
      <div className="min-w-0 flex-1">
        <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          {fix.title}
        </h3>
        <p className="m-0 mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">{fix.description}</p>
        <div className="mt-[9px] flex flex-wrap items-center gap-2">
          {fix.category ? (
            <span className="rounded-[6px] bg-[rgba(147,51,234,0.1)] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--purple)">
              {fix.category}
            </span>
          ) : null}
          {fix.impact ? (
            <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
              {t("signalAuditReport.fixes.impact", { impact: fix.impact })}
            </span>
          ) : null}
          {fixSourceLabelKeys(fix.sources ?? []).map((key) => (
            <span
              key={key}
              className="rounded-[6px] border-0 bg-[#EEF1F6] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-3)"
            >
              {t(key)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
