"use client";

import { asset } from "@/lib/basePath";
import React, { useCallback, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import AuditConfigurationForm from "@/components/results/AuditConfigurationForm";
import SignalCrumb from "@/components/signal/SignalCrumb";
import { useAuth } from "@/contexts/AuthContext";
import { useAuditForm } from "@/hooks/useAuditForm";
import { useAuditNotification } from "@/hooks/useAuditNotification";
import { useAuditRunner } from "@/hooks/useAuditRunner";
import { useBillingSettings } from "@/hooks/useBillingSettings";
import { useScanPrompts } from "@/hooks/useScanPrompts";
import { useTierDurations } from "@/hooks/useTierDurations";
import { useWorkspaceHistory } from "@/hooks/useWorkspaceHistory";
import { findPreviousScan, resolveScanVisibilityStat } from "@/lib/auditScanRun";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { clearScanLaunchIntent, isSameTarget, peekScanLaunchIntent } from "@/lib/scanLaunchIntent";
import { fetchVisibilitySummary } from "@/services/monitoringService";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

// SIGV2-1163: a finished scan does NOT navigate on its own, and must not be
// made to again without a conversation first.
//
// A timed redirect was tried on this page and withdrawn. The approved design
// (mockup: Signal Audit Run.html) makes the completed scan a terminal state
// with four actions the user chooses between - the report, the fixes, the
// dashboard, and running another scan - and moving the page out of an approved
// terminal state a couple of seconds later fights that design: it gives
// someone reaching for one of those four actions no time to take it, and the
// faster the reader the more likely the page moves under their cursor.
// Cancelling the move on first interaction, which the withdrawn version did,
// only narrows the window; it does not make an unrequested navigation the
// right default.
//
// The original complaint was that the Dashboard control did not work, not that
// the page failed to leave on its own. That is fixed independently by
// SIGV2-1164 (`projectDashboardHref` below), which points the crumb and the
// dashboard action at the project dashboard rather than the workspace
// overview. `page.test.tsx` pins both the destination and the fact that a
// completed run stays put.

const START_CHECK_TABS = ["start", "history"] as const;

type StartCheckTab = (typeof START_CHECK_TABS)[number];

export function resolveStartCheckTab(raw: string | null | undefined): StartCheckTab {
  const normalized = raw?.trim().toLowerCase() ?? "";
  return (START_CHECK_TABS as readonly string[]).includes(normalized)
    ? (normalized as StartCheckTab)
    : "start";
}

export default function AuditDashboardPage() {
  const { t } = useTranslation();
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedUrl = useMemo(() => searchParams.get("url")?.trim() ?? "", [searchParams]);
  const requestedProjectId = useMemo(() => {
    const rawValue = searchParams.get("projectId")?.trim() ?? "";
    const parsedValue = Number(rawValue);
    return Number.isInteger(parsedValue) && parsedValue > 0 ? parsedValue : undefined;
  }, [searchParams]);

  // SIGV2-1187: scan history lives on the project dashboard now. Old
  // `?tab=history` links that name a project land on its expanded history
  // card; a bare `?tab=history` stays on the setup form it now is.
  React.useEffect(() => {
    if (
      resolveStartCheckTab(searchParams.get("tab")) === "history" &&
      requestedProjectId !== undefined
    ) {
      router.replace(`/dashboard/projects/${requestedProjectId}#scan-history`);
    }
  }, [router, searchParams, requestedProjectId]);
  const requestedTargetType = useMemo(() => {
    const normalized = searchParams.get("targetType")?.trim().toLowerCase();
    if (normalized === "brand") return "brand";
    if (normalized === "website") return "website";
    return null;
  }, [searchParams]);
  const requestedTargetName = useMemo(
    () => searchParams.get("targetName")?.trim() ?? "",
    [searchParams]
  );
  const requestedTier = useMemo(() => {
    const normalized = searchParams.get("tier")?.trim().toLowerCase();
    if (normalized === "deep_judgment") return "deep_judgment";
    if (normalized === "deep" || normalized === "smart") return "smart";
    if (normalized === "fast") return "fast";
    return null;
  }, [searchParams]);
  const reattachJobId = useMemo(() => searchParams.get("reattach")?.trim() || null, [searchParams]);

  const { getToken, isSignedIn, user } = useAuth();

  const getAuthHeaders = React.useCallback(async () => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const scannerRef = useRef<{ triggerAiScan: () => void }>(null);
  const hasAppliedSearchPrefill = useRef(false);
  const hasAutoStarted = useRef(false);
  const { notify, requestPermission } = useAuditNotification();

  const triggerAiScan = useCallback(() => {
    scannerRef.current?.triggerAiScan?.();
  }, []);

  const auditForm = useAuditForm({
    getAuthHeaders,
    onAutoDetectStart: triggerAiScan,
    // SIGV2-1170: a target the link names explicitly outranks a stored draft,
    // so `?url=` is never displayed under a different site's saved form.
    linkTarget: requestedUrl || requestedTargetName || undefined,
  });

  const { form } = auditForm;

  React.useEffect(() => {
    if (hasAppliedSearchPrefill.current) {
      return;
    }

    if (!requestedUrl && !requestedTargetType && !requestedTargetName && !requestedTier) {
      return;
    }

    if (requestedTargetType) {
      auditForm.setFormValue("auditTargetType", requestedTargetType);
    }
    if (requestedTier) {
      auditForm.setFormValue("tier", requestedTier);
    }
    if (requestedTargetName && form.targetName.trim().length === 0) {
      auditForm.setFormValue("targetName", requestedTargetName);
    }
    if (requestedUrl) {
      if (form.url.trim().length === 0) {
        auditForm.setFormValue("url", requestedUrl);
      }
      if (form.targetUrl.trim().length === 0) {
        auditForm.setFormValue("targetUrl", requestedUrl);
      }
    }

    hasAppliedSearchPrefill.current = true;
  }, [
    auditForm,
    form.targetName,
    form.targetUrl,
    form.url,
    requestedTargetName,
    requestedTargetType,
    requestedTier,
    requestedUrl,
  ]);

  const workspaceHistory = useWorkspaceHistory({
    getAuthHeaders,
    isSignedIn: !!isSignedIn,
  });
  const billingSettings = useBillingSettings();
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
  const highConfidenceEligiblePlanLabels = useMemo(() => {
    const labels = billingPlans
      .filter((plan) => plan.capabilities.has_high_confidence_mode === true)
      .map((plan) => plan.name);
    return labels.length ? labels : ["Specialist", "Executive"];
  }, [billingPlans]);
  const formatPlanName = useCallback(
    (planId: string | null | undefined) =>
      String(planId ?? "")
        .split("_")
        .filter(Boolean)
        .map((segment) => segment.charAt(0).toUpperCase() + segment.slice(1))
        .join(" ") || "Unknown plan",
    []
  );
  const currentPlanLabel =
    currentBillingPlan?.name ??
    formatPlanName(billingOverview?.current_plan ?? user?.subscription_plan ?? null);

  const auditRunner = useAuditRunner({
    getAuthHeaders,
    isSignedIn: !!isSignedIn,
    projectId: requestedProjectId,
    reattachJobId,
    form: auditForm.form,
    validateForm: auditForm.validateForm,
    verifyUrlPreflight: auditForm.verifyUrlPreflight,
    fetchAuditRecord: workspaceHistory.fetchAuditRecord,
    invalidateHistory: workspaceHistory.invalidateHistory,
    upsertHistoryEntry: workspaceHistory.upsertHistoryEntry,
    // A finished scan notifies and stays put: the completed state is where
    // the user chooses what to do next (SIGV2-1163, see the note at the top of
    // this file). Nothing here navigates.
    onAuditComplete: (entry) => {
      const label = entry.targetName || entry.url || "Your audit";
      void notify({
        title: "Audit Complete",
        body: `${label}, score: ${entry.geoScore ?? "N/A"}`,
        onClick: () => {
          window.location.href = asset(`/dashboard/audit/${entry.id}`);
        },
      });
    },
  });

  // Request browser notification permission when an audit starts running
  React.useEffect(() => {
    if (auditRunner.isPolling) void requestPermission();
  }, [auditRunner.isPolling, requestPermission]);

  // SIGV2-1176: prompts are part of scan setup, and at least one is mandatory
  // to launch. The list is read here, once, so the Launch gate below and the
  // prompts section inside the form cannot disagree about whether this project
  // has a prompt. `blocksLaunch` is deliberately narrow (see useScanPrompts):
  // it is false when there is no project yet, when the list could not be read,
  // and when the plan permits no prompts at all, because a customer must never
  // be unable to scan over a requirement they cannot meet.
  const scanPrompts = useScanPrompts({
    projectId: requestedProjectId,
    isSignedIn: !!isSignedIn,
    getAuthHeaders,
  });

  // SIGV2-1177: the per-depth durations the page states are measured, read
  // once here so the depth table and the Launch sentence share one figure.
  // A tier with no publishable measurement states nothing.
  const tierDurations = useTierDurations({
    isSignedIn: !!isSignedIn,
    getAuthHeaders,
  });

  const highConfidencePlanLocked = form.tier === "deep_judgment" && !hasHighConfidenceMode;
  const isStartDisabled =
    auditRunner.isLoading ||
    auditRunner.isPolling ||
    auditForm.isPreflightChecking ||
    Boolean(auditForm.preflightError) ||
    highConfidencePlanLocked ||
    scanPrompts.blocksLaunch;

  // SIGV2-1159: one clear path from the onboarding's "Run my first scan" to
  // the scan running, so the approved run view replaces the setup form instead
  // of the customer meeting a second setup page.
  //
  // The authority for starting is a launch intent in `sessionStorage`, never
  // the URL. No query parameter can authorise a scan: the form prefills itself
  // from `?url=`, so a URL-derived check would compare an attacker-supplied
  // value against itself and `?url=attacker.tld` would spend a signed-in
  // customer's scan on a target they never chose. An intent cannot be written
  // by a link, only by our own launch path in this tab, and it is consumed
  // before the run starts so a reload cannot start a second scan.
  //
  // Every other guard stays: once per visit, signed in, no run attached or in
  // flight, the form not blocked (validation, preflight, plan-locked depth),
  // and the form's target still has to be the one the intent names. A target
  // that cannot start leaves the form on screen with its own error, which is
  // where the customer would have been anyway.
  const startScan = auditRunner.handleSubmit;
  const currentRunPhase = auditRunner.runPhase;
  React.useEffect(() => {
    if (hasAutoStarted.current) return;
    if (!isSignedIn || reattachJobId) return;
    if (currentRunPhase !== "idle" || isStartDisabled) return;

    const intent = peekScanLaunchIntent();
    if (!intent) return;

    // A URL that names a project must name the intent's project. Without this,
    // a crafted link arriving inside a live intent's window could keep the
    // target the intent authorised while redirecting the run at a project of
    // the sender's choosing.
    if (requestedProjectId !== undefined && requestedProjectId !== intent.projectId) return;

    // Read before consuming: the first pass runs before the prefill lands, and
    // an intent consumed then would be gone before its target could match.
    const formTarget = form.targetUrl.trim() || form.url.trim();
    if (!formTarget || !isSameTarget(formTarget, intent.target)) return;

    hasAutoStarted.current = true;
    clearScanLaunchIntent();
    void startScan();
  }, [
    currentRunPhase,
    form.targetUrl,
    form.url,
    isSignedIn,
    isStartDisabled,
    reattachJobId,
    requestedProjectId,
    startScan,
  ]);

  // The comparison baseline for the succeeded state: the most recent earlier
  // scan of the same target. Null when the target has never been scanned
  // before, which the run view says rather than implying a delta.
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

  const runPhase = auditRunner.runPhase;

  // The approved succeeded view's third stat is the project's measured AI
  // visibility, which the monitoring runs produce and a scan does not
  // (SIGV2-1123). The run itself carries no project id, so it comes from the
  // history entry for the finished audit, and from the ?projectId= the page
  // was opened with until history catches up. Null means there is no project
  // behind this scan, and then the view shows two stats.
  const completedAuditId =
    auditRunner.completedAuditMeta?.auditId ?? auditRunner.runSnapshot?.auditId ?? null;
  const scanProjectId = useMemo(() => {
    const fromHistory =
      completedAuditId === null
        ? undefined
        : workspaceHistory.sortedHistory.find((entry) => entry.id === completedAuditId)?.projectId;
    return fromHistory ?? requestedProjectId ?? null;
  }, [completedAuditId, requestedProjectId, workspaceHistory.sortedHistory]);

  const [visibilitySummary, setVisibilitySummary] = useState<VisibilitySummaryResponse | null>(
    null
  );
  React.useEffect(() => {
    if (runPhase !== "succeeded" || !scanProjectId || !isSignedIn) {
      setVisibilitySummary(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const headers = await getAuthHeaders();
        const summary = await fetchVisibilitySummary(scanProjectId, headers);
        if (!cancelled) setVisibilitySummary(summary);
      } catch {
        // No figure rather than a guessed one.
        if (!cancelled) setVisibilitySummary(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, isSignedIn, runPhase, scanProjectId]);

  const scanVisibility = useMemo(
    () => resolveScanVisibilityStat(visibilitySummary),
    [visibilitySummary]
  );

  // SIGV2-1164: on these surfaces "Dashboard" means this project's dashboard,
  // as in the approved design: the Audit Run crumb and its "Back to dashboard"
  // action both point at Signal Overview.html, which is the project dashboard
  // (`/dashboard/projects/<id>`), not Signal Workspace Overview.html. They
  // pointed at the workspace overview instead, so the only dashboard
  // affordance on the finished-scan screen never reached the project
  // dashboard. The workspace overview stays as the honest fallback while the
  // scan has no project id to route to. Any id used here came from the API
  // (the audit's own project, or the `?projectId=` this page was opened with),
  // so this changes no authorization: the destination keeps its own plan and
  // workspace gating.
  const projectDashboardHref = scanProjectId
    ? `/dashboard/projects/${scanProjectId}`
    : "/dashboard";

  const runTarget = auditRunner.runSnapshot?.targetLabel?.trim() ?? "";
  const heading =
    runPhase === "idle"
      ? t("signalStartCheck.heading")
      : runTarget
        ? t("signalScanRun.heading", { target: runTarget })
        : t("signalScanRun.headingNoTarget");
  const intro =
    runPhase === "idle"
      ? t("signalStartCheck.intro")
      : runPhase === "succeeded"
        ? t("signalScanRun.statusSucceeded")
        : runPhase === "failed"
          ? t("signalScanRun.statusFailed")
          : t("signalScanRun.statusRunning");

  // Approved `.top > .crumb` on the run views: Dashboard > Start a scan >
  // this run (SIGV2-1123). The leaf names the phase the run is actually in
  // rather than the mockup's single static "Scan in progress", which would be
  // a false status word on a run that has already finished or failed. The
  // start-scan form keeps the bar's left side as it is; it is not part of this
  // change.
  const { setHeader } = useWorkspacePageHeader();
  const runCrumb = useMemo(() => {
    if (runPhase === "idle") return null;
    const leaf =
      runPhase === "succeeded"
        ? t("signalScanRun.crumbSucceeded")
        : runPhase === "failed"
          ? t("signalScanRun.crumbFailed")
          : t("signalScanRun.crumbRunning");
    return (
      <SignalCrumb
        items={[
          { label: t("signalScanRun.crumbHome"), href: projectDashboardHref },
          { label: t("signalStartCheck.heading"), href: "/dashboard/audit" },
          { label: leaf },
        ]}
      />
    );
  }, [projectDashboardHref, runPhase, t]);
  React.useEffect(() => {
    setHeader(runCrumb ? { crumb: runCrumb } : null);
    return () => setHeader(null);
  }, [setHeader, runCrumb]);

  return (
    <div className="dashboard-page-shell space-y-6 md:space-y-8">
      {/* Page title only — nav already carries the scan icon (UI/UX Fixes). */}
      <header className="min-w-0">
        <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold leading-[1.25] tracking-[-0.02em]">
          {heading}
        </h1>
        <p className="m-0 mt-2 max-w-[640px] text-[13px] leading-[1.5] text-(--t-2)">{intro}</p>
      </header>

      <AuditConfigurationForm
        ref={scannerRef}
        auditForm={auditForm}
        auditRunner={auditRunner}
        isStartDisabled={isStartDisabled}
        previousScan={previousScan}
        visibility={scanVisibility}
        dashboardHref={projectDashboardHref}
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
    </div>
  );
}
