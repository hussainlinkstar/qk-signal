"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, useRouter, usePathname } from "next/navigation";
import {
  Archive,
  FileJson,
  FileText,
  Lock,
  Loader2,
  Sparkles,
  Activity,
  Globe,
  Layers,
  Search,
  Zap,
} from "lucide-react";
import { motion } from "motion/react";
import { cx } from "@/components/ui/utils";
import GeoIcon from "@/components/ui/GeoIcon";
import AuditConfigurationForm from "./AuditConfigurationForm";
import Button from "@/components/ui/Button";
import { findPreviousScan } from "@/lib/auditScanRun";
import { ScheduleAutomation } from "./ScheduleAutomation";
import { rankEntitySuggestionsFromHistory } from "@/lib/entitySuggestionRanking";
import { getAuditLockedSection, type CanonicalAuditReport } from "@/lib/reportAdapters";
import { ClientSafeDate } from "@/lib/dateFormat";
import type { AuditHistoryItem, TabId } from "@/types/auditWorkspace";
import { tabs } from "@/types/auditWorkspace";

import { useAuditForm } from "@/hooks/useAuditForm";
import { useAuditRunner } from "@/hooks/useAuditRunner";
import { useWorkspaceHistory } from "@/hooks/useWorkspaceHistory";
import { useAuditComparison } from "@/hooks/useAuditComparison";
import { useAuditReportData } from "@/hooks/useAuditReportData";
import { useScanPrompts } from "@/hooks/useScanPrompts";
import { useTierDurations } from "@/hooks/useTierDurations";
import { useTabHotkeys } from "@/hooks/useTabHotkeys";

import OverviewTab from "./tabs/OverviewTab";
import SeoTab from "./tabs/SeoTab";
import AeoTab from "./tabs/AeoTab";
import GeoTab from "./tabs/GeoTab";
import EntitiesTab from "./tabs/EntitiesTab";
import ExportTab from "./tabs/ExportTab";
import TechnicalTab from "./tabs/TechnicalTab";
import CompetitorsTab from "./tabs/CompetitorsTab";
import HallucinationsTab from "./tabs/HallucinationsTab";
import IntegrityStatusBanner from "./IntegrityStatusBanner";
import TabErrorBoundary from "@/components/ui/TabErrorBoundary";
import CommandPalette from "@/components/ui/CommandPalette";
import FeatureLockOverlay from "@/components/dashboard/FeatureLockOverlay";
import GatedSection from "@/components/results/GatedSection";
import TierPreviewControl, { TIER_PREVIEW_ENABLED } from "@/components/results/TierPreviewControl";
import { useAuth } from "@/components/auth/custom-auth";
import { useBillingSettings } from "@/hooks/useBillingSettings";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

type AuditWorkspaceProps = {
  defaultTab?: TabId;
  title: string;
  description: string;
  isSignedIn: boolean;
  getAuthHeaders: () => Promise<Record<string, string>>;
  framed?: boolean;
  readOnly?: boolean;
  accessLevel?: "full" | "guest" | "sample";
  guestAuditToken?: string;
  initialReport?: CanonicalAuditReport | null;
  projectId?: number;
};

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

const HistoryItemSkeleton = () => (
  <div className="group w-full max-w-full rounded-xl border border-transparent p-3 text-left">
    <div className="flex items-start justify-between gap-2 overflow-hidden">
      <div className="h-4 w-3/4 animate-pulse rounded bg-(--line-2)"></div>
    </div>
    <div className="mt-2 flex items-center justify-between text-xs">
      <div className="h-3 w-20 animate-pulse rounded bg-(--line-2)"></div>
      <div className="h-4 w-10 animate-pulse rounded-full bg-(--line-2)"></div>
    </div>
  </div>
);

// ---------------------------------------------------------------------------
// AuditWorkspace Component
// ---------------------------------------------------------------------------

