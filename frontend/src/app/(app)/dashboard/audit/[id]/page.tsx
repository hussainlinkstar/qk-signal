"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";

import { buttonClasses } from "@/components/ui/Button";

import { useWorkspaceHistory } from "@/hooks/useWorkspaceHistory";
import { useRegisterProjectScope } from "@/components/dashboard/projectScope";
import { useAuth } from "@/contexts/AuthContext";
import { getAuditLockedSection } from "@/lib/reportAdapters";
import { computeAioScore } from "@/lib/aioScore";
import { resolvePlanCapabilities } from "@/lib/planCapabilities";
import { useAuditReportData } from "@/hooks/useAuditReportData";
import { useRoleMode } from "@/contexts/RoleModeContext";
import { shownInMode } from "@/lib/roleMode";

import TabErrorBoundary from "@/components/ui/TabErrorBoundary";
import OverviewTab from "@/components/results/tabs/OverviewTab";
import SeoTab from "@/components/results/tabs/SeoTab";
import AeoTab from "@/components/results/tabs/AeoTab";
import GeoTab from "@/components/results/tabs/GeoTab";
import ScoreFactorRow from "@/components/results/tabs/ScoreFactorRow";
import TechnicalTab from "@/components/results/tabs/TechnicalTab";
import EntitiesTab from "@/components/results/tabs/EntitiesTab";
import CompetitorsTab from "@/components/results/tabs/CompetitorsTab";
import HallucinationsTab from "@/components/results/tabs/HallucinationsTab";
import ClaimReviewQueue from "@/components/results/ClaimReviewQueue";
import { Spinner } from "@/components/ui/Loading";
import NotFoundContent from "@/components/NotFoundContent";
import {
  fetchClaimReviewSummary,
  type ClaimReviewSummaryResponse,
} from "@/services/claimReviewService";
import { fetchVisibilitySummary } from "@/services/monitoringService";
import type { VisibilitySummaryResponse } from "@/types/monitoring";
import { useAuditComparison } from "@/hooks/useAuditComparison";

import ReportHeader from "./report/ReportHeader";
import ReportDisclosure from "./report/ReportDisclosure";
import ScanResults from "./report/ScanResults";
import AioReportSection from "./report/AioReportSection";
import SeoReportSection from "./report/SeoReportSection";
import PrioritizedFixes from "./report/PrioritizedFixes";
import ActionSection from "./report/ActionSection";

import { useTranslation } from "react-i18next";

