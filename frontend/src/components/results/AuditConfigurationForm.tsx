"use client";

import React, { forwardRef, useImperativeHandle, useMemo, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useTranslation } from "react-i18next";

import AuditAllowanceSection from "@/components/results/AuditAllowanceSection";
import AuditContextSection from "@/components/results/AuditContextSection";
import AuditDepthSection from "@/components/results/AuditDepthSection";
import AuditEntitiesSection from "@/components/results/AuditEntitiesSection";
import AuditLaunchSection from "@/components/results/AuditLaunchSection";
import AuditPromptsSection from "@/components/results/AuditPromptsSection";
import AuditScanRunView, { type CompletedScanScores } from "@/components/results/AuditScanRunView";
import AuditStickyStartBar from "@/components/results/AuditStickyStartBar";
import AuditTargetSection from "@/components/results/AuditTargetSection";
import type { ScanPromptsState } from "@/hooks/useScanPrompts";
import type { TierDurationsMap } from "@/hooks/useTierDurations";
import type { ScanVisibilityStat } from "@/lib/auditScanRun";
import type { AuditHistoryItem } from "@/types/auditWorkspace";

type AuditConfigurationFormProps = {
  auditForm: any;
  auditRunner: any;
  isStartDisabled: boolean;
  highConfidenceAccess: {
    isLocked: boolean;
    isLoading: boolean;
    currentPlanLabel: string;
    eligiblePlanLabels: string[];
  };
  /** Most recent earlier scan for the same target, for the succeeded state. */
  previousScan?: AuditHistoryItem | null;
  /**
   * The project's measured AI visibility for the succeeded state's third stat.
   * Null when the scan has no project behind it or the summary is not read.
   */
  visibility?: ScanVisibilityStat | null;
  /**
   * Where the run view's "Back to dashboard" action goes. The approved design
   * sends it to the scan's own project dashboard (SIGV2-1164); the workspace
   * overview is the fallback when no project is known.
   */
  dashboardHref?: string;
  /**
   * The project's prompt list, read once by the page so the Launch gate and
   * the prompts section cannot disagree about whether a prompt exists
   * (SIGV2-1176).
   */
  prompts: ScanPromptsState;
  /**
   * Measured per-tier durations, read once by the page (SIGV2-1177) so the
   * depth table and the Launch sentence share one figure. Null when the read
   * has not landed; a tier absent from the map states no duration.
   */
  tierDurations: TierDurationsMap | null;
  /** Auth headers for the prompt creation dialog. */
  getAuthHeaders: () => Promise<Record<string, string>>;
};

/* ──────────────────── Error message cleaner ──────────────────── */
function cleanAuditError(raw: string | null | undefined): string {
  if (!raw) return "";
  if (raw.includes("RESOURCE_EXHAUSTED") || raw.includes("quota") || raw.includes("rate limit")) {
    return "The analysis service has hit its request limit for now. Please try again in a few minutes.";
  }
  if (raw.includes("API_KEY_INVALID") || raw.includes("PERMISSION_DENIED") || raw.includes("401")) {
    return "We could not sign in to the analysis service. Please contact support.";
  }
  if (raw.includes("timeout") || raw.includes("DEADLINE_EXCEEDED") || raw.includes("503")) {
    return "The analysis service is briefly unavailable. Please try again in a moment.";
  }
  if (raw.includes("{") || raw.includes("'message'")) {
    const msgMatch = raw.match(/'message':\s*'([^']{10,200})'/);
    if (msgMatch) return msgMatch[1].split(".")[0] + ".";
    return "Something went wrong during the analysis. Please try again.";
  }
  return raw;
}

/**
 * The approved start-scan page (mockup: Signal Audit.html) and the run view
 * that replaces it (mockup: Signal Audit Run.html).
 *
 * All seven sections are visible at once, in the approved `.setgrid` two-column
 * order: Target, Context, Entity configuration on the left; Allowance, How
 * thorough, Model selection, Launch on the right. Each carries its own
 * explanatory sentence. Nothing is folded behind a disclosure, which is what
 * had collapsed four of the seven sections out of sight.
 */