export default function AuditWorkspace({
  defaultTab = "overview",
  title: _title,
  description: _description,
  isSignedIn,
  getAuthHeaders,
  framed = true,
  readOnly = false,
  accessLevel = "full",
  guestAuditToken,
  initialReport = null,
  projectId,
}: AuditWorkspaceProps) {
  const { user } = useAuth();
  const billingSettings = useBillingSettings();
  const isGuest = accessLevel === "guest";
  const isEmbedded = accessLevel === "guest" || accessLevel === "sample";
  const showLockOverlay = readOnly && !isEmbedded;
  const formatHistoryScore = (value: number | null | undefined): string =>
    typeof value === "number" ? String(Math.round(value)) : "--";
  const formatPlanName = useCallback(
    (planId: string | null | undefined) =>
      String(planId ?? "")
        .split("_")
        .filter(Boolean)
        .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
        .join(" ") || "Unknown plan",
    []
  );

  // --- Tab state from URL search params ---
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const tabParam = searchParams.get("tab");
  const validTabIds = tabs.map((t) => t.id) as readonly string[];
  const activeTab: TabId =
    tabParam && validTabIds.includes(tabParam) ? (tabParam as TabId) : defaultTab;

  const setActiveTab = useCallback(
    (tab: TabId) => {
      const params = new URLSearchParams(searchParams.toString());
      params.set("tab", tab);
      router.replace(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [pathname, router, searchParams]
  );

  // --- Keyboard hotkeys (Alt+1-7) ---
  useTabHotkeys(setActiveTab);

  const scannerRef = React.useRef<{ triggerAiScan: () => void }>(null);
  const [isFormVisible, setIsFormVisible] = useState(true);

  const triggerAiScan = useCallback(() => {
    scannerRef.current?.triggerAiScan?.();
  }, []);

  // --- Custom hooks ---
  const auditForm = useAuditForm({
    getAuthHeaders,
    onAutoDetectStart: triggerAiScan,
  });

  const workspaceHistory = useWorkspaceHistory({
    getAuthHeaders,
    isSignedIn,
  });

  const effectiveProjectId = projectId || workspaceHistory.activeAuditMeta?.projectId;

  const { data: comparisonData } = useAuditComparison(workspaceHistory.selectedAuditId);

  const onAuditComplete = useCallback(
    (newEntry: AuditHistoryItem, normalizedReport: CanonicalAuditReport) => {
      workspaceHistory.setSelectedAuditId(newEntry.id);
      workspaceHistory.setActiveReport(normalizedReport, newEntry);
    },
    [workspaceHistory]
  );

  // Sync selected audit ID from URL params
  useEffect(() => {
    const idParam = searchParams.get("id");
    if (idParam) {
      const parsedId = parseInt(idParam, 10);
      if (!isNaN(parsedId) && parsedId !== workspaceHistory.selectedAuditId) {
        workspaceHistory.setSelectedAuditId(parsedId);
      }
    }
  }, [searchParams, workspaceHistory]);

  const auditRunner = useAuditRunner({
    getAuthHeaders,
    isSignedIn,
    projectId,
    form: auditForm.form,
    preScanResult: auditForm.preScanResult,
    validateForm: auditForm.validateForm,
    verifyUrlPreflight: auditForm.verifyUrlPreflight,
    fetchAuditRecord: workspaceHistory.fetchAuditRecord,
    invalidateHistory: workspaceHistory.invalidateHistory,
    upsertHistoryEntry: workspaceHistory.upsertHistoryEntry,
    onAuditComplete,
  });

  // Scan-limit errors surface through the runner's error text; no credit
  // wallet modal exists to show for them (SIGV2-1024).
  useEffect(() => {
    if (workspaceHistory.selectedAuditId || initialReport) {
      setIsFormVisible(false);
    }
  }, [workspaceHistory.selectedAuditId, initialReport]);

  // --- Derived state ---
  const activeReport = initialReport || workspaceHistory.activeReport;
  const activeAuditMeta = workspaceHistory.activeAuditMeta;

  const reportData = useAuditReportData({ activeReport, activeAuditMeta });
  const {
    activeTargetType,
    activeTargetUrl,
    activeTargetLabel,
    isBrandWithoutUrl,
    aeoTabData,
    geoTabData,
    performance,
    network,
    seoAudits,
    structuredDataDetected,
    seoStatus,
    lcpValue,
    clsValue,
    overallScore,
    seoScore,
    aeoScore,
    geoScore,
    scoreGroups,
    aeoScoreEntries,
    aeoEntityClarity,
    aeoRecommendations,
    aeoReadabilityFindings,
    aeoRewriteSuggestions,
    geoSummary,
    geoRecommendations,
    allRecommendations,
    normalizedEntities,
    scheduleAuditParams,
    handleCopySummary,
    handleExportJson,
    copyStatus,
  } = reportData;

  const { form } = auditForm;
  const billingOverview =
    billingSettings.billingOverview &&
    typeof billingSettings.billingOverview === "object" &&
    !Array.isArray(billingSettings.billingOverview)
      ? billingSettings.billingOverview
      : null;
  const billingPlans = useMemo(() => billingOverview?.plans ?? [], [billingOverview]);
  const currentBillingPlan = useMemo(
    () => billingPlans.find((plan) => plan.id === billingOverview?.current_plan) ?? null,
    [billingOverview?.current_plan, billingPlans]
  );
  const fallbackCapabilities = resolvePlanCapabilities(user?.subscription_plan);
  const hasHighConfidenceMode =
    currentBillingPlan?.capabilities.has_high_confidence_mode === true
      ? true
      : currentBillingPlan
        ? false
        : fallbackCapabilities.has_high_confidence_mode;
  // Comparison search type is gated to Specialist+ via the competitor-analysis
  // capability (signal plan Phase 4). Resolve from the active billing plan,
  // falling back to the user's subscription plan capabilities.
  const canSeeComparison =
    currentBillingPlan?.capabilities.has_competitor_analysis === true
      ? true
      : currentBillingPlan
        ? false
        : fallbackCapabilities.has_competitor_analysis;
  // Advisor AI recommendations are gated to Standard+ via the
  // advisor-recommendations capability (signal plan Phase 5). Resolve from the
  // active billing plan, falling back to the user's subscription plan
  // capabilities; unknown plans resolve to `false` (fail-safe LOCKED).
  const canSeeAdvisor =
    currentBillingPlan?.capabilities.has_advisor_recommendations === true
      ? true
      : currentBillingPlan
        ? false
        : fallbackCapabilities.has_advisor_recommendations;
  // Done-for-you execution is gated to Executive+ via the
  // done-for-you-execution capability (signal plan Phase 5). Same fail-safe
  // resolution as the other premium capabilities.
  const canSeeExecution =
    currentBillingPlan?.capabilities.has_done_for_you_execution === true
      ? true
      : currentBillingPlan
        ? false
        : fallbackCapabilities.has_done_for_you_execution;
  // Live engine tracking has no plan resolution here on purpose (SIGV2-1108):
  // the backend grants `has_live_engine_tracking` on every plan, so the engine
  // panel is always presented as included and there is nothing to gate.

  // --- Non-prod tier preview (Phase 5, Task 5.3) ----------------------------
  // QA-only visual override: when the `NEXT_PUBLIC_ENABLE_TIER_PREVIEW` flag is
  // on and the operator selects a tier, the three *displayed* capability
  // booleans below are derived from that tier's plan capabilities INSTEAD of
  // the real plan — purely so the blurred upsell states can be previewed.
  //
  // This never touches `currentBillingPlan`, `user.subscription_plan`, audit
  // requests, or any server call: it only swaps what the report panels render.
  // With the flag off (production) `TIER_PREVIEW_ENABLED` is `false`, so the
  // override is dead code and the real booleans are used unchanged.
  const [previewPlanKey, setPreviewPlanKey] = useState<string | null>(null);
  const previewCapabilities = useMemo(
    () => (TIER_PREVIEW_ENABLED && previewPlanKey ? resolvePlanCapabilities(previewPlanKey) : null),
    [previewPlanKey]
  );
  const displayCanSeeComparison = previewCapabilities
    ? previewCapabilities.has_competitor_analysis
    : canSeeComparison;
  const displayCanSeeAdvisor = previewCapabilities
    ? previewCapabilities.has_advisor_recommendations
    : canSeeAdvisor;
  const displayCanSeeExecution = previewCapabilities
    ? previewCapabilities.has_done_for_you_execution
    : canSeeExecution;

  const highConfidenceEligiblePlanLabels = useMemo(() => {
    const labels = billingPlans
      .filter((plan) => plan.capabilities.has_high_confidence_mode === true)
      .map((plan) => plan.name);
    return labels.length ? labels : ["Specialist", "Executive"];
  }, [billingPlans]);
  const currentPlanLabel =
    currentBillingPlan?.name ??
    formatPlanName(billingOverview?.current_plan ?? user?.subscription_plan ?? null);
  const highConfidencePlanLocked = form.tier === "deep_judgment" && !hasHighConfidenceMode;

  // SIGV2-1176: the mandatory prompt is a property of starting a scan, not of
  // one page, so this surface reads the same list through the same hook and
  // applies the same gate as the start-scan page.
  const scanPrompts = useScanPrompts({
    projectId: effectiveProjectId,
    isSignedIn,
    getAuthHeaders,
  });

  // SIGV2-1177: measured per-depth durations, read once so the depth table
  // and the Launch sentence share one figure; a tier without a publishable
  // measurement states nothing.
  const tierDurations = useTierDurations({
    isSignedIn,
    getAuthHeaders,
  });

  const isStartDisabled =
    auditRunner.isLoading ||
    auditRunner.isPolling ||
    auditForm.isPreflightChecking ||
    Boolean(auditForm.preflightError) ||
    highConfidencePlanLocked ||
    scanPrompts.blocksLaunch;

  // --- Entity sync from report → editableEntities ---
  useEffect(() => {
    auditForm.setEditableEntities(
      normalizedEntities.map((entity) => ({
        name: entity.name,
        type: entity.type,
        confidence: entity.relevance,
      }))
    );
  }, [normalizedEntities]); // eslint-disable-line react-hooks/exhaustive-deps

  const entityChipSuggestions = useMemo(
    () =>
      rankEntitySuggestionsFromHistory(
        workspaceHistory.historyForEntitySuggestions.map((entry) => ({
          created_at: entry.createdAt,
          full_report: entry.fullReport ?? null,
        })),
        auditForm.editableEntities,
        { limit: 10 }
      ),
    [auditForm.editableEntities, workspaceHistory.historyForEntitySuggestions]
  );

  // Comparison baseline for the run view's succeeded state, same rule as the
  // start-scan page: the most recent earlier scan of the same target.
  const previousScan = useMemo(
    () =>
      findPreviousScan(workspaceHistory.sortedHistory, {
        auditId:
          auditRunner.completedAuditMeta?.auditId ?? auditRunner.runSnapshot?.auditId ?? null,
        url: auditRunner.runSnapshot?.targetUrl ?? "",
        targetName: auditRunner.runSnapshot?.targetLabel ?? "",
      }),
    [
      workspaceHistory.sortedHistory,
      auditRunner.completedAuditMeta?.auditId,
      auditRunner.runSnapshot?.auditId,
      auditRunner.runSnapshot?.targetUrl,
      auditRunner.runSnapshot?.targetLabel,
    ]
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <>
      <div
        className={cx(
          "relative flex flex-col gap-8 transition-all duration-700",
          framed ? "p-0" : ""
        )}
      >
        {/* ---- Audit Form Card ---- */}
        {!readOnly && !isEmbedded && (
          <div className="px-4 md:px-0 space-y-4">
            {!isFormVisible && (
              <Button
                variant="ghost"
                onClick={() => setIsFormVisible(true)}
                className="w-full border-dashed border-(--line) hover:border-primary/50"
              >
                <Zap className="w-4 h-4 mr-2" /> Start New Audit
              </Button>
            )}
            {isFormVisible && (
              <AuditConfigurationForm
                ref={scannerRef}
                auditForm={auditForm}
                auditRunner={auditRunner}
                isStartDisabled={isStartDisabled}
                previousScan={previousScan}
                prompts={scanPrompts}
                tierDurations={tierDurations.durations}
                getAuthHeaders={getAuthHeaders}
                highConfidenceAccess={{
                  isLocked: !hasHighConfidenceMode,
                  isLoading: billingSettings.isLoading && !billingOverview,
                  currentPlanLabel,
                  eligiblePlanLabels: highConfidenceEligiblePlanLabels,
                }}
              />
            )}
          </div>
        )}

        {/* ---- Results Panel ---- */}
        <div className={cx("relative group/workspace", isEmbedded && "overflow-hidden")}>
          {/* Background Glow */}
          <div className="absolute -inset-2 bg-linear-to-br from-primary/10 via-transparent to-indigo-500/10 blur-3xl opacity-30 pointer-events-none group-hover/workspace:opacity-50 transition-opacity duration-1000" />

          <div
            className={cx(
              "relative mx-4 mb-4 flex flex-col rounded-4xl border border-(--line) bg-(--panel) shadow-2xl ring-1 ring-white/5 md:mx-0 md:mb-8 xl:flex-row",
              isEmbedded
                ? "min-h-[400px] md:min-h-[600px]"
                : "h-[calc(100vh-140px)] min-h-[400px] md:min-h-[600px] overflow-hidden"
            )}
          >
            {/* Sidebar: Audit Library (hidden in embedded mode) */}
            {!isEmbedded && (
              <div className="flex w-full shrink-0 max-h-[35vh] xl:max-h-none flex-col border-b border-(--line) bg-(--line-2) xl:w-85 xl:border-b-0 xl:border-r min-h-0  transition-all duration-500">
                <div className="sticky top-0 z-10 flex items-center justify-between border-b border-(--line) bg-(--line-2) px-6 py-5 ">
                  <div>
                    <h2 className="text-xs font-black uppercase tracking-[0.2em] text-(--t-3) flex items-center gap-2">
                      <Activity className="w-3.5 h-3.5 text-primary" />
                      Audit History
                    </h2>
                    <p className="text-[10px] text-(--t-3) font-bold uppercase tracking-[0.2em] mt-1 ">
                      Recent Audit Runs
                    </p>
                  </div>
                  <div className="px-2.5 py-0.5 rounded-lg border border-(--line) bg-(--line-2) text-[10px] font-black text-(--t-2)">
                    {workspaceHistory.sortedHistory.length}
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
                  {workspaceHistory.historyLoading && (
                    <div className="space-y-3">
                      {[1, 2, 3, 4].map((i) => (
                        <HistoryItemSkeleton key={i} />
                      ))}
                    </div>
                  )}

                  {!workspaceHistory.historyLoading &&
                    workspaceHistory.history.length === 0 &&
                    !workspaceHistory.historyError && (
                      <div className="flex flex-col items-center justify-center p-12 text-center">
                        <div className="w-14 h-14 rounded bg-(--line-2) border border-(--line) flex items-center justify-center mb-4 text-(--t-3)">
                          <FileJson className="w-6 h-6" />
                        </div>
                        <p className="text-[10px] font-black uppercase tracking-[0.3em] text-(--t-2) ">
                          History Empty
                        </p>
                        <p className="mt-2 text-[11px] text-(--t-3)  font-medium leading-relaxed">
                          Run an audit to see your results here.
                        </p>
                      </div>
                    )}

                  <div className="space-y-2.5">
                    {workspaceHistory.sortedHistory.map((entry) => {
                      const isSelected = workspaceHistory.selectedAuditId === entry.id;
                      const statusLabel = String(entry.status || "completed").toUpperCase();
                      const auditTypeLabel = String(entry.auditType || "FAST").toUpperCase();
                      const entryTargetType =
                        entry.auditTargetType === "brand" ? "brand" : "website";
                      const entryTargetLabel = (
                        entry.targetName ||
                        entry.targetUrl ||
                        entry.url ||
                        "Unnamed target"
                      ).trim();
                      return (
                        <button
                          key={entry.id}
                          type="button"
                          onClick={() => {
                            workspaceHistory.setSelectedAuditId(entry.id);
                            // Explicitly route to the full Audit Results page
                            router.push(`/dashboard/audit?id=${entry.id}`);
                          }}
                          className={cx(
                            "group w-full rounded border p-4 text-left transition-all duration-500 relative overflow-hidden",
                            isSelected
                              ? "border-primary/30 bg-primary/5 shadow-[0_0_25px_rgba(6,182,212,0.05)]"
                              : "border-(--line)  hover:bg-(--line-2) hover:border-(--line)"
                          )}
                        >
                          {isSelected && (
                            <motion.div
                              layoutId="activeHistoryGlow"
                              className="absolute inset-0 bg-linear-to-r from-primary/10 via-transparent to-primary/10 pointer-events-none"
                              initial={{ opacity: 0 }}
                              animate={{ opacity: 1 }}
                            />
                          )}

                          <div className="relative flex flex-col gap-3">
                            <div className="flex items-start justify-between gap-2">
                              <p
                                className={cx(
                                  "truncate text-xs font-bold tracking-wide transition-colors duration-300",
                                  isSelected
                                    ? "text-(--t-1)"
                                    : "text-(--t-2) group-hover:text-(--t-1)"
                                )}
                              >
                                {entryTargetLabel.replace(/^https?:\/\/(www\.)?/, "")}
                              </p>
                              <div className="flex items-center gap-1.5 shrink-0">
                                <span
                                  className={cx(
                                    "rounded-md border px-1.5 py-0.5 text-[8px] font-black uppercase tracking-widest",
                                    entryTargetType === "brand"
                                      ? "border-violet-400/30 bg-violet-500/10 text-violet-300"
                                      : "border-[color-mix(in_srgb,var(--purple)_30%,transparent)] bg-cyan-500/10 text-(--purple)"
                                  )}
                                >
                                  {entryTargetType}
                                </span>
                                <span
                                  className={cx(
                                    "rounded-md border px-1.5 py-0.5 text-[8px] font-black uppercase tracking-widest",
                                    isSelected
                                      ? "border-primary/30 bg-primary/10 text-primary"
                                      : "border-(--line) bg-(--line-2) text-(--t-3)"
                                  )}
                                >
                                  {auditTypeLabel}
                                </span>
                                <span
                                  className={cx(
                                    "rounded-md border px-1.5 py-0.5 text-[8px] font-black uppercase tracking-widest",
                                    statusLabel === "FAILED"
                                      ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
                                      : statusLabel === "DEGRADED"
                                        ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
                                        : statusLabel === "ARCHIVED"
                                          ? "border-sky-500/30 bg-sky-500/10 text-sky-300"
                                          : statusLabel === "PURGED"
                                            ? "border-zinc-500/30 bg-zinc-500/10 text-zinc-400"
                                            : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300"
                                  )}
                                >
                                  {statusLabel}
                                </span>
                              </div>
                            </div>

                            <div className="flex items-center justify-between">
                              <span className="text-[9px] font-black uppercase tracking-widest text-(--t-3) group-hover:text-(--t-3) transition-colors">
                                <ClientSafeDate date={entry.createdAt} />
                              </span>
                            </div>

                            <div className="grid grid-cols-3 gap-2">
                              {[
                                { label: "SEO", value: formatHistoryScore(entry.seoScore) },
                                { label: "AI answers", value: formatHistoryScore(entry.aeoScore) },
                                {
                                  label: "AI visibility",
                                  value: formatHistoryScore(entry.geoScore),
                                },
                              ].map((score) => (
                                <div
                                  key={score.label}
                                  className={cx(
                                    "flex items-center justify-between rounded-lg border px-2 py-1.5",
                                    isSelected
                                      ? "border-primary/20 bg-primary/5"
                                      : "border-(--line) bg-black/30"
                                  )}
                                >
                                  <span className="text-[8px] font-black uppercase tracking-widest text-(--t-3)">
                                    {score.label}
                                  </span>
                                  <span
                                    className={cx(
                                      "text-[10px] font-black",
                                      isSelected ? "text-primary" : "text-(--t-2)"
                                    )}
                                  >
                                    {score.value}
                                  </span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}

            {/* Main Content Stage */}
            <div className="flex flex-1 flex-col relative min-w-0 min-h-0 bg-(--paper)">
              <div className="sticky top-0 z-20 border-b border-(--line) bg-(--panel) ">
                <div className="px-8 py-6 md:px-12">
                  {activeReport ? (
                    <div className="flex flex-col gap-8">
                      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-3 mb-2">
                            <div className="h-1.5 w-1.5 rounded-full bg-primary animate-pulse shadow-[0_0_10px_var(--primary)]" />
                            <span className="text-[10px] font-black uppercase tracking-[0.2em] text-primary">
                              Results Active
                            </span>
                          </div>
                          <h2
                            className="truncate text-2xl md:text-3xl font-black tracking-tighter text-(--t-1) flex items-center gap-4 uppercase "
                            title={activeTargetLabel}
                          >
                            {activeTargetLabel.replace(/^https?:\/\/(www\.)?/, "")}
                            {activeTargetUrl ? (
                              <a
                                href={activeTargetUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="h-9 w-9 rounded-xl flex items-center justify-center bg-(--line-2) border border-(--line) text-(--t-3) hover:text-primary hover:border-primary/20 hover:shadow-[0_0_15px_rgba(6,182,212,0.1)] transition-all"
                              >
                                <Globe className="w-4 h-4" />
                              </a>
                            ) : null}
                          </h2>
                          <p className="text-[10px] font-black uppercase tracking-[0.15em] text-(--t-3) mt-2 flex items-center gap-2">
                            Audit Results ({activeTargetType}) • Scoped:{" "}
                            {activeAuditMeta?.createdAt ? (
                              <ClientSafeDate date={activeAuditMeta.createdAt} />
                            ) : (
                              "Pending"
                            )}
                          </p>
                        </div>

                        <div className="flex flex-col items-end gap-3 shrink-0">
                          <div className="flex items-center gap-4 bg-(--line-2) border border-(--line) rounded px-6 py-4 shadow-inner w-full justify-end">
                            <div className="flex flex-col items-end">
                              <span className="text-[9px] font-black uppercase tracking-[0.2em] text-(--t-3) mb-0.5">
                                Overall Score
                              </span>
                              <div className="flex items-baseline gap-1">
                                <span className="text-3xl font-black text-primary drop-shadow-[0_0_15px_rgba(6,182,212,0.3)]">
                                  {overallScore}
                                </span>
                                <span className="text-xs font-black text-(--t-3)">/100</span>
                              </div>
                            </div>
                          </div>
                          {!isEmbedded && (
                            <button
                              type="button"
                              onClick={() => setActiveTab("export")}
                              aria-pressed={activeTab === "export"}
                              className={cx(
                                "w-full flex items-center justify-center gap-2 h-10 px-4 rounded-xl border text-xs font-bold transition-all",
                                activeTab === "export"
                                  ? "border-primary/20 bg-primary/10 text-primary shadow-[0_0_15px_rgba(6,182,212,0.12)]"
                                  : "border-(--line) bg-(--line-2) text-(--t-2) hover:bg-(--line-2) hover:text-(--t-1)"
                              )}
                            >
                              <FileText
                                className={cx(
                                  "w-4 h-4 leading-none",
                                  activeTab === "export" ? "text-primary" : "text-(--t-3)"
                                )}
                              />
                              Report exports
                            </button>
                          )}
                        </div>
                      </div>

                      {/* Automation Controls */}
                      {!isEmbedded && (
                        <div className="w-full">
                          <ScheduleAutomation
                            targetUrl={activeTargetUrl}
                            isLocked={readOnly}
                            projectId={effectiveProjectId}
                            auditParams={scheduleAuditParams}
                          />
                        </div>
                      )}

                      <div className="flex items-center gap-0.5 overflow-x-auto pb-1 no-scrollbar scroll-smooth">
                        {tabs
                          .filter((tab) => !(isEmbedded && tab.id === "export"))
                          .filter(
                            (tab) =>
                              !(
                                isGuest &&
                                ["competitors", "entities", "hallucinations"].includes(tab.id)
                              )
                          )
                          .filter((tab) => !(isBrandWithoutUrl && tab.id === "technical"))
                          .map((tab) => {
                            const isActive = activeTab === tab.id;
                            const isGuestLocked = isGuest && ["aeo", "geo"].includes(tab.id);
                            return (
                              <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={cx(
                                  "whitespace-nowrap px-3 py-3.5 text-xs font-black uppercase tracking-[0.15em] min-h-[44px] flex items-center transition-all duration-500 relative group/tab md:px-4 md:py-3 md:text-[10px] md:tracking-[0.2em] md:min-h-0",
                                  isActive ? "text-primary" : "text-(--t-3) hover:text-(--t-2)"
                                )}
                              >
                                <span className="relative z-10 flex items-center gap-2.5">
                                  {tab.id === "overview" && (
                                    <Layers className="w-3.5 h-3.5 transition-transform group-hover/tab:scale-110" />
                                  )}
                                  {tab.id === "seo" && (
                                    <Search className="w-3.5 h-3.5 transition-transform group-hover/tab:scale-110" />
                                  )}
                                  {tab.id === "aeo" && (
                                    <Sparkles className="w-3.5 h-3.5 transition-transform group-hover/tab:scale-110" />
                                  )}
                                  {tab.id === "geo" && (
                                    <GeoIcon className="w-3.5 h-3.5 transition-transform group-hover/tab:scale-110" />
                                  )}
                                  {tab.id === "technical" && (
                                    <Activity className="w-3.5 h-3.5 transition-transform group-hover/tab:scale-110" />
                                  )}
                                  {tab.label}
                                  {isGuestLocked && <Lock className="w-3 h-3 text-(--t-3)" />}
                                </span>
                                {isActive && (
                                  <motion.div
                                    layoutId="activeWorkspaceTab"
                                    className="absolute inset-0 bg-primary/5 rounded-xl border border-primary/10"
                                  />
                                )}
                              </button>
                            );
                          })}
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-6 py-4">
                      <div className="w-14 h-14 rounded bg-(--line-2) border border-(--line) flex items-center justify-center text-(--t-3)">
                        <Activity className="w-6 h-6 animate-pulse" />
                      </div>
                      <div>
                        <h2 className="text-lg font-black text-(--t-1) tracking-tight uppercase">
                          Awaiting Selection
                        </h2>
                        <p className="text-[11px] text-(--t-3) font-bold uppercase tracking-widest mt-1">
                          Choose an audit from the history panel
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Scrollable Report Content */}
              <div
                className={cx(
                  "flex-1 p-8",
                  isEmbedded
                    ? "overflow-visible"
                    : "overflow-y-auto scrollbar-thin scrollbar-thumb-white/5 hover:scrollbar-thumb-white/10"
                )}
              >
                {workspaceHistory.reportLoading && (
                  <div className="flex h-full min-h-[400px] items-center justify-center">
                    <div className="flex flex-col items-center gap-6">
                      <div className="relative">
                        <Loader2 className="h-10 w-10 animate-spin text-primary" />
                        <div className="absolute inset-0 blur-xl bg-primary/20 animate-pulse" />
                      </div>
                      <p className="font-black tracking-[0.3em] uppercase text-[10px] text-(--t-3) animate-pulse">
                        Loading assessment data
                      </p>
                    </div>
                  </div>
                )}

                {workspaceHistory.reportError && (
                  <SignalAlert tone="danger" title="Error Loading Data">
                    {workspaceHistory.reportError}
                  </SignalAlert>
                )}

                {!workspaceHistory.reportLoading &&
                  !workspaceHistory.reportError &&
                  !activeReport &&
                  workspaceHistory.isActiveAuditArchived && (
                    <div className="flex h-full min-h-[400px] flex-col items-center justify-center gap-6 text-center">
                      <div className="relative group">
                        <div className="absolute inset-0 bg-sky-500/10 blur-2xl opacity-50 rounded-full" />
                        <div className="relative h-20 w-20 rounded bg-sky-500/5 border border-sky-500/20 flex items-center justify-center text-sky-400">
                          <Archive className="h-10 w-10 opacity-60" />
                        </div>
                      </div>
                      <div>
                        <p className="text-xl font-black tracking-tight text-(--t-1) uppercase mb-2">
                          Report Archived
                        </p>
                        <p className="max-w-sm text-[11px] leading-relaxed text-(--t-3) font-bold uppercase tracking-widest">
                          This audit report has been archived. Scores and summary are still
                          available. Full report data is no longer accessible.
                        </p>
                      </div>
                    </div>
                  )}

                {!workspaceHistory.reportLoading &&
                  !workspaceHistory.reportError &&
                  !activeReport &&
                  !workspaceHistory.isActiveAuditArchived && (
                    <div className="flex h-full min-h-[400px] flex-col items-center justify-center gap-6 text-center">
                      <div className="relative group">
                        <div className="absolute inset-0 bg-primary/10 blur-2xl opacity-0 group-hover:opacity-100 transition-opacity duration-1000 rounded-full" />
                        <div className="relative h-20 w-20 rounded bg-(--line-2) border border-(--line) flex items-center justify-center text-(--t-3) group-hover:text-primary group-hover:border-primary/20 transition-all duration-700">
                          <FileJson className="h-10 w-10 opacity-30 group-hover:opacity-100" />
                        </div>
                      </div>
                      <div>
                        <p className="text-xl font-black tracking-tight text-(--t-1) uppercase mb-2">
                          No Audit Selected
                        </p>
                        <p className="max-w-xs text-[11px] leading-relaxed text-(--t-3) font-bold uppercase tracking-widest">
                          Select a recorded audit from the history panel to view results.
                        </p>
                      </div>
                    </div>
                  )}

                {!workspaceHistory.reportLoading &&
                  !workspaceHistory.reportError &&
                  activeReport && (
                    <div className="mx-auto max-w-6xl min-h-[60vh] space-y-10 animate-in fade-in slide-in-from-bottom-8 duration-1000">
                      {activeTab === "overview" && (
                        <TierPreviewControl
                          value={previewPlanKey}
                          onPreviewTier={setPreviewPlanKey}
                        />
                      )}
                      {activeTab === "overview" && (
                        <OverviewTab
                          report={activeReport}
                          overallScore={overallScore}
                          seoScore={seoScore}
                          aeoScore={aeoScore}
                          geoScore={geoScore}
                          performance={performance}
                          network={network}
                          structuredDataDetected={structuredDataDetected}
                          seoStatus={seoStatus}
                          scoreGroups={scoreGroups}
                          allRecommendations={allRecommendations}
                          aeoTabData={aeoTabData}
                          geoTabData={geoTabData}
                          readOnly={readOnly}
                          projectId={effectiveProjectId}
                          auditId={activeAuditMeta?.id}
                          comparisonData={comparisonData}
                          sampleMode={accessLevel === "sample" || accessLevel === "guest"}
                          isBrandWithoutUrl={isBrandWithoutUrl}
                          onNavigateToTab={(tab) => setActiveTab(tab as TabId)}
                          canSeeComparison={displayCanSeeComparison}
                          canSeeAdvisor={displayCanSeeAdvisor}
                          canSeeExecution={displayCanSeeExecution}
                          guestAuditToken={guestAuditToken}
                        />
                      )}

                      {activeTab !== "overview" && (
                        <IntegrityStatusBanner report={activeReport} variant="detailed" />
                      )}

                      {activeTab === "competitors" && (
                        <TabErrorBoundary sectionName="Competitors">
                          <CompetitorsTab
                            competitors={
                              Array.isArray(activeReport?.competitors)
                                ? activeReport.competitors
                                : []
                            }
                            competitorSummary={
                              activeReport?.metadata &&
                              typeof activeReport.metadata.competitor_summary === "object" &&
                              activeReport.metadata.competitor_summary !== null
                                ? activeReport.metadata.competitor_summary
                                : undefined
                            }
                            lockedSection={getAuditLockedSection(activeReport, "competitors")}
                          />
                        </TabErrorBoundary>
                      )}

                      {activeTab === "seo" && (
                        <TabErrorBoundary sectionName="SEO Analysis">
                          <SeoTab
                            performance={performance}
                            seoAudits={seoAudits}
                            structuredDataDetected={structuredDataDetected}
                            lcpValue={lcpValue}
                            clsValue={clsValue}
                            isBrandWithoutUrl={isBrandWithoutUrl}
                          />
                        </TabErrorBoundary>
                      )}

                      {activeTab === "aeo" && (
                        <TabErrorBoundary sectionName="AI answers analysis">
                          {isGuest ? (
                            <GatedSection
                              title="AI answers intelligence"
                              teaser={`${activeReport?.structured_findings?.aeo_findings?.total_count ?? 0} AI answers findings discovered. Sign up to see the full breakdown.`}
                              // SIGV2-1221: a guest gate withholds the tab
                              // from anyone who has not signed up, and the
                              // free Starter plan unlocks it, so this card
                              // names no plan. It used to say "Available on
                              // Specialist and above" next to a Start Free
                              // CTA, which contradicted itself and put a
                              // price on something that costs nothing.
                              guestAuditToken={guestAuditToken}
                              blurredPreview={
                                <AeoTab
                                  aeoScore={aeoScore}
                                  aeoScoreEntries={aeoScoreEntries}
                                  aeoEntityClarity={aeoEntityClarity}
                                  aeoRecommendations={aeoRecommendations}
                                  readabilityFindings={aeoReadabilityFindings}
                                  rewriteSuggestions={aeoRewriteSuggestions}
                                  contextUrl={activeAuditMeta?.url || activeReport?.url || null}
                                  entityNames={normalizedEntities.map((entity) => entity.name)}
                                  projectId={effectiveProjectId}
                                  auditId={activeAuditMeta?.id}
                                  lockedSection={getAuditLockedSection(
                                    activeReport,
                                    "semantic_graph"
                                  )}
                                />
                              }
                            />
                          ) : (
                            <div className="relative">
                              {showLockOverlay && (
                                <FeatureLockOverlay
                                  title="AI answers intelligence"
                                  description="Unlock AI answers protocols and semantic visibility metrics."
                                  ctaLabel="Activate Subscription"
                                  href="/dashboard/billing"
                                />
                              )}
                              <div
                                className={cx(
                                  "transition-all duration-1000",
                                  showLockOverlay
                                    ? "blur-[6px] opacity-30 select-none pointer-events-none"
                                    : ""
                                )}
                              >
                                <AeoTab
                                  aeoScore={aeoScore}
                                  aeoScoreEntries={aeoScoreEntries}
                                  aeoEntityClarity={aeoEntityClarity}
                                  aeoRecommendations={aeoRecommendations}
                                  readabilityFindings={aeoReadabilityFindings}
                                  rewriteSuggestions={aeoRewriteSuggestions}
                                  contextUrl={activeAuditMeta?.url || activeReport?.url || null}
                                  entityNames={normalizedEntities.map((entity) => entity.name)}
                                  getAuthHeaders={getAuthHeaders}
                                  projectId={effectiveProjectId}
                                  auditId={activeAuditMeta?.id}
                                  lockedSection={getAuditLockedSection(
                                    activeReport,
                                    "semantic_graph"
                                  )}
                                />
                              </div>
                            </div>
                          )}
                        </TabErrorBoundary>
                      )}

                      {activeTab === "geo" && (
                        <TabErrorBoundary sectionName="AI visibility analysis">
                          {isGuest ? (
                            <GatedSection
                              title="AI visibility analysis"
                              teaser={`${activeReport?.structured_findings?.geo_findings?.total_count ?? 0} AI visibility findings discovered. Sign up to see the full breakdown.`}
                              // SIGV2-1221: a guest gate withholds the tab
                              // from anyone who has not signed up, and the
                              // free Starter plan unlocks it, so this card
                              // names no plan. It used to say "Available on
                              // Specialist and above" next to a Start Free
                              // CTA, which contradicted itself and put a
                              // price on something that costs nothing.
                              guestAuditToken={guestAuditToken}
                              blurredPreview={
                                <GeoTab
                                  geoScore={geoScore}
                                  geoSummary={geoSummary}
                                  geoTabData={geoTabData}
                                  geoRecommendations={geoRecommendations}
                                  contextUrl={activeAuditMeta?.url || activeReport?.url || null}
                                  entityNames={normalizedEntities.map((entity) => entity.name)}
                                  projectId={effectiveProjectId}
                                  auditId={activeAuditMeta?.id}
                                  isBrandWithoutUrl={isBrandWithoutUrl}
                                  lockedSection={getAuditLockedSection(
                                    activeReport,
                                    "brand_integrity"
                                  )}
                                />
                              }
                            />
                          ) : (
                            <div className="relative">
                              {showLockOverlay && (
                                <FeatureLockOverlay
                                  title="AI visibility analysis"
                                  description="Unlock AI visibility performance tracking and citation authority data."
                                  ctaLabel="Activate Subscription"
                                  href="/dashboard/billing"
                                />
                              )}
                              <div
                                className={cx(
                                  "transition-all duration-1000",
                                  showLockOverlay
                                    ? "blur-[6px] opacity-30 select-none pointer-events-none"
                                    : ""
                                )}
                              >
                                <GeoTab
                                  geoScore={geoScore}
                                  geoSummary={geoSummary}
                                  geoTabData={geoTabData}
                                  geoRecommendations={geoRecommendations}
                                  contextUrl={activeAuditMeta?.url || activeReport?.url || null}
                                  entityNames={normalizedEntities.map((entity) => entity.name)}
                                  getAuthHeaders={getAuthHeaders}
                                  projectId={effectiveProjectId}
                                  auditId={activeAuditMeta?.id}
                                  isBrandWithoutUrl={isBrandWithoutUrl}
                                  lockedSection={getAuditLockedSection(
                                    activeReport,
                                    "brand_integrity"
                                  )}
                                />
                              </div>
                            </div>
                          )}
                        </TabErrorBoundary>
                      )}

                      {activeTab === "entities" && (
                        <TabErrorBoundary sectionName="Entities">
                          <div className="relative">
                            {showLockOverlay && (
                              <FeatureLockOverlay
                                title="Entity Coverage"
                                description="Map and optimize semantic entities to build authority within LLM training sets."
                                ctaLabel="Activate Subscription"
                                href="/dashboard/billing"
                              />
                            )}
                            <div
                              className={cx(
                                "transition-all duration-1000",
                                showLockOverlay
                                  ? "blur-[6px] opacity-30 select-none pointer-events-none"
                                  : ""
                              )}
                            >
                              <EntitiesTab
                                editableEntities={auditForm.editableEntities}
                                setEditableEntities={
                                  readOnly ? undefined : auditForm.setEditableEntities
                                }
                                entityChipSuggestions={entityChipSuggestions}
                                entitySummary={auditForm.entitySummary}
                                readOnly={readOnly}
                                lockedSection={getAuditLockedSection(activeReport, "entities")}
                              />
                            </div>
                          </div>
                        </TabErrorBoundary>
                      )}

                      {activeTab === "technical" && (
                        <TabErrorBoundary sectionName="Technical Analysis">
                          {isBrandWithoutUrl ? (
                            <div className="flex flex-col items-center justify-center gap-4 py-20 text-center">
                              <div className="rounded-xl border border-(--line) bg-(--line-2) px-8 py-6">
                                <h3 className="text-lg font-semibold text-(--t-1)">
                                  Technical Metrics Unavailable
                                </h3>
                                <p className="mt-2 max-w-md text-sm text-(--t-2)">
                                  Brand-only audits derive insights from entity signals and search
                                  presence rather than website technical analysis. Add a URL to
                                  include Core Web Vitals, network protocols, and crawl diagnostics.
                                </p>
                              </div>
                            </div>
                          ) : (
                            <TechnicalTab
                              performance={performance}
                              network={network}
                              technicalSignals={activeReport.technical_signals ?? null}
                            />
                          )}
                        </TabErrorBoundary>
                      )}

                      {activeTab === "hallucinations" && (
                        <TabErrorBoundary sectionName="Hallucinations">
                          <HallucinationsTab hallucination={activeReport?.hallucination ?? null} />
                        </TabErrorBoundary>
                      )}

                      {activeTab === "export" && !isEmbedded && (
                        <TabErrorBoundary sectionName="Export">
                          <div className="relative">
                            {showLockOverlay && (
                              <FeatureLockOverlay
                                title="Export Gateway"
                                description="Generate comprehensive reports in PDF and JSON for stakeholder distribution."
                                ctaLabel="Activate Subscription"
                                href="/dashboard/billing"
                              />
                            )}
                            <div
                              className={cx(
                                "transition-all duration-1000",
                                showLockOverlay
                                  ? "blur-[6px] opacity-30 select-none pointer-events-none"
                                  : ""
                              )}
                            >
                              <ExportTab
                                handleCopySummary={handleCopySummary}
                                handleExportJson={handleExportJson}
                                copyStatus={copyStatus}
                                activeReport={activeReport}
                                activeAuditMeta={activeAuditMeta}
                                getAuthHeaders={getAuthHeaders}
                              />
                            </div>
                          </div>
                        </TabErrorBoundary>
                      )}
                    </div>
                  )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {!isEmbedded && (
        <>
          <CommandPalette
            setActiveTab={setActiveTab}
            onRunAudit={readOnly ? undefined : auditRunner.handleSubmit}
            onExportJson={handleExportJson}
          />
        </>
      )}
    </>
  );
}