export default function AuditDetailsPage() {
  const { t } = useTranslation();
  const params = useParams<{ id: string }>();
  const auditId = useMemo(() => params?.id ?? "", [params?.id]);
  const router = useRouter();
  const { getToken, isSignedIn, user } = useAuth();
  const { roleMode } = useRoleMode();

  const [reviewSummary, setReviewSummary] = useState<ClaimReviewSummaryResponse | null>(null);
  const [visibilitySummary, setVisibilitySummary] = useState<VisibilitySummaryResponse | null>(
    null
  );

  const getAuthHeaders = React.useCallback(async () => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  const workspaceHistory = useWorkspaceHistory({
    getAuthHeaders,
    isSignedIn,
  });

  const numericAuditId = auditId ? Number(auditId) : null;

  // Make sure we set the ID in the hook if it's not already
  useEffect(() => {
    if (numericAuditId && workspaceHistory.selectedAuditId !== numericAuditId) {
      workspaceHistory.setSelectedAuditId(numericAuditId);
    }
  }, [numericAuditId, workspaceHistory]);

  const activeReport = workspaceHistory.activeReport;
  const activeAuditMeta = workspaceHistory.activeAuditMeta;

  const { data: comparisonData } = useAuditComparison(numericAuditId);

  const reportData = useAuditReportData({ activeReport, activeAuditMeta });
  const {
    isBrandWithoutUrl,
    aeoTabData,
    geoTabData,
    performance,
    network,
    technicalSignals,
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
    geoSummary,
    geoRecommendations,
    allRecommendations,
    normalizedEntities,
    scheduleAuditParams,
  } = reportData;

  const projectId = activeAuditMeta?.projectId;
  // SIGV2-1180: a report opened from a project's history is still that
  // project's view, so the sidebar keeps the project menu rather than falling
  // back to the workspace one. The URL names no project here, so the scope is
  // the audit's own served project and nothing the link can choose.
  useRegisterProjectScope(projectId ?? null);
  // Comparison search type is gated to Specialist+ via the competitor-analysis
  // capability (signal plan Phase 4). This detail route has no billing-overview
  // hook, so resolve from the authenticated user's subscription plan; unknown /
  // guest / Starter / Standard plans resolve to `false` (fail-safe LOCKED).
  const canSeeComparison = useMemo(
    () => resolvePlanCapabilities(user?.subscription_plan).has_competitor_analysis,
    [user?.subscription_plan]
  );
  // Advisor AI recommendations (Standard+) and done-for-you execution
  // (Executive+) are gated the same way (signal plan Phase 5). Unknown / guest /
  // Starter plans resolve to `false` (fail-safe LOCKED).
  const canSeeAdvisor = useMemo(
    () => resolvePlanCapabilities(user?.subscription_plan).has_advisor_recommendations,
    [user?.subscription_plan]
  );
  const canSeeExecution = useMemo(
    () => resolvePlanCapabilities(user?.subscription_plan).has_done_for_you_execution,
    [user?.subscription_plan]
  );
  const hasInitialReviewQueue = Boolean(
    typeof activeReport?.integrity_certificate?.summary?.track_b_needs_manual_review === "number" &&
    activeReport.integrity_certificate.summary.track_b_needs_manual_review > 0
  );

  useEffect(() => {
    let cancelled = false;

    async function loadReviewSummary() {
      if (!numericAuditId || !isSignedIn) {
        if (!cancelled) {
          setReviewSummary(null);
        }
        return;
      }

      try {
        const headers = await getAuthHeaders();
        const summary = await fetchClaimReviewSummary(numericAuditId, headers);
        if (!cancelled) {
          setReviewSummary(summary);
        }
      } catch {
        if (!cancelled) {
          setReviewSummary(null);
        }
      }
    }

    void loadReviewSummary();
    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, isSignedIn, numericAuditId]);

  const showReviewQueue = hasInitialReviewQueue || (reviewSummary?.total_flagged ?? 0) > 0;
  const hasActionSectionContent = Boolean(projectId) || Boolean(showReviewQueue && numericAuditId);
  const reviewQueuePendingCount =
    reviewSummary?.pending_count ??
    activeReport?.integrity_certificate?.summary?.track_b_needs_manual_review ??
    0;

  // Deep-link target used by components that still speak in tab ids: scroll to
  // the matching disclosure and open it.
  const navigateToSection = useCallback((tab: string) => {
    const node = document.getElementById(`report-sec-${tab}`);
    if (!node) return;
    node.scrollIntoView({ behavior: "smooth", block: "start" });
    const header = node.querySelector<HTMLButtonElement>("button.sh");
    if (header && header.getAttribute("aria-expanded") === "false") {
      header.click();
    }
  }, []);

  // SIGV2-1193: no local re-sort. `allRecommendations` is the single
  // consolidated list, already in the one ordering
  // (`compareConsolidatedFixes`), so these two sections are engine filters of
  // it and nothing more. The previous `sortByImpact` ranked on
  // `Math.abs(impactValue)`, which silently put every row the audit attached
  // no number to last regardless of its severity, and gave this screen an
  // order no other surface used.
  const aioFixes = useMemo(
    () =>
      allRecommendations.filter(
        (fix) => fix.engines?.includes("AEO") || fix.engines?.includes("GEO")
      ),
    [allRecommendations]
  );
  const seoFixes = useMemo(
    () => allRecommendations.filter((fix) => fix.engines?.includes("SEO")),
    [allRecommendations]
  );

  // The headline AIO matches the project overview exactly: the average of the
  // canonical aeo/geo scores, including a real 0 (SIGNAL-1000).
  const aioHeadline = computeAioScore(activeReport);
  const aioDelta = useMemo(() => {
    if (!comparisonData?.has_previous || aioHeadline === null) return undefined;
    const prevParts = [
      comparisonData.scores.aeo?.previous,
      comparisonData.scores.geo?.previous,
    ].filter((v): v is number => typeof v === "number");
    if (prevParts.length === 0) return undefined;
    const previous = Math.round(prevParts.reduce((a, b) => a + b, 0) / prevParts.length);
    const delta = aioHeadline - previous;
    return {
      current: aioHeadline,
      previous,
      delta,
      direction: delta > 0 ? ("up" as const) : delta < 0 ? ("down" as const) : ("stable" as const),
    };
  }, [comparisonData, aioHeadline]);

  // The third figure of the approved results block, AI visibility, is produced
  // by the monitoring worker from the project's tracked prompts, not by this
  // check. It is fetched separately and only rendered when a completed run
  // exists, so the card is never permanently empty.
  useEffect(() => {
    if (!projectId || !isSignedIn) {
      setVisibilitySummary(null);
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const headers = await getAuthHeaders();
        const summary = await fetchVisibilitySummary(projectId, headers);
        if (!cancelled) setVisibilitySummary(summary);
      } catch {
        if (!cancelled) setVisibilitySummary(null);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getAuthHeaders, isSignedIn, projectId]);

  const aiVisibility = useMemo(() => {
    if (!visibilitySummary) return null;
    if (visibilitySummary.entitlements?.is_locked) return null;
    if ((visibilitySummary.completed_checks ?? 0) <= 0) return null;
    const score = visibilitySummary.visibility_score;
    if (typeof score !== "number" || !Number.isFinite(score)) return null;
    return { score, measuredAt: visibilitySummary.last_updated_at ?? null };
  }, [visibilitySummary]);

  if (workspaceHistory.reportLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[70vh] gap-4">
        <Spinner size="lg" />
        <p className="text-sm text-(--text-soft)">Loading audit report...</p>
      </div>
    );
  }

  if (workspaceHistory.reportError) {
    return (
      <div className="flex min-h-[70vh] items-center justify-center px-6">
        <div className="w-full max-w-md rounded-[14px] border-0 bg-[#EEF1F6] p-8 text-center space-y-5">
          <div className="flex items-center justify-center w-12 h-12 mx-auto rounded border-0 bg-(--background)">
            <AlertTriangle className="w-5 h-5 text-amber-500" />
          </div>
          <div className="space-y-2">
            <h2 className="text-lg font-semibold text-(--foreground)">Unable to load report</h2>
            <p className="text-sm text-(--text-soft)">{workspaceHistory.reportError}</p>
          </div>
          <button
            onClick={() => router.push("/dashboard/audit")}
            className={buttonClasses({ variant: "ghost", size: "sm" })}
          >
            Back to audits
          </button>
        </div>
      </div>
    );
  }

  if (!activeReport) {
    return (
      <NotFoundContent
        isAuditNotFound={true}
        title="Audit not found"
        description="We couldn't find the audit you requested. It may have been removed, or you may no longer have access to it."
        primaryLabel="Back to audits"
        primaryHref="/dashboard/audit"
        secondaryLabel="Dashboard overview"
        secondaryHref="/dashboard/overview"
      />
    );
  }

  const aeoPanel = (
    <AeoTab
      aeoScore={aeoScore}
      aeoScoreEntries={aeoScoreEntries}
      aeoEntityClarity={aeoEntityClarity}
      aeoRecommendations={aeoRecommendations}
      contextUrl={activeAuditMeta?.url || activeReport?.url || null}
      entityNames={normalizedEntities.map((entity) => entity.name)}
      getAuthHeaders={getAuthHeaders}
      projectId={projectId}
      auditId={activeAuditMeta?.id}
      lockedSection={getAuditLockedSection(activeReport, "semantic_graph")}
    />
  );
  const geoPanel = (
    <GeoTab
      geoScore={geoScore}
      geoSummary={geoSummary}
      geoTabData={geoTabData}
      geoRecommendations={geoRecommendations}
      contextUrl={activeAuditMeta?.url || activeReport?.url || null}
      entityNames={normalizedEntities.map((entity) => entity.name)}
      getAuthHeaders={getAuthHeaders}
      projectId={projectId}
      auditId={activeAuditMeta?.id}
      isBrandWithoutUrl={isBrandWithoutUrl}
      lockedSection={getAuditLockedSection(activeReport, "brand_integrity")}
    />
  );

  return (
    <div className="dashboard-page-shell space-y-4">
      <ReportHeader
        url={activeReport.url || ""}
        auditId={auditId}
        numericAuditId={numericAuditId}
        auditType={activeAuditMeta?.auditType}
        createdAt={activeAuditMeta?.createdAt}
        overallScore={overallScore}
        overallDelta={comparisonData?.has_previous ? comparisonData.scores.overall : undefined}
        previousAuditDate={comparisonData?.previous_audit_date ?? null}
        scheduleParams={scheduleAuditParams}
        projectId={projectId ?? null}
        onBack={() => router.push("/dashboard/audit")}
      />

      <ScanResults
        aioScore={aioHeadline}
        seoScore={seoScore}
        aioDelta={aioDelta}
        seoDelta={comparisonData?.has_previous ? comparisonData.scores.seo : undefined}
        comparison={comparisonData ?? null}
        previousAuditDate={comparisonData?.previous_audit_date ?? null}
        aiVisibility={aiVisibility}
        /* SIGV2-1164: "Back to dashboard" means this report's own project
           dashboard, not the workspace overview. The id is the audit's served
           project, so the destination keeps its own gating. */
        dashboardHref={projectId ? `/dashboard/projects/${projectId}` : undefined}
      />

      <PrioritizedFixes fixes={allRecommendations} />

      <ReportDisclosure
        title={t("signalAuditReport.scores.detailTitle")}
        description={t("signalAuditReport.scores.detailDescription")}
        anchorId="report-sec-overview"
      >
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
          readOnly={false}
          projectId={projectId}
          comparisonData={comparisonData}
          isBrandWithoutUrl={isBrandWithoutUrl}
          onNavigateToTab={navigateToSection}
          roleMode={roleMode}
          aeoPanel={aeoPanel}
          geoPanel={geoPanel}
          canSeeComparison={canSeeComparison}
          canSeeAdvisor={canSeeAdvisor}
          canSeeExecution={canSeeExecution}
        />
      </ReportDisclosure>

      <AioReportSection fixes={aioFixes}>
        {/* SIGV2-1317: one AIO score, explained once.
            AEO and GEO were two separate sections, which contradicted the
            number printed above them: `computeAioScore` averages the two into
            the single AIO score, so presenting them as unrelated topics asked
            the reader to reconcile arithmetic the page would not show.
            They are the two factors of one score now, on the same approved
            `.st` row anatomy that answers the same question for SEO, so both
            scores are explained the same way and each factor still opens to
            its own full detail. */}
        {shownInMode("aeo", roleMode) || shownInMode("geo", roleMode) ? (
          <ReportDisclosure
            title={t("signalAuditReport.aio.factors")}
            description={t("signalAuditReport.aio.factorsDesc")}
            anchorId="report-sec-aio"
          >
            <div className="-mx-[22px]">
              {shownInMode("aeo", roleMode) ? (
                <ScoreFactorRow
                  group="aio"
                  factor={{
                    id: "answers",
                    title: t("signalAuditReport.aio.answers"),
                    description: t("signalAuditReport.aio.answersDesc"),
                    score: typeof aeoScore === "number" ? aeoScore : null,
                    why: t("signalAuditReport.aio.answersWhy"),
                  }}
                />
              ) : null}
              {shownInMode("geo", roleMode) ? (
                <ScoreFactorRow
                  group="aio"
                  factor={{
                    id: "engines",
                    title: t("signalAuditReport.aio.engines"),
                    description: t("signalAuditReport.aio.enginesDesc"),
                    score: typeof geoScore === "number" ? geoScore : null,
                    why: t("signalAuditReport.aio.enginesWhy"),
                  }}
                />
              ) : null}
            </div>
            {shownInMode("aeo", roleMode) ? (
              <div className="mt-4 border-t border-(--line-2) pt-4" id="report-sec-aeo">
                <TabErrorBoundary sectionName="AI answers analysis">{aeoPanel}</TabErrorBoundary>
              </div>
            ) : null}
            {shownInMode("geo", roleMode) ? (
              <div className="mt-4 border-t border-(--line-2) pt-4" id="report-sec-geo">
                <TabErrorBoundary sectionName="AI visibility analysis">{geoPanel}</TabErrorBoundary>
              </div>
            ) : null}
          </ReportDisclosure>
        ) : null}
        <ReportDisclosure
          title={t("signalAuditReport.aio.compare")}
          description={t("signalAuditReport.aio.compareDesc")}
          anchorId="report-sec-competitors"
        >
          <TabErrorBoundary sectionName="Competitors Analysis">
            <CompetitorsTab
              competitors={Array.isArray(activeReport?.competitors) ? activeReport.competitors : []}
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
        </ReportDisclosure>
        <ReportDisclosure
          title={t("signalAuditReport.aio.brand")}
          description={t("signalAuditReport.aio.brandDesc")}
          anchorId="report-sec-entities"
        >
          <TabErrorBoundary sectionName="Entity Coverage">
            <EntitiesTab
              editableEntities={normalizedEntities.map((e) => ({
                name: e.name,
                type: e.type ?? "Entity",
                confidence: e.relevance,
              }))}
              entityChipSuggestions={[]}
              entitySummary={{
                total: normalizedEntities.length,
                categorized: normalizedEntities.filter((e) => e.type !== "Entity").length,
                avgConfidence: (() => {
                  const scores = normalizedEntities
                    .map((e) => e.relevance)
                    .filter((r): r is number => typeof r === "number");
                  return scores.length > 0
                    ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length)
                    : null;
                })(),
                highConfidence: normalizedEntities.filter(
                  (e) => typeof e.relevance === "number" && e.relevance >= 80
                ).length,
              }}
              readOnly={true}
            />
          </TabErrorBoundary>
        </ReportDisclosure>
        <ReportDisclosure
          title={t("signalAuditReport.aio.accuracy")}
          description={t("signalAuditReport.aio.accuracyDesc")}
          anchorId="report-sec-hallucinations"
        >
          <TabErrorBoundary sectionName="Hallucination Analysis">
            <HallucinationsTab hallucination={activeReport?.hallucination} />
          </TabErrorBoundary>
        </ReportDisclosure>
      </AioReportSection>

      <SeoReportSection fixes={seoFixes}>
        <ReportDisclosure
          title={t("signalAuditReport.seo.factors")}
          description={t("signalAuditReport.seo.factorsDesc")}
          anchorId="report-sec-seo"
        >
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
        </ReportDisclosure>
        {!isBrandWithoutUrl ? (
          <ReportDisclosure
            title={t("signalAuditReport.seo.siteHealth")}
            description={t("signalAuditReport.seo.siteHealthDesc")}
            anchorId="report-sec-technical"
          >
            <TabErrorBoundary sectionName="Technical Core">
              <TechnicalTab
                performance={performance}
                network={network}
                technicalSignals={technicalSignals}
              />
            </TabErrorBoundary>
          </ReportDisclosure>
        ) : null}
      </SeoReportSection>

      {/* SIGV2-1124 removed this section's "Export this report" block: it was
          invented, and the approved Export control now sits in the header.
          What is left is the action-plan link out and the claim review queue.
          The review queue has no approved home anywhere in the MVP design, so
          it stays reachable exactly where it was while that is settled with
          the stakeholder, rather than being deleted or rehoused on a guess.
          With export gone the section can now be genuinely empty, so it is
          only rendered when it has something in it. */}
      {hasActionSectionContent ? (
        <ActionSection>
          {/* The report truncates to the top fixes; the full ranked plan lives
              on the project's action plan page. The approved design routes to
              it from every detail screen with a "Full action plan" control
              (Signal SEO Detail.html, Signal AIO Detail.html), so this block
              links out rather than restating the plan. Needs a project to link
              to: a guest or orphaned audit has no plan page. */}
          {projectId ? (
            <ReportDisclosure
              title={t("signalAuditReport.action.plan")}
              description={t("signalAuditReport.action.planDesc")}
              anchorId="report-sec-plan"
              defaultOpen
            >
              <Link
                href={`/dashboard/projects/${projectId}/fixes`}
                className="inline-flex h-[30px] items-center gap-1.5 rounded-(--r-sm) border-0 bg-white px-[11px] text-[12px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
              >
                {t("signalAuditReport.action.planCta")}
              </Link>
            </ReportDisclosure>
          ) : null}
          {showReviewQueue && numericAuditId ? (
            <ReportDisclosure
              title={t("signalAuditReport.action.reviewQueue")}
              description={t("signalAuditReport.action.reviewQueueDesc", {
                count: reviewQueuePendingCount,
              })}
              anchorId="report-sec-review_queue"
            >
              <TabErrorBoundary sectionName="Review Queue">
                <ClaimReviewQueue
                  auditId={numericAuditId}
                  getAuthHeaders={getAuthHeaders}
                  onSummaryChange={setReviewSummary}
                />
              </TabErrorBoundary>
            </ReportDisclosure>
          ) : null}
        </ActionSection>
      ) : null}
    </div>
  );
}
