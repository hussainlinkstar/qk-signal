"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import ReportSection from "./ReportSection";
import TargetFixes from "./TargetFixes";
import type { ConsolidatedFix } from "@/lib/reportAdapters";

export default function AioReportSection({
  fixes,
  children,
}: {
  fixes: ConsolidatedFix[];
  children: React.ReactNode;
}) {
  const { t } = useTranslation();

  return (
    <ReportSection
      eyebrow={t("signalAuditReport.aio.eyebrow")}
      title={t("signalAuditReport.aio.title")}
      anchorId="report-aio"
    >
      <TargetFixes fixes={fixes} />
      {/* SIGV2-1317: no panel around the set.
          Each disclosure is its own card now, on the approved Scan history
          anatomy, so the sections are siblings with one gap between them
          rather than rows inside a card that itself sat inside the section.
          That outer wrapper was the first of the three card levels the page
          was reported for. */}
      <div className="space-y-4">{children}</div>
    </ReportSection>
  );
}
