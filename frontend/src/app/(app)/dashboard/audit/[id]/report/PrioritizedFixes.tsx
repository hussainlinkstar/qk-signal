"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import ReportSection from "./ReportSection";
import FixRow from "./FixRow";
import type { ConsolidatedFix } from "@/lib/reportAdapters";

export default function PrioritizedFixes({ fixes }: { fixes: ConsolidatedFix[] }) {
  const { t } = useTranslation();
  const topFixes = fixes.slice(0, 5);

  return (
    <ReportSection
      anchorId="report-sec-fixes"
      eyebrow={t("signalAuditReport.fixes.eyebrow")}
      title={t("signalAuditReport.fixes.title")}
    >
      {topFixes.length > 0 ? (
        <div className="rounded-[22px] border-0 bg-white">
          {topFixes.map((fix, index) => (
            <FixRow key={`${fix.title}-${index}`} fix={fix} rank={index + 1} />
          ))}
        </div>
      ) : (
        <div className="rounded-[22px] border-0 bg-white">
          <div className="flex items-center gap-4 border-t border-t-(--line-2) px-[22px] py-[18px] first:border-t-0">
            <div className="min-w-0 flex-1">
              <p className="m-0 mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
                {t("signalAuditReport.fixes.empty")}
              </p>
            </div>
          </div>
        </div>
      )}
    </ReportSection>
  );
}
