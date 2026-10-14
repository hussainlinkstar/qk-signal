"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import ScoreTargetsCard from "@/components/settings/ScoreTargetsCard";

import SettingsSection from "./SettingsSection";

/** Section 1. The card owns its state and saves through the project PATCH. */
export default function ScoreTargetsSection({ projectId }: { projectId: string | number }) {
  const { t } = useTranslation();
  return (
    <SettingsSection
      id="score-targets"
      title={t("signalProjectSettings.scoreTargets.heading")}
      description={t("signalProjectSettings.scoreTargets.description")}
    >
      <ScoreTargetsCard projectId={projectId} />
    </SettingsSection>
  );
}
