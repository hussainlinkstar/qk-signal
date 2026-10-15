"use client";

// Rebuilt 1:1 with /Users/user/signal-MVP/Signal AIO Detail.html: breadcrumb
// top bar, hero ring, and the approved four tabs (Improve, Search types,
// By engine, Prompts). Wired to real audit data (useProjectLatestAudit) and
// the visibility summary feed; anything the feeds do not produce is rendered
// as an explicit unmeasured state rather than a plausible number.
import SignalAlert from "@/components/signal/SignalAlert";
import React, { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useTranslation } from "react-i18next";
import { SkelCard, SkelPagehead } from "@/components/signal/SignalSkeleton";
import SignalLockCard from "@/components/signal/SignalLockCard";
import { LockedActPreview } from "@/components/signal/SignalLockedPlanPreview";

import { useAuth } from "@/components/auth/custom-auth";
import { useProjectLatestAudit } from "@/hooks/useProjectLatestAudit";
import { useSignalEntrance } from "@/hooks/useSignalChartMotion";
import { isAuditResult } from "@/types/auditResult";
import {
  deriveRecommendations,
  normalizeLatestAuditReport,
  sortRecommendations,
} from "@/lib/deriveRecommendations";
import {
  getSearchTypes,
  isMeasuredSearchType,
  type FixSource,
  type ResolvedLevel,
  type SearchType,
} from "@/lib/reportAdapters";
import { fixSourceLabelKeys } from "@/lib/fixSource";
import { resolveAdvisorPlanAccess } from "@/lib/advisorPlanAccess";
import { provenanceByProvider } from "@/lib/visibilityProvenance";
import { cx } from "@/components/ui/utils";
import { fetchVisibilitySummary } from "@/services/monitoringService";
import PromptSetup from "@/components/signal/PromptSetup";
import { useScanPrompts } from "@/hooks/useScanPrompts";
import SignalCrumb from "@/components/signal/SignalCrumb";
import SignalExportMenu from "@/components/signal/SignalExportMenu";
import SignalTabs from "@/components/signal/SignalTabs";
import SignalScoreRing from "@/components/signal/SignalScoreRing";
import { useWorkspacePageHeader } from "@/components/dashboard/workspacePageHeader";
import type { VisibilityProviderBreakdown, VisibilitySummaryResponse } from "@/types/monitoring";
import {
  VISIBILITY_PROVIDER_LABELS,
  isMeasuredVisibilityProvider,
  measuredVisibilityProviders,
} from "@/components/dashboard/visibilityUtils";

const roundOrNull = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? Math.round(v) : null;

const scoreColor = (n: number): string =>
  n >= 70 ? "var(--good)" : n >= 50 ? "var(--warn)" : "var(--bad)";

type TabId = "improve" | "types" | "engines" | "prompts";
const TABS: TabId[] = ["improve", "types", "engines", "prompts"];

const sectionHeaderCls =
  "m-0 font-(family-name:--disp) text-[15px] font-extrabold tracking-[-0.02em] text-[#111827]";
const miniCls =
  "whitespace-nowrap text-[12px] font-medium text-(--t-3) max-md:w-full max-md:whitespace-normal";
const unmeasuredCls = "text-[11px] font-medium text-(--t-3)";
const emptyCls =
  "mt-3.5 flex flex-col items-center gap-3 rounded-[22px] border-0 bg-white px-6 py-[22px] text-center text-[13px] text-(--t-2)";
const btnCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3] disabled:cursor-not-allowed disabled:opacity-50";
const btnPrimaryCls =
  "inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black";
const chipCls =
  "rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-[0.04em]";

/** signal-MVP `.sec`: heading, `.ln` divider, `.mini`, spacer, action. */
function Sec({ title, mini, action }: { title: string; mini?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-3.5 flex items-center gap-3 max-md:min-w-0 max-md:flex-wrap max-md:items-start">
      <h2 className={sectionHeaderCls}>{title}</h2>
      <span className="h-4 w-px flex-none bg-(--line-2)" />
      {mini ? <span className={miniCls}>{mini}</span> : null}
      <div className="flex-1" />
      {action}
    </div>
  );
}