const AuditConfigurationForm = forwardRef(function AuditConfigurationForm(
  {
    auditForm,
    auditRunner,
    isStartDisabled,
    highConfidenceAccess,
    previousScan = null,
    visibility = null,
    dashboardHref,
    prompts,
    tierDurations,
    getAuthHeaders,
  }: AuditConfigurationFormProps,
  ref
) {
  const { t } = useTranslation();
  const shouldReduceMotion = useReducedMotion();
  const [showScanLine, setShowScanLine] = useState(false);

  const stickyStartLabel = auditForm.isPreflightChecking
    ? t("signalStartCheck.launch.checkingAddress")
    : auditRunner.isLoading
      ? t("signalStartCheck.launch.starting")
      : auditRunner.isPolling
        ? t("signalStartCheck.launch.running")
        : t("signalStartCheck.launch.start");

  const { form } = auditForm;
  const highConfidenceEligibleLabel = useMemo(() => {
    const labels = highConfidenceAccess.eligiblePlanLabels.filter(Boolean);
    if (labels.length <= 1) return labels[0] ?? "eligible enterprise plans";
    if (labels.length === 2) return `${labels[0]} or ${labels[1]}`;
    return `${labels.slice(0, -1).join(", ")}, or ${labels[labels.length - 1]}`;
  }, [highConfidenceAccess.eligiblePlanLabels]);
  const resolvedTargetUrl = (form.targetUrl?.trim() || form.url?.trim() || "").trim();

  const completedScores: CompletedScanScores | null = auditRunner.completedAuditMeta
    ? {
        auditId: auditRunner.completedAuditMeta.auditId,
        aioScore: auditRunner.completedAuditMeta.aioScore ?? null,
        seoScore: auditRunner.completedAuditMeta.seoScore ?? null,
      }
    : null;

  const scanLineTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  React.useEffect(
    () => () => {
      if (scanLineTimer.current) clearTimeout(scanLineTimer.current);
    },
    []
  );

  useImperativeHandle(ref, () => ({
    triggerAiScan: () => {
      if (shouldReduceMotion) return;
      setShowScanLine(true);
      if (scanLineTimer.current) clearTimeout(scanLineTimer.current);
      scanLineTimer.current = setTimeout(() => setShowScanLine(false), 500);
    },
  }));

  if (auditRunner.runPhase !== "idle" && auditRunner.runSnapshot) {
    return (
      <AuditScanRunView
        snapshot={auditRunner.runSnapshot}
        debateProgress={auditRunner.liveDebateProgress ?? null}
        completed={completedScores}
        previousScan={previousScan}
        visibility={visibility}
        dashboardHref={dashboardHref}
        scansRemaining={auditRunner.scansRemaining}
        onRetry={() => auditRunner.handleSubmit()}
        onChangeOptions={auditRunner.dismissRun}
      />
    );
  }

  return (
    <form onSubmit={auditRunner.handleSubmit} className="relative pb-24">
      <AnimatePresence>
        {showScanLine && (
          <motion.div
            key="ai-scan"
            className="pointer-events-none absolute inset-x-0 z-50 h-1 bg-(--ink)/20 blur-xs"
            initial={{ top: "-10%" }}
            animate={{ top: "110%" }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.8, ease: "linear" }}
          />
        )}
      </AnimatePresence>

      {/* `.setgrid`: 1fr 1fr with a 16px gap on the approved viewport. */}
      <div className="grid gap-4 lg:grid-cols-2 lg:items-start">
        <div className="space-y-4">
          <AuditTargetSection
            auditForm={auditForm}
            isStartDisabled={isStartDisabled}
            resolvedTargetUrl={resolvedTargetUrl}
            cleanAuditError={cleanAuditError}
          />
          <AuditContextSection auditForm={auditForm} auditRunner={auditRunner} />
          {/* SIGV2-1176: Jake's design puts prompts here, between Context and
              Entity configuration. The approved mockup (Signal Audit.html)
              predates the decision and carries no prompts section, so this is
              a deliberate addition to that screen, not a drift from it. */}
          <AuditPromptsSection prompts={prompts} getAuthHeaders={getAuthHeaders} />
          <AuditEntitiesSection
            auditForm={auditForm}
            isStartDisabled={isStartDisabled}
            entitySummary={auditForm.entitySummary}
          />
        </div>

        <div className="space-y-4">
          <AuditDepthSection
            auditForm={auditForm}
            auditRunner={auditRunner}
            highConfidenceAccess={highConfidenceAccess}
            highConfidenceEligibleLabel={highConfidenceEligibleLabel}
            tierDurations={tierDurations}
          />
          {/* Allowance stays visible in the column for detail; sticky bar
              carries the live remaining count + Start (UI/UX Fixes). Models
              card removed — nothing to choose. */}
          <AuditAllowanceSection
            planLabel={highConfidenceAccess.currentPlanLabel}
            used={auditRunner.scansUsed}
            remaining={auditRunner.scansRemaining}
            resetAt={auditRunner.scansResetAt}
          />
          <AuditLaunchSection
            auditForm={auditForm}
            auditRunner={auditRunner}
            isStartDisabled={isStartDisabled}
            tierDurations={tierDurations}
          />
        </div>
      </div>

      <AuditStickyStartBar
        planLabel={highConfidenceAccess.currentPlanLabel}
        remaining={auditRunner.scansRemaining}
        isStartDisabled={isStartDisabled}
        startLabel={stickyStartLabel}
        isBusy={Boolean(
          auditRunner.isLoading || auditForm.isPreflightChecking || auditRunner.isPolling
        )}
      />
    </form>
  );
});

AuditConfigurationForm.displayName = "AuditConfigurationForm";

export default AuditConfigurationForm;
