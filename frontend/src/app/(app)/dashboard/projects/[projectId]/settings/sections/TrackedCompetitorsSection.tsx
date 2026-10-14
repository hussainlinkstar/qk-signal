"use client";

import React from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import FeatureLockOverlay from "@/components/dashboard/FeatureLockOverlay";
import CompetitorRosterChips from "@/components/settings/CompetitorRosterChips";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";

import SettingsSection from "./SettingsSection";

/**
 * Section 2. The Product tab card is the roster only: chips of the tracked
 * competitors plus the add chip that lands on the Brand tab's Competitive
 * Intelligence card, which owns the benchmark automation and digest cadence
 * the design deliberately splits into its own card.
 *
 * On a plan without competitor analysis the lock overlay covers the whole
 * card, heading included: the heading is the card's own title, not a
 * page-section rule, so the detail-page pattern (heading outside `.lockwrap`)
 * does not apply here.
 */
export default function TrackedCompetitorsSection({
  projectId,
  onAddCompetitor,
  children,
}: {
  projectId: string;
  onAddCompetitor?: () => void;
  /**
   * SIGV2-1039: the approved Product Settings tab shares this card with the
   * "Tracked prompts" heading, so the page passes that block in as a child
   * rather than giving it a card of its own.
   */
  children?: React.ReactNode;
}) {
  const { t } = useTranslation();
  const { user } = useAuth();
  const planLocked = !resolvePlanCapabilities(user?.subscription_plan).has_competitor_analysis;

  return (
    <SettingsSection
      id="competitors"
      title={t("signalProjectSettings.competitors.heading")}
      description={t("signalProjectSettings.competitors.description")}
      className={planLocked ? "relative overflow-hidden" : undefined}
    >
      <CompetitorRosterChips projectId={projectId} onAddCompetitor={onAddCompetitor} />
      {children}
      {planLocked ? (
        <FeatureLockOverlay
          title="Competitive Intelligence requires Specialist"
          description="Upgrade this workspace to configure live benchmark targets, recurring competitor assessments, and AI-backed competitive gap summaries."
          ctaLabel="Upgrade workspace"
          className="rounded-(--r)"
        />
      ) : null}
    </SettingsSection>
  );
}