export default function ProjectAioDetailPage() {
  const { t } = useTranslation();
  const params = useParams<{ projectId: string }>();
  const projectId = params?.projectId ?? "";
  const numericProjectId = Number(projectId);
  const base = `/dashboard/projects/${projectId}`;
  const deeperAuditHref = `/dashboard/audit?projectId=${projectId}&tier=smart&tab=overview`;
  const [activeTab, setActiveTab] = useState<TabId>("improve");
  const [open, setOpen] = useState<number | null>(null);
  // SIGV2-1194: the Prompts tab is the manage mode of the approved
  // prompt-setup surface; its own add/edit/remove live inside it.

  // `?tab=` makes a single tab linkable from elsewhere in the product; the
  // overview's "Appearance in AI answers" explanation sends people straight to
  // Prompts, the surface that actually drives that figure (SIGV2-1111). Same
  // contract as AuditWorkspace: an unknown value is ignored, not fatal.
  const searchParams = useSearchParams();
  const requestedTab = searchParams?.get("tab") ?? null;
  useEffect(() => {
    if (requestedTab && (TABS as readonly string[]).includes(requestedTab)) {
      setActiveTab(requestedTab as TabId);
    }
  }, [requestedTab]);

  const { project, latestAudit, loading, error, refetch } = useProjectLatestAudit(projectId, {
    includeFullReport: true,
  });

  const { getToken, isSignedIn } = useAuth();

  // ------------------------------------------------------------------
  // Visibility summary: the only feed that carries per-prompt and
  // per-engine visibility results (plan-gated monitoring data).
  // ------------------------------------------------------------------
  const [summary, setSummary] = useState<VisibilitySummaryResponse | null>(null);
  const [summaryFailed, setSummaryFailed] = useState(false);

  const loadSummary = useCallback(async () => {
    if (!projectId || !isSignedIn) return;
    try {
      const token = await getToken();
      const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
      setSummary(await fetchVisibilitySummary(projectId, headers));
      setSummaryFailed(false);
    } catch {
      // A missing or refused feed must not take down the score page; both
      // tabs that read it show their own explicit unavailable state.
      setSummary(null);
      setSummaryFailed(true);
    }
  }, [getToken, isSignedIn, projectId]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const promptAuthHeaders = useCallback(async (): Promise<Record<string, string>> => {
    const token = await getToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }, [getToken]);

  // The Prompts tab reads the same live project list as scan setup
  // (SIGV2-1194), so the two surfaces can never disagree.
  const promptSetupState = useScanPrompts({
    projectId: Number.isFinite(numericProjectId) ? numericProjectId : undefined,
    isSignedIn: Boolean(isSignedIn),
    getAuthHeaders: promptAuthHeaders,
  });

  const report = useMemo(() => {
    const raw = latestAudit?.full_report;
    return isAuditResult(raw) ? (raw as Record<string, any>) : null;
  }, [latestAudit?.full_report]);

  const score = useMemo(() => {
    const aeo = roundOrNull(
      report?.scores?.aeo ?? project?.latest_aeo_score ?? report?.aeo?.answerability_score
    );
    const geo = roundOrNull(
      report?.scores?.geo ?? project?.latest_geo_score ?? report?.geo?.visibility_index
    );
    const parts = [aeo, geo].filter((v): v is number => typeof v === "number");
    if (parts.length === 0) return null;
    return Math.round(parts.reduce((a, b) => a + b, 0) / parts.length);
  }, [report, project?.latest_aeo_score, project?.latest_geo_score]);

  const heroEntranceRef = useSignalEntrance(
    `hero:${loading ? "loading" : "ready"}:${score ?? "-"}`
  );

  const searchTypes = useMemo<SearchType[]>(() => {
    const canonical = normalizeLatestAuditReport(latestAudit);
    if (canonical) return getSearchTypes(canonical);
    const raw = report?.metadata?.search_types;
    return Array.isArray(raw) ? getSearchTypes({ metadata: { search_types: raw } } as any) : [];
  }, [latestAudit, report]);

  // Recommendation titles are gated content: count them to decide whether the
  // improve panel exists, but only materialise the rows when the plan allows
  // the action plan (see the lockgate below).
  const improveCount = useMemo(() => {
    return deriveRecommendations(latestAudit).filter(
      (r) => r.engines.includes("AEO") || r.engines.includes("GEO")
    ).length;
  }, [latestAudit]);
  const advisorPlan = resolveAdvisorPlanAccess(project);
  // SIGV2-1211: impact is categorical by product rule, and the band is
  // resolved once on the consolidated row (SIGV2-1193), shared with the full
  // action plan, so a fix cannot be rated here and unrated there. A row the
  // audit attached no number to stays unrated rather than defaulting to
  // Medium. The numeric deduction never reaches the row: it measures what the
  // problem costs today, not what fixing it would recover.
  const improve = useMemo(() => {
    if (!advisorPlan.allowed)
      return [] as {
        title: string;
        action: string;
        category: string;
        impact: ResolvedLevel;
        sources: FixSource[];
      }[];
    return sortRecommendations(deriveRecommendations(latestAudit))
      .filter((r) => r.engines.includes("AEO") || r.engines.includes("GEO"))
      .slice(0, 4)
      .map((r) => ({
        title: r.title,
        action: r.description,
        category: r.category,
        // SIGV2-1193: the band is resolved once, on the consolidated row, so
        // this list and the action plan cannot rate the same fix differently.
        impact: r.impactLevel,
        sources: r.sources,
      }));
  }, [latestAudit, advisorPlan.allowed]);

  const hasScore = score !== null;
  // The action plan is a Pro feature (agents action each fix). Gate it off real
  // feature access rather than a demo toggle.

  // ------------------------------------------------------------------
  // Export: the approved `.exp-menu` control (SIGV2-1124). The four PDF
  // variants, their locks and the job panel all live in SignalExportMenu;
  // this page only says which screen it is and what audit to build from.
  // ------------------------------------------------------------------
  const auditId = typeof latestAudit?.id === "number" ? latestAudit.id : null;

  // Approved `.top`: crumb + actions live inside the shared SignalTopBar
  // (registered via the page-header context), never a second row under it.
  const { setHeader } = useWorkspacePageHeader();
  const topCrumb = useMemo(
    () => (
      <SignalCrumb
        items={[
          { label: t("signalAioDetail.crumbHome"), href: base },
          { label: t("signalAioDetail.crumbCurrent") },
        ]}
      />
    ),
    [t, base]
  );
  const topActions = useMemo(
    () => (
      <>
        <SignalExportMenu
          page="aio"
          reportKind="aio"
          auditId={auditId}
          projectId={Number.isFinite(numericProjectId) ? numericProjectId : null}
        />
        <Link href={`${base}/settings`} className={btnPrimaryCls}>
          {t("signalAioDetail.improveSettings")}
        </Link>
      </>
    ),
    [auditId, numericProjectId, t, base]
  );
  useEffect(() => {
    setHeader({ crumb: topCrumb, actions: topActions });
    return () => setHeader(null);
  }, [setHeader, topCrumb, topActions]);

  if (loading) {
    return (
      <div role="status" aria-label="Loading your AI check" className="flex flex-col gap-5">
        <SkelPagehead />
        <SkelCard className="h-[186px]" />
        <SkelCard />
      </div>
    );
  }
  if (error) {
    return (
      <div className="min-w-0">
        <SignalAlert tone="danger" title={t("alerts.errorTitle")}>
          {error}
        </SignalAlert>
        <button type="button" className={`${btnCls} mt-3 min-h-11`} onClick={() => void refetch()}>
          {t("common.tryAgain")}
        </button>
      </div>
    );
  }

  // SIGV2-1215: a withdrawn engine is neither counted nor listed here. A
  // project that selected Copilot while it was offered can still have a
  // breakdown row for it, and this tab is the per-engine surface.
  // SIGV2-1216: nor is an engine this plan has stopped measuring. The count
  // on the tab is a claim about how many engines we measure, so it has to
  // come off the plan's roster rather than off the stored prompt rows.
  const planProviders = summary?.entitlements?.allowed_providers;
  const engineRows = (summary?.provider_breakdown ?? []).filter((row) =>
    isMeasuredVisibilityProvider(row.provider, planProviders)
  );
  const engineCount = engineRows.length
    ? engineRows.length
    : measuredVisibilityProviders(summary?.providers, planProviders).length;
  // SIGV2-1299: the row's label names a consumer engine, so the row also has
  // to say when the answer behind it did not come from that engine.
  const engineSources = summary ? provenanceByProvider(summary) : {};

  const tabCounts: Record<TabId, number> = {
    improve: improveCount,
    types: searchTypes.length,
    engines: engineCount,
    prompts: summary?.queries?.length ?? 0,
  };
  const tabLabels: Record<TabId, string> = {
    improve: t("signalAioDetail.tabImprove"),
    types: t("signalAioDetail.tabTypes"),
    engines: t("signalAioDetail.tabEngines"),
    prompts: t("signalAioDetail.tabPrompts"),
  };

  const summaryLocked = summary?.entitlements?.is_locked === true;
  const visibilityUnavailableReason = summaryFailed
    ? t("signalAioDetail.feedFailed")
    : summaryLocked
      ? t("signalAioDetail.enginesLocked")
      : null;

  return (
    // SIGV2-1036: the approved page's own <style> overrides the shared
    // `.wrap{padding:20px 32px 14px}` to `26px 32px 52px`, and the dashboard
    // shell supplies the shared value, so the built body sits 4px above the
    // approved frame in English. Adding the 6px/38px difference here was
    // measured and reverted: the extra 38px at the bottom pushed this page's
    // Arabic Search-types panel past the shell's min-height, growing the
    // document from 915px to 930px against a 900px approved page and taking
    // aio-detail-tab-types ar from 16.85% to 20.78%, over its budget. The
    // 6px at the top only helps English, because the Arabic hero is 165px in
    // the approved page against 196px here (longer Arabic strings), so the
    // Arabic body already sits below the frame.
    <div className="flex min-w-0 flex-col gap-[22px]">
      <div ref={heroEntranceRef} className="flex flex-col gap-[22px]">
        {/* Hero */}
        <div className="relative flex items-center gap-[26px] overflow-hidden rounded-[22px] border-0 bg-white px-7 py-6 max-md:flex-col max-md:items-stretch max-md:p-5">
          <SignalScoreRing
            score={score}
            size={140}
            color="#3B82F6"
            className="max-md:self-center"
            emptyLabel={
              <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                {t("signalOverview.notMeasured")}
              </span>
            }
          />
          <div className="min-w-0 flex-1">
            <span className="inline-flex rounded-full bg-[#E8F1FF] px-2.5 py-0.5 text-[11px] font-semibold text-[#1D4ED8]">
              {t("signalAioDetail.eyebrow")}
            </span>
            <h1 className="mt-2.5 mb-1.5 font-(family-name:--disp) text-[28px] font-extrabold tracking-[-0.02em] text-[#111827]">
              {t("signalAioDetail.heroTitle")}
            </h1>
            <p className="m-0 max-w-[560px] text-[14px] leading-[1.5] text-(--t-2)">
              {t("signalAioDetail.heroCopy")}
            </p>
          </div>
          <div className="w-[250px] flex-none rounded-[16px] border-0 bg-[#F8FAFC] px-[18px] py-4 max-md:w-full">
            <div className="text-[10.5px] font-semibold uppercase tracking-[0.06em] text-(--t-3)">
              {t("signalAioDetail.currentScore")}
            </div>
            <div className="mt-2 mb-1 flex items-baseline gap-2">
              <span className="font-(family-name:--disp) text-[30px] font-extrabold tracking-[-0.02em] text-[#111827]">
                {score === null ? (
                  <span className="font-(family-name:--body-font) text-[12px] font-semibold tracking-normal text-(--t-3)">
                    {t("signalOverview.notMeasured")}
                  </span>
                ) : (
                  score
                )}
              </span>
            </div>
            <div className="text-[12.5px] text-(--t-2)">
              {project?.score_targets?.aio == null
                ? t("signalAioDetail.noTargets")
                : project.score_targets.aio.gap === null
                  ? t("signalAioDetail.targetUnmeasured", {
                      target: project.score_targets.aio.target,
                    })
                  : project.score_targets.aio.gap === 0
                    ? t("signalAioDetail.atTarget", {
                        target: project.score_targets.aio.target,
                      })
                    : t("signalAioDetail.targetLine", {
                        target: project.score_targets.aio.target,
                        gap: Math.round(project.score_targets.aio.gap),
                      })}
            </div>
          </div>
        </div>

        {/* signal-MVP `.tabs`: the approved underline row via SignalTabs. */}
        <SignalTabs
          tabs={TABS.map((tab) => ({ id: tab, label: tabLabels[tab], count: tabCounts[tab] }))}
          activeId={activeTab}
          onChange={(id) => setActiveTab(id as TabId)}
        />

        {/* IMPROVE */}
        <div
          role="tabpanel"
          id="signal-tabpanel-improve"
          aria-labelledby="signal-tab-improve"
          hidden={activeTab !== "improve"}
        >
          {/* SIGV2-1175: this list and the action plan read disjoint data
              sets (audit findings vs Advisor recommendations), so each names
              its own source and count, and the link names where it actually
              goes rather than implying an expanded version of this list. */}
          <Sec
            title={t("signalAioDetail.improveTitle")}
            mini={
              advisorPlan.allowed
                ? t("signalAioDetail.improveMini", {
                    shown: improve.length,
                    total: improveCount,
                  })
                : t("signalAioDetail.improveMiniLocked", { total: improveCount })
            }
            action={
              <Link
                href={`${base}/fixes`}
                className="inline-flex h-[34px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-3.5 font-(family-name:--body-font) text-[12px] font-semibold text-[#111827] hover:bg-[#E8ECF3]"
              >
                {t("signalAioDetail.advisorActionPlan")}
              </Link>
            }
          />
          {improveCount > 0 ? (
            <div className={cx("relative", !advisorPlan.allowed && "grid")}>
              <div
                className={cx(
                  !advisorPlan.allowed &&
                    "col-start-1 row-start-1 pointer-events-none select-none blur-[6px]"
                )}
                aria-hidden={!advisorPlan.allowed || undefined}
              >
                <div className="rounded-[22px] border-0 bg-white">
                  {!advisorPlan.allowed ? (
                    // Blur is presentation, not authorization: gated rows
                    // must not sit in the DOM, so render the approved .act
                    // anatomy with generic illustrative copy, never the
                    // customer's recommendations.
                    <LockedActPreview accent="purple" />
                  ) : (
                    improve.map((a) => (
                      <div
                        className="flex items-center gap-4 border-t border-t-[#F3F4F6] px-[22px] py-[18px] first:border-t-0"
                        key={a.title}
                      >
                        {/* Leading column kept for approved row anatomy
                            (SIGV2-1211); the +N PTS figure is gone. */}
                        <div
                          className="flex h-10 w-10 flex-none items-center justify-center rounded-[12px] bg-[#F5F3FF] text-[#7C3AED]"
                          aria-hidden="true"
                        >
                          <svg
                            width="16"
                            height="16"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                          >
                            <path d="M12 3l2.1 6.4L20.5 11l-6.4 2.1L12 19.5l-2.1-6.4L3.5 11l6.4-1.6z" />
                          </svg>
                        </div>
                        <div className="min-w-0 flex-1">
                          <h3 className="m-0 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em] text-[#111827]">
                            {a.title}
                          </h3>
                          {a.action ? (
                            <p className="mt-[5px] text-[13px] leading-[1.5] text-(--t-2)">
                              {a.action}
                            </p>
                          ) : null}
                          <div className="mt-[9px] flex flex-wrap items-center gap-1.5">
                            <span className={`${chipCls} bg-[#F5F3FF] text-[#7C3AED]`}>
                              {a.category}
                            </span>
                            {/* SIGV2-1193: one consolidated list, so each row
                                says which channel raised it rather than the
                                list as a whole naming one source. */}
                            {fixSourceLabelKeys(a.sources).map((key) => (
                              <span key={key} className={`${chipCls} bg-[#EEF1F6] text-(--t-3)`}>
                                {t(key)}
                              </span>
                            ))}
                            {a.impact.measured ? (
                              <span className={`${chipCls} bg-[#EEF1F6] text-(--t-2)`}>
                                {t("signalFixes.plan.impactRated", {
                                  level: t(`signalFixes.plan.level.${a.impact.level}`),
                                })}
                              </span>
                            ) : (
                              <span
                                className={`${chipCls} bg-[#F8FAFC] text-(--t-3)`}
                                title={t("signalFixes.plan.unratedHint")}
                              >
                                {t("signalFixes.plan.impactUnrated")}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div
                className={cx(
                  "relative z-10 col-start-1 row-start-1 items-center justify-center p-4",
                  // SIGV2-1305: an upsell needs a positive refusal, not
                  // silence. `allowed` is false both for a plan that excludes
                  // this and for a payload that never said, and only the
                  // first justifies asking a customer to pay. QA caught a
                  // Standard customer being asked to upgrade for the action
                  // plan their plan grants.
                  //
                  // The blurred content behind this is unchanged: withholding
                  // on an unknown entitlement is the fail-safe direction, and
                  // it was only the demand for money that was unsafe.
                  !advisorPlan.allowed && advisorPlan.resolved ? "flex" : "hidden"
                )}
              >
                <SignalLockCard
                  eyebrow={advisorPlan.requiredPlan ?? ""}
                  title={t("signalFixes.plan.gateTitle")}
                  body={
                    advisorPlan.requiredPlan
                      ? t("signalFixes.plan.gateBodyPlan", { plan: advisorPlan.requiredPlan })
                      : t("signalFixes.plan.gateBody")
                  }
                  ctaLabel={
                    advisorPlan.requiredPlan
                      ? t("signalFixes.plan.gateCtaPlan", { plan: advisorPlan.requiredPlan })
                      : t("signalFixes.plan.gateCta")
                  }
                  ctaHref={advisorPlan.upgradeHref}
                />
              </div>
            </div>
          ) : (
            <div className={emptyCls}>
              <span>
                {hasScore
                  ? t("signalAioDetail.improveEmpty")
                  : t("signalAioDetail.improveEmptyNoScore")}
              </span>
            </div>
          )}
        </div>

        {/* SEARCH TYPES */}
        <div
          role="tabpanel"
          id="signal-tabpanel-types"
          aria-labelledby="signal-tab-types"
          hidden={activeTab !== "types"}
        >
          <Sec title={t("signalAioDetail.typesTitle")} mini={t("signalAioDetail.typesMini")} />
          {searchTypes.length > 0 ? (
            <div className="rounded-[22px] border-0 bg-white">
              {searchTypes.map((s, i) => {
                // Measured on this project's own AI-engine runs, or nothing.
                // The retired "Estimated" state put an audit sub-score behind
                // this label, which is a different quantity (SIGV2-1105).
                const measured = isMeasuredSearchType(s);
                const stScore = measured ? (s.score as number) : 0;
                return (
                  <div className="border-t border-t-[#F3F4F6] first:border-t-0" key={s.id}>
                    <button
                      type="button"
                      className="flex w-full cursor-pointer items-center gap-3.5 border-current px-[22px] py-4 text-left font-normal transition-colors hover:bg-[#F8FAFC] focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-[#3B82F6]"
                      aria-expanded={open === i}
                      onClick={() => setOpen(open === i ? null : i)}
                    >
                      <span
                        className="w-[52px] flex-none font-(family-name:--disp) text-[26px] font-extrabold tracking-[-0.02em] text-(--sc)"
                        style={{ "--sc": scoreColor(stScore) } as React.CSSProperties}
                      >
                        {measured ? s.score : "—"}
                      </span>
                      <span className="flex-1">
                        <span className="block font-(family-name:--disp) text-[14.5px] font-bold text-[#111827]">
                          {s.label}
                        </span>
                        <span
                          className={cx(
                            "mt-1.5 inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[10.5px] font-semibold",
                            measured
                              ? "bg-[#ECFDF5] text-[#059669]"
                              : "bg-[#EEF1F6] text-(--t-2)"
                          )}
                        >
                          <span
                            className="h-[5px] w-[5px] rounded-full bg-current"
                            aria-hidden="true"
                          />
                          {measured
                            ? t("signalOverview.measured")
                            : t("signalOverview.notMeasured")}
                        </span>
                      </span>
                      <span className="block h-1.5 w-[150px] flex-none overflow-hidden rounded-full bg-[#EEF1F6]">
                        <i
                          className="block h-full w-(--sw) origin-left rounded-full bg-(--sc) rtl:origin-right"
                          data-signal-enter="bar"
                          style={
                            {
                              "--sw": `${stScore}%`,
                              "--sc": scoreColor(stScore),
                            } as React.CSSProperties
                          }
                        />
                      </span>
                      <svg
                        className={cx(
                          "text-(--t-3) transition-transform duration-200",
                          open === i && "rotate-90"
                        )}
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth={2}
                      >
                        <path d="M9 6l6 6-6 6" />
                      </svg>
                    </button>
                    <div
                      className={cx(
                        "px-[22px] pt-0.5 pb-5 ps-[74px]",
                        open === i ? "block" : "hidden"
                      )}
                    >
                      <div className="mt-3 mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-(--t-3)">
                        {t("signalAioDetail.whyHere")}
                      </div>
                      <p className="m-0 text-[13px] leading-[1.55] text-(--t-2)">
                        {s.insight || t("signalAioDetail.noInsight")}
                      </p>
                      {/* Per-search-type improvement lists have no source: the
                          audit emits global recommendations, not keyed to a
                          type, so this slot names that rather than re-showing
                          the global list under a type heading. */}
                      <div className="mt-4 mb-1.5 text-[10.5px] font-semibold uppercase tracking-[0.06em] text-(--t-3)">
                        {t("signalAioDetail.howImprove")}
                      </div>
                      <p className={unmeasuredCls}>{t("signalAioDetail.typeActionsUnmeasured")}</p>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalAioDetail.typesEmpty")}</span>
              <Link href={deeperAuditHref} className={btnPrimaryCls}>
                {t("signalAioDetail.typesEmptyCta")}
              </Link>
            </div>
          )}
        </div>

        {/* BY ENGINE */}
        <div
          role="tabpanel"
          id="signal-tabpanel-engines"
          aria-labelledby="signal-tab-engines"
          hidden={activeTab !== "engines"}
        >
          <Sec title={t("signalAioDetail.enginesTitle")} />
          {visibilityUnavailableReason ? (
            <div className={emptyCls}>
              <span>{visibilityUnavailableReason}</span>
            </div>
          ) : engineRows.length > 0 ? (
            <div className="rounded-[22px] border-0 bg-white">
              {engineRows.map((row: VisibilityProviderBreakdown) => (
                <div
                  key={row.provider}
                  className="flex items-center gap-3.5 border-t border-t-[#F3F4F6] px-[22px] py-3.5 first:border-t-0 max-md:flex-wrap"
                >
                  {/* Keep a fixed 150px bar (SIGV2-1036): widening it blows
                      the design-comparison budget on this tab. */}
                  <span className="flex h-9 w-9 flex-none items-center justify-center rounded-[12px] bg-[#E8F1FF] text-[12px] font-bold text-[#1D4ED8]">
                    {(VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider).charAt(0)}
                  </span>
                  <span className="w-[140px] flex-none text-[13.5px] font-semibold text-[#111827] max-md:w-full">
                    {VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider}
                  </span>
                  <span className="block h-1.5 w-[150px] flex-none overflow-hidden rounded-full bg-[#EEF1F6]">
                    <i
                      className="block h-full w-(--sw) origin-left rounded-full bg-(--sc) rtl:origin-right"
                      data-signal-enter="bar"
                      style={
                        {
                          "--sw": `${row.visibility_score ?? 0}%`,
                          "--sc": scoreColor(row.visibility_score ?? 0),
                        } as React.CSSProperties
                      }
                    />
                  </span>
                  <span className="flex-1 text-[12.5px] text-(--t-2)">
                    {row.completed_checks > 0
                      ? t("signalAioDetail.citedOfChecks", {
                          cited: row.cited_checks,
                          total: row.completed_checks,
                        })
                      : t("signalAioDetail.noCompletedChecks")}
                    {/* SIGV2-1299: stand-in answers stay labelled inside this
                        note slot rather than as a new column. */}
                    {engineSources[row.provider] === "fallback" ||
                    engineSources[row.provider] === "mixed" ? (
                      <span
                        className="text-(--t-3)"
                        data-testid={`engine-standin-${row.provider}`}
                        title={t("signalAioDetail.engineStandInReason", {
                          engine: VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider,
                        })}
                      >
                        {" · "}
                        {t(
                          engineSources[row.provider] === "mixed"
                            ? "signalAioDetail.engineStandInPartial"
                            : "signalAioDetail.engineStandIn",
                          { engine: VISIBILITY_PROVIDER_LABELS[row.provider] ?? row.provider }
                        )}
                      </span>
                    ) : null}
                  </span>
                  <span
                    className="flex-none rounded-full bg-[#EEF1F6] px-2.5 py-0.5 text-[11px] font-semibold text-(--t-3)"
                    title={t("signalAioDetail.statusReason")}
                  >
                    {t("signalAioDetail.statusNotMeasured")}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className={emptyCls}>
              <span>{t("signalAioDetail.enginesEmpty")}</span>
            </div>
          )}
        </div>

        {/* PROMPTS */}
        <div
          role="tabpanel"
          id="signal-tabpanel-prompts"
          aria-labelledby="signal-tab-prompts"
          hidden={activeTab !== "prompts"}
        >
          {/* SIGV2-1194: the approved prompt-setup surface in manage mode.
              The old per-prompt results table is gone; this tab is where the
              prompt set itself is edited (add, reword, remove). */}
          <PromptSetup
            mode="manage"
            state={promptSetupState}
            project={promptSetupState.project}
            getAuthHeaders={promptAuthHeaders}
          />
        </div>
      </div>
    </div>
  );
}
