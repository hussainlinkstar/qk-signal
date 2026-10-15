"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import ReportSection from "./ReportSection";

export default function ActionSection({ children }: { children: React.ReactNode }) {
  const { t } = useTranslation();

  return (
    <ReportSection
      eyebrow={t("signalAuditReport.action.eyebrow")}
      title={t("signalAuditReport.action.title")}
    >
      <div className="rounded-[22px] border-0 bg-white">{children}</div>
    </ReportSection>
  );
}
