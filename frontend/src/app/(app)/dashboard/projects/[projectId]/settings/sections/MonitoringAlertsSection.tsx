"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import AlertSettings from "@/components/settings/AlertSettings";

import SettingsSection from "./SettingsSection";

/** Section 12. Alert rules, kept as one short block at the end of the list. */
export default function MonitoringAlertsSection({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  return (
    <SettingsSection
      variant="wsec"
      id="alerts"
      title={t("signalProjectSettings.monitoringAlerts.heading")}
      description={t("signalProjectSettings.monitoringAlerts.description")}
    >
      <AlertSettings projectId={projectId} />
    </SettingsSection>
  );
}
