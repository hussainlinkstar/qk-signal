"use client";

import SignalAlert from "@/components/signal/SignalAlert";
import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowUpRight, Lock } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useAuth } from "@/components/auth/custom-auth";
import { fetchVisibilitySummary } from "@/services/monitoringService";
import { fetchProjectTrends, type ProjectTrendResponse } from "@/services/workspaceService";
import type { VisibilitySummaryResponse } from "@/types/monitoring";

import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { useScanAllowance } from "@/hooks/useScanAllowance";
import { useSiteTraffic } from "@/hooks/useSiteTraffic";
import SiteTrafficSection from "@/components/dashboard/SiteTrafficSection";
import ScanHistoryCard from "@/components/dashboard/ScanHistoryCard";
import SearchTypeFeeds from "@/components/dashboard/SearchTypeFeeds";
import VisibilityPanels from "@/components/dashboard/VisibilityPanels";
import AiVisibilityReputation from "@/components/dashboard/AiVisibilityReputation";
import { isAuditResult } from "@/types/auditResult";
import { SITE_TRAFFIC_WINDOWS } from "@/types/siteTraffic";
import {
  deriveRecommendations,
  normalizeLatestAuditReport,
  sortRecommendations,
} from "@/lib/deriveRecommendations";
import { getSearchTypes } from "@/lib/reportAdapters";
import { computeAioScore } from "@/lib/aioScore";
import { resolveProjectAuditTarget } from "@/lib/projectAuditFeature";
import { buildScanLaunchHref } from "@/lib/scanLaunch";
import {
  deriveProjectScoreTrends,
  SCORE_TREND_GRANULARITY,
  SCORE_TREND_PERIOD,
} from "@/lib/projectScoreTrend";
import { formatRelativeTime } from "@/lib/dateFormat";
import { resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { SkelCard, SkelChart, SkelPagehead } from "@/components/signal/SignalSkeleton";
import SignalLockCard from "@/components/signal/SignalLockCard";
import ScanAllowanceNote from "@/components/signal/ScanAllowanceNote";
import { LockedFixPreview } from "@/components/signal/SignalLockedPlanPreview";
import { cx } from "@/components/ui/utils";

const roundOrNull = (v: number | null | undefined): number | null =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

// signal-MVP `.dhead` period label per traffic window.
const WINDOW_PERIOD_KEY: Record<string, string> = {
  "7D": "signalOverview.last7days",
  "15D": "signalOverview.last15days",
  "90D": "signalOverview.last90days",
  "12M": "signalOverview.last12months",
};

export default function ProjectOverviewPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const basePath = `/dashboard/projects/${projectId}`;

  const { project, latestAudit, loading, error, refetch } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
  });
  // Hoisted so the approved page header carries the period pills and the
  // "Last N days / tracking" line, while the section below consumes the data.
  const siteTraffic = useSiteTraffic(projectId);
  const scanAllowance = useScanAllowance();
  const { getToken } = useAuth();
  const [visibilitySummary, setVisibilitySummary] = useState<VisibilitySummaryResponse | null>(
    null
  );
  const [scoreTrend, setScoreTrend] = useState<ProjectTrendResponse | null>(null);

  // The "AI visibility & reputation" rows and the AIO card's "Appearance in
  // AI answers" stat both read this summary through the one shared derivation;
  // a null response keeps the explicit unmeasured states.
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const result = await fetchVisibilitySummary(projectId, headers);
        if (!cancelled) setVisibilitySummary(result);
      } catch {
        // Unreachable or refused: the panel keeps its unmeasured reasons.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, projectId]);

  // SIGV2-1181: the progressive change under each gauge is this project's own
  // score history, read from the same backend trend payload (90 days, weekly
  // buckets) that the workspace overview's project card already draws, so the
  // two surfaces cannot report different movements for the same project. No
  // history, no figures: the panel then renders neither a delta nor a spark.
  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const headers = token ? { Authorization: `Bearer ${token}` } : {};
        const result = await fetchProjectTrends(projectId, headers, {
          period: SCORE_TREND_PERIOD,
          granularity: SCORE_TREND_GRANULARITY,
        });
        if (!cancelled) setScoreTrend(result);
      } catch {
        // Unreachable or refused: the gauges keep the score with no trend.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [getToken, projectId]);

  const scoreTrends = useMemo(() => deriveProjectScoreTrends(scoreTrend), [scoreTrend]);

  const latestReport = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? raw : null;
  }, [latestAudit?.full_report]);

  const seoScore = useMemo(() => {
    // Canonical score first, same fix as the AIO tab (aeo/page.tsx): averaging
    // raw sub-fields here produced a different number than the real seo/aeo
    // detail tabs for the same audit (SIGNAL-1000).
    const canonical = roundOrNull(latestReport?.scores?.seo ?? project?.latest_seo_score);
    if (canonical !== null) return canonical;
    const seo = latestReport?.seo;
    const parts = [seo?.onpage, seo?.performance, seo?.indexing].filter(
      (v): v is number => typeof v === "number"
    );
    if (parts.length > 0) return Math.round(parts.reduce((a, b) => a + b, 0) / parts.length);
    return null;
  }, [latestReport?.scores?.seo, latestReport?.seo, project?.latest_seo_score]);

  const aioScore = useMemo(
    () =>
      computeAioScore(latestReport, {
        aeo: project?.latest_aeo_score,
        geo: project?.latest_geo_score,
      }),
    [latestReport, project?.latest_aeo_score, project?.latest_geo_score]
  );

  const fixes = useMemo(
    () => sortRecommendations(deriveRecommendations(latestAudit)).slice(0, 3),
    [latestAudit]
  );
  const searchTypes = useMemo(() => {
    const report = normalizeLatestAuditReport(latestAudit);
    return report ? getSearchTypes(report) : [];
  }, [latestAudit]);
  const hasScores = seoScore !== null || aioScore !== null;

  // SIGV2-1184: Rescan has to re-run *this* project's scan, so the target
  // travels with it. It was a bare link to the workspace start-scan form
  // (`?projectId=42&tab=overview`), which named no target and carried no
  // authority to start: the customer arrived at an empty - or worse, a
  // restored draft for some other site - setup form and nothing ran. The
  // target is the one the last audit actually used, falling back to the
  // project's own domain before there is an audit to repeat.
  const rescanTarget = useMemo(() => {
    const resolved = resolveProjectAuditTarget(latestAudit, latestReport);
    // `resolveProjectAuditTarget` falls back to the address when the audit
    // carries no label, and the form field this prefills is "Name on the
    // report", so an address is not a name: the project's own name is used
    // instead.
    const label = resolved.label && resolved.label !== resolved.url ? resolved.label : "";
    return {
      url: resolved.url || project?.domain_url || "",
      name: label || project?.name || "",
      targetType: resolved.type,
    };
  }, [latestAudit, latestReport, project?.domain_url, project?.name]);
  // SIGV2-1256: Rescan prefills the setup form and stops there. It used to
  // also record a launch intent (`authorizeScanLaunch`) in this tab's
  // sessionStorage, which the audit page's auto-start effect then acted on, so
  // a single click went straight to a running scan: no chance to change the
  // search types, the depth or the prompts, and an accidental click spent one
  // of the plan's scans. That auto-start belongs to the onboarding's "Run my
  // first scan" (SIGV2-1159), where the wizard has already collected the
  // configuration; a rescan has collected nothing. The href grants nothing,
  // which is why it is safe to compute while rendering.
  const auditHref = useMemo(
    () => buildScanLaunchHref(projectId, rescanTarget, { tab: "overview" }),
    [projectId, rescanTarget]
  );

  // The header's "tracking up/down" trend comes from the traffic window's own
  // sessions delta; without a payload the header shows the period only.
  const trafficTrend = useMemo(() => {
    const tr = siteTraffic.traffic;
    if (!tr || tr.status !== "ok") return null;
    const v = tr.overview?.changes?.sessions?.value;
    return typeof v === "number" ? v : null;
  }, [siteTraffic.traffic]);

  // SIGV2-1134: the preview of the action plan is the action plan, so it is
  // gated on the served `advisor_recommendations` entitlement the plan page
  // itself uses. It used to read the project's workflow-automation feature
  // access instead, a different capability granted from Specialist up, which
  // told a Standard customer who already owns the plan to upgrade before they
  // could preview it.
  const advisorPlan = resolveAdvisorPlanAccess(project);
  const canAction = advisorPlan.allowed;

  if (loading) {
    return (
      <div role="status" aria-label={t("signalOverview.loading")} className="flex flex-col gap-5">
        <SkelPagehead />
        <SkelChart className="h-[220px]" />
        <SkelCard />
      </div>
    );
  }
  if (error) {
    return (
      <div>
        <SignalAlert tone="danger" title={t("alerts.errorTitle")}>
          {error}
        </SignalAlert>
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] mt-3 leading-[normal] max-md:min-h-11"
          onClick={() => void refetch()}
        >
          {t("common.tryAgain")}
        </button>
      </div>
    );
  }

  return (
    <div data-project-overview className="flex min-w-0 flex-col gap-[22px] leading-[normal]">
      {/* ── Page header (.dhead): title, period line, window pills,
            rescan with the real last-audit timestamp ─────────────── */}
      <header className="flex flex-wrap items-end gap-4">
        <div>
          <h1 className="m-0 font-(family-name:--disp) text-[24px] font-extrabold leading-[normal] tracking-[-0.02em]">
            {t("signalOverview.title")}
          </h1>
          <div className="mt-1 text-[13px] text-(--t-2)">
            {t(WINDOW_PERIOD_KEY[siteTraffic.window] ?? "signalOverview.last7days")}{" "}
            {trafficTrend !== null ? (
              <b
                className={cx("font-semibold", trafficTrend > 0 ? "text-(--good)" : "text-(--bad)")}
              >
                {trafficTrend > 0 ? "▲" : "▼"}{" "}
                {t(trafficTrend > 0 ? "signalOverview.trackingUp" : "signalOverview.trackingDown")}
              </b>
            ) : null}{" "}
            {t("signalOverview.vsPrevious")}
          </div>
        </div>
        <div className="flex-1" />
        {/* Soft segmented control driving the GA4 window */}
        <div className="inline-flex gap-0.5 rounded-[12px] bg-[#EEF1F6] p-[3px]" role="group">
          {SITE_TRAFFIC_WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => siteTraffic.setWindow(w)}
              aria-pressed={siteTraffic.window === w}
              className={cx(
                "cursor-pointer rounded-[9px]! border-none px-[11px] py-1.5 font-mono text-[12px] font-semibold leading-[normal] transition-colors",
                siteTraffic.window === w
                  ? "bg-[#E8F1FF] text-[#1D4ED8]"
                  : "bg-transparent text-(--t-3) hover:text-(--t-1)"
              )}
            >
              {w}
            </button>
          ))}
        </div>
        {/* The allowance note must not move the button. Stacking them in a
            column centres the pair as one block, which lifted the control 20px
            above the period pills; the approved header has them on one centre
            line, 2px apart. From md up the note is taken out of flow and hangs
            under the button, so the row keeps the approved geometry. Below md
            the header already wraps, so it stays in flow there. */}
        <div className="relative flex items-center max-md:flex-col max-md:items-start max-md:gap-1">
          <Link
            href={auditHref}
            className="inline-flex h-[38px] cursor-pointer items-center gap-1.5 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white leading-[normal] hover:bg-black max-md:min-h-11"
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              aria-hidden="true"
            >
              <path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" />
            </svg>
            {project?.last_audit_at ? (
              <>
                {t("signalOverview.rescan")}
                <span className="text-[11.5px] font-normal opacity-75">
                  ({formatRelativeTime(project.last_audit_at)})
                </span>
              </>
            ) : (
              t("signalOverview.firstScan")
            )}
          </Link>
          {/* SIGV2-1094: the rescan offer must state the plan's scan allowance
              - scans on the plan, never credits. The window is the backend's
              rolling 30 days, not a calendar month (SIGV2-1135). Renders
              nothing until the figures are known. */}
          <span className="whitespace-nowrap md:absolute md:end-0 md:top-full md:mt-1">
            <ScanAllowanceNote
              used={scanAllowance?.used ?? null}
              remaining={scanAllowance?.remaining}
              resetAt={scanAllowance?.resetAt ?? null}
            />
          </span>
        </div>
      </header>

      {/* ── Traffic & conversions (GA4) ─────────────────────── */}
      <SiteTrafficSection state={siteTraffic} projectId={projectId} />

      {/* ── Why AI recommends / ignores your website ────────── */}
      <SearchTypeFeeds searchTypes={searchTypes} />

      {/* ── Your website visibility (.scores .spanel) ───────── */}
      <VisibilityPanels
        aioScore={aioScore}
        seoScore={seoScore}
        aioTarget={project?.score_targets?.aio.target ?? null}
        seoTarget={project?.score_targets?.seo.target ?? null}
        aioTrend={scoreTrends.aio}
        seoTrend={scoreTrends.seo}
        aioHref={`${basePath}/ai-answers`}
        seoHref={`${basePath}/google`}
        promptsHref={`${basePath}/ai-answers?tab=prompts`}
        summary={visibilitySummary}
      />

      {/* ── AI visibility & reputation ──────────────────────── */}
      <AiVisibilityReputation
        aioScore={aioScore}
        opportunity={canAction ? (fixes[0]?.title ?? null) : null}
        summary={visibilitySummary}
      />
      {/* ── Prioritised fixes ───────────────────────────────── */}
      <section aria-labelledby="overview-actions-title">
        <div className="mb-0.5 flex items-center gap-3 max-md:min-w-0 max-md:flex-wrap max-md:items-start">
          <h2
            id="overview-actions-title"
            className="m-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em] max-md:min-w-0 max-md:whitespace-normal"
          >
            {t("signalOverview.actionsTitle")}
          </h2>
          <span className="h-4 w-px flex-none bg-(--line-2)" />
          <div className="flex-1" />
          {canAction && fixes.length > 0 ? (
            <Link
              className="inline-flex min-h-11 items-center gap-[5px] pt-3 text-[12.5px] font-semibold text-(--blue) focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-(--purple)"
              href={`${basePath}/fixes`}
            >
              {t("signalOverview.allActions")}
              <ArrowUpRight size={16} aria-hidden="true" />
            </Link>
          ) : null}
          {fixes.length > 0 ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-(--bad-s) px-2.5 py-1 font-mono text-[10.5px] text-(--bad)">
              <Lock size={12} strokeWidth={2} aria-hidden="true" />
              {t("signalOverview.needsWork")}
            </span>
          ) : null}
        </div>
        <p className="mt-2 text-[14px] leading-[1.5] text-(--t-2) wrap-anywhere">
          {t("signalOverview.actionsIntro")}
        </p>
        {/* signal-MVP wraps this list in .lockwrap.locked with a .lockgate. The
            AIO and SEO pages already gate the same action plan behind Pro. */}
        <div className={cx("relative mt-3.5", !canAction && "grid")}>
          <div
            className={cx(
              !canAction && "col-start-1 row-start-1 pointer-events-none select-none blur-[6px]"
            )}
            aria-hidden={!canAction || undefined}
          >
            <div className="rounded-[22px] border-0 bg-white">
              {!canAction ? (
                // Blur is presentation, not authorization: gated fix titles
                // must not sit in the DOM, so the blurred layer renders the
                // approved .fix row anatomy with generic illustrative copy,
                // never this project's recommendations.
                <LockedFixPreview />
              ) : fixes.length > 0 ? (
                fixes.map((fix, index) => (
                  <div
                    className="grid grid-cols-1 border-t border-t-(--line-2) px-[22px] py-4 first-of-type:border-t-0 lg:grid-cols-[1fr_340px]"
                    key={`${fix.title}-${index}`}
                  >
                    <div className="flex items-start gap-[18px]">
                      <div className="w-[34px] flex-none font-(family-name:--disp) text-[26px] font-normal leading-[1.1] text-(--fix-num)">
                        {String(index + 1).padStart(2, "0")}
                      </div>
                      <div className="min-w-0 flex-1 wrap-anywhere">
                        <h3 className="m-0 font-(family-name:--disp) text-[14.5px] font-bold tracking-[-0.01em]">
                          {fix.title}
                        </h3>
                        {fix.description ? (
                          <p className="mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
                            {fix.description}
                          </p>
                        ) : null}
                        <div className="mt-[9px] flex items-center gap-2 max-md:flex-wrap">
                          {/* Categorical impact only: numeric point predictions
                              like the mock's "+14 est. AIO" are roadmap
                              SIGV2-1007 and are not rendered. */}
                          <span
                            className={cx(
                              "rounded-[6px] px-2 py-[3px] font-mono text-[10.5px] uppercase tracking-[0.04em]",
                              fix.impact === "Critical"
                                ? "bg-(--bad-s) text-(--bad)"
                                : fix.impact === "Strategic"
                                  ? "bg-(--warn-s) text-(--warn)"
                                  : "bg-(--line-2) text-(--t-2)"
                            )}
                          >
                            {t(
                              fix.impact === "Critical"
                                ? "signalOverview.impactHigh"
                                : fix.impact === "Strategic"
                                  ? "signalOverview.impactMedium"
                                  : "signalOverview.impactLow"
                            )}
                          </span>
                          {fix.category ? (
                            <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] font-mono text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
                              {fix.category}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                    {/* .fix-right: advisor action plan entry, links to the real
                        fixes surface */}
                    <div className="relative ml-6 flex flex-col justify-center rounded-[14px] bg-[#F6F8FB] px-[18px] py-3.5 max-lg:mt-3">
                      <span className="absolute left-[18px] top-4 text-(--purple-deep)">
                        <Lock size={18} strokeWidth={2} aria-hidden="true" />
                      </span>
                      <h4 className="m-0 pl-7 font-(family-name:--disp) text-[13px] font-bold tracking-[-0.01em]">
                        {t("signalOverview.advisorPlan")}
                      </h4>
                      <p className="m-0 mt-1 pl-7 text-[12px] leading-[1.45] text-(--t-2)">
                        {t("signalOverview.advisorPlanDesc")}
                      </p>
                      <Link
                        className="mt-2 inline-flex items-center gap-[5px] pl-7 text-[12.5px] font-semibold text-(--brand) hover:underline max-md:min-h-11"
                        href={`${basePath}/fixes`}
                      >
                        {t("signalOverview.advisorPlanLink")} →
                      </Link>
                    </div>
                  </div>
                ))
              ) : (
                <div className="flex flex-col items-center gap-3 rounded-2xl bg-(--panel) px-6 py-[22px] text-center text-[13px] text-(--t-2)">
                  <span>
                    {t(hasScores ? "signalOverview.noActions" : "signalOverview.actionsEmpty")}
                  </span>
                </div>
              )}
            </div>
          </div>
          {/* SIGV2-1305: an upsell needs a positive refusal, not silence.
              `allowed` is false both for a plan that excludes this and for a
              payload that never said. Only the first justifies asking a
              customer to pay, and QA caught a Standard customer being asked to
              upgrade for the action plan their plan grants.
              The blur above is unchanged: gated content stays protected when
              the entitlement is unknown, which is the fail-safe direction.
              What goes is the demand for money on no evidence. */}
          {!canAction && advisorPlan.resolved ? (
            <div className="relative z-10 col-start-1 row-start-1 flex items-center justify-center p-4">
              {/* The plan named here, and the plan the CTA links to, come from
                  the same served entitlement as the gate itself, so the lock
                  can never advertise a plan the backend does not require. */}
              <SignalLockCard
                eyebrow={advisorPlan.requiredPlan ?? t("signalOverview.unlockEyebrow")}
                title={t("signalOverview.unlockActions")}
                body={t("signalOverview.unlockDescription")}
                ctaLabel={
                  advisorPlan.requiredPlan
                    ? t("signalOverview.upgradeToPlan", { plan: advisorPlan.requiredPlan })
                    : t("signalOverview.upgradePlan")
                }
                ctaHref={advisorPlan.upgradeHref}
              />
            </div>
          ) : null}
        </div>
      </section>

      {/* ── Scan history & PDFs (.scan-history) ─────────────── */}
      <ScanHistoryCard projectId={projectId} projectName={project?.name} />
    </div>
  );
}
